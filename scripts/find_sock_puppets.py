#!/usr/bin/env python3
"""
Sock Puppet Detection for a Single User.

Given a username or address, find the most similar accounts that could be
sock puppets (same person operating multiple accounts).

Uses entropy-weighted fingerprint comparison: individual attributes may be
common, but the COMBINATION is unique. Rare attribute matches count more
than common ones.

Example output:
    satoshi: 78% (screen_res: 8.4, canvas: 7.2, plugins: 6.1)
    Charlie: CRITICAL (IP: 10.0) + 45% preference similarity

Usage:
    python scripts/find_sock_puppets.py <username_or_address>
    python scripts/find_sock_puppets.py <username_or_address> --top 20
    python scripts/find_sock_puppets.py <username_or_address> --min-score 0.3
    python scripts/find_sock_puppets.py <username_or_address> --all
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

# Add project root to path for shared imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.fingerprint import (
    FingerprintData,
    FingerprintFrequency,
    FingerprintMatch,
    compare_all_fingerprints,
    format_match_summary,
    load_fingerprint_frequencies,
    load_fingerprints_from_db,
)

# =============================================================================
# CONFIGURATION
# =============================================================================

DB_URL = "postgresql://mirage:mirage@127.0.0.1:5432/mirage"
LOOKBACK_DAYS = 90

# Score thresholds
CRITICAL_FP_SCORE = 0.5  # Fingerprint score that triggers CRITICAL
HIGH_FP_SCORE = 0.3  # Fingerprint score that's notable


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class UserData:
    owner: str
    username: str
    level: int = 0
    created_at: int = 0

    posts: int = 0
    comments: int = 0
    upvotes_given: int = 0
    downvotes_given: int = 0
    votes_received_up: int = 0
    votes_received_down: int = 0

    first_action_ts: int = 0
    last_action_ts: int = 0
    active_days: int = 0
    active_day_set: Set[int] = field(default_factory=set)
    hour_histogram: List[int] = field(default_factory=lambda: [0] * 24)
    day_of_week_histogram: List[int] = field(default_factory=lambda: [0] * 7)

    topic_counts: Dict[str, int] = field(default_factory=dict)
    word_counts: Counter = field(default_factory=Counter)
    content_hashes: Set[str] = field(default_factory=set)
    total_words: int = 0

    @property
    def content_count(self) -> int:
        return self.posts + self.comments

    @property
    def age_days(self) -> float:
        DEFAULT_CREATED_AT = 1730419200
        if self.created_at > 0 and self.created_at != DEFAULT_CREATED_AT:
            ts = self.created_at
        elif self.first_action_ts > 0:
            ts = self.first_action_ts
        else:
            return 0.0
        now = int(time.time())
        return max(0.0, (now - ts) / 86400.0)


@dataclass
class SockPuppetMatch:
    """A potential sock puppet match."""

    target_user: str
    target_username: str
    match_user: str
    match_username: str

    # Fingerprint match (from shared module)
    fp_match: Optional[FingerprintMatch] = None

    # Preference similarity
    preference_sim: float = 0.0
    preference_shared: int = 0

    # Combined score
    total_score: float = 0.0

    # Flags for display
    flags: List[str] = field(default_factory=list)


# =============================================================================
# DATABASE
# =============================================================================


def connect():
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("psycopg not installed. Run: pip install 'psycopg[binary]'")
    return psycopg.connect(DB_URL, autocommit=True)


# =============================================================================
# DATA LOADING
# =============================================================================


def sanitize_input(s: str) -> str:
    """Remove invalid Unicode surrogate characters from input."""
    return s.encode("utf-8", errors="ignore").decode("utf-8")


def find_user_address(cur, username_or_address: str) -> Optional[Tuple[str, str]]:
    """Find user by username or address. Returns (address, username) or None."""
    input_lower = sanitize_input(username_or_address).lower().strip()

    # Try as address first
    cur.execute(
        "SELECT LOWER(owner), COALESCE(username, '') FROM profiles WHERE LOWER(owner) = %s",
        (input_lower,),
    )
    row = cur.fetchone()
    if row:
        return row[0], row[1] or row[0][:20]

    # Try as username
    cur.execute(
        "SELECT LOWER(owner), username FROM profiles WHERE LOWER(username) = %s",
        (input_lower,),
    )
    row = cur.fetchone()
    if row:
        return row[0], row[1]

    # Try partial match
    cur.execute(
        "SELECT LOWER(owner), username FROM profiles WHERE LOWER(username) LIKE %s LIMIT 1",
        (f"%{input_lower}%",),
    )
    row = cur.fetchone()
    if row:
        return row[0], row[1]

    return None


def load_all_users(cur, since_ts: int) -> Dict[str, UserData]:
    """Load all users with activity data."""
    # Load profiles
    cur.execute(
        """
        SELECT LOWER(owner), COALESCE(username, ''), COALESCE(level, 0), COALESCE(created_at, 0)
        FROM profiles
        """
    )
    users: Dict[str, UserData] = {}
    for owner, username, level, created_at in cur.fetchall():
        o = owner.strip().lower()
        if o:
            users[o] = UserData(owner=o, username=username or o[:20], level=level, created_at=created_at)

    # Load posts and build activity data
    cur.execute(
        """
        SELECT LOWER(owner), txhash, COALESCE(title, ''), COALESCE(content, ''),
               COALESCE(topic, ''), COALESCE(root_topic, ''), COALESCE(target, ''),
               created_at, COALESCE(deleted, FALSE)
        FROM posts
        WHERE created_at >= %s
        ORDER BY created_at DESC
        """,
        (since_ts,),
    )

    for row in cur.fetchall():
        owner, txhash, title, content, topic, root_topic, target, created_at, deleted = row
        o = owner.strip().lower()

        if o not in users:
            users[o] = UserData(owner=o, username=o[:20])

        if deleted:
            continue

        u = users[o]
        if target:
            u.comments += 1
        else:
            u.posts += 1

        if u.first_action_ts == 0 or created_at < u.first_action_ts:
            u.first_action_ts = created_at
        if created_at > u.last_action_ts:
            u.last_action_ts = created_at

        day = created_at // 86400
        u.active_day_set.add(day)

        dt = datetime.fromtimestamp(created_at, tz=timezone.utc)
        u.hour_histogram[dt.hour] += 1
        u.day_of_week_histogram[dt.weekday()] += 1

        t = (root_topic or topic or "").strip().lower()
        if t:
            u.topic_counts[t] = u.topic_counts.get(t, 0) + 1

        text = f"{title} {content}".strip()
        if text:
            words = re.findall(r"[a-z]+", text.lower())
            u.word_counts.update(words)
            u.total_words += len(words)
            if len(text) > 20:
                h = hashlib.md5(text.lower().encode()).hexdigest()[:16]
                u.content_hashes.add(h)

    # Finalize
    for u in users.values():
        u.active_days = len(u.active_day_set)

    return users


def load_user_preferences(cur, since_ts: int) -> Dict[str, Dict[str, float]]:
    """Load voting preferences for all users."""
    cur.execute(
        """
        SELECT LOWER(owner), pref_type || ':' || target, weight
        FROM preferences
        WHERE updated_at > %s
        """,
        (since_ts,),
    )

    user_prefs: Dict[str, Dict[str, float]] = defaultdict(dict)
    for owner, key, weight in cur.fetchall():
        user_prefs[owner][key] = weight

    return dict(user_prefs)


# =============================================================================
# SIMILARITY COMPUTATION
# =============================================================================


def compute_preference_similarity(prefs_a: Dict[str, float], prefs_b: Dict[str, float]) -> Tuple[float, int]:
    """
    Compute similarity based on voting preferences.
    Uses Pearson correlation on same-sign votes.
    Returns (similarity, shared_count).
    """
    shared_keys = set(prefs_a.keys()) & set(prefs_b.keys())

    # Only count same-sign preferences (both positive or both negative)
    same_sign_keys = []
    for k in shared_keys:
        wa, wb = prefs_a[k], prefs_b[k]
        if (wa > 0 and wb > 0) or (wa < 0 and wb < 0):
            same_sign_keys.append(k)

    n = len(same_sign_keys)
    if n < 5:  # Need at least 5 shared preferences
        return 0.0, n

    # Pearson correlation over same-sign preferences
    vals_a = [prefs_a[k] for k in same_sign_keys]
    vals_b = [prefs_b[k] for k in same_sign_keys]

    mean_a = sum(vals_a) / n
    mean_b = sum(vals_b) / n

    centered_a = [v - mean_a for v in vals_a]
    centered_b = [v - mean_b for v in vals_b]

    numerator = sum(a * b for a, b in zip(centered_a, centered_b))
    denom_a = math.sqrt(sum(a * a for a in centered_a))
    denom_b = math.sqrt(sum(b * b for b in centered_b))

    if denom_a == 0 or denom_b == 0:
        pearson = 1.0  # All values identical = perfect agreement
    else:
        pearson = numerator / (denom_a * denom_b)

    # Apply confidence factor (log scale, 30 shared = 1.0)
    confidence = math.log(n + 1) / math.log(31)
    similarity = min(1.0, max(0.0, pearson * confidence))

    return similarity, n


def compare_users(
    target: UserData,
    other: UserData,
    target_fps: List[FingerprintData],
    other_fps: List[FingerprintData],
    target_prefs: Dict[str, float],
    other_prefs: Dict[str, float],
    fp_freq: FingerprintFrequency,
) -> SockPuppetMatch:
    """Compare two users using fingerprints and preferences."""
    match = SockPuppetMatch(
        target_user=target.owner,
        target_username=target.username,
        match_user=other.owner,
        match_username=other.username,
    )

    # Fingerprint comparison using shared module
    if target_fps and other_fps:
        match.fp_match = compare_all_fingerprints(target_fps, other_fps, fp_freq)

        # Set flags based on fingerprint match
        if match.fp_match.score >= CRITICAL_FP_SCORE:
            match.flags.append(f"FP:{match.fp_match.score:.0%}")
            if match.fp_match.has_ip_match:
                match.flags.append("IP")
            if match.fp_match.has_canvas_match:
                match.flags.append("Canvas")

    # Preference similarity
    match.preference_sim, match.preference_shared = compute_preference_similarity(target_prefs, other_prefs)

    # Combined score: max of fingerprint score and preference similarity
    fp_score = match.fp_match.score if match.fp_match else 0.0
    match.total_score = max(fp_score, match.preference_sim)

    return match


# =============================================================================
# OUTPUT
# =============================================================================


def format_ts(ts: int) -> str:
    if ts <= 0:
        return "N/A"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def estimate_timezone(hour_histogram: List[int]) -> str:
    if sum(hour_histogram) < 5:
        return "Unknown"
    min_activity = float("inf")
    min_start = 0
    for start in range(24):
        window_sum = sum(hour_histogram[(start + h) % 24] for h in range(4))
        if window_sum < min_activity:
            min_activity = window_sum
            min_start = start
    offset = (3 - min_start) % 24
    if offset > 12:
        offset -= 24
    return f"UTC{offset:+d}"


def print_user_summary(user: UserData, fps: List[FingerprintData], fp_freq: FingerprintFrequency, label: str = ""):
    """Print a summary of a user."""
    print(f"\n{'=' * 60}")
    if label:
        print(f"{label}: {user.username}")
    else:
        print(f"User: {user.username}")
    print("=" * 60)
    print(f"Address: {user.owner}")
    print(f"Level: {user.level}")
    print(f"Account age: {user.age_days:.1f} days")
    print(f"Posts: {user.posts}, Comments: {user.comments}")
    print(f"Active days: {user.active_days}")
    print(f"First action: {format_ts(user.first_action_ts)}")
    print(f"Last action: {format_ts(user.last_action_ts)}")
    print(f"Timezone: {estimate_timezone(user.hour_histogram)}")

    if user.topic_counts:
        top_topics = sorted(user.topic_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        topics_str = ", ".join(f"#{t}({c})" for t, c in top_topics)
        print(f"Top topics: {topics_str}")

    if fps:
        print(f"\nFingerprints on file: {len(fps)}")
        unique_ips = len({fp.ip_hash for fp in fps if fp.ip_hash})
        unique_canvas = len({fp.canvas_hash for fp in fps if fp.canvas_hash})
        print(f"Unique IPs: {unique_ips}, Unique canvas: {unique_canvas}")

        # Count attributes for first fingerprint
        if fps[0].attributes:
            attr_count = len(fps[0].attributes)
            print(f"Extended attributes: {attr_count} categories")


def print_match(match: SockPuppetMatch, verbose: bool = False):
    """Print match with entropy-weighted fingerprint details."""
    fp = match.fp_match
    pref_sim = match.preference_sim
    pref_shared = match.preference_shared

    parts = []

    # Fingerprint score
    if fp and fp.score >= HIGH_FP_SCORE:
        # Format: "78% (screen_res: 8.4, canvas: 7.2)"
        fp_summary = format_match_summary(fp, max_attrs=3)
        if fp.score >= CRITICAL_FP_SCORE:
            parts.append(f"CRITICAL {fp_summary}")
        else:
            parts.append(f"FP: {fp_summary}")

    # Preference similarity
    if pref_sim > 0 and pref_shared > 0:
        parts.append(f"Pref: {pref_sim:.0%} ({pref_shared} shared)")

    if parts:
        print(f"{match.match_username}: {' + '.join(parts)}")
    else:
        print(f"{match.match_username}: {match.total_score:.0%}")

    # Verbose: show top fingerprint matches
    if verbose and fp and fp.matches:
        for attr, weight in fp.top_matches(5):
            rarity = "RARE" if weight >= 6 else "uncommon" if weight >= 4 else "common"
            print(f"    {attr}: {weight:.1f} ({rarity})")


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Find potential sock puppet accounts for a given user")
    parser.add_argument("username", help="Username or address to analyze")
    parser.add_argument("--top", "-n", type=int, default=15, help="Number of top matches to show (default: 15)")
    parser.add_argument("--min-score", "-m", type=float, default=0.15, help="Minimum score to show (default: 0.15)")
    parser.add_argument("--all", "-a", action="store_true", help="Show all matches above threshold")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed fingerprint breakdown")
    args = parser.parse_args()

    print("=" * 60)
    print("Sock Puppet Detection (Entropy-Weighted Fingerprinting)")
    print("=" * 60)

    now_ts = int(time.time())
    since_ts = now_ts - LOOKBACK_DAYS * 86400

    with connect() as conn:
        with conn.cursor() as cur:
            # Find target user
            result = find_user_address(cur, args.username)
            if not result:
                print(f"User '{args.username}' not found.")
                return

            target_addr, target_username = result
            print(f"Target: {target_username} ({target_addr})")

            # Load all data
            print("\nLoading data...")
            users = load_all_users(cur, since_ts)
            all_prefs = load_user_preferences(cur, since_ts)
            print(f"Loaded {len(users)} users, {len(all_prefs)} with preferences")

            # Load fingerprints using shared module
            print("Loading fingerprints...")
            all_fingerprints = load_fingerprints_from_db(cur)
            print(f"Loaded fingerprints for {len(all_fingerprints)} users")

            # Calculate fingerprint frequencies
            print("Calculating attribute frequencies...")
            fp_freq = load_fingerprint_frequencies(cur)
            print(f"Total users with fingerprints: {fp_freq.total_users}")
            print(f"Tracked attributes: {len(fp_freq.counts)}")

            # Get target user data
            target_user = users.get(target_addr)
            if not target_user:
                target_user = UserData(owner=target_addr, username=target_username)
            target_fps = all_fingerprints.get(target_addr, [])
            target_prefs = all_prefs.get(target_addr, {})

            if not target_prefs:
                print(f"Warning: No preference data for {target_username}")

            # Print target user summary
            print_user_summary(target_user, target_fps, fp_freq, "TARGET")

            # Compare against all other users
            print("\nComparing against all users...")
            matches: List[Tuple[SockPuppetMatch, UserData]] = []

            # Compare with users who have preferences OR fingerprints
            users_to_compare = set(all_prefs.keys()) | set(all_fingerprints.keys())
            users_to_compare.discard(target_addr)

            for other_addr in users_to_compare:
                other_user = users.get(other_addr)
                if not other_user:
                    other_user = UserData(owner=other_addr, username=other_addr[:20])

                other_fps = all_fingerprints.get(other_addr, [])
                other_prefs = all_prefs.get(other_addr, {})

                match = compare_users(
                    target_user, other_user,
                    target_fps, other_fps,
                    target_prefs, other_prefs,
                    fp_freq
                )

                if match.total_score >= args.min_score:
                    matches.append((match, other_user))

            # Sort by score
            matches.sort(key=lambda x: x[0].total_score, reverse=True)

            # Limit results
            if not args.all:
                matches = matches[: args.top]

            # Print results
            if not matches:
                print("\nNo potential sock puppets found above the threshold.")
                return

            print(f"\nSimilar users ({len(matches)} matches):")
            for match, other_user in matches:
                print_match(match, verbose=args.verbose)


if __name__ == "__main__":
    main()
