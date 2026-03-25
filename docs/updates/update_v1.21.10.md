# Mirage v1.21.10 Release Notes

### Database separation

The backend and the indexer no longer share a single database. Chain-indexed data — posts, votes, profiles, balances, everything the indexer writes — stays in its own database. Operational data that the backend owns — quests, rewards, push notifications, invite codes, reports, user activity — now lives in a dedicated backend database. The backend connects to the indexer database through a read-only PostgreSQL role, so even a bug in the backend code cannot corrupt chain-indexed state. This is the kind of change you never notice as a user, but it means a misbehaving feature on the backend side can never silently wreck the data that every node in the network depends on.

A one-time migration runs automatically on upgrade and copies all backend-owned rows from the old shared database into the new one. The databases are named consistently: `mirage_indexer` for chain data and `mirage_backend` for backend data. Each database has its own PostgreSQL role (`mirage_indexer`, `mirage_backend`), plus a `mirage_indexer_ro` role for the backend's read-only connection to the indexer. The entrypoint handles renaming from legacy names automatically. A new verification script (`scripts/verify_upgrade.py`) checks schema correctness, data migration completeness, read-only enforcement, and API health in one pass — run it after any upgrade to confirm everything landed cleanly.

### Cross-node push notifications

Push notifications used to fire only when a transaction passed through the same node you were connected to. If someone replied to your post from a different node, your phone stayed silent. That is fixed. The backend now runs a background listener that polls the indexer for new on-chain posts and awards regardless of which node relayed them. If a reply or award targets one of your posts, you get the push. The listener deduplicates events so you never get the same notification twice, and only one worker thread runs the listener across all backend processes to keep database load minimal.

### Real activity tracking

The "active users" number on the welcome page used to count browser page views, which was noisy and easy to inflate. It now counts distinct users who hit any authenticated API endpoint in the last 24 hours — actual logged-in activity, not passive page loads. A lightweight `user_last_seen` table updates on every authenticated request, throttled to one write per user per minute so it adds near-zero overhead. The same data powers the stats dashboard.

### Account creation cleanup

The `/create_account` endpoint is gone. Account creation now goes through `/signup` — shorter, cleaner, and the only path. The old endpoint returns nothing, no redirects, no legacy compatibility. The frontend route was updated to match. If you have bookmarks or scripts pointing at `/create_account`, update them.

### Content tag filtering

A round of fixes to how content tags (sensitive, gore, etc.) interact with feeds. Tags are now filtered correctly in topic feeds, user post lists, comment trees, and agent-edited posts. Previously, `allowed_tags` filtering ran before agent edits, so an agent rewriting a post could bypass tag restrictions. Filtering now runs after edits. Posts by the logged-in user always appear in their own feeds regardless of tag settings — you should always see your own content.

### Feed improvements

Your own posts now interleave naturally into the Magic feed instead of being pinned to the top. The old behavior pushed your latest post above everything else regardless of relevance, which looked odd when scrolling. Posts from blocked topics are properly excluded from all feed types. Hashtags in posts and comments are now clickable links — `#technology` takes you straight to `/t/technology`.

### Node operator improvements

The indexer WebSocket reconnect loop no longer burns CPU when the node is temporarily unreachable. Video resize handles work properly on desktop. Per-platform app download banners can be toggled independently for iOS and Android via `frontend.env`. The test suite retries transient 429 and 500 errors instead of failing immediately, and agent-related tests use polling instead of fixed sleeps. A new `scripts/deploy_all_prod.sh` script streamlines multi-node production deploys.
