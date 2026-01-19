#!/usr/bin/env bash
# Enable rate limiting on the HOST (not inside Docker)
# Called by deploy.sh after container startup
# Uses the same .migrations tracking as container migrations
#
# Supports: iptables, ufw, firewalld

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
# Migration: v1_9_0_p2p_rate_limiting
# Limits connections to port 26656 to prevent P2P abuse
# =============================================================================
run_v1_9_0_p2p_rate_limiting() {
    local key="v1_9_0_p2p_rate_limiting"
    
    if migration_done "$key"; then
        echo "    ✓ P2P rate limiting already configured"
        return 0
    fi
    
    echo "==> Running migration: $key"
    
    # Try different firewall tools in order of preference
    if command -v iptables &>/dev/null; then
        setup_iptables_rules
    elif command -v ufw &>/dev/null; then
        setup_ufw_rules
    elif command -v firewall-cmd &>/dev/null; then
        setup_firewalld_rules
    else
        echo "    ⚠ No supported firewall found (tried: iptables, ufw, firewalld)"
        echo "    ⚠ P2P rate limiting NOT configured - consider manual setup"
        mark_complete "$key" "skipped (no firewall)"
        return 0
    fi
}

setup_iptables_rules() {
    local key="v1_9_0_p2p_rate_limiting"
    local rules_added=""
    
    echo "    Using iptables..."
    
    # Rule 1: Limit concurrent connections per IP to port 26656
    if ! iptables -C INPUT -p tcp --dport 26656 -m connlimit --connlimit-above 5 --connlimit-mask 32 -j DROP 2>/dev/null; then
        iptables -A INPUT -p tcp --dport 26656 -m connlimit --connlimit-above 5 --connlimit-mask 32 -j DROP
        echo "    ✓ Added concurrent connection limit (5 per IP)"
        rules_added="connlimit"
    fi
    
    # Rule 2: Rate limit new connections per IP (tracking)
    if ! iptables -C INPUT -p tcp --dport 26656 -m state --state NEW -m recent --set --name P2P_RATELIMIT 2>/dev/null; then
        iptables -A INPUT -p tcp --dport 26656 -m state --state NEW -m recent --set --name P2P_RATELIMIT
    fi
    
    # Rule 3: Rate limit new connections per IP (drop after 10/min)
    if ! iptables -C INPUT -p tcp --dport 26656 -m state --state NEW -m recent --update --seconds 60 --hitcount 10 --name P2P_RATELIMIT -j DROP 2>/dev/null; then
        iptables -A INPUT -p tcp --dport 26656 -m state --state NEW -m recent --update --seconds 60 --hitcount 10 --name P2P_RATELIMIT -j DROP
        echo "    ✓ Added new connection rate limit (10 per minute per IP)"
        rules_added="${rules_added:+$rules_added, }ratelimit"
    fi
    
    # Persist rules
    if command -v netfilter-persistent &>/dev/null; then
        netfilter-persistent save 2>/dev/null || true
        echo "    ✓ Rules persisted via netfilter-persistent"
    elif command -v iptables-save &>/dev/null; then
        iptables-save > /etc/iptables.rules 2>/dev/null || true
        echo "    ✓ Rules saved to /etc/iptables.rules"
    fi
    
    if [ -n "$rules_added" ]; then
        mark_complete "$key" "iptables: $rules_added"
    else
        mark_complete "$key" "iptables: rules already present"
    fi
    echo "    ✓ Migration $key complete"
}

setup_ufw_rules() {
    local key="v1_9_0_p2p_rate_limiting"
    
    echo "    Using ufw..."
    
    # UFW has built-in rate limiting with 'limit' rule
    # This allows 6 connections per 30 seconds per IP
    if ! ufw status | grep -q "26656.*LIMIT"; then
        ufw limit 26656/tcp comment "P2P rate limit" 2>/dev/null || true
        echo "    ✓ Added ufw rate limit on port 26656"
        mark_complete "$key" "ufw: limit rule added"
    else
        mark_complete "$key" "ufw: rule already present"
    fi
    echo "    ✓ Migration $key complete"
}

setup_firewalld_rules() {
    local key="v1_9_0_p2p_rate_limiting"
    
    echo "    Using firewalld..."
    
    # firewalld uses rich rules for rate limiting
    local rule="rule family=ipv4 port port=26656 protocol=tcp limit value=10/m accept"
    
    if ! firewall-cmd --query-rich-rule="$rule" 2>/dev/null; then
        firewall-cmd --permanent --add-rich-rule="$rule" 2>/dev/null || true
        firewall-cmd --reload 2>/dev/null || true
        echo "    ✓ Added firewalld rate limit on port 26656"
        mark_complete "$key" "firewalld: rich rule added"
    else
        mark_complete "$key" "firewalld: rule already present"
    fi
    echo "    ✓ Migration $key complete"
}

# =============================================================================
# Main
# =============================================================================
echo "==> Running host-side migrations..."

run_v1_9_0_p2p_rate_limiting

echo "✓ Host setup complete"
