#!/usr/bin/env python3
"""
Batch AI Account Review - Sockpuppet Detection.

Reads a list of usernames/addresses from a txt file, compiles unbiased factual
evidence for each target (activity, fingerprints, preferences, referrals) by
comparing against ALL accounts in the database, then uses ChatGPT to produce
a final verdict with clear reasoning.

Key features:
- Entropy-weighted fingerprint combo matching (rare attribute combos count more)
- Preference similarity (Pearson correlation on voting patterns)
- CRITICAL alerts for same IP / same canvas hash
- Unbiased factual reports (no accusations baked in)
- ChatGPT produces final verdict citing concrete evidence

Usage:
    python scripts/review_accounts_ai.py --input accounts.txt
    python scripts/review_accounts_ai.py --input accounts.txt --output-dir /tmp/review
    python scripts/review_accounts_ai.py --input accounts.txt --lookback-days 60
"""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Add project root to path for shared imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.fingerprint import (
    FingerprintData,
    FingerprintFrequency,
    FingerprintMatch,
    compare_all_fingerprints,
    format_match_summary,
    format_match_table,
    load_fingerprint_frequencies,
    load_fingerprints_from_db,
)

# =============================================================================
# CONFIGURATION
# =============================================================================

DB_URL = os.environ.get("DATABASE_URL", "postgresql://mirage:mirage@127.0.0.1:5432/mirage")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "user-analysis")
LOOKBACK_DAYS = 90

# Evidence detail levels
MAX_RECENT_POSTS_TARGET_FILE = 50
MAX_RECENT_POSTS_TARGET_AI = 12
MAX_RECENT_POSTS_MATCH_FILE = 5
MAX_MATCHES_WITH_POST_SAMPLES = 5  # per severity bucket (CRITICAL/HIGH)

# ChatGPT API key - will be prompted if not in environment
CHATGPT_API_KEY = os.environ.get("CHATGPT_API_KEY", "")

# Severity thresholds for categorization (display only, no filtering)
# IMPORTANT: We treat device/fingerprint signals as primary for sockpuppet detection.
# Preference similarity alone can be high for real users (shared community tastes),
# so it is shown as evidence but does NOT drive severity categories.
CRITICAL_FP_SCORE = 0.5  # Fingerprint combo score
HIGH_FP_SCORE = 0.3
CRITICAL_PREF_SIM = 0.7
HIGH_PREF_SIM = 0.5

# Minimum scores to include in output (very low - we want everything notable)
MIN_FP_SCORE_TO_SHOW = 0.1
MIN_PREF_SIM_TO_SHOW = 0.1

# Display thresholds for the "Other Notable Matches" section.
# We keep matching broad, but we only *display* notables when there is meaningful fingerprint overlap.
MIN_FP_SCORE_TO_DISPLAY_NOTABLE = 0.15
MIN_FP_WEIGHT_TO_DISPLAY_NOTABLE = 8.0


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class UserData:
    """User profile and activity data."""

    owner: str
    username: str
    level: int = 0
    created_at: int = 0

    # Content stats
    posts: int = 0
    comments: int = 0
    upvotes_given: int = 0
    downvotes_given: int = 0
    votes_received_up: int = 0
    votes_received_down: int = 0

    # Temporal
    first_action_ts: int = 0
    last_action_ts: int = 0
    active_days: int = 0
    active_day_set: Set[int] = field(default_factory=set)
    hour_histogram: List[int] = field(default_factory=lambda: [0] * 24)
    day_of_week_histogram: List[int] = field(default_factory=lambda: [0] * 7)

    # Topics
    topic_counts: Dict[str, int] = field(default_factory=dict)

    # Content analysis
    word_counts: Counter = field(default_factory=Counter)
    total_words: int = 0

    # Network
    reply_targets: Dict[str, int] = field(default_factory=dict)
    reply_sources: Dict[str, int] = field(default_factory=dict)
    vote_targets: Dict[str, int] = field(default_factory=dict)

    @property
    def content_count(self) -> int:
        return self.posts + self.comments

    @property
    def age_days(self) -> float:
        DEFAULT_CREATED_AT = 1730419200  # Chain init default
        if self.created_at > 0 and self.created_at != DEFAULT_CREATED_AT:
            ts = self.created_at
        elif self.first_action_ts > 0:
            ts = self.first_action_ts
        else:
            return 0.0
        now = int(time.time())
        return max(0.0, (now - ts) / 86400.0)


@dataclass
class AccountMatch:
    """A match between target and another account."""

    target_addr: str
    target_username: str
    match_addr: str
    match_username: str

    # Fingerprint match
    fp_match: Optional[FingerprintMatch] = None
    fp_score: float = 0.0

    # Preference similarity
    pref_sim: float = 0.0
    pref_shared: int = 0

    # Direct matches (CRITICAL signals)
    same_ip: bool = False
    same_canvas: bool = False

    # Severity category
    severity: str = "NOTABLE"  # CRITICAL, HIGH, NOTABLE

    def compute_severity(self):
        """Determine severity based on signals."""
        # Direct device signals
        if self.same_ip or self.same_canvas:
            self.severity = "CRITICAL"
        # Strong fingerprint combo match
        elif self.fp_score >= CRITICAL_FP_SCORE:
            self.severity = "CRITICAL"
        # High fingerprint combo match *with* at least one high-entropy attribute match
        # (prevents labeling broad/common matches as HIGH severity)
        elif self.fp_score >= HIGH_FP_SCORE and self.fp_match and self.fp_match.has_device_match:
            self.severity = "HIGH"
        else:
            self.severity = "NOTABLE"


@dataclass
class TargetEvidence:
    """Complete evidence bundle for a target account."""

    address: str
    username: str
    user_data: Optional[UserData] = None
    fingerprints: List[FingerprintData] = field(default_factory=list)

    # Referral context
    referrer_addr: Optional[str] = None
    referrer_username: Optional[str] = None
    referee_count: int = 0
    pending_reward: float = 0.0

    # All matches found
    matches: List[AccountMatch] = field(default_factory=list)

    # Recent posts (unbiased facts) for the target and select matches
    recent_posts: List[Dict[str, Any]] = field(default_factory=list)
    match_recent_posts: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    # AI verdict (filled after ChatGPT call)
    verdict: str = ""
    confidence: str = ""
    recommendation: str = ""
    reasoning: str = ""
    likely_real_anchor: str = ""


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
# INPUT PARSING
# =============================================================================


def sanitize_input(s: str) -> str:
    """Remove invalid Unicode surrogate characters from input."""
    return s.encode("utf-8", errors="ignore").decode("utf-8")


def parse_input_file(filepath: str) -> List[str]:
    """Parse input file, returning list of identifiers (usernames or addresses).

    Supports:
    - One identifier per line
    - Blank lines (ignored)
    - Comments starting with # (ignored)
    - Inline comments after identifier
    """
    identifiers = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip blank lines and full-line comments
            if not line or line.startswith("#"):
                continue
            # Handle inline comments
            if "#" in line:
                line = line.split("#")[0].strip()
            if line:
                identifiers.append(sanitize_input(line))
    return identifiers


def resolve_identifier(cur, identifier: str) -> Optional[Tuple[str, str]]:
    """Resolve username or address to (address, username). Returns None if not found."""
    input_lower = identifier.lower().strip()

    # Try as address first (starts with mirage1)
    if input_lower.startswith("mirage1"):
        cur.execute(
            "SELECT LOWER(owner), COALESCE(username, '') FROM profiles WHERE LOWER(owner) = %s",
            (input_lower,),
        )
        row = cur.fetchone()
        if row:
            return row[0], row[1] or row[0][:20]

    # Try as exact username match
    cur.execute(
        "SELECT LOWER(owner), username FROM profiles WHERE LOWER(username) = %s",
        (input_lower,),
    )
    row = cur.fetchone()
    if row:
        return row[0], row[1]

    # Try as address (if it wasn't mirage1 prefixed, maybe partial)
    cur.execute(
        "SELECT LOWER(owner), COALESCE(username, '') FROM profiles WHERE LOWER(owner) = %s",
        (input_lower,),
    )
    row = cur.fetchone()
    if row:
        return row[0], row[1] or row[0][:20]

    return None


# =============================================================================
# DATA LOADING
# =============================================================================


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
            users[o] = UserData(
                owner=o,
                username=username or o[:20],
                level=level,
                created_at=created_at,
            )

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

    posts_by_hash: Dict[str, Dict] = {}

    for row in cur.fetchall():
        owner, txhash, title, content, topic, root_topic, target, created_at, deleted = row
        o = owner.strip().lower()

        posts_by_hash[txhash.lower()] = {"owner": o, "target": target}

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

    # Track reply targets
    for txhash, post_data in posts_by_hash.items():
        target = post_data.get("target")
        if target:
            target_lower = target.lower()
            if target_lower in posts_by_hash:
                replier = post_data["owner"]
                target_owner = posts_by_hash[target_lower]["owner"]
                if replier in users and target_owner != replier:
                    users[replier].reply_targets[target_owner] = users[replier].reply_targets.get(target_owner, 0) + 1

    # Load votes
    cur.execute(
        """
        SELECT LOWER(v.owner), LOWER(p.owner), v.user_vote, v.created_at
        FROM votes v
        JOIN posts p ON LOWER(v.target) = LOWER(p.txhash)
        WHERE v.created_at >= %s
        """,
        (since_ts,),
    )

    for voter, post_owner, weight, vote_ts in cur.fetchall():
        v = voter.strip().lower()
        po = post_owner.strip().lower()

        if v not in users:
            users[v] = UserData(owner=v, username=v[:20])

        u = users[v]
        if weight > 0:
            u.upvotes_given += 1
        else:
            u.downvotes_given += 1

        if po != v:
            u.vote_targets[po] = u.vote_targets.get(po, 0) + 1

        vote_day = vote_ts // 86400
        u.active_day_set.add(vote_day)

        if u.first_action_ts == 0 or vote_ts < u.first_action_ts:
            u.first_action_ts = vote_ts
        if vote_ts > u.last_action_ts:
            u.last_action_ts = vote_ts

        dt = datetime.fromtimestamp(vote_ts, tz=timezone.utc)
        u.hour_histogram[dt.hour] += 1
        u.day_of_week_histogram[dt.weekday()] += 1

        if po in users:
            if weight > 0:
                users[po].votes_received_up += 1
            else:
                users[po].votes_received_down += 1

    # Finalize
    for u in users.values():
        u.active_days = len(u.active_day_set)

    return users


def load_all_preferences(cur) -> Dict[str, Dict[str, float]]:
    """Load voting preferences for all users."""
    cur.execute(
        """
        SELECT LOWER(owner), pref_type || ':' || target, weight
        FROM preferences
        WHERE weight != 0
        """
    )

    user_prefs: Dict[str, Dict[str, float]] = defaultdict(dict)
    for owner, key, weight in cur.fetchall():
        user_prefs[owner][key] = weight

    return dict(user_prefs)


def load_referral_context(cur) -> Tuple[Dict[str, Tuple[str, int]], Dict[str, int], Dict[str, float]]:
    """Load referral links, referee counts, and pending rewards.

    Returns:
        - referral_links: {referee_addr: (referrer_addr, referred_at)}
        - referee_counts: {referrer_addr: count}
        - pending_by_referee: {referee_addr: pending_amount}
    """
    # Load referral links
    cur.execute("SELECT LOWER(user_address), LOWER(referrer_address), referred_at FROM referral_links")
    referral_links = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    # Count referees per referrer
    referee_counts: Dict[str, int] = defaultdict(int)
    for referee, (referrer, _) in referral_links.items():
        referee_counts[referrer] += 1

    # Load pending rewards by referee
    cur.execute(
        """
        SELECT LOWER(referee_address), SUM(pending)
        FROM referral_user_accruals
        WHERE pending > 0
        GROUP BY LOWER(referee_address)
        """
    )
    pending_by_referee = {row[0]: float(row[1]) for row in cur.fetchall()}

    return referral_links, dict(referee_counts), pending_by_referee


def load_recent_posts_for_addresses(
    cur,
    owners: List[str],
    since_ts: int,
    max_posts_per_user: int,
) -> Dict[str, List[Dict[str, Any]]]:
    """Load recent posts/comments for a list of owners (lowercased addresses).

    Returns {owner: [post_dict, ...]} ordered newest-first per owner.
    Includes per-post upvote/downvote counts within the lookback window.
    """
    owners = [o.lower() for o in owners if o]
    owners = list(dict.fromkeys(owners))  # dedupe, stable
    if not owners:
        return {}

    cur.execute(
        """
        SELECT LOWER(owner), LOWER(txhash), COALESCE(title, ''), COALESCE(content, ''),
               COALESCE(topic, ''), COALESCE(root_topic, ''), COALESCE(target, ''),
               created_at, COALESCE(deleted, FALSE)
        FROM posts
        WHERE created_at >= %s AND LOWER(owner) = ANY(%s)
        ORDER BY created_at DESC
        """,
        (since_ts, owners),
    )

    posts_by_user: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    posts_by_hash: Dict[str, Dict[str, Any]] = {}

    for row in cur.fetchall():
        owner, txhash, title, content, topic, root_topic, target, created_at, deleted = row
        if deleted:
            continue
        p = {
            "owner": owner,
            "txhash": txhash,
            "title": title,
            "content": content,
            "topic": (root_topic or topic or "").strip(),
            "target": target or "",
            "created_at": int(created_at or 0),
            "upvotes": 0,
            "downvotes": 0,
            "parent_owner": "",
        }
        posts_by_hash[txhash] = p
        if len(posts_by_user[owner]) < max_posts_per_user:
            posts_by_user[owner].append(p)

    # Load parent owners for comments (to provide unbiased context)
    target_hashes = [p["target"].lower() for p in posts_by_hash.values() if p.get("target")]
    target_hashes = list(dict.fromkeys([h for h in target_hashes if h]))
    if target_hashes:
        cur.execute(
            """
            SELECT LOWER(txhash), LOWER(owner)
            FROM posts
            WHERE LOWER(txhash) = ANY(%s)
            """,
            (target_hashes,),
        )
        parent_owner_by_hash = {row[0]: row[1] for row in cur.fetchall()}
        for p in posts_by_hash.values():
            tgt = (p.get("target") or "").lower()
            if tgt:
                p["parent_owner"] = parent_owner_by_hash.get(tgt, "")

    # Vote counts for these posts (within the lookback window)
    txhashes = list(posts_by_hash.keys())
    if txhashes:
        cur.execute(
            """
            SELECT LOWER(target),
                   SUM(CASE WHEN user_vote > 0 THEN 1 ELSE 0 END) AS upvotes,
                   SUM(CASE WHEN user_vote < 0 THEN 1 ELSE 0 END) AS downvotes
            FROM votes
            WHERE created_at >= %s AND LOWER(target) = ANY(%s)
            GROUP BY LOWER(target)
            """,
            (since_ts, txhashes),
        )
        for target, up, down in cur.fetchall():
            if target in posts_by_hash:
                posts_by_hash[target]["upvotes"] = int(up or 0)
                posts_by_hash[target]["downvotes"] = int(down or 0)

    return dict(posts_by_user)


def augment_evidence_with_recent_posts(
    cur,
    evidence: TargetEvidence,
    since_ts: int,
) -> None:
    """Attach recent posts for the target and a small sample for CRITICAL/HIGH matches."""
    # Target posts
    owners: List[str] = [evidence.address]

    critical_addrs = [m.match_addr for m in evidence.matches if m.severity == "CRITICAL"][
        :MAX_MATCHES_WITH_POST_SAMPLES
    ]
    high_addrs = [m.match_addr for m in evidence.matches if m.severity == "HIGH"][:MAX_MATCHES_WITH_POST_SAMPLES]

    owners.extend(critical_addrs)
    owners.extend(high_addrs)

    posts = load_recent_posts_for_addresses(
        cur=cur,
        owners=owners,
        since_ts=since_ts,
        max_posts_per_user=max(MAX_RECENT_POSTS_TARGET_FILE, MAX_RECENT_POSTS_MATCH_FILE),
    )

    evidence.recent_posts = posts.get(evidence.address.lower(), [])[:MAX_RECENT_POSTS_TARGET_FILE]

    for addr in critical_addrs + high_addrs:
        evidence.match_recent_posts[addr.lower()] = posts.get(addr.lower(), [])[:MAX_RECENT_POSTS_MATCH_FILE]


# =============================================================================
# SIMILARITY COMPUTATION
# =============================================================================


def compute_preference_similarity(prefs_a: Dict[str, float], prefs_b: Dict[str, float]) -> Tuple[float, int]:
    """
    Compute Pearson correlation on same-sign preferences.
    Returns (similarity, shared_count).

    Same algorithm as web/backend/similarity.py and scripts/classify_users.py.
    """
    MIN_SHARED = 5
    CONFIDENCE_REFERENCE = 31  # log(31) gives 1.0 at 30 shared dims

    if not prefs_a or not prefs_b:
        return 0.0, 0

    shared_keys = set(prefs_a.keys()) & set(prefs_b.keys())

    # Only use keys where both users have same-sign preferences
    same_sign_keys = []
    for k in shared_keys:
        wa, wb = prefs_a[k], prefs_b[k]
        if (wa > 0 and wb > 0) or (wa < 0 and wb < 0):
            same_sign_keys.append(k)

    n = len(same_sign_keys)
    if n < MIN_SHARED:
        return 0.0, n

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
        pearson = 1.0  # Perfect correlation if no variance
    else:
        pearson = numerator / (denom_a * denom_b)

    # Logarithmic confidence factor
    confidence = math.log(n + 1) / math.log(CONFIDENCE_REFERENCE)

    # Final similarity (capped at 1.0)
    return min(1.0, max(0.0, pearson * confidence)), n


def find_direct_matches(
    target_fps: List[FingerprintData],
    other_fps: List[FingerprintData],
) -> Tuple[bool, bool]:
    """Check for direct IP and canvas hash matches between two users.

    Returns (same_ip, same_canvas).
    """
    target_ips = {fp.ip_hash for fp in target_fps if fp.ip_hash}
    target_canvas = {fp.canvas_hash for fp in target_fps if fp.canvas_hash}

    other_ips = {fp.ip_hash for fp in other_fps if fp.ip_hash}
    other_canvas = {fp.canvas_hash for fp in other_fps if fp.canvas_hash}

    same_ip = bool(target_ips & other_ips)
    same_canvas = bool(target_canvas & other_canvas)

    return same_ip, same_canvas


def compare_all_users(
    target_addr: str,
    target_username: str,
    target_fps: List[FingerprintData],
    target_prefs: Dict[str, float],
    all_users: Dict[str, UserData],
    all_fps: Dict[str, List[FingerprintData]],
    all_prefs: Dict[str, Dict[str, float]],
    fp_freq: FingerprintFrequency,
) -> List[AccountMatch]:
    """Compare target against ALL other users, return all notable matches."""
    matches = []

    for other_addr, other_user in all_users.items():
        if other_addr == target_addr:
            continue

        other_fps_list = all_fps.get(other_addr, [])
        other_prefs = all_prefs.get(other_addr, {})

        # Compute fingerprint match
        fp_match = None
        fp_score = 0.0
        same_ip = False
        same_canvas = False

        if target_fps and other_fps_list:
            fp_match = compare_all_fingerprints(target_fps, other_fps_list, fp_freq)
            fp_score = fp_match.score
            same_ip, same_canvas = find_direct_matches(target_fps, other_fps_list)

        # Compute preference similarity
        pref_sim, pref_shared = compute_preference_similarity(target_prefs, other_prefs)

        # Decide if this match is notable enough to include
        is_notable = same_ip or same_canvas or fp_score >= MIN_FP_SCORE_TO_SHOW or pref_sim >= MIN_PREF_SIM_TO_SHOW

        if is_notable:
            match = AccountMatch(
                target_addr=target_addr,
                target_username=target_username,
                match_addr=other_addr,
                match_username=other_user.username,
                fp_match=fp_match,
                fp_score=fp_score,
                pref_sim=pref_sim,
                pref_shared=pref_shared,
                same_ip=same_ip,
                same_canvas=same_canvas,
            )
            match.compute_severity()
            matches.append(match)

    # Sort by severity then by fp_score + pref_sim
    severity_order = {"CRITICAL": 0, "HIGH": 1, "NOTABLE": 2}
    matches.sort(key=lambda m: (severity_order[m.severity], -(m.fp_score + m.pref_sim)))

    return matches


# =============================================================================
# EVIDENCE GENERATION
# =============================================================================


def format_ts(ts: int) -> str:
    """Format timestamp for display."""
    if ts <= 0:
        return "N/A"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def format_date(ts: int) -> str:
    """Format timestamp as date only."""
    if ts <= 0:
        return "N/A"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def estimate_timezone_from_activity(hour_histogram: List[int]) -> str:
    """Estimate timezone from activity pattern (fallback only)."""
    if sum(hour_histogram) < 5:
        return "Unknown (insufficient data)"
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
    return f"UTC{offset:+d} (estimated)"


def get_timezone_from_fingerprints(fps: List[FingerprintData]) -> Optional[str]:
    """Get real timezone from fingerprint data."""
    for fp in fps:
        if fp.timezone:
            # Return named timezone (e.g., "America/Los_Angeles")
            return fp.timezone
        if fp.timezone_offset is not None:
            # Convert offset in minutes to hours
            hours = -fp.timezone_offset // 60  # Offset is inverted (UTC-7 = +420)
            return f"UTC{hours:+d}"
    return None


def get_user_timezone(fps: List[FingerprintData], hour_histogram: List[int]) -> str:
    """Get timezone: prefer real fingerprint data, fallback to estimation."""
    real_tz = get_timezone_from_fingerprints(fps)
    if real_tz:
        return real_tz
    return estimate_timezone_from_activity(hour_histogram)


def build_target_evidence(
    addr: str,
    username: str,
    users: Dict[str, UserData],
    all_fps: Dict[str, List[FingerprintData]],
    all_prefs: Dict[str, Dict[str, float]],
    fp_freq: FingerprintFrequency,
    referral_links: Dict[str, Tuple[str, int]],
    referee_counts: Dict[str, int],
    pending_by_referee: Dict[str, float],
) -> TargetEvidence:
    """Build complete evidence bundle for a target."""
    evidence = TargetEvidence(address=addr, username=username)

    # User data
    evidence.user_data = users.get(addr)
    evidence.fingerprints = all_fps.get(addr, [])

    # Referral context
    if addr in referral_links:
        referrer_addr, _ = referral_links[addr]
        evidence.referrer_addr = referrer_addr
        referrer_user = users.get(referrer_addr)
        evidence.referrer_username = referrer_user.username if referrer_user else referrer_addr[:20]

    evidence.referee_count = referee_counts.get(addr, 0)
    evidence.pending_reward = pending_by_referee.get(addr, 0.0)

    # Find all matches
    target_prefs = all_prefs.get(addr, {})

    evidence.matches = compare_all_users(
        addr,
        username,
        evidence.fingerprints,
        target_prefs,
        users,
        all_fps,
        all_prefs,
        fp_freq,
    )

    return evidence


# =============================================================================
# MARKDOWN GENERATION
# =============================================================================


def generate_evidence_markdown(
    evidence: TargetEvidence,
    users: Dict[str, UserData],
    all_fps: Dict[str, List[FingerprintData]],
) -> str:
    """Generate markdown report for a single target."""
    lines = []

    lines.append(f"# Account Analysis: {evidence.username}")
    lines.append("")
    lines.append(f"**Generated**: {format_ts(int(time.time()))}")
    lines.append("")

    # Identity
    lines.append("## Identity")
    lines.append("")
    lines.append(f"| Field | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| Username | `{evidence.username}` |")
    lines.append(f"| Address | `{evidence.address}` |")

    if evidence.user_data:
        u = evidence.user_data
        lines.append(f"| Level | {u.level} |")
        lines.append(f"| Account Age | {u.age_days:.1f} days |")
    lines.append("")

    # Activity Summary
    if evidence.user_data:
        u = evidence.user_data
        lines.append("## Activity Summary")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Posts | {u.posts} |")
        lines.append(f"| Comments | {u.comments} |")
        lines.append(f"| Total Content | {u.content_count} |")
        lines.append(f"| Active Days | {u.active_days} |")
        lines.append(f"| Upvotes Given | {u.upvotes_given} |")
        lines.append(f"| Downvotes Given | {u.downvotes_given} |")
        lines.append(f"| Upvotes Received | {u.votes_received_up} |")
        lines.append(f"| Downvotes Received | {u.votes_received_down} |")
        lines.append(f"| First Action | {format_ts(u.first_action_ts)} |")
        lines.append(f"| Last Action | {format_ts(u.last_action_ts)} |")
        lines.append(f"| Unique Topics | {len(u.topic_counts)} |")
        lines.append(f"| Timezone | {get_user_timezone(evidence.fingerprints, u.hour_histogram)} |")
        lines.append("")

        # Topics
        if u.topic_counts:
            lines.append("### Topics")
            lines.append("")
            lines.append("| Topic | Posts |")
            lines.append("|-------|-------|")
            for topic, count in sorted(u.topic_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
                lines.append(f"| #{topic} | {count} |")
            lines.append("")

        # Hour histogram
        lines.append("### Hourly Activity (UTC)")
        lines.append("")
        lines.append("```")
        total_hourly = sum(u.hour_histogram)
        max_hourly = max(u.hour_histogram) if u.hour_histogram else 1
        for hour in range(24):
            count = u.hour_histogram[hour]
            pct = (count / total_hourly * 100) if total_hourly > 0 else 0
            bar = "█" * int(20 * count / max(1, max_hourly))
            lines.append(f"{hour:02d}:00  {bar} {count} ({pct:.0f}%)")
        lines.append("```")
        lines.append("")

    # Fingerprints
    lines.append("## Fingerprint Data")
    lines.append("")
    if evidence.fingerprints:
        lines.append(f"Fingerprints on file: {len(evidence.fingerprints)}")
        lines.append("")
        lines.append("| # | First Seen | Last Seen | Count | IP Hash | Screen | Canvas | Timezone |")
        lines.append("|---|------------|-----------|-------|---------|--------|--------|----------|")
        for i, fp in enumerate(evidence.fingerprints, 1):
            first = format_date(fp.first_seen) if fp.first_seen else "-"
            last = format_date(fp.last_seen) if fp.last_seen else "-"
            screen = f"{fp.screen_width}x{fp.screen_height}" if fp.screen_width and fp.screen_height else "-"
            canvas = (fp.canvas_hash[:8] + "...") if fp.canvas_hash else "-"
            ip = (fp.ip_hash[:8] + "...") if fp.ip_hash else "-"
            tz = fp.timezone or "-"
            lines.append(f"| {i} | {first} | {last} | {fp.seen_count} | {ip} | {screen} | {canvas} | {tz} |")
        lines.append("")
    else:
        lines.append("*No fingerprint data available.*")
        lines.append("")

    # Referral Context
    lines.append("## Referral Context")
    lines.append("")
    if evidence.referrer_addr:
        lines.append(f"- **Referrer**: `{evidence.referrer_username}` (`{evidence.referrer_addr}`)")
    else:
        lines.append("- **Referrer**: None (organic signup)")

    if evidence.referee_count > 0:
        lines.append(f"- **Referees**: {evidence.referee_count} accounts referred by this user")

    if evidence.pending_reward > 0:
        lines.append(f"- **Pending Reward**: {evidence.pending_reward:.6f} MIRAGE")
    lines.append("")

    # Matches
    lines.append("## Similar Accounts Found")
    lines.append("")

    if not evidence.matches:
        lines.append("*No notable matches found.*")
        lines.append("")
    else:
        # Group by severity
        critical = [m for m in evidence.matches if m.severity == "CRITICAL"]
        high = [m for m in evidence.matches if m.severity == "HIGH"]
        notable = [m for m in evidence.matches if m.severity == "NOTABLE"]
        pref_similar = [m for m in evidence.matches if m.pref_sim >= HIGH_PREF_SIM]

        if critical:
            lines.append("### CRITICAL Matches")
            lines.append("")
            lines.append("These accounts share strong device/fingerprint signals with the target.")
            lines.append("")
            for m in critical:
                lines.append(f"#### {m.match_username} (`{m.match_addr}`)")
                lines.append("")
                flags = []
                if m.same_ip:
                    flags.append("**SAME IP**")
                if m.same_canvas:
                    flags.append("**SAME CANVAS**")
                if m.fp_score >= CRITICAL_FP_SCORE:
                    flags.append(f"FP: {m.fp_score:.0%}")
                if m.pref_sim >= CRITICAL_PREF_SIM:
                    flags.append(f"Pref: {m.pref_sim:.0%} ({m.pref_shared} shared)")

                lines.append(f"**Signals**: {', '.join(flags)}")
                lines.append("")

                # Fingerprint interpretation (unbiased facts)
                # Note: match.score is a completeness ratio (matched_weight / possible_weight) for this pair.
                # The absolute weight indicates how much entropy/rarity the match carries overall.
                if m.fp_match:
                    high_entropy = "yes" if m.fp_match.has_device_match else "no"
                    lines.append(
                        f"**Fingerprint (facts)**: score={m.fp_match.score:.0%} "
                        f"(completeness), weight={m.fp_match.total_weight:.1f}/{m.fp_match.max_possible_weight:.1f} "
                        f"(entropy-weight sum), has_high_entropy_attr={high_entropy}"
                    )
                    lines.append(
                        "_Interpretation_: 100% score means all compared attributes matched; "
                        "if individual attributes are common, the match is less unique unless the total weight is high "
                        "or there are direct matches like canvas hash."
                    )
                    lines.append("")

                # Fingerprint breakdown
                if m.fp_match and m.fp_match.matches:
                    lines.extend(format_match_table(m.fp_match))
                    lines.append("")

                # Recent posts sample for this match (unbiased facts)
                match_posts = evidence.match_recent_posts.get(m.match_addr.lower(), [])
                if match_posts:
                    lines.append("**Recent Posts (sample)**")
                    lines.append("")
                    for i, p in enumerate(match_posts, 1):
                        ts = format_ts(p.get("created_at", 0))
                        topic = p.get("topic") or "none"
                        votes = f"+{p.get('upvotes', 0)}/-{p.get('downvotes', 0)}"
                        is_comment = bool(p.get("target"))
                        text = (p.get("content") or "").strip().replace("\n", " ")
                        if len(text) > 220:
                            text = text[:220] + "..."
                        kind = "comment" if is_comment else "post"
                        lines.append(f"- {i}. [{ts}] #{topic} {votes} ({kind}) `{p.get('txhash','')[:12]}...`")
                        if is_comment and p.get("parent_owner"):
                            lines.append(f"  - Reply to owner: `{p.get('parent_owner')}`")
                        if text:
                            lines.append(f"  - {text}")
                    lines.append("")

                # Match user info
                match_user = users.get(m.match_addr)
                if match_user:
                    match_fps = all_fps.get(m.match_addr, [])
                    lines.append(f"| Metric | Value |")
                    lines.append(f"|--------|-------|")
                    lines.append(f"| Posts | {match_user.posts} |")
                    lines.append(f"| Comments | {match_user.comments} |")
                    lines.append(f"| Active Days | {match_user.active_days} |")
                    lines.append(f"| Timezone | {get_user_timezone(match_fps, match_user.hour_histogram)} |")
                    lines.append("")

        if high:
            lines.append("### HIGH Severity Fingerprint Matches")
            lines.append("")
            lines.append(
                "These accounts have a strong fingerprint combo match with at least one high-entropy attribute match."
            )
            lines.append("")
            lines.append("| Username | Address | FP Score | FP Weight | Pref Sim | Flags |")
            lines.append("|----------|---------|----------|----------:|----------|-------|")
            for m in high:
                flags = []
                if m.same_ip:
                    flags.append("IP")
                if m.same_canvas:
                    flags.append("Canvas")
                flags_str = ", ".join(flags) if flags else "-"
                pref_str = f"{m.pref_sim:.0%} ({m.pref_shared})" if m.pref_shared > 0 else "-"
                fp_weight = m.fp_match.total_weight if m.fp_match else 0.0
                lines.append(
                    f"| {m.match_username} | `{m.match_addr[:20]}...` | {m.fp_score:.0%} | {fp_weight:.1f} | {pref_str} | {flags_str} |"
                )
            lines.append("")

        if pref_similar:
            lines.append("### Preference Similarity (Not A Verdict)")
            lines.append("")
            lines.append(
                "These accounts have similar voting preferences. This can happen for real users in the same community, "
                "so it is provided as evidence but does not imply sockpuppeting by itself."
            )
            lines.append("")
            lines.append("| Username | Pref Sim | Shared Prefs | FP Score | Device Flags |")
            lines.append("|----------|----------|--------------|----------|--------------|")
            for m in pref_similar[:100]:
                device_flags = []
                if m.same_ip:
                    device_flags.append("IP")
                if m.same_canvas:
                    device_flags.append("Canvas")
                device_str = ", ".join(device_flags) if device_flags else "-"
                pref_str = f"{m.pref_sim:.0%}"
                lines.append(f"| {m.match_username} | {pref_str} | {m.pref_shared} | {m.fp_score:.0%} | {device_str} |")
            if len(pref_similar) > 100:
                lines.append(f"| ... and {len(pref_similar) - 100} more | | | | |")
            lines.append("")

        if notable:
            notable_display = [
                m
                for m in notable
                if (
                    m.fp_score >= MIN_FP_SCORE_TO_DISPLAY_NOTABLE
                    or (m.fp_match and m.fp_match.has_device_match)
                    or (m.fp_match and m.fp_match.total_weight >= MIN_FP_WEIGHT_TO_DISPLAY_NOTABLE)
                )
            ]
            omitted = len(notable) - len(notable_display)

            lines.append("### Other Notable Fingerprint Matches")
            lines.append("")
            lines.append(
                "This section is restricted to matches with meaningful fingerprint overlap. "
                "Very low-signal matches are omitted to avoid noise."
            )
            if omitted > 0:
                lines.append(f"Low-signal matches omitted: {omitted}")
            lines.append("")

            if not notable_display:
                lines.append("*No additional notable fingerprint matches.*")
                lines.append("")
            else:
                lines.append("| Username | FP Score | FP Weight | Pref Sim |")
                lines.append("|----------|----------|----------:|----------|")
                for m in notable_display[:50]:  # Limit display for readability
                    pref_str = f"{m.pref_sim:.0%} ({m.pref_shared})" if m.pref_shared > 0 else "-"
                    fp_weight = m.fp_match.total_weight if m.fp_match else 0.0
                    lines.append(f"| {m.match_username} | {m.fp_score:.0%} | {fp_weight:.1f} | {pref_str} |")
                if len(notable_display) > 50:
                    lines.append(f"| ... and {len(notable_display) - 50} more | | | |")
            lines.append("")

    # Recent posts for the target (unbiased facts)
    lines.append("## Recent Posts (Target)")
    lines.append("")
    if not evidence.recent_posts:
        lines.append("*No recent posts found in the lookback window.*")
        lines.append("")
    else:
        for i, p in enumerate(evidence.recent_posts[:MAX_RECENT_POSTS_TARGET_FILE], 1):
            ts = format_ts(p.get("created_at", 0))
            topic = p.get("topic") or "none"
            votes = f"+{p.get('upvotes', 0)}/-{p.get('downvotes', 0)}"
            is_comment = bool(p.get("target"))
            kind = "comment" if is_comment else "post"
            txhash = p.get("txhash", "")
            title = (p.get("title") or "").strip().replace("\n", " ")
            content = (p.get("content") or "").strip()
            if len(content) > 600:
                content = content[:600] + "..."
            lines.append(f"**{i}. [{ts}] #{topic} {votes} ({kind})**")
            if title and not is_comment:
                lines.append(f"Title: {title[:120]}")
            if txhash:
                lines.append(f"TxHash: `{txhash}`")
            if is_comment and p.get("parent_owner"):
                lines.append(f"Reply to owner: `{p.get('parent_owner')}`")
            if content:
                lines.append("")
                lines.append(f"> {content.replace(chr(10), chr(10)+'> ')}")
            lines.append("")

    # AI Verdict placeholder
    lines.append("---")
    lines.append("")
    lines.append("## AI Analysis")
    lines.append("")
    if evidence.verdict:
        lines.append(f"**Verdict**: {evidence.verdict}")
        lines.append(f"**Confidence**: {evidence.confidence}")
        lines.append(f"**Recommendation**: {evidence.recommendation}")
        lines.append("")
        lines.append("### Reasoning")
        lines.append("")
        lines.append(evidence.reasoning)
        lines.append("")
        if evidence.likely_real_anchor:
            lines.append(f"**Likely Real Anchor**: {evidence.likely_real_anchor}")
            lines.append("")
    else:
        lines.append("*AI analysis pending.*")
        lines.append("")

    return "\n".join(lines)


def generate_evidence_json(evidence: TargetEvidence) -> Dict[str, Any]:
    """Generate JSON representation of evidence."""
    result: Dict[str, Any] = {
        "address": evidence.address,
        "username": evidence.username,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    if evidence.user_data:
        u = evidence.user_data
        result["activity"] = {
            "posts": u.posts,
            "comments": u.comments,
            "active_days": u.active_days,
            "upvotes_given": u.upvotes_given,
            "downvotes_given": u.downvotes_given,
            "votes_received_up": u.votes_received_up,
            "votes_received_down": u.votes_received_down,
            "first_action": u.first_action_ts,
            "last_action": u.last_action_ts,
            "topics": u.topic_counts,
            "timezone": get_user_timezone(evidence.fingerprints, u.hour_histogram),
            "hour_histogram": u.hour_histogram,
        }

    result["fingerprints"] = [
        {
            "ip_hash": fp.ip_hash,
            "canvas_hash": fp.canvas_hash,
            "screen": f"{fp.screen_width}x{fp.screen_height}" if fp.screen_width else None,
            "timezone": fp.timezone,
            "first_seen": fp.first_seen,
            "last_seen": fp.last_seen,
            "seen_count": fp.seen_count,
        }
        for fp in evidence.fingerprints
    ]

    result["referral"] = {
        "referrer_addr": evidence.referrer_addr,
        "referrer_username": evidence.referrer_username,
        "referee_count": evidence.referee_count,
        "pending_reward": evidence.pending_reward,
    }

    result["matches"] = {
        "critical": [
            {
                "addr": m.match_addr,
                "username": m.match_username,
                "fp_score": m.fp_score,
                "fp_weight": m.fp_match.total_weight if m.fp_match else 0.0,
                "fp_weight_max": m.fp_match.max_possible_weight if m.fp_match else 0.0,
                "fp_has_high_entropy_attr": m.fp_match.has_device_match if m.fp_match else False,
                "pref_sim": m.pref_sim,
                "pref_shared": m.pref_shared,
                "same_ip": m.same_ip,
                "same_canvas": m.same_canvas,
            }
            for m in evidence.matches
            if m.severity == "CRITICAL"
        ],
        "high": [
            {
                "addr": m.match_addr,
                "username": m.match_username,
                "fp_score": m.fp_score,
                "fp_weight": m.fp_match.total_weight if m.fp_match else 0.0,
                "fp_weight_max": m.fp_match.max_possible_weight if m.fp_match else 0.0,
                "fp_has_high_entropy_attr": m.fp_match.has_device_match if m.fp_match else False,
                "pref_sim": m.pref_sim,
                "pref_shared": m.pref_shared,
                "same_ip": m.same_ip,
                "same_canvas": m.same_canvas,
            }
            for m in evidence.matches
            if m.severity == "HIGH"
        ],
        "notable_count": len([m for m in evidence.matches if m.severity == "NOTABLE"]),
    }

    result["ai_verdict"] = {
        "verdict": evidence.verdict,
        "confidence": evidence.confidence,
        "recommendation": evidence.recommendation,
        "reasoning": evidence.reasoning,
        "likely_real_anchor": evidence.likely_real_anchor,
    }

    result["recent_posts"] = evidence.recent_posts
    result["match_recent_posts"] = evidence.match_recent_posts

    return result


# =============================================================================
# CHATGPT INTEGRATION
# =============================================================================

CHATGPT_SYSTEM_PROMPT = """You are a fraud detection expert analyzing user accounts for a blockchain social media platform called Mirage.

Your task is to determine if accounts are REAL users or GAMING (sockpuppets / fake accounts).

Key signals to look for:
1. SAME IP HASH - Two accounts from same IP are highly suspicious
2. SAME CANVAS HASH - Browser fingerprint match indicates same device
3. HIGH FINGERPRINT COMBO SCORE - Rare attribute combinations matching
4. PREFERENCE SIMILARITY - Same voting patterns can be correlated for real users in the same community.
   Treat preference similarity as SUPPORTING evidence only unless paired with device/fingerprint evidence.
5. COORDINATED ACTIVITY - Same timezone, same topics, same timing

Signs of a REAL user:
- Organic posting patterns (varied times, topics)
- Genuine engagement (replies, discussions)
- Unique device fingerprints
- Different timezone/activity patterns from similar accounts

BE OBJECTIVE. Cite concrete evidence from the data provided. If the evidence is insufficient, say so and recommend REVIEW."""

CHATGPT_USER_PROMPT = """Analyze this account and its similar accounts. Is this a REAL user or a GAMING/FAKE account?

{evidence_markdown}

---

Based on the evidence above, provide your verdict in YAML format:

```yaml
verdict: GAMING  # One of: REAL_USER, LIKELY_REAL, REVIEW, LIKELY_GAMING, GAMING
confidence: HIGH  # One of: HIGH, MEDIUM, LOW
recommendation: deny  # One of: approve, deny, review
reasoning: |
  2-3 sentences explaining your conclusion with specific evidence.
likely_real_anchor: |
  If this account appears fake, which similar account (if any) appears to be
  the real/original account and why? Leave empty if this account is real.
```"""


def analyze_with_chatgpt(evidence_markdown: str) -> Dict[str, str]:
    """Send evidence to ChatGPT and get verdict."""
    if not CHATGPT_API_KEY:
        return {
            "verdict": "REVIEW",
            "confidence": "LOW",
            "recommendation": "review",
            "reasoning": "ChatGPT analysis skipped: No API key configured.",
            "likely_real_anchor": "",
        }

    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CHATGPT_API_KEY}",
        }
        data = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": CHATGPT_SYSTEM_PROMPT},
                {"role": "user", "content": CHATGPT_USER_PROMPT.format(evidence_markdown=evidence_markdown)},
            ],
            "temperature": 0.3,
            "max_tokens": 1000,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
            ai_response = result["choices"][0]["message"]["content"]

            # Parse YAML from response
            import re

            yaml_match = re.search(r"```yaml\s*(.*?)\s*```", ai_response, re.DOTALL)
            if yaml_match:
                yaml_content = yaml_match.group(1)
                # Simple YAML parsing (avoid dependency)
                parsed = {}
                current_key = None
                current_value = []

                for line in yaml_content.split("\n"):
                    if line.strip().startswith("#"):
                        continue
                    if ":" in line and not line.startswith(" "):
                        if current_key and current_value:
                            parsed[current_key] = "\n".join(current_value).strip()
                        parts = line.split(":", 1)
                        current_key = parts[0].strip()
                        value = parts[1].strip() if len(parts) > 1 else ""
                        if value == "|":
                            current_value = []
                        else:
                            parsed[current_key] = value.strip()
                            current_key = None
                            current_value = []
                    elif current_key and line.startswith("  "):
                        current_value.append(line.strip())

                if current_key and current_value:
                    parsed[current_key] = "\n".join(current_value).strip()

                return {
                    "verdict": parsed.get("verdict", "REVIEW"),
                    "confidence": parsed.get("confidence", "LOW"),
                    "recommendation": parsed.get("recommendation", "review"),
                    "reasoning": parsed.get("reasoning", ai_response),
                    "likely_real_anchor": parsed.get("likely_real_anchor", ""),
                }

            # Fallback if YAML parsing fails
            return {
                "verdict": "REVIEW",
                "confidence": "LOW",
                "recommendation": "review",
                "reasoning": ai_response,
                "likely_real_anchor": "",
            }

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        return {
            "verdict": "REVIEW",
            "confidence": "LOW",
            "recommendation": "review",
            "reasoning": f"ChatGPT API error: {e.code} - {error_body}",
            "likely_real_anchor": "",
        }
    except Exception as e:
        return {
            "verdict": "REVIEW",
            "confidence": "LOW",
            "recommendation": "review",
            "reasoning": f"ChatGPT error: {e}",
            "likely_real_anchor": "",
        }


def generate_ai_evidence_markdown(
    evidence: TargetEvidence,
    users: Dict[str, UserData],
    all_fps: Dict[str, List[FingerprintData]],
) -> str:
    """Generate a condensed, high-signal evidence snapshot for ChatGPT."""
    lines: List[str] = []
    lines.append(f"# Evidence Snapshot: {evidence.username}")
    lines.append("")
    lines.append(f"- Address: `{evidence.address}`")
    if evidence.user_data:
        u = evidence.user_data
        lines.append(f"- Age: {u.age_days:.1f} days")
        lines.append(f"- Posts: {u.posts}, Comments: {u.comments}, Active days: {u.active_days}")
        lines.append(f"- Timezone: {get_user_timezone(evidence.fingerprints, u.hour_histogram)}")
        lines.append(f"- Unique topics: {len(u.topic_counts)}")
    lines.append("")

    # Fingerprint summary
    lines.append("## Fingerprint Summary")
    lines.append("")
    lines.append(f"- Fingerprints on file: {len(evidence.fingerprints)}")
    if evidence.fingerprints:
        unique_ips = len({fp.ip_hash for fp in evidence.fingerprints if fp.ip_hash})
        unique_canvas = len({fp.canvas_hash for fp in evidence.fingerprints if fp.canvas_hash})
        lines.append(f"- Unique IP hashes: {unique_ips}")
        lines.append(f"- Unique canvas hashes: {unique_canvas}")
    lines.append("")

    # Critical/high matches summary (keep concise)
    crit = [m for m in evidence.matches if m.severity == "CRITICAL"][:10]
    high = [m for m in evidence.matches if m.severity == "HIGH"][:15]

    lines.append("## Strong Device/Fingerprint Matches")
    lines.append("")
    if not crit and not high:
        lines.append("None found.")
        lines.append("")
    else:
        if crit:
            lines.append("### CRITICAL")
            for m in crit:
                flags = []
                if m.same_ip:
                    flags.append("SAME_IP")
                if m.same_canvas:
                    flags.append("SAME_CANVAS")
                if m.fp_match:
                    flags.append(f"FP={m.fp_match.score:.0%} weight={m.fp_match.total_weight:.1f}")
                    if m.fp_match.has_device_match:
                        flags.append("HAS_HIGH_ENTROPY_ATTR")
                if m.pref_sim >= CRITICAL_PREF_SIM:
                    flags.append(f"PREF={m.pref_sim:.0%} ({m.pref_shared})")
                lines.append(f"- {m.match_username} `{m.match_addr}`: {', '.join(flags)}")
            lines.append("")

        if high:
            lines.append("### HIGH")
            for m in high:
                fpw = m.fp_match.total_weight if m.fp_match else 0.0
                lines.append(f"- {m.match_username} `{m.match_addr}`: FP={m.fp_score:.0%} weight={fpw:.1f}")
            lines.append("")

    # Recent posts (target) - truncated
    lines.append("## Recent Posts (Target, truncated)")
    lines.append("")
    if not evidence.recent_posts:
        lines.append("No posts.")
    else:
        for p in evidence.recent_posts[:MAX_RECENT_POSTS_TARGET_AI]:
            ts = format_ts(p.get("created_at", 0))
            topic = p.get("topic") or "none"
            is_comment = bool(p.get("target"))
            kind = "comment" if is_comment else "post"
            text = (p.get("content") or "").strip().replace("\n", " ")
            if len(text) > 240:
                text = text[:240] + "..."
            lines.append(f"- [{ts}] #{topic} ({kind}): {text}")
    lines.append("")

    # Preference similarity caution
    pref_similar = [m for m in evidence.matches if m.pref_sim >= HIGH_PREF_SIM][:20]
    if pref_similar:
        lines.append("## Preference Similarity (supporting evidence only)")
        lines.append("")
        for m in pref_similar:
            lines.append(f"- {m.match_username}: {m.pref_sim:.0%} ({m.pref_shared} shared), FP={m.fp_score:.0%}")
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Batch AI Account Review - Sockpuppet Detection")
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Input file with usernames/addresses (one per line)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=LOOKBACK_DAYS,
        help=f"Days of activity to analyze (default: {LOOKBACK_DAYS})",
    )
    args = parser.parse_args()

    # Validate input file
    if not os.path.exists(args.input):
        print(f"ERROR: Input file not found: {args.input}")
        sys.exit(1)

    # Parse input
    identifiers = parse_input_file(args.input)
    if not identifiers:
        print("ERROR: No identifiers found in input file.")
        sys.exit(1)

    print("=" * 60)
    print("Batch AI Account Review")
    print("=" * 60)
    print(f"Input: {args.input}")
    print(f"Targets: {len(identifiers)}")
    print(f"Output: {args.output_dir}")
    print(f"Lookback: {args.lookback_days} days")
    print("")

    # Prompt for API key if not set
    global CHATGPT_API_KEY
    if not CHATGPT_API_KEY:
        print("Enter ChatGPT API key (or press Enter to skip AI analysis):")
        try:
            api_key = getpass.getpass("API Key: ").strip()
            if api_key:
                CHATGPT_API_KEY = api_key
                print("API key set. AI analysis enabled.")
            else:
                print("No API key provided. AI analysis will be skipped.")
        except (EOFError, KeyboardInterrupt):
            print("\nSkipping AI analysis.")
    print("")

    # Setup output directory
    output_dir = Path(args.output_dir)
    targets_dir = output_dir / "targets"

    # Clear generated artifacts (always overwrite)
    if targets_dir.exists():
        shutil.rmtree(targets_dir)
    for f in ["summary.md", "summary.json"]:
        fpath = output_dir / f
        if fpath.exists():
            fpath.unlink()

    output_dir.mkdir(parents=True, exist_ok=True)
    targets_dir.mkdir(parents=True, exist_ok=True)

    now_ts = int(time.time())
    since_ts = now_ts - args.lookback_days * 86400

    started = time.time()

    with connect() as conn:
        with conn.cursor() as cur:
            # Resolve all identifiers
            print("Resolving identifiers...")
            resolved: List[Tuple[str, str]] = []
            not_found: List[str] = []

            for identifier in identifiers:
                result = resolve_identifier(cur, identifier)
                if result:
                    resolved.append(result)
                    print(f"  {identifier} -> {result[1]} ({result[0][:20]}...)")
                else:
                    not_found.append(identifier)
                    print(f"  {identifier} -> NOT FOUND")

            if not_found:
                print(f"\nWarning: {len(not_found)} identifier(s) not found:")
                for nf in not_found:
                    print(f"  - {nf}")

            if not resolved:
                print("\nERROR: No valid identifiers found. Exiting.")
                sys.exit(1)

            print(f"\nResolved {len(resolved)} targets.")
            print("")

            # Load all data
            print("Loading all users...")
            users = load_all_users(cur, since_ts)
            print(f"  Loaded {len(users)} users")

            print("Loading fingerprints...")
            all_fps = load_fingerprints_from_db(cur)
            print(f"  Loaded fingerprints for {len(all_fps)} users")

            print("Loading fingerprint frequencies...")
            fp_freq = load_fingerprint_frequencies(cur)
            print(f"  {fp_freq.total_users} users, {len(fp_freq.counts)} attribute types")

            print("Loading preferences...")
            all_prefs = load_all_preferences(cur)
            print(f"  Loaded preferences for {len(all_prefs)} users")

            print("Loading referral context...")
            referral_links, referee_counts, pending_by_referee = load_referral_context(cur)
            print(f"  {len(referral_links)} referral links")
            print("")

            # Process each target
            print("Analyzing targets...")
            all_evidence: List[TargetEvidence] = []

            for i, (addr, username) in enumerate(resolved, 1):
                print(f"  [{i}/{len(resolved)}] {username}...")

                evidence = build_target_evidence(
                    addr,
                    username,
                    users,
                    all_fps,
                    all_prefs,
                    fp_freq,
                    referral_links,
                    referee_counts,
                    pending_by_referee,
                )

                # Attach recent posts (target + small sample for CRITICAL/HIGH matches)
                augment_evidence_with_recent_posts(cur, evidence, since_ts)

                # Generate markdown for AI (condensed snapshot)
                ai_md = generate_ai_evidence_markdown(evidence, users, all_fps)

                # Get AI verdict
                if CHATGPT_API_KEY:
                    print(f"      Analyzing with ChatGPT...")
                    verdict = analyze_with_chatgpt(ai_md)
                    evidence.verdict = verdict["verdict"]
                    evidence.confidence = verdict["confidence"]
                    evidence.recommendation = verdict["recommendation"]
                    evidence.reasoning = verdict["reasoning"]
                    evidence.likely_real_anchor = verdict["likely_real_anchor"]
                    print(f"      Verdict: {evidence.verdict} ({evidence.confidence})")

                # Regenerate markdown with verdict
                evidence_md = generate_evidence_markdown(evidence, users, all_fps)

                # Write per-target files
                safe_name = re.sub(r"[^\w\-]", "_", username)[:50]
                (targets_dir / f"{safe_name}.md").write_text(evidence_md, encoding="utf-8")
                (targets_dir / f"{safe_name}.json").write_text(
                    json.dumps(generate_evidence_json(evidence), indent=2),
                    encoding="utf-8",
                )

                all_evidence.append(evidence)

            print("")

    # Generate summary
    print("Generating summary...")

    # Build clusters from CRITICAL matches using Union-Find
    # Only consider matches between accounts that are both in our target list
    target_addrs = {e.address for e in all_evidence}
    addr_to_username = {e.address: e.username for e in all_evidence}

    # Union-Find data structures
    parent: Dict[str, str] = {addr: addr for addr in target_addrs}
    rank: Dict[str, int] = {addr: 0 for addr in target_addrs}

    def find(x: str) -> str:
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x: str, y: str):
        px, py = find(x), find(y)
        if px == py:
            return
        if rank[px] < rank[py]:
            px, py = py, px
        parent[py] = px
        if rank[px] == rank[py]:
            rank[px] += 1

    # Build edges from CRITICAL matches
    for e in all_evidence:
        for m in e.matches:
            if m.severity == "CRITICAL" and m.match_addr in target_addrs:
                union(e.address, m.match_addr)

    # Group by cluster
    clusters: Dict[str, List[str]] = defaultdict(list)
    for addr in target_addrs:
        clusters[find(addr)].append(addr)

    # Filter to clusters with 2+ members and sort by size
    multi_clusters = [
        sorted(addrs, key=lambda a: addr_to_username.get(a, a)) for addrs in clusters.values() if len(addrs) >= 2
    ]
    multi_clusters.sort(key=lambda c: -len(c))

    summary_lines = []
    summary_lines.append("# Batch Account Review Summary")
    summary_lines.append("")
    summary_lines.append(f"**Generated**: {format_ts(int(time.time()))}")
    summary_lines.append(f"**Targets**: {len(all_evidence)}")
    summary_lines.append(f"**Lookback**: {args.lookback_days} days")
    summary_lines.append("")

    # Clusters section (before verdict summary)
    if multi_clusters:
        summary_lines.append("## Clusters (CRITICAL Connections)")
        summary_lines.append("")
        summary_lines.append("Accounts connected by CRITICAL-level signals (same IP, same canvas, or FP ≥50%).")
        summary_lines.append("Each cluster likely represents the same person.")
        summary_lines.append("")
        for i, cluster_addrs in enumerate(multi_clusters, 1):
            usernames = [addr_to_username.get(a, a[:20]) for a in cluster_addrs]
            summary_lines.append(f"**Cluster {i}** ({len(cluster_addrs)} accounts):")
            for username in usernames:
                summary_lines.append(f"- {username}")
            summary_lines.append("")
    else:
        summary_lines.append("## Clusters (CRITICAL Connections)")
        summary_lines.append("")
        summary_lines.append("*No clusters found (no CRITICAL connections between analyzed accounts).*")
        summary_lines.append("")

    # Stats
    verdicts = defaultdict(int)
    for e in all_evidence:
        verdicts[e.verdict or "PENDING"] += 1

    summary_lines.append("## Verdict Summary")
    summary_lines.append("")
    summary_lines.append("| Verdict | Count |")
    summary_lines.append("|---------|-------|")
    for v in ["GAMING", "LIKELY_GAMING", "REVIEW", "LIKELY_REAL", "REAL_USER", "PENDING"]:
        if verdicts[v] > 0:
            summary_lines.append(f"| {v} | {verdicts[v]} |")
    summary_lines.append("")

    # Results table
    summary_lines.append("## All Targets")
    summary_lines.append("")
    summary_lines.append("| Username | Verdict | Confidence | Critical Matches | High Matches | Recommendation |")
    summary_lines.append("|----------|---------|------------|------------------|--------------|----------------|")
    for e in all_evidence:
        critical_count = len([m for m in e.matches if m.severity == "CRITICAL"])
        high_count = len([m for m in e.matches if m.severity == "HIGH"])
        summary_lines.append(
            f"| [{e.username}](targets/{re.sub(r'[^\\w\\-]', '_', e.username)[:50]}.md) | {e.verdict or 'PENDING'} | {e.confidence or '-'} | {critical_count} | {high_count} | {e.recommendation or '-'} |"
        )
    summary_lines.append("")

    (output_dir / "summary.md").write_text("\n".join(summary_lines), encoding="utf-8")

    # Summary JSON
    summary_json = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": args.lookback_days,
        "targets_count": len(all_evidence),
        "verdicts": dict(verdicts),
        "clusters": [
            {
                "id": i,
                "size": len(cluster_addrs),
                "accounts": [{"address": a, "username": addr_to_username.get(a, a[:20])} for a in cluster_addrs],
            }
            for i, cluster_addrs in enumerate(multi_clusters, 1)
        ],
        "targets": [
            {
                "address": e.address,
                "username": e.username,
                "verdict": e.verdict,
                "confidence": e.confidence,
                "recommendation": e.recommendation,
                "critical_matches": len([m for m in e.matches if m.severity == "CRITICAL"]),
                "high_matches": len([m for m in e.matches if m.severity == "HIGH"]),
            }
            for e in all_evidence
        ],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary_json, indent=2), encoding="utf-8")

    elapsed = time.time() - started
    print(f"\nCompleted in {elapsed:.1f}s")
    print(f"Output: {output_dir}")
    print("")

    if multi_clusters:
        print(f"Clusters found: {len(multi_clusters)}")
        for i, cluster_addrs in enumerate(multi_clusters, 1):
            usernames = [addr_to_username.get(a, a[:20]) for a in cluster_addrs]
            print(f"  Cluster {i}: {', '.join(usernames)}")
        print("")

    print("Verdicts:")
    for v in ["GAMING", "LIKELY_GAMING", "REVIEW", "LIKELY_REAL", "REAL_USER"]:
        if verdicts[v] > 0:
            print(f"  {v}: {verdicts[v]}")


if __name__ == "__main__":
    main()
