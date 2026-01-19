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
        "/opt/mirage/blockchain/miraged",  # inside container
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


def _run_text(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr}".strip())
    return (p.stdout or "").strip()


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


def _check_close(label: str, got: float, expected: float, failures: list[str], eps: float = 1e-9) -> None:
    if abs(got - expected) > eps:
        failures.append(f"{label} expected {expected!r}, got {got!r}")


def _read_text_if_exists(path: Path) -> str | None:
    try:
        if path.exists():
            return path.read_text()
    except Exception:
        return None
    return None


def _extract_toml_string_value(text: str, key: str) -> str | None:
    # minimal TOML for `key = "value"` on a single line
    # ignores commented lines
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
    # Source of truth: blockchain/x/core/types/params.go (DefaultParams + DefaultTiers)
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
        # Tier 0: Free
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
        # Tier 1: Trusted
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
        # Tier 2: Established
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
        # Tier 3: Distinguished
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


def check_node_health(rpc: str, failures: list[str], warnings: list[str]) -> tuple[str | None, str | None]:
    print("-> Checking node health (RPC)...")
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

        print("   [OK] RPC reachable")
        print(f"   [OK] Network: {network}")
        print(f"   [OK] Tendermint version: {tm_version}")
        print(f"   [OK] Latest block height: {latest_height}")
        if latest_time:
            print(f"   [OK] Latest block time: {latest_time}")
        if catching_up:
            warnings.append("node is catching up (syncing)")
            print("   [WARN] Node is catching up (syncing)")

        chain_id = network if isinstance(network, str) else None
        return chain_id, str(latest_height) if latest_height is not None else None
    except urllib.error.URLError as e:
        failures.append(f"RPC unreachable: {e}")
    except Exception as e:
        failures.append(f"RPC check failed: {e}")
    return None, None


def check_binary_version(miraged: str, failures: list[str], warnings: list[str]) -> None:
    print("\n-> Checking binary version...")
    try:
        v = _run_text([miraged, "version"])
        print(f"   [OK] miraged version: {v}")
        # allow formats like "v1.9.0" or "1.9.0"
        v_norm = v.strip()
        if v_norm.startswith("v"):
            v_norm = v_norm[1:]
        if not v_norm.startswith("1.9."):
            warnings.append(f"binary version does not look like 1.9.x: {v!r}")
    except Exception as e:
        failures.append(f"could not check binary version: {e}")


def check_upgrade_state(miraged: str, rpc: str, phase: str, failures: list[str]) -> None:
    print("\n-> Checking upgrade module state...")
    # applied
    applied_height: int | None = None
    try:
        applied = _run_json([miraged, "q", "upgrade", "applied", UPGRADE_NAME, "--node", rpc, "-o", "json"])
        # SDK prints {"height":"123"} typically
        h = applied.get("height", "0")
        applied_height = _as_int(h)
    except Exception:
        applied_height = None

    # plan
    plan: dict | None = None
    plan_err: str | None = None
    try:
        plan = _run_json([miraged, "q", "upgrade", "plan", "--node", rpc, "-o", "json"])
    except Exception as e:
        plan_err = str(e)

    if phase == "post":
        if applied_height is None or applied_height <= 0:
            failures.append(f"upgrade {UPGRADE_NAME} is not applied (or cannot be queried)")
        else:
            print(f"   [OK] upgrade applied: {UPGRADE_NAME} @ height {applied_height}")
        # In post phase there should be no pending plan (typical); if plan is present, fail.
        if plan is not None and plan.get("plan") not in (None, {}):
            failures.append(f"upgrade plan still present after upgrade: {plan.get('plan')!r}")
    else:
        # pre phase: plan must exist and match name
        if plan is None:
            failures.append(f"upgrade plan query failed (pre phase requires a plan): {plan_err}")
            return
        p = plan.get("plan", plan)
        name = p.get("name", "")
        if name != UPGRADE_NAME:
            failures.append(f"upgrade plan name expected {UPGRADE_NAME!r}, got {name!r}")
        else:
            print(f"   [OK] upgrade plan present: {name}")
        # applied may or may not exist in pre; if it does and is >0 that's fine.


def fetch_core_params(miraged: str, rpc: str) -> dict:
    # `miraged q core params` prints Params object directly (not wrapped).
    return _run_json([miraged, "q", "core", "params", "--node", rpc, "-o", "json"])


def check_core_params_exhaustive(core: dict, failures: list[str]) -> dict:
    print("\n-> Checking core params (EXHAUSTIVE)...")
    expected = _expected_core_params_v190()

    # Ensure required top-level keys exist
    must_have = list(expected.keys()) + ["tiers", "bridge_chains"]
    _require_keys(core, must_have, "core params", failures)

    # Scalars
    for k, v_exp in expected.items():
        if k not in core:
            continue
        try:
            if isinstance(v_exp, float):
                _check_close(f"core params.{k}", _as_float(core[k]), float(v_exp), failures)
            else:
                _check_equal(f"core params.{k}", _as_int(core[k]), int(v_exp), failures)
        except Exception as e:
            failures.append(f"core params.{k} invalid value {core[k]!r}: {e}")

    # Tiers: strict 4-tier schema with exact expected values for every field
    tiers = core.get("tiers")
    if isinstance(tiers, list):
        if len(tiers) != 4:
            failures.append(f"core params.tiers expected exactly 4 tiers, got {len(tiers)}")
        exp_tiers = _expected_tiers_v190()
        for i in range(min(len(tiers), 4)):
            t = tiers[i]
            if not isinstance(t, dict):
                failures.append(f"core params.tiers[{i}] expected object, got {type(t)}")
                continue
            exp = exp_tiers[i]
            _require_keys(t, list(exp.keys()), f"core params.tiers[{i}]", failures)
            for field, v_exp in exp.items():
                if field not in t:
                    continue
                try:
                    if isinstance(v_exp, bool):
                        _check_equal(f"core params.tiers[{i}].{field}", _as_bool(t[field]), v_exp, failures)
                    elif isinstance(v_exp, float):
                        _check_close(
                            f"core params.tiers[{i}].{field}", _as_float(t[field]), float(v_exp), failures
                        )
                    else:
                        _check_equal(f"core params.tiers[{i}].{field}", _as_int(t[field]), int(v_exp), failures)
                except Exception as e:
                    failures.append(f"core params.tiers[{i}].{field} invalid value {t[field]!r}: {e}")

    # Bridge chains: schema + invariants
    bridge_chains = core.get("bridge_chains")
    if bridge_chains is None:
        failures.append("core params.bridge_chains must be an array (empty is valid), got None")
    elif not isinstance(bridge_chains, list):
        failures.append(f"core params.bridge_chains expected list, got {type(bridge_chains)}")
    else:
        for idx, ch in enumerate(bridge_chains):
            if not isinstance(ch, dict):
                failures.append(f"core params.bridge_chains[{idx}] expected object, got {type(ch)}")
                continue
            _require_keys(
                ch,
                ["chain_id", "contract_address", "enabled", "is_ibc", "ibc_channel"],
                f"core params.bridge_chains[{idx}]",
                failures,
            )
            chain_id = ch.get("chain_id")
            if not isinstance(chain_id, str) or not chain_id.strip():
                failures.append(f"core params.bridge_chains[{idx}].chain_id must be non-empty string")
            try:
                is_ibc = _as_bool(ch.get("is_ibc"))
                _ = _as_bool(ch.get("enabled"))
            except Exception as e:
                failures.append(f"core params.bridge_chains[{idx}] bool fields invalid: {e}")
                continue
            contract_address = ch.get("contract_address", "")
            ibc_channel = ch.get("ibc_channel", "")

            if is_ibc:
                if not isinstance(ibc_channel, str) or not ibc_channel.strip():
                    failures.append(
                        f"core params.bridge_chains[{idx}]: is_ibc=true requires non-empty ibc_channel"
                    )
            else:
                if isinstance(ibc_channel, str) and ibc_channel.strip():
                    failures.append(
                        f"core params.bridge_chains[{idx}]: is_ibc=false requires ibc_channel to be empty"
                    )
                if not isinstance(contract_address, str) or not contract_address.strip():
                    failures.append(
                        f"core params.bridge_chains[{idx}]: is_ibc=false requires non-empty contract_address"
                    )

    print("   [OK] core params checked (see summary for failures)")
    return core


def fetch_bridge_status(miraged: str, rpc: str) -> dict:
    return _run_json([miraged, "q", "bridge", "status", "--node", rpc, "-o", "json"])


def fetch_bridge_config(miraged: str, rpc: str) -> dict:
    return _run_json([miraged, "q", "bridge", "config", "--node", rpc, "-o", "json"])


def _normalize_chain_cfg_list(lst: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for item in lst:
        cid = item.get("chain_id", "")
        if isinstance(cid, str) and cid.strip():
            out[cid] = item
    return out


def check_bridge_queries_strict(core: dict, status: dict, cfg: dict, failures: list[str]) -> None:
    print("\n-> Checking bridge queries (STRICT)...")
    _require_keys(status, ["enabled_chains", "pending_attestations_count"], "bridge status", failures)
    _require_keys(cfg, ["chains", "attestation_threshold", "bridge_fee"], "bridge config", failures)

    # Types
    enabled_chains = status.get("enabled_chains", [])
    if not isinstance(enabled_chains, list):
        failures.append(f"bridge status.enabled_chains expected list, got {type(enabled_chains)}")
        enabled_chains = []
    try:
        _ = _as_int(status.get("pending_attestations_count", 0))
    except Exception as e:
        failures.append(f"bridge status.pending_attestations_count invalid: {e}")

    chains = cfg.get("chains", [])
    if not isinstance(chains, list):
        failures.append(f"bridge config.chains expected list, got {type(chains)}")
        chains = []

    # Param equality vs expected constants
    try:
        _check_equal("bridge config.attestation_threshold", _as_int(cfg.get("attestation_threshold", 0)), 6667, failures)
    except Exception as e:
        failures.append(f"bridge config.attestation_threshold invalid: {e}")
    try:
        _check_equal("bridge config.bridge_fee", _as_int(cfg.get("bridge_fee", 0)), 1_000_000, failures)
    except Exception as e:
        failures.append(f"bridge config.bridge_fee invalid: {e}")

    # Cross-check vs core params
    try:
        _check_equal(
            "core.bridge_attestation_threshold vs bridge config.attestation_threshold",
            _as_int(core.get("bridge_attestation_threshold", 0)),
            _as_int(cfg.get("attestation_threshold", 0)),
            failures,
        )
    except Exception as e:
        failures.append(f"cross-check bridge_attestation_threshold failed: {e}")
    try:
        _check_equal(
            "core.bridge_fee vs bridge config.bridge_fee",
            _as_int(core.get("bridge_fee", 0)),
            _as_int(cfg.get("bridge_fee", 0)),
            failures,
        )
    except Exception as e:
        failures.append(f"cross-check bridge_fee failed: {e}")

    # Cross-check chain configs vs core.bridge_chains
    core_chains = core.get("bridge_chains", [])
    if not isinstance(core_chains, list):
        failures.append("core.bridge_chains is not a list; cannot cross-check chain configs")
        return
    core_by_id = _normalize_chain_cfg_list([c for c in core_chains if isinstance(c, dict)])
    cfg_by_id = _normalize_chain_cfg_list([c for c in chains if isinstance(c, dict)])

    # Every chain in core must exist in bridge config (same module storage)
    for cid in core_by_id.keys():
        if cid not in cfg_by_id:
            failures.append(f"bridge config missing chain present in core params: {cid!r}")

    # Enabled chains in status must be exactly those enabled in config (by chain_id)
    enabled_cfg = []
    for cid, item in cfg_by_id.items():
        try:
            if _as_bool(item.get("enabled", False)):
                enabled_cfg.append(cid)
        except Exception:
            # schema errors handled elsewhere
            pass
    enabled_status = []
    for item in enabled_chains:
        if isinstance(item, dict):
            cid = item.get("chain_id", "")
            if isinstance(cid, str) and cid.strip():
                enabled_status.append(cid)
    if sorted(enabled_status) != sorted(enabled_cfg):
        failures.append(
            f"enabled chains mismatch: status={sorted(enabled_status)!r} config={sorted(enabled_cfg)!r}"
        )

    print("   [OK] bridge queries checked (see summary for failures)")


def fetch_gov_params(miraged: str, rpc: str) -> dict:
    out = _run_json([miraged, "q", "gov", "params", "--node", rpc, "-o", "json"])
    return out.get("params", out)


def check_gov_params_strict(gp: dict, failures: list[str]) -> None:
    print("\n-> Checking gov params (STRICT)...")
    _require_keys(gp, ["min_deposit", "expedited_min_deposit"], "gov params", failures)

    def _coin_amount(coins: Any, denom: str) -> int:
        if not isinstance(coins, list):
            raise ValueError("expected list of coins")
        for c in coins:
            if isinstance(c, dict) and c.get("denom") == denom:
                return _as_int(c.get("amount", "0"))
        return 0

    try:
        min_amt = _coin_amount(gp.get("min_deposit", []), "umirage")
        _check_equal("gov min_deposit[umirage]", min_amt, 500_000_000_000, failures)
    except Exception as e:
        failures.append(f"gov min_deposit invalid: {e}")

    try:
        exp_amt = _coin_amount(gp.get("expedited_min_deposit", []), "umirage")
        _check_equal("gov expedited_min_deposit[umirage]", exp_amt, 1_000_000_000_000, failures)
    except Exception as e:
        failures.append(f"gov expedited_min_deposit invalid: {e}")

    # Presence checks for other key governance fields (don’t guess defaults here)
    for k in ["voting_period", "max_deposit_period", "quorum", "threshold", "veto_threshold"]:
        if k not in gp:
            failures.append(f"gov params: missing key {k!r}")

    print("   [OK] gov params checked (see summary for failures)")


def fetch_difficulty(miraged: str, rpc: str) -> dict:
    return _run_json([miraged, "q", "core", "difficulty", "--node", rpc, "-o", "json"])


def check_difficulty(d: dict, failures: list[str]) -> None:
    print("\n-> Checking difficulty endpoint...")
    _require_keys(d, ["current_difficulty"], "core difficulty", failures)
    try:
        cur = _as_int(d.get("current_difficulty", 0))
        if cur <= 0:
            failures.append(f"current_difficulty must be > 0, got {cur}")
        else:
            print(f"   [OK] current_difficulty: {cur}")
    except Exception as e:
        failures.append(f"core difficulty invalid: {e}")


def check_local_config(home_dir: Path, rpc_chain_id: str | None, failures: list[str], warnings: list[str]) -> None:
    print("\n-> Checking local node config (STRICT)...")
    cfg_dir = home_dir / "node" / "config"

    app_toml = cfg_dir / "app.toml"
    if app_toml.exists():
        txt = app_toml.read_text()
        min_gas = _extract_toml_string_value(txt, "minimum-gas-prices")
        if min_gas is None:
            failures.append("app.toml: missing minimum-gas-prices")
        else:
            _check_equal('app.toml minimum-gas-prices', min_gas, REQUIRED_MIN_GAS_PRICE, failures)
            if min_gas == REQUIRED_MIN_GAS_PRICE:
                print(f'   [OK] app.toml minimum-gas-prices = "{REQUIRED_MIN_GAS_PRICE}"')
    else:
        warnings.append(f"app.toml not found at {app_toml}")

    for name in ["config.toml", "client.toml", "genesis.json"]:
        p = cfg_dir / name
        if p.exists():
            print(f"   [OK] {name} exists")
        else:
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
                failures.append(f"genesis.json: invalid chain_id {cid!r}")
        except Exception as e:
            failures.append(f"genesis.json parse failed: {e}")

    if rpc_chain_id and genesis_chain_id:
        _check_equal("RPC chain-id vs genesis chain_id", rpc_chain_id, genesis_chain_id, failures)

    client_toml = cfg_dir / "client.toml"
    client_txt = _read_text_if_exists(client_toml)
    if client_txt is not None and genesis_chain_id:
        cfg_cid = _extract_toml_string_value(client_txt, "chain-id")
        if cfg_cid is None:
            warnings.append("client.toml: missing chain-id")
        else:
            _check_equal("client.toml chain-id vs genesis chain_id", cfg_cid, genesis_chain_id, failures)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Mirage v1.9.0-bridge upgrade (strict/exhaustive)")
    parser.add_argument("--node", default="http://127.0.0.1:26657", help="CometBFT RPC endpoint")
    parser.add_argument("--home", default=str(Path.home() / ".mirage"), help="Mirage home directory root (expects HOME/node/)")
    parser.add_argument("--skip-config", action="store_true", help="Skip local config file checks")
    parser.add_argument("--phase", choices=["pre", "post"], default="post", help="pre=plan must exist, post=applied required")
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

    # 1) RPC health
    rpc_chain_id, _ = check_node_health(rpc, failures, warnings)

    # 2) Binary
    check_binary_version(miraged, failures, warnings)

    # 3) Upgrade state
    check_upgrade_state(miraged, rpc, args.phase, failures)

    # 4) Core params (single fetch, exhaustive validation)
    try:
        core = fetch_core_params(miraged, rpc)
        check_core_params_exhaustive(core, failures)
    except Exception as e:
        failures.append(f"failed to fetch/validate core params: {e}")
        core = {}

    # 5) Bridge queries (must exist + must match core/config)
    try:
        b_status = fetch_bridge_status(miraged, rpc)
        b_cfg = fetch_bridge_config(miraged, rpc)
        if core:
            check_bridge_queries_strict(core, b_status, b_cfg, failures)
    except Exception as e:
        failures.append(f"bridge query failed: {e}")

    # 6) Gov params (strict deposits + presence checks)
    try:
        gp = fetch_gov_params(miraged, rpc)
        check_gov_params_strict(gp, failures)
    except Exception as e:
        failures.append(f"failed to fetch/validate gov params: {e}")

    # 7) Difficulty endpoint
    try:
        d = fetch_difficulty(miraged, rpc)
        check_difficulty(d, failures)
    except Exception as e:
        failures.append(f"failed to fetch/validate difficulty: {e}")

    # 8) Local config checks
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

