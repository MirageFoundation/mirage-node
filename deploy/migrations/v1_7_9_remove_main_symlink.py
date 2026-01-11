"""
v1.7.9: Remove ~/.mirage/main symlink

The v1.7.8 migration renamed ~/.mirage/main/ to ~/.mirage/node/ and created
a symlink main -> node for backward compatibility with the old binary.

Now that the binary uses "node" as the default home (v1.7.9-node-home upgrade),
the symlink is no longer needed and can be removed.
"""

import os
from pathlib import Path

MIGRATION_KEY = "v1.7.9-remove-main-symlink"
DESCRIPTION = "Remove ~/.mirage/main symlink (binary now uses node/ by default)"


def run(config_dir: Path, logger) -> str:
    data_dir = config_dir.parent  # ~/.mirage
    main_symlink = data_dir / "main"

    if not main_symlink.exists():
        return "main symlink already absent"

    if main_symlink.is_symlink():
        target = os.readlink(main_symlink)
        logger.info(f"    Removing symlink: {main_symlink} -> {target}")
        main_symlink.unlink()
        return f"removed symlink main -> {target}"

    # If it's a real directory (not symlink), don't touch it
    logger.warning(f"    {main_symlink} is a real directory, not a symlink - skipping")
    return "main is a directory (not symlink), skipped"
