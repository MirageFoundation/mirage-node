# Mirage v1.7.3 Release Notes

### Overview

v1.7.3 introduces **Magic 2** and **Magic 3**, two new feed algorithms built from the ground up. The original magic algorithm grew complex over time with its bucket interleaving, topic preferences, and second-chance mechanics. These new algorithms strip all that away in favor of a single, unified score that's easy to understand and reason about.

The philosophy is simple: one score, computed from a handful of signals, multiplied by recency decay. No hard cutoffs, no arbitrary position rules—just soft decay curves that naturally surface fresh, engaging content. A 3-day old post with no comments won't appear at the top of your feed anymore, and posts with 50 upvotes will rank meaningfully higher than posts with 10.

All three Magic algorithms are available from the dropdown on your Home or Following feed. We're testing which one works best—try them out and let us know which you prefer. The community favorite will become the default.

- **Magic 1**: The original algorithm with bucket interleaving and preference-based sorting
- **Magic 2**: Pure signal-based scoring, ignores your topic/author preferences
- **Magic 3**: Signal-based scoring + preference boost from your voting history

---

### Magic 2 Feed Algorithm

Pure signal-based scoring: `(S + V + U) × R`

- **S (Similar)**: Posts upvoted by users with similar taste get boosted
- **V (Votes)**: `sqrt(votes) × 0.5` — softer than log, so 50 upvotes beats 10 decisively
- **U (Unique)**: `sqrt(unique_commenters) × 0.3` — distinct users, not total comments
- **R (Recency)**: `1 / (1 + (age/24h)^1.585)` — gentle decay: 12h=0.75, 24h=0.5, 48h=0.25

Preferences only affect hiding (≤-5 combined) and bucket labels, not the score itself.

---

### Magic 3 Feed Algorithm

Magic 2 + preference boost: `(S + V + U + P) × R`

- **P (Prefs)**: `sqrt(max(0, topic_pref + author_pref)) × 0.3`

Posts from topics and authors you've upvoted get a score boost. Your voting history directly influences what ranks higher.

---

### Feed Debug Tooltips

Hover over the feed reason (liked/similar/etc.) to see scoring details:

- **Score**: The final unified score
- **S**: Similarity component
- **V**: Vote component with raw point count
- **U**: Unique commenter component with user count
- **P**: Preference boost (Magic 3 only)
- **R**: Recency factor with age in hours

---

### New Feed Bucket Types

Magic 2 uses more descriptive bucket labels:

- **similar**: Similar users liked this
- **liked**: You like this topic/author
- **popular**: High vote count
- **discussion**: Active unique commenters
- **discovery**: Fresh content

---

### UI Density & Compact Mode

The entire interface is now ~12% more compact by default through a reduced base font-size. This makes better use of screen real estate without changing any component code.

Compact card mode (selectable from the feed info bar) has been significantly improved:

- **Tighter card padding**: Reduced internal spacing on all sides
- **Smaller gaps between cards**: Cards stack closer together
- **Reduced internal margins**: Less whitespace around titles, meta info, and action rows
- **Thumbnail alignment fix**: Thumbnails now properly align with the top of text content
- **More breathing room**: Slightly increased bottom padding to avoid cramped action rows

---

### Infinite Scroll Improvements

The feed now loads the next page earlier—when you're about 5-6 posts from the bottom instead of 2-3. This creates a smoother scrolling experience with fewer visible loading states.

---

### Media Mode

A new **Media Mode** card size option displays full-size images and videos directly in the feed, right below the post title. No more clicking to expand—content shows at its original aspect ratio with a max height of 2000px.

- Available from the dropdown on your Home, Following, or Topic feeds
- Falls back to thumbnail display if no media is available
- All videos autoplay muted for seamless browsing
- Sensitive content remains properly blurred when blur setting is enabled

---

### Full Width Mode

New setting (Settings → Appearance → Full width) expands the content area, top bar, and search to use the full screen width. Great for larger monitors.

---

### Topic Feed Sorting

Sort options (Hot, New, Magic) now work correctly on individual topic pages, not just Home and Following feeds.

---

### Feed Controls in the Info Bar

Sorting and card density controls are now available directly in the feed/topic info bars, so you can change your view without digging through Settings.

- **Sort mode**: Choose between Magic variants / newest, and it applies consistently across feeds (including topics)
- **Card mode**: Switch between compact / regular / media

---

### Card Click Behavior

Clicking a post card (title or thumbnail) now always opens the post view page instead of directly opening external links. This gives you a chance to see the post details and comments before visiting the link—the URL is still visible and clickable from the post view.

---

### Settings UI Polish

- **Checkboxes**: Improved alignment and behavior; only the checkbox+text area is clickable, with a subtle checkbox-only hover affordance

---

### Performance

- **Votes cache**: Reduced local vote cache to a small recent set and removed expensive vote-cache parsing from hot render paths

---

### Bug Fixes

- **Blur clipping**: Blurred sensitive media no longer extends beyond the card boundaries
- **Stronger blur**: Sensitive blur intensity increased for better obscuring
- **Hide downvoted posts**: Setting now works correctly—posts you downvote on Home feed hide with a fade animation
- **Search results layout**: Post cards no longer overlap in search results
- **Time tooltip visibility**: Timestamps in compact mode no longer get hidden behind other cards
- **Settings page contrast**: Text now uses proper theme colors in light mode
- **Back navigation**: Clicking "Back" after viewing a post now correctly returns to the topic feed you came from
- **Follow button stability**: Follow/Unfollow no longer changes size on hover
- **Vote preference accuracy**: Comment votes now only affect author preference, not topic preference
- **Removed unused setting**: "Hide negative comments" option has been removed
