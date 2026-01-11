### Chain upgrades (governance + deploy) — Mirage runbook

This guide is the **exact** operational flow for upgrades that change the blockchain state machine (the `miraged` binary / Go chain code).

### Key concepts (Mirage-specific)

- **Upgrade “name”**: the on-chain upgrade plan name (example: `v1.7.7-tier-pricing`).
  - This must match the string passed to `app.UpgradeKeeper.SetUpgradeHandler("<name>", ...)` in `blockchain/app/upgrades.go`.
  - This must also match the `plan.name` in the governance proposal JSON.
- **Deployment model**: a single Docker container (`mirage`) starts a tmux session and runs:
  - `miraged start ... | cronolog ...` (node logs go to `~/.mirage/logs/node/miraged-YYYY-MM-DD.log`)
  - other services (postgres, backend, indexer, etc.)
- **What happens at upgrade height**:
  - When the chain reaches the scheduled upgrade height, **`miraged start` exits** to force a restart so the upgrade handler can run on startup.
  - The Docker container usually **does not exit** (tmux stays alive), so you must **restart the container** (or redeploy) to bring the node back up.

### Step 0 — Pick a good upgrade name

Use the “version + slug” style so it’s self-explanatory, e.g.:

- `v1.7.7-tier-pricing`
- `v1.8.0-<feature>`

### Step 1 — Implement the chain changes (Go)

At minimum, for a chain upgrade you need:

- **Upgrade handler** in `blockchain/app/upgrades.go`:
  - `app.UpgradeKeeper.SetUpgradeHandler("<upgrade-name>", func(...) {...})`
  - Put all required on-chain param/state updates here.
- **Genesis updates** (optional):
  - Only relevant for *new* chains / local fresh init.
  - Existing chains will not read `blockchain/genesis/genesis.json` again.

If your upgrade adds/removes stores (module KV stores), you must also ensure the app is wired to handle store upgrades. (For simple param changes, you usually don’t need store-loader wiring.)

### Step 2 — (If needed) add a deploy migration

If the upgrade requires filesystem/config cleanup on validators (not chain state), add a migration under:

- `deploy/migrations/*.py`

Important:
- **Renaming the migration filename is safe** (ordering is by filename, tracking is by key).
- **Changing `MIGRATION_KEY` changes what the system considers “already run”**:
  - A new key will run even if an older version already ran (because it won’t be present in `~/.mirage/env/.migrations`).
  - Only do this if the migration is truly idempotent and you *want* it to re-run.
- Migrations run on container start via `deploy/entrypoint.sh`:
  - `python3 -m deploy.migrations --config-dir ~/.mirage/env`

### Step 3 — Build the Docker image tarball (new `miraged`)

On your local machine (repo root):

```bash
cd /home/nik/projects/mirage/public/mirage-node && ./deploy/deploy.sh --build-only --file deploy/mirage-docker-dev.tar.gz
```

This:
- regenerates protobufs
- builds and installs `miraged`
- builds the Docker image
- saves it to a tarball you can deploy

### Step 4 — Write the upgrade proposal JSON

Edit/create:

- `scripts/proposals/proposal_upgrade.json`

It should be a `MsgSoftwareUpgrade` and include:
- `plan.name`: **exactly** your upgrade handler name
- `plan.height`: use the `T+N` placeholder format (recommended) so the submit script resolves it automatically

Example:

```json
{
  "messages": [
    {
      "@type": "/cosmos.upgrade.v1beta1.MsgSoftwareUpgrade",
      "authority": "mirage10d07y265gmmuvt4z0w9aw880jnsr700jvealeg",
      "plan": {
        "name": "v1.7.7-tier-pricing",
        "height": "T+7200",
        "info": "Human summary of what changes"
      }
    }
  ],
  "metadata": "",
  "deposit": "10000000umirage",
  "title": "Upgrade: v1.7.7-tier-pricing",
  "summary": "Short but complete summary.",
  "expedited": true
}
```

Notes:
- Mirage block time is ~3s, so `T+7200` is roughly 6 hours (\(7200*3s\)).
- The actual resolution happens at submission time (see the next step).

### Step 5 — Submit the proposal (governance transaction)

Use the submit script:

```bash
cd /home/nik/projects/mirage/public/mirage-node && python3 scripts/submit_proposal.py remote scripts/proposals/proposal_upgrade.json
```

What the script does (high level):
- resolves `T+N` into an absolute height using the RPC `/status`
- submits the proposal (from the faucet account)
- votes YES with all validator keys it can find
- polls until it gets a final result

Tip: do a dry-run first to confirm the final JSON that will be broadcast:

```bash
cd /home/nik/projects/mirage/public/mirage-node && python3 scripts/submit_proposal.py remote scripts/proposals/proposal_upgrade.json --dry-run
```

### Step 6 — Deploy the new image to validators (before upgrade height)

You want the new binary available everywhere **before** the upgrade height.

Deploy to a server:

```bash
cd /home/nik/projects/mirage/public/mirage-node && ./deploy/deploy.sh root@your-server --update --file deploy/mirage-docker-dev.tar.gz
```

What this does:
- stops and removes the old `mirage` container
- loads the new image tarball
- starts a fresh `mirage` container
- container startup runs deploy migrations + init + tmux services (including `miraged start`)

### Step 7 — At the upgrade height: restart `mirage` so the chain continues

At the scheduled height:
- the currently running `miraged start` process will exit
- you must restart it by restarting the container (or redeploying)

If you already deployed the new image in Step 6, the quickest restart is:

```bash
ssh root@your-server 'docker restart mirage'
```

If you did **not** deploy the new image yet, you must deploy it now (Step 6) and that will restart the container as part of deployment.

### Step 8 — Verify the upgrade actually applied

Checks to run after the chain is producing blocks again:

- **Node is live**:
  - `curl -sf http://<server>:26657/status`
- **Logs**:
  - confirm new logs continue in `~/.mirage/logs/node/miraged-YYYY-MM-DD.log`
  - confirm expected upgrade log lines (from your upgrade handler)
- **State/params**:
  - query the relevant module params/state and confirm the new values are present

### Common failure modes

- **Plan name mismatch** (proposal vs handler):
  - The chain halts at upgrade height and the restarted binary can’t find a matching handler.
  - Fix: make `plan.name` match the handler string exactly, rebuild, redeploy, restart.
- **You deployed new binary but didn’t restart at height**:
  - The `miraged start` process is dead, container still running.
  - Fix: `docker restart mirage`.
- **Deploy migration didn’t run**:
  - Migrations run on container startup only.
  - Fix: restart container (or redeploy).

