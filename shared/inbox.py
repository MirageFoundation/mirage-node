from __future__ import annotations


def compute_unread_count(cur, address: str) -> tuple[int, int]:
    """Compute unread inbox items and return (count, last_seen_ts)."""
    if not address or address.lower() == "guest":
        return 0, 0

    viewer = address.lower()

    cur.execute(
        """
        SELECT pr.inbox_last_viewed_at, COUNT(r.txhash)
        FROM profiles pr
        LEFT JOIN posts p ON LOWER(p.owner) = LOWER(pr.owner)
        LEFT JOIN posts r
          ON r.target = p.txhash
         AND LOWER(r.owner) != LOWER(pr.owner)
         AND r.deleted = FALSE
         AND r.created_at > pr.inbox_last_viewed_at
        WHERE LOWER(pr.owner) = %s
        GROUP BY pr.inbox_last_viewed_at
        """,
        (viewer,),
    )
    row = cur.fetchone()
    last_seen = int(row[0]) if row and row[0] else 0
    reply_count = int(row[1]) if row and row[1] else 0

    cur.execute(
        """
        SELECT COUNT(*) FROM mentions m
        JOIN posts p ON p.txhash = m.post_txhash AND p.deleted = FALSE
        WHERE LOWER(m.mentioned_address) = %s
          AND LOWER(m.mentioner_address) != %s
          AND m.created_at > %s
          AND NOT EXISTS (
              SELECT 1 FROM posts tp
              WHERE tp.txhash = p.target
                AND LOWER(tp.owner) = %s
          )
        """,
        (viewer, viewer, last_seen, viewer),
    )
    mrow = cur.fetchone()
    mention_count = int(mrow[0]) if mrow and mrow[0] else 0

    cur.execute(
        """
        SELECT COUNT(*) FROM awards a
        JOIN posts p ON p.txhash = a.target AND p.deleted = FALSE
        WHERE LOWER(p.owner) = %s
          AND LOWER(a.owner) != %s
          AND a.created_at > %s
        """,
        (viewer, viewer, last_seen),
    )
    arow = cur.fetchone()
    award_count = int(arow[0]) if arow and arow[0] else 0

    return reply_count + mention_count + award_count, last_seen
