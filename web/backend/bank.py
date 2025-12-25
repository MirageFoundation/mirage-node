from __future__ import annotations

from typing import Optional, List, Tuple

import grpc as _grpc
from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2 as bank_query_pb2
from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2_grpc as bank_query_pb2_grpc

from node import require_runtime


def get_balance(address: Optional[str]) -> int:
    if not address:
        return 0
    try:
        target = require_runtime().grpc_target
        with _grpc.insecure_channel(target) as ch:
            stub = bank_query_pb2_grpc.QueryStub(ch)
            req = bank_query_pb2.QueryBalanceRequest(address=str(address), denom="umirage")
            resp = stub.Balance(req)
            amt = (resp.balance.amount if resp and resp.balance else "0") or "0"
            try:
                return int(amt)
            except Exception:
                return 0
    except Exception:
        return 0


def get_total_supply() -> int:
    """Get total supply of umirage tokens from the chain."""
    try:
        target = require_runtime().grpc_target
        with _grpc.insecure_channel(target) as ch:
            stub = bank_query_pb2_grpc.QueryStub(ch)
            req = bank_query_pb2.QuerySupplyOfRequest(denom="umirage")
            resp = stub.SupplyOf(req)
            amt = (resp.amount.amount if resp and resp.amount else "0") or "0"
            try:
                return int(amt)
            except Exception:
                return 0
    except Exception:
        return 0


def get_balances_batch(addresses: List[str]) -> List[Tuple[str, int]]:
    """Get balances for multiple addresses. Returns list of (address, balance) tuples."""
    results = []
    target = require_runtime().grpc_target
    try:
        with _grpc.insecure_channel(target) as ch:
            stub = bank_query_pb2_grpc.QueryStub(ch)
            for addr in addresses:
                try:
                    req = bank_query_pb2.QueryBalanceRequest(address=str(addr), denom="umirage")
                    resp = stub.Balance(req)
                    amt = (resp.balance.amount if resp and resp.balance else "0") or "0"
                    results.append((addr, int(amt)))
                except Exception:
                    results.append((addr, 0))
    except Exception:
        for addr in addresses:
            results.append((addr, 0))
    return results


__all__ = ["get_balance", "get_total_supply", "get_balances_batch"]
