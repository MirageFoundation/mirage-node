# Trending Notifications — Mobile Integration Guide

## Overview

The backend now sends push notifications for trending posts to inactive users and writes a corresponding inbox event so it appears in the in-app inbox list.

---

## 1. Push Notification

When a trending push arrives, the payload looks like:

```json
{
  "title": "Trending on Mirage",
  "body": "Lively discussion on 'Post Title Here'",
  "data": {
    "type": "trending",
    "postId": "450ca1f5bfc25bb1...",
    "rootPostId": "450ca1f5bfc25bb1..."
  }
}
```

### What to do

Add a case for `data.type === "trending"` in the push notification tap handler. Navigate to the post screen using `data.postId` (or `data.rootPostId` — they're identical since trending only fires for root posts).

---

## 2. Inbox Item

> **Note on field names**: `/api/get_inbox` uses legacy `reply_*` prefixes for every item type (replies, mentions, awards, follows, donations, trending). This is historical — the inbox originally only served replies, then was extended to other types without renaming. Treat `reply_*` as generic "item" fields, not "reply-specific" fields.
>
> **These fields will be renamed in the next breaking API update** (`reply_id` → `item_id`, `reply_timestamp` → `item_timestamp`, `reply_owner` → `actor_owner`, etc.). Do NOT hardcode rendering logic around the `reply_*` names beyond what's strictly necessary — branch on `type` first, then pluck the fields. See `TODO.md` for the full rename plan.

The response now includes items with `"type": "trending"`. Example:

```json
{
  "reply_id": "trending:mirage13lg...:450ca1f5...",
  "reply_owner": "mirage1mfrsv4ks8ltgnl...",
  "reply_username": "SomeUser",
  "reply_author_level": 2,
  "reply_author_is_new": false,
  "reply_content": "",
  "reply_timestamp": 1776371728,
  "parent_id": "450ca1f5bfc25bb1...",
  "parent_content": "Just Setting Up My Mirage",
  "parent_owner": "mirage1mfrsv4ks8ltgnl...",
  "root_post_id": "450ca1f5bfc25bb1...",
  "award_type": "",
  "type": "trending",
  "amount": null
}
```

### Field mapping (for `type === "trending"`)

| Field | Meaning |
|---|---|
| `type` | Always `"trending"` |
| `reply_owner` / `reply_username` | The **post author** (ignore for phrasing — nobody is "replying") |
| `reply_timestamp` | When the notification was sent (unix epoch) |
| `reply_content` | Always empty string |
| `parent_id` | The trending post's txhash |
| `parent_content` | Post title (falls back to content preview, truncated to 200 chars) |
| `parent_owner` | The post author's address (same as `reply_owner`) |
| `root_post_id` | Same as `parent_id` (trending only fires on root posts) |
| `amount` | Always `null` |
| `award_type` | Always `""` |

### What to do

Add a render case for `type === "trending"` in the inbox list. Suggested UI:

- **Icon**: a flame/trending icon (distinct from reply/follow/award icons)
- **Text**: "Trending — *{parent_content}*" or "Lively discussion on *{parent_content}*"
- **Tap action**: navigate to post screen using `root_post_id`
- **Author avatar/name**: optionally show `reply_username` as the post author, but this is secondary — the focus is the post itself

### What NOT to do

- Don't show trending items as "unread" in the inbox badge — the backend deliberately excludes them from the unread count.
- Don't treat `reply_owner` as someone who interacted with the viewer. It's the post author, not a commenter or follower.

---

## 3. Testing

There's a test row inserted for `@Degenerate` on `mirage.talk`. After the backend is redeployed with the latest code, call:

```
GET /api/get_inbox?address=mirage13lggwdpr230vz57jr5wsrzeegcqkw49q83f8ze&page=0&limit=200
```

Filter for `type === "trending"` — you should see the test item with `parent_content = "Just Setting Up My Mirage"`.
