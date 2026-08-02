# Mirage Deployment System

This document provides a comprehensive technical overview of the Mirage deployment system, covering the Docker-based containerization, deployment scripts, service orchestration, and operational procedures. It is intended for senior engineers, DevOps personnel, and project managers who need to understand how the system is deployed, updated, and maintained.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Philosophy](#architecture-philosophy)
3. [Docker Image](#docker-image)
4. [Deployment Script](#deployment-script)
5. [Container Entrypoint](#container-entrypoint)
6. [Service Orchestration](#service-orchestration)
7. [Configuration Management](#configuration-management)
8. [HTTPS and TLS](#https-and-tls)
9. [Validator Operations](#validator-operations)
10. [Monitoring and Logging](#monitoring-and-logging)
11. [Common Operations](#common-operations)
12. [Troubleshooting](#troubleshooting)

---

## Overview

The Mirage deployment system packages all components into a single Docker container:

- **Blockchain Node** (miraged) - CometBFT consensus + Cosmos SDK app
- **Web Backend** (Flask/Gunicorn) - API relay layer
- **Indexer** (Python) - PostgreSQL-backed chain indexer
- **PostgreSQL** - Two databases: `mirage_indexer` (indexer) and `mirage_backend` (backend-owned data)
- **Caddy** - Reverse proxy with automatic HTTPS
- **Optional Services**: Bridge Orchestrator

**Key Design Principle:** One container per node. All services are managed via tmux windows for easy operator access. Persistent data lives in `~/.mirage` on the host (volume-mounted).

---

## Architecture Philosophy

### Why Monolithic Container?

Traditional microservices would split each component into separate containers. Mirage uses a monolithic approach because:

1. **Simplicity** - Single container to deploy, update, monitor
2. **Tight Coupling** - Components depend on each other's availability
3. **Resource Efficiency** - Shared memory, no inter-container networking overhead
4. **Operator Experience** - tmux provides unified access to all services

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CONTAINER ARCHITECTURE                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Docker Container: mirage                                           │    │
│  │                                                                      │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐│    │
│  │  │  Caddy   │  │  Node    │  │ Backend  │  │     PostgreSQL       ││    │
│  │  │  :80/443 │  │ :26656/7 │  │  :5000   │  │       :5432          ││    │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────────┬───────────┘│    │
│  │       │             │             │                   │            │    │
│  │       │         ┌───┴───┐         │       ┌───────────┴──────────┐  │    │
│  │       │         │Indexer│────────RW──────►│  mirage_indexer DB   │  │    │
│  │       │         └───────┘         │       └─────────────────┘      │    │
│  │       │                           │       ┌─────────────────┐      │    │
│  │       │                        ───RW─────►│ mirage_backend  │      │    │
│  │       │                        ───RO─────►│ mirage_indexer  │      │    │
│  │       └───────────────────────────┘       └─────────────────┘      │    │
│  │                   │                                                │    │
│  │           reverse_proxy /api/*                                     │    │
│  │                                                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  Host Volume: ~/.mirage/                                                     │
│    ├── node/        (blockchain data)                                        │
│    ├── postgres/    (database files)                                         │
│    ├── logs/        (all service logs)                                       │
│    └── env/         (environment files)                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Registry-Based Deployment

Images are pushed to GitHub Container Registry (GHCR):
- Build once locally
- Push to `ghcr.io/miragefoundation/mirage-node:<hash>`
- All servers pull from registry (parallel, fast)

---

## Docker Image

### Multi-Stage Build

The Dockerfile uses multiple stages for efficiency:

```dockerfile
# Stage 0: Build Caddy with rate-limit plugin
FROM caddy:builder AS caddy-builder
RUN xcaddy build --output /usr/bin/caddy \
    --with github.com/mholt/caddy-ratelimit

# Stage 1: Build frontend, install dependencies
FROM ubuntu:24.04 AS builder
# Install Node.js 20, Python 3, build tools
# npm ci for frontend dependencies
# pip install for backend dependencies
# npm run build for React production build

# Stage 2: Minimal runtime image
FROM ubuntu:24.04
# Install only runtime dependencies
# Copy binaries from builder (not source code)
# Copy built frontend (not source)
# Copy Python modules
```

### What's Included

| Component | Source | Destination |
|-----------|--------|-------------|
| miraged binary | `blockchain/bin/miraged` | `/opt/mirage/blockchain/bin/miraged` |
| orchestrator binary | `blockchain/bin/orchestrator` | `/opt/mirage/blockchain/bin/orchestrator` |
| React build | `web/frontend/build/` | `/opt/mirage/web/frontend/build/` |
| Python backend | `web/backend/` | `/opt/mirage/web/backend/` |
| Python indexer | `indexer/` | `/opt/mirage/indexer/` |
| Shared modules | `shared/` | `/opt/mirage/shared/` |
| Deploy scripts | `deploy/` | `/opt/mirage/deploy/` |
| Templates | `deploy/templates/` | `/opt/mirage/deploy/templates/` |

### Pre-Built Binaries

Go binaries are built on the host before Docker build:

```bash
maybe_proto_gen_and_go_build() {
    # Check if proto-gen needed (based on .proto source files)
    if proto_hash_changed; then
        cd blockchain && make proto-gen
    fi
    
    # Check if Go build needed
    if go_source_changed || binaries_missing; then
        cd blockchain && make build-all
    fi
}
```

This avoids installing Go in the Docker image, reducing size significantly.

### Exposed Ports

```dockerfile
EXPOSE 80 443 26656 26657
```

| Port | Service | Purpose |
|------|---------|---------|
| 80 | Caddy | HTTP (redirects to HTTPS) |
| 443 | Caddy | HTTPS (frontend + API) |
| 26656 | miraged | P2P (node discovery, block propagation) |
| 26657 | miraged | RPC (query interface, optional external access) |

---

## Deployment Script

### Usage

```bash
# Remote deployment (update existing node)
deploy/deploy.sh user@host --update

# Remote deployment (first-time setup)
deploy/deploy.sh user@host --init --moniker "my-validator"

# Local development
deploy/deploy.sh --local --update

# Build and push to registry only
deploy/deploy.sh --build-only
```

### Modes

| Mode | Purpose |
|------|---------|
| `--init` | First-time setup: imports mnemonic, derives keys, creates validator |
| `--update` | Update image and restart (preserves data) |
| `--build-only` | Build and push image without deploying |
| `--local` | Deploy to local Docker (development) |

### Init Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         --init DEPLOYMENT FLOW                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. Sanity Check                                                             │
│     - Verify no existing priv_validator_key.json (prevent overwrite)         │
│                                                                              │
│  2. Build & Push Image                                                       │
│     - Run proto-gen if needed                                                │
│     - Build Go binaries if needed                                            │
│     - docker buildx build --push                                             │
│                                                                              │
│  3. Prompt for Mnemonic                                                      │
│     - Read 12-word BIP39 mnemonic from stdin                                 │
│     - Validate word count                                                    │
│                                                                              │
│  4. Derive Consensus Key                                                     │
│     - Run derive_consensus_key.py in one-shot container                      │
│     - Creates priv_validator_key.json from mnemonic + derivation index       │
│                                                                              │
│  5. Import Account Key                                                       │
│     - Run `miraged keys add validator --recover`                             │
│     - Imports mnemonic into keyring (test backend)                           │
│                                                                              │
│  6. Start Container                                                          │
│     - Mount ~/.mirage (persistent data)                                      │
│     - Start services via entrypoint.sh                                       │
│                                                                              │
│  7. Create Validator                                                         │
│     - Run create_validator.sh inside container                               │
│     - Stakes initial tokens, registers validator on-chain                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Update Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         --update DEPLOYMENT FLOW                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. Build & Push Image                                                       │
│     - Same as --init                                                         │
│                                                                              │
│  2. Stop Existing Container                                                  │
│     - docker stop --timeout=60 mirage                                        │
│     - Graceful shutdown (allows block completion)                            │
│                                                                              │
│  3. Remove Old Container                                                     │
│     - docker rm mirage                                                       │
│                                                                              │
│  4. Pull New Image                                                           │
│     - docker pull ghcr.io/miragefoundation/mirage-node:<hash>               │
│                                                                              │
│  5. Start New Container                                                      │
│     - Same volume mounts as before                                           │
│     - Reads existing MONIKER from node.env                                   │
│                                                                              │
│  6. Stability Check                                                          │
│     - Wait for container to be "running" and responsive                      │
│     - Require 3 consecutive successful docker exec                           │
│                                                                              │
│  7. Post-Update Tasks                                                        │
│     - Update validator moniker if changed                                    │
│     - Configure host-side rate limiting                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### SSH Optimization

For remote deploys, the script uses SSH control sockets:

```bash
# Establish control socket (reused for all commands)
ssh -o ControlMaster=auto -o ControlPath=/tmp/mirage-ssh-%r@%h:%p \
    -o ControlPersist=300 "$REMOTE" 'exit'

# All subsequent commands reuse the socket
run_ssh() {
    ssh -o ControlPath=/tmp/mirage-ssh-%r@%h:%p "$REMOTE" "$@"
}
```

For high-latency servers, use `--proxyjump`:

```bash
deploy/deploy.sh root@slow-server --update --proxyjump mirage.vote
```

---

## Container Entrypoint

### Startup Sequence

The `entrypoint.sh` script orchestrates service startup:

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. Sync env files with templates (fills in defaults from deploy/templates/env/)
python3 -c "from deploy.migrations._helpers import sync_all; ..."

# 2. Load environment files
load_env_files  # ~/.mirage/env/*.env

# 3. Validate required env vars (INDEXER_DB_URL, INDEXER_DB_RO_URL, BACKEND_DB_URL)

# 4. Set container hostname
hostname "${DOMAIN//./-}"

# 5. Run initialization (init.sh)
bash "$ROOT_DIR/deploy/init.sh"

# 6. Render Caddyfile template
python3 render_template.py templates/caddy/Caddyfile /etc/caddy/Caddyfile

# 7. Start tmux session
tmux new-session -d -s mirage

# 8. Start services in order:
#    Caddy → PostgreSQL → (wait for pg_isready)
#    → Migrate DB/role names if needed (mirage → mirage_indexer, etc.)
#    → Ensure both DBs exist (mirage_indexer + mirage_backend) + mirage_indexer_ro role
#    → Initialize backend schema (init_backend_schema)
#    → Run deploy migrations
#    → Node → Indexer → Backend → (optional: Orchestrator)
```

### Service Dependencies

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SERVICE STARTUP ORDER                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Caddy (immediate)                                                           │
│    ↓                                                                         │
│  PostgreSQL (immediate, wait for pg_isready)                                 │
│    ↓                                                                         │
│  Migrate DB/role names (one-time: mirage → mirage_indexer, etc.)             │
│    ↓                                                                         │
│  Ensure DBs + roles (mirage_indexer, mirage_backend, mirage_indexer_ro)      │
│    ↓                                                                         │
│  init_backend_schema + deploy migrations                                     │
│    ↓                                                                         │
│  Node (immediate, wait for RPC http://127.0.0.1:26657/status)               │
│    ↓                                                                         │
│  Indexer (after Node RPC ready)                                              │
│    ↓                                                                         │
│  Backend (after Node RPC ready)                                              │
│    ↓                                                                         │
│  Orchestrator (if binary exists)                                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Graceful Shutdown

The entrypoint handles SIGTERM/SIGINT:

```bash
cleanup() {
    echo "Received shutdown signal, gracefully stopping services..."
    
    # Stop orchestrator
    pkill -TERM -f "blockchain/bin/orchestrator"
    sleep 1
    
    # Stop node (with timeout for block completion)
    pkill -TERM -f "miraged start"
    for i in $(seq 1 30); do
        if ! pgrep -f "miraged start"; then break; fi
        sleep 1
    done
    
    # Force kill if still running
    pkill -KILL -f "miraged start"
    
    # Stop PostgreSQL
    pg_ctlcluster 16 main stop -m fast
}
trap cleanup SIGTERM SIGINT
```

---

## Service Orchestration

### tmux Windows

All services run in a tmux session named `mirage`:

```bash
tmux new-session -d -s mirage -n caddy
tmux new-window -t mirage -n postgres
tmux new-window -t mirage -n node
tmux new-window -t mirage -n indexer
tmux new-window -t mirage -n backend
tmux new-window -t mirage -n orchestrator # Optional
tmux new-window -t mirage -n status
```

Operators can attach and switch windows:

```bash
# Attach to session
ssh -t user@host 'docker exec -it mirage tmux attach -t mirage'

# Inside tmux:
# Ctrl-b 0  → caddy window
# Ctrl-b 1  → postgres window
# Ctrl-b 2  → node window
# Ctrl-b n  → next window
# Ctrl-b p  → previous window
```

### Log Rotation

All services use `cronolog` for date-based log rotation:

```bash
# Node logs
$BIN start --home "$NODE_HOME" 2>&1 | tee >(cronolog "$LOGS_DIR/node/miraged-%Y-%m-%d.log")

# Backend logs (via gunicorn config)
# Indexer logs (via Python logging)
# Caddy logs (via cronolog)
```

Logs are stored in `~/.mirage/logs/<component>/`:

```
~/.mirage/logs/
├── node/miraged-2026-01-21.log
├── indexer/indexer-2026-01-21.log
├── backend/backend-2026-01-21.log
├── postgres/postgres-2026-01-21.log
├── caddy/caddy-2026-01-21.log
├── orchestrator/orchestrator-2026-01-21.log
└── deploy/entrypoint-2026-01-21.log
```

---

## Configuration Management

### Environment Files

Configuration is stored in `~/.mirage/env/`:

| File | Purpose |
|------|---------|
| `node.env` | MONIKER, DOMAIN, PERSISTENT_PEERS, PEX_ENABLED |
| `backend.env` | Backend settings + DB URLs (INDEXER_DB_RO_URL, BACKEND_DB_URL) |
| `indexer.env` | Indexer settings + DB URLs (INDEXER_DB_URL, INDEXER_DB_RO_URL, BACKEND_DB_URL) |
| `secrets.env` | Sensitive values (excluded from git) |
| `orchestrator.env` | ORCHESTRATOR_ENABLED, Solana RPC URL |

**Critical DB variables (must be set):**

| Variable | Canonical Location | Used By |
|----------|-------------------|---------|
| `INDEXER_DB_URL` | `indexer.env` | Indexer (read-write to `mirage_indexer`), migration scripts |
| `INDEXER_DB_RO_URL` | `indexer.env` + `backend.env` | Backend (read-only access to `mirage_indexer` via `mirage_indexer_ro` role) |
| `BACKEND_DB_URL` | `backend.env` + `indexer.env` | Backend (read-write to `mirage_backend` DB) |

All env files are loaded in order (`backend.env`, `indexer.env`, `secrets.env`, …) via `set -a; . file; set +a`. If a variable appears in multiple files, the **last file loaded wins**. The env sync mechanism (`_helpers.sync_all`) ensures template defaults are applied for any missing keys, but **never overwrites** user-set values. The entrypoint enforces that all three DB URLs are present — the container will fail to start if any are missing.

### Template Rendering

Configuration files are rendered from templates:

```bash
python3 render_template.py templates/node/config.toml ~/.mirage/node/config/config.toml
```

Templates use Python's string.Template with environment variable substitution:

```toml
# templates/node/config.toml
moniker = "$MONIKER"
[p2p]
persistent_peers = "$PERSISTENT_PEERS"
pex = $PEX_ENABLED
max_num_inbound_peers = $MAX_INBOUND_PEERS
```

### Deploy Migrations

The `deploy/migrations/` module handles configuration evolution:

```python
# v1_8_0_economics.py - Add new economic parameters
# v1_9_0_indexer_env_rename.py - Rename env vars
# v1_9_0_p2p_rate_limiting.py - Enable P2P rate limits
# v1_21_10_migrate_backend_db.py - One-time data migration from indexer → backend DB
```

Migrations run automatically on startup. Each migration runs once and is tracked in `~/.mirage/env/.migrations`. On fresh deployments (no existing data), all existing migrations are skipped. If a migration fails, the entrypoint aborts immediately (fail-fast).

---

## HTTPS and TLS

### Automatic HTTPS

When DOMAIN is set, Caddy automatically obtains TLS certificates from Let's Encrypt:

```bash
# Run inside container
docker exec mirage python3 /opt/mirage/deploy/setup_letsencrypt.py --domain=mirage.vote
```

This script:
1. Updates DOMAIN in node.env (persisted)
2. Renders HTTPS Caddyfile
3. Reloads Caddy
4. Caddy obtains certificate automatically

### Caddyfile Template

```caddyfile
# HTTP-only (default)
:80 {
    root * /opt/mirage/web/frontend/build
    file_server
    handle /api/* {
        reverse_proxy 127.0.0.1:5000
    }
}

# HTTPS (after setup_letsencrypt.py)
mirage.vote {
    root * /opt/mirage/web/frontend/build
    file_server
    handle /api/* {
        reverse_proxy 127.0.0.1:5000
    }
}
www.mirage.vote {
    redir https://mirage.vote{uri}
}
```

### Certificate Persistence

Caddy stores certificates in `~/.caddy` (volume-mounted from host):

```bash
docker run ... -v "$HOME/.caddy:/root/.local/share/caddy" ...
```

Certificates persist across container restarts.

---

## Validator Operations

### Creating a Validator

The `create_validator.sh` script stakes tokens and registers the validator:

```bash
# Run automatically during --init, or manually:
docker exec -e MONIKER="my-validator" mirage bash /opt/mirage/deploy/create_validator.sh
```

Script flow:
1. Check if validator already exists (skip if so)
2. Query account balance
3. Calculate stake amount (95% of balance)
4. Submit `create-validator` transaction

### Consensus Key Derivation

Consensus keys are derived from the mnemonic using a deterministic path:

```python
# derive_consensus_key.py
def derive_consensus_key(mnemonic: str, index: int = 0):
    # BIP44 path: m/44'/118'/0'/0/{index}
    # Generate Ed25519 key for CometBFT consensus
    # Output: priv_validator_key.json
```

The `MIRAGE_DERIVATION_INDEX` environment variable allows multiple validators from one mnemonic (different indices).

### Validator Mode

When `priv_validator_key.json` exists, validator mode is enabled:

```bash
if [ -f "$NODE_HOME/config/priv_validator_key.json" ]; then
    bash "$ROOT_DIR/deploy/enable_validator_mode.sh"
fi
```

This script applies validator-specific configurations:
- Enables double-sign protection
- Configures priority mempool
- Sets appropriate gas prices

---

## Monitoring and Logging

### Status Dashboard

A unified status dashboard runs in the `status` tmux window:

```python
# scripts/status_dashboard.py
# Displays:
# - Node sync status (catching up, latest height)
# - Validator status (bonded, jailed, voting power)
# - Service health (backend, indexer, postgres)
# - Recent blocks and transactions
```

### Log Access

```bash
# Follow all logs
ssh user@host 'docker logs -f mirage'

# Follow specific service
ssh user@host 'docker exec mirage tail -f ~/.mirage/logs/node/miraged-$(date +%Y-%m-%d).log'

# View recent indexer logs
ssh user@host 'docker exec mirage tail -100 ~/.mirage/logs/indexer/indexer-$(date +%Y-%m-%d).log'
```

### Health Checks

The stability check in `deploy.sh` ensures the container is healthy:

```bash
for i in $(seq 1 60); do
    st=$(docker inspect -f "{{.State.Status}}" mirage)
    if [ "$st" = "running" ]; then
        if docker exec mirage echo ready; then
            consec=$((consec+1))
            if [ "$consec" -ge 3 ]; then
                echo "Container is stable!"
                break
            fi
        fi
    fi
    sleep 1
done
```

---

## Common Operations

### Updating a Node

```bash
# From repo root
./scripts/deploy_all_prod.sh --update
# Or for a single node:
deploy/deploy.sh root@mirage.vote --update
```

### Viewing Logs

```bash
# Attach to tmux (interactive)
ssh -t root@mirage.vote 'docker exec -it mirage tmux attach -t mirage'

# Quick log check
ssh root@mirage.vote 'docker logs --tail 100 mirage'

# Specific component
ssh root@mirage.vote 'docker exec mirage tail -f ~/.mirage/logs/indexer/indexer-*.log'
```

### Restarting a Service

```bash
# Restart entire container
ssh root@mirage.vote 'docker restart mirage'

# Restart specific service (inside tmux)
# 1. Attach to tmux
# 2. Navigate to service window (Ctrl-b <number>)
# 3. Kill current process (Ctrl-c)
# 4. Start again (up arrow, enter)
```

### Checking Validator Status

```bash
ssh root@mirage.vote 'docker exec mirage /opt/mirage/blockchain/bin/miraged q staking validators --home ~/.mirage/node'
```

### Unjailing a Validator

```bash
ssh root@mirage.vote 'docker exec mirage bash /opt/mirage/scripts/unjail_validator.sh'
```

### Manual Database Query

```bash
ssh root@mirage.vote 'docker exec mirage psql -U mirage -d mirage -c "SELECT COUNT(*) FROM posts"'
```

---

## Troubleshooting

### Container Won't Start

1. Check Docker logs:
   ```bash
   docker logs mirage
   ```

2. Check for missing keys:
   ```bash
   ls ~/.mirage/node/config/priv_validator_key.json
   ```

3. Check environment files:
   ```bash
   cat ~/.mirage/env/node.env
   ```

### Node Not Syncing

1. Check peer connectivity:
   ```bash
   docker exec mirage curl -s http://127.0.0.1:26657/net_info | jq '.result.n_peers'
   ```

2. Check persistent peers configuration:
   ```bash
   grep persistent_peers ~/.mirage/node/config/config.toml
   ```

3. Check if catching up:
   ```bash
   docker exec mirage curl -s http://127.0.0.1:26657/status | jq '.result.sync_info'
   ```

### Indexer Errors

1. Check PostgreSQL is running:
   ```bash
   docker exec mirage pg_isready -h 127.0.0.1 -p 5432
   ```

2. Check database connection:
   ```bash
   docker exec mirage psql -U mirage -d mirage -c "SELECT 1"
   ```

3. Check indexer logs:
   ```bash
   docker exec mirage tail -100 ~/.mirage/logs/indexer/indexer-*.log
   ```

### Backend 502 Errors

1. Check backend is running:
   ```bash
   docker exec mirage curl -s http://127.0.0.1:5000/api/get_chain_config
   ```

2. Check Caddy proxy config:
   ```bash
   docker exec mirage cat /etc/caddy/Caddyfile
   ```

3. Check backend logs:
   ```bash
   docker exec mirage tail -100 ~/.mirage/logs/backend/backend-*.log
   ```

### HTTPS Certificate Issues

1. Check domain configuration:
   ```bash
   grep DOMAIN ~/.mirage/env/node.env
   ```

2. Check Caddy logs for ACME errors:
   ```bash
   docker exec mirage tail -100 ~/.mirage/logs/caddy/caddy-*.log
   ```

3. Verify DNS points to server:
   ```bash
   dig +short mirage.vote
   ```

4. Re-run HTTPS setup:
   ```bash
   docker exec mirage python3 /opt/mirage/deploy/setup_letsencrypt.py --domain=mirage.vote
   ```

---

## Security Considerations

### Key Storage

- **Consensus key** (`priv_validator_key.json`) stored on persistent volume
- **Account key** stored in keyring (test backend) on persistent volume
- **Mnemonic** never stored, only used during `--init`

### Network Exposure

- Port 80/443: Public (web interface)
- Port 26656: Public (P2P networking)
- Port 26657: Optional external access (RPC)
- Port 5000: Internal only (backend)
- Port 5432: Internal only (PostgreSQL)
- Port 9090: Internal only (gRPC)

### Host-Side Rate Limiting

The deploy script configures iptables rate limiting:

```bash
# enable_rate_limiting.sh
iptables -A INPUT -p tcp --dport 26656 -m state --state NEW -m recent --set
iptables -A INPUT -p tcp --dport 26656 -m state --state NEW -m recent --update --seconds 60 --hitcount 10 -j DROP
```

This prevents P2P connection flood attacks.

---

## Production Deployment

### Multi-Node Deploy

```bash
# Deploy to all production nodes
./scripts/deploy_all_prod.sh --update

# This script:
# 1. Builds image once
# 2. Pushes to registry
# 3. Deploys to each host in sequence
```

### Hosts Configuration

Production hosts are hard-coded in `deploy_all_prod.sh`:

```bash
HOSTS=(
    "mirage.vote"
    "<val3>"
    "<val4>"
    "mirage.talk"
)
```

### Post-Deploy Verification

After deployment:
1. Check validator is signing blocks
2. Verify sync status
3. Test API endpoints
4. Verify HTTPS certificates
