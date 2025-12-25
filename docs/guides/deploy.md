# Mirage deploy refactor - usage

## Reset local testnet from live state (single-validator simulation)

You can clone the live chain’s on-disk state and run a fully isolated, single-validator simulation locally for upgrade testing.

Requirements:
- Docker installed locally
- SSH access to the source host

Usage:

```bash
conda run -n mirage-node python3 scripts/reset_local_testnet.py
```

Options:
- `--source <host>`: override source host (default is defined by the script)
- `--file <path>`: use a previously saved local snapshot tarball instead of fetching from the source

What it does:
- Briefly stops the `mirage` container on the source, archives `/root/.mirage/main`, copies it locally, then restarts the source container.
- The remote archive `/tmp/main.tgz` is removed after transfer.
- Loads/starts a local `mirage` container if missing.
- Preserves the exact snapshot inside the container at `/root/.mirage/main.clone`.
- Builds a new local, runnable single-validator genesis in `/root/.mirage/main`:
  - Keeps all app parameters and non-staking module state.
  - Rewrites staking/slashing to a single local validator.
  - Creates `validator` and `faucet` keys in `keyring-test`.
  - Prefunds `faucet` for proposal testing.
- Restarts the local container; node, indexer, and backend come up automatically.

Notes:
- The local node is fully isolated (no peers) and uses `keyring-backend = "test"` to sign transactions in the backend.
- To reset again, simply re-run the script.

## One script

Run all deployments with:

```bash
deploy/deploy.sh user@host --init
deploy/deploy.sh user@host --update
deploy/deploy.sh user@host --update-init
```

### Deploy to multiple servers (build once, reuse)

There is a wrapper that deploys once to build the image tarball, then reuses that exact tarball to deploy to the rest of your servers. The host list is defined inside `scripts/deploy_all_prod.sh`.

```bash
scripts/deploy_all_prod.sh [--init|--update|--update-init]
```

- Default mode is `--update-init`.
- Set `SSH_USER` to override the default user (root).
- The wrapper will prompt for confirmation before proceeding.
- If HTTPS is not working afterwards, run inside the container:

```bash
CONTAINER="${CONTAINER:-mirage}"
NODE_DOMAIN="<YOUR_NODE_DOMAIN>"
docker exec "${CONTAINER}" bash /opt/mirage/deploy/letsencrypt_register.sh --domain "${NODE_DOMAIN}"
```

Notes:
- Moniker is fixed to `validator`.
- On `--init`, you will be prompted to enter your funded mnemonic. It is imported into the node volume before startup.
- Persistent data: `~/.mirage` (node) and `~/.caddy` (certs) on the remote host.
- No config files are edited in-place. Configs are rendered from templates.

## Persistent config

- On `--init`, `~/.mirage/config/` is created on the host. Example templates from `deploy/templates/*.env.example` are copied and first-time `.env` files are created if missing.
- On subsequent `--update` or `--update-init`, these files are never overwritten.
- The container loads any present files via `--env-file`:
  - `~/.mirage/config/backend.env`
  - `~/.mirage/config/node.env`
  - `~/.mirage/config/indexer.env`
  - `~/.mirage/config/frontend.env` (build-time values only)
- To change the validator moniker persistently, edit `~/.mirage/config/node.env` and set `MONIKER=your-name`. You can also pass `--moniker` to override for a given deployment.

### Database (PostgreSQL)

- The indexer and backend require PostgreSQL.
- You must set `MIRAGE_INDEXER_DB_URL` in `~/.mirage/config/indexer.env` (and ensure the same URL is reachable by the backend).
- Example:

```
MIRAGE_INDEXER_DB_URL=postgresql://mirage:password@127.0.0.1:5432/mirage
```

- If `MIRAGE_INDEXER_DB_URL` is not set, startup will fail immediately.

## Server requirements

Minimum recommended droplet size on DigitalOcean for a validator:

```
Regular (shared)

2 vCPUs

4 GB memory

25 GB

4 TB transfer

$24/mo

$0.036/hr
```

## Domain and TLS

After the container is running, enable HTTPS from the Docker host:

```bash
CONTAINER="${CONTAINER:-mirage}"
NODE_DOMAIN="<YOUR_NODE_DOMAIN>"
docker exec "${CONTAINER}" bash /opt/mirage/deploy/letsencrypt_register.sh --domain "${NODE_DOMAIN}"
```

The script validates DNS, renders the Caddyfile with the domain, and reloads Caddy.

## Key management

- `priv_validator_key.json` is generated once if missing and preserved thereafter.
- On-chain consensus key rotation is not supported on this chain. If the validator is tombstoned or keys mismatch, provision a fresh node and run create-validator.

### Consensus key derivation (deterministic)

- On `--init`, the consensus Ed25519 key is deterministically derived from your mnemonic using SLIP-0010 at path `m/44'/118'/1'/i'`, where `i` is the rotation index.
- The script will prompt: `Consensus derivation index [0] (default 0; do not change unless rotating)`. For a new server, use `0`.
- The consensus key is written to `~/.mirage/main/config/priv_validator_key.json` and is never overwritten. If the file exists, deploy aborts immediately before any changes.
- To rotate the consensus key in the future, increase `i` (e.g., `1`, `2`, …) and deploy a fresh node. On-chain key rotation is not supported.

## Files of interest

- `deploy/deploy.sh`: unified deploy CLI.
- `deploy/entrypoint.sh`, `deploy/init.sh`: container bootstrap and runtime.
- `deploy/templates/`: `config.toml`, `app.toml`, `client.toml`, `Caddyfile`.
- `deploy/letsencrypt_register.sh`: HTTPS setup (configures Caddy with Let's Encrypt).
 

