# Postmortem — 2026-06-16 mirage.talk AppHash divergence + dead auto-recovery

- **Date (UTC):** 2026-06-16
- **Service:** mirage.talk (prod app host + validator, `159.203.114.27`)
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
| 18:22:30 | Watchdog → `recover.sh peer-pull` attempt #1 (source 139.59.9.96). **Fails instantly** — `ssh` is not installed in the container (`exit 127`), surfaced as "ssh peer-pull failed". |
| 18:37:46 | Watchdog → `recover.sh restart` (non-destructive). Chain does not advance past 5378001 (state is wrong, restart can't fix it) → exit 5. |
| 18:38:51 | Watchdog → `recover.sh peer-pull` attempt #2 (source 64.23.136.132). **Fails instantly** (same missing `ssh`). |
| 18:38:51 → 19:56 | Watchdog now reports `catching_up=true … note="catching_up; not a divergence"` every 60 s and **never acts again** (detection blind spot — a diverged node looks "catching up"). |
| ~18:49 | Reward distributor `bank send` fails (`account number (0)`), collateral of the halt. |
| 19:41–19:50 | User `vote.begin` log lines with **no completion** — all returning 503 `node_catching_up`. This is the user's "Transaction failed." |
| ~19:43 | Incident response begins. |
| 19:45 | Diagnosed: chain halted at 5378001, `catching_up=true`, AppHash mismatch vs peers (peers agree on canonical chain). Confirmed `ssh` missing in container; installed `openssh-client` live. Verified recovery key matches peer `authorized_keys`; `peer-pull --dry-run` clean. |
| 19:45:48 | `peer-pull --auto` connects for the first time, streams the tar — but `recover.sh serve` on the peer hits `paused: unbound variable`, skips SIGCONT, and exits non-zero → client aborts. **Source peer 64.23.136.132 left frozen (SIGSTOP).** Manually resumed (`pkill -CONT`). |
| ~19:50 | Root-caused the serve bug; patched `recover.sh` (made `paused` global), deployed to all 3 peers. |
| 19:51:28 | `peer-pull --auto` retry. SIGCONT now runs but hits a **second** unbound var — `container` (also `local`, also referenced from the EXIT trap) — so the actual `docker exec … pkill -CONT` never runs. **Source peer frozen again.** Manually resumed. |
| ~19:53 | Patched `container` to global + fallback; redeployed to all 3 peers. |
| 19:54:21 | `peer-pull --auto` retry **succeeds**: 957 MB tar pulled from 64.23.136.132, `priv_validator_state.json` preserved, chain DBs replaced, miraged restarted. |
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
`iavl-disable-fastnode = true` (verified live; `MutableTree.Get`'s fast-node block
is gated off and `ImmutableTree.Get` never consults it). So 2026-06-16 is a
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
   aborted the client pull. This bug froze 64.23.136.132 twice during this
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
| 6 | Add an external alert (independent of the watchdog) for "any node `catching_up=true` and height frozen > N min" so a future silent failure pages a human | Detection | **Open** |
| 7 | Periodically smoke-test auto-recovery end-to-end in prod (`peer-pull --dry-run` is not enough — the `ssh`/serve path must be exercised) | Process | **Open** |
| 8 | **Fail-fast the silent fallbacks**: make consensus-path `store.Get` error branches `panic`/halt instead of returning a default (`HasEnvelopeNonce`→`false`, `GetCurrentDifficulty`/`GetPoWMessageCount`→default). A deterministic halt is recoverable by the (now-fixed) watchdog; a silent wrong value is not. | Hardening | **Open (high value)** |
| 9 | **Defense-in-depth**: drop the fast-node read block from `MutableTree.Get` entirely (mirror the `ImmutableTree.Get` patch) so no read path can ever consult the advisory index, regardless of the `iavl-disable-fastnode` toggle. | Hardening | **Open** |
| 10 | **Pin the exact surface**: replay block 5378001 on the `data.preheal-*` backup vs a peer's state to identify which key/module read diverged. | Investigation | **Open** |
| 11 | Add an in-process app-hash self-check / periodic state-vs-peer reconciliation so a single-node divergence is caught at the producing node, not only at the next block's header check. | Detection | **Open** |

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
[18:22:32] pulling chain snapshot from root@139.59.9.96 …
[18:22:32] ERROR: ssh peer-pull from 139.59.9.96 failed or timed out      # ssh missing in container
[18:37:46] restart mode … ERROR: restart did not advance the chain past 5378001
[18:38:51] ERROR: ssh peer-pull from 64.23.136.132 failed or timed out
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
# source peer 64.23.136.132 left in state Tl+ (SIGSTOP) both times; manually resumed
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
