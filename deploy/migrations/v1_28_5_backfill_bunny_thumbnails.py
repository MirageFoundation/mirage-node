"""
One-time migration: backfill thumbnail_url for Bunny Stream video posts that
were indexed before the indexer learned how to derive Bunny thumbnails.

The indexer's thumbnail discovery only handled Cloudflare Stream and YouTube,
so root posts whose media is a Bunny HLS playlist
(https://{host}.b-cdn.net/{guid}/playlist.m3u8) got an empty thumbnail_url and
the feed showed a placeholder instead of the poster. New posts are fixed at
index time; this fills in the gap for already-indexed posts.

Derivation mirrors the indexer (_bunny_stream_thumbnail) and the frontend
(getVideoThumbnailUrl): /{guid}/playlist.m3u8 -> /{guid}/thumbnail.jpg on the
same host. Idempotent: only touches roots with an empty thumbnail_url.
"""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse

MIGRATION_KEY = "v1.28.5-backfill-bunny-thumbnails"
DESCRIPTION = "Backfill thumbnail_url for Bunny Stream video posts indexed before Bunny support"

_BUNNY_PLAYLIST_RE = re.compile(r"^/([^/]+)/playlist\.m3u8$")


def _bunny_thumb(url: str) -> str | None:
    try:
        u = urlparse(url or "")
        host = (u.hostname or "").lower()
        if not host.endswith(".b-cdn.net"):
            return None
        m = _BUNNY_PLAYLIST_RE.match(u.path or "")
        if not m:
            return None
        return f"{u.scheme}://{u.hostname}/{m.group(1)}/thumbnail.jpg"
    except Exception:
        return None


def run(config_dir, logger):
    import psycopg

    indexer_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not indexer_url:
        raise RuntimeError("INDEXER_DB_URL must be set")

    conn = psycopg.connect(indexer_url, autocommit=False)
    updated = 0
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT txhash, COALESCE(media, '[]') FROM posts "
            "WHERE (thumbnail_url IS NULL OR thumbnail_url = '') "
            "AND COALESCE(target, '') = '' "
            "AND media LIKE '%b-cdn.net%playlist.m3u8%'"
        )
        rows = cur.fetchall()
        logger.info(f"  scanning {len(rows)} candidate bunny posts")
        for txhash, media_json in rows:
            try:
                media = json.loads(media_json) or []
            except Exception:
                continue
            if not media:
                continue
            thumb = _bunny_thumb(media[0])
            if not thumb:
                continue
            cur.execute(
                "UPDATE posts SET thumbnail_url = %s WHERE txhash = %s",
                (thumb, txhash),
            )
            updated += 1
        conn.commit()
        logger.info(f"  backfilled {updated} bunny video thumbnails")
    finally:
        conn.close()

    return f"backfilled {updated} bunny thumbnails"
