"""
Clear stale similarity cache after algorithm overhaul (Pearson + confidence damper).

Old scores were computed with same-sign-only filtering, author_factor, and
log-based confidence that could exceed 1.0. New scores use full-overlap
Pearson with n/(n+k) confidence. Truncating forces lazy recompute.
"""

MIGRATION_KEY = "v1.16.0_similarity_overhaul"


def run(db, chain, logger):
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_similarity_cache")
            deleted = cur.rowcount
    return f"cleared {deleted} stale cache rows"
