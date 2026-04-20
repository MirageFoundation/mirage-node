# AppHash Divergence Investigation — Block 4015233

**Date**: 2026-04-20
**Incident**: `mirage.talk` (PROD) stalled, frontend showing "node catching up".
**Root symptom**: AppHash mismatch on block 4015234, caused by divergent state produced while executing block 4015233 on half the validator set.

---

## TL;DR

At block **4015233**, two of four validators (including `mirage.talk` / `159.203.114.27`) computed a different AppHash from the other two. The divergence is a **74,486,000 umirage** excess in the `fee_collector` balance that the sick set burned during `BeginBlock`.

- Sick burn: `2827221501 umirage`
- Healthy burn: `2752735501 umirage`
- Delta: `74486000 umirage`  (≈ the exact fee from block 4015231's single tx)

**Paradox**: block-results `app_hash` for block **4015232** is byte-identical on sick and healthy nodes, which means the IAVL state root (including `fee_collector` balance) was provably identical going into block 4015233. Yet one block later, `BurnAllFromModuleName` reads different balances.

Something writes 74,486,000 umirage into `fee_collector` on the sick validators between the commit of 4015232 and the core module's `BurnAllFromModuleName` call inside the 4015233 `BeginBlocker`. That "something" is the non-deterministic culprit we are hunting.

---

## Cluster state (at time of investigation)

| Node                 | Role       | Height   | App Hash (prefix) | Status               |
|----------------------|------------|----------|-------------------|----------------------|
| **159.203.114.27 (mirage.talk)** | validator  | 4015233  | `D18DF844…` (wrong) | **stalled, prevote nil** |
| 64.23.136.132 (mirage.vote)  | validator  | ~4022168 | `E3E2C046…`  | healthy              |
| 146.190.108.140      | validator  | ~4022167 | `EF8C80B2…`  | healthy              |
| 139.59.9.96          | validator  | ~4022168 | `8B2F555D…`  | healthy              |

All four run the identical binary `v1.23.7-11-g54dfbbb`, so this is NOT a version mismatch.

**Only one node (mirage.talk) is sick.** The network has ⅔ agreement and is making blocks. mirage.talk computed a wrong apphash for block 4015233, committed it locally, and is now stuck because its local state doesn't match the canonical chain.

This is **single-node non-determinism**. The cause is node-specific (hardware fault, in-memory state pollution, or a race condition that happened to fire on this one node).

---

## Evidence chain

### 1. `block_results.app_hash` agreement up to 4015232

```
h=4015230 sick=/eHpLFUZHcvuYgcAkpISwkMZgNSzXJFN7pRtyRlIM30= ok=/eHpLFUZHcvuYgcAkpISwkMZgNSzXJFN7pRtyRlIM30= match=YES
h=4015231 sick=ow1rvlr7tVHqNKS7DY4I1MYklM6QVRPe+Te8mV7RAoM= ok=ow1rvlr7tVHqNKS7DY4I1MYklM6QVRPe+Te8mV7RAoM= match=YES
h=4015232 sick=SGSjFps7b54TmHZbgto2ZVCM5+FvsHz7Yqdok2ygVcs= ok=SGSjFps7b54TmHZbgto2ZVCM5+FvsHz7Yqdok2ygVcs= match=YES
h=4015233 sick=0Y34RKHe4y0MtG6wad4E9GSU3D81dslpjS34umd/uQI= ok=qeTC3Vl6XyHKDLRNeKEt+td6A1dOyWS6+Gdd2m/3tfA= match=NO
```

→ IAVL state identical after 4015232 on both sides.

### 2. Tx in 4015233 is deterministic

Block 4015233 contains one tx (`MsgSetAgents`). Its `tx_result` on sick and healthy is bit-identical:

- `code=0`, `gas_used=59261`
- Same 5 events, same attribute ordering, same values.

→ Divergence is NOT inside the tx handler.

### 3. Only divergence is in BeginBlock burn

A full json diff of `/block_results?height=4015233` between sick and ok shows **exactly five lines differ**, all the same pair of numbers, all in the "fee_collector → core → burn" chain:

```
<           "value": "2827221501umirage"     (sick)
>           "value": "2752735501umirage"     (ok)
```

Specifically these five events in order:
1. `coin_spent` from fee_collector (`mirage17xpfvakm2amg962yls6f84z3kell8c5lxzd6yx`)
2. `coin_received` by core (`mirage1p4zltl2x9wx8p0lmzqpp4sdulul43u5m96x969`)
3. `transfer` fee_collector → core
4. `coin_spent` from core
5. `burn` by core

All are emitted by `Keeper.BurnAllFromModuleName(ctx, authtypes.FeeCollectorName)` called in `x/core/module/module.go BeginBlock`:

```1127:1141:blockchain/x/core/keeper/keeper.go
func (k Keeper) BurnAllFromModuleName(ctx sdk.Context, moduleName string) error {
    if strings.TrimSpace(moduleName) == "" {
        return nil
    }
    srcAddr := authtypes.NewModuleAddress(moduleName)
    bal := k.bank.GetBalance(ctx, srcAddr, k.mintDenom()).Amount
    if !bal.IsPositive() {
        return nil
    }
    coin := sdk.NewCoin(k.mintDenom(), bal)
    if err := k.bank.SendCoinsFromModuleToModule(ctx, moduleName, types.ModuleName, sdk.NewCoins(coin)); err != nil {
        return err
    }
    return k.bank.BurnCoins(ctx, types.ModuleName, sdk.NewCoins(coin))
}
```

### 4. Events preceding the divergence are identical

`x/mint.BeginBlocker` mints `2752735501 umirage` into `fee_collector` — same on both nodes (events 0–6 identical).

Arithmetic:
- If sick burned 2827221501 right after mint → `fee_collector` on sick held `2827221501 − 2752735501 = 74486000` BEFORE mint.
- If ok burned 2752735501 right after mint → `fee_collector` on ok held `0` BEFORE mint.

So the pre-mint `fee_collector` balance differs by 74,486,000 umirage at the start of block 4015233, despite both nodes' committed state after 4015232 being byte-identical.

### 5. Shape of the missing coin: 74,486,000

This equals the transaction fee that would have been collected from block 4015231's one tx (it had `gas_used=70519`; typical gas price ×1000 ≈ 70,519,000 or similar). Confirmation pending, but the number pattern strongly suggests: **the fee from a past tx got re-added to `fee_collector` on sick nodes between the end of 4015232 and the BurnAll call of 4015233**.

---

## Where can a write to `fee_collector` come from between blocks?

Anything running AFTER block 4015232 committed and BEFORE `x/core.BeginBlocker` executes `BurnAllFromModuleName` in 4015233.

Order of operations inside 4015233 `FinalizeBlock`:

1. `PreBlockers`: `upgradetypes`, `authtypes`
2. `BeginBlockers`: `minttypes` → `coremoduletypes` → …  (the burn is the FIRST thing `coremoduletypes` does)

Between the mint event and the burn call there is no other module code. So for the balance to differ at the read, one of:

- **(a)** The mint itself ran twice on sick somehow (ruled out — mint event emitted once, same amount).
- **(b)** PreBlocker (`x/auth` or `x/upgrade`) wrote 74486000 to `fee_collector` on sick.
- **(c)** A PrepareProposal/ProcessProposal ante chain persisted state on sick.
- **(d)** Block 4015232's `EndBlock` or tx commit path did something only sick did (though apphash matched — which would mean non-deterministic *events* without non-deterministic *state*, impossible).
- **(e)** A prior ante handler (e.g. `MetasigDeductFeeDecorator`, `EnsureAccountsDecorator`) was invoked outside its exec-mode guard during ProcessProposal and wrote state that was later committed.

### Primary suspects identified so far

1. **`MetasigDeductFeeDecorator` in `app/ante_metasig.go`** deducts fees when `ctx.ExecMode()` is `ExecModeFinalize` *OR* `ExecModeSimulate`. If for any reason this decorator is reached with `ExecModeFinalize` on the persisted state during a PROCESS_PROPOSAL → FINALIZE sequence that re-runs antes without resetting the counter, a second deduction could sneak in. Needs code trace.

2. **`EnsureAccountsDecorator`** has no exec-mode guard and `SetAccount` every time. Cannot create coins, but confirms the pattern of writing-without-guards.

3. **`PowDecorator.recent` in-memory slice** (`app/ante_pow.go`) is explicit non-determinism: per-node in-memory buffer of recent block hashes used to accept/reject PoW txs. Could cause a tx to be accepted on some nodes and rejected on others → different fee collection. Needs a blocks-earlier check.

4. **`RelayAccountingDecorator`** writes to core keeper during `ExecModeSimulate` too. Simulate should use a cache context but worth auditing.

---

## Next steps

- [ ] Walk the full `relayAnte` chain and mark every decorator that writes state, with its exec-mode guard (or lack thereof).
- [ ] Audit `PrepareProposal`/`ProcessProposal` handlers to confirm antes there run on a discarded cache context.
- [ ] Reconstruct block 4015231's tx fee to confirm the exact 74,486,000 figure and identify the payer.
- [ ] On sick node, inspect x/bank's `fee_collector` balance directly via abci_query at height 4015232 vs 4015233 (pre-BeginBlock) to pin the insertion moment.
- [ ] Search for any code path that `SendCoinsFromAccountToModule(…, FeeCollectorName, …)` or `MintCoins` → transfer to fee_collector, unguarded.
- [ ] Check `x/auth` PreBlocker and `x/upgrade` PreBlocker for anything fee-collector-adjacent on this chain's version.

Updates will be appended below as each lead is resolved.

---

## Timeline log

- **T0**: Confirmed apphash match through 4015232; divergence at 4015233.
- **T1**: Confirmed tx execution identical; divergence isolated to BeginBlock.
- **T2**: Isolated divergence to exactly one value pair (2827221501 vs 2752735501) in `BurnAllFromModuleName(fee_collector)`.
- **T3**: Confirmed `74,486,000 umirage` is **exactly** the fee of block 4015231's tx `58DAD08…` — see `block_results?height=4015231`: `coin_received receiver=mirage17xpfvak... (fee_collector) amount=74486000umirage`.
- **T4**: Corrected cluster topology: **only 1 validator (mirage.talk) is sick**. The other three agreed, made blocks, the chain advanced to 4022168. This is **single-node non-determinism**, not a 2/2 split.
- **T5**: Queried sick IAVL directly:
  - `bank balance fee_collector --height 4015231` = `74486000` ✓ (fee collected)
  - `bank balance fee_collector --height 4015232` = `0`        ✓ (burned in 4015232 BeginBlock)
  - `bank balance fee_collector --height 4015233` = `62129000` (= new tx fee only — POST the divergent burn)
  - `total-supply-of umirage --height 4015232` = `109611337501889598`
  - `total-supply-of umirage --height 4015233` = `109611337427403598` (Δ = −74,486,000 — matches "extra" burn)
  - Fee payer `mirage1rd00m…` was debited once per block (74486000 in 4015231, 62129000 in 4015233) — **no double-charging**.
- **T6**: All 4 validators have byte-identical `app_hash` for block 4015232 → sick's committed IAVL state is provably identical to healthy at that height, including `fee_collector = 0`.
- **T7**: Ruled out via code & logs:
  - No duplicate `DeliverTx` invocation for `58DAD08…` (logs show exactly one `phase=check` + one `phase=deliver`).
  - No `phase=simulate` log with `fee=74486000` (only the check+deliver entries).
  - `MetaSignerDecorator` / `RelayGasFeeDecorator` fee deduction is properly guarded by `ExecMode ∈ {Finalize, Simulate}`.
  - `ProcessProposal` in `app.go` does NOT invoke ante handlers, so no state mutation there.
  - `PreBlockers` (`x/upgrade`, `x/auth`) do not touch bank. `x/auth.PreBlock` only calls `RemoveExpiredUnorderedNonces`.
  - Only caller that funds `fee_collector` from an account is `RelayGasFeeDecorator` on line 1158 of `ante_metasig.go` — gated by exec mode.
  - Between `x/mint.BeginBlocker` (which emits the 2752735501 mint events — same on sick & healthy) and `x/core.BeginBlocker.BurnAllFromModuleName` there is **no code** that touches `fee_collector`.
- **T8**: Host health on `mirage.talk` (`validator1` @ `159.203.114.27`):
  - OS uptime: **168 days**, no hardware errors in `dmesg` / `journalctl`.
  - No `panic` / `OOM` / restart in docker logs around the divergence.
  - Memory: 3.8 GiB total, **135–137 MiB free**, container used ~2 GiB of 3.8 GiB limit. Tight but not thrashing at divergence time.
  - **Swap: 0 B — confirmed `swapon --show` empty, `/proc/swaps` empty (header only), `/etc/fstab` has no swap entry, no `/swapfile`/`/swap`/`/swap.img` on disk, no `*.swap` systemd units.**
  - **All four validators in the cluster have 0 swap** (verified via `free -h` over SSH on every node) — the supposed "2 GiB swap" was never actually provisioned anywhere.
  - No ECC registers exposed, but no MCE messages either.

## Working conclusion

The 74,486,000 umirage that appeared in sick's `fee_collector` during block 4015233's `BurnAllFromModuleName` read is:

- **the exact fee amount from the tx committed two blocks earlier** (4015231),
- **not attributable to any code path** visible in the codebase that runs between the 4015232 commit and the x/core burn call, and
- **not explainable by proposer role, simulate leaks, or ante handler re-entry** in logs.

The committed state at 4015232 is objectively correct on sick (same apphash as healthy). The divergence appears during the execution of block 4015233's `BeginBlocker` on this one node — the read of `fee_collector`'s balance returned `2827221501` while the underlying committed IAVL says `0 + 2752735501 = 2752735501`.

**The most plausible remaining explanation is silent in-memory state corruption on the sick node**: an IAVL / rootmulti / pebble-level cache on the sick process retained a stale "2752735501 + leftover 74486000" view of `fee_collector`'s value for exactly that one read, despite the underlying committed KV being 0. The `CacheMultiStore` branched from `app.cms` inside `ProcessProposal(4015233)` inherited a stale entry from a prior cache generation that the 4015232 commit failed to invalidate.

Supporting circumstantial facts:

- 168-day host uptime, **0 swap (confirmed, not 2 GiB as previously assumed)**, and very low free RAM (~135 MiB) make subtle memory-pressure bugs (cache eviction races, partial allocation failures swallowed by Go's runtime, fragmented heap causing odd IAVL `nodeCache` evictions) significantly more likely. Without swap there is no soft-failure cushion — the kernel either kills or returns ENOMEM with no warning trail.
- Only one validator out of four is affected — consistent with a machine-local bug rather than an algorithmic non-determinism.
- The corruption amount matches a recent-history fee exactly, not a random number — consistent with a stale-cache read of a previous `fee_collector` state.
- No other state (validator set, distribution, payer balance, tx events) differs — the corruption is scoped to a single `GetBalance(fee_collector)` call during BeginBlock.

## Remediation plan

1. Stop `miraged` on `mirage.talk`.
2. Rollback local state to height 4015232 using `miraged rollback --hard` (or restore from a snapshot at ≤ 4015232).
3. Restart and let the node fast-sync from peers through block 4015234 onwards.
4. Host-level fixes to reduce recurrence probability:
   - Reboot host (flushes long-lived kernel caches).
   - **Add swap on ALL four validators** (≥ 2 GiB each) — verified today that none of them have any swap at all. The current 3.8 GiB with no swap is dangerously tight for a validator and gives the kernel no soft-fail buffer under memory pressure. This is the single highest-leverage operational fix.
   - Or raise the droplet's RAM (8 GiB+ recommended).
   - Schedule a periodic systemd restart of the node container (e.g. weekly) to bound in-memory state lifetime.
5. Code-level hardening (to catch this class of issue faster in the future):
   - Add an assertion at the top of `BurnAllFromModuleName(fee_collector)` that the pre-burn balance equals `expected = mint_amount` (with a log, not a panic, for diagnosability).
   - In BeginBlock of `x/core`, emit a custom event with both the pre-mint and post-mint `fee_collector` balance so any future divergence is instantly auditable from `block_results`.
   - Enable a periodic invariant check on total supply vs. sum of account balances.

## Open questions for follow-up

- Can we reproduce the stale-cache read deterministically by restoring the sick's PebbleDB dir onto a fresh host and replaying 4015233?
- Is `app.cms.CacheMultiStore()` inside `setState(execModeFinalize)` actually creating a fresh branch, or is there a version-tag bug that causes it to share a live cache with a previous FinalizeBlock?
- Should we disable in-memory caching in our rootmulti store config and see if the bug vanishes on a resynced sick host?

---

_Last updated: 2026-04-20. Investigation is closed on the SYMPTOM side with 100% confidence (the sick burn is 74,486,000 umirage = fee of tx in 4015231, read by `BurnAllFromModuleName(fee_collector)` during 4015233 BeginBlock). Root cause on the process side is narrowed to "stale cache in `app.cms`/rootmulti on the sick node"; definitive confirmation requires restoring sick's PebbleDB on a fresh host and re-running the block._

---

## Recovery outcome (2026-04-20 ~19:18 UTC)

**Val1 is fully recovered and back in consensus.**

### What we did

1. Ran `scripts/backup_restore.py restore --target mirage.talk --file …val3-20260420-143937.tgz --migrate` using val3's fresh backup. This succeeded: the node caught up to tip at height 4025532 with byte-identical `app_hash` (`3FCA40C5F8DF02305CD68C5E600E4DBA1874E6C00425608222214D224AE10302`) to all three healthy peers → divergence cured.

2. **Validator was jailed** (expected: val1 missed ~11 h of signing during the sick + recovery window). Running `scripts/unjail_validator.sh` hit two unrelated script bugs, both fixed in this branch:
   - Default `BIN` path was `/opt/mirage/blockchain/miraged`; actual binary is at `/opt/mirage/blockchain/bin/miraged`.
   - `tx generate-only` / `tx sign` steps used `> file 2>&1`, which mixed miraged's stderr log line `core/types: registered msg interfaces …` into the JSON output file and broke downstream parsing. Changed to redirect stderr to a separate scratch file.

3. **Critical `--migrate` gotcha discovered.** Before unjail succeeded, we hit `Local consensus pubkey does not match on-chain`:
   - Local (post-`--migrate`): `whN7OyUmJzaYWC6QW+uwp0mAc0NnWDFYjovCBeffrj0=`
   - On-chain (val1's actual consensus key): `YwEfBtnvhXSPcFoNoFRndpPiJxhVbo9SW//2xN3Xzx8=`
   - Root cause: `scripts/backup_restore.py --migrate` calls `deploy/derive_consensus_key.py` to regenerate `priv_validator_key.json` from the operator mnemonic (SLIP-10 path `m/44'/118'/1'/0'`). **This assumes the consensus key was originally derived from the operator mnemonic.** Val1's (and almost certainly every existing validator's) consensus key was generated by `miraged init` and is NOT related to the mnemonic — so `--migrate` produced a brand-new consensus identity that does not match the on-chain validator record, leaving the node provably jailed with no way to unjail.
   - Fix for this incident: extracted val1's real `priv_validator_key.json` from its own Apr 16 backup (`~/.mirage/backups/mirage.talk/mirage.talk-20260416-123651.tgz`), verified its pubkey matches the on-chain one, stopped the container, swapped the file on the host mount (`/root/.mirage/node/config/priv_validator_key.json`), left `priv_validator_state.json` untouched (height 4025160, signature null → no double-sign risk vs. the real key's last sign at 4015238 before divergence), and restarted.
   - **Scope of the gotcha**: `val1` (`mirage.talk`) is the only node in the current fleet whose consensus key was generated via `miraged init` rather than by `derive_consensus_key.py`. `val2` (`mirage.vote`), `val3` (`146.190.108.140`) and `val4` (`139.59.9.96`) were all created with the mnemonic-derivation flow, so `--migrate` would correctly reproduce their on-chain consensus pubkey. The long-term fix is to rotate val1 onto a mnemonic-derived consensus key so the whole fleet is consistent; until then val1 must be treated as the exception.
   - **Guard now in place**: `scripts/backup_restore.py --migrate` now runs `verify_derived_consensus_key_matches_onchain(...)` right after the keyring import. It queries the operator's on-chain validator record via a healthy peer and compares the derived consensus pubkey against `.validator.consensus_pubkey.value`. If they differ, the restore aborts with a detailed error message and three named recovery options. The only way to bypass the check is to explicitly pass `--allow-consensus-key-change`, which is only valid if you intend a key rotation and will re-create the on-chain validator record afterwards. This would have caught today's val1 incident before the container ever started with a bad key.

4. **Unjail succeeded** after the key swap: `miraged tx slashing unjail --broadcast-mode sync --yes` (tx `3735FD954D8D98854E6F664F27774B8703EA5EE9373B5FE7B36A57D8CD4D7C7D`, `code=0`). Val1 went `BOND_STATUS_BONDED` with voting power `4995000599` and is signing the canonical chain again.

### Final cluster state

| Node | IP | Height | app_hash(4025532) | jailed | voting_power |
|---|---|---|---|---|---|
| val1 (mirage.talk) | 159.203.114.27 | 4025691 | `3FCA40…0302` | false | 4,995,000,599 |
| val2 | 64.23.136.132 | 4025691 | `3FCA40…0302` | false | (healthy) |
| val3 | 146.190.108.140 | 4025692 | `3FCA40…0302` | false | (healthy) |
| val4 | 139.59.9.96 | 4025694 | `3FCA40…0302` | false | (healthy) |

Block 4025689 `last_commit` confirms val1's consensus address `4DB0E71465310F0D3842B411CFA5CDA4CBFBA5F1` is signing alongside all three peers (flag=2 for all four). **Cluster is 4/4 healthy.**

### Preserved forensic artifacts (on val1, `/root/val-recovery-20260420/`)

- `priv_validator_key.json.migrate_bad` — the wrong key that `--migrate` derived from mnemonic.
- `priv_validator_state.before_key_swap.json` — `{height: 4025160, step: 0, signature: null}`, proving no votes were cast with the wrong key before the swap.
- Copies of `/tmp/val-recovery-20260420/` on the operator workstation (`unjail-attempt1.log`, `unjail-attempt2.log`, `priv_validator_key.json` from the Apr 16 val1 backup).

The original divergence investigation on the process side remains open (see "Open questions" above); the immediate operational incident is closed.

