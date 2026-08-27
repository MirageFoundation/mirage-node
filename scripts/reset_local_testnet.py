#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import backup_restore
from bech32 import bech32_decode, bech32_encode, convertbits  # type: ignore

ROOT = Path(__file__).resolve().parents[1]

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


# Matches the fleet's timeout_commit (deploy/templates/node/config.toml default).
# Local used to run 2s, which made block-derived windows look 33% tighter here
# than in production: block_hash_window at 60 blocks is 120s at 2s but 180s at
# 3s, and that gap is exactly where a too-narrow window hides during testing.
LOCAL_BLOCK_TIME_SECONDS = 3
LOCAL_RETENTION_BLOCKS = read_positive_int("RETENTION_BLOCKS")
LOCAL_RETENTION_SECONDS = LOCAL_RETENTION_BLOCKS * LOCAL_BLOCK_TIME_SECONDS

LOCAL_EVIDENCE_PARAMS = {
    "max_age_num_blocks": str(LOCAL_RETENTION_BLOCKS),
    "max_age_duration": str(LOCAL_RETENTION_SECONDS * 1_000_000_000),
    "max_bytes": "1048576",
}
EXTRA_VALIDATOR_FUNDS_MIRAGE = 10_000_000
EXTRA_VALIDATOR_FUNDS_UMIRAGE = EXTRA_VALIDATOR_FUNDS_MIRAGE * 1_000_000


def ensure_mirage_tmp() -> Path:
    """Ensure ~/.mirage/tmp/ exists and is writable."""

    def fix_permissions():
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

    try:
        MIRAGE_TMP.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        status("Fixing permissions on ~/.mirage/tmp ...")
        fix_permissions()
    if not os.access(MIRAGE_TMP, os.W_OK | os.X_OK):
        status("Fixing permissions on ~/.mirage/tmp ...")
        fix_permissions()
    if not os.access(MIRAGE_TMP, os.W_OK | os.X_OK):
        raise RuntimeError(f"tmp directory is not writable: {MIRAGE_TMP}")
    return MIRAGE_TMP


def status(msg: str):
    print(f"==> {msg}", flush=True)


def run(cmd, check=True, capture=False):
    if capture:
        result = subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout
    subprocess.run(cmd, check=check, text=True)
    return ""


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

    status(f"Starting local container with image: {image_ref} (entrypoint disabled)")
    run(
        [
            "bash",
            "-lc",
            f"docker run -d {backup_restore.CONTAINER_PORTS} "
            f"--name mirage --hostname testnet --restart no "
            f"-e SKIP_PEERS=1 -e SKIP_VALIDATOR_CHECK=1 "
            f"--entrypoint /bin/bash "
            f"-v {home}/.mirage:/root/.mirage -v {home}/.caddy:/root/.local/share/caddy '{image_ref}' "
            f"-lc 'sleep 31536000'",
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


def _clean_snapshots(backup_root: Path) -> None:
    """Remove state sync snapshots from backup data before export.

    The export command doesn't need snapshots, and pruned snapshot directories
    often have stale metadata referencing chunk files that no longer exist,
    which causes PebbleDB objstorage errors during export.
    """
    snapshots_dir = backup_root / "node" / "data" / "snapshots"
    if snapshots_dir.exists():
        status("Removing snapshots directory (not needed for export)...")
        shutil.rmtree(snapshots_dir)


def run_export_from_backup(backup_root: Path, image_ref: str) -> Path:
    status("Running chain export from backup data...")
    export_path = backup_root / "export.json"
    if export_path.exists():
        export_path.unlink()

    _clean_snapshots(backup_root)

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

    backend_sql = backup_root / "backup_backend.sql"
    if backend_sql.exists():
        status("Copying PostgreSQL backend dump...")
        run(["bash", "-lc", f"docker cp '{backend_sql}' mirage:/root/.mirage/node.clone/backend.sql"])
    else:
        status("No backend SQL dump found (will be initialized by the application)")

    # Copy env directory (node.env, backend.env, .migrations, etc.)
    # These provide RETENTION_BLOCKS, INDEXER_DB_URL, etc. for the entrypoint
    env_dir = backup_root / "env"
    if env_dir.exists() and env_dir.is_dir():
        migrations_file = env_dir / ".migrations"
        if not migrations_file.exists():
            status("Backup env missing .migrations (migrations will be re-evaluated on startup)")
        status("Copying env files from backup (clearing old env first)...")
        run(["bash", "-lc", "docker exec mirage rm -rf /root/.mirage/env"])
        run(["bash", "-lc", "docker exec mirage mkdir -p /root/.mirage/env"])
        for item in sorted(env_dir.iterdir()):
            if item.is_file():
                run(["bash", "-lc", f"docker cp '{item}' mirage:/root/.mirage/env/"])
        desired_snapshot_keep_recent = read_node_env_value("SNAPSHOT_KEEP_RECENT")
        if not desired_snapshot_keep_recent.isdigit() or int(desired_snapshot_keep_recent) <= 0:
            raise RuntimeError(
                f"SNAPSHOT_KEEP_RECENT must be a positive integer (got {desired_snapshot_keep_recent!r})"
            )
        status(f"Enforcing SNAPSHOT_KEEP_RECENT={desired_snapshot_keep_recent} in container env...")
        run(
            [
                "bash",
                "-lc",
                "docker exec mirage bash -lc "
                f"'set -euo pipefail; "
                'if ! grep -q "^SNAPSHOT_KEEP_RECENT=" /root/.mirage/env/node.env; then '
                'echo "SNAPSHOT_KEEP_RECENT missing in /root/.mirage/env/node.env" >&2; exit 1; '
                "fi; "
                f'sed -i "s/^SNAPSHOT_KEEP_RECENT=.*/SNAPSHOT_KEEP_RECENT={desired_snapshot_keep_recent}/" '
                "/root/.mirage/env/node.env'",
            ]
        )
        # Force backend-db-split migration to re-run (production backup has the
        # marker but the local backend DB is restored separately and may be empty)
        run(
            [
                "bash",
                "-lc",
                "docker exec mirage sed -i '/v1\\.21\\.10-migrate-backend-db-split/d' /root/.mirage/env/.migrations 2>/dev/null || true",
            ]
        )
        if migrations_file.exists():
            status("Forcing snapshot retention migration to re-run on startup...")
            run(
                [
                    "bash",
                    "-lc",
                    "docker exec mirage sed -i '/v1\\.22\\.0-snapshot-keep-recent/d' /root/.mirage/env/.migrations",
                ]
            )
        # Clear DOMAIN to prevent entrypoint from attempting HTTPS/LetsEncrypt setup locally
        # Clear PERSISTENT_PEERS so the local testnet is fully isolated from the real network
        run(
            [
                "bash",
                "-lc",
                "docker exec mirage sed -i "
                "'s/^DOMAIN=.*/DOMAIN=/; "
                "s/^PERSISTENT_PEERS=.*/PERSISTENT_PEERS=/' "
                "/root/.mirage/env/node.env 2>/dev/null || true",
            ]
        )
        # Enable open registration without invite codes for local testnet
        run(
            [
                "bash",
                "-lc",
                "docker exec mirage sed -i "
                "'s/^REGISTRATION_ENABLED=.*/REGISTRATION_ENABLED=true/; "
                "s/^REGISTRATION_INVITE_CODE_REQUIRED=.*/REGISTRATION_INVITE_CODE_REQUIRED=false/; "
                "s/^OPEN_BROWSING_ENABLED=.*/OPEN_BROWSING_ENABLED=true/' "
                "/root/.mirage/env/backend.env 2>/dev/null || true",
            ]
        )
        # OPEN_BROWSING_ENABLED is required (settings.require_bool_env); append if
        # this node's backend.env predates the template that introduced it.
        run(
            [
                "bash",
                "-lc",
                "docker exec mirage sh -c "
                "'grep -q ^OPEN_BROWSING_ENABLED= /root/.mirage/env/backend.env "
                "|| echo OPEN_BROWSING_ENABLED=true >> /root/.mirage/env/backend.env' 2>/dev/null || true",
            ]
        )

    run(["bash", "-lc", "docker exec mirage chmod -R u+rwX /root/.mirage/node.clone || true"])

    local_export = MIRAGE_TMP / "export.json"
    shutil.copy(export_path, local_export)

    status("Backup staged")
    return local_export


def restore_indexer_database(chain_id: str):
    """Restore local indexer PostgreSQL database from the backup dump, if present.

    The dump's checkpoint sits just below the new chain's initial_height, so the
    indexer can never hash-compare it. Stamp meta.chain_id here — this script is
    the operator action that decides the restored rows belong to the chain it
    just built — otherwise startup refuses to index a database whose lineage it
    cannot establish.
    """
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

    # Drop and recreate databases + roles, then restore dumps
su - postgres <<EOF
psql -c "DROP DATABASE IF EXISTS mirage_indexer"
psql -c "DROP DATABASE IF EXISTS mirage_backend"
psql -c "DROP ROLE IF EXISTS mirage_indexer_ro"
psql -c "DROP ROLE IF EXISTS mirage_indexer"
psql -c "DROP ROLE IF EXISTS mirage_backend"
psql -c "DROP ROLE IF EXISTS mirage_ro"
psql -c "DROP ROLE IF EXISTS mirage"
psql -c "CREATE ROLE mirage_indexer WITH LOGIN PASSWORD 'mirage_indexer'"
psql -c "CREATE ROLE mirage_indexer_ro WITH LOGIN PASSWORD 'mirage_indexer_ro'"
psql -c "CREATE ROLE mirage_backend WITH LOGIN PASSWORD 'mirage_backend'"
psql -c "CREATE DATABASE mirage_indexer OWNER mirage_indexer"
psql -c "CREATE DATABASE mirage_backend OWNER mirage_backend"
psql -d mirage_indexer -f "$DUMP_FILE"
psql -d mirage_indexer -c "GRANT CONNECT ON DATABASE mirage_indexer TO mirage_indexer_ro"
psql -d mirage_indexer -c "GRANT USAGE ON SCHEMA public TO mirage_indexer_ro"
psql -d mirage_indexer -c "GRANT SELECT ON ALL TABLES IN SCHEMA public TO mirage_indexer_ro"
psql -d mirage_indexer -c "ALTER DEFAULT PRIVILEGES FOR ROLE mirage_indexer IN SCHEMA public GRANT SELECT ON TABLES TO mirage_indexer_ro"
psql -d mirage_indexer -c "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT ON TABLES TO mirage_indexer_ro"
EOF

BACKEND_DUMP="/root/.mirage/node.clone/backend.sql"
if [ -f "$BACKEND_DUMP" ]; then
    su - postgres -c "psql -d mirage_backend -f $BACKEND_DUMP"
    echo "Backend DB restored from dump"
else
    echo "No backend dump found, backend DB will be initialized by the application"
fi

su - postgres -c "psql -d mirage_indexer -c \\"INSERT INTO meta (key, value) VALUES ('chain_id', '__CHAIN_ID__') ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value\\""
echo "Stamped indexer provenance: chain_id=__CHAIN_ID__"

echo "Databases restored"
"""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", chain_id):
        raise RuntimeError(f"refusing to stamp unexpected chain_id: {chain_id!r}")
    script = script.replace("__CHAIN_ID__", chain_id)

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

su - postgres -c "psql -c \\"DROP DATABASE IF EXISTS mirage_indexer;\\""
su - postgres -c "psql -c \\"DROP ROLE IF EXISTS mirage_indexer_ro;\\""
su - postgres -c "psql -c \\"DROP ROLE IF EXISTS mirage_indexer;\\""
su - postgres -c "psql -c \\"DROP ROLE IF EXISTS mirage;\\""
su - postgres -c "psql -c \\"CREATE ROLE mirage_indexer WITH LOGIN PASSWORD 'mirage_indexer';\\""
su - postgres -c "psql -c \\"CREATE DATABASE mirage_indexer OWNER mirage_indexer;\\""
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

    Returns profiles in InitialProfile format matching the IMAGE binary's schema.
    The image binary may predate field renames (e.g. followed_moderators → enabled_agents),
    so we detect which proto fields the image knows and use the matching names.
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
# Support both new (enabled_agents) and old (followed_mods) schema for backup compatibility
enabled_agents_data = parse_copy_data(content, "enabled_agents", [])
if not enabled_agents_data:
    enabled_agents_data = parse_copy_data(content, "followed_mods", [])

agents_map = {}
for row in enabled_agents_data:
    owner = (row.get("owner") or "").lower()
    agent = row.get("agent") or row.get("moderator") or ""  # moderator for old schema
    if owner and agent:
        agents_map.setdefault(owner, []).append(agent)

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
    profiles.append({
        "core": {
            "owner": owner,
            "username": username,
            "level": lvl,
            "biography": bio,
            "avatar": avatar,
        },
        "enabled_agents": agents_map.get(owner_key, []),
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
    export_path: Path, cons_pub_b64: str, *, easy_difficulty: bool = False
) -> tuple[str, str, str, str]:
    status("Building single-validator genesis...")
    with open(export_path, "r", encoding="utf-8") as f:
        gen = json.load(f)

    apply_local_evidence_params(gen)

    app_state = gen.get("app_state") or {}

    # v1.28.0 removes x/group and x/circuit. An export taken from a pre-v1.28.0
    # binary still carries their app_state sections; the new binary has no such
    # modules, so drop them here to keep InitGenesis clean.
    for removed_module in ("group", "circuit"):
        if app_state.pop(removed_module, None) is not None:
            status(f"Stripped removed module '{removed_module}' from genesis app_state")

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

    core_params = core_state.get("params")
    if not isinstance(core_params, dict):
        raise RuntimeError("core genesis params must be an object")

    # Bridge params and bridge_* raw_state keys are deliberately left intact. This genesis is
    # imported by the binary from the backup image, which still validates
    # bridge_attestation_threshold and would reject a genesis without it. The v1.31.0 upgrade
    # handler is what removes them, so leaving them here is also what lets a local run rehearse
    # that cleanup against real state.

    if easy_difficulty:
        core_params["pow_message_limit"] = "9999999"
        status("Easy difficulty: set pow_message_limit=9999999")

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
    extra_validator_funds = EXTRA_VALIDATOR_FUNDS_UMIRAGE
    if extra_validator_funds <= 0:
        raise RuntimeError("EXTRA_VALIDATOR_FUNDS_MIRAGE must be a positive integer")
    status(
        f"DEBUG: Extra validator funds configured: {EXTRA_VALIDATOR_FUNDS_MIRAGE} MIRAGE "
        f"({extra_validator_funds} umirage)"
    )

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
    val_balance_before = None
    for bal in new_balances:
        if bal.get("address") != val_addr:
            continue
        coins = bal.get("coins")
        if not isinstance(coins, list):
            raise RuntimeError("invalid coins for validator balance (expected list)")
        for coin in coins:
            if coin.get("denom") != "umirage":
                continue
            amount_raw = coin.get("amount")
            if amount_raw is None:
                raise RuntimeError("missing amount for validator umirage balance")
            if not str(amount_raw).isdigit():
                raise RuntimeError(f"invalid validator umirage balance amount: {amount_raw!r}")
            val_balance_before = int(amount_raw)
            coin["amount"] = str(val_balance_before + extra_validator_funds)
            break
        else:
            val_balance_before = 0
            coins.append({"denom": "umirage", "amount": str(extra_validator_funds)})
        bal["coins"] = coins
        break
    if val_balance_before is None:
        new_balances.append(
            {"address": val_addr, "coins": [{"denom": "umirage", "amount": str(extra_validator_funds)}]}
        )
        val_balance_before = 0
    status(
        "DEBUG: Added extra validator funds: "
        f"{val_balance_before} -> {val_balance_before + extra_validator_funds} umirage"
    )
    bank["balances"] = new_balances

    supply_delta = (total_bonded - old_bonded_balance) - old_not_bonded_balance + extra_validator_funds
    status(
        f"Supply delta: {supply_delta} (bonded: {old_bonded_balance} -> {total_bonded}, "
        f"not_bonded: {old_not_bonded_balance} -> 0, extra_validator_funds: {extra_validator_funds})"
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


def prepare_local_node(genesis_json: str):
    """Prepare node directory with transformed genesis for local testnet.

    This only sets up files in ~/.mirage/ so the container can start
    with the normal entrypoint (which handles all service orchestration).
    Config files (config.toml, app.toml, client.toml, Caddyfile) are NOT
    copied from backup - they are rendered fresh from templates by init.sh.
    """
    status("Writing genesis to /root/.mirage/node/config/genesis.json ...")
    ensure_mirage_tmp()
    tmp = Path(tempfile.mkdtemp(prefix="genesis-", dir=str(MIRAGE_TMP)))
    local_path = tmp / "genesis.json"
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(genesis_json)
    run(["bash", "-lc", "docker exec mirage mkdir -p /root/.mirage/node/config"])
    run(["bash", "-lc", f"docker cp '{local_path}' mirage:/root/.mirage/node/config/genesis.json"])
    shutil.rmtree(tmp, ignore_errors=True)

    # Copy identity files only (config is rendered fresh by entrypoint/init.sh from templates)
    # priv_validator_key.json: required (genesis references this validator's consensus key)
    # node_key.json: NOT copied — CometBFT auto-generates a fresh one on startup,
    #   giving the local testnet a unique P2P identity that can't collide with production
    status("Copying identity files from backup (node_key.json will be auto-generated) ...")
    run(
        [
            "bash",
            "-lc",
            "docker exec mirage bash -lc '"
            "mkdir -p /root/.mirage/node/config; "
            "cp -f /root/.mirage/node.clone/config/priv_validator_key.json /root/.mirage/node/config/; "
            "for d in /root/.mirage/node.clone/keyring-*; do "
            '  if [ -d "$d" ]; then cp -nR "$d" /root/.mirage/node/; fi; '
            "done'",
        ]
    )

    status("Clearing data directory ...")
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
    restore_indexer_database(json.loads(genesis_json)["chain_id"])


def start_with_entrypoint(image_ref: str):
    """Stop prep container and start with the normal entrypoint (identical to production).

    The entrypoint.sh handles everything: loading env files, running init.sh
    (which renders config templates, Caddyfile, etc.), starting all services
    (caddy, postgres, node, indexer, backend, status dashboard),
    maintenance mode, and health checks.

    Local testnet overrides are passed as container env vars:
    - SKIP_PEERS=1: no peer connections
    - SKIP_VALIDATOR_CHECK=1: skip key validation in init.sh
    - CREATE_EMPTY_BLOCKS=true: produce blocks even with no txs. The fleet
      leaves this false because real traffic keeps it advancing; an idle local
      chain would otherwise never move, stalling anything that waits on height.
    - CREATE_EMPTY_BLOCKS_INTERVAL / TIMEOUT_COMMIT: both the fleet's 3s, so
      block-derived windows span the same wall-clock here as in production.
    """
    status("Starting container with normal entrypoint (like production) ...")
    run(["bash", "-lc", "docker rm -f mirage 2>/dev/null || true"])

    home = str(Path.home())
    run(
        [
            "bash",
            "-lc",
            f"docker run -d --name mirage --hostname testnet --restart no "
            # Containers inherit the Docker daemon's 1024 soft nofile limit and
            # never see /etc/security/limits.d/99-mirage.conf, so the node,
            # Postgres, indexer and backend shared 1024 descriptors. Matches the
            # deploy path and what harden_server.sh already intends.
            f"--ulimit nofile=131072:131072 "
            f"-e SKIP_PEERS=1 -e SKIP_VALIDATOR_CHECK=1 "
            f"-e CREATE_EMPTY_BLOCKS=true "
            f"-e CREATE_EMPTY_BLOCKS_INTERVAL={LOCAL_BLOCK_TIME_SECONDS}s "
            f"-e TIMEOUT_COMMIT={LOCAL_BLOCK_TIME_SECONDS}s "
            f"{backup_restore.CONTAINER_PORTS} "
            f"-v {home}/.mirage:/root/.mirage "
            f"-v {home}/.caddy:/root/.local/share/caddy "
            f"'{image_ref}'",
        ]
    )

    status("Waiting for services (entrypoint handles startup) ...")
    for _ in range(120):
        ok = run(
            [
                "bash",
                "-lc",
                "docker exec mirage curl -sf http://127.0.0.1:26657/status >/dev/null 2>&1 && echo ok || true",
            ],
            capture=True,
        ).strip()
        if ok == "ok":
            status("Node RPC is ready")
            break
        time.sleep(2)
    else:
        raise RuntimeError("Node not ready after 240s. Check: mirage-status  (or docker logs -f mirage)")

    # Quick verification that entrypoint started everything
    time.sleep(5)
    checks = {
        "node": "pgrep -f 'miraged start' >/dev/null 2>&1",
        "caddy": "pgrep -f 'caddy run' >/dev/null 2>&1",
        "postgres": "pg_isready -h 127.0.0.1 -p 5432 -U postgres -t 1 >/dev/null 2>&1",
        "backend": "pgrep -f gunicorn >/dev/null 2>&1",
        "indexer": "pgrep -f 'indexer/main.py' >/dev/null 2>&1",
    }
    all_ok = True
    for name, cmd in checks.items():
        result = run(
            ["bash", "-lc", f"docker exec mirage bash -c '{cmd}' && echo ok || echo fail"],
            capture=True,
        ).strip()
        if result == "ok":
            print(f"  ✓ {name}")
        else:
            print(f"  ✗ {name} NOT RUNNING")
            all_ok = False

    if not all_ok:
        status("WARNING: Some services failed. Check: mirage-status  (or docker logs -f mirage)")
    else:
        status("All services running")


def configure_local_backend_env() -> None:
    """Turn on the settings the local suites need.

    Local testnet only — this patches the container's backend.env, never a
    deployed one. Media uploads are exercised by the backend suite, and debug
    logging is what makes a failed probe diagnosable from the container log.

    Must run before start_with_entrypoint(), so the backend reads the final
    values on its first start and needs no restart.
    """
    status("Configuring backend.env for the local testnet ...")

    # sed the values that exist; append the ones this node's backend.env predates.
    settings = {
        "MEDIA_UPLOADS_ENABLED": "true",
        "BACKEND_DEBUG": "true",
    }
    env_path = "/root/.mirage/env/backend.env"
    for key, value in settings.items():
        run(
            [
                "bash",
                "-lc",
                f"docker exec mirage sh -c '"
                f'if grep -q "^{key}=" {env_path}; then '
                f'sed -i "s|^{key}=.*|{key}={value}|" {env_path}; '
                f'else echo "{key}={value}" >> {env_path}; fi\'',
            ]
        )


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
    parser.add_argument(
        "--easy-difficulty",
        action="store_true",
        help="Set pow_message_limit to 9999999 so difficulty never increases",
    )
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

    # Step 4: Stop old container, start prep container (entrypoint disabled for file setup)
    stop_local_container()
    ensure_local_container(image_ref)

    # Step 5: Stage backup files into container (config, keyring, env, indexer dump)
    export_path = stage_backup_into_container(backup_root, export_path)
    status("Cleaning up extracted backup files...")
    shutil.rmtree(extract_dir, ignore_errors=True)

    # Step 6: Transform genesis to single-validator
    cons_pub_b64 = read_priv_validator_pubkey_b64()
    new_genesis, val_addr, valoper, valcons_addr = transform_to_single_validator(
        export_path, cons_pub_b64, easy_difficulty=args.easy_difficulty
    )

    # Step 7: Prepare node directory (genesis, identity files, fresh data, postgres, indexer)
    prepare_local_node(new_genesis)

    # Clean up temp files
    if export_path.exists():
        export_path.unlink()
    for item in MIRAGE_TMP.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)

    # Clean up staging directory in container
    run(
        [
            "bash",
            "-lc",
            "docker exec mirage bash -lc 'rm -rf /root/.mirage/node/.mirage /root/.mirage/node.clone 2>/dev/null || true'",
        ]
    )

    # Step 7.5: Local-only backend.env wiring, before the backend first starts
    configure_local_backend_env()

    # Step 8: Start container with normal entrypoint (handles ALL service orchestration)
    start_with_entrypoint(image_ref)

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
