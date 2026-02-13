"""
Migration: v1.11.1 - Set registration defaults per node

Sets registration env vars based on the node's domain:
- mirage.talk: registration ON, invite codes REQUIRED
- All others: registration OFF, invite codes NOT required

This ensures only the primary node accepts new accounts.
"""

from pathlib import Path

from deploy.migrations._helpers import parse_env_file, update_env_value

MIGRATION_KEY = "v1_11_1_registration_defaults"
DESCRIPTION = "Set registration enabled/invite codes per node domain"

# Only this domain gets registration enabled
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

    if domain == REGISTRATION_DOMAIN:
        reg_enabled = "true"
        invite_required = "true"
        logger.info(f"    Domain is {domain} — enabling registration + invite codes")
    else:
        reg_enabled = "false"
        invite_required = "false"
        label = domain or "(no domain)"
        logger.info(f"    Domain is {label} — disabling registration")

    changes = []
    if update_env_value(backend_env, "REGISTRATION_ENABLED", reg_enabled):
        changes.append(f"REGISTRATION_ENABLED={reg_enabled}")
    if update_env_value(backend_env, "REGISTRATION_INVITE_CODE_REQUIRED", invite_required):
        changes.append(f"REGISTRATION_INVITE_CODE_REQUIRED={invite_required}")

    if changes:
        return f"set: {', '.join(changes)}"
    return "no changes needed"
