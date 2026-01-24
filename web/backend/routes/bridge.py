from __future__ import annotations

"""Bridge relay endpoints for IBC and attested transfers.

Endpoints:
- POST /api/bridge/ibc_transfer: Relay IBC transfer to Cosmos chains (e.g., Osmosis)
- POST /api/bridge/burn: Relay burn for attested bridge to non-IBC chains (e.g., Solana)
- GET /api/bridge/config: Get bridge configuration (enabled chains, fees)
- GET /api/bridge/status: Query bridge status from indexer DB
"""

import base64
import os
from typing import Any, Dict

from flask import Blueprint, jsonify, request
from google.protobuf.any_pb2 import Any as AnyPB
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody

from bech32 import bech32_decode, convertbits  # type: ignore

from shared.datatypes import (
    MsgIBCTransfer,
    MsgBridgeBurn,
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
            # Get aggregated attestation data including power info
            # Only count validators with power > 0 (power=0 means duplicate/failed attestation)
            cur.execute(
                """
                SELECT 
                    MAX(tx_hash) as tx_hash,
                    MAX(recipient) as recipient,
                    MAX(amount) as amount,
                    MAX(validator) as validator,
                    BOOL_OR(minted) as minted,
                    MAX(created_at) as created_at,
                    COUNT(DISTINCT CASE WHEN power > 0 THEN validator END) as attestor_count,
                    COALESCE(SUM(power), 0) as attested_power,
                    MAX(required_power) as required_power
                FROM bridge_transactions
                WHERE direction = 'in'
                  AND msg_type = 'attest_burned'
                  AND LOWER(source_chain) = LOWER(%s)
                  AND burn_id = %s
                """,
                (source_chain, burn_id),
            )
            row = cur.fetchone()
            if not row or row[6] == 0:  # attestor_count == 0 means no records
                return {"found": False, "confirmed": False}

            return {
                "found": True,
                "confirmed": bool(row[4]),
                "mint_tx": row[0],  # Frontend expects mint_tx for inbound bridges
                "recipient": row[1],
                "amount": row[2],
                "validator": row[3],
                "created_at": row[5],
                "attestor_count": row[6],
                "attested_power": row[7],
                "required_power": row[8] or 0,
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

            # Get aggregated attestation data including power info
            # Only count validators with power > 0 (power=0 means duplicate/failed attestation)
            cur.execute(
                """
                SELECT 
                    MAX(destination_tx) as destination_tx,
                    MAX(created_at) as confirmed_at,
                    COUNT(DISTINCT CASE WHEN power > 0 THEN validator END) as attestor_count,
                    COALESCE(SUM(power), 0) as attested_power,
                    MAX(required_power) as required_power,
                    BOOL_OR(minted) as minted
                FROM bridge_transactions
                WHERE direction = 'out'
                  AND msg_type = 'attest_minted'
                  AND LOWER(burn_id) = LOWER(%s)
                """,
                (burn_tx_hash,),
            )
            attest_row = cur.fetchone()
            # attest_row will always return a row, check attestor_count for records
            has_attestations = attest_row and attest_row[2] > 0

            return {
                "found": True,
                "confirmed": bool(attest_row[5]) if has_attestations else False,
                "destination_chain": burn_row[0],
                "destination_address": burn_row[1],
                "amount": burn_row[2],
                "created_at": burn_row[3],
                "destination_tx": attest_row[0] if has_attestations else None,
                "confirmed_at": attest_row[1] if has_attestations else None,
                "attestor_count": attest_row[2] if has_attestations else 0,
                "attested_power": attest_row[3] if has_attestations else 0,
                "required_power": attest_row[4] or 0 if has_attestations else 0,
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


@bridge_bp.route("/api/bridge/status", methods=["GET"])
def get_bridge_status():
    """Query bridge status from indexer DB.

    Inbound (external -> Mirage): pass burn_sequence + chain (e.g., chain=solana)
    Outbound (Mirage -> external): pass burn_tx_hash (Mirage burn tx hash)
    """
    rid = next_request_id()
    burn_sequence = (request.args.get("burn_sequence") or "").strip()
    burn_tx_hash = (request.args.get("burn_tx_hash") or "").strip().lower()
    chain = (request.args.get("chain") or "").strip().lower()
    log_event(
        rid,
        "bridge_status.begin",
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
                "bridge_status.ok",
                burn_sequence=burn_sequence,
                chain=chain,
                found=result.get("found", False),
                confirmed=result.get("confirmed", False),
            )
        else:
            # Outbound bridge: query by burn_tx_hash (Mirage tx hash)
            tx_hash = burn_tx_hash.lower()
            if len(tx_hash) != 64 or any(c not in "0123456789abcdef" for c in tx_hash):
                return jsonify({"error": "invalid burn_tx_hash (expected tx hash)"}), 400

            result = _query_bridge_burn_from_db(tx_hash)
            result["burn_tx_hash"] = tx_hash
            result["burn_sequence"] = None
            log_event(
                rid,
                "bridge_status.ok",
                burn_tx_hash=tx_hash,
                burn_sequence=result.get("burn_sequence"),
                confirmed=result.get("confirmed", False),
                destination_chain=result.get("destination_chain"),
            )
        return jsonify(result)
    except Exception as e:
        log_event(rid, "bridge_status.err", chain=chain, error=str(e))
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

        # IBC transfer skips PoW for all users - token transfers are self-authenticating
        # (you can't transfer tokens you don't have)
        # Force difficulty and proof to 0 to ensure consistent signature verification
        difficulty = 0
        proof = 0

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

        # Bridge burn skips PoW for all users - token transfers are self-authenticating
        # (you can't burn tokens you don't have, and bridge fee is already charged)
        # Force difficulty and proof to 0 to ensure consistent signature verification
        difficulty = 0
        proof = 0

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
