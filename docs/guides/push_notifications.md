# Mobile Client: Push Notification Integration

## Overview

The backend now supports Expo push notifications for inbox events (replies, mentions, awards). Not every node enables this — the mobile app must check the node's config and gracefully fall back to local polling when unsupported.

**Key rules:**

- Max **5 server-side pushes** per user in any **30-minute window**. After that, new events are suppressed.
- When the 30-minute window expires and events were suppressed, the server automatically sends a single summary push ("You have N unread messages").
- After a summary, pushes are **paused for 3 hours** or until `mark_inbox_viewed` is called.
- There is **no client-side budget** to track — the server handles all throttling.
- Push tokens must be explicitly unregistered on **logout** and **server switch**.
- Notification banners must be **suppressed** when the inbox screen is active.

## Backend Changes Summary (for mobile dev)

- Push support is gated by `push_notifications_enabled` in `/api/get_node_config`. If false, skip all push registration and keep local polling only.
- `register_push_token`, `unregister_push_token`, and `mark_inbox_viewed` are signed endpoints that require `pubkey`, `signature`, `timestamp` (ms), and `envelope_nonce`.
- A push token belongs to whichever account most recently registered it. Registration is last-writer-wins: the signed-in account takes ownership of the device token (so account switches recover even if the previous logout unregister failed).
- Push notifications are throttled to **5 per 30 minutes** per user. Suppressed events trigger a summary push after the window expires.
- `EXPO_ACCESS_TOKEN` is optional and only needed if the node enables "Enhanced Push Security" in the EAS dashboard.

---

## 1. Check Node Capability

Before registering a push token, check if the current node supports push notifications.

`GET /api/get_node_config` now returns:

```json
{
  "push_notifications_enabled": true,
  ...
}
```

Add `push_notifications_enabled: boolean` to your `NodeConfigResponse` type (`src/api/types.ts`).

If `false` or missing, skip all push registration — continue using local polling only.
If push registration fails for any reason (permissions denied, token fetch error, API error), you MUST fall back to the existing background refresh/local polling flow.

---

## 2. Register Push Token

After the user logs in (and `push_notifications_enabled` is `true`), get an Expo push token and register it with the backend.

**Note:** a push token is owned by one account at a time, but registration is last-writer-wins — the signed-in account automatically takes ownership of the device token. Unregistering on account switch is still recommended (so the previous account stops receiving pushes promptly), but no longer required: registering under the new account transfers the token.

### Getting the token

```typescript
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

const { status } = await Notifications.requestPermissionsAsync();
if (status !== "granted") return;

const tokenData = await Notifications.getExpoPushTokenAsync({
  projectId: "your-expo-project-id",
});
const token = tokenData.data; // "ExponentPushToken[...]"
const platform = Platform.OS; // "ios" or "android"
```

### Endpoint

`POST /api/core/register_push_token` (signed endpoint)

**Request body:**

```json
{
  "pubkey": "<base64>",
  "signature": "<base64>",
  "timestamp": 1700000000000,
  "envelope_nonce": 123456789,
  "token": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]",
  "platform": "ios"
}
```

**Signing**: the signature covers this exact UTF-8 string:

```
register_push_token:{token}:{platform}:{timestamp}:{nonce}
```

For example:
```
register_push_token:ExponentPushToken[abc123]:ios:1700000000000:123456789
```

Sign the SHA-256 hash of these bytes with the user's private key (same secp256k1 compact signature as other core endpoints).

**Timestamp / nonce rules**:

- `timestamp` must be **milliseconds** since epoch (UTC), and within **±5 minutes** of server time.
- `envelope_nonce` must be **unique** per request; replays are rejected.

**Response:**

```json
{ "ok": true }
```

**Errors:** `404` if push not enabled on this node, `400` for validation failures, `503` if node is catching up.

**Ownership:** Expo push tokens are device-scoped (the same device keeps its token across logout and reinstall). Registration is **last-writer-wins** — the signed-in account takes ownership of the token, transferring it from any previous account on that device. This means a failed logout unregister (offline / network error) is self-healing: the next successful register on the device reassigns the token to the active account.

### When to call

- After login, once you have the wallet and the node config confirms push support.
- On app foreground (re-register to keep `last_used_at` fresh — the endpoint is an upsert).

---

## 3. Unregister Push Token

### Endpoint

`POST /api/core/unregister_push_token` (signed endpoint)

**Request body:**

```json
{
  "pubkey": "<base64>",
  "signature": "<base64>",
  "timestamp": 1700000000000,
  "envelope_nonce": 123456789,
  "token": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]"
}
```

**Signing**: signature covers this exact UTF-8 string:

```
unregister_push_token:{token}:{timestamp}:{nonce}
```

**Response:**

```json
{ "ok": true }
```

**Timestamp / nonce rules**:

- `timestamp` must be **milliseconds** since epoch (UTC), and within **±5 minutes** of server time.
- `envelope_nonce` must be **unique** per request; replays are rejected.

### When to call

1. **Logout** — call **before** wiping the wallet from the auth store. Once the wallet is gone you can't sign the request. This is best-effort: if it fails (offline / network error), the next account to register on this device automatically takes ownership of the token, so a missed unregister is self-healing.
2. **Server switch** — unregister from the old server, then register on the new one (if it supports push).

---

## 4. Push Payload Format

When the backend sends a push notification, the payload looks like:

```json
{
  "title": "@alice replied",
  "body": "I think that's a great point...",
  "data": {
    "type": "reply",
    "rootPostId": "abc123...",
    "replyId": "def456...",
    "notificationType": "inbox",
    "notificationId": "inbox-reply:def456..."
  },
  "sound": "default",
  "channelId": "inbox"
}
```

The `data.type` field is one of: `"reply"`, `"mention"`, `"award"`, `"summary"`, `"trending"`.

Every payload also carries two fields the server always sets so notification taps (especially on Android) resolve to an identifiable target:

- `notificationType`: `"inbox"` for inbox events (reply / mention / award / follow / donation / subscription_gift / summary) or `"trending"` for trending pushes.
- `notificationId`: a stable id derived from the payload — `<notificationType>-reply:<replyId>`, else `<notificationType>-root:<rootPostId>`, else `inbox-summary:<unixSeconds>` for summaries.

Summary notifications are sent automatically by the server when the user's 30-minute throttle window expires with suppressed events. They look like:

```json
{
  "title": "Mirage",
  "body": "You have 7 unread messages",
  "data": {
    "type": "summary",
    "notificationType": "inbox",
    "notificationId": "inbox-summary:1700000000"
  },
  "sound": "default",
  "channelId": "inbox"
}
```

When receiving a `"summary"` type, navigate to the inbox screen rather than a specific post. The `inbox-summary:<unixSeconds>` id is unique per send (a tap identity, not a collapse key).

Create an Android notification channel `"inbox"` at app startup:

```typescript
Notifications.setNotificationChannelAsync("inbox", {
  name: "Inbox",
  importance: Notifications.AndroidImportance.HIGH,
  sound: "default",
});
```

---

## 5. Throttle and Summary Notifications

The server enforces a **5-per-30-minute** sliding window per user. The mobile app does **not** need to track any client-side budget.

When a user receives more than 5 inbox events within 30 minutes, extra events are silently suppressed. Once the window expires, the server sends a single summary push with the total unread count (e.g., "You have 12 unread messages").

After sending a summary, the server pauses all pushes for **3 hours**. The cooldown ends early if the user calls `mark_inbox_viewed`.

### Deduplication

Server pushes and local polling can overlap. When a server push arrives with `data.replyId`, add that ID to your existing `inbox-notified-ids` set in MMKV. Your local polling logic (`inbox-notifications.ts`) already checks this set before firing — so it will skip any event the server already pushed.

Listener example:

```typescript
Notifications.addNotificationReceivedListener((notification) => {
  const data = notification.request.content.data;
  if (data?.replyId) {
    addToNotifiedIds(data.replyId);
  }
});
```

---

## 6. Suppress Banners When Inbox Active

When the user is already viewing the inbox screen, incoming push banners are redundant and disruptive.

Use `Notifications.setNotificationHandler` to suppress them conditionally:

```typescript
Notifications.setNotificationHandler({
  handleNotification: async (notification) => {
    const isInboxActive = /* check your navigation state */;
    return {
      shouldShowAlert: !isInboxActive,
      shouldPlaySound: !isInboxActive,
      shouldSetBadge: true,
    };
  },
});
```

---

## 7. Signing `mark_inbox_viewed`

`POST /api/mark_inbox_viewed` now requires a signed payload.

Calling this endpoint also clears any active push cooldown for the user.

**Request body:**

```json
{
  "pubkey": "<base64>",
  "signature": "<base64>",
  "timestamp": 1700000000000,
  "envelope_nonce": 123456789,
  "address": "mirage1..."
}
```

`address` is optional, but if present must match the pubkey-derived address. The signed payload always uses the pubkey-derived address.

**Signing**: signature covers this exact UTF-8 string:

```
mark_inbox_viewed:{address}:{timestamp}:{nonce}
```

**Timestamp / nonce rules**:

- `timestamp` must be **milliseconds** since epoch (UTC), and within **±5 minutes** of server time.
- `envelope_nonce` must be **unique** per request; replays are rejected.

---

## 8. Integration Checklist

- [ ] Add `push_notifications_enabled` to `NodeConfigResponse` type.
- [ ] Create `registerPushToken` / `unregisterPushToken` write endpoints in `src/api/write/`.
- [ ] After login: check node config → request permissions → get Expo token → register.
- [ ] On app foreground: re-register token (upsert keeps `last_used_at` fresh).
- [ ] On logout: unregister token **before** wallet wipe.
- [ ] On server switch: unregister from old server, register on new (if supported).
- [ ] Create `"inbox"` Android notification channel at startup.
- [ ] Add push received listener: track `replyId` in notified-ids for deduplication.
- [ ] Handle `data.type === "summary"` — navigate to inbox screen.
- [ ] Suppress notification banners when inbox screen is active.
- [ ] Handle deep linking from notification taps (navigate to `rootPostId`).
