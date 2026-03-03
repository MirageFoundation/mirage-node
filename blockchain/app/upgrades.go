package app

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"math"
	"time"

	storetypes "cosmossdk.io/store/types"
	upgradetypes "cosmossdk.io/x/upgrade/types"
	cmtproto "github.com/cometbft/cometbft/proto/tendermint/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/cosmos/cosmos-sdk/types/module"

	corekeeper "mirage/x/core/keeper"
	coretypes "mirage/x/core/types"
)

const (
	// 201600 blocks = 7 days at 3s/block
	retentionBlocks        = int64(201600)
	retentionBlockTimeSecs = int64(3)
	retentionDuration      = time.Duration(retentionBlocks*retentionBlockTimeSecs) * time.Second

	sdkRestoreUpgradeName = "v1.10.4-restore-sdk"
)

// RegisterUpgradeHandlers registers all upgrade handlers for the chain
func (app *App) RegisterUpgradeHandlers() {
	// Add more upgrade handlers as needed

	// Followed moderators upgrade
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.2.0-follow-mods",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.2.0-follow-mods...")

			// IMPORTANT: IF WE CHANGE THE CORE MODULE, WE NEED TO ACCOUNT FOR THE BELOW.
			// Treat core v1->v2 as a no-op store migration: bump version pre-migration.
			// if v, ok := fromVM[coretypes.ModuleName]; !ok || v < 2 {
			// 	fromVM[coretypes.ModuleName] = 2
			// }

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// 1) Migrate profile JSON: moderators -> followed_moderators
			profiles, err := app.CoreKeeper.GetAllProfiles(sdkCtx)
			if err != nil {
				return nil, err
			}
			type anyMap = map[string]interface{}
			for _, bz := range profiles {
				var m anyMap
				if err := json.Unmarshal(bz, &m); err != nil {
					continue
				}
				owner, _ := m["owner"].(string)
				if owner == "" {
					continue
				}
				// Rename legacy key if present
				if old, hasOld := m["moderators"]; hasOld {
					m["followed_moderators"] = old
					delete(m, "moderators")
				}
				// Ensure followed_moderators exists and is a JSON array
				if fm, ok := m["followed_moderators"]; !ok || fm == nil {
					m["followed_moderators"] = []string{}
				} else {
					switch v := fm.(type) {
					case []interface{}:
						arr := make([]string, 0, len(v))
						for _, e := range v {
							if s, ok := e.(string); ok {
								arr = append(arr, s)
							}
						}
						m["followed_moderators"] = arr
					case []string:
						// already correct
					default:
						// Coerce any non-array to empty array for schema consistency
						m["followed_moderators"] = []string{}
					}
				}
				if nbz, err := json.Marshal(m); err == nil {
					_ = app.CoreKeeper.SetProfile(sdkCtx, owner, nbz)
				}
			}

			sdkCtx.Logger().Info("Upgrade to v1.2.0-follow-mods complete - field migration done")
			return toVM, nil
		},
	)

	// Tier system upgrade with split lists
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.3.0-tiers",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.3.0-tiers...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Default CreatedAt for existing profiles: 2025-11-01 00:00:00 UTC
			const defaultCreatedAt int64 = 1761955200

			// Migrate all profiles: add new fields AND split lists into separate storage
			profiles, err := app.CoreKeeper.GetAllProfiles(sdkCtx)
			if err != nil {
				return nil, err
			}

			type anyMap = map[string]interface{}
			migratedCount := 0
			for _, bz := range profiles {
				var m anyMap
				if err := json.Unmarshal(bz, &m); err != nil {
					continue
				}
				owner, _ := m["owner"].(string)
				if owner == "" {
					continue
				}

				// Set CreatedAt if not present or zero
				if ca, ok := m["created_at"].(float64); !ok || ca == 0 {
					m["created_at"] = float64(defaultCreatedAt)
				}

				// Initialize SubscriptionExpiry if not present
				if _, ok := m["subscription_expiry"]; !ok {
					m["subscription_expiry"] = float64(0)
				}

				// Initialize IsModerator if not present
				if _, ok := m["is_moderator"]; !ok {
					m["is_moderator"] = false
				}

				// Initialize AutoRenew to false for existing profiles
				if _, ok := m["auto_renew"]; !ok {
					m["auto_renew"] = false
				}

				// Initialize Banner if not present
				if _, ok := m["banner"]; !ok {
					m["banner"] = ""
				}

				// Extract and migrate lists to separate storage, then remove from core
				listMigrations := []struct {
					field  string
					setter func(sdk.Context, string, []string) error
				}{
					{"followed_moderators", app.CoreKeeper.SetProfileEnabledAgents},
					{"followed_users", app.CoreKeeper.SetProfileFollowedUsers},
					{"followed_topics", app.CoreKeeper.SetProfileFollowedTopics},
					{"blocked_users", app.CoreKeeper.SetProfileBlockedUsers},
					{"blocked_posts", app.CoreKeeper.SetProfileBlockedPosts},
					{"blocked_topics", app.CoreKeeper.SetProfileBlockedTopics},
				}

				for _, lm := range listMigrations {
					if raw, ok := m[lm.field]; ok && raw != nil {
						var items []string
						switch v := raw.(type) {
						case []interface{}:
							for _, e := range v {
								if s, ok := e.(string); ok {
									items = append(items, s)
								}
							}
						case []string:
							items = v
						}
						if len(items) > 0 {
							_ = lm.setter(sdkCtx, owner, items)
						}
					}
					// Remove list from core profile (whether it had data or not)
					delete(m, lm.field)
				}

				// Save the core profile without lists
				if nbz, err := json.Marshal(m); err == nil {
					_ = app.CoreKeeper.SetProfileCore(sdkCtx, owner, nbz)
					migratedCount++
				}
			}

			sdkCtx.Logger().Info("v1.3.0-tiers: profile migration complete",
				"total_profiles", len(profiles),
				"migrated", migratedCount,
			)

			// Update params with new fields (SubscriptionReservePercent, RelayMinGasPrice, RelayMaxGasFee, Tiers)
			params := app.CoreKeeper.GetParams(sdkCtx)
			needsUpdate := false

			// Set default tiers if not present
			if len(params.Tiers) == 0 {
				params.Tiers = coretypes.DefaultTiers()
				needsUpdate = true
				sdkCtx.Logger().Info("v1.3.0-tiers: set default tiers", "count", len(params.Tiers))
			}

			// Set SubscriptionReservePercent if not set
			if params.SubscriptionReservePercent == 0 {
				params.SubscriptionReservePercent = 0.20 // 20% of monthly fee goes to reserve
				needsUpdate = true
				sdkCtx.Logger().Info("v1.3.0-tiers: set SubscriptionReservePercent", "value", params.SubscriptionReservePercent)
			}

			// Set RelayMinGasPrice (25 = 0.025 umirage per gas, using /1000 divisor)
			if params.RelayMinGasPrice == 0 || params.RelayMinGasPrice == 1 {
				params.RelayMinGasPrice = 25 // 0.025 umirage per gas (25/1000)
				needsUpdate = true
				sdkCtx.Logger().Info("v1.3.0-tiers: set RelayMinGasPrice", "value", params.RelayMinGasPrice)
			}

			// Set RelayMaxGasFee if not set
			if params.RelayMaxGasFee == 0 {
				params.RelayMaxGasFee = 5000 // 0.005 MIRAGE max per tx
				needsUpdate = true
				sdkCtx.Logger().Info("v1.3.0-tiers: set RelayMaxGasFee", "value", params.RelayMaxGasFee)
			}

			// Set SubscriptionPeriod if not set (5 minutes for testing)
			if params.SubscriptionPeriod == 0 {
				params.SubscriptionPeriod = 5
				needsUpdate = true
				sdkCtx.Logger().Info("v1.3.0-tiers: set SubscriptionPeriod", "value", params.SubscriptionPeriod)
			}

			if needsUpdate {
				if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
					sdkCtx.Logger().Error("v1.3.0-tiers: failed to update params", "err", err)
				} else {
					sdkCtx.Logger().Info("v1.3.0-tiers: params updated successfully")
				}
			}

			sdkCtx.Logger().Info("Upgrade to v1.3.0-tiers complete")
			return toVM, nil
		},
	)

	// v1.3.1: Admin users (level >= 100) exempt from reserve check
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.3.1",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.3.1...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			sdkCtx.Logger().Info("Upgrade to v1.3.1 complete - admins now exempt from reserve check")
			return toVM, nil
		},
	)

	// v1.4.0-profile-core: ProfileCore moved to proto, Level type int->int32
	// This is a no-op migration since ProfileCore is stored as JSON (not proto binary),
	// and JSON serialization of int32 vs int is identical.
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.4.0-profile-core",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.4.0-profile-core...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			sdkCtx.Logger().Info("Upgrade to v1.4.0-profile-core complete - ProfileCore now defined in proto")
			return toVM, nil
		},
	)

	// v1.5.0-social-graph: Breaking changes to relay message wire format + social graph features.
	// Wire format changes:
	// - Adds envelope_timestamp (tag 6) for guaranteed transaction uniqueness and replay protection
	// - Moves envelope_signature from tag 6 to tag 10 (tags 7-9 reserved for future use)
	// - Changes envelope_block_hash from string to bytes (saves 32 bytes per tx)
	// Feature changes:
	// - Multi-topic posts, content tags
	// - Follow/unfollow users and topics
	// - Explicit block/unblock messages
	// Param changes:
	// - Adds max_envelope_age (default 60 seconds)
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.5.0-social-graph",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.5.0-social-graph...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Update params for this upgrade
			params := app.CoreKeeper.GetParams(sdkCtx)
			needsUpdate := false

			// Set new param: max_envelope_age (required for envelope_timestamp validation)
			if params.MaxEnvelopeAge == 0 {
				params.MaxEnvelopeAge = 60 // 60 seconds
				needsUpdate = true
				sdkCtx.Logger().Info("v1.5.0-social-graph: set max_envelope_age", "value", params.MaxEnvelopeAge)
			}

			// Increase subscription reserve fraction from 20% to 40%
			if params.SubscriptionReservePercent < 0.40 {
				params.SubscriptionReservePercent = 0.40
				needsUpdate = true
				sdkCtx.Logger().Info("v1.5.0-social-graph: set subscription_reserve_percent", "value", params.SubscriptionReservePercent)
			}

			if needsUpdate {
				if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
					return nil, err
				}
			}

			sdkCtx.Logger().Info("Upgrade to v1.5.0-social-graph complete - social graph features enabled, envelope timestamp added, signature moved to tag 10, block_hash now bytes")
			return toVM, nil
		},
	)

	// v1.5.1: Tier config fix + min_topic_size reduction
	// - GetTierConfig now returns highest tier for levels >= max (e.g., admin level 100)
	//   Previously returned free tier (bug), now returns distinguished tier
	// - min_topic_size reduced from 3 to 2
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.5.1",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.5.1...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Update min_topic_size from 3 to 2
			params := app.CoreKeeper.GetParams(sdkCtx)
			if params.MinTopicSize > 2 {
				params.MinTopicSize = 2
				if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
					return nil, err
				}
				sdkCtx.Logger().Info("v1.5.1: set min_topic_size", "value", params.MinTopicSize)
			}

			sdkCtx.Logger().Info("Upgrade to v1.5.1 complete - tier config fix applied, min_topic_size=2")
			return toVM, nil
		},
	)

	// v1.6.0-personalized-feeds: Home/Following feeds, single topic posts, reduced limits
	// - Home feed with tier-weighted vote scores, Following feed for subscribed content
	// - MsgPost/MsgEdit: topics array -> single topic string
	// - max_cross_posts removed from TierConfig proto
	// - mint_interval: 20 -> 200 blocks (1 min -> 10 min)
	// - max_topic_size: 50 -> 35
	// - max_username_size: 40 -> 30
	// - Content/title validation uses rune count (characters) not byte length
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.6.0-personalized-feeds",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.6.0-personalized-feeds...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Update params for v1.6
			params := app.CoreKeeper.GetParams(sdkCtx)
			changed := false

			if params.MintInterval != 200 {
				params.MintInterval = 200
				changed = true
				sdkCtx.Logger().Info("v1.6: set mint_interval", "value", 200)
			}
			if params.MaxTopicSize != 35 {
				params.MaxTopicSize = 35
				changed = true
				sdkCtx.Logger().Info("v1.6: set max_topic_size", "value", 35)
			}
			if params.MaxUsernameSize != 30 {
				params.MaxUsernameSize = 30
				changed = true
				sdkCtx.Logger().Info("v1.6: set max_username_size", "value", 30)
			}

			if changed {
				if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
					return nil, err
				}
			}

			sdkCtx.Logger().Info("Upgrade to v1.6.0-personalized-feeds complete")
			return toVM, nil
		},
	)

	// v1.7.7-tier-pricing: Tier cost update (10/20/30 MIRAGE per 30 days) + remove Go log rotation
	// - Tier 1 (Trusted): 10 MIRAGE per 30 days
	// - Tier 2 (Established): 20 MIRAGE per 30 days
	// - Tier 3 (Distinguished): 30 MIRAGE per 30 days
	// - SubscriptionPeriod: 43200 minutes (30 days)
	// - Go-based log rotation removed (shell cronolog handles logging)
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.7.7-tier-pricing",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.7.7-tier-pricing...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Update subscription period + tier costs
			params := app.CoreKeeper.GetParams(sdkCtx)
			changed := false

			// SubscriptionPeriod is in minutes (43200 = 30 days)
			if params.SubscriptionPeriod != 43200 {
				params.SubscriptionPeriod = 43200
				changed = true
				sdkCtx.Logger().Info("v1.7.7-tier-pricing: set subscription_period", "value", 43200)
			}

			// Ensure we have at least 4 tiers
			if len(params.Tiers) >= 4 {
				// Tier 1: 10 MIRAGE (10_000_000 umirage)
				if params.Tiers[1].PeriodFee != 10_000_000 {
					params.Tiers[1].PeriodFee = 10_000_000
					changed = true
					sdkCtx.Logger().Info("v1.7.7-tier-pricing: set tier 1 period_fee", "value", 10_000_000)
				}
				// Tier 2: 20 MIRAGE (20_000_000 umirage)
				if params.Tiers[2].PeriodFee != 20_000_000 {
					params.Tiers[2].PeriodFee = 20_000_000
					changed = true
					sdkCtx.Logger().Info("v1.7.7-tier-pricing: set tier 2 period_fee", "value", 20_000_000)
				}
				// Tier 3: 30 MIRAGE (30_000_000 umirage)
				if params.Tiers[3].PeriodFee != 30_000_000 {
					params.Tiers[3].PeriodFee = 30_000_000
					changed = true
					sdkCtx.Logger().Info("v1.7.7-tier-pricing: set tier 3 period_fee", "value", 30_000_000)
				}
			}

			if changed {
				if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
					return nil, err
				}
			}

			sdkCtx.Logger().Info("Upgrade to v1.7.7-tier-pricing complete - tier costs updated, Go log rotation removed")
			return toVM, nil
		},
	)

	// v1.7.9-node-home: DefaultNodeHome changed from "main" to "node"
	// - Binary now uses ~/.mirage/node/ as default home directory
	// - Migration removes the backward-compat ~/.mirage/main symlink
	// - No on-chain state changes required
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.7.9-node-home",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.7.9-node-home...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			sdkCtx.Logger().Info("Upgrade to v1.7.9-node-home complete - DefaultNodeHome is now ~/.mirage/node/")
			return toVM, nil
		},
	)

	// v1.8.0-economics: Major economics rebalancing for 10,000x token multiplier
	// - RelayMinGasPrice: 25 → 5000 (now umirage per gas, was per 1000 gas)
	// - RelayMaxGasFee: 5000 → 500,000,000 (500 MIRAGE cap)
	// - SubscriptionReservePercent: 40 → 80 (80% to reserve, 20% burned)
	// - MintQuantity: 100,000 → 350,000,000 (350 MIRAGE per 10min)
	// - Tier period fees: 10/20/30 MIRAGE → 100K/200K/300K MIRAGE
	// - Gov min_deposit: 10 MIRAGE → 500K MIRAGE ($5)
	// - Gov expedited_min_deposit: 10 MIRAGE → 1M MIRAGE ($10)
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.8.0-economics",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.8.0-economics...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Update core params
			params := app.CoreKeeper.GetParams(sdkCtx)

			// Log old values before update
			sdkCtx.Logger().Info("v1.8.0-economics: current core params",
				"relay_min_gas_price", params.RelayMinGasPrice,
				"relay_max_gas_fee", params.RelayMaxGasFee,
				"subscription_reserve_percent", params.SubscriptionReservePercent,
				"mint_quantity", params.MintQuantity,
				"tier1_period_fee", params.Tiers[1].PeriodFee,
				"tier2_period_fee", params.Tiers[2].PeriodFee,
				"tier3_period_fee", params.Tiers[3].PeriodFee,
			)

			// RelayMinGasPrice: now umirage per gas (was per 1000 gas with /1000 divisor)
			params.RelayMinGasPrice = 5000 // 5000 umirage per gas
			sdkCtx.Logger().Info("v1.8.0-economics: set relay_min_gas_price", "value", params.RelayMinGasPrice)

			// RelayMaxGasFee: 500 MIRAGE cap per tx
			params.RelayMaxGasFee = 500_000_000
			sdkCtx.Logger().Info("v1.8.0-economics: set relay_max_gas_fee", "value", params.RelayMaxGasFee)

			// SubscriptionReservePercent: 80% to reserve, 20% burned
			params.SubscriptionReservePercent = 0.80
			sdkCtx.Logger().Info("v1.8.0-economics: set subscription_reserve_percent", "value", params.SubscriptionReservePercent)

			// MintQuantity: 350 MIRAGE per 10min
			params.MintQuantity = 350_000_000
			sdkCtx.Logger().Info("v1.8.0-economics: set mint_quantity", "value", params.MintQuantity)

			// Tier period fees (10,000x increase)
			if len(params.Tiers) >= 4 {
				// Tier 1: 100K MIRAGE ($1/mo at $0.00001/MIRAGE)
				params.Tiers[1].PeriodFee = 100_000_000_000
				sdkCtx.Logger().Info("v1.8.0-economics: set tier 1 period_fee", "value", params.Tiers[1].PeriodFee)

				// Tier 2: 200K MIRAGE ($2/mo)
				params.Tiers[2].PeriodFee = 200_000_000_000
				sdkCtx.Logger().Info("v1.8.0-economics: set tier 2 period_fee", "value", params.Tiers[2].PeriodFee)

				// Tier 3: 300K MIRAGE ($3/mo)
				params.Tiers[3].PeriodFee = 300_000_000_000
				sdkCtx.Logger().Info("v1.8.0-economics: set tier 3 period_fee", "value", params.Tiers[3].PeriodFee)
			}

			if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
				sdkCtx.Logger().Error("v1.8.0-economics: failed to update core params", "err", err)
				return nil, err
			}
			sdkCtx.Logger().Info("v1.8.0-economics: core params updated successfully")

			// Update gov params (min_deposit, expedited_min_deposit)
			govParams, err := app.GovKeeper.Params.Get(ctx)
			if err != nil {
				sdkCtx.Logger().Error("v1.8.0-economics: failed to get gov params", "err", err)
				return nil, err
			}

			sdkCtx.Logger().Info("v1.8.0-economics: current gov params",
				"min_deposit", govParams.MinDeposit,
				"expedited_min_deposit", govParams.ExpeditedMinDeposit,
			)

			// min_deposit: 500K MIRAGE ($5 at $0.00001/MIRAGE)
			govParams.MinDeposit = sdk.NewCoins(sdk.NewInt64Coin("umirage", 500_000_000_000))
			sdkCtx.Logger().Info("v1.8.0-economics: set min_deposit", "value", govParams.MinDeposit)

			// expedited_min_deposit: 1M MIRAGE ($10)
			govParams.ExpeditedMinDeposit = sdk.NewCoins(sdk.NewInt64Coin("umirage", 1_000_000_000_000))
			sdkCtx.Logger().Info("v1.8.0-economics: set expedited_min_deposit", "value", govParams.ExpeditedMinDeposit)

			if err := app.GovKeeper.Params.Set(ctx, govParams); err != nil {
				sdkCtx.Logger().Error("v1.8.0-economics: failed to update gov params", "err", err)
				return nil, err
			}
			sdkCtx.Logger().Info("v1.8.0-economics: gov params updated successfully")

			sdkCtx.Logger().Info("Upgrade to v1.8.0-economics complete - economics rebalanced for 10,000x multiplier")
			return toVM, nil
		},
	)

	// v1.9.0-bridge: Cross-chain bridge functionality
	// - Attested bridge for external chains (Solana, Ethereum)
	// - New params: bridge_chains, bridge_attestation_threshold, bridge_fee
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.9.0-bridge",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.9.0-bridge...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Update core params with bridge defaults
			params := app.CoreKeeper.GetParams(sdkCtx)
			changed := false

			// Enable Solana bridge with 500 MIRAGE fee
			solanaEnabled := false
			for _, chain := range params.BridgeChains {
				if chain.ChainId == "solana" {
					solanaEnabled = true
					if chain.Fee != 500_000_000 {
						oldFee := chain.Fee
						chain.Fee = 500_000_000
						changed = true
						sdkCtx.Logger().Info("v1.9.0-bridge: updated Solana bridge fee to 500 MIRAGE",
							"old_fee", oldFee, "new_fee", 500_000_000)
					}
					break
				}
			}
			if !solanaEnabled {
				params.BridgeChains = append(params.BridgeChains, &coretypes.BridgeChainConfig{
					ChainId: "solana",
					Enabled: true,
					Fee:     500_000_000, // 500 MIRAGE
				})
				changed = true
				sdkCtx.Logger().Info("v1.9.0-bridge: enabled Solana bridge with 500 MIRAGE fee")
			}

			// Set attestation threshold: 66.67%
			if params.BridgeAttestationThreshold == 0 {
				params.BridgeAttestationThreshold = 0.6667
				changed = true
				sdkCtx.Logger().Info("v1.9.0-bridge: set bridge_attestation_threshold", "value", params.BridgeAttestationThreshold)
			}

			if changed {
				if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
					sdkCtx.Logger().Error("v1.9.0-bridge: failed to update params", "err", err)
					return nil, err
				}
				sdkCtx.Logger().Info("v1.9.0-bridge: params updated successfully")
			}

			// Advance Solana bridge sequence only if currently lower than minimum
			// This prevents "AlreadyMinted" errors when Mirage chain is reset but Solana state persists
			// but doesn't overwrite a higher value that may have been set via genesis
			const minSolanaSeq uint64 = 100
			currentSeq, _ := app.CoreKeeper.GetCurrentBridgeSequence(sdkCtx, "solana")
			if currentSeq < minSolanaSeq {
				if err := app.CoreKeeper.SetBridgeSequence(sdkCtx, "solana", minSolanaSeq); err != nil {
					sdkCtx.Logger().Error("v1.9.0-bridge: failed to set bridge sequence", "err", err)
					return nil, err
				}
				sdkCtx.Logger().Info("v1.9.0-bridge: advanced Solana bridge sequence", "from", currentSeq, "to", minSolanaSeq)
			} else {
				sdkCtx.Logger().Info("v1.9.0-bridge: kept existing Solana bridge sequence", "seq", currentSeq)
			}

			sdkCtx.Logger().Info("Upgrade to v1.9.0-bridge complete - cross-chain bridge enabled")
			return toVM, nil
		},
	)

	// v1.9.1-seq-fix: HACK to advance Solana sequence past stale devnet state
	// Use this if v1.9.0-bridge already ran before the sequence fix was added
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.9.1-seq-fix",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.9.1-seq-fix...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Advance Solana bridge sequence only if currently lower than minimum
			const minSolanaSeq uint64 = 100
			currentSeq, _ := app.CoreKeeper.GetCurrentBridgeSequence(sdkCtx, "solana")
			if currentSeq < minSolanaSeq {
				if err := app.CoreKeeper.SetBridgeSequence(sdkCtx, "solana", minSolanaSeq); err != nil {
					sdkCtx.Logger().Error("v1.9.1-seq-fix: failed to set bridge sequence", "err", err)
					return nil, err
				}
				sdkCtx.Logger().Info("v1.9.1-seq-fix: advanced Solana bridge sequence", "from", currentSeq, "to", minSolanaSeq)
			} else {
				sdkCtx.Logger().Info("v1.9.1-seq-fix: kept existing Solana bridge sequence", "seq", currentSeq)
			}

			sdkCtx.Logger().Info("Upgrade to v1.9.1-seq-fix complete")
			return toVM, nil
		},
	)

	// v1.9.1-query-fix: Bridge query endpoint fixes
	// - Fixed CLI: `miraged q bridge mint` now requires destination_chain parameter
	// - Fixed REST: Added GetBridgeMint handler to REST gateway
	// - Fixed proto: QueryBridgeMintResponse now includes attestation progress fields
	// - Deploy: Always prunes Docker and clears /tmp on remote deploys
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.9.1-query-fix",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.9.1-query-fix...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			sdkCtx.Logger().Info("Upgrade to v1.9.1-query-fix complete - bridge query endpoints fixed")
			return toVM, nil
		},
	)

	// v1.10.0-bridge-refactor: Bridge attestation refactor
	// - BridgeBurn no longer creates state records (event-only)
	// - Unified BridgeAttestation model with direction field
	// - MsgBridgeAttest renamed to MsgBridgeAttestBurned
	// - MsgBridgeMinted renamed to MsgBridgeAttestMinted
	// - Response fields use 'confirmed' instead of 'minted'
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.10.0-bridge-refactor",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.10.0-bridge-refactor...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Note: The bridge refactor removes BridgeBurn as state.
			// Existing burns are still tracked via:
			// 1. burn_sequence counter (already exists)
			// 2. BridgeMintedRecord (for outbound burn confirmations)
			// 3. BridgeAttestation (for inbound/outbound attestations)
			//
			// No state migration needed because:
			// - Old BridgeBurnRecords can remain in state (harmless)
			// - New burns will use event-only model
			// - Orchestrators watch events, not state

			sdkCtx.Logger().Info("Upgrade to v1.10.0-bridge-refactor complete")
			return toVM, nil
		},
	)

	// v1.9.2-bridge-fee-endblock: Move bridge fee distribution to EndBlock
	// - MsgBridgeAttestMinted no longer distributes fees inline (stabilizes gas)
	// - Fee distribution queued and processed in EndBlock
	// - New ConfirmedBy field on BridgeMintAttestation tracks threshold-crossing validator
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.9.2-bridge-fee-endblock",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.9.2-bridge-fee-endblock...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Behavior change:
			// - Fee distribution now happens in EndBlock instead of inline in MsgBridgeAttestMinted
			// - This stabilizes gas usage for attestation txs (removes variance from concurrent attestations)

			sdkCtx.Logger().Info("Upgrade to v1.9.2-bridge-fee-endblock complete - fee distribution moved to EndBlock")
			return toVM, nil
		},
	)

	// v1.9.3-bridge-fee-burn: Store mint attestors separately and burn bridge fees
	// - Keeps mint attestation record size stable (separate attestor keys)
	// - Prevents gas variance from growing attestor maps
	// - Burns bridge fees inline when threshold is reached (no attestor payouts)
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.9.3-bridge-fee-burn",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.9.3-bridge-fee-burn...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			if err := app.CoreKeeper.MigrateBridgeMintAttestors(sdkCtx); err != nil {
				return nil, err
			}

			sdkCtx.Logger().Info("Upgrade to v1.9.3-bridge-fee-burn complete - attestors moved and fees burned")
			return toVM, nil
		},
	)

	// v1.9.4-bridge-attestor-fix: Store all attestors separately (replaces v1.9.3 which passed but didn't execute)
	// - Migrates OUTBOUND mint attestors (was v1.9.3-bridge-fee-burn)
	// - Migrates INBOUND attestors
	// - Keeps attestation records fixed-size to prevent gas variance
	// - Orchestrator gas retry: 1.5x → 2x → 2.5x → 3x → 5x
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.9.4-bridge-attestor-fix",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.9.4-bridge-attestor-fix...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Migrate OUTBOUND mint attestors (was v1.9.3-bridge-fee-burn which passed but didn't execute)
			if err := app.CoreKeeper.MigrateBridgeMintAttestors(sdkCtx); err != nil {
				return nil, err
			}
			sdkCtx.Logger().Info("v1.9.4: outbound mint attestors migrated")

			// Migrate INBOUND attestors
			if err := app.CoreKeeper.MigrateBridgeAttestors(sdkCtx); err != nil {
				return nil, err
			}
			sdkCtx.Logger().Info("v1.9.4: inbound attestors migrated")

			sdkCtx.Logger().Info("Upgrade to v1.9.4-bridge-attestor-fix complete - all attestors migrated")
			return toVM, nil
		},
	)

	// v1.9.5-bridge-no-pow: Remove PoW requirement for bridge operations
	// - MsgBridgeBurn and MsgIBCTransfer no longer require PoW
	// - Token transfers are self-authenticating (can't burn/transfer what you don't have)
	// - Simplifies bridge UX for free-tier users
	// - No data migration needed, just binary change in ante handler
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.9.5-bridge-no-pow",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.9.5-bridge-no-pow...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// No data migration needed - this is a binary-only change
			// The ante handler now skips PoW validation for MsgBridgeBurn and MsgIBCTransfer

			sdkCtx.Logger().Info("Upgrade to v1.9.5-bridge-no-pow complete - bridge operations no longer require PoW")
			return toVM, nil
		},
	)

	// v1.9.7-bridge-replay: Bridge reliability + fee burn simplification (combines v1.9.6 + v1.9.7)
	// - Late/duplicate attestations now emit bridge_attest events (from v1.9.6)
	// - Orchestrator replays pending outbound burns on startup
	// - Requires CometBFT tx_index=on for TxSearch
	// - Bridge fees burned at MsgBridgeBurn (no escrow/burn-on-confirm)
	// - Bridge mint query renamed to GetBridgeMint
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.9.7-bridge-replay",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.9.7-bridge-replay...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// No data migration needed - binary-only changes
			sdkCtx.Logger().Info("Upgrade to v1.9.7-bridge-replay complete - replay + fee burn simplification enabled")
			return toVM, nil
		},
	)

	// v1.9.9-retention: Align evidence retention with deploy retention blocks.
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.9.9-retention",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.9.9-retention...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			params, err := app.ConsensusParamsKeeper.ParamsStore.Get(ctx)
			if err != nil {
				sdkCtx.Logger().Error("v1.9.9-retention: failed to get consensus params", "err", err)
				return nil, err
			}

			if params.Evidence == nil {
				params.Evidence = &cmtproto.EvidenceParams{}
			}

			oldBlocks := params.Evidence.MaxAgeNumBlocks
			oldDuration := params.Evidence.MaxAgeDuration

			params.Evidence.MaxAgeNumBlocks = retentionBlocks
			params.Evidence.MaxAgeDuration = retentionDuration

			if err := app.ConsensusParamsKeeper.ParamsStore.Set(ctx, params); err != nil {
				sdkCtx.Logger().Error("v1.9.9-retention: failed to set consensus params", "err", err)
				return nil, err
			}

			sdkCtx.Logger().Info(
				"v1.9.9-retention: updated evidence params",
				"old_max_age_num_blocks", oldBlocks,
				"old_max_age_duration", oldDuration.String(),
				"max_age_num_blocks", params.Evidence.MaxAgeNumBlocks,
				"max_age_duration", params.Evidence.MaxAgeDuration.String(),
			)

			sdkCtx.Logger().Info("Upgrade to v1.9.9-retention complete - evidence retention updated")
			return toVM, nil
		},
	)

	// v1.10.0-remove-ibc: Remove IBC/Osmosis support entirely
	// - Removes Osmosis from bridge_chains params
	// - IBC modules have been removed from the binary
	// - Adds MsgBurnTokens for governance burns
	// - Renames MsgMintTo to MsgMintTokens
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.10.0-remove-ibc",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.10.0-remove-ibc...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Remove Osmosis from bridge_chains if present
			params := app.CoreKeeper.GetParams(sdkCtx)
			changed := false
			newChains := make([]*coretypes.BridgeChainConfig, 0, len(params.BridgeChains))
			for _, chain := range params.BridgeChains {
				if chain.ChainId == "osmosis" {
					sdkCtx.Logger().Info("v1.10.0-remove-ibc: removing Osmosis from bridge_chains")
					changed = true
					continue
				}
				newChains = append(newChains, chain)
			}

			if changed {
				params.BridgeChains = newChains
				if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
					sdkCtx.Logger().Error("v1.10.0-remove-ibc: failed to update params", "err", err)
					return nil, err
				}
				sdkCtx.Logger().Info("v1.10.0-remove-ibc: params updated - Osmosis removed")
			} else {
				sdkCtx.Logger().Info("v1.10.0-remove-ibc: Osmosis not in bridge_chains, no changes needed")
			}

			sdkCtx.Logger().Info("Upgrade to v1.10.0-remove-ibc complete - IBC support removed")
			return toVM, nil
		},
	)

	// v1.10.4-restore-sdk: Restore SDK modules that were soft-removed in v1.10.3-sdk-bloat
	// These modules were excluded from the app but their store data was preserved.
	// We just run migrations normally - stores will load their existing state.
	app.UpgradeKeeper.SetUpgradeHandler(
		sdkRestoreUpgradeName,
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.10.4-restore-sdk...")

			// Just run migrations normally - modules will load their existing store data
			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			sdkCtx.Logger().Info("Upgrade to v1.10.4-restore-sdk complete - SDK modules restored")
			return toVM, nil
		},
	)

	// v1.10.5: Cleanup one-time upgrade code from app.go
	// - Removed store loader logic for v1.10.4-restore-sdk (no longer needed after upgrade ran)
	// - No state migration needed, binary-only change
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.10.5",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.10.5...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			sdkCtx.Logger().Info("Upgrade to v1.10.5 complete - cleanup of one-time upgrade code")
			return toVM, nil
		},
	)

	// v1.10.7: Admin gas fee non-blocking
	// - Admin relay gas fee: skip deduction on insufficient balance instead of failing tx
	// - Admin operations should never be blocked over gas fees
	// - No state migration needed, binary-only change
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.10.7",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.10.7...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			sdkCtx.Logger().Info("Upgrade to v1.10.7 complete - admin gas fee non-blocking")
			return toVM, nil
		},
	)

	// v1.11.0: Target-based PoW difficulty (gradual scaling)
	// - Difficulty changes from bit-count to step count (0 = base, factor = 1000 * (1+step)^difficulty)
	// - Validation changes from leadingZeroBits to big.Int target comparison
	// - subscription_reserve_fraction changes from integer percent (0-100) to double fraction [0,1]
	// - bridge_attestation_threshold changes from basis points (0-10000) to double fraction [0,1]
	// - New param: pow_factor (double, default 0.25 = 25% per step)
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.11.0",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.11.0...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// --- 1. Read old param values from raw protobuf bytes ---
			// The wire type for subscription_reserve_fraction (field 42) and bridge_attestation_threshold (field 51)
			// changed from varint to double, so we must extract old values from raw bytes before unmarshal.
			store := app.CoreKeeper.StoreService().OpenKVStore(sdkCtx)
			rawParams, err := store.Get([]byte("params"))
			if err != nil || len(rawParams) == 0 {
				sdkCtx.Logger().Error("v1.11.0: no raw params found, using defaults")
				rawParams = nil
			}

			oldSubReserve := uint64(80) // default if not found
			oldBridgeThreshold := uint64(6667)
			if rawParams != nil {
				if v, ok := extractProtoVarint(rawParams, 42); ok {
					oldSubReserve = v
				}
				if v, ok := extractProtoVarint(rawParams, 51); ok {
					oldBridgeThreshold = v
				}
			}
			sdkCtx.Logger().Info("v1.11.0: extracted old param values",
				"old_subscription_reserve_pct", oldSubReserve,
				"old_bridge_attestation_threshold", oldBridgeThreshold)

			// --- 2. Write fresh default params first so GetParams doesn't fail ---
			// (The old bytes will fail unmarshal due to wire type change.)
			defaults := coretypes.DefaultParams()
			if err := app.CoreKeeper.SetParams(sdkCtx, defaults); err != nil {
				return nil, err
			}

			// --- 3. Now read params with new types and apply merges ---
			params := app.CoreKeeper.GetParams(sdkCtx)

			// Convert subscription_reserve_fraction: old integer (0-100) → fraction [0,1]
			newSubReserve := float64(oldSubReserve) / 100.0
			if newSubReserve > 1 {
				newSubReserve = 1
			}
			params.SubscriptionReservePercent = newSubReserve
			sdkCtx.Logger().Info("v1.11.0: converted subscription_reserve_percent", "old", oldSubReserve, "new", newSubReserve)

			// Convert bridge_attestation_threshold: old basis points (0-10000) → fraction [0,1]
			newBridgeThreshold := float64(oldBridgeThreshold) / 10000.0
			if newBridgeThreshold > 1 {
				newBridgeThreshold = 1
			}
			if newBridgeThreshold <= 0 {
				newBridgeThreshold = 0.6667
			}
			params.BridgeAttestationThreshold = newBridgeThreshold
			sdkCtx.Logger().Info("v1.11.0: converted bridge_attestation_threshold", "old", oldBridgeThreshold, "new", newBridgeThreshold)

			// Set pow_difficulty_step if zero
			if params.PowDifficultyStep == 0 {
				params.PowDifficultyStep = 0.25
				sdkCtx.Logger().Info("v1.11.0: set pow_difficulty_step", "value", 0.25)
			}

			if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
				return nil, err
			}
			sdkCtx.Logger().Info("v1.11.0: params migrated successfully")

			// --- 4. Convert difficulty from bit-count to factor ---
			oldDiff := app.CoreKeeper.GetCurrentDifficulty(sdkCtx)
			baseBits := params.MinDifficulty

			// After GetCurrentDifficulty with new code, the old bit-count value was read as-is.
			// If it's below BaseDifficultyFactor, it was an old bit-count value that needs conversion.
			// If it's already >= BaseDifficultyFactor, it was already in factor format.
			rawDiffBz, _ := store.Get([]byte("current_difficulty"))
			if len(rawDiffBz) == 8 {
				oldDiff = binary.BigEndian.Uint64(rawDiffBz)
			}

			baseFactor := corekeeper.BaseDifficultyFactor
			powFactor := params.PowDifficultyStep
			factor := oldDiff
			if oldDiff < baseFactor {
				// Old value is a bit-count; convert to factor: base_factor * 2^(old - pow_base_bits)
				shift := uint64(0)
				if oldDiff > baseBits {
					shift = oldDiff - baseBits
				}
				if shift > 53 {
					factor = corekeeper.MaxSafeDifficultyFactor
				} else {
					factor = baseFactor << shift
					if factor > corekeeper.MaxSafeDifficultyFactor {
						factor = corekeeper.MaxSafeDifficultyFactor
					}
				}
				sdkCtx.Logger().Info("v1.11.0: converted difficulty bit-count to factor",
					"old_bits", oldDiff, "pow_base_bits", baseBits, "shift", shift, "factor", factor)
			} else {
				sdkCtx.Logger().Info("v1.11.0: difficulty already in factor format", "value", oldDiff)
			}

			// Convert factor to difficulty steps: steps = log(factor/base_factor) / log(1 + pow_factor)
			if math.IsNaN(powFactor) || math.IsInf(powFactor, 0) || powFactor <= 0 || powFactor > 1 {
				return nil, fmt.Errorf("v1.11.0: invalid pow_factor: %v", powFactor)
			}
			steps := uint64(0)
			if factor > baseFactor {
				ratio := float64(factor) / float64(baseFactor)
				exp := math.Log(ratio) / math.Log(1+powFactor)
				if math.IsNaN(exp) || math.IsInf(exp, 0) {
					return nil, fmt.Errorf("v1.11.0: difficulty step conversion overflow")
				}
				steps = uint64(math.Round(exp))
				if steps > corekeeper.MaxSafeDifficultySteps {
					steps = corekeeper.MaxSafeDifficultySteps
				}
			}
			sdkCtx.Logger().Info("v1.11.0: converted difficulty factor to steps",
				"factor", factor, "pow_factor", powFactor, "steps", steps)
			if err := app.CoreKeeper.SetCurrentDifficulty(sdkCtx, steps); err != nil {
				return nil, err
			}

			sdkCtx.Logger().Info("Upgrade to v1.11.0 complete - target-based PoW difficulty enabled")
			return toVM, nil
		},
	)

	// v1.12.0: Add dedicated media field to MsgPost, rename params for clarity
	// - MsgPost gains repeated string 'media' field (proto field 105)
	// - Params field renames (wire-compatible, same field numbers):
	//     PowBaseBits → MinDifficulty, PowIncreaseThreshold → PowMessageLimit,
	//     PowDifficultyGracePeriod → PowDifficultyAllowance, PowFactor → PowDifficultyStep,
	//     MintDynamicFraction → MintDynamicSplit, SubscriptionReserveFraction → SubscriptionReservePercent
	// - No state migration needed (field numbers unchanged, protobuf binary compatible)
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.12.0",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.12.0...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			sdkCtx.Logger().Info("Upgrade to v1.12.0 complete - media field on MsgPost, params renamed")
			return toVM, nil
		},
	)

	// v1.13.0: Topic blocking + quality_posts removal
	// - TierConfig field 7 renamed from max_quality_posts to max_blocked_topics (same wire format)
	// - New MsgBlockTopic / MsgUnblockTopic message types
	// - Old plist_quality/ KV data is orphaned (no code reads it) — cleaned up here
	// - Tier configs updated with correct MaxBlockedTopics values (10/125/500/1000)
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.13.0",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.13.0...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Update tier configs with correct MaxBlockedTopics values.
			// Field 7 was renamed from max_quality_posts to max_blocked_topics (same field number),
			// so existing chains may have stale values from the old quality_posts feature.
			params := app.CoreKeeper.GetParams(sdkCtx)
			desiredMaxBlockedTopics := []uint64{10, 125, 500, 1000}
			changed := false
			for i, tier := range params.Tiers {
				if i < len(desiredMaxBlockedTopics) && tier.MaxBlockedTopics != desiredMaxBlockedTopics[i] {
					sdkCtx.Logger().Info("v1.13.0: updating MaxBlockedTopics",
						"tier", i, "old", tier.MaxBlockedTopics, "new", desiredMaxBlockedTopics[i])
					tier.MaxBlockedTopics = desiredMaxBlockedTopics[i]
					params.Tiers[i] = tier
					changed = true
				}
			}
			if changed {
				if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
					sdkCtx.Logger().Error("v1.13.0: failed to update params", "err", err)
					return nil, err
				}
				sdkCtx.Logger().Info("v1.13.0: tier MaxBlockedTopics updated")
			}

			// Clean up orphaned plist_quality/ KV data from removed quality_posts feature.
			// This prefix is no longer read by any code, so we delete all keys under it.
			store := app.CoreKeeper.StoreService().OpenKVStore(sdkCtx)
			qualityPrefix := []byte("plist_quality/")
			iter, err := store.Iterator(qualityPrefix, storetypes.PrefixEndBytes(qualityPrefix))
			if err == nil {
				deletedCount := 0
				for ; iter.Valid(); iter.Next() {
					_ = store.Delete(iter.Key())
					deletedCount++
				}
				iter.Close()
				if deletedCount > 0 {
					sdkCtx.Logger().Info("v1.13.0: cleaned up orphaned quality_posts data", "keys_deleted", deletedCount)
				}
			}

			// Increase MintQuantity: 350 MIRAGE → 125,000 MIRAGE per 10min (~357x)
			if params.MintQuantity != 125_000_000_000 {
				sdkCtx.Logger().Info("v1.13.0: updating MintQuantity",
					"old", params.MintQuantity, "new", 125_000_000_000)
				params.MintQuantity = 125_000_000_000
				if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
					sdkCtx.Logger().Error("v1.13.0: failed to update MintQuantity", "err", err)
					return nil, err
				}
			}

			sdkCtx.Logger().Info("Upgrade to v1.13.0 complete - topic blocking, quality_posts removed, minting increased")
			return toVM, nil
		},
	)

	// v1.14.0: MsgDeleteUser for account deletion
	// - New MsgDeleteUser message type: self-signed (envelope_pubkey derives to target) or governance
	// - DeleteUserState: clears profile KV, lists, username, subscription; sweeps spendable to community pool
	// - Indexer: soft-deletes profile (deleted_at) for post attribution; upsert clears deleted_at on re-register
	// - No on-chain state migration needed — just new message types
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.14.0",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.14.0...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			sdkCtx.Logger().Info("Upgrade to v1.14.0 complete - MsgDeleteUser enabled")
			return toVM, nil
		},
	)

	// v1.15.0: Awards (burn-only signal)
	// - MsgAward: burns MIRAGE to give an award to a post/comment (free for level >= 100)
	// - award_configs added to Params (replaces unused award_permissions on TierConfig)
	// - Indexer stores award records; backend aggregates for display and magic scoring
	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.15.0",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.15.0...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			params := app.CoreKeeper.GetParams(sdkCtx)
			if len(params.AwardConfigs) == 0 {
				params.AwardConfigs = coretypes.DefaultAwardConfigs()
				if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
					return nil, err
				}
				sdkCtx.Logger().Info("v1.15.0: set default award_configs")
			}

			sdkCtx.Logger().Info("Upgrade to v1.15.0 complete - MsgAward + award_configs")
			return toVM, nil
		},
	)

	app.UpgradeKeeper.SetUpgradeHandler(
		"v1.16.0",
		func(ctx context.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
			sdkCtx := sdk.UnwrapSDKContext(ctx)
			sdkCtx.Logger().Info("Starting upgrade to v1.16.0...")

			toVM, err := app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
			if err != nil {
				return nil, err
			}

			// Migrate KV prefix plist_mods/* -> plist_agents/*
			store := app.CoreKeeper.StoreService().OpenKVStore(sdkCtx)
			oldPrefix := []byte("plist_mods/")
			newPrefix := []byte("plist_agents/")
			it, err := store.Iterator(oldPrefix, storetypes.PrefixEndBytes(oldPrefix))
			if err != nil {
				return nil, fmt.Errorf("failed to iterate plist_mods: %w", err)
			}
			var keys [][]byte
			var vals [][]byte
			for ; it.Valid(); it.Next() {
				keys = append(keys, append([]byte(nil), it.Key()...))
				vals = append(vals, append([]byte(nil), it.Value()...))
			}
			it.Close()

			migrated := 0
			for i, oldKey := range keys {
				suffix := oldKey[len(oldPrefix):]
				newKey := make([]byte, len(newPrefix)+len(suffix))
				copy(newKey, newPrefix)
				copy(newKey[len(newPrefix):], suffix)
				if err := store.Set(newKey, vals[i]); err != nil {
					return nil, fmt.Errorf("failed to set new key: %w", err)
				}
				if err := store.Delete(oldKey); err != nil {
					return nil, fmt.Errorf("failed to delete old key: %w", err)
				}
				migrated++
			}
			sdkCtx.Logger().Info("v1.16.0: migrated plist_mods -> plist_agents", "count", migrated)

			// Set new tier defaults (Free=0, Subscriber=1, Agent=10)
			params := app.CoreKeeper.GetParams(sdkCtx)
			params.Tiers = coretypes.DefaultTiers()
			if err := app.CoreKeeper.SetParams(sdkCtx, params); err != nil {
				return nil, fmt.Errorf("failed to set new tier params: %w", err)
			}
			sdkCtx.Logger().Info("v1.16.0: set tier defaults (Free=0, Subscriber=1, Agent=10)")

			// Migrate existing profile JSON:
			// 1. Strip is_moderator field
			// 2. Remap user levels: old 0->0, 1->1, 2->1, 3->10
			profiles, pErr := app.CoreKeeper.GetAllProfiles(sdkCtx)
			if pErr == nil {
				migrated := 0
				for _, bz := range profiles {
					var m map[string]interface{}
					if err := json.Unmarshal(bz, &m); err != nil {
						continue
					}
					changed := false
					if _, ok := m["is_moderator"]; ok {
						delete(m, "is_moderator")
						changed = true
					}
					// Remap level: old tiers 0=Free, 1=Trusted, 2=Established, 3=Distinguished
					// New tiers: 0=Free, 1=Subscriber, 10=Agent
					if lvl, ok := m["level"]; ok {
						var oldLevel int
						switch v := lvl.(type) {
						case float64:
							oldLevel = int(v)
						case int:
							oldLevel = v
						}
						var newLevel int
						switch oldLevel {
						case 0:
							newLevel = 0
						case 1, 2, 3:
							newLevel = 1
						default:
							if oldLevel >= 100 {
								newLevel = oldLevel // preserve admin levels
							} else {
								newLevel = 0
							}
						}
						if newLevel != oldLevel {
							m["level"] = newLevel
							changed = true
						}
					}
					if changed {
						owner, _ := m["owner"].(string)
						newBz, err := json.Marshal(m)
						if err != nil || owner == "" {
							continue
						}
						_ = app.CoreKeeper.SetProfileCore(sdkCtx, owner, newBz)
						migrated++
					}
				}
				sdkCtx.Logger().Info("v1.16.0: migrated profiles (is_moderator removal + level remap)", "count", migrated)
			}

			sdkCtx.Logger().Info("Upgrade to v1.16.0 complete")
			return toVM, nil
		},
	)
}

// extractProtoVarint scans raw protobuf bytes for a field with the given tag number (varint wire type = 0)
// and returns its value. Returns (0, false) if not found.
func extractProtoVarint(data []byte, fieldNum uint64) (uint64, bool) {
	i := 0
	for i < len(data) {
		// Decode tag (field_number << 3 | wire_type)
		tag, n := binary.Uvarint(data[i:])
		if n <= 0 {
			return 0, false
		}
		i += n
		wireType := tag & 0x7
		fnum := tag >> 3

		switch wireType {
		case 0: // varint
			val, n := binary.Uvarint(data[i:])
			if n <= 0 {
				return 0, false
			}
			i += n
			if fnum == fieldNum {
				return val, true
			}
		case 1: // 64-bit
			if i+8 > len(data) {
				return 0, false
			}
			if fnum == fieldNum {
				// Interpret as float64 → uint64 (for reading old double fields)
				bits := binary.LittleEndian.Uint64(data[i:])
				f := math.Float64frombits(bits)
				return uint64(f), true
			}
			i += 8
		case 2: // length-delimited
			length, n := binary.Uvarint(data[i:])
			if n <= 0 {
				return 0, false
			}
			i += n + int(length)
		case 5: // 32-bit
			i += 4
		default:
			return 0, false
		}
	}
	return 0, false
}
