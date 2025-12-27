# Mirage v1.7.4 Release Notes

### Overview

v1.7.4 is about making Mirage’s ranking **simpler, clearer, and harder to game**. We removed the old “Magic 1/2” variants and unified the entire app around a single algorithm called **Magic**—the one with the best signal and the most explainability.

This release also pushes transparency to the surface: posts don’t just appear in your feed—they come with an explicit **reason** and a **score**. Whether you’re browsing Home, Following, topic feeds, or even using Mirage as a guest, you can see exactly what the system is optimizing for.

---

### Magic feed (unified)

- **Magic is now the default** (formerly “Magic 3”)
- Removed **Magic 1** and **Magic 2** from the UI and API
- Guest Home feed now uses Magic scoring (no personalization, but the same explainable components)

---

### Feed transparency

- Feed items consistently show a **reason** and **score** across Home, Following, and topic/all feeds
- Following feed reasons now explain *why* a post is included (followed topic/user/your post)

---

### Network: burn vs mint chart

- Added a burn/mint chart based on recent supply history
- New backend endpoint for chart data: `GET /api/get_supply_history` (7-day window, cached)

---

### Bug fixes

- Fixed cases where posts could render without a visible feed reason

---

### For developers

- **API**: `GET /api/get_supply_history` returns `history` plus mint params for client-side burn/mint calculations
- **Indexer**: new `supply_history` table and periodic sampling of total supply

