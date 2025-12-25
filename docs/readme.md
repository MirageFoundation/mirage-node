# Mirage

**The Decentralized Public Square**

Mirage is a sovereign, censorship-resistant social network that combines the familiar experience of Reddit with the unstoppable nature of a blockchain. It is built to ensure that online communities remain open, transparent, and free from the arbitrary control of corporate admins and power-hungry moderators.

---

## Why Mirage?

Centralized social platforms are broken. They are controlled by single entities that can—and do—silence voices, manipulate feeds, and erase communities overnight.

Mirage fixes this by changing the architecture of the internet discussion:

*   **Uncensorable**: Content is stored on a global blockchain ledger. No single admin, company, or government can delete it from the network.
*   **No Authoritarian Moderation**: Unlike Reddit where power-tripping mods can ban you on a whim, Mirage separates content hosting from moderation. No moderator can delete your posts from the blockchain. You choose who to follow and what filters to apply.
*   **Decentralized**: The network is powered by independent nodes. If one node blocks you, you can simply switch to another and your history, posts, and identity follow you.
*   **User-Owned**: You are not a product. There are no hidden algorithms manipulating your feed for ad revenue.

## Key Features

### Zero Friction Entry (Free Tier)
Mirage is the first decentralized platform that doesn't require you to buy crypto to participate.
*   **No Wallet Needed**: Start posting immediately.
*   **Proof-of-Work Anti-Spam**: Your device performs a lightweight calculation (Proof-of-Work) to authorize your posts.
*   **Anonymous Defaults**: Post with a generated "Anon-" identity or upgrade later.

### Pro Tier (Token Powered)
For power users who want more control and permanence.
*   **Custom Usernames**: Claim a unique, permanent handle (e.g., `@alice`).
*   **Priority Access**: Skip the Proof-of-Work and get guaranteed transaction inclusion.
*   **Moderation Tools**: Build your own moderation filters that others can subscribe to.

### Community Rewards
Grow the network and earn ownership in it.
*   **Invite & Earn**: Earn MIRAGE tokens when people you invite become active members of the community.
*   **Meritocracy**: Use your earned tokens to upgrade to Pro Tier or tip other users for quality content.

### Familiar Experience
Mirage looks and feels like the forums you know.
*   **Threaded Discussions**: Nested comments and rich text discussions.
*   **Voting System**: Upvote and downvote content to curate the community view.
*   **Multimedia**: Built-in support for images, video, and links.

---

## How It Works

Mirage uses a hybrid architecture to deliver speed and security:

1.  **The Blockchain (Core)**: A custom Cosmos SDK chain serves as the single source of truth. It records every post, vote, and username claim.
2.  **The Nodes (Gateways)**: Independent operators run "Nodes" that host the website and connect to the blockchain. Users access Mirage through these nodes (websites).
3.  **The User (You)**: You interact with the site just like any other social media. Your browser handles the cryptographic signing and Proof-of-Work in the background.

---

## Get Started

### For Users
You don't need to install anything. Just visit a public node to start browsing or posting:
*   **[Mirage.vote](https://mirage.vote)** (UAT/Public Node)
*   **[Mirage.talk](https://mirage.talk)** (Production Node)

### For Node Operators
Run your own Mirage node to help secure the network and provide a gateway for your community.
*   [Deployment Guide](guides/deploy.md) - Set up a node in minutes using Docker.
*   [Infrastructure Guide](troubleshooting/infrastructure.md) - Hardware requirements and network setup.

### For Developers
Mirage is open source and built on modern tech.
*   **Backend**: Python (Flask/FastAPI), Go (Cosmos SDK)
*   **Frontend**: React
*   **Consensus**: CometBFT

Check out the [API Documentation](api-curl-examples.md) to start building bots or alternative clients.

---

## Vision

Mirage is what the internet was meant to be: a place for free and open exchange of ideas, where the rules are transparent and the users are in control. By decoupling the interface (Nodes) from the data (Blockchain), we create a system where moderation is voluntary, communities are resilient, and speech is truly free.

**Coming Soon**: Mobile Apps (iOS/Android), Advanced Discovery, and Enhanced Moderation Tools.

Join us in building the future of online conversation.
