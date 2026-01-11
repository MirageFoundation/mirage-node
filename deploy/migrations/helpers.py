"""
Helper functions for deploy migrations.

Common utilities used by migration scripts and env file sync.
"""

import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

# Files to sync with templates
ENV_FILES = [
    "backend.env",
    "frontend.env",
    "indexer.env",
    "node.env",
    "secrets.env",
]


def parse_env_file(path: Path) -> Dict[str, str]:
    """
    Parse an env file into a dict of key=value pairs.
    Ignores comments and empty lines.
    """
    values = {}
    if not path.exists():
        return values

    with open(path, "r") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove quotes if present
                if value and value[0] in ('"', "'") and len(value) > 1 and value[-1] == value[0]:
                    value = value[1:-1]
                values[key] = value
    return values


def parse_env_with_lines(path: Path) -> Tuple[Dict[str, str], List[str]]:
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
                if value and value[0] in ('"', "'") and len(value) > 1 and value[-1] == value[0]:
                    value = value[1:-1]
                values[key] = value

    return values, lines


def update_env_value(path: Path, key: str, value: str) -> bool:
    """
    Update a key's value in an env file.
    Returns True if the key was found and updated.
    """
    if not path.exists():
        return False

    content = path.read_text()
    pattern = rf"^{re.escape(key)}=.*$"
    new_line = f"{key}={value}"

    new_content, count = re.subn(pattern, new_line, content, flags=re.MULTILINE)
    if count > 0:
        path.write_text(new_content)
        return True
    return False


def append_env_value(path: Path, key: str, value: str, comment: str = None) -> bool:
    """
    Append a key=value to an env file if it doesn't exist.
    Returns True if appended, False if key already exists.
    """
    if not path.exists():
        return False

    existing = parse_env_file(path)
    if key in existing:
        return False

    with open(path, "a") as f:
        if comment:
            f.write(f"\n# {comment}\n")
        f.write(f"{key}={value}\n")
    return True


def remove_keys_from_file(path: Path, keys: List[str], logger=None) -> int:
    """
    Remove specified keys from an env file, preserving structure.
    Also removes comments that appear to be about the removed key.
    Returns number of keys removed.
    """
    if not path.exists():
        return 0

    removed = 0
    new_lines = []

    with open(path, "r") as f:
        lines = f.readlines()

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Check if this line is a key we should remove
        should_remove = False
        for key in keys:
            if stripped.startswith(f"{key}="):
                should_remove = True
                removed += 1
                # Also remove preceding comment if it mentions this key
                if new_lines and new_lines[-1].strip().startswith("#"):
                    comment_lower = new_lines[-1].lower()
                    key_words = key.lower().replace("_", " ").split()
                    if any(word in comment_lower for word in key_words):
                        new_lines.pop()
                break

        if not should_remove:
            new_lines.append(line)

    with open(path, "w") as f:
        f.writelines(new_lines)

    return removed


def backup_file(path: Path, backup_dir: Path = None) -> Path:
    """
    Create a timestamped backup of a file.
    Returns the backup path.
    """
    if not path.exists():
        return None

    if backup_dir is None:
        backup_dir = path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{path.name}.{timestamp}.bak"
    shutil.copy2(path, backup_path)
    return backup_path


def backup_env_files(config_dir: Path, logger=None) -> Path:
    """
    Backup all env files in the config directory.
    Returns the backup directory.
    """
    backup_dir = config_dir / "backups"
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for env_file in ENV_FILES:
        src = config_dir / env_file
        if src.exists():
            dst = backup_dir / f"{env_file}.{timestamp}.bak"
            shutil.copy2(src, dst)

    if logger:
        logger.info(f"  Created backups in {backup_dir}")

    return backup_dir


def delete_legacy_files(config_dir: Path, patterns: List[str], logger=None) -> int:
    """
    Delete files matching patterns in config directory.
    Returns number of files deleted.
    """
    deleted = 0
    for pattern in patterns:
        for f in config_dir.glob(pattern):
            f.unlink()
            deleted += 1
            if logger:
                logger.info(f"  Deleted {f.name}")
    return deleted


# ============================================================================
# Env File Sync (runs every deploy)
# ============================================================================


def sync_env_file(template_path: Path, config_path: Path, logger=None) -> dict:
    """
    Sync a config file with its template.

    Returns dict with stats: {added: [], removed: [], preserved: int}
    """
    stats = {"added": [], "removed": [], "preserved": 0}

    # Parse template to get expected keys and structure
    template_values, template_lines = parse_env_with_lines(template_path)

    # Parse existing config to get user values
    existing_values, _ = parse_env_with_lines(config_path)

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

            if key in existing_values and existing_values[key]:
                # Preserve user's non-empty value
                new_lines.append(f"{key}={existing_values[key]}\n")
                stats["preserved"] += 1
            else:
                # Use template default (new key or empty existing value)
                new_lines.append(line)
                if key not in existing_values:
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


def sync_all(templates_dir: Path, config_dir: Path, logger=None) -> dict:
    """
    Sync all env files with templates.

    Returns overall stats.
    """
    import logging

    if logger is None:
        logger = logging.getLogger(__name__)

    overall = {"synced": 0, "created": 0, "added": [], "removed": []}

    # Create backup before making changes
    backup_env_files(config_dir, logger)

    for env_file in ENV_FILES:
        template_path = templates_dir / env_file
        config_path = config_dir / env_file

        if not template_path.exists():
            logger.debug(f"Template not found: {env_file}")
            continue

        if not config_path.exists():
            # New file - just copy template
            shutil.copy2(template_path, config_path)
            logger.info(f"  Created {env_file} from template")
            overall["created"] += 1
        else:
            # Sync existing file with template
            stats = sync_env_file(template_path, config_path, logger)

            if stats["added"] or stats["removed"]:
                logger.info(
                    f"  Synced {env_file}: +{len(stats['added'])} new, "
                    f"-{len(stats['removed'])} removed, {stats['preserved']} preserved"
                )
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
    delete_legacy_files(config_dir, ["*.env.example"], logger)

    return overall
