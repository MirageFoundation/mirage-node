"""
v1.7.5 Migration: Backfill subscription_expiry from chain state

The indexer had a bug where subscription_expiry wasn't being updated on
subscription renewals (fixed in v1.7.4). This migration backfills the correct
values from chain state for all profiles.
"""

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logging import Logger
    from indexer.database import DatabaseManager
    from indexer.chain_client import ChainClient

MIGRATION_KEY = "v1.7.5_subscription_expiry"


def run(db: "DatabaseManager", chain: "ChainClient", logger: "Logger") -> str:
    """Backfill subscription_expiry values from chain state."""
    logger.info("v1.7.5 migration: Fetching profiles from chain...")
    
    try:
        chain_profiles = chain.list_profiles_subspace()
    except Exception as e:
        raise RuntimeError(f"Failed to fetch profiles from chain: {e}") from e
    
    logger.info(f"v1.7.5 migration: Found {len(chain_profiles)} profiles on chain")
    
    now = int(time.time())
    updated_count = 0
    skipped_count = 0
    active_count = 0
    
    for profile in chain_profiles:
        owner = profile.get("owner", "")
        if not owner:
            continue
        
        level = int(profile.get("level", 0) or 0)
        subscription_expiry = int(profile.get("subscription_expiry", 0) or 0)
        
        # Only update profiles that have subscription data
        if level == 0 and subscription_expiry == 0:
            skipped_count += 1
            continue
        
        # Track active subscriptions
        if subscription_expiry > now and level > 0:
            active_count += 1
        
        try:
            success = db.update_profile_subscription(owner, level, subscription_expiry, now)
            if success:
                updated_count += 1
            else:
                skipped_count += 1
        except Exception as e:
            logger.warning(f"v1.7.5 migration: Error updating {owner}: {e}")
            skipped_count += 1
    
    logger.info(
        f"v1.7.5 migration: Updated {updated_count} profiles, "
        f"skipped {skipped_count}, active subscriptions: {active_count}"
    )
    return f"completed:updated={updated_count},active={active_count}"
