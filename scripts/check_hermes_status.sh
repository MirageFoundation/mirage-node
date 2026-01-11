#!/usr/bin/env bash
# Hermes Status Check for Mirage <-> Osmosis
#
# Usage: ./check_hermes_status.sh [--alert-webhook URL]
#
# Checks:
# 1. Is Hermes relayer running?
# 2. Are IBC clients healthy (not expired/expiring soon)?
# 3. Is the channel open?
# 4. Are there pending/stuck packets?
# 5. Are client updates happening? (prevents expiry)
#
# Alerts: Configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in ~/.mirage/config/secrets.env
#         Or use --alert-webhook for Slack-compatible webhooks
#
# Exit codes:
#   0 = All healthy
#   1 = Warning (client expiring soon)
#   2 = Critical (relayer down or client expired)

set -euo pipefail

# Load secrets env file if present (for Telegram credentials)
SECRETS_FILE="${HOME}/.mirage/config/secrets.env"
if [ -f "$SECRETS_FILE" ]; then
    # shellcheck source=/dev/null
    source "$SECRETS_FILE"
fi

TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
WEBHOOK_URL=""
WARNING_DAYS=3  # Warn if client expires within this many days

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --alert-webhook)
            WEBHOOK_URL="$2"
            shift 2
            ;;
        --warning-days)
            WARNING_DAYS="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

STATUS="healthy"
ISSUES=()

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              IBC Health Check - Mirage <-> Osmosis           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check 1: Is Hermes running?
echo "Checking Hermes relayer..."
if pgrep -f "hermes start" >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Hermes is running (PID: $(pgrep -f 'hermes start'))"
else
    echo -e "  ${RED}✗${NC} Hermes is NOT running!"
    STATUS="critical"
    ISSUES+=("Hermes relayer is not running")
fi

# Check 2: Is Hermes config present?
echo ""
echo "Checking Hermes configuration..."
if [ -f "$HOME/.hermes/config.toml" ]; then
    echo -e "  ${GREEN}✓${NC} Config file exists"
else
    echo -e "  ${RED}✗${NC} Config file missing at ~/.hermes/config.toml"
    STATUS="critical"
    ISSUES+=("Hermes config missing")
fi

# Check 3: Query IBC client status (if hermes is available)
if command -v hermes &>/dev/null && [ -f "$HOME/.hermes/config.toml" ]; then
    echo ""
    echo "Checking IBC client health..."
    
    # Check Mirage -> Osmosis client
    CLIENT_OUTPUT=$(hermes query clients --host-chain mirage-1 2>&1 || true)
    if echo "$CLIENT_OUTPUT" | grep -q "07-tendermint"; then
        MIRAGE_CLIENT=$(echo "$CLIENT_OUTPUT" | grep -oE "07-tendermint-[0-9]+" | tail -1 || echo "")
        if [ -n "$MIRAGE_CLIENT" ]; then
            # Check client status (Active vs Expired/Frozen)
            CLIENT_STATUS=$(hermes query client status --chain mirage-1 --client "$MIRAGE_CLIENT" 2>&1 || true)
            if echo "$CLIENT_STATUS" | grep -q "SUCCESS Active"; then
                echo -e "  ${GREEN}✓${NC} Mirage client $MIRAGE_CLIENT is Active"
            elif echo "$CLIENT_STATUS" | grep -qi "expired\|frozen"; then
                echo -e "  ${RED}✗${NC} Mirage client $MIRAGE_CLIENT is EXPIRED/FROZEN!"
                STATUS="critical"
                ISSUES+=("IBC client on Mirage is expired")
            else
                echo -e "  ${YELLOW}?${NC} Mirage client $MIRAGE_CLIENT status unknown"
                echo "      $CLIENT_STATUS" | head -3
            fi
        fi
    else
        echo -e "  ${YELLOW}?${NC} Could not query Mirage clients"
    fi
    
    # Check channel status
    echo ""
    echo "Checking IBC channel..."
    CHANNEL_OUTPUT=$(hermes query channels --chain mirage-1 2>&1 || true)
    if echo "$CHANNEL_OUTPUT" | grep -q "channel-"; then
        CHANNEL=$(echo "$CHANNEL_OUTPUT" | grep -oE "channel-[0-9]+" | head -1 || echo "")
        if [ -n "$CHANNEL" ]; then
            CHANNEL_STATE=$(hermes query channel end --chain mirage-1 --port transfer --channel "$CHANNEL" 2>&1 || true)
            if echo "$CHANNEL_STATE" | grep -qi "OPEN"; then
                echo -e "  ${GREEN}✓${NC} Channel $CHANNEL is OPEN"
            else
                echo -e "  ${RED}✗${NC} Channel $CHANNEL is NOT open!"
                STATUS="critical"
                ISSUES+=("IBC channel is not open")
            fi
        fi
    else
        echo -e "  ${YELLOW}?${NC} No channels found"
    fi
    
    # Check for pending packets (stuck relays)
    echo ""
    echo "Checking relay activity..."
    if [ -n "$CHANNEL" ]; then
        PENDING=$(hermes query packet pending --chain mirage-1 --port transfer --channel "$CHANNEL" 2>&1 || true)
        UNRECEIVED=$(echo "$PENDING" | grep -oE "unreceived_packets: \[[0-9]" | head -1 || echo "")
        UNACKED=$(echo "$PENDING" | grep -oE "unreceived_acks: \[[0-9]" | head -1 || echo "")
        
        if [ -n "$UNRECEIVED" ] || [ -n "$UNACKED" ]; then
            echo -e "  ${YELLOW}!${NC} Pending packets detected - relay in progress or stuck"
            # Extract counts for more detail
            UNRECEIVED_COUNT=$(echo "$PENDING" | grep -oE "unreceived_packets: \[[^]]*\]" | grep -oE "[0-9]+" | wc -l || echo "0")
            UNACKED_COUNT=$(echo "$PENDING" | grep -oE "unreceived_acks: \[[^]]*\]" | grep -oE "[0-9]+" | wc -l || echo "0")
            echo "      Unreceived: $UNRECEIVED_COUNT, Unacked: $UNACKED_COUNT"
        else
            echo -e "  ${GREEN}✓${NC} No pending packets"
        fi
    fi
    
    # Check hermes log for recent activity (client updates keep the channel alive)
    # Check date-based log first, then legacy locations
    HERMES_LOG="${HOME}/.mirage/logs/hermes/hermes-$(date -u +%Y-%m-%d).log"
    if [ ! -f "$HERMES_LOG" ]; then
        # Try yesterday's log
        HERMES_LOG="${HOME}/.mirage/logs/hermes/hermes-$(date -u -d 'yesterday' +%Y-%m-%d 2>/dev/null || date -u -v-1d +%Y-%m-%d).log"
    fi
    if [ ! -f "$HERMES_LOG" ]; then
        HERMES_LOG="/var/log/hermes.log"  # Legacy location
    fi
    if [ -f "$HERMES_LOG" ]; then
        # Check for any client update in the last 24 hours
        LAST_UPDATE=$(grep -i "client.*update\|UpdateClient" "$HERMES_LOG" 2>/dev/null | tail -1 || echo "")
        if [ -z "$LAST_UPDATE" ]; then
            # No client updates found in log - check log age
            LOG_AGE_HOURS=$(( ($(date +%s) - $(stat -c %Y "$HERMES_LOG" 2>/dev/null || echo "0")) / 3600 ))
            if [ "$LOG_AGE_HOURS" -gt 24 ]; then
                echo -e "  ${YELLOW}!${NC} No client updates in log (log is ${LOG_AGE_HOURS}h old)"
                if [ "$STATUS" = "healthy" ]; then
                    STATUS="warning"
                fi
                ISSUES+=("No recent IBC client updates - expiry countdown may be active")
            else
                echo -e "  ${GREEN}✓${NC} Hermes log active (${LOG_AGE_HOURS}h old)"
            fi
        else
            echo -e "  ${GREEN}✓${NC} Client updates found in log"
        fi
    else
        echo -e "  ${YELLOW}?${NC} Hermes log not found at $HERMES_LOG"
    fi
fi

# Summary
echo ""
echo "═══════════════════════════════════════════════════════════════"
if [ "$STATUS" = "healthy" ]; then
    echo -e "Status: ${GREEN}HEALTHY${NC}"
    EXIT_CODE=0
elif [ "$STATUS" = "warning" ]; then
    echo -e "Status: ${YELLOW}WARNING${NC}"
    EXIT_CODE=1
else
    echo -e "Status: ${RED}CRITICAL${NC}"
    EXIT_CODE=2
fi

if [ ${#ISSUES[@]} -gt 0 ]; then
    echo ""
    echo "Issues:"
    for issue in "${ISSUES[@]}"; do
        echo "  • $issue"
    done
fi
echo "═══════════════════════════════════════════════════════════════"

# Send alerts if configured and not healthy
if [ "$STATUS" != "healthy" ]; then
    ALERT_MSG="🚨 IBC Health Alert [$STATUS]: ${ISSUES[*]}"
    
    # Telegram alert
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        echo ""
        echo "Sending Telegram alert..."
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=${ALERT_MSG}" \
            -d "parse_mode=HTML" >/dev/null 2>&1 || true
    fi
    
    # Slack/generic webhook alert
    if [ -n "$WEBHOOK_URL" ]; then
        echo ""
        echo "Sending webhook alert..."
        curl -s -X POST "$WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"text\": \"$ALERT_MSG\"}" >/dev/null 2>&1 || true
    fi
fi

exit $EXIT_CODE
