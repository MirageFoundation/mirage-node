#!/usr/bin/env python3
"""
Verify Mirage Node Upgrade (v1.9.0-bridge) — strict + exhaustive.

This script is intentionally "no hand-waving":
- It validates EVERY core param field introduced/used by v1.9.0 (including every tier field).
- It validates bridge query commands (`miraged q bridge ...`) exist and return consistent data.
- It validates upgrade state (pre vs post) and local config consistency.

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
from typing import Any
import urllib.error
import urllib.request


UPGRADE_NAME = "v1.9.0-bridge"
REQUIRED_MIN_GAS_PRICE = "5000umirage"


def _http_get_json(url: str, timeout: int = 5) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "mirage-verify/1.9.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))


def _find_miraged() -> str:
    candidates = [
        "/opt/mirage/blockchain/bin/miraged",  # inside container
        str(Path(__file__).resolve().parents[1] / "blockchain" / "miraged"),  # repo checkout
        "miraged",
    ]
    for c in candidates:
        if c == "miraged":
            return c
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return "miraged"


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
        "bridge_fee": 1_000_000,
    }


def _expected_tiers_v190() -> list[dict[str, Any]]:
    return [
        {"period_fee": 0, "max_followed_mods": 5, "max_followed_users": 25, "max_followed_topics": 50,
         "max_blocked_users": 10, "max_blocked_posts": 25, "max_quality_posts": 0, "max_title_length": 130,
         "max_content_length": 1000, "editing_time_mins": 10, "archive_duration_days": 30, "vote_weight": 1.0,
         "award_permissions": 0, "eligible_for_mod": False, "can_change_name": False, "can_have_biography": False,
         "can_have_avatar": False, "can_have_banner": False},
        {"period_fee": 100_000_000_000, "max_followed_mods": 10, "max_followed_users": 125, "max_followed_topics": 250,
         "max_blocked_users": 125, "max_blocked_posts": 100, "max_quality_posts": 0, "max_title_length": 165,
         "max_content_length": 2000, "editing_time_mins": 60, "archive_duration_days": 90, "vote_weight": 1.15,
         "award_permissions": 1, "eligible_for_mod": False, "can_change_name": True, "can_have_biography": True,
         "can_have_avatar": True, "can_have_banner": True},
        {"period_fee": 200_000_000_000, "max_followed_mods": 25, "max_followed_users": 500, "max_followed_topics": 500,
         "max_blocked_users": 500, "max_blocked_posts": 200, "max_quality_posts": 50, "max_title_length": 200,
         "max_content_length": 5000, "editing_time_mins": 360, "archive_duration_days": 180, "vote_weight": 1.30,
         "award_permissions": 2, "eligible_for_mod": True, "can_change_name": True, "can_have_biography": True,
         "can_have_avatar": True, "can_have_banner": True},
        {"period_fee": 300_000_000_000, "max_followed_mods": 50, "max_followed_users": 1000, "max_followed_topics": 1000,
         "max_blocked_users": 1000, "max_blocked_posts": 500, "max_quality_posts": 100, "max_title_length": 250,
         "max_content_length": 25000, "editing_time_mins": 720, "archive_duration_days": 365, "vote_weight": 1.45,
         "award_permissions": 3, "eligible_for_mod": True, "can_change_name": True, "can_have_biography": True,
         "can_have_avatar": True, "can_have_banner": True},
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


def check_node_health(rpc: str, failures: list[str], warnings: list[str]) -> tuple[str | None, str | None]:
    print("-> Checking node health...")
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


def check_upgrade_state(miraged: str, rpc: str, phase: str, failures: list[str]) -> None:
    print("\n-> Checking upgrade state...")
    applied_height: int | None = None
    try:
        applied = _run_json([miraged, "q", "upgrade", "applied", UPGRADE_NAME, "--node", rpc, "-o", "json"])
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
            print(f"   [FAIL] upgrade {UPGRADE_NAME} not applied")
            failures.append(f"upgrade {UPGRADE_NAME} is not applied (or cannot be queried)")
        else:
            print(f"   [OK] upgrade applied: {UPGRADE_NAME} @ height {applied_height}")
        if plan is not None and plan.get("plan") not in (None, {}):
            failures.append(f"upgrade plan still present after upgrade: {plan.get('plan')!r}")
    else:
        if plan is None:
            print(f"   [FAIL] upgrade plan not found")
            failures.append(f"upgrade plan query failed (pre phase requires a plan): {plan_err}")
            return
        p = plan.get("plan", plan)
        name = p.get("name", "")
        if name != UPGRADE_NAME:
            print(f"   [FAIL] upgrade plan name: expected {UPGRADE_NAME}, got {name}")
            failures.append(f"upgrade plan name expected {UPGRADE_NAME!r}, got {name!r}")
        else:
            print(f"   [OK] upgrade plan: {name}")


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
                print(f"   [FAIL] Tier {i} ({name}): {', '.join(tier_errors[:3])}{'...' if len(tier_errors) > 3 else ''}")
                for err in tier_errors:
                    failures.append(f"core params.tiers[{i}].{err}")

    print("\n   Bridge chains:")
    bridge_chains = core.get("bridge_chains")
    if bridge_chains is None:
        print("   [FAIL] bridge_chains is None")
        failures.append("core params.bridge_chains must be an array (empty is valid), got None")
    elif not isinstance(bridge_chains, list):
        print(f"   [FAIL] bridge_chains expected list, got {type(bridge_chains)}")
        failures.append(f"core params.bridge_chains expected list, got {type(bridge_chains)}")
    elif len(bridge_chains) == 0:
        print("   [OK] bridge_chains: [] (empty)")
    else:
        print(f"   [OK] bridge_chains: {len(bridge_chains)} chain(s)")
        for idx, ch in enumerate(bridge_chains):
            if isinstance(ch, dict):
                chain_id = ch.get("chain_id", "?")
                enabled = ch.get("enabled", False)
                is_ibc = ch.get("is_ibc", False)
                bridge_type = "IBC" if is_ibc else "Attested"
                status = "enabled" if enabled else "disabled"
                print(f"      - {chain_id}: {bridge_type}, {status}")

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

    try:
        fee = _as_int(cfg.get("bridge_fee", 0))
        if fee == 1_000_000:
            print(f"   [OK] bridge_fee: {fee:,} (1 MIRAGE)")
        else:
            print(f"   [FAIL] bridge_fee: expected 1,000,000, got {fee:,}")
            failures.append(f"bridge config.bridge_fee expected 1_000_000, got {fee}")
    except Exception as e:
        print(f"   [FAIL] bridge_fee: invalid")
        failures.append(f"bridge config.bridge_fee invalid: {e}")

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

    try:
        core_fee = _as_int(core.get("bridge_fee", 0))
        cfg_fee = _as_int(cfg.get("bridge_fee", 0))
        if core_fee == cfg_fee:
            print(f"   [OK] bridge_fee: {core_fee:,} (matches)")
        else:
            print(f"   [FAIL] fee mismatch: core={core_fee}, config={cfg_fee}")
            failures.append(f"bridge_fee mismatch")
    except Exception as e:
        print(f"   [FAIL] cross-check fee: {e}")
        failures.append(f"cross-check bridge_fee failed: {e}")


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


def check_local_config(home_dir: Path, rpc_chain_id: str | None, failures: list[str], warnings: list[str]) -> None:
    print("\n-> Checking local config...")
    cfg_dir = home_dir / "node" / "config"

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
    parser = argparse.ArgumentParser(description="Verify Mirage v1.9.0-bridge upgrade")
    parser.add_argument("--node", default="http://127.0.0.1:26657", help="CometBFT RPC endpoint")
    parser.add_argument("--home", default=str(Path.home() / ".mirage"), help="Mirage home directory")
    parser.add_argument("--skip-config", action="store_true", help="Skip local config checks")
    parser.add_argument("--phase", choices=["pre", "post"], default="post", help="pre=plan exists, post=applied")
    args = parser.parse_args()

    rpc = args.node.rstrip("/")
    miraged = _find_miraged()
    home_dir = Path(args.home)

    failures: list[str] = []
    warnings: list[str] = []

    print("=" * 72)
    print(f"Verify {UPGRADE_NAME} ({datetime.now().isoformat()})")
    print("=" * 72)
    print(f"RPC:     {rpc}")
    print(f"HOME:    {home_dir}")
    print(f"miraged: {miraged}")
    print(f"phase:   {args.phase}")
    print()

    rpc_chain_id, _ = check_node_health(rpc, failures, warnings)
    check_upgrade_state(miraged, rpc, args.phase, failures)

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
