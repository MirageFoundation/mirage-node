"""
Migration: Clean up legacy/orphaned files

This migration removes files and directories that are no longer used:
1. ~/.mirage/main/config/write-file-atomic-* - CometBFT temp files not cleaned up
2. ~/.mirage/main/config/priv_validator_key.json.bak-* - old backup files
3. ~/.mirage/priv_validator_state.json - orphaned file (correct location is main/data/)
4. ~/.mirage/.domain - legacy domain file (now in node.env)
5. ~/.mirage/main/bin/ - old snapshot location (now main/snapshot/)
6. ~/.mirage/main/indexer.sql - old snapshot location (now main/snapshot/)
7. ~/.mirage/setup/ - legacy manual setup directory (all contents are duplicates or unused)
"""

import shutil
from pathlib import Path

MIGRATION_KEY = "v1.7.6_cleanup_legacy"
DESCRIPTION = "Remove legacy/orphaned files and directories"


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    data_dir = config_dir.parent  # ~/.mirage
    main_dir = data_dir / "main"
    
    removed = []
    
    # 1. Remove CometBFT temp files
    config_path = main_dir / "config"
    if config_path.exists():
        temp_files = list(config_path.glob("write-file-atomic-*"))
        if temp_files:
            for f in temp_files:
                f.unlink()
            removed.append(f"main/config/write-file-atomic-* ({len(temp_files)} files)")
            logger.info(f"  Removed {len(temp_files)} CometBFT temp files")
    
    # 2. Remove old priv_validator_key backups
    if config_path.exists():
        backup_files = list(config_path.glob("priv_validator_key.json.bak-*"))
        if backup_files:
            for f in backup_files:
                f.unlink()
            removed.append(f"main/config/priv_validator_key.json.bak-* ({len(backup_files)} files)")
            logger.info(f"  Removed {len(backup_files)} validator key backup files")
    
    # 3. Remove orphaned priv_validator_state.json from root
    orphan_pv_state = data_dir / "priv_validator_state.json"
    if orphan_pv_state.exists():
        orphan_pv_state.unlink()
        removed.append("priv_validator_state.json")
        logger.info("  Removed orphaned priv_validator_state.json")
    
    # 4. Remove legacy .domain file
    legacy_domain = data_dir / ".domain"
    if legacy_domain.exists():
        legacy_domain.unlink()
        removed.append(".domain")
        logger.info("  Removed legacy .domain file")
    
    # 5. Remove old snapshot location (main/bin/)
    old_bin_dir = main_dir / "bin"
    if old_bin_dir.exists():
        shutil.rmtree(old_bin_dir)
        removed.append("main/bin/")
        logger.info("  Removed old main/bin/ directory")
    
    # 6. Remove old snapshot location (main/indexer.sql)
    old_indexer_sql = main_dir / "indexer.sql"
    if old_indexer_sql.exists():
        old_indexer_sql.unlink()
        removed.append("main/indexer.sql")
        logger.info("  Removed old main/indexer.sql")
    
    # 7. Remove legacy setup directory
    setup_dir = data_dir / "setup"
    if setup_dir.exists():
        shutil.rmtree(setup_dir)
        removed.append("setup/")
        logger.info("  Removed legacy setup/ directory")
    
    if removed:
        return f"removed: {', '.join(removed)}"
    return "no legacy files found"
