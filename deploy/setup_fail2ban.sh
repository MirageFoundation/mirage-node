#!/bin/bash
# Setup fail2ban to protect against SSH brute force attacks
# Run this script directly on the server as root
#
# Usage: ./setup_fail2ban.sh

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: Must run as root" >&2
    exit 1
fi

echo "==> Installing fail2ban..."
apt-get update -qq
apt-get install -y fail2ban

echo "==> Configuring fail2ban for SSH protection..."
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

echo "==> Starting fail2ban service..."
systemctl enable fail2ban
systemctl restart fail2ban

echo "==> Clearing old btmp logs (failed login records)..."
truncate -s 0 /var/log/btmp 2>/dev/null || true
truncate -s 0 /var/log/btmp.1 2>/dev/null || true

echo "==> Waiting for service to start..."
sleep 2

echo "==> fail2ban status:"
fail2ban-client status sshd || echo "(service still starting)"

echo ""
echo "============================================"
echo "✓ fail2ban installed and configured"
echo "============================================"
echo "  - Max retries: 5 attempts"
echo "  - Find time: 10 minutes"
echo "  - Ban time: 1 hour"
echo ""
echo "Useful commands:"
echo "  fail2ban-client status sshd    # View banned IPs"
echo "  fail2ban-client unban <IP>     # Unban an IP"
echo "  tail -f /var/log/fail2ban.log  # Watch bans"
