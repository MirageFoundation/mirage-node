# Mirage v1.10.9 Release Notes

### Overview

v1.10.9 brings @mention tagging — type @ in any post or comment and an autocomplete dropdown appears, letting you tag other users by name. Mentioned users get a notification in their inbox, right alongside replies. Mentions render as clickable links that go straight to the tagged user's profile.

The home feed algorithm also got a round of tuning. The candidate pool is smaller and smarter, recency scoring was rebalanced, and a random exploration factor now surfaces posts you wouldn't otherwise see. Several edge-case bugs around feed pagination and config caching were fixed too.

---

### @Mention User Tagging

- Type `@` in the post/comment editor to trigger an autocomplete dropdown
- Searches usernames in real time via `GET /api/search_username` (200ms debounce)
- Keyboard navigation: Arrow Up/Down to select, Enter/Tab to confirm, Escape to dismiss
- Selecting a user inserts `@username` into the text with a trailing space
- Mentions render as clickable profile links in all post and comment content
- New `remarkMentions` remark plugin for the Markdown renderer, same pattern as spoiler tags
- Mentions inside code blocks and inline code are ignored (both in rendering and notification extraction)

---

### Mention Notifications

- New `mentions` database table tracks which users are mentioned in which posts
- Indexer extracts `@username` patterns from post/comment content on creation and edit
- Self-mentions are silently filtered out
- Edits delete old mentions and re-extract from updated content
- Inbox count now includes both replies and mentions
- `GET /api/get_inbox` returns a unified feed with a `type` field: `"reply"` or `"mention"`
- Inbox items show "mentioned you in" vs "replied to" to distinguish at a glance
- Blocked users and deleted posts are excluded from mention notifications
- Duplicate mentions of the same user in one post are deduplicated via unique constraint

---

### Home Feed Tuning

- Shrunk the candidate pool for faster query times without sacrificing quality
- Added random exploration factor to surface posts outside the user's usual patterns
- Reduced recency half-life from default to 9 hours for a faster-moving feed
- Fast path for "newest" sort skips the scoring pipeline entirely
- Added jitter to home feed scoring to reduce stale ordering

---

### Bug Fixes

- Fixed feed loading page 2 immediately on initial load (double-fetch on mount)
- Fixed `REGISTRATION_ENABLED` not being set on mirage.talk after deploy
- Reduced node config client-side cache TTL from 24 hours to 1 hour so config changes propagate faster
- Resolved frontend build warnings: unused import in App.js, missing hook dependencies in InboxView and SettingsView

---

### Roadmap

- Galleries — multiple images and videos in a single post
- Block entire topics or keywords you don't want to see
- Push notifications for mentions and replies

Have a feature suggestion? Let us know on [Mirage](https://mirage.talk) — post it in the #feedback topic or message us directly.
