# Server Setup for a Mirage Node

This is the OS-level baseline every Mirage validator host must meet **before** running `deploy/deploy.sh`. It applies to fresh DigitalOcean droplets (Ubuntu 24.04 LTS) and to existing hosts that need to be brought up to spec.

Skip nothing. Each step here addresses a real incident or a real near-miss in production.

> Companion docs: [`deploy.md`](deploy.md) for the node software, [`apphash-divergence-4015233.md`](../apphash-divergence-4015233.md) for the incident that motivated swap + memory hardening.

---

## Target spec

| Item        | Value                                                  |
|-------------|--------------------------------------------------------|
| OS          | Ubuntu 24.04 LTS                                       |
| Arch        | x86_64                                                 |
| vCPUs       | 2 minimum, 4 recommended                               |
| RAM         | 4 GB minimum, **8 GB strongly recommended**            |
| Swap        | **2 GB minimum (mandatory)**                           |
| Disk        | 80 GB SSD minimum (chain grows ~10 GB/year)            |
| Timezone    | `Etc/UTC`                                              |
| Kernel      | 6.8+ (Ubuntu 24.04 default)                            |

A DigitalOcean **`s-2vcpu-4gb-amd`** droplet works for testing. For production, use **`s-4vcpu-8gb-amd`** or larger — 4 GB RAM with no swap is what caused [the 4015233 AppHash divergence](../apphash-divergence-4015233.md).

---

## 1. Update the base system

```bash
apt update && apt -y full-upgrade
apt -y install ufw fail2ban unattended-upgrades curl ca-certificates gnupg htop iotop dstat jq
reboot   # if a new kernel was installed
```

---

## 2. Swap — 2 GB, mandatory

**Without swap, a transient memory spike on a busy validator can cause silent in-memory cache corruption** (page eviction races inside Go's runtime / IAVL `nodeCache`) without triggering an OOM kill. The kernel has no soft-fail buffer; the process either survives or dies, and "mostly survives" is exactly how AppHash divergence sneaks in.

```bash
# Create a 2 GB swapfile (idempotent — skips if already exists)
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Tune for a server (avoid swapping unless we really have to)
cat > /etc/sysctl.d/99-mirage-swap.conf <<'EOF'
vm.swappiness = 10
vm.vfs_cache_pressure = 50
EOF
sysctl --system

# Verify
swapon --show
free -h
```

You should see one entry under `swapon --show` and `Swap: 2.0Gi` in `free -h`. If both are empty, fix it before continuing.

---

## 3. SSH — key only, no passwords

Ubuntu 24.04 droplets ship with a **contradictory** sshd config: `/etc/ssh/sshd_config` says `PasswordAuthentication no`, `/etc/ssh/sshd_config.d/50-cloud-init.conf` overrides to `yes`, and `/etc/ssh/sshd_config.d/60-cloudimg-settings.conf` overrides back to `no`. The last file alphabetically wins, but this is fragile. Drop a definitive override file:

```bash
cat > /etc/ssh/sshd_config.d/99-mirage-hardening.conf <<'EOF'
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitEmptyPasswords no
ChallengeResponseAuthentication no
UsePAM yes
X11Forwarding no
MaxAuthTries 3
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
EOF

# Verify the merged config — the *Authentication lines should all be 'no' except Pubkey
sshd -T | grep -Ei 'permitroot|passwordauth|pubkey|kbdinteract|challengeresp'

systemctl reload ssh
```

**Before disconnecting**, in a *second* terminal, confirm you can still SSH in with your key. Lock yourself out and the only fix is the cloud provider's recovery console.

Authorized keys live in `/root/.ssh/authorized_keys`. Add team keys here, one per line. Remove keys when people leave.

---

## 4. Firewall (UFW)

Mirage validators expose exactly four inbound ports. Everything else stays closed.

```bash
ufw default deny incoming
ufw default allow outgoing
ufw default deny routed

ufw allow 22/tcp     comment 'SSH'
ufw allow 80/tcp     comment 'HTTP (cert renewal + frontend)'
ufw allow 443/tcp    comment 'HTTPS'
ufw allow 26656/tcp  comment 'CometBFT P2P'
ufw allow 26657/tcp  comment 'CometBFT RPC'

ufw --force enable
ufw status verbose
```

**Do not** open 1317 (REST), 9090 (gRPC), 5432 (Postgres), or 26658 (ABCI). They listen on `127.0.0.1` only and reaching them from the internet means something is misconfigured.

---

## 5. fail2ban

```bash
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true
EOF

systemctl enable --now fail2ban
fail2ban-client status sshd
```

---

## 6. Unattended security upgrades

Auto-apply security patches; do *not* auto-apply feature updates (those can change behavior under your validator).

```bash
dpkg-reconfigure --priority=low unattended-upgrades   # or just enable manually:
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

# Reboots only happen at 03:30 if the kernel demands it
sed -i 's|//\s*Unattended-Upgrade::Automatic-Reboot .*|Unattended-Upgrade::Automatic-Reboot "true";|' /etc/apt/apt.conf.d/50unattended-upgrades
sed -i 's|//\s*Unattended-Upgrade::Automatic-Reboot-Time .*|Unattended-Upgrade::Automatic-Reboot-Time "03:30";|' /etc/apt/apt.conf.d/50unattended-upgrades

systemctl enable --now unattended-upgrades
```

---

## 7. Time sync

Consensus is height- and time-stamped. Drift breaks block proposing.

```bash
timedatectl set-timezone Etc/UTC
timedatectl set-ntp true
timedatectl status   # System clock synchronized: yes  /  NTP service: active
```

---

## 8. Docker

Use Docker's official APT repo, not the Ubuntu-shipped `docker.io` package. Mirage requires the `compose` plugin.

```bash
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list

apt update
apt -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker

# Verify
docker --version
docker compose version
```

Cap container log size so a chatty container can't fill the disk:

```bash
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "100m", "max-file": "5" }
}
EOF
systemctl restart docker
```

---

## 9. Kernel & ulimit tuning for a chain node

CometBFT opens a lot of file descriptors and sockets. Defaults are fine on small chains but tighten under load.

```bash
cat > /etc/sysctl.d/99-mirage-net.conf <<'EOF'
# Raise connection backlogs (P2P + RPC + reverse proxy)
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096
net.ipv4.ip_local_port_range = 10240 65535

# Reuse TIME_WAIT sockets quickly
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15

# More room for the inotify watchers Docker / journald use
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 512
EOF
sysctl --system

cat > /etc/security/limits.d/99-mirage.conf <<'EOF'
*       soft    nofile  131072
*       hard    nofile  131072
root    soft    nofile  131072
root    hard    nofile  131072
EOF
```

Re-login (or reboot) for the `nofile` limits to take effect. Verify with `ulimit -n` — it should print `131072`.

---

## 10. Operational hygiene

### Weekly container restart

Bound the lifetime of in-memory state. Long-running Go processes can accumulate subtle GC fragmentation; a weekly restart is cheap insurance and was identified as a remediation step from the [4015233 incident](../apphash-divergence-4015233.md).

```bash
cat > /etc/systemd/system/mirage-weekly-restart.service <<'EOF'
[Unit]
Description=Weekly restart of Mirage container
[Service]
Type=oneshot
ExecStart=/usr/bin/docker restart mirage
EOF

cat > /etc/systemd/system/mirage-weekly-restart.timer <<'EOF'
[Unit]
Description=Restart Mirage container weekly
[Timer]
OnCalendar=Sun 04:00
RandomizedDelaySec=30m
Persistent=true
[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now mirage-weekly-restart.timer
systemctl list-timers mirage-weekly-restart.timer
```

The restart staggers across the cluster (different `OnCalendar` per host, or rely on `RandomizedDelaySec`) so consensus is never at risk of losing too many validators at once.

### Disk monitoring

`/root/.mirage/` grows steadily. At 80% full, it's time to either bump the disk or prune older state.

```bash
df -h /
du -sh /root/.mirage/* 2>/dev/null | sort -h | tail -10
```

---

## Verification checklist

After running everything above, the host should pass every line:

```bash
free -h | grep -E 'Mem|Swap'                        # Swap row shows 2.0Gi
swapon --show                                        # one line, /swapfile, 2G
sshd -T | grep -E 'permitroot|passwordauth'          # prohibit-password / no
ufw status | grep -E '22|80|443|26656|26657'         # five lines, all ALLOW
systemctl is-active fail2ban unattended-upgrades docker   # active x3
timedatectl | grep -E 'NTP service|synchronized'     # both yes/active
docker compose version                               # prints a v2.x version
ulimit -n                                            # 131072
sysctl vm.swappiness net.core.somaxconn              # 10 / 4096
```

Every one of those should match. If any doesn't, fix it before deploying the node. Once the host passes, proceed to [`deploy.md`](deploy.md).

---

## Hardening the existing fleet

The four existing validators (`159.203.114.27`, `64.23.136.132`, `146.190.108.140`, `139.59.9.96`) were provisioned before this guide existed. Audit each with:

```bash
for ip in 159.203.114.27 64.23.136.132 146.190.108.140 139.59.9.96; do
  echo "=== $ip ==="
  ssh -o ConnectTimeout=5 root@$ip '
    free -h | grep Swap;
    sshd -T | grep -E "^(permitrootlogin|passwordauthentication) ";
    ufw status | head -1;
    systemctl is-active fail2ban unattended-upgrades docker | tr "\n" " "; echo;
    docker compose version 2>&1 | head -1;
  '
done
```

Anything that doesn't match the verification checklist gets brought into compliance one node at a time, leaving at least 3 of 4 validators online during the work to keep consensus.
