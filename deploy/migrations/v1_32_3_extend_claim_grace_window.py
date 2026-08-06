"""
Move LEGACY_UNSIGNED_UNTIL off the original 2026-09-05 claim grace deadline.

The window shipped in v1.33.0 only covered claims that carried no signature at
all, so every installed mobile build — which sends an identity block signed
under an older scheme — got a hard 401 on /api/rewards/claim for the whole first
month of it. The handler now treats an unverifiable proof like a missing one, and
the deadline moves out to give clients a real month of overlap.

Existing nodes pin the old date in backend.env, which overrides the code default,
so changing settings.py alone would be inert on every deployed node. Idempotent:
only rewrites the value when it is still the original deadline.
"""

from __future__ import annotations

from pathlib import Path

from deploy.migrations._helpers import append_env_value, backup_file, parse_env_file, update_env_value

MIGRATION_KEY = "v1.32.3-extend-claim-grace-window"
DESCRIPTION = "Move LEGACY_UNSIGNED_UNTIL from 2026-09-05 to 2026-10-05 in backend.env"

OLD_DEADLINE = "2026-09-05"
NEW_DEADLINE = "2026-10-05"


def run(config_dir, logger):
    env_path = Path(config_dir) / "backend.env"
    if not env_path.exists():
        raise RuntimeError("backend.env missing; cannot set LEGACY_UNSIGNED_UNTIL")

    current = parse_env_file(env_path).get("LEGACY_UNSIGNED_UNTIL", "").strip()
    if current == NEW_DEADLINE:
        return f"LEGACY_UNSIGNED_UNTIL already {NEW_DEADLINE}"
    if current and current != OLD_DEADLINE:
        # An operator picked a deadline deliberately; do not overwrite it.
        logger.info(f"  LEGACY_UNSIGNED_UNTIL={current!r} is operator-set; leaving alone")
        return f"LEGACY_UNSIGNED_UNTIL left at operator value {current}"

    backup_file(env_path)

    if not current:
        if not append_env_value(
            env_path,
            "LEGACY_UNSIGNED_UNTIL",
            NEW_DEADLINE,
            comment="Grace period for /api/rewards/claim proofs (YYYY-MM-DD UTC)",
        ):
            raise RuntimeError("failed to append LEGACY_UNSIGNED_UNTIL")
        logger.info(f"  Appended LEGACY_UNSIGNED_UNTIL={NEW_DEADLINE}")
        return f"LEGACY_UNSIGNED_UNTIL appended as {NEW_DEADLINE}"

    if not update_env_value(env_path, "LEGACY_UNSIGNED_UNTIL", NEW_DEADLINE):
        raise RuntimeError("failed to update LEGACY_UNSIGNED_UNTIL")

    logger.info(f"  LEGACY_UNSIGNED_UNTIL {OLD_DEADLINE} -> {NEW_DEADLINE}")
    return f"LEGACY_UNSIGNED_UNTIL {OLD_DEADLINE} -> {NEW_DEADLINE}"
