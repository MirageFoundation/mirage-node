from __future__ import annotations

"""
PostgreSQL connection helper for backend (hard-fail, no fallbacks).
"""

import psycopg
from typing import Optional, Any, Dict

from shared.config import get_config


def connect_db(timeout: float = 10.0, busy_timeout_ms: int = 15000) -> psycopg.Connection:
    """
    Open a connection to the indexer PostgreSQL database.
    timeout and busy_timeout_ms are ignored for PostgreSQL and kept for API compatibility.
    """
    cfg = get_config()
    idx: Dict[str, Any] = cfg.get_indexer_config()
    url = idx.get("database_url")
    if not url:
        raise RuntimeError("INDEXER_DB_URL is required")
    return psycopg.connect(url, autocommit=True)


__all__ = ["connect_db"]


