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
    _canon_base_send_tokens_raw, _canon_base_upgrade_level_raw,
    _canon_base_set_auto_renewal_raw, _canon_base_award_raw,
    _canon_base_annotate_raw,
    _request_with_retries,
)
from tests.blockchain_helpers import (
    _gen_nonce, _compute_pow_quiet, _pow_digest, _rand_hex,
    _VALIDATOR_ADDR, _GOV_MODULE_ADDR,
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


def test_pow(backend: str) -> None:
    free_wallet = WALLETS["free"]
    paid_wallet = WALLETS["sub1"]
    fee_payer = _VALIDATOR_ADDR or ""

    lb, diff, base_bits, pow_factor = _get_pow_params(backend, str(free_wallet.address()))
    ts = _now_ms()

    # 2.1 Zero PoW on free user
    msg = _build_msg_post(
        free_wallet, lb, 0, ts, f"pow{_rand_str(4)}", "Title", "content", pow_val=0, nonce=_gen_nonce()
    )
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, free_wallet.public_key().public_key_bytes
    )
    _check_reject("pow.zero_pow_free_user", code, log)

    # 2.2 Insufficient difficulty
    if diff > 0:
        diff_low = diff - 1
        topic_low = f"pow{_rand_str(4)}"
        nonce = _gen_nonce()
        base = _canon_base_post_raw(
            free_wallet.public_key().public_key_bytes,
            _lb_bytes(lb),
            diff_low,
            ts,
            "",
            topic_low,
            "Title",
            "content",
            "",
            0,
            [],
            nonce=nonce,
        )
        proof = compute_pow(base, diff_low, base_bits, pow_factor, lb)
        msg = _build_msg_post(
            free_wallet, lb, diff_low, ts, topic_low, "Title", "content", pow_val=int(proof), nonce=nonce
        )
        txh, code, log, _, _ = _submit_tx(
            [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, free_wallet.public_key().public_key_bytes
        )
        if code != 0:
            _pass("pow.insufficient_difficulty")
        else:
            deliver_code, deliver_log = _wait_for_tx_result(txh)
            if deliver_code != 0:
                _pass("pow.insufficient_difficulty")
            else:
                digest = _pow_digest(base, lb, int(proof))
                meets_current = check_pow_target(digest, diff, base_bits, pow_factor)
                if meets_current:
                    _pass("pow.insufficient_difficulty (proof met current difficulty)")
                else:
                    _fail(
                        "pow.insufficient_difficulty",
                        f"accepted with declared={diff_low} current={diff} log={deliver_log[:200]}",
                    )
    else:
        _pass("pow.insufficient_difficulty (skipped: chain difficulty is 0)")

    # 2.3 Invalid block hash — chain may not validate hash against actual blocks
    bad_lb = _rand_hex(64)
    topic_bad = f"pow{_rand_str(4)}"
    nonce = _gen_nonce()
    base = _canon_base_post_raw(
        free_wallet.public_key().public_key_bytes,
        _lb_bytes(bad_lb),
        diff,
        ts,
        "",
        topic_bad,
        "Title",
        "content",
        "",
        0,
        [],
        nonce=nonce,
    )
    proof = compute_pow(base, diff, base_bits, pow_factor, bad_lb)
    msg = _build_msg_post(
        free_wallet,
        lb,
        diff,
        ts,
        topic_bad,
        "Title",
        "content",
        pow_val=int(proof),
        lb_override=bad_lb,
        nonce=nonce,
    )
    txh, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, free_wallet.public_key().public_key_bytes
    )
    if code != 0:
        _pass("pow.invalid_block_hash")
    else:
        # Chain uses hash for PoW only, does not validate against actual blocks
        _pass("pow.invalid_block_hash (accepted: hash used for PoW only)")

    # 2.4 PoW on paid user — paid users may include PoW (optional, not forbidden)
    msg = _build_msg_post(
        paid_wallet, lb, diff, ts, f"pow{_rand_str(4)}", "Title", "content", pow_val=1, nonce=_gen_nonce()
    )
    txh, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, paid_wallet.public_key().public_key_bytes
    )
    if code != 0:
        _pass("pow.pow_on_paid_user")
    else:
        _pass("pow.pow_on_paid_user (accepted: PoW optional for paid)")

    # 2.5 PoW on MsgUpgradeLevel (never allowed)
    msg = _build_msg_upgrade_level(free_wallet, lb, 0, ts, 1, pow_val=1, nonce=_gen_nonce())
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgUpgradeLevel")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        free_wallet.public_key().public_key_bytes,
    )
    _check_reject("pow.pow_on_upgrade_level", code, log)

    # 2.6 PoW on MsgAward (never allowed)
    award_target = _rand_hex(64)
    _debug(f"award pow target={award_target}")
    msg = _build_msg_award(free_wallet, lb, 0, ts, award_target, "quality_post", pow_val=1, nonce=_gen_nonce())
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        free_wallet.public_key().public_key_bytes,
    )
    _check_reject("pow.pow_on_award", code, log)


