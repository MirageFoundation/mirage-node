#!/usr/bin/env bash
set -euo pipefail

# Fully automated Hermes IBC relayer setup for Mirage <-> Osmosis
# Usage: ./setup_hermes_relayer.sh [--create-new-channel]
#
# Options:
#   --create-new-channel  Allow creation of a NEW IBC channel (use with caution!)
#
# You will be prompted to enter your 12-word mnemonic (hidden input)
# Data is stored in ~/.mirage/hermes (persisted via Docker volume mount)
#
# NOTE: The tmux hermes window startup code (near end of file) is duplicated
#       in deploy/entrypoint.sh. If you change one, update the other!

HERMES_VERSION="v1.13.3"
HERMES_HOME="${HOME}/.mirage/hermes"
CREATE_NEW_CHANNEL=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --create-new-channel)
            CREATE_NEW_CHANNEL=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--create-new-channel]"
            echo ""
            echo "Options:"
            echo "  --create-new-channel  Allow creation of a NEW IBC channel"
            echo "                        (Only use if no valid channel exists!)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Use --help for usage information" >&2
            exit 1
            ;;
    esac
done


# Verify persistence (hermes dir is inside ~/.mirage which is always mounted)
echo "==> Verifying hermes directory..."
mkdir -p "$HERMES_HOME"
echo "    ✓ Hermes home: $HERMES_HOME"

# Read mnemonic securely
echo -n "Enter 12-word mnemonic: "
read -rs MNEMONIC
echo ""

WORD_COUNT=$(echo "$MNEMONIC" | wc -w)
if [ "$WORD_COUNT" -ne 12 ]; then
    echo "ERROR: Expected 12-word mnemonic, got $WORD_COUNT words" >&2
    exit 1
fi
echo "==> Mnemonic accepted (12 words)"

# Install or upgrade Hermes
echo "==> Checking Hermes ${HERMES_VERSION}..."
INSTALLED_VERSION=$(hermes version 2>&1 | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo "")
if [ "$INSTALLED_VERSION" != "$HERMES_VERSION" ]; then
    echo "    Installing Hermes ${HERMES_VERSION} (was: ${INSTALLED_VERSION:-not installed})..."
    cd /tmp
    curl -sL "https://github.com/informalsystems/hermes/releases/download/${HERMES_VERSION}/hermes-${HERMES_VERSION}-x86_64-unknown-linux-gnu.tar.gz" -o hermes.tar.gz
    tar -xzf hermes.tar.gz
    mv -f hermes /usr/local/bin/
    chmod +x /usr/local/bin/hermes
    rm hermes.tar.gz
    echo "    Installed: $(hermes version 2>&1 | head -1)"
else
    echo "    Already at ${HERMES_VERSION}"
fi

# Create minimal config for key derivation
echo "==> Deriving relayer addresses..."
mkdir -p "$HERMES_HOME/keys"

cat > "$HERMES_HOME/config.toml" << 'CONFIG'
[global]
log_level = 'info'

[mode.clients]
enabled = true
refresh = true
misbehaviour = true

[mode.connections]
enabled = false

[mode.channels]
enabled = true

[mode.packets]
enabled = true
clear_interval = 100
clear_on_start = true
tx_confirmation = false

[rest]
enabled = false
host = '127.0.0.1'
port = 3000

[telemetry]
enabled = false
host = '127.0.0.1'
port = 3001

[[chains]]
id = 'mirage-1'
type = 'CosmosSdk'
rpc_addr = 'http://127.0.0.1:26657'
grpc_addr = 'http://127.0.0.1:9090'
event_source = { mode = 'push', url = 'ws://127.0.0.1:26657/websocket', batch_delay = '500ms' }
rpc_timeout = '10s'
trusted_node = false
account_prefix = 'mirage'
key_name = 'relayer'
key_store_type = 'Test'
store_prefix = 'ibc'
default_gas = 100000
max_gas = 4000000
gas_multiplier = 1.2
max_msg_num = 30
max_tx_size = 180000
clock_drift = '5s'
max_block_time = '30s'
trusting_period = '14days'
trust_threshold = '2/3'
gas_price = { price = 0.025, denom = 'umirage' }
address_type = { derivation = 'cosmos' }

[chains.packet_filter]
policy = 'allow'
list = [['transfer', 'channel-1']]

[[chains]]
id = 'osmosis-1'
type = 'CosmosSdk'
rpc_addr = 'https://rpc.osmosis.zone:443'
grpc_addr = 'https://grpc.osmosis.zone:443'
event_source = { mode = 'push', url = 'wss://rpc.osmosis.zone/websocket', batch_delay = '500ms' }
rpc_timeout = '10s'
trusted_node = false
account_prefix = 'osmo'
key_name = 'relayer'
key_store_type = 'Test'
store_prefix = 'ibc'
default_gas = 300000
max_gas = 10000000
gas_multiplier = 1.3
max_msg_num = 30
max_tx_size = 180000
clock_drift = '5s'
max_block_time = '30s'
trusting_period = '13days'
trust_threshold = '2/3'
gas_price = { price = 0.1, denom = 'uosmo' }
address_type = { derivation = 'cosmos' }

[chains.packet_filter]
policy = 'allow'
list = [['transfer', 'channel-108698']]
CONFIG

# Set key_store_folder to our custom hermes home (variables don't expand in heredoc)
sed -i "s|^\[global\]|\[global\]\nkey_store_folder = '$HERMES_HOME/keys'|" "$HERMES_HOME/config.toml"

# Import keys to derive addresses
MNEMONIC_FILE=$(mktemp)
echo "$MNEMONIC" > "$MNEMONIC_FILE"
trap "rm -f $MNEMONIC_FILE" EXIT

hermes --config "$HERMES_HOME/config.toml" keys delete --chain mirage-1 --key-name relayer >/dev/null 2>&1 || true
hermes --config "$HERMES_HOME/config.toml" keys delete --chain osmosis-1 --key-name relayer >/dev/null 2>&1 || true

hermes --config "$HERMES_HOME/config.toml" keys add --chain mirage-1 --key-name relayer --hd-path "m/44'/118'/0'/0/0" --mnemonic-file "$MNEMONIC_FILE" >/dev/null 2>&1
hermes --config "$HERMES_HOME/config.toml" keys add --chain osmosis-1 --key-name relayer --hd-path "m/44'/118'/0'/0/0" --mnemonic-file "$MNEMONIC_FILE" >/dev/null 2>&1

rm -f "$MNEMONIC_FILE"

MIRAGE_ADDR=$(hermes --config "$HERMES_HOME/config.toml" keys list --chain mirage-1 2>&1 | grep -oE 'mirage1[a-z0-9]+')
OSMO_ADDR=$(hermes --config "$HERMES_HOME/config.toml" keys list --chain osmosis-1 2>&1 | grep -oE 'osmo1[a-z0-9]+')

echo ""
echo "==========================================="
echo "RELAYER ADDRESSES"
echo "==========================================="
echo ""
echo "  Mirage:  $MIRAGE_ADDR"
echo "  Osmosis: $OSMO_ADDR"
echo ""
echo "==========================================="
echo ""
echo "These addresses need to be funded before proceeding:"
echo "  - Mirage:  at least 1 MIRAGE"
echo "  - Osmosis: at least 100 OSMO"
echo ""
echo -n "Continue with setup? [y/N]: "
read -r CONFIRM
if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    echo "Aborted."
    exit 0
fi

# Check balances
echo ""
echo "==> Checking balances..."

check_balance() {
    local chain=$1
    local denom=$2
    local result
    result=$(hermes --config "$HERMES_HOME/config.toml" keys balance --chain "$chain" --key-name relayer 2>&1 | grep -oE "[0-9]+ $denom" | awk '{print $1}' || echo "0")
    echo "${result:-0}"
}

MIRAGE_BAL=$(check_balance "mirage-1" "umirage")
OSMO_BAL=$(check_balance "osmosis-1" "uosmo")

echo "    Mirage balance:  $MIRAGE_BAL umirage"
echo "    Osmosis balance: $OSMO_BAL uosmo"

# Wait for funding if needed
MIN_MIRAGE=1000000   # 1 MIRAGE
MIN_OSMO=100000000   # 100 OSMO

if [ "$MIRAGE_BAL" -lt "$MIN_MIRAGE" ] || [ "$OSMO_BAL" -lt "$MIN_OSMO" ]; then
    echo ""
    echo "==========================================="
    echo "WAITING FOR FUNDING"
    echo "==========================================="
    echo "Minimum required:"
    echo "  - Mirage: 1 MIRAGE ($MIN_MIRAGE umirage)"
    echo "  - Osmosis: 100 OSMO ($MIN_OSMO uosmo)"
    echo ""
    echo "Send funds to:"
    echo "  - Mirage:  $MIRAGE_ADDR"
    echo "  - Osmosis: $OSMO_ADDR"
    echo ""
    echo "Checking every 30 seconds... (Ctrl+C to abort)"
    echo "==========================================="
    
    while true; do
        sleep 30
        MIRAGE_BAL=$(check_balance "mirage-1" "umirage")
        OSMO_BAL=$(check_balance "osmosis-1" "uosmo")
        echo "    Mirage: $MIRAGE_BAL umirage | Osmosis: $OSMO_BAL uosmo"
        
        if [ "$MIRAGE_BAL" -ge "$MIN_MIRAGE" ] && [ "$OSMO_BAL" -ge "$MIN_OSMO" ]; then
            echo "==> Funding complete!"
            break
        fi
    done
fi

# Check if channel already exists or create new one
echo ""
echo "==> Checking for existing IBC channel to Osmosis..."

# Query existing channels and check each one's counterparty
CHANNEL_LIST=$(hermes --config "$HERMES_HOME/config.toml" query channels --chain mirage-1 2>&1 | grep -oE 'channel-[0-9]+' || true)
MIRAGE_CHANNEL=""
OSMOSIS_CHANNEL=""

for chan in $CHANNEL_LIST; do
    # Query channel details to get connection and counterparty channel
    CHAN_INFO=$(hermes --config "$HERMES_HOME/config.toml" query channel end --chain mirage-1 --port transfer --channel "$chan" 2>&1 || true)
    
    # Skip if channel not in Open state
    if ! echo "$CHAN_INFO" | grep -q "state: Open"; then
        continue
    fi
    
    # Extract connection ID from channel info
    CONN_ID=$(echo "$CHAN_INFO" | grep -oE 'connection-[0-9]+' | head -1 || echo "")
    if [ -z "$CONN_ID" ]; then
        continue
    fi
    
    # Query connection to get client ID
    CONN_INFO=$(hermes --config "$HERMES_HOME/config.toml" query connection end --chain mirage-1 --connection "$CONN_ID" 2>&1 || true)
    CLIENT_ID=$(echo "$CONN_INFO" | grep -oE '07-tendermint-[0-9]+' | head -1 || echo "")
    if [ -z "$CLIENT_ID" ]; then
        continue
    fi
    
    # Query client state to get counterparty chain ID
    CLIENT_INFO=$(hermes --config "$HERMES_HOME/config.toml" query client state --chain mirage-1 --client "$CLIENT_ID" 2>&1 || true)
    if echo "$CLIENT_INFO" | grep -q "osmosis-1"; then
        MIRAGE_CHANNEL="$chan"
        # Extract counterparty channel ID
        OSMOSIS_CHANNEL=$(echo "$CHAN_INFO" | grep -oE 'channel-[0-9]+' | tail -1 || echo "")
        break
    fi
done

if [ -n "$MIRAGE_CHANNEL" ]; then
    echo "    Found existing channel: $MIRAGE_CHANNEL"
    echo "    Counterparty on Osmosis: $OSMOSIS_CHANNEL"
else
    echo ""
    echo "    ╔══════════════════════════════════════════════════════════════╗"
    echo "    ║                      NO CHANNEL FOUND                        ║"
    echo "    ╚══════════════════════════════════════════════════════════════╝"
    echo ""
    
    if [ "$CREATE_NEW_CHANNEL" != "true" ]; then
        echo "    No IBC channel to Osmosis exists on this chain."
        echo ""
        echo "    If this is the FIRST TIME setting up IBC, run with:"
        echo "        $0 --create-new-channel"
        echo ""
        echo "    If a channel SHOULD exist, check:"
        echo "        1. Is the relayer wallet funded?"
        echo "        2. Did the IBC client expire? (trusting period is ~14 days)"
        echo "        3. Run 'hermes --config ~/.mirage/hermes/config.toml query channels --chain mirage-1' to debug"
        echo ""
        echo "    ⚠️  DO NOT create a new channel if one already exists!"
        echo "       This will create DUPLICATE channels and break the Osmosis asset list."
        echo ""
        exit 1
    fi
    
    echo "    ╔══════════════════════════════════════════════════════════════╗"
    echo "    ║                    ⚠️  WARNING ⚠️                             ║"
    echo "    ║                                                              ║"
    echo "    ║  You are about to CREATE A NEW IBC CHANNEL.                  ║"
    echo "    ║                                                              ║"
    echo "    ║  This should ONLY be done if:                                ║"
    echo "    ║    • This is the first-ever IBC setup for Mirage             ║"
    echo "    ║    • The previous channel's clients have EXPIRED             ║"
    echo "    ║                                                              ║"
    echo "    ║  Creating duplicate channels will:                           ║"
    echo "    ║    • Break the Osmosis asset list integration                ║"
    echo "    ║    • Require updating the channel in osmosis-labs/assetlists ║"
    echo "    ║    • Cause user confusion                                    ║"
    echo "    ║                                                              ║"
    echo "    ╚══════════════════════════════════════════════════════════════╝"
    echo ""
    read -p "    Type 'CREATE' to proceed with new channel creation: " CONFIRM_CREATE
    if [ "$CONFIRM_CREATE" != "CREATE" ]; then
        echo "    Aborted."
        exit 1
    fi
    
    echo ""
    echo "==> Creating new IBC channel..."
    echo "    This will take 2-3 minutes and cost gas on both chains."
    echo ""
    
    CREATE_OUTPUT=$(hermes --config "$HERMES_HOME/config.toml" create channel --a-chain mirage-1 --b-chain osmosis-1 --a-port transfer --b-port transfer --new-client-connection --yes 2>&1)
    echo "$CREATE_OUTPUT"
    
    if echo "$CREATE_OUTPUT" | grep -q "SUCCESS"; then
        echo ""
        echo "==> IBC channel created successfully!"
        # Extract channel IDs from creation output
        MIRAGE_CHANNEL=$(echo "$CREATE_OUTPUT" | grep -oE "channel-[0-9]+" | head -1 || echo "channel-?")
        OSMOSIS_CHANNEL=$(echo "$CREATE_OUTPUT" | grep -oE "channel-[0-9]+" | tail -1 || echo "channel-?")
        echo ""
        echo "    ╔══════════════════════════════════════════════════════════════╗"
        echo "    ║  NEW CHANNEL CREATED - ACTION REQUIRED                       ║"
        echo "    ╠══════════════════════════════════════════════════════════════╣"
        echo "    ║  Mirage channel:  $MIRAGE_CHANNEL"
        echo "    ║  Osmosis channel: $OSMOSIS_CHANNEL"
        echo "    ║                                                              ║"
        echo "    ║  You MUST update the Osmosis asset list:                     ║"
        echo "    ║  1. Fork github.com/osmosis-labs/assetlists                  ║"
        echo "    ║  2. Update osmosis-1/osmosis.zone_assets.json                ║"
        echo "    ║  3. Change path to: transfer/$OSMOSIS_CHANNEL/umirage"
        echo "    ║  4. Submit PR                                                ║"
        echo "    ╚══════════════════════════════════════════════════════════════╝"
        echo ""
    else
        echo ""
        echo "ERROR: Failed to create IBC channel. Check logs above."
        exit 1
    fi
fi

# Verify we have channel numbers
if [ -z "$MIRAGE_CHANNEL" ] || [ -z "$OSMOSIS_CHANNEL" ]; then
    echo "WARNING: Could not detect channel numbers automatically."
    echo "         Check 'hermes --config ~/.mirage/hermes/config.toml query channels --chain mirage-1' manually."
    MIRAGE_CHANNEL="${MIRAGE_CHANNEL:-channel-?}"
    OSMOSIS_CHANNEL="${OSMOSIS_CHANNEL:-channel-?}"
fi
# Start the relayer
echo ""
echo "==> Starting Hermes relayer..."

# Kill any existing hermes
pkill -f "hermes start" 2>/dev/null || true
sleep 1

HERMES_LOG_DIR="$HOME/.mirage/logs/hermes"
mkdir -p "$HERMES_LOG_DIR"

if tmux has-session -t mirage 2>/dev/null; then
    # Docker mode with tmux session available - use tmux window
    echo "    Using tmux session 'mirage'..."
    SESSION="mirage"
    
    # Kill hermes window if it exists, then recreate
    tmux kill-window -t "$SESSION:hermes" 2>/dev/null || true
    
    # Create hermes window with the standard command from entrypoint
    tmux new-window -t "$SESSION" -n hermes -c /opt/mirage
    tmux send-keys -t "$SESSION:hermes" "hermes --config \"$HERMES_HOME/config.toml\" start 2>&1 | tee >(cronolog \"$HERMES_LOG_DIR/hermes-%Y-%m-%d.log\")" C-m
    
    sleep 2
    if pgrep -f "hermes start" >/dev/null; then
        echo "    Hermes is running in tmux window 'hermes'"
        SERVICE_MODE="tmux"
    else
        echo "ERROR: Hermes failed to start. Check tmux window or logs."
        exit 1
    fi
else
    # Docker mode without tmux - suggest restart
    echo ""
    echo "    ╔══════════════════════════════════════════════════════════════╗"
    echo "    ║  Hermes configured! Restart container to start relayer.      ║"
    echo "    ╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "    Run: docker restart mirage"
    echo ""
    SERVICE_MODE="pending"
fi

echo ""
echo "==========================================="
echo "SETUP COMPLETE"
echo "==========================================="
echo ""
echo "IBC Channel:"
echo "  Mirage:  $MIRAGE_CHANNEL (transfer)"
echo "  Osmosis: $OSMOSIS_CHANNEL (transfer)"
echo ""
case "$SERVICE_MODE" in
    tmux)
        echo "Relayer running in tmux window 'hermes':"
        echo "  View:    tmux select-window -t mirage:hermes"
        echo "  Logs:    tail -f ~/.mirage/logs/hermes/hermes-\$(date -u +%Y-%m-%d).log"
        echo "  Restart: tmux send-keys -t mirage:hermes C-c && sleep 1 && tmux send-keys -t mirage:hermes 'hermes --config ~/.mirage/hermes/config.toml start' C-m"
        ;;
    pending)
        echo "Relayer configured but NOT running."
        echo "  Start:   docker restart mirage"
        ;;
esac
echo ""
echo "To test IBC transfer from Mirage to Osmosis:"
echo "  miraged tx ibc-transfer transfer transfer $MIRAGE_CHANNEL <OSMO_ADDRESS> 1000000umirage --from <KEY> --chain-id mirage-1 --fees 50000umirage"
echo ""
echo "==========================================="