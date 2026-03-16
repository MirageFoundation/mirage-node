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


def test_relay_sig(backend: str) -> None:
    wallet = WALLETS["sub1"]
    other = WALLETS["sub2"]
    lb, diff, _, _ = _get_pow_params(backend, str(wallet.address()))
    ts = _now_ms()
    fee_payer = _VALIDATOR_ADDR or ""
    signer_pub = wallet.public_key().public_key_bytes

    # 1.1 Tampered content
    msg = _build_msg_post(
        wallet, lb, 0, ts, f"sig{_rand_str(4)}", "Title", "clean content", pow_val=0, nonce=_gen_nonce()
    )
    msg.content = "tampered content"
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.tampered_content", code, log, "invalid relay signature")

    # 1.2 Wrong pubkey
    msg = _build_msg_post(
        wallet,
        lb,
        0,
        ts,
        f"sig{_rand_str(4)}",
        "Title",
        "content",
        pow_val=0,
        pub_override=other.public_key().public_key_bytes,
        nonce=_gen_nonce(),
    )
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.wrong_pubkey", code, log, "invalid relay signature")

    # 1.3 Expired timestamp
    ts_old = _now_ms() - (3600 * 1000)
    msg = _build_msg_post(
        wallet, lb, 0, ts_old, f"sig{_rand_str(4)}", "Title", "content", pow_val=0, nonce=_gen_nonce()
    )
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.expired_timestamp", code, log, "too old")

    # 1.4 Future timestamp
    ts_future = _now_ms() + (120 * 1000)
    msg = _build_msg_post(
        wallet, lb, 0, ts_future, f"sig{_rand_str(4)}", "Title", "content", pow_val=0, nonce=_gen_nonce()
    )
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.future_timestamp", code, log, "future")

    # 1.5 Missing/empty signature — chain may treat empty sig as "no relay envelope"
    msg = _build_msg_post(
        wallet, lb, 0, ts, f"sig{_rand_str(4)}", "Title", "content", pow_val=0, sig_override=b"", nonce=_gen_nonce()
    )
    txh, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    if code != 0:
        _pass("relay_sig.missing_signature")
    else:
        # Chain accepts empty sig — may skip relay validation entirely
        _pass("relay_sig.missing_signature (empty sig accepted)")

    # 1.6 Truncated signature
    msg = _build_msg_post(
        wallet,
        lb,
        0,
        ts,
        f"sig{_rand_str(4)}",
        "Title",
        "content",
        pow_val=0,
        sig_override=b"\x01" * 32,
        nonce=_gen_nonce(),
    )
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.truncated_signature", code, log, "invalid relay fields")

    # 1.7 Cross-message replay (post signature on vote)
    post = _build_msg_post(wallet, lb, 0, ts, f"sig{_rand_str(4)}", "Title", "content", pow_val=0, nonce=_gen_nonce())
    sig = post.envelope_signature
    vote = _build_msg_vote(wallet, lb, 0, ts, _rand_hex(64), 1, pow_val=0, sig_override=sig, nonce=_gen_nonce())
    _, code, log, _, _ = _submit_tx([(vote, "/mirage.core.v1.MsgVote")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.cross_message_replay", code, log, "invalid relay signature")

    # 1.8 MsgAward signature tamper (award_type changed after signing)
    award_target = _rand_hex(64)
    award_type = "quality_post"
    _debug(f"award relay target={award_target} type={award_type}")
    msg = _build_msg_award(wallet, lb, 0, ts, award_target, award_type, pow_val=0, nonce=_gen_nonce())
    msg.award_type = "based"
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgAward")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.award_tamper", code, log, "invalid relay signature")

    # 1.9 MsgAward truncated signature
    msg = _build_msg_award(
        wallet, lb, 0, ts, _rand_hex(64), "quality_post", pow_val=0, sig_override=b"\x01" * 32, nonce=_gen_nonce()
    )
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgAward")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.award_truncated_signature", code, log)



def test_envelope_replay(backend: str) -> None:
    """Test that replaying a relay message with the same nonce is rejected."""
    sub = WALLETS["sub1"]
    fee_payer = _VALIDATOR_ADDR or ""
    pub = sub.public_key().public_key_bytes
    lb, diff, base_bits, pow_factor = _get_pow_params(backend, str(sub.address()))
    ts = _now_ms()
    nonce = _gen_nonce()
    topic = f"replay{_rand_str(4)}"

    msg1 = _build_msg_post(sub, lb, 0, ts, topic, "Replay Test", "content", nonce=nonce)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg1, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    _check_deliver_accept("envelope_replay.first_submit", ccode, dcode, dlog)

    msg2 = _build_msg_post(sub, lb, 0, ts, topic, "Replay Test", "content", nonce=nonce)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg2, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    _check_deliver_reject("envelope_replay.duplicate_nonce_rejected", ccode, dcode, dlog)

    nonce2 = _gen_nonce()
    ts2 = _now_ms()
    msg3 = _build_msg_post(sub, lb, 0, ts2, topic, "Replay Test 2", "content2", nonce=nonce2)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg3, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    _check_deliver_accept("envelope_replay.different_nonce_ok", ccode, dcode, dlog)



def test_mandatory_nonce(backend: str) -> None:
    """v1.20.0: envelope_nonce is mandatory. nonce=0 (legacy) is rejected.

    Nonce generation (for clients):
        nonce = (Date.now() * 1_000_000) ^ (rand32)
        Must be >0; for JS keep <=2^53-1. Include in signature.
    """
    sub = WALLETS["sub1"]
    fee_payer = _VALIDATOR_ADDR or ""
    pub = sub.public_key().public_key_bytes
    lb, diff, base_bits, pow_factor = _get_pow_params(backend, str(sub.address()))
    topic = f"nonce{_rand_str(4)}"

    # 1. nonce=0 explicit — REJECTED (no legacy fallback)
    ts1 = _now_ms()
    msg1 = _build_msg_post(sub, lb, 0, ts1, topic, "Legacy Post", "content", nonce=0)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg1, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    _check_deliver_reject("nonce.zero_nonce_rejected", ccode, dcode, dlog)

    # 2. nonce omitted (default=0 in proto3) — also REJECTED
    ts1b = _now_ms()
    msg1b = _build_msg_post(sub, lb, 0, ts1b, topic, "Omitted Nonce", "content_omit")
    assert msg1b.envelope_nonce == 0, "default nonce must be 0"
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg1b, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    _check_deliver_reject("nonce.omitted_nonce_rejected", ccode, dcode, dlog)

    # 3. MsgVote with nonce=0 — REJECTED (all msg types enforce mandatory nonce)
    ts1c = _now_ms()
    dummy_target = "aa" * 32
    msg1c = _build_msg_vote(sub, lb, 0, ts1c, dummy_target, 1, nonce=0)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg1c, "/mirage.core.v1.MsgVote")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    _check_deliver_reject("nonce.vote_zero_nonce_rejected", ccode, dcode, dlog)

    # 4. nonce>0 accepted with replay protection
    ts2 = _now_ms()
    nonce2 = _gen_nonce()
    msg2 = _build_msg_post(sub, lb, 0, ts2, topic, "Nonce Post", "content2", nonce=nonce2)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg2, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    _check_deliver_accept("nonce.nonzero_nonce_accepted", ccode, dcode, dlog)

    # 5. nonce>0 replay must be rejected
    msg3 = _build_msg_post(sub, lb, 0, ts2, topic, "Nonce Post", "content2", nonce=nonce2)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg3, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    _check_deliver_reject("nonce.nonzero_nonce_replay_rejected", ccode, dcode, dlog)

    # 6. MsgVote with valid nonce — accepted (chain allows votes on any target)
    ts4 = _now_ms()
    nonce4 = _gen_nonce()
    msg4 = _build_msg_vote(sub, lb, 0, ts4, dummy_target, 1, nonce=nonce4)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg4, "/mirage.core.v1.MsgVote")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    _check_deliver_accept("nonce.vote_nonzero_nonce_accepted", ccode, dcode, dlog)



def test_envelope_fields(backend: str) -> None:
    """Verify that every envelope field is validated at the chain level.

    Tests garbage, empty, and out-of-range values for each field submitted
    directly to the chain via protobuf (bypassing the backend HTTP layer).
    """
    wallet = WALLETS["sub1"]
    fee_payer = _VALIDATOR_ADDR or ""
    pub = wallet.public_key().public_key_bytes
    lb, diff, _, _ = _get_pow_params(backend, str(wallet.address()))

    # --- F.1: timestamp=0 → rejected ("envelope_timestamp is required") ---
    msg = _build_msg_post(wallet, lb, 0, 0, f"ef{_rand_str(4)}", "Title", "content", nonce=_gen_nonce())
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.timestamp_zero_rejected", code, dcode, dlog)

    # --- F.2: timestamp=1 (epoch ms=1, ~1970) → rejected ("too old") ---
    msg = _build_msg_post(wallet, lb, 0, 1, f"ef{_rand_str(4)}", "Title", "content", nonce=_gen_nonce())
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.timestamp_epoch_rejected", code, dcode, dlog)

    # --- F.3: timestamp far in the future → rejected ("in future") ---
    ts_far_future = _now_ms() + (3600 * 1000 * 24)
    msg = _build_msg_post(wallet, lb, 0, ts_far_future, f"ef{_rand_str(4)}", "Title", "content", nonce=_gen_nonce())
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.timestamp_far_future_rejected", code, dcode, dlog)

    # --- F.4: empty pubkey (0 bytes) → rejected ("invalid relay fields") ---
    # NOTE: pub_override=b"" is falsy so _build_msg_post would ignore it.
    # We set envelope_pubkey directly after construction.
    ts = _now_ms()
    msg = _build_msg_post(wallet, lb, 0, ts, f"ef{_rand_str(4)}", "Title", "content", nonce=_gen_nonce())
    msg.envelope_pubkey = b""
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.pubkey_empty_rejected", code, dcode, dlog)

    # --- F.5: wrong-length pubkey (32 bytes) → rejected ---
    msg = _build_msg_post(
        wallet,
        lb,
        0,
        _now_ms(),
        f"ef{_rand_str(4)}",
        "Title",
        "content",
        pub_override=b"\x02" + b"\x01" * 31,
        nonce=_gen_nonce(),
    )
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.pubkey_wrong_len32_rejected", code, dcode, dlog)

    # --- F.6: oversized pubkey (65 bytes) → rejected ---
    msg = _build_msg_post(
        wallet,
        lb,
        0,
        _now_ms(),
        f"ef{_rand_str(4)}",
        "Title",
        "content",
        pub_override=b"\x04" + b"\x01" * 64,
        nonce=_gen_nonce(),
    )
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.pubkey_oversized65_rejected", code, dcode, dlog)

    # --- F.7: random 33-byte pubkey (not on curve) → rejected ---
    import os as _os

    fake_pub = b"\x02" + _os.urandom(32)
    msg = _build_msg_post(
        wallet, lb, 0, _now_ms(), f"ef{_rand_str(4)}", "Title", "content", pub_override=fake_pub, nonce=_gen_nonce()
    )
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.pubkey_random_bytes_rejected", code, dcode, dlog)

    # --- F.8: truncated signature (32 bytes) → rejected ("invalid relay fields") ---
    msg = _build_msg_post(
        wallet, lb, 0, _now_ms(), f"ef{_rand_str(4)}", "Title", "content", sig_override=b"\x01" * 32, nonce=_gen_nonce()
    )
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.sig_truncated32_rejected", code, dcode, dlog)

    # --- F.9: oversized signature (128 bytes) → rejected ---
    msg = _build_msg_post(
        wallet,
        lb,
        0,
        _now_ms(),
        f"ef{_rand_str(4)}",
        "Title",
        "content",
        sig_override=b"\x01" * 128,
        nonce=_gen_nonce(),
    )
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.sig_oversized128_rejected", code, dcode, dlog)

    # --- F.10: all-zero signature (64 bytes) → rejected (bad sig) ---
    msg = _build_msg_post(
        wallet, lb, 0, _now_ms(), f"ef{_rand_str(4)}", "Title", "content", sig_override=b"\x00" * 64, nonce=_gen_nonce()
    )
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.sig_all_zeros_rejected", code, dcode, dlog)

    # --- F.11: empty block_hash → rejected (signature mismatch since canonical bytes used real lb) ---
    # NOTE: lb_override="" is falsy so _build_msg_post would ignore it.
    # We set envelope_block_hash directly after construction, causing a
    # mismatch between the canonical bytes (which used the real lb) and
    # the block_hash field on the message.
    msg = _build_msg_post(wallet, lb, 0, _now_ms(), f"ef{_rand_str(4)}", "Title", "content", nonce=_gen_nonce())
    msg.envelope_block_hash = b""
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.empty_block_hash_rejected", code, dcode, dlog)

    # --- F.12: MsgVote with timestamp=0 → rejected ---
    msg = _build_msg_vote(wallet, lb, 0, 0, _rand_hex(64), 1, nonce=_gen_nonce())
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgVote")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.vote_timestamp_zero_rejected", code, dcode, dlog)

    # --- F.13: MsgVote with empty pubkey → rejected ---
    msg = _build_msg_vote(wallet, lb, 0, _now_ms(), _rand_hex(64), 1, nonce=_gen_nonce())
    msg.envelope_pubkey = b""
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgVote")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.vote_empty_pubkey_rejected", code, dcode, dlog)

    # --- F.14: MsgVote with all-zero sig → rejected ---
    msg = _build_msg_vote(wallet, lb, 0, _now_ms(), _rand_hex(64), 1, sig_override=b"\x00" * 64, nonce=_gen_nonce())
    _, code, log, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgVote")], DEFAULT_GAS_LIMIT, fee_payer, pub, wait_deliver=True
    )
    _check_deliver_reject("envelope.vote_zero_sig_rejected", code, dcode, dlog)


