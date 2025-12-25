from __future__ import annotations

"""Transaction helpers: gas estimation, simulation, and broadcasting.

Functions:
- estimate_total_gas_limit(body_bytes, content_len): Heuristic gas estimator.
- build_tx_bytes(body_bytes, gas_limit): Construct TxRaw bytes with payer.
- simulate_gas(tx_bytes): gRPC Simulate to get gas_used.
- broadcast_tx(tx_bytes): Broadcast async (fire-and-forget); returns (tx_hash, code, height, raw_log).
"""

from typing import Tuple
import hashlib as _hashlib
import math as _math

import grpc as _grpc
from google.protobuf.any_pb2 import Any as AnyPB
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody, AuthInfo, Fee, TxRaw, SignerInfo, ModeInfo
from cosmpy.protos.cosmos.tx.signing.v1beta1.signing_pb2 import SignMode
from cosmpy.protos.cosmos.base.v1beta1.coin_pb2 import Coin
from cosmpy.protos.cosmos.tx.v1beta1.service_pb2 import BroadcastTxRequest, BroadcastMode, SimulateRequest
from cosmpy.protos.cosmos.tx.v1beta1.service_pb2_grpc import ServiceStub
from cosmpy.protos.cosmos.auth.v1beta1 import query_pb2 as auth_query_pb2
from cosmpy.protos.cosmos.auth.v1beta1 import query_pb2_grpc as auth_query_pb2_grpc

from node import min_gas_price_umirage, require_runtime


def estimate_total_gas_limit(body_bytes: bytes, content_len: int) -> int:
    base_required = 0
    tx_size_ppb = _get_tx_size_cost_per_byte()
    min_gas_price = min_gas_price_umirage(require_runtime().node_id)

    def _txraw_len(gas_lim: int) -> int:
        fee_amt = int(_math.ceil(gas_lim * min_gas_price))
        fee = Fee(gas_limit=int(gas_lim))
        fee.amount.extend([Coin(denom="umirage", amount=str(fee_amt))])
        fee.payer = require_runtime().validator_payer_addr
        pub_any = AnyPB()
        pub_any.Pack(_secp_pubkey())
        pub_any.type_url = "/cosmos.crypto.secp256k1.PubKey"
        mode = ModeInfo(single=ModeInfo.Single(mode=SignMode.SIGN_MODE_DIRECT))
        si = SignerInfo(public_key=pub_any, mode_info=mode, sequence=0)
        auth = AuthInfo(signer_infos=[si], fee=fee)
        tx_raw = TxRaw(
            body_bytes=body_bytes, auth_info_bytes=auth.SerializeToString(), signatures=[b"\x00"]
        )  # placeholder
        return len(tx_raw.SerializeToString())

    gas_guess = max(base_required, 1)
    for _ in range(2):
        size_gas = tx_size_ppb * _txraw_len(int(gas_guess))
        store_gas = 1000 + 2000 + (30 * max(0, int(content_len)))
        new_gas = base_required + size_gas + store_gas + 1024
        if new_gas % 64 != 0:
            new_gas = ((new_gas + 63) // 64) * 64
        if abs(new_gas - gas_guess) <= 1:
            gas_guess = new_gas
            break
        gas_guess = new_gas
    return int(gas_guess)


def build_tx_bytes(body_bytes: bytes, gas_limit: int) -> bytes:
    min_gas_price = min_gas_price_umirage(require_runtime().node_id)
    fee_amt = int(_math.ceil(int(gas_limit) * min_gas_price))
    fee = Fee(gas_limit=int(gas_limit))
    fee.amount.extend([Coin(denom="umirage", amount=str(fee_amt))])
    fee.payer = require_runtime().validator_payer_addr

    validator_addr = require_runtime().validator_payer_addr
    sequence = get_account_sequence(validator_addr)

    pub_any = AnyPB()
    pub_any.Pack(_secp_pubkey())
    pub_any.type_url = "/cosmos.crypto.secp256k1.PubKey"
    mode = ModeInfo(single=ModeInfo.Single(mode=SignMode.SIGN_MODE_DIRECT))
    si = SignerInfo(public_key=pub_any, mode_info=mode, sequence=sequence)
    auth = AuthInfo(signer_infos=[si], fee=fee)
    return TxRaw(
        body_bytes=body_bytes, auth_info_bytes=auth.SerializeToString(), signatures=[b"\x00"]
    ).SerializeToString()


def simulate_gas(tx_bytes: bytes) -> int:
    target = require_runtime().grpc_target
    with _grpc.insecure_channel(target) as ch:
        stub = ServiceStub(ch)
        req = SimulateRequest(tx_bytes=tx_bytes)
        resp = stub.Simulate(req)
        return int(getattr(getattr(resp, "gas_info", None), "gas_used", 0) or 0)


def broadcast_tx(tx_bytes: bytes) -> Tuple[str, int, int, str]:
    """Broadcast transaction asynchronously (fire-and-forget).
    
    The tx_hash is computed deterministically from the transaction bytes,
    so we don't need to wait for the node's response to know it.
    """
    tx_hash = _hashlib.sha256(tx_bytes).hexdigest().lower()
    target = require_runtime().grpc_target
    try:
        with _grpc.insecure_channel(target) as ch:
            stub = ServiceStub(ch)
            req = BroadcastTxRequest(tx_bytes=tx_bytes, mode=BroadcastMode.BROADCAST_MODE_ASYNC)
            stub.BroadcastTx(req)
            return tx_hash, 0, 0, ""
    except Exception as e:
        return tx_hash, 1, 0, str(e)


def _get_tx_size_cost_per_byte() -> int:
    """Fetch tx_size_cost_per_byte from chain via gRPC (auth module params)."""
    target = require_runtime().grpc_target
    try:
        with _grpc.insecure_channel(target) as ch:
            stub = auth_query_pb2_grpc.QueryStub(ch)
            req = auth_query_pb2.QueryParamsRequest()
            resp = stub.Params(req)
            params = getattr(resp, "params", None)
            value = getattr(params, "tx_size_cost_per_byte", 0) if params is not None else 0
            v = int(value or 0)
            if v <= 0:
                return 10
            return v
    except Exception:
        return 10


def _secp_pubkey():
    from cosmpy.protos.cosmos.crypto.secp256k1.keys_pb2 import PubKey as SecpPubKey

    return SecpPubKey(key=require_runtime().validator_pubkey_bytes)


def get_account_info(address: str) -> tuple[int, int]:
    """Query the account sequence and account number from the chain.
    Returns (account_number, sequence).
    """
    target = require_runtime().grpc_target
    try:
        with _grpc.insecure_channel(target) as ch:
            stub = auth_query_pb2_grpc.QueryStub(ch)
            req = auth_query_pb2.QueryAccountRequest(address=str(address))
            resp = stub.Account(req)
            account = resp.account
            if account.type_url == "/cosmos.auth.v1beta1.BaseAccount":
                from cosmpy.protos.cosmos.auth.v1beta1.auth_pb2 import BaseAccount
                base_account = BaseAccount()
                account.Unpack(base_account)
                return int(base_account.account_number), int(base_account.sequence)
            elif account.type_url == "/ethermint.types.v1.EthAccount":
                from cosmpy.protos.ethermint.types.v1.account_pb2 import EthAccount
                eth_account = EthAccount()
                account.Unpack(eth_account)
                return int(eth_account.base_account.account_number), int(eth_account.base_account.sequence)
            else:
                return 0, 0
    except Exception:
        return 0, 0


def get_account_sequence(address: str) -> int:
    """Query the account sequence number from the chain."""
    _, sequence = get_account_info(address)
    return sequence


__all__ = [
    "estimate_total_gas_limit",
    "build_tx_bytes",
    "simulate_gas",
    "broadcast_tx",
]
