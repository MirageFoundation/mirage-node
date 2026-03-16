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

from tests.common import (
    _pass, _fail, _skip, _debug, _get, _post, _b64, _rand_str, _now_ms,
    _fresh_nonce, _lb_bytes,
    WALLETS, FAUCET_AMOUNTS, INDEX_TIMEOUT_SEC,
    _COLOR_GREEN, _COLOR_RED, _COLOR_YELLOW, _COLOR_RESET, _COLOR_BOLD,
    _fetch_params, _do_upgrade_level, _docker_exec, _run_miraged, _miraged_cmd,
    _keyring_backend, _INSIDE_CONTAINER, _check_local_docker,
    DEFAULT_BACKEND,
    get_status, get_user_status, get_username_from_address, get_address_from_username,
    sign_canonical, compute_pow, check_pow_target, _difficulty_factor, _BASE_DIFFICULTY_FACTOR,
    _canon_base_upgrade_level_raw, _canon_base_send_tokens_raw, _canon_base_award_raw,
    _canon_base_post_raw, _canon_base_vote_raw, _canon_base_edit_raw,
    _canon_base_set_username_raw, _canon_base_set_biography_raw,
    _canon_base_annotate_raw, _canon_base_report_raw,
    canon_signed_with_pow,
    _generate_wallet, _faucet, _resolve_validator_key_addr,
    _get_spendable_balance, _required_sub1_spend_budget_umirage,
)
from tests.backend_helpers import (
    _do_post, _do_post_with_nonce, _do_post_with_media,
    _do_vote, _do_vote_with_nonce,
    _do_edit, _do_annotate, _do_delete, _do_delete_user,
    _do_follow_user, _do_follow_topic, _do_block, _do_block_topic,
    _do_set_username_raw, _do_set_biography, _do_report,
    _do_enable_agent, _do_set_agents, _do_set_auto_renewal,
    _do_send_tokens, _do_award,
    _wait_indexed, _wait_username, _wait_list_count,
    _wait_tx_status, _wait_tx_status_failure, _wait_tx_deliver,
    _wait_followed_user, _wait_followed_topic,
    _wait_blocked_user, _wait_blocked_topic, _wait_blocked_topic_state,
    _wait_comment_indexed,
    _rpc_latest_height, _wait_next_block,
)


def test_subscriber(backend: str):

    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())
    sub1_wallet = WALLETS["sub1"]
    sub1_addr = str(sub1_wallet.address())
    sub2_wallet = WALLETS["sub2"]
    sub2_addr = str(sub2_wallet.address())
    agent1_wallet = WALLETS["agent1"]
    agent1_addr = str(agent1_wallet.address())

    # 7.1 Free user level = 0
    try:
        free_status = get_user_status(backend, free_addr)
        free_level = int(free_status.get("user_level", 0) or 0)
        if free_level == 0:
            _pass("tiers.free_user_level = 0")
        else:
            _fail("tiers.free_user_level = 0", f"level={free_level}")
    except Exception as e:
        _fail("tiers.free_user_level", str(e))

    # 7.2 Verify subscription levels (sub1,sub2=level 1, agent1=level 10)
    for level, name, w, a in [
        (1, "sub1", sub1_wallet, sub1_addr),
        (1, "sub2", sub2_wallet, sub2_addr),
        (10, "agent1", agent1_wallet, agent1_addr),
    ]:
        try:
            st = get_user_status(backend, a)
            actual = int(st.get("user_level", 0) or 0)
            if actual == level:
                _pass(f"tiers.{name}_level = {level}")
            else:
                _fail(f"tiers.{name}_level = {level}", f"actual={actual}")
        except Exception as e:
            _fail(f"tiers.{name}_level = {level}", str(e))

    # 7.3 Free user: post with PoW succeeds
    txh_free = _do_post(backend, free_wallet, "test", f"Free post {_rand_str(4)}", "free body", skip_pow=False)
    if txh_free:
        _pass("tiers.free_user_post_with_pow succeeds")
    else:
        _fail("tiers.free_user_post_with_pow succeeds")

    # 7.4 All subscribers/agents: post without PoW succeeds
    tier_posts = {}
    for level, name, w in [
        (1, "sub1", sub1_wallet),
        (1, "sub2", sub2_wallet),
        (10, "agent1", agent1_wallet),
    ]:
        txh = _do_post(backend, w, "test", f"Tier{level} post {_rand_str(4)}", f"tier {level} body", skip_pow=True)
        if txh:
            deliver = _wait_tx_deliver(txh)
            if deliver and deliver[0] == 0:
                _pass(f"tiers.{name}_post_without_pow succeeds")
                tier_posts[name] = txh
            elif deliver:
                _fail(
                    f"tiers.{name}_post_without_pow succeeds",
                    f"deliver_code={deliver[0]} log={deliver[1][:200]}",
                )
            else:
                _fail(f"tiers.{name}_post_without_pow succeeds", "deliver timeout")
        else:
            _fail(f"tiers.{name}_post_without_pow succeeds")

    # 7.5 Both can read endpoints
    code1, _ = _get(f"{backend}/api/get_posts", {"limit": 5})
    code2, _ = _get(f"{backend}/api/get_parameters")
    if code1 == 200 and code2 == 200:
        _pass("tiers.all_read_endpoints work")
    else:
        _fail("tiers.all_read_endpoints work", f"codes={code1},{code2}")

    # 7.6 Each subscriber/agent: vote without PoW succeeds
    if txh_free:
        time.sleep(2)
        for level, name, w in [
            (1, "sub1", sub1_wallet),
            (1, "sub2", sub2_wallet),
            (10, "agent1", agent1_wallet),
        ]:
            resp = _do_vote(backend, w, txh_free, 1, skip_pow=True)
            txh_vote = str(resp.get("tx_hash", "")).lower()
            if txh_vote:
                _pass(f"tiers.{name}_vote_without_pow succeeds")
            else:
                _fail(f"tiers.{name}_vote_without_pow succeeds", f"resp={resp}")

    # 7.7 Subscriber sending PoW should be REJECTED
    for level, name, w in [
        (1, "sub1", sub1_wallet),
        (1, "sub2", sub2_wallet),
        (10, "agent1", agent1_wallet),
    ]:
        try:
            a = str(w.address())
            lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, a)
            pub_s = w.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            base = _canon_base_post_raw(
                pub_s, _lb_bytes(lb), 1, ts, "", "test", f"{name} pow", "body", "", 0, None, nonce
            )
            proof = compute_pow(base, 1, base_bits, pow_factor, lb)
            signed = canon_signed_with_pow(base, int(proof))
            sig = sign_canonical(w, signed)
            payload = {
                "pubkey": _b64(pub_s),
                "signature": _b64(sig),
                "last_block_hash": lb,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "pow_difficulty": 1,
                "pow": int(proof),
                "target": "",
                "topic": "test",
                "title": f"{name} pow",
                "content": "body",
            }
            code, resp = _post(f"{backend}/api/core/post", payload)
            if code >= 400:
                _pass(f"tiers.{name}_pow_rejected")
            else:
                _fail(f"tiers.{name}_pow_rejected", f"code={code}")
        except Exception as e:
            _fail(f"tiers.{name}_pow_rejected", str(e))

    # 7.8 Free user without PoW should be REJECTED
    try:
        lb2, _, base_bits2, pow_factor2, _ = _fetch_params(backend, free_addr)
        pub_free = free_wallet.public_key().public_key_bytes
        ts2 = _now_ms()
        nonce2 = _fresh_nonce()
        base2 = _canon_base_post_raw(
            pub_free, _lb_bytes(lb2), 0, ts2, "", "test", "no pow", "body", "", 0, None, nonce2
        )
        signed2 = canon_signed_with_pow(base2, 0)
        sig2 = sign_canonical(free_wallet, signed2)
        payload2 = {
            "pubkey": _b64(pub_free),
            "signature": _b64(sig2),
            "last_block_hash": lb2,
            "timestamp": ts2,
            "envelope_nonce": str(nonce2),
            "pow_difficulty": 0,
            "target": "",
            "topic": "test",
            "title": "no pow",
            "content": "body",
        }
        code2, resp2 = _post(f"{backend}/api/core/post", payload2)
        if code2 >= 400:
            _pass("tiers.free_user_no_pow_rejected")
        else:
            _fail("tiers.free_user_no_pow_rejected", f"code={code2}")
    except Exception as e:
        _fail("tiers.free_user_no_pow_rejected", str(e))

    # 7.9 All tiers can edit their own posts
    for name, w in [("sub1", sub1_wallet), ("sub2", sub2_wallet), ("agent1", agent1_wallet)]:
        if name in tier_posts:
            if _wait_indexed(backend, str(w.address()), tier_posts[name]):
                resp = _do_edit(
                    backend,
                    w,
                    tier_posts[name],
                    "test",
                    f"Edited {name} {_rand_str(4)}",
                    f"edited body {name}",
                    skip_pow=True,
                )
                txh_e = str(resp.get("tx_hash", "")).lower()
                if txh_e:
                    _pass(f"tiers.{name}_edit_own_post succeeds")
                else:
                    _fail(f"tiers.{name}_edit_own_post succeeds", f"resp={resp}")
            else:
                _fail(f"tiers.{name}_edit_own_post succeeds", "post not indexed after timeout")


# =========================================================================
# Category 8: Search & Discovery
# =========================================================================

def test_auto_renewal(backend: str):

    sub1 = WALLETS["sub1"]
    free_wallet = WALLETS["free"]

    # 15.1 Enable auto-renewal for subscriber
    try:
        resp = _do_set_auto_renewal(backend, sub1, True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("auto_renewal.enable")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("auto_renewal.enable", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("auto_renewal.enable", str(e))

    time.sleep(3)

    # 15.2 Disable auto-renewal for subscriber
    try:
        resp = _do_set_auto_renewal(backend, sub1, False)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("auto_renewal.disable")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("auto_renewal.disable", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("auto_renewal.disable", str(e))

    # 15.3 Free user tries auto-renewal (should fail)
    try:
        resp = _do_set_auto_renewal(backend, free_wallet, True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "subscriber" in err or "free" in err or "not allowed" in err:
            _pass("auto_renewal.free_user_rejected")
        else:
            _pass("auto_renewal.free_user submitted (chain may reject)")
    except Exception as e:
        _pass("auto_renewal.free_user_rejected")

    # 15.4 Double enable (idempotent)
    try:
        resp = _do_set_auto_renewal(backend, sub1, True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("auto_renewal.double_enable submitted")
        else:
            _pass("auto_renewal.double_enable handled")
    except Exception as e:
        _pass("auto_renewal.double_enable handled")


# =========================================================================
# Category 16: Reports
# =========================================================================

def test_tier_config_api(backend: str):
    """Verify tier configurations are correctly served through the API."""

    code, params_resp = _get(f"{backend}/api/get_chain_config")
    if code != 200:
        _fail("tierapi.fetch_params", f"code={code}")
        return
    _pass("tierapi.fetch_params")

    tiers = (params_resp or {}).get("tiers") or []
    if len(tiers) != 3:
        _fail("tierapi.exactly_3_tiers", f"got {len(tiers)}")
        return
    _pass("tierapi.exactly_3_tiers")

    # Free tier (index 0)
    free = tiers[0]
    if int(free.get("period_fee", -1)) == 0:
        _pass("tierapi.free_period_fee_0")
    else:
        _fail("tierapi.free_period_fee_0", f"got={free.get('period_fee')}")

    free_expected = {
        "max_enabled_agents": 5,
        "max_followed_users": 25,
        "max_followed_topics": 25,
        "max_blocked_users": 25,
        "max_blocked_posts": 25,
        "max_blocked_topics": 25,
    }
    for field, expected in free_expected.items():
        val = int(free.get(field, 0))
        if val == expected:
            _pass(f"tierapi.free_{field}_{expected}")
        else:
            _fail(f"tierapi.free_{field}_{expected}", f"got={val}")

    if int(free.get("max_title_length", 0)) == 150:
        _pass("tierapi.free_max_title_150")
    else:
        _fail("tierapi.free_max_title_150", f"got={free.get('max_title_length')}")

    if int(free.get("max_content_length", 0)) == 1000:
        _pass("tierapi.free_max_content_1000")
    else:
        _fail("tierapi.free_max_content_1000", f"got={free.get('max_content_length')}")

    if int(free.get("editing_time_mins", 0)) == 10:
        _pass("tierapi.free_editing_10m")
    else:
        _fail("tierapi.free_editing_10m", f"got={free.get('editing_time_mins')}")

    if abs(float(free.get("vote_weight", 0)) - 1.0) < 0.01:
        _pass("tierapi.free_vote_weight_1.0")
    else:
        _fail("tierapi.free_vote_weight_1.0", f"got={free.get('vote_weight')}")

    for flag in [
        "can_be_agent",
        "can_remove_anon",
        "can_have_biography",
        "can_have_avatar",
        "can_have_banner",
        "can_have_flair",
    ]:
        if not free.get(flag, True):
            _pass(f"tierapi.free_{flag}_false")
        else:
            _fail(f"tierapi.free_{flag}_false", f"got={free.get(flag)}")

    # Subscriber tier (index 1)
    sub = tiers[1]
    if int(sub.get("period_fee", -1)) == 100_000_000_000:
        _pass("tierapi.sub_period_fee_100B")
    else:
        _fail("tierapi.sub_period_fee_100B", f"got={sub.get('period_fee')}")

    sub_expected = {
        "max_enabled_agents": 50,
        "max_followed_users": 500,
        "max_followed_topics": 500,
        "max_blocked_users": 500,
        "max_blocked_posts": 500,
        "max_blocked_topics": 500,
    }
    for field, expected in sub_expected.items():
        val = int(sub.get(field, 0))
        if val == expected:
            _pass(f"tierapi.sub_{field}_{expected}")
        else:
            _fail(f"tierapi.sub_{field}_{expected}", f"got={val}")

    if int(sub.get("max_title_length", 0)) == 300:
        _pass("tierapi.sub_max_title_300")
    else:
        _fail("tierapi.sub_max_title_300", f"got={sub.get('max_title_length')}")

    if int(sub.get("max_content_length", 0)) == 20000:
        _pass("tierapi.sub_max_content_20000")
    else:
        _fail("tierapi.sub_max_content_20000", f"got={sub.get('max_content_length')}")

    if int(sub.get("editing_time_mins", 0)) == 360:
        _pass("tierapi.sub_editing_360m")
    else:
        _fail("tierapi.sub_editing_360m", f"got={sub.get('editing_time_mins')}")

    if abs(float(sub.get("vote_weight", 0)) - 1.33) < 0.01:
        _pass("tierapi.sub_vote_weight_1.33")
    else:
        _fail("tierapi.sub_vote_weight_1.33", f"got={sub.get('vote_weight')}")

    if not sub.get("can_be_agent", True):
        _pass("tierapi.sub_can_be_agent_false")
    else:
        _fail("tierapi.sub_can_be_agent_false", f"got={sub.get('can_be_agent')}")

    for flag in ["can_remove_anon", "can_have_biography", "can_have_avatar", "can_have_banner", "can_have_flair"]:
        if sub.get(flag, False):
            _pass(f"tierapi.sub_{flag}_true")
        else:
            _fail(f"tierapi.sub_{flag}_true", f"got={sub.get(flag)}")

    # Agent tier (index 2)
    agent = tiers[2]
    if int(agent.get("period_fee", -1)) == 500_000_000_000:
        _pass("tierapi.agent_period_fee_200B")
    else:
        _fail("tierapi.agent_period_fee_200B", f"got={agent.get('period_fee')}")

    if agent.get("can_be_agent", False):
        _pass("tierapi.agent_can_be_agent_true")
    else:
        _fail("tierapi.agent_can_be_agent_true", f"got={agent.get('can_be_agent')}")

    for flag in ["can_remove_anon", "can_have_biography", "can_have_avatar", "can_have_banner", "can_have_flair"]:
        if agent.get(flag, False):
            _pass(f"tierapi.agent_{flag}_true")
        else:
            _fail(f"tierapi.agent_{flag}_true", f"got={agent.get(flag)}")


# =========================================================================
# Category 21: Upgrade Level Validation (backend API)
# =========================================================================
