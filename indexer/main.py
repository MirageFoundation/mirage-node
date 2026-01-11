#!/usr/bin/env python3
"""
Mirage Blockchain Indexer

IMPORTANT: API USAGE POLICY
- Use gRPC (port 9090) for all chain queries (governance, bank, etc.)
- Use RPC/HTTP (port 26657) only for Tendermint-specific queries (status, block_results, websocket)
- NEVER use REST API (port 1317) - it is not enabled and not used by the backend
- This matches the backend's API usage pattern for consistency
"""
import base64
import hashlib
import json
import os
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
        self._catch_up_mode: bool = False
        self._last_height = self.db.get_last_height()

        self._lock_file = None
        try:
            # Derive a stable lock directory under node home (not DB-specific)
            node_home = os.path.join(str(Path.home() / ".mirage"), "main")
            lock_dir = os.path.join(node_home, "data", "indexer")
            os.makedirs(lock_dir, exist_ok=True)
            lock_path = os.path.join(lock_dir, ".indexer.lock")
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
                            continue

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

                    if pending_proposals:
                        tx_events = txs_results[idx].get("events", []) if idx < len(txs_results) else []
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
        """Process governance events for passed proposals."""
        events = result_obj.get("end_block_events") or result_obj.get("finalize_block_events")
        if events is None:
            events = []
        if not events:
            return

        passed_ids = self.processor.extract_passed_proposals(events)
        for proposal_id in passed_ids:
            try:
                messages = self._proposal_cache.pop(proposal_id, None)
                if not messages:
                    if self._catch_up_mode:
                        try:
                            messages = self.chain.fetch_proposal_messages(proposal_id, TYPE_URL_TO_PROTO)
                        except RuntimeError as grpc_err:
                            if "no trackable messages" in str(grpc_err).lower():
                                logger.warning(
                                    "Skipping proposal %s - contains only governance-only messages (not tracked by indexer)",
                                    proposal_id,
                                )
                                continue
                            try:
                                messages = self.chain.fetch_submit_proposal_messages_via_tx_search(
                                    proposal_id,
                                    MessageProcessor.decode_events,
                                    MessageProcessor.extract_proposal_id,
                                    MessageProcessor.extract_inner_messages,
                                )
                            except RuntimeError as tx_err:
                                logger.warning(
                                    "Skipping proposal %s - unable to resolve messages during catch-up (gRPC error: %s, tx_search error: %s)",
                                    proposal_id,
                                    grpc_err,
                                    tx_err,
                                )
                                continue
                    else:
                        try:
                            messages = self.chain.fetch_submit_proposal_messages_via_tx_search(
                                proposal_id,
                                MessageProcessor.decode_events,
                                MessageProcessor.extract_proposal_id,
                                MessageProcessor.extract_inner_messages,
                            )
                        except RuntimeError as tx_err:
                            try:
                                messages = self.chain.fetch_proposal_messages(proposal_id, TYPE_URL_TO_PROTO)
                            except RuntimeError as grpc_err:
                                if "no trackable messages" in str(grpc_err).lower():
                                    logger.warning(
                                        "Skipping proposal %s - contains only governance-only messages (not tracked by indexer)",
                                        proposal_id,
                                    )
                                    continue
                                logger.warning(
                                    "Skipping proposal %s - unable to resolve messages (tx_search error: %s, gRPC error: %s)",
                                    proposal_id,
                                    tx_err,
                                    grpc_err,
                                )
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
                            self.db.upsert_difficulty(height, info["difficulty"], info["msg_count"], int(time.time()))
                        except Exception as diff_err:
                            logger.warning("Failed to record difficulty at height %s: %s", height, diff_err)
                        # Record supply every 200 blocks (aligns with mint interval)
                        if height % 200 == 0:
                            try:
                                supply = self.chain.get_total_supply()
                                if supply > 0:
                                    self.db.upsert_supply(height, supply, int(time.time()))
                            except Exception as supply_err:
                                logger.warning("Failed to record supply at height %s: %s", height, supply_err)
        except Exception as e:
            logger.error("Error processing message: %s", e, exc_info=True)

    def on_error(self, ws, error):
        logger.error("WebSocket error: %s", error)

    def on_close(self, ws, close_status_code, close_msg):
        logger.warning("WebSocket closed: %s - %s", close_status_code, close_msg)
        if self.running:
            self._reconnect()

    def on_open(self, ws):
        logger.info("WebSocket connected")
        ws.send(
            json.dumps({"jsonrpc": "2.0", "method": "subscribe", "id": 1, "params": {"query": "tm.event='NewBlock'"}})
        )

    def start_websocket(self):
        """Start WebSocket connection."""
        self.ws = self.chain.create_websocket_app(
            self.on_open,
            self.on_message,
            self.on_error,
            self.on_close,
        )
        self.chain.run_websocket_forever(self.ws, self.running)

    def _reconnect(self):
        """Reconnect loop with fixed retry delay."""
        attempt = 0
        delay = WS_RECONNECT_DELAY
        while self.running:
            attempt += 1
            try:
                if not self.chain.wait_for_rpc_ready():
                    time.sleep(delay)
                    continue

                logger.info("Reconnecting websocket (attempt %s, delay %ss)...", attempt, delay)
                self.start_websocket()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error("Reconnect error: %s", e, exc_info=True)
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

        self.running = True
        current_height = self._catch_up()
        logger.info("Transitioning to live mode (WebSocket)")
        try:
            self.start_websocket()
        except KeyboardInterrupt:
            pass

    def _sync_profiles_from_chain(self):
        """
        Full KV reload for profiles from the blockchain at startup.
        Only profiles (not list tables like followed_mods/blocked_*).
        """
        logger.info("KV Sync: Fetching profiles subspace from chain...")
        profiles = self.chain.list_profiles_subspace()
        now = int(time.time())
        num = 0
        for p in profiles:
            owner = str(p.get("owner", "")).strip().lower()
            if not owner:
                continue
            username = p.get("username") or None
            level = int(p.get("level", 0) or 0)
            created_at = int(p.get("created_at", 0) or 0)
            subscription_expiry = int(p.get("subscription_expiry", 0) or 0)
            auto_renew = bool(p.get("auto_renew", False))
            is_moderator = bool(p.get("is_moderator", False))
            biography = str(p.get("biography", "") or "")
            avatar = str(p.get("avatar", "") or "")
            banner = str(p.get("banner", "") or "")
            self.db.upsert_profile_full(
                owner,
                username,
                level,
                created_at,
                subscription_expiry,
                auto_renew,
                is_moderator,
                biography,
                avatar,
                banner,
                now,
            )
            num += 1
        logger.info("KV Sync: Upserted %d profiles from chain KV", num)


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

        _cfg(component="indexer", node_id=1, level=_logging.INFO)
    except Exception:
        pass

    Indexer(start_height=args.height).start()
