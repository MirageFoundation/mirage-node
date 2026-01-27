#!/usr/bin/env bash
set -e

# Check block retention and storage usage
# Usage: ./check_block_retention.sh [RPC_URL]

RPC_URL="${1:-http://127.0.0.1:26657}"
HOME_DIR="${HOME_DIR:-$HOME/.mirage/node}"
DATA_DIR="$HOME_DIR/data"
APP_TOML="$HOME_DIR/config/app.toml"

is_number() {
    [[ "${1:-}" =~ ^[0-9]+$ ]]
}

toml_get() {
    local key="$1"
    local line
    line=$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$APP_TOML" 2>/dev/null | head -1 || true)
    if [ -z "$line" ]; then
        echo ""
        return 0
    fi
    echo "$line" | cut -d'=' -f2- | tr -d ' "'
}

min_non_zero() {
    local a="$1"
    local b="$2"
    if ! is_number "$a" || [ "$a" -eq 0 ]; then
        echo "$b"
        return 0
    fi
    if ! is_number "$b" || [ "$b" -eq 0 ]; then
        echo "$a"
        return 0
    fi
    if [ "$a" -lt "$b" ]; then
        echo "$a"
    else
        echo "$b"
    fi
}

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
    PRUNING_STRATEGY=$(toml_get "pruning")
    KEEP_RECENT=$(toml_get "pruning-keep-recent")
    KEEP_EVERY=$(toml_get "pruning-keep-every")
    INTERVAL=$(toml_get "pruning-interval")

    [ -z "$PRUNING_STRATEGY" ] && PRUNING_STRATEGY="default"
    [ -z "$KEEP_RECENT" ] && KEEP_RECENT="0"
    [ -z "$KEEP_EVERY" ] && KEEP_EVERY="0"
    [ -z "$INTERVAL" ] && INTERVAL="0"

    echo "Pruning strategy:      $PRUNING_STRATEGY"
    echo "Keep recent:           $KEEP_RECENT blocks"
    echo "Keep every:            $KEEP_EVERY blocks"
    echo "Pruning interval:      $INTERVAL blocks"
else
    echo "app.toml not found at $APP_TOML"
fi

# Check min-retain-blocks (the 10k limit)
MIN_RETAIN=$(toml_get "min-retain-blocks")
[ -z "$MIN_RETAIN" ] && MIN_RETAIN="0"
if [ "$MIN_RETAIN" != "0" ]; then
    echo "Min retain blocks:     $MIN_RETAIN (minimum to keep)"
    PERCENT=$((RETAINED_BLOCKS * 100 / MIN_RETAIN))
    echo "Current retention:     $PERCENT% of min-retain-blocks"
fi

# Chain constraints (consensus params + snapshot retention)
CONSENSUS=$(curl -s "$RPC_URL/consensus_params")
EVIDENCE_MAX_AGE_BLOCKS=$(echo "$CONSENSUS" | jq -r '.result.consensus_params.evidence.max_age_num_blocks // empty')
SNAPSHOT_INTERVAL=$(toml_get "snapshot-interval")
SNAPSHOT_KEEP_RECENT=$(toml_get "snapshot-keep-recent")

[ -z "$SNAPSHOT_INTERVAL" ] && SNAPSHOT_INTERVAL="0"
[ -z "$SNAPSHOT_KEEP_RECENT" ] && SNAPSHOT_KEEP_RECENT="0"
if is_number "$SNAPSHOT_INTERVAL" && is_number "$SNAPSHOT_KEEP_RECENT"; then
    SNAPSHOT_RETENTION=$((SNAPSHOT_INTERVAL * SNAPSHOT_KEEP_RECENT))
else
    SNAPSHOT_RETENTION=0
fi

echo ""
echo "--- Chain vs Config ---"
echo "Evidence max_age_num_blocks: $EVIDENCE_MAX_AGE_BLOCKS"
echo "Snapshot retention blocks:   $SNAPSHOT_RETENTION (interval * keep)"
echo "Min retain blocks (config):  $MIN_RETAIN"

EXPECTED_RETENTION="$MIN_RETAIN"
EXPECTED_RETENTION=$(min_non_zero "$EXPECTED_RETENTION" "$EVIDENCE_MAX_AGE_BLOCKS")
EXPECTED_RETENTION=$(min_non_zero "$EXPECTED_RETENTION" "$SNAPSHOT_RETENTION")
echo "Effective retention blocks:  $EXPECTED_RETENTION (min of evidence/snapshot/min-retain)"

if is_number "$EVIDENCE_MAX_AGE_BLOCKS" && is_number "$MIN_RETAIN" && [ "$EVIDENCE_MAX_AGE_BLOCKS" -gt 0 ] && [ "$MIN_RETAIN" -gt 0 ] && [ "$EVIDENCE_MAX_AGE_BLOCKS" -lt "$MIN_RETAIN" ]; then
    echo "WARN: Evidence max_age_num_blocks gates retention below min-retain-blocks"
fi
if is_number "$SNAPSHOT_RETENTION" && is_number "$MIN_RETAIN" && [ "$SNAPSHOT_RETENTION" -gt 0 ] && [ "$MIN_RETAIN" -gt 0 ] && [ "$SNAPSHOT_RETENTION" -lt "$MIN_RETAIN" ]; then
    echo "WARN: Snapshot retention gates retention below min-retain-blocks"
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
TOLERANCE=100
if is_number "$EXPECTED_RETENTION" && [ "$EXPECTED_RETENTION" -gt 0 ]; then
    if [ "$RETAINED_BLOCKS" -lt $((EXPECTED_RETENTION - TOLERANCE)) ]; then
        echo "WARN: Retained blocks ($RETAINED_BLOCKS) below expected retention ($EXPECTED_RETENTION)"
        echo "      Chain may still be syncing or pruning hasn't stabilized"
    elif [ "$RETAINED_BLOCKS" -gt $((EXPECTED_RETENTION + TOLERANCE)) ]; then
        echo "WARN: Retained blocks ($RETAINED_BLOCKS) above expected retention ($EXPECTED_RETENTION)"
        echo "      Pruning may not be working correctly"
    else
        echo "OK: Block retention within expected range"
        echo "    Retained: $RETAINED_BLOCKS blocks (expected: $EXPECTED_RETENTION)"
    fi
elif [ "$MIN_RETAIN" != "0" ] && [ "$RETAINED_BLOCKS" -lt "$MIN_RETAIN" ]; then
    echo "WARN: Retained blocks ($RETAINED_BLOCKS) below min-retain-blocks ($MIN_RETAIN)"
    echo "      Chain may still be syncing or pruning hasn't stabilized"
elif [ "$MIN_RETAIN" != "0" ] && [ "$RETAINED_BLOCKS" -gt $((MIN_RETAIN + 1000)) ]; then
    echo "WARN: Retained blocks ($RETAINED_BLOCKS) significantly above min-retain-blocks ($MIN_RETAIN)"
    echo "      Pruning may not be working correctly"
elif [ "$MIN_RETAIN" != "0" ]; then
    echo "OK: Block retention within expected range"
    echo "    Retained: $RETAINED_BLOCKS blocks (min: $MIN_RETAIN)"
else
    echo "INFO: No min-retain-blocks limit configured"
    echo "      Retained: $RETAINED_BLOCKS blocks"
fi

echo "Storage: $DATA_SIZE"

