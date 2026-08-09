#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "$PWD" != "$SCRIPT_DIR" ]; then
    echo "  ERROR: run this script from web/frontend" >&2
    exit 1
fi

ENV_FILE="${SCRIPT_DIR}/../../deploy/templates/env/frontend.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "  ERROR: $ENV_FILE not found. Are you inside web/frontend/?" >&2
    exit 1
fi

# Source the env file
set -a
source "$ENV_FILE"
set +a

replace_or_append() {
    local key="$1"
    local value="$2"
    local tmp="${ENV_FILE}.tmp.$$"
    local found="0"

    while IFS= read -r line || [ -n "$line" ]; do
        if [[ "$line" == "${key}="* ]]; then
            printf '%s=%s\n' "$key" "$value" >> "$tmp"
            found="1"
        else
            printf '%s\n' "$line" >> "$tmp"
        fi
    done < "$ENV_FILE"

    if [ "$found" = "0" ]; then
        printf '\n%s=%s\n' "$key" "$value" >> "$tmp"
    fi

    mv "$tmp" "$ENV_FILE"
}

# If VITE_API_BASE is empty, ask the user which node to use
if [ -z "${VITE_API_BASE:-}" ]; then
    echo ""
    echo "  VITE_API_BASE is not set in frontend.env."
    echo ""
    echo "  Which Mirage node do you want to connect to?"
    echo ""
    echo "    1) mirage.vote  (public UAT node -- recommended)"
    echo "    2) Custom URL"
    echo "    3) Local (full-stack Docker on this machine)"
    echo ""
    read -rp "  Pick [1]: " choice
    choice="${choice:-1}"

    case "$choice" in
        2)
            read -rp "  Enter node URL (e.g. https://mynode.example.com): " custom_url
            export VITE_API_BASE="$custom_url"
            ;;
        3)
            export VITE_API_BASE="http://localhost"
            ;;
        *)
            export VITE_API_BASE="https://mirage.vote"
            ;;
    esac

    replace_or_append "VITE_API_BASE" "${VITE_API_BASE}"
    echo ""
    echo "  Saved to frontend.env"
fi

if [ ! -d node_modules ]; then
    echo ""
    echo "  Installing dependencies..."
    npm install --legacy-peer-deps
fi

echo ""
echo "  Starting Vite dev server (node: ${VITE_API_BASE})..."
echo ""

START_URL="http://localhost:3000"
if command -v xdg-open >/dev/null 2>&1; then
    (sleep 2; xdg-open "$START_URL" >/dev/null 2>&1) &
elif command -v open >/dev/null 2>&1; then
    (sleep 2; open "$START_URL" >/dev/null 2>&1) &
fi

npm run dev
