"""
One-time migration: generate a stable CLIENT_HASH_SALT for referral gating.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from deploy.migrations._helpers import parse_env_file, update_env_value, append_env_value

MIGRATION_KEY = "v1.21.11-client-hash-salt"
DESCRIPTION = "Generate CLIENT_HASH_SALT for referral client-hash gate"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    env_path = config_dir / "backend.env"
    if not env_path.exists():
        raise RuntimeError("backend.env missing; cannot set CLIENT_HASH_SALT")

    values = parse_env_file(env_path)
    existing = values.get("CLIENT_HASH_SALT", "").strip()
    if existing:
        return "CLIENT_HASH_SALT already set"

    salt = secrets.token_hex(32)
    if update_env_value(env_path, "CLIENT_HASH_SALT", salt):
        logger.info("Set CLIENT_HASH_SALT in backend.env")
        return "CLIENT_HASH_SALT set"

    if append_env_value(env_path, "CLIENT_HASH_SALT", salt, comment="Salt for client hash gating"):
        logger.info("Appended CLIENT_HASH_SALT in backend.env")
        return "CLIENT_HASH_SALT appended"

    raise RuntimeError("failed to set CLIENT_HASH_SALT")
