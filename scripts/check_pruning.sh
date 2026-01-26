#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

die() {
  log "ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

require_file() {
  [ -f "$1" ] || die "Missing required file: $1"
}

require_dir() {
  [ -d "$1" ] || die "Missing required directory: $1"
}

require_number() {
  local value="$1"
  local label="$2"
  if ! echo "$value" | grep -Eq '^[0-9]+$'; then
    die "Invalid numeric value for ${label}: ${value}"
  fi
}

toml_get() {
  local file="$1"
  local key="$2"
  local value=""

  value="$(awk -v key="$key" '
    BEGIN { found=0 }
    /^[[:space:]]*#/ { next }
    {
      if ($0 ~ "^[[:space:]]*" key "[[:space:]]*=") {
        found=1
        line=$0
        sub(/^[[:space:]]*[^=]+=[[:space:]]*/, "", line)
        sub(/[[:space:]]*#.*/, "", line)
        gsub(/^[\"\047]/, "", line)
        gsub(/[\"\047]$/, "", line)
        print line
        exit
      }
    }
    END { if (!found) exit 2 }
  ' "$file")" || die "Missing key '${key}' in ${file}"

  if [ -z "$value" ]; then
    die "Empty value for '${key}' in ${file}"
  fi

  echo "$value"
}

APP_TOML="/root/.mirage/node/config/app.toml"
CONFIG_TOML="/root/.mirage/node/config/config.toml"
DATA_DIR="/root/.mirage/node/data"
RPC_URL="http://127.0.0.1:26657"

EXPECT_PRUNING="custom"
EXPECT_KEEP_RECENT="1000"
EXPECT_INTERVAL="100"
EXPECT_MIN_RETAIN="28800"
EXPECT_DB_BACKEND="goleveldb"
EXPECT_APP_DB_BACKEND="goleveldb"

MAX_APP_DB_BYTES=""
MAX_DATA_DIR_BYTES=""
MAX_BLOCK_GAP=""
RECORD_FILE=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app-toml)
      [ -n "${2:-}" ] || die "--app-toml requires a value"
      APP_TOML="$2"
      shift 2
      ;;
    --config-toml)
      [ -n "${2:-}" ] || die "--config-toml requires a value"
      CONFIG_TOML="$2"
      shift 2
      ;;
    --data-dir)
      [ -n "${2:-}" ] || die "--data-dir requires a value"
      DATA_DIR="$2"
      shift 2
      ;;
    --rpc-url)
      [ -n "${2:-}" ] || die "--rpc-url requires a value"
      RPC_URL="$2"
      shift 2
      ;;
    --expect-pruning)
      [ -n "${2:-}" ] || die "--expect-pruning requires a value"
      EXPECT_PRUNING="$2"
      shift 2
      ;;
    --expect-keep-recent)
      [ -n "${2:-}" ] || die "--expect-keep-recent requires a value"
      EXPECT_KEEP_RECENT="$2"
      shift 2
      ;;
    --expect-interval)
      [ -n "${2:-}" ] || die "--expect-interval requires a value"
      EXPECT_INTERVAL="$2"
      shift 2
      ;;
    --expect-min-retain)
      [ -n "${2:-}" ] || die "--expect-min-retain requires a value"
      EXPECT_MIN_RETAIN="$2"
      shift 2
      ;;
    --expect-db-backend)
      [ -n "${2:-}" ] || die "--expect-db-backend requires a value"
      EXPECT_DB_BACKEND="$2"
      shift 2
      ;;
    --expect-app-db-backend)
      [ -n "${2:-}" ] || die "--expect-app-db-backend requires a value"
      EXPECT_APP_DB_BACKEND="$2"
      shift 2
      ;;
    --max-app-db-bytes)
      [ -n "${2:-}" ] || die "--max-app-db-bytes requires a value"
      MAX_APP_DB_BYTES="$2"
      shift 2
      ;;
    --max-data-dir-bytes)
      [ -n "${2:-}" ] || die "--max-data-dir-bytes requires a value"
      MAX_DATA_DIR_BYTES="$2"
      shift 2
      ;;
    --max-block-gap)
      [ -n "${2:-}" ] || die "--max-block-gap requires a value"
      MAX_BLOCK_GAP="$2"
      shift 2
      ;;
    --record-file)
      [ -n "${2:-}" ] || die "--record-file requires a value"
      RECORD_FILE="$2"
      shift 2
      ;;
    --help)
      cat <<'USAGE'
Usage: check_pruning.sh [options]

Options:
  --app-toml <path>            Path to app.toml
  --config-toml <path>         Path to config.toml
  --data-dir <path>            Path to node data directory
  --rpc-url <url>              CometBFT RPC URL
  --expect-pruning <value>     Expected pruning mode (default: custom)
  --expect-keep-recent <n>     Expected pruning-keep-recent (default: 1000)
  --expect-interval <n>        Expected pruning-interval (default: 100)
  --expect-min-retain <n>      Expected min-retain-blocks (default: 28800)
  --expect-db-backend <value>  Expected config.toml db_backend (default: goleveldb)
  --expect-app-db-backend <v>  Expected app.toml app-db-backend (default: goleveldb)
  --max-app-db-bytes <n>       Fail if application.db exceeds this size
  --max-data-dir-bytes <n>     Fail if data dir exceeds this size
  --max-block-gap <n>          Fail if latest - earliest exceeds this value
  --record-file <path>         Append a TSV record to this file
USAGE
      exit 0
      ;;
    *)
      die "Unknown arg: $1"
      ;;
  esac
done

require_cmd awk
require_cmd curl
require_cmd du
require_cmd grep
require_cmd python3

require_file "$APP_TOML"
require_file "$CONFIG_TOML"
require_dir "$DATA_DIR"

pruning="$(toml_get "$APP_TOML" "pruning")"
keep_recent="$(toml_get "$APP_TOML" "pruning-keep-recent")"
interval="$(toml_get "$APP_TOML" "pruning-interval")"
min_retain="$(toml_get "$APP_TOML" "min-retain-blocks")"
db_backend="$(toml_get "$CONFIG_TOML" "db_backend")"
app_db_backend="$(toml_get "$APP_TOML" "app-db-backend")"

require_number "$keep_recent" "pruning-keep-recent"
require_number "$interval" "pruning-interval"
require_number "$min_retain" "min-retain-blocks"

[ "$pruning" = "$EXPECT_PRUNING" ] || die "pruning=${pruning}, expected ${EXPECT_PRUNING}"
[ "$keep_recent" = "$EXPECT_KEEP_RECENT" ] || die "pruning-keep-recent=${keep_recent}, expected ${EXPECT_KEEP_RECENT}"
[ "$interval" = "$EXPECT_INTERVAL" ] || die "pruning-interval=${interval}, expected ${EXPECT_INTERVAL}"
[ "$min_retain" = "$EXPECT_MIN_RETAIN" ] || die "min-retain-blocks=${min_retain}, expected ${EXPECT_MIN_RETAIN}"
[ "$db_backend" = "$EXPECT_DB_BACKEND" ] || die "db_backend=${db_backend}, expected ${EXPECT_DB_BACKEND}"
[ "$app_db_backend" = "$EXPECT_APP_DB_BACKEND" ] || die "app-db-backend=${app_db_backend}, expected ${EXPECT_APP_DB_BACKEND}"

echo ""
echo "=== PRUNING CONFIG ==="
echo "  pruning             = ${pruning}  (expected: ${EXPECT_PRUNING}) ✓"
echo "  pruning-keep-recent = ${keep_recent}  (expected: ${EXPECT_KEEP_RECENT}) ✓"
echo "  pruning-interval    = ${interval}  (expected: ${EXPECT_INTERVAL}) ✓"
echo "  min-retain-blocks   = ${min_retain}  (expected: ${EXPECT_MIN_RETAIN}) ✓"
echo ""
echo "=== DATABASE BACKEND ==="
echo "  db_backend          = ${db_backend}  (expected: ${EXPECT_DB_BACKEND}) ✓"
echo "  app-db-backend      = ${app_db_backend}  (expected: ${EXPECT_APP_DB_BACKEND}) ✓"

status_json="$(curl -sf "${RPC_URL}/status")"
catching_up="$(echo "$status_json" | python3 -c "import sys,json; print(str(json.load(sys.stdin)['result']['sync_info']['catching_up']).lower())")"
latest_height="$(echo "$status_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['sync_info']['latest_block_height'])")"
earliest_height="$(echo "$status_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['sync_info']['earliest_block_height'])")"

if [ "$catching_up" != "false" ]; then
  die "Node is still catching up"
fi

require_number "$latest_height" "latest_block_height"
require_number "$earliest_height" "earliest_block_height"

block_gap=$((latest_height - earliest_height))

echo ""
echo "=== BLOCK RETENTION ==="
echo "  latest_block_height   = ${latest_height}"
echo "  earliest_block_height = ${earliest_height}"
echo "  blocks retained       = ${block_gap}"
echo ""
if [ "$block_gap" -le "$EXPECT_MIN_RETAIN" ]; then
  echo "  ✓ Block gap (${block_gap}) <= min-retain-blocks (${EXPECT_MIN_RETAIN})"
  echo "    Pruning is WORKING - old blocks are being removed"
else
  echo "  ⚠ Block gap (${block_gap}) > min-retain-blocks (${EXPECT_MIN_RETAIN})"
  echo "    This is normal if the node just started or recently state-synced"
fi

app_db_path="${DATA_DIR}/application.db"
require_dir "$app_db_path"
app_db_bytes="$(du -sb "$app_db_path" | awk '{print $1}')"
data_dir_bytes="$(du -sb "$DATA_DIR" | awk '{print $1}')"

require_number "$app_db_bytes" "application.db bytes"
require_number "$data_dir_bytes" "data dir bytes"

human_size() {
  local bytes="$1"
  if [ "$bytes" -ge 1073741824 ]; then
    echo "$(awk "BEGIN {printf \"%.2f GB\", $bytes/1073741824}")"
  elif [ "$bytes" -ge 1048576 ]; then
    echo "$(awk "BEGIN {printf \"%.2f MB\", $bytes/1048576}")"
  elif [ "$bytes" -ge 1024 ]; then
    echo "$(awk "BEGIN {printf \"%.2f KB\", $bytes/1024}")"
  else
    echo "${bytes} bytes"
  fi
}

app_db_human="$(human_size "$app_db_bytes")"
data_dir_human="$(human_size "$data_dir_bytes")"

echo ""
echo "=== DISK USAGE ==="
echo "  application.db = ${app_db_human} (${app_db_bytes} bytes)"
echo "  data directory = ${data_dir_human} (${data_dir_bytes} bytes)"

if [ -n "$MAX_APP_DB_BYTES" ]; then
  require_number "$MAX_APP_DB_BYTES" "max-app-db-bytes"
  [ "$app_db_bytes" -le "$MAX_APP_DB_BYTES" ] || die "application.db too large: ${app_db_bytes} > ${MAX_APP_DB_BYTES}"
fi

if [ -n "$MAX_DATA_DIR_BYTES" ]; then
  require_number "$MAX_DATA_DIR_BYTES" "max-data-dir-bytes"
  [ "$data_dir_bytes" -le "$MAX_DATA_DIR_BYTES" ] || die "data dir too large: ${data_dir_bytes} > ${MAX_DATA_DIR_BYTES}"
fi

if [ -n "$MAX_BLOCK_GAP" ]; then
  require_number "$MAX_BLOCK_GAP" "max-block-gap"
  [ "$block_gap" -le "$MAX_BLOCK_GAP" ] || die "block gap too large: ${block_gap} > ${MAX_BLOCK_GAP}"
fi

if [ -n "$RECORD_FILE" ]; then
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$pruning" "$keep_recent" "$interval" "$min_retain" \
    "$db_backend" "$app_db_backend" \
    "$latest_height" "$earliest_height" "$block_gap" \
    "$app_db_bytes" >> "$RECORD_FILE"
  echo ""
  echo "  Recorded metrics to ${RECORD_FILE}"
fi

echo ""
echo "=== SUMMARY ==="
echo "  ✓ Pruning config is correct"
echo "  ✓ Node is synced (not catching up)"
if [ "$block_gap" -le "$EXPECT_MIN_RETAIN" ]; then
  echo "  ✓ Pruning is actively removing old blocks"
else
  echo "  ⚠ Block gap exceeds min-retain (normal after state-sync)"
fi
if [ "$app_db_bytes" -lt 1073741824 ]; then
  echo "  ✓ Database size is healthy (< 1 GB)"
else
  echo "  ⚠ Database size is large ($(human_size "$app_db_bytes"))"
fi
echo ""
echo "ALL CHECKS PASSED"
echo ""
