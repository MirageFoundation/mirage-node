#!/usr/bin/env python3
"""
Manage invite codes: replenish for all users, give codes to a specific user, or list codes.

Modes:
1. Replenish all users: Gives every user a target number of invite codes (default: 3).
   If a user already has some codes, only adds enough to reach the target.

2. Give to specific user: Adds a specific number of codes to one user and returns their full code list.

3. List codes for a user: Shows all codes (unused and used) without creating new ones.

Usage:
    python3 scripts/manage_invites.py                    # Top up all users to 3 codes
    python3 scripts/manage_invites.py --target 5         # Top up all users to 5 codes
    python3 scripts/manage_invites.py --dry-run          # Show what would happen without making changes
    python3 scripts/manage_invites.py --user Santa --count 100   # Give Santa 100 new codes, show all their codes
    python3 scripts/manage_invites.py --user Santa --list        # List all of Santa's codes (no changes)
"""

import argparse
import os
import random
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


def list_codes_for_user(conn, username: str) -> None:
    """List all codes for a user without creating new ones."""
    cur = conn.cursor()

    # Find the user by username (case-insensitive)
    cur.execute(
        "SELECT owner, username FROM profiles WHERE LOWER(username) = LOWER(%s)",
        (username,),
    )
    row = cur.fetchone()
    if not row:
        print(f"Error: User '{username}' not found", file=sys.stderr)
        sys.exit(1)

    owner, actual_username = row
    print(f"User: {actual_username} ({owner[:20]}...)")
    print()

    # Get all codes for this user
    cur.execute(
        """
        SELECT code, created_at, used_by 
        FROM invite_codes 
        WHERE LOWER(owner) = LOWER(%s)
        ORDER BY created_at DESC
        """,
        (owner,),
    )
    all_codes = cur.fetchall()

    if not all_codes:
        print("No invite codes found for this user.")
        return

    unused_codes = []
    used_codes = []
    for code, created_at, used_by in all_codes:
        if used_by:
            used_codes.append((code, used_by))
        else:
            unused_codes.append(code)

    print("=" * 60)
    print(f"ALL CODES FOR {actual_username} ({len(all_codes)} total)")
    print("=" * 60)
    print()

    print(f"UNUSED CODES ({len(unused_codes)}):")
    print("-" * 40)
    if unused_codes:
        for code in unused_codes:
            print(f"  {code}")
    else:
        print("  (none)")
    print()

    if used_codes:
        print(f"USED CODES ({len(used_codes)}):")
        print("-" * 40)
        for code, used_by in used_codes:
            print(f"  {code}  -> {used_by[:30]}...")
        print()

    print("=" * 60)


def give_codes_to_user(conn, username: str, count: int, dry_run: bool) -> None:
    """Give a specific number of codes to a user and print their full code list."""
    cur = conn.cursor()

    # Find the user by username (case-insensitive)
    cur.execute(
        "SELECT owner, username FROM profiles WHERE LOWER(username) = LOWER(%s)",
        (username,),
    )
    row = cur.fetchone()
    if not row:
        print(f"Error: User '{username}' not found", file=sys.stderr)
        sys.exit(1)

    owner, actual_username = row
    print(f"Found user: {actual_username} ({owner[:20]}...)")
    print()

    # Get existing codes for uniqueness check
    existing_codes = get_existing_codes(cur)

    # Get user's current codes
    cur.execute(
        """
        SELECT code, created_at, used_by 
        FROM invite_codes 
        WHERE LOWER(owner) = LOWER(%s)
        ORDER BY created_at DESC
        """,
        (owner,),
    )
    current_codes = cur.fetchall()
    print(f"Current codes: {len(current_codes)}")
    print(f"Codes to add: {count}")
    print()

    if dry_run:
        print("DRY RUN - no changes will be made")
        print()
        print(f"Would add {count} codes to {actual_username}")
        print()
        print("Current codes:")
        for code, created_at, used_by in current_codes:
            status = f"used by {used_by[:20]}..." if used_by else "unused"
            print(f"  {code}  ({status})")
        return

    # Confirmation
    print("Type 'confirm' to proceed, or anything else to cancel:")
    confirmation = input("> ").strip().lower()
    if confirmation != "confirm":
        print("Cancelled.")
        sys.exit(0)

    print()
    print(f"Creating {count} codes for {actual_username}...")

    now_ts = int(time.time())
    new_codes = []
    for _ in range(count):
        code = generate_unique_code(existing_codes)
        existing_codes.add(code)
        cur.execute(
            """
            INSERT INTO invite_codes (code, owner, created_at)
            VALUES (%s, %s, %s)
            """,
            (code, owner, now_ts),
        )
        new_codes.append(code)

    print(f"Created {len(new_codes)} new codes")
    print()

    # Get full updated code list
    cur.execute(
        """
        SELECT code, created_at, used_by 
        FROM invite_codes 
        WHERE LOWER(owner) = LOWER(%s)
        ORDER BY created_at DESC
        """,
        (owner,),
    )
    all_codes = cur.fetchall()

    print("=" * 60)
    print(f"ALL CODES FOR {actual_username} ({len(all_codes)} total)")
    print("=" * 60)
    print()

    unused_codes = []
    used_codes = []
    for code, created_at, used_by in all_codes:
        if used_by:
            used_codes.append((code, used_by))
        else:
            unused_codes.append(code)

    print(f"UNUSED CODES ({len(unused_codes)}):")
    print("-" * 40)
    for code in unused_codes:
        print(f"  {code}")
    print()

    if used_codes:
        print(f"USED CODES ({len(used_codes)}):")
        print("-" * 40)
        for code, used_by in used_codes:
            print(f"  {code}  -> {used_by[:30]}...")
        print()

    print("=" * 60)
    print("Done!")


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
    parser.add_argument(
        "--user",
        type=str,
        help="Username to give codes to (instead of replenishing all users)",
    )
    parser.add_argument(
        "--count",
        type=int,
        help="Number of codes to give to --user (required with --user unless --list)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all codes for --user without creating new ones",
    )
    args = parser.parse_args()

    # Validate args
    if args.list and not args.user:
        print("Error: --user is required when using --list", file=sys.stderr)
        sys.exit(1)
    if args.list and args.count:
        print("Error: --list and --count cannot be used together", file=sys.stderr)
        sys.exit(1)
    if args.user and not args.count and not args.list:
        print("Error: --count or --list is required when using --user", file=sys.stderr)
        sys.exit(1)
    if args.count and not args.user:
        print("Error: --user is required when using --count", file=sys.stderr)
        sys.exit(1)
    if args.count and args.count < 1:
        print("Error: --count must be at least 1", file=sys.stderr)
        sys.exit(1)

    target = args.target
    dry_run = args.dry_run

    if target < 1:
        print("Error: --target must be at least 1", file=sys.stderr)
        sys.exit(1)

    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        print("Error: INDEXER_DB_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    try:
        conn = psycopg.connect(db_url, autocommit=True)
    except Exception as e:
        print(f"Error connecting to database: {e}", file=sys.stderr)
        sys.exit(1)

    # Single user mode: list only
    if args.user and args.list:
        list_codes_for_user(conn, args.user)
        conn.close()
        return

    # Single user mode: add codes
    if args.user:
        give_codes_to_user(conn, args.user, args.count, dry_run)
        conn.close()
        return

    # Replenish all users mode
    print(f"Replenishing invite codes (target: {target} per user)")
    if dry_run:
        print("DRY RUN - no changes will be made")
    print()

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


if __name__ == "__main__":
    main()
