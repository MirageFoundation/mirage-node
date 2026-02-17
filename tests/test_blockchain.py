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

from shared.client import compute_pow, get_status, sign_canonical
from shared.canon import (
    canon_base_block_post as _canon_base_block_post_raw,
    canon_base_block_topic as _canon_base_block_topic_raw,
    canon_base_block_user as _canon_base_block_user_raw,
    canon_base_delete as _canon_base_delete_raw,
    canon_base_edit as _canon_base_edit_raw,
    canon_base_post as _canon_base_post_raw,
    canon_base_send_tokens as _canon_base_send_tokens_raw,
    canon_base_set_username as _canon_base_set_username_raw,
    canon_base_upgrade_level as _canon_base_upgrade_level_raw,
    canon_base_vote as _canon_base_vote_raw,
    canon_signed_with_pow,
)
from shared.datatypes import (
    MsgBlockPost,
    MsgBlockTopic,
    MsgBlockUser,
    MsgDelete,
    MsgEdit,
    MsgPost,
    MsgSendTokens,
    MsgSetUsername,
    MsgUpgradeLevel,
    MsgVote,
)

import tests.test_backend as tb

DEFAULT_BACKEND = tb.DEFAULT_BACKEND
COMET_RPC_URL = "http://127.0.0.1:26657"
DEFAULT_GAS_LIMIT = 200000

_COLOR_GREEN = "\033[92m"
_COLOR_RED = "\033[91m"
_COLOR_YELLOW = "\033[93m"
_COLOR_RESET = "\033[0m"
_COLOR_BOLD = "\033[1m"

_INSIDE_CONTAINER = tb._INSIDE_CONTAINER
_docker_exec = tb._docker_exec
_check_local_docker = tb._check_local_docker
_miraged_cmd = tb._miraged_cmd
_keyring_backend = tb._keyring_backend
_rand_str = tb._rand_str
_now_ms = tb._now_ms
_lb_bytes = tb._lb_bytes

WALLETS: dict[str, LocalWallet] = {}
_VALIDATOR_ADDR: Optional[str] = None
_GOV_MODULE_ADDR: Optional[str] = None


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
    miraged = _miraged_cmd()
    cmd = f"{miraged} q auth module-account gov --home /root/.mirage/node --node tcp://127.0.0.1:26657 -o json"
    code, out = _docker_exec(cmd, timeout=10)
    if code != 0 or not out:
        raise RuntimeError(f"failed to query gov module account: {out[:200]}")
    data = json.loads(out)
    acc = (data or {}).get("account") or {}
    if "base_account" in acc:
        addr = str((acc.get("base_account") or {}).get("address", "")).strip()
    else:
        addr = str(acc.get("address", "")).strip()
    if not addr:
        raise RuntimeError("gov module address missing in response")
    return addr


def _get_chain_params() -> dict:
    miraged = _miraged_cmd()
    cmd = f"{miraged} q core params --home /root/.mirage/node --node tcp://127.0.0.1:26657 -o json"
    code, out = _docker_exec(cmd, timeout=10)
    if code != 0 or not out:
        raise RuntimeError(f"failed to query core params: {out[:200]}")
    data = json.loads(out)
    return data.get("params") or data


def _get_tier_config(level: int) -> dict:
    params = _get_chain_params()
    tiers = params.get("tiers") or []
    idx = int(level)
    if idx < 0 or idx >= len(tiers):
        raise RuntimeError(f"tier index {idx} not in params")
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
    h = tx_hash
    if not h.startswith("0x"):
        h = "0x" + h
    start = time.time()
    while (time.time() - start) < timeout:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "tx", "params": {"hash": h, "prove": False}}
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


def setup_test_wallets(backend: str) -> bool:
    ok = tb.setup_test_wallets(backend)
    if not ok:
        return False
    WALLETS.clear()
    WALLETS.update(tb.WALLETS)
    return True


def _check_reject(name: str, code: int, log: str, expect: str | None = None) -> None:
    if code != 0 and (expect is None or expect in log.lower()):
        _pass(name)
    else:
        _fail(name, f"code={code} log={log[:200]}")


def _check_deliver_reject(name: str, check_code: int, deliver_code: Optional[int], deliver_log: Optional[str]) -> None:
    if check_code != 0:
        _fail(name, f"checktx code={check_code}")
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

    # 1.5 Missing signature
    msg = _build_msg_post(wallet, lb, 0, ts, f"sig{_rand_str(4)}", "Title", "content", pow_val=0, sig_override=b"")
    _, code, log, _, _ = _submit_tx([(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, signer_pub)
    _check_reject("relay_sig.missing_signature", code, log, "invalid relay fields")

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
    diff_low = max(diff - 1, 0)
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
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, free_wallet.public_key().public_key_bytes
    )
    _check_reject("pow.insufficient_difficulty", code, log)

    # 2.3 Invalid block hash
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
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, free_wallet.public_key().public_key_bytes
    )
    _check_reject("pow.invalid_block_hash", code, log)

    # 2.4 PoW on paid user (should be rejected by chain)
    msg = _build_msg_post(paid_wallet, lb, diff, ts, f"pow{_rand_str(4)}", "Title", "content", pow_val=1)
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")], DEFAULT_GAS_LIMIT, fee_payer, paid_wallet.public_key().public_key_bytes
    )
    _check_reject("pow.pow_on_paid_user", code, log)

    # 2.5 PoW on MsgUpgradeLevel (never allowed)
    msg = _build_msg_upgrade_level(free_wallet, lb, 0, ts, 1, pow_val=1)
    _, code, log, _, _ = _submit_tx(
        [(msg, "/mirage.core.v1.MsgUpgradeLevel")],
        DEFAULT_GAS_LIMIT,
        fee_payer,
        free_wallet.public_key().public_key_bytes,
    )
    _check_reject("pow.pow_on_upgrade_level", code, log)


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
    _check_reject("authority.gov_spoof", code, log, "signature")


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

    # 6.10 Block limits: posts/users/topics
    tier = _get_tier_config(1)
    max_blocked_posts = _tier_int(tier, "max_blocked_posts")
    max_blocked_users = _tier_int(tier, "max_blocked_users")
    max_blocked_topics = _tier_int(tier, "max_blocked_topics")

    _debug(f"tier1 max_blocked_posts={max_blocked_posts}")
    for i in range(max_blocked_posts):
        target = _rand_hex(64)
        msg = _build_msg_block_post(w1, lb, 0, ts, target, pow_val=0)
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail("msg.block_post_fill", f"index={i} check={ccode} deliver={dcode}")
            break
    else:
        msg = _build_msg_block_post(w1, lb, 0, ts, _rand_hex(64), pow_val=0)
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockPost")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_reject("msg.block_post_over_limit", ccode, dcode, dlog)

    _debug(f"tier1 max_blocked_users={max_blocked_users}")
    for i in range(max_blocked_users):
        target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        msg = _build_msg_block_user(w1, lb, 0, ts, target, pow_val=0)
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockUser")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail("msg.block_user_fill", f"index={i} check={ccode} deliver={dcode}")
            break
    else:
        target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        msg = _build_msg_block_user(w1, lb, 0, ts, target, pow_val=0)
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockUser")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_reject("msg.block_user_over_limit", ccode, dcode, dlog)

    _debug(f"tier1 max_blocked_topics={max_blocked_topics}")
    for i in range(max_blocked_topics):
        topic = f"t{_rand_str(6)}{i}"
        msg = _build_msg_block_topic(w1, lb, 0, ts, str(w1.address()), topic, pow_val=0)
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockTopic")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            _fail("msg.block_topic_fill", f"index={i} check={ccode} deliver={dcode}")
            break
    else:
        topic = f"t{_rand_str(6)}x"
        msg = _build_msg_block_topic(w1, lb, 0, ts, str(w1.address()), topic, pow_val=0)
        _, ccode, clog, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgBlockTopic")],
            DEFAULT_GAS_LIMIT,
            fee_payer,
            w1.public_key().public_key_bytes,
            wait_deliver=True,
        )
        _check_deliver_reject("msg.block_topic_over_limit", ccode, dcode, dlog)


def test_direct_bank(backend: str) -> None:
    print(f"\n{_COLOR_BOLD}[7] Direct bank send (bypass check){_COLOR_RESET}")
    miraged = _miraged_cmd()
    kb = _keyring_backend()
    key_name = f"directbank{_rand_str(6)}"

    cmd_add = f"{miraged} keys add {key_name} --home /root/.mirage/node --keyring-backend {kb} --output json"
    code, out = _docker_exec(cmd_add, timeout=10)
    if code != 0 or not out:
        _fail("direct_bank.key_add", f"exit={code} out={out[:200]}")
        return
    try:
        addr = str(json.loads(out).get("address", "")).strip()
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
    cmd_send = (
        f"{miraged} tx bank send {addr} {target} 1umirage "
        f"--home /root/.mirage/node --keyring-backend {kb} "
        f"--chain-id mirage-1 --node tcp://127.0.0.1:26657 --yes --gas auto "
        f"--gas-adjustment 1.5 --gas-prices 5000umirage -o json 2>&1"
    )
    code, out = _docker_exec(cmd_send, timeout=30)
    if code != 0 or not out:
        _fail("direct_bank.msg_send_blocked", f"exit={code} out={out[:200]}")
        return
    try:
        lines = out.strip().split("\n")
        resp = json.loads(lines[-1])
        tx_code = int(resp.get("code", 1))
    except Exception as e:
        _fail("direct_bank.msg_send_blocked", f"parse error: {e}")
        return

    if tx_code == 0:
        _fail("direct_bank.msg_send_blocked", "direct MsgSend succeeded (bypass allowed)")
    else:
        _pass("direct_bank.msg_send_blocked")


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
