# Mirage

**Mirage is what Reddit could have been if it hadn’t sold out.**

We are building true discourse without gatekeepers, decentralized by design and unstoppable in practice.

Instead of a corporate database, Mirage runs on **its own L1 blockchain** secured by battle-tested Tendermint-style consensus. This ensures that communities are durable, rules are transparent, and no single operator can rewrite history or erase your identity.

Crucially, **Mirage is not just for crypto users.** There are no wallets to install, no coins to buy, and no transaction fees to pay.

Instead, Mirage uses a **Proof-of-Work (PoW)** handshake to combat spam. Your device silently solves a cryptographic puzzle in the background to "pay" for your post. This allows for a completely permissionless, free-to-use network that remains resistant to bot attacks—solving the biggest problem of decentralized social media.

---

## Why Mirage?

Centralized platforms are broken. Admins deplatform communities overnight, and **power-tripping moderators** silence dissent on a whim. On Reddit, a handful of unaccountable "super-mods" control the flow of information for millions of people.

Mirage fixes this by changing the architecture of internet discussion:

- **No Authoritarian Moderation**: moderation is separated from content hosting. No moderator can delete your identity or social graph.
- **Node Choice**: if a node operator or their filters become tyrannical, you can simply switch to another node. Your identity and social graph follow you seamlessly.
- **Voluntary Filters**: moderation is opt-in. You choose which filters to apply and which curators to trust.
- **Unfiltered Truth**: because your identity and graph are not owned by any one website, you can always run your own node to bypass gatekeepers and see the raw reality of the network.
- **No Global Censorship**: a single operator can refuse to serve content on their specific node, but they cannot erase your identity from the network.

---

## How It Works

Most decentralized apps are hard to use. Mirage is different.

1. **Visit a Node**: Go to any public node (website) like [mirage.talk](https://mirage.talk). It looks and feels like a normal forum.
2. **Create an Account**: No email or phone number required. Your browser generates a cryptographic key pair locally. This is your "account."
3. **Start Posting**: When you post, vote, or reply, your browser signs the action and performs a lightweight **Proof-of-Work** calculation. This prevents spam without requiring you to pay transaction fees or hold tokens.
4. **Permanent Record**: The node broadcasts your signed action to the network. Once confirmed, its existence is permanent, and nodes can index and serve it.

---

## Why Run a Node?

Nodes are the backbone of the network, and the protocol rewards them directly.

- **Earn MIRAGE**: Node operators earn tokens simply for hosting a node, maintaining uptime, and strengthening the network's resilience.
- **Unfiltered Truth**: View the raw data directly from the chain and your node’s local index. Bypass other nodes' filters and see exactly what is happening on the network.
- **Sovereignty**: Run a community on your own terms. Set your own rules, theme, and culture without answering to a central authority.
- **Resilience**: Help secure the global ledger. The more nodes exist, the harder the network is to stop.

---

## Key Features

### Zero Friction Entry (Free Tier)
- **No Wallet Needed**: The client manages keys transparently.
- **Proof-of-Work Anti-Spam**: Post for free by trading computational work for blockchain space.
- **Anonymous-by-Default**: Identities are cryptographic keys, not real-world profiles.

### Pro Tier (Token Powered)
- **Custom Usernames**: Claim a unique handle without the `Anon-` prefix from the free tier.
- **Priority Access**: Skip the Proof-of-Work and get guaranteed transaction inclusion.
- **Moderation Tooling**: Create filters others can subscribe to.

### Community Rewards
- **Invite & Earn**: Earn MIRAGE when people you invite become active.
- **Meritocracy**: Use tokens for upgrades and tipping.

---

## Mirage vs. The World

Most “decentralized social” projects are forced to choose:

> If posting is free, bots will spam you. If posting costs money, onboarding dies.

Mirage uses **PoW** so normal users can post immediately without paying, while bots can’t spam at scale without burning real compute.

Here’s how Mirage compares to the main alternatives people actually use (we cover more, like Nostr and hybrid crypto social, in `docs/comparison.md`):

| Dimension | Mirage | Centralized (Discuit/Tildes/etc.) | Federated (Lemmy/Mastodon/kbin/PieFed) | Social L1 (Steem/Hive) |
| :--- | :--- | :--- | :--- | :--- |
| **Decentralized?** | **Fully** | No | Partial | Limited |
| **Onboarding** | **PoW** | Email | Email | Wallet |
| **Anti-spam** | **PoW** | Admin | Admin | Stake |
| **Switch nodes** | **Seamless** | No | Hard | Easy |
| **Can ban?** | **No** | Yes | Yes | Yes |
| **Own identity** | **Yes** | No | Admin | Yes |
| **Own graph** | **Yes** | No | Admin | Yes |
| **Post record** | **Yes** | No | Mixed | Yes |
| **Content hosting** | Nodes | Site | Instances | Frontends |
| **Moderation** | Opt-in | Admin | Admin | Stake |

[**Read the full analysis in our documentation**](docs/comparison.md) to understand why we chose a custom L1 blockchain over federation or relays.

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
