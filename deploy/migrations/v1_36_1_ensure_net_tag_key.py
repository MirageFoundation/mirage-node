"""
Ensure NET_TAG_HMAC_KEY is set before the backend fails hard on import.

Generates a fresh per-node secret, which is the correct end state for an
independent operator: their node is its own trust domain and needs no
coordination with anyone. Officially operated frontends additionally run
scripts/set_net_tag_key.py to overwrite all of them with one shared value, so a
tag matches whichever frontend a user happens to hit.

Idempotent: an existing value is validated and left alone, so re-running never
rotates a key and silently breaks tag continuity mid-epoch.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from deploy.migrations._helpers import parse_env_file, update_env_value, append_env_value

MIGRATION_KEY = "v1.36.1-ensure-net-tag-key"
DESCRIPTION = "Ensure NET_TAG_HMAC_KEY is present in backend.env (fail-hard prerequisite)"

MIN_KEY_BYTES = 32


def run(config_dir, logger):
    config_dir = Path(config_dir)
    env_path = config_dir / "backend.env"
    if not env_path.exists():
        raise RuntimeError("backend.env missing; cannot set NET_TAG_HMAC_KEY")

    values = parse_env_file(env_path)
    existing = values.get("NET_TAG_HMAC_KEY", "").strip()
    if existing:
        try:
            raw = bytes.fromhex(existing)
        except ValueError as e:
            raise RuntimeError(f"NET_TAG_HMAC_KEY present but not valid hex: {e}") from e
        if len(raw) < MIN_KEY_BYTES:
            raise RuntimeError(
                f"NET_TAG_HMAC_KEY present but only {len(raw)} bytes; need at least {MIN_KEY_BYTES}"
            )
        return "NET_TAG_HMAC_KEY already set"

    key = secrets.token_hex(MIN_KEY_BYTES)
    if update_env_value(env_path, "NET_TAG_HMAC_KEY", key):
        logger.info("Set NET_TAG_HMAC_KEY in backend.env")
        return "NET_TAG_HMAC_KEY set"

    if append_env_value(
        env_path,
        "NET_TAG_HMAC_KEY",
        key,
        comment="Secret for epoch-scoped network tags (trust-domain scoped)",
    ):
        logger.info("Appended NET_TAG_HMAC_KEY in backend.env")
        return "NET_TAG_HMAC_KEY appended"

    raise RuntimeError("failed to set NET_TAG_HMAC_KEY")
