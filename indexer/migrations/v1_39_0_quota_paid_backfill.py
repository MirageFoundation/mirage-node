"""v1.39.0: project daily relay quota for paid/relay profiles after upgrade.

v1_39_0_communities adds effective_paid DEFAULT FALSE, then
v1_39_0_curator_defined_communities used to backfill only WHERE
effective_paid=TRUE — which is always empty at migration time because KV
profile sync (the thing that flips effective_paid from chain) runs AFTER
migrations. Admins were covered by v1_39_0_quota_admins; paid subscribers
were not. Bootstrap fails hard on a missing projection and 503s login.

This migration is the upgrade chokepoint for that gap. Owners come from the
chain (effective_paid / level>=1), intersected with indexer rows that still
have NULL quota — so it works on a real v1.38→v1.39 upgrade before sync,
and is a no-op once projections exist. The post-sync gap fill in
indexer/main.py is belt-and-suspenders only.
"""

MIGRATION_KEY = "v1.39.0_quota_paid_backfill"


def run(db, chain, logger):
    progress_key = f"migration_{MIGRATION_KEY}_progress"

    profiles = chain.list_profiles_paginated()
    chain_relay_owners = set()
    for profile in profiles:
        owner = str(profile.get("owner") or "").strip().lower()
        if not owner:
            raise RuntimeError("chain profile listing returned an empty owner")
        level = int(profile.get("level") or 0)
        if bool(profile.get("effective_paid")) or level >= 1:
            chain_relay_owners.add(owner)

    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT LOWER(owner) FROM profiles
                WHERE subscriber_quota_epoch IS NULL
                """
            )
            null_quota = {str(row[0]) for row in cur.fetchall() if row and row[0]}
            # DB-only safety net: level may already mark relay users even when
            # chain listing is temporarily incomplete.
            cur.execute(
                """
                SELECT LOWER(owner) FROM profiles
                WHERE subscriber_quota_epoch IS NULL
                  AND (effective_paid = TRUE OR level >= 1)
                """
            )
            db_relay_null = {str(row[0]) for row in cur.fetchall() if row and row[0]}

    owners = sorted((chain_relay_owners & null_quota) | db_relay_null)
    logger.info(
        "[quota] paid backfill candidates chain_relay=%d null_quota=%d project=%d",
        len(chain_relay_owners),
        len(null_quota),
        len(owners),
    )

    done = 0
    for owner in owners:
        runtime = chain.query_subscription_runtime(owner)
        db.update_subscription_runtime(owner, runtime)
        done += 1
        if done % 50 == 0 or done == len(owners):
            db.set_meta(progress_key, f"{done}/{len(owners)}")
            logger.info("[quota] paid backfill progress %d/%d", done, len(owners))

    logger.info(
        "[quota] projected relay quota for %d profiles with NULL projection",
        done,
    )
    return f"paid_quota_backfill owners={done}"
