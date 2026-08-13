#!/usr/bin/env python3
"""
Post-deploy verification for v1.34.0.

Per the /upgrade workflow this file is rewritten every release to check ONLY
what THIS release changes:

  python scripts/verify_upgrade.py
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py

What v1.34.0 changes (deploy-visible)
-------------------------------------
Consensus-breaking hardening from the 2026-08-07 blockchain review:

  * store read/write failures on consensus inputs reject the tx or fail the
    block instead of decoding as zero (M-1, M-2, M-3, M-5, M-6);
  * Params gained operational upper bounds and every cast/multiply/expiry
    computation is checked (M-7);
  * MsgUpdateParams requires an explicit update_mask, so governance can set a
    parameter to zero on purpose and cannot silently skip a field (L-9);
  * subscription reserve/burn split is computed in basis points and sums exactly
    to the period fee (L-4).

Checks:

  1. Frontend version.txt reports v1.34.1.
  2. Chain binary version reports v1.34.1.
  3. Upgrade handler name v1.34.0 is applied (applied_plan query) — the chain
     upgrade stays v1.34.0 because v1.34.1 ships no consensus change.
  4. Chain is live and has produced blocks past the upgrade height.
  5. Every parameter the new runtime arithmetic reads is present in the params
     query. A missing field is a hard failure: the runtime has no fallback.
  6. Stored params satisfy the full Params.Validate rule set, including the new
     operational bounds. The upgrade handler refuses to complete otherwise;
     this re-checks the live chain after later governance proposals.
  7. The indexer topic-attribution repair applied and left no drifted rows.
  8. LEGACY_UNSIGNED_UNTIL is gone from backend.env, so reward claims cannot
     fall through to the removed unsigned path.

Checks 7 and 8 read deployment artifacts (the indexer database, backend.env)
that exist inside the container but not in a plain source checkout. When the
artifact is absent they report NOTE and do not affect the exit code, because a
missing artifact means "not verifiable from here", not "verified". Run the
docker form above for the full set — a run that only prints NOTE for 7 and 8 has
not checked them.

This script is read-only: it never broadcasts. Two properties of this release
cannot be observed read-only and are proven by tests instead:

  * mask-driven zero-value governance updates —
    tests/test_blockchain.py --category params_mask
  * fail-fast store semantics —
    blockchain/x/core/module/store_failures_test.go
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# The shipped software version, checked against version.txt and the binary.
RELEASE_VERSION = "v1.34.1"
# The chain upgrade handler this release runs on. These diverge whenever a patch
# ships without a consensus-breaking change: v1.34.1 is backend-only, so the
# applied plan on chain is still the one v1.34.0 scheduled and there is no
# v1.34.1 plan to query.
UPGRADE_NAME = "v1.34.0"
COMET_RPC_URL = "http://127.0.0.1:26657"
REST_URL = "http://127.0.0.1:1317"

# Blocks the chain must have produced after the upgrade height before the
# upgrade counts as "live", not just "applied".
MIN_BLOCKS_AFTER_UPGRADE = 5

# Read-only mirror of Params.Validate() and its v1.34.0 bounds in
# blockchain/x/core/types/params.go. Keep both the values and cross-field rules
# in sync.
INTEGER_PARAM_BOUNDS = {
    "min_difficulty": (1, 256),
    "pow_message_window": (1, 1_000),
    "pow_message_limit": (1, 18_446_744_073_709_551_615),
    "pow_calm_period_definition": (0, 18_446_744_073_709_551_615),
    "pow_calm_sequence_threshold": (1, 1_000_000),
    "mint_interval": (1, 10_512_000),
    "mint_quantity": (1, 10_000_000_000_000),
    "mint_dynamic_credit_cap": (0, 18_446_744_073_709_551_615),
    # Floor is MinBlockHashWindow: below it the PoW window rejects envelopes that
    # max_envelope_age still accepts, so the upgrade widens a stored value of 10.
    "block_hash_window": (20, 1_000),
    "subscription_reserve_bps": (0, 10_000),
    "pow_difficulty_allowance": (0, 18_446_744_073_709_551_615),
    "min_username_size": (1, 64),
    "max_username_size": (1, 128),
    "min_topic_size": (1, 100),
    "max_topic_size": (1, 100),
    "relay_min_gas_price": (0, 1_000_000_000),
    "relay_max_gas_fee": (0, 100_000_000_000),
    "max_envelope_age": (1, 86_400),
    "subscription_period": (0, 525_600),
}
FLOAT_PARAM_BOUNDS = {
    "mint_dynamic_split": (0.0, 1.0),
    # Superseded by subscription_reserve_bps; v1.34.0 converts and zeroes it, and
    # Params.Validate rejects any non-zero value from then on.
    "subscription_reserve_percent": (0.0, 0.0),
    "pow_difficulty_step": (0.01, 1.0),
}
MAX_PROFILE_LIST_ENTRIES = 4_294_967_295
MAX_VOTE_WEIGHT = 100.0
MAX_AWARD_CONFIG_COST = 1_000_000_000_000
PROFILE_LIST_LIMIT_FIELDS = (
    "max_enabled_agents",
    "max_followed_users",
    "max_followed_topics",
    "max_blocked_users",
    "max_blocked_posts",
    "max_blocked_topics",
)

# Every field in Params. Presence is checked separately from value validation so
# a generated-query/schema mismatch cannot hide behind a numeric default.
REQUIRED_PARAMS = (
    "min_difficulty",
    "pow_message_window",
    "pow_message_limit",
    "pow_calm_period_definition",
    "pow_calm_sequence_threshold",
    "pow_difficulty_allowance",
    "mint_interval",
    "mint_quantity",
    "mint_dynamic_credit_cap",
    "mint_dynamic_split",
    "block_hash_window",
    "min_username_size",
    "max_username_size",
    "min_topic_size",
    "max_topic_size",
    "max_envelope_age",
    "subscription_period",
    "subscription_reserve_percent",
    "subscription_reserve_bps",
    "tiers",
    "relay_min_gas_price",
    "relay_max_gas_fee",
    "pow_difficulty_step",
    "award_configs",
)

passed = 0
failed = 0


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  PASS  {msg}")


def fail(msg: str) -> None:
    global failed
    failed += 1
    print(f"  FAIL  {msg}")


def note(msg: str) -> None:
    """Informational only — does not affect the exit code."""
    print(f"  NOTE  {msg}")


def http_json(url: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # urllib's message is just the status line; the gRPC-gateway puts the
        # actual reason in the body, which is the only useful part here.
        raise RuntimeError(f"HTTP {e.code} from {url}: {e.read().decode()[:300]}") from None


def check_version_txt() -> None:
    candidates = [
        Path("/opt/mirage/web/frontend/build/version.txt"),
        Path("/opt/mirage/web/frontend/public/version.txt"),
        Path(__file__).resolve().parent.parent / "web" / "frontend" / "public" / "version.txt",
    ]
    for p in candidates:
        if p.is_file():
            ver = p.read_text().strip()
            if ver == RELEASE_VERSION:
                ok(f"version.txt={ver} ({p})")
            else:
                fail(f"version.txt={ver!r} want {RELEASE_VERSION} ({p})")
            return
    fail("version.txt not found")


def check_binary_version() -> None:
    bin_candidates = [
        "/usr/local/bin/miraged",
        "/root/go/bin/miraged",
        str(Path(__file__).resolve().parent.parent / "blockchain" / "bin" / "miraged"),
        str(Path(__file__).resolve().parent.parent / "blockchain" / "miraged"),
    ]
    for b in bin_candidates:
        if not os.path.isfile(b):
            continue
        try:
            out = subprocess.check_output([b, "version", "--long"], stderr=subprocess.STDOUT, timeout=10).decode()
        except Exception as e:
            fail(f"miraged version failed ({b}): {e}")
            return
        if RELEASE_VERSION.lstrip("v") in out or RELEASE_VERSION in out:
            ok(f"binary version contains {RELEASE_VERSION} ({b})")
        else:
            fail(f"binary version {out.strip()[:120]!r} does not contain {RELEASE_VERSION} ({b})")
        return
    fail("miraged binary not found")


def applied_upgrade_height() -> int:
    """Height at which the UPGRADE_NAME plan was applied. Raises if not applied."""
    data = http_json(f"{REST_URL}/cosmos/upgrade/v1beta1/applied_plan/{UPGRADE_NAME}")
    height = int(data.get("height") or data.get("Height") or 0)
    if height <= 0:
        raise RuntimeError(f"upgrade {UPGRADE_NAME} not applied: {data}")
    return height


def check_upgrade_applied() -> None:
    try:
        height = applied_upgrade_height()
    except Exception as e:
        fail(f"applied_plan check failed: {e}")
        return
    ok(f"upgrade {UPGRADE_NAME} applied at height={height}")


def check_chain_live_past_upgrade() -> None:
    """The fail-fast contract in this release turns a bad consensus write into a
    halted block, so 'applied' is not enough: the chain must keep producing
    blocks after the upgrade height.
    """
    try:
        head = int(http_json(f"{COMET_RPC_URL}/status")["result"]["sync_info"]["latest_block_height"])
    except Exception as e:
        fail(f"comet status failed: {e}")
        return
    if head <= 0:
        fail(f"chain height={head}")
        return

    try:
        upgrade_height = applied_upgrade_height()
    except Exception as e:
        fail(f"chain liveness check: {e}")
        return

    produced = head - upgrade_height
    if produced >= MIN_BLOCKS_AFTER_UPGRADE:
        ok(f"chain live at height={head}, {produced} block(s) after the upgrade height {upgrade_height}")
    else:
        fail(
            f"chain at height={head} has produced only {produced} block(s) since the upgrade height "
            f"{upgrade_height}; want at least {MIN_BLOCKS_AFTER_UPGRADE}"
        )


def query_params() -> dict:
    return (http_json(f"{REST_URL}/mirage/core/v1/params").get("params")) or {}


def check_required_params_present() -> None:
    try:
        params = query_params()
    except Exception as e:
        fail(f"params query failed: {e}")
        return
    missing = [name for name in REQUIRED_PARAMS if params.get(name) is None]
    if missing:
        fail(f"params query is missing required field(s): {missing}")
        return
    ok(f"all {len(REQUIRED_PARAMS)} runtime-required params present")


def check_param_bounds() -> None:
    try:
        params = query_params()
    except Exception as e:
        fail(f"params bounds check: params query failed: {e}")
        return

    violations: list[str] = []
    checked = 0
    int_values: dict[str, int] = {}
    for name, (low, high) in INTEGER_PARAM_BOUNDS.items():
        checked += 1
        raw = params.get(name)
        if raw is None:
            violations.append(f"{name} missing")
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            violations.append(f"{name}={raw!r} not an integer")
            continue
        int_values[name] = value
        if value < low or value > high:
            violations.append(f"{name}={value} outside [{low}, {high}]")

    for name, (low, high) in FLOAT_PARAM_BOUNDS.items():
        checked += 1
        raw = params.get(name)
        try:
            value = float(raw)
            if not math.isfinite(value):
                violations.append(f"{name}={value} is not finite")
            elif value < low or value > high:
                violations.append(f"{name}={value} outside [{low}, {high}]")
        except (TypeError, ValueError):
            violations.append(f"{name}={raw!r} not a number")

    pow_limit = int_values.get("pow_message_limit")
    calm_definition = int_values.get("pow_calm_period_definition")
    if pow_limit is not None and calm_definition is not None and calm_definition >= pow_limit:
        violations.append(
            f"pow_calm_period_definition={calm_definition} must be < pow_message_limit={pow_limit}"
        )

    pow_window = int_values.get("pow_message_window")
    allowance = int_values.get("pow_difficulty_allowance")
    if pow_window is not None and allowance is not None and allowance > 2 * pow_window:
        violations.append(
            f"pow_difficulty_allowance={allowance} must be <= 2*pow_message_window={2 * pow_window}"
        )

    min_username = int_values.get("min_username_size")
    max_username = int_values.get("max_username_size")
    if min_username is not None and max_username is not None and min_username > max_username:
        violations.append(f"min_username_size={min_username} exceeds max_username_size={max_username}")

    min_topic = int_values.get("min_topic_size")
    max_topic = int_values.get("max_topic_size")
    if min_topic is not None and max_topic is not None and min_topic > max_topic:
        violations.append(f"min_topic_size={min_topic} exceeds max_topic_size={max_topic}")

    tiers = params.get("tiers")
    if not isinstance(tiers, list) or len(tiers) != 3:
        violations.append(f"tiers must contain exactly 3 entries, got {tiers!r}")
    else:
        for index, tier in enumerate(tiers):
            if not isinstance(tier, dict):
                violations.append(f"tiers[{index}] is not an object")
                continue
            for name in PROFILE_LIST_LIMIT_FIELDS:
                checked += 1
                raw = tier.get(name)
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    violations.append(f"tiers[{index}].{name}={raw!r} not an integer")
                    continue
                if value < 0 or value > MAX_PROFILE_LIST_ENTRIES:
                    violations.append(
                        f"tiers[{index}].{name}={value} outside [0, {MAX_PROFILE_LIST_ENTRIES}]"
                    )
            for name in ("period_fee", "max_title_length", "max_content_length"):
                checked += 1
                raw = tier.get(name)
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    violations.append(f"tiers[{index}].{name}={raw!r} not an integer")
                    continue
                if value < 0:
                    violations.append(f"tiers[{index}].{name}={value} must be non-negative")
                if name in ("max_title_length", "max_content_length") and value == 0:
                    violations.append(f"tiers[{index}].{name} must be > 0")
                if index == 0 and name == "period_fee" and value != 0:
                    violations.append(f"tiers[0].period_fee={value} must be 0")

            checked += 1
            raw_vote_weight = tier.get("vote_weight")
            try:
                vote_weight = float(raw_vote_weight)
                if not math.isfinite(vote_weight):
                    violations.append(f"tiers[{index}].vote_weight={vote_weight} is not finite")
                elif vote_weight < 0.0 or vote_weight > MAX_VOTE_WEIGHT:
                    violations.append(
                        f"tiers[{index}].vote_weight={vote_weight} outside [0.0, {MAX_VOTE_WEIGHT}]"
                    )
            except (TypeError, ValueError):
                violations.append(f"tiers[{index}].vote_weight={raw_vote_weight!r} not a number")

    award_configs = params.get("award_configs")
    if not isinstance(award_configs, list) or not award_configs:
        violations.append(f"award_configs must be a non-empty list, got {award_configs!r}")
    else:
        award_names: set[str] = set()
        for index, award in enumerate(award_configs):
            if not isinstance(award, dict):
                violations.append(f"award_configs[{index}] is not an object")
                continue
            checked += 2
            name = award.get("name")
            if not isinstance(name, str) or name == "":
                violations.append(f"award_configs[{index}].name must be non-empty")
            elif name in award_names:
                violations.append(f"award_configs[{index}].name={name!r} is duplicated")
            else:
                award_names.add(name)
            raw_cost = award.get("cost")
            try:
                cost = int(raw_cost)
            except (TypeError, ValueError):
                violations.append(f"award_configs[{index}].cost={raw_cost!r} not an integer")
                continue
            if cost < 0 or cost > MAX_AWARD_CONFIG_COST:
                violations.append(
                    f"award_configs[{index}].cost={cost} outside [0, {MAX_AWARD_CONFIG_COST}]"
                )

    if violations:
        fail("stored params violate Params.Validate(): " + "; ".join(violations))
        return
    ok(f"stored params satisfy the v1.34.0 Params.Validate() rules ({checked} values checked)")


INDEXER_REPAIR_MIGRATION = "v1.34.0_repair_topic_attribution"

# Canonical definition of a (owner, topic) stats row, mirroring
# DatabaseManager._VOTE_STATS_FROM_CANONICAL and the rebuild migration. A row
# that disagrees means a topic edit stranded attribution again.
DRIFTED_TOPIC_ROWS_SQL = """
    SELECT COUNT(*) FROM (
        SELECT s.owner, s.topic
        FROM user_topic_stats s
        LEFT JOIN (
            SELECT LOWER(v.owner) AS owner,
                   LOWER(COALESCE(NULLIF(p.root_topic, ''), p.topic)) AS topic,
                   SUM(CASE WHEN v.user_vote > 0 THEN 1 WHEN v.user_vote < 0 THEN -1 ELSE 0 END)::int AS net
            FROM votes v
            JOIN posts p ON LOWER(p.txhash) = LOWER(v.target)
            WHERE COALESCE(NULLIF(p.root_topic, ''), p.topic) <> ''
            GROUP BY 1, 2
        ) d ON d.owner = s.owner AND d.topic = s.topic
        WHERE s.net_votes <> COALESCE(d.net, 0)
    ) mismatched
"""


def indexer_db_url() -> str:
    """INDEXER_DB_URL from the environment, or from the deployed env files.

    `docker exec mirage python3 .../verify_upgrade.py` — the invocation in this
    file's docstring — does not source the env files, so reading them directly is
    what makes the check run instead of reporting NOTE for a solvable reason.
    """
    from_env = os.environ.get("INDEXER_DB_URL", "").strip()
    if from_env:
        return from_env
    env_dir = Path("/root/.mirage/env")
    if not env_dir.is_dir():
        return ""
    for env_file in sorted(env_dir.glob("*.env")):
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("INDEXER_DB_URL="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def check_topic_attribution_repaired() -> None:
    """The repair migration asserts this invariant before it writes its marker,
    so a missing marker plus drifted rows means it never ran on this host.
    """
    db_url = indexer_db_url()
    if not db_url:
        note("no INDEXER_DB_URL in the environment or /root/.mirage/env: "
             "topic-attribution repair not verifiable from here")
        return
    try:
        import psycopg
    except ImportError:
        note("psycopg unavailable: topic-attribution repair not verifiable from here")
        return

    try:
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT value FROM meta WHERE key = %s",
                    (f"migration_{INDEXER_REPAIR_MIGRATION}",),
                )
                row = cur.fetchone()
                cur.execute(DRIFTED_TOPIC_ROWS_SQL)
                drifted = int(cur.fetchone()[0])
    except Exception as e:
        fail(f"topic-attribution check failed: {e}")
        return

    if row is None:
        fail(f"indexer migration {INDEXER_REPAIR_MIGRATION} has not been applied")
    elif drifted:
        fail(f"{drifted} (owner, topic) row(s) disagree with their canonical votes after the repair")
    else:
        ok(f"topic attribution repaired ({INDEXER_REPAIR_MIGRATION}) with no drifted rows")


def check_claim_grace_removed() -> None:
    """v1.34.0 ends the unsigned reward-claim window early; the deploy migration
    removes the key so nothing can re-open it by setting a future date.
    """
    env_path = Path("/root/.mirage/env/backend.env")
    if not env_path.is_file():
        note(f"{env_path} absent: claim-grace removal not verifiable from here")
        return
    offending = [
        line.strip()
        for line in env_path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("LEGACY_UNSIGNED_UNTIL=")
    ]
    if offending:
        fail(f"backend.env still defines {offending[0]}")
    else:
        ok("backend.env has no LEGACY_UNSIGNED_UNTIL")


def main() -> int:
    print(f"verify_upgrade.py for {RELEASE_VERSION}")
    check_version_txt()
    check_binary_version()
    check_upgrade_applied()
    check_chain_live_past_upgrade()
    check_required_params_present()
    check_param_bounds()
    check_topic_attribution_repaired()
    check_claim_grace_removed()
    note(
        "mask-driven zero-value governance updates are proven by "
        "tests/test_blockchain.py --category params_mask (local testnet only); "
        "fail-fast store semantics by blockchain/x/core/module/store_failures_test.go"
    )
    print(f"\nResult: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
