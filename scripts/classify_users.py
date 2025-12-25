#!/usr/bin/env python3
"""
Comprehensive Mirage User Classification and Sockpuppet Detection.

Generates per-user markdown analysis files with full analytics for human/LLM review.

Usage:
    python scripts/classify_users.py
    python scripts/classify_users.py --output-dir /path/to/output
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# =============================================================================
# CONFIGURATION - Edit these directly, no env vars needed
# =============================================================================

DB_URL = "postgresql://mirage:mirage@127.0.0.1:5432/mirage"
OUTPUT_DIR = "/tmp/mirage-classification"
LOOKBACK_DAYS = 30

# Classification thresholds
MIN_CONTENT_FOR_REAL = 5
MIN_ACTIVE_DAYS_FOR_REAL = 3
MIN_TOPICS_FOR_REAL = 2

# Sockpuppet detection
SIMILARITY_THRESHOLD = 0.6  # Flag as potential sockpuppet if above this
COORDINATED_TIMING_WINDOW_SECS = 60  # Posts within this window are "coordinated"
HIGH_SIMILARITY_THRESHOLD = 0.75  # Definitely suspicious

# Limits
MAX_POSTS_PER_USER = 50  # In markdown output
MAX_SIMILAR_USERS = 10  # Top N similar users to show

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
    votes_given: int = 0
    votes_received_up: int = 0
    votes_received_down: int = 0
    deleted_posts: int = 0

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

    # Interactions
    reply_targets: Dict[str, int] = field(default_factory=dict)  # who this user replies to
    reply_sources: Dict[str, int] = field(default_factory=dict)  # who replies to this user
    vote_targets: Dict[str, int] = field(default_factory=dict)  # who this user votes on
    voted_posts: Set[str] = field(default_factory=set)  # post IDs voted on

    # Content
    word_counts: Counter = field(default_factory=Counter)
    content_hashes: Set[str] = field(default_factory=set)
    avg_post_length: float = 0.0
    total_words: int = 0

    # Raw posts for output
    recent_posts: List[Dict] = field(default_factory=list)
    recent_votes: List[Dict] = field(default_factory=list)

    @property
    def content_count(self) -> int:
        return self.posts + self.comments

    @property
    def age_days(self) -> float:
        # Use created_at if it's a real value (not the default 1730419200)
        # Otherwise fall back to first_action_ts
        DEFAULT_CREATED_AT = 1730419200  # Nov 1, 2024 - chain init default
        if self.created_at > 0 and self.created_at != DEFAULT_CREATED_AT:
            ts = self.created_at
        elif self.first_action_ts > 0:
            ts = self.first_action_ts
        else:
            return 0.0
        now = int(time.time())
        return max(0.0, (now - ts) / 86400.0)

    @property
    def registration_ts(self) -> int:
        """Get the best available registration timestamp."""
        DEFAULT_CREATED_AT = 1730419200
        if self.created_at > 0 and self.created_at != DEFAULT_CREATED_AT:
            return self.created_at
        return 0  # Unknown


@dataclass
class PairwiseSimilarity:
    user_a: str
    user_b: str
    timing_sim: float = 0.0
    topic_sim: float = 0.0
    reply_sim: float = 0.0
    vote_sim: float = 0.0
    content_sim: float = 0.0
    active_days_sim: float = 0.0
    preference_sim: float = 0.0  # Pearson on vote preferences (same as backend)
    pref_shared: int = 0  # Number of shared same-sign preferences
    coord_ratio: float = 0.0  # Proportion of posts that are coordinated
    match_ratio: float = 0.0  # Proportion of posts that are identical
    combined: float = 0.0

    # Raw counts (for display)
    coordinated_posts: int = 0
    identical_content: int = 0
    one_way_score: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "timing": round(self.timing_sim, 3),
            "topics": round(self.topic_sim, 3),
            "replies": round(self.reply_sim, 3),
            "votes": round(self.vote_sim, 3),
            "content": round(self.content_sim, 3),
            "active_days": round(self.active_days_sim, 3),
            "preference": round(self.preference_sim, 3),
            "coord_ratio": round(self.coord_ratio, 3),
            "match_ratio": round(self.match_ratio, 3),
            "combined": round(self.combined, 3),
            "coordinated_posts": self.coordinated_posts,
            "identical_content": self.identical_content,
            "one_way": round(self.one_way_score, 3),
        }


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


def load_preferences(cur) -> Dict[str, Dict[str, float]]:
    """Load user preference vectors from the preferences table."""
    cur.execute(
        """
        SELECT LOWER(owner), pref_type || ':' || target as key, weight
        FROM preferences
        WHERE weight != 0
    """
    )
    user_prefs: Dict[str, Dict[str, float]] = defaultdict(dict)
    for owner, key, weight in cur.fetchall():
        user_prefs[owner][key] = weight
    return dict(user_prefs)


def compute_preference_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> Tuple[float, int]:
    """
    Compute Pearson correlation on shared same-sign preferences.
    Returns (similarity, shared_count).

    EXACT same algorithm as web/backend/similarity.py:
    1. Pearson correlation on same-sign preferences only
    2. Logarithmic confidence factor: log(n+1) / log(31), 1.0 at 30 shared
    3. Final = min(1.0, pearson * confidence)
    """
    MIN_SHARED = 5
    CONFIDENCE_REFERENCE = 31  # log(31) gives 1.0 at 30 shared dims

    if not vec_a or not vec_b:
        return 0.0, 0

    shared_keys = set(vec_a.keys()) & set(vec_b.keys())

    # Only use keys where both users have same-sign preferences
    same_sign_keys = []
    for k in shared_keys:
        wa, wb = vec_a[k], vec_b[k]
        if (wa > 0 and wb > 0) or (wa < 0 and wb < 0):
            same_sign_keys.append(k)

    n = len(same_sign_keys)
    if n < MIN_SHARED:
        return 0.0, n

    vals_a = [vec_a[k] for k in same_sign_keys]
    vals_b = [vec_b[k] for k in same_sign_keys]

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

    # Logarithmic confidence: log(n+1) / log(31)
    # 5 dims → 0.52, 10 dims → 0.70, 20 dims → 0.88, 30 dims → 1.00
    confidence = math.log(n + 1) / math.log(CONFIDENCE_REFERENCE)

    # Final similarity (capped at 1.0)
    final = min(1.0, max(0.0, pearson * confidence))

    return final, n


def load_all_data(
    cur, since_ts: int
) -> Tuple[Dict[str, UserData], Dict[str, Dict], Dict[str, List[Dict]], Dict[str, Dict[str, float]]]:
    """Load all users, posts, votes, and preference vectors from database."""

    # Load profiles
    cur.execute(
        "SELECT LOWER(owner), COALESCE(username, ''), COALESCE(level, 0), COALESCE(created_at, 0) FROM profiles"
    )
    users: Dict[str, UserData] = {}
    for owner, username, level, created_at in cur.fetchall():
        o = owner.strip().lower()
        if o:
            users[o] = UserData(owner=o, username=username, level=level, created_at=created_at)

    # Load posts with full content
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
            "replies": [],
        }
        posts_by_hash[txhash.lower()] = post
        posts_by_user[o].append(post)

        if o in users and not deleted:
            u = users[o]
            # Count posts vs comments
            if target:
                u.comments += 1
            else:
                u.posts += 1

            # Timestamps
            u.post_timestamps.append(created_at)
            if u.first_action_ts == 0 or created_at < u.first_action_ts:
                u.first_action_ts = created_at
            if created_at > u.last_action_ts:
                u.last_action_ts = created_at

            # Active days
            day = created_at // 86400
            u.active_day_set.add(day)

            # Hour and day of week
            dt = datetime.fromtimestamp(created_at, tz=timezone.utc)
            u.hour_histogram[dt.hour] += 1
            u.day_of_week_histogram[dt.weekday()] += 1

            # Topics
            t = (root_topic or topic or "").strip().lower()
            if t:
                u.topic_counts[t] = u.topic_counts.get(t, 0) + 1

            # Content analysis
            text = f"{title} {content}".strip()
            if text:
                words = re.findall(r"[a-z]+", text.lower())
                u.word_counts.update(words)
                u.total_words += len(words)
                # Content hash for duplicate detection
                if len(text) > 20:
                    h = hashlib.md5(text.lower().encode()).hexdigest()[:16]
                    u.content_hashes.add(h)

            # Store recent posts
            if len(u.recent_posts) < MAX_POSTS_PER_USER:
                u.recent_posts.append(post)

    # Link replies to parent posts and track reply targets
    for post in posts_by_hash.values():
        if post["target"]:
            target_lower = post["target"].lower()
            if target_lower in posts_by_hash:
                posts_by_hash[target_lower]["replies"].append(post)
                # Track who this user replies to
                replier = post["owner"]
                target_owner = posts_by_hash[target_lower]["owner"]
                if replier in users and target_owner != replier:
                    users[replier].reply_targets[target_owner] = users[replier].reply_targets.get(target_owner, 0) + 1

    # Compute reply sources (who replies to each user)
    for o, u in users.items():
        for post in posts_by_user.get(o, []):
            for reply in post.get("replies", []):
                replier = reply["owner"]
                if replier != o:
                    u.reply_sources[replier] = u.reply_sources.get(replier, 0) + 1

    # Load votes with details for recent votes display
    cur.execute(
        """
        SELECT LOWER(v.owner), LOWER(p.owner), v.target, v.user_vote, v.created_at
        FROM votes v
        JOIN posts p ON LOWER(v.target) = LOWER(p.txhash)
        WHERE v.created_at >= %s
        ORDER BY v.created_at DESC
    """,
        (since_ts,),
    )

    for voter, post_owner, target, weight, vote_ts in cur.fetchall():
        # Update post vote counts
        target_lower = target.lower()
        if target_lower in posts_by_hash:
            if weight > 0:
                posts_by_hash[target_lower]["upvotes"] += 1
            else:
                posts_by_hash[target_lower]["downvotes"] += 1
        v = voter.strip().lower()
        po = post_owner.strip().lower()
        if v in users:
            u = users[v]
            u.votes_given += 1
            u.voted_posts.add(target.lower())
            if po != v:
                u.vote_targets[po] = u.vote_targets.get(po, 0) + 1

            # Track active days, timestamps, and histograms from votes too
            vote_day = vote_ts // 86400
            u.active_day_set.add(vote_day)
            if u.first_action_ts == 0 or vote_ts < u.first_action_ts:
                u.first_action_ts = vote_ts
            if vote_ts > u.last_action_ts:
                u.last_action_ts = vote_ts
            dt = datetime.fromtimestamp(vote_ts, tz=timezone.utc)
            u.hour_histogram[dt.hour] += 1
            u.day_of_week_histogram[dt.weekday()] += 1

            # Store recent votes (max 50, exclude self-votes)
            if len(u.recent_votes) < 50 and po != v:
                u.recent_votes.append(
                    {
                        "target": target,
                        "post_owner": po,
                        "weight": weight,
                        "created_at": vote_ts,
                    }
                )
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

    # Load preference vectors for similarity calculation
    user_prefs = load_preferences(cur)

    return users, posts_by_hash, posts_by_user, user_prefs


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


def weighted_jaccard(a: Dict[str, int], b: Dict[str, int]) -> float:
    """Jaccard similarity weighted by counts."""
    if not a or not b:
        return 0.0
    all_keys = set(a.keys()) | set(b.keys())
    intersection = sum(min(a.get(k, 0), b.get(k, 0)) for k in all_keys)
    union = sum(max(a.get(k, 0), b.get(k, 0)) for k in all_keys)
    return intersection / union if union > 0 else 0.0


def compute_pairwise_similarity(
    a: UserData,
    b: UserData,
    pref_a: Dict[str, float],
    pref_b: Dict[str, float],
) -> PairwiseSimilarity:
    """Compute all similarity metrics between two users."""
    sim = PairwiseSimilarity(user_a=a.owner, user_b=b.owner)

    # Skip if either user has no activity
    if a.content_count == 0 or b.content_count == 0:
        return sim

    min_posts = min(a.content_count, b.content_count)

    # Timing similarity (hour histogram)
    a_hours = [x / max(1, sum(a.hour_histogram)) for x in a.hour_histogram]
    b_hours = [x / max(1, sum(b.hour_histogram)) for x in b.hour_histogram]
    sim.timing_sim = cosine_similarity(a_hours, b_hours)

    # Topic similarity
    sim.topic_sim = jaccard_similarity(set(a.topic_counts.keys()), set(b.topic_counts.keys()))

    # Reply target similarity (who they reply to)
    sim.reply_sim = weighted_jaccard(a.reply_targets, b.reply_targets)

    # Vote target similarity
    sim.vote_sim = weighted_jaccard(a.vote_targets, b.vote_targets)

    # Active days overlap
    sim.active_days_sim = jaccard_similarity(a.active_day_set, b.active_day_set)

    # Content similarity (shared uncommon words)
    a_vocab = {w for w, c in a.word_counts.items() if c >= 2 and len(w) > 4}
    b_vocab = {w for w, c in b.word_counts.items() if c >= 2 and len(w) > 4}
    sim.content_sim = jaccard_similarity(a_vocab, b_vocab)

    # Preference similarity (Pearson correlation on vote preferences - same as backend)
    sim.preference_sim, sim.pref_shared = compute_preference_similarity(pref_a, pref_b)

    # Identical content - raw count and ratio
    sim.identical_content = len(a.content_hashes & b.content_hashes)
    sim.match_ratio = sim.identical_content / max(1, min_posts)

    # Coordinated timing - count unique windows and compute ratio
    if a.post_timestamps and b.post_timestamps:
        a_matched = set()
        b_matched = set()
        for i, ts_a in enumerate(a.post_timestamps):
            for j, ts_b in enumerate(b.post_timestamps):
                if abs(ts_a - ts_b) <= COORDINATED_TIMING_WINDOW_SECS:
                    a_matched.add(i)
                    b_matched.add(j)
        sim.coordinated_posts = min(len(a_matched), len(b_matched))
        sim.coord_ratio = sim.coordinated_posts / max(1, min_posts)

    # One-way relationship score
    a_to_b = a.reply_targets.get(b.owner, 0) + a.vote_targets.get(b.owner, 0)
    b_to_a = b.reply_targets.get(a.owner, 0) + b.vote_targets.get(a.owner, 0)
    total = a_to_b + b_to_a
    if total > 0:
        sim.one_way_score = abs(a_to_b - b_to_a) / total

    # Combined score: preference similarity is the PRIMARY sockpuppet signal
    # (same algorithm as the backend's "Similar Users" feature)
    # Other signals provide supplementary boosts
    base = sim.preference_sim  # This is the core sockpuppet indicator

    # Boost for behavioral signals (max 30% boost)
    behavior_boost = (
        0.05 * sim.timing_sim  # Same daily rhythm
        + 0.05 * sim.topic_sim  # Same interests
        + 0.05 * sim.reply_sim  # Reply to same people
        + 0.05 * sim.vote_sim  # Vote on same things
        + 0.05 * sim.coord_ratio  # Coordinated posting
        + 0.05 * sim.match_ratio  # Identical content
    )

    sim.combined = base + behavior_boost

    return sim


def compute_all_similarities(
    users: Dict[str, UserData],
    user_prefs: Dict[str, Dict[str, float]],
) -> Tuple[Dict[str, List[PairwiseSimilarity]], List[PairwiseSimilarity]]:
    """Compute pairwise similarities for all user pairs."""
    # Only compute for users with some activity
    active_users = [o for o, u in users.items() if u.content_count >= 2]

    similarities: Dict[str, List[PairwiseSimilarity]] = defaultdict(list)
    top_pairs: List[PairwiseSimilarity] = []

    n = len(active_users)
    for i in range(n):
        for j in range(i + 1, n):
            a = users[active_users[i]]
            b = users[active_users[j]]
            pref_a = user_prefs.get(a.owner, {})
            pref_b = user_prefs.get(b.owner, {})
            sim = compute_pairwise_similarity(a, b, pref_a, pref_b)

            if sim.preference_sim > 0.05 or sim.combined > 0.1:  # Include if meaningful pref similarity
                similarities[a.owner].append(sim)
                # Create reverse entry
                sim_rev = PairwiseSimilarity(
                    user_a=b.owner,
                    user_b=a.owner,
                    timing_sim=sim.timing_sim,
                    topic_sim=sim.topic_sim,
                    reply_sim=sim.reply_sim,
                    vote_sim=sim.vote_sim,
                    content_sim=sim.content_sim,
                    active_days_sim=sim.active_days_sim,
                    preference_sim=sim.preference_sim,
                    pref_shared=sim.pref_shared,
                    coord_ratio=sim.coord_ratio,
                    match_ratio=sim.match_ratio,
                    combined=sim.combined,
                    coordinated_posts=sim.coordinated_posts,
                    identical_content=sim.identical_content,
                    one_way_score=sim.one_way_score,
                )
                similarities[b.owner].append(sim_rev)

                # Include in top pairs if preference similarity >= 70%
                if sim.preference_sim >= 0.7:
                    top_pairs.append(sim)

    # Sort each user's similarities by preference_sim (primary sockpuppet signal)
    for owner in similarities:
        similarities[owner].sort(key=lambda s: (s.preference_sim, s.combined), reverse=True)
        similarities[owner] = similarities[owner][:MAX_SIMILAR_USERS]

    return similarities, sorted(top_pairs, key=lambda s: (s.preference_sim, s.combined), reverse=True)[:50]


# =============================================================================
# COORDINATED POST EXAMPLES
# =============================================================================


def find_coordinated_examples(
    a: UserData, b: UserData, posts_by_user: Dict[str, List[Dict]], max_examples: int = 3
) -> List[Dict]:
    """Find examples of posts from two users within 60 seconds of each other."""
    a_posts = posts_by_user.get(a.owner, [])
    b_posts = posts_by_user.get(b.owner, [])

    examples = []
    seen_pairs = set()

    for pa in a_posts:
        for pb in b_posts:
            ts_a = pa["created_at"]
            ts_b = pb["created_at"]
            gap = abs(ts_a - ts_b)
            if gap <= COORDINATED_TIMING_WINDOW_SECS:
                pair_key = (pa["txhash"], pb["txhash"])
                if pair_key not in seen_pairs:
                    seen_pairs.add(pair_key)
                    examples.append(
                        {
                            "gap_secs": gap,
                            "user_a": a.username,
                            "user_b": b.username,
                            "ts_a": ts_a,
                            "ts_b": ts_b,
                            "content_a": (pa.get("title") or pa.get("content") or "")[:80],
                            "content_b": (pb.get("title") or pb.get("content") or "")[:80],
                            "topic_a": pa.get("topic", ""),
                            "topic_b": pb.get("topic", ""),
                        }
                    )
                    if len(examples) >= max_examples:
                        return sorted(examples, key=lambda x: x["gap_secs"])

    return sorted(examples, key=lambda x: x["gap_secs"])


# =============================================================================
# NETWORK ANALYSIS
# =============================================================================


def compute_network_metrics(users: Dict[str, UserData]) -> Dict[str, Dict]:
    """Compute network centrality and clustering metrics for each user."""
    metrics = {}

    all_owners = set(users.keys())

    for owner, u in users.items():
        # Degree centrality
        out_degree = len(u.reply_targets)
        in_degree = len(u.reply_sources)
        degree = len(set(u.reply_targets.keys()) | set(u.reply_sources.keys()))
        degree_centrality = degree / max(1, len(all_owners) - 1)

        # Reciprocity
        reciprocal = set(u.reply_targets.keys()) & set(u.reply_sources.keys())
        total_connections = set(u.reply_targets.keys()) | set(u.reply_sources.keys())
        reciprocity = len(reciprocal) / max(1, len(total_connections))

        # Echo chamber score (concentration of interactions)
        total_interactions = sum(u.reply_targets.values()) + sum(u.reply_sources.values())
        if total_interactions > 0:
            top_3 = sorted(
                list(u.reply_targets.items()) + list(u.reply_sources.items()), key=lambda x: x[1], reverse=True
            )[:3]
            top_3_interactions = sum(c for _, c in top_3)
            echo_chamber = top_3_interactions / total_interactions
        else:
            echo_chamber = 0.0

        metrics[owner] = {
            "out_degree": out_degree,
            "in_degree": in_degree,
            "degree_centrality": round(degree_centrality, 3),
            "reciprocity": round(reciprocity, 3),
            "echo_chamber": round(echo_chamber, 3),
            "total_connections": len(total_connections),
        }

    return metrics


# =============================================================================
# TEMPORAL ANALYSIS
# =============================================================================


def compute_temporal_metrics(u: UserData) -> Dict:
    """Compute temporal patterns for a user."""
    if not u.post_timestamps:
        return {
            "gaps": [],
            "burst_count": 0,
            "avg_gap_hours": 0,
            "median_gap_hours": 0,
            "min_gap_secs": 0,
            "max_gap_days": 0,
        }

    timestamps = sorted(u.post_timestamps)
    gaps = []
    for i in range(1, len(timestamps)):
        gaps.append(timestamps[i] - timestamps[i - 1])

    if not gaps:
        return {
            "gaps": [],
            "burst_count": 0,
            "avg_gap_hours": 0,
            "median_gap_hours": 0,
            "min_gap_secs": 0,
            "max_gap_days": 0,
        }

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
    for i, gap in enumerate(gaps):
        if gap > 3 * 86400:
            dormant_periods.append(
                {
                    "start": datetime.fromtimestamp(timestamps[i], tz=timezone.utc).isoformat(),
                    "end": datetime.fromtimestamp(timestamps[i + 1], tz=timezone.utc).isoformat(),
                    "days": round(gap / 86400, 1),
                }
            )

    avg_gap = sum(gaps) / len(gaps)
    sorted_gaps = sorted(gaps)
    median_gap = sorted_gaps[len(sorted_gaps) // 2]

    return {
        "dormant_periods": dormant_periods[:5],  # Top 5
        "burst_count": burst_count,
        "avg_gap_hours": round(avg_gap / 3600, 1),
        "median_gap_hours": round(median_gap / 3600, 1),
        "min_gap_secs": min(gaps),
        "max_gap_days": round(max(gaps) / 86400, 1),
    }


# =============================================================================
# CLASSIFICATION
# =============================================================================


def classify_user(u: UserData, similar_users: List[PairwiseSimilarity]) -> Tuple[str, float, List[str]]:
    """Classify user as REAL or FAKE with confidence and reasons."""
    reasons = []

    # System accounts
    if u.username.startswith("mirage-") or u.username.startswith("Validator-"):
        return "FAKE", 0.95, ["System account"]

    # No activity at all
    if u.content_count == 0 and u.votes_given == 0:
        return "FAKE", 0.95, ["No activity"]

    # Check for high similarity sockpuppet
    high_sim = [s for s in similar_users if s.combined >= HIGH_SIMILARITY_THRESHOLD]
    if high_sim:
        reasons.append(f"High similarity ({high_sim[0].combined:.2f}) with {high_sim[0].user_b}")

    # Vote-only users (lurkers) - this is OK!
    if u.content_count == 0 and u.votes_given > 0:
        reasons.append(f"Lurker: {u.votes_given} votes, no posts")
        if u.votes_given >= 10 and u.active_days >= 2:
            if high_sim:
                return "SUSPICIOUS", 0.6, reasons
            return "REAL", 0.75, reasons + ["Active voter"]
        elif u.votes_given >= 5:
            return "REAL", 0.6, reasons + ["Casual voter"]
        else:
            return "REAL", 0.5, reasons + ["Light voter"]

    # Basic activity checks
    has_content = u.content_count >= MIN_CONTENT_FOR_REAL
    has_days = u.active_days >= MIN_ACTIVE_DAYS_FOR_REAL
    has_topics = len(u.topic_counts) >= MIN_TOPICS_FOR_REAL
    has_engagement = len(u.reply_sources) >= 1

    if has_content:
        reasons.append(f"Has {u.content_count} posts/comments")
    else:
        reasons.append(f"Low content ({u.content_count})")

    if has_days:
        reasons.append(f"Active {u.active_days} days")

    if has_topics:
        reasons.append(f"Covers {len(u.topic_counts)} topics")

    if has_engagement:
        reasons.append(f"Got replies from {len(u.reply_sources)} users")

    # Classification logic
    if has_content and has_days:
        if high_sim:
            return "SUSPICIOUS", 0.7, reasons
        return "REAL", 0.95, reasons

    if has_content and has_engagement and u.active_days >= 2:
        if high_sim:
            return "SUSPICIOUS", 0.65, reasons
        return "REAL", 0.85, reasons

    if has_content:
        if u.active_days >= 2:
            return "REAL", 0.75, reasons
        elif u.content_count >= 10:
            return "REAL", 0.8, reasons + ["High volume single day"]
        elif has_engagement and len(u.reply_sources) >= 3:
            return "REAL", 0.7, reasons + ["Strong engagement"]
        else:
            return "FAKE", 0.6, reasons + ["Only 1 active day"]

    if u.content_count >= 3 and has_days:
        return "REAL", 0.7, reasons

    if u.content_count >= 2 and u.active_days >= 2 and has_engagement:
        return "REAL", 0.55, reasons

    if u.content_count >= 2 and u.active_days >= 2:
        return "FAKE", 0.55, reasons + ["Minimal activity, no engagement"]

    return "FAKE", 0.7, reasons + ["Insufficient activity"]


# =============================================================================
# MARKDOWN GENERATION
# =============================================================================


def generate_user_markdown(
    u: UserData,
    similar_users: List[PairwiseSimilarity],
    network: Dict,
    temporal: Dict,
    users: Dict[str, UserData],
    similarities: Dict[str, List[PairwiseSimilarity]],
    posts_by_user: Dict[str, List[Dict]],
) -> str:
    """Generate comprehensive markdown analysis for a single user."""

    classification, confidence, reasons = classify_user(u, similar_users)

    lines = []
    lines.append(f"# User Analysis: {u.username}")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append(f"- **Wallet**: `{u.owner}`")
    lines.append(f"- **Classification**: {classification} (confidence: {confidence:.0%})")
    lines.append(f"- **Account age**: {u.age_days:.1f} days")
    if u.registration_ts:
        lines.append(
            f"- **Registered**: {datetime.fromtimestamp(u.registration_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
    if u.first_action_ts:
        lines.append(
            f"- **First post**: {datetime.fromtimestamp(u.first_action_ts, tz=timezone.utc).strftime('%Y-%m-%d')}"
        )
    if u.last_action_ts:
        lines.append(
            f"- **Last active**: {datetime.fromtimestamp(u.last_action_ts, tz=timezone.utc).strftime('%Y-%m-%d')}"
        )
    lines.append(f"- **Content**: {u.posts} posts, {u.comments} comments")
    lines.append(f"- **Active days**: {u.active_days}")
    lines.append(f"- **Topics**: {len(u.topic_counts)} unique")
    lines.append(f"- **Votes given**: {u.votes_given}")
    lines.append(f"- **Votes received**: +{u.votes_received_up} / -{u.votes_received_down}")
    lines.append("")

    # Red Flags - only show preference similarity >= 70%
    red_flags = []
    for sim in similar_users[:5]:
        if sim.preference_sim >= 0.7:
            other = users.get(sim.user_b, UserData(sim.user_b, sim.user_b))
            red_flags.append(
                f"High preference similarity ({sim.preference_sim:.0%}) with **{other.username}** ({sim.pref_shared} shared)"
            )

    if red_flags:
        lines.append("## RED FLAGS")
        for flag in red_flags:
            lines.append(f"- [!] {flag}")
        lines.append("")

    # Sockpuppet Analysis
    lines.append("## Sockpuppet Analysis")
    lines.append("")
    lines.append(
        "This section compares this user against all other users to detect potential sockpuppet relationships."
    )
    lines.append("")
    lines.append("**Prefs** (Preference Similarity) is the PRIMARY sockpuppet indicator, using the same")
    lines.append("Pearson correlation algorithm as the feed recommendations. **Combined** = Prefs + behavioral boosts.")
    lines.append("")
    lines.append("| Signal | Role | Description | Calculation |")
    lines.append("|--------|------|-------------|-------------|")
    lines.append(
        "| **Prefs** | PRIMARY | Vote preference alignment | Pearson correlation on same-sign votes (log confidence) |"
    )
    lines.append("| **Timing** | +5% boost | Hour-of-day activity pattern | Cosine similarity of 24-hour histograms |")
    lines.append("| **Topics** | +5% boost | Overlap in discussion topics | Jaccard similarity of topic sets |")
    lines.append("| **Replies** | +5% boost | Who they reply to | Weighted Jaccard of reply targets |")
    lines.append("| **Votes** | +5% boost | Who they vote on | Weighted Jaccard of vote targets |")
    lines.append("| **CoordR** | +5% boost | Coordinated posting rate | Proportion of posts within 60s of each other |")
    lines.append("| **MatchR** | +5% boost | Identical content rate | Proportion of posts with identical content |")
    lines.append("")
    if similar_users:
        lines.append("### Most Similar Users")
        lines.append("| Rank | User | Combined | Prefs | Timing | Topics | Replies | Votes | CoordR | MatchR |")
        lines.append("|------|------|----------|-------|--------|--------|---------|-------|--------|--------|")
        for i, sim in enumerate(similar_users[:MAX_SIMILAR_USERS], 1):
            other = users.get(sim.user_b, UserData(sim.user_b, sim.user_b))
            # Format prefs like backend: "85% (43)"
            pref_str = f"{sim.preference_sim:.0%} ({sim.pref_shared})" if sim.pref_shared > 0 else "-"
            lines.append(
                f"| {i} | {other.username} | {sim.combined:.2f} | {pref_str} | {sim.timing_sim:.2f} | {sim.topic_sim:.2f} | {sim.reply_sim:.2f} | {sim.vote_sim:.2f} | {sim.coord_ratio:.2f} | {sim.match_ratio:.2f} |"
            )
        lines.append("")

        # Detailed breakdown for top suspect
        if similar_users[0].combined >= SIMILARITY_THRESHOLD:
            top = similar_users[0]
            other = users.get(top.user_b, UserData(top.user_b, top.user_b))
            lines.append(f"### Why Similar to {other.username}?")

            # Reply target overlap
            shared_reply = set(u.reply_targets.keys()) & set(other.reply_targets.keys())
            if shared_reply:
                lines.append(f"- Reply targets overlap: {len(shared_reply)} users in common")

            # Topic overlap
            shared_topics = set(u.topic_counts.keys()) & set(other.topic_counts.keys())
            if shared_topics:
                lines.append(f"- Topic overlap: {', '.join(list(shared_topics)[:5])}")

            # Timing
            if top.timing_sim >= 0.7:
                lines.append(f"- Hour-of-day correlation: {top.timing_sim:.2f} (both active at similar times)")

            if top.coordinated_posts >= 1:
                lines.append(f"- Posts within 60s of each other: {top.coordinated_posts} times")

            lines.append("")
    else:
        lines.append("No significant similarities found.")
        lines.append("")

    # Temporal Analysis
    lines.append("## Temporal Analysis")
    lines.append("")
    lines.append(
        "Examines when and how frequently this user posts. Unusual patterns (e.g., 24/7 activity, extreme bursting) may indicate bot behavior."
    )
    lines.append("")
    lines.append("### Activity Stats")
    lines.append(f"- Posts in period: {u.content_count}")
    lines.append(f"- Avg posts per active day: {u.content_count / max(1, u.active_days):.1f}")
    lines.append(f"- Avg gap between posts: {temporal['avg_gap_hours']:.1f} hours")
    lines.append(f"- Median gap: {temporal['median_gap_hours']:.1f} hours")
    lines.append(f"- Min gap: {temporal['min_gap_secs']} seconds")
    lines.append(f"- Max gap: {temporal['max_gap_days']:.1f} days")
    lines.append(f"- Burst periods (10+ posts/hour): {temporal['burst_count']}")
    lines.append("")

    if temporal.get("dormant_periods"):
        lines.append("### Dormant Periods")
        for dp in temporal["dormant_periods"]:
            lines.append(f"- {dp['start'][:10]} to {dp['end'][:10]} ({dp['days']} days)")
        lines.append("")

    # Hour histogram
    lines.append("### Hour-of-Day Distribution (UTC)")
    lines.append("```")
    max_hour = max(u.hour_histogram) if u.hour_histogram else 1
    for hour in range(24):
        count = u.hour_histogram[hour]
        bar = "█" * int(20 * count / max(1, max_hour))
        lines.append(f"{hour:02d}: {bar} {count}")
    lines.append("```")
    lines.append("")

    # Day of week
    lines.append("### Day-of-Week Distribution")
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_str = ", ".join(f"{days[i]}: {u.day_of_week_histogram[i]}" for i in range(7))
    lines.append(day_str)
    lines.append("")

    # Estimate timezone from activity pattern
    if sum(u.hour_histogram) >= 10:  # Need enough data
        # Find the 4-hour window with least activity (likely 2-6 AM local time)
        min_activity = float("inf")
        min_start = 0
        for start in range(24):
            window_sum = sum(u.hour_histogram[(start + h) % 24] for h in range(4))
            if window_sum < min_activity:
                min_activity = window_sum
                min_start = start

        # If least active window starts at hour X in UTC, assume that's ~3 AM local
        # So local time = UTC + offset, where offset = (3 - X) mod 24, adjusted to -12..+12
        estimated_local_3am = min_start
        offset = (3 - estimated_local_3am) % 24
        if offset > 12:
            offset -= 24

        # Map offset to timezone name
        tz_names = {
            -12: "UTC-12 (Baker Island)",
            -11: "UTC-11 (Samoa)",
            -10: "UTC-10 (Hawaii)",
            -9: "UTC-9 (Alaska)",
            -8: "UTC-8 (Pacific/LA)",
            -7: "UTC-7 (Mountain/Denver)",
            -6: "UTC-6 (Central/Chicago)",
            -5: "UTC-5 (Eastern/NYC)",
            -4: "UTC-4 (Atlantic)",
            -3: "UTC-3 (Brazil)",
            -2: "UTC-2",
            -1: "UTC-1 (Azores)",
            0: "UTC+0 (London)",
            1: "UTC+1 (Paris/Berlin)",
            2: "UTC+2 (Cairo/Johannesburg)",
            3: "UTC+3 (Moscow)",
            4: "UTC+4 (Dubai)",
            5: "UTC+5 (Pakistan)",
            5.5: "UTC+5:30 (India)",
            6: "UTC+6 (Bangladesh)",
            7: "UTC+7 (Bangkok)",
            8: "UTC+8 (Singapore/Beijing)",
            9: "UTC+9 (Tokyo)",
            10: "UTC+10 (Sydney)",
            11: "UTC+11",
            12: "UTC+12 (Auckland)",
        }
        tz_name = tz_names.get(offset, f"UTC{offset:+d}")

        # Calculate confidence based on how quiet the sleep window is
        total_posts = sum(u.hour_histogram)
        sleep_ratio = min_activity / total_posts if total_posts > 0 else 0
        # Good confidence if sleep window has <10% of activity
        tz_confidence = "high" if sleep_ratio < 0.10 else "medium" if sleep_ratio < 0.20 else "low"

        lines.append("### Estimated Timezone")
        lines.append(f"- Most likely: **{tz_name}**")
        lines.append(f"- Confidence: {tz_confidence}")
        lines.append(
            f"- Based on: least active UTC hours {min_start:02d}-{(min_start+3)%24:02d} (assumed ~3-6 AM local)"
        )
        lines.append("")

    # Content Analysis
    lines.append("## Content Analysis")
    lines.append("")
    lines.append(
        "Analyzes the text content of posts. Low vocabulary diversity or very short posts may indicate low-effort spam."
    )
    lines.append("")

    # Compute post length stats from recent_posts
    post_lengths_words = []
    post_lengths_chars = []
    for post in u.recent_posts:
        content = f"{post.get('title', '')} {post.get('content', '')}".strip()
        words = len(re.findall(r"[a-z]+", content.lower()))
        chars = len(content)
        post_lengths_words.append(words)
        post_lengths_chars.append(chars)

    lines.append("### Overall Stats")
    lines.append(f"- Total posts/comments: {u.content_count}")
    lines.append(f"- Total words written: {u.total_words}")
    if post_lengths_words:
        avg_words = sum(post_lengths_words) / len(post_lengths_words)
        sorted_words = sorted(post_lengths_words)
        median_words = sorted_words[len(sorted_words) // 2]
        min_words = min(post_lengths_words)
        max_words = max(post_lengths_words)
        lines.append(f"- Words per post: avg={avg_words:.0f}, median={median_words}, min={min_words}, max={max_words}")

        avg_chars = sum(post_lengths_chars) / len(post_lengths_chars)
        sorted_chars = sorted(post_lengths_chars)
        median_chars = sorted_chars[len(sorted_chars) // 2]
        min_chars = min(post_lengths_chars)
        max_chars = max(post_lengths_chars)
        lines.append(f"- Chars per post: avg={avg_chars:.0f}, median={median_chars}, min={min_chars}, max={max_chars}")
    lines.append("")

    # Vocabulary stats
    vocab_size = len([w for w, c in u.word_counts.items() if c >= 2])
    lines.append("### Vocabulary")
    lines.append(f"- Unique words (used 2+ times): {vocab_size}")
    lines.append(f"- Total unique words: {len(u.word_counts)}")
    if u.total_words > 0:
        diversity = vocab_size / u.total_words
        lines.append(f"- Vocabulary diversity: {diversity:.3f} (higher = more varied language)")
    lines.append("")

    # Last 5 posts stats
    if len(u.recent_posts) >= 5:
        last5 = u.recent_posts[:5]
        last5_words = []
        last5_chars = []
        last5_topics = set()
        for post in last5:
            content = f"{post.get('title', '')} {post.get('content', '')}".strip()
            last5_words.append(len(re.findall(r"[a-z]+", content.lower())))
            last5_chars.append(len(content))
            if post.get("topic"):
                last5_topics.add(post["topic"])

        lines.append("### Last 5 Posts")
        lines.append(f"- Avg words: {sum(last5_words)/5:.0f}")
        lines.append(f"- Avg chars: {sum(last5_chars)/5:.0f}")
        lines.append(f"- Topics: {', '.join(last5_topics) if last5_topics else 'none'}")

        # Time span of last 5
        if last5[0].get("created_at") and last5[-1].get("created_at"):
            span_hours = (last5[0]["created_at"] - last5[-1]["created_at"]) / 3600
            lines.append(f"- Time span: {span_hours:.1f} hours")
        lines.append("")

    if u.word_counts:
        # Filter out common words
        common = {
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
        }
        top_words = [(w, c) for w, c in u.word_counts.most_common(30) if w not in common and len(w) > 3][:10]
        if top_words:
            lines.append("### Most Used Words")
            for w, c in top_words:
                lines.append(f'- "{w}": {c}x')
            lines.append("")

    # Network Analysis
    lines.append("## Network Analysis")
    lines.append("")
    lines.append("Measures how this user connects with others in the community.")
    lines.append("")
    lines.append("| Metric | Description |")
    lines.append("|--------|-------------|")
    lines.append("| **Out-degree** | Number of unique users this account replies to |")
    lines.append("| **In-degree** | Number of unique users who reply to this account |")
    lines.append("| **Degree centrality** | Connectedness relative to total users (0-1) |")
    lines.append("| **Reciprocity** | Fraction of connections that are mutual (0-1) |")
    lines.append("| **Echo chamber** | Concentration of interactions with top 3 users (high = narrow circle) |")
    lines.append("")
    lines.append(f"- Out-degree (users replied to): {network['out_degree']}")
    lines.append(f"- In-degree (users who reply): {network['in_degree']}")
    lines.append(f"- Degree centrality: {network['degree_centrality']:.3f}")
    lines.append(f"- Reciprocity: {network['reciprocity']:.2f}")
    lines.append(f"- Echo chamber score: {network['echo_chamber']:.2f}")
    lines.append("")

    # Reply graph
    if u.reply_targets:
        lines.append("### Users This Account Replies To")
        lines.append("| User | Count | Similarity |")
        lines.append("|------|-------|------------|")
        for target, count in sorted(u.reply_targets.items(), key=lambda x: x[1], reverse=True)[:10]:
            other = users.get(target, UserData(target, target))
            sim_score = 0.0
            for s in similar_users:
                if s.user_b == target:
                    sim_score = s.combined
                    break
            lines.append(f"| {other.username} | {count} | {sim_score:.2f} |")
        lines.append("")

    if u.reply_sources:
        lines.append("### Users Who Reply To This Account")
        lines.append("| User | Count | Similarity |")
        lines.append("|------|-------|------------|")
        for source, count in sorted(u.reply_sources.items(), key=lambda x: x[1], reverse=True)[:10]:
            other = users.get(source, UserData(source, source))
            sim_score = 0.0
            for s in similar_users:
                if s.user_b == source:
                    sim_score = s.combined
                    break
            lines.append(f"| {other.username} | {count} | {sim_score:.2f} |")
        lines.append("")

    # Vote targets
    if u.vote_targets:
        lines.append("### Vote Targets")
        lines.append("| User | Votes | Similarity |")
        lines.append("|------|-------|------------|")
        for target, count in sorted(u.vote_targets.items(), key=lambda x: x[1], reverse=True)[:10]:
            other = users.get(target, UserData(target, target))
            sim_score = 0.0
            for s in similar_users:
                if s.user_b == target:
                    sim_score = s.combined
                    break
            lines.append(f"| {other.username} | {count} | {sim_score:.2f} |")
        lines.append("")

    # Topic breakdown
    if u.topic_counts:
        lines.append("## Topics")
        lines.append("| Topic | Posts |")
        lines.append("|-------|-------|")
        for topic, count in sorted(u.topic_counts.items(), key=lambda x: x[1], reverse=True)[:15]:
            lines.append(f"| {topic} | {count} |")
        lines.append("")

    # Recent posts
    if u.recent_posts:
        lines.append("## Recent Posts")
        lines.append("")
        for i, post in enumerate(u.recent_posts[:MAX_POSTS_PER_USER], 1):
            topic = post.get("topic") or "none"
            votes = f"+{post['upvotes']}/-{post['downvotes']}"
            ts = datetime.fromtimestamp(post["created_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

            if post.get("target"):
                # Comment
                lines.append(f"### Post {i} (comment, #{topic}, {votes}, {ts})")
            else:
                # Root post - show full title
                title = post.get("title", "") or "(untitled)"
                lines.append(f"### Post {i}: {title}")
                lines.append(f"#{topic} | {votes} | {ts}")

            content = post.get("content", "")
            if content:
                lines.append("")
                lines.append(content)

            replies = post.get("replies", [])
            if replies:
                lines.append("")
                lines.append(f"**Replies ({len(replies)}):**")
                for reply in replies[:5]:
                    replier = users.get(reply["owner"], UserData(reply["owner"], reply["owner"]))
                    sim_score = 0.0
                    for s in similar_users:
                        if s.user_b == reply["owner"]:
                            sim_score = s.combined
                            break
                    reply_content = reply.get("content", "") or ""
                    lines.append(f"- **{replier.username}** (sim {sim_score:.2f}): {reply_content}")
            lines.append("")

    # Recent votes
    if u.recent_votes:
        lines.append("## Recent Votes")
        lines.append("")
        lines.append("Last 50 votes (useful for sockpuppet pattern detection).")
        lines.append("")
        lines.append("| Time | Vote | User | Sim | Post ID |")
        lines.append("|------|------|------|-----|---------|")
        for vote in u.recent_votes[:50]:
            ts = datetime.fromtimestamp(vote["created_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            vote_type = "UP" if vote["weight"] > 0 else "DOWN"
            post_owner = users.get(vote["post_owner"], UserData(vote["post_owner"], vote["post_owner"]))
            # Get similarity with vote target
            sim_score = 0.0
            for s in similar_users:
                if s.user_b == vote["post_owner"]:
                    sim_score = s.preference_sim
                    break
            lines.append(f"| {ts} | {vote_type} | {post_owner.username} | {sim_score:.0%} | {vote['target'][:12]}... |")
        lines.append("")

    # Signal Interpretation
    lines.append("## Signal Interpretation")
    lines.append("")
    lines.append("Human-readable analysis of this user's behavior patterns and sockpuppet risk.")
    lines.append("")
    lines.append(f"**Classification**: {classification} ({confidence:.0%} confidence)")
    lines.append("")
    lines.append("### Why this classification?")
    for reason in reasons:
        lines.append(f"- {reason}")
    lines.append("")

    # Activity signals
    lines.append("### Activity Signals")
    activity_desc = []
    if u.content_count >= 50:
        activity_desc.append(f"Very high volume ({u.content_count} posts/comments) - indicates dedicated user or bot")
    elif u.content_count >= 10:
        activity_desc.append(f"Moderate volume ({u.content_count} posts/comments) - consistent contributor")
    elif u.content_count >= 5:
        activity_desc.append(f"Light activity ({u.content_count} posts/comments) - casual user")
    else:
        activity_desc.append(f"Minimal activity ({u.content_count} posts/comments) - possibly inactive or new")

    if u.active_days >= 14:
        activity_desc.append(f"Long-term presence ({u.active_days} active days) - established account")
    elif u.active_days >= 7:
        activity_desc.append(f"Regular presence ({u.active_days} active days) - recurring user")
    elif u.active_days >= 3:
        activity_desc.append(f"Short presence ({u.active_days} active days) - new or sporadic")
    else:
        activity_desc.append(f"Brief presence ({u.active_days} active days) - very new or one-time")

    for desc in activity_desc:
        lines.append(f"- {desc}")
    lines.append("")

    # Engagement signals
    lines.append("### Engagement Signals")
    if len(u.reply_sources) >= 10:
        lines.append(f"- Strong community engagement: {len(u.reply_sources)} different users reply to this account")
    elif len(u.reply_sources) >= 3:
        lines.append(f"- Moderate engagement: {len(u.reply_sources)} users reply to this account")
    elif len(u.reply_sources) >= 1:
        lines.append(f"- Limited engagement: only {len(u.reply_sources)} user(s) reply to this account")
    else:
        lines.append("- No engagement: nobody replies to this account (suspicious for active posters)")

    if len(u.reply_targets) >= 10:
        lines.append(f"- Active participant: replies to {len(u.reply_targets)} different users")
    elif len(u.reply_targets) >= 3:
        lines.append(f"- Some participation: replies to {len(u.reply_targets)} users")
    elif len(u.reply_targets) >= 1:
        lines.append(f"- Minimal participation: only replies to {len(u.reply_targets)} user(s)")
    else:
        lines.append("- No replies: this account never replies to anyone")

    reciprocity = network.get("reciprocity", 0)
    if reciprocity >= 0.5:
        lines.append(f"- High reciprocity ({reciprocity:.0%}): healthy two-way conversations")
    elif reciprocity >= 0.2:
        lines.append(f"- Some reciprocity ({reciprocity:.0%}): mix of one-way and two-way interactions")
    else:
        lines.append(f"- Low reciprocity ({reciprocity:.0%}): mostly one-way interactions (suspicious)")
    lines.append("")

    # Sockpuppet indicators
    lines.append("### Sockpuppet Risk Assessment")
    sockpuppet_risks = []
    coordinated_examples = []

    for sim in similar_users[:5]:
        other = users.get(sim.user_b, UserData(sim.user_b, sim.user_b))
        if sim.identical_content >= 1:
            sockpuppet_risks.append(
                f"CRITICAL: {sim.identical_content} identical post(s) with **{other.username}** - strong sockpuppet indicator"
            )
        if sim.coordinated_posts >= 10:
            sockpuppet_risks.append(
                f"HIGH: {sim.coordinated_posts} posts within 60s of **{other.username}** - coordinated posting"
            )
            examples = find_coordinated_examples(u, other, posts_by_user, max_examples=3)
            if examples:
                coordinated_examples.append((other.username, examples))
        elif sim.coordinated_posts >= 3:
            sockpuppet_risks.append(f"MODERATE: {sim.coordinated_posts} posts within 60s of **{other.username}**")
            examples = find_coordinated_examples(u, other, posts_by_user, max_examples=2)
            if examples:
                coordinated_examples.append((other.username, examples))
        if sim.one_way_score >= 0.9 and (u.reply_targets.get(sim.user_b, 0) + u.vote_targets.get(sim.user_b, 0)) >= 5:
            sockpuppet_risks.append(
                f"HIGH: One-way support pattern with **{other.username}** (this account supports but never receives)"
            )
        if sim.combined >= 0.7:
            sockpuppet_risks.append(f"HIGH: Overall similarity {sim.combined:.0%} with **{other.username}**")
        elif sim.combined >= 0.5:
            sockpuppet_risks.append(f"MODERATE: Overall similarity {sim.combined:.0%} with **{other.username}**")

    if sockpuppet_risks:
        for risk in sockpuppet_risks:
            lines.append(f"- {risk}")
    else:
        lines.append("- No significant sockpuppet indicators detected")
    lines.append("")

    # Show coordinated post examples
    if coordinated_examples:
        lines.append("### Coordinated Posting Examples")
        lines.append("")
        for other_name, examples in coordinated_examples:
            lines.append(f"**With {other_name}:**")
            lines.append("")
            for ex in examples:
                ts_a_str = datetime.fromtimestamp(ex["ts_a"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                ts_b_str = datetime.fromtimestamp(ex["ts_b"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                lines.append(f"- Gap: **{ex['gap_secs']}s**")
                lines.append(f"  - {u.username} @ {ts_a_str}: \"{ex['content_a']}...\" (#{ex['topic_a']})")
                lines.append(f"  - {other_name} @ {ts_b_str}: \"{ex['content_b']}...\" (#{ex['topic_b']})")
                lines.append("")
        lines.append("")

    # Behavioral quirks
    lines.append("### Behavioral Notes")
    if temporal.get("burst_count", 0) >= 3:
        lines.append(f"- Frequent bursting: {temporal['burst_count']} periods of 10+ posts/hour (bot-like behavior)")
    elif temporal.get("burst_count", 0) >= 1:
        lines.append(f"- Occasional bursting: {temporal['burst_count']} period(s) of rapid posting")

    if network.get("echo_chamber", 0) >= 0.8:
        lines.append(f"- Echo chamber behavior: {network['echo_chamber']:.0%} of interactions with top 3 users")

    if u.avg_post_length < 5:
        lines.append(f"- Very short posts (avg {u.avg_post_length:.0f} words) - low effort content")
    elif u.avg_post_length > 50:
        lines.append(f"- Long posts (avg {u.avg_post_length:.0f} words) - detailed contributor")

    peak_hour = u.hour_histogram.index(max(u.hour_histogram)) if u.hour_histogram else 0
    lines.append(f"- Most active hour: {peak_hour:02d}:00 UTC")

    return "\n".join(lines)


# =============================================================================
# MAIN
# =============================================================================


def main():
    parser = argparse.ArgumentParser(description="Classify Mirage users with comprehensive analysis")
    parser.add_argument("--output-dir", "-o", default=OUTPUT_DIR, help=f"Output directory (default: {OUTPUT_DIR})")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    users_dir = output_dir / "users"
    users_dir.mkdir(parents=True, exist_ok=True)

    now_ts = int(time.time())
    since_ts = now_ts - LOOKBACK_DAYS * 86400

    print(f"Connecting to database...")
    started = time.time()

    with connect() as conn:
        with conn.cursor() as cur:
            print(f"Loading data (last {LOOKBACK_DAYS} days)...")
            users, posts_by_hash, posts_by_user, user_prefs = load_all_data(cur, since_ts)

    print(f"Loaded {len(users)} users, {len(user_prefs)} with preferences in {time.time() - started:.1f}s")

    # Compute similarities
    print("Computing pairwise similarities...")
    sim_started = time.time()
    similarities, top_pairs = compute_all_similarities(users, user_prefs)
    print(f"Computed similarities in {time.time() - sim_started:.1f}s")

    # Compute network metrics
    print("Computing network metrics...")
    network_metrics = compute_network_metrics(users)

    # Generate per-user markdown files
    print("Generating per-user analysis files...")
    real_count = 0
    fake_count = 0
    suspicious_count = 0

    for owner, u in users.items():
        sim_list = similarities.get(owner, [])
        network = network_metrics.get(owner, {})
        temporal = compute_temporal_metrics(u)

        md = generate_user_markdown(u, sim_list, network, temporal, users, similarities, posts_by_user)

        # Sanitize filename
        safe_name = re.sub(r"[^\w\-]", "_", u.username)[:50]
        filepath = users_dir / f"{safe_name}.md"
        filepath.write_text(md, encoding="utf-8")

        # Count classifications
        classification, _, _ = classify_user(u, sim_list)
        if classification == "REAL":
            real_count += 1
        elif classification == "SUSPICIOUS":
            suspicious_count += 1
        else:
            fake_count += 1

    # Generate summary.json
    print("Generating summary...")
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "total_users": len(users),
        "classifications": {
            "real": real_count,
            "suspicious": suspicious_count,
            "fake": fake_count,
        },
        "top_sockpuppet_pairs": [
            {
                "user_a": users.get(p.user_a, UserData(p.user_a, p.user_a)).username,
                "user_b": users.get(p.user_b, UserData(p.user_b, p.user_b)).username,
                "similarity": p.to_dict(),
            }
            for p in top_pairs[:20]
        ],
        "config": {
            "db_url": DB_URL.split("@")[-1] if "@" in DB_URL else DB_URL,  # Hide password
            "similarity_threshold": SIMILARITY_THRESHOLD,
            "min_content": MIN_CONTENT_FOR_REAL,
            "min_active_days": MIN_ACTIVE_DAYS_FOR_REAL,
        },
    }

    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    elapsed = time.time() - started
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  Real: {real_count}")
    print(f"  Suspicious: {suspicious_count}")
    print(f"  Fake: {fake_count}")
    print(f"\nOutput: {output_dir}")

    if top_pairs:
        print(f"\nTop sockpuppet pairs:")
        for p in top_pairs[:5]:
            a = users.get(p.user_a, UserData(p.user_a, p.user_a)).username
            b = users.get(p.user_b, UserData(p.user_b, p.user_b)).username
            print(f"  {a} <-> {b}: {p.combined:.2f}")


if __name__ == "__main__":
    main()
