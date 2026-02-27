"""
User similarity engine for home feed.

Computes Pearson correlation over ALL shared preferences (agreements and
disagreements) between users, then applies a Bayesian confidence damper
(shared / (shared + k)) so sparse overlaps don't produce misleading scores.

Result range: (-1, +1) by construction — no clamping needed.
Symmetric: similarity(A, B) == similarity(B, A) always.
"""

import logging
import time

logger = logging.getLogger(__name__)

CACHE_TTL = 7200  # 2 hours
MIN_SHARED = 25
MIN_SIMILARITY = 0.05
MAX_SIMILAR_USERS = 30
ACTIVE_DAYS = 30
CONFIDENCE_K = 8  # n/(n+k) damper; 8 shared → 0.50, 30 → 0.79, 73 → 0.90


def compute_user_similarities(cur, viewer: str) -> list:
    """
    Compute similarity for viewer against all recently active users via a
    single SQL aggregate query (Pearson from raw sums) + Python confidence.

    Returns list of (user_address, similarity, shared_dimensions).
    """
    viewer_lower = viewer.strip().lower()
    since_ts = int(time.time()) - (ACTIVE_DAYS * 86400)

    cur.execute(
        """
        WITH viewer_prefs AS (
            SELECT pref_type, target, weight
            FROM preferences
            WHERE LOWER(owner) = %s
        ),
        active_owners AS (
            SELECT DISTINCT LOWER(owner) AS owner
            FROM preferences
            WHERE updated_at > %s AND LOWER(owner) != %s
        ),
        agg AS (
            SELECT
                LOWER(p.owner)                  AS other_user,
                COUNT(*)                        AS shared,
                SUM(v.weight)                   AS sum_vw,
                SUM(p.weight)                   AS sum_pw,
                SUM(v.weight * p.weight)        AS sum_vp,
                SUM(v.weight * v.weight)        AS sum_v2,
                SUM(p.weight * p.weight)        AS sum_p2
            FROM preferences p
            JOIN viewer_prefs v USING (pref_type, target)
            JOIN active_owners a ON LOWER(p.owner) = a.owner
            GROUP BY LOWER(p.owner)
            HAVING COUNT(*) >= %s
        ),
        scored AS (
            SELECT
                other_user,
                shared,
                CASE
                    WHEN (shared * sum_v2 - sum_vw * sum_vw) * (shared * sum_p2 - sum_pw * sum_pw) <= 0
                    THEN 1.0
                    ELSE (shared * sum_vp - sum_vw * sum_pw)
                         / SQRT((shared * sum_v2 - sum_vw * sum_vw) * (shared * sum_p2 - sum_pw * sum_pw))
                END AS pearson
            FROM agg
        )
        SELECT
            other_user,
            shared,
            pearson * (shared::double precision / (shared + %s)) AS similarity
        FROM scored
        WHERE pearson * (shared::double precision / (shared + %s)) > %s
        ORDER BY similarity DESC
        LIMIT %s
        """,
        (
            viewer_lower,
            since_ts,
            viewer_lower,
            MIN_SHARED,
            CONFIDENCE_K,
            CONFIDENCE_K,
            MIN_SIMILARITY,
            MAX_SIMILAR_USERS,
        ),
    )

    rows = cur.fetchall()
    results = [(other_user, round(similarity, 6), shared) for other_user, shared, similarity in rows]

    logger.debug(
        "similarity.compute: %s -> %d results in top %d",
        viewer_lower[:12],
        len(results),
        MAX_SIMILAR_USERS,
    )
    return results


def get_or_compute_similarities(cur, viewer: str) -> list:
    """
    Return cached similarities if fresh, otherwise recompute.

    Cache is valid when: TTL not expired AND viewer's prefs unchanged since
    the cache was built. Otherwise recompute immediately (SQL query is fast).

    Returns list of (user_address, similarity, shared_dimensions).
    """
    viewer_lower = viewer.strip().lower()
    now_ts = int(time.time())

    cur.execute(
        """
        SELECT similar_user, similarity, shared_dims, computed_at
        FROM user_similarity_cache
        WHERE LOWER(owner) = %s AND expires_at > %s
        ORDER BY similarity DESC
        LIMIT %s
        """,
        (viewer_lower, now_ts, MAX_SIMILAR_USERS),
    )
    cached = cur.fetchall()

    if cached:
        cache_computed_at = cached[0][3]
        cur.execute(
            "SELECT MAX(updated_at) FROM preferences WHERE LOWER(owner) = %s",
            (viewer_lower,),
        )
        row = cur.fetchone()
        last_update = row[0] if row and row[0] else 0

        if last_update <= cache_computed_at:
            logger.debug("similarity.cache_hit: %s", viewer_lower[:12])
            return [(r[0], r[1], r[2]) for r in cached]

    start = time.time()
    similarities = compute_user_similarities(cur, viewer)
    elapsed_ms = (time.time() - start) * 1000

    if similarities:
        expires_at = now_ts + CACHE_TTL
        cur.execute("DELETE FROM user_similarity_cache WHERE LOWER(owner) = %s", (viewer_lower,))
        for other_user, sim, shared in similarities:
            cur.execute(
                """
                INSERT INTO user_similarity_cache(owner, similar_user, similarity, shared_dims, computed_at, expires_at)
                VALUES(%s, %s, %s, %s, %s, %s)
                """,
                (viewer_lower, other_user, sim, shared, now_ts, expires_at),
            )

    logger.debug(
        "similarity.computed: %s -> %d users in %.1fms",
        viewer_lower[:12],
        len(similarities),
        elapsed_ms,
    )
    return similarities
