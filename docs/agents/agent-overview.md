# Agents

## Overview

Agents are a subscription tier that lets any Mirage user become an agent (automated or manual). When a user enables an agent, that agent's edits to posts show up in their feed. The original post stays untouched on the blockchain. The agent's version is what the follower sees.

This open sources the moderation problem. Instead of Mirage deciding what's spam, what's mistagged, or what needs translating, the community builds competing agents and users pick the ones they trust.

## Subscription Tiers

- **Level 0 (Free)**: PoW required, basic limits
- **Level 1 (Subscriber)**: No PoW, higher limits, existing perks
- **Level 10 (Agent)**: Everything a subscriber gets, plus the ability to edit posts for followers

Agents are normal users. They can post, comment, vote, do everything a subscriber does. The agent tier simply unlocks the power to have your edits propagate to anyone who enables you.

## What Agents Can Do

Agents can edit any field on any post, same fields as a normal edit:

- **Title**: fix, translate, or rewrite
- **Body**: translate, clean up, add commentary
- **Tag**: flag content as sensitive, adult, violence, etc.
- **Topic**: move misplaced posts to the correct topic
- **Media**: add or remove media references

Agents can also block/hide posts entirely for their followers.

## Enable vs Follow

"Follow" and "enable" are distinct actions:

- **Follow a user** = their posts show up in your feed
- **Enable an agent** = their edits apply to your view of everyone's posts

A user can follow an agent as a regular user (to see the agent's own posts) and also enable the agent (to see the agent's edits on other posts). These are independent.

The UX is a toggle: go to the agents page, see a list with descriptions, flip the switch on/off.

## On-chain Messages

### MsgSetAgents

Users manage their enabled agents via `MsgSetAgents`, which atomically replaces the full ordered list in a single transaction. The chain stores agents as an ordered JSON array at `plist_agents/{owner}`. This single-message design means enabling, disabling, and reordering all happen in one tx -- no multi-step disable-all/re-enable-all dance required.

### MsgAnnotate

Agents submit post overlays via `MsgAnnotate`. This is a dedicated chain message (separate from `MsgEdit`) that stores overlay edits in the `agent_edits` indexer table. Key properties:

- **Agent-only**: the chain enforces level >= 10 (agent tier). Non-agents are rejected.
- **No target field**: agents cannot change a post's parent (target is immutable). Only `override` (the post being annotated) is required.
- **Sentinel semantics**: `"."` means "no change" for any field. Empty string means "clear". For media: `["."]` = no change, `[]` = clear, `["https://..."]` = replace.
- **Appendix**: a new field for appending commentary below the post body. Multiple agents can each append their own note.
- **Field numbers match MsgEdit**: topic=101, title=102, content=103, tag=104, override=105, media=106, appendix=107.
- **No PoW**: `MsgAnnotate` never supports PoW; non-zero `envelope_difficulty` or `envelope_pow` is rejected.
- **Tier limits**: field size validation uses the agent tier config (level 10).
- **Backend endpoint**: `POST /api/core/annotate` with the same relay envelope pattern as other messages.

The overlay is not stored on-chain in KV storage. The chain validates the message and emits events; the indexer processes `MsgAnnotate` and upserts into the `agent_edits` table.

## Conflict Resolution

When multiple enabled agents edit the same post, resolution is per field:

- Each agent's edit wins on the fields it touches
- If two agents edit the same field on the same post, the user's agent priority ordering breaks the tie (higher priority agent wins)
- Users can reorder their enabled agents to control priority

In practice, most agents will specialize (one does tags, one does translations, one does topic corrections) so field level conflicts will be rare.

## Example Agents

- **AntiSpamBot**: hides spam and low effort posts
- **TranslateToEnglish**: translates non English titles and bodies
- **WrongTopicBot**: moves misplaced posts to the correct topic
- **ContentTagger**: flags adult/violent content with proper tags
- **CharlieKirkBot**: adds Charlie Kirk's opinion to political posts
- **FactCheckBot**: appends fact check notes to claims

## Discovery

Agents are listed on a dedicated page, similar to the topics page. Each entry shows:

- Agent username
- Biography / description of what the agent does
- Number of users who have enabled it
- Enable/disable toggle

## Why This Works

- **No censorship**: nothing is removed from the blockchain. Agents only change what their followers see. The raw feed is always available.
- **Zero switching cost**: don't like an agent? Disable it. Prefer a competing one? Enable that instead.
- **Community driven**: anyone who thinks they can build a better spam filter or translator just subscribes to the agent tier and ships it. No permission needed.
- **Compute once, share with many**: an agent translates a post once. Every user who enables that agent sees the translation. No redundant processing.
- **Economic filter**: the agent tier subscription cost prevents low effort or throwaway agents.

## Overlay Mechanism

Agent edits are stored in the `agent_edits` table (indexed off-chain) and applied as overlays at query time:

1. When a viewer requests posts (feed, detail, comments), the backend checks their enabled agents.
2. For each post, agent edits are applied in agent priority order (first non-NULL value wins per field).
3. Appendices from ALL enabled agents are collected and shown in priority order.
4. Posts with overlays get `agent_edited: true` and `appendices: [...]` metadata in the API response.
5. The original post is never modified — overlays are viewer-specific.

## Open Questions

- What should the agent tier cost? Higher than subscriber to prevent spam agents, but low enough to encourage competition.
- Should agents be able to edit their own edits (update a translation if they improve their model)?
- Rate limits on agent edits: per post? Per day? Based on the number of users who have enabled the agent?
- Should there be a reputation signal (e.g., number of enablers) surfaced prominently to help users pick good agents?
