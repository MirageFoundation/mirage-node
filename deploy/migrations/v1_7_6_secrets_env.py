"""
Migration: Move secrets to secrets.env

Moves sensitive credentials from node.env/backend.env to secrets.env.
"""

import shutil
from pathlib import Path

from deploy.migrations.helpers import (
    parse_env_file,
    remove_keys_from_file,
    update_env_value,
    backup_env_files,
)

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
    backup_env_files(config_dir, logger)

    # Step 4: Create secrets.env from template if it doesn't exist
    secrets_path = config_dir / "secrets.env"
    secrets_template = templates_dir / "secrets.env"
    if not secrets_path.exists() and secrets_template.exists():
        shutil.copy2(secrets_template, secrets_path)
        logger.info("  Created secrets.env from template")

    # Step 5: Update secrets.env with secret values
    if secret_values and secrets_path.exists():
        for key, value in secret_values.items():
            update_env_value(secrets_path, key, value)
        logger.info(f"  Added {len(secret_values)} secrets to secrets.env")

    # Step 6: Remove secret keys from source files
    for env_file in ["backend.env", "node.env"]:
        env_path = config_dir / env_file
        if env_path.exists():
            removed = remove_keys_from_file(env_path, SECRET_KEYS, logger)
            if removed:
                logger.info(f"  Removed {removed} secret keys from {env_file}")

    return f"migrated {len(secret_values)} secrets"
