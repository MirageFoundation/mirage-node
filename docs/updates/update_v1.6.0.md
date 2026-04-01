# Mirage v1.6 Release Notes

**Version:** 1.6.0  
**Codename:** Personalized Discovery

---

## Overview

Mirage v1.6 makes your feed *yours*. The previous release built the social graph, follows, blocks, and tier-based limits. This upgrade puts that graph to work with personalized feeds that learn from your votes, a curated Following feed for content you've explicitly subscribed to, and granular content filters that let you see exactly what you want (and hide what you don't).

We're moving toward a truly social experience where the more you engage, the better your feed becomes, while keeping you in complete control of what shows up.

---

## What's new

### A Home feed that learns

Your Home feed is no longer a firehose. It's a smart blend of:

- **Posts from topics and users you follow**: front and center.
- **Content you've shown interest in**: topics and authors you've upvoted rise higher.
- **New communities to discover**: a curated slice of fresh content so you never miss what's trending.
- **Suppressed content**: topics and authors you've downvoted fade to the background.

Every vote teaches your feed. Upvote what you like, downvote what you don't, and watch your Home feed transform into a personalized stream. Strong dislikes (topics or authors you've repeatedly downvoted) are filtered out entirely.

Toggle between **Personalized** and **Chronological** modes whenever you want a different view.

### A Following feed that's just for you

The new Following feed is a pure timeline of posts from the topics and users you've chosen to follow, no algorithm, no discovery, no surprises. It's chronological, predictable, and completely under your control.

Use Home for discovery. Use Following when you only want what you've subscribed to.

### Content tags and safety controls

Not all content is for everyone. v1.6 introduces content tags so you can filter what you see:

- **Sensitive**: mature themes that may not be safe for work.
- **Adult**: adult content.
- **Violence**: depictions of violent acts.
- **Gore**: graphic injury or blood.
- **Death**: content depicting death.

When you first open Mirage, you'll be asked whether you want to see adult content. Say yes or no, you can always change it later in Settings.

Each tag has its own toggle. Show sensitive content but hide gore. See violence but skip adult content. You decide.

### Instant feedback, zero friction

- **Hide posts on downvote**: The moment you downvote a post in your Home feed, it vanishes. No waiting, no page refresh. You're cleaning your feed in real time.
- **Optimistic replies**: When you reply to a post, your comment appears instantly while the blockchain confirms in the background. The conversation keeps flowing.
- **Real-time status**: Buttons show queue position and transaction progress so you always know what's happening.

---

## Discover new topics

The dedicated **Discover** page lets you browse all active topics, sorted by activity. Find new communities, follow them with one click, and watch them appear in your Home and Following feeds.

Your Home feed also includes a "discovery" bucket, a rotating slice of popular posts from topics you haven't interacted with yet. It's how you stumble onto the next community you'll love.

---

## Protocol and performance changes

### Simpler posting

v1.6 removes multi-topic (cross-post) support. Every post now belongs to exactly one topic. This simplifies the protocol, makes moderation clearer, and ensures posts have a single home.

If you want your content in multiple communities, post it where it fits best, the social graph will surface it to the right people.

### Character-based limits

Content and title validation now counts **characters** (runes), not bytes. This means international users get the same limits as English speakers, no more being penalized for non-ASCII characters.

### Tighter limits

We've reduced some limits to encourage focused, quality content:

| Limit          | v1.5 | v1.6 |
|----------------|------|------|
| Topic name     | 50   | 35   |
| Username       | 40   | 30   |

### Slower minting

The `mint_interval` has increased from 20 blocks (~1 min) to 200 blocks (~10 min). This reduces inflation and makes the token more sustainable long-term.

---

## Settings for power users

The Settings page now includes:

- **Content tag toggles**: Show or hide each content category independently.
- **Blur sensitive media**: Keep posts visible but blur images/video until you click.
- **Hide negative comments**: Set your own threshold (-1 to -10) for comment visibility.
- **Hide posts you downvote**: Instantly remove downvoted posts from your Home feed.
- **Sidebar people count**: Choose how many followed users to show before "show more".

---

## The philosophy behind v1.6

We believe social media should feel social, not like shouting into a void. v1.6 is a step toward feeds that understand you, while giving you the tools to shape them.

- **Discovery without manipulation**: We show you new content, but your votes decide what sticks.
- **Control without isolation**: Follow who you want, hide what you don't, but always have a path to discover more.
- **Transparency without complexity**: Every post in your Home feed can show exactly *why* it's there, hover for debug info.

The more you use Mirage, the better it gets. And if you ever want to reset, just change what you follow.

---

## For developers and integrators

Key changes since v1.5:

- Posts:
  - `topics` array removed; replaced with single `topic` string.
  - `max_cross_posts` removed from `TierConfig` proto.
  - Content/title validation uses `utf8.RuneCountInString()` (characters) not `len()` (bytes).

- Feeds:
  - `/api/public/posts` accepts `feed` param: `home`, `following`, or topic name.
  - Home feed returns `feed_bucket` and `feed_debug` for transparency.
  - `sort_mode` param: `personalized` (default) or `chrono` for Home feed.

- Content tags:
  - Posts include `tag` field for content classification.
  - `/api/public/topic_search` returns `safety_flags` per topic.
  - Filter posts by excluded tags via `excluded_tags` query param.

- Preferences:
  - Topic/author preferences tracked via `topic_prefs` and `author_prefs` tables.
  - Preferences updated automatically from vote history.
  - Hard block threshold: preference ≤ -5 hides content entirely.

- Params:
  - `mint_interval`: 20 → 200
  - `max_topic_size`: 50 → 35
  - `max_username_size`: 40 → 30
