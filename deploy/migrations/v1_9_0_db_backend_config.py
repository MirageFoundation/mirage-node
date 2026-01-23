"""
Migration: v1.9.0 - Add DB backend + statesync defaults to node config.

Ensures:
- config.toml has top-level db_backend
- app.toml has top-level app-db-backend
- config.toml has a [statesync] section with required keys

This migration is safe to run multiple times; it only adds missing keys.
"""

from pathlib import Path
import re

MIGRATION_KEY = "v1_9_0_db_backend_config"
DESCRIPTION = "Add db_backend/app-db-backend/statesync defaults to node config"


def _read_lines(path: Path) -> list[str]:
    return path.read_text().splitlines()


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


def _set_top_level_key(path: Path, key: str, value: str, logger) -> bool:
    lines = _read_lines(path)
    first_table = next((i for i, l in enumerate(lines) if l.strip().startswith("[")), len(lines))
    found = False

    for i in range(first_table):
        if re.match(rf"^\s*{re.escape(key)}\s*=", lines[i]):
            found = True
            return False

    insert_at = first_table
    lines.insert(insert_at, f'{key} = "{value}"')
    _write_lines(path, lines)
    logger.info(f"    Added {key} to {path.name}")
    return True


def _ensure_statesync_block(path: Path, logger) -> bool:
    defaults = {
        "enable": "false",
        "rpc_servers": '""',
        "trust_height": "0",
        "trust_hash": '""',
        "trust_period": '"168h0m0s"',
    }
    lines = _read_lines(path)
    changed = False

    # Find [statesync] block
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "[statesync]":
            start_idx = i
            continue
        if start_idx is not None and line.strip().startswith("[") and i > start_idx:
            end_idx = i
            break

    if start_idx is None:
        # Append block at end
        lines.append("")
        lines.append("[statesync]")
        for k, v in defaults.items():
            lines.append(f"{k} = {v}")
        _write_lines(path, lines)
        logger.info("    Added [statesync] block to config.toml")
        return True

    if end_idx is None:
        end_idx = len(lines)

    block = lines[start_idx + 1 : end_idx]
    existing_keys = set()
    for line in block:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            existing_keys.add(key)

    missing = [k for k in defaults.keys() if k not in existing_keys]
    if missing:
        insert_at = end_idx
        for k in missing:
            lines.insert(insert_at, f"{k} = {defaults[k]}")
            insert_at += 1
        _write_lines(path, lines)
        logger.info(f"    Added statesync keys: {missing}")
        changed = True

    return changed


def run(config_dir, logger):
    config_dir = Path(config_dir)
    data_dir = config_dir.parent
    node_config_dir = data_dir / "node" / "config"

    config_toml = node_config_dir / "config.toml"
    app_toml = node_config_dir / "app.toml"

    if not config_toml.exists():
        raise RuntimeError(f"Missing config.toml at {config_toml}")
    if not app_toml.exists():
        raise RuntimeError(f"Missing app.toml at {app_toml}")

    logger.info("  Updating node config for db backend/statesync...")

    changed = False
    changed |= _set_top_level_key(config_toml, "db_backend", "goleveldb", logger)
    changed |= _set_top_level_key(app_toml, "app-db-backend", "goleveldb", logger)
    changed |= _ensure_statesync_block(config_toml, logger)

    return "updated" if changed else "no changes"
