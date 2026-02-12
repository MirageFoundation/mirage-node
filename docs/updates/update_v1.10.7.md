# Mirage v1.10.7 Release Notes

### Overview

v1.10.7 is a privacy and security release. Your seed phrase—the key to your account—now has real protection. Choose how it's stored: encrypt it with a password, keep it in memory only so it's gone when you close the tab, or lock it behind your device's biometrics with a passkey. No more plaintext secrets sitting in your browser if you don't want that (but you can do that of course if you prefer).

On the privacy side, we've ripped out the entire device fingerprinting system. No more browser fingerprints, no IP hashes, no raw user-agent strings, no sock puppet detection scripts. Stats are now simple DAU/MAU counts with coarse device categories—enough to understand usage patterns without profiling anyone. We understand that was a major concern, and since it was not used at all, we removed it entirely.

This release also hardens the backend. Error messages no longer leak internal details to the client. Every exception is logged server-side with a request ID; the user only sees a clean, generic message. Combined with new spoiler tags in posts and server-side inbox notifications, v1.10.7 is a meaningful step toward a more private and polished experience.

---

### Seed Phrase Security

- Four storage modes: plaintext (legacy), password-encrypted, memory-only, and passkey (WebAuthn)
- Password mode uses AES-GCM with PBKDF2 key derivation—unlock once per session
- Passkey mode uses hardware-backed encryption via Touch ID, Face ID, or security keys
- Memory-only mode never persists the seed—re-enter it each session
- New settings UI for switching modes, viewing recovery phrase, and security status banner
- Unlock overlay prompts for the password or passkey when the vault is locked

---

### Privacy: Fingerprinting Removed

- Deleted the entire fingerprinting system: frontend collector, backend endpoint, shared analysis module
- Dropped user-agent strings, IP hashes, and referrer tracking from the database
- Stats simplified to DAU/MAU with server-side bot filtering
- Device breakdowns now use coarse categories (e.g. "Chrome", "desktop") extracted at ingest—never the raw User-Agent
- Removed sock puppet detection, user profiling, and account classification scripts

---

### Spoiler Tags

- New `||spoiler text||` syntax in the markdown editor
- Click-to-reveal interaction—spoiler content is hidden until tapped
- Works in posts and comments

---

### Server-Side Inbox Notifications

- Inbox unread count now tracked server-side instead of localStorage
- Every API response includes the current unread count for logged-in users
- Badge shows the actual number of new items, not just a dot
- 60-second server-side cache keeps it fast

---

### Sanitized Error Responses

- Backend no longer returns raw exception text to clients
- 77 instances of leaked error details replaced with generic messages
- Full exceptions logged server-side with request IDs for debugging
- New `safe_error()` helper and global Flask error handler

---

### Admin Gas Fee (Non-Blocking)

- Admin relay operations (account creation, username changes) no longer fail when the admin wallet has insufficient gas
- Gas fee deduction is skipped instead of blocking the transaction
- Backend classifies admin balance errors as 400 instead of 500
- Frontend shows clear messages when admin balance is low

---

### Bug Fixes

- Fixed MIRAGE balance wrapping around at ~4,294 MIRAGE due to 32-bit integer overflow
- Fixed balance showing stale values across pages—single `useBalance` hook as source of truth
- Balance injected into all address-aware API responses for automatic frontend sync
- Fixed scrolling broken in Telegram WebView and Brave
- Fixed inbox badge clipping when count text is too wide

---


### Roadmap

- Galleries—multiple images and videos in a single post
- Tag users with @ mentions for notifications
- Block entire topics or keywords you don't want to see

Have a feature suggestion? Let us know on [Mirage](https://mirage.talk) — post it in the #feedback topic or message us directly.
