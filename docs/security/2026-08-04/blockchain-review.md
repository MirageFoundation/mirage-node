# Blockchain Security Review — 2026-08-04

**Scope:** `blockchain/` — all tracked Go/proto/module files, including app/ante handlers, core module, keeper, types, params, genesis, bridge handlers, orchestrator, upgrade handlers, **the two vendored consensus-critical forks under `blockchain/patches/`**, and security-relevant tests.
**Out of scope:** `web/`, `indexer/`, `deploy/`, `scripts/`, external Solana programs, production servers. Ops-layer tooling (`scripts/divergence_watchdog.py`, `scripts/recover.sh`, `scripts/stuck_node_alert.py`) is referenced where a blockchain-side design choice depends on it, but is not itself audited.
**Baseline:** `prod` at `1d3ab707ca39cb961397c58e9475a9749f5c74ac` (`v1.30.0`). `blockchain/` is byte-identical on `dev` (`d1ef62ec`, v1.30.1 dev); the only delta is a version bump outside this tree. Working tree clean.
**Previous review:** `review-2026-05-09.md` (baseline `v1.24.4`) — that review and the four before it were removed on 2026-08-06 as superseded; they remain in git history. The Prior Finding Status table below is the surviving record of their verdicts.

> **STATUS — SUPERSEDED BY RETEST (2026-08-06).** Remediation shipped in
> v1.31.0–v1.32.2 and is deployed. **Of 23 findings: 15 fixed, 2 documented, 1
> partially fixed, 3 accepted risk, 2 open.** Every status claim in the body below
> describes the 2026-08-04 baseline and is stale — including the six headings that
> read "Not Started", H-2's "Conditional on Operator Verification", the Prior
> Finding Status table, and all eleven Prioritized Recommendations. See
> [`2026-08-04/blockchain-retest.md`](blockchain-retest.md), which is
> authoritative wherever the two disagree. The analysis below is preserved as
> written, with its line references frozen at its baseline.
>
> **Still open:** L-8 (the two ante switches are not mechanically tied to the
> shared relay registry), I-1 (validators still co-located with indexer and
> backend query load, re-confirmed 2026-08-06), I-2, the H-2 burn-record audit,
> and three missing tests (PoW benchmark, M-5 wedged user, M-6 bootstrap).

> **Bridge / Orchestrator scope note — the dormancy premise from the previous
> review does not hold and must be re-verified before triaging.** The 2026-05-09
> review deferred all bridge findings on the stated basis that "no `bridge_chain`
> is enabled in chain params, so on-chain bridge handlers reject every
> `MsgBridgeBurn`/`MsgBridgeAttestMinted` via `ValidateBridgeChain`." Source
> review this cycle contradicts both halves of that sentence: the `v1.9.0-bridge`
> upgrade handler *writes* an enabled Solana entry into `params.BridgeChains` and
> no later handler removes it, and `bridgeAttestMinted` never calls
> `ValidateBridgeChain` at all. See **H-2**. Bridge findings are held at
> ACCEPTED-AND-DEFERRED **only if** an operator confirms the live params are
> actually empty; if they are not, they become live user-fund-loss findings.
>
> **RESOLVED 2026-08-05 — no operator verification needed.** v1.31.0 removed the
> bridge outright: handlers, params fields, message types and store prefixes are
> all gone, and the ante router rejects any surviving bridge message. The
> triage gate above is moot, and every bridge-scoped finding from this and prior
> reviews is closed by construction rather than by params state. The one item
> still outstanding is historical, not preventive: whether any user burned tokens
> that were never minted on the destination chain before removal. See the retest.

---

## Executive Summary

Full re-audit of `blockchain/` at 81 tracked Go/proto files (87 including generated `*.pb.go`), plus 143 Go files across the two vendored forks that are new to the scope this cycle. Reviewed transaction admission, the ante router and both ante chains, the PoW decorator, relay signature verification, core message handlers, the BeginBlock/EndBlock determinism contract, mint distribution, all 42 registered upgrade handlers, the bridge surface, and the vendored IAVL and store/v2 patches.

**The defining event of this cycle is not a new feature — it is that the fail-fast contract adopted after the May 4 divergence became, on 2026-07-12, the direct cause of a 3-hour-47-minute full-chain halt.** A `PRUNE_HOLE` guard added to the vendored IAVL fork panicked on a false positive (a transient batch-flush window between a `Delete` and its paired `Set`), and the panic destroyed the pending batch, converting the transient window into a real persistent hole. Two of four validators — specifically the two running `pruning="custom"` under user-facing query load — crashed within nine minutes of each other, dropping the network below 2/3 voting power. The false-positive bug itself was correctly root-caused and fixed in v1.29.4, and pruning mode was reverted to async in v1.29.5.

The *bug* is fixed. The *structural lesson is not addressed*, and it is this review's highest-severity finding. There are **13 literal `CONSENSUS_FATAL` panic sites** across the chain code and vendored IAVL fork: 12 in the core keeper and one IAVL prune-hole guard. Every one of them is a deliberate, correct decision to halt a node rather than commit a divergent app hash — the right call for a *node-local* fault. But `panic()` is the wrong halt mechanism, because CometBFT's `receiveRoutine` recovers it: the process stays alive, RPC and p2p keep answering, `/status` reports a frozen height with `catching_up=false`, and consensus is dead. The 2026-07-12 incident showed this "consensus zombie" state defeating the height-based watchdog. The top-level `recover()` in `cmd/miraged/main.go` does not help, because block execution runs on a different goroutine. And critically, the entire contract is designed around the assumption that these faults are node-local; for any panic condition that is *deterministic* — a `Params.Validate()` failure introduced by a governance proposal, a supply-invariant violation caused by a code bug rather than a stale read, or a prune-hole reached by every node with identical pruning config — all four validators zombie simultaneously and the chain halts with no automatic recovery path. On 2026-07-12 that scenario played out at 2/4 power. See **H-1**.

Beyond that, the second-order effects of the June/July remediations deserve attention. Disabling the IAVL fast-node index (removed outright from the read path, not merely toggled off) means every consensus read is now a canonical tree traversal. `AssertSupplyInvariant`, added in the same period, iterates *every account balance* in *every* `EndBlock` through that slower path. These two mitigations multiply each other's cost, the second is O(accounts) and unbounded, and a violation is itself a zombie-producing halt. See **M-2**.

Two prod divergences (2026-05-25 h4854225 and 2026-06-16 h5378001) remain unrooted. The postmortem's own highest-value open action item — isolate the validator from the indexer, backend `simulate`, and reward-distributor query traffic that only the public validators carry — is still open, and the correlation evidence for it is strong (the two nodes that carry local query load are the only two that have ever diverged or hit prune holes).

No new privilege-escalation, signature-bypass, or unauthorized-mint vector was found. `GovAuthorityDecorator` closes the gov-authority spoofing class comprehensively and is applied on both ante paths. Envelope replay protection (per-pubkey nonce with expiry) is correct and fails closed. The relay allowlist, which the last two reviews flagged, is now in exact parity across `isRelayMessage`, the PoW switch, and `RelaySigDecorator` — though still unpinned by a test.

**Ship blockers:** None in the code as written. **H-2 is an operator-verification blocker**: one query against live params determines whether it is informational or a live fund-loss issue.

---

## Findings

> **Status annotations (2026-08-06).** A `Status` line appears below on every
> finding whose own text asserts a stale status, and on every finding still open.
> The rest are: **M-1 Fixed** (its benchmark item still open), **M-2, M-3, M-4,
> M-8, L-1, L-2, L-4 Fixed**, **M-5 Fixed** (its regression test still missing),
> **L-3 Documented**, **I-2 Not Started** (informational), **I-3 and I-4 Accepted
> Risk** (unchanged carryovers). Full evidence per finding is in the
> [retest](blockchain-retest.md).

### H-1: `CONSENSUS_FATAL` Panics Produce Consensus Zombies, Not Process Exits — A Deterministic Trigger Halts the Whole Chain With No Automatic Recovery (High)

> **Status (2026-08-06): Fixed in v1.31.0.** All four remediation items landed. The 13 panic sites are now zero; `consensusfatal.HaltErr` calls `os.Exit(1)`; each site carries a node-local/deterministic classification; `TestNoConsensusFatalPanicLeft` prevents regression; and `UpdateParams` validates at governance execution instead of at the next `BeginBlock`.

**Location:** 13 literal panic sites — `x/core/keeper/keeper.go` (12) and `patches/iavl/nodedb.go` (1). Other `CONSENSUS_FATAL` strings in module, ante, and upgrade code are returned errors or log messages, not panic sites. Halt mechanism: `cmd/miraged/main.go` lines 19–24.

The fail-fast contract introduced in v1.25.0 and extended on 2026-06-22 is the correct response to the May 4 silent-fallback divergence: a node that cannot read consensus state must stop rather than substitute a default. The implementation halts by panicking. That choice has three consequences that the contract does not account for.

**1. A panic in block execution does not stop the process.** Block execution runs on CometBFT's consensus goroutine, whose `receiveRoutine` has a deferred `recover()`. It stops the consensus reactor and leaves everything else running. The node keeps serving RPC and p2p, and `/status` reports a frozen height with `catching_up=false` — a state that looks healthier than an actual crash. The `recover()` in `cmd/miraged/main.go` only guards the main goroutine and never sees these panics:

```19:24:blockchain/cmd/miraged/main.go
	defer func() {
		if r := recover(); r != nil {
			fmt.Fprintf(os.Stderr, "FATAL: panic: %v\n%s", r, string(debug.Stack()))
			os.Exit(1)
		}
	}()
```

**2. The zombie state defeats the recovery tooling the contract depends on.** Every `CONSENSUS_FATAL` doc comment in the codebase justifies halting on the grounds that "the auto-recovery watchdog will state-sync from healthy peers." That is only true if the watchdog can tell the node is dead. On 2026-06-16 the watchdog sat idle for over an hour because a diverged node reports `catching_up=true`; that specific blind spot was fixed. On 2026-07-12 the zombie reported `catching_up=false` at a frozen height, a different shape again. The dependency runs the wrong way: the blockchain's halt semantics are being chosen on the assumption that an ops-layer script will interpret them correctly, and that assumption has now failed twice in different ways.

**3. The contract assumes node-local faults, but several panic conditions are deterministic.** A node-local fault (transient store read error, stale IAVL read) zombies one node and the network survives. A deterministic fault zombies every node at the same height. Conditions in the current code that are deterministic or fleet-correlated:

- `GetParams` panics on `Validate()` failure. A governance `MsgUpdateParams` that writes params passing the handler's checks but failing `Validate()` on the next `BeginBlock` halts 4/4 validators at the same height. There is no recovery: state-sync from peers is useless when every peer has the same params.
- `AssertSupplyInvariant` (EndBlock) halts on mismatch. If a mismatch ever arises from a *code* bug in mint/burn accounting rather than a stale read, it is identical on every node.
- `PRUNE_HOLE` in `patches/iavl/nodedb.go` correlates with pruning configuration, not with node identity. On 2026-07-12 it fired on exactly the two nodes sharing `pruning="custom"` plus query load, within nine minutes, and took the chain below 2/3.

**Impact:** Demonstrated 3h47m full-chain halt at 2/4 power, requiring manual intervention (`pruning="nothing"` plus restart) at roughly 00:00 UTC on 2026-07-13. The same mechanism at 4/4 power is an unrecoverable halt until an operator ships a new binary. The blast radius grows with each panic site added, and 13 is already too many for a contract whose safety argument rests on every trigger being node-local.

**Remediation, in priority order:**

1. **Change the halt mechanism from `panic()` to process termination.** A `CONSENSUS_FATAL` should log, flush, and call `os.Exit(1)` (or `syscall.Kill(os.Getpid(), SIGABRT)`) so the supervisor sees a dead process and the watchdog sees an unreachable endpoint — both unambiguous signals, neither dependent on interpreting a half-alive node. This is a small, mechanical change and it removes the zombie class entirely.
2. **Classify every panic site as node-local or deterministic**, and record the classification in the doc comment next to it. Deterministic conditions must not use the same mechanism as node-local ones, because "state-sync from healthy peers" is not a remedy when there are no healthy peers.
3. **For `GetParams` specifically**, validate in the `MsgUpdateParams` / governance-execution path so a proposal that would produce unvalidatable params is rejected at submission, not discovered at the next `BeginBlock` on every validator at once.
4. **Add a startup-time inventory test** that enumerates `CONSENSUS_FATAL` sites and asserts each has a classification comment, so the count cannot grow silently.

---

### H-2: Bridge Dormancy Premise Contradicted by Upgrade History — `MsgBridgeBurn` May Be Live and Burns User Funds With No Redemption Path (High, Conditional on Operator Verification)

> **Status (2026-08-06): Fixed in v1.31.0 by removal — the operator-verification gate is moot.** The bridge was deleted rather than gated, so dormancy is no longer a params property. The kill-switch this finding asked for is unnecessary because there is no handler left to gate. **Outstanding:** the requested `BridgeBurnRecord` audit was never performed, so whether funds were already lost before removal is still unanswered.

**Location:** `app/upgrades.go` lines 630–652 (v1.9.0-bridge), `x/core/module/bridge_handlers.go` lines 109–191 (`bridgeBurn`) and 412+ (`bridgeAttestMinted`), `cmd/orchestrator/main.go` lines 31–33, `web/backend/routes/bridge.py` line 6.

The previous review deferred seven bridge findings on the stated basis that `params.BridgeChains` is empty in production and that `ValidateBridgeChain` therefore rejects every bridge message. Source review does not support either claim.

**The upgrade history enables Solana and never disables it.** The `v1.9.0-bridge` handler appends an enabled Solana entry with a 500 MIRAGE fee if one is not already present. Tracing every later handler: `v1.10.0-remove-ibc` removes *Osmosis* only and explicitly leaves the rest; `v1.20.0` logs the orchestrator's disablement but performs no on-chain change; nothing through v1.30.0 touches `BridgeChains` again. Any chain that executed the v1.9.0 upgrade — which mainnet did — has an enabled Solana bridge chain in params unless it was removed out-of-band by a governance `MsgUpdateParams` that leaves no trace in this repository.

**One of the two gates the previous review relied on does not exist.** `bridgeBurn` and `bridgeAttestBurned` do call `ValidateBridgeChain`. `bridgeAttestMinted` does not — it validates its inputs and proceeds without ever consulting `params.BridgeChains`.

**If Solana is enabled, the burn path is a live fund-loss vector.** `bridgeBurn` burns the user's full amount irreversibly and then emits an event for an orchestrator to pick up:

```149:178:blockchain/x/core/module/bridge_handlers.go
	// Burn the full amount immediately (fee included)
	if err := k.BurnFromAccount(ctx, owner, amount); err != nil {
		return nil, fmt.Errorf("failed to burn tokens: %w", err)
	}
	// ... persist burn record, deduct relay gas fee ...
	// Emit event for orchestrators to pick up
	ctx.EventManager().EmitEvent(
		buildBridgeBurnEvent(owner, destChain, destAddr, amount, bridgeFee, sequence),
	)
```

The orchestrator that consumes that event is hard-disabled at startup (`panic("ORCHESTRATOR_HARD_DISABLED: bridge is offline; do not run this binary")`) and nobody runs it. So the tokens are destroyed on Mirage and never minted on Solana. There is no refund, reversal, or expiry path in the handler — the `BridgeBurnRecord` is written for audit, not for recovery. `MsgBridgeBurn` is in `isRelayMessage`, is PoW-exempt in the ante, and the backend exposes it at `POST /api/bridge/burn`, so the path is reachable by an ordinary user through the normal product surface.

**Impact:** If enabled, permanent and silent loss of user funds for anyone who invokes the bridge, plus all seven previously deferred bridge findings become live rather than dormant. If disabled, this is a documentation-accuracy issue and a latent risk that a single params edit re-arms.

**This review did not contact production**, per the operator rules, so the live value is unknown. Determine it with:

```bash
miraged q core params -o json | jq '.params.bridge_chains'
```

**Remediation:**

1. **Verify live params first.** Everything else depends on the answer.
2. **If Solana is enabled and the orchestrator is not running, disable it now** via `MsgUpdateParams`, and audit `BridgeBurnRecord` entries created since v1.9.0 to find users who already burned tokens that never arrived.
3. **Add the hard kill-switch** the previous review recommended as L-1 (still Not Started): a dedicated `params.BridgeEnabled` defaulting to false, checked at the top of *every* bridge handler including `bridgeAttestMinted`, so dormancy is a code property rather than a params property.
4. **Add `ValidateBridgeChain` to `bridgeAttestMinted`** regardless of the kill-switch decision.
5. Correct the dormancy assertion in the 2026-05-09 review, which is currently a false statement that future reviewers will inherit.

---

### M-1: Argon2 PoW Verification Runs Before Signature Verification and Before the O(1) Block-Hash Check (Medium)

**Location:** `app/app.go` lines 355–367 (relay ante ordering), `app/ante_pow.go` lines 1278–1305.

The relay ante chain is ordered `setup, validateBasic, govDec, timeout, gasSize, logDec, powDec, ensure, metaFees, accDec, meta`. `powDec` — memory-hard Argon2id verification — is seventh. `meta` — `RelaySigDecorator`, the only thing that establishes the envelope was signed by anyone at all — is eleventh. Every relay transaction therefore pays full PoW verification cost before the node has any reason to believe it is authentic.

Measured on an Intel Core Ultra 9 285K with the production parameters (`argon2.IDKey(guess, salt, 1, 4096, 1, 32)`): **1.76 ms and 4.20 MB allocated per verification**. That is roughly 565 verifications per second per core and ~2.4 GB/s of allocation churn at saturation, on a fast desktop CPU; a validator VM will be worse. This runs in `CheckTx`, so any peer that can reach the mempool can force it without holding a valid key.

Within `validatePoWBytesArgon2` the ordering compounds the problem. The Argon2 call is at line 1278; the `last_block_hash` validity check — a string compare against `LastBlockId` plus at worst one store read — is at lines 1288–1305, *after* it. An envelope carrying a stale or fabricated block hash is rejected for free in principle, but in practice costs a full Argon2 first. The two checks are independent, so the order is arbitrary.

**Impact:** Unauthenticated CPU and memory amplification against mempool admission. Not a consensus or funds issue, and the four-validator topology limits who can be targeted, but it is the cheapest DoS surface in the chain and the fix is nearly free.

**Remediation:**

1. **Hoist the `last_block_hash` check above the Argon2 call** inside `validatePoWBytesArgon2`. Semantically equivalent, and it makes the common spam shape (stale or garbage block hash) an O(1) rejection.
2. **Move `meta` (`RelaySigDecorator`) ahead of `powDec`** in the relay chain so signature verification gates PoW verification. Signature verification is ~50 µs against Argon2's 1.76 ms — a 35x reduction in the cost of rejecting an unauthenticated envelope. Confirm no ordering dependency exists first; `RelaySigDecorator` reads only the envelope fields and the nonce store, so none is apparent.
3. Add a benchmark to the test suite pinning per-envelope verification cost so a future parameter change cannot silently make this worse.

---

### M-2: `AssertSupplyInvariant` Iterates Every Balance Every Block, Through the Now-Canonical-Only IAVL Read Path (Medium)

**Location:** `x/core/keeper/keeper.go` lines 1215–1232, called from `x/core/module/module.go` EndBlock lines 740–751.

The invariant guard added after the 2026-06-12 divergence is a good control and it caught real corruption. Its cost profile deserves scrutiny, because it interacts badly with the other mitigation shipped in the same period.

```1215:1232:blockchain/x/core/keeper/keeper.go
func (k Keeper) AssertSupplyInvariant(ctx sdk.Context) error {
	denom := k.mintDenom()
	sum := sdkmath.ZeroInt()
	k.bank.IterateAllBalances(ctx, func(_ sdk.AccAddress, coin sdk.Coin) bool {
		if coin.Denom == denom {
			sum = sum.Add(coin.Amount)
		}
		return false
	})
	supply := k.bank.GetSupply(ctx, denom).Amount
	if !supply.Equal(sum) {
		return fmt.Errorf(
			"supply invariant violated for %s: recorded supply %s != sum of balances %s (diff %s)",
			denom, supply.String(), sum.String(), supply.Sub(sum).String(),
		)
	}
	return nil
}
```

Three compounding concerns:

1. **It is O(accounts) per block with no cap and no sampling.** Cost grows monotonically with user count, forever, and it runs unconditionally in every `EndBlock`.
2. **The vendored IAVL fork made the iteration slower.** `ImmutableTree.Iterator` and `MutableTree.Iterator` were patched to force canonical tree traversal and never consult the fast-node index. That patch is correct for consensus safety, but it removed exactly the index that makes a full-range bank iteration cheap. The two mitigations from the same incident window multiply.
3. **A violation is a `CONSENSUS_FATAL` halt**, which per H-1 means a zombie rather than a clean exit, and a mismatch arising from a code bug rather than a stale read is deterministic across the fleet.

**Impact:** Unbounded per-block latency growth on the critical path. There is no evidence of a current problem — the chain produces blocks — but nothing bounds this, and block time degradation from an EndBlock hook is the kind of issue that is invisible until it is urgent.

**Remediation:**

1. **Do not replace this with a supply-delta-only assertion.** A delta check proves that the supply changed by the requested mint/burn amount, but it cannot detect the incident's exact shape: supply changed while the corresponding balance write was missing. Keep the full scan until an O(1) invariant independently tracks both aggregate balances and recorded supply inside the bank write path.
2. **Instrument scan duration and balance count** so growth is visible before it becomes a block-time problem, then use production measurements to set an explicit performance budget.
3. Add the incremental delta assertion as a complementary guard for missed or duplicated supply updates, not as a substitute for the supply-vs-balances identity.

---

### M-3: `GetRelayCredit` Silently Returns Zero on Store-Read Failure, and It Feeds Mint Distribution (Medium)

**Location:** `x/core/keeper/keeper.go` lines 1004–1015.

The 2026-06-22 sweep (postmortem action item 8) converted the consensus-path read family to fail-fast: `HasEnvelopeNonce`, `RecordPoWMessage`, `GetPoWMessageCount`, `GetCurrentDifficulty`, `HasCurrentDifficulty`, `GetPreviousDifficulty`, `GetLastDifficultyChangeHeight`, and `GetConsecutiveLowUsage` all now panic with a tagged `CONSENSUS_FATAL:*_STORE_GET` on a raw `store.Get` error. `GetRelayCredit` was not included, and it returns a zero `Int` on both a store error and a decode failure.

Relay credits determine each validator's share of the dynamic mint in `MintIfNeeded`. A node that reads zero where its peers read a real credit computes a different distribution, mints different amounts to different accounts, and produces a divergent app hash — the exact shape of the May 4 incident, in the token issuance path rather than the params path. It is the last silent-default left in this family, which makes it the one most likely to be missed.

**Impact:** Divergence vector in mint distribution. Same class and likelihood as the conditions the fail-fast sweep was built to eliminate; the sweep simply did not reach this function.

**Remediation:** Panic with `CONSENSUS_FATAL:RELAY_CREDIT_STORE_GET` on the error branch and `CONSENSUS_FATAL:RELAY_CREDIT_DECODE` on the decode branch, matching the eight functions already converted. Extend `TestConsensusReadsPanicOnStoreGetFailure` and `TestConsensusReadsReturnDefaultsOnAbsentKey` to cover it — absent key should still mean zero credit, which is a legitimate state.

---

### M-4: `RelayAccountingDecorator` Discards Credit-Accounting Errors Without Logging (Medium)

**Location:** `app/ante_relay_acc.go` lines 17–54.

The decorator resolves the relaying validator's operator address via `AccToValoper` and increments its relay credit via `AddRelayCredit`. Both error returns are discarded, and neither failure produces a log line. Combined with M-3, both the write and the read side of relay credit accounting can fail invisibly, and relay credits feed mint distribution.

The silence is the worst part. A node whose credit writes are failing looks identical to a node whose validator simply relayed nothing, and the resulting mint discrepancy surfaces later as an unexplained app-hash divergence with no app-level marker — precisely the signature the 2026-06-16 postmortem singled out as what made that incident so hard to root-cause (`record_fail=0 renewal_fail=0 supply=0 fatal=0`).

**Impact:** Silent divergence vector with no forensic trail.

**Remediation:** Propagate both errors and reject the transaction, consistent with the fail-fast contract applied to every other consensus-state write in the ante chain. If rejecting is judged too aggressive for a bookkeeping write, log at `Error` with a distinguishable tag at minimum — a silent failure in a mint input should never be possible.

---

### M-5: Ante-Side `checkReserveOrDowngrade` Mutations Are Always Rolled Back, Wedging Paid Users at an Unusable Tier (Medium)

**Location:** `app/ante_pow.go` lines 157–247, versus `x/core/module/module.go` lines 365–417.

The same "reserve exhausted, downgrade to free tier" logic exists in two places with opposite persistence semantics.

The handler-side copy in `deductRelayGasFee` mutates the profile (`ReserveFunds = 0`, `Level = 0`, clears subscription and auto-renew), emits a `subscription_expired` event, writes the profile, and returns `nil`. The mutation commits.

The ante-side copy in `checkReserveOrDowngrade` performs the equivalent mutation and then **returns an error**. Cosmos SDK's `baseapp.runTx` branches a cached context before invoking the ante handler specifically so it can discard on failure; on the error path `msCache.Write()` is never called. The downgrade is unconditionally rolled back, every time. It is dead code — the log line fires, the state change does not.

The user-visible consequence is a wedge. A level-1+ user whose reserve falls below `RelayMinGasPrice` hits `checkReserveOrDowngrade` in the ante on every ordinary relay message. The tx is rejected. The downgrade that would restore access is discarded. The user cannot use PoW (that path requires level 0) and cannot pay (no reserve). The escapes are non-obvious: `MsgSubscribe` skips the reserve check entirely, and `MsgAward`/`MsgBridgeBurn` skip the ante check and reach the handler-side copy, which does persist the downgrade. So recovery depends on the user happening to send one of three specific message types.

**Impact:** Users self-lock out of the product. Not a consensus or funds-loss issue, but the intended remediation for a normal, expected condition does not work, and the two implementations of one rule disagreeing is a maintenance hazard independent of the bug.

**Remediation:** Delete the mutation from the ante-side copy and keep only the rejection — an ante handler should classify, not mutate. Let the handler-side `deductRelayGasFee` remain the single place the downgrade happens, and make sure a wedged user reaches it. Add a regression test asserting a level-1 user with zero reserve is downgraded exactly once and can transact afterwards.

---

### M-6: BeginBlock Reserved Module Account Profile Bootstrap Still Discards Three Errors (Medium, Carryover from 2026-05-09 M-1, Not Started)

> **Status (2026-08-06): Fixed in v1.31.0.** Implemented the preferred option — a one-shot sentinel (`HasReservedProfilesBootstrapped`) rather than a new panic site — with all three errors propagated. A test asserting it is a no-op on subsequent blocks is still missing.

**Location:** `x/core/module/module.go` lines 681–690.

Unchanged since the previous review. `GetProfileCore`'s error is collapsed into `found == false`, and both `ClaimUsername` and `SetProfileCore` errors are discarded with `_ =`. A partial failure leaves a username claimed without a profile, or the reverse, and the mutation runs in `BeginBlock` where a per-node difference produces app-hash divergence on the next round.

This was the previous review's number-one prioritized recommendation and remains the closest-to-incident-class silent-skip pattern in the chain. It is also the one place where the fail-fast contract, applied nearly everywhere else, was simply not applied.

**Remediation:** Unchanged from the previous review — either propagate errors and halt, consistent with the rest of `BeginBlock`, or gate the block behind a one-shot sentinel key so it runs at genesis and upgrade rather than on every block. Given H-1, prefer the sentinel: it removes the per-block failure opportunity entirely rather than adding a 49th panic site.

---

### M-7: `processSubscriptions` One-Time-Payment Path Short-Circuits Before Profile Decode (Medium, Carryover from 2026-05-09 M-5, Not Started)

> **Status (2026-08-06): Fixed in v1.31.0.** The decode was hoisted above the `SubscriptionPeriod == 0` continue, and `TestProcessSubscriptionsFailsFastOnCorruptProfileOneTimePayment` covers the corrupt-profile case.

**Location:** `x/core/module/module.go` lines 846–855.

Unchanged. When `params.SubscriptionPeriod == 0`, the loop removes the subscription index and continues without ever decoding the profile, so a corrupt `ProfileCore` on an expiring one-time-payment subscription escapes the fail-fast detector. Consensus-safe as written — no state mutation depends on the undecoded bytes — but it narrows the contract's reach, and the corruption surfaces later at a less diagnosable point.

**Remediation:** Unchanged — move the `GetProfileCore` decode above the `SubscriptionPeriod == 0` short-circuit, and add a regression test for the corrupt-profile-with-one-time-payment case.

---

### M-8: Two Vendored Consensus-Critical Forks With No Upstream Advisory Tracking (Medium, New Scope)

**Location:** `blockchain/patches/iavl` (9,425 lines, forked from `github.com/cosmos/iavl@v1.2.8`), `blockchain/patches/cosmos-sdk-store-v2` (23,310 lines, forked from `github.com/cosmos/cosmos-sdk/store/v2@v2.0.0`), wired via `replace` directives in `go.mod`.

These forks account for 24,126 of the 25,773 lines added since the previous review's baseline — the non-patch chain code actually shrank by a small net amount. Both are load-bearing for consensus, and neither was in scope before, so this is their first review.

**The patches themselves are well-executed.** Reviewed all nine functional changes:

*iavl* (eight changes across three files): fast-node lookup removed from `ImmutableTree.Get` (lines 183–194); canonical iterator forced in `ImmutableTree.Iterator` (229–245); unsaved fast-node overlay disabled in `MutableTree.Get` (174–187); `MutableTree.Iterate` and `MutableTree.Iterator` delegated to the canonical tree (205–214, 223–237); `MutableTree.GetVersioned` forced to canonical historical reads (654–678); reference-root reformat reordered to Set-then-Delete in `deleteVersion` (520–541); fail-fast guard plus batch-flush re-probe in `deleteVersionsTo` (761–826).

*store/v2* (one change): bounded commit-info pruning in `rootmulti/store.go` — `pruneCommitInfo` (751–819) called from `PruneStores` (726–741), capped at `commitInfoPruneBatch = 20000` per pass (746–749).

Each change is documented in place with the incident that motivated it, the Set-then-Delete reorder is the correct fix for the flush-split window, the batch cap correctly avoids stalling a block while draining the ~2.1M-record backlog, and the range iteration is tight enough not to walk IAVL substore data. Both carry regression tests (`fastnode_import_test.go`, `nodedb_prune_fail_fast_test.go`, `commit_info_prune_test.go`) and both were verified to fail without their fix. The commit-info bug was filed upstream as [cosmos-sdk#26551](https://github.com/cosmos/cosmos-sdk/issues/26551) with a PR, and the double-close as [#26559](https://github.com/cosmos/cosmos-sdk/pull/26559). This is good work.

**The risk is the ongoing maintenance posture, not the code.** Four gaps:

1. **No pinned upstream provenance.** Neither fork records the upstream commit hash it was taken from, only a version in `go.mod`. There is no way to mechanically re-derive the diff, which means there is no way to confidently rebase or to prove no unintended change slipped in alongside the intended ones.
2. **No upstream advisory tracking.** A security fix landing in `iavl` v1.2.9+ or in the SDK's store module will not reach this chain through any dependency-update mechanism. Nothing in the repository watches for that. Both postmortem entries explicitly state that upstream review is not being tracked — reasonable for the *feature* patches, but it also means security patches are unmonitored.
3. **`govulncheck` does not see them.** Vulnerability scanning against the module graph will not analyze `replace`-directed local paths.
4. **`go mod verify` cannot check them.** It reports "all modules verified" while silently skipping both `replace`-directed local modules, so the verification step in this and prior reviews provides less assurance than it appears to.

**Impact:** A security-relevant upstream fix to IAVL or the SDK store layer will be silently missed. For a chain whose last four incidents were all in exactly this layer, that is the wrong blind spot to have.

**Remediation:**

1. **Record provenance.** Add a `PATCHES.md` (or per-fork header) naming the exact upstream commit hash, the tag, the date, and a one-line summary of each functional change. Add a CI check that regenerates the diff against that hash and fails if it does not match the recorded change set.
2. **Subscribe to upstream security advisories** for `cosmos/iavl` and `cosmos/cosmos-sdk`, and add a quarterly rebase-review item.
3. **Run `govulncheck` against both patch modules explicitly**, not just the main module.
4. **Note in the verification procedure that `go mod verify` skips replaced modules**, so future reviews do not over-read that result.

---

### M-9: Mint Subsystem and Admin Fee Waiver Remain on Log-and-Continue — Contract Drift Still Undecided (Medium, Carryover from 2026-05-09 M-2 and M-3, Not Started)

> **Status (2026-08-06): Documented — decision recorded, code deliberately unchanged.** [`docs/architecture/adr-mint-log-and-continue.md`](../../architecture/adr-mint-log-and-continue.md) accepts the exception with the rationale this finding asked for, cross-referenced at both sites. This is the "accept and document" outcome the finding argued H-1 made stronger; it should not be re-raised.

**Location:** `x/core/keeper/keeper.go` `mintAndDistribute` / `MintIfNeeded`; `x/core/module/module.go` lines 298–325 (admin branch of `deductRelayGasFee`).

Both carryovers are unchanged in substance. `MintIfNeeded` still logs and continues on `MintCoins`, `SendCoinsFromModuleToAccount`, `BurnCoins`, `IterateValidators`, `LegacyNewDecFromStr`, and `ResetAllRelayCredits` failures. The admin branch still returns `nil` when `DeductFeeFromOwner` fails (the only change is the log level, `Error` → `Warn`).

The previous review asked for an explicit decision — align with fail-fast, or document the exception and its rationale. Neither happened, so the drift persists into a third cycle. Consolidating them here because they are the same shape and the same decision.

Worth noting: **H-1 makes the case for "accept and document" materially stronger than it was.** The previous review argued fail-fast carried less liveness risk than previously thought because the v1.25.0 cutover landed cleanly. The 2026-07-12 halt is direct evidence the other way. The mint subsystem is a good candidate for a documented exception rather than adding more fatal halt sites.

**Remediation:** Make the decision and write it down, in an ADR or a doc comment at each site. If accepting, state the rationale (mint latency and liveness budget versus halt risk, informed by 2026-07-12) so the next review does not re-raise it. If aligning, do so only after H-1's halt mechanism is fixed.

---

### L-1: `computeDifficultyFactor` Uses `math.Pow` on `float64` in a Consensus Decision (Low)

**Location:** `app/ante_pow.go` lines 1200–1226, reached from `computeTarget` (1229–1238) and `validatePoWBytesArgon2` (1280).

```1213:1221:blockchain/app/ante_pow.go
	pow := math.Pow(1+powFactor, float64(difficultySteps))
	if math.IsNaN(pow) || math.IsInf(pow, 0) {
		return corekeeper.MaxSafeDifficultyFactor, nil
	}
	factorFloat := float64(corekeeper.BaseDifficultyFactor) * pow
	if factorFloat > float64(corekeeper.MaxSafeDifficultyFactor) {
		return corekeeper.MaxSafeDifficultyFactor, nil
	}
	factor := uint64(math.Round(factorFloat))
```

The resulting `factor` divides the PoW target, so it directly decides whether a transaction is accepted. Two ways this can differ between nodes: Go's spec explicitly permits fusing floating-point operations (FMA) differently across architectures, and `math.Pow` has architecture-specific assembly implementations on some platforms. A one-ULP difference that crosses a `math.Round` boundary shifts `factor` by one, shifts the target, and can flip the accept/reject decision for an envelope whose hash sits at the boundary — producing app-hash divergence.

Practical likelihood is very low: the validator fleet is homogeneous amd64, boundary-adjacent hashes are rare, and the function is well-guarded against NaN/Inf and clamped at both ends. Other live economics fields also use `float64` (`mint_dynamic_split`, `subscription_reserve_percent`, and tier vote weights), though they avoid `math.Pow`; their validation currently rejects out-of-range finite values but must also reject NaN and infinities explicitly.

**Remediation:** Compute the factor in integer or `big.Int` fixed-point. `(1+powFactor)^steps` scaled by a fixed denominator is straightforward with `big.Int` exponentiation, and it eliminates the class rather than bounding it. Add a determinism test asserting a fixed input table produces a fixed factor table, and reject non-finite values for every float-backed parameter in `Params.Validate`.

---

### L-2: `ResetAllRelayCredits` Deletes During Iteration and Ignores Delete Errors (Low)

**Location:** `x/core/keeper/keeper.go` lines 1060–1072.

The function iterates the relay-credit prefix and deletes keys inside the iteration callback. Mutating a store during iteration is undefined behavior in some Cosmos store implementations and, at minimum, is a pattern that behaves differently across store backends — a meaningful concern here, where the store layer is a vendored fork. Delete errors are also discarded, so a partial reset is silent, and it is called from the mint path where a partial reset means credits carry over on one node but not another.

**Remediation:** Collect keys in the iteration, close the iterator, then delete — the same collect-then-close-then-write shape the store/v2 patch itself adopted in `pruneCommitInfo` to avoid an iterator/writer deadlock. Propagate delete errors to the caller.

---

### L-3: v1.28.0 Store Deletion Is Split Across the Load Phase and the Upgrade Handler (Low)

**Location:** `app/upgrades.go` lines 2170–2228.

The v1.28.0 upgrade removes the circuit-breaker store. The `Deleted` store list is applied by `SetStoreLoader` during the load phase, while the handler's state migration runs in a separate phase. The two are not atomic: an interruption between them leaves the physical store deleted with the migration incomplete, or the reverse.

The blast radius here is small — the deleted store was dormant — but the pattern is what matters, because it will be reused for the next store removal, and store removals are exactly the operation where a partial application is hardest to diagnose.

**Remediation:** Document the ordering contract at the `SetStoreLoader` call site so the next author understands the two phases are independent. If a future removal touches a store with live state, add a sentinel key written by the handler and asserted at the start of the next block.

---

### L-4: `RecordPoWMessage` Write Failure Is Swallowed by Its Ante Caller While Its Read Path Panics (Low)

**Location:** `x/core/keeper/keeper.go` lines 1707–1730, called from `app/ante_pow.go` lines 324–326.

The 2026-06-22 sweep made `RecordPoWMessage`'s read-before-increment panic on a `store.Get` error. The keeper returns the `store.Set` error to its caller, and the ante caller logs and ignores it. The counter feeds the sliding window that drives `SetCurrentDifficulty`, so a dropped increment on one node yields a different difficulty than its peers.

The read path halting while the write path is ignored is contract drift within a single function that the same sweep touched.

**Remediation:** Reject the transaction on a `RecordPoWMessage` error in the ante, matching the read path's severity. The counter is a consensus input; an ante rejection is the cheap, correct response and does not add a panic site.

---

### L-5: `getUserLevel` Returns `(0, "")` for a Malformed Pubkey (Low, Carryover from 2026-05-09 L-3, Not Started)

> **Status (2026-08-06): Fixed in v1.31.0.** `requireEnvelopePubkey` rejects a non-33-byte pubkey before any routing or PoW work, exactly as recommended.

**Location:** `app/ante_pow.go` lines 89–92.

Unchanged. A non-33-byte `EnvelopePubkey` is silently normalized to level 0 with an empty address and routes through the free-tier PoW branch. Not exploitable — `RelaySigDecorator` rejects the malformed envelope later — but it is silent normalization of malformed input in the ante path, and it means the expensive PoW branch runs for input already known to be invalid (compounding M-1).

**Remediation:** Unchanged — reject non-33-byte pubkeys at the top of `AnteHandle`, before any `getUserLevel` / `canUsePoW` / `routePoWTx` call.

---

### L-6: `ProcessProposal` Performs Minimal Validation Only (Low, Carryover from 2026-05-09 L-4, Not Started)

> **Status (2026-08-06): Accepted Risk.** Deliberately unchanged. The finding suggested revisiting it alongside M-1's ante ordering; M-1 is fixed, and moving signature verification ahead of Argon2 removed most of the proposer-DoS concern that motivated this. No test required, per the finding's own retest guidance.

**Location:** `app/app.go` `ProcessProposal`.

Unchanged for a third cycle. Not a signer bypass; potential proposer DoS. Given M-1's finding that PoW verification is unauthenticated and expensive, this is worth revisiting together with the ante ordering rather than in isolation.

---

### L-7: `routePoWTx` Logs a Normal User-Error Rejection at `Error` Level (Low, Carryover from 2026-05-09 L-5, Not Started)

> **Status (2026-08-06): Fixed in v1.31.0.** The insufficient-reserve branch now logs at `Warn`.

**Location:** `app/ante_pow.go` lines 137–152.

Unchanged. The consensus-fatal profile-decode branch and the routine "paid user has insufficient reserve" branch both log at `Error`. Operators grepping for `Error` see false positives mixed with incident-class events. This was listed as trivial cleanup in the previous review and remains undone.

**Remediation:** Lower the insufficient-reserve log to `Warn`.

---

### L-8: Relay Allowlist Parity Holds Today but Is Unpinned (Low, Downgraded from 2026-05-09 M-4)

> **Status (2026-08-06): Partially fixed — STILL OPEN.** A shared registry exists, `isRelayMessage` derives from it, `TestRelayMessageRegistryParity` pins the two together, the dead `MsgSetLevel` branch is gone, and `EnsureAccountsDecorator` carries its scope comment. **But the `PowDecorator` and `RelaySigDecorator` switches are still hand-maintained and no test ties them to the registry**, so a message added to the registry but omitted from one switch would still pass — the exact bypass class this finding describes.

**Location:** `app/app.go` lines 221–238 (`isRelayMessage`), `app/ante_pow.go` `AnteHandle` switch, `app/ante_metasig.go` `RelaySigDecorator` switch, `app/ante_ensure_accounts.go` lines 43–71.

Mechanically enumerated all four switches this cycle. `isRelayMessage` covers 26 message types; the PoW switch and `RelaySigDecorator` cover **exactly the same 26** — no message is missing PoW or signature verification. This is better than the previous review implied and justifies the downgrade from Medium.

Two residual notes:

- `RelaySigDecorator` still handles `MsgSetLevel`, which is not in `isRelayMessage`. A `MsgSetLevel` transaction routes to `stdAnte`, so the branch is unreachable — dead code, not a gap, but it is the kind of dead code that reads as intentional coverage.
- `EnsureAccountsDecorator` covers 13 of the 26. This is benign: it only ensures the *authority* account (always a validator or module address, which always exists) and the SDK signer accounts, not the envelope user's. Worth a comment saying so, since the partial list otherwise looks like an oversight.

The finding stays open only because nothing *enforces* the parity. A new relay-eligible message added to one switch and not the others revives the original bypass class, and the parity is currently maintained by discipline alone.

**Remediation:** Unchanged from the previous review — a single shared registry consumed by all switches, or a parity test that enumerates `isRelayMessage` and asserts the other two handle each entry. Remove the `MsgSetLevel` branch, and comment `EnsureAccountsDecorator`'s scope.

---

### I-1: Two Production Divergences Remain Unrooted, and the Highest-Value Prevention Item Is Open (Informational)

> **Status (2026-08-06): Not Started — re-confirmed open.** A read-only inventory of all four hosts during the v1.32.2 deploy showed `indexer` and `backend` still running in the same container as the validator on every host. The co-location that correlates with every divergence and prune-hole event to date is unchanged, and this remains the highest-value open item in the document.

The 2026-06-16 postmortem tracks four prod-only divergence events (2026-05-25 h4854225, 2026-06-12 h5280036, 2026-06-14 stall, 2026-06-16 h5378001). The 06-12 event was root-caused to the IAVL fast-node stale read and fixed. The 05-25 and 06-16 events are not pinned to a line; action item 10 is partially done and item 11 (in-process app-hash self-check) is open.

The correlation evidence is strong and consistent across every incident: only the two public validators — the only nodes running the indexer, backend `simulate`, and reward distributor against their own ABCI state concurrently with block execution — have ever diverged or hit a prune hole. The other two validators, running neither the local query load nor active pruning, have never had either. The postmortem's action item 5 (point local workloads at a separate non-validating full node) is self-assessed as the highest-value open item, and this review agrees. It is an infrastructure change and therefore outside `blockchain/` scope, but every finding in this document about read-path determinism is downstream of it.

Also open from that postmortem: item 7 (end-to-end auto-recovery smoke test in prod — the `ssh`/serve path failed silently for an unknown period and was only discovered mid-incident) and item 11.

---

### I-2: `upgrades.go` Carries 42 Registered Handlers in a Single 2,279-Line File (Informational)

Every upgrade handler since genesis lives in one file, including one-shot data migrations that can never run again on any live chain. This is only a maintenance concern — the handlers are correct and gated by name — but H-2 is a direct consequence of its shape: determining whether Solana bridging is enabled required manually tracing param mutations across 42 handlers and 2,279 lines, and there is no test asserting the resulting end state of `BridgeChains` or any other param.

**Suggestion:** Split by release range, and add a test that applies all handlers in order against a genesis state and asserts the resulting params — which would have caught H-2 mechanically.

---

### I-3: Genesis `raw_state` Remains a Full Trust Anchor (Informational, Carryover)

Unchanged from 2026-05-09 I-2. A tampered genesis with corrupt `raw_state` for the `params` key halts on the first `BeginBlock` rather than silently running on defaults — strictly better than the pre-v1.25.0 behavior. Note the halt is a zombie per H-1, which for a fresh node is less serious (the operator is watching) but is the same mechanism.

---

### I-4: Delete Authorization Remains Indexer-Enforced by Design (Informational, Carryover)

Unchanged from 2026-05-09 I-1 and prior. Documented architecture boundary.

---

## Prior Finding Status

> **This table describes the 2026-08-04 baseline and is stale.** Every "Not
> Started" below was remediated in v1.31.0. The bridge row's deferral is moot —
> the bridge was removed. See the [retest](blockchain-retest.md).

| Prior finding | Current status |
| :--- | :--- |
| 2026-05-09 M-1 — BeginBlock reserved-profile bootstrap | **Not Started.** Re-raised as M-6. Was the previous review's #1 recommendation. |
| 2026-05-09 M-2 — Mint `log-and-continue` | **Not Started (no decision recorded).** Consolidated into M-9. H-1 strengthens the case for documented acceptance. |
| 2026-05-09 M-3 — Admin fee waiver | **Not Started (log level `Error`→`Warn` only).** Consolidated into M-9. |
| 2026-05-09 M-4 — Relay allowlist parity | **Substantially Improved.** All three switches now cover exactly the same 26 message types (mechanically verified). Downgraded to L-8; still unpinned by a test. |
| 2026-05-09 M-5 — `processSubscriptions` short-circuit | **Not Started.** Re-raised as M-7. |
| 2026-05-09 L-1 — Bridge handler routing active despite dormancy | **Escalated to H-2.** The dormancy premise itself is contradicted: v1.9.0 enabled Solana and nothing removed it, and `bridgeAttestMinted` never calls `ValidateBridgeChain`. The recommended kill-switch is still Not Started. |
| 2026-05-09 L-2 — PoW block-hash window empty at upgrade | **Closed.** Historical; window long since full. |
| 2026-05-09 L-3 — `getUserLevel` malformed pubkey | **Not Started.** Re-raised as L-5. |
| 2026-05-09 L-4 — `ProcessProposal` validation | **Not Started.** Re-raised as L-6. |
| 2026-05-09 L-5 — `routePoWTx` log severity | **Not Started.** Re-raised as L-7. Trivial. |
| 2026-05-09 I-1 — Delete authorization | Unchanged. Now I-4. |
| 2026-05-09 I-2 — Genesis raw_state | Unchanged. Now I-3. |
| 2026-05-09 I-3 — Patched IAVL tracking | **Materially expanded and now in scope.** A second fork (store/v2) was added and both were audited in full. Re-raised with specific gaps as M-8. |
| 2026-04-24 H-1/H-2, M-2/M-3/M-6/M-7, L-6 (bridge scope) | **Not Started.** Deferral is contingent on H-2's operator verification; if the bridge is enabled these are live, not dormant. |

---

## Positive Security Controls Observed (this cycle)

- **`GovAuthorityDecorator` closes the gov-authority spoofing class completely.** Any transaction carrying a message whose `GetAuthority()` equals the gov module address is rejected outright, on the correct reasoning that legitimate gov-executed messages are dispatched by the gov EndBlocker and never traverse ante handlers. Critically, it is wired on **both** paths — `mirageAnteRouter` forces any gov-authority transaction onto the non-relay branch (resetting both routing flags and breaking), and `govDec` is also third in the relay chain. The `if m.Authority == govAuthority { continue }` branches scattered through `PowDecorator` and `RelaySigDecorator` — which skip both PoW and signature verification — are consequently unreachable. Verified by tracing all message-ordering permutations through the router.
- **Envelope replay protection is correct and fails closed.** Per-pubkey-hash nonce with expiry: nonce must be non-zero, `HasEnvelopeNonce` rejects reuse, `SetEnvelopeNonce` write failures propagate and reject the transaction, and `HasEnvelopeNonce` now panics rather than returning `false` on a store error (the June sweep). Combined with the timestamp window this is a solid anti-replay design.
- **The June 2026 fail-fast sweep is thorough within its family.** Eight consensus-path readers converted from silent-default to tagged `CONSENSUS_FATAL:*_STORE_GET` panic, with absent-key semantics correctly preserved as the default, pinned by `TestConsensusReadsPanicOnStoreGetFailure` and `TestConsensusReadsReturnDefaultsOnAbsentKey`. `GetRelayCredit` is the one omission (M-3). The mechanism is wrong (H-1); the coverage is right.
- **Both vendored patches are correct, minimal, documented in place, and regression-tested.** Nine functional changes total across 32,735 lines of vendored code — a genuinely restrained diff. The Set-then-Delete reorder plus flush-and-re-probe is the right two-layer fix for the prune-hole false positive, and each test was verified to fail on the pre-fix code. Both underlying bugs were filed upstream.
- **`AssertSupplyInvariant` is the right kind of control.** A cheap-to-state, impossible-to-violate-under-correct-execution identity checked every block. It caught real corruption. The concern in M-2 is its cost and its halt mechanism, not its existence.
- **Idempotent `app.Close()` via `sync.Once`** correctly fixes the fleet-wide `pebble: closed` shutdown panic at the right level — the app wrapper, covering every DB `BaseApp.Close` touches — after a first attempt that only wrapped one of the two handles. Pinned by `TestAppCloseIsIdempotent`, verified to fail without the fix.
- **`MaxSafeDifficultySteps` is checked before any target computation**, bounding the difficulty input before it reaches the float path, and the factor is clamped at both ends.
- **`Params.Validate()` is comprehensive**, with explicit bounds on every numeric parameter including the award-config cost cap added in v1.24.0.
- **Postmortem discipline is exceptional.** The 2026-06-16 postmortem records refuted hypotheses as prominently as confirmed ones (the memory-pressure theory is explicitly retracted with evidence), marks two of its own fixes as failed, and tracks 14 action items with honest status. This review's H-1 is derived almost entirely from evidence the team documented against itself.

---

## Test Coverage Gaps

> **Seven of these eleven gaps are now closed** and one is moot. Only three remain
> open: the PoW verification benchmark, the M-5 wedged-user regression, and the
> M-6 bootstrap idempotence test. The relay-parity gap is half closed. Current
> state is tabulated in the [retest](blockchain-retest.md).

- **No test enumerating `CONSENSUS_FATAL` sites or asserting the halt mechanism terminates the process.** The 2026-07-12 halt is unrepresented in the test suite. See H-1.
- **No test asserting the end state of `params.BridgeChains` after applying all upgrade handlers in order.** Would have caught H-2 mechanically. See H-2 and I-2.
- **No benchmark pinning per-envelope PoW verification cost**, so a parameter change could silently worsen M-1.
- **No test asserting ante-chain decorator ordering.** The security-relevant property (signature verification before expensive work) is currently implicit in a slice literal.
- **No instrumentation or bound on `AssertSupplyInvariant` iteration cost.** See M-2.
- **No relay-allowlist parity test.** Parity holds today by discipline. See L-8.
- **No regression test for the BeginBlock reserved-profile bootstrap error swallow.** Carryover. See M-6.
- **No regression test for `processSubscriptions` with a corrupt profile on the one-time-payment path.** Carryover. See M-7.
- **No test for the wedged-paid-user scenario** in M-5 (level ≥ 1, zero reserve, attempts an ordinary relay message).
- **No determinism test for `computeDifficultyFactor`** over a fixed input table. See L-1.
- **No `govulncheck` run against the patch modules**, and `go mod verify` silently skips them. See M-8.

---

## Prioritized Recommendations

> **Items 1–10 are done; item 11 is not.** Recommendations 1 through 10 were
> implemented in v1.31.0–v1.32.2, with two deltas from what is written below:
> H-2 was resolved by removing the bridge rather than gating it, and M-9 was
> accepted-and-documented rather than aligned. **Item 11 (isolating validators
> from local query traffic) remains open** and was re-confirmed unchanged on the
> fleet on 2026-08-06. Partial: item 3's benchmark and item 7's L-8 switch parity.

1. **Fix the halt mechanism (H-1).** Convert `CONSENSUS_FATAL` from `panic()` to process termination so a halting node is unambiguously dead rather than a zombie. This is small, mechanical, and it retires an entire failure class that has already cost one full-chain halt. Then classify each of the 13 sites node-local versus deterministic, and validate params at governance-proposal time rather than at the next `BeginBlock` on every validator simultaneously.
2. **Verify live `bridge_chains` (H-2).** One query. If Solana is enabled, disable it, audit burn records for users whose funds were destroyed, and add the kill-switch. If it is not, correct the previous review's dormancy claim and add the kill-switch anyway.
3. **Reorder the relay ante chain and the PoW hash check (M-1).** Move `RelaySigDecorator` ahead of `PowDecorator`, and hoist the `last_block_hash` check above the Argon2 call. Two small changes that remove a 1.76 ms / 4.2 MB unauthenticated amplification factor.
4. **Measure and redesign `AssertSupplyInvariant` without weakening it (M-2).** A supply-delta check is useful but does not detect the missing balance write from the incident it guards against. Keep the full identity check until an O(1) design independently tracks aggregate balances and recorded supply.
5. **Close the last silent-default in the mint input path (M-3, M-4).** `GetRelayCredit` and `RelayAccountingDecorator` are the remaining places where a store failure silently changes token distribution with no log line.
6. **Establish patch provenance and advisory tracking (M-8).** A `PATCHES.md` with upstream commit hashes, a CI diff check, `govulncheck` against both modules, and a subscription to upstream advisories. Cheap insurance for the layer where the last four incidents occurred.
7. **Clear the carryovers (M-6, M-7, L-5, L-7).** Four findings now unaddressed across two review cycles, one of which (M-6) was the previous review's top recommendation and one of which (L-7) is a one-line change.
8. **Decide M-9 explicitly** and write the decision down, so the third cycle is the last time it is raised.
9. **Fix the wedged-user path (M-5)** — a real product bug where the intended remediation for an expected condition is unconditionally rolled back.
10. **Eliminate floating exponentiation from consensus (L-1).** Use exact rational/integer arithmetic in `computeDifficultyFactor` and reject all non-finite float-backed parameters.
11. **Support the infrastructure work in I-1.** Isolating the validators from local query traffic is outside this repository, but it is the single change most likely to stop the recurring divergence class, and the correlation evidence has only strengthened.

---

## Verification Performed

- Inventoried tracked blockchain source: 81 Go/proto files excluding generated `*.pb.go` and `patches/`, 87 including generated, plus 143 Go files across the two vendored forks.
- Diffed the full tree against the previous review baseline `4c9bcf11..1d3ab707`: 154 files, +25,773 / −1,996. Excluding `patches/`: 25 files, +1,647 / −1,793 — a net reduction, confirming the vendored forks are the entirety of the growth.
- Read every functional change in both vendored forks (nine total) and their regression tests.
- Read the 2026-06-16 postmortem in full and cross-checked its claims against source: the `MutableTree.Get` fast-node removal, the Set-then-Delete reorder, the flush-and-re-probe guard, the `sync.Once` `Close`, the async-pruning revert, and the eight fail-fast conversions were all verified present as described.
- Mechanically enumerated and diffed the message-type sets of `isRelayMessage`, the PoW `AnteHandle` switch, `RelaySigDecorator`, and `EnsureAccountsDecorator` (26 / 26 / 27 / 13).
- Traced every `params.BridgeChains` mutation across all 42 registered upgrade handlers.
- Traced all message-ordering permutations through `mirageAnteRouter` to confirm gov-authority transactions cannot reach the relay path.
- Confirmed against Cosmos SDK `baseapp.runTx` that ante-handler state mutations are discarded on the error path (basis for M-5).
- Benchmarked production Argon2 parameters (`t=1, m=4096 KiB, p=1, 32 B`): 1,764,989 ns/op, 4,198,670 B/op, 24 allocs/op on an Intel Core Ultra 9 285K (basis for M-1).
- Grepped all `float64`/`float32` uses in consensus paths. `computeDifficultyFactor` is the direct cross-architecture exponentiation risk in L-1; parameter validation must also reject non-finite values before other float-backed economics fields are used.
- Counted literal `panic(...CONSENSUS_FATAL...)` call sites with syntax-aware inspection: 13 across two files (basis for H-1).
- `go build ./...` — clean.
- `go vet ./app/... ./x/core/...` — clean.
- `go test ./app/... ./x/core/... ./orchestrator/...` — all packages pass.
- `go test ./...` in `patches/iavl` — passes.
- `go test ./...` in `patches/cosmos-sdk-store-v2` — passes except `store/v2/streaming`, which fails on a go-plugin handshake requiring a real plugin binary. Environmental, unrelated to the patch, and the patched `rootmulti` package passes.
- `go mod verify` — "all modules verified" (note: this silently skips both `replace`-directed local modules; see M-8).
- All Go commands run in a `golang:1.25` container with the repository root mounted, since no local toolchain is installed.

---

## Assumptions

- Production servers were not contacted. All statements about live chain state are derived from source and from committed postmortems; **H-2 in particular requires operator verification before it can be triaged.**
- Validators are honest-majority for governance and bridge attestation assumptions.
- External Solana program correctness is out of scope.
- Indexer authorization for delete/edit visibility remains an accepted architecture boundary.
- The 2026-06-16 postmortem's account of the 2026-07-12 halt — specifically that CometBFT's `receiveRoutine` recover leaves the process alive with consensus stopped — is taken as accurate observed behavior. H-1's remediation does not depend on that specific mechanism being the only one; process termination is the correct halt semantics regardless.
- The 2026-06-12 root cause (IAVL fast-node stale read) is taken as correctly attributed. This review audits whether the remediations are sound and whether they introduced regressions; it does not re-derive that root cause.
- Ops-layer tooling (`divergence_watchdog.py`, `recover.sh`, `stuck_node_alert.py`) is assumed to work as its documentation describes, except where the postmortem records otherwise. H-1 argues the blockchain should not depend on that assumption.

---

## Follow-up Retest Guidance

> **Done 2026-08-06:** [`2026-08-04/blockchain-retest.md`](blockchain-retest.md).
> Note that `review-2026-03-12-retest.md`, named below as the pattern to follow,
> **does not exist in this repository** — the retest follows
> [`2026-08-05/backend-retest.md`](../2026-08-05/backend-retest.md)
> instead, the only retest precedent actually present.

If remediation lands in the same release cycle, produce `docs/security/2026-08-04/blockchain-retest.md` following the pattern in `review-2026-03-12-retest.md`:

- Header with `Scope`, `Baseline` (post-remediation commit), and `Previous review: 2026-08-04/blockchain-review`.
- `## Remediation Status — Review 2026-08-04` table with columns `ID`, `Title`, `Status` (Fixed / Accepted Risk / Documented / Not Started), `Notes`.
- Include every finding: `H-1`–`H-2`, `M-1`–`M-9`, `L-1`–`L-8`, `I-1`–`I-4`.
- For bridge-scoped findings, only mark `Fixed` once the kill-switch exists in code — params-only remediation is not sufficient, since params-only dormancy is exactly what H-2 shows cannot be relied upon.

Minimum retest evidence expected per finding:

- **H-1**: halt mechanism converted to process termination, with a test that drives a `CONSENSUS_FATAL` condition and asserts the process exits non-zero rather than continuing; plus a classification comment at each of the 13 sites and an inventory test asserting the count and classifications.
- **H-2**: operator confirmation of live `bridge_chains`; `params.BridgeEnabled` kill-switch checked in all three bridge handlers including `bridgeAttestMinted`; a unit test asserting rejection regardless of `BridgeChains` content; and, if the bridge was live, an audit of `BridgeBurnRecord` entries.
- **M-1**: ante chain reordered with a test pinning decorator order; `last_block_hash` check hoisted above the Argon2 call; a benchmark pinning per-envelope cost.
- **M-2**: incremental delta check replacing the full scan, with a test that injects a supply/balance mismatch and asserts detection; or, if the scan is kept, duration instrumentation plus an every-N-blocks cadence.
- **M-3 / M-4**: fail-fast conversion with store-error injection tests, matching the existing `TestConsensusReadsPanicOnStoreGetFailure` pattern.
- **M-5**: regression test for a level-1 user with zero reserve — downgraded exactly once, able to transact afterwards.
- **M-6**: sentinel-gated one-shot bootstrap (preferred over a new panic site), with a test asserting it is a no-op on subsequent blocks.
- **M-7**: profile decode moved above the `SubscriptionPeriod == 0` short-circuit, with a corrupt-profile test.
- **M-8**: `PATCHES.md` with upstream commit hashes; CI diff check against those hashes; `govulncheck` output for both patch modules.
- **M-9**: an ADR or in-code doc comment recording the decision and its rationale.
- **L-1**: integer fixed-point implementation plus a fixed input/output determinism table.
- **L-2**: collect-then-close-then-delete with propagated errors.
- **L-3**: documented ordering contract at the `SetStoreLoader` call site.
- **L-4**: ante rejects on `RecordPoWMessage` error, with an injection test.
- **L-5**: malformed-pubkey-length rejection test at the top of `AnteHandle`.
- **L-6**: no test required if accepted.
- **L-7**: log severity change verified by diff.
- **L-8**: parity test enumerating the shared registry; `MsgSetLevel` branch removed; `EnsureAccountsDecorator` scope commented.

---

## Post-remediation dependency scan — 2026-08-04

`make govulncheck` now scans the main module and both replacement modules even
when an earlier scan fails. `blockchain/go.mod` requires Go 1.25.12 or newer;
the release is built with the distribution-packaged Go 1.26.5, and the results
below were verified on both toolchains. Together with patched dependency
versions for gRPC, `x/net`, `x/text`, OpenTelemetry, and quic-go, this removed
all ten advisories that had an upstream fix, and no standard-library advisory
is reachable on either toolchain. Both replacement modules scan clean.
Standard-library reachability depends on the toolchain that builds the release,
so re-run `make govulncheck` and revise this section whenever it moves.

Two main-module advisories remain and keep the target non-zero. Neither has an
upstream fixed version:

- `GO-2026-5932` reaches the unmaintained OpenPGP package through the Cosmos SDK
  keyring CLI. Mirage production uses the `test` keyring backend, not the
  OpenPGP-backed file backend.
- `GO-2026-4479` reaches Pion DTLS through CometBFT's optional libp2p/WebRTC
  transport. Mirage explicitly leaves `[p2p.libp2p] enabled=false` and uses
  CometBFT P2P.

These are residual dependency risks, not clean scan results. Recheck both on
every dependency refresh and remove the transitive packages when Cosmos SDK or
CometBFT provides a supported path.
