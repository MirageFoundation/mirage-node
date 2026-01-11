#!/usr/bin/env bash
set -euo pipefail

# Enable validator mode safely by:
# 1) Setting priv_validator_state.json to head+5
# 2) Restoring priv_validator_key.json (from disabled file if present)
# 3) Restarting the node process (when run with --restart)

NODE_HOME="${MIRAGE_NODE_HOME:-$HOME/.mirage/main}"
LOGS_DIR="${HOME}/.mirage/logs"
PV_STATE="$NODE_HOME/data/priv_validator_state.json"
PV_KEY="$NODE_HOME/config/priv_validator_key.json"
PV_KEY_DISABLED="$NODE_HOME/config/priv_validator_key.json.disabled"
RPC_URL="${RPC_URL:-http://127.0.0.1:26657}"

TARGET_HEIGHT_ARG="${1:-}"
RESTART_AFTER="${2:-}" # pass --restart to restart miraged

get_current_height() {
  curl -s "$RPC_URL/status" | jq -r '.result.sync_info.latest_block_height' 2>/dev/null
}

main() {
  mkdir -p "$NODE_HOME/data" "$NODE_HOME/config"

  local current_height target_height
  if [[ -n "$TARGET_HEIGHT_ARG" && "$TARGET_HEIGHT_ARG" =~ ^[0-9]+$ ]]; then
    target_height="$TARGET_HEIGHT_ARG"
  else
    current_height="$(get_current_height)"
    if [ -z "$current_height" ] || [ "$current_height" = "null" ] || ! [[ "$current_height" =~ ^[0-9]+$ ]]; then
      echo "ERROR: Could not determine current height from RPC ($RPC_URL)" >&2
      exit 1
    fi
    target_height=$((current_height + 5))
  fi

  cat > "$PV_STATE" <<EOF
{
  "height": "$target_height",
  "round": 0,
  "step": 0,
  "signature": null,
  "signbytes": null
}
EOF

  # Restore validator key from disabled file if present
  if [ -f "$PV_KEY_DISABLED" ]; then
    echo "Restoring validator key from disabled file"
    mv -f "$PV_KEY_DISABLED" "$PV_KEY"
  else
    echo "WARNING: No validator key available to restore" >&2
  fi
  if [ -f "$PV_KEY" ]; then
    chmod 600 "$PV_KEY"
  fi

  # Create marker file to prevent re-disabling on container restart
  touch "$NODE_HOME/.validator_auto_enabled"
  
  if [ "$RESTART_AFTER" = "--restart" ]; then
    # Restart the node process inside tmux pane 0
    SESSION="${SESSION:-mirage}"
    BIN="${BIN:-/opt/mirage/blockchain/miraged}"
    NODE_HOME="${NODE_HOME:-$HOME/.mirage/main}"
    
    # Kill miraged and tail processes
    tmux send-keys -t "$SESSION:mirage.0" C-c
    sleep 1
    if pgrep -f "miraged start" >/dev/null 2>&1; then
      pkill -f "miraged start"
    fi
    if pgrep -f "tail.*miraged.log" >/dev/null 2>&1; then
      pkill -f "tail.*miraged.log"
    fi
    sleep 1
    
    # Clear the pane and restart with full command (matching entrypoint)
    tmux send-keys -t "$SESSION:mirage.0" C-l
    tmux send-keys -t "$SESSION:mirage.0" "bash -lc 'export MIRAGE_NODE_HOME=\"$NODE_HOME\"; mkdir -p \"$LOGS_DIR/node\"; setsid nohup $BIN start >> \"$LOGS_DIR/node/miraged.log\" 2>&1 & echo PID:\$! && sleep 1 && tail -n +1 -F \"$LOGS_DIR/node/miraged.log\"'" C-m
  fi

  echo "Validator enabled at height $target_height."
}

main "$@"

