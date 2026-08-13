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

### Tests

- `fastnode_import_test.go`
- `nodedb_prune_fail_fast_test.go`
- `consensus_fatal_test.go`

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

### Tests

- `rootmulti/commit_info_prune_test.go`

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
