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
#   --weekly-day=N         Day of week (1=Mon .. 7=Sun) for the weekly Mirage
#                          container restart timer. Default 1 (Mon). Keep it
#                          clear of the off-site backup window, which also
#                          stops containers — see MIRAGE_BACKUP_WINDOW in the
#                          operator's .env.
#   --weekly-hour=NN       Hour (0-23) for the weekly Mirage container restart
#                          timer (${WEEKLY_DAY_NAME} ${WEEKLY_HOUR}:00 UTC).
#                          Default 08. Stagger across the fleet so no two
#                          validators ever restart in the same window.
#   --upgrade-day=N        Day of week (1=Mon .. 7=Sun) for the weekly full
#                          OS upgrade + reboot. REQUIRED to enroll the host
#                          in the per-host weekly upgrade policy. Stagger
#                          across the fleet so only one validator reboots
#                          per day. If omitted, daily security-only auto
#                          upgrades still happen (no reboot) and the host
#                          must be upgraded manually.
#   --upgrade-hour=NN      Hour (0-23) for the weekly OS upgrade. Default 04.
#   --no-migrate-docker    Skip the docker.io -> docker-ce migration.
#   --no-restart-docker    Skip the post-apply docker restart, even if
#                          daemon.json changed. Log-size limits will not
#                          take effect until docker is restarted manually.
#   --no-reboot            Skip the final reboot, even if a kernel update is
#                          pending. /var/run/reboot-required will remain,
#                          and the next weekly upgrade window will pick it
#                          up (after pre-flight checks).
#   --dry-run              Print what would be done and exit.
#   -h, --help             This message.
#
# Upgrade policy after hardening:
#   - Daily: unattended-upgrades applies security patches (no reboot).
#   - Weekly: mirage-weekly-upgrade.timer runs full-upgrade + reboot-if-needed
#     on --upgrade-day at --upgrade-hour, but ONLY after a pre-flight check
#     confirms the validator is healthy (container running, RPC responsive,
#     not catching up, recent block). Pre-flight failure aborts the run and
#     surfaces in `journalctl -u mirage-weekly-upgrade`.
#
# Rollout across a 4-validator cluster: one host at a time, waiting for each
# to come back and confirm it is signing before moving on. No long soak is
# required — hardening does not touch validator identity.
#
#   harden_server.sh --weekly-hour=NN --upgrade-day=N
#
# Give each host its own --upgrade-day and its own --weekly-hour, so only one
# validator is ever in a maintenance window. Keep the restart hours a few hours
# clear of the upgrade slot too: an upgrade may reboot, and a container restart
# firing into a half-finished apt transaction is worse than either alone.
# Leave part of the week empty so issues that land near a weekend don't
# immediately trigger reboots.
#
# The per-host assignment is not recorded here — this repo is public. See
# MIRAGE_WEEKLY_RESTART_SLOTS / MIRAGE_WEEKLY_UPGRADE_SLOTS in the operator's
# .env (docs/guides/server_setup.md explains the constraints they satisfy).

set -euo pipefail

WEEKLY_DAY="1"
WEEKLY_HOUR="08"
UPGRADE_DAY=""
UPGRADE_HOUR="04"
MIGRATE_DOCKER=1
RESTART_DOCKER=1
REBOOT_IF_NEEDED=1
DRY_RUN=0

for arg in "$@"; do
    case "$arg" in
        --weekly-day=*)       WEEKLY_DAY="${arg#*=}" ;;
        --weekly-hour=*)      WEEKLY_HOUR="${arg#*=}" ;;
        --upgrade-day=*)      UPGRADE_DAY="${arg#*=}" ;;
        --upgrade-hour=*)     UPGRADE_HOUR="${arg#*=}" ;;
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

DAY_NAMES=(Mon Tue Wed Thu Fri Sat Sun)

if [[ ! "$WEEKLY_DAY" =~ ^[1-7]$ ]]; then
    echo "--weekly-day must be 1-7 (1=Mon .. 7=Sun); got: $WEEKLY_DAY" >&2
    exit 2
fi
WEEKLY_DAY_NAME="${DAY_NAMES[$((WEEKLY_DAY-1))]}"

if [[ ! "$WEEKLY_HOUR" =~ ^[0-9]{1,2}$ ]] || (( 10#$WEEKLY_HOUR > 23 )); then
    echo "--weekly-hour must be 0-23 (got: $WEEKLY_HOUR)" >&2
    exit 2
fi
WEEKLY_HOUR=$(printf '%02d' "$((10#$WEEKLY_HOUR))")

if [[ ! "$UPGRADE_HOUR" =~ ^[0-9]{1,2}$ ]] || (( 10#$UPGRADE_HOUR > 23 )); then
    echo "--upgrade-hour must be 0-23 (got: $UPGRADE_HOUR)" >&2
    exit 2
fi
UPGRADE_HOUR=$(printf '%02d' "$((10#$UPGRADE_HOUR))")

UPGRADE_DAY_NAME=""
if [[ -n "$UPGRADE_DAY" ]]; then
    if [[ ! "$UPGRADE_DAY" =~ ^[1-7]$ ]]; then
        echo "--upgrade-day must be 1-7 (1=Mon .. 7=Sun); got: $UPGRADE_DAY" >&2
        exit 2
    fi
    UPGRADE_DAY_NAME="${DAY_NAMES[$((UPGRADE_DAY-1))]}"
fi

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
else
    echo "/etc/os-release missing" >&2
    exit 1
fi

arch=$(dpkg --print-architecture)
case "$arch" in
    amd64|arm64) ;;
    *)
        echo "unsupported arch $arch (need amd64 or arm64)" >&2
        exit 1
        ;;
esac

if command -v systemd-detect-virt >/dev/null 2>&1; then
    if systemd-detect-virt --quiet --container; then
        echo "container virtualization ($(systemd-detect-virt)) is not supported; need KVM/Xen/Hyper-V/VMware/bare metal" >&2
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
# Step 1 — apt upgrade and baseline
# -----------------------------------------------------------------------------
say "apt update + full upgrade + baseline packages"
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_MODE=a
run 'apt-get -qq update'
run 'apt-get -qq -y \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold" \
    full-upgrade'
run 'apt-get -qq -y install \
    ufw fail2ban unattended-upgrades \
    curl ca-certificates gnupg \
    htop iotop dstat jq'

# -----------------------------------------------------------------------------
# Step 2 — sysctl (memory + network + inotify)
# -----------------------------------------------------------------------------
# No swapfile. It was originally added on the theory that memory pressure caused
# the 2026-06-16 AppHash divergence; the postmortem refuted that (the node
# diverged while idle, on a host that already had swap, with zero OOM kills) and
# the real IAVL prune-hole cause was fixed in v1.29.4/v1.29.5. Nine days of sar
# history across the fleet then showed swap holding under 50 MiB at ~0 pages/sec
# while memory peaked at 38%, so it was carrying no load.
#
# vm.swappiness stays because existing hosts keep the /swapfile this script used
# to create; it must remain biased against swapping there.
say "sysctl (memory + network + inotify)"
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
# Step 3 — ulimits (nofile 131072)
# -----------------------------------------------------------------------------
say "ulimits (nofile 131072)"
write_file /etc/security/limits.d/99-mirage.conf '*       soft    nofile  131072
*       hard    nofile  131072
root    soft    nofile  131072
root    hard    nofile  131072
'

# -----------------------------------------------------------------------------
# Step 4 — SSH hardening
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
if [[ ! -s /root/.ssh/authorized_keys ]] || ! ssh-keygen -l -f /root/.ssh/authorized_keys >/dev/null 2>&1; then
    echo "ERROR: no valid SSH public key in /root/.ssh/authorized_keys; aborting before disabling password auth" >&2
    exit 1
fi
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
    # sshd -t aborts with "Missing privilege separation directory" when /run/sshd
    # is absent. Current Ubuntu 24.04 images socket-activate SSH, so ssh.service
    # is inactive and systemd has removed its RuntimeDirectory.
    install -d -m 0755 /run/sshd
    sshd -t
    # Socket activation means each connection gets its own ssh@.service, so there
    # is no long-running unit to reload; the listener has to be restarted instead.
    if systemctl is-active --quiet ssh.service; then
        systemctl reload ssh.service
    elif systemctl is-active --quiet ssh.socket; then
        systemctl restart ssh.socket
    else
        echo "ERROR: neither ssh.service nor ssh.socket is active; refusing to leave SSH unconfigured" >&2
        exit 1
    fi
fi

# -----------------------------------------------------------------------------
# Step 5 — fail2ban
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
# Step 6 — unattended security upgrades (daily, NO reboot)
#
# Security patches apply daily via unattended-upgrades. Reboots are NOT done
# here — they happen in the per-host weekly slot configured in Step 11.5
# (mirage-weekly-upgrade.timer) so the fleet never reboots in lockstep.
# -----------------------------------------------------------------------------
say "unattended-upgrades (daily security-only, no reboot)"
write_file /etc/apt/apt.conf.d/20auto-upgrades 'APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
'
# Force Automatic-Reboot to "false". Uncomment the line first if it's still
# the shipped commented default so our value sticks.
if (( ! DRY_RUN )); then
    sed -i 's|^//\s*\(Unattended-Upgrade::Automatic-Reboot\s\+"\)|\1|' /etc/apt/apt.conf.d/50unattended-upgrades
    sed -i 's|^Unattended-Upgrade::Automatic-Reboot\s\+"[a-z]\+";|Unattended-Upgrade::Automatic-Reboot "false";|' /etc/apt/apt.conf.d/50unattended-upgrades
fi
run 'systemctl enable --now unattended-upgrades >/dev/null 2>&1 || systemctl enable --now unattended-upgrades'

# -----------------------------------------------------------------------------
# Step 7 — timezone / NTP
# -----------------------------------------------------------------------------
say "Timezone / NTP"
run 'timedatectl set-timezone Etc/UTC'
run 'timedatectl set-ntp true'

# -----------------------------------------------------------------------------
# Step 8 — UFW
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
# Step 9 — Docker engine + daemon.json
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
# Step 10 — Weekly container restart timer
#
# Two other things bounce these containers on a schedule, and this timer has to
# stay clear of both: the off-site backup, which stops each container while it
# streams state, and mirage-weekly-upgrade.timer, which may reboot. Voting
# power is split evenly across the validators, so quorum needs all but one —
# two down at the same time stalls the chain.
#
# Hence one host per hour, on a day that is not the backup day. The concrete
# slots live in the operator's .env, not here.
# -----------------------------------------------------------------------------
say "Weekly mirage container restart (${WEEKLY_DAY_NAME} ${WEEKLY_HOUR}:00 UTC ±30m)"
write_file /usr/local/sbin/mirage-weekly-restart.sh '#!/usr/bin/env bash
set -euo pipefail
SAFETY_BLOCKS="${UPGRADE_PREFLIGHT_SAFETY_BLOCKS:-500}"

if ! docker inspect mirage --format "{{.State.Status}}" 2>/dev/null | grep -qx running; then
  echo "mirage container not running; skip weekly restart"
  exit 0
fi

plan=$(curl -fsS --max-time 5 http://127.0.0.1:1317/cosmos/upgrade/v1beta1/current_plan || true)
plan_name=$(echo "$plan" | python3 -c "import json,sys
try:
    p=json.load(sys.stdin).get(\"plan\") or {}
    print(p.get(\"name\") or \"\")
except Exception:
    print(\"\")
" 2>/dev/null || true)
if [[ -n "$plan_name" ]]; then
  plan_h=$(echo "$plan" | python3 -c "import json,sys; p=json.load(sys.stdin).get(\"plan\") or {}; print(int(p.get(\"height\") or 0))")
  height=$(curl -fsS --max-time 5 http://127.0.0.1:26657/status | python3 -c "import json,sys; print(int(json.load(sys.stdin)[\"result\"][\"sync_info\"][\"latest_block_height\"]))")
  remaining=$((plan_h - height))
  if (( remaining >= 0 && remaining <= SAFETY_BLOCKS )); then
    echo "upgrade plan $plan_name in $remaining blocks; skipping weekly restart"
    exit 0
  fi
fi

exec /usr/bin/docker restart mirage
'
if (( ! DRY_RUN )); then
    chmod 0755 /usr/local/sbin/mirage-weekly-restart.sh
fi
write_file /etc/systemd/system/mirage-weekly-restart.service '[Unit]
Description=Weekly restart of Mirage container

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/mirage-weekly-restart.sh
'
write_file /etc/systemd/system/mirage-weekly-restart.timer "[Unit]
Description=Restart Mirage container weekly (${WEEKLY_DAY_NAME} ${WEEKLY_HOUR}:00 UTC ±30m)

[Timer]
OnCalendar=${WEEKLY_DAY_NAME} ${WEEKLY_HOUR}:00
RandomizedDelaySec=30m
Persistent=true

[Install]
WantedBy=timers.target
"
run 'systemctl daemon-reload'
run 'systemctl enable --now mirage-weekly-restart.timer >/dev/null'

# -----------------------------------------------------------------------------
# Step 10.5 — Weekly full OS upgrade + reboot (per-host day, with pre-flight)
#
# Drops the daily kernel-auto-reboot model (which would fire fleet-wide at the
# same time when Ubuntu ships a kernel) in favor of a per-host weekly slot.
# Each validator picks one day of the week via --upgrade-day so only one host
# is down for an upgrade-reboot per 24h window.
#
# The script aborts cleanly if the validator is not currently healthy. That
# failure surfaces in `journalctl -u mirage-weekly-upgrade` so the operator
# can investigate and re-run manually after fixing the underlying issue.
# -----------------------------------------------------------------------------
if [[ -n "$UPGRADE_DAY_NAME" ]]; then
    say "Weekly OS upgrade (${UPGRADE_DAY_NAME} ${UPGRADE_HOUR}:00 UTC ±30m)"

    write_file /usr/local/sbin/mirage-weekly-upgrade.sh '#!/usr/bin/env bash
# Weekly OS upgrade for a Mirage validator host. Written by harden_server.sh.
# Aborts unless the validator is healthy. Reboots only if apt says so.

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

log() { echo "[$(date -u +%FT%TZ)] $*"; }

# --- Pre-flight ---
if ! docker inspect mirage --format "{{.State.Status}}" 2>/dev/null | grep -qx running; then
    log "ABORT: mirage container is not running"
    exit 1
fi

if ! status=$(curl -fsS --max-time 5 http://127.0.0.1:26657/status 2>/dev/null); then
    log "ABORT: CometBFT RPC (127.0.0.1:26657) not responding"
    exit 1
fi

catching_up=$(echo "$status" | jq -r ".result.sync_info.catching_up")
if [[ "$catching_up" != "false" ]]; then
    log "ABORT: node is catching up (catching_up=$catching_up)"
    exit 1
fi

latest=$(echo "$status" | jq -r ".result.sync_info.latest_block_time")
if ! latest_epoch=$(date -d "$latest" +%s 2>/dev/null); then
    log "ABORT: could not parse latest_block_time ($latest)"
    exit 1
fi
age=$(( $(date -u +%s) - latest_epoch ))
if (( age < 0 || age > 60 )); then
    log "ABORT: latest block is ${age}s old (expected 0-60s)"
    exit 1
fi

log "Pre-flight OK (latest block ${age}s ago). Starting full-upgrade."

# --- Upgrade ---
APT_OPTS=(-qq -y \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold")

apt-get -qq update
apt-get "${APT_OPTS[@]}" full-upgrade
apt-get "${APT_OPTS[@]}" autoremove --purge

# --- Reboot if needed ---
if [[ -f /var/run/reboot-required ]]; then
    reason=$(cat /var/run/reboot-required 2>/dev/null || true)
    log "Reboot required: $reason — rebooting now"
    systemctl reboot
else
    log "Upgrade complete. No reboot needed."
fi
'
    if (( ! DRY_RUN )); then
        chmod 0755 /usr/local/sbin/mirage-weekly-upgrade.sh
    fi

    write_file /etc/systemd/system/mirage-weekly-upgrade.service '[Unit]
Description=Weekly full OS upgrade for Mirage validator (with pre-flight)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/mirage-weekly-upgrade.sh
'
    write_file /etc/systemd/system/mirage-weekly-upgrade.timer "[Unit]
Description=Weekly full OS upgrade (${UPGRADE_DAY_NAME} ${UPGRADE_HOUR}:00 UTC ±30m)

[Timer]
OnCalendar=${UPGRADE_DAY_NAME} ${UPGRADE_HOUR}:00
RandomizedDelaySec=30m
Persistent=true

[Install]
WantedBy=timers.target
"
    run 'systemctl daemon-reload'
    run 'systemctl enable --now mirage-weekly-upgrade.timer >/dev/null'
else
    note "skipping weekly OS upgrade timer (no --upgrade-day specified)"
    note "you must upgrade this host manually or re-run with --upgrade-day=N (1=Mon..7=Sun)"
fi

# -----------------------------------------------------------------------------
# Step 11 — docker restart (only when something that requires it changed and
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
# Step 12 — verification
# -----------------------------------------------------------------------------
say "Verification"
echo "--- free -h ---";                   free -h | grep -E 'Mem|Swap'
echo "--- sshd (effective) ---";          sshd -T 2>/dev/null | grep -E '^(permitrootlogin|passwordauthentication|pubkeyauthentication|kbdinteractiveauthentication|challengeresponseauthentication|permitemptypasswords|x11forwarding|maxauthtries|logingracetime|clientaliveinterval|clientalivecountmax) '
echo "--- ufw ---";                       ufw status | sed -n '1,12p'
ssh_unit=ssh.service
systemctl is-active --quiet ssh.service || ssh_unit=ssh.socket
echo "--- services ---";                  for svc in "$ssh_unit" fail2ban unattended-upgrades docker; do
                                               printf "    %-22s %s/%s\n" "$svc" "$(systemctl is-active $svc 2>/dev/null)" "$(systemctl is-enabled $svc 2>/dev/null)"
                                          done
echo "--- sysctl ---";                    sysctl vm.swappiness net.core.somaxconn net.ipv4.tcp_max_syn_backlog net.ipv4.ip_local_port_range fs.inotify.max_user_watches | sed 's/^/    /'
echo "--- docker ---";                    docker --version; docker compose version 2>&1 | head -1 || true
echo "--- weekly timers ---";             systemctl list-timers 'mirage-weekly-*.timer' --no-pager 2>/dev/null | sed -n '1,5p'
echo "--- auto-reboot ---";               grep -E '^[^/]*Unattended-Upgrade::Automatic-Reboot\s' /etc/apt/apt.conf.d/50unattended-upgrades 2>/dev/null | sed 's/^/    /'
echo "--- container ---";                 docker inspect mirage --format '    {{.State.Status}} image={{.Config.Image}} restart={{.HostConfig.RestartPolicy.Name}}' 2>/dev/null || echo "    (no mirage container)"

# -----------------------------------------------------------------------------
# Step 13 — reboot if kernel update is pending
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
