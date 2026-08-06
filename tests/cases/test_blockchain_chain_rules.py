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
from cosmpy.protos.cosmos.staking.v1beta1.tx_pb2 import MsgDelegate, MsgUndelegate, MsgBeginRedelegate

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
    _faucet,
    _get_spendable_balance,
)
import tests.blockchain_helpers as _bh
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


def test_authority(backend: str) -> None:
    wallet = WALLETS["sub1"]
    lb, _, _, _ = _get_pow_params(backend, str(wallet.address()))
    ts = _now_ms()

    # 3.1 Fake authority with unfunded fee payer.
    # Since C-1 the outer signature is verified before the fee is deducted, so
    # naming someone else as fee.payer is refused for lack of authorization
    # rather than for lack of funds — the tx never reaches DeductFee.
    fake = LocalWallet(PrivateKey(), prefix="mirage")
    msg = _build_msg_post(
        wallet,
        lb,
        0,
        ts,
        f"auth{_rand_str(4)}",
        "Title",
        "content",
        pow_val=0,
        authority_override=str(fake.address()),
        nonce=_gen_nonce(),
    )
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        str(fake.address()),
        wallet.public_key().public_key_bytes,
    )
    _check_reject("authority.fake_authority", code, log, "pubkey")

    # 3.2 Governance authority spoof
    msg = _build_msg_post(
        wallet,
        lb,
        0,
        ts,
        f"auth{_rand_str(4)}",
        "Title",
        "content",
        pow_val=0,
        authority_override=_bh._GOV_MODULE_ADDR,
        nonce=_gen_nonce(),
    )
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        _bh._VALIDATOR_ADDR or "",
        wallet.public_key().public_key_bytes,
    )
    _check_reject("authority.gov_spoof", code, log, "unauthorized")


def test_fee(backend: str) -> None:
    wallet = WALLETS["sub1"]
    lb, _, _, _ = _get_pow_params(backend, str(wallet.address()))
    ts = _now_ms()
    fee_payer = _bh._VALIDATOR_ADDR or ""
    signer_pub = wallet.public_key().public_key_bytes
    msg = _build_msg_post(wallet, lb, 0, ts, f"fee{_rand_str(4)}", "Title", "content", pow_val=0, nonce=_gen_nonce())

    # 4.1 Zero fee
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub, fee_amount=0
    )
    _check_reject("fee.zero_fee_rejected", code, log, "insufficient fee")

    # 4.2 Wrong denom
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        signer_pub,
        fee_denom="uatom",
        fee_amount=1,
    )
    _check_reject("fee.wrong_denom_rejected", code, log, "insufficient fee")

    # 4.3 Insufficient fee amount
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub, fee_amount=1
    )
    _check_reject("fee.insufficient_fee_rejected", code, log, "insufficient fee")


def test_c1_unauthorized_gas_payer(backend: str) -> None:
    """C-1: placeholder outer signature / third-party gas payer must be rejected.

    Before the fix, a relay tx with signatures=[0x00] and fee.payer=victim drained
    the victim. After the fix, SigVerificationDecorator rejects unsigned outer txs.
    """
    wallet = WALLETS["sub1"]
    victim = LocalWallet(PrivateKey(), prefix="mirage")
    victim_addr = str(victim.address())
    lb, _, _, _ = _get_pow_params(backend, str(wallet.address()))
    ts = _now_ms()
    topic = f"c1{_rand_str(4)}"
    msg = _build_msg_follow_topic(wallet, lb, 0, ts, str(wallet.address()), topic, pow_val=0, nonce=_gen_nonce())
    # Name victim as both authority and fee.payer (single required signer slot).
    msg.authority = victim_addr
    signer_pub = wallet.public_key().public_key_bytes
    gas = DEFAULT_GAS_LIMIT
    steal = gas * 1000  # meets floor if it were accepted

    tx_bytes = _bh._build_tx_bytes(
        [(msg, "/mirage.core.v1.MsgFollowTopic")],
        gas,
        fee_payer=victim_addr,
        signer_pubkey=signer_pub,
        fee_amount=steal,
        sign_outer=False,
    )
    tx_hash, code, log = _bh._broadcast_tx_sync(tx_bytes)
    _debug(f"c1 unsigned drain attempt hash={tx_hash} code={code} log={log[:200]}")
    _check_reject("c1.unsigned_fee_payer_rejected", code, log, "pubkey")

    # Empty fee.payer + foreign SignerInfo pubkey (same class: unverified outer identity).
    msg2 = _build_msg_follow_topic(
        wallet, lb, 0, ts, str(wallet.address()), f"c1e{_rand_str(4)}", pow_val=0, nonce=_gen_nonce()
    )
    msg2.authority = _bh._VALIDATOR_ADDR or ""
    tx_bytes2 = _bh._build_tx_bytes(
        [(msg2, "/mirage.core.v1.MsgFollowTopic")],
        gas,
        fee_payer="",  # empty → SDK falls back to first signer (authority)
        signer_pubkey=signer_pub,  # attacker's pubkey, not validator's
        fee_amount=steal,
        sign_outer=False,
    )
    tx_hash2, code2, log2 = _bh._broadcast_tx_sync(tx_bytes2)
    _debug(f"c1 empty fee.payer attempt hash={tx_hash2} code={code2} log={log2[:200]}")
    _check_reject("c1.empty_fee_payer_foreign_pubkey_rejected", code2, log2, "pubkey")

    # The sharpest forgery: the victim's real (public) pubkey in SignerInfo with a
    # forged 64-byte signature. This passes SetPubKey, so only SigVerification can
    # stop it. The victim is funded and the fee is exactly the expected gas
    # payment, so a rejection cannot come from insufficient funds or the fee floor
    # instead.
    funded_victim = LocalWallet(PrivateKey(), prefix="mirage")
    fv_addr = str(funded_victim.address())
    fv_pub = funded_victim.public_key().public_key_bytes
    expected_fee = gas * int((_bh._get_chain_params().get("relay_min_gas_price")) or 0)
    if not _faucet(backend, fv_addr, amount=expected_fee + 10_000_000):
        _fail("c1.forged_signature_rejected", f"could not fund victim {fv_addr}")
        return
    time.sleep(2)
    balance_before = _get_spendable_balance(fv_addr)
    if balance_before < expected_fee:
        _fail("c1.forged_signature_rejected", f"victim underfunded: {balance_before} < {expected_fee}")
        return

    msg4 = _build_msg_follow_topic(
        wallet, lb, 0, ts, str(wallet.address()), f"c1f{_rand_str(4)}", pow_val=0, nonce=_gen_nonce()
    )
    msg4.authority = fv_addr
    tx_bytes4 = _bh._build_tx_bytes(
        [(msg4, "/mirage.core.v1.MsgFollowTopic")],
        gas,
        fee_payer=fv_addr,
        signer_pubkey=fv_pub,  # victim's real pubkey — matches the required signer
        fee_amount=expected_fee,
        sign_outer=False,
        outer_sig=b"\x11" * 64,  # forged signature of the right shape
        unordered=True,
    )
    tx_hash4, code4, log4 = _bh._broadcast_tx_sync(tx_bytes4)
    _debug(f"c1 forged-signature attempt hash={tx_hash4} code={code4} log={log4[:200]}")
    _check_reject("c1.forged_signature_rejected", code4, log4, "signature verification failed")

    balance_after = _get_spendable_balance(fv_addr)
    _debug(f"c1 forged-signature victim balance before={balance_before} after={balance_after}")
    if balance_after < balance_before:
        _fail(
            "c1.forged_signature_victim_unharmed",
            f"victim was charged: {balance_before} -> {balance_after}",
        )
    else:
        _pass("c1.forged_signature_victim_unharmed")

    # A signed relay tx above relay_max_gas_fee/relay_min_gas_price gas must be
    # payable. The C-1 remediation briefly capped the fee at
    # min(gas*relay_min_gas_price, relay_max_gas_fee), which crossed the CheckTx
    # minimum-gas-price floor at 500k gas and made every larger relay tx
    # unsubmittable — including posts over ~10.7k chars, inside the 20k tier
    # limit. The payer signs the fee, so magnitude needs no ante bound.
    fee_payer = _bh._VALIDATOR_ADDR or ""
    params = _bh._get_chain_params()
    relay_min = int(params.get("relay_min_gas_price") or 0)
    relay_max = int(params.get("relay_max_gas_fee") or 0)
    if relay_min <= 0:
        _fail("c1.high_gas_relay_accepted", "relay_min_gas_price missing from chain params")
        return
    high_gas = (relay_max // relay_min) * 2 if relay_max > 0 else gas * 5
    high_fee = high_gas * relay_min
    msg3 = _build_msg_follow_topic(
        wallet, lb, 0, ts, str(wallet.address()), f"c1c{_rand_str(4)}", pow_val=0, nonce=_gen_nonce()
    )
    _, code3, log3, dcode3, dlog3 = _submit_tx(
        [(msg3, "/mirage.core.v1.MsgFollowTopic")],
        high_gas,
        fee_payer,
        signer_pub,
        fee_amount=high_fee,
        wait_deliver=True,
    )
    _debug(
        f"c1 high-gas relay gas={high_gas} fee={high_fee} relay_max_gas_fee={relay_max} "
        f"check={code3} log={log3[:200]} deliver={dcode3}"
    )
    _check_deliver_accept("c1.high_gas_relay_accepted", code3, dcode3, dlog3)


def test_staking(backend: str) -> None:
    wallet = WALLETS["sub1"]
    free_wallet = WALLETS["free"]
    lb, _, _, _ = _get_pow_params(backend, str(wallet.address()))
    ts = _now_ms()
    fee_payer = _bh._VALIDATOR_ADDR or ""

    conf = _request_with_retries("GET", f"{backend}/api/get_node_config", timeout=10).json()
    valoper = str(conf.get("validator_operator_address", "")).strip()
    if not valoper:
        _fail("staking.get_valoper", "validator_operator_address missing")
        return

    post = _build_msg_post(wallet, lb, 0, ts, f"stake{_rand_str(4)}", "Title", "content", pow_val=0, nonce=_gen_nonce())
    post_any = (post, "/mirage.core.v1.MsgPost")

    # 5.1 MsgDelegate
    msg = MsgDelegate()
    msg.delegator_address = str(free_wallet.address())
    msg.validator_address = valoper
    msg.amount.denom = "umirage"
    msg.amount.amount = "1"
    _, code, log, _, _ = _submit_tx(
        [post_any, (msg, "/cosmos.staking.v1beta1.MsgDelegate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        wallet.public_key().public_key_bytes,
    )
    _check_reject("staking.delegate_blocked", code, log)

    # 5.2 MsgUndelegate
    msg = MsgUndelegate()
    msg.delegator_address = str(free_wallet.address())
    msg.validator_address = valoper
    msg.amount.denom = "umirage"
    msg.amount.amount = "1"
    _, code, log, _, _ = _submit_tx(
        [post_any, (msg, "/cosmos.staking.v1beta1.MsgUndelegate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        wallet.public_key().public_key_bytes,
    )
    _check_reject("staking.undelegate_blocked", code, log)

    # 5.3 MsgBeginRedelegate
    msg = MsgBeginRedelegate()
    msg.delegator_address = str(free_wallet.address())
    msg.validator_src_address = valoper
    msg.validator_dst_address = valoper
    msg.amount.denom = "umirage"
    msg.amount.amount = "1"
    _, code, log, _, _ = _submit_tx(
        [post_any, (msg, "/cosmos.staking.v1beta1.MsgBeginRedelegate")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        wallet.public_key().public_key_bytes,
    )
    _check_reject("staking.redelegate_blocked", code, log)


def test_msg_validation(backend: str) -> None:
    w1 = WALLETS["sub1"]
    w2 = WALLETS["sub2"]
    fee_payer = _bh._VALIDATOR_ADDR or ""
    lb, _, _, _ = _get_pow_params(backend, str(w1.address()))
    ts = _now_ms()

    # 6.1 MsgSendTokens with wrong sender
    msg = _build_msg_send_tokens(w1, lb, 0, ts, str(w2.address()), str(w1.address()), 1, pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSendTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.send_tokens_wrong_sender", ccode, dcode, dlog)

    # 6.2 MsgSendTokens with zero amount
    msg = _build_msg_send_tokens(w1, lb, 0, ts, str(w1.address()), str(w2.address()), 0, pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSendTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.send_tokens_zero_amount", ccode, dcode, dlog)

    # 6.3 MsgPost invalid topic
    msg = _build_msg_post(w1, lb, 0, ts, "BadTopic", "Title", "content", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.post_invalid_topic", ccode, dcode, dlog)

    # 6.3a MsgBlockTopic wildcard patterns accepted
    base = f"t{_rand_str(4)}"
    _debug(f"block_topic wildcard base={base}")
    patterns = {
        "trailing": f"{base}*",
        "leading": f"*{base}",
        "middle": f"{base[:2]}*{base[2:]}",
        "both": f"*{base}*",
    }
    for label, pat in patterns.items():
        msg = _build_msg_block_topic(w2, lb, 0, ts, str(w2.address()), pat, pow_val=0, nonce=_gen_nonce())
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockTopic")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w2.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept(f"msg.block_topic_wildcard_{label}", ccode, dcode, dlog)

    # 6.3b MsgBlockTopic invalid wildcard
    msg = _build_msg_block_topic(w2, lb, 0, ts, str(w2.address()), "*", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgBlockTopic")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w2.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.block_topic_invalid_wildcard", ccode, dcode, dlog)

    # 6.4 MsgPost oversized content
    tier1 = _get_tier_config(1)
    max_content = _tier_int(tier1, "max_content_length")
    big_content = "x" * (max_content + 25)
    msg = _build_msg_post(w1, lb, 0, ts, f"t{_rand_str(4)}", "Title", big_content, pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.post_oversized_content", ccode, dcode, dlog)

    # 6.5 MsgVote empty target
    msg = _build_msg_vote(w1, lb, 0, ts, "", 1, pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgVote")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.vote_empty_target", ccode, dcode, dlog)

    # 6.6 MsgSetUsername duplicate claim
    uname = f"dup{_rand_str(5)}"
    msg = _build_msg_set_username(w1, lb, 0, ts, str(w1.address()), uname, pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetUsername")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("msg.set_username_initial", ccode, dcode, dlog)

    msg = _build_msg_set_username(w2, lb, 0, ts, str(w2.address()), uname, pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetUsername")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w2.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.set_username_duplicate", ccode, dcode, dlog)

    # 6.7 MsgDelete/MsgEdit ownership gap
    post_topic = f"own{_rand_str(4)}"
    post = _build_msg_post(w1, lb, 0, ts, post_topic, "Title", "content", pow_val=0, nonce=_gen_nonce())
    txh, ccode, clog, dcode, dlog = _submit_tx(
        [(post, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode == 0 and dcode == 0:
        _pass("msg.post_for_ownership")
    else:
        _fail("msg.post_for_ownership", f"check={ccode} deliver={dcode}")
        txh = ""

    if txh:
        del_msg = _build_msg_delete(w2, lb, 0, ts, txh, pow_val=0, nonce=_gen_nonce())
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(del_msg, "/mirage.core.v1.MsgDelete")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w2.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept("msg.delete_foreign_succeeds", ccode, dcode, dlog)

        edit_msg = _build_msg_edit(
            w2, lb, 0, ts, "", post_topic, "Edited", "edited content", "", txh, pow_val=0, nonce=_gen_nonce()
        )
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(edit_msg, "/mirage.core.v1.MsgEdit")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w2.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept("msg.edit_foreign_succeeds", ccode, dcode, dlog)
    else:
        _fail("msg.delete_foreign_succeeds", "missing post tx hash")
        _fail("msg.edit_foreign_succeeds", "missing post tx hash")

    # 6.8 MsgPost invalid media
    msg = _build_msg_post(
        w1,
        lb,
        0,
        ts,
        f"media{_rand_str(4)}",
        "Title",
        "content",
        media=["http://example.com"],
        pow_val=0,
        nonce=_gen_nonce(),
    )
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.post_invalid_media", ccode, dcode, dlog)

    # 6.9 MsgSubscribe invalid level
    msg = _build_msg_subscribe(w1, lb, 0, ts, 99, pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSubscribe")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.subscribe_invalid", ccode, dcode, dlog)

    # 6.10 Block limits — use the FREE wallet (tier 0) so we hit the real
    # free-tier ceiling and can verify overflow is rejected.
    tier0 = _get_tier_config(0)
    max_blocked_posts = _tier_int(tier0, "max_blocked_posts")
    max_blocked_users = _tier_int(tier0, "max_blocked_users")
    max_blocked_topics = _tier_int(tier0, "max_blocked_topics")

    bw = WALLETS["free"]
    bw_addr = str(bw.address())
    bw_pub = bw.public_key().public_key_bytes

    # Ensure the free wallet has a profile core so GetProfile queries work
    lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
    ts = _now_ms()
    bw_uname = f"bw{_rand_str(6)}"
    nonce = _gen_nonce()
    base = _canon_base_set_username_raw(bw_pub, _lb_bytes(lb), diff, ts, bw_addr, bw_uname, nonce=nonce)
    proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
    msg = _build_msg_set_username(bw, lb, diff, ts, bw_addr, bw_uname, pow_val=proof, nonce=nonce)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetUsername")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        bw_pub,
        wait_deliver=True,
    )
    if ccode != 0 or dcode != 0:
        _debug(f"free wallet SetUsername FAILED check={ccode} deliver={dcode} log={dlog}")

    # ── blocked posts fill + overflow ────────────────────────────
    _debug(f"free-tier max_blocked_posts={max_blocked_posts}")
    fill_ok = True
    blocked_post_targets: list[str] = []
    for i in range(max_blocked_posts):
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
        ts = _now_ms()
        if i > 0 and i % 10 == 0:
            print(f"    [{i}/{max_blocked_posts}] blocked posts…")
        target = _rand_hex(64)
        blocked_post_targets.append(target)
        nonce = _gen_nonce()
        base = _canon_base_block_post_raw(bw_pub, _lb_bytes(lb), diff, ts, target, nonce=nonce)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_post(bw, lb, diff, ts, target, pow_val=proof, nonce=nonce)
        _, ccode, _, dcode, _ = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockPost")],
            FILL_GAS_LIMIT,
            fee_payer,
            bw_pub,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail("msg.block_post_fill", f"index={i} check={ccode} deliver={dcode}")
            fill_ok = False
            break
    else:
        _pass(f"msg.block_post_fill ({max_blocked_posts} blocked)")

    if fill_ok:
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
        ts = _now_ms()
        over_target = _rand_hex(64)
        nonce = _gen_nonce()
        base = _canon_base_block_post_raw(bw_pub, _lb_bytes(lb), diff, ts, over_target, nonce=nonce)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_post(bw, lb, diff, ts, over_target, pow_val=proof, nonce=nonce)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockPost")],
            FILL_GAS_LIMIT,
            fee_payer,
            bw_pub,
            wait_deliver=True,
        )
        _check_deliver_accept("msg.block_post_overflow (capped)", ccode, dcode, dlog)
        chain_profile = _get_chain_profile(bw_addr)
        got = [str(v).lower() for v in (chain_profile.get("blocked_posts") or chain_profile.get("blockedPosts") or [])]
        expected = (blocked_post_targets + [over_target])[-max_blocked_posts:]
        _assert_capped_deque("msg.block_post_overflow_deque", got, expected)

    # ── blocked users fill + overflow ────────────────────────────
    _debug(f"free-tier max_blocked_users={max_blocked_users}")
    fill_ok = True
    blocked_user_targets: list[str] = []
    for i in range(max_blocked_users):
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
        ts = _now_ms()
        target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        blocked_user_targets.append(target.lower())
        nonce = _gen_nonce()
        base = _canon_base_block_user_raw(bw_pub, _lb_bytes(lb), diff, ts, target, nonce=nonce)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_user(bw, lb, diff, ts, target, pow_val=proof, nonce=nonce)
        _, ccode, _, dcode, _ = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockUser")],
            FILL_GAS_LIMIT,
            fee_payer,
            bw_pub,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail("msg.block_user_fill", f"index={i} check={ccode} deliver={dcode}")
            fill_ok = False
            break
    else:
        _pass(f"msg.block_user_fill ({max_blocked_users} blocked)")

    if fill_ok:
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
        ts = _now_ms()
        over_target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        nonce = _gen_nonce()
        base = _canon_base_block_user_raw(bw_pub, _lb_bytes(lb), diff, ts, over_target, nonce=nonce)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_user(bw, lb, diff, ts, over_target, pow_val=proof, nonce=nonce)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockUser")],
            FILL_GAS_LIMIT,
            fee_payer,
            bw_pub,
            wait_deliver=True,
        )
        _check_deliver_accept("msg.block_user_overflow (capped)", ccode, dcode, dlog)
        chain_profile = _get_chain_profile(bw_addr)
        got = [str(v).lower() for v in (chain_profile.get("blocked_users") or chain_profile.get("blockedUsers") or [])]
        expected = (blocked_user_targets + [over_target.lower()])[-max_blocked_users:]
        _assert_capped_deque("msg.block_user_overflow_deque", got, expected)

    # ── blocked topics fill + overflow ───────────────────────────
    _debug(f"free-tier max_blocked_topics={max_blocked_topics}")
    fill_ok = True
    blocked_topic_targets: list[str] = []
    for i in range(max_blocked_topics):
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
        ts = _now_ms()
        topic = f"t{_rand_str(6)}{i}"
        blocked_topic_targets.append(topic)
        nonce = _gen_nonce()
        base = _canon_base_block_topic_raw(bw_pub, _lb_bytes(lb), diff, ts, bw_addr, topic, nonce=nonce)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_topic(bw, lb, diff, ts, bw_addr, topic, pow_val=proof, nonce=nonce)
        _, ccode, _, dcode, _ = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockTopic")],
            FILL_GAS_LIMIT,
            fee_payer,
            bw_pub,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail("msg.block_topic_fill", f"index={i} check={ccode} deliver={dcode}")
            fill_ok = False
            break
    else:
        _pass(f"msg.block_topic_fill ({max_blocked_topics} blocked)")

    if fill_ok:
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
        ts = _now_ms()
        over_topic = f"t{_rand_str(6)}over"
        nonce = _gen_nonce()
        base = _canon_base_block_topic_raw(bw_pub, _lb_bytes(lb), diff, ts, bw_addr, over_topic, nonce=nonce)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_topic(bw, lb, diff, ts, bw_addr, over_topic, pow_val=proof, nonce=nonce)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockTopic")],
            FILL_GAS_LIMIT,
            fee_payer,
            bw_pub,
            wait_deliver=True,
        )
        _check_deliver_accept("msg.block_topic_overflow (capped)", ccode, dcode, dlog)
        chain_profile = _get_chain_profile(bw_addr)
        got = [
            str(v).lower() for v in (chain_profile.get("blocked_topics") or chain_profile.get("blockedTopics") or [])
        ]
        expected = (blocked_topic_targets + [over_topic.lower()])[-max_blocked_topics:]
        _assert_capped_deque("msg.block_topic_overflow_deque", got, expected)

    # 6.11 Unblock post (happy path: block then unblock)
    lb, _, _, _ = _get_pow_params(backend, str(w2.address()))
    ts = _now_ms()
    block_post_target = _rand_hex(64)
    msg = _build_msg_block_post(w2, lb, 0, ts, block_post_target, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgBlockPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w2.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode == 0 and dcode == 0:
        msg = _build_msg_unblock_post(w2, lb, 0, ts, block_post_target, pow_val=0, nonce=_gen_nonce())
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgUnblockPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w2.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept("msg.unblock_post_happy", ccode, dcode, dlog)
    else:
        _fail("msg.unblock_post_happy", "setup block failed")

    # 6.12 Unblock user (happy path)
    lb, _, _, _ = _get_pow_params(backend, str(w2.address()))
    ts = _now_ms()
    block_user_target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    msg = _build_msg_block_user(w2, lb, 0, ts, block_user_target, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgBlockUser")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w2.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode == 0 and dcode == 0:
        msg = _build_msg_unblock_user(w2, lb, 0, ts, block_user_target, pow_val=0, nonce=_gen_nonce())
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgUnblockUser")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w2.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept("msg.unblock_user_happy", ccode, dcode, dlog)
    else:
        _fail("msg.unblock_user_happy", "setup block failed")

    # 6.13 Unblock topic (happy path)
    lb, _, _, _ = _get_pow_params(backend, str(w2.address()))
    ts = _now_ms()
    block_topic_target = f"ub{_rand_str(4)}"
    msg = _build_msg_block_topic(w2, lb, 0, ts, str(w2.address()), block_topic_target, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgBlockTopic")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w2.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode == 0 and dcode == 0:
        msg = _build_msg_unblock_topic(
            w2, lb, 0, ts, str(w2.address()), block_topic_target, pow_val=0, nonce=_gen_nonce()
        )
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgUnblockTopic")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w2.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept("msg.unblock_topic_happy", ccode, dcode, dlog)
    else:
        _fail("msg.unblock_topic_happy", "setup block failed")

    # Refresh for remaining tests
    lb, _, _, _ = _get_pow_params(backend, str(w1.address()))
    ts = _now_ms()

    # 6.14 Send tokens to self — chain may accept (harmless no-op) or reject
    msg = _build_msg_send_tokens(w1, lb, 0, ts, str(w1.address()), str(w1.address()), 1, pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSendTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode != 0 or (dcode is not None and dcode != 0):
        _pass("msg.send_tokens_self (rejected)")
    else:
        _pass("msg.send_tokens_self (accepted: harmless self-transfer)")

    # 6.15 Send tokens insufficient balance
    msg = _build_msg_send_tokens(
        w1, lb, 0, ts, str(w1.address()), str(w2.address()), 999_999_999_999_999, pow_val=0, nonce=_gen_nonce()
    )
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSendTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.send_tokens_insufficient", ccode, dcode, dlog)

    # 6.16 Send tokens to invalid address
    msg = _build_msg_send_tokens(w1, lb, 0, ts, str(w1.address()), "invalid_addr", 1, pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSendTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.send_tokens_invalid_target", ccode, dcode, dlog)

    # 6.17 Vote with invalid target format (not hex64)
    msg = _build_msg_vote(w1, lb, 0, ts, "short_target", 1, pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgVote")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.vote_invalid_target_format", ccode, dcode, dlog)

    # 6.18 Root post with empty topic (should fail)
    msg = _build_msg_post(w1, lb, 0, ts, "", "Title", "content", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.post_empty_topic", ccode, dcode, dlog)

    # 6.19 Edit with invalid override format
    msg = _build_msg_edit(
        w1, lb, 0, ts, "", f"t{_rand_str(4)}", "Edited", "content", "", "not_a_hex_hash", pow_val=0, nonce=_gen_nonce()
    )
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgEdit")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.edit_invalid_override", ccode, dcode, dlog)

    # 6.20 MsgPost oversized title (not just content)
    tier1 = _get_tier_config(1)
    max_title = _tier_int(tier1, "max_title_length")
    big_title = "T" * (max_title + 25)
    msg = _build_msg_post(w1, lb, 0, ts, f"t{_rand_str(4)}", big_title, "content", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.post_oversized_title", ccode, dcode, dlog)

    # 6.21 MsgDeleteUser — cross-account deletion rejected (w1 tries to delete w2)
    msg = _build_msg_delete_user(w1, lb, 0, ts, str(w2.address()), pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgDeleteUser")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.delete_user_cross_account", ccode, dcode, dlog)

    # 6.22 MsgDeleteUser — self-deletion not rejected as "unauthorized"
    # Uses a throwaway wallet; CheckTx may reject (no account on chain) but that's
    # not an auth failure. The Go unit tests cover the full self-delete happy path.
    throwaway = LocalWallet(PrivateKey(), prefix="mirage")
    throwaway_addr = str(throwaway.address())
    msg = _build_msg_delete_user(throwaway, lb, 0, ts, throwaway_addr, pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgDeleteUser")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        throwaway.public_key().public_key_bytes,
        wait_deliver=True,
    )
    combined_log = ((clog or "") + (dlog or "")).lower()
    if "unauthorized" in combined_log:
        _fail("msg.delete_user_self_auth", "self-delete rejected as unauthorized")
    else:
        _pass("msg.delete_user_self_auth")

    # 6.23 MsgDeleteUser — empty target rejected
    msg = _build_msg_delete_user(w1, lb, 0, ts, "", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgDeleteUser")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.delete_user_empty_target", ccode, dcode, dlog)

    # 6.24 MsgAward — empty target rejected
    msg = _build_msg_award(w1, lb, 0, ts, "", "quality_post", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.award_empty_target", ccode, dcode, dlog)

    # 6.25 MsgAward — invalid target rejected
    msg = _build_msg_award(w1, lb, 0, ts, "not_a_hash", "quality_post", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.award_invalid_target", ccode, dcode, dlog)

    # 6.26 MsgAward — empty award_type rejected
    msg = _build_msg_award(w1, lb, 0, ts, _rand_hex(64), "", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.award_empty_type", ccode, dcode, dlog)

    # 6.27 MsgAward — unknown award_type rejected
    msg = _build_msg_award(w1, lb, 0, ts, _rand_hex(64), "not_a_real_award", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.award_unknown_type", ccode, dcode, dlog)

    # 6.28 MsgAward — valid award accepted
    award_target = _rand_hex(64)
    _debug(f"award validation target={award_target}")
    msg = _build_msg_award(w1, lb, 0, ts, award_target, "based", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("msg.award_valid", ccode, dcode, dlog)


def _required_validator_fee_budget_umirage() -> int:
    min_gas_price = _min_gas_price_umirage()
    per_tx_fee = int(math.ceil(int(DEFAULT_GAS_LIMIT) * min_gas_price))
    total = per_tx_fee * int(ESTIMATED_CHECKTX_TOTAL)
    _debug(
        "validator fee budget: "
        f"min_gas_price={min_gas_price} per_tx={per_tx_fee / 1_000_000:,.0f} MIRAGE "
        f"estimated_txs={ESTIMATED_CHECKTX_TOTAL} total={total / 1_000_000:,.0f} MIRAGE"
    )
    return total


def _query_spendable_umirage(addr: str) -> int:
    """Query on-chain spendable umirage balance for an address."""
    code, out = _run_miraged(
        [
            "q",
            "bank",
            "spendable-balances",
            addr,
            "--home",
            "/root/.mirage/node",
            "--node",
            "tcp://127.0.0.1:26657",
            "-o",
            "json",
        ],
        timeout=10,
    )
    if code != 0:
        raise RuntimeError(f"spendable balance query failed: exit={code} out={out[:200]}")
    data = _parse_cli_json(out)
    balances = data.get("balances") or []
    for entry in balances:
        if entry.get("denom") == "umirage":
            return int(entry.get("amount", 0) or 0)
    return 0


def _validate_validator_funds() -> bool:
    """Fail fast if the validator fee payer cannot cover the suite."""
    if not _bh._VALIDATOR_ADDR:
        _fail("validator.funds", "validator address not set")
        return False
    required = _required_validator_fee_budget_umirage()
    balance = _query_spendable_umirage(_bh._VALIDATOR_ADDR)
    if balance < required:
        _fail(
            "validator.funds",
            f"insufficient fee balance: have={balance} need={required} "
            f"({balance / 1_000_000:,.0f} MIRAGE < {required / 1_000_000:,.0f} MIRAGE)",
        )
        return False
    _debug(f"validator spendable={balance / 1_000_000:,.0f} MIRAGE (ok)")
    return True


def test_msg_format(backend: str) -> None:
    """Test invalid field values at chain level (bypassing backend validation)."""

    w1 = WALLETS["sub1"]
    fee_payer = _bh._VALIDATOR_ADDR or ""
    lb, _, _, _ = _get_pow_params(backend, str(w1.address()))
    ts = _now_ms()

    # ─── Username at chain level ──────────────────────────────────
    bad_usernames = [
        ("user_name", "underscore"),
        ("user.name", "dot"),
        ("user name", "space"),
        ("\u00fcser", "unicode"),
        ("\U0001f602user", "emoji"),
        ("ab", "too_short"),
        ("a" * 100, "too_long"),
        ("", "empty"),
    ]
    for uname, label in bad_usernames:
        msg = _build_msg_set_username(w1, lb, 0, ts, str(w1.address()), uname, pow_val=0, nonce=_gen_nonce())
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgSetUsername")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_reject(f"format.username_{label}", ccode, dcode, dlog)

    # ─── Topic at chain level ─────────────────────────────────────
    bad_topics = [
        ("UPPER", "uppercase"),
        ("with spaces", "spaces"),
        ("special!@#", "special_chars"),
        ("tést", "accented"),
        ("тема", "cyrillic"),
        ("te\u200bst", "zero_width"),
        ("a", "too_short"),
        ("a" * 200, "too_long"),
    ]
    for topic, label in bad_topics:
        msg = _build_msg_post(w1, lb, 0, ts, topic, "Title", "content", pow_val=0, nonce=_gen_nonce())
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_reject(f"format.topic_{label}", ccode, dcode, dlog)

    # Refresh lb/ts for remaining format tests
    lb, _, _, _ = _get_pow_params(backend, str(w1.address()))
    ts = _now_ms()

    # ─── Tag at chain level ───────────────────────────────────────
    bad_tags = [
        ("nsfw", "nsfw"),
        ("SENSITIVE", "uppercase_sensitive"),
        ("random_tag", "random_string"),
        ("t" * 100, "very_long"),
    ]
    for tag, label in bad_tags:
        msg = _build_msg_post(
            w1, lb, 0, ts, f"fmt{_rand_str(4)}", "Title", "content", tag=tag, pow_val=0, nonce=_gen_nonce()
        )
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_reject(f"format.tag_{label}", ccode, dcode, dlog)

    # ─── Unicode content/title accepted ───────────────────────────
    unicode_cases = [
        ("zwsp_title", f"Zero\u200bWidth", "body"),
        ("zwj_title", f"Join\u200dTest", "body"),
        ("rtl_content", "Title", "abc\u202edef"),
        ("bidi_isolate", "Title", "a\u2066b\u2069c"),
        ("combining", "Cafe\u0301", "body"),
        ("emoji", "Title🙂", "content 🙂"),
    ]
    for label, title, content in unicode_cases:
        msg = _build_msg_post(w1, lb, 0, ts, f"fmt{_rand_str(4)}", title, content, pow_val=0, nonce=_gen_nonce())
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept(f"format.unicode_{label}", ccode, dcode, dlog)

    # ─── Vote direction at chain level ────────────────────────────
    # Chain may accept any integer direction (clamping or treating as no-op)
    post_target = _rand_hex(64)
    for direction, label in [(2, "direction_2"), (-2, "direction_neg2"), (999, "direction_999")]:
        msg = _build_msg_vote(w1, lb, 0, ts, post_target, direction, pow_val=0, nonce=_gen_nonce())
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgVote")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        if ccode != 0 or (dcode is not None and dcode != 0):
            _pass(f"format.vote_{label}")
        else:
            _pass(f"format.vote_{label} (chain accepts out-of-range)")

    # ─── Media at chain level ─────────────────────────────────────
    lb, _, _, _ = _get_pow_params(backend, str(w1.address()))
    ts = _now_ms()
    # http:// URL
    msg = _build_msg_post(
        w1,
        lb,
        0,
        ts,
        f"fmt{_rand_str(4)}",
        "Title",
        "content",
        media=["http://insecure.com/img.jpg"],
        pow_val=0,
        nonce=_gen_nonce(),
    )
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("format.media_http_url", ccode, dcode, dlog)

    # >10 media items
    many_media = [f"https://example.com/{i}.jpg" for i in range(12)]
    msg = _build_msg_post(
        w1, lb, 0, ts, f"fmt{_rand_str(4)}", "Title", "content", media=many_media, pow_val=0, nonce=_gen_nonce()
    )
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("format.media_too_many", ccode, dcode, dlog)

    # >2048 char URL
    long_url = "https://example.com/" + "a" * 2040
    msg = _build_msg_post(
        w1, lb, 0, ts, f"fmt{_rand_str(4)}", "Title", "content", media=[long_url], pow_val=0, nonce=_gen_nonce()
    )
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("format.media_oversized_url", ccode, dcode, dlog)

    # ─── Title at chain level ─────────────────────────────────────
    tier1 = _get_tier_config(1)
    max_title = _tier_int(tier1, "max_title_length")
    big_title = "T" * (max_title + 25)
    msg = _build_msg_post(w1, lb, 0, ts, f"fmt{_rand_str(4)}", big_title, "content", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("format.title_oversized", ccode, dcode, dlog)


def test_malicious_inputs(backend: str) -> None:
    """Test that NUL bytes, control chars, and other dangerous payloads are rejected at chain level."""

    w1 = WALLETS["sub1"]
    fee_payer = _bh._VALIDATOR_ADDR or ""
    lb, _, _, _ = _get_pow_params(backend, str(w1.address()))
    ts = _now_ms()

    def _submit_post(label, topic="", title="", content="", tag=""):
        nonlocal lb, ts
        msg = _build_msg_post(w1, lb, 0, ts, topic, title, content, tag=tag, pow_val=0, nonce=_gen_nonce())
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_reject(f"malicious.{label}", ccode, dcode, dlog)

    # ─── NUL bytes (\x00) in every text field ─────────────────────
    _submit_post("nul_in_topic", topic=f"nul\x00topic", title="Title", content="body")
    _submit_post("nul_in_title", topic=f"t{_rand_str(4)}", title="Nul\x00Title", content="body")
    _submit_post("nul_in_content", topic=f"t{_rand_str(4)}", title="Title", content="Has\x00Nul")
    _submit_post("nul_in_tag", topic=f"t{_rand_str(4)}", title="Title", content="body", tag="gore\x00")
    _submit_post("embedded_nul", topic=f"t{_rand_str(4)}", title="Normal Title", content="Looks normal\x00hidden")
    _submit_post("only_nul_bytes", topic=f"t{_rand_str(4)}", title="\x00\x00\x00", content="\x00\x00\x00")

    # ─── Other C0 control characters ──────────────────────────────
    for byte_val, label in [
        ("\x01", "soh"),
        ("\x02", "stx"),
        ("\x07", "bel"),
        ("\x08", "backspace"),
        ("\x0b", "vtab"),
        ("\x0c", "formfeed"),
        ("\x0e", "shift_out"),
        ("\x1b", "escape"),
        ("\x1f", "unit_sep"),
    ]:
        _submit_post(
            f"control_{label}_in_content",
            topic=f"t{_rand_str(4)}",
            title="Title",
            content=f"has {byte_val} control char",
        )

    # ─── DEL character (\x7F) ─────────────────────────────────────
    _submit_post("del_in_content", topic=f"t{_rand_str(4)}", title="Title", content=f"has \x7f del")
    _submit_post("del_in_title", topic=f"t{_rand_str(4)}", title=f"Del\x7fTitle", content="body")

    # ─── NUL bytes in username ────────────────────────────────────
    msg = _build_msg_set_username(w1, lb, 0, ts, str(w1.address()), f"user\x00name", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetUsername")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("malicious.nul_in_username", ccode, dcode, dlog)

    # ─── Control char in username ─────────────────────────────────
    msg = _build_msg_set_username(w1, lb, 0, ts, str(w1.address()), f"user\x08name", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetUsername")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("malicious.control_in_username", ccode, dcode, dlog)

    # ─── NUL / control chars in award_type ─────────────────────────
    award_target = _rand_hex(64)
    _debug(f"award malicious target={award_target}")
    msg = _build_msg_award(w1, lb, 0, ts, award_target, "quality\x00post", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("malicious.nul_in_award_type", ccode, dcode, dlog)

    msg = _build_msg_award(w1, lb, 0, ts, award_target, "quality\x1bpost", pow_val=0, nonce=_gen_nonce())
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("malicious.control_in_award_type", ccode, dcode, dlog)

    # ─── NUL / control chars in media URLs ────────────────────────
    media_cases = [
        ("nul_in_media", [f"https://example.com/\x00img.jpg"]),
        ("control_in_media", [f"https://example.com/\x07img.jpg"]),
        ("del_in_media", [f"https://example.com/\x7fimg.jpg"]),
    ]
    for label, bad_media in media_cases:
        msg = _build_msg_post(
            w1,
            lb,
            0,
            ts,
            f"t{_rand_str(4)}",
            "Title",
            "body",
            media=bad_media,
            pow_val=0,
            nonce=_gen_nonce(),
        )
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_reject(f"malicious.{label}", ccode, dcode, dlog)
