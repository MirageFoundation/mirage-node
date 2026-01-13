"""
Migration: v1.8.1-hermes-config - Regenerate Hermes config from template

Regenerates the Hermes config.toml from the template to fix:
1. gas_price for mirage-1 chain (v1.8.0 economics: 5000 umirage/gas)
2. Duplicate key_store_folder lines (v1.7.6 migration bug)

This fixes IBC relay failures after the v1.8.0 economics update.
"""

import os
import re
from pathlib import Path

MIGRATION_KEY = "v1.8.1-hermes-config"
DESCRIPTION = "Regenerate Hermes config from template"

# Template variable pattern (from render_template.py)
TEMPLATE_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _render_template(text: str) -> str:
    """Render template variables from environment."""
    def repl(m: re.Match) -> str:
        key = m.group(1)
        default = m.group(2)
        value = os.environ.get(key, "")
        if not value and default is not None:
            return default
        return value
    return TEMPLATE_PATTERN.sub(repl, text)


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    data_dir = config_dir.parent  # ~/.mirage
    hermes_dir = data_dir / "hermes"
    hermes_config = hermes_dir / "config.toml"

    # Only proceed if this is a relayer node (has hermes directory with keys)
    hermes_keys = hermes_dir / "keys"
    if not hermes_keys.exists():
        logger.info("    No Hermes keys found (not a relayer node)")
        return "no changes needed"

    # Find template - works both inside Docker and during local dev
    template_paths = [
        Path("/opt/mirage/deploy/templates/hermes/config.toml"),  # Docker
        Path(__file__).parent.parent / "templates" / "hermes" / "config.toml",  # Local
    ]
    
    template = None
    for p in template_paths:
        if p.exists():
            template = p
            break
    
    if not template:
        logger.warning("    Hermes template not found, skipping")
        return "template not found"

    # Set environment variable for template rendering
    os.environ["HERMES_KEY_STORE_FOLDER"] = str(hermes_keys)

    # Read and render template
    template_content = template.read_text()
    new_content = _render_template(template_content)

    # Check if config needs updating
    if hermes_config.exists():
        old_content = hermes_config.read_text()
        if old_content == new_content:
            logger.info("    Hermes config already matches template")
            return "no changes needed"
        
        # Backup old config
        backup = hermes_config.with_suffix(".toml.bak")
        backup.write_text(old_content)
        logger.info(f"    Backed up old config to {backup.name}")

    # Write new config
    hermes_config.parent.mkdir(parents=True, exist_ok=True)
    hermes_config.write_text(new_content)
    logger.info("    Regenerated Hermes config from template")
    
    return "regenerated hermes config"
