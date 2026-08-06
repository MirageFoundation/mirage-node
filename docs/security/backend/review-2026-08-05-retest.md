# Backend Security Review — Retest of 2026-08-05

**Retest of:** [`review-2026-08-05.md`](review-2026-08-05.md) — the first security review of the Mirage backend, 25 findings (2 Critical, 3 High, 8 Medium, 8 Low, 4 Informational).
**Review baseline:** `dev` at `3ccf8c70` (v1.31.0).
**Retest state:** remediation committed as `b7c8b258` and released as **v1.32.1**; deployed to all four validators at **v1.32.2** on 2026-08-06. Chain-side remediation shipped in the **v1.32.0** consensus upgrade; the backend-only items landed on v1.32.1.
**Scope of this document:** current status of every finding, the evidence for each claim, and the rationale for each item accepted rather than fixed. Where this document and the original disagree about present-day state, **this one is authoritative**; the original is preserved as written, with its line references frozen at its baseline.

> **Count correction.** Earlier planning notes for this retest said "22 findings".
> The review actually contains **25**. The 22 was a transcription of the "22 PoW
> prechecks" figure inside H-3, not a finding count. All 25 are listed here.

---

## Summary

**15 findings fully fixed, 5 partially fixed, 4 accepted risk outright, 1 open informational.** Counting the partial ones by their unfixed half, there are **7 accepted-risk residuals, 5 of them explicit operator decisions**. No finding was closed by re-reading the code and deciding it was fine; each fix below has either a regression test or a verified source change behind it.

The two Critical findings are both closed and both were *verified by reproduction rather than by inspection*, which mattered in each case:

- **C-1** (any account's balance drainable through the public chain endpoint) was fixed in v1.32.0. A local reproduction drained 500 MIRAGE from a third-party account before the fix and is rejected at CheckTx after it.
- **C-2** (concurrent unauthenticated reward claims paid repeatedly) was fixed in v1.32.0, but **its regression test was proving nothing, in two independent ways, until this retest.** That is the most important result here and is written up in full below.

The most substantive new work in v1.32.1 is not a vulnerability fix but the removal of three fail-soft paths (**M-6**) and the documentation of what backend validation is actually worth (**H-3**), because both were making the system's real security posture unreadable.

### The C-2 test was vacuous twice over

The double-pay race was fixed in v1.32.0 with a signature requirement and a per-owner advisory lock. The test guarding it, `reward_claim.no_double_pay`, was green throughout — while never once exercising the race:

1. **It was gated on the unsigned grace period.** The probe fired unsigned claims and ran only `if in_grace`. When the grace period closed, the check stopped running and the suite stayed green. Nothing reported that a check had gone dormant.
2. **It read the wrong field.** It took the quest identifier from `quests[0].get("quest_id")`, but `/api/rewards/summary` emits that field as `id` (`routes/quests.py:503`). So the value was always `None`, the seeding POST was refused with `quest_id required`, and the probe took its "cannot seed" skip branch — *even when the grace period was open*. This alone meant the check had never run since it was written.
3. **Its assertion could not fail.** It asserted `len(paid) <= 1`. Zero payouts — the outcome when payouts are disabled, the pool is unfunded, or seeding failed as in (2) — satisfies it. The one outcome the test existed to detect was indistinguishable from the test not running.

Fixed on all three counts: each concurrent claim is now individually signed with its own nonce (no grace-period dependency), the quest id is read from `id` with a hard failure if absent, and the assertion is `len(paid) == 1` with a distinct diagnostic for the zero case that names the required configuration. Proving it also required the local testnet to actually be able to pay, which it could not: `scripts/reset_local_testnet.py` now provisions a `rewards_pool` key, enables `QUESTS_ENABLED`/`QUESTS_PAYOUTS_ENABLED`/`BACKEND_DEBUG`, and funds the pool from the validator.

Verified: four concurrent signed claims against one seeded reward produce **exactly one** payout, confirmed at the data layer (a single `pending_rewards` row, `claimed_at` set once). Reproduced on two separate owners.

The generalizable lesson — a passing check is not evidence until you have seen it fail — is why **M-3** and **M-8** below were also re-examined rather than taken at their word. M-3 turned out to have the same defect.

---

## Status of All 25 Findings

| ID | Finding (abbreviated) | Status | Shipped |
|----|----------------------|--------|---------|
| C-1 | Relay tx deducts attacker-chosen fee from attacker-chosen `fee.payer` | **Fixed** | v1.32.0 |
| C-2 | `/api/rewards/claim` unauthenticated, pays before marking claimed, no lock | **Fixed**; regression test repaired and now meaningful | v1.32.0 / v1.32.1 |
| H-1 | Four admin endpoints trust a client-supplied address | **Fixed** | v1.32.0 |
| H-2 | User-scoped reads treat `address` as identity | **Fixed** (reclassified) | v1.32.0 |
| H-3 | Backend is not an enforcement boundary but is written as if it were; 22 PoW prechecks silently skipped | **Fixed** (documented + silent skips removed) | v1.32.1 |
| M-1 | `_is_localhost()` trusts `X-Forwarded-For` | **Fixed** | v1.32.0 |
| M-2 | `CLIENT_HASH_SALT` generated per worker when unset | **Fixed** (fails hard) | v1.32.0 |
| M-3 | Invite codes: weak RNG, enumerable owner oracle | **Fixed** (backend v1.32.0; **minting scripts v1.32.1**) | v1.32.0 / v1.32.1 |
| M-4 | `/api/upload_media` unauthenticated, reads whole body before size check | **Partially fixed** — size cap added; auth **Accepted Risk** | v1.32.0 |
| M-5 | Ten dependency advisories; two dead Solana-era packages | **Fixed** | v1.32.1 |
| M-6 | `chain.py` fails soft where the project requires failing hard | **Fixed** | v1.32.1 |
| M-7 | Analytics links browsing identity to a `mirage1` address, no retention bound | **Accepted Risk** (operator decision) | — |
| M-8 | Backend cannot detect wrong indexer data; indexer enforces authz the chain does not | **Partially fixed** — drift detection added; boundary **Accepted Risk** | v1.32.1 |
| L-1 | `stream_proxy` follows redirects, reflects third-party content with `ACAO: *` | **Fixed** | v1.32.1 |
| L-2 | `CORS(app)` allows every origin on every route | **Accepted Risk** (operator decision) | — |
| L-3 | `/api/get_node_config` returns a third-party API key | **Accepted Risk** (operator decision) | — |
| L-4 | Validator and rewards-pool keys use the plaintext `test` keyring | **Accepted Risk** (operator decision) | — |
| L-5 | Fleet peer probing accepts private and link-local IPv4 | **Fixed** | v1.32.1 |
| L-6 | Unvalidated address passed as a positional CLI argument on the payout path | **Fixed** | v1.32.1 |
| L-7 | Push tokens stored in plaintext, prefix logged | **Partially fixed** — logging fixed; at-rest **Accepted Risk** | v1.32.1 |
| L-8 | Full chain parameter set logged at `INFO` on every startup | **Fixed** | v1.32.1 |
| I-1 | Broad `except Exception` blocks in the two route modules | **Partially addressed** | v1.32.1 |
| I-2 | `routes/public.py` is ~9.9k lines, `routes/core.py` ~5.1k | **Open** (informational) | — |
| I-3 | `_require_admin()` is dead code documenting the unsafe pattern | **Fixed** (deleted) | v1.32.1 |
| I-4 | No `MAX_CONTENT_LENGTH`; synchronous workers | **Half fixed** — cap added; sync workers stand | v1.32.0 |

---

## Fixed in v1.32.1 (this remediation pass)

### H-3 — the enforcement boundary is now written down, and no precheck fails silently

The finding was not that a check was missing but that nobody could tell which checks were load-bearing: 22 endpoints wrapped their PoW precheck in `except Exception: pass`, 16 skipped backend signature verification while 13 performed it, and the backend was partly written as though it were the enforcement boundary when `/chain/rest/*` and `/chain/rpc/*` are publicly proxied.

- **[`docs/architecture/backend-trust-model.md`](../../architecture/backend-trust-model.md)** now states the model plainly: the chain ante is authoritative, every backend-side check on a chain write is advisory and exists for fast client feedback, and an advisory check must therefore never be the only thing standing between a request and a state change. `routes/core.py`'s module docstring links to it.
- **`_log_pow_precheck_error(rid, action, exc)`** replaces all 21 remaining `except Exception: pass` bodies in the PoW prechecks. The precheck still does not reject the request — that is deliberate and now documented — but a precheck that throws is no longer invisible.
- **`_client_timestamp(rid, action, data)`** replaces timestamp synthesis. The backend previously substituted `now` when a client omitted a timestamp, putting an `envelope_timestamp` on the wire that the client never signed. The chain caught it as `invalid relay signature`, so nothing was accepted, but the failure was misattributed to the signature rather than the missing field. It now forwards the client's value or `0` and logs the absence, and the chain reports `envelope_timestamp is required`.

Three `except Exception: pass` blocks remain in `routes/core.py` (lines ~4053, ~4303, ~4954). All three are post-commit best-effort work — user-action logging and an inbox cache bump — that runs after the transaction has already succeeded and must not fail the response. They are not prechecks and are counted under I-1, not H-3.

### M-6 — three fail-soft paths removed

`AGENTS.md` requires failing hard, and `chain.py` did the opposite in the three places where it mattered most: a dead indexer DB was reported as a healthy-but-syncing node, and difficulty defaulted to zero.

A new `IndexerUnavailable` exception (`error_utils.py`) is raised instead of a plausible default by `is_node_catching_up`, `get_indexer_health`, and `get_difficulty_info` (which also rejects a row missing any required key, rather than treating a partial write as real state). `safe_error` maps it to **503 `indexer_unavailable`**, and `_classify_exception` reads the live exception via `sys.exc_info()` so the mapping holds at all 30 of its call sites in `routes/core.py` — each of which sits inside a broad `except Exception` — without editing any of them.

Why 503 and a distinct code: the failure it replaces was *indistinguishable from `node_catching_up`*, so an outage looked like ordinary startup lag to every client and dashboard.

Regression: `tests/test_backend.py --category indexer_fail_hard` — 4 checks, monkeypatching `connect_db` to raise, asserting each function raises rather than returns, plus the 503 classification.

### M-3 — the minting scripts, which the backend test could not see

The backend half was fixed in v1.32.0: `_generate_invite_code` (`reward_distributor.py:71`) uses `secrets`, and the enumeration oracle is closed — `get_invite_codes` requires a signed read and validation no longer returns the owner.

But the generators an operator actually runs to mint codes were still using `random.choices`: `scripts/manage_invites.py` (tracked) and `scripts/onboard_influencer.py` (present locally, gitignored via `.gitignore:73`). The guard test only walked `web/backend/`, so it confirmed the already-fixed copy and never saw the live ones — the same "green but not looking" failure as C-2. Invite codes are bearer credentials for account creation and the keyspace is only 32⁸ ≈ 1.1e12, so entropy quality is the entire defense.

Both now use `secrets.choice`. `invite_code.script_crypto_rng` extends the hygiene test to cover them; it passes, and it was verified to **fail** against a deliberately reverted generator. The check skips per-file when a script is absent, so it stays valid in a clean checkout where the gitignored one does not exist — and if neither is present it skips rather than reporting a pass it did not earn.

### L-1, L-5, L-6, L-7, L-8, I-3

- **L-1 `stream_proxy`:** the video UID and path are charset-validated (`_STREAM_UID_RE`, `_STREAM_PATH_RE`, explicit `..` rejection), query parameters are filtered against an allowlist with drops logged, and **`allow_redirects=False`**. The redirect was the real issue: the response body is reflected with `Access-Control-Allow-Origin: *`, so following an upstream redirect would let `videodelivery.net` aim the proxy at any host.
- **L-5 peer probing:** `_peer_endpoint` now requires `ipaddress.ip_address(ip).is_global`. The old shape-only regex accepted `10.x`, loopback and link-local, turning a peer list containing `169.254.169.254` into an outbound probe of the host's own network from inside the container.
- **L-6 payout argv:** `is_valid_mirage_address()` bech32-validates the recipient in both `send_reward` and `_send_tokens_via_cli` before it can reach a `miraged` argv list as a positional argument.
- **L-7 push token logs:** `_token_fingerprint()` logs a truncated SHA-256 instead of a token prefix. Tokens remain plaintext at rest — see Accepted Risk.
- **L-8:** the full parameter set moved to `debug`; startup logs the count at `info`.
- **I-3:** `_require_admin()` deleted, along with `_is_admin()`, which it orphaned.

### M-5 — dependencies

`Flask` → `>=3.1.3`, `Flask-CORS` → `>=6.0.0` (7 of the 10 advisories were here, and these were the only two packages pinned with exact `==`). `pynacl` and `base58` — Solana-era leftovers, imported nowhere — removed.

`scripts/audit_python_deps.sh` runs `pip-audit` and documents the two remaining advisories as accepted with per-advisory reasoning rather than suppressing them: `ecdsa` `PYSEC-2026-1325` (a timing side-channel in a code path this project does not use) and `pynacl` `PYSEC-2026-3002` (reachable only via a `cosmpy` transitive pin, in libsodium functions unrelated to our ed25519 use).

### M-8 — drift detection, narrowly

The architectural half stays accepted (below). What was actionable is detection: `indexer_drift` previously compared exactly one value (`pow_base_bits`). It now also compares **profile level, username, and balance** for a provisioned wallet against direct chain queries, with bounded retries to absorb ordinary indexer lag. 4 checks, all passing.

---

## Accepted Risk

Seven residuals, five of them explicit operator decisions recorded during remediation planning: those fixes would change client or operator behaviour, and that cost was judged higher than the residual risk. None of these is closed, and each is stated with what would actually go wrong.

### M-4 (auth half) — `/api/upload_media` stays unauthenticated
Requiring a signed envelope would break every existing client's upload path. The body-size half **is** fixed: `MAX_CONTENT_LENGTH` is set globally (`factory.py:54`, `max_video_bytes() + 16MB`), so Flask rejects oversized bodies before a handler reads them, and Caddy's `upload_limit` zone is no longer the only bound. **Residual:** anonymous upload capacity remains, rate-limited only at the edge.

### M-7 — analytics identity linkage
Permanently associating a pseudonymous browsing identity with a `mirage1` address, with no retention bound, is what makes the product's own analytics work. **Residual:** this is a privacy exposure, not a compromise — it is a deanonymization surface for anyone with DB access, and it grows without bound. Revisit alongside any retention policy.

### L-2 — `CORS(app)` on every route
Tightening origins risks breaking the frontend and third-party clients. Consequence is limited because the API has no cookies or sessions: there is no ambient credential for a hostile origin to ride. **Residual:** any origin can read any unauthenticated endpoint from a victim's browser.

### L-3 — Giphy key in `/api/get_node_config`
Proxying Giphy server-side was declined. **Residual:** the key is public and can be used up to its quota by anyone; rotation is the only remedy if abused.

### L-4 — `test` keyring backend
Consistent with the blockchain review's acceptance. The web process runs alongside plaintext validator and rewards-pool keys. **Residual:** any backend RCE or arbitrary file read is an immediate key compromise. This is the largest accepted risk in the set, and the honest reason it is accepted is operational cost, not low severity.

### L-7 (at-rest half) — push tokens in plaintext
Log leakage is fixed; the stored values are not encrypted. **Residual:** DB access yields the ability to push to users' devices.

### M-8 (boundary half) — the indexer enforces authorization the chain does not
Treated as the documented, accepted architecture it is described as. **Residual:** delete and edit visibility depends on the indexer behaving; a node running a modified indexer can serve content the chain never authorized as hidden, and the backend has no way to notice. Drift detection now covers accidental divergence, not a hostile indexer.

---

## Open — Informational

- **I-1:** `routes/core.py` has 38 bare `except Exception:` and 75 named; `routes/public.py` has 38 bare and 56 named; 16 still end in a silent `pass` (13 in `public.py`, 3 in `core.py`). The 21 PoW-precheck cases from H-3 are gone. No further consolidation attempted — this is a readability and diagnosability concern, not a vulnerability.
- **I-2:** `routes/public.py` 9,930 lines, `routes/core.py` 5,149. Unchanged in kind.
- **I-4 (second half):** `worker_class = "sync"` stands. An availability consideration, not a vulnerability.

---

## Verification Performed

All against local Docker (`127.0.0.1`) on the retest state. Production was not contacted for this retest; see the disclosure note in the original review's Assumptions for the one read-only request made during v1.32.1 remediation.

```bash
# 50/50 — includes the repaired C-2 probe and the four admin-authz checks
python tests/test_backend.py --category security,admin_authz,reward_claim_authz,indexer_drift,indexer_fail_hard

# 3/3 — includes the new script-RNG guard
python tests/test_backend.py --category invite_code_hygiene
```

- `reward_claim.no_double_pay` — passing, on two separate owners, with `paid == 1` of 4 concurrent signed claims. Cross-checked in `mirage_backend`: one `pending_rewards` row, `claimed_at` set once.
- `admin_authz` — 4/4, one per H-1 endpoint.
- `indexer_fail_hard` — 4/4 (`is_node_catching_up`, `get_indexer_health`, `difficulty_no_row`, `classified_503`).
- `indexer_drift` — 4/4 (`pow_base_bits`, `profile_level`, `profile_username`, `balance`).
- `invite_code_hygiene` — 3/3, and the new script check was confirmed to **fail** against a deliberately reverted generator, so it is known to be capable of failing.
- Both invite-minting scripts import cleanly and emit well-formed codes after the `random` → `secrets` change.
- Local testnet provisioning (`enable_local_quests_payouts`, `fund_local_rewards_pool`) executed end to end: key created, `backend.env` patched, pool funded, quests served.

**Not verified:** nothing in the Accepted Risk section, by definition. `MAX_CONTENT_LENGTH` was confirmed set by source inspection, not by submitting an oversized body.

---

## Follow-up

1. **L-4 is the item to revisit first.** It is accepted for operational reasons, not because it is minor; it converts any backend file-read bug into key compromise.
2. **Audit for other dormant checks.** C-2 and M-3 both had tests that were green while watching nothing, for different reasons — a closed grace period, a wrong field name, an assertion satisfied by non-execution, and a source scan pointed at the wrong directory. The suite's remaining source-level guards deserve the same treatment: confirm each can fail.
3. **M-7 needs a retention decision**, not a code change.
4. Re-run `scripts/audit_python_deps.sh` at each release; it fails on any advisory not explicitly accepted in the script.
