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
    _keyring_backend,
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


def test_governance_reject(backend: str) -> None:
    """Test that governance-only messages are rejected from non-governance callers."""

    w1 = WALLETS["sub1"]
    w1_addr = str(w1.address())
    fee_payer = _VALIDATOR_ADDR or ""
    lb, _, _, _ = _get_pow_params(backend, w1_addr)
    ts = _now_ms()
    pub = w1.public_key().public_key_bytes

    # 12.1 Regular user submits MsgSetLevel
    msg = MsgSetLevel()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = _lb_bytes(lb)
    msg.envelope_difficulty = 0
    msg.envelope_pow = 0
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = b"\x00" * 64
    msg.target = w1_addr
    msg.level = 10
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetLevel")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    if ccode != 0 or (dcode is not None and dcode != 0):
        _pass("governance.set_level_rejected")
    else:
        _fail("governance.set_level_rejected", f"check={ccode} deliver={dcode}")

    # 12.2 Regular user submits MsgMintTokens
    msg = MsgMintTokens()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.target = w1_addr
    msg.amount = 1_000_000
    msg.reason = "test"
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgMintTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    if ccode != 0 or (dcode is not None and dcode != 0):
        _pass("governance.mint_tokens_rejected")
    else:
        _fail("governance.mint_tokens_rejected", f"check={ccode} deliver={dcode}")

    # 12.3 Regular user submits MsgBurnTokens
    msg = MsgBurnTokens()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.target = w1_addr
    msg.amount = 1_000_000
    msg.reason = "test"
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgBurnTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    if ccode != 0 or (dcode is not None and dcode != 0):
        _pass("governance.burn_tokens_rejected")
    else:
        _fail("governance.burn_tokens_rejected", f"check={ccode} deliver={dcode}")

    # 12.4 Submit MsgSetLevel with gov module authority (but we're not governance)
    msg = MsgSetLevel()
    msg.authority = _GOV_MODULE_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = _lb_bytes(lb)
    msg.envelope_difficulty = 0
    msg.envelope_pow = 0
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = b"\x00" * 64
    msg.target = w1_addr
    msg.level = 10
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetLevel")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    if ccode != 0 or (dcode is not None and dcode != 0):
        _pass("governance.set_level_gov_spoof_rejected")
    else:
        _fail("governance.set_level_gov_spoof_rejected", f"check={ccode} deliver={dcode}")

    # 12.5 MsgMintTokens with gov module authority (spoof)
    msg = MsgMintTokens()
    msg.authority = _GOV_MODULE_ADDR or ""
    msg.target = w1_addr
    msg.amount = 1_000_000
    msg.reason = "spoof"
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgMintTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    if ccode != 0 or (dcode is not None and dcode != 0):
        _pass("governance.mint_tokens_gov_spoof_rejected")
    else:
        _fail("governance.mint_tokens_gov_spoof_rejected", f"check={ccode} deliver={dcode}")

    # 12.6 MsgBurnTokens with gov module authority (spoof)
    msg = MsgBurnTokens()
    msg.authority = _GOV_MODULE_ADDR or ""
    msg.target = w1_addr
    msg.amount = 1_000_000
    msg.reason = "spoof"
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgBurnTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        pub,
        wait_deliver=True,
    )
    if ccode != 0 or (dcode is not None and dcode != 0):
        _pass("governance.burn_tokens_gov_spoof_rejected")
    else:
        _fail("governance.burn_tokens_gov_spoof_rejected", f"check={ccode} deliver={dcode}")



def test_direct_bank(backend: str) -> None:
    kb = _keyring_backend()
    key_name = f"directbank{_rand_str(6)}"
    key_home = tempfile.mkdtemp(prefix="mirage_directbank_")
    _debug(f"direct_bank keyring_home={key_home}")

    try:
        code, out = _run_miraged(
            ["keys", "add", key_name, "--home", key_home, "--keyring-backend", kb, "--output", "json"],
            timeout=10,
        )
        if code != 0 or not out:
            _fail("direct_bank.key_add", f"exit={code} out={out[:200]}")
            return
        try:
            idx = out.find("{")
            if idx < 0:
                raise ValueError("no JSON object in output")
            addr = str(json.loads(out[idx:]).get("address", "")).strip()
        except Exception as e:
            _fail("direct_bank.key_add", f"parse error: {e}")
            return
        if not addr:
            _fail("direct_bank.key_add", "missing address")
            return

        from tests.common import _faucet
        if not _faucet(backend, addr, 5_000_000):
            _fail("direct_bank.faucet", "faucet failed")
            return

        target = str(WALLETS["free"].address())
        code, out = _run_miraged(
            [
                "tx",
                "bank",
                "send",
                addr,
                target,
                "1umirage",
                "--home",
                key_home,
                "--keyring-backend",
                kb,
                "--chain-id",
                "mirage-1",
                "--node",
                "tcp://127.0.0.1:26657",
                "--yes",
                "--gas",
                "auto",
                "--gas-adjustment",
                "1.5",
                "--gas-prices",
                "1000umirage",
                "-o",
                "json",
            ],
            timeout=30,
        )
        if code != 0 or not out:
            _fail("direct_bank.msg_send_blocked", f"exit={code} out={out[:200]}")
            return
        try:
            # miraged may print log lines before the JSON — find the last '{'
            json_start = out.rfind("{")
            if json_start < 0:
                raise ValueError("no JSON object in output")
            resp = json.loads(out[json_start:])
            tx_code = int(resp.get("code", 1))
        except Exception as e:
            _fail("direct_bank.msg_send_blocked", f"parse error: {e}")
            return

        if tx_code == 0:
            _fail("direct_bank.msg_send_blocked", "direct MsgSend succeeded (bypass allowed)")
        else:
            _pass("direct_bank.msg_send_blocked")
    finally:
        if os.path.isdir(key_home):
            shutil.rmtree(key_home)


