#!/usr/bin/env bash
# deploy/harden_server.sh
# Complete OS hardening for a Mirage validator host. Idempotent; safe to re-run.
# Run as root on Ubuntu 24.04 LTS.
#
# Every step here corresponds to a bullet in docs/guides/server_setup.md
# and is motivated by a real incident or near-miss in production.
#
# Default behavior: fully harden the host.
#   - Write all config files.
#   - Enable all services (UFW, fail2ban, unattended-upgrades).
#   - Replace Ubuntu docker.io with the official docker-ce + compose plugin.
#   - Restart docker at the end if daemon.json changed (picks up log limits).
#   - Reboot the host at the end if /var/run/reboot-required exists.
#
# Use the opt-out flags below on existing production hosts only when you know
# the cluster can't absorb one of those side-effects right now.
#
# Flags:
#   --weekly-hour=NN       Hour (0-23) for the weekly Mirage container restart
#                          timer. Default 04. Stagger across the fleet so no
#                          two validators ever restart in the same window.
#   --no-migrate-docker    Skip the docker.io -> docker-ce migration.
#   --no-restart-docker    Skip the post-apply docker restart, even if
#                          daemon.json changed. Log-size limits will not
#                          take effect until docker is restarted manually.
#   --no-reboot            Skip the final reboot, even if a kernel update is
#                          pending. /var/run/reboot-required will remain,
#                          and the next unattended-upgrades window (03:30)
#                          will reboot on its own.
#   --dry-run              Print what would be done and exit.
#   -h, --help             This message.
#
# Typical rollout across a 4-validator cluster (one host at a time, wait
# for each to come back and confirm it is signing before moving on; no
# long soak required — hardening does not touch validator identity):
#   harden_server.sh --weekly-hour=04   # on val4
#   harden_server.sh --weekly-hour=05   # on val3
#   harden_server.sh --weekly-hour=06   # on val2
#   harden_server.sh --weekly-hour=07   # on val1

set -euo pipefail

WEEKLY_HOUR="04"
MIGRATE_DOCKER=1
RESTART_DOCKER=1
REBOOT_IF_NEEDED=1
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --weekly-hour=*)      WEEKLY_HOUR="${arg#*=}" ;;
        --no-migrate-docker)  MIGRATE_DOCKER=0 ;;
        --no-restart-docker)  RESTART_DOCKER=0 ;;
        --no-reboot)          REBOOT_IF_NEEDED=0 ;;
        --dry-run)            DRY_RUN=1 ;;
        -h|--help)
            sed -n '2,/^set -euo/p' "$0" | sed -n 's/^# \{0,1\}//p' | sed '$d'
            exit 0
            ;;
        *)
            echo "unknown flag: $arg" >&2
            echo "run with --help for usage" >&2
            exit 2
            ;;
    esac
done

if [[ ! "$WEEKLY_HOUR" =~ ^[0-9]{1,2}$ ]] || (( 10#$WEEKLY_HOUR > 23 )); then
    echo "--weekly-hour must be 0-23 (got: $WEEKLY_HOUR)" >&2
    exit 2
fi
WEEKLY_HOUR=$(printf '%02d' "$((10#$WEEKLY_HOUR))")

if [[ $EUID -ne 0 ]]; then
    echo "must be run as root" >&2
    exit 1
fi

if [[ -r /etc/os-release ]]; then
    . /etc/os-release
    if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != 24.04 ]]; then
        echo "only supported on Ubuntu 24.04 LTS (got: ${ID:-?} ${VERSION_ID:-?})" >&2
        exit 1
    fi
fi

say()  { echo;      echo "==> $*"; }
note() { echo "    $*"; }

run() {
    if (( DRY_RUN )); then
        echo "DRY-RUN: $*"
    else
        eval "$@"
    fi
}

DAEMON_JSON_CHANGED=0
DOCKER_ENGINE_TOUCHED=0

# write_file PATH CONTENT [CHANGE_VAR]
# Writes CONTENT to PATH only if different from the existing file. If
# CHANGE_VAR is given and the file was changed, sets that variable to 1.
write_file() {
    local path=$1 content=$2 change_var=${3:-}
    if (( DRY_RUN )); then
        echo "DRY-RUN: write $path"
        echo "$content" | sed 's/^/    | /'
        return
    fi
    mkdir -p "$(dirname "$path")"
    local tmp
    tmp=$(mktemp)
    printf '%s' "$content" > "$tmp"
    if ! cmp -s "$tmp" "$path" 2>/dev/null; then
        install -m 0644 -- "$tmp" "$path"
        note "wrote $path"
        [[ -n "$change_var" ]] && declare -g "$change_var=1"
    else
        note "$path already up to date"
    fi
    rm -f "$tmp"
}

# -----------------------------------------------------------------------------
# Step 1 — apt baseline
# -----------------------------------------------------------------------------
say "apt update + baseline packages"
export DEBIAN_FRONTEND=noninteractive
run 'apt-get -qq update'
run 'apt-get -qq -y install \
    ufw fail2ban unattended-upgrades \
    curl ca-certificates gnupg \
    htop iotop dstat jq'

# -----------------------------------------------------------------------------
# Step 2 — 2 GiB swap
# -----------------------------------------------------------------------------
say "Swap (2 GiB)"
if [[ ! -f /swapfile ]]; then
    run 'fallocate -l 2G /swapfile'
    run 'chmod 600 /swapfile'
    run 'mkswap /swapfile >/dev/null'
    run 'swapon /swapfile'
    grep -q '^/swapfile' /etc/fstab || run "echo '/swapfile none swap sw 0 0' >> /etc/fstab"
else
    note "/swapfile already exists"
    swapon --show | grep -q '^/swapfile' || run 'swapon /swapfile' || true
fi

# -----------------------------------------------------------------------------
# Step 3 — sysctl (swap + network + inotify)
# -----------------------------------------------------------------------------
say "sysctl (swap + network + inotify)"
write_file /etc/sysctl.d/99-mirage-swap.conf 'vm.swappiness = 10
vm.vfs_cache_pressure = 50
'
write_file /etc/sysctl.d/99-mirage-net.conf '# Raise connection backlogs (P2P + RPC + reverse proxy)
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096
net.ipv4.ip_local_port_range = 10240 65535

# Reuse TIME_WAIT sockets quickly
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15

# More room for the inotify watchers Docker / journald use
fs.inotify.max_user_watches = 524288
fs.inotify.max_user_instances = 512
'
run 'sysctl --system >/dev/null'

# -----------------------------------------------------------------------------
# Step 4 — ulimits (nofile 131072)
# -----------------------------------------------------------------------------
say "ulimits (nofile 131072)"
write_file /etc/security/limits.d/99-mirage.conf '*       soft    nofile  131072
*       hard    nofile  131072
root    soft    nofile  131072
root    hard    nofile  131072
'

# -----------------------------------------------------------------------------
# Step 5 — SSH hardening
#
# NOTE: sshd_config.d/*.conf files are applied in alphabetical order and the
# FIRST occurrence of a directive wins. Ubuntu cloud-init ships
# /etc/ssh/sshd_config.d/50-cloud-init.conf with PasswordAuthentication yes,
# so our override must sort BEFORE it. Hence 00-mirage-hardening.conf.
#
# Disabling PasswordAuthentication does NOT lock you out of DigitalOcean's
# "Launch Droplet Console" — that console is a hypervisor-level serial/VNC
# login via PAM, not SSH.
# -----------------------------------------------------------------------------
say "SSH hardening"
# Remove legacy-named file if a previous version of this script wrote it.
if [[ -f /etc/ssh/sshd_config.d/99-mirage-hardening.conf ]]; then
    run 'rm -f /etc/ssh/sshd_config.d/99-mirage-hardening.conf'
    note 'removed legacy /etc/ssh/sshd_config.d/99-mirage-hardening.conf'
fi
write_file /etc/ssh/sshd_config.d/00-mirage-hardening.conf 'PermitRootLogin prohibit-password
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
'
if (( ! DRY_RUN )); then
    sshd -t
    systemctl reload ssh
fi

# -----------------------------------------------------------------------------
# Step 6 — fail2ban
# -----------------------------------------------------------------------------
say "fail2ban"
write_file /etc/fail2ban/jail.local '[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true
'
run 'systemctl enable --now fail2ban >/dev/null 2>&1 || systemctl enable --now fail2ban'
run 'systemctl restart fail2ban'

# -----------------------------------------------------------------------------
# Step 7 — unattended security upgrades
# -----------------------------------------------------------------------------
say "unattended-upgrades"
write_file /etc/apt/apt.conf.d/20auto-upgrades 'APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
'
# Enable the 03:30 auto-reboot lines in 50unattended-upgrades. Only touches
# the two lines we care about; leaves the rest of the file alone.
if (( ! DRY_RUN )); then
    sed -i 's|^//\s*\(Unattended-Upgrade::Automatic-Reboot\s\+"\)|\1|'      /etc/apt/apt.conf.d/50unattended-upgrades
    sed -i 's|^//\s*\(Unattended-Upgrade::Automatic-Reboot-Time\s\+"\)|\1|' /etc/apt/apt.conf.d/50unattended-upgrades
    sed -i 's|^Unattended-Upgrade::Automatic-Reboot\s\+"false";|Unattended-Upgrade::Automatic-Reboot "true";|' /etc/apt/apt.conf.d/50unattended-upgrades
    sed -i 's|^Unattended-Upgrade::Automatic-Reboot-Time\s\+"[0-9:]\+";|Unattended-Upgrade::Automatic-Reboot-Time "03:30";|' /etc/apt/apt.conf.d/50unattended-upgrades
fi
run 'systemctl enable --now unattended-upgrades >/dev/null 2>&1 || systemctl enable --now unattended-upgrades'

# -----------------------------------------------------------------------------
# Step 8 — timezone / NTP
# -----------------------------------------------------------------------------
say "Timezone / NTP"
run 'timedatectl set-timezone Etc/UTC'
run 'timedatectl set-ntp true'

# -----------------------------------------------------------------------------
# Step 9 — UFW
# -----------------------------------------------------------------------------
say "UFW"
run 'ufw default deny incoming  >/dev/null'
run 'ufw default allow outgoing >/dev/null'
run 'ufw default deny routed    >/dev/null'
run "ufw allow 22/tcp    comment 'SSH'                      >/dev/null"
run "ufw allow 80/tcp    comment 'HTTP (cert renewal + FE)' >/dev/null"
run "ufw allow 443/tcp   comment 'HTTPS'                    >/dev/null"
run "ufw allow 26656/tcp comment 'CometBFT P2P'             >/dev/null"
run "ufw allow 26657/tcp comment 'CometBFT RPC'             >/dev/null"
run 'ufw --force enable >/dev/null'

# -----------------------------------------------------------------------------
# Step 10 — Docker engine + daemon.json
#
# On a host running Ubuntu's docker.io, this removes it and installs the
# official docker-ce + docker-compose-plugin stack. On a host already running
# docker-ce, it upgrades to the latest available version. In both cases the
# apt install of docker-ce restarts the docker daemon (which auto-restarts
# containers with restart=unless-stopped), so we don't need to restart it
# ourselves afterwards — unless only daemon.json changed and we want the new
# log-size limits to take effect.
# -----------------------------------------------------------------------------
say "Docker"

docker_ce_present=0
docker_io_present=0
if dpkg -l docker-ce 2>/dev/null | grep -q '^ii'; then docker_ce_present=1; fi
if dpkg -l docker.io  2>/dev/null | grep -q '^ii'; then docker_io_present=1; fi

if (( MIGRATE_DOCKER )); then
    # Docker's official apt repo (idempotent).
    run 'install -m 0755 -d /etc/apt/keyrings'
    if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
        run 'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg'
        run 'chmod a+r /etc/apt/keyrings/docker.gpg'
    fi
    codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
    write_file /etc/apt/sources.list.d/docker.list \
"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $codename stable
"
    run 'apt-get -qq update'

    if (( docker_io_present )); then
        say "Migrating docker.io -> docker-ce (mirage container will be briefly stopped)"
        # This stops docker.service and all running containers. docker-ce
        # install below will start its own docker.service and the mirage
        # container will come back on its unless-stopped policy.
        run 'apt-get -qq -y remove docker.io containerd || true'
        DOCKER_ENGINE_TOUCHED=1
    fi

    # Install-or-upgrade to latest docker-ce. `install` is idempotent; if
    # there is a newer version available it updates (and restarts docker).
    before=$(dpkg-query -W -f='${Version}' docker-ce 2>/dev/null || echo "")
    run 'apt-get -qq -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin'
    after=$(dpkg-query -W -f='${Version}' docker-ce 2>/dev/null || echo "")
    if [[ "$before" != "$after" ]]; then
        note "docker-ce $before -> $after"
        DOCKER_ENGINE_TOUCHED=1
    fi
    run 'systemctl enable --now docker >/dev/null 2>&1 || systemctl enable --now docker'
else
    note "skipping docker engine migration (--no-migrate-docker)"
fi

# daemon.json log limits. If this file changed, docker needs a restart for
# it to take effect — unless we just reinstalled docker above, which already
# restarted the daemon and picked up whatever's on disk.
write_file /etc/docker/daemon.json '{
  "log-driver": "json-file",
  "log-opts": { "max-size": "100m", "max-file": "5" }
}
' DAEMON_JSON_CHANGED

# -----------------------------------------------------------------------------
# Step 11 — Weekly container restart timer
# -----------------------------------------------------------------------------
say "Weekly mirage container restart (Sun ${WEEKLY_HOUR}:00 UTC ±30m)"
write_file /etc/systemd/system/mirage-weekly-restart.service '[Unit]
Description=Weekly restart of Mirage container

[Service]
Type=oneshot
ExecStart=/usr/bin/docker restart mirage
'
write_file /etc/systemd/system/mirage-weekly-restart.timer "[Unit]
Description=Restart Mirage container weekly

[Timer]
OnCalendar=Sun ${WEEKLY_HOUR}:00
RandomizedDelaySec=30m
Persistent=true

[Install]
WantedBy=timers.target
"
run 'systemctl daemon-reload'
run 'systemctl enable --now mirage-weekly-restart.timer >/dev/null'

# -----------------------------------------------------------------------------
# Step 12 — docker restart (only when something that requires it changed and
# the user didn't opt out)
# -----------------------------------------------------------------------------
if (( RESTART_DOCKER )) && (( DAEMON_JSON_CHANGED )) && (( DOCKER_ENGINE_TOUCHED == 0 )); then
    say "Restarting docker to apply daemon.json (mirage container will briefly go down)"
    run 'systemctl restart docker'
    for _ in $(seq 1 30); do
        if docker inspect -f '{{.State.Running}}' mirage 2>/dev/null | grep -q true; then
            note "mirage container running again"
            break
        fi
        sleep 2
    done
elif (( DOCKER_ENGINE_TOUCHED )); then
    note "docker engine was (re)installed above; daemon.json already in effect"
elif (( DAEMON_JSON_CHANGED )) && (( RESTART_DOCKER == 0 )); then
    note "daemon.json changed but --no-restart-docker set; log limits will apply on next docker restart"
fi

# -----------------------------------------------------------------------------
# Step 13 — verification
# -----------------------------------------------------------------------------
say "Verification"
echo "--- free -h ---";                   free -h | grep -E 'Mem|Swap'
echo "--- swapon ---";                    swapon --show
echo "--- sshd (effective) ---";          sshd -T 2>/dev/null | grep -E '^(permitrootlogin|passwordauthentication|pubkeyauthentication|kbdinteractiveauthentication|challengeresponseauthentication|permitemptypasswords|x11forwarding|maxauthtries|logingracetime|clientaliveinterval|clientalivecountmax) '
echo "--- ufw ---";                       ufw status | sed -n '1,12p'
echo "--- services ---";                  for svc in ssh fail2ban unattended-upgrades docker; do
                                               printf "    %-22s %s/%s\n" "$svc" "$(systemctl is-active $svc 2>/dev/null)" "$(systemctl is-enabled $svc 2>/dev/null)"
                                          done
echo "--- sysctl ---";                    sysctl vm.swappiness net.core.somaxconn net.ipv4.tcp_max_syn_backlog net.ipv4.ip_local_port_range fs.inotify.max_user_watches | sed 's/^/    /'
echo "--- docker ---";                    docker --version; docker compose version 2>&1 | head -1 || true
echo "--- weekly timer ---";              systemctl list-timers mirage-weekly-restart.timer --no-pager 2>/dev/null | sed -n '1,3p'
echo "--- container ---";                 docker inspect mirage --format '    {{.State.Status}} image={{.Config.Image}} restart={{.HostConfig.RestartPolicy.Name}}' 2>/dev/null || echo "    (no mirage container)"

# -----------------------------------------------------------------------------
# Step 14 — reboot if kernel update is pending
# -----------------------------------------------------------------------------
if [[ -f /var/run/reboot-required ]]; then
    if (( REBOOT_IF_NEEDED )); then
        say "Kernel update pending — rebooting in 10s (Ctrl+C to cancel)"
        note "$(cat /var/run/reboot-required 2>/dev/null || true)"
        sleep 10
        run 'systemctl reboot'
        exit 0
    else
        echo
        echo "NOTE: /var/run/reboot-required exists but --no-reboot was set."
        echo "      Reboot manually when the cluster can absorb ~60s of downtime for this host:"
        echo "        $(cat /var/run/reboot-required 2>/dev/null || true)"
    fi
fi

echo
echo "Hardening complete."
