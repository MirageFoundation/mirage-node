"""
Ensure CLIENT_HASH_SALT is set before the backend fails hard on import.

v1.21.11 already generated the salt on nodes that ran that migration. Nodes
that skipped it (or wiped backend.env) would crash on restart once client_ip
stopped inventing a per-process salt. Idempotent: leaves an existing value alone.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from deploy.migrations._helpers import parse_env_file, update_env_value, append_env_value

MIGRATION_KEY = "v1.32.0-ensure-client-hash-salt"
DESCRIPTION = "Ensure CLIENT_HASH_SALT is present in backend.env (fail-hard prerequisite)"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    env_path = config_dir / "backend.env"
    if not env_path.exists():
        raise RuntimeError("backend.env missing; cannot set CLIENT_HASH_SALT")

    values = parse_env_file(env_path)
    existing = values.get("CLIENT_HASH_SALT", "").strip()
    if existing:
        try:
            bytes.fromhex(existing)
        except ValueError as e:
            raise RuntimeError(f"CLIENT_HASH_SALT present but not valid hex: {e}") from e
        return "CLIENT_HASH_SALT already set"

    salt = secrets.token_hex(32)
    if update_env_value(env_path, "CLIENT_HASH_SALT", salt):
        logger.info("Set CLIENT_HASH_SALT in backend.env")
        return "CLIENT_HASH_SALT set"

    if append_env_value(env_path, "CLIENT_HASH_SALT", salt, comment="Salt for client/visitor hashing"):
        logger.info("Appended CLIENT_HASH_SALT in backend.env")
        return "CLIENT_HASH_SALT appended"

    raise RuntimeError("failed to set CLIENT_HASH_SALT")
