# "mirage.talk is down" — Divergence Triage & Recovery

Runbook for the incident class where the site looks dead (API returns
`503 node_catching_up`, frontend loads but shows no data, writes fail) because
the local node fell out of step with the rest of the cluster. Written after the
2026-06-12 divergence (height 5280037) and the 2026-06-14 stuck-consensus stall
(height 5329009). General entry point for all validator sickness:
[`incident-recovery.md`](incident-recovery.md).

> Latest incident: [2026-06-16 mirage.talk divergence + dead auto-recovery](postmortems/2026-06-16-mirage-talk-divergence.md)
> (height 5378002). That postmortem documents three recovery-tooling failures —
> missing `ssh` in the container, the `serve` SIGCONT unbound-var bug, and the
> watchdog ignoring divergence while `catching_up=true` — all now fixed.

## TWO failure classes, TWO cures

The watchdog and `recover.sh` now distinguish two very different problems. Get
this distinction right before acting — it decides whether you wipe the DB:

| Symptom | Class | Cure | Destructive? |
|---|---|---|---|
| Height frozen, `catching_up=false`, **app_hash at the stuck height MATCHES peers** | **Stuck consensus / runtime hang** (2026-06-14) | `recover.sh restart` | No — just restarts the process |
| `wrong Block.Header.AppHash` in log, OR stall whose **app_hash DISAGREES** with peers | **State divergence** (2026-06-12) | `recover.sh peer-pull` | Yes — wipes & re-pulls chain DBs |
| Process dead | **Crash** | `recover.sh restart`, then peer-pull if it can't recover | restart first |

The watchdog's automatic escalation ladder:

```
log-pattern divergence   -> peer-pull            (gated by WATCHDOG_AUTORECOVER)
stall + app_hash MATCH   -> restart              (ungated; non-destructive)
stall + app_hash MISS    -> peer-pull            (gated)
process-dead             -> restart, then peer-pull if restart fails to recover
3 restarts within 2h     -> peer-pull            (recurrence escalation)
```

The restart path is ungated and runs on **every** validator (the watchdog is
`AUTO_DIVERGENCE_RECOVERY=true` everywhere now). Destructive peer-pull stays
gated by `WATCHDOG_AUTORECOVER=true`, which should be set on exactly one host
(mirage.talk).

---

## 0. 2026-06-22 — supply-invariant divergence (h5522659) + mitigations

A single node diverged at **height 5522659** on a `MsgVote` tx with
`CONSENSUS_FATAL:SUPPLY_INVARIANT` (recorded supply != sum of balances). This
was **after** the v1.28.0 upgrade (SDK v0.54 store/v2 + #24655 atomic
lastCommitInfo / state-manager serialization), so the upstream Commit↔Query
race fix did **not** cover it. A money-conservation break on one node only is
the signature of a non-deterministic read during tx execution.

Three changes landed in response (all repo-side, no chain upgrade):

1. **`inter-block-cache = false`** in `deploy/templates/node/app.toml`, applied
   to already-deployed nodes by migration
   `deploy/migrations/v1_28_2_disable_inter_block_cache.py` (config-only, picked
   up on the next miraged restart — rolling, low risk). The inter-block cache is
   a shared, mutable-across-blocks `CommitKVStore` cache and is the most likely
   remaining non-deterministic read surface. This was the Plan-A mitigation that
   was previously skipped.

2. **Always-on pre-wipe forensic snapshot.** `recover.sh` now preserves the
   diverged chain DBs into `/root/.mirage/.divergence_forensics/<utc>-h<height>/`
   **before** any wipe, at the single `wipe_chain_dbs` chokepoint (so both
   peer-pull and state-sync are covered, automated or manual, regardless of
   `--force`). The watchdog passes `RECOVERY_REASON=watchdog:<trigger>` so the
   capture's `MANIFEST.txt` is traceable. Retention is bounded by `FORENSIC_KEEP`
   (default 2). **Never wipe a diverged DB without a snapshot** — it is the only
   artifact that lets us replay the offending block. See `RULES.md`.

3. **MsgVote → mint/burn audit.** The cache-sensitive reads on the vote path
   are the balance reads that *clamp* a burn/spend amount:
   - `deductRelayGasFee` (paid voters) → `BurnFromModuleAmount` /
     `DeductFeeFromOwner`, which read the module/owner balance via
     `bank.GetBalance` and clamp the burn to it (`if bal.LT(amt) { amt = bal }`,
     `keeper.go`). A stale cached balance here changes the burned amount on the
     affected node only → supply != balances at `AssertSupplyInvariant`
     (EndBlock).
   - `MintIfNeeded` (BeginBlock, mint-interval blocks) and `mintAndDistribute`
     read params + staking state and mint/send/burn; the same cache exposure
     applies to those store reads.

   `AssertSupplyInvariant` (EndBlock) is the **detector**, not the cause: it
   iterates all balances vs `GetSupply` and halts the node if they disagree.
   Disabling the inter-block cache forces every one of these reads through the
   canonical store, removing the non-determinism. Follow-up: consider whether the
   burn-clamp fallbacks should fail hard instead of silently clamping (per
   `RULES.md` "no fallbacks"), so a bad balance read surfaces as a rejected tx
   identically on all nodes rather than as a per-node supply drift.

### 0.1 Root-cause investigation — the IAVL pruning fork is the origin (2026-06-22)

The mitigations above (fast-node off, inter-block-cache off) all address the
**read** side of a node-local read-consistency race. A fork-vs-upstream diff of
the repo's vendored IAVL (`blockchain/patches/iavl`) pins the **pruning** side —
the half that was never reverted:

- The fork was first introduced **2026-04-02** (`8f0aa77` + `5c384f1`, base
  `cosmos/iavl v1.2.2`). At that point the **only non-test file changed vs
  upstream was `nodedb.go`** — two hunks that swallow `ErrVersionDoesNotExist`
  during pruning ("skip missing versions"). `immutable_tree.go` /
  `mutable_tree.go` were byte-identical to upstream; the fast-node read patch
  came **later** (`0445ee1` 2026-05-27, a response to the May divergences).
- The same-day `app/app.go` change (`fixStalePruneSnapshotHeights`) **switched
  active pruning ON for the first time** — its own commit message: *"stale
  entries prevented IAVL pruning entirely … application.db 3.2 GB → 2.4 GB after
  first compaction cycle."* Pruning runs in a background goroutine
  (`nodedb.startPruning`) concurrently with commits and with the prod-only local
  query traffic (indexer, backend `simulate`, reward distributor).
- First app-hash divergences began **~2–4 weeks later** (the 2026-05-09 review
  records a 2026-05-04 divergence at h4,349,996; then h4854225 on 05-25, h5280036
  on 06-12, h5378002 on 06-16). The fork's own comment in `immutable_tree.go`
  names *"pruning races"* as a cause of the fast-node index going stale.
- **Today** the bump to `v1.2.8` means `nodedb.go` is again byte-identical to
  upstream (upstream adopted the same "tolerate missing version" behavior via
  `rootkeyCache`). So the swallow is now *upstream* code, and the fork's only
  delta vs v1.2.8 is the fast-node read disable in `immutable_tree.go` /
  `mutable_tree.go`.

**Fix applied — fail-fast pruning guard (Mirage patch on `nodedb.go`).**
`deleteVersionsTo` now distinguishes the two missing-version cases instead of
swallowing both:

- A **contiguous prefix of missing versions at the bottom** of the prune range
  is the legitimate state-sync gap (those versions were never written locally) →
  skip and continue, as before.
- A version **missing above one already seen** is a hole in otherwise-present
  history (DB corruption / pruning-bookkeeping bug) → **panic
  `CONSENSUS_FATAL:PRUNE_HOLE`**. A deterministic crash is recoverable by the
  watchdog (peer-pull restores the DB from a healthy peer); a silent skip leaves
  the node running and serving reads off inconsistent state. Unit tests:
  `blockchain/patches/iavl/nodedb_prune_fail_fast_test.go`.

**Notification.** `CONSENSUS_FATAL:PRUNE_HOLE` is in the watchdog's
`DIVERGENCE_PATTERNS` (→ peer-pull). The watchdog also gained an **external push
alert**: set `ALERT_WEBHOOK_URL` (Slack/Discord/Mattermost/ntfy-compatible) and
it POSTs a one-liner whenever it fires a loud alert or dispatches a recovery —
so a crash/divergence pages a human instead of only landing in a tmux log nobody
is watching. Unset = disabled; failures are swallowed to the forensic log and
never stall the loop.

**Independent stuck-node pager (`scripts/stuck_node_alert.py`).** The watchdog
only pages on a `catching_up=true` + frozen node when it *also* finds a
divergence log pattern — so a *silent* freeze (the 2026-06-16 case: no
`wrong Block.Header.AppHash`, no marker) is invisible to it, and a watchdog that
is itself `kill -STOP`'d (as during a manual recovery) can't page at all. This
standalone pager closes both gaps: it runs in its **own** tmux window (separate
process), imports nothing from the watchdog, and pages `ALERT_WEBHOOK_URL` on a
single rule — local height frozen, or `/status` unreachable, for
`STUCK_ALERT_SECONDS` (default 600), regardless of any log marker. It only starts
when `ALERT_WEBHOOK_URL` is set and **never recovers anything** (detection only;
recovery stays the watchdog's job). Logs to
`/root/.mirage/logs/deploy/stuck_node_alert-YYYY-MM-DD.log`. Manual check:
`docker exec mirage python3 /opt/mirage/scripts/stuck_node_alert.py --once`
(one poll) or `--selftest` (verify config + send a test page).

Note pruning itself stays **on** — it is required to bound disk growth
(`PRUNING_KEEP_RECENT=1000`, `PRUNING_INTERVAL=100`). The fix is to make a prune
that hits inconsistent state *halt* rather than mask it, not to disable pruning.

### 0.2 Confidence & status — READ THIS before calling it fixed (2026-06-22)

**Nothing in §0.1 is a proven root cause. It is the prime suspect, not a
conviction.** Honest status of the pruning work, so nobody mistakes it for a cure:

- **What was tested:** only at the **unit level** — the guard's logic
  (`blockchain/patches/iavl/nodedb_prune_fail_fast_test.go`: a synthetic
  mid-history hole panics; a synthetic bottom gap is skipped) and that the full
  `miraged` binary + the watchdog compile and their tests pass. **No real
  diverged snapshot has been replayed.** No prod box was touched.
- **What is NOT proven:** that a pruning operation actually produced any observed
  app-hash divergence. §0.1 is a **timeline + code-comment** argument (pruning
  was switched on 2026-04-02, weeks before the divergences began; the fork's own
  `immutable_tree.go` comment names "pruning races"). That is **correlation, not
  causation.**
- **The guard is defensive hardening, not a fix.** It converts a *silent*
  corrupt-state prune into a *loud, recoverable, alerting* halt
  (`CONSENSUS_FATAL:PRUNE_HOLE` → watchdog peer-pull). It does **not** make
  divergences impossible, and it does **not** touch the read path.
- **Surface mismatch to keep in mind:** the *observed* divergences (the
  postmortems) were **fast-node stale reads** / a supply-invariant break during
  block execution — a *read-path* fault, already targeted by
  `iavl-disable-fastnode=true`, dropping fast-node from the read path, and
  `inter-block-cache=false`. The pruning guard addresses a *different* (related)
  failure mode; do **not** assume it would have caught the 05-25 / 06-12 / 06-16
  events.
- **What would actually settle it:** on an isolated box (never prod), replay the
  offending block from a real diverged snapshot with pruning active vs
  `pruning="nothing"`, and/or diff the diverged DB's IAVL/pruning state against a
  healthy peer's at the same height. Tooling: `scripts/replay_divergence.sh`
  (forensic scan, drives `blockchain/cmd/analyze-db`) plus the behavioral A/B
  procedure documented in that script's header. **Until that runs, the pruning
  fork is a suspect, not the culprit.**

#### 0.2.1 First real-snapshot scan run — pruning-bloat hypothesis NOT supported (2026-06-22)

The static half of the above finally ran against **real** snapshots (the 06-16
diverged DB was gone — that recovery kept only `priv_validator_state.json` — but
the **06-12** incident's full diverged DB was preserved as
`data.preheal-20260612T164034Z`, h**5280037**, same divergence class). Both the
diverged DB and a current **healthy** peer (<val4>, never diverged) were
copied off-host and scanned with `analyze-db`:

| snapshot | commit-info (`s/<version>`) count | version floor |
|---|---|---|
| diverged (06-12, h5280037) | 2,133,637 | **3146400** |
| healthy (<val4>, h5532429) | 2,386,030 | **3146400** |

- **Result:** the "PRUNING APPEARS BROKEN" signal (commit-info store far larger
  than `keep-recent`) is present on the **healthy** node too, with the **same
  version floor**. So it is **fleet-wide, not divergence-specific**, and **does
  not implicate pruning in the divergence.** `replay_divergence.sh` was corrected
  so its verdict no longer reads a standalone commit-info count as "consistent
  with the prune-race hypothesis" — it now requires a diverged-vs-healthy floor
  delta and says so.
- **What this does and does not mean:** it rules out *commit-info bloat* as the
  culprit. It does **not** refute the IAVL *node-level* prune race (deleting/
  serving inconsistent nodes under concurrent reads) — a static count cannot see
  a transient, load-triggered race. That still needs the behavioral A/B under the
  prod-only concurrent read load (`replay_divergence.sh --procedure`), which needs
  a snapshot whose blocks H..H+2 are locally replayable. **Still the honest
  bottom line: the pruning fork remains a suspect, not the culprit — and the
  cheap static evidence now leans *against* the bloat theory.**
- **Side discovery (the real disk-growth driver):** the cosmos-sdk commit-info
  store (`s/<version>`, ~848 B/height) is **never pruned** — ~1.83 GB of the
  ~1.84 GB `application.db`, growing every block, fleet-wide (floor v3146400 =
  DB-creation height). The IAVL state itself is only ~85 MB (node pruning works).
  `min-retain-blocks=201600` is not the floor (2.1M ≫ 201600) and
  `pruneSnapshotHeights` is healthy. **Confirmed root cause:** the store our
  v0.54 binary actually links is `github.com/cosmos/cosmos-sdk/store/v2@v2.0.0`
  (verified via `go mod why`: `mirage/app → baseapp → store/v2`; the legacy
  `cosmossdk.io/store` is unused — *"main module does not need package"*). NOTE:
  this `store/v2` is the **relocated rootmulti** module (moved into the SDK repo,
  bumped to v2.0.0), **not** the SS/SC architectural rewrite — so it has the same
  bug: `PruneStores()` prunes only IAVL versions and bumps the `s/earliest`
  pointer, but never deletes commit-info (`s/<version>`), which `flushCommitInfo`
  writes every block.   (Verified 2026-06-23 by source-fetch: `store/rootmulti/store.go` is
  byte-identical across the `store/v2.0.0` tag, `release/v0.54.x`, and `main`,
  none delete commit-info; there is no SS/SC store in the repo to migrate to, so
  no upstream version fixes it — our patch is the only fix.) **Fixed (action item 12):** forked the
  store/v2 module (`blockchain/patches/cosmos-sdk-store-v2`,
  `replace github.com/cosmos/cosmos-sdk/store/v2 => ./patches/cosmos-sdk-store-v2`,
  like the iavl patch) and added `pruneCommitInfo` to `PruneStores` — each prune
  pass deletes `s/<v>` for `v < pruningHeight`, capped at 20000/pass so the
  historical backlog drains gradually. Consensus-safe (the app hash uses the
  *current* commit-info), so nodes draining the backlog at different rates is
  fine, and **no chain upgrade/state migration is needed** (we are already on
  store/v2). After deploy, expect `application.db` to shrink as the backlog
  clears.

### 0.3 First post-deploy soak — the guard fired for real + a new lead (2026-06-25)

~2.5 days after v1.28.2 rolled to the whole mainnet-1 validator set (mirage.talk
+ mirage.vote + <val3> + <val4>), a fleet-wide log scan
(forensic captures, watchdog events, AppHash markers, restart cadence) found:

- **Zero state/app-hash divergences.** No `wrong Block.Header.AppHash` on any
  node; all four on the same chain and in sync. mirage.talk specifically — the
  only historically-diverging node — was clean (0 PRUNE_HOLE, 0 app-hash).

- **The PRUNE_HOLE guard fired once, in the wild, exactly as designed.** On
  **mirage.vote, 2026-06-24 18:22:37Z**:
  `CONSENSUS_FATAL:PRUNE_HOLE missing_version=5569770 (first=5558400 prune_to=5571899 latest=5572900)`.
  A version was missing **above** existing history during a prune pass, so the
  guard panicked instead of pruning inconsistent state; the supervisor restarted
  miraged 5s later, it replayed the WAL and rejoined. **It happened once and did
  NOT recur** (0 on 06-23, 0 on 06-25), so it was a *transient* prune-bookkeeping
  inconsistency, not persistent on-disk corruption. Pre-v1.28.2 this is the case
  upstream IAVL would have silently swallowed and kept serving reads off — i.e.
  it is concrete evidence the prune race is **real** and is now *contained*
  (converted to a recoverable crash). It is **not** proof it was the divergence
  cause; no app-hash break accompanied it. (`WATCHDOG_AUTORECOVER` is off on
  mirage.vote, so the watchdog only alerted — no peer-pull, no forensic snapshot
  was taken; the in-process supervisor restart was enough.)

- **NEW fault — `pebble: closed` panic on shutdown, fleet-wide (root-caused).**
  Every node hits it on its weekly maintenance restart (counts 06-23..06-25:
  mirage.talk **3**, mirage.vote 2, <val3> 2, <val4> 1). The log
  shows a **double-close of `application.db` during graceful shutdown**:

  ```
  INF Closing application.db module=baseapp
  INF Closing snapshots/metadata.db module=baseapp
  INF Closing application.db module=baseapp      <-- closed a SECOND time
  FATAL: panic: pebble: closed
  ```

  **Root cause (confirmed, source-level):** upstream cosmos-sdk `v0.54.3`
  `server/start.go` `startInProcess` registers **two** deferred cleanups that
  both call `app.Close()` (`startCmtNode` cleanup L418 + `startApp` cleanup
  L643), and `baseapp.(*BaseApp).Close()` (L1155) is not idempotent — it closes
  `app.db` unconditionally. First defer closes cleanly (app.db + snapshots),
  second defer re-closes `app.db` → `pebble: closed`. Stock wiring
  (`server.StartCmd(newApp,…)`), pure upstream bug.

  **Trigger (confirmed):** the `mirage-weekly-upgrade.timer` systemd timer runs a
  **weekly** `apt full-upgrade` (~04:00, staggered per host, with a chain-liveness
  pre-flight). It upgrades `docker-ce`/`containerd.io`, which **restarts the
  Docker daemon**, bouncing every `unless-stopped` container → miraged SIGTERM →
  the double-close. Intended security maintenance; benign.

  **Correction to the first-pass hypothesis:** the double-close does **not**
  meaningfully seed the prune holes — the *first* close is clean, so `app.db` is
  closed properly; the panic is the redundant second close at the tail of an
  orderly shutdown. (Also: the one observed PRUNE_HOLE on mirage.vote fired ~14 h
  *after* that node's restart, not at shutdown.) The real cost is signal/noise:
  every weekly restart logs a `FATAL: panic` + non-zero exit, polluting the
  crash/forensic monitoring and able to mask a real `Close()` error.

  **Fix (06-16 postmortem item 13):** the first attempt (v1.28.2) wrapped only the
  `db` passed to `newApp` in an idempotent-`Close` shim — but the 07-08 soak showed
  panics **still occurring**, because `BaseApp.Close()` closes **both**
  `application.db` *and* `snapshots/metadata.db` and the db-shim covered only the
  former. The complete fix moves the guard up a level: `app.(*App).Close()`
  (`blockchain/app/app.go`) now runs the embedded `BaseApp.Close()` exactly once via
  `sync.Once`, so *every* handle it touches is closed once regardless of how many
  times the server calls `app.Close()`. The partial db-shim was removed; regression
  test `TestAppCloseIsIdempotent` fails without the guard. Reported upstream as
  cosmos-sdk PR [#26559](https://github.com/cosmos/cosmos-sdk/pull/26559)
  (`BaseApp.Close` nils its handles after closing).

- **Caveats:** only ~2.5 days of soak, and the external pager is still disabled
  (`ALERT_WEBHOOK_URL` unset) — none of the above paged anyone; it was found only
  by manual log scan.

### 0.3.1 Root cause of the recurring PRUNE_HOLE — pinned (2026-07-08)

Analysis of the two captured PRUNE_HOLE events on mirage.talk
(`/root/.mirage/.divergence_forensics/`, val1 `<val1>`):

| when | guard log |
|------|-----------|
| 2026-06-28 06:18 | `missing_version=5656103 first=5650500 prune_to=5658299 latest=5659300` |
| 2026-07-05 20:03 | `missing_version=5841942 first=5832000 prune_to=5845499 latest=5846500` |

Both are a **single missing rootkey in the middle of otherwise-present, unpruned
history** (not a contiguous state-sync gap), `keep-recent≈1000`
(`latest − prune_to ≈ 1001` both times). The 8:03PM pass had already deleted
`5832000..5841941` successfully and then walked into an *already-missing* `5841942`
— i.e. the hole pre-existed the pass that reported it.

**Mechanism (code-level, `blockchain/patches/iavl/nodedb.go` + `patches/cosmos-sdk-store-v2/rootmulti/store.go`):**

1. **Async pruning is ON** (`rootmulti` L1123 `AsyncPruningOption(!iavlSyncPruning)`;
   `iavlSyncPruning` defaults false). Deletes run in a background goroutine
   (`startPruning`, nodedb L651) that only checks the shutdown ctx **between whole
   passes** (L653–657), never mid-pass, and writes through a byte-threshold
   **batch flusher** (`NewBatchWithFlusher`, L111) that persists partial progress
   to disk mid-pass.
2. **Reference roots.** mirage produces almost entirely **empty blocks**
   (`num_txs=0` throughout the logs), so most versions store their root as a
   *reference* to an earlier version's unchanged state root. Pruning the owning
   version therefore has to **reformat/relocate that shared root** (nodedb
   `deleteVersion` L510–525) — a non-atomic multi-write that touches a *different*
   version's key. A crash between those writes orphans exactly one version's
   rootkey while its neighbors (which own independent roots) survive → an
   **isolated hole**, not a contiguous prefix.
3. **Nothing drains the pruner on shutdown.** `nodeDB.Close()` cancels the ctx and
   waits `<-ndb.done` (nodedb L1265–1270) — but **`rootmulti.Store` has no
   `Close()` method at all**, so it is never called. `BaseApp.Close()` closes the
   raw `app.db` (PebbleDB) directly and the process exits while the prune goroutine
   may still be mid-pass. The DB is yanked out from under it → the in-flight
   reference-root reformat is left half-applied (this is also a second source of
   `pebble: closed`, independent of the double-close in item 13).
4. **`firstVersion` is never persisted.** `resetFirstVersion` (nodedb L891) sets
   only the in-memory field; on restart `getFirstVersion` (L847) **binary-searches
   `hasVersion` assuming contiguity**, so it silently mislocates the floor and
   cannot detect or repair a hole. The node runs happily until a later prune pass
   climbs up to the orphaned version and (post-v1.28.2) the guard halts.

**Why weekly, why mirage.talk:** every node bounces on its weekly OS-upgrade
docker restart (item 14), and until v1.29.x every shutdown exited via the
`pebble: closed` panic (item 13) — an abrupt exit that maximised the odds of
catching the pruner mid-pass. mirage.talk also carries the local query/tx load,
so it prunes/reads the most.

**Consequence, pre- vs post-guard:** pre-v1.28.2 upstream IAVL *silently skipped*
the missing version and kept serving reads off inconsistent state — the plausible
seed of the original app-hash divergences. Post-guard it is a loud, recoverable
halt: both events auto-recovered via peer-pull and **no app-hash divergence or
supply break accompanied either** (7-day scan). The guard + watchdog are
containing it exactly as designed; this is now a reliability/noise issue, not a
consensus-safety one.

**Fix SHIPPED — synchronous pruning (option A), 2026-07-08:** `newApp`
(`blockchain/cmd/miraged/cmd/commands.go`) now appends
`baseapp.SetIAVLSyncPruning(true)` after `DefaultBaseappOptions` (overriding the
default-async `iavl-sync-pruning` flag). With async pruning off, the background
prune goroutine is **never started** (`nodedb.go` L124 gates `go startPruning()`
on `opts.AsyncPruning`) and `DeleteVersionsTo` runs **inline inside `Commit`**, in
the consensus loop — which CometBFT stops *before* `app.Close()`/`app.db.Close()`.
So no prune can ever be in flight at shutdown, the DB can't be closed under a
running pass, and the non-atomic reference-root reformat can't be interrupted → no
new holes. Cost: a little inline latency on prune-interval blocks, bounded by
`keep-recent`. The fail-fast guard is **kept** as a safety net (and to drain any
pre-existing latent hole into one last recoverable halt). Combined with the
idempotent `app.Close` (item 13), both crash sources — the `pebble: closed`
shutdown panic and the `PRUNE_HOLE` halt — are addressed at the root.

Considered but not needed given (A): **(B)** a real `rootmulti.Store.Close()` that
drains each nodeDB before `app.db.Close()`; **(C)** persisting `firstVersion` so
restart doesn't rely on the contiguity-assuming binary search. Both remain valid
defence-in-depth / upstream candidates but are unnecessary once the goroutine is
gone.

**To definitively prove the interleaving:** the Jul 5 diverged DB is preserved
(`20260705T200500Z-h5846523/application.db`). A read-only `analyze-db` / rootkey
probe on it can confirm the hole is exactly `{5841942}` and that `5841942` was a
reference-root (empty-block) version. Not yet done.

### 0.3.2 SUPERSEDED by the 2026-07-12 chain halt — the real mechanism (2026-07-13)

**The §0.3.1 diagnosis was wrong (or at most a secondary path): synchronous
pruning did NOT stop the holes.** On 2026-07-12 both pruning validators
(mirage.talk and mirage.vote) hit `PRUNE_HOLE` within 9 minutes under v1.29.3
sync pruning — the panic stacks run inline through `rootmulti.Commit →
PruneStores → deleteVersionsTo` on the consensus goroutine, and the missing
versions were created after the 07-08 deploy with no restart in between.
CometBFT's `receiveRoutine` recovers the panic by killing the consensus reactor
while leaving RPC/p2p alive (a "consensus zombie"), so with 2 of 4 validators
zombied the chain lost quorum and halted ~3h47m at h6019400.

**Actual root cause (pinned with a deterministic repro):** the fail-fast guard
itself, interacting with the `BatchWithFlusher`. The reference-root reformat in
`deleteVersion` stages `Delete((v,1))` then `Set((v,0))` on the shared
auto-flushing batch; a size-threshold flush landing between the pair leaves the
disk transiently inconsistent (referenced root gone, replacement pending), and
`GetRoot` reads the DB directly — it can never see pending batch writes. The
guard probed the next referencing version, saw a phantom
`ErrVersionDoesNotExist`, and panicked — **and the panic dropped the pending
batch, converting the self-healing transient window into a real persistent
hole** that later passes crashed on. Under-load reader aborts made passes huge
(13k versions), maximizing mid-pass flushes. The pre-v1.29.3 "async shutdown"
holes were most likely the same split persisted by a shutdown mid-pass.

**Fix (2026-07-13, `blockchain/patches/iavl/nodedb.go`, two independent
layers):** (a) reformat order swapped to Set-then-Delete so every intermediate
flush state stays resolvable; (b) the guard flushes the batch and re-probes
from disk before panicking — transient misses heal, staged writes are never
destroyed, and only a still-missing version is a genuine hole (panic retained).
Regression test `TestDeleteVersionsToSurvivesReformatFlushSplit` forces the
flush boundary onto the reformat pair; it panics on the old code and passes on
the fix. The split window itself is an upstream IAVL bug (silent phantom reads
+ crash-persisted holes there); upstream issue/PR candidate.

**Interim fleet state (set during the 07-12 recovery): `pruning = "nothing"` on
ALL FOUR validators** — holes can't form and dormant ones are never touched,
but `application.db` grows unbounded. After this fix ships, restore
`pruning = "custom"`; on talk+vote first heal the real holes left by the 07-12
dropped batches (peer-pull from never-pruned n146/n139, or accept one
guard-triggered auto-recovery each).

### 0.3.3 v1.29.4 deployed; lockstep-stall from sync pruning → revert to async (2026-07-13)

v1.29.4 (the §0.3.2 hole fix) rolled out fleet-wide 2026-07-13 ~01:45–02:00 UTC.
The container restarts during deploy re-rendered `app.toml` from the template, so
`pruning = "custom"` came back on automatically (the interim `"nothing"` is gone;
disk is bounded again). No `PRUNE_HOLE`, no crash, no divergence since.

**But a new symptom appeared: a ~6-minute FULL-CHAIN stall at h6033700
(~14:04–14:09 UTC).** All four validators sat at the same height and resumed
together; no crash, no restart (`RestartCount=0`, 14h+ miraged uptime), consensus
pinned at round 0 the whole time (blocked in-process, not failing to agree). Cause:
**synchronous pruning** (the v1.29.3 `SetIAVLSyncPruning(true)` override). 6033700
is a multiple of `pruning-interval=100`, so every validator ran the same prune
pass inline in `Commit` at the same height; that pass was a large backlog drain
(talk's post-peer-pull base was ~6016143, ~16k versions behind), so `Commit`
blocked on ALL nodes at once → chain paused until the drain finished. Backlog now
drained; did not recur.

**Fix SHIPPED (v1.29.5): revert to ASYNCHRONOUS pruning.** `newApp`
(`blockchain/cmd/miraged/cmd/commands.go`) now sets
`baseapp.SetIAVLSyncPruning(false)` explicitly. Sync pruning was only ever added
to dodge the (wrong) shutdown-race theory; with the real hole cause fixed in
v1.29.4, async is safe again (an interrupted async pass at worst leaves both
reformat keys briefly present — never a hole — and the prune guard flush+re-probe
backstops it) and it decouples pruning from consensus: a slow pass makes one node
briefly lag and catch up instead of halting the whole chain in lockstep. The
fail-fast guard and idempotent `app.Close` remain.

### 0.3.4 Disk composition — pruning is DONE; the disk is logs (2026-07-28)

**Read this before "fixing" disk usage by pruning harder. It will not help.**
Measured on mirage.talk (the busiest node, 24 G volume, 15 G used / 65 %):

| What | Size | Bounded by |
|---|---|---|
| `/var/lib/docker` | 3.7 G | 1 image, `docker system df` = 0 B reclaimable |
| `/root/.mirage/logs` | 1.9 G | `LOG_RETENTION_DAYS` (was 30 → now 14) |
| Postgres (app data) | 1.4 G | nothing — real product data, grows with usage |
| **All chain data** | **975 M** | config, see below |
| `/var/log/journal` | 806 M | **was uncapped** → journald's 10 %-of-disk default (2.4 G) |

Chain data breakdown: `blockstore.db` 446 M, `cs.wal` 276 M, `state.db` 198 M,
**`application.db` 40 M**. That last number is the point — it was **1.84 GB**
before the commit-info pruning patch (item 12). Every prunable thing is now at
exactly its configured limit: the blockstore retained 6206151→6407751 =
**precisely 201,600 blocks**, matching `min-retain-blocks` to the block. So the
entire chain state is ~4 % of the disk and `application.db` is 0.17 %; pruning
more aggressively would reclaim single-digit MB.

**A disk-triggered auto-prune would also be actively harmful**: bulk IAVL delete
passes are the machinery behind the prune-hole crashes (§0.3.2) and the lockstep
stall (§0.3.3), and PebbleDB needs free headroom to compact, so mass deletes can
*raise* usage before reclaiming it. Firing that at 90 % full is the worst moment
to do it. Hence the watchdog's disk check is **alert-only** by design.

**Changes shipped (v1.29.9):** journald capped at 200 M via a deploy-managed
drop-in (`deploy/cap_journald.sh`, `/etc/systemd/journald.conf.d/99-mirage.conf`,
vacuumed on install); `LOG_RETENTION_DAYS` 30 → 14 (template + migration
`v1_29_9_log_retention_14d.py`, since the env sync preserves existing values, so
a template bump alone never reaches a live node); and a disk-pressure warning in
`divergence_watchdog.py` at `DISK_ALERT_PCT=80` that logs loudly and pages
`ALERT_WEBHOOK_URL`, deduped on its **own** marker (`.disk_alert_lock` — never
`ALERT_LOCK` or `LOCK`, per the 2026-06-12 shared-lock lesson) and never taking
action. Tests: `scripts/tests/test_watchdog_disk_alert.py`.

**If a disk warning fires**, triage with
`du -sh /root/.mirage/* /var/lib/docker /var/log | sort -rh`. Expect logs and
journald. If Postgres is genuinely the driver, that is real product data and the
answer is a bigger volume, not pruning.

**Verifying a no-Go release:** v1.29.9 touched only Python/bash/config, so
`deploy.sh`'s mtime staleness check correctly skipped the Go rebuild and
`miraged version` still reports **v1.29.8** on the fleet. That is accurate — it
names the binary you are running, which genuinely did not change — but it means
`miraged version` is NOT the deploy signal for releases like this. Verify with
the artifacts the release actually ships: `grep log-retention-14d
/root/.mirage/env/.migrations`, `grep ^LOG_RETENTION_DAYS
/root/.mirage/env/node.env` (expect 14), `cat
/etc/systemd/journald.conf.d/99-mirage.conf`, and `disk_alert_pct=80` in the
watchdog STARTUP line.

---

## 1. WHAT TO CHECK FIRST (read-only, ~3 minutes)

Run these from your workstation, in order. Each step splits the problem space
in half.

### 1a. Is it the frontend, the API, or the chain?

```bash
curl -so /dev/null -w "frontend %{http_code}\n" https://mirage.talk/
curl -s https://mirage.talk/api/get_network_stats | head -c 120; echo
```

- Frontend 200 + API `{"error":"node is catching up","error_code":"node_catching_up"}`
  → backend is alive but `is_node_catching_up()` (`web/backend/chain.py`) is
  tripping. That check reads `indexer_state` in the indexer DB. Continue to 1b.
- Frontend down too → infra problem (Caddy/Cloudflare/host), different runbook.

### 1b. Cluster triage — who is stuck?

```bash
source ./.env   # MIRAGE_FLEET_HOSTS — gitignored, see .env.example
for ip in $(echo "$MIRAGE_FLEET_HOSTS" | tr , " "); do
  curl -sfm5 "http://$ip:26657/status" \
    | jq -r "\"$ip h=\(.result.sync_info.latest_block_height) \
catching_up=\(.result.sync_info.catching_up) \
app=\(.result.sync_info.latest_app_hash[0:12])\""
done
```

Three outcomes:

| Pattern | Meaning | Action |
|---|---|---|
| One node's height frozen, others advancing | **Divergence OR stuck consensus** (this runbook) | → §1c to classify, then §2A/§2B |
| All four frozen at the same height | **Chain halt** (upgrade halt? 2+ nodes down?) | → `incident-recovery.md` §0; check miraged logs for `UPGRADE "..." NEEDED` |
| All four advancing, API still 503 | **Indexer-only problem** | → §4 (indexer restart) |

> Trap from 2026-06-12: a stuck local node *also* makes the local
> `chain_head_height` in `indexer_state` go stale, so the backend's error is
> the same in all three cases. Always run the 4-node triage loop — do not
> diagnose from the API error alone.

### 1c. Stuck consensus vs state divergence vs crash

```bash
ssh root@<sick-host> 'docker exec mirage curl -s http://127.0.0.1:26657/status' \
  | jq '.result.sync_info | {latest_block_height, latest_block_time, catching_up}'
```

- Process up, height frozen, `catching_up: false`. Now decide WHICH class by
  comparing the app_hash AT the stuck height against a healthy peer:

```bash
SICK=<val1>; PEER=<val3>
H=$(curl -sfm5 http://$SICK:26657/status | jq -r .result.sync_info.latest_block_height)
for ip in $SICK $PEER; do
  curl -sfm5 "http://$ip:26657/block?height=$H" \
    | jq -r "\"$ip app=\(.result.block.header.app_hash)\""
done
```

  - **app_hash MATCHES the peer** → this is a **stuck consensus / runtime hang**
    (the 2026-06-14 case: frozen at h=5329009 step=3 prevote, app_hash identical
    to peers). Local state is correct. Cure is a **restart** (§2A), not a wipe.
  - **app_hash DIFFERS**, or the log shows `wrong Block.Header.AppHash` →
    **state divergence**, go to peer-pull (§2B):

```bash
ssh root@<sick-host> 'docker exec mirage grep -a "wrong Block.Header.AppHash" \
  /root/.mirage/logs/node/miraged-$(date -u +%F).log | head -5'
```

- Process dead → crash; the watchdog/`recover.sh restart` handles it even if
  peers are unreachable, because restart is non-destructive. It escalates to
  peer-pull only if the restart can't bring the chain forward, and peer-pull's
  own peer-health checks still have to pass.

### 1d. Check what the watchdog saw

Two logs. The tmux-pane capture (human view):

```bash
ssh root@<sick-host> 'docker exec mirage tail -40 \
  /root/.mirage/logs/deploy/divergence_watchdog-$(date -u +%F).log'
```

And the **dense forensic log** (durable, 90-day retention, one or more tagged
lines per poll — this is the "what happened at 3am four months ago" source):

```bash
ssh root@<sick-host> "docker exec mirage sh -c '
  F=/root/.mirage/logs/watchdog/watchdog-\$(date -u +%F).log
  echo \"== last poll ==\";    grep \"\\[POLL\\]\"     \"\$F\" | tail -3
  echo \"== events ==\";       grep -E \"\\[(TRIGGER|PRECHECK|DISPATCH|INVOKE|POSTCHECK|ESCALATE|ALERT|LAG|IO|CRASH)\\]\" \"\$F\" | tail -30'"
```

Key fields to read: `[POLL] last_advance_age_s=` (how long stuck), `[PRECHECK]
match=true|false` (the app_hash decision), `[DISPATCH] action=restart|peer-pull`
(what it chose and why). If the watchdog already restarted and recovered, you may
be done — verify with §5. If `WATCHDOG_AUTORECOVER` is not `true` and the class
is divergence, peer-pull was not run; proceed manually (§2B).

### 1e. Behind the network but NOT stuck (`[LAG]` / `[IO]`)

There is a failure mode that none of §1c's classes cover and that every trigger
above is blind to, because they all require a **frozen** height: the node keeps
committing blocks, just slower than the network. On **2026-08-06** mirage.talk ran
~21 blocks (~75 s) behind for five minutes with `catching_up=false`. The chain
rejected every relayed write (`envelope_timestamp in future`, because the ante
handler compares against *our* stale block time), the backend returned 500s on
`POST /api/core/post`, and users saw failed posts — while nothing alerted and no
class in §1c applied. The cause was the droplet's volume degrading: 33 → 13 IOPS
while average service time went 12 ms → **281 ms**. Our own I/O *fell*; the device
got slow. It self-healed in ~13 minutes.

The watchdog now names both halves, alert-only:

```bash
ssh root@<host> "docker exec mirage sh -c '
  F=/root/.mirage/logs/watchdog/watchdog-\$(date -u +%F).log
  grep -E \"\\[(LAG|IO)\\]\" \"\$F\" | tail -20
  grep \"\\[POLL\\]\" \"\$F\" | tail -5   # io_await_ms= / io_busy_pct= every poll'"
```

`[LAG]` = behind healthy peers by `LAG_ALERT_BLOCKS` (10) for `LAG_ALERT_POLLS`
(3) polls while still advancing. `[IO]` = host disk `await` above
`IO_AWAIT_ALERT_MS` (100 ms; val1 normally sits at 3-4 ms).

**Do not recover.** A slow node re-converges by itself, and every recovery action
writes more to the disk that is already the bottleneck — a restart replays the WAL
and can turn a five-minute lag into a real outage. Triage the host instead with
`iostat -x 5`: latency up **with** IOPS up is our own workload (compaction,
snapshot, vacuum); latency up with IOPS flat or falling is the volume degrading,
which is a provider issue and not fixable from inside the box. Historical detail
lives in the sysstat and PCP archives (`sar -d -f /var/log/sysstat/sa$(date +%d)`),
which is how the 2026-08-06 numbers above were reconstructed after the fact.

Tests: `scripts/tests/test_watchdog_lag_io_alert.py`.

---

## 2A. RECOVERY — stuck consensus / runtime hang (NON-destructive)

When §1c showed the app_hash MATCHES peers, the chain DB is fine; the process is
just wedged. This is what the watchdog now does automatically on every host. To
do it by hand:

```bash
ssh root@<sick-host> 'docker exec mirage bash /opt/mirage/scripts/recover.sh restart --dry-run'
# Then:
ssh root@<sick-host> 'docker exec mirage bash /opt/mirage/scripts/recover.sh restart --auto'
```

This stops and relaunches miraged via the supervisor, touches NOTHING else (no
DB wipe, no `priv_validator_state.json` change, no service pause), and verifies
the chain advances past the pre-stop height. Exit 5 means it restarted but the
chain did not move — that reclassifies the incident as divergence; go to §2B.
Then verify with §5. The indexer keeps running (no wipe), so §4 is usually NOT
needed for a restart-only recovery — but check the gap in §5 anyway.

---

## 2B. RECOVERY — state divergence, automated path (try this first)

All commands run on the sick host. Total time ≈ 15 min for ~2 GB of chain data.

### 2a. Pre-flight

```bash
# Cool-down lock: if it exists and is EMPTY, it was written by the (pre-fix)
# watchdog alert path, not by a real recovery — safe to delete. A real
# recovery writes a UTC timestamp into it.
ssh root@<sick-host> 'docker exec mirage sh -c \
  "ls -la /root/.mirage/.divergence_recovery_lock 2>/dev/null; cat /root/.mirage/.divergence_recovery_lock 2>/dev/null"'

# Recovery key present? peer-pull --auto needs it.
ssh root@<sick-host> 'docker exec mirage ls -la /root/.mirage/.ssh/recovery_id'
```

### 2b. Dry-run, then recover

```bash
ssh root@<sick-host> 'docker exec mirage bash /opt/mirage/scripts/recover.sh peer-pull --dry-run --force'
# Expect: >=2 healthy peers, "peers agree on app_hash @ H", a selected source
# peer, and NO note about a missing recovery_id. Then:
ssh root@<sick-host> 'docker exec mirage bash /opt/mirage/scripts/recover.sh peer-pull --auto --force'
```

`--force` bypasses the 6 h cool-down; justified whenever you have verified the
node is genuinely diverged and no recovery is mid-flight. The script preserves
`priv_validator_state.json` (double-sign watermark), wipes only chain DBs,
pulls a tar from the best peer, restarts miraged and the tmux services
(including the indexer), and writes the cool-down lock only after verifying
block progress.

Then go to §5 (verify). If the dry-run flagged a missing `recovery_id`, use §3.

---

## 3. RECOVERY — manual fallback (no recovery key provisioned)

This is what was done on 2026-06-12. It is the same algorithm as
`recover.sh peer-pull`, driven by hand from the workstation. SOURCE = any
healthy peer from the §1b triage; SICK = the diverged host.

```bash
SOURCE=<val3>
SICK=<val1>

# 1. Stream chain DBs from SOURCE to SICK host (~2 min for ~1 GB compressed).
#    SIGSTOP keeps the source's supervisor from restarting miraged mid-tar;
#    the trap guarantees SIGCONT even if the SSH dies.
ssh root@$SOURCE '
  trap "docker exec mirage pkill -CONT -f \"miraged start\" 2>/dev/null || true" EXIT INT TERM
  docker exec mirage pkill -STOP -f "miraged start"; sleep 1
  tar --ignore-failed-read --exclude=priv_validator_state.json -czf - \
    -C /root/.mirage/node/data \
    application.db blockstore.db cs.wal evidence.db snapshots state.db tx_index.db
' | ssh root@$SICK 'cat > /root/snap.tar.gz'

# 2. Verify the source resumed (height advancing again):
ssh root@$SOURCE 'docker exec mirage curl -s http://127.0.0.1:26657/status' \
  | jq -r .result.sync_info.latest_block_height

# 3. On SICK: stop miraged, back up, swap in the new DBs, restart.
ssh root@$SICK 'docker cp /root/snap.tar.gz mirage:/tmp/snap.tar.gz && rm /root/snap.tar.gz'
ssh root@$SICK 'docker exec mirage bash -s' <<'EOS'
set -euo pipefail
tmux send-keys -t mirage:node C-c
for i in 1 2 3 4 5 6; do
  pgrep -f "miraged start" >/dev/null || break; sleep 5
done
pgrep -f "miraged start" >/dev/null && { echo "miraged refused to stop"; exit 1; }
cp /root/.mirage/node/data/priv_validator_state.json /root/.mirage/priv_validator_state.json.preheal
BACKUP=/root/.mirage/data.preheal-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP"
cd /root/.mirage/node/data
for d in application.db blockstore.db cs.wal evidence.db snapshots state.db tx_index.db; do
  if [ -e "$d" ]; then mv "$d" "$BACKUP/"; fi
done
tar xzf /tmp/snap.tar.gz -C /root/.mirage/node/data
echo "old DBs in $BACKUP; priv_validator_state.json untouched:"
cat /root/.mirage/node/data/priv_validator_state.json
tmux send-keys -t mirage:node "bash /opt/mirage/deploy/run_miraged_supervised.sh" Enter
EOS
```

**Never** copy `priv_validator_state.json` from the peer and **never** delete
the local one — it is the only thing standing between a recovery and a
double-sign tombstone.

Now do §4 (the manual path does not restart the indexer for you), then §5.

---

## 4. THE INDEXER TRAP — always restart the indexer after recovery

The indexer only runs its historical catch-up (`_catch_up()` in
`indexer/main.py`) **at startup**. If it stayed up through the outage, it will
happily tail new blocks over WebSocket — the indexed height advances 1 block
per ~3 s, in lockstep with the head, and **the gap never closes** (and any
blocks it indexed on the diverged fork are never rolled back). The symptom:
"the number just goes up every 3 seconds" while the API stays 503.

```bash
ssh root@<sick-host> 'docker exec mirage bash -c "
  tmux send-keys -t mirage:indexer C-c; sleep 5
  tmux send-keys -t mirage:indexer \"PYTHONPATH=/opt/mirage python3 /opt/mirage/indexer/main.py\" Enter"'
```

On restart the indexer detects its DB is past/off the chain's real history,
rolls back to the divergence point, and replays forward at ~4 blocks/s
(~8 min per 2000 blocks). Watch the gap close:

Read the height from `meta.last_height` — since v1.33.0 that is the only height
authority, written in the same transaction as the block it describes. Do **not**
use `indexer_state.last_processed_height`: nothing has written it since that
change, so on a database predating v1.33.8 it sits frozen thousands of blocks
back and looks exactly like an indexer that has stopped.

```bash
ssh root@<sick-host> 'docker exec -u postgres mirage psql -d mirage_indexer -At -F" " -c \
  "SELECT (SELECT value FROM meta WHERE key='"'"'last_height'"'"') AS indexed,
          (SELECT value FROM indexer_state WHERE key='"'"'chain_head_height'"'"') AS head;"'
```

The API flips to 200 when the gap is ≤10 blocks and `last_processed_time` is
fresh (<30 s).

---

## 5. VERIFY

```bash
# 1. App hash agreement at one height across all four nodes:
H=$(curl -sfm5 http://<val3>:26657/status | jq -r .result.sync_info.latest_block_height)
source ./.env   # MIRAGE_FLEET_HOSTS — gitignored, see .env.example
for ip in $(echo "$MIRAGE_FLEET_HOSTS" | tr , " "); do
  curl -sfm5 "http://$ip:26657/block?height=$H" \
    | jq -r "\"$ip app=\(.result.block.header.app_hash[0:16])\""
done

# 2. The recovered validator is signing again (flag 2 = signed):
curl -sfm5 "http://<val3>:26657/block?height=$H" \
  | jq '.result.block.last_commit.signatures[] | .block_id_flag'

# 3. User-facing:
curl -so /dev/null -w "api %{http_code}\n" https://mirage.talk/api/get_network_stats

# 4. If the validator got jailed during the outage: incident-recovery.md §3.
```

Cleanup after a day of stable operation: the `data.preheal-*` backup dir and
`/tmp/snap.tar.gz` on the sick host. Keep
`priv_validator_state.json.preheal` until signing has clearly progressed past
the divergence height.

---

## 6. Known traps (all hit on 2026-06-12)

1. **Empty cool-down lock.** The pre-fix watchdog `touch`ed the *recovery*
   cool-down lock from its alert-only path, blocking operator recovery for 6 h
   after every detection. Fixed: alerts now use a separate
   `.divergence_alert_lock`. An empty `.divergence_recovery_lock` is always
   safe to delete; a real one contains a UTC timestamp.
2. **`recover.sh` exiting silently after the "healthy:" lines.** Was a
   `set -e` bug in `peer_pick_min_height` (a final false `[ ... ] && ...` test
   escaping as the function's return code). Fixed 2026-06-12. If you ever see
   recover.sh stop printing mid-flow with no `ERROR:`, suspect this bug class:
   a function whose last statement can return non-zero.
3. **Missing recovery key.** `peer-pull --auto` needs
   `/root/.mirage/.ssh/recovery_id`, installed by `recover.sh provision`. The
   watchdog now keeps restart-only recovery alive if this key is missing, but
   it logs `[ALERT] kind=destructive-autorecover-disabled` and will not run
   destructive peer-pull until the key exists. The dry-run also prints a note if
   it is missing — read the dry-run output. Manual fallback: §3.
4. **Indexer live-tail.** See §4. The catch-up gap does not close on its own.
5. **Wiping a healthy DB (2026-06-14).** A stuck consensus reactor looks just
   like a divergence at the API level (frozen height, 503), but the chain DB is
   correct — the app_hash at the stuck height matches peers. Reaching for
   `peer-pull` here needlessly wipes ~2 GB and risks the validator's signing
   watermark. Always run the §1c app_hash comparison first; if it matches, use
   `recover.sh restart` (§2A). The watchdog now makes this call automatically
   via its `[PRECHECK] match=` gate.
6. **Auto-recovery silently dead (2026-06-16).** Three defects meant peer-pull had
   never actually worked on prod: (a) `ssh`/`openssh-client` was missing from the
   container image, so in-container `peer-pull` died with `exit 127`; (b)
   `recover.sh serve` used `local paused`/`local container`, which the `EXIT`-trap
   resume cannot see under `set -u`, so SIGCONT never fired and the **source peer
   was left frozen**; (c) the watchdog skipped divergence checks whenever
   `catching_up=true`, but a diverged node reports exactly that. All three are
   fixed — see the [2026-06-16 postmortem](postmortems/2026-06-16-mirage-talk-divergence.md).
   If a peer-pull ever leaves a healthy peer stuck (`docker top` shows `Tl`/stopped),
   resume it immediately: `ssh root@<peer> 'docker exec mirage pkill -CONT -f "miraged start"'`.

---

## 7. Post-deploy smoke check (new restart path)

After rolling out the two-tier watchdog, confirm the new entry point and
supervisor handoff work on each validator without actually restarting anything:

```bash
source ./.env   # MIRAGE_FLEET_HOSTS — gitignored, see .env.example
for ip in $(echo "$MIRAGE_FLEET_HOSTS" | tr , " "); do
  echo "== $ip =="
  ssh root@$ip 'docker exec mirage bash /opt/mirage/scripts/recover.sh restart --dry-run'
done
```

Expect each to print the pre-stop height and the "DRY RUN — would: stop
miraged ... NO DB wipe ..." block, then exit 0. Also confirm the watchdog is
running and logging on every host:

```bash
source ./.env   # MIRAGE_FLEET_HOSTS — gitignored, see .env.example
for ip in $(echo "$MIRAGE_FLEET_HOSTS" | tr , " "); do
  ssh root@$ip 'docker exec mirage sh -c "tail -1 /root/.mirage/logs/watchdog/watchdog-$(date -u +%F).log"'
done
```
