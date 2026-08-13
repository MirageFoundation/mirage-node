# Blockchain Security Review — 2026-08-06

**Scope:** `blockchain/` — all tracked Go/proto/module files, including app/ante handlers, core module, keeper, types, params, genesis, upgrade handlers, the two vendored consensus-critical forks under `blockchain/patches/`, and security-relevant tests. The orchestrator package is confirmed absent (removed with the bridge).
**Out of scope:** `web/`, `indexer/`, `deploy/`, `scripts/`, external Solana programs, production servers. Ops-layer tooling is referenced where a blockchain-side design choice depends on it, but is not itself audited. The backend C-1 finding is cited only for the chain-side remediation that closed it.
**Baseline:** `dev` at `589133443eac331fed67321902ef0e9ca353b456` (`v1.32.4`). `prod` tip is `d628eec6` (`v1.32.3`); the only `blockchain/` delta between `prod` and this baseline is a one-line comment edit in `app/upgrades.go` plus the version-bump commit. Working tree clean under `blockchain/`.
**Previous review:** [`2026-08-04/blockchain-review.md`](../2026-08-04/blockchain-review.md) (baseline `v1.30.0`) and its authoritative retest [`2026-08-04/blockchain-retest.md`](../2026-08-04/blockchain-retest.md) (`prod` `870afabd`, `v1.32.2`). This cycle re-audits the full tree after that remediation wave plus the v1.32.0–v1.32.1 C-1 / fee-ceiling work.

> **Relationship to the Aug 4 retest.** The retest recorded remediation status for the
> prior 23 findings. This document is a new full audit, not another retest. Prior
> findings that remain open are re-stated with current evidence; closed findings
> appear in the Prior Finding Status table and are not re-argued unless the
> property drifted.

---

## Executive Summary

Full re-audit of `blockchain/` at 43 tracked non-test Go/proto files outside patches (74 including generated and tests), plus 145 Go files across the two vendored forks. Reviewed transaction admission (ante router, both ante chains, C-1 gas-payer consent, PoW, envelope signatures), core message handlers, BeginBlock/EndBlock, mint distribution, subscription accounting, delete-user state cleanup, all 44 registered upgrade handlers, and the vendored IAVL and store/v2 patches.

**The defining event since the Aug 4 baseline is not a new divergence — it is that the Aug 4 remediations largely landed, and a Critical fee-drain (C-1) was discovered and closed in the same window.** Fifteen of twenty-three Aug 4 findings are Fixed, two Documented, one Partially fixed, three Accepted Risk, and two remain open (I-1 co-location, L-8 ante-switch half). Separately, the backend review found that relay transactions named an attacker-chosen `fee.payer` with no outer signature; v1.32.0 added `SigVerification` before `DeductFee` on the relay ante chain, and v1.32.1 correctly removed a fee ceiling that made large legitimate relay txs unpayable. That authorization fix holds under this review.

**What this cycle found that the remediations did not close** is concentrated in fail-fast gaps on consensus *writes* — the June sweep covered consensus *reads* thoroughly, and several write paths that move or gate state still log-and-continue:

1. **Subscription index writes still log-and-continue after bank value has moved.** Both EndBlock renewal and `MsgSubscribe` can burn/escrow fees, then discard `SetSubscription` errors and still succeed. A node-local write failure produces asymmetric index vs bank/profile state — the same silent-divergence class the June fail-fast sweep was built to eliminate. See **M-1**.
2. **Tier-cap counters silently default on store-read failure.** `countSetEntries` and the count bumps inside `addSetEntry` / `addOrderedEntry` / `addDequeEntry` discard `store.Get` errors and treat them as zero, which fail-opens hard caps (follows, agents, topics). See **M-2**.
3. **`DeleteUserState` fail-opens on profile reload and subscription removal** (username / sub-index orphans). See **M-3**.

Unused prepaid reserve left in the core module on delete was examined and **is not treated as a finding** — reserve is non-refundable prepaid gas, not withdrawable balance; spendable is already swept correctly. See **I-7**.

No new privilege-escalation, signature-bypass, or unauthorized-mint vector was found. `GovAuthorityDecorator`, envelope replay protection, C-1 outer-sig consent, M-1 ante ordering, and the Aug 4 halt→`os.Exit(1)` conversion all hold. Bridge code is gone by construction.

**Ship blockers:** None. **Nothing in this review warrants a dedicated release.** Every Medium below is contingent on a node-local store read or write failing mid-path; see [Urgency Assessment](#urgency-assessment--nothing-here-is-a-this-month-fix).

---

## Findings

### M-1: Subscription Index / Profile Saves Log-and-Continue After Value Has Moved (Medium)

**Location:** `x/core/module/module.go` lines 1022–1025 and 1065–1076 (`processSubscriptions`); lines 3398–3421 and 3473–3491 (`Subscribe` gift and self paths).

Two paths move bank value and then treat the matching index/profile write as best-effort.

In `processSubscriptions`, after a successful renewal burn + escrow, `SetSubscription` errors are logged only. Marshal failure `continue`s without restoring the already-removed index. `SetProfileCore` failure is logged and ignored. The old index was already removed at lines 894–896 (that removal correctly fails closed).

In `MsgSubscribe`, fee burn/escrow succeeds, `RemoveSubscription` is discarded with `_ =`, `SetSubscription` failure is logged, and the handler still marshals and saves the profile and returns success.

**Impact:** Node-local store write failure → one validator has a subscription index (or an updated profile) that its peers lack → EndBlock renewal/expiry mutates different state → app-hash divergence. Deterministic write failure → paid user with burned fees and no expiry index (stranded paid tier until something else touches the profile). Same silent-divergence family as the June incident class.

**Remediation:** Propagate `SetSubscription`, marshal, and `SetProfileCore` errors from both paths. On the user-tx path, reject the transaction so bank + profile + index stay atomic. On the EndBlock path, return the error so the block fails closed (consistent with the decode fail-fast contract already documented on `processSubscriptions`).

---

### M-2: Tier-Cap Counters Silently Default to Zero on `store.Get` Error (Medium)

**Location:** `x/core/keeper/keeper.go` lines 354–356, 374–375, 394–397 (`addSetEntry` / `removeSetEntry` / `countSetEntries`); lines 467–477 and 554–565 (`addOrderedEntry` / `addDequeEntry` seq and count bumps). Cap checks at `module.go:2144`, `2703`, `2852`.

The June fail-fast sweep converted consensus-path readers to halt on raw `store.Get` errors. The unordered/ordered/deque helpers were not included. `countSetEntries` discards the error and returns `getUint32(nil) == 0`. The write paths that bump the count do the same: a failed read is treated as zero, then `0+1` is written.

Those counts gate hard caps for followed users, followed topics, and enabled agents. A node that reads an error where peers read a real count will admit follows past the tier limit, rewrite the count key, and diverge.

**Impact:** Fail-open on tier limits under node-local read failure; count-key corruption; app-hash divergence. Same class as Aug 4 M-3 (`GetRelayCredit`), which was fixed precisely because silent zero defaults feed consensus state.

**Remediation:** Propagate `store.Get` errors from count/seq helpers (return error from `Count*` / `Add*` APIs). Never treat a Get error as an empty count when writing. Extend the consensus-read panic/halt tests to cover count keys.

---

### M-3: `DeleteUserState` Fail-Opens on Profile Reload and Subscription Removal (Medium)

**Location:** `x/core/keeper/keeper.go` lines 2275–2280 and 2335–2338.

The handler already successfully loaded and decoded the profile (`module.go:3018–3029`), then `DeleteUserState` reloads it with discarded Get/unmarshal errors and discards `RemoveSubscription` errors:

```2275:2280:blockchain/x/core/keeper/keeper.go
	if bz, found, _ := k.GetProfileCore(ctx, addr); found {
		var core types.ProfileCore
		if err := json.Unmarshal(bz, &core); err == nil {
			username = core.Username
			subscriptionExpiry = core.SubscriptionExpiry
		}
	}
```

If the reload fails open, the profile KV is still deleted while the username mapping and/or subscription index may remain. A leftover `subs/{expiry}:{addr}` entry later hits `processSubscriptions`' missing-profile `CONSENSUS_FATAL`. A node-local `RemoveSubscription` failure diverges immediately.

**Impact:** Orphan username/subscription index entries; delayed consensus halt; divergence on node-local delete failure.

**Remediation:** Pass username / expiry from the handler into `DeleteUserState` (avoid the second load), or fail closed on Get/unmarshal. Propagate `RemoveSubscription` errors.

---

### M-4: `SubscriptionPeriod == 0` Short-Circuit Skips Reserve Burn and Tier Downgrade (Medium)

**Location:** `x/core/module/module.go` lines 916–918; param semantics in `types/params.go:164–165` and `params.pb.go:246–247`.

`SubscriptionPeriod == 0` means “one-time payment.” New subscriptions under period 0 set `newExpiry = 0` and do not index. The EndBlock short-circuit exists so a corrupt profile on an indexed one-time row still fail-fasts (Aug 4 M-7, Fixed). After a successful decode, however, `continue` skips leftover-reserve burn and level downgrade:

```916:918:blockchain/x/core/module/module.go
		// One-time payment: index already removed; profile must still decode.
		if params.SubscriptionPeriod == 0 {
			continue
```

If governance sets `SubscriptionPeriod` to 0 while indexed paid subscriptions still exist, each expiry removes the index and leaves `Level` and `ReserveFunds` untouched forever (until an unrelated path burns the reserve). The paid tier becomes permanent and the escrow remains attributed only until some other burn path runs.

**Impact:** Governance footgun: a param change can freeze paid tiers and strand reserves. Not reachable under the default 43200-minute period without a params update.

**Remediation:** After decode, always burn leftover reserve and clear paid fields when not renewing — including the period-0 path. Keep the decode-before-continue ordering that closed M-7. Add a test: indexed paid sub + `SubscriptionPeriod=0` → on expiry, reserve burned and level 0.

---

### M-5: BeginBlock/EndBlock Comments Claim Node-Local Write Failures “Affect ALL Nodes Equally” (Medium)

**Location:** `x/core/module/module.go` lines 644–648 (BeginBlock) and 756–760 (EndBlock).

Both comments justify log-and-continue on `SetCurrentDifficulty`, `ClearPoWWindow`, `PruneExpiredNonces`, `SetConsecutiveLowUsage`, fee-collector burn, etc., by asserting those failures “affect ALL nodes equally (same operation, same in-memory state) and so do not cause divergence.”

That is true for deterministic logic bugs. It is false for node-local `store.Set` / `store.Delete` errors (disk, Pebble, transient IAVL). One node logging-and-continuing while peers commit the write is exactly the May/June divergence shape. The comments actively steer maintainers away from fail-fast on the class already treated as `CONSENSUS_FATAL` for reads and for `RecordRecentBlockHash`.

Concrete discards that inherit this rationalization include `ClearPoWWindow`'s `_ = store.Delete` (`keeper.go:2036`), secondary writes in `SetCurrentDifficulty` (`keeper.go:2104`, `2107`), and EndBlock calm-reset `_ = SetConsecutiveLowUsage` (`module.go:877`).

**Impact:** Documentation-driven contract drift. Not an exploit by itself; it is why M-1/M-2-class gaps keep shipping.

**Remediation:** Rewrite the comments to distinguish deterministic vs node-local failure. For consensus inputs (difficulty, PoW window counts, calm sequence), propagate write errors or halt. Leave only ADR-documented mint/admin exceptions on log-and-continue.

---

### L-1: `updateProfileCore` / `SetUsername` Discard Profile Get and Unmarshal Errors (Low)

**Location:** `module.go:1805–1807`, `1931–1933`, `1951`; similar `found, _` patterns at `2711`, `2859`.

Corrupt or unreadable profile bytes are treated as empty core; `ReleaseUsername` errors are discarded before reclaim. Elsewhere (DeleteUser, processSubscriptions, requireUsername) decode failures fail closed. This path can overwrite unreadable state or orphan a username mapping on one node.

**Remediation:** Propagate Get/Unmarshal/`ReleaseUsername` errors; do not synthesize an empty profile over a read failure.

---

### L-2: `ClearPoWWindow` Discards Delete Errors (Low)

**Location:** `keeper.go:2034–2037`, called from EndBlock after difficulty changes.

Partial clears leave different per-height counters across nodes, which feed the next difficulty decision. Sibling of M-5.

**Remediation:** Propagate delete errors (collect-then-delete, matching `ResetAllRelayCredits`).

---

### L-3: `SetCurrentDifficulty` Discards Previous-Difficulty and Last-Change-Height Writes (Low)

**Location:** `keeper.go:2104`, `2107`.

Current difficulty Set is checked; the two accompanying keys are `_ =`. Grace-window / query fields can desync from `current_difficulty` on a single node.

**Remediation:** Propagate both secondary write errors.

---

### L-4: Reserve Basis-Point Conversion Still Multiplies `float64` (Low)

**Location:** `module.go:977`, `3366` (`uint64(params.SubscriptionReservePercent * 10000)`).

Comments claim integer math; the conversion into basis points still uses float multiply. Default `0.95` truncates cleanly; other `[0,1]` governance values can under-escrow by 1 bps. Homogeneous amd64 fleets will agree; this is residual L-1-family exactness debt, not a live divergence.

**Remediation:** Store reserve as integer basis points in params, or round with an explicit fixed-point helper.

---

### L-5: Relay Ante Switches Still Hand-Maintained (Low — Aug 4 L-8 Carryover, Impact Reduced)

**Location:** `app/relay_messages.go:9–45`, `relay_messages_test.go:12–33`, `ante_pow.go` / `ante_metasig.go` switches.

Registry, `isRelayMessage`, PowDecorator, and RelaySigDecorator all cover the same **25** types today. `TestRelayMessageRegistryParity` still only pins registry ↔ `isRelayMessage`. Both ante switches now **fail closed** on unknown types (`ante_pow.go:851–852`, `ante_metasig.go:898–899`), so omitting a type from a switch rejects rather than skipping PoW/sig. The residual bypass class is the opposite mistake: a new envelope-bearing `Msg*` left out of the registry routes via `stdAnte` (SDK sig on authority only). Only intentional gov-only `MsgSetLevel` sits outside the registry today.

**Remediation:** Extend the parity test to assert both switches handle every registry entry, or generate the switches from the registry. Optionally assert every `EnvelopePubkey`-bearing message is either registered or explicitly allowlisted as gov-only.

---

### L-6: `ProcessProposal` Performs Minimal Validation Only (Low — Accepted Risk Carryover)

**Location:** `app/app.go` `ProcessProposal`.

Unchanged by choice (Aug 4 L-6). Mitigated by M-1 ordering (sig before PoW) and C-1 (outer sig required). Still a proposer can force peers through full DeliverTx ante work.

**Remediation:** None required while accepted; otherwise run a cheap ante subset in `ProcessProposal`.

---

### L-7: Stale PoW Commentary and Unused `PowDecorator.MinFee` (Low)

**Location:** `ante_pow.go:42–46`, `228–229`, `1435`; constructed zero in `ante_relay_chain.go:62–64`.

Struct comment still implies CheckTx may skip `last_block_hash`; the runtime path always validates when `LastBlockId` is non-empty, with hash check before Argon2 (M-1 Fixed). `MinFee` is documented as a PoW-skip path but never read. Empty `LastBlockId` still skips the hash membership check (early/genesis window only).

**Remediation:** Fix the comment; remove `MinFee` or implement and test it; consider rejecting empty hash outside an explicit bootstrap height.

---

### I-1: Validator / Query-Load Co-Location Remains Open (Informational — Carryover)

Unchanged since the Aug 4 retest. Confirmed co-located on all four hosts during the v1.32.2 deploy (2026-08-06). Highest-value open prevention item for the unrooted divergence class; outside `blockchain/` scope.

---

### I-2: `upgrades.go` Still a Single 2 259-Line / 44-Handler File (Informational — Carryover)

Essentially unchanged vs retest (was 2 260 / 44). Maintenance and auditability concern only.

---

### I-3: Genesis `raw_state` Remains a Full Trust Anchor (Informational — Accepted Risk)

Unchanged. Halt on bad params is now a clean `os.Exit` rather than a zombie (H-1 Fixed). InitGenesis still soft-defaults some zero fields and ignores some `GetProfileCore` errors on `initial_profiles` (`module.go:525–527`, `:564`) — genesis-only, trusted input.

---

### I-4: Edit / Delete Authorization Remains Indexer-Enforced (Informational — Accepted Risk)

Unchanged. Chain accepts `MsgEdit` / `MsgDelete` from any relay-authenticated user for arbitrary targets; indexer agreement is the moderation boundary. Documented in handler comments.

---

### I-5: Historical Bridge Burn Audit Still Unanswered (Informational — Carryover)

Bridge removed in v1.31.0. Whether any mainnet `MsgBridgeBurn` destroyed funds that were never minted on Solana before removal is still not recorded. Prevention is complete; historical loss is unknown.

---

### I-6: No Ante Fee Magnitude Ceiling After C-1 (Informational — By Design)

v1.32.0 added a ceiling; v1.32.1 removed it because it crossed the CheckTx floor and made large relay txs unpayable. `DeductFee` uses the SDK default floor only. The gas payer has signed the SignDoc (fee amount, gas, payer). Residual risk is self-drain of the consenting payer key (validator/backend), not third-party drain. `relay_max_gas_fee` still caps paid-user **reserve** deduction. Rationale is recorded on `relayAnteDecorators` (`ante_relay_chain.go:27–37`).

---

### I-7: Unused Prepaid Reserve Remains in the Core Module on Delete (Informational — Accepted Risk)

**Location:** `x/core/keeper/keeper.go` `DeleteUserState` (no `BurnFromModuleAmount` of `ReserveFunds`); contrast expiry / re-subscribe paths that do burn leftover reserve.

Examined as a candidate High and **rejected**. `ReserveFunds` is prepaid relay gas escrowed into the core module at subscribe time — not user-withdrawable balance. On delete, spendable bank coins are swept to the community pool (correct). Leaving unused prepaid gas in the module does not steal from the user, does not break the supply invariant, and leaves the module *over*-backed relative to remaining profile liabilities (safe for `CORE_MODULE_SHORT_BURN`). Expiry burning leftover reserve is accounting hygiene for live subscriptions; on account deletion the prepaid gas is simply unused protocol escrow. No remediation required unless product policy later wants an explicit burn-on-delete for supply cosmetics.

---

## Prior Finding Status

| Prior finding | Current status |
| :--- | :--- |
| 2026-08-04 H-1 — CONSENSUS_FATAL zombies | **Fixed (holds).** Zero panic sites in keeper/IAVL; `os.Exit(1)` halt; inventory test; params validated at `UpdateParams`. |
| 2026-08-04 H-2 — Bridge dormancy / burn | **Fixed (holds).** Bridge deleted; ante rejects surviving msgs; burn-record audit still unanswered (I-5). |
| 2026-08-04 M-1 — PoW before sig / hash | **Fixed (holds).** RelaySig before Pow; hash before Argon2; order test present. **Benchmark still absent.** |
| 2026-08-04 M-2 — Supply full scan cost | **Fixed (holds).** Delta + full scan; timed every 1000 blocks. |
| 2026-08-04 M-3 — GetRelayCredit silent zero | **Fixed (holds).** |
| 2026-08-04 M-4 — RelayAccountingDecorator | **Fixed (holds).** Decorator removed; handler accounting propagates errors. |
| 2026-08-04 M-5 — Ante downgrade wedge | **Fixed (holds).** Mutation deleted from ante. **Wedged-user regression test still absent.** |
| 2026-08-04 M-6 — Reserved-profile bootstrap | **Fixed (holds).** Sentinel + propagated errors. **Idempotence test still absent.** |
| 2026-08-04 M-7 — processSubscriptions short-circuit | **Fixed (holds)** for decode ordering. Residual period-0 burn/downgrade gap is **M-4** this cycle. |
| 2026-08-04 M-8 — Patch provenance | **Fixed (holds).** `PATCHES.md`, `check_patches.sh`, govulncheck covers both modules. |
| 2026-08-04 M-9 — Mint log-and-continue | **Documented (holds).** ADR unchanged; code deliberately unchanged. |
| 2026-08-04 L-1 — float Pow | **Fixed (holds).** `big.Rat` + determinism table. Residual float→bps is **L-4**. |
| 2026-08-04 L-2 — ResetAllRelayCredits | **Fixed (holds).** |
| 2026-08-04 L-3 — Store deletion phases | **Documented (holds).** |
| 2026-08-04 L-4 — RecordPoWMessage swallow | **Fixed (holds).** |
| 2026-08-04 L-5 — malformed pubkey | **Fixed (holds).** |
| 2026-08-04 L-6 — ProcessProposal | **Accepted Risk (holds).** Restated as L-6. |
| 2026-08-04 L-7 — routePoWTx log level | **Fixed (holds).** |
| 2026-08-04 L-8 — relay allowlist parity | **Partially fixed (holds).** Restated as L-5; fail-closed defaults reduce impact. |
| 2026-08-04 I-1 — co-location | **Not Started.** Restated as I-1. |
| 2026-08-04 I-2 — upgrades.go size | **Not Started.** Restated as I-2. |
| 2026-08-04 I-3 — raw_state | **Accepted Risk.** Restated as I-3. |
| 2026-08-04 I-4 — indexer delete authz | **Accepted Risk.** Restated as I-4. |
| Backend C-1 — fee.payer drain | **Fixed (v1.32.0, holds).** Chain ante requires outer sig before DeductFee; integration tests `c1.*`. |

---

## Positive Security Controls Observed (this cycle)

- **C-1 gas-payer consent is correctly implemented.** Relay ante order is `SetPubKey → SigGasConsume → SigVerification → DeductFee → RelaySig → Pow`, pinned by `TestRelayAnteDecoratorOrder`. SignDoc covers fee amount/gas/payer. The v1.32.1 ceiling removal is justified and documented in-code so it is less likely to return.
- **Aug 4 H-1 halt remediation holds.** Nineteen keeper `HaltErr` sites plus the IAVL prune-hole twin; inventory test forbids `panic(…CONSENSUS_FATAL…)`.
- **GovAuthorityDecorator** still closes gov-authority spoofing on both ante paths; mint/burn remain governance-only in handlers.
- **Envelope replay protection** remains fail-closed (nonce > 0, HasEnvelopeNonce halts on store error, SetEnvelopeNonce rejects on write failure, timestamp window).
- **Bridge removal is structural.** No handlers, no orchestrator binary, ante hard-reject, prefix cleanup in v1.31.0 upgrade, tests pin both.
- **Supply invariant pair** (delta + full scan) retained by design with instrumentation.
- **Patch posture** matches what M-8 asked for: provenance file, CI drift check, govulncheck on both replacement modules (both clean this run).
- **Fail-closed ante defaults** on unknown relay message types improve L-8 residual risk vs Aug 4.
- **Params.Validate** rejects NaN/Inf on float-backed economics fields; `UpdateParams` validates before write.

---

## Test Coverage Gaps

| Gap | State |
|-----|-------|
| PoW per-envelope benchmark | **Open** (carryover) |
| M-5 wedged-user regression | **Open** (carryover) |
| M-6 bootstrap idempotence | **Open** (carryover) |
| L-8 ante-switch ↔ registry parity | **Partial** (carryover) |
| Subscribe / processSubscriptions index write failure | **Open** (new — M-1) |
| Count-key store.Get error injection | **Open** (new — M-2) |
| SubscriptionPeriod=0 expiry burns reserve | **Open** (new — M-4) |

---

## Urgency Assessment — Nothing Here Is a This-Month Fix

Recorded explicitly so this document is not read as a work queue. The findings above are real and correctly classified, but **none of them justifies a dedicated release, and none should displace product work this month.**

Every Medium in this cycle shares one precondition: a **node-local `store.Get` / `store.Set` / `store.Delete` failure in the middle of a specific path**. On a healthy Pebble/IAVL node that does not happen in isolation, and when the store *is* failing that way the node is already in divergence-recovery territory, where these paths are not the thing that saves it. None is an exploit path, none is reachable by an unprivileged attacker on demand, and none is the next C-1 — C-1 was an authorization hole reachable from the public internet with no preconditions, which is the bar that earns an out-of-band release.

| ID | Fix this month? | Rationale |
| :--- | :--- | :--- |
| M-1 — subscription writes log-and-continue | No | Requires a write to fail *after* a successful burn, on one node only. Ugly accounting, not urgent. |
| M-2 — count fail-open | No | Absent key → 0 is correct and normal; only the *error* branch is wrong, and it is rare. |
| M-3 — `DeleteUserState` fail-open | No | Delete is a low-frequency path and the handler already decoded the same profile in the same tx. |
| M-4 — `SubscriptionPeriod == 0` | No | Only reachable if governance sets the period to 0. Treat as "don't do that" until someone proposes it. |
| M-5 — misleading fail-fast comments | No | A maintainer trap, not a defect. Fix in passing. |
| L-1 – L-7 | No | Hygiene, accepted risk, or "pin it when you next add a relay message". |
| I-7 — reserve left on delete | No | Correctly accepted; prepaid gas is not user-withdrawable balance. |
| I-1 — validator/query co-location | Only item worth scheduling | Still the strongest correlate of every divergence and prune-hole to date — and it is ops work, not chain code. |

**Recommended posture:** carry M-1 through M-5 as backlog and pick them up opportunistically when a release is already touching those files. The Prioritized Recommendations below are ordered by value *within that backlog*, not by urgency.

---

## Prioritized Recommendations

Ordering is relative priority within the backlog, per the Urgency Assessment above — not a schedule.

1. **Fail closed on subscription index/profile writes after value moves (M-1).** Same for `RemoveSubscription` on the subscribe path.
2. **Fail-fast count/seq store reads (M-2).** Extend the consensus-read test family.
3. **Harden `DeleteUserState` error handling (M-3)** — propagate reload / `RemoveSubscription` failures.
4. **Burn + downgrade on period-0 expiry path (M-4)** while keeping decode-before-continue.
5. **Correct BeginBlock/EndBlock fail-fast comments and close the write discards they excuse (M-5, L-2, L-3).**
6. **Finish L-8** — pin ante switches to the registry (L-5).
7. **Add the three missing Aug 4 tests** (PoW benchmark, wedged user, bootstrap idempotence).
8. **Answer the historical bridge-burn question (I-5)** and keep pushing I-1 isolation.

---

## Verification Performed

- Inventoried tracked `blockchain/` source: 43 non-test Go/proto files outside patches; 74 Go+proto including generated/tests outside patches; 145 patch Go files; `upgrades.go` 2 259 lines / 44 `SetUpgradeHandler` registrations.
- Diffed `blockchain/` against Aug 4 review baseline `1d3ab707` and against retest baseline `870afabd` (post-retest delta is a comment-only upgrades.go edit).
- Re-verified Aug 4 Fixed findings against current source (halt helper, bridge absence, ante order, supply pair, GetRelayCredit, sentinel bootstrap, PATCHES.md, big.Rat difficulty, etc.).
- Mechanically counted relay registry (25) and confirmed fail-closed defaults on ante switches.
- Traced `DeleteUserState`, `processSubscriptions`, `Subscribe`, set/deque count helpers, C-1 ante chain, and fee-ceiling removal rationale.
- `go build` / `go vet` over `./app/... ./x/core/... ./consensusfatal/...` — clean (golang:1.25 container, repo root mounted).
- `go test ./app/... ./x/core/... ./consensusfatal/...` — all pass.
- `go test ./...` in `patches/iavl` — pass.
- `go mod verify` — "all modules verified" (still silently skips `replace` modules; provenance via `PATCHES.md`).
- `make govulncheck` — both patch modules: no vulnerabilities. Main module: **two reachable advisories unchanged** from the Aug 4 post-remediation scan:
  - `GO-2026-5932` — OpenPGP via SDK keyring CLI (production uses `test` backend).
  - `GO-2026-4479` — Pion DTLS via CometBFT optional libp2p/WebRTC (`[p2p.libp2p] enabled=false`).
  Unreachable import/require advisories also reported (`GO-2024-2584`, `GO-2026-5841`, `GO-2025-3442`, `GO-2023-1881`, `GO-2023-1821`) — not in reachable symbol results for Mirage code.

---

## Assumptions

- Production servers were not contacted for this review. I-1 co-location status is inherited from the Aug 4 retest's 2026-08-06 fleet inventory, not re-swept.
- Validators are honest-majority for governance assumptions.
- Indexer authorization for edit/delete visibility remains an accepted architecture boundary (I-4).
- Ops-layer recovery tooling is assumed to work as documented except where prior postmortems record otherwise.
- Store `Get`/`Set`/`Delete` errors are treated as realistically node-local (the premise of the June fail-fast contract).

---

## Follow-up Retest Guidance

If remediation lands in this release cycle, produce `docs/security/2026-08-06/blockchain-retest.md` following [`2026-08-04/blockchain-retest.md`](../2026-08-04/blockchain-retest.md):

- Header with Scope, Baseline (post-remediation commit), Previous review: `2026-08-06/blockchain-review`.
- Remediation Status table covering every finding: `M-1`–`M-5`, `L-1`–`L-7`, `I-1`–`I-7`.
- Minimum evidence:
  - **M-1**: injected `SetSubscription` / `SetProfileCore` failures reject the tx or halt EndBlock; no success path after value move.
  - **M-2**: count-key Get error fails closed; cap not bypassed.
  - **M-3**: delete with injected Get/`RemoveSubscription` failure rejects or halts; no orphan index/username.
  - **M-4**: period-0 expiry burns reserve and clears level.
  - **M-5**: comments corrected; difficulty/window write errors propagated or explicitly ADR-excepted.
  - **L-5**: parity test covers both ante switches.
  - **I-7**: no code change required unless product policy changes.
  - Carryover tests: PoW benchmark, wedged user, bootstrap idempotence.
