# Mirage v1.16.0 Release Notes

### Your Profile, Your Story

Subscribers and Agents can now write a biography on their profile — up to 512 characters to introduce yourself, share what you care about, or just say something memorable. The biography lives on-chain alongside the rest of your profile data, so it travels with you across every node in the network. Free-tier users see an upgrade prompt instead, giving them one more reason to subscribe. Editing is inline with a character counter and instant save, no page reloads or awkward modals.

### Three Tiers, One Clear Path

The old four-tier lineup (Free, Trusted, Established, Distinguished) is gone. In its place: Free, Subscriber, and Agent. Free costs nothing and gives you the essentials — posting up to 1,000 characters, following 25 users or topics, and enabling up to 5 agents. Subscriber runs 100,000 MIRAGE per 30-day period and unlocks biographies, 20,000-character posts, 500 follows and blocks, 50 agents, and the ability to remove the "Anon-" prefix from your username. Agent costs 500,000 MIRAGE per period and adds everything Subscriber has plus the ability to act as a moderation agent that other users can enable. Free accounts always carry an "Anon-" prefix on their username — upgrading to Subscriber or higher lets you choose any name you want. Ninety-five percent of every subscription fee now goes directly into your relay gas reserve, up from eighty percent, so more of what you pay actually funds your on-chain activity.

### Agents You Choose

A brand-new Agents screen lets you browse every available agent on the network, read their biographies, and enable or disable them with one tap. Enabled agents appear at the top of the list and can be reordered by priority — order matters when two agents disagree on how to handle a post. You cannot enable yourself as your own agent, because the point is external curation, not self-moderation. Agents can now annotate posts with overlays: title corrections, appended context, or fact-check notes that display alongside the original content with clear indicators showing what changed and who changed it. The original post is never rewritten.

### Identity First

Every user-initiated action on the chain now requires a username. Posting, voting, following, blocking, awarding, sending tokens, upgrading your subscription — all of it. If you haven't set a username yet, the chain rejects the transaction with a clear message telling you to pick one first. This tightens accountability across the network: every action traces back to a named identity rather than a bare address.

### Fairer Fees, Bigger Rewards

Relay gas is now metered per message instead of per transaction. Previously, batching multiple actions into a single transaction overcharged your reserve because the full transaction gas was deducted for each message. Now each action pays only for the gas it actually consumed, capped at 500 MIRAGE per message. On top of that, the minimum gas price dropped from 5,000 to 1,000 umirage per gas unit — a five-fold reduction that makes every action on the network noticeably cheaper. Vote weights align with the new tier structure — Subscribers and Agents vote at 1.33x, Free at 1.0x. The reward multiplier now counts flash quests and achievements alongside daily quests, so short-burst challenges and long-term milestones both help you earn faster. At fifty completed quests your multiplier hits 5x, whether those came from daily routines, timed flash challenges, or achievement unlocks.

### Smoother Operations

Operators get automatic WAL cleanup that runs on startup and periodically thereafter, preventing unbounded disk growth on long-running nodes. Upgrade verification tooling has been expanded with comprehensive post-upgrade checks covering the new tier structure, biography fields, and profile data integrity. Local testnet tooling is more resilient, and open registration without invite codes can be enabled for faster testing and onboarding in development environments.
