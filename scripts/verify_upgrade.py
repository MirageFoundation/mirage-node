#!/usr/bin/env python3
"""
Verify a software upgrade was applied correctly on a Mirage chain.

Runs locally on the node (inside the container / on the server).
Queries localhost REST (1317) and RPC (26657) + local miraged binary.

Usage:
    python3 verify_upgrade.py [--upgrade-name NAME] [--debug]
"""
import json
import shutil
import subprocess
import sys
import urllib.request
import urllib.parse
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
RPC = "http://127.0.0.1:26657"
REST = "http://127.0.0.1:1317"

_passed = 0
_failed = 0
_warned = 0
_debug = False


def ok(msg: str) -> None:
    global _passed
    _passed += 1
    print(f"  \033[32m✓\033[0m {msg}")


def fail(msg: str) -> None:
    global _failed
    _failed += 1
    print(f"  \033[31m✗\033[0m {msg}")


def warn(msg: str) -> None:
    global _warned
    _warned += 1
    print(f"  \033[33m!\033[0m {msg}")


def debug(msg: str) -> None:
    if _debug:
        print(f"  [debug] {msg}")


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def http_get(url: str) -> dict | None:
    try:
        debug(f"GET {url}")
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        fail(f"HTTP GET {url} failed: {e}")
        return None


def find_miraged() -> str:
    for p in ["/opt/mirage/blockchain/bin/miraged", "/opt/mirage/blockchain/miraged"]:
        if Path(p).is_file():
            debug(f"Found miraged at {p}")
            return p
    found = shutil.which("miraged") or "miraged"
    debug(f"Using miraged from PATH: {found}")
    return found


def detect_upgrade_name() -> str | None:
    proposal_file = SCRIPTS_DIR / "proposals" / "proposal_upgrade.json"
    if proposal_file.exists():
        try:
            data = json.loads(proposal_file.read_text())
            for msg in data.get("messages", []):
                plan = msg.get("plan", {})
                if plan.get("name"):
                    debug(f"Detected upgrade name from proposal: {plan['name']}")
                    return plan["name"]
        except Exception:
            pass
    return None


EXPECTED_TIERS = [
    {
        "level": 0,
        "name": "Free",
        "period_fee": 0,
        "max_enabled_agents": 5,
        "max_followed_users": 25,
        "max_followed_topics": 25,
        "max_blocked_users": 25,
        "max_blocked_posts": 25,
        "max_blocked_topics": 25,
        "max_title_length": 150,
        "max_content_length": 1000,
        "editing_time_mins": 10,
        "vote_weight": 1.0,
        "can_be_agent": False,
        "can_remove_anon": False,
        "can_have_biography": False,
        "can_have_avatar": False,
        "can_have_banner": False,
        "can_have_flair": False,
    },
    {
        "level": 1,
        "name": "Subscriber",
        "period_fee": 100_000_000_000,
        "max_enabled_agents": 50,
        "max_followed_users": 500,
        "max_followed_topics": 500,
        "max_blocked_users": 500,
        "max_blocked_posts": 500,
        "max_blocked_topics": 500,
        "max_title_length": 300,
        "max_content_length": 20_000,
        "editing_time_mins": 360,
        "vote_weight": 1.33,
        "can_be_agent": False,
        "can_remove_anon": True,
        "can_have_biography": True,
        "can_have_avatar": True,
        "can_have_banner": True,
        "can_have_flair": True,
    },
    {
        "level": 10,
        "name": "Agent",
        "period_fee": 500_000_000_000,
        "max_enabled_agents": 50,
        "max_followed_users": 500,
        "max_followed_topics": 500,
        "max_blocked_users": 500,
        "max_blocked_posts": 500,
        "max_blocked_topics": 500,
        "max_title_length": 300,
        "max_content_length": 20_000,
        "editing_time_mins": 360,
        "vote_weight": 1.33,
        "can_be_agent": True,
        "can_remove_anon": True,
        "can_have_biography": True,
        "can_have_avatar": True,
        "can_have_banner": True,
        "can_have_flair": True,
    },
]

# Fields removed in v1.16.0 tier overhaul — must not appear in params response
REMOVED_TIER_FIELDS = [
    "max_followed_mods",
    "archive_duration_days",
    "eligible_for_mod",
    "can_change_name",
]

# Fields removed in v1.16.0 profile migration — must not appear in profile response
REMOVED_PROFILE_FIELDS = [
    "is_moderator",
    "followed_moderators",
]

EXPECTED_AWARD_CONFIGS = [
    {"name": "quality_post", "cost": 10_000_000_000},
    {"name": "original_content", "cost": 5_000_000_000},
    {"name": "based", "cost": 5_000_000_000},
    {"name": "receipts", "cost": 5_000_000_000},
]

EXPECTED_PARAMS = {
    "min_difficulty": 10,
    "mint_interval": 200,
    "mint_quantity": 5_800_000_000,
    "mint_dynamic_credit_cap": 100,
    "subscription_period": 43200,
    "relay_min_gas_price": 5000,
    "relay_max_gas_fee": 500_000_000,
    "max_envelope_age": 60,
    "min_username_size": 3,
    "max_username_size": 30,
    "min_topic_size": 2,
    "max_topic_size": 35,
    "block_hash_window": 10,
}


def is_valid_level(level: int) -> bool:
    return level in (0, 1, 10) or level >= 100


# ── Checks ─────────────────────────────────────────────────


def check_node_reachable() -> bool:
    section("Node Connectivity")
    data = http_get(f"{RPC}/status")
    if not data:
        fail("Node not reachable")
        return False
    r = data.get("result", {})
    ni = r.get("node_info", {})
    si = r.get("sync_info", {})
    network = ni.get("network", "?")
    cometbft = ni.get("version", "?")
    height = si.get("latest_block_height", "?")
    catching_up = si.get("catching_up", False)

    ok(f"Node reachable (network={network}, cometbft={cometbft}, height={height})")
    if catching_up:
        warn("Node is still catching up")
    else:
        ok("Node is synced")
    return True


def _version_matches(actual: str, upgrade_name: str) -> bool:
    if not actual or not upgrade_name:
        return False
    if upgrade_name in actual:
        return True
    if upgrade_name.startswith("v") and upgrade_name[1:] in actual:
        return True
    if not upgrade_name.startswith("v") and f"v{upgrade_name}" in actual:
        return True
    return False


def check_software_version(upgrade_name: str) -> None:
    section("Software Version")
    miraged = find_miraged()
    r = subprocess.run([miraged, "version"], capture_output=True, text=True, check=False)
    if r.returncode == 0:
        bin_ver = r.stdout.strip()
        ok(f"Binary on disk: {bin_ver}")
        if _version_matches(bin_ver, upgrade_name):
            ok(f"Binary version matches upgrade: {upgrade_name}")
        else:
            fail(f"Binary version mismatch: {bin_ver} (want {upgrade_name})")
    else:
        fail(f"Could not run '{miraged} version': {r.stderr.strip()[:120]}")

    data = http_get(f"{REST}/cosmos/base/tendermint/v1beta1/node_info")
    if data:
        ver = data.get("application_version", {}).get("version", "?")
        ok(f"Running node (ABCI): {ver}")
        if _version_matches(str(ver), upgrade_name):
            ok(f"ABCI version matches upgrade: {upgrade_name}")
        else:
            fail(f"ABCI version mismatch: {ver} (want {upgrade_name})")


def check_upgrade_plan(upgrade_name: str) -> None:
    section("Upgrade Status")

    data = http_get(f"{REST}/cosmos/upgrade/v1beta1/current_plan")
    if data is not None:
        plan = data.get("plan")
        if plan is None or plan == {}:
            ok("No active upgrade plan (cleared after upgrade)")
        else:
            fail(f"Upgrade plan still active: {plan.get('name', '?')} at height {plan.get('height', '?')}")

    data = http_get(f"{REST}/cosmos/upgrade/v1beta1/applied_plan/{upgrade_name}")
    if data is not None:
        h = data.get("height", "0")
        if h and h != "0":
            ok(f"Upgrade '{upgrade_name}' applied at height {h}")
        else:
            fail(f"Upgrade '{upgrade_name}' not found in applied upgrades")


def check_core_params() -> None:
    section("Core Module Parameters")
    data = http_get(f"{REST}/mirage/core/v1/params")
    if data is None:
        return

    params = data.get("params", {})

    # ── Global params ──
    for key, expected_val in EXPECTED_PARAMS.items():
        actual_raw = params.get(key, "0")
        actual_val = int(actual_raw)
        if actual_val != expected_val:
            fail(f"params.{key} = {actual_val} (want {expected_val})")
        else:
            ok(f"params.{key} = {actual_val}")

    mint_split = float(params.get("mint_dynamic_split", "0"))
    if abs(mint_split - 0.75) >= 0.01:
        fail(f"params.mint_dynamic_split = {mint_split} (want 0.75)")
    else:
        ok(f"params.mint_dynamic_split = {mint_split}")

    reserve_pct = float(params.get("subscription_reserve_percent", "0"))
    if abs(reserve_pct - 0.95) >= 0.01:
        fail(f"params.subscription_reserve_percent = {reserve_pct} (want 0.95)")
    else:
        ok(f"params.subscription_reserve_percent = {reserve_pct}")

    # ── Award configs ──
    award_configs = params.get("award_configs", [])
    if len(award_configs) != len(EXPECTED_AWARD_CONFIGS):
        fail(f"Expected {len(EXPECTED_AWARD_CONFIGS)} award configs, got {len(award_configs)}")
    else:
        ok(f"Award config count: {len(award_configs)}")
        award_errors = []
        for expected_ac in EXPECTED_AWARD_CONFIGS:
            match = next((a for a in award_configs if a.get("name") == expected_ac["name"]), None)
            if match is None:
                award_errors.append(f"missing award '{expected_ac['name']}'")
            else:
                actual_cost = int(match.get("cost", "0"))
                if actual_cost != expected_ac["cost"]:
                    award_errors.append(
                        f"award '{expected_ac['name']}' cost={actual_cost} (want {expected_ac['cost']})"
                    )
        if award_errors:
            for e in award_errors:
                fail(e)
        else:
            ok("All award configs match (names + costs)")

    # ── Tier configs ──
    tiers = params.get("tiers", [])
    if len(tiers) != 3:
        fail(f"Expected 3 tiers, got {len(tiers)}")
        return
    ok(f"Tier count: {len(tiers)}")

    int_fields = [
        "max_enabled_agents",
        "max_followed_users",
        "max_followed_topics",
        "max_blocked_users",
        "max_blocked_posts",
        "max_blocked_topics",
        "max_title_length",
        "max_content_length",
        "editing_time_mins",
    ]
    bool_fields = [
        "can_be_agent",
        "can_remove_anon",
        "can_have_biography",
        "can_have_avatar",
        "can_have_banner",
        "can_have_flair",
    ]

    for i, expected in enumerate(EXPECTED_TIERS):
        actual = tiers[i]
        label = f"Tier {expected['level']} ({expected['name']})"
        errors = []

        actual_fee = int(actual.get("period_fee", "0"))
        if actual_fee != expected["period_fee"]:
            errors.append(f"period_fee={actual_fee} (want {expected['period_fee']})")

        for f in int_fields:
            av = int(actual.get(f, "0"))
            if av != expected[f]:
                errors.append(f"{f}={av} (want {expected[f]})")

        for f in bool_fields:
            av = actual.get(f, False)
            if isinstance(av, str):
                av = av.lower() == "true"
            if av != expected[f]:
                errors.append(f"{f}={av} (want {expected[f]})")

        av_vw = float(actual.get("vote_weight", "0"))
        if abs(av_vw - expected["vote_weight"]) >= 0.01:
            errors.append(f"vote_weight={av_vw} (want {expected['vote_weight']})")

        if errors:
            for e in errors:
                fail(f"{label}: {e}")
        else:
            ok(f"{label}: all fields match")

    # ── Removed tier fields (pre-v1.16.0 leftovers) ──
    stale_found = False
    for i, tier in enumerate(tiers):
        for removed in REMOVED_TIER_FIELDS:
            if removed in tier:
                fail(f"Tier[{i}]: stale field '{removed}' still present")
                stale_found = True
    if not stale_found:
        ok("No stale pre-v1.16.0 tier fields present")


def fetch_all_profiles() -> tuple[list[dict], int | None]:
    """Fetch all profiles with pagination."""
    profiles: list[dict] = []
    next_key: str | None = None
    total: int | None = None
    page = 0
    while True:
        page += 1
        debug(f"Fetching profiles page {page} (next_key={'set' if next_key else 'none'})")
        url = f"{REST}/mirage/core/v1/profiles?pagination.limit=500&pagination.count_total=true"
        if next_key:
            url += f"&pagination.key={urllib.parse.quote(next_key)}"
        data = http_get(url)
        if data is None:
            break
        batch = data.get("profiles", [])
        profiles.extend(batch)
        debug(f"Fetched {len(batch)} profiles (total so far: {len(profiles)})")
        pagination = data.get("pagination", {}) or {}
        if total is None:
            try:
                total = int(pagination.get("total", "0"))
            except Exception:
                total = None
        nk = pagination.get("next_key")
        if not nk or not batch:
            break
        next_key = nk
        if page > 200:
            fail("Pagination safety limit reached (100k+ profiles)")
            break
    return profiles, total


def check_profiles() -> None:
    section("Profile Migration")
    profiles, total = fetch_all_profiles()
    if not profiles:
        fail("No profiles found (cannot validate migration)")
        return

    ok(f"Total profiles fetched: {len(profiles)}")
    if total and total > 0 and total != len(profiles):
        fail(f"Profile count mismatch: fetched {len(profiles)} vs pagination total {total}")

    bad_levels = []
    level_counts: dict[int, int] = {}
    missing_lists = {
        "enabled_agents": 0,
        "followed_users": 0,
        "followed_topics": 0,
        "blocked_users": 0,
        "blocked_posts": 0,
        "blocked_topics": 0,
    }
    missing_scalars = {
        "biography": 0,
        "avatar": 0,
        "banner": 0,
        "flair": 0,
    }
    stale_field_hits: dict[str, int] = {f: 0 for f in REMOVED_PROFILE_FIELDS}

    for p in profiles:
        lvl = p.get("level", 0)
        if isinstance(lvl, str):
            lvl = int(lvl)
        level_counts[lvl] = level_counts.get(lvl, 0) + 1
        if not is_valid_level(lvl):
            bad_levels.append((p.get("owner", "?")[:20], lvl))
        for key in missing_lists:
            if key not in p:
                missing_lists[key] += 1
        for key in missing_scalars:
            if key not in p:
                missing_scalars[key] += 1
        for removed_field in REMOVED_PROFILE_FIELDS:
            if removed_field in p:
                stale_field_hits[removed_field] += 1

    dist = ", ".join(f"lvl {k}: {v}" for k, v in sorted(level_counts.items()))
    ok(f"Level distribution: {dist}")

    if bad_levels:
        fail(f"{len(bad_levels)} profiles have invalid levels: {bad_levels[:5]}")
    else:
        ok("All profiles have valid levels (0, 1, 10, or 100+)")

    for key, count in missing_lists.items():
        if count:
            fail(f"{count} profiles missing '{key}' field")
        else:
            ok(f"All profiles include '{key}' field")

    # proto3 omits zero-value scalars (empty string) in JSON, so missing is expected
    for key, count in missing_scalars.items():
        if count:
            warn(f"{count} profiles missing '{key}' scalar field (empty values omitted by proto)")
        else:
            ok(f"All profiles include '{key}' scalar field")

    stale_any = False
    for removed_field, count in stale_field_hits.items():
        if count:
            fail(f"{count} profiles still have stale '{removed_field}' field")
            stale_any = True
    if not stale_any:
        ok("No stale pre-v1.16.0 profile fields present")

    self_agent_violations = []
    for p in profiles:
        owner = str(p.get("owner", "")).lower()
        agents = [str(a).lower() for a in (p.get("enabled_agents") or [])]
        if owner and owner in agents:
            self_agent_violations.append(owner[:20])
    if self_agent_violations:
        fail(f"{len(self_agent_violations)} profiles have themselves as enabled agent: {self_agent_violations[:5]}")
    else:
        ok("No profiles have themselves as enabled agent")


# ── Main ───────────────────────────────────────────────────


def main() -> int:
    args = sys.argv[1:]
    upgrade_name = None
    global _debug

    if "--debug" in args:
        args.remove("--debug")
        _debug = True

    if "--upgrade-name" in args:
        idx = args.index("--upgrade-name")
        if idx + 1 < len(args):
            upgrade_name = args[idx + 1]
            args = args[:idx] + args[idx + 2 :]

    if not upgrade_name:
        upgrade_name = detect_upgrade_name()
    if not upgrade_name:
        fail("Upgrade name not found (pass --upgrade-name or check proposal file)")
        section("Summary")
        total = _passed + _failed + _warned
        print(f"  Passed: {_passed}/{total}  Failed: {_failed}  Warnings: {_warned}")
        return 1

    print(f"==> Verifying upgrade '{upgrade_name}'")

    if not check_node_reachable():
        print(f"\n\033[31mFATAL: Cannot reach node at {RPC}\033[0m")
        return 1

    check_software_version(upgrade_name)
    check_upgrade_plan(upgrade_name)
    check_core_params()
    check_profiles()
    section("Summary")
    total = _passed + _failed + _warned
    print(f"  Passed: {_passed}/{total}  Failed: {_failed}  Warnings: {_warned}")
    if _failed:
        print(f"\n\033[31mUPGRADE VERIFICATION FAILED ({_failed} failures)\033[0m")
        return 1
    if _warned:
        print(f"\n\033[33mUPGRADE VERIFICATION PASSED with {_warned} warnings\033[0m")
        return 0
    print(f"\n\033[32mUPGRADE VERIFICATION PASSED\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
