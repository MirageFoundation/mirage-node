#!/usr/bin/env python3
"""
Mirage Blockchain Indexer

IMPORTANT: API USAGE POLICY
- Use gRPC (port 9090) for all chain queries (governance, bank, etc.)
- Use RPC/HTTP (port 26657) only for Tendermint-specific queries (status, block_results, websocket)
- NEVER use REST API (port 1317) - it is not enabled and not used by the backend
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import os
import fcntl
import signal
import atexit
import time
import logging
from pathlib import Path

# Add parent directory to path for shared imports
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from indexer.database import DatabaseManager
from indexer.chain_client import ChainClient
from indexer.message_processor import MessageProcessor, TYPE_URL_TO_PROTO
from indexer.migrations import run_migrations
from indexer.params import load_params as load_chain_params
from indexer.settings import (
    SEEN_TXS_MAX_SIZE,
    SEEN_TXS_CLEANUP_BATCH,
    CATCHUP_PROGRESS_INTERVAL,
    WS_RECONNECT_DELAY,
    HTTP_TIMEOUT_LONG,
    RPC_READY_MAX_WAIT,
    RPC_READY_RETRY_DELAY,
)
from shared.config import get_config
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxRaw, TxBody
from cosmpy.protos.cosmos.gov.v1beta1.tx_pb2 import MsgSubmitProposal

logger = logging.getLogger(__name__)


def _synthesize_raw_log(tx_result: dict, height: int, tx_hash: str) -> str:
    """Build raw_log JSON from the events array when the log field is empty.

    CometBFT sometimes returns an empty ``log`` for successful txs while
    the structured events are still present in ``events``.  The push
    listener expects ``[{"events": [...]}]`` format, so we wrap the flat
    events list into that shape.
    """
    events = tx_result.get("events")
    if not events:
        raise RuntimeError(f"tx_index raw_log missing (empty log AND no events) height={height} txhash={tx_hash}")
    # CometBFT events use base64-encoded attribute values; decode them so
    # downstream JSON consumers (push_listener) see plain strings.
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
    synthesized = json.dumps([{"events": decoded_events}])
    logger.debug(
        "tx_index.raw_log synthesized from events height=%s txhash=%s events=%d",
        height,
        tx_hash,
        len(decoded_events),
    )
    return synthesized


def _resolve_validator_address() -> str:
    """Resolve the local validator's account address from the keyring."""
    try:
        config = get_config()
        node_cfg = config.get_node_config()
        home = node_cfg["home"]
        keyring_backend = config.get_keyring_backend()
        bin_path = os.path.abspath(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "blockchain", "bin", "miraged")
        )
        cmd = [bin_path, "keys", "list", "--output", "json", "--home", home, "--keyring-backend", keyring_backend]
        out = subprocess.check_output(cmd, timeout=5, stderr=subprocess.DEVNULL).decode("utf-8").strip()
        for entry in json.loads(out) or []:
            if str(entry.get("name", "")) == "validator":
                addr = str(entry.get("address", "")).strip()
                if addr and re.fullmatch(r"mirage1[0-9a-z]{38}", addr):
                    return addr
    except Exception as e:
        logger.warning("Could not resolve validator address: %s", e)
    return ""


class Indexer:
    """Mirage Blockchain Indexer."""

    def __init__(self, start_height: int | None = None):
        config = get_config()
        indexer_config = config.get_indexer_config()

        if not indexer_config["enabled"]:
            raise RuntimeError("Indexer disabled")

        self._start_height_override = start_height

        jsonrpc_url = indexer_config["jsonrpc_url"]
        db_url = indexer_config["database_url"]

        self.db = DatabaseManager(db_url)
        self.chain = ChainClient(jsonrpc_url)

        # Resolve validator address for node balance tracking
        self._validator_address = _resolve_validator_address()
        if self._validator_address:
            logger.info("Tracking node balance for %s", self._validator_address)
        else:
            logger.warning("Validator address not resolved; node balance tracking disabled")

        # Run pending migrations before processing begins
        migration_count = run_migrations(self.db, self.chain)
        if migration_count > 0:
            logger.info(f"Completed {migration_count} migrations")

        self.processor = MessageProcessor(
            self.db,
            self.chain,
            self._log_yaml,
            self.chain.iso_timestamp,
        )

        self.running = False
        self.ws = None
        self._seen_txs: set[str] = set()
        self._proposal_cache: dict[int, list[dict]] = {}
        self._skipped_proposals: set[int] = set()  # Track proposals we've already logged as skipped
        self._catch_up_mode: bool = False
        self._last_height = self.db.get_last_height()

        self._lock_file = None
        try:
            # Use /tmp for lock file - ephemeral, cleared on container restart
            lock_path = "/tmp/mirage-indexer.lock"
            self._lock_file = open(lock_path, "w")
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_file.write(str(os.getpid()))
            self._lock_file.flush()
            self._lock_path = lock_path
            atexit.register(self._release_lock)
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except BlockingIOError:
            logger.error("Another indexer instance already running for this node; exiting.")
            sys.exit(0)

        try:
            import yaml as _yaml  # type: ignore

            self._yaml = _yaml
        except Exception:
            self._yaml = None

    def _release_lock(self):
        try:
            if getattr(self, "_lock_file", None):
                try:
                    fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
                try:
                    self._lock_file.close()
                except Exception:
                    pass
            if getattr(self, "_lock_path", None) and os.path.exists(self._lock_path):
                try:
                    os.remove(self._lock_path)
                except Exception:
                    pass
        except Exception:
            pass

    def _handle_signal(self, signum, _frame):
        logger.info("Signal %s received; cleaning up lock and exiting.", signum)
        try:
            self.running = False
        except Exception:
            pass
        try:
            if getattr(self, "ws", None) is not None:
                try:
                    self.ws.close()
                except Exception:
                    pass
        except Exception:
            pass
        self._release_lock()
        try:
            sys.exit(0)
        except SystemExit:
            raise

    def _log_yaml(self, title: str, data: dict):
        try:
            logger.info("================ INDEXER ==================")
            logger.info(title)
            if self._yaml is not None:
                try:
                    logger.info(self._yaml.safe_dump(data, sort_keys=False, default_flow_style=False).rstrip())
                except Exception:
                    logger.info(json.dumps(data, indent=2, ensure_ascii=False))
            else:
                logger.info(json.dumps(data, indent=2, ensure_ascii=False))
            logger.info("-------------------------------------------")
        except Exception:
            pass

    def _process_block(self, height: int):
        """Decode transactions in a block and process core messages."""
        try:
            blk = self.chain.get_block(height)
            result = blk.get("result")
            if not result:
                raise RuntimeError(f"Missing 'result' in block response at height {height}")
            block = result.get("block")
            if not block:
                raise RuntimeError(f"Missing 'block' in result at height {height}")
            block_hash = (result.get("block_id") or {}).get("hash", "") or ""
            header = block.get("header")
            if not header:
                raise RuntimeError(f"Missing 'header' in block at height {height}")
            block_data = block.get("data", {})
            txs = block_data.get("txs", [])
            ts = self.chain.parse_header_time(str(header.get("time", "")))

            results = self.chain.get_block_results(height)
            result_obj = results.get("result")
            if not result_obj:
                raise RuntimeError(f"Missing 'result' in block_results at height {height}")
            txs_results = result_obj.get("txs_results", [])

            for idx, tx_b64 in enumerate(txs):
                try:
                    raw_tx_bytes = base64.b64decode(tx_b64)
                    tx_hash = hashlib.sha256(raw_tx_bytes).hexdigest().lower()
                    if tx_hash in self._seen_txs:
                        continue

                    tx_raw = TxRaw()
                    tx_raw.ParseFromString(raw_tx_bytes)
                    tx_body = TxBody()
                    tx_body.ParseFromString(tx_raw.body_bytes)

                    if idx < len(txs_results):
                        code = int(txs_results[idx].get("code", 0))
                        if code != 0:
                            from indexer.message_processor import type_url_to_tx_type

                            tx_type = "unknown"
                            for any_msg in tx_body.messages:
                                if any_msg.type_url.startswith("/mirage.core.v1."):
                                    tx_type = type_url_to_tx_type(any_msg.type_url)
                                    break
                            raw_log = str(txs_results[idx].get("log", "") or "")
                            self.db.upsert_tx_index(
                                tx_hash,
                                tx_type,
                                code,
                                raw_log,
                                height,
                                ts,
                            )
                            logger.debug(
                                "Recorded failed tx (height=%s code=%s tx_type=%s txhash=%s)",
                                height,
                                code,
                                tx_type,
                                tx_hash,
                            )
                            continue

                    # Successful tx: record once in tx_index using the first core message type.
                    from indexer.message_processor import type_url_to_tx_type

                    core_types = [
                        any_msg.type_url
                        for any_msg in tx_body.messages
                        if any_msg.type_url.startswith("/mirage.core.v1.")
                    ]
                    if core_types:
                        if len(core_types) == 1:
                            tx_type = type_url_to_tx_type(core_types[0])
                        else:
                            tx_type = "multi"
                        raw_entry = None
                        if idx < len(txs_results):
                            raw_entry = txs_results[idx].get("log")
                        raw_log = "" if raw_entry is None else str(raw_entry)
                        if tx_type in ("send_tokens", "multi"):
                            if idx >= len(txs_results):
                                logger.error(
                                    "tx_index.raw_log_missing no_tx_result height=%s txhash=%s type=%s",
                                    height,
                                    tx_hash,
                                    tx_type,
                                )
                                raise RuntimeError(
                                    f"tx_index raw_log missing (no tx_result) height={height} txhash={tx_hash}"
                                )
                            if raw_log == "":
                                raw_log = _synthesize_raw_log(txs_results[idx], height, tx_hash)
                        self.db.upsert_tx_index(
                            tx_hash,
                            tx_type,
                            0,
                            raw_log,
                            height,
                            ts,
                        )

                    pending_proposals: list[list[dict]] = []
                    for any_msg in tx_body.messages:
                        if any_msg.type_url in (
                            "/cosmos.gov.v1beta1.MsgSubmitProposal",
                            "/cosmos.gov.v1.MsgSubmitProposal",
                        ):
                            parsed = MsgSubmitProposal()
                            parsed.ParseFromString(any_msg.value)
                            payloads: list[dict] = []
                            inner_msgs = MessageProcessor.extract_inner_messages(parsed)
                            for inner in inner_msgs:
                                if not inner.type_url:
                                    raise RuntimeError("Inner message missing type_url in proposal")
                                if not inner.value:
                                    raise RuntimeError("Inner message missing value in proposal")
                                payloads.append(
                                    {
                                        "type_url": inner.type_url,
                                        "value": base64.b64encode(inner.value).decode("ascii"),
                                    }
                                )
                            if payloads:
                                pending_proposals.append(payloads)
                            continue

                        if any_msg.type_url.startswith("/cosmos.gov."):
                            continue

                        if not any_msg.type_url.startswith("/mirage.core.v1."):
                            continue

                        self.processor.process_core_message(any_msg.type_url, any_msg.value, tx_hash, ts, height)

                    tx_events = txs_results[idx].get("events", []) if idx < len(txs_results) else []
                    self.processor.process_tx_events(tx_events, tx_hash)

                    if pending_proposals:
                        proposal_ids_set: set[int] = set()
                        for ev_type, attrs in MessageProcessor.decode_events(tx_events):
                            pid = MessageProcessor.extract_proposal_id(attrs)
                            if pid is not None:
                                proposal_ids_set.add(pid)
                        for proposal_id in sorted(proposal_ids_set):
                            if not pending_proposals:
                                break
                            payloads = pending_proposals.pop(0)
                            self._proposal_cache[int(proposal_id)] = payloads

                    self._seen_txs.add(tx_hash)
                    if len(self._seen_txs) > SEEN_TXS_MAX_SIZE:
                        for _ in range(SEEN_TXS_CLEANUP_BATCH):
                            try:
                                self._seen_txs.pop()
                            except KeyError:
                                break

                except Exception as tx_err:
                    raise RuntimeError(f"Error processing tx at height {height}: {tx_err}") from tx_err

            self._process_governance_events(result_obj, ts, height)
            self._process_subscription_events(result_obj, ts, height)

            # Per-block state updates: balances, recent blocks, indexer state
            try:
                self._update_per_block_state(height, header, result_obj, ts, block_hash)
            except Exception as state_err:
                logger.warning("Per-block state update failed at height %s: %s", height, state_err)
        except Exception as e:
            raise RuntimeError(f"Error processing block {height}: {e}") from e

    def _process_subscription_events(self, result_obj: dict, ts: int, height: int):
        """Process subscription expiration/renewal events from EndBlock."""
        events = result_obj.get("end_block_events") or result_obj.get("finalize_block_events")
        if not events:
            return

        for event in events:
            event_type = event.get("type", "")
            if event_type == "subscription_expired":
                attrs = {a["key"]: a.get("value", "") for a in event.get("attributes", [])}
                address = attrs.get("address", "")
                if address:
                    logger.info("Subscription expired for %s (reason: %s)", address, attrs.get("reason", "unknown"))
                    self.processor.update_profile_level(address, 0, ts)
            elif event_type == "subscription_renewed":
                attrs = {a["key"]: a.get("value", "") for a in event.get("attributes", [])}
                address = attrs.get("address", "")
                level_str = attrs.get("level", "0")
                new_expiry_str = attrs.get("new_expiry", "0")
                if address:
                    try:
                        level = int(level_str)
                    except ValueError:
                        level = 0
                    try:
                        new_expiry = int(new_expiry_str)
                    except ValueError:
                        new_expiry = 0
                    logger.info(
                        "Subscription renewed for %s (level: %d, new_expiry: %d)",
                        address,
                        level,
                        new_expiry,
                    )
                    self.processor.update_profile_subscription(address, level, new_expiry, ts)

    def _process_governance_events(self, result_obj: dict, ts: int, height: int):
        """Process governance events for passed proposals.

        Resolution order: proposal cache → gRPC query.
        No tx_search fallback — indexer="null" means tx_search is unavailable.
        """
        events = result_obj.get("end_block_events") or result_obj.get("finalize_block_events")
        if events is None:
            events = []
        if not events:
            return

        passed_ids = self.processor.extract_passed_proposals(events)
        for proposal_id in passed_ids:
            if proposal_id in self._skipped_proposals:
                continue
            try:
                messages = self._proposal_cache.pop(proposal_id, None)
                if not messages:
                    try:
                        messages = self.chain.fetch_proposal_messages(proposal_id, TYPE_URL_TO_PROTO)
                    except RuntimeError as grpc_err:
                        if "no trackable messages" in str(grpc_err).lower():
                            logger.warning(
                                "Skipping proposal %s — governance-only messages (not tracked by indexer)",
                                proposal_id,
                            )
                        else:
                            logger.error(
                                "Failed to resolve proposal %s via gRPC: %s",
                                proposal_id,
                                grpc_err,
                            )
                        self._skipped_proposals.add(proposal_id)
                        continue

                for entry in messages or []:
                    type_url = entry.get("type_url")
                    value_b64 = entry.get("value")
                    if not type_url or not value_b64:
                        logger.warning("Skipping invalid message entry for proposal %s", proposal_id)
                        continue
                    value_bytes = base64.b64decode(value_b64)
                    self.processor.process_core_message(type_url, value_bytes, f"proposal-{proposal_id}", ts, height)
            except Exception as e:
                logger.warning("Non-fatal governance processing error for proposal %s: %s", proposal_id, e)

    def _catch_up(self):
        """Catch up to current block height."""
        logger.info("=" * 60)
        logger.info("INDEXER CATCHUP: Starting catchup process")
        logger.info("=" * 60)

        current_height = self.chain.get_current_height()
        logger.info("Current chain height: %s", current_height)

        # Determine safe starting height considering node pruning window
        earliest = self.chain.get_earliest_height()
        if earliest < 1:
            earliest = 1
        if self._start_height_override is not None:
            requested = int(self._start_height_override)
            start = requested if requested >= earliest else earliest
            logger.info(
                "Starting from height %s (override specified, clamped to earliest available %s)",
                start,
                earliest,
            )
        else:
            last_height = self.db.get_last_height()
            logger.info("Database last processed height: %s", last_height)

            # Max lookback (default 7 days, ~100,800 blocks at 6 sec/block)
            # Values > 7 days unlikely to work due to aggressive node pruning
            max_lookback_days = int(os.environ.get("INDEXER_MAX_LOOKBACK_DAYS", "7") or "7")
            blocks_per_day = 14_400  # ~6 sec/block
            max_lookback_blocks = max_lookback_days * blocks_per_day
            max_lookback_height = max(current_height - max_lookback_blocks, 1)

            if last_height > 0:
                # Continue from where we left off
                start = last_height + 1
            else:
                # Fresh DB: start from earliest available, but no more than 7 days back
                start = max(earliest, max_lookback_height)

            # Clamp to node's pruning window
            if start < earliest:
                logger.info(
                    "Adjusting start height from %s to earliest available %s due to pruning",
                    start,
                    earliest,
                )
                start = earliest

            # Clamp to max lookback
            if start < max_lookback_height:
                logger.info(
                    "Clamping start height from %s to %s (max %d-day lookback)",
                    start,
                    max_lookback_height,
                    max_lookback_days,
                )
                start = max_lookback_height

            logger.info("Starting from height %s", start)

        end = current_height

        if start <= end:
            total_blocks = end - start + 1
            logger.info("Catchup range: blocks %s to %s (total: %s blocks)", start, end, total_blocks)
            logger.info("Catchup started at: %s", self.chain.iso_timestamp(int(time.time())))
            self._catch_up_mode = True
            catchup_start_time = time.time()
            try:
                for height in range(start, end + 1):
                    self._process_block(height)
                    self.db.set_last_height(height)
                    self._last_height = height
                    if height % CATCHUP_PROGRESS_INTERVAL == 0:
                        processed = height - start + 1
                        elapsed = time.time() - catchup_start_time
                        rate = processed / elapsed if elapsed > 0 else 0
                        remaining = end - height
                        eta_seconds = remaining / rate if rate > 0 else 0
                        logger.info(
                            "Catchup progress: processed %s / %s blocks (%.1f blocks/sec, ~%.0f seconds remaining)",
                            processed,
                            total_blocks,
                            rate,
                            eta_seconds,
                        )
            finally:
                self._catch_up_mode = False
                catchup_end_time = time.time()
                elapsed_total = catchup_end_time - catchup_start_time
                logger.info("=" * 60)
                logger.info("INDEXER CATCHUP: Completed successfully")
                logger.info(
                    "Processed %s blocks in %.1f seconds (%.1f blocks/sec)",
                    total_blocks,
                    elapsed_total,
                    total_blocks / elapsed_total if elapsed_total > 0 else 0,
                )
                logger.info("Caught up to height: %s", end)
                logger.info("=" * 60)
        else:
            logger.info("No catchup needed: already at current height %s", current_height)

        return current_height

    def on_message(self, ws, message):
        """Handle WebSocket message."""
        try:
            data = json.loads(message)
            if "result" in data and "data" in data["result"]:
                result_data = data["result"]["data"]
                if "value" in result_data and "block" in result_data["value"]:
                    block_data = result_data["value"]["block"]
                    height = int(block_data.get("header", {}).get("height", 0))
                    if height > 0:
                        if height <= self._last_height:
                            return
                        for h in range(self._last_height + 1, height + 1):
                            self._process_block(h)
                        self.db.set_last_height(height)
                        self._last_height = height
                        # Record difficulty and msg_count in live mode (accurate data)
                        try:
                            info = self.chain.get_difficulty_info()
                            self.db.upsert_difficulty(
                                height,
                                int(info.get("current_difficulty", 0)),
                                int(info.get("pow_message_count", 0)),
                                int(time.time()),
                            )
                            self.db.set_chain_stat("difficulty_info", info, int(time.time()))
                        except Exception as diff_err:
                            logger.warning("Failed to record difficulty at height %s: %s", height, diff_err)
                        # Record supply (and node balance) every 200 blocks (aligns with mint interval)
                        if height % 200 == 0:
                            try:
                                supply = self.chain.get_total_supply()
                                node_bal = None
                                if self._validator_address:
                                    try:
                                        node_bal = self.chain.get_balance(self._validator_address)
                                    except Exception:
                                        pass
                                if supply > 0:
                                    self.db.upsert_supply(height, supply, int(time.time()), node_balance=node_bal)
                                    self.db.set_chain_stat("total_supply", supply, int(time.time()))
                            except Exception as supply_err:
                                logger.warning("Failed to record supply at height %s: %s", height, supply_err)
        except Exception as e:
            logger.error("Error processing message: %s", e, exc_info=True)

    def on_error(self, ws, error):
        logger.error("WebSocket error: %s", error)

    def on_close(self, ws, close_status_code, close_msg):
        logger.warning("WebSocket closed: %s - %s", close_status_code, close_msg)

    def on_open(self, ws):
        logger.info("WebSocket connected")
        ws.send(
            json.dumps({"jsonrpc": "2.0", "method": "subscribe", "id": 1, "params": {"query": "tm.event='NewBlock'"}})
        )

    def _run_websocket_loop(self):
        """Non-recursive WebSocket loop. run_forever() blocks until close,
        then this loop handles reconnection without nesting stack frames."""
        delay = WS_RECONNECT_DELAY
        attempt = 0
        while self.running:
            try:
                if not self.chain.wait_for_rpc_ready():
                    time.sleep(delay)
                    continue

                if attempt > 0:
                    logger.info("Reconnecting websocket (attempt %s, delay %ss)...", attempt, delay)

                self.ws = self.chain.create_websocket_app(
                    self.on_open,
                    self.on_message,
                    self.on_error,
                    self.on_close,
                )
                self.chain.run_websocket_forever(self.ws, self.running)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error("WebSocket loop error: %s", e, exc_info=True)

            attempt += 1
            if self.running:
                time.sleep(delay)

    def start(self):
        """Start the indexer."""
        logger.info("Starting indexer for %s", self.chain.jsonrpc_url)
        logger.info("Database URL: %s", getattr(self.db, "database_url", "unknown"))

        # Wait for RPC readiness before starting (internalized, no external wrapper script)
        waited = 0
        while not self.chain.wait_for_rpc_ready():
            if waited >= RPC_READY_MAX_WAIT:
                raise RuntimeError(f"Node RPC not ready after {RPC_READY_MAX_WAIT}s at {self.chain.jsonrpc_url}")
            time.sleep(RPC_READY_RETRY_DELAY)
            waited += RPC_READY_RETRY_DELAY

        # Load chain params BEFORE processing any blocks - indexer MUST have params
        logger.info("Loading chain params from %s...", self.chain.grpc_target)
        load_chain_params(self.chain.grpc_target)

        # Perform KV sync for profiles once RPC is ready (ensures DB reflects on-chain KV)
        try:
            self._sync_profiles_from_chain()
        except Exception as e:
            logger.warning("KV Sync skipped (profiles): %s", e)

        # Startup resync: refresh mutable chain state (balances, supply, validators, params)
        try:
            self._startup_resync()
        except Exception as e:
            logger.warning("Startup resync failed: %s", e, exc_info=True)

        self.running = True

        current_height = self._catch_up()

        logger.info("Transitioning to live mode (WebSocket)")
        try:
            self._run_websocket_loop()
        except KeyboardInterrupt:
            pass

    def _startup_resync(self):
        """Refresh mutable chain state on startup — block replay may be incomplete."""
        now = int(time.time())
        logger.info("Startup resync: refreshing chain stats, params, balances...")

        # 1. Chain params (store RAW gRPC dict so backend gets all fields)
        try:
            from indexer.params import get_raw_params

            params_dict = get_raw_params()
            if params_dict:
                self.db.set_chain_stat("chain_params", params_dict, now)
                logger.info("Startup resync: chain_params stored")
        except Exception as e:
            logger.warning("Startup resync: chain_params failed: %s", e)

        # 2. Total supply
        try:
            supply = self.chain.get_total_supply()
            if supply > 0:
                self.db.set_chain_stat("total_supply", supply, now)
                logger.info("Startup resync: total_supply=%d", supply)
        except Exception as e:
            logger.warning("Startup resync: total_supply failed: %s", e)

        # 2b. Auth params (tx_size_cost_per_byte)
        try:
            tx_size_ppb = int(self.chain.get_tx_size_cost_per_byte() or 0)
            if tx_size_ppb > 0:
                self.db.set_chain_stat("tx_size_cost_per_byte", tx_size_ppb, now)
        except Exception as e:
            logger.warning("Startup resync: tx_size_cost_per_byte failed: %s", e)

        # 3. Validator info (moniker, staked balance)
        try:
            self._sync_validator_info(now)
        except Exception as e:
            logger.warning("Startup resync: validator_info failed: %s", e)

        # 4. Difficulty snapshot
        try:
            diff_info = self.chain.get_difficulty_info()
            if diff_info:
                self.db.set_chain_stat("difficulty_info", diff_info, now)
        except Exception as e:
            logger.warning("Startup resync: difficulty_info failed: %s", e)

        # 5. Balance snapshot for all profiles + system wallets
        try:
            self._snapshot_all_balances(now)
        except Exception as e:
            logger.warning("Startup resync: balance snapshot failed: %s", e)

        # 6. Recent blocks (last 100)
        try:
            self._sync_recent_blocks()
        except Exception as e:
            logger.warning("Startup resync: recent blocks failed: %s", e)

        # 6b. Connected peers
        try:
            self._sync_connected_peers()
        except Exception as e:
            logger.warning("Startup resync: connected peers failed: %s", e)

        # 7. Indexer state
        status = self.chain.get_status()
        chain_height = int(((status.get("result") or {}).get("sync_info") or {}).get("latest_block_height", 0))
        self.db.set_indexer_state("chain_head_height", str(chain_height), now)
        logger.info("Startup resync complete")

    def _sync_validator_info(self, now: int):
        """Query validator info from chain and store in chain_stats."""
        try:
            from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2 as staking_query_pb2
            from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2_grpc as staking_query_pb2_grpc
            import grpc as _grpc

            with _grpc.insecure_channel(self.chain.grpc_target) as channel:
                stub = staking_query_pb2_grpc.QueryStub(channel)
                resp = stub.Validators(staking_query_pb2.QueryValidatorsRequest(), timeout=10)
                validators = []
                for v in resp.validators or []:
                    moniker = v.description.moniker if v.description else ""
                    tokens = str(v.tokens) if v.tokens else "0"
                    status = int(v.status)
                    oper_addr = v.operator_address or ""
                    validators.append(
                        {
                            "moniker": moniker,
                            "tokens": tokens,
                            "status": status,
                            "operator_address": oper_addr,
                        }
                    )
                self.db.set_chain_stat("validators", validators, now)
                logger.info("Startup resync: %d validators stored", len(validators))

                # Store total staked across all validators
                total_staked = sum(int(v.get("tokens") or 0) for v in validators)
                self.db.set_chain_stat("total_staked", total_staked, now)
        except Exception as e:
            logger.warning("_sync_validator_info failed: %s", e)

    def _snapshot_all_balances(self, now: int):
        """Snapshot balances for all profile owners + system wallets."""
        import os

        owners = []
        with self.db._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT owner FROM profiles")
                owners = [r[0] for r in cur.fetchall()]

        # Add system wallets from env or hardcoded
        system_wallets = [w.strip() for w in os.environ.get("INDEXER_SYSTEM_WALLETS", "").split(",") if w.strip()]
        all_addrs = list(set(owners + system_wallets))
        logger.info("Balance snapshot: querying %d addresses...", len(all_addrs))

        batch = []
        errors = 0
        for addr in all_addrs:
            try:
                bal = self.chain.get_balance(addr)
                batch.append((addr, bal))
            except Exception:
                errors += 1
                batch.append((addr, 0))

        self.db.upsert_balances_batch(batch, now)
        logger.info("Balance snapshot: upserted %d balances (%d errors)", len(batch), errors)

    def _sync_recent_blocks(self):
        """Fetch recent blocks from RPC and store hashes."""
        try:
            status = self.chain.get_status()
            latest = int(((status.get("result") or {}).get("sync_info") or {}).get("latest_block_height", 0))
            if latest <= 0:
                return
            start = max(1, latest - 99)
            for h in range(start, latest + 1):
                try:
                    blk = self.chain.get_block(h)
                    result = blk.get("result", {})
                    block = result.get("block", {})
                    header = block.get("header", {})
                    block_hash = result.get("block_id", {}).get("hash", "")
                    block_time = self.chain.parse_header_time(str(header.get("time", "")))
                    self.db.upsert_recent_block(h, block_hash, block_time)
                except Exception:
                    pass
        except Exception as e:
            logger.warning("_sync_recent_blocks failed: %s", e)

    def _sync_connected_peers(self):
        """Fetch connected peers from RPC and store in chain_stats."""
        info = self.chain.get_net_info()
        peers_data = ((info or {}).get("result") or {}).get("peers") or []
        peers: list[dict] = []
        seen_ips: set[str] = set()
        for peer in peers_data:
            ip = str(peer.get("remote_ip", "") or "").strip()
            if not ip or ip in seen_ips:
                continue
            node_info = peer.get("node_info") or {}
            moniker = str(node_info.get("moniker", "") or "").strip()
            peers.append({"ip": ip, "moniker": moniker})
            seen_ips.add(ip)
        self.db.set_chain_stat("connected_peers", peers, int(time.time()))

    def _update_per_block_state(self, height: int, header: dict, result_obj: dict, ts: int, block_hash: str):
        """Per-block updates: recent blocks, balances for touched addresses, indexer state."""
        now = int(time.time())

        # Store block hash (block_id.hash)
        try:
            self.db.upsert_recent_block(height, block_hash, ts)
            if height % 1000 == 0:
                self.db.prune_old_blocks(1000)
        except Exception:
            pass

        # Collect addresses touched by bank events from all event sources:
        # - txs_results: regular transactions
        # - end_block_events/finalize_block_events: governance execution (mints, burns, etc.)
        touched = set()

        all_events = []
        for tx_result in result_obj.get("txs_results") or []:
            all_events.extend(tx_result.get("events") or [])
        all_events.extend(result_obj.get("end_block_events") or result_obj.get("finalize_block_events") or [])
        all_events.extend(result_obj.get("begin_block_events") or [])

        for ev in all_events:
            ev_type = ev.get("type", "")
            if ev_type in ("transfer", "coin_spent", "coin_received"):
                for attr in ev.get("attributes") or []:
                    key = attr.get("key", "")
                    val = attr.get("value", "")
                    try:
                        key = base64.b64decode(key).decode("utf-8")
                    except Exception:
                        pass
                    try:
                        val = base64.b64decode(val).decode("utf-8")
                    except Exception:
                        pass
                    if key in ("sender", "recipient", "spender", "receiver") and val.startswith("mirage"):
                        touched.add(val.lower())

        # Refresh balances for touched addresses (bounded)
        MAX_BALANCE_REFRESH_PER_BLOCK = 200
        if touched:
            addrs = list(touched)[:MAX_BALANCE_REFRESH_PER_BLOCK]
            batch = []
            for addr in addrs:
                try:
                    bal = self.chain.get_balance(addr)
                    batch.append((addr, bal))
                except Exception:
                    pass
            if batch:
                self.db.upsert_balances_batch(batch, now)

        # Update indexer state
        self.db.set_indexer_state("last_processed_height", str(height), now)
        self.db.set_indexer_state("last_processed_time", str(now), now)

        # Periodically update chain head height
        if height % 10 == 0:
            try:
                status = self.chain.get_status()
                chain_height = int(((status.get("result") or {}).get("sync_info") or {}).get("latest_block_height", 0))
                if chain_height > 0:
                    self.db.set_indexer_state("chain_head_height", str(chain_height), now)
            except Exception:
                pass

        # Periodically refresh connected peers
        if height % 20 == 0:
            try:
                self._sync_connected_peers()
            except Exception as e:
                logger.warning("Connected peers refresh failed at height %s: %s", height, e)

        # Push summary flush handled by backend

    def _sync_profiles_from_chain(self):
        """
        Full KV reload for profiles from the blockchain at startup.
        Only profiles (not list tables like enabled_agents/blocked_*).
        """
        logger.info("KV Sync: Fetching profiles subspace from chain...")
        t0 = time.time()
        profiles = self.chain.list_profiles_subspace()
        t_fetch = time.time()
        logger.info("KV Sync: Fetched %d profiles in %.1fs", len(profiles), t_fetch - t0)

        now = int(time.time())
        batch = []
        for p in profiles:
            owner = str(p.get("owner", "")).strip().lower()
            if not owner:
                continue
            batch.append(
                (
                    owner,
                    p.get("username") or None,
                    int(p.get("level", 0) or 0),
                    int(p.get("created_at", 0) or 0),
                    int(p.get("subscription_expiry", 0) or 0),
                    bool(p.get("auto_renew", False)),
                    str(p.get("biography", "") or ""),
                    str(p.get("avatar", "") or ""),
                    str(p.get("banner", "") or ""),
                    str(p.get("flair", "") or ""),
                    int(p.get("reserve_funds", 0) or 0),
                )
            )

        self.db.upsert_profiles_batch(batch, now)
        t_upsert = time.time()
        logger.info(
            "KV Sync: Upserted %d profiles in %.1fs (total %.1fs)", len(batch), t_upsert - t_fetch, t_upsert - t0
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mirage Blockchain Indexer")
    parser.add_argument(
        "--height",
        type=int,
        default=None,
        help="Start replaying from this block height (overrides database last_height)",
    )
    args = parser.parse_args()

    try:
        from shared.logging_setup import configure_logging as _cfg
        import logging as _logging

        _cfg(component="indexer", level=_logging.INFO)
    except Exception:
        pass

    Indexer(start_height=args.height).start()
