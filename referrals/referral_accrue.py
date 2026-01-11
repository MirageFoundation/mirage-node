#!/usr/bin/env python3
"""
Referral reward accrual daemon.

Runs continuously, calculating pending rewards based on activity since last run.

Usage:
    python referrals/referral_accrue.py                 # Run daemon (continuous loop)
    python referrals/referral_accrue.py --once          # Run once and exit
    python referrals/referral_accrue.py --dry-run       # Show calculations without saving
    python referrals/referral_accrue.py --period 60     # Use 60-second periods (for testing)
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Set

# Add parent directory to path for shared imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.logging_setup import configure_logging

# Initialize logging
configure_logging("referrals", redirect_std=False)
logger = logging.getLogger("referrals")

# =============================================================================
# CONFIGURATION
# =============================================================================

DB_URL = "postgresql://mirage:mirage@127.0.0.1:5432/mirage"

# Reward rates by level (halving pyramid) - NO self-reward, only from referrals
REWARD_RATES = [0.0, 1.0, 0.5, 0.25, 0.125, 0.0625]  # L0=self (none), L1-L5=referrals
MAX_DEPTH = 5
MAX_LIFETIME_PERIODS = 10  # Lifetime cap per referee (total rewarded days)

# Period configuration (in seconds)
# Default: 86400 (1 day), can be overridden with --period flag
DEFAULT_PERIOD_SECONDS = 86400
STATE_KEY_LAST_RUN = "referral_accrue_last_run"
STATE_KEY_PERIOD = "referral_accrue_period"

# Global period value (set at startup)
PERIOD_SECONDS = DEFAULT_PERIOD_SECONDS


def format_period(seconds: int) -> str:
    """Format period for display."""
    if seconds >= 86400:
        days = seconds // 86400
        return f"{days} day{'s' if days > 1 else ''}"
    elif seconds >= 3600:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''}"
    elif seconds >= 60:
        mins = seconds // 60
        return f"{mins} minute{'s' if mins > 1 else ''}"
    else:
        return f"{seconds} second{'s' if seconds > 1 else ''}"


# =============================================================================
# DATABASE
# =============================================================================


def connect():
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("psycopg not installed. Run: pip install 'psycopg[binary]'")
    return psycopg.connect(DB_URL, autocommit=True)


def get_last_run_ts(cur) -> int:
    """Get timestamp of last successful run."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS referral_state (
            key VARCHAR(64) PRIMARY KEY,
            value BIGINT NOT NULL,
            updated_at BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())
        )
    """
    )
    cur.execute("SELECT value FROM referral_state WHERE key = %s", (STATE_KEY_LAST_RUN,))
    row = cur.fetchone()
    return int(row[0]) if row else 0


def set_last_run_ts(cur, ts: int):
    """Update last run timestamp."""
    cur.execute(
        """
        INSERT INTO referral_state (key, value, updated_at)
        VALUES (%s, %s, EXTRACT(EPOCH FROM NOW()))
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
    """,
        (STATE_KEY_LAST_RUN, ts),
    )


def set_period_seconds(cur, period_seconds: int):
    """Store the configured period so the backend can read it."""
    cur.execute(
        """
        INSERT INTO referral_state (key, value, updated_at)
        VALUES (%s, %s, EXTRACT(EPOCH FROM NOW()))
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
    """,
        (STATE_KEY_PERIOD, period_seconds),
    )


def ensure_rewarded_periods_table(cur):
    """Create table for tracking lifetime rewarded periods per referee."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS referral_rewarded_periods (
            referee_address VARCHAR(128) PRIMARY KEY,
            rewarded_count INTEGER NOT NULL DEFAULT 0,
            last_updated BIGINT
        )
    """
    )


def load_rewarded_periods(cur, referees: list[str]) -> Dict[str, int]:
    """Load existing rewarded period counts for given referees."""
    if not referees:
        return {}
    cur.execute(
        """
        SELECT referee_address, rewarded_count 
        FROM referral_rewarded_periods 
        WHERE referee_address = ANY(%s)
    """,
        (referees,),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def update_rewarded_periods(cur, period_updates: Dict[str, int], run_ts: int):
    """Update rewarded period counts."""
    for referee, new_periods in period_updates.items():
        if new_periods > 0:
            cur.execute(
                """
                INSERT INTO referral_rewarded_periods (referee_address, rewarded_count, last_updated)
                VALUES (%s, %s, %s)
                ON CONFLICT (referee_address) DO UPDATE SET 
                    rewarded_count = referral_rewarded_periods.rewarded_count + EXCLUDED.rewarded_count,
                    last_updated = EXCLUDED.last_updated
            """,
                (referee, new_periods, run_ts),
            )


# =============================================================================
# DATA LOADING
# =============================================================================


@dataclass
class UserActivity:
    owner: str
    active_periods: Set[int]
    period_count: int = 0


def load_referral_tree(cur) -> Dict[str, str]:
    """Load referrer for each user."""
    cur.execute("SELECT user_address, referrer_address FROM referral_links")
    return {row[0]: row[1] for row in cur.fetchall()}


def load_user_activity(cur, since_ts: int, period_seconds: int) -> Dict[str, UserActivity]:
    """Load active periods (posts/comments) since timestamp."""
    cur.execute(
        """
        SELECT LOWER(owner), created_at
        FROM posts
        WHERE created_at >= %s AND deleted = FALSE
    """,
        (since_ts,),
    )

    users: Dict[str, UserActivity] = {}
    for owner, created_at in cur.fetchall():
        o = owner.strip().lower()
        if o not in users:
            users[o] = UserActivity(owner=o, active_periods=set())
        period = created_at // period_seconds
        users[o].active_periods.add(period)

    for u in users.values():
        u.period_count = len(u.active_periods)

    return users


# =============================================================================
# REWARD CALCULATION
# =============================================================================


@dataclass
class AccrualDetail:
    beneficiary: str
    referee: str
    level: int
    amount: float


def calculate_referral_rewards(
    users: Dict[str, UserActivity],
    referral_tree: Dict[str, str],
    existing_rewarded: Dict[str, int],
) -> tuple[Dict[str, float], list[AccrualDetail], Dict[str, int]]:
    """Calculate rewards with lifetime cap per referee.

    Returns:
        - {user_address: reward_amount}
        - [per-referee details]
        - {referee_address: new_periods_to_add} for updating the cap tracker
    """
    rewards: Dict[str, float] = {}
    details: list[AccrualDetail] = []
    period_updates: Dict[str, int] = {}

    for owner, u in users.items():
        if u.period_count == 0:
            continue

        # Check lifetime cap for this referee
        already_rewarded = existing_rewarded.get(owner, 0)
        remaining_quota = MAX_LIFETIME_PERIODS - already_rewarded
        if remaining_quota <= 0:
            continue

        # Cap this run's periods to remaining quota
        active_periods = min(remaining_quota, u.period_count)
        period_updates[owner] = active_periods

        # Walk up the referral tree and reward each level
        current = owner
        for level in range(1, MAX_DEPTH + 1):
            referrer = referral_tree.get(current)
            if not referrer:
                break

            reward = active_periods * REWARD_RATES[level]
            rewards[referrer] = rewards.get(referrer, 0.0) + reward
            details.append(
                AccrualDetail(
                    beneficiary=referrer,
                    referee=owner,
                    level=level,
                    amount=reward,
                )
            )
            current = referrer

    return rewards, details, period_updates


def save_rewards(cur, rewards: Dict[str, float], details: list[AccrualDetail], run_ts: int) -> int:
    """Save rewards to pending table and per-referee accruals."""
    count = 0
    for user, amount in rewards.items():
        if amount > 0:
            cur.execute(
                """
                INSERT INTO referral_pending_rewards 
                (user_address, period_start, period_end, referral_reward, total_pending, status)
                VALUES (%s, %s, %s, %s, %s, 'pending')
                ON CONFLICT (user_address, period_start) 
                DO UPDATE SET 
                    referral_reward = referral_pending_rewards.referral_reward + EXCLUDED.referral_reward,
                    total_pending = referral_pending_rewards.total_pending + EXCLUDED.total_pending
            """,
                (user, run_ts, run_ts, amount, amount),
            )
            count += 1

    # Save per-referee accrual details
    for d in details:
        cur.execute(
            """
            INSERT INTO referral_user_accruals 
            (beneficiary_address, referee_address, level, pending, last_updated)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (beneficiary_address, referee_address) 
            DO UPDATE SET 
                pending = referral_user_accruals.pending + EXCLUDED.pending,
                last_updated = EXCLUDED.last_updated
        """,
            (d.beneficiary, d.referee, d.level, d.amount, run_ts),
        )

    return count


# =============================================================================
# MAIN
# =============================================================================


def run_accrual(dry_run: bool = False, period_seconds: int = DEFAULT_PERIOD_SECONDS) -> bool:
    """Run one accrual cycle."""
    now_ts = int(time.time())

    with connect() as conn:
        with conn.cursor() as cur:
            last_run = get_last_run_ts(cur)

            if last_run == 0:
                # First run - for daily periods, look back to previous midnight
                if period_seconds == 86400:
                    since_ts = get_midnight_utc(now_ts) - 86400
                    since_str = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    logger.info(f"First run, checking since {since_str}")
                else:
                    since_ts = now_ts - period_seconds
                    logger.info(f"First run, checking last {format_period(period_seconds)}")
            else:
                # For daily periods, use midnight boundaries
                if period_seconds == 86400:
                    since_ts = get_midnight_utc(last_run)
                    since_str = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    logger.info(f"Checking activity since {since_str} (midnight UTC)")
                else:
                    since_ts = last_run
                    elapsed = now_ts - since_ts
                    logger.info(f"Checking activity since last run ({format_period(elapsed)} ago)")

            referral_tree = load_referral_tree(cur)
            logger.info(f"Referral relationships: {len(referral_tree)}")

            if not referral_tree:
                logger.info("No referrals found. Skipping.")
                if not dry_run:
                    set_last_run_ts(cur, now_ts)
                    set_period_seconds(cur, period_seconds)
                return False

            users = load_user_activity(cur, since_ts, period_seconds)
            active_count = sum(1 for u in users.values() if u.period_count > 0)
            logger.info(f"Active users since last run: {active_count}")

            # Ensure tracking table exists and load existing rewarded periods
            ensure_rewarded_periods_table(cur)
            existing_rewarded = load_rewarded_periods(cur, list(users.keys()))
            capped_count = sum(1 for u in users if existing_rewarded.get(u, 0) >= MAX_LIFETIME_PERIODS)
            if capped_count > 0:
                logger.info(f"Users at lifetime cap ({MAX_LIFETIME_PERIODS} days): {capped_count}")

            # Calculate rewards
            rewards, details, period_updates = calculate_referral_rewards(users, referral_tree, existing_rewarded)
            total = sum(rewards.values())
            logger.info(f"Total rewards: {total:.4f} MIRAGE for {len(rewards)} users")
            logger.info(f"Per-referee accruals: {len(details)} entries")

            if rewards:
                top = sorted(rewards.items(), key=lambda x: x[1], reverse=True)[:5]
                logger.info("Top earners:")
                for user, amount in top:
                    logger.info(f"  {user[:16]}...: {amount:.4f} MIRAGE")

            if dry_run:
                logger.info("DRY RUN - not saving")
            else:
                count = save_rewards(cur, rewards, details, now_ts)
                update_rewarded_periods(cur, period_updates, now_ts)
                set_last_run_ts(cur, now_ts)
                set_period_seconds(cur, period_seconds)
                logger.info(f"Saved {count} reward records")

    return True


def get_midnight_utc(ts: int) -> int:
    """Get the midnight UTC timestamp for the day containing ts."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp())


def get_next_midnight_utc() -> int:
    """Get the next midnight UTC timestamp."""
    now = datetime.now(tz=timezone.utc)
    # Get today's midnight, then add 1 day
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    next_midnight = today_midnight + timedelta(days=1)
    return int(next_midnight.timestamp())


def should_run_now(period_seconds: int) -> tuple[bool, int]:
    """Check if enough time has passed. Returns (should_run, seconds_until_next).
    
    For daily periods (86400s), aligns to midnight UTC.
    """
    with connect() as conn:
        with conn.cursor() as cur:
            last_run = get_last_run_ts(cur)

    now_ts = int(time.time())

    if last_run == 0:
        # First run: if daily period, wait for next midnight; otherwise run now
        if period_seconds == 86400:
            next_midnight = get_next_midnight_utc()
            remaining = next_midnight - now_ts
            return (remaining <= 0, max(0, remaining))
        return True, 0

    # For daily periods, align to midnight UTC
    if period_seconds == 86400:
        last_midnight = get_midnight_utc(last_run)
        next_midnight = last_midnight + 86400
        remaining = next_midnight - now_ts
        return (remaining <= 0, max(0, remaining))

    # For other periods, just check elapsed time
    next_run = last_run + period_seconds
    remaining = next_run - now_ts
    return (remaining <= 0, max(0, remaining))


def format_duration(seconds: int) -> str:
    if seconds >= 86400:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days}d {hours}h" if hours > 0 else f"{days}d"
    elif seconds >= 3600:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"
    elif seconds >= 60:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s" if secs > 0 else f"{minutes}m"
    else:
        return f"{seconds}s"


def main():
    parser = argparse.ArgumentParser(description="Referral reward accrual daemon")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--dry-run", action="store_true", help="Show without saving")
    parser.add_argument("--force", action="store_true", help="Run immediately")
    parser.add_argument(
        "--period",
        type=int,
        default=DEFAULT_PERIOD_SECONDS,
        help=f"Period in seconds (default: {DEFAULT_PERIOD_SECONDS})",
    )
    args = parser.parse_args()

    period_seconds = args.period
    global PERIOD_SECONDS
    PERIOD_SECONDS = period_seconds

    logger.info("=" * 50)
    logger.info("Referral Accrual Daemon")
    logger.info("=" * 50)
    logger.info(f"Period: {format_period(period_seconds)} ({period_seconds}s)")
    if period_seconds == 86400:
        logger.info("  -> Aligned to midnight UTC")
    logger.info(f"Lifetime cap: {MAX_LIFETIME_PERIODS} active periods per referral")
    logger.info(f"Reward rates: L1={REWARD_RATES[1]}, L2={REWARD_RATES[2]}, L3={REWARD_RATES[3]}...")

    running = True

    def signal_handler(sig, frame):
        nonlocal running
        logger.info("Shutting down...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.once or args.dry_run:
        if args.force or args.dry_run:
            run_accrual(dry_run=args.dry_run, period_seconds=period_seconds)
        else:
            should_run, wait = should_run_now(period_seconds)
            if should_run:
                run_accrual(dry_run=args.dry_run, period_seconds=period_seconds)
            else:
                logger.info(f"Last run was recent. Next run in {format_duration(wait)}.")
                logger.info("Use --force to run anyway.")
        return

    logger.info("Running in daemon mode. Press Ctrl+C to stop.")

    while running:
        should_run, wait = should_run_now(period_seconds)

        if args.force or should_run:
            args.force = False
            run_accrual(dry_run=False, period_seconds=period_seconds)
            wait = period_seconds

        if not running:
            break

        next_time = datetime.fromtimestamp(int(time.time()) + wait, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        logger.info(f"Next run in {format_duration(wait)} at {next_time}")

        # Sleep in 1-second chunks for fast shutdown
        while wait > 0 and running:
            time.sleep(1)
            wait -= 1

    logger.info("Daemon stopped.")


if __name__ == "__main__":
    main()
