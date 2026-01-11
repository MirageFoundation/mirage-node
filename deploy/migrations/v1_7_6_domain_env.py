"""
Migration: Move domain from .domain file to node.env

This migration:
1. Reads domain from legacy ~/.mirage/.domain file
2. Adds DOMAIN= to node.env if not already set
3. Removes the legacy .domain file
"""

from pathlib import Path

MIGRATION_KEY = "v1.7.6_domain_env"
DESCRIPTION = "Move domain from .domain file to node.env"


def parse_env_file(path: Path) -> dict:
    """Parse an env file into a dict."""
    env = {}
    if not path.exists():
        return env
    
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    # Legacy .domain file location
    data_dir = config_dir.parent  # ~/.mirage
    domain_file = data_dir / ".domain"
    node_env = config_dir / "node.env"
    
    # Check if DOMAIN already set in node.env
    existing = parse_env_file(node_env)
    if existing.get("DOMAIN"):
        # Already migrated or manually set
        if domain_file.exists():
            domain_file.unlink()
            return "DOMAIN already in node.env, deleted legacy .domain file"
        return "DOMAIN already in node.env"
    
    # Read from legacy .domain file
    domain = ""
    if domain_file.exists():
        domain = domain_file.read_text().strip()
    
    if not domain:
        return "no domain to migrate"
    
    # Add DOMAIN to node.env
    if node_env.exists():
        with open(node_env, "a") as f:
            f.write(f"\n# Domain for HTTPS/TLS\nDOMAIN={domain}\n")
    
    # Remove legacy file
    if domain_file.exists():
        domain_file.unlink()
    
    logger.info(f"  Migrated DOMAIN={domain} to node.env")
    return f"migrated domain: {domain}"
