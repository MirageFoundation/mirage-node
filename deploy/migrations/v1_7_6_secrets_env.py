"""
Migration: Move secrets to secrets.env

This migration:
1. Moves sensitive credentials from node.env/backend.env to secrets.env
2. Removes secret keys from source files
3. Preserves ALL existing user values

IMPORTANT: This migration does NOT overwrite user values with templates.
It only moves secrets and creates secrets.env if missing.
"""

import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List

MIGRATION_KEY = "v1.7.6_secrets_env"
DESCRIPTION = "Move secrets to dedicated secrets.env file"

# Secret keys that should be moved to secrets.env
SECRET_KEYS = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_HASH",
    "CLOUDFLARE_STREAM_CUSTOMER_CODE",
    "OPENAI_API_KEY",
]


def parse_env_file(path: Path) -> Dict[str, str]:
    """Parse an env file into a dict of key=value pairs."""
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
                key = key.strip()
                value = value.strip()
                if value and value[0] in ('"', "'") and value[-1] == value[0]:
                    value = value[1:-1]
                env[key] = value
    return env


def remove_keys_from_file(path: Path, keys: List[str], logger) -> int:
    """Remove specified keys from an env file, preserving structure."""
    if not path.exists():
        return 0

    removed = 0
    new_lines = []

    with open(path, "r") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i]
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
        i += 1

    # Write back
    with open(path, "w") as f:
        f.writelines(new_lines)

    return removed


def update_env_file(path: Path, values: Dict[str, str]) -> int:
    """Update or append values in an env file."""
    if not path.exists() or not values:
        return 0

    updated = 0
    lines = []
    found_keys = set()

    with open(path, "r") as f:
        for line in f:
            stripped = line.strip()

            # Check if this is a key=value line we should update
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                if key in values:
                    found_keys.add(key)
                    # Always update with existing value (even if it overwrites template default)
                    lines.append(f"{key}={values[key]}\n")
                    updated += 1
                    continue

            lines.append(line)

    # Append any values that weren't found in the file
    for key, value in values.items():
        if key not in found_keys and value:
            lines.append(f"{key}={value}\n")
            updated += 1

    with open(path, "w") as f:
        f.writelines(lines)

    return updated


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    templates_dir = Path(__file__).parent.parent / "templates"

    # Step 1: Read ALL existing values from all env files
    all_values = {}
    for env_file in ["backend.env", "frontend.env", "indexer.env", "node.env", "secrets.env"]:
        env_path = config_dir / env_file
        if env_path.exists():
            values = parse_env_file(env_path)
            all_values.update(values)
            logger.info(f"  Read {len(values)} values from {env_file}")

    # Step 2: Extract secret values
    secret_values = {k: all_values[k] for k in SECRET_KEYS if k in all_values and all_values[k]}

    logger.info(f"  Total values found: {len(all_values)}")
    logger.info(f"  Secrets to migrate: {len(secret_values)}")
    if secret_values:
        logger.info(f"  Secret keys: {list(secret_values.keys())}")

    # Step 3: Backup existing files
    backup_dir = config_dir / "backups"
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for env_file in ["backend.env", "frontend.env", "indexer.env", "node.env", "secrets.env"]:
        src = config_dir / env_file
        if src.exists():
            dst = backup_dir / f"{env_file}.{timestamp}.bak"
            shutil.copy2(src, dst)
    logger.info(f"  Created backups in {backup_dir}")

    # Step 4: Create secrets.env from template if it doesn't exist
    secrets_path = config_dir / "secrets.env"
    secrets_template = templates_dir / "secrets.env"
    if not secrets_path.exists() and secrets_template.exists():
        shutil.copy2(secrets_template, secrets_path)
        logger.info("  Created secrets.env from template")

    # Step 5: Update secrets.env with secret values
    if secret_values:
        update_env_file(secrets_path, secret_values)
        logger.info(f"  Added {len(secret_values)} secrets to secrets.env")

    # Step 6: Remove secret keys from source files (they're now in secrets.env)
    for env_file in ["backend.env", "node.env"]:
        env_path = config_dir / env_file
        if env_path.exists():
            removed = remove_keys_from_file(env_path, SECRET_KEYS, logger)
            if removed:
                logger.info(f"  Removed {removed} secret keys from {env_file}")

    # Step 7: Delete old .env.example files
    deleted = 0
    for example_file in config_dir.glob("*.env.example"):
        example_file.unlink()
        deleted += 1
    if deleted:
        logger.info(f"  Deleted {deleted} old .env.example files")

    return f"migrated {len(secret_values)} secrets, deleted {deleted} example files"
