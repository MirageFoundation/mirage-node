# Mirage v1.6.3 Release Notes

### Overview

Discovery should be effortless. You shouldn't have to scroll endlessly hoping to stumble upon something interesting. With v1.6.3, Mirage gets universal search: find any user, topic, or post instantly. Type `@username` to find someone specific, `#topic` to explore a community, or just search freely across everything. The entire platform is now at your fingertips.

The mobile experience has been completely rethought. A persistent header with the MIRAGE logo and an expandable search bar appears on every screen. Tap the magnifying glass and the search bar slides smoothly across, no jarring transitions, no layout shifts. It's the kind of polish that makes the difference between software you tolerate and software you enjoy.

Under the hood, we've pre-computed similarity scores for all users and backfilled profile creation dates. The feed algorithm now knows who's like you before you even ask. Everything feels faster because it is.

---

### Search

- Type `@username` to find a specific user and their posts
- Type `#topic` to find matching topics
- Type anything else to search across all users, topics, and posts
- Results paginated with "Load More" for each category

---

### Mobile header

- Persistent header on every view: MIRAGE logo (tap to go home) + search button
- Search bar expands full-width with smooth slide animation
- Topic hero cards now appear below the header with proper width

---

### Bug fixes

- Vote state now persists correctly across all views
- Back navigation restores feed state and scroll position
- Search back button returns to results instead of home

---

### Database migrations

Two one-time migrations on first startup:

- **Profile dates**: Backfills `created_at` for existing profiles (Nov 1, 2024)
- **Similarity scores**: Pre-computes user similarity for profiles with 5+ preferences

---

### For developers

- New endpoint: `GET /api/search?q=query&offset=0&limit=10&viewer=address`
- New component: `MobileHeader.js` (reusable across all views)
- Migrations tracked in `meta` table, run only once
