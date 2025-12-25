export const isLikelyImageUrl = (url) => {
    try {
        if (!url) return false;
        const u = new URL(url);
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
        const u = new URL(url);
        const host = (u.hostname || '').toLowerCase();
        const path = (u.pathname || '').toLowerCase();
        const isStream = host.endsWith('cloudflarestream.com') || host.endsWith('videodelivery.net');
        const isRedgifsWatch = host.endsWith('redgifs.com') && path.startsWith('/watch/');
        const isVidExt = ['.mp4', '.webm', '.ogv', '.mov', '.mkv', '.gifv'].some((ext) => path.endsWith(ext));
        // YouTube video URLs
        const isYoutube = (host === 'www.youtube.com' || host === 'youtube.com' || host === 'm.youtube.com' || host === 'youtu.be' || host === 'www.youtu.be');
        return isStream || isRedgifsWatch || isVidExt || isYoutube;
    } catch (_) {
        return false;
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
