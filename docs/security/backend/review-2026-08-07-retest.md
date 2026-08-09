# Backend Security Review — Retest of 2026-08-07

**Retest of:** [`review-2026-08-07.md`](review-2026-08-07.md) — full backend audit, 2 Medium, 8 Low, 3 Informational.
**Review baseline:** `dev` at `d9dbf87a` (v1.32.4 plus review commit).
**Retest state:** remediation committed as `5dec8f59` / `bd2c294f`, released as **v1.33.3**, and deployed to all four validators on 2026-08-09.
**Scope of this document:** status of every Aug 7 finding, regression evidence, and residuals that remain accepted or deferred. Where this document and the original disagree about present-day state, **this one is authoritative**; the original is preserved as written, with its line references frozen at its baseline.

> **Earlier reviews.** [`review-2026-08-06.md`](review-2026-08-06.md) and
> [`review-2026-08-05-retest.md`](review-2026-08-05-retest.md) remain the record of
> how prior Critical/High remediations were closed. The Aug 6 payout residuals
> restated in Aug 7 as L-2/L-3 are closed here.

---

## Summary

**11 findings fully fixed, 1 accepted until a calendar cutoff, 1 deferred.** No Medium or Low finding from the Aug 7 review remains open in code. The unsigned-claim grace (**I-1**) is still an explicit product decision through 2026-10-05 UTC. The oversized route modules (**I-3**) stay deferred; the quest-assignment duplication that made them security-relevant was extracted without a broad route refactor.

The first remediation pass closed the review findings, then a second audit of that implementation corrected several defects before release: CheckTx acceptance is no longer reported as a completed payout; reward-summary polling drives reconciliation and exposes pending state; failed Expo sends release their throttle slot; mention pushes use one outbox row per recipient; analytics bind an address only after a successful signed route; and daily/flash assignment share one owner lock.

---

## Status of All Findings

| ID | Finding (abbreviated) | Status | Shipped |
|----|----------------------|--------|---------|
| M-1 | Action-side tracker ignores required quest env | **Fixed** | v1.33.3 |
| M-2 | Concurrent daily assignment can exceed cap | **Fixed** | v1.33.3 |
| L-1 | Stats fan-out accepts private HTTP(S) monikers | **Fixed** | v1.33.3 |
| L-2 | Crash after payout broadcast can double-pay | **Fixed** | v1.33.3 |
| L-3 | Payout CLI treats ambiguous success as transfer | **Fixed** (CLI removed) | v1.33.3 |
| L-4 | Push events deduplicated before delivery | **Fixed** | v1.33.3 |
| L-5 | Flash quest cap/insert not atomic | **Fixed** (with M-2) | v1.33.3 |
| L-6 | Test skips reported as passes | **Fixed** | v1.33.3 |
| L-7 | Query `address` mutates last-seen / analytics | **Fixed** | v1.33.3 |
| L-8 | Invite gate trusts client `Host` header | **Fixed** | v1.33.3 |
| I-1 | Unsigned/bad-proof claim grace until 2026-10-05 | **Accepted until cutoff** | setting required |
| I-2 | Soft defaults for media uploads / indexer enable | **Fixed** | v1.33.3 |
| I-3 | Oversized route modules | **Deferred** | quest assignment extracted only |

Prior Aug 6 residuals restated by Aug 7:

| Prior finding | Current status |
| :--- | :--- |
| 2026-08-06 L-1 — pay-before-mark crash window | **Fixed** (as Aug 7 L-2) |
| 2026-08-06 L-2 — CLI assumes non-JSON success | **Fixed** (as Aug 7 L-3) |
| 2026-08-06 L-3 — invite Host policy | **Fixed** (as Aug 7 L-8) |
| 2026-08-06 L-4 — soft defaults | **Fixed** (as Aug 7 I-2) |
| 2026-08-06 I-1 — claim grace | **Accepted until 2026-10-05** (as Aug 7 I-1) |

---

## Fixed

### M-1 — duplicate quest configuration

`quest_settings.py` is deleted. Route and action-side quest code use the required values in `settings.py`, including explicit booleans, bounded counts, probabilities, and interval validation. The v1.33.3 deploy migration writes required values for existing nodes and normalizes previously accepted indexer boolean spellings before strict parsing.

### M-2 and L-5 — daily and flash assignment races

Assignment is consolidated in `quest_assignment.py`. Daily selection, flash cap/cooldown checks, inserts, and `user_quest_state` updates run in real PostgreSQL transactions under one per-owner advisory transaction lock. Concurrent first requests are idempotent and cannot exceed the configured cap.

### L-1 — stats fan-out SSRF

Every inferred or explicit fleet endpoint is parsed and resolved. Credentials, paths, fragments, non-global IPs, and mixed public/private DNS answers are rejected. The outbound request connects to a validated IP with redirects disabled while preserving the original TLS hostname; environment proxy routing is disabled for this request.

### L-2 and L-3 — payout crash window and ambiguous transport

Claims persist signed unordered transaction bytes, hash, timeout, scan cursor, and reward links before broadcast. CheckTx success returns HTTP 202 until block scanning confirms DeliverTx success. Transport failures and rebroadcast rejections remain pending; rewards are released only after an initial definitive rejection, an included failed transaction, or expiration after a complete bounded scan. Broadcast responses require an explicit integer code and the exact expected transaction hash.

The summary endpoint reconciles open payouts even when payouts or quests are later disabled, and the frontend derives its pending state from that response and polls while confirmation is outstanding. Per-reward rounding now reconciles exactly to the on-chain batch amount, and pool checks include the transaction fee. The `miraged` CLI payout path is gone.

### L-4 — push deduplication before delivery

`push_event_seen` is now the transactional outbox. Source cursor advancement and enqueue commit together; workers lease due rows, settle only known delivery outcomes, retry with bounded exponential backoff, and never delete pending rows during cleanup. Pending payloads are database-constrained to be JSON objects, delivery database outages remain retryable, stale rows expire before delivery, and settlement no-ops fail visibly.

The source poller and delivery worker run on separate threads so Expo latency cannot stop source ingestion. Mention events are keyed per recipient, failed Expo attempts release their throttle slot, and malformed source rows are logged and advanced rather than pinning a cursor forever.

As with any external notification provider, a process death after Expo accepts a request but before local settlement can still duplicate a notification. The outbox deliberately prefers retrying over silently losing the event; exact atomic delivery across the database/Expo boundary is not available.

### L-6 — skips reported as passes

Results have explicit pass, fail, and skip states. The runner reports each count separately, and a skip in a release-gate category fails the run. The backend and blockchain entry points also hard-require the local Docker container, localhost backend, `hostname=testnet`, and the raised PoW message limit before wallet setup. Focused backend categories that use no wallets skip wallet provisioning instead of generating unrelated chain traffic.

### L-7 — unverified analytics identity

Query-string addresses no longer update last-seen or analytics identity. Anonymous requests use only the salted visitor identifier. The shared signature verifier records the derived address after successful cryptographic verification, and analytics bind it only when that signed route succeeds. Failed analytics writes release their in-process throttle entry so a retry is not silently dropped.

### L-8 — invite deployment gate

Invite validation policy uses server-side deployment configuration rather than trusting the request Host header. Regression coverage includes the spoofed-host case.

### I-2 — security-sensitive defaults

Media uploads, achievements, quest controls, claim grace, and indexer enablement require explicit configuration. Fresh deployments default media uploads off; the local reset enables them only for the local test environment.

---

## Accepted / deferred residuals

### I-1 — unsigned claim grace

**Accepted until the existing cutoff.** Missing or invalid reward-claim proofs remain allowed and logged until 2026-10-05 UTC. The setting is required and date-validated at startup; there is no code default. Do not extend the cutoff without a new product decision. After that date, verify unsigned and unverifiable proofs return 401 on a deployed node.

### I-3 — route module size

**Deferred.** No broad route refactor was performed. The duplicated quest assignment logic implicated by the review was extracted into `quest_assignment.py`, but unrelated route code remains untouched.

---

## Verification

Local Docker testnet (`hostname=testnet`) after `pow_message_limit=9999999`:

- Full backend suite: **854 passed, 0 skipped, 0 failed** (673 seconds)
- Focused late-audit categories (quest config, analytics identity, reward authorization, push schema/retry): **30 passed, 0 skipped, 0 failed**
- Walletless focused subsets ran without provisioning test wallets
- Static checks: Python compilation of edited modules, frontend hook syntax, IDE diagnostics, `git diff --check`

Fleet deploy on 2026-08-09 (`bd2c294f` / v1.33.3): all four validators running the release image with synced chain/indexer, backend APIs returning 200, and payout/outbox schema present.

Primary regression categories: `quest_config`, `quest_assignment`, `fleet_url`, `analytics_identity`, `reward_claim_authz`, `payout_*`, `push_outbox_*`, `runner_accounting`.
