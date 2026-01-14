"""
Migration: v1.8.3 - Update Caddyfile with new /chain/rpc and /chain/rest paths

This migration re-renders the Caddyfile from the template to add:
- /chain/rpc (new path for CometBFT RPC)
- /chain/rest (new path for Cosmos REST API)
- Backwards compatibility for /rpc and /lcd (deprecated 2026-02-20)
"""

import os
import re
import subprocess
from pathlib import Path

MIGRATION_KEY = "v1_8_3_caddy_chain_paths"


def run(config_dir: Path, logger) -> str:
    caddyfile = Path("/etc/caddy/Caddyfile")
    template = Path("/opt/mirage/deploy/templates/caddy/Caddyfile")
    render_script = Path("/opt/mirage/deploy/render_template.py")

    if not template.exists():
        logger.info("    Caddyfile template not found, skipping")
        return "template not found"

    if not render_script.exists():
        logger.info("    render_template.py not found, skipping")
        return "render script not found"

    # Check if migration is needed - look for /chain/rpc in existing Caddyfile
    if caddyfile.exists():
        content = caddyfile.read_text()
        if "/chain/rpc" in content and "/chain/rest" in content:
            logger.info("    Caddyfile already has /chain/rpc and /chain/rest paths")
            return "already up to date"

    # Backup existing Caddyfile
    if caddyfile.exists():
        backup = caddyfile.with_suffix(".bak")
        caddyfile.rename(backup)
        logger.info(f"    Backed up existing Caddyfile to {backup}")

    # Re-render from template
    try:
        result = subprocess.run(
            ["python3", str(render_script), str(template), str(caddyfile)],
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("    Re-rendered Caddyfile from template")
    except subprocess.CalledProcessError as e:
        logger.error(f"    Failed to render Caddyfile: {e.stderr}")
        # Restore backup
        if backup.exists():
            backup.rename(caddyfile)
        return f"render failed: {e.stderr[:50]}"

    # Verify new paths exist
    if caddyfile.exists():
        content = caddyfile.read_text()
        if "/chain/rpc" not in content:
            logger.error("    Rendered Caddyfile missing /chain/rpc")
            return "missing /chain/rpc after render"

    # Reload Caddy
    try:
        subprocess.run(
            ["caddy", "reload", "--config", str(caddyfile)],
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("    Reloaded Caddy with new config")
    except subprocess.CalledProcessError as e:
        logger.warning(f"    Failed to reload Caddy (may need manual restart): {e.stderr}")
        return "rendered, reload failed"

    return "updated and reloaded"
