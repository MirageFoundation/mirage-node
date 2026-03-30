# Mirage v1.22.1 Release Notes

This document summarizes **everything merged on `dev` since production last tracked `v1.21.12`** (47 commits ahead of `prod` at the time of writing). It is meant as the **delta for the next production deploy**.

The **v1.22.0** chain and product story (gift subscriptions, inbox donations and follows, mobile card layout, snapshot retention, iOS Universal Links, and upgrade instructions) is documented in depth in [`update_v1.22.0.md`](./update_v1.22.0.md). Read that first for protocol and operator-facing detail; the sections below add **v1.22.1 web and themes**, plus a concise **backend, indexer, and test** rundown that is not duplicated there.

---

### Chain & protocol (v1.22.0 uplift)

- **`MsgSubscribe`** (formerly upgrade-level messaging), **subscription gifting** on-chain, and related wallet/UI flows — see [`update_v1.22.0.md`](./update_v1.22.0.md).
- **Governance upgrades** can target users; **send-token transfers** are eligible for notifications where applicable.
- **Inbox and push**: donations and new followers surface in the inbox; **gifted subscriptions** generate inbox events and push notifications (with filtering fixes so subscription gifts appear in profile notices).
- **Indexer**: **`tx_index` `raw_log`** backfill and hardened backfill path; malformed inputs return **400** instead of **500** where appropriate; **`raw_log` synthesized from events** when needed.
- **Node operations**: state-sync snapshot retention reduced from **28 to 4**; retention is **applied at startup** so one deploy/restart picks it up.
- **Post/timestamp validation** tightened on **`core_post`**; subscriber **PoW** fields and tests aligned with chain behavior.

---

### Web: multi-theme architecture

- **Single manifest source** (`manifests.js`): registry-driven **`THEMES`**, **`normalizeThemeId`** (legacy **`moon` → `bluemoon`**), **`bootstrapThemeId`** before React for correct first paint (`data-theme-id` on `documentElement`).
- **Theme manifests** are the only install list; **`ThemeGlobalStyle`** is enforced per family; **oldreddit** “flat” global CSS is **gated on `flatMode`** so it does not leak across themes.
- **Presentation** stays in theme routes and tokens; shared hooks avoid style fallbacks — **fail-fast** tokens and validation instead of optional styling chains.
- **Bluemoon** width and layout use **theme tokens** (including full-width behavior); shared “feed media only” width hacks were removed in favor of token-driven layout.
- **Dependencies**: unused **`ajv`** / **`web-vitals`** dropped; **`npm test`** script removed where obsolete.
- **Stability**: frontend **race conditions and lifecycle cleanup**; **ESLint** cache and theme-cap logic refactors.

---

### Web: Old Reddit theme

- **Shell and navigation**: list-style layout with **action links**, **vote** integration, and **strict** theme validation at startup.
- **Consistency pass** across **inbox, profile, discover, settings, subscription, follows, blocks, network, stats, referrals, bridge**, and related screens: shared **tab strip** primitives (aligned tab row, ~**1200px** content alignment for chrome, **full-bleed** where intended), **fewer redundant single-tab strips** where the shell already titles the page.
- **Feeds**: home/following navigation, **sort** control styled as plain text, options **best** / **new**; tighter toolbar spacing; first tab aligned with the **logo** column.
- **Logged-out home**: denser **welcome** strip, **Watch Introduction (YouTube)** and **Learn More** (mirage.foundation), **Create account** / **Sign in** as primary actions.
- **Profile / lists**: **`ListFeedView`** robustness (`num_comments` default, imports); **ProfileView** ordering fix (`effectivePostsFilter` declared before effects to avoid TDZ).
- **Visual polish**: **blur** support where used; cross-route **token** alignment.

---

### Web: Bluemoon

- **Hero alignment** with Old Reddit: logged-out block includes **Watch Introduction (YouTube)** and **Learn More** alongside the main invite copy.
- **Tab strips and feed chrome** brought in line with shared layout patterns (toolbar, welcome links) where the same work landed on Old Reddit.

---

### Backend & testing hygiene

- **Referral `client_hash` gate**: temporarily disabled for testing, then **re-enabled** with the intended enforcement.
- **Database**: **SERIAL sequence drift** after the backend/indexer DB split fixed so quest rewards no longer fail on insert conflicts.
- **Feeds**: **infinite scroll** with **tag filters** no longer stops early on short pages.
- **HTTP tests**: stricter **status code** expectations; **500** retries with JSON error bodies; indexer polling in deque tests; **self-block / self-follow / future-timestamp** pre-checks.
- **`verify_upgrade.py`**: localhost default for **`BACKEND_API`**; **500** accepted where **`upgrade_level` route was removed**; post-upgrade script aligned with **v1.22.x** checks.
- **Gift subscribe**: fetches **chain config on demand** when localStorage cache is empty; confirmation UI shows **cost**; errors **inline** instead of only toasts; duplicate **`giftSubMessages`** declaration removed.
- **Chain tests**: gift flows, **`raw_log`** assertions, edge cases failing on **5xx**.

---

### Documentation

- **v1.22.0** release notes rewritten for clarity (`docs: rewrite v1.22.0 release notes`).
- **Themes**: expanded **`web/frontend/src/themes/README.md`** for custom theme authors (manifest checklist, registry, bootstrap).

---

## Upgrade Instructions

1. **Chain binary**: Operators still follow **`v1.22.0`** as described in [`update_v1.22.0.md`](./update_v1.22.0.md) — upgrade name **`v1.22.0`**, coordinated frontend/backend/indexer deploy, **`/api/core/upgrade_level` removed**.

2. **Web client**: Ship **`web/frontend`** as **v1.22.1** (includes **`public/version.txt`**). If production is still on **pre–v1.22.0** chain, deploy chain + services per step 1 **and** this frontend together.

3. **No additional state migration** is introduced by **v1.22.1** beyond what **v1.22.0** already required; this release is primarily **frontend/theme packaging** plus the **backend/indexer fixes** listed above.
