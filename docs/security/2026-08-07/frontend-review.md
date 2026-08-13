# Frontend Security and Correctness Review — 2026-08-07

**Scope:** `web/frontend/` — all 357 tracked files, including account creation and recovery, seed storage, transaction construction/queueing, API access, Markdown and media rendering, all four themes, service/build configuration, and dependency manifests. `deploy/Dockerfile` and `deploy/templates/caddy/Caddyfile` were reviewed at the browser/deployment trust boundary.
**Out of scope:** Backend and chain authorization correctness except where needed to assess whether a frontend issue is contained; native mobile clients; Google Tag Manager container contents and account controls; CDN-added response headers; browser-extension compromise; and production-server testing. No production system was contacted.
**Baseline:** `dev` at `d9dbf87a5c0632c5a95ce0e369bbc559fe3c4185` (`v1.32.4` + review commit). The reviewed frontend and deployment files were clean. Unrelated security-review documents were already modified/untracked and were not touched.
**Previous review:** No prior dedicated frontend review. The blockchain and backend reviews remain authoritative for chain enforcement and backend authentication.

---

## Executive Summary

The frontend performs wallet duties: it generates and displays recovery phrases, keeps decrypted seed material in browser memory, derives signing keys, and signs transactions. That makes its browser execution environment part of the key-custody boundary. The implementation has several good cryptographic and rendering controls, but its current seed lifecycle and transaction queue do not consistently preserve account identity.

**Four High findings define the review:**

1. **Google Tag Manager can execute mutable third-party JavaScript in the wallet origin.** A container-account or upstream compromise can read plaintext recovery phrases, instrument signing, or change transaction UI without a Mirage deployment. See **H-1**.
2. **Recovery phrases are plaintext by default and are copied into browser history state.** New/imported phrases remain in `localStorage`, React state, and `window.history.state`, including after leaving the welcome screen. See **H-2**.
3. **Secure seed storage can silently downgrade to plaintext, while signup clears the prior vault before the replacement account is valid.** A protected-vault error therefore becomes weaker storage, and merely entering account setup can destroy the prior persisted vault. See **H-3**.
4. **Queued transactions are not bound to the account that created them and failed queues retain stale entries.** An old send/post/follow can later be signed by a newly logged-in account. See **H-4**.

No first-party DOM XSS sink, unsafe Markdown HTML rendering, client-side admin authorization bypass, private-key network transmission, or non-canonical transaction-signing path was found. React escapes ordinary content; `react-markdown` does not enable raw HTML; external links are generally opened with `noopener noreferrer`; backend privileged routes still enforce signed authorization; and transaction signatures are produced locally.

**Ship posture:** **H-4 should be fixed before the transaction queue is considered safe for account switching or recovery from a failed batch. H-1 through H-3 should be fixed before describing the web client as secure key custody.** Protected vault modes reduce at-rest exposure, but the current default, fallback, history transport, and same-origin tag manager bypass that protection.

---

## Findings

### H-1: Mutable Google Tag Manager Code Executes Inside the Wallet Key-Custody Origin (High)

**Location:** `web/frontend/public/index.html` lines 5–14; seed entry/display in `src/themes/default/routes/LoginView.js` and `SettingsView.js`; in-memory seed access in `src/utils/SeedVault.js`; transaction signing in `src/utils/TransactionHandler.js`.

The application loads and executes the GTM container before the React bundle:

```5:14:web/frontend/public/index.html
    <!-- Google Tag Manager -->
    <script>(function (w, d, s, l, i) {
            w[l] = w[l] || []; w[l].push({
                'gtm.start':
                    new Date().getTime(), event: 'gtm.js'
            }); var f = d.getElementsByTagName(s)[0],
                j = d.createElement(s), dl = l != 'dataLayer' ? '&l=' + l : ''; j.async = true; j.src =
                    'https://www.googletagmanager.com/gtm.js?id=' + i + dl; f.parentNode.insertBefore(j, f);
        })(window, document, 'script', 'dataLayer', 'GTM-TL3G7VNP');</script>
```

GTM is not a passive image beacon. Its container configuration can load arbitrary JavaScript that has the same DOM, storage, Web Crypto, history, and network privileges as first-party code. It can read a phrase while it is typed or displayed, read the default plaintext vault, observe `window.history.state`, instrument cryptographic calls, alter recipient/amount UI, or exfiltrate secrets. Neither HTTPS nor seed encryption contains code that runs after the user unlocks the vault.

**Impact:** Compromise or misconfiguration of the GTM account, a malicious published tag, or compromise of the upstream script becomes wallet compromise for every affected visitor without changing the Mirage repository or release artifact.

**Remediation:** Remove GTM and all mutable third-party scripts from authenticated, recovery, signup, welcome, settings, and transaction-capable pages. Prefer a same-origin, fixed-schema analytics endpoint with no remote code execution. If analytics must remain, serve a separate non-wallet landing origin and keep the wallet origin free of tag managers. Require reviewed repository changes for every script shipped to the wallet, pin build inputs, and add a CSP that cannot authorize arbitrary GTM container code. Treat GTM administrative access as key-custody access until removal.

---

### H-2: Recovery Phrases Are Plaintext by Default and Persist in Browser History State (High)

**Location:** `web/frontend/src/utils/SeedVault.js` lines 4–8, 143–171, and 254–265; `src/logic/useCreateAccount.js` lines 381–385 and 414–435; `src/logic/useLogin.js` lines 59–77; `src/logic/useWelcome.js` lines 7–17.

`SeedVault` defaults to insecure mode and stores the phrase directly in `localStorage`:

```143:167:web/frontend/src/utils/SeedVault.js
    getMode() {
        const mode = Storage.load(KEY_MODE, null);
        if (mode && ['insecure', 'memory', 'password', 'passkey'].includes(mode)) {
            return mode;
        }
        // Backwards compat: if no mode saved but plaintext seed exists → insecure
        const raw = Storage.load(KEY_PLAINTEXT, '');
        if (raw) return 'insecure';
        return 'insecure';
    }

    // ── Read ──────────────────────────────────────────────────────────────────

    getSeed() {
        // If already unlocked, return from memory
        if (this._seed) return this._seed;

        // For insecure mode, auto-load from localStorage
        const mode = this.getMode();
        if (mode === 'insecure') {
            const raw = Storage.load(KEY_PLAINTEXT, '');
            if (raw) {
                this._seed = raw;
                return raw;
```

Account creation explicitly selects that mode. Recovery of an unknown account passes the phrase through React Router state to `/signup`; successful signup passes it again to `/welcome`. Browser-router state is persisted in `window.history.state`, survives reloads, and can remain in the back/forward history after the user leaves the welcome page.

```428:435:web/frontend/src/logic/useCreateAccount.js
            navigate('/welcome', {
                state: {
                    username: finalUsername,
                    seedPhrase
                },
                replace: true
            });
            setCredentials(publicKey, finalUsername, seedPhrase);
```

`replace: true` replaces the current entry; it does not erase the phrase when a later navigation pushes a new entry. The recovery textarea also disables spellcheck/autocorrect but does not specify an autocomplete policy.

**Impact:** Any same-origin script, XSS, browser profile theft, local malware, shared-device user, backup/sync process, or extension with page/storage access can recover the wallet phrase. History persistence extends exposure beyond the visible recovery/welcome step. Because the phrase controls the chain account, compromise is permanent unless assets and identity move to a new wallet.

**Remediation:** Make memory-only the default for new/imported phrases. Require an explicit user decision before persistent storage, and offer password/passkey protection during onboarding rather than only in settings. Never put a phrase in router/history state; use a short-lived in-memory handoff outside browser history and clear it immediately after acknowledgement. Replace the welcome history entry when leaving it and test that `window.history.state`, `localStorage`, and session history contain no phrase. Add appropriate recovery-input autocomplete controls and a user-visible warning that extensions and injected scripts can read any phrase shown in the page.

---

### H-3: Vault Errors Downgrade to Plaintext and Signup Clears the Existing Vault Before Validation (High)

**Location:** `web/frontend/src/App.js` lines 755–776; `src/logic/useCreateAccount.js` lines 244–265 and 381–385; `src/utils/Storage.js` clear behavior; `src/utils/SeedVault.js` lines 254–335.

`setCredentials` first marks the UI logged in, then attempts the selected seed mode. Any failure in password/passkey storage is intentionally converted into insecure plaintext storage:

```755:773:web/frontend/src/App.js
    setCredentials(publicKey, username, seedPhrase) {
        this.setState({
            publicKey: publicKey,
            username: username,
            seedPhrase: seedPhrase,
        });

        Storage.save('publicKey', publicKey);
        Storage.save('username', username);
        // Store seed through SeedVault (respects chosen security mode).
        // If the current mode requires a secret we don't have (e.g. user re-entered
        // seed via fallback login while mode is 'password'), fall back to insecure.
        if (seedPhrase) {
            seedVault.storeSeed(seedPhrase, seedVault.getMode(), null).catch((e) => {
                console.warn('[SeedVault] Falling back to insecure mode:', e.message);
                return seedVault.storeSeed(seedPhrase, 'insecure', null);
            }).catch((e) => {
                console.error('[SeedVault] Failed to store seed:', e);
            });
```

The signup hook has the inverse ordering problem: it calls `Storage.clear()` before generating/importing and deriving the replacement account. A locked user's encrypted vault is browser storage, so opening this flow can erase the only persisted copy before the new phrase is validated or an account transaction succeeds.

```244:257:web/frontend/src/logic/useCreateAccount.js
    const initializeAccount = (existingSeed = null) => {
        Storage.clear();
        const newSeedPhrase = existingSeed || generateMnemonic();
        setSeedPhrase(newSeedPhrase);
        try {
            // Derive public key/address from seed phrase
            const {
                publicKey: address
            } = deriveKeysFromSeed(newSeedPhrase);
            setPublicKey(address);
        } catch (error) {
            setSubmitError("Key derivation failed: " + error.message);
        }
    };
```

The account-creation write to `seedVault.storeSeed(...)` is also not awaited; its `try/catch` cannot catch a rejected promise.

**Impact:** A user who chose protected storage can silently end up with a plaintext phrase after re-entry or a vault-key state error. A locked wallet can lose its persisted encrypted seed while exploring/retrying signup. UI credentials can be committed before durable seed storage succeeds, creating a logged-in-looking session that cannot survive reload.

**Remediation:** Delete the insecure fallback and fail the login atomically with a clear error. Do not update identity state/storage until the selected vault write succeeds. Stage account creation independently; preserve the existing vault until the new account is validated, successfully submitted, and explicitly confirmed by the user. Await every `storeSeed` call. Implement one atomic seed-vault transition API that builds and verifies the replacement first, commits it, then clears only superseded seed keys. Add failure-injection tests for WebAuthn cancellation, encryption rejection, quota/storage errors, malformed imports, and account-creation failure.

---

### H-4: Failed Queue Entries Survive and Can Be Signed by a Different Account (High)

**Location:** `web/frontend/src/utils/TransactionHandler.js` lines 1436–1503, 2167–2240, 2488–2537, and 2575–2578; `src/utils/CryptoUtils.js` lines 18–58; `src/logic/useSignOut.js` lines 5–15.

Queue entries contain the requested action, target, and amount, but no immutable signer/owner. At dequeue, the handler reads whatever seed is currently in the singleton vault and silently rewrites `publicKey` when it differs:

```2184:2238:web/frontend/src/utils/TransactionHandler.js
        while (this.transactions.length > 0) {
            // Get the next transaction  
            const queued = this.transactions.shift() || {};
            const _resolve = typeof queued._resolve === 'function' ? queued._resolve : null;
            const { _resolve: _ignored, _followKey: _ignored2, _blockKey: _ignored3, _deleteKey: _ignored4, _agentKey: _ignored5, ...transaction } = queued;
            // ...
            // Derive signer address from current seed to ensure consistency with relay
            const seedPhrase = seedVault.getSeed() || "";
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return Storage.load('publicKey', ''); } })();
            if (derivedAddress && derivedAddress !== Storage.load('publicKey', '')) {
                try { Storage.save('publicKey', derivedAddress); } catch (_) { }
            }
```

On a fetch, signing, or broadcast failure, processing `break`s after resolving only the current entry. The remaining `this.transactions` entries are not removed or rejected. The method then resets counters and `isProcessing`, so the next enqueue restarts the old residual queue before the new action.

Sign-out clears `SeedVault` and browser storage but does not cancel/reject the transaction singleton's queue or pending maps. A later login therefore supplies a new seed to old intents. For `send_tokens`, the recipient and amount remain from account A while signing and chain balance belong to account B; if B has sufficient funds, B sends A's stale payment. Posts, votes, follows, blocks, subscriptions, and awards have analogous identity confusion.

There is an additional fail-open: `CryptoUtils` calls `bip39.mnemonicToSeedSync` without `validateMnemonic`. That library derives a deterministic 64-byte seed even for `""`, so the fallback does not necessarily throw; dequeue can derive and persist the globally known empty-mnemonic account instead of failing.

**Impact:** Token loss or unintended public actions after a failed multi-action queue, sign-out, wallet recovery, or account switch. Pending promises/UI state can also remain unresolved indefinitely. The behavior violates the core invariant that the account approving an intent is the account that signs it.

**Remediation:** Derive and store an immutable owner address on every queue entry at enqueue. Immediately before signing, require a present, valid BIP-39 mnemonic and exact equality among the entry owner, derived signer, and active account; fail without modifying identity storage on mismatch. On any queue abort, drain and reject every remaining entry and clear all corresponding pending maps/listeners. Sign-out, lock, account switch, and hard reset must synchronously cancel pending entries; an already-signing transaction should have an explicit, tested policy. Never auto-correct `publicKey` inside dequeue. Add deterministic tests for failure in item 1 of N, sign-out with queued entries, login as B, empty/invalid seed, and stale send/follow/post intents.

---

### M-1: The Deployed Frontend Has No CSP or Anti-Framing Policy (Medium)

**Location:** `deploy/templates/caddy/Caddyfile` lines 152–177; `web/frontend/public/index.html`.

The frontend file handler sets cache headers but no `Content-Security-Policy`, `frame-ancestors`, `X-Frame-Options`, `Referrer-Policy`, or `Permissions-Policy`. No equivalent meta policy exists in the HTML. CDN-added headers were out of scope and must not be assumed as an origin guarantee.

**Impact:** Any HTML/script injection has an unrestricted exfiltration surface, and another origin can frame the wallet UI for clickjacking. The absence of CSP also makes accidental introduction of a dangerous rendering sink substantially more damaging. Current inline style/script and third-party integrations make a strict policy harder to add later.

**Remediation:** First remove GTM and move inline bootstrap code/styles into hashed first-party assets or use per-response nonces. Deploy CSP in report-only mode, collect violations, then enforce at least `default-src 'self'`, restrictive `script-src`, explicit `connect-src`/media providers, `object-src 'none'`, `base-uri 'none'`, `form-action 'self'`, and `frame-ancestors 'none'`. Add `Referrer-Policy: no-referrer`, a minimal `Permissions-Policy`, and `X-Content-Type-Options: nosniff`; retain `X-Frame-Options: DENY` as legacy defense. Verify headers from the origin and CDN in CI.

---

### M-2: Password Vaults Accept Four-Character Passwords and Stay Unlocked for the Session (Medium)

**Location:** `web/frontend/src/utils/SeedVault.js` lines 42–52 and 132–171; `src/themes/default/routes/SettingsView.js` lines 973–1006; startup/inactivity handling in `src/App.js`.

Password encryption uses AES-GCM, a random salt, and 600,000 PBKDF2-SHA-256 iterations, which are sound primitives. The settings hook, however, accepts any password of four or more characters and performs no strength check. Once unlocked, the phrase and derived password key remain cached in the singleton until manual lock/sign-out; the general inactivity logout is 30 days, not a short vault timeout.

**Impact:** Theft of browser storage enables offline guessing, and a one-character/common password provides little protection despite the PBKDF2 cost. Long-lived unlocked memory broadens the window for injected scripts, extensions, shared-device access, and unattended sessions.

**Remediation:** Enforce a meaningful passphrase policy and show a strength estimate before committing password mode. Prefer a calibrated memory-hard KDF where browser support and migration can be implemented safely; otherwise benchmark and retain a documented PBKDF2 work factor. Add a configurable short auto-lock based on inactivity and page lifecycle, clear seed/KDF key bytes on lock, and require re-unlock before signing or revealing the phrase. Do not silently extend an unlocked session.

---

### M-3: The Dependency/Build Chain Contains Known Vulnerabilities and an Unlocked Build-Time Install (Medium)

**Location:** `web/frontend/package.json`, `web/frontend/package-lock.json`; `deploy/Dockerfile` lines 58–63.

The scoped `npm audit` reports **59 vulnerabilities: 14 low, 19 moderate, 24 high, and 2 critical**. Most severe paths are inherited from the legacy Create React App/react-scripts toolchain and are not present as exploitable modules in the emitted browser bundle. The audit does, however, include a direct runtime React Router advisory; `react-router-dom` 6.30.3 is installed and 6.30.4 is available. No clearly attacker-controlled protocol-relative redirect call was found, but carrying the vulnerable router is unnecessary.

The Docker build runs `npm ci`, then separately installs `@babel/plugin-transform-private-property-in-object` without a version and outside the lockfile. A build on a later date can therefore fetch and execute different package contents despite an unchanged commit and `package-lock.json`.

**Impact:** Direct runtime advisories can become reachable as routing changes. Vulnerable build/dev tooling expands the risk of malicious source-map/CSS/SVG inputs, local development exposure, and supply-chain compromise. The unpinned post-`npm ci` install defeats reproducible-build expectations for a wallet artifact.

**Remediation:** Upgrade `react-router-dom` to the patched 6.30.4 release immediately and add a regression test for `//host` navigation. Add the Babel plugin through the package manager so its exact dependency graph and integrity hashes are committed, then remove the Docker `npm install --no-save`. Plan migration away from the stale CRA/react-scripts chain instead of applying `npm audit fix --force`, which proposes breaking/invalid versions. Separate build-only packages into `devDependencies`, generate an SBOM, audit in CI, and verify the final bundle independently from the Node build tree.

---

### M-4: The PoW Worker Executes Unpinned JavaScript From jsDelivr at Runtime (Medium)

**Location:** `web/frontend/public/pow/worker.js` lines 1–2; worker creation in `src/utils/TransactionHandler.js`.

The tracked worker is not self-contained. On every uncached load it executes the current contents returned for an unversioned npm package URL:

```1:2:web/frontend/public/pow/worker.js
// Use Argon2id in the worker (WASM bundled)
importScripts('https://cdn.jsdelivr.net/npm/argon2-browser/dist/argon2-bundled.min.js');
```

The comment says bundled, but the code is remote and has neither a package version nor an integrity check. `importScripts` does not offer a browser SRI parameter. Worker isolation prevents direct DOM/local-storage access, but compromised code controls PoW outputs, CPU/memory use, message timing, and transaction availability.

**Impact:** A jsDelivr/npm package compromise, malicious newly published package version, or upstream delivery incident can make transaction PoW fail, consume excessive client resources, or return attacker-selected results without a Mirage release changing. The external dependency also conflicts with a strict self-only CSP.

**Remediation:** Vendor the reviewed Argon2 JavaScript and WASM artifacts under `/public/pow/`, commit their hashes, and load them from the wallet origin. Pin the npm source in the lockfile used to refresh those assets and add a build check comparing committed artifact hashes. Restrict the worker CSP to first-party scripts; do not rely on a floating CDN URL.

---

### M-5: Sign-Out Does Not Clear Per-Tab API and Feed Caches (Medium)

**Location:** `web/frontend/src/utils/api.js` lines 225–289; `src/logic/useMain.js` lines 34–62; `src/logic/useSignOut.js` lines 5–15.

Sign-out clears the vault and browser storage, but `Api` retains its module-level response/in-flight maps and the feed keeps `window.__MIRAGE_FEED_MEM_CACHE__`. The feed cache is keyed by topic, not account. Neither cache exposes a reset operation used by sign-out/account switch.

**Impact:** Account B logging into the same tab can briefly receive/render account A's cached feed or API response until the entries expire or are replaced. In-flight requests started as A can also settle after sign-out and update shared state. This is a cross-account privacy and state-isolation failure, although it does not expose A's signing key.

**Remediation:** Add one synchronous session-reset function that aborts in-flight requests, clears the API response/in-flight maps, clears feed/bootstrap/global caches, and resets account-scoped singleton state. Invoke it before clearing identity on sign-out, lock, hard reset, and account switch. Include an account identifier in every account-specific cache key as defense in depth.

---

### M-6: Direct Transaction Paths Bypass the Serialized Queue and Run Concurrently (Medium)

**Location:** queued processing at `web/frontend/src/utils/TransactionHandler.js` lines 2167–2537; direct `performTransaction` calls for account creation, posts/comments, reports, awards, subscriptions, edit/delete, biography, and auto-renewal around lines 713, 761, 805, 1423, 1555, 1620, 1651, 1751, 1811, 1856, 2086, and 2159.

Votes, follows, blocks, sends, deletes, and agent actions use `this.transactions` and the `isProcessing` serialization gate. Other chain actions call `performTransaction` directly. A post/comment/award/subscription can therefore run a PoW worker and relay concurrently with a queued vote/follow/send. All paths share global status, balance, notifications, and seed-vault state.

**Impact:** Queue-position text and global transaction status can be wrong or flicker; multiple PoW workers and relays run simultaneously; balance updates race; and lock/sign-out cancellation semantics differ by action. Backend nonce and chain validation limit consensus harm, but the frontend's advertised single transaction queue is not a real global invariant.

**Remediation:** Route every chain action through one owner-bound scheduler, including actions that currently return directly. If selected actions must remain concurrent, implement an explicit scheduler with separate immutable owners and isolated status/balance state; do not share queue-global counters. Add concurrency tests covering a queued send plus each direct action and auth changes during execution.

---

### M-7: The Decrypted Phrase Is Duplicated in App State and Reveal Requires No Step-Up (Medium)

**Location:** `web/frontend/src/App.js` lines 203–217, 755–760, and 957; `src/themes/default/routes/SettingsView.js` lines 1038–1081 and equivalent theme views.

The unlocked recovery phrase is held both in `SeedVault` and top-level React state, which is passed to route components even though signing can read the vault directly. In settings, any unlocked session can reveal and copy the phrase with one click; the 60-second auto-hide is not reauthentication.

**Impact:** React debugging/error instrumentation and future child components receive a longer-lived duplicate secret. Brief access to an unattended unlocked device—or injected script after unlock—can reveal/copy the durable account credential without the vault password/passkey being checked again.

**Remediation:** Remove `seedPhrase` from `App.state` and keep one in-memory copy inside `SeedVault`. Require password/passkey user verification immediately before reveal or clipboard copy, independent of the session's current unlocked state. Clear the clipboard where supported after a short warning period, while explaining that clipboard managers may retain it.

---

### L-1: Embedded and User-Hosted Media Loads Third Parties Without a Privacy Gate (Low)

**Location:** `web/frontend/src/themes/default/components/InlineMedia.js` lines 325–380 and 411–525; shared use by the theme card views.

Posts can cause automatic requests to Redgifs, YouTube, Cloudflare Stream, image hosts, HLS endpoints, and arbitrary HTTP(S) media origins. Blurred-image mode also sends the full source URL to third-party image proxies such as `wsrv.nl` and `i0.wp.com`. The iframes have no `sandbox` or `referrerPolicy`; YouTube is granted `clipboard-write`. Direct image/video loads reveal the reader's IP and the Mirage origin to the media host under normal browser referrer behavior. Autoplay can trigger requests before deliberate interaction.

**Impact:** A post author can observe readers who load a unique media URL, and embedded providers can correlate browsing. This is primarily privacy/tracking exposure rather than first-party code execution because iframe origins remain isolated and ordinary image/video content does not gain parent-origin privileges.

**Remediation:** Use click-to-load placeholders for third-party embeds and arbitrary remote media, or fetch approved media through the existing validated proxy architecture. Set `referrerPolicy="no-referrer"`, remove unnecessary iframe permissions such as `clipboard-write`, and apply the tightest sandbox that still supports each provider. Document unavoidable provider disclosure in the privacy notice and make autoplay opt-in.

---

### L-2: Visiting the `/sign_out` Route Immediately Destroys the Local Session (Low)

**Location:** `web/frontend/src/App.js` route definition around line 1044; `src/logic/useSignOut.js` lines 5–15.

Mounting `/sign_out` immediately clears the seed vault and storage with no confirmation or user gesture. Because the frontend can currently be framed, an attacker can load that route in a hidden frame; a top-level link/redirect has the same effect.

**Impact:** Forced local logout and, in insecure mode, deletion of the only browser-stored phrase. It does not let the attacker sign or steal funds, but it can cause session denial and recovery burden.

**Remediation:** Remove destructive behavior from a bare GET route. Require an in-app confirmation and explicit action, then perform the reset. Enforcing `frame-ancestors 'none'` also blocks the hidden-frame path but should not replace confirmation.

---

### L-3: Several Blockchain Buttons Do Not Follow the Global Pending/Queue-Status Pattern (Low)

**Location:** vote sections in all four themes; profile follow handling in `web/frontend/src/logic/useProfile.js`; award/report dialogs in card views.

Vote entries store queue positions and expose global pending state, but themed vote buttons do not display `formatStatusForPosition`. Profile follow uses component-local pending state and a queue-position snapshot instead of `usePendingFollows`, so navigation can lose the disabled/status state. Award and some report surfaces likewise use only local guards.

**Impact:** Users can see incorrect queue depth, lose pending feedback across navigation, or attempt duplicate actions from another surface. Server/chain checks contain most duplicates, making this primarily reliability and UX risk.

**Remediation:** Apply the repository's blockchain-button pattern consistently: global pending singleton, enqueue-time queue position, `formatStatusForPosition`, and action-specific fallback text. Add navigation and double-click tests across every theme.

---

### I-1: Markdown and Link Rendering Avoid the Common First-Party XSS Sinks (Informational)

No `dangerouslySetInnerHTML`, `innerHTML`, `document.write`, JavaScript URL construction, `eval`, or `new Function` use was found in tracked frontend source. `MarkdownRenderer` uses `react-markdown` without `rehype-raw`, so post HTML is parsed as text rather than inserted into the DOM. The library's URL transform rejects dangerous schemes, custom mention/hashtag plugins create React nodes, and ordinary external links use `noopener noreferrer`.

Keep regression tests around these guarantees. A future raw-HTML plugin, custom URL transform, syntax highlighter, or rich embed can invalidate this conclusion.

---

### I-2: Client-Side Admin Checks Are UI Controls, Not the Authorization Boundary (Informational)

The reports, quest administration, and statistics views use cached `user_level`/`isAdmin` values to hide controls. Those browser values are user-modifiable, but the reviewed backend boundary requires signed payloads and performs its own privilege checks; debug reward routes also require debug mode and localhost. No privileged result was found that depends solely on frontend state.

Retain server-side authorization as the only authority. Frontend checks should continue to be treated as usability controls and should never be cited as security enforcement.

---

## Positive Security and Reliability Controls Observed

- Seed encryption uses random AES-GCM IVs; password mode uses a random salt and 600,000 PBKDF2-SHA-256 iterations.
- Passkey mode requires WebAuthn user verification and derives the encryption key from PRF output rather than storing it.
- Within `SeedVault.storeSeed`, encrypted replacement blobs are built before old seed formats are removed.
- Transaction payloads are encoded canonically and signed locally; the frontend does not send a private key or recovery phrase to the backend.
- PoW execution has a 60-second timeout and explicit worker termination; the runtime script-source weakness is documented in M-4.
- API GET/POST requests have a default 30-second abort deadline and preserve structured backend error codes.
- React escaping and `react-markdown`'s default raw-HTML behavior materially reduce stored-XSS risk.
- External media parsing restricts active iframe embeds to recognized providers; unknown values fall back to links/text.
- Production builds disable source maps, and the final Docker stage copies the compiled build rather than `node_modules`.
- Caddy serves uploaded media with `X-Content-Type-Options: nosniff`; dynamic API/chain responses are marked non-cacheable at the origin.

---

## Test Coverage Gaps

There is no `test` script or committed automated frontend test suite. The production build and lint command exercise compilation only. For wallet code, the missing behavioral coverage is itself a release risk.

The first tests should cover:

1. Seed-vault mode transitions, encryption/storage failures, WebAuthn cancellation, lock/unlock, auto-lock, and proof that protected-mode failures never create `seedPhrase` plaintext.
2. New/imported account routing with assertions that no phrase appears in browser history, URL, local/session storage, analytics payloads, or logs.
3. Queue ownership: A enqueues N actions, item 1 fails, sign-out occurs, B logs in, and every residual A action is rejected and removed.
4. Empty/invalid mnemonic rejection before every derivation/signing path.
5. Account A sign-out/account B login in the same tab while API/feed requests are cached or in flight; no A response may render after reset.
6. Concurrent queued and direct chain actions, with accurate status, balance, cancellation, and owner isolation.
7. CSP and security headers at both origin and CDN, including a frame-embedding failure test.
8. PoW worker artifact integrity and proof that runtime transaction flow makes no third-party script request.
9. Malicious Markdown/link/media fixtures: raw HTML, encoded protocols, protocol-relative navigation, oversized input, spoiler nesting, iframe IDs, and arbitrary media hosts.
10. Signed admin/API flows proving tampered browser levels cannot grant privileges and replayed signatures are rejected by the backend.
11. Password strength, short auto-lock, and step-up authentication before reveal/copy.
12. A production-bundle dependency check and reproducible build comparison from a clean lockfile.

---

## Urgency Assessment

| Priority | Findings | Rationale |
|---|---|---|
| **P0 — before relying on queued transactions across auth changes** | H-4 | A stale payment or public action can be signed by the wrong account. |
| **P0 — before claiming secure browser custody** | H-1, H-2, H-3 | Same-origin mutable code, plaintext/history persistence, and fail-open vault transitions defeat protected storage. |
| **P1 — next hardening release** | M-1 through M-7 | Browser containment, practical password protection, same-tab isolation, one transaction scheduler, self-hosted PoW, and reproducible builds are core wallet defenses. |
| **P2 — privacy/UX hardening** | L-1 through L-3 | Third-party media disclosure, forced logout, and inconsistent pending UI are contained but user-visible. |

---

## Prioritized Recommendations

1. Bind every queued intent to its signer, validate the mnemonic/owner immediately before signing, and reject/drain all residual work on failure, lock, sign-out, or account switch.
2. Remove GTM from the wallet origin. Move analytics to a non-executable, first-party event path or a separate public landing origin.
3. Make onboarding seed custody atomic: memory-only default, no router/history phrase, no insecure fallback, no early vault clear, and awaited durable storage before identity commit.
4. Add an enforced CSP plus anti-framing, referrer, permissions, and MIME-sniffing headers at the origin and verify CDN preservation.
5. Self-host and hash the Argon2 worker assets; make the production transaction path independent of runtime CDN scripts.
6. Add a single session reset that aborts requests and clears queue, pending, API, feed, bootstrap, and other per-tab caches.
7. Unify all chain actions under the owner-bound scheduler and apply global queue-status hooks to every blockchain button.
8. Add password strength, short auto-lock, and step-up controls; remove the duplicate phrase from top-level React state.
9. Patch React Router, lock the Babel build dependency, then replace the legacy CRA dependency tree through a tested build migration.
10. Establish browser-level tests around seed non-persistence and cross-account isolation before expanding frontend behavior.
11. Add privacy gates and restrictive policies for third-party/user-hosted media.

---

## Verification Performed

- `npm --prefix web/frontend run build` — **passed**, with the same 9 ESLint warnings and a 1.1 MB gzip main bundle.
- `npm --prefix web/frontend run lint` — **passed with 0 errors and 9 warnings** (unused variables in the four themed `ViewPostView.js` implementations).
- Scoped frontend `npm audit` — **failed: 59 vulnerabilities** (14 low, 19 moderate, 24 high, 2 critical).
- `npm outdated` — identified patch updates including `react-router-dom` 6.30.4 and several other direct dependencies.
- Frontend test invocation — **not available:** `package.json` has no `test` script.
- Production bundle inspection — vulnerable build-tree packages such as `elliptic` were not found in emitted JavaScript/license manifests; React Router is a runtime dependency.
- Empty mnemonic check — `bip39.validateMnemonic('')` returned false while `mnemonicToSeedSync('')` returned 64 bytes, confirming derivation must validate explicitly.
- Pattern review covered DOM sinks, URL/navigation APIs, external links/iframes/media, storage/cookies/history, seed/private-key access, logging, admin controls, API calls, timers/workers, and transaction enqueue/sign/broadcast paths.

The first npm commands attempted from the repository root were discarded because that directory has no frontend `package.json`; all reported dependency results use the explicit `web/frontend` prefix.

---

## Assumptions

- A recovery phrase is the account's durable signing authority and must be treated as a high-value secret.
- Users can lock, sign out, recover, or switch accounts while transaction work is queued or after one queued item fails.
- GTM container administrators can publish executable tags independently of a Mirage code release.
- CDN configuration may add defenses, but origin configuration is the repository-controlled baseline and must fail secure independently.
- Backend and chain authorization prevent forged admin authority, but they cannot distinguish an unintended stale action that is validly signed by the wrong locally loaded account.

---

## Follow-up Retest Guidance

A retest should begin with executable regressions, not only source inspection:

1. Queue a send plus a second action as account A, force item 1 to fail, sign out, log in as B, and prove no A intent signs or broadcasts and every promise/pending map settles.
2. Exercise every seed onboarding and vault-error branch, then inspect local storage, session storage, IndexedDB, `window.history.state`, logs, and analytics requests for phrase fragments.
3. Publish the built client under the deployment Caddy configuration and verify enforced CSP, denied framing, restrictive referrer/permissions headers, and no GTM request on wallet routes.
4. Confirm sign-out aborts requests and clears all per-tab caches, then run account A/account B same-tab isolation tests.
5. Exercise a queued send concurrently with posts, awards, subscriptions, and edit/delete actions; verify one owner-bound scheduler and accurate status.
6. Build twice from a clean checkout/lockfile and compare dependency resolution and artifacts; confirm no unpinned install or runtime CDN script occurs.
7. Re-run build, lint, the new browser test suite, dependency audit, and malicious Markdown/navigation/media fixtures.
