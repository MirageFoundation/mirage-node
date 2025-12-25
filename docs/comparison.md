# Mirage vs. the Social Platform Landscape

“Decentralized social” is a messy category because different projects solve *different* problems:

- **Censorship resistance**: “Can someone delete me?”
- **Portability**: “If my server/admin sucks, can I move without losing my identity/graph?”
- **Spam resistance**: “Can the system stay usable without charging money or central gatekeeping?”
- **Usability**: “Can a normal person post instantly?”

The hardest trade‑off is the one most projects dodge:

> **If posting is free, bots will spam you. If posting costs money, onboarding dies.**

Mirage’s defining design choice is that it doesn’t pick between those two. It uses **Proof‑of‑Work (PoW)** as a *non‑monetary* “payment” for posting: cheap for humans, expensive at scale for botnets.

This doc compares Mirage to the common alternatives people actually use (and the ones that come up in conversation).

---

## 1) Centralized “Reddit alternatives” (Discuit, Tildes, Squabblr, Scored) and comment systems (Disqus)

These products are useful to compare against because they’re what most people mean by “a better Reddit”.

### What they are

- **Discuit / Tildes / Squabblr / Scored**: single websites with a single operator (or small team), single database, single set of rules.
- **Disqus**: centralized hosted comments/identity layer embedded into other sites (not a full social network, but relevant as “the hosted discussion layer”).

### What they do well

- **Great onboarding**: email + password, you’re in.
- **Stable UX**: one canonical site, no federation weirdness.
- **Spam controls**: centrally enforced rate limits, moderation tools, anti‑abuse heuristics.

### Where they break (for “unstoppable discourse”)

- **Single point of censorship**: the operator decides what is allowed and can remove content/accounts.
- **Topic bans and policy drift**: centrally moderated platforms can (and often do) ban categories of content. Your access depends on whoever runs the site.
- **No exit**: if you don’t like the operator, your identity/social graph does not come with you.
- **Deplatforming risk**: payment processors/hosts/app stores can pressure one operator into enforcing rules.

**Mirage’s difference**: Mirage keeps the *account and social graph* independent of any single website operator, and uses **PoW** to keep posting free without a central “KYC / pay / invite / admin gate” model.

---

## 2) The Fediverse / ActivityPub (Mastodon, Lemmy, kbin, PieFed, Pixelfed)

### What they are

Federation is “many servers talk to each other.” The biggest decentralized social movement today is ActivityPub:

- **Mastodon**: microblogging.
- **Lemmy / kbin / PieFed**: link aggregation + threaded discussion (Reddit‑like) via federation.
- **Pixelfed**: photos.

### What they do well

- **Email onboarding** (usually).
- **Multiple operators**: you can pick a server whose policies you like.
- **Some portability**: you can *sometimes* migrate an account.

### Where federation breaks

- **Admin feudalism**: your “rights” depend on your instance admin. They can ban you, delete your account, and control what you see.
- **Defederation as censorship**: server‑level blocks are common; entire communities become unreachable depending on admin politics.
- **Migration pain**: moving is not seamless. “Follow graph” moves imperfectly; history often doesn’t.
- **Data fragility**: if an instance dies, its local content can disappear.
- **Spam vs. usability tension**: to keep abuse down, instances often rely on manual moderation, approval queues, rate limits, and social gatekeeping.

**Mirage’s difference**: Mirage makes **switching nodes seamless** because the *identity and social graph* live beyond any single operator, and it uses **PoW** to reduce spam pressure without forcing invite‑only/admin‑approval culture.

---

## 3) Relay networks (Nostr)

### What it is

- Your identity is a keypair.
- You publish events to relays.
- Clients pick which relays to read/write.

### What it does well

- **Portable identity**: keys are portable.
- **Easy “provider switching”**: add/remove relays.

### Where it breaks

- **No global consensus**: “what exists” depends on what relays you/others have.
- **Availability is optional**: if a relay disappears, content can disappear unless replicated elsewhere.
- **Spam is brutal**: without a built‑in system cost, many ecosystems drift toward:
  - paid relays / admission fees,
  - private relay lists,
  - heavy client‑side filtering.

**Mirage’s difference**: Mirage uses **PoW** so the base layer can stay usable without turning into “pay for a relay” or “curated relay lists”.

---

## 4) Social blockchains (Steem, Hive)

Steem/Hive are the closest spiritually to Mirage in the sense that they are “social‑native L1s”.

### What they do well

- **On‑chain identity and history (text)**: durable public record (media is typically off‑chain).
- **Multiple frontends**: you can use different websites against the same chain.

### Where they break

- **Funded wallet requirement**: posting effectively requires stake‑based resources (it’s pay‑to‑play in practice).
- **Plutocracy dynamics**: stake influences visibility and social outcomes.
- **Small producer set**: DPoS‑style systems typically converge to a small set of block producers (e.g., 21), which harms censorship resistance and “anyone can join” decentralization.
- **UX drift into finance**: discussion becomes yield farming.

**Mirage’s difference**: Mirage replaces “stake to speak” with **PoW to speak**. You don’t need to buy tokens or get delegated stake to post.

---

## 5) Social L2 (Farcaster, Lens)

### What they are

- Identity/graph anchored on a general‑purpose chain/L2.
- Content stored off‑chain (hubs, indexers, storage networks).

### What they do well

- **Portable identity** (in theory).

### Where they break

- **Fees/subscriptions and complexity**: onboarding friction and mental overhead.
- **Reliance on third‑party hubs/indexers**: someone still runs the infrastructure that makes the UX usable.
- **History and availability are not guaranteed**: depends on who pins/hosts what.

**Mirage’s difference**: Mirage keeps identity/graph sovereign and integrates the “serve content” model around nodes, without requiring Ethereum gas or a separate hub‑operator layer to make posting usable.

---

## Summary comparison (what matters in practice)

The point of this table is the *trade‑offs people actually feel*.

**Legend**: ✅ advantage, ⚠️ mixed, ❌ downside

| Dimension | **Mirage** | Centralized | Federated | Relays | Social L1 | Social L2 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Decentralized?** | **✅ Fully** | ❌ No | ⚠️ Partial | ⚠️ Partial | ⚠️ Limited | ⚠️ Limited |
| **Onboarding** | **✅ PoW** | ✅ Email | ✅ Email | ❌ Keys | ❌ Wallet | ❌ Fees |
| **Anti-spam** | **✅ PoW** | ⚠️ Enforced | ⚠️ Enforced | ⚠️ Paid | ⚠️ Stake | ⚠️ Fees |
| **Switch nodes** | **✅ Seamless** | ❌ No | ❌ Hard | ✅ Easy | ✅ Easy | ⚠️ Mixed |
| **Can ban?** | **✅ No** | ❌ Yes | ❌ Yes | ⚠️ Relay | ❌ Yes | ❌ Yes |
| **Own identity** | **✅ Yes** | ❌ No | ❌ Admin | ✅ Keys | ✅ Yes | ✅ Yes |
| **Own graph** | **✅ Yes** | ❌ No | ❌ Admin | ✅ Keys | ✅ Yes | ✅ Yes |
| **Post record** | **✅ Yes** | ❌ No | ⚠️ Mixed | ⚠️ Mixed | ✅ Yes | ⚠️ Mixed |
| **Content hosting** | **✅ Nodes** | ❌ Site | ⚠️ Instances | ⚠️ Relays | ⚠️ Frontends | ❌ Hubs |
| **Moderation** | **✅ Opt-in** | ❌ Enforced | ❌ Enforced | ⚠️ Client | ❌ Stake | ❌ Enforced |

### Category key (examples)

- **Centralized**: Discuit, Tildes, Squabblr, Scored, Disqus
- **Federated**: Lemmy, Mastodon, kbin, PieFed
- **Relays**: Nostr
- **Social L1**: Steem, Hive
- **Social L2**: Farcaster, Lens

### How to read the rows

- **Decentralized?**: “Can anyone join as infrastructure without needing permission from a small fixed set?”
- **Onboarding**: What a normal user needs to do to make their first post.
- **Anti-spam**: What the system uses to prevent bot flooding at scale.
- **Switch nodes**: Whether you can change providers without losing identity/graph.
- **Can ban?**: Whether a provider/operator can stop you from participating (globally vs locally).
- **Own identity / Own graph**: Whether your identity and follower graph are portable or owned by an operator.
- **Post record**: Whether posts have a durable record vs being purely “database content”.
- **Content hosting**: Where the actual content is served from in practice.
- **Moderation**: Whether moderation is opt‑in / user‑controlled vs centrally enforced.

### Why PoW matters (and why it’s the key differentiator)

Most “decentralized social” systems end up choosing one:

- **Charge money** (fees, stake, subscriptions) → stops spam, kills onboarding.
- **Central gatekeeping** (admins, approvals, invite‑only culture) → stops spam, recreates censorship.

Mirage uses **PoW** so a normal user can post immediately without paying, while bots can’t spam at scale without burning real compute.

---

## Appendix: where the “usual suspects” fit

These names come up a lot. Most differences are not about ideology; they’re about *architecture*:

- **Discuit**: centralized Reddit‑like (single operator + database).
- **Tildes**: centralized, heavily curated, invite‑gated (single operator + database).
- **Squabblr**: centralized Reddit‑like (single operator + database).
- **Scored**: centralized Reddit‑like (single operator + database).
- **Disqus**: centralized hosted comments + identity layer (embedded into other sites).
- **Lemmy**: federated Reddit‑like (ActivityPub).
- **kbin**: federated link aggregator / forum (ActivityPub). Different implementation, same federation trade‑offs.
- **PieFed**: federated Reddit‑like (ActivityPub). Different implementation, same federation trade‑offs.
- **Mastodon / Pixelfed**: federated (ActivityPub) for microblogging / photos.

