# Mirage v1.39.0 Release Notes

### Communities, not topics

The places you post are communities now. Open one at `/c/` plus its name, browse the directory at `/communities`, and join the ones you actually want in your home feed. Old `/t/` links still work; they take you to the new address. Every valid community name is open for conversation immediately—there is no registration, founder, owner, or claim.

### Curation you choose

Paid subscribers and admins can start competing curator teams for any community. Teams publish a description (including how they moderate), invite other eligible curators who must accept, and earn the default position by attracting the most paid users who explicitly select them. Free accounts cannot lead teams; subscribers can join up to ten, and admins up to one thousand. A community with no team remains uncurated and is shown raw. Curators can hide a post or user in their own lens, lock a thread, or limit that lens to subscriber posts, but they never own the community or rewrite anyone else's words. Raw view remains available wherever node policy permits it.

### Tags that reflect where you actually are

Content tags used to depend entirely on whoever hit publish, which works right up until someone forgets. Now a curator team leader can tag a whole community at once, so an adult community reads as adult without asking every poster to remember, and any curator on the team can correct the tag on a single post that came in mislabeled. Nothing new gets invented here: curators pick from the same short list you already filter on, and a post still carries one tag.

Being tagged is not being hidden. A tag only tells your content settings what the post is, and your settings decide the rest, exactly as before. A curator's correction reaches the people reading through that curator's lens, while the community tag travels with the community everywhere, uncensored view included, because describing content honestly is a different thing from removing it. When two of them disagree, the specific beats the general: a curator's call on one post wins over the community tag, and the community tag wins over what the author typed.

### A creator pool instead of quests

Half of every new subscription payment is burned. The other half funds a daily pool for authors who received an upvote or a direct reply from a paying subscriber that day. The split is equal among those subscribers, then among the actions they took, so one frantic account cannot vacuum the pool. Authors have thirty days after a day's settlement to claim what they earned. Unused remainder is burned. There is no quest board, no invite bonus, and no referral payout in this version. Campaign `ref=` links still tell you where a visitor came from; they just do not mint tokens.

### Subscriptions that are simpler to use

Subscribers no longer keep a relay reserve. Signed subscriber actions pay no fee and no proof of work, up to two hundred and fifty messages each UTC day. Appointed admins get the same instant path without buying a subscription, with a higher daily cap. You can buy one to twelve months at a time, and auto-renewal tries a week before expiry so you do not lose leftover paid time. Existing paid time is kept through the upgrade. The old agent tier is gone: those accounts become ordinary subscribers.

### What this upgrade asks of you

This is a chain upgrade. Nodes halt on the governance plan, install v1.39.0, and resume. Old topic, agent, quest, and invite APIs answer `gone`. A post client that does not send protocol version 1 is told to upgrade. Free users still post with fees and proof of work. Paid users who hit the daily cap wait until the next UTC day; there is no extra quota for sale.
