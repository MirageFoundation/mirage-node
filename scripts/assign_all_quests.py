#!/usr/bin/env python3
"""
Assign ALL quests to a single user and optionally mark them completed.

This manually inserts every daily quest, flash quest, special quest, and
achievement for a user — useful for testing the full quest UI and claim flow.

Usage:
    # Assign all quests (pending, user must complete them naturally):
    python3 scripts/assign_all_quests.py --user Alice

    # Assign all quests AND mark them completed (ready to claim):
    python3 scripts/assign_all_quests.py --user Alice --complete

    # Dry run (show what would happen):
    python3 scripts/assign_all_quests.py --user Alice --complete --dry-run

Requires INDEXER_DB_URL environment variable.
"""

import argparse
import json
import os
import sys
import time

import psycopg


# ---------------------------------------------------------------------------
# Quest definitions (mirrored from quests.yaml)
# ---------------------------------------------------------------------------

DAILY_QUESTS = [
    {"id": "active_poster", "target": 5, "reward_mirage": 1000},
    {"id": "quality_creator", "target": 1, "reward_mirage": 2500},
    {"id": "engaged_commenter", "target": 1, "reward_mirage": 1500},
    {"id": "community_curator", "target": 15, "reward_mirage": 1500},
    {"id": "balanced_voter", "target": 10, "reward_mirage": 1250},
    {"id": "topic_explorer", "target": 3, "reward_mirage": 1000},
    {"id": "casual_poster", "target": 2, "reward_mirage": 400},
    {"id": "conversation_contributor", "target": 5, "reward_mirage": 600},
    {"id": "quick_curator", "target": 5, "reward_mirage": 300},
    {"id": "thoughtful_commenter", "target": 3, "reward_mirage": 500},
    {"id": "daily_voter", "target": 10, "reward_mirage": 500},
]

SPECIAL_QUESTS = [
    {"id": "invite_recruit", "target": 1, "reward_mirage": 10000},
    {"id": "invite_referred", "target": 1, "reward_mirage": 10000, "no_multiplier": True},
    {"id": "invite_earner", "target": 1, "reward_type": "invite_code", "reward_amount": 1},
]

FLASH_QUESTS = [
    {"id": "quick_vote", "target": 3, "window_min": 10, "reward_mirage": 200},
    {"id": "first_comment", "target": 1, "window_min": 5, "reward_mirage": 100},
    {"id": "speed_voter", "target": 5, "window_min": 15, "reward_mirage": 200},
    {"id": "quick_post", "target": 1, "window_min": 10, "reward_mirage": 250},
    {"id": "mini_commenter", "target": 3, "window_min": 20, "reward_mirage": 450},
    {"id": "double_vote", "target": 2, "window_min": 5, "reward_mirage": 100},
    {"id": "comment_blitz", "target": 5, "window_min": 60, "reward_mirage": 1500},
    {"id": "voting_spree", "target": 15, "window_min": 180, "reward_mirage": 2500},
]

ACHIEVEMENTS = [
    {"id": "first_viral", "target": 1, "reward_mirage": 100000},
    {"id": "conversation_starter", "target": 1, "reward_mirage": 50000},
    {"id": "trusted_member", "target": 10, "reward_mirage": 75000},
    {"id": "topic_pioneer", "target": 1, "reward_mirage": 20000},
]


def _utc_day(ts: int) -> int:
    """Convert unix timestamp to UTC Julian day number."""
    return 2440588 + ts // 86400


def resolve_user(cur, username: str) -> tuple[str, str]:
    """Resolve username to (owner_address, display_username). Exits on failure."""
    cur.execute(
        "SELECT owner, username FROM profiles WHERE LOWER(username) = LOWER(%s)",
        (username,),
    )
    row = cur.fetchone()
    if not row:
        print(f"Error: User '{username}' not found", file=sys.stderr)
        sys.exit(1)
    return row[0], row[1]


def assign_daily_quests(cur, owner: str, day_utc: int, complete: bool, ts: int, dry_run: bool) -> int:
    """Insert all daily + special quests for the user. Returns count."""
    count = 0
    all_quests = DAILY_QUESTS + SPECIAL_QUESTS

    for q in all_quests:
        qid = q["id"]
        target = q["target"]
        progress = target if complete else 0
        completed_at = ts if complete else None

        if dry_run:
            status = "completed" if complete else "pending"
            print(f"  [DRY] daily quest: {qid} ({status})")
            count += 1
            continue

        cur.execute(
            """
            INSERT INTO user_daily_quests (owner, day_utc, quest_id, progress, progress_meta, completed_at)
            VALUES (%s, %s, %s, %s, '{}', %s)
            ON CONFLICT (owner, day_utc, quest_id) DO UPDATE SET
                progress = EXCLUDED.progress,
                completed_at = EXCLUDED.completed_at
            """,
            (owner, day_utc, qid, progress, completed_at),
        )
        count += 1

        # Add pending reward if completing
        if complete:
            _add_reward(cur, owner, q, f"quest:{qid}", ts, dry_run)

    return count


def assign_flash_quests(cur, owner: str, complete: bool, ts: int, dry_run: bool) -> int:
    """Insert all flash quests for the user. Returns count."""
    count = 0

    for q in FLASH_QUESTS:
        qid = q["id"]
        target = q["target"]
        window = q["window_min"] * 60
        starts_at = ts
        ends_at = ts + window
        progress = target if complete else 0
        completed_at = ts if complete else None

        if dry_run:
            status = "completed" if complete else "active"
            print(f"  [DRY] flash quest: {qid} ({status}, {q['window_min']}min window)")
            count += 1
            continue

        cur.execute(
            """
            INSERT INTO user_flash_quests (owner, template_id, starts_at, ends_at, progress, progress_meta, completed_at)
            VALUES (%s, %s, %s, %s, %s, '{}', %s)
            ON CONFLICT (owner, starts_at) DO UPDATE SET
                template_id = EXCLUDED.template_id,
                progress = EXCLUDED.progress,
                completed_at = EXCLUDED.completed_at
            """,
            (owner, qid, starts_at, ends_at, progress, completed_at),
        )
        # Stagger starts_at so each flash quest gets a unique PK
        ts += 1
        count += 1

        if complete:
            _add_reward(cur, owner, q, f"flash:{qid}", ts, dry_run)

    return count


def assign_achievements(cur, owner: str, complete: bool, ts: int, dry_run: bool) -> int:
    """Insert all achievements for the user. Returns count."""
    count = 0

    for a in ACHIEVEMENTS:
        aid = a["id"]
        target = a["target"]
        progress = target if complete else 0
        unlocked_at = ts if complete else None

        if dry_run:
            status = "unlocked" if complete else "in progress"
            print(f"  [DRY] achievement: {aid} ({status})")
            count += 1
            continue

        cur.execute(
            """
            INSERT INTO user_achievements (owner, achievement_id, unlocked_at, progress, progress_meta)
            VALUES (%s, %s, %s, %s, '{}')
            ON CONFLICT (owner, achievement_id) DO UPDATE SET
                progress = EXCLUDED.progress,
                unlocked_at = EXCLUDED.unlocked_at
            """,
            (owner, aid, unlocked_at or 0, progress),
        )
        count += 1

        if complete:
            _add_reward(cur, owner, a, f"achievement:{aid}", ts, dry_run)

    return count


def _add_reward(cur, owner: str, quest: dict, reason: str, ts: int, dry_run: bool) -> None:
    """Insert a pending reward for a completed quest/achievement."""
    reward_type = quest.get("reward_type", "mirage")

    if reward_type == "mirage":
        amount_mirage = quest.get("reward_mirage", 0)
        amount_umirage = amount_mirage * 1_000_000
        apply_multiplier = not quest.get("no_multiplier", False)
        reward_data = {"amount": amount_umirage, "apply_multiplier": apply_multiplier}
    elif reward_type == "invite_code":
        reward_data = {"amount": quest.get("reward_amount", 1)}
    else:
        reward_data = {}

    if dry_run:
        if reward_type == "mirage":
            print(f"    [DRY] reward: {quest.get('reward_mirage', 0):,} MIRAGE ({reason})")
        else:
            print(f"    [DRY] reward: {reward_type} ({reason})")
        return

    cur.execute(
        """
        INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (owner, reward_type, json.dumps(reward_data), reason, ts),
    )


def main():
    parser = argparse.ArgumentParser(description="Assign all quests to a user")
    parser.add_argument("--user", required=True, help="Username to assign quests to")
    parser.add_argument("--complete", action="store_true", help="Mark all quests as completed (ready to claim)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    args = parser.parse_args()

    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        print("Error: INDEXER_DB_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    try:
        conn = psycopg.connect(db_url, autocommit=True)
    except Exception as e:
        print(f"Error connecting to database: {e}", file=sys.stderr)
        sys.exit(1)

    cur = conn.cursor()
    owner, display_name = resolve_user(cur, args.user)
    ts = int(time.time())
    day_utc = _utc_day(ts)
    mode = "completed + rewards" if args.complete else "pending (must complete naturally)"

    print(f"User:   {display_name} ({owner})")
    print(f"Day:    {day_utc} (UTC)")
    print(f"Mode:   {mode}")
    if args.dry_run:
        print(f"        ** DRY RUN — no changes will be made **")
    print()

    # Daily + special quests
    print("Daily & special quests:")
    n_daily = assign_daily_quests(cur, owner, day_utc, args.complete, ts, args.dry_run)
    print(f"  -> {n_daily} quests")

    # Flash quests
    print("\nFlash quests:")
    n_flash = assign_flash_quests(cur, owner, args.complete, ts, args.dry_run)
    print(f"  -> {n_flash} quests")

    # Achievements
    print("\nAchievements:")
    n_ach = assign_achievements(cur, owner, args.complete, ts, args.dry_run)
    print(f"  -> {n_ach} achievements")

    total = n_daily + n_flash + n_ach
    print(f"\nTotal: {total} quests/achievements assigned")

    if args.complete and not args.dry_run:
        total_mirage = sum(
            q.get("reward_mirage", 0) for q in DAILY_QUESTS + SPECIAL_QUESTS + FLASH_QUESTS + ACHIEVEMENTS
        )
        print(f"Pending rewards: {total_mirage:,} MIRAGE + 1 invite code")
        print(f"User can claim via /api/rewards/claim")

    conn.close()


if __name__ == "__main__":
    main()
