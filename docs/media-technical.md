# Media System — Technical Reference

How multi-media posts work end-to-end: upload, submit, store, retrieve, render.

---

## Data Model

Media is a `repeated string` protobuf field on both `MsgPost` and `MsgEdit`. Each entry is an HTTPS URL pointing to an uploaded image or video.

**Proto definitions** (`blockchain/proto/mirage/core/v1/tx.proto`):

```protobuf
message MsgPost {
  // ... envelope fields (1-10) ...
  string  target  = 100;
  string  topic   = 101;
  string  title   = 102;
  string  content = 103;
  string  tag     = 104;
  repeated string media = 105;
}

message MsgEdit {
  // ... envelope fields (1-10) ...
  string  target   = 100;
  string  topic    = 101;
  string  title    = 102;
  string  content  = 103;
  string  tag      = 104;
  string  override = 105;
  repeated string media = 106;  // note: field 106, not 105
}
```

**Key difference**: in `MsgPost`, `media` is field 105. In `MsgEdit`, `override` takes field 105 and `media` is field 106. This matters for canonical encoding.

---

## Validation Rules

Enforced at three layers — chain, backend, and frontend. All three enforce the same rules:

| Rule | Limit |
|------|-------|
| Max items per post | 10 |
| Max URL length | 2048 characters |
| URL scheme | Must start with `https://` |
| Empty array | Valid (no media) |

Chain validation (`blockchain/x/core/module/module.go`):

```go
func validateMsgPostMedia(media []string) error {
    if len(media) > 10 {
        return fmt.Errorf("media exceeds limit: %d > 10", len(media))
    }
    for i, mediaItem := range media {
        if len(mediaItem) > 2048 {
            return fmt.Errorf("media[%d] exceeds length limit: %d > 2048", i, len(mediaItem))
        }
        if !strings.HasPrefix(mediaItem, "https://") {
            return fmt.Errorf("media[%d] must use https://", i)
        }
    }
    return nil
}
```

Backend validation (`web/backend/routes/core.py`) returns 400 with the same error messages. Frontend validates client-side before submission.

---

## Upload Flow

Media is **not** uploaded as part of the post transaction. Uploads happen first, then the resulting URLs go into the `media` array.

### Step 1: Get a direct upload URL

```
POST /api/get_upload_url
Content-Type: application/json

{ "type": "image" }   // or "video"
```

**Image response** (Cloudflare Images):
```json
{
  "uploadURL": "https://upload.imagedelivery.net/...",
  "id": "image-uuid",
  "accountHash": "abc123"
}
```

**Video response** (Cloudflare Stream):
```json
{
  "uploadURL": "https://upload.videodelivery.net/...",
  "provider": "stream",
  "streamCustomer": "customer-code",
  "uid": "video-uuid"
}
```

### Step 2: Upload directly to Cloudflare

**Images**: `POST` the file to `uploadURL` as multipart form data. The final URL is constructed as:
```
https://imagedelivery.net/{accountHash}/{id}/public
```

**Videos**: `POST` the file to `uploadURL` via TUS protocol or multipart. Max duration is 60 seconds (enforced client-side and by Cloudflare). The final URL is:
```
https://videodelivery.net/{uid}/manifest/video.m3u8
```

### Step 3: Submit post with media URLs

The resulting HTTPS URLs go into the `media` array on the create/edit request.

---

## API: Create Post

```
POST /api/core/post
Content-Type: application/json

{
  "pubkey": "<base64 secp256k1 pubkey>",
  "signature": "<base64 signature>",
  "last_block_hash": "<hex>",
  "pow_difficulty": 0,
  "pow": 12345,
  "timestamp": 1700000000000,
  "target": "",
  "topic": "general",
  "title": "My post",
  "content": "Hello world",
  "tag": "",
  "media": [
    "https://imagedelivery.net/abc/img1/public",
    "https://imagedelivery.net/abc/img2/public",
    "https://videodelivery.net/xyz/manifest/video.m3u8"
  ]
}
```

The `media` field is optional. Omit it or pass `[]` for text-only posts.

---

## API: Edit Post

```
POST /api/core/edit
Content-Type: application/json

{
  "pubkey": "<base64 secp256k1 pubkey>",
  "signature": "<base64 signature>",
  "last_block_hash": "<hex>",
  "pow_difficulty": 0,
  "pow": 12345,
  "timestamp": 1700000000000,
  "target": "",
  "topic": "general",
  "title": "My post (edited)",
  "content": "Updated content",
  "tag": "",
  "override": "<64-char txhash of original post>",
  "media": [
    "https://imagedelivery.net/abc/img1/public"
  ]
}
```

On edit, send the **full replacement** media array. The old media is not merged — whatever you send becomes the new media list.

---

## API: Post Response Format

All endpoints that return posts include a `media` field:

```json
{
  "post_id": "a1b2c3...",
  "author": "mirage1...",
  "username": "alice",
  "timestamp": 1700000000,
  "topic": "general",
  "title": "My post",
  "content": "Hello world",
  "tag": "",
  "edited": false,
  "edited_at": 0,
  "thumbnail": "",
  "media": [
    "https://imagedelivery.net/abc/img1/public",
    "https://imagedelivery.net/abc/img2/public"
  ]
}
```

- `media` is always an array of strings (URLs)
- Empty array `[]` for posts with no media
- Pre-v1.12.0 posts will have `media: []`
- Endpoints returning media: home feed, topic feed, user posts, post detail, comment trees, search

---

## Canonical Encoding (for PoW + Signatures)

Media URLs are included in the canonical bytes used for Proof-of-Work mining and signature verification. This is critical — if the canonical encoding doesn't match the backend/chain, the signature will be rejected.

### Format

Canonical bytes are a **custom protobuf-like** binary format:

```
PREFIX = b"mirage.core.v1:" + MSG_NAME + b"\x00"
```

Fields are written in tag order. Each field is: `tag_byte + uvarint(length) + payload` for strings/bytes, or `tag_byte + uvarint(value)` for integers.

**Authority (tag 1) and signature (tag 10) are EXCLUDED** from canonical bytes.

### MsgPost canonical order

```
prefix
tag 2:   envelope_pubkey (bytes)
tag 3:   envelope_block_hash (bytes)
tag 4:   envelope_difficulty (uint64)
tag 5:   envelope_pow (uint64)       // included in signed, excluded from base
tag 6:   envelope_timestamp (uint64)
tag 100: target (string)
tag 101: topic (string)
tag 102: title (string)
tag 103: content (string)
tag 104: tag (string)
tag 105: media[0] (string)           // repeated: one entry per media URL
tag 105: media[1] (string)
tag 105: media[2] (string)
...
```

### MsgEdit canonical order

```
prefix
tag 2:   envelope_pubkey (bytes)
tag 3:   envelope_block_hash (bytes)
tag 4:   envelope_difficulty (uint64)
tag 5:   envelope_pow (uint64)
tag 6:   envelope_timestamp (uint64)
tag 100: target (string)
tag 101: topic (string)
tag 102: title (string)
tag 103: content (string)
tag 104: tag (string)
tag 105: override (string)
tag 106: media[0] (string)           // field 106 for edit, not 105
tag 106: media[1] (string)
...
```

### Repeated field encoding

Each media URL gets its own `tag + length + value` entry. They are **not** packed into a single field. Empty media array = nothing written.

Python reference (`shared/canon.py`):

```python
# MsgPost: media is tag 105
for m in media or []:
    out += _enc_str(105, m)

# MsgEdit: media is tag 106
for m in media or []:
    out += _enc_str(106, m)
```

### Encoding helpers

```python
def uvarint(n: int) -> bytes:
    n = int(n) & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)

def _enc_str(tag: int, s: str) -> bytes:
    b = s.encode("utf-8")
    return bytes([tag & 0xFF]) + uvarint(len(b)) + b
```

### Two-phase signing

1. **Base canonical** (for PoW): everything except `envelope_pow` (tag 5) and `envelope_signature` (tag 10)
2. **Signed canonical** (for signature): base + `envelope_pow` appended. The PoW nonce goes between tag 4 and tag 6.

The signature is `secp256k1_sign(sha256(signed_canonical), private_key)`.

---

## Database Storage

Media is stored as a JSON string array in the `posts.media` column (PostgreSQL `TEXT`). The indexer parses on-chain `MsgPost`/`MsgEdit` events and writes the media array as JSON.

All queries use `COALESCE(p.media, '[]')` so legacy posts without the column return an empty array.

---

## Legacy Compatibility

Pre-v1.12.0 posts embedded media as a URL on the first line of `content`. The web frontend handles this:

1. If `media` array has items, render from `media` (new path)
2. If `media` is empty, check if the first line of `content` is an image/video URL
3. If so, extract it and render it as inline media, removing it from the text content

A mobile client should implement the same fallback for old posts.

---

## Video Streaming

Videos are delivered as HLS streams via Cloudflare Stream. The URL format:

```
https://videodelivery.net/{uid}/manifest/video.m3u8
```

There's also a proxy endpoint for CORS issues:

```
GET /api/stream_proxy/{uid}             -> main manifest
GET /api/stream_proxy/{uid}/{segment}   -> video segments
```

Use the proxy if hitting CORS errors with direct Cloudflare URLs. The proxy strips the `Origin` header.

---

## Quick Reference

| What | Where |
|------|-------|
| Proto definition | `blockchain/proto/mirage/core/v1/tx.proto` |
| Chain validation | `blockchain/x/core/module/module.go` → `validateMsgPostMedia()` |
| Backend validation | `web/backend/routes/core.py` → `/api/core/post` and `/api/core/edit` |
| Canonical encoding | `shared/canon.py` → `canon_base_post()` and `canon_base_edit()` |
| Upload URL endpoint | `web/backend/routes/public.py` → `/api/get_upload_url` |
| DB storage | `posts.media` column (JSON text array) |
| Gallery component | `web/frontend/src/components/MediaGallery.js` |
