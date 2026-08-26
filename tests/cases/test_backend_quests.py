"""Quest configuration and assignment tests.

Covers the two ways the quest system could hand out more than it should: a
second, hardcoded copy of the configuration that ignored the node's settings,
and unserialized assignment that let concurrent first requests each hand the
same user a full set of quests.
"""

from __future__ import annotations

import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tests.common import (
    _pass,
    _fail,
    _debug,
    _get,
    _rand_str,
    _docker_exec,
    _check_local_docker,
    container_env,
    docker_import_probe,
    docker_python,
    resolve_db_name,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _psql(db_name: str, sql: str) -> tuple[int, str]:
    return _docker_exec(f'su - postgres -c "psql -d {db_name} -tAc \\"{sql}\\" 2>&1"', timeout=15)


def _utc_julian_day(ts: int) -> int:
    return 2440588 + (ts // 86400)


def test_quest_config(backend: str):
    """Quests were removed in v1.39.0."""
    code, _ = _get(f"{backend}/api/rewards/summary")
    if code == 410:
        _pass("quest_config.gone")
    else:
        _fail("quest_config.gone", f"code={code}")


def test_quest_assignment(backend: str):
    """Quests were removed in v1.39.0."""
    code, _ = _get(f"{backend}/api/rewards/summary")
    if code == 410:
        _pass("quest_assignment.gone")
    else:
        _fail("quest_assignment.gone", f"code={code}")
