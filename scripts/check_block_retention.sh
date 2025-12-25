#!/usr/bin/env bash
set -e

# Check block retention and storage usage
# Usage: ./check_block_retention.sh [RPC_URL]

RPC_URL="${1:-http://127.0.0.1:26657}"
HOME_DIR="${HOME_DIR:-$HOME/.mirage/main}"
DATA_DIR="$HOME_DIR/data"
APP_TOML="$HOME_DIR/config/app.toml"

echo "=== Block Retention Status ==="
echo "RPC: $RPC_URL"
echo "Data dir: $DATA_DIR"
echo ""

# Get current block info
echo "--- Current Chain Status ---"
STATUS=$(curl -s "$RPC_URL/status")
LATEST_HEIGHT=$(echo "$STATUS" | jq -r '.result.sync_info.latest_block_height')
EARLIEST_HEIGHT=$(echo "$STATUS" | jq -r '.result.sync_info.earliest_block_height')
CATCHING_UP=$(echo "$STATUS" | jq -r '.result.sync_info.catching_up')

echo "Latest block height:   $LATEST_HEIGHT"
echo "Earliest block height: $EARLIEST_HEIGHT"
echo "Catching up:           $CATCHING_UP"

RETAINED_BLOCKS=$((LATEST_HEIGHT - EARLIEST_HEIGHT + 1))
echo "Blocks retained:       $RETAINED_BLOCKS (height range)"

# Sample last 100 blocks to estimate empty vs non-empty ratio
SAMPLE_SIZE=100
SAMPLE_START=$((LATEST_HEIGHT - SAMPLE_SIZE + 1))
if [ "$SAMPLE_START" -lt "$EARLIEST_HEIGHT" ]; then
    SAMPLE_START=$EARLIEST_HEIGHT
    SAMPLE_SIZE=$((LATEST_HEIGHT - EARLIEST_HEIGHT + 1))
fi

NON_EMPTY=0
for i in $(seq $SAMPLE_START $LATEST_HEIGHT); do
    TX_COUNT=$(curl -s "$RPC_URL/block?height=$i" 2>/dev/null | jq -r '.result.block.data.txs | length')
    if [ "$TX_COUNT" -gt 0 ] 2>/dev/null; then
        NON_EMPTY=$((NON_EMPTY + 1))
    fi
done

if [ "$SAMPLE_SIZE" -gt 0 ]; then
    EMPTY_PERCENT=$(( (SAMPLE_SIZE - NON_EMPTY) * 100 / SAMPLE_SIZE ))
    echo "Sample analysis:"
    echo "  Last $SAMPLE_SIZE blocks: $NON_EMPTY with txs ($EMPTY_PERCENT% empty)"
    ESTIMATED_NON_EMPTY=$(( RETAINED_BLOCKS * NON_EMPTY / SAMPLE_SIZE ))
    echo "  Estimated blocks w/ txs: ~$ESTIMATED_NON_EMPTY"
fi
echo ""

# Check pruning config
echo "--- Pruning Configuration ---"
if [ -f "$APP_TOML" ]; then
    PRUNING=$(grep -A 5 "^\[pruning\]" "$APP_TOML" 2>/dev/null || echo "")
    if [ -n "$PRUNING" ]; then
        PRUNING_STRATEGY=$(echo "$PRUNING" | grep "^pruning =" | cut -d'"' -f2 || echo "default")
        KEEP_RECENT=$(echo "$PRUNING" | grep "^pruning-keep-recent =" | cut -d'"' -f2 || echo "0")
        KEEP_EVERY=$(echo "$PRUNING" | grep "^pruning-keep-every =" | cut -d'"' -f2 || echo "0")
        INTERVAL=$(echo "$PRUNING" | grep "^pruning-interval =" | cut -d'"' -f2 || echo "0")
        
        echo "Pruning strategy:      $PRUNING_STRATEGY"
        echo "Keep recent:           $KEEP_RECENT blocks"
        echo "Keep every:            $KEEP_EVERY blocks"
        echo "Pruning interval:      $INTERVAL blocks"
    else
        echo "No pruning config found in app.toml"
    fi
else
    echo "app.toml not found at $APP_TOML"
fi

# Check min-retain-blocks (the 10k limit)
MIN_RETAIN=$(grep "^min-retain-blocks" "$APP_TOML" 2>/dev/null | cut -d'=' -f2 | tr -d ' "' || echo "0")
if [ "$MIN_RETAIN" != "0" ]; then
    echo "Min retain blocks:     $MIN_RETAIN (minimum to keep)"
    PERCENT=$((RETAINED_BLOCKS * 100 / MIN_RETAIN))
    echo "Current retention:     $PERCENT% of min-retain-blocks"
fi

echo ""

# Check disk usage
echo "--- Storage Usage ---"
if [ -d "$DATA_DIR" ]; then
    DATA_SIZE=$(du -sh "$DATA_DIR" 2>/dev/null | cut -f1)
    echo "Data directory size:   $DATA_SIZE"
    
    # Break down by subdirectory
    if [ -d "$DATA_DIR/application.db" ]; then
        APP_SIZE=$(du -sh "$DATA_DIR/application.db" 2>/dev/null | cut -f1)
        echo "  application.db:      $APP_SIZE"
    fi
    if [ -d "$DATA_DIR/blockstore.db" ]; then
        BLOCK_SIZE=$(du -sh "$DATA_DIR/blockstore.db" 2>/dev/null | cut -f1)
        echo "  blockstore.db:       $BLOCK_SIZE"
    fi
    if [ -d "$DATA_DIR/state.db" ]; then
        STATE_SIZE=$(du -sh "$DATA_DIR/state.db" 2>/dev/null | cut -f1)
        echo "  state.db:            $STATE_SIZE"
    fi
else
    echo "Data directory not found"
fi

echo ""

# Summary and warnings
echo "=== Summary ==="
if [ "$MIN_RETAIN" != "0" ] && [ "$RETAINED_BLOCKS" -lt "$MIN_RETAIN" ]; then
    echo "⚠️  Retained blocks ($RETAINED_BLOCKS) below min-retain-blocks ($MIN_RETAIN)"
    echo "   Chain is still syncing or pruning hasn't stabilized"
elif [ "$MIN_RETAIN" != "0" ] && [ "$RETAINED_BLOCKS" -gt $((MIN_RETAIN + 1000)) ]; then
    echo "⚠️  Retained blocks ($RETAINED_BLOCKS) significantly above min-retain-blocks ($MIN_RETAIN)"
    echo "   Pruning may not be working correctly"
elif [ "$MIN_RETAIN" != "0" ]; then
    echo "✅ Block retention within expected range"
    echo "   Retained: $RETAINED_BLOCKS blocks (min: $MIN_RETAIN)"
else
    echo "ℹ️  No min-retain-blocks limit configured"
    echo "   Retained: $RETAINED_BLOCKS blocks"
fi

echo "Storage: $DATA_SIZE"

