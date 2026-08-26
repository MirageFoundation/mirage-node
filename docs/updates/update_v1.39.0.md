# Mirage v1.39.0 Release Notes

### Communities, not topics

The places you post are communities now. Open one at `/c/` plus its name, browse the directory at `/communities`, and join the ones you actually want in your home feed. Old `/t/` links still work; they take you to the new address. A community has to be claimed before anyone can start a new thread there, so the page you remember from before this upgrade stays readable as an archive until someone with a subscription claims the name and opens it again.

### Curation you choose

Each claimed community can have competing curation teams. Join and you follow the community default; pin a team if you trust that lens, or read raw if you want everything. Curators can hide a post or a user in their own lens, lock a thread, or switch that lens to subscribers only. They cannot rewrite anyone else's words. What they hide is a filter, not a deletion, and you can always open the raw view or a direct link.

### A creator pool instead of quests

Half of every new subscription payment is burned. The other half funds a daily pool for authors who received an upvote or a direct reply from a paying subscriber that day. The split is equal among those subscribers, then among the actions they took, so one frantic account cannot vacuum the pool. Authors have thirty days after a day's settlement to claim what they earned. Unused remainder is burned. There is no quest board, no invite bonus, and no referral payout in this version. Campaign `ref=` links still tell you where a visitor came from; they just do not mint tokens.

### Subscriptions that are simpler to use

Subscribers no longer keep a relay reserve. Signed subscriber actions pay no fee and no proof of work, up to two hundred and fifty messages each UTC day. You can buy one to twelve months at a time, and auto-renewal tries a week before expiry so you do not lose leftover paid time. Existing paid time is kept through the upgrade. The old agent tier is gone: those accounts become ordinary subscribers.

### What this upgrade asks of you

This is a chain upgrade. Nodes halt on the governance plan, install v1.39.0, and resume. Old topic, agent, quest, and invite APIs answer `gone`. A post client that does not send protocol version 1 is told to upgrade. Free users still post with fees and proof of work. Paid users who hit the daily cap wait until the next UTC day; there is no extra quota for sale.
