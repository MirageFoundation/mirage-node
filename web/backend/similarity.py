"""
User similarity engine for home feed.

Uses Pearson correlation with confidence scaling and author preference factors
to compute meaningful taste similarity between users. On-demand computation
with staggered TTL caching to avoid load spikes.

KEY INSIGHT: Only preferences where both users agree on direction (both like
or both dislike) count as "shared". If you like something and they hate it,
that's OPPOSITE taste, not shared taste.
"""

import logging
import math
import random
import time

logger = logging.getLogger(__name__)

# TTL: 12 hours base + 0-1 hour jitter (hard backstop, idle-based recomputation handles freshness)
BASE_TTL_SECONDS = 43200
JITTER_RANGE_SECONDS = 3600

# Idle period: recompute only if user hasn't updated preferences in this long
IDLE_THRESHOLD_SECONDS = 1800  # 30 minutes

# Thresholds
MIN_SHARED_SAME_SIGN = 5  # Minimum same-sign shared preferences for meaningful similarity
MIN_FINAL_SIMILARITY = 0.05  # 5% minimum to be considered similar
MAX_SIMILAR_USERS = 30
ACTIVE_DAYS_DEFAULT = 30

# Confidence reference point: 30 shared dims = 1.0 confidence
CONFIDENCE_REFERENCE = 31  # log(31) gives 1.0 at 30 shared dims


def compute_agreement_score(vec_a: dict, vec_b: dict) -> tuple[float, int, int]:
    """
    Compute similarity based on same-sign preferences only.

    CRITICAL: Only preferences where both users have the same sign count.
    - Both positive: agreement (shared like)
    - Both negative: agreement (shared dislike)
    - Opposite signs: NOT counted (this is disagreement!)

    Returns (correlation, same_sign_count, opposite_sign_count).

    The correlation is Pearson over same-sign preferences only.
    """
    shared_keys = set(vec_a.keys()) & set(vec_b.keys())

    same_sign_keys = []
    opposite_count = 0

    for k in shared_keys:
        wa, wb = vec_a[k], vec_b[k]
        # Same sign = both positive or both negative
        if (wa > 0 and wb > 0) or (wa < 0 and wb < 0):
            same_sign_keys.append(k)
        else:
            # Opposite signs = disagreement, not shared taste
            opposite_count += 1

    n = len(same_sign_keys)

    # Need at least MIN_SHARED_SAME_SIGN for meaningful correlation
    if n < MIN_SHARED_SAME_SIGN:
        return 0.0, n, opposite_count

    # Compute Pearson over same-sign preferences only
    vals_a = [vec_a[k] for k in same_sign_keys]
    vals_b = [vec_b[k] for k in same_sign_keys]

    mean_a = sum(vals_a) / n
    mean_b = sum(vals_b) / n

    centered_a = [v - mean_a for v in vals_a]
    centered_b = [v - mean_b for v in vals_b]

    numerator = sum(a * b for a, b in zip(centered_a, centered_b))
    denom_a = math.sqrt(sum(a * a for a in centered_a))
    denom_b = math.sqrt(sum(b * b for b in centered_b))

    if denom_a == 0 or denom_b == 0:
        # All values identical on one side, use 1.0 (perfect agreement on same-sign prefs)
        return 1.0, n, opposite_count

    pearson = numerator / (denom_a * denom_b)
    return pearson, n, opposite_count


def confidence_factor(shared_dims: int) -> float:
    """
    Logarithmic confidence based on number of same-sign shared dimensions.
    More shared preferences = more meaningful similarity.

    Reference: 30 shared dims = 1.0
    Examples:
      5 dims  → 0.52
      10 dims → 0.70
      20 dims → 0.88
      30 dims → 1.00
      50 dims → 1.14
      100 dims → 1.34
    """
    if shared_dims < 1:
        return 0.0
    return math.log(shared_dims + 1) / math.log(CONFIDENCE_REFERENCE)


def author_factor(author_pref: float) -> float:
    """
    Soft penalty for users you've downvoted, slight boost for upvoted.

    This incorporates your direct relationship with this user into
    the similarity calculation.

    Examples:
      pref = -6.5 → 0.13 (heavy penalty, you really dislike them)
      pref = -2   → 0.33
      pref = -1   → 0.50
      pref = 0    → 1.00 (neutral)
      pref = +1   → 1.05
      pref = +2   → 1.10
      pref = +4   → 1.20 (max boost)
    """
    if author_pref < 0:
        return 1.0 / (1.0 + abs(author_pref))
    else:
        # Slight boost for positive preference, capped at 20%
        return 1.0 + min(author_pref * 0.05, 0.2)


def compute_user_similarities(cur, viewer: str, active_days: int = ACTIVE_DAYS_DEFAULT) -> list:
    """
    Compute similarity scores for viewer against all recently active users.

    Uses Pearson correlation on SAME-SIGN preferences only, then applies:
    - Confidence factor based on same-sign shared dimensions (logarithmic)
    - Author factor based on viewer's preference for that user

    Returns list of (user_address, final_similarity, shared_dimensions).
    """
    viewer_lower = viewer.strip().lower()

    # Load viewer's full preference vector
    cur.execute(
        "SELECT pref_type || ':' || target, weight FROM preferences WHERE LOWER(owner) = %s",
        (viewer_lower,),
    )
    viewer_vec = {row[0]: row[1] for row in cur.fetchall()}

    if len(viewer_vec) < MIN_SHARED_SAME_SIGN:
        logger.debug(
            "similarity.compute: viewer %s has only %d preferences, need %d",
            viewer_lower[:12],
            len(viewer_vec),
            MIN_SHARED_SAME_SIGN,
        )
        return []

    # Extract viewer's author preferences for author_factor calculation
    viewer_author_prefs: dict[str, float] = {}
    for key, weight in viewer_vec.items():
        if key.startswith("author:"):
            author_addr = key[7:]  # Remove "author:" prefix
            viewer_author_prefs[author_addr] = weight

    # Only compare against users active in last N days
    since_ts = int(time.time()) - (active_days * 86400)

    cur.execute(
        """
        SELECT LOWER(owner), pref_type || ':' || target, weight
        FROM preferences
        WHERE LOWER(owner) != %s
          AND updated_at > %s
        """,
        (viewer_lower, since_ts),
    )

    # Group by user
    user_vecs: dict[str, dict] = {}
    for owner, key, weight in cur.fetchall():
        if owner not in user_vecs:
            user_vecs[owner] = {}
        user_vecs[owner][key] = weight

    logger.debug(
        "similarity.compute: comparing viewer %s against %d active users",
        viewer_lower[:12],
        len(user_vecs),
    )

    # Compute similarities with all factors
    results = []
    for other_user, other_vec in user_vecs.items():
        # Compute agreement score (Pearson over same-sign prefs only)
        pearson, same_sign_count, opposite_count = compute_agreement_score(viewer_vec, other_vec)

        if same_sign_count < MIN_SHARED_SAME_SIGN:
            continue  # Not enough same-sign shared preferences

        # Apply confidence factor (logarithmic on same-sign shared dims)
        conf = confidence_factor(same_sign_count)

        # Apply author factor (penalty/boost based on your pref for them)
        author_pref = viewer_author_prefs.get(other_user, 0.0)
        auth = author_factor(author_pref)

        # Final similarity (capped at 1.0)
        final = min(1.0, pearson * conf * auth)

        # Only keep if above minimum threshold
        if final > MIN_FINAL_SIMILARITY:
            results.append((other_user, final, same_sign_count))

            # Debug log for interesting cases
            if author_pref != 0 or opposite_count > 0:
                logger.debug(
                    "similarity: %s -> %s: pearson=%.2f same_sign=%d opposite=%d conf=%.2f author=%.2f final=%.2f",
                    viewer_lower[:8],
                    other_user[:8],
                    pearson,
                    same_sign_count,
                    opposite_count,
                    conf,
                    auth,
                    final,
                )

    # Sort by final similarity descending and keep top N
    results.sort(key=lambda x: x[1], reverse=True)
    top_results = results[:MAX_SIMILAR_USERS]

    logger.debug(
        "similarity.compute: found %d similar users for %s (top score: %.3f)",
        len(top_results),
        viewer_lower[:12],
        top_results[0][1] if top_results else 0.0,
    )

    return top_results


def get_or_compute_similarities(cur, viewer: str) -> list:
    """
    Get cached similarities or compute fresh after idle period.

    Recomputes only if:
    - No cache exists, OR
    - Cache expired, OR
    - User's preferences changed since cache AND user has been idle for 30+ mins

    This prevents constant recomputation during active voting sessions.

    Returns list of (user_address, similarity_score, shared_dimensions).
    """
    viewer_lower = viewer.strip().lower()
    now_ts = int(time.time())

    # Check cache (get computed_at for staleness check)
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
        cache_computed_at = cached[0][3]  # All rows have same computed_at

        # Check if user's preferences have been updated since cache was computed
        cur.execute(
            "SELECT MAX(updated_at) FROM preferences WHERE LOWER(owner) = %s",
            (viewer_lower,),
        )
        row = cur.fetchone()
        last_pref_update = row[0] if row and row[0] else 0

        if last_pref_update <= cache_computed_at:
            # Preferences haven't changed since cache, use it
            logger.debug("similarity.cache_hit: %s, prefs unchanged", viewer_lower[:12])
            return [(r[0], r[1], r[2]) for r in cached]

        # Preferences changed - but only recompute if user has been idle
        idle_time = now_ts - last_pref_update
        if idle_time < IDLE_THRESHOLD_SECONDS:
            # User still active, use stale cache
            logger.debug(
                "similarity.cache_stale_but_active: %s, idle=%ds (need %ds)",
                viewer_lower[:12],
                idle_time,
                IDLE_THRESHOLD_SECONDS,
            )
            return [(r[0], r[1], r[2]) for r in cached]

        # User idle for 30+ mins and prefs changed, recompute
        logger.debug(
            "similarity.cache_stale_and_idle: %s, idle=%ds, recomputing",
            viewer_lower[:12],
            idle_time,
        )

    # Cache miss or stale+idle: compute fresh
    logger.debug("similarity.computing: %s", viewer_lower[:12])
    start_time = time.time()
    similarities = compute_user_similarities(cur, viewer)
    compute_ms = (time.time() - start_time) * 1000

    if similarities:
        # Store with jittered TTL to prevent thundering herd
        ttl = BASE_TTL_SECONDS + random.randint(0, JITTER_RANGE_SECONDS)
        expires_at = now_ts + ttl

        # Clear old cache for this user
        cur.execute("DELETE FROM user_similarity_cache WHERE LOWER(owner) = %s", (viewer_lower,))

        # Insert new cache entries
        for other_user, sim, shared in similarities:
            cur.execute(
                """
                INSERT INTO user_similarity_cache(owner, similar_user, similarity, shared_dims, computed_at, expires_at)
                VALUES(%s, %s, %s, %s, %s, %s)
                """,
                (viewer_lower, other_user, sim, shared, now_ts, expires_at),
            )

        logger.debug(
            "similarity.computed: %s -> %d similar users in %.1fms, cached until %d (ttl=%ds)",
            viewer_lower[:12],
            len(similarities),
            compute_ms,
            expires_at,
            ttl,
        )

    return similarities
