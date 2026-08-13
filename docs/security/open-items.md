# Security Open Items — Cross-Component Register

**As of:** 2026-08-13, at the `v1.34.0` tag on `dev`. Pinned to the tag rather than a commit hash, which went stale the moment the release was amended.
**Purpose:** one place to find every security item that is still open across components, so that an accepted risk or a deferred plan item cannot quietly become forgotten work. Every entry needs either a scheduled action or a recorded decision.

Component detail lives in the retests, which stay authoritative for their own findings:

- [blockchain](blockchain/review-2026-08-07-retest.md) — staged for `v1.34.0`
- [backend](backend/review-2026-08-07-retest.md) — shipped `v1.33.3`, plus the 2026-08-12 delta appendix
- [indexer](indexer/review-2026-08-07-retest.md) — shipped `v1.33.0`–`v1.33.2`, plus the 2026-08-12 delta appendix and the topic-attribution fix in `v1.34.0`
- [frontend](frontend/retest-2026-08-09.md) — plus the 2026-08-12 delta appendix

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
| Indexer M-1 | Pruned-history gaps continue instead of failing | Failing startup hard would leave an offline-too-long node with no index at all, and would be worked around by wiping — losing the blocked-list history the finding protects. Guarded by `history_gaps`, `history_complete=false`, and the `unverified_pruned_gap` continuity marker. |
| Indexer I-1 | Owner derivation from unsigned content | Accepted architecture with the envelope-first precedence fix. Revisit only if node-relayed messages stop needing it. |
| Indexer L-4 | Skipped content derivations are not durably recorded | Only cosmetic fields can be lost. Trigger: the first time a missing thumbnail or mention needs explaining after the fact. |
| Indexer I-4 | Supervisor restart budget is a rate, not a lifetime cap | A genuinely fatal startup error crash-loops fast enough to trip the hourly cap and exit loudly. Trigger: an observed sustained flap, or the arrival of an alerting channel. |
| Frontend L-1 | Photon/wsrv thumbnail proxies | Keep the viewer's IP off origin hosts and apply upstream abuse filtering that a direct fetch would not. |
| Frontend L-4 | Click-to-load media gate removed | Inline media on unknown hosts now loads without consent, so a post author can learn a passing reader's IP. Accepted for reading experience; recorded separately because the proxy rationale does not cover a direct inline fetch. |
| Dependencies | `GO-2026-5932` (OpenPGP), `GO-2026-4479` (Pion DTLS) | No upstream fix exists. Reached only through the SDK keyring CLI and CometBFT's optional libp2p transport; production uses the `test` keyring backend and `[p2p.libp2p] enabled=false`. Revisit immediately if a deployment template enables libp2p. |

---

## Deferred work with triggers

### Highest value first

**I-1 — separate public query load from validating processes (ops project).** Still the single highest-value operational prevention, and still unverified because fleet hosts were not contacted. Scope: move indexer, backend, and public query load off validating processes, or document equivalent RPC, cgroup, and resource isolation. Trigger: the next infrastructure or capacity window, or any new divergence investigation. Acceptance: a read-only fleet inventory showing validator processes isolated from public query workloads, followed by 30 days with no load-correlated divergence. Never change production without separate explicit approval.

**Indexer — a safe non-empty `--height` replay/rebuild tool.** The most valuable of the deferred indexer tooling, because divergence recovery currently requires a trusted `pg_dump` whose checkpoint happens to match the recovered chain. Trigger: the next divergence, or the next time an operator needs to rebuild a height range.

### The rest

| Component | Item | Trigger | Acceptance |
| :--- | :--- | :--- | :--- |
| Blockchain I-2 | `upgrades.go` decomposition and execution tests for already-run handlers | Handler 46+, the file exceeding 2,500 lines, or the next migration-framework change | Registrar-only top-level file, exhaustive registration still passing, seeded pre-upgrade state reaching exact post-upgrade invariants |
| Blockchain I-5 | Historical bridge-burn forensics | A user loss report, a compliance request, or a scheduled historical audit | A documented block-range scan proving no unmatched burns, or enumerating every unmatched amount and transaction. No production mutation. |
| Backend I-3 | Oversized route modules | The next feature that must substantially touch one of them | Only the quest-assignment extraction was ever in scope |
| Indexer M-4 | Historical difficulty and supply backfill | Not planned — the source data no longer exists on pruned nodes | — |
| Indexer | Remote media enrichment service; automatic indexer wipe/rollback after divergence | Operational need | — |

---

## Maintaining this file

Add an entry when a review closes with an accepted or deferred item, and remove it when the trigger fires and the work lands. An item that is fixed belongs in its component retest, not here. If an entry sits with a fired trigger and no action, that is the signal to escalate rather than to soften the wording.
