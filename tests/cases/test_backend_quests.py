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
    return

    del backend

    if os.path.exists(os.path.join(REPO_ROOT, "web", "backend", "quest_settings.py")):
        _fail(
            "quest_config.no_hardcoded_module",
            "web/backend/quest_settings.py is back; the action-side tracker would "
            "again read quest flags that ignore this node's environment",
        )
    else:
        _pass("quest_config.no_hardcoded_module")

    tracker_src = open(os.path.join(REPO_ROOT, "web", "backend", "quest_tracker.py"), encoding="utf-8").read()
    if "quest_settings" not in tracker_src:
        _pass("quest_config.tracker_reads_env_settings")
    else:
        _fail("quest_config.tracker_reads_env_settings", "quest_tracker.py still imports quest_settings")

    # Every quest setting must be read in settings.py, the one module that
    # crashes on a missing or malformed value rather than inventing one.
    settings_src = open(os.path.join(REPO_ROOT, "web", "backend", "settings.py"), encoding="utf-8").read()
    required = (
        "QUESTS_ENABLED",
        "ACHIEVEMENTS_ENABLED",
        "QUESTS_DAILY_COUNT",
        "QUESTS_FLASH_COUNT",
        "QUESTS_FLASH_MIN_INTERVAL_HOURS",
        "QUESTS_FLASH_MAX_INTERVAL_HOURS",
        "QUESTS_INVITE_RECRUIT_CHANCE",
        "QUESTS_INVITE_EARNER_CHANCE",
        "QUESTS_INVITE_EARNER_INTERVAL",
    )
    missing = [name for name in required if f"\n{name} = require_" not in settings_src]
    if not missing:
        _pass("quest_config.settings_complete", count=len(required))
    else:
        _fail("quest_config.settings_complete", f"settings.py does not require {missing}")

    assignment_src = open(os.path.join(REPO_ROOT, "web", "backend", "quest_assignment.py"), encoding="utf-8").read()
    if assignment_src.count('with _locked_transaction(f"quest_assignment:{owner_lc}")') == 2:
        _pass("quest_config.daily_flash_share_owner_lock")
    else:
        _fail(
            "quest_config.daily_flash_share_owner_lock",
            "daily assignment and flash cooldown initialization are not serialized by the same lock",
        )

    if not _check_local_docker():
        _fail("quest_config.fail_hard_on_bad_settings", "local docker required")
        return

    # The env the node actually boots with decides these, and a missing or
    # nonsensical value must stop the process rather than be guessed around.
    probes = {
        "missing_achievements_flag": ("unset ACHIEVEMENTS_ENABLED", "ACHIEVEMENTS_ENABLED"),
        "negative_daily_count": ("export QUESTS_DAILY_COUNT=-1", "QUESTS_DAILY_COUNT"),
        "out_of_range_chance": ("export QUESTS_INVITE_RECRUIT_CHANCE=1.5", "QUESTS_INVITE_RECRUIT_CHANCE"),
        "zero_earner_interval": ("export QUESTS_INVITE_EARNER_INTERVAL=0", "QUESTS_INVITE_EARNER_INTERVAL"),
        "inverted_flash_interval": ("export QUESTS_FLASH_MIN_INTERVAL_HOURS=99", "QUESTS_FLASH_MIN_INTERVAL_HOURS"),
    }
    for name, (mutation, expected) in probes.items():
        code, out = docker_import_probe("settings", mutation)
        if code == 0 and "rc=1" in out and expected in out:
            _pass(f"quest_config.fail_hard_{name}")
        else:
            _fail(
                f"quest_config.fail_hard_{name}",
                f"settings imported anyway with {mutation!r}: {out[-300:]}",
            )

    from deploy.migrations.v1_33_3_require_explicit_settings import run as migrate_explicit_settings

    class _MigrationLogger:
        def info(self, _message):
            return None

    with tempfile.TemporaryDirectory() as tmp:
        config_dir = Path(tmp)
        (config_dir / "backend.env").write_text("")
        (config_dir / "indexer.env").write_text("INDEXER_ENABLED=yes\n")
        migrate_explicit_settings(config_dir, _MigrationLogger())
        normalized = (config_dir / "indexer.env").read_text()
    if "INDEXER_ENABLED=true" in normalized and "INDEXER_ENABLED=yes" not in normalized:
        _pass("quest_config.migration_normalizes_legacy_indexer_flag")
    else:
        _fail(
            "quest_config.migration_normalizes_legacy_indexer_flag",
            f"legacy INDEXER_ENABLED was not normalized: {normalized!r}",
        )


def test_quest_assignment(backend: str):
    """Quests were removed in v1.39.0."""
    code, _ = _get(f"{backend}/api/rewards/summary")
    if code == 410:
        _pass("quest_assignment.gone")
    else:
        _fail("quest_assignment.gone", f"code={code}")
    return

    if not _check_local_docker():
        _fail("quest_assignment.concurrent_requests_respect_cap", "local docker required")
        return

    db_name = resolve_db_name("BACKEND_DB_URL")
    if not db_name:
        _fail("quest_assignment.concurrent_requests_respect_cap", "BACKEND_DB_URL not resolvable")
        return

    code, resp = _get(f"{backend}/api/rewards/summary", {"owner": f"mirage1probe{_rand_str(8)}"})
    if code != 200:
        _fail("quest_assignment.concurrent_requests_respect_cap", f"rewards summary unavailable: {code} {resp}")
        return
    if resp.get("disabled"):
        _fail("quest_assignment.concurrent_requests_respect_cap", "quests are disabled on this node")
        return

    raw_cap = container_env("QUESTS_DAILY_COUNT")
    if not raw_cap.isdigit():
        _fail("quest_assignment.concurrent_requests_respect_cap", f"QUESTS_DAILY_COUNT unreadable: {raw_cap!r}")
        return
    cap = int(raw_cap)

    owner = f"mirage1qa{_rand_str(20)}"
    day_utc = _utc_julian_day(int(time.time()))

    def _hit(_i: int) -> int:
        status, _ = _get(f"{backend}/api/rewards/summary", {"owner": owner})
        return status

    with ThreadPoolExecutor(max_workers=12) as pool:
        statuses = [f.result() for f in as_completed([pool.submit(_hit, i) for i in range(12)])]

    bad_statuses = [s for s in statuses if s != 200]
    if bad_statuses:
        _fail("quest_assignment.concurrent_requests_respect_cap", f"non-200 responses: {bad_statuses}")
        return

    rc, out = _psql(
        db_name,
        f"SELECT count(*) FROM user_daily_quests WHERE LOWER(owner) = LOWER('{owner}') AND day_utc = {day_utc};",
    )
    if rc != 0 or not out.strip().isdigit():
        _fail("quest_assignment.concurrent_requests_respect_cap", f"count query failed rc={rc} out={out}")
        return

    assigned = int(out.strip())
    _debug(f"quest_assignment: owner={owner} assigned={assigned} cap={cap}")
    if (cap == 0 and assigned == 0) or (cap > 0 and 0 < assigned <= cap):
        _pass("quest_assignment.concurrent_requests_respect_cap", assigned=assigned, cap=cap)
    else:
        _fail(
            "quest_assignment.concurrent_requests_respect_cap",
            f"{assigned} quests assigned for one day with cap {cap}",
        )

    # A second wave must reuse the same set rather than top it up.
    with ThreadPoolExecutor(max_workers=6) as pool:
        [f.result() for f in as_completed([pool.submit(_hit, i) for i in range(6)])]

    rc2, out2 = _psql(
        db_name,
        f"SELECT count(*) FROM user_daily_quests WHERE LOWER(owner) = LOWER('{owner}') AND day_utc = {day_utc};",
    )
    if rc2 == 0 and out2.strip().isdigit() and int(out2.strip()) == assigned:
        _pass("quest_assignment.repeat_requests_are_idempotent", assigned=assigned)
    else:
        _fail(
            "quest_assignment.repeat_requests_are_idempotent",
            f"assignment changed on repeat requests: {out2.strip()} != {assigned}",
        )

    # The roll that decides a special quest must not change when the user
    # reloads, or a user could re-roll until they get the invite quest.
    rc, out = docker_python(
        "from quest_assignment import deterministic_roll as r; "
        f"print(len({{r('{owner}', {day_utc}, 'invite_recruit') for _ in range(5)}}), "
        f"r('{owner}', {day_utc}, 'invite_recruit') == r('{owner}', {day_utc + 1}, 'invite_recruit'))"
    )
    if rc == 0 and "1 False" in out:
        _pass("quest_assignment.roll_is_deterministic")
    else:
        _fail("quest_assignment.roll_is_deterministic", f"rc={rc} out={out[-300:]}")
