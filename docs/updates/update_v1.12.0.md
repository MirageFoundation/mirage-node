# Mirage v1.12.0 Release Notes

### Overview

v1.12.0 delivers multi-media posts — a highly requested feature since launch. Every post and comment can now carry up to 10 images or videos in a dedicated media field, displayed in a swipeable gallery with preloaded navigation. No more pasting a single URL on the first line and hoping for the best; media is a first-class part of the post data model, validated on-chain and editable after the fact.

On the reliability side, the frontend API timeout has been tripled from 10 seconds to 30 seconds. A lot of users were hitting "The operation was aborted" errors on slower connections or when the backend was under load — the old 10-second window was simply too aggressive. Pages that previously failed on the first load and required a manual refresh should now complete without issue.

The release also includes a revamped status dashboard, automatic maintenance pages during chain upgrades, and a round of test-suite cleanup that consolidates scattered attack tests into the main test runner.

**Upgrade Name:** `v1.12.0`

---

### Multi-Media Posts

Posts and comments now support a dedicated `media` field carrying up to 10 URLs.

- **Proto**: `repeated string media` added to both `MsgPost` (field 105) and `MsgEdit` (field 106)
- **Backend validation**: max 10 items, each URL capped at 2048 characters, HTTPS required
- **Create flow**: drag-and-drop, sticker picker, GIF picker, and upload buttons all feed into the media array
- **Edit flow**: existing media loads into the editor and can be reordered or removed
- **Legacy support**: pre-v1.12.0 posts that embedded a URL on the first line of content still render correctly

---

### Media Gallery

New `MediaGallery` component for posts with multiple attachments.

- Left/right arrow navigation with "X of Y" counter
- Touch swipe support on mobile
- All items mount eagerly so images are preloaded before the user swipes
- Single-media posts skip the gallery and render inline as before
- Feed cards show the first media item as a thumbnail

---

### API Timeout Increase

Default frontend request timeout raised from **10 seconds to 30 seconds**.

- Affects all API calls that didn't already specify a custom timeout
- Calls that intentionally use shorter windows (transaction status polling at 5s, username autocomplete at 4s) are unchanged
- Eliminates the "The operation was aborted" errors users were seeing on page loads when the backend took longer than 10 seconds to respond

---

### Maintenance Page During Upgrades

Caddy now serves a maintenance page automatically when the chain is upgrading.

- Checks for a `/etc/caddy/.maintenance` marker file
- API and chain endpoints return a JSON 503 instead of hanging
- All other routes serve an HTML maintenance page
- Clears automatically once the upgrade completes

---

### Status Dashboard

`scripts/status_dashboard.py` rewritten with a card-based layout.

- Monitors CometBFT, Validator, PostgreSQL, Backend API, Indexer, Caddy, and Bridge Orchestrator
- Color-coded status indicators per service
- Currency label corrected from MRG to MIRAGE
- "Server" card renamed to "Node" for consistency

---

### Test Suite Cleanup

- `tests/attack_tests_backend.py` and `tests/attack_tests_rpc.py` removed (~6,000 lines)
- Attack scenarios consolidated into `tests/test_local.py`
- `tests/spam_attack.py` renamed to `tests/test_spam.py`
- Added unit tests for `MsgPost` media validation and canonical encoding

---

### Bug Fixes

- Fixed media thumbnail spinner never clearing after upload completes
- Fixed gallery counter not updating after editing a post's media
- Fixed scroll jump on first view of newly uploaded gallery images
- Fixed post view jumping to top on short content (added min-height)
- Fixed media gallery not rendering on posts with empty text content

---

### Roadmap

- Block entire topics or keywords you don't want to see
- Push notifications for mentions and replies
- Threaded conversations with inline reply chains

Have a feature suggestion? Let us know on [Mirage](https://mirage.talk) — post it in the #feedback topic or message us directly.
