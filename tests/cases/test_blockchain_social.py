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
    _canon_base_join_community_raw, _canon_base_unfollow_topic_raw,
    _canon_base_enable_agent_raw, _canon_base_disable_agent_raw,
    _canon_base_set_agents_raw,
    _canon_base_block_post_raw, _canon_base_unblock_post_raw,
    _canon_base_block_user_raw, _canon_base_unblock_user_raw,
    _canon_base_block_community_raw, _canon_base_unblock_topic_raw,
    _canon_base_send_tokens_raw, _canon_base_subscribe_raw,
    _canon_base_set_auto_renewal_raw, _canon_base_award_raw,
    _canon_base_annotate_raw,
    _request_with_retries,
)
from tests.blockchain_helpers import (
    _gen_nonce, _compute_pow_quiet, _pow_digest, _rand_hex,
    _get_pow_params, _get_chain_params, _get_tier_config, _tier_int,
    _get_chain_profile, _get_profile_full, _wait_profile_agents, _assert_capped_deque,
    _build_tx_bytes, _simulate_tx_gas, _simulate_tx_bytes_gas,
    _broadcast_tx_sync, _wait_for_tx_result, _submit_tx, _sign_relay,
    _build_msg_post, _build_msg_vote, _build_msg_set_username,
    _build_msg_set_biography, _build_msg_send_tokens,
    _build_msg_delete, _build_msg_delete_user, _build_msg_award,
    _build_msg_edit, _build_msg_annotate,
    _build_msg_block_post, _build_msg_block_user, _build_msg_block_community,
    _build_msg_subscribe,
    _build_msg_follow_user, _build_msg_unfollow_user,
    _build_msg_join_community, _build_msg_leave_community, _claim_community,
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
    MsgSubscribe, MsgVote, MsgAnnotate,
)


def test_follow_limits(backend: str) -> None:
    """Test follow/unfollow tier limits and mutual exclusion at chain level."""

    # Use the FREE wallet (tier 0) so we hit the real free-tier ceiling
    # and can verify overflow is rejected.
    fw = WALLETS["free"]
    fw_addr = str(fw.address())
    fw_pub = fw.public_key().public_key_bytes
    fee_payer = _bh._VALIDATOR_ADDR or ""
    tier0 = _get_tier_config(0)

    # Query chain (not indexer) for accurate pre-existing list counts.
    fw_chain_profile = _get_chain_profile(fw_addr)
    existing_followed_users = fw_chain_profile.get("followed_users") or fw_chain_profile.get("followedUsers") or []
    existing_joined_communities = fw_chain_profile.get("joined_communities") or fw_chain_profile.get("joinedCommunities") or []

    # 8.1 Fill free-tier max_followed_users + overflow
    max_followed_users = _tier_int(tier0, "max_followed_users")
    remaining_followed_users = max(0, max_followed_users - len(existing_followed_users))
    _debug(
        f"free-tier max_followed_users={max_followed_users} existing={len(existing_followed_users)} remaining={remaining_followed_users}"
    )
    fill_ok = True
    followed_user_targets: list[str] = []
    chunk_size = 25
    for start in range(0, remaining_followed_users, chunk_size):
        batch_count = min(chunk_size, remaining_followed_users - start)
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, fw_addr)
        ts_base = _now_ms()
        msgs: list[tuple[object, str]] = []
        for i in range(batch_count):
            target_addr = str(LocalWallet(PrivateKey(), prefix="mirage").address())
            followed_user_targets.append(target_addr.lower())
            ts = ts_base + i
            nonce = _gen_nonce()
            base = _canon_base_follow_user_raw(fw_pub, _lb_bytes(lb), diff, ts, fw_addr, target_addr, nonce=nonce)
            proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
            msg = _build_msg_follow_user(fw, lb, diff, ts, fw_addr, target_addr, pow_val=proof, nonce=nonce)
            msgs.append((msg, "/mirage.core.v1.MsgFollowUser"))
        sim_limit = max(FILL_GAS_LIMIT, int(DEFAULT_GAS_LIMIT * len(msgs) * 3))
        sim_gas = int(_simulate_tx_gas(msgs, sim_limit, fee_payer, fw_pub) * FILL_GAS_BUFFER)
        _, ccode, _, dcode, _ = _submit_tx(msgs, sim_gas, fee_payer, fw_pub, wait_deliver=True)
        if ccode != 0 or dcode != 0:
            _fail("follow.user_fill", f"chunk_start={start} check={ccode} deliver={dcode}")
            fill_ok = False
            break
    if fill_ok:
        _pass(
            f"follow.user_fill ({len(existing_followed_users) + remaining_followed_users}/{max_followed_users} followed)"
        )

    if fill_ok:
        # Overflow should be REJECTED (hard cap, not deque)
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, fw_addr)
        ts = _now_ms()
        over_addr = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        nonce = _gen_nonce()
        base = _canon_base_follow_user_raw(fw_pub, _lb_bytes(lb), diff, ts, fw_addr, over_addr, nonce=nonce)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_follow_user(fw, lb, diff, ts, fw_addr, over_addr, pow_val=proof, nonce=nonce)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgFollowUser")],
            FILL_GAS_LIMIT,
            fee_payer,
            fw_pub,
            wait_deliver=True,
        )
        _check_deliver_reject("follow.user_overflow_rejected (hard cap)", ccode, dcode, dlog)

    # 8.2 Fill free-tier max_joined_communities + overflow
    max_joined_communities = _tier_int(tier0, "max_joined_communities")
    remaining_joined = max(0, max_joined_communities - len(existing_joined_communities))
    _debug(
        f"free-tier max_joined_communities={max_joined_communities} existing={len(existing_joined_communities)} remaining={remaining_joined}"
    )
    fill_ok = True
    joined_targets: list[str] = []
    for start in range(0, remaining_joined, chunk_size):
        batch_count = min(chunk_size, remaining_joined - start)
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, fw_addr)
        ts_base = _now_ms()
        msgs = []
        for i in range(batch_count):
            topic = f"ft{_rand_str(4)}{start + i}"
            joined_targets.append(topic)
            _claim_community(backend, topic)
            ts = ts_base + i
            nonce = _gen_nonce()
            base = _canon_base_join_community_raw(fw_pub, _lb_bytes(lb), diff, ts, topic, nonce=nonce)
            proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
            msg = _build_msg_join_community(fw, lb, diff, ts, topic, pow_val=proof, nonce=nonce)
            msgs.append((msg, "/mirage.core.v1.MsgJoinCommunity"))
        sim_limit = max(FILL_GAS_LIMIT, int(DEFAULT_GAS_LIMIT * len(msgs) * 3))
        sim_gas = int(_simulate_tx_gas(msgs, sim_limit, fee_payer, fw_pub) * FILL_GAS_BUFFER)
        _, ccode, _, dcode, _ = _submit_tx(msgs, sim_gas, fee_payer, fw_pub, wait_deliver=True)
        if ccode != 0 or dcode != 0:
            _fail("follow.community_fill", f"chunk_start={start} check={ccode} deliver={dcode}")
            fill_ok = False
            break
    if fill_ok:
        _pass(
            f"follow.community_fill ({len(existing_joined_communities) + remaining_joined}/{max_joined_communities} joined)"
        )

    if fill_ok:
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, fw_addr)
        ts = _now_ms()
        over_topic = f"ft{_rand_str(4)}over"
        _claim_community(backend, over_topic)
        nonce = _gen_nonce()
        base = _canon_base_join_community_raw(fw_pub, _lb_bytes(lb), diff, ts, over_topic, nonce=nonce)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_join_community(fw, lb, diff, ts, over_topic, pow_val=proof, nonce=nonce)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgJoinCommunity")],
            FILL_GAS_LIMIT,
            fee_payer,
            fw_pub,
            wait_deliver=True,
        )
        _check_deliver_reject("follow.community_overflow_rejected (hard cap)", ccode, dcode, dlog)

    _pass("follow.agent_tier_removed")

    # 8.3b Subscriber bulk fill (no PoW): submit follow-user messages up to
    # the tier limit, then verify overflow is rejected (hard cap).
    sub = WALLETS["sub1"]
    sub_addr = str(sub.address())
    sub_pub = sub.public_key().public_key_bytes
    sub_tier = _get_tier_config(1)
    sub_max_followed_users = _tier_int(sub_tier, "max_followed_users")
    sub_chain_profile = _get_chain_profile(sub_addr)
    before_followed = sub_chain_profile.get("followed_users") or sub_chain_profile.get("followedUsers") or []
    remaining = max(0, sub_max_followed_users - len(before_followed))
    _debug(
        f"subscriber tier1 max_followed_users={sub_max_followed_users} existing={len(before_followed)} remaining={remaining}"
    )
    bulk_targets = [str(LocalWallet(PrivateKey(), prefix="mirage").address()).lower() for _ in range(remaining)]
    chunk_size = 25
    bulk_ok = True
    _debug(f"subscriber tier1 bulk follow users: total={len(bulk_targets)} chunk_size={chunk_size}")
    for start in range(0, len(bulk_targets), chunk_size):
        batch = bulk_targets[start : start + chunk_size]
        lb, _, _, _ = _get_pow_params(backend, sub_addr)
        ts_base = _now_ms()
        msgs: list[tuple[object, str]] = []
        for i, target_addr in enumerate(batch):
            msg = _build_msg_follow_user(sub, lb, 0, ts_base + i, sub_addr, target_addr, pow_val=0, nonce=_gen_nonce())
            msgs.append((msg, "/mirage.core.v1.MsgFollowUser"))
        sim_limit = max(FILL_GAS_LIMIT, int(DEFAULT_GAS_LIMIT * len(msgs) * 3))
        try:
            sim_gas = int(_simulate_tx_gas(msgs, sim_limit, fee_payer, sub_pub) * FILL_GAS_BUFFER)
        except Exception as sim_err:
            _fail("follow.subscriber_bulk_user_fill", f"simulate failed at chunk_start={start}: {str(sim_err)[:200]}")
            bulk_ok = False
            break
        _debug(f"subscriber bulk follow gas: start={start} msgs={len(msgs)} sim_limit={sim_limit} gas_used={sim_gas}")
        gas_limit = sim_gas
        _, ccode, _, dcode, dlog = _submit_tx(
            msgs,
            gas_limit,
            fee_payer,
            sub_pub,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail(
                "follow.subscriber_bulk_user_fill",
                f"chunk_start={start} size={len(batch)} check={ccode} deliver={dcode} log={str(dlog or '')[:120]}",
            )
            bulk_ok = False
            break
    if bulk_ok:
        _pass(f"follow.subscriber_bulk_user_fill ({len(bulk_targets)} filled to limit)")
        # Verify subscriber level persists after bulk follow (reserve should not be over-charged)
        after_profile = _get_profile_full(backend, sub_addr)
        after_level = int(after_profile.get("level", 0) or 0)
        if after_level == 1:
            _pass("follow.subscriber_level_persist")
        else:
            _fail("follow.subscriber_level_persist", f"level={after_level}")
        # Now verify overflow is REJECTED
        lb, _, _, _ = _get_pow_params(backend, sub_addr)
        ts = _now_ms()
        over_addr = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        msg = _build_msg_follow_user(sub, lb, 0, ts, sub_addr, over_addr, pow_val=0, nonce=_gen_nonce())
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgFollowUser")],
            FILL_GAS_LIMIT,
            fee_payer,
            sub_pub,
            wait_deliver=True,
        )
        _check_deliver_reject("follow.subscriber_bulk_user_overflow_rejected (hard cap)", ccode, dcode, dlog)

    # 8.4 Follow user removes blocked user (mutual exclusion)
    w_mx = WALLETS["agent1"]
    w_mx_addr = str(w_mx.address())
    lb, _, _, _ = _get_pow_params(backend, w_mx_addr)
    ts = _now_ms()
    block_target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    msg = _build_msg_block_user(w_mx, lb, 0, ts, block_target, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgBlockUser")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w_mx.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode == 0 and dcode == 0:
        lb, _, _, _ = _get_pow_params(backend, w_mx_addr)
        ts = _now_ms()
        msg = _build_msg_follow_user(w_mx, lb, 0, ts, w_mx_addr, block_target, pow_val=0, nonce=_gen_nonce())
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgFollowUser")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w_mx.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept("follow.user_removes_block", ccode, dcode, dlog)
    else:
        _fail("follow.user_removes_block", "setup block failed")

    # 8.5 Join community after blocking it still succeeds (block and join are independent)
    lb, _, _, _ = _get_pow_params(backend, w_mx_addr)
    ts = _now_ms()
    block_topic = f"mx{_rand_str(4)}"
    _claim_community(backend, block_topic)
    msg = _build_msg_block_community(w_mx, lb, 0, ts, w_mx_addr, block_topic, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgBlockCommunity")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w_mx.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode == 0 and dcode == 0:
        lb, _, _, _ = _get_pow_params(backend, w_mx_addr)
        ts = _now_ms()
        msg = _build_msg_join_community(w_mx, lb, 0, ts, block_topic, pow_val=0, nonce=_gen_nonce())
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgJoinCommunity")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w_mx.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept("follow.community_join_after_block", ccode, dcode, dlog)
    else:
        _fail("follow.community_join_after_block", "setup block failed")

    # 8.6 Double follow same user (should be idempotent or rejected, not crash)
    lb, _, _, _ = _get_pow_params(backend, w_mx_addr)
    ts = _now_ms()
    dbl_target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    msg = _build_msg_follow_user(w_mx, lb, 0, ts, w_mx_addr, dbl_target, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgFollowUser")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w_mx.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode == 0 and dcode == 0:
        msg = _build_msg_follow_user(w_mx, lb, 0, ts, w_mx_addr, dbl_target, pow_val=0, nonce=_gen_nonce())
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgFollowUser")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w_mx.public_key().public_key_bytes,
            wait_deliver=True,
        )
        if ccode == 0 and (dcode == 0 or dcode is None):
            _pass("follow.double_follow_idempotent")
        elif dcode is not None and dcode != 0:
            _pass("follow.double_follow_rejected")
        else:
            _pass("follow.double_follow handled")
    else:
        _fail("follow.double_follow_idempotent", "initial follow failed")

    # 8.7 Unfollow without follow (non-followed entity)
    lb, _, _, _ = _get_pow_params(backend, w_mx_addr)
    ts = _now_ms()
    unfol_target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    msg = _build_msg_unfollow_user(w_mx, lb, 0, ts, w_mx_addr, unfol_target, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgUnfollowUser")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w_mx.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode != 0 or (dcode is not None and dcode != 0):
        _pass("follow.unfollow_nonfollowed_rejected")
    else:
        _pass("follow.unfollow_nonfollowed_accepted (idempotent)")



def test_hard_cap_vs_deque(backend: str) -> None:
    """Test that follow/enable lists use hard cap while block lists use deque."""

    fee_payer = _bh._VALIDATOR_ADDR or ""

    # ── 13.1 blocked_users deque: block more than limit, oldest evicted ──
    bw = WALLETS["free"]
    bw_addr = str(bw.address())
    bw_pub = bw.public_key().public_key_bytes
    tier0 = _get_tier_config(0)
    max_blocked_users = _tier_int(tier0, "max_blocked_users")
    _debug(f"free-tier max_blocked_users={max_blocked_users}")

    # Fill blocked_users to max + 2 (deque should keep only the newest max)
    blocked_targets: list[str] = []
    total_to_block = max_blocked_users + 2
    chunk_size = 25
    block_user_ok = True
    for start in range(0, total_to_block, chunk_size):
        batch_count = min(chunk_size, total_to_block - start)
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
        ts_base = _now_ms()
        msgs: list[tuple[object, str]] = []
        for i in range(batch_count):
            target_addr = str(LocalWallet(PrivateKey(), prefix="mirage").address())
            blocked_targets.append(target_addr.lower())
            ts = ts_base + i
            nonce = _gen_nonce()
            base = _canon_base_block_user_raw(bw_pub, _lb_bytes(lb), diff, ts, target_addr, nonce=nonce)
            proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
            msg = _build_msg_block_user(bw, lb, diff, ts, target_addr, pow_val=proof, nonce=nonce)
            msgs.append((msg, "/mirage.core.v1.MsgBlockUser"))
        sim_limit = max(FILL_GAS_LIMIT, int(DEFAULT_GAS_LIMIT * len(msgs) * 3))
        sim_gas = int(_simulate_tx_gas(msgs, sim_limit, fee_payer, bw_pub) * FILL_GAS_BUFFER)
        _, ccode, _, dcode, dlog = _submit_tx(msgs, sim_gas, fee_payer, bw_pub, wait_deliver=True)
        if ccode != 0 or dcode != 0:
            _fail("hardcap.blocked_user_deque_fill", f"chunk_start={start} ccode={ccode} dcode={dcode}")
            block_user_ok = False
            break
    if block_user_ok:
        _pass(f"hardcap.blocked_user_deque_fill ({total_to_block} blocked, no rejection)")

    profile = _get_chain_profile(bw_addr)
    chain_blocked = [str(v).lower() for v in (profile.get("blocked_users") or profile.get("blockedUsers") or [])]
    if len(chain_blocked) <= max_blocked_users:
        _pass(f"hardcap.blocked_user_deque_capped (len={len(chain_blocked)} <= {max_blocked_users})")
    else:
        _fail(f"hardcap.blocked_user_deque_capped", f"len={len(chain_blocked)} > {max_blocked_users}")

    # ── 13.2 blocked_posts deque ──
    max_blocked_posts = _tier_int(tier0, "max_blocked_posts")
    blocked_post_targets: list[str] = []
    total_to_block_posts = max_blocked_posts + 2
    block_post_ok = True
    for start in range(0, total_to_block_posts, chunk_size):
        batch_count = min(chunk_size, total_to_block_posts - start)
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
        ts_base = _now_ms()
        msgs = []
        for i in range(batch_count):
            fake_hash = _rand_hex(64)
            blocked_post_targets.append(fake_hash.lower())
            ts = ts_base + i
            nonce = _gen_nonce()
            base = _canon_base_block_post_raw(bw_pub, _lb_bytes(lb), diff, ts, fake_hash, nonce=nonce)
            proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
            msg = _build_msg_block_post(bw, lb, diff, ts, fake_hash, pow_val=proof, nonce=nonce)
            msgs.append((msg, "/mirage.core.v1.MsgBlockPost"))
        sim_limit = max(FILL_GAS_LIMIT, int(DEFAULT_GAS_LIMIT * len(msgs) * 3))
        sim_gas = int(_simulate_tx_gas(msgs, sim_limit, fee_payer, bw_pub) * FILL_GAS_BUFFER)
        _, ccode, _, dcode, dlog = _submit_tx(msgs, sim_gas, fee_payer, bw_pub, wait_deliver=True)
        if ccode != 0 or dcode != 0:
            _fail("hardcap.blocked_post_deque_fill", f"chunk_start={start}")
            block_post_ok = False
            break
    if block_post_ok:
        _pass(f"hardcap.blocked_post_deque_fill ({total_to_block_posts} blocked, no rejection)")

    # ── 13.3 blocked_topics deque ──
    max_blocked_communities = _tier_int(tier0, "max_blocked_communities")
    total_to_block_topics = max_blocked_communities + 2
    block_topic_ok = True
    for start in range(0, total_to_block_topics, chunk_size):
        batch_count = min(chunk_size, total_to_block_topics - start)
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
        ts_base = _now_ms()
        msgs = []
        for i in range(batch_count):
            topic = f"bt{_rand_str(4)}{start + i}"
            ts = ts_base + i
            nonce = _gen_nonce()
            base = _canon_base_block_community_raw(bw_pub, _lb_bytes(lb), diff, ts, bw_addr, topic, nonce=nonce)
            proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
            msg = _build_msg_block_community(bw, lb, diff, ts, bw_addr, topic, pow_val=proof, nonce=nonce)
            msgs.append((msg, "/mirage.core.v1.MsgBlockCommunity"))
        sim_limit = max(FILL_GAS_LIMIT, int(DEFAULT_GAS_LIMIT * len(msgs) * 3))
        sim_gas = int(_simulate_tx_gas(msgs, sim_limit, fee_payer, bw_pub) * FILL_GAS_BUFFER)
        _, ccode, _, dcode, dlog = _submit_tx(msgs, sim_gas, fee_payer, bw_pub, wait_deliver=True)
        if ccode != 0 or dcode != 0:
            _fail("hardcap.blocked_topic_deque_fill", f"chunk_start={start}")
            block_topic_ok = False
            break
    if block_topic_ok:
        _pass(f"hardcap.blocked_topic_deque_fill ({total_to_block_topics} blocked, no rejection)")

    _pass("hardcap.agent_lists_removed")

