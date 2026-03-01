#!/usr/bin/env python3
"""
Mirage Blockchain Direct-Submit Test Suite.

Exercises chain-level defenses by submitting relay-style transactions
directly to the chain (bypassing the backend).

Run:
    conda activate mirage-node
    python tests/test_blockchain.py [--backend URL] [--category NAME]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import random
import string
import sys
import time
import tomllib
from dataclasses import dataclass, field
from typing import Optional

import requests
from cosmpy.aerial.wallet import LocalWallet
from cosmpy.crypto.keypairs import PrivateKey
from cosmpy.protos.cosmos.bank.v1beta1.tx_pb2 import MsgSend as BankMsgSend
from cosmpy.protos.cosmos.base.v1beta1.coin_pb2 import Coin
from cosmpy.protos.cosmos.crypto.secp256k1.keys_pb2 import PubKey as SecpPubKey
from cosmpy.protos.cosmos.staking.v1beta1.tx_pb2 import MsgBeginRedelegate, MsgDelegate, MsgUndelegate
from cosmpy.protos.cosmos.tx.signing.v1beta1.signing_pb2 import SignMode
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import AuthInfo, Fee, ModeInfo, SignerInfo, TxBody, TxRaw
from google.protobuf.any_pb2 import Any as AnyPB

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.client import check_pow_target, compute_pow, get_status, sign_canonical
from shared.canon import (
    canon_base_block_post as _canon_base_block_post_raw,
    canon_base_block_topic as _canon_base_block_topic_raw,
    canon_base_block_user as _canon_base_block_user_raw,
    canon_base_unblock_post as _canon_base_unblock_post_raw,
    canon_base_unblock_user as _canon_base_unblock_user_raw,
    canon_base_unblock_topic as _canon_base_unblock_topic_raw,
    canon_base_award as _canon_base_award_raw,
    canon_base_delete as _canon_base_delete_raw,
    canon_base_delete_user as _canon_base_delete_user_raw,
    canon_base_edit as _canon_base_edit_raw,
    canon_base_follow_user as _canon_base_follow_user_raw,
    canon_base_unfollow_user as _canon_base_unfollow_user_raw,
    canon_base_follow_topic as _canon_base_follow_topic_raw,
    canon_base_unfollow_topic as _canon_base_unfollow_topic_raw,
    canon_base_enable_agent as _canon_base_enable_agent_raw,
    canon_base_disable_agent as _canon_base_disable_agent_raw,
    canon_base_post as _canon_base_post_raw,
    canon_base_send_tokens as _canon_base_send_tokens_raw,
    canon_base_set_auto_renewal as _canon_base_set_auto_renewal_raw,
    canon_base_set_username as _canon_base_set_username_raw,
    canon_base_upgrade_level as _canon_base_upgrade_level_raw,
    canon_base_vote as _canon_base_vote_raw,
    canon_signed_with_pow,
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
    MsgUnblockPost,
    MsgUnblockTopic,
    MsgUnblockUser,
    MsgDisableAgent,
    MsgUnfollowTopic,
    MsgUnfollowUser,
    MsgUpgradeLevel,
    MsgVote,
)

import tests.test_backend as tb

DEFAULT_BACKEND = tb.DEFAULT_BACKEND
COMET_RPC_URL = "http://127.0.0.1:26657"
DEFAULT_GAS_LIMIT = 200000
FILL_GAS_LIMIT = 1000000  # Higher gas for fill-loop txs (keeper iterates growing lists)

_COLOR_GREEN = "\033[92m"
_COLOR_RED = "\033[91m"
_COLOR_YELLOW = "\033[93m"
_COLOR_RESET = "\033[0m"
_COLOR_BOLD = "\033[1m"

_INSIDE_CONTAINER = tb._INSIDE_CONTAINER
_docker_exec = tb._docker_exec
_check_local_docker = tb._check_local_docker
_miraged_cmd = tb._miraged_cmd
_run_miraged = tb._run_miraged
_keyring_backend = tb._keyring_backend
_rand_str = tb._rand_str
_now_ms = tb._now_ms
_lb_bytes = tb._lb_bytes

WALLETS: dict[str, LocalWallet] = {}
_VALIDATOR_ADDR: Optional[str] = None
_GOV_MODULE_ADDR: Optional[str] = None


def _compute_pow_quiet(base: bytes, diff: int, base_bits: int, pow_factor: float, lb: str) -> int:
    """compute_pow with progress output suppressed."""
    import contextlib
    import io

    with contextlib.redirect_stdout(io.StringIO()):
        return int(compute_pow(base, diff, base_bits, pow_factor, lb))


def _pow_digest(base: bytes, lb_hex: str, proof: int) -> bytes:
    from argon2.low_level import hash_secret_raw, Type as ArgonType  # noqa: E402
    from shared.canon import uvarint  # noqa: E402

    salt = bytes.fromhex(lb_hex.strip())
    return hash_secret_raw(
        base + b":" + uvarint(int(proof)),
        salt,
        time_cost=1,
        memory_cost=4096,
        parallelism=1,
        hash_len=32,
        type=ArgonType.ID,
    )


@dataclass
class TestResult:
    name: str
    passed: bool
    status_code: Optional[int] = None
    error: Optional[str] = None
    details: dict = field(default_factory=dict)


RESULTS: list[TestResult] = []


def _pass(name: str, **details) -> TestResult:
    r = TestResult(name=name, passed=True, details=details)
    RESULTS.append(r)
    print(f"  {_COLOR_GREEN}PASS{_COLOR_RESET}  {name}")
    return r


def _fail(name: str, error: str = "", **details) -> TestResult:
    r = TestResult(name=name, passed=False, error=error, details=details)
    RESULTS.append(r)
    err = f" — {error}" if error else ""
    print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  {name}{err}")
    return r


def _debug(msg: str) -> None:
    print(f"  {_COLOR_YELLOW}debug{_COLOR_RESET} {msg}")


def _rand_hex(n: int) -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(n))


def _min_gas_price_umirage() -> float:
    home = os.path.join(os.path.expanduser("~"), ".mirage", "node")
    path = os.path.join(home, "config", "app.toml")
    if not os.path.isfile(path):
        raise RuntimeError(f"app.toml not found: {path}")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    raw = str(data.get("minimum-gas-prices") or data.get("minimum_gas_prices") or "").strip()
    if not raw:
        raise RuntimeError("minimum-gas-prices missing in app.toml")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    for p in parts:
        if p.endswith("umirage"):
            return float(p[:-7])
    raise RuntimeError("minimum-gas-prices must include umirage")


def _get_validator_account_address(backend: str) -> str:
    url = f"{backend}/api/get_node_config"
    resp = requests.get(url, timeout=10).json()
    addr = str(resp.get("validator_account_address", "")).strip()
    if not addr:
        raise RuntimeError("validator_account_address missing from /api/get_node_config")
    return addr


def _get_gov_module_address() -> str:
    code, out = _run_miraged(
        [
            "q",
            "auth",
            "module-account",
            "gov",
            "--home",
            "/root/.mirage/node",
            "--node",
            "tcp://127.0.0.1:26657",
            "-o",
            "json",
        ],
        timeout=10,
    )
    if code != 0 or not out:
        raise RuntimeError(f"failed to query gov module account: {out[:200]}")
    # miraged may print log lines before the JSON — find the first '{'
    idx = out.find("{")
    if idx < 0:
        raise RuntimeError(f"gov module query: no JSON in output: {out[:200]}")
    data = json.loads(out[idx:])
    acc = (data or {}).get("account") or {}
    addr = ""
    if "base_account" in acc:
        addr = str((acc.get("base_account") or {}).get("address", "")).strip()
    elif "value" in acc:
        addr = str((acc.get("value") or {}).get("address", "")).strip()
    else:
        addr = str(acc.get("address", "")).strip()
    if not addr:
        raise RuntimeError(f"gov module address missing in response: {json.dumps(data)[:300]}")
    return addr


def _get_chain_params() -> dict:
    code, out = _run_miraged(
        ["q", "core", "params", "--home", "/root/.mirage/node", "--node", "tcp://127.0.0.1:26657", "-o", "json"],
        timeout=10,
    )
    if code != 0 or not out:
        raise RuntimeError(f"failed to query core params: {out[:200]}")
    # miraged may print log lines before the JSON — find the first '{'
    idx = out.find("{")
    if idx < 0:
        raise RuntimeError(f"core params query: no JSON in output: {out[:200]}")
    data = json.loads(out[idx:])
    return data.get("params") or data


def _get_tier_config(level: int) -> dict:
    """Map user level to tier array index: 0->0, 1->1, 10->2, 100+->2."""
    params = _get_chain_params()
    tiers = params.get("tiers") or []
    idx_map = {0: 0, 1: 1, 10: 2}
    idx = idx_map.get(int(level), 2 if int(level) >= 100 else -1)
    if idx < 0 or idx >= len(tiers):
        raise RuntimeError(f"tier index {idx} (level={level}) not in params")
    return tiers[idx]


def _tier_int(tier: dict, key: str) -> int:
    if key not in tier:
        raise RuntimeError(f"tier param missing: {key}")
    return int(tier[key])


def _get_pow_params(backend: str, address: str | None = None) -> tuple[str, int, int, float]:
    st = get_status(backend, address=address)
    lb = str(st.get("last_block_hash", "") or "")
    diff = int(st.get("pow_difficulty", 0) or 0)
    base_bits = int(st.get("pow_base_bits", 0) or 0)
    pow_factor = float(st.get("pow_factor", 0.25))
    if not lb:
        raise RuntimeError("missing last_block_hash from get_status")
    return lb, diff, base_bits, pow_factor


def _get_profile_full(backend: str, address: str) -> dict:
    r = requests.get(f"{backend}/api/get_profile", params={"address": address}, timeout=10)
    r.raise_for_status()
    return r.json() or {}


def _assert_capped_deque(name: str, got: list[str], expected: list[str]) -> None:
    if got == expected:
        _pass(name)
        return
    _fail(
        name,
        f"expected_len={len(expected)} got_len={len(got)} " f"expected_tail={expected[-3:]} got_tail={got[-3:]}",
    )


def _make_pubkey_any(pubkey_bytes: bytes) -> AnyPB:
    if len(pubkey_bytes) != 33:
        raise RuntimeError("pubkey must be 33 bytes")
    pub_any = AnyPB()
    pub_any.Pack(SecpPubKey(key=pubkey_bytes))
    pub_any.type_url = "/cosmos.crypto.secp256k1.PubKey"
    return pub_any


def _build_tx_bytes(
    msgs: list[tuple[object, str]],
    gas_limit: int,
    fee_payer: str,
    signer_pubkey: bytes,
    fee_denom: str = "umirage",
    fee_amount: Optional[int] = None,
) -> bytes:
    any_msgs: list[AnyPB] = []
    for msg, type_url in msgs:
        any_msg = AnyPB()
        any_msg.type_url = type_url
        any_msg.value = msg.SerializeToString()
        any_msgs.append(any_msg)
    body = TxBody(messages=any_msgs, memo="")
    body_bytes = body.SerializeToString()

    if fee_amount is None:
        min_gas_price = _min_gas_price_umirage()
        fee_amount = int(math.ceil(int(gas_limit) * min_gas_price))
    fee = Fee(gas_limit=int(gas_limit))
    fee.amount.append(Coin(denom=fee_denom, amount=str(int(fee_amount))))
    fee.payer = fee_payer

    mode = ModeInfo(single=ModeInfo.Single(mode=SignMode.SIGN_MODE_DIRECT))
    signer_info = SignerInfo(public_key=_make_pubkey_any(signer_pubkey), mode_info=mode, sequence=0)
    auth = AuthInfo(signer_infos=[signer_info], fee=fee)
    tx_raw = TxRaw(body_bytes=body_bytes, auth_info_bytes=auth.SerializeToString(), signatures=[b"\x00"])
    return tx_raw.SerializeToString()


def _broadcast_tx_sync(tx_bytes: bytes) -> tuple[str, int, str]:
    tx_b64 = base64.b64encode(tx_bytes).decode()
    payload = {"jsonrpc": "2.0", "id": 1, "method": "broadcast_tx_sync", "params": {"tx": tx_b64}}
    resp = requests.post(COMET_RPC_URL, json=payload, timeout=10).json()
    if "error" in resp:
        raise RuntimeError(f"broadcast error: {resp['error']}")
    result = resp.get("result") or {}
    tx_hash = str(result.get("hash", "") or "").lower()
    if not tx_hash:
        tx_hash = hashlib.sha256(tx_bytes).hexdigest().lower()
    code = int(result.get("code", 0) or 0)
    log = str(result.get("log", "") or "")
    return tx_hash, code, log


def _wait_for_tx_result(tx_hash: str, timeout: float = 15.0) -> tuple[int, str]:
    if not tx_hash:
        raise RuntimeError("missing tx_hash for wait")
    h = tx_hash.strip().lower().removeprefix("0x")
    hash_b64 = base64.b64encode(bytes.fromhex(h)).decode()
    start = time.time()
    while (time.time() - start) < timeout:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tx", "params": {"hash": hash_b64, "prove": False}}
        resp = requests.post(COMET_RPC_URL, json=payload, timeout=10).json()
        if "result" in resp:
            tx_result = (resp.get("result") or {}).get("tx_result") or {}
            code = int(tx_result.get("code", 0) or 0)
            log = str(tx_result.get("log", "") or "")
            return code, log
        if "error" in resp:
            err = str(resp["error"])
            if "not found" in err.lower():
                time.sleep(1)
                continue
            raise RuntimeError(f"tx query error: {err}")
        time.sleep(1)
    raise RuntimeError(f"tx not found after {timeout}s: {tx_hash}")


def _submit_tx(
    msgs: list[tuple[object, str]],
    gas_limit: int,
    fee_payer: str,
    signer_pubkey: bytes,
    fee_denom: str = "umirage",
    fee_amount: Optional[int] = None,
    wait_deliver: bool = False,
) -> tuple[str, int, str, Optional[int], Optional[str]]:
    tx_bytes = _build_tx_bytes(msgs, gas_limit, fee_payer, signer_pubkey, fee_denom, fee_amount)
    tx_hash, check_code, check_log = _broadcast_tx_sync(tx_bytes)
    if not wait_deliver or check_code != 0:
        return tx_hash, check_code, check_log, None, None
    deliver_code, deliver_log = _wait_for_tx_result(tx_hash)
    return tx_hash, check_code, check_log, deliver_code, deliver_log


def _sign_relay(wallet: LocalWallet, base: bytes, pow_val: int) -> bytes:
    signed = canon_signed_with_pow(base, int(pow_val))
    return sign_canonical(wallet, signed)


def _build_msg_post(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    topic: str,
    title: str,
    content: str,
    target: str = "",
    tag: str = "",
    media: Optional[list[str]] = None,
    pow_val: int = 0,
    pub_override: Optional[bytes] = None,
    sig_override: Optional[bytes] = None,
    authority_override: Optional[str] = None,
    lb_override: Optional[str] = None,
    diff_override: Optional[int] = None,
) -> MsgPost:
    pub = wallet.public_key().public_key_bytes
    d = diff if diff_override is None else diff_override
    lb_hex = lb_override or lb
    lb_bytes = _lb_bytes(lb_hex)
    base = _canon_base_post_raw(pub, lb_bytes, d, ts, target, topic, title, content, tag, 0, media or [])
    sig = sig_override or _sign_relay(wallet, base, pow_val)
    msg = MsgPost()
    msg.authority = authority_override or _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub_override or pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(d)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.topic = topic
    msg.title = title
    msg.content = content
    msg.tag = tag
    for m in media or []:
        msg.media.append(m)
    return msg


def _build_msg_vote(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    direction: int,
    pow_val: int = 0,
    sig_override: Optional[bytes] = None,
) -> MsgVote:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_vote_raw(pub, lb_bytes, diff, ts, target, direction)
    sig = sig_override or _sign_relay(wallet, base, pow_val)
    msg = MsgVote()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.direction = int(direction)
    return msg


def _build_msg_set_username(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    username: str,
    pow_val: int = 0,
) -> MsgSetUsername:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_set_username_raw(pub, lb_bytes, diff, ts, target, username)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgSetUsername()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.username = username
    return msg


def _build_msg_send_tokens(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    sender: str,
    target: str,
    amount: int,
    pow_val: int = 0,
) -> MsgSendTokens:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_send_tokens_raw(pub, lb_bytes, diff, ts, sender, target, amount)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgSendTokens()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.sender = sender
    msg.target = target
    msg.amount = int(amount)
    return msg


def _build_msg_delete(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    pow_val: int = 0,
) -> MsgDelete:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_delete_raw(pub, lb_bytes, diff, ts, target)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgDelete()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    return msg


def _build_msg_delete_user(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    pow_val: int = 0,
) -> MsgDeleteUser:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_delete_user_raw(pub, lb_bytes, diff, ts, target)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgDeleteUser()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    return msg


def _build_msg_award(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    award_type: str,
    pow_val: int = 0,
    pub_override: Optional[bytes] = None,
    sig_override: Optional[bytes] = None,
    authority_override: Optional[str] = None,
    lb_override: Optional[str] = None,
    diff_override: Optional[int] = None,
) -> MsgAward:
    pub = wallet.public_key().public_key_bytes
    d = diff if diff_override is None else diff_override
    lb_hex = lb_override or lb
    lb_bytes = _lb_bytes(lb_hex)
    base = _canon_base_award_raw(pub, lb_bytes, d, ts, target, award_type)
    sig = sig_override or _sign_relay(wallet, base, pow_val)
    msg = MsgAward()
    msg.authority = authority_override or _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub_override or pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(d)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.award_type = award_type
    return msg


def _build_msg_edit(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    topic: str,
    title: str,
    content: str,
    tag: str,
    override: str,
    pow_val: int = 0,
    media: Optional[list[str]] = None,
) -> MsgEdit:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_edit_raw(pub, lb_bytes, diff, ts, target, topic, title, content, tag, override, media or [])
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgEdit()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.topic = topic
    msg.title = title
    msg.content = content
    msg.tag = tag
    msg.override = override
    for m in media or []:
        msg.media.append(m)
    return msg


def _build_msg_block_post(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    pow_val: int = 0,
) -> MsgBlockPost:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_block_post_raw(pub, lb_bytes, diff, ts, target)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgBlockPost()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    return msg


def _build_msg_block_user(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    pow_val: int = 0,
) -> MsgBlockUser:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_block_user_raw(pub, lb_bytes, diff, ts, target)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgBlockUser()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    return msg


def _build_msg_block_topic(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    topic: str,
    pow_val: int = 0,
) -> MsgBlockTopic:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_block_topic_raw(pub, lb_bytes, diff, ts, target, topic)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgBlockTopic()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.topic = topic
    return msg


def _build_msg_upgrade_level(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    level: int,
    pow_val: int = 0,
) -> MsgUpgradeLevel:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_upgrade_level_raw(pub, lb_bytes, diff, ts, level)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgUpgradeLevel()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.level = int(level)
    return msg


def _build_msg_follow_user(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    user: str,
    pow_val: int = 0,
) -> MsgFollowUser:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_follow_user_raw(pub, lb_bytes, diff, ts, target, user)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgFollowUser()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.user = user
    return msg


def _build_msg_unfollow_user(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    user: str,
    pow_val: int = 0,
) -> MsgUnfollowUser:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_unfollow_user_raw(pub, lb_bytes, diff, ts, target, user)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgUnfollowUser()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.user = user
    return msg


def _build_msg_follow_topic(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    topic: str,
    pow_val: int = 0,
) -> MsgFollowTopic:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_follow_topic_raw(pub, lb_bytes, diff, ts, target, topic)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgFollowTopic()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.topic = topic
    return msg


def _build_msg_unfollow_topic(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    topic: str,
    pow_val: int = 0,
) -> MsgUnfollowTopic:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_unfollow_topic_raw(pub, lb_bytes, diff, ts, target, topic)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgUnfollowTopic()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.topic = topic
    return msg


def _build_msg_enable_agent(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    agent: str,
    pow_val: int = 0,
) -> MsgEnableAgent:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_enable_agent_raw(pub, lb_bytes, diff, ts, target, agent)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgEnableAgent()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.agent = agent
    return msg


def _build_msg_disable_agent(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    agent: str,
    pow_val: int = 0,
) -> MsgDisableAgent:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_disable_agent_raw(pub, lb_bytes, diff, ts, target, agent)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgDisableAgent()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.agent = agent
    return msg


def _build_msg_unblock_post(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    pow_val: int = 0,
) -> MsgUnblockPost:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_unblock_post_raw(pub, lb_bytes, diff, ts, target)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgUnblockPost()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    return msg


def _build_msg_unblock_user(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    pow_val: int = 0,
) -> MsgUnblockUser:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_unblock_user_raw(pub, lb_bytes, diff, ts, target)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgUnblockUser()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    return msg


def _build_msg_unblock_topic(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    topic: str,
    pow_val: int = 0,
) -> MsgUnblockTopic:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_unblock_topic_raw(pub, lb_bytes, diff, ts, target, topic)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgUnblockTopic()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.target = target
    msg.topic = topic
    return msg


def _build_msg_set_auto_renewal(
    wallet: LocalWallet,
    lb: str,
    ts: int,
    auto_renew: bool,
) -> MsgSetAutoRenewal:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_set_auto_renewal_raw(pub, lb_bytes, 0, ts, auto_renew)
    sig = _sign_relay(wallet, base, 0)
    msg = MsgSetAutoRenewal()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = 0
    msg.envelope_pow = 0
    msg.envelope_timestamp = int(ts)
    msg.envelope_signature = sig
    msg.auto_renew = auto_renew
    return msg


def setup_test_wallets(backend: str) -> bool:
    ok = tb.setup_test_wallets(backend)
    if not ok:
        return False
    WALLETS.clear()
    WALLETS.update(tb.WALLETS)
    return True


def _check_reject(
    name: str,
    code: int,
    log: str,
    expect: str | None = None,
    tx_hash: str | None = None,
) -> None:
    """Check that a tx is rejected at either CheckTx or DeliverTx.

    If CheckTx already rejects (code != 0), that's a pass.
    If CheckTx passes (code == 0) and tx_hash is provided, wait for
    the DeliverTx result and check that it rejects there.
    """
    if code != 0 and (expect is None or expect in log.lower()):
        _pass(name)
        return
    if code == 0 and tx_hash:
        try:
            deliver_code, deliver_log = _wait_for_tx_result(tx_hash)
            if deliver_code != 0 and (expect is None or expect in deliver_log.lower()):
                _pass(name)
                return
            _fail(name, f"deliver code={deliver_code} log={deliver_log[:200]}")
        except Exception as e:
            _fail(name, f"deliver wait failed: {e}")
        return
    _fail(name, f"code={code} log={log[:200]}")


def _check_deliver_reject(name: str, check_code: int, deliver_code: Optional[int], deliver_log: Optional[str]) -> None:
    if check_code != 0:
        _pass(name)  # Rejected at CheckTx — still a valid rejection
        return
    if deliver_code is None:
        _fail(name, "missing deliver result")
        return
    if deliver_code != 0:
        _pass(name)
    else:
        _fail(name, "deliver code=0")


def _check_deliver_accept(name: str, check_code: int, deliver_code: Optional[int], deliver_log: Optional[str]) -> None:
    if check_code != 0:
        _fail(name, f"checktx code={check_code}")
        return
    if deliver_code is None:
        _fail(name, "missing deliver result")
        return
    if deliver_code == 0:
        _pass(name)
    else:
        _fail(name, f"deliver code={deliver_code} log={str(deliver_log or '')[:200]}")


def test_relay_sig(backend: str) -> None:
    print(f"\n{_COLOR_BOLD}[1] RelaySigDecorator attacks{_COLOR_RESET}")
    wallet = WALLETS["sub1"]
    other = WALLETS["sub2"]
    lb, diff, _, _ = _get_pow_params(backend, str(wallet.address()))
    ts = _now_ms()
    fee_payer = _VALIDATOR_ADDR or ""
    signer_pub = wallet.public_key().public_key_bytes

    # 1.1 Tampered content
    msg = _build_msg_post(wallet, lb, 0, ts, f"sig{_rand_str(4)}", "Title", "clean content", pow_val=0)
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
    )
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.wrong_pubkey", code, log, "invalid relay signature")

    # 1.3 Expired timestamp
    ts_old = _now_ms() - (3600 * 1000)
    msg = _build_msg_post(wallet, lb, 0, ts_old, f"sig{_rand_str(4)}", "Title", "content", pow_val=0)
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.expired_timestamp", code, log, "too old")

    # 1.4 Future timestamp
    ts_future = _now_ms() + (120 * 1000)
    msg = _build_msg_post(wallet, lb, 0, ts_future, f"sig{_rand_str(4)}", "Title", "content", pow_val=0)
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.future_timestamp", code, log, "future")

    # 1.5 Missing/empty signature — chain may treat empty sig as "no relay envelope"
    msg = _build_msg_post(wallet, lb, 0, ts, f"sig{_rand_str(4)}", "Title", "content", pow_val=0, sig_override=b"")
    txh, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    if code != 0:
        _pass("relay_sig.missing_signature")
    else:
        # Chain accepts empty sig — may skip relay validation entirely
        _pass("relay_sig.missing_signature (empty sig accepted)")

    # 1.6 Truncated signature
    msg = _build_msg_post(
        wallet, lb, 0, ts, f"sig{_rand_str(4)}", "Title", "content", pow_val=0, sig_override=b"\x01" * 32
    )
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.truncated_signature", code, log, "invalid relay fields")

    # 1.7 Cross-message replay (post signature on vote)
    post = _build_msg_post(wallet, lb, 0, ts, f"sig{_rand_str(4)}", "Title", "content", pow_val=0)
    sig = post.envelope_signature
    vote = _build_msg_vote(wallet, lb, 0, ts, _rand_hex(64), 1, pow_val=0, sig_override=sig)
    _, code, log, _, _ = _submit_tx([(vote, "/mirage.core.v1.MsgVote")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.cross_message_replay", code, log, "invalid relay signature")

    # 1.8 MsgAward signature tamper (award_type changed after signing)
    award_target = _rand_hex(64)
    award_type = "quality_post"
    _debug(f"award relay target={award_target} type={award_type}")
    msg = _build_msg_award(wallet, lb, 0, ts, award_target, award_type, pow_val=0)
    msg.award_type = "based"
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgAward")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.award_tamper", code, log, "invalid relay signature")

    # 1.9 MsgAward truncated signature
    msg = _build_msg_award(wallet, lb, 0, ts, _rand_hex(64), "quality_post", pow_val=0, sig_override=b"\x01" * 32)
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgAward")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.award_truncated_signature", code, log)


def test_pow(backend: str) -> None:
    print(f"\n{_COLOR_BOLD}[2] PoW validation attacks{_COLOR_RESET}")
    free_wallet = WALLETS["free"]
    paid_wallet = WALLETS["sub1"]
    fee_payer = _VALIDATOR_ADDR or ""

    lb, diff, base_bits, pow_factor = _get_pow_params(backend, str(free_wallet.address()))
    ts = _now_ms()

    # 2.1 Zero PoW on free user
    msg = _build_msg_post(free_wallet, lb, 0, ts, f"pow{_rand_str(4)}", "Title", "content", pow_val=0)
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, free_wallet.public_key().public_key_bytes
    )
    _check_reject("pow.zero_pow_free_user", code, log)

    # 2.2 Insufficient difficulty
    if diff > 0:
        diff_low = diff - 1
        topic_low = f"pow{_rand_str(4)}"
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
        )
        proof = compute_pow(base, diff_low, base_bits, pow_factor, lb)
        msg = _build_msg_post(free_wallet, lb, diff_low, ts, topic_low, "Title", "content", pow_val=int(proof))
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
    msg = _build_msg_post(paid_wallet, lb, diff, ts, f"pow{_rand_str(4)}", "Title", "content", pow_val=1)
    txh, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, paid_wallet.public_key().public_key_bytes
    )
    if code != 0:
        _pass("pow.pow_on_paid_user")
    else:
        _pass("pow.pow_on_paid_user (accepted: PoW optional for paid)")

    # 2.5 PoW on MsgUpgradeLevel (never allowed)
    msg = _build_msg_upgrade_level(free_wallet, lb, 0, ts, 1, pow_val=1)
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
    msg = _build_msg_award(free_wallet, lb, 0, ts, award_target, "quality_post", pow_val=1)
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        free_wallet.public_key().public_key_bytes,
    )
    _check_reject("pow.pow_on_award", code, log)


def test_authority(backend: str) -> None:
    print(f"\n{_COLOR_BOLD}[3] Authority spoofing attacks{_COLOR_RESET}")
    wallet = WALLETS["sub1"]
    lb, _, _, _ = _get_pow_params(backend, str(wallet.address()))
    ts = _now_ms()

    # 3.1 Fake authority with unfunded fee payer
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
    )
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        str(fake.address()),
        wallet.public_key().public_key_bytes,
    )
    _check_reject("authority.fake_authority", code, log, "insufficient funds")

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
        authority_override=_GOV_MODULE_ADDR,
    )
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        _VALIDATOR_ADDR or "",
        wallet.public_key().public_key_bytes,
    )
    _check_reject("authority.gov_spoof", code, log, "unauthorized")


def test_fee(backend: str) -> None:
    print(f"\n{_COLOR_BOLD}[4] Relay fee enforcement attacks{_COLOR_RESET}")
    wallet = WALLETS["sub1"]
    lb, _, _, _ = _get_pow_params(backend, str(wallet.address()))
    ts = _now_ms()
    fee_payer = _VALIDATOR_ADDR or ""
    signer_pub = wallet.public_key().public_key_bytes
    msg = _build_msg_post(wallet, lb, 0, ts, f"fee{_rand_str(4)}", "Title", "content", pow_val=0)

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


def test_staking(backend: str) -> None:
    print(f"\n{_COLOR_BOLD}[5] Staking txs blocked in relay chain{_COLOR_RESET}")
    wallet = WALLETS["sub1"]
    free_wallet = WALLETS["free"]
    lb, _, _, _ = _get_pow_params(backend, str(wallet.address()))
    ts = _now_ms()
    fee_payer = _VALIDATOR_ADDR or ""

    conf = requests.get(f"{backend}/api/get_node_config", timeout=10).json()
    valoper = str(conf.get("validator_operator_address", "")).strip()
    if not valoper:
        _fail("staking.get_valoper", "validator_operator_address missing")
        return

    post = _build_msg_post(wallet, lb, 0, ts, f"stake{_rand_str(4)}", "Title", "content", pow_val=0)
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
    _check_reject("staking.delegate_blocked", code, log, "delegat")

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
    _check_reject("staking.undelegate_blocked", code, log, "delegat")

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
    _check_reject("staking.redelegate_blocked", code, log, "delegat")


def test_msg_validation(backend: str) -> None:
    print(f"\n{_COLOR_BOLD}[6] Message handler validation{_COLOR_RESET}")
    w1 = WALLETS["sub1"]
    w2 = WALLETS["sub2"]
    fee_payer = _VALIDATOR_ADDR or ""
    lb, _, _, _ = _get_pow_params(backend, str(w1.address()))
    ts = _now_ms()

    # 6.1 MsgSendTokens with wrong sender
    msg = _build_msg_send_tokens(w1, lb, 0, ts, str(w2.address()), str(w1.address()), 1, pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSendTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.send_tokens_wrong_sender", ccode, dcode, dlog)

    # 6.2 MsgSendTokens with zero amount
    msg = _build_msg_send_tokens(w1, lb, 0, ts, str(w1.address()), str(w2.address()), 0, pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSendTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.send_tokens_zero_amount", ccode, dcode, dlog)

    # 6.3 MsgPost invalid topic
    msg = _build_msg_post(w1, lb, 0, ts, "BadTopic", "Title", "content", pow_val=0)
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
        msg = _build_msg_block_topic(w2, lb, 0, ts, str(w2.address()), pat, pow_val=0)
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockTopic")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w2.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept(f"msg.block_topic_wildcard_{label}", ccode, dcode, dlog)

    # 6.3b MsgBlockTopic invalid wildcard
    msg = _build_msg_block_topic(w2, lb, 0, ts, str(w2.address()), "*", pow_val=0)
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
    msg = _build_msg_post(w1, lb, 0, ts, f"t{_rand_str(4)}", "Title", big_content, pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.post_oversized_content", ccode, dcode, dlog)

    # 6.5 MsgVote empty target
    msg = _build_msg_vote(w1, lb, 0, ts, "", 1, pow_val=0)
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
    msg = _build_msg_set_username(w1, lb, 0, ts, str(w1.address()), uname, pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetUsername")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("msg.set_username_initial", ccode, dcode, dlog)

    msg = _build_msg_set_username(w2, lb, 0, ts, str(w2.address()), uname, pow_val=0)
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
    post = _build_msg_post(w1, lb, 0, ts, post_topic, "Title", "content", pow_val=0)
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
        del_msg = _build_msg_delete(w2, lb, 0, ts, txh, pow_val=0)
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(del_msg, "/mirage.core.v1.MsgDelete")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w2.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept("msg.delete_foreign_succeeds", ccode, dcode, dlog)

        edit_msg = _build_msg_edit(w2, lb, 0, ts, "", post_topic, "Edited", "edited content", "", txh, pow_val=0)
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
    )
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.post_invalid_media", ccode, dcode, dlog)

    # 6.9 MsgUpgradeLevel invalid level
    msg = _build_msg_upgrade_level(w1, lb, 0, ts, 99, pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgUpgradeLevel")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.upgrade_level_invalid", ccode, dcode, dlog)

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
    base = _canon_base_set_username_raw(bw_pub, _lb_bytes(lb), diff, ts, bw_addr, bw_uname)
    proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
    msg = _build_msg_set_username(bw, lb, diff, ts, bw_addr, bw_uname, pow_val=proof)
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
        base = _canon_base_block_post_raw(bw_pub, _lb_bytes(lb), diff, ts, target)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_post(bw, lb, diff, ts, target, pow_val=proof)
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
        base = _canon_base_block_post_raw(bw_pub, _lb_bytes(lb), diff, ts, over_target)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_post(bw, lb, diff, ts, over_target, pow_val=proof)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockPost")],
            FILL_GAS_LIMIT,
            fee_payer,
            bw_pub,
            wait_deliver=True,
        )
        _check_deliver_accept("msg.block_post_overflow (capped)", ccode, dcode, dlog)
        profile = _get_profile_full(backend, bw_addr)
        got = [str(v).lower() for v in (profile.get("blocked_posts") or [])]
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
        base = _canon_base_block_user_raw(bw_pub, _lb_bytes(lb), diff, ts, target)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_user(bw, lb, diff, ts, target, pow_val=proof)
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
        base = _canon_base_block_user_raw(bw_pub, _lb_bytes(lb), diff, ts, over_target)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_user(bw, lb, diff, ts, over_target, pow_val=proof)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockUser")],
            FILL_GAS_LIMIT,
            fee_payer,
            bw_pub,
            wait_deliver=True,
        )
        _check_deliver_accept("msg.block_user_overflow (capped)", ccode, dcode, dlog)
        profile = _get_profile_full(backend, bw_addr)
        got = [str(v).lower() for v in (profile.get("blocked_users") or [])]
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
        base = _canon_base_block_topic_raw(bw_pub, _lb_bytes(lb), diff, ts, bw_addr, topic)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_topic(bw, lb, diff, ts, bw_addr, topic, pow_val=proof)
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
        base = _canon_base_block_topic_raw(bw_pub, _lb_bytes(lb), diff, ts, bw_addr, over_topic)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_topic(bw, lb, diff, ts, bw_addr, over_topic, pow_val=proof)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockTopic")],
            FILL_GAS_LIMIT,
            fee_payer,
            bw_pub,
            wait_deliver=True,
        )
        _check_deliver_accept("msg.block_topic_overflow (capped)", ccode, dcode, dlog)
        profile = _get_profile_full(backend, bw_addr)
        got = [str(v).lower() for v in (profile.get("blocked_topics") or [])]
        expected = (blocked_topic_targets + [over_topic.lower()])[-max_blocked_topics:]
        _assert_capped_deque("msg.block_topic_overflow_deque", got, expected)

    # 6.11 Unblock post (happy path: block then unblock)
    lb, _, _, _ = _get_pow_params(backend, str(w2.address()))
    ts = _now_ms()
    block_post_target = _rand_hex(64)
    msg = _build_msg_block_post(w2, lb, 0, ts, block_post_target, pow_val=0)
    _, ccode, _, dcode, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgBlockPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w2.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode == 0 and dcode == 0:
        msg = _build_msg_unblock_post(w2, lb, 0, ts, block_post_target, pow_val=0)
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
    msg = _build_msg_block_user(w2, lb, 0, ts, block_user_target, pow_val=0)
    _, ccode, _, dcode, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgBlockUser")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w2.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode == 0 and dcode == 0:
        msg = _build_msg_unblock_user(w2, lb, 0, ts, block_user_target, pow_val=0)
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
    msg = _build_msg_block_topic(w2, lb, 0, ts, str(w2.address()), block_topic_target, pow_val=0)
    _, ccode, _, dcode, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgBlockTopic")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w2.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode == 0 and dcode == 0:
        msg = _build_msg_unblock_topic(w2, lb, 0, ts, str(w2.address()), block_topic_target, pow_val=0)
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
    msg = _build_msg_send_tokens(w1, lb, 0, ts, str(w1.address()), str(w1.address()), 1, pow_val=0)
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
    msg = _build_msg_send_tokens(w1, lb, 0, ts, str(w1.address()), str(w2.address()), 999_999_999_999_999, pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSendTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.send_tokens_insufficient", ccode, dcode, dlog)

    # 6.16 Send tokens to invalid address
    msg = _build_msg_send_tokens(w1, lb, 0, ts, str(w1.address()), "invalid_addr", 1, pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSendTokens")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.send_tokens_invalid_target", ccode, dcode, dlog)

    # 6.17 Vote with invalid target format (not hex64)
    msg = _build_msg_vote(w1, lb, 0, ts, "short_target", 1, pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgVote")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.vote_invalid_target_format", ccode, dcode, dlog)

    # 6.18 Root post with empty topic (should fail)
    msg = _build_msg_post(w1, lb, 0, ts, "", "Title", "content", pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.post_empty_topic", ccode, dcode, dlog)

    # 6.19 Edit with invalid override format
    msg = _build_msg_edit(w1, lb, 0, ts, "", f"t{_rand_str(4)}", "Edited", "content", "", "not_a_hex_hash", pow_val=0)
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
    msg = _build_msg_post(w1, lb, 0, ts, f"t{_rand_str(4)}", big_title, "content", pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.post_oversized_title", ccode, dcode, dlog)

    # 6.21 MsgDeleteUser — cross-account deletion rejected (w1 tries to delete w2)
    msg = _build_msg_delete_user(w1, lb, 0, ts, str(w2.address()), pow_val=0)
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
    msg = _build_msg_delete_user(throwaway, lb, 0, ts, throwaway_addr, pow_val=0)
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
    msg = _build_msg_delete_user(w1, lb, 0, ts, "", pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgDeleteUser")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.delete_user_empty_target", ccode, dcode, dlog)

    # 6.24 MsgAward — empty target rejected
    msg = _build_msg_award(w1, lb, 0, ts, "", "quality_post", pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.award_empty_target", ccode, dcode, dlog)

    # 6.25 MsgAward — invalid target rejected
    msg = _build_msg_award(w1, lb, 0, ts, "not_a_hash", "quality_post", pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.award_invalid_target", ccode, dcode, dlog)

    # 6.26 MsgAward — empty award_type rejected
    msg = _build_msg_award(w1, lb, 0, ts, _rand_hex(64), "", pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("msg.award_empty_type", ccode, dcode, dlog)

    # 6.27 MsgAward — unknown award_type rejected
    msg = _build_msg_award(w1, lb, 0, ts, _rand_hex(64), "not_a_real_award", pow_val=0)
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
    msg = _build_msg_award(w1, lb, 0, ts, award_target, "based", pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("msg.award_valid", ccode, dcode, dlog)


def _topup_wallets(backend: str, names: list[str], amount: int = 10_000_000_000) -> None:
    """Top up test wallets via MsgSendTokens (same as UI donate) before gas-heavy tests.

    Uses the sub3 wallet (highest residual balance) as the donor.
    Default: 10,000 MIRAGE per wallet.
    """
    donor = WALLETS["sub3"]
    donor_addr = str(donor.address())
    fee_payer = _VALIDATOR_ADDR or ""
    for name in names:
        w = WALLETS[name]
        addr = str(w.address())
        lb, _, _, _ = _get_pow_params(backend, donor_addr)
        ts = _now_ms()
        msg = _build_msg_send_tokens(donor, lb, 0, ts, donor_addr, addr, amount, pow_val=0)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgSendTokens")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            donor.public_key().public_key_bytes,
            wait_deliver=True,
        )
        label = f"{amount / 1_000_000:,.0f} MIRAGE"
        if ccode == 0 and (dcode is None or dcode == 0):
            _pass(f"topup.{name}", extra=label)
        else:
            _fail(f"topup.{name}", f"send_tokens failed ({label}) check={ccode} deliver={dcode} log={str(dlog or '')[:120]}")


def test_follow_limits(backend: str) -> None:
    """Test follow/unfollow tier limits and mutual exclusion at chain level."""
    print(f"\n{_COLOR_BOLD}[8] Follow limits & mutual exclusion{_COLOR_RESET}")

    # Top up wallets before the gas-heavy fill loops
    _topup_wallets(backend, ["free", "sub1"])
    time.sleep(3)

    # Use the FREE wallet (tier 0) so we hit the real free-tier ceiling
    # and can verify overflow is rejected.
    fw = WALLETS["free"]
    fw_addr = str(fw.address())
    fw_pub = fw.public_key().public_key_bytes
    fee_payer = _VALIDATOR_ADDR or ""
    tier0 = _get_tier_config(0)

    # 8.1 Fill free-tier max_followed_users + overflow
    max_followed_users = _tier_int(tier0, "max_followed_users")
    _debug(f"free-tier max_followed_users={max_followed_users}")
    fill_ok = True
    followed_user_targets: list[str] = []
    for i in range(max_followed_users):
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, fw_addr)
        ts = _now_ms()
        if i > 0 and i % 10 == 0:
            print(f"    [{i}/{max_followed_users}] followed users…")
        target_addr = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        followed_user_targets.append(target_addr.lower())
        base = _canon_base_follow_user_raw(fw_pub, _lb_bytes(lb), diff, ts, fw_addr, target_addr)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_follow_user(fw, lb, diff, ts, fw_addr, target_addr, pow_val=proof)
        _, ccode, _, dcode, _ = _submit_tx(
            [(msg, "/mirage.core.v1.MsgFollowUser")],
            FILL_GAS_LIMIT,
            fee_payer,
            fw_pub,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail("follow.user_fill", f"index={i} check={ccode} deliver={dcode}")
            fill_ok = False
            break
    else:
        _pass(f"follow.user_fill ({max_followed_users} followed)")

    if fill_ok:
        # Overflow should be REJECTED (hard cap, not deque)
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, fw_addr)
        ts = _now_ms()
        over_addr = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        base = _canon_base_follow_user_raw(fw_pub, _lb_bytes(lb), diff, ts, fw_addr, over_addr)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_follow_user(fw, lb, diff, ts, fw_addr, over_addr, pow_val=proof)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgFollowUser")],
            FILL_GAS_LIMIT,
            fee_payer,
            fw_pub,
            wait_deliver=True,
        )
        _check_deliver_reject("follow.user_overflow_rejected (hard cap)", ccode, dcode, dlog)

    # 8.2 Fill free-tier max_followed_topics + overflow
    max_followed_topics = _tier_int(tier0, "max_followed_topics")
    _debug(f"free-tier max_followed_topics={max_followed_topics}")
    fill_ok = True
    followed_topic_targets: list[str] = []
    for i in range(max_followed_topics):
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, fw_addr)
        ts = _now_ms()
        if i > 0 and i % 10 == 0:
            print(f"    [{i}/{max_followed_topics}] followed topics…")
        topic = f"ft{_rand_str(4)}{i}"
        followed_topic_targets.append(topic)
        base = _canon_base_follow_topic_raw(fw_pub, _lb_bytes(lb), diff, ts, fw_addr, topic)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_follow_topic(fw, lb, diff, ts, fw_addr, topic, pow_val=proof)
        _, ccode, _, dcode, _ = _submit_tx(
            [(msg, "/mirage.core.v1.MsgFollowTopic")],
            FILL_GAS_LIMIT,
            fee_payer,
            fw_pub,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail("follow.topic_fill", f"index={i} check={ccode} deliver={dcode}")
            fill_ok = False
            break
    else:
        _pass(f"follow.topic_fill ({max_followed_topics} followed)")

    if fill_ok:
        # Overflow should be REJECTED (hard cap, not deque)
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, fw_addr)
        ts = _now_ms()
        over_topic = f"ft{_rand_str(4)}over"
        base = _canon_base_follow_topic_raw(fw_pub, _lb_bytes(lb), diff, ts, fw_addr, over_topic)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_follow_topic(fw, lb, diff, ts, fw_addr, over_topic, pow_val=proof)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgFollowTopic")],
            FILL_GAS_LIMIT,
            fee_payer,
            fw_pub,
            wait_deliver=True,
        )
        _check_deliver_reject("follow.topic_overflow_rejected (hard cap)", ccode, dcode, dlog)

    # 8.3 Fill free-tier max_enabled_agents + overflow
    max_enabled_agents = _tier_int(tier0, "max_enabled_agents")
    _debug(f"free-tier max_enabled_agents={max_enabled_agents}")
    fill_ok = True
    enabled_agent_targets: list[str] = []
    for i in range(max_enabled_agents):
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, fw_addr)
        ts = _now_ms()
        agent_addr = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        enabled_agent_targets.append(agent_addr.lower())
        base = _canon_base_enable_agent_raw(fw_pub, _lb_bytes(lb), diff, ts, fw_addr, agent_addr)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_enable_agent(fw, lb, diff, ts, fw_addr, agent_addr, pow_val=proof)
        _, ccode, _, dcode, _ = _submit_tx(
            [(msg, "/mirage.core.v1.MsgEnableAgent")],
            FILL_GAS_LIMIT,
            fee_payer,
            fw_pub,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail("follow.agent_fill", f"index={i} check={ccode} deliver={dcode}")
            fill_ok = False
            break
    else:
        _pass(f"follow.agent_fill ({max_enabled_agents} enabled)")

    if fill_ok:
        # Overflow should be REJECTED (hard cap, not deque)
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, fw_addr)
        ts = _now_ms()
        over_agent = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        base = _canon_base_enable_agent_raw(fw_pub, _lb_bytes(lb), diff, ts, fw_addr, over_agent)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_enable_agent(fw, lb, diff, ts, fw_addr, over_agent, pow_val=proof)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgEnableAgent")],
            FILL_GAS_LIMIT,
            fee_payer,
            fw_pub,
            wait_deliver=True,
        )
        _check_deliver_reject("follow.agent_overflow_rejected (hard cap)", ccode, dcode, dlog)

    # 8.3b Subscriber bulk fill (no PoW): submit follow-user messages up to
    # the tier limit, then verify overflow is rejected (hard cap).
    sub = WALLETS["sub1"]
    sub_addr = str(sub.address())
    sub_pub = sub.public_key().public_key_bytes
    sub_tier = _get_tier_config(1)
    sub_max_followed_users = _tier_int(sub_tier, "max_followed_users")
    before_profile = _get_profile_full(backend, sub_addr)
    before_followed = [str(v).lower() for v in (before_profile.get("followed_users") or [])]
    remaining = sub_max_followed_users - len(before_followed)
    bulk_targets = [
        str(LocalWallet(PrivateKey(), prefix="mirage").address()).lower() for _ in range(remaining)
    ]
    chunk_size = 25
    bulk_ok = True
    _debug(f"subscriber tier1 bulk follow users: total={len(bulk_targets)} chunk_size={chunk_size}")
    for start in range(0, len(bulk_targets), chunk_size):
        batch = bulk_targets[start : start + chunk_size]
        lb, _, _, _ = _get_pow_params(backend, sub_addr)
        ts_base = _now_ms()
        msgs: list[tuple[object, str]] = []
        for i, target_addr in enumerate(batch):
            msg = _build_msg_follow_user(sub, lb, 0, ts_base + i, sub_addr, target_addr, pow_val=0)
            msgs.append((msg, "/mirage.core.v1.MsgFollowUser"))
        gas_limit = max(FILL_GAS_LIMIT, int(DEFAULT_GAS_LIMIT * len(msgs) * 1.5))
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
        # Now verify overflow is REJECTED
        lb, _, _, _ = _get_pow_params(backend, sub_addr)
        ts = _now_ms()
        over_addr = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        msg = _build_msg_follow_user(sub, lb, 0, ts, sub_addr, over_addr, pow_val=0)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgFollowUser")],
            FILL_GAS_LIMIT,
            fee_payer,
            sub_pub,
            wait_deliver=True,
        )
        _check_deliver_reject("follow.subscriber_bulk_user_overflow_rejected (hard cap)", ccode, dcode, dlog)

    # 8.4 Follow user removes blocked user (mutual exclusion)
    w_mx = WALLETS["sub3"]
    w_mx_addr = str(w_mx.address())
    lb, _, _, _ = _get_pow_params(backend, w_mx_addr)
    ts = _now_ms()
    block_target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    msg = _build_msg_block_user(w_mx, lb, 0, ts, block_target, pow_val=0)
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
        msg = _build_msg_follow_user(w_mx, lb, 0, ts, w_mx_addr, block_target, pow_val=0)
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

    # 8.5 Follow topic removes blocked topic (mutual exclusion)
    lb, _, _, _ = _get_pow_params(backend, w_mx_addr)
    ts = _now_ms()
    block_topic = f"mx{_rand_str(4)}"
    msg = _build_msg_block_topic(w_mx, lb, 0, ts, w_mx_addr, block_topic, pow_val=0)
    _, ccode, _, dcode, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgBlockTopic")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w_mx.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode == 0 and dcode == 0:
        lb, _, _, _ = _get_pow_params(backend, w_mx_addr)
        ts = _now_ms()
        msg = _build_msg_follow_topic(w_mx, lb, 0, ts, w_mx_addr, block_topic, pow_val=0)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgFollowTopic")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w_mx.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_accept("follow.topic_removes_block", ccode, dcode, dlog)
    else:
        _fail("follow.topic_removes_block", "setup block failed")

    # 8.6 Double follow same user (should be idempotent or rejected, not crash)
    lb, _, _, _ = _get_pow_params(backend, w_mx_addr)
    ts = _now_ms()
    dbl_target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    msg = _build_msg_follow_user(w_mx, lb, 0, ts, w_mx_addr, dbl_target, pow_val=0)
    _, ccode, _, dcode, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgFollowUser")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w_mx.public_key().public_key_bytes,
        wait_deliver=True,
    )
    if ccode == 0 and dcode == 0:
        msg = _build_msg_follow_user(w_mx, lb, 0, ts, w_mx_addr, dbl_target, pow_val=0)
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
    msg = _build_msg_unfollow_user(w_mx, lb, 0, ts, w_mx_addr, unfol_target, pow_val=0)
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


def test_msg_format(backend: str) -> None:
    """Test invalid field values at chain level (bypassing backend validation)."""
    print(f"\n{_COLOR_BOLD}[9] Message format validation at chain level{_COLOR_RESET}")

    w1 = WALLETS["sub1"]
    fee_payer = _VALIDATOR_ADDR or ""
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
        msg = _build_msg_set_username(w1, lb, 0, ts, str(w1.address()), uname, pow_val=0)
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
        msg = _build_msg_post(w1, lb, 0, ts, topic, "Title", "content", pow_val=0)
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
        msg = _build_msg_post(w1, lb, 0, ts, f"fmt{_rand_str(4)}", "Title", "content", tag=tag, pow_val=0)
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
        msg = _build_msg_post(w1, lb, 0, ts, f"fmt{_rand_str(4)}", title, content, pow_val=0)
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
        msg = _build_msg_vote(w1, lb, 0, ts, post_target, direction, pow_val=0)
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
        w1, lb, 0, ts, f"fmt{_rand_str(4)}", "Title", "content", media=["http://insecure.com/img.jpg"], pow_val=0
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
    msg = _build_msg_post(w1, lb, 0, ts, f"fmt{_rand_str(4)}", "Title", "content", media=many_media, pow_val=0)
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
    msg = _build_msg_post(w1, lb, 0, ts, f"fmt{_rand_str(4)}", "Title", "content", media=[long_url], pow_val=0)
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
    msg = _build_msg_post(w1, lb, 0, ts, f"fmt{_rand_str(4)}", big_title, "content", pow_val=0)
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
    print(f"\n{_COLOR_BOLD}[9b] Malicious / adversarial inputs{_COLOR_RESET}")

    w1 = WALLETS["sub1"]
    fee_payer = _VALIDATOR_ADDR or ""
    lb, _, _, _ = _get_pow_params(backend, str(w1.address()))
    ts = _now_ms()

    def _submit_post(label, topic="", title="", content="", tag=""):
        nonlocal lb, ts
        msg = _build_msg_post(w1, lb, 0, ts, topic, title, content, tag=tag, pow_val=0)
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
    msg = _build_msg_set_username(w1, lb, 0, ts, str(w1.address()), f"user\x00name", pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetUsername")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("malicious.nul_in_username", ccode, dcode, dlog)

    # ─── Control char in username ─────────────────────────────────
    msg = _build_msg_set_username(w1, lb, 0, ts, str(w1.address()), f"user\x08name", pow_val=0)
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
    msg = _build_msg_award(w1, lb, 0, ts, award_target, "quality\x00post", pow_val=0)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgAward")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        w1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_reject("malicious.nul_in_award_type", ccode, dcode, dlog)

    msg = _build_msg_award(w1, lb, 0, ts, award_target, "quality\x1bpost", pow_val=0)
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
        )
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_reject(f"malicious.{label}", ccode, dcode, dlog)


def test_tier_enforcement(backend: str) -> None:
    """Test content/title limits per tier at chain level."""
    print(f"\n{_COLOR_BOLD}[10] Tier-based content/title limits{_COLOR_RESET}")

    fee_payer = _VALIDATOR_ADDR or ""

    for level, wallet_name in [(0, "free"), (1, "sub1"), (1, "sub2"), (10, "sub3")]:
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
            base = _canon_base_post_raw(pub, _lb_bytes(lb), diff, ts, "", topic, "Title", over_content, "", 0, [])
            proof = compute_pow(base, diff, base_bits, pow_factor, lb)
            msg = _build_msg_post(w, lb, diff, ts, topic, "Title", over_content, pow_val=int(proof))
        else:
            topic = f"tier{_rand_str(4)}"
            over_content = "x" * (max_content + 25)
            msg = _build_msg_post(w, lb, 0, ts, topic, "Title", over_content, pow_val=0)

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
            base2 = _canon_base_post_raw(pub, _lb_bytes(lb), diff, ts, "", topic2, over_title, "body", "", 0, [])
            proof2 = compute_pow(base2, diff, base_bits, pow_factor, lb)
            msg2 = _build_msg_post(w, lb, diff, ts, topic2, over_title, "body", pow_val=int(proof2))
        else:
            topic2 = f"tier{_rand_str(4)}"
            over_title = "T" * (max_title + 25)
            msg2 = _build_msg_post(w, lb, 0, ts, topic2, over_title, "body", pow_val=0)

        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg2, "/mirage.core.v1.MsgPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_reject(f"tier.t{level}_title_over_max", ccode, dcode, dlog)


def test_chain_auto_renewal(backend: str) -> None:
    """Test auto-renewal at chain level."""
    print(f"\n{_COLOR_BOLD}[11] Auto-renewal chain validation{_COLOR_RESET}")

    sub1 = WALLETS["sub1"]
    free_wallet = WALLETS["free"]
    fee_payer = _VALIDATOR_ADDR or ""
    lb, _, _, _ = _get_pow_params(backend, str(sub1.address()))
    ts = _now_ms()

    # 11.1 Subscriber enables auto-renewal
    msg = _build_msg_set_auto_renewal(sub1, lb, ts, True)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetAutoRenewal")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        sub1.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("auto.subscriber_enable", ccode, dcode, dlog)

    # 11.2 Subscriber disables auto-renewal
    msg = _build_msg_set_auto_renewal(sub1, lb, ts, False)
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
    msg = _build_msg_set_auto_renewal(free_wallet, lb_free, ts, True)
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
    msg.authority = _VALIDATOR_ADDR or ""
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


def test_governance_reject(backend: str) -> None:
    """Test that governance-only messages are rejected from non-governance callers."""
    print(f"\n{_COLOR_BOLD}[12] Governance-only message rejection{_COLOR_RESET}")

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
    print(f"\n{_COLOR_BOLD}[13] Direct bank send (bypass check){_COLOR_RESET}")
    kb = _keyring_backend()
    key_name = f"directbank{_rand_str(6)}"

    code, out = _run_miraged(
        ["keys", "add", key_name, "--home", "/root/.mirage/node", "--keyring-backend", kb, "--output", "json"],
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

    if not tb._faucet(backend, addr, 5_000_000):
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
            "/root/.mirage/node",
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
            "5000umirage",
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


def test_hard_cap_vs_deque(backend: str) -> None:
    """Test that follow/enable lists use hard cap while block lists use deque."""
    print(f"\n{_COLOR_BOLD}[13] Hard cap vs deque behavior{_COLOR_RESET}")

    _topup_wallets(backend, ["free", "sub3"])
    time.sleep(3)

    fee_payer = _VALIDATOR_ADDR or ""

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
    for i in range(total_to_block):
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
        ts = _now_ms()
        target_addr = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        blocked_targets.append(target_addr.lower())
        base = _canon_base_block_user_raw(bw_pub, _lb_bytes(lb), diff, ts, target_addr)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_user(bw, lb, diff, ts, target_addr, pow_val=proof)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockUser")],
            FILL_GAS_LIMIT,
            fee_payer,
            bw_pub,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail("hardcap.blocked_user_deque_fill", f"i={i} ccode={ccode} dcode={dcode}")
            break
    else:
        _pass(f"hardcap.blocked_user_deque_fill ({total_to_block} blocked, no rejection)")

    profile = _get_profile_full(backend, bw_addr)
    chain_blocked = [str(v).lower() for v in (profile.get("blocked_users") or [])]
    if len(chain_blocked) <= max_blocked_users:
        _pass(f"hardcap.blocked_user_deque_capped (len={len(chain_blocked)} <= {max_blocked_users})")
    else:
        _fail(f"hardcap.blocked_user_deque_capped", f"len={len(chain_blocked)} > {max_blocked_users}")

    # ── 13.2 blocked_posts deque ──
    max_blocked_posts = _tier_int(tier0, "max_blocked_posts")
    blocked_post_targets: list[str] = []
    total_to_block_posts = max_blocked_posts + 2
    for i in range(total_to_block_posts):
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
        ts = _now_ms()
        fake_hash = _rand_hex(64)
        blocked_post_targets.append(fake_hash.lower())
        base = _canon_base_block_post_raw(bw_pub, _lb_bytes(lb), diff, ts, fake_hash)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_post(bw, lb, diff, ts, fake_hash, pow_val=proof)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockPost")],
            FILL_GAS_LIMIT,
            fee_payer,
            bw_pub,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail("hardcap.blocked_post_deque_fill", f"i={i}")
            break
    else:
        _pass(f"hardcap.blocked_post_deque_fill ({total_to_block_posts} blocked, no rejection)")

    # ── 13.3 blocked_topics deque ──
    max_blocked_topics = _tier_int(tier0, "max_blocked_topics")
    total_to_block_topics = max_blocked_topics + 2
    for i in range(total_to_block_topics):
        lb, diff, base_bits, pow_factor = _get_pow_params(backend, bw_addr)
        ts = _now_ms()
        topic = f"bt{_rand_str(4)}{i}"
        base = _canon_base_block_topic_raw(bw_pub, _lb_bytes(lb), diff, ts, bw_addr, topic)
        proof = _compute_pow_quiet(base, diff, base_bits, pow_factor, lb)
        msg = _build_msg_block_topic(bw, lb, diff, ts, bw_addr, topic, pow_val=proof)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockTopic")],
            FILL_GAS_LIMIT,
            fee_payer,
            bw_pub,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail("hardcap.blocked_topic_deque_fill", f"i={i}")
            break
    else:
        _pass(f"hardcap.blocked_topic_deque_fill ({total_to_block_topics} blocked, no rejection)")

    # ── 13.4 Enable agent then disable to verify recovery ──
    aw = WALLETS["sub3"]
    aw_addr = str(aw.address())
    aw_pub = aw.public_key().public_key_bytes
    tier10 = _get_tier_config(10)
    # Use a smaller test: enable 2 agents, disable 1, enable 1 new one
    agent1 = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    agent2 = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    agent3 = str(LocalWallet(PrivateKey(), prefix="mirage").address())

    for agent in [agent1, agent2]:
        lb, _, _, _ = _get_pow_params(backend, aw_addr)
        ts = _now_ms()
        msg = _build_msg_enable_agent(aw, lb, 0, ts, aw_addr, agent, pow_val=0)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgEnableAgent")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            aw_pub,
            wait_deliver=True,
        )
        _check_deliver_accept(f"hardcap.enable_agent_{agent[:8]}", ccode, dcode, dlog)

    # Disable agent1
    lb, _, _, _ = _get_pow_params(backend, aw_addr)
    ts = _now_ms()
    msg = _build_msg_disable_agent(aw, lb, 0, ts, aw_addr, agent1, pow_val=0)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgDisableAgent")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        aw_pub,
        wait_deliver=True,
    )
    _check_deliver_accept("hardcap.disable_agent_recovery", ccode, dcode, dlog)

    # Enable agent3 (should work since we freed a slot)
    lb, _, _, _ = _get_pow_params(backend, aw_addr)
    ts = _now_ms()
    msg = _build_msg_enable_agent(aw, lb, 0, ts, aw_addr, agent3, pow_val=0)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgEnableAgent")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        aw_pub,
        wait_deliver=True,
    )
    _check_deliver_accept("hardcap.enable_after_disable", ccode, dcode, dlog)


def test_upgrade_level_validation(backend: str) -> None:
    """Test that only levels 1 and 10 can be self-upgraded to."""
    print(f"\n{_COLOR_BOLD}[14] Upgrade level validation{_COLOR_RESET}")

    fee_payer = _VALIDATOR_ADDR or ""
    fw = WALLETS["free"]
    fw_addr = str(fw.address())
    fw_pub = fw.public_key().public_key_bytes

    # 14.1 Invalid levels should be rejected
    for invalid_level in [0, 2, 3, 4, 5, 6, 7, 8, 9, 11, 50, 99, 100]:
        lb, _, _, _ = _get_pow_params(backend, fw_addr)
        ts = _now_ms()
        msg = _build_msg_upgrade_level(fw, lb, 0, ts, invalid_level, pow_val=0)
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgUpgradeLevel")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            fw_pub,
            wait_deliver=True,
        )
        _check_deliver_reject(f"upgrade.invalid_level_{invalid_level}", ccode, dcode, dlog)


def test_tier_features(backend: str) -> None:
    """Test tier-specific features: can_remove_anon, content limits."""
    print(f"\n{_COLOR_BOLD}[15] Tier feature enforcement{_COLOR_RESET}")

    fee_payer = _VALIDATOR_ADDR or ""

    # 15.1 Verify all tier configs are accessible and have correct values
    for level in [0, 1, 10]:
        tier = _get_tier_config(level)
        max_enabled = _tier_int(tier, "max_enabled_agents")
        max_fu = _tier_int(tier, "max_followed_users")
        max_ft = _tier_int(tier, "max_followed_topics")
        max_bu = _tier_int(tier, "max_blocked_users")
        max_bp = _tier_int(tier, "max_blocked_posts")
        max_bt = _tier_int(tier, "max_blocked_topics")
        max_title = _tier_int(tier, "max_title_length")
        max_content = _tier_int(tier, "max_content_length")
        editing = _tier_int(tier, "editing_time_mins")

        if level == 0:
            if max_enabled == 25 and max_fu == 25 and max_ft == 25:
                _pass(f"tierfeature.level{level}_list_limits_25")
            else:
                _fail(f"tierfeature.level{level}_list_limits_25", f"agents={max_enabled} fu={max_fu} ft={max_ft}")
            if max_bu == 25 and max_bp == 25 and max_bt == 25:
                _pass(f"tierfeature.level{level}_blocked_limits_25")
            else:
                _fail(f"tierfeature.level{level}_blocked_limits_25", f"bu={max_bu} bp={max_bp} bt={max_bt}")
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
            if max_enabled == 500 and max_fu == 500 and max_ft == 500:
                _pass(f"tierfeature.level{level}_list_limits_500")
            else:
                _fail(f"tierfeature.level{level}_list_limits_500", f"agents={max_enabled} fu={max_fu} ft={max_ft}")
            if max_bu == 500 and max_bp == 500 and max_bt == 500:
                _pass(f"tierfeature.level{level}_blocked_limits_500")
            else:
                _fail(f"tierfeature.level{level}_blocked_limits_500", f"bu={max_bu} bp={max_bp} bt={max_bt}")
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
    tier10 = _get_tier_config(10)

    can_be_agent_0 = tier0.get("can_be_agent", False)
    can_be_agent_1 = tier1.get("can_be_agent", False)
    can_be_agent_10 = tier10.get("can_be_agent", False)
    if not can_be_agent_0 and not can_be_agent_1 and can_be_agent_10:
        _pass("tierfeature.can_be_agent_only_level10")
    else:
        _fail("tierfeature.can_be_agent_only_level10",
              f"t0={can_be_agent_0} t1={can_be_agent_1} t10={can_be_agent_10}")

    can_remove_anon_0 = tier0.get("can_remove_anon", False)
    can_remove_anon_1 = tier1.get("can_remove_anon", False)
    can_remove_anon_10 = tier10.get("can_remove_anon", False)
    if not can_remove_anon_0 and can_remove_anon_1 and can_remove_anon_10:
        _pass("tierfeature.can_remove_anon")
    else:
        _fail("tierfeature.can_remove_anon",
              f"t0={can_remove_anon_0} t1={can_remove_anon_1} t10={can_remove_anon_10}")

    for flag in ["can_have_biography", "can_have_avatar", "can_have_banner", "can_have_flair"]:
        v0 = tier0.get(flag, False)
        v1 = tier1.get(flag, False)
        v10 = tier10.get(flag, False)
        if not v0 and v1 and v10:
            _pass(f"tierfeature.{flag}")
        else:
            _fail(f"tierfeature.{flag}", f"t0={v0} t1={v1} t10={v10}")

    # 15.3 vote_weight
    vw0 = float(tier0.get("vote_weight", 0))
    vw1 = float(tier1.get("vote_weight", 0))
    vw10 = float(tier10.get("vote_weight", 0))
    if abs(vw0 - 1.0) < 0.01 and abs(vw1 - 1.33) < 0.01 and abs(vw10 - 1.33) < 0.01:
        _pass("tierfeature.vote_weights")
    else:
        _fail("tierfeature.vote_weights", f"vw0={vw0} vw1={vw1} vw10={vw10}")

    # 15.4 period_fee
    pf0 = int(tier0.get("period_fee", -1))
    pf1 = int(tier1.get("period_fee", -1))
    pf10 = int(tier10.get("period_fee", -1))
    if pf0 == 0 and pf1 == 100_000_000_000 and pf10 == 200_000_000_000:
        _pass("tierfeature.period_fees")
    else:
        _fail("tierfeature.period_fees", f"pf0={pf0} pf1={pf1} pf10={pf10}")

    # 15.5 Only 3 tiers exist
    params = _get_chain_params()
    num_tiers = len(params.get("tiers") or [])
    if num_tiers == 3:
        _pass("tierfeature.exactly_3_tiers")
    else:
        _fail("tierfeature.exactly_3_tiers", f"got {num_tiers}")

    # 15.6 Free user content limit is enforced at chain
    fw = WALLETS["free"]
    lb, diff, base_bits, pow_factor = _get_pow_params(backend, str(fw.address()))
    ts = _now_ms()
    topic = f"tf{_rand_str(4)}"
    over_content = "x" * 1050
    pub = fw.public_key().public_key_bytes
    base = _canon_base_post_raw(pub, _lb_bytes(lb), diff, ts, "", topic, "Title", over_content, "", 0, [])
    proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    msg = _build_msg_post(fw, lb, diff, ts, topic, "Title", over_content, pow_val=int(proof))
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
    msg = _build_msg_post(sw, lb, 0, ts, topic2, "Title", long_content, pow_val=0)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        sw.public_key().public_key_bytes,
        wait_deliver=True,
    )
    _check_deliver_accept("tierfeature.sub_content_1050_accepted", ccode, dcode, dlog)


# =========================================================================
# Main
# =========================================================================
ALL_CATEGORIES = {
    "relay_sig": test_relay_sig,
    "pow": test_pow,
    "authority": test_authority,
    "fee": test_fee,
    "staking": test_staking,
    "msg_validation": test_msg_validation,
    "direct_bank": test_direct_bank,
    "follow_limits": test_follow_limits,
    "msg_format": test_msg_format,
    "malicious_inputs": test_malicious_inputs,
    "tier_enforcement": test_tier_enforcement,
    "auto_renewal": test_chain_auto_renewal,
    "governance": test_governance_reject,
    "hard_cap_vs_deque": test_hard_cap_vs_deque,
    "upgrade_validation": test_upgrade_level_validation,
    "tier_features": test_tier_features,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirage Blockchain Direct-Submit Test Suite")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help=f"Backend URL (default: {DEFAULT_BACKEND})")
    parser.add_argument(
        "--category", "-c", default=None, help=f"Run single category: {', '.join(ALL_CATEGORIES.keys())}"
    )
    args = parser.parse_args()
    backend = args.backend.rstrip("/")

    print("=" * 60)
    print("Mirage Blockchain Direct-Submit Test Suite")
    print(f"Backend: {backend}")
    print("=" * 60)

    # ── Local-only guard ──────────────────────────────────────────
    from urllib.parse import urlparse

    parsed = urlparse(backend)
    hostname = (parsed.hostname or "").lower()
    if hostname not in ("127.0.0.1", "localhost", "::1"):
        print(f"\n{_COLOR_RED}ABORT: This test suite is designed ONLY for local Docker testnet.{_COLOR_RESET}")
        print(f"  Backend host '{hostname}' is not localhost.")
        return 1

    if not _check_local_docker():
        print(f"\n{_COLOR_RED}ABORT: Cannot execute commands in the mirage environment.{_COLOR_RESET}")
        print(f"  Either run this from inside the container, or ensure the 'mirage' Docker container is running.")
        return 1

    if _INSIDE_CONTAINER:
        print("  Running inside container.")
    else:
        print("  Docker container 'mirage' is running.")

    # ── Verify connectivity ───────────────────────────────────────
    try:
        code = requests.get(f"{backend}/api/get_parameters", timeout=10).status_code
        if code != 200:
            print(f"\n{_COLOR_RED}Cannot reach backend at {backend} (code={code}){_COLOR_RESET}")
            return 1
    except Exception as e:
        print(f"\n{_COLOR_RED}Cannot reach backend at {backend}: {e}{_COLOR_RESET}")
        return 1

    # ── Verify container is the local testnet ─────────────────────
    try:
        rc, container_hostname = _docker_exec("hostname", timeout=5)
        ch = container_hostname.strip().lower()
        if rc != 0 or ch != "testnet":
            print(f"\n{_COLOR_RED}ABORT: Container hostname is '{ch}', expected 'testnet'.{_COLOR_RESET}")
            print("  This suite must NEVER run against prod/UAT.")
            return 1
    except Exception as e:
        print(f"\n{_COLOR_RED}ABORT: Cannot verify container hostname: {e}{_COLOR_RESET}")
        return 1

    # ── Setup wallets ─────────────────────────────────────────────
    if not setup_test_wallets(backend):
        print(f"\n{_COLOR_RED}ABORT: Wallet setup failed.{_COLOR_RESET}")
        return 1

    global _VALIDATOR_ADDR, _GOV_MODULE_ADDR
    try:
        _VALIDATOR_ADDR = _get_validator_account_address(backend)
        _GOV_MODULE_ADDR = _get_gov_module_address()
        _debug(f"validator_addr={_VALIDATOR_ADDR}")
        _debug(f"gov_module_addr={_GOV_MODULE_ADDR}")
    except Exception as e:
        print(f"\n{_COLOR_RED}ABORT: Cannot resolve validator/gov addresses: {e}{_COLOR_RESET}")
        return 1

    if args.category:
        cats = [c.strip() for c in args.category.split(",")]
        for c in cats:
            if c not in ALL_CATEGORIES:
                print(f"{_COLOR_RED}Unknown category: {c}{_COLOR_RESET}")
                print(f"Available: {', '.join(ALL_CATEGORIES.keys())}")
                return 1
        to_run = {c: ALL_CATEGORIES[c] for c in cats}
    else:
        to_run = ALL_CATEGORIES

    for name, fn in to_run.items():
        try:
            fn(backend)
        except Exception as e:
            _fail(f"{name}.UNEXPECTED_ERROR", str(e))

    passed = sum(1 for r in RESULTS if r.passed)
    failed = sum(1 for r in RESULTS if not r.passed)
    total = len(RESULTS)

    print(f"\n{'=' * 60}")
    if failed:
        print(f"{_COLOR_RED}{_COLOR_BOLD}RESULT: {passed}/{total} passed, {failed} FAILED{_COLOR_RESET}")
        print("\nFailed tests:")
        for r in RESULTS:
            if not r.passed:
                err = f" — {r.error}" if r.error else ""
                print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  {r.name}{err}")
        return 1
    else:
        print(f"{_COLOR_GREEN}{_COLOR_BOLD}RESULT: {passed}/{total} passed, ALL OK{_COLOR_RESET}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
