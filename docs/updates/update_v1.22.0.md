# Mirage v1.22.0 Release Notes

### MsgUpgradeLevel Renamed to MsgSubscribe

The on-chain message for subscribing to a paid tier has been renamed from `MsgUpgradeLevel` to `MsgSubscribe` across the entire stack — proto definitions, chain handler, backend API, frontend, indexer, tests, and documentation. The rename reflects what the message actually does: it subscribes a user to a tier rather than "upgrading a level." All field tags remain identical, so the change is wire-compatible with no state migration required.

The backend API endpoint has moved from `/api/core/upgrade_level` to `/api/core/subscribe`. The frontend `TransactionHandler` method was renamed from `upgradeLevel()` to `subscribe()`. All canonical signing functions were updated accordingly.

### Subscription Gifting

Users can now gift a subscription to another address. When calling `MsgSubscribe` with a `target` field set to a different user's address, the sender pays the period fee and the recipient's subscription is extended by one subscription period.

Key behaviors:

- **Expiry stacking**: If the recipient already has an active subscription, the gift extends from their current expiry (not from now), so multiple gifts stack correctly.
- **Auto-renew preserved**: The recipient's `auto_renew` setting is never modified by a gift. If they had auto-renewal off, it stays off.
- **Higher-tier rejection**: Gifting a lower tier to someone who already has a higher tier is explicitly rejected on-chain (e.g., gifting Subscriber tier to someone who is already an Agent).
- **Self-subscribe unchanged**: Omitting the `target` field or setting it to your own address behaves exactly like before — a normal self-subscription.
- **Fee handling**: The sender's tokens are burned and escrowed in the same proportions as a normal subscription. The recipient's existing reserve funds are preserved (not burned on gift).

The frontend adds a "Gift subscription" option to the triple-dot menu on posts and profiles. The menu item shows the exact cost (e.g., "Gift 100.00K subscription"). Pending gift transactions are tracked with real-time status indicators ("Gifting...").

### Governance and Admin Subscriptions

Governance proposals continue to work as before: mint tokens to the target address, then submit a `MsgSubscribe` proposal with the target field set to the recipient. The governance module address acts as the authority and the target is the subscription recipient.

Admins (level >= 100) gift from their own accounts through the normal user flow.

### Valid Subscription Levels

`MsgSubscribe` is restricted to levels 1 (Subscriber) and 10 (Agent). Attempting to subscribe to any other level — including admin levels (100+) — is rejected both at the backend and on-chain.

### Backend Validation

The backend now validates gift requests before broadcasting:

- Invalid `target` addresses (not matching `mirage1[0-9a-z]{38}`) are rejected with 400.
- Gifts to higher-tier recipients are pre-checked against the indexer and rejected with 400, mirroring the chain-level rejection.
- If the indexer is unavailable during the pre-check, the request returns 503 (fail-closed).

### Upgrade Instructions

The upgrade name is `v1.22.0` and the binary must be built from the `v1.22.0` tag. No state migration is required. The rename is wire-compatible — existing on-chain data and protobuf field tags are unchanged.

All clients (frontend, backend, indexer) must be updated to use the new message name and API endpoint. The old `/api/core/upgrade_level` endpoint no longer exists.
