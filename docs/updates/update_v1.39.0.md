# Mirage v1.39.0 Release Notes

### Open communities

The places you post are communities now. Every valid community name is open for conversation immediately, with no registration, founder, owner, or claim. Join the communities you want in your home feed and choose the view that suits you.

### Curation without ownership

Paid subscribers and appointed admins can form competing curator teams for any community. Teams can organize posts, apply familiar content tags, hide material from their own lens, and lock a thread from that point forward, but they never own the community or rewrite anyone else's words. A lock filters one team's view rather than blocking replies, and raw view remains available wherever node policy permits it. Community-wide tags still describe content in raw view; a team's per-post overrides do not.

### Creator rewards

Half of every new subscription payment is burned, and half funds authors who receive an upvote or direct reply from a paying subscriber. Creator periods begin at six-hour intervals, split rewards so one highly active account cannot take the whole pool, and leave earnings claimable for thirty days before unused funds are burned. Governance may change the interval without shortening subscriptions or existing claim windows. Quests, invite bonuses, and referral payouts are retired.

### Simpler subscriptions

Subscribers no longer maintain a relay reserve. They receive up to 1,000 zero-fee relays per UTC day, while appointed admins receive up to 10,000; free users continue with fees and proof of work. Subscriptions can cover one to twelve months, renew early without losing paid time, and carry existing paid time through the upgrade. The old Agent tier is gone, and eligible Agent accounts become ordinary subscribers.

### History stays readable

Posts made before v1.39 remain readable alongside current conversations. Older threads created before the upgrade remain read-only for new replies, even after a client update, because they lack the on-chain parent details needed to validate a safe reply; users can start a new community thread instead. A delete now stays deleted after an edit, and the upgrade repairs older posts that the network can prove were accidentally revived. Very old posts created before deletion metadata existed cannot always be distinguished from legitimate content, so those ambiguous cases remain.

### Coordinated chain upgrade

This release changes consensus. Validators must install v1.39.0 for the governance halt and resume together; mixed v1.38 and v1.39 binaries cannot safely process the same blocks. The currently published mobile app receives a temporary bridge for its topic-era reads, posts, subscriptions, and community actions while the replacement reaches users, but new clients must use the community format. Agents, quests, invite rewards, and referrals remain retired. Users who reach their daily relay cap wait for the next UTC day; additional quota is not sold.
