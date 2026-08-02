"""Fleet inventory lookup for operator tools.

This repo is public, so real validator addresses, the peer list and per-host
maintenance windows are not committed. Tools that need them read ``.env`` on
the operator's machine; see ``.env.example`` for the contract.

Values may also come from the process environment, which takes precedence over
the file. That is what CI and one-off overrides use, e.g.::

    MIRAGE_FLEET_HOSTS=staging.example.com python3 scripts/backup_restore.py backup --all

Lookups are lazy: importing this module never fails, so the scripts that import
it still run ``--help`` and their local-only subcommands on a machine with no
inventory. Only asking for a missing key is an error, and it names the key
rather than falling back to a default that would point at the wrong host.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTORY_NAME = ".env"
EXAMPLE = ".env.example"
INVENTORY = REPO_ROOT / INVENTORY_NAME

_cache: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache

    values: dict[str, str] = {}
    if INVENTORY.exists():
        for raw in INVENTORY.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")

    _cache = values
    return _cache


def get(key: str, default: str | None = None) -> str | None:
    """Return an inventory value, or ``default`` when it is unset."""
    value = os.environ.get(key) or _load().get(key, "")
    return value or default


def require(key: str) -> str:
    """Return an inventory value, or exit with an actionable message.

    Raises ``SystemExit`` rather than a bare exception because every caller is
    an operator CLI: a one-line "here is the key you are missing" beats a
    traceback when you are mid-incident.
    """
    value = get(key)
    if value:
        return value

    raise SystemExit(
        f"{key} is not set.\n"
        f"  Real fleet addresses are not committed (this repo is public).\n"
        f"  Create {INVENTORY_NAME} from {EXAMPLE} and set {key},\n"
        f"  or pass it in the environment: {key}=... <command>"
    )


def hosts() -> list[str]:
    """Return the fleet hosts, in the order operator tools should visit them."""
    return [h.strip() for h in require("MIRAGE_FLEET_HOSTS").split(",") if h.strip()]
