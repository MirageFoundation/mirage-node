#!/usr/bin/env python3
"""
Verify v1.6.0-personalized-feeds upgrade completed successfully.

Changes since prod (v1.5.0):

v1.5.1 upgrade:
- min_topic_size changed from 3 to 2
- GetTierConfig bugfix for admin levels

v1.6.0-personalized-feeds upgrade:
- Home feed with tier-weighted vote scores
- Following feed for subscribed users/topics
- Multi-topic/cross-posting removed
- MsgPost and MsgEdit use single `topic` string instead of `topics` array
- max_cross_posts removed from tier configs
- post_topics junction table dropped from indexer
- mint_interval changed from 20 blocks (1 min) to 200 blocks (10 min)
- max_topic_size changed from 50 to 35
- max_username_size changed from 40 to 30
- Content/title limits now count characters (Unicode code points), not bytes
  - Uses utf8.RuneCountInString() instead of len() in Go
  - "2000 characters" now means 2000 characters regardless of UTF-8 encoding

Checks:
1. Upgrade was applied
2. Params are queryable and valid:
   - min_topic_size == 2 (v1.5.1)
   - mint_interval == 200 (v1.6)
   - max_topic_size == 35 (v1.6)
   - max_username_size == 30 (v1.6)
   - No tier has max_cross_posts (v1.6)
3. Backend /api/get_config returns correct values
4. Functional tests (optional, if TEST_MNEMONIC set)
   - Post/Delete flow
   - Character counting (Unicode chars counted as 1, not multi-byte)
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from shared import canon as canon_shared
from shared import client as shared_client

UPGRADE_NAME = "v1.6.0-personalized-feeds"
MIRAGED_BIN = "/opt/mirage/blockchain/miraged"


def _run_cli(args: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
    """Run miraged CLI command."""
    bin_path = MIRAGED_BIN if Path(MIRAGED_BIN).exists() else "miraged"
    cmd = [bin_path] + args + ["--node", "tcp://127.0.0.1:26657"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, "", str(e)


def _get_backend_url() -> str:
    host = os.environ.get("BACKEND_HOST", "127.0.0.1")
    port = os.environ.get("BACKEND_PORT", "5000")
    return f"http://{host}:{port}"


def _api_get(endpoint: str, params: dict = None, timeout: float = 10.0) -> dict | None:
    url = f"{_get_backend_url()}/api/{endpoint}"
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _api_post(endpoint: str, data: dict, timeout: float = 30.0) -> dict | None:
    url = f"{_get_backend_url()}/api/{endpoint}"
    try:
        resp = requests.post(url, json=data, timeout=timeout)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def _hex_to_bytes(hex_str: str) -> bytes:
    """Convert hex string to bytes."""
    return bytes.fromhex(hex_str) if hex_str else b""


def create_wallet_from_mnemonic(mnemonic: str):
    """Create wallet from mnemonic using shared/client."""
    return shared_client.create_wallet_from_seed(mnemonic, prefix="mirage")


def get_last_block_hash() -> str:
    """Get latest block hash from backend."""
    resp = _api_get("get_parameters")
    if resp:
        return resp.get("last_block_hash", "")
    return ""


def submit_post(wallet, address: str, use_pow: bool, topic: str, title: str, content: str) -> tuple[bool, str]:
    """Submit a post transaction."""
    resp = _api_get("get_parameters", {"address": address})
    if not resp:
        return False, "Could not get parameters"

    block_hash_hex = resp.get("last_block_hash", "")
    block_hash = _hex_to_bytes(block_hash_hex)
    pub = wallet.public_key().public_key_bytes
    target = ""
    timestamp = int(time.time() * 1000)  # milliseconds

    if use_pow:
        diff = int(resp.get("pow_difficulty", 10))
        base = canon_shared.canon_base_post(pub, block_hash, diff, timestamp, target, topic, title, content)
        proof = shared_client.compute_pow(base, diff, block_hash_hex)
    else:
        diff = 0
        proof = 0
        base = canon_shared.canon_base_post(pub, block_hash, diff, timestamp, target, topic, title, content)

    canon = canon_shared.canon_signed_with_pow(base, proof)
    sig = shared_client.sign_canonical(wallet, canon)

    data = {
        "pubkey": base64.b64encode(pub).decode(),
        "signature": base64.b64encode(sig).decode(),
        "last_block_hash": block_hash_hex,
        "target": target,
        "topic": topic,
        "title": title,
        "content": content,
        "pow_difficulty": diff,
        "pow": proof,
        "timestamp": timestamp,
    }

    result = _api_post("core/post", data)
    if not result:
        return False, "No response"
    if "error" in result:
        return False, result["error"]
    if result.get("code", 0) != 0:
        return False, result.get("raw_log", "failed")
    return True, result.get("tx_hash", "")


def submit_delete(wallet, address: str, use_pow: bool, tx_hash: str) -> tuple[bool, str]:
    """Submit a delete transaction."""
    resp = _api_get("get_parameters", {"address": address})
    if not resp:
        return False, "Could not get parameters"

    block_hash_hex = resp.get("last_block_hash", "")
    block_hash = _hex_to_bytes(block_hash_hex)
    pub = wallet.public_key().public_key_bytes
    timestamp = int(time.time() * 1000)  # milliseconds

    if use_pow:
        diff = int(resp.get("pow_difficulty", 10))
        base = canon_shared.canon_base_delete(pub, block_hash, diff, timestamp, tx_hash)
        proof = shared_client.compute_pow(base, diff, block_hash_hex)
    else:
        diff = 0
        proof = 0
        base = canon_shared.canon_base_delete(pub, block_hash, diff, timestamp, tx_hash)

    canon = canon_shared.canon_signed_with_pow(base, proof)
    sig = shared_client.sign_canonical(wallet, canon)

    data = {
        "pubkey": base64.b64encode(pub).decode(),
        "signature": base64.b64encode(sig).decode(),
        "last_block_hash": block_hash_hex,
        "target": tx_hash,
        "pow_difficulty": diff,
        "pow": proof,
        "timestamp": timestamp,
    }

    result = _api_post("core/delete_post", data)
    if not result:
        return False, "No response"
    if "error" in result:
        return False, result["error"]
    if result.get("code", 0) != 0:
        return False, result.get("raw_log", "failed")
    return True, result.get("tx_hash", "")


def get_account_info(address: str) -> dict:
    """Get account info from backend."""
    return _api_get("get_config", {"address": address}) or {}


# ============================================================================
# Static Checks
# ============================================================================


def check_upgrade_applied() -> tuple[bool, str]:
    code, stdout, stderr = _run_cli(["query", "upgrade", "applied", UPGRADE_NAME])
    if code != 0:
        return False, f"Upgrade not applied: {stderr}"
    stripped = stdout.strip()
    if not stripped or stripped == "{}":
        return False, "Upgrade not yet applied"
    for line in stripped.split("\n"):
        if "height:" in line:
            height = line.split(":")[-1].strip().strip('"')
            return True, f"Applied at height {height}"
    return False, "Upgrade not yet applied (no height found)"


def check_params() -> tuple[bool, str]:
    """Check chain params for v1.5.1 and v1.6 breaking changes."""
    code, stdout, stderr = _run_cli(["query", "core", "params", "-o", "json"])
    if code != 0:
        return False, f"Could not query params: {stderr}"
    try:
        data = json.loads(stdout)
        params = data.get("params", data)
    except Exception as e:
        return False, f"Invalid JSON: {e}"

    errors = []

    # Check essential params exist
    essential = [
        "min_difficulty",
        "pow_message_window",
        "pow_message_limit",
        "mint_interval",
        "mint_quantity",
        "mint_dynamic_split",
        "subscription_period",
        "subscription_reserve_percent",
        "relay_min_gas_price",
        "relay_max_gas_fee",
        "max_envelope_age",
        "max_topic_size",
        "min_topic_size",
        "max_username_size",
        "min_username_size",
        "tiers",
    ]
    for field in essential:
        if field not in params:
            errors.append(f"Missing {field}")

    # v1.5.1 breaking change: min_topic_size must be 2
    min_topic_size = int(params.get("min_topic_size", 0))
    if min_topic_size != 2:
        errors.append(f"min_topic_size={min_topic_size}, expected 2 (v1.5.1)")

    # v1.6 breaking change: mint_interval must be 200 (10 mins)
    mint_interval = int(params.get("mint_interval", 0))
    if mint_interval != 200:
        errors.append(f"mint_interval={mint_interval}, expected 200 (v1.6)")

    # v1.6 breaking change: max_topic_size must be 35
    max_topic_size = int(params.get("max_topic_size", 0))
    if max_topic_size != 35:
        errors.append(f"max_topic_size={max_topic_size}, expected 35 (v1.6)")

    # v1.6 breaking change: max_username_size must be 30
    max_username_size = int(params.get("max_username_size", 0))
    if max_username_size != 30:
        errors.append(f"max_username_size={max_username_size}, expected 30 (v1.6)")

    # Check tiers
    tiers = params.get("tiers", [])
    if len(tiers) != 4:
        errors.append(f"Expected 4 tiers, got {len(tiers)}")

    # v1.6 breaking change: no tier should have max_cross_posts
    tier_fields = [
        "period_fee",
        "max_title_length",
        "max_content_length",
        "editing_time_mins",
        "archive_duration_days",
        "vote_weight",
    ]
    for i, tier in enumerate(tiers):
        # Check required fields exist
        for field in tier_fields:
            if field not in tier:
                errors.append(f"Tier {i}: missing {field}")
        # Check max_cross_posts is NOT present (v1.6 removal)
        if "max_cross_posts" in tier:
            errors.append(f"Tier {i}: has max_cross_posts (should be removed in v1.6)")

    if errors:
        return False, "; ".join(errors)

    return (
        True,
        f"{len(tiers)} tiers, min_topic_size={min_topic_size}, max_topic_size={max_topic_size}, mint_interval={mint_interval}",
    )


def check_profiles() -> tuple[bool, str]:
    code, stdout, stderr = _run_cli(["query", "core", "profiles", "-o", "json"], timeout=60)
    if code != 0:
        return False, f"Could not query profiles: {stderr}"
    try:
        data = json.loads(stdout)
        profiles = data.get("profiles", [])
    except Exception as e:
        return False, f"Invalid JSON: {e}"

    if not profiles:
        return False, "No profiles found"

    # Check first few profiles have expected fields
    required_fields = ["owner", "username", "level", "created_at"]
    errors = []
    for p in profiles[:5]:
        missing = [f for f in required_fields if f not in p]
        if missing:
            errors.append(f"{p.get('owner', '?')}: missing {missing}")

    if errors:
        return False, "; ".join(errors)

    return True, f"{len(profiles)} profiles OK"


def check_backend_config() -> tuple[bool, str]:
    """Check backend /api/get_config for v1.5.1 and v1.6 changes."""
    config = _api_get("get_config")
    if not config:
        return False, "Backend unavailable"
    if "error" in config:
        return False, config["error"]

    errors = []

    # Check required fields exist
    required = ["tiers", "max_topic_size", "min_topic_size", "subscription_period", "mint_interval"]
    for field in required:
        if field not in config:
            errors.append(f"Missing {field}")

    # v1.5.1: min_topic_size should be 2
    min_topic_size = int(config.get("min_topic_size", 0))
    if min_topic_size != 2:
        errors.append(f"min_topic_size={min_topic_size}, expected 2")

    # v1.6: mint_interval should be 200 (10 mins)
    mint_interval = int(config.get("mint_interval", 0))
    if mint_interval != 200:
        errors.append(f"mint_interval={mint_interval}, expected 200")

    # v1.6: max_topic_size should be 35
    max_topic_size = int(config.get("max_topic_size", 0))
    if max_topic_size != 35:
        errors.append(f"max_topic_size={max_topic_size}, expected 35")

    # v1.6: max_username_size should be 30
    max_username_size = int(config.get("max_username_size", 0))
    if max_username_size != 30:
        errors.append(f"max_username_size={max_username_size}, expected 30")

    # v1.6: no tier should have max_cross_posts
    tiers = config.get("tiers", [])
    for i, tier in enumerate(tiers):
        if "max_cross_posts" in tier:
            errors.append(f"Tier {i}: has max_cross_posts (should be removed)")

    # Check for new fields from dev (pow tracking)
    new_fields = ["pow_message_count", "pow_calm_sequence", "current_height"]
    for field in new_fields:
        if field not in config:
            errors.append(f"Missing new field {field}")

    if errors:
        return False, "; ".join(errors)

    return (
        True,
        f"{len(tiers)} tiers, min_topic_size={min_topic_size}, max_topic_size={max_topic_size}, current_height={config.get('current_height')}",
    )


# ============================================================================
# Functional Tests
# ============================================================================


def _query_chain_profile(address: str) -> dict:
    """Query profile directly from chain."""
    code, stdout, _ = _run_cli(["query", "core", "profile", address, "-o", "json"], timeout=30)
    if code != 0:
        return {}
    try:
        return json.loads(stdout)
    except Exception:
        return {}


def test_post_delete(wallet, address: str, use_pow: bool) -> tuple[bool, str]:
    """Test basic post and delete flow."""
    import random

    test_id = random.randint(10000, 99999)
    mode = "PoW" if use_pow else "fees"

    print(f"      [a] Post with {mode}...")
    ok, tx_hash = submit_post(
        wallet, address, use_pow=use_pow, topic="te", title=f"Test {test_id}", content="Test content"
    )
    if not ok:
        return False, f"Post failed: {tx_hash}"
    time.sleep(3)

    print(f"      [b] Delete with {mode}...")
    ok, msg = submit_delete(wallet, address, use_pow=use_pow, tx_hash=tx_hash)
    if not ok:
        return False, f"Delete failed: {msg}"

    return True, f"Post/Delete worked with {mode}"


def test_unicode_character_counting(wallet, address: str, use_pow: bool) -> tuple[bool, str]:
    """
    Test that content limits count characters, not bytes.

    v1.6 fix: Chain uses utf8.RuneCountInString() instead of len().
    Unicode chars like '→' (3 bytes) should count as 1 character.
    """
    import random

    # Get user's tier limit
    info = get_account_info(address)
    if not info:
        return False, "Could not get account info"

    level = info.get("user_level", 0)
    tiers = info.get("tiers", [])
    if not tiers or level >= len(tiers):
        return False, f"Invalid tier config: level={level}, tiers={len(tiers)}"

    tier = tiers[level]
    max_content = int(tier.get("max_content_length", 1000))

    # Create content with Unicode arrows (→ is 3 bytes in UTF-8, but 1 character)
    # We'll use exactly max_content characters, with some being multi-byte
    # If the chain counts bytes, this would exceed the limit; if characters, it should pass
    arrow = "→"  # 3 bytes, 1 character
    num_arrows = 50  # 50 arrows = 50 chars but 150 bytes
    padding_len = max_content - num_arrows - 20  # Leave room for test ID

    test_id = random.randint(10000, 99999)
    # Content: arrows + ASCII padding = exactly near the limit with multi-byte chars
    content = (arrow * num_arrows) + ("x" * padding_len) + f" test{test_id}"

    # Verify our test setup
    char_count = len(content)
    byte_count = len(content.encode("utf-8"))

    if char_count > max_content:
        return False, f"Test setup error: {char_count} chars > {max_content} limit"

    if byte_count <= max_content:
        # Byte count should exceed char limit to prove we're testing the right thing
        return False, f"Test setup: byte_count ({byte_count}) should exceed char limit ({max_content})"

    mode = "PoW" if use_pow else "fees"
    print(f"      Content: {char_count} chars, {byte_count} bytes (limit: {max_content})")
    print(f"      Posting with {mode}...")

    ok, tx_hash = submit_post(
        wallet, address, use_pow=use_pow, topic="te", title=f"Unicode test {test_id}", content=content
    )

    if not ok:
        # Check if the error mentions bytes - that would indicate the bug
        if "exceeds limit" in str(tx_hash) and str(byte_count) in str(tx_hash):
            return False, f"REGRESSION: Chain still counts bytes! Error: {tx_hash}"
        return False, f"Post failed: {tx_hash}"

    time.sleep(3)

    # Clean up
    print(f"      Deleting test post...")
    del_ok, del_msg = submit_delete(wallet, address, use_pow=use_pow, tx_hash=tx_hash)
    if not del_ok:
        print(f"      Warning: Delete failed: {del_msg}")

    return True, f"Unicode char counting works ({char_count} chars, {byte_count} bytes accepted)"


def run_functional_tests(mnemonic: str) -> tuple[bool, dict]:
    """Run functional tests."""
    results = {}

    try:
        wallet = create_wallet_from_mnemonic(mnemonic)
        address = str(wallet.address())
        print(f"   Derived address: {address}")
    except Exception as e:
        return False, {"error": f"Key derivation failed: {e}"}

    info = get_account_info(address)
    if not info:
        return False, {"error": "Could not get account info"}

    balance = info.get("user_balance", 0)
    level = info.get("user_level", 0)
    print(f"   Balance: {balance/1_000_000:.2f} MIRAGE, level: {level}")

    if balance < 100_000:
        return False, {"error": f"Need at least 0.1 MIRAGE, have {balance/1_000_000:.2f}"}

    # Test based on user level
    if level == 0:
        print("   [1] Post/Delete with PoW (level 0)...")
        ok, msg = test_post_delete(wallet, address, use_pow=True)
        results["pow_flow"] = {"success": ok, "message": msg}
        print(f"       {'OK' if ok else 'FAILED'}: {msg}")

        print("   [2] Unicode character counting with PoW (v1.6)...")
        ok, msg = test_unicode_character_counting(wallet, address, use_pow=True)
        results["unicode_chars"] = {"success": ok, "message": msg}
        print(f"       {'OK' if ok else 'FAILED'}: {msg}")
    else:
        print("   [1] Post/Delete with fees (level > 0)...")
        ok, msg = test_post_delete(wallet, address, use_pow=False)
        results["fees_flow"] = {"success": ok, "message": msg}
        print(f"       {'OK' if ok else 'FAILED'}: {msg}")

        print("   [2] Unicode character counting with fees (v1.6)...")
        ok, msg = test_unicode_character_counting(wallet, address, use_pow=False)
        results["unicode_chars"] = {"success": ok, "message": msg}
        print(f"       {'OK' if ok else 'FAILED'}: {msg}")

    all_ok = all(r.get("success", False) for r in results.values())
    return all_ok, results


# ============================================================================
# Main
# ============================================================================


def main() -> int:
    print(f"=== {UPGRADE_NAME} Upgrade Verification ===\n")

    all_ok = True

    # 1. Check upgrade applied
    print("1. Checking upgrade status...")
    ok, msg = check_upgrade_applied()
    print(f"   {'OK' if ok else 'FAILED'}: {msg}")
    if not ok:
        print("\n" + "=" * 50)
        print(f"RESULT: FAILED - Upgrade {UPGRADE_NAME} not applied")
        print("        Apply the upgrade proposal and rerun verification.")
        print("=" * 50)
        return 1

    # 2. Check params (includes v1.5.1 and v1.6 breaking changes)
    print("\n2. Checking chain params...")
    ok, msg = check_params()
    print(f"   {'OK' if ok else 'FAILED'}: {msg}")
    if not ok:
        all_ok = False

    # 3. Check profiles
    print("\n3. Checking profiles...")
    ok, msg = check_profiles()
    print(f"   {'OK' if ok else 'FAILED'}: {msg}")
    if not ok:
        all_ok = False

    # 4. Check backend config (includes v1.5.1 and v1.6 breaking changes)
    print("\n4. Checking backend /api/get_config...")
    ok, msg = check_backend_config()
    print(f"   {'OK' if ok else 'FAILED'}: {msg}")
    if not ok:
        all_ok = False

    # 5. Functional tests (optional)
    print("\n5. Functional tests...")
    mnemonic = os.environ.get("TEST_MNEMONIC", "")

    if not mnemonic:
        print("   Skipped (set TEST_MNEMONIC env var to run)")
        print("   Note: Static checks are sufficient for verification")
        functional_ok = True
        functional_results = {}
    else:
        try:
            wallet = create_wallet_from_mnemonic(mnemonic)
            address = str(wallet.address())
        except Exception as e:
            print(f"   ERROR: {e}")
            functional_ok = False
            functional_results = {"error": str(e)}
        else:
            functional_ok, functional_results = run_functional_tests(mnemonic)

    # Summary
    print("\n" + "=" * 50)
    print("=== SUMMARY ===")
    print("=" * 50)

    if functional_results:
        print("\nFunctional Tests:")
        if "error" in functional_results:
            print(f"  ERROR: {functional_results['error']}")
        else:
            for name, r in functional_results.items():
                status = "OK" if r.get("success") else "FAILED"
                print(f"  {name}: {status} - {r.get('message', '')}")

    print()
    if all_ok and functional_ok:
        print(f"RESULT: SUCCESS - {UPGRADE_NAME} verified!")
        return 0
    elif all_ok:
        print("RESULT: PARTIAL - Static checks OK, functional tests failed")
        return 1
    else:
        print("RESULT: FAILED - Static checks failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
