from __future__ import annotations

"""Bridge relay endpoints for IBC and attested transfers.

Endpoints:
- POST /api/bridge/ibc_transfer: Relay IBC transfer to Cosmos chains (e.g., Osmosis)
- POST /api/bridge/burn: Relay burn for attested bridge to non-IBC chains (e.g., Solana)
- GET /api/bridge/config: Get bridge configuration (enabled chains, fees)
- GET /api/bridge/status: Get bridge status (pending transfers)
- GET /api/bridge/get_minted: Query bridge mint status from indexer DB
"""

import base64
import json
import os
from typing import Any, Dict

from flask import Blueprint, jsonify, request
from google.protobuf.any_pb2 import Any as AnyPB
from google.protobuf.json_format import MessageToDict
import grpc
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody

from bech32 import bech32_decode, convertbits  # type: ignore

from shared.datatypes import (
    MsgIBCTransfer,
    MsgBridgeBurn,
    QueryBridgeAttestationRequest,
    QueryBridgeAttestationResponse,
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
from db import connect_db

# Import shared helpers from core module
from routes.core import is_subscriber, _verify_signature, get_user_level, _hex_to_bytes, GAS_BUFFER_MULTIPLIER


bridge_bp = Blueprint("bridge", __name__)

_MAX_ADDR_LEN = 128
_MAX_CHAIN_LEN = 64
_MAX_CHANNEL_LEN = 64
_MAX_BLOCKHASH_HEX_LEN = 128


def _query_bridge_attestation_from_db(source_chain: str, burn_id: str) -> dict:
    """Query inbound bridge attestation from indexer DB."""
    with connect_db() as conn:
        with conn.cursor() as cur:
            # Get attestation details from most recent record
            cur.execute(
                """
                SELECT tx_hash, recipient, amount, validator, minted, created_at
                FROM bridge_transactions
                WHERE direction = 'in'
                  AND msg_type = 'attest_burned'
                  AND LOWER(source_chain) = LOWER(%s)
                  AND burn_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (source_chain, burn_id),
            )
            row = cur.fetchone()
            if not row:
                return {"found": False, "confirmed": False}

            # Count unique attestors
            cur.execute(
                """
                SELECT COUNT(DISTINCT validator)
                FROM bridge_transactions
                WHERE direction = 'in'
                  AND msg_type = 'attest_burned'
                  AND LOWER(source_chain) = LOWER(%s)
                  AND burn_id = %s
                """,
                (source_chain, burn_id),
            )
            attestor_count = cur.fetchone()[0] or 0

            return {
                "found": True,
                "confirmed": bool(row[4]),
                "mint_tx": row[0],  # Frontend expects mint_tx for inbound bridges
                "recipient": row[1],
                "amount": row[2],
                "validator": row[3],
                "created_at": row[5],
                "attestor_count": attestor_count,
            }


def _query_bridge_burn_from_db(burn_tx_hash: str) -> dict:
    """Query outbound bridge burn from indexer DB by Mirage tx hash."""
    with connect_db() as conn:
        with conn.cursor() as cur:
            # First get the burn record
            cur.execute(
                """
                SELECT destination_chain, recipient, amount, created_at
                FROM bridge_transactions
                WHERE direction = 'out'
                  AND msg_type = 'burn'
                  AND LOWER(tx_hash) = LOWER(%s)
                LIMIT 1
                """,
                (burn_tx_hash,),
            )
            burn_row = cur.fetchone()
            if not burn_row:
                return {"found": False, "confirmed": False}

            # Check if there's a CONFIRMED attest_minted (minted=true means threshold met)
            cur.execute(
                """
                SELECT destination_tx, created_at
                FROM bridge_transactions
                WHERE direction = 'out'
                  AND msg_type = 'attest_minted'
                  AND LOWER(burn_id) = LOWER(%s)
                  AND minted = TRUE
                LIMIT 1
                """,
                (burn_tx_hash,),
            )
            minted_row = cur.fetchone()

            # Count unique attestors for this burn
            cur.execute(
                """
                SELECT COUNT(DISTINCT validator)
                FROM bridge_transactions
                WHERE direction = 'out'
                  AND msg_type = 'attest_minted'
                  AND LOWER(burn_id) = LOWER(%s)
                """,
                (burn_tx_hash,),
            )
            attestor_count = cur.fetchone()[0] or 0

            return {
                "found": True,
                "confirmed": minted_row is not None,
                "destination_chain": burn_row[0],
                "destination_address": burn_row[1],
                "amount": burn_row[2],
                "created_at": burn_row[3],
                "destination_tx": minted_row[0] if minted_row else None,
                "confirmed_at": minted_row[1] if minted_row else None,
                "attestor_count": attestor_count,
            }


def _query_bridge_attestation_from_chain(source_chain: str, burn_id: str, timeout: float = 5.0) -> dict:
    """Query inbound bridge attestation directly from chain via gRPC."""

    def _deserialize(data: bytes) -> QueryBridgeAttestationResponse:
        msg = QueryBridgeAttestationResponse()
        msg.ParseFromString(data)
        return msg

    try:
        target = require_runtime().grpc_target
    except Exception as e:
        raise RuntimeError(f"gRPC not configured: {e}")

    try:
        with grpc.insecure_channel(target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/GetBridgeAttestation",
                request_serializer=lambda msg: msg.SerializeToString(),
                response_deserializer=_deserialize,
            )
            req = QueryBridgeAttestationRequest(source_chain=source_chain, burn_id=burn_id)
            resp = method(req, timeout=timeout)
    except grpc.RpcError as e:
        raise RuntimeError(f"gRPC error: {e.code()} - {e.details()}")

    return MessageToDict(resp, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)


def _query_bridge_minted_from_chain(dest_chain: str, burn_id: str, timeout: float = 5.0) -> dict:
    """Query outbound bridge mint status (attestation progress + completion) from chain via gRPC."""

    def _deserialize(data: bytes) -> QueryBridgeMintedResponse:
        msg = QueryBridgeMintedResponse()
        msg.ParseFromString(data)
        return msg

    try:
        target = require_runtime().grpc_target
    except Exception as e:
        raise RuntimeError(f"gRPC not configured: {e}")

    try:
        with grpc.insecure_channel(target) as channel:
            method = channel.unary_unary(
                "/mirage.core.v1.Query/GetBridgeMinted",
                request_serializer=lambda msg: msg.SerializeToString(),
                response_deserializer=_deserialize,
            )
            req = QueryBridgeMintedRequest(destination_chain=dest_chain, burn_id=burn_id)
            resp = method(req, timeout=timeout)
    except grpc.RpcError as e:
        raise RuntimeError(f"gRPC error: {e.code()} - {e.details()}")

    return MessageToDict(resp, preserving_proto_field_name=True, always_print_fields_with_no_presence=True)


def _decode_event_attributes(attrs: list) -> dict:
    """Decode CometBFT event attributes (handles both base64 and plain text formats)."""
    decoded: Dict[str, str] = {}
    for attr in attrs:
        if "key" not in attr or "value" not in attr:
            raise RuntimeError("tx event attribute missing key/value")
        raw_key = attr["key"]
        raw_value = attr["value"]
        # Try base64 decode first (old CometBFT format), fall back to plain text (new format)
        try:
            key = base64.b64decode(raw_key).decode("utf-8")
        except Exception:
            key = str(raw_key)
        try:
            value = base64.b64decode(raw_value).decode("utf-8")
        except Exception:
            value = str(raw_value)
        decoded[key] = value
    return decoded


def _get_bridge_burn_event_from_tx_hash(tx_hash: str, timeout: float = 3.0) -> dict:
    """Fetch bridge_burn event attributes from a Mirage tx hash via RPC."""
    import urllib.request as _url
    import urllib.error as _urlerr

    try:
        rpc = require_runtime().rpc_url
    except Exception as e:
        raise RuntimeError(f"RPC not configured: {e}")

    url = f"{rpc}/tx?hash=0x{tx_hash.upper()}&prove=false"
    try:
        with _url.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except _urlerr.HTTPError as e:
        raise RuntimeError(f"RPC HTTP error {e.code}: {e.reason}")
    except _urlerr.URLError as e:
        raise RuntimeError(f"RPC connection error: {e.reason}")
    except TimeoutError:
        raise RuntimeError(f"RPC timeout after {timeout}s")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"RPC invalid JSON: {e}")

    # Check for RPC-level error response
    if "error" in (data or {}):
        err = data["error"]
        raise RuntimeError(f"RPC error: {err.get('message', err)}")

    txr = (data or {}).get("result", {})
    if not txr:
        raise RuntimeError("TX not found (not indexed yet?)")

    events = (txr.get("tx_result", {}) or {}).get("events", []) or []
    for ev in events:
        if str(ev.get("type", "") or "") != "bridge_burn":
            continue
        attrs = _decode_event_attributes(ev.get("attributes") or [])
        return attrs
    raise RuntimeError("bridge_burn event not found in tx result")


def _query_attestation_status_inbound(source_chain: str, burn_id: str) -> dict:
    """Query inbound attestation progress from indexer DB."""
    with connect_db() as conn:
        with conn.cursor() as cur:
            # Get all attestations for this burn_id
            cur.execute(
                """
                SELECT validator, minted, created_at
                FROM bridge_transactions
                WHERE direction = 'in'
                  AND msg_type = 'attest_burned'
                  AND LOWER(source_chain) = LOWER(%s)
                  AND burn_id = %s
                ORDER BY created_at ASC
                """,
                (source_chain, burn_id),
            )
            rows = cur.fetchall()
            if not rows:
                return {"found": False, "confirmed": False, "attestors": [], "attestor_count": 0}

            attestors = [r[0] for r in rows if r[0]]
            confirmed = any(r[1] for r in rows)  # Any row with minted=true means threshold met

            return {
                "found": True,
                "confirmed": confirmed,
                "attestors": attestors,
                "attestor_count": len(attestors),
            }


def _query_attestation_status_outbound(burn_id: str) -> dict:
    """Query outbound attestation progress from indexer DB."""
    with connect_db() as conn:
        with conn.cursor() as cur:
            # Get all attestations for this burn_id
            cur.execute(
                """
                SELECT validator, minted, destination_tx, created_at
                FROM bridge_transactions
                WHERE direction = 'out'
                  AND msg_type = 'attest_minted'
                  AND LOWER(burn_id) = LOWER(%s)
                ORDER BY created_at ASC
                """,
                (burn_id,),
            )
            rows = cur.fetchall()
            if not rows:
                return {"found": False, "confirmed": False, "attestors": [], "attestor_count": 0}

            attestors = [r[0] for r in rows if r[0]]
            confirmed = any(r[1] for r in rows)  # Any row with minted=true means threshold met
            destination_tx = next((r[2] for r in rows if r[2]), None)

            return {
                "found": True,
                "confirmed": confirmed,
                "attestors": attestors,
                "attestor_count": len(attestors),
                "destination_tx": destination_tx,
            }


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
            channel = str(c.get("ibc_channel", "")).strip()
            if not channel:
                continue
            if channel == source_channel:
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
            if str(c.get("ibc_channel", "")).strip():
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

        # Solana program ID and token address from orchestrator config
        solana_program_id = os.environ.get("ORCHESTRATOR_SOLANA_PROGRAM_ID", "")
        solana_token_address = os.environ.get("ORCHESTRATOR_SOLANA_TOKEN_ADDRESS", "")

        # Format chains for frontend - each chain must have fee
        chains = []
        for chain in bridge_chains:
            chain_id = chain["chain_id"]
            fee_umirage = int(chain["fee"])  # Required per-chain fee
            entry = {
                "chain_id": chain_id,
                "enabled": chain["enabled"],
                "ibc_channel": chain.get("ibc_channel", ""),
                "fee_umirage": fee_umirage,
                "fee_mirage": fee_umirage / 1_000_000,
            }
            if chain_id == "solana":
                entry["solana_cluster"] = solana_cluster
                entry["solana_program_id"] = solana_program_id
                entry["solana_token_address"] = solana_token_address
            chains.append(entry)

        attestation_threshold = int(p["bridge_attestation_threshold"])
        return jsonify({"chains": chains, "attestation_threshold_bps": attestation_threshold})
    except Exception as e:
        log_event(rid, "bridge_config.err", error=str(e))
        return jsonify({"error": str(e)}), 500


@bridge_bp.route("/api/bridge/get_minted", methods=["GET"])
def get_bridge_minted():
    """Query bridge mint status from indexer DB.

    Inbound (external -> Mirage): pass burn_sequence + chain (e.g., chain=solana)
    Outbound (Mirage -> external): pass burn_tx_hash (Mirage burn tx hash)
    """
    rid = next_request_id()
    burn_sequence = (request.args.get("burn_sequence") or "").strip()
    burn_tx_hash = (request.args.get("burn_tx_hash") or "").strip().lower()
    chain = (request.args.get("chain") or "").strip().lower()
    log_event(
        rid,
        "get_bridge_minted.begin",
        burn_sequence=burn_sequence,
        burn_tx_hash=burn_tx_hash,
        chain=chain,
    )

    if chain:
        if not burn_sequence:
            return jsonify({"error": "burn_sequence required"}), 400
        if burn_tx_hash:
            return jsonify({"error": "burn_tx_hash not allowed for inbound queries"}), 400
    else:
        if not burn_tx_hash:
            return jsonify({"error": "burn_tx_hash required"}), 400
        if burn_sequence:
            return jsonify({"error": "burn_sequence not allowed for outbound queries"}), 400

    # Note: No IP restriction - this is a read-only status query for public blockchain data

    try:
        if chain:
            # Inbound bridge: query attestation by source chain and burn_sequence
            result = _query_bridge_attestation_from_db(chain, burn_sequence)
            result["burn_sequence"] = burn_sequence
            result["burn_tx_hash"] = None
            log_event(
                rid,
                "get_bridge_minted.ok",
                burn_sequence=burn_sequence,
                chain=chain,
                found=result.get("found", False),
                confirmed=result.get("confirmed", False),
            )
        else:
            # Outbound bridge: query by burn_tx_hash (Mirage tx hash)
            tx_hash = burn_tx_hash.lower()
            burn_attrs = _get_bridge_burn_event_from_tx_hash(tx_hash)
            burn_seq = str(burn_attrs.get("burn_id", "") or "").strip()
            dest_chain = str(burn_attrs.get("destination_chain", "") or "").strip().lower()
            if not burn_seq or not dest_chain:
                raise RuntimeError("bridge_burn event missing burn_id or destination_chain")

            result = _query_bridge_burn_from_db(tx_hash)
            result["burn_tx_hash"] = tx_hash
            result["burn_sequence"] = burn_seq
            if not result.get("destination_chain"):
                result["destination_chain"] = dest_chain
            log_event(
                rid,
                "get_bridge_minted.ok",
                burn_tx_hash=tx_hash,
                burn_sequence=burn_seq,
                confirmed=result.get("confirmed", False),
                destination_chain=result.get("destination_chain"),
            )
        return jsonify(result)
    except Exception as e:
        log_event(rid, "get_bridge_minted.err", chain=chain, error=str(e))
        return jsonify({"error": str(e)}), 500


@bridge_bp.route("/api/bridge/attestation_status", methods=["GET"])
def get_attestation_status():
    """Query bridge attestation progress from chain (gRPC + RPC).

    Inbound (external -> Mirage): pass burn_sequence + chain (e.g., chain=solana)
    Outbound (Mirage -> external): pass burn_tx_hash (Mirage burn tx hash)

    Returns:
    - found: whether any attestations exist
    - confirmed: whether threshold has been met
    - attestors: list of validator addresses that have attested
    - attestor_count: number of attestations received
    - attested_power: total voting power that has attested
    - required_power: voting power required to confirm
    """
    rid = next_request_id()
    burn_sequence = (request.args.get("burn_sequence") or "").strip()
    burn_tx_hash = (request.args.get("burn_tx_hash") or "").strip().lower()
    chain = (request.args.get("chain") or "").strip().lower()
    log_event(
        rid,
        "attestation_status.begin",
        burn_sequence=burn_sequence,
        burn_tx_hash=burn_tx_hash,
        chain=chain,
    )

    if chain:
        if not burn_sequence:
            return jsonify({"error": "burn_sequence required"}), 400
        if burn_tx_hash:
            return jsonify({"error": "burn_tx_hash not allowed for inbound queries"}), 400
    else:
        if not burn_tx_hash:
            return jsonify({"error": "burn_tx_hash required"}), 400
        if burn_sequence:
            return jsonify({"error": "burn_sequence not allowed for outbound queries"}), 400

    # Note: No IP restriction - this is a read-only status query for public blockchain data

    try:
        if chain:
            # Inbound bridge: query from indexer DB
            db_data = _query_attestation_status_inbound(chain, burn_sequence)
            result = {
                "found": db_data.get("found", False),
                "confirmed": db_data.get("confirmed", False),
                "burn_sequence": burn_sequence,
                "burn_tx_hash": None,
                "attestors": db_data.get("attestors", []),
                "attestor_count": db_data.get("attestor_count", 0),
                "attested_power": 0,
                "required_power": 0,
            }
        else:
            # Outbound bridge: resolve burn sequence from tx hash, then query chain
            tx_hash = burn_tx_hash.lower()
            if len(tx_hash) != 64 or any(c not in "0123456789abcdef" for c in tx_hash):
                return jsonify({"error": "invalid burn_tx_hash (expected tx hash)"}), 400

            burn_attrs = _get_bridge_burn_event_from_tx_hash(tx_hash)
            burn_seq = str(burn_attrs.get("burn_id", "") or "").strip()
            dest_chain = str(burn_attrs.get("destination_chain", "") or "").strip().lower()
            if not burn_seq or not dest_chain:
                raise RuntimeError("bridge_burn event missing burn_id or destination_chain")

            # Outbound bridge: query from indexer DB
            db_data = _query_attestation_status_outbound(tx_hash)
            result = {
                "found": db_data.get("found", False),
                "confirmed": db_data.get("confirmed", False),
                "burn_tx_hash": tx_hash,
                "burn_sequence": burn_seq,
                "attestors": db_data.get("attestors", []),
                "attestor_count": db_data.get("attestor_count", 0),
                "attested_power": 0,
                "required_power": 0,
                "destination_chain": dest_chain,
                "destination_tx": db_data.get("destination_tx"),
            }

        log_event(
            rid,
            "attestation_status.ok",
            burn_sequence=burn_sequence,
            burn_tx_hash=burn_tx_hash,
            chain=chain,
            found=result.get("found", False),
            confirmed=result.get("confirmed", False),
            attestor_count=result.get("attestor_count", 0),
        )
        return jsonify(result)
    except Exception as e:
        log_event(rid, "attestation_status.err", chain=chain, error=str(e))
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
                "burn_tx_hash": tx_hash,
                "burn_sequence": None,
                "code": code,
                "height": height,
                "raw_log": raw_log,
            }
        )
    except Exception as e:
        log_event(rid, "bridge_burn.err", error=str(e))
        return jsonify({"error": str(e)}), 500
