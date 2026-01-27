# Mirage v1.7.1 Release Notes

### Overview

v1.7.1 is a quality-of-life release focused on UX polish, form navigation, and performance improvements. This update makes posting and replying smoother while restoring several features that were accidentally dropped in previous builds.

---

### Form Navigation Improvements

Keyboard-first users will appreciate the new circular tab navigation:

- **Tab wraps around**: Pressing Tab on the Submit button returns focus to the first field
- **Shift+Tab works too**: Navigate backwards seamlessly through all form fields
- **Visible focus indicators**: Buttons now show a clear purple outline when focused via keyboard
- **Streamlined tab order**: Auxiliary controls (stickers, GIFs, upload) are skipped during Tab navigation

These improvements apply to both the Create Post form and inline Reply forms.

---

### Inbox Mark Read

Each unread inbox item now has a small **Mark read** button (desktop/tablet only). Dismiss individual notifications without opening them, keeping your inbox organized.

---

### Performance: Smarter Similarity Caching

The user similarity engine now uses idle-based recomputation:

- Similarity scores only recompute after 30 minutes of inactivity
- Active voting sessions no longer trigger expensive recalculations
- Cache TTL extended to 12 hours as a backstop
- Result: faster page loads during active browsing

---

### Restored Features

Several features from the prod branch were accidentally missing from dev. This release restores:

- Per-item Mark read button in inbox
- Ctrl+B scroll fix in markdown editor (no more page jumps)
- Tab key handling in topic selector
- `check_grpc.py` utility script

---

### Technical Changes

- Unified `get_tx_status` endpoint with type-specific enrichment
- Standardized vote field naming across DB, API, and frontend
- Added React Native API guide with comprehensive endpoint documentation

---

### Upgrade Path

Standard Docker deployment. No database migrations required.

```bash
./deploy/deploy.sh --update-init
```

