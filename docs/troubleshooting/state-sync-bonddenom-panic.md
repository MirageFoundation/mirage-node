# IAVL Fast-Node Miss Incident

## Summary

On 2026-05-25, `mirage.talk` diverged from the rest of the validator set at
block `4854225`, was killed by the divergence watchdog, and then panicked with
`panic: invalid denom:` from `mint.BeginBlocker` after the watchdog's
state-sync recovery. Root cause: the deployed `blockchain/patches/iavl`
treated a missing fast-node entry at the latest version as proof that the key
did not exist in IAVL. That assumption is wrong. The fast-node index is a
secondary read index. The canonical IAVL tree (rooted at the version's app
hash) is the source of truth for consensus reads. When the fast-node index is
incomplete or stale — which happens on every state-sync import and can happen
transiently during fast-storage upgrades or pruning — every read path that
trusted "fast-node missing" returned `nil` for keys that were demonstrably
present in the verified state. Different nodes' fast-node indices can be in
different states, so this read inconsistency is a deterministic divergence
vector.

The fix removes that short-circuit from every IAVL read path
(`Get`, `GetVersioned`, `Iterator`, `Iterate` on both `ImmutableTree` and
`MutableTree`). Fast-node hits at the requested version are still served from
the index for performance. Fast-node misses always fall back to canonical IAVL.

## Original Divergence (block 4,854,225)

This branch of the incident is **evidence-consistent with the IAVL fast-node
miss**, not formally proven. Evidence:

The watchdog trigger was a CometBFT app-hash mismatch, not a stall:

```text
2026-05-25T17:08:12Z DIVERGENCE DETECTED - log pattern: 'wrong Block.Header.AppHash'
```

At block `4854225`, prod and peers executed the same block with the same tx:

```text
tx: 069D74B61EF6333F5002A93BB2309C001CC1DD0C765412D3D5910529F5A1194B
message: /mirage.core.v1.MsgVote
```

Healthy peers computed:

```text
0C292525581082F0EE257981A555DED8A73A5EFA75986AD02CDE95EECF3A9E42
```

Prod computed:

```text
1FD6806EC0851E2C6B5C06A2D60CCFADF70A7B0197EFBCD4310E2711D83140CD
```

The visible handler path matched on prod and the fourth node:

```text
--> Tx Vote ... phase=deliver ... tx=069D74B...
PoW message recorded height=4854225 count=1
relay accounting: posts counted count=0
```

That rules out "different tx", "tx rejected on peers", and "bad peer
proposal". Among IAVL-level read paths exercised on the deliver path
(`PowDecorator.recentHashSeen`, `Keeper.GetParams`, `Keeper.RecordPoWMessage`
counter read, profile lookups), every one of them depends on the same
fast-node read contract that we have now proven incorrect for the state-sync
case. Without per-node IAVL state captures from the moment of divergence we
cannot point at one specific key, but the only IAVL-level read pattern that
would yield a different value on prod vs peers for the same input is exactly
this one. We treat the original divergence as **explained, not reproduced**.

## State-Sync BondDenom Panic (proven)

The post-recovery failure is **proven** to be the same bug:

```text
mint.BeginBlocker
  -> DefaultMintFn
    -> Keeper.StakingTokenSupply(ctx)
      -> stakingKeeper.BondDenom(ctx)   // returned ""
      -> bankKeeper.GetSupply(ctx, "")  // sdk.NewCoin("", ...) panicked
```

State-sync verified the canonical app hash and restored the snapshot. The
next block panicked because a latest-version `Get` of `staking/params`
returned `nil` through the fast-node path even though the canonical IAVL
tree contained the params. This is reproduced deterministically by
`patches/iavl/fastnode_import_test.go`.

## Code Cause

Across `blockchain/patches/iavl/{immutable_tree.go, mutable_tree.go}` the
fast-node read paths short-circuited to `nil` (or to a `FastIterator` that
walks only the index) when the index reported a miss at the latest version.
The simplest illustration, from `ImmutableTree.Get`:

```go
if fastNode == nil {
    if t.version == t.ndb.latestVersion {
        return nil, nil   // BUG: trusts an advisory index as authoritative
    }
    _, result, err := t.root.get(t, key)
    return result, err
}
```

`ImmutableTree.Iterator` and `MutableTree.Iterator` had the same defect at
the iterator level — they returned `FastIterator`/`UnsavedFastIterator`,
which walk only the fast-node index and silently omit keys that are present
in canonical IAVL but absent from the index.
`MutableTree.GetVersioned` had the same `return nil, nil` short-circuit as
`Get` at `version == latestVersion`.

## Fix

Every read path now treats fast-node misses as a hint, never as proof of
absence:

- `ImmutableTree.Get` — falls through to `t.root.get(t, key)` on a miss.
- `ImmutableTree.Iterator` — always returns `NewIterator` (canonical
  traversal). `FastIterator` is no longer on the consensus read path.
- `ImmutableTree.Iterate` — uses the patched `Iterator`, so canonical too.
- `MutableTree.Get` — already correct (falls through to `ImmutableTree.Get`).
- `MutableTree.GetVersioned` — short-circuit removed.
- `MutableTree.Iterator` / `MutableTree.Iterate` — delegate to the canonical
  `ImmutableTree.Iterator`. `MutableTree.set` keeps `ImmutableTree.root` in
  sync with every unsaved write, so canonical traversal already reflects
  uncommitted state without consulting the fast-node index.

Fast-node *hits* at or before the requested version are still served from
the index — this is purely a correctness change, not a "disable the cache"
change.

`FastIterator` remains in the package for the fast-storage maintenance flow in
`MutableTree.enableFastStorageAndCommit` (enumerating live fast-nodes during
the storage upgrade), which is not on the consensus read path.
`UnsavedFastIterator` is no longer used by Mirage's read paths; it remains only
as upstream fork surface area.

## Performance Note

Every fast-node *miss* now traverses canonical IAVL instead of returning `nil`
immediately. For absent point reads this means an extra O(log n) IAVL walk per
read. In normal steady state — fast-node index fully populated — point-read
hits dominate and continue to short-circuit.

Range iteration is intentionally different: `Iterator` and `Iterate` now always
walk canonical IAVL and no longer use the fast-node DB index as their backend.
That can make large range scans slower than the previous fast-index-only path.
We accept that cost because a complete canonical range scan is consensus-safe;
a fast range scan that silently omits keys is an app-hash divergence vector.
For Mirage's current consensus paths the relevant ranges are bounded or small,
but this should be benchmarked before adding any new per-block full-store scans.

## Regression Test

The regression test is `blockchain/patches/iavl/fastnode_import_test.go`.
It builds a destination `MutableTree` whose canonical IAVL is fully
populated via `Export`/`Import` at version V, but whose fast-node index is
empty even though it claims to be current at V — exactly the production
state-sync failure shape. It then asserts every read path returns canonical
values:

- `ImmutableTree.Get`
- `ImmutableTree.Iterator`
- `ImmutableTree.Iterate`
- `ImmutableTree.IterateRange`
- `ImmutableTree.IterateRangeInclusive`
- `MutableTree.GetVersioned`
- `MutableTree.Iterator`

Additional pins cover an empty-tree iterator (must return an empty iterator,
not panic) and `GetVersioned` for historical versions when the fast-node index
contains a newer value than the requested version.

Keys are intentionally representative — `staking/params` (the concrete
`BondDenom` panic vector), `core/recent_block_hashes` (the PoW recent-hash
read path that ran during the original divergence) and
`core/pow_msg_count:4854225` (the original divergence height marker). The
test does not depend on Cosmos-SDK store key encoding; the IAVL invariant
being checked is "all read paths agree with canonical IAVL when the
fast-node index is incomplete".

Run it with:

```bash
cd blockchain
make test-iavl
# or it runs automatically as part of:
make test-fast
```

`test-iavl` is wired into both `test-fast` and `test`. Because
`patches/iavl` is its own go module (`replace` directive in `go.mod`), it
is **not** picked up by `go test ./...` — the explicit Makefile dependency
is the only thing keeping it in CI.

## Rollout

This patch changes the local IAVL read contract. The change is **state-machine
breaking by definition**: it changes the values that consensus reads observe
(specifically: post-state-sync nodes used to silently see `nil` where they
now see the canonical value). Two nodes running different binaries against
the same canonical state will compute different app hashes the moment one of
them hits a fast-node miss. Rollout must therefore be **coordinated** across
the validator set.

Coordinated rollout is shipped as `v1.26.0`:

- Upgrade handler: `blockchain/app/upgrades.go` (`v1.26.0`). The handler is
  intentionally a no-op for on-chain state — it carries `RunMigrations` for
  module-version bookkeeping and a logging line marking the IAVL contract
  change. There are no new params, no new store keys, no module migrations.
- Release notes: `docs/updates/update_v1.26.0.md`.
- Upgrade verification: `scripts/verify_upgrade.py` (rewritten to v1.26.0
  checks).
- Proposal: `scripts/proposals/proposal_upgrade.json`.
- Regression test: `make test-iavl` (also runs as part of `make test-fast`).

Until the patched binary (v1.26.0) is on every validator past the upgrade
height, prefer `recover.sh peer-pull` over `recover.sh state-sync` for any
recovery — peer-pull copies the source's already-populated fast-node index
and is therefore not exposed to this bug class. The watchdog default remains
peer-pull (set in Phase 1 of the recovery hardening plan).

After v1.26.0 is live across the validator set, state-sync is safe again on
this chain.

## Upstream Cross-Check (follow-up)

We have not yet cross-referenced upstream `cosmos/iavl` to confirm whether
their unpatched code has the same defect, or whether our fork introduced /
preserved it during a previous merge. That investigation is a deliberate
follow-up; it does not block the v1.26.0 rollout because the fix is local
to our patched module.
