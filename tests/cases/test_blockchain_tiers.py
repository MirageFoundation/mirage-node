from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import random
import string
import time
from typing import Optional

import requests

from tests.common import (
    _pass, _fail, _skip, _debug, _get, _post, _b64, _rand_str, _now_ms,
    _fresh_nonce, _lb_bytes,
    WALLETS, INDEX_TIMEOUT_SEC,
    _COLOR_GREEN, _COLOR_RED, _COLOR_YELLOW, _COLOR_RESET, _COLOR_BOLD,
    _docker_exec, _run_miraged, _INSIDE_CONTAINER,
    DEFAULT_BACKEND,
    get_status, sign_canonical, compute_pow, check_pow_target,
    canon_signed_with_pow,
    _canon_base_post_raw, _canon_base_vote_raw, _canon_base_edit_raw,
    _canon_base_delete_raw, _canon_base_delete_user_raw,
    _canon_base_set_username_raw, _canon_base_set_biography_raw,
    _canon_base_follow_user_raw, _canon_base_unfollow_user_raw,
    _canon_base_follow_topic_raw, _canon_base_unfollow_topic_raw,
    _canon_base_enable_agent_raw, _canon_base_disable_agent_raw,
    _canon_base_set_agents_raw,
    _canon_base_block_post_raw, _canon_base_unblock_post_raw,
    _canon_base_block_user_raw, _canon_base_unblock_user_raw,
    _canon_base_block_topic_raw, _canon_base_unblock_topic_raw,
    _canon_base_send_tokens_raw, _canon_base_subscribe_raw,
    _canon_base_set_auto_renewal_raw, _canon_base_award_raw,
    _canon_base_annotate_raw,
    _request_with_retries,
)
from tests.blockchain_helpers import (
    _gen_nonce, _compute_pow_quiet, _pow_digest, _rand_hex,
    _get_pow_params, _get_chain_params, _get_tier_config, _tier_int,
    _get_chain_profile, _get_profile_full, _assert_capped_deque,
    _build_tx_bytes, _simulate_tx_gas, _simulate_tx_bytes_gas,
    _broadcast_tx_sync, _wait_for_tx_result, _submit_tx, _sign_relay,
    _build_msg_post, _build_msg_vote, _build_msg_set_username,
    _build_msg_set_biography, _build_msg_send_tokens,
    _build_msg_delete, _build_msg_delete_user, _build_msg_award,
    _build_msg_edit, _build_msg_annotate,
    _build_msg_block_post, _build_msg_block_user, _build_msg_block_topic,
    _build_msg_subscribe,
    _build_msg_follow_user, _build_msg_unfollow_user,
    _build_msg_follow_topic, _build_msg_unfollow_topic,
    _build_msg_enable_agent, _build_msg_disable_agent, _build_msg_set_agents,
    _build_msg_unblock_post, _build_msg_unblock_user, _build_msg_unblock_topic,
    _build_msg_set_auto_renewal,
    _check_reject, _check_accept, _check_deliver_reject, _check_deliver_accept,
    _min_gas_price_umirage, _get_grpc_target,
    DEFAULT_GAS_LIMIT, SUBSCRIBE_GAS_LIMIT, FILL_GAS_LIMIT, FILL_GAS_BUFFER,
    COMET_RPC_URL, ESTIMATED_CHECKTX_TOTAL,
    _validate_validator_funds, _required_validator_fee_budget_umirage,
    _query_spendable_umirage,
)
import tests.blockchain_helpers as _bh
from shared.datatypes import (
    MsgAward, MsgBlockPost, MsgBlockTopic, MsgBlockUser,
    MsgBurnTokens, MsgDelete, MsgDeleteUser, MsgEdit,
    MsgEnableAgent, MsgFollowTopic, MsgFollowUser,
    MsgMintTokens, MsgPost, MsgSendTokens, MsgSetAutoRenewal,
    MsgSetLevel, MsgSetUsername, MsgSetBiography,
    MsgUnblockPost, MsgUnblockTopic, MsgUnblockUser,
    MsgDisableAgent, MsgSetAgents, MsgUnfollowTopic, MsgUnfollowUser,
    MsgSubscribe, MsgVote, MsgAnnotate,
)


def test_tier_enforcement(backend: str) -> None:
    """Test content/title limits per tier at chain level."""

    fee_payer = _bh._VALIDATOR_ADDR or ""

    for level, wallet_name in [(0, "free"), (1, "sub1"), (1, "sub2")]:
        w = WALLETS[wallet_name]
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, str(w.address()))
        ts = _now_ms()
        tier = _get_tier_config(level)
        max_content = _tier_int(tier, "max_content_length")
        max_title = _tier_int(tier, "max_title_length")

        # Compute PoW for free user
        if level == 0:
            topic = f"tier{_rand_str(4)}"
            over_content = "x" * (max_content + 25)
            pub = w.public_key().public_key_bytes
            nonce = _gen_nonce()
            base = _canon_base_post_raw(
                pub, _lb_bytes(lb), diff, ts, "", topic, "Title", over_content, "", 0, [], nonce=nonce
            )
            proof = compute_pow(base, diff, base_bits, pow_factor, lb)
            msg = _build_msg_post(w, lb, diff, ts, topic, "Title", over_content, pow_val=int(proof), nonce=nonce)
        else:
            topic = f"tier{_rand_str(4)}"
            over_content = "x" * (max_content + 25)
            msg = _build_msg_post(w, lb, 0, ts, topic, "Title", over_content, pow_val=0, nonce=_gen_nonce())

        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_reject(f"tier.t{level}_content_over_max", ccode, dcode, dlog)

        # Oversized title
        if level == 0:
            topic2 = f"tier{_rand_str(4)}"
            over_title = "T" * (max_title + 25)
            nonce2 = _gen_nonce()
            base2 = _canon_base_post_raw(
                pub, _lb_bytes(lb), diff, ts, "", topic2, over_title, "body", "", 0, [], nonce=nonce2
            )
            proof2 = compute_pow(base2, diff, base_bits, pow_factor, lb)
            msg2 = _build_msg_post(w, lb, diff, ts, topic2, over_title, "body", pow_val=int(proof2), nonce=nonce2)
        else:
            topic2 = f"tier{_rand_str(4)}"
            over_title = "T" * (max_title + 25)
            msg2 = _build_msg_post(w, lb, 0, ts, topic2, over_title, "body", pow_val=0, nonce=_gen_nonce())

        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg2, "/mirage.core.v1.MsgPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_reject(f"tier.t{level}_title_over_max", ccode, dcode, dlog)



def test_subscribe_validation(backend: str) -> None:
    """Test that level 1 is the only subscribable level."""

    fee_payer = _bh._VALIDATOR_ADDR or ""
    fw = WALLETS["free"]
    fw_addr = str(fw.address())
    fw_pub = fw.public_key().public_key_bytes

    # 14.1 Invalid levels should be rejected. 10 is included now that the Agent
    # tier is gone.
    for invalid_level in [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 50, 99, 100]:
        lb, _, _, _ = _get_pow_params(backend, fw_addr)
        ts = _now_ms()
        msg = _build_msg_subscribe(fw, lb, 0, ts, invalid_level, pow_val=0, nonce=_gen_nonce())
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgSubscribe")],
            SUBSCRIBE_GAS_LIMIT,
            fee_payer,
            fw_pub,
            wait_deliver=True,
        )
        _check_deliver_reject(f"subscribe.invalid_level_{invalid_level}", ccode, dcode, dlog)



def test_subscribe_gift_extends_expiry(backend: str) -> None:
    """Gift should extend expiry and keep auto_renew unchanged."""
    fee_payer = _bh._VALIDATOR_ADDR or ""
    giver = WALLETS["sub1"]
    recipient = WALLETS["sub2"]
    recipient_addr = str(recipient.address())
    auto_original = False

    try:
        params = _get_chain_params()
        period_minutes = int(params.get("subscription_period", 0) or 0)
        if period_minutes <= 0:
            _fail("subscribe.gift_extends_expiry", f"subscription_period={period_minutes}")
            return
    except Exception as e:
        _fail("subscribe.gift_extends_expiry", str(e))
        return

    try:
        profile = _get_chain_profile(recipient_addr)
        level = int(profile.get("level", 0) or 0)
        if level < 1:
            lb, _, _, _ = _get_pow_params(backend, recipient_addr)
            ts = _now_ms()
            msg = _build_msg_subscribe(recipient, lb, 0, ts, 1, pow_val=0, nonce=_gen_nonce())
            _, ccode, _, dcode, dlog = _submit_tx(
                [(msg, "/mirage.core.v1.MsgSubscribe")],
                SUBSCRIBE_GAS_LIMIT,
                fee_payer,
                recipient.public_key().public_key_bytes,
                wait_deliver=True,
            )
            _check_deliver_accept("subscribe.gift_extends_expiry.setup_subscribe", ccode, dcode, dlog)
            time.sleep(2)
            profile = _get_chain_profile(recipient_addr)
            level = int(profile.get("level", 0) or 0)
        if level < 1:
            _fail("subscribe.gift_extends_expiry.setup_subscribe", f"level={level}")
            return
    except Exception as e:
        _fail("subscribe.gift_extends_expiry.setup_subscribe", str(e))
        return

    try:
        original = _get_chain_profile(recipient_addr)
        auto_original = bool(original.get("auto_renew", False))
        if auto_original:
            lb, _, _, _ = _get_pow_params(backend, recipient_addr)
            ts = _now_ms()
            msg = _build_msg_set_auto_renewal(recipient, lb, ts, False, nonce=_gen_nonce())
            _, ccode, _, dcode, dlog = _submit_tx(
                [(msg, "/mirage.core.v1.MsgSetAutoRenewal")],
                DEFAULT_GAS_LIMIT,
                fee_payer,
                recipient.public_key().public_key_bytes,
                wait_deliver=True,
            )
            _check_deliver_accept("subscribe.gift_auto_renew_disable", ccode, dcode, dlog)
            time.sleep(2)
    except Exception as e:
        _fail("subscribe.gift_auto_renew_disable", str(e))
        return

    try:
        before = _get_chain_profile(recipient_addr)
        before_exp = int(before.get("subscription_expiry", 0) or 0)
        auto_before = bool(before.get("auto_renew", False))
        _debug(
            f"subscribe.gift_extends_expiry.before addr={recipient_addr} exp={before_exp} "
            f"auto={auto_before} period_min={period_minutes}"
        )
        if before_exp <= 0:
            _fail("subscribe.gift_extends_expiry", f"before_exp={before_exp}")
            return
    except Exception as e:
        _fail("subscribe.gift_extends_expiry", str(e))
        return

    try:
        lb, _, _, _ = _get_pow_params(backend, str(giver.address()))
        ts = _now_ms()
        msg = _build_msg_subscribe(giver, lb, 0, ts, 1, target=recipient_addr, pow_val=0, nonce=_gen_nonce())
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgSubscribe")],
            SUBSCRIBE_GAS_LIMIT,
            fee_payer,
            giver.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept("subscribe.gift_extends_expiry", ccode, dcode, dlog)
    except Exception as e:
        _fail("subscribe.gift_extends_expiry", str(e))
        return

    deadline = time.time() + 30
    after_exp = before_exp
    auto_after = auto_before
    while time.time() < deadline:
        after = _get_chain_profile(recipient_addr)
        after_exp = int(after.get("subscription_expiry", 0) or 0)
        auto_after = bool(after.get("auto_renew", False))
        if after_exp > before_exp:
            break
        time.sleep(2)

    _debug(
        f"subscribe.gift_extends_expiry.after addr={recipient_addr} exp={after_exp} auto={auto_after}"
    )

    if after_exp <= before_exp:
        _fail("subscribe.gift_extends_expiry", f"before={before_exp} after={after_exp}")
    elif auto_after != auto_before:
        _fail("subscribe.gift_auto_renew_unchanged", f"before={auto_before} after={auto_after}")
    elif after_exp < before_exp + period_minutes * 60:
        _fail("subscribe.gift_extends_expiry", f"delta={after_exp - before_exp} expected>={period_minutes * 60}")
    else:
        _pass("subscribe.gift_extends_expiry")
        _pass("subscribe.gift_auto_renew_unchanged")

    if not auto_original:
        return

    try:
        lb, _, _, _ = _get_pow_params(backend, recipient_addr)
        ts = _now_ms()
        msg = _build_msg_set_auto_renewal(recipient, lb, ts, True, nonce=_gen_nonce())
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgSetAutoRenewal")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            recipient.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept("subscribe.gift_auto_renew_restore", ccode, dcode, dlog)
    except Exception as e:
        _fail("subscribe.gift_auto_renew_restore", str(e))


def test_tier_features(backend: str) -> None:
    """Test tier-specific features: can_remove_anon, content limits."""

    fee_payer = _bh._VALIDATOR_ADDR or ""

    # 15.1 Verify all tier configs are accessible and have correct values
    for level in [0, 1]:
        tier = _get_tier_config(level)
        max_fu = _tier_int(tier, "max_followed_users")
        max_jc = _tier_int(tier, "max_joined_communities")
        max_bu = _tier_int(tier, "max_blocked_users")
        max_bp = _tier_int(tier, "max_blocked_posts")
        max_bc = _tier_int(tier, "max_blocked_communities")
        max_title = _tier_int(tier, "max_title_length")
        max_content = _tier_int(tier, "max_content_length")
        editing = _tier_int(tier, "editing_time_mins")

        if level == 0:
            if max_fu == 25 and max_jc == 25:
                _pass(f"tierfeature.level{level}_list_limits_25_25")
            else:
                _fail(
                    f"tierfeature.level{level}_list_limits_25_25",
                    f"fu={max_fu} jc={max_jc}",
                )
            if max_bu == 25 and max_bp == 25 and max_bc == 25:
                _pass(f"tierfeature.level{level}_blocked_limits_25")
            else:
                _fail(f"tierfeature.level{level}_blocked_limits_25", f"bu={max_bu} bp={max_bp} bc={max_bc}")
            if max_title == 150:
                _pass(f"tierfeature.level{level}_max_title_150")
            else:
                _fail(f"tierfeature.level{level}_max_title_150", f"got={max_title}")
            if max_content == 1000:
                _pass(f"tierfeature.level{level}_max_content_1000")
            else:
                _fail(f"tierfeature.level{level}_max_content_1000", f"got={max_content}")
            if editing == 10:
                _pass(f"tierfeature.level{level}_editing_10m")
            else:
                _fail(f"tierfeature.level{level}_editing_10m", f"got={editing}")
        else:
            if max_fu == 500 and max_jc == 500:
                _pass(f"tierfeature.level{level}_list_limits_500_500")
            else:
                _fail(
                    f"tierfeature.level{level}_list_limits_500_500",
                    f"fu={max_fu} jc={max_jc}",
                )
            if max_bu == 500 and max_bp == 500 and max_bc == 500:
                _pass(f"tierfeature.level{level}_blocked_limits_500")
            else:
                _fail(f"tierfeature.level{level}_blocked_limits_500", f"bu={max_bu} bp={max_bp} bc={max_bc}")
            if max_title == 300:
                _pass(f"tierfeature.level{level}_max_title_300")
            else:
                _fail(f"tierfeature.level{level}_max_title_300", f"got={max_title}")
            if max_content == 20000:
                _pass(f"tierfeature.level{level}_max_content_20000")
            else:
                _fail(f"tierfeature.level{level}_max_content_20000", f"got={max_content}")
            if editing == 360:
                _pass(f"tierfeature.level{level}_editing_360m")
            else:
                _fail(f"tierfeature.level{level}_editing_360m", f"got={editing}")

    # 15.2 Verify boolean flags
    tier0 = _get_tier_config(0)
    tier1 = _get_tier_config(1)

    can_be_agent_0 = bool(tier0.get("can_be_agent", False))
    can_be_agent_1 = bool(tier1.get("can_be_agent", False))
    if not can_be_agent_0 and not can_be_agent_1:
        _pass("tierfeature.can_be_agent_removed")
    else:
        _fail("tierfeature.can_be_agent_removed", f"t0={can_be_agent_0} t1={can_be_agent_1}")

    can_remove_anon_0 = tier0.get("can_remove_anon", False)
    can_remove_anon_1 = tier1.get("can_remove_anon", False)
    if not can_remove_anon_0 and can_remove_anon_1:
        _pass("tierfeature.can_remove_anon")
    else:
        _fail("tierfeature.can_remove_anon", f"t0={can_remove_anon_0} t1={can_remove_anon_1}")

    for flag in ["can_have_biography", "can_have_avatar", "can_have_banner", "can_have_flair"]:
        v0 = tier0.get(flag, False)
        v1 = tier1.get(flag, False)
        if not v0 and v1:
            _pass(f"tierfeature.{flag}")
        else:
            _fail(f"tierfeature.{flag}", f"t0={v0} t1={v1}")

    # 15.3 vote_weight
    vw0 = float(tier0.get("vote_weight", 0))
    vw1 = float(tier1.get("vote_weight", 0))
    if abs(vw0 - 1.0) < 0.01 and abs(vw1 - 1.33) < 0.01:
        _pass("tierfeature.vote_weights")
    else:
        _fail("tierfeature.vote_weights", f"vw0={vw0} vw1={vw1}")

    # 15.4 period_fee
    pf0 = int(tier0.get("period_fee", -1))
    pf1 = int(tier1.get("period_fee", -1))
    if pf0 == 0 and pf1 == 100_000_000_000:
        _pass("tierfeature.period_fees")
    else:
        _fail("tierfeature.period_fees", f"pf0={pf0} pf1={pf1}")

    # 15.5 Three tiers: free, subscriber, admin. The Agent tier is gone.
    params = _get_chain_params()
    num_tiers = len(params.get("tiers") or [])
    if num_tiers == 3:
        _pass("tierfeature.exactly_3_tiers")
    else:
        _fail("tierfeature.exactly_3_tiers", f"got {num_tiers}")
    admin = _get_tier_config(100)
    if int(admin.get("period_fee", -1)) == 0 and int(admin.get("max_curation_memberships", -1)) == 1000:
        _pass("tierfeature.admin_appointed_not_purchased")
    else:
        _fail(
            "tierfeature.admin_appointed_not_purchased",
            f"fee={admin.get('period_fee')} curation={admin.get('max_curation_memberships')}",
        )

    # 15.6 Free user content limit is enforced at chain
    fw = WALLETS["free"]
    lb, diff, base_bits, pow_factor = _get_pow_params(backend, str(fw.address()))
    ts = _now_ms()
    topic = f"tf{_rand_str(4)}"
    over_content = "x" * 1050
    pub = fw.public_key().public_key_bytes
    nonce = _gen_nonce()
    base = _canon_base_post_raw(pub, _lb_bytes(lb), diff, ts, "", topic, "Title", over_content, "", 0, [], nonce=nonce)
    proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    msg = _build_msg_post(fw, lb, diff, ts, topic, "Title", over_content, pow_val=int(proof), nonce=nonce)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    _check_deliver_reject("tierfeature.free_content_over_1000_rejected", ccode, dcode, dlog)

    # 15.7 Subscriber can post content > 1000
    sw = WALLETS["sub1"]
    lb, _, _, _ = _get_pow_params(backend, str(sw.address()))
    ts = _now_ms()
    topic2 = f"tf{_rand_str(4)}"
    long_content = "x" * 1050
    msg = _build_msg_post(sw, lb, 0, ts, topic2, "Title", long_content, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        sw.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("tierfeature.sub_content_1050_accepted", ccode, dcode, dlog)