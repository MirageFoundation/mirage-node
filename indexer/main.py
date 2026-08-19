#!/usr/bin/env python3
"""
Mirage Blockchain Indexer

IMPORTANT: API USAGE POLICY
- Use gRPC (port 9090) for all chain queries (governance, bank, etc.)
- Use RPC/HTTP (port 26657) only for Tendermint-specific queries (status, block_results, websocket)
- NEVER use REST API (port 1317) - it is not enabled and not used by the backend

Correctness contract:
- Every required write for a block plus its checkpoint happen in ONE PostgreSQL
  transaction. A failure rolls the whole block back; the checkpoint never moves
  past a partially applied block.
- Optional telemetry (difficulty/supply samples, peers, head height) runs OUTSIDE
  that transaction and is warn-only.
- History is never silently skipped. When blocks are unreachable (pruning), the
  gap is recorded in meta.history_gaps and meta.history_complete flips to false.
"""
import atexit
import base64
import fcntl
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time

# Add parent directory to path for shared imports
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from indexer.database import (
    DatabaseManager,
    format_db_target,
    META_CHAIN_ID,
    META_LAST_BLOCK_HASH,
    META_LAST_HEIGHT,
)
from indexer.chain_client import ChainClient
from indexer.message_processor import MessageProcessor, TYPE_URL_TO_PROTO, attr_text
from indexer.migrations import run_migrations
from indexer import redgifs, rumble
from indexer.params import load_params as load_chain_params, get_raw_params
from indexer.settings import (
    CATCHUP_PROGRESS_INTERVAL,
    PROFILE_SYNC_MAX_ABSENT_FRACTION,
    WS_RECONNECT_DELAY,
    RPC_READY_MAX_WAIT,
    RPC_READY_RETRY_DELAY,
)
from shared.config import get_config
from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxRaw, TxBody
from google.protobuf.message import DecodeError

logger = logging.getLogger(__name__)

LOCK_PATH = "/tmp/mirage-indexer.lock"

# Non-checkpoint meta keys describing how trustworthy the indexed history is.
META_CONTINUITY_STATUS = "continuity_status"
META_HISTORY_GAPS = "history_gaps"
META_HISTORY_COMPLETE = "history_complete"

TYPE_URL_UPDATE_PARAMS = "/mirage.core.v1.MsgUpdateParams"

# Telemetry sampling intervals (blocks)
SUPPLY_SAMPLE_INTERVAL = 200
HEAD_HEIGHT_SAMPLE_INTERVAL = 10
PEERS_SAMPLE_INTERVAL = 20
BLOCK_PRUNE_INTERVAL = 1000
RECENT_BLOCKS_KEEP = 1000
REDGIFS_BACKFILL_INTERVAL = 20

# One pass resolves at most this many gifs, scanning at most this many rows to
# find them. RedGIFs answers one id per request, so the batch is what keeps a
# backlog from turning a block boundary into a long run of HTTP calls; the scan
# is larger because rows already known missing are skipped without a request.
REDGIFS_BACKFILL_BATCH = 5
REDGIFS_BACKFILL_SCAN = 50

# Rumble is far rarer than RedGIFs, and one answer settles both the thumbnail
# and the embed, so it needs less of both.
RUMBLE_BACKFILL_INTERVAL = 30
RUMBLE_BACKFILL_BATCH = 3
RUMBLE_BACKFILL_SCAN = 30

# Gifs the API said are gone, and the posts carrying them or carrying no
# resolvable id at all. Both are retried once per process rather than once per
# pass: a row that can never resolve would otherwise sit in the scan window
# forever, and enough of them would leave no room for rows that can. Bounded
# because it is memory, and a restart is a cheap re-check.
REDGIFS_MISSING_CAP = 10000


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
    # Attributes arrive as plain text (see attr_text); normalise only so downstream
    # JSON consumers (push_listener) get a consistent shape.
    decoded_events: list[dict] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        attrs_raw = ev.get("attributes") or []
        attrs: list[dict] = []
        for attr in attrs_raw:
            if not isinstance(attr, dict):
                continue
            attrs.append({"key": attr_text(attr.get("key")), "value": attr_text(attr.get("value"))})
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
        # The instance lock is taken before anything else touches the database:
        # a second process must never run migrations or write blocks concurrently.
        self._lock_file = None
        self._acquire_instance_lock()

        config = get_config()
        indexer_config = config.get_indexer_config()

        if not indexer_config["enabled"]:
            raise RuntimeError("Indexer disabled")

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

        # Migrations run in start() AFTER continuity verification so a diverged
        # or wrong-network database cannot be rewritten before we refuse to index.

        self.processor = MessageProcessor(
            self.db,
            self.chain,
            self._log_yaml,
            self.chain.iso_timestamp,
        )

        self._last_height = self.db.get_last_height()
        self._expected_chain_id: str | None = None

        # Replay into a populated database would double-apply cumulative rows
        # (topic stats, preferences, vote deltas). Only allowed on an empty DB.
        self._start_height_override = None if start_height is None else int(start_height)
        if self._start_height_override is not None and self._last_height > 0:
            raise RuntimeError(
                f"--height {self._start_height_override} rejected: database already holds checkpoint height "
                f"{self._last_height}. Replay is only supported against an empty indexer database."
            )

        self.running = False
        self.ws = None
        self._catch_up_mode: bool = False
        self._redgifs = redgifs.RedgifsResolver()
        self._redgifs_missing: set[str] = set()
        self._redgifs_skip: set[str] = set()
        self._rumble = rumble.RumbleResolver()
        self._rumble_skip: set[str] = set()

        try:
            import yaml as _yaml  # type: ignore

            self._yaml = _yaml
        except Exception:
            self._yaml = None

    def _acquire_instance_lock(self):
        """Take the exclusive single-instance lock or exit non-zero."""
        self._lock_path = LOCK_PATH
        self._lock_file = open(LOCK_PATH, "a+")
        try:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = ""
            try:
                self._lock_file.seek(0)
                holder = self._lock_file.read().strip()
            except Exception:
                pass
            try:
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None
            logger.error(
                "Another indexer instance already holds %s (pid=%s); refusing to start.",
                LOCK_PATH,
                holder or "unknown",
            )
            sys.exit(1)

        self._lock_file.seek(0)
        self._lock_file.truncate()
        self._lock_file.write(str(os.getpid()))
        self._lock_file.flush()
        atexit.register(self._release_lock)
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        logger.debug("instance_lock.acquired path=%s pid=%s", LOCK_PATH, os.getpid())

    def _release_lock(self):
        # The lock file itself is left in place: unlinking it would drop the
        # lock a newly started instance may already hold.
        lock_file = getattr(self, "_lock_file", None)
        if lock_file is None:
            return
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            lock_file.close()
        except Exception:
            pass
        self._lock_file = None
        logger.debug("instance_lock.released path=%s", getattr(self, "_lock_path", LOCK_PATH))

    def _verify_chain_id(self, height: int, chain_id: str) -> None:
        """Reject a block whose chain_id differs from the one this run has been projecting.

        `set_checkpoint` rewrites `meta.chain_id` from this value on every block, and the
        stored value is what the next startup verifies against. Left unchecked, a node
        restarted onto a different network mid-run would be absorbed silently and would
        overwrite the evidence that continuity verification exists to catch. Latched from
        the first block rather than queried per block, so this costs no round-trip;
        startup verification separately compares the stored id against the node.
        """
        if self._expected_chain_id is None:
            self._expected_chain_id = chain_id
            return
        if chain_id != self._expected_chain_id:
            raise RuntimeError(
                f"chain_id changed mid-run at height {height}: block header says {chain_id!r} "
                f"but this indexer has been projecting {self._expected_chain_id!r}"
            )

    def _handle_signal(self, signum, _frame):
        logger.info("Signal %s received; cleaning up lock and exiting.", signum)
        self.running = False
        ws = getattr(self, "ws", None)
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self._release_lock()
        # Conventional 128+signum rather than 0: this is an interruption, and a
        # supervisor reading 0 as a clean shutdown would leave the node unindexed
        # with nothing to alert on. Any in-flight block transaction rolls back.
        sys.exit(128 + int(signum))

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

    # ------------------------------------------------------------------
    # Block processing
    # ------------------------------------------------------------------

    def _process_block(self, height: int):
        """Project one block into PostgreSQL atomically, then advance the checkpoint."""
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
        block_hash = str((result.get("block_id") or {}).get("hash", "") or "")
        if not block_hash:
            raise RuntimeError(f"Missing block_id.hash at height {height}")
        chain_id = str(header.get("chain_id", "") or "")
        if not chain_id:
            raise RuntimeError(f"Missing header.chain_id at height {height}")
        self._verify_chain_id(height, chain_id)
        txs = (block.get("data") or {}).get("txs") or []
        ts = self.chain.parse_header_time(str(header.get("time", "")))

        results = self.chain.get_block_results_matching(height, len(txs))
        result_obj = results.get("result")
        if not result_obj:
            raise RuntimeError(f"Missing 'result' in block_results at height {height}")
        txs_results = result_obj.get("txs_results") or []
        if len(txs_results) != len(txs):
            raise RuntimeError(
                f"block/result cardinality mismatch at height {height}: txs={len(txs)} txs_results={len(txs_results)}"
            )

        now = int(time.time())
        logger.debug("block.begin height=%s txs=%d chain_id=%s hash=%s", height, len(txs), chain_id, block_hash)

        # Prefetch required balance reads BEFORE opening the block transaction so
        # a slow/failed gRPC call cannot hold row locks against other DB users.
        touched = self._collect_touched_addresses(result_obj)
        balances = self.chain.get_balances_batch(sorted(touched)) if touched else None

        self.chain.begin_block_profile_cache()
        try:
            with self.db.transaction(label="block", height=height):
                for idx, tx_b64 in enumerate(txs):
                    try:
                        self._process_tx(idx, tx_b64, txs_results[idx], height, ts)
                    except Exception as tx_err:
                        raise RuntimeError(f"Error processing tx {idx} at height {height}: {tx_err}") from tx_err

                self._process_governance_events(result_obj, ts, height)
                self._process_subscription_events(result_obj, ts, height)

                self.db.upsert_recent_block(height, block_hash, ts)
                if balances is not None:
                    self.db.upsert_balances_batch(sorted(balances.items()), now)
                    logger.debug("balances.refreshed height=%s addresses=%d", height, len(balances))
                self.db.set_indexer_state("last_processed_time", str(now), now)
                self.db.set_checkpoint(height, block_hash, chain_id)
        finally:
            self.chain.end_block_profile_cache()

        self._last_height = height
        logger.debug("block.committed height=%s", height)

        self._record_optional_telemetry(height)

    def _record_net_tag(self, tx_hash: str, tx_body, height: int, ts: int) -> None:
        """Project the network tag a relayer published in the tx memo.

        The memo is attacker-controlled: anyone who pays a fee can write
        anything there, including a copied namespace. Everything stored here is
        therefore a claim by the relayer named alongside it, and it is only
        meaningful when scoped to relayers the reader trusts.
        """
        from indexer.message_processor import relayer_from_message
        from shared.nettag import STATUS_ABSENT, STATUS_INVALID, parse_memo

        parsed = parse_memo(tx_body.memo)
        if parsed.status == STATUS_ABSENT:
            return
        if parsed.status == STATUS_INVALID:
            logger.warning(
                "net_tag.invalid height=%s txhash=%s reason=%s",
                height,
                tx_hash,
                parsed.reason,
            )
            return

        relayer = ""
        for any_msg in tx_body.messages:
            if any_msg.type_url.startswith("/mirage.core.v1."):
                relayer = relayer_from_message(any_msg.type_url, any_msg.value)
                break
        if not relayer:
            # An unattributed tag has no trustworthy scope and is analytically
            # worthless. Skipping it also prevents ordinary bank transactions
            # from polluting the permanent table with copied tags.
            logger.warning(
                "net_tag.unattributed height=%s txhash=%s; not storing",
                height,
                tx_hash,
            )
            return

        self.db.upsert_net_tag(
            tx_hash,
            parsed.namespace,
            parsed.epoch,
            parsed.family,
            parsed.tag,
            parsed.net_class,
            relayer,
            height,
            ts,
        )
        logger.debug(
            "net_tag.stored height=%s txhash=%s epoch=%s family=%s class=%s relayer=%s",
            height,
            tx_hash,
            parsed.epoch,
            parsed.family,
            parsed.net_class,
            relayer,
        )

    def _process_tx(self, idx: int, tx_b64: str, tx_result: dict, height: int, ts: int):
        """Decode and project one transaction. Must run inside the block transaction."""
        raw_tx_bytes = base64.b64decode(tx_b64)
        tx_hash = hashlib.sha256(raw_tx_bytes).hexdigest().lower()

        tx_raw = TxRaw()
        tx_body = TxBody()
        try:
            tx_raw.ParseFromString(raw_tx_bytes)
            tx_body.ParseFromString(tx_raw.body_bytes)
        except (DecodeError, UnicodeDecodeError) as exc:
            # Go does not UTF-8-validate protobuf string fields. Python does, so
            # a memo the chain accepted can still fail here. Aborting the block
            # then exiting would wedge every indexer on one undecodable tx.
            logger.error(
                "tx.decode_failed height=%s idx=%s txhash=%s err=%s",
                height,
                idx,
                tx_hash,
                exc,
            )
            self.db.upsert_tx_index(tx_hash, "undecodable", -1, str(exc), height, ts)
            return

        from indexer.message_processor import type_url_to_tx_type

        core_types = [m.type_url for m in tx_body.messages if m.type_url.startswith("/mirage.core.v1.")]
        code = int(tx_result.get("code", 0) or 0)

        if code != 0:
            tx_type = type_url_to_tx_type(core_types[0]) if core_types else "unknown"
            raw_log = str(tx_result.get("log", "") or "")
            self.db.upsert_tx_index(tx_hash, tx_type, code, raw_log, height, ts)
            logger.debug(
                "tx.failed height=%s code=%s tx_type=%s txhash=%s",
                height,
                code,
                tx_type,
                tx_hash,
            )
            return

        # Only a successful transaction has a chain-validated authority. A
        # failed transaction may contain an arbitrary authority string supplied
        # by a proposer, so projecting it would make relayer attribution false
        # and could feed unbounded text into the relayer index.
        self._record_net_tag(tx_hash, tx_body, height, ts)

        if core_types:
            tx_type = type_url_to_tx_type(core_types[0]) if len(core_types) == 1 else "multi"
            raw_entry = tx_result.get("log")
            raw_log = "" if raw_entry is None else str(raw_entry)
            if tx_type in ("send_tokens", "multi") and raw_log == "":
                raw_log = _synthesize_raw_log(tx_result, height, tx_hash)
            self.db.upsert_tx_index(tx_hash, tx_type, 0, raw_log, height, ts)

        for any_msg in tx_body.messages:
            # Governance traffic is resolved from passed-proposal events, never
            # from the submitting tx: a submitted proposal is not an applied one.
            if any_msg.type_url.startswith("/cosmos.gov."):
                continue
            if not any_msg.type_url.startswith("/mirage.core.v1."):
                continue
            self.processor.process_core_message(any_msg.type_url, any_msg.value, tx_hash, ts, height)

    def _process_subscription_events(self, result_obj: dict, ts: int, height: int):
        """Process subscription expiration/renewal events from EndBlock."""
        events = result_obj.get("end_block_events") or result_obj.get("finalize_block_events")
        if not events:
            return

        for event in events:
            event_type = event.get("type", "")
            if event_type not in ("subscription_expired", "subscription_renewed"):
                continue
            attrs = {attr_text(a.get("key")): attr_text(a.get("value")) for a in event.get("attributes", [])}
            address = attrs.get("address", "")
            if not address:
                raise RuntimeError(f"{event_type} event without address at height {height}")

            if event_type == "subscription_expired":
                logger.info("Subscription expired for %s (reason: %s)", address, attrs.get("reason", "unknown"))
                self.processor.update_profile_level(address, 0, ts)
            else:
                level = int(attrs.get("level", "0") or 0)
                new_expiry = int(attrs.get("new_expiry", "0") or 0)
                logger.info(
                    "Subscription renewed for %s (level: %d, new_expiry: %d)",
                    address,
                    level,
                    new_expiry,
                )
                self.processor.update_profile_subscription(address, level, new_expiry, ts)

    def _process_governance_events(self, result_obj: dict, ts: int, height: int):
        """Apply the messages of every proposal that passed in this block.

        Fails closed: an unresolvable passed proposal rolls the block back rather
        than advancing the checkpoint past a governance action that was never applied.
        The one tolerated case is a proposal whose messages the indexer does not
        track at all (e.g. governance-only mint/burn).
        """
        events = result_obj.get("end_block_events") or result_obj.get("finalize_block_events") or []
        if not events:
            return

        passed_ids = self.processor.extract_passed_proposals(events)
        if not passed_ids:
            return
        logger.debug("governance.passed height=%s proposals=%s", height, passed_ids)

        params_updated = False
        for proposal_id in passed_ids:
            try:
                messages = self.chain.fetch_proposal_messages(proposal_id, TYPE_URL_TO_PROTO)
            except RuntimeError as grpc_err:
                if "no trackable messages" in str(grpc_err).lower():
                    logger.warning(
                        "Proposal %s carries no indexer-tracked messages; nothing to project (height=%s)",
                        proposal_id,
                        height,
                    )
                    continue
                raise

            for entry in messages:
                type_url = entry.get("type_url")
                value_b64 = entry.get("value")
                if not type_url or not value_b64:
                    raise RuntimeError(f"Proposal {proposal_id} returned a message without type_url/value")
                value_bytes = base64.b64decode(value_b64)
                self.processor.process_core_message(type_url, value_bytes, f"proposal-{proposal_id}", ts, height)
                if type_url == TYPE_URL_UPDATE_PARAMS:
                    params_updated = True

        if params_updated:
            load_chain_params(self.chain.grpc_target, force=True)
            self.db.set_chain_stat("chain_params", get_raw_params(), int(time.time()))
            logger.info("Chain params reloaded after governance update at height %s", height)

    @staticmethod
    def _collect_touched_addresses(result_obj: dict) -> set[str]:
        """Addresses whose balance may have changed in this block."""
        all_events: list[dict] = []
        for tx_result in result_obj.get("txs_results") or []:
            all_events.extend(tx_result.get("events") or [])
        all_events.extend(result_obj.get("end_block_events") or result_obj.get("finalize_block_events") or [])
        all_events.extend(result_obj.get("begin_block_events") or [])

        touched: set[str] = set()
        for ev in all_events:
            if ev.get("type", "") not in ("transfer", "coin_spent", "coin_received"):
                continue
            for attr in ev.get("attributes") or []:
                key = attr_text(attr.get("key"))
                val = attr_text(attr.get("value"))
                if key in ("sender", "recipient", "spender", "receiver") and val.startswith("mirage"):
                    touched.add(val.lower())
        return touched

    def _record_optional_telemetry(self, height: int):
        """Chart/ops samples taken after the block is committed. Never fatal.

        These read the CURRENT chain head, so they are only meaningful in live
        mode where head and the just-committed height coincide.
        """
        now = int(time.time())

        if height % BLOCK_PRUNE_INTERVAL == 0:
            try:
                self.db.prune_old_blocks(RECENT_BLOCKS_KEEP)
            except Exception as e:
                logger.warning("Telemetry: prune_old_blocks failed at height %s: %s", height, e)

        if self._catch_up_mode:
            return

        try:
            info = self.chain.get_difficulty_info()
            self.db.upsert_difficulty(
                height,
                int(info.get("current_difficulty", 0)),
                int(info.get("pow_message_count", 0)),
                now,
            )
            self.db.set_chain_stat("difficulty_info", info, now)
        except Exception as e:
            logger.warning("Telemetry: difficulty sample failed at height %s: %s", height, e)

        if height % SUPPLY_SAMPLE_INTERVAL == 0:
            try:
                supply = self.chain.get_total_supply()
                node_balance = self.chain.get_balance(self._validator_address) if self._validator_address else None
                node_staked = (
                    self.chain.get_staked_balance(self._validator_address) if self._validator_address else None
                )
                self.db.upsert_supply(
                    height,
                    supply,
                    now,
                    node_balance=node_balance,
                    node_staked=node_staked,
                )
                self.db.set_chain_stat("total_supply", supply, now)
            except Exception as e:
                logger.warning("Telemetry: supply sample failed at height %s: %s", height, e)

        if height % HEAD_HEIGHT_SAMPLE_INTERVAL == 0:
            try:
                self.db.set_indexer_state("chain_head_height", str(self.chain.get_current_height()), now)
            except Exception as e:
                logger.warning("Telemetry: chain head refresh failed at height %s: %s", height, e)

        if height % PEERS_SAMPLE_INTERVAL == 0:
            try:
                self._sync_connected_peers()
            except Exception as e:
                logger.warning("Telemetry: connected peers refresh failed at height %s: %s", height, e)

        if height % REDGIFS_BACKFILL_INTERVAL == 0:
            try:
                self._backfill_redgifs_thumbnails()
            except Exception as e:
                logger.warning("Telemetry: redgifs thumbnail backfill failed at height %s: %s", height, e)

        if height % RUMBLE_BACKFILL_INTERVAL == 0:
            try:
                self._backfill_rumble_media()
            except Exception as e:
                logger.warning("Telemetry: rumble media backfill failed at height %s: %s", height, e)

    def _backfill_redgifs_thumbnails(self) -> None:
        """Fill in thumbnails for RedGIFs posts, which cannot be derived offline.

        Runs here rather than in the message path on purpose. A network call
        while a block is being projected would let a slow third party stall
        indexing, and a rebuild would replay it once per historical post; from
        here it is post-commit, skipped entirely during catch-up, and capped
        per pass. Nothing downstream changes: the value lands in the same
        posts.thumbnail_url column the offline derivation writes, so the
        backend and the clients need to know nothing about any of this.

        An edit resets the column to the offline derivation, which for RedGIFs
        is empty. That post simply becomes a candidate again on a later pass.
        """
        candidates = self.db.select_redgifs_posts_missing_thumbnail(
            REDGIFS_BACKFILL_SCAN, sorted(self._redgifs_skip)
        )
        if not candidates:
            return

        resolved = 0
        filled = 0
        for txhash, media_raw, content in candidates:
            if resolved >= REDGIFS_BACKFILL_BATCH:
                break
            try:
                media = json.loads(media_raw or "[]")
            except (ValueError, TypeError):
                media = []
            gif_id = redgifs.find_gif_id(media if isinstance(media, list) else [], content)
            if not gif_id:
                # Mentions redgifs.com but carries no id — a bare domain, or a
                # link shape this does not read. Nothing to ask about.
                self._skip_redgifs_post(txhash)
                continue
            if gif_id in self._redgifs_missing:
                self._skip_redgifs_post(txhash)
                continue

            # A transport failure aborts the pass rather than the row: if the
            # API is unreachable the next id will not fare better, and the
            # caller logs it once.
            url = self._redgifs.resolve_thumbnail(gif_id)
            resolved += 1
            if url is None:
                if len(self._redgifs_missing) < REDGIFS_MISSING_CAP:
                    self._redgifs_missing.add(gif_id)
                self._skip_redgifs_post(txhash)
                logger.info("[redgifs] no thumbnail for %s (gone or private)", gif_id)
                continue
            self.db.update_post_thumbnail(txhash, url)
            filled += 1
            logger.info("[redgifs] thumbnail for tx=%s id=%s -> %s", txhash[:12], gif_id, url)

        if filled:
            logger.info("[redgifs] backfilled %d thumbnail(s) from %d candidate(s)", filled, len(candidates))

    def _skip_redgifs_post(self, txhash: str) -> None:
        """Keep a row that cannot resolve out of the next scan window."""
        if len(self._redgifs_skip) < REDGIFS_MISSING_CAP:
            self._redgifs_skip.add(txhash)

    def _backfill_rumble_media(self) -> None:
        """Resolve Rumble posts to their thumbnail and their real embed id.

        The embed id is not cosmetic. Rumble's watch ids and embed ids are
        different namespaces that collide, so an embed built from the watch id
        plays an unrelated video rather than failing. Until this has run, the
        clients have no correct id and must not guess one.

        Same placement rationale as the RedGIFs pass: post-commit, never fatal,
        never during catch-up, capped per pass.
        """
        candidates = self.db.select_rumble_posts_needing_resolution(
            RUMBLE_BACKFILL_SCAN, sorted(self._rumble_skip)
        )
        if not candidates:
            return

        resolved = 0
        for txhash, media_raw, content, meta_raw, thumbnail in candidates:
            if resolved >= RUMBLE_BACKFILL_BATCH:
                break
            try:
                media = json.loads(media_raw or "[]")
            except (ValueError, TypeError):
                media = []
            watch_url = rumble.find_watch_url(media if isinstance(media, list) else [], content)
            if not watch_url:
                self._skip_rumble_post(txhash)
                continue

            # As with RedGIFs, an outage ends the pass rather than the row.
            answer = self._rumble.resolve(watch_url)
            resolved += 1
            if answer is None:
                self._skip_rumble_post(txhash)
                logger.info("[rumble] nothing to resolve for %s (gone or private)", watch_url)
                continue

            # Only fill an empty thumbnail. A post that already has one got it
            # from the offline derivation, which prefers the author's own
            # attached image — that choice outranks the video's poster frame.
            if answer["thumbnail"] and not thumbnail:
                self.db.update_post_thumbnail(txhash, answer["thumbnail"])
            if answer["embed_id"]:
                self.db.update_post_media_meta(
                    txhash, self._media_meta_with_embed(meta_raw, answer["embed_id"])
                )
            logger.info(
                "[rumble] tx=%s embed=%s thumb=%s",
                txhash[:12],
                answer["embed_id"],
                (answer["thumbnail"] or "")[:60],
            )
            if not answer["embed_id"]:
                # Nothing more to learn about this one, and it would otherwise
                # keep matching the "no embed" half of the candidate test.
                self._skip_rumble_post(txhash)

    @staticmethod
    def _media_meta_with_embed(meta_raw: str, embed_id: str) -> str:
        """Set the embed id on the first media-meta slot, preserving the rest.

        Slot 0 because that is the one the clients read alongside the post's
        first link, which is the only place find_watch_url looks.
        """
        try:
            meta = json.loads(meta_raw or "[]")
        except (ValueError, TypeError):
            meta = []
        if not isinstance(meta, list):
            meta = []
        if not meta:
            meta = [{}]
        if not isinstance(meta[0], dict):
            meta[0] = {}
        meta[0]["embed"] = embed_id
        return json.dumps(meta)

    def _skip_rumble_post(self, txhash: str) -> None:
        """Keep a row that cannot resolve out of the next scan window."""
        if len(self._rumble_skip) < REDGIFS_MISSING_CAP:
            self._rumble_skip.add(txhash)

    # ------------------------------------------------------------------
    # Continuity / history bookkeeping
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_history_gaps(gaps: list[dict]) -> list[dict]:
        """Normalize and merge overlapping/adjacent gap ranges.

        Reasons may differ for the same span (continuity vs catch-up); overlapping
        or adjacent ranges are coalesced and reasons are unioned.
        """
        normalized: list[dict] = []
        for gap in gaps:
            start = int(gap.get("start", 0) or 0)
            end = int(gap.get("end", 0) or 0)
            if start < 1 or end < start:
                raise RuntimeError(f"invalid history gap record start={start} end={end}")
            normalized.append({"start": start, "end": end, "reason": str(gap.get("reason", "") or "unknown")})

        normalized.sort(key=lambda g: (g["start"], g["end"]))
        merged: list[dict] = []
        for gap in normalized:
            if merged and gap["start"] <= merged[-1]["end"] + 1:
                merged[-1]["end"] = max(merged[-1]["end"], gap["end"])
                if gap["reason"] != merged[-1]["reason"]:
                    reasons = {r for r in merged[-1]["reason"].split("|") if r} | {gap["reason"]}
                    merged[-1]["reason"] = "|".join(sorted(reasons))
                continue
            merged.append(dict(gap))
        return merged

    def _record_history_gap(self, start: int, end: int, reason: str):
        """Persist a range of blocks this indexer will never have indexed."""
        if end < start:
            raise RuntimeError(f"history gap end {end} precedes start {start}")
        raw = self.db.get_meta(META_HISTORY_GAPS) or "[]"
        try:
            existing = json.loads(raw)
        except Exception as e:
            raise RuntimeError(f"meta.{META_HISTORY_GAPS} is not valid JSON: {raw!r}") from e
        if not isinstance(existing, list):
            raise RuntimeError(f"meta.{META_HISTORY_GAPS} is not a list: {raw!r}")

        merged = self._merge_history_gaps(existing + [{"start": int(start), "end": int(end), "reason": reason}])
        self.db.set_meta(META_HISTORY_GAPS, json.dumps(merged))
        self.db.set_meta(META_HISTORY_COMPLETE, "false")
        logger.warning(
            "HISTORY GAP recorded: blocks %s-%s will never be indexed (reason=%s, total_gaps=%d)",
            start,
            end,
            reason,
            len(merged),
        )

    def _verify_chain_continuity(self):
        """Refuse to keep indexing onto a chain that is not the one already in the DB.

        Recovery preserves PostgreSQL, so a diverged/reset/wrong-network node would
        otherwise keep serving rows from blocks that are not on the canonical chain.
        """
        node_chain_id = self.chain.get_chain_id()
        stored_chain_id = self.db.get_meta(META_CHAIN_ID)
        stored_height = self.db.get_last_height()
        stored_hash = self.db.get_meta(META_LAST_BLOCK_HASH)
        logger.debug(
            "continuity.check node_chain_id=%s stored_chain_id=%s stored_height=%s stored_hash=%s",
            node_chain_id,
            stored_chain_id,
            stored_height,
            stored_hash,
        )

        if stored_height <= 0:
            if stored_chain_id and stored_chain_id != node_chain_id:
                raise RuntimeError(
                    f"chain identity mismatch: database was built against chain_id {stored_chain_id!r} "
                    f"but the node reports {node_chain_id!r}. Refusing to index."
                )
            self.db.set_meta(META_CONTINUITY_STATUS, "fresh")
            logger.info("Continuity: fresh database, chain_id=%s", node_chain_id)
            return

        if stored_chain_id and stored_chain_id != node_chain_id:
            raise RuntimeError(
                f"chain identity mismatch at checkpoint height {stored_height}: database chain_id "
                f"{stored_chain_id!r} vs node chain_id {node_chain_id!r}. Refusing to index."
            )

        current_height = self.chain.get_current_height()
        if stored_height > current_height:
            raise RuntimeError(
                f"checkpoint height {stored_height} is ahead of the node head {current_height}. "
                "The node was rolled back or reset; the indexed rows above the head are not canonical."
            )

        earliest = self.chain.get_earliest_height()
        if stored_height < earliest:
            if not stored_chain_id:
                raise RuntimeError(
                    f"database holds {META_LAST_HEIGHT}={stored_height} but no {META_CHAIN_ID}, and every block "
                    f"that could identify the chain it was built from has been pruned (node retains from "
                    f"{earliest}). Restore a trusted dump or start from an empty database."
                )
            self.db.set_meta(META_CONTINUITY_STATUS, "unverified_pruned_gap")
            # stored_height + 1 == earliest means the DB ends exactly where the
            # node's retained history starts: no block is missing, there is just
            # no overlap left to compare hashes against.
            if stored_height + 1 <= earliest - 1:
                self._record_history_gap(stored_height + 1, earliest - 1, "pruned_before_verification")
            logger.warning(
                "Continuity UNVERIFIED: checkpoint height %s is below the node's earliest retained height %s. "
                "The overlap needed to compare block hashes was pruned; continuing.",
                stored_height,
                earliest,
            )
            return

        # Compare every retained recent_blocks row against the node BEFORE any
        # startup upsert can overwrite the evidence of a divergence.
        verified_hashes: dict[int, str] = {}
        for row in self.db.get_recent_block_hashes(limit=500):
            h = int(row.get("height") or 0)
            stored_row_hash = str(row.get("hash") or "")
            if h < earliest or h > current_height or not stored_row_hash:
                continue
            blk_row = self.chain.get_block(h)
            node_row_hash = str((((blk_row or {}).get("result") or {}).get("block_id") or {}).get("hash", "") or "")
            if not node_row_hash:
                raise RuntimeError(f"node returned no block_id.hash for recent_blocks height {h}")
            if node_row_hash.lower() != stored_row_hash.lower():
                raise RuntimeError(
                    f"BLOCK HASH MISMATCH in recent_blocks at height {h}: database has {stored_row_hash} but the node "
                    f"has {node_row_hash}. Leaving evidence untouched; restore a trusted dump or rebuild."
                )
            verified_hashes[h] = node_row_hash

        if not stored_hash:
            # A database written before the checkpoint carried provenance holds the same
            # evidence in recent_blocks: the hash the old indexer recorded for the
            # checkpoint block as it projected it. Adopt it only when the node confirms
            # that hash, so a diverged database is still refused.
            adopted_hash = verified_hashes.get(stored_height)
            if not adopted_hash:
                raise RuntimeError(
                    f"database holds {META_LAST_HEIGHT}={stored_height} but neither {META_CHAIN_ID}/"
                    f"{META_LAST_BLOCK_HASH} in meta nor a node-confirmed recent_blocks row at that height. "
                    "Its provenance cannot be verified; restore a trusted dump or start from an empty database."
                )
            self.db.set_meta(META_CHAIN_ID, node_chain_id)
            self.db.set_meta(META_LAST_BLOCK_HASH, adopted_hash)
            self.db.set_meta(META_CONTINUITY_STATUS, "adopted")
            logger.warning(
                "Continuity ADOPTED: database carried no recorded provenance; %s recent_blocks rows match the node "
                "and the checkpoint at height %s confirms as %s. Recording chain_id=%s.",
                len(verified_hashes),
                stored_height,
                adopted_hash,
                node_chain_id,
            )
            return

        blk = self.chain.get_block(stored_height)
        node_hash = str((((blk or {}).get("result") or {}).get("block_id") or {}).get("hash", "") or "")
        if not node_hash:
            raise RuntimeError(f"node returned no block_id.hash for checkpoint height {stored_height}")
        if node_hash.lower() != stored_hash.lower():
            raise RuntimeError(
                f"BLOCK HASH MISMATCH at checkpoint height {stored_height}: database has {stored_hash} but the node "
                f"has {node_hash}. The indexed rows come from a diverged chain. Restore a trusted PostgreSQL dump "
                "or rebuild from an empty database; do NOT keep indexing."
            )

        self.db.set_meta(META_CONTINUITY_STATUS, "verified")
        logger.info(
            "Continuity verified: chain_id=%s checkpoint height=%s hash=%s",
            node_chain_id,
            stored_height,
            stored_hash,
        )

    # ------------------------------------------------------------------
    # Catch-up and live mode
    # ------------------------------------------------------------------

    def _catch_up(self):
        """Replay every block from the checkpoint to the head. Gaps are recorded, never hidden."""
        logger.info("=" * 60)
        logger.info("INDEXER CATCHUP: Starting catchup process")
        logger.info("=" * 60)

        current_height = self.chain.get_current_height()
        earliest = max(1, self.chain.get_earliest_height())
        last_height = self.db.get_last_height()
        logger.info(
            "Chain head=%s earliest retained=%s database checkpoint=%s",
            current_height,
            earliest,
            last_height,
        )

        if self._start_height_override is not None:
            start = max(1, self._start_height_override)
            gap_reason = "height_override"
            logger.info("Starting from height %s (--height override)", start)
            if start > 1:
                # Only allowed on an empty database, so everything below `start` is
                # simply never indexed. Recorded here because the check below only
                # fires when the range was pruned, and without a gap row the backend
                # defaults history_complete to true and reports a partial index as
                # complete.
                self._record_history_gap(1, start - 1, gap_reason)
        elif last_height > 0:
            start = last_height + 1
            gap_reason = "checkpoint_behind_pruning_window"
        else:
            start = 1
            gap_reason = "fresh_start_pruned"

        if start < earliest:
            self._record_history_gap(start, earliest - 1, gap_reason)
            start = earliest

        end = current_height
        if start > end:
            logger.info("No catchup needed: already at current height %s", current_height)
            return current_height

        total_blocks = end - start + 1
        logger.info("Catchup range: blocks %s to %s (total: %s blocks)", start, end, total_blocks)
        logger.info("Catchup started at: %s", self.chain.iso_timestamp(int(time.time())))
        self._catch_up_mode = True
        catchup_start_time = time.time()
        try:
            for height in range(start, end + 1):
                self._process_block(height)
                if height % CATCHUP_PROGRESS_INTERVAL == 0:
                    processed = height - start + 1
                    elapsed = time.time() - catchup_start_time
                    rate = processed / elapsed if elapsed > 0 else 0
                    eta_seconds = (end - height) / rate if rate > 0 else 0
                    logger.info(
                        "Catchup progress: processed %s / %s blocks (%.1f blocks/sec, ~%.0f seconds remaining)",
                        processed,
                        total_blocks,
                        rate,
                        eta_seconds,
                    )
        finally:
            self._catch_up_mode = False

        elapsed_total = time.time() - catchup_start_time
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
        return current_height

    def on_message(self, ws, message):
        """Handle WebSocket message. Projection failure exits non-zero — never leave a stuck live loop."""
        try:
            data = json.loads(message)
            block_data = (((data.get("result") or {}).get("data") or {}).get("value") or {}).get("block")
            if not block_data:
                return
            height = int((block_data.get("header") or {}).get("height", 0) or 0)
            if height <= 0 or height <= self._last_height:
                return
            # Close any gap the socket skipped; _process_block advances the checkpoint.
            for h in range(self._last_height + 1, height + 1):
                self._process_block(h)
        except Exception as e:
            logger.error("Fatal error processing live block message: %s", e, exc_info=True)
            self.running = False
            try:
                ws.close()
            except Exception:
                pass
            self._release_lock()
            sys.exit(1)

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
        logger.info("Indexer database: %s", format_db_target(self.db.database_url))

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

        # Identity/continuity must be settled before migrations or recent-block
        # overwrites can destroy the evidence of a divergence.
        self._verify_chain_continuity()

        migration_count = run_migrations(self.db, self.chain)
        if migration_count > 0:
            logger.info("Completed %d migrations", migration_count)

        self._sync_profiles_from_chain()
        self._startup_resync()

        self.running = True
        self._catch_up()

        logger.info("Transitioning to live mode (WebSocket)")
        try:
            self._run_websocket_loop()
        except KeyboardInterrupt:
            pass

    def _startup_resync(self):
        """Refresh mutable chain state on startup. Required — a failure aborts startup."""
        now = int(time.time())
        logger.info("Startup resync: refreshing chain stats, params, balances...")

        self.db.set_chain_stat("chain_params", get_raw_params(), now)

        supply = self.chain.get_total_supply()
        self.db.set_chain_stat("total_supply", supply, now)
        logger.info("Startup resync: total_supply=%d", supply)

        self.db.set_chain_stat("tx_size_cost_per_byte", int(self.chain.get_tx_size_cost_per_byte()), now)

        self._sync_validator_info(now)
        self.db.set_chain_stat("difficulty_info", self.chain.get_difficulty_info(), now)
        self._snapshot_all_balances(now)
        self._sync_recent_blocks()
        self._sync_connected_peers()

        self.db.set_indexer_state("chain_head_height", str(self.chain.get_current_height()), now)
        logger.info("Startup resync complete")

    def _sync_validator_info(self, now: int):
        """Query validator info from chain and store in chain_stats."""
        from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2 as staking_query_pb2
        from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2_grpc as staking_query_pb2_grpc
        import grpc as _grpc

        with _grpc.insecure_channel(self.chain.grpc_target) as channel:
            stub = staking_query_pb2_grpc.QueryStub(channel)
            resp = stub.Validators(staking_query_pb2.QueryValidatorsRequest(), timeout=10)

        validators = []
        for v in resp.validators or []:
            validators.append(
                {
                    "moniker": v.description.moniker if v.description else "",
                    "tokens": str(v.tokens) if v.tokens else "0",
                    "status": int(v.status),
                    "operator_address": v.operator_address or "",
                }
            )
        self.db.set_chain_stat("validators", validators, now)
        self.db.set_chain_stat("total_staked", sum(int(v["tokens"] or 0) for v in validators), now)
        logger.info("Startup resync: %d validators stored", len(validators))

    def _snapshot_all_balances(self, now: int):
        """Snapshot balances for all profile owners + system wallets."""
        with self.db._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT owner FROM profiles")
                owners = [r[0] for r in cur.fetchall()]

        system_wallets = [w.strip() for w in os.environ.get("INDEXER_SYSTEM_WALLETS", "").split(",") if w.strip()]
        if self._validator_address:
            system_wallets.append(self._validator_address)
        all_addrs = sorted({str(a).lower() for a in owners + system_wallets if a})
        logger.info("Balance snapshot: querying %d addresses...", len(all_addrs))

        balances = self.chain.get_balances_batch(all_addrs)
        self.db.upsert_balances_batch(sorted(balances.items()), now)
        logger.info("Balance snapshot: upserted %d balances", len(balances))

    def _sync_recent_blocks(self):
        """Fetch recent blocks from RPC and store hashes."""
        latest = self.chain.get_current_height()
        earliest = max(1, self.chain.get_earliest_height())
        start = max(earliest, latest - 99)
        for h in range(start, latest + 1):
            blk = self.chain.get_block(h)
            result = blk.get("result") or {}
            header = (result.get("block") or {}).get("header") or {}
            block_hash = str((result.get("block_id") or {}).get("hash", "") or "")
            if not block_hash:
                raise RuntimeError(f"recent block sync: missing block_id.hash at height {h}")
            self.db.upsert_recent_block(h, block_hash, self.chain.parse_header_time(str(header.get("time", ""))))
        logger.debug("recent_blocks.synced start=%s end=%s", start, latest)

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
            peers.append({"ip": ip, "moniker": str(node_info.get("moniker", "") or "").strip()})
            seen_ips.add(ip)
        self.db.set_chain_stat("connected_peers", peers, int(time.time()))

    def _sync_profiles_from_chain(self):
        """Reconcile the profile tables against chain state. Required — a failure aborts startup.

        Scalars and hard-capped lists (agents, follows) are authoritative from the
        chain. Blocked lists are merged, never cleared: the chain keeps a small
        deque while the indexer intentionally retains the full history.
        """
        logger.info("KV Sync: Fetching profiles from chain...")
        t0 = time.time()
        profiles = self.chain.list_profiles_paginated()
        t_fetch = time.time()
        logger.info("KV Sync: Fetched %d profiles in %.1fs", len(profiles), t_fetch - t0)

        now = int(time.time())
        chain_owners: set[str] = set()
        batch = []
        for p in profiles:
            owner = str(p.get("owner", "")).strip().lower()
            if not owner:
                raise RuntimeError("chain returned a profile with an empty owner")
            chain_owners.add(owner)
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

        with self.db.transaction(label="profile_sync"):
            self.db.upsert_profiles_batch(batch, now)

            for p in profiles:
                owner = str(p.get("owner", "")).strip().lower()
                self.db.set_enabled_agents(owner, [str(a).lower() for a in p.get("enabled_agents") or []])
                self.db.set_followed_users(owner, [str(u).lower() for u in p.get("followed_users") or []])
                self.db.set_followed_topics(owner, [str(t) for t in p.get("followed_topics") or []])
                for target in p.get("blocked_users") or []:
                    self.db.block_user(owner, str(target).lower(), now)
                for target in p.get("blocked_posts") or []:
                    self.db.block_post(owner, str(target).lower(), now)
                for target in p.get("blocked_topics") or []:
                    self.db.block_topic(owner, str(target), now)

            absent = self._soft_delete_absent_owners(chain_owners, now)

        t_done = time.time()
        logger.info(
            "KV Sync: reconciled %d profiles in %.1fs (soft-deleted %d absent, total %.1fs)",
            len(batch),
            t_done - t_fetch,
            absent,
            t_done - t0,
        )

    def _soft_delete_absent_owners(self, chain_owners: set[str], now: int) -> int:
        """Soft-delete profiles the chain no longer has and drop their list rows.

        Partly irreversible: the blocked_* rows dropped here are the indexer's own
        retained history, which the chain keeps only as a small deque and cannot
        rebuild. Both guards below abort startup rather than act on an inventory
        that looks wrong, because there is no way back once the rows are gone.
        """
        with self.db._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT owner FROM profiles WHERE deleted_at IS NULL")
                db_owners = [str(r[0]) for r in cur.fetchall()]

        if not db_owners:
            return 0

        if not chain_owners:
            # An empty-but-successful GetProfiles is indistinguishable from "the chain
            # has no users". Against a populated index it can only mean the query was
            # wrong, and acting on it would delete every profile and every blocked list.
            raise RuntimeError(
                f"chain returned an empty profile inventory while {len(db_owners)} profile(s) are indexed; "
                "refusing to soft-delete every user"
            )

        absent = [o for o in db_owners if o.strip().lower() not in chain_owners]
        if not absent:
            return 0

        fraction = len(absent) / len(db_owners)
        if fraction > PROFILE_SYNC_MAX_ABSENT_FRACTION:
            raise RuntimeError(
                f"profile sync would soft-delete {len(absent)} of {len(db_owners)} profile(s) "
                f"({fraction:.1%} > {PROFILE_SYNC_MAX_ABSENT_FRACTION:.1%}); refusing — "
                "verify the chain profile inventory before re-running"
            )

        for owner in absent:
            self.db.soft_delete_profile(owner, now)
            with self.db._connect() as conn:
                with conn.cursor() as cur:
                    for table in (
                        "enabled_agents",
                        "followed_users",
                        "followed_topics",
                        "blocked_users",
                        "blocked_posts",
                        "blocked_topics",
                    ):
                        cur.execute(f"DELETE FROM {table} WHERE LOWER(owner) = LOWER(%s)", (owner,))
            logger.debug("profile_sync.soft_deleted owner=%s", owner)

        logger.warning("KV Sync: soft-deleted %d profile(s) absent from chain state", len(absent))
        return len(absent)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Mirage Blockchain Indexer")
    parser.add_argument(
        "--height",
        type=int,
        default=None,
        help="Replay from this block height. Only allowed against an empty indexer database.",
    )
    args = parser.parse_args()

    try:
        from shared.logging_setup import configure_logging as _cfg
        import logging as _logging

        _cfg(component="indexer", level=_logging.INFO)
    except Exception:
        pass

    Indexer(start_height=args.height).start()
