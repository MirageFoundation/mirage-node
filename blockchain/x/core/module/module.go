package core

import (
	"context"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"reflect"
	"strings"
	"time"
	"unicode/utf8"

	"cosmossdk.io/core/appmodule"
	sdkmath "cosmossdk.io/math"
	gogotypes "github.com/cosmos/gogoproto/types"

	"github.com/cosmos/cosmos-sdk/client"
	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	sdkerrors "github.com/cosmos/cosmos-sdk/types/errors"
	"github.com/cosmos/cosmos-sdk/types/module"
	"github.com/cosmos/cosmos-sdk/types/query"

	// txtypes removed; no longer needed
	"github.com/grpc-ecosystem/grpc-gateway/runtime"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"mirage/x/core/keeper"
	"mirage/x/core/types"

	"github.com/cosmos/cosmos-sdk/crypto/keys/secp256k1"

	// module names and helpers for reserved module accounts
	authtypes "github.com/cosmos/cosmos-sdk/x/auth/types"
	distrtypes "github.com/cosmos/cosmos-sdk/x/distribution/types"
	govtypes "github.com/cosmos/cosmos-sdk/x/gov/types"
	minttypes "github.com/cosmos/cosmos-sdk/x/mint/types"
	stakingtypes "github.com/cosmos/cosmos-sdk/x/staking/types"
)

var (
	_ module.AppModuleBasic = (*AppModule)(nil)
	_ module.AppModule      = (*AppModule)(nil)
	_ module.HasGenesis     = (*AppModule)(nil)

	_ appmodule.AppModule = (*AppModule)(nil)
)

const logDelimiter = "----------------------------------------------------------------------------------------------------"

// validateSafeText checks that s is valid UTF-8 and contains no control
// characters other than horizontal tab, newline, and carriage return.
// Rejects: NUL, C0 controls (\x01-\x08, \x0B, \x0C, \x0E-\x1F), DEL (\x7F).
func validateSafeText(field, s string) error {
	if !utf8.ValidString(s) {
		return fmt.Errorf("%s contains invalid UTF-8", field)
	}
	for i, r := range s {
		if r == utf8.RuneError {
			return fmt.Errorf("%s contains invalid UTF-8 at byte %d", field, i)
		}
		if r <= 0x1F && r != '\t' && r != '\n' && r != '\r' {
			return fmt.Errorf("%s contains control character 0x%02X", field, r)
		}
		if r == 0x7F {
			return fmt.Errorf("%s contains DEL character", field)
		}
	}
	return nil
}

// rejectUnsafeFields validates all provided name/value pairs are safe text.
func rejectUnsafeFields(pairs ...string) error {
	for i := 0; i < len(pairs)-1; i += 2 {
		if err := validateSafeText(pairs[i], pairs[i+1]); err != nil {
			return err
		}
	}
	return nil
}

// validateTxHash validates that a string is exactly 64 hex characters (for post/comment/vote targets)
func validateTxHash(target string) error {
	target = strings.ToLower(strings.TrimSpace(target))
	if len(target) != 64 {
		return fmt.Errorf("invalid target length: must be 64 hex characters")
	}
	for _, c := range target {
		if !((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')) {
			return fmt.Errorf("invalid target format: must be hexadecimal")
		}
	}
	return nil
}

// validateAddress validates that a string is a valid mirage address
func validateAddress(address string) error {
	address = strings.TrimSpace(address)
	if address == "" {
		return fmt.Errorf("address cannot be empty")
	}
	// Use SDK's AccAddressFromBech32 for proper bech32 validation
	_, err := sdk.AccAddressFromBech32(address)
	if err != nil {
		return fmt.Errorf("invalid bech32 address: %w", err)
	}
	return nil
}

// validateTopic enforces lowercase alphanumeric topics and max length
func validateTopic(topic string, maxLen, minLen uint64) error {
	topic = strings.TrimSpace(topic)
	if topic == "" {
		return fmt.Errorf("topic required for root posts")
	}
	if uint64(len(topic)) < minLen {
		return fmt.Errorf("topic below minimum: %d < %d", len(topic), minLen)
	}
	if uint64(len(topic)) > maxLen {
		return fmt.Errorf("topic exceeds limit: %d > %d", len(topic), maxLen)
	}
	for _, c := range topic {
		if !((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) {
			return fmt.Errorf("topic must be lowercase alphanumeric")
		}
	}
	return nil
}

// validateBlockedTopicPattern allows exact topics or glob patterns with * wildcards.
// The alphanumeric portion (with * removed) must pass validateTopic rules.
// Consecutive ** is not allowed.
func validateBlockedTopicPattern(topic string, maxLen, minLen uint64) error {
	topic = strings.TrimSpace(topic)
	if topic == "" {
		return fmt.Errorf("topic required for blocking")
	}
	if strings.Contains(topic, "**") {
		return fmt.Errorf("consecutive wildcards not allowed")
	}
	alpha := strings.ReplaceAll(topic, "*", "")
	if alpha == "" {
		return fmt.Errorf("pattern must contain alphanumeric characters")
	}
	return validateTopic(alpha, maxLen, minLen)
}

// topicMatchesPattern returns true if topic matches a glob pattern where * matches
// zero or more characters at any position.
func topicMatchesPattern(topic string, pattern string) bool {
	if !strings.Contains(pattern, "*") {
		return topic == pattern
	}
	parts := strings.Split(pattern, "*")
	// All parts must appear in order within topic
	pos := 0
	for i, part := range parts {
		if part == "" {
			continue
		}
		idx := strings.Index(topic[pos:], part)
		if idx < 0 {
			return false
		}
		// First part must match at start if pattern doesn't start with *
		if i == 0 && idx != 0 {
			return false
		}
		pos += idx + len(part)
	}
	// Last part must match at end if pattern doesn't end with *
	if len(parts) > 0 && parts[len(parts)-1] != "" {
		return strings.HasSuffix(topic, parts[len(parts)-1])
	}
	return true
}

// allowedTags is the whitelist of valid tag values
var allowedTags = map[string]bool{
	"":          true,
	"sensitive": true,
	"adult":     true,
	"gore":      true,
	"violence":  true,
	"death":     true,
}

// tagAliases maps deprecated tag names to their canonical replacements.
// TODO: remove "porn" alias once all clients send "adult".
var tagAliases = map[string]string{
	"porn": "adult",
}

// normalizeTag returns the canonical form of a tag (applying aliases).
func normalizeTag(tag string) string {
	tag = strings.TrimSpace(tag)
	if canonical, ok := tagAliases[tag]; ok {
		return canonical
	}
	return tag
}

// validateTag validates the content tag field
func validateTag(tag string) error {
	tag = normalizeTag(tag)
	if len(tag) > 50 {
		return fmt.Errorf("tag exceeds limit: %d > 50", len(tag))
	}
	if !allowedTags[tag] {
		return fmt.Errorf("invalid tag: %s", tag)
	}
	return nil
}

// deriveOwnerFromPubkey extracts owner address from a compressed pubkey
func deriveOwnerFromPubkey(pubkey []byte) (string, error) {
	if len(pubkey) != 33 {
		return "", fmt.Errorf("invalid pubkey length: expected 33, got %d", len(pubkey))
	}
	pub := secp256k1.PubKey{Key: pubkey}
	return sdk.AccAddress(pub.Address()).String(), nil
}

// requireUsername loads ProfileCore for owner and fails hard if the profile
// is missing or has no username set. Returns (ProfileCore, nil) on success.
// Governance callers must skip this check before calling.
func (am AppModule) requireUsername(sdkCtx sdk.Context, owner, action string) (types.ProfileCore, error) {
	bz, found, err := am.k.GetProfileCore(sdkCtx, owner)
	if err != nil {
		return types.ProfileCore{}, fmt.Errorf("failed to load profile: %w", err)
	}
	if !found {
		sdkCtx.Logger().Debug("requireUsername: no profile", "owner", owner, "action", action)
		return types.ProfileCore{}, fmt.Errorf("username required: no profile found for %s", owner)
	}
	var core types.ProfileCore
	if err := json.Unmarshal(bz, &core); err != nil {
		return types.ProfileCore{}, fmt.Errorf("failed to unmarshal profile: %w", err)
	}
	if core.Username == "" {
		sdkCtx.Logger().Debug("requireUsername: empty username", "owner", owner, "action", action)
		return types.ProfileCore{}, fmt.Errorf("username required: set a username before calling %s", action)
	}
	return core, nil
}

// validateAndDeductFee checks minimum fee and deducts from owner
func (am AppModule) validateAndDeductFee(ctx sdk.Context, owner string, feeAmt, minFee uint64) error {
	if feeAmt == 0 {
		return nil
	}
	if feeAmt < minFee {
		return fmt.Errorf("fee below minimum: need >= %d umirage", minFee)
	}
	if err := am.k.DeductFeeFromOwner(ctx, owner, feeAmt); err != nil {
		return fmt.Errorf("fee deduction failed: %w", err)
	}
	return nil
}

// calculateRelayFee computes the fee based on gas consumed and min gas price.
// fee = gasConsumed * minGasPrice, capped at maxGasFee.
func calculateRelayFee(gasConsumed, minGasPrice, maxGasFee uint64) uint64 {
	// Fee = gasConsumed * minGasPrice (minGasPrice is umirage per gas unit)
	// Check for overflow before multiplication
	if gasConsumed > 0 && minGasPrice > math.MaxUint64/gasConsumed {
		return maxGasFee // Would overflow, return max
	}
	fee := gasConsumed * minGasPrice

	// Cap at maximum
	if fee > maxGasFee {
		fee = maxGasFee
	}
	return fee
}

// deductRelayGasFee deducts gas fee from paid users (level >= 1) using their escrowed reserve.
// Fee = gasUsed * relayMinGasPrice, capped at relayMaxGasFee.
// relayMinGasPrice is in umirage per gas unit (e.g., 5000 = 5000 umirage per gas).
// Only deducts from users with level >= 1; free users (level 0) use PoW instead.
// If reserve is insufficient, burns remainder, zeros reserve, and downgrades user to level 0.
func (am AppModule) deductRelayGasFee(ctx sdk.Context, owner string, userLevel int, gasUsed uint64, reason string) error {
	// Only charge paid users (level >= 1)
	if userLevel < 1 {
		return nil
	}

	params := am.k.GetParams(ctx)
	minGasPrice := params.RelayMinGasPrice
	maxGasFee := params.RelayMaxGasFee

	// Calculate fee based on gas used for this message
	fee := calculateRelayFee(gasUsed, minGasPrice, maxGasFee)

	if fee == 0 {
		return nil
	}

	// Special rule for admins (level >= 100): deduct gas directly from on-chain balance,
	// never from reserve and never downgrade. If balance is insufficient, skip deduction
	// but let the tx through -- admin operations should never be blocked over gas fees.
	//
	// ADR: docs/architecture/adr-mint-log-and-continue.md — intentional
	// log-and-continue (not CONSENSUS_FATAL) for insufficient admin balance;
	// liveness preferred after the 2026-07-12 full-chain halt.
	//
	// The waiver covers insufficient funds only. Treating every error as an
	// empty balance meant a node-local bank/store failure skipped the deduction
	// here while peers deducted and burned (review L-10).
	if userLevel >= 100 {
		if err := am.k.DeductFeeFromOwner(ctx, owner, fee); err != nil {
			if !errors.Is(err, sdkerrors.ErrInsufficientFunds) {
				return fmt.Errorf("relay gas fee (admin): deduct from %s failed: %w", owner, err)
			}
			ctx.Logger().Warn("relay gas fee (admin): insufficient balance, skipping deduction",
				"owner", owner,
				"level", userLevel,
				"reason", reason,
				"gas_used", gasUsed,
				"fee", fee,
				"err", err)
			return nil
		}
		if err := am.k.BurnFromModuleAmount(ctx, fee); err != nil {
			return fmt.Errorf("relay gas fee (admin): burn from module failed: %w", err)
		} else {
			ctx.Logger().Info("relay gas fee deducted from admin balance",
				"owner", owner,
				"level", userLevel,
				"reason", reason,
				"gas_used", gasUsed,
				"fee", fee,
				"min_gas_price", minGasPrice,
				"max_gas_fee", maxGasFee)
		}
		return nil
	}

	// Load profile core to access reserve.
	// FAIL-FAST: a paid user (level >= 1) without a readable profile is a
	// state inconsistency. Silently skipping the fee deduction on this node
	// while peers (with intact state) deduct correctly produces a per-node
	// state divergence -> app-hash divergence on the next consensus round.
	// Returning the error rejects the tx; the same corrupt bytes on all
	// peers reject identically, so consensus is preserved.
	bz, found, err := am.k.GetProfileCore(ctx, owner)
	if err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:PROFILE_GET deductRelayGasFee owner=%s: %w", owner, err)
	}
	if !found {
		return fmt.Errorf("CONSENSUS_FATAL:PROFILE_MISSING deductRelayGasFee owner=%s level=%d: paid user has no profile", owner, userLevel)
	}

	var core types.ProfileCore
	if err := json.Unmarshal(bz, &core); err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:PROFILE_DECODE deductRelayGasFee owner=%s bytes=%d: %w", owner, len(bz), err)
	}

	// Deduct from reserve
	if core.ReserveFunds >= fee {
		// Sufficient reserve: deduct and burn from module
		reserveBefore := core.ReserveFunds
		core.ReserveFunds -= fee
		if err := am.k.BurnFromModuleAmount(ctx, fee); err != nil {
			return fmt.Errorf("deductRelayGasFee: burn from module failed: %w", err)
		}
		ctx.Logger().Info("relay gas fee deducted from reserve",
			"owner", owner,
			"level", userLevel,
			"reason", reason,
			"gas_used", gasUsed,
			"fee", fee,
			"min_gas_price", minGasPrice,
			"max_gas_fee", maxGasFee,
			"reserve_before", reserveBefore,
			"reserve_remaining", core.ReserveFunds)
	} else {
		// Insufficient reserve: burn whatever is left, then downgrade
		previousLevel := core.Level
		reserveBefore := core.ReserveFunds
		if core.ReserveFunds > 0 {
			if err := am.k.BurnFromModuleAmount(ctx, core.ReserveFunds); err != nil {
				return fmt.Errorf("deductRelayGasFee: burn remaining reserve failed: %w", err)
			}
		}
		ctx.Logger().Info("deductRelayGasFee: reserve exhausted, downgrading to free",
			"owner", owner,
			"level", core.Level,
			"reason", reason,
			"gas_used", gasUsed,
			"fee", fee,
			"min_gas_price", minGasPrice,
			"max_gas_fee", maxGasFee,
			"reserve_before", reserveBefore,
			"reserve_was", core.ReserveFunds)

		// Remove subscription index
		if core.SubscriptionExpiry > 0 {
			if err := am.k.RemoveSubscription(ctx, owner, core.SubscriptionExpiry); err != nil {
				return fmt.Errorf("deductRelayGasFee: remove subscription failed for %s: %w", owner, err)
			}
		}

		// Downgrade to free tier
		core.ReserveFunds = 0
		core.Level = 0
		core.SubscriptionExpiry = 0
		core.AutoRenew = false

		// Emit event so the indexer updates the user's level
		ctx.EventManager().EmitEvent(
			sdk.NewEvent(
				"subscription_expired",
				sdk.NewAttribute("address", owner),
				sdk.NewAttribute("previous_level", fmt.Sprintf("%d", previousLevel)),
				sdk.NewAttribute("reason", "reserve_exhausted"),
			),
		)
	}

	// Save updated profile
	newBz, err := json.Marshal(core)
	if err != nil {
		return fmt.Errorf("deductRelayGasFee: failed to marshal profile for %s: %w", owner, err)
	}
	if err := am.k.SetProfileCore(ctx, owner, newBz); err != nil {
		return fmt.Errorf("deductRelayGasFee: failed to save profile for %s: %w", owner, err)
	}
	return nil
}

// AppModule implements the AppModule interface for the minimal core module.
type AppModule struct {
	cdc codec.Codec
	k   keeper.Keeper
}

func NewAppModule(cdc codec.Codec, k keeper.Keeper) AppModule { return AppModule{cdc: cdc, k: k} }

// IsAppModule implements the appmodule.AppModule interface.
func (AppModule) IsAppModule() {}

// Name returns the module name.
func (AppModule) Name() string { return types.ModuleName }

// RegisterLegacyAminoCodec registers amino codec (unused).
func (AppModule) RegisterLegacyAminoCodec(*codec.LegacyAmino) {}

// RegisterGRPCGatewayRoutes registers gRPC Gateway routes.
func (AppModule) RegisterGRPCGatewayRoutes(clientCtx client.Context, mux *runtime.ServeMux) {
	if err := types.RegisterQueryHandlerClient(clientCtx.CmdContext, mux, types.NewQueryClient(clientCtx)); err != nil {
		panic(err)
	}
}

// RegisterInterfaces registers interfaces.
func (AppModule) RegisterInterfaces(registrar codectypes.InterfaceRegistry) {
	types.RegisterInterfaces(registrar)
}

// RegisterServices registers Msg/Query servers.
func (am AppModule) RegisterServices(registrar grpc.ServiceRegistrar) error {
	types.RegisterQueryServer(registrar, am)
	types.RegisterMsgServer(registrar, am)
	return nil
}

// DefaultGenesis returns default genesis state.
func (am AppModule) DefaultGenesis(codec.JSONCodec) json.RawMessage {
	return am.cdc.MustMarshalJSON(types.DefaultGenesis())
}

// ValidateGenesis validates genesis state.
func (am AppModule) ValidateGenesis(_ codec.JSONCodec, _ client.TxEncodingConfig, bz json.RawMessage) error {
	var genState types.GenesisState
	if err := am.cdc.UnmarshalJSON(bz, &genState); err != nil {
		return fmt.Errorf("failed to unmarshal %s genesis state: %w", types.ModuleName, err)
	}
	// Default params if missing in genesis
	p := genState.Params
	if p.MinDifficulty == 0 || p.PowMessageWindow == 0 || p.MintInterval == 0 || p.MintQuantity == 0 || p.BlockHashWindow == 0 {
		genState.Params = types.DefaultParams()
	}
	return genState.Validate()
}

// reservedModuleAccountNames returns the list of module account names to reserve usernames for.
func reservedModuleAccountNames() []string {
	return []string{
		authtypes.FeeCollectorName,
		distrtypes.ModuleName,
		minttypes.ModuleName,
		stakingtypes.BondedPoolName,
		stakingtypes.NotBondedPoolName,
		govtypes.ModuleName,
		types.ModuleName, // core module account
	}
}

func reservedUsernameForModule(modName string) string {
	// enforce kebab-case: replace underscores with hyphens
	return "mirage-" + strings.ReplaceAll(modName, "_", "-")
}

// InitGenesis initializes state from genesis; reserve usernames for module accounts.
func (am AppModule) InitGenesis(sdkCtx sdk.Context, _ codec.JSONCodec, gs json.RawMessage) {
	// Reserve usernames for well-known module accounts with the `mirage-` prefix
	for _, modName := range reservedModuleAccountNames() {
		addr := authtypes.NewModuleAddress(modName).String()
		username := reservedUsernameForModule(modName)

		if err := am.k.ClaimUsername(sdkCtx, username, addr); err != nil {
			sdkCtx.Logger().Warn("InitGenesis: ClaimUsername failed (may already exist)", "username", username, "err", err)
		}

		core := types.ProfileCore{Owner: addr, Username: username}
		bz, err := json.Marshal(core)
		if err != nil {
			panic(fmt.Errorf("InitGenesis: marshal module profile failed: %w", err))
		}
		if err := am.k.SetProfileCore(sdkCtx, addr, bz); err != nil {
			panic(fmt.Errorf("InitGenesis: SetProfileCore for module %s failed: %w", modName, err))
		}
	}

	// Initialize params from genesis
	var genState types.GenesisState
	if err := am.cdc.UnmarshalJSON(gs, &genState); err != nil {
		panic(fmt.Errorf("failed to unmarshal core genesis state: %w", err))
	}
	p := genState.Params
	if p.MinDifficulty == 0 || p.PowMessageWindow == 0 || p.MintInterval == 0 || p.MintQuantity == 0 || p.BlockHashWindow == 0 {
		p = types.DefaultParams()
	}
	// subscription_reserve_bps is substituted on its own rather than joining the
	// all-or-nothing test above, which would discard every deliberately-set value
	// in the genesis file alongside it.
	//
	// Zero is legal to Validate() (the bound is an upper one) but it short-circuits
	// the reserve split, so all three call sites burn the entire period fee and
	// escrow nothing: the user reaches level 1 with an empty reserve and is demoted
	// on their next relay message. Full fee in, instant demotion, no service.
	//
	// This is not hypothetical. The shipped genesis params carried no
	// subscription_reserve_bps key at all, so proto3 decoded it as 0 and every
	// chain started from that file — a reset_local_testnet.py run, a new
	// deployment, a from-genesis replay — ran inverted until the v1.34.0 handler
	// executed. Fixed here rather than in Validate() for the replay reason
	// documented on MinBlockHashWindow.
	if p.SubscriptionReserveBps == 0 {
		p.SubscriptionReserveBps = types.DefaultParams().SubscriptionReserveBps
		sdkCtx.Logger().Info("InitGenesis: substituted default subscription_reserve_bps",
			"value", p.SubscriptionReserveBps)
	}
	if err := am.k.SetParams(sdkCtx, p); err != nil {
		panic(fmt.Errorf("InitGenesis: SetParams failed: %w", err))
	}

	// Import raw state if present (complete KV store restore from export)
	if len(genState.RawState) > 0 {
		for _, kv := range genState.RawState {
			key, err := base64.StdEncoding.DecodeString(kv.Key)
			if err != nil {
				panic(fmt.Errorf("InitGenesis: base64 decode key failed: %w", err))
			}
			value, err := base64.StdEncoding.DecodeString(kv.Value)
			if err != nil {
				panic(fmt.Errorf("InitGenesis: base64 decode value failed: %w", err))
			}
			if err := am.k.SetRawKVPair(sdkCtx, key, value); err != nil {
				panic(fmt.Errorf("InitGenesis: SetRawKVPair failed: %w", err))
			}
		}
	}

	// Create any initial profiles specified in genesis (e.g., validators, faucet)
	for _, ip := range genState.InitialProfiles {
		if ip.Core == nil {
			continue
		}
		owner := strings.TrimSpace(ip.Core.Owner)
		username := strings.TrimSpace(ip.Core.Username)
		if owner == "" {
			continue
		}
		if username != "" {
			if err := am.k.ClaimUsername(sdkCtx, username, owner); err != nil {
				sdkCtx.Logger().Warn("InitGenesis: ClaimUsername failed", "username", username, "err", err)
			}
		}
		_, hasProfile, err := am.k.GetProfileCore(sdkCtx, owner)
		if err != nil {
			panic(fmt.Errorf("InitGenesis: load profile for %s failed: %w", owner, err))
		}
		if !hasProfile {
			bz, err := json.Marshal(ip.Core)
			if err != nil {
				panic(fmt.Errorf("InitGenesis: marshal profile for %s failed: %w", owner, err))
			}
			if err := am.k.SetProfileCore(sdkCtx, owner, bz); err != nil {
				panic(fmt.Errorf("InitGenesis: SetProfileCore for %s failed: %w", owner, err))
			}
		}

		if len(ip.EnabledAgents) > 0 {
			if err := am.k.ReplaceAllEnabledAgents(sdkCtx, owner, ip.EnabledAgents); err != nil {
				panic(fmt.Errorf("InitGenesis: ReplaceAllEnabledAgents for %s failed: %w", owner, err))
			}
		}
		for _, u := range ip.FollowedUsers {
			if _, err := am.k.AddFollowedUser(sdkCtx, owner, u); err != nil {
				panic(fmt.Errorf("InitGenesis: AddFollowedUser for %s failed: %w", owner, err))
			}
		}
		for _, t := range ip.FollowedTopics {
			if _, err := am.k.AddFollowedTopic(sdkCtx, owner, t); err != nil {
				panic(fmt.Errorf("InitGenesis: AddFollowedTopic for %s failed: %w", owner, err))
			}
		}
		for _, u := range ip.BlockedUsers {
			if _, err := am.k.AddBlockedUserDeque(sdkCtx, owner, u, 0); err != nil {
				panic(fmt.Errorf("InitGenesis: AddBlockedUserDeque for %s failed: %w", owner, err))
			}
		}
		for _, p := range ip.BlockedPosts {
			if _, err := am.k.AddBlockedPostDeque(sdkCtx, owner, p, 0); err != nil {
				panic(fmt.Errorf("InitGenesis: AddBlockedPostDeque for %s failed: %w", owner, err))
			}
		}
		for _, t := range ip.BlockedTopics {
			if _, err := am.k.AddBlockedTopicDeque(sdkCtx, owner, t, 0); err != nil {
				panic(fmt.Errorf("InitGenesis: AddBlockedTopicDeque for %s failed: %w", owner, err))
			}
		}
	}
}

// ExportGenesis exports genesis state including params and ALL KV pairs from the store.
// This ensures complete state export without needing to update code for new prefixes.
func (am AppModule) ExportGenesis(sdkCtx sdk.Context, _ codec.JSONCodec) json.RawMessage {
	gs := types.GenesisState{Params: am.k.GetParams(sdkCtx)}

	// Export ALL key-value pairs from the store
	rawState, err := am.k.GetAllKVPairs(sdkCtx)
	if err != nil {
		panic(fmt.Errorf("failed to get KV pairs for export: %w", err))
	}
	gs.RawState = rawState

	bz, err := am.cdc.MarshalJSON(&gs)
	if err != nil {
		panic(fmt.Errorf("failed to marshal %s genesis state: %w", types.ModuleName, err))
	}
	return bz
}

// ConsensusVersion returns module consensus version.
func (AppModule) ConsensusVersion() uint64 { return 1 }

// BeginBlock runs consensus-critical housekeeping: burn fee collector,
// maybe-mint + distribute rewards, initialize difficulty on first run,
// record the previous block's hash in the on-chain recent-block-hashes
// window, one-shot reserved module profile bootstrap, and periodically
// clean up counters.
//
// FAIL-FAST CONTRACT (consensus-critical writes only):
// RecordRecentBlockHash failures and the one-shot reserved-profile
// bootstrap (when the sentinel is unset) propagate as a non-nil return,
// which the SDK turns into a chain halt. The on-chain recent-block-hashes
// window is consensus-critical state read by the PoW ante; a per-node
// write failure here would cause per-node tx-acceptance divergence on
// subsequent blocks, which is strictly worse than a clean halt
// detected by the auto-recovery watchdog.
//
// Difficulty initialization and CleanupOldCounters also propagate: both
// write state that later blocks read to make consensus decisions, and a
// store failure is node-local, not fleet-wide (review M-5, M-6).
//
// Fee-collector burns and mint distribution propagate as well. Both change
// balances and supply, so a node-local failure cannot safely be retried in a
// later block while peers commit the successful transition now.
func (am AppModule) BeginBlock(ctx context.Context) error {
	sdkCtx := sdk.UnwrapSDKContext(ctx)

	// M-2: capture the baseline before core's mint/burn operations. x/mint runs
	// earlier in BeginBlock and is intentionally part of this baseline; the
	// full supply-vs-balances scan below covers all modules every block.
	if err := am.k.CaptureBlockSupplyStart(sdkCtx); err != nil {
		sdkCtx.Logger().Error("CONSENSUS_FATAL:SUPPLY_START_CAPTURE BeginBlock; halting chain (auto-recovery will state-sync)",
			"height", sdkCtx.BlockHeight(), "err", err)
		return err
	}

	if err := am.k.BurnAllFromModuleName(sdkCtx, authtypes.FeeCollectorName); err != nil {
		sdkCtx.Logger().Error("CONSENSUS_FATAL:FEE_COLLECTOR_BURN BeginBlock; halting chain (auto-recovery will state-sync)",
			"height", sdkCtx.BlockHeight(), "err", err)
		return err
	}
	// NOTE: Do NOT burn the core module account balance here. It holds user reserve funds.
	if err := am.k.MintIfNeeded(sdkCtx); err != nil {
		sdkCtx.Logger().Error("CONSENSUS_FATAL:MINT_DISTRIBUTION BeginBlock; halting chain (auto-recovery will state-sync)",
			"height", sdkCtx.BlockHeight(), "err", err)
		return err
	}

	// Initialize difficulty if not set (base step = 0). The PoW ante reads
	// this every transaction, so a node that fails the write admits work at a
	// different difficulty than its peers.
	params := am.k.GetParams(sdkCtx)
	if !am.k.HasCurrentDifficulty(sdkCtx) {
		if err := am.k.SetCurrentDifficulty(sdkCtx, keeper.BaseDifficultySteps); err != nil {
			sdkCtx.Logger().Error("CONSENSUS_FATAL:DIFFICULTY_INIT BeginBlock; halting chain (auto-recovery will state-sync)",
				"height", sdkCtx.BlockHeight(), "err", err)
			return err
		}
	}

	// Record this block's hash into the on-chain recent-block-hashes window.
	// This is consensus-critical state used by the PoW ante to validate that an
	// envelope's last_block_hash references a recent committed block. The window
	// MUST be identical across all nodes; a state-write failure here causes
	// per-node window divergence -> later per-node tx-acceptance divergence ->
	// app-hash divergence. Halt the chain via the propagated error so the
	// auto-recovery watchdog can state-sync from healthy peers.
	//
	// The source is HeaderHash, not BlockHeader().LastBlockId.Hash: under ABCI
	// 2.0 FinalizeBlock carries no LastBlockId, so the old source was empty on
	// every path and the window filled with empty strings, leaving envelope
	// staleness unenforced (retest L-7). baseapp sets HeaderHash from
	// RequestFinalizeBlock.Hash for both the finalize and the CheckTx state, so
	// it is populated and identical fleet-wide. A client can only ever have seen
	// an already-committed block, so recording the current hash keeps the window
	// a superset of what any honest envelope can reference.
	blockHash := strings.ToLower(hex.EncodeToString(sdkCtx.HeaderHash()))
	if blockHash == "" {
		// Genesis/InitChain has no block hash yet. Recording nothing keeps the
		// window free of empty entries, which is what the ante treats as
		// "window not ready" while it bootstraps.
		sdkCtx.Logger().Debug("recent-block-hashes: empty HeaderHash, nothing recorded",
			"height", sdkCtx.BlockHeight())
	} else if err := am.k.RecordRecentBlockHash(sdkCtx, blockHash, uint32(params.BlockHashWindow)); err != nil {
		sdkCtx.Logger().Error("CONSENSUS_FATAL:RECENT_HASHES_WRITE BeginBlock; halting chain (auto-recovery will state-sync)",
			"height", sdkCtx.BlockHeight(), "err", err)
		return err
	}

	// One-shot bootstrap of reserved module-account profiles. Gated by a
	// sentinel so this never re-runs after the first successful pass —
	// avoiding a per-block fail-fast opportunity (review M-6).
	bootstrapped, err := am.k.HasReservedProfilesBootstrapped(sdkCtx)
	if err != nil {
		return fmt.Errorf("CONSENSUS_FATAL:RESERVED_PROFILES_SENTINEL_GET height=%d: %w", sdkCtx.BlockHeight(), err)
	}
	if !bootstrapped {
		for _, modName := range reservedModuleAccountNames() {
			addr := authtypes.NewModuleAddress(modName).String()
			_, found, gerr := am.k.GetProfileCore(sdkCtx, addr)
			if gerr != nil {
				return fmt.Errorf("CONSENSUS_FATAL:RESERVED_PROFILE_GET module=%s addr=%s: %w", modName, addr, gerr)
			}
			if found {
				continue
			}
			username := reservedUsernameForModule(modName)
			if err := am.k.ClaimUsername(sdkCtx, username, addr); err != nil {
				return fmt.Errorf("CONSENSUS_FATAL:RESERVED_PROFILE_CLAIM_USERNAME module=%s username=%s: %w", modName, username, err)
			}
			bz, merr := json.Marshal(types.ProfileCore{Owner: addr, Username: username})
			if merr != nil {
				return fmt.Errorf("CONSENSUS_FATAL:RESERVED_PROFILE_MARSHAL module=%s: %w", modName, merr)
			}
			if err := am.k.SetProfileCore(sdkCtx, addr, bz); err != nil {
				return fmt.Errorf("CONSENSUS_FATAL:RESERVED_PROFILE_SET module=%s addr=%s: %w", modName, addr, err)
			}
			sdkCtx.Logger().Info("BeginBlock: bootstrapped reserved module profile",
				"module", modName, "addr", addr, "username", username)
		}
		if err := am.k.SetReservedProfilesBootstrapped(sdkCtx); err != nil {
			return fmt.Errorf("CONSENSUS_FATAL:RESERVED_PROFILES_SENTINEL_SET height=%d: %w", sdkCtx.BlockHeight(), err)
		}
		sdkCtx.Logger().Info("BeginBlock: reserved module profiles bootstrap complete; sentinel set")
	}

	// Faucet username is set during network bootstrap via a direct tx.

	// Cleanup old counters periodically (every 100 blocks). The sweep deletes
	// committed keys and advances a stored cursor, so a node that skips or
	// mis-starts a sweep commits a different keyset than its peers.
	if sdkCtx.BlockHeight()%100 == 0 {
		if err := am.k.CleanupOldCounters(sdkCtx, params); err != nil {
			sdkCtx.Logger().Error("CONSENSUS_FATAL:POW_COUNTER_CLEANUP BeginBlock; halting chain (auto-recovery will state-sync)",
				"height", sdkCtx.BlockHeight(), "err", err)
			return err
		}
	}

	return nil
}

// EndBlock adjusts PoW difficulty based on message volume and processes subscription renewals.
//
// FAIL-FAST CONTRACT (consensus-critical decode paths only):
// CONSENSUS_FATAL errors from processSubscriptions (corrupt or missing
// ProfileCore for an expired subscription) propagate as a non-nil return,
// which the SDK turns into a chain halt. This is strictly safer than the
// prior "log and continue" behavior: silently skipping a renewal/expiry on
// one node while peers process it correctly produces a per-node app-hash
// divergence that is invisible until the next consensus round. A clean halt
// is detected by the auto-recovery watchdog and state-synced from healthy
// peers.
//
// Difficulty, PoW-window, and calm-sequence writes also propagate. Every one
// of them is an input to a later block's difficulty decision or to ante
// admission, and a store failure is node-local rather than fleet-wide
// (review M-5, L-2, L-3).
//
// Expired-nonce pruning also propagates: HasEnvelopeNonce checks nonce-key
// presence, so a failed delete on one node would make it reject a fresh
// envelope reusing that nonce while peers accept it.
func (am AppModule) EndBlock(ctx context.Context) error {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	params := am.k.GetParams(sdkCtx)

	if pruned, err := am.k.PruneExpiredNonces(sdkCtx, sdkCtx.BlockTime().Unix()); err != nil {
		sdkCtx.Logger().Error("CONSENSUS_FATAL:ENVELOPE_NONCE_PRUNE EndBlock; halting chain (auto-recovery will state-sync)",
			"height", sdkCtx.BlockHeight(), "err", err)
		return err
	} else if pruned > 0 {
		sdkCtx.Logger().Debug("EndBlock: pruned expired nonces", "count", pruned)
	}

	// Process subscription renewals/expirations. CONSENSUS_FATAL decode
	// failures propagate to halt the chain rather than silently diverge.
	if err := am.processSubscriptions(sdkCtx, params); err != nil {
		sdkCtx.Logger().Error("EndBlock: processSubscriptions returned error; propagating to halt chain (auto-recovery will state-sync)",
			"height", sdkCtx.BlockHeight(), "err", err)
		return err
	}

	// The O(1) delta check catches missed or duplicated supply updates. It cannot
	// prove that the matching account-balance write happened, so the full
	// supply-vs-balances scan must still run every block: that is the guard that
	// caught the 2026-06-12 stale-read divergence.
	if err := am.k.AssertSupplyDeltaInvariant(sdkCtx); err != nil {
		sdkCtx.Logger().Error("CONSENSUS_FATAL:SUPPLY_DELTA_INVARIANT EndBlock; halting chain (auto-recovery will state-sync)",
			"height", sdkCtx.BlockHeight(), "err", err)
		return err
	}
	// The full scan is O(accounts) and, unlike the delta check, its cost is
	// charged to no transaction — while the set it walks is user-growable and
	// irreversible: MsgSendTokens moves as little as 1 umirage to any valid
	// bech32 address with no existence requirement, x/bank deletes only zero
	// balances, and nothing sweeps dust for addresses that have no profile. Each
	// such transfer is paid for once and adds one permanent entry that every
	// future block had to walk, forever, with no ceiling (review M-5).
	//
	// So it now runs periodically rather than every block. The height test is a
	// pure function of the block height, so every validator scans at exactly the
	// same heights and nothing about this is non-deterministic. The cost is a
	// bounded detection delay of at most SupplyFullScanInterval blocks for the
	// one fault class the delta check cannot see (a supply write paired with a
	// missing balance write); the node still halts, and recovery is a state-sync
	// either way.
	if sdkCtx.BlockHeight()%types.SupplyFullScanInterval == 0 {
		scanStart := time.Now()
		if err := am.k.AssertSupplyInvariant(sdkCtx); err != nil {
			sdkCtx.Logger().Error("CONSENSUS_FATAL:SUPPLY_INVARIANT EndBlock; halting chain (auto-recovery will state-sync)",
				"height", sdkCtx.BlockHeight(), "err", err)
			return err
		}
		// Same cadence, same reason: O(profiles) and charged to no transaction.
		// This asserts what the review could previously only argue from
		// inspection — that the core module account can pay every reserve it has
		// recorded, with no other module draining it out-of-band.
		if err := am.k.AssertModuleSolvencyInvariant(sdkCtx); err != nil {
			sdkCtx.Logger().Error("CONSENSUS_FATAL:MODULE_SOLVENCY_INVARIANT EndBlock; halting chain (auto-recovery will state-sync)",
				"height", sdkCtx.BlockHeight(), "err", err)
			return err
		}
		sdkCtx.Logger().Info("supply full scan complete",
			"height", sdkCtx.BlockHeight(),
			"elapsed_ms", time.Since(scanStart).Milliseconds())
	}

	currentDifficulty := am.k.GetCurrentDifficulty(sdkCtx)

	// Sliding-window message count over last PowMessageWindow blocks
	messageCount := am.k.GetPoWMessageCount(sdkCtx, params)
	calmSeq := am.k.GetConsecutiveLowUsage(sdkCtx)

	sdkCtx.Logger().Debug("PoW difficulty status",
		"block", sdkCtx.BlockHeight(),
		"current_difficulty", currentDifficulty,
		"messages_in_window", messageCount,
		"calm_sequence", calmSeq,
	)

	// Busy window: increase difficulty by 1 step and reset calm sequence
	if messageCount >= params.PowMessageLimit {
		newDifficulty := currentDifficulty + 1
		if newDifficulty > keeper.MaxSafeDifficultySteps {
			newDifficulty = keeper.MaxSafeDifficultySteps
		}
		if newDifficulty != currentDifficulty {
			if err := am.k.SetCurrentDifficulty(sdkCtx, newDifficulty); err != nil {
				sdkCtx.Logger().Error("CONSENSUS_FATAL:DIFFICULTY_BUSY_INCREASE EndBlock; halting chain (auto-recovery will state-sync)",
					"height", sdkCtx.BlockHeight(), "old", currentDifficulty, "new", newDifficulty, "err", err)
				return err
			}
			if err := am.k.ClearPoWWindow(sdkCtx, params); err != nil {
				sdkCtx.Logger().Error("CONSENSUS_FATAL:POW_WINDOW_CLEAR_BUSY EndBlock; halting chain (auto-recovery will state-sync)",
					"height", sdkCtx.BlockHeight(), "err", err)
				return err
			}
			sdkCtx.Logger().Info("Increased PoW difficulty due to busy window",
				"old_difficulty", currentDifficulty, "new_difficulty", newDifficulty)
		}
		if err := am.k.SetConsecutiveLowUsage(sdkCtx, 0); err != nil {
			sdkCtx.Logger().Error("CONSENSUS_FATAL:CALM_SEQUENCE_RESET_BUSY EndBlock; halting chain (auto-recovery will state-sync)",
				"height", sdkCtx.BlockHeight(), "err", err)
			return err
		}
		return nil
	}

	// Calm window: increment consecutive calm sequence
	if messageCount < params.PowCalmPeriodDefinition {
		nextCalmSeq, err := types.CheckedAddUint64(calmSeq, 1)
		if err != nil {
			return fmt.Errorf("CONSENSUS_FATAL:CALM_SEQUENCE_OVERFLOW height=%d: %w",
				sdkCtx.BlockHeight(), err)
		}
		calmSeq = nextCalmSeq
		if err := am.k.SetConsecutiveLowUsage(sdkCtx, calmSeq); err != nil {
			sdkCtx.Logger().Error("CONSENSUS_FATAL:CALM_SEQUENCE_INCREMENT EndBlock; halting chain (auto-recovery will state-sync)",
				"height", sdkCtx.BlockHeight(), "calm_seq", calmSeq, "err", err)
			return err
		}
		if calmSeq >= params.PowCalmSequenceThreshold {
			newDifficulty := currentDifficulty
			if currentDifficulty > keeper.BaseDifficultySteps {
				newDifficulty = currentDifficulty - 1
			}
			if newDifficulty != currentDifficulty {
				if err := am.k.SetCurrentDifficulty(sdkCtx, newDifficulty); err != nil {
					sdkCtx.Logger().Error("CONSENSUS_FATAL:DIFFICULTY_CALM_DECREASE EndBlock; halting chain (auto-recovery will state-sync)",
						"height", sdkCtx.BlockHeight(), "old", currentDifficulty, "new", newDifficulty, "err", err)
					return err
				}
				if err := am.k.ClearPoWWindow(sdkCtx, params); err != nil {
					sdkCtx.Logger().Error("CONSENSUS_FATAL:POW_WINDOW_CLEAR_CALM EndBlock; halting chain (auto-recovery will state-sync)",
						"height", sdkCtx.BlockHeight(), "err", err)
					return err
				}
				sdkCtx.Logger().Info("Decreased PoW difficulty due to calm sequence",
					"old_difficulty", currentDifficulty, "new_difficulty", newDifficulty,
					"calm_sequence", calmSeq)
			}
			// reset sequence after decreasing
			if err := am.k.SetConsecutiveLowUsage(sdkCtx, 0); err != nil {
				sdkCtx.Logger().Error("CONSENSUS_FATAL:CALM_SEQUENCE_RESET_CALM EndBlock; halting chain (auto-recovery will state-sync)",
					"height", sdkCtx.BlockHeight(), "err", err)
				return err
			}
		}
		return nil
	}

	// Neither busy nor calm → reset sequence
	if calmSeq > 0 {
		if err := am.k.SetConsecutiveLowUsage(sdkCtx, 0); err != nil {
			sdkCtx.Logger().Error("CONSENSUS_FATAL:CALM_SEQUENCE_RESET_NEUTRAL EndBlock; halting chain (auto-recovery will state-sync)",
				"height", sdkCtx.BlockHeight(), "err", err)
			return err
		}
	}
	return nil
}

// processSubscriptions handles subscription renewals and expirations
func (am AppModule) processSubscriptions(sdkCtx sdk.Context, params types.Params) error {
	currentTime := sdkCtx.BlockTime().Unix()

	// Get all expired subscriptions
	expired, err := am.k.GetExpiredSubscriptions(sdkCtx, currentTime)
	if err != nil {
		return err
	}

	for _, sub := range expired {
		// Remove old subscription index
		if err := am.k.RemoveSubscription(sdkCtx, sub.Address, sub.Expiry); err != nil {
			return fmt.Errorf("processSubscriptions: failed to remove old index for %s: %w", sub.Address, err)
		}

		// Load profile core BEFORE the SubscriptionPeriod==0 short-circuit.
		// FAIL-FAST: an expired-subscription record without a readable profile
		// is a state inconsistency even for one-time payments (period==0).
		// Decoding after the continue would let corrupt ProfileCore escape
		// detection until a less diagnosable later path (review M-7).
		bz, found, err := am.k.GetProfileCore(sdkCtx, sub.Address)
		if err != nil {
			return fmt.Errorf("CONSENSUS_FATAL:PROFILE_GET processSubscriptions address=%s expiry=%d: %w", sub.Address, sub.Expiry, err)
		}
		if !found {
			return fmt.Errorf("CONSENSUS_FATAL:PROFILE_MISSING processSubscriptions address=%s expiry=%d: subscription index points to missing profile", sub.Address, sub.Expiry)
		}

		var core types.ProfileCore
		if err := json.Unmarshal(bz, &core); err != nil {
			return fmt.Errorf("CONSENSUS_FATAL:PROFILE_DECODE processSubscriptions address=%s bytes=%d: %w", sub.Address, len(bz), err)
		}

		// Burn any remaining reserve from module account before renewal/downgrade
		reserveBurned := false
		if core.ReserveFunds > 0 {
			if err := am.k.BurnFromModuleAmount(sdkCtx, core.ReserveFunds); err != nil {
				return fmt.Errorf("processSubscriptions: failed to burn reserve for %s: %w", sub.Address, err)
			}
			sdkCtx.Logger().Info("processSubscriptions: burned leftover reserve",
				"address", sub.Address, "reserve", core.ReserveFunds)
			core.ReserveFunds = 0
			reserveBurned = true
		}

		// Get tier config for current level using canonical level→tier mapping
		tierIdx := types.LevelToTierIndex(int(core.Level))
		if tierIdx == 0 {
			// A free-tier profile cannot have an active subscription after its
			// stale index is removed.
			if reserveBurned || core.SubscriptionExpiry != 0 || core.AutoRenew {
				core.SubscriptionExpiry = 0
				core.AutoRenew = false
				goto saveProfile
			}
			continue
		}
		if tierIdx < 0 {
			previousLevel := core.Level
			core.Level = 0
			core.SubscriptionExpiry = 0
			core.AutoRenew = false
			sdkCtx.Logger().Error("processSubscriptions: invalid subscription level, downgrading to free",
				"address", sub.Address, "level", previousLevel)
			sdkCtx.EventManager().EmitEvent(sdk.NewEvent("subscription_expired",
				sdk.NewAttribute("address", sub.Address),
				sdk.NewAttribute("previous_level", fmt.Sprintf("%d", previousLevel)),
				sdk.NewAttribute("reason", "invalid_subscription_level")))
			goto saveProfile
		}

		// One-time payment mode: there is nothing to renew and nothing to
		// re-index, but the expiry still has to take effect. Continuing here
		// left a paid level and stranded reserve behind with no index to expire
		// them ever again (review M-4). The reserve was burned above.
		if params.SubscriptionPeriod == 0 {
			previousLevel := core.Level
			core.Level = 0
			core.SubscriptionExpiry = 0
			core.AutoRenew = false
			sdkCtx.Logger().Info("processSubscriptions: one-time subscription expired, downgrading to free",
				"address", sub.Address, "level", previousLevel)
			sdkCtx.EventManager().EmitEvent(sdk.NewEvent("subscription_expired",
				sdk.NewAttribute("address", sub.Address),
				sdk.NewAttribute("previous_level", fmt.Sprintf("%d", previousLevel)),
				sdk.NewAttribute("reason", "one_time_expired")))
			goto saveProfile
		}

		// Check if auto_renew is enabled
		if !core.AutoRenew {
			// User cancelled auto-renewal via MsgSetAutoRenewal(auto_renew=false)
			sdkCtx.Logger().Info("processSubscriptions: auto-renew disabled, downgrading to free",
				"address", sub.Address,
				"level", core.Level,
			)
			previousLevel := core.Level
			core.Level = 0
			core.SubscriptionExpiry = 0
			// Emit subscription_expired event for indexer
			sdkCtx.EventManager().EmitEvent(
				sdk.NewEvent(
					"subscription_expired",
					sdk.NewAttribute("address", sub.Address),
					sdk.NewAttribute("previous_level", fmt.Sprintf("%d", previousLevel)),
					sdk.NewAttribute("reason", "auto_renew_disabled"),
				),
			)
		} else {
			tierConfig := params.GetTierConfig(int(core.Level))
			if tierConfig == nil {
				previousLevel := core.Level
				sdkCtx.Logger().Error("processSubscriptions: invalid level, downgrading to free",
					"address", sub.Address, "level", core.Level)
				core.Level = 0
				core.SubscriptionExpiry = 0
				sdkCtx.EventManager().EmitEvent(sdk.NewEvent("subscription_expired",
					sdk.NewAttribute("address", sub.Address),
					sdk.NewAttribute("previous_level", fmt.Sprintf("%d", previousLevel)),
					sdk.NewAttribute("reason", "invalid_tier_config")))
				goto saveProfile
			}
			periodFee := tierConfig.PeriodFee
			balance := am.k.GetBalance(sdkCtx, sub.Address, "umirage")

			if balance.GTE(sdkmath.NewIntFromUint64(periodFee)) {
				reserveAmount, burnAmount, err := types.SplitPeriodFee(periodFee, params.SubscriptionReserveBps)
				if err != nil {
					return fmt.Errorf("processSubscriptions: fee split for %s: %w", sub.Address, err)
				}

				// Burn non-reserve portion
				if burnAmount > 0 {
					if err := am.k.BurnFromAccount(sdkCtx, sub.Address, burnAmount); err != nil {
						return fmt.Errorf("processSubscriptions: failed to burn renewal fee for %s: %w",
							sub.Address, err)
					}
				}

				// Escrow reserve portion to module
				if reserveAmount > 0 {
					if err := am.k.DeductFeeFromOwner(sdkCtx, sub.Address, reserveAmount); err != nil {
						return fmt.Errorf("processSubscriptions: failed to escrow renewal reserve for %s: %w",
							sub.Address, err)
					}
				}

				// Renewal successful
				newExpiry, err := types.CheckedSubscriptionExpiry(currentTime, params.SubscriptionPeriod)
				if err != nil {
					return fmt.Errorf("processSubscriptions: expiry for %s: %w", sub.Address, err)
				}
				core.SubscriptionExpiry = newExpiry
				core.ReserveFunds = reserveAmount

				// Re-index with new expiry. The fee has already been burned and
				// escrowed, so a lost index would leave a paid user who never
				// expires and whose state differs from peers (review M-1).
				if err := am.k.SetSubscription(sdkCtx, sub.Address, int(core.Level), newExpiry); err != nil {
					return fmt.Errorf("processSubscriptions: failed to set new subscription index for %s: %w",
						sub.Address, err)
				}
				sdkCtx.Logger().Info("processSubscriptions: subscription renewed",
					"address", sub.Address,
					"level", core.Level,
					"fee", periodFee,
					"reserve", reserveAmount,
					"new_expiry", newExpiry,
				)
				// Emit subscription_renewed event for indexer
				sdkCtx.EventManager().EmitEvent(
					sdk.NewEvent(
						"subscription_renewed",
						sdk.NewAttribute("address", sub.Address),
						sdk.NewAttribute("level", fmt.Sprintf("%d", core.Level)),
						sdk.NewAttribute("new_expiry", fmt.Sprintf("%d", newExpiry)),
					),
				)
			} else {
				// Insufficient balance, downgrade to free tier
				sdkCtx.Logger().Info("processSubscriptions: insufficient balance, downgrading to free",
					"address", sub.Address,
					"level", core.Level,
					"required", periodFee,
					"balance", balance.String(),
				)
				previousLevel := core.Level
				core.Level = 0
				core.SubscriptionExpiry = 0
				// Emit subscription_expired event for indexer
				sdkCtx.EventManager().EmitEvent(
					sdk.NewEvent(
						"subscription_expired",
						sdk.NewAttribute("address", sub.Address),
						sdk.NewAttribute("previous_level", fmt.Sprintf("%d", previousLevel)),
						sdk.NewAttribute("reason", "insufficient_balance"),
					),
				)
			}
		}

	saveProfile:
		// Save updated profile core. Value has already moved by this point, so
		// skipping the profile write would commit a bank/index state that
		// contradicts the stored level and reserve (review M-1).
		newBz, err := json.Marshal(core)
		if err != nil {
			return fmt.Errorf("processSubscriptions: failed to marshal profile for %s: %w", sub.Address, err)
		}
		if err := am.k.SetProfileCore(sdkCtx, sub.Address, newBz); err != nil {
			return fmt.Errorf("processSubscriptions: failed to save profile for %s: %w", sub.Address, err)
		}
	}

	return nil
}

// Implement minimal Query/Msg servers on the module itself.

// Params Query
func (am AppModule) GetParams(ctx context.Context, _ *types.QueryParamsRequest) (*types.QueryParamsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	return &types.QueryParamsResponse{Params: am.k.GetParams(sdkCtx)}, nil
}

// Difficulty Query
func (am AppModule) GetDifficulty(ctx context.Context, _ *types.QueryDifficultyRequest) (*types.QueryDifficultyResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	params := am.k.GetParams(sdkCtx)

	currentDiff := am.k.GetCurrentDifficulty(sdkCtx)
	prevDiff := am.k.GetPreviousDifficulty(sdkCtx)
	lastChange := am.k.GetLastDifficultyChangeHeight(sdkCtx)
	msgCount := am.k.GetPoWMessageCount(sdkCtx, params)
	calmSeq := am.k.GetConsecutiveLowUsage(sdkCtx)

	// Get latest block hash from header
	latestHash := strings.ToLower(hex.EncodeToString(sdkCtx.BlockHeader().LastBlockId.Hash))
	currentHeight := sdkCtx.BlockHeight()

	return &types.QueryDifficultyResponse{
		CurrentDifficulty:   currentDiff,
		PreviousDifficulty:  prevDiff,
		LastChangeHeight:    lastChange,
		PowMessageCount:     msgCount,
		ConsecutiveLowUsage: calmSeq,
		LatestBlockHash:     latestHash,
		CurrentHeight:       currentHeight,
		MinDifficulty:       params.MinDifficulty,
	}, nil
}

// Profile Query
func (am AppModule) GetProfile(ctx context.Context, req *types.QueryProfileRequest) (*types.QueryProfileResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)

	address := strings.ToLower(strings.TrimSpace(req.Address))
	if address == "" {
		return nil, fmt.Errorf("address cannot be empty")
	}

	profile, found, err := am.loadFullProfile(sdkCtx, address)
	if err != nil {
		return nil, fmt.Errorf("failed to get profile: %w", err)
	}

	if !found {
		// NotFound, not a generic error: a deleted account is a legitimate state,
		// and callers must be able to tell it apart from a node failure without
		// matching on the message text.
		return nil, status.Errorf(codes.NotFound, "profile not found for address: %s", address)
	}

	return &types.QueryProfileResponse{
		Owner:              profile.Owner,
		Username:           profile.Username,
		Level:              int32(profile.Level),
		CreatedAt:          profile.CreatedAt,
		SubscriptionExpiry: profile.SubscriptionExpiry,
		AutoRenew:          profile.AutoRenew,
		ReserveFunds:       profile.ReserveFunds,
		Biography:          profile.Biography,
		Avatar:             profile.Avatar,
		Banner:             profile.Banner,
		Flair:              profile.Flair,
		EnabledAgents:      profile.EnabledAgents,
		FollowedUsers:      profile.FollowedUsers,
		FollowedTopics:     profile.FollowedTopics,
		BlockedUsers:       profile.BlockedUsers,
		BlockedPosts:       profile.BlockedPosts,
		BlockedTopics:      profile.BlockedTopics,
	}, nil
}

// Profiles Query (lists profiles with pagination)
func (am AppModule) GetProfiles(ctx context.Context, req *types.QueryProfilesRequest) (*types.QueryProfilesResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)

	// Extract pagination params
	var pageKey []byte
	var limit uint64 = 100 // Default limit
	if req.Pagination != nil {
		pageKey = req.Pagination.Key
		if req.Pagination.Limit > 0 {
			limit = req.Pagination.Limit
		}
	}

	profilesData, nextKey, err := am.k.GetProfilesPaginated(sdkCtx, pageKey, limit)
	if err != nil {
		return nil, fmt.Errorf("failed to get profiles: %w", err)
	}

	var profiles []*types.QueryProfileResponse
	for _, data := range profilesData {
		var core types.ProfileCore
		if err := json.Unmarshal(data, &core); err != nil {
			return nil, fmt.Errorf("GetProfiles: corrupt profile JSON: %w", err)
		}

		agents, err := am.k.ListEnabledAgentsOrdered(sdkCtx, core.Owner)
		if err != nil {
			return nil, fmt.Errorf("GetProfiles: enabled_agents for %s: %w", core.Owner, err)
		}
		users, err := am.k.ListFollowedUsers(sdkCtx, core.Owner)
		if err != nil {
			return nil, fmt.Errorf("GetProfiles: followed_users for %s: %w", core.Owner, err)
		}
		topics, err := am.k.ListFollowedTopics(sdkCtx, core.Owner)
		if err != nil {
			return nil, fmt.Errorf("GetProfiles: followed_topics for %s: %w", core.Owner, err)
		}
		blockedUsers, err := am.k.ListBlockedUsers(sdkCtx, core.Owner)
		if err != nil {
			return nil, fmt.Errorf("GetProfiles: blocked_users for %s: %w", core.Owner, err)
		}
		blockedPosts, err := am.k.ListBlockedPosts(sdkCtx, core.Owner)
		if err != nil {
			return nil, fmt.Errorf("GetProfiles: blocked_posts for %s: %w", core.Owner, err)
		}
		blockedTopics, err := am.k.ListBlockedTopics(sdkCtx, core.Owner)
		if err != nil {
			return nil, fmt.Errorf("GetProfiles: blocked_topics for %s: %w", core.Owner, err)
		}

		profiles = append(profiles, &types.QueryProfileResponse{
			Owner:              core.Owner,
			Username:           core.Username,
			Level:              core.Level,
			CreatedAt:          core.CreatedAt,
			SubscriptionExpiry: core.SubscriptionExpiry,
			AutoRenew:          core.AutoRenew,
			ReserveFunds:       core.ReserveFunds,
			Biography:          core.Biography,
			Avatar:             core.Avatar,
			Banner:             core.Banner,
			Flair:              core.Flair,
			EnabledAgents:      agents,
			FollowedUsers:      users,
			FollowedTopics:     topics,
			BlockedUsers:       blockedUsers,
			BlockedPosts:       blockedPosts,
			BlockedTopics:      blockedTopics,
		})
	}

	// Build pagination response
	var paginationResp *query.PageResponse
	if nextKey != nil {
		paginationResp = &query.PageResponse{NextKey: nextKey}
	}

	return &types.QueryProfilesResponse{
		Profiles:   profiles,
		Pagination: paginationResp,
	}, nil
}

// paramFieldSetters is the allowlist of Params fields a governance proposal may
// select, keyed by canonical snake_case proto field name.
//
// Field presence used to be inferred from "value != 0", which made it impossible
// to set any field to zero — including subscription_period, whose zero selects
// documented one-time-payment mode (review L-9). Selection now comes from
// MsgUpdateParams.update_mask, so a masked field is applied even when its value
// is zero, and an unmasked field is never touched.
//
// A Params field with no entry here is ungovernable, which is drift unless it is
// deliberate — deprecatedParamFields records the deliberate cases and the
// coverage test requires every other field to be present.
var paramFieldSetters = map[string]func(dst *types.Params, src types.Params){
	"min_difficulty":              func(d *types.Params, s types.Params) { d.MinDifficulty = s.MinDifficulty },
	"pow_message_window":          func(d *types.Params, s types.Params) { d.PowMessageWindow = s.PowMessageWindow },
	"pow_message_limit":           func(d *types.Params, s types.Params) { d.PowMessageLimit = s.PowMessageLimit },
	"pow_calm_period_definition":  func(d *types.Params, s types.Params) { d.PowCalmPeriodDefinition = s.PowCalmPeriodDefinition },
	"pow_calm_sequence_threshold": func(d *types.Params, s types.Params) { d.PowCalmSequenceThreshold = s.PowCalmSequenceThreshold },
	"pow_difficulty_allowance":    func(d *types.Params, s types.Params) { d.PowDifficultyAllowance = s.PowDifficultyAllowance },
	"pow_difficulty_step":         func(d *types.Params, s types.Params) { d.PowDifficultyStep = s.PowDifficultyStep },
	"mint_interval":               func(d *types.Params, s types.Params) { d.MintInterval = s.MintInterval },
	"mint_quantity":               func(d *types.Params, s types.Params) { d.MintQuantity = s.MintQuantity },
	"mint_dynamic_credit_cap":     func(d *types.Params, s types.Params) { d.MintDynamicCreditCap = s.MintDynamicCreditCap },
	"mint_dynamic_split":          func(d *types.Params, s types.Params) { d.MintDynamicSplit = s.MintDynamicSplit },
	"mint_floor_split":            func(d *types.Params, s types.Params) { d.MintFloorSplit = s.MintFloorSplit },
	"block_hash_window":           func(d *types.Params, s types.Params) { d.BlockHashWindow = s.BlockHashWindow },
	"min_username_size":           func(d *types.Params, s types.Params) { d.MinUsernameSize = s.MinUsernameSize },
	"max_username_size":           func(d *types.Params, s types.Params) { d.MaxUsernameSize = s.MaxUsernameSize },
	"min_topic_size":              func(d *types.Params, s types.Params) { d.MinTopicSize = s.MinTopicSize },
	"max_topic_size":              func(d *types.Params, s types.Params) { d.MaxTopicSize = s.MaxTopicSize },
	"subscription_period":         func(d *types.Params, s types.Params) { d.SubscriptionPeriod = s.SubscriptionPeriod },
	// subscription_reserve_percent is deliberately absent: it is superseded by
	// subscription_reserve_bps, so a proposal naming it is rejected as an
	// unsupported path instead of being applied to a field nothing reads.
	// deprecatedParamFields records that choice for the coverage test.
	"subscription_reserve_bps": func(d *types.Params, s types.Params) { d.SubscriptionReserveBps = s.SubscriptionReserveBps },
	"relay_min_gas_price":      func(d *types.Params, s types.Params) { d.RelayMinGasPrice = s.RelayMinGasPrice },
	"relay_max_gas_fee":        func(d *types.Params, s types.Params) { d.RelayMaxGasFee = s.RelayMaxGasFee },
	"max_envelope_age":         func(d *types.Params, s types.Params) { d.MaxEnvelopeAge = s.MaxEnvelopeAge },
	// Repeated fields are replaced wholesale; there is no per-element merge.
	"tiers":         func(d *types.Params, s types.Params) { d.Tiers = s.Tiers },
	"award_configs": func(d *types.Params, s types.Params) { d.AwardConfigs = s.AwardConfigs },
}

// deprecatedParamFields are Params fields that exist only so pre-upgrade stored
// blobs still decode. They are intentionally not in paramFieldSetters, so a
// proposal naming one is rejected rather than writing a field nothing reads.
// Params.Validate deliberately does not constrain them either: historical
// upgrade handlers set them and call SetParams, so a from-genesis replay must
// still succeed.
var deprecatedParamFields = map[string]string{
	"subscription_reserve_percent": "superseded by subscription_reserve_bps in v1.34.0",
}

// applyParamUpdates merges the masked fields of updates into current. It rejects
// an absent or empty mask, and any path that is not exactly one allowlisted
// top-level field name.
func applyParamUpdates(current types.Params, updates types.Params, mask *gogotypes.FieldMask) (types.Params, []string, error) {
	if mask == nil || len(mask.Paths) == 0 {
		return types.Params{}, nil, fmt.Errorf("update_mask is required and must select at least one field")
	}
	paths := mask.Paths

	original := current
	seen := make(map[string]struct{}, len(paths))
	changed := make([]string, 0, len(paths))
	for _, raw := range paths {
		path := strings.TrimSpace(raw)
		if path == "" {
			return types.Params{}, nil, fmt.Errorf("update_mask contains an empty path")
		}
		if path != raw {
			return types.Params{}, nil, fmt.Errorf("update_mask path %q contains surrounding whitespace", raw)
		}
		if strings.Contains(path, ".") {
			return types.Params{}, nil, fmt.Errorf("update_mask path %q is nested; only top-level Params fields are supported", path)
		}
		if _, dup := seen[path]; dup {
			return types.Params{}, nil, fmt.Errorf("update_mask path %q is listed more than once", path)
		}
		setter, ok := paramFieldSetters[path]
		if !ok {
			return types.Params{}, nil, fmt.Errorf("update_mask path %q is not a supported Params field", path)
		}
		seen[path] = struct{}{}
		setter(&current, updates)
		changed = append(changed, path)
	}

	if reflect.DeepEqual(original, current) {
		return types.Params{}, nil, fmt.Errorf("update_mask does not change any selected field")
	}
	return current, changed, nil
}

// UpdateParams stores new params after full Validate().
// Validation runs here (and again inside SetParams) so a governance proposal
// that would produce unvalidatable params fails at execution — not on the
// next BeginBlock GetParams CONSENSUS_FATAL halt across all validators.
func (am AppModule) UpdateParams(ctx context.Context, req *types.MsgUpdateParams) (*types.MsgUpdateParamsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	// Only governance authority may update params
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	if strings.TrimSpace(req.GetAuthority()) != govAuthority {
		return nil, fmt.Errorf("unauthorized: only governance authority can update params")
	}

	current := am.k.GetParams(sdkCtx)
	updated, changed, err := applyParamUpdates(current, req.Params, req.GetUpdateMask())
	if err != nil {
		return nil, fmt.Errorf("invalid update_mask: %w", err)
	}
	if err := updated.Validate(); err != nil {
		return nil, fmt.Errorf("invalid params: %w", err)
	}
	// Constraints a proposal must satisfy but a historical blob need not, so they
	// cannot be folded into Validate() without breaking a from-genesis replay.
	if err := updated.ValidateGovernanceUpdate(); err != nil {
		return nil, fmt.Errorf("invalid params: %w", err)
	}
	if err := am.k.SetParams(sdkCtx, updated); err != nil {
		return nil, err
	}
	sdkCtx.Logger().Info("UpdateParams applied", "fields", strings.Join(changed, ","))
	return &types.MsgUpdateParamsResponse{}, nil
}

// validateMsgPostMedia validates the media field constraints
func validateMsgPostMedia(media []string) error {
	if len(media) > 10 {
		return fmt.Errorf("media exceeds limit: %d > 10", len(media))
	}
	for i, mediaItem := range media {
		if len(mediaItem) > 2048 {
			return fmt.Errorf("media[%d] exceeds length limit: %d > 2048", i, len(mediaItem))
		}
		if !strings.HasPrefix(mediaItem, "https://") {
			return fmt.Errorf("media[%d] must use https://", i)
		}
		if err := validateSafeText(fmt.Sprintf("media[%d]", i), mediaItem); err != nil {
			return err
		}
	}
	return nil
}

// Post handler accepts MsgPost and returns empty response.
func (am AppModule) Post(ctx context.Context, req *types.MsgPost) (*types.MsgPostResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()

	var owner string
	if authority == govAuthority {
		// GOVERNANCE PATH: can post from any address
		// In governance context, we could use authority as owner or require an additional field
		// For now, use governance address as owner
		owner = authority
	} else {
		// NODE PATH: owner is the user derived from envelope_pubkey
		if len(req.GetEnvelopePubkey()) != 33 {
			sdkCtx.Logger().Info(logDelimiter)
			sdkCtx.Logger().Error("Post: invalid pubkey length", "len", len(req.GetEnvelopePubkey()))
			sdkCtx.Logger().Info(logDelimiter)
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		owner = sdk.AccAddress(pub.Address()).String()
	}

	var userLevel int
	if authority != govAuthority {
		core, err := am.requireUsername(sdkCtx, owner, "Post")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	params := am.k.GetParams(sdkCtx)

	if err := rejectUnsafeFields(
		"topic", req.GetTopic(),
		"title", req.GetTitle(),
		"content", req.GetContent(),
		"target", req.GetTarget(),
		"tag", req.GetTag(),
	); err != nil {
		return nil, err
	}

	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	isComment := target != ""
	if isComment {
		if err := validateTxHash(target); err != nil {
			return nil, err
		}
		// Comments must not include topic
		if strings.TrimSpace(req.GetTopic()) != "" {
			return nil, fmt.Errorf("comments must not include topic")
		}
		// Comments must include non-empty content
		if strings.TrimSpace(req.GetContent()) == "" {
			return nil, fmt.Errorf("comment content cannot be empty")
		}
	} else {
		// Root posts MUST include a non-empty topic
		topic := strings.TrimSpace(req.GetTopic())
		if topic == "" {
			return nil, fmt.Errorf("root posts require a topic")
		}
		if err := validateTopic(topic, uint64(params.MaxTopicSize), uint64(params.MinTopicSize)); err != nil {
			return nil, err
		}
	}

	// Validate and normalize tag field
	tag := normalizeTag(req.GetTag())
	if err := validateTag(tag); err != nil {
		return nil, err
	}
	// Validate media field (v1.12.0+ edit support)
	if err := validateMsgPostMedia(req.GetMedia()); err != nil {
		return nil, err
	}

	tierConfig := params.GetTierConfig(userLevel)
	if tierConfig == nil {
		return nil, fmt.Errorf("tier config not found for level %d", userLevel)
	}

	// Validate content size based on tier (count characters, not bytes)
	contentLen := uint64(utf8.RuneCountInString(req.GetContent()))
	maxContent := tierConfig.MaxContentLength
	if contentLen > maxContent {
		return nil, fmt.Errorf("content exceeds limit: %d > %d (tier level=%d)", contentLen, maxContent, userLevel)
	}

	// Validate title size for posts (not comments)
	if !isComment {
		titleLen := uint64(utf8.RuneCountInString(req.GetTitle()))
		maxTitle := tierConfig.MaxTitleLength
		if titleLen > maxTitle {
			return nil, fmt.Errorf("title exceeds limit: %d > %d (tier level=%d)", titleLen, maxTitle, userLevel)
		}
	}

	// Deduct gas fee from paid users
	gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
	if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "Post"); err != nil {
		return nil, err
	}
	if authority != govAuthority {
		valoper, err := am.k.AccToValoper(authority)
		if err != nil {
			return nil, fmt.Errorf("relay accounting: AccToValoper: %w", err)
		}
		if err := am.k.AddRelayCredit(sdkCtx, valoper, sdkmath.OneInt()); err != nil {
			return nil, fmt.Errorf("relay accounting: AddRelayCredit: %w", err)
		}
		sdkCtx.Logger().Debug("relay accounting: successful post credited",
			"payer", authority, "valoper", valoper)
	}

	return &types.MsgPostResponse{}, nil
}

// Vote handler accepts MsgVote and returns empty response.
func (am AppModule) Vote(ctx context.Context, req *types.MsgVote) (*types.MsgVoteResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()

	var owner string
	var userLevel int
	if authority != govAuthority {
		// NODE PATH: validate envelope_pubkey
		if len(req.GetEnvelopePubkey()) != 33 {
			sdkCtx.Logger().Info(logDelimiter)
			sdkCtx.Logger().Error("Vote: invalid pubkey length", "len", len(req.GetEnvelopePubkey()))
			sdkCtx.Logger().Info(logDelimiter)
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		owner = sdk.AccAddress(pub.Address()).String()

		core, err := am.requireUsername(sdkCtx, owner, "Vote")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	if target == "" {
		return nil, fmt.Errorf("vote target cannot be empty")
	}
	if err := validateTxHash(target); err != nil {
		return nil, err
	}

	// Deduct gas fee from paid users
	if owner != "" {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "Vote"); err != nil {
			return nil, err
		}
	}

	return &types.MsgVoteResponse{}, nil
}

// Edit handler accepts MsgEdit and returns empty response.
func (am AppModule) Edit(ctx context.Context, req *types.MsgEdit) (*types.MsgEditResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()

	var owner string
	if authority == govAuthority {
		owner = authority
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			sdkCtx.Logger().Info(logDelimiter)
			sdkCtx.Logger().Error("Edit: invalid pubkey length", "len", len(req.GetEnvelopePubkey()))
			sdkCtx.Logger().Info(logDelimiter)
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		owner = sdk.AccAddress(pub.Address()).String()
	}

	var userLevel int
	if authority != govAuthority {
		core, err := am.requireUsername(sdkCtx, owner, "Edit")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	params := am.k.GetParams(sdkCtx)

	if err := rejectUnsafeFields(
		"topic", req.GetTopic(),
		"title", req.GetTitle(),
		"content", req.GetContent(),
		"target", req.GetTarget(),
		"tag", req.GetTag(),
	); err != nil {
		return nil, err
	}

	// Validate override txhash (the post/comment being edited)
	override := strings.ToLower(strings.TrimSpace(req.GetOverride()))
	if err := validateTxHash(override); err != nil {
		return nil, fmt.Errorf("invalid override: %w", err)
	}

	// Validate target for comments (optional)
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	isComment := target != ""
	if isComment {
		if err := validateTxHash(target); err != nil {
			return nil, err
		}
	}
	tierConfig := params.GetTierConfig(userLevel)
	if tierConfig == nil {
		return nil, fmt.Errorf("tier config not found for level %d", userLevel)
	}

	// Validate content length based on tier (count characters, not bytes)
	contentLen := uint64(utf8.RuneCountInString(req.GetContent()))
	maxContent := tierConfig.MaxContentLength
	if contentLen > maxContent {
		return nil, fmt.Errorf("content exceeds limit: %d > %d (tier level=%d)", contentLen, maxContent, userLevel)
	}

	// Validate title length for root posts (not comments)
	if !isComment {
		titleLen := uint64(utf8.RuneCountInString(req.GetTitle()))
		maxTitle := tierConfig.MaxTitleLength
		if titleLen > maxTitle {
			return nil, fmt.Errorf("title exceeds limit: %d > %d (tier level=%d)", titleLen, maxTitle, userLevel)
		}
	}

	// Validate topic
	topic := strings.TrimSpace(req.GetTopic())
	if isComment {
		// Comments must not include topic on edit
		if topic != "" {
			return nil, fmt.Errorf("comments must not include topic")
		}
	} else {
		// Root posts must include a non-empty topic
		if topic == "" {
			return nil, fmt.Errorf("root posts require a topic")
		}
		if err := validateTopic(topic, uint64(params.MaxTopicSize), uint64(params.MinTopicSize)); err != nil {
			return nil, err
		}
	}

	// Validate and normalize tag field
	tag := normalizeTag(req.GetTag())
	if err := validateTag(tag); err != nil {
		return nil, err
	}

	// Log edit event (indexer enforces ownership)
	sdkCtx.Logger().Info("Edit",
		"owner", owner,
		"override", override,
		"target", target,
		"media_count", len(req.GetMedia()),
	)

	// Deduct gas fee from paid users
	gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
	if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "Edit"); err != nil {
		return nil, err
	}

	return &types.MsgEditResponse{}, nil
}

// Annotate handler: agent-only overlay on an existing post.
// Sentinel "." means no change; empty string means clear.
func (am AppModule) Annotate(ctx context.Context, req *types.MsgAnnotate) (*types.MsgAnnotateResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()

	var owner string
	if authority == govAuthority {
		owner = authority
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			sdkCtx.Logger().Info(logDelimiter)
			sdkCtx.Logger().Error("Annotate: invalid pubkey length", "len", len(req.GetEnvelopePubkey()))
			sdkCtx.Logger().Info(logDelimiter)
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		owner = sdk.AccAddress(pub.Address()).String()
	}

	var userLevel int
	if authority != govAuthority {
		core, err := am.requireUsername(sdkCtx, owner, "Annotate")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	// Enforce agent tier
	if userLevel < types.LevelAgent && authority != govAuthority {
		return nil, fmt.Errorf("annotate requires agent tier (level >= %d), got %d", types.LevelAgent, userLevel)
	}

	params := am.k.GetParams(sdkCtx)

	// Validate override txhash (the post being annotated)
	override := strings.ToLower(strings.TrimSpace(req.GetOverride()))
	if err := validateTxHash(override); err != nil {
		return nil, fmt.Errorf("invalid override: %w", err)
	}

	// Annotate never supports PoW
	if req.GetEnvelopeDifficulty() != 0 || req.GetEnvelopePow() != 0 {
		sdkCtx.Logger().Error("Annotate: PoW not allowed", "difficulty", req.GetEnvelopeDifficulty(), "pow", req.GetEnvelopePow())
		return nil, fmt.Errorf("annotate does not allow pow")
	}

	tierConfig := params.GetTierConfig(types.LevelAgent)
	if tierConfig == nil {
		return nil, fmt.Errorf("tier config not found for level %d", types.LevelAgent)
	}

	// Sentinel "." means no change — skip validation for those fields.
	const sentinel = "."

	// Validate topic (skip if sentinel)
	topic := strings.TrimSpace(req.GetTopic())
	if topic != sentinel && topic != "" {
		if err := validateTopic(topic, uint64(params.MaxTopicSize), uint64(params.MinTopicSize)); err != nil {
			return nil, err
		}
	}

	// Validate title length (skip if sentinel)
	title := req.GetTitle()
	if title != sentinel {
		titleLen := uint64(utf8.RuneCountInString(title))
		if titleLen > tierConfig.MaxTitleLength {
			return nil, fmt.Errorf("title exceeds limit: %d > %d", titleLen, tierConfig.MaxTitleLength)
		}
	}

	// Validate content length (skip if sentinel)
	content := req.GetContent()
	if content != sentinel {
		contentLen := uint64(utf8.RuneCountInString(content))
		if contentLen > tierConfig.MaxContentLength {
			return nil, fmt.Errorf("content exceeds limit: %d > %d", contentLen, tierConfig.MaxContentLength)
		}
	}

	// Validate and normalize tag (skip if sentinel)
	tag := strings.TrimSpace(req.GetTag())
	if tag != sentinel {
		tag = normalizeTag(tag)
		if err := validateTag(tag); err != nil {
			return nil, err
		}
	}

	// Validate appendix length (skip if sentinel)
	appendix := req.GetAppendix()
	if appendix != sentinel {
		appendixLen := uint64(utf8.RuneCountInString(appendix))
		if appendixLen > tierConfig.MaxContentLength {
			return nil, fmt.Errorf("appendix exceeds limit: %d > %d", appendixLen, tierConfig.MaxContentLength)
		}
	}

	// Validate media (skip if single-element sentinel ["."])
	media := req.GetMedia()
	isSentinelMedia := len(media) == 1 && media[0] == sentinel
	if !isSentinelMedia && len(media) > 0 {
		if err := validateMsgPostMedia(media); err != nil {
			return nil, err
		}
	}

	// Validate non-sentinel fields for unsafe text
	unsafeChecks := []struct{ name, val string }{
		{"topic", topic}, {"title", title}, {"content", content},
		{"tag", tag}, {"appendix", appendix},
	}
	for _, c := range unsafeChecks {
		if c.val != sentinel {
			if err := rejectUnsafeFields(c.name, c.val); err != nil {
				return nil, err
			}
		}
	}

	sdkCtx.Logger().Info("Annotate",
		"agent", owner,
		"override", override,
		"topic_sentinel", topic == sentinel,
		"title_sentinel", title == sentinel,
		"content_sentinel", content == sentinel,
		"tag_sentinel", tag == sentinel,
		"appendix_sentinel", appendix == sentinel,
		"media_sentinel", isSentinelMedia,
		"media_count", len(media),
	)

	gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
	if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "Annotate"); err != nil {
		return nil, err
	}

	return &types.MsgAnnotateResponse{}, nil
}

// updateProfileCore is a helper that loads, updates, validates, and persists core profile data only.
// Lists (EnabledAgents, etc.) are stored separately and should be updated via keeper methods.
func (am AppModule) updateProfileCore(sdkCtx sdk.Context, owner string, updateFn func(*types.ProfileCore) error) error {
	params := am.k.GetParams(sdkCtx)

	// Load existing core profile. Only a genuinely absent key may start from an
	// empty core: an unreadable or undecodable profile must not be silently
	// overwritten with one (review L-1).
	var core types.ProfileCore
	old, found, err := am.k.GetProfileCore(sdkCtx, owner)
	if err != nil {
		return fmt.Errorf("updateProfileCore: load profile for %s: %w", owner, err)
	}
	if found {
		if err := json.Unmarshal(old, &core); err != nil {
			return fmt.Errorf("updateProfileCore: corrupt profile for %s: %w", owner, err)
		}
	}
	core.Owner = owner

	// Set CreatedAt if not already set (first creation)
	if core.CreatedAt == 0 {
		core.CreatedAt = sdkCtx.BlockTime().Unix()
	}

	// Apply updates
	if err := updateFn(&core); err != nil {
		return err
	}

	// Validate core fields (need to get agents count for validation)
	agents, err := am.k.ListEnabledAgentsOrdered(sdkCtx, owner)
	if err != nil {
		return fmt.Errorf("updateProfileCore: load enabled_agents for %s: %w", owner, err)
	}
	// A nil tier config is a governance fault, not a cue to invent a limit.
	// Each of these eight sites used to substitute a different hardcoded number,
	// none of them matching DefaultTiers, while Edit hard-failed on exactly the
	// same condition (review I-5). Reachable only through a governance
	// MsgSetLevel to a level in 2..9, where LevelToTierIndex returns -1.
	tierConfig := params.GetTierConfig(int(core.Level))
	if tierConfig == nil {
		return fmt.Errorf("tier config not found for level %d", core.Level)
	}
	maxAgents := tierConfig.MaxEnabledAgents

	// Build a temporary Profile for validation
	tempProf := core.ToProfile()
	tempProf.EnabledAgents = agents
	if err := tempProf.ValidateBasic(params.MinUsernameSize, params.MaxUsernameSize, maxAgents); err != nil {
		return err
	}

	// Persist core only
	bz, err := json.Marshal(core)
	if err != nil {
		return err
	}
	return am.k.SetProfileCore(sdkCtx, owner, bz)
}

// loadFullProfile loads the complete profile including all lists from separate storage
func (am AppModule) loadFullProfile(sdkCtx sdk.Context, owner string) (types.Profile, bool, error) {
	// Load core
	bz, found, err := am.k.GetProfileCore(sdkCtx, owner)
	if err != nil {
		return types.Profile{}, false, err
	}
	if !found {
		return types.Profile{}, false, nil
	}

	var core types.ProfileCore
	if err := json.Unmarshal(bz, &core); err != nil {
		return types.Profile{}, false, err
	}

	// Convert to full profile
	prof := core.ToProfile()

	// Load lists via per-entry iterators.
	//
	// Every error propagates. These used to be `if xs, err := ...; err == nil`,
	// which discarded the error and returned the profile with that list empty and
	// err == nil — so a transient read fault was indistinguishable from a user who
	// blocks nobody, and a client read "0 blocked users" as truth (review L-4).
	// Query-only, so it could not diverge consensus, but it is the exact fail-open
	// shape the v1.34.0 contract set out to remove, and the paginated path already
	// propagates.
	agents, err := am.k.ListEnabledAgentsOrdered(sdkCtx, owner)
	if err != nil {
		return types.Profile{}, false, fmt.Errorf("loading enabled agents for %s: %w", owner, err)
	}
	prof.EnabledAgents = agents

	users, err := am.k.ListFollowedUsers(sdkCtx, owner)
	if err != nil {
		return types.Profile{}, false, fmt.Errorf("loading followed users for %s: %w", owner, err)
	}
	prof.FollowedUsers = users

	topics, err := am.k.ListFollowedTopics(sdkCtx, owner)
	if err != nil {
		return types.Profile{}, false, fmt.Errorf("loading followed topics for %s: %w", owner, err)
	}
	prof.FollowedTopics = topics

	blocked, err := am.k.ListBlockedUsers(sdkCtx, owner)
	if err != nil {
		return types.Profile{}, false, fmt.Errorf("loading blocked users for %s: %w", owner, err)
	}
	prof.BlockedUsers = blocked

	posts, err := am.k.ListBlockedPosts(sdkCtx, owner)
	if err != nil {
		return types.Profile{}, false, fmt.Errorf("loading blocked posts for %s: %w", owner, err)
	}
	prof.BlockedPosts = posts

	blockedTopics, err := am.k.ListBlockedTopics(sdkCtx, owner)
	if err != nil {
		return types.Profile{}, false, fmt.Errorf("loading blocked topics for %s: %w", owner, err)
	}
	prof.BlockedTopics = blockedTopics

	return prof, true, nil
}

// SetUsername typed handler persists username
func (am AppModule) SetUsername(ctx context.Context, req *types.MsgSetUsername) (*types.MsgSetUsernameResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	params := am.k.GetParams(sdkCtx)
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))

	var owner string
	var isGov bool
	if authority == govAuthority {
		// GOVERNANCE PATH: can set username for any target
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		owner = target
		isGov = true
	} else {
		// NODE PATH: envelope_pubkey must derive to TARGET (the user being updated)
		if len(req.GetEnvelopePubkey()) != 33 {
			sdkCtx.Logger().Info(logDelimiter)
			sdkCtx.Logger().Error("SetUsername: invalid pubkey length", "len", len(req.GetEnvelopePubkey()))
			sdkCtx.Logger().Info(logDelimiter)
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		derived := sdk.AccAddress(pub.Address()).String()
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		if derived != target {
			return nil, fmt.Errorf("envelope_pubkey must derive to target")
		}
		owner = target
		isGov = false
	}

	username := req.GetUsername()
	if err := validateSafeText("username", username); err != nil {
		return nil, err
	}

	// Get user's tier to check if they can change name (only need Level and Username)
	var userLevel int
	var prevUsername string
	old, found, err := am.k.GetProfileCore(sdkCtx, owner)
	if err != nil {
		return nil, fmt.Errorf("SetUsername: load profile for %s: %w", owner, err)
	}
	if found {
		var prev types.ProfileCore
		if err := json.Unmarshal(old, &prev); err != nil {
			return nil, fmt.Errorf("SetUsername: corrupt profile for %s: %w", owner, err)
		}
		userLevel = int(prev.Level)
		prevUsername = prev.Username
	}

	tierConfig := params.GetTierConfig(userLevel)
	canRemoveAnon := isGov || (tierConfig != nil && tierConfig.CanRemoveAnon)

	// Username normalization: if user can't remove anon (free tier), force "Anon-" prefix
	if !canRemoveAnon {
		for strings.HasPrefix(strings.ToLower(username), "anon-") {
			username = username[len("anon-"):]
		}
		username = "Anon-" + username
	}

	// Release previous username if changing. Discarding this left the old
	// mapping claimed by an owner who no longer uses it. Release → claim →
	// profile write is atomic through the transaction cache.
	if prevUsername != "" && !strings.EqualFold(prevUsername, username) {
		if err := am.k.ReleaseUsername(sdkCtx, prevUsername, owner); err != nil {
			return nil, fmt.Errorf("SetUsername: release previous username %q for %s: %w",
				prevUsername, owner, err)
		}
	}

	// Claim new username
	if err := am.k.ClaimUsername(sdkCtx, username, owner); err != nil {
		sdkCtx.Logger().Info(logDelimiter)
		sdkCtx.Logger().Error("SetUsername: claim username failed", "username", username, "owner", owner, "err", err.Error())
		sdkCtx.Logger().Info(logDelimiter)
		return nil, err
	}

	// Update profile core
	finalUsername := username
	if err := am.updateProfileCore(sdkCtx, owner, func(c *types.ProfileCore) error {
		c.Username = finalUsername
		return nil
	}); err != nil {
		sdkCtx.Logger().Info(logDelimiter)
		sdkCtx.Logger().Error("SetUsername: update profile failed", "owner", owner, "err", err.Error())
		sdkCtx.Logger().Info(logDelimiter)
		return nil, err
	}

	// Log successful username change
	sdkCtx.Logger().Info(logDelimiter)
	if prevUsername != "" && prevUsername != username {
		sdkCtx.Logger().Info("SetUsername: username changed", "owner", owner, "old_username", prevUsername, "new_username", username, "can_remove_anon", canRemoveAnon)
	} else {
		sdkCtx.Logger().Info("SetUsername: username set", "owner", owner, "username", username, "can_remove_anon", canRemoveAnon)
	}
	sdkCtx.Logger().Info(logDelimiter)

	// Deduct gas fee from paid users
	gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
	if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "SetUsername"); err != nil {
		return nil, err
	}

	return &types.MsgSetUsernameResponse{}, nil
}

// SetBiography updates a user's biography (subscriber-only feature)
func (am AppModule) SetBiography(ctx context.Context, req *types.MsgSetBiography) (*types.MsgSetBiographyResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	params := am.k.GetParams(sdkCtx)
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))

	var owner string
	if authority == govAuthority {
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		owner = target
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			sdkCtx.Logger().Info(logDelimiter)
			sdkCtx.Logger().Error("SetBiography: invalid pubkey length", "len", len(req.GetEnvelopePubkey()))
			sdkCtx.Logger().Info(logDelimiter)
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		derived := sdk.AccAddress(pub.Address()).String()
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		if derived != target {
			return nil, fmt.Errorf("envelope_pubkey must derive to target")
		}
		owner = target
	}

	var userLevel int
	if authority != govAuthority {
		core, err := am.requireUsername(sdkCtx, owner, "SetBiography")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	biography := strings.TrimSpace(req.GetBiography())
	if err := validateSafeText("biography", biography); err != nil {
		return nil, err
	}

	tierConfig := params.GetTierConfig(userLevel)

	// Non-empty biography requires CanHaveBiography (governance can always set)
	if biography != "" && authority != govAuthority {
		if tierConfig == nil || !tierConfig.CanHaveBiography {
			return nil, fmt.Errorf("biography not available for tier level %d", userLevel)
		}
		// Zero is "disabled", per the field's own proto comment — not "unlimited".
		// The old `maxLen > 0 &&` guard meant the opposite, so a tier with
		// can_have_biography enabled but no length set had no tier limit at all
		// (review I-6). ValidateGovernanceUpdate now rejects that combination, so
		// this branch is unreachable via governance; it stays because the state it
		// guards against is a raw_state import away.
		maxLen := tierConfig.MaxBiographyLength
		if maxLen == 0 {
			return nil, fmt.Errorf("biography not available for tier level %d: max_biography_length is 0", userLevel)
		}
		if uint64(utf8.RuneCountInString(biography)) > maxLen {
			return nil, fmt.Errorf("biography exceeds limit: %d > %d characters", utf8.RuneCountInString(biography), maxLen)
		}
	}

	// Update profile core
	if err := am.updateProfileCore(sdkCtx, owner, func(c *types.ProfileCore) error {
		c.Biography = biography
		return nil
	}); err != nil {
		sdkCtx.Logger().Info(logDelimiter)
		sdkCtx.Logger().Error("SetBiography: update profile failed", "owner", owner, "err", err.Error())
		sdkCtx.Logger().Info(logDelimiter)
		return nil, err
	}

	sdkCtx.Logger().Info(logDelimiter)
	sdkCtx.Logger().Info("SetBiography: biography updated", "owner", owner, "length", len(biography))
	sdkCtx.Logger().Info(logDelimiter)

	// Deduct gas fee from paid users
	gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
	if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "SetBiography"); err != nil {
		return nil, err
	}

	return &types.MsgSetBiographyResponse{}, nil
}

// EnableAgent adds an agent to the user's enabled agents list (capped deque)
func (am AppModule) EnableAgent(ctx context.Context, req *types.MsgEnableAgent) (*types.MsgEnableAgentResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	params := am.k.GetParams(sdkCtx)
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	agent := strings.ToLower(strings.TrimSpace(req.GetAgent()))

	var owner string
	if authority == govAuthority {
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		owner = target
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			sdkCtx.Logger().Info(logDelimiter)
			sdkCtx.Logger().Error("EnableAgent: invalid pubkey length", "len", len(req.GetEnvelopePubkey()))
			sdkCtx.Logger().Info(logDelimiter)
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		derived := sdk.AccAddress(pub.Address()).String()
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		if derived != target {
			return nil, fmt.Errorf("envelope_pubkey must derive to target")
		}
		owner = target
	}

	if _, err := sdk.AccAddressFromBech32(agent); err != nil {
		sdkCtx.Logger().Info(logDelimiter)
		sdkCtx.Logger().Error("EnableAgent: invalid agent address", "address", agent)
		sdkCtx.Logger().Info(logDelimiter)
		return nil, fmt.Errorf("invalid agent address: %s", agent)
	}
	if agent == owner {
		sdkCtx.Logger().Info(logDelimiter)
		sdkCtx.Logger().Error("EnableAgent: self-enable not allowed", "owner", owner)
		sdkCtx.Logger().Info(logDelimiter)
		return nil, fmt.Errorf("cannot enable yourself as an agent")
	}

	var userLevel int
	if authority != govAuthority {
		core, err := am.requireUsername(sdkCtx, owner, "EnableAgent")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}
	// A nil tier config is a governance fault, not a cue to invent a limit.
	// Each of these eight sites used to substitute a different hardcoded number,
	// none of them matching DefaultTiers, while Edit hard-failed on exactly the
	// same condition (review I-5). Reachable only through a governance
	// MsgSetLevel to a level in 2..9, where LevelToTierIndex returns -1.
	tierConfig := params.GetTierConfig(userLevel)
	if tierConfig == nil {
		return nil, fmt.Errorf("tier config not found for level %d", userLevel)
	}
	maxAgents := int(tierConfig.MaxEnabledAgents)

	has, err := am.k.HasEnabledAgent(sdkCtx, owner, agent)
	if err != nil {
		return nil, err
	}
	if has {
		return &types.MsgEnableAgentResponse{}, nil
	}
	agentCount, err := am.k.CountEnabledAgents(sdkCtx, owner)
	if err != nil {
		return nil, fmt.Errorf("EnableAgent: enabled_agents count for %s: %w", owner, err)
	}
	if int(agentCount) >= maxAgents {
		return nil, fmt.Errorf("enabled agents limit reached (%d); disable an agent first", maxAgents)
	}
	if _, err := am.k.AddEnabledAgent(sdkCtx, owner, agent); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Info(logDelimiter)
	sdkCtx.Logger().Info("EnableAgent: agent enabled", "owner", owner, "agent", agent)
	sdkCtx.Logger().Info(logDelimiter)

	gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
	if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "EnableAgent"); err != nil {
		return nil, err
	}

	return &types.MsgEnableAgentResponse{}, nil
}

// DisableAgent removes an agent from the user's enabled agents list
func (am AppModule) DisableAgent(ctx context.Context, req *types.MsgDisableAgent) (*types.MsgDisableAgentResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	agent := strings.ToLower(strings.TrimSpace(req.GetAgent()))

	var owner string
	if authority == govAuthority {
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		owner = target
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			sdkCtx.Logger().Info(logDelimiter)
			sdkCtx.Logger().Error("DisableAgent: invalid pubkey length", "len", len(req.GetEnvelopePubkey()))
			sdkCtx.Logger().Info(logDelimiter)
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		derived := sdk.AccAddress(pub.Address()).String()
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		if derived != target {
			return nil, fmt.Errorf("envelope_pubkey must derive to target")
		}
		owner = target
	}

	var userLevel int
	if authority != govAuthority {
		core, err := am.requireUsername(sdkCtx, owner, "DisableAgent")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	if err := am.k.RemoveEnabledAgent(sdkCtx, owner, agent); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Info(logDelimiter)
	sdkCtx.Logger().Info("DisableAgent: agent disabled", "owner", owner, "agent", agent)
	sdkCtx.Logger().Info(logDelimiter)

	gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
	if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "DisableAgent"); err != nil {
		return nil, err
	}

	return &types.MsgDisableAgentResponse{}, nil
}

// SetAgents atomically replaces the user's enabled agents list (ordered).
func (am AppModule) SetAgents(ctx context.Context, req *types.MsgSetAgents) (*types.MsgSetAgentsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	params := am.k.GetParams(sdkCtx)
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))

	var owner string
	if authority == govAuthority {
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		owner = target
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			sdkCtx.Logger().Info(logDelimiter)
			sdkCtx.Logger().Error("SetAgents: invalid pubkey length", "len", len(req.GetEnvelopePubkey()))
			sdkCtx.Logger().Info(logDelimiter)
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		derived := sdk.AccAddress(pub.Address()).String()
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		if derived != target {
			return nil, fmt.Errorf("envelope_pubkey must derive to target")
		}
		owner = target
	}

	var userLevel int
	if authority != govAuthority {
		core, err := am.requireUsername(sdkCtx, owner, "SetAgents")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}
	// A nil tier config is a governance fault, not a cue to invent a limit.
	// Each of these eight sites used to substitute a different hardcoded number,
	// none of them matching DefaultTiers, while Edit hard-failed on exactly the
	// same condition (review I-5). Reachable only through a governance
	// MsgSetLevel to a level in 2..9, where LevelToTierIndex returns -1.
	tierConfig := params.GetTierConfig(userLevel)
	if tierConfig == nil {
		return nil, fmt.Errorf("tier config not found for level %d", userLevel)
	}
	maxAgents := int(tierConfig.MaxEnabledAgents)

	agents := req.GetAgents()
	if len(agents) > maxAgents {
		return nil, fmt.Errorf("too many agents: %d > %d", len(agents), maxAgents)
	}

	ownerLower := strings.ToLower(owner)
	seen := make(map[string]struct{}, len(agents))
	normalized := make([]string, 0, len(agents))
	for _, a := range agents {
		a = strings.ToLower(strings.TrimSpace(a))
		if _, err := sdk.AccAddressFromBech32(a); err != nil {
			sdkCtx.Logger().Info(logDelimiter)
			sdkCtx.Logger().Error("SetAgents: invalid agent address", "address", a)
			sdkCtx.Logger().Info(logDelimiter)
			return nil, fmt.Errorf("invalid agent address: %s", a)
		}
		if a == ownerLower {
			return nil, fmt.Errorf("cannot set yourself as an agent")
		}
		if _, dup := seen[a]; dup {
			return nil, fmt.Errorf("duplicate agent: %s", a)
		}
		seen[a] = struct{}{}
		normalized = append(normalized, a)
	}

	if err := am.k.ReplaceAllEnabledAgents(sdkCtx, owner, normalized); err != nil {
		sdkCtx.Logger().Info(logDelimiter)
		sdkCtx.Logger().Error("SetAgents: failed to save enabled agents", "owner", owner, "err", err.Error())
		sdkCtx.Logger().Info(logDelimiter)
		return nil, err
	}

	_, hasProfile, err := am.k.GetProfileCore(sdkCtx, owner)
	if err != nil {
		return nil, fmt.Errorf("SetAgents: load profile for %s: %w", owner, err)
	}
	if !hasProfile {
		if err := am.updateProfileCore(sdkCtx, owner, func(c *types.ProfileCore) error {
			return nil
		}); err != nil {
			return nil, fmt.Errorf("SetAgents: bootstrap profile for %s: %w", owner, err)
		}
	}

	sdkCtx.Logger().Info(logDelimiter)
	sdkCtx.Logger().Info("SetAgents: agents set", "owner", owner, "count", len(normalized))
	sdkCtx.Logger().Info(logDelimiter)

	gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
	if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "SetAgents"); err != nil {
		return nil, err
	}

	return &types.MsgSetAgentsResponse{}, nil
}

// BlockPost blocks a post txhash (persisted on-chain)
func (am AppModule) BlockPost(ctx context.Context, req *types.MsgBlockPost) (*types.MsgBlockPostResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	params := am.k.GetParams(sdkCtx)
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()

	var owner string
	var userLevel int
	if authority == govAuthority {
		owner = authority
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		owner = sdk.AccAddress(pub.Address()).String()
		core, err := am.requireUsername(sdkCtx, owner, "BlockPost")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	if err := validateTxHash(target); err != nil {
		return nil, err
	}

	// A nil tier config is a governance fault, not a cue to invent a limit.
	// Each of these eight sites used to substitute a different hardcoded number,
	// none of them matching DefaultTiers, while Edit hard-failed on exactly the
	// same condition (review I-5). Reachable only through a governance
	// MsgSetLevel to a level in 2..9, where LevelToTierIndex returns -1.
	tierConfig := params.GetTierConfig(userLevel)
	if tierConfig == nil {
		return nil, fmt.Errorf("tier config not found for level %d", userLevel)
	}
	maxPosts := tierConfig.MaxBlockedPosts
	if maxPosts == 0 {
		return nil, fmt.Errorf("blocked post limit is zero for level %d", userLevel)
	}

	// O(1) add with automatic deque eviction of oldest when over cap
	if _, err := am.k.AddBlockedPostDeque(sdkCtx, owner, target, uint32(maxPosts)); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Info("BlockPost", "owner", owner, "target", target)

	if owner != "" && authority != govAuthority {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "BlockPost"); err != nil {
			return nil, err
		}
	}

	return &types.MsgBlockPostResponse{}, nil
}

// UnblockPost unblocks a post txhash (persisted on-chain)
func (am AppModule) UnblockPost(ctx context.Context, req *types.MsgUnblockPost) (*types.MsgUnblockPostResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()

	var owner string
	var userLevel int
	if authority == govAuthority {
		owner = authority
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		owner = sdk.AccAddress(pub.Address()).String()
		core, err := am.requireUsername(sdkCtx, owner, "UnblockPost")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	if err := validateTxHash(target); err != nil {
		return nil, err
	}

	if err := am.k.RemoveBlockedPost(sdkCtx, owner, target); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Info("UnblockPost", "owner", owner, "target", target)

	if owner != "" && authority != govAuthority {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "UnblockPost"); err != nil {
			return nil, err
		}
	}

	return &types.MsgUnblockPostResponse{}, nil
}

// BlockUser blocks a user address (persisted on-chain)
func (am AppModule) BlockUser(ctx context.Context, req *types.MsgBlockUser) (*types.MsgBlockUserResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	params := am.k.GetParams(sdkCtx)
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()

	var owner string
	var userLevel int
	if authority == govAuthority {
		owner = authority
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		owner = sdk.AccAddress(pub.Address()).String()
		core, err := am.requireUsername(sdkCtx, owner, "BlockUser")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	if err := validateAddress(target); err != nil {
		return nil, err
	}

	if owner == target {
		return nil, fmt.Errorf("cannot block yourself")
	}

	// Mutual exclusion: blocking a user removes them from followed list (O(1)).
	// A discarded delete could commit both entries on one node and only the
	// block on its peers (review L-8).
	if err := am.k.RemoveFollowedUser(sdkCtx, owner, target); err != nil {
		return nil, fmt.Errorf("BlockUser: unfollow %s for %s: %w", target, owner, err)
	}

	// A nil tier config is a governance fault, not a cue to invent a limit.
	// Each of these eight sites used to substitute a different hardcoded number,
	// none of them matching DefaultTiers, while Edit hard-failed on exactly the
	// same condition (review I-5). Reachable only through a governance
	// MsgSetLevel to a level in 2..9, where LevelToTierIndex returns -1.
	tierConfig := params.GetTierConfig(userLevel)
	if tierConfig == nil {
		return nil, fmt.Errorf("tier config not found for level %d", userLevel)
	}
	maxUsers := tierConfig.MaxBlockedUsers
	if maxUsers == 0 {
		return nil, fmt.Errorf("blocked user limit is zero for level %d", userLevel)
	}

	if _, err := am.k.AddBlockedUserDeque(sdkCtx, owner, target, uint32(maxUsers)); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Info("BlockUser", "owner", owner, "target", target)

	if owner != "" && authority != govAuthority {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "BlockUser"); err != nil {
			return nil, err
		}
	}

	return &types.MsgBlockUserResponse{}, nil
}

// UnblockUser unblocks a user address (persisted on-chain)
func (am AppModule) UnblockUser(ctx context.Context, req *types.MsgUnblockUser) (*types.MsgUnblockUserResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()

	var owner string
	var userLevel int
	if authority == govAuthority {
		owner = authority
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		owner = sdk.AccAddress(pub.Address()).String()
		core, err := am.requireUsername(sdkCtx, owner, "UnblockUser")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	if err := validateAddress(target); err != nil {
		return nil, err
	}

	if err := am.k.RemoveBlockedUser(sdkCtx, owner, target); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Info("UnblockUser", "owner", owner, "target", target)

	if owner != "" && authority != govAuthority {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "UnblockUser"); err != nil {
			return nil, err
		}
	}

	return &types.MsgUnblockUserResponse{}, nil
}

// BlockTopic blocks a topic (persisted on-chain, tier-limited)
func (am AppModule) BlockTopic(ctx context.Context, req *types.MsgBlockTopic) (*types.MsgBlockTopicResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	params := am.k.GetParams(sdkCtx)
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()

	var owner string
	var userLevel int
	if authority == govAuthority {
		owner = authority
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		owner = sdk.AccAddress(pub.Address()).String()
		core, err := am.requireUsername(sdkCtx, owner, "BlockTopic")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	topic := strings.ToLower(strings.TrimSpace(req.GetTopic()))
	if err := validateBlockedTopicPattern(topic, uint64(params.MaxTopicSize), uint64(params.MinTopicSize)); err != nil {
		return nil, fmt.Errorf("invalid topic: %w", err)
	}
	if strings.HasSuffix(topic, "*") {
		sdkCtx.Logger().Debug("BlockTopic wildcard", "owner", owner, "pattern", topic)
	}

	// Mutual exclusion: blocking a topic pattern removes matching followed topics.
	followedTopics, err := am.k.ListFollowedTopics(sdkCtx, owner)
	if err != nil {
		return nil, err
	}
	for _, t := range followedTopics {
		if topicMatchesPattern(t, topic) {
			if err := am.k.RemoveFollowedTopic(sdkCtx, owner, t); err != nil {
				return nil, fmt.Errorf("BlockTopic: unfollow %q for %s: %w", t, owner, err)
			}
		}
	}

	// A nil tier config is a governance fault, not a cue to invent a limit.
	// Each of these eight sites used to substitute a different hardcoded number,
	// none of them matching DefaultTiers, while Edit hard-failed on exactly the
	// same condition (review I-5). Reachable only through a governance
	// MsgSetLevel to a level in 2..9, where LevelToTierIndex returns -1.
	tierConfig := params.GetTierConfig(userLevel)
	if tierConfig == nil {
		return nil, fmt.Errorf("tier config not found for level %d", userLevel)
	}
	maxTopics := tierConfig.MaxBlockedTopics
	if maxTopics == 0 {
		return nil, fmt.Errorf("blocked topic limit is zero for level %d", userLevel)
	}

	if _, err := am.k.AddBlockedTopicDeque(sdkCtx, owner, topic, uint32(maxTopics)); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Info("BlockTopic", "owner", owner, "topic", topic)

	if owner != "" && authority != govAuthority {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "BlockTopic"); err != nil {
			return nil, err
		}
	}

	return &types.MsgBlockTopicResponse{}, nil
}

// UnblockTopic unblocks a topic (persisted on-chain)
func (am AppModule) UnblockTopic(ctx context.Context, req *types.MsgUnblockTopic) (*types.MsgUnblockTopicResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	params := am.k.GetParams(sdkCtx)
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()

	var owner string
	var userLevel int
	if authority == govAuthority {
		owner = authority
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		owner = sdk.AccAddress(pub.Address()).String()
		core, err := am.requireUsername(sdkCtx, owner, "UnblockTopic")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	topic := strings.ToLower(strings.TrimSpace(req.GetTopic()))
	if err := validateBlockedTopicPattern(topic, uint64(params.MaxTopicSize), uint64(params.MinTopicSize)); err != nil {
		return nil, fmt.Errorf("invalid topic: %w", err)
	}

	if err := am.k.RemoveBlockedTopic(sdkCtx, owner, topic); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Info("UnblockTopic", "owner", owner, "topic", topic)

	if owner != "" && authority != govAuthority {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "UnblockTopic"); err != nil {
			return nil, err
		}
	}

	return &types.MsgUnblockTopicResponse{}, nil
}

// FollowUser follows a user (adds to followed users list, capped deque)
func (am AppModule) FollowUser(ctx context.Context, req *types.MsgFollowUser) (*types.MsgFollowUserResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	params := am.k.GetParams(sdkCtx)
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	user := strings.ToLower(strings.TrimSpace(req.GetUser()))

	var owner string
	if authority == govAuthority {
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		owner = target
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		derived := sdk.AccAddress(pub.Address()).String()
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		if derived != target {
			return nil, fmt.Errorf("envelope_pubkey must derive to target")
		}
		owner = target
	}

	if _, err := sdk.AccAddressFromBech32(user); err != nil {
		return nil, fmt.Errorf("invalid user address: %s", user)
	}

	if owner == user {
		return nil, fmt.Errorf("cannot follow yourself")
	}

	var userLevel int
	if authority != govAuthority {
		core, err := am.requireUsername(sdkCtx, owner, "FollowUser")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	// Mutual exclusion: following a user removes them from the blocked list (O(1) delete)
	if err := am.k.RemoveBlockedUser(sdkCtx, owner, user); err != nil {
		return nil, err
	}

	// A nil tier config is a governance fault, not a cue to invent a limit.
	// Each of these eight sites used to substitute a different hardcoded number,
	// none of them matching DefaultTiers, while Edit hard-failed on exactly the
	// same condition (review I-5). Reachable only through a governance
	// MsgSetLevel to a level in 2..9, where LevelToTierIndex returns -1.
	tierConfig := params.GetTierConfig(userLevel)
	if tierConfig == nil {
		return nil, fmt.Errorf("tier config not found for level %d", userLevel)
	}
	maxUsers := tierConfig.MaxFollowedUsers

	// O(1) duplicate check
	has, err := am.k.HasFollowedUser(sdkCtx, owner, user)
	if err != nil {
		return nil, err
	}
	if has {
		return &types.MsgFollowUserResponse{}, nil
	}
	// O(1) cap check
	userCount, err := am.k.CountFollowedUsers(sdkCtx, owner)
	if err != nil {
		return nil, fmt.Errorf("FollowUser: followed_users count for %s: %w", owner, err)
	}
	if uint64(userCount) >= maxUsers {
		return nil, fmt.Errorf("followed users limit reached (%d); unfollow a user first", maxUsers)
	}
	// O(1) write
	if _, err := am.k.AddFollowedUser(sdkCtx, owner, user); err != nil {
		return nil, err
	}

	// Bootstrap a core profile for a first-time follower. A list entry without a
	// core profile is inconsistent state, so neither the existence check nor the
	// write may be discarded (review L-1).
	_, hasProfile, err := am.k.GetProfileCore(sdkCtx, owner)
	if err != nil {
		return nil, fmt.Errorf("FollowUser: load profile for %s: %w", owner, err)
	}
	if !hasProfile {
		if err := am.updateProfileCore(sdkCtx, owner, func(c *types.ProfileCore) error { return nil }); err != nil {
			return nil, fmt.Errorf("FollowUser: bootstrap profile for %s: %w", owner, err)
		}
	}

	sdkCtx.Logger().Info("FollowUser", "owner", owner, "user", user)

	if authority != govAuthority {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "FollowUser"); err != nil {
			return nil, err
		}
	}

	return &types.MsgFollowUserResponse{}, nil
}

// UnfollowUser unfollows a user (removes from followed users list)
func (am AppModule) UnfollowUser(ctx context.Context, req *types.MsgUnfollowUser) (*types.MsgUnfollowUserResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	user := strings.ToLower(strings.TrimSpace(req.GetUser()))

	var owner string
	if authority == govAuthority {
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		owner = target
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		derived := sdk.AccAddress(pub.Address()).String()
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		if derived != target {
			return nil, fmt.Errorf("envelope_pubkey must derive to target")
		}
		owner = target
	}

	var userLevel int
	if authority != govAuthority {
		core, err := am.requireUsername(sdkCtx, owner, "UnfollowUser")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	// O(1) remove — idempotent, no error if not present
	if err := am.k.RemoveFollowedUser(sdkCtx, owner, user); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Info("UnfollowUser", "owner", owner, "user", user)

	if authority != govAuthority {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "UnfollowUser"); err != nil {
			return nil, err
		}
	}

	return &types.MsgUnfollowUserResponse{}, nil
}

// FollowTopic follows a topic (adds to followed topics list, capped deque)
func (am AppModule) FollowTopic(ctx context.Context, req *types.MsgFollowTopic) (*types.MsgFollowTopicResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	params := am.k.GetParams(sdkCtx)
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	topic := strings.ToLower(strings.TrimSpace(req.GetTopic()))

	var owner string
	if authority == govAuthority {
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		owner = target
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		derived := sdk.AccAddress(pub.Address()).String()
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		if derived != target {
			return nil, fmt.Errorf("envelope_pubkey must derive to target")
		}
		owner = target
	}

	var userLevel int
	if authority != govAuthority {
		core, err := am.requireUsername(sdkCtx, owner, "FollowTopic")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	if err := validateTopic(topic, uint64(params.MaxTopicSize), uint64(params.MinTopicSize)); err != nil {
		return nil, fmt.Errorf("invalid topic: %w", err)
	}

	// Mutual exclusion: following a topic removes matching blocked topic patterns.
	// Must iterate blocked topics because of wildcard pattern matching.
	blockedTopics, err := am.k.ListBlockedTopics(sdkCtx, owner)
	if err != nil {
		return nil, err
	}
	for _, t := range blockedTopics {
		if topicMatchesPattern(topic, t) {
			if err := am.k.RemoveBlockedTopic(sdkCtx, owner, t); err != nil {
				return nil, fmt.Errorf("FollowTopic: unblock %q for %s: %w", t, owner, err)
			}
		}
	}

	// A nil tier config is a governance fault, not a cue to invent a limit.
	// Each of these eight sites used to substitute a different hardcoded number,
	// none of them matching DefaultTiers, while Edit hard-failed on exactly the
	// same condition (review I-5). Reachable only through a governance
	// MsgSetLevel to a level in 2..9, where LevelToTierIndex returns -1.
	tierConfig := params.GetTierConfig(userLevel)
	if tierConfig == nil {
		return nil, fmt.Errorf("tier config not found for level %d", userLevel)
	}
	maxTopics := tierConfig.MaxFollowedTopics

	has, err := am.k.HasFollowedTopic(sdkCtx, owner, topic)
	if err != nil {
		return nil, err
	}
	if has {
		return &types.MsgFollowTopicResponse{}, nil
	}
	topicCount, err := am.k.CountFollowedTopics(sdkCtx, owner)
	if err != nil {
		return nil, fmt.Errorf("FollowTopic: followed_topics count for %s: %w", owner, err)
	}
	if uint64(topicCount) >= maxTopics {
		return nil, fmt.Errorf("followed topics limit reached (%d); unfollow a topic first", maxTopics)
	}
	if _, err := am.k.AddFollowedTopic(sdkCtx, owner, topic); err != nil {
		return nil, err
	}

	_, hasProfile, err := am.k.GetProfileCore(sdkCtx, owner)
	if err != nil {
		return nil, fmt.Errorf("FollowTopic: load profile for %s: %w", owner, err)
	}
	if !hasProfile {
		if err := am.updateProfileCore(sdkCtx, owner, func(c *types.ProfileCore) error { return nil }); err != nil {
			return nil, fmt.Errorf("FollowTopic: bootstrap profile for %s: %w", owner, err)
		}
	}

	sdkCtx.Logger().Info("FollowTopic", "owner", owner, "topic", topic)

	if authority != govAuthority {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "FollowTopic"); err != nil {
			return nil, err
		}
	}

	return &types.MsgFollowTopicResponse{}, nil
}

// UnfollowTopic unfollows a topic (removes from followed topics list)
func (am AppModule) UnfollowTopic(ctx context.Context, req *types.MsgUnfollowTopic) (*types.MsgUnfollowTopicResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	topic := strings.ToLower(strings.TrimSpace(req.GetTopic()))

	var owner string
	if authority == govAuthority {
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		owner = target
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		derived := sdk.AccAddress(pub.Address()).String()
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		if derived != target {
			return nil, fmt.Errorf("envelope_pubkey must derive to target")
		}
		owner = target
	}

	var userLevel int
	if authority != govAuthority {
		core, err := am.requireUsername(sdkCtx, owner, "UnfollowTopic")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	if err := am.k.RemoveFollowedTopic(sdkCtx, owner, topic); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Info("UnfollowTopic", "owner", owner, "topic", topic)

	if authority != govAuthority {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "UnfollowTopic"); err != nil {
			return nil, err
		}
	}

	return &types.MsgUnfollowTopicResponse{}, nil
}

// Delete validates and logs deletion of a post/comment (not persisted on-chain).
//
// SECURITY MODEL (enforced by indexer, NOT here):
// The blockchain accepts Delete messages from anyone - they just pay gas. This is
// intentional: on-chain validation would require storing post ownership data in the
// KV store, which is expensive and unnecessary.
//
// Authorization is enforced by the INDEXER (see indexer/message_processor.py):
//   - Governance: can delete any post
//   - Admin (level >= 100): can delete any post
//   - Regular user: can only delete posts they own
//
// If someone submits a Delete for a post they don't own, they waste gas but the
// indexer rejects it - the post remains visible. This is the intended design.
func (am AppModule) Delete(ctx context.Context, req *types.MsgDelete) (*types.MsgDeleteResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()

	var owner string
	var userLevel int
	if authority == govAuthority {
		// GOVERNANCE PATH: governance module is the "owner" for logging
		owner = authority
	} else {
		// NODE PATH: authority is the validator, owner is derived from envelope_pubkey
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		owner = sdk.AccAddress(pub.Address()).String()

		core, err := am.requireUsername(sdkCtx, owner, "Delete")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	if err := validateTxHash(target); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Info("Delete",
		"owner", owner,
		"target", target,
	)

	// Deduct gas fee from paid users
	gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
	if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "Delete"); err != nil {
		return nil, err
	}

	return &types.MsgDeleteResponse{}, nil
}

// DeleteUser permanently removes a user account.
// Authorization: self-signed (envelope_pubkey derives to target) or governance.
func (am AppModule) DeleteUser(ctx context.Context, req *types.MsgDeleteUser) (*types.MsgDeleteUserResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))

	if err := validateAddress(target); err != nil {
		return nil, fmt.Errorf("invalid target address: %w", err)
	}

	var actorType string
	if authority == govAuthority {
		actorType = "governance"
	} else {
		// Self-delete: envelope_pubkey must derive to target
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		derived := sdk.AccAddress(pub.Address()).String()
		if derived != target {
			return nil, fmt.Errorf("unauthorized: envelope_pubkey does not derive to target")
		}
		actorType = "self"
	}

	// Verify the profile exists and has a username
	bz, found, err := am.k.GetProfileCore(sdkCtx, target)
	if err != nil {
		return nil, fmt.Errorf("failed to load profile: %w", err)
	}
	if !found {
		return nil, fmt.Errorf("profile not found or already deleted for %s", target)
	}
	var core types.ProfileCore
	if err := json.Unmarshal(bz, &core); err != nil {
		return nil, fmt.Errorf("failed to unmarshal profile: %w", err)
	}
	if core.Username == "" {
		sdkCtx.Logger().Debug("requireUsername: empty username", "owner", target, "action", "DeleteUser")
		return nil, fmt.Errorf("username required: set a username before calling DeleteUser")
	}

	// Deduct relay gas fee for self-delete (relay node compensation)
	if actorType == "self" {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, target, int(core.Level), gasUsed, "DeleteUser"); err != nil {
			return nil, err
		}
	}

	// Execute the full deletion using the profile already decoded above, so the
	// keeper does not re-read it and swallow the failure (review M-3).
	sweptAmounts, err := am.k.DeleteUserState(sdkCtx, target, core.Username, core.SubscriptionExpiry)
	if err != nil {
		return nil, fmt.Errorf("delete user failed: %w", err)
	}

	sdkCtx.Logger().Info(logDelimiter)
	sdkCtx.Logger().Info("DeleteUser",
		"actor_type", actorType,
		"target", target,
		"username_released", core.Username,
		"swept_amounts", sweptAmounts.String(),
	)
	sdkCtx.Logger().Info(logDelimiter)

	return &types.MsgDeleteUserResponse{}, nil
}

// SendTokens sends tokens from signer to target.
func (am AppModule) SendTokens(ctx context.Context, req *types.MsgSendTokens) (*types.MsgSendTokensResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	sender := strings.ToLower(strings.TrimSpace(req.GetSender()))
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))

	var userLevel int
	if authority == govAuthority {
		// GOVERNANCE PATH: can send from any address
		if err := validateAddress(sender); err != nil {
			return nil, fmt.Errorf("invalid sender address: %w", err)
		}
	} else {
		// NODE PATH: envelope_pubkey must derive to SENDER
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		derived := sdk.AccAddress(pub.Address()).String()
		if derived != sender {
			return nil, fmt.Errorf("envelope_pubkey must derive to sender")
		}

		core, err := am.requireUsername(sdkCtx, sender, "SendTokens")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	if err := validateAddress(target); err != nil {
		return nil, err
	}

	// Validate amount
	if req.GetAmount() == 0 {
		return nil, fmt.Errorf("amount must be > 0")
	}

	// Parse addresses
	senderAddr, err := sdk.AccAddressFromBech32(sender)
	if err != nil {
		return nil, err
	}
	targetAddr, err := sdk.AccAddressFromBech32(target)
	if err != nil {
		return nil, err
	}

	// Check sender has sufficient balance for amount
	senderBalance := am.k.GetBalance(sdkCtx, sender, "umirage")
	if senderBalance.LT(sdkmath.NewIntFromUint64(req.GetAmount())) {
		return nil, fmt.Errorf("insufficient balance: have %s, need %d",
			senderBalance.String(), req.GetAmount())
	}

	// Transfer tokens from sender to target using bank module
	coins := sdk.NewCoins(sdk.NewCoin("umirage", sdkmath.NewIntFromUint64(req.GetAmount())))
	if err := am.k.SendCoins(sdkCtx, senderAddr, targetAddr, coins); err != nil {
		return nil, fmt.Errorf("failed to send tokens: %w", err)
	}

	sdkCtx.Logger().Info("SendTokens",
		"sender", sender,
		"target", target,
		"amount", req.GetAmount(),
	)

	// Deduct gas fee from paid users
	gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
	if err := am.deductRelayGasFee(sdkCtx, sender, userLevel, gasUsed, "SendTokens"); err != nil {
		return nil, err
	}

	return &types.MsgSendTokensResponse{}, nil
}

// SetLevel sets the user level for a given address (currently governance-only)
func (am AppModule) SetLevel(ctx context.Context, req *types.MsgSetLevel) (*types.MsgSetLevelResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))

	// For now, only governance can set levels
	if authority != govAuthority {
		return nil, fmt.Errorf("unauthorized: only governance can set levels (for now)")
	}

	// Validate target address
	if err := validateAddress(target); err != nil {
		return nil, fmt.Errorf("invalid target address: %w", err)
	}

	// Get existing profile core (must exist - can't set level on non-existent user)
	bz, found, err := am.k.GetProfileCore(sdkCtx, target)
	if err != nil {
		return nil, fmt.Errorf("failed to get profile: %w", err)
	}
	if !found {
		return nil, fmt.Errorf("user %s does not have a profile - cannot set level on non-existent user", target)
	}

	var core types.ProfileCore
	if err := json.Unmarshal(bz, &core); err != nil {
		return nil, fmt.Errorf("failed to unmarshal profile: %w", err)
	}

	// Validate level is a known tier
	newLevel := req.GetLevel()
	if types.LevelToTierIndex(int(newLevel)) < 0 {
		return nil, fmt.Errorf("invalid level %d: must be 0, 1, 10, or >= 100", newLevel)
	}

	core.Level = newLevel

	// Save profile core
	bz, err = json.Marshal(core)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal profile: %w", err)
	}
	if err := am.k.SetProfileCore(sdkCtx, target, bz); err != nil {
		return nil, fmt.Errorf("failed to save profile: %w", err)
	}

	sdkCtx.Logger().Info("SetLevel",
		"target", target,
		"level", req.GetLevel(),
	)

	return &types.MsgSetLevelResponse{}, nil
}

// PunishValidator slashes/jails/tombstones a validator (governance only)
func (am AppModule) PunishValidator(ctx context.Context, req *types.MsgPunishValidator) (*types.MsgPunishValidatorResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)

	// Verify authority is governance module
	if req.Authority != authtypes.NewModuleAddress(govtypes.ModuleName).String() {
		return nil, fmt.Errorf("unauthorized: only governance can punish validators")
	}

	valoper := strings.TrimSpace(req.Valoper)
	if valoper == "" {
		return nil, fmt.Errorf("valoper cannot be empty")
	}

	// Parse and clamp fraction
	fracStr := strings.TrimSpace(req.Fraction)
	if fracStr == "" {
		fracStr = "0"
	}
	frac, err := sdkmath.LegacyNewDecFromStr(fracStr)
	if err != nil {
		return nil, fmt.Errorf("invalid fraction: %w", err)
	}
	if frac.IsNegative() {
		frac = sdkmath.LegacyNewDec(0)
	}
	if frac.GT(sdkmath.LegacyNewDec(1)) {
		frac = sdkmath.LegacyNewDec(1)
	}

	if err := am.k.PunishValidator(sdkCtx, valoper, frac, req.Jail, req.Tombstone, strings.TrimSpace(req.Reason)); err != nil {
		return nil, err
	}

	// Log
	sdkCtx.Logger().Info("PunishValidator",
		"valoper", valoper,
		"fraction", frac.String(),
		"jail", req.Jail,
		"tombstone", req.Tombstone,
	)

	return &types.MsgPunishValidatorResponse{}, nil
}

// MintTokens mints new tokens to a target address (governance only)
func (am AppModule) MintTokens(ctx context.Context, req *types.MsgMintTokens) (*types.MsgMintTokensResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)

	if req.Authority != authtypes.NewModuleAddress(govtypes.ModuleName).String() {
		return nil, fmt.Errorf("unauthorized: only governance can mint")
	}

	target := strings.TrimSpace(req.Target)
	if target == "" {
		return nil, fmt.Errorf("target cannot be empty")
	}
	if req.Amount == 0 {
		return nil, fmt.Errorf("amount must be > 0")
	}

	if err := am.k.MintToAccount(sdkCtx, target, req.Amount); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Debug("MintTokens", "target", target, "amount", req.Amount, "reason", strings.TrimSpace(req.Reason))

	return &types.MsgMintTokensResponse{}, nil
}

// BurnTokens burns tokens from a target address (governance only)
func (am AppModule) BurnTokens(ctx context.Context, req *types.MsgBurnTokens) (*types.MsgBurnTokensResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)

	if req.Authority != authtypes.NewModuleAddress(govtypes.ModuleName).String() {
		return nil, fmt.Errorf("unauthorized: only governance can burn")
	}

	target := strings.TrimSpace(req.Target)
	if target == "" {
		return nil, fmt.Errorf("target cannot be empty")
	}
	if req.Amount == 0 {
		return nil, fmt.Errorf("amount must be > 0")
	}

	if err := am.k.BurnFromAccount(sdkCtx, target, req.Amount); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Debug("BurnTokens", "target", target, "amount", req.Amount, "reason", strings.TrimSpace(req.Reason))

	return &types.MsgBurnTokensResponse{}, nil
}

// Subscribe handles paid tier subscriptions (self or gift).
// When target == payer (or empty): self-subscribe with full setup.
// When target != payer: gift — payer pays, recipient's expiry extends by one period.
func (am AppModule) Subscribe(ctx context.Context, req *types.MsgSubscribe) (*types.MsgSubscribeResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	params := am.k.GetParams(sdkCtx)
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()
	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))

	var payer string
	var isGov bool
	if authority == govAuthority {
		// Governance path: target is the recipient, governance pays
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid target address: %w", err)
		}
		payer = target
		isGov = true
	} else {
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		derived, err := deriveOwnerFromPubkey(req.GetEnvelopePubkey())
		if err != nil {
			return nil, err
		}
		payer = derived
		isGov = false
	}

	// Determine recipient: if target is set and different from payer, it's a gift
	recipient := payer
	isGift := false
	if target != "" && target != payer && !isGov {
		if err := validateAddress(target); err != nil {
			return nil, fmt.Errorf("invalid gift target address: %w", err)
		}
		recipient = target
		isGift = true
	}

	// MsgSubscribe MUST be paid with tokens, not PoW
	if req.GetEnvelopePow() > 0 {
		return nil, fmt.Errorf("MsgSubscribe cannot use PoW, must pay with tokens")
	}

	requestedLevel := int(req.GetLevel())

	// Only levels 1 (Subscriber) and 10 (Agent) are valid
	if !types.ValidSubscriptionLevels[requestedLevel] {
		return nil, fmt.Errorf("invalid level %d: must be %d (Subscriber) or %d (Agent)", requestedLevel, types.LevelSubscriber, types.LevelAgent)
	}

	tierConfig := params.GetTierConfig(requestedLevel)
	if tierConfig == nil {
		return nil, fmt.Errorf("tier config not found for level %d", requestedLevel)
	}

	// Load recipient profile (must have a username)
	recipientCore, err := am.requireUsername(sdkCtx, recipient, "Subscribe")
	if err != nil {
		return nil, err
	}

	sdkCtx.Logger().Debug("Subscribe",
		"payer", payer,
		"recipient", recipient,
		"is_gift", isGift,
		"is_gov", isGov,
		"level", requestedLevel,
	)

	periodFee := tierConfig.PeriodFee

	if isGift {
		if recipientCore.Level > int32(requestedLevel) {
			return nil, fmt.Errorf("gift rejected: recipient level %d > requested %d", recipientCore.Level, requestedLevel)
		}
		// ── Gift path: payer pays, recipient's subscription extends ──
		var reserveAmount uint64
		if periodFee > 0 {
			balance := am.k.GetBalance(sdkCtx, payer, "umirage")
			if balance.LT(sdkmath.NewIntFromUint64(periodFee)) {
				return nil, fmt.Errorf("insufficient balance: need %d umirage, have %s", periodFee, balance.String())
			}

			reserve, burnAmount, err := types.SplitPeriodFee(periodFee, params.SubscriptionReserveBps)
			if err != nil {
				return nil, fmt.Errorf("Subscribe gift: fee split: %w", err)
			}
			reserveAmount = reserve

			if burnAmount > 0 {
				if err := am.k.BurnFromAccount(sdkCtx, payer, burnAmount); err != nil {
					return nil, fmt.Errorf("Subscribe gift: failed to burn fee: %w", err)
				}
			}
			if reserveAmount > 0 {
				if err := am.k.DeductFeeFromOwner(sdkCtx, payer, reserveAmount); err != nil {
					return nil, fmt.Errorf("Subscribe gift: failed to escrow reserve: %w", err)
				}
			}
		}

		// Remove old subscription index. Value has already moved, so a stale
		// index must reject the transaction rather than survive (review M-1).
		if recipientCore.SubscriptionExpiry > 0 {
			if err := am.k.RemoveSubscription(sdkCtx, recipient, recipientCore.SubscriptionExpiry); err != nil {
				return nil, fmt.Errorf("Subscribe gift: failed to remove old subscription index for %s: %w",
					recipient, err)
			}
		}

		// Extend expiry from max(currentExpiry, now) + period
		var newExpiry int64
		if params.SubscriptionPeriod > 0 {
			base := sdkCtx.BlockTime().Unix()
			if recipientCore.SubscriptionExpiry > base {
				base = recipientCore.SubscriptionExpiry
			}
			newExpiry, err = types.CheckedSubscriptionExpiry(base, params.SubscriptionPeriod)
			if err != nil {
				return nil, fmt.Errorf("Subscribe gift: expiry for %s: %w", recipient, err)
			}
		}

		recipientCore.Level = int32(requestedLevel)
		recipientCore.SubscriptionExpiry = newExpiry
		// Keep auto_renew unchanged for gifts
		recipientCore.ReserveFunds, err = types.CheckedAddUint64(recipientCore.ReserveFunds, reserveAmount)
		if err != nil {
			return nil, fmt.Errorf("Subscribe gift: reserve for %s: %w", recipient, err)
		}

		if newExpiry > 0 {
			if err := am.k.SetSubscription(sdkCtx, recipient, requestedLevel, newExpiry); err != nil {
				return nil, fmt.Errorf("Subscribe gift: failed to set subscription index for %s: %w",
					recipient, err)
			}
		}

		bz, err := json.Marshal(recipientCore)
		if err != nil {
			return nil, fmt.Errorf("failed to marshal profile: %w", err)
		}
		if err := am.k.SetProfileCore(sdkCtx, recipient, bz); err != nil {
			return nil, fmt.Errorf("failed to save profile: %w", err)
		}

		sdkCtx.Logger().Info("Subscribe (gift)",
			"payer", payer,
			"recipient", recipient,
			"level", requestedLevel,
			"period_fee", periodFee,
			"reserve_added", reserveAmount,
			"new_expiry", newExpiry,
			"auto_renew", recipientCore.AutoRenew,
		)
	} else {
		// ── Self-subscribe path (or governance): payer == recipient ──
		// Burn old reserve
		if recipientCore.ReserveFunds > 0 {
			if err := am.k.BurnFromModuleAmount(sdkCtx, recipientCore.ReserveFunds); err != nil {
				return nil, fmt.Errorf("Subscribe: failed to burn old reserve: %w", err)
			}
			recipientCore.ReserveFunds = 0
		}

		var reserveAmount uint64
		if periodFee > 0 {
			balance := am.k.GetBalance(sdkCtx, payer, "umirage")
			if balance.LT(sdkmath.NewIntFromUint64(periodFee)) {
				return nil, fmt.Errorf("insufficient balance: need %d umirage, have %s", periodFee, balance.String())
			}

			reserve, burnAmount, err := types.SplitPeriodFee(periodFee, params.SubscriptionReserveBps)
			if err != nil {
				return nil, fmt.Errorf("Subscribe: fee split: %w", err)
			}
			reserveAmount = reserve

			if burnAmount > 0 {
				if err := am.k.BurnFromAccount(sdkCtx, payer, burnAmount); err != nil {
					return nil, fmt.Errorf("Subscribe: failed to burn fee: %w", err)
				}
			}
			if reserveAmount > 0 {
				if err := am.k.DeductFeeFromOwner(sdkCtx, payer, reserveAmount); err != nil {
					return nil, fmt.Errorf("Subscribe: failed to escrow reserve: %w", err)
				}
			}
		}

		// Remove old subscription index
		if recipientCore.SubscriptionExpiry > 0 {
			if err := am.k.RemoveSubscription(sdkCtx, recipient, recipientCore.SubscriptionExpiry); err != nil {
				return nil, fmt.Errorf("Subscribe: failed to remove old subscription index for %s: %w",
					recipient, err)
			}
		}

		var newExpiry int64
		if params.SubscriptionPeriod > 0 {
			newExpiry, err = types.CheckedSubscriptionExpiry(sdkCtx.BlockTime().Unix(), params.SubscriptionPeriod)
			if err != nil {
				return nil, fmt.Errorf("Subscribe: expiry for %s: %w", recipient, err)
			}
		}

		recipientCore.Level = int32(requestedLevel)
		recipientCore.SubscriptionExpiry = newExpiry
		recipientCore.AutoRenew = true
		recipientCore.ReserveFunds = reserveAmount

		if newExpiry > 0 {
			if err := am.k.SetSubscription(sdkCtx, recipient, requestedLevel, newExpiry); err != nil {
				return nil, fmt.Errorf("Subscribe: failed to set subscription index for %s: %w",
					recipient, err)
			}
		}

		bz, err := json.Marshal(recipientCore)
		if err != nil {
			return nil, fmt.Errorf("failed to marshal profile: %w", err)
		}
		if err := am.k.SetProfileCore(sdkCtx, recipient, bz); err != nil {
			return nil, fmt.Errorf("failed to save profile: %w", err)
		}

		sdkCtx.Logger().Info("Subscribe (self)",
			"owner", payer,
			"level", requestedLevel,
			"period_fee", periodFee,
			"reserve", reserveAmount,
			"expiry", newExpiry,
			"auto_renew", true,
			"subscription_period", params.SubscriptionPeriod,
		)
	}

	return &types.MsgSubscribeResponse{}, nil
}

// SetAutoRenewal sets the auto_renew flag for a user's subscription.
func (am AppModule) SetAutoRenewal(ctx context.Context, req *types.MsgSetAutoRenewal) (*types.MsgSetAutoRenewalResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()

	// Derive owner from envelope_pubkey
	if len(req.GetEnvelopePubkey()) != 33 {
		return nil, fmt.Errorf("invalid envelope_pubkey length")
	}
	owner, err := deriveOwnerFromPubkey(req.GetEnvelopePubkey())
	if err != nil {
		return nil, err
	}

	core, err := am.requireUsername(sdkCtx, owner, "SetAutoRenewal")
	if err != nil {
		return nil, err
	}

	// MsgSetAutoRenewal MUST be paid with reserve, not PoW
	if req.GetEnvelopePow() > 0 {
		return nil, fmt.Errorf("MsgSetAutoRenewal cannot use PoW, must pay with reserve")
	}

	targetAuto := req.GetAutoRenew()

	// Prevent enabling auto-renew for free tier or when no active subscription exists
	if targetAuto {
		if core.Level <= 0 {
			return nil, fmt.Errorf("cannot enable auto-renew for free tier")
		}
		if core.SubscriptionExpiry <= 0 {
			return nil, fmt.Errorf("cannot enable auto-renew without active subscription")
		}
	}

	previousAuto := core.AutoRenew
	if previousAuto == targetAuto {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, int(core.Level), gasUsed, "SetAutoRenewal"); err != nil {
			return nil, err
		}
		return &types.MsgSetAutoRenewalResponse{}, nil
	}

	core.AutoRenew = targetAuto

	bz, err := json.Marshal(core)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal profile: %w", err)
	}
	if err := am.k.SetProfileCore(sdkCtx, owner, bz); err != nil {
		return nil, fmt.Errorf("failed to save profile: %w", err)
	}

	sdkCtx.Logger().Info("SetAutoRenewal",
		"owner", owner,
		"level", core.Level,
		"auto_renew", core.AutoRenew,
		"previous_auto_renew", previousAuto,
		"subscription_expiry", core.SubscriptionExpiry,
	)

	// Deduct gas fee from paid users using their escrowed reserve
	gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
	if err := am.deductRelayGasFee(sdkCtx, owner, int(core.Level), gasUsed, "SetAutoRenewal"); err != nil {
		return nil, err
	}

	return &types.MsgSetAutoRenewalResponse{}, nil
}

// Award handler accepts MsgAward, burns MIRAGE (free for admins level >= 100).
func (am AppModule) Award(ctx context.Context, req *types.MsgAward) (*types.MsgAwardResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	authority := req.GetAuthority()

	var owner string
	var userLevel int
	if authority != govAuthority {
		if len(req.GetEnvelopePubkey()) != 33 {
			return nil, fmt.Errorf("invalid envelope_pubkey length")
		}
		pub := secp256k1.PubKey{Key: req.GetEnvelopePubkey()}
		owner = sdk.AccAddress(pub.Address()).String()

		core, err := am.requireUsername(sdkCtx, owner, "Award")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	} else {
		owner = authority
	}

	target := strings.ToLower(strings.TrimSpace(req.GetTarget()))
	if target == "" {
		return nil, fmt.Errorf("award target cannot be empty")
	}
	if err := validateTxHash(target); err != nil {
		return nil, err
	}

	awardType := strings.TrimSpace(req.GetAwardType())
	if awardType == "" {
		return nil, fmt.Errorf("award_type cannot be empty")
	}

	params := am.k.GetParams(sdkCtx)
	ac := params.GetAwardConfig(awardType)
	if ac == nil {
		return nil, fmt.Errorf("unknown award_type: %s", awardType)
	}

	isAdmin := userLevel >= 100
	burnAmount := ac.Cost
	if isAdmin {
		burnAmount = 0
	}

	if burnAmount > 0 {
		if err := am.k.BurnFromAccount(sdkCtx, owner, burnAmount); err != nil {
			return nil, fmt.Errorf("failed to burn award cost: %w", err)
		}
	}

	sdkCtx.Logger().Info("Award",
		"owner", owner,
		"target", target,
		"award_type", awardType,
		"burned", burnAmount,
		"admin", isAdmin,
	)

	if owner != "" && authority != govAuthority {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		if err := am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "Award"); err != nil {
			return nil, err
		}
	}

	return &types.MsgAwardResponse{}, nil
}
