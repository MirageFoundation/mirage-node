#!/usr/bin/env python3
"""
Migrate .env files to new secrets.env format.

This script migrates sensitive credentials from node.env and backend.env
to a new consolidated secrets.env file.

Moved to secrets.env:
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (from node.env)
- CLOUDFLARE_* (from backend.env)

Usage:
    python scripts/migrate_env_to_secrets.py [--dry-run] [--config-dir PATH]

Options:
    --dry-run       Show what would be done without making changes
    --config-dir    Path to config directory (default: ~/.mirage/config)
"""

import os
import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple


# Keys to migrate from each source file
MIGRATIONS = {
    "node.env": [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ],
    "backend.env": [
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_HASH",
        "CLOUDFLARE_STREAM_CUSTOMER_CODE",
    ],
}

# Template for new secrets.env (only used if file doesn't exist)
SECRETS_TEMPLATE = """# =============================================================================
# SECRETS - API Keys and Tokens (NEVER commit actual values!)
# =============================================================================

# OpenAI / ChatGPT (for AI fraud analysis)
OPENAI_API_KEY=

# Telegram Alerts (for IBC/Hermes monitoring)
TELEGRAM_BOT_TOKEN={TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID={TELEGRAM_CHAT_ID}

# Cloudflare Media Services
CLOUDFLARE_ACCOUNT_ID={CLOUDFLARE_ACCOUNT_ID}
CLOUDFLARE_API_TOKEN={CLOUDFLARE_API_TOKEN}
CLOUDFLARE_ACCOUNT_HASH={CLOUDFLARE_ACCOUNT_HASH}
CLOUDFLARE_STREAM_CUSTOMER_CODE={CLOUDFLARE_STREAM_CUSTOMER_CODE}
"""


def parse_env_file(path: Path) -> Dict[str, str]:
    """Parse an env file into a dict of key=value pairs."""
    env = {}
    if not path.exists():
        return env
    
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            # Parse key=value
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove quotes if present
                if value and value[0] in ('"', "'") and value[-1] == value[0]:
                    value = value[1:-1]
                env[key] = value
    return env


def remove_keys_from_file(path: Path, keys_to_remove: List[str], dry_run: bool) -> List[str]:
    """Remove specified keys from an env file, preserving comments and structure."""
    if not path.exists():
        return []
    
    removed = []
    new_lines = []
    
    with open(path, "r") as f:
        lines = f.readlines()
    
    skip_next_empty = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Check if this line defines a key we want to remove
        should_remove = False
        for key in keys_to_remove:
            if stripped.startswith(f"{key}=") or stripped == key:
                should_remove = True
                removed.append(key)
                break
        
        if should_remove:
            # Also remove preceding comment if it's about this key
            if new_lines and new_lines[-1].strip().startswith("#"):
                comment = new_lines[-1].strip().lower()
                key_lower = key.lower().replace("_", " ")
                # Check if comment is related to this key
                if any(word in comment for word in key_lower.split()):
                    new_lines.pop()
            skip_next_empty = True
        else:
            # Skip empty lines after removed content
            if skip_next_empty and not stripped:
                skip_next_empty = False
            else:
                new_lines.append(line)
                skip_next_empty = False
        
        i += 1
    
    # Clean up trailing whitespace
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()
    if new_lines:
        new_lines.append("\n")
    
    if not dry_run and removed:
        with open(path, "w") as f:
            f.writelines(new_lines)
    
    return removed


def backup_file(path: Path) -> Path:
    """Create a timestamped backup of a file."""
    if not path.exists():
        return None
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_suffix(f".{timestamp}.bak")
    shutil.copy2(path, backup_path)
    return backup_path


def migrate(config_dir: Path, dry_run: bool = False) -> Tuple[bool, List[str]]:
    """
    Perform the migration.
    
    Returns (success, messages) tuple.
    """
    messages = []
    secrets_path = config_dir / "secrets.env"
    
    # Collect all values to migrate
    all_values = {}
    files_to_update = []
    
    for source_file, keys in MIGRATIONS.items():
        source_path = config_dir / source_file
        if not source_path.exists():
            messages.append(f"  ⚠ {source_file} not found, skipping")
            continue
        
        env = parse_env_file(source_path)
        has_keys = False
        
        for key in keys:
            if key in env and env[key]:
                all_values[key] = env[key]
                has_keys = True
                messages.append(f"  ✓ Found {key} in {source_file}")
            else:
                all_values[key] = ""
        
        if has_keys:
            files_to_update.append((source_path, keys))
    
    # Check if there's anything to migrate
    non_empty_values = {k: v for k, v in all_values.items() if v}
    if not non_empty_values:
        messages.append("\n  ℹ No credentials found to migrate")
        return True, messages
    
    # Check if secrets.env already exists with these values
    if secrets_path.exists():
        existing = parse_env_file(secrets_path)
        already_migrated = all(
            key in existing and existing[key] == value
            for key, value in non_empty_values.items()
        )
        if already_migrated:
            messages.append(f"\n  ℹ secrets.env already contains all credentials")
            # Still need to clean up source files
        else:
            messages.append(f"\n  ℹ secrets.env exists, will merge values")
    
    if dry_run:
        messages.append("\n  [DRY RUN] Would perform the following:")
        messages.append(f"    - Create/update {secrets_path}")
        for source_path, keys in files_to_update:
            messages.append(f"    - Remove {keys} from {source_path.name}")
        return True, messages
    
    # Backup files
    messages.append("\nBacking up files...")
    for source_path, _ in files_to_update:
        backup = backup_file(source_path)
        if backup:
            messages.append(f"  ✓ Backed up {source_path.name} -> {backup.name}")
    
    if secrets_path.exists():
        backup = backup_file(secrets_path)
        if backup:
            messages.append(f"  ✓ Backed up secrets.env -> {backup.name}")
    
    # Create/update secrets.env
    messages.append("\nCreating secrets.env...")
    if secrets_path.exists():
        # Merge with existing
        existing = parse_env_file(secrets_path)
        existing.update(non_empty_values)
        
        # Rewrite file preserving structure where possible
        with open(secrets_path, "r") as f:
            content = f.read()
        
        for key, value in non_empty_values.items():
            if f"{key}=" in content:
                # Update existing line
                import re
                content = re.sub(
                    rf"^{key}=.*$",
                    f"{key}={value}",
                    content,
                    flags=re.MULTILINE
                )
            else:
                # Append new key
                content = content.rstrip() + f"\n{key}={value}\n"
        
        with open(secrets_path, "w") as f:
            f.write(content)
    else:
        # Create new file from template
        content = SECRETS_TEMPLATE.format(**{k: all_values.get(k, "") for k in [
            "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
            "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_ACCOUNT_HASH", "CLOUDFLARE_STREAM_CUSTOMER_CODE"
        ]})
        with open(secrets_path, "w") as f:
            f.write(content)
    
    messages.append(f"  ✓ Created {secrets_path}")
    
    # Remove keys from source files
    messages.append("\nCleaning up source files...")
    for source_path, keys in files_to_update:
        removed = remove_keys_from_file(source_path, keys, dry_run=False)
        if removed:
            messages.append(f"  ✓ Removed {removed} from {source_path.name}")
    
    messages.append("\n✓ Migration complete!")
    return True, messages


def main():
    parser = argparse.ArgumentParser(
        description="Migrate .env files to new secrets.env format"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path.home() / ".mirage" / "config",
        help="Path to config directory (default: ~/.mirage/config)"
    )
    args = parser.parse_args()
    
    print("=" * 60)
    print("Mirage Environment Migration Tool")
    print("=" * 60)
    print(f"\nConfig directory: {args.config_dir}")
    
    if not args.config_dir.exists():
        print(f"\n✗ Config directory does not exist: {args.config_dir}")
        sys.exit(1)
    
    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]\n")
    
    print("\nScanning for credentials to migrate...")
    success, messages = migrate(args.config_dir, dry_run=args.dry_run)
    
    for msg in messages:
        print(msg)
    
    print("\n" + "=" * 60)
    
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
