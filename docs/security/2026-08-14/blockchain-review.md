# Blockchain Security Review — 2026-08-14

**Baseline:** `dev` at the `v1.35.0` tag (`922867c6`), working tree clean.
**Scope:** `blockchain/` in full — `app/` (ante chain, router, wiring, upgrades), `x/core/module/`, `x/core/keeper/`, `x/core/types/`, `proto/`, `cmd/`, `consensusfatal/`, and both vendored forks under `patches/`.
**Reporting bar:** all severities. Every finding required a concrete path traced end to end in source; candidates that could not be traced were dropped rather than filed as patterns.
**Method:** six parallel component audits, each instructed to construct exploits rather than match patterns, followed by independent re-verification of every surviving candidate by the reviewer against source. The load-bearing link of each Critical, High and Medium below was read directly, including the relevant Cosmos SDK v0.54.3 source in the module cache.

**Prior state.** All 7 Medium and 10 of 11 Low findings from [`2026-08-07/blockchain-review.md`](../2026-08-07/blockchain-review.md) were closed in `v1.34.0`; see [`2026-08-07/blockchain-retest.md`](../2026-08-07/blockchain-retest.md). The [2026-08-13 cross-component sweep](../2026-08-13/cross-component-review.md) reported `blockchain/` clean at Critical/High, at a Critical/High-only bar. Nothing here re-reports a known item, and the items recorded as accepted in [`open-items.md`](../open-items.md) — `ProcessProposal` validation (L-6), genesis `raw_state` trust (I-3), indexer moderation boundary (I-4), no ante fee ceiling (I-6), prepaid reserve on delete (I-7), `upgrades.go` decomposition (I-2), bridge-burn forensics (I-5), validator/query co-location (I-1), and the two unfixable Go advisories — were excluded by instruction and are not re-derived.

---

> **Disposition (2026-08-16, `v1.36.0`).** Every finding below has been dispositioned.
> **25 fixed, 1 accepted as risk, 2 closed as not-a-defect.** See
> [Dispositions](#dispositions) at the end of this document for the per-finding record,
> and [`../open-items.md`](../open-items.md) for the accepted risk.
>
> The release also settled four of the eight items under
> [Not determined from source](#not-determined-from-source) — the two that only needed a
> test, plus a read-only check of the live fleet and a new runtime invariant.

## Summary

**1 Critical, 2 High, 5 Medium, 9 Low, 10 Informational. All dispositioned in `v1.36.0`.**

| ID | Finding | Severity | Privilege required |
| :-- | :-- | :-- | :-- |
| **C-1** | `authz.MsgExec` nesting bypasses the entire relay ante chain — envelope signature, nonce replay and PoW. Any account with a username can be drained or impersonated by anyone | **Critical** | Ordinary funded account |
| **H-1** | A mid-iteration storage fault is unobservable at every layer, so a truncated iteration commits as a complete one | **High** | Node-local disk fault |
| **H-2** | `iavl.Store.Set` logs and drops tree write errors, so a state write can silently vanish on one validator | **High** | Node-local disk fault |
| **M-1** | Three parameter values pass `Validate()` and break the chain; one of them is the state a fresh genesis actually starts in | **Medium** | Governance, or any new chain |
| **M-2** | Unauthenticated `Simulate` runs Argon2id per message under an infinite gas meter | **Medium** | Anonymous network access |
| **M-3** | `MsgSendTokens` ignores the blocked-module-account list, and the core module account is missing from it | **Medium** | Ordinary user |
| **M-4** | `MsgSetAutoRenewal` is a free, PoW-exempt, unlimited-throughput channel for free-tier users | **Medium** | Ordinary user, level 0 |
| **M-5** | `EndBlock` scans every account balance every block, over a set any user can grow permanently with dust | **Medium** | Ordinary user |
| L-1 … L-9 | See [Low findings](#low-findings) | Low | — |
| I-1 … I-10 | See [Informational](#informational) | Informational | — |

**C-1 is the one that matters today.** It is unprivileged, cheap, deterministic, and it steals funds. It needs no timing, no grant, no validator key and no relay-operator cooperation, and the disclosed-fleet-address decision recorded as accepted in the last sweep is exactly what makes it easy to aim: the transaction is an ordinary signed Cosmos transaction broadcast to the public RPC port.

**H-1 and H-2 are the same class as the whole `v1.34.0` release, in the layer that release did not reach.** That release wrapped every core KV store so a node-local failure fails closed instead of decoding as absence. Both findings are holes in that wrapper's coverage — one for iterator reads, one for writes — and both were found independently by two of the six audits.

Two of the six areas produced no Critical or High. Their attempted exploits and the guard that killed each are recorded under [Attempted and killed](#attempted-and-killed), because a clean result only means something if the attempts are visible. In particular, the exhaustive field-by-field diff of all 25 relay message types against their canon writers found **no** field that executes without being signed, and no canon ambiguity — the envelope authentication scheme itself is sound. C-1 does not break it; C-1 skips it.

---

## C-1 (Critical) — `authz.MsgExec` bypasses the relay ante chain: theft of any account's funds, impersonation of any user, and total PoW bypass

**Component:** `blockchain/app/`. **Privilege:** any ordinary account with enough balance to pay one transaction fee. **Cost:** one transaction. **Effect:** the full spendable balance of any account with a username, transferred to the attacker; plus forged posts, votes, edits, follows, blocks, biographies and account deletions attributed to arbitrary users.

### Exploit path

Every link was read in source.

1. **The router classifies by top-level messages only.** `mirageAnteRouter` iterates `tx.GetMsgs()` and calls `isRelayMessage` on each (`blockchain/app/app.go:184-206`), which is a lookup in a registry keyed by `sdk.MsgTypeURL` (`blockchain/app/app.go:231-234`). `authz.MsgExec` is not a relay message, so `isRelayTx` stays false and `hasNonRelay` becomes true. It never inspects the messages *inside* `MsgExec`.
2. **A pure non-relay transaction goes to the standard ante chain** (`blockchain/app/app.go:213-221`), which is the stock SDK handler built at `:319-329`. `RelaySigDecorator` and `PowDecorator` live only in the relay chain (`blockchain/app/ante_relay_chain.go:61-62`) and are therefore never entered.
3. **`x/authz` is wired and live** (`blockchain/app/app_config.go:193-195`), with its keeper injected at `blockchain/app/app.go:99` and its own module store.
4. **Self-exec needs no grant.** `authz.Keeper.DispatchActions` resolves the inner message's signer and, when it equals the grantee, **implicitly accepts with no grant lookup at all** (`cosmos-sdk@v0.54.3/x/authz/keeper/keeper.go:120-124`), then dispatches straight into the message router at `:161-169`. No ante handler runs on an inner message — that is standard authz behaviour, not a local defect.
5. **The signer of every core message is its own `authority` field** (`option (cosmos.msg.v1.signer) = "authority"`, `blockchain/proto/mirage/core/v1/tx.proto:112` and on every other core message). `authority` is not validated against anything on the non-governance path, so the attacker sets it to their own address and is simultaneously granter and grantee.
6. **The handler then authorizes purely on the unverified envelope.** `MsgSendTokens` requires only that `envelope_pubkey` derives to `sender` (`blockchain/x/core/module/module.go:3242-3249`), then moves the coins (`:3286`). The envelope **signature** is never checked here — it is checked only in `RelaySigDecorator` (`blockchain/app/ante_metasig.go:37-88` and one branch per type through `:977`), which step 2 skipped. Core messages define no `ValidateBasic`, so the router's validation hook is a no-op, and no circuit breaker is configured.
7. **The victim's precondition is having a username** (`requireUsername`, `blockchain/x/core/module/module.go:233-251`) — i.e. every real user. Their public key is recoverable from any transaction they have ever signed.

The transaction:

```
MsgExec{
  grantee: <attacker>,
  msgs: [ MsgSendTokens{
      authority:          <attacker>,        // = signer, so authz implicitly accepts
      sender:             <victim>,
      target:             <attacker>,
      amount:             <victim's balance>,
      envelope_pubkey:    <victim's pubkey>, // derives to sender, which is all the handler checks
      envelope_signature: <arbitrary bytes>  // never verified — RelaySigDecorator was skipped
  } ]
}
```

signed normally by the attacker. It is an ordinary Cosmos transaction, broadcastable through `broadcast_tx_sync` on the CometBFT RPC port that `scripts/fleet_audit.sh:114,191` requires to be open on every host.

### Three further consequences of the same root cause

- **The delegation ban is bypassed.** `rejectDelegatorStakingMsgs` is deliberately hoisted to the top of the router so it covers both paths (`blockchain/app/app.go:176`) and allows only self-delegation (`blockchain/app/ante_disable_staking.go:22-60`) — but it too iterates `tx.GetMsgs()` only. `MsgDelegate`'s signer is `delegator_address`, so self-exec satisfies the implicit-accept branch and the staking handler runs unfiltered. Delegation moves consensus voting power and staking-weighted gov voting weight, so this is a consensus-relevant policy bypass, not only an economics one.
- **`GovAuthorityDecorator`'s stated invariant is false.** It documents that "any transaction arriving here with gov authority is a spoof attempt" and rejects unconditionally (`blockchain/app/ante_gov_authority.go:12-30`), and it inspects only top-level messages. A transaction whose single top-level message is `MsgExec` has no `GetAuthority()`, so it passes on both paths. Direct escalation is still blocked, because an inner message carrying the gov authority makes `granter != grantee` and the grant lookup fails (`keeper.go:125-131`) — but the decorator is not the reason, and it is documented as if it were.
- **Governance can delegate its own privilege permanently.** `authz.MsgGrant`'s signer is `granter`, so `MsgGrant{granter: <gov module address>, grantee: A, authorization: GenericAuthorization{"/mirage.core.v1.MsgSendTokens"}}` is a well-formed proposal message. One passing proposal hands an ordinary key the governance path of `MsgSendTokens` — which sends from any address with no envelope check at all (`blockchain/x/core/module/module.go:3235-3239`) — indefinitely. That is qualitatively different from "honest-majority governance can change params": the proposal does not perform the privileged action, it gives the privilege away.

### Why the existing tests do not catch it

`TestMixedRelaySDKMessageRejection` enumerates `authz.MsgGrant`, `MsgRevoke` **and `MsgExec` by name** (`blockchain/app/ante_metasig_test.go:290-292`) and asserts only that each is classified non-relay when paired with a relay message. The nesting case — `MsgExec` *containing* a relay message — is never constructed, in that test or anywhere else. The registry-parity and fail-closed-default tests are equally blind, because they reason about the message set the router sees rather than the set that ultimately executes.

### Fix

Two changes, and the first is the one that must land:

1. **Make classification transitive.** In `mirageAnteRouter`, flatten nested messages (`authz.MsgExec.GetMessages()`) before classifying, and reject any transaction whose transitive message set contains a relay message on the standard path. The same flattened set must feed `rejectDelegatorStakingMsgs` and `GovAuthorityDecorator`. Rejecting nesting outright is stronger than trying to route it correctly, since a nested relay message cannot be given a meaningful envelope check anyway.
2. **Remove `x/authz`.** Nothing in the product references it — no chain code, no backend, no frontend — and it is the only message wrapper that exists today. Removing it eliminates the current instance; the transitive guard is still required, because it is what stops the next wrapper. This is a store deletion and needs the paired `StoreUpgrades.Deleted` + `SetStoreLoader` treatment that `registerV1_28_0StoreLoader` models (`blockchain/app/upgrades.go:2338-2350`), including its documented non-atomicity. `x/feegrant`, `x/vesting`, `x/evidence` and `x/epochs` appear equally unused and are worth the same question, but only `authz` carries this bug.

A regression test belongs in `blockchain/app/relay_messages_test.go`: assert that the router rejects `authz.MsgExec` carrying **every** entry of `relayMessagePrototypes()`, so a newly added relay message cannot be forgotten.

---

## H-1 (High) — A storage fault during iteration is unobservable at every layer, so a truncated iteration commits as a complete one

**Component:** `blockchain/patches/` + `blockchain/x/core/keeper/`. **Trigger:** a node-local read fault mid-traversal — bad block, descriptor exhaustion, a node pruning removed. Not attacker-triggered; I could find no way for a user to induce one. It is High because the `v1.34.0` contract takes exactly this fault as its premise ("Node-local store Get/Set/Delete failures are realistic and must never be treated as fleet-wide deterministic failures"), and this is the one read shape that contract misses.

The wrapper halts correctly when an iterator fails to *construct* (`blockchain/x/core/keeper/failfast_store.go:192-199`). A failure *during* traversal is discarded three times:

1. **The patched iavl iterator throws the error away.** `Iterator.Next()` receives a real error from `traversal.next()` — which propagates a `nodeDB.GetNode` database read — and never assigns `iter.err`:

```224:236:blockchain/patches/iavl/iterator.go
// Next implements dbm.Iterator
func (iter *Iterator) Next() {
	if iter.t == nil {
		return
	}

	node, err := iter.t.next()
	// TODO: double-check if this error is correctly handled.
	if node == nil || err != nil {
		iter.t = nil
		iter.valid = false
		return
	}
```

So `Error()` returns `nil` (`:253-256`) and `Close()` returns `nil` (`:247-251`). The iterator is indistinguishable from one that finished cleanly. Upstream's own `TODO` on line 231 is the admission.

2. **The cachekv merge iterator never consults its parent.** `Error()` is a pure `Valid()` proxy that manufactures a sentinel (`blockchain/patches/cosmos-sdk-store-v2/cachekv/internal/mergeiterator.go:151-157`), and `Next()` treats an invalid parent as an exhausted one. Because every keeper store access is branched through `cachekv`, a `cacheMergeIterator` is *always* between the keeper and IAVL — so this layer is dispositive on its own.

3. **`failfast_store.go` must then map that sentinel to `nil`**, because it is what every healthy loop returns at its end (`blockchain/x/core/keeper/failfast_store.go:222-243`).

**Consequence.** The post-loop `if err := it.Error()` checks throughout `keeper.go` are structurally incapable of observing a real fault; they can only ever see the sentinel, which is `nil`. Every affected call site runs with `ExecMode() == ExecModeFinalize`:

- `evictLowestSeq` — a truncated scan evicts a *different* deque entry than peers do, on any ordinary user's block action.
- `deleteAllSetEntries` — entries survive while the count key is deleted anyway, so the list reports zero while holding N, and the tier hard caps that `M-2` was written to protect admit a further full quota on that node.
- `GetExpiredSubscriptions` — missed expiries produce a different set of burns, escrows and levels than peers.
- `PruneExpiredNonces` — fewer nonce deletes, so the node admits or refuses envelopes its peers do not.
- `ResetAllRelayCredits` — an incomplete reset changes the next interval's mint distribution.

All five are AppHash divergence, which is the failure class both forks exist to prevent.

The two existing tests confirm rather than refute this: `failfast_store_test.go` asserts that the real `cachekv` stack's `Error()` is filtered out, and proves forwarding only from a hand-written `failingIterator` that no real delegate behaves like.

**Fix.** Three lines, in the two already-patched vendored modules:

- `blockchain/patches/iavl/iterator.go:232` — assign `iter.err = err` before invalidating.
- `blockchain/patches/cosmos-sdk-store-v2/cachekv/internal/mergeiterator.go:151` — return `parent.Error()` / `cache.Error()` when either is non-nil, before falling through to the exhaustion sentinel.

`iteratorExhausted` then keeps its current job and `failFastIterator.Error()` starts halting on real faults. Both deviations need a `PATCHES.md` entry, and the fix needs a test that injects a parent-iterator failure *mid-loop* and asserts the keeper call returns an error rather than a short list — the existing `TestIteratorExhaustionIsNotAFault` pins only the benign direction.

---

## H-2 (High) — `iavl.Store.Set` logs and drops tree write errors, so a state write can vanish on one validator

**Component:** `blockchain/patches/cosmos-sdk-store-v2/iavl/`. **Trigger:** node-local write-path fault. Upstream defect, in scope, and it defeats the `v1.34.0` write contract at the last mile.

`Get`, `Has` and `Delete` all `panic(err)` (`blockchain/patches/cosmos-sdk-store-v2/iavl/store.go:194-217`), which the finalization guard converts into a clean exit. `Set` alone logs and returns as though it succeeded:

```183:191:blockchain/patches/cosmos-sdk-store-v2/iavl/store.go
// Set implements types.KVStore, creates a new key/value pair in the underlying IAVL tree.
func (st *Store) Set(key, value []byte) {
	types.AssertValidKey(key)
	types.AssertValidValue(value)
	_, err := st.tree.Set(key, value)
	if err != nil && st.logger != nil {
		st.logger.Error("iavl set error", "error", err.Error())
	}
}
```

`MutableTree.Set` reads nodes from `nodeDB` to descend and rebalance, so a disk fault there returns an error and the pair is never applied. The keeper's `Set` goes into the `cachekv` map (which cannot fail), and the real write happens at commit time via `cachekv.Write` → `parent.Set(...)` → the code above. The `types.KVStore` interface has no error return at that boundary, so `failFastKVStore.Set` (`blockchain/x/core/keeper/failfast_store.go:184-186`) has already returned success and no wrapper can observe the loss. One validator commits a block without that key while healthy peers commit with it.

**Fix.** `panic(err)`, for symmetry with the other three methods, and record the deviation in `PATCHES.md`.

---

## M-1 (Medium) — Three parameter values pass `Validate()` and break the chain, and one of them is the state a fresh genesis actually starts in

**Component:** `blockchain/x/core/types/params.go`. **Trigger:** governance for all three; the third additionally on any newly launched chain. Only values that pass the tightened `v1.34.0` `Validate()` are reported here — "governance can change params" on its own is not a finding.

**(a) `min_difficulty = 256` makes proof-of-work mathematically unsatisfiable.** `Validate()` accepts the full range `[1,256]` (`blockchain/x/core/types/params.go:230-232`) and the field is governance-writable. It feeds the target as a right shift: `new(big.Int).Rsh(bigMaxHash, uint(baseBits))` (`blockchain/app/ante_pow.go:1417`). At 256 the base target is exactly zero, so the acceptance test `hashInt.Cmp(effTarget) > 0` (`:1493`) fails for every Argon2id output except the all-zero digest. From the next block, every level-0 transaction is rejected in the ante — no posts, votes, follows or username claims from free users — while paid tiers are PoW-exempt and unaffected, so the chain looks healthy while most of its users are locked out. Anything above roughly 40 is already unsatisfiable in practice; 256 is where it becomes provable. Governance can still recover, since gov transactions are not PoW-gated.

**(b) `relay_min_gas_price = 0` or `relay_max_gas_fee = 0` makes every relay message free for paid tiers.** Both are bounded above only (`params.go:306-312`). Either at zero makes `calculateRelayFee` return zero, and the deduction short-circuits at `blockchain/x/core/module/module.go:302-304`. Level ≥ 1 users are PoW-exempt by design, so this fee is the *only* per-message cost they bear: at zero, every paid tier gets unlimited free chain writes, and because reserves never drain they also never hit the usage-based downgrade. Note the semantic trap — zero means "no fee" here, while zero means "reject" in the adjacent deque-cap checks (`module.go:2479`).

**(c) `subscription_reserve_bps = 0` inverts subscription economics, and the shipped genesis params omit the field.** Zero passes (`params.go:291-293`) and short-circuits the split (`blockchain/x/core/types/subscription_math.go:47-49`), so all three call sites burn the entire period fee from the payer and escrow nothing. The user is now level 1 with an empty reserve; their next relay message fails the reserve test and takes the exhaustion branch — index removed, `Level = 0`, `subscription_expired` with reason `reserve_exhausted`. Full fee in, instant demotion, no service.

This one is not merely hypothetical. `blockchain/x/core/types/testdata/genesis_core_params.json` — the de-facto genesis params, which `params_test.go` treats as such — has no `subscription_reserve_bps` key at all, so proto3 decodes it as 0, and `TestGenesisParamsStillValidate` passes precisely *because* zero is legal. `InitGenesis`'s zero-substitution sentinel checks five other fields and not this one (`blockchain/x/core/module/module.go:538-544`), so the params are taken verbatim. Any chain started from that genesis — a `reset_local_testnet.py` run, a new deployment, a from-genesis replay — runs inverted until the `v1.34.0` handler executes. The live fleet is fine, because that handler already ran.

**Fix.** Reject zero in `Validate()` for `relay_min_gas_price` and `relay_max_gas_fee`; lower `min_difficulty`'s ceiling to a reachable value (32 is generous against a default of 10). For the reserve field, add it to the `InitGenesis` zero-substitution list and to the genesis params — **not** to `Validate()`, for the same reason already documented for `MinBlockHashWindow` (`params.go:52-58`): the pre-`v1.34.0` handlers call `SetParams`, so a `Validate()` rejection would panic a from-genesis replay.

---

## M-2 (Medium) — Unauthenticated `Simulate` runs Argon2id per message under an infinite gas meter

**Component:** `blockchain/app/ante_pow.go`. **Privilege:** anonymous network access to the CometBFT RPC port.

`Simulate` is registered on the app's gRPC **query** router (`cosmos-sdk@v0.54.3/runtime/app.go:210-212`), which is served through ABCI Query — so it is reachable as `/abci_query?path="/cosmos.tx.v1beta1.Service/Simulate"` on port 26657 regardless of whether 1317/9090 are published. In simulate mode the SDK installs an infinite gas meter, signature verification is skipped, and a zero fee deducts nothing, so the request is free and unauthenticated.

Neither relay decorator consults the flag: `PowDecorator.AnteHandle` and `RelaySigDecorator.AnteHandle` take `simulate` and pass it straight to `next` without ever branching on it (`blockchain/app/ante_pow.go:193` and `:873`; `blockchain/app/ante_metasig.go:37` and `:977`). `argon2.IDKey(guess, salt, 1, 4096, 1, 32)` therefore executes per message (`ante_pow.go:1486`) at the benchmarked 1.65 ms and 4.2 MB per call.

The amplification is worse than one Argon2 per request. Argon2 aborts on the first failure, so reaching the k-th evaluation needs k−1 *valid* proofs — but the nonce is never persisted in simulate (the state is discarded), so a set of valid envelopes is computed **once** and re-simulated indefinitely. Precompute 100 valid messages once and every subsequent HTTP request costs the node ~165 ms of CPU and ~400 MB of allocation churn, for free. `query-gas-limit = "0"` (`deploy/templates/node/app.toml:15`) removes the only configured ceiling.

**Fix.** Skip `validatePoWBytesArgon2` when `simulate` is true — proof of work is not part of gas estimation — and set a non-zero `query-gas-limit` in the node template.

---

## M-3 (Medium) — `MsgSendTokens` ignores the blocked-module-account list, and the core module account is missing from it

**Component:** `blockchain/app/app_config.go`, `blockchain/x/core/keeper/keeper.go`. **Privilege:** ordinary user (self-inflicted; combined with C-1, inflictable on anyone).

`blockAccAddrs` exists to "block module accounts that should not receive direct transfers" (`blockchain/app/app_config.go:75-83`) and is handed to bank as `BlockedModuleAccountsOverride` (`:173`). That list is enforced only inside bank's own `MsgServer`. The chain's primary user-facing transfer message does not go through it: `MsgSendTokens` calls the core keeper's `SendCoins`, which reaches `k.bank.SendCoins` directly and never consults the list (`blockchain/x/core/keeper/keeper.go:1074-1079`). So `fee_collector`, `mint`, `gov`, both staking pools and `distribution` are all reachable targets.

Separately, `coremoduletypes.ModuleName` — the one module account holding Minter, Burner **and** Staking simultaneously (`app_config.go:71`) — is absent from `blockAccAddrs`. Because the list is non-empty, `BlockedAddresses()` uses it verbatim and never falls back to the full permission map (`blockchain/app/app.go:579-592`), so even a plain bank `MsgSend` into the core module account is accepted.

**Impact.** Irrecoverable user fund loss, and drift in staking/distribution pool accounting with no runtime detection — the crisis/invariant module is not wired. The supply invariant does **not** catch it: it compares recorded supply against the sum of all balances (`keeper.go:1423-1441`), which a transfer preserves. Worse, excess balance in the core account *masks* the `CORE_MODULE_SHORT_BURN` guard (`keeper.go:1613-1624`), which is the detector for reserve liabilities exceeding their backing.

**Fix.** Add `coremoduletypes.ModuleName` to `blockAccAddrs`, and have `Keeper.SendCoins` reject a `toAddr` in `BlockedAddresses()` before calling bank.

---

## M-4 (Medium) — `MsgSetAutoRenewal` is a free, PoW-exempt, unlimited-throughput channel for free-tier users

**Component:** `blockchain/app/ante_pow.go`, `blockchain/x/core/module/module.go`. **Privilege:** ordinary user, level 0, with a username (one PoW to bootstrap).

The PoW decorator exempts this type on the premise stated in its own comment — "MsgSetAutoRenewal NEVER allows PoW - must pay with reserve" (`blockchain/app/ante_pow.go:284-299`). That premise is false at level 0: `checkReserveOrDowngrade` returns `nil` unconditionally for free users (`ante_pow.go:164-167`), so neither PoW nor reserve is demanded.

The handler cannot charge either. A level-0 user's `AutoRenew` is false and the only value they may set is false, since `targetAuto == true` is rejected at `blockchain/x/core/module/module.go:3727-3730`. That forces the no-op branch (`:3737-3743`), which calls `deductRelayGasFee` with `userLevel = 0`, and that returns immediately for `userLevel < 1` (`:291-293`).

So each message costs the user zero PoW, zero tokens and zero reserve and produces zero state change, while the node pays a full relay ante: an unmetered secp256k1 envelope verification, two profile reads with JSON unmarshals, and two nonce-store writes. The chain-level invariant that every free-tier relay message is paid for in Argon2 work is broken, and because `RecordPoWMessage` is only reached inside the PoW branches, the abuse never raises difficulty. It is Medium rather than High only because block space still costs the relay operator their outer Cosmos fee — the attacker gets free quota, not free blockspace.

**Fix.** Require a paid level in the `MsgSetAutoRenewal` branch of `PowDecorator`, mirroring the handler's own free-tier rule.

---

## M-5 (Medium) — `EndBlock` scans every account balance every block, over a set any user can grow permanently with dust

**Component:** `blockchain/x/core/keeper/keeper.go`, `blockchain/x/core/module/module.go`. **Privilege:** ordinary user with a username and a small balance.

`AssertSupplyInvariant` sums every balance through an unbounded walk of the bank balances index (`keeper.go:1423-1441`) and runs on every block from `EndBlock`. The growable half: `MsgSendTokens` moves as little as 1 umirage to any valid bech32 address with no requirement that it exist (`module.go:3258-3288`; `validateAddress` at `:103-114` is bech32-only). x/bank deletes only zero balances, so each dust transfer to a fresh address adds one permanent index entry that every subsequent block must walk, forever. Nothing sweeps it: `DeleteUserState` clears balances only for addresses that have a profile.

Each entry is paid for once and imposes an unmetered per-block cost on every validator indefinitely. `BeginBlock`/`EndBlock` work is charged to no transaction, so the asymmetry is unbounded in the attacker's favour, and the end state is block-time inflation until a block cannot finish inside `timeout_commit`. The same growth arrives organically with adoption.

The O(accounts) cost itself is a deliberate, documented trade (`keeper.go:1419-1422`, closing the earlier M-2). What is documented nowhere — not in the retest, not in `open-items.md` — is that the scanned set is user-growable and the growth is irreversible.

**Fix.** Either scope the full scan to a periodic height and rely on the O(1) delta check every block, accepting a bounded detection delay for the one fault class the delta cannot see; or make the scan resumable with a stored cursor and a per-block key budget, the pattern `CleanupOldCounters` already uses. Separately, a minimum transfer amount raises the price of the growth half.

---

## Low findings

**L-1 — `consensusfatal.HaltErr` is not confined to finalization; a store fault while answering a public query exits the process.** The wrappers gate correctly on `ExecMode() == ExecModeFinalize` (`failfast_store.go:49, 72, 87, 119, 137`), but the keeper readers with no error channel call `HaltErr` — `os.Exit(1)` (`consensusfatal/halt.go:10-13`) — with no exec-mode test: `GetParams` (`keeper.go:1287-1310`), `GetRelayCredit` (`:1158-1174`), `RecordPoWMessage` (`:2036-2058`), the PoW counters and all four difficulty getters (`:2088-2380`), and `HasEnvelopeNonce` (`:2666-2677`). Six are on the ante path, which runs in check, recheck and simulate modes; per `AGENTS.md` the backend simulates every user action, so these are reachable from public RPC. On those modes nothing is committed and no accept/reject split is possible, so halting buys no consensus safety and costs the validator. `RecordPoWMessage` contradicts itself inside one function — it halts on the `Get` failure and *returns* the `Set` failure. **Fix:** return the error where a channel exists; elsewhere gate on finalize and panic otherwise, matching `haltFinalizeBankPanic`, which already gets this right.

**L-2 — a malicious state-sync peer crashes a restoring node with a negative IAVL node version.** `rootmulti` validates `item.IAVL.Height` against `MaxInt8` but performs no validation of `item.IAVL.Version`, a wire-supplied `int64`, and passes it straight into `ExportNode` (`blockchain/patches/cosmos-sdk-store-v2/rootmulti/store.go:1105-1114`). The importer rejects only versions *above* its own (`blockchain/patches/iavl/import.go:130-133`), then indexes `i.nonces[exportNode.Version]` on a slice allocated as `make([]uint32, version+1)` (`import.go:56`). A negative version is an out-of-range panic inside the restore goroutine, which has no `recover`, so the process dies instead of rejecting the snapshot and trying the next peer. Chunk hashes are verified only against the peer's own metadata, so everything reaching `Importer.Add` is attacker-controlled. **Fix:** reject `Version < 0` (and `Height < 0`) at both sites.

**L-3 — `v1.35.0` deleted the parameter bounds checks that `params.go` names as their enforcing surface.** `params.go:52-59` explains that the `MinBlockHashWindow` floor deliberately cannot live in `Validate()` and states that "the v1.34.0 handler widens a stored value below the floor, and verify_upgrade.py bounds the live chain." The `v1.35.0` rewrite of `scripts/verify_upgrade.py` (+213/−334) removed `check_required_params_present()`, `check_param_bounds()`, the `REQUIRED_PARAMS` list, and the `block_hash_window`, `subscription_reserve_bps` and `subscription_reserve_percent` bounds; the current file contains no match for `param`, `bps`, `reserve` or `block_hash_window`. The handler check is a one-shot at a single height, so governance can now set `block_hash_window` to 1–19, pass `Validate()`, and make the recent-hash window a stricter freshness rule than `max_envelope_age` — the original finding, undetected at runtime. **Fix:** restore the bounds check, or stop naming a surface that no longer exists.

**L-4 — `GetProfile` silently returns a partial profile on a store read error.** `loadFullProfile` loads the six list fields with `if xs, err := ...; err == nil` and discards every error, returning the profile with that list **empty** and `err == nil` (`blockchain/x/core/module/module.go:1966-1986`). `GetProfilesPaginated` propagates the same errors. Query-only, so it cannot diverge consensus; the harm is a client reading "0 blocked users" as truth during a transient fault. It is the exact fail-open shape the `v1.34.0` contract set out to remove. **Fix:** propagate, matching the paginated path.

**L-5 — a mid-transaction downgrade lets every later message in the same transaction run with neither PoW nor fee.** The ante decides PoW-versus-reserve routing once per message from the level as it stood before any handler ran, and `continue`s without a PoW check for a paid user. `checkReserveOrDowngrade` deliberately does not reject on insufficient reserve (`ante_pow.go:135-141, 184-190`). When message 1 exhausts the reserve, `deductRelayGasFee` writes `Level = 0` into the shared cache-wrapped store, so messages 2..N read level 0 and are charged nothing — while the ante already waived their PoW. N is bounded only by tx size and block gas. One-shot per subscription. **Fix:** have `checkReserveOrDowngrade` require reserve covering the *count* of messages that pubkey submitted in this transaction.

**L-6 — `LoggingDecorator` emits one log line per message before the outer signature is verified.** It sits at index 5 of the relay chain while `SigVerification` is at index 9 (`blockchain/app/ante_relay_chain.go:49-63`), and its handler loops over every message calling `logger.Info`, plus a SHA-256 over the whole transaction. A 1 MB transaction of thousands of minimal relay messages with a garbage signature therefore produces thousands of log lines on every node that CheckTx's it, from an unauthenticated attacker. This contradicts the chain's own ordering contract stated at `ante_relay_chain.go:17-22`. **Fix:** move it after `SigVerificationDecorator`, or gate the loop on finalize.

**L-7 — zero-height genesis export fails open on iterator close.** In `prepForZeroHeightGenesis` a failed `iter.Close()` logs and `return`s (`blockchain/app/export.go:232-235`), skipping `ApplyAndReturnValidatorSetUpdates` and the slashing signing-info reset. `ExportAppStateAndValidators` cannot observe this and marshals the partial state anyway, so `miraged export --for-zero-height` produces an artifact with validator power updates unapplied and a zero exit code — against the project's fail-hard rule. **Fix:** panic, matching every other error in that function.

**L-8 — the canon completeness harness has two vacuous checks and does not cover the authentication boundary.** `MsgSubscribe.Level` is checked vacuously: `populateFields` has no `reflect.Uint32` case (`blockchain/app/ante_canon_test.go:28-46`) so `Level` stays 0, and `verifyCanon` then searches for the single byte `0x00`, which every canon buffer contains as the writer's prefix terminator — so the assertion would pass even if `level` were dropped from the canon entirely, and `level` selects the paid tier. There is no `reflect.Bool` case either, so `MsgSetAutoRenewal.AutoRenew` is uncoverable. And the table drives only the `buildCanonFor*` PoW builders, not the 25 metasig closures that *are* the authentication boundary — two of the pinned builders (`buildCanonForAward`, `buildCanonForSubscribe`) are in fact dead, since both types reject PoW outright. All 25 closures are complete today; I verified each by hand. **Fix:** add the two `reflect` cases with non-zero values and drive the table through the metasig closures.

**L-9 — three more patched-fork paths discard iterator errors.** `iavl.Store.Query`'s `/subspace` handler appends pairs, calls `Close()` (which returns the always-nil `iter.err`), and never calls `Error()`, so a truncated iteration is marshalled as a successful response to a remote client. `ImmutableTree.Iterate` returns `(false, nil)` without checking `itr.Error()` (`blockchain/patches/iavl/immutable_tree.go:219-224`). `nodeDB.traversePrefix` returns `nil` unconditionally (`nodedb.go:1146-1160`) while its sibling `traverseRange` correctly returns `itr.Error()` — and it backs both prefix walks in `deleteLegacyVersions`, so a truncated walk leaves legacy orphans undeleted while reporting success, which is unbounded disk growth the `MIRAGE_PRUNE_DEGRADED` counter will never see. All upstream defects; the same class as H-1.

---

## Informational

| ID | Item |
| :-- | :-- |
| **I-1** | **`AddRelayCredit` silently saturates** at `2^64-1` instead of returning an error (`keeper.go:1185-1191`), against both `AGENTS.md`'s no-fallbacks rule and the `safe_math.go` contract. Unreachable today — the only caller passes 1 and credits are wiped each mint interval — and live the moment the delta becomes a fee amount. |
| **I-2** | **`GetBalance` returns zero when the address fails to decode** (`keeper.go:1065-1071`), on paths that gate value movement (renewal affordability, both `Subscribe` checks). Deterministic, so it cannot diverge; reachable only from a profile stored at a malformed address key, i.e. `raw_state` import. Still the exact "decode failure defaults to zero" shape the release removed elsewhere. |
| **I-3** | **`RecordRecentBlockHash` substitutes a hardcoded window of 60** when the param is zero (`keeper.go:1383-1386`), duplicating `DefaultParams` in a second place that can drift. Unreachable through governance because `Validate()` bounds the window to `[1,1000]`. |
| **I-4** | **`IterateRelayCredits` decodes a malformed credit value as zero** (`keeper.go:1207-1212`), directly contradicting `GetRelayCredit`, which halts on the same bytes. It has no non-test caller and is dead code today; wiring it to a query or mint path would reintroduce the old M-3. |
| **I-5** | **Eight per-callsite hardcoded tier fallbacks** when `GetTierConfig` returns nil, each a different number (5, 5, 25, 10, 10, 25, 50), while `Edit` hard-fails on the same condition. Reachable only via a governance `MsgSetLevel` to a level in 2..9, where `LevelToTierIndex` returns −1. |
| **I-6** | **`max_biography_length = 0` means "no limit", not "disabled"**, contradicting its own proto comment (`params.proto:36` versus `module.go:2161-2164`), and the field is completely unvalidated. Unreachable as shipped; a proposal enabling biographies for a tier without setting a length leaves that tier with no tier-level limit. |
| **I-7** | **Retired proto tags are protected by comments rather than `reserved`.** `tx.proto` has zero `reserved` statements while `// tags 8-9 reserved` appears in ~25 messages; `params.proto` is inconsistent with itself. `TierConfig` tag 14 held a deleted field with no `reserved 14`, and tag 7 was repurposed across a type-compatible rename (`max_quality_posts` → `max_blocked_topics`), so a pre-rename stored blob decodes the old value into the new field. Fail-closed today. |
| **I-8** | **Three legacy messages are registered without handlers** and without the early ante rejection the five bridge messages get (`codec.go:58-59`): `MsgMintTo`, `MsgFollowModerator`, `MsgUnfollowModerator`. They reach the message router and fail there. |
| **I-9** | **The gates that exist because `replace` hides the forks are themselves scoped to one package.** `blockchain/Makefile:159-167` runs `govulncheck ./...` for the main module but `.` and `./rootmulti/` for the forks, re-creating the blind spot for `iavl/db`, `iavl/fastnode`, `iavl/cache`, and store/v2's `snapshots/`, `cachekv/`, `iavl/`, `pruning/` — `snapshots/` being the one package with a remote attack surface. `test-iavl` and `test-store` are scoped the same way. |
| **I-10** | **`check_patches.sh` blind spots:** `globstar nullglob` without `dotglob`, so dot-prefixed files inside either fork are invisible; the missing-upstream-file loop filters to `*.go`, which is how the absent iavl `LICENSE` (an Apache-2.0 redistribution gap on a public repo) went unnoticed; and the pins are `grep`ed from `PATCHES.md` while the modules are downloaded by tag, with nothing tying hash to tag. |

Also noted, not findings: `batch.go:52-87` unlocks an already-unlocked mutex on the flush-error path, so a disk-full condition during commit surfaces as a mutex panic that obscures the cause; the `CONSENSUS_FATAL:PRUNE_HOLE` guard exits from a background goroutine with no test seam and no hook into `recover.sh`'s forensic-snapshot chokepoint, so an operator's first action after it fires is the wipe `AGENTS.md` forbids; commit-info pruning is synchronous while IAVL pruning is asynchronous, leaving a window where a historical query fails rather than serving; and snapshot restore allocates 4 bytes per block of chain history per substore with all importers held live.

---

## Attempted and killed

A clean result is only meaningful if the attempts are visible. These are the exploits constructed and the specific guard that killed each.

### Envelope authentication — no bypass exists

The strongest structural threat is a field that executes but is not signed, since a relay operator signs the outer transaction. All 25 relay message types were diffed field by field against both their metasig closures and their PoW canon builders. **Every payload field that executes is signed, and the encoding is injective.**

- Representative coverage: `MsgPost` tags 100–105 (`ante_metasig.go:63-77`), `MsgEdit` 100–106 (`:786-801`), `MsgSendTokens` sender/target/amount (`:749-758`), `MsgAnnotate` 101–107 (`:829-844`), `MsgSubscribe` level and target (`:882-885`), `MsgAward` target and type (`:959-960`).
- **Canon collision by shifting a character between adjacent string fields** — killed by length-prefixing: every variable-length field is tag + uvarint(len) + bytes (`ante_metasig.go:999-1013`), and repeated elements are individually prefixed, so `["ab"]` and `["a","b"]` differ.
- **`MsgAnnotate` re-parenting a post** — the proto has no `target` field at all (`tx.proto:822`), and the annotated post travels in the signed `override`.
- **`MsgSubscribe`'s conditional `target` stripped or injected** — the verifier rebuilds the canon with the identical condition (`:883-885`), so either mutation changes the preimage.

### PoW, replay and freshness

- **Work reused across type, user, nonce or block** — the Argon2 preimage carries the type prefix, pubkey, block hash, timestamp and nonce (`ante_pow.go:1019-1024`, `:1474-1479`).
- **Replay of an identical envelope** — closed at three layers: the nonce must be non-zero and unseen and is recorded in the ante (`ante_metasig.go:57-89`), which commits even when the handler later fails; the timestamp must fall in the age window with bounded future skew; and `envelope_block_hash` must be in the on-chain rolling window (`ante_pow.go:1453-1471`).
- **Nonce reuse within one transaction** — `SetEnvelopeNonce` writes into the same cache-wrapped store the loop reads.
- **Replay after nonce pruning** — the expiry is `max(blockTime, txTime) + maxAge + 5 min` against a freshness check of `maxAge`, a margin in the safe direction.
- **Fabricated or cheap `last_block_hash`** — window membership is checked *before* Argon2, and an empty hash is refused explicitly so it cannot alias the always-empty ABCI 2.0 `LastBlockId` (`ante_pow.go:1453-1472`).
- **Inflated mempool priority for free** — priority is `1 + EnvelopeDifficulty` but the target uses `max(declared, chain minimum)` (`:1444-1448`), so every priority point is paid for in real work; saturation needs ≈133 steps and a per-hash probability of 2⁻⁵³.
- **Argon2 amplification in CheckTx** — the branch aborts on the first failure, so reaching the k-th hash needs k−1 valid proofs, each costing the attacker ≈1024 evaluations against the node's 1. (The simulate path defeats this, which is M-2.)

### Authorization and routing

- **Mixed relay + non-relay message sets** — rejected at `app.go:208-211`.
- **A gov-authority message appended to a relay transaction** to exploit the router's flag reset — `GovAuthorityDecorator` wraps the standard path and rejects any transaction containing a gov-authority message, using the same `TrimSpace` comparison, in either message order.
- **Whitespace-padded gov authority** to make the ante's trimmed comparison and the handler's exact comparison disagree — trimmed-equals-gov is implied by exact-equals-gov, so the padded variant is caught first.
- **Every governance-only handler submitted directly** (`MsgSetLevel`, `MsgMintTokens`, `MsgBurnTokens`, `MsgPunishValidator`, `MsgUpdateParams`) — each re-checks the gov module address by exact equality (`module.go:1424, 3313, 3366, 3410, 3435`), and this holds through `MsgExec` too.
- **Resurrected bridge messages** on either path — rejected before classification (`app.go:187-192`), pinned by test.
- **A relay message with no `PowDecorator` branch** — fail-closed `default` (`ante_pow.go:868`) plus AST parity enforcement in both directions.
- **ICA/IBC-delivered nested messages** — no IBC or ICA module is wired; removed in `v1.10.0`.
- **`MsgMultiSend` into a blocked module account** — bank's own message server enforces the override. (`MsgSendTokens` is the bypass; that is M-3.)
- **A direct transfer into the core module account to break the supply invariant and halt the fleet** — the invariant compares supply against the sum of balances, which a transfer preserves. The residual is M-3's fund loss and masking.

### Consensus halt reachability

- **Orphaning a subscription index to reach `CONSENSUS_FATAL:PROFILE_MISSING`** — index expiry stays in lockstep with `core.SubscriptionExpiry` on every mutating path, and `RemoveSubscription` is idempotent, so the delete-plus-downgrade race is harmless.
- **Malformed subscription-index or nonce keys** to break the expiry sweep or the prune — both key formats are keeper-written from internal values with no user-controlled bytes; the expiry sweep's zero-padded `%016x` makes lexicographic ordering numeric, and the exclusive end is built with checked arithmetic.
- **`CORE_MODULE_SHORT_BURN` via recorded reserves exceeding module balance** — reserves are escrowed before they are recorded, self-subscribe burns the old reserve in the same atomic transaction, and account delete leaves the reserve in the module (the accepted I-7). Every path keeps module balance ≥ Σ reserves. See "not determined" below.
- **`ErrInsufficientFunds` during finalize via a vesting/locked balance** — `SendCoins` and `BurnFromAccount` precheck spendable and return a normal error before the unexpected-error wrapper fires; the wrapper explicitly lets `ErrInsufficientFunds` through.
- **Halting the ante with a difficulty or params value** — both range checks read committed state, not the transaction, and `SetCurrentDifficulty` validates on write.

### State, keys and arithmetic

- **Key collision between an entry key and its count/sequence key** — the metadata suffixes are `"\x00c"`/`"\x00s"` while entry keys separate with `"/"`, and `0x00 < 0x2F`, so the metadata keys sort below the entry range.
- **A crafted username, topic or post hash escaping its owner's keyspace** — every user-supplied component is charset-restricted before reaching the key builder: topics lowercase alphanumeric, hashes 64 lowercase hex, agents and blocked users valid bech32. None can contain `/` or NUL, and the owner is always envelope-derived.
- **Overlapping prefixes** — `fu/ ft/ ea/ bu/ bp/ bt/` are pairwise non-prefixing, and `envelope_nonce/` versus `envelope_nonce_expiry/` diverge at byte 15.
- **`uint32(maxPosts)` truncating a tier limit to zero to disable deque eviction** — `Validate()` bounds list limits to `MaxUint32` so the conversion is exact, and a zero limit is rejected before the call.
- **Renewal leaking the previous reserve** — the leftover is burned at the top of the loop before any renewal branch.
- **Obtaining an unwrapped raw core store** — `NewKeeper` wraps unconditionally, there is one construction site, and no `ctx.KVStore(coreStoreKey)` exists anywhere.
- **Exec-mode misclassification letting the lifecycle hooks fail open** — baseapp applies `ExecModeFinalize` before `preBlock` and `beginBlock`, so upgrade handlers and both hooks see it.
- **SDK single-value balance helpers returning zero on failure** — the keeper deliberately routes every balance and supply read through iterator APIs that panic, under a recover guard.
- **Deleting during iteration** — every mutating loop collects keys, closes, then deletes.
- **Bulk `SetAgents` bypassing the tier hard cap** — length rejected before the replace.
- **Non-determinism feeding a write** — mint sorts valopers before distribution, param updates iterate the ordered mask paths, tier lookups iterate ordered slices; no `time.Now` or float-driven write on a consensus path.

### Snapshots, tooling and CLI

- **Substituting chunk content during state sync** — SHA-256 chunk-hash check before the write.
- **Path traversal through snapshot height/format/chunk** — every path component is a formatted numeric.
- **`analyze-db` writing to a live database** — it symlinks every file except `LOCK` into a temp directory and opens Pebble read-only; `compact-db` opens read-write but Pebble's exclusive `LOCK` makes the open fail while `miraged` holds the DB, exiting non-zero.
- **`unsafe-reset-all` or an equivalent state-destroying command** — not registered.
- **`extractProtoVarint` unbounded advance** producing a negative index and a chain-wide panic inside an upgrade handler — its sole caller passes a keeper-marshalled `Params` blob, and that handler has already executed. Worth hardening if the helper is ever reused on untrusted bytes.
- **The prune-hole guard reusing a written batch** — `BatchWithFlusher.Write` recreates the inner batch.
- **Fast-node cache incoherence on a consensus read** — killed by the patch itself: fast nodes are off the read path entirely.

### Prior fixes spot-checked as genuinely present

Eleven of the seventeen `v1.34.0` fixes were re-verified in source (M-1, M-2, M-3, M-4, M-6, M-7, L-2, L-3, L-4, L-8, L-10), plus M-7's `safe_math` call sites, L-9's `paramFieldSetters` map, and L-4's field-54 parity. **No claimed fix was found absent.** The provenance gate also passes: `scripts/check_patches.sh` reports both forks OK, and an independent recursive diff against the upstream module caches (`iavl@v1.2.8`, `store/v2@v2.0.0`) shows the deviation set matching `PATCHES.md` exactly, byte for byte.

---

## Upgrade posture

The `v1.35.0` handler is correct and matches its release notes. The notes describe a query-path-only change — `Query/GetProfile` returning gRPC `NotFound` — and the handler does exactly one thing, `RunMigrations`, with the error propagated (`blockchain/app/upgrades.go:2305-2319`). No state write, no param mutation, no store key change, so there is no partial-failure window. Registration purely for fleet coordination is documented at `:2290-2304`.

The store-loader two-phase contract is sound at this release: the only `SetStoreLoader` registration fires only when the on-disk upgrade info names `v1.28.0`, it is called before `app.Load`, and no handler since has added, deleted or renamed a store. Registration is exhaustively enforced by AST parse plus a count pin at 46, and `v1.35.0` is the last entry, so nothing is pending.

One trigger has fired: the `I-2` deferral named "handler 46+" as its re-trigger, and handler 46 has now landed. The file is 2,400 lines, still below the 2,500-line trigger.

---

## Not determined from source

1. **Whether the live fleet's stored parameters are safe with respect to M-1.** No server was contacted. M-1(b) and M-1(c) are stated as reachable by proposal and reachable from genesis, not as live misconfiguration.
2. **Whether a from-genesis replay on the `v1.35.0` binary can hit `CONSENSUS_FATAL:PARAMS_VALIDATE`.** `GetParams` validates on **every** read and halts on failure (`keeper.go:1305-1310`), so any historical params blob violating the `v1.34.0` bounds would kill a syncing node at that height. The two known cases were handled; answering it in general needs the chain's actual parameter history at each pre-`v1.34.0` upgrade height, from an archive node.
3. **Exhaustiveness of the module-account solvency invariant.** Every reserve mutation preserves module balance ≥ Σ recorded reserves, so `CORE_MODULE_SHORT_BURN` is not reachable — but I did not prove no other module can withdraw from the core account out-of-band, and M-3 shows that account is not even blocked from receiving. A runtime invariant would convert this from believed-safe to asserted-safe.
4. **Whether a false-positive `PRUNE_HOLE` halt is reachable.** `getFirstVersion`'s binary search assumes monotonic `hasVersion`, and `hasVersion` probes only the nonce-1 root, which pruning reformats. No concrete false positive was constructed; settling it needs a replay against a real pruned fleet DB.
5. **Empty-value round-trip for envelope nonces across a commit.** Nonce presence is stored as `[]byte{}` and `cachekv`'s `Has` is `!isZero(Get(key))`, so replay protection depends on the lower layers returning non-nil for a committed empty value. Worth a direct test — write, commit, restart, assert still present. A one-byte sentinel would remove the question.
6. **Whether M-2's amplification is bounded by anything upstream of the node.** Reachability rests on the RPC port, which `fleet_audit.sh` requires to be open; the effective request rate at the edge is operator-side.
7. **Empirical cost of the M-5 scan.** `EndBlock` logs the full-scan duration every 1000 blocks; the current account count and measured time would settle the remaining headroom.
8. **No tests were run for this review.** Every cited test was confirmed by reading it. `go build`, `go test`, `make test-fast` and the Docker suites were not executed; `scripts/check_patches.sh` and the upstream provenance diffs were the only commands run.

---

## Prioritized recommendations

1. **Fix C-1 before anything else.** Transitive message classification in the router, plus removing `x/authz`. It steals funds, it is unprivileged, and the exploit is a single ordinary transaction.
2. **Close the iterator and write-error holes (H-1, H-2).** Three lines across two already-patched forks, plus `PATCHES.md` entries and a mid-loop failure-injection test. Without them, the entire `v1.34.0` fail-closed contract has a documented exception nobody wrote down.
3. **Bound the parameters that pass `Validate()` (M-1)**, and fix the genesis reserve field through `InitGenesis` rather than `Validate()`. The genesis half means every new chain and every local reset currently starts with inverted subscription economics.
4. **Skip Argon2 in simulate and set a `query-gas-limit` (M-2).** One line and one template value against a free unauthenticated CPU amplifier.
5. **Block the core module account and route `SendCoins` through the blocked list (M-3).** Two small changes that also un-mask the short-burn detector.
6. **Then M-4, M-5, and the Lows.** L-1 (exec-mode gating on the halt sites) and L-3 (restore the `verify_upgrade.py` bounds) are the cheapest of the remainder and both restore a guarantee the source already claims to provide.

Items 1–3 change chain behaviour and belong in one coordinated upgrade rather than three. Item 1 alone justifies the release.

---

## Assumptions

- No production or UAT server was contacted. Everything is source-level plus the two provenance diffs.
- Governance has an honest majority, but an approved parameter value must still be safe to execute — which is the entire basis of M-1.
- Node-local store read and write failures are realistic and must never be treated as fleet-wide deterministic failures. This is the `v1.34.0` premise and it is what makes H-1 and H-2 High rather than Informational.
- Cosmos SDK transaction and block cache semantics roll back writes when a handler or lifecycle method returns an error.
- The CometBFT RPC port is publicly reachable, per `scripts/fleet_audit.sh` and the accepted address-disclosure decision of 2026-08-13. C-1 and M-2 both depend on reachability, not on secrecy.
- Genesis `raw_state` trust and the indexer moderation boundary remain accepted architecture boundaries and were excluded from scope.

---

## Dispositions

Recorded 2026-08-16. Everything below shipped in `v1.36.0`, which the fixes made
consensus-breaking; the tag was moved and the release re-rehearsed.

### Fixed

| ID | Fix | Regression test |
| :-- | :-- | :-- |
| **C-1** | Transitive message flattening (`nestedMsgs` / `transitiveMsgs`, depth-capped at 4) so the router, the staking decorator and the governance-authority decorator all classify nested messages; nested relay messages rejected outright. `x/authz` unwired from `app_config.go` and its KV store deleted by a `v1.36.0` store loader. | `app/ante_nested_msgs_test.go`, over every relay prototype; mutation-tested |
| **H-1** | `iavl/iterator.go` records the traversal error instead of discarding it; `cachekv/internal/mergeiterator.go` consults parent and cache before its exhaustion sentinel. | `x/core/keeper/failfast_store_test.go` mid-loop fault injection |
| **H-2** | `iavl/store.go` `Set` panics on a tree write error, matching `Get`/`Has`/`Delete`; the finalization guard converts it to a clean halt. | same file |
| **M-1** | New `Params.ValidateGovernanceUpdate()` — reachable `min_difficulty` ceiling (32), non-zero `relay_min_gas_price` / `relay_max_gas_fee` / `subscription_reserve_bps`, `block_hash_window` floor. Kept out of `Validate()` so from-genesis replay still works. Genesis reserve fixed via an `InitGenesis` sentinel plus the genesis file. | `x/core/types/params_test.go` |
| **M-2** | `PowDecorator` returns early when `simulate` is true; `query-gas-limit = 50000000` in the node template. | — |
| **M-4** | The `MsgSetAutoRenewal` branch of `PowDecorator` requires a paid level, mirroring the handler. | — |
| **M-5** | The O(accounts) full scan runs every `SupplyFullScanInterval` (100) blocks behind the O(1) per-block delta check. Measured on prod: 874 accounts, median 107 ms, max 678 ms per scan — about 115 ms of *every* 3000 ms block before this change, growing with a set any user can extend permanently. | — |
| **L-1** | New `haltFinalizeFatal`: the 27 no-error-channel halt sites halt during finalization and panic (recovered by baseapp into an error response) everywhere else. Six sit on the ante path, which runs in check, recheck and simulate, so a transient fault while answering a public query used to `os.Exit(1)` a validator. | `TestHaltFinalizeFatalIsConfinedToFinalization` |
| **L-2** | Negative `Height`/`Version` rejected in both `rootmulti.Restore` and `iavl.Importer.Add`. Was a remote crash of any state-syncing node. | `patches/iavl` suite |
| **L-3** | Parameter bounds checks restored to `verify_upgrade.py`, retightened to the `v1.36.0` governance bounds. | — |
| **L-4** | `loadFullProfile` propagates all six list errors instead of `if err == nil`. | — |
| **L-5** | `checkReserveOrDowngrade` requires the reserve to cover the message count that pubkey submitted in the transaction; the single-message downgrade path is deliberately unchanged. | — |
| **L-6** | `LoggingDecorator` moved after `SigVerificationDecorator`. | `TestRelayAnteDecoratorOrder` |
| **L-7** | The `iter.Close()` failure in `prepForZeroHeightGenesis` panics rather than returning a silently partial export. | — |
| **L-8** | `reflect.Uint32` and `reflect.Bool` cases added to the canon harness — without them the `MsgSubscribe.Level` assertion searched for `0x00`, which every canon buffer contains, and passed vacuously. Plus a new AST-driven check that every field of every relay message appears in its metasig closure, which is the actual authentication boundary the old harness never touched. | `app/ante_metasig_canon_completeness_test.go`; both mutation-tested |
| **L-9** | `immutable_tree.go` `Iterate` and `nodedb.go` `traversePrefix` return `itr.Error()`; `iavl/store.go` `/subspace` refuses to answer with a truncated result. | — |
| **I-1** | `AddRelayCredit` returns an overflow error instead of saturating at 2^64−1. | — |
| **I-2** | `GetBalance` halts on an undecodable address instead of reporting zero. | — |
| **I-3** | `RecordRecentBlockHash` rejects a zero window instead of substituting a duplicated default of 60. | — |
| **I-4** | `IterateRelayCredits` errors on a malformed credit value, matching `GetRelayCredit`. | — |
| **I-5** | All eight hardcoded tier fallbacks replaced with a hard fail, matching `Edit`. | — |
| **I-6** | `max_biography_length = 0` now means disabled at the use site, and `ValidateGovernanceUpdate` rejects `can_have_biography` without a length. | — |
| **I-9** | `govulncheck`, `test-iavl` and `test-store` widened to `./...` (minus `streaming`, whose test needs a compiled plugin). | — |
| **I-10** | `check_patches.sh` gained `dotglob`, dropped the `*.go` filter, and the iavl `LICENSE` was restored — an Apache-2.0 redistribution gap on a public repo. | — |
| — | `batch.go` re-takes the mutex before returning a flush error. A disk-full condition during commit used to surface as `sync: unlock of unlocked mutex`, hiding the real cause. | `patches/iavl/batch_flush_error_test.go`; mutation-tested |
| — | `consensusFatalHalt` writes a breadcrumb that `recover.sh` reads at its forensic-snapshot chokepoint, and exits through a test seam. The prune-hole guard fires from a background goroutine, so an unattended halt was indistinguishable from a crash and the operator's first move was the wipe `AGENTS.md` forbids. | `patches/iavl/consensus_fatal_test.go` |

### Accepted as risk

| ID | Decision |
| :-- | :-- |
| **M-3** | `MsgSendTokens` ignoring the blocked-module-account list is accepted: sending to a module account is self-inflicted fund loss, not an attack on anyone else. Recorded in [`../open-items.md`](../open-items.md) and not to be re-raised. |

### Closed as not-a-defect

| ID | Decision |
| :-- | :-- |
| **I-7** | Retired proto tags protected by comments rather than `reserved`. Fail-closed today; no change. |
| **I-8** | Three legacy messages registered without handlers. They fail at the router; no change. |

### Not-determined items settled

| # | Result |
| :-- | :-- |
| **1** | Live fleet parameters checked read-only against M-1 on both prod and UAT: `min_difficulty=10`, `relay_min_gas_price=1000`, `relay_max_gas_fee=500000000`, `subscription_reserve_bps=9500`, `block_hash_window=60`. All inside the new governance bounds, and no tier shows the I-6 shape. M-1 was a reachability finding, not a live misconfiguration. |
| **3** | Now asserted rather than argued: `AssertModuleSolvencyInvariant` checks core module balance ≥ Σ recorded reserves on the same periodic cadence as the supply scan. Covered by `x/core/keeper/module_solvency_test.go`, including that the sum uses arbitrary precision rather than a `uint64` that would wrap. |
| **5** | Settled by test, not by sentinel. `x/core/keeper/envelope_nonce_roundtrip_test.go` writes a nonce, commits, reopens the same database and asserts it is still present, including through a transaction's cache context. Empty values do survive, so replay protection is sound as written. |
| **7** | Measured on prod: 874 accounts, median 107 ms, p95 176 ms, max 678 ms per scan — roughly 0.13 ms per account. At the old every-block cadence that was ~3.8% of every 3000 ms block, and it scales linearly with a set any user can grow permanently. The 1-in-100 cadence brings it to ~1.15 ms amortised. |

Items 2, 4, 6 and 8 remain open. Item 8 no longer applies to the fixes: every
change above was built and tested, the two vendored fork suites and
`scripts/check_patches.sh` were run, and the release was re-rehearsed through
`scripts/test_upgrade.sh`.
