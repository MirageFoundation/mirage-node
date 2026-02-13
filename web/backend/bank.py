from __future__ import annotations

from typing import Optional, List, Tuple

from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2 as bank_query_pb2
from cosmpy.protos.cosmos.bank.v1beta1 import query_pb2_grpc as bank_query_pb2_grpc

from node import get_grpc_channel


# Validator info cache (moniker, tokens, status) — keyed by valoper address.
# Cached permanently (until restart); moniker changes require MsgEditValidator.
_VALIDATOR_CACHE: dict[str, dict] = {}


def get_balance(address: Optional[str]) -> int:
    if not address:
        return 0
    try:
        stub = bank_query_pb2_grpc.QueryStub(get_grpc_channel())
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
        stub = bank_query_pb2_grpc.QueryStub(get_grpc_channel())
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
    try:
        stub = bank_query_pb2_grpc.QueryStub(get_grpc_channel())
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


def get_staked_balance(address: Optional[str]) -> int:
    """Get total staked (delegated) umirage for an address via gRPC."""
    if not address:
        return 0
    try:
        from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2 as staking_query_pb2
        from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2_grpc as staking_query_pb2_grpc

        total = 0
        stub = staking_query_pb2_grpc.QueryStub(get_grpc_channel())
        req = staking_query_pb2.QueryDelegatorDelegationsRequest(delegator_addr=str(address))
        resp = stub.DelegatorDelegations(req)
        for dr in resp.delegation_responses or []:
            amt = (dr.balance.amount if dr and dr.balance else "0") or "0"
            try:
                total += int(amt)
            except (ValueError, TypeError):
                pass
        return total
    except Exception:
        return 0


def get_validator(valoper: str) -> dict:
    """Get a single validator's info by operator address via gRPC.

    Returns dict with 'moniker', 'tokens', etc. Empty dict on failure.
    Cached permanently per valoper address (until process restart).
    """
    if not valoper:
        return {}

    cached = _VALIDATOR_CACHE.get(valoper)
    if cached is not None:
        return cached

    try:
        from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2 as staking_query_pb2
        from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2_grpc as staking_query_pb2_grpc

        stub = staking_query_pb2_grpc.QueryStub(get_grpc_channel())
        req = staking_query_pb2.QueryValidatorRequest(validator_addr=str(valoper))
        resp = stub.Validator(req)
        v = resp.validator
        if not v:
            return {}
        result = {
            "moniker": v.description.moniker if v.description else "",
            "tokens": str(v.tokens) if v.tokens else "0",
            "status": int(v.status),
        }
        _VALIDATOR_CACHE[valoper] = result
        return result
    except Exception:
        return {}


def get_all_validators() -> list[dict]:
    """Get all validators via gRPC.

    Returns list of dicts with 'moniker', 'consensus_pubkey', etc.
    """
    try:
        from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2 as staking_query_pb2
        from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2_grpc as staking_query_pb2_grpc
        import base64

        results = []
        stub = staking_query_pb2_grpc.QueryStub(get_grpc_channel())
        req = staking_query_pb2.QueryValidatorsRequest()
        resp = stub.Validators(req)
        for v in resp.validators or []:
            pubkey_b64 = ""
            if v.consensus_pubkey and v.consensus_pubkey.value:
                # The value is a protobuf-encoded ed25519 key; extract raw bytes
                raw = v.consensus_pubkey.value
                # Skip the protobuf prefix (first 2 bytes: field tag + length)
                if len(raw) > 2:
                    pubkey_b64 = base64.b64encode(raw[2:]).decode("ascii")
            moniker = v.description.moniker if v.description else ""
            if pubkey_b64 and moniker:
                results.append({"consensus_pubkey": pubkey_b64, "moniker": moniker})
        return results
    except Exception:
        return []


__all__ = [
    "get_balance",
    "get_total_supply",
    "get_balances_batch",
    "get_staked_balance",
    "get_validator",
    "get_all_validators",
]
