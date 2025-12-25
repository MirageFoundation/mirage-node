# Mirage v1.6.1 Release Notes

**Version:** 1.6.1  
**Codename:** Earned Influence

---

## Overview

Mirage v1.6.1 refines how your voice matters. The previous release introduced personalized feeds that learn from your votes. This update takes it further: your vote weight is now earned through genuine participation in each community. Show up, contribute, and your influence grows. Lurk or spam, and you stay at baseline.

We've also polished the experience with smoother feedback, cleaner navigation, and a few quality-of-life fixes that make the app feel faster and more intuitive.

---

## What's new

### Votes that reflect your reputation

Your vote weight is no longer just about your subscription tier. It's now calculated per-topic based on how much you've actually participated:

- **Topic activity**: The more you vote in a community, the more weight you earn there.
- **Content contribution**: Post and comment in a topic to unlock full voting power. Lurkers start at baseline.
- **Account maturity**: Newer accounts build weight over their first week.
- **Engagement breadth**: Vote across different threads, not just one post repeatedly.
- **Anti-abuse protection**: If you've been mostly downvoting in a topic (net score below -10), you're capped at baseline weight. Chronic negativity doesn't earn influence.

This means a prolific contributor in `/gaming` carries real weight there, while their votes in `/photography` (where they've never posted) count less. Reputation is earned, not given.

### Magic and Newest modes everywhere

Both Home and Following feeds now offer two sorting modes:

- **Magic**: Our algorithm surfaces the best content based on weighted votes, freshness, and your preferences.
- **Newest**: Pure chronological order for when you want to see everything as it happens.

Switch between them anytime with the dropdown in the feed header.

### Real-time feedback that keeps you in the loop

When you vote, you now see exactly what's happening:

- **Instant toast notifications** show PoW progress, queue position, and confirmation status.
- **Vote weight details** appear after your vote is indexed, so you can see your actual impact.
- **Your vote always shows as +1/-1** on the post itself, while the real weighted contribution is tracked behind the scenes.
- **Downvoted posts vanish immediately** and stay gone, even while PoW completes in the background.

No more wondering if your action went through. The UI tells you everything.

### Threaded conversations that don't dead-end

Deeply nested comment threads now show a "Continue this thread" link when replies go beyond the visible depth. Click through to see the full conversation without losing context.

---

## Polish and fixes

### Cleaner navigation

- **Page titles** now update as you navigate, so your browser tabs and history make sense.
- **Topic badges** only appear on root posts, not on every comment in a thread.
- **Sidebar updates optimistically** when you follow or unfollow topics and users.
- **Discover page** shows topic tags for easier browsing.

### Routing cleanup

- Removed the `/all` and `/popular` routes entirely. Home and Following are your primary feeds now.
- Startup route restore uses a safe allowlist and falls back to `/home` if the saved route is invalid.

### Security

- **Inactivity auto-logout**: If you haven't used Mirage in 30 days, you're logged out automatically on next visit. Active users are unaffected.
- **Transaction timing hidden** for subscribers and admins to reduce information leakage.

### Bug fixes

- Fixed subscriber 400 errors when creating posts.
- Fixed home feed loading wrong pages on browser refresh.
- Fixed infinite loading when navigating between topic feeds.
- Fixed pill button height inconsistencies and mobile reply styling in light mode.
- Redgifs watch URLs now correctly open as external video links.

---

## The philosophy behind v1.6.1

Influence should be earned, not bought. While subscription tiers unlock higher *potential* vote weight, you still have to show up and participate to claim it. A Tier 3 subscriber who never posts in a topic has less sway there than a free user who's been contributing for months.

This creates healthier communities:

- **Newcomers can't brigade**: Fresh accounts start at baseline until they've proven themselves.
- **Regulars shape their communities**: The people who actually participate have the most say.
- **Cross-topic spam is pointless**: Your reputation doesn't transfer. Build it where it matters.

Your feed learns from you. Your influence grows with you. That's the deal.

---

## For developers and integrators

Key changes since v1.6:

- Vote weighting:
  - New `user_topic_stats` table tracks per-user per-topic: `vote_count`, `net_votes`, `unique_root_posts`, `post_count`.
  - Community vote weight formula: `baseline + (topic_factor * age_factor * root_factor * posts_factor) * (tier_max - baseline)`.
  - Configurable constants in `indexer/settings.py`: `COMMUNITY_VOTE_BASELINE`, `COMMUNITY_VOTE_MAX_TOPIC_VOTES`, `COMMUNITY_VOTE_MIN_NET_VOTES`, `COMMUNITY_VOTE_MATURITY_DAYS`, `COMMUNITY_VOTE_MIN_ROOT_POSTS`, `COMMUNITY_VOTE_MAX_POSTS`.
  - Vote logs include full calculation breakdown for debugging.

- Feeds:
  - `sort_mode` param renamed: `personalized` -> `magic`, `chrono` -> `newest`.
  - Both Home and Following feeds support Magic/Newest modes.

- Frontend:
  - Toast notification system for transaction progress.
  - Vote details endpoint: `/api/public/vote_details` returns real community vote after indexing.
  - Optimistic UI updates for votes, follows, and sidebar state.
