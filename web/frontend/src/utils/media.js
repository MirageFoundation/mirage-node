// Parse a URL that may be relative (e.g. local provider "/media/..."), using
// the current origin as the base so relative media URLs resolve correctly.
const _parseUrl = (url) => {
    try {
        return new URL(url);
    } catch (_) {
        try {
            const origin = (typeof window !== 'undefined' && window.location && window.location.origin) || 'http://localhost';
            return new URL(url, origin);
        } catch (__) {
            return null;
        }
    }
};

export const isLikelyImageUrl = (url) => {
    try {
        if (!url) return false;
        const u = _parseUrl(url);
        if (!u) return false;
        const host = (u.hostname || '').toLowerCase();
        const path = (u.pathname || '').toLowerCase();
        if (host.endsWith('imagedelivery.net')) return true;
        return ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.avif'].some((ext) => path.endsWith(ext));
    } catch (_) {
        return false;
    }
};

export const isLikelyVideoUrl = (url) => {
    try {
        if (!url) return false;
        const u = _parseUrl(url);
        if (!u) return false;
        const host = (u.hostname || '').toLowerCase();
        const path = (u.pathname || '').toLowerCase();
        const isStream = host.endsWith('cloudflarestream.com') || host.endsWith('videodelivery.net');
        const isRedgifsWatch = host.endsWith('redgifs.com') && path.startsWith('/watch/');
        const isVidExt = ['.mp4', '.webm', '.ogv', '.mov', '.mkv', '.gifv', '.m3u8'].some((ext) => path.endsWith(ext));
        // YouTube video URLs
        const isYoutube = (host === 'www.youtube.com' || host === 'youtube.com' || host === 'm.youtube.com' || host === 'youtu.be' || host === 'www.youtu.be');
        const isRumble = (host === 'rumble.com' || host === 'www.rumble.com');
        return isStream || isRedgifsWatch || isVidExt || isYoutube || isRumble;
    } catch (_) {
        return false;
    }
};

const _safeFilenamePart = (value) => {
    const cleaned = String(value || '').replace(/[^a-z0-9._-]+/gi, '-').replace(/^-+|-+$/g, '');
    return cleaned || 'media';
};

const _extensionFromPath = (path) => {
    const match = String(path || '').match(/\.(png|jpe?g|gif|webp|bmp|avif|mp4|webm|ogv|mov|mkv|gifv)$/i);
    if (!match) return '';
    return match[0].toLowerCase() === '.gifv' ? '.mp4' : match[0].toLowerCase();
};

const _filenameFromUrl = (u, kind, extOverride = '') => {
    const parts = (u.pathname || '').split('/').filter(Boolean);
    const last = parts.length ? parts[parts.length - 1] : '';
    const decodedLast = last;
    const existingExt = _extensionFromPath(decodedLast);
    if (existingExt) return _safeFilenamePart(decodedLast.replace(/\.gifv$/i, '.mp4'));

    const ext = extOverride || '';
    const slug = parts.length ? parts[parts.length - 1] : 'media';
    return `mirage-${kind || 'media'}-${_safeFilenamePart(slug)}${ext}`;
};

// Map a file extension to a short format tag used in download labels/filenames.
// Only returns values we are willing to show in the UI (e.g. "MP4").
const _formatFromExt = (ext) => {
    const e = String(ext || '').toLowerCase();
    if (e === '.mp4' || e === 'mp4') return 'mp4';
    if (e === '.mov' || e === 'mov') return 'mov';
    if (e === '.webm' || e === 'webm') return 'webm';
    if (e === '.ogv' || e === 'ogv') return 'ogv';
    return null;
};

// Mirror web/backend/media/base.py sniff() for video containers — used to pick
// the right extension for Bunny `/original` downloads (octet-stream, no filename).
const _sniffVideoExtFromBytes = (buf) => {
    if (!buf || buf.byteLength < 12) return '';
    const head = new Uint8Array(buf);
    if (head[4] === 0x66 && head[5] === 0x74 && head[6] === 0x79 && head[7] === 0x70) {
        const brand = String.fromCharCode(head[8], head[9], head[10], head[11]);
        if (brand === 'qt  ') return '.mov';
        return '.mp4';
    }
    if (head[0] === 0x1a && head[1] === 0x45 && head[2] === 0xdf && head[3] === 0xa3) return '.webm';
    if (head[0] === 0x4f && head[1] === 0x67 && head[2] === 0x67 && head[3] === 0x53) return '.ogv';
    return '';
};

const _clickDownloadLink = (href, filename, { sameOriginBlob = false } = {}) => {
    const a = document.createElement('a');
    a.href = href;
    if (filename) a.download = filename;
    // blob: URLs honor `download`; cross-origin http(s) ignore it (browser uses the
    // path basename — hence Bunny saving as "original" with no extension).
    if (!sameOriginBlob) {
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
    }
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
};

const _downloadViaBlob = (blob, filename) => {
    const objectUrl = window.URL.createObjectURL(blob);
    console.debug('[media-download] blob save', filename, blob.type, blob.size);
    _clickDownloadLink(objectUrl, filename, { sameOriginBlob: true });
    setTimeout(() => {
        try { window.URL.revokeObjectURL(objectUrl); } catch (_) { /* noop */ }
    }, 2000);
};

const _isCrossOrigin = (href) => {
    try {
        return new URL(href, window.location.href).origin !== window.location.origin;
    } catch (_) {
        return true;
    }
};

export const getMediaDownloadInfo = (rawUrl, kind = 'media') => {
    if (!rawUrl) return null;
    const resolved = normalizeRedgifsToMp4(rawUrl);
    const u = _parseUrl(resolved);
    if (!u) return null;

    const scheme = u.protocol.toLowerCase();
    if (scheme !== 'http:' && scheme !== 'https:') return null;

    const host = (u.hostname || '').toLowerCase();
    const path = (u.pathname || '').toLowerCase();
    const isYoutube = (
        host === 'www.youtube.com' ||
        host === 'youtube.com' ||
        host === 'm.youtube.com' ||
        host === 'youtu.be' ||
        host === 'www.youtu.be'
    );
    if (isYoutube) return null;

    const isCloudflareStream = host === 'iframe.cloudflarestream.com' ||
        host.endsWith('cloudflarestream.com') ||
        host.endsWith('videodelivery.net');
    if (isCloudflareStream) {
        const videoUid = (u.pathname || '').split('/').filter(Boolean)[0];
        if (!videoUid) return null;
        const href = `https://videodelivery.net/${videoUid}/downloads/default.mp4`;
        return {
            href,
            filename: `mirage-video-${_safeFilenamePart(videoUid)}.mp4`,
            format: 'mp4',
        };
    }

    // Bunny Stream HLS → original upload. play_{N}p.mp4 only exists when the
    // library has MP4 Fallback enabled (ours does not — those URLs 404).
    // Original may be mp4/mov/webm — extension is sniffed on download click.
    const bunnyPlaylistMatch = path.match(/^\/([^/]+)\/playlist\.m3u8$/);
    if (bunnyPlaylistMatch) {
        const videoId = bunnyPlaylistMatch[1];
        const href = new URL(u.toString());
        href.pathname = `/${videoId}/original`;
        href.search = '';
        console.debug('[media-download] bunny playlist → original', videoId);
        return {
            href: href.toString(),
            filename: `mirage-video-${_safeFilenamePart(videoId)}`,
            format: null,
            sniffExt: true,
        };
    }

    if (path.endsWith('.m3u8')) return null;

    if (path.endsWith('.gifv')) {
        const mp4Url = new URL(u.toString());
        mp4Url.pathname = mp4Url.pathname.replace(/\.gifv$/i, '.mp4');
        return {
            href: mp4Url.toString(),
            filename: _filenameFromUrl(mp4Url, 'video', '.mp4'),
            format: 'mp4',
        };
    }

    const pathExt = _extensionFromPath(path);
    const filenameExt = kind === 'image' && host.endsWith('imagedelivery.net') ? '.jpg' : '';
    return {
        href: u.toString(),
        filename: _filenameFromUrl(u, kind, filenameExt),
        format: _formatFromExt(pathExt),
    };
};

// Classify a media URL for download labeling/handling.
const _mediaKind = (url) => (isLikelyVideoUrl(url) ? 'video' : (isLikelyImageUrl(url) ? 'image' : 'media'));

// Resolve a post's media URL(s) into a list of downloadable entries. Media with
// no direct download (YouTube, HLS manifests, etc) is skipped. Each entry is the
// `getMediaDownloadInfo` result plus the detected `kind`.
export const getDownloadableMedia = (urls) => {
    const list = Array.isArray(urls) ? urls : (urls ? [urls] : []);
    const out = [];
    for (const url of list) {
        const kind = _mediaKind(url);
        const info = getMediaDownloadInfo(url, kind);
        if (info) out.push({ ...info, kind });
    }
    return out;
};

// Human label for a download menu row. Appends an index when a post has more
// than one downloadable item so each row is distinguishable. Appends " (MP4)"
// only when format is known to be mp4 — never guess for Bunny originals.
export const mediaDownloadLabel = (kind, index, total, format = null) => {
    let base = kind === 'video' ? 'Download video' : kind === 'image' ? 'Download image' : 'Download media';
    if (kind === 'video' && format === 'mp4') base = `${base} (MP4)`;
    return total > 1 ? `${base} ${index + 1}` : base;
};

// Trigger a browser download for a resolved `getMediaDownloadInfo` entry.
// Cross-origin URLs ignore the `download` attribute (Bunny would save as the
// path basename "original" with no extension), so we fetch as a blob and save
// via a same-origin object URL. When sniffExt is set, read the first bytes of
// that blob to pick .mp4/.mov/.webm/.ogv for the filename.
export const triggerMediaDownload = (info) => {
    if (!info || !info.href || typeof document === 'undefined') return;
    console.debug('[media-download] trigger', info.href, info.filename, info.format, info.sniffExt);

    const useBlob = info.sniffExt || (info.filename && _isCrossOrigin(info.href));
    if (!useBlob) {
        _clickDownloadLink(info.href, info.filename);
        return;
    }

    fetch(info.href)
        .then((res) => {
            if (!res.ok) throw new Error(`download HTTP ${res.status}`);
            return res.blob();
        })
        .then(async (blob) => {
            let filename = info.filename || 'mirage-media';
            if (info.sniffExt) {
                const buf = await blob.slice(0, 32).arrayBuffer();
                const ext = _sniffVideoExtFromBytes(buf);
                const format = _formatFromExt(ext);
                const base = String(filename).replace(/\.(mp4|mov|webm|ogv)$/i, '');
                filename = `${base}${ext || ''}`;
                console.debug('[media-download] sniffed', { ext, format, filename, size: blob.size });
            }
            _downloadViaBlob(blob, filename);
        })
        .catch((err) => {
            console.error('[media-download] blob download failed', err);
            throw err;
        });
};

// Ephemeral client-side video posters. Maps a freshly-uploaded video URL to a
// local object-URL poster captured from the source file, so the composer can
// show a preview instantly instead of waiting for the provider to transcode and
// generate a server-side thumbnail (Bunny Stream 404s its thumbnail until then).
// In-memory only; lost on reload — by which point the server thumbnail exists.
const _localVideoPosters = new Map();

export const registerLocalVideoPoster = (videoUrl, posterUrl) => {
    if (videoUrl && posterUrl) _localVideoPosters.set(videoUrl, posterUrl);
};

// Capture a poster frame from a local video File/Blob and return an object URL
// for a JPEG, or null if the browser can't decode the file. Uses a short safety
// timeout so a problematic file never hangs the upload flow.
export const captureVideoPoster = (file) =>
    new Promise((resolve) => {
        let settled = false;
        let srcUrl = null;
        const video = document.createElement('video');
        const finish = (result) => {
            if (settled) return;
            settled = true;
            try { if (srcUrl) window.URL.revokeObjectURL(srcUrl); } catch (_) { }
            resolve(result);
        };
        const grab = () => {
            try {
                const w = video.videoWidth;
                const h = video.videoHeight;
                if (!w || !h) { finish(null); return; }
                const canvas = document.createElement('canvas');
                canvas.width = w;
                canvas.height = h;
                const ctx = canvas.getContext('2d');
                if (!ctx) { finish(null); return; }
                ctx.drawImage(video, 0, 0, w, h);
                canvas.toBlob(
                    (blob) => finish(blob ? window.URL.createObjectURL(blob) : null),
                    'image/jpeg',
                    0.85,
                );
            } catch (_) {
                finish(null);
            }
        };
        try {
            video.muted = true;
            video.preload = 'auto';
            video.playsInline = true;
            video.onloadeddata = () => {
                video.onseeked = () => { video.onseeked = null; grab(); };
                // Nudge past 0 to dodge an all-black first frame.
                try { video.currentTime = Math.min(0.1, (video.duration || 1) / 2); } catch (_) { grab(); }
            };
            video.onerror = () => finish(null);
            setTimeout(() => finish(null), 8000);
            srcUrl = window.URL.createObjectURL(file);
            video.src = srcUrl;
        } catch (_) {
            finish(null);
        }
    });

// Build a poster/thumbnail image URL for a hosted (transcoded) video URL.
//   Bunny Stream: https://{host}/{guid}/playlist.m3u8 -> https://{host}/{guid}/thumbnail.jpg
//   Cloudflare:   https://{host}/{uid}/...            -> https://{host}/{uid}/thumbnails/thumbnail.jpg
// Returns null when the URL isn't a recognized hosted-video URL so callers can
// fall back (e.g. to the raw URL).
export const getVideoThumbnailUrl = (rawUrl) => {
    try {
        if (!rawUrl) return null;
        const local = _localVideoPosters.get(rawUrl);
        if (local) return local;
        const u = _parseUrl(rawUrl);
        if (!u) return null;
        const host = (u.hostname || '').toLowerCase();
        const parts = (u.pathname || '').split('/').filter(Boolean);
        const uid = parts[0];
        if (!uid) return null;
        // Bunny Stream serves the thumbnail at /{guid}/thumbnail.jpg (no "thumbnails/").
        if (host.endsWith('.b-cdn.net')) {
            return `${u.origin}/${uid}/thumbnail.jpg`;
        }
        const isCloudflareStream = host.endsWith('cloudflarestream.com') || host.endsWith('videodelivery.net');
        if (isCloudflareStream) {
            return `${u.origin}/${uid}/thumbnails/thumbnail.jpg`;
        }
        return null;
    } catch (_) {
        return null;
    }
};

// Photon (WordPress.com CDN) - works with redgifs and other domains wsrv blocks
export const buildPhotonUrl = (src, { w, h } = {}) => {
    try {
        if (!src) return '';
        const srcUrl = new URL(src);
        // Photon format: https://i0.wp.com/{host}/{path}?w=X&h=Y&crop=1
        // crop=1 ensures the image fills the dimensions (like object-fit: cover)
        const photonUrl = new URL(`https://i0.wp.com/${srcUrl.host}${srcUrl.pathname}`);
        if (w) photonUrl.searchParams.set('w', String(w));
        if (h) photonUrl.searchParams.set('h', String(h));
        if (w && h) photonUrl.searchParams.set('crop', '1');
        return photonUrl.toString();
    } catch (_) {
        return src;
    }
};

// wsrv.nl - fallback proxy (blocks some domains like redgifs)
export const buildWsrvUrl = (src, { w, h, fit = 'cover', blur } = {}) => {
    try {
        if (!src) return '';
        const url = new URL('https://wsrv.nl/');
        const params = url.searchParams;
        params.set('url', src);
        if (w) params.set('w', String(w));
        if (h) params.set('h', String(h));
        if (fit) params.set('fit', fit);
        if (typeof blur === 'number') params.set('blur', String(blur));
        return url.toString();
    } catch (_) {
        return src;
    }
};

export const buildBlurredWsrvUrl = (src, opts = {}) => {
    const { blur = 24, ...rest } = opts || {};
    return buildWsrvUrl(src, { ...rest, blur });
};

/**
 * Pick the thumbnail proxy for a remote image.
 *
 * Photon is primary because it serves hosts wsrv blocks (e.g. redgifs), but it
 * drops query strings, so URLs that carry one must go through wsrv instead.
 * YouTube posters are served direct — both proxies rate-limit them.
 *
 * Callers render `src`, swap to `blurSrc` for sensitive tags, and on error can
 * fall back from `photon` to wsrv using `original`.
 *
 * @param {string|null} src
 * @param {{ w?: number, h?: number, blur?: number }} [opts]
 * @returns {{ src: string|null, blurSrc: string|null, original: string|null, proxy: 'none'|'direct'|'photon'|'wsrv' }}
 */
export const buildThumbProxy = (src, { w = 240, h = 240, blur = 18 } = {}) => {
    const original = typeof src === 'string' && src.trim() ? src.trim() : null;
    if (!original) return { src: null, blurSrc: null, original: null, proxy: 'none' };

    if (original.includes('img.youtube.com') || original.includes('i.ytimg.com')) {
        return { src: original, blurSrc: original, original, proxy: 'direct' };
    }
    if (original.includes('?')) {
        return {
            src: buildWsrvUrl(original, { w, h }),
            blurSrc: buildBlurredWsrvUrl(original, { w, h, blur }),
            original,
            proxy: 'wsrv',
        };
    }
    return {
        src: buildPhotonUrl(original, { w, h }),
        blurSrc: buildPhotonUrl(original, { w, h }),
        original,
        proxy: 'photon',
    };
};

/** wsrv fallback used when a Photon thumbnail fails to load. */
export const buildThumbProxyFallback = (original, { w = 240, h = 240, blur = 18 } = {}) => ({
    src: buildWsrvUrl(original, { w, h }),
    blurSrc: buildBlurredWsrvUrl(original, { w, h, blur }),
    original,
    proxy: 'wsrv',
});

const _extractRedgifsId = (u) => {
    try {
        const host = (u.hostname || '').toLowerCase();
        if (!host.includes('redgifs.com')) return null;
        // Already thumbs domain with filename
        const pathParts = (u.pathname || '').split('/').filter(Boolean);
        if (!pathParts.length) return null;
        const last = pathParts[pathParts.length - 1];
        // If last is filename.mp4 or filename.jpg
        const base = last.replace(/\.(mp4|webm|jpg|jpeg|png)$/i, '');
        if (base) return base;
        // Watch/ifr/{id}
        if (pathParts[0] === 'watch' || pathParts[0] === 'ifr') {
            return pathParts[1] ? pathParts[1].split('?')[0] : null;
        }
        return null;
    } catch (_) {
        return null;
    }
};

export const extractRedgifsId = (rawUrl) => {
    try {
        if (!rawUrl) return null;
        const u = new URL(rawUrl);
        return _extractRedgifsId(u);
    } catch (_) {
        return null;
    }
};

/**
 * Extract a Rumble embed id from a watch or embed URL.
 * Watch: https://rumble.com/v70bqqu-some-title.html → v70bqqu
 * Embed: https://rumble.com/embed/v70bqqu/ or https://rumble.com/embed/uXXXX.v70bqqu/
 * @param {string} rawUrl
 * @returns {string|null}
 */
export const extractRumbleId = (rawUrl) => {
    try {
        if (!rawUrl) return null;
        const u = new URL(String(rawUrl).trim());
        const host = (u.hostname || '').toLowerCase();
        if (host !== 'rumble.com' && host !== 'www.rumble.com') return null;
        const parts = (u.pathname || '').split('/').filter(Boolean);
        if (!parts.length) return null;
        if (parts[0] === 'embed') {
            const id = String(parts[1] || '').split('?')[0].replace(/\/+$/, '');
            // Accept vXXXX or publisher.vXXXX embed path segments.
            if (/^(?:[a-z0-9]+\.)?v[a-z0-9]+$/i.test(id)) return id;
            return null;
        }
        // Watch / share pages: /vXXXX-slug.html
        const first = String(parts[0] || '').replace(/\.html?$/i, '');
        const m = first.match(/^(v[a-z0-9]+)/i);
        return m ? m[1] : null;
    } catch (_) {
        return null;
    }
};

/**
 * Build a Rumble iframe embed URL. autoPlay uses Rumble's muted autoplay (=2).
 * @param {string} id
 * @param {boolean=} autoPlay
 */
export const buildRumbleEmbedUrl = (id, autoPlay = false) => {
    const clean = String(id || '').replace(/\/+$/, '');
    if (!clean) return '';
    const base = `https://rumble.com/embed/${clean}/`;
    return autoPlay ? `${base}?autoplay=2` : base;
};

export const rumbleCanonicalWatchUrl = (rawUrl) => {
    try {
        const id = extractRumbleId(rawUrl);
        if (!id) return rawUrl;
        // Prefer the short vXXXX form for watch links when we only have an embed id.
        const videoId = id.includes('.') ? id.split('.').pop() : id;
        return `https://rumble.com/${videoId}.html`;
    } catch (_) {
        return rawUrl;
    }
};

export const redgifsCanonicalWatchUrl = (rawUrl) => {
    try {
        const id = extractRedgifsId(rawUrl);
        if (!id) return rawUrl;
        return `https://www.redgifs.com/watch/${id}`;
    } catch (_) {
        return rawUrl;
    }
};

export const normalizeRedgifsToMp4 = (rawUrl) => {
    try {
        if (!rawUrl) return rawUrl;
        const u = new URL(rawUrl);
        const host = (u.hostname || '').toLowerCase();
        if (!host.includes('redgifs.com')) return rawUrl;
        // If already mp4 with thumbs domain, keep as-is
        if (host.startsWith('thumbs') && u.pathname.toLowerCase().endsWith('.mp4')) return rawUrl;
        const id = _extractRedgifsId(u);
        if (!id) return rawUrl;
        // Use widely accessible mobile variant
        return `https://thumbs4.redgifs.com/${id}-mobile.mp4`;
    } catch (_) {
        return rawUrl;
    }
};

export const redgifsPosterFromUrl = (rawUrl) => {
    try {
        if (!rawUrl) return null;
        const u = new URL(rawUrl);
        const host = (u.hostname || '').toLowerCase();
        if (!host.includes('redgifs.com')) return null;
        const id = _extractRedgifsId(u);
        if (!id) return null;
        // Multiple CDN variants; try in order
        return [
            `https://thumbs4.redgifs.com/${id}-poster.jpg`,
            `https://thumbs4.redgifs.com/${id}-mobile.jpg`,
            `https://thumbs4.redgifs.com/${id}.jpg`,
            `https://thumbs4.redgifs.com/${id}.webp`,
            `https://thumbs2.redgifs.com/${id}-poster.jpg`,
            `https://thumbs2.redgifs.com/${id}-mobile.jpg`,
            `https://thumbs2.redgifs.com/${id}.jpg`,
            `https://thumbs2.redgifs.com/${id}.webp`,
            `https://thumbs.redgifs.com/${id}.jpg`,
            `https://thumbs.redgifs.com/${id}.webp`,
            `https://i.redgifs.com/${id}.jpg`,
            `https://i.redgifs.com/${id}.webp`,
        ];
    } catch (_) {
        return null;
    }
};

export const redgifsIframeUrl = (rawUrl) => {
    try {
        if (!rawUrl) return null;
        const u = new URL(rawUrl);
        const id = _extractRedgifsId(u);
        if (!id) return null;
        return `https://www.redgifs.com/ifr/${id}`;
    } catch (_) {
        return null;
    }
};
