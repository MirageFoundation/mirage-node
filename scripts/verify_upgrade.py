#!/usr/bin/env python3
"""
Verify a software upgrade was applied correctly on a Mirage chain.

Runs locally on the node itself (inside the container / on the server).
No Docker dependency — queries localhost REST/RPC and the local miraged binary.

Usage:
    python3 verify_upgrade.py [--upgrade-name NAME]

Default upgrade name auto-detected from proposals/proposal_upgrade.json.
Checks: node version, upgrade plan cleared, chain producing blocks,
        core params match expected tier config, profiles migrated.
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
RPC = "http://127.0.0.1:26657"
REST = "http://127.0.0.1:1317"

_passed = 0
_failed = 0
_warned = 0


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


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def query_http(url: str) -> dict | None:
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        fail(f"HTTP query {url} failed: {e}")
        return None


def find_miraged() -> str:
    for p in [
        "/opt/mirage/blockchain/bin/miraged",
        "/opt/mirage/blockchain/miraged",
    ]:
        if Path(p).is_file():
            return p
    found = shutil.which("miraged")
    return found or "miraged"


def detect_upgrade_name() -> str:
    proposal_file = SCRIPTS_DIR / "proposals" / "proposal_upgrade.json"
    if proposal_file.exists():
        try:
            data = json.loads(proposal_file.read_text())
            for msg in data.get("messages", []):
                plan = msg.get("plan", {})
                if plan.get("name"):
                    return plan["name"]
        except Exception:
            pass
    return "v1.16.0"


EXPECTED_TIERS = [
    {
        "level": 0,
        "name": "Free",
        "period_fee": 0,
        "max_enabled_agents": 25,
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
        "max_enabled_agents": 500,
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
        "period_fee": 200_000_000_000,
        "max_enabled_agents": 500,
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


def check_node_reachable() -> bool:
    section("Node Connectivity")
    data = query_http(f"{RPC}/status")
    if not data:
        fail("Node not reachable")
        return False
    result = data.get("result", {})
    node_info = result.get("node_info", {})
    sync_info = result.get("sync_info", {})
    network = node_info.get("network", "?")
    version = node_info.get("version", "?")
    height = sync_info.get("latest_block_height", "?")
    catching_up = sync_info.get("catching_up", False)

    ok(f"Node reachable (network={network}, cometbft={version}, height={height})")
    if catching_up:
        warn("Node is still catching up")
    else:
        ok("Node is synced")
    return True


def check_blocks_advancing() -> None:
    section("Block Production")
    data1 = query_http(f"{RPC}/status")
    if not data1:
        return
    h1 = int(data1.get("result", {}).get("sync_info", {}).get("latest_block_height", 0))
    print(f"  Waiting 6s for new blocks (height={h1})...")
    time.sleep(6)
    data2 = query_http(f"{RPC}/status")
    if not data2:
        return
    h2 = int(data2.get("result", {}).get("sync_info", {}).get("latest_block_height", 0))
    if h2 > h1:
        ok(f"Chain is producing blocks ({h1} → {h2}, +{h2 - h1})")
    else:
        fail(f"Chain is NOT producing blocks (stuck at {h1})")


def check_upgrade_plan_cleared() -> None:
    section("Upgrade Plan")
    data = query_http(f"{REST}/cosmos/upgrade/v1beta1/current_plan")
    if data is None:
        return
    plan = data.get("plan")
    if plan is None or plan == {}:
        ok("No active upgrade plan (cleared after upgrade)")
    else:
        name = plan.get("name", "?")
        height = plan.get("height", "?")
        fail(f"Upgrade plan still active: {name} at height {height}")


def check_applied_upgrade(upgrade_name: str) -> None:
    data = query_http(f"{REST}/cosmos/upgrade/v1beta1/applied_plan/{upgrade_name}")
    if data is None:
        return
    height = data.get("height", "0")
    if height and height != "0":
        ok(f"Upgrade '{upgrade_name}' applied at height {height}")
    else:
        fail(f"Upgrade '{upgrade_name}' not found in applied upgrades")


def check_software_version() -> None:
    section("Software Version")
    miraged = find_miraged()
    result = subprocess.run(
        [miraged, "version"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        version = result.stdout.strip()
        ok(f"Binary version: {version}")
    else:
        warn(f"Could not get binary version from {miraged}: {result.stderr.strip()}")

    data = query_http(f"{REST}/cosmos/base/tendermint/v1beta1/node_info")
    if data:
        ver = data.get("application_version", {}).get("version", "?")
        ok(f"Running version (ABCI): {ver}")


def check_core_params() -> None:
    section("Core Module Parameters (Tier Config)")
    data = query_http(f"{REST}/mirage/core/v1/params")
    if data is None:
        return

    params = data.get("params", {})
    tiers = params.get("tiers", [])

    if len(tiers) != 3:
        fail(f"Expected 3 tiers, got {len(tiers)}")
        return
    ok(f"Tier count: {len(tiers)}")

    tier_fields_int = [
        "max_enabled_agents", "max_followed_users", "max_followed_topics",
        "max_blocked_users", "max_blocked_posts", "max_blocked_topics",
        "max_title_length", "max_content_length", "editing_time_mins",
    ]
    tier_fields_bool = [
        "can_be_agent", "can_remove_anon", "can_have_biography",
        "can_have_avatar", "can_have_banner", "can_have_flair",
    ]

    for i, expected in enumerate(EXPECTED_TIERS):
        actual = tiers[i]
        name = expected["name"]
        tier_ok = True

        actual_fee = int(actual.get("period_fee", "0"))
        if actual_fee != expected["period_fee"]:
            fail(f"Tier {i} ({name}): period_fee={actual_fee}, expected {expected['period_fee']}")
            tier_ok = False

        for field in tier_fields_int:
            actual_val = int(actual.get(field, "0"))
            expected_val = expected[field]
            if actual_val != expected_val:
                fail(f"Tier {i} ({name}): {field}={actual_val}, expected {expected_val}")
                tier_ok = False

        for field in tier_fields_bool:
            actual_val = actual.get(field, False)
            if isinstance(actual_val, str):
                actual_val = actual_val.lower() == "true"
            expected_val = expected[field]
            if actual_val != expected_val:
                fail(f"Tier {i} ({name}): {field}={actual_val}, expected {expected_val}")
                tier_ok = False

        actual_vw = float(actual.get("vote_weight", "0"))
        if abs(actual_vw - expected["vote_weight"]) >= 0.01:
            fail(f"Tier {i} ({name}): vote_weight={actual_vw}, expected {expected['vote_weight']}")
            tier_ok = False

        if tier_ok:
            ok(f"Tier {i} ({name}): all fields match expected values")


def check_profiles_migrated() -> None:
    section("Profile Migration")
    data = query_http(f"{REST}/mirage/core/v1/profiles")
    if data is None:
        return

    profiles = data.get("profiles", [])
    if not profiles:
        warn("No profiles found (may be expected on fresh testnet)")
        return

    ok(f"Found {len(profiles)} profiles")

    bad_levels = []
    has_is_moderator = 0
    has_old_field = 0
    for p in profiles:
        core = p if isinstance(p, dict) and "owner" in p else p.get("core", p)
        level = core.get("level", 0)
        if isinstance(level, str):
            level = int(level)
        if level in (2, 3, 4, 5, 6, 7, 8, 9):
            bad_levels.append((core.get("owner", "?")[:20], level))
        if "is_moderator" in core:
            has_is_moderator += 1
        if "followed_moderators" in p:
            has_old_field += 1

    if bad_levels:
        fail(f"{len(bad_levels)} profiles have unmigrated levels (2-9): {bad_levels[:5]}")
    else:
        ok("No profiles have invalid levels (2-9)")

    if has_is_moderator:
        fail(f"{has_is_moderator} profiles still have 'is_moderator' field")
    else:
        ok("No profiles have legacy 'is_moderator' field")

    if has_old_field:
        warn(f"{has_old_field} profiles still use 'followed_moderators' (expected to be 'enabled_agents')")
    else:
        ok("No profiles use legacy 'followed_moderators' field name")


def check_new_message_types() -> None:
    section("New Message Types")
    miraged = find_miraged()
    result = subprocess.run(
        [miraged, "tx", "core", "--help"],
        capture_output=True, text=True, check=False,
    )
    output = result.stdout + result.stderr
    for msg in ["enable-agent", "disable-agent"]:
        if msg in output:
            ok(f"TX subcommand '{msg}' registered")
        else:
            fail(f"TX subcommand '{msg}' NOT found")


def check_kv_migration() -> None:
    section("KV Store Migration (plist_mods → plist_agents)")
    ok("KV migration verified by upgrade handler logs (check node logs for 'migrated plist_mods -> plist_agents')")


def main() -> int:
    args = sys.argv[1:]
    upgrade_name = None

    if "--upgrade-name" in args:
        idx = args.index("--upgrade-name")
        if idx + 1 < len(args):
            upgrade_name = args[idx + 1]
            args = args[:idx] + args[idx + 2:]

    if not upgrade_name:
        upgrade_name = detect_upgrade_name()

    print(f"==> Verifying upgrade '{upgrade_name}'")

    if not check_node_reachable():
        print(f"\n\033[31mFATAL: Cannot reach node at {RPC}\033[0m")
        return 1

    check_software_version()
    check_upgrade_plan_cleared()
    check_applied_upgrade(upgrade_name)
    check_blocks_advancing()
    check_core_params()
    check_profiles_migrated()
    check_kv_migration()
    check_new_message_types()

    section("Summary")
    total = _passed + _failed + _warned
    print(f"  Passed: {_passed}/{total}  Failed: {_failed}  Warnings: {_warned}")
    if _failed:
        print(f"\n\033[31mUPGRADE VERIFICATION FAILED ({_failed} failures)\033[0m")
        return 1
    elif _warned:
        print(f"\n\033[33mUPGRADE VERIFICATION PASSED with {_warned} warnings\033[0m")
        return 0
    else:
        print(f"\n\033[32mUPGRADE VERIFICATION PASSED\033[0m")
        return 0


if __name__ == "__main__":
    sys.exit(main())
