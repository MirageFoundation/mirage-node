# Mirage v1.22.0 Release Notes

### Gift a Subscription

You can now gift subscriptions to other users directly from a post. Tap the triple-dot menu, pick "Gift subscription," and the recipient gets a full subscription period paid for by you. The cost is shown upfront so there are no surprises, and the confirmation tells you the exact date the subscription will run through.

Gifts stack. If someone already has an active subscription, your gift extends it from where it currently ends, not from today. Two gifts back-to-back give two full periods. The recipient's auto-renewal setting is never touched — if they had it off, it stays off. You cannot downgrade someone either: if they are already on a higher tier, the chain rejects the gift outright and your tokens stay in your wallet.

Governance can gift subscriptions too, so the community can vote to sponsor contributors, moderators, or anyone who deserves it. All of this runs on-chain with the same burn-and-escrow mechanics as a regular subscription — no special rules, no backdoors.

### Donations and Follows in Your Inbox

When someone sends you MIRAGE or starts following you, it now shows up in your inbox alongside replies and awards. Push notifications fire for both, so you know the moment someone tips your post or joins your audience. This works whether the sender used the web wallet, the CLI, or any other tool — the indexer picks up every on-chain transfer and turns it into a notification.

The donate flow has a 10,000 MIRAGE minimum and is available from post menus, the full post view, and profile pages. Guests are prompted to log in first. Pending donations show real-time queue status just like votes and posts.

### Cleaner Mobile Experience

Post cards on mobile got a facelift. When a post has an image, the title now sits below the thumbnail instead of overlaid on top of it, so you can actually read both. Images no longer stretch awkwardly on narrow screens — they scale proportionally with consistent spacing regardless of device width.

### Smaller, Leaner Nodes

State-sync snapshot retention dropped from 28 to 4. That wipes out 24 full-state dumps that were quietly eating disk on every node in the network. Four snapshots still give a 24-hour window for new nodes to state-sync, which is plenty. The blockstore still keeps 7 days of history — that part is unchanged. Node operators should see a noticeable drop in disk usage over the next day as old snapshots are pruned.

The deploy pipeline now applies config changes from migrations on the same startup instead of requiring a second restart. One deploy, one restart, everything takes effect.

### Bug Fixes

Paginated feeds with tag filters no longer stop loading early. A short filtered page used to trick the backend into thinking there was nothing left — that is fixed. The database sequence drift from the v1.21.10 DB split has been patched so insert conflicts cannot recur. The referral client-hash gate that was temporarily off for testing is back on. And the gift subscription dialog no longer says "Extend until..." when the recipient has no subscription — it just says "Until..." for new subs.

### iOS Deep Links

Universal Links on iOS now cover `/referrals`, `/blocks`, `/login`, `/follows`, and `/`. If you have the app installed, tapping these links opens them natively instead of bouncing through the browser.

---

## Upgrade Instructions

The chain upgrade name is `v1.22.0` and the binary must be built from the `v1.22.0` tag. No state migration is required — the subscribe rename is wire-compatible. All clients (frontend, backend, indexer) must be updated simultaneously. The old `/api/core/upgrade_level` endpoint no longer exists.
