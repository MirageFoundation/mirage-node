# Security Open Items — Cross-Component Register

**As of:** 2026-08-13, at the `v1.34.1` tag on `dev`. Pinned to the tag rather than a commit hash, which went stale the moment the release was amended.
**Purpose:** one place to find every security item that is still open across components, so that an accepted risk or a deferred plan item cannot quietly become forgotten work. Every entry needs either a scheduled action or a recorded decision.

Component detail lives in the retests, which stay authoritative for their own findings:

- [blockchain](2026-08-07/blockchain-retest.md) — staged for `v1.34.0`
- [backend](2026-08-07/backend-retest.md) — shipped `v1.33.3`, plus the 2026-08-12 delta appendix
- [indexer](2026-08-07/indexer-retest.md) — shipped `v1.33.0`–`v1.33.2`, plus the 2026-08-12 delta appendix and the topic-attribution fix in `v1.34.0`
- [frontend](2026-08-09/frontend-retest.md) — plus the 2026-08-12 delta appendix
- [cross-component sweep 2026-08-13](2026-08-13/cross-component-review.md) — Critical/High only, all five components; staged for `v1.35.0`; **authoritative for the unfixed items in the next section**

---

## Open Critical / High — action required

**None.** The [2026-08-13 sweep](2026-08-13/cross-component-review.md) found 1 Critical and 5 High; four were fixed the same day and two were accepted as non-issues by the operator. The fixes are staged for **`v1.35.0`** and are code-complete and test-verified, but **not yet released** — the chain change takes effect only after the binary is rebuilt and the fleet crosses the `v1.35.0` upgrade height.

| ID | Component | Item | Outcome |
| :--- | :--- | :--- | :--- |
| **C-1** | Indexer | Account self-delete permanently wedged the indexer on an earlier block | **Fixed** — `GetProfile` returns `codes.NotFound`; indexer skips and logs `profile_absent`; unknown message types no longer halt either. Two regression tests pin the status code. |
| **H-1** | Deploy | Fleet addresses in public git history | **Non-issue (accepted)** — addresses are public knowledge; keeping them out of the tree is the only requirement and it already holds |
| **H-2** | Deploy | Remote RPC `block_id.hash` reached `eval` as root during `--init` | **Fixed** — `eval` removed in favour of a validated four-key parser; hash also hex-checked at the source. Verified against injection payloads. |
| **H-3** | Deploy | `backup_restore.py` published `1317`/`9090`, which ufw cannot restrict | **Fixed** — single `CONTAINER_PORTS` constant matching `deploy.sh`. Live check: no host was ever in the exposed state. |
| **H-4** | Deploy | Backup archive mode `0644` in `/tmp` | **Non-issue (accepted)** — operator's own backups on single-tenant hosts; live check found no archive present |
| **H-5** | Backend | Invite-referral reward re-payable to the same pair | **Fixed** — gated on `is_new_user and code == 0`. **It had already fired in production:** one referee was paid twice (2026-04-15 and 2026-04-18), both claimed. |

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
| Indexer M-1 | Pruned-history gaps continue instead of failing | Failing startup hard would leave an offline-too-long node with no index at all, and would be worked around by wiping — losing the blocked-list history the finding protects. Guarded by `history_gaps`, `history_complete=false`, and the `unverified_pruned_gap` continuity marker. |
| Indexer I-1 | Owner derivation from unsigned content | Accepted architecture with the envelope-first precedence fix. Revisit only if node-relayed messages stop needing it. |
| Indexer L-4 | Skipped content derivations are not durably recorded | Only cosmetic fields can be lost. Trigger: the first time a missing thumbnail or mention needs explaining after the fact. |
| Indexer I-4 | Supervisor restart budget is a rate, not a lifetime cap | A genuinely fatal startup error crash-loops fast enough to trip the hourly cap and exit loudly. Trigger: an observed sustained flap, or the arrival of an alerting channel. |
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
| Blockchain I-2 | `upgrades.go` decomposition and execution tests for already-run handlers | Handler 46+, the file exceeding 2,500 lines, or the next migration-framework change | Registrar-only top-level file, exhaustive registration still passing, seeded pre-upgrade state reaching exact post-upgrade invariants |
| Blockchain I-5 | Historical bridge-burn forensics | A user loss report, a compliance request, or a scheduled historical audit | A documented block-range scan proving no unmatched burns, or enumerating every unmatched amount and transaction. No production mutation. |
| Backend I-3 | Oversized route modules | The next feature that must substantially touch one of them | Only the quest-assignment extraction was ever in scope |
| Indexer M-4 | Historical difficulty and supply backfill | Not planned — the source data no longer exists on pruned nodes | — |
| Indexer | Remote media enrichment service; automatic indexer wipe/rollback after divergence | Operational need | — |

---

## Maintaining this file

Add an entry when a review closes with an accepted or deferred item, and remove it when the trigger fires and the work lands. An item that is fixed belongs in its component retest, not here. Unfixed Critical/High items go in the first section instead, and are removed only once a retest records them as closed — never by downgrading them into an accepted decision. If an entry sits with a fired trigger and no action, that is the signal to escalate rather than to soften the wording.
