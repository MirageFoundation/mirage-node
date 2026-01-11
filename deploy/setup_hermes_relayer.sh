#!/usr/bin/env bash
set -euo pipefail

# Fully automated Hermes IBC relayer setup for Mirage <-> Osmosis
# Usage: ./setup_hermes_relayer.sh [--create-new-channel]
#
# Options:
#   --create-new-channel  Allow creation of a NEW IBC channel (use with caution!)
#
# You will be prompted to enter your 12-word mnemonic (hidden input)
# Data is stored in ~/.hermes (persisted via Docker volume mount)

HERMES_VERSION="v1.10.4"
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


# Verify volume mount is working (critical for persistence)
echo "==> Verifying ~/.hermes persistence..."
if [ -f /.dockerenv ]; then
    # We're inside a container - check if ~/.hermes is a mount point
    HERMES_DIR="$HOME/.hermes"
    mkdir -p "$HERMES_DIR"
    
    # Write a test file and check if it persists on the host
    TEST_FILE="$HERMES_DIR/.persistence_test_$$"
    echo "test" > "$TEST_FILE"
    
    # Check mount info
    if ! findmnt -n "$HERMES_DIR" >/dev/null 2>&1; then
        echo ""
        echo "WARNING: ~/.hermes does not appear to be a mounted volume!"
        echo "         Config will be LOST when container restarts."
        echo ""
        echo "To fix: ensure deploy.sh mounts ~/.hermes as a volume:"
        echo "  -v \$HOME/.hermes:/root/.hermes"
        echo ""
        read -p "Continue anyway? [y/N] " CONTINUE
        if [ "${CONTINUE,,}" != "y" ]; then
            rm -f "$TEST_FILE"
            exit 1
        fi
    else
        echo "    ✓ ~/.hermes is mounted (config will persist)"
    fi
    rm -f "$TEST_FILE"
else
    echo "    Running outside Docker - config will persist normally"
fi

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

# Install Hermes (needed to derive addresses)
echo "==> Installing Hermes ${HERMES_VERSION}..."
if ! command -v hermes &>/dev/null; then
    cd /tmp
    curl -sL "https://github.com/informalsystems/hermes/releases/download/${HERMES_VERSION}/hermes-${HERMES_VERSION}-x86_64-unknown-linux-gnu.tar.gz" -o hermes.tar.gz
    tar -xzf hermes.tar.gz
    mv hermes /usr/local/bin/
    chmod +x /usr/local/bin/hermes
    rm hermes.tar.gz
    echo "    Installed: $(hermes version 2>&1 | head -1)"
else
    echo "    Already installed: $(hermes version 2>&1 | head -1)"
fi

# Create minimal config for key derivation
echo "==> Deriving relayer addresses..."
mkdir -p ~/.hermes/keys

cat > ~/.hermes/config.toml << 'CONFIG'
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
CONFIG

# Import keys to derive addresses
MNEMONIC_FILE=$(mktemp)
echo "$MNEMONIC" > "$MNEMONIC_FILE"
trap "rm -f $MNEMONIC_FILE" EXIT

hermes keys delete --chain mirage-1 --key-name relayer >/dev/null 2>&1 || true
hermes keys delete --chain osmosis-1 --key-name relayer >/dev/null 2>&1 || true

hermes keys add --chain mirage-1 --key-name relayer --hd-path "m/44'/118'/0'/0/0" --mnemonic-file "$MNEMONIC_FILE" >/dev/null 2>&1
hermes keys add --chain osmosis-1 --key-name relayer --hd-path "m/44'/118'/0'/0/0" --mnemonic-file "$MNEMONIC_FILE" >/dev/null 2>&1

rm -f "$MNEMONIC_FILE"

MIRAGE_ADDR=$(hermes keys list --chain mirage-1 2>&1 | grep -oE 'mirage1[a-z0-9]+')
OSMO_ADDR=$(hermes keys list --chain osmosis-1 2>&1 | grep -oE 'osmo1[a-z0-9]+')

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
    result=$(hermes keys balance --chain "$chain" --key-name relayer 2>&1 | grep -oE "[0-9]+ $denom" | awk '{print $1}' || echo "0")
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
CHANNEL_LIST=$(hermes query channels --chain mirage-1 2>&1 | grep -oE 'channel-[0-9]+' || true)
MIRAGE_CHANNEL=""
OSMOSIS_CHANNEL=""

for chan in $CHANNEL_LIST; do
    # Query channel details to get connection and counterparty channel
    CHAN_INFO=$(hermes query channel end --chain mirage-1 --port transfer --channel "$chan" 2>&1 || true)
    
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
    CONN_INFO=$(hermes query connection end --chain mirage-1 --connection "$CONN_ID" 2>&1 || true)
    CLIENT_ID=$(echo "$CONN_INFO" | grep -oE '07-tendermint-[0-9]+' | head -1 || echo "")
    if [ -z "$CLIENT_ID" ]; then
        continue
    fi
    
    # Query client state to get counterparty chain ID
    CLIENT_INFO=$(hermes query client state --chain mirage-1 --client "$CLIENT_ID" 2>&1 || true)
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
        echo "        3. Run 'hermes query channels --chain mirage-1' to debug"
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
    
    CREATE_OUTPUT=$(hermes create channel --a-chain mirage-1 --b-chain osmosis-1 --a-port transfer --b-port transfer --new-client-connection --yes 2>&1)
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
    echo "         Check 'hermes query channels --chain mirage-1' manually."
    MIRAGE_CHANNEL="${MIRAGE_CHANNEL:-channel-?}"
    OSMOSIS_CHANNEL="${OSMOSIS_CHANNEL:-channel-?}"
fi
# Start the relayer
echo ""
echo "==> Setting up Hermes relayer..."

# Kill any existing hermes
pkill -f "hermes start" 2>/dev/null || true
sleep 1

# Check if systemd is available (not in Docker)
if pidof systemd >/dev/null 2>&1; then
    echo "    Using systemd..."
    
    cat > /etc/systemd/system/hermes.service << EOF
[Unit]
Description=Hermes IBC Relayer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/hermes start
Restart=always
RestartSec=5
LimitNOFILE=65535
Environment="HOME=/root"

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable hermes >/dev/null 2>&1
    systemctl stop hermes 2>/dev/null || true
    systemctl start hermes
    
    sleep 3
    if systemctl is-active --quiet hermes; then
        echo "    Hermes service is running"
        SERVICE_MODE="systemd"
    else
        echo "ERROR: Hermes service failed to start"
        journalctl -u hermes --no-pager -n 20
        exit 1
    fi
else
    echo "    Using background process (Docker mode)..."
    
    # Create a restart wrapper script
    HERMES_LOG_DIR="$HOME/.mirage/logs/hermes"
    mkdir -p "$HERMES_LOG_DIR"
    cat > /usr/local/bin/hermes-runner.sh << RUNNER
#!/usr/bin/env bash
HERMES_LOG="$HERMES_LOG_DIR/hermes.log"
while true; do
    /usr/local/bin/hermes start >> "\$HERMES_LOG" 2>&1
    echo "\$(date): Hermes exited, restarting in 5s..." >> "\$HERMES_LOG"
    sleep 5
done
RUNNER
    chmod +x /usr/local/bin/hermes-runner.sh
    
    # Start in background
    nohup /usr/local/bin/hermes-runner.sh > /dev/null 2>&1 &
    
    sleep 3
    if pgrep -f "hermes start" >/dev/null; then
        echo "    Hermes is running (PID: $(pgrep -f 'hermes start'))"
        SERVICE_MODE="background"
    else
        echo "ERROR: Hermes failed to start. Check ~/.mirage/logs/hermes/hermes.log"
        exit 1
    fi
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
if [ "$SERVICE_MODE" = "systemd" ]; then
    echo "Relayer Service (systemd):"
    echo "  Status:  systemctl status hermes"
    echo "  Logs:    journalctl -u hermes -f"
    echo "  Restart: systemctl restart hermes"
else
    echo "Relayer Process (Docker mode):"
    echo "  Status:  pgrep -a hermes"
    echo "  Logs:    tail -f ~/.mirage/logs/hermes/hermes.log"
    echo "  Restart: pkill -f hermes-runner && /usr/local/bin/hermes-runner.sh &"
fi
echo ""
echo "To test IBC transfer from Mirage to Osmosis:"
echo "  miraged tx ibc-transfer transfer transfer $MIRAGE_CHANNEL <OSMO_ADDRESS> 1000000umirage --from <KEY> --chain-id mirage-1 --fees 50000umirage"
echo ""
echo "==========================================="
echo ""
echo "NOTE: For Hermes to auto-start on future container restarts,"
echo "      you must restart the container once:"
echo ""
echo "      docker restart mirage"
echo ""
echo "      The entrypoint will then detect ~/.hermes/config.toml"
echo "      and start Hermes automatically in a tmux window."
echo ""