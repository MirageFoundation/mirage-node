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

The old `POST /api/get_upload_url` (the Cloudflare browser-direct-upload shape) is a **deprecated legacy shim that will be removed after 2026-08**. It only exists so old app builds keep working during the storage cutover. New mobile builds must use `/api/upload_media`.

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
https://mirage-img.b-cdn.net/stickers/<pack>/<NN>.png
```

for example `https://mirage-img.b-cdn.net/stickers/meme/01.png`. If your app embeds the sticker list, mirror this new base path and drop any hard-coded `imagedelivery.net` URLs.
