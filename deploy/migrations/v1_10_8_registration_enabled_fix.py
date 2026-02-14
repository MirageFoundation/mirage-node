"""
Migration: v1.10.8 - Fix REGISTRATION_ENABLED on mirage.talk

The v1_10_8_registration_defaults migration used update_env_value() which
only updates existing keys. REGISTRATION_ENABLED was a NEW key that didn't
exist in older backend.env files, so it was never set. The env sync then
added it from the template with the default value "false".

This fixup re-applies the correct value for mirage.talk.
"""

from pathlib import Path

from deploy.migrations._helpers import append_env_value, parse_env_file, update_env_value

MIGRATION_KEY = "v1_10_8_registration_enabled_fix"
DESCRIPTION = "Fix REGISTRATION_ENABLED=false on mirage.talk (was skipped by original migration)"

REGISTRATION_DOMAIN = "mirage.talk"


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"
    node_env = config_dir / "node.env"

    if not backend_env.exists():
        logger.info("    backend.env not found, skipping")
        return "skipped (no backend.env)"

    # Read domain from node.env
    domain = ""
    if node_env.exists():
        node_values = parse_env_file(node_env)
        domain = node_values.get("DOMAIN", "").strip().lower()

    if domain != REGISTRATION_DOMAIN:
        logger.info(f"    Domain is {domain or '(no domain)'} — not {REGISTRATION_DOMAIN}, skipping")
        return "skipped (not registration domain)"

    # Check current value
    current = parse_env_file(backend_env)
    if current.get("REGISTRATION_ENABLED") == "true":
        logger.info("    REGISTRATION_ENABLED already true")
        return "no changes needed"

    # Fix: set REGISTRATION_ENABLED=true
    if not update_env_value(backend_env, "REGISTRATION_ENABLED", "true"):
        append_env_value(backend_env, "REGISTRATION_ENABLED", "true")

    logger.info("    Fixed REGISTRATION_ENABLED=true")
    return "set: REGISTRATION_ENABLED=true"
