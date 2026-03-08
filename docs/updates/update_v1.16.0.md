# Mirage v1.16.0 Release Notes

### Moderation Belongs to You Now

Every social network has moderation. Most of them hide it behind a corporate trust-and-safety team you never chose and can never fire. Mirage v1.16.0 flips that model: moderation is now a service anyone can offer, and every user decides whose moderation they want. No one is forced to see filtered content, and no one is forced to see unfiltered content. You build your own lens.

The new Agent tier lets any user become a moderation agent on the network. Agents can annotate any post with title corrections, translated or cleaned-up body text, content-warning tags, replaced media, or an appendix — a note appended below the original content for fact-checks, added context, or corrections. The original post is never rewritten. Every overlay sits on top, clearly attributed to the agent who wrote it, and the unmodified original is always one tap away. Agents can also block posts, users, and topics on behalf of the people who enable them — if you trust an agent's judgment, their blocks become your blocks.

### How It Works

You browse the new Agents screen to see every available agent on the network, read their biography, and enable or disable them with one tap. Enabled agents appear at the top of the list and can be reordered by priority — order matters, because when two agents edit the same field on a post, the one higher in your list wins. Appendices from multiple agents all show up, ordered by your priority list. You cannot enable yourself as your own agent, because the whole point is external curation, not talking to yourself. Free accounts can enable up to five agents, Subscribers get fifty, and Agents also get fifty. The barrier to becoming an agent is a 500,000 MIRAGE subscription per 30-day period — high enough to filter out spam, low enough that anyone with skin in the game can participate.

### Why This Matters

This is the endgame of opt-in moderation. There is no central authority deciding what you see. There is no algorithm quietly suppressing posts. Instead, there is a marketplace of curators competing on reputation. A fact-checking agent, a language-translation agent, a NSFW-tagging agent, a community elder who just has good judgment — all of them coexist, and you pick the combination that matches your values. If an agent does a bad job, you disable them and their overlays vanish from your feed instantly. If a new agent earns trust, the community can adopt them overnight. Moderation becomes a service you subscribe to, not a policy imposed on you.

### Three Tiers, One Clear Path

The old four-tier lineup (Free, Trusted, Established, Distinguished) is gone. In its place: Free, Subscriber, and Agent. Free costs nothing and gives you the essentials — posting up to 1,000 characters, following 25 users or topics, and enabling up to 5 agents. Subscriber runs 100,000 MIRAGE per 30-day period and unlocks biographies, 20,000-character posts, 500 follows and blocks, 50 agents, and the ability to drop the "Anon-" prefix from your username. Agent costs 500,000 MIRAGE per period and adds everything Subscriber has plus the ability to act as a moderation agent that others can enable. Free accounts always carry an "Anon-" prefix — upgrading to Subscriber or higher lets you choose any name you want. Ninety-five percent of every subscription fee now goes directly into your relay gas reserve, up from eighty percent, so more of what you pay actually funds your on-chain activity.

### Identity First

Every user-initiated action on the chain now requires a username. Posting, voting, following, blocking, awarding, sending tokens, upgrading your subscription — all of it. If you haven't set a username yet, the chain rejects the transaction with a clear message telling you to pick one first. This tightens accountability across the network: every action traces back to a named identity rather than a bare address. Combined with agents, it means every overlay is attributable to a real, staked username — not an anonymous flag.

### Fairer Fees, Bigger Rewards

Relay gas is now metered per message instead of per transaction. Previously, batching multiple actions into a single transaction overcharged your reserve because the full transaction gas was deducted for each message. Now each action pays only for the gas it actually consumed, capped at 500 MIRAGE per message. The minimum gas price dropped from 5,000 to 1,000 umirage per gas unit — a five-fold reduction that makes every action on the network noticeably cheaper. Vote weights align with the new tier structure — Subscribers and Agents vote at 1.33x, Free at 1.0x. The reward multiplier now counts flash quests and achievements alongside daily quests, so short-burst challenges and long-term milestones both help you earn faster.
