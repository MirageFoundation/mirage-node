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

## Run a Node

A node is one Docker container holding the whole stack: the `miraged`
validator, PostgreSQL, the indexer, the backend API, the React frontend and
Caddy. You install it with one command and it runs itself from there — it syncs,
registers itself as a validator, and updates itself.

### What you need

A **[mirage.talk](https://mirage.talk) account with a username and 10,000,000
MIRAGE on it**, plus that account's 12-word recovery phrase. The node signs
blocks with this account, so the stake has to be there before you start.

A **server**: Ubuntu 24.04 LTS, amd64, 2 vCPU and 4 GB RAM (at least 3800 MiB
visible inside Ubuntu), 20 GB free disk — though you want 40 GB. It has to be a
real VM; LXC containers and arm64 are refused. On
[DigitalOcean](https://cloud.digitalocean.com/droplets/new) that is the
`s-2vcpu-4gb-amd` plan with your SSH key on root, which is what the live
validators run.

### Install

SSH in as root and run:

```bash
curl -fsSL https://raw.githubusercontent.com/MirageFoundation/mirage-node/prod/deploy/install.sh | bash
```

It asks for your recovery phrase, then three questions you can answer by
pressing Enter: node name (defaults to your username), domain (none), and media
uploads (off). If Ubuntu needs a reboot first, run the same command again when
it comes back. Re-running the installer on a finished node just updates it.

The phrase is the only secret you type. It is used locally to derive the signing
key and is never transmitted.

### After the install

The node state-syncs to the current chain height, which takes a while, then
**registers itself as a validator automatically**. Never run
`create-validator` by hand.

Watch it happen:

```bash
mirage-status
```

That is a live dashboard: sync progress, services, peers, disk, retention,
endpoints, and an earnings card showing what the node earned and spent over the
last 24 hours and 30 days. `Ctrl+C` exits. Until the backend is healthy the
site serves a maintenance page, which lifts on its own once sync finishes.

### Serve it on a domain

Point an A record (and AAAA if you have IPv6) at the server, then:

```bash
mirage-domain --set example.com
```

That gets a certificate and switches to HTTPS. Until then the node is reachable
at `http://<server-ip>`, which works fine for browsing but not for the wallet
features that browsers only allow on a secure origin.

### Everyday commands

```bash
mirage-status                  # live dashboard (--once for a snapshot, --json for scripts)
mirage-logs                    # follow service logs
mirage-update                  # apply the newest signed release
mirage-update --status         # what is active, staged and prepared
mirage-backup                  # online backup — copy the archive off the server
mirage-restore BACKUP          # restore from an archive
mirage-domain --set DOMAIN     # serve a domain over HTTPS
mirage-restart                 # whole-container restart, refused when unsafe
```

### Updates

Your node never fetches releases automatically. To verify, pull and activate an
ordinary signed release:

```bash
mirage-update
```

Being several releases behind is fine — one update applies everything it missed.

**Blockchain upgrades require explicit preparation.** After governance passes
the proposal, run `mirage-update --prepare`. It verifies and pulls the exact
signed digest, matches it to the on-chain plan, and arms the node. At the halt,
the local activator swaps to that already prepared image automatically; it
never fetches anything itself.

### Backups

Chain data comes back from the network on its own, but your posts, indexer state
and backend data do not. `mirage-backup` archives them without taking the
validator offline. **The archive is secret operational material — keep a copy
off the server.**

### Verifying and getting help

Releases are signed with key fingerprint
`679a39294dc9639170ca9cb4010c44cc71dd153fa2029f2e73969bff6d86c0a8`
(see [SECURITY.md](SECURITY.md)).

Full detail is in the [Deployment Guide](docs/guides/deploy.md). For anything
else, ask in the [Mirage Portal on Telegram](https://t.me/+5SILWcCke8tmODlh).

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

Here’s how Mirage compares at a high level (more detail + more platforms in `docs/comparison.md`):

| Dimension | **Mirage** | Centralized | Federated | Social L1 | Social L2 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Decentralized?** | **✅ Fully** | ❌ No | ⚠️ Partial | ⚠️ Limited | ⚠️ Limited |
| **Onboarding** | **✅ PoW** | ✅ Email | ✅ Email | ❌ Wallet | ❌ Fees |
| **Anti-spam** | **✅ PoW** | ⚠️ Admin | ⚠️ Admin | ⚠️ Stake | ⚠️ Fees |
| **Switch nodes** | **✅ Seamless** | ❌ No | ❌ Hard | ✅ Easy | ⚠️ Mixed |
| **Can ban?** | **✅ No** | ❌ Yes | ❌ Yes | ❌ Yes | ❌ Yes |
| **Own identity** | **✅ Yes** | ❌ No | ❌ Admin | ✅ Yes | ✅ Yes |
| **Own graph** | **✅ Yes** | ❌ No | ❌ Admin | ✅ Yes | ✅ Yes |
| **Post record** | **✅ Yes** | ❌ No | ⚠️ Mixed | ✅ Yes | ⚠️ Mixed |
| **Content hosting** | **✅ Nodes** | ❌ Site | ⚠️ Instances | ⚠️ Frontends | ❌ Hubs |
| **Moderation** | **✅ Opt-in** | ❌ Enforced | ❌ Enforced | ❌ Stake | ❌ Enforced |

### Category key (examples)

- **Centralized**: Discuit, Tildes, Squabblr, Scored, Disqus
- **Federated**: Lemmy, Mastodon, kbin, PieFed
- **Social L1**: Steem, Hive
- **Social L2**: Farcaster, Lens

[**Read the full analysis in our documentation**](docs/comparison.md) to understand why we chose a custom L1 blockchain over federation or relays.

---

## Get Started

### For Users
You don't need to install anything. Just visit a public node:

- **[mirage.talk](https://mirage.talk)** (Production Node)
- **[mirage.vote](https://mirage.vote)** (UAT/Public Node)

### For Node Operators

See [Run a Node](#run-a-node) above: one command on an Ubuntu 24.04 server, and
an account holding 10,000,000 MIRAGE.

### For Developers
- **Backend**: Python (Flask), Go (Mirage chain)
- **Frontend**: React
- **Consensus**: CometBFT (Tendermint)
