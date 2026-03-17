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
from cosmpy.aerial.wallet import LocalWallet
from cosmpy.crypto.keypairs import PrivateKey

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
    _canon_base_send_tokens_raw, _canon_base_upgrade_level_raw,
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
    _build_msg_upgrade_level,
    _build_msg_follow_user, _build_msg_unfollow_user,
    _build_msg_follow_topic, _build_msg_unfollow_topic,
    _build_msg_enable_agent, _build_msg_disable_agent, _build_msg_set_agents,
    _build_msg_unblock_post, _build_msg_unblock_user, _build_msg_unblock_topic,
    _build_msg_set_auto_renewal,
    _check_reject, _check_accept, _check_deliver_reject, _check_deliver_accept,
    _min_gas_price_umirage, _get_grpc_target,
    DEFAULT_GAS_LIMIT, FILL_GAS_LIMIT, FILL_GAS_BUFFER,
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
    MsgUpgradeLevel, MsgVote, MsgAnnotate,
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
    """Chain-level tests for MsgAnnotate validation."""

    agent = WALLETS.get("agent1")
    free = WALLETS.get("free")
    if not agent or not free:
        _fail("annotate_chain.setup", "wallets not available")
        return

    fee_payer = _bh._VALIDATOR_ADDR or ""
    signer_pub = agent.public_key().public_key_bytes

    # Get chain params
    lb, diff, _, _ = _get_pow_params(backend, str(agent.address()))
    ts = _now_ms()

    # First create a post to annotate (via backend for convenience)
    from tests.backend_helpers import _do_post, _wait_indexed
    txh = _do_post(backend, free, "test", f"ChainAnnotateTarget {_rand_str(6)}", "content")
    if not txh:
        _fail("annotate_chain.create_target")
        return
    _wait_indexed(backend, str(free.address()), txh)
    _pass("annotate_chain.create_target")

    # 1. Non-agent submitting annotate should fail
    msg = _build_msg_annotate(free, lb, 0, ts, ".", ".", ".", ".", txh, appendix="hacker note", nonce=_gen_nonce())
    tx_hash, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAnnotate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        free.public_key().public_key_bytes,
    )
    _check_reject("annotate_chain.non_agent_rejected", code, log, "agent tier", tx_hash)

    # 2. Agent with valid sentinel should succeed
    msg = _build_msg_annotate(agent, lb, 0, ts, ".", ".", ".", ".", txh, appendix="valid note", nonce=_gen_nonce())
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAnnotate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        signer_pub,
        wait_deliver=True,
    )
    _check_deliver_accept("annotate_chain.agent_annotate_ok", code, dcode, dlog)

    # 3. Invalid relay signature should fail
    msg = _build_msg_annotate(agent, lb, 0, ts, ".", ".", ".", ".", txh, appendix="bad sig", nonce=_gen_nonce())
    msg.envelope_signature = b"\x00" * 64
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAnnotate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        signer_pub,
    )
    _check_reject("annotate_chain.bad_signature", code, log, "relay signature")

    # 4. Annotate should reject PoW fields
    msg = _build_msg_annotate(agent, lb, 1, ts, ".", ".", ".", ".", txh, appendix="pow", nonce=_gen_nonce())
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAnnotate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        signer_pub,
    )
    _check_reject("annotate_chain.pow_rejected", code, log, "pow")

    # 5. Invalid override should fail (rejected at DeliverTx, not CheckTx)
    msg = _build_msg_annotate(agent, lb, 0, ts, ".", ".", ".", ".", "invalid", appendix="note", nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAnnotate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        signer_pub,
        wait_deliver=True,
    )
    _check_deliver_reject("annotate_chain.invalid_override", ccode, dcode, dlog)

    # 6. Title exceeding MaxTitleLength should be rejected
    tier_agent = _get_tier_config(10)
    max_title = _tier_int(tier_agent, "max_title_length")
    over_title = "A" * (max_title + 1)
    msg = _build_msg_annotate(agent, lb, 0, _now_ms(), ".", over_title, ".", ".", txh, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAnnotate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        signer_pub,
        wait_deliver=True,
    )
    _check_deliver_reject("annotate_chain.title_too_long", ccode, dcode, dlog)

    # 7. Content exceeding MaxContentLength should be rejected
    max_content = _tier_int(tier_agent, "max_content_length")
    over_content = "B" * (max_content + 1)
    msg = _build_msg_annotate(agent, lb, 0, _now_ms(), ".", ".", over_content, ".", txh, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAnnotate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        signer_pub,
        wait_deliver=True,
    )
    _check_deliver_reject("annotate_chain.content_too_long", ccode, dcode, dlog)

    # 8. Appendix exceeding MaxContentLength should be rejected
    over_appendix = "C" * (max_content + 1)
    msg = _build_msg_annotate(
        agent, lb, 0, _now_ms(), ".", ".", ".", ".", txh, appendix=over_appendix, nonce=_gen_nonce()
    )
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAnnotate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        signer_pub,
        wait_deliver=True,
    )
    _check_deliver_reject("annotate_chain.appendix_too_long", ccode, dcode, dlog)

    # 9. Title exactly at limit should succeed
    exact_title = "D" * max_title
    msg = _build_msg_annotate(agent, lb, 0, _now_ms(), ".", exact_title, ".", ".", txh, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAnnotate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        signer_pub,
        wait_deliver=True,
    )
    _check_deliver_accept("annotate_chain.title_at_limit_ok", ccode, dcode, dlog)

    # 10. Subscriber (level 1) submitting annotate should fail
    sub = WALLETS.get("sub1")
    if sub:
        msg = _build_msg_annotate(
            sub, lb, 0, _now_ms(), ".", ".", ".", ".", txh, appendix="sub note", nonce=_gen_nonce()
        )
        tx_hash, code, log, _, _ = _submit_tx(
            [(msg, "/mirage.core.v1.MsgAnnotate")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            sub.public_key().public_key_bytes,
        )
        _check_reject("annotate_chain.subscriber_rejected", code, log, "agent tier", tx_hash)

    # 11. No-username wallet submitting annotate should fail
    noname_wallet = LocalWallet(PrivateKey(), prefix="mirage")
    msg = _build_msg_annotate(
        noname_wallet, lb, 0, _now_ms(), ".", ".", ".", ".", txh, appendix="x", nonce=_gen_nonce()
    )
    tx_hash, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAnnotate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        noname_wallet.public_key().public_key_bytes,
    )
    _check_reject("annotate_chain.no_username_rejected", code, log, "username", tx_hash)

    # 12. EnableAgent self-enable (agent == owner) — chain should reject
    agent_addr = str(agent.address())
    msg = _build_msg_enable_agent(agent, lb, 0, _now_ms(), agent_addr, agent_addr, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgEnableAgent")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        signer_pub,
        wait_deliver=True,
    )
    if ccode != 0 or (dcode is not None and dcode != 0):
        _pass("annotate_chain.self_enable_rejected")
    else:
        _fail("annotate_chain.self_enable_rejected", f"BUG: EnableAgent allows self-enable (SetAgents rejects it)")

    # 13. SetAgents with more than tier max should be rejected
    max_agents = _tier_int(tier_agent, "max_enabled_agents")
    over_agents = [str(LocalWallet(PrivateKey(), prefix="mirage").address()) for _ in range(max_agents + 1)]
    msg = _build_msg_set_agents(agent, lb, 0, _now_ms(), agent_addr, over_agents, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetAgents")],
        DEFAULT_GAS_LIMIT * 5,
        fee_payer,
        signer_pub,
        wait_deliver=True,
    )
    _check_deliver_reject("annotate_chain.set_agents_over_max", ccode, dcode, dlog)

    # 14. EnableAgent without username should fail
    noname_wallet2 = LocalWallet(PrivateKey(), prefix="mirage")
    noname_addr = str(noname_wallet2.address())
    random_agent = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    lb2, diff2, base_bits2, pow_factor2 = _get_pow_params(backend, noname_addr)
    ts2 = _now_ms()
    nonce2 = _gen_nonce()
    base2 = _canon_base_enable_agent_raw(
        noname_wallet2.public_key().public_key_bytes,
        _lb_bytes(lb2),
        diff2,
        ts2,
        noname_addr,
        random_agent,
        nonce=nonce2,
    )
    proof2 = _compute_pow_quiet(base2, diff2, base_bits2, pow_factor2, lb2)
    msg = _build_msg_enable_agent(
        noname_wallet2, lb2, diff2, ts2, noname_addr, random_agent, pow_val=proof2, nonce=nonce2
    )
    tx_hash, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgEnableAgent")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        noname_wallet2.public_key().public_key_bytes,
    )
    _check_reject("annotate_chain.enable_no_username", code, log, "username", tx_hash)

    # 15. SetAgents without username should fail
    lb3, diff3, base_bits3, pow_factor3 = _get_pow_params(backend, noname_addr)
    ts3 = _now_ms()
    nonce3 = _gen_nonce()
    base3 = _canon_base_set_agents_raw(
        noname_wallet2.public_key().public_key_bytes,
        _lb_bytes(lb3),
        diff3,
        ts3,
        noname_addr,
        [random_agent],
        nonce=nonce3,
    )
    proof3 = _compute_pow_quiet(base3, diff3, base_bits3, pow_factor3, lb3)
    msg = _build_msg_set_agents(
        noname_wallet2, lb3, diff3, ts3, noname_addr, [random_agent], pow_val=proof3, nonce=nonce3
    )
    tx_hash, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetAgents")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        noname_wallet2.public_key().public_key_bytes,
    )
    _check_reject("annotate_chain.setagents_no_username", code, log, "username", tx_hash)



def test_security(backend: str) -> None:
    """Security checks: tier params, subscription period, bridge threshold, replay rejection."""

    fee_payer = _bh._VALIDATOR_ADDR or ""

    # 1. Verify LevelToTierIndex correctness via chain config endpoint
    #    Agent (level 10) must have a valid tier config (not be skipped)
    try:
        resp = requests.get(f"{backend}/api/get_chain_config", timeout=10)
        params = resp.json()
        tiers = params.get("tiers", [])
        if len(tiers) != 3:
            _fail("security.tier_count", f"expected 3 tiers, got {len(tiers)}")
        else:
            _pass("security.tier_count")

        # Level 10 (Agent) must map to tier index 2 which has can_be_agent=True
        agent_tier = tiers[2] if len(tiers) > 2 else {}
        if agent_tier.get("can_be_agent"):
            _pass("security.agent_tier_valid")
        else:
            _fail("security.agent_tier_valid", f"tier[2].can_be_agent={agent_tier.get('can_be_agent')}")
    except Exception as e:
        _fail("security.params_check", str(e))

    # 2. Verify subscription_period is non-zero (M-8 SubscriptionPeriod=0 governance attack)
    try:
        sub_period = int(params.get("subscription_period", 0))
        if sub_period > 0:
            _pass("security.subscription_period_nonzero")
        else:
            _fail("security.subscription_period_nonzero", f"subscription_period={sub_period}")
    except Exception as e:
        _fail("security.subscription_period_nonzero", str(e))

    # 3. Bridge attestation threshold should be > 0 and <= 1
    try:
        threshold = float(params.get("bridge_attestation_threshold", 0))
        if 0 < threshold <= 1:
            _pass("security.bridge_threshold_valid")
        else:
            _fail("security.bridge_threshold_valid", f"threshold={threshold}")
    except Exception as e:
        _fail("security.bridge_threshold_valid", str(e))

    # 4. Relay nonce: submit same tx twice — second should be rejected
    #    (Note: basic timestamp replay check already exists via envelope_timestamp;
    #    we verify the timestamp + PoW dedup here)
    agent = WALLETS.get("agent1")
    if agent:
        lb, diff, _, _ = _get_pow_params(backend, str(agent.address()))
        ts = _now_ms()

        msg = _build_msg_post(
            agent, lb, 0, ts, f"sec{_rand_str(4)}", "Security Test", "v1.17.0 test", pow_val=0, nonce=_gen_nonce()
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


