#!/usr/bin/env python3
"""
Replenish invite codes for all users on the platform.

Gives every user a target number of invite codes (default: 3).
If a user already has some codes, only adds enough to reach the target.

Usage:
    python3 scripts/replenish_invites.py                    # Top up all users to 3 codes
    python3 scripts/replenish_invites.py --target 5         # Top up all users to 5 codes
    python3 scripts/replenish_invites.py --dry-run          # Show what would happen without making changes
"""

import argparse
import os
import random
import string
import sys
import time

import psycopg

# Characters for invite codes (uppercase alphanumeric, excluding confusing chars)
CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # Excludes I, O, 0, 1 for clarity


def generate_code() -> str:
    """Generate a random invite code in format XXXX-XXXX."""
    part1 = "".join(random.choices(CODE_CHARS, k=4))
    part2 = "".join(random.choices(CODE_CHARS, k=4))
    return f"{part1}-{part2}"


def get_existing_codes(cur) -> set:
    """Get all existing invite codes to avoid duplicates."""
    cur.execute("SELECT code FROM invite_codes")
    return {row[0] for row in cur.fetchall()}


def generate_unique_code(existing: set) -> str:
    """Generate a code that doesn't already exist."""
    for _ in range(1000):
        code = generate_code()
        if code not in existing:
            return code
    raise RuntimeError("Failed to generate unique code after 1000 attempts")


def main():
    parser = argparse.ArgumentParser(description="Replenish invite codes for all users")
    parser.add_argument(
        "--target",
        type=int,
        default=3,
        help="Target number of invite codes per user (default: 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes",
    )
    args = parser.parse_args()

    target = args.target
    dry_run = args.dry_run

    if target < 1:
        print("Error: --target must be at least 1", file=sys.stderr)
        sys.exit(1)

    db_url = os.environ.get("MIRAGE_INDEXER_DB_URL", "").strip()
    if not db_url:
        print("Error: MIRAGE_INDEXER_DB_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    print(f"Replenishing invite codes (target: {target} per user)")
    if dry_run:
        print("DRY RUN - no changes will be made")
    print()

    try:
        conn = psycopg.connect(db_url, autocommit=True)
        cur = conn.cursor()

        # Get all users with profiles
        cur.execute("SELECT owner FROM profiles")
        users = [row[0] for row in cur.fetchall()]
        print(f"Found {len(users)} users with profiles")

        # Get existing codes for uniqueness check
        existing_codes = get_existing_codes(cur)
        print(f"Found {len(existing_codes)} existing invite codes")

        # Count codes per user
        cur.execute(
            """
            SELECT LOWER(owner), COUNT(*) 
            FROM invite_codes 
            GROUP BY LOWER(owner)
            """
        )
        codes_per_user = {row[0]: row[1] for row in cur.fetchall()}

        # Calculate what needs to be done
        users_needing_codes = []
        total_to_create = 0
        for user in users:
            user_lower = user.lower()
            current_count = codes_per_user.get(user_lower, 0)
            needed = target - current_count
            if needed > 0:
                users_needing_codes.append((user, current_count, needed))
                total_to_create += needed

        print()
        print("=" * 50)
        print(f"Users total: {len(users)}")
        print(f"Users needing codes: {len(users_needing_codes)}")
        print(f"Codes to create: {total_to_create}")
        print("=" * 50)

        if total_to_create == 0:
            print("\nNo codes need to be created. All users already have enough.")
            conn.close()
            return

        if dry_run:
            print("\nDRY RUN - showing what would be created:\n")
            for user, current, needed in users_needing_codes:
                print(f"  {user[:20]}... has {current} codes, would add {needed}")
            print()
            print(f"Would create {total_to_create} codes for {len(users_needing_codes)} users")
            print("(DRY RUN - no actual changes made)")
            conn.close()
            return

        # Confirmation required for actual changes
        print()
        print("This will create invite codes in the database.")
        print("Type 'confirm' to proceed, or anything else to cancel:")
        confirmation = input("> ").strip().lower()
        if confirmation != "confirm":
            print("Cancelled.")
            conn.close()
            sys.exit(0)

        print()
        print("Creating codes...")
        total_created = 0
        now_ts = int(time.time())

        for user, current_count, needed in users_needing_codes:
            print(f"  {user[:20]}... has {current_count} codes, adding {needed}")
            for _ in range(needed):
                code = generate_unique_code(existing_codes)
                existing_codes.add(code)
                cur.execute(
                    """
                    INSERT INTO invite_codes (code, owner, created_at)
                    VALUES (%s, %s, %s)
                    """,
                    (code, user, now_ts),
                )
                total_created += 1

        conn.close()

        print()
        print("=" * 50)
        print(f"Users updated: {len(users_needing_codes)}")
        print(f"Codes created: {total_created}")
        print("Done!")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
