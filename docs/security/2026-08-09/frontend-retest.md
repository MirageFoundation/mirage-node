# Mirage Frontend Security Retest — 2026-08-09

Companion to [`2026-08-07/frontend-review.md`](../2026-08-07/frontend-review.md).

> **Two rows in the closure map below were wrong.** Corrected on 2026-08-14 by the
> [full frontend review](../2026-08-14/frontend-review.md); both are now closed for
> real in `v1.36.0`. The map is left as originally written, with the corrections
> marked inline, because rewriting it would hide the failure mode: a closure map is
> only useful if it can be audited against the findings it claims to close.
>
> 1. **M-1 was not closed.** Report-only is a milestone, not a closure, and the
>    rollout had no collector and so no way to conclude. Enforcing mode shipped in
>    `v1.36.0`.
> 2. **The review's M-7 was never closed; a different item was recorded under its
>    ID.** The 2026-08-07 M-7 is "the decrypted phrase is duplicated in App state
>    and reveal requires no step-up". The row below describes sign-out, which is
>    what M-5 already covered — two rows for session reset, and the real M-7
>    missing. Step-up shipped in `v1.36.0`.

## Finding closure map

| ID | Finding | Status | Evidence |
|---|---|---|---|
| H-1 | GTM on wallet origin | Closed | GTM removed from `index.html`; `tests/unit/noGtm.test.js`; `check:bundle-policy` |
| H-2 | Recovery phrase in router history | Closed | `onboardingSession.js` handoff; `useLogin`/`useCreateAccount`/`useWelcome` no longer put seeds in `location.state` |
| H-3 | Destructive signup / insecure vault fallback | Closed | Deferred vault commit; `setCredentials` no longer falls back to insecure on error |
| H-4 | Queue not owner-bound / incomplete drain | Closed | `TransactionHandler` stamps owner+session; `_drainQueue` / `cancelAll` / `resetSession` |
| M-1 | Missing CSP / anti-framing | ~~Closed (report-only)~~ **Not closed here — closed in `v1.36.0`** | Caddy CSP-Report-Only + `X-Frame-Options DENY` + `Referrer-Policy: strict-origin-when-cross-origin` (not `no-referrer` — YouTube embeds return Error 153 without a Referer) |
| M-2 | Weak password / no auto-lock | Closed | 12-char password policy; `vault_auto_lock_minutes` + `SeedVault.checkAutoLock` |
| M-3 | CRA audit debt / unpinned Docker install | Closed | Vite migration; Dockerfile unpinned Babel install removed |
| M-4 | Remote Argon2 | Closed | Vendored `/pow/argon2-bundled.min.js` + `MANIFEST.txt` |
| M-5 | Incomplete session reset | Closed | `sessionLifecycle.resetClientSession` + API abort generation |
| M-6 | Direct tx paths bypass queue | Closed | Former direct `performTransaction` callers queued |
| M-7 | ~~Sign-out incomplete~~ **Wrong finding — the real M-7 is "phrase duplicated in App state, reveal needs no step-up"** | ~~Closed~~ **Not closed here — closed in `v1.36.0`** | Sign-out drains queue via session reset (which is M-5's evidence, not M-7's) |
| L-1 | Media privacy / proxies | Accepted risk | Photon/wsrv thumbnail proxies retained deliberately — they keep the viewer's IP off the origin host and apply upstream abuse filtering (incl. CSAM) that a direct fetch would not. `mediaPolicy` still rejects unsafe URLs; `autoplay_media` default off |
| L-2 | Login autocomplete / help | Closed | Default `LoginView` autocomplete hardening + privacy helper text |
| L-3 | Vote buttons lack queue status | Closed | `formatVoteStatus` wired into all theme `VoteSection`s |

## Verification commands

```bash
cd web/frontend
npm ci --legacy-peer-deps
npm run check:pow-assets
npm run lint
npm run test
VITE_APP_VERSION=dev VITE_API_BASE=/api npm run build
npm run check:bundle-policy
npm audit --audit-level=high
```

Plaintext seed storage remains the intentional default.

---

## Appendix — delta review of post-retest commits (2026-08-12)

The closure map above was written against the Vite-migration hardening in `324b2d92`. Five commits touched the same paths afterwards and were reviewed on 2026-08-12 as part of the blockchain `v1.34.0` release gate. Reviewed range: `bd2c294f..4acbf0b9`, frontend commits `324b2d92`, `5e79df29`, `99745a82`, `cfaac16a`, `034a9e8b`.

**H-2 holds.** The "handoff signer metadata" that `5e79df29` threads through the transaction queue is `_signerSource: 'handoff'` and `_handoffPurpose: 'create-user-signing'` only. No mnemonic, seed, or private key is placed on a queue entry or on `final_transaction`; the phrase is resolved at signing time from the in-memory `onboardingSession` Map through `peekHandoffByPurpose`. Router state still carries only `handoffId`, `fromRecovery`, and `username`. The `99745a82` error hardening maps structured failures to generic copy through `errorMessages.js`, so no secret material reaches an error object or a rendered message.

**H-4 holds.** `_stampQueueEntry` still stamps owner and session generation on every enqueue, and `_verifyOwnerBinding` re-checks both at dequeue, pre-sign, and sign. For the handoff path the owner is derived from the handoff seed's public key and cross-checked against the stored handoff owner, so it cannot enqueue or drain under a different owner. `resetSession` drains the queue and then clears all handoffs. `5e79df29` fixed a real bug — without the copied signer source, sign-time verification read the still-empty vault — without weakening the binding.

**M-1 holds.** `Referrer-Policy: strict-origin-when-cross-origin` is set once, in `deploy/templates/caddy/Caddyfile`, and cross-origin requests therefore carry only scheme and host. No post path, post ID, username, or query string can reach YouTube, Rumble, a thumbnail proxy, or any other third-party request. Redgifs and Rumble iframes additionally set `referrerPolicy="no-referrer"` per element. `034a9e8b` restored exactly the Referer that YouTube requires and nothing more.

**L-1 acceptance is narrower than the shipped code.** The acceptance text describes *thumbnail* proxies keeping the viewer's IP off origin hosts, and that still describes card and feed thumbnails, which route through Photon or wsrv. It does not describe inline media: `InlineMedia` renders `src={resolved}` directly to the poster-chosen host at full resolution. Search-dropdown thumbnails also load unproxied. Both are outside the L-1 rationale as written.

### L-4 — dropping the click-to-load gate removed media-load consent (Low, newly accepted)

`cfaac16a` deleted `ExternalMediaGate`. The gate was network-silent: for a host that is not on the media allowlist it did not mount the `img`, `iframe`, or `video` at all until the reader clicked, and it displayed the external hostname first. Nothing replaced that specific protection. `classifyMediaUrl` still computes `autoLoad: false` for a non-allowlisted host (`mediaPolicy.js:119`), but no component reads the flag any more — it is now dead. `InlineMedia` keeps only the structural rejection (`InlineMedia.js:580-592`): a non-http scheme, embedded credentials, or control characters still refuse to render, so the URL-validation half of L-1 does hold. `autoplay_media` gates playback, not loading, and does not cover images.

The consequence is stated plainly because it is a real regression against the gate era: a post author can now learn the IP address and user agent of any reader who scrolls past inline media on an unknown host, with no click. That is the same tracking class as the original L-1 and is accepted for the same reason the proxies are — the alternative measurably hurt the reading experience — but it is recorded as its own item rather than folded into L-1, because the proxy rationale does not apply to a direct inline fetch.

**Trigger for revisiting:** a report of media used to profile readers, or any decision to restore consent UI. **Cheapest partial mitigations, not shipped:** re-gate only the `autoLoad === false` branch of `InlineMediaBody`, and route `SearchDropdown`'s `getPostThumbnail` through `buildThumbProxy` so dropdown thumbnails match the rest of the feed.

**Verification note.** This appendix is source review only. The frontend suites listed under Verification commands were not re-run for it.
