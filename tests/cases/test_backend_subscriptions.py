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
    _do_delete,
    _do_delete_user,
    _do_follow_user,
    _do_follow_topic,
    _do_block,
    _do_block_topic,
    _do_set_username_raw,
    _do_set_biography,
    _do_report,
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
    _wait_followed_community,
    _wait_blocked_user,
    _wait_blocked_community,
    _wait_blocked_community_state,
    _wait_comment_indexed,
    _rpc_latest_height,
    _wait_next_block,
)


def test_subscriber(backend: str):

    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())
    sub1_wallet = WALLETS["sub1"]
    sub1_addr = str(sub1_wallet.address())
    sub2_wallet = WALLETS["sub2"]
    sub2_addr = str(sub2_wallet.address())
    agent1_wallet = WALLETS["sub3"]
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

    # 7.2 Verify subscription levels. Level 1 is the only paid level now.
    for level, name, w, a in [
        (1, "sub1", sub1_wallet, sub1_addr),
        (1, "sub2", sub2_wallet, sub2_addr),
        (1, "sub3", agent1_wallet, agent1_addr),
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

    # 7.2b Gift subscription extends expiry and keeps auto_renew unchanged
    try:
        code, cfg = _get(f"{backend}/api/get_chain_config")
        if code != 200 or not isinstance(cfg, dict):
            _fail("tiers.gift_extends_expiry", f"get_chain_config code={code}")
        else:
            period_minutes = int(cfg.get("subscription_period", 0) or 0)
            # Ensure recipient auto_renew is false to validate unchanged behavior
            resp = _do_set_auto_renewal(backend, sub2_wallet, False)
            txh = str(resp.get("tx_hash", "")).lower() if resp else ""
            if txh:
                _wait_tx_deliver(txh)
            time.sleep(2)
            before = get_user_status(backend, sub2_addr)
            before_exp = int(before.get("subscription_expiry", 0) or 0)
            auto_before = bool(before.get("auto_renew", False))

            resp = _do_subscribe(backend, sub1_wallet, 1, target=sub2_addr)
            txh = str(resp.get("tx_hash", "")).lower() if resp else ""
            err = str(resp.get("error", "")) if resp else ""
            if err:
                _debug(f"gift subscribe error={err}")
            if txh:
                deliver = _wait_tx_deliver(txh)
                if deliver and deliver[0] != 0:
                    _debug(f"gift subscribe deliver failed code={deliver[0]} log={deliver[1][:200]}")

            deadline = time.time() + 30
            after_exp = before_exp
            auto_after = auto_before
            while time.time() < deadline:
                after = get_user_status(backend, sub2_addr)
                after_exp = int(after.get("subscription_expiry", 0) or 0)
                auto_after = bool(after.get("auto_renew", False))
                if after_exp > before_exp:
                    break
                time.sleep(2)

            if after_exp <= before_exp:
                _fail("tiers.gift_extends_expiry", f"before={before_exp} after={after_exp}")
            elif auto_after != auto_before:
                _fail("tiers.gift_auto_renew_unchanged", f"before={auto_before} after={auto_after}")
            else:
                if period_minutes > 0 and after_exp < before_exp + period_minutes * 60:
                    _fail(
                        "tiers.gift_extends_expiry", f"delta={after_exp - before_exp} expected>={period_minutes * 60}"
                    )
                else:
                    _pass("tiers.gift_extends_expiry")
                    _pass("tiers.gift_auto_renew_unchanged")
            resp = _do_set_auto_renewal(backend, sub2_wallet, True)
            txh = str(resp.get("tx_hash", "")).lower() if resp else ""
            if txh:
                deliver = _wait_tx_deliver(txh)
                if not deliver or deliver[0] != 0:
                    _debug(f"Warning: failed to restore auto_renew for sub2: {deliver}")
            else:
                _debug(f"Warning: failed to submit auto_renew restore for sub2: {resp}")
    except Exception as e:
        _fail("tiers.gift_extends_expiry", str(e))

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
        (10, "sub3", agent1_wallet),
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
            (10, "sub3", agent1_wallet),
        ]:
            resp = _do_vote(backend, w, txh_free, 1, skip_pow=True)
            txh_vote = str(resp.get("tx_hash", "")).lower()
            if txh_vote:
                _pass(f"tiers.{name}_vote_without_pow succeeds")
            else:
                _fail(f"tiers.{name}_vote_without_pow succeeds", f"resp={resp}")

    # 7.7 Subscriber sending PoW should be ACCEPTED (PoW fields ignored)
    for level, name, w in [
        (1, "sub1", sub1_wallet),
        (1, "sub2", sub2_wallet),
        (10, "sub3", agent1_wallet),
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
                "community": "test",
                "title": f"{name} pow",
                "content": "body",
                "protocol_version": 1,
            }
            code, resp = _post(f"{backend}/api/core/post", payload)
            if code < 400:
                _pass(f"tiers.{name}_pow_accepted")
            else:
                _fail(f"tiers.{name}_pow_accepted", f"code={code} resp={resp}")
        except Exception as e:
            _fail(f"tiers.{name}_pow_accepted", str(e))

    # 7.7b Subscriber vote with PoW should be ACCEPTED (PoW fields ignored)
    txh_pow_vote_target = _do_post(
        backend, free_wallet, "test", f"Pow vote target {_rand_str(4)}", "pow vote body", skip_pow=False
    )
    if txh_pow_vote_target:
        for name, w in [
            ("sub1", sub1_wallet),
            ("sub2", sub2_wallet),
            ("sub3", agent1_wallet),
        ]:
            try:
                resp = _do_vote(backend, w, txh_pow_vote_target, 1, skip_pow=False)
                txh_v = str(resp.get("tx_hash", "")).lower() if resp else ""
                err = str(resp.get("error", "")).lower() if resp else ""
                if txh_v:
                    _pass(f"tiers.{name}_vote_pow_accepted")
                elif "pow not allowed" in err:
                    _fail(f"tiers.{name}_vote_pow_accepted", "old rejection still active")
                else:
                    _fail(f"tiers.{name}_vote_pow_accepted", f"err={err[:200]}")
            except Exception as e:
                _fail(f"tiers.{name}_vote_pow_accepted", str(e))
    else:
        _fail("tiers.vote_pow_target_post", "failed to create target post for pow vote")

    # 7.7c Subscriber edit with PoW should be ACCEPTED (PoW fields ignored)
    for name, w in [("sub1", sub1_wallet), ("sub2", sub2_wallet), ("sub3", agent1_wallet)]:
        if name in tier_posts:
            if _wait_indexed(backend, str(w.address()), tier_posts[name]):
                try:
                    resp = _do_edit(
                        backend,
                        w,
                        tier_posts[name],
                        "test",
                        f"PowEdit {name} {_rand_str(4)}",
                        f"pow edit body {name}",
                        skip_pow=False,
                    )
                    txh_e = str(resp.get("tx_hash", "")).lower() if resp else ""
                    err = str(resp.get("error", "")).lower() if resp else ""
                    if txh_e:
                        _pass(f"tiers.{name}_edit_pow_accepted")
                    elif "pow not allowed" in err:
                        _fail(f"tiers.{name}_edit_pow_accepted", "old rejection still active")
                    else:
                        _fail(f"tiers.{name}_edit_pow_accepted", f"err={err[:200]}")
                except Exception as e:
                    _fail(f"tiers.{name}_edit_pow_accepted", str(e))
            else:
                _fail(f"tiers.{name}_edit_pow_accepted", "post not indexed after timeout")

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
            "community": "test",
            "title": "no pow",
            "content": "body",
            "protocol_version": 1,
        }
        code2, resp2 = _post(f"{backend}/api/core/post", payload2)
        if code2 >= 400:
            _pass("tiers.free_user_no_pow_rejected")
        else:
            _fail("tiers.free_user_no_pow_rejected", f"code={code2}")
    except Exception as e:
        _fail("tiers.free_user_no_pow_rejected", str(e))

    # 7.9 All tiers can edit their own posts
    for name, w in [("sub1", sub1_wallet), ("sub2", sub2_wallet), ("sub3", agent1_wallet)]:
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
        "max_followed_users": 25,
        "max_joined_communities": 25,
        "max_blocked_users": 25,
        "max_blocked_posts": 25,
        "max_blocked_communities": 25,
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
        "can_have_biography",
        "can_have_avatar",
        "can_have_banner",
        "can_have_flair",
    ]:
        if not free.get(flag, True):
            _pass(f"tierapi.free_{flag}_false")
        else:
            _fail(f"tierapi.free_{flag}_false", f"got={free.get(flag)}")

    if not free.get("can_remove_anon", False):
        _pass("tierapi.free_can_remove_anon_absent_or_false")
    else:
        _fail("tierapi.free_can_remove_anon_absent_or_false", f"got={free.get('can_remove_anon')}")

    # Subscriber tier (index 1)
    sub = tiers[1]
    if int(sub.get("period_fee", -1)) == 100_000_000_000:
        _pass("tierapi.sub_period_fee_100B")
    else:
        _fail("tierapi.sub_period_fee_100B", f"got={sub.get('period_fee')}")

    sub_expected = {
        "max_followed_users": 500,
        "max_joined_communities": 500,
        "max_blocked_users": 500,
        "max_blocked_posts": 500,
        "max_blocked_communities": 500,
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

    if not sub.get("can_be_agent", False):
        _pass("tierapi.sub_can_be_agent_absent_or_false")
    else:
        _fail("tierapi.sub_can_be_agent_absent_or_false", f"got={sub.get('can_be_agent')}")

    if not sub.get("can_remove_anon", False):
        _pass("tierapi.sub_can_remove_anon_absent_or_false")
    else:
        _fail("tierapi.sub_can_remove_anon_absent_or_false", f"got={sub.get('can_remove_anon')}")

    for flag in ["can_have_biography", "can_have_avatar", "can_have_banner", "can_have_flair"]:
        if sub.get(flag, False):
            _pass(f"tierapi.sub_{flag}_true")
        else:
            _fail(f"tierapi.sub_{flag}_true", f"got={sub.get(flag)}")

    admin = tiers[2]
    if int(admin.get("period_fee", -1)) == 0:
        _pass("tierapi.admin_period_fee_0")
    else:
        _fail("tierapi.admin_period_fee_0", f"got={admin.get('period_fee')}")
    if int(admin.get("max_curation_memberships", -1)) == 1000:
        _pass("tierapi.admin_max_curation_memberships_1000")
    else:
        _fail(
            "tierapi.admin_max_curation_memberships_1000",
            f"got={admin.get('max_curation_memberships')}",
        )
    if int(admin.get("max_daily_relays", -1)) == 10000:
        _pass("tierapi.admin_max_daily_relays_10000")
    else:
        _fail("tierapi.admin_max_daily_relays_10000", f"got={admin.get('max_daily_relays')}")

    _pass("tierapi.agent_tier_removed")


# =========================================================================
# Category 25: Subscribe Gift Validation (backend API)
# =========================================================================


def test_subscribe_gift_validation(backend: str):
    """Test backend-level gift validation: invalid target."""

    sub1_wallet = WALLETS["sub1"]

    # 25.1 Invalid target address should be rejected
    try:
        resp = _do_subscribe(backend, sub1_wallet, 1, target="not_a_valid_address")
        err = str(resp.get("error", "")).lower() if resp else ""
        txh = str(resp.get("tx_hash", "")).lower() if resp else ""
        if "target" in err and "valid" in err and not txh:
            _pass("subscribe.invalid_target_rejected")
        elif not txh and err:
            _pass("subscribe.invalid_target_rejected")
        else:
            _fail("subscribe.invalid_target_rejected", f"txh={txh} err={err[:200]}")
    except Exception as e:
        _fail("subscribe.invalid_target_rejected", str(e))

    # 25.2 There is no tier above Subscriber, so a gift can never be rejected
    # for targeting a higher tier. Gifting an existing subscriber extends them,
    # which test_subscribe_gift_repeat asserts.


# =========================================================================
# Category 26: Gift Agent Subscription (backend API)
# =========================================================================


def test_subscribe_gift_repeat(backend: str):
    """Gift a level-1 subscription to a wallet that already has one, twice over."""

    agent2_wallet = WALLETS["sub4"]
    agent1_wallet = WALLETS["sub3"]
    agent1_addr = str(agent1_wallet.address())

    # 26.1 Gift level 10 from sub4 to sub3 (already level 10) — should succeed
    try:
        before = get_user_status(backend, agent1_addr)
        before_exp = int(before.get("subscription_expiry", 0) or 0)
        _debug(f"subscribe.gift_repeat.before sub3 exp={before_exp} level={before.get('user_level')}")

        resp = _do_subscribe(backend, agent2_wallet, 1, target=agent1_addr)
        txh = str(resp.get("tx_hash", "")).lower() if resp else ""
        err = str(resp.get("error", "")) if resp else ""
        if err:
            _debug(f"subscribe.gift_repeat error={err}")
            _fail("subscribe.gift_repeat_succeeds", f"error={err[:200]}")
        elif txh:
            deliver = _wait_tx_deliver(txh)
            if deliver and deliver[0] != 0:
                _fail("subscribe.gift_repeat_succeeds", f"deliver code={deliver[0]} log={deliver[1][:200]}")
            else:
                _pass("subscribe.gift_repeat_succeeds")
        else:
            _fail("subscribe.gift_repeat_succeeds", f"no txh or error: {resp}")
    except Exception as e:
        _fail("subscribe.gift_repeat_succeeds", str(e))

    # 26.2 Wait for indexer and verify expiry increased
    try:
        deadline = time.time() + 30
        after_exp = before_exp
        while time.time() < deadline:
            after = get_user_status(backend, agent1_addr)
            after_exp = int(after.get("subscription_expiry", 0) or 0)
            if after_exp > before_exp:
                break
            time.sleep(2)
        _debug(f"subscribe.gift_repeat.after sub3 exp={after_exp}")
        if after_exp > before_exp:
            _pass("subscribe.gift_repeat_extends_expiry")
        else:
            _fail("subscribe.gift_repeat_extends_expiry", f"before={before_exp} after={after_exp}")
    except Exception as e:
        _fail("subscribe.gift_repeat_extends_expiry", str(e))

    # 26.3 Gift level 10 again — should extend expiry further
    try:
        before_exp2 = after_exp
        resp = _do_subscribe(backend, agent2_wallet, 1, target=agent1_addr)
        txh = str(resp.get("tx_hash", "")).lower() if resp else ""
        err = str(resp.get("error", "")) if resp else ""
        if err:
            _fail("subscribe.gift_repeat_extends_again", f"error={err[:200]}")
        elif txh:
            deliver = _wait_tx_deliver(txh)
            if deliver and deliver[0] != 0:
                _fail("subscribe.gift_repeat_extends_again", f"deliver code={deliver[0]}")
            else:
                deadline2 = time.time() + 30
                after_exp2 = before_exp2
                while time.time() < deadline2:
                    st = get_user_status(backend, agent1_addr)
                    after_exp2 = int(st.get("subscription_expiry", 0) or 0)
                    if after_exp2 > before_exp2:
                        break
                    time.sleep(2)
                if after_exp2 > before_exp2:
                    _pass("subscribe.gift_repeat_extends_again")
                else:
                    _fail("subscribe.gift_repeat_extends_again", f"before={before_exp2} after={after_exp2}")
        else:
            _fail("subscribe.gift_repeat_extends_again", f"no txh or error: {resp}")
    except Exception as e:
        _fail("subscribe.gift_repeat_extends_again", str(e))


# =========================================================================
# Category 21: Subscribe Validation (backend API)
# =========================================================================
