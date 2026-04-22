# Incident Recovery Runbook

This is the single entry point when a validator is sick. Work top-down: identify the symptom, pick the matching procedure, execute, verify.

> Prefer linking other docs over duplicating them. Every procedure below points at the canonical script and the postmortem it came from.

---

## 0. Triage

Before touching anything, capture the state of the cluster. It tells you how much slack you have and whether consensus is already compromised.

```bash
for ip in 159.203.114.27 64.23.136.132 146.190.108.140 139.59.9.96; do
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
| Node stuck at height N, peers at N+k, frontend "node catching up" | **Apphash divergence** → §2 |
| Node jailed (`jailed: true` in `staking validator`) | **Unjail** → §3 |
| Fresh host, no data yet | **Deploy from scratch** → §4 |
| Host-level issues (swap, ulimit, SSH, docker) | **Baseline / rehardening** → §5 |
| Validator pubkey mismatch on unjail | **Consensus key recovery** → §6 |

---

## 2. Apphash divergence (node stuck behind peers)

**Background**: this class of incident on the Mirage fleet has always been traced back to host-level memory pressure on an underprovisioned validator (4 GB RAM, no swap) causing a silent IAVL cache corruption — the committed state is correct on disk, but an in-memory read during `BeginBlock` returns a stale value, which produces a different apphash for that one height on that one node. `miraged rollback` cannot fix this; restore-from-peer can.

**Canonical recovery for validator-only hosts** (`mirage.vote`, `146.190.108.140`, `139.59.9.96`): restore a fresh backup from a healthy peer using `scripts/backup_restore.py`.

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
for ip in 159.203.114.27 64.23.136.132 146.190.108.140 139.59.9.96; do
  curl -sfm5 "http://$ip:26657/block?height=$H" \
    | jq -r "\"$ip app=\(.result.block.header.app_hash[0:16])\""
done

# 2. Validator is signing. Replace <ADDR> with the validator's consensus address.
curl -sfm5 "http://<healthy-peer>:26657/block?height=$H" \
  | jq '.result.block.last_commit.signatures[] | select(.validator_address=="<ADDR>") | .block_id_flag'
# flag=2 means this validator signed the block.
```

If all four rows match and flag=2 for the recovered validator three heights in a row, the recovery is done. Log the incident with a one-paragraph update in the relevant postmortem file.
