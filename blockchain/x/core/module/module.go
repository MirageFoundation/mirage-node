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
	"porn":      true,
	"gore":      true,
	"violence":  true,
	"death":     true,
}

// validateTag validates the content tag field
func validateTag(tag string) error {
	tag = strings.TrimSpace(tag)
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
			ctx.Logger().Warn("relay gas fee (admin): failed to burn from module after deduction",
				"owner", owner,
				"level", userLevel,
				"reason", reason,
				"gas_used", gasUsed,
				"fee", fee,
				"err", err)
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

	// Load profile core to access reserve
	bz, found, err := am.k.GetProfileCore(ctx, owner)
	if err != nil || !found {
		ctx.Logger().Warn("deductRelayGasFee: profile not found", "owner", owner)
		return nil
	}

	var core types.ProfileCore
	if err := json.Unmarshal(bz, &core); err != nil {
		ctx.Logger().Warn("deductRelayGasFee: failed to unmarshal profile", "owner", owner, "err", err)
		return nil
	}

	// Deduct from reserve
	if core.ReserveFunds >= fee {
		// Sufficient reserve: deduct and burn from module
		reserveBefore := core.ReserveFunds
		core.ReserveFunds -= fee
		if err := am.k.BurnFromModuleAmount(ctx, fee); err != nil {
			ctx.Logger().Warn("deductRelayGasFee: failed to burn from module", "owner", owner, "fee", fee, "err", err)
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
				ctx.Logger().Warn("deductRelayGasFee: failed to burn remaining reserve", "owner", owner, "reserve", core.ReserveFunds, "err", err)
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
			_ = am.k.RemoveSubscription(ctx, owner, core.SubscriptionExpiry)
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
		ctx.Logger().Warn("deductRelayGasFee: failed to marshal profile", "owner", owner, "err", err)
		return nil
	}
	if err := am.k.SetProfileCore(ctx, owner, newBz); err != nil {
		ctx.Logger().Warn("deductRelayGasFee: failed to save profile", "owner", owner, "err", err)
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

		// Best-effort claim; ignore error if already taken by same owner
		_ = am.k.ClaimUsername(sdkCtx, username, addr)

		// Store only core profile data (no lists for module accounts)
		core := types.ProfileCore{Owner: addr, Username: username}
		if bz, err := json.Marshal(core); err == nil {
			_ = am.k.SetProfileCore(sdkCtx, addr, bz)
		}
	}

	// Initialize params from genesis
	var genState types.GenesisState
	if err := am.cdc.UnmarshalJSON(gs, &genState); err != nil {
		panic(fmt.Errorf("failed to unmarshal core genesis state: %w", err))
	}
	// Default params if missing in genesis
	p := genState.Params
	if p.MinDifficulty == 0 || p.PowMessageWindow == 0 || p.MintInterval == 0 || p.MintQuantity == 0 || p.BlockHashWindow == 0 {
		p = types.DefaultParams()
	}
	_ = am.k.SetParams(sdkCtx, p)

	// Import raw state if present (complete KV store restore from export)
	if len(genState.RawState) > 0 {
		for _, kv := range genState.RawState {
			key, err := base64.StdEncoding.DecodeString(kv.Key)
			if err != nil {
				continue
			}
			value, err := base64.StdEncoding.DecodeString(kv.Value)
			if err != nil {
				continue
			}
			_ = am.k.SetRawKVPair(sdkCtx, key, value)
		}
	}

	// Create any initial profiles specified in genesis (e.g., validators, faucet)
	// This also handles legacy genesis files without raw_state
	for _, ip := range genState.InitialProfiles {
		if ip.Core == nil {
			continue
		}
		owner := strings.TrimSpace(ip.Core.Owner)
		username := strings.TrimSpace(ip.Core.Username)
		if owner == "" {
			continue
		}
		// claim username if present
		if username != "" {
			_ = am.k.ClaimUsername(sdkCtx, username, owner)
		}
		// Store core profile data ONLY if not already present (e.g., when importing raw_state)
		if _, found, _ := am.k.GetProfileCore(sdkCtx, owner); !found {
			// Use the core directly from InitialProfile
			bz, _ := json.Marshal(ip.Core)
			_ = am.k.SetProfileCore(sdkCtx, owner, bz)
		}

		// Store all list fields separately (only if not empty)
		if len(ip.EnabledAgents) > 0 {
			_ = am.k.SetProfileEnabledAgents(sdkCtx, owner, ip.EnabledAgents)
		}
		if len(ip.FollowedUsers) > 0 {
			_ = am.k.SetProfileFollowedUsers(sdkCtx, owner, ip.FollowedUsers)
		}
		if len(ip.FollowedTopics) > 0 {
			_ = am.k.SetProfileFollowedTopics(sdkCtx, owner, ip.FollowedTopics)
		}
		if len(ip.BlockedUsers) > 0 {
			_ = am.k.SetProfileBlockedUsers(sdkCtx, owner, ip.BlockedUsers)
		}
		if len(ip.BlockedPosts) > 0 {
			_ = am.k.SetProfileBlockedPosts(sdkCtx, owner, ip.BlockedPosts)
		}
		if len(ip.BlockedTopics) > 0 {
			_ = am.k.SetProfileBlockedTopics(sdkCtx, owner, ip.BlockedTopics)
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

// BeginBlock burns any funds sitting in the core module account and mints daily issuance to the fee collector once per UTC day.
func (am AppModule) BeginBlock(ctx context.Context) error {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	// Fail-fast here if this node is not a validator so the operator sees the error after init
	// Check local consensus pubkey is among bonded validators
	consAddr := sdkCtx.ConsensusParams() // placeholder to use sdkCtx
	_ = consAddr
	// Emit clear log; actual detection is in app init, but we ensure visibility here
	// If needed, a keeper-based query could assert bonded set contains us.
	// Burn any fees collected by the fee collector before distribution runs
	if err := am.k.BurnAllFromModuleName(sdkCtx, authtypes.FeeCollectorName); err != nil {
		return err
	}
	// NOTE: Do NOT burn the core module account balance here. It holds user reserve funds.
	if err := am.k.MintIfNeeded(sdkCtx); err != nil {
		return err
	}

	// Initialize difficulty if not set (base step = 0)
	params := am.k.GetParams(sdkCtx)
	if !am.k.HasCurrentDifficulty(sdkCtx) {
		if err := am.k.SetCurrentDifficulty(sdkCtx, keeper.BaseDifficultySteps); err != nil {
			return err
		}
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

	// Cleanup old counters periodically (every 100 blocks)
	if sdkCtx.BlockHeight()%100 == 0 {
		if err := am.k.CleanupOldCounters(sdkCtx, params); err != nil {
			return err
		}
	}

	return nil
}

// EndBlock adjusts PoW difficulty based on message volume and processes subscription renewals
func (am AppModule) EndBlock(ctx context.Context) error {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	params := am.k.GetParams(sdkCtx)

	// Bridge fees are burned inline when threshold is reached.

	// Process subscription renewals/expirations
	if err := am.processSubscriptions(sdkCtx, params); err != nil {
		sdkCtx.Logger().Error("EndBlock: failed to process subscriptions", "err", err)
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
				return err
			}
			_ = am.k.ClearPoWWindow(sdkCtx, params)
			sdkCtx.Logger().Info("Increased PoW difficulty due to busy window",
				"old_difficulty", currentDifficulty, "new_difficulty", newDifficulty)
		}
		_ = am.k.SetConsecutiveLowUsage(sdkCtx, 0)
		return nil
	}

	// Calm window: increment consecutive calm sequence
	if messageCount < params.PowCalmPeriodDefinition {
		calmSeq++
		if err := am.k.SetConsecutiveLowUsage(sdkCtx, calmSeq); err != nil {
			return err
		}
		if calmSeq >= params.PowCalmSequenceThreshold {
			newDifficulty := currentDifficulty
			if currentDifficulty > keeper.BaseDifficultySteps {
				newDifficulty = currentDifficulty - 1
			}
			if newDifficulty != currentDifficulty {
				if err := am.k.SetCurrentDifficulty(sdkCtx, newDifficulty); err != nil {
					return err
				}
				_ = am.k.ClearPoWWindow(sdkCtx, params)
				sdkCtx.Logger().Info("Decreased PoW difficulty due to calm sequence",
					"old_difficulty", currentDifficulty, "new_difficulty", newDifficulty,
					"calm_sequence", calmSeq)
			}
			// reset sequence after decreasing
			_ = am.k.SetConsecutiveLowUsage(sdkCtx, 0)
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
			sdkCtx.Logger().Error("processSubscriptions: failed to remove old index",
				"address", sub.Address, "err", err)
		}

		// If subscription_period is 0, it's one-time payment, no renewal needed
		if params.SubscriptionPeriod == 0 {
			continue
		}

		// Load profile core
		bz, found, err := am.k.GetProfileCore(sdkCtx, sub.Address)
		if err != nil || !found {
			sdkCtx.Logger().Error("processSubscriptions: profile not found",
				"address", sub.Address)
			continue
		}

		var core types.ProfileCore
		if err := json.Unmarshal(bz, &core); err != nil {
			sdkCtx.Logger().Error("processSubscriptions: failed to unmarshal profile",
				"address", sub.Address, "err", err)
			continue
		}

		// Burn any remaining reserve from module account before renewal/downgrade
		if core.ReserveFunds > 0 {
			if err := am.k.BurnFromModuleAmount(sdkCtx, core.ReserveFunds); err != nil {
				sdkCtx.Logger().Warn("processSubscriptions: failed to burn reserve",
					"address", sub.Address, "reserve", core.ReserveFunds, "err", err)
			}
			sdkCtx.Logger().Info("processSubscriptions: burned leftover reserve",
				"address", sub.Address, "reserve", core.ReserveFunds)
			core.ReserveFunds = 0
		}

		// Get tier config for current level
		if core.Level <= 0 || int(core.Level) >= len(params.Tiers) {
			// Already free tier or invalid, nothing to renew
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
				// Calculate reserve for new period (SubscriptionReservePercent is fraction [0,1])
				reserveFrac := params.SubscriptionReservePercent
				if reserveFrac > 1 {
					reserveFrac = 1
				}
				reserveAmount := uint64(float64(periodFee) * reserveFrac)
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
	for _, data := range profilesData {
		var core types.ProfileCore
		if err := json.Unmarshal(data, &core); err != nil {
			continue // Skip invalid profiles
		}

		// Load all lists for this profile
		agents, _ := am.k.GetProfileEnabledAgents(sdkCtx, core.Owner)
		users, _ := am.k.GetProfileFollowedUsers(sdkCtx, core.Owner)
		topics, _ := am.k.GetProfileFollowedTopics(sdkCtx, core.Owner)
		blockedUsers, _ := am.k.GetProfileBlockedUsers(sdkCtx, core.Owner)
		blockedPosts, _ := am.k.GetProfileBlockedPosts(sdkCtx, core.Owner)
		blockedTopics, _ := am.k.GetProfileBlockedTopics(sdkCtx, core.Owner)

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

// UpdateParams stores new params
func (am AppModule) UpdateParams(ctx context.Context, req *types.MsgUpdateParams) (*types.MsgUpdateParamsResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	// Only governance authority may update params
	govAuthority := authtypes.NewModuleAddress(govtypes.ModuleName).String()
	if strings.TrimSpace(req.GetAuthority()) != govAuthority {
		return nil, fmt.Errorf("unauthorized: only governance authority can update params")
	}
	// Support partial updates: overlay non-zero fields onto current params
	cur := am.k.GetParams(sdkCtx)
	p := req.Params
	// Minting
	if p.MintInterval != 0 {
		cur.MintInterval = p.MintInterval
	}
	if p.MintQuantity != 0 {
		cur.MintQuantity = p.MintQuantity
	}
	if p.MintDynamicCreditCap != 0 {
		cur.MintDynamicCreditCap = p.MintDynamicCreditCap
	}
	if p.MintDynamicSplit != 0 {
		cur.MintDynamicSplit = p.MintDynamicSplit
	}
	// PoW
	if p.MinDifficulty != 0 {
		cur.MinDifficulty = p.MinDifficulty
	}
	if p.PowMessageWindow != 0 {
		cur.PowMessageWindow = p.PowMessageWindow
	}
	if p.PowMessageLimit != 0 {
		cur.PowMessageLimit = p.PowMessageLimit
	}
	if p.PowCalmPeriodDefinition != 0 {
		cur.PowCalmPeriodDefinition = p.PowCalmPeriodDefinition
	}
	if p.PowCalmSequenceThreshold != 0 {
		cur.PowCalmSequenceThreshold = p.PowCalmSequenceThreshold
	}
	if p.PowDifficultyAllowance != 0 {
		cur.PowDifficultyAllowance = p.PowDifficultyAllowance
	}
	if p.PowDifficultyStep != 0 {
		cur.PowDifficultyStep = p.PowDifficultyStep
	}
	if p.BlockHashWindow != 0 {
		cur.BlockHashWindow = p.BlockHashWindow
	}
	// Username limits
	if p.MaxUsernameSize != 0 {
		cur.MaxUsernameSize = p.MaxUsernameSize
	}
	if p.MaxTopicSize != 0 {
		cur.MaxTopicSize = p.MaxTopicSize
	}
	if p.MinUsernameSize != 0 {
		cur.MinUsernameSize = p.MinUsernameSize
	}
	// Subscription
	if p.SubscriptionPeriod != 0 {
		cur.SubscriptionPeriod = p.SubscriptionPeriod
	}
	// Subscription reserve percent [0,1]
	if p.SubscriptionReservePercent != 0 {
		cur.SubscriptionReservePercent = p.SubscriptionReservePercent
	}
	// Tiers - replace entirely if provided
	if len(p.Tiers) > 0 {
		cur.Tiers = p.Tiers
	}
	// Topic size limits
	if p.MinTopicSize != 0 {
		cur.MinTopicSize = p.MinTopicSize
	}
	// Relay fee settings
	if p.RelayMinGasPrice != 0 {
		cur.RelayMinGasPrice = p.RelayMinGasPrice
	}
	if p.RelayMaxGasFee != 0 {
		cur.RelayMaxGasFee = p.RelayMaxGasFee
	}
	// Envelope age (replay protection)
	if p.MaxEnvelopeAge != 0 {
		cur.MaxEnvelopeAge = p.MaxEnvelopeAge
	}
	// Bridge parameters - replace entirely if provided (fees are per-chain in BridgeChains)
	if len(p.BridgeChains) > 0 {
		cur.BridgeChains = p.BridgeChains
	}
	if p.BridgeAttestationThreshold != 0 {
		cur.BridgeAttestationThreshold = p.BridgeAttestationThreshold
	}
	// Award configs - replace entirely if provided
	if len(p.AwardConfigs) > 0 {
		cur.AwardConfigs = p.AwardConfigs
	}

	if err := cur.Validate(); err != nil {
		return nil, err
	}
	if err := am.k.SetParams(sdkCtx, cur); err != nil {
		return nil, err
	}
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

	// Validate tag field
	tag := strings.TrimSpace(req.GetTag())
	if err := validateTag(tag); err != nil {
		return nil, err
	}
	// Validate media field (v1.12.0+ edit support)
	if err := validateMsgPostMedia(req.GetMedia()); err != nil {
		return nil, err
	}

	// Validate media field (v1.12.0)
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

	// Validate tag field
	tag := strings.TrimSpace(req.GetTag())
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

	// Validate tag (skip if sentinel)
	tag := strings.TrimSpace(req.GetTag())
	if tag != sentinel {
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
	agents, _ := am.k.GetProfileEnabledAgents(sdkCtx, owner)
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

	// Load lists
	if agents, err := am.k.GetProfileEnabledAgents(sdkCtx, owner); err == nil {
		prof.EnabledAgents = agents
	}
	if users, err := am.k.GetProfileFollowedUsers(sdkCtx, owner); err == nil {
		prof.FollowedUsers = users
	}
	if topics, err := am.k.GetProfileFollowedTopics(sdkCtx, owner); err == nil {
		prof.FollowedTopics = topics
	}
	if blocked, err := am.k.GetProfileBlockedUsers(sdkCtx, owner); err == nil {
		prof.BlockedUsers = blocked
	}
	if posts, err := am.k.GetProfileBlockedPosts(sdkCtx, owner); err == nil {
		prof.BlockedPosts = posts
	}
	if blockedTopics, err := am.k.GetProfileBlockedTopics(sdkCtx, owner); err == nil {
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

	agents, err := am.k.GetProfileEnabledAgents(sdkCtx, owner)
	if err != nil {
		agents = []string{}
	}

	for _, a := range agents {
		if a == agent {
			return &types.MsgEnableAgentResponse{}, nil
		}
	}

	if len(agents) >= maxAgents {
		return nil, fmt.Errorf("enabled agents limit reached (%d); disable an agent first", maxAgents)
	}

	agents = append(agents, agent)
	if err := am.k.SetProfileEnabledAgents(sdkCtx, owner, agents); err != nil {
		sdkCtx.Logger().Info(logDelimiter)
		sdkCtx.Logger().Error("EnableAgent: failed to save enabled agents", "owner", owner, "err", err.Error())
		sdkCtx.Logger().Info(logDelimiter)
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

	agents, err := am.k.GetProfileEnabledAgents(sdkCtx, owner)
	if err != nil {
		agents = []string{}
	}

	newAgents := make([]string, 0, len(agents))
	for _, a := range agents {
		if a != agent {
			newAgents = append(newAgents, a)
		}
	}

	if err := am.k.SetProfileEnabledAgents(sdkCtx, owner, newAgents); err != nil {
		sdkCtx.Logger().Info(logDelimiter)
		sdkCtx.Logger().Error("DisableAgent: failed to save enabled agents", "owner", owner, "err", err.Error())
		sdkCtx.Logger().Info(logDelimiter)
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

	if err := am.k.SetProfileEnabledAgents(sdkCtx, owner, normalized); err != nil {
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

	posts, _ := am.k.GetProfileBlockedPosts(sdkCtx, owner)
	for _, p := range posts {
		if p == target {
			return &types.MsgBlockPostResponse{}, nil
		}
	}
	posts = append(posts, target)
	if uint64(len(posts)) > maxPosts {
		posts = posts[len(posts)-int(maxPosts):]
	}
	if err := am.k.SetProfileBlockedPosts(sdkCtx, owner, posts); err != nil {
		return nil, err
	}

	sdkCtx.Logger().Info("BlockPost", "owner", owner, "target", target)

	if owner != "" && authority != govAuthority {
		gasUsed := sdkCtx.GasMeter().GasConsumed() - gasStart
		_ = am.deductRelayGasFee(sdkCtx, owner, userLevel, gasUsed, "BlockPost")
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

	posts, _ := am.k.GetProfileBlockedPosts(sdkCtx, owner)
	newPosts := make([]string, 0, len(posts))
	for _, p := range posts {
		if p != target {
			newPosts = append(newPosts, p)
		}
	}
	if err := am.k.SetProfileBlockedPosts(sdkCtx, owner, newPosts); err != nil {
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

	followedUsers, err := am.k.GetProfileFollowedUsers(sdkCtx, owner)
	if err != nil {
		return nil, err
	}
	if len(followedUsers) > 0 {
		newFollowedUsers := make([]string, 0, len(followedUsers))
		removed := false
		for _, u := range followedUsers {
			if u == target {
				removed = true
				continue
			}
			newFollowedUsers = append(newFollowedUsers, u)
		}
		if removed {
			if err := am.k.SetProfileFollowedUsers(sdkCtx, owner, newFollowedUsers); err != nil {
				return nil, err
			}
			sdkCtx.Logger().Debug("BlockUser removed follow", "owner", owner, "target", target)
		}
	}

	tierConfig := params.GetTierConfig(userLevel)
	maxUsers := uint64(10)
	if tierConfig != nil {
		maxUsers = tierConfig.MaxBlockedUsers
	}

	users, _ := am.k.GetProfileBlockedUsers(sdkCtx, owner)
	for _, u := range users {
		if u == target {
			return &types.MsgBlockUserResponse{}, nil
		}
	}
	users = append(users, target)
	if uint64(len(users)) > maxUsers {
		users = users[len(users)-int(maxUsers):]
	}
	if err := am.k.SetProfileBlockedUsers(sdkCtx, owner, users); err != nil {
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

	users, _ := am.k.GetProfileBlockedUsers(sdkCtx, owner)
	newUsers := make([]string, 0, len(users))
	for _, u := range users {
		if u != target {
			newUsers = append(newUsers, u)
		}
	}
	if err := am.k.SetProfileBlockedUsers(sdkCtx, owner, newUsers); err != nil {
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

	followedTopics, err := am.k.GetProfileFollowedTopics(sdkCtx, owner)
	if err != nil {
		return nil, err
	}
	if len(followedTopics) > 0 {
		newFollowedTopics := make([]string, 0, len(followedTopics))
		removedCount := 0
		for _, t := range followedTopics {
			if topicMatchesPattern(t, topic) {
				removedCount++
				continue
			}
			newFollowedTopics = append(newFollowedTopics, t)
		}
		if removedCount > 0 {
			if err := am.k.SetProfileFollowedTopics(sdkCtx, owner, newFollowedTopics); err != nil {
				return nil, err
			}
			sdkCtx.Logger().Debug("BlockTopic removed follows", "owner", owner, "pattern", topic, "count", removedCount)
		}
	}

	tierConfig := params.GetTierConfig(userLevel)
	maxTopics := uint64(10)
	if tierConfig != nil {
		maxTopics = tierConfig.MaxBlockedTopics
	}

	topics, _ := am.k.GetProfileBlockedTopics(sdkCtx, owner)
	for _, t := range topics {
		if t == topic {
			return &types.MsgBlockTopicResponse{}, nil
		}
	}
	topics = append(topics, topic)
	if uint64(len(topics)) > maxTopics {
		topics = topics[len(topics)-int(maxTopics):]
	}
	if err := am.k.SetProfileBlockedTopics(sdkCtx, owner, topics); err != nil {
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

	topics, _ := am.k.GetProfileBlockedTopics(sdkCtx, owner)
	newTopics := make([]string, 0, len(topics))
	for _, t := range topics {
		if t != topic {
			newTopics = append(newTopics, t)
		}
	}
	if err := am.k.SetProfileBlockedTopics(sdkCtx, owner, newTopics); err != nil {
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

	var userLevel int
	if authority != govAuthority {
		core, err := am.requireUsername(sdkCtx, owner, "FollowUser")
		if err != nil {
			return nil, err
		}
		userLevel = int(core.Level)
	}

	blockedUsers, err := am.k.GetProfileBlockedUsers(sdkCtx, owner)
	if err != nil {
		return nil, err
	}
	if len(blockedUsers) > 0 {
		newBlockedUsers := make([]string, 0, len(blockedUsers))
		removed := false
		for _, u := range blockedUsers {
			if u == user {
				removed = true
				continue
			}
			newBlockedUsers = append(newBlockedUsers, u)
		}
		if removed {
			if err := am.k.SetProfileBlockedUsers(sdkCtx, owner, newBlockedUsers); err != nil {
				return nil, err
			}
			sdkCtx.Logger().Debug("FollowUser removed block", "owner", owner, "user", user)
		}
	}

	tierConfig := params.GetTierConfig(userLevel)
	maxUsers := uint64(25)
	if tierConfig != nil {
		maxUsers = tierConfig.MaxFollowedUsers
	}

	users, _ := am.k.GetProfileFollowedUsers(sdkCtx, owner)
	for _, u := range users {
		if u == user {
			return &types.MsgFollowUserResponse{}, nil
		}
	}
	if uint64(len(users)) >= maxUsers {
		return nil, fmt.Errorf("followed users limit reached (%d); unfollow a user first", maxUsers)
	}
	users = append(users, user)
	if err := am.k.SetProfileFollowedUsers(sdkCtx, owner, users); err != nil {
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

	users, _ := am.k.GetProfileFollowedUsers(sdkCtx, owner)
	newUsers := make([]string, 0, len(users))
	for _, u := range users {
		if u != user {
			newUsers = append(newUsers, u)
		}
	}
	if err := am.k.SetProfileFollowedUsers(sdkCtx, owner, newUsers); err != nil {
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

	blockedTopics, err := am.k.GetProfileBlockedTopics(sdkCtx, owner)
	if err != nil {
		return nil, err
	}
	if len(blockedTopics) > 0 {
		newBlockedTopics := make([]string, 0, len(blockedTopics))
		removedCount := 0
		for _, t := range blockedTopics {
			if topicMatchesPattern(topic, t) {
				removedCount++
				continue
			}
			newBlockedTopics = append(newBlockedTopics, t)
		}
		if removedCount > 0 {
			if err := am.k.SetProfileBlockedTopics(sdkCtx, owner, newBlockedTopics); err != nil {
				return nil, err
			}
			sdkCtx.Logger().Debug("FollowTopic removed blocks", "owner", owner, "topic", topic, "count", removedCount)
		}
	}

	tierConfig := params.GetTierConfig(userLevel)
	maxTopics := uint64(50)
	if tierConfig != nil {
		maxTopics = tierConfig.MaxFollowedTopics
	}

	topics, _ := am.k.GetProfileFollowedTopics(sdkCtx, owner)
	for _, t := range topics {
		if t == topic {
			return &types.MsgFollowTopicResponse{}, nil
		}
	}
	if uint64(len(topics)) >= maxTopics {
		return nil, fmt.Errorf("followed topics limit reached (%d); unfollow a topic first", maxTopics)
	}
	topics = append(topics, topic)
	if err := am.k.SetProfileFollowedTopics(sdkCtx, owner, topics); err != nil {
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

	topics, _ := am.k.GetProfileFollowedTopics(sdkCtx, owner)
	newTopics := make([]string, 0, len(topics))
	for _, t := range topics {
		if t != topic {
			newTopics = append(newTopics, t)
		}
	}
	if err := am.k.SetProfileFollowedTopics(sdkCtx, owner, newTopics); err != nil {
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

	// Update level
	core.Level = req.GetLevel()

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

// UpgradeLevel upgrades or cancels a user's tier subscription
func (am AppModule) UpgradeLevel(ctx context.Context, req *types.MsgUpgradeLevel) (*types.MsgUpgradeLevelResponse, error) {
	sdkCtx := sdk.UnwrapSDKContext(ctx)
	params := am.k.GetParams(sdkCtx)

	// Derive owner from envelope_pubkey
	if len(req.GetEnvelopePubkey()) != 33 {
		return nil, fmt.Errorf("invalid envelope_pubkey length")
	}
	owner, err := deriveOwnerFromPubkey(req.GetEnvelopePubkey())
	if err != nil {
		return nil, err
	}

	core, err := am.requireUsername(sdkCtx, owner, "UpgradeLevel")
	if err != nil {
		return nil, err
	}

	// MsgUpgradeLevel MUST be paid with tokens, not PoW
	if req.GetEnvelopePow() > 0 {
		return nil, fmt.Errorf("MsgUpgradeLevel cannot use PoW, must pay with tokens")
	}

	requestedLevel := int(req.GetLevel())

	// Only levels 1 (Subscriber) and 10 (Agent) can be self-upgraded to.
	// Admin levels require governance via MsgSetLevel; level 0 is free (downgrade via MsgSetAutoRenewal).
	if !types.ValidSubscriptionLevels[requestedLevel] {
		return nil, fmt.Errorf("invalid level %d: must be %d (Subscriber) or %d (Agent)", requestedLevel, types.LevelSubscriber, types.LevelAgent)
	}

	// Get tier config for requested level
	tierConfig := params.GetTierConfig(requestedLevel)
	if tierConfig == nil {
		return nil, fmt.Errorf("tier config not found for level %d", requestedLevel)
	}

	// Burn any existing reserve from module account before charging new fee
	if core.ReserveFunds > 0 {
		if err := am.k.BurnFromModuleAmount(sdkCtx, core.ReserveFunds); err != nil {
			sdkCtx.Logger().Warn("UpgradeLevel: failed to burn old reserve", "owner", owner, "reserve", core.ReserveFunds, "err", err)
		}
		core.ReserveFunds = 0
	}

	// Charge period fee: split into burn portion and reserve portion
	periodFee := tierConfig.PeriodFee
	var reserveAmount uint64
	if periodFee > 0 {
		balance := am.k.GetBalance(sdkCtx, owner, "umirage")
		if balance.LT(sdkmath.NewIntFromUint64(periodFee)) {
			return nil, fmt.Errorf("insufficient balance: need %d umirage, have %s", periodFee, balance.String())
		}

		// Calculate reserve (subscription_reserve_percent is fraction [0,1])
		reserveFrac := params.SubscriptionReservePercent
		if reserveFrac > 1 {
			reserveFrac = 1
		}
		reserveAmount = uint64(float64(periodFee) * reserveFrac)
		burnAmount := periodFee - reserveAmount

		// Burn the non-reserve portion directly from user
		if burnAmount > 0 {
			if err := am.k.BurnFromAccount(sdkCtx, owner, burnAmount); err != nil {
				return nil, fmt.Errorf("failed to burn fee portion: %w", err)
			}
		}

		// Transfer reserve portion from user to module account (escrow)
		if reserveAmount > 0 {
			if err := am.k.DeductFeeFromOwner(sdkCtx, owner, reserveAmount); err != nil {
				return nil, fmt.Errorf("failed to escrow reserve: %w", err)
			}
		}
	}

	// Remove old subscription index if exists
	if core.SubscriptionExpiry > 0 {
		_ = am.k.RemoveSubscription(sdkCtx, owner, core.SubscriptionExpiry)
	}

	// Calculate new expiry
	var newExpiry int64
	if params.SubscriptionPeriod > 0 {
		// subscription_period is in minutes
		newExpiry = sdkCtx.BlockTime().Unix() + int64(params.SubscriptionPeriod)*60
	} else {
		// One-time payment, no renewal needed
		newExpiry = 0
	}

	// Update profile core
	core.Level = int32(requestedLevel)
	core.SubscriptionExpiry = newExpiry
	core.AutoRenew = true // Enable auto-renewal for paid tiers
	core.ReserveFunds = reserveAmount

	// Index subscription for renewal tracking (only if recurring)
	if newExpiry > 0 {
		if err := am.k.SetSubscription(sdkCtx, owner, requestedLevel, newExpiry); err != nil {
			sdkCtx.Logger().Error("UpgradeLevel: failed to set subscription index", "owner", owner, "err", err)
		}
	}

	// Save profile core
	bz, err := json.Marshal(core)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal profile: %w", err)
	}
	if err := am.k.SetProfileCore(sdkCtx, owner, bz); err != nil {
		return nil, fmt.Errorf("failed to save profile: %w", err)
	}

	sdkCtx.Logger().Info("UpgradeLevel",
		"owner", owner,
		"level", requestedLevel,
		"period_fee", periodFee,
		"reserve", reserveAmount,
		"expiry", newExpiry,
		"auto_renew", true,
		"subscription_period", params.SubscriptionPeriod,
	)

	return &types.MsgUpgradeLevelResponse{}, nil
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

	attestors, err := am.k.GetBridgeAttestorList(sdkCtx, sourceChain, burnID)
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
