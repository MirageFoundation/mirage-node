"""
Backfill tx_index.raw_log for successful send_tokens/multi rows.

Ensures raw_log is non-empty JSON for push notifications and upgrade checks.
"""

from __future__ import annotations

import base64
import hashlib
import json


MIGRATION_KEY = "v1.22.0_tx_index_raw_log_backfill"


def _fetch_tx_result_log(chain, txhash: str, height: int) -> tuple[int, str]:
    block_resp = chain.get_block(height)
    block = (block_resp.get("result") or {}).get("block")
    if not block:
        raise RuntimeError(f"tx_index.raw_log_backfill missing block height={height} tx={txhash}")
    txs = (block.get("data") or {}).get("txs") or []
    tx_idx = None
    for idx, tx_b64 in enumerate(txs):
        if not tx_b64:
            continue
        try:
            raw_tx_bytes = base64.b64decode(tx_b64)
        except Exception as exc:
            raise RuntimeError(f"tx_index.raw_log_backfill invalid base64 height={height} tx={txhash}") from exc
        txh = hashlib.sha256(raw_tx_bytes).hexdigest().lower()
        if txh == txhash:
            tx_idx = idx
            break
    if tx_idx is None:
        raise RuntimeError(f"tx_index.raw_log_backfill tx not found height={height} tx={txhash}")

    results = chain.get_block_results(height)
    result_obj = results.get("result") or {}
    txs_results = result_obj.get("txs_results", [])
    if tx_idx >= len(txs_results):
        raise RuntimeError(f"tx_index.raw_log_backfill missing tx_result height={height} tx={txhash}")
    tx_result = txs_results[tx_idx] or {}
    code = int(tx_result.get("code", 0) or 0)
    raw_log = "" if tx_result.get("log") is None else str(tx_result.get("log"))
    return code, raw_log


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

    with db._connect() as conn:
        with conn.cursor() as cur:
            for txhash, height in rows:
                txh = str(txhash or "").strip().lower()
                if not txh:
                    raise RuntimeError("tx_index.raw_log_backfill missing txhash")
                h = int(height or 0)
                if h <= 0:
                    raise RuntimeError(f"tx_index.raw_log_backfill invalid height tx={txh}")

                code, raw_log = _fetch_tx_result_log(chain, txh, h)
                if code != 0:
                    raise RuntimeError(f"tx_index.raw_log_backfill nonzero code={code} height={h} tx={txh}")
                if raw_log.strip() == "":
                    raise RuntimeError(f"tx_index.raw_log_backfill empty log height={h} tx={txh}")
                try:
                    parsed = json.loads(raw_log)
                except Exception as exc:
                    raise RuntimeError(f"tx_index.raw_log_backfill invalid json height={h} tx={txh}") from exc
                if not isinstance(parsed, list):
                    raise RuntimeError(f"tx_index.raw_log_backfill unexpected format height={h} tx={txh}")

                cur.execute(
                    "UPDATE tx_index SET raw_log = %s WHERE txhash = %s",
                    (db._strip_nul(raw_log), txh),
                )
                updated += 1
                logger.debug("tx_index.raw_log_backfill updated tx=%s height=%s", txh, h)

    logger.info("tx_index.raw_log_backfill done updated=%d", updated)
    return f"backfilled tx_index raw_log: {updated}"
