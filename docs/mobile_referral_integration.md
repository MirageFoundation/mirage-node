# Referral System — Mobile Integration Guide

This document covers the referral link signup flow and referral dashboard for mobile clients.

---

## Overview

Users can share referral links (`https://node.example/signup?ref=USERNAME`) that let new users sign up using the referrer's invite codes. The flow:

1. New user opens a referral link containing `?ref=<username>`
2. App calls **precheck** to verify the referrer is valid and has codes
3. New user picks a username and submits (the referrer username is sent along)
4. Backend atomically assigns one of the referrer's invite codes to the new account
5. Referrers can view their referred users and activity stats in a **Referrals** dashboard

Referral links only work when `registration_invite_code_required = true` in the node config. If the node doesn't require invite codes, the referral flow is inactive.

---

## 1. Deep Link Handling

When the app opens a URL like `https://node.example/signup?ref=God`, extract the `ref` query parameter and store it in memory (component state only — do NOT persist it).

Also support the existing direct invite code parameter: `?invite=XXXX-XXXX`.

Priority: if both `ref` and `invite` are present, prefer `invite` (direct code).

---

## 2. Node Config Check

`GET /api/get_node_config` returns (among other things):

```json
{
  "registration_enabled": true,
  "registration_invite_code_required": true
}
```

- If `registration_invite_code_required` is `false`, ignore the `?ref=` parameter entirely — referral links are not active.
- If `registration_enabled` is `false`, registration is fully disabled.

---

## 3. Referral Precheck

**Endpoint:** `GET /api/referrals/precheck`

**Auth:** None (unauthenticated).

**Query params:**

| Param      | Type   | Required | Description              |
|------------|--------|----------|--------------------------|
| `username` | string | yes      | The referrer's username   |

**Success response (200):**

```json
{
  "valid": true,
  "available": 17
}
```

`available` = number of unused invite codes the referrer has. Display this to create urgency (e.g. "Only 17 codes left").

**Failure responses (200 with `valid: false`):**

```json
{ "valid": false, "error": "referrer not found" }
{ "valid": false, "error": "referrer has not enabled referral links" }
{ "valid": false, "error": "referrer has no available codes" }
{ "valid": false, "error": "already used this referrer" }
{ "valid": false, "error": "invite codes not required on this node" }
```

Error strings are lowercase human-readable (consistent with the rest of the API). Map them to proper user-facing copy on the client:

| Backend Error | Suggested User Message |
|---------------|----------------------|
| `already used this referrer` | "You already used this referrer." |
| `referrer has no available codes` | "This referrer has no invite codes left." |
| `referrer not found` | "Referrer not found." |
| `referrer has not enabled referral links` | "This referrer has not enabled referral links." |
| `invite codes not required on this node` | "Invite codes are not required on this node." |

**UI behavior by precheck result:**

| Result | UI State |
|--------|----------|
| `valid: true` | Show "Code applied" (disabled input), show available count, show username input + Continue button |
| `valid: false`, error = `"you already used your code"` | Show error in disabled input field. **Hide** the username input and submit button entirely. Show a "Have an invite code? Enter it manually" link that navigates to plain `/signup` |
| `valid: false`, any other error | Show error in disabled input. Optionally let user enter a direct invite code manually |
| Precheck loading | Show "Checking referral..." in disabled input, hide submit button |

**Important:** The "Code applied" / "Checking referral..." input field should be **unclickable** (`disabled`, no pointer events).

---

## 4. Account Creation with Referrer

**Endpoint:** `POST /api/core/set_username`

This is the existing signup endpoint. To use the referral path, include `referrer_username` in the JSON body **instead of** `invite_code`.

**Request body (referral path):**

```json
{
  "pubkey": "<base64>",
  "signature": "<base64>",
  "username": "chosen-name",
  "last_block_hash": "<hex>",
  "pow_difficulty": 20,
  "pow": 12345,
  "timestamp": 1711324800,
  "nonce": "random-uuid",
  "referrer_username": "God"
}
```

**Key rules:**

- Send `referrer_username` OR `invite_code`, never both.
- `referrer_username` must be alphanumeric + hyphens only (`[A-Za-z0-9-]+`).
- The backend resolves the username to an address, verifies available codes, and atomically assigns one after the transaction succeeds.
- Self-referral (`referrer_username` = the new user's own username) is rejected.

**Referral-specific errors (400):**

```json
{ "error": "referral links require invite codes" }
{ "error": "referrer username too long" }
{ "error": "invalid referrer username format" }
{ "error": "referrer not found" }
{ "error": "self-referral is not allowed" }
{ "error": "already used this referrer" }
```

If the referrer runs out of codes between precheck and submit, the account is still created (PoW was already done and tx broadcast), but no referral link is recorded. This is a rare edge case.

**Direct invite code path (unchanged):**

```json
{
  "pubkey": "...",
  "signature": "...",
  "username": "chosen-name",
  "invite_code": "ABCD-EFGH",
  "...": "..."
}
```

Code format: `XXXX-XXXX` (uppercase, 4 chars, dash, 4 chars).

---

## 5. User Status — Precheck Opt-In Flag

`GET /api/get_user_status` returns a new field:

```json
{
  "referral_precheck_enabled": false
}
```

This indicates whether the logged-in user has opted in to allow their username to be used in referral precheck lookups. If `false`, anyone visiting `?ref=<their-username>` will get `"referrer has not enabled referral checks"`.

---

## 6. Referral Precheck Opt-In Toggle

**Endpoint:** `POST /api/referrals/precheck_opt_in`

**Auth:** Signed request (same envelope pattern as other authenticated endpoints).

**Request body:**

```json
{
  "pubkey": "<base64>",
  "signature": "<base64>",
  "address": "mirage1...",
  "enabled": true,
  "timestamp": 1711324800,
  "nonce": "random-uuid"
}
```

**Signature payload** (sign this exact string as UTF-8 bytes):

```
referrals_precheck_opt_in:<address_lowercase>:<enabled_flag>:<timestamp>:<nonce>
```

Where `<enabled_flag>` is `"1"` for true, `"0"` for false.

**Response:**

```json
{
  "ok": true,
  "precheck_enabled": true,
  "updated_at": 1711324800
}
```

**UI:** This is a toggle in Settings. Label it something like "Referral links" with explanatory text: "Allow people to sign up using a personal link with your username. Anyone with the link can use your codes, so leave this off if you want to hand them out manually."

**Visibility:** Only show this setting when `registration_invite_code_required` is `true` in the node config.

---

## 7. Referrals Dashboard

**Endpoint:** `GET /api/referrals/summary`

**Auth:** None (unauthenticated — uses the address directly).

**Query params:**

| Param    | Type   | Required | Default | Description |
|----------|--------|----------|---------|-------------|
| `address`| string | yes      | —       | The referrer's address (e.g. `mirage1abc...`) |
| `period` | string | no       | `"7d"`  | `"7d"`, `"30d"`, or `"month"` |
| `month`  | string | no       | —       | Required when `period=month`. Format: `"YYYY-MM"` |
| `limit`  | int    | no       | 50      | Page size (1–200) |
| `offset` | int    | no       | 0       | Pagination offset |

**Response:**

```json
{
  "referrals": [
    {
      "address": "mirage1xyz...",
      "username": "alice",
      "referred_at": 1711200000,
      "posts": 5,
      "votes": 12,
      "total_actions": 17
    }
  ],
  "total": 3,
  "period_start": 1710720000,
  "period_end": 1711324800,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

**Fields per referral:**

| Field           | Type   | Description |
|-----------------|--------|-------------|
| `address`       | string | Referred user's address |
| `username`      | string | Referred user's username (may be empty if not yet set) |
| `referred_at`   | int    | Unix timestamp of when they signed up |
| `posts`         | int    | Number of posts in the selected period |
| `votes`         | int    | Number of votes in the selected period |
| `total_actions` | int    | `posts + votes` |

**"Real user" indicator:** A referred user with `total_actions >= 10` should be highlighted (green badge, checkmark, etc). This is purely a frontend concern — the backend does not send a flag for it.

**Period tabs:** `Last 7 Days` | `Last 30 Days` | `This Month` | `Last Month`

**Pagination:** Use `has_more` to show a "Load More" button. On load-more failure, keep existing data visible and show an inline error.

---

## 8. Share URL Construction

On the referrals dashboard, show a share box with the user's referral link. The URL depends on the user's settings:

| Condition | Share URL |
|-----------|-----------|
| `referral_precheck_enabled` is `true` | `https://node/signup?ref=USERNAME` |
| Has unused invite codes | `https://node/signup?invite=CODE` (first available code) |
| Neither | Don't show the share box |

To get the user's invite codes: `GET /api/get_invite_codes?address=<address>` returns `{ "codes": [{ "code": "ABCD-EFGH", "is_used": false }, ...] }`.

---

## 9. Client Hash Gate

The backend uses a salted hash of the client's IP address to prevent the same device from using the same referrer multiple times. This is checked at:

1. **Precheck** — returns `"you already used your code"` if the device already signed up via this referrer
2. **Submission** — returns `"you already used your code"` as a server-side backstop

The client does not need to send any special headers for this. The backend reads `CF-Connecting-IP` (behind Cloudflare) or falls back to the raw TCP peer address.

If the precheck returns `"you already used your code"`, the mobile app should block the signup form (hide username input and submit button) and suggest entering a direct invite code instead.

---

## 10. Summary of New/Modified Endpoints

| Endpoint | Method | Auth | New? |
|----------|--------|------|------|
| `/api/referrals/precheck` | GET | No | New |
| `/api/referrals/precheck_opt_in` | POST | Signed | New |
| `/api/referrals/summary` | GET | No | New |
| `/api/core/set_username` | POST | Signed | Modified (accepts `referrer_username`) |
| `/api/get_user_status` | GET | Signed | Modified (returns `referral_precheck_enabled`) |
| `/api/get_node_config` | GET | No | Unchanged (already has `registration_invite_code_required`) |
| `/api/get_invite_codes` | GET | No | Unchanged |
