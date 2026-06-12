import re
from pathlib import Path

from deploy.migrations._helpers import backup_file

MIGRATION_KEY = "v1.27.0-disable-fastnode"
DESCRIPTION = "Force iavl-disable-fastnode=true in node app.toml"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    app_toml = config_dir.parent / "node" / "config" / "app.toml"

    if not app_toml.exists():
        raise FileNotFoundError(f"app.toml not found: {app_toml}")

    backup_file(app_toml)
    content = app_toml.read_text(encoding="utf-8")

    key_pattern = re.compile(r"(?m)^\s*iavl-disable-fastnode\s*=\s*(true|false)\s*$")
    match = key_pattern.search(content)
    target_line = "iavl-disable-fastnode = true"

    if match:
        current = match.group(1)
        if current == "true":
            logger.info("  iavl-disable-fastnode already true")
            return "already true"
        updated = key_pattern.sub(target_line, content, count=1)
        app_toml.write_text(updated, encoding="utf-8")
        logger.info("  Updated iavl-disable-fastnode: false -> true")
        return "updated false -> true"

    anchor_pattern = re.compile(r"(?m)^(app-db-backend\s*=.*)$")
    note = (
        "# Disable IAVL fast-node so consensus reads always use canonical IAVL tree "
        "(prevents stale-read divergences)"
    )
    block = f"{note}\n{target_line}"

    if anchor_pattern.search(content):
        updated = anchor_pattern.sub(rf"\1\n\n{block}", content, count=1)
        app_toml.write_text(updated, encoding="utf-8")
        logger.info("  Added iavl-disable-fastnode below app-db-backend")
        return "added key near app-db-backend"

    updated = content.rstrip() + f"\n\n{block}\n"
    app_toml.write_text(updated, encoding="utf-8")
    logger.info("  Appended iavl-disable-fastnode at end of app.toml")
    return "appended key"
