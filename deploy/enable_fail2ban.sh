#!/usr/bin/env bash
# Enable fail2ban on the HOST (not inside Docker)
# Called by deploy.sh after container startup
# Uses the same .migrations tracking as container migrations
#
# Protects SSH from brute force attacks

set -euo pipefail

MIGRATIONS_FILE="$HOME/.mirage/env/.migrations"
mkdir -p "$(dirname "$MIGRATIONS_FILE")"

# Check if a migration has already been completed
migration_done() {
    local key="$1"
    if [ -f "$MIGRATIONS_FILE" ]; then
        grep -q "^${key}|" "$MIGRATIONS_FILE" 2>/dev/null
        return $?
    fi
    return 1
}

# Mark a migration as complete (same format as Python migrations)
mark_complete() {
    local key="$1"
    local result="${2:-completed}"
    local timestamp
    timestamp=$(date -Iseconds)
    echo "${key}|${timestamp}|${result}" >> "$MIGRATIONS_FILE"
}

# =============================================================================
# Migration: v1_10_0_fail2ban
# Installs and configures fail2ban for SSH protection
# =============================================================================
run_v1_10_0_fail2ban() {
    local key="v1_10_0_fail2ban"
    
    if migration_done "$key"; then
        echo "    ✓ fail2ban already configured"
        return 0
    fi
    
    echo "==> Running migration: $key"
    
    # Check if we're root
    if [ "$(id -u)" -ne 0 ]; then
        echo "    ⚠ Not running as root, skipping fail2ban setup"
        mark_complete "$key" "skipped (not root)"
        return 0
    fi
    
    # Install fail2ban
    echo "    Installing fail2ban..."
    apt-get update -qq
    apt-get install -y fail2ban >/dev/null 2>&1
    
    # Configure for SSH
    echo "    Configuring SSH jail..."
    cat > /etc/fail2ban/jail.local << 'EOF'
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
findtime = 600
bantime = 3600
ignoreip = 127.0.0.1/8
EOF
    
    # Enable and start
    echo "    Starting fail2ban service..."
    systemctl enable fail2ban >/dev/null 2>&1
    systemctl restart fail2ban
    
    # Clear old failed login logs
    truncate -s 0 /var/log/btmp 2>/dev/null || true
    truncate -s 0 /var/log/btmp.1 2>/dev/null || true
    
    mark_complete "$key" "installed"
    echo "    ✓ Migration $key complete"
    echo "    ✓ SSH protection: 5 attempts / 10 min / 1 hour ban"
}

# =============================================================================
# Main
# =============================================================================
echo "==> Running host-side fail2ban setup..."

run_v1_10_0_fail2ban

echo "✓ fail2ban setup complete"
