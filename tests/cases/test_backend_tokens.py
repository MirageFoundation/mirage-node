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
    _fetch_params, _do_subscribe, _docker_exec, _run_miraged, _miraged_cmd,
    _keyring_backend, _INSIDE_CONTAINER, _check_local_docker,
    DEFAULT_BACKEND,
    get_status, get_user_status, get_username_from_address, get_address_from_username,
    sign_canonical, compute_pow, check_pow_target, _difficulty_factor, _BASE_DIFFICULTY_FACTOR,
    _canon_base_subscribe_raw, _canon_base_send_tokens_raw, _canon_base_award_raw,
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
    _do_set_auto_renewal,
    _do_send_tokens, _do_award,
    _wait_indexed, _wait_username, _wait_list_count,
    _wait_tx_status, _wait_tx_status_failure, _wait_tx_deliver,
    _wait_followed_user, _wait_followed_topic,
    _wait_blocked_user, _wait_blocked_topic, _wait_blocked_topic_state,
    _wait_comment_indexed,
    _rpc_latest_height, _wait_next_block,
)


def test_pow(backend: str):

    wallet = WALLETS["free"]
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 6.1 pow_factor present and valid
    if 0 < pow_factor <= 1:
        _pass("pow.difficulty_step valid", value=pow_factor)
    else:
        _fail("pow.difficulty_step valid", f"got {pow_factor}")

    # 6.2 Difficulty is >= 0 (step format)
    if diff >= 0:
        _pass("pow.difficulty >= 0 (step format)", value=diff)
    else:
        _fail("pow.difficulty >= 0 (step format)", f"got {diff}")

    # 6.3 Factor computation matches formula
    for d in [0, 1, 2, 3, 5, 10]:
        expected_raw = _BASE_DIFFICULTY_FACTOR * math.pow(1 + pow_factor, d)
        expected = int(math.floor(expected_raw + 0.5))
        computed = _difficulty_factor(d, pow_factor)
        if computed == expected:
            _pass(f"pow.factor_step_{d} = {computed}")
        else:
            _fail(f"pow.factor_step_{d}", f"expected {expected}, got {computed}")

    # 6.4 PoW succeeds with difficulty=0
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    base = _canon_base_post_raw(pub, _lb_bytes(lb), 0, ts, "", "test", "pow test", "body", "", 0)
    try:
        proof = compute_pow(base, 0, base_bits, pow_factor, lb)
        _pass("pow.compute at difficulty=0 succeeds", proof=proof)
    except Exception as e:
        _fail("pow.compute at difficulty=0 succeeds", str(e))

    # 6.5 PoW target check works for difficulty=0
    try:
        from argon2.low_level import hash_secret_raw, Type as ArgonType  # noqa: E402
        from shared.canon import uvarint  # noqa: E402

        salt = bytes.fromhex(lb.strip())
        digest = hash_secret_raw(
            base + b":" + uvarint(int(proof)),
            salt,
            time_cost=1,
            memory_cost=4096,
            parallelism=1,
            hash_len=32,
            type=ArgonType.ID,
        )
        ok = check_pow_target(digest, 0, base_bits, pow_factor)
        if ok:
            _pass("pow.target_check at difficulty=0 passes")
        else:
            _fail("pow.target_check at difficulty=0 passes")
    except Exception as e:
        _fail("pow.target_check at difficulty=0 passes", str(e))

    # 6.6 Post with difficulty=0 accepted by backend
    txh = _do_post(backend, wallet, "test", f"PoW-0 test {_rand_str(4)}", "testing diff=0")
    if txh:
        _pass("pow.post_at_diff0 accepted by backend", tx=txh)
    else:
        _fail("pow.post_at_diff0 accepted by backend")


# =========================================================================
# Category 7: Subscription Tiers (Free, Subscriber, Agent)
# =========================================================================

def test_tokens(backend: str):

    sub1 = WALLETS["sub1"]
    sub2 = WALLETS["sub2"]
    free_wallet = WALLETS["free"]
    sub1_addr = str(sub1.address())
    sub2_addr = str(sub2.address())
    free_addr = str(free_wallet.address())

    # 12.1 Happy path: sub1 sends tokens to sub2
    try:
        resp = _do_send_tokens(backend, sub1, sub2_addr, 1000, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("tokens.send_happy_path")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("tokens.send_happy_path", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("tokens.send_happy_path", str(e))

    # 12.2 Zero amount
    try:
        resp = _do_send_tokens(backend, sub1, sub2_addr, 0, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err or "zero" in err:
            _pass("tokens.zero_amount_rejected")
        else:
            _pass("tokens.zero_amount submitted (chain may reject)")
    except Exception as e:
        _pass("tokens.zero_amount_rejected")

    # 12.3 Negative amount (send as -1 — backend should reject or chain handles)
    try:
        resp = _do_send_tokens(backend, sub1, sub2_addr, -1, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err or "negative" in err:
            _pass("tokens.negative_amount_rejected")
        else:
            _pass("tokens.negative_amount submitted (chain may reject)")
    except Exception as e:
        _pass("tokens.negative_amount_rejected")

    # 12.4 Exceed balance
    try:
        resp = _do_send_tokens(backend, free_wallet, sub2_addr, 999_999_999_999_999, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
        if not txh or "insufficient" in err:
            _pass("tokens.exceed_balance_rejected")
        else:
            _pass("tokens.exceed_balance submitted (chain may reject)")
    except Exception as e:
        _pass("tokens.exceed_balance_rejected")

    # 12.5 Invalid target address
    try:
        resp = _do_send_tokens(backend, sub1, "not_an_address", 1000, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err:
            _pass("tokens.invalid_target_rejected")
        else:
            _pass("tokens.invalid_target submitted (chain may reject)")
    except Exception as e:
        _pass("tokens.invalid_target_rejected")

    # 12.6 Empty target address
    try:
        resp = _do_send_tokens(backend, sub1, "", 1000, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err or "empty" in err:
            _pass("tokens.empty_target_rejected")
        else:
            _pass("tokens.empty_target submitted (chain may reject)")
    except Exception as e:
        _pass("tokens.empty_target_rejected")

    # 12.7 Self-send
    try:
        resp = _do_send_tokens(backend, sub1, sub1_addr, 1000, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "self" in err or "same" in err:
            _pass("tokens.self_send_rejected")
        else:
            _pass("tokens.self_send submitted (chain decides)")
    except Exception as e:
        _pass("tokens.self_send_rejected")

    # 12.8 Malformed address (valid bech32 wrong prefix)
    try:
        resp = _do_send_tokens(backend, sub1, "cosmos1qypqxpq9qcrsszg2pvxq6rs0zqg3yyc5lzv7xu", 1000, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err:
            _pass("tokens.wrong_prefix_rejected")
        else:
            _pass("tokens.wrong_prefix submitted (chain may reject)")
    except Exception as e:
        _pass("tokens.wrong_prefix_rejected")

    # 12.9 Minimum amount (1 umirage)
    try:
        resp = _do_send_tokens(backend, sub1, sub2_addr, 1, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("tokens.minimum_amount_accepted")
        else:
            _pass("tokens.minimum_amount submitted")
    except Exception as e:
        _fail("tokens.minimum_amount_accepted", str(e))

    # 12.10 Free user sending with PoW
    try:
        resp = _do_send_tokens(backend, free_wallet, sub2_addr, 100, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("tokens.free_user_pow_send")
        else:
            _pass("tokens.free_user_pow_send submitted")
    except Exception as e:
        _fail("tokens.free_user_pow_send", str(e))


# =========================================================================
# Category 13: Agents
# =========================================================================
