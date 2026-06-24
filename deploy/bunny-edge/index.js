/**
 * Reference Bunny Edge Scripting handler for Mirage edge-offload uploads.
 *
 * This is OPTIONAL and OPERATOR-DEPLOYED. It is NOT part of the node and never
 * runs on the node. It lets a `bunny_edge` deployment intercept the uniform
 * `POST /api/upload_media` path AT THE BUNNY EDGE so upload bytes never reach the
 * origin node. The client contract is unchanged: clients still just POST a
 * multipart `kind` + `file` to `/api/upload_media` and get back `{url, asset_id,
 * kind}`.
 *
 * What it does on an upload:
 *   1. (Recommended) run an edge upload-safety scan (e.g. Bunny Shield) BEFORE
 *      the origin would ever see the bytes. A node not fronted by such an edge
 *      has no scanning — see docs/guides/media_providers.md.
 *   2. Store the bytes: images -> Bunny Storage; video -> Bunny Stream.
 *   3. Register the image with the node for garbage collection via the HMAC-signed
 *      callback POST /api/media_edge_register (keyed by BUNNY_EDGE_CALLBACK_SECRET).
 *   4. Return `{url, asset_id, kind}` to the client.
 *
 * Everything else (any non-upload path) is passed straight through to the origin.
 *
 * Configure these as Edge Script environment variables (mirror of the node's
 * secrets.env, plus the origin host):
 *   ORIGIN_HOST              e.g. mirage.talk
 *   BUNNY_STORAGE_ZONE
 *   BUNNY_STORAGE_ACCESS_KEY
 *   BUNNY_STORAGE_HOST       e.g. storage.bunnycdn.com
 *   BUNNY_PULL_ZONE_HOST     e.g. myzone.b-cdn.net
 *   BUNNY_STREAM_LIBRARY_ID
 *   BUNNY_STREAM_API_KEY
 *   BUNNY_STREAM_CDN_HOST    e.g. vz-xxxxxxxx.b-cdn.net
 *   BUNNY_EDGE_CALLBACK_SECRET   (same value as the node)
 *
 * This file is intentionally dependency-free (standard fetch + Web Crypto) and is
 * a faithful mirror of web/backend/media/bunny.py so the two stay in sync.
 */

const env = (k, d = "") => (globalThis.process?.env?.[k] ?? d);

function hex(buf) {
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function hmacSha256Hex(secret, bodyBytes) {
    const key = await crypto.subtle.importKey(
        "raw",
        new TextEncoder().encode(secret),
        { name: "HMAC", hash: "SHA-256" },
        false,
        ["sign"]
    );
    return hex(await crypto.subtle.sign("HMAC", key, bodyBytes));
}

// Magic-byte sniff mirroring web/backend/media/base.py:sniff()
function sniff(bytes) {
    const b = bytes;
    if (b.length < 12) return [null, null];
    const eq = (off, sig) => sig.every((c, i) => b[off + i] === c);
    const ascii = (s) => [...s].map((c) => c.charCodeAt(0));
    if (eq(0, [0xff, 0xd8, 0xff])) return ["image", ".jpg"];
    if (eq(0, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return ["image", ".png"];
    if (eq(0, ascii("GIF87a")) || eq(0, ascii("GIF89a"))) return ["image", ".gif"];
    if (eq(0, ascii("BM"))) return ["image", ".bmp"];
    if (eq(0, ascii("RIFF")) && eq(8, ascii("WEBP"))) return ["image", ".webp"];
    if (eq(4, ascii("ftyp"))) {
        const brand = String.fromCharCode(b[8], b[9], b[10], b[11]);
        if (["avif", "avis", "heic", "heix", "mif1"].includes(brand)) return ["image", ".avif"];
        if (brand === "qt  ") return ["video", ".mov"];
        return ["video", ".mp4"];
    }
    if (eq(0, [0x1a, 0x45, 0xdf, 0xa3])) return ["video", ".webm"];
    if (eq(0, ascii("OggS"))) return ["video", ".ogv"];
    return [null, null];
}

function uuidHex() {
    return crypto.randomUUID().replace(/-/g, "");
}

function ym() {
    const d = new Date();
    return `${d.getUTCFullYear()}/${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function jsonResponse(obj, status = 200) {
    return new Response(JSON.stringify(obj), {
        status,
        headers: { "Content-Type": "application/json" },
    });
}

async function storeImage(bytes, ext, contentType) {
    const rel = `images/${ym()}/${uuidHex()}${ext}`;
    const url = `https://${env("BUNNY_STORAGE_HOST", "storage.bunnycdn.com")}/${env("BUNNY_STORAGE_ZONE")}/${rel}`;
    const resp = await fetch(url, {
        method: "PUT",
        headers: { AccessKey: env("BUNNY_STORAGE_ACCESS_KEY"), "Content-Type": contentType },
        body: bytes,
    });
    if (resp.status !== 200 && resp.status !== 201) throw new Error(`storage_put_${resp.status}`);
    return { url: `https://${env("BUNNY_PULL_ZONE_HOST")}/${rel}`, asset_id: rel, kind: "image" };
}

async function storeVideo(bytes) {
    const base = `https://video.bunnycdn.com/library/${env("BUNNY_STREAM_LIBRARY_ID")}/videos`;
    const headers = { AccessKey: env("BUNNY_STREAM_API_KEY") };
    const create = await fetch(base, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ title: uuidHex() }),
    });
    if (create.status !== 200 && create.status !== 201) throw new Error(`stream_create_${create.status}`);
    const guid = (await create.json()).guid;
    const up = await fetch(`${base}/${guid}`, {
        method: "PUT",
        headers: { ...headers, "Content-Type": "application/octet-stream" },
        body: bytes,
    });
    if (up.status !== 200 && up.status !== 201) throw new Error(`stream_put_${up.status}`);
    return { url: `https://${env("BUNNY_STREAM_CDN_HOST")}/${guid}/playlist.m3u8`, asset_id: guid, kind: "video" };
}

async function registerWithNode(result) {
    // Only images are GC-tracked, matching the node.
    if (result.kind !== "image") return;
    const secret = env("BUNNY_EDGE_CALLBACK_SECRET");
    if (!secret) return;
    const body = new TextEncoder().encode(
        JSON.stringify({ asset_id: result.asset_id, kind: "image", provider: "bunny" })
    );
    const sig = await hmacSha256Hex(secret, body);
    await fetch(`https://${env("ORIGIN_HOST")}/api/media_edge_register`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Mirage-Edge-Signature": sig },
        body,
    });
}

async function handleUpload(request) {
    const form = await request.formData();
    const kind = String(form.get("kind") || "").toLowerCase();
    const file = form.get("file");
    if (kind !== "image" && kind !== "video") return jsonResponse({ error: "media_invalid_kind" }, 400);
    if (!file) return jsonResponse({ error: "media_file_required" }, 400);

    const bytes = new Uint8Array(await file.arrayBuffer());
    const [detected, ext] = sniff(bytes);
    if (!detected || detected !== kind) return jsonResponse({ error: "media_invalid_type" }, 415);

    // 1) Upload-safety scan happens here (e.g. Bunny Shield) before storing.
    //    Reject and return early on a positive hit. Left as an operator hook.

    try {
        const result = kind === "image" ? await storeImage(bytes, ext, file.type || "application/octet-stream") : await storeVideo(bytes);
        await registerWithNode(result);
        return jsonResponse(result);
    } catch (e) {
        return jsonResponse({ error: "media_store_failed", detail: String(e) }, 502);
    }
}

// Bunny Edge Scripting entrypoint.
export default {
    async fetch(request) {
        const url = new URL(request.url);
        if (request.method === "POST" && url.pathname === "/api/upload_media") {
            return handleUpload(request);
        }
        // Pass everything else through to the origin node unchanged.
        return fetch(request);
    },
};
