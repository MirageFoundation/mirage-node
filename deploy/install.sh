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
MONIKER_CHOICE=""
MEDIA_UPLOADS=""
MNEMONIC=""
IMAGE=""
USERNAME=""
ADDRESS=""
MANIFEST_DIR=""
TEMP_MANIFEST_DIR=""
PUBLIC_IP=""
PUBLIC_IP6=""
PREVIOUS_IMAGE=""
RESUME_IMAGE_CHANGED=0

GITHUB_RAW="https://raw.githubusercontent.com/MirageFoundation/mirage-node/prod"
RELEASE_MANIFEST_URL="${MIRAGE_MANIFEST_URL:-$GITHUB_RAW/release/manifest.json}"
NETWORK_MANIFEST_URL="${MIRAGE_NETWORK_URL:-$GITHUB_RAW/release/network.json}"
BOOTSTRAP_BASE="${MIRAGE_MANIFEST_MIRROR:-$GITHUB_RAW/deploy}"

# Fingerprint of deploy/hosttools/pubkey.pem (raw ed25519 hex). Stable across releases.
EXPECTED_PUBKEY_FINGERPRINT="679a39294dc9639170ca9cb4010c44cc71dd153fa2029f2e73969bff6d86c0a8"
EXPECTED_VERIFY_SHA256="bf96b421c5761f036be5ac8809ab3d86d637e88886586ad4e3e0c236909f44a8"
EXPECTED_HARDEN_SHA256="db0153c09e5eb7d4a039225f74c4e5f6e2031b0650bf02bca7c3cfa41518707a"

die() { echo "ERROR: $*" >&2; exit 1; }

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --domain) DOMAIN_ARG="${2:-}"; shift 2 ;;
      --domain=*) DOMAIN_ARG="${1#*=}"; shift ;;
      -h|--help)
        echo "usage: install.sh [--domain example.com]"
        echo
        echo "The installer asks for a validator name, a domain and whether to accept"
        echo "media uploads. Set MIRAGE_MONIKER, MIRAGE_DOMAIN or MIRAGE_MEDIA_UPLOADS"
        echo "to answer any of them up front; an empty value is a valid answer."
        exit 0
        ;;
      *) die "unknown flag: $1" ;;
    esac
  done
  if [[ -n "$DOMAIN_ARG" ]] && ! valid_hostname "$DOMAIN_ARG"; then
    die "--domain must be a hostname like example.com (got '$DOMAIN_ARG')"
  fi
}

valid_hostname() {
  [[ "$1" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$ ]]
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

refresh_manifests_for_resume() {
  use_pinned_manifests
  verify_manifests
  local pinned_release_id pinned_generation
  pinned_release_id=$(jq -r '.release_id' "$MANIFEST_DIR/manifest.json")
  pinned_generation=$(jq -r '.generation' "$MANIFEST_DIR/network.json")
  PREVIOUS_IMAGE=$(jq -r '.image' "$MANIFEST_DIR/manifest.json")

  fetch_manifests
  verify_manifests
  local fetched_release_id fetched_generation fetched_image
  fetched_release_id=$(jq -r '.release_id' "$MANIFEST_DIR/manifest.json")
  fetched_generation=$(jq -r '.generation' "$MANIFEST_DIR/network.json")
  fetched_image=$(jq -r '.image' "$MANIFEST_DIR/manifest.json")
  if (( fetched_release_id < pinned_release_id )); then
    die "fetched release id $fetched_release_id is older than pinned release id $pinned_release_id"
  fi
  if (( fetched_generation < pinned_generation )); then
    die "fetched network generation $fetched_generation is older than pinned generation $pinned_generation"
  fi
  if [[ "$fetched_image" != "$PREVIOUS_IMAGE" ]]; then
    RESUME_IMAGE_CHANGED=1
    echo "==> Signed release changed during the incomplete install; switching to $fetched_image"
  fi
  pin_manifests
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
  # Normalise what terminals and password managers add to a pasted phrase.
  # Every step here is bash parameter expansion: piping through tr or xargs
  # would put the seed in a process argv, where anyone with /proc access can
  # read it. Runs of plain whitespace need no help; read -a collapses those.
  raw="${raw//$'\e[200~'/}"                  # bracketed-paste markers; read does not strip them
  raw="${raw//$'\e[201~'/}"
  raw="${raw//$'\xc2\xa0'/ }"                # no-break space, indistinguishable from a space
  raw="${raw//$'\xe2\x80\xaf'/ }"            # narrow no-break space
  raw="${raw//$'\xe3\x80\x80'/ }"            # ideographic space
  raw="${raw//$'\xe2\x80\x8b'/}"             # zero-width space
  raw="${raw//$'\xef\xbb\xbf'/}"             # byte-order mark
  raw="${raw//[$'\001'-$'\037'$'\177']/ }"   # carriage returns, stray escapes, other controls
  raw="${raw,,}"                             # the BIP-39 English words are all lowercase
  local -a words
  read -r -a words <<<"$raw"
  MNEMONIC="${words[*]}"
  if (( ${#words[@]} != 12 )); then
    die "recovery phrase must be 12 words on one line, separated by spaces (got ${#words[@]})"
  fi
}

prompt_mnemonic() {
  local raw
  printf '\n\n%s\n%s\n' \
    "Now paste your 12-word recovery phrase on ONE line, with a space between each word." \
    "It stays hidden while you paste, and extra spacing is cleaned up for you." >/dev/tty
  read -r -s -p "Recovery phrase: " raw </dev/tty
  echo >/dev/tty
  set_mnemonic "$raw"
  unset raw
  echo "==> Read a 12-word phrase" >/dev/tty
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

# Read the same document from every endpoint and refuse to continue unless they
# agree, so no single node can decide an install on its own. The optional third
# argument narrows the comparison to specific top-level keys. Use it for any
# response that also carries node-local operational state: the backend serves
# per-node data (inbox counters and similar) out of its own database, which
# cannot agree across hosts and says nothing about the chain. Comparing only the
# keys we act on is deliberate -- a denylist would silently start matching each
# new node-local field and break installs again.
agree_json() {
  python3 - "$1" "$2" "${3-}" <<'PY'
import json, sys, urllib.request
urls, path, keys = sys.argv[1].split(","), sys.argv[2], sys.argv[3]
compare = [k for k in keys.split(",") if k]
bodies = []
for u in urls:
    req = urllib.request.Request(u.rstrip("/") + path, headers={"User-Agent": "mirage-install"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        bodies.append(json.loads(resp.read().decode()))

def compared(body):
    # A key the endpoints both omit is still compared, as None against None, so
    # an absent field stays the caller's decision instead of passing silently.
    return body if not compare else {k: body.get(k) for k in compare}

first = json.dumps(compared(bodies[0]), sort_keys=True)
for b in bodies[1:]:
    if json.dumps(compared(b), sort_keys=True) != first:
        detail = (" for " + ",".join(compare)) if compare else ""
        sys.stderr.write("endpoints disagree on %s%s\n" % (path, detail))
        sys.exit(1)
json.dump(bodies[0], sys.stdout)
PY
}

# Balances are held in umirage; an operator reads Mirage. Grouping is done here
# because printf "%'d" would depend on the host locale being set.
as_mirage() {
  local whole=$(( $1 / 1000000 )) grouped=""
  while (( whole >= 1000 )); do
    grouped=$(printf ',%03d%s' "$(( whole % 1000 ))" "$grouped")
    whole=$(( whole / 1000 ))
  done
  printf '%d%s' "$whole" "$grouped"
}

# miraged prints an interface-registration banner on stderr every time it runs,
# which is noise in an install transcript. Hold stderr back and print it only if
# the command fails, so a real error is still reported in full.
quiet_run() {
  local errfile rc=0
  errfile=$(mktemp)
  "$@" 2>"$errfile" || rc=$?
  if (( rc != 0 )); then
    cat "$errfile" >&2
  fi
  rm -f "$errfile"
  return "$rc"
}

derive_address() {
  ADDRESS=$(echo "$MNEMONIC" | quiet_run docker run --rm -i --entrypoint /bin/sh "$IMAGE" -lc \
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
    die "address $ADDRESS holds $(as_mirage "$amount") Mirage, need $(as_mirage "$activation")"
  fi
  local profile
  profile=$(agree_json "$api" "/api/get_profile?address=${ADDRESS}" "username")
  USERNAME=$(echo "$profile" | jq -r '.username // ""')
  if [[ -z "$USERNAME" ]]; then
    die "address $ADDRESS has no username; create an account and set a username on mirage.talk first"
  fi
  echo "==> Profile username @$USERNAME, balance $(as_mirage "$amount") Mirage"
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

valid_ipv4() {
  [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]
}

valid_ipv6() {
  [[ "$1" == *:* && "$1" =~ ^[0-9A-Fa-f:.]+$ ]]
}

valid_external_address() {
  [[ "$1" =~ ^tcp://([0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]+$ ]] \
    || [[ "$1" =~ ^tcp://\[[0-9A-Fa-f:.]+\]:[0-9]+$ ]]
}

# Sets PUBLIC_IP / PUBLIC_IP6 in the caller, so it must not run in a subshell.
detect_public_ip() {
  local raw
  raw=$(curl -4 -fsS --max-time 5 https://api.ipify.org || true)
  PUBLIC_IP=""
  if [[ -n "$raw" ]]; then
    if valid_ipv4 "$raw"; then
      PUBLIC_IP="$raw"
    else
      echo "WARNING: IPv4 probe returned a non-address; ignoring it" >&2
    fi
  fi
  PUBLIC_IP6=""
  # Only probe v6 where the host actually has a global v6 address. Probing
  # regardless printed a connection failure on every v4-only host, which reads
  # as a broken install when the address is optional. A host that does have v6
  # and still cannot reach the probe is worth a warning, so that case is not
  # silenced.
  if [[ -n "$(ip -6 addr show scope global 2>/dev/null)" ]]; then
    raw=$(curl -6 -fsS --max-time 5 https://api6.ipify.org || true)
    if [[ -z "$raw" ]]; then
      echo "WARNING: host has a global IPv6 address but the IPv6 probe failed; continuing with IPv4"
    elif valid_ipv6 "$raw"; then
      PUBLIC_IP6="$raw"
    else
      echo "WARNING: IPv6 probe returned a non-address; ignoring it" >&2
    fi
  fi
}

external_address() {
  if [[ -n "${MIRAGE_EXTERNAL_ADDRESS:-}" ]]; then
    if ! valid_external_address "$MIRAGE_EXTERNAL_ADDRESS"; then
      die "MIRAGE_EXTERNAL_ADDRESS must be tcp://IPv4:port or tcp://[IPv6]:port (got '$MIRAGE_EXTERNAL_ADDRESS')"
    fi
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

# Nothing here is asked. A new public node has one right answer for each of
# these, so the recovery phrase stays the only thing an operator has to supply.
# Each setting still reads an environment variable for anyone who wants a
# different one, and every value can also be changed after the install.
choose_settings() {
  choose_moniker
  choose_media_uploads
  choose_domain
}

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  printf '%s' "${s%"${s##*[![:space:]]}"}"
}

# This name is what other operators see in the validator list, and it is written
# on-chain at registration, where changing it costs a transaction. The account's
# username is the default because it is the name the network already knows.
choose_moniker() {
  local raw="$USERNAME"
  if [[ -n "${MIRAGE_MONIKER+x}" ]]; then
    raw=$(trim "$MIRAGE_MONIKER")
    [[ -n "$raw" ]] || raw="$USERNAME"
  fi
  if [[ ! "$raw" =~ ^[[:print:]]{1,70}$ ]]; then
    die "MIRAGE_MONIKER is not a usable validator name (1-70 printable characters)"
  fi
  MONIKER_CHOICE="$raw"
  printf '\n%s\n' "==> Validator name: $MONIKER_CHOICE"
}

choose_domain() {
  local raw=""
  if [[ -n "$DOMAIN_ARG" ]]; then
    warn_domain_dns "$DOMAIN_ARG"
    return 0
  fi
  if [[ -n "${MIRAGE_DOMAIN+x}" ]]; then
    raw=$(trim "$MIRAGE_DOMAIN")
  fi
  if [[ -z "$raw" ]]; then
    printf '\n\n%s\n' \
      "No domain for now; this node will serve on its IP. You can set it up later using \`mirage-domain example.com\`, which will enable SSL (https) for you and bind the domain."
    return 0
  fi
  if ! valid_hostname "$raw"; then
    die "MIRAGE_DOMAIN is not a hostname"
  fi
  DOMAIN_ARG="$raw"
  warn_domain_dns "$raw"
}

# HTTPS is configured at startup and a failure there is deliberately non-fatal,
# so a domain whose DNS is not live yet costs a certificate rather than the
# install. Saying that here beats letting the operator discover a plain-HTTP node.
warn_domain_dns() {
  local domain="$1" resolved="" hosts
  # A name that does not resolve is one of the answers this function reports on,
  # so getent's "key not found" exit is handled rather than allowed to end the
  # install: under pipefail it would otherwise abort with no explanation at all.
  if hosts=$(getent ahostsv4 "$domain" 2>/dev/null); then
    resolved=$(printf '%s\n' "$hosts" | awk '{print $1; exit}')
  fi
  if [[ -z "$resolved" ]]; then
    echo "WARNING: $domain does not resolve yet; HTTPS is retried on every restart, or run 'mirage-domain $domain' once DNS is live" >&2
  elif [[ -n "$PUBLIC_IP" && "$resolved" != "$PUBLIC_IP" ]]; then
    echo "WARNING: $domain resolves to $resolved, not this host ($PUBLIC_IP); HTTPS will fail until DNS points here" >&2
  else
    echo "==> Domain $domain resolves to this host; HTTPS will be requested on startup"
  fi
}

# Uploads put users' images and video on this node's disk, and nothing scans them
# unless a scanning edge fronts the node. A new node has no such edge, so they
# stay off until the operator sets MIRAGE_MEDIA_UPLOADS.
choose_media_uploads() {
  local raw=""
  if [[ -n "${MIRAGE_MEDIA_UPLOADS+x}" ]]; then
    raw=$(trim "$MIRAGE_MEDIA_UPLOADS")
  fi
  case "${raw,,}" in
    ''|n|no|false) MEDIA_UPLOADS=false ;;
    y|yes|true) MEDIA_UPLOADS=true ;;
    *) die "MIRAGE_MEDIA_UPLOADS must be yes or no (got '${raw:0:20}')" ;;
  esac
  printf '\n%s\n' "==> Media uploads enabled: $MEDIA_UPLOADS"
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
    local key="$1" val="$2" file="${3:-/root/.mirage/env/node.env}"
    python3 - "$file" "$key" "$val" <<'PY'
import os, re, shlex, sys
path, key, value = sys.argv[1:4]
text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
matches = pattern.findall(text)
if len(matches) > 1:
    raise SystemExit(f"duplicate {key} entries in {path}")
# Quote so an accidental bash-source cannot run a spaced name or `$()`.
line = f"{key}={shlex.quote(value)}"
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
  write_env_key MONIKER "$MONIKER_CHOICE"
  write_env_key EXTERNAL_ADDRESS "$ext"
  if [[ -n "$DOMAIN_ARG" ]]; then
    write_env_key DOMAIN "$DOMAIN_ARG"
  fi
  # A single operator is not watching at 04:00, and a diverged node that waits
  # for a human is down for as long as the human takes. Recovery snapshots the
  # diverged state before it touches anything, so the forensics survive either
  # way; this only decides whether the node waits to be told.
  write_env_key WATCHDOG_AUTORECOVER true
  write_env_key MEDIA_UPLOADS_ENABLED "$MEDIA_UPLOADS" /root/.mirage/env/backend.env
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
  if ! echo "$MNEMONIC" | quiet_run docker run --rm -i \
    --entrypoint /bin/sh \
    -v /root/.mirage:/root/.mirage \
    "$IMAGE" -lc '/opt/mirage/blockchain/bin/miraged keys add validator --recover --home /root/.mirage/node --keyring-backend test >/dev/null'; then
    die "failed to import the validator account into the keyring"
  fi
  chmod 600 "$keyfile"
  unset MNEMONIC
  echo "==> Validator account and consensus key imported"
}

running_pinned_image() {
  [[ "$(docker inspect -f '{{.State.Running}}' mirage 2>/dev/null || true)" == true ]] || return 1
  local want
  want=$(docker inspect -f '{{.Id}}' "$IMAGE" 2>/dev/null || true)
  [[ -n "$want" && "$(docker inspect -f '{{.Image}}' mirage 2>/dev/null || true)" == "$want" ]]
}

reset_partial_chain_init() {
  local data=/root/.mirage/node/data
  local validator_state="$data/priv_validator_state.json"
  [[ -d "$data" ]] || die "incomplete install has no node data directory to preserve"
  [[ -f "$validator_state" ]] || die "incomplete install has no priv_validator_state.json"
  local signed_height
  signed_height=$(jq -r '.height' "$validator_state")
  if [[ "$signed_height" != "0" ]]; then
    die "refusing to reset an incomplete install whose validator signed height is $signed_height"
  fi

  docker rm -f mirage >/dev/null 2>&1 || true
  local stamp cap
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  cap="/root/.mirage/.failed_install_forensics/$stamp"
  mkdir -p "$cap"
  printf 'reason=release_changed_before_first_rpc\nprevious_image=%s\nnew_image=%s\nsigned_height=%s\ncaptured_at=%s\n' \
    "$PREVIOUS_IMAGE" "$IMAGE" "$signed_height" "$stamp" > "$cap/MANIFEST.txt"
  mv "$data" "$cap/data"
  mkdir -p "$data"
  install -m 0600 "$cap/data/priv_validator_state.json" "$validator_state"
  rm -f /root/.mirage/node/config/genesis.json /root/.mirage/.initialized
  echo "==> Preserved partial chain initialization in $cap and reset it for the amended release"
}

startup_failed() {
  echo "ERROR: $1" >&2
  echo "--- last 20 lines of container output ---" >&2
  docker logs --tail 20 mirage >&2 2>&1 || true
  echo "--- last 40 lines of miraged output ---" >&2
  local latest_node_log
  latest_node_log=$({ compgen -G '/root/.mirage/logs/node/miraged-*.log' || true; } | sort | tail -1)
  if [[ -n "$latest_node_log" ]]; then
    tail -n 40 "$latest_node_log" >&2
  else
    echo "No miraged log found in /root/.mirage/logs/node" >&2
  fi
  die "the node did not come up; follow it with 'docker logs -f mirage', then re-run this installer to finish"
}

# A restart of the running validators reaches RPC in about 35 seconds. A first
# boot also creates the Postgres cluster inside the volume, applies every
# migration to empty databases and state-syncs the chain, so the budget is an
# order of magnitude above the warm path rather than a guess. A crashed or
# crash-looping container ends the wait immediately, so the deadline is only
# ever spent on a node that is still making progress.
wait_for_rpc() {
  local budget=900 elapsed=0 restarts_before restarts_now
  restarts_before=$(docker inspect -f '{{.RestartCount}}' mirage 2>/dev/null || echo 0)
  while (( elapsed < budget )); do
    if curl -sf --max-time 2 http://127.0.0.1:26657/status >/dev/null; then
      echo "✓ RPC is up after ${elapsed}s"
      return 0
    fi
    if [[ "$(docker inspect -f '{{.State.Running}}' mirage 2>/dev/null || true)" != true \
       && "$(docker inspect -f '{{.State.Restarting}}' mirage 2>/dev/null || true)" != true ]]; then
      startup_failed "the mirage container is no longer running"
    fi
    restarts_now=$(docker inspect -f '{{.RestartCount}}' mirage 2>/dev/null || echo "$restarts_before")
    if (( restarts_now > restarts_before )); then
      startup_failed "the mirage container is restarting in a loop"
    fi
    if (( elapsed > 0 && elapsed % 30 == 0 )); then
      echo "    still starting (${elapsed}s of ${budget}s): $(docker logs --tail 1 mirage 2>&1 | tr -d '\r' | cut -c1-100)"
    fi
    sleep 3
    elapsed=$((elapsed + 3))
  done
  startup_failed "RPC did not become ready in ${budget}s"
}

launch() {
  # Resuming an install must not restart a node that is already up on the
  # pinned image; recreating it would throw away an in-progress state sync.
  if running_pinned_image; then
    echo "==> mirage is already running the pinned image; not recreating it"
  else
    /usr/local/bin/mirage-launch --image "$IMAGE" --moniker "$USERNAME"
  fi
  wait_for_rpc
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
    refresh_manifests_for_resume
  fi
  IMAGE=$(jq -r '.image' "$MANIFEST_DIR/manifest.json")
  if [[ -z "$IMAGE" || "$IMAGE" == "null" ]]; then
    die "release manifest missing image"
  fi

  if (( RESUME_IMAGE_CHANGED )) || ! state_at_least pulled; then
    pull_image
    install_hosttools
    if ! state_at_least pulled; then
      advance_state pulled
    fi
  fi

  prompt_mnemonic
  printf '\n\n%s\n' "Processing recovery phrase"
  validate_mnemonic_wordlist
  derive_address
  preflight_account
  collision_guard
  detect_public_ip

  if ! state_at_least configured; then
    choose_settings
    configure
    advance_state configured
  fi

  if ! state_at_least identity; then
    identity
    advance_state identity
  fi

  if (( RESUME_IMAGE_CHANGED )) && state_at_least identity && ! state_at_least launched; then
    reset_partial_chain_init
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
