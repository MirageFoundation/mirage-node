#!/usr/bin/env python3
"""
Verify Mirage Node Upgrade — strict + exhaustive.

This script is intentionally "no hand-waving":
- It validates EVERY core param field introduced/used by v1.9.x (including every tier field).
- It validates bridge query commands (`miraged q bridge ...`) exist and return consistent data.
- It validates upgrade state (pre vs post) and local config consistency.
- It checks that critical CLI commands are exposed.
- It can optionally verify genesis export with --export-check (stops node, runs export, restarts).
- It shows status of ALL registered upgrades.

NOTE: This does NOT submit transactions or mutate chain state.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request


# Current upgrade being verified (set via --upgrade or defaults to latest)
UPGRADE_NAME = "v1.10.4-restore-sdk"
REQUIRED_MIN_GAS_PRICE = "5000umirage"
EXPECTED_VERSION_PREFIX = "v1.10"

# All registered upgrade names in chronological order
ALL_UPGRADES = [
    "v1.2.0-follow-mods",
    "v1.3.0-tiers",
    "v1.3.1",
    "v1.4.0-profile-core",
    "v1.5.0-social-graph",
    "v1.5.1",
    "v1.6.0-personalized-feeds",
    "v1.7.7-tier-pricing",
    "v1.7.9-node-home",
    "v1.8.0-economics",
    "v1.9.0-bridge",
    "v1.9.1-seq-fix",
    "v1.9.1-query-fix",
    "v1.9.2-bridge-fee-endblock",
    "v1.9.3-bridge-fee-burn",
    "v1.9.4-bridge-attestor-fix",
    "v1.9.5-bridge-no-pow",
    "v1.9.7-bridge-replay",
    "v1.9.9-retention",
    "v1.10.0-bridge-refactor",
    "v1.10.0-remove-ibc",
    "v1.10.3-sdk-bloat",
    "v1.10.4-restore-sdk",
]


def _http_get_json(url: str, timeout: int = 5) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "mirage-verify/1.9.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))


def _find_miraged() -> str:
    candidates = [
        "/opt/mirage/blockchain/miraged",  # inside container (new structure)
        "/opt/mirage/blockchain/bin/miraged",  # inside container (old structure)
        str(Path(__file__).resolve().parents[1] / "blockchain" / "miraged"),  # repo checkout (new)
        str(Path(__file__).resolve().parents[1] / "blockchain" / "bin" / "miraged"),  # repo checkout (old)
        "miraged",
    ]
    for c in candidates:
        if c == "miraged":
            return c
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return "miraged"


def _resolve_node_home(home_dir: Path) -> Path:
    # Home can be either ~/.mirage (base) or ~/.mirage/node (node home).
    return home_dir if home_dir.name == "node" else home_dir / "node"


def _is_miraged_running() -> bool:
    try:
        p = subprocess.run(["pgrep", "-f", "miraged start"], capture_output=True, text=True, check=False)
        return p.returncode == 0
    except Exception:
        return False


def _stop_miraged() -> bool:
    if not _is_miraged_running():
        return False
    subprocess.run(["pkill", "-TERM", "-f", "miraged start"], check=False)
    for _ in range(30):
        if not _is_miraged_running():
            return True
        time.sleep(1)
    subprocess.run(["pkill", "-KILL", "-f", "miraged start"], check=False)
    return not _is_miraged_running()


def _restart_miraged(node_home: Path) -> bool:
    # Prefer tmux session if present
    try:
        if subprocess.run(["tmux", "has-session", "-t", "mirage"], check=False).returncode == 0:
            cmd = f'miraged start --home "{node_home}"'
            subprocess.run(["tmux", "send-keys", "-t", "mirage:node", cmd, "C-m"], check=False)
            return True
    except Exception:
        pass
    # Fallback: start in background
    try:
        subprocess.Popen(["miraged", "start", "--home", str(node_home)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _run_json(cmd: list[str]) -> dict:
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr}".strip())
    out = p.stdout.strip()
    if not out:
        raise RuntimeError(f"command returned empty stdout: {' '.join(cmd)}")
    return json.loads(out)


def _as_int(v: Any) -> int:
    if isinstance(v, bool):
        raise ValueError(f"not an int: {v!r}")
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if s.isdigit():
            return int(s)
    raise ValueError(f"not an int: {v!r}")


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "false"):
            return s == "true"
    raise ValueError(f"not a bool: {v!r}")


def _as_float(v: Any) -> float:
    if isinstance(v, bool):
        raise ValueError(f"not a float: {v!r}")
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        return float(s)
    raise ValueError(f"not a float: {v!r}")


def _require_keys(obj: dict, keys: list[str], ctx: str, failures: list[str]) -> None:
    for k in keys:
        if k not in obj:
            failures.append(f"{ctx}: missing required key {k!r}")


def _check_equal(label: str, got: Any, expected: Any, failures: list[str]) -> None:
    if got != expected:
        failures.append(f"{label} expected {expected!r}, got {got!r}")


def _read_text_if_exists(path: Path) -> str | None:
    try:
        if path.exists():
            return path.read_text()
    except Exception:
        return None
    return None


def _extract_toml_string_value(text: str, key: str) -> str | None:
    pat = re.compile(rf'^\s*{re.escape(key)}\s*=\s*"(.*)"\s*$')
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = pat.match(s)
        if m:
            return m.group(1)
    return None


def _expected_core_params_v190() -> dict[str, Any]:
    return {
        "mint_interval": 200,
        "mint_quantity": 350_000_000,
        "mint_dynamic_credit_cap": 25,
        "mint_dynamic_split": 0.5,
        "min_difficulty": 10,
        "pow_message_window": 20,
        "pow_message_limit": 15,
        "pow_calm_period_definition": 10,
        "pow_calm_sequence_threshold": 100,
        "block_hash_window": 10,
        "pow_difficulty_allowance": 2,
        "min_username_size": 3,
        "max_username_size": 30,
        "min_topic_size": 2,
        "max_topic_size": 35,
        "subscription_period": 43200,
        "subscription_reserve_percent": 80,
        "relay_min_gas_price": 5000,
        "relay_max_gas_fee": 500_000_000,
        "max_envelope_age": 60,
        "bridge_attestation_threshold": 6667,
        # bridge_fee is now per-chain in BridgeChainConfig.fee
    }


def _expected_tiers_v190() -> list[dict[str, Any]]:
    return [
        {
            "period_fee": 0,
            "max_followed_mods": 5,
            "max_followed_users": 25,
            "max_followed_topics": 50,
            "max_blocked_users": 10,
            "max_blocked_posts": 25,
            "max_quality_posts": 0,
            "max_title_length": 130,
            "max_content_length": 1000,
            "editing_time_mins": 10,
            "archive_duration_days": 30,
            "vote_weight": 1.0,
            "award_permissions": 0,
            "eligible_for_mod": False,
            "can_change_name": False,
            "can_have_biography": False,
            "can_have_avatar": False,
            "can_have_banner": False,
        },
        {
            "period_fee": 100_000_000_000,
            "max_followed_mods": 10,
            "max_followed_users": 125,
            "max_followed_topics": 250,
            "max_blocked_users": 125,
            "max_blocked_posts": 100,
            "max_quality_posts": 0,
            "max_title_length": 165,
            "max_content_length": 2000,
            "editing_time_mins": 60,
            "archive_duration_days": 90,
            "vote_weight": 1.15,
            "award_permissions": 1,
            "eligible_for_mod": False,
            "can_change_name": True,
            "can_have_biography": True,
            "can_have_avatar": True,
            "can_have_banner": True,
        },
        {
            "period_fee": 200_000_000_000,
            "max_followed_mods": 25,
            "max_followed_users": 500,
            "max_followed_topics": 500,
            "max_blocked_users": 500,
            "max_blocked_posts": 200,
            "max_quality_posts": 50,
            "max_title_length": 200,
            "max_content_length": 5000,
            "editing_time_mins": 360,
            "archive_duration_days": 180,
            "vote_weight": 1.30,
            "award_permissions": 2,
            "eligible_for_mod": True,
            "can_change_name": True,
            "can_have_biography": True,
            "can_have_avatar": True,
            "can_have_banner": True,
        },
        {
            "period_fee": 300_000_000_000,
            "max_followed_mods": 50,
            "max_followed_users": 1000,
            "max_followed_topics": 1000,
            "max_blocked_users": 1000,
            "max_blocked_posts": 500,
            "max_quality_posts": 100,
            "max_title_length": 250,
            "max_content_length": 25000,
            "editing_time_mins": 720,
            "archive_duration_days": 365,
            "vote_weight": 1.45,
            "award_permissions": 3,
            "eligible_for_mod": True,
            "can_change_name": True,
            "can_have_biography": True,
            "can_have_avatar": True,
            "can_have_banner": True,
        },
    ]


def _fmt_value(v: Any) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        if v >= 1_000_000_000_000:
            return f"{v:,} ({v // 1_000_000_000_000}T umirage)"
        elif v >= 1_000_000_000:
            return f"{v:,} ({v // 1_000_000_000}B umirage)"
        elif v >= 1_000_000:
            return f"{v:,} ({v // 1_000_000} MIRAGE)"
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v}"
    return str(v)


def check_binary_version(miraged: str, failures: list[str], warnings: list[str]) -> str | None:
    """Check that miraged binary version matches expected version."""
    print("-> Checking binary version...")
    try:
        p = subprocess.run([miraged, "version"], capture_output=True, text=True, check=False)
        version = p.stdout.strip() or p.stderr.strip()
        if version.startswith(EXPECTED_VERSION_PREFIX):
            print(f"   [OK] Binary version: {version}")
            return version
        else:
            print(f"   [FAIL] Binary version: {version} (expected {EXPECTED_VERSION_PREFIX}*)")
            failures.append(f"Binary version {version} does not match expected {EXPECTED_VERSION_PREFIX}")
            return version
    except Exception as e:
        print(f"   [FAIL] Cannot check version: {e}")
        failures.append(f"Cannot check binary version: {e}")
        return None


def check_bridge_commands(miraged: str, failures: list[str], warnings: list[str]) -> None:
    """Check that new bridge CLI commands exist."""
    print("\n-> Checking bridge CLI commands...")
    
    # Check query commands exist (should show help, not error)
    query_cmds = [
        ([miraged, "q", "bridge", "--help"], "q bridge"),
        ([miraged, "q", "bridge", "status", "--help"], "q bridge status"),
        ([miraged, "q", "bridge", "config", "--help"], "q bridge config"),
    ]
    
    for cmd, name in query_cmds:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, check=False)
            # Help should return 0 or show usage
            if p.returncode == 0 or "usage" in p.stdout.lower() or "usage" in p.stderr.lower():
                print(f"   [OK] {name}")
            else:
                print(f"   [FAIL] {name}: command not found")
                failures.append(f"Bridge command '{name}' not available")
        except Exception as e:
            print(f"   [FAIL] {name}: {e}")
            failures.append(f"Bridge command '{name}' check failed: {e}")
    
    # Check tx commands exist
    tx_cmds = [
        ([miraged, "tx", "bridge", "--help"], "tx bridge"),
    ]
    
    for cmd, name in tx_cmds:
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if p.returncode == 0 or "usage" in p.stdout.lower() or "usage" in p.stderr.lower():
                print(f"   [OK] {name}")
            else:
                print(f"   [FAIL] {name}: command not found")
                failures.append(f"Bridge command '{name}' not available")
        except Exception as e:
            print(f"   [FAIL] {name}: {e}")
            failures.append(f"Bridge command '{name}' check failed: {e}")


def check_node_health(rpc: str, failures: list[str], warnings: list[str]) -> tuple[str | None, str | None]:
    print("\n-> Checking node health...")
    try:
        status = _http_get_json(f"{rpc}/status")
        result = status.get("result", {})
        sync_info = result.get("sync_info", {})
        node_info = result.get("node_info", {})
        latest_height = sync_info.get("latest_block_height", "unknown")
        latest_time = sync_info.get("latest_block_time", "")
        catching_up = sync_info.get("catching_up", False)
        network = node_info.get("network", "unknown")
        tm_version = node_info.get("version", "unknown")

        print(f"   [OK] RPC reachable")
        print(f"   [OK] Network: {network}")
        print(f"   [OK] Tendermint: {tm_version}")
        print(f"   [OK] Height: {latest_height}")
        if latest_time:
            print(f"   [OK] Block time: {latest_time}")
        if catching_up:
            warnings.append("node is catching up (syncing)")
            print("   [WARN] Node is catching up")

        chain_id = network if isinstance(network, str) else None
        return chain_id, str(latest_height) if latest_height is not None else None
    except urllib.error.URLError as e:
        failures.append(f"RPC unreachable: {e}")
    except Exception as e:
        failures.append(f"RPC check failed: {e}")
    return None, None


def check_all_upgrades(miraged: str, rpc: str, warnings: list[str]) -> dict[str, int]:
    """Check status of all registered upgrades. Returns dict of upgrade_name -> applied_height (0 if not applied)."""
    print("\n-> Checking all upgrade statuses...")
    results = {}
    
    for upgrade_name in ALL_UPGRADES:
        try:
            applied = _run_json([miraged, "q", "upgrade", "applied", upgrade_name, "--node", rpc, "-o", "json"])
            h = applied.get("height", "0")
            height = _as_int(h)
            results[upgrade_name] = height
            if height > 0:
                print(f"   [OK] {upgrade_name}: applied @ height {height}")
            else:
                print(f"   [--] {upgrade_name}: not applied")
        except Exception:
            results[upgrade_name] = 0
            print(f"   [--] {upgrade_name}: not applied")
    
    # Check current plan
    try:
        plan = _run_json([miraged, "q", "upgrade", "plan", "--node", rpc, "-o", "json"])
        p = plan.get("plan")
        if p and isinstance(p, dict) and p.get("name"):
            plan_name = p.get("name", "")
            plan_height = p.get("height", "?")
            print(f"\n   [PENDING] Current plan: {plan_name} @ height {plan_height}")
    except Exception:
        pass
    
    return results


def check_upgrade_state(miraged: str, rpc: str, phase: str, upgrade_name: str, failures: list[str]) -> None:
    print(f"\n-> Checking upgrade state for {upgrade_name}...")
    applied_height: int | None = None
    try:
        applied = _run_json([miraged, "q", "upgrade", "applied", upgrade_name, "--node", rpc, "-o", "json"])
        h = applied.get("height", "0")
        applied_height = _as_int(h)
    except Exception:
        applied_height = None

    plan: dict | None = None
    plan_err: str | None = None
    try:
        plan = _run_json([miraged, "q", "upgrade", "plan", "--node", rpc, "-o", "json"])
    except Exception as e:
        plan_err = str(e)

    if phase == "post":
        if applied_height is None or applied_height <= 0:
            print(f"   [FAIL] upgrade {upgrade_name} not applied")
            failures.append(f"upgrade {upgrade_name} is not applied (or cannot be queried)")
        else:
            print(f"   [OK] upgrade applied: {upgrade_name} @ height {applied_height}")
        if plan is not None and plan.get("plan") not in (None, {}):
            failures.append(f"upgrade plan still present after upgrade: {plan.get('plan')!r}")
    else:
        if plan is None:
            print(f"   [FAIL] upgrade plan not found")
            failures.append(f"upgrade plan query failed (pre phase requires a plan): {plan_err}")
            return
        p = plan.get("plan", plan)
        name = p.get("name", "")
        if name != upgrade_name:
            print(f"   [FAIL] upgrade plan name: expected {upgrade_name}, got {name}")
            failures.append(f"upgrade plan name expected {upgrade_name!r}, got {name!r}")
        else:
            print(f"   [OK] upgrade plan: {name}")


def check_sdk_modules_restored(miraged: str, failures: list[str], warnings: list[str]) -> None:
    """Verify that SDK modules removed in v1.10.3-sdk-bloat are present again."""
    print("\n-> Checking SDK modules restored...")

    query_modules = ["authz", "feegrant", "group", "epochs", "circuit", "evidence", "mint"]
    tx_modules = ["authz", "feegrant", "group"]

    try:
        q_help = subprocess.run([miraged, "q", "--help"], capture_output=True, text=True, check=False)
        q_output = (q_help.stdout + q_help.stderr).lower()
    except Exception as e:
        failures.append(f"cannot run '{miraged} q --help': {e}")
        return

    for mod in query_modules:
        if f"\n  {mod}" in q_output or f"\n\t{mod}" in q_output or f"  {mod} " in q_output:
            print(f"   [OK] q {mod}: command present")
        else:
            print(f"   [FAIL] q {mod}: command missing")
            failures.append(f"SDK module '{mod}' not present in query commands")

    try:
        tx_help = subprocess.run([miraged, "tx", "--help"], capture_output=True, text=True, check=False)
        tx_output = (tx_help.stdout + tx_help.stderr).lower()
    except Exception as e:
        warnings.append(f"cannot run '{miraged} tx --help': {e}")
        return

    for mod in tx_modules:
        if f"\n  {mod}" in tx_output or f"\n\t{mod}" in tx_output or f"  {mod} " in tx_output:
            print(f"   [OK] tx {mod}: command present")
        else:
            print(f"   [WARN] tx {mod}: command missing")
            warnings.append(f"tx {mod} command missing after restore (verify module wiring)")


def check_export_command(miraged: str, home_dir: Path, failures: list[str]) -> None:
    """Ensure export command is available and produces genesis (stops/starts node)."""
    print("\n-> Checking genesis export (stopping node)...")
    node_home = _resolve_node_home(home_dir)
    try:
        genesis_path = node_home / "config" / "genesis.json"
        if not genesis_path.exists():
            failures.append(f"export failed: missing genesis at {genesis_path}")
            print("   [FAIL] export failed (missing genesis)")
            return
        cmd = [miraged, "export", "--home", str(node_home)]
        was_running = _is_miraged_running()
        if was_running:
            stopped = _stop_miraged()
            if not stopped:
                failures.append("export failed: could not stop miraged")
                print("   [FAIL] export failed (could not stop miraged)")
                return
        with tempfile.NamedTemporaryFile(prefix="mirage-export-", suffix=".json") as tmp:
            cmd = cmd + ["--output-document", tmp.name]
            p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
            if p.returncode != 0:
                err = p.stderr.strip()
                if "failed to initialize database" in err or "resource temporarily unavailable" in err:
                    msg = "export failed: database locked (stop miraged or use a stopped data copy)"
                    print("   [FAIL] export failed (database locked)")
                    failures.append(msg)
                    return
                print("   [FAIL] export failed")
                failures.append(f"export failed: {err}")
                return
            tmp.flush()
            tmp.seek(0)
            raw = tmp.read()
            if not raw.strip():
                print("   [FAIL] export output is empty")
                failures.append("export output is empty")
                return
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                print("   [FAIL] export output is not UTF-8")
                failures.append("export output is not UTF-8")
                return
            try:
                json.loads(text)
            except json.JSONDecodeError as err:
                print("   [FAIL] export output is not JSON")
                failures.append(f"export output is not JSON: {err}")
                return
            print("   [OK] export succeeded")
        if was_running:
            restarted = _restart_miraged(node_home)
            if not restarted:
                failures.append("export check failed: could not restart miraged")
                print("   [FAIL] export check failed (could not restart miraged)")
                return
    except Exception as e:
        failures.append(f"export command check failed: {e}")


def fetch_core_params(miraged: str, rpc: str) -> dict:
    return _run_json([miraged, "q", "core", "params", "--node", rpc, "-o", "json"])


def check_core_params_exhaustive(core: dict, failures: list[str]) -> dict:
    print("\n-> Checking core params...")
    expected = _expected_core_params_v190()

    must_have = list(expected.keys()) + ["tiers", "bridge_chains"]
    _require_keys(core, must_have, "core params", failures)

    for k, v_exp in expected.items():
        if k not in core:
            print(f"   [FAIL] {k}: MISSING")
            continue
        try:
            if isinstance(v_exp, float):
                got = _as_float(core[k])
                if abs(got - v_exp) < 1e-9:
                    print(f"   [OK] {k}: {got}")
                else:
                    print(f"   [FAIL] {k}: expected {v_exp}, got {got}")
                    failures.append(f"core params.{k} expected {v_exp!r}, got {got!r}")
            else:
                got = _as_int(core[k])
                if got == int(v_exp):
                    print(f"   [OK] {k}: {_fmt_value(got)}")
                else:
                    print(f"   [FAIL] {k}: expected {_fmt_value(v_exp)}, got {_fmt_value(got)}")
                    failures.append(f"core params.{k} expected {v_exp!r}, got {got!r}")
        except Exception as e:
            print(f"   [FAIL] {k}: invalid value {core[k]!r}")
            failures.append(f"core params.{k} invalid value {core[k]!r}: {e}")

    print("\n   Tiers:")
    tier_names = ["Free", "Trusted", "Established", "Distinguished"]
    tiers = core.get("tiers")
    if isinstance(tiers, list):
        if len(tiers) != 4:
            print(f"   [FAIL] expected 4 tiers, got {len(tiers)}")
            failures.append(f"core params.tiers expected exactly 4 tiers, got {len(tiers)}")
        exp_tiers = _expected_tiers_v190()
        for i in range(min(len(tiers), 4)):
            t = tiers[i]
            name = tier_names[i] if i < len(tier_names) else f"Tier{i}"
            if not isinstance(t, dict):
                print(f"   [FAIL] tiers[{i}] ({name}): expected object")
                failures.append(f"core params.tiers[{i}] expected object, got {type(t)}")
                continue
            exp = exp_tiers[i]
            tier_ok = True
            tier_errors = []
            for field, v_exp in exp.items():
                if field not in t:
                    tier_errors.append(f"missing {field}")
                    tier_ok = False
                    continue
                try:
                    if isinstance(v_exp, bool):
                        got = _as_bool(t[field])
                        if got != v_exp:
                            tier_errors.append(f"{field}={got}")
                            tier_ok = False
                    elif isinstance(v_exp, float):
                        got = _as_float(t[field])
                        if abs(got - v_exp) > 1e-9:
                            tier_errors.append(f"{field}={got}")
                            tier_ok = False
                    else:
                        got = _as_int(t[field])
                        if got != int(v_exp):
                            tier_errors.append(f"{field}={got}")
                            tier_ok = False
                except Exception as e:
                    tier_errors.append(f"{field}: invalid")
                    tier_ok = False

            period_fee = t.get("period_fee", 0)
            if tier_ok:
                print(f"   [OK] Tier {i} ({name}): fee={_fmt_value(period_fee)}, {len(exp)} fields OK")
            else:
                print(
                    f"   [FAIL] Tier {i} ({name}): {', '.join(tier_errors[:3])}{'...' if len(tier_errors) > 3 else ''}"
                )
                for err in tier_errors:
                    failures.append(f"core params.tiers[{i}].{err}")

    print("\n   Bridge chains (attested only):")
    bridge_chains = core.get("bridge_chains")
    if bridge_chains is None:
        print("   [FAIL] bridge_chains is None")
        failures.append("core params.bridge_chains must be an array (empty is valid), got None")
    elif not isinstance(bridge_chains, list):
        print(f"   [FAIL] bridge_chains expected list, got {type(bridge_chains)}")
        failures.append(f"core params.bridge_chains expected list, got {type(bridge_chains)}")
    elif len(bridge_chains) == 0:
        print("   [FAIL] bridge_chains: [] (empty - expected at least Solana)")
        failures.append("bridge_chains is empty, expected at least Solana")
    else:
        print(f"   [OK] bridge_chains: {len(bridge_chains)} chain(s)")
        solana_found = False
        for idx, ch in enumerate(bridge_chains):
            print(f"   [DEBUG] bridge_chains[{idx}] raw={ch!r}")
            if not isinstance(ch, dict):
                print(f"   [FAIL] bridge_chains[{idx}] expected object, got {type(ch)}")
                failures.append(f"core params.bridge_chains[{idx}] expected object, got {type(ch)}")
                continue

            chain_id = ch.get("chain_id", "?")
            enabled = None
            fee = None

            if "enabled" not in ch:
                print(f"   [FAIL] {chain_id}: missing enabled")
                failures.append(f"bridge_chains[{idx}] missing enabled")
            else:
                try:
                    enabled = _as_bool(ch.get("enabled"))
                except Exception as e:
                    print(f"   [FAIL] {chain_id}: invalid enabled {ch.get('enabled')!r}")
                    failures.append(f"bridge_chains[{idx}].enabled invalid: {e}")

            if "fee" not in ch:
                print(f"   [FAIL] {chain_id}: missing fee")
                failures.append(f"bridge_chains[{idx}] missing fee")
            else:
                try:
                    fee = _as_int(ch.get("fee"))
                except Exception as e:
                    print(f"   [FAIL] {chain_id}: invalid fee {ch.get('fee')!r}")
                    failures.append(f"bridge_chains[{idx}].fee invalid: {e}")

            if enabled is None or fee is None:
                print(f"   [FAIL] {chain_id}: invalid bridge config")
                continue

            status = "enabled" if enabled else "disabled"
            fee_str = f"{fee:,} ({fee // 1_000_000} MIRAGE)" if fee >= 1_000_000 else f"{fee:,}"
            print(f"      - {chain_id}: {status}, fee: {fee_str}")

            # Verify Solana config
            if chain_id == "solana":
                solana_found = True
                if not enabled:
                    print(f"   [FAIL] Solana bridge is disabled")
                    failures.append("bridge_chains: Solana is disabled")
                if fee != 500_000_000:
                    print(f"   [FAIL] Solana fee expected 500,000,000, got {fee}")
                    failures.append(f"bridge_chains: Solana fee expected 500_000_000, got {fee}")

        if not solana_found:
            print("   [FAIL] Solana not found in bridge_chains")
            failures.append("bridge_chains: Solana chain not configured")

    return core


def fetch_bridge_status(miraged: str, rpc: str) -> dict:
    return _run_json([miraged, "q", "bridge", "status", "--node", rpc, "-o", "json"])


def fetch_bridge_config(miraged: str, rpc: str) -> dict:
    return _run_json([miraged, "q", "bridge", "config", "--node", rpc, "-o", "json"])


def check_bridge_queries_strict(core: dict, status: dict, cfg: dict, failures: list[str]) -> None:
    print("\n-> Checking bridge queries...")

    print("   Status (q bridge status):")
    enabled_chains = status.get("enabled_chains", [])
    if isinstance(enabled_chains, list):
        print(f"   [OK] enabled_chains: {len(enabled_chains)}")
    else:
        print(f"   [FAIL] enabled_chains: expected list")
        failures.append(f"bridge status.enabled_chains expected list, got {type(enabled_chains)}")

    pending = status.get("pending_attestations_count", 0)
    try:
        pending_int = _as_int(pending)
        print(f"   [OK] pending_attestations: {pending_int}")
    except Exception as e:
        print(f"   [FAIL] pending_attestations: invalid")
        failures.append(f"bridge status.pending_attestations_count invalid: {e}")

    print("\n   Config (q bridge config):")
    chains = cfg.get("chains", [])
    if isinstance(chains, list):
        print(f"   [OK] chains: {len(chains)}")
    else:
        print(f"   [FAIL] chains: expected list")
        failures.append(f"bridge config.chains expected list, got {type(chains)}")

    try:
        threshold = _as_int(cfg.get("attestation_threshold", 0))
        if threshold == 6667:
            print(f"   [OK] attestation_threshold: {threshold} ({threshold/100:.2f}%)")
        else:
            print(f"   [FAIL] attestation_threshold: expected 6667, got {threshold}")
            failures.append(f"bridge config.attestation_threshold expected 6667, got {threshold}")
    except Exception as e:
        print(f"   [FAIL] attestation_threshold: invalid")
        failures.append(f"bridge config.attestation_threshold invalid: {e}")

    # Note: bridge_fee is now per-chain in BridgeChainConfig.fee, not global

    print("\n   Cross-check vs core params:")
    try:
        core_threshold = _as_int(core.get("bridge_attestation_threshold", 0))
        cfg_threshold = _as_int(cfg.get("attestation_threshold", 0))
        if core_threshold == cfg_threshold:
            print(f"   [OK] attestation_threshold: {core_threshold} (matches)")
        else:
            print(f"   [FAIL] threshold mismatch: core={core_threshold}, config={cfg_threshold}")
            failures.append(f"attestation_threshold mismatch")
    except Exception as e:
        print(f"   [FAIL] cross-check threshold: {e}")
        failures.append(f"cross-check bridge_attestation_threshold failed: {e}")


def fetch_gov_params(miraged: str, rpc: str) -> dict:
    out = _run_json([miraged, "q", "gov", "params", "--node", rpc, "-o", "json"])
    return out.get("params", out)


def check_gov_params_strict(gp: dict, failures: list[str]) -> None:
    print("\n-> Checking gov params...")

    def _coin_amount(coins: Any, denom: str) -> int:
        if not isinstance(coins, list):
            raise ValueError("expected list of coins")
        for c in coins:
            if isinstance(c, dict) and c.get("denom") == denom:
                return _as_int(c.get("amount", "0"))
        return 0

    try:
        min_amt = _coin_amount(gp.get("min_deposit", []), "umirage")
        expected_min = 500_000_000_000
        if min_amt == expected_min:
            print(f"   [OK] min_deposit: {min_amt:,} ({min_amt // 1_000_000:,} MIRAGE)")
        else:
            print(f"   [FAIL] min_deposit: expected {expected_min:,}, got {min_amt:,}")
            failures.append(f"gov min_deposit expected {expected_min}, got {min_amt}")
    except Exception as e:
        print(f"   [FAIL] min_deposit: {e}")
        failures.append(f"gov min_deposit invalid: {e}")

    try:
        exp_amt = _coin_amount(gp.get("expedited_min_deposit", []), "umirage")
        expected_exp = 1_000_000_000_000
        if exp_amt == expected_exp:
            print(f"   [OK] expedited_min_deposit: {exp_amt:,} ({exp_amt // 1_000_000:,} MIRAGE)")
        else:
            print(f"   [FAIL] expedited_min_deposit: expected {expected_exp:,}, got {exp_amt:,}")
            failures.append(f"gov expedited_min_deposit expected {expected_exp}, got {exp_amt}")
    except Exception as e:
        print(f"   [FAIL] expedited_min_deposit: {e}")
        failures.append(f"gov expedited_min_deposit invalid: {e}")

    for k in ["voting_period", "max_deposit_period", "quorum", "threshold", "veto_threshold"]:
        if k in gp:
            print(f"   [OK] {k}: {gp[k]}")
        else:
            print(f"   [FAIL] {k}: MISSING")
            failures.append(f"gov params: missing key {k!r}")


def fetch_difficulty(miraged: str, rpc: str) -> dict:
    return _run_json([miraged, "q", "core", "difficulty", "--node", rpc, "-o", "json"])


def check_difficulty(d: dict, failures: list[str]) -> None:
    print("\n-> Checking difficulty...")
    _require_keys(d, ["current_difficulty"], "core difficulty", failures)
    try:
        cur = _as_int(d.get("current_difficulty", 0))
        if cur <= 0:
            print(f"   [FAIL] current_difficulty: {cur} (must be > 0)")
            failures.append(f"current_difficulty must be > 0, got {cur}")
        else:
            print(f"   [OK] current_difficulty: {cur}")
    except Exception as e:
        print(f"   [FAIL] current_difficulty: {e}")
        failures.append(f"core difficulty invalid: {e}")


def check_python_protobuf_definitions(failures: list[str], warnings: list[str]) -> None:
    """Check that Python protobuf definitions are complete and importable."""
    print("\n-> Checking Python protobuf definitions...")
    
    try:
        from shared import datatypes
        print("   [OK] shared.datatypes imported")
    except ImportError as e:
        print(f"   [WARN] Cannot import shared.datatypes: {e}")
        warnings.append(f"Cannot import shared.datatypes: {e}")
        return
    
    # Check all required message classes exist
    required_classes = [
        # Transaction messages
        "MsgPost",
        "MsgEdit",
        "MsgVote",
        "MsgSetUsername",
        "MsgFollowModerator",
        "MsgUnfollowModerator",
        "MsgFollowUser",
        "MsgUnfollowUser",
        "MsgFollowTopic",
        "MsgUnfollowTopic",
        "MsgBlockPost",
        "MsgUnblockPost",
        "MsgBlockUser",
        "MsgUnblockUser",
        "MsgDelete",
        "MsgSendTokens",
        "MsgSetLevel",
        "MsgUpgradeLevel",
        "MsgSetAutoRenewal",
        "MsgBridgeBurn",
        "MsgBridgeAttestBurned",
        "MsgBridgeAttestBurnedResponse",
        "MsgBridgeAttestMinted",
        "MsgBridgeAttestMintedResponse",
        # Config/params messages
        "TierConfig",
        "BridgeChainConfig",
        "Params",
        "MsgUpdateParams",
        # Query messages
        "QueryParamsRequest",
        "QueryParamsResponse",
        "QueryDifficultyRequest",
        "QueryDifficultyResponse",
    ]
    
    missing = []
    for cls_name in required_classes:
        if hasattr(datatypes, cls_name):
            cls = getattr(datatypes, cls_name)
            if cls is not None:
                continue
        missing.append(cls_name)
    
    if missing:
        print(f"   [FAIL] Missing classes: {', '.join(missing)}")
        failures.append(f"datatypes.py missing classes: {', '.join(missing)}")
    else:
        print(f"   [OK] All {len(required_classes)} message classes present")
    
    # Check Params has all required fields
    try:
        params_cls = datatypes.Params
        # Create empty instance to check fields
        p = params_cls()
        required_param_fields = [
            "min_difficulty",
            "pow_message_window",
            "pow_message_limit",
            "mint_interval",
            "mint_quantity",
            "subscription_period",
            "max_envelope_age",
            "bridge_attestation_threshold",
            # bridge_fee removed - now per-chain in BridgeChainConfig.fee
        ]
        
        # Check if field descriptors exist
        descriptor = params_cls.DESCRIPTOR
        field_names = [f.name for f in descriptor.fields]
        
        missing_fields = [f for f in required_param_fields if f not in field_names]
        if missing_fields:
            print(f"   [FAIL] Params missing fields: {', '.join(missing_fields)}")
            failures.append(f"Params proto missing fields: {', '.join(missing_fields)}")
        else:
            print(f"   [OK] Params has all required fields")
        
        # Check bridge_chains is a repeated field
        bridge_chains_field = None
        for f in descriptor.fields:
            if f.name == "bridge_chains":
                bridge_chains_field = f
                break
        
        if bridge_chains_field is None:
            print("   [FAIL] Params.bridge_chains field missing")
            failures.append("Params proto missing bridge_chains field")
        elif bridge_chains_field.label != 3:  # LABEL_REPEATED = 3
            print("   [FAIL] Params.bridge_chains should be repeated")
            failures.append("Params.bridge_chains should be repeated field")
        else:
            print("   [OK] Params.bridge_chains is repeated")
            
    except Exception as e:
        print(f"   [FAIL] Cannot verify Params fields: {e}")
        failures.append(f"Cannot verify Params proto fields: {e}")
    
    # Check BridgeChainConfig has required fields
    try:
        bcc_cls = datatypes.BridgeChainConfig
        descriptor = bcc_cls.DESCRIPTOR
        field_names = [f.name for f in descriptor.fields]
        
        required_bcc_fields = ["chain_id", "enabled", "fee"]
        missing_bcc = [f for f in required_bcc_fields if f not in field_names]
        if missing_bcc:
            print(f"   [FAIL] BridgeChainConfig missing: {', '.join(missing_bcc)}")
            failures.append(f"BridgeChainConfig missing fields: {', '.join(missing_bcc)}")
        else:
            print(f"   [OK] BridgeChainConfig has required fields (chain_id, enabled, fee)")
    except Exception as e:
        print(f"   [FAIL] Cannot verify BridgeChainConfig: {e}")
        failures.append(f"Cannot verify BridgeChainConfig proto: {e}")
    
    # Check MsgBridgeAttestBurned has required fields (used by orchestrator for inbound)
    try:
        attest_cls = datatypes.MsgBridgeAttestBurned
        descriptor = attest_cls.DESCRIPTOR
        field_names = [f.name for f in descriptor.fields]
        
        required_attest_fields = ["validator", "source_chain", "burn_id", "mirage_recipient", "amount"]
        missing_attest = [f for f in required_attest_fields if f not in field_names]
        if missing_attest:
            print(f"   [FAIL] MsgBridgeAttestBurned missing: {', '.join(missing_attest)}")
            failures.append(f"MsgBridgeAttestBurned missing fields: {', '.join(missing_attest)}")
        else:
            print(f"   [OK] MsgBridgeAttestBurned has required fields")
    except Exception as e:
        print(f"   [FAIL] Cannot verify MsgBridgeAttestBurned: {e}")
        failures.append(f"Cannot verify MsgBridgeAttestBurned proto: {e}")
    
    # Check MsgBridgeAttestMinted has required fields (used by orchestrator for outbound)
    try:
        attest_cls = datatypes.MsgBridgeAttestMinted
        descriptor = attest_cls.DESCRIPTOR
        field_names = [f.name for f in descriptor.fields]
        
        required_attest_fields = ["validator", "burn_id", "destination_chain", "destination_tx"]
        missing_attest = [f for f in required_attest_fields if f not in field_names]
        if missing_attest:
            print(f"   [FAIL] MsgBridgeAttestMinted missing: {', '.join(missing_attest)}")
            failures.append(f"MsgBridgeAttestMinted missing fields: {', '.join(missing_attest)}")
        else:
            print(f"   [OK] MsgBridgeAttestMinted has required fields")
    except Exception as e:
        print(f"   [FAIL] Cannot verify MsgBridgeAttestMinted: {e}")
        failures.append(f"Cannot verify MsgBridgeAttestMinted proto: {e}")
    
    # Check MsgBridgeBurn has required fields (user bridge transactions)
    try:
        burn_cls = datatypes.MsgBridgeBurn
        descriptor = burn_cls.DESCRIPTOR
        field_names = [f.name for f in descriptor.fields]
        
        required_burn_fields = ["destination_chain", "destination_address", "amount"]
        missing_burn = [f for f in required_burn_fields if f not in field_names]
        if missing_burn:
            print(f"   [FAIL] MsgBridgeBurn missing: {', '.join(missing_burn)}")
            failures.append(f"MsgBridgeBurn missing fields: {', '.join(missing_burn)}")
        else:
            print(f"   [OK] MsgBridgeBurn has required fields")
    except Exception as e:
        print(f"   [FAIL] Cannot verify MsgBridgeBurn: {e}")
        failures.append(f"Cannot verify MsgBridgeBurn proto: {e}")


def check_orchestrator_config(home_dir: Path, failures: list[str], warnings: list[str]) -> None:
    """Check orchestrator configuration if enabled."""
    print("\n-> Checking orchestrator config...")
    
    orchestrator_env = home_dir / "env" / "orchestrator.env"
    if not orchestrator_env.exists():
        print("   [INFO] orchestrator.env not found (orchestrator not configured)")
        return
    
    try:
        content = orchestrator_env.read_text()
    except Exception as e:
        print(f"   [WARN] Cannot read orchestrator.env: {e}")
        warnings.append(f"Cannot read orchestrator.env: {e}")
        return
    
    # Parse env file
    env_values = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            env_values[key.strip()] = value.strip()
    
    # Check if enabled
    enabled = env_values.get("ORCHESTRATOR_ENABLED", "").lower()
    if enabled not in ("true", "1", "yes"):
        print("   [INFO] Orchestrator disabled (ORCHESTRATOR_ENABLED != true)")
        return
    
    print("   [OK] Orchestrator enabled")
    
    # Check required fields
    required_fields = [
        ("ORCHESTRATOR_SOLANA_PROGRAM_ID", "Solana program ID"),
        ("ORCHESTRATOR_SOLANA_RPC", "Solana RPC endpoint"),
        ("ORCHESTRATOR_SOLANA_KEYPAIR", "Solana keypair path"),
    ]
    
    for field, desc in required_fields:
        value = env_values.get(field, "")
        if value:
            # Truncate long values for display
            display_val = value if len(value) <= 40 else value[:37] + "..."
            print(f"   [OK] {field}: {display_val}")
        else:
            print(f"   [FAIL] {field}: not set ({desc})")
            failures.append(f"Orchestrator enabled but {field} not set")
    
    # Check keypair file exists
    keypair_path = env_values.get("ORCHESTRATOR_SOLANA_KEYPAIR", "")
    if keypair_path:
        # Expand ~ and env vars
        keypair_path = os.path.expanduser(keypair_path)
        keypair_path = os.path.expandvars(keypair_path)
        if os.path.exists(keypair_path):
            print(f"   [OK] Keypair file exists")
        else:
            print(f"   [WARN] Keypair file not found: {keypair_path}")
            warnings.append(f"Orchestrator keypair file not found: {keypair_path}")


def check_deploy_migrations(home_dir: Path, failures: list[str], warnings: list[str]) -> None:
    """Check that required v1.9.0 deploy migrations have been applied."""
    print("\n-> Checking deploy migrations...")

    migrations_file = home_dir / "env" / ".migrations"
    if not migrations_file.exists():
        print("   [WARN] .migrations file not found (fresh install?)")
        warnings.append(".migrations file not found - migrations may not have run yet")
        return

    try:
        content = migrations_file.read_text()
    except Exception as e:
        print(f"   [FAIL] Cannot read .migrations: {e}")
        failures.append(f"Cannot read .migrations file: {e}")
        return

    # Required migrations for v1.9.0
    required_migrations = [
        "v1_9_0_indexer_env_rename",
        "v1_9_0_p2p_rate_limiting",
    ]

    for migration_key in required_migrations:
        # Check if migration key appears in the file (format: "key|timestamp|result")
        if migration_key in content:
            # Check if it failed
            for line in content.splitlines():
                if line.startswith(migration_key + "|"):
                    parts = line.split("|")
                    result = parts[2] if len(parts) > 2 else "unknown"
                    if result.startswith("FAILED"):
                        print(f"   [FAIL] {migration_key}: {result}")
                        failures.append(f"Migration {migration_key} failed: {result}")
                    else:
                        print(f"   [OK] {migration_key}: {result}")
                    break
        else:
            print(f"   [WARN] {migration_key}: not applied")
            warnings.append(f"Migration {migration_key} has not been applied")


def check_local_config(home_dir: Path, rpc_chain_id: str | None, failures: list[str], warnings: list[str]) -> None:
    print("\n-> Checking local config...")
    cfg_dir = _resolve_node_home(home_dir) / "config"

    app_toml = cfg_dir / "app.toml"
    if app_toml.exists():
        txt = app_toml.read_text()
        min_gas = _extract_toml_string_value(txt, "minimum-gas-prices")
        if min_gas is None:
            print("   [FAIL] app.toml: minimum-gas-prices missing")
            failures.append("app.toml: missing minimum-gas-prices")
        elif min_gas == REQUIRED_MIN_GAS_PRICE:
            print(f'   [OK] app.toml: minimum-gas-prices = "{min_gas}"')
        else:
            print(f'   [FAIL] app.toml: minimum-gas-prices = "{min_gas}" (expected "{REQUIRED_MIN_GAS_PRICE}")')
            failures.append(f'app.toml minimum-gas-prices expected "{REQUIRED_MIN_GAS_PRICE}", got "{min_gas}"')
    else:
        print(f"   [WARN] app.toml not found")
        warnings.append(f"app.toml not found at {app_toml}")

    for name in ["config.toml", "client.toml", "genesis.json"]:
        p = cfg_dir / name
        if p.exists():
            print(f"   [OK] {name} exists")
        else:
            print(f"   [WARN] {name} not found")
            warnings.append(f"{name} not found at {p}")

    genesis_path = cfg_dir / "genesis.json"
    genesis_chain_id: str | None = None
    if genesis_path.exists():
        try:
            g = json.loads(genesis_path.read_text())
            cid = g.get("chain_id", "")
            if isinstance(cid, str) and cid.strip():
                genesis_chain_id = cid
                print(f"   [OK] genesis chain_id: {cid}")
            else:
                print(f"   [FAIL] genesis chain_id: invalid")
                failures.append(f"genesis.json: invalid chain_id {cid!r}")
        except Exception as e:
            print(f"   [FAIL] genesis.json: {e}")
            failures.append(f"genesis.json parse failed: {e}")

    if rpc_chain_id and genesis_chain_id:
        if rpc_chain_id == genesis_chain_id:
            print(f"   [OK] RPC chain_id matches genesis")
        else:
            print(f"   [FAIL] RPC chain_id ({rpc_chain_id}) != genesis ({genesis_chain_id})")
            failures.append(f"RPC chain-id vs genesis chain_id mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Mirage node upgrade status")
    parser.add_argument("--node", default="http://127.0.0.1:26657", help="CometBFT RPC endpoint")
    parser.add_argument("--home", default=str(Path.home() / ".mirage"), help="Mirage home directory")
    parser.add_argument("--skip-config", action="store_true", help="Skip local config checks")
    parser.add_argument("--phase", choices=["pre", "post"], default="post", help="pre=plan exists, post=applied")
    parser.add_argument("--upgrade", default=UPGRADE_NAME, help=f"Upgrade name to verify (default: {UPGRADE_NAME})")
    parser.add_argument("--list-all", action="store_true", help="List status of all registered upgrades")
    parser.add_argument("--export-check", action="store_true", help="Stop node, run export, restart")
    args = parser.parse_args()

    rpc = args.node.rstrip("/")
    miraged = _find_miraged()
    home_dir = Path(args.home)
    upgrade_name = args.upgrade

    failures: list[str] = []
    warnings: list[str] = []

    print("=" * 72)
    print(f"Verify Mirage Node Upgrade ({datetime.now().isoformat()})")
    print("=" * 72)
    print(f"RPC:     {rpc}")
    print(f"HOME:    {home_dir}")
    print(f"miraged: {miraged}")
    print(f"phase:   {args.phase}")
    print(f"upgrade: {upgrade_name}")
    print()

    # Check binary version first
    check_binary_version(miraged, failures, warnings)
    
    # Check bridge CLI commands exist
    check_bridge_commands(miraged, failures, warnings)

    rpc_chain_id, _ = check_node_health(rpc, failures, warnings)
    
    # Show all upgrade statuses if requested
    if args.list_all:
        check_all_upgrades(miraged, rpc, warnings)
    
    # Check specific upgrade
    check_upgrade_state(miraged, rpc, args.phase, upgrade_name, failures)

    if args.export_check:
        check_export_command(miraged, home_dir, failures)

    if "restore-sdk" in upgrade_name and args.phase == "post":
        check_sdk_modules_restored(miraged, failures, warnings)

    try:
        core = fetch_core_params(miraged, rpc)
        check_core_params_exhaustive(core, failures)
    except Exception as e:
        failures.append(f"failed to fetch/validate core params: {e}")
        core = {}

    try:
        b_status = fetch_bridge_status(miraged, rpc)
        b_cfg = fetch_bridge_config(miraged, rpc)
        if core:
            check_bridge_queries_strict(core, b_status, b_cfg, failures)
    except Exception as e:
        failures.append(f"bridge query failed: {e}")

    try:
        gp = fetch_gov_params(miraged, rpc)
        check_gov_params_strict(gp, failures)
    except Exception as e:
        failures.append(f"failed to fetch/validate gov params: {e}")

    try:
        d = fetch_difficulty(miraged, rpc)
        check_difficulty(d, failures)
    except Exception as e:
        failures.append(f"failed to fetch/validate difficulty: {e}")

    if not args.skip_config:
        check_local_config(home_dir, rpc_chain_id, failures, warnings)
        check_deploy_migrations(home_dir, failures, warnings)
        check_orchestrator_config(home_dir, failures, warnings)
    
    # Check Python protobuf definitions (always run)
    check_python_protobuf_definitions(failures, warnings)

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    if warnings:
        print(f"\n[WARNINGS] ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")
    if failures:
        print(f"\n[FAILURES] ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        print(f"\n[RESULT] FAILED ({len(failures)} error(s), {len(warnings)} warning(s))")
        return 1
    print(f"\n[RESULT] PASSED ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
