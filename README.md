# Mirage

**Mirage is what Reddit could have been if it hadn’t sold out.**

We are building true discourse without gatekeepers, decentralized by design and unstoppable in practice.

Instead of a corporate database, Mirage runs on **its own L1 blockchain** secured by battle-tested Tendermint-style consensus. This ensures that communities are durable, rules are transparent, and no single operator can rewrite history or erase your identity.

Crucially, **Mirage is not just for crypto users.** There are no wallets to install, no extensions to manage, and no coins to buy. You can start browsing and posting immediately; the cryptography is handled silently in the background.

---

## Why Mirage?

Centralized platforms are broken. Admins deplatform communities overnight, and **power-tripping moderators** silence dissent on a whim. On Reddit, a handful of unaccountable "super-mods" control the flow of information for millions of people.

Mirage fixes this by changing the architecture of internet discussion:

- **No Authoritarian Moderation**: moderation is separated from content hosting. No moderator can ban you from the network or delete your posts from the blockchain.
- **Node Choice**: if a node operator or their filters become tyrannical, you can simply switch to another node. Your history and social graph follow you seamlessly.
- **Voluntary Filters**: moderation is opt-in. You choose which filters to apply and which curators to trust.
- **Unfiltered Truth**: because the data lives on-chain, you can always run your own node to bypass all gatekeepers and see the raw reality of the network.
- **No Global Censorship**: transactions propagate across the decentralized network. A single operator can refuse to serve content on their specific node, but they cannot remove it from existence.

---

## How It Works

Most decentralized apps are hard to use. Mirage is different.

1. **Visit a Node**: Go to any public node (website) like [Mirage.vote](https://mirage.vote). It looks and feels like a normal forum.
2. **Create an Account**: No email or phone number required. Your browser generates a cryptographic key pair locally. This is your "account."
3. **Start Posting**: When you post, vote, or reply, your browser signs the action and performs a lightweight **Proof-of-Work** calculation. This prevents spam without requiring you to pay transaction fees or hold tokens.
4. **Permanent Record**: The node broadcasts your signed action to the blockchain. Once confirmed, it is permanent and replicated across the entire network.

---

## Why Run a Node?

Nodes are the backbone of the network, and the protocol rewards them directly.

- **Earn MIRAGE**: Node operators earn tokens simply for hosting a node, maintaining uptime, and strengthening the network's resilience.
- **Unfiltered Truth**: View the raw data directly from the blockchain. Bypass other nodes' filters and see exactly what is happening on the network.
- **Sovereignty**: Run a community on your own terms. Set your own rules, theme, and culture without answering to a central authority.
- **Resilience**: Help secure the global ledger. The more nodes exist, the harder the network is to stop.

---

## Key Features

### Zero Friction Entry (Free Tier)
- **No Wallet Needed**: The client manages keys transparently.
- **Proof-of-Work Anti-Spam**: Post for free by trading computational work for blockchain space.
- **Anonymous-by-Default**: Identities are cryptographic keys, not real-world profiles.

### Pro Tier (Token Powered)
- **Custom Usernames**: Claim a unique handle wthout the `Anon-` prefix from the free tier.
- **Priority Access**: Skip the Proof-of-Work and get guaranteed transaction inclusion.
- **Moderation Tooling**: Create filters others can subscribe to.

### Community Rewards
- **Invite & Earn**: Earn MIRAGE when people you invite become active.
- **Meritocracy**: Use tokens for upgrades and tipping.

---

## Get Started

### For Users
You don't need to install anything. Just visit a public node:

- **[mirage.talk](https://mirage.talk)** (Production Node)
- **[mirage.vote](https://mirage.vote)** (UAT/Public Node)

### For Node Operators
- [Deployment Guide](docs/guides/deploy.md)
- [Infrastructure Guide](docs/troubleshooting/infrastructure.md)
- **[Join the Mirage Portal](https://t.me/+5SILWcCke8tmODlh)** on Telegram to connect with the team and get setup help (especially if you want to run a node).

### For Developers
- **Backend**: Python (Flask), Go (Mirage chain)
- **Frontend**: React
- **Consensus**: CometBFT (Tendermint)

Start with the [API Documentation](docs/api-curl-examples.md).
