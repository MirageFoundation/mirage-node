# Indexer Security Review — Retest of 2026-08-07

**Retest of:** [`review-2026-08-07.md`](review-2026-08-07.md) — first dedicated indexer security/correctness review (5 High, 9 Medium, 3 Low, 3 Informational).
**Review baseline:** `dev` at `d9dbf87a` (`v1.32.4`).
**Retest state:** remediation implemented against baseline tag **v1.32.4** and shipped as **v1.33.0** (migrations keyed `v1_33_0_*`).
**Scope of this document:** status of every finding, evidence, and residuals that remain accepted or deferred.

---

## Summary

**18 findings fixed, 2 accepted.** No High finding remains open in code. I-3's table drop landed in v1.33.2 once schema approval was given; everything still outstanding is an accepted decision or an explicitly deferred plan item, listed below.

The two accepted items are decisions, not oversights. **M-1** (long downtime skips irrecoverable history) was deliberately not implemented as the review specified: failing startup hard would leave a node that was offline past the pruning window with *no* index at all, and in practice would be worked around by wiping the database — losing the very blocked-list history the finding exists to protect. The shipped behavior continues indexing but records the exact missing range and can no longer report itself as complete. **I-1** remains the accepted architecture from the backend M-8 retest; only the concrete owner-precedence bug inside it was fixed.

The remediation contract now matches the operator decisions from the plan:

- Block projection and checkpoint are one PostgreSQL transaction; required handler failures re-raise and roll the block back.
- Chain ID + checkpoint hash are stored and verified; pruning gaps continue automatically but are recorded and exposed.
- Media enrichment no longer performs outbound fetches; only deterministic URL transforms remain.
- Governance and profile inventory use gRPC only; REST/ABCI fallbacks are gone.
- `--height` against a non-empty database is rejected; unsafe replay tooling is deferred.

---

## Status of All Findings

| ID | Finding (abbreviated) | Status | Evidence |
|----|----------------------|--------|----------|
| H-1 | Non-atomic block writes / swallowed failures / unsafe replay | **Fixed** | `DatabaseManager.transaction` + `set_checkpoint` inside txn; handlers re-raise; `--height` rejected when `last_height > 0`; `indexer_hardening.block_transaction_rolls_back`, `.checkpoint_requires_txn` |
| H-2 | No chain-ID / hash continuity after recovery | **Fixed** | `meta.chain_id` / `meta.last_block_hash`; startup hash check at the checkpoint height; recover.sh documents no auto-wipe; health exposes continuity; `indexer_hardening.checkpoint_has_provenance` |
| H-3 | Missing `txs_results` treated as success | **Fixed** | `get_block_results_matching`; `indexer_hardening.block_results_retry`, `.block_results_deadline` |
| H-4 | Dead gov cache + REST fallback | **Fixed** | gov v1 gRPC `fetch_proposal_messages`; `extract_inner_anys`; fail-closed on unresolved tracked proposals; `indexer_hardening.extract_inner_anys`, `.no_rest_port` |
| H-5 | Media SSRF / unbounded stalls | **Fixed** (by removal) | `discover_post_thumbnail` is offline/deterministic; no requests/BS4/PIL in message path; `indexer_hardening.thumbnail_deterministic`, `.no_remote_media`, `.message_processor_no_http` |
| M-1 | Silent history clamp / incomplete history | **Accepted with guardrails** | Auto-continue on pruned `last_height+1`; gaps in `meta.history_gaps`; `history_complete=false`; health exposes ranges; `indexer_hardening.history_gap_merge`, `.history_gap_validation` |
| M-2 | Balance/query failures written as zero | **Fixed** | `get_balance` / batch / supply / earliest height fail hard |
| M-3 | Incomplete profile reconciliation | **Fixed** | paginated `GetProfiles` gRPC; fail-hard Go JSON/list errors; full reconcile before live mode |
| M-4 | Catch-up difficulty/supply claims | **Fixed** (reclassified as head telemetry) | Samples taken only at real queried heads and skipped during catch-up; docs no longer claim per-block history; historical backfill out of scope |
| M-5 | Migration discovery/locking soft-fail | **Fixed** | fail-closed discovery; session-held advisory lock; checksum pinning; `run_db_migration` atomicity |
| M-6 | Credentialful DB URL in logs | **Fixed** | `format_db_target`; `indexer_hardening.db_target_redacted`, `.db_target_default_port`, `.db_target_fails_hard` |
| M-7 | Post-consensus admission revalidation | **Fixed** | size gates removed from successful-tx projection; missing vote/edit/annotate targets and out-of-range vote directions log and skip instead of failing the block |
| M-8 | Vote `net_votes` uses direction not delta | **Fixed** | `net_votes_delta`; `v1_33_0_rebuild_derived_stats`; `indexer_hardening.net_votes_delta_signature`, `.vote_direction_normalized`, `.net_votes_matches_canonical_votes` |
| M-9 | Vote-weight / required write fallbacks | **Fixed** | weight errors re-raise; preference/stat paths re-raise |
| L-1 | Media `w`/`h` query meta dropped | **Fixed** | `_sanitize_wh` via `_extract_media_meta`; `indexer_hardening.media_meta_extraction`, `.sanitize_wh_bounds` |
| L-2 | Catch-up logs success in `finally` | **Fixed** | completion logged only after normal loop exit |
| L-3 | Duplicate-instance lock exits 0 | **Fixed** | lock contention `sys.exit(1)` |
| I-1 | Edit/delete trust boundary untested | **Accepted risk, bug fixed, now tested** | envelope-first `derive_owner_from_dict`; `indexer_hardening.derive_owner_envelope_first`, `.derive_owner_fallbacks`, `.foreign_edit_rejected`, `.owner_edit_applied` |
| I-2 | INDEXER.md contradicted code | **Fixed** | `docs/modules/INDEXER.md` patched for atomic checkpoint, history gaps, gRPC-only, no-network media, head-sampled telemetry |
| I-3 | Obsolete `pending_txs` surface | **Fixed** | Methods + fresh CREATE removed (`indexer_hardening.obsolete_surface_removed`); table dropped by `v1_33_2_drop_pending_txs` after schema approval |

---

## Fixed

### H-1 — atomic projection

`_process_block` fetches/validates block results outside the DB, then applies all required writes and `set_checkpoint(height, hash, chain_id)` inside one `db.transaction()`. `set_checkpoint` refuses to run without an active transaction. Required handler exceptions propagate. `_seen_txs` and unsafe non-empty `--height` replay are gone.

Aborting the block is scoped to indexer failures, never to the content of a message the chain accepted — see M-7. The chain validates only that a vote target is well-formed hex, never that it exists, and does not constrain `direction`; `MsgEdit` may disagree with the stored post's target. Those cases log and skip. Raising on them was verified during local testing to halt the indexer permanently at the offending height, which any user could trigger with one transaction against every node on the network.

### H-2 — continuity

The checkpoint stores chain ID and block hash alongside the height. Before projecting anything, startup compares `meta.chain_id` against the node's chain ID, every retained `recent_blocks` hash against the node's hash at that height, and `meta.last_block_hash` against the node's hash at `meta.last_height`; any mismatch is fatal and leaves the database untouched for the operator. A database indexed before those meta keys existed is adopted rather than rejected, but only once the node confirms its `recent_blocks` row at the checkpoint height — a diverged database fails that same comparison. If the checkpoint height sits below the node's earliest retained block the hash cannot be compared at all, so continuity is recorded as `unverified_pruned_gap` rather than claimed verified, and a database with no recorded provenance is refused outright in that case. `scripts/recover.sh` documents that PostgreSQL is never auto-wiped and that the operator must restore a trusted `pg_dump` whose checkpoint matches the recovered chain.

### H-3 — result cardinality

`ChainClient.get_block_results_matching` retries until `len(txs_results) == N` (or null only when `N=0`), then fails the height under a deadline.

### H-4 — governance gRPC

Proposal messages are resolved via cosmos.gov.v1 gRPC (legacy v1beta1 content path retained for shape). Unresolved tracked proposals fail the block.

### H-5 — media

Outbound OG/image probing removed. Thumbnails are deterministic transforms for raster/YouTube/Cloudflare/Bunny URLs only.

### M-2 / M-3 / M-5 / M-6 / M-7 / M-8 / M-9 / L-1 / L-2 / L-3 / I-2

As in the status table. Derived-stat repair ships as `indexer/migrations/v1_33_0_rebuild_derived_stats.py`, which recomputes `net_votes` and topic content stats from the canonical `votes` and `posts` rows for databases written by the old direction-based arithmetic. Its dominant-tag rebuild mirrors `DatabaseManager._compute_dominant_tag` exactly, including the `ratio >= 0.5` threshold and the empty-string default.

---

## Accepted / deferred residuals

### M-1 — automatic continue on pruned history

**Accepted.** When `last_height + 1` is below the node's earliest retained height, the indexer records the gap, sets `history_complete=false`, and continues. Hash continuity across a no-overlap gap is reported as `unverified_pruned_gap`, not claimed verified.

### I-1 — edit/delete trust boundary

**Accepted risk, unchanged from the backend M-8 retest.** The indexer still derives the acting user from unsigned message content when a message carries no envelope, because governance and node-relayed messages legitimately do so. What changed is the precedence: `derive_owner_from_dict` now reads the envelope signer *first* and only falls back to `owner`, then `authority`. Previously a relayer-supplied `owner` field outranked the signed envelope, which let a caller attribute an action to another address. `_handle_edit` and `_handle_delete` compare the derived owner against the stored post owner and drop the message on mismatch; `indexer_hardening.foreign_edit_rejected` exercises that path against a stub database rather than a live chain, so it runs in CI without docker.

### M-4 — historical difficulty/supply backfill

Not planned. Difficulty and supply are now documented and implemented as head telemetry: sampled only when the indexer actually queries the node, and skipped entirely during catch-up. Reconstructing those series for pruned heights would require application state the node no longer retains.

### I-3 — drop existing `pending_txs`

**Closed in v1.33.2.** The dead read/write API and the fresh-schema `CREATE TABLE` went in v1.33.0; `indexer/migrations/v1_33_2_drop_pending_txs.py` removes the table itself from deployed databases, after schema-change approval. Both prod and UAT held zero rows at the time it was written. The migration counts before it drops and raises if the table is non-empty, since rows would mean something still writes to it and would invalidate the reason for dropping. On databases created after v1.33.0 the table never existed and the migration records itself as a no-op.

### Explicitly still deferred (plan)

- Remote media enrichment service
- Safe non-empty `--height` replay/rebuild tool
- Automatic indexer wipe/rollback after divergence

---

## Verification

```bash
conda activate mirage-node
python -m compileall -q indexer shared tests/cases/test_backend_indexer.py web/backend/chain.py
python -m pip check
python tests/test_backend.py --category indexer_hardening
python tests/test_backend.py --category indexer
python tests/test_backend.py --category indexer_drift
python tests/test_backend.py --category indexer_fail_hard
```

Primary regression category: `indexer_hardening` in `tests/cases/test_backend_indexer.py` (credential redaction, media meta, deterministic thumbnails, envelope owner precedence, foreign-edit stub rejection, `block_results` retry/deadline, history-gap merge, obsolete-surface removal, plus optional live-DB provenance/`net_votes`/rollback checks).

**Retest evidence (2026-08-07 local docker, restored from the latest UAT backup):** `indexer_hardening` **36/36**, `tests/test_backend.py` **783/783**, `tests/test_blockchain.py` **280/280**. The docker-gated checks (`checkpoint_has_provenance`, `net_votes_matches_canonical_votes`, `block_transaction_rolls_back`) were observed green against a real database, not skipped.

Run the suites **inside the container**. From the host, `_docker_exec` shells out to `docker exec bash -lc`, which does not source `/root/.mirage/env/*.env`, so probes that import `client_ip` or read `BACKEND_DB_URL` fail on a missing variable rather than on what they test, and the live-DB checks cannot reach PostgreSQL. Submit `scripts/proposals/proposal_set_pow_message_limit_9999999.json` first or PoW difficulty makes the backend suite impractically slow.

The end-to-end run also exercised the deployment path the unit checks cannot: continuity `adopted` on the first start against a database with no recorded provenance, then `verified` on the next; the `v1_33_0` rebuild applied to real rows; and passed-proposal resolution over gov v1 gRPC with a params reload.

### Follow-up review fixes (same day)

Implementation review closed remaining soft-fail residuals before release:

- Subscribe / auto-renew / biography now require gRPC `GetProfile` (no ABCI soft-query fallbacks).
- Live WebSocket projection failures exit non-zero instead of looping forever.
- Touched-balance gRPC reads are prefetched outside the block transaction.
- Continuity compares retained `recent_blocks` hashes before any overwrite; migrations run only after continuity.
- Auto-upvote contributes `net_votes_delta=+1`; preference rebuild excludes `auto_%` rows.
- Missing vote/edit/annotate targets log and skip unconditionally. An earlier
  round of this remediation gated that on `history_complete=false`, which local
  testing showed would halt the indexer permanently on a vote for a post that
  never existed — see M-7.
- Corrupt `meta.history_gaps` raises `IndexerUnavailable`; `set_last_height` is forbidden.
