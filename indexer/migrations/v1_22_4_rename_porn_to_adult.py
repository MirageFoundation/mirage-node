"""Rename tag 'porn' -> 'adult' in posts and recompute topic_content_stats."""

MIGRATION_KEY = "v1.22.4_rename_porn_to_adult"


def run(db, chain, logger):
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE posts SET tag = 'adult' WHERE LOWER(tag) = 'porn'")
            updated = cur.rowcount
            logger.info("Updated %d posts tag porn -> adult", updated)

            cur.execute(
                "UPDATE topic_content_stats SET adult_count = adult_count + porn_count, porn_count = 0 WHERE porn_count > 0"
            )

            cur.execute("UPDATE topic_content_stats SET dominant_tag = 'adult' WHERE dominant_tag = 'porn'")

    return f"updated {updated} posts"
