# Mirage v1.10.6 Release Notes

### Overview

v1.10.6 focuses on making Mirage faster and more accessible. Pages load faster for everyone—especially new visitors—with smarter caching and fewer redundant requests under the hood.

Posts and profiles now have clean, shareable URLs. Instead of long ugly links, you get short URLs like `/p/{id}` and `/u/{username}`—links that look good when shared on social media or in chat. The topics page has been redesigned to surface active communities first, with a search that digs into smaller topics on demand.

On mobile, scrolling now works reliably in Telegram's in-app browser and Brave. And the MIRAGE balance in the top bar updates instantly, so you won't see stale numbers when jumping between pages.

---

### Clean Shareable URLs

- Posts and profiles now have short, clean URLs
- Old links still work—nothing breaks
- All links across the site use the new format

---

### Topics Page

- Shows only active topics (10+ posts) by default
- Search reveals smaller topics as you type
- Topic selector when creating a post still shows everything

---

### Performance

- Comment threads load significantly faster regardless of how deep they go
- Stats and welcome page load faster with smarter caching
- Pages load quicker for visitors who aren't logged in
- Smoother scrolling—removed visual effects that caused jank

---

### Mobile and Browser Fixes

- MIRAGE balance updates instantly across all pages
- Fixed scrolling in Telegram's in-app browser and Brave
- Compact card view is now the default on mobile

---

### Bug Fixes

- Fixed MIRAGE balance showing different values on different pages
- Fixed subscription level sometimes showing stale info
- Fixed "Continue this thread" appearing where it shouldn't
- Consistent confirmation dialogs across the site
- Added a proper 404 page for bad links

---

### Roadmap

- Block entire topics you don't want to see
- Galleries—multiple images and videos in a single post
- Block keywords in topics or posts
- Tag users with @ mentions for notifications

Have a feature suggestion? Let us know on [Mirage](https://mirage.talk) — post it in the #feedback topic or message us directly.
