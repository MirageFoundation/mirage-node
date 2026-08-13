# Blockchain Security Review — Retest of 2026-08-04

**Retest of:** [`2026-08-04/blockchain-review.md`](blockchain-review.md) — 23 findings (2 High, 9 Medium, 8 Low, 4 Informational).
**Review baseline:** `prod` at `1d3ab707` (v1.30.0).
**Retest state:** `prod` at `870afabd` (v1.32.2), deployed to all four validators on 2026-08-06.
**Remediation landed in:** `3ccf8c70` (v1.31.0 — bridge removal and the bulk of the findings), `3fd4f59e` (v1.32.0 — C-1 relay gas payer consent), `94274101` (ante-order pinning and authorization tests), `6d25f71a` (relay fee ceiling removal).
**Scope of this document:** the current status of every finding, the evidence behind each claim, and the rationale for each item accepted rather than fixed. Where this document and the original disagree about present-day state, **this one is authoritative**; the original is preserved as written, with its line references frozen at its baseline.

> **Later full review:** [`2026-08-06/blockchain-review.md`](../2026-08-06/blockchain-review.md) re-audits the
> tree after this remediation wave (baseline `v1.32.4`). Use that document for
> new findings and for present-day status of carryovers; this retest remains the
> record of how the Aug 4 findings were closed.

> **Why this document is late.** The review prescribed a retest doc in its own
> follow-up guidance and it was never written, even though the remediation
> shipped the next day. For a month the review was the only status record, and it
> reads as fully open: `H-2` is titled "Conditional on Operator Verification",
> six findings carry "Not Started" in their headings, and the Prioritized
> Recommendations list eleven items as outstanding. Every one of those statements
> was accurate at the 2026-08-04 baseline and stale within 24 hours. The original
> now carries a banner pointing here.
>
> The retest guidance also names `review-2026-03-12-retest.md` as the pattern to
> follow. **That file does not exist.** This document follows the structure of
> [`2026-08-05/backend-retest.md`](../2026-08-05/backend-retest.md)
> instead, which is the only retest precedent actually in the repository.

---

## Summary

**15 fixed, 2 documented, 1 partially fixed, 3 accepted risk, 2 open** — 23 total. Nothing was closed by re-reading the code and deciding it was fine; every "Fixed" below cites a source change, and most cite a named regression test.

Two results are worth reading past the table:

- **H-1 was fixed at the mechanism level, not patched around.** The review's core argument was that `panic()` is the wrong halt primitive because CometBFT recovers it, leaving a "consensus zombie" that reports `catching_up=false` at a frozen height. All 13 panic sites are gone: there are now **zero** `panic(` calls in `x/core/keeper/keeper.go` and `patches/iavl/nodedb.go`, replaced by a shared halt helper that calls `os.Exit(1)`. Each site carries the node-local / deterministic classification the review asked for, and an inventory test fails the build if a `CONSENSUS_FATAL` panic is reintroduced.
- **H-2 was resolved more thoroughly than the review asked for.** The review wanted a `params.BridgeEnabled` kill-switch and explicitly warned that params-only dormancy is not sufficient. Rather than gate the bridge, v1.31.0 **deleted it** — handlers, params fields, message types, and store prefixes. This satisfies the guidance's intent by construction, and is discussed below because the guidance's literal wording ("only mark Fixed once the kill-switch exists in code") would otherwise leave it open forever.

The one substantive residual is **L-8**: the shared relay-message registry and its parity test now exist, but the two ante switches are still hand-maintained, so the property the finding was about — parity that does not depend on discipline — is only half established.

---

## Remediation Status — Review 2026-08-04

| ID | Title (abbreviated) | Status | Notes |
|----|---------------------|--------|-------|
| H-1 | `CONSENSUS_FATAL` panics produce consensus zombies | **Fixed** | 13 panic sites → 0; `os.Exit(1)` halt, classifications, inventory test |
| H-2 | Bridge dormancy premise contradicted; `MsgBridgeBurn` may burn user funds | **Fixed** | Bridge removed entirely in v1.31.0, not gated — see caveat below |
| M-1 | Argon2 PoW runs before signature verification and before the O(1) hash check | **Fixed** | Ante reordered, hash check hoisted, order pinned by test; benchmark still absent |
| M-2 | `AssertSupplyInvariant` iterates every balance every block | **Fixed** | O(1) delta invariant added alongside; full scan retained by design, now instrumented |
| M-3 | `GetRelayCredit` silently returns zero on store failure | **Fixed** | Halts with `RELAY_CREDIT_STORE_GET` / `RELAY_CREDIT_DECODE` |
| M-4 | `RelayAccountingDecorator` discards credit-accounting errors | **Fixed** | Decorator removed; accounting moved to handler with propagated errors |
| M-5 | Ante-side `checkReserveOrDowngrade` mutations always rolled back | **Fixed** | Mutation deleted from ante; downgrade lives only in the handler |
| M-6 | BeginBlock reserved-profile bootstrap discards three errors | **Fixed** | One-shot sentinel gate, errors propagated |
| M-7 | `processSubscriptions` short-circuits before profile decode | **Fixed** | Decode hoisted above the `SubscriptionPeriod == 0` continue |
| M-8 | Two vendored forks with no upstream provenance tracking | **Fixed** | `PATCHES.md`, CI diff check, `govulncheck` covers both modules |
| M-9 | Mint and admin fee waiver remain log-and-continue, no decision recorded | **Documented** | ADR accepts the exception with rationale; in-code cross-references added |
| L-1 | `computeDifficultyFactor` uses `math.Pow` on `float64` in consensus | **Fixed** | `big.Rat` fixed-point; NaN/Inf rejected in `Params.Validate` |
| L-2 | `ResetAllRelayCredits` deletes during iteration, ignores errors | **Fixed** | Collect-then-close-then-delete, errors propagated |
| L-3 | v1.28.0 store deletion split across load phase and handler | **Documented** | Two-phase contract documented at the `SetStoreLoader` call site |
| L-4 | `RecordPoWMessage` write failure swallowed by its ante caller | **Fixed** | Ante now rejects the transaction on error |
| L-5 | `getUserLevel` returns `(0, "")` for a malformed pubkey | **Fixed** | Pubkey length rejected before any routing decision |
| L-6 | `ProcessProposal` performs minimal validation only | **Accepted Risk** | Unchanged by choice; M-1's reordering removed most of the underlying DoS concern |
| L-7 | `routePoWTx` logs a routine user error at `Error` | **Fixed** | Lowered to `Warn` |
| L-8 | Relay allowlist parity holds but is unpinned | **Partially fixed** | Registry + parity test exist; the two ante switches are still hand-maintained |
| I-1 | Two divergences unrooted; validators still carry local query load | **Not Started** | Confirmed still co-located on all four hosts, 2026-08-06 |
| I-2 | `upgrades.go` carries every handler in one file | **Not Started** | 2,260 lines, 44 registered handlers (was 2,279 / 42) |
| I-3 | Genesis `raw_state` remains a full trust anchor | **Accepted Risk** | Unchanged by design, but the halt is now a clean exit rather than a zombie |
| I-4 | Delete authorization remains indexer-enforced | **Accepted Risk** | Documented architecture boundary; mirrors backend M-8 |

---

## Evidence

### H-1 — the halt mechanism was replaced, not worked around

- **Zero panic sites.** `panic(` no longer appears in `x/core/keeper/keeper.go` or `patches/iavl/nodedb.go`. The only `panic(` in the tree carrying a `CONSENSUS_FATAL` string is the deliberately unreachable one after `os.Exit` in the halt helper itself, documented at `blockchain/consensusfatal/halt.go:26` as a guard in case `haltWith` is ever stubbed.
- **Process termination.** `consensusfatal.HaltErr` calls `os.Exit(1)` (`blockchain/consensusfatal/halt.go:10`). The vendored fork cannot import the main module, so it carries its own copy at `blockchain/patches/iavl/consensus_fatal.go:13`, called from the prune-hole guard at `nodedb.go:817`.
- **Classification at each site**, as remediation item 2 asked: for example `keeper.go:1008` is marked node-local and `keeper.go:1019` deterministic.
- **Inventory test.** `blockchain/consensusfatal/inventory_test.go` (`TestNoConsensusFatalPanicLeft`) fails if a `CONSENSUS_FATAL` panic reappears, so the count cannot grow silently. `halt_test.go` covers the helper.
- **Remediation item 3 also landed.** `UpdateParams` validates the merged params and rejects the proposal at execution (`x/core/module/module.go:1330`), with a comment stating the reason: so a bad proposal fails there rather than at the next `BeginBlock` `GetParams` halt on every validator simultaneously.

### H-2 — bridge deleted, and why that counts as Fixed

The retest guidance says to mark bridge findings Fixed "only once the kill-switch exists in code — params-only remediation is not sufficient, since params-only dormancy is exactly what H-2 shows cannot be relied upon." No kill-switch exists, because there is nothing left to switch off:

- `x/core/module/bridge_handlers.go` is gone.
- `BridgeChains` and the bridge fee fields are gone from `x/core/types/params.go` and the proto.
- The ante router rejects any surviving bridge message outright — `blockchain/app/app.go:192`, "bridge messages were removed in v1.31.0" — pinned by `TestMirageAnteRouterRejectsRemovedBridgeMessages` (`app/relay_messages_test.go:35`).
- Store prefixes were removed, with `TestRemovedBridgePrefixesComplete` asserting completeness.

Deletion is strictly stronger than the requested params-independent gate: the concern was that dormancy depended on a mutable value, and there is now no code path to re-arm without a new release. Marked **Fixed** on that basis.

**One item from the H-2 remediation list has no evidence and is not claimed here:** the review asked, if the bridge turned out to be live, for an audit of `BridgeBurnRecord` entries created since v1.9.0 to find users whose tokens were burned and never minted. No such audit is recorded in this repository. The removal prevents any further loss but does not answer whether loss already occurred. See Follow-up.

### M-1 — ordering fixed, benchmark still missing

The relay ante chain now runs signature verification before proof-of-work: `SetUpContext → ValidateBasic → GovAuthority → TxTimeoutHeight → ConsumeGasForTxSize → Logging → EnsureAccounts → SetPubKey → SigGasConsume → SigVerification → DeductFee → RelaySigDecorator → PowDecorator` (`app/ante_relay_chain.go:49`). The order is pinned by `TestRelayAnteDecoratorOrder` (`app/ante_relay_chain_test.go`), which closes the review's "no test asserting ante-chain decorator ordering" gap. Inside `validatePoWBytesArgon2` the `last_block_hash` validation now sits at `ante_pow.go:1432`, above the `argon2.IDKey` call at `1463`.

Remediation item 3 — a benchmark pinning per-envelope verification cost — was not done. No `Benchmark*` function exists anywhere under `blockchain/app/` or `blockchain/x/`.

### M-2 — both halves, as the review asked

The review was explicit that a delta check must not *replace* the full identity check, because a delta cannot detect the 2026-06-12 shape (supply changed while the balance write was missing). Both now run in `EndBlock` (`x/core/module/module.go:783` and `:789`), the full scan is timed, and the duration is logged every 1000 blocks (`:794`). Consistent with H-1, a violation returns an error from `EndBlock` rather than panicking.

### M-3, M-4, M-5, M-6, M-7 — the silent-failure family

- **M-3:** `GetRelayCredit` halts with `CONSENSUS_FATAL:RELAY_CREDIT_STORE_GET` (`keeper.go:1010`) and `:RELAY_CREDIT_DECODE` (`keeper.go:1020`). This was the last silent default in the mint input path.
- **M-4:** `RelayAccountingDecorator` and `app/ante_relay_acc.go` no longer exist. Accounting moved into the handler path, where `AccToValoper` and `AddRelayCredit` failures are returned as `relay accounting: …` errors (`module.go:1477`).
- **M-5:** the ante-side copy no longer mutates. `ante_pow.go:154` documents the finding, and the insufficient-reserve branch returns without writing (`:203`). The downgrade now happens only in `deductRelayGasFee` (`module.go:277`), where it commits.
- **M-6:** the bootstrap is gated by a one-shot sentinel (`HasReservedProfilesBootstrapped`, `module.go:694`, keys at `x/core/types/keys.go:87`) and every error is propagated. The review preferred the sentinel over a new panic site, and that is what was implemented.
- **M-7:** the profile decode was hoisted above the `SubscriptionPeriod == 0` continue (`module.go:898`), and `TestProcessSubscriptionsFailsFastOnCorruptProfileOneTimePayment` covers the corrupt-profile case.

### M-8 — provenance now exists

`blockchain/patches/PATCHES.md` records the upstream commit hash, tag, date, and change summary for both forks. `scripts/check_patches.sh`, wired at `blockchain/Makefile:86`, regenerates the diff and fails on drift. `make govulncheck` (`Makefile:159`) scans the main module plus `patches/iavl` and `patches/cosmos-sdk-store-v2/rootmulti`, closing the review's observation that `replace`-directed modules were invisible to scanning.

### M-9, L-3 — decisions recorded rather than code changed

- **M-9:** `docs/architecture/adr-mint-log-and-continue.md` records the decision to keep log-and-continue in the mint subsystem and the admin fee waiver, with the rationale the review asked for — including that the 2026-07-12 halt is evidence against adding halt sites. Cross-referenced at `keeper.go:1555` and `module.go:303`. Status is **Documented**, which is what the review requested; the code is deliberately unchanged.
- **L-3:** the two-phase, non-atomic contract is documented at the `SetStoreLoader` call site (`app/upgrades.go:2191`), including the suggestion to use a handler-written sentinel for any future removal of a store with live state.

### L-1, L-2, L-4, L-5, L-7 — the low-severity set

- **L-1:** `computeDifficultyFactor` uses `big.Rat` exponentiation with no `math.Pow` (`ante_pow.go:1316`), and `TestComputeDifficultyFactorDeterminismTable` pins a fixed input/output table. `Params.Validate` now rejects non-finite values for the float-backed economics fields (`x/core/types/params.go:214`, `:246`, `:282`).
- **L-2:** collect-then-close-then-delete with propagated delete errors (`keeper.go:1077`).
- **L-4:** the ante returns the error instead of logging it (`ante_pow.go:304`), matching the read path's severity without adding a halt site.
- **L-5:** `requireEnvelopePubkey` rejects a non-33-byte pubkey before any routing or PoW work (`ante_pow.go:241`); `getUserLevel` also errors on bad length (`:90`).
- **L-7:** the insufficient-reserve log is now `Warn` (`ante_pow.go:203`).

### L-8 — half done, and the remaining half is the point

What exists: a shared registry of 25 relay message types (`app/relay_messages.go:17`), `isRelayMessage` derived from it (`app/app.go:230`), and `TestRelayMessageRegistryParity` asserting the two agree (`app/relay_messages_test.go:15`). The dead `MsgSetLevel` branch is gone from `RelaySigDecorator` (comment at `ante_metasig.go:791`) and `EnsureAccountsDecorator` carries the scope comment explaining why it covers only 13 (`ante_ensure_accounts.go:17`).

What does not: the `PowDecorator` and `RelaySigDecorator` switches are still hand-written `case` lists — `ante_metasig.go` has 25 cases, matching the registry today. The parity test compares the registry against `isRelayMessage` only, so a new relay-eligible message added to the registry and to `isRelayMessage` but omitted from one of the ante switches would still pass. That is precisely the bypass class the finding describes, and it remains held by discipline.

### I-1 — still open, and confirmed from the fleet

The review called validator/query-load isolation the single change most likely to stop the recurring divergence class. During the v1.32.2 fleet deploy on 2026-08-06, a read-only inventory of all four hosts showed the `indexer` and `backend` services running in the same container as the validator on **every** host. The co-location that correlates with every divergence and prune-hole event to date is unchanged. This is infrastructure work outside `blockchain/`, which is why it stays informational here, but it is the highest-value open item in the document.

---

## Test coverage gaps — current state

Of the eleven gaps the review listed, seven are closed:

| Gap | State |
|-----|-------|
| `CONSENSUS_FATAL` site inventory / halt mechanism | **Closed** — `consensusfatal/inventory_test.go`, `halt_test.go` |
| Ante-chain decorator ordering | **Closed** — `TestRelayAnteDecoratorOrder` |
| `computeDifficultyFactor` determinism table | **Closed** — `TestComputeDifficultyFactorDeterminismTable` |
| `processSubscriptions` corrupt profile, one-time payment | **Closed** — `TestProcessSubscriptionsFailsFastOnCorruptProfileOneTimePayment` |
| `AssertSupplyInvariant` cost visibility | **Closed** — timed, logged every 1000 blocks |
| `govulncheck` against patch modules | **Closed** — `Makefile` target covers both |
| Relay-allowlist parity | **Partial** — registry ↔ `isRelayMessage` only, not the ante switches |
| `params.BridgeChains` end state after all handlers | **Moot** — the field no longer exists |
| Per-envelope PoW verification benchmark | **Open** |
| M-5 wedged-user regression (level ≥ 1, zero reserve, then transacts) | **Open** |
| M-6 bootstrap no-op-on-subsequent-blocks test | **Open** |

---

## Dependency posture

The review's own appended section (Post-remediation dependency scan — 2026-08-04) still describes the current state and is not superseded: ten advisories with upstream fixes were cleared, both replacement modules scan clean, and two main-module advisories remain with no upstream fix — `GO-2026-5932` (OpenPGP via the SDK keyring CLI; production uses the `test` backend) and `GO-2026-4479` (Pion DTLS via CometBFT's optional libp2p transport, which is disabled). `make govulncheck` was **not** re-run for this retest; that section's results are inherited, not re-verified.

---

## Verification Performed

Source-level verification against `prod` at `870afabd`, plus read-only observation of the deployed fleet.

- Counted `panic(` in `x/core/keeper/keeper.go` and `patches/iavl/nodedb.go` (0 in both) and `panic(…CONSENSUS_FATAL…)` across `blockchain/` (1, the documented unreachable guard in the halt helper).
- Read the halt helper, both `os.Exit(1)` sites, the classification comments, and the inventory test.
- Confirmed by absence: `bridge_handlers.go`, `ante_relay_acc.go`, `BridgeChains` in params.
- Read the current relay ante decorator slice and its order test; confirmed the block-hash check precedes `argon2.IDKey` by line number.
- Read `UpdateParams` and confirmed `Validate()` runs before `SetParams`.
- Confirmed `PATCHES.md`, `scripts/check_patches.sh` wiring, the `govulncheck` target's module list, and `docs/architecture/adr-mint-log-and-continue.md`.
- Counted the shared registry (25) and the `RelaySigDecorator` switch (25); confirmed no test ties the switches to the registry.
- Measured `upgrades.go` at 2,260 lines with 44 `SetUpgradeHandler` calls.
- Confirmed I-1 from a read-only fleet sweep during the v1.32.2 deploy: `indexer` and `backend` present in the service list on all four hosts.

**Not verified:**

- **No Go tests were executed for this retest.** There is no local Go toolchain; the review ran its tests in a `golang:1.25` container. Every test cited here was confirmed to exist by name and to assert the property described, by reading it — not by running it. The named tests were run by their authors in the commits that introduced them.
- `make govulncheck` was not re-run; see Dependency posture.
- Nothing in Accepted Risk, by definition.
- Whether any user funds were lost through the bridge before its removal.

---

## Follow-up

1. **Close L-8's remaining half.** Derive the `PowDecorator` and `RelaySigDecorator` switches from the shared registry, or extend `TestRelayMessageRegistryParity` to assert both switches handle every registry entry. Until then the parity that prevents a PoW/signature bypass is maintained by review discipline, which is what the finding objected to.
2. **Answer the H-2 audit question.** Determine whether any `MsgBridgeBurn` ever executed on mainnet before v1.31.0 removed the path, and if so whether those users' tokens were ever minted on the destination chain. Removal stopped the bleeding; it did not establish that nobody was hurt. This is the only H-2 remediation item with no evidence behind it.
3. **I-1 remains the highest-value open item**, now confirmed unchanged on the live fleet. Every read-path determinism finding in the original review is downstream of it.
4. **Add the three missing tests** (PoW benchmark, M-5 wedged user, M-6 bootstrap idempotence). The first is the one that guards a parameter change from silently reintroducing M-1.
5. **Re-run `make govulncheck`** at the next dependency refresh and revise the review's dependency section in place, as that section instructs.
