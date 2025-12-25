# Mirage vs. The Landscape of Decentralized Social Media

The quest for a "decentralized Reddit/Twitter" has produced many contenders. While they share the goal of escaping Big Tech control, they differ fundamentally in architecture.

This document analyzes the most common alternatives and explains why Mirage chose a dedicated Layer 1 blockchain architecture.

## 1. The Federated Model (Mastodon, Lemmy, Pixelfed)

**Architecture**: A network of independently run servers (instances) that talk to each other via ActivityPub.

**The Good**:
*   Easy to join (just sign up with an email).
*   Moderation is handled locally by admins, keeping communities "safe" or "focused".
*   Low cost to run a small instance.

**The Bad (The "Digital Feudalism" Problem)**:
*   **Admin Tyranny**: You are a serf on someone else's server. The admin can ban you, delete your account, and read your DMs.
*   **Defederation**: If an admin dislikes another server, they can "de-federate" (block) it entirely. Your ability to communicate is limited by your admin's politics.
*   **Migration Pain**: Moving to a new server is not seamless. You often lose your post history, and not all followers will migrate correctly.
*   **Data Fragility**: If an instance shuts down (admin gets bored, runs out of money, or gets sued), all data on that instance vanishes.

**Mirage Difference**:
Mirage is **not federated**; it is **replicated**. Every node has the *entire* history. If a node operator bans you from their UI, your data still exists on the blockchain and can be accessed via any other node. No single admin can delete your existence.

## 2. The Relay Model (Nostr)

**Architecture**: Dumb servers ("relays") store and forward signed text notes. Clients choose which relays to listen to.

**The Good**:
*   Extremely censorship-resistant (just find a new relay).
*   Simple, key-based identity.

**The Bad**:
*   **Data Availability**: There is no global consensus. If the relays you posted to go offline, your content is gone.
*   **UX Complexity**: Managing relay lists and syncing state across devices is difficult for normal users.
*   **Spam**: Without inherent cost (like PoW or fees), relays are often flooded with spam.

**Mirage Difference**:
Mirage provides **global consensus**. When a post is confirmed, it is confirmed by the network, not just stored on a specific hard drive. We use Proof-of-Work (like Bitcoin) to prevent spam without requiring users to manage relay lists.

## 3. First-Gen Social Blockchains (Steem, Hive)

**Architecture**: Layer 1 blockchains where every upvote is a financial transaction.

**The Good**:
*   Immutable data.
*   Rewards creators.

**The Bad**:
*   **Plutocracy**: "Stake-weighted voting" means rich users decide what is popular. If a whale dislikes you, they can "nuke" your reputation.
*   **Hyper-Financialization**: Every interaction feels like a transaction. Communities become click-farms rather than discussion spaces.
*   **Onboarding**: Often requires buying tokens or complex account creation.
*   **Centralization**: Relies on a fixed set of block producers (e.g., 21 witnesses), making the network prone to cartel-like behavior and difficult to join as a node operator.

**Mirage Difference**:
Mirage uses **Proof-of-Work for access**, not stake. A billionaire's upvote counts the same as a fresh user's upvote (in terms of social signal, though reputation systems can layer on top). We separate "money" from "speech"—you don't need to buy tokens to post.

## 4. The Hybrid Model (Farcaster, Lens)

**Architecture**: Identity on-chain (Ethereum/Optimism/Polygon), content off-chain (Hubs or Arweave/IPFS).

**The Good**:
*   Owning your social graph (followers).
*   Good mobile apps (initially).

**The Bad**:
*   **Failed Product-Market Fit**: After years of development, these platforms have largely failed to gain traction, with teams pivoting or effectively abandoning the original vision.
*   **Cost & Complexity**: High gas fees or subscription models ($5/year) created friction that prevented mass adoption.
*   **Storage guarantees**: "Hubs" eventually prune data. Old posts may disappear if not pinned elsewhere.

**Mirage Difference**:
Mirage uses a **sovereign L1 for identity**, ensuring you own your social graph without paying rent to Ethereum validators. Unlike hybrid models that rely on third-party "hubs" or confusing L2 bridges, Mirage's architecture is integrated: nodes index content directly from the network, and your cryptographic identity works seamlessly across any node you choose.

## Summary

| Feature | Mirage | Federated (Lemmy/Mastodon) | Relays (Nostr) | Social L1 (Steem) |
| :--- | :--- | :--- | :--- | :--- |
| **Data Storage** | **On-Chain Identity** | Admin's Database | Specific Relay | On-Chain Identity |
| **Censorship** | **Unstoppable** | Admin can ban/delete | Relay can ban | Whale downvotes |
| **Decentralization** | **High (Open Set)** | Low (Federated) | Medium | Low (21 Nodes) |
| **Onboarding** | **Very Easy (PoW)** | Easy (Email) | Complex (Keys+Relays) | Funded Wallet Required |
| **Permanence** | **High** | Low (Server death) | Medium (Relay death) | High |
| **Portability** | **Seamless** | Difficult (Migration) | Easy | Seamless |
| **Cost to Post** | **PoW** | Free | Free (usually) | Staked Tokens |
| **Moderation** | **Voluntary/Opt-in** | Authoritarian | Client-side | Stake-based |

Mirage uses a **hybrid storage model**:
*   **Identity & Social Graph**: Stored on-chain in the global state. This means your username, follows, and blocks are replicated by every validator and cannot be deleted.
*   **Content (Posts)**: Stored by nodes. While the transaction hash is permanent on-chain (proof of existence), the actual content is indexed by nodes. If one node refuses to serve a post, your identity allows you to seamlessly switch to another node that does.

Mirage is built for **resilience**. We believe that for speech to be truly free, the underlying infrastructure must be unable to discriminate.

