package app

import (
	"context"
	"encoding/json"

	upgradetypes "cosmossdk.io/x/upgrade/types"
	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/cosmos/cosmos-sdk/types/module"

	coretypes "mirage/x/core/types"
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
					{"followed_moderators", app.CoreKeeper.SetProfileFollowedMods},
					{"followed_users", app.CoreKeeper.SetProfileFollowedUsers},
					{"followed_topics", app.CoreKeeper.SetProfileFollowedTopics},
					{"blocked_users", app.CoreKeeper.SetProfileBlockedUsers},
					{"blocked_posts", app.CoreKeeper.SetProfileBlockedPosts},
					{"quality_posts", app.CoreKeeper.SetProfileQualityPosts},
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
				params.SubscriptionReservePercent = 20 // 20% of monthly fee goes to reserve
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

			// Increase subscription reserve percent from 20% to 40%
			if params.SubscriptionReservePercent < 40 {
				params.SubscriptionReservePercent = 40
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
}
