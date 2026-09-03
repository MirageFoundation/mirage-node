"""Canonical SQL for home-feed candidate selection.

The partial indexes in `indexer/database.py` and the candidate queries in
`web/backend/routes/public.py` must spell this predicate identically: Postgres
only uses a partial index when it can prove the query's WHERE clause implies the
index predicate, and it does that by matching the expressions. If the two copies
drift by so much as `deleted = false` vs `NOT deleted`, the index is silently
ignored and the home feed goes back to sequential-scanning the whole posts table.
`test_feed_candidate_indexes` in `tests/cases/test_backend_indexer.py` asserts
both callers use these strings and that no candidate query falls back to a
sequential scan.
"""

# Candidate posts are root posts that live in a community and are not deleted.
# Written against a table alias so the same text serves the queries; pass an
# empty alias for an index predicate, which must use bare column names.
_ROOT_POST_PREDICATE = (
    "({a}root_post_id IS NULL OR {a}root_post_id = '' "
    "OR LOWER({a}root_post_id) = LOWER({a}txhash)) "
    "AND {a}community IS NOT NULL AND TRIM({a}community) != '' "
    "AND {a}deleted = false"
)

# Upvotes only. Downvotes and retracted votes never generate candidates.
UPVOTE_PREDICATE = "user_vote > 0"

# Candidates are bounded by age because the magic feed's recency term is
# R = 1 / (1 + (age_hours / 9) ** 1.585), which puts a 7-day-old post at
# R ~= 0.0096 and a 14-day-old post at R ~= 0.0032. A post that old needs
# hundreds of times the votes, comments and awards of a fresh one to place, so
# widening the window past this buys ranking changes too small to observe while
# multiplying the rows every downstream stats query has to aggregate.
CANDIDATE_WINDOW_DAYS = 14
CANDIDATE_WINDOW_SECONDS = CANDIDATE_WINDOW_DAYS * 86400

# Rows each candidate source may contribute. Everything after candidate loading
# — the vote, comment, unique-commenter and award aggregates, the similarity
# intersection, the lens and tag filters, and scoring itself — is linear in the
# size of this pool, and the pool used to be 500 per source: 1139 candidates
# aggregated and scored to render 15 posts, with the lens filter discarding 3 of
# them. Each source is ordered newest-first, so 150 covers roughly the last two
# days of a source, where the recency term is still worth ~8% of a brand new
# post and a genuinely strong older post can therefore still place.
MAX_CANDIDATES_PER_SOURCE = 150


def feed_candidate_predicate(alias: str = "") -> str:
    """Return the root-post predicate, qualified by `alias` (e.g. "p")."""
    return _ROOT_POST_PREDICATE.format(a=f"{alias}." if alias else "")
