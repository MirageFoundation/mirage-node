"""
Migration: v1.9.7 - Ensure tx_index is enabled in node config.

Ensures:
- config.toml has top-level tx_index = "on"
"""

from pathlib import Path
import re

MIGRATION_KEY = "v1_9_7_tx_index"
DESCRIPTION = "Enable tx_index in node config.toml"


def _read_lines(path: Path) -> list[str]:
    return path.read_text().splitlines()


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


def _set_top_level_key(path: Path, key: str, value: str, logger) -> bool:
    lines = _read_lines(path)
    first_table = next((i for i, l in enumerate(lines) if l.strip().startswith("[")), len(lines))

    for i in range(first_table):
        if re.match(rf"^\s*{re.escape(key)}\s*=", lines[i]):
            return False

    insert_at = first_table
    lines.insert(insert_at, f'{key} = "{value}"')
    _write_lines(path, lines)
    logger.info(f"    Added {key} to {path.name}")
    return True


def run(config_dir, logger):
    config_dir = Path(config_dir)
    data_dir = config_dir.parent
    node_config_dir = data_dir / "node" / "config"

    config_toml = node_config_dir / "config.toml"
    if not config_toml.exists():
        raise RuntimeError(f"Missing config.toml at {config_toml}")

    logger.info("  Updating node config for tx_index...")
    changed = _set_top_level_key(config_toml, "tx_index", "on", logger)

    return "updated" if changed else "no changes"
