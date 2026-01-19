#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from bech32 import bech32_encode, convertbits  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
MIRAGE_TMP = Path.home() / ".mirage" / "tmp"


def ensure_mirage_tmp() -> Path:
    """Ensure ~/.mirage/tmp/ exists and return it."""
    MIRAGE_TMP.mkdir(parents=True, exist_ok=True)
    return MIRAGE_TMP


def status(msg: str):
    print(f"==> {msg}", flush=True)


def run(cmd, check=True, capture=False):
    if capture:
        result = subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout
    subprocess.run(cmd, check=check, text=True)
    return ""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


# Registry for pulling production images
REGISTRY_IMAGE = "ghcr.io/miragefoundation/mirage-node"


def stop_local_container():
    """Stop, kill, and remove the local mirage container if running."""
    status("Stopping local Docker container 'mirage'...")
    run(["bash", "-lc", "docker stop mirage 2>/dev/null || true"])
    run(["bash", "-lc", "docker kill mirage 2>/dev/null || true"])
    time.sleep(2)
    # Clear main directory using docker (files owned by root)
    home = str(Path.home())
    run(["bash", "-lc", f"docker run --rm -v '{home}/.mirage:/data' alpine rm -rf /data/node 2>/dev/null || true"])
    run(["bash", "-lc", "docker rm -f mirage 2>/dev/null || true"])
    status("Container stopped and removed")


def ensure_local_container(image_ref: str):
    """Ensure local container is running with the specified image.

    Always removes existing container and creates fresh one from the exact image.
    This ensures we use the same binary as the source chain.
    """
    status(f"Pulling image: {image_ref}")
    run(["bash", "-lc", f"docker pull '{image_ref}'"])

    # Remove any existing container (we want fresh state with exact image)
    run(["bash", "-lc", "docker rm -f mirage 2>/dev/null || true"])

    home = str(Path.home())
    status("Creating persistent volumes (~/.mirage, ~/.caddy)...")
    run(["bash", "-lc", f"mkdir -p '{home}/.mirage' '{home}/.caddy'"])

    status(f"Starting local container with image: {image_ref}")
    run(
        [
            "bash",
            "-lc",
            f"docker run -d -p 80:80 -p 26656:26656 -p 26657:26657 -p 443:443 "
            f"--name mirage --restart unless-stopped -e SKIP_PEERS=1 -e SKIP_VALIDATOR_CHECK=1 "
            f"-v {home}/.mirage:/root/.mirage -v {home}/.caddy:/root/.local/share/caddy '{image_ref}'",
        ]
    )
    status("Waiting for container exec to be ready...")
    for _ in range(60):
        try:
            run(["bash", "-lc", "docker exec mirage echo ready >/dev/null 2>&1 || true"])
            break
        except Exception:
            time.sleep(1)
    status("Local container is ready")


def remote_snapshot(source_host: str, ssh_user: str = "root") -> Path:
    """
    Create a lightweight snapshot on the remote host by running export there.
    This avoids copying ~5GB of blockchain databases, reducing transfer to ~200MB.

    The archive contains (in node/snapshot/):
    - image_ref.txt (exact docker image reference, e.g., ghcr.io/.../mirage-node:abc123)
    - export.json (chain state export, ~50MB)
    - indexer.sql (PostgreSQL dump, ~20MB)
    And node/config/ (node configuration)

    Note: We no longer copy the miraged binary - instead we capture the exact image
    reference and pull that image during reset.
    """
    conn = f"{ssh_user}@{source_host}"
    status(f"Connecting to source host: {conn}")

    # Capture the exact docker image reference BEFORE stopping the container
    status("Capturing docker image reference...")
    image_ref = run(
        ["bash", "-lc", f"ssh -o StrictHostKeyChecking=accept-new {conn} 'docker inspect mirage --format \"{{{{.Config.Image}}}}\"'"],
        capture=True,
    ).strip()
    if not image_ref or ":" not in image_ref:
        raise RuntimeError(f"Could not get valid image reference from remote container: {image_ref}")
    status(f"Remote image: {image_ref}")

    status("Stopping remote container 'mirage' (briefly)...")
    run(["bash", "-lc", f"ssh {conn} 'docker stop --timeout 60 mirage || true'"])

    status("Finding miraged binary path...")
    # Find the binary path dynamically (handles path changes across versions)
    binary_path = run(
        [
            "bash",
            "-lc",
            f"ssh {conn} 'docker start mirage >/dev/null 2>&1; sleep 2; "
            f"docker exec mirage which miraged || docker exec mirage find /opt -name miraged -type f 2>/dev/null | head -1'",
        ],
        capture=True,
    ).strip()
    if not binary_path:
        raise RuntimeError("Could not find miraged binary in remote container")
    status(f"Found binary at: {binary_path}")
    run(["bash", "-lc", f"ssh {conn} 'docker stop mirage >/dev/null 2>&1 || true'"])

    # Create snapshot directory and save image reference
    run(
        [
            "bash",
            "-lc",
            f"ssh {conn} 'mkdir -p /root/.mirage/node/snapshot && echo \"{image_ref}\" > /root/.mirage/node/snapshot/image_ref.txt'",
        ]
    )

    # Copy binary for export (we need it to run the export command)
    run(
        [
            "bash",
            "-lc",
            f"ssh {conn} 'docker cp mirage:{binary_path} /root/.mirage/node/snapshot/miraged'",
        ]
    )

    status("Running chain export on remote (this may take a minute)...")
    run(
        [
            "bash",
            "-lc",
            f"ssh {conn} '/root/.mirage/node/snapshot/miraged export --home /root/.mirage/node --output-document /root/.mirage/node/snapshot/export.json'",
        ]
    )

    status("Dumping PostgreSQL indexer database...")
    run(
        [
            "bash",
            "-lc",
            f"ssh {conn} 'docker start mirage >/dev/null 2>&1; sleep 5; "
            f'docker exec mirage bash -c "PGPASSWORD=mirage pg_dump -h 127.0.0.1 -U mirage -d mirage > /root/.mirage/node/snapshot/indexer.sql" 2>/dev/null || true; '
            f"docker stop --timeout 10 mirage || true'",
        ]
    )

    # Remove the binary from snapshot (we'll pull the image instead)
    run(["bash", "-lc", f"ssh {conn} 'rm -f /root/.mirage/node/snapshot/miraged'"])

    status("Creating lightweight remote archive...")
    run(
        [
            "bash",
            "-lc",
            f"ssh {conn} 'cd /root/.mirage && tar czf /tmp/main.tgz " "node/snapshot " "node/config " "env/.migrations'",
        ]
    )

    status("Restarting remote container 'mirage'...")
    run(["bash", "-lc", f"ssh {conn} 'docker start mirage >/dev/null 2>&1 || true'"])

    status("Cleaning up remote snapshot directory...")
    run(["bash", "-lc", f"ssh {conn} 'rm -rf /root/.mirage/node/snapshot'"])

    ensure_mirage_tmp()
    date_name = time.strftime("%Y-%m-%d")
    local_tar = MIRAGE_TMP / f"{date_name}.tgz"
    status(f"Copying remote snapshot to local: {local_tar}")
    run(["bash", "-lc", f"scp {conn}:/tmp/main.tgz '{local_tar}'"])
    status("Cleaning up remote archive...")
    run(["bash", "-lc", f"ssh {conn} 'rm -f /tmp/main.tgz'"])
    status("Remote snapshot completed")
    return local_tar


def extract_snapshot(local_tar: Path) -> tuple[Path, str]:
    """
    Extract the snapshot tarball locally.
    Returns (extract_dir, image_ref) where extract_dir contains the snapshot files.
    """
    status("Extracting snapshot locally...")
    ensure_mirage_tmp()
    extract_dir = MIRAGE_TMP / "extract"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)
    run(["bash", "-lc", f"tar xzf '{local_tar}' -C '{extract_dir}' --no-same-owner --no-same-permissions"])

    # Support both new (node/) and old (main/) tarball structures
    src_dir = extract_dir / "node"
    if not src_dir.exists():
        src_dir = extract_dir / "main"  # fallback for old tarballs
    if not src_dir.exists():
        raise RuntimeError(f"Expected directory not found after extraction: {extract_dir}/node or {extract_dir}/main")

    snapshot_dir = src_dir / "snapshot"

    # Read image reference (new snapshots have this file)
    image_ref_file = snapshot_dir / "image_ref.txt"
    if image_ref_file.exists():
        image_ref = image_ref_file.read_text().strip()
        status(f"Snapshot image: {image_ref}")
    else:
        # Legacy snapshot without image_ref - use latest from registry
        status("WARNING: Snapshot missing image_ref.txt, using latest from registry")
        image_ref = f"{REGISTRY_IMAGE}:dev"

    export_json = snapshot_dir / "export.json"
    if not export_json.exists():
        raise RuntimeError(f"export.json not found in snapshot: {export_json}")

    return extract_dir, image_ref


def copy_snapshot_into_container(extract_dir: Path) -> Path:
    """
    Copy extracted snapshot files into the container.
    Returns the path to the local export.json file.
    """
    # Support both new (node/) and old (main/) tarball structures
    src_dir = extract_dir / "node"
    if not src_dir.exists():
        src_dir = extract_dir / "main"
    snapshot_dir = src_dir / "snapshot"
    export_json = snapshot_dir / "export.json"

    status("Preparing target directories inside container...")
    # Only reset the staging clone; leave /root/.mirage/node and /root/.mirage/postgres
    # under control of the entrypoint and this script.
    run(
        [
            "bash",
            "-lc",
            "docker exec mirage bash -lc '"
            "rm -rf /root/.mirage/node.clone; "
            "mkdir -p /root/.mirage/node.clone /root/.mirage/node'",
        ]
    )

    status("Copying config into container...")
    run(["bash", "-lc", f"docker cp '{src_dir}/config' mirage:/root/.mirage/node.clone/"])
    # Note: We don't copy the miraged binary anymore - we use the one from the pulled image

    indexer_sql = snapshot_dir / "indexer.sql"
    if indexer_sql.exists():
        status("Copying PostgreSQL indexer dump...")
        run(["bash", "-lc", f"docker cp '{indexer_sql}' mirage:/root/.mirage/node.clone/indexer.sql"])

    # Copy .migrations file to preserve deploy migration state
    migrations_file = extract_dir / "env" / ".migrations"
    if migrations_file.exists():
        status("Copying .migrations file...")
        run(["bash", "-lc", "docker exec mirage mkdir -p /root/.mirage/env"])
        run(["bash", "-lc", f"docker cp '{migrations_file}' mirage:/root/.mirage/env/.migrations"])

    run(["bash", "-lc", "docker exec mirage chmod -R u+rwX /root/.mirage/node.clone || true"])

    local_export = MIRAGE_TMP / "export.json"
    shutil.copy(export_json, local_export)

    status("Cleaning up local extraction...")
    shutil.rmtree(extract_dir, ignore_errors=True)
    status("Snapshot staged")
    return local_export


def restore_indexer_database():
    """Restore local indexer PostgreSQL database from the snapshot dump, if present."""
    status("Restoring indexer PostgreSQL database from dump (if present)...")

    # Use a small shell script inside the container to avoid complex quoting here
    script = """#!/bin/bash
set -e
DUMP_FILE="/root/.mirage/node.clone/indexer.sql"
if [ ! -f "$DUMP_FILE" ]; then
    echo "No indexer dump found, skipping"
    exit 0
fi

PG_DATA_DIR="/root/.mirage/postgres"
if [ ! -d "$PG_DATA_DIR" ]; then
    echo "Postgres data dir missing at $PG_DATA_DIR; cannot restore"
    exit 0
fi

pg_ctlcluster 16 main start 2>/dev/null || true
for i in $(seq 1 30); do
    pg_isready -h 127.0.0.1 -p 5432 -U postgres -t 1 >/dev/null 2>&1 && break || sleep 1
done

# Drop and recreate the mirage database and role, then restore dump as postgres (peer auth)
su - postgres <<EOF
psql -c "DROP DATABASE IF EXISTS mirage"
psql -c "DROP ROLE IF EXISTS mirage"
psql -c "CREATE ROLE mirage WITH LOGIN PASSWORD 'mirage'"
psql -c "CREATE DATABASE mirage OWNER mirage"
psql -d mirage -f "$DUMP_FILE"
EOF

echo "Index DB restored from dump"
"""

    ensure_mirage_tmp()
    tmp = Path(tempfile.mkdtemp(prefix="restore-indexer-", dir=str(MIRAGE_TMP)))
    script_path = tmp / "restore_indexer.sh"
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)
    try:
        run(["bash", "-lc", f"docker cp '{script_path}' mirage:/tmp/restore_indexer.sh"])
        run(["bash", "-lc", "docker exec mirage bash /tmp/restore_indexer.sh"])
        run(["bash", "-lc", "docker exec mirage rm -f /tmp/restore_indexer.sh"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def generate_random_mnemonic() -> str:
    code = "from mnemonic import Mnemonic; print(Mnemonic('english').generate(strength=128))"
    mn = run(["bash", "-lc", f'docker exec mirage python3 -c "{code}"'], capture=True).strip()
    if not mn or len(mn.split()) != 12:
        raise RuntimeError("failed to generate mnemonic inside container")
    return mn


def scrub_consensus_key():
    status("Generating new local consensus key...")
    # Remove existing key (copied from snapshot) before generating new one
    run(["bash", "-lc", "docker exec mirage rm -f /root/.mirage/node/config/priv_validator_key.json"])
    mnemonic = generate_random_mnemonic()
    cmd = "python3 /opt/mirage/deploy/derive_consensus_key.py"
    run(["bash", "-lc", f"echo '{mnemonic}' | docker exec -i mirage bash -lc \"{cmd}\""])
    run(["bash", "-lc", "docker exec mirage chmod 600 /root/.mirage/node/config/priv_validator_key.json"])
    status("Consensus key generated")


def ensure_test_keys():
    status("Creating test keys (validator, faucet)...")

    def _create_key(name: str):
        m = generate_random_mnemonic()
        cmd = f"echo '{m}' | /opt/mirage/blockchain/bin/miraged keys add {name} --recover --home /root/.mirage/node --keyring-backend test >/dev/null 2>&1 || true"
        run(["bash", "-lc", f'docker exec mirage bash -lc "{cmd}"'])

    _create_key("validator")
    _create_key("faucet")

    # Fix keyring permissions so host user can access (Docker creates as root with 700)
    run(["bash", "-lc", "docker exec mirage chmod -R 755 /root/.mirage/node/keyring-test"])

    val_addr = run(
        [
            "bash",
            "-lc",
            "docker exec mirage /opt/mirage/blockchain/bin/miraged keys show validator -a --home /root/.mirage/node --keyring-backend test",
        ],
        capture=True,
    ).strip()
    valoper = run(
        [
            "bash",
            "-lc",
            "docker exec mirage /opt/mirage/blockchain/bin/miraged keys show validator --bech val -a --home /root/.mirage/node --keyring-backend test",
        ],
        capture=True,
    ).strip()
    faucet_addr = run(
        [
            "bash",
            "-lc",
            "docker exec mirage /opt/mirage/blockchain/bin/miraged keys show faucet -a --home /root/.mirage/node --keyring-backend test",
        ],
        capture=True,
    ).strip()
    status(f"validator: {val_addr}")
    status(f"valoper:   {valoper}")
    status(f"faucet:    {faucet_addr}")
    return val_addr, valoper, faucet_addr


def stop_node_in_container():
    status("Stopping any running node ...")
    run(["bash", "-lc", "docker exec mirage tmux send-keys -t mirage:node C-c 2>/dev/null || true"])
    time.sleep(2)
    run(["bash", "-lc", "docker exec mirage pkill -9 -f miraged 2>/dev/null || true"])
    time.sleep(1)


def reinitialize_postgres():
    """Reinitialize PostgreSQL cluster after data directory was cleared."""
    status("Reinitializing PostgreSQL...")
    script = """#!/bin/bash
set -e
PG_DATA_DIR="/root/.mirage/postgres"
PG_LOG_DIR="/root/.mirage/logs/postgres"

pkill -9 postgres 2>/dev/null || true
sleep 1

rm -rf /etc/postgresql/16/main 2>/dev/null || true
rm -rf /var/lib/postgresql/16/main 2>/dev/null || true
rm -rf "$PG_DATA_DIR"

mkdir -p "$PG_DATA_DIR" "$PG_LOG_DIR"
chmod o+x /root /root/.mirage /root/.mirage/node /root/.mirage/node/data /root/.mirage/logs
chown -R postgres:postgres "$PG_DATA_DIR" "$PG_LOG_DIR"
chmod 700 "$PG_DATA_DIR"
chmod 755 "$PG_LOG_DIR"

pg_createcluster 16 main --datadir="$PG_DATA_DIR" --locale=C.UTF-8 -- --auth-local=peer --auth-host=scram-sha-256
pg_ctlcluster 16 main start
sleep 2

for i in $(seq 1 30); do
    if pg_isready -h 127.0.0.1 -p 5432 -U postgres -t 1 >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

su - postgres -c "psql -c \\"DROP DATABASE IF EXISTS mirage;\\""
su - postgres -c "psql -c \\"DROP ROLE IF EXISTS mirage;\\""
su - postgres -c "psql -c \\"CREATE ROLE mirage WITH LOGIN PASSWORD 'mirage';\\""
su - postgres -c "psql -c \\"CREATE DATABASE mirage OWNER mirage;\\""
"""
    ensure_mirage_tmp()
    tmp = Path(tempfile.mkdtemp(prefix="pg-init-", dir=str(MIRAGE_TMP)))
    script_path = tmp / "init_postgres.sh"
    with open(script_path, "w") as f:
        f.write(script)
    run(["bash", "-lc", f"docker cp '{script_path}' mirage:/tmp/init_postgres.sh"])
    run(["bash", "-lc", "docker exec mirage bash /tmp/init_postgres.sh"])
    run(["bash", "-lc", "docker exec mirage rm -f /tmp/init_postgres.sh"])
    shutil.rmtree(tmp, ignore_errors=True)
    status("PostgreSQL reinitialized")


def read_priv_validator_pubkey_b64() -> str:
    raw = run(["bash", "-lc", "docker exec mirage cat /root/.mirage/node/config/priv_validator_key.json"], capture=True)
    data = json.loads(raw)
    b64 = str(((data.get("pub_key") or {}).get("value") or "")).strip()
    if not b64:
        raise RuntimeError("missing consensus pubkey in priv_validator_key.json")
    return b64


def compute_valcons_from_pubkey_b64(b64: str) -> str:
    pub = base64.b64decode(b64)
    h20 = hashlib.sha256(pub).digest()[:20]
    data5 = convertbits(h20, 8, 5)
    if not data5:
        raise RuntimeError("bech32 convertbits failed")
    return bech32_encode("miragevalcons", data5)


def compute_validator_hex_address(cons_pub_b64: str) -> str:
    pub = base64.b64decode(cons_pub_b64)
    return hashlib.sha256(pub).hexdigest()[:40].upper()


def load_profiles_from_indexer_db() -> list:
    """Load user profiles from the SQL dump file.

    Returns profiles in InitialProfile format:
    {core: {owner, username, level, biography, avatar, ...}, followed_moderators: [...]}
    """
    status("Loading profiles from indexer dump...")
    # Parse the SQL dump file directly instead of querying PostgreSQL
    script = """
import json, re, time

dump_file = "/root/.mirage/node.clone/indexer.sql"

def parse_copy_data(content, table_name, columns):
    \"\"\"Parse COPY data from pg_dump output.\"\"\"
    pattern = rf"COPY public\\.{table_name} \\(([^)]+)\\) FROM stdin;"
    match = re.search(pattern, content)
    if not match:
        return []
    col_str = match.group(1)
    cols = [c.strip() for c in col_str.split(",")]
    start = match.end()
    end = content.find("\\\\.", start)
    if end < 0:
        return []
    data_section = content[start:end].strip()
    rows = []
    for line in data_section.split("\\n"):
        if not line or line == "\\\\.":
            continue
        values = line.split("\\t")
        if len(values) >= len(cols):
            row = {}
            for i, col in enumerate(cols):
                val = values[i] if i < len(values) else ""
                if val == "\\\\N":
                    val = None
                row[col] = val
            rows.append(row)
    return rows

try:
    with open(dump_file, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
except Exception as e:
    print(json.dumps([]))
    exit(0)

profiles_data = parse_copy_data(content, "profiles", [])
followed_mods_data = parse_copy_data(content, "followed_mods", [])

mods_map = {}
for row in followed_mods_data:
    owner = (row.get("owner") or "").lower()
    mod = row.get("moderator") or ""
    if owner and mod:
        mods_map.setdefault(owner, []).append(mod)

profiles = []
now = int(time.time())
for row in profiles_data:
    owner = row.get("owner") or ""
    username = row.get("username") or ""
    if not owner or not username:
        continue
    lvl = int(row.get("level") or 0)
    exp = int(row.get("subscription_expiry") or 0)
    if lvl > 0 and lvl < 100 and exp <= now:
        lvl = 0
    bio = row.get("biography") or ""
    avatar = row.get("avatar") or ""
    owner_key = owner.lower()
    # Build InitialProfile format with nested core
    profiles.append({
        "core": {
            "owner": owner,
            "username": username,
            "level": lvl,
            "biography": bio,
            "avatar": avatar,
        },
        "followed_moderators": mods_map.get(owner_key, []),
    })

print(json.dumps(profiles))
"""
    ensure_mirage_tmp()
    tmp = Path(tempfile.mkdtemp(prefix="profiles-", dir=str(MIRAGE_TMP)))
    script_path = tmp / "load_profiles.py"
    with open(script_path, "w") as f:
        f.write(script)
    run(["bash", "-lc", f"docker cp '{script_path}' mirage:/tmp/load_profiles.py"])
    result = run(
        ["bash", "-lc", "docker exec mirage python3 /tmp/load_profiles.py"],
        capture=True,
    )
    run(["bash", "-lc", "docker exec mirage rm -f /tmp/load_profiles.py"])
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        profiles = json.loads(result.strip())
        status(f"Loaded {len(profiles)} profiles from indexer dump")
        return profiles
    except Exception as e:
        status(f"WARNING: Failed to load profiles from indexer dump: {e}")
        return []


def find_module_account_address(auth_accounts: list, module_name: str) -> str | None:
    """Find a module account address by name in auth accounts."""
    for acc in auth_accounts:
        if acc.get("@type") == "/cosmos.auth.v1beta1.ModuleAccount":
            base = acc.get("base_account") or {}
            if acc.get("name") == module_name:
                return base.get("address")
    return None


def transform_to_single_validator(
    export_path: Path, val_addr: str, valoper: str, valcons: str, cons_pub_b64: str, faucet_addr: str
) -> str:
    status("Building single-validator genesis...")
    with open(export_path, "r", encoding="utf-8") as f:
        gen = json.load(f)

    app_state = gen.get("app_state") or {}
    auth = app_state.get("auth") or {}
    staking = app_state.get("staking") or {}
    bank = app_state.get("bank") or {}
    slashing = app_state.get("slashing") or {}
    upgrade_state = app_state.get("upgrade") or {}
    core_state = app_state.get("core") or {}
    gov_state = app_state.get("gov") or {}

    # Fix gov params: expedited_min_deposit must be > min_deposit
    gov_params = gov_state.get("params") or {}
    min_deposit = gov_params.get("min_deposit", [])
    expedited_min_deposit = gov_params.get("expedited_min_deposit", [])
    if min_deposit and expedited_min_deposit:
        min_amt = int(min_deposit[0].get("amount", "0"))
        exp_amt = int(expedited_min_deposit[0].get("amount", "0"))
        if exp_amt <= min_amt:
            # Set expedited to 2x min_deposit
            expedited_min_deposit[0]["amount"] = str(min_amt * 2)
            gov_params["expedited_min_deposit"] = expedited_min_deposit
            gov_state["params"] = gov_params
            app_state["gov"] = gov_state

    # Backfill profiles from indexer DB if chain export is missing them
    existing_profiles = core_state.get("initial_profiles") or []
    if len(existing_profiles) <= 10:  # Only module accounts
        indexer_profiles = load_profiles_from_indexer_db()
        if indexer_profiles:
            core_state["initial_profiles"] = indexer_profiles
            app_state["core"] = core_state
            status(f"Injected {len(indexer_profiles)} profiles from indexer DB into genesis")

    # Find staking module account addresses (needed to fix bank balances)
    auth_accounts = auth.get("accounts") or []
    bonded_pool_addr = find_module_account_address(auth_accounts, "bonded_tokens_pool")
    not_bonded_pool_addr = find_module_account_address(auth_accounts, "not_bonded_tokens_pool")
    if not bonded_pool_addr or not not_bonded_pool_addr:
        raise RuntimeError(f"Could not find staking module accounts in genesis: bonded={bonded_pool_addr}, not_bonded={not_bonded_pool_addr}")
    status(f"Staking pools: bonded={bonded_pool_addr}, not_bonded={not_bonded_pool_addr}")

    total_bonded = 0
    for v in staking.get("validators") or []:
        if str(v.get("status", "")) == "BOND_STATUS_BONDED":
            total_bonded += int(str(v.get("tokens", "0")))
    if total_bonded <= 0:
        total_bonded = 100_000_000

    power_reduction = 1_000_000
    last_power = str(total_bonded // power_reduction)
    tokens_str = str(total_bonded)
    status(f"Total bonded: {total_bonded} umirage, power={last_power}")

    single_validator = {
        "operator_address": valoper,
        "consensus_pubkey": {"@type": "/cosmos.crypto.ed25519.PubKey", "key": cons_pub_b64},
        "jailed": False,
        "status": "BOND_STATUS_BONDED",
        "tokens": tokens_str,
        "delegator_shares": tokens_str,
        "description": {
            "moniker": "mirage-node-1",
            "identity": "",
            "website": "",
            "security_contact": "",
            "details": "",
        },
        "unbonding_height": "0",
        "unbonding_time": "0001-01-01T00:00:00Z",
        "commission": {
            "commission_rates": {
                "rate": "0.000000000000000000",
                "max_rate": "0.000000000000000000",
                "max_change_rate": "0.000000000000000000",
            },
            "update_time": "0001-01-01T00:00:00Z",
        },
        "min_self_delegation": "1",
    }

    app_state["staking"] = {
        "params": staking.get("params", {}),
        "last_total_power": last_power,
        "last_validator_powers": [{"address": valoper, "power": last_power}],
        "validators": [single_validator],
        "delegations": [{"delegator_address": val_addr, "validator_address": valoper, "shares": tokens_str}],
        "unbonding_delegations": [],
        "redelegations": [],
        "exported": False,
    }

    app_state["slashing"] = {
        "params": slashing.get("params", {}),
        "signing_infos": [
            {
                "address": valcons,
                "validator_signing_info": {
                    "address": valcons,
                    "start_height": "0",
                    "index_offset": "0",
                    "jailed_until": "0001-01-01T00:00:00Z",
                    "tombstoned": False,
                    "missed_blocks_counter": "0",
                },
            }
        ],
        "missed_blocks": [],
    }

    faucet_amount = 100_000_000_000_000_000  # 100 billion MIRAGE
    validator_extra = 100_000_000_000_000  # 100 million MIRAGE
    balances = bank.get("balances") or []

    # Track supply changes
    supply_delta = faucet_amount + validator_extra

    # Fix staking module account balances to match our new staking state:
    # - bonded_tokens_pool should have exactly total_bonded (all our validator's stake)
    # - not_bonded_tokens_pool should have 0 (no unbonding delegations)
    old_bonded_balance = 0
    old_not_bonded_balance = 0
    new_balances = []
    for bal in balances:
        addr = bal.get("address", "")
        if addr == bonded_pool_addr:
            for coin in bal.get("coins") or []:
                if coin.get("denom") == "umirage":
                    old_bonded_balance = int(coin.get("amount", "0"))
            # Replace with new bonded amount
            new_balances.append({"address": addr, "coins": [{"denom": "umirage", "amount": str(total_bonded)}]})
        elif addr == not_bonded_pool_addr:
            for coin in bal.get("coins") or []:
                if coin.get("denom") == "umirage":
                    old_not_bonded_balance = int(coin.get("amount", "0"))
            # Skip (don't add) - not_bonded_pool should be empty since we have no unbonding delegations
            continue
        else:
            new_balances.append(bal)

    # Add faucet and validator balances
    new_balances.append({"address": faucet_addr, "coins": [{"denom": "umirage", "amount": str(faucet_amount)}]})
    new_balances.append({"address": val_addr, "coins": [{"denom": "umirage", "amount": str(validator_extra)}]})
    bank["balances"] = new_balances

    # Adjust supply for module account changes
    supply_delta += (total_bonded - old_bonded_balance)  # bonded pool change
    supply_delta -= old_not_bonded_balance  # removed not_bonded pool entirely
    status(f"Supply delta: +{faucet_amount + validator_extra} (faucet+validator), "
           f"bonded: {old_bonded_balance} -> {total_bonded}, not_bonded: {old_not_bonded_balance} -> 0")

    supply_list = bank.get("supply") or []
    for c in supply_list:
        if c.get("denom") == "umirage":
            c["amount"] = str(int(c.get("amount", "0")) + supply_delta)
            break
    else:
        supply_list.append({"denom": "umirage", "amount": str(supply_delta)})
    bank["supply"] = supply_list
    app_state["bank"] = bank

    auth_accounts.append(
        {
            "@type": "/cosmos.auth.v1beta1.BaseAccount",
            "address": faucet_addr,
            "pub_key": None,
            "account_number": str(len(auth_accounts)),
            "sequence": "0",
        }
    )
    auth["accounts"] = auth_accounts
    app_state["auth"] = auth

    if isinstance(upgrade_state, dict):
        upgrade_state["plan"] = None
        app_state["upgrade"] = upgrade_state

    gen["app_state"] = app_state

    cons_hex_addr = compute_validator_hex_address(cons_pub_b64)
    consensus_section = gen.get("consensus") or {}
    consensus_section["validators"] = [
        {
            "address": cons_hex_addr,
            "pub_key": {"type": "tendermint/PubKeyEd25519", "value": cons_pub_b64},
            "power": last_power,
            "name": "mirage-node-1",
        }
    ]
    gen["consensus"] = consensus_section

    status("Single-validator genesis assembled")
    return json.dumps(gen, ensure_ascii=False)


def write_working_genesis(genesis_json: str):
    status("Writing genesis to /root/.mirage/node/config/genesis.json ...")
    ensure_mirage_tmp()
    tmp = Path(tempfile.mkdtemp(prefix="genesis-", dir=str(MIRAGE_TMP)))
    local_path = tmp / "genesis.json"
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(genesis_json)
    run(["bash", "-lc", f"docker cp '{local_path}' mirage:/root/.mirage/node/config/genesis.json"])
    shutil.rmtree(tmp, ignore_errors=True)

    status("Copying config files from node.clone ...")
    run(
        [
            "bash",
            "-lc",
            "docker exec mirage bash -lc '"
            "mkdir -p /root/.mirage/node/config; "
            "for f in app.toml config.toml client.toml; do "
            "  cp -n /root/.mirage/node.clone/config/$f /root/.mirage/node/config/ 2>/dev/null || true; "
            "done'",
        ]
    )

    status("Configuring node for local testnet ...")
    run(
        [
            "bash",
            "-lc",
            "docker exec mirage bash -lc '"
            'cfg="/root/.mirage/node/config/config.toml"; '
            'sed -i "/^\\[rpc\\]/,/^\\[/{s/^laddr *= *.*/laddr = \\"tcp:\\/\\/0.0.0.0:26657\\"/}" "$cfg"; '
            'sed -i "/^\\[p2p\\]/,/^\\[/{s/^pex *= *.*/pex = false/}" "$cfg"; '
            'sed -i "/^\\[p2p\\]/,/^\\[/{s/^persistent_peers *= *.*/persistent_peers = \\"\\"/}" "$cfg"; '
            'sed -i "/^\\[p2p\\]/,/^\\[/{s/^max_num_inbound_peers *= *.*/max_num_inbound_peers = 0/}" "$cfg"; '
            'sed -i "/^\\[p2p\\]/,/^\\[/{s/^max_num_outbound_peers *= *.*/max_num_outbound_peers = 0/}" "$cfg"; '
            'sed -i "/^\\[consensus\\]/,/^\\[/{s/^create_empty_blocks *= *.*/create_empty_blocks = true/}" "$cfg"; '
            'sed -i "/^\\[consensus\\]/,/^\\[/{s/^create_empty_blocks_interval *= *.*/create_empty_blocks_interval = \\"2s\\"/}" "$cfg"; '
            'sed -i "/^\\[consensus\\]/,/^\\[/{s/^timeout_commit *= *.*/timeout_commit = \\"2s\\"/}" "$cfg"; '
            'sed -i "s/^chain-id *= *.*/chain-id = \\"mirage-1\\"/" /root/.mirage/node/config/client.toml; '
            'sed -i "s/^keyring-backend *= *.*/keyring-backend = \\"test\\"/" /root/.mirage/node/config/client.toml || true\'',
        ]
    )

    stop_node_in_container()

    status("Clearing data directory (preserving postgres)...")
    run(
        [
            "bash",
            "-lc",
            "docker exec mirage bash -lc '"
            "mkdir -p /root/.mirage/node/data && "
            "cd /root/.mirage/node/data && "
            "find . -mindepth 1 -maxdepth 1 ! -name postgres -exec rm -rf {} \\; ; "
            "mkdir -p /root/.mirage/node/data/cs.wal /root/.mirage/logs'",
        ]
    )
    run(
        [
            "bash",
            "-lc",
            'docker exec mirage bash -lc \'echo "{\\"height\\": \\"0\\", \\"round\\": 0, \\"step\\": 0}" > /root/.mirage/node/data/priv_validator_state.json\'',
        ]
    )
    reinitialize_postgres()

    # Restore full indexer DB before starting services
    restore_indexer_database()

    # Note: We use the binary from the pulled image (same version as source chain)
    # No need to copy binary from snapshot

    status("Starting node in tmux ...")
    start_cmd = '/opt/mirage/blockchain/bin/miraged start --home "/root/.mirage/node" 2>&1 | tee >(cronolog "/root/.mirage/logs/node/miraged-%Y-%m-%d.log")'
    run(["bash", "-lc", f"docker exec mirage tmux send-keys -t mirage:node '{start_cmd}' C-m"])

    status("Waiting for RPC ...")
    for _ in range(30):
        ok = run(
            [
                "bash",
                "-lc",
                "docker exec mirage curl -sf http://127.0.0.1:26657/status >/dev/null 2>&1 && echo ok || true",
            ],
            capture=True,
        ).strip()
        if ok == "ok":
            status("RPC is ready")
            break
        time.sleep(1)
    else:
        status("WARNING: RPC not available after 30s")
        return

    status("Ensuring PostgreSQL is running...")
    run(
        [
            "bash",
            "-lc",
            "docker exec mirage bash -c '"
            "pg_ctlcluster 16 main start 2>/dev/null || true; "
            "for i in $(seq 1 30); do pg_isready -h 127.0.0.1 -p 5432 -U postgres -t 1 >/dev/null 2>&1 && break || sleep 1; done'",
        ]
    )

    status("Starting indexer ...")
    run(["bash", "-lc", "docker exec mirage tmux send-keys -t mirage:indexer C-c 2>/dev/null || true"])
    time.sleep(2)  # Wait for node to stabilize
    initial_height = run(
        ["bash", "-lc", "docker exec mirage jq -r .initial_height /root/.mirage/node/config/genesis.json"],
        capture=True,
    ).strip()
    run(
        [
            "bash",
            "-lc",
            f"docker exec mirage tmux send-keys -t mirage:indexer 'PYTHONPATH=/opt/mirage python3 /opt/mirage/indexer/main.py --height {initial_height}' C-m",
        ]
    )

    status("Starting backend ...")
    run(["bash", "-lc", "docker exec mirage tmux send-keys -t mirage:backend C-c 2>/dev/null || true"])
    time.sleep(0.5)
    run(
        [
            "bash",
            "-lc",
            "docker exec mirage tmux send-keys -t mirage:backend 'cd /opt/mirage/web/backend && PYTHONPATH=/opt/mirage python3 -m gunicorn -c gunicorn_config.py factory:app' C-m",
        ]
    )

    # Start orchestrator (optional - may not exist in older builds)
    # Note: The entrypoint.sh can't create the orchestrator window because we killed the node
    # earlier (it waits for RPC before creating orchestrator window), so we create it here.
    orchestrator_exists = run(
        ["bash", "-lc", "docker exec mirage test -f /opt/mirage/blockchain/bin/orchestrator && echo yes || echo no"],
        capture=True,
    ).strip()
    if orchestrator_exists == "yes":
        try:
            status("Starting orchestrator ...")
            run(["bash", "-lc", "docker exec mirage mkdir -p /root/.mirage/orchestrator /root/.mirage/logs/orchestrator"])
            # Check if orchestrator window exists, create if not
            window_exists = run(
                [
                    "bash",
                    "-lc",
                    "docker exec mirage tmux list-windows -t mirage -F '#{window_name}' 2>/dev/null | grep -q '^orchestrator$' && echo yes || echo no",
                ],
                capture=True,
            ).strip()
            if window_exists != "yes":
                run(["bash", "-lc", "docker exec mirage tmux new-window -t mirage -n orchestrator -c /opt/mirage"])
                time.sleep(0.3)
            run(
                [
                    "bash",
                    "-lc",
                    'docker exec mirage tmux send-keys -t mirage:orchestrator \'/opt/mirage/blockchain/bin/orchestrator 2>&1 | tee >(cronolog "/root/.mirage/logs/orchestrator/orchestrator-%Y-%m-%d.log")\' C-m',
                ]
            )
        except Exception as e:
            status(f"WARNING: Orchestrator startup failed (optional): {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Reset local testnet from remote clone, then run single-validator simulation."
    )
    parser.add_argument("--source", default="mirage.vote", help="Source host (default: mirage.vote)")
    parser.add_argument("--file", dest="snapshot_file", default=None, help="Use local snapshot tarball (skip remote)")
    args = parser.parse_args()

    status("Reset local testnet: BEGIN")

    # Step 1: Get snapshot (fetch remote or use local file)
    if args.snapshot_file:
        tarball = Path(args.snapshot_file).expanduser().resolve()
        if not tarball.exists():
            raise RuntimeError(f"Snapshot file not found: {tarball}")
        status(f"Using local snapshot: {tarball}")
    else:
        tarball = remote_snapshot(args.source)
        status(f"Snapshot saved to: {tarball}")

    # Step 2: Extract snapshot to get image reference
    extract_dir, image_ref = extract_snapshot(tarball)

    # Step 3: Stop old container, pull exact image, start new container
    stop_local_container()
    ensure_local_container(image_ref)

    # Important: prevent the entrypoint from running the node while we rewrite home
    stop_node_in_container()

    # Step 4: Copy snapshot files into container
    export_path = copy_snapshot_into_container(extract_dir)

    scrub_consensus_key()
    val_addr, valoper, faucet_addr = ensure_test_keys()
    cons_pub_b64 = read_priv_validator_pubkey_b64()
    valcons_addr = compute_valcons_from_pubkey_b64(cons_pub_b64)
    new_genesis = transform_to_single_validator(export_path, val_addr, valoper, valcons_addr, cons_pub_b64, faucet_addr)
    write_working_genesis(new_genesis)

    # Clean up temp files (keep only .tgz snapshots)
    if export_path.exists():
        export_path.unlink()
    for item in MIRAGE_TMP.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)

    # Clean up redundant directories in container
    status("Cleaning up redundant directories...")
    run(
        [
            "bash",
            "-lc",
            "docker exec mirage bash -lc 'rm -rf /root/.mirage/node/snapshot /root/.mirage/node/.mirage /root/.mirage/node.clone 2>/dev/null || true'",
        ]
    )

    status("Local testnet reset: COMPLETE")
    print("Summary:")
    print("  - Working home: /root/.mirage/node")
    print("  - Validator:", val_addr)
    print("  - Valoper:", valoper)
    print("  - Faucet:", faucet_addr)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
