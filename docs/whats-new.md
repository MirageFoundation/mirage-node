# What's New in Mirage

A summary of the biggest features and improvements shipped from **v1.10.8** through **v1.15.0**.

---

### Topic Blocking

Block entire topics you don't want to see. Pick a topic from any post's menu, confirm the block, and all content tagged with that topic disappears from your feeds, search results, inbox, and comment trees. Blocked topics are stored on-chain and sync across devices — free users can block up to 10 topics, with higher limits at each subscription tier (125 / 500 / 1000).

This replaces the unused `quality_posts` infrastructure. The TierConfig slot it occupied has been repurposed for `max_blocked_topics`.

---

### Multi-Media Posts & Galleries

Posts and comments now support up to **10 images or videos** as first-class media attachments — no more pasting a URL on the first line and hoping for the best. Drag-and-drop files, pick a sticker, search for a GIF, or upload from your device. Everything feeds into a dedicated media field that's validated on-chain and fully editable after posting.

When a post has multiple attachments, a swipeable gallery appears with arrow navigation, an "X of Y" counter, and touch swipe on mobile. All items are preloaded so transitions feel instant. Single-media posts render inline like before — the gallery only activates when there's more than one.

<video src="gallery_demo.mp4" controls width="100%"></video>

---

### @Mention User Tagging

Type `@` anywhere in a post or comment and an autocomplete dropdown appears, searching usernames in real time. Use arrow keys to navigate, Enter or Tab to confirm, Escape to dismiss. Mentions render as clickable profile links throughout the app.

Tagged users get a notification in their inbox — a unified feed now shows both replies and mentions, distinguished at a glance with "mentioned you in" vs "replied to" labels. Self-mentions are filtered, duplicates are deduplicated, and mentions inside code blocks are left alone.

<video src="tagging_demo.mp4" controls width="100%"></video>

---

### Smarter Proof-of-Work Difficulty

The difficulty system was rebuilt from the ground up in v1.11.0. The old mechanism doubled the required work for every single step increase — way too aggressive. The new system uses a configurable fractional step size (`pow_factor`, default 25%), so difficulty ramps gradually instead of exponentially.

Difficulty is now a simple step counter starting at 0. Each busy window increments by 1, each calm window decrements by 1, and the effective work multiplier is `(1 + pow_factor)^steps`. It takes roughly 4 steps to double the work instead of 1. The step size is a governable on-chain parameter — validators can vote to adjust it without a code upgrade.

| Steps | Multiplier | vs Previous |
|-------|-----------|-------------|
| 0     | 1.00x     | baseline    |
| 1     | 1.25x     | +25%        |
| 2     | 1.56x     | +25%        |
| 3     | 1.95x     | +25%        |
| 4     | 2.44x     | +25%        |
| 5     | 3.05x     | +25%        |

---

### Network Charts & Observability

The Server page now has real charts — all built with lightweight inline SVGs that load instantly:

- **Node Balance**: 7-day line chart of the validator's liquid MIRAGE balance, green when rising, red when falling
- **Earned vs Spent**: cumulative earnings and spending derived from balance deltas
- **Total Supply**: 7-day supply trend with color indicating growth or decline
- **Minted vs Burned**: renamed from "Tokenomics" for clarity
- **Staked Balance**: now visible on the Server page

---

### Home Feed Improvements

The feed algorithm got a round of tuning in v1.10.9:

- Smaller, smarter candidate pool for faster queries
- Random exploration factor surfaces posts outside your usual patterns
- Reduced recency half-life to 9 hours for a faster-moving feed
- Jitter added to scoring to reduce stale ordering
- "Newest" sort fast path skips the scoring pipeline entirely

---

### Infrastructure & Reliability

A lot of behind-the-scenes work to make everything faster and more resilient:

- **API timeout tripled** from 10s to 30s — eliminates "operation aborted" errors on slower connections
- **Maintenance pages** during upgrades — Caddy serves a styled "Upgrade in Progress" page instead of raw 502 errors, with auto-refresh every 30 seconds
- **gRPC migration** — validator queries that shelled out to the CLI now go through gRPC directly, faster with no subprocess overhead
- **Smart rebuilds** — Go binary only recompiles when Go source files change; Python and frontend commits skip the recompile
- **Registration hardened** — off by default for new nodes, with hard failures on missing config instead of silent defaults
- **Status dashboard** rewritten with a card-based layout monitoring all services with color-coded indicators

---

### Fail-Hard Philosophy

Across the entire stack, silent fallbacks and recovery paths were stripped out in favor of hard failures. If a parameter is missing, a config is invalid, or a PoW value is out of range — the system tells you immediately instead of silently guessing. This surfaces bugs early and makes the network more predictable.

---

### Burn-Only Awards

Give awards to posts and comments by burning MIRAGE tokens. Four award types — Quality Post (🏆, 10k), Original Content (💡, 5k), Based AF (💪, 5k), Receipts (🏷️, 5k) — each with a permanent token burn. One award per account per post; no self-awards. Admins (level >= 100) award for free. Types and costs are governable on-chain parameters.

Awards feed into the Magic scoring algorithm: posts with awards from many distinct users get a ranking boost. Multiple awards of the same type stack (`3x🏆`); different types display as a list (`3x🏆, 💪, 2x🏷️`).

---

### Full Release Notes

- [v1.10.8](updates/update_v1.10.8.md) — Network charts, gRPC migration, registration hardening
- [v1.10.9](updates/update_v1.10.9.md) — @mention tagging, mention notifications, feed tuning
- [v1.11.0](updates/update_v1.11.0.md) — PoW difficulty overhaul, governable parameters, test suite
- [v1.12.0](updates/update_v1.12.0.md) — Multi-media posts, gallery component, API timeout fix
- [v1.13.0](updates/update_v1.13.0.md) — Topic blocking, quality_posts removal, tier-dependent limits
- [v1.14.0](updates/update_v1.14.0.md) — MsgDeleteUser for account deletion, soft-delete indexing, post attribution preserved
- [v1.15.0](updates/update_v1.15.0.md) — Burn-only awards, MsgAward, governable award_configs, magic scoring boost
