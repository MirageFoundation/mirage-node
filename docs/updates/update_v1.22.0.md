# Mirage v1.22.0 Release Notes

## Chain Upgrade: MsgSubscribe + Subscription Gifting

### MsgUpgradeLevel Renamed to MsgSubscribe

The on-chain message for subscribing to a paid tier has been renamed from `MsgUpgradeLevel` to `MsgSubscribe` across the entire stack — proto definitions, chain handler, backend API, frontend, indexer, tests, and documentation. The rename reflects what the message actually does: it subscribes a user to a tier rather than "upgrading a level." All field tags remain identical, so the change is wire-compatible with no state migration required.

The backend API endpoint has moved from `/api/core/upgrade_level` to `/api/core/subscribe`. The frontend `TransactionHandler` method was renamed from `upgradeLevel()` to `subscribe()`. All canonical signing functions were updated accordingly.

### Subscription Gifting

Users can now gift a subscription to another address. When calling `MsgSubscribe` with a `target` field set to a different user's address, the sender pays the period fee and the recipient's subscription is extended by one subscription period.

Key behaviors:

- **Expiry stacking**: If the recipient already has an active subscription, the gift extends from their current expiry (not from now), so multiple gifts stack correctly.
- **Auto-renew preserved**: The recipient's `auto_renew` setting is never modified by a gift. If they had auto-renewal off, it stays off.
- **Higher-tier rejection**: Gifting a lower tier to someone who already has a higher tier is explicitly rejected on-chain and at the backend (e.g., gifting Subscriber tier to someone who is already an Agent).
- **Self-subscribe unchanged**: Omitting the `target` field or setting it to your own address behaves exactly like before — a normal self-subscription.
- **Fee handling**: The sender's tokens are burned and escrowed in the same proportions as a normal subscription. The recipient's existing reserve funds are preserved (not burned on gift).

The frontend adds a "Gift subscription" option to the triple-dot menu on posts. The menu item shows the exact cost (e.g., "Gift 100.00K subscription"). Pending gift transactions are tracked with real-time status indicators ("Gifting...").

### Backend Gift Validation

The backend validates gift requests before broadcasting:

- Invalid `target` addresses (not matching `mirage1[0-9a-z]{38}`) are rejected with 400.
- Gifts to higher-tier recipients are pre-checked against the indexer and rejected with 400, mirroring the chain-level rejection.
- If the indexer is unavailable during the pre-check, the request returns 503 (fail-closed).

### Governance Subscriptions

Governance proposals can now target a specific user address for subscription via `MsgSubscribe` with a `target` field. The governance module address acts as the authority and the target is the subscription recipient. The standard governance flow is: mint tokens to the target, then submit a `MsgSubscribe` proposal.

`MsgSubscribe` is restricted to levels 1 (Subscriber) and 10 (Agent). Attempting to subscribe to any other level — including admin levels (100+) — is rejected both at the backend and on-chain.

---

## Donation Notifications and Pending Sends

Token sends (donations) and follows now appear in the inbox with push notifications.

- **Inbox**: Shows follow events ("started following you") and donation events ("sent you X MIRAGE") alongside existing reply and award notifications. Combined list is sorted chronologically with unified pagination.
- **Push notifications**: Sent for follows and donations. Works for sends made through the web wallet and for on-chain transfers indexed from any source (CLI, other nodes).
- **Pending send tracking**: The frontend tracks in-flight `send_tokens` transactions with queue-style status indicators, matching the pattern used for other transaction types.
- **Donate UI**: Minimum 10,000 MIRAGE per donation. Guests are prompted to log in. The donate flow is available from post menus, the view-post page, and profile pages.
- **Push listener expansion**: The background push listener now polls `tx_index` for `send_tokens` and `multi` transactions, parses transfers from raw logs, writes inbox events, and sends donation pushes — covering sends that don't go through the web wallet API.

---

## Mobile UI Improvements

### Card Layout

On mobile, post cards with images now show the title below the thumbnail instead of overlaid on the image. Text-only cards are unchanged.

### Image Rendering

Fixed image stretching on narrow screens. Images now use `aspect-ratio` with `maxHeight` and `objectFit: 'cover'` instead of explicit pixel heights, producing more predictable vertical spacing without distortion.

---

## Bug Fixes

### Infinite Scroll with Tag Filtering

Fixed a bug where paginated feeds would stop loading early when tag filtering was enabled. The backend no longer sets `has_more = false` prematurely when filtered results produce a short page.

### DB-Split SERIAL Sequence Drift

After the v1.21.10 database split, SERIAL sequences for backend-owned tables (`pending_rewards`, `referral_*`, `reports`, `push_*`, etc.) could drift below the actual max ID, causing primary key conflicts on insert. The schema init now resets all SERIAL sequences to `MAX(id)`, and the migration script does the same post-migration.

### Referral Client Hash Gate

The referral `client_hash` abuse-prevention gate was temporarily disabled for testing and has been re-enabled. Users are again blocked from reusing the same referrer from the same client fingerprint.

---

## Platform Integration

### iOS Deep Links (AASA)

Added missing paths to the Apple App Site Association file: `/referrals`, `/blocks`, `/login`, `/follows`, and `/`. Universal Links on iOS can now open these routes in the app when installed.

---

## Indexer

The indexer now stores the Comet `raw_log` field in `tx_index`, enabling the push listener to parse transfer events from any transaction type.

---

## Upgrade Instructions

The chain upgrade name is `v1.22.0` and the binary must be built from the `v1.22.0` tag. No state migration is required — the MsgSubscribe rename is wire-compatible (same field tags). All clients (frontend, backend, indexer) must be updated simultaneously. The old `/api/core/upgrade_level` endpoint no longer exists.
