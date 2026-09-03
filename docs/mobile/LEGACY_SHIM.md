# v1.39.0 legacy mobile shim

This document describes the temporary compatibility layer for the mobile release published before v1.39.0. It is an operator teardown manifest, not a supported contract for new clients. The permanent mobile target is `docs/mobile/v1.39.0-mobile-migration-guide.md`.

## Compatibility surface

Restored reads:

- `GET /api/get_topics` returns `{"topics":[...]}`. Each item has `topic`, `post_count`, `count`, `comment_count`, content-tag `flags`, `dominant_tag`, and `dominant_ratio`.
- `GET /api/search_topics?q=...` returns `{"topics":[...]}` with the same item shape. The query is stripped to alphanumerics, a query shorter than two characters returns an empty list, matching is substring, and results are ordered exact match, then prefix, then contains, each tie broken by post count then name. The default limit is 20 and the maximum is 50.
- `GET /api/get_agents` returns `{"agents":[]}`.
- `GET /api/get_invite_codes` returns `{"codes":[],"total":0,"available":0}`.
- `GET /api/rewards/summary` returns a complete disabled rewards model; `GET /api/rewards/achievements` returns `{"achievements":[]}`.
- `GET /api/referrals/precheck`, `GET /api/referrals/summary`, and `GET /api/referral/stats` return typed empty or disabled models.

Restored topic writes:

- `POST /api/core/follow_topic` broadcasts the original `MsgFollowTopic`. Following removes matching blocked-community patterns and joins the exact community with the default live lens.
- `POST /api/core/unfollow_topic` broadcasts `MsgUnfollowTopic` and leaves the exact community.
- `POST /api/core/block_topic` broadcasts `MsgBlockTopic`. Its signed `target` must be empty; blocking records the pattern and leaves every joined community it matches.
- `POST /api/core/unblock_topic` broadcasts `MsgUnblockTopic`. Its signed `target` must be empty and the matching blocked pattern is removed.

Normalized existing routes:

- `GET /api/get_posts?topic=` is rewritten to `community=`. Conflicting topic and community values fail with `invalid_input`.
- `GET /api/bootstrap?view=topic:<slug>` is rewritten to `view=community:<slug>`.
- `GET /api/search?type=topics` uses community search and adds `topics`, `has_more_topics`, and the topic-era search type.
- `POST /api/core/post` copies a nonconflicting `topic` field to `community`. When `topic` is present and `protocol_version` is omitted, it verifies the old signature and broadcasts protocol version 0; an explicit modern protocol version remains on the modern canonical path.
- `POST /api/core/edit` copies a nonconflicting `topic` body field to `community`.
- `POST /api/core/subscribe` accepts an omitted `period_count`; level 1 buys one subscriber period, and cached level 10 also buys exactly one subscriber period at the subscriber price.

All JSON responses may receive additive aliases. `community` gains `topic`, `root_community` gains `root_topic`, `joined_communities` gains `followed_topics`, and `blocked_communities` gains `blocked_topics`; modern keys are never removed or overwritten. Preferences, search, stats, bootstrap, transaction status, chain config, node config, profiles, and followed lists receive the old typed fields the published app reads. Legacy config responses expose only Free and Subscriber tiers and disable Agent, quest, invite-reward, and referral surfaces.

Still retired:

- Agent and annotation writes: `/api/core/enable_agent`, `/api/core/disable_agent`, `/api/core/set_agents`, and `/api/core/annotate`.
- Reward, referral, and quest writes, including `/api/rewards/claim` and `/api/referrals/precheck_opt_in`.
- Invite validation: `/api/validate_invite_code`.
- Claimed-community ownership writes: `/api/core/create_community`, `/api/core/set_community_metadata`, and `/api/core/transfer_community`.

These writes return HTTP 410 with `error_code: "gone"` and a `retired` endpoint label. The shim never fabricates a transaction hash or reports a retired write as successful.

## How a request is classified as legacy

The published app sends no version or platform header, so the bridge uses the header the v1.39 contract requires instead: a request without `X-Mirage-Visitor` may be the published app. The web frontend sends it on every request (`web/frontend/src/utils/visitorId.js`), the test suites send it, and migrated clients must send it.

Most compatibility work needs no classification at all: restored paths are legacy by definition, response aliases are additive, and body/query rewrites trigger on the old field names. Only three behaviors depend on the header, and only one of them is lossy:

- `GET /api/get_chain_config` and the `chain_config` section of `GET /api/bootstrap` expose only Free and Subscriber. The published app maps tier index 2 onto its Agent purchase card, so a third tier would offer an unbuyable plan. A client that sends the header always sees every tier.
- `GET /api/get_node_config` and the bootstrap `node_config`, `rewards_summary`, and `invite_codes` sections gain disabled Agent, quest, invite, and referral fields.
- Unsigned `address` personalization and the retired bootstrap read action are refused once the header is present.

## Canonical and chain exceptions

The compatibility cases preserve the bytes signed by the published app:

- Legacy `MsgPost` includes payload tags 100 through 105 and omits tag 106. The protobuf carries `protocol_version=0`. Modern posts include tag 106 with value 1.
- Legacy `MsgSubscribe` signs the original level at tag 100, an optional gift target at tag 101, and omits tag 102. The protobuf carries `period_count=0`; chain semantics use one period. Level 10 is only a wire alias for level-1 Subscriber semantics.
- `MsgFollowTopic` and `MsgUnfollowTopic` sign the owner target at tag 100 and the topic at tag 101.
- `MsgBlockTopic` and `MsgUnblockTopic` sign an encoded empty string at tag 100 and the block pattern at tag 101. The empty field is not omitted.

`shared/testdata/canon_v139_vectors.json` pins these bytes for both the Go and the Python builders, but a vector this repo generates cannot prove it matches the shipped client. Verify that against the app's own builder with the mobile checkout present:

```bash
node --experimental-strip-types scripts/legacy_mobile_canon_check.mjs [/path/to/mirage-mobile-app]
```

It imports `src/api/write/signing/canonical.ts` verbatim and fails on the first byte of disagreement. Run it whenever a legacy vector or a canonical builder changes. It is not a suite test because the mobile repo does not exist inside the test container.

The backend cannot translate these messages into modern message names because it cannot re-sign user bytes. The four topic messages therefore remain live through protobuf RPC registration, relay routing, signature ante, PoW/quota ante, chain handlers, and indexer projection for the bridge window. Agent and Annotate messages remain decode-only and retired.

## Known limitations and security boundary

Posts and replies created after the v1.39 upgrade have chain metadata and can receive legacy-mobile replies. Threads created before v1.39 remain readable, but new replies to them fail with `legacy_thread_read_only`; accepting unsigned parent metadata would make consensus depend on an untrusted backend claim.

That rejection is **not** part of the bridge. The chain refuses a reply whose parent has no metadata regardless of protocol version, so a migrated protocol-1 client replying to a pre-v1.39 thread is refused identically. The error code, its registry entry, its frontend copy, its classification in `web/backend/routes/core.py` (`_classify_thread_read_only`), and the permanent test `comments.reply_needs_parent_metadata` therefore all stay after teardown.

When all proof fields are absent, `X-Mirage-Visitor` is absent, and `address` is a valid Mirage address, the bridge honors that address for personalization on `/api/get_posts`, `/api/get_comments`, `/api/get_user_posts`, `/api/search`, and `/api/bootstrap`, and on the restored `/api/get_topics` and `/api/search_topics`. The list is enforced by path, because several routes share the `get_posts` read action and must not inherit it implicitly.

Anyone can spoof that address. It may alter vote, block, and tag presentation, but it never sets verified identity and is not used for writes, rewards, visitor attribution, curator reads, or admin authorization. Partial proofs still fail, and signed modern reads keep their normal verification.

The published app signs logged-in bootstrap reads with the retired `get_invite_codes:<address>:<timestamp>:<nonce>` action. The bridge retries that action only after modern content-read verification fails, only on `/api/bootstrap`, and only when `X-Mirage-Visitor` is absent. Migrated clients must sign `get_posts` for bootstrap feeds and `get_comments` for bootstrap threads.

A post created through the bridge is protocol 0, so besides being curated normally in `scope=current` it also appears in the `scope=legacy` protocol-0 archive. It does carry chain metadata, unlike genuinely pre-v1.39 posts, and the indexer requires that metadata for every post finalized from the recorded activation height onward (`meta.post_metadata_from_height`).

The level-10 subscription alias does not recreate Agent privileges, Agent state, or Agent pricing. It purchases one ordinary subscriber period. Disabled Agent/reward/referral read models exist only to keep old screens from crashing.

## Telemetry

Backend compatibility events use one prefix and include a request ID where available, the path or action, and a per-process cumulative `total`. They never log signatures, private keys, full public keys, invite codes, or complete addresses.

- `legacy_mobile.install`: shim installed in a backend worker.
- `legacy_mobile.route`: restored path interception.
- `legacy_mobile.query_rewrite`: topic query or bootstrap/search view rewrite.
- `legacy_mobile.post_v0`: protocol-0 post preparation.
- `legacy_mobile.edit_topic`: topic-shaped edit preparation.
- `legacy_mobile.topic_action`: restored follow/unfollow/block/unblock action.
- `legacy_mobile.subscribe_period0`: subscription with omitted period count.
- `legacy_mobile.subscribe_level10`: cached level-10 subscription alias.
- `legacy_mobile.unsigned_read`: unsigned personalized content read; only an address prefix is logged.
- `legacy_mobile.bootstrap_signed_read`: accepted published-app bootstrap signature.
- `legacy_mobile.disabled_read`: typed disabled or empty feature read.
- `legacy_mobile.response_aliases`: additive response transformations; debug level because this is high volume.
- `legacy_mobile.topic_list_error` / `legacy_mobile.topic_search_error`: indexer failure while serving a restored topic read.

Count actual uses from the collected backend log stream with:

```bash
rg -o 'event=legacy_mobile\.[^ ]+' backend.log | sort | uniq -c
```

Do not sum cumulative `total` fields across workers or restarts. Count event lines over the agreed observation window, segmented by event and path/action. Exclude `legacy_mobile.install` and debug-only `legacy_mobile.response_aliases` when measuring active legacy clients. Chain logs also identify legacy `MsgPost`, `MsgSubscribe`, and `Msg*Topic` execution and can corroborate backend counts.

## Removal gate

Remove the shim only when all of these are true:

1. The migrated mobile release is publicly available in both app stores.
2. Mobile developers confirm every item in `docs/mobile/v1.39.0-mobile-migration-guide.md`.
3. Collected `legacy_mobile` route and write events show negligible usage for the agreed observation window.
4. The cutoff has been announced.
5. A coordinated node release is scheduled. Consensus compatibility must never be removed from one validator independently.

## Teardown manifest

Remove in reverse dependency order:

1. Restore retired-route expectations in `scripts/verify_upgrade.py`, `tests/cases/test_backend_retired.py`, `tests/cases/test_backend_authz.py`, and `tests/cases/test_backend_accounts.py`. Remove compatibility-only helpers/assertions from `tests/backend_helpers.py`, `tests/common.py`, `tests/cases/test_backend_content.py`, `tests/cases/test_backend_infra.py`, `tests/cases/test_backend_security.py`, `tests/cases/test_backend_social.py`, `tests/cases/test_backend_stats.py`, `tests/cases/test_backend_subscriptions.py`, and their category registrations in `tests/test_backend.py`.
2. Remove the preparation and exception-classification calls from `web/backend/routes/core.py`, both compatibility viewer calls from `web/backend/routes/public.py`, and the installation call from `web/backend/factory.py`. Keep the topic paths in `_GONE_PATHS`.
3. Delete `web/backend/legacy_mobile_wiring.py`. Restore strict protocol-1 post and explicit-period subscription handling, and remove compatibility-only arguments/branches from `web/backend/pow.py` and `shared/canon.py`. Keep `legacy_thread_read_only` in `web/backend/error_utils.py`, its frontend copy, and `_classify_thread_read_only` in `web/backend/routes/core.py`; that chain rule is permanent.
4. Remove the four topic RPC methods from `blockchain/proto/mirage/core/v1/tx.proto` and regenerate `blockchain/x/core/types/tx.pb.go`. Keep the historical message structs and field numbers.
5. In `blockchain/x/core/types/codec.go`, move `MsgFollowTopic`, `MsgUnfollowTopic`, `MsgBlockTopic`, and `MsgUnblockTopic` back to decode-only registration and restore them to `RetiredMsgTypeURLs()`.
6. Remove those four messages from `blockchain/app/relay_messages.go`, `blockchain/app/ante_metasig.go`, `blockchain/app/ante_pow.go`, and compatibility logging in `blockchain/app/ante_log.go`.
7. Restore unconditional modern tag-106 and tag-102 canonical encoding, strict protocol/subscription chain validation in `blockchain/x/core/module/module.go`, and delete `blockchain/app/legacy_mobile.go` plus `blockchain/x/core/module/legacy_mobile.go`.
8. Delete `scripts/legacy_mobile_canon_check.mjs` and its `.gitignore` allowlist entry, then remove compatibility-only assertions and vectors from `blockchain/app/ante_canon_v139_parity_test.go`, `blockchain/app/ante_metasig_canon_completeness_test.go`, `blockchain/app/ante_metasig_test.go`, `blockchain/app/relay_messages_test.go`, `blockchain/x/core/module/block_community_test.go`, `blockchain/x/core/module/legacy_mobile_test.go`, `shared/testdata/canon_v139_vectors.json`, `tests/blockchain_helpers.py`, `tests/cases/test_blockchain_chain_rules.py`, `tests/cases/test_blockchain_envelope.py`, `tests/cases/test_blockchain_features.py`, `tests/cases/test_blockchain_pow.py`, `tests/cases/test_blockchain_social.py`, `tests/cases/test_blockchain_tiers.py`, and their category registrations in `tests/test_blockchain.py`. Delete `blockchain/x/core/module/legacy_mobile_test.go` when no permanent historical case remains.
9. Delete this file after its manifest has been applied and reviewed, then run the full blockchain-upgrade test and release process for the removal release.

## Keep permanently

- `docs/mobile/v1.39.0-mobile-migration-guide.md`.
- `docs/updates/update_v1.39.0.md`, because release notes must describe what users actually experienced.
- Historical `MsgFollowTopic`, `MsgUnfollowTopic`, `MsgBlockTopic`, and `MsgUnblockTopic` structs and field numbers in Go protobuf output and `shared/datatypes.py`, so old blocks remain decodable.
- Historical topic canonical builders in `shared/canon.py`, so pre-v1.39 signatures remain reproducible during replay and forensic work.
- The corrected `topic` field decoding and projections in `indexer/message_processor.py`; historical reindexing must still reproduce committed state.
- Optional protocol-0 `PostMetadata` reads in `indexer/chain_client.py`, metadata persistence in `indexer/database.py`, and their `message_processor.py` reconciliation paths. Posts created during the compatibility window retain chain metadata after teardown, while older protocol-0 posts legitimately have none.
- Historical reindex tests that prove old topic messages project correctly.
- `legacy_thread_read_only`: the error code, its registry entry, its frontend copy, `_classify_thread_read_only`, and `comments.reply_needs_parent_metadata`. Replies to a metadata-less pre-v1.39 root stay rejected for every client.
