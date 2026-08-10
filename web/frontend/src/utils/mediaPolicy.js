/**
 * Central media allowlist / classification.
 *
 * Remote thumbnails are routed through the Photon/wsrv image proxies (see
 * buildThumbProxy in media.js), which also gives us their upstream abuse
 * filtering. Classification here rejects structurally unsafe URLs and labels
 * providers for logging.
 */

/** @typedef {'same-origin'|'mirage-cdn'|'dicebear'|'giphy'|'youtube'|'redgifs'|'rumble'|'cloudflare-stream'|'image-proxy'|'unknown'|'invalid'} MediaProvider */

const EXACT_HOSTS = new Map([
    ['api.dicebear.com', 'dicebear'],
    ['api.giphy.com', 'giphy'],
    ['i.giphy.com', 'giphy'],
    ['media.giphy.com', 'giphy'],
    ['media0.giphy.com', 'giphy'],
    ['media1.giphy.com', 'giphy'],
    ['media2.giphy.com', 'giphy'],
    ['media3.giphy.com', 'giphy'],
    ['media4.giphy.com', 'giphy'],
    ['www.youtube.com', 'youtube'],
    ['youtube.com', 'youtube'],
    ['youtu.be', 'youtube'],
    ['img.youtube.com', 'youtube'],
    ['i.ytimg.com', 'youtube'],
    ['www.redgifs.com', 'redgifs'],
    ['redgifs.com', 'redgifs'],
    ['i.redgifs.com', 'redgifs'],
    ['thumbs.redgifs.com', 'redgifs'],
    ['thumbs2.redgifs.com', 'redgifs'],
    ['thumbs4.redgifs.com', 'redgifs'],
    ['rumble.com', 'rumble'],
    ['www.rumble.com', 'rumble'],
    ['iframe.cloudflarestream.com', 'cloudflare-stream'],
    ['videodelivery.net', 'cloudflare-stream'],
    ['mirage-img.b-cdn.net', 'mirage-cdn'],
    ['wsrv.nl', 'image-proxy'],
    ['i0.wp.com', 'image-proxy'],
    ['i1.wp.com', 'image-proxy'],
    ['i2.wp.com', 'image-proxy'],
    ['i3.wp.com', 'image-proxy'],
]);

const SUFFIX_HOSTS = [
    ['.giphy.com', 'giphy'],
    ['.cloudflarestream.com', 'cloudflare-stream'],
    ['.imagedelivery.net', 'mirage-cdn'],
    ['.b-cdn.net', 'mirage-cdn'],
    ['.redgifs.com', 'redgifs'],
];

/**
 * @param {string} raw
 * @returns {{ ok: boolean, url?: URL, hostname?: string, provider: MediaProvider, reason: string, autoLoad: boolean }}
 */
export function classifyMediaUrl(raw) {
    if (raw == null || typeof raw !== 'string' || !raw.trim()) {
        return { ok: false, provider: 'invalid', reason: 'empty', autoLoad: false };
    }
    const trimmed = raw.trim();
    if ([...trimmed].some((ch) => {
        const code = ch.charCodeAt(0);
        return code <= 0x1f || code === 0x7f;
    })) {
        return { ok: false, provider: 'invalid', reason: 'control-chars', autoLoad: false };
    }

    let url;
    try {
        // Resolve relative URLs against current origin when in browser.
        const base = (typeof window !== 'undefined' && window.location && window.location.origin)
            ? window.location.origin
            : 'http://localhost';
        url = new URL(trimmed, base);
    } catch (_) {
        return { ok: false, provider: 'invalid', reason: 'parse-error', autoLoad: false };
    }

    const scheme = url.protocol.replace(':', '').toLowerCase();
    if (scheme !== 'https' && scheme !== 'http' && scheme !== 'blob' && scheme !== 'data') {
        return { ok: false, provider: 'invalid', reason: `scheme:${scheme}`, autoLoad: false };
    }
    if (url.username || url.password) {
        return { ok: false, provider: 'invalid', reason: 'credentials', autoLoad: false };
    }

    if (scheme === 'blob' || scheme === 'data') {
        return { ok: true, url, hostname: '', provider: 'same-origin', reason: scheme, autoLoad: true };
    }

    const hostname = String(url.hostname || '').toLowerCase();
    if (!hostname) {
        return { ok: false, provider: 'invalid', reason: 'no-host', autoLoad: false };
    }
    if (typeof window !== 'undefined' && window.location) {
        const originHost = String(window.location.hostname || '').toLowerCase();
        if (hostname === originHost || hostname === 'localhost' || hostname === '127.0.0.1') {
            logDecision(hostname, 'same-origin', 'origin-match', true);
            return { ok: true, url, hostname, provider: 'same-origin', reason: 'origin-match', autoLoad: true };
        }
    }

    if (EXACT_HOSTS.has(hostname)) {
        const provider = EXACT_HOSTS.get(hostname);
        logDecision(hostname, provider, 'exact', true);
        return { ok: true, url, hostname, provider, reason: 'exact', autoLoad: true };
    }

    for (const [suffix, provider] of SUFFIX_HOSTS) {
        if (hostname.endsWith(suffix) && hostname.length > suffix.length) {
            // Reject deceptive prefixes like "evil-youtube.com" via suffix that includes leading dot.
            logDecision(hostname, provider, `suffix:${suffix}`, true);
            return { ok: true, url, hostname, provider, reason: `suffix:${suffix}`, autoLoad: true };
        }
    }

    logDecision(hostname, 'unknown', 'not-allowlisted', false);
    return { ok: true, url, hostname, provider: 'unknown', reason: 'not-allowlisted', autoLoad: false };
}

/**
 * @param {string} hostname
 * @param {string} provider
 * @param {string} reason
 * @param {boolean} autoLoad
 */
function logDecision(hostname, provider, reason, autoLoad) {
    try {
        console.debug('[MediaPolicy]', { hostname, provider, reason, autoLoad });
    } catch (_) { /* noop */ }
}

export const MEDIA_POLICY = {
    EXACT_HOSTS,
    SUFFIX_HOSTS,
};
