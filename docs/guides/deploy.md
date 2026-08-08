# Deploying a Mirage Node

Run your own Mirage validator node in minutes.

## Requirements

- A Linux server (**Ubuntu 24.04 LTS** — see [`server_setup.md`](server_setup.md) for the mandatory OS baseline)
- Docker installed on the server (the baseline installs it)
- A domain name pointing to your server (for HTTPS)
- A funded wallet with at least **15 MIRAGE** (25 recommended)

### Server specs

Minimum recommended:

- 2 vCPUs
- 4 GB RAM + **2 GB swap** (the swap is mandatory; a validator that OOMs without swap can silently corrupt its IAVL cache and produce a wrong apphash)
- 25 GB disk

A DigitalOcean droplet at ~$24/month works, but 8 GB RAM is strongly recommended for production.

## Step 0: Bring the host to baseline

Before `deploy.sh`, the host must satisfy the OS baseline in [`server_setup.md`](server_setup.md) (SSH key-only, UFW, fail2ban, swap, docker-ce, ulimits, weekly restart timer). The shortest path is:

```bash
scp deploy/harden_server.sh root@your-server:/root/
ssh root@your-server 'bash /root/harden_server.sh'
```

The script is idempotent; re-running it on an already-hardened host is a no-op.

## Step 1: Get a funded mnemonic

You need a wallet with MIRAGE tokens to run a validator node.

**How to get funded:**

1. Visit [mirage.talk](https://mirage.talk)
2. Create a free account
3. Post in the **#mirage** topic asking for validator funding
4. We'll send you MIRAGE tokens and help you get set up

You'll receive a 12-word mnemonic phrase. Keep it safe — this is your validator identity.

## Step 2: Clone the repository

On your **local machine** (not the server):

```bash
git clone https://github.com/MirageFoundation/mirage-node.git
cd mirage-node
```

## Step 3: Point the node at the network

A new node always joins the existing mirage-1 chain, so it needs to know where
to fetch the genesis and which peers to dial. Neither is committed to this
repo. Copy the template and fill in two entries:

```bash
cp .env.example .env
```

```bash
MIRAGE_REMOTE_RPC=https://mirage.talk/chain/rpc,https://mirage.vote/chain/rpc
MIRAGE_PERSISTENT_PEERS=<node_id>@<host>:26656,<node_id>@<host>:26656
```

`MIRAGE_REMOTE_RPC` needs at least two endpoints. The genesis they serve is
verified against a hash pinned in `deploy/bootstrap_join.py`, so a wrong or
tampered genesis is refused outright. The state-sync trust hash has no such
pin, so it is accepted only when the endpoints agree on it — which is why one
endpoint is not enough. Both are only read during `--init`.

Get peer IDs from any running node with `scripts/get_persistent_peers.sh`, or
ask in **#mirage**.

## Step 4: Deploy

Run the deploy script:

```bash
deploy/deploy.sh root@your-server --init --moniker your-node-name
```

Replace:
- `your-server` with your server's IP or domain
- `your-node-name` with whatever you want to call your node

You'll be prompted for your funded mnemonic. Paste the 12 words when asked.

That's it! The script builds the Docker image, pushes it to a registry, and starts everything on your server.

### Registry auth (one-time)

Deploy now uses a public Docker image on `ghcr.io` by default (fast updates: server pulls layers instead of uploading a tarball).

To be able to **push** images, you must log in once on your local machine:

```bash
docker login ghcr.io
```

Use your GitHub username and a Personal Access Token with `write:packages`.

## Step 5: Enable HTTPS (optional)

If you have a domain pointing to your server, enable TLS:

```bash
ssh root@your-server
docker exec mirage python3 /opt/mirage/deploy/setup_letsencrypt.py --domain=your-domain.com
```

If you're just using an IP address, skip this step — your node will be accessible at `http://your-server-ip` directly.

## Updating your node

To update to the latest version:

```bash
deploy/deploy.sh root@your-server --update
```

This rebuilds the image and restarts the container while preserving all your data and keys.

## What the deploy script does

The script handles everything automatically:

1. **Installs Docker** on the server if it's not already installed
2. **Builds the Docker image** on your local machine and pushes to GHCR
3. **Pulls the image** on your server (fast: only downloads changed layers)
4. **Prompts for your mnemonic** and securely imports your validator keys
5. **Fetches and verifies the mirage-1 genesis** from your bootstrap endpoints
6. **Sets up PostgreSQL** inside the container (no manual database config needed)
7. **Starts all services** (blockchain node, indexer, web backend, frontend)
8. **Creates your validator** on-chain

All data is persisted in `~/.mirage` on the server, so updates preserve your keys and state.

### Your node starts from a state-sync snapshot

Nodes retain roughly a week of blocks, and genesis begins at height 2096156, so
there is no one left to serve the millions of blocks in between. A new node
therefore state-syncs to a recent snapshot instead of replaying history, and
`--init` derives the trust height for you.

The consequence is worth expecting: your indexer starts at the snapshot height
and records the blocks before it as a permanent gap, so node health reports
`history_complete: false` with the missing range listed. That is accurate
rather than broken — your node genuinely has no record of those blocks, and we
would rather say so than let it imply a complete archive. It serves current
traffic normally.

## Monitoring

```bash
# View logs
ssh root@your-server 'docker logs mirage'

# Attach to tmux session
ssh -t root@your-server 'docker exec -it mirage tmux attach -t mirage'
```

## Need help?

Join the conversation on [mirage.talk/r/mirage](https://mirage.talk/t/mirage). We're happy to help you get your node running!
