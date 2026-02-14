#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import backup_restore
from bech32 import bech32_decode, bech32_encode, convertbits  # type: ignore

ROOT = Path(__file__).resolve().parents[1]

# Solana bridge state constants (from orchestrator)
# BridgeState account layout (Anchor):
#   8 bytes: discriminator
#   1 byte:  bump
#   32 bytes: authority
#   8 bytes: last_sequence
# Total offset for last_sequence: 8 + 1 + 32 = 41


def query_solana_last_sequence() -> int | None:
    """Query Solana's bridge_state account to get the last_sequence.

    Returns the last_sequence value, or None if query fails.
    This is used to initialize Mirage's burn_sequence counter to match Solana.
    """
    solana_rpc = os.environ.get("ORCHESTRATOR_SOLANA_RPC", "https://api.devnet.solana.com")
    program_id = os.environ.get("ORCHESTRATOR_SOLANA_PROGRAM_ID", "9rMS8JEHCM5UTGjwKoXV7V32tzkgM9b16LZcbVdPAMdp")

    if not program_id:
        status("WARNING: ORCHESTRATOR_SOLANA_PROGRAM_ID not set, cannot query Solana")
        return None

    try:
        # Derive bridge_state PDA (seed = "bridge_state")
        # We use a simple approach: query via getProgramAccounts with memcmp filter
        # or compute the PDA directly. For simplicity, let's try to find it.
        from solders.pubkey import Pubkey  # type: ignore

        program_pubkey = Pubkey.from_string(program_id)
        bridge_state_pda, _ = Pubkey.find_program_address([b"bridge_state"], program_pubkey)

        # Query the account
        req_data = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [str(bridge_state_pda), {"encoding": "base64"}],
            }
        ).encode()

        req = urllib.request.Request(solana_rpc, data=req_data, headers={"Content-Type": "application/json"})

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.load(resp)

        account_info = result.get("result", {}).get("value")
        if not account_info:
            status(f"WARNING: Solana bridge_state account not found at {bridge_state_pda}")
            return None

        # Decode base64 data
        data_b64 = account_info.get("data", [None])[0]
        if not data_b64:
            status("WARNING: Solana bridge_state has no data")
            return None

        data = base64.b64decode(data_b64)
        if len(data) < 49:
            status(f"WARNING: Solana bridge_state data too short: {len(data)} bytes")
            return None

        # Extract last_sequence (little-endian uint64 at offset 41)
        last_sequence = struct.unpack("<Q", data[41:49])[0]
        status(f"Solana bridge_state last_sequence: {last_sequence}")
        return last_sequence

    except ImportError:
        status("WARNING: solders not installed, cannot derive Solana PDA")
        return None
    except Exception as e:
        status(f"WARNING: Failed to query Solana bridge_state: {e}")
        return None


MIRAGE_TMP = Path.home() / ".mirage" / "tmp"
BACKUP_DIR = backup_restore.BACKUP_DIR


def read_node_env_value(key: str) -> str:
    node_env = ROOT / "deploy" / "templates" / "env" / "node.env"
    if not node_env.exists():
        raise RuntimeError(f"node.env source not found: {node_env}")
    for raw in node_env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError(f"{key} missing in deploy/templates/env/node.env")


def read_positive_int(key: str) -> int:
    value = read_node_env_value(key)
    if not value.isdigit() or int(value) <= 0:
        raise RuntimeError(f"{key} must be a positive integer (got {value!r})")
    return int(value)


LOCAL_BLOCK_TIME_SECONDS = 2
LOCAL_RETENTION_BLOCKS = read_positive_int("RETENTION_BLOCKS")
LOCAL_PRUNING_INTERVAL = read_positive_int("PRUNING_INTERVAL")
LOCAL_SNAPSHOT_INTERVAL = read_positive_int("SNAPSHOT_INTERVAL")
LOCAL_SNAPSHOT_KEEP_RECENT = read_positive_int("SNAPSHOT_KEEP_RECENT")
LOCAL_RETENTION_SECONDS = LOCAL_RETENTION_BLOCKS * LOCAL_BLOCK_TIME_SECONDS

LOCAL_EVIDENCE_PARAMS = {
    "max_age_num_blocks": str(LOCAL_RETENTION_BLOCKS),
    "max_age_duration": str(LOCAL_RETENTION_SECONDS * 1_000_000_000),
    "max_bytes": "1048576",
}

LOCAL_APP_TOML_OVERRIDES = {
    "pruning-keep-recent": f'"{LOCAL_RETENTION_BLOCKS}"',
    "pruning-interval": f'"{LOCAL_PRUNING_INTERVAL}"',
    "min-retain-blocks": str(LOCAL_RETENTION_BLOCKS),
    "snapshot-interval": str(LOCAL_SNAPSHOT_INTERVAL),
    "snapshot-keep-recent": str(LOCAL_SNAPSHOT_KEEP_RECENT),
}


def ensure_mirage_tmp() -> Path:
    """Ensure ~/.mirage/tmp/ exists and return it."""
    try:
        MIRAGE_TMP.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        home = Path.home()
        uid = os.getuid()
        gid = os.getgid()
        run(
            [
                "bash",
                "-lc",
                f"docker run --rm -v '{home}/.mirage:/data' alpine sh -c "
                f'"mkdir -p /data/tmp && chown -R {uid}:{gid} /data/tmp"',
            ]
        )
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


def apply_local_pruning_settings():
    status("Applying local pruning settings (app.toml)...")
    overrides = LOCAL_APP_TOML_OVERRIDES
    script = f"""import re
from pathlib import Path

path = Path("/root/.mirage/node/config/app.toml")
if not path.exists():
    raise RuntimeError(f"app.toml not found at {{path}}")

content = path.read_text()
overrides = {overrides}

for key, value in overrides.items():
    pattern = rf"^{{re.escape(key)}}\\s*=.*$"
    repl = f"{{key}} = {{value}}"
    content, count = re.subn(pattern, repl, content, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"expected 1 match for {{key}}, got {{count}}")

path.write_text(content)
"""
    run(["bash", "-lc", f"docker exec -i mirage python3 - <<'PY'\n{script}\nPY"])
    status(f"Local pruning settings applied: {LOCAL_APP_TOML_OVERRIDES}")


def apply_local_evidence_params(gen: dict):
    consensus = gen.get("consensus")
    if not isinstance(consensus, dict):
        raise RuntimeError("missing consensus section in genesis")
    params = consensus.get("params")
    if not isinstance(params, dict):
        raise RuntimeError("missing consensus.params in genesis")
    evidence = params.get("evidence")
    if not isinstance(evidence, dict):
        raise RuntimeError("missing consensus.params.evidence in genesis")

    old = {
        "max_age_num_blocks": evidence.get("max_age_num_blocks"),
        "max_age_duration": evidence.get("max_age_duration"),
        "max_bytes": evidence.get("max_bytes"),
    }
    evidence.update(LOCAL_EVIDENCE_PARAMS)
    params["evidence"] = evidence
    consensus["params"] = params
    gen["consensus"] = consensus

    app_state = gen.get("app_state")
    if app_state is not None:
        if not isinstance(app_state, dict):
            raise RuntimeError("invalid app_state in genesis")
        consensus_state = app_state.get("consensus")
        if consensus_state is not None:
            if not isinstance(consensus_state, dict):
                raise RuntimeError("invalid app_state.consensus in genesis")
            cs_params = consensus_state.get("params")
            if not isinstance(cs_params, dict):
                raise RuntimeError("missing app_state.consensus.params in genesis")
            cs_evidence = cs_params.get("evidence")
            if not isinstance(cs_evidence, dict):
                raise RuntimeError("missing app_state.consensus.params.evidence in genesis")
            cs_evidence.update(LOCAL_EVIDENCE_PARAMS)
            cs_params["evidence"] = cs_evidence
            consensus_state["params"] = cs_params
            app_state["consensus"] = consensus_state
            gen["app_state"] = app_state

    status("Updated genesis evidence params: " f"old={{old}} new={{LOCAL_EVIDENCE_PARAMS}}")


# Cached miraged path inside container
_container_miraged_path: str | None = None


def get_container_miraged_path() -> str:
    """Get the miraged binary path inside the Docker container.

    Handles both old (/opt/mirage/blockchain/bin/miraged) and
    new (/opt/mirage/blockchain/miraged) directory structures.
    """
    global _container_miraged_path
    if _container_miraged_path is not None:
        return _container_miraged_path

    # Check new path first, then fall back to old path
    new_path = "/opt/mirage/blockchain/miraged"
    old_path = "/opt/mirage/blockchain/bin/miraged"

    result = subprocess.run(
        ["docker", "exec", "mirage", "test", "-f", new_path],
        capture_output=True,
    )
    if result.returncode == 0:
        _container_miraged_path = new_path
    else:
        _container_miraged_path = old_path

    return _container_miraged_path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


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
            f"--name mirage --hostname local-testnet --restart no "
            f"-e SKIP_PEERS=1 -e SKIP_VALIDATOR_CHECK=1 -e RESET_MODE=1 "
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


def create_full_backup(source_host: str, ssh_user: str) -> Path:
    status(f"Creating backup from {source_host} using backup_restore.py")
    return backup_restore.backup(source_host, ssh_user)


def find_latest_backup(source_host: str) -> Path:
    return backup_restore.find_latest_backup(source_host)


def extract_backup(backup_tar: Path) -> tuple[Path, str, Path]:
    status("Extracting backup locally...")
    ensure_mirage_tmp()
    extract_dir = Path(tempfile.mkdtemp(prefix="extract-", dir=str(MIRAGE_TMP)))
    run(["bash", "-lc", f"tar xzf '{backup_tar}' -C '{extract_dir}' --no-same-owner --no-same-permissions"])

    backup_root = extract_dir / ".mirage"
    if not backup_root.exists():
        raise RuntimeError(f"Expected .mirage directory not found after extraction: {backup_root}")

    image_ref_file = backup_root / "docker_image"
    if not image_ref_file.exists():
        raise RuntimeError(f"backup missing docker_image metadata: {image_ref_file}")
    image_ref = image_ref_file.read_text().strip()
    if not image_ref:
        raise RuntimeError("docker_image metadata is empty")
    status(f"Backup image: {image_ref}")

    return extract_dir, image_ref, backup_root


def run_export_from_backup(backup_root: Path, image_ref: str) -> Path:
    status("Running chain export from backup data...")
    export_path = backup_root / "export.json"
    if export_path.exists():
        export_path.unlink()

    status("Running export in isolated container (skip entrypoint)...")
    export_cmd = (
        "set -euo pipefail; "
        "if [ -x /opt/mirage/blockchain/miraged ]; then MIRAGED=/opt/mirage/blockchain/miraged; "
        "elif [ -x /opt/mirage/blockchain/bin/miraged ]; then MIRAGED=/opt/mirage/blockchain/bin/miraged; "
        "else echo 'ERROR: miraged binary not found in image' >&2; exit 1; fi; "
        "$MIRAGED export --home /root/.mirage/node --output-document /root/.mirage/export.json"
    )
    run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/bin/bash",
            "-v",
            f"{backup_root}:/root/.mirage",
            image_ref,
            "-c",
            export_cmd,
        ]
    )

    # Fix permissions on export.json (created as root by docker)
    uid = os.getuid()
    gid = os.getgid()
    run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{backup_root}:/root/.mirage",
            "alpine",
            "chown",
            f"{uid}:{gid}",
            "/root/.mirage/export.json",
        ]
    )

    if not export_path.exists():
        raise RuntimeError(f"export.json not created at {export_path}")
    return export_path


def stage_backup_into_container(backup_root: Path, export_path: Path) -> Path:
    """
    Stage backup files into the container.
    Returns the path to the local export.json file.
    """
    status("Preparing target directories inside container...")
    run(
        [
            "bash",
            "-lc",
            "docker exec mirage bash -lc '"
            "rm -rf /root/.mirage/node.clone; "
            "mkdir -p /root/.mirage/node.clone /root/.mirage/node'",
        ]
    )

    config_dir = backup_root / "node" / "config"
    if not config_dir.exists():
        raise RuntimeError(f"backup missing node config: {config_dir}")
    status("Copying config into container...")
    run(["bash", "-lc", f"docker cp '{config_dir}' mirage:/root/.mirage/node.clone/"])

    keyring_dirs = sorted(backup_root.glob("node/keyring-*"))
    if not keyring_dirs:
        raise RuntimeError("backup missing node keyring (expected node/keyring-*)")
    status("Copying keyring into container...")
    for keyring in keyring_dirs:
        run(["bash", "-lc", f"docker cp '{keyring}' mirage:/root/.mirage/node.clone/"])

    indexer_sql = backup_root / "backup_indexer.sql"
    if not indexer_sql.exists():
        raise RuntimeError(f"backup missing indexer SQL dump: {indexer_sql}")
    status("Copying PostgreSQL indexer dump...")
    run(["bash", "-lc", f"docker cp '{indexer_sql}' mirage:/root/.mirage/node.clone/indexer.sql"])

    migrations_file = backup_root / "env" / ".migrations"
    if migrations_file.exists():
        status("Copying .migrations file...")
        run(["bash", "-lc", "docker exec mirage mkdir -p /root/.mirage/env"])
        run(["bash", "-lc", f"docker cp '{migrations_file}' mirage:/root/.mirage/env/.migrations"])

    run(["bash", "-lc", "docker exec mirage chmod -R u+rwX /root/.mirage/node.clone || true"])

    local_export = MIRAGE_TMP / "export.json"
    shutil.copy(export_path, local_export)

    status("Backup staged")
    return local_export


def restore_indexer_database():
    """Restore local indexer PostgreSQL database from the backup dump, if present."""
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
    raw = run(
        ["bash", "-lc", "docker exec mirage cat /root/.mirage/node.clone/config/priv_validator_key.json"],
        capture=True,
    )
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


def convert_bech32_prefix(addr: str, target_prefix: str) -> str:
    hrp, data5 = bech32_decode(addr)
    if not hrp or data5 is None:
        raise RuntimeError(f"invalid bech32 address: {addr}")
    # data5 is already in 5-bit form from bech32_decode, just re-encode with new prefix
    return bech32_encode(target_prefix, data5)


def find_validator_by_consensus_pubkey(validators: list, cons_pub_b64: str) -> dict:
    for v in validators:
        pub = v.get("consensus_pubkey") or {}
        key = pub.get("key") or pub.get("value")
        if key == cons_pub_b64:
            return v
    raise RuntimeError("validator matching consensus pubkey not found in staking.validators")


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


def transform_to_single_validator(export_path: Path, cons_pub_b64: str) -> tuple[str, str, str, str]:
    status("Building single-validator genesis...")
    with open(export_path, "r", encoding="utf-8") as f:
        gen = json.load(f)

    apply_local_evidence_params(gen)

    app_state = gen.get("app_state") or {}
    auth = app_state.get("auth") or {}
    staking = app_state.get("staking") or {}
    bank = app_state.get("bank") or {}
    slashing = app_state.get("slashing") or {}
    upgrade_state = app_state.get("upgrade") or {}
    core_state = app_state.get("core") or {}
    gov_state = app_state.get("gov") or {}

    gov_params = gov_state.get("params") or {}
    min_deposit = gov_params.get("min_deposit", [])
    expedited_min_deposit = gov_params.get("expedited_min_deposit", [])
    if min_deposit and expedited_min_deposit:
        min_amt = int(min_deposit[0].get("amount", "0"))
        exp_amt = int(expedited_min_deposit[0].get("amount", "0"))
        if exp_amt <= min_amt:
            expedited_min_deposit[0]["amount"] = str(min_amt * 2)
            gov_params["expedited_min_deposit"] = expedited_min_deposit
            gov_state["params"] = gov_params
            app_state["gov"] = gov_state

    existing_profiles = core_state.get("initial_profiles") or []
    if len(existing_profiles) <= 10:
        indexer_profiles = load_profiles_from_indexer_db()
        if indexer_profiles:
            core_state["initial_profiles"] = indexer_profiles
            status(f"Injected {len(indexer_profiles)} profiles from indexer DB into genesis")

    solana_last_seq = query_solana_last_sequence()
    if solana_last_seq is not None and solana_last_seq > 0:
        raw_state = core_state.get("raw_state") or []
        seq_key = base64.b64encode(b"bridge_sequence/solana").decode()
        seq_value = base64.b64encode(struct.pack(">Q", solana_last_seq)).decode()
        raw_state = [kv for kv in raw_state if kv.get("key") != seq_key]
        raw_state.append({"key": seq_key, "value": seq_value})
        core_state["raw_state"] = raw_state
        status(f"Injected bridge_sequence/solana={solana_last_seq} into genesis raw_state")

    app_state["core"] = core_state

    auth_accounts = auth.get("accounts") or []
    bonded_pool_addr = find_module_account_address(auth_accounts, "bonded_tokens_pool")
    not_bonded_pool_addr = find_module_account_address(auth_accounts, "not_bonded_tokens_pool")
    if not bonded_pool_addr or not not_bonded_pool_addr:
        raise RuntimeError(
            f"Could not find staking module accounts in genesis: bonded={bonded_pool_addr}, not_bonded={not_bonded_pool_addr}"
        )
    status(f"Staking pools: bonded={bonded_pool_addr}, not_bonded={not_bonded_pool_addr}")

    validators = staking.get("validators") or []
    if not validators:
        raise RuntimeError("no validators found in staking state")
    selected = find_validator_by_consensus_pubkey(validators, cons_pub_b64)
    valoper = selected.get("operator_address")
    if not valoper:
        raise RuntimeError("selected validator missing operator_address")
    val_addr = convert_bech32_prefix(valoper, "mirage")
    valcons = compute_valcons_from_pubkey_b64(cons_pub_b64)
    status(f"Using validator: {valoper} (account {val_addr})")

    total_bonded_base = 0
    for v in validators:
        if str(v.get("status", "")) == "BOND_STATUS_BONDED":
            total_bonded_base += int(str(v.get("tokens", "0")))

    balances = bank.get("balances") or []
    old_bonded_balance = 0
    old_not_bonded_balance = 0
    for bal in balances:
        addr = bal.get("address", "")
        if addr == bonded_pool_addr:
            for coin in bal.get("coins") or []:
                if coin.get("denom") == "umirage":
                    old_bonded_balance = int(coin.get("amount", "0"))
        elif addr == not_bonded_pool_addr:
            for coin in bal.get("coins") or []:
                if coin.get("denom") == "umirage":
                    old_not_bonded_balance = int(coin.get("amount", "0"))

    total_bonded = total_bonded_base + old_not_bonded_balance
    power_reduction = 1_000_000
    last_power = str(total_bonded // power_reduction)
    tokens_str = str(total_bonded)
    status(f"Total bonded: {total_bonded} umirage, power={last_power}")

    cons_pub = selected.get("consensus_pubkey") or {}
    cons_pub = {
        "@type": cons_pub.get("@type") or "/cosmos.crypto.ed25519.PubKey",
        "key": cons_pub_b64,
    }
    single_validator = dict(selected)
    single_validator.update(
        {
            "consensus_pubkey": cons_pub,
            "jailed": False,
            "status": "BOND_STATUS_BONDED",
            "tokens": tokens_str,
            "delegator_shares": tokens_str,
            "unbonding_height": "0",
            "unbonding_time": "0001-01-01T00:00:00Z",
            "min_self_delegation": "1",
        }
    )

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

    new_balances = []
    for bal in balances:
        addr = bal.get("address", "")
        if addr == bonded_pool_addr:
            new_balances.append({"address": addr, "coins": [{"denom": "umirage", "amount": str(total_bonded)}]})
        elif addr == not_bonded_pool_addr:
            continue
        else:
            new_balances.append(bal)
    bank["balances"] = new_balances

    supply_delta = (total_bonded - old_bonded_balance) - old_not_bonded_balance
    status(
        f"Supply delta: {supply_delta} (bonded: {old_bonded_balance} -> {total_bonded}, "
        f"not_bonded: {old_not_bonded_balance} -> 0)"
    )
    supply_list = bank.get("supply") or []
    for c in supply_list:
        if c.get("denom") == "umirage":
            c["amount"] = str(int(c.get("amount", "0")) + supply_delta)
            break
    else:
        supply_list.append({"denom": "umirage", "amount": str(supply_delta)})
    bank["supply"] = supply_list
    app_state["bank"] = bank

    if not any(
        acc.get("address") == val_addr
        or (acc.get("@type") == "/cosmos.auth.v1beta1.BaseAccount" and acc.get("address") == val_addr)
        for acc in auth_accounts
    ):
        auth_accounts.append(
            {
                "@type": "/cosmos.auth.v1beta1.BaseAccount",
                "address": val_addr,
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
    return json.dumps(gen, ensure_ascii=False), val_addr, valoper, valcons


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
            "for f in app.toml config.toml client.toml priv_validator_key.json node_key.json; do "
            "  cp -f /root/.mirage/node.clone/config/$f /root/.mirage/node/config/ 2>/dev/null || true; "
            "done; "
            "for d in /root/.mirage/node.clone/keyring-*; do "
            '  if [ -d "$d" ]; then cp -nR "$d" /root/.mirage/node/; fi; '
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

    apply_local_pruning_settings()

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
    # No need to copy binary from backup

    # Disable tmux automatic-rename so windows created with -n keep their names
    # (otherwise tmux renames them to the running process, breaking send-keys by name)
    run(["bash", "-lc", "docker exec mirage tmux set-option -g automatic-rename off 2>/dev/null || true"])
    run(["bash", "-lc", "docker exec mirage tmux set-option -g allow-rename off 2>/dev/null || true"])

    # Create a fresh tmux window (kill first if it exists from a previous run).
    def ensure_tmux_window(window_name: str):
        run(["bash", "-lc", f"docker exec mirage tmux kill-window -t mirage:{window_name} 2>/dev/null || true"])
        time.sleep(0.2)
        run(["bash", "-lc", f"docker exec mirage tmux new-window -t mirage -n {window_name} -c /opt/mirage"])
        time.sleep(0.5)

    status("Starting node in tmux ...")
    ensure_tmux_window("node")
    miraged = get_container_miraged_path()
    start_cmd = f'{miraged} start --home "/root/.mirage/node" 2>&1 | tee >(cronolog "/root/.mirage/logs/node/miraged-%Y-%m-%d.log")'
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
    ensure_tmux_window("indexer")
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
    ensure_tmux_window("backend")
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
        ["bash", "-lc", "docker exec mirage test -f /opt/mirage/blockchain/orchestrator && echo yes || echo no"],
        capture=True,
    ).strip()
    if orchestrator_exists == "yes":
        try:
            status("Starting orchestrator ...")
            run(
                [
                    "bash",
                    "-lc",
                    "docker exec mirage mkdir -p /root/.mirage/orchestrator /root/.mirage/logs/orchestrator",
                ]
            )
            ensure_tmux_window("orchestrator")
            run(
                [
                    "bash",
                    "-lc",
                    "docker exec mirage tmux send-keys -t mirage:orchestrator '/opt/mirage/blockchain/orchestrator 2>&1 | tee >(cronolog \"/root/.mirage/logs/orchestrator/orchestrator-%Y-%m-%d.log\")' C-m",
                ]
            )
        except Exception as e:
            status(f"WARNING: Orchestrator startup failed (optional): {e}")


def find_latest_backup_tarball(source_host: str) -> Path:
    status(f"Finding latest backup for {source_host} in {BACKUP_DIR}...")
    return find_latest_backup(source_host)


def main():
    parser = argparse.ArgumentParser(
        description="Reset local testnet from full server backup, then run single-validator simulation."
    )
    parser.add_argument("--source", default="mirage.vote", help="Source host (default: mirage.vote)")
    parser.add_argument("--user", default="root", help="SSH user (default: root)")
    parser.add_argument("--file", dest="backup_file", default=None, help="Use local backup tarball (skip remote)")
    parser.add_argument("--latest", action="store_true", help="Use the latest backup from ~/.mirage/backups/")
    args = parser.parse_args()

    status("Reset local testnet: BEGIN")

    # Step 1: Get backup (fetch remote or use local file)
    if args.latest:
        tarball = find_latest_backup_tarball(args.source)
        status(f"Using latest backup: {tarball}")
    elif args.backup_file:
        tarball = Path(args.backup_file).expanduser().resolve()
        if not tarball.exists():
            raise RuntimeError(f"Backup file not found: {tarball}")
        status(f"Using local backup: {tarball}")
    else:
        tarball = create_full_backup(args.source, args.user)
        status(f"Backup saved to: {tarball}")

    # Step 2: Extract backup and read image reference
    extract_dir, image_ref, backup_root = extract_backup(tarball)

    # Step 3: Export chain state from backup data (exact binary from image)
    export_path = run_export_from_backup(backup_root, image_ref)

    # Step 4: Stop old container, pull exact image, start new container
    stop_local_container()
    ensure_local_container(image_ref)

    # Important: prevent the entrypoint from running the node while we rewrite home
    stop_node_in_container()

    # Step 5: Stage backup files into container
    export_path = stage_backup_into_container(backup_root, export_path)
    status("Cleaning up extracted backup files...")
    shutil.rmtree(extract_dir, ignore_errors=True)

    cons_pub_b64 = read_priv_validator_pubkey_b64()
    new_genesis, val_addr, valoper, valcons_addr = transform_to_single_validator(export_path, cons_pub_b64)
    write_working_genesis(new_genesis)

    # Clean up temp files (keep only backup tarballs)
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
            "docker exec mirage bash -lc 'rm -rf /root/.mirage/node/.mirage /root/.mirage/node.clone 2>/dev/null || true'",
        ]
    )

    status("Local testnet reset: COMPLETE")
    print("Summary:")
    print("  - Working home: /root/.mirage/node")
    print("  - Validator:", val_addr)
    print("  - Valoper:", valoper)
    print("  - Valcons:", valcons_addr)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
