# Mirage v1.5 Release Notes

**Version:** 1.5.0  
**Codename:** Social Graph

---

## Overview

Mirage v1.5 turns the chain and app into a real social graph. The previous production release already shipped subscription tiers, but most interactions were still simple posts in topics. This upgrade connects those tiers to an on-chain social graph, adds feed personalization, and upgrades the protocol so we can safely add richer features like cross posting and content tags.

---

## What you can do today

### Build a personal Home feed

- Follow individual users directly from posts, comments, and profiles.
- Follow topics you care about; your `Home` feed now blends posts from both followed topics and followed users.
- Follows are stored on-chain and enforced per tier, so your social graph travels with you across devices and frontends.

### Block once, forget everywhere

- Block specific posts and block user accounts you do not want to see.
- Blocks are now first-class on-chain data instead of temporary indexer flags, which means they apply consistently across sessions and devices.
- Tier limits define how many posts and users you can block, so heavy users can curate aggressively without impacting the rest of the network.

### Tiers that shape your social graph

Subscription tiers were already live in the last production build. v1.5 extends them so they now control:

- How many moderators, users, and topics you can follow.
- How many users and posts you can block.
- How long and how often you can edit content after publishing.
- Maximum title and content length per tier.
- Vote weight multiplier, profile features, and moderator eligibility.

#### Tier comparison

| Feature            | Free | Tier 1 | Tier 2 | Tier 3 |
|--------------------|------|--------|--------|--------|
| Follow Users       | 25   | 125    | 500    | 1,000  |
| Follow Topics      | 50   | 250    | 500    | 1,000  |
| Cross-post budget* | 0    | 10     | 25     | 100    |
| Content Length     | 1,000| 2,000  | 5,000  | 25,000 |
| Edit Window        | 10 min | 1 hour | 6 hours | 12 hours |
| Vote Weight        | 1.0x | 1.15x  | 1.30x  | 1.45x  |
| Custom Username    | No   | Yes    | Yes    | Yes    |
| Avatar & Banner    | No   | Yes    | Yes    | Yes    |
| Moderator Eligible | No   | No     | Yes    | Yes    |

\*Cross-post budget is a protocol limit. The current UI still targets a single topic per post; multi-topic posting will roll out in a later UI update.

### Easier subscription management

- New `SetAutoRenewal` transaction and `/api/core/set_auto_renewal` endpoint.
- The Subscription page now shows your current tier, next renewal time, and a clear toggle for auto-renew, backed by on-chain state.
- Paid subscribers continue to skip PoW for posting and voting; free users still use Argon2id PoW.

---

## Protocol and performance changes

### Social graph primitives on-chain

- New message types for following and unfollowing users and topics, and for blocking and unblocking posts and users.
- Follows, blocks, and "quality posts" are now stored in the core module state and indexed in PostgreSQL tables.
- The indexer exposes this data to the app, powering the Home feed, Settings view, and future recommendation features.

### Multi-topic posts and content tags

- `MsgPost` and `MsgEdit` now carry a `topics` array instead of a single `topic` string, plus a new `tag` field for content classification.
- The indexer stores primary and secondary topics in a `post_topics` table, so a single post can appear in multiple communities without duplication.
- The current UI continues to use one topic per post; the protocol and backend are ready for cross posting and content tags in upcoming releases.

### Stronger replay protection and cleaner signatures

- All relayed messages now include an `envelope_timestamp`, with a new `max_envelope_age` chain parameter (default 60 seconds). Transactions older than this window are rejected.
- The node, backend, and frontend share a single canonical-byte format for every supported message type, reducing signature mismatches across platforms.
- Timestamp skew handling has been tuned so honest clients are accepted while stale or far-future transactions are rejected quickly.

### Database and infrastructure

- The indexer schema has been extended for multi-topic posts, follows, blocks, quality posts, and subscription events.
- Legacy SQLite migration code and backward-compatibility shims have been removed; Mirage now relies solely on PostgreSQL.
- PostgreSQL logging and local reset scripts have been improved to make development and observability smoother.

---

## For developers and integrators

See the technical migration guide in the developer docs (`chain-rpc-examples.md`) for concrete RPC and message examples.

Key changes since the last production release:

- Posts:
  - `topic` field replaced with `topics` array.
  - New `tag` field for content labels and future content warnings.
- Social graph and safety:
  - New messages and HTTP endpoints: `follow_user`, `unfollow_user`, `follow_topic`, `unfollow_topic`, `block_post`, `unblock_post`, `block_user`, `unblock_user`.
  - New `followed_users`, `followed_topics`, `blocked_users`, `blocked_posts`, and `quality_posts` tables in the indexer.
- Subscriptions:
  - New `MsgSetAutoRenewal` and `/api/core/set_auto_renewal` endpoint to toggle auto-renew without changing tier.
- Relay and signing:
  - All write endpoints now require a client-side `timestamp` field that maps to `envelope_timestamp` on-chain.
  - Canonical bytes for relay signatures have changed; see `ante_metasig.go`, `shared/canon.py`, and `web/backend/pow.py` for the exact format.
- Tooling and deployment:
  - `deploy/deploy.sh` gained a `--build-only` mode for producing tarballs without deploying.
  - Added safer multi-host deployment workflow by reusing a single pre-built image tarball across servers.
  - Tmux configuration is bundled via `deploy/templates/tmux.conf` inside the Docker image.
