#!/usr/bin/env bash
set -euo pipefail

# Enable validator mode safely by:
# 1) Raising priv_validator_state.json to max(existing, head+5), never lowering
#    it, and skipping the write while catching_up (reported height is not tip)
# 2) Restoring priv_validator_key.json (from disabled file if present)
# 3) Restarting the node process (when run with --restart)

NODE_HOME="$HOME/.mirage/node"
LOGS_DIR="${HOME}/.mirage/logs"
PV_STATE="$NODE_HOME/data/priv_validator_state.json"
PV_KEY="$NODE_HOME/config/priv_validator_key.json"
PV_KEY_DISABLED="$NODE_HOME/config/priv_validator_key.json.disabled"
RPC_URL="${RPC_URL:-http://127.0.0.1:26657}"

TARGET_HEIGHT_ARG="${1:-}"
RESTART_AFTER="${2:-}" # pass --restart to restart miraged

get_status_json() {
  curl -s --max-time 5 "$RPC_URL/status"
}

main() {
  mkdir -p "$NODE_HOME/data" "$NODE_HOME/config"

  local status_json catching current_height target_height existing="" write_state=1
  status_json="$(get_status_json)"
  catching="$(printf '%s' "$status_json" | jq -r '.result.sync_info.catching_up')"
  if [ "$catching" != "true" ] && [ "$catching" != "false" ]; then
    echo "ERROR: Could not determine catching_up from RPC ($RPC_URL): $catching" >&2
    exit 1
  fi

  if [ "$catching" = "true" ]; then
    echo "skipping priv_validator_state overwrite while catching_up"
    write_state=0
  elif [[ -n "$TARGET_HEIGHT_ARG" && "$TARGET_HEIGHT_ARG" =~ ^[0-9]+$ ]]; then
    target_height="$TARGET_HEIGHT_ARG"
  else
    current_height="$(printf '%s' "$status_json" | jq -r '.result.sync_info.latest_block_height')"
    if [ -z "$current_height" ] || [ "$current_height" = "null" ] || ! [[ "$current_height" =~ ^[0-9]+$ ]]; then
      echo "ERROR: Could not determine current height from RPC ($RPC_URL)" >&2
      exit 1
    fi
    target_height=$((current_height + 5))
  fi

  if [ "$write_state" = "1" ] && [ -f "$PV_STATE" ]; then
    existing="$(jq -r '.height // empty' "$PV_STATE")"
    if ! [[ "$existing" =~ ^[0-9]+$ ]]; then
      echo "ERROR: $PV_STATE height is not an integer: $existing" >&2
      exit 1
    fi
    if [ "$existing" -ge "$target_height" ]; then
      echo "keeping existing watermark $existing (refusing to lower to $target_height)"
      write_state=0
      target_height="$existing"
    fi
  fi

  if [ "$write_state" = "1" ]; then
    cat > "$PV_STATE" <<EOF
{
  "height": "$target_height",
  "round": 0,
  "step": 0,
  "signature": null,
  "signbytes": null
}
EOF
  fi

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

  if [ "$RESTART_AFTER" = "--restart" ]; then
    # Restart the node process inside tmux pane 0
    SESSION="${SESSION:-mirage}"
    BIN="${BIN:-/opt/mirage/blockchain/bin/miraged}"
    
    # Kill miraged and tail processes
    tmux send-keys -t "$SESSION:mirage.0" C-c
    sleep 1
    if pgrep -f "miraged start" >/dev/null 2>&1; then
      pkill -f "miraged start"
    fi
    if pgrep -f "tail.*miraged.*log" >/dev/null 2>&1; then
      pkill -f "tail.*miraged.*log"
    fi
    sleep 1
    
    # Clear the pane and restart with full command (matching entrypoint)
    # Use tee + cronolog for live output AND date-based log files
    tmux send-keys -t "$SESSION:mirage.0" C-l
    tmux send-keys -t "$SESSION:mirage.0" "bash -lc 'mkdir -p \"$LOGS_DIR/node\"; $BIN start 2>&1 | tee >(cronolog \"$LOGS_DIR/node/miraged-%Y-%m-%d.log\")'" C-m
  fi

  if [ "$write_state" = "1" ]; then
    echo "Validator enabled at height $target_height."
  elif [ "$catching" = "true" ]; then
    echo "Validator key restored; watermark left unchanged (catching_up)."
  else
    echo "Validator enabled; existing watermark $target_height kept."
  fi
}

main "$@"

