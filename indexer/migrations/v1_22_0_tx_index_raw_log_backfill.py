"""
Backfill tx_index.raw_log for successful send_tokens/multi rows.

When a block is pruned and the log can't be recovered, the row is deleted
from tx_index (stale entry that push_listener can't use anyway).

When the block is available but the log field is empty, raw_log is
synthesized from the events array (same logic as the main indexer loop).
"""

from __future__ import annotations

import base64
import hashlib
import json

import requests


MIGRATION_KEY = "v1.22.0_tx_index_raw_log_backfill"


class PrunedTxError(RuntimeError):
    pass


class MissingTxError(RuntimeError):
    pass


def _is_pruned_error(exc: requests.exceptions.HTTPError) -> bool:
    resp = exc.response
    if resp is None:
        return False
    try:
        payload = resp.json()
        text = json.dumps(payload)
    except Exception:
        text = resp.text or ""
    text = text.lower()
    return (
        "lowest height" in text
        or "height is not available" in text
        or "pruned" in text
        or "height must be between" in text
    )


def _synthesize_raw_log_from_events(tx_result: dict) -> str:
    """Build raw_log JSON from the events array (same format push_listener expects)."""
    events = tx_result.get("events") or []
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


def _fetch_raw_log(chain, txhash: str, height: int) -> str:
    """Fetch raw_log from the block at the given height.

    Raises PrunedTxError or MissingTxError for unrecoverable entries.
    Raises RuntimeError for transient RPC errors.
    """
    try:
        block_resp = chain.get_block(height)
    except requests.exceptions.HTTPError as exc:
        if _is_pruned_error(exc):
            raise PrunedTxError(f"block pruned height={height} tx={txhash}") from exc
        raise RuntimeError(f"rpc error fetching block height={height} tx={txhash}: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"rpc error fetching block height={height} tx={txhash}: {exc}") from exc

    block = (block_resp.get("result") or {}).get("block")
    if not block:
        raise MissingTxError(f"block missing height={height} tx={txhash}")
    txs = (block.get("data") or {}).get("txs") or []
    tx_idx = None
    for idx, tx_b64 in enumerate(txs):
        if not tx_b64:
            continue
        try:
            raw_tx_bytes = base64.b64decode(tx_b64)
        except Exception:
            continue
        txh = hashlib.sha256(raw_tx_bytes).hexdigest().lower()
        if txh == txhash:
            tx_idx = idx
            break
    if tx_idx is None:
        raise MissingTxError(f"tx not found in block height={height} tx={txhash}")

    try:
        results = chain.get_block_results(height)
    except Exception as exc:
        raise RuntimeError(f"rpc error fetching block_results height={height} tx={txhash}: {exc}") from exc
    result_obj = results.get("result") or {}
    txs_results = result_obj.get("txs_results") or []
    if tx_idx >= len(txs_results):
        raise MissingTxError(f"tx_result missing height={height} tx={txhash}")
    tx_result = txs_results[tx_idx] or {}
    code = int(tx_result.get("code", 0) or 0)
    if code != 0:
        raise MissingTxError(f"nonzero code={code} height={height} tx={txhash}")

    raw_log = "" if tx_result.get("log") is None else str(tx_result.get("log"))
    if raw_log == "":
        raw_log = _synthesize_raw_log_from_events(tx_result)
    if not raw_log:
        raise MissingTxError(f"empty log and no events height={height} tx={txhash}")
    return raw_log


def run(db, chain, logger):
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT txhash, height
                FROM tx_index
                WHERE code = 0
                  AND tx_type IN ('send_tokens', 'multi')
                  AND (raw_log IS NULL OR raw_log = '')
                ORDER BY created_at ASC
                """
            )
            rows = cur.fetchall()

    if not rows:
        return "no tx_index raw_log backfill needed"

    logger.info("tx_index.raw_log_backfill start missing=%d", len(rows))
    updated = 0
    pruned = 0

    with db._connect() as conn:
        with conn.cursor() as cur:
            for txhash, height in rows:
                txh = str(txhash or "").strip().lower()
                if not txh:
                    logger.warning("tx_index.raw_log_backfill skipping row with empty txhash")
                    continue
                h = int(height or 0)

                if h <= 0:
                    raise MissingTxError(f"invalid height={h} tx={txh}")

                try:
                    raw_log = _fetch_raw_log(chain, txh, h)
                    cur.execute(
                        "UPDATE tx_index SET raw_log = %s WHERE txhash = %s",
                        (db._strip_nul(raw_log), txh),
                    )
                    updated += 1
                    logger.debug("tx_index.raw_log_backfill updated tx=%s height=%s", txh, h)
                except (PrunedTxError, MissingTxError) as exc:
                    cur.execute("DELETE FROM tx_index WHERE txhash = %s", (txh,))
                    pruned += 1
                    logger.info(
                        "tx_index.raw_log_backfill deleted tx=%s height=%s reason=%s",
                        txh,
                        h,
                        exc,
                    )

    logger.info("tx_index.raw_log_backfill done updated=%d pruned=%d", updated, pruned)
    return f"backfilled={updated} pruned={pruned}"
