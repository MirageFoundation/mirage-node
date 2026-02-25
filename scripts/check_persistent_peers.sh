#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="\$HOME/.mirage/env/node.env"
TIMEOUT=5

DEFAULT_SERVERS=(
  "root@159.203.114.27"
  "root@64.23.136.132"
  "root@146.190.108.140"
  "root@139.59.9.96"
)

SERVERS=("$@")
if [ "${#SERVERS[@]}" -eq 0 ]; then
  SERVERS=("${DEFAULT_SERVERS[@]}")
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required" >&2
  exit 1
fi

ERRORS=0

for server in "${SERVERS[@]}"; do
  echo ""
  echo "==> Server: $server"

  if ! peers=$(ssh "$server" "grep '^PERSISTENT_PEERS=' $ENV_FILE | head -1 | cut -d= -f2-"); then
    echo "    ERROR: Failed to read PERSISTENT_PEERS" >&2
    ERRORS=$((ERRORS + 1))
    continue
  fi

  if [ -z "$peers" ]; then
    echo "    ERROR: PERSISTENT_PEERS is empty" >&2
    ERRORS=$((ERRORS + 1))
    continue
  fi

  echo "    PERSISTENT_PEERS=$peers"
  updated_peers=""
  needs_update=false

  IFS=',' read -r -a peer_list <<< "$peers"
  for peer in "${peer_list[@]}"; do
    if ! echo "$peer" | grep -q '@' || ! echo "$peer" | grep -q ':26656'; then
      echo "    ERROR: Invalid peer entry: $peer" >&2
      ERRORS=$((ERRORS + 1))
      continue
    fi

    node_id="${peer%@*}"
    addr="${peer#*@}"
    peer_ip="${addr%:26656}"

    if ! status=$(ssh "$server" "curl -sfS --max-time $TIMEOUT http://${peer_ip}:26657/status" 2>/dev/null); then
      echo "    FAIL  $peer (RPC unreachable)"
      ERRORS=$((ERRORS + 1))
      continue
    fi

    remote_id=$(echo "$status" | jq -r '.result.node_info.id // empty')
    if [ -z "$remote_id" ]; then
      echo "    FAIL  $peer (invalid status response)"
      ERRORS=$((ERRORS + 1))
      continue
    fi

    if [ "$remote_id" != "$node_id" ]; then
      echo "    MISMATCH  $peer_ip: config=$node_id actual=$remote_id"
      fixed_peer="${remote_id}@${addr}"

      read -p "    Fix to $fixed_peer? [y/N] " -n 1 -r
      echo
      if [[ $REPLY =~ ^[Yy]$ ]]; then
        peer="$fixed_peer"
        needs_update=true
        echo "    FIXED  $peer"
      else
        echo "    SKIPPED"
        ERRORS=$((ERRORS + 1))
      fi
    else
      echo "    OK    $peer"
    fi

    if [ -n "$updated_peers" ]; then
      updated_peers="$updated_peers,"
    fi
    updated_peers="${updated_peers}${peer}"
  done

  if [ "$needs_update" = true ] && [ -n "$updated_peers" ]; then
    echo "    Updating PERSISTENT_PEERS on $server..."
    ssh "$server" "sed -i 's|^PERSISTENT_PEERS=.*|PERSISTENT_PEERS=$updated_peers|' $ENV_FILE"
    echo "    Done."
  fi
done

echo ""
if [ "$ERRORS" -gt 0 ]; then
  echo "=== $ERRORS issue(s) found ==="
  exit 1
else
  echo "=== All peers verified ==="
fi
