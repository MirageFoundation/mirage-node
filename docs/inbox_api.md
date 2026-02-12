# Inbox Notification API

## How it works

Every JSON API response for a logged-in user now includes a `new_inbox_items` field with the count of unread inbox replies. This is injected server-side via middleware -- you don't need to call a separate endpoint to check.

The count is based on a per-user `inbox_last_viewed_at` timestamp stored in the DB. Any reply to the user's posts that arrived after that timestamp is counted as unread.

The count is cached server-side for 60 seconds per user, so it's cheap.

## Reading the count

Any GET request with an `address` query param will include it:

```bash
curl "http://127.0.0.1/api/get_posts?address=mirage1abc123&limit=10"
```

Response (truncated):
```json
{
  "posts": [...],
  "total": 42,
  "new_inbox_items": 3
}
```

- `new_inbox_items: 0` = no unread replies
- `new_inbox_items: 5` = 5 unread replies
- Field is absent for guest/unauthenticated requests

This works on all endpoints: `get_posts`, `get_comments`, `get_user_status`, `get_config`, etc.

## Marking inbox as viewed

When the user opens the inbox screen, POST to clear the count:

```bash
curl -X POST "http://127.0.0.1/api/mark_inbox_viewed" \
  -H "Content-Type: application/json" \
  -d '{"address": "mirage1abc123"}'
```

Response:
```json
{
  "ok": true,
  "inbox_last_viewed_at": 1739311200
}
```

After this, the next API response will return `new_inbox_items: 0` (cache is invalidated immediately on mark).

## Displaying the badge

- Show a numbered badge when `new_inbox_items > 0`
- Cap display at "99+" for counts over 99
- Hide badge when count is 0
- Update the badge on every API response (the field is always there)
