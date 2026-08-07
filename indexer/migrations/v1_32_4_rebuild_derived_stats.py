"""
Rebuild derived indexer stats from canonical tables.

Repairs user_topic_stats, topic_content_stats, and preferences that may have
been corrupted by non-idempotent incremental updates (replay / re-vote deltas).

No schema changes — temporary tables only, swapped via DELETE+INSERT in one
transaction when DatabaseManager.transaction is available.
"""

from __future__ import annotations

MIGRATION_KEY = "v1.32.4_rebuild_derived_stats"

# Must match indexer/database.py update_preference DECAY.
_PREFERENCE_DECAY = 0.9


def run(db, chain, logger):
    """Rebuild derived stats from votes/posts. Idempotent."""
    del chain  # unused; signature required by migration runner

    if not hasattr(db, "transaction"):
        raise RuntimeError("DatabaseManager.transaction required for v1.32.4_rebuild_derived_stats")

    with db.transaction(label="migration:v1.32.4_rebuild_derived_stats"):
        with db._connect() as conn:
            with conn.cursor() as cur:
                before = _snapshot_counts(cur)
                logger.info(
                    "rebuild_derived_stats before user_topic_stats=%s topic_content_stats=%s preferences=%s",
                    before["user_topic_stats"],
                    before["topic_content_stats"],
                    before["preferences"],
                )

                _rebuild_user_topic_stats(cur, logger)
                _rebuild_topic_content_stats(cur, logger)
                _rebuild_preferences(cur, logger)

                after = _snapshot_counts(cur)
                logger.info(
                    "rebuild_derived_stats after user_topic_stats=%s topic_content_stats=%s preferences=%s",
                    after["user_topic_stats"],
                    after["topic_content_stats"],
                    after["preferences"],
                )

                # Sanity: net_votes should equal sum of current non-zero user_vote per topic.
                cur.execute(
                    """
                    SELECT COALESCE(SUM(ABS(net_votes)), 0) FROM user_topic_stats
                    """
                )
                abs_net = int(cur.fetchone()[0])
                logger.info("rebuild_derived_stats abs_net_votes_sum=%s", abs_net)

    return f"rebuilt user_topic_stats={after['user_topic_stats']} topic_content_stats={after['topic_content_stats']} preferences={after['preferences']}"


def _snapshot_counts(cur) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in ("user_topic_stats", "topic_content_stats", "preferences"):
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        out[table] = int(cur.fetchone()[0])
    return out


def _rebuild_user_topic_stats(cur, logger) -> None:
    cur.execute("DROP TABLE IF EXISTS _tmp_user_topic_stats")
    cur.execute(
        """
        CREATE TEMP TABLE _tmp_user_topic_stats (
            owner TEXT NOT NULL,
            topic TEXT NOT NULL,
            vote_count INTEGER NOT NULL DEFAULT 0,
            net_votes INTEGER NOT NULL DEFAULT 0,
            unique_root_posts INTEGER NOT NULL DEFAULT 0,
            post_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (owner, topic)
        ) ON COMMIT DROP
        """
    )

    # Current vote standing: one row per (owner, target) from votes with latest?
    # votes table has UNIQUE(owner, target) so each pair is current.
    cur.execute(
        """
        INSERT INTO _tmp_user_topic_stats (owner, topic, vote_count, net_votes, unique_root_posts, post_count)
        SELECT
            LOWER(v.owner) AS owner,
            LOWER(COALESCE(NULLIF(p.root_topic, ''), p.topic)) AS topic,
            COUNT(*) FILTER (WHERE v.user_vote <> 0) AS vote_count,
            COALESCE(SUM(CASE
                WHEN v.user_vote > 0 THEN 1
                WHEN v.user_vote < 0 THEN -1
                ELSE 0
            END), 0)::int AS net_votes,
            COUNT(DISTINCT LOWER(COALESCE(NULLIF(p.root_post_id, ''), p.txhash)))
                FILTER (WHERE v.user_vote <> 0) AS unique_root_posts,
            0 AS post_count
        FROM votes v
        JOIN posts p ON LOWER(p.txhash) = LOWER(v.target)
        WHERE COALESCE(NULLIF(p.root_topic, ''), p.topic) IS NOT NULL
          AND COALESCE(NULLIF(p.root_topic, ''), p.topic) <> ''
        GROUP BY LOWER(v.owner), LOWER(COALESCE(NULLIF(p.root_topic, ''), p.topic))
        """
    )

    # Post activity (posts/comments authored in topic)
    cur.execute(
        """
        INSERT INTO _tmp_user_topic_stats (owner, topic, vote_count, net_votes, unique_root_posts, post_count)
        SELECT
            LOWER(p.owner) AS owner,
            LOWER(COALESCE(NULLIF(p.root_topic, ''), p.topic)) AS topic,
            0, 0, 0,
            COUNT(*)::int AS post_count
        FROM posts p
        WHERE COALESCE(NULLIF(p.root_topic, ''), p.topic) IS NOT NULL
          AND COALESCE(NULLIF(p.root_topic, ''), p.topic) <> ''
          AND COALESCE(p.deleted, FALSE) = FALSE
        GROUP BY LOWER(p.owner), LOWER(COALESCE(NULLIF(p.root_topic, ''), p.topic))
        ON CONFLICT (owner, topic) DO UPDATE SET
            post_count = EXCLUDED.post_count
        """
    )

    cur.execute("DELETE FROM user_topic_stats")
    cur.execute(
        """
        INSERT INTO user_topic_stats (owner, topic, vote_count, net_votes, unique_root_posts, post_count)
        SELECT owner, topic, vote_count, net_votes, unique_root_posts, post_count
        FROM _tmp_user_topic_stats
        """
    )
    logger.debug("rebuild_derived_stats user_topic_stats rows=%s", cur.rowcount)


def _rebuild_topic_content_stats(cur, logger) -> None:
    cur.execute("DROP TABLE IF EXISTS _tmp_topic_content_stats")
    cur.execute(
        """
        CREATE TEMP TABLE _tmp_topic_content_stats (
            topic TEXT PRIMARY KEY,
            total_posts INTEGER NOT NULL DEFAULT 0,
            sensitive_count INTEGER NOT NULL DEFAULT 0,
            gore_count INTEGER NOT NULL DEFAULT 0,
            violence_count INTEGER NOT NULL DEFAULT 0,
            death_count INTEGER NOT NULL DEFAULT 0,
            adult_count INTEGER NOT NULL DEFAULT 0,
            dominant_tag TEXT,
            dominant_ratio DOUBLE PRECISION
        ) ON COMMIT DROP
        """
    )
    cur.execute(
        """
        INSERT INTO _tmp_topic_content_stats (
            topic, total_posts, sensitive_count, gore_count, violence_count, death_count, adult_count
        )
        SELECT
            LOWER(COALESCE(NULLIF(root_topic, ''), topic)) AS topic,
            COUNT(*)::int AS total_posts,
            SUM(CASE WHEN LOWER(tag) = 'sensitive' THEN 1 ELSE 0 END)::int,
            SUM(CASE WHEN LOWER(tag) = 'gore' THEN 1 ELSE 0 END)::int,
            SUM(CASE WHEN LOWER(tag) = 'violence' THEN 1 ELSE 0 END)::int,
            SUM(CASE WHEN LOWER(tag) = 'death' THEN 1 ELSE 0 END)::int,
            SUM(CASE WHEN LOWER(tag) IN ('adult', 'porn') THEN 1 ELSE 0 END)::int
        FROM posts
        WHERE COALESCE(target, '') = ''
          AND COALESCE(deleted, FALSE) = FALSE
          AND COALESCE(NULLIF(root_topic, ''), topic) IS NOT NULL
          AND COALESCE(NULLIF(root_topic, ''), topic) <> ''
        GROUP BY LOWER(COALESCE(NULLIF(root_topic, ''), topic))
        """
    )

    # Dominant tag: highest count among safety tags when ratio >= 0.5 of total
    cur.execute(
        """
        UPDATE _tmp_topic_content_stats SET
            dominant_tag = sub.tag,
            dominant_ratio = sub.ratio
        FROM (
            SELECT
                topic,
                tag,
                CASE WHEN total_posts > 0 THEN cnt::float / total_posts ELSE 0 END AS ratio
            FROM (
                SELECT topic, total_posts, 'sensitive' AS tag, sensitive_count AS cnt FROM _tmp_topic_content_stats
                UNION ALL
                SELECT topic, total_posts, 'gore', gore_count FROM _tmp_topic_content_stats
                UNION ALL
                SELECT topic, total_posts, 'violence', violence_count FROM _tmp_topic_content_stats
                UNION ALL
                SELECT topic, total_posts, 'death', death_count FROM _tmp_topic_content_stats
                UNION ALL
                SELECT topic, total_posts, 'adult', adult_count FROM _tmp_topic_content_stats
            ) x
            WHERE cnt > 0
        ) sub
        WHERE _tmp_topic_content_stats.topic = sub.topic
          AND sub.ratio = (
              SELECT MAX(CASE WHEN total_posts > 0 THEN cnt::float / total_posts ELSE 0 END)
              FROM (
                  SELECT sensitive_count AS cnt, total_posts FROM _tmp_topic_content_stats t2 WHERE t2.topic = sub.topic
                  UNION ALL SELECT gore_count, total_posts FROM _tmp_topic_content_stats t2 WHERE t2.topic = sub.topic
                  UNION ALL SELECT violence_count, total_posts FROM _tmp_topic_content_stats t2 WHERE t2.topic = sub.topic
                  UNION ALL SELECT death_count, total_posts FROM _tmp_topic_content_stats t2 WHERE t2.topic = sub.topic
                  UNION ALL SELECT adult_count, total_posts FROM _tmp_topic_content_stats t2 WHERE t2.topic = sub.topic
              ) m
          )
        """
    )

    cur.execute("DELETE FROM topic_content_stats")
    cur.execute(
        """
        INSERT INTO topic_content_stats (
            topic, total_posts, sensitive_count, gore_count, violence_count,
            death_count, adult_count, dominant_tag, dominant_ratio
        )
        SELECT
            topic, total_posts, sensitive_count, gore_count, violence_count,
            death_count, adult_count, dominant_tag, COALESCE(dominant_ratio, 0)
        FROM _tmp_topic_content_stats
        """
    )
    logger.debug("rebuild_derived_stats topic_content_stats rows=%s", cur.rowcount)


def _rebuild_preferences(cur, logger) -> None:
    """Rebuild preferences deterministically from current non-neutral votes in created_at order."""
    cur.execute(
        """
        SELECT
            LOWER(v.owner) AS owner,
            LOWER(COALESCE(NULLIF(p.root_topic, ''), p.topic)) AS topic,
            LOWER(p.owner) AS author,
            CASE WHEN v.user_vote > 0 THEN 1 WHEN v.user_vote < 0 THEN -1 ELSE 0 END AS direction,
            COALESCE(NULLIF(p.root_post_id, ''), p.txhash) AS root_post_id,
            LOWER(v.target) AS target,
            v.created_at AS created_at
        FROM votes v
        JOIN posts p ON LOWER(p.txhash) = LOWER(v.target)
        WHERE v.user_vote <> 0
          AND LOWER(v.txhash) NOT LIKE 'auto\\_%' ESCAPE '\\'
          AND COALESCE(NULLIF(p.root_topic, ''), p.topic) IS NOT NULL
          AND COALESCE(NULLIF(p.root_topic, ''), p.topic) <> ''
        ORDER BY v.created_at ASC, LOWER(v.txhash) ASC
        """
    )
    rows = cur.fetchall()

    # topic prefs: only when voting on root post (target == root_post_id)
    # author prefs: when voter != author
    topic_weights: dict[tuple[str, str], float] = {}
    author_weights: dict[tuple[str, str], float] = {}
    topic_updated: dict[tuple[str, str], int] = {}
    author_updated: dict[tuple[str, str], int] = {}

    for owner, topic, author, direction, root_post_id, target, created_at in rows:
        if not owner or not topic:
            continue
        is_root = root_post_id and target and str(root_post_id).lower() == str(target).lower()
        if is_root:
            key = (owner, topic)
            delta = 0.5 if direction > 0 else -0.5
            old = topic_weights.get(key, 0.0)
            topic_weights[key] = max(min(old * _PREFERENCE_DECAY + delta, 10.0), -10.0)
            topic_updated[key] = int(created_at)
        if author and owner != author:
            key_a = (owner, author)
            delta_a = 1.0 if direction > 0 else -1.0
            old_a = author_weights.get(key_a, 0.0)
            author_weights[key_a] = max(min(old_a * _PREFERENCE_DECAY + delta_a, 10.0), -10.0)
            author_updated[key_a] = int(created_at)

    cur.execute("DELETE FROM preferences")
    pref_rows = []
    for (owner, topic), weight in topic_weights.items():
        pref_rows.append((owner, "topic", topic, float(weight), topic_updated[(owner, topic)]))
    for (owner, author), weight in author_weights.items():
        pref_rows.append((owner, "author", author, float(weight), author_updated[(owner, author)]))
    if pref_rows:
        cur.executemany(
            """
            INSERT INTO preferences(owner, pref_type, target, weight, updated_at)
            VALUES(%s, %s, %s, %s, %s)
            """,
            pref_rows,
        )
    logger.debug("rebuild_derived_stats preferences rows=%s", len(pref_rows))
