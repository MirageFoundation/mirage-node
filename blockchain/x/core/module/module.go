package core

import (
	"context"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"strings"
	"unicode/utf8"

	"cosmossdk.io/core/appmodule"
	sdkmath "cosmossdk.io/math"
	"github.com/cosmos/cosmos-sdk/client"
	"github.com/cosmos/cosmos-sdk/codec"
	codectypes "github.com/cosmos/cosmos-sdk/codec/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/cosmos/cosmos-sdk/types/module"
	"github.com/cosmos/cosmos-sdk/types/query"

	// txtypes removed; no longer needed
	"github.com/grpc-ecosystem/grpc-gateway/runtime"
	"google.golang.org/grpc"

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
	if userLevel >= 100 {
		if err := am.k.DeductFeeFromOwner(ctx, owner, fee); err != nil {
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
		if _, found, _ := am.k.GetProfileCore(sdkCtx, owner); !found {
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
// window, reconcile reserved module profiles, and periodically clean
// up counters.
//
// FAIL-FAST CONTRACT (consensus-critical writes only):
// RecordRecentBlockHash failures propagate as a non-nil return, which
// the SDK turns into a chain halt. The on-chain recent-block-hashes
// window is consensus-critical state read by the PoW ante; a per-node
// write failure here would cause per-node tx-acceptance divergence on
// subsequent blocks, which is strictly worse than a clean halt
// detected by the auto-recovery watchdog.
//
// Non-consensus-critical write failures (BurnAllFromModuleName(fee_collector),
// MintIfNeeded, SetCurrentDifficulty, ClaimUsername/SetProfileCore for
// reserved module profiles, CleanupOldCounters) are still logged and
// the corresponding state simply does not update this block; those
// failures affect ALL nodes equally (same operation, same in-memory
// state) and so do not cause divergence.
func (am AppModule) BeginBlock(ctx context.Context) error {
	sdkCtx := sdk.UnwrapSDKContext(ctx)

	if err := am.k.BurnAllFromModuleName(sdkCtx, authtypes.FeeCollectorName); err != nil {
		sdkCtx.Logger().Error("BeginBlock: BurnAllFromModuleName(fee_collector) failed; fees left in collector", "err", err)
	}
	// NOTE: Do NOT burn the core module account balance here. It holds user reserve funds.
	// MintIfNeeded is defined to always return nil; the check is defensive.
	if err := am.k.MintIfNeeded(sdkCtx); err != nil {
		sdkCtx.Logger().Error("BeginBlock: MintIfNeeded returned error (should be impossible)", "err", err)
	}

	// Initialize difficulty if not set (base step = 0). If this fails the
	// next block will retry; do not halt.
	params := am.k.GetParams(sdkCtx)
	if !am.k.HasCurrentDifficulty(sdkCtx) {
		if err := am.k.SetCurrentDifficulty(sdkCtx, keeper.BaseDifficultySteps); err != nil {
			sdkCtx.Logger().Error("BeginBlock: SetCurrentDifficulty(base) failed; will retry next block", "err", err)
		}
	}

	// Record the previous block's hash into the on-chain recent-block-hashes
	// window. This is consensus-critical state used by the PoW ante to
	// validate that an envelope's last_block_hash references a recent
	// committed block. The window MUST be identical across all nodes; a
	// state-write failure here causes per-node window divergence -> later
	// per-node tx-acceptance divergence -> app-hash divergence. Halt the
	// chain via the propagated error so the auto-recovery watchdog can
	// state-sync from healthy peers.
	lastHash := strings.ToLower(hex.EncodeToString(sdkCtx.BlockHeader().LastBlockId.Hash))
	if err := am.k.RecordRecentBlockHash(sdkCtx, lastHash, uint32(params.BlockHashWindow)); err != nil {
		sdkCtx.Logger().Error("CONSENSUS_FATAL:RECENT_HASHES_WRITE BeginBlock; halting chain (auto-recovery will state-sync)",
			"height", sdkCtx.BlockHeight(), "err", err)
		return err
	}

	// Ensure reserved module account profiles exist even if they were absent at genesis
	for _, modName := range reservedModuleAccountNames() {
		addr := authtypes.NewModuleAddress(modName).String()
		if _, found, _ := am.k.GetProfileCore(sdkCtx, addr); !found {
			username := reservedUsernameForModule(modName)
			_ = am.k.ClaimUsername(sdkCtx, username, addr)
			if bz, err := json.Marshal(types.ProfileCore{Owner: addr, Username: username}); err == nil {
				_ = am.k.SetProfileCore(sdkCtx, addr, bz)
			}
		}
	}

	// Faucet username is set during network bootstrap via a direct tx.

	// Cleanup old counters periodically (every 100 blocks). If this fails,
	// stale counter rows linger until the next successful sweep; never halt.
	if sdkCtx.BlockHeight()%100 == 0 {
		if err := am.k.CleanupOldCounters(sdkCtx, params); err != nil {
			sdkCtx.Logger().Error("BeginBlock: CleanupOldCounters failed; will retry next sweep", "err", err)
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
// Non-consensus-critical write failures (PruneExpiredNonces,
// SetCurrentDifficulty, SetConsecutiveLowUsage, etc.) are still logged and
// the corresponding state simply does not update this block; those failures
// affect ALL nodes equally (same operation, same in-memory state) and so do
// not cause divergence.
func (am AppModule) EndBlock(ctx context.Context) error {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	params := am.k.GetParams(sdkCtx)

	if pruned, err := am.k.PruneExpiredNonces(sdkCtx, sdkCtx.BlockTime().Unix()); err != nil {
		sdkCtx.Logger().Error("EndBlock: failed to prune expired nonces", "err", err)
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
				sdkCtx.Logger().Error("EndBlock: SetCurrentDifficulty (busy increase) failed; will retry next block",
					"old", currentDifficulty, "new", newDifficulty, "err", err)
			} else {
				if err := am.k.ClearPoWWindow(sdkCtx, params); err != nil {
					sdkCtx.Logger().Error("EndBlock: ClearPoWWindow (busy increase) failed; counts may carry over",
						"err", err)
				}
				sdkCtx.Logger().Info("Increased PoW difficulty due to busy window",
					"old_difficulty", currentDifficulty, "new_difficulty", newDifficulty)
			}
		}
		if err := am.k.SetConsecutiveLowUsage(sdkCtx, 0); err != nil {
			sdkCtx.Logger().Error("EndBlock: SetConsecutiveLowUsage reset failed after busy window",
				"err", err)
		}
		return nil
	}

	// Calm window: increment consecutive calm sequence
	if messageCount < params.PowCalmPeriodDefinition {
		calmSeq++
		if err := am.k.SetConsecutiveLowUsage(sdkCtx, calmSeq); err != nil {
			sdkCtx.Logger().Error("EndBlock: SetConsecutiveLowUsage (calm increment) failed; sequence will not advance this block",
				"calm_seq", calmSeq, "err", err)
			return nil
		}
		if calmSeq >= params.PowCalmSequenceThreshold {
			newDifficulty := currentDifficulty
			if currentDifficulty > keeper.BaseDifficultySteps {
				newDifficulty = currentDifficulty - 1
			}
			if newDifficulty != currentDifficulty {
				if err := am.k.SetCurrentDifficulty(sdkCtx, newDifficulty); err != nil {
					sdkCtx.Logger().Error("EndBlock: SetCurrentDifficulty (calm decrease) failed; will retry next qualifying block",
						"old", currentDifficulty, "new", newDifficulty, "err", err)
				} else {
					if err := am.k.ClearPoWWindow(sdkCtx, params); err != nil {
						sdkCtx.Logger().Error("EndBlock: ClearPoWWindow (calm decrease) failed; counts may carry over",
							"err", err)
					}
					sdkCtx.Logger().Info("Decreased PoW difficulty due to calm sequence",
						"old_difficulty", currentDifficulty, "new_difficulty", newDifficulty,
						"calm_sequence", calmSeq)
				}
			}
			// reset sequence after decreasing
			if err := am.k.SetConsecutiveLowUsage(sdkCtx, 0); err != nil {
				sdkCtx.Logger().Error("EndBlock: SetConsecutiveLowUsage reset failed after calm decrease",
					"err", err)
			}
		}
		return nil
	}

	// Neither busy nor calm → reset sequence
	if calmSeq > 0 {
		_ = am.k.SetConsecutiveLowUsage(sdkCtx, 0)
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

		// If subscription_period is 0, it's one-time payment, no renewal needed
		if params.SubscriptionPeriod == 0 {
			continue
		}

		// Load profile core.
		// FAIL-FAST: an expired-subscription record without a readable profile
		// is a state inconsistency. Silently `continue`-ing on one node while
		// peers (with intact state) renew/expire the subscription produces a
		// per-node state divergence -> app-hash divergence. Returning the
		// error from EndBlock halts the chain cleanly so the auto-recovery
		// watchdog can state-sync from healthy peers, which is strictly
		// safer than silent divergence.
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
		if core.ReserveFunds > 0 {
			if err := am.k.BurnFromModuleAmount(sdkCtx, core.ReserveFunds); err != nil {
				return fmt.Errorf("processSubscriptions: failed to burn reserve for %s: %w", sub.Address, err)
			}
			sdkCtx.Logger().Info("processSubscriptions: burned leftover reserve",
				"address", sub.Address, "reserve", core.ReserveFunds)
			core.ReserveFunds = 0
		}

		// Get tier config for current level using canonical level→tier mapping
		tierIdx := types.LevelToTierIndex(int(core.Level))
		if tierIdx <= 0 {
			// Free tier (0) or invalid level (-1) — nothing to renew
			continue
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
				// Integer reserve calculation: basis points to avoid float64 precision loss.
				// SubscriptionReservePercent is [0,1]; multiply by 10000 for basis-point math.
				reserveBps := uint64(params.SubscriptionReservePercent * 10000)
				if reserveBps > 10000 {
					reserveBps = 10000
				}
				reserveAmount := periodFee * reserveBps / 10000
				burnAmount := periodFee - reserveAmount

				// Burn non-reserve portion
				if burnAmount > 0 {
					if err := am.k.BurnFromAccount(sdkCtx, sub.Address, burnAmount); err != nil {
						previousLevel := core.Level
						sdkCtx.Logger().Error("processSubscriptions: failed to burn fee portion",
							"address", sub.Address, "err", err)
						core.Level = 0
						core.SubscriptionExpiry = 0
						sdkCtx.EventManager().EmitEvent(sdk.NewEvent("subscription_expired",
							sdk.NewAttribute("address", sub.Address),
							sdk.NewAttribute("previous_level", fmt.Sprintf("%d", previousLevel)),
							sdk.NewAttribute("reason", "renewal_burn_failed")))
						goto saveProfile
					}
				}

				// Escrow reserve portion to module
				if reserveAmount > 0 {
					if err := am.k.DeductFeeFromOwner(sdkCtx, sub.Address, reserveAmount); err != nil {
						previousLevel := core.Level
						sdkCtx.Logger().Error("processSubscriptions: failed to escrow reserve",
							"address", sub.Address, "err", err)
						core.Level = 0
						core.SubscriptionExpiry = 0
						sdkCtx.EventManager().EmitEvent(sdk.NewEvent("subscription_expired",
							sdk.NewAttribute("address", sub.Address),
							sdk.NewAttribute("previous_level", fmt.Sprintf("%d", previousLevel)),
							sdk.NewAttribute("reason", "renewal_escrow_failed")))
						goto saveProfile
					}
				}

				// Renewal successful
				newExpiry := currentTime + int64(params.SubscriptionPeriod)*60
				core.SubscriptionExpiry = newExpiry
				core.ReserveFunds = reserveAmount

				// Re-index with new expiry
				if err := am.k.SetSubscription(sdkCtx, sub.Address, int(core.Level), newExpiry); err != nil {
					sdkCtx.Logger().Error("processSubscriptions: failed to set new subscription index",
						"address", sub.Address, "err", err)
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
		// Save updated profile core
		newBz, err := json.Marshal(core)
		if err != nil {
			sdkCtx.Logger().Error("processSubscriptions: failed to marshal profile",
				"address", sub.Address, "err", err)
			continue
		}
		if err := am.k.SetProfileCore(sdkCtx, sub.Address, newBz); err != nil {
			sdkCtx.Logger().Error("processSubscriptions: failed to save profile",
				"address", sub.Address, "err", err)
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
		return nil, fmt.Errorf("profile not found for address: %s", address)
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
	var skippedCorrupt int
	for _, data := range profilesData {
		var core types.ProfileCore
		if err := json.Unmarshal(data, &core); err != nil {
			skippedCorrupt++
			continue // Skip invalid profiles
		}

		// Load all lists via per-entry iterators
		agents, _ := am.k.ListEnabledAgentsOrdered(sdkCtx, core.Owner)
		users, _ := am.k.ListFollowedUsers(sdkCtx, core.Owner)
		topics, _ := am.k.ListFollowedTopics(sdkCtx, core.Owner)
		blockedUsers, _ := am.k.ListBlockedUsers(sdkCtx, core.Owner)
		blockedPosts, _ := am.k.ListBlockedPosts(sdkCtx, core.Owner)
		blockedTopics, _ := am.k.ListBlockedTopics(sdkCtx, core.Owner)

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

	if skippedCorrupt > 0 {
		sdkCtx.Logger().Error("GetProfiles: skipped corrupt profile rows", "count", skippedCorrupt)
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

func applyParamUpdates(current types.Params, updates types.Params) (types.Params, []string) {
	var changed []string
	if updates.MintInterval != 0 {
		current.MintInterval = updates.MintInterval
		changed = append(changed, "mint_interval")
	}
	if updates.MintQuantity != 0 {
		current.MintQuantity = updates.MintQuantity
		changed = append(changed, "mint_quantity")
	}
	if updates.MintDynamicCreditCap != 0 {
		current.MintDynamicCreditCap = updates.MintDynamicCreditCap
		changed = append(changed, "mint_dynamic_credit_cap")
	}
	if updates.MintDynamicSplit != 0 {
		current.MintDynamicSplit = updates.MintDynamicSplit
		changed = append(changed, "mint_dynamic_split")
	}
	if updates.MinDifficulty != 0 {
		current.MinDifficulty = updates.MinDifficulty
		changed = append(changed, "min_difficulty")
	}
	if updates.PowMessageWindow != 0 {
		current.PowMessageWindow = updates.PowMessageWindow
		changed = append(changed, "pow_message_window")
	}
	if updates.PowMessageLimit != 0 {
		current.PowMessageLimit = updates.PowMessageLimit
		changed = append(changed, "pow_message_limit")
	}
	if updates.PowCalmPeriodDefinition != 0 {
		current.PowCalmPeriodDefinition = updates.PowCalmPeriodDefinition
		changed = append(changed, "pow_calm_period_definition")
	}
	if updates.PowCalmSequenceThreshold != 0 {
		current.PowCalmSequenceThreshold = updates.PowCalmSequenceThreshold
		changed = append(changed, "pow_calm_sequence_threshold")
	}
	if updates.PowDifficultyAllowance != 0 {
		current.PowDifficultyAllowance = updates.PowDifficultyAllowance
		changed = append(changed, "pow_difficulty_allowance")
	}
	if updates.PowDifficultyStep != 0 {
		current.PowDifficultyStep = updates.PowDifficultyStep
		changed = append(changed, "pow_difficulty_step")
	}
	if updates.BlockHashWindow != 0 {
		current.BlockHashWindow = updates.BlockHashWindow
		changed = append(changed, "block_hash_window")
	}
	if updates.MinUsernameSize != 0 {
		current.MinUsernameSize = updates.MinUsernameSize
		changed = append(changed, "min_username_size")
	}
	if updates.MaxUsernameSize != 0 {
		current.MaxUsernameSize = updates.MaxUsernameSize
		changed = append(changed, "max_username_size")
	}
	if updates.MinTopicSize != 0 {
		current.MinTopicSize = updates.MinTopicSize
		changed = append(changed, "min_topic_size")
	}
	if updates.MaxTopicSize != 0 {
		current.MaxTopicSize = updates.MaxTopicSize
		changed = append(changed, "max_topic_size")
	}
	if updates.SubscriptionPeriod != 0 {
		current.SubscriptionPeriod = updates.SubscriptionPeriod
		changed = append(changed, "subscription_period")
	}
	if updates.SubscriptionReservePercent != 0 {
		current.SubscriptionReservePercent = updates.SubscriptionReservePercent
		changed = append(changed, "subscription_reserve_percent")
	}
	if len(updates.Tiers) != 0 {
		current.Tiers = updates.Tiers
		changed = append(changed, "tiers")
	}
	if updates.RelayMinGasPrice != 0 {
		current.RelayMinGasPrice = updates.RelayMinGasPrice
		changed = append(changed, "relay_min_gas_price")
	}
	if updates.RelayMaxGasFee != 0 {
		current.RelayMaxGasFee = updates.RelayMaxGasFee
		changed = append(changed, "relay_max_gas_fee")
	}
	if updates.MaxEnvelopeAge != 0 {
		current.MaxEnvelopeAge = updates.MaxEnvelopeAge
		changed = append(changed, "max_envelope_age")
	}
	if len(updates.BridgeChains) != 0 {
		current.BridgeChains = updates.BridgeChains
		changed = append(changed, "bridge_chains")
	}
	if updates.BridgeAttestationThreshold != 0 {
		current.BridgeAttestationThreshold = updates.BridgeAttestationThreshold
		changed = append(changed, "bridge_attestation_threshold")
	}
	if len(updates.AwardConfigs) != 0 {
		current.AwardConfigs = updates.AwardConfigs
		changed = append(changed, "award_configs")
	}
	return current, changed
}

// UpdateParams stores new params
func (am AppModule) UpdateParams(ctx context.Context, req *types.MsgUpdateParams) (*types.MsgUpdateParamsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	// Only governance authority may update params
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	if strings.TrimSpace(req.GetAuthority()) != govAuthority {
		return nil, fmt.Errorf("unauthorized: only governance authority can update params")
	}

	current := am.k.GetParams(sdkCtx)
	updated, changed := applyParamUpdates(current, req.Params)
	if err := updated.Validate(); err != nil {
		return nil, fmt.Errorf("invalid params: %w", err)
	}
	if err := am.k.SetParams(sdkCtx, updated); err != nil {
		return nil, err
	}
	sdkCtx.Logger().Debug("UpdateParams applied", "fields", strings.Join(changed, ","))
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

	// Load existing core profile
	var core types.ProfileCore
	if old, found, _ := am.k.GetProfileCore(sdkCtx, owner); found {
		_ = json.Unmarshal(old, &core)
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
	agents, _ := am.k.ListEnabledAgentsOrdered(sdkCtx, owner)
	tierConfig := params.GetTierConfig(int(core.Level))
	maxAgents := uint64(5)
	if tierConfig != nil {
		maxAgents = tierConfig.MaxEnabledAgents
	}

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

	// Load lists via per-entry iterators
	if agents, err := am.k.ListEnabledAgentsOrdered(sdkCtx, owner); err == nil {
		prof.EnabledAgents = agents
	}
	if users, err := am.k.ListFollowedUsers(sdkCtx, owner); err == nil {
		prof.FollowedUsers = users
	}
	if topics, err := am.k.ListFollowedTopics(sdkCtx, owner); err == nil {
		prof.FollowedTopics = topics
	}
	if blocked, err := am.k.ListBlockedUsers(sdkCtx, owner); err == nil {
		prof.BlockedUsers = blocked
	}
	if posts, err := am.k.ListBlockedPosts(sdkCtx, owner); err == nil {
		prof.BlockedPosts = posts
	}
	if blockedTopics, err := am.k.ListBlockedTopics(sdkCtx, owner); err == nil {
		prof.BlockedTopics = blockedTopics
	}

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
	if old, found, _ := am.k.GetProfileCore(sdkCtx, owner); found {
		var prev types.ProfileCore
		_ = json.Unmarshal(old, &prev)
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

	// Release previous username if changing
	if prevUsername != "" && !strings.EqualFold(prevUsername, username) {
		_ = am.k.ReleaseUsername(sdkCtx, prevUsername, owner)
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
		maxLen := tierConfig.MaxBiographyLength
		if maxLen > 0 && uint64(utf8.RuneCountInString(biography)) > maxLen {
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
	tierConfig := params.GetTierConfig(userLevel)
	maxAgents := 5
	if tierConfig != nil {
		maxAgents = int(tierConfig.MaxEnabledAgents)
	}

	has, err := am.k.HasEnabledAgent(sdkCtx, owner, agent)
	if err != nil {
		return nil, err
	}
	if has {
		return &types.MsgEnableAgentResponse{}, nil
	}
	if int(am.k.CountEnabledAgents(sdkCtx, owner)) >= maxAgents {
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
	tierConfig := params.GetTierConfig(userLevel)
	maxAgents := 5
	if tierConfig != nil {
		maxAgents = int(tierConfig.MaxEnabledAgents)
	}

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

	if _, found, _ := am.k.GetProfileCore(sdkCtx, owner); !found {
		if err := am.updateProfileCore(sdkCtx, owner, func(c *types.ProfileCore) error {
			return nil
		}); err != nil {
			sdkCtx.Logger().Error("SetAgents: failed to create profile", "owner", owner, "err", err.Error())
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

	tierConfig := params.GetTierConfig(userLevel)
	maxPosts := uint64(25)
	if tierConfig != nil {
		maxPosts = tierConfig.MaxBlockedPosts
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

	// Mutual exclusion: blocking a user removes them from followed list (O(1))
	_ = am.k.RemoveFollowedUser(sdkCtx, owner, target)

	tierConfig := params.GetTierConfig(userLevel)
	maxUsers := uint64(10)
	if tierConfig != nil {
		maxUsers = tierConfig.MaxBlockedUsers
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
			_ = am.k.RemoveFollowedTopic(sdkCtx, owner, t)
		}
	}

	tierConfig := params.GetTierConfig(userLevel)
	maxTopics := uint64(10)
	if tierConfig != nil {
		maxTopics = tierConfig.MaxBlockedTopics
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

	tierConfig := params.GetTierConfig(userLevel)
	maxUsers := uint64(25)
	if tierConfig != nil {
		maxUsers = tierConfig.MaxFollowedUsers
	}

	// O(1) duplicate check
	has, err := am.k.HasFollowedUser(sdkCtx, owner, user)
	if err != nil {
		return nil, err
	}
	if has {
		return &types.MsgFollowUserResponse{}, nil
	}
	// O(1) cap check
	if uint64(am.k.CountFollowedUsers(sdkCtx, owner)) >= maxUsers {
		return nil, fmt.Errorf("followed users limit reached (%d); unfollow a user first", maxUsers)
	}
	// O(1) write
	if _, err := am.k.AddFollowedUser(sdkCtx, owner, user); err != nil {
		return nil, err
	}

	if _, found, _ := am.k.GetProfileCore(sdkCtx, owner); !found {
		_ = am.updateProfileCore(sdkCtx, owner, func(c *types.ProfileCore) error { return nil })
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
			_ = am.k.RemoveBlockedTopic(sdkCtx, owner, t)
		}
	}

	tierConfig := params.GetTierConfig(userLevel)
	maxTopics := uint64(50)
	if tierConfig != nil {
		maxTopics = tierConfig.MaxFollowedTopics
	}

	has, err := am.k.HasFollowedTopic(sdkCtx, owner, topic)
	if err != nil {
		return nil, err
	}
	if has {
		return &types.MsgFollowTopicResponse{}, nil
	}
	if uint64(am.k.CountFollowedTopics(sdkCtx, owner)) >= maxTopics {
		return nil, fmt.Errorf("followed topics limit reached (%d); unfollow a topic first", maxTopics)
	}
	if _, err := am.k.AddFollowedTopic(sdkCtx, owner, topic); err != nil {
		return nil, err
	}

	if _, found, _ := am.k.GetProfileCore(sdkCtx, owner); !found {
		_ = am.updateProfileCore(sdkCtx, owner, func(c *types.ProfileCore) error { return nil })
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

	// Execute the full deletion
	usernameReleased, sweptAmounts, err := am.k.DeleteUserState(sdkCtx, target)
	if err != nil {
		return nil, fmt.Errorf("delete user failed: %w", err)
	}

	sdkCtx.Logger().Info(logDelimiter)
	sdkCtx.Logger().Info("DeleteUser",
		"actor_type", actorType,
		"target", target,
		"username_released", usernameReleased,
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
	reserveBps := uint64(params.SubscriptionReservePercent * 10000)
	if reserveBps > 10000 {
		reserveBps = 10000
	}

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

			reserveAmount = periodFee * reserveBps / 10000
			burnAmount := periodFee - reserveAmount

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

		// Remove old subscription index
		if recipientCore.SubscriptionExpiry > 0 {
			_ = am.k.RemoveSubscription(sdkCtx, recipient, recipientCore.SubscriptionExpiry)
		}

		// Extend expiry from max(currentExpiry, now) + period
		var newExpiry int64
		if params.SubscriptionPeriod > 0 {
			base := sdkCtx.BlockTime().Unix()
			if recipientCore.SubscriptionExpiry > base {
				base = recipientCore.SubscriptionExpiry
			}
			newExpiry = base + int64(params.SubscriptionPeriod)*60
		}

		recipientCore.Level = int32(requestedLevel)
		recipientCore.SubscriptionExpiry = newExpiry
		// Keep auto_renew unchanged for gifts
		recipientCore.ReserveFunds += reserveAmount

		if newExpiry > 0 {
			if err := am.k.SetSubscription(sdkCtx, recipient, requestedLevel, newExpiry); err != nil {
				sdkCtx.Logger().Error("Subscribe gift: failed to set subscription index", "recipient", recipient, "err", err)
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

			reserveAmount = periodFee * reserveBps / 10000
			burnAmount := periodFee - reserveAmount

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
			_ = am.k.RemoveSubscription(sdkCtx, recipient, recipientCore.SubscriptionExpiry)
		}

		var newExpiry int64
		if params.SubscriptionPeriod > 0 {
			newExpiry = sdkCtx.BlockTime().Unix() + int64(params.SubscriptionPeriod)*60
		}

		recipientCore.Level = int32(requestedLevel)
		recipientCore.SubscriptionExpiry = newExpiry
		recipientCore.AutoRenew = true
		recipientCore.ReserveFunds = reserveAmount

		if newExpiry > 0 {
			if err := am.k.SetSubscription(sdkCtx, recipient, requestedLevel, newExpiry); err != nil {
				sdkCtx.Logger().Error("Subscribe: failed to set subscription index", "recipient", recipient, "err", err)
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
		// No state change required
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

// ============================================
// Bridge Handlers
// ============================================

// BridgeBurn burns MIRAGE for bridging to an external (non-IBC) chain
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

func (am AppModule) BridgeBurn(ctx context.Context, req *types.MsgBridgeBurn) (*types.MsgBridgeBurnResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	gasStart := sdkCtx.GasMeter().GasConsumed()
	return bridgeBurn(sdkCtx, am.k, req, func(c sdk.Context, owner string, userLevel int) error {
		gasUsed := c.GasMeter().GasConsumed() - gasStart
		return am.deductRelayGasFee(c, owner, userLevel, gasUsed, "BridgeBurn")
	})
}

// BridgeAttest allows validators to attest to a burn on an external chain (inbound).
// When 2/3 threshold is met, tokens are minted on Mirage.
// BridgeAttestBurned allows validators to attest to a burn on an external chain (inbound).
// When 2/3 threshold is met, tokens are minted on Mirage.
func (am AppModule) BridgeAttestBurned(ctx context.Context, req *types.MsgBridgeAttestBurned) (*types.MsgBridgeAttestBurnedResponse, error) {
	return bridgeAttestBurned(sdk.UnwrapSDKContext(ctx), am.k, req)
}

// BridgeAttestMinted allows validators to attest to a mint on an external chain (outbound).
// When 2/3 threshold is met, the mint is confirmed and the bridge fee is burned.
func (am AppModule) BridgeAttestMinted(ctx context.Context, req *types.MsgBridgeAttestMinted) (*types.MsgBridgeAttestMintedResponse, error) {
	return bridgeAttestMinted(sdk.UnwrapSDKContext(ctx), am.k, req)
}

// ============================================
// Bridge Query Handlers
// ============================================

// BridgeStatus queries the current bridge status
func (am AppModule) GetBridgeStatus(ctx context.Context, _ *types.QueryBridgeStatusRequest) (*types.QueryBridgeStatusResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)

	enabledChains := am.k.GetEnabledBridgeChains(sdkCtx)
	pendingCount, err := am.k.GetBridgePendingCount(sdkCtx)
	if err != nil {
		return nil, err
	}

	// Get per-chain sequence counters
	var chainStatus []*types.BridgeChainStatus
	for _, chain := range enabledChains {
		seq, err := am.k.GetCurrentBridgeSequence(sdkCtx, chain.ChainId)
		if err != nil {
			// Log but continue - sequence of 0 is valid for new chains
			seq = 0
		}
		chainStatus = append(chainStatus, &types.BridgeChainStatus{
			ChainId:         chain.ChainId,
			CurrentSequence: seq,
		})
	}

	return &types.QueryBridgeStatusResponse{
		EnabledChains:            enabledChains,
		PendingAttestationsCount: pendingCount,
		ChainStatus:              chainStatus,
	}, nil
}

// BridgeAttestation queries a specific attestation
func (am AppModule) GetBridgeAttestation(ctx context.Context, req *types.QueryBridgeAttestationRequest) (*types.QueryBridgeAttestationResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	params := am.k.GetParams(sdkCtx)

	sourceChain := strings.TrimSpace(req.GetSourceChain())
	burnID := strings.TrimSpace(req.GetBurnId())

	if sourceChain == "" || burnID == "" {
		return nil, fmt.Errorf("source_chain and burn_id are required")
	}

	attestation, found, err := am.k.GetBridgeAttestation(sdkCtx, sourceChain, burnID)
	if err != nil {
		return nil, fmt.Errorf("failed to get attestation: %w", err)
	}

	if !found {
		return &types.QueryBridgeAttestationResponse{Found: false}, nil
	}

	totalPower, _ := am.k.GetTotalBondedValidatorPower(sdkCtx)
	requiredPower := types.RequiredPower(totalPower, params.BridgeAttestationThreshold)

	attestors, err := am.k.GetBridgeAttestorList(sdkCtx, sourceChain, burnID, attestation.MirageRecipient, attestation.Amount)
	if err != nil {
		return nil, fmt.Errorf("failed to load attestors: %w", err)
	}

	return &types.QueryBridgeAttestationResponse{
		Found:           true,
		SourceChain:     attestation.SourceChain,
		BurnId:          attestation.BurnID,
		MirageRecipient: attestation.MirageRecipient,
		Amount:          attestation.Amount,
		Attestors:       attestors,
		AttestedPower:   attestation.AttestedPower,
		RequiredPower:   requiredPower,
		Minted:          attestation.Minted,
		CreatedAt:       attestation.CreatedAt,
	}, nil
}

// GetBridgeMint queries outbound mint status including attestation progress and completion.
// Returns both attestation progress (attested_power, required_power) and completion status (minted).
func (am AppModule) GetBridgeMint(ctx context.Context, req *types.QueryBridgeMintRequest) (*types.QueryBridgeMintResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	params := am.k.GetParams(sdkCtx)

	burnID := strings.TrimSpace(req.GetBurnId())
	if burnID == "" {
		return nil, fmt.Errorf("burn_id is required")
	}

	destChain := strings.ToLower(strings.TrimSpace(req.GetDestinationChain()))
	if destChain == "" {
		return nil, fmt.Errorf("destination_chain is required")
	}

	// Query attestation progress (may exist even if not yet confirmed)
	attestation, attFound, err := am.k.GetBridgeMintAttestation(sdkCtx, destChain, burnID)
	if err != nil {
		return nil, fmt.Errorf("failed to load mint attestation: %w", err)
	}

	// Query final minted record (exists only after threshold was crossed)
	record, recFound, err := am.k.GetBridgeMintedRecord(sdkCtx, destChain, burnID)
	if err != nil {
		return nil, fmt.Errorf("failed to load mint record: %w", err)
	}

	// Calculate required power for threshold
	totalPower, _ := am.k.GetTotalBondedValidatorPower(sdkCtx)
	requiredPower := types.RequiredPower(totalPower, params.BridgeAttestationThreshold)

	// Build response with all info
	resp := &types.QueryBridgeMintResponse{
		Found:            attFound || recFound,
		Minted:           recFound,
		DestinationChain: destChain,
		RequiredPower:    requiredPower,
	}

	// Add attestation details if found
	if attFound {
		attestors, err := am.k.GetBridgeMintAttestorList(sdkCtx, destChain, burnID)
		if err != nil {
			return nil, fmt.Errorf("failed to load mint attestors: %w", err)
		}
		resp.Attestors = attestors
		resp.AttestedPower = attestation.AttestedPower
		resp.DestinationTx = attestation.DestinationTx
	}

	// Override destination_tx from final record if available (authoritative)
	if recFound {
		resp.DestinationTx = record.DestinationTx
	}

	return resp, nil
}

// BridgeConfig queries the bridge configuration
func (am AppModule) GetBridgeConfig(ctx context.Context, _ *types.QueryBridgeConfigRequest) (*types.QueryBridgeConfigResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	params := am.k.GetParams(sdkCtx)

	return &types.QueryBridgeConfigResponse{
		Chains:               params.BridgeChains,
		AttestationThreshold: params.BridgeAttestationThreshold,
	}, nil
}

// GetBridgeBurn queries an outbound burn record by destination chain and burn_id.
func (am AppModule) GetBridgeBurn(ctx context.Context, req *types.QueryBridgeBurnRequest) (*types.QueryBridgeBurnResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)

	destChain := strings.ToLower(strings.TrimSpace(req.GetDestinationChain()))
	burnID := strings.TrimSpace(req.GetBurnId())

	if destChain == "" || burnID == "" {
		return nil, fmt.Errorf("destination_chain and burn_id are required")
	}

	record, found, err := am.k.GetBridgeBurnRecord(sdkCtx, destChain, burnID)
	if err != nil {
		return nil, fmt.Errorf("failed to get burn record: %w", err)
	}

	if !found {
		return &types.QueryBridgeBurnResponse{Found: false}, nil
	}

	return &types.QueryBridgeBurnResponse{
		Found:              true,
		BurnId:             record.BurnID,
		Owner:              record.Owner,
		DestinationChain:   record.DestinationChain,
		DestinationAddress: record.DestinationAddress,
		Amount:             record.Amount,
		BridgeFee:          record.BridgeFee,
		Sequence:           record.Sequence,
		CreatedAt:          record.CreatedAt,
	}, nil
}
