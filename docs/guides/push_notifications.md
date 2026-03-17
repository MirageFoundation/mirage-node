# Mobile Client: Push Notification Integration

## Overview

The backend now supports Expo push notifications for inbox events (replies, mentions, awards). Not every node enables this — the mobile app must check the node's config and gracefully fall back to local polling when unsupported.

**Key rules:**

- Max **3 server-side pushes** per user, then silence until the user views their inbox.
- The same 3-notification budget is shared with local polling — the mobile app must respect it client-side.
- Push tokens must be explicitly unregistered on **logout** and **server switch**.
- Notification banners must be **suppressed** when the inbox screen is active.

## Backend Changes Summary (for mobile dev)

- Push support is gated by `push_notifications_enabled` in `/api/get_node_config`. If false, skip all push registration and keep local polling only.
- `register_push_token`, `unregister_push_token`, and `mark_inbox_viewed` are signed endpoints that require `pubkey`, `signature`, `timestamp` (ms), and `envelope_nonce`.
- A push token can only be registered to one account at a time; attempting to register a token owned by another user returns `409`.
- The 3-notification budget resets only when `mark_inbox_viewed` succeeds.
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

**Note:** a push token can only be registered to one account at a time. If you need to switch accounts, you must unregister first or the backend will return `409`.

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

1. **Logout** — call **before** wiping the wallet from the auth store. Once the wallet is gone you can't sign the request.
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
    "replyId": "def456..."
  },
  "sound": "default",
  "channelId": "inbox"
}
```

The `data.type` field is one of: `"reply"`, `"mention"`, `"award"`.

Create an Android notification channel `"inbox"` at app startup:

```typescript
Notifications.setNotificationChannelAsync("inbox", {
  name: "Inbox",
  importance: Notifications.AndroidImportance.HIGH,
  sound: "default",
});
```

---

## 5. Notification Budget (Client-Side)

The server enforces a budget of 3 pushes, but the mobile app's **local polling** must also respect this shared budget. The combined total of server pushes + locally-generated notifications must not exceed 3.

### Tracking

Use MMKV to store a counter:

```
push-budget-remaining: number  (initialize to 3)
```

- When a push notification arrives (via `Notifications.addNotificationReceivedListener`), decrement the counter.
- When local polling would fire a notification, check the counter first — skip if 0.
- When `mark_inbox_viewed` succeeds, reset the counter to 3. **This endpoint now requires a signed payload** (see below).

### Deduplication

Server pushes and local polling can overlap. When a server push arrives with `data.replyId`, add that ID to your existing `inbox-notified-ids` set in MMKV. Your local polling logic (`inbox-notifications.ts`) already checks this set before firing — so it will skip any event the server already pushed.

Listener example:

```typescript
Notifications.addNotificationReceivedListener((notification) => {
  const data = notification.request.content.data;
  if (data?.replyId) {
    addToNotifiedIds(data.replyId);
  }
  decrementBudget();
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
- [ ] Add push received listener: track `replyId` in notified-ids, decrement budget.
- [ ] Local polling: check budget before firing, skip if 0.
- [ ] `mark_inbox_viewed`: reset local budget counter to 3.
- [ ] Suppress notification banners when inbox screen is active.
- [ ] Handle deep linking from notification taps (navigate to `rootPostId`).
