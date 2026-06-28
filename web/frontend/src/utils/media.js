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
        return isStream || isRedgifsWatch || isVidExt || isYoutube;
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
        };
    }

    const bunnyPlaylistMatch = path.match(/^\/([^/]+)\/playlist\.m3u8$/);
    if (bunnyPlaylistMatch) {
        const videoId = bunnyPlaylistMatch[1];
        const href = new URL(u.toString());
        href.pathname = `/${videoId}/play_1080p.mp4`;
        href.search = '';
        return {
            href: href.toString(),
            filename: `mirage-video-${_safeFilenamePart(videoId)}.mp4`,
        };
    }

    if (path.endsWith('.m3u8')) return null;

    if (path.endsWith('.gifv')) {
        const mp4Url = new URL(u.toString());
        mp4Url.pathname = mp4Url.pathname.replace(/\.gifv$/i, '.mp4');
        return {
            href: mp4Url.toString(),
            filename: _filenameFromUrl(mp4Url, 'video', '.mp4'),
        };
    }

    const filenameExt = kind === 'image' && host.endsWith('imagedelivery.net') ? '.jpg' : '';
    return {
        href: u.toString(),
        filename: _filenameFromUrl(u, kind, filenameExt),
    };
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
