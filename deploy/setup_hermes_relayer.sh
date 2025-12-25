#!/usr/bin/env bash
set -euo pipefail

# Fully automated Hermes IBC relayer setup for Mirage <-> Osmosis
# Usage: ./setup_hermes_relayer.sh
# You will be prompted to enter your 12-word mnemonic (hidden input)
#
# Data is stored in ~/.hermes (persisted via Docker volume mount)

HERMES_VERSION="${HERMES_VERSION:-v1.10.4}"
MIRAGE_CHANNEL="channel-0"
OSMOSIS_CHANNEL="channel-108600"

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
enabled = false

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

# Check if channel already exists
echo ""
echo "==> Checking for existing IBC channel..."

EXISTING_CHANNELS=$(hermes query channels --chain mirage-1 2>&1 | grep -c "channel-" || echo "0")

if [ "$EXISTING_CHANNELS" -gt 0 ]; then
    echo "    Channel already exists on mirage-1"
    hermes query channels --chain mirage-1 2>&1 | grep -E "channel-|port_id|state" || true
else
    echo "    No channel found. Creating new IBC channel..."
    echo "    This will take 2-3 minutes and cost gas on both chains."
    echo ""
    
    if hermes create channel --a-chain mirage-1 --b-chain osmosis-1 --a-port transfer --b-port transfer --new-client-connection --yes 2>&1; then
        echo ""
        echo "==> IBC channel created successfully!"
    else
        echo ""
        echo "ERROR: Failed to create IBC channel. Check logs above."
        exit 1
    fi
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
    cat > /usr/local/bin/hermes-runner.sh << 'RUNNER'
#!/usr/bin/env bash
while true; do
    /usr/local/bin/hermes start >> /var/log/hermes.log 2>&1
    echo "$(date): Hermes exited, restarting in 5s..." >> /var/log/hermes.log
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
        echo "ERROR: Hermes failed to start. Check /var/log/hermes.log"
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
    echo "  Logs:    tail -f /var/log/hermes.log"
    echo "  Restart: pkill -f hermes-runner && /usr/local/bin/hermes-runner.sh &"
fi
echo ""
echo "To test IBC transfer from Mirage to Osmosis:"
echo "  miraged tx ibc-transfer transfer transfer $MIRAGE_CHANNEL <OSMO_ADDRESS> 1000000umirage --from <KEY> --chain-id mirage-1 --fees 50000umirage"
echo ""
echo "==========================================="
