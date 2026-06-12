# "mirage.talk is down" — Divergence Triage & Recovery

Runbook for the incident class where the site looks dead (API returns
`503 node_catching_up`, frontend loads but shows no data, writes fail) because
the local node diverged from the rest of the cluster. Written after the
2026-06-12 incident (height 5280037). General entry point for all validator
sickness: [`incident-recovery.md`](incident-recovery.md).

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
| One node's height frozen, others advancing | **Divergence** (this runbook) | → §2 |
| All four frozen at the same height | **Chain halt** (upgrade halt? 2+ nodes down?) | → `incident-recovery.md` §0; check miraged logs for `UPGRADE "..." NEEDED` |
| All four advancing, API still 503 | **Indexer-only problem** | → §4 (indexer restart) |

> Trap from 2026-06-12: a stuck local node *also* makes the local
> `chain_head_height` in `indexer_state` go stale, so the backend's error is
> the same in all three cases. Always run the 4-node triage loop — do not
> diagnose from the API error alone.

### 1c. Confirm it is a divergence, not a crash

```bash
ssh root@<sick-host> 'docker exec mirage curl -s http://127.0.0.1:26657/status' \
  | jq '.result.sync_info | {latest_block_height, latest_block_time, catching_up}'
```

- Process up, height frozen, `catching_up: false` → diverged (it thinks it is
  fine; it is on its own fork). The miraged log will show the moment it forked —
  look for `wrong Block.Header.AppHash` near the stall time:

```bash
ssh root@<sick-host> 'docker exec mirage grep -a "wrong Block.Header.AppHash" \
  /root/.mirage/logs/node/miraged-$(date -u +%F).log | head -5'
```

- Process dead → crash, not divergence; check the supervisor and the end of the
  miraged log instead.

### 1d. Check what the watchdog saw

```bash
ssh root@<sick-host> 'docker exec mirage tail -40 \
  /root/.mirage/logs/deploy/divergence_watchdog-$(date -u +%F).log'
```

You should see `DIVERGENCE DETECTED — stall: ...` lines. If the watchdog was in
alert-only mode (`WATCHDOG_AUTORECOVER` not `true`), nothing has been recovered
yet and you proceed manually (§2).

---

## 2. RECOVERY — automated path (try this first)

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
   dry-run prints a note if it is missing — read the dry-run output. Manual
   fallback: §3.
4. **Indexer live-tail.** See §4. The catch-up gap does not close on its own.
