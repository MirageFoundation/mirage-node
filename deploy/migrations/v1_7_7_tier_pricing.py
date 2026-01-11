"""
Migration: v1.7.7-tier-pricing - Tier cost update and Go log rotation removal

This migration:
1. Cleans up ~/.mirage/main/logs/ directory (Go log rotation was removed from miraged)

Chain-side changes (via upgrade handler):
- Tier 1 (Trusted): 10 MIRAGE per 30 days
- Tier 2 (Established): 20 MIRAGE per 30 days
- Tier 3 (Distinguished): 30 MIRAGE per 30 days

Shell-based logging via cronolog now handles all log output to
~/.mirage/logs/node/miraged-YYYY-MM-DD.log

NOTE: This migration runs during container startup *before* miraged is started (see deploy/entrypoint.sh),
so it cannot reliably verify on-chain params. For post-start verification, run:
  python3 scripts/verify_v1_7_7_tier_pricing.py
"""

import shutil
from pathlib import Path

MIGRATION_KEY = "v1.7.7-tier-pricing"
DESCRIPTION = "Tier cost update and Go log rotation removal"


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    results = []
    data_dir = config_dir.parent  # ~/.mirage
    main_dir = data_dir / "main"

    # Remove old Go-based logs directory (node.log.* files)
    # This may have been recreated by the old binary since v1.7.6
    old_logs_dir = main_dir / "logs"
    if old_logs_dir.exists():
        file_count = sum(1 for _ in old_logs_dir.iterdir())
        shutil.rmtree(old_logs_dir)
        logger.info(f"    Removed main/logs/ ({file_count} files)")
        results.append(f"removed main/logs/ ({file_count} files)")

    if results:
        return "; ".join(results)
    return "no changes needed"
