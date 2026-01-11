#!/usr/bin/env python3
"""
Sync env files with latest templates.

This script runs on every deploy to:
1. Use latest .env templates from deploy/templates/
2. Preserve existing user values for keys that still exist
3. Remove deprecated keys that are no longer in templates
4. Add new keys with default values from templates

Usage:
    python3 deploy/sync_env_files.py [--config-dir PATH]
"""

import argparse
import logging
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Files to sync (template name -> config name)
ENV_FILES = [
    "backend.env",
    "frontend.env",
    "indexer.env",
    "node.env",
    "secrets.env",
]


def parse_env_file(path: Path) -> Tuple[Dict[str, str], list]:
    """
    Parse an env file into values dict and original lines (for structure).
    Returns (values_dict, lines_list)
    """
    values = {}
    lines = []
    
    if not path.exists():
        return values, lines
    
    with open(path, "r") as f:
        for line in f:
            lines.append(line)
            stripped = line.strip()
            
            if not stripped or stripped.startswith("#"):
                continue
            
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove quotes if present
                if value and value[0] in ('"', "'") and value[-1] == value[0]:
                    value = value[1:-1]
                values[key] = value
    
    return values, lines


def sync_env_file(template_path: Path, config_path: Path, logger) -> dict:
    """
    Sync a config file with its template.
    
    Returns dict with stats: {added: [], removed: [], preserved: int}
    """
    stats = {"added": [], "removed": [], "preserved": 0}
    
    # Parse template to get expected keys and structure
    template_values, template_lines = parse_env_file(template_path)
    
    # Parse existing config to get user values
    existing_values, _ = parse_env_file(config_path)
    
    # Build new file: template structure + user values
    new_lines = []
    seen_keys = set()
    
    for line in template_lines:
        stripped = line.strip()
        
        # Keep comments and empty lines as-is
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        
        # Handle key=value lines
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            seen_keys.add(key)
            
            if key in existing_values:
                # Preserve user's value
                new_lines.append(f"{key}={existing_values[key]}\n")
                stats["preserved"] += 1
            else:
                # Use template default (new key)
                new_lines.append(line)
                stats["added"].append(key)
        else:
            new_lines.append(line)
    
    # Find removed keys (in existing but not in template)
    for key in existing_values:
        if key not in seen_keys:
            stats["removed"].append(key)
    
    # Write the synced file
    with open(config_path, "w") as f:
        f.writelines(new_lines)
    
    return stats


def sync_all(templates_dir: Path, config_dir: Path) -> dict:
    """
    Sync all env files.
    
    Returns overall stats.
    """
    overall = {"synced": 0, "created": 0, "added": [], "removed": []}
    
    # Create backup before making changes
    backup_dir = config_dir / "backups"
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    for env_file in ENV_FILES:
        template_path = templates_dir / env_file
        config_path = config_dir / env_file
        
        if not template_path.exists():
            logger.debug(f"Template not found: {env_file}")
            continue
        
        # Backup existing file
        if config_path.exists():
            backup_path = backup_dir / f"{env_file}.{timestamp}.bak"
            shutil.copy2(config_path, backup_path)
        
        if not config_path.exists():
            # New file - just copy template
            shutil.copy2(template_path, config_path)
            logger.info(f"  Created {env_file} from template")
            overall["created"] += 1
        else:
            # Sync existing file with template
            stats = sync_env_file(template_path, config_path, logger)
            
            if stats["added"] or stats["removed"]:
                logger.info(f"  Synced {env_file}: +{len(stats['added'])} new, -{len(stats['removed'])} removed, {stats['preserved']} preserved")
                if stats["added"]:
                    logger.info(f"    Added: {stats['added']}")
                if stats["removed"]:
                    logger.info(f"    Removed: {stats['removed']}")
                overall["added"].extend(stats["added"])
                overall["removed"].extend(stats["removed"])
            else:
                logger.debug(f"  {env_file}: no changes ({stats['preserved']} keys)")
            
            overall["synced"] += 1
    
    # Clean up old .env.example files
    for example_file in config_dir.glob("*.env.example"):
        example_file.unlink()
        logger.info(f"  Deleted deprecated {example_file.name}")
    
    return overall


def main():
    parser = argparse.ArgumentParser(description="Sync env files with latest templates")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path.home() / ".mirage" / "config",
        help="Config directory (default: ~/.mirage/config)",
    )
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=None,
        help="Templates directory (default: auto-detect from script location)",
    )
    args = parser.parse_args()
    
    # Auto-detect templates directory
    if args.templates_dir:
        templates_dir = args.templates_dir
    else:
        templates_dir = Path(__file__).parent / "templates"
    
    if not templates_dir.exists():
        logger.error(f"Templates directory not found: {templates_dir}")
        return 1
    
    if not args.config_dir.exists():
        logger.info(f"Config directory does not exist, creating: {args.config_dir}")
        args.config_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Syncing env files...")
    logger.info(f"  Templates: {templates_dir}")
    logger.info(f"  Config: {args.config_dir}")
    
    stats = sync_all(templates_dir, args.config_dir)
    
    if stats["created"] or stats["added"] or stats["removed"]:
        logger.info(f"Sync complete: {stats['created']} created, {stats['synced']} synced, +{len(stats['added'])} new keys, -{len(stats['removed'])} removed keys")
    else:
        logger.info("Sync complete: all files up to date")
    
    return 0


if __name__ == "__main__":
    exit(main())
