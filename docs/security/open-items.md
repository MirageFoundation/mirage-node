# Security Open Items — Cross-Component Register

**As of:** 2026-08-16, at the `v1.36.0` tag on `dev`. Pinned to the tag rather than a commit hash, which went stale the moment the release was amended.

**No Critical or High is open in any component.** The last three — the blockchain
C-1, H-1 and H-2 — shipped in `v1.36.0` on 2026-08-16, which is also what made
that release consensus-breaking.
**Purpose:** one place to find every security item that is still open across components, so that an accepted risk or a deferred plan item cannot quietly become forgotten work. Every entry needs either a scheduled action or a recorded decision.

Component detail lives in the retests, which stay authoritative for their own findings:

- [blockchain](2026-08-07/blockchain-retest.md) — staged for `v1.34.0`
- [backend](2026-08-07/backend-retest.md) — shipped `v1.33.3`, plus the 2026-08-12 delta appendix
- [indexer](2026-08-07/indexer-retest.md) — shipped `v1.33.0`–`v1.33.2`, plus the 2026-08-12 delta appendix and the topic-attribution fix in `v1.34.0`
- [frontend](2026-08-09/frontend-retest.md) — plus the 2026-08-12 delta appendix
- [cross-component sweep 2026-08-13](2026-08-13/cross-component-review.md) — Critical/High only, all five components; shipped in `v1.35.0`
- [indexer full review 2026-08-14](2026-08-14/indexer-review.md) — all severities, `indexer/` only (2 High, 3 Medium, 4 Low, 1 Informational). **All dispositioned on 2026-08-14: nine fixed and shipped in `v1.36.0`, M-1 accepted as risk.** Still authoritative for the reasoning behind each
- [frontend full review 2026-08-14](2026-08-14/frontend-review.md) — all severities, `web/frontend/` only (1 High, 2 Medium, 2 Low, 1 Informational). **All dispositioned on 2026-08-14: everything fixed and shipped in `v1.36.0` except the CSP media-host breadth and the two `react-router` advisories, both accepted as risk.** **Authoritative for the frontend items below**, and it corrects two closure-map errors in the 2026-08-09 frontend retest
- [backend full review 2026-08-14](2026-08-14/backend-review.md) — all severities, `web/backend/` only (1 Critical, 3 High, 5 Medium, 2 Low). **All dispositioned: ten fixed and shipped in `v1.36.0`, M-5 accepted as risk on 2026-08-14, and the `EXPO_ACCESS_TOKEN` sub-threshold item accepted as risk on 2026-08-16. Nothing from this review is open.** **Authoritative for the backend items below**, and it supersedes the 2026-08-07 backend retest as the current statement of backend posture
- [blockchain full review 2026-08-14](2026-08-14/blockchain-review.md) — all severities, `blockchain/` only (1 Critical, 2 High, 5 Medium, 9 Low, 10 Informational). **All dispositioned on 2026-08-16: 25 fixed and shipped in `v1.36.0`, M-3 accepted as risk, I-7 and I-8 closed as not-a-defect. Nothing from this review is open.** **Authoritative for the blockchain items below**, and it supersedes the 2026-08-07 blockchain retest as the current statement of chain posture

---

## Critical / High — all closed

**Two Critical and eight High**, from four separate full reviews on 2026-08-14.
**All ten are now fixed and shipped in `v1.36.0`.** The rows are kept so the
history stays readable.

| ID | Component | Item | Status |
| :--- | :--- | :--- | :--- |
| **C-1 (bc)** | Blockchain | `authz.MsgExec` nesting bypasses the entire relay ante chain — envelope signature, nonce replay and PoW all skipped. The router classifies by top-level messages only, authz self-exec needs no grant, and every relay handler authorizes on an `envelope_pubkey` that nothing has verified. **One ordinary signed transaction to the public RPC port drains any account that has a username**, and the same shape forges posts, votes, follows and account deletions as any user. Also bypasses the delegation ban, and one `MsgGrant` proposal hands governance's own send privilege to an ordinary key permanently. | **Fixed, shipped in `v1.36.0`.** The router, the staking decorator and the governance-authority decorator now classify transitively over nested messages (depth-capped at 4) and reject nested relay messages outright; `x/authz` is unwired and its KV store deleted on upgrade. The regression test covers every relay prototype and was mutation-tested |
| **H-1 (bc)** | Blockchain | A storage fault *during* iteration is discarded at three independent layers — the patched iavl iterator never assigns `iter.err`, the cachekv merge iterator's `Error()` never consults its parent, and the fail-fast wrapper must therefore treat the resulting sentinel as "iteration finished". So `failFastIterator.Error()` **can never observe a real fault**, and a truncated iteration commits as a complete one: wrong deque entry evicted, list entries surviving a deleted count key (a tier-cap bypass), missed subscription expiries, missed nonce prunes, incomplete relay-credit reset. All AppHash divergence. | **Fixed, shipped in `v1.36.0`.** Both forks propagate the error, `PATCHES.md` records each deviation, and a mid-loop failure-injection test drives an injected fault through the real cachekv stack |
| **H-2 (bc)** | Blockchain | `iavl.Store.Set` logs and drops tree write errors while `Get`/`Has`/`Delete` all panic. The `types.KVStore` interface has no error return at that boundary, so the fail-fast wrapper has already reported success and nothing can observe the loss — one validator commits a block without the key while healthy peers commit with it. | **Fixed, shipped in `v1.36.0`.** `Set` panics for symmetry with the sibling methods, and the finalization guard converts it into a clean named halt |
| **H-1 (idx)** | Indexer | Governance event attributes are base64-decoded on a guess. 1,040 of the 9,000 four-digit proposal IDs (11.6%) decode to a string `int()` rejects, permanently wedging every indexer. Verified by executing the real decode. **No attacker needed — it arms itself as the proposal counter advances, starting at ID 1400.** | **Fixed, shipped in `v1.36.0`.** UAT was at proposal **108** on 2026-08-14, so roughly 1,290 proposals of runway remained |
| **H-2 (idx)** | Indexer | The indexer resolves vote weight by exact level lookup and only knows admin level `100`, but the chain accepts **any** level ≥ 100 and says so in its own error message. One governance `MsgSetLevel{level: 101}` plus one ordinary post by that account wedges every indexer permanently. | **Fixed, shipped in `v1.36.0`.** |
| **H-3 (fe)** | Frontend | "Sign in with recovery phrase instead" — the only in-app recovery for a forgotten vault password or a lost passkey — can never succeed. `handleFallbackLogin` nulls the cached vault key, then `setCredentials` calls `storeSeed(…, mode, null)`, which throws unconditionally for both protected modes. The rejection is dispatched as a `seedVaultStoreFailed` event that **nothing listens for**, so the user sees no error while every signature silently fails. | **Fixed, shipped in `v1.36.0`.** `storeSeedForSession()` falls back to `memory` when the protected mode has no cached key, and warns the user that the fallback will not survive a refresh; a `seedVaultStoreFailed` listener now surfaces any remaining write failure |

**C-1 (bc) was the only item on this page that took other people's money**, and it
is closed. It needed no privilege, no grant, no timing and no relay-operator
cooperation — one ordinary transaction. Every other Critical and High degraded or
wedged a service; that one transferred balances.

**H-1 (bc) and H-2 (bc) shipped alongside it, as intended.** Both were holes in
the `v1.34.0` fail-closed contract — one for iterator reads, one for writes — in
the two shapes that release's store wrapper did not reach. They undermined the
guarantee the whole release was built to establish, so they rode the same
coordinated upgrade.

**Cut across three of the backend findings and now fixed in `v1.36.0`:** the backend had no `statement_timeout`, no query deadline, and `connect_db()` documented its `timeout` and `busy_timeout_ms` arguments as ignored while ~30 call sites passed them. All three DSN paths now set `statement_timeout`, `lock_timeout` and `connect_timeout`, and the previously-ignored arguments are honoured. A connection pool is still absent.

**Measured 2026-08-14:** UAT (`val2`) and prod (`val1`) both report governance proposal **108** against a first corrupting ID of **1400**, so H-1 (idx) had roughly 1,290 proposals of runway. Both returned byte-identical responses, so they front the same chain rather than two independent counters.

### Closed in `v1.35.0`

The [2026-08-13 sweep](2026-08-13/cross-component-review.md) found 1 Critical and 5 High; four were fixed and two were accepted as non-issues by the operator. All shipped in `v1.35.0`.

| ID | Component | Item | Outcome |
| :--- | :--- | :--- | :--- |
| **C-1** | Indexer | Account self-delete permanently wedged the indexer on an earlier block | **Fixed** — `GetProfile` returns `codes.NotFound`; indexer skips and logs `profile_absent`; unknown message types no longer halt either. Two regression tests pin the status code. |
| **H-1** | Deploy | Fleet addresses in public git history | **Non-issue (accepted)** — addresses are public knowledge; keeping them out of the tree is the only requirement and it already holds |
| **H-2** | Deploy | Remote RPC `block_id.hash` reached `eval` as root during `--init` | **Fixed** — `eval` removed in favour of a validated four-key parser; hash also hex-checked at the source. Verified against injection payloads. |
| **H-3** | Deploy | `backup_restore.py` published `1317`/`9090`, which ufw cannot restrict | **Fixed** — single `CONTAINER_PORTS` constant matching `deploy.sh`. Live check: no host was ever in the exposed state. |
| **H-4** | Deploy | Backup archive mode `0644` in `/tmp` | **Non-issue (accepted)** — operator's own backups on single-tenant hosts; live check found no archive present |
| **H-5** | Backend | Invite-referral reward re-payable to the same pair | **Fixed** — gated on `is_new_user and code == 0`. **It had already fired in production:** one referee was paid twice (2026-04-15 and 2026-04-18), both claimed. |

---

## Fixed in `v1.36.0` — 2026-08-14 backend review

All Medium and Low findings except **M-5** shipped in `v1.36.0`, together with the
Critical and all three High, the cross-cutting timeout work, and all nine
sub-threshold observations. **M-5 is accepted as a risk and will not be raised
again** — see the accepted-decisions table. Detail and per-finding status in
[the review](2026-08-14/backend-review.md).

Each fix has a behavioural regression check in `tests/cases/test_backend_hardening.py`
(`--category backend_hardening`, walletless). The set was mutation-tested: every fix
was reverted in turn and the matching check confirmed to fail; all 18 mutations were
caught.

One sub-threshold item is fixed only partially, by choice: **`EXPO_ACCESS_TOKEN` is
empty on every fleet node** while push is enabled, so the backend logs an error at
startup rather than refusing to boot, which would have taken the fleet down on
upgrade. **Accepted as risk 2026-08-16** — the loud startup error is the end state,
and issuing the token is an operator action outside this repository. Nothing from
this review remains open.

| ID | Item | Why it matters | Note | Status |
| :--- | :--- | :--- | :--- | :--- |
| **M-1 (be)** | Push delivery ignores the blocks and deletions the in-app inbox enforces | `shared/push.py` contains no reference to any blocked list — zero matches on search. A blocked user puts attacker-authored text on the victim's lock screen by replying or writing `@victim`, repeatable at the throttle ceiling, while the victim sees nothing in-app to report. Deletion is not re-checked either: content is snapshotted at enqueue, and the mention path explicitly tolerates the post being gone — so post-abuse-then-delete leaves the text on the device and nothing recoverable anywhere else | The trending push path *does* filter blocks, which shows the intent; the event-driven paths were never given the same filter | **Fixed in `v1.36.0`.** |
| **M-2 (be)** | Mention fan-out is uncapped at enqueue, and the overflow destroys rather than delays | One 20,000-character subscriber post yields ~5,000 outbox rows against a single thread draining 50 per tick. Legitimate pushes queued behind it are marked terminal at 30 minutes **without ever being delivered**, and hourly cleanup deletes fewer rows than one post creates | The existing `MAX_MENTION_PUSHES = 10` is applied at delivery to one row's resolved owners, and rows are keyed per username, so it bounds nothing at the queue level. Fix is a cap at enqueue plus resolving usernames to existing owners first | **Fixed in `v1.36.0`.** |
| **M-3 (be)** | `/api/upload_media` parses the whole body before the per-kind cap | The comment says the probe runs before the body is materialized; the line above it reads `request.form`, which already consumed the stream and spooled to disk. Only the global cap applies during that parse, and it is sized for video — so an unauthenticated `kind=image` upload transfers up to 1516 MiB before the 413 | Bounded (hence Medium), but the edge allows 4 uploads per 10 s per IP at that size, each holding a sync worker, in a container shared with `miraged` and PostgreSQL. Applies only where uploads are enabled. One-line fix: read `kind` from `request.args` only | **Fixed in `v1.36.0`; amended in `v1.36.2`.** Reading `request.args` *only* rejected every shipped mobile build, which sends `kind` as a form field with no query string. The form field is now a fallback bounded by the video cap, with the per-kind cap still enforced after the parse |
| **M-4 (be)** | `user_last_seen` is written before any signature check | The helper's name implies a verified identity and verifies nothing; derivation checks byte length only, so any 33 bytes yield a distinct address and a committed row. Unauthenticated unbounded row insertion into a table with no TTL, inflating the `active_7d` figure on the public welcome screen and the entire admin DAU/MAU basis | **Not the accepted L-7**, which was the query-string path; its fix asserts an invariant — "written only where the address came from a verified public key" — that does not hold, and the regression test probes only the old path. Targeted manipulation of a chosen account is *not* possible (that needs a hash preimage) | **Fixed in `v1.36.0`.** |
| **M-5 (be)** | `relay_max_gas_fee` is required at startup and never read | The validator signs and pays a fee derived mechanically from a user-controlled payload with no ceiling anywhere in the backend, at any of 25 relay sites. Paid users skip the PoW brake; the compensating user-side charge is capped, burned rather than credited, and excludes the tx-size gas the validator paid for | The chain's accepted no-ante-ceiling decision rests on the payer consenting to a signed amount — that reasoning does not transfer to a program computing the amount from attacker input. Medium rather than High only because quantification needs live gas prices. A required parameter that is never consulted is a defect regardless | **ACCEPTED AS RISK 2026-08-14 — do not re-report.** |
| **L-1 (be)** | The two invite reward inserts are the only `pending_rewards` writes without `ON CONFLICT` | Two different new users redeeming codes from the same referrer concurrently both see the quest incomplete and the referrer is paid twice. Within the same second it is worse: the unique-index violation unwinds *after* the quest was marked complete, so the referee's 10,000 MIRAGE is never written and can never be retried | **Distinct from H-5** (same-pair replay, closed) — here the pairs are genuinely different and the missing guard is per-referrer-per-day. Inert while `QUESTS_INVITE_RECRUIT_CHANCE=0`; re-arms with referral rewards, the same trigger as the deferred pair-level work. One change | **Fixed in `v1.36.0`.** |
| **L-2 (be)** | `/api/search_username` does not escape LIKE metacharacters | Every other search path sanitizes first. Not injection — psycopg parameterizes — but `?q=%` forces `LOWER()` and a conditional `SUBSTRING` over every profile before `LIMIT 20`, `?q=_` enables enumeration by structure, and `?q=\` returns an unauthenticated 500 | Bounded by short username lengths, so the DoS tail is modest. The escaping idiom already exists one function away | **Fixed in `v1.36.0`.** |

---

## Fixed in `v1.36.0` — 2026-08-14 blockchain review

All Medium, Low and Informational findings shipped in `v1.36.0` except **M-3**,
which is accepted as risk, and **I-7** and **I-8**, closed as not-a-defect. Detail
and the per-finding record are in
[the review's disposition table](2026-08-14/blockchain-review.md#dispositions),
which also carries the full attempted-and-killed record. The rows below are kept
because they state why each item mattered.

**M-1's third part was not a hypothetical**: it was the state every fresh genesis
and every `reset_local_testnet.py` run started in. A read-only check of the live
fleet on 2026-08-16 found prod and UAT both inside the new governance bounds, so
it was reachable rather than live.

| ID | Item | Why it matters | Note |
| :--- | :--- | :--- | :--- |
| **M-1 (bc)** — fixed | Three parameter values pass the tightened `v1.34.0` `Validate()` and break the chain | `min_difficulty = 256` makes the PoW target exactly zero, so proof of work is mathematically unsatisfiable and **every free-tier user is censored while paid tiers, being PoW-exempt, notice nothing**. `relay_min_gas_price = 0` or `relay_max_gas_fee = 0` short-circuits the fee, and since paid tiers are PoW-exempt that fee is their *only* per-message cost — one proposal removes anti-spam for every paid user. `subscription_reserve_bps = 0` burns the whole period fee and escrows nothing, so a subscriber pays in full and is demoted to free on their first action | The reserve one is live for new chains, not just reachable by proposal: the genesis params **omit the field entirely**, so proto3 decodes 0, and `InitGenesis`'s zero-substitution sentinel checks five other fields and not this one. `TestGenesisParamsStillValidate` passes *because* zero is legal. Fix it through the sentinel and the genesis file, **not** through `Validate()` — the same replay constraint already documented for `MinBlockHashWindow` applies |
| **M-2 (bc)** — fixed | Unauthenticated `Simulate` runs Argon2id per message under an infinite gas meter | `Simulate` is registered on the gRPC *query* router, so it is reachable via `abci_query` on the public RPC port regardless of whether 1317/9090 are published. Neither relay decorator branches on the `simulate` flag. Because the nonce is never persisted in simulate, a set of valid envelopes is precomputed **once** and re-simulated indefinitely: ~100 messages is ~165 ms CPU and ~400 MB of allocation churn per free HTTP request | The CheckTx equivalent is properly defended — the branch aborts on first failure so the attacker pays ~1024 evaluations per one of the node's. Simulate defeats that defence by making the work reusable. Fix is to skip PoW when `simulate` is true, plus a non-zero `query-gas-limit` |
| **M-3 (bc)** — accepted as risk | `MsgSendTokens` ignores the blocked-module-account list, and the core module account is missing from it | The list is enforced only inside bank's own msg server; the chain's primary transfer message calls the keeper's `SendCoins` and never consults it, so all six blocked module accounts are reachable targets. Separately `coremoduletypes.ModuleName` — the account holding Minter, Burner *and* Staking — is absent from the list, so even a plain bank `MsgSend` into it is accepted | Irrecoverable fund loss plus staking/distribution accounting drift with no runtime detector, since the crisis module is not wired. The supply invariant cannot see it (a transfer preserves supply == sum of balances), and excess balance in the core account **masks** the `CORE_MODULE_SHORT_BURN` guard, which is the detector for reserve liabilities exceeding their backing |
| **M-4 (bc)** — fixed | `MsgSetAutoRenewal` is a free, PoW-exempt, unlimited-throughput channel for free-tier users | The ante exempts it on the premise, stated in its own comment, that it "must pay with reserve" — but `checkReserveOrDowngrade` returns nil unconditionally at level 0, and the handler cannot charge either: a level-0 user may only set the flag to the value it already has, forcing the no-op branch, and `deductRelayGasFee` returns immediately below level 1. Zero PoW, zero tokens, zero state change, full relay ante paid by the node | Breaks the invariant that every free-tier relay message is paid for in Argon2 work, and because `RecordPoWMessage` sits inside the PoW branches the abuse never raises difficulty. Medium not High because block space still costs the relay operator their outer fee — free quota, not free blockspace |
| **M-5 (bc)** — fixed | `EndBlock` scans every account balance every block, over a set any user can grow permanently | `AssertSupplyInvariant` walks the whole bank balances index each block. `MsgSendTokens` sends as little as 1 umirage to any valid bech32 address with no existence requirement, x/bank deletes only zero balances, and nothing sweeps dust for addresses without a profile — so each transfer adds one permanent entry every future block must walk. Lifecycle work is charged to no transaction, so the cost asymmetry is unbounded | The O(accounts) cost is a deliberate documented trade from the earlier M-2. What is documented nowhere is that the scanned set is **user-growable and irreversible**. Fix: periodic full scan behind the every-block O(1) delta check, or a resumable cursor with a per-block budget as `CleanupOldCounters` already does |

Two Lows worth naming because both restored a guarantee the source already
claimed, and both are now fixed: **L-1 (bc)**, where the keeper readers with no
error channel called `os.Exit(1)` with no exec-mode gate, so a transient store
fault while answering a public query or a CheckTx killed the validator on a path
where nothing is committed and no divergence is possible; and **L-3 (bc)**, where
the `v1.35.0` rewrite of `verify_upgrade.py` deleted the parameter bounds checks
that `params.go` still named as their enforcing surface — so the
`MinBlockHashWindow` floor, which deliberately cannot live in `Validate()`, had no
runtime enforcement at all. L-1 is the change that put the new chain failure
policy into effect: halt during finalization, return everywhere else.

**Also closed alongside the numbered findings**, from the review's "noted, not
findings" paragraph: the `batch.go` mutex panic that masked disk-full errors
during commit, and the `CONSENSUS_FATAL:PRUNE_HOLE` guard's missing hook into
`recover.sh`'s forensic-snapshot chokepoint — the one that made an operator's
first move after a halt the wipe `AGENTS.md` forbids. Commit-info pruning
synchronicity and the snapshot-restore allocation shape were noted and left
alone.

---

## Fixed in `v1.36.0` — 2026-08-14 indexer review

Every finding except M-1 was fixed on the same day the review landed; M-1 was accepted as risk and moved to the accepted-decisions table. Detail in [the review](2026-08-14/indexer-review.md). **All of it shipped in `v1.36.0`**, including the correction to M-3, whose first fix was undone by the next indexer restart.

| ID | Item | Fix |
| :--- | :--- | :--- |
| **H-1 (idx)** | Governance event attributes base64-decoded on a guess; 11.6% of four-digit proposal IDs wedged every indexer | Guess removed. New `attr_text` decodes only genuine `bytes`, and **all four** readers of the same `result_obj` now share it — `decode_events`, `_process_subscription_events`, `_collect_touched_addresses` and `_synthesize_raw_log`, the last of which still carried a comment asserting the attributes were encoded. An unparseable proposal id now raises a named error instead of a bare `int()` traceback, and stays fatal so the checkpoint cannot pass an unprojected governance action |
| **H-2 (idx)** | Only admin level `100` exactly was recognised, but the chain accepts any level ≥ 100 | `level_to_tier_index` mirrors the chain's `LevelToTierIndex` as a range check, and the level-keyed `vote_weights` dict is gone in favour of a tier-indexed lookup — which also removes the `KeyError` that would have fired at param load if governance ever shipped fewer than three tiers |
| **M-3 (idx)** | Deleting a post never retracted the topic standing it granted | `delete_post` now recomputes the affected `(owner, topic)` rows from canonical via a shared `_recompute_topic_stats` helper, and the canonical vote SQL excludes an author's own vote on their own deleted post. Repair migration `v1_36_0_repair_deleted_post_standing` fixes rows written before the fix. **Scope decision below.** **This fix was incomplete on first attempt — see the row below** |
| **M-3 (idx), second defect** | The M-3 repair was undone by the next indexer restart | A vote backfill in `_init_db()`, commented "one-time" but run on every startup, held a third copy of the stats definition without the deleted-self-vote exclusion. The repair *deletes* those rows, so its `ON CONFLICT DO NOTHING` suppressed nothing and it re-inserted them at pre-fix values, byte for byte. Found by the whole-database consistency assertion during the `v1.36.0` release run, not by the M-3 tests, which only covered `delete_post` and the canonical SQL. Backfill deleted rather than patched, so one definition remains. New behavioural test `indexer_hardening.startup_does_not_resurrect_standing` runs the real `_init_db` twice against a scratch schema; mutation-tested. The consistency assertion itself was also wrong — it omitted the same exclusion and so asserted the pre-M-3 definition |
| **M-2 (idx)** | An empty profile inventory would soft-delete every user and destroy the blocked-list history | Two guards in `_soft_delete_absent_owners`: an empty chain inventory against a populated index is refused outright, and any sync that would soft-delete more than `PROFILE_SYNC_MAX_ABSENT_FRACTION` (10%) of known profiles aborts startup |
| **L-1 (idx)** | A swallowed exception inside the block transaction could not do what its comment claimed | Legacy backfill wrapped in a `SAVEPOINT`, so "best-effort" is now true rather than aspirational |
| **L-2 (idx)** | Governance silently dropped message types the indexer can handle | `MsgAnnotate` added to `TYPE_URL_TO_PROTO`, and an untracked `/mirage.core.v1.` message in a proposal is now fatal rather than filtered. Cosmos messages are still deliberately ignored, matching `_process_tx` |
| **L-3 (idx)** | Per-block `chain_id` written to the checkpoint without comparison | Latched from the first block and compared on every subsequent one, so a mid-run network switch fails loudly instead of overwriting the stored identity. No extra network call |
| **L-4 (idx)** | Profile gRPC reads inside the block transaction | **Partially fixed**, remainder accepted as risk. Per-block memo collapses repeat reads of the same address, removing the packing amplification. gRPC still happens inside the transaction |
| **I-1 (idx)** | `unblock_topics_matching` treated a stored `%` as a wildcard | Escaped in SQL with an explicit `ESCAPE '#'` (the pattern is a column, not a parameter, so the sibling's Python-side escaping did not transfer). Verified against a real PostgreSQL that `*` still globs |
| Minor | Operational items | Ancestor comment-count walk bounded by `MAX_ANCESTOR_WALK_DEPTH = 100`; `--height` on an empty DB now records the `[1, start-1]` history gap; signal handler exits `128+signum` instead of `0`; `get_balances_batch` gained an overall `BALANCE_BATCH_DEADLINE` (30s) so a block touching many addresses has a budget; `INDEXER_ENABLED=false` now skips cleanly in the supervisor instead of burning the restart budget on a crash-loop. The `v1_33_0` marker item was accepted as risk |

**Two scope notes worth carrying forward:**

- **M-3 retracts standing from the author only.** The chosen option was "deleted posts grant no standing", which is ambiguous between "the author loses what their deleted post granted" and "everyone who voted on it loses it too". The second reading creates a griefing lever — an author could strip a voter's topic standing by deleting their own popular content — so only the author's own votes on their own deleted posts are excluded. Other voters keep what they earned. Verified against PostgreSQL: attacker standing `(3,3,3,3)` → gone; honest voter's `(1,1,1)` → kept.
- **L-4 is a mitigation, not the full fix**, and the remainder is now an accepted risk rather than open work. Fully removing gRPC from the block transaction needs prefetching, which needs knowing the addresses before the transaction opens, which means duplicating the owner-derivation precedence across five handlers — the exact fragile logic the 2026-08-07 I-1 fix consolidated.

---

## Fixed in `v1.36.0` — 2026-08-14 frontend review

Every finding was dispositioned on the day the review landed. All were fixed except
the CSP media-host breadth inside M-1 and the two `react-router` advisories, both of
which **are accepted as risk and will not be raised again** — see the
accepted-decisions table. Detail in [the review](2026-08-14/frontend-review.md).

Regression coverage is `web/frontend/tests/unit/frontendHardening.test.js` (18 tests)
plus, for the two-sided L-2 fix, `tests/cases/test_backend_hardening.py` and the
`account` category. The set was mutation-tested — `npm run check:mutation` reverts
each frontend fix and requires its test to fail, and it runs in CI, so a future
revert cannot pass silently.

| ID | Item | Fix |
| :--- | :--- | :--- |
| **M-1 (fe)** | CSP had been Report-Only since the day it shipped, with no `report-uri`, `report-to` or `Reporting-Endpoints` anywhere in `deploy/`, so the "enforce after UAT soak" exit criterion had no evidence to conclude on | **Fixed in `v1.36.0`** by ending the soak instead of building a collector: the header is now `Content-Security-Policy`, enforcing, and `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy` were added alongside. `check:headers` asserts all of it against the Caddyfile in CI. **The `img-src`/`media-src https:` breadth is accepted as risk** — see the accepted-decisions table. **This row corrects the 2026-08-09 retest, which recorded M-1 as "Closed (report-only)"**; report-only was a milestone, not a closure |
| **M-2 (fe)** | `onSessionReset` had zero subscribers; sign-out left the feed memory cache, the API response cache and `sessionStorage` populated, so on a shared device account B could be served account A's personalized feed | **Fixed in `v1.36.0`.** Six subscribers wired: feed memory cache, API response cache and inflight map, seen-posts buffer, `ProfileCache` pending requests, `UsernameCache`, and `App.state.posts`. Sign-out now calls `resetClientSession({ hardReset: true })`, which routes through the `hardResetAllStorage()` that already existed and was never called |
| **M-7 (fe, from 2026-08-07)** | The decrypted phrase is duplicated into React state and reveal requires no step-up | **Fixed in `v1.36.0`.** `requireFreshUnlock(120s)` — written in an earlier round and never called from anywhere — is now called before the phrase is revealed or copied, in all four themes; a stale unlock prompts for the password or re-runs the passkey ceremony. **See the bookkeeping correction below** |
| **L-1 (fe)** | Cross-tab sign-out locked the sibling tab's vault but did not drain its queue or bump its generation | **Fixed in `v1.36.0`.** The watcher calls `resetClientSession({ reason: 'cross_tab_sign_out', clearVault: true, lockVault: true })`, keeping the encrypted blob so the tab can still offer the unlock screen |
| **L-2 (fe)** | Signed request bodies were narrower than the fields the backend acts on | **Fixed in `v1.36.0` for the two fields with money attached.** `invite_code` and `referrer_username` now carry an `attribution_signature` over `canon_attribution`, bound to the envelope nonce, pinned byte-for-byte between `shared/canon.py` and `canonicalEncoding.js` by shared golden vectors, and verified against the received value before the handler's own referrer-blanking. The remaining fields named in the review (`seen_posts.posts`, `resolve_report.id`, `admin_rewards_suspend.target`, the admin stats window) were deliberately left unsigned — they carry no payout. **Re-rate the remainder immediately if a third-party relay is ever introduced** |
| **I-1 (fe)** | The lint gate covered 7 of 322 source files; no test asserted any response header; `check:repro` was not in CI; `npm audit` gated at `high` | **Fixed in `v1.36.0`.** `npm run lint` covers the whole tree with errors fatal and warnings permitted, to be ratcheted down over time; the original zero-warning gate survives as `lint:strict` and both run in CI. `check:headers`, `check:repro` and `check:audit` (moderate, allowlisted by GHSA ID) are all wired in, and the Caddy template is in the workflow's path filter. The pre-existing errors this surfaced were fixed rather than suppressed |

**Bookkeeping correction, now applied.** The 2026-08-07 frontend M-7 ("the decrypted phrase is duplicated in App state and reveal requires no step-up") was **never closed**: the 2026-08-09 closure map listed "Sign-out incomplete" under M-7 and "Incomplete session reset" under M-5, two rows describing session reset, with the real M-7 absent. It has its own row above rather than being folded into M-2, so the record cannot lose it a second time. Both this and the M-1 mislabelling are annotated in the [2026-08-09 retest](2026-08-09/frontend-retest.md) itself.

---

## Deferred from the 2026-08-13 sweep

| Item | Why deferred | Trigger |
| :--- | :--- | :--- |
| Default-deny `DOCKER-USER` firewall rule | The structural version of the H-3 fix: it makes *any* stray `docker run -p` non-public instead of relying on port lists staying correct. Changes packet filtering on live validators, so it needs its own change window rather than riding a source fix. | Next infrastructure window, or the next time a container's port set changes |
| Pair-level idempotency for invite rewards + missing `QUESTS_ENABLED` check | The `is_new_user` gate already makes the H-5 replay unreachable, so this is thoroughness rather than closure. `pending_rewards` records no `(referrer, referee)` pair, which is why referrer-side replay could not be distinguished from legitimate multi-recruit during the investigation. | Before referral rewards are switched back on, or the next time invite accounting needs auditing |
| End-to-end reindex test over a self-delete block | C-1 is covered by chain-side unit tests, but the actual wedge was an indexer projection failure. A replay test needs local docker and the raised PoW limit. | Next local-testnet test pass |
| Reconciling the ~20k MIRAGE over-issued in April | Recorded so the number is not lost; reversing it is a product decision, not a security fix. | Operator decision |

---

## Calendar-bound

**None.** The unsigned reward-claim grace, which was the only dated item, was closed early in `v1.34.0` rather than left to expire on 2026-10-05. `/api/rewards/claim` now verifies a proof for the claimed owner or returns 401; the `LEGACY_UNSIGNED_UNTIL` setting, its handler branch, and the env key are gone, and `test_reward_claim_authz` asserts the rejection unconditionally with a source guard against reintroducing the window. Users on a client that signs under the older scheme cannot claim until they update — that was the accepted cost of ending it 54 days early.

---

## Accepted decisions — no code change intended

| Component | Item | Why it stands |
| :--- | :--- | :--- |
| Blockchain L-6 | `ProcessProposal` does minimal validation | Signature-before-PoW ordering and fee-payer consent already bound the exposure. Revisit only on evidence of proposer-driven DoS. |
| Blockchain I-3 | Genesis `raw_state` is trusted input | Params still validate before any runtime write, now against the tighter `v1.34.0` bounds. |
| Blockchain I-4 | Indexer edit/delete authorization | Documented moderation boundary, not a chain authorization gap. |
| Blockchain I-6 | No ante fee ceiling | Deliberate: the payer signs the exact amount, and a ceiling made the longest posts unpublishable when it was tried. |
| Blockchain I-7 | Prepaid reserve remains on account delete | Protocol escrow. Changing it is a product policy decision. |
| Blockchain M-3 (2026-08-14) | `MsgSendTokens` ignores the blocked-module-account list, and the core module account is missing from it | **Accepted as risk 2026-08-16; do not re-report.** The list is enforced only inside bank's own msg server, so the chain's primary transfer message never consults it and all six blocked module accounts are reachable targets; `coremoduletypes.ModuleName` is absent from the list entirely. Accepted with the impact understood: reaching it requires a user to deliberately type a module account address as a transfer destination, which is self-inflicted fund loss and harms nobody else. The masking concern it raised is separately answered — `AssertModuleSolvencyInvariant` now asserts at runtime that the core module balance covers every recorded reserve, so excess balance in that account no longer hides a shortfall. |
| Indexer L-4 residue (2026-08-14) | Profile gRPC reads remain inside the block transaction | **Accepted as risk 2026-08-14; do not re-report.** The per-block memo shipped and removes the amplification (a block packed with transactions from one account now costs one read, not one per transaction). The residual is a single up-to-3s call holding row locks. Eliminating it needs prefetching, which needs the addresses before the transaction opens, which means duplicating the owner-derivation precedence across five handlers — the logic the 2026-08-07 I-1 fix deliberately consolidated into one chokepoint. Accepted rather than reintroduce a closed finding. |
| Indexer minor (2026-08-14) | `v1_33_0`'s completion marker is written outside its own transaction | **Accepted as risk 2026-08-14; do not re-report.** A crash between the rebuild and the marker re-runs the rebuild; it is idempotent, so correctness is unaffected. Effectively unfixable: applied migration files are checksum-pinned and editing one is a hard startup failure on every existing deployment. `v1_34_0` onward already use the atomic `run_db_migration()`, so the pattern is fixed going forward. |
| Indexer M-1 (2026-08-14) | Historical blocks are projected against present-day chain state | **Accepted as risk 2026-08-14; do not re-report.** Replay reads the acting account's *current* level, so a rebuild after an admin is demoted un-deletes the posts that admin moderated, a delete written today against another user's post takes effect on a later reindex if the sender ever reaches level ≥ 100, and vote weights are not reproducible between a live index and a rebuild. Accepted with the impact understood: the only correct fix persists the acting level alongside the projection, which needs a schema column, and the operator judged the cost above the risk. The two convergent variants (profile-list refresh and chain params both read at HEAD during replay) are covered by the same acceptance. |
| Backend M-5 (2026-08-14) | No backend ceiling on validator-funded relay fees | **Accepted as risk 2026-08-14; do not re-report.** The validator signs and pays a fee derived from a user-controlled payload with no ceiling at any of 25 relay sites, and `relay_max_gas_fee` is required at startup but never read. Accepted with the impact understood: the chain's own no-ante-ceiling decision was taken for the same reason a ceiling was rejected here — a cap large enough not to make the longest posts unpublishable is too large to bound the spend usefully. Revisit only on observed fee drain. |
| Backend push auth (2026-08-14) | `EXPO_ACCESS_TOKEN` is empty fleet-wide, so pushes are sent unauthenticated | **Accepted as risk 2026-08-16; do not re-report.** `_expo_headers` omits `Authorization` entirely when the token is empty, so anyone holding a copy of the `push_tokens` table can send pushes to users. Making it fatal at import — the treatment every other required setting gets — would take the fleet offline on upgrade rather than fix anything, so the backend logs an error at startup instead and that is the accepted end state. Closing it needs a token issued *and* enhanced security enabled in the Expo dashboard, which is an operator action outside this repository. Revisit if a token is ever issued. |
| Backend H-2 residue (2026-08-14) | Admin stats proofs are not scoped per destination | **Accepted as risk 2026-08-14; do not re-report.** The exploitable half is fixed: destinations come from an operator-configured https roster instead of unauthenticated P2P monikers, so an attacker can no longer nominate a recipient. What remains is that one proof is still replayable across the roster for its 5-minute window, because the proof format is shared with the client and scoping it per host is a protocol change. Every roster member is a host the operator already trusts with admin stats. |
| Indexer M-1 (2026-08-07) | Pruned-history gaps continue instead of failing | Failing startup hard would leave an offline-too-long node with no index at all, and would be worked around by wiping — losing the blocked-list history the finding protects. Guarded by `history_gaps`, `history_complete=false`, and the `unverified_pruned_gap` continuity marker. |
| Indexer I-1 | Owner derivation from unsigned content | Accepted architecture with the envelope-first precedence fix. Revisit only if node-relayed messages stop needing it. |
| Indexer L-4 | Skipped content derivations are not durably recorded | Only cosmetic fields can be lost. Trigger: the first time a missing thumbnail or mention needs explaining after the fact. |
| Indexer I-4 | Supervisor restart budget is a rate, not a lifetime cap | A genuinely fatal startup error crash-loops fast enough to trip the hourly cap and exit loudly. Trigger: an observed sustained flap, or the arrival of an alerting channel. |
| Frontend M-1 residue (2026-08-14) | CSP `img-src`/`media-src` allow any HTTPS host | **Accepted as risk 2026-08-14; do not re-report.** The enforcing-mode flip shipped; what remains is that an enforced policy still permits an image or media request to any HTTPS host, which would allow beacon exfiltration of the seed. Reaching it requires script already running on the origin — realistically a supply-chain compromise of the bundle, which `script-src 'self'` would not stop either — and no post content can get there. Tightening to the `mediaPolicy` allowlist would break inline media from arbitrary hosts, which is accepted behaviour under Frontend L-4. |
| Frontend dependencies (2026-08-14) | `react-router` 6.30.4 open-redirect and SSR constructor-injection advisories | **Accepted as risk 2026-08-14; do not re-report.** Neither is reachable: the app is client-rendered with `BrowserRouter` and has no hydration path, and router targets are not built from unconstrained user input. The fix is a breaking major bump to 7.x. Recorded by GHSA ID in `web/frontend/scripts/check_audit.mjs`, so a *new* moderate-or-higher advisory still fails CI — the acceptance is three named exceptions, not a raised threshold. |
| Frontend L-1 | Photon/wsrv thumbnail proxies | Keep the viewer's IP off origin hosts and apply upstream abuse filtering that a direct fetch would not. |
| Frontend L-4 | Click-to-load media gate removed | Inline media on unknown hosts now loads without consent, so a post author can learn a passing reader's IP. Accepted for reading experience; recorded separately because the proxy rationale does not cover a direct inline fetch. |
| Dependencies | `GO-2026-5932` (OpenPGP), `GO-2026-4479` (Pion DTLS) | No upstream fix exists. Reached only through the SDK keyring CLI and CometBFT's optional libp2p transport; production uses the `test` keyring backend and `[p2p.libp2p] enabled=false`. Revisit immediately if a deployment template enables libp2p. |
| Deploy H-1 (2026-08-13) | Validator addresses present in public git history | Addresses are public knowledge — a validator must be reachable to peer. The requirement is only that they stay out of the source tree, which holds at the tip. No rotation, no history rewrite. |
| Deploy H-4 (2026-08-13) | Backup archive left mode `0644` in `/tmp` | Operator's own backups, on single-tenant hosts with key-only root SSH. Accepted as operator risk. One-line fix recorded in the review if ever revisited. |
| Indexer (2026-08-13) | Unknown message types are skipped, not fatal | Halting on an unknown type takes the whole platform down *and* makes the block permanently unprojectable, for what is really a deploy-skew mistake. A skipped message means an incomplete index for that height, resolved by upgrading and replaying; the skip is logged at error level with type, height and tx hash. |

---

## Deferred work with triggers

### Highest value first

**I-1 — separate public query load from validating processes (ops project).** Still the single highest-value operational prevention, and still unverified because fleet hosts were not contacted. Scope: move indexer, backend, and public query load off validating processes, or document equivalent RPC, cgroup, and resource isolation. Trigger: the next infrastructure or capacity window, or any new divergence investigation. Acceptance: a read-only fleet inventory showing validator processes isolated from public query workloads, followed by 30 days with no load-correlated divergence. Never change production without separate explicit approval.

**Indexer — a safe non-empty `--height` replay/rebuild tool.** The most valuable of the deferred indexer tooling, because divergence recovery currently requires a trusted `pg_dump` whose checkpoint happens to match the recovered chain. Trigger: the next divergence, or the next time an operator needs to rebuild a height range.

### The rest

| Component | Item | Trigger | Acceptance |
| :--- | :--- | :--- | :--- |
| Blockchain I-2 | `upgrades.go` decomposition and execution tests for already-run handlers | **Trigger partly fired:** handler 46 landed with `v1.35.0`. The file is 2,400 lines, still under the 2,500-line trigger, and the next migration-framework change has not happened. Re-decide at handler 47 rather than letting a fired trigger sit | Registrar-only top-level file, exhaustive registration still passing, seeded pre-upgrade state reaching exact post-upgrade invariants |
| Blockchain I-5 | Historical bridge-burn forensics | A user loss report, a compliance request, or a scheduled historical audit | A documented block-range scan proving no unmatched burns, or enumerating every unmatched amount and transaction. No production mutation. |
| Backend I-3 | Oversized route modules | The next feature that must substantially touch one of them | Only the quest-assignment extraction was ever in scope |
| Indexer M-4 | Historical difficulty and supply backfill | Not planned — the source data no longer exists on pruned nodes | — |
| Indexer | Remote media enrichment service; automatic indexer wipe/rollback after divergence | Operational need | — |

---

## Maintaining this file

Add an entry when a review closes with an accepted or deferred item, and remove it when the trigger fires and the work lands. An item that is fixed belongs in its component retest, not here. Unfixed Critical/High items go in the first section instead, and are removed only once a retest records them as closed — never by downgrading them into an accepted decision. If an entry sits with a fired trigger and no action, that is the signal to escalate rather than to soften the wording.
