# Mirage Infrastructure Reference (Public)

This document is written to be safe for public sharing. It does not include hard-coded server IPs, SSH shortcuts, or specific validator addresses.

### Assumptions

- You are on the machine that runs your Mirage node, or you have access to it through your own normal admin workflow.
- Your services run inside a Docker container (default name: `mirage`).

### Variables used below

Set these to match your environment:

```bash
CONTAINER="${CONTAINER:-mirage}"
NODE_DOMAIN="<YOUR_NODE_DOMAIN>"
```

### Services inside the container

Many deployments run these services together:

- **Web server**: Caddy (HTTP/HTTPS)
- **Node**: `miraged` (CometBFT + Cosmos SDK application)
- **Indexer**: Python process consuming chain data
- **Backend API**: Python web service serving `/api`

### Useful ports

Ports are deployment-dependent, but commonly:

| Service | Port | Notes |
|---------|------|------|
| HTTP | 80 | Web entrypoint |
| HTTPS | 443 | Web entrypoint |
| CometBFT RPC | 26657 | JSON-RPC, `/status`, `/block`, etc. |
| P2P | 26656 | Node networking |
| Cosmos REST API | 1317 | If enabled |
| gRPC | 9090 | If enabled |

### Quick health checks (from your own machine)

```bash
curl -I "https://${NODE_DOMAIN}/"
curl -I "https://${NODE_DOMAIN}/api/get_parameters"
```

### Container checks (run on the host that runs Docker)

```bash
docker ps -a

docker exec "${CONTAINER}" ps aux | grep -E "caddy|python|miraged"

docker exec "${CONTAINER}" tmux list-panes -t mirage || true
docker exec "${CONTAINER}" tmux capture-pane -t mirage:0 -p | tail -50 || true
```

### Common file locations (inside the container)

| Path | Description |
|------|-------------|
| `/opt/mirage/` | Application root |
| `/opt/mirage/blockchain/bin/miraged` | Blockchain binary |
| `/opt/mirage/web/frontend/` | Frontend build |
| `/opt/mirage/web/backend/` | Backend API |
| `/opt/mirage/indexer/` | Transaction indexer |
| `/opt/mirage/deploy/` | Deployment scripts |
| `/opt/mirage/scripts/` | Utility scripts |
| `/etc/caddy/Caddyfile` | Caddy configuration |

### Notes

- If you publish public docs, avoid embedding infrastructure IPs, SSH commands, validator addresses, or secrets.


