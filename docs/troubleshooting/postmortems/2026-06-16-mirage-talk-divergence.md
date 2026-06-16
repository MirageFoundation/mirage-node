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

### 4.1 Trigger (the divergence itself) — most likely host memory pressure → IAVL cache corruption

prod diverged alone (all 3 peers had **0** AppHash errors that day), so this is
**not** a chain-wide non-determinism bug. It matches the failure class already
documented in [`incident-recovery.md` §2](../incident-recovery.md): host-level
memory pressure on an underprovisioned validator causing a silent in-memory IAVL
read to return a stale value during block execution, which yields a different
app_hash for one height on that one node. The committed on-disk state is correct;
`miraged rollback` cannot fix it; restore-from-peer can.

Supporting evidence:
- prod-only divergence (peers clean).
- prod is the **single most memory-constrained and most loaded** box in the fleet
  — it runs miraged **and** the indexer, backend (gunicorn), PostgreSQL, and Caddy
  together on **3.8 GiB RAM** (observed 168 MiB free, 2 GiB swap).
- This is **recurring** on prod specifically: divergence/stall recoveries on
  2026-05-25, 2026-06-12, 2026-06-14 (stall), and 2026-06-16. The cadence is
  tightening (every ~2 days recently).

> This trigger is strongly indicated but not definitively proven for this specific
> event (no OOM-kill or EDAC/MCE line was captured in `dmesg` at the time). It
> remains the leading hypothesis and the basis for the prevention action items.

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

All three tooling defects are fixed in the repo. The trigger (memory pressure) is
**not** fixed — see Action Items.

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
| 1 | Add `openssh-client` to runtime image | Fix | Done (repo); deploy pending |
| 2 | Fix `recover.sh serve` SIGCONT (globals) | Fix | Done (repo + live on peers); image deploy pending |
| 3 | Watchdog detects divergence while `catching_up=true` | Fix | Done (repo); deploy pending |
| 4 | Rebuild image + redeploy fleet so 1–3 are permanent/live | Deploy | **Open** |
| 5 | **Address the trigger: relieve prod memory pressure** — move the validator off the app host, or materially increase RAM, or both. prod runs node+indexer+backend+postgres+caddy on 3.8 GiB. | Prevention | **Open (highest value)** |
| 6 | Add an external alert (independent of the watchdog) for "any node `catching_up=true` and height frozen > N min" so a future silent failure pages a human | Detection | **Open** |
| 7 | Periodically smoke-test auto-recovery end-to-end in prod (`peer-pull --dry-run` is not enough — the `ssh`/serve path must be exercised) | Process | **Open** |
| 8 | Consider on-chain/IAVL determinism hardening + fail-fast (some already shipped per `incident-recovery.md` §2.2) to convert silent divergence into a clean, auto-recoverable halt | Hardening | **Open** |

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
