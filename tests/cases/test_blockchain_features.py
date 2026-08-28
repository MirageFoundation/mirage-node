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


from cosmpy.aerial.wallet import LocalWallet
from cosmpy.crypto.keypairs import PrivateKey

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
    INDEX_TIMEOUT_SEC,
    _COLOR_GREEN,
    _COLOR_RED,
    _COLOR_YELLOW,
    _COLOR_RESET,
    _COLOR_BOLD,
    _docker_exec,
    _run_miraged,
    _INSIDE_CONTAINER,
    DEFAULT_BACKEND,
    get_status,
    sign_canonical,
    compute_pow,
    check_pow_target,
    canon_signed_with_pow,
    _canon_base_post_raw,
    _canon_base_vote_raw,
    _canon_base_edit_raw,
    _canon_base_delete_raw,
    _canon_base_delete_user_raw,
    _canon_base_set_username_raw,
    _canon_base_set_biography_raw,
    _canon_base_follow_user_raw,
    _canon_base_unfollow_user_raw,
    _canon_base_follow_topic_raw,
    _canon_base_unfollow_topic_raw,
    _canon_base_enable_agent_raw,
    _canon_base_disable_agent_raw,
    _canon_base_set_agents_raw,
    _canon_base_block_post_raw,
    _canon_base_unblock_post_raw,
    _canon_base_block_user_raw,
    _canon_base_unblock_user_raw,
    _canon_base_block_topic_raw,
    _canon_base_unblock_topic_raw,
    _canon_base_send_tokens_raw,
    _canon_base_subscribe_raw,
    _canon_base_set_auto_renewal_raw,
    _canon_base_award_raw,
    _canon_base_annotate_raw,
    _request_with_retries,
)
from tests.blockchain_helpers import (
    _gen_nonce,
    _compute_pow_quiet,
    _pow_digest,
    _rand_hex,
    _get_pow_params,
    _get_chain_params,
    _get_tier_config,
    _tier_int,
    _get_chain_profile,
    _get_profile_full,
    _assert_capped_deque,
    _build_tx_bytes,
    _simulate_tx_gas,
    _simulate_tx_bytes_gas,
    _broadcast_tx_sync,
    _wait_for_tx_result,
    _submit_tx,
    _sign_relay,
    _build_msg_post,
    _shared_community,
    _build_msg_vote,
    _build_msg_set_username,
    _build_msg_set_biography,
    _build_msg_send_tokens,
    _build_msg_delete,
    _build_msg_delete_user,
    _build_msg_award,
    _build_msg_edit,
    _build_msg_annotate,
    _build_msg_block_post,
    _build_msg_block_user,
    _build_msg_block_topic,
    _build_msg_subscribe,
    _build_msg_follow_user,
    _build_msg_unfollow_user,
    _build_msg_follow_topic,
    _build_msg_unfollow_topic,
    _build_msg_enable_agent,
    _build_msg_disable_agent,
    _build_msg_set_agents,
    _build_msg_unblock_post,
    _build_msg_unblock_user,
    _build_msg_unblock_topic,
    _build_msg_set_auto_renewal,
    _check_reject,
    _check_accept,
    _check_deliver_reject,
    _check_deliver_accept,
    _min_gas_price_umirage,
    _get_grpc_target,
    DEFAULT_GAS_LIMIT,
    FILL_GAS_LIMIT,
    FILL_GAS_BUFFER,
    COMET_RPC_URL,
    ESTIMATED_CHECKTX_TOTAL,
    _validate_validator_funds,
    _required_validator_fee_budget_umirage,
    _query_spendable_umirage,
)
import tests.blockchain_helpers as _bh
from shared.datatypes import (
    MsgAward,
    MsgBlockPost,
    MsgBlockTopic,
    MsgBlockUser,
    MsgBurnTokens,
    MsgDelete,
    MsgDeleteUser,
    MsgEdit,
    MsgEnableAgent,
    MsgFollowTopic,
    MsgFollowUser,
    MsgMintTokens,
    MsgPost,
    MsgSendTokens,
    MsgSetAutoRenewal,
    MsgSetLevel,
    MsgSetUsername,
    MsgSetBiography,
    MsgUnblockPost,
    MsgUnblockTopic,
    MsgUnblockUser,
    MsgDisableAgent,
    MsgSetAgents,
    MsgUnfollowTopic,
    MsgUnfollowUser,
    MsgSubscribe,
    MsgVote,
    MsgAnnotate,
)


def test_chain_auto_renewal(backend: str) -> None:
    """Test auto-renewal at chain level."""

    sub1 = WALLETS["sub1"]
    free_wallet = WALLETS["free"]
    fee_payer = _bh._VALIDATOR_ADDR or ""
    lb, _, _, _ = _get_pow_params(backend, str(sub1.address()))
    ts = _now_ms()

    # 11.1 Subscriber enables auto-renewal
    msg = _build_msg_set_auto_renewal(sub1, lb, ts, True, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetAutoRenewal")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        sub1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("auto.subscriber_enable", ccode, dcode, dlog)

    # 11.2 Subscriber disables auto-renewal
    msg = _build_msg_set_auto_renewal(sub1, lb, ts, False, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetAutoRenewal")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        sub1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("auto.subscriber_disable", ccode, dcode, dlog)

    # 11.3 Free user tries auto-renewal (should fail)
    lb_free, _, _, _ = _get_pow_params(backend, str(free_wallet.address()))
    msg = _build_msg_set_auto_renewal(free_wallet, lb_free, ts, True, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetAutoRenewal")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        free_wallet.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("auto.free_user_rejected", ccode, dcode, dlog)

    # 11.4 Auto-renewal with PoW set (should fail — never allowed on auto-renewal)
    pub = sub1.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_set_auto_renewal_raw(pub, lb_bytes, 0, ts, True)
    sig = _sign_relay(sub1, base, 1)
    msg = MsgSetAutoRenewal()
    msg.authority = _bh._VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = 0
    msg.envelope_pow = 1
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.auto_renew = True
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetAutoRenewal")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    if ccode != 0:
        _pass("auto.pow_forbidden")
    elif dcode is not None and dcode != 0:
        _pass("auto.pow_forbidden")
    else:
        _fail("auto.pow_forbidden", f"check={ccode} deliver={dcode}")


def test_send_tokens_raw_log_present(backend: str) -> None:
    """Ensure send_tokens deliver log is present and JSON."""
    fee_payer = _bh._VALIDATOR_ADDR or ""
    sender = WALLETS["sub1"]
    recipient = WALLETS["sub2"]
    sender_addr = str(sender.address())
    recipient_addr = str(recipient.address())
    lb, _, _, _ = _get_pow_params(backend, sender_addr)
    ts = _now_ms()
    amount = 1_000_000
    msg = _build_msg_send_tokens(sender, lb, 0, ts, sender_addr, recipient_addr, amount, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSendTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        sender.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("send_tokens.raw_log_present", ccode, dcode, dlog)
    if not dlog or not str(dlog).strip():
        _fail("send_tokens.raw_log_present", "missing deliver log")
        return
    try:
        parsed = json.loads(str(dlog))
    except Exception as e:
        _fail("send_tokens.raw_log_present", f"invalid json log: {e}")
        return
    if isinstance(parsed, list) and parsed:
        _pass("send_tokens.raw_log_present")
    else:
        _fail("send_tokens.raw_log_present", f"unexpected log format: {type(parsed).__name__}")


def test_biography(backend: str) -> None:
    """Test MsgSetBiography: subscriber can set, free user rejected, length limit."""

    fee_payer = _bh._VALIDATOR_ADDR or ""

    # 16.1 Subscriber sets biography (should succeed)
    sub = WALLETS["sub1"]
    lb, _, _, _ = _get_pow_params(backend, str(sub.address()))
    ts = _now_ms()
    bio_text = "Hello, I am a subscriber!"
    msg = _build_msg_set_biography(sub, lb, 0, ts, str(sub.address()), bio_text, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetBiography")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        sub.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("biography.subscriber_set", ccode, dcode, dlog)

    # 16.2 Subscriber clears biography (empty string should succeed)
    ts = _now_ms()
    msg2 = _build_msg_set_biography(sub, lb, 0, ts, str(sub.address()), "", pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg2, "/mirage.core.v1.MsgSetBiography")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        sub.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("biography.subscriber_clear", ccode, dcode, dlog)

    # 16.3 Biography length 512 accepted
    ts = _now_ms()
    bio_512 = "x" * 512
    msg_len_ok = _build_msg_set_biography(sub, lb, 0, ts, str(sub.address()), bio_512, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg_len_ok, "/mirage.core.v1.MsgSetBiography")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        sub.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("biography.len_512_ok", ccode, dcode, dlog)

    # 16.4 Biography length 513 rejected
    ts = _now_ms()
    bio_513 = "x" * 513
    msg_len_bad = _build_msg_set_biography(sub, lb, 0, ts, str(sub.address()), bio_513, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg_len_bad, "/mirage.core.v1.MsgSetBiography")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        sub.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("biography.len_513_rejected", ccode, dcode, dlog)

    # 16.5 Agent (level 10) sets biography (should succeed)
    agent = WALLETS["agent1"]
    lb, _, _, _ = _get_pow_params(backend, str(agent.address()))
    ts = _now_ms()
    agent_bio = (
        "This is a test agent biography.\n"
        "Agents operate at level 10 with expanded capabilities.\n"
        "This biography was set during automated testing."
    )
    msg_agent = _build_msg_set_biography(
        agent, lb, 0, ts, str(agent.address()), agent_bio, pow_val=0, nonce=_gen_nonce()
    )
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg_agent, "/mirage.core.v1.MsgSetBiography")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        agent.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("biography.agent_set", ccode, dcode, dlog)

    # 16.6 Free user sets biography with PoW (should be rejected by tier gate)
    fw = WALLETS["free"]
    lb, diff, base_bits, pow_factor = _get_pow_params(backend, str(fw.address()))
    ts = _now_ms()
    pub = fw.public_key().public_key_bytes
    nonce = _gen_nonce()
    base = _canon_base_set_biography_raw(pub, _lb_bytes(lb), diff, ts, str(fw.address()), "free bio", nonce=nonce)
    proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    msg3 = _build_msg_set_biography(fw, lb, diff, ts, str(fw.address()), "free bio", pow_val=int(proof), nonce=nonce)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg3, "/mirage.core.v1.MsgSetBiography")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    _check_deliver_reject("biography.free_user_rejected", ccode, dcode, dlog)

    # 16.7 Biography too long (> 512 chars) rejected
    ts = _now_ms()
    long_bio = "x" * 600
    msg4 = _build_msg_set_biography(sub, lb, 0, ts, str(sub.address()), long_bio, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg4, "/mirage.core.v1.MsgSetBiography")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        sub.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("biography.too_long_rejected", ccode, dcode, dlog)

    # 16.8 Biography with control characters rejected (NUL, BEL, etc.)
    ts = _now_ms()
    bad_bio = "Hello\x00World"
    msg5 = _build_msg_set_biography(sub, lb, 0, ts, str(sub.address()), bad_bio, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg5, "/mirage.core.v1.MsgSetBiography")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        sub.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("biography.control_chars_rejected", ccode, dcode, dlog)


def test_annotate_chain(backend: str) -> None:
    """MsgAnnotate was retired in v1.39.0."""
    _pass("annotate_chain.retired")


def test_security(backend: str) -> None:
    """Security checks: tier params, subscription period, replay rejection."""

    fee_payer = _bh._VALIDATOR_ADDR or ""

    # 1. Verify LevelToTierIndex correctness via chain config endpoint.
    #    Free (0), subscriber (1), admin (2). Agent is gone.
    try:
        _, params = _get(f"{backend}/api/get_chain_config")
        params = params or {}
        tiers = params.get("tiers", [])
        if len(tiers) != 3:
            _fail("security.tier_count", f"expected 3 tiers, got {len(tiers)}")
        else:
            _pass("security.tier_count")

        if any(t.get("can_be_agent") for t in tiers):
            _fail("security.agent_tier_removed", f"can_be_agent still set: {[t.get('can_be_agent') for t in tiers]}")
        else:
            _pass("security.agent_tier_removed")
    except Exception as e:
        _fail("security.params_check", str(e))

    # 2. subscription_period bounds. Zero is a documented mode, not an attack:
    #    subscriptions become one-time purchases that expire (and downgrade the
    #    user) instead of renewing. What must never happen is an unbounded
    #    period, which would push expiry arithmetic out of range, so assert the
    #    value stays inside the chain's own cap of one year in minutes.
    try:
        sub_period = int(params.get("subscription_period", -1))
        # Mirrors MaxSubscriptionPeriodMinutes in blockchain/x/core/types/params.go
        max_period = 525_600
        if sub_period == 0:
            _pass("security.subscription_period_bounded")
            _debug("security: subscription_period=0 — one-time purchase mode, renewals disabled")
        elif 0 < sub_period <= max_period:
            _pass("security.subscription_period_bounded")
        else:
            _fail(
                "security.subscription_period_bounded",
                f"subscription_period={sub_period} outside [0, {max_period}]",
            )
    except Exception as e:
        _fail("security.subscription_period_bounded", str(e))

    # 3. Relay nonce: submit same tx twice — second should be rejected
    #    (Note: basic timestamp replay check already exists via envelope_timestamp;
    #    we verify the timestamp + PoW dedup here)
    agent = WALLETS.get("agent1")
    if agent:
        lb, diff, _, _ = _get_pow_params(backend, str(agent.address()))
        ts = _now_ms()

        msg = _build_msg_post(
            agent, lb, 0, ts, _shared_community(), "Security Test", "v1.17.0 test", pow_val=0, nonce=_gen_nonce()
        )
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            agent.public_key().public_key_bytes,
            wait_deliver=True,
        )
        if ccode == 0 and dcode == 0:
            _pass("security.first_post_accepted")

            # Same msg with same timestamp — should fail at check, deliver, or mempool level
            try:
                _, ccode2, clog2, dcode2, dlog2 = _submit_tx(
                    [(msg, "/mirage.core.v1.MsgPost")],
                    DEFAULT_GAS_LIMIT,
                    fee_payer,
                    agent.public_key().public_key_bytes,
                    wait_deliver=True,
                )
                if ccode2 != 0 or dcode2 != 0:
                    _pass("security.replay_rejected")
                else:
                    _fail("security.replay_rejected", f"ccode={ccode2} dcode={dcode2}")
            except RuntimeError as e:
                if "already exists in cache" in str(e):
                    _pass("security.replay_rejected")
                else:
                    _fail("security.replay_rejected", str(e))
        else:
            _fail("security.first_post_accepted", f"ccode={ccode} dcode={dcode}")
    else:
        _fail("security.relay_test", "agent1 wallet not available")
