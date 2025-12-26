# Mirage v1.7.3 Release Notes

### Overview

v1.7.3 introduces **Magic 2** and **Magic 3**, two new feed algorithms built from the ground up. The original magic algorithm grew complex over time with its bucket interleaving, topic preferences, and second-chance mechanics. These new algorithms strip all that away in favor of a single, unified score that's easy to understand and reason about.

The philosophy is simple: one score, computed from a handful of signals, multiplied by recency decay. No hard cutoffs, no arbitrary position rules—just soft decay curves that naturally surface fresh, engaging content. A 3-day old post with no comments won't appear at the top of your feed anymore, and posts with 50 upvotes will rank meaningfully higher than posts with 10.

Both algorithms are available from the dropdown on your Home or Following feed. Magic 2 ignores your topic/author preferences in scoring, while Magic 3 factors them in.

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

Compact card mode (Settings → Appearance → Card size) has been significantly improved:

- **Tighter card padding**: Reduced internal spacing on all sides
- **Smaller gaps between cards**: Cards stack closer together
- **Reduced internal margins**: Less whitespace around titles, meta info, and action rows
- **Thumbnail alignment fix**: Thumbnails now properly align with the top of text content

---

### Infinite Scroll Improvements

The feed now loads the next page earlier—when you're about 5-6 posts from the bottom instead of 2-3. This creates a smoother scrolling experience with fewer visible loading states.

---

### Upgrade Path

Standard Docker deployment. No database migrations required.

```bash
./deploy/deploy.sh --update-init
```

