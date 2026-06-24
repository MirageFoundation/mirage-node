# Bunny edge-offload (optional, operator-deployed)

This directory holds a **reference** Bunny Edge Scripting handler. It is **not**
part of the node and never runs on the node. It is an optional operator
deployment that intercepts the uniform `POST /api/upload_media` path **at the
Bunny edge**, so upload bytes never reach the origin node.

See `docs/guides/media_providers.md` for the full design. Key points:

- The client contract is unchanged. Clients still POST multipart `kind` + `file`
  to `/api/upload_media` and receive `{url, asset_id, kind}`.
- The edge handler stores images to Bunny Storage and video to Bunny Stream,
  optionally runs an edge upload-safety scan (e.g. Bunny Shield) before storing,
  and registers images with the node for garbage collection via the HMAC-signed
  `POST /api/media_edge_register` callback.
- `index.js` mirrors `web/backend/media/bunny.py`; keep them in sync.

## Deploy

1. Create a Bunny Edge Script and paste `index.js`.
2. Set the Edge Script environment variables listed at the top of `index.js`
   (the same Bunny credentials as the node's `secrets.env`, plus `ORIGIN_HOST`
   and the shared `BUNNY_EDGE_CALLBACK_SECRET`).
3. Route the pull zone that fronts your domain through the Edge Script.
4. On the node, set `BUNNY_EDGE_CALLBACK_SECRET` in `secrets.env` to the same
   value so the registration callback authenticates.

## Without the edge

A node that does not front uploads through this edge simply uses its configured
`MEDIA_PROVIDER` (`local`/`cloudflare`/`bunny`) directly and has **no** edge-based
upload-safety scanning. That is a deliberate, documented property — scanning is an
edge/operator concern, not a node feature.
