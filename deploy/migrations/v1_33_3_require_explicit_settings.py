"""
Write out the settings the backend now refuses to guess.

`ACHIEVEMENTS_ENABLED` is new: the action-side quest tracker used to read a
hardcoded module where achievements were always on, so a node with quests
disabled still accrued achievement state. `MEDIA_UPLOADS_ENABLED`,
`INDEXER_ENABLED` and `LEGACY_UNSIGNED_UNTIL` already existed but had soft
code defaults; the code now fails hard when they are absent, so every existing
node needs the value written down before it restarts on the new build.

Idempotent, and never overwrites a value an operator already chose. Missing
media policy fails closed; an operator must explicitly enable uploads only
after putting a scanning edge in front of the node.
"""

from __future__ import annotations

from pathlib import Path

from deploy.migrations._helpers import append_env_value, backup_file, parse_env_file, update_env_value

MIGRATION_KEY = "v1.33.3-require-explicit-settings"
DESCRIPTION = (
    "Write ACHIEVEMENTS_ENABLED, MEDIA_UPLOADS_ENABLED, LEGACY_UNSIGNED_UNTIL and "
    "INDEXER_ENABLED explicitly so the backend can fail hard on missing settings"
)

CLAIM_GRACE_DEADLINE = "2026-10-05"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"
    indexer_env = config_dir / "indexer.env"

    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")
    if not indexer_env.exists():
        raise FileNotFoundError(f"indexer.env not found: {indexer_env}")

    backend_defaults = [
        (
            "ACHIEVEMENTS_ENABLED",
            "false",
            "Achievements - set to true to track achievement unlocks on user actions",
        ),
        (
            "MEDIA_UPLOADS_ENABLED",
            "false",
            "Public media uploads. Only true where a scanning edge (Bunny Shield) fronts uploads.",
        ),
        (
            "LEGACY_UNSIGNED_UNTIL",
            CLAIM_GRACE_DEADLINE,
            "Grace period for /api/rewards/claim proofs (YYYY-MM-DD UTC)",
        ),
    ]

    changes = []
    existing = parse_env_file(backend_env)
    if any(key not in existing for key, _, _ in backend_defaults):
        backup_file(backend_env)

    for key, value, comment in backend_defaults:
        if key in existing:
            logger.info(f"  {key} already set to {existing[key]!r}")
            continue
        if not append_env_value(backend_env, key, value, comment=comment):
            raise RuntimeError(f"failed to append {key} to backend.env")
        logger.info(f"  Appended {key}={value}")
        changes.append(f"{key}={value}")

    indexer_existing = parse_env_file(indexer_env)
    indexer_enabled = indexer_existing.get("INDEXER_ENABLED")
    if indexer_enabled is None:
        backup_file(indexer_env)
        if not append_env_value(
            indexer_env,
            "INDEXER_ENABLED",
            "true",
            comment="Enable or disable the blockchain indexer service (true/false)",
        ):
            raise RuntimeError("failed to append INDEXER_ENABLED to indexer.env")
        logger.info("  Appended INDEXER_ENABLED=true")
        changes.append("INDEXER_ENABLED=true")
    else:
        normalized = indexer_enabled.strip().lower()
        legacy_values = {
            "1": "true",
            "yes": "true",
            "0": "false",
            "no": "false",
        }
        canonical = legacy_values.get(normalized, normalized)
        if canonical not in ("true", "false"):
            raise RuntimeError(
                "INDEXER_ENABLED must be true or false before upgrading, "
                f"got {indexer_enabled!r}"
            )
        if indexer_enabled != canonical:
            backup_file(indexer_env)
            if not update_env_value(indexer_env, "INDEXER_ENABLED", canonical):
                raise RuntimeError("failed to normalize INDEXER_ENABLED in indexer.env")
            logger.info(f"  Normalized INDEXER_ENABLED={indexer_enabled!r} to {canonical}")
            changes.append(f"INDEXER_ENABLED={canonical}")
        else:
            logger.info(f"  INDEXER_ENABLED already set to {canonical!r}")

    if not changes:
        return "all required settings already explicit"
    return "wrote " + ", ".join(changes)
