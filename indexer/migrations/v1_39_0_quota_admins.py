"""v1.39.0: project daily relay quota for appointed admins.

Paid subscribers are backfilled in v1_39_0_curator_defined_communities.
Admins are appointed without EffectivePaid, so their quota columns stay NULL
until a later message unless we project them here. Bootstrap fails hard on
a relay-quota profile with missing quota, which would 500 the admin UI.
"""

from indexer.migrations import run_db_migration

MIGRATION_KEY = "v1.39.0_quota_admins"


def run(db, chain, logger):
    def _migrate(cur):
        cur.execute(
            """
            SELECT owner FROM profiles
            WHERE level >= 100
            ORDER BY owner
            """
        )
        owners = [str(row[0]).strip().lower() for row in cur.fetchall() if row and row[0]]
        for owner in owners:
            runtime = chain.query_subscription_runtime(owner)
            cur.execute(
                """
                UPDATE profiles
                SET subscriber_quota_epoch=%s,
                    subscriber_quota_used=%s,
                    renewal_next_attempt=%s,
                    renewal_last_attempt_epoch=%s,
                    renewal_warning_expiry=%s,
                    renewal_warning_sent=%s
                WHERE LOWER(owner)=%s
                """,
                (
                    runtime["quota_epoch"],
                    runtime["quota_used"],
                    runtime["renewal_next_attempt"],
                    runtime["renewal_last_attempt_epoch"],
                    runtime["renewal_expiry"],
                    runtime["renewal_warning_sent"],
                    owner,
                ),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"admin profile disappeared during quota backfill: {owner}")
        logger.info("[quota] projected relay quota for %d admin profiles", len(owners))
        return f"admin_quota_backfill owners={len(owners)}"

    return run_db_migration(db, MIGRATION_KEY, _migrate, logger)
