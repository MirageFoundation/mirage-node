#!/usr/bin/env python3
"""
Manage invite codes: replenish for all users, add codes to a specific user, or list codes.

Modes:
1. Replenish all users: Top up every user to a target number of unused codes (default: 3).
2. Replenish single user: Top up one user to the target number of unused codes.
3. Add codes to a user: Create a specific number of new codes for one user.
4. List codes for a user: Shows unused codes without creating new ones.

Usage:
    python3 scripts/manage_invites.py                          # Top up all users to 3 unused codes
    python3 scripts/manage_invites.py --target 5               # Top up all users to 5 unused codes
    python3 scripts/manage_invites.py --dry-run                # Show what would happen without making changes
    python3 scripts/manage_invites.py --user Santa             # List Santa's unused codes
    python3 scripts/manage_invites.py --user Santa --add 10    # Create 10 new codes for Santa
    python3 scripts/manage_invites.py --user Santa --replenish # Top up Santa to target (default: 3)
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


def get_user(cur, username: str):
    """Find a user by username (case-insensitive). Exits if not found."""
    cur.execute(
        "SELECT owner, username FROM profiles WHERE LOWER(username) = LOWER(%s)",
        (username,),
    )
    row = cur.fetchone()
    if not row:
        print(f"Error: User '{username}' not found", file=sys.stderr)
        sys.exit(1)
    return row[0], row[1]


def get_unused_count(cur, owner: str) -> int:
    """Get count of unused codes for a user."""
    cur.execute(
        "SELECT COUNT(*) FROM invite_codes WHERE LOWER(owner) = LOWER(%s) AND used_by IS NULL",
        (owner,),
    )
    return cur.fetchone()[0]


def get_unused_codes(cur, owner: str) -> list:
    """Get list of unused codes for a user."""
    cur.execute(
        """
        SELECT code
        FROM invite_codes 
        WHERE LOWER(owner) = LOWER(%s) AND used_by IS NULL
        ORDER BY created_at DESC
        """,
        (owner,),
    )
    return [row[0] for row in cur.fetchall()]


def print_unused_codes(actual_username: str, unused_codes: list) -> None:
    """Print a user's unused codes."""
    print("=" * 60)
    print(f"UNUSED CODES FOR {actual_username} ({len(unused_codes)})")
    print("=" * 60)
    print()
    if unused_codes:
        for code in unused_codes:
            print(f"  {code}")
    else:
        print("  (none)")
    print()
    print("=" * 60)


def create_codes(cur, owner: str, count: int, existing_codes: set) -> list:
    """Create new invite codes for a user. Returns list of new codes."""
    now_ts = int(time.time())
    new_codes = []
    for _ in range(count):
        code = generate_unique_code(existing_codes)
        existing_codes.add(code)
        cur.execute(
            "INSERT INTO invite_codes (code, owner, created_at) VALUES (%s, %s, %s)",
            (code, owner, now_ts),
        )
        new_codes.append(code)
    return new_codes


def list_codes_for_user(conn, username: str) -> None:
    """List unused codes for a user."""
    cur = conn.cursor()
    owner, actual_username = get_user(cur, username)
    print(f"User: {actual_username} ({owner[:20]}...)")
    print()
    unused_codes = get_unused_codes(cur, owner)
    print_unused_codes(actual_username, unused_codes)


def add_codes_to_user(conn, username: str, count: int, dry_run: bool) -> None:
    """Add a specific number of new codes to a user."""
    cur = conn.cursor()
    owner, actual_username = get_user(cur, username)

    unused_count = get_unused_count(cur, owner)
    print(f"User: {actual_username} ({owner[:20]}...)")
    print(f"Unused codes: {unused_count}")
    print(f"Adding: {count}")
    print()

    if dry_run:
        print(f"DRY RUN - would add {count} codes to {actual_username}")
        return

    print("Type 'confirm' to proceed, or anything else to cancel:")
    confirmation = input("> ").strip().lower()
    if confirmation != "confirm":
        print("Cancelled.")
        sys.exit(0)

    print()
    existing_codes = get_existing_codes(cur)
    new_codes = create_codes(cur, owner, count, existing_codes)
    print(f"Created {len(new_codes)} new codes")
    print()

    unused_codes = get_unused_codes(cur, owner)
    print_unused_codes(actual_username, unused_codes)


def replenish_user(conn, username: str, target: int, dry_run: bool) -> None:
    """Top up a single user to the target number of unused codes."""
    cur = conn.cursor()
    owner, actual_username = get_user(cur, username)

    unused_count = get_unused_count(cur, owner)
    needed = max(0, target - unused_count)

    print(f"User: {actual_username} ({owner[:20]}...)")
    print(f"Unused codes: {unused_count}")
    print(f"Target: {target}")
    print()

    if needed == 0:
        print(f"Already has {unused_count} unused codes (target: {target}). Nothing to do.")
        return

    print(f"Need to create: {needed}")
    print()

    if dry_run:
        print(f"DRY RUN - would add {needed} codes to {actual_username}")
        return

    print("Type 'confirm' to proceed, or anything else to cancel:")
    confirmation = input("> ").strip().lower()
    if confirmation != "confirm":
        print("Cancelled.")
        sys.exit(0)

    print()
    existing_codes = get_existing_codes(cur)
    new_codes = create_codes(cur, owner, needed, existing_codes)
    print(f"Created {len(new_codes)} new codes")
    print()

    unused_codes = get_unused_codes(cur, owner)
    print_unused_codes(actual_username, unused_codes)


def replenish_all(conn, target: int, dry_run: bool) -> None:
    """Top up all users to the target number of unused codes."""
    print(f"Replenishing invite codes (target: {target} unused per user)")
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

    # Count UNUSED codes per user
    cur.execute(
        """
        SELECT LOWER(owner), COUNT(*) 
        FROM invite_codes 
        WHERE used_by IS NULL
        GROUP BY LOWER(owner)
        """
    )
    unused_per_user = {row[0]: row[1] for row in cur.fetchall()}

    # Calculate what needs to be done
    users_needing_codes = []
    total_to_create = 0
    for user in users:
        user_lower = user.lower()
        unused_count = unused_per_user.get(user_lower, 0)
        needed = target - unused_count
        if needed > 0:
            users_needing_codes.append((user, unused_count, needed))
            total_to_create += needed

    print()
    print("=" * 50)
    print(f"Users total: {len(users)}")
    print(f"Users needing codes: {len(users_needing_codes)}")
    print(f"Codes to create: {total_to_create}")
    print("=" * 50)

    if total_to_create == 0:
        print("\nAll users already have enough unused codes.")
        return

    if dry_run:
        print("\nDRY RUN - showing what would be created:\n")
        for user, unused, needed in users_needing_codes:
            print(f"  {user[:20]}... has {unused} unused, would add {needed}")
        print()
        print(f"Would create {total_to_create} codes for {len(users_needing_codes)} users")
        return

    print()
    print("This will create invite codes in the database.")
    print("Type 'confirm' to proceed, or anything else to cancel:")
    confirmation = input("> ").strip().lower()
    if confirmation != "confirm":
        print("Cancelled.")
        sys.exit(0)

    print()
    print("Creating codes...")
    total_created = 0

    for user, unused_count, needed in users_needing_codes:
        print(f"  {user[:20]}... has {unused_count} unused, adding {needed}")
        new_codes = create_codes(cur, user, needed, existing_codes)
        total_created += len(new_codes)

    print()
    print("=" * 50)
    print(f"Users updated: {len(users_needing_codes)}")
    print(f"Codes created: {total_created}")
    print("Done!")


def main():
    parser = argparse.ArgumentParser(description="Manage invite codes: replenish, add, or list")
    parser.add_argument(
        "--target",
        type=int,
        default=3,
        help="Target number of unused codes per user for replenish (default: 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes",
    )
    parser.add_argument(
        "--user",
        type=str,
        help="Username to operate on (without this, replenishes all users)",
    )
    parser.add_argument(
        "--add",
        type=int,
        metavar="N",
        help="Create N new codes for --user",
    )
    parser.add_argument(
        "--replenish",
        action="store_true",
        help="Top up --user to --target unused codes (like the global mode, but for one user)",
    )
    args = parser.parse_args()

    # Validate args
    if args.add and not args.user:
        print("Error: --user is required when using --add", file=sys.stderr)
        sys.exit(1)
    if args.add and args.add < 1:
        print("Error: --add must be at least 1", file=sys.stderr)
        sys.exit(1)
    if args.add and args.replenish:
        print("Error: --add and --replenish cannot be used together", file=sys.stderr)
        sys.exit(1)
    if args.replenish and not args.user:
        print("Error: --user is required when using --replenish", file=sys.stderr)
        sys.exit(1)
    if args.target < 1:
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

    if args.user and args.add:
        add_codes_to_user(conn, args.user, args.add, args.dry_run)
    elif args.user and args.replenish:
        replenish_user(conn, args.user, args.target, args.dry_run)
    elif args.user:
        list_codes_for_user(conn, args.user)
    else:
        replenish_all(conn, args.target, args.dry_run)

    conn.close()


if __name__ == "__main__":
    main()
