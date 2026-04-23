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

from db import connect_backend_db

logger = logging.getLogger(__name__)

CACHE_TTL = 86400  # 24 hours
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


def get_or_compute_similarities(cur, viewer: str, backend_cur=None) -> list:
    """
    Return cached similarities if any non-expired rows exist, otherwise
    recompute. With a 24h TTL we intentionally serve slightly-stale results
    rather than re-running the cross-user Pearson aggregate on every request
    — it was costing 100-500ms per home feed load.

    Args:
        cur: Indexer DB cursor (for preferences table reads).

    Returns list of (user_address, similarity, shared_dimensions).
    """
    viewer_lower = viewer.strip().lower()
    now_ts = int(time.time())

    if backend_cur is not None:
        backend_cur.execute(
            """
            SELECT similar_user, similarity, shared_dims
            FROM user_similarity_cache
            WHERE LOWER(owner) = %s AND expires_at > %s
            ORDER BY similarity DESC
            LIMIT %s
            """,
            (viewer_lower, now_ts, MAX_SIMILAR_USERS),
        )
        cached = backend_cur.fetchall()
    else:
        with connect_backend_db() as bconn:
            with bconn.cursor() as bcur:
                bcur.execute(
                    """
                    SELECT similar_user, similarity, shared_dims
                    FROM user_similarity_cache
                    WHERE LOWER(owner) = %s AND expires_at > %s
                    ORDER BY similarity DESC
                    LIMIT %s
                    """,
                    (viewer_lower, now_ts, MAX_SIMILAR_USERS),
                )
                cached = bcur.fetchall()

    if cached:
        logger.debug("similarity.cache_hit: %s", viewer_lower[:12])
        return [(r[0], r[1], r[2]) for r in cached]

    start = time.time()
    similarities = compute_user_similarities(cur, viewer)
    elapsed_ms = (time.time() - start) * 1000

    if similarities:
        expires_at = now_ts + CACHE_TTL
        values_sql = ",".join(["(%s, %s, %s, %s, %s, %s)"] * len(similarities))
        params: list = []
        for other_user, sim, shared in similarities:
            params.extend((viewer_lower, other_user, sim, shared, now_ts, expires_at))

        if backend_cur is not None:
            backend_cur.execute("DELETE FROM user_similarity_cache WHERE LOWER(owner) = %s", (viewer_lower,))
            backend_cur.execute(
                f"""
                INSERT INTO user_similarity_cache(owner, similar_user, similarity, shared_dims, computed_at, expires_at)
                VALUES {values_sql}
                ON CONFLICT (owner, similar_user) DO UPDATE SET
                    similarity = EXCLUDED.similarity,
                    shared_dims = EXCLUDED.shared_dims,
                    computed_at = EXCLUDED.computed_at,
                    expires_at = EXCLUDED.expires_at
                """,
                params,
            )
        else:
            with connect_backend_db() as bconn:
                with bconn.cursor() as bcur:
                    bcur.execute("DELETE FROM user_similarity_cache WHERE LOWER(owner) = %s", (viewer_lower,))
                    bcur.execute(
                        f"""
                        INSERT INTO user_similarity_cache(owner, similar_user, similarity, shared_dims, computed_at, expires_at)
                        VALUES {values_sql}
                        ON CONFLICT (owner, similar_user) DO UPDATE SET
                            similarity = EXCLUDED.similarity,
                            shared_dims = EXCLUDED.shared_dims,
                            computed_at = EXCLUDED.computed_at,
                            expires_at = EXCLUDED.expires_at
                        """,
                        params,
                    )

    logger.debug(
        "similarity.computed: %s -> %d users in %.1fms",
        viewer_lower[:12],
        len(similarities),
        elapsed_ms,
    )
    return similarities
