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
   `deploy/migrations/v1_28_1_disable_inter_block_cache.py` (config-only, picked
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
for ip in 159.203.114.27 64.23.136.132 146.190.108.140 139.59.9.96; do
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
SICK=159.203.114.27; PEER=146.190.108.140
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
  echo \"== events ==\";       grep -E \"\\[(TRIGGER|PRECHECK|DISPATCH|INVOKE|POSTCHECK|ESCALATE|ALERT|CRASH)\\]\" \"\$F\" | tail -30'"
```

Key fields to read: `[POLL] last_advance_age_s=` (how long stuck), `[PRECHECK]
match=true|false` (the app_hash decision), `[DISPATCH] action=restart|peer-pull`
(what it chose and why). If the watchdog already restarted and recovered, you may
be done — verify with §5. If `WATCHDOG_AUTORECOVER` is not `true` and the class
is divergence, peer-pull was not run; proceed manually (§2B).

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
SOURCE=146.190.108.140
SICK=159.203.114.27

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
happily tail new blocks over WebSocket — `last_processed_height` advances 1
block per ~3 s, in lockstep with the head, and **the gap never closes** (and
any blocks it indexed on the diverged fork are never rolled back). The symptom:
"the number just goes up every 3 seconds" while the API stays 503.

```bash
ssh root@<sick-host> 'docker exec mirage bash -c "
  tmux send-keys -t mirage:indexer C-c; sleep 5
  tmux send-keys -t mirage:indexer \"PYTHONPATH=/opt/mirage python3 /opt/mirage/indexer/main.py\" Enter"'
```

On restart the indexer detects its DB is past/off the chain's real history,
rolls back to the divergence point, and replays forward at ~4 blocks/s
(~8 min per 2000 blocks). Watch the gap close:

```bash
ssh root@<sick-host> 'docker exec -u postgres mirage psql -d mirage_indexer -At -F" " -c \
  "SELECT key, value FROM indexer_state WHERE key IN ('"'"'last_processed_height'"'"','"'"'chain_head_height'"'"') ORDER BY key;"'
```

The API flips to 200 when the gap is ≤10 blocks and `last_processed_time` is
fresh (<30 s).

---

## 5. VERIFY

```bash
# 1. App hash agreement at one height across all four nodes:
H=$(curl -sfm5 http://146.190.108.140:26657/status | jq -r .result.sync_info.latest_block_height)
for ip in 159.203.114.27 64.23.136.132 146.190.108.140 139.59.9.96; do
  curl -sfm5 "http://$ip:26657/block?height=$H" \
    | jq -r "\"$ip app=\(.result.block.header.app_hash[0:16])\""
done

# 2. The recovered validator is signing again (flag 2 = signed):
curl -sfm5 "http://146.190.108.140:26657/block?height=$H" \
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
for ip in 159.203.114.27 64.23.136.132 146.190.108.140 139.59.9.96; do
  echo "== $ip =="
  ssh root@$ip 'docker exec mirage bash /opt/mirage/scripts/recover.sh restart --dry-run'
done
```

Expect each to print the pre-stop height and the "DRY RUN — would: stop
miraged ... NO DB wipe ..." block, then exit 0. Also confirm the watchdog is
running and logging on every host:

```bash
for ip in 159.203.114.27 64.23.136.132 146.190.108.140 139.59.9.96; do
  ssh root@$ip 'docker exec mirage sh -c "tail -1 /root/.mirage/logs/watchdog/watchdog-$(date -u +%F).log"'
done
```
