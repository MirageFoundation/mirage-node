# Mobile Developer Notes

## Optimistic Post Creation

When a user creates a root post, the mobile app should show the post as soon as the broadcast returns a transaction hash. Do not keep the composer in a user-facing "verifying" state while waiting for the indexer. For posts, the transaction hash is the real post id, so the app already has the stable identifier it needs.

Expected flow:

1. Submit the signed `create_post` transaction through the normal relay endpoint.
2. If the response is successful and includes `tx_hash`, lowercase it and treat it as the canonical `post_id`.
3. Immediately build an optimistic root post and navigate/render `/p/{tx_hash}`.
4. Poll or retry in the background until `get_comments` returns the indexed root post.
5. Replace the optimistic object with the indexed API object. This should be visually invisible unless the indexed data includes new metadata.
6. If transaction status later reports rejection, remove the optimistic post and show a clear failure message.

The optimistic root post should use this shape:

```javascript
{
  post_id: txHash,
  tx_hash: txHash,
  author: viewerAddress,
  user_id: viewerAddress,
  username: cachedUsername,
  timestamp: Math.floor(Date.now() / 1000),
  topic,
  title,
  content,
  target: "",
  root_post_id: txHash,
  tag,
  media,
  thumbnail,
  direction: 1,
  user_vote: 1,
  user_weight: 1,
  points: 1,
  comments: 0,
  deleted: false,
  _optimistic: true
}
```

The `user_weight: 1` field matters. Mirage vote displays are calculated as:

```javascript
displayVotes = Math.round(points - user_weight + direction)
```

Without `user_weight`, a new optimistic post with `points: 1` and active `direction: 1` renders as `+2`, then corrects to `+1` after indexing. Keep `points`, `user_vote`, `user_weight`, and `direction` aligned so the score does not jump.

Persist the optimistic post briefly by `post_id` so a refresh or immediate route transition can render it while the indexer catches up. A short TTL is enough; the web frontend uses a bounded local cache and removes the entry once `get_comments` returns the real root.

Detail views should treat a temporary `404` from `get_comments` as indexer lag if a matching optimistic post exists. Render the optimistic copy instead of an error card, then keep retrying quietly in the background.

Background reconciliation should:

- call `get_tx_status` or retry `get_comments` on a bounded schedule;
- replace the optimistic root when `get_comments({ post_id: txHash, address })` returns data;
- remove the optimistic cache entry after replacement;
- remove the optimistic cache entry and show an error if the transaction is rejected;
- leave the user on the real post id throughout, since the hash does not change.

Replies already use a similar optimistic pattern, but root posts need this extra route/cache handling because the app navigates directly to `/p/{tx_hash}` before the backend/indexer can always serve the post.

## Media Uploads (v1.29.0)

### One upload endpoint

Use `POST /api/upload_media` for all uploads. It is provider-agnostic — the node hides whether it stores to local disk, Cloudflare, or Bunny behind this single endpoint.

```
POST /api/upload_media          (multipart/form-data)
  kind:     "image" | "video"
  file:     the bytes
  duration: required for video (seconds, probed client-side)
  height:   required for video (pixels, probed client-side)

200 -> { url, asset_id, kind }
```

The old `POST /api/get_upload_url` (Cloudflare browser-direct-upload shape) has
been **removed**. Use `POST /api/upload_media` only. See
[`mobile_instant_load.md`](./mobile_instant_load.md) for the one-call cold
start and thread `ancestors` contract.

### Uploads can be disabled per node

A node only accepts uploads when it sits behind a content-scanning edge. Nodes that do not (for example IP-only nodes) reject every upload with:

```
403  { "error": "uploads_disabled" }
```

This is returned by both `/api/upload_media` and the legacy `/api/get_upload_url`. It is **not** advertised in `get_node_config`, so the app should treat a `403 uploads_disabled` as a signal to hide or disable the attach-media UI (or show a clear "uploads are off on this server" message) rather than surfacing it as a generic upload failure.

### Video limits (raised in v1.29.0)

Video uploads now allow roughly **30 minutes** and a larger file size:

- Max duration: 1800s (30 min).
- Max size: 1500 MB (images remain 15 MB).

`duration` and `height` are **required** for video — the node has no transcoder for the local default and uses them to apply the resolution policy. Validate client-side before transferring a large file, because the server enforces the same limits and returns specific error codes you should map to friendly messages:

- `video_too_long` (400) — duration exceeds the cap.
- `media_too_large` (413) — file exceeds the size cap.
- `media_metadata_required` (400) — missing/invalid `duration` or `height`.
- `media_invalid_type` (415) — content does not match `kind` (the server sniffs magic bytes, never the filename).
- `media_invalid_kind` / `media_file_required` (400) — malformed request.

Long-form clips (over 60s) above 1080p may be rejected on non-transcoding nodes, since those nodes cannot downscale.

## Sticker Assets Moved to the Bunny CDN

Sticker packs are now served from the Bunny CDN instead of Cloudflare Images. The base path is:

```
https://mirage-img.b-cdn.net/stickers/<pack>/<NN>.webp
```

for example `https://mirage-img.b-cdn.net/stickers/meme/01.webp`. If your app embeds the sticker list, mirror this new base path (note the `.webp` extension — the web client uses WebP, not PNG) and drop any hard-coded `imagedelivery.net` URLs.

## Open Browsing (v1.29.0)

Logged-out visitors can now read everything — feeds, posts, profiles, search — and are only prompted to create an account when they attempt a write/social action (post, vote, follow, reply). This is controlled per-node by the `open_browsing_enabled` boolean in `get_node_config`.

Mobile guidance:

- Read `open_browsing_enabled` from `get_node_config`. When `true`, render the feed/post/search views for visitors with no account instead of an up-front login wall.
- Gate only write/social actions. On tap, if there is no account, show the signup flow instead of performing the action.
- Until `get_node_config` has loaded, treat open-browsing state as unknown and do NOT render either gate — otherwise the logged-out wall flashes on cold start before the config resolves.
- When `open_browsing_enabled` is `false` (invite-only nodes), keep the existing behavior: those actions are unreachable without an account anyway.

## Server-enforced Agents (`auto_enabled_agents`)

`get_node_config` now returns `auto_enabled_agents`: a list of agent `mirage1` addresses the node injects as enabled for every user (e.g. AntiSpamBot on mirage.talk). These are merged on top of the user's own enabled agents.

Mobile guidance:

- Read `auto_enabled_agents` (array of lowercase addresses) from `get_node_config` and merge it into the viewer's enabled-agent set for feed filtering, deduping by address.
- Treat them as enabled for filtering purposes even though they are not in the user's own on-chain enabled list. The list may be empty on most nodes.

## Video Posters / Thumbnails

A returned video `url` is a stream (HLS playlist for transcoding providers), and the still poster is derived from it per provider. The critical caveat: the provider generates the server-side thumbnail during transcoding, so Bunny Stream returns **HTTP 404** for `/{guid}/thumbnail.jpg` until processing finishes. A client that fetches the poster right after upload and never retries shows a permanently blank tile.

For the just-uploaded composer preview, capture the first frame from the local file you already have (iOS `AVAssetImageGenerator`, Android `MediaMetadataRetriever`, or `expo-video-thumbnails`) and show that immediately. For already-published posts in the feed the server thumbnail is reliably available. Full per-provider poster paths and the retry alternative are documented in [media_providers.md](media_providers.md) under "Video posters / thumbnails".

## Media Downloads

Downloads are resolved entirely client-side from the post's media URL — there is no backend download endpoint. The web logic lives in `web/frontend/src/utils/media.js` (`getMediaDownloadInfo`); mirror this resolution on mobile:

- Bunny Stream (`https://{host}/{guid}/playlist.m3u8`) → `https://{host}/{guid}/original` (uploaded source; may be mp4/mov/webm — sniff magic bytes for the filename extension; do not assume `.mp4`. `play_{N}p.mp4` only exists if the library has MP4 Fallback enabled).
- Label the affordance "Download video (MP4)" only when the format is known to be mp4 (Cloudflare download URL, `.gifv`→`.mp4`, or a URL whose path already ends in `.mp4`). For Bunny originals leave it as "Download video" until/unless you sniff.
- On web, cross-origin ignores the HTML `download` attribute (Bunny would save as the path basename `original` with no extension), so the client fetches the file as a blob and saves via an object URL with the sniffed filename. Mobile can write the response body straight to disk with that name.
- Cloudflare Stream (`cloudflarestream.com` / `videodelivery.net`) → `https://videodelivery.net/{uid}/downloads/default.mp4`.
- `.gifv` → swap the extension to `.mp4`.
- Direct image/video files (including `imagedelivery.net` images) → download the URL as-is.
- YouTube, bare HLS `.m3u8` manifests, and other non-direct sources have no download and should be skipped (no download affordance).

## Profile follow counts (v1.30.0)

When a profile screen opens, `GET /api/get_profile?address=<addr>` returns two
additive integers alongside the existing profile fields:

- `following_count` — how many users this account follows
- `follower_count` — how many users follow this account

Show both in the profile header / about section (web already does). Do not
infer followers from the `followed_users` list — that list is the account's
outgoing follows only. Counts are always present (including `0` when the
profile row is missing). Older builds that ignore unknown keys keep working.

## Referral rewards removed (v1.29.0)

Quests are unchanged and still pay out. Only the referral reward (the recruit/welcome payout for bringing in new accounts) has been turned off fleet-wide — referral bounties are too easy to farm with unlimited accounts. If the app surfaces referral earnings, expect those payouts to be zero; invite sharing itself still works.
