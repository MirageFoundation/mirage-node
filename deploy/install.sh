#!/usr/bin/env bash
# Mirage node installer. Truncation-safe: every statement is inside a function
# except the final `main "$@"` call. A partial download defines functions and
# runs nothing.
#
#   curl -fsSL https://raw.githubusercontent.com/MirageFoundation/mirage-node/prod/deploy/install.sh | bash

set -euo pipefail

STATE_DIR=/var/lib/mirage/install
STATE_FILE="$STATE_DIR/state"
DOMAIN_ARG=""
MNEMONIC=""
IMAGE=""
USERNAME=""
ADDRESS=""
MANIFEST_DIR=""
TEMP_MANIFEST_DIR=""
PUBLIC_IP=""
PUBLIC_IP6=""

GITHUB_RAW="https://raw.githubusercontent.com/MirageFoundation/mirage-node/prod"
RELEASE_MANIFEST_URL="${MIRAGE_MANIFEST_URL:-$GITHUB_RAW/release/manifest.json}"
NETWORK_MANIFEST_URL="${MIRAGE_NETWORK_URL:-$GITHUB_RAW/release/network.json}"
BOOTSTRAP_BASE="${MIRAGE_MANIFEST_MIRROR:-$GITHUB_RAW/deploy}"

# Fingerprint of deploy/hosttools/pubkey.pem (raw ed25519 hex). Stable across releases.
EXPECTED_PUBKEY_FINGERPRINT="679a39294dc9639170ca9cb4010c44cc71dd153fa2029f2e73969bff6d86c0a8"
EXPECTED_VERIFY_SHA256="9296945b68e466a526536c48cb1e68a6ecf07c9d705791e8b3a624a3c7d5df1f"
EXPECTED_HARDEN_SHA256="3412205a921678d22df5448facd07b1d915f0d768a6ae350a1e5e678ebd6bb47"

die() { echo "ERROR: $*" >&2; exit 1; }

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --domain) DOMAIN_ARG="${2:-}"; shift 2 ;;
      --domain=*) DOMAIN_ARG="${1#*=}"; shift ;;
      -h|--help)
        echo "usage: install.sh [--domain example.com]"
        exit 0
        ;;
      *) die "unknown flag: $1" ;;
    esac
  done
  if [[ -n "$DOMAIN_ARG" && ! "$DOMAIN_ARG" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$ ]]; then
    die "--domain must be a hostname like example.com (got '$DOMAIN_ARG')"
  fi
}

require_root() {
  if [[ ${EUID} -ne 0 ]]; then
    die "must be run as root"
  fi
}

require_tty() {
  # In `curl ... | bash`, stdin is the script stream. Secrets and confirmations
  # must use the controlling terminal directly or the documented one-liner can
  # never become interactive.
  if [[ ! -t 1 ]] || ! : </dev/tty 2>/dev/null; then
    die "install must run on an interactive SSH session with a controlling TTY"
  fi
}

load_or_init_state() {
  mkdir -p "$STATE_DIR"
  if [[ ! -f "$STATE_FILE" ]]; then
    echo "preflight" > "$STATE_FILE"
  fi
}

advance_state() {
  echo "$1" > "$STATE_FILE"
}

current_state() {
  cat "$STATE_FILE"
}

state_at_least() {
  local order=(preflight hardened verified pulled configured identity launched enrolled_timer done)
  local cur want c=-1 w=-1 i
  cur=$(current_state)
  want="$1"
  for i in "${!order[@]}"; do
    [[ "${order[$i]}" == "$cur" ]] && c=$i
    [[ "${order[$i]}" == "$want" ]] && w=$i
  done
  if (( c < 0 )); then
    die "unrecognized install state '$cur' in $STATE_FILE; delete $STATE_DIR to start over"
  fi
  if (( w < 0 )); then
    die "internal error: unknown state '$want'"
  fi
  (( c >= w ))
}

preflight_os() {
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != 24.04 ]]; then
      die "only supported on Ubuntu 24.04 LTS (got: ${ID:-?} ${VERSION_ID:-?})"
    fi
  else
    die "/etc/os-release missing"
  fi
  local arch
  arch=$(dpkg --print-architecture)
  # Released images are linux/amd64 only. Passing preflight on arm64 would just
  # move the failure to `docker pull`, where the error is far less clear.
  if [[ "$arch" != amd64 ]]; then
    die "unsupported arch $arch; released images are linux/amd64 only"
  fi
  if command -v systemd-detect-virt >/dev/null 2>&1; then
    if systemd-detect-virt --quiet --container; then
      die "container virtualization ($(systemd-detect-virt)) is not supported; need KVM/Xen/Hyper-V/VMware/bare metal"
    fi
  fi
  # Thresholds below are measured against the running validators, not guessed. Both
  # sit on a 4 GB / 2 vCPU plan that reports 3915 MiB, with the node at ~1.3 GiB
  # RSS, 47 MiB of 2 GiB swap touched, no OOM kill and no stall in memory pressure.
  local mem_kb mem_mib
  mem_kb=$(awk '/MemTotal:/ {print $2}' /proc/meminfo)
  mem_mib=$((mem_kb / 1024))
  if (( mem_mib < 3800 )); then
    die "need a 4 GB RAM VM with at least 3800 MiB visible after provider overhead (got ${mem_mib} MiB)"
  fi
  # A live validator occupies ~15 GiB in total: 2.2 GiB image, ~1 GiB of pruned
  # chain data (~8 days retained), ~2 GiB Postgres and ~1 GiB logs, on top of
  # Ubuntu. Logs and the indexer add a few GiB a month, hence the headroom warning.
  local disk_b disk_gib
  disk_b=$(df -B1 / | awk 'NR==2 {print $4}')
  disk_gib=$((disk_b / 1024 / 1024 / 1024))
  if (( disk_gib < 20 )); then
    die "need at least 20 GiB free on / (got ${disk_gib} GiB)"
  fi
  if (( disk_gib < 40 )); then
    echo "WARNING: 40 GiB free is recommended; logs and the indexer grow a few GiB per month (got ${disk_gib} GiB)"
  fi
  if [[ ! -s /root/.ssh/authorized_keys ]] || ! ssh-keygen -l -f /root/.ssh/authorized_keys >/dev/null 2>&1; then
    die "no valid SSH public key in /root/.ssh/authorized_keys; aborting before disabling password auth"
  fi
}

# Raw ed25519 key is the last 32 bytes of the DER SubjectPublicKeyInfo. openssl
# and od are both in the base image, so this runs before harden installs anything.
pubkey_fingerprint() {
  openssl pkey -pubin -in "$1" -outform DER | tail -c 32 | od -An -v -tx1 | tr -d ' \n'
}

write_embedded_pubkey() {
  mkdir -p /usr/local/share/mirage
  cat > /usr/local/share/mirage/pubkey.pem <<'PUB'
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAZ5o5KU3JY5Fwypy0AQxEzHHdFT+iAp8uc5ab/22GwKg=
-----END PUBLIC KEY-----
PUB
  chmod 644 /usr/local/share/mirage/pubkey.pem
  local fp
  fp=$(pubkey_fingerprint /usr/local/share/mirage/pubkey.pem)
  if [[ "$fp" != "$EXPECTED_PUBKEY_FINGERPRINT" ]]; then
    die "embedded pubkey fingerprint $fp does not match $EXPECTED_PUBKEY_FINGERPRINT"
  fi
}

fetch_manifests() {
  MANIFEST_DIR=$(mktemp -d)
  TEMP_MANIFEST_DIR="$MANIFEST_DIR"
  trap 'rm -rf "$TEMP_MANIFEST_DIR"' EXIT
  local base
  base="${MIRAGE_MANIFEST_MIRROR:-}"
  local rel_url net_url
  rel_url="$RELEASE_MANIFEST_URL"
  net_url="$NETWORK_MANIFEST_URL"
  if [[ -n "$base" ]]; then
    rel_url="${base%/}/manifest.json"
    net_url="${base%/}/network.json"
  fi
  curl -fsSL "$rel_url" -o "$MANIFEST_DIR/manifest.json"
  curl -fsSL "${rel_url}.sig" -o "$MANIFEST_DIR/manifest.json.sig"
  curl -fsSL "$net_url" -o "$MANIFEST_DIR/network.json"
  curl -fsSL "${net_url}.sig" -o "$MANIFEST_DIR/network.json.sig"
}

pin_manifests() {
  local pinned="$STATE_DIR/manifests"
  mkdir -p "$pinned"
  local name
  for name in manifest.json manifest.json.sig network.json network.json.sig; do
    install -m 0600 "$MANIFEST_DIR/$name" "$pinned/$name.tmp"
    mv "$pinned/$name.tmp" "$pinned/$name"
  done
  MANIFEST_DIR="$pinned"
}

use_pinned_manifests() {
  MANIFEST_DIR="$STATE_DIR/manifests"
  local name
  for name in manifest.json manifest.json.sig network.json network.json.sig; do
    if [[ ! -f "$MANIFEST_DIR/$name" ]]; then
      die "install state is verified but pinned manifest is missing: $MANIFEST_DIR/$name"
    fi
  done
}

verify_manifests() {
  python3 /usr/local/share/mirage/release_verify.py verify \
    --manifest "$MANIFEST_DIR/network.json" \
    --signature "$MANIFEST_DIR/network.json.sig" \
    --pubkey /usr/local/share/mirage/pubkey.pem
  python3 /usr/local/share/mirage/release_verify.py verify \
    --manifest "$MANIFEST_DIR/manifest.json" \
    --signature "$MANIFEST_DIR/manifest.json.sig" \
    --pubkey /usr/local/share/mirage/pubkey.pem
  local peers
  peers=$(jq -r '.persistent_peers | length' "$MANIFEST_DIR/network.json")
  if [[ "$peers" -lt 1 ]]; then
    die "network manifest has no persistent_peers; a joining node cannot dial the network"
  fi
  local rpc_n
  rpc_n=$(jq -r '.rpc | length' "$MANIFEST_DIR/network.json")
  if [[ "$rpc_n" -lt 2 ]]; then
    die "network manifest needs at least two rpc URLs"
  fi
  local min_release release_version
  min_release=$(jq -r '.min_release' "$MANIFEST_DIR/network.json")
  release_version=$(jq -r '.version' "$MANIFEST_DIR/manifest.json")
  if ! version_at_least "$release_version" "$min_release"; then
    die "release manifest is $release_version but the network requires at least $min_release"
  fi
}

# Compare vX.Y.Z strings. Returns 0 when $1 >= $2.
version_at_least() {
  local have="$1" want="$2"
  if [[ ! "$have" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ || ! "$want" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    die "cannot compare versions '$have' and '$want'"
  fi
  local -a h w
  IFS=. read -r -a h <<<"${have#v}"
  IFS=. read -r -a w <<<"${want#v}"
  local i
  for i in 0 1 2; do
    if (( 10#${h[$i]} > 10#${w[$i]} )); then return 0; fi
    if (( 10#${h[$i]} < 10#${w[$i]} )); then return 1; fi
  done
  return 0
}

fetch_pinned() {
  local url="$1" expected="$2" dest="$3" mode="$4" tmp actual
  tmp=$(mktemp)
  curl -fsSL "$url" -o "$tmp"
  actual=$(sha256sum "$tmp" | cut -d' ' -f1)
  if [[ "$actual" != "$expected" ]]; then
    rm -f "$tmp"
    die "download hash mismatch for $url: got $actual, expected $expected"
  fi
  install -m "$mode" "$tmp" "$dest"
  rm -f "$tmp"
}

# A node mirror can supply install.sh, but not executable dependencies. Their
# hashes are embedded above so a changed GitHub response cannot gain root.
install_verify_helper() {
  mkdir -p /usr/local/share/mirage
  fetch_pinned \
    "${BOOTSTRAP_BASE}/release_verify.py" \
    "$EXPECTED_VERIFY_SHA256" \
    /usr/local/share/mirage/release_verify.py \
    0644
}

set_mnemonic() {
  local raw="$1"
  local -a words
  # Split in bash. Piping through xargs would put the seed in a process argv,
  # where anyone with /proc access can read it.
  read -r -a words <<<"$raw"
  MNEMONIC="${words[*]}"
  if (( ${#words[@]} != 12 )); then
    die "mnemonic must be exactly 12 words (got ${#words[@]})"
  fi
}

prompt_mnemonic() {
  local raw
  read -r -s -p "Enter 12-word mnemonic: " raw </dev/tty
  echo >/dev/tty
  set_mnemonic "$raw"
  unset raw
}

validate_mnemonic_wordlist() {
  echo "$MNEMONIC" | docker run --rm -i --entrypoint python3 "$IMAGE" -c '
import sys
from mnemonic import Mnemonic
phrase = sys.stdin.read().strip()
words = phrase.split()
if len(words) != 12:
    sys.stderr.write("mnemonic must be exactly 12 words (got %d)\n" % len(words))
    sys.exit(1)
m = Mnemonic("english")
unknown = [w for w in words if w not in m.wordlist]
if unknown:
    sys.stderr.write("mnemonic contains words not in the BIP-39 English list: %s\n" % " ".join(unknown))
    sys.exit(1)
if not m.check(phrase):
    sys.stderr.write("mnemonic failed BIP-39 checksum\n")
    sys.exit(1)
'
}

# Every host must land in its own maintenance window. Fixed defaults would put
# the whole public fleet into the same half hour.
maintenance_slots() {
  local seed hex n restart_hour
  if [[ ! -s /etc/machine-id ]]; then
    die "/etc/machine-id is missing; cannot derive stable maintenance slots"
  fi
  seed=$(cat /etc/machine-id)
  hex=$(printf '%s' "$seed" | sha256sum | cut -c1-8)
  n=$((16#$hex))
  restart_hour=$(( n / 7 % 24 ))
  # The upgrade window is half a day from the restart window: a container
  # restart firing into a half-finished apt transaction is worse than either.
  printf -- '--weekly-day=%d --weekly-hour=%d --upgrade-day=%d --upgrade-hour=%d' \
    $(( n % 7 + 1 )) "$restart_hour" $(( n / 168 % 7 + 1 )) $(( (restart_hour + 12) % 24 ))
}

harden() {
  local script slots
  script=$(mktemp)
  fetch_pinned \
    "${BOOTSTRAP_BASE}/harden_server.sh" \
    "$EXPECTED_HARDEN_SHA256" \
    "$script" \
    0755
  slots=$(maintenance_slots)
  # shellcheck disable=SC2086
  bash "$script" --no-reboot $slots
  rm -f "$script"
  if [[ -f /var/run/reboot-required ]]; then
    echo "A reboot is required. Re-run the same installer command after reboot; it resumes automatically."
    advance_state hardened
    exit 0
  fi
}

pull_image() {
  if [[ "$IMAGE" != *"@sha256:"* ]]; then
    die "release manifest image is not digest-pinned: $IMAGE"
  fi
  docker pull "$IMAGE"
  local digest want_sha
  digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$IMAGE")
  want_sha=${IMAGE#*@}
  if [[ "$digest" != *"$want_sha"* ]]; then
    die "pulled RepoDigest $digest does not match manifest $IMAGE"
  fi
}

install_hosttools() {
  local staging
  staging=$(mktemp -d)
  mkdir -p /usr/local/bin /usr/local/sbin /usr/local/share/mirage
  docker run --rm -v "$staging:/out" --entrypoint /bin/bash "$IMAGE" -lc \
    'cp -a /opt/mirage/deploy/hosttools/. /out/ && cp /opt/mirage/deploy/release_verify.py /out/'
  # The trust anchor stays the key this script embedded. The image ships a copy
  # only so in-container verification works; if the two ever disagree, the image
  # is not the one this key signed for, so nothing from it gets installed.
  local image_fp host_fp
  image_fp=$(pubkey_fingerprint "$staging/pubkey.pem")
  host_fp=$(pubkey_fingerprint /usr/local/share/mirage/pubkey.pem)
  if [[ "$image_fp" != "$host_fp" ]]; then
    die "image pubkey $image_fp does not match the installer's $host_fp"
  fi
  local tool
  for tool in mirage-verify mirage-launch mirage-status mirage-update mirage-domain mirage-enroll; do
    if [[ ! -f "$staging/$tool" ]]; then
      die "image missing host tool $tool"
    fi
    install -m 0755 "$staging/$tool" "/usr/local/bin/$tool"
  done
  install -m 0755 "$staging/prune_mirage_images.sh" /usr/local/bin/prune_mirage_images.sh
  install -m 0755 "$staging/mirage-weekly-restart.sh" /usr/local/sbin/mirage-weekly-restart.sh
  install -m 0644 "$staging/release_verify.py" /usr/local/share/mirage/release_verify.py
  mkdir -p /etc/systemd/system
  for tool in mirage-enroll.service mirage-enroll.timer mirage-update.service mirage-update.timer; do
    install -m 0644 "$staging/systemd/$tool" "/etc/systemd/system/$tool"
  done
  rm -rf "$staging"
}

agree_json() {
  python3 - "$1" "$2" <<'PY'
import json, sys, urllib.request
urls, path = sys.argv[1].split(","), sys.argv[2]
bodies = []
for u in urls:
    req = urllib.request.Request(u.rstrip("/") + path, headers={"User-Agent": "mirage-install"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        bodies.append(json.loads(resp.read().decode()))
first = json.dumps(bodies[0], sort_keys=True)
for b in bodies[1:]:
    if json.dumps(b, sort_keys=True) != first:
        sys.stderr.write("endpoints disagree on %s\n" % path)
        sys.exit(1)
json.dump(bodies[0], sys.stdout)
PY
}

derive_address() {
  ADDRESS=$(echo "$MNEMONIC" | docker run --rm -i --entrypoint /bin/sh "$IMAGE" -lc \
    'tmp=$(mktemp -d); /opt/mirage/blockchain/bin/miraged keys add tmp --recover --home "$tmp" --keyring-backend test >/dev/null && /opt/mirage/blockchain/bin/miraged keys show tmp -a --home "$tmp" --keyring-backend test')
  ADDRESS=$(echo "$ADDRESS" | tr -d '\r' | tail -1)
  if [[ -z "$ADDRESS" ]]; then
    die "failed to derive address from mnemonic"
  fi
  echo "==> Derived address $ADDRESS"
}

preflight_account() {
  local rest api activation
  rest=$(jq -r '.rest | join(",")' "$MANIFEST_DIR/network.json")
  api=$(jq -r '.api | join(",")' "$MANIFEST_DIR/network.json")
  activation=$(jq -r '.activation_balance_umirage' "$MANIFEST_DIR/network.json")
  local bal
  bal=$(agree_json "$rest" "/cosmos/bank/v1beta1/balances/${ADDRESS}/by_denom?denom=umirage")
  local amount
  amount=$(echo "$bal" | jq -r '.balance.amount // "0"')
  if [[ "$amount" -lt "$activation" ]]; then
    die "address $ADDRESS holds $((amount / 1000000)) MIRAGE, need $((activation / 1000000))"
  fi
  local profile
  profile=$(agree_json "$api" "/api/get_profile?address=${ADDRESS}")
  USERNAME=$(echo "$profile" | jq -r '.username // ""')
  if [[ -z "$USERNAME" ]]; then
    die "address $ADDRESS has no username; create an account and set a username on mirage.talk first"
  fi
  echo "==> Profile username @$USERNAME, balance ${amount} umirage"
}

collision_guard() {
  local rest tmp_home pub
  rest=$(jq -r '.rest | join(",")' "$MANIFEST_DIR/network.json")
  tmp_home=$(mktemp -d)
  echo "$MNEMONIC" | docker run --rm -i \
    -e HOME=/tmp \
    -v "$tmp_home:/tmp/.mirage" \
    --entrypoint python3 \
    "$IMAGE" /opt/mirage/deploy/derive_consensus_key.py --index 0 >/dev/null
  pub=$(jq -r '.pub_key.value' "$tmp_home/node/config/priv_validator_key.json")
  rm -rf "$tmp_home"
  if [[ -z "$pub" || "$pub" == "null" ]]; then
    die "could not derive the consensus pubkey for the double-sign check"
  fi
  local statuses=(BOND_STATUS_BONDED BOND_STATUS_UNBONDING BOND_STATUS_UNBONDED)
  local st match="" page body next_key encoded_key path
  for st in "${statuses[@]}"; do
    # A query failure here must not pass as "no collision"; two hosts signing
    # with one key is the one mistake that cannot be undone.
    next_key=""
    for page in $(seq 1 1000); do
      path="/cosmos/staking/v1beta1/validators?status=${st}&pagination.limit=1000"
      if [[ -n "$next_key" ]]; then
        encoded_key=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$next_key")
        path="${path}&pagination.key=${encoded_key}"
      fi
      body=$(agree_json "$rest" "$path")
      match=$(echo "$body" | jq -r --arg pub "$pub" \
        '.validators[]? | select((.consensus_pubkey.key // .consensus_pubkey.value // "") == $pub) | .operator_address' \
        | head -1)
      if [[ -n "$match" && "$match" != "null" ]]; then
        break 2
      fi
      next_key=$(echo "$body" | jq -r '.pagination.next_key // ""')
      if [[ -z "$next_key" || "$next_key" == "null" ]]; then
        break
      fi
      if (( page == 1000 )); then
        die "validator pagination exceeded 1000 pages while checking for a consensus-key collision"
      fi
    done
  done
  local local_pub=""
  if [[ -f /root/.mirage/node/config/priv_validator_key.json ]]; then
    local_pub=$(jq -r '.pub_key.value' /root/.mirage/node/config/priv_validator_key.json)
    if [[ "$local_pub" != "$pub" ]]; then
      die "the supplied mnemonic does not match this host's existing consensus key"
    fi
  fi
  local local_address=""
  if local_address=$(docker run --rm -v /root/.mirage:/root/.mirage --entrypoint /bin/sh "$IMAGE" -lc \
      '/opt/mirage/blockchain/bin/miraged keys show validator -a --home /root/.mirage/node --keyring-backend test' \
      2>/dev/null); then
    local_address=$(echo "$local_address" | tr -d '\r' | tail -1)
    if [[ "$local_address" != "$ADDRESS" ]]; then
      die "the supplied mnemonic derives $ADDRESS but this host's validator account is $local_address"
    fi
  fi
  if [[ -n "$match" && "$match" != "null" ]]; then
    if [[ "$local_pub" == "$pub" ]]; then
      echo "==> Consensus key already on this host and registered ($match); reinstall is idempotent"
      return 0
    fi
    die "this seed's consensus key is already a validator ($match) on another host; migrate with scripts/backup_restore.py --migrate"
  fi
}

# Sets PUBLIC_IP / PUBLIC_IP6 in the caller, so it must not run in a subshell.
detect_public_ip() {
  PUBLIC_IP=$(curl -4 -fsS --max-time 5 https://api.ipify.org || true)
  PUBLIC_IP6=$(curl -6 -fsS --max-time 5 https://api6.ipify.org || true)
}

external_address() {
  if [[ -n "${MIRAGE_EXTERNAL_ADDRESS:-}" ]]; then
    echo "$MIRAGE_EXTERNAL_ADDRESS"
    return 0
  fi
  if [[ -n "$PUBLIC_IP" ]]; then
    echo "tcp://${PUBLIC_IP}:26656"
    return 0
  fi
  if [[ -n "$PUBLIC_IP6" ]]; then
    echo "tcp://[$PUBLIC_IP6]:26656"
    return 0
  fi
  die "could not detect a public address for P2P external_address"
}

configure() {
  mkdir -p /root/.mirage/env /root/.mirage/node/config /root/.caddy
  docker run --rm -v /root/.mirage:/root/.mirage --entrypoint /bin/bash "$IMAGE" -lc \
    'for f in /opt/mirage/deploy/templates/env/*.env; do
       dest=/root/.mirage/env/$(basename "$f")
       if [ ! -f "$dest" ]; then cp "$f" "$dest"; fi
     done'
  chmod 700 /root/.mirage /root/.mirage/env /root/.mirage/node
  chmod 600 /root/.mirage/env/*.env
  local rpc peers ext
  rpc=$(jq -r '.rpc | join(",")' "$MANIFEST_DIR/network.json")
  peers=$(jq -r '.persistent_peers | join(",")' "$MANIFEST_DIR/network.json")
  ext=$(external_address)
  write_env_key() {
    local key="$1" val="$2" file=/root/.mirage/env/node.env
    python3 - "$file" "$key" "$val" <<'PY'
import os, re, sys
path, key, value = sys.argv[1:4]
text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
matches = pattern.findall(text)
if len(matches) > 1:
    raise SystemExit(f"duplicate {key} entries in {path}")
line = f"{key}={value}"
if matches:
    text = pattern.sub(lambda _: line, text, count=1)
else:
    text += ("" if not text or text.endswith("\n") else "\n") + line + "\n"
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write(text)
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
  }
  write_env_key BOOTSTRAP_RPC "$rpc"
  write_env_key PERSISTENT_PEERS "$peers"
  write_env_key MONIKER "$USERNAME"
  write_env_key EXTERNAL_ADDRESS "$ext"
  if [[ -n "$DOMAIN_ARG" ]]; then
    write_env_key DOMAIN "$DOMAIN_ARG"
  fi
  cp "$MANIFEST_DIR/network.json" /root/.mirage/env/network-manifest.json
  cp "$MANIFEST_DIR/network.json.sig" /root/.mirage/env/network-manifest.json.sig
  cp "$MANIFEST_DIR/manifest.json" /root/.mirage/env/release-manifest.json
  cp "$MANIFEST_DIR/manifest.json.sig" /root/.mirage/env/release-manifest.json.sig
}

identity() {
  local keyfile=/root/.mirage/node/config/priv_validator_key.json
  local has_key=0 has_account=0
  [[ -f "$keyfile" ]] && has_key=1
  if docker run --rm -v /root/.mirage:/root/.mirage --entrypoint /bin/sh "$IMAGE" -lc \
      '/opt/mirage/blockchain/bin/miraged keys show validator --home /root/.mirage/node --keyring-backend test >/dev/null 2>&1'; then
    has_account=1
  fi
  if [[ $has_key -eq 1 && $has_account -eq 1 ]]; then
    echo "==> Identity already present; not rewriting keys"
    unset MNEMONIC
    return 0
  fi
  if [[ $has_key -ne $has_account ]]; then
    die "inconsistent identity (keyfile=$has_key keyring=$has_account); will not generate a replacement"
  fi
  if ! echo "$MNEMONIC" | docker run --rm -i \
    --entrypoint python3 \
    -v /root/.mirage:/root/.mirage \
    "$IMAGE" /opt/mirage/deploy/derive_consensus_key.py --index 0 >/dev/null; then
    die "failed to derive the consensus key"
  fi
  if ! echo "$MNEMONIC" | docker run --rm -i \
    --entrypoint /bin/sh \
    -v /root/.mirage:/root/.mirage \
    "$IMAGE" -lc '/opt/mirage/blockchain/bin/miraged keys add validator --recover --home /root/.mirage/node --keyring-backend test >/dev/null'; then
    die "failed to import the validator account into the keyring"
  fi
  chmod 600 "$keyfile"
  unset MNEMONIC
  echo "==> Validator account and consensus key imported"
}

launch() {
  /usr/local/bin/mirage-launch --image "$IMAGE" --moniker "$USERNAME"
  local i
  for i in $(seq 1 120); do
    if curl -sf --max-time 2 http://127.0.0.1:26657/status >/dev/null; then
      echo "✓ RPC is up"
      return 0
    fi
    sleep 1
  done
  die "container started but RPC did not become ready in 120s"
}

# Without this the first updater tick has no baseline: it would re-stage the
# release the node is already running and ask the operator to restart for it.
seed_update_state() {
  mkdir -p /var/lib/mirage/update
  python3 - \
    /var/lib/mirage/update/state.json \
    "$IMAGE" \
    "$MANIFEST_DIR/manifest.json" \
    "$MANIFEST_DIR/network.json" <<'PY'
import json, os, sys
path, image, release_manifest, network_manifest = sys.argv[1:5]
release = json.load(open(release_manifest))
network = json.load(open(network_manifest))
state = {
    "active": image,
    "active_activation": release["activation"],
    "active_rollback_safe": bool(release["rollback_safe"]),
    "active_consensus_breaking": bool(release["consensus_breaking"]),
    "previous": "",
    "staged": "",
    "staged_activation": "",
    "staged_rollback_safe": False,
    "staged_consensus_breaking": False,
    "last_release_id": int(release["release_id"]),
    "last_network_generation": int(network["generation"]),
}
tmp = path + ".tmp"
open(tmp, "w").write(json.dumps(state, indent=2) + "\n")
os.replace(tmp, path)
PY
}

install_timers() {
  systemctl daemon-reload
  systemctl enable --now mirage-enroll.timer
  systemctl enable --now mirage-update.timer
}

print_next_steps() {
  echo
  echo "=============================================="
  echo "Mirage node is installing/syncing."
  echo "HTTP:      http://${PUBLIC_IP:-YOUR_IP}"
  echo "Username:  ${USERNAME}"
  echo "Address:   ${ADDRESS}"
  echo
  echo "HTTPS: point A/AAAA at this IP, then:  mirage-domain your.domain"
  echo "Status:  mirage-status"
  echo "This node will register itself once synced. Do not run create-validator by hand."
  echo "=============================================="
}

main() {
  parse_args "$@"
  require_root
  require_tty
  umask 077
  load_or_init_state
  if state_at_least done; then
    echo "==> Mirage installation is already complete; use mirage-status or mirage-update"
    return 0
  fi

  if ! state_at_least hardened; then
    preflight_os
    harden
    advance_state hardened
  fi
  if [[ -f /var/run/reboot-required ]]; then
    die "host still requires a reboot; reboot now, then run the installer again"
  fi

  write_embedded_pubkey
  install_verify_helper
  if ! state_at_least verified; then
    fetch_manifests
    verify_manifests
    pin_manifests
    advance_state verified
  else
    use_pinned_manifests
    verify_manifests
  fi
  IMAGE=$(jq -r '.image' "$MANIFEST_DIR/manifest.json")
  if [[ -z "$IMAGE" || "$IMAGE" == "null" ]]; then
    die "release manifest missing image"
  fi

  if ! state_at_least pulled; then
    pull_image
    install_hosttools
    advance_state pulled
  fi

  prompt_mnemonic
  validate_mnemonic_wordlist
  derive_address
  preflight_account
  collision_guard
  detect_public_ip

  if ! state_at_least configured; then
    configure
    advance_state configured
  fi

  if ! state_at_least identity; then
    identity
    advance_state identity
  fi

  if ! state_at_least launched; then
    launch
    seed_update_state
    advance_state launched
  fi

  if ! state_at_least enrolled_timer; then
    install_timers
    advance_state enrolled_timer
  fi

  advance_state done
  print_next_steps
}

main "$@"
