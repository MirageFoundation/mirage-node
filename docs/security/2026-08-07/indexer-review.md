# Indexer Security and Correctness Review — 2026-08-07

**Scope:** `indexer/` — all 18 tracked Python files (7,092 lines), including block ingestion, WebSocket catch-up, protobuf decoding, all 26 message handlers, PostgreSQL schema and writes, chain queries, parameter caching, media enrichment, and all 10 indexer migrations. Directly relevant backend health checks, recovery behavior, chain validation, backup tooling, and indexer tests were reviewed at the trust boundary.
**Out of scope:** `web/frontend/`, backend route/authentication internals, blockchain consensus internals already covered by [`2026-08-06/blockchain-review.md`](../2026-08-06/blockchain-review.md), production servers, and the correctness of external media providers. Local `127.0.0.1` RPC was used only to verify response encoding.
**Baseline:** `dev` at `d9dbf87a5c0632c5a95ce0e369bbc559fe3c4185` (`v1.32.4` + review commit). Working tree clean under `indexer/`. There is no `indexer/` delta between `public/prod` and this baseline; the last indexer change in history is part of the v1.31.0 remediation commit.
**Previous review:** No prior dedicated indexer review. Backend finding [`2026-08-05 M-8`](../2026-08-05/backend-review.md#M-8-the-backend-cannot-detect-wrong-data-in-the-indexer-db-and-the-indexer-enforces-authorization-the-chain-deliberately-does-not) identified the indexer trust boundary, non-atomic writes, silent handler failures, and lookback truncation. Its retest marked drift tests Partially Fixed and the authorization boundary Accepted Risk. This review audits the full implementation rather than only that boundary.

> **Retest:** [`2026-08-07/indexer-retest.md`](indexer-retest.md) is
> authoritative for present-day status (v1.33.0 / v1.33.2). This review is
> preserved as written at its baseline.

> **Relationship to backend M-8.** The accepted architecture is that edit/delete
> visibility is indexer-enforced. That acceptance does not cover implementation
> defects that silently apply failed transactions, lose passed governance actions,
> retain state from a diverged chain, or advance the checkpoint past failed writes.

---

## Executive Summary

The indexer is not a disposable cache. The backend serves its PostgreSQL rows as chain truth; admin delete authority is read from indexed profile levels; and blocked-list history intentionally exceeds what the chain retains. The code and `docs/modules/INDEXER.md` nevertheless assume block replay is idempotent and the database can be rebuilt from the chain. Both assumptions are false at this baseline.

**Five High findings define the review:**

1. **A block's writes and checkpoint are not atomic, many handlers swallow failures, and replay mutates cumulative rows again.** A crash or transient write error can create permanent partial state, while `--height` can actively inflate derived counters. See **H-1**.
2. **The indexer never verifies chain identity or block-hash continuity.** Recovery deliberately preserves PostgreSQL, so rows indexed from a diverged pre-recovery chain survive and are served after the node rejoins the canonical chain. See **H-2**.
3. **Missing `txs_results` entries are treated as successful transactions.** The indexer processes a transaction whenever its result entry has not appeared yet, even though the transaction may later report a non-zero DeliverTx code. See **H-3**.
4. **Passed-governance resolution has a dead cache and an undeclared REST dependency.** The proposal cache uses a protobuf that has no `messages`/`msgs` field, then falls back to REST despite the indexer's gRPC-only policy; errors are non-fatal and the block checkpoint advances. See **H-4**.
5. **User-controlled media causes server-side requests on the validator host.** Redirects are not revalidated, direct media probes bypass the public-IP check, response size is not bounded before download, and the advertised 10-second probe timeout waits for running workers anyway. See **H-5**.

No direct secret-key extraction, SQL injection, unsafe deserialization, shell injection, or arbitrary code execution was found. SQL values are parameterized; dynamic SQL identifiers are restricted to internal constants; subprocess invocation uses an argv list; and no `eval`, `pickle`, `yaml.load`, or `shell=True` path exists in the indexer.

**Ship posture:** **H-3, H-4, and H-5 should be fixed before treating the indexer as release-ready.** H-3 violates the core “failed transactions are skipped” invariant, H-4 loses governance actions whenever its undeclared REST dependency is unavailable or resolution otherwise fails, and H-5 is public-input SSRF/denial-of-service on a validator host. H-1 and H-2 require a larger integrity/recovery change and should be the next indexer hardening milestone, not indefinite backlog.

---

## Findings

### H-1: Block Writes and the Height Checkpoint Are Non-Atomic; Failure and Replay Corrupt Derived State (High)

**Location:** `indexer/database.py` lines 31–33; `indexer/main.py` lines 395–405, 561–564, and 597–612; broad handler catches in `indexer/message_processor.py` (for example lines 997–999, 1074–1136, and 1273–1491); cumulative writes at `database.py:1129–1135`, `1524–1528`, and `1576–1578`.

Every database method opens a new autocommit connection:

```31:33:indexer/database.py
    def _connect(self) -> psycopg.Connection:
        """Create a new PostgreSQL connection with autocommit enabled."""
        return psycopg.connect(self.database_url, autocommit=True)
```

A block executes many independent commits, then advances `meta.last_height` in another independent commit. Most profile/list/award/annotation handlers catch all exceptions, log, and return, so `_process_block` reports success and the checkpoint advances past the dropped message. Vote and post secondary writes also log-and-continue.

Replay is not idempotent. The `user_topic_stats.post_count` path checks `not existing`, but `update_topic_content_stats` has no such guard and increments on every root-post replay. `update_user_topic_stats` adds `direction` to `net_votes` even when `is_new_vote` is false. Preferences apply a rolling decay, so a crash before the final vote row can apply the same signal twice. The public `--height` option replays directly into live tables without rollback or deduplication.

**Impact:** Permanent partial blocks; lost profile/list/moderation updates; inflated topic and voting statistics; different feeds on nodes that restart at different instruction boundaries; stale admin levels; and no reliable meaning for “last processed height.” A transient operation-specific error can be permanently hidden if the connection is healthy again by the checkpoint write.

**Remediation:** Make canonical block projection and its checkpoint one PostgreSQL transaction. Pass one connection/cursor through the processor instead of opening a connection per method; fail the entire block on every required write; commit the block hash and height only after all required writes succeed. Keep media/network enrichment outside that transaction and explicitly classify it as recomputable. Add crash injection after each write stage and assert rollback + exact replay equality. Until that lands, remove or hard-disable `--height` against a non-empty database.

---

### H-2: No Chain-ID or Block-Hash Reconciliation After Divergence Recovery (High)

**Location:** `indexer/main.py` lines 158, 492–595, 597–612, and 856–876; `indexer/database.py` lines 684–707 and 2296–2325; `scripts/recover.sh` lines 70–78.

Startup trusts only an integer `last_height`. It does not persist or verify chain ID, genesis identity, the checkpoint block hash, or a recent overlap against RPC. WebSocket events at heights less than or equal to the stored height are ignored.

Recovery explicitly preserves the indexer database:

```70:78:scripts/recover.sh
# Recovery only replaces chain data under $NODE_HOME/data:
#
#   application.db blockstore.db cs.wal evidence.db snapshots state.db tx_index.db
#
# It never copies or modifies:
#   - PostgreSQL data (mirage_backend / mirage_indexer);
```

`_sync_recent_blocks` then overwrites recent hash rows from the recovered chain without comparing them to the old values. It repairs neither posts/votes derived from mismatched blocks nor list history.

**Impact:** After an AppHash divergence, peer-pull, state-sync, wrong-network configuration, or chain reset, the backend can continue serving rows from blocks that are not on the recovered chain. If the recovered head is below `last_height`, the indexer ignores canonical blocks until the chain surpasses the stale checkpoint. The existing recent-block table can erase the evidence that would have detected the mismatch.

**Remediation:** Store chain ID and checkpoint block hash in the existing `meta` table. Before profile sync or recent-block upsert, compare chain ID plus a bounded overlap of stored `(height, hash)` rows against RPC. On any mismatch, fail startup with a forensic message; do not overwrite the evidence. Recovery should restore a PostgreSQL dump whose checkpoint is known to be canonical or run an explicit, tested rebuild/rollback procedure. Do not automatically wipe indexer data.

---

### H-3: A Missing Transaction Result Is Treated as DeliverTx Success (High)

**Location:** `indexer/main.py` lines 255–338.

The code loads `txs_results`, but checks the result code only when `idx < len(txs_results)`. If the results endpoint temporarily returns fewer entries than the block's transaction list, processing falls through to the successful-transaction path:

```273:301:indexer/main.py
                    if idx < len(txs_results):
                        code = int(txs_results[idx].get("code", 0))
                        if code != 0:
                            ...
                            continue

                    # Successful tx: record once in tx_index using the first core message type.
```

The test infrastructure itself documents that `block_results` may lag block data (`tests/blockchain_helpers.py:721–723`) and retries until the result appears. The indexer does not. Only `send_tokens`/`multi` later fail on a missing result because they require a raw log; every other core message proceeds to its handler.

**Impact:** A transaction that ultimately has a non-zero DeliverTx code can be indexed as successful. This is especially dangerous for handlers that assume chain authorization, such as `MsgSetLevel`, subscriptions, or governance-shaped messages. Invalid content can appear, profile levels can be changed in PostgreSQL, and `tx_index` can permanently record `code=0`.

**Remediation:** Require exact cardinality: for a block with N transactions, `txs_results` must contain N result objects before any transaction is processed. Require an explicit parseable `code` for every entry. Treat mismatch as a retryable block-fetch failure with a bounded overall deadline; never advance the height. Add a test where the first `block_results` response is empty/partial and the later response contains a failed transaction.

---

### H-4: Passed Governance Messages Depend on a Dead Cache and Undeclared REST Fallback (High)

**Location:** `indexer/main.py` lines 340–386 and 445–490; `indexer/message_processor.py` lines 2273–2281; `indexer/chain_client.py` lines 233–280; documented policy at `indexer/main.py:5–8` and `docs/modules/INDEXER.md:592–597, 833–835`.

Both `/cosmos.gov.v1beta1.MsgSubmitProposal` and `/cosmos.gov.v1.MsgSubmitProposal` are parsed with `cosmpy.protos.cosmos.gov.v1beta1.MsgSubmitProposal`. That generated message has fields `content`, `initial_deposit`, and `proposer`; it has neither `messages` nor `msgs`. `extract_inner_messages` therefore returns an empty list and `_proposal_cache` is never populated.

When a proposal passes, `fetch_proposal_messages` calls port 1317 REST, not gRPC. This contradicts the indexer's explicit gRPC-only/no-REST policy and the nearby logs that call the lookup “via gRPC.” The standard node template currently enables REST on port 1317 (`deploy/templates/node/app.toml:53–56`), while the local review environment had it disabled. A REST outage, configuration that follows the documented indexer policy, or other resolution failure is logged as “non-fatal,” then block processing and checkpoint advancement continue. `_skipped_proposals` also converts selected resolution errors into a no-retry decision for the process lifetime.

**Impact:** Passed `MsgUpdateParams`, `MsgSetLevel`, moderation, or other tracked proposal messages can be absent from PostgreSQL until an unrelated restart/resync repairs only part of the state. Cached params remain stale, so later blocks are validated and weighted against old governance values. Governance moderation actions may never be reflected.

**Remediation:** Decode the actual gov v1 and v1beta1 wire types explicitly. Replace REST with the governance gRPC `Query/Proposal` endpoint. Make failure to resolve a passed proposal fatal to that block unless every inner message is on an explicit, tested “no indexed effect” allowlist. Remove transient failures from `_skipped_proposals`; retry with a bounded deadline. Add an end-to-end test with REST disabled to enforce the indexer's documented policy, even though the current deploy template enables REST: submit, pass, and index a multi-message proposal.

---

### H-5: Media Enrichment Permits Blind SSRF and Unbounded Indexer Stalls (High)

**Location:** `indexer/message_processor.py` lines 1874–1900, 1994–2049, 2081–2161, and 2163–2270; chain media validation at `blockchain/x/core/module/module.go:1350–1366`.

`discover_post_thumbnail` checks the initial hostname with `_is_public_http_url`, but `_fetch_html` follows redirects without validating each destination. A public HTTPS URL can redirect to `http://127.0.0.1`, a private service, or a link-local metadata endpoint.

The media-dimension path is less protected: `_probe_media_dimensions` calls `_probe_dimensions` for direct images and derived thumbnails without invoking `_is_public_http_url` at all. Chain media must start with `https://`, but an attacker-controlled HTTPS endpoint can redirect to a private HTTP target because `requests` follows redirects by default.

The denial-of-service bounds are also incomplete:

- `_fetch_html` uses non-streaming `requests.get`; the entire response is downloaded/decompressed before `resp.text[:1_500_000]`.
- `_probe_dimensions` has a byte cap but no wall-clock deadline. A peer can drip chunks just under the read timeout.
- `discover_media_dimensions` calls `wait(..., timeout=10)` but exits a `ThreadPoolExecutor` context, whose shutdown waits for already-running requests. `Future.cancel()` does not cancel them.
- Enrichment runs synchronously in the canonical block-processing thread.

**Impact:** Any user who can post a URL can make the validator host issue blind GET requests and can hold block indexing behind slow or oversized responses. While the backend detects height lag, the indexer can be kept perpetually behind and the backend can become unavailable for writes.

**Remediation:** Move all remote media enrichment out of the block checkpoint path. Use one hardened fetch helper that resolves and pins the destination, rejects private/link-local/reserved addresses, disables redirects or revalidates every hop, caps compressed and decompressed bytes while streaming, validates content type, and enforces one wall-clock budget. Treat DNS rebinding explicitly. Add redirect-to-loopback, slow-drip, oversized-body, and worker-timeout tests.

---

### M-1: Existing Databases Silently Skip Irrecoverable History After Long Downtime (Medium)

**Location:** `indexer/main.py` lines 501–550; `deploy/templates/env/indexer.env:15`; long-history list contract in `indexer/database.py:12, 1936–2010`.

For both a fresh database and an existing database, catch-up is clamped to the later of the node's earliest retained height and `current_height - 7 days`. If `last_height + 1` is older, the code logs an adjustment, starts later, and eventually advances the checkpoint across the missing range.

This is not merely lost analytics. Blocked lists intentionally retain up to 100,000 historical entries per user while the chain keeps a much smaller deque. Once pruned blocks are skipped, that history cannot be reconstructed from current chain state. Weekly PostgreSQL backups mitigate total loss but do not make a silently partial rebuild correct.

**Impact:** A node offline longer than the lookback window, or restored with a stale database, serves an apparently healthy but permanently incomplete feed/moderation view.

**Remediation:** If an existing checkpoint cannot continue at exactly `last_height + 1`, fail hard and require an operator-selected trusted PostgreSQL restore or archive source. For a deliberately partial fresh node, require an explicit flag and persist an `incomplete_before_height` marker that the backend/monitoring exposes. Do not call the database fully rebuilt.

---

### M-2: Balance Query Failures Are Persisted as Real Zero Balances (Medium)

**Location:** `indexer/chain_client.py` lines 382–398; `indexer/main.py` lines 828–854 and 934–946.

`ChainClient.get_balance` catches every gRPC error and returns `0`. Callers are written as if it raises: they catch exceptions, but the exception can never arrive. The startup snapshot's exception branch is therefore dead for gRPC failures; startup writes zero for every failed account, and per-block refresh writes zero for every touched address whose query failed.

**Impact:** A transient gRPC outage overwrites known-good balances with zero, which the backend serves as chain truth. Per-block corruption can persist until that address is touched again or the indexer restarts.

**Remediation:** Propagate query failures. Only upsert balances with successful, validated responses; log failed addresses and retry them under a bounded budget. Reuse a gRPC channel/batch strategy so one block cannot create hundreds of sequential three-second channel/query attempts.

---

### M-3: Startup Profile Sync Is Neither Complete Nor a Reconciliation (Medium)

**Location:** `indexer/main.py` lines 702–712 and 971–1008; `indexer/chain_client.py` lines 158–231.

Startup sync updates scalar `profiles` rows only. It does not:

- sync `enabled_agents`, followed lists, or blocked lists;
- mark database profiles absent from a verified complete chain response as deleted;
- detect malformed/skipped profile records;
- prove the ABCI subspace response is complete;
- fail startup when sync fails.

The fallback is REST despite the no-REST architecture, and the caller logs “KV Sync skipped” before continuing.

**Impact:** Deleted profiles can remain active after a missed event; fresh databases omit current social lists until those users change them; list history older than lookback is absent; and the indexer can advertise a current height while serving stale profile state.

**Remediation:** Make scalar reconciliation fail-fast and completeness-checked. Sync current list state through supported gRPC queries, while treating long-term deque history as backup/archive data rather than reconstructable current state. Reconcile deletions only after a complete authoritative owner inventory; never infer deletion from a partial response.

---

### M-4: Difficulty, Supply, and Per-Block State Are Best-Effort and Gap During Catch-Up (Medium)

**Location:** `indexer/main.py` lines 401–405, 613–639, and 894–967.

Difficulty and supply history are written only after processing the final height delivered by a WebSocket callback. Catch-up does not write either history. If a callback closes a five-block gap, only the callback height gets a difficulty sample; a missed height divisible by 200 gets no supply sample. Recent-block, balance, head-height, and indexer-state failures are swallowed while the canonical checkpoint can still advance.

**Impact:** Charts and operational state have permanent holes after every disconnect. More importantly, `indexer_state` can claim recent progress even though required per-block state failed, and there is no durable error marker.

**Remediation:** Define which rows are required projection versus optional telemetry. Put required block hash/height state in the atomic block commit from H-1. Backfill telemetry at each intended sample height, or label it explicitly as current-head sampling rather than historical data. Record optional enrichment failures for bounded retry instead of silent discard.

---

### M-5: Migration Discovery Fails Open and Migration/Marker Writes Are Not Atomic (Medium)

**Location:** `indexer/migrations/__init__.py` lines 39–62, 65–79, and 82–133; `indexer/database.py` lines 31–33.

An exception importing a migration module is logged and skipped, allowing startup without the migration. Failure reading completed migrations returns an empty set, causing all migrations to be considered pending. Migration statements and `migration_*` markers use autocommit connections, so a crash can leave a partially applied migration without a marker.

**Impact:** Nodes can start with different schemas/data transformations while logs contain the only signal. A non-idempotent future migration can be partially applied and rerun.

**Remediation:** Make discovery/import and completed-set reads fatal. Serialize migration execution with a PostgreSQL advisory lock. Run each database-only migration and its marker in one transaction; split external RPC work into explicit resumable phases. Pin a checksum for each applied migration so edited historical files fail loudly.

---

### M-6: The Full PostgreSQL Credential Is Logged at Startup (Medium)

**Location:** `indexer/main.py` lines 685–688.

`Database URL: %s` logs `self.db.database_url`, which is the full `postgresql://user:password@host/database` secret from `INDEXER_DB_URL`.

**Impact:** Anyone with access to aggregated/service logs receives the indexer's read-write database credential. The backend's read-only role limits backend compromise, but this log exposes the write role directly.

**Remediation:** Log only a parsed, redacted host/port/database identifier. Never log username, password, query parameters, or the raw URL. Rotate the credential if existing logs were exported beyond the host.

---

### M-7: The Indexer Revalidates Successful Historical Messages Against Different Rules (Medium)

**Location:** `indexer/params.py` lines 93–117; `indexer/message_processor.py` lines 247–270; chain validation at `blockchain/x/core/module/module.go:1429–1468`.

The chain permits an empty root-post title and enforces only its tier-specific maximum. The indexer invents `min_title_size = 1` and silently rejects the already-successful transaction. It also loads current-head params once, then applies them to historical blocks, so a governance limit change can cause the same historical transaction to be accepted by one rebuild and omitted by another.

**Impact:** Valid on-chain posts can be absent from PostgreSQL; rebuild results depend on when the rebuild runs; and the indexer can orphan comments/votes that target an omitted root.

**Remediation:** Do not re-enforce chain admission rules after a transaction has a verified `code=0`. Decode and project it. Keep only database-safety checks that cannot disagree with consensus. If a projection invariant is still needed, generate/share exact rules and add parity tests, including empty titles and historical param changes.

---

### M-8: Vote Changes Apply the New Direction Instead of the Net Delta (Medium)

**Location:** `indexer/message_processor.py` lines 462–529 and 546–648; `indexer/database.py` lines 1486–1542.

For every non-neutral vote, `update_user_topic_stats` adds the new `raw_direction` to `net_votes`. It does not subtract the previous direction first. Repeating the same upvote adds another `+1`; changing `+1 → -1` adds only `-1` instead of the correct `-2`; and the neutral path updates preferences and the canonical vote row but never reverses `user_topic_stats.net_votes`.

**Impact:** Users can inflate or distort their topic standing through repeat/re-vote transactions, and clearing a vote leaves stale sentiment. `net_votes` participates in downvote-power gating, so the error changes later vote weights rather than remaining analytics-only.

**Remediation:** Compute `net_delta = new_direction - previous_direction` (where neutral is zero) and apply that once in the same transaction as the canonical vote upsert. Repeated identical votes must produce delta zero. Add transitions for `0→+1`, `+1→+1`, `+1→-1`, `-1→0`, and replay of each.

---

### M-9: Vote-Weight Calculation Fails Open to a Fabricated Weight (Medium)

**Location:** `indexer/message_processor.py` lines 577–648.

The vote-weight block includes profile/params reads and the `user_topic_stats` write. Any exception is logged, then indexing continues with a hardcoded fallback: upvotes receive weight `1.0` and downvotes receive the baseline. This can leave the required stats write missing while the vote row is committed with a value that did not come from chain params.

**Impact:** Transient database or parameter errors create permanent ranking drift while the block checkpoint advances. The fallback also violates the repository's fail-hard/no-fallback contract.

**Remediation:** Propagate the exception so the block transaction rolls back and retries. Do not write the vote, preferences, or checkpoint unless authoritative profile, params, stats, and vote writes all succeed.

---

### L-1: URL Width/Height Metadata Extraction Always Falls Back to Empty (Low)

**Location:** `indexer/database.py` lines 828–844.

`_extract_media_meta` calls `Database._sanitize_wh`, but no `Database` symbol exists; the broad exception catches the `NameError` and stores `{}`. A direct reproduction with `...?w=640&h=480` returned `[{}]`.

**Impact:** Known upload dimensions are silently discarded at insert time, causing avoidable network probing/layout shifts. Security impact is limited.

**Remediation:** Call `DatabaseManager._sanitize_wh` (or the current class) and add a focused test asserting valid dimensions survive while invalid values are rejected. Remove the broad catch around programmer errors.

---

### L-2: Failed Catch-Up Logs “Completed Successfully” (Low)

**Location:** `indexer/main.py` lines 558–590.

The success banner is in `finally`, so an exception processing any height still logs “INDEXER CATCHUP: Completed successfully” and “Caught up to height: end” before the exception propagates.

**Impact:** Operators can read a false success immediately before process failure, slowing diagnosis.

**Remediation:** Log completion only after the loop exits normally. On failure, log the last committed height, failed height, and exception, then exit non-zero.

---

### L-3: Duplicate-Instance Lock Failure Exits Successfully (Low)

**Location:** `indexer/main.py` lines 160–174.

If another process holds the lock, the new process logs an error and exits with status 0. A supervisor or deployment check can interpret that as a successful indexer start even though the process is not running.

**Remediation:** Exit non-zero with the lock path and holder PID in the error. Keep the existing bounded, non-blocking lock acquisition.

---

### I-1: Edit/Delete Authorization Remains an Accepted Indexer Boundary (Informational — Carryover)

The chain intentionally accepts edit/delete messages whose visibility authorization is enforced here. The indexer correctly derives normal user identity from `envelope_pubkey`, checks edit ownership, and distinguishes governance/admin/owner delete rights. A hostile node can still run a modified indexer, and accidental profile-level drift can affect admin delete decisions. This architecture was explicitly Accepted Risk in the backend M-8 retest; H-1 through H-4 are required to make the honest implementation dependable.

`derive_owner_from_dict` still prefers a generic explicit `owner` field over the envelope signer (`indexer/address_utils.py:92–106`). `MsgDelete` currently has no such field, so this is not exploitable today. Change precedence before reusing that helper for any message that has both fields.

---

### I-2: The Indexer Architecture Document States Guarantees the Code Does Not Provide (Informational)

**Location:** `docs/modules/INDEXER.md` lines 66–73, 118–122, 137–141, 592–597, 815–835.

The document says replay is idempotent, the DB can be rebuilt from chain, proposal fallback uses gRPC, difficulty/supply are recorded at each block, `_seen_txs` is ~10K, and REST is never used. Current code contradicts each claim; `_seen_txs` is capped at 5,000 (`indexer/settings.py:36`).

**Remediation:** Correct the document in the same changes that close H-1/H-4/M-1/M-4. Until then, put a warning in the recovery section that PostgreSQL is a required long-history artifact and `--height` is not a safe replay tool.

---

### I-3: Obsolete Queue Schema and Configuration Remain in the Indexer (Informational)

`pending_txs` plus its database methods remain even though the architecture says the indexer never broadcasts and the backend broadcasts directly. `DB_LIST_CAP_MULTIPLIER` and `DB_MAX_*` settings are unused while `INDEXER_LIST_CAP` is hardcoded separately. These are not live vulnerabilities, but they expand audit surface and invite future code to revive an obsolete transaction path.

**Remediation:** Remove them when next changing the schema/config surface. Dropping the existing table requires explicit schema-change approval.

---

## Prior Finding Status

| Prior finding | Current status |
| :--- | :--- |
| Backend 2026-08-05 M-8 — indexer trust/authz boundary, non-atomic writes, silent failure, lookback truncation | **Partially addressed / still open.** Integration drift checks now compare params, profile level, username, and balance for one provisioned user. There is still no runtime drift monitor, block transaction, hash reconciliation, or complete-history marker. Restated as H-1, H-2, M-1, M-3, and I-1. |

---

## Positive Security and Reliability Controls Observed

- **Single-instance lock:** `flock(LOCK_EX|LOCK_NB)` prevents two indexers in one container from concurrently applying cumulative updates.
- **Sequential gap fill:** WebSocket height gaps are processed in ascending order rather than skipping directly to the newest notification.
- **Fail-hard parameter bootstrap:** Required params and tier structure must load before block processing starts.
- **Envelope-derived user identity:** Normal user handlers derive the acting address from the signed envelope public key, not `authority`.
- **Edit/delete checks:** The accepted indexer authorization boundary has explicit ownership, governance, and admin branches.
- **SQL values are parameterized:** No user-controlled SQL identifier path was found; dynamic table/column names are internal constants.
- **Bounded in-memory transaction set and database lists:** `_seen_txs`, `tx_index`, and long-history lists have caps.
- **Read-only backend role:** The backend reads `mirage_indexer` through `mirage_indexer_ro`; it cannot corrupt index rows.
- **Finite network call timeouts:** RPC/gRPC/media calls specify timeouts, although H-5 shows the media operations lack an overall deadline.
- **Backups include PostgreSQL:** `scripts/backup_restore.py` runs `pg_dump` and validates a non-empty indexer dump, which is essential given M-1.
- **No dangerous Python execution primitives:** No `eval`, `exec`, `pickle`, unsafe YAML load, or shell-based subprocess was found.

---

## Test Coverage Gaps

| Gap | State |
|-----|-------|
| One transaction for all required block writes + checkpoint | **Absent — H-1** |
| Crash injection at every block write boundary; replay equality | **Absent — H-1** |
| `--height` replay against non-empty DB | **Absent — H-1** |
| Chain ID / stored block-hash mismatch on recovery | **Absent — H-2** |
| Partial/lagging `block_results`, including later non-zero code | **Absent — H-3** |
| Passed gov v1 multi-message proposal with REST disabled | **Absent — H-4** |
| Governance query transient failure retries same block | **Absent — H-4** |
| Media redirect to loopback/private IP | **Absent — H-5** |
| Slow-drip and oversized/decompression response budget | **Absent — H-5** |
| Downtime beyond pruning/lookback window fails closed | **Absent — M-1** |
| gRPC balance failure preserves last known value | **Absent — M-2** |
| Complete profile/list/deletion reconciliation | **Absent — M-3** |
| Catch-up difficulty/supply sampling | **Absent — M-4** |
| Migration import/read failure is fatal; migration+marker atomicity | **Absent — M-5** |
| Empty root title and historical param parity | **Absent — M-7** |
| Re-vote/neutral-vote `net_votes` delta correctness | **Absent — M-8** |
| Vote-weight query/write failure rejects the block | **Absent — M-9** |
| Direct-chain foreign edit/delete succeeds on-chain but leaves index unchanged | **Absent — I-1** |
| Width/height query metadata extraction | **Absent — L-1** |

The existing `indexer` backend category checks API shape, current balances/profile fields, current params, health, WebSocket reconnect, and `tx_index`. `indexer_drift` compares a small current-state sample against direct chain queries. Neither suite exercises block processor failure semantics or recovery.

---

## Urgency Assessment

| ID | Recommended timing | Rationale |
| :--- | :--- | :--- |
| H-3 — missing tx result treated as success | **Before next release** | Violates the indexer's primary failed-transaction invariant and can project unauthorized/failed messages. Small, surgical fail-closed fix. |
| H-4 — governance cache/REST path | **Before next release** | Dead cache plus an undeclared fallback; governance state is lost whenever REST resolution fails. |
| H-5 — media SSRF / stall | **Before next release** | Public-input network access on a validator host; can stall canonical indexing. |
| H-1 — block atomicity / replay | **Next indexer hardening milestone** | Largest integrity defect and root cause for several lower findings; broader refactor and failure-injection tests required. |
| H-2 — recovery reconciliation | **With H-1, before next divergence recovery** | Recovery currently preserves and trusts potentially divergent rows. |
| M-1 / M-3 — incomplete history and profile sync | **Before relying on fresh rebuilds** | Current rebuild guarantees are false; backup restore must remain the supported recovery path until fixed. |
| M-2 / M-4 / M-5 / M-6 / M-7 / M-8 / M-9 | **Near-term backlog** | Concrete correctness/security improvements, mostly surgical after the High fixes establish the contract. |
| L-1 / L-2 / L-3 / I-2 / I-3 | **Fix in passing** | Low-impact bugs, observability, and dead-surface cleanup. |

---

## Prioritized Recommendations

1. **Fail closed on block/result cardinality (H-3).** This is the smallest high-value change and needs a lagging-results regression test.
2. **Replace governance REST resolution with exact protobuf + gRPC handling (H-4).** Make unresolved passed proposals block-fatal.
3. **Take media enrichment off the checkpoint thread and harden all fetches (H-5).**
4. **Introduce one required block transaction and atomic checkpoint (H-1).** Remove handler-level swallowing for required projection writes.
5. **Add startup chain-ID/hash reconciliation and a documented PostgreSQL recovery decision (H-2).**
6. **Fail on history gaps instead of silently clamping (M-1); expose deliberate partial-history state.**
7. **Stop persisting query failures as zero and make profile reconciliation authoritative (M-2, M-3).**
8. **Separate required projection from optional telemetry and backfill intended samples (M-4).**
9. **Make migration discovery/execution fail-closed and redact the database URL (M-5, M-6).**
10. **Correct re-vote deltas and remove vote-weight fallback (M-8, M-9).**
11. **Remove consensus revalidation drift, fix media metadata extraction, and correct the indexer documentation (M-7, L-1, I-2).**

---

## Verification Performed

- Inventoried 18 tracked indexer Python files / 7,092 lines, 26 `_handle_*` methods, 24 schema `CREATE TABLE` statements in `database.py`, and 10 migration modules.
- Diffed `indexer/` against the current prod merge-base and v1.32.4 baseline: no indexer changes in the reviewed delta.
- Traced block/result mapping, failed/successful transaction paths, checkpoint advancement, replay behavior, all message handlers, governance cache/fallback, startup sync, recovery interaction, balance refresh, and media fetches.
- Verified the installed v1beta1 `MsgSubmitProposal` descriptor has only `content`, `initial_deposit`, and `proposer`; `extract_inner_messages` cannot populate the documented cache.
- Confirmed local port 1317 refused the governance REST request while RPC remained available. The indexer policy documents no REST, but the standard node deploy template currently enables port 1317.
- Reproduced `_extract_media_meta("...?w=640&h=480")` returning `[{}]`.
- Confirmed local `/block_results` subscription event attributes are plain strings; no finding was raised for subscription event decoding.
- `python -m compileall -q indexer` — pass.
- `python -m pip check` — “No broken requirements found.”
- Searched indexer code for dangerous execution/deserialization and SQL construction patterns; no exploitable primitive found.
- Attempted `python tests/test_backend.py --category indexer`; the suite aborted before tests because the expected `mirage` Docker container was unavailable, although local RPC was running.
- `ruff` and `pip-audit` were not installed in the `mirage-node` environment. The repository dependency-audit script therefore did not run.

---

## Assumptions

- Production servers were not contacted.
- The local node response shape is representative of the deployed CometBFT version.
- Honest nodes run the reviewed indexer; the accepted ability of a node operator to serve a modified index is not reclassified as a vulnerability.
- PostgreSQL backups are taken as documented, but backup freshness and restore success were not tested.
- A node-local DB/network error and a process crash are realistic operational events; “rare” is not equivalent to safe when the checkpoint advances past them.
- Database schema changes remain approval-gated. Most immediate remediations do not require a new table; any proposed schema extension must be approved separately.

---

## Follow-up Retest Guidance

**Done.** See [`2026-08-07/indexer-retest.md`](indexer-retest.md).

