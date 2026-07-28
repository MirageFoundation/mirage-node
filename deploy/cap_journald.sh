#!/usr/bin/env bash
# Cap systemd-journald disk usage on the HOST (not inside Docker)
# Called by deploy.sh after container startup
# Uses the same .migrations tracking as container migrations
#
# journald ships with no explicit size limit, so it defaults to 10% of the
# filesystem — 2.4G on our 24G validator volumes. It had grown to ~800M on
# mirage.talk and was the single largest uncapped consumer on the box, while the
# actual chain data (all of it) is under 1G. Cap it and reclaim immediately.

set -euo pipefail

JOURNAL_MAX_USE="${JOURNAL_MAX_USE:-200M}"

MIGRATIONS_FILE="$HOME/.mirage/env/.migrations"
mkdir -p "$(dirname "$MIGRATIONS_FILE")"

migration_done() {
    local key="$1"
    if [ -f "$MIGRATIONS_FILE" ]; then
        grep -q "^${key}|" "$MIGRATIONS_FILE" 2>/dev/null
        return $?
    fi
    return 1
}

mark_complete() {
    local key="$1"
    local result="${2:-completed}"
    local timestamp
    timestamp=$(date -Iseconds)
    echo "${key}|${timestamp}|${result}" >> "$MIGRATIONS_FILE"
}

# =============================================================================
# Migration: v1_29_9_journald_cap
# Caps journald at JOURNAL_MAX_USE and vacuums the existing journal down to it
# =============================================================================
run_v1_29_9_journald_cap() {
    local key="v1_29_9_journald_cap"

    if migration_done "$key"; then
        echo "    ✓ journald already capped"
        return 0
    fi

    echo "==> Running migration: $key"

    if [ "$(id -u)" -ne 0 ]; then
        echo "    ⚠ Not running as root, skipping journald cap"
        mark_complete "$key" "skipped (not root)"
        return 0
    fi

    if ! command -v journalctl >/dev/null 2>&1; then
        echo "    ⚠ journalctl not present, skipping"
        mark_complete "$key" "skipped (no journald)"
        return 0
    fi

    local before
    before=$(journalctl --disk-usage 2>/dev/null | grep -oE "[0-9.]+[KMG]" | tail -1 || echo "?")

    # Drop-in rather than editing journald.conf: survives package upgrades that
    # rewrite the distro config, and is trivially reversible (delete the file).
    echo "    Writing /etc/systemd/journald.conf.d/99-mirage.conf (SystemMaxUse=$JOURNAL_MAX_USE)..."
    mkdir -p /etc/systemd/journald.conf.d
    cat > /etc/systemd/journald.conf.d/99-mirage.conf << EOF
# Managed by mirage deploy (deploy/cap_journald.sh) — do not edit by hand.
# Without this journald defaults to 10% of the filesystem (~2.4G on a 24G
# volume). Node forensics live in /root/.mirage/logs (own retention), so the
# journal only needs enough history for host-level triage.
[Journal]
SystemMaxUse=$JOURNAL_MAX_USE
EOF

    echo "    Restarting systemd-journald..."
    systemctl restart systemd-journald

    # Reclaim now — the cap alone only bounds future growth.
    echo "    Vacuuming journal to $JOURNAL_MAX_USE..."
    journalctl --vacuum-size="$JOURNAL_MAX_USE" >/dev/null 2>&1 || true

    local after
    after=$(journalctl --disk-usage 2>/dev/null | grep -oE "[0-9.]+[KMG]" | tail -1 || echo "?")

    mark_complete "$key" "capped at $JOURNAL_MAX_USE (was $before, now $after)"
    echo "    ✓ Migration $key complete"
    echo "    ✓ journald: $before -> $after (cap $JOURNAL_MAX_USE)"
}

# =============================================================================
# Main
# =============================================================================
echo "==> Running host-side journald cap..."

run_v1_29_9_journald_cap

echo "✓ journald cap complete"
