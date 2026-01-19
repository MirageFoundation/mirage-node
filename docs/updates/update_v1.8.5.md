# Mirage v1.8.5 Release Notes

### Overview

This release focuses on feed quality and user experience polish. The magic feed algorithm now decays posts faster—reaching half-score at 12 hours instead of 24—which keeps the feed fresher and rewards timely engagement. Combined with the preference score cap, feeds are now more balanced between new content and established posts.

Subscriber identity gets more visible with tier tooltips. Hover over any colored username to see their subscription level (Trusted, Established, or Distinguished). The tooltip system was overhauled to appear consistently above text across the entire platform, eliminating the visual inconsistency of tooltips appearing in different positions.

For token listings and market data aggregators, we've added CoinGecko-compliant supply endpoints that return plain-text values for easy integration. The circulating supply calculation excludes team-controlled wallets (Founders, Marketing, and Development funds) to provide accurate market data.

---

### Feed Algorithm Tuning

- Recency half-time reduced from 24h to 12h (posts decay twice as fast)
- Raw preference score capped to ±5 (prevents extreme topic/author bias)
- Post author excluded from unique commenter count (no self-boosting)

---

### Tier Status Tooltips

- Hover over colored usernames shows "Trusted/Established/Distinguished Subscriber"
- All tooltips standardized to appear above text, left-aligned
- Tooltips now use portal rendering to avoid overflow clipping in cards
- Removed cursor:help styling from tooltip triggers

---

### CoinGecko Supply Endpoints

- `/api/get_total_supply` — returns total supply as plain text (6 decimals)
- `/api/get_circulating_supply` — returns circulating supply excluding team wallets
- Excluded wallets: Founders Fund, Marketing Fund, Development Fund

---

### Navigation & Access

- `/discover` renamed to `/topics` with public access for logged-out users
- Non-logged-in users redirect to home instead of custom login screens
- All other views gated for logged-out users with consistent login prompts
- Tier colors extended to search results and inbox

---

### Optimistic UI

- Comments show immediate self-upvote on submission
- Invite-only banner displayed on home and following feeds

---

### Bug Fixes

- Fix send_tokens signature mismatch for large token amounts
- Fix tuple unpacking error in topic feed queries
- Fix container hostname resolution in Docker deployments

---

### For Developers

**New API endpoints:**
- `GET /api/get_total_supply` — plain text, 6 decimal places
- `GET /api/get_circulating_supply` — plain text, excludes team wallets

**Feed algorithm constants:**
- `RECENCY_HALF_TIME = 12` (was 24)
- `MAX_PREF_SCORE = 5` (preference clamping)

**Admin endpoints:**
- `GET /api/stats/signups` — recent signups with referrer info (admin only)
