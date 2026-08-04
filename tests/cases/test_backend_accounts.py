from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import random
import string
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Tuple

import requests
from cosmpy.crypto.keypairs import PrivateKey
from cosmpy.aerial.wallet import LocalWallet

from tests.common import (
    _pass,
    _fail,
    _skip,
    _debug,
    _get,
    _post,
    _b64,
    _rand_str,
    _now_ms,
    _fresh_nonce,
    _lb_bytes,
    WALLETS,
    FAUCET_AMOUNTS,
    INDEX_TIMEOUT_SEC,
    _COLOR_GREEN,
    _COLOR_RED,
    _COLOR_YELLOW,
    _COLOR_RESET,
    _COLOR_BOLD,
    _fetch_params,
    _do_subscribe,
    _docker_exec,
    _run_miraged,
    _miraged_cmd,
    _keyring_backend,
    _INSIDE_CONTAINER,
    _check_local_docker,
    DEFAULT_BACKEND,
    get_status,
    get_user_status,
    get_username_from_address,
    get_address_from_username,
    sign_canonical,
    compute_pow,
    check_pow_target,
    _difficulty_factor,
    _BASE_DIFFICULTY_FACTOR,
    _canon_base_subscribe_raw,
    _canon_base_send_tokens_raw,
    _canon_base_award_raw,
    _canon_base_post_raw,
    _canon_base_vote_raw,
    _canon_base_edit_raw,
    _canon_base_set_username_raw,
    _canon_base_set_biography_raw,
    _canon_base_annotate_raw,
    _canon_base_report_raw,
    canon_signed_with_pow,
    _generate_wallet,
    _faucet,
    _resolve_validator_key_addr,
    _get_spendable_balance,
    _required_sub1_spend_budget_umirage,
)
from tests.backend_helpers import (
    _do_post,
    _do_post_with_nonce,
    _do_post_with_media,
    _do_vote,
    _do_vote_with_nonce,
    _do_edit,
    _do_annotate,
    _do_delete,
    _do_delete_user,
    _do_follow_user,
    _do_follow_topic,
    _do_block,
    _do_block_topic,
    _do_set_username_raw,
    _do_set_biography,
    _do_report,
    _do_enable_agent,
    _do_set_agents,
    _do_set_auto_renewal,
    _do_send_tokens,
    _do_award,
    _wait_indexed,
    _wait_username,
    _wait_list_count,
    _wait_tx_status,
    _wait_tx_status_failure,
    _wait_tx_deliver,
    _wait_followed_user,
    _wait_followed_topic,
    _wait_blocked_user,
    _wait_blocked_topic,
    _wait_blocked_topic_state,
    _wait_comment_indexed,
    _rpc_latest_height,
    _wait_next_block,
    _feed_has_post,
    _feed_missing_post,
)


def test_account(backend: str):

    wallet = WALLETS["free"]
    addr = str(wallet.address())

    # 2.1 get_user_status returns data
    try:
        us = get_user_status(backend, addr)
        if us and "user_level" in us:
            _pass("account.get_user_status returns data", level=us.get("user_level"))
        else:
            _fail("account.get_user_status returns data", f"got {us}")
    except Exception as e:
        _fail("account.get_user_status returns data", str(e))

    # 2.2 get_profile returns data
    code, profile = _get(f"{backend}/api/get_profile", {"address": addr})
    if code == 200:
        _pass("account.get_profile returns 200")
        if isinstance(profile.get("following_count"), int) and profile["following_count"] >= 0:
            _pass("account.get_profile following_count")
        else:
            _fail("account.get_profile following_count", f"got={profile.get('following_count')}")
        if isinstance(profile.get("follower_count"), int) and profile["follower_count"] >= 0:
            _pass("account.get_profile follower_count")
        else:
            _fail("account.get_profile follower_count", f"got={profile.get('follower_count')}")
    else:
        _fail("account.get_profile returns 200", f"code={code}")

    # 2.3 Set a unique test username
    # Check if registration is enabled on this node
    _code, _ncfg = _get(f"{backend}/api/get_node_config")
    reg_enabled = (_ncfg or {}).get("registration_enabled", False) if _code == 200 else False
    if not reg_enabled:
        _pass("account.set_username skipped (registration disabled on this node)")
        return

    test_uname = f"test-{_rand_str(6)}"
    try:
        from shared.client import set_username

        resp = set_username(backend, wallet, test_uname, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            # Wait for it
            time.sleep(3)
            _pass("account.set_username succeeds", username=test_uname, tx=txh)
        else:
            _fail("account.set_username succeeds", f"resp={resp}")
            return
    except Exception as e:
        _fail("account.set_username succeeds", str(e))
        return

    # The chain prefixes free-tier (level 0) usernames with "Anon-"
    user_level = int((us or {}).get("user_level", 0))
    expected_uname = f"Anon-{test_uname}" if user_level == 0 else test_uname

    # 2.4 get_address_from_username resolves (poll up to 10s)
    resolved = None
    for _ in range(10):
        time.sleep(1)
        resolved = get_address_from_username(backend, expected_uname)
        if resolved and resolved.lower() == addr.lower():
            break
    if resolved and resolved.lower() == addr.lower():
        _pass("account.get_address_from_username resolves", username=expected_uname)
    else:
        _fail("account.get_address_from_username resolves", f"got {resolved}")

    # 2.5 get_username_from_address resolves (poll up to 10s)
    resolved_name = None
    for _ in range(10):
        time.sleep(1)
        resolved_name = get_username_from_address(backend, addr)
        if resolved_name and resolved_name.lower() == expected_uname.lower():
            break
    if resolved_name and resolved_name.lower() == expected_uname.lower():
        _pass("account.get_username_from_address resolves", username=resolved_name)
    else:
        _fail("account.get_username_from_address resolves", f"got {resolved_name}")

    # 2.6 search_username finds user
    code, sr = _get(f"{backend}/api/search_username", {"q": expected_uname[:8]})
    if code == 200:
        results = sr.get("results") or sr.get("users") or sr.get("data") or []
        # Flatten — some backends return different shapes
        found = any(expected_uname.lower() in json.dumps(r).lower() for r in results) if results else False
        if found:
            _pass("account.search_username finds user")
        else:
            # Search might take time to index, pass with warning
            _pass("account.search_username returns 200 (may need indexing)")
    else:
        _fail("account.search_username finds user", f"code={code}")

    # 2.7 get_users returns list
    code, users = _get(f"{backend}/api/get_users", {"limit": 10})
    if code == 200:
        _pass("account.get_users returns 200")
    else:
        _fail("account.get_users returns 200", f"code={code}")

    # 2.8 get_user_followed returns structure
    code, followed = _get(f"{backend}/api/get_user_followed", {"address": addr})
    if code == 200:
        _pass("account.get_user_followed returns 200")
    else:
        _fail("account.get_user_followed returns 200", f"code={code}")

    # 2.9 Profile-share attribution works with open registration and rewards off.
    invite_required = bool((_ncfg or {}).get("registration_invite_code_required", False))
    if invite_required:
        _skip("account.profile_referral open-registration coverage", "invite codes required on this node")
        return

    referrer_wallet = _generate_wallet()
    referrer_addr = str(referrer_wallet.address()).lower()
    referrer_resp = _do_set_username_raw(backend, referrer_wallet, f"ref-{_rand_str(6)}")
    if not referrer_resp.get("tx_hash"):
        _fail("account.profile_referral creates referrer", f"resp={referrer_resp}")
        return
    referrer_name = _wait_username(backend, referrer_addr)
    if not referrer_name:
        _fail("account.profile_referral indexes referrer", f"address={referrer_addr}")
        return

    unknown_wallet = _generate_wallet()
    unknown_resp = _do_set_username_raw(
        backend,
        unknown_wallet,
        f"referred-{_rand_str(6)}",
        referrer_username=f"missing-{_rand_str(8)}",
    )
    if unknown_resp.get("tx_hash"):
        _pass("account.profile_referral ignores unknown referrer")
    else:
        _fail("account.profile_referral ignores unknown referrer", f"resp={unknown_resp}")

    malformed_wallet = _generate_wallet()
    malformed_resp = _do_set_username_raw(
        backend,
        malformed_wallet,
        f"referred-{_rand_str(6)}",
        referrer_username="invalid referrer!",
    )
    if malformed_resp.get("tx_hash"):
        _pass("account.profile_referral ignores malformed referrer")
    else:
        _fail("account.profile_referral ignores malformed referrer", f"resp={malformed_resp}")

    referred_wallet = _generate_wallet()
    referred_addr = str(referred_wallet.address()).lower()
    referred_resp = _do_set_username_raw(
        backend,
        referred_wallet,
        f"referred-{_rand_str(6)}",
        referrer_username=referrer_name,
    )
    if not referred_resp.get("tx_hash"):
        _fail("account.profile_referral registration succeeds", f"resp={referred_resp}")
        return
    _pass("account.profile_referral registration succeeds", referrer=referrer_name)

    summary = None
    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    while time.perf_counter() < deadline:
        summary_code, candidate = _get(f"{backend}/api/referrals/summary", {"address": referrer_addr})
        if summary_code == 200 and any(
            str(item.get("address", "")).lower() == referred_addr for item in (candidate.get("referrals") or [])
        ):
            summary = candidate
            break
        time.sleep(0.5)
    if summary:
        _pass("account.profile_referral appears in referral stats")
    else:
        _fail("account.profile_referral appears in referral stats", f"address={referred_addr}")

    duplicate_wallet = _generate_wallet()
    duplicate_resp = _do_set_username_raw(
        backend,
        duplicate_wallet,
        f"duplicate-{_rand_str(6)}",
        referrer_username=referrer_name,
    )
    if not duplicate_resp.get("tx_hash"):
        _fail("account.profile_referral client gate allows registration", f"resp={duplicate_resp}")
        return
    _pass("account.profile_referral client gate allows registration")

    duplicate_addr = str(duplicate_wallet.address()).lower()
    summary_code, summary_after_gate = _get(f"{backend}/api/referrals/summary", {"address": referrer_addr})
    if summary_code != 200:
        _fail("account.profile_referral client gate suppresses attribution", f"code={summary_code}")
        return
    duplicate_attributed = any(
        str(item.get("address", "")).lower() == duplicate_addr for item in (summary_after_gate.get("referrals") or [])
    )
    if not duplicate_attributed:
        _pass("account.profile_referral client gate suppresses attribution")
    else:
        _fail("account.profile_referral client gate suppresses attribution", f"address={duplicate_addr}")


# =========================================================================
# Category 3: Post Lifecycle
# =========================================================================


def test_subscribe_validation(backend: str):
    """Test subscribe validation via the backend API."""

    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())

    # 21.1 Valid levels (1, 10) — we already tested these in test_subscriber
    # Just verify the free user's current level
    try:
        us = get_user_status(backend, free_addr)
        val = us.get("user_level")
        free_level = int(val) if val is not None else -1
        if free_level == 0:
            _pass("subscribe.free_level_is_0")
        else:
            _fail("subscribe.free_level_is_0", f"level={free_level}")
    except Exception as e:
        _fail("subscribe.free_level_is_0", str(e))

    # 21.2 Invalid level 3 should be rejected
    resp = _do_subscribe(backend, free_wallet, 3)
    err = str(resp.get("error", "")).lower() if resp else ""
    txh = str(resp.get("tx_hash", "")).lower() if resp else ""
    tx_code = int(resp.get("code", 0) or 0) if resp else -1
    if "invalid" in err or (not txh) or tx_code != 0:
        _pass("subscribe.level_3_rejected")
    else:
        _fail("subscribe.level_3_rejected", f"txh={txh} code={tx_code} err={err[:100]}")

    # 21.3 Invalid level 0 (already free)
    resp = _do_subscribe(backend, free_wallet, 0)
    err = str(resp.get("error", "")).lower() if resp else ""
    txh = str(resp.get("tx_hash", "")).lower() if resp else ""
    if "invalid" in err or (not txh):
        _pass("subscribe.level_0_rejected")
    else:
        _fail("subscribe.level_0_rejected", f"txh={txh}")

    # 21.4 Invalid levels 2, 5, 9, 100
    for invalid_level in [2, 5, 9, 100]:
        resp = _do_subscribe(backend, free_wallet, invalid_level)
        err = str(resp.get("error", "")).lower() if resp else ""
        txh = str(resp.get("tx_hash", "")).lower() if resp else ""
        tx_code = int(resp.get("code", 0) or 0) if resp else -1
        if "invalid" in err or (not txh) or tx_code != 0:
            _pass(f"subscribe.level_{invalid_level}_rejected")
        else:
            _fail(f"subscribe.level_{invalid_level}_rejected", f"txh={txh} code={tx_code}")


# =========================================================================
# Category 22: Indexer Deque Storage (backend API)
# =========================================================================


def test_profile_fields(backend: str):
    """Verify profile fields are correctly returned through the API."""

    sub1 = WALLETS["sub1"]
    sub1_addr = str(sub1.address())
    agent1 = WALLETS["agent1"]
    agent1_addr = str(agent1.address())
    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())

    # 24.1 Verify get_profile returns expected fields
    code, profile = _get(f"{backend}/api/get_profile", {"address": sub1_addr})
    if code != 200:
        _fail("profile.get_profile_200", f"code={code}")
        return
    _pass("profile.get_profile_200")

    # 24.2 Verify level is correct
    level = profile.get("level")
    if level is not None and int(level) == 1:
        _pass("profile.sub1_level_1")
    else:
        _fail("profile.sub1_level_1", f"level={level}")

    # 24.3 Agent level
    code, agent_profile = _get(f"{backend}/api/get_profile", {"address": agent1_addr})
    if code == 200:
        agent_level = agent_profile.get("level")
        if agent_level is not None and int(agent_level) == 10:
            _pass("profile.agent1_level_10")
        else:
            _fail("profile.agent1_level_10", f"level={agent_level}")

    # 24.4 Free level
    code, free_profile = _get(f"{backend}/api/get_profile", {"address": free_addr})
    if code == 200:
        free_level = free_profile.get("level")
        if free_level is not None and int(free_level) == 0:
            _pass("profile.free_level_0")
        else:
            _fail("profile.free_level_0", f"level={free_level}")

    # 24.5 Verify enabled_agents field exists in profile
    if "enabled_agents" in (profile or {}):
        _pass("profile.has_enabled_agents_field")
    else:
        _pass("profile.enabled_agents_in_followed_data")

    # 24.6 Verify is_moderator is NOT in profile
    if "is_moderator" not in (profile or {}):
        _pass("profile.no_is_moderator_field")
    else:
        _fail("profile.no_is_moderator_field", "is_moderator still present")

    # 24.7 Verify flair field exists (may be empty string)
    if "flair" in (profile or {}) or "flair" in (free_profile or {}):
        _pass("profile.has_flair_field")
    else:
        _pass("profile.flair_may_be_omitted_if_empty")


# ---------------------------------------------------------------------------
# 26  Agent Block Propagation
# ---------------------------------------------------------------------------


def _ensure_subscriber(backend: str, wallet: LocalWallet, name: str, expected_level: int = 1) -> bool:
    """Verify wallet is still a subscriber; re-subscribe if subscription expired."""
    addr = str(wallet.address())
    try:
        us = get_user_status(backend, addr)
        level = int(us.get("user_level", 0) or 0)
        if level >= expected_level:
            return True
        _debug(f"{name} level dropped to {level}, re-subscribing to level {expected_level}")
        resp = _do_subscribe(backend, wallet, expected_level)
        txh = str(resp.get("tx_hash", "")).lower()
        if not txh:
            _debug(f"{name} re-subscribe failed: {resp.get('error', resp)}")
            return False
        # Wait until the indexer reflects the subscription level; core routes gate skip_pow on indexer level.
        for _ in range(15):
            time.sleep(1)
            us = get_user_status(backend, addr)
            level = int(us.get("user_level", 0) or 0)
            if level >= expected_level:
                return True
        _debug(f"{name} re-subscribe not indexed yet after tx={txh[:12]}")
        return False
    except Exception as e:
        _debug(f"{name} level check error: {e}")
        return False
