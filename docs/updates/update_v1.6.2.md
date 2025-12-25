# Mirage v1.6.2 Release Notes

**Version:** 1.6.2  
**Codename:** Smarter Discovery

---

## Overview

Mirage v1.6.2 rebuilds the home feed from the ground up. The previous version introduced preference-based personalization. This release makes it dramatically smarter: your feed now learns from users who share your taste, surfacing content you're likely to love before you even know it exists.

We've also streamlined the codebase, removing legacy feed logic and unifying how both Home and Following feeds work.

---

## What's new

### A feed that knows your taste

Your home feed now uses four distinct content streams, intelligently blended:

- **Liked**: Posts from topics and authors you've upvoted. Your explicit preferences come first.
- **Similar**: Posts upvoted by users with similar taste. If someone who votes like you loved a post, you'll see it too.
- **Discovery**: Fresh content you haven't interacted with yet. New voices, new topics.
- **Second Chance**: Posts from topics or authors you've mildly downvoted. Everyone deserves a redemption arc.

The algorithm scores each post using recency, engagement, and similarity signals, then weaves them together in a natural rhythm. Every third post highlights similar users' picks. Every fourth brings something new. Every tenth gives a second chance.

### Similarity that actually works

User similarity is now computed using Pearson correlation with confidence weighting:

- **Same-sign preferences only**: Two users who both love `/gaming` and both hate `/crypto` are similar. Mixed signals don't count.
- **Confidence scaling**: More shared preferences = higher confidence. A handful of agreements won't dominate.
- **Author sentiment**: Your direct feelings about a user softly adjust their similarity score.

The result: recommendations from people who genuinely share your worldview, not random overlap.

### Smarter scoring

Every post gets a score based on:

- **Recency**: Fresh posts score higher. The decay is smooth: 1 hour old = 0.97, 6 hours = 0.50, 24 hours = 0.06.
- **Engagement**: Comments and net votes boost visibility, using logarithmic scaling so one viral post doesn't dominate.
- **Similarity**: How much do users-like-you love this post? Capped at 3.0 and normalized.

The formula varies by bucket:
- Liked/Discovery/Second Chance: `(votes + comments) * recency`
- Similar: `similarity * recency`

### Newest mode that makes sense

Toggle to "Newest" and you get pure chronological order. Every post appears, including second-chance content, sorted by time. No algorithms, no buckets, just the firehose.

### Following feed, upgraded

The Following feed now uses the same scoring system. Posts from followed topics and users are ranked by the same recency/engagement formula, with Magic and Newest modes working identically to Home.

---

## Technical cleanup

### Removed legacy feed logic

The old feed functions are gone:

- `_calculate_hot_score`
- `_compute_bucket_weights`
- `_merge_feed_buckets`
- `_get_feed_posts`
- `_calculate_velocity`
- `_compute_baseline_velocity`
- `_build_bucket_sequence_dynamic`

Both Home and Following feeds now run through unified code paths.

### Pruned unused imports

Removed dead imports: `socket`, `ipaddress`, `send_file`, redundant `Response`.

### Debug tooltips

Hover over any post to see exactly why it's in your feed:

- Bucket assignment (liked/similar/discovery/second_chance)
- Full scoring formula with values
- Similarity sum, recency factor, comment count
- Topic and author preference breakdown

---

## The philosophy behind v1.6.2

Discovery should feel effortless. You shouldn't have to hunt for good content or manually curate your feed. The algorithm should learn from your behavior and from people like you.

But it shouldn't be a black box. The debug tooltip shows you exactly why every post appears. You're in control, with full transparency into how your feed works.

Your taste. Your people. Your feed.

---

## For developers and integrators

Key changes since v1.6.1:

- Home/Following feeds:
  - Unified architecture for both feeds.
  - `_get_home_feed()` and `_get_following_feed()` replace all legacy feed functions.
  - Bucket scoring: `(V + C) * R` for quality, `S * R` for similarity.
  - Interleaving: every 3rd = similar, every 4th = discovery, every 10th = second_chance, default = liked.
  - Severely disliked threshold: `combined_pref < -10` hides posts entirely.
  - Second chance threshold: `-10 <= combined_pref < 0`.

- Similarity:
  - Pearson correlation with same-sign preference matching.
  - Confidence factor: `ln(1 + shared_count) / ln(1 + 50)`.
  - Author factor: soft penalty/boost based on viewer preference for similar user.
  - Cached in `user_similarity_cache` with staggered TTL (5-10 min jitter).

- Scoring helpers:
  - `_log_recency(ts)`: Inverse quadratic decay `1 / (1 + (hours/6)^2)`.
  - `_log_comments(n)`: `ln(1 + n)`.
  - `_log_signed(x)`: `sign(x) * ln(1 + |x|)`.

- Frontend:
  - `FeedDebugTooltip` shows full scoring breakdown.
  - Sort mode switching triggers proper refetch without reload.

