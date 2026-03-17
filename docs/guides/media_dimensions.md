## Media Dimensions (media_meta)

This document explains how Mirage now provides media dimensions for better layout
stability, especially on mobile.

### What is media_meta?

Every post has a `media` array. The backend now returns a parallel `media_meta`
array with the same length. Each entry is either:

- `{ "w": <int>, "h": <int> }` when dimensions are known
- `{}` when dimensions are unknown

Example response:

```
{
  "media": [
    "https://videodelivery.net/abc123/manifest/video.m3u8",
    "https://example.com/image.jpg"
  ],
  "media_meta": [
    { "w": 1920, "h": 1080 },
    { "w": 1200, "h": 800 }
  ]
}
```

### How dimensions are detected

The indexer probes media at ingest time:

- **Cloudflare Stream**: loads the generated thumbnail and reads image size
- **Direct images**: probes the image directly
- **YouTube**: standard videos use 16:9 (1280x720); Shorts use 9:16 (1080x1920)
- **Redgifs**: reads `og:video:width` / `og:video:height` from the page HTML
- **Uploads via Mirage**: `?w=X&h=Y` is appended to the URL during upload

If a probe fails or times out, the entry stays `{}`.

### Sanitization and limits

All dimensions are sanitized as integers and clamped to a safe range:

- minimum: 1
- maximum: 10,000

Anything outside this range is ignored and stored as `{}`.

### How the mobile app should use it

Use `media_meta[i]` to set the initial aspect ratio of media rendering. If the
entry is `{}`, fall back to your existing default behavior (e.g. 16:9 placeholder
or auto sizing after metadata loads).

### Notes

- `media_meta` is populated for **new posts going forward**. Older posts may have
  `{}` entries until they are reindexed or edited.
- Agent edits may replace `media`. In that case `media_meta` is derived only from
  URL query params (e.g. `?w=1920&h=1080`).
