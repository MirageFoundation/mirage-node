"""
Turn the quest, payout and achievement flags off before the v1.39.0 backend starts.

v1.39.0 replaces the quest board with the on-chain creator pool and drops the
quest, achievement, invite and pending-reward tables. The backend now refuses to
start with any of those flags true, because every tracking write would run
against a table that no longer exists. A node upgrading from v1.38.x still has
`true` on disk, so the values have to be rewritten here — the env sync only adds
missing keys and would leave an operator's `true` in place.

Idempotent: a node already on false is left untouched.
"""

from __future__ import annotations

from pathlib import Path

from deploy.migrations._helpers import backup_file, parse_env_file, update_env_value

MIGRATION_KEY = "v1.39.0-disable-quests"
DESCRIPTION = "Set QUESTS_ENABLED, QUESTS_PAYOUTS_ENABLED and ACHIEVEMENTS_ENABLED to false"

RETIRED_FLAGS = ("QUESTS_ENABLED", "QUESTS_PAYOUTS_ENABLED", "ACHIEVEMENTS_ENABLED")


def run(config_dir, logger):
    backend_env = Path(config_dir) / "backend.env"
    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")

    existing = parse_env_file(backend_env)
    stale = [key for key in RETIRED_FLAGS if existing.get(key, "false").strip().lower() != "false"]
    if not stale:
        return "quests, payouts and achievements already disabled"

    backup_file(backend_env)
    for key in stale:
        if not update_env_value(backend_env, key, "false"):
            raise RuntimeError(f"failed to set {key}=false in backend.env")
        logger.info(f"  {key}={existing.get(key)!r} -> false")

    return "disabled " + ", ".join(stale)
