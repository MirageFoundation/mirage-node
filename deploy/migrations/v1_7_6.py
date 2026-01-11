"""
Migration: v1.7.6 - Environment restructuring and cleanup

This migration:
1. Moves secrets to dedicated secrets.env file
2. Moves domain from .domain file to node.env (updates MONIKER if default)
3. Cleans up legacy/orphaned files
4. Moves ~/.hermes to ~/.mirage/hermes
5. Adds packet_filter to Hermes config (only relay on channel-1)
6. Sets Hermes `key_store_folder` per-chain to use ~/.mirage/hermes/keys

All operations are idempotent - safe to run multiple times.
"""

import shutil
from pathlib import Path

from deploy.migrations._helpers import (
    parse_env_file,
    remove_keys_from_file,
    update_env_value,
    backup_env_files,
)

MIGRATION_KEY = "v1.7.6"
DESCRIPTION = "Environment restructuring and cleanup"

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
    results = []
    data_dir = config_dir.parent  # ~/.mirage
    main_dir = data_dir / "main"
    templates_dir = Path(__file__).parent.parent / "templates"

    # =========================================================================
    # STEP 1: Move secrets to secrets.env
    # =========================================================================
    logger.info("  Step 1: Secrets migration")

    # Read ALL existing values from all env files
    all_values = {}
    for env_file in ["backend.env", "frontend.env", "indexer.env", "node.env", "secrets.env"]:
        env_path = config_dir / env_file
        if env_path.exists():
            values = parse_env_file(env_path)
            all_values.update(values)

    # Extract secret values
    secret_values = {k: all_values[k] for k in SECRET_KEYS if k in all_values and all_values[k]}

    if secret_values:
        # Backup existing files
        backup_env_files(config_dir, logger)

        # Create secrets.env from template if needed
        secrets_path = config_dir / "secrets.env"
        secrets_template = templates_dir / "secrets.env"
        if not secrets_path.exists() and secrets_template.exists():
            shutil.copy2(secrets_template, secrets_path)

        # Update secrets.env with secret values
        if secrets_path.exists():
            for key, value in secret_values.items():
                update_env_value(secrets_path, key, value)

        # Remove secret keys from source files
        for env_file in ["backend.env", "node.env"]:
            env_path = config_dir / env_file
            if env_path.exists():
                remove_keys_from_file(env_path, SECRET_KEYS, logger)

        results.append(f"{len(secret_values)} secrets migrated")
        logger.info(f"    Migrated {len(secret_values)} secrets")

    # =========================================================================
    # STEP 2: Move domain to node.env
    # =========================================================================
    logger.info("  Step 2: Domain migration")

    domain_file = data_dir / ".domain"
    node_env = config_dir / "node.env"
    existing = parse_env_file(node_env)

    # Read domain from legacy file
    domain = ""
    if domain_file.exists():
        domain = domain_file.read_text().strip()

    if domain:
        # Set DOMAIN if not already set
        if not existing.get("DOMAIN"):
            if node_env.exists():
                with open(node_env, "a") as f:
                    f.write(f"\nDOMAIN={domain}\n")
                logger.info(f"    Set DOMAIN={domain}")

        # NOTE: We no longer auto-sync MONIKER from DOMAIN.
        # MONIKER should be set explicitly to match the on-chain validator description.
        # The on-chain moniker may include "https://" or other formatting.

        results.append(f"domain={domain}")

    # =========================================================================
    # STEP 3: Clean up legacy files
    # =========================================================================
    logger.info("  Step 3: Cleanup legacy files")

    removed = []

    # CometBFT temp files
    config_path = main_dir / "config"
    if config_path.exists():
        temp_files = list(config_path.glob("write-file-atomic-*"))
        if temp_files:
            for f in temp_files:
                f.unlink()
            removed.append(f"write-file-atomic-* ({len(temp_files)})")

    # Old priv_validator_key backups
    if config_path.exists():
        backup_files = list(config_path.glob("priv_validator_key.json.bak-*"))
        if backup_files:
            for f in backup_files:
                f.unlink()
            removed.append(f"priv_validator_key.json.bak-* ({len(backup_files)})")

    # Orphaned priv_validator_state.json from root
    orphan_pv_state = data_dir / "priv_validator_state.json"
    if orphan_pv_state.exists():
        orphan_pv_state.unlink()
        removed.append("priv_validator_state.json")

    # Legacy .domain file (now in node.env)
    if domain_file.exists():
        domain_file.unlink()
        removed.append(".domain")

    # Old snapshot location (main/bin/)
    old_bin_dir = main_dir / "bin"
    if old_bin_dir.exists():
        shutil.rmtree(old_bin_dir)
        removed.append("main/bin/")

    # Old snapshot location (main/indexer.sql)
    old_indexer_sql = main_dir / "indexer.sql"
    if old_indexer_sql.exists():
        old_indexer_sql.unlink()
        removed.append("main/indexer.sql")

    # Legacy setup directory
    setup_dir = data_dir / "setup"
    if setup_dir.exists():
        shutil.rmtree(setup_dir)
        removed.append("setup/")

    # Old logs directory (garbage node.log files from Go rotation)
    old_logs_dir = main_dir / "logs"
    if old_logs_dir.exists():
        shutil.rmtree(old_logs_dir)
        removed.append("main/logs/")

    # Old miraged.log (new logs via cronolog)
    old_miraged_log = main_dir / "miraged.log"
    if old_miraged_log.exists():
        old_miraged_log.unlink()
        removed.append("main/miraged.log")

    # Dead marker file (.validator_auto_enabled)
    validator_marker = main_dir / ".validator_auto_enabled"
    if validator_marker.exists():
        validator_marker.unlink()
        removed.append(".validator_auto_enabled")

    # Old indexer lock directory (lock now in /tmp)
    old_indexer_dir = main_dir / "data" / "indexer"
    if old_indexer_dir.exists():
        shutil.rmtree(old_indexer_dir)
        removed.append("main/data/indexer/")

    if removed:
        results.append(f"removed {len(removed)} legacy items")
        logger.info(f"    Removed: {', '.join(removed)}")

    # =========================================================================
    # STEP 4: Move ~/.hermes to ~/.mirage/hermes
    # =========================================================================
    logger.info("  Step 4: Hermes directory migration")

    home_dir = Path.home()
    old_hermes = home_dir / ".hermes"
    new_hermes = data_dir / "hermes"

    if old_hermes.exists() and old_hermes.is_dir() and not old_hermes.is_symlink():
        if new_hermes.exists():
            # Both exist - merge (copy files that don't exist in new location)
            for item in old_hermes.iterdir():
                dest = new_hermes / item.name
                if not dest.exists():
                    if item.is_dir():
                        shutil.copytree(item, dest)
                    else:
                        shutil.copy2(item, dest)
            # Remove old directory
            shutil.rmtree(old_hermes)
            logger.info("    Merged ~/.hermes -> ~/.mirage/hermes")
            results.append("merged hermes dir")
        else:
            # Move old to new
            shutil.move(str(old_hermes), str(new_hermes))
            logger.info("    Moved ~/.hermes -> ~/.mirage/hermes")
            results.append("moved hermes dir")

    # =========================================================================
    # STEP 5: Update Hermes config (packet_filter + per-chain key_store_folder)
    # =========================================================================
    logger.info("  Step 5: Hermes config updates")

    hermes_config = data_dir / "hermes" / "config.toml"

    if hermes_config.exists():
        content = hermes_config.read_text()
        modified = False

        # Remove INVALID key_store_folder placements from our prior attempt
        # (top-level or [global]); valid placement is inside each [[chains]] block.
        cleaned_lines = []
        in_global = False
        in_chain = False
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("[global]"):
                in_global = True
                in_chain = False
            elif stripped.startswith("[[chains]]"):
                in_chain = True
                in_global = False
            elif stripped.startswith("[") and not stripped.startswith("[[chains]]") and stripped != "[global]":
                # any other section
                in_chain = False
                in_global = False

            # Drop key_store_folder lines that are NOT inside a chain block
            if stripped.startswith("key_store_folder") and not in_chain:
                modified = True
                continue
            cleaned_lines.append(line)
        content = "\n".join(cleaned_lines)

        # Ensure each chain has key_store_folder (points to ~/.mirage/hermes/keys)
        lines = content.split("\n")
        new_lines = []
        in_chain = False
        saw_key_store = False
        saw_key_name = False
        current_chain_id = None

        def _should_add_key_store(chain_id: str | None) -> str | None:
            if chain_id == "mirage-1" or chain_id == "osmosis-1":
                # NOTE: Hermes does not expand $HOME in this field in our environment,
                # so we use an absolute path.
                return "key_store_folder = '/root/.mirage/hermes/keys'"
            return None

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[[chains]]"):
                # finalize previous chain (if missing)
                if in_chain and not saw_key_store:
                    ks = _should_add_key_store(current_chain_id)
                    if ks:
                        new_lines.append(ks)
                        modified = True
                # reset for new chain
                in_chain = True
                saw_key_store = False
                saw_key_name = False
                current_chain_id = None
                new_lines.append(line)
                continue

            if in_chain:
                if stripped.startswith("id ="):
                    # e.g. id = 'mirage-1'
                    current_chain_id = stripped.split("=", 1)[1].strip().strip("'").strip('"')
                if stripped.startswith("key_store_folder"):
                    saw_key_store = True
                if stripped.startswith("key_name"):
                    saw_key_name = True
                    new_lines.append(line)
                    # insert key_store_folder immediately after key_name if missing
                    if not saw_key_store:
                        ks = _should_add_key_store(current_chain_id)
                        if ks:
                            new_lines.append(ks)
                            saw_key_store = True
                            modified = True
                    continue

            new_lines.append(line)

        # finalize last chain
        if in_chain and not saw_key_store:
            ks = _should_add_key_store(current_chain_id)
            if ks:
                new_lines.append(ks)
                modified = True

        content = "\n".join(new_lines)

        # Add packet_filter if missing (only relay on channel-1)
        if "packet_filter" not in content:
            lines = content.split("\n")
            new_lines = []
            current_chain = None

            for line in lines:
                new_lines.append(line)

                # Track which chain we're in
                if line.strip().startswith("id = 'mirage-1'"):
                    current_chain = "mirage-1"
                elif line.strip().startswith("id = 'osmosis-1'"):
                    current_chain = "osmosis-1"
                elif line.strip().startswith("[[chains]]"):
                    current_chain = None

                # Add packet_filter after address_type line
                if "address_type" in line and current_chain:
                    new_lines.append("")
                    new_lines.append("[chains.packet_filter]")
                    new_lines.append("policy = 'allow'")
                    if current_chain == "mirage-1":
                        new_lines.append("list = [['transfer', 'channel-1']]")
                    elif current_chain == "osmosis-1":
                        new_lines.append("list = [['transfer', 'channel-108698']]")
                    current_chain = None

            content = "\n".join(new_lines)
            logger.info("    Added packet_filter (channel-1 <-> channel-108698)")
            modified = True

        if modified:
            hermes_config.write_text(content)
            results.append("hermes config updated")
        else:
            logger.info("    Hermes config already up to date")

    # =========================================================================
    # Summary
    # =========================================================================
    if results:
        return "; ".join(results)
    return "no changes needed"
