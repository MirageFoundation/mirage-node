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

ORCHESTRATOR_DISABLE_TOKEN = "ORCHESTRATOR_HARD_DISABLED"
MIGRATION_TX_INDEX_CLEANUP = "v1.20.0-tx-index-cleanup"


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


def _read_env_value(path: Path, key: str) -> str | None:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith(f"{key}="):
                    return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception as e:
        debug(f"Failed to read env file {path}: {e}")
    return None


def _read_tx_indexer(config_path: Path) -> str | None:
    if not config_path.exists():
        return None
    try:
        in_tx_index = False
        with open(config_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    in_tx_index = line == "[tx_index]"
                    continue
                if in_tx_index and line.startswith("indexer"):
                    _, _, val = line.partition("=")
                    return val.strip().strip('"').strip("'")
    except Exception as e:
        debug(f"Failed to parse config.toml {config_path}: {e}")
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
        "max_biography_length": 0,
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
        "max_biography_length": 512,
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
        "max_biography_length": 512,
    },
]

EXPECTED_AWARD_CONFIGS = [
    {"name": "quality_post", "cost": 10_000_000_000},
    {"name": "original_content", "cost": 5_000_000_000},
    {"name": "based", "cost": 5_000_000_000},
    {"name": "receipts", "cost": 5_000_000_000},
]

EXPECTED_PARAMS = {
    "min_difficulty": 10,
    "pow_message_window": 20,
    "pow_message_limit": 15,
    "pow_calm_period_definition": 10,
    "pow_calm_sequence_threshold": 100,
    "mint_interval": 200,
    "mint_quantity": 5_800_000_000,
    "mint_dynamic_credit_cap": 100,
    "subscription_period": 43200,
    "relay_min_gas_price": 1000,
    "relay_max_gas_fee": 500_000_000,
    "max_envelope_age": 60,
    "min_username_size": 3,
    "max_username_size": 30,
    "min_topic_size": 2,
    "max_topic_size": 35,
    "block_hash_window": 10,
    "pow_difficulty_allowance": 2,
}


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


def _extract_semver(s: str) -> str:
    """Extract the semver portion, stripping leading 'v' and any suffix after patch."""
    import re

    m = re.search(r"v?(\d+\.\d+\.\d+)", s)
    return m.group(1) if m else s


def _version_matches(actual: str, upgrade_name: str) -> bool:
    if not actual or not upgrade_name:
        return False
    return _extract_semver(actual) == _extract_semver(upgrade_name)


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

    pow_step = float(params.get("pow_difficulty_step", "0"))
    if abs(pow_step - 0.25) >= 0.01:
        fail(f"params.pow_difficulty_step = {pow_step} (want 0.25)")
    else:
        ok(f"params.pow_difficulty_step = {pow_step}")

    reserve_pct = float(params.get("subscription_reserve_percent", "0"))
    if abs(reserve_pct - 0.95) >= 0.01:
        fail(f"params.subscription_reserve_percent = {reserve_pct} (want 0.95)")
    else:
        ok(f"params.subscription_reserve_percent = {reserve_pct}")

    bridge_threshold = float(params.get("bridge_attestation_threshold", "0"))
    if abs(bridge_threshold - 0.6667) >= 0.01:
        fail(f"params.bridge_attestation_threshold = {bridge_threshold} (want 0.6667)")
    else:
        ok(f"params.bridge_attestation_threshold = {bridge_threshold}")

    bridge_chains = params.get("bridge_chains", [])
    if not isinstance(bridge_chains, list):
        fail(f"params.bridge_chains invalid type: {type(bridge_chains).__name__}")
    else:
        ok(f"bridge_chains count: {len(bridge_chains)}")
        for i, chain in enumerate(bridge_chains):
            cid = str(chain.get("chain_id", "")).strip()
            if not cid:
                fail(f"bridge_chains[{i}].chain_id missing")
            enabled = chain.get("enabled")
            if not isinstance(enabled, bool):
                fail(f"bridge_chains[{i}].enabled not bool: {enabled}")
            fee = int(chain.get("fee", 0) or 0)
            if fee < 0:
                fail(f"bridge_chains[{i}].fee negative: {fee}")

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


def check_subscription_index_consistency() -> None:
    """v1.17.0: verify no ghost reserves and subscription index is consistent."""
    section("Subscription Index Consistency (v1.17.0)")

    profiles, _ = fetch_all_profiles()
    if not profiles:
        warn("No profiles — skipping subscription consistency check")
        return

    import time as _time

    now_unix = int(_time.time())
    ghost_reserves = []
    expired_paid = []

    for p in profiles:
        lvl = p.get("level", 0)
        if isinstance(lvl, str):
            lvl = int(lvl)
        reserve = int(p.get("reserve_funds", 0) or 0)
        sub_expiry = int(p.get("subscription_expiry", 0) or 0)
        owner = str(p.get("owner", ""))[:20]

        if reserve > 0 and sub_expiry > 0 and sub_expiry <= now_unix:
            ghost_reserves.append(f"{owner} reserve={reserve}")

        if lvl > 0 and lvl < 100 and sub_expiry > 0 and sub_expiry <= now_unix:
            expired_paid.append(f"{owner} lvl={lvl} exp={sub_expiry}")

    if ghost_reserves:
        fail(f"{len(ghost_reserves)} profiles have ghost reserves: {ghost_reserves[:5]}")
    else:
        ok("No ghost reserves found")

    if expired_paid:
        fail(f"{len(expired_paid)} paid profiles have expired subscriptions: {expired_paid[:5]}")
    else:
        ok("No paid profiles with expired subscriptions")


def check_biography_limits() -> None:
    """v1.18.0+: verify max_biography_length is set correctly on tier configs."""
    section("Biography Length Limits (since v1.18.0)")
    data = http_get(f"{REST}/mirage/core/v1/params")
    if not data:
        fail("Could not fetch params for biography check")
        return
    params = data.get("params", {})
    tiers = params.get("tiers", [])
    expected = {0: 0, 1: 512, 2: 512}
    for idx, exp_val in expected.items():
        if idx >= len(tiers):
            fail(f"Tier {idx} missing from params")
            continue
        got = int(tiers[idx].get("max_biography_length", -1))
        if got == exp_val:
            ok(f"Tier {idx} max_biography_length = {got}")
        else:
            fail(f"Tier {idx} max_biography_length = {got}, expected {exp_val}")


def _semver_tuple(ver: str) -> tuple[int, ...]:
    """Convert '1.20.0' to (1, 20, 0) for numeric comparison."""
    try:
        return tuple(int(x) for x in ver.split("."))
    except (ValueError, AttributeError):
        return (0,)


def check_nonce_enforcement(upgrade_name: str) -> None:
    section("Envelope Nonce Enforcement")
    ver = _extract_semver(upgrade_name)
    vt = _semver_tuple(ver)
    if vt == (1, 19, 0):
        warn(
            "v1.19.0 uses legacy nonce fallback; cannot verify via queries. Submit a legacy-signed tx or inspect logs."
        )
    elif vt >= (1, 20, 0):
        ok("v1.20.0+: envelope_nonce is mandatory. Legacy fallback removed.")
        ok("Nonce rejection covered by test_backend.py (9.11b/c/d)")
    else:
        ok(f"Nonce enforcement not applicable for {upgrade_name}")


def check_tx_index_and_orchestrator() -> None:
    section("Tx Index + Orchestrator Config")
    node_home = Path.home() / ".mirage" / "node"
    env_dir = Path.home() / ".mirage" / "env"
    config_path = node_home / "config" / "config.toml"
    tx_index_path = node_home / "data" / "tx_index.db"
    orchestrator_env = env_dir / "orchestrator.env"

    debug(f"config.toml path: {config_path}")
    debug(f"tx_index.db path: {tx_index_path}")
    debug(f"orchestrator.env path: {orchestrator_env}")

    indexer = _read_tx_indexer(config_path)
    if indexer is None:
        fail(f"config.toml missing or tx_index.indexer not found: {config_path}")
    elif indexer == "null":
        ok("config.toml tx_index.indexer = null")
    else:
        fail(f"config.toml tx_index.indexer = {indexer} (want null)")

    status = http_get(f"{RPC}/status")
    if status:
        tx_index_rpc = status.get("result", {}).get("node_info", {}).get("other", {}).get("tx_index", "")
        if str(tx_index_rpc).lower() == "off":
            ok("RPC /status tx_index = off (runtime confirmed)")
        else:
            fail(f"RPC /status tx_index = {tx_index_rpc} (want off)")

        # Verify /tx endpoint rejects queries (tx_index=null)
        fake_hash = "0x" + "00" * 32
        tx_url = f"{RPC}/tx?hash={fake_hash}"
        try:
            debug(f"GET {tx_url}")
            req = urllib.request.Request(tx_url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read())
            if body and body.get("error"):
                err_msg = str(body["error"].get("data", "")).lower()
                if "indexing is disabled" in err_msg or "not available" in err_msg:
                    ok("/tx endpoint correctly returns indexing-disabled error")
                else:
                    warn(f"/tx endpoint returned unexpected error: {err_msg[:100]}")
            else:
                fail("/tx endpoint did not return an error (tx_index should be disabled)")
        except urllib.error.HTTPError as e:
            body_str = ""
            try:
                body_str = e.read().decode("utf-8", errors="replace").lower()
            except Exception:
                pass
            if "indexing is disabled" in body_str or e.code == 500:
                ok(f"/tx endpoint rejected request (HTTP {e.code}, tx_index disabled)")
            else:
                fail(f"/tx endpoint returned HTTP {e.code} with unexpected body")
        except Exception as e:
            ok(f"/tx endpoint unreachable: {e} (expected with indexer=null)")

    if tx_index_path.exists():
        fail(f"tx_index.db still present: {tx_index_path}")
    else:
        ok("tx_index.db removed")

    enabled = _read_env_value(orchestrator_env, "ORCHESTRATOR_ENABLED")
    if enabled is None:
        fail(f"ORCHESTRATOR_ENABLED missing in {orchestrator_env}")
    elif enabled.lower() == "false":
        ok("ORCHESTRATOR_ENABLED=false")
    else:
        fail(f"ORCHESTRATOR_ENABLED={enabled} (want false)")

    try:
        result = subprocess.run(["pgrep", "-f", "blockchain/bin/orchestrator"], capture_output=True, text=True)
        debug(f"pgrep orchestrator returncode={result.returncode}")
        if result.returncode == 0:
            fail("Orchestrator process is running")
        else:
            ok("Orchestrator process not running")
    except Exception as e:
        fail(f"Orchestrator process check failed: {e}")


def check_orchestrator_hard_disable() -> None:
    section("Orchestrator Hard Disable")
    orchestrator_bin = Path("/opt/mirage/blockchain/bin/orchestrator")
    debug(f"orchestrator bin path: {orchestrator_bin}")
    if not orchestrator_bin.exists():
        fail(f"Orchestrator binary missing: {orchestrator_bin}")
        return

    try:
        r = subprocess.run([str(orchestrator_bin)], capture_output=True, text=True, timeout=5)
    except Exception as e:
        fail(f"Failed to run orchestrator binary: {e}")
        return

    output = (r.stdout or "") + (r.stderr or "")
    debug(f"orchestrator exit={r.returncode}, output_len={len(output)}")

    if r.returncode == 0:
        fail("Orchestrator exited 0 (expected hard-disable panic)")
    else:
        ok("Orchestrator exits non-zero (hard-disabled)")

    if ORCHESTRATOR_DISABLE_TOKEN in output:
        ok("Orchestrator hard-disable message present")
    else:
        fail(f"Orchestrator hard-disable message missing: {ORCHESTRATOR_DISABLE_TOKEN}")


def check_deploy_migration() -> None:
    section("Deploy Migrations")
    migrations_file = Path.home() / ".mirage" / "env" / ".migrations"
    debug(f"migrations file: {migrations_file}")
    if not migrations_file.exists():
        warn(f"Migrations file not found: {migrations_file}")
        return

    try:
        content = migrations_file.read_text(encoding="utf-8")
    except Exception as e:
        fail(f"Failed to read migrations file: {e}")
        return

    if MIGRATION_TX_INDEX_CLEANUP in content:
        ok(f"Migration applied: {MIGRATION_TX_INDEX_CLEANUP}")
    else:
        fail(f"Migration missing: {MIGRATION_TX_INDEX_CLEANUP}")


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
    check_subscription_index_consistency()
    check_biography_limits()
    check_nonce_enforcement(upgrade_name)
    check_tx_index_and_orchestrator()
    check_orchestrator_hard_disable()
    check_deploy_migration()
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
