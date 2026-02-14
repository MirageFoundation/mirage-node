#!/usr/bin/env python3
"""
Verify Mirage Node Upgrade — strict + exhaustive.

This script is intentionally "no hand-waving":
- It validates EVERY core param field (including every tier field).
- It validates bridge query commands (`miraged q bridge ...`) exist and return consistent data.
- It validates upgrade state (pre vs post) and local config consistency.
- It checks that critical CLI commands are exposed.
- It can optionally verify genesis export with --export-check (stops node, runs export, restarts).
- It shows status of ALL registered upgrades.

v1.10.7 additions (source-level checks):
- Fingerprinting system fully removed (tables, columns, code references)
- safe_error() helper used across all route files + global Flask handler
- Spoiler tag support (||text|| syntax, remarkSpoiler plugin, Spoiler component)
- Server-side inbox unread count (cache, middleware, migration, API sync)
- Seed phrase security (SeedVault with 4 modes: insecure, password, memory, passkey)
- Admin gas fee non-blocking (level >= 100 skip deduction in chain module)
- Balance overflow fix (uvarint64 encoding, useBalance hook)

v1.10.8 additions (source-level checks):
- gRPC staking queries replace CLI subprocess calls (bank.py, chain.py, public.py)
- Node balance tracking (migration v2_0_4, indexer records balance every 200 blocks)
- Network charts: unified layout constants, Total Supply chart, chart label fixes
- Server page: node balance chart, earned vs spent chart, staked balance display
- Deploy migration v1_11_0_backend_env_renames (with full content validation)
- Quest settings renamed to QUESTS_* prefix (env vars + Python constants)
- Reward env vars renamed to QUESTS_ prefix (reward_distributor.py, setup_rewards_pool.py)
- GUNICORN_WORKERS renamed to BACKEND_GUNICORN_WORKERS (gunicorn_config.py)
- Frontend env template cleaned (REACT_APP_API_BASE removed, bake-time note added)
- Donation amount formatting (toLocaleString)

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


# Current release being verified (set via --upgrade or defaults to latest)
# NOTE: UPGRADE_NAME is the last *chain* upgrade (on-chain governance proposal).
# v1.10.8 is a services-only release (Python/JS) — no new chain upgrade.
UPGRADE_NAME = "v1.10.7"
REQUIRED_MIN_GAS_PRICE = "5000umirage"
EXPECTED_VERSION = "v1.10.8"

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
    "v1.10.5",
    "v1.10.7",
]

# Repo root (scripts/ is one level below)
REPO_ROOT = Path(__file__).resolve().parents[1]


def _http_get_json(url: str, timeout: int = 5) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "mirage-verify/1.10.8"})
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
        subprocess.Popen(
            ["miraged", "start", "--home", str(node_home)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
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
        "subscription_reserve_percent": 0.80,
        "relay_min_gas_price": 5000,
        "relay_max_gas_fee": 500_000_000,
        "max_envelope_age": 60,
        "bridge_attestation_threshold": 0.6667,
        "pow_difficulty_step": 0.25,
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
    """Check that miraged binary version starts with the expected version prefix.

    Accepts both exact tags (v1.10.8) and git-describe suffixes (v1.10.8-3-g67679d3)
    since post-tag commits that don't touch Go source produce identical binaries.
    """
    print("-> Checking binary version...")
    try:
        p = subprocess.run([miraged, "version"], capture_output=True, text=True, check=False)
        version = p.stdout.strip() or p.stderr.strip()
        if version == EXPECTED_VERSION:
            print(f"   [OK] Binary version: {version}")
            return version
        elif version.startswith(EXPECTED_VERSION + "-"):
            print(f"   [OK] Binary version: {version} (matches {EXPECTED_VERSION} prefix)")
            return version
        else:
            print(f"   [FAIL] Binary version: {version} (expected {EXPECTED_VERSION} or {EXPECTED_VERSION}-*)")
            failures.append(f"Binary version {version!r} does not match expected {EXPECTED_VERSION!r}")
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


def check_sdk_modules_restored(miraged: str, rpc: str, failures: list[str], warnings: list[str]) -> None:
    """Verify that SDK modules removed in v1.10.3-sdk-bloat are present and functional."""
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

    # Verify modules have actual state (not just CLI commands)
    print("\n   Module state verification:")

    # Check mint params
    try:
        mint_params = _run_json([miraged, "q", "mint", "params", "--node", rpc, "-o", "json"])
        params = mint_params.get("params", mint_params)
        mint_denom = params.get("mint_denom", "")
        if mint_denom:
            print(f"   [OK] mint: params loaded (denom={mint_denom})")
        else:
            print(f"   [FAIL] mint: params missing mint_denom")
            failures.append("mint module params missing mint_denom")
    except Exception as e:
        print(f"   [FAIL] mint: cannot query params: {e}")
        failures.append(f"mint module query failed: {e}")

    # Check epochs info
    try:
        epochs_info = _run_json([miraged, "q", "epochs", "epoch-infos", "--node", rpc, "-o", "json"])
        epochs = epochs_info.get("epochs", [])
        if isinstance(epochs, list) and len(epochs) > 0:
            epoch_ids = [e.get("identifier", "?") for e in epochs[:3]]
            print(f"   [OK] epochs: {len(epochs)} epoch(s) configured ({', '.join(epoch_ids)})")
        else:
            print(f"   [WARN] epochs: no epochs configured (may be expected)")
            warnings.append("epochs module has no epochs configured")
    except Exception as e:
        print(f"   [FAIL] epochs: cannot query epoch-infos: {e}")
        failures.append(f"epochs module query failed: {e}")

    # Check authz (verify query works - use help to avoid needing valid address)
    try:
        p = subprocess.run([miraged, "q", "authz", "grants", "--help"], capture_output=True, text=True, check=False)
        if p.returncode == 0 or "usage" in (p.stdout + p.stderr).lower():
            print(f"   [OK] authz: query functional")
        else:
            print(f"   [FAIL] authz: query command broken")
            failures.append("authz module query command broken")
    except Exception as e:
        print(f"   [FAIL] authz: cannot query: {e}")
        failures.append(f"authz module query failed: {e}")

    # Check circuit (empty accounts is OK)
    try:
        circuit_result = _run_json([miraged, "q", "circuit", "accounts", "--node", rpc, "-o", "json"])
        print(f"   [OK] circuit: query functional")
    except Exception as e:
        err_str = str(e).lower()
        if "pagination" in err_str or "empty" in err_str:
            print(f"   [OK] circuit: query functional (no accounts)")
        else:
            print(f"   [FAIL] circuit: cannot query: {e}")
            failures.append(f"circuit module query failed: {e}")

    # Check evidence list (empty is OK)
    try:
        evidence_result = _run_json([miraged, "q", "evidence", "list", "--node", rpc, "-o", "json"])
        evidence_list = evidence_result.get("evidence", [])
        print(f"   [OK] evidence: query functional ({len(evidence_list)} item(s))")
    except Exception as e:
        err_str = str(e).lower()
        if "no evidence" in err_str or "empty" in err_str or "pagination" in err_str or "null" in err_str:
            print(f"   [OK] evidence: query functional (no evidence)")
        else:
            print(f"   [FAIL] evidence: cannot query: {e}")
            failures.append(f"evidence module query failed: {e}")


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
        threshold = float(cfg.get("attestation_threshold", 0))
        if abs(threshold - 0.6667) < 1e-4:
            print(f"   [OK] attestation_threshold: {threshold}")
        else:
            print(f"   [FAIL] attestation_threshold: expected ~0.6667, got {threshold}")
            failures.append(f"bridge config.attestation_threshold expected ~0.6667, got {threshold}")
    except Exception as e:
        print(f"   [FAIL] attestation_threshold: invalid")
        failures.append(f"bridge config.attestation_threshold invalid: {e}")

    # Note: bridge_fee is now per-chain in BridgeChainConfig.fee, not global

    print("\n   Cross-check vs core params:")
    try:
        core_threshold = float(core.get("bridge_attestation_threshold", 0))
        cfg_threshold = float(cfg.get("attestation_threshold", 0))
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
        if cur < 0:
            print(f"   [FAIL] current_difficulty: {cur} (must be >= 0)")
            failures.append(f"current_difficulty must be >= 0, got {cur}")
        else:
            print(f"   [OK] current_difficulty: {cur} steps")
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


# ---------------------------------------------------------------------------
# v1.10.8 feature checks (source-level verification)
# ---------------------------------------------------------------------------


def check_grpc_staking_queries(failures: list[str], warnings: list[str]) -> None:
    """Verify CLI subprocess staking calls replaced with gRPC in bank.py, chain.py, public.py."""
    print("\n-> Checking gRPC staking migration...")

    # 1. bank.py must have new gRPC functions
    bank_py = REPO_ROOT / "web" / "backend" / "bank.py"
    if not bank_py.exists():
        failures.append("gRPC staking: web/backend/bank.py not found")
        return
    bank_text = bank_py.read_text()

    for fn in ("get_staked_balance", "get_validator", "get_all_validators"):
        if f"def {fn}(" in bank_text:
            print(f"   [OK] bank.py: {fn}() defined")
        else:
            print(f"   [FAIL] bank.py: {fn}() not found")
            failures.append(f"gRPC staking: bank.py missing {fn}()")

    if "staking.v1beta1" in bank_text:
        print("   [OK] bank.py: uses cosmos.staking.v1beta1 protos")
    else:
        print("   [FAIL] bank.py: missing staking proto imports")
        failures.append("gRPC staking: bank.py does not import staking protos")

    # 2. chain.py must NOT use subprocess for staking
    chain_py = REPO_ROOT / "web" / "backend" / "chain.py"
    if chain_py.exists():
        chain_text = chain_py.read_text()
        if "subprocess" not in chain_text:
            print("   [OK] chain.py: no subprocess dependency")
        else:
            print("   [FAIL] chain.py: still uses subprocess")
            failures.append("gRPC staking: chain.py still uses subprocess")

        if "get_all_validators" in chain_text:
            print("   [OK] chain.py: uses bank.get_all_validators()")
        else:
            print("   [FAIL] chain.py: not using gRPC validator query")
            failures.append("gRPC staking: chain.py not using bank.get_all_validators()")

    # 3. public.py must NOT use subprocess for staking
    public_py = REPO_ROOT / "web" / "backend" / "routes" / "public.py"
    if public_py.exists():
        public_text = public_py.read_text()
        if "import subprocess" not in public_text:
            print("   [OK] public.py: no subprocess import")
        else:
            print("   [FAIL] public.py: still imports subprocess")
            failures.append("gRPC staking: public.py still imports subprocess")

        if "_get_validator" in public_text or "_get_staked_balance" in public_text:
            print("   [OK] public.py: uses gRPC staking functions")
        else:
            print("   [FAIL] public.py: not using gRPC staking functions")
            failures.append("gRPC staking: public.py not using gRPC staking functions")

        if "staked_balance" in public_text:
            print("   [OK] public.py: staked_balance in network stats response")
        else:
            print("   [FAIL] public.py: staked_balance not in response")
            failures.append("gRPC staking: public.py missing staked_balance in get_network_stats")


def check_node_balance_tracking(failures: list[str], warnings: list[str]) -> None:
    """Verify indexer records node balance alongside supply history."""
    print("\n-> Checking node balance tracking...")

    # 1. Migration file exists
    migration = REPO_ROOT / "indexer" / "migrations" / "v2_0_4_node_balance.py"
    if migration.exists():
        print("   [OK] v2_0_4_node_balance.py migration exists")
        if _file_contains(migration, r"node_balance"):
            print("   [OK] migration adds node_balance column")
        else:
            print("   [FAIL] migration missing node_balance column")
            failures.append("node balance: migration v2_0_4 does not add node_balance")
    else:
        print("   [FAIL] v2_0_4_node_balance.py migration not found")
        failures.append("node balance: indexer/migrations/v2_0_4_node_balance.py not found")

    # 2. chain_client.py has get_balance()
    chain_client = REPO_ROOT / "indexer" / "chain_client.py"
    if _file_contains(chain_client, r"def get_balance\("):
        print("   [OK] chain_client.py: get_balance() defined")
    else:
        print("   [FAIL] chain_client.py: get_balance() not found")
        failures.append("node balance: chain_client.py missing get_balance()")

    # 3. main.py resolves validator address and records node balance
    main_py = REPO_ROOT / "indexer" / "main.py"
    if main_py.exists():
        main_text = main_py.read_text()
        if "_resolve_validator_address" in main_text:
            print("   [OK] main.py: _resolve_validator_address() present")
        else:
            print("   [FAIL] main.py: validator address resolution not found")
            failures.append("node balance: indexer main.py missing _resolve_validator_address()")

        if "node_balance" in main_text:
            print("   [OK] main.py: records node_balance in supply history")
        else:
            print("   [FAIL] main.py: node_balance recording not found")
            failures.append("node balance: indexer main.py does not record node_balance")

    # 4. database.py upsert_supply accepts node_balance
    db_py = REPO_ROOT / "indexer" / "database.py"
    if _file_contains(db_py, r"node_balance"):
        print("   [OK] database.py: node_balance in supply queries")
    else:
        print("   [FAIL] database.py: node_balance not found")
        failures.append("node balance: database.py missing node_balance support")

    # 5. Backend supply history includes node_balance
    public_py = REPO_ROOT / "web" / "backend" / "routes" / "public.py"
    if _file_contains(public_py, r"node_balance"):
        print("   [OK] public.py: node_balance in supply history response")
    else:
        print("   [FAIL] public.py: node_balance not in supply history")
        failures.append("node balance: public.py supply history missing node_balance")


def check_network_charts(failures: list[str], warnings: list[str]) -> None:
    """Verify unified chart layout and new chart components in NetworkView."""
    print("\n-> Checking network charts...")

    nv = REPO_ROOT / "web" / "frontend" / "src" / "views" / "NetworkView.js"
    if not nv.exists():
        print("   [WARN] NetworkView.js not found (frontend source not present)")
        warnings.append("network charts: NetworkView.js not found (frontend source not on this host)")
        return
    text = nv.read_text()

    # 1. Shared CHART constants
    if "const CHART" in text:
        print("   [OK] Shared CHART layout constants defined")
    else:
        print("   [FAIL] Shared CHART constants not found")
        failures.append("network charts: missing shared CHART layout constants")

    # 2. SupplyChart component
    if "function SupplyChart(" in text:
        print("   [OK] SupplyChart component defined")
    else:
        print("   [FAIL] SupplyChart component not found")
        failures.append("network charts: SupplyChart component missing")

    # 3. NodeBalanceChart component
    if "function NodeBalanceChart(" in text:
        print("   [OK] NodeBalanceChart component defined")
    else:
        print("   [FAIL] NodeBalanceChart component not found")
        failures.append("network charts: NodeBalanceChart component missing")

    # 4. NodeMintBurnChart component
    if "function NodeMintBurnChart(" in text:
        print("   [OK] NodeMintBurnChart component defined")
    else:
        print("   [FAIL] NodeMintBurnChart component not found")
        failures.append("network charts: NodeMintBurnChart component missing")

    # 5. Staked balance display
    if "stakedBalance" in text:
        print("   [OK] Staked balance state and display present")
    else:
        print("   [FAIL] Staked balance not found")
        failures.append("network charts: stakedBalance display missing from server tab")

    # 6. ChartGrid shared component
    if "function ChartGrid(" in text:
        print("   [OK] ChartGrid shared component defined")
    else:
        print("   [FAIL] ChartGrid component not found")
        failures.append("network charts: ChartGrid shared component missing")

    # 7. fmtMirage shared formatter
    if "function fmtMirage(" in text:
        print("   [OK] fmtMirage shared formatter defined")
    else:
        print("   [FAIL] fmtMirage formatter not found")
        failures.append("network charts: fmtMirage shared formatter missing")


def check_deploy_migration_v1_11(failures: list[str], warnings: list[str]) -> None:
    """Verify deploy migration for backend env renames exists and covers all renames."""
    print("\n-> Checking deploy migration v1.11.0...")

    migration = REPO_ROOT / "deploy" / "migrations" / "v1_11_0_backend_env_renames.py"
    if not migration.exists():
        print("   [FAIL] v1_11_0_backend_env_renames.py not found")
        failures.append("deploy: migrations/v1_11_0_backend_env_renames.py not found")
        return

    print("   [OK] v1_11_0_backend_env_renames.py exists")
    mig_text = migration.read_text()

    # Verify the migration covers all required renames
    required_renames = {
        "INVITE_CODES_REQUIRED": "REGISTRATION_INVITE_CODE_REQUIRED",
        "GUNICORN_WORKERS": "BACKEND_GUNICORN_WORKERS",
        "DAILY_QUESTS_COUNT": "QUESTS_DAILY_COUNT",
        "FLASH_QUESTS_COUNT": "QUESTS_FLASH_COUNT",
        "FLASH_QUEST_MIN_INTERVAL_HOURS": "QUESTS_FLASH_MIN_INTERVAL_HOURS",
        "FLASH_QUEST_MAX_INTERVAL_HOURS": "QUESTS_FLASH_MAX_INTERVAL_HOURS",
        "PAYOUTS_ENABLED": "QUESTS_PAYOUTS_ENABLED",
        "REWARDS_POOL_ADDRESS": "QUESTS_REWARDS_POOL_ADDRESS",
        "INVITE_RECRUIT_CHANCE": "QUESTS_INVITE_RECRUIT_CHANCE",
        "INVITE_EARNER_QUEST_INTERVAL": "QUESTS_INVITE_EARNER_INTERVAL",
        "INVITE_EARNER_CHANCE": "QUESTS_INVITE_EARNER_CHANCE",
    }
    for old, new in required_renames.items():
        if f'"{old}"' in mig_text and f'"{new}"' in mig_text:
            print(f"   [OK] migration: {old} -> {new}")
        else:
            print(f"   [FAIL] migration: {old} -> {new} mapping not found")
            failures.append(f"deploy migration: missing rename {old} -> {new}")


def check_quest_settings_rename(failures: list[str], warnings: list[str]) -> None:
    """Verify all quest env vars use the QUESTS_ prefix."""
    print("\n-> Checking quest settings rename...")

    # All quest env vars/constants must use QUESTS_ prefix
    quests_names = [
        "QUESTS_DAILY_COUNT",
        "QUESTS_FLASH_MIN_INTERVAL_HOURS",
        "QUESTS_FLASH_MAX_INTERVAL_HOURS",
        "QUESTS_INVITE_RECRUIT_CHANCE",
        "QUESTS_INVITE_EARNER_INTERVAL",
        "QUESTS_INVITE_EARNER_CHANCE",
    ]
    # Old names that must NOT appear as bare definitions
    old_names = [
        "INVITE_RECRUIT_CHANCE",
        "INVITE_EARNER_QUEST_INTERVAL",
        "INVITE_EARNER_CHANCE",
        "DAILY_QUESTS_COUNT",
        "FLASH_QUESTS_COUNT",
        "FLASH_QUEST_MIN_INTERVAL_HOURS",
        "FLASH_QUEST_MAX_INTERVAL_HOURS",
    ]

    settings_py = REPO_ROOT / "indexer" / "settings.py"
    if settings_py.exists():
        text = settings_py.read_text()
        for name in quests_names:
            if name in text:
                print(f"   [OK] settings.py: {name} defined")
            else:
                print(f"   [FAIL] settings.py: {name} not found")
                failures.append(f"quest settings: {name} not defined in settings.py")

        for name in old_names:
            if re.search(rf"^{name}\s*=", text, re.MULTILINE):
                print(f"   [FAIL] settings.py: old name {name} still defined")
                failures.append(f"quest settings: old name {name} still present in settings.py")

    # Check quest_tracker.py uses new names
    tracker_py = REPO_ROOT / "indexer" / "quest_tracker.py"
    if tracker_py.exists():
        tracker_text = tracker_py.read_text()
        for old in old_names:
            if re.search(rf"(?<![A-Z_]){old}(?![A-Z_])", tracker_text):
                print(f"   [FAIL] quest_tracker.py still references {old}")
                failures.append(f"quest settings: quest_tracker.py still uses {old}")
        print("   [OK] quest_tracker.py: uses QUESTS_ prefix")

    # Check quests.py uses consistent names
    quests_py = REPO_ROOT / "web" / "backend" / "routes" / "quests.py"
    if quests_py.exists():
        quests_text = quests_py.read_text()
        for name in quests_names:
            if name in quests_text:
                print(f"   [OK] quests.py: {name} used")
            else:
                print(f"   [WARN] quests.py: {name} not found")
                warnings.append(f"quest settings: quests.py does not reference {name}")


def check_registration_gating(failures: list[str], warnings: list[str]) -> None:
    """Verify registration gating via REGISTRATION_ENABLED and REGISTRATION_INVITE_CODE_REQUIRED."""
    print("\n-> Checking registration gating...")

    # 1. Backend core.py: REGISTRATION_ENABLED + REGISTRATION_INVITE_CODE_REQUIRED
    core_py = REPO_ROOT / "web" / "backend" / "routes" / "core.py"
    if core_py.exists():
        text = core_py.read_text()
        if "REGISTRATION_ENABLED" in text:
            print("   [OK] core.py: REGISTRATION_ENABLED env var used")
        else:
            print("   [FAIL] core.py: REGISTRATION_ENABLED not found")
            failures.append("registration: core.py missing REGISTRATION_ENABLED check")

        if "REGISTRATION_INVITE_CODE_REQUIRED" in text:
            print("   [OK] core.py: REGISTRATION_INVITE_CODE_REQUIRED env var used")
        else:
            print("   [FAIL] core.py: REGISTRATION_INVITE_CODE_REQUIRED not found")
            failures.append("registration: core.py missing REGISTRATION_INVITE_CODE_REQUIRED check")

        # Old name should be gone
        if "INVITE_CODES_REQUIRED" in text:
            print("   [FAIL] core.py: old INVITE_CODES_REQUIRED still present")
            failures.append("registration: core.py still uses old INVITE_CODES_REQUIRED")
        else:
            print("   [OK] core.py: old INVITE_CODES_REQUIRED removed")

        # Registration disabled gate
        if "registration is disabled" in text or "registration_disabled" in text:
            print("   [OK] core.py: registration disabled gate present")
        else:
            print("   [FAIL] core.py: registration disabled response not found")
            failures.append("registration: core.py missing registration disabled response")

    # 2. Frontend CreateAccountView reads config flags
    cav = REPO_ROOT / "web" / "frontend" / "src" / "views" / "CreateAccountView.js"
    if cav.exists():
        cav_text = cav.read_text()
        if "registrationEnabled" in cav_text:
            print("   [OK] CreateAccountView.js: reads registrationEnabled from config")
        else:
            print("   [FAIL] CreateAccountView.js: registrationEnabled not found")
            failures.append("registration: CreateAccountView.js missing registrationEnabled")

        if "inviteCodeRequired" in cav_text:
            print("   [OK] CreateAccountView.js: reads inviteCodeRequired from config")
        else:
            print("   [FAIL] CreateAccountView.js: inviteCodeRequired not found")
            failures.append("registration: CreateAccountView.js missing inviteCodeRequired")

        # Old hardcoded hostname check should be gone
        if "isMainSite" in cav_text or "mirage.talk" in cav_text:
            print("   [FAIL] CreateAccountView.js: still has hardcoded hostname check")
            failures.append("registration: CreateAccountView.js still uses hardcoded hostname")
        else:
            print("   [OK] CreateAccountView.js: no hardcoded hostname checks")

    # 3. Backend env template has new keys
    env_template = REPO_ROOT / "deploy" / "templates" / "env" / "backend.env"
    if env_template.exists():
        env_text = env_template.read_text()
        for key in ("REGISTRATION_ENABLED", "REGISTRATION_INVITE_CODE_REQUIRED"):
            if key in env_text:
                print(f"   [OK] backend.env template: {key} present")
            else:
                print(f"   [FAIL] backend.env template: {key} missing")
                failures.append(f"registration: backend.env template missing {key}")


def check_reward_env_renames(failures: list[str], warnings: list[str]) -> None:
    """Verify reward env vars use the QUESTS_ prefix."""
    print("\n-> Checking reward env renames...")

    rd = REPO_ROOT / "web" / "backend" / "reward_distributor.py"
    if not rd.exists():
        print("   [WARN] reward_distributor.py not found")
        warnings.append("reward renames: reward_distributor.py not found")
        return

    text = rd.read_text()

    # New names should be present
    for new_name in ("QUESTS_REWARDS_POOL_ADDRESS", "QUESTS_PAYOUTS_ENABLED"):
        if new_name in text:
            print(f"   [OK] reward_distributor.py: {new_name} used")
        else:
            print(f"   [FAIL] reward_distributor.py: {new_name} not found")
            failures.append(f"reward renames: reward_distributor.py missing {new_name}")

    # Old bare names should NOT be defined (but may appear in comments)
    if re.search(r"^REWARDS_POOL_ADDRESS\s*=", text, re.MULTILINE):
        print("   [FAIL] reward_distributor.py: old REWARDS_POOL_ADDRESS still defined")
        failures.append("reward renames: old REWARDS_POOL_ADDRESS still defined")
    else:
        print("   [OK] old REWARDS_POOL_ADDRESS definition removed")

    if re.search(r"^PAYOUTS_ENABLED\s*=", text, re.MULTILINE):
        print("   [FAIL] reward_distributor.py: old PAYOUTS_ENABLED still defined")
        failures.append("reward renames: old PAYOUTS_ENABLED still defined")
    else:
        print("   [OK] old PAYOUTS_ENABLED definition removed")

    # Backend env template
    env_template = REPO_ROOT / "deploy" / "templates" / "env" / "backend.env"
    if env_template.exists():
        env_text = env_template.read_text()
        for key in ("QUESTS_REWARDS_POOL_ADDRESS", "QUESTS_PAYOUTS_ENABLED"):
            if key in env_text:
                print(f"   [OK] backend.env template: {key} present")
            else:
                print(f"   [FAIL] backend.env template: {key} missing")
                failures.append(f"reward renames: backend.env template missing {key}")

    # setup_rewards_pool.py should also use QUESTS_ prefix
    srp = REPO_ROOT / "deploy" / "setup_rewards_pool.py"
    if srp.exists():
        srp_text = srp.read_text()
        for new_name in ("QUESTS_REWARDS_POOL_ADDRESS", "QUESTS_PAYOUTS_ENABLED"):
            if new_name in srp_text:
                print(f"   [OK] setup_rewards_pool.py: {new_name} used")
            else:
                print(f"   [FAIL] setup_rewards_pool.py: {new_name} not found")
                failures.append(f"reward renames: setup_rewards_pool.py missing {new_name}")

        # Old bare names should not be present
        for old_name in ("REWARDS_POOL_ADDRESS", "PAYOUTS_ENABLED"):
            if re.search(rf"(?<![A-Z_]){old_name}(?![A-Z_])", srp_text):
                print(f"   [FAIL] setup_rewards_pool.py: old {old_name} still referenced")
                failures.append(f"reward renames: setup_rewards_pool.py still uses {old_name}")
    else:
        print("   [WARN] setup_rewards_pool.py not found")
        warnings.append("reward renames: setup_rewards_pool.py not found")


def check_donation_formatting(failures: list[str], warnings: list[str]) -> None:
    """Verify donation success messages use toLocaleString() for amount formatting."""
    print("\n-> Checking donation amount formatting...")

    for fname in ("components/CardView.js", "views/ViewPostView.js"):
        path = REPO_ROOT / "web" / "frontend" / "src" / fname
        if not path.exists():
            continue
        text = path.read_text()
        if "toLocaleString()" in text:
            print(f"   [OK] {fname}: uses toLocaleString() for donation amounts")
        else:
            print(f"   [WARN] {fname}: toLocaleString() not found")
            warnings.append(f"donation formatting: {fname} missing toLocaleString()")


def check_gunicorn_workers_rename(failures: list[str], warnings: list[str]) -> None:
    """Verify GUNICORN_WORKERS was renamed to BACKEND_GUNICORN_WORKERS."""
    print("\n-> Checking BACKEND_GUNICORN_WORKERS rename...")

    # 1. gunicorn_config.py should use BACKEND_GUNICORN_WORKERS
    gc = REPO_ROOT / "web" / "backend" / "gunicorn_config.py"
    if gc.exists():
        text = gc.read_text()
        if "BACKEND_GUNICORN_WORKERS" in text:
            print("   [OK] gunicorn_config.py: uses BACKEND_GUNICORN_WORKERS")
        else:
            print("   [FAIL] gunicorn_config.py: BACKEND_GUNICORN_WORKERS not found")
            failures.append("gunicorn rename: gunicorn_config.py missing BACKEND_GUNICORN_WORKERS")

        # Old name should not be present (as a bare reference)
        if re.search(r'(?<![A-Z_])GUNICORN_WORKERS(?![A-Z_])', text):
            print("   [FAIL] gunicorn_config.py: old GUNICORN_WORKERS still referenced")
            failures.append("gunicorn rename: gunicorn_config.py still uses old GUNICORN_WORKERS")
        else:
            print("   [OK] gunicorn_config.py: old GUNICORN_WORKERS removed")
    else:
        print("   [WARN] gunicorn_config.py not found")
        warnings.append("gunicorn rename: gunicorn_config.py not found")

    # 2. backend.env template should use BACKEND_GUNICORN_WORKERS
    env_template = REPO_ROOT / "deploy" / "templates" / "env" / "backend.env"
    if env_template.exists():
        env_text = env_template.read_text()
        if "BACKEND_GUNICORN_WORKERS" in env_text:
            print("   [OK] backend.env template: BACKEND_GUNICORN_WORKERS present")
        else:
            print("   [FAIL] backend.env template: BACKEND_GUNICORN_WORKERS missing")
            failures.append("gunicorn rename: backend.env template missing BACKEND_GUNICORN_WORKERS")

        if re.search(r'^GUNICORN_WORKERS=', env_text, re.MULTILINE):
            print("   [FAIL] backend.env template: old GUNICORN_WORKERS= still present")
            failures.append("gunicorn rename: backend.env template still has old GUNICORN_WORKERS")
        else:
            print("   [OK] backend.env template: old GUNICORN_WORKERS= removed")

    # 3. Migration should include this rename
    migration = REPO_ROOT / "deploy" / "migrations" / "v1_11_0_backend_env_renames.py"
    if migration.exists():
        mig_text = migration.read_text()
        if '"GUNICORN_WORKERS"' in mig_text and '"BACKEND_GUNICORN_WORKERS"' in mig_text:
            print("   [OK] migration: GUNICORN_WORKERS -> BACKEND_GUNICORN_WORKERS mapping present")
        else:
            print("   [FAIL] migration: GUNICORN_WORKERS rename mapping not found")
            failures.append("gunicorn rename: migration missing GUNICORN_WORKERS -> BACKEND_GUNICORN_WORKERS")


def check_frontend_env_template(failures: list[str], warnings: list[str]) -> None:
    """Verify frontend.env template is cleaned up (no REACT_APP_API_BASE)."""
    print("\n-> Checking frontend.env template...")

    fe = REPO_ROOT / "deploy" / "templates" / "env" / "frontend.env"
    if not fe.exists():
        print("   [WARN] frontend.env template not found")
        warnings.append("frontend env: template not found")
        return

    text = fe.read_text()

    # REACT_APP_API_BASE should NOT be in the template (it's baked at build time
    # and is not user-configurable)
    if re.search(r'^REACT_APP_API_BASE=', text, re.MULTILINE):
        print("   [FAIL] frontend.env: REACT_APP_API_BASE should not be user-configurable")
        failures.append("frontend env: REACT_APP_API_BASE still in template (baked at build time)")
    else:
        print("   [OK] frontend.env: REACT_APP_API_BASE not exposed as configurable")

    # Should have the bake-time note
    if "baked" in text.lower() or "build time" in text.lower():
        print("   [OK] frontend.env: contains build-time note for REACT_APP_* vars")
    else:
        print("   [WARN] frontend.env: missing note about REACT_APP_* being baked at build time")
        warnings.append("frontend env: missing bake-time note for REACT_APP_* vars")


# ---------------------------------------------------------------------------
# v1.10.7 feature checks (source-level verification)
# ---------------------------------------------------------------------------


def _file_contains(path: Path, pattern: str) -> bool:
    """Return True if *path* exists and its text matches *pattern* (regex)."""
    try:
        if not path.exists():
            return False
        return bool(re.search(pattern, path.read_text()))
    except Exception:
        return False


def _file_missing_pattern(path: Path, pattern: str) -> bool:
    """Return True if *path* exists and does NOT match *pattern* (regex)."""
    try:
        if not path.exists():
            return False
        return not bool(re.search(pattern, path.read_text()))
    except Exception:
        return False


def check_fingerprinting_removed(failures: list[str], warnings: list[str]) -> None:
    """Verify that the device fingerprinting system has been fully removed."""
    print("\n-> Checking fingerprinting removal...")

    # 1. user_fingerprints table should be dropped in database.py
    db_path = REPO_ROOT / "indexer" / "database.py"
    if _file_contains(db_path, r"DROP TABLE IF EXISTS user_fingerprints"):
        print("   [OK] database.py: DROP TABLE user_fingerprints present")
    else:
        print("   [FAIL] database.py: missing DROP TABLE user_fingerprints")
        failures.append("fingerprinting: database.py does not drop user_fingerprints table")

    # 2. PII columns (user_agent, ip_hash, referrer) should be dropped from stats_events.
    #    The source uses an f-string loop: for col in ("user_agent", "ip_hash", "referrer")
    #    so we check for the column names in the iteration tuple AND the DROP COLUMN statement.
    if _file_contains(db_path, r"DROP COLUMN"):
        print("   [OK] database.py: DROP COLUMN statement present")
    else:
        print("   [FAIL] database.py: no DROP COLUMN statement found")
        failures.append("fingerprinting: database.py has no DROP COLUMN for PII columns")
    for col in ("user_agent", "ip_hash", "referrer"):
        if _file_contains(db_path, rf'"{col}"'):
            print(f"   [OK] database.py: column {col} referenced in drop loop")
        else:
            print(f"   [FAIL] database.py: column {col} not referenced")
            failures.append(f"fingerprinting: stats_events.{col} not referenced in database.py drop loop")

    # 3. Coarse device columns should be added instead.
    #    Same f-string loop pattern: for col in ("browser_family", "os_family", "device_type")
    if _file_contains(db_path, r"ADD COLUMN"):
        print("   [OK] database.py: ADD COLUMN statement present for coarse categories")
    else:
        print("   [WARN] database.py: no ADD COLUMN for coarse categories")
        warnings.append("fingerprinting: database.py has no ADD COLUMN for coarse device columns")
    for col in ("browser_family", "os_family", "device_type"):
        if _file_contains(db_path, rf'"{col}"'):
            print(f"   [OK] database.py: coarse column {col} referenced")
        else:
            print(f"   [WARN] database.py: coarse column {col} not found")
            warnings.append(f"fingerprinting: expected coarse column {col} in database.py")

    # 4. No fingerprinting code in backend routes
    routes_dir = REPO_ROOT / "web" / "backend" / "routes"
    public_py = routes_dir / "public.py"
    if public_py.exists():
        text = public_py.read_text()
        for banned in ("fingerprint", "sock_puppet", "sock puppet", "user_profiling"):
            if re.search(banned, text, re.IGNORECASE):
                print(f"   [FAIL] public.py: still contains '{banned}'")
                failures.append(f"fingerprinting: public.py still references '{banned}'")
                break
        else:
            print("   [OK] public.py: no fingerprinting references")
    else:
        print("   [WARN] public.py not found")
        warnings.append("fingerprinting: web/backend/routes/public.py not found")

    # 5. Stats endpoint should use bot filtering, not fingerprinting
    if _file_contains(public_py, r"_STATS_BOT_NAMES|bot.*filter"):
        print("   [OK] public.py: server-side bot filtering present")
    else:
        print("   [WARN] public.py: bot filtering pattern not found")
        warnings.append("fingerprinting: expected server-side bot filtering in public.py")


def check_safe_error_coverage(failures: list[str], warnings: list[str]) -> None:
    """Verify that safe_error() exists and is wired into all route files and the global handler."""
    print("\n-> Checking sanitized error responses...")

    # 1. error_utils.py must exist with safe_error()
    error_utils = REPO_ROOT / "web" / "backend" / "error_utils.py"
    if not error_utils.exists():
        print("   [FAIL] error_utils.py: not found")
        failures.append("safe_error: web/backend/error_utils.py not found")
        return

    text = error_utils.read_text()
    if "def safe_error(" in text:
        print("   [OK] error_utils.py: safe_error() defined")
    else:
        print("   [FAIL] error_utils.py: safe_error() not defined")
        failures.append("safe_error: function not defined in error_utils.py")

    if "request_id" in text:
        print("   [OK] error_utils.py: returns request_id to client")
    else:
        print("   [FAIL] error_utils.py: missing request_id in response")
        failures.append("safe_error: does not include request_id in error response")

    # 2. Global error handler in factory.py
    factory = REPO_ROOT / "web" / "backend" / "factory.py"
    if _file_contains(factory, r"@app\.errorhandler\(Exception\)"):
        print("   [OK] factory.py: global Exception handler registered")
    else:
        print("   [FAIL] factory.py: missing global Exception handler")
        failures.append("safe_error: factory.py missing @app.errorhandler(Exception)")

    if _file_contains(factory, r"safe_error"):
        print("   [OK] factory.py: global handler uses safe_error()")
    else:
        print("   [FAIL] factory.py: global handler does not use safe_error()")
        failures.append("safe_error: factory.py global handler does not call safe_error()")

    # 3. Route files should sanitize errors — either via safe_error() directly or
    #    via a local _classify_exception() helper that also strips raw exception text.
    routes_dir = REPO_ROOT / "web" / "backend" / "routes"
    route_files = ["public.py", "core.py", "bridge.py", "quests.py"]
    for fname in route_files:
        rpath = routes_dir / fname
        if not rpath.exists():
            print(f"   [WARN] routes/{fname}: not found")
            warnings.append(f"safe_error: routes/{fname} not found")
            continue
        has_safe_error = _file_contains(rpath, r"safe_error")
        has_classify = _file_contains(rpath, r"_classify_exception")
        if has_safe_error:
            print(f"   [OK] routes/{fname}: uses safe_error()")
        elif has_classify:
            print(f"   [OK] routes/{fname}: uses _classify_exception() (sanitized)")
        else:
            print(f"   [FAIL] routes/{fname}: no error sanitization found")
            failures.append(f"safe_error: routes/{fname} has no safe_error() or _classify_exception()")


def check_spoiler_tags(failures: list[str], warnings: list[str]) -> None:
    """Verify spoiler tag support in the markdown renderer."""
    frontend_src = REPO_ROOT / "web" / "frontend" / "src"
    renderer = frontend_src / "components" / "MarkdownRenderer.js"
    if not frontend_src.exists() or not renderer.exists():
        return

    print("\n-> Checking spoiler tag support...")

    text = renderer.read_text()

    # Spoiler component
    if re.search(r"function\s+Spoiler", text):
        print("   [OK] Spoiler component defined")
    else:
        print("   [FAIL] Spoiler component not found")
        failures.append("spoiler tags: Spoiler component not defined in MarkdownRenderer.js")

    # remarkSpoiler plugin
    if re.search(r"function\s+remarkSpoiler", text):
        print("   [OK] remarkSpoiler plugin defined")
    else:
        print("   [FAIL] remarkSpoiler plugin not found")
        failures.append("spoiler tags: remarkSpoiler plugin not defined in MarkdownRenderer.js")

    # Plugin registered in remarkPlugins
    if "remarkSpoiler" in text and "remarkPlugins" in text:
        print("   [OK] remarkSpoiler registered in remarkPlugins")
    else:
        print("   [FAIL] remarkSpoiler not registered in remarkPlugins")
        failures.append("spoiler tags: remarkSpoiler not wired into remarkPlugins")

    # Component mapping for spoiler-tag
    if "'spoiler-tag'" in text or '"spoiler-tag"' in text:
        print("   [OK] spoiler-tag component mapping present")
    else:
        print("   [FAIL] spoiler-tag component mapping missing")
        failures.append("spoiler tags: spoiler-tag not mapped in components prop")

    # ||text|| syntax (the regex pattern in the plugin)
    if re.search(r"\|\|.*\|\|", text):
        print("   [OK] ||double pipes|| syntax pattern present")
    else:
        print("   [WARN] ||double pipes|| syntax pattern not found")
        warnings.append("spoiler tags: expected ||text|| pattern in remarkSpoiler")


def check_inbox_server_side(failures: list[str], warnings: list[str]) -> None:
    """Verify server-side inbox unread count tracking."""
    print("\n-> Checking server-side inbox notifications...")

    # 1. Backend: _get_new_inbox_count in public.py
    public_py = REPO_ROOT / "web" / "backend" / "routes" / "public.py"
    if not public_py.exists():
        print("   [FAIL] routes/public.py: not found")
        failures.append("inbox: web/backend/routes/public.py not found")
        return

    text = public_py.read_text()

    if "def _get_new_inbox_count(" in text:
        print("   [OK] _get_new_inbox_count() defined")
    else:
        print("   [FAIL] _get_new_inbox_count() not found")
        failures.append("inbox: _get_new_inbox_count() not defined in public.py")

    if "_inbox_cache" in text:
        print("   [OK] _inbox_cache present (60s server-side cache)")
    else:
        print("   [FAIL] _inbox_cache not found")
        failures.append("inbox: _inbox_cache not found in public.py")

    if "def _invalidate_inbox_cache(" in text:
        print("   [OK] _invalidate_inbox_cache() defined")
    else:
        print("   [FAIL] _invalidate_inbox_cache() not found")
        failures.append("inbox: _invalidate_inbox_cache() not defined in public.py")

    if "mark_inbox_viewed" in text:
        print("   [OK] mark_inbox_viewed endpoint present")
    else:
        print("   [FAIL] mark_inbox_viewed endpoint not found")
        failures.append("inbox: /api/mark_inbox_viewed endpoint missing from public.py")

    # 2. Middleware: factory.py injects new_inbox_items
    factory = REPO_ROOT / "web" / "backend" / "factory.py"
    if _file_contains(factory, r"new_inbox_items"):
        print("   [OK] factory.py: new_inbox_items injected into responses")
    else:
        print("   [FAIL] factory.py: new_inbox_items injection missing")
        failures.append("inbox: factory.py does not inject new_inbox_items into API responses")

    if _file_contains(factory, r"@app\.after_request"):
        print("   [OK] factory.py: after_request middleware registered")
    else:
        print("   [FAIL] factory.py: after_request middleware missing")
        failures.append("inbox: factory.py missing @app.after_request middleware for inbox count")

    # 3. Database migration for inbox_last_viewed_at
    migration = REPO_ROOT / "indexer" / "migrations" / "v2_0_3_inbox_last_viewed.py"
    if migration.exists():
        print("   [OK] v2_0_3_inbox_last_viewed.py migration exists")
        if _file_contains(migration, r"inbox_last_viewed_at"):
            print("   [OK] migration adds inbox_last_viewed_at column")
        else:
            print("   [FAIL] migration missing inbox_last_viewed_at column")
            failures.append("inbox: migration v2_0_3 does not add inbox_last_viewed_at")
    else:
        print("   [FAIL] v2_0_3_inbox_last_viewed.py migration not found")
        failures.append("inbox: indexer/migrations/v2_0_3_inbox_last_viewed.py not found")

    # 4. Frontend: api.js syncs inbox count from responses (only when source is present)
    api_js = REPO_ROOT / "web" / "frontend" / "src" / "lib" / "api.js"
    if api_js.exists():
        if _file_contains(api_js, r"new_inbox_items|inboxCount"):
            print("   [OK] api.js: inbox count sync from API responses")
        else:
            print("   [WARN] api.js: inbox count sync not found")
            warnings.append("inbox: frontend api.js does not sync new_inbox_items")


def check_seed_vault(failures: list[str], warnings: list[str]) -> None:
    """Verify seed phrase security with four storage modes."""
    frontend_src = REPO_ROOT / "web" / "frontend" / "src"
    vault = frontend_src / "utils" / "SeedVault.js"
    if not frontend_src.exists() or not vault.exists():
        return

    print("\n-> Checking seed phrase security (SeedVault)...")

    text = vault.read_text()

    # Class / core structure
    if "class SeedVault" in text:
        print("   [OK] SeedVault class defined")
    else:
        print("   [FAIL] SeedVault class not found")
        failures.append("seed vault: SeedVault class not defined")

    # Four modes present
    modes = ["insecure", "memory", "password", "passkey"]
    found_modes = [m for m in modes if m in text]
    missing_modes = [m for m in modes if m not in text]
    if not missing_modes:
        print(f"   [OK] All 4 storage modes present ({', '.join(modes)})")
    else:
        print(f"   [FAIL] Missing storage modes: {', '.join(missing_modes)}")
        failures.append(f"seed vault: missing storage modes: {', '.join(missing_modes)}")

    # getMode()
    if "getMode()" in text or "getMode (" in text:
        print("   [OK] getMode() defined")
    else:
        print("   [FAIL] getMode() not found")
        failures.append("seed vault: getMode() not defined")

    # AES-GCM / PBKDF2 for password mode
    if "AES-GCM" in text or "aes-gcm" in text.lower():
        print("   [OK] AES-GCM encryption present (password mode)")
    else:
        print("   [FAIL] AES-GCM encryption not found")
        failures.append("seed vault: AES-GCM encryption not found for password mode")

    if "PBKDF2" in text or "pbkdf2" in text.lower():
        print("   [OK] PBKDF2 key derivation present")
    else:
        print("   [FAIL] PBKDF2 key derivation not found")
        failures.append("seed vault: PBKDF2 key derivation not found")

    # WebAuthn / PRF for passkey mode
    if "PRF" in text or "prf" in text:
        print("   [OK] PRF extension present (passkey mode)")
    else:
        print("   [FAIL] PRF extension not found")
        failures.append("seed vault: PRF extension not found for passkey mode")

    # Unlock prompt component
    unlock = frontend_src / "components" / "UnlockPrompt.js"
    if unlock.exists():
        print("   [OK] UnlockPrompt.js component exists")
    else:
        print("   [WARN] UnlockPrompt.js not found")
        warnings.append("seed vault: UnlockPrompt.js component not found")


def check_admin_gas_nonblocking(failures: list[str], warnings: list[str]) -> None:
    """Verify admin gas fee deduction is non-blocking in the chain module."""
    print("\n-> Checking admin gas fee (non-blocking)...")

    # 1. Chain module: admin level check + skip deduction (only when Go source is present)
    module_go = REPO_ROOT / "blockchain" / "x" / "core" / "module" / "module.go"
    if module_go.exists():
        text = module_go.read_text()
        if re.search(r"userLevel\s*>=\s*100", text):
            print("   [OK] module.go: admin level >= 100 check present")
        else:
            print("   [FAIL] module.go: admin level check not found")
            failures.append("admin gas: module.go missing admin level >= 100 check")

        if re.search(r"insufficient balance.*skipping deduction", text, re.IGNORECASE):
            print("   [OK] module.go: skip deduction on insufficient balance")
        else:
            print("   [FAIL] module.go: skip-deduction logic not found")
            failures.append("admin gas: module.go missing skip deduction for admin insufficient balance")

    # 2. Upgrade handler registered for v1.10.7 (only when Go source is present)
    upgrades_go = REPO_ROOT / "blockchain" / "app" / "upgrades.go"
    if upgrades_go.exists():
        if _file_contains(upgrades_go, r"v1\.10\.7"):
            print("   [OK] upgrades.go: v1.10.7 upgrade handler registered")
        else:
            print("   [FAIL] upgrades.go: v1.10.7 upgrade handler not found")
            failures.append("admin gas: upgrades.go missing v1.10.7 handler")

    # 3. Backend: classify admin balance error as 400
    core_py = REPO_ROOT / "web" / "backend" / "routes" / "core.py"
    if _file_contains(core_py, r"admin insufficient balance"):
        print("   [OK] routes/core.py: admin insufficient balance -> 400")
    else:
        print("   [WARN] routes/core.py: admin balance error classification not found")
        warnings.append("admin gas: routes/core.py does not classify admin balance error as 400")

    # 4. Frontend: handles admin balance error (only when source is present)
    tx_handler = REPO_ROOT / "web" / "frontend" / "src" / "utils" / "TransactionHandler.js"
    if tx_handler.exists():
        if _file_contains(tx_handler, r"admin insufficient balance"):
            print("   [OK] TransactionHandler.js: admin balance error handling present")
        else:
            print("   [WARN] TransactionHandler.js: admin balance error handling not found")
            warnings.append("admin gas: TransactionHandler.js does not handle admin balance error")


def check_balance_overflow_fix(failures: list[str], warnings: list[str]) -> None:
    """Verify balance uses 64-bit encoding and single source-of-truth hook."""
    frontend_src = REPO_ROOT / "web" / "frontend" / "src"
    tx_handler = frontend_src / "utils" / "TransactionHandler.js"
    if not frontend_src.exists() or not tx_handler.exists():
        return

    print("\n-> Checking balance overflow fix...")

    text = tx_handler.read_text()
    uvarint64_count = len(re.findall(r"uvarint64", text))
    if uvarint64_count > 0:
        print(f"   [OK] TransactionHandler.js: uvarint64 used ({uvarint64_count} occurrences)")
    else:
        print("   [FAIL] TransactionHandler.js: uvarint64 not found")
        failures.append("balance fix: TransactionHandler.js does not use uvarint64 for amounts")

    # 2. useBalance.js hook as single source of truth
    use_balance = frontend_src / "utils" / "useBalance.js"
    if not use_balance.exists():
        print("   [FAIL] useBalance.js: not found")
        failures.append("balance fix: useBalance.js not found")
        return

    balance_text = use_balance.read_text()
    if "function useBalance" in balance_text or "export default function useBalance" in balance_text:
        print("   [OK] useBalance.js: hook defined")
    else:
        print("   [FAIL] useBalance.js: useBalance hook not found")
        failures.append("balance fix: useBalance() hook not defined in useBalance.js")

    if "balanceUpdated" in balance_text:
        print("   [OK] useBalance.js: balanceUpdated event listener")
    else:
        print("   [FAIL] useBalance.js: balanceUpdated event not found")
        failures.append("balance fix: useBalance.js missing balanceUpdated CustomEvent listener")


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
        check_sdk_modules_restored(miraged, rpc, failures, warnings)

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

    # ---- v1.10.7 feature checks (source-level) ----
    check_fingerprinting_removed(failures, warnings)
    check_safe_error_coverage(failures, warnings)
    check_spoiler_tags(failures, warnings)
    check_inbox_server_side(failures, warnings)
    check_seed_vault(failures, warnings)
    check_admin_gas_nonblocking(failures, warnings)
    check_balance_overflow_fix(failures, warnings)

    # ---- v1.10.8 feature checks (source-level) ----
    check_grpc_staking_queries(failures, warnings)
    check_node_balance_tracking(failures, warnings)
    check_network_charts(failures, warnings)
    check_deploy_migration_v1_11(failures, warnings)
    check_quest_settings_rename(failures, warnings)
    check_registration_gating(failures, warnings)
    check_reward_env_renames(failures, warnings)
    check_gunicorn_workers_rename(failures, warnings)
    check_frontend_env_template(failures, warnings)
    check_donation_formatting(failures, warnings)

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
