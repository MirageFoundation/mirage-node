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

### List Fields (Per-Entry KV Storage)

All six profile lists use **per-entry KV keys** for O(1) add/remove/has operations.
Three flavors of the same underlying pattern:

#### Unordered Set (followed_users, followed_topics)

| Key | Value | Description |
|-----|-------|-------------|
| `{prefix}{owner}/{entry}` | `[]byte{1}` (sentinel) | One key per entry |
| `{prefix}{owner}\x00c` | `uint32` big-endian | Entry count |

- **Has**: single KV Get — O(1)
- **Add**: Get count → check cap → Set entry + increment count — O(1)
- **Remove**: Delete entry + decrement count — O(1)
- **List**: prefix iterator — O(n)

#### Ordered Set (enabled_agents)

| Key | Value | Description |
|-----|-------|-------------|
| `ea/{owner}/{agent}` | `uint64` big-endian (position) | One key per agent |
| `ea/{owner}\x00c` | `uint32` big-endian | Entry count |
| `ea/{owner}\x00s` | `uint64` big-endian | Next position to assign |

- **AddAgent**: assign next position, increment seq and count — O(1)
- **RemoveAgent**: delete entry, decrement count — O(1). Gaps in position are fine.
- **ListOrdered**: prefix iterate, sort by position — O(n log n), n ≤ 50
- **ReplaceAll**: delete all + write with positions 0..n-1, reset seq — O(n)

#### Deque (blocked_users, blocked_posts, blocked_topics)

Same as ordered set but with **eviction**: when over cap, the entry with the lowest sequence is deleted.

| Key | Value | Description |
|-----|-------|-------------|
| `{prefix}{owner}/{entry}` | `uint64` big-endian (sequence) | One key per entry |
| `{prefix}{owner}\x00c` | `uint32` big-endian | Entry count |
| `{prefix}{owner}\x00s` | `uint64` big-endian | Next sequence |

#### Prefix Table

| Prefix | List Type | Keeper Methods |
|--------|-----------|----------------|
| `fu/` | Followed users (unordered set) | `AddFollowedUser`, `RemoveFollowedUser`, `HasFollowedUser`, `CountFollowedUsers`, `ListFollowedUsers`, `DeleteAllFollowedUsers` |
| `ft/` | Followed topics — retired in v1.39.0 | `DeleteAllFollowedTopics` |
| `ea/` | Enabled agents — retired in v1.39.0 | `DeleteAllEnabledAgents` |
| `bu/` | Blocked users (deque) | `AddBlockedUserDeque`, `RemoveBlockedUser`, `HasBlockedUser`, `CountBlockedUsers`, `ListBlockedUsers`, `DeleteAllBlockedUsers` |
| `bp/` | Blocked posts (deque) | `AddBlockedPostDeque`, `RemoveBlockedPost`, `HasBlockedPost`, `CountBlockedPosts`, `ListBlockedPosts`, `DeleteAllBlockedPosts` |
| `bt/` | Blocked topics — retired in v1.39.0 | `DeleteAllBlockedTopics` |

The three retired prefixes are drained by `MigrateV139` and their messages are rejected by
`RetiredMsgDecorator`; only the `DeleteAll*` sweeps remain, called from `DeleteUserState`.

Legacy JSON-blob prefixes (`plist_agents/`, `plist_users/`, etc.) are kept for compile-time compatibility with the v1.3.0-tiers historical upgrade handler and for migration reads.

## Genesis Export/Import

### ExportGenesis

Exports ALL key-value pairs from the module's KV store into `raw_state`. This includes:
- All ProfileCore data
- All per-entry list keys
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

For `initial_profiles`, lists are written as per-entry keys using `AddFollowedUser`, `AddBlockedUserDeque`, etc.

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
2. Add public per-entry methods in `x/core/keeper/keeper.go` (using the generic `addSetEntry`/`addDequeEntry` helpers)
3. Add field to `InitialProfile` in `genesis.proto`
4. Update `InitGenesis` to import the new list using per-entry methods
5. Run `make proto-gen`
6. If needed for backfill, add table to indexer DB and update reset script

## Type Considerations

- `ProfileCore.Level` is `int32` (proto limitation)
- Internal Go code often uses `int` for level comparisons
- Cast with `int(core.Level)` when needed
- The `Profile` struct in `types/types.go` uses `int32` to match
