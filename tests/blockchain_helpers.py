"""Blockchain-specific gRPC helpers, msg builders, and direct-submit utilities."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import random
import time
import tomllib
from typing import Optional

import grpc
import requests
from cosmpy.aerial.wallet import LocalWallet
from cosmpy.protos.cosmos.bank.v1beta1.tx_pb2 import MsgSend as BankMsgSend
from cosmpy.protos.cosmos.base.v1beta1.coin_pb2 import Coin
from cosmpy.protos.cosmos.crypto.secp256k1.keys_pb2 import PubKey as SecpPubKey
from cosmpy.protos.cosmos.staking.v1beta1.tx_pb2 import MsgBeginRedelegate, MsgDelegate, MsgUndelegate
from cosmpy.protos.cosmos.tx.signing.v1beta1.signing_pb2 import SignMode
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import AuthInfo, Fee, ModeInfo, SignerInfo, TxBody, TxRaw, SignDoc
from cosmpy.protos.cosmos.tx.v1beta1.service_pb2 import SimulateRequest
from cosmpy.protos.cosmos.tx.v1beta1.service_pb2_grpc import ServiceStub
from google.protobuf.any_pb2 import Any as AnyPB
from google.protobuf.timestamp_pb2 import Timestamp
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from shared.client import (
    _request_with_retries,
    check_pow_target,
    compute_pow,
    get_status,
    sign_canonical,
    der_to_compact_sig,
)
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
    canon_base_set_agents as _canon_base_set_agents_raw,
    canon_base_join_community as _canon_base_join_community_raw,
    canon_base_leave_community as _canon_base_leave_community_raw,
    canon_base_block_community as _canon_base_block_community_raw,
    canon_base_unblock_community as _canon_base_unblock_community_raw,
    canon_base_create_community as _canon_base_create_community_raw,
    canon_base_post as _canon_base_post_raw,
    canon_base_send_tokens as _canon_base_send_tokens_raw,
    canon_base_set_auto_renewal as _canon_base_set_auto_renewal_raw,
    canon_base_set_username as _canon_base_set_username_raw,
    canon_base_set_biography as _canon_base_set_biography_raw,
    canon_base_subscribe as _canon_base_subscribe_raw,
    canon_base_vote as _canon_base_vote_raw,
    canon_base_annotate as _canon_base_annotate_raw,
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
    MsgJoinCommunity,
    MsgLeaveCommunity,
    MsgBlockCommunity,
    MsgUnblockCommunity,
    MsgCreateCommunity,
)

from tests.common import (
    _pass,
    _fail,
    _debug,
    _lb_bytes,
    _now_ms,
    _rand_str,
    _run_miraged,
    _docker_exec,
    _INSIDE_CONTAINER,
    INDEX_TIMEOUT_SEC,
)

COMET_RPC_URL = "http://127.0.0.1:26657"
DEFAULT_GAS_LIMIT = 200000
FILL_GAS_LIMIT = 1000000
FILL_GAS_BUFFER = 1.3
ESTIMATED_CHECKTX_TOTAL = 230


def _gen_nonce() -> int:
    return int(time.time_ns()) ^ random.getrandbits(32)


_VALIDATOR_ADDR: Optional[str] = None
_GOV_MODULE_ADDR: Optional[str] = None
_GRPC_TARGET: Optional[str] = None
_GRPC_CHANNEL = None
_SIMULATE_MODE_LOGGED = False

_MIN_GAS_PRICE_CACHE: Optional[float] = None
_VALIDATOR_PRIVKEY: Optional[bytes] = None
_VALIDATOR_ACCOUNT_NUMBER: Optional[int] = None
_CHAIN_ID: Optional[str] = None
_UNORDERED_TTL_NS = 120 * 1_000_000_000


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


def _rand_hex(n: int) -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(n))


def _min_gas_price_umirage() -> float:
    global _MIN_GAS_PRICE_CACHE
    if _MIN_GAS_PRICE_CACHE is not None:
        return _MIN_GAS_PRICE_CACHE
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
            _MIN_GAS_PRICE_CACHE = float(p[:-7])
            return _MIN_GAS_PRICE_CACHE
    raise RuntimeError("minimum-gas-prices must include umirage")


def _get_grpc_target() -> str:
    global _GRPC_TARGET
    if _GRPC_TARGET is not None:
        return _GRPC_TARGET
    home = os.path.join(os.path.expanduser("~"), ".mirage", "node")
    path = os.path.join(home, "config", "app.toml")
    if not os.path.isfile(path):
        raise RuntimeError(f"app.toml not found: {path}")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    addr = str((data.get("grpc") or {}).get("address") or "").strip()
    if not addr:
        raise RuntimeError("grpc.address missing in app.toml")
    parts = addr.rsplit(":", 1)
    if len(parts) != 2:
        raise RuntimeError(f"invalid grpc.address: {addr}")
    host, port = parts[0].strip(), parts[1].strip()
    if host in ("0.0.0.0", "localhost"):
        host = "127.0.0.1"
    _GRPC_TARGET = f"{host}:{port}"
    return _GRPC_TARGET


def _get_grpc_channel():
    global _GRPC_CHANNEL
    if _GRPC_CHANNEL is None:
        _GRPC_CHANNEL = grpc.insecure_channel(_get_grpc_target())
    return _GRPC_CHANNEL


def _get_validator_account_address(backend: str) -> str:
    url = f"{backend}/api/get_node_config"
    resp = _request_with_retries("GET", url, timeout=10).json()
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


def _parse_cli_json(out: str) -> dict | None:
    """Extract the first top-level JSON object from CLI output that may
    contain log lines before/after the JSON."""
    idx = out.find("{")
    if idx < 0:
        return None
    depth = 0
    end = idx
    for i in range(idx, len(out)):
        if out[i] == "{":
            depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    try:
        return json.loads(out[idx:end])
    except (json.JSONDecodeError, ValueError):
        return None


def _get_chain_params() -> dict:
    code, out = _run_miraged(
        ["q", "core", "params", "--home", "/root/.mirage/node", "--node", "tcp://127.0.0.1:26657", "-o", "json"],
        timeout=10,
    )
    if code != 0 or not out:
        raise RuntimeError(f"failed to query core params: {out[:200]}")
    data = _parse_cli_json(out)
    if not data:
        raise RuntimeError(f"core params query: no JSON in output: {out[:200]}")
    return data.get("params") or data


def _get_tier_config(level: int) -> dict:
    """Map user level to tier array index: 0->0, 1->1."""
    params = _get_chain_params()
    tiers = params.get("tiers") or []
    idx_map = {0: 0, 1: 1}
    idx = idx_map.get(int(level), -1)
    if idx < 0 or idx >= len(tiers):
        raise RuntimeError(f"tier index {idx} (level={level}) not in params")
    return tiers[idx]


def _tier_int(tier: dict, key: str) -> int:
    if key not in tier:
        raise RuntimeError(f"tier param missing: {key}")
    return int(tier[key])


def _get_pow_params(backend: str, address: str | None = None) -> tuple[str, int, int, float]:
    # Prefer direct chain query (uncached) over backend /api/get_parameters
    # which has a 3-second cache TTL that causes stale params in bulk loops.
    # The difficulty query returns: current_difficulty, latest_block_hash,
    # min_difficulty (= pow_base_bits) — everything we need except pow_factor.
    code, out = _run_miraged(
        ["q", "core", "difficulty", "--home", "/root/.mirage/node", "--node", "tcp://127.0.0.1:26657", "-o", "json"],
        timeout=10,
    )
    if code == 0 and out:
        data = _parse_cli_json(out)
        if data:
            lb = str(data.get("latest_block_hash", "") or "").strip().lower()
            raw_diff = data.get("current_difficulty")
            base_bits = int(data.get("min_difficulty", 0) or 0)
            if lb and raw_diff is not None and base_bits > 0:
                try:
                    params = _get_chain_params()
                    pow_factor = float(params.get("pow_difficulty_step", 0) or 0)
                except Exception:
                    pow_factor = 0.0
                if pow_factor <= 0:
                    st = get_status(backend, address=address)
                    pow_factor = float(st.get("pow_factor", 0.25) or 0.25)
                return lb, int(raw_diff), base_bits, pow_factor

    # Fallback: use the backend HTTP endpoint.
    st = get_status(backend, address=address)
    lb = str(st.get("last_block_hash", "") or "")
    diff = int(st.get("pow_difficulty", 0) or 0)
    base_bits = int(st.get("pow_base_bits", 0) or 0)
    pow_factor = float(st.get("pow_factor", 0.25) or 0.25)
    if not lb:
        raise RuntimeError("missing last_block_hash from get_status")
    return lb, diff, base_bits, pow_factor


def _get_profile_full(backend: str, address: str) -> dict:
    r = _request_with_retries("GET", f"{backend}/api/get_profile", params={"address": address}, timeout=10)
    r.raise_for_status()
    return r.json() or {}


def _wait_profile_agents(backend: str, address: str, expected: list[str]) -> list[str]:
    """Poll get_profile until enabled_agents matches expected, and return what was last seen.

    get_profile is served from the indexer, which processes blocks asynchronously, so a
    delivered SetAgents is not visible the instant the tx lands.
    """
    want = [a.lower() for a in expected]
    got = []
    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    while time.perf_counter() < deadline:
        profile = _get_profile_full(backend, address)
        got = [str(a).lower() for a in (profile.get("enabled_agents") or [])]
        if got == want:
            return got
        time.sleep(1)
    return got


def _get_chain_profile(address: str) -> dict:
    """Query the chain directly for a profile (bypasses indexer)."""
    code, out = _run_miraged(
        [
            "q",
            "core",
            "profile",
            address.lower(),
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
        raise RuntimeError(f"failed to query chain profile: {out[:200]}")
    data = _parse_cli_json(out)
    if not data:
        raise RuntimeError(f"chain profile query: no JSON in output: {out[:200]}")
    return data


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
    *,
    sign_outer: bool = True,
    outer_sig: Optional[bytes] = None,
    unordered: bool = False,
    memo: str = "",
) -> bytes:
    """Build TxRaw. By default signs unordered outer tx with validator key (C-1).

    Set sign_outer=False only for negative tests that assert rejection of
    placeholder signatures / unauthorized fee payers. In that mode outer_sig
    overrides the 1-byte placeholder (use a 64-byte forgery to force the chain
    all the way into signature verification), and unordered=True adds the
    unordered/timeout_timestamp body fields the real signed path uses.

    memo mirrors what the relaying backend attaches for network tags. It is set
    on the TxBody here rather than appended as raw wire bytes: the backend has
    to append because cosmpy's TxBody predates the unordered fields, but a test
    building the body from scratch has no such constraint, and going through the
    proto is what proves the field survives signing and the ante chain.
    """
    any_msgs: list[AnyPB] = []
    for msg, type_url in msgs:
        any_msg = AnyPB()
        any_msg.type_url = type_url
        any_msg.value = msg.SerializeToString()
        any_msgs.append(any_msg)
    body = TxBody(messages=any_msgs, memo=memo)
    body_bytes = body.SerializeToString()

    if fee_amount is None:
        min_gas_price = _min_gas_price_umirage()
        fee_amount = int(math.ceil(int(gas_limit) * min_gas_price))
    fee = Fee(gas_limit=int(gas_limit))
    fee.amount.append(Coin(denom=fee_denom, amount=str(int(fee_amount))))
    fee.payer = fee_payer

    mode = ModeInfo(single=ModeInfo.Single(mode=SignMode.SIGN_MODE_DIRECT))
    outer_pub = signer_pubkey
    if sign_outer:
        # Outer signer must be the gas payer (validator). Envelope pubkey is unrelated.
        from cosmpy.crypto.keypairs import PrivateKey as _Priv

        outer_pub = _Priv(_require_validator_privkey()).public_key.public_key_bytes
    signer_info = SignerInfo(public_key=_make_pubkey_any(outer_pub), mode_info=mode, sequence=0)
    auth = AuthInfo(signer_infos=[signer_info], fee=fee)
    auth_bytes = auth.SerializeToString()

    if not sign_outer:
        forged_body = _append_unordered_timeout(body_bytes, _unique_timeout_ns()) if unordered else body_bytes
        tx_raw = TxRaw(
            body_bytes=forged_body,
            auth_info_bytes=auth_bytes,
            signatures=[outer_sig if outer_sig is not None else b"\x00"],
        )
        return tx_raw.SerializeToString()

    timeout_ns = _unique_timeout_ns()
    signed_body = _append_unordered_timeout(body_bytes, timeout_ns)
    priv = _require_validator_privkey()
    chain_id = _require_chain_id()
    acc_num = _require_validator_account_number()
    sign_doc = SignDoc(
        body_bytes=signed_body,
        auth_info_bytes=auth_bytes,
        chain_id=chain_id,
        account_number=int(acc_num),
    )
    sig = _sign_sign_doc(priv, sign_doc.SerializeToString())
    tx_raw = TxRaw(body_bytes=signed_body, auth_info_bytes=auth_bytes, signatures=[sig])
    return tx_raw.SerializeToString()


def _unique_timeout_ns() -> int:
    now = time.time_ns()
    cand = now + _UNORDERED_TTL_NS + ((os.getpid() & 0xFFFF) << 16) + random.getrandbits(16)
    max_ns = now + 9 * 60 * 1_000_000_000
    if cand > max_ns:
        cand = max_ns - random.getrandbits(20)
    if cand <= now:
        cand = now + _UNORDERED_TTL_NS + random.getrandbits(20)
    return int(cand)


def _encode_varint(n: int) -> bytes:
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n & 0x7F)
    return bytes(out)


def _append_unordered_timeout(body_bytes: bytes, timeout_ns: int) -> bytes:
    unordered = b"\x20\x01"
    ts = Timestamp()
    ts.seconds = timeout_ns // 1_000_000_000
    ts.nanos = int(timeout_ns % 1_000_000_000)
    ts_bytes = ts.SerializeToString()
    timeout = b"\x2a" + _encode_varint(len(ts_bytes)) + ts_bytes
    return body_bytes + unordered + timeout


def _sign_sign_doc(privkey_bytes: bytes, sign_doc_bytes: bytes) -> bytes:
    priv_key_int = int.from_bytes(privkey_bytes, "big")
    priv_key = ec.derive_private_key(priv_key_int, ec.SECP256K1(), default_backend())
    sig_der = priv_key.sign(sign_doc_bytes, ec.ECDSA(hashes.SHA256()))
    sig = der_to_compact_sig(sig_der)
    if len(sig) != 64:
        raise RuntimeError(f"outer signature must be 64 bytes, got {len(sig)}")
    return sig


def _require_validator_privkey() -> bytes:
    global _VALIDATOR_PRIVKEY
    if _VALIDATOR_PRIVKEY is not None:
        return _VALIDATOR_PRIVKEY
    code, out = _run_miraged(
        [
            "keys",
            "export",
            "validator",
            "--unarmored-hex",
            "--unsafe",
            "-y",
            "--home",
            "/root/.mirage/node",
            "--keyring-backend",
            "test",
        ],
        timeout=10,
    )
    if code != 0:
        raise RuntimeError(f"validator privkey export failed: {out[:300]}")
    hex_key = ""
    for line in reversed((out or "").splitlines()):
        token = line.strip()
        if len(token) == 64 and all(c in "0123456789abcdefABCDEF" for c in token):
            hex_key = token
            break
    if not hex_key:
        raise RuntimeError(f"validator privkey export: no hex key in output: {(out or '')[:200]}")
    _VALIDATOR_PRIVKEY = bytes.fromhex(hex_key)
    return _VALIDATOR_PRIVKEY


def _require_chain_id() -> str:
    global _CHAIN_ID
    if _CHAIN_ID:
        return _CHAIN_ID
    # Prefer client.toml inside container; fall back to REST node_info.
    code, out = _docker_exec("grep -E '^chain-id' /root/.mirage/node/config/client.toml || true")
    if code == 0 and out and "=" in out:
        _CHAIN_ID = out.split("=", 1)[1].strip().strip('"').strip("'")
        if _CHAIN_ID:
            return _CHAIN_ID
    resp = requests.get(f"{COMET_RPC_URL}/status", timeout=5).json()
    _CHAIN_ID = str(resp["result"]["node_info"]["network"])
    if not _CHAIN_ID:
        raise RuntimeError("chain_id unresolved")
    return _CHAIN_ID


def _require_validator_account_number() -> int:
    global _VALIDATOR_ACCOUNT_NUMBER
    if _VALIDATOR_ACCOUNT_NUMBER is not None:
        return _VALIDATOR_ACCOUNT_NUMBER
    if not _VALIDATOR_ADDR:
        raise RuntimeError("validator address not set")
    url = f"http://127.0.0.1:80/chain/rest/cosmos/auth/v1beta1/accounts/{_VALIDATOR_ADDR}"
    resp = requests.get(url, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"account query failed: {resp.status_code} {resp.text[:200]}")
    acc = resp.json().get("account") or {}
    if "base_account" in acc:
        acc = acc["base_account"] or {}
    _VALIDATOR_ACCOUNT_NUMBER = int(acc["account_number"])
    return _VALIDATOR_ACCOUNT_NUMBER


_SIMULATE_PY = """import base64
import os
import tomllib
import grpc
from cosmpy.protos.cosmos.tx.v1beta1.service_pb2 import SimulateRequest
from cosmpy.protos.cosmos.tx.v1beta1.service_pb2_grpc import ServiceStub

tx_bytes = base64.b64decode(os.environ["TX_B64"])
home = os.path.join(os.path.expanduser("~"), ".mirage", "node")
path = os.path.join(home, "config", "app.toml")
if not os.path.isfile(path):
    raise SystemExit("app.toml not found: " + path)
with open(path, "rb") as f:
    data = tomllib.load(f)
addr = str((data.get("grpc") or {}).get("address") or "").strip()
if not addr:
    raise SystemExit("grpc.address missing in app.toml")
parts = addr.rsplit(":", 1)
if len(parts) != 2:
    raise SystemExit("invalid grpc.address: " + addr)
host, port = parts[0].strip(), parts[1].strip()
if host in ("0.0.0.0", "localhost"):
    host = "127.0.0.1"
target = host + ":" + port
ch = grpc.insecure_channel(target)
stub = ServiceStub(ch)
resp = stub.Simulate(SimulateRequest(tx_bytes=tx_bytes), timeout=10)
gas_used = int(getattr(getattr(resp, "gas_info", None), "gas_used", 0) or 0)
if gas_used <= 0:
    raise SystemExit("simulate returned gas_used=0")
print(gas_used)
"""


def _simulate_tx_bytes_gas(tx_bytes: bytes, timeout: int = 10) -> int:
    global _SIMULATE_MODE_LOGGED
    if _INSIDE_CONTAINER:
        if not _SIMULATE_MODE_LOGGED:
            _debug("simulate: using local gRPC")
            _SIMULATE_MODE_LOGGED = True
        stub = ServiceStub(_get_grpc_channel())
        resp = stub.Simulate(SimulateRequest(tx_bytes=tx_bytes), timeout=timeout)
        gas_used = int(getattr(getattr(resp, "gas_info", None), "gas_used", 0) or 0)
        if gas_used <= 0:
            raise RuntimeError("simulate returned gas_used=0")
        return gas_used

    if not _SIMULATE_MODE_LOGGED:
        _debug("simulate: using docker exec")
        _SIMULATE_MODE_LOGGED = True
    tx_b64 = base64.b64encode(tx_bytes).decode()
    cmd = f"TX_B64='{tx_b64}' python3 - <<'PY'\n{_SIMULATE_PY}\nPY"
    code, out = _docker_exec(cmd, timeout=timeout)
    if code != 0:
        raise RuntimeError(f"simulate failed: {out}")
    try:
        return int(out.strip())
    except Exception:
        raise RuntimeError(f"simulate returned non-integer: {out}")


def _simulate_tx_gas(
    msgs: list[tuple[object, str]],
    gas_limit: int,
    fee_payer: str,
    signer_pubkey: bytes,
    fee_denom: str = "umirage",
    fee_amount: Optional[int] = None,
    timeout: int = 10,
) -> int:
    tx_bytes = _build_tx_bytes(msgs, gas_limit, fee_payer, signer_pubkey, fee_denom, fee_amount)
    return _simulate_tx_bytes_gas(tx_bytes, timeout=timeout)


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


def _synthesize_log_from_events(events: list) -> str:
    """Build a raw_log JSON string from CometBFT events when the log field is empty.

    Newer CometBFT versions omit the ``log`` field for successful txs but
    still populate ``events``.  This mirrors the indexer's synthesis logic.
    """
    decoded_events: list[dict] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        attrs_raw = ev.get("attributes") or []
        attrs: list[dict] = []
        for attr in attrs_raw:
            if not isinstance(attr, dict):
                continue
            k = attr.get("key", "")
            v = attr.get("value", "")
            try:
                k = base64.b64decode(k).decode() if k else ""
            except Exception:
                pass
            try:
                v = base64.b64decode(v).decode() if v else ""
            except Exception:
                pass
            attrs.append({"key": k, "value": v})
        decoded_events.append({"type": ev.get("type", ""), "attributes": attrs})
    if not decoded_events:
        return ""
    return json.dumps([{"events": decoded_events}])


def _wait_for_tx_result(tx_hash: str, timeout: float = 20.0) -> tuple[int, str]:
    """Wait for a tx to land in a block by scanning block_results (tx_index disabled).

    The budget is ~6 blocks at the 3s block time the local testnet now shares with
    the fleet. It was 10s when local ran at 2s, which is only 3 blocks at 3s and
    close enough to a single slow block to flake.
    """
    if not tx_hash:
        raise RuntimeError("missing tx_hash for wait")
    h = tx_hash.strip().upper().removeprefix("0X")
    start = time.monotonic()
    deadline = start + timeout

    # Get the current height as our scan starting point
    status_resp = requests.get(f"{COMET_RPC_URL}/status", timeout=5).json()
    last_height = int(status_resp["result"]["sync_info"]["latest_block_height"]) - 1

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        status_resp = requests.get(f"{COMET_RPC_URL}/status", timeout=min(3.0, remaining)).json()
        current_height = int(status_resp["result"]["sync_info"]["latest_block_height"])
        for height in range(last_height + 1, current_height + 1):
            # Fetch the block to get tx hashes
            block_resp = requests.get(f"{COMET_RPC_URL}/block?height={height}", timeout=5).json()
            txs = block_resp.get("result", {}).get("block", {}).get("data", {}).get("txs") or []
            tx_index_in_block = None
            for idx, tx_b64 in enumerate(txs):
                tx_bytes = base64.b64decode(tx_b64)
                if hashlib.sha256(tx_bytes).hexdigest().upper() == h:
                    tx_index_in_block = idx
                    break
            if tx_index_in_block is not None:
                # block_results may lag behind block data; retry until deadline
                while time.monotonic() < deadline:
                    br = requests.get(f"{COMET_RPC_URL}/block_results?height={height}", timeout=5).json()
                    deliver_txs = br.get("result", {}).get("txs_results") or []
                    if tx_index_in_block < len(deliver_txs):
                        tx_result = deliver_txs[tx_index_in_block]
                        code = int(tx_result.get("code", 0) or 0)
                        log = str(tx_result.get("log", "") or "")
                        if code == 0 and not log.strip():
                            log = _synthesize_log_from_events(tx_result.get("events") or [])
                        return code, log
                    time.sleep(0.5)
                raise RuntimeError(f"tx at height={height} idx={tx_index_in_block}: block_results never populated")
        last_height = current_height
        time.sleep(min(1.0, deadline - time.monotonic()))
    raise RuntimeError(f"tx not found in blocks after {timeout}s: {tx_hash}")


def _submit_tx(
    msgs: list[tuple[object, str]],
    gas_limit: int,
    fee_payer: str,
    signer_pubkey: bytes,
    fee_denom: str = "umirage",
    fee_amount: Optional[int] = None,
    wait_deliver: bool = False,
    memo: str = "",
) -> tuple[str, int, str, Optional[int], Optional[str]]:
    tx_bytes = _build_tx_bytes(msgs, gas_limit, fee_payer, signer_pubkey, fee_denom, fee_amount, memo=memo)
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
    nonce: int = 0,
    pub_override: Optional[bytes] = None,
    sig_override: Optional[bytes] = None,
    authority_override: Optional[str] = None,
    lb_override: Optional[str] = None,
    diff_override: Optional[int] = None,
) -> MsgPost:
    if not target:
        slug = str(topic or "").strip().lower()
        if slug:
            try:
                _claim_community("", slug)
            except Exception:
                pass
    pub = wallet.public_key().public_key_bytes
    d = diff if diff_override is None else diff_override
    lb_hex = lb_override or lb
    lb_bytes = _lb_bytes(lb_hex)
    base = _canon_base_post_raw(pub, lb_bytes, d, ts, target, topic, title, content, tag, 0, media or [], nonce=nonce)
    sig = sig_override or _sign_relay(wallet, base, pow_val)
    msg = MsgPost()
    msg.authority = authority_override or _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub_override or pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(d)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.target = target
    msg.community = topic
    msg.title = title
    msg.content = content
    msg.tag = tag
    msg.protocol_version = 1
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
    nonce: int = 0,
    sig_override: Optional[bytes] = None,
) -> MsgVote:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_vote_raw(pub, lb_bytes, diff, ts, target, direction, nonce=nonce)
    sig = sig_override or _sign_relay(wallet, base, pow_val)
    msg = MsgVote()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
) -> MsgSetUsername:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_set_username_raw(pub, lb_bytes, diff, ts, target, username, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgSetUsername()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.target = target
    msg.username = username
    return msg


def _build_msg_set_biography(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    biography: str,
    pow_val: int = 0,
    nonce: int = 0,
) -> MsgSetBiography:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_set_biography_raw(pub, lb_bytes, diff, ts, target, biography, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgSetBiography()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.target = target
    msg.biography = biography
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
    nonce: int = 0,
) -> MsgSendTokens:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_send_tokens_raw(pub, lb_bytes, diff, ts, sender, target, amount, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgSendTokens()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
) -> MsgDelete:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_delete_raw(pub, lb_bytes, diff, ts, target, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgDelete()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
) -> MsgDeleteUser:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_delete_user_raw(pub, lb_bytes, diff, ts, target, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgDeleteUser()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
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
    base = _canon_base_award_raw(pub, lb_bytes, d, ts, target, award_type, nonce=nonce)
    sig = sig_override or _sign_relay(wallet, base, pow_val)
    msg = MsgAward()
    msg.authority = authority_override or _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub_override or pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(d)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
) -> MsgEdit:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_edit_raw(
        pub, lb_bytes, diff, ts, target, topic, title, content, tag, override, media or [], nonce=nonce
    )
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgEdit()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.target = target
    msg.community = topic
    msg.title = title
    msg.content = content
    msg.tag = tag
    msg.override = override
    for m in media or []:
        msg.media.append(m)
    return msg


def _build_msg_annotate(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    topic: str,
    title: str,
    content: str,
    tag: str,
    override: str,
    media: Optional[list[str]] = None,
    appendix: str = "",
    pow_val: int = 0,
    nonce: int = 0,
) -> MsgAnnotate:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_annotate_raw(
        pub, lb_bytes, diff, ts, topic, title, content, tag, override, media=media or [], appendix=appendix, nonce=nonce
    )
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgAnnotate()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.topic = topic
    msg.title = title
    msg.content = content
    msg.tag = tag
    msg.override = override
    for m in media or []:
        msg.media.append(m)
    msg.appendix = appendix
    return msg


def _build_msg_block_post(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    pow_val: int = 0,
    nonce: int = 0,
) -> MsgBlockPost:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_block_post_raw(pub, lb_bytes, diff, ts, target, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgBlockPost()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
) -> MsgBlockUser:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_block_user_raw(pub, lb_bytes, diff, ts, target, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgBlockUser()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
) -> MsgBlockTopic:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_block_topic_raw(pub, lb_bytes, diff, ts, target, topic, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgBlockTopic()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.target = target
    msg.topic = topic
    return msg


def _build_msg_subscribe(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    level: int,
    target: str = "",
    pow_val: int = 0,
    nonce: int = 0,
) -> MsgSubscribe:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_subscribe_raw(pub, lb_bytes, diff, ts, level, target=target, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgSubscribe()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.level = int(level)
    msg.period_count = 1
    if target:
        msg.target = target
    return msg


def _build_msg_follow_user(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    user: str,
    pow_val: int = 0,
    nonce: int = 0,
) -> MsgFollowUser:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_follow_user_raw(pub, lb_bytes, diff, ts, target, user, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgFollowUser()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
) -> MsgUnfollowUser:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_unfollow_user_raw(pub, lb_bytes, diff, ts, target, user, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgUnfollowUser()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.target = target
    msg.user = user
    return msg


def _build_msg_join_community(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    community: str,
    pow_val: int = 0,
    nonce: int = 0,
) -> MsgJoinCommunity:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    slug = str(community or "").strip().lower()
    base = _canon_base_join_community_raw(pub, lb_bytes, diff, ts, slug, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgJoinCommunity()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.community = slug
    return msg


def _build_msg_leave_community(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    community: str,
    pow_val: int = 0,
    nonce: int = 0,
) -> MsgLeaveCommunity:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    slug = str(community or "").strip().lower()
    base = _canon_base_leave_community_raw(pub, lb_bytes, diff, ts, slug, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgLeaveCommunity()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.community = slug
    return msg


def _build_msg_block_community(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    community: str,
    pow_val: int = 0,
    nonce: int = 0,
) -> MsgBlockCommunity:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    slug = str(community or "").strip().lower()
    base = _canon_base_block_community_raw(pub, lb_bytes, diff, ts, target, slug, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgBlockCommunity()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.target = target
    msg.community = slug
    return msg


def _build_msg_unblock_community(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    community: str,
    pow_val: int = 0,
    nonce: int = 0,
) -> MsgUnblockCommunity:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    slug = str(community or "").strip().lower()
    base = _canon_base_unblock_community_raw(pub, lb_bytes, diff, ts, target, slug, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgUnblockCommunity()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.target = target
    msg.community = slug
    return msg


def _build_msg_create_community(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    community: str,
    pow_val: int = 0,
    nonce: int = 0,
    title: str = "",
    description: str = "test community",
    original_team_name: str = "orig",
    bio: str = "bio",
    policy: str = "policy",
) -> MsgCreateCommunity:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    slug = str(community or "").strip().lower()
    title = title or slug
    base = _canon_base_create_community_raw(
        pub, lb_bytes, diff, ts, slug, title, description, original_team_name, bio, policy, nonce=nonce
    )
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgCreateCommunity()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.community = slug
    msg.title = title
    msg.description = description
    msg.original_team_name = original_team_name
    msg.bio = bio
    msg.policy = policy
    return msg


_CLAIMED_ON_CHAIN: set[str] = set()


def _claim_community(backend: str, slug: str) -> None:
    """CreateCommunity from sub1 so JoinCommunity(requireClaimed) can succeed."""
    from tests.common import WALLETS

    community = str(slug or "").strip().lower()
    if not community or community in _CLAIMED_ON_CHAIN:
        return
    claimer = WALLETS.get("sub1")
    if claimer is None:
        raise RuntimeError("sub1 wallet required to claim a community")
    addr = str(claimer.address())
    pub = claimer.public_key().public_key_bytes
    lb, _, _, _ = _get_pow_params(backend, addr)
    ts = _now_ms()
    nonce = _gen_nonce()
    msg = _build_msg_create_community(claimer, lb, 0, ts, community, pow_val=0, nonce=nonce)
    _, ccode, clog, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgCreateCommunity")],
        DEFAULT_GAS_LIMIT,
        _VALIDATOR_ADDR or "",
        pub,
        wait_deliver=True,
    )
    combined = f"{clog or ''} {dlog or ''}".lower()
    if ccode == 0 and dcode == 0:
        _CLAIMED_ON_CHAIN.add(community)
        return
    if "already" in combined:
        _CLAIMED_ON_CHAIN.add(community)
        return
    raise RuntimeError(f"claim community {community} failed check={ccode} deliver={dcode} log={combined[:200]}")


def _build_msg_follow_topic(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    topic: str,
    pow_val: int = 0,
    nonce: int = 0,
) -> MsgFollowTopic:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_follow_topic_raw(pub, lb_bytes, diff, ts, target, topic, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgFollowTopic()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
) -> MsgUnfollowTopic:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_unfollow_topic_raw(pub, lb_bytes, diff, ts, target, topic, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgUnfollowTopic()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
) -> MsgEnableAgent:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_enable_agent_raw(pub, lb_bytes, diff, ts, target, agent, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgEnableAgent()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
) -> MsgDisableAgent:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_disable_agent_raw(pub, lb_bytes, diff, ts, target, agent, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgDisableAgent()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.target = target
    msg.agent = agent
    return msg


def _build_msg_set_agents(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    agents: list[str],
    pow_val: int = 0,
    nonce: int = 0,
) -> MsgSetAgents:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_set_agents_raw(pub, lb_bytes, diff, ts, target, agents, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgSetAgents()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.target = target
    for a in agents:
        msg.agents.append(a)
    return msg


def _build_msg_unblock_post(
    wallet: LocalWallet,
    lb: str,
    diff: int,
    ts: int,
    target: str,
    pow_val: int = 0,
    nonce: int = 0,
) -> MsgUnblockPost:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_unblock_post_raw(pub, lb_bytes, diff, ts, target, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgUnblockPost()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
) -> MsgUnblockUser:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_unblock_user_raw(pub, lb_bytes, diff, ts, target, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgUnblockUser()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
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
    nonce: int = 0,
) -> MsgUnblockTopic:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_unblock_topic_raw(pub, lb_bytes, diff, ts, target, topic, nonce=nonce)
    sig = _sign_relay(wallet, base, pow_val)
    msg = MsgUnblockTopic()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = int(diff)
    msg.envelope_pow = int(pow_val)
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.target = target
    msg.topic = topic
    return msg


def _build_msg_set_auto_renewal(
    wallet: LocalWallet,
    lb: str,
    ts: int,
    auto_renew: bool,
    nonce: int = 0,
) -> MsgSetAutoRenewal:
    pub = wallet.public_key().public_key_bytes
    lb_bytes = _lb_bytes(lb)
    base = _canon_base_set_auto_renewal_raw(pub, lb_bytes, 0, ts, auto_renew, nonce=nonce)
    sig = _sign_relay(wallet, base, 0)
    msg = MsgSetAutoRenewal()
    msg.authority = _VALIDATOR_ADDR or ""
    msg.envelope_pubkey = pub
    msg.envelope_block_hash = lb_bytes
    msg.envelope_difficulty = 0
    msg.envelope_pow = 0
    msg.envelope_timestamp = int(ts)
    msg.envelope_nonce = int(nonce)
    msg.envelope_signature = sig
    msg.auto_renew = auto_renew
    return msg


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


def _check_accept(name: str, code: int, log: str) -> None:
    """Check that a tx was accepted at CheckTx (code == 0)."""
    if code == 0:
        _pass(name)
    else:
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
    if not _VALIDATOR_ADDR:
        _fail("validator.funds", "validator address not set")
        return False
    required = _required_validator_fee_budget_umirage()
    balance = _query_spendable_umirage(_VALIDATOR_ADDR)
    if balance < required:
        _fail(
            "validator.funds",
            f"insufficient fee balance: have={balance} need={required} "
            f"({balance / 1_000_000:,.0f} MIRAGE < {required / 1_000_000:,.0f} MIRAGE)",
        )
        return False
    _debug(f"validator spendable={balance / 1_000_000:,.0f} MIRAGE (ok)")
    return True
