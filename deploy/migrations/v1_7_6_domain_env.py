"""
Migration: Move domain from .domain file to node.env

Also updates MONIKER if it's the default 'mirage-node'.
"""

from pathlib import Path

from deploy.migrations.helpers import parse_env_file, update_env_value

MIGRATION_KEY = "v1.7.6_domain_env"
DESCRIPTION = "Move domain from .domain file to node.env"


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    data_dir = config_dir.parent  # ~/.mirage
    domain_file = data_dir / ".domain"
    node_env = config_dir / "node.env"

    results = []

    # Read existing values
    existing = parse_env_file(node_env)

    # Read domain from legacy file
    domain = ""
    if domain_file.exists():
        domain = domain_file.read_text().strip()

    # Set DOMAIN if not already set
    if not existing.get("DOMAIN") and domain:
        if node_env.exists():
            with open(node_env, "a") as f:
                f.write(f"\nDOMAIN={domain}\n")
        logger.info(f"  Set DOMAIN={domain}")
        results.append(f"DOMAIN={domain}")

    # Update MONIKER if it's the default 'mirage-node' and we have a domain
    if domain and existing.get("MONIKER") == "mirage-node":
        if update_env_value(node_env, "MONIKER", domain):
            logger.info(f"  Updated MONIKER={domain}")
            results.append(f"MONIKER={domain}")

    # Remove legacy .domain file
    if domain_file.exists():
        domain_file.unlink()
        results.append("deleted .domain")

    if results:
        return ", ".join(results)
    return "no changes needed"
