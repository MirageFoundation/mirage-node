# Postmortem — 2026-06-16 mirage.talk AppHash divergence + dead auto-recovery

- **Date (UTC):** 2026-06-16
- **Service:** mirage.talk (prod app host + validator, `<val1>`)
- **Duration of user impact:** ~95 minutes (18:21:25 → ~19:56:41 UTC)
- **Severity:** High — all write actions (votes, posts, follows, comments, gifts) failed site-wide.
- **Author:** incident responder (Cursor agent session)
- **Status:** Recovered. Tooling fixes written; root-cause prevention still open (see Action Items).

---

## 1. Summary

At **18:21:25 UTC** the prod validator computed a different application state hash
than the rest of the network for block **5378002** and halted with a
`CONSENSUS FAILURE!!! wrong Block.Header.AppHash`. The node froze at height
5378001 reporting `catching_up=true`. Because the backend guards every write with
`is_node_catching_up()` (returns HTTP 503), every vote/post/follow on the site
failed; the frontend rendered the 503 as the generic `Transaction failed`. The
user-reported symptom was "Transaction failed when I upvote."

The chain itself was fine — the other three nodes stayed in consensus and kept
producing blocks. **Only prod diverged.**

Automatic recovery existed but **did nothing**, because of two latent bugs in the
recovery tooling and one blind spot in the watchdog detection logic (all three
detailed in §5). Recovery was ultimately performed manually via
`recover.sh peer-pull` after fixing the tooling bugs mid-incident. Prod was
restored on the canonical chain at 19:56:41 UTC; 24 on-chain writes were
confirmed flowing again by 20:08 UTC.

---

## 2. Impact

- **Users:** Could not vote, post, comment, follow, or send gifts for ~95 min.
  Reads (feed, comments, profiles, rewards summaries) continued to work, so the
  site looked "up but broken."
- **Chain:** No impact to the network. 3/4 validators healthy throughout; blocks
  kept advancing on the canonical chain.
- **Validator:** prod stopped signing for the outage window but was **not jailed**
  (stayed under the downtime slashing threshold). No double-sign, no tombstone.
- **Collateral:** the reward distributor's `bank send` failed during the window
  (`account number (0) ... unauthorized`) because account/state queries against
  the halted node returned stale/zero values.

---

## 3. Timeline (UTC)

| Time | Event |
|---|---|
| 18:21:25 | Prod commits its **last** block, height **5378001**. `latest_block_time` freezes here. |
| 18:21 | Height 5378002: `prevote nil` then `CONSENSUS FAILURE!!!` — `wrong Block.Header.AppHash. Expected C6ABD68C…, got 21C470FF…`. Prod is now diverged and stuck. |
| 18:22:30 | Watchdog → `recover.sh peer-pull` attempt #1 (source <val4>). **Fails instantly** — `ssh` is not installed in the container (`exit 127`), surfaced as "ssh peer-pull failed". |
| 18:37:46 | Watchdog → `recover.sh restart` (non-destructive). Chain does not advance past 5378001 (state is wrong, restart can't fix it) → exit 5. |
| 18:38:51 | Watchdog → `recover.sh peer-pull` attempt #2 (source <val2>). **Fails instantly** (same missing `ssh`). |
| 18:38:51 → 19:56 | Watchdog now reports `catching_up=true … note="catching_up; not a divergence"` every 60 s and **never acts again** (detection blind spot — a diverged node looks "catching up"). |
| ~18:49 | Reward distributor `bank send` fails (`account number (0)`), collateral of the halt. |
| 19:41–19:50 | User `vote.begin` log lines with **no completion** — all returning 503 `node_catching_up`. This is the user's "Transaction failed." |
| ~19:43 | Incident response begins. |
| 19:45 | Diagnosed: chain halted at 5378001, `catching_up=true`, AppHash mismatch vs peers (peers agree on canonical chain). Confirmed `ssh` missing in container; installed `openssh-client` live. Verified recovery key matches peer `authorized_keys`; `peer-pull --dry-run` clean. |
| 19:45:48 | `peer-pull --auto` connects for the first time, streams the tar — but `recover.sh serve` on the peer hits `paused: unbound variable`, skips SIGCONT, and exits non-zero → client aborts. **Source peer <val2> left frozen (SIGSTOP).** Manually resumed (`pkill -CONT`). |
| ~19:50 | Root-caused the serve bug; patched `recover.sh` (made `paused` global), deployed to all 3 peers. |
| 19:51:28 | `peer-pull --auto` retry. SIGCONT now runs but hits a **second** unbound var — `container` (also `local`, also referenced from the EXIT trap) — so the actual `docker exec … pkill -CONT` never runs. **Source peer frozen again.** Manually resumed. |
| ~19:53 | Patched `container` to global + fallback; redeployed to all 3 peers. |
| 19:54:21 | `peer-pull --auto` retry **succeeds**: 957 MB tar pulled from <val2>, `priv_validator_state.json` preserved, chain DBs replaced, miraged restarted. |
| 19:56:41 | Recovery verified: height 5379118 > trust height 5379104; cool-down lock written. Prod `catching_up=false`, app_hash matches network. |
| 20:07–20:08 | 24 successful on-chain broadcasts confirmed — writes fully restored. |

---

## 4. Root cause

### 4.1 Trigger (the divergence itself) — node-local read-consistency fault, unique to the validator that also serves local queries (NOT memory, NOT load)

prod diverged alone (all 3 peers had **0** AppHash errors that day), so this is
**not** a chain-wide non-determinism bug. One node computed a different app_hash
for the same block, executing block 5378001 → `C6ABD68C…` while the network
computed `21C470FF…` (prod was the outlier and was peer-pulled onto the canonical
chain). The committed on-disk state is correct; `miraged rollback` cannot fix it;
restore-from-peer can.

**The original "host memory pressure → IAVL cache corruption" hypothesis is
REFUTED by post-incident evidence (2026-06-16):**

- **All 4 hosts are provisioned identically** — `3915 MB` RAM, `2047 MB` swap,
  `vm.swappiness=10`. prod is **not** under-provisioned relative to peers.
- **All 4 run only the `mirage` container** at near-identical memory: ~705–741 MiB
  (~18 %), with ~2.6 GiB `MemAvailable` and swap virtually untouched
  (`SwapFree ≈ 2000/2047`) on every host. prod was **not** memory-starved.
- **Zero OOM-kills, host *and* container.** `journalctl -k | grep oom` = 0 on all
  four hosts. The `mirage` container has **no** memory limit (`docker inspect` →
  `Memory=0`; cgroup `memory.max=max`) and its cgroup OOM counter is
  `memory.events: oom_kill 0` — it has never hit a limit. (So "increase the
  container's RAM" is a no-op: there is no limit to raise, and nothing was killed.)
- **The "168 MiB free" figure in the first draft was a misread of `free`.** On
  Linux the `free` column is always low because the kernel uses spare RAM for
  reclaimable `buff/cache`; the number that matters is `available`. Live `free -m`
  on prod: `free 197 / buff/cache 2810 / available 2574` — i.e. **~2.5 GiB
  genuinely free**, matching the host monitoring's flat **~45 % memory** all day.
- **No hardware memory errors.** The only `EDAC` line is the benign boot banner
  `EDAC MC: Ver: 3.0.0` (present identically on all hosts); no MCE/correctable/
  uncorrectable errors.
- **prod's miraged ran ~18 h continuously** (00:01 → 18:21) before diverging, so
  this was **not** a cold-cache-after-restart event.
- **It was not even under load at the time.** Host metrics at the divergence
  (~14:21 EDT / 18:21 UTC) show **CPU 17.5 %, load 0.71/0.74/0.81, memory 45.5 %** —
  the box was idle. (The later CPU spike to ~85 % / load ~3.8 at ~16:00 EDT was the
  recovery peer-pull + redeploys, *not* the incident.) So this is **not** a
  resource-exhaustion or high-load event at all.

**What it actually is — the documented read-consistency class, minus the fast-node
vector.** The repo's own IAVL patch
([`blockchain/patches/iavl/immutable_tree.go`](../../../blockchain/patches/iavl/immutable_tree.go))
records the mechanism for the prior prod divergences (2026-05-25 h4854225,
2026-06-12 h5280036): *under concurrent query load the fast-node index can return
a value one commit stale relative to the canonical tree while the version check
still passes.* That specific vector is now **disabled** — prod runs with
`iavl-disable-fastnode = true` (verified live), and the fork goes further: the
fast-node read block was *removed* from `MutableTree.Get` — it delegates straight
to the canonical `ImmutableTree.Get`, which never consults the index — so reads
are fast-node-free regardless of the toggle. So 2026-06-16 is a
**residual instance of the same class** (a node-local read returning a value
inconsistent with committed state), reached through a *different* surface than
fast-node.

The discriminator is **not** load level — the box was idle when it diverged. It is
that prod is the **only** node running local workloads that hit its own ABCI/app
state concurrently with consensus block execution: the **indexer** (gRPC/RPC
polling), the **backend** (`simulate` gas-estimation, which executes txs against a
query context), and the **reward distributor** (broadcasts). The peers run none of
these. A single concurrent query interleaving with block execution at the wrong
instant is enough to read through a shared/stale view — which is probabilistic per
concurrent access, so it fires even at low CPU and only on prod. The leading
candidate surfaces:

1. **Error-swallowing store fallbacks** in the consensus path that turn an
   intermittent `store.Get` error into a *silently different* state transition
   rather than a fail-fast halt — e.g. `Keeper.HasEnvelopeNonce` returns `false`
   on a `Get` error (→ could accept a replay one peer rejects), and the PoW
   difficulty getters (`GetCurrentDifficulty`, `GetPoWMessageCount`, …) return
   their default on a `Get` error (→ wrong PoW accept/reject threshold). None of
   these log on the error branch — **consistent with 2026-06-16 leaving no
   app-level marker** (`record_fail=0 renewal_fail=0 supply=0 fatal=0`, vs the
   2026-06-12/06-14 events which *did* log supply-invariant violations).
2. **Residual store/cache read staleness** below the app (PebbleDB block cache /
   IAVL node cache) exercised by the local query/tx workloads only prod runs
   against its own node (indexer, backend `simulate`, reward distributor) — present
   even when the box is idle, which the peers simply don't have.

> Confidence: HIGH that it is **not** memory/OOM/hardware **and not load/CPU**
> (hard evidence above — it diverged while the box was idle). HIGH that it is a
> node-local, concurrency-exposed, *silent* read-consistency fault of the same
> family as the documented IAVL divergences. The exact remaining
> surface (error-swallowing fallback vs sub-IAVL cache) is **not yet pinned to a
> line** for this specific height — that requires replaying 5378001 against a
> peer's state (see Action Items 9–11). The prior `data.preheal-*` backup from
> recovery is the artifact to replay against.

Recurrence history (prod-only): 2026-05-25, 2026-06-12, 2026-06-14 (stall),
2026-06-16 — cadence tightening as prod traffic grows, which fits a
**concurrency-driven** (not memory-driven) trigger.

### 4.2 Why automatic recovery did nothing (the part we *can* fix today)

Three independent defects meant the watchdog/`recover.sh` recovery path had
**never actually worked** on this host:

1. **`ssh` was missing from the container image.** `recover.sh peer-pull` runs
   inside the container and shells out to `ssh`. The runtime image
   (`deploy/Dockerfile`) never installed `openssh-client`, so every peer-pull
   died immediately with `exit 127`. Auto-recovery was dead on arrival.

2. **`recover.sh serve` skipped SIGCONT (left the source peer frozen).** `serve`
   pauses the source peer's miraged with `SIGSTOP`, streams a tar, and is supposed
   to `SIGCONT` it from an `EXIT` trap. But the trap runs *after* `cmd_serve`
   returns (`main → cmd_serve → return → script EOF → EXIT trap`), at which point
   the `local paused` and `local container` variables are out of scope. Under
   `set -u` the trap died with `unbound variable` **before** sending SIGCONT —
   leaving the healthy source peer frozen and making `serve` exit non-zero, which
   aborted the client pull. This bug froze <val2> twice during this
   incident (each time manually resumed). It affected the version of `recover.sh`
   in the repo, i.e. it would have failed every real peer-pull.

3. **The watchdog is blind to divergence while `catching_up=true`.** A diverged
   node reports `catching_up=true` (it is "trying to catch up" but can never apply
   the next block). The watchdog's poll loop short-circuited on `catching_up` with
   `note="catching_up; not a divergence"` and never ran its divergence checks, so
   after the two (failed) initial attempts it sat idle for the rest of the outage.

---

## 5. Detection

- **What detected it:** a human, via the user report ("Transaction failed on
  upvote"). The watchdog *logged* the AppHash failure and even attempted recovery
  twice, but its attempts failed silently and it then mislabeled the ongoing
  divergence as benign catch-up.
- **What should have detected it:** the watchdog, automatically, within ~10 min —
  and it now will (§6.3).
- **Gap:** no external alert fired. The watchdog's loud-alert path requires the
  detection logic to fire, which it didn't (blind spot #3).

---

## 6. Fixes (this incident)

All three tooling defects are fixed in the repo. The trigger (a node-local
read-consistency fault from local query traffic racing block execution — see §4.1;
**not** memory and **not** load) is **not** fixed — see Action Items.

### 6.1 `deploy/Dockerfile` — install `openssh-client`
Added `openssh-client` to the runtime package list so the in-container
`peer-pull` can SSH to peers. (Installed live in the running prod container during
the incident; the Dockerfile change makes it permanent on the next image build.)

### 6.2 `scripts/recover.sh` — make `serve` resume reliable
`paused` and `container` are now module-level globals (not `local`) so the
`EXIT`-trap resume can always reach them, and the resume uses `${container:-mirage}`
as a defensive fallback. Verified end-to-end: the successful 19:54 pull logged
`resuming miraged (SIGCONT)` and exited 0, and the source peer stayed healthy.

### 6.3 `scripts/divergence_watchdog.py` — detect divergence behind `catching_up`
New pure helper `is_catchup_divergence(...)`: when `catching_up=true` **and** the
local height has been frozen ≥ `CATCHUP_STALL_SECONDS` (default = `STALL_BLOCKS *
POLL_SECONDS` = 10 min) **and** the node log shows an AppHash/consensus-failure
line in the detection window **and** ≥2 healthy peers are ahead, the watchdog
fires `TRIGGER_LOG_PATTERN` → `peer-pull` (still gated by `WATCHDOG_AUTORECOVER`).
A genuine block-sync advances, so its height is never frozen this long — that is
the discriminator. Unit tests added in
`scripts/tests/test_watchdog_dispatch.py` (23/23 pass).

---

## 7. What went well / poorly

**Well**
- The chain stayed up; 3/4 consensus held; no double-sign, no jail.
- `priv_validator_state.json` was preserved throughout (no double-sign risk).
- The forensic logs (`divergence_recovery-*.log`, `divergence_watchdog-*.log`,
  miraged logs) made the timeline fully reconstructable.

**Poorly**
- Auto-recovery had never actually worked on prod (missing `ssh`), and nobody
  knew because it failed silently and was never end-to-end tested in prod.
- The serve bug actively *harmed* a healthy peer (froze it) during recovery.
- Detection mislabeled an active divergence as benign for >1 hour.
- The underlying divergence is recurring and still unaddressed.

---

## 8. Action items

| # | Action | Type | Status |
|---|---|---|---|
| 1 | Add `openssh-client` to runtime image | Fix | **Done** (released v1.27.3, deployed fleet-wide) |
| 2 | Fix `recover.sh serve` SIGCONT (globals) | Fix | **Done** (released v1.27.3, deployed fleet-wide) |
| 3 | Watchdog detects divergence while `catching_up=true` | Fix | **Done** (released v1.27.3, deployed fleet-wide) |
| 4 | Rebuild image + redeploy fleet so 1–3 are permanent/live | Deploy | **Done** — v1.27.3 (`d7b9642`) rolled peers-first then prod; all 4 verified `ssh`/recover/watchdog + auto-recovery armed |
| 5 | ~~Relieve prod memory pressure~~ **REVISED (see §4.1): the trigger is NOT memory and NOT load** (it diverged while the box was idle — CPU 17.5 %, mem 45 %). **Isolate the validator from all local query/tx traffic**: point the indexer, backend (`simulate`), and reward distributor at a **separate non-validating full node**, so nothing reads the validator's ABCI/app state concurrently with block execution. Adding RAM does nothing (no limit set, `oom_kill 0`). | Prevention | **Open (highest value)** |
| 6 | Add an external alert (independent of the watchdog) for "any node `catching_up=true` and height frozen > N min" so a future silent failure pages a human | Detection | **Done (2026-06-22)** — `scripts/stuck_node_alert.py`: a standalone, stdlib-only liveness pager that imports nothing from the watchdog and runs in its **own** tmux window (separate failure domain — survives a `kill -STOP`'d/crashed watchdog). Pages `ALERT_WEBHOOK_URL` when the local height is frozen, or `/status` is unreachable, for `STUCK_ALERT_SECONDS` (default 600) — **regardless of any divergence log marker**, which is exactly the silent-freeze signature here. Re-pages every `STUCK_ALERT_REPEAT_SECONDS` and sends a one-time "RECOVERED" when it advances again. Detection only (never recovers). Wired into `deploy/entrypoint.sh` (starts only when `ALERT_WEBHOOK_URL` is set) and documented in `node.env`. Smoke-tested: frozen→page, advancing→silent, re-page dedup, recovery transition. |
| 7 | Periodically smoke-test auto-recovery end-to-end in prod (`peer-pull --dry-run` is not enough — the `ssh`/serve path must be exercised) | Process | **Open** |
| 8 | **Fail-fast the silent fallbacks**: make consensus-path `store.Get` error branches `panic`/halt instead of returning a default (`HasEnvelopeNonce`→`false`, `GetCurrentDifficulty`/`GetPoWMessageCount`→default). A deterministic halt is recoverable by the (now-fixed) watchdog; a silent wrong value is not. | Hardening | **Done (2026-06-22)** — extended the fail-fast contract to the whole consensus-path read family in `x/core/keeper/keeper.go`: `HasEnvelopeNonce`, `RecordPoWMessage` (read-before-increment), `GetPoWMessageCount`, `GetCurrentDifficulty`, `HasCurrentDifficulty`, `GetPreviousDifficulty`, `GetLastDifficultyChangeHeight`, `GetConsecutiveLowUsage`. Each now panics `CONSENSUS_FATAL:*_STORE_GET` on a raw `store.Get` **error** (absent-key → default behavior unchanged). The stale "`GetPoWMessageCount` is non-consensus-critical" note in `never_halt_test.go` was corrected (its window sum feeds `SetCurrentDifficulty`). Pinned by `TestConsensusReadsPanicOnStoreGetFailure` + `TestConsensusReadsReturnDefaultsOnAbsentKey`. |
| 9 | **Defense-in-depth**: drop the fast-node read block from `MutableTree.Get` entirely (mirror the `ImmutableTree.Get` patch) so no read path can ever consult the advisory index, regardless of the `iavl-disable-fastnode` toggle. | Hardening | **Done — already satisfied in the fork.** `MutableTree.Get` (`blockchain/patches/iavl/mutable_tree.go`) does not gate a fast-node block on the toggle; it was *removed* — `Get` delegates straight to the canonical `tree.ImmutableTree.Get(key)`, which also never consults fast-node. (Supersedes the "gated off" phrasing in §4.1: the block is gone, not merely disabled, so the read path is fast-node-free independent of `iavl-disable-fastnode`.) |
| 10 | **Pin the exact surface**: replay block 5378001 on the `data.preheal-*` backup vs a peer's state to identify which key/module read diverged. | Investigation | **Partially done — static forensic scan run (2026-06-22); pruning-bloat hypothesis NOT supported.** The 06-16 (h5378001) diverged chain DB was **not** preserved (that recovery kept only the 248-byte `priv_validator_state.json`). But a real diverged DB **was** preserved from the **06-12** incident: `data.preheal-20260612T164034Z` on prod, h**5280037**, same divergence class. Copied off-host to a dev box and scanned with `analyze-db` via `scripts/replay_divergence.sh`. **Finding:** the diverged DB's cosmos-sdk commit-info store (`s/<version>`) held **2,133,637** records (floor v3146400) vs the ~1000 `pruning-keep-recent` implies — looks like "pruning broken." **But** a current **healthy** mirage-1 peer (<val4>, never diverged) shows the **identical** signature: **2,386,030** records, **same floor v3146400**. So the bloat is **fleet-wide, not divergence-specific → it does not implicate pruning in the divergence.** The static count cannot see the load-triggered IAVL *node-level* prune race (the actual §0.1 hypothesis); that still needs the behavioral A/B under concurrent read load (`replay_divergence.sh --procedure`) against a snapshot whose blocks are locally replayable — still **Open**. Side discovery → new item 12. |
| 11 | Add an in-process app-hash self-check / periodic state-vs-peer reconciliation so a single-node divergence is caught at the producing node, not only at the next block's header check. | Detection | **Open** |
| 12 | **Fleet-wide commit-info bloat — the actual disk-growth driver (discovered 2026-06-22 via item 10).** The cosmos-sdk rootmulti **commit-info** store (`s/<decimal version>`, one ~848-byte `CommitInfo` per height) is **never pruned**: every mirage-1 node retains every commit-info record since the DB was created (version floor **3146400**) — 2.13M on the 06-12 diverged DB, 2.39M on a healthy peer. This is **~1.83 GB of the ~1.84 GB `application.db`** — the IAVL state itself is only ~85 MB because IAVL node pruning (`keep-recent=1000`) *does* work. It grows ~848 B/block forever. **Not the divergence cause** (identical on healthy nodes) but it **is** the disk problem. Ruled out: `min-retain-blocks=201600` is not the floor (2.1M ≫ 201600); `pruneSnapshotHeights` is healthy (recent boundary, not the stale-2026-04-02 bug); floor v3146400 is just the DB (re)creation/state-sync height. **Root cause CONFIRMED (source-level, 2026-06-22; module corrected 2026-06-23):** the store our v0.54 binary actually links is `github.com/cosmos/cosmos-sdk/store/v2@v2.0.0` (`go mod why`: `mirage/app → baseapp → store/v2`; the legacy `cosmossdk.io/store` is unused — *"main module does not need package"*). This `store/v2` is the **relocated rootmulti** module (moved into the SDK repo, bumped to v2.0.0), **not** the SS/SC architectural rewrite — so it carries the identical bug. `rootmulti.Store.PruneStores()` loops stores and `continue`s past everything that is not `StoreTypeIAVL`, pruning only IAVL versions via `DeleteVersionsTo` (and bumping the `s/earliest` pointer); there is **no `deleteCommitInfo`** in the module (the sole `.Delete` is for removing a whole store). Meanwhile `flushCommitInfo` writes `s/<version>` on every `Commit()`. So commit-info is written every block and never deleted — upstream behavior, identical on every node, unbounded. (Deleting old `s/<version>` is consensus-safe: the app hash is computed from the *current* commit-info, not historical; pruned heights are unqueryable anyway and `pruningHeight` already respects snapshot retention.) **Fix shipped (corrected 2026-06-23):** forked the store/v2 module `github.com/cosmos/cosmos-sdk/store/v2` (`blockchain/patches/cosmos-sdk-store-v2`, `replace => ./patches/cosmos-sdk-store-v2`, mirroring the iavl patch) and added `pruneCommitInfo` to `PruneStores`. (An earlier 2026-06-22 attempt patched the *unused* legacy `cosmossdk.io/store` — a build-clean no-op on the live binary; reverted along with its replace.) Each prune pass deletes commit-info records `s/<v>` for `v < pruningHeight`, capped at `commitInfoPruneBatch=20000` per pass so the ~2.1M historical backlog drains over successive passes without stalling a block (steady state is trivial). Iterates the tight `["s/0","s/:")` range so it never walks the IAVL substore data (`s/_/`, `s/k:`) or `s/latest`, and parses the suffix defensively. Collect-then-close-then-write avoids a MemDB iterator/writer deadlock (caught by the new tests). Tests: `rootmulti/commit_info_prune_test.go` (stale-record deletion + batch-cap/decoy-safety). **Upstream status (verified 2026-06-23, source-fetched):** `store/rootmulti/store.go` is **byte-identical** (md5 `ea36670ad370b0ab03857487ed81b2fe`) across the `store/v2.0.0` tag (the module we link), `release/v0.54.x`, and `main`, and **none** delete commit-info — `PruneStores` (L678–L727) only prunes IAVL versions and bumps the `s/earliest` queryable-floor pointer (which frees no disk), while `flushCommitInfo` (L1268) writes `s/<version>` every block. There is **no SS/SC store** in the repo to migrate to (`store/commitment`, `store/storage`, `store/v2/` all 404 on `main`); `store/` *is* rootmulti. So no released or `main` cosmos-sdk version fixes this — our local patch is the only fix. This is a genuine, still-open upstream bug affecting every rootmulti chain with pruning — it just hides where IAVL state dwarfs commit-info (ours is the inverse: ~85 MB state vs ~1.83 GB commit-info). **Filed upstream 2026-06-23:** issue [#26551](https://github.com/cosmos/cosmos-sdk/issues/26551) + PR from `MirageFoundation:fix/rootmulti-prune-commit-info` (branch `fix/rootmulti-prune-commit-info` in the `cosmos-sdk` clone; `cd store && go test ./rootmulti/...` green). | Bug | **DONE — fixed locally; contributed upstream as issue #26551 + PR (courtesy contribution). No further follow-up planned: our fork carries the fix regardless of whether upstream merges; if a maintainer engages we may respond, but we are not tracking review/backport.** |
| 13 | **`pebble: closed` panic on shutdown (double-close of `application.db`), fleet-wide.** First post-deploy soak scan (2026-06-25, ~2.5 days after v1.28.2) found every node panicking `FATAL: panic: pebble: closed` during *graceful* shutdown (counts 06-23..06-25: mirage.talk **3**, mirage.vote 2, <val3> 2, <val4> 1). Log shows `Closing application.db module=baseapp` logged **twice**, the second close on the already-closed handle panicking. **Root cause CONFIRMED (source-level, 2026-06-25):** upstream cosmos-sdk `v0.54.3` `server/start.go` `startInProcess` registers **two** deferred cleanups that both call `app.Close()` — `startCmtNode`'s `cleanupFn` (L415–419, after `tmNode.Stop()`) and `startApp`'s `appCleanupFn` (L634–645) — and `baseapp.(*BaseApp).Close()` (baseapp.go L1155) is **not idempotent**: it calls `app.db.Close()` unconditionally. On shutdown both defers fire (LIFO): the first does a *clean* full close (app.db + snapshots/metadata.db); the second re-enters and `app.db.Close()` panics `pebble: closed`. Pure upstream bug; our wiring is the stock `server.StartCmd(newApp,…)`. **Mostly cosmetic:** the first close succeeds, so app.db *is* cleanly closed — the panic is the redundant second close at the very tail of an already-orderly shutdown, exiting the process non-zero. **Correction to the 06-25 first-pass hypothesis:** this does **not** meaningfully "seed" the prune holes — app.db closes cleanly on the first call, and the one observed PRUNE_HOLE (mirage.vote) happened ~14 h *after* that node's restart, not at shutdown. The real harm is signal/noise: every weekly maintenance restart (item 14) logs a scary `FATAL: panic` and a non-zero exit, polluting crash/forensic monitoring and able to mask a genuine `Close()` error. **Fix v1 (shipped v1.28.2, INCOMPLETE):** wrapped only the `db` handed to `newApp` (`cmd/miraged/cmd/commands.go`) in an idempotent-`Close()` shim. The 2026-07-08 soak scan showed panics **still occurring fleet-wide** — because `BaseApp.Close()` closes **two** handles unconditionally (`application.db` *and* `snapshots/metadata.db`), and the db-shim only covered the first; the second still double-closed and panicked. **Fix v2 (shipped, COMPLETE):** made shutdown idempotent one level up, at the app wrapper — `app.(*App).Close()` now runs the embedded `runtime/baseapp` `Close()` exactly once via `sync.Once` (`blockchain/app/app.go`). This shadows the promoted `BaseApp.Close`, so no matter how many times the server calls `app.Close()`, every underlying DB (`app.db`, `snapshots/metadata.db`, anything else) is closed exactly once — the partial db-shim was removed. Regression test `TestAppCloseIsIdempotent` (`blockchain/app/app_close_test.go`) drives a panic-on-second-close DB through a real `app.New(...)` and asserts the second `Close()` is a no-op; verified to **fail without the fix**. **Upstream fix:** cosmos-sdk PR [#26559](https://github.com/cosmos/cosmos-sdk/pull/26559) makes `BaseApp.Close` itself idempotent (nils `db`/`snapshotManager` after closing); our app-level guard is the local equivalent regardless of whether upstream merges. | Bug | **DONE — app-level idempotent `Close` (v2, complete); contributed upstream as PR #26559 (courtesy contribution). No further follow-up planned: our local guard stands on its own; not tracking review/backport.** |
| 14 | **What restarts the validators ~04:00.** SOLVED (2026-06-25): the orderly `service stop` cascade is triggered by the **`mirage-weekly-upgrade.timer`** systemd timer → `mirage-weekly-upgrade.sh`, a **weekly** `apt full-upgrade` (with a chain-liveness pre-flight). That upgrade pulls new `docker-ce`/`containerd.io`, and installing them **restarts the Docker daemon**, which bounces every `unless-stopped` container → miraged SIGTERM → graceful shutdown → item 13. Confirmed: on mirage.talk `dockerd ActiveEnterTimestamp` and container `startedAt` are both `2026-06-25T04:07:38Z`, and the journal shows `mirage-weekly-upgrade.service` unpacking docker-ce 29.5.3→29.6.0 at that moment (timer NEXT 2026-07-02 04:04). It is **weekly per host, staggered ~04:00**, not daily, and is *intended* security maintenance — **benign, no action required** beyond fixing the cosmetic item-13 panic so these restarts exit cleanly. (Optional hardening: confirm the container stop grace exceeds miraged's shutdown time so a daemon bounce can never SIGKILL mid-commit/mid-prune; observed shutdowns completed within the window.) | Investigation | **Done — weekly OS-upgrade docker-daemon restart; benign** |
| — | **First real PRUNE_HOLE in the wild (2026-06-24, mirage.vote, h≈5572900).** Not an action item — a *result*: the v1.28.2 IAVL fail-fast guard fired once (`CONSENSUS_FATAL:PRUNE_HOLE missing_version=5569770 above existing history`), crashed loudly, auto-recovered, and did **not** recur. Concrete proof the prune race is real and now *contained* (loud recoverable halt vs silent inconsistent read). **Not** proof it caused any past divergence (no app-hash break accompanied it). **Root-caused 2026-07-08** (2 captured events on mirage.talk, both single mid-history holes, `keep-recent≈1000`): async IAVL pruning (background goroutine, byte-flusher persists partial passes) + non-atomic reference-root reformat for empty-block versions (`deleteVersion` L510–525) + **no shutdown drain** (`rootmulti.Store` has no `Close()`, so `nodeDB.Close()`'s `<-ndb.done` drain never runs and `app.db` closes under an in-flight pass) + `firstVersion` never persisted (restart recomputes it via a contiguity-assuming binary search that can't see the hole). Every weekly-upgrade restart exited via the item-13 `pebble: closed` panic, maximising the mid-pass-kill window. **Fix SHIPPED 2026-07-08 — option (A) synchronous pruning:** `newApp` appends `baseapp.SetIAVLSyncPruning(true)`, so the background prune goroutine is never started (`nodedb.go` L124) and deletes run inline in `Commit` (consensus loop stops before `app.db` closes) — no in-flight pass at shutdown, no interrupted reference-root reformat, no new holes. Guard kept as a safety net. Together with the item-13 idempotent `app.Close`, both crash sources are fixed at the root. (B) store-Close drain and (C) persist `firstVersion` were considered but are unnecessary once the goroutine is gone. Diverged DB preserved for offline rootkey-probe verification. See divergence-recovery.md §0.3.1. | Result | **SUPERSEDED 2026-07-12 — the sync-pruning fix did NOT prevent hole formation (see next row). Root cause still OPEN.** |
| — | **FULL CHAIN HALT (2026-07-12 ~20:12–00:00 UTC, ~3h47m) — the v1.29.3 sync-pruning fix FAILED.** v1.29.3 (`SetIAVLSyncPruning(true)` + idempotent `app.Close`) was deployed fleet-wide 2026-07-08. On 07-12 the **two pruning validators crashed on `PRUNE_HOLE` within 9 min** (mirage.talk 20:03 `missing_version=6008029`, 20:12 `missing_version=6016128`; mirage.vote 4 events, incl. a nil-precommit at 20:13). **Sync pruning was confirmed active** — the panic stack runs `rootmulti.Commit → handlePruning → PruneStores → iavl.DeleteVersionsTo → deleteVersionsTo` **inline on the consensus goroutine** (no background prune goroutine) — and the missing versions (6008029, 6016128) were **created AFTER the 07-08 deploy**, under sync pruning, with no shutdown between their creation and their pruning. **So the async-shutdown-race hypothesis (row above) is wrong/incomplete: holes form during normal synchronous operation.** Two failed root-cause fixes now (v1.28.2 inter-block-cache; v1.29.3 sync-pruning). **How a single-node bug became a chain halt:** CometBFT's `receiveRoutine` deferred `recover()` catches the `PRUNE_HOLE` panic and **stops the consensus reactor but leaves the process alive** (RPC + p2p keep responding, `/status` reports the frozen height with `catching_up=false`) — a *consensus zombie*, invisible to the height-based watchdog until the stall timer. With val-2 (vote) and val-3 (talk) both zombied, only val-0 (n146) + val-1 (n139) remained = ~0.4996 power < 2/3 → chain wedged at 6019400 (which was itself validly committed: 0,1,3 precommitted `A9CE0C71` = 0.75). Peer-pull recovery didn't help — the node re-hit a hole within seconds of replaying. **Decisive new correlation:** only talk+vote ran `pruning="custom"` (active); **n146+n139 already ran `pruning="nothing"` and have NEVER hit a hole** → hole formation is tied to *active pruning under user-facing query/tx load* (the two public validators), a reproducible signal. **Recovery (manual, ~00:00 UTC 07-13):** set `pruning="nothing"` on talk+vote and restarted miraged (supervisor relaunch) → consensus reactors restarted → chain resumed instantly (6019400→6019410 in ~12s); vote rejoined; site/API healthy. **Current mitigation state: pruning DISABLED fleet-wide.** Trade-off: `application.db` now grows unbounded (IAVL nodes no longer pruned + the never-pruned commit-info from item 12) — **must monitor disk** (talk was 62% used); this is a **temporary** stopgap, not a fix. **Root cause OPEN** — next step is to reproduce hole formation offline under synchronous pruning + concurrent read load (not the shutdown race), using the preserved 07-05/07-12 diverged DBs. | Result | **Chain restored (pruning disabled fleet-wide, temporary); root cause pinned + fixed same night — see next row** |
| — | **PRUNE_HOLE root cause PINNED (2026-07-13, source-level + deterministic repro): the fail-fast guard panicking on a transient batch-flush window, then destroying the pending batch.** Mechanism, fully verified in code: (1) stores that rarely change (params/upgrade/circuit/…) save a **reference root** for every unchanged version — thousands of consecutive versions all pointing at the same literal root `(v,1)` (`SaveRoot` stores `tree.root.nodeKey`). (2) When pruning version v whose successor references it, `deleteVersion` reformats the root: `Delete((v,1))` then `Set((v,0))` — **two ops on the shared `BatchWithFlusher`, which auto-flushes every ~100 KB**. (3) On talk/vote, reader-load aborts (`unable to delete version X with N active readers`) let the prune backlog grow to thousands of versions per pass (crash #1: first=6005200, prune_to=6018299 → 13k versions), guaranteeing many mid-pass threshold flushes; when one lands **between** the Delete and the Set, the disk transiently has the referenced root deleted and its replacement still pending — and `GetRoot` reads the DB directly, never the pending batch. (4) The guard's probe of the next referencing version (probe errors are never cached, so it re-reads disk) got `ErrVersionDoesNotExist` → **panicked on a false positive** → the panic dropped the pending batch (including the reformat `Set`) → **the transient window became a REAL persistent hole**, which the next pass/restart then crashed on legitimately. So the guard didn't just detect holes — under sync pruning **it manufactured them**; the v1.29.3 sync-pruning change was irrelevant because the flusher behaves identically in both modes (and the pre-v1.29.3 async holes were the same split persisted by shutdown mid-pass). **Fix (two independent layers, `blockchain/patches/iavl/nodedb.go`):** (a) reformat order swapped to **Set-then-Delete** — every intermediate flush state is consistent (worst case both keys briefly coexist, harmless: `GetRoot` resolves via `(v,1)` until the delete lands); (b) the guard now **flushes the batch and re-probes from disk before panicking** — pending-write artifacts heal instead of halting, staged writes are never destroyed, and only a version still missing after the flush is a genuine hole (panic retained for real corruption → watchdog recovery). Regression test `TestDeleteVersionsToSurvivesReformatFlushSplit` (`nodedb_prune_fail_fast_test.go`) forces the flush boundary onto the reformat pair via an instrumented DB wrapper — **verified to panic on the old code and pass on the fixed code**; the real-hole (`HaltsOnMidHistoryHole`) and state-sync-gap tests still pass. NOTE the underlying Delete/Set split window is an **upstream IAVL bug** (upstream doesn't panic, but concurrent readers see phantom missing versions, orphans leak when the traversal errors, and a crash mid-window persists a real hole under async pruning) — candidate for an upstream issue+PR. **Deploy plan:** ship in next patch release; talk+vote carry real holes from tonight's dropped batches, so before re-enabling `pruning="custom"` on them, peer-pull their DBs from the never-pruned n146/n139 (or accept one guard-triggered auto-recovery each); then restore pruning fleet-wide config to stop unbounded disk growth. | Fix | **SHIPPED v1.29.4 (2026-07-13, fleet-wide); pruning auto-re-enabled to `custom` by config re-render on deploy restart. No hole/crash since.** |
| — | **Lockstep chain stall from SYNCHRONOUS pruning → reverted to async (2026-07-13).** After v1.29.4 deployed, a **~6-min FULL-CHAIN stall at h6033700** (~14:04–14:09 UTC): all 4 validators stuck at the same height, resumed together, **no crash / no restart** (`RestartCount=0`, 14h+ uptime), consensus pinned at round 0 (blocked in-process, not failing agreement). Cause = the v1.29.3 `SetIAVLSyncPruning(true)` override: 6033700 is a multiple of `pruning-interval=100`, so every validator ran the same prune pass **inline in `Commit` at the same height**; that pass was a large backlog drain (talk's post-peer-pull base ~6016143, ~16k versions behind) and blocked `Commit` on ALL nodes at once. Backlog drained; did not recur. **Fix SHIPPED v1.29.5:** `newApp` now sets `baseapp.SetIAVLSyncPruning(false)` (explicit async). Sync was only ever added for the wrong shutdown-race theory; with the real hole cause fixed in v1.29.4, async is safe (interrupted pass leaves both reformat keys briefly present, never a hole; guard flush+re-probe backstops) and decouples pruning from consensus so a slow pass makes one node lag/catch-up instead of halting the chain. See divergence-recovery.md §0.3.3. | Fix | **Fixed v1.29.5 (async pruning)** |

---

## 9. Appendix — key evidence

**Divergence (miraged log, 18:21):**
```
ERR CONSENSUS FAILURE!!! err="precommit step; +2/3 prevoted for an invalid block:
wrong Block.Header.AppHash.
  Expected C6ABD68CC326370C8AD3079E80A2BE5A8628AB68CE67ABD07E573DD8FDB85C1C
  got      21C470FFC8B20AED44CFFBBD6D624C52763162DB3A1805C03DF081B8A9AB61EA"
height=5378002 module=consensus
```

**Backend write guard (the user-visible 503):**
```
web/backend/routes/core.py  (core_vote)
    if is_node_catching_up():
        return api_error_code("node_catching_up", 503)
```

**Failed auto-recovery (recover.sh log):**
```
[18:22:32] pulling chain snapshot from root@<val4> …
[18:22:32] ERROR: ssh peer-pull from <val4> failed or timed out      # ssh missing in container
[18:37:46] restart mode … ERROR: restart did not advance the chain past 5378001
[18:38:51] ERROR: ssh peer-pull from <val2> failed or timed out
```

**Watchdog blind spot (repeated every 60 s for ~80 min):**
```
[POLL] … local_h=5378001 catching_up=True … note="catching_up; not a divergence"
```

**serve SIGCONT bug (hit during manual recovery):**
```
[19:45] tar stream complete
        /opt/mirage/scripts/recover.sh: line …: paused: unbound variable
[19:51] resuming miraged (SIGCONT)...
        /opt/mirage/scripts/recover.sh: line …: container: unbound variable
# source peer <val2> left in state Tl+ (SIGSTOP) both times; manually resumed
```

**Successful recovery (recover.sh log):**
```
[19:54:21] peers agree on app_hash @ 5379004
[19:55:32] tar stream complete  /  resuming miraged (SIGCONT)...
[19:56:24] restored priv_validator_state.json (height watermark preserved)
[19:56:41] verified: miraged height 5379118 is past trust height 5379104
[19:56:41] recovery verified. Cool-down lock written.
```

**Post-recovery health:** prod `catching_up=false`, app_hash matches network at
multiple heights; 24 successful on-chain broadcasts 20:07–20:08 UTC.
