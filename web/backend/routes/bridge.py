from __future__ import annotations

"""Bridge relay endpoints for IBC and attested transfers.

Endpoints:
- POST /api/bridge/ibc_transfer: Relay IBC transfer to Cosmos chains (e.g., Osmosis)
- POST /api/bridge/burn: Relay burn for attested bridge to non-IBC chains (e.g., Solana)
- GET /api/bridge/config: Get bridge configuration (enabled chains, fees)
- GET /api/bridge/status: Get bridge status (pending transfers)
- GET /api/bridge/get_minted: Query outbound mint confirmation by burn_id
"""

import base64
import os
from typing import Any, Dict

from flask import Blueprint, jsonify, request
from google.protobuf.any_pb2 import Any as AnyPB
from google.protobuf.json_format import MessageToDict
import grpc as _grpc
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody

from bech32 import bech32_decode, convertbits  # type: ignore

from shared.datatypes import (
    MsgIBCTransfer,
    MsgBridgeBurn,
    QueryBridgeMintedRequest,
    QueryBridgeMintedResponse,
)
from shared.canon import canon_signed_with_pow

from logging_utils import log_event, next_request_id
from node import derive_address_from_pubkey, require_runtime
from params import expect_params
from pow import canon_base_ibc_transfer, canon_base_bridge_burn
from tx import estimate_total_gas_limit, build_tx_bytes, simulate_gas, broadcast_tx
from chain import classify_reject, get_current_pow_difficulty, is_node_catching_up, is_valid_recent_block_hash

# Import shared helpers from core module
from routes.core import is_subscriber, _verify_signature, get_user_level, _hex_to_bytes, GAS_BUFFER_MULTIPLIER


bridge_bp = Blueprint("bridge", __name__)

_MAX_ADDR_LEN = 128
_MAX_CHAIN_LEN = 64
_MAX_CHANNEL_LEN = 64
_MAX_BLOCKHASH_HEX_LEN = 128


def _client_ip() -> str:
    ip_raw = request.headers.get("X-Forwarded-For", request.headers.get("X-Real-IP", request.remote_addr or ""))
    return (ip_raw.split(",")[0].strip() if ip_raw else "").strip()


def _is_private_ip(ip: str) -> bool:
    if not ip:
        return False
    if ip in ("127.0.0.1", "::1", "localhost"):
        return True
    # Basic RFC1918 checks for IPv4
    try:
        parts = [int(p) for p in ip.split(".")]
        if len(parts) != 4:
            return False
    except ValueError:
        return False
    if parts[0] == 10:
        return True
    if parts[0] == 192 and parts[1] == 168:
        return True
    if parts[0] == 172 and 16 <= parts[1] <= 31:
        return True
    return False


def _query_bridge_minted(burn_id: str, timeout: float = 3.0) -> dict:
    def _deserialize(data: bytes) -> QueryBridgeMintedResponse:
        msg = QueryBridgeMintedResponse()
        msg.ParseFromString(data)
        return msg

    target = require_runtime().grpc_target
    with _grpc.insecure_channel(target) as channel:
        method = channel.unary_unary(
            "/mirage.core.v1.Query/GetBridgeMinted",
            request_serializer=lambda msg: msg.SerializeToString(),
            response_deserializer=_deserialize,
        )
        resp = method(QueryBridgeMintedRequest(burn_id=burn_id), timeout=timeout)
    return MessageToDict(resp, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)


def _base58_decode(s: str) -> bytes:
    """Minimal base58 decode (Bitcoin alphabet). Raises ValueError on invalid input."""
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    idx = {c: i for i, c in enumerate(alphabet)}
    n = 0
    for ch in s:
        v = idx.get(ch)
        if v is None:
            raise ValueError("invalid base58 character")
        n = n * 58 + v
    full = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = 0
    for ch in s:
        if ch == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + full


def _validate_bech32_20(addr: str, expected_hrp: str | None = None) -> bool:
    hrp, data5 = bech32_decode(addr)
    if not hrp or not data5:
        return False
    if expected_hrp is not None and hrp != expected_hrp:
        return False
    data8 = convertbits(data5, 5, 8, False)
    if not data8:
        return False
    return len(bytes(data8)) == 20


def _resolve_enabled_ibc_chain(source_channel: str) -> Dict[str, Any] | None:
    """Return enabled IBC chain config matching channel, else None."""
    p = expect_params()
    for c in p.get("bridge_chains", []) or []:
        try:
            if not c.get("enabled", False):
                continue
            if not c.get("is_ibc", False):
                continue
            if str(c.get("ibc_channel", "")).strip() == source_channel:
                return c
        except Exception:
            continue
    return None


def _resolve_enabled_attested_chain(chain_id: str) -> Dict[str, Any] | None:
    """Return enabled non-IBC chain config matching chain_id (case-insensitive), else None."""
    want = (chain_id or "").strip().lower()
    if not want:
        return None
    p = expect_params()
    for c in p.get("bridge_chains", []) or []:
        try:
            if not c.get("enabled", False):
                continue
            if c.get("is_ibc", False):
                continue
            if str(c.get("chain_id", "")).strip().lower() == want:
                return c
        except Exception:
            continue
    return None


def _expected_receiver_hrp(chain_cfg: Dict[str, Any] | None) -> str | None:
    if not chain_cfg:
        return None
    cid = str(chain_cfg.get("chain_id", "")).strip().lower()
    if cid == "osmosis" or "osmosis" in cid:
        return "osmo"
    return None


def _tx_error(
    rid: str,
    endpoint: str,
    msg_type: str,
    code: int,
    tx_hash: str,
    raw_log: str,
    extra: Dict[str, Any] | None = None,
):
    """Standardized error payload for failed chain broadcasts."""
    info = classify_reject(raw_log)
    if extra:
        try:
            info.update(extra)
        except Exception:
            pass
    info.setdefault("code", code)
    info.setdefault("tx_type", msg_type)
    info.setdefault("endpoint", endpoint)
    info.setdefault("tx_hash", tx_hash)
    message = (info.get("message") or "").strip() or "rejected"
    log_event(
        rid,
        f"{endpoint}.reject",
        code=code,
        tx_hash=tx_hash,
        height=extra.get("height") if isinstance(extra, dict) else None,
        raw_log=raw_log,
        details=info,
    )
    return jsonify({"error": message, **info}), 400


@bridge_bp.route("/api/bridge/config", methods=["GET"])
def bridge_config():
    """Return bridge configuration (enabled chains, fees, etc.)."""
    rid = next_request_id()
    log_event(rid, "bridge_config.begin")
    try:
        p = expect_params()
        bridge_chains = p["bridge_chains"]  # Required, fail if missing

        # Derive Solana cluster from RPC URL: contains "devnet" -> devnet, "testnet" -> testnet, else mainnet
        solana_rpc = os.environ.get("ORCHESTRATOR_SOLANA_RPC", "").lower()
        if "devnet" in solana_rpc:
            solana_cluster = "devnet"
        elif "testnet" in solana_rpc:
            solana_cluster = "testnet"
        else:
            solana_cluster = "mainnet"

        # Format chains for frontend - each chain must have fee
        chains = []
        for chain in bridge_chains:
            chain_id = chain["chain_id"]
            fee_umirage = int(chain["fee"])  # Required per-chain fee
            entry = {
                "chain_id": chain_id,
                "enabled": chain["enabled"],
                "is_ibc": chain.get("is_ibc", False),
                "ibc_channel": chain.get("ibc_channel", ""),
                "fee_umirage": fee_umirage,
                "fee_mirage": fee_umirage / 1_000_000,
            }
            if chain_id == "solana":
                entry["solana_cluster"] = solana_cluster
            chains.append(entry)

        return jsonify({"chains": chains})
    except Exception as e:
        log_event(rid, "bridge_config.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@bridge_bp.route("/api/bridge/get_minted", methods=["GET"])
def get_bridge_minted():
    """Query outbound bridge mint confirmation by burn_id."""
    rid = next_request_id()
    burn_id = (request.args.get("burn_id") or "").strip().lower()
    log_event(rid, "get_bridge_minted.begin", burn_id=burn_id)

    if not burn_id:
        return jsonify({"error": "burn_id required"}), 400

    client_ip = _client_ip()
    if not _is_private_ip(client_ip):
        log_event(rid, "get_bridge_minted.forbidden", ip=client_ip, burn_id=burn_id)
        return jsonify({"error": "forbidden"}), 403

    try:
        result = _query_bridge_minted(burn_id)
        log_event(
            rid,
            "get_bridge_minted.ok",
            burn_id=burn_id,
            minted=result.get("minted", False),
            destination_chain=result.get("destination_chain"),
        )
        return jsonify(result)
    except Exception as e:
        log_event(rid, "get_bridge_minted.err", burn_id=burn_id, error=str(e))
        return jsonify({"error": str(e)}), 500


@bridge_bp.route("/api/bridge/ibc_transfer", methods=["POST"])
def bridge_ibc_transfer():
    """Relay IBC transfer to a Cosmos chain (e.g., Osmosis).

    Required fields:
    - pubkey: Base64 encoded compressed public key
    - signature: Base64 encoded signature
    - last_block_hash: Recent block hash for relay/PoW
    - timestamp: Unix timestamp (seconds)
    - receiver: Destination address on target chain (e.g., osmo1...)
    - amount: Amount in umirage to transfer
    - source_channel: IBC channel ID (e.g., "channel-1")
    - timeout_seconds: Timeout in seconds (default: 600)

    Optional (for non-subscribers):
    - pow_difficulty: PoW difficulty
    - pow: PoW proof value
    """
    rid = next_request_id()
    log_event(rid, "ibc_transfer.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503

        data = request.get_json(force=True) or {}
        log_event(rid, "ibc_transfer.data", receiver=data.get("receiver"), amount=data.get("amount"))

        # Parse required fields
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()
        if len(last_block_hash) > _MAX_BLOCKHASH_HEX_LEN:
            return jsonify({"error": "last_block_hash too long"}), 400
        if len(last_block_hash) > _MAX_BLOCKHASH_HEX_LEN:
            return jsonify({"error": "last_block_hash too long"}), 400

        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400

        receiver = str(data.get("receiver", "")).strip()
        if not receiver:
            return jsonify({"error": "receiver required"}), 400
        if len(receiver) > _MAX_ADDR_LEN:
            return jsonify({"error": "receiver too long"}), 400

        try:
            amount = int(data.get("amount", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid amount"}), 400
        if amount <= 0:
            return jsonify({"error": "amount must be positive"}), 400

        source_channel = str(data.get("source_channel", "")).strip()
        if not source_channel:
            return jsonify({"error": "source_channel required"}), 400
        if len(source_channel) > _MAX_CHANNEL_LEN:
            return jsonify({"error": "source_channel too long"}), 400

        # Ensure the requested IBC channel is enabled (params-driven)
        chain_cfg = _resolve_enabled_ibc_chain(source_channel)
        if not chain_cfg:
            return jsonify({"error": "ibc channel not enabled"}), 400

        # Validate receiver format for known chains (bech32 checksum + 20-byte payload)
        expected_hrp = _expected_receiver_hrp(chain_cfg)
        if expected_hrp is not None and not _validate_bech32_20(receiver, expected_hrp):
            return jsonify({"error": f"invalid receiver address (expected {expected_hrp} bech32)"}), 400

        try:
            timeout_seconds = int(data.get("timeout_seconds", 600))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timeout_seconds"}), 400
        if timeout_seconds < 60:
            timeout_seconds = 60
        if timeout_seconds > 86400:  # Max 24 hours
            timeout_seconds = 86400

        try:
            difficulty = int(data.get("pow_difficulty", 0) or 0)
            proof = int(data.get("pow", 0) or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid pow fields"}), 400

        if not (pub_b64 and sig_b64):
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        validator_addr = require_runtime().validator_payer_addr

        # Check subscriber status for PoW requirement
        user_is_sub = is_subscriber(user_addr)
        if not user_is_sub:
            # Non-subscriber: require PoW
            if not (difficulty > 0 and proof):
                return jsonify({"error": "pow_required", "details": "Non-subscriber must provide valid PoW"}), 400
            required = get_current_pow_difficulty()
            if difficulty < required:
                return jsonify({"error": "insufficient pow (precheck)"}), 400
            if not is_valid_recent_block_hash(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
        else:
            # Subscriber: PoW not allowed
            if difficulty > 0 or proof > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400

        # Verify signature
        try:
            base = canon_base_ibc_transfer(
                pub_dec,
                last_block_hash,
                difficulty,
                timestamp,
                receiver,
                amount,
                source_channel,
                timeout_seconds,
            )
            signed = canon_signed_with_pow(base, proof)
            if not _verify_signature(pub_dec, sig_dec, signed):
                log_event(rid, "ibc_transfer.sig_fail", canonical_hex=signed.hex())
                return jsonify({"error": "invalid signature"}), 400
        except Exception as e:
            log_event(rid, "ibc_transfer.sig_exception", error=str(e))
            return jsonify({"error": "invalid signature"}), 400

        # Build and broadcast transaction
        msg = MsgIBCTransfer()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = difficulty
        msg.envelope_pow = proof
        msg.envelope_timestamp = timestamp
        msg.envelope_signature = sig_dec
        msg.receiver = receiver
        msg.amount = amount
        msg.source_channel = source_channel
        msg.timeout_seconds = timeout_seconds

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgIBCTransfer"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        content_len = len(receiver) + len(source_channel)
        gas_est = int(estimate_total_gas_limit(body_bytes, content_len))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)

        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "receiver": receiver,
                "amount": amount,
                "source_channel": source_channel,
            }
            return _tx_error(rid, "bridge/ibc_transfer", "MsgIBCTransfer", code, tx_hash, raw_log, extra)

        log_event(rid, "ibc_transfer.success", tx_hash=tx_hash, receiver=receiver, amount=amount)
        return jsonify({"tx_hash": tx_hash, "code": code, "height": height, "raw_log": raw_log})
    except Exception as e:
        log_event(rid, "ibc_transfer.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@bridge_bp.route("/api/bridge/burn", methods=["POST"])
def bridge_burn():
    """Relay burn for attested bridge to non-IBC chains (e.g., Solana).

    Required fields:
    - pubkey: Base64 encoded compressed public key
    - signature: Base64 encoded signature
    - last_block_hash: Recent block hash for relay/PoW
    - timestamp: Unix timestamp (seconds)
    - destination_chain: Target chain ID (e.g., "solana")
    - destination_address: Recipient address on target chain
    - amount: Amount in umirage to burn and bridge

    Optional (for non-subscribers):
    - pow_difficulty: PoW difficulty
    - pow: PoW proof value
    """
    rid = next_request_id()
    log_event(rid, "bridge_burn.begin")
    try:
        if is_node_catching_up():
            return jsonify({"error": "node_catching_up"}), 503

        data = request.get_json(force=True) or {}
        log_event(rid, "bridge_burn.data", dest_chain=data.get("destination_chain"), amount=data.get("amount"))

        # Parse required fields
        pub_b64 = str(data.get("pubkey", "")).strip()
        sig_b64 = str(data.get("signature", "")).strip()
        last_block_hash = str(data.get("last_block_hash", "")).strip()

        if "timestamp" not in data:
            return jsonify({"error": "timestamp required"}), 400
        try:
            timestamp = int(data.get("timestamp"))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid timestamp"}), 400

        destination_chain = str(data.get("destination_chain", "")).strip()
        if not destination_chain:
            return jsonify({"error": "destination_chain required"}), 400
        if len(destination_chain) > _MAX_CHAIN_LEN:
            return jsonify({"error": "destination_chain too long"}), 400
        destination_chain = destination_chain.lower()

        # Ensure destination chain is enabled (params-driven)
        if not _resolve_enabled_attested_chain(destination_chain):
            return jsonify({"error": "destination_chain not enabled"}), 400

        destination_address = str(data.get("destination_address", "")).strip()
        if not destination_address:
            return jsonify({"error": "destination_address required"}), 400
        if len(destination_address) > _MAX_ADDR_LEN:
            return jsonify({"error": "destination_address too long"}), 400

        # Chain-specific validation (tight for Solana)
        if destination_chain == "solana":
            try:
                decoded = _base58_decode(destination_address)
            except Exception:
                return jsonify({"error": "invalid solana address"}), 400
            if len(decoded) != 32:
                return jsonify({"error": "invalid solana address length"}), 400

        try:
            amount = int(data.get("amount", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "invalid amount"}), 400
        if amount <= 0:
            return jsonify({"error": "amount must be positive"}), 400

        try:
            difficulty = int(data.get("pow_difficulty", 0) or 0)
            proof = int(data.get("pow", 0) or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid pow fields"}), 400

        if not (pub_b64 and sig_b64):
            return jsonify({"error": "missing required fields"}), 400

        pub_dec = base64.b64decode(pub_b64)
        sig_dec = base64.b64decode(sig_b64)
        if len(sig_dec) == 65:
            sig_dec = sig_dec[:64]
        if len(pub_dec) != 33 or len(sig_dec) != 64:
            return jsonify({"error": "invalid relay fields"}), 400

        user_addr = derive_address_from_pubkey(pub_dec)
        if not user_addr:
            return jsonify({"error": "invalid pubkey"}), 400

        validator_addr = require_runtime().validator_payer_addr

        # Check subscriber status for PoW requirement
        user_is_sub = is_subscriber(user_addr)
        if not user_is_sub:
            # Non-subscriber: require PoW
            if not (difficulty > 0 and proof):
                return jsonify({"error": "pow_required", "details": "Non-subscriber must provide valid PoW"}), 400
            required = get_current_pow_difficulty()
            if difficulty < required:
                return jsonify({"error": "insufficient pow (precheck)"}), 400
            if not is_valid_recent_block_hash(last_block_hash):
                return jsonify({"error": "invalid last_block_hash"}), 400
        else:
            # Subscriber: PoW not allowed
            if difficulty > 0 or proof > 0:
                return jsonify({"error": "pow not allowed for subscribers"}), 400

        # Verify signature
        try:
            base = canon_base_bridge_burn(
                pub_dec,
                last_block_hash,
                difficulty,
                timestamp,
                destination_chain,
                destination_address,
                amount,
            )
            signed = canon_signed_with_pow(base, proof)
            if not _verify_signature(pub_dec, sig_dec, signed):
                log_event(rid, "bridge_burn.sig_fail", canonical_hex=signed.hex())
                return jsonify({"error": "invalid signature"}), 400
        except Exception as e:
            log_event(rid, "bridge_burn.sig_exception", error=str(e))
            return jsonify({"error": "invalid signature"}), 400

        # Build and broadcast transaction
        msg = MsgBridgeBurn()
        msg.authority = validator_addr
        msg.envelope_pubkey = pub_dec
        msg.envelope_block_hash = _hex_to_bytes(last_block_hash)
        msg.envelope_difficulty = difficulty
        msg.envelope_pow = proof
        msg.envelope_timestamp = timestamp
        msg.envelope_signature = sig_dec
        msg.destination_chain = destination_chain
        msg.destination_address = destination_address
        msg.amount = amount

        any_msg = AnyPB()
        any_msg.type_url = "/mirage.core.v1.MsgBridgeBurn"
        any_msg.value = msg.SerializeToString()
        body = TxBody(messages=[any_msg], memo="")
        body_bytes = body.SerializeToString()
        content_len = len(destination_chain) + len(destination_address)
        gas_est = int(estimate_total_gas_limit(body_bytes, content_len))
        tx_bytes_est = build_tx_bytes(body_bytes, gas_est)
        gas_used = int(simulate_gas(tx_bytes_est))
        gas_limit = max(gas_est, int(gas_used * GAS_BUFFER_MULTIPLIER))
        tx_bytes = build_tx_bytes(body_bytes, gas_limit)
        tx_hash, code, height, raw_log = broadcast_tx(tx_bytes)

        if code != 0:
            extra = {
                "height": height,
                "user_addr": user_addr,
                "destination_chain": destination_chain,
                "destination_address": destination_address,
                "amount": amount,
            }
            return _tx_error(rid, "bridge/burn", "MsgBridgeBurn", code, tx_hash, raw_log, extra)

        log_event(rid, "bridge_burn.success", tx_hash=tx_hash, destination_chain=destination_chain, amount=amount)
        return jsonify(
            {
                "tx_hash": tx_hash,
                "code": code,
                "height": height,
                "raw_log": raw_log,
                "burn_id": tx_hash,  # burn_id is the tx hash
            }
        )
    except Exception as e:
        log_event(rid, "bridge_burn.err", error=str(e))
        return jsonify({"error": str(e)}), 500
