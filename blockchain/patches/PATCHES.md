# Vendored Consensus Patches

`go mod verify` and default `govulncheck` **silently skip** `replace`-directed local
modules. Treat this file as the provenance source of truth for both forks.

## `github.com/cosmos/iavl` → `./patches/iavl`

| | |
|---|---|
| Upstream module | `github.com/cosmos/iavl` |
| Upstream tag | `v1.2.8` |
| Upstream commit | `45196a8322a03bf2ef3888e314e24f2b3bcb49bb` (annotated tag object: `f71f58be8e82fdddf3fcb5f4d4a94b6f0850434e`) |
| Fork date | 2026-06 / 2026-07 (fast-node + prune-hole work) |

### Functional changes (only these; everything else is upstream)

The vendored module intentionally omits upstream `cmd/`, `benchmarks/`,
documentation, and upstream-only test files; none are linked by Mirage.

1. **`immutable_tree.go`** — remove fast-node lookup from `ImmutableTree.Get`; force canonical iterator in `ImmutableTree.Iterator`.
2. **`mutable_tree.go`** — disable unsaved fast-node overlay in `MutableTree.Get`; delegate `Iterate` / `Iterator` / `GetVersioned` to the canonical tree.
3. **`nodedb.go` `deleteVersion`** — reference-root reformat reordered to **Set-then-Delete** (upstream is Delete-then-Set; flush mid-pair created prune holes).
4. **`nodedb.go` `deleteVersionsTo`** — fail-fast `CONSENSUS_FATAL:PRUNE_HOLE` guard with batch flush + re-probe before panicking/halting; skip missing versions on state-synced gaps instead of aborting the whole prune.
5. **`consensus_fatal.go`** — process-exit helper for the prune-hole guard; local and stdlib-only because the replacement module cannot import the application package.
6. **`iterator.go` `Iterator.Next`** — assign `iter.err` when `traversal.next()` fails. Upstream invalidates the iterator and discards the error (its own `TODO` on that line is the admission), so `Error()` and `Close()` both returned `nil` and a truncated iteration was indistinguishable from a clean one. A truncated iteration that commits is AppHash divergence.
7. **`immutable_tree.go` `ImmutableTree.Iterate`** — return `itr.Error()` instead of an unconditional `(false, nil)`, so a caller can tell "visited every key" from "stopped early on a read fault".
8. **`nodedb.go` `traversePrefix`** — return `itr.Error()`, matching the sibling `traverseRange` which already does. Both prefix walks in `deleteLegacyVersions` run through here, so a truncated walk left legacy orphans undeleted while reporting success — unbounded disk growth invisible to the `MIRAGE_PRUNE_DEGRADED` counter.
9. **`batch.go` `BatchWithFlusher.Set` / `.Delete`** — re-take `mtx` before returning the flush error. Both methods drop the lock around the threshold flush, and upstream's `if err := b.Write(); err != nil { return err }` returns while still unlocked, so the deferred `Unlock` panics with `sync: unlock of unlocked mutex`. A disk-full or read-only volume during commit therefore surfaced as an unrelated runtime mutex error, hiding the real cause on the one path where it matters most.
10. **`consensus_fatal.go`** — write a breadcrumb file (`MIRAGE_CONSENSUS_FATAL_FILE`, else `$MIRAGE_NODE_HOME/.consensus_fatal`, else `$HOME/.mirage/.consensus_fatal`) before exiting, and route the exit through an `exitProcess` seam so the guard is testable. The prune-hole guard fires from the background pruning goroutine, so an unattended halt was indistinguishable from an ordinary crash: `recover.sh` reads the breadcrumb at its forensic-snapshot chokepoint, records the reason in `MANIFEST.txt` and preserves the file inside the capture. Keep `breadcrumbPath` in lockstep with `consensusfatal.BreadcrumbPath`, which cannot be imported here.
11. **`import.go` `Importer.Add`** — reject a negative `Version` or `Height`. Upstream bounds `Version` only from above, then indexes `i.nonces[exportNode.Version]` on a slice allocated as `make([]uint32, version+1)`, so a negative value is an out-of-range panic. Every field reaching this function comes off the wire from the state-sync peer, and chunk hashes are verified only against that same peer's metadata, so a malicious peer chose the value. The restore goroutine has no `recover`, so the panic killed the node instead of rejecting the snapshot and trying the next peer — a remote crash of any node bootstrapping by state sync. Also guarded at the `rootmulti` call site; both, because this is the function that does the indexing.

### Tests

- `fastnode_import_test.go`
- `nodedb_prune_fail_fast_test.go`
- `consensus_fatal_test.go` (also covers the breadcrumb and its path resolution)
- `batch_flush_error_test.go`
- Deviations 6–8 are pinned from the application side by `x/core/keeper/failfast_store_test.go` (`TestIteratorFaultMidLoopHalts`), which drives an injected mid-loop fault through the real cachekv stack.

### Advisory tracking

Subscribe to GitHub security advisories for `cosmos/iavl`. Rebase review at least quarterly.

---

## `github.com/cosmos/cosmos-sdk/store/v2` → `./patches/cosmos-sdk-store-v2`

| | |
|---|---|
| Upstream module | `github.com/cosmos/cosmos-sdk/store/v2` |
| Upstream tag | `v2.0.0` |
| Upstream commit | `f45bfa5c9d80112a0bd55c9a671ca0759941f7b9` (`store/v2.0.0`; annotated tag object: `3920dda30c4ee8236b6249af4d6f28c1763b7751`) |
| Upstream issue | https://github.com/cosmos/cosmos-sdk/issues/26551 |
| Upstream PR | rootmulti commit-info prune (courtesy contribution) |
| Fork date | 2026-06-23 |
| Security dependency refresh | 2026-08-04 |

### Functional changes (only these)

1. **`rootmulti/store.go`** — `pruneCommitInfo` called from `PruneStores`; deletes `s/<version>` commit-info records below `pruningHeight`, capped at `commitInfoPruneBatch = 20000` per pass. Collect-then-close-then-write to avoid MemDB iterator/writer deadlock.
2. **`rootmulti/store.go`** — `PruneStores` no longer returns `nil` after a failure. Upstream logged each per-store failure and then reported success, so a node that had stopped reclaiming disk (read-only volume, full disk, wedged substore) looked healthy to `Commit` and to the `prune` CLI alike. Every failure — per-store `DeleteVersionsTo`, the `s/earliest` write, and `pruneCommitInfo` — now increments `pruneFailures` (exposed by `PruneFailures()`), logs at error level under the greppable `MIRAGE_PRUNE_DEGRADED` marker, and is joined into the returned error. The pass still attempts the remaining stores, and the node never halts: pruning is node-local housekeeping and never consensus input, so `Commit` logs and continues while the `prune` CLI exits non-zero. Upstream's early return on `ErrVersionDoesNotExist` is unchanged apart from the added log and counter, so it still skips the remaining stores.
3. **`go.mod` / `go.sum`** — security-only dependency floors track the release
   toolchain and patched gRPC / `x/net` / `x/text` versions. No module API or
   store behavior is changed by these pins.
4. **`cachekv/internal/mergeiterator.go` `Error`** — consult `parent.Error()` and `cache.Error()` before falling through to the exhaustion sentinel, filtering the two known "iteration finished" markers via `isExhaustionSentinel`. Upstream's version is a pure `Valid()` proxy, so it manufactured the same sentinel for a genuine storage fault as for normal exhaustion. Every keeper store access is branched through cachekv, so this layer alone made a mid-iteration fault unobservable. Keep `isExhaustionSentinel` in lockstep with `iteratorExhausted` in `x/core/keeper/failfast_store.go`.
5. **`iavl/store.go` `Store.Set`** — `panic(err)` on a tree write failure, for symmetry with `Get`, `Has` and `Delete`, which all already panic. `types.KVStore` has no error return at that boundary, so upstream's log-and-continue meant the fail-fast wrapper had already reported success and nothing could observe the lost write: one validator commits a block without the key while healthy peers commit with it. The panic is converted into a clean halt by the finalization guard.
6. **`iavl/store.go` `Store.Query` `/subspace`** — check `iterator.Error()` before marshalling, and return an error rather than answering a remote client with a silently truncated result set. Returns rather than halts: queries commit nothing, so no divergence is possible.
7. **`rootmulti/store.go` `Restore`** — reject a negative `IAVL.Height` or `IAVL.Version` from a snapshot item before handing it to `importer.Add`. Upstream checks only the `MaxInt8` ceiling on height and nothing at all on version. Paired with iavl deviation 9; see that entry for the crash path.

### Tests

- `rootmulti/commit_info_prune_test.go`
- Deviation 4 is pinned from the application side by `x/core/keeper/failfast_store_test.go` (`TestIteratorFaultMidLoopHalts` and `TestIteratorFaultMidLoopReturnsOutsideFinalize`).

### Advisory tracking

Subscribe to GitHub security advisories for `cosmos/cosmos-sdk`. Rebase review at least quarterly.

---

## CI / local checks

```bash
# From blockchain/
make test-patch-provenance test-iavl test-store

# Vulnerability scan against the main and replaced modules explicitly
make govulncheck
```

`scripts/check_patches.sh` (repo root) downloads the recorded upstream modules,
compares every vendored file outside the documented touch list byte-for-byte,
and also fails when an upstream production Go file was omitted.
