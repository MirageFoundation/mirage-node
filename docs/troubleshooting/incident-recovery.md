# Incident Recovery Runbook

This is the single entry point when a validator is sick. Work top-down: identify the symptom, pick the matching procedure, execute, verify.

> Prefer linking other docs over duplicating them. Every procedure below points at the canonical script and the postmortem it came from.

---

## 0. Triage

Before touching anything, capture the state of the cluster. It tells you how much slack you have and whether consensus is already compromised.

```bash
source ./.env   # MIRAGE_FLEET_HOSTS — gitignored, see .env.example
for ip in $(echo "$MIRAGE_FLEET_HOSTS" | tr , " "); do
  curl -sfm5 "http://$ip:26657/status" \
    | jq -r "\"$ip h=\(.result.sync_info.latest_block_height) \
catching_up=\(.result.sync_info.catching_up) \
app=\(.result.sync_info.latest_app_hash[0:12])\""
done
```

- **4/4 in sync, same app_hash prefix** → healthy. Whatever you are debugging is not a consensus issue.
- **3/4 in sync, one stuck or diverged** → single-node problem. The cluster keeps making blocks. Recover the sick host at your leisure; see §2.
- **2/4 or fewer healthy** → **stop.** The chain is halted or at risk of halting. Do not restart, rollback, or deploy anything on a healthy host. Identify the smallest change that brings one more host back into consensus and do only that.

`scripts/fleet_audit.sh` gives the same triage info plus host-level hardening compliance for each validator.

---

## 1. Which symptom?

| Symptom | Canonical procedure |
|---|---|
| Node stuck at height N, peers at N+k, frontend "node catching up" | **Apphash divergence** → [`divergence-recovery.md`](divergence-recovery.md) (full triage + manual fallback), summary in §2 |
| Node jailed (`jailed: true` in `staking validator`) | **Unjail** → §3 |
| Fresh host, no data yet | **Deploy from scratch** → §4 |
| Host-level issues (swap, ulimit, SSH, docker) | **Baseline / rehardening** → §5 |
| Validator pubkey mismatch on unjail | **Consensus key recovery** → §6 |

---

## 2. Apphash divergence (node stuck behind peers)

**Background**: this class of incident on the Mirage fleet has always been traced back to host-level memory pressure on an underprovisioned validator (4 GB RAM, no swap) causing a silent IAVL cache corruption — the committed state is correct on disk, but an in-memory read during `BeginBlock` returns a stale value, which produces a different apphash for that one height on that one node. `miraged rollback` cannot fix this; restore-from-peer can.

**Canonical recovery for validator-only hosts** (`mirage.vote`, `<val3>`, `<val4>`): restore a fresh backup from a healthy peer using `scripts/backup_restore.py`.

```bash
# From your workstation
scripts/backup_restore.py backup --target mirage.vote          # take a fresh backup from a HEALTHY peer
scripts/backup_restore.py restore \
    --target <sick-host> \
    --file ~/.mirage/backups/mirage.vote/mirage.vote-YYYYMMDD-HHMMSS.tgz \
    --migrate
```

`--migrate` rewrites the restored node to the sick operator's mnemonic, keyring, and moniker. It runs a safety guard (`verify_derived_consensus_key_matches_onchain`) immediately after the keyring import; if the derived consensus pubkey does not match the on-chain validator record, the restore aborts with three named recovery options. Only override with `--allow-consensus-key-change` if you are intentionally rotating the consensus key.

Inside the keyring, `--migrate` replaces only the `validator` account key from the mnemonic. Every other named key in the backup keyring (e.g. `rewards_pool` for quest payouts) is preserved byte-for-byte, and the script logs the preserved set before and after so an operator can confirm nothing was silently dropped. If the post-import check reports missing keys, the specific service that depends on them (e.g. quest payouts on a `503 reward pool not configured` error) must be repaired by re-adding the key manually before the node is considered fully recovered.

**Hard rule for `mirage.talk` (prod app host): do not run cross-node restore (`--migrate` from another node backup).**

`mirage.talk` is not just a validator; it is the live app/backend data node (quests, points, referrals, invite state, stats, push state). Restoring it from another node's backup can overwrite `mirage_backend` with foreign state and permanently hide or drop user-facing progress until manual forensic merge/backfill.

If `mirage.talk` has a chain-state issue, recover by resyncing chain state on that host (or restoring from a `mirage.talk` backup only), not by importing another node's full backup image.

After the node catches up:

1. Confirm `app_hash` matches peers for the latest height.
2. If it was jailed during the outage, go to §3.

**Do not** use `miraged rollback` as a first move. It only rewinds one block and cannot repair an IAVL cache corruption; restore-from-peer is always the safe play.

### 2.1 Auto-recovery via peer-pull (watchdog)

**Scripts**: [`scripts/divergence_watchdog.py`](../../scripts/divergence_watchdog.py), [`scripts/recover.sh`](../../scripts/recover.sh).

Each container ships with a `watchdog` tmux window that polls miraged every 60s and triggers an in-place recovery when it detects either:

1. The miraged log contains `"wrong Block.Header.AppHash"` or `"CONSENSUS FAILURE!!!"` within the last 5 minutes, **or**
2. The local `latest_block_height` has not advanced for ~10 polls (~10 min) **and** ≥2 healthy peers report a height ≥20 blocks ahead.

Default mode is [`recover.sh peer-pull --auto`](../../scripts/recover.sh). It runs inside the container and:

1. Verifies cool-down (≥6 h since last recovery) and that the opt-out marker `~/.mirage/.recovery_disabled` does not exist.
2. Selects ≥2 healthy peers from `persistent_peers` and confirms they agree on `app_hash` for a recent height (refuses to act on a split-brain peer set).
3. Pauses the `indexer`, `backend`, and `status` tmux windows.
4. Stops `miraged`, **backs up `priv_validator_state.json`** (so the height-watermark is preserved — no double-sign risk), wipes only the chain DBs (`application.db`, `blockstore.db`, `cs.wal`, `evidence.db`, `snapshots`, `state.db`, `tx_index.db`).
5. SSHes to the highest healthy peer using the dedicated recovery key. The peer's `authorized_keys` forces `recover.sh serve`, which pauses the peer's `miraged`, streams a gzipped tar of chain DBs, and resumes the peer on exit.
6. Extracts that tar locally, restores the local `priv_validator_state.json`, restarts `miraged` through the supervisor, resumes services, and verifies block progress before writing the cool-down marker (`~/.mirage/.divergence_recovery_lock`).

The script does **not** auto-unjail and does **not** restore PostgreSQL or any backend data — only chain state. Honors the `mirage.talk` hard rule (no PostgreSQL clobber).

`recover.sh state-sync` still exists as an explicit fallback, but it is no longer the watchdog default until the cosmos-sdk v0.53 BondDenom state-sync bug is fixed in Phase 4.

**Disable / dry-run / opt-out**:

```bash
# Detect-only mode (per restart): set in node.env and restart container
DIVERGENCE_DRY_RUN=true

# Disable watchdog entirely (per restart): set in node.env and restart container
AUTO_DIVERGENCE_RECOVERY=false

# One-shot opt-out (no restart needed): create marker inside the container
docker exec mirage touch /root/.mirage/.recovery_disabled
docker exec mirage rm   /root/.mirage/.recovery_disabled   # re-enable

# Override the cool-down (only do this if you know what you're doing)
docker exec mirage rm /root/.mirage/.divergence_recovery_lock
docker exec mirage bash /opt/mirage/scripts/recover.sh peer-pull --auto --force
```

**Logs**:

- Watchdog decisions: `~/.mirage/logs/deploy/divergence_watchdog-YYYY-MM-DD.log` (or `tmux attach -t mirage` → `watchdog`)
- Recovery actions: `~/.mirage/logs/deploy/divergence_recovery-YYYY-MM-DD.log`
- Backups of `priv_validator_state.json` are timestamped under `~/.mirage/.recovery_backup/`.

**Manual invocation** (e.g. when triaging):

```bash
docker exec mirage bash /opt/mirage/scripts/recover.sh peer-pull --dry-run   # plan only
docker exec mirage bash /opt/mirage/scripts/recover.sh peer-pull --auto      # do it

# Legacy state-sync fallback (not the default until the BondDenom bug is fixed)
docker exec mirage bash /opt/mirage/scripts/recover.sh state-sync --dry-run
```

**Limitations**:

- Cannot recover if <2 peers are healthy or peers disagree (by design — refuses to act on a split-brain).
- Does not auto-unjail; after catchup, run §3.
- Does not restore application/backend data on `mirage.talk` (intentional; chain-state-only).

### 2.2 Consensus-determinism fail-fast (panic / EndBlock error)

After the determinism-hardening release, several previously-silent fallbacks in
the consensus path now halt the chain immediately rather than diverge silently.
**This is by design.** A clean halt is detected by §2.1 and recovered from
healthy peers (peer-pull by default; state-sync only as an explicit fallback
once the v0.53 BondDenom panic is fixed in Phase 4); silent divergence — the
original `mirage.talk` failure mode — would have jailed the validator instead.

**Triggers** (search `miraged` logs for any of these strings):

| Tag | Where | Cause | Operator action |
| --- | --- | --- | --- |
| `CONSENSUS_FATAL:PARAMS_STORE_GET` | `core.GetParams` (BeginBlock / EndBlock / handler) | Raw KVStore.Get failed for the `params` key (disk / wrapper I/O error). | Watchdog recovers via §2.1 (peer-pull). |
| `CONSENSUS_FATAL:PARAMS_EMPTY` | `core.GetParams` | `params` key missing post-genesis. Indicates state truncation or genesis-ordering corruption. | Watchdog recovers via §2.1 (peer-pull). |
| `CONSENSUS_FATAL:PARAMS_UNMARSHAL` | `core.GetParams` | Stored params bytes failed to decode. | Watchdog recovers via §2.1 (peer-pull). |
| `CONSENSUS_FATAL:PARAMS_VALIDATE` | `core.GetParams` | Stored params decoded but failed `Validate()` (e.g. governance proposal that bypassed validation). | Halt is correct; investigate the proposal that wrote them, then upgrade-migrate or peer-pull. |
| `CONSENSUS_FATAL:PROFILE_GET` | `deductRelayGasFee`, `processSubscriptions`, ante `getUserLevel` / `checkReserveOrDowngrade` | Raw KVStore.Get failed for a `profiles/<addr>` key. | Watchdog recovers via §2.1 (peer-pull). |
| `CONSENSUS_FATAL:PROFILE_DECODE` | same | A stored ProfileCore JSON blob failed to unmarshal. | Watchdog recovers via §2.1 (peer-pull). |
| `CONSENSUS_FATAL:PROFILE_MISSING` | `deductRelayGasFee`, `processSubscriptions` | A paid-tier user (or an active subscription index entry) has no profile. State inconsistency. | Watchdog recovers via §2.1 (peer-pull). |
| `CONSENSUS_FATAL:RECENT_HASHES_GET` | `RecordRecentBlockHash` (BeginBlock) | Raw KVStore.Get failed for the on-chain recent-block-hashes window. | Watchdog recovers via §2.1 (peer-pull). |
| `CONSENSUS_FATAL:RECENT_HASHES_DECODE` | `GetRecentBlockHashes` (ante) | The on-chain window bytes failed to decode. | Watchdog recovers via §2.1 (peer-pull). |

**What changed for the PoW ante (state-derived recent-hash window)**:

Before: each validator process kept a private in-memory ring of recently-seen
block hashes. After a restart this ring was empty and the node would reject
PoW envelopes referencing block hashes within the window — a per-node accept/
reject flip and therefore an app-hash divergence vs warm peers.

After: the recent-block-hashes window is stored on-chain (key
`recent_block_hashes`, written each `BeginBlock` from
`ctx.BlockHeader().LastBlockId.Hash`, length bounded by
`params.BlockHashWindow`). Acceptance is identical across all peers and across
process restarts.

**Operational implication**: immediately after the upgrade activation height,
the on-chain window starts empty and grows up to `BlockHashWindow` (default 10)
over the next 10 blocks. PoW envelopes referencing pre-upgrade block hashes
will be rejected for those first 10 blocks. This is a brief, planned UX dip;
clients automatically retry with the new last-block-hash on the next refresh.

## 3. Unjailing a validator

**Script**: [`scripts/unjail_validator.sh`](../../scripts/unjail_validator.sh). **Troubleshooting**: [`docs/troubleshooting/validator-unjail-failure.md`](validator-unjail-failure.md).

```bash
ssh root@<host> 'docker exec -it mirage /opt/mirage/scripts/unjail_validator.sh'
```

The script:

1. Waits for `jailed_until` to pass.
2. Queries the on-chain account sequence (never guesses).
3. Generates + signs + broadcasts an `unjail` tx in sync mode.
4. Verifies via state (`jailed` flips to `false`), not by tx-hash lookup.

If it fails, see the troubleshooting guide first. **If it fails with `local consensus pubkey does not match on-chain`, stop and go to §6 — do not retry.** That message means your `priv_validator_key.json` does not match the on-chain validator record and retrying will not help.

## 4. Deploying a fresh node

See [`docs/guides/deploy.md`](../guides/deploy.md). Order is: (1) baseline the host with `deploy/harden_server.sh`, (2) run `deploy/deploy.sh`, (3) optionally `setup_letsencrypt.py`.

## 5. Baseline / rehardening a host

**Script**: [`deploy/harden_server.sh`](../../deploy/harden_server.sh). **Spec**: [`docs/guides/server_setup.md`](../guides/server_setup.md).

One-liner:

```bash
scp deploy/harden_server.sh root@<host>:/root/ && \
  ssh root@<host> 'bash /root/harden_server.sh --weekly-hour=NN'
```

Per-host weekly restart slots live in `.env` (`MIRAGE_WEEKLY_RESTART_SLOTS`), not in this repo. One host per hour, on a day clear of the off-site backup — the backup also stops containers, and only one validator may be down at a time. See [`server_setup.md`](../guides/server_setup.md#weekly-container-restart).

Defaults-on: writes every config, swaps `docker.io` → `docker-ce`, restarts docker if `daemon.json` changed, reboots if a kernel update is pending. Opt out with `--no-migrate-docker`, `--no-restart-docker`, `--no-reboot` if the maintenance window can't absorb one of those right now.

Rolling across the fleet: do one host at a time, verify it is signing after it comes back (a few blocks is enough), then move on. No long soak is required because the hardening does not touch validator identity; worst case you regress one host and recover it the same way.

Use `scripts/fleet_audit.sh` to confirm every host matches the baseline before and after.

## 6. Consensus key recovery (pubkey mismatch)

**When**: unjail (or any signing op) fails with `local consensus pubkey does not match on-chain`.

**Why it happens**: `priv_validator_key.json` on the host is not the key registered for this validator. Most common trigger historically was `scripts/backup_restore.py --migrate` regenerating the key from the operator mnemonic on a validator whose original key was created by `miraged init` (not mnemonic-derived). The `--migrate` safety guard now blocks this class of mistake pre-flight, but the recovery stays in case you hit it another way.

**Recovery outline**:

1. Find a backup tarball for this host that was taken **before** the key was overwritten. Typical location: `~/.mirage/backups/<host>/<host>-YYYYMMDD-HHMMSS.tgz`.
2. Extract that backup's `priv_validator_key.json` and confirm its embedded pubkey matches the on-chain validator's `consensus_pubkey.value` (base64 compare).
3. Check `priv_validator_state.json` on the live host for double-sign risk. If `signature` is `null` (no votes cast with the bad key), you are safe to swap. If there are committed signatures, stop and escalate.
4. Stop the container, swap the key file on the mounted config dir (`/root/.mirage/node/config/priv_validator_key.json`), preserve the existing `priv_validator_state.json`, restart.
5. Verify with `miraged status | jq .ValidatorInfo` and then go to §3 to unjail.

Preserve the bad key and the pre-swap state under `/root/val-recovery-YYYYMMDD/` as forensic artifacts.

**Long-term**: rotate the consensus key onto a mnemonic-derived one so the whole fleet can use `--migrate` without the manual guard.

---

## Verification, after any recovery

```bash
# 1. App hash agrees with peers at the latest height.
H=$(curl -sfm5 http://<healthy-peer>:26657/status | jq -r .result.sync_info.latest_block_height)
source ./.env   # MIRAGE_FLEET_HOSTS — gitignored, see .env.example
for ip in $(echo "$MIRAGE_FLEET_HOSTS" | tr , " "); do
  curl -sfm5 "http://$ip:26657/block?height=$H" \
    | jq -r "\"$ip app=\(.result.block.header.app_hash[0:16])\""
done

# 2. Validator is signing. Replace <ADDR> with the validator's consensus address.
curl -sfm5 "http://<healthy-peer>:26657/block?height=$H" \
  | jq '.result.block.last_commit.signatures[] | select(.validator_address=="<ADDR>") | .block_id_flag'
# flag=2 means this validator signed the block.
```

If all four rows match and flag=2 for the recovered validator three heights in a row, the recovery is done. Log the incident with a one-paragraph update in the relevant postmortem file.
