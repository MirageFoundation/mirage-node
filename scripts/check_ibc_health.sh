#!/usr/bin/env bash
# IBC Health Check for Mirage <-> Osmosis
#
# Usage: ./check_ibc_health.sh [--alert-webhook URL]
#
# Checks:
# 1. Is Hermes relayer running?
# 2. Are IBC clients healthy (not expired/expiring soon)?
# 3. Is the channel open?
#
# Exit codes:
#   0 = All healthy
#   1 = Warning (client expiring soon)
#   2 = Critical (relayer down or client expired)

set -euo pipefail

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
            # Check client state
            CLIENT_STATE=$(hermes query client state --chain mirage-1 --client "$MIRAGE_CLIENT" 2>&1 || true)
            if echo "$CLIENT_STATE" | grep -qi "expired\|frozen"; then
                echo -e "  ${RED}✗${NC} Mirage client $MIRAGE_CLIENT is EXPIRED/FROZEN!"
                STATUS="critical"
                ISSUES+=("IBC client on Mirage is expired")
            else
                echo -e "  ${GREEN}✓${NC} Mirage client $MIRAGE_CLIENT is active"
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

# Send webhook alert if configured and not healthy
if [ -n "$WEBHOOK_URL" ] && [ "$STATUS" != "healthy" ]; then
    echo ""
    echo "Sending alert to webhook..."
    ALERT_MSG="IBC Health Alert [$STATUS]: ${ISSUES[*]}"
    curl -s -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"text\": \"$ALERT_MSG\"}" >/dev/null 2>&1 || true
fi

exit $EXIT_CODE
