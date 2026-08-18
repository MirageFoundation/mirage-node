#!/usr/bin/env bash
# Print node_id@host:26656 for a running local or remote mirage container.
# Used to publish a network-manifest generation, not by the installer.
set -euo pipefail

CONTAINER="${CONTAINER:-mirage}"
if ! docker inspect "$CONTAINER" --format '{{.State.Status}}' 2>/dev/null | grep -qx running; then
  echo "ERROR: container $CONTAINER is not running" >&2
  exit 1
fi

status=$(docker exec "$CONTAINER" curl -fsS --max-time 5 http://127.0.0.1:26657/status)
node_id=$(echo "$status" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["node_info"]["id"])')
listen=$(echo "$status" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["node_info"]["listen_addr"])')

host=""
if docker exec "$CONTAINER" test -f /root/.mirage/env/node.env; then
  domain=$(docker exec "$CONTAINER" grep -E '^DOMAIN=' /root/.mirage/env/node.env | cut -d= -f2- | tr -d '"' | tr -d "'" || true)
  if [[ -n "$domain" ]]; then
    host="$domain"
  fi
fi
if [[ -z "$host" ]]; then
  ext=$(docker exec "$CONTAINER" grep -E '^EXTERNAL_ADDRESS=' /root/.mirage/env/node.env 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
  # tcp://1.2.3.4:26656 or tcp://[v6]:26656
  host=$(echo "$ext" | sed -E 's#^tcp://##; s#:26656$##; s#^\[##; s#\]$##')
fi
if [[ -z "$host" ]]; then
  host=$(echo "$listen" | sed -E 's#^tcp://##; s#:26656$##')
fi
if [[ -z "$node_id" || -z "$host" ]]; then
  echo "ERROR: could not derive node_id@host from status (id=$node_id host=$host listen=$listen)" >&2
  exit 1
fi
echo "${node_id}@${host}:26656"
