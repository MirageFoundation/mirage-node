#!/usr/bin/env python3
"""
Referral Chain Analysis for Gaming Detection.

Generates per-REFERRER markdown analysis files that include:
- The referrer's full profile and activity
- ALL their direct referees (siblings) with full profiles
- Cross-comparison between ALL siblings (not just vs referrer)
- Detection of account rotation patterns (B farms 10, then C takes over)
- Full referral tree visualization

Key fraud patterns detected:
- Same person running multiple referred accounts
- Account rotation after hitting reward caps
- Coordinated activity between siblings
- Identical content/vocabulary across siblings

Output: referrals/analysis/

Usage:
    python referrals/referral_1_analysis.py
    python referrals/referral_1_analysis.py --output-dir /path/to/output
    python referrals/referral_1_analysis.py --referrer <address>
    python referrals/referral_1_analysis.py --save-db
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.request
import urllib.error
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
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "analysis")
LOOKBACK_DAYS = 90


# ChatGPT API key - will be prompted if not in environment
CHATGPT_API_KEY = os.environ.get("CHATGPT_API_KEY", "")

# Referral-specific thresholds
MIN_ACTIVITY_FOR_LEGIT = 5  # Minimum posts/comments for legitimate user
MIN_ACTIVE_DAYS_FOR_LEGIT = 3  # Minimum unique days active
MIN_TOPICS_FOR_LEGIT = 2  # Minimum unique topics

# Gaming detection thresholds
COORDINATED_TIMING_WINDOW_SECS = 60  # Posts within this window are "coordinated"
REGISTRATION_BURST_WINDOW_SECS = 300  # Registrations within 5 min are suspicious
HIGH_SIMILARITY_THRESHOLD = 0.7  # Definitely suspicious
SUSPICIOUS_THRESHOLD = 0.5  # Worth investigating
MIN_ACTIVITY_RATIO = 0.3  # Referee should have at least 30% of referrer's activity

# Limits
MAX_POSTS_PER_USER = 500  # Store all posts within lookback window

# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class UserData:
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
    post_timestamps: List[int] = field(default_factory=list)

    # Topics
    topic_counts: Dict[str, int] = field(default_factory=dict)

    # Interactions within referral chain
    votes_to_referrer: int = 0
    votes_from_referrer: int = 0
    replies_to_referrer: int = 0
    replies_from_referrer: int = 0

    # Network interactions (all users)
    reply_targets: Dict[str, int] = field(default_factory=dict)  # who this user replies to
    reply_sources: Dict[str, int] = field(default_factory=dict)  # who replies to this user
    vote_targets: Dict[str, int] = field(default_factory=dict)  # who this user votes on

    # Content
    word_counts: Counter = field(default_factory=Counter)
    content_hashes: Set[str] = field(default_factory=set)
    avg_post_length: float = 0.0
    total_words: int = 0

    # Raw posts for output
    recent_posts: List[Dict] = field(default_factory=list)

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


# Fingerprint class is now imported from shared.fingerprint as FingerprintData
Fingerprint = FingerprintData  # Alias for backwards compatibility


@dataclass
class SiblingComparison:
    """Comparison between two sibling accounts (same referrer)."""

    user_a: str
    user_b: str
    username_a: str
    username_b: str

    timing_sim: float = 0.0
    topic_sim: float = 0.0
    content_sim: float = 0.0
    vocabulary_sim: float = 0.0
    active_days_sim: float = 0.0
    coordinated_posts: int = 0
    identical_content: int = 0
    same_timezone: bool = False

    # Sequential activity pattern (A stops, B starts)
    sequential_activity: bool = False
    overlap_days: int = 0


@dataclass
class ReferralRelationship:
    """Analysis of a single referrer -> referee relationship."""

    referrer: str
    referee: str
    referred_at: int

    # Similarity scores
    timing_sim: float = 0.0
    topic_sim: float = 0.0
    content_sim: float = 0.0
    vocabulary_sim: float = 0.0
    active_days_sim: float = 0.0

    # Gaming indicators
    registration_burst: bool = False
    minimal_activity: bool = False
    one_way_support: bool = False
    coordinated_posts: int = 0
    identical_content: int = 0
    same_timezone: bool = False

    # Raw counts
    referee_votes_to_referrer: int = 0
    referee_votes_from_referrer: int = 0
    referee_replies_to_referrer: int = 0
    referee_replies_from_referrer: int = 0

    # Combined score (higher = more suspicious)
    gaming_score: float = 0.0

    # Classification
    classification: str = "UNKNOWN"
    confidence: float = 0.0
    flags: List[str] = field(default_factory=list)
    recommendation: str = "REVIEW"


@dataclass
class ReferrerAnalysis:
    """Complete analysis of a referrer and all their referees."""

    referrer: str
    referrer_username: str
    referrer_data: Optional[UserData] = None

    # All direct referees
    referees: List[str] = field(default_factory=list)
    referee_data: Dict[str, UserData] = field(default_factory=dict)
    referee_relationships: Dict[str, ReferralRelationship] = field(default_factory=dict)

    # Sibling comparisons
    sibling_comparisons: List[SiblingComparison] = field(default_factory=list)

    # Aggregate stats
    total_referees: int = 0
    gaming_count: int = 0
    suspicious_count: int = 0
    legit_count: int = 0
    insufficient_count: int = 0

    # Overall assessment
    overall_risk: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    overall_flags: List[str] = field(default_factory=list)


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


def load_referral_links(cur) -> Dict[str, Tuple[str, int]]:
    """Load referral links: {referee_address: (referrer_address, referred_at)}."""
    cur.execute("SELECT LOWER(user_address), LOWER(referrer_address), referred_at FROM referral_links")
    return {row[0]: (row[1], row[2]) for row in cur.fetchall()}


def load_pending_rewards(cur) -> Dict[str, float]:
    """Load pending rewards per referrer from referral_pending_rewards.

    Returns {referrer_address: total_pending}
    """
    cur.execute(
        """
        SELECT user_address, SUM(total_pending)
        FROM referral_pending_rewards
        WHERE status = 'pending'
        GROUP BY user_address
    """
    )
    return {row[0].lower(): float(row[1]) for row in cur.fetchall()}


def load_per_referee_pending(cur) -> Dict[Tuple[str, str], float]:
    """Load per-referee pending amounts from referral_user_accruals.

    Returns {(beneficiary_address, referee_address): pending_amount}
    """
    cur.execute(
        """
        SELECT beneficiary_address, referee_address, pending
        FROM referral_user_accruals
        WHERE pending > 0
    """
    )
    return {(row[0].lower(), row[1].lower()): float(row[2]) for row in cur.fetchall()}


def load_total_pending_by_referee(cur) -> Dict[str, float]:
    """Load total pending amounts per referee (summed across all beneficiaries).

    Returns {referee_address: total_pending}
    """
    cur.execute(
        """
        SELECT LOWER(referee_address), SUM(pending)
        FROM referral_user_accruals
        WHERE pending > 0
        GROUP BY LOWER(referee_address)
    """
    )
    return {row[0]: float(row[1]) for row in cur.fetchall()}


def load_payout_history() -> Dict[str, float]:
    """Load total paid amounts from payout_history.csv.

    Returns {referrer_address: total_paid}
    """
    import csv

    history_file = Path(SCRIPT_DIR) / "payout_history.csv"
    if not history_file.exists():
        return {}

    paid: Dict[str, float] = {}
    with open(history_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            addr = row.get("address", "").lower()
            amount = float(row.get("amount", 0))
            paid[addr] = paid.get(addr, 0) + amount
    return paid


def load_referral_tree(cur) -> Dict[str, List[str]]:
    """Load referral tree: {referrer_address: [referee_addresses]}."""
    cur.execute("SELECT LOWER(user_address), LOWER(referrer_address) FROM referral_links")
    tree: Dict[str, List[str]] = defaultdict(list)
    for user, referrer in cur.fetchall():
        tree[referrer].append(user)
    return dict(tree)


def load_fingerprints(cur, relevant_addresses: Optional[Set[str]] = None) -> Dict[str, List[FingerprintData]]:
    """Load fingerprints by user address, optionally filtered to relevant addresses.
    
    Uses the shared fingerprint module which includes JSONB attributes.
    """
    return load_fingerprints_from_db(cur, relevant_addresses)


def load_relevant_data(
    cur, since_ts: int, relevant_addresses: Set[str]
) -> Tuple[Dict[str, UserData], Dict[str, Dict], Dict[str, List[Dict]]]:
    """Load users, posts, and votes only for relevant addresses."""

    if not relevant_addresses:
        return {}, {}, {}

    # Normalize addresses
    addr_list = [addr.lower() for addr in relevant_addresses]

    # Load profiles only for relevant users
    cur.execute(
        """
        SELECT LOWER(owner), COALESCE(username, ''), COALESCE(level, 0), COALESCE(created_at, 0)
        FROM profiles
        WHERE LOWER(owner) = ANY(%s)
        """,
        (addr_list,),
    )
    users: Dict[str, UserData] = {}
    for owner, username, level, created_at in cur.fetchall():
        o = owner.strip().lower()
        if o:
            users[o] = UserData(owner=o, username=username, level=level, created_at=created_at)

    # Create UserData for any missing addresses
    for addr in addr_list:
        if addr not in users:
            users[addr] = UserData(owner=addr, username=addr[:20])

    # Load posts only for relevant users
    cur.execute(
        """
        SELECT LOWER(owner), txhash, COALESCE(title, ''), COALESCE(content, ''),
               COALESCE(topic, ''), COALESCE(root_topic, ''), COALESCE(target, ''),
               created_at, COALESCE(deleted, FALSE)
        FROM posts
        WHERE created_at >= %s AND LOWER(owner) = ANY(%s)
        ORDER BY created_at DESC
        """,
        (since_ts, addr_list),
    )

    posts_by_hash: Dict[str, Dict] = {}
    posts_by_user: Dict[str, List[Dict]] = defaultdict(list)

    for row in cur.fetchall():
        owner, txhash, title, content, topic, root_topic, target, created_at, deleted = row
        o = owner.strip().lower()
        post = {
            "txhash": txhash,
            "owner": o,
            "title": title,
            "content": content,
            "topic": root_topic or topic or "",
            "target": target or "",
            "created_at": created_at,
            "deleted": deleted,
            "upvotes": 0,
            "downvotes": 0,
        }
        posts_by_hash[txhash.lower()] = post
        posts_by_user[o].append(post)

        if o in users and not deleted:
            u = users[o]
            if target:
                u.comments += 1
            else:
                u.posts += 1

            u.post_timestamps.append(created_at)
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

            if len(u.recent_posts) < MAX_POSTS_PER_USER:
                u.recent_posts.append(post)

    # Load target posts for reply tracking (posts that our users replied to)
    target_hashes = [p["target"].lower() for p in posts_by_hash.values() if p["target"]]
    if target_hashes:
        cur.execute(
            """
            SELECT LOWER(owner), txhash
            FROM posts
            WHERE LOWER(txhash) = ANY(%s)
            """,
            (target_hashes,),
        )
        for owner, txhash in cur.fetchall():
            if txhash.lower() not in posts_by_hash:
                posts_by_hash[txhash.lower()] = {"owner": owner.lower(), "txhash": txhash}

    # Track reply targets (who each user replies to)
    for post in posts_by_hash.values():
        if post.get("target") and not post.get("deleted"):
            target_lower = post["target"].lower()
            if target_lower in posts_by_hash:
                replier = post["owner"]
                target_owner = posts_by_hash[target_lower]["owner"]
                if replier in users and target_owner != replier:
                    users[replier].reply_targets[target_owner] = users[replier].reply_targets.get(target_owner, 0) + 1

    # Load replies to our users' posts (for reply_sources)
    our_post_hashes = [p["txhash"].lower() for p in posts_by_hash.values() if p.get("owner") in users]
    if our_post_hashes:
        cur.execute(
            """
            SELECT LOWER(owner), target
            FROM posts
            WHERE LOWER(target) = ANY(%s) AND COALESCE(deleted, FALSE) = FALSE
            """,
            (our_post_hashes,),
        )
        for replier, target in cur.fetchall():
            target_lower = target.lower()
            if target_lower in posts_by_hash:
                target_owner = posts_by_hash[target_lower].get("owner")
                if target_owner and target_owner in users and replier.lower() != target_owner:
                    users[target_owner].reply_sources[replier.lower()] = (
                        users[target_owner].reply_sources.get(replier.lower(), 0) + 1
                    )

    # Load votes only for relevant users (as voters or post owners)
    cur.execute(
        """
        SELECT LOWER(v.owner), LOWER(p.owner), v.target, v.user_vote, v.created_at
        FROM votes v
        JOIN posts p ON LOWER(v.target) = LOWER(p.txhash)
        WHERE v.created_at >= %s AND (LOWER(v.owner) = ANY(%s) OR LOWER(p.owner) = ANY(%s))
        """,
        (since_ts, addr_list, addr_list),
    )

    for voter, post_owner, target, weight, vote_ts in cur.fetchall():
        target_lower = target.lower()
        if target_lower in posts_by_hash:
            if weight > 0:
                posts_by_hash[target_lower]["upvotes"] = posts_by_hash[target_lower].get("upvotes", 0) + 1
            else:
                posts_by_hash[target_lower]["downvotes"] = posts_by_hash[target_lower].get("downvotes", 0) + 1
        v = voter.strip().lower()
        po = post_owner.strip().lower()
        if v in users:
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

    # Finalize user stats
    for u in users.values():
        u.active_days = len(u.active_day_set)
        if u.posts + u.comments > 0:
            u.avg_post_length = u.total_words / (u.posts + u.comments)
        u.post_timestamps.sort()

    return users, posts_by_hash, posts_by_user


def load_referral_interactions(cur, referrer: str, referee: str, since_ts: int) -> Tuple[int, int, int, int]:
    """Load vote and reply interactions between referrer and referee."""
    # Votes from referee to referrer's posts
    cur.execute(
        """
        SELECT COUNT(*) FROM votes v
        JOIN posts p ON LOWER(v.target) = LOWER(p.txhash)
        WHERE LOWER(v.owner) = %s AND LOWER(p.owner) = %s AND v.created_at >= %s
    """,
        (referee.lower(), referrer.lower(), since_ts),
    )
    votes_to_referrer = cur.fetchone()[0] or 0

    # Votes from referrer to referee's posts
    cur.execute(
        """
        SELECT COUNT(*) FROM votes v
        JOIN posts p ON LOWER(v.target) = LOWER(p.txhash)
        WHERE LOWER(v.owner) = %s AND LOWER(p.owner) = %s AND v.created_at >= %s
    """,
        (referrer.lower(), referee.lower(), since_ts),
    )
    votes_from_referrer = cur.fetchone()[0] or 0

    # Replies from referee to referrer's posts
    cur.execute(
        """
        SELECT COUNT(*) FROM posts p1
        JOIN posts p2 ON LOWER(p1.target) = LOWER(p2.txhash)
        WHERE LOWER(p1.owner) = %s AND LOWER(p2.owner) = %s AND p1.created_at >= %s
    """,
        (referee.lower(), referrer.lower(), since_ts),
    )
    replies_to_referrer = cur.fetchone()[0] or 0

    # Replies from referrer to referee's posts
    cur.execute(
        """
        SELECT COUNT(*) FROM posts p1
        JOIN posts p2 ON LOWER(p1.target) = LOWER(p2.txhash)
        WHERE LOWER(p1.owner) = %s AND LOWER(p2.owner) = %s AND p1.created_at >= %s
    """,
        (referrer.lower(), referee.lower(), since_ts),
    )
    replies_from_referrer = cur.fetchone()[0] or 0

    return votes_to_referrer, votes_from_referrer, replies_to_referrer, replies_from_referrer


# =============================================================================
# SIMILARITY COMPUTATION
# =============================================================================


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def jaccard_similarity(a: Set, b: Set) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def compute_referral_similarity(
    referrer: UserData,
    referee: UserData,
    posts_by_user: Dict[str, List[Dict]],
) -> Dict[str, float]:
    """Compute similarity metrics specific to referral gaming detection."""
    result = {
        "timing_sim": 0.0,
        "topic_sim": 0.0,
        "content_sim": 0.0,
        "vocabulary_sim": 0.0,
        "active_days_sim": 0.0,
        "coordinated_posts": 0,
        "identical_content": 0,
        "same_timezone": False,
    }

    if referrer.content_count == 0 or referee.content_count == 0:
        return result

    # Hour histogram similarity (timing patterns)
    r_hours = [x / max(1, sum(referrer.hour_histogram)) for x in referrer.hour_histogram]
    e_hours = [x / max(1, sum(referee.hour_histogram)) for x in referee.hour_histogram]
    result["timing_sim"] = cosine_similarity(r_hours, e_hours)

    # Topic overlap
    result["topic_sim"] = jaccard_similarity(set(referrer.topic_counts.keys()), set(referee.topic_counts.keys()))

    # Content hash overlap (identical posts)
    result["identical_content"] = len(referrer.content_hashes & referee.content_hashes)
    total_hashes = len(referrer.content_hashes) + len(referee.content_hashes)
    result["content_sim"] = (result["identical_content"] * 2) / max(1, total_hashes)

    # Vocabulary similarity (uncommon words they both use)
    r_vocab = {w for w, c in referrer.word_counts.items() if c >= 2 and len(w) > 4}
    e_vocab = {w for w, c in referee.word_counts.items() if c >= 2 and len(w) > 4}
    result["vocabulary_sim"] = jaccard_similarity(r_vocab, e_vocab)

    # Active days overlap
    result["active_days_sim"] = jaccard_similarity(referrer.active_day_set, referee.active_day_set)

    # Coordinated posting (posts within 60 seconds of each other)
    if referrer.post_timestamps and referee.post_timestamps:
        coord_count = 0
        for ts_r in referrer.post_timestamps:
            for ts_e in referee.post_timestamps:
                if abs(ts_r - ts_e) <= COORDINATED_TIMING_WINDOW_SECS:
                    coord_count += 1
        result["coordinated_posts"] = coord_count

    # Same timezone detection
    if sum(referrer.hour_histogram) >= 5 and sum(referee.hour_histogram) >= 5:
        r_peak = referrer.hour_histogram.index(max(referrer.hour_histogram))
        e_peak = referee.hour_histogram.index(max(referee.hour_histogram))
        result["same_timezone"] = abs(r_peak - e_peak) <= 2 or abs(r_peak - e_peak) >= 22

    return result


def compare_siblings(user_a: UserData, user_b: UserData) -> SiblingComparison:
    """Compare two sibling accounts for similarity patterns."""
    comp = SiblingComparison(
        user_a=user_a.owner,
        user_b=user_b.owner,
        username_a=user_a.username,
        username_b=user_b.username,
    )

    if user_a.content_count == 0 or user_b.content_count == 0:
        return comp

    # Timing similarity
    a_hours = [x / max(1, sum(user_a.hour_histogram)) for x in user_a.hour_histogram]
    b_hours = [x / max(1, sum(user_b.hour_histogram)) for x in user_b.hour_histogram]
    comp.timing_sim = cosine_similarity(a_hours, b_hours)

    # Topic overlap
    comp.topic_sim = jaccard_similarity(set(user_a.topic_counts.keys()), set(user_b.topic_counts.keys()))

    # Content hash overlap
    comp.identical_content = len(user_a.content_hashes & user_b.content_hashes)
    total_hashes = len(user_a.content_hashes) + len(user_b.content_hashes)
    comp.content_sim = (comp.identical_content * 2) / max(1, total_hashes)

    # Vocabulary similarity
    a_vocab = {w for w, c in user_a.word_counts.items() if c >= 2 and len(w) > 4}
    b_vocab = {w for w, c in user_b.word_counts.items() if c >= 2 and len(w) > 4}
    comp.vocabulary_sim = jaccard_similarity(a_vocab, b_vocab)

    # Active days overlap
    comp.active_days_sim = jaccard_similarity(user_a.active_day_set, user_b.active_day_set)
    comp.overlap_days = len(user_a.active_day_set & user_b.active_day_set)

    # Coordinated posting
    if user_a.post_timestamps and user_b.post_timestamps:
        for ts_a in user_a.post_timestamps:
            for ts_b in user_b.post_timestamps:
                if abs(ts_a - ts_b) <= COORDINATED_TIMING_WINDOW_SECS:
                    comp.coordinated_posts += 1

    # Same timezone
    if sum(user_a.hour_histogram) >= 5 and sum(user_b.hour_histogram) >= 5:
        a_peak = user_a.hour_histogram.index(max(user_a.hour_histogram))
        b_peak = user_b.hour_histogram.index(max(user_b.hour_histogram))
        comp.same_timezone = abs(a_peak - b_peak) <= 2 or abs(a_peak - b_peak) >= 22

    # Sequential activity pattern (A stops posting, then B starts)
    # Only flag if at least one account had meaningful activity (7+ day span or 5+ active days)
    # Otherwise it's too early to determine rotation patterns
    if user_a.active_day_set and user_b.active_day_set:
        a_last = max(user_a.active_day_set)
        b_first = min(user_b.active_day_set)
        a_first = min(user_a.active_day_set)
        b_last = max(user_b.active_day_set)

        a_span = a_last - a_first
        b_span = b_last - b_first
        has_meaningful_activity = a_span >= 7 or b_span >= 7 or user_a.active_days >= 5 or user_b.active_days >= 5

        if has_meaningful_activity:
            # Check if B started around when A stopped (within 3 days)
            if 0 <= b_first - a_last <= 3 and comp.overlap_days <= 2:
                comp.sequential_activity = True
            # Or vice versa
            elif 0 <= a_first - b_last <= 3 and comp.overlap_days <= 2:
                comp.sequential_activity = True

    return comp


# =============================================================================
# GAMING DETECTION
# =============================================================================


def detect_registration_burst(
    referee: str,
    referred_at: int,
    referral_links: Dict[str, Tuple[str, int]],
    referrer: str,
) -> Tuple[bool, int]:
    """Check if referee was registered in a burst with other referees from same referrer."""
    burst_count = 0
    for other_referee, (other_referrer, other_referred_at) in referral_links.items():
        if other_referee == referee:
            continue
        if other_referrer != referrer:
            continue
        if abs(other_referred_at - referred_at) <= REGISTRATION_BURST_WINDOW_SECS:
            burst_count += 1
    return burst_count >= 2, burst_count


def analyze_referral_relationship(
    referrer_data: UserData,
    referee_data: UserData,
    referred_at: int,
    referral_links: Dict[str, Tuple[str, int]],
    posts_by_user: Dict[str, List[Dict]],
    cur,
    since_ts: int,
) -> ReferralRelationship:
    """Analyze a single referrer -> referee relationship for gaming."""
    rel = ReferralRelationship(
        referrer=referrer_data.owner,
        referee=referee_data.owner,
        referred_at=referred_at,
    )

    # Load interactions
    (
        rel.referee_votes_to_referrer,
        rel.referee_votes_from_referrer,
        rel.referee_replies_to_referrer,
        rel.referee_replies_from_referrer,
    ) = load_referral_interactions(cur, referrer_data.owner, referee_data.owner, since_ts)

    # Compute similarities
    sim = compute_referral_similarity(referrer_data, referee_data, posts_by_user)
    rel.timing_sim = sim["timing_sim"]
    rel.topic_sim = sim["topic_sim"]
    rel.content_sim = sim["content_sim"]
    rel.vocabulary_sim = sim["vocabulary_sim"]
    rel.active_days_sim = sim["active_days_sim"]
    rel.coordinated_posts = sim["coordinated_posts"]
    rel.identical_content = sim["identical_content"]
    rel.same_timezone = sim["same_timezone"]

    # Gaming indicators
    flags = []

    # 1. Registration burst
    is_burst, burst_count = detect_registration_burst(
        referee_data.owner, referred_at, referral_links, referrer_data.owner
    )
    rel.registration_burst = is_burst
    if is_burst:
        flags.append(f"BURST: Registered with {burst_count} others within 5min")

    # 2. Minimal activity (just enough for rewards)
    if referee_data.content_count > 0 and referee_data.content_count < MIN_ACTIVITY_FOR_LEGIT:
        if referee_data.active_days < MIN_ACTIVE_DAYS_FOR_LEGIT:
            rel.minimal_activity = True
            flags.append(f"MINIMAL: Only {referee_data.content_count} posts in {referee_data.active_days} days")

    # 3. One-way support (referrer supports referee but not vice versa)
    if rel.referee_votes_from_referrer >= 3 and rel.referee_votes_to_referrer == 0:
        rel.one_way_support = True
        flags.append(f"ONE_WAY: Referrer voted {rel.referee_votes_from_referrer}x, referee voted 0x")

    # 4. High timing similarity
    if rel.timing_sim >= 0.9:
        flags.append(f"TIMING: {rel.timing_sim:.0%} hour pattern match")

    # 5. Same timezone with high similarity
    if rel.same_timezone and rel.timing_sim >= 0.7:
        flags.append("TIMEZONE: Same timezone with matching activity pattern")

    # 6. Identical content
    if rel.identical_content >= 1:
        flags.append(f"CONTENT: {rel.identical_content} identical posts")

    # 8. High topic overlap with low activity
    if rel.topic_sim >= 0.8 and len(referee_data.topic_counts) <= 2:
        flags.append(f"TOPICS: {rel.topic_sim:.0%} overlap, only {len(referee_data.topic_counts)} topics")

    # 9. High vocabulary similarity
    if rel.vocabulary_sim >= 0.5:
        flags.append(f"VOCAB: {rel.vocabulary_sim:.0%} vocabulary overlap")

    # 10. Activity ratio check (referee should have reasonable activity relative to referrer)
    if referrer_data.content_count > 10:
        activity_ratio = referee_data.content_count / referrer_data.content_count
        if activity_ratio < 0.1 and referee_data.content_count < 3:
            flags.append(f"RATIO: Referee has only {activity_ratio:.0%} of referrer's activity")

    # 11. No engagement from community (only from referrer)
    if referee_data.votes_received_up > 0:
        from_referrer_ratio = rel.referee_votes_from_referrer / referee_data.votes_received_up
        if from_referrer_ratio >= 0.8 and referee_data.votes_received_up <= 5:
            flags.append(f"ISOLATED: {from_referrer_ratio:.0%} of votes from referrer")

    # 12. Account age vs activity mismatch
    if referee_data.age_days >= 7 and referee_data.content_count < 3:
        flags.append(f"DORMANT: {referee_data.age_days:.0f} days old, only {referee_data.content_count} posts")

    rel.flags = flags

    # Calculate gaming score (weighted sum of indicators)
    score = 0.0
    score += 0.15 * rel.timing_sim
    score += 0.10 * rel.topic_sim
    score += 0.20 * rel.content_sim  # Identical content is very suspicious
    score += 0.15 * rel.vocabulary_sim
    score += 0.05 * rel.active_days_sim
    score += 0.15 if rel.registration_burst else 0.0
    score += 0.10 if rel.minimal_activity else 0.0
    score += 0.05 if rel.one_way_support else 0.0
    score += min(0.05, rel.identical_content * 0.05)
    rel.gaming_score = min(1.0, score)

    # Classification
    if rel.gaming_score >= HIGH_SIMILARITY_THRESHOLD:
        rel.classification = "GAMING"
        rel.confidence = min(0.95, rel.gaming_score + 0.1)
        rel.recommendation = "REJECT"
    elif rel.gaming_score >= SUSPICIOUS_THRESHOLD or len(flags) >= 3:
        rel.classification = "SUSPICIOUS"
        rel.confidence = 0.6 + (rel.gaming_score * 0.2)
        rel.recommendation = "REVIEW"
    elif referee_data.content_count >= MIN_ACTIVITY_FOR_LEGIT and referee_data.active_days >= MIN_ACTIVE_DAYS_FOR_LEGIT:
        rel.classification = "LEGIT"
        rel.confidence = 0.8 + (0.15 * (1 - rel.gaming_score))
        rel.recommendation = "APPROVE"
    else:
        rel.classification = "INSUFFICIENT"
        rel.confidence = 0.5
        rel.recommendation = "REVIEW"

    return rel


# =============================================================================
# MARKDOWN GENERATION
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


def estimate_timezone(hour_histogram: List[int]) -> str:
    """Estimate timezone from activity pattern."""
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
    return f"UTC{offset:+d}"


def generate_user_profile(user: UserData, label: str = "") -> List[str]:
    """Generate detailed profile section for a user."""
    lines = []
    title = f"### {label}: {user.username}" if label else f"### {user.username}"
    lines.append(title)
    lines.append("")

    # Identity
    lines.append("**Identity**")
    lines.append(f"- Username: `{user.username}`")
    lines.append(f"- Address: `{user.owner}`")
    lines.append(f"- Level: {user.level}")
    lines.append(f"- Account age: {user.age_days:.1f} days")
    lines.append("")

    # Activity metrics
    lines.append("**Activity Metrics**")
    lines.append(f"- Posts: {user.posts}")
    lines.append(f"- Comments: {user.comments}")
    lines.append(f"- Total content: {user.content_count}")
    lines.append(f"- Active days: {user.active_days}")
    lines.append(f"- Votes given: +{user.upvotes_given} / -{user.downvotes_given}")
    lines.append(f"- Votes received: +{user.votes_received_up} / -{user.votes_received_down}")
    lines.append("")

    # Temporal
    lines.append("**Temporal**")
    lines.append(f"- First action: {format_ts(user.first_action_ts)}")
    lines.append(f"- Last action: {format_ts(user.last_action_ts)}")
    lines.append(f"- Estimated timezone: {estimate_timezone(user.hour_histogram)}")
    lines.append("")

    # Topics
    if user.topic_counts:
        lines.append("**Topics**")
        for topic, count in sorted(user.topic_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
            lines.append(f"- #{topic}: {count} posts")
        lines.append("")

    # Hour distribution (compact)
    if sum(user.hour_histogram) >= 3:
        peak_hours = sorted(range(24), key=lambda h: user.hour_histogram[h], reverse=True)[:3]
        peak_str = ", ".join(f"{h:02d}:00" for h in peak_hours)
        lines.append(f"**Peak hours (UTC)**: {peak_str}")
        lines.append("")

    return lines


def generate_referee_markdown(
    referee: UserData,
    referrer: UserData,
    rel: ReferralRelationship,
    siblings: List[UserData],
    sibling_comparisons: List[SiblingComparison],
    posts_by_user: Dict[str, List[Dict]],
    all_fingerprints: Dict[str, List[FingerprintData]],
    fp_freq: Optional[FingerprintFrequency] = None,
    pending_reward: float = 0.0,
) -> str:
    """Generate comprehensive markdown analysis for a single REFEREE with full context."""
    lines = []

    # ==========================================================================
    # HEADER
    # ==========================================================================
    lines.append(f"# Referee Analysis: {referee.username}")
    lines.append("")
    lines.append(f"**Generated**: {format_ts(int(time.time()))}")
    lines.append("")
    lines.append(f"**Pending Reward**: {pending_reward:.6f} MIRAGE")
    lines.append("")

    # ==========================================================================
    # SYSTEM EXPLANATION
    # ==========================================================================
    lines.append("## About This Analysis")
    lines.append("")
    lines.append(
        "The Mirage referral system rewards users for inviting others to the platform. "
        "Referrers earn MIRAGE tokens based on their referees' activity: 1 MIRAGE per active day for L1 (direct referrals), "
        "0.5 for L2, 0.25 for L3, 0.125 for L4, and 0.0625 for L5. Each referee can generate rewards for up to 10 active days. "
        "An active day is any day where the referee posts or comments."
    )
    lines.append("")
    lines.append(
        "This analysis exists to detect referral gaming, where a single person creates multiple accounts to farm rewards. "
        "Common gaming patterns include: creating fake referee accounts that mimic real user behavior, "
        "rotating between accounts to bypass the 10-day cap (one account stops posting, another starts), "
        "posting identical or very similar content across accounts, and registering multiple accounts in quick succession. "
        "The analysis compares each referee against their referrer and against 'siblings' (other accounts referred by the same person) "
        "to identify behavioral similarities that indicate shared ownership."
    )
    lines.append("")
    lines.append(
        "Key metrics examined: timing patterns (when accounts are active), topic overlap, vocabulary similarity, "
        "content duplication, device fingerprints (IP, browser, screen), and interaction patterns between accounts. "
        "High similarity across multiple metrics between a referee and their referrer or siblings is a strong indicator of gaming."
    )
    lines.append("")

    # ==========================================================================
    # VERDICT
    # ==========================================================================
    # ==========================================================================
    # THE REFEREE (SUBJECT OF ANALYSIS)
    # ==========================================================================
    lines.append("## The Referee (Subject)")
    lines.append("")
    lines.append("This is the account being evaluated for referral rewards.")
    lines.append("")

    # Identity box
    lines.append("### Identity")
    lines.append("")
    lines.append(f"| Field | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| Username | `{referee.username}` |")
    lines.append(f"| Full Address | `{referee.owner}` |")
    lines.append(f"| Level | {referee.level} |")
    lines.append(f"| Signed Up (via referral) | {format_ts(rel.referred_at)} |")
    lines.append(f"| Account Age | {referee.age_days:.1f} days |")
    secs_to_first_action = (
        (referee.first_action_ts - rel.referred_at) if referee.first_action_ts > 0 and rel.referred_at > 0 else 0
    )
    lines.append(f"| Time to First Action | {secs_to_first_action} seconds |")
    lines.append("")

    # Activity Summary
    lines.append("### Activity Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Posts (top-level) | {referee.posts} |")
    lines.append(f"| Comments (replies) | {referee.comments} |")
    lines.append(f"| Total Content | {referee.content_count} |")
    lines.append(f"| Active Days | {referee.active_days} |")
    if referee.active_days > 0:
        lines.append(f"| Posts per Active Day | {referee.content_count / referee.active_days:.2f} |")
    lines.append(f"| Upvotes Given | {referee.upvotes_given} |")
    lines.append(f"| Downvotes Given | {referee.downvotes_given} |")
    lines.append(f"| Upvotes Received | {referee.votes_received_up} |")
    lines.append(f"| Downvotes Received | {referee.votes_received_down} |")
    if referee.votes_received_up + referee.votes_received_down > 0:
        upvote_ratio = referee.votes_received_up / (referee.votes_received_up + referee.votes_received_down)
        lines.append(f"| Upvote Ratio | {upvote_ratio:.0%} |")
    lines.append(f"| First Action | {format_ts(referee.first_action_ts)} |")
    lines.append(f"| Last Action | {format_ts(referee.last_action_ts)} |")
    if referee.first_action_ts > 0 and referee.last_action_ts > 0:
        span_days = (referee.last_action_ts - referee.first_action_ts) / 86400
        lines.append(f"| Activity Span | {span_days:.1f} days |")
        if span_days > 0:
            density = referee.active_days / span_days
            lines.append(f"| Activity Density | {density:.0%} (active days / span) |")
    lines.append(f"| Unique Topics | {len(referee.topic_counts)} |")
    lines.append(f"| Estimated Timezone | {estimate_timezone(referee.hour_histogram)} |")
    lines.append("")

    # Network Analysis
    lines.append("### Network Analysis")
    lines.append("")
    out_degree = len(referee.reply_targets)
    in_degree = len(referee.reply_sources)
    total_connections = len(set(referee.reply_targets.keys()) | set(referee.reply_sources.keys()))
    reciprocal = set(referee.reply_targets.keys()) & set(referee.reply_sources.keys())
    reciprocity = len(reciprocal) / max(1, total_connections)

    # Echo chamber score
    total_interactions = sum(referee.reply_targets.values()) + sum(referee.reply_sources.values())
    if total_interactions > 0:
        top_3 = sorted(
            list(referee.reply_targets.items()) + list(referee.reply_sources.items()), key=lambda x: x[1], reverse=True
        )[:3]
        top_3_interactions = sum(c for _, c in top_3)
        echo_chamber = top_3_interactions / total_interactions
    else:
        echo_chamber = 0.0

    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Out-degree (users replied to) | {out_degree} |")
    lines.append(f"| In-degree (users who reply) | {in_degree} |")
    lines.append(f"| Total connections | {total_connections} |")
    lines.append(f"| Reciprocity | {reciprocity:.0%} |")
    lines.append(f"| Echo chamber score | {echo_chamber:.0%} |")
    lines.append(f"| Vote targets (unique users) | {len(referee.vote_targets)} |")
    lines.append(f"| Total votes to others | {sum(referee.vote_targets.values())} |")
    lines.append("")

    # Users this account replies to
    if referee.reply_targets:
        lines.append("### Users This Account Replies To")
        lines.append("")
        lines.append("| User | Count |")
        lines.append("|------|-------|")
        for target, count in sorted(referee.reply_targets.items(), key=lambda x: x[1], reverse=True)[:15]:
            target_username = target[:20]
            for u in [referrer] + siblings:
                if u.owner.lower() == target.lower():
                    target_username = u.username
                    break
            lines.append(f"| {target_username} | {count} |")
        lines.append("")

    # Users who reply to this account
    if referee.reply_sources:
        lines.append("### Users Who Reply To This Account")
        lines.append("")
        lines.append("| User | Count |")
        lines.append("|------|-------|")
        for source, count in sorted(referee.reply_sources.items(), key=lambda x: x[1], reverse=True)[:15]:
            source_username = source[:20]
            for u in [referrer] + siblings:
                if u.owner.lower() == source.lower():
                    source_username = u.username
                    break
            lines.append(f"| {source_username} | {count} |")
        lines.append("")

    # Vote targets
    if referee.vote_targets:
        lines.append("### Vote Targets (Who This Account Votes On)")
        lines.append("")
        lines.append("| User | Votes |")
        lines.append("|------|-------|")
        for target, count in sorted(referee.vote_targets.items(), key=lambda x: x[1], reverse=True)[:15]:
            target_username = target[:20]
            for u in [referrer] + siblings:
                if u.owner.lower() == target.lower():
                    target_username = u.username
                    break
            lines.append(f"| {target_username} | {count} |")
        lines.append("")

    # Content Analysis (comprehensive stats like classify_users.py)
    lines.append("### Content Analysis")
    lines.append("")

    # Compute post length stats
    post_lengths_words = []
    post_lengths_chars = []
    for post in referee.recent_posts:
        content = f"{post.get('title', '')} {post.get('content', '')}".strip()
        words = len(re.findall(r"[a-z]+", content.lower()))
        chars = len(content)
        post_lengths_words.append(words)
        post_lengths_chars.append(chars)

    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total Words Written | {referee.total_words} |")
    lines.append(f"| Unique Words (2+ uses) | {len([w for w, c in referee.word_counts.items() if c >= 2])} |")
    lines.append(f"| Total Unique Words | {len(referee.word_counts)} |")
    if referee.total_words > 0:
        vocab_diversity = len([w for w, c in referee.word_counts.items() if c >= 2]) / referee.total_words
        lines.append(f"| Vocabulary Diversity | {vocab_diversity:.4f} |")

    if post_lengths_words:
        avg_words = sum(post_lengths_words) / len(post_lengths_words)
        sorted_words = sorted(post_lengths_words)
        median_words = sorted_words[len(sorted_words) // 2]
        min_words = min(post_lengths_words)
        max_words = max(post_lengths_words)
        lines.append(f"| Words/Post (avg) | {avg_words:.1f} |")
        lines.append(f"| Words/Post (median) | {median_words} |")
        lines.append(f"| Words/Post (min) | {min_words} |")
        lines.append(f"| Words/Post (max) | {max_words} |")

        avg_chars = sum(post_lengths_chars) / len(post_lengths_chars)
        sorted_chars = sorted(post_lengths_chars)
        median_chars = sorted_chars[len(sorted_chars) // 2]
        min_chars = min(post_lengths_chars)
        max_chars = max(post_lengths_chars)
        lines.append(f"| Chars/Post (avg) | {avg_chars:.1f} |")
        lines.append(f"| Chars/Post (median) | {median_chars} |")
        lines.append(f"| Chars/Post (min) | {min_chars} |")
        lines.append(f"| Chars/Post (max) | {max_chars} |")
    lines.append("")

    # Temporal Analysis
    lines.append("### Temporal Analysis")
    lines.append("")

    if referee.post_timestamps:
        timestamps = sorted(referee.post_timestamps)
        gaps = []
        for i in range(1, len(timestamps)):
            gaps.append(timestamps[i] - timestamps[i - 1])

        if gaps:
            avg_gap = sum(gaps) / len(gaps)
            sorted_gaps = sorted(gaps)
            median_gap = sorted_gaps[len(sorted_gaps) // 2]
            min_gap = min(gaps)
            max_gap = max(gaps)

            # Detect bursts (10+ posts within 1 hour)
            burst_count = 0
            i = 0
            while i < len(timestamps):
                count_in_hour = 1
                j = i + 1
                while j < len(timestamps) and timestamps[j] - timestamps[i] <= 3600:
                    count_in_hour += 1
                    j += 1
                if count_in_hour >= 10:
                    burst_count += 1
                    i = j
                else:
                    i += 1

            # Dormant periods (gaps > 3 days)
            dormant_periods = []
            for idx, gap in enumerate(gaps):
                if gap > 3 * 86400:
                    dormant_periods.append(
                        {
                            "start": format_ts(timestamps[idx]),
                            "end": format_ts(timestamps[idx + 1]),
                            "days": round(gap / 86400, 1),
                        }
                    )

            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Avg Gap Between Posts | {avg_gap / 3600:.1f} hours |")
            lines.append(f"| Median Gap | {median_gap / 3600:.1f} hours |")
            lines.append(f"| Min Gap | {min_gap} seconds |")
            lines.append(f"| Max Gap | {max_gap / 86400:.1f} days |")
            lines.append(f"| Burst Periods (10+ posts/hour) | {burst_count} |")
            lines.append("")

            if dormant_periods:
                lines.append("**Dormant Periods (gaps > 3 days):**")
                lines.append("")
                for dp in dormant_periods[:5]:
                    lines.append(f"- {dp['start']} to {dp['end']} ({dp['days']} days)")
                lines.append("")
        else:
            lines.append("Only 1 post, no gap analysis possible.")
            lines.append("")
    else:
        lines.append("No posts to analyze.")
        lines.append("")

    # Hour-by-hour activity
    lines.append("### Hourly Activity Distribution (UTC)")
    lines.append("")
    lines.append("Activity by hour of day (UTC).")
    lines.append("")
    lines.append("```")
    total_hourly = sum(referee.hour_histogram)
    max_hourly = max(referee.hour_histogram) if referee.hour_histogram else 1
    for hour in range(24):
        count = referee.hour_histogram[hour]
        pct = (count / total_hourly * 100) if total_hourly > 0 else 0
        bar = "█" * int(30 * count / max(1, max_hourly))
        lines.append(f"{hour:02d}:00  {bar} {count} ({pct:.0f}%)")
    lines.append("```")
    lines.append("")

    # Day-of-week activity
    lines.append("### Day-of-Week Distribution")
    lines.append("")
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    lines.append("| Day | Actions | % |")
    lines.append("|-----|---------|---|")
    total_dow = sum(referee.day_of_week_histogram)
    for i, day_name in enumerate(day_names):
        count = referee.day_of_week_histogram[i]
        pct = (count / total_dow * 100) if total_dow > 0 else 0
        lines.append(f"| {day_name} | {count} | {pct:.0f}% |")
    lines.append("")

    # All active dates
    if referee.active_day_set:
        lines.append("### All Active Dates")
        lines.append("")
        sorted_days = sorted(referee.active_day_set)
        date_strs = [format_date(d * 86400) for d in sorted_days]
        lines.append(", ".join(date_strs))
        lines.append("")

        # Gaps analysis
        if len(sorted_days) > 1:
            gaps = [sorted_days[i + 1] - sorted_days[i] for i in range(len(sorted_days) - 1)]
            max_gap = max(gaps)
            avg_gap = sum(gaps) / len(gaps)
            lines.append(
                f"**Gap Analysis**: Longest gap between active days: {max_gap} days. Average gap: {avg_gap:.1f} days."
            )
            lines.append("")

    # Topics (all of them)
    if referee.topic_counts:
        lines.append("### All Topics Used")
        lines.append("")
        lines.append("| Topic | Posts | % of Total |")
        lines.append("|-------|-------|------------|")
        for topic, count in sorted(referee.topic_counts.items(), key=lambda x: x[1], reverse=True):
            pct = (count / referee.content_count * 100) if referee.content_count > 0 else 0
            lines.append(f"| #{topic} | {count} | {pct:.0f}% |")
        lines.append("")

    # Word frequency (top words, excluding common words)
    if referee.word_counts:
        common_words = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "as",
            "into",
            "through",
            "and",
            "but",
            "or",
            "nor",
            "so",
            "yet",
            "both",
            "either",
            "neither",
            "not",
            "only",
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
            "me",
            "him",
            "her",
            "us",
            "them",
            "my",
            "your",
            "his",
            "its",
            "our",
            "their",
            "mine",
            "yours",
            "ours",
            "theirs",
            "this",
            "that",
            "these",
            "those",
            "what",
            "which",
            "who",
            "whom",
            "whose",
            "if",
            "then",
            "else",
            "when",
            "where",
            "why",
            "how",
            "all",
            "each",
            "every",
            "just",
            "also",
            "very",
            "really",
            "more",
            "most",
            "some",
            "any",
            "no",
            "none",
            "about",
            "like",
            "can",
            "get",
            "think",
            "know",
            "want",
            "see",
            "come",
            "make",
            "take",
            "give",
            "use",
            "find",
            "tell",
            "ask",
            "work",
            "seem",
            "feel",
            "try",
            "leave",
            "call",
            "good",
            "new",
            "first",
            "last",
            "long",
            "great",
            "little",
            "own",
            "other",
            "old",
            "right",
            "big",
            "high",
            "different",
            "small",
            "large",
            "next",
            "early",
            "young",
            "important",
            "few",
            "public",
            "bad",
            "same",
            "able",
            "dont",
            "even",
            "much",
            "now",
            "still",
            "way",
            "need",
            "here",
            "there",
            "thing",
            "things",
            "people",
            "said",
            "one",
            "two",
        }
        filtered_words = [
            (w, c) for w, c in referee.word_counts.most_common(50) if w.lower() not in common_words and len(w) > 3
        ][:20]

        lines.append("### Top Words Used (excluding common words)")
        lines.append("")
        lines.append("| Word | Count |")
        lines.append("|------|-------|")
        for word, count in filtered_words:
            lines.append(f"| {word} | {count} |")
        lines.append("")

    # All posts within analysis window (limit to last 50)
    if referee.recent_posts:
        total_posts = len(referee.recent_posts)
        posts_to_show = referee.recent_posts[:50]
        if total_posts > 50:
            lines.append(f"### Posts ({total_posts} total, showing last 50)")
        else:
            lines.append(f"### All Posts ({total_posts} total)")
        lines.append("")
        for i, post in enumerate(posts_to_show, 1):
            topic = post.get("topic") or "none"
            ts = format_ts(post["created_at"])
            votes = f"+{post['upvotes']}/-{post['downvotes']}"
            txhash = post.get("txhash", "")
            title = post.get("title", "") or ""
            content = post.get("content", "") or ""
            full_text = f"{title} {content}".strip()
            word_count = len(re.findall(r"[a-z]+", full_text.lower()))
            char_count = len(full_text)

            if post.get("target"):
                lines.append(f"**{i}. [{ts}] #{topic} {votes} (comment) [{word_count} words, {char_count} chars]**")
                lines.append(f"Reply to: `{post.get('target', '')}`")
            else:
                display_title = title[:100] if title else "(untitled)"
                lines.append(f"**{i}. [{ts}] #{topic} {votes} [{word_count} words, {char_count} chars]**")
                lines.append(f"Title: {display_title}")

            if txhash:
                lines.append(f"TxHash: `{txhash}`")

            if content:
                lines.append("")
                lines.append(f"> {content}")
            lines.append("")

    # ==========================================================================
    # DEVICE FINGERPRINT ANALYSIS (Entropy-Weighted)
    # ==========================================================================
    referee_fps = all_fingerprints.get(referee.owner.lower(), [])
    referrer_fps = all_fingerprints.get(referrer.owner.lower(), [])
    sibling_fps = {s.owner.lower(): all_fingerprints.get(s.owner.lower(), []) for s in siblings}

    lines.append("---")
    lines.append("")
    lines.append("## Device Fingerprint Analysis")
    lines.append("")
    lines.append("Uses entropy-weighted comparison: rare attribute matches count more than common ones.")
    lines.append("A 78% score from matching rare attributes is more significant than matching common ones.")
    lines.append("")

    if not referee_fps:
        lines.append("*No fingerprint data available for this referee.*")
        lines.append("")
    else:
        lines.append("### Referee's Fingerprint History")
        lines.append("")
        lines.append("| # | First Seen | Last Seen | Count | IP Hash | Screen | Canvas | WebGL | Timezone |")
        lines.append("|---|------------|-----------|-------|---------|--------|--------|-------|----------|")
        for i, fp in enumerate(referee_fps, 1):
            first = format_date(fp.first_seen) if fp.first_seen else "-"
            last = format_date(fp.last_seen) if fp.last_seen else "-"
            screen = f"{fp.screen_width}x{fp.screen_height}" if fp.screen_width and fp.screen_height else "-"
            canvas = (fp.canvas_hash[:8] + "...") if fp.canvas_hash else "-"
            webgl = (fp.webgl_hash[:8] + "...") if fp.webgl_hash else "-"
            ip = (fp.ip_hash[:8] + "...") if fp.ip_hash else "-"
            tz = fp.timezone or "-"
            lines.append(f"| {i} | {first} | {last} | {fp.seen_count} | {ip} | {screen} | {canvas} | {webgl} | {tz} |")
        lines.append("")

        if len(referee_fps) > 1:
            lines.append(f"Multiple fingerprint records: {len(referee_fps)} distinct fingerprints on file.")
            lines.append("")

        # Show extended attributes if available
        if referee_fps[0].attributes:
            attr_count = len(referee_fps[0].attributes)
            lines.append(f"Extended attributes: {attr_count} categories collected")
            lines.append("")

    # Cross-account comparison using entropy-weighted scoring
    all_accounts = [
        ("Referee", referee.owner.lower(), referee.username),
        ("Referrer", referrer.owner.lower(), referrer.username),
    ] + [("Sibling", s.owner.lower(), s.username) for s in siblings]

    # Compute entropy-weighted fingerprint matches
    fp_comparisons: List[Tuple[str, str, str, str, FingerprintMatch]] = []

    if fp_freq and referee_fps:
        # Compare referee vs referrer
        if referrer_fps:
            match = compare_all_fingerprints(referee_fps, referrer_fps, fp_freq)
            if match.score > 0.1:
                fp_comparisons.append(("Referee", referee.username, "Referrer", referrer.username, match))

        # Compare referee vs each sibling
        for sib in siblings:
            sib_fps = all_fingerprints.get(sib.owner.lower(), [])
            if sib_fps:
                match = compare_all_fingerprints(referee_fps, sib_fps, fp_freq)
                if match.score > 0.1:
                    fp_comparisons.append(("Referee", referee.username, "Sibling", sib.username, match))

    # Sort by score descending
    fp_comparisons.sort(key=lambda x: x[4].score, reverse=True)

    if fp_comparisons:
        lines.append("### Cross-Account Fingerprint Comparison (Entropy-Weighted)")
        lines.append("")
        lines.append("Higher scores indicate more suspicious matches. Rare attribute matches contribute more weight.")
        lines.append("")
        lines.append("| Comparison | Score | Top Matching Attributes |")
        lines.append("|------------|-------|-------------------------|")

        for label_a, name_a, label_b, name_b, match in fp_comparisons:
            score_pct = f"{match.score:.0%}"
            if match.score >= 0.5:
                score_pct = f"**{score_pct}** CRITICAL"
            elif match.score >= 0.3:
                score_pct = f"**{score_pct}** HIGH"

            top_attrs = match.top_matches(3)
            attrs_str = ", ".join(f"{a}: {w:.1f}" for a, w in top_attrs) if top_attrs else "-"
            lines.append(f"| {name_a} vs {name_b} | {score_pct} | {attrs_str} |")

        lines.append("")

        # Show detailed breakdown for high matches
        high_matches = [c for c in fp_comparisons if c[4].score >= 0.3]
        if high_matches:
            lines.append("### Detailed Fingerprint Match Breakdown")
            lines.append("")
            for label_a, name_a, label_b, name_b, match in high_matches[:3]:
                lines.append(f"#### {name_a} vs {name_b}")
                lines.append("")
                lines.extend(format_match_table(match))
                lines.append("")

    else:
        # Fall back to simple hash comparison if no frequency data
        canvas_by_hash: Dict[str, List[str]] = defaultdict(list)
        ip_by_hash: Dict[str, List[str]] = defaultdict(list)
        webgl_by_hash: Dict[str, List[str]] = defaultdict(list)

        for label, addr, username in all_accounts:
            fps = all_fingerprints.get(addr, [])
            for fp in fps:
                name = f"{username} ({label})"
                if fp.canvas_hash:
                    canvas_by_hash[fp.canvas_hash].append(name)
                if fp.ip_hash:
                    ip_by_hash[fp.ip_hash].append(name)
                if fp.webgl_hash:
                    webgl_by_hash[fp.webgl_hash].append(name)

        fp_alerts = []
        for hash_val, users in canvas_by_hash.items():
            unique_users = list(set(users))
            if len(unique_users) > 1:
                fp_alerts.append(("CRITICAL", "Canvas Hash", hash_val[:12], unique_users))
        for hash_val, users in ip_by_hash.items():
            unique_users = list(set(users))
            if len(unique_users) > 1:
                fp_alerts.append(("MEDIUM", "IP Hash", hash_val[:12], unique_users))

        if fp_alerts:
            lines.append("### Cross-Account Fingerprint Matches")
            lines.append("")
            for severity, field, hash_preview, users in fp_alerts:
                users_str = ", ".join(sorted(set(users)))
                lines.append(f"- **{severity}**: {field} `{hash_preview}...` shared by: {users_str}")
            lines.append("")
        elif any(all_fingerprints.get(addr, []) for _, addr, _ in all_accounts):
            lines.append("### Cross-Account Comparison")
            lines.append("")
            lines.append("*No matching fingerprints detected between referee, referrer, and siblings.*")
            lines.append("")

    # ==========================================================================
    # THE REFERRER (WHO BENEFITS)
    # ==========================================================================
    lines.append("---")
    lines.append("")
    lines.append("## The Referrer (Beneficiary)")
    lines.append("")
    lines.append("This account referred the subject and receives rewards for their activity.")
    lines.append("")

    lines.append("### Identity")
    lines.append("")
    lines.append(f"| Field | Value |")
    lines.append(f"|-------|-------|")
    lines.append(f"| Username | `{referrer.username}` |")
    lines.append(f"| Full Address | `{referrer.owner}` |")
    lines.append(f"| Level | {referrer.level} |")
    lines.append(f"| Account Created | {format_ts(referrer.created_at)} |")
    lines.append(f"| Account Age | {referrer.age_days:.1f} days |")
    lines.append("")

    lines.append("### Activity Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Posts (top-level) | {referrer.posts} |")
    lines.append(f"| Comments (replies) | {referrer.comments} |")
    lines.append(f"| Total Content | {referrer.content_count} |")
    lines.append(f"| Active Days | {referrer.active_days} |")
    lines.append(f"| Upvotes Given | {referrer.upvotes_given} |")
    lines.append(f"| Downvotes Given | {referrer.downvotes_given} |")
    lines.append(f"| Upvotes Received | {referrer.votes_received_up} |")
    lines.append(f"| Downvotes Received | {referrer.votes_received_down} |")
    lines.append(f"| First Action | {format_ts(referrer.first_action_ts)} |")
    lines.append(f"| Last Action | {format_ts(referrer.last_action_ts)} |")
    lines.append(f"| Unique Topics | {len(referrer.topic_counts)} |")
    lines.append(f"| Total Words Written | {referrer.total_words} |")
    lines.append(f"| Estimated Timezone | {estimate_timezone(referrer.hour_histogram)} |")
    lines.append("")

    # Referrer's hourly activity
    lines.append("### Referrer's Hourly Activity (UTC)")
    lines.append("")
    lines.append("```")
    total_hourly_ref = sum(referrer.hour_histogram)
    max_hourly_ref = max(referrer.hour_histogram) if referrer.hour_histogram else 1
    for hour in range(24):
        count = referrer.hour_histogram[hour]
        pct = (count / total_hourly_ref * 100) if total_hourly_ref > 0 else 0
        bar = "█" * int(30 * count / max(1, max_hourly_ref))
        lines.append(f"{hour:02d}:00  {bar} {count} ({pct:.0f}%)")
    lines.append("```")
    lines.append("")

    # Referrer's topics
    if referrer.topic_counts:
        lines.append("### Referrer's Topics")
        lines.append("")
        lines.append("| Topic | Posts |")
        lines.append("|-------|-------|")
        for topic, count in sorted(referrer.topic_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
            shared = " (shared)" if topic in referee.topic_counts else ""
            lines.append(f"| #{topic}{shared} | {count} |")
        lines.append("")

    # Relationship between referee and referrer
    lines.append("### Similarity Metrics: Referee vs Referrer")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Timing Similarity (hour pattern) | {rel.timing_sim:.1%} |")
    lines.append(f"| Topic Overlap | {rel.topic_sim:.1%} |")
    lines.append(f"| Vocabulary Overlap | {rel.vocabulary_sim:.1%} |")
    lines.append(f"| Content Match | {rel.content_sim:.1%} |")
    lines.append(f"| Active Days Overlap | {rel.active_days_sim:.1%} |")
    lines.append(f"| Identical Posts Count | {rel.identical_content} |")
    lines.append(f"| Same Timezone | {'Yes' if rel.same_timezone else 'No'} |")
    lines.append(f"| Coordinated Posts (within 60s) | {rel.coordinated_posts} |")
    lines.append("")

    # Shared topics detail
    shared_topics = set(referee.topic_counts.keys()) & set(referrer.topic_counts.keys())
    if shared_topics:
        lines.append("### Shared Topics Detail")
        lines.append("")
        lines.append("| Topic | Referee Posts | Referrer Posts |")
        lines.append("|-------|---------------|----------------|")
        for topic in sorted(shared_topics):
            lines.append(f"| #{topic} | {referee.topic_counts.get(topic, 0)} | {referrer.topic_counts.get(topic, 0)} |")
        lines.append("")

    # Shared vocabulary
    ref_vocab = {w for w, c in referee.word_counts.items() if c >= 2 and len(w) > 4}
    rer_vocab = {w for w, c in referrer.word_counts.items() if c >= 2 and len(w) > 4}
    shared_vocab = ref_vocab & rer_vocab
    if shared_vocab:
        lines.append("### Shared Vocabulary (words used 2+ times by both)")
        lines.append("")
        lines.append(", ".join(sorted(shared_vocab)[:50]))
        if len(shared_vocab) > 50:
            lines.append(f"... and {len(shared_vocab) - 50} more")
        lines.append("")

    lines.append("### Direct Interaction Between Referee and Referrer")
    lines.append("")
    lines.append(f"| Direction | Votes | Replies |")
    lines.append(f"|-----------|-------|---------|")
    lines.append(f"| Referee -> Referrer | {rel.referee_votes_to_referrer} | {rel.referee_replies_to_referrer} |")
    lines.append(f"| Referrer -> Referee | {rel.referee_votes_from_referrer} | {rel.referee_replies_from_referrer} |")
    lines.append(
        f"| **Total** | {rel.referee_votes_to_referrer + rel.referee_votes_from_referrer} | {rel.referee_replies_to_referrer + rel.referee_replies_from_referrer} |"
    )
    lines.append("")
    lines.append("")

    # ==========================================================================
    # SIBLINGS (OTHER REFEREES FROM SAME REFERRER)
    # ==========================================================================
    if siblings:
        lines.append("---")
        lines.append("")
        lines.append("## Siblings (Other Referees of Same Referrer)")
        lines.append("")
        lines.append(
            f"The referrer `{referrer.username}` has referred **{len(siblings) + 1}** accounts total (including this one)."
        )
        lines.append(
            "If these accounts show high similarity, they may be the same person running multiple accounts to farm rewards."
        )
        lines.append("After reaching the 10-day cap on one account, a fraudster would switch to another sibling.")
        lines.append("")

        # Siblings overview table
        lines.append("### All Siblings Overview")
        lines.append("")
        lines.append("| # | Username | Full Address | Posts | Comments | Days | First | Last | Timezone |")
        lines.append("|---|----------|--------------|-------|----------|------|-------|------|----------|")
        lines.append(
            f"| **THIS** | **{referee.username}** | `{referee.owner}` | {referee.posts} | {referee.comments} | {referee.active_days} | {format_date(referee.first_action_ts)} | {format_date(referee.last_action_ts)} | {estimate_timezone(referee.hour_histogram)} |"
        )
        for i, sib in enumerate(siblings, 1):
            lines.append(
                f"| {i} | {sib.username} | `{sib.owner}` | {sib.posts} | {sib.comments} | {sib.active_days} | {format_date(sib.first_action_ts)} | {format_date(sib.last_action_ts)} | {estimate_timezone(sib.hour_histogram)} |"
            )
        lines.append("")

        # Comparisons with THIS referee
        my_comparisons = [c for c in sibling_comparisons if c.user_a == referee.owner or c.user_b == referee.owner]

        if my_comparisons:
            lines.append("### Detailed Comparison: This Referee vs Each Sibling")
            lines.append("")
            lines.append(
                "| Sibling | Timing Sim | Topic Sim | Vocab Sim | Content Sim | Days Overlap | Coordinated Posts | Sequential | Identical Content |"
            )
            lines.append(
                "|---------|------------|-----------|-----------|-------------|--------------|-------------------|------------|-------------------|"
            )

            for comp in my_comparisons:
                other_username = comp.username_b if comp.user_a == referee.owner else comp.username_a
                seq = "**YES**" if comp.sequential_activity else "-"
                ident = f"**{comp.identical_content}**" if comp.identical_content > 0 else "0"
                lines.append(
                    f"| {other_username} | {comp.timing_sim:.1%} | {comp.topic_sim:.1%} | {comp.vocabulary_sim:.1%} | {comp.content_sim:.1%} | {comp.overlap_days} | {comp.coordinated_posts} | {seq} | {ident} |"
                )
            lines.append("")

            # Detailed sibling profiles
            lines.append("### Individual Sibling Profiles")
            lines.append("")

            for sib in siblings:
                lines.append(f"#### Sibling: {sib.username}")
                lines.append("")
                lines.append(f"| Field | Value |")
                lines.append(f"|-------|-------|")
                lines.append(f"| Username | `{sib.username}` |")
                lines.append(f"| Full Address | `{sib.owner}` |")
                lines.append(f"| Level | {sib.level} |")
                lines.append(f"| Posts | {sib.posts} |")
                lines.append(f"| Comments | {sib.comments} |")
                lines.append(f"| Active Days | {sib.active_days} |")
                lines.append(f"| First Action | {format_ts(sib.first_action_ts)} |")
                lines.append(f"| Last Action | {format_ts(sib.last_action_ts)} |")
                lines.append(f"| Timezone | {estimate_timezone(sib.hour_histogram)} |")
                lines.append(f"| Topics | {', '.join(f'#{t}' for t in list(sib.topic_counts.keys())[:10])} |")
                lines.append("")

                # Quick comparison with this referee
                comp = next((c for c in my_comparisons if c.user_a == sib.owner or c.user_b == sib.owner), None)
                if comp:
                    lines.append(f"**Comparison with THIS referee ({referee.username})**:")
                    lines.append(f"- Timing similarity: {comp.timing_sim:.1%}")
                    lines.append(f"- Vocabulary similarity: {comp.vocabulary_sim:.1%}")
                    lines.append(f"- Topic overlap: {comp.topic_sim:.1%}")
                    lines.append(f"- Active days overlap: {comp.overlap_days} days")
                    lines.append(f"- Same timezone: {'Yes' if comp.same_timezone else 'No'}")
                    lines.append(
                        f"- Sequential activity: {'**YES - SUSPICIOUS**' if comp.sequential_activity else 'No'}"
                    )
                    lines.append(f"- Identical content: {comp.identical_content}")
                    lines.append("")

                    # Shared words between this referee and sibling
                    sib_vocab = {w for w, c in sib.word_counts.items() if c >= 2 and len(w) > 4}
                    ref_vocab = {w for w, c in referee.word_counts.items() if c >= 2 and len(w) > 4}
                    shared = ref_vocab & sib_vocab
                    if shared:
                        lines.append(f"**Shared vocabulary**: {', '.join(sorted(shared)[:20])}")
                        if len(shared) > 20:
                            lines.append(f"... and {len(shared) - 20} more shared words")
                        lines.append("")

            # Notable sibling patterns
            notable = [
                c
                for c in my_comparisons
                if c.sequential_activity
                or c.identical_content > 0
                or (c.timing_sim >= 0.85 and c.vocabulary_sim >= 0.3)
            ]
            if notable:
                lines.append("### Notable Sibling Patterns")
                lines.append("")
                for comp in notable:
                    other_username = comp.username_b if comp.user_a == referee.owner else comp.username_a
                    other_addr = comp.user_b if comp.user_a == referee.owner else comp.user_a
                    lines.append(f"#### With `{other_username}` (`{other_addr}`)")
                    lines.append("")
                    if comp.sequential_activity:
                        lines.append(f"- Sequential activity: Yes (one stopped when other started)")
                    if comp.identical_content > 0:
                        lines.append(f"- Identical content: {comp.identical_content} posts")
                    if comp.timing_sim >= 0.85:
                        lines.append(f"- Timing similarity: {comp.timing_sim:.1%}")
                    if comp.vocabulary_sim >= 0.3:
                        lines.append(f"- Vocabulary overlap: {comp.vocabulary_sim:.1%}")
                    if comp.same_timezone:
                        lines.append(f"- Same timezone: Yes")
                    lines.append("")

    # ==========================================================================
    # TIMELINE
    # ==========================================================================
    lines.append("---")
    lines.append("")
    lines.append("## Activity Timeline")
    lines.append("")

    all_days: Set[int] = set()
    all_days.update(referee.active_day_set)
    all_days.update(referrer.active_day_set)
    for sib in siblings:
        all_days.update(sib.active_day_set)

    if all_days:
        min_day = min(all_days)
        max_day = max(all_days)

        lines.append("```")
        lines.append(
            f"Period: {format_date(min_day * 86400)} to {format_date(max_day * 86400)} ({max_day - min_day + 1} days)"
        )
        lines.append("")

        # Build header
        all_users = [referee, referrer] + siblings[:8]
        header = "Date       |"
        for u in all_users:
            label = u.username[:8]
            if u.owner == referee.owner:
                label = ">>THIS<<"
            elif u.owner == referrer.owner:
                label = "REFERRER"
            header += f" {label:8} |"
        lines.append(header)
        lines.append("-" * len(header))

        # Show full timeline (up to 90 days)
        for day in range(max(min_day, max_day - 90), max_day + 1):
            date_str = format_date(day * 86400)[:10]
            row = f"{date_str} |"
            for u in all_users:
                active = "   ##   " if day in u.active_day_set else "        "
                row += f" {active} |"
            lines.append(row)

        lines.append("```")
        lines.append("")
        lines.append("Legend: `##` = active on this day")
        lines.append("")

        # Timeline statistics
        lines.append("### Timeline Statistics")
        lines.append("")
        lines.append(f"| Account | First Active | Last Active | Active Days | Span | Density |")
        lines.append(f"|---------|--------------|-------------|-------------|------|---------|")
        for u in all_users:
            label = u.username
            if u.owner == referee.owner:
                label = f"**{u.username}** (THIS)"
            elif u.owner == referrer.owner:
                label = f"{u.username} (REFERRER)"
            first = format_date(u.first_action_ts) if u.first_action_ts > 0 else "N/A"
            last = format_date(u.last_action_ts) if u.last_action_ts > 0 else "N/A"
            if u.first_action_ts > 0 and u.last_action_ts > 0:
                span = (u.last_action_ts - u.first_action_ts) / 86400
                density = (u.active_days / span * 100) if span > 0 else 0
                lines.append(f"| {label} | {first} | {last} | {u.active_days} | {span:.0f}d | {density:.0f}% |")
            else:
                lines.append(f"| {label} | {first} | {last} | {u.active_days} | - | - |")
        lines.append("")
    return "\n".join(lines)


# =============================================================================
# DATABASE SAVE
# =============================================================================


def save_analysis_to_db(cur, relationships: List[ReferralRelationship], analysis_ts: int):
    """Save analysis results to referral_analysis table."""
    for rel in relationships:
        cur.execute(
            """
            INSERT INTO referral_analysis 
            (referee_address, referrer_address, analysis_date, classification, confidence, 
             similarity_to_referrer, flags, recommendation)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (referee_address, analysis_date) DO UPDATE SET
                classification = EXCLUDED.classification,
                confidence = EXCLUDED.confidence,
                similarity_to_referrer = EXCLUDED.similarity_to_referrer,
                flags = EXCLUDED.flags,
                recommendation = EXCLUDED.recommendation
        """,
            (
                rel.referee,
                rel.referrer,
                analysis_ts,
                rel.classification,
                rel.confidence,
                rel.gaming_score,
                rel.flags,
                rel.recommendation,
            ),
        )


# =============================================================================
# MAIN
# =============================================================================


def build_referrer_analysis(
    referrer_addr: str,
    referee_list: List[str],
    users: Dict[str, UserData],
    referral_links: Dict[str, Tuple[str, int]],
    posts_by_user: Dict[str, List[Dict]],
    cur,
    since_ts: int,
) -> ReferrerAnalysis:
    """Build complete analysis for a referrer and all their referees."""

    referrer_data = users.get(referrer_addr)
    if not referrer_data:
        referrer_data = UserData(owner=referrer_addr, username=referrer_addr[:20])

    analysis = ReferrerAnalysis(
        referrer=referrer_addr,
        referrer_username=referrer_data.username,
        referrer_data=referrer_data,
        referees=referee_list,
        total_referees=len(referee_list),
    )

    # Analyze each referee
    for referee_addr in referee_list:
        referee_data = users.get(referee_addr)
        if not referee_data:
            referee_data = UserData(owner=referee_addr, username=referee_addr[:20])

        analysis.referee_data[referee_addr] = referee_data

        _, referred_at = referral_links.get(referee_addr, (referrer_addr, 0))

        rel = analyze_referral_relationship(
            referrer_data,
            referee_data,
            referred_at,
            referral_links,
            posts_by_user,
            cur,
            since_ts,
        )
        analysis.referee_relationships[referee_addr] = rel

        if rel.classification == "GAMING":
            analysis.gaming_count += 1
        elif rel.classification == "SUSPICIOUS":
            analysis.suspicious_count += 1
        elif rel.classification == "LEGIT":
            analysis.legit_count += 1
        else:
            analysis.insufficient_count += 1

    # Compare all siblings to each other
    for i, addr_a in enumerate(referee_list):
        for addr_b in referee_list[i + 1 :]:
            user_a = analysis.referee_data.get(addr_a)
            user_b = analysis.referee_data.get(addr_b)
            if user_a and user_b:
                comp = compare_siblings(user_a, user_b)
                analysis.sibling_comparisons.append(comp)

    # Determine overall risk
    overall_flags = []

    # Check for high sibling similarity
    high_sim_pairs = 0
    sequential_pairs = 0
    for comp in analysis.sibling_comparisons:
        if comp.timing_sim >= 0.9 and comp.vocabulary_sim >= 0.5:
            high_sim_pairs += 1
            overall_flags.append(f"High similarity between {comp.username_a} and {comp.username_b}")
        if comp.sequential_activity:
            sequential_pairs += 1
            overall_flags.append(f"Sequential activity pattern: {comp.username_a} -> {comp.username_b}")
        if comp.identical_content > 0:
            overall_flags.append(f"Identical content between {comp.username_a} and {comp.username_b}")

    # Check for registration bursts
    if analysis.total_referees >= 3:
        referred_times = [referral_links.get(addr, (None, 0))[1] for addr in referee_list]
        referred_times = [t for t in referred_times if t > 0]
        if referred_times:
            referred_times.sort()
            for i in range(len(referred_times) - 2):
                if referred_times[i + 2] - referred_times[i] <= 600:  # 3 in 10 min
                    overall_flags.append(f"Registration burst: 3+ referees within 10 minutes")
                    break

    # Determine overall risk level
    if analysis.gaming_count >= 2 or high_sim_pairs >= 2 or sequential_pairs >= 2:
        analysis.overall_risk = "CRITICAL"
    elif analysis.gaming_count >= 1 or high_sim_pairs >= 1 or sequential_pairs >= 1:
        analysis.overall_risk = "HIGH"
    elif analysis.suspicious_count >= 2 or len(overall_flags) >= 2:
        analysis.overall_risk = "MEDIUM"
    else:
        analysis.overall_risk = "LOW"

    analysis.overall_flags = overall_flags

    return analysis


# =============================================================================
# CHATGPT ANALYSIS
# =============================================================================

CHATGPT_SYSTEM_PROMPT = """You are a fraud detection expert analyzing referral program data for a blockchain social media platform called Mirage.

The referral system works as follows:
- Users can refer others and earn 1 MIRAGE token per day that their referral is active (posts or comments)
- Maximum reward is capped at 10 MIRAGE per referral (10 active days)
- Multi-level rewards exist (L2=0.5x, L3=0.25x, etc.)

Common gaming patterns to look for:
1. SELF-REFERRAL: User creates multiple accounts and refers themselves to farm rewards
2. ACCOUNT ROTATION: After hitting 10-day cap on one account, switches to another referred account
3. COORDINATED ACTIVITY: Multiple accounts posting at the same times, same topics, same writing style
4. MINIMAL EFFORT: Just enough activity to trigger rewards, no genuine engagement
5. IDENTICAL CONTENT: Copy-pasting content across accounts
6. SAME DEVICE: Multiple accounts from same IP, browser fingerprint, or device

Signs of a REAL user:
- Organic posting patterns (varied times, topics)
- Genuine engagement (replies, discussions)
- Unique writing style and vocabulary
- Activity beyond minimum required
- Different devices/fingerprints from referrer

Your task: Analyze the provided user data and determine if this is a REAL user or a GAMING/FAKE account.
Be decisive. Provide clear reasoning based on the data."""

CHATGPT_USER_PROMPT = """Analyze this referral account and determine: Is this a REAL user or someone GAMING the referral system?

{markdown_content}

---

Based on ALL the data above, provide your verdict in YAML format inside a code block:

```yaml
verdict: GAMING  # One of: REAL USER, LIKELY REAL, SUSPICIOUS, LIKELY GAMING, GAMING
confidence: HIGH  # One of: HIGH, MEDIUM, LOW
recommendation: deny  # One of: approve, deny, review
reasoning: |
  2-3 sentences explaining your conclusion. This should be a clear,
  decisive explanation of why you reached this verdict.
```

Be decisive. The reasoning field should explain your conclusion clearly."""


def analyze_with_chatgpt(markdown_content: str) -> str:
    """Send the analysis to ChatGPT and get a verdict."""
    if not CHATGPT_API_KEY:
        return "\n\n---\n\n## AI Analysis\n\n*ChatGPT analysis skipped: No API key configured.*\n"

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
                {"role": "user", "content": CHATGPT_USER_PROMPT.format(markdown_content=markdown_content)},
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
            return f"\n\n---\n\n{ai_response}\n"

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        return f"\n\n---\n\n## AI Analysis\n\n*ChatGPT analysis failed: {e.code} - {error_body}*\n"
    except Exception as e:
        return f"\n\n---\n\n## AI Analysis\n\n*ChatGPT analysis failed: {e}*\n"


def main():
    parser = argparse.ArgumentParser(description="Analyze referral chains for gaming behavior")
    parser.add_argument("--output-dir", "-o", default=OUTPUT_DIR, help=f"Output directory (default: {OUTPUT_DIR})")
    parser.add_argument("--save-db", action="store_true", help="Save results to referral_analysis table")
    parser.add_argument("--referrer", help="Only analyze this specific referrer (address or username)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    now_ts = int(time.time())
    since_ts = now_ts - LOOKBACK_DAYS * 86400

    print("=" * 60)
    print("Referral Gaming Analysis (Per-Referrer)")
    print("=" * 60)
    print(f"Lookback: {LOOKBACK_DAYS} days")
    print(f"Output: {output_dir}")
    print("")

    started = time.time()

    with connect() as conn:
        with conn.cursor() as cur:
            # First load referral metadata to determine relevant addresses
            print("Loading referral metadata...")
            referral_links = load_referral_links(cur)
            referral_tree = load_referral_tree(cur)
            pending_rewards = load_pending_rewards(cur)
            total_pending_by_referee = load_total_pending_by_referee(cur)
            payout_history = load_payout_history()

            print(f"  Referral links: {len(referral_links)}")
            print(f"  Referrers: {len(referral_tree)}")
            print(f"  Referrers with pending rewards: {len(pending_rewards)}")
            print(f"  Referees with pending rewards: {len(total_pending_by_referee)}")

            if not referral_links:
                print("No referral links found. Exiting.")
                return

            # Filter to only referrers who have referees with pending rewards
            referrers_with_pending_referees = {
                addr: refs
                for addr, refs in referral_tree.items()
                if any(total_pending_by_referee.get(ref.lower(), 0) > 0 for ref in refs)
            }
            if not referrers_with_pending_referees and not args.referrer:
                print("No referees with pending rewards. Nothing to analyze.")
                return
            if referrers_with_pending_referees:
                referral_tree = referrers_with_pending_referees
                print(f"Filtered to {len(referral_tree)} referrers with pending referees")

            # Filter to specific referrer if requested
            if args.referrer:
                referrer_input = args.referrer.lower()
                matched_addr = referrer_input if referrer_input in referral_tree else None
                if not matched_addr:
                    # Try by username - need to load profiles to check
                    cur.execute(
                        "SELECT LOWER(owner) FROM profiles WHERE LOWER(username) = %s",
                        (referrer_input,),
                    )
                    row = cur.fetchone()
                    if row and row[0] in referral_tree:
                        matched_addr = row[0]

                if not matched_addr:
                    print(f"Referrer '{args.referrer}' not found.")
                    return
                referral_tree = {matched_addr: referral_tree[matched_addr]}

            # Determine relevant addresses (referrers + their referees)
            relevant_addresses: Set[str] = set()
            for referrer_addr, referee_list in referral_tree.items():
                relevant_addresses.add(referrer_addr.lower())
                for referee_addr in referee_list:
                    relevant_addresses.add(referee_addr.lower())

            print(f"Loading data for {len(relevant_addresses)} relevant users...")
            users, posts_by_hash, posts_by_user = load_relevant_data(cur, since_ts, relevant_addresses)
            all_fingerprints = load_fingerprints(cur, relevant_addresses)
            print(f"  Loaded {len(users)} user profiles")

            # Load fingerprint frequencies for entropy-weighted comparison
            print("Loading fingerprint frequencies...")
            fp_freq = load_fingerprint_frequencies(cur)
            print(f"  Fingerprint frequencies: {fp_freq.total_users} users, {len(fp_freq.counts)} attributes")

            # Build referrer analyses (for sibling comparisons)
            print("Analyzing referral chains...")
            referrer_analyses: Dict[str, ReferrerAnalysis] = {}
            all_relationships: List[ReferralRelationship] = []

            for referrer_addr, referee_list in referral_tree.items():
                analysis = build_referrer_analysis(
                    referrer_addr,
                    referee_list,
                    users,
                    referral_links,
                    posts_by_user,
                    cur,
                    since_ts,
                )
                referrer_analyses[referrer_addr] = analysis
                all_relationships.extend(analysis.referee_relationships.values())

            print(f"  Analyzed {len(referrer_analyses)} referrers")
            print(f"  Total referees: {len(all_relationships)}")
            print("")

            # Prompt for ChatGPT API key if not set
            global CHATGPT_API_KEY
            if not CHATGPT_API_KEY:
                print("=" * 60)
                print("Enter ChatGPT API key for AI analysis (or press Enter to skip):")
                print("=" * 60)
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

            # Generate per-REFEREE markdown files (with sibling context)
            print("Generating per-referee analysis files...")

            total_gaming = 0
            total_suspicious = 0
            total_legit = 0
            total_insufficient = 0
            flagged_referees = []

            for referrer_addr, analysis in referrer_analyses.items():
                referrer_data = analysis.referrer_data or UserData(owner=referrer_addr, username=referrer_addr[:20])

                for referee_addr in analysis.referees:
                    referee_data = analysis.referee_data.get(referee_addr)
                    rel = analysis.referee_relationships.get(referee_addr)
                    if not referee_data or not rel:
                        continue

                    # Get total pending reward for this referee (across all beneficiary levels)
                    referee_total_pending = total_pending_by_referee.get(referee_addr.lower(), 0.0)

                    # Skip referees with no pending reward and delete old files
                    safe_name = re.sub(r"[^\w\-]", "_", referee_data.username or referee_addr[:20])[:50]
                    filepath = output_dir / f"{safe_name}.md"

                    if referee_total_pending <= 0:
                        if filepath.exists():
                            filepath.unlink()
                            print(f"    Deleted {referee_data.username}: no pending reward")
                        else:
                            print(f"    Skipping {referee_data.username}: no pending reward")
                        continue

                    # Get siblings (other referees from same referrer, excluding this one)
                    siblings = [
                        analysis.referee_data[addr]
                        for addr in analysis.referees
                        if addr != referee_addr and addr in analysis.referee_data
                    ]

                    # Generate the analysis
                    md = generate_referee_markdown(
                        referee_data,
                        referrer_data,
                        rel,
                        siblings,
                        analysis.sibling_comparisons,
                        posts_by_user,
                        all_fingerprints,
                        fp_freq=fp_freq,
                        pending_reward=referee_total_pending,
                    )

                    # Get ChatGPT analysis
                    print(f"    Analyzing {referee_data.username} with ChatGPT...")
                    ai_analysis = analyze_with_chatgpt(md)
                    md += ai_analysis

                    filepath.write_text(md, encoding="utf-8")

                    if rel.classification == "GAMING":
                        total_gaming += 1
                        flagged_referees.append((referee_data.username, rel.classification, rel.gaming_score))
                    elif rel.classification == "SUSPICIOUS":
                        total_suspicious += 1
                        flagged_referees.append((referee_data.username, rel.classification, rel.gaming_score))
                    elif rel.classification == "LEGIT":
                        total_legit += 1
                    else:
                        total_insufficient += 1

            # Save to database if requested
            if args.save_db:
                print("Saving to database...")
                save_analysis_to_db(cur, all_relationships, now_ts)
                print(f"  Saved {len(all_relationships)} analysis records")

    elapsed = time.time() - started
    print("")
    print("=" * 60)
    print(f"Completed in {elapsed:.1f}s")
    print("")
    print(f"Referee Analysis Summary:")
    print(f"  Total referees analyzed: {len(all_relationships)}")
    print(f"  Gaming: {total_gaming}")
    print(f"  Suspicious: {total_suspicious}")
    print(f"  Legit: {total_legit}")
    print(f"  Insufficient: {total_insufficient}")
    print("")
    print(f"Output: {output_dir}")

    if flagged_referees:
        print("")
        print("Flagged Referees (require review):")
        for username, classification, score in sorted(flagged_referees, key=lambda x: x[2], reverse=True)[:15]:
            print(f"  {username}: {classification} (score: {score:.2f})")


if __name__ == "__main__":
    main()
