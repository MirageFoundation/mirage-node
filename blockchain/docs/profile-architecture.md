# Profile Data Architecture

This document describes how user profiles are stored, exported, and imported in the Mirage blockchain.

## Data Model

### ProfileCore (Scalar Fields)

Defined in `proto/mirage/core/v1/genesis.proto` and auto-generated into `x/core/types/genesis.pb.go`.

**DO NOT duplicate this struct elsewhere.** The proto definition is the single source of truth.

Fields:
- `owner` (string): Account address, primary key
- `username` (string): Claimed username
- `level` (int32): Subscription tier (0=Free, 1=Subscriber, 10=Agent, 100+=admin)
- `created_at` (int64): Unix timestamp of profile creation
- `subscription_expiry` (int64): Unix timestamp when subscription expires (0 = no subscription)
- `auto_renew` (bool): Whether subscription auto-renews
- `reserve_funds` (uint64): Escrowed gas reserve in umirage
- `biography` (string): User bio text
- `avatar` (string): Avatar URL
- `banner` (string): Banner URL

### List Fields (Stored Separately)

For performance, list fields are stored at separate KV prefixes rather than in ProfileCore:

| Prefix | Description | Keeper Methods |
|--------|-------------|----------------|
| `plist_agents/{owner}` | Agents the user has enabled | `SetProfileEnabledAgents`, `GetProfileEnabledAgents` |
| `followed_users/{owner}` | Users the user follows | `SetProfileFollowedUsers`, `GetProfileFollowedUsers` |
| `followed_topics/{owner}` | Topics the user follows | `SetProfileFollowedTopics`, `GetProfileFollowedTopics` |
| `blocked_users/{owner}` | Users the user has blocked | `SetProfileBlockedUsers`, `GetProfileBlockedUsers` |
| `blocked_posts/{owner}` | Posts the user has blocked | `SetProfileBlockedPosts`, `GetProfileBlockedPosts` |
| `blocked_topics/{owner}` | Topics the user has blocked | `SetProfileBlockedTopics`, `GetProfileBlockedTopics` |

## Genesis Export/Import

### ExportGenesis

Exports ALL key-value pairs from the module's KV store into `raw_state`. This includes:
- All ProfileCore data
- All list fields
- Username claims
- Subscriptions index
- Any other KV pairs

This is the complete, authoritative export.

### InitGenesis

Import order:
1. **Import `raw_state`** first (complete KV restore)
2. **Process `initial_profiles`** only if profile NOT already present in KV

The `InitialProfile` message wraps `ProfileCore` plus all list fields:

```protobuf
message InitialProfile {
  ProfileCore core = 1;
  repeated string enabled_agents = 2;
  repeated string followed_users = 3;
  repeated string followed_topics = 4;
  repeated string blocked_users = 5;
  repeated string blocked_posts = 6;
  repeated string blocked_topics = 7;
}
```

This allows backfilling profiles from external sources (like the indexer DB) when the chain export is incomplete.

## Indexer Database

The indexer DB (PostgreSQL) stores the full history of profile list data (up to 100k per user per list via `INDEXER_LIST_CAP`). This is the long-term storage layer; the chain keeps only a small deque window per tier.

| Table | Description |
|-------|-------------|
| `profiles` | Core profile data |
| `enabled_agents` | Enabled agents |
| `followed_users` | Followed users |
| `followed_topics` | Followed topics |
| `blocked_users` | Blocked users |
| `blocked_posts` | Blocked posts |
| `blocked_topics` | Blocked topics |

The `get_profile` API returns scalar fields from the chain and list fields from the indexer. Feed filtering also reads from the indexer. This means users see their full block/follow history even after the chain evicts old entries from its deque.

## Adding New Profile Fields

### Scalar Fields

1. Add field to `ProfileCore` in `proto/mirage/core/v1/genesis.proto`
2. Run `make proto-gen` to regenerate Go code
3. Update any code that creates/modifies ProfileCore
4. Add migration in upgrade handler if needed for existing chains

### List Fields

1. Add new prefix constant in `x/core/types/keys.go`
2. Add `Set` and `Get` methods in `x/core/keeper/keeper.go`
3. Add field to `InitialProfile` in `genesis.proto`
4. Update `InitGenesis` to import the new list
5. Run `make proto-gen`
6. If needed for backfill, add table to indexer DB and update reset script

## Type Considerations

- `ProfileCore.Level` is `int32` (proto limitation)
- Internal Go code often uses `int` for level comparisons
- Cast with `int(core.Level)` when needed
- The `Profile` struct in `types/types.go` uses `int32` to match

