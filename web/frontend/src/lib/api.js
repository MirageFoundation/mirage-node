// @ts-check

/**
 * Minimal API client wrapper around fetch with JSON handling and timeouts.
 * IMPORTANT: We default to relative "/api" (Caddy proxy). We NEVER hardcode mirage.vote here.
 * If the local backend is unreachable or misrouted (e.g., HTML returned), we FALL BACK to
 * https://mirage.vote/api for that request only.
 */

/**
 * @returns {string}
 */
function isLocalHost() {
    try {
        const h = (typeof window !== 'undefined' && window.location && window.location.hostname) ? window.location.hostname : '';
        if (!h) return false;
        if (h === 'localhost' || h === '127.0.0.1') return true;
        // Private ranges and raw IPv4
        if (/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.)/.test(h)) return true;
        if (/^\d{1,3}(\.\d{1,3}){3}$/.test(h)) return true;
        return false;
    } catch (_) {
        return false;
    }
}

/**
 * @returns {string}
 */
function getBaseUrl() {
    try {
        // Default to relative /api path (goes through Caddy proxy)
        let base = '/api';
        // Respect explicit env override ONLY when not on localhost-like hosts
        const env = (typeof process !== 'undefined' && process.env && process.env.REACT_APP_API_BASE) ? process.env.REACT_APP_API_BASE : '';
        if (env && !isLocalHost()) {
            base = String(env || '').trim() || '/api';
        }
        // ensure single /api suffix
        if (!/\/?api\/?$/.test(base)) {
            base = base.replace(/\/$/, '') + '/api';
        }
        return base.replace(/\/$/, '');
    } catch (_) {
        return '/api';
    }
}

const API_BASE = getBaseUrl();

/**
 * Build a URL with query params
 * @param {string} path
 * @param {Record<string, any>=} params
 */
function buildUrl(path, params) {
    const p = String(path || '').replace(/^\//, '');
    let url;
    // If API_BASE is absolute (starts with http:// or https://), use URL constructor
    // Otherwise, treat as relative path and use window.location.origin as base
    if (API_BASE.startsWith('http://') || API_BASE.startsWith('https://')) {
        url = new URL(API_BASE + '/' + p);
    } else {
        // Relative path - use current origin
        url = new URL(API_BASE + '/' + p, window.location.origin);
    }
    if (params && typeof params === 'object') {
        Object.entries(params).forEach(([k, v]) => {
            if (v === undefined || v === null) return;
            url.searchParams.set(k, String(v));
        });
    }
    return url.toString();
}

// Removed remote fallback helpers (hard-fail policy)

/**
 * Auto-sync balance: if the API response contains a `balance` field and the
 * request was for the logged-in user's own address, update localStorage and
 * fire the balanceUpdated event so TopBar/MobileHeader stay in sync.
 * @param {Record<string,any>=} params - GET query params
 * @param {any=} body - POST body
 * @param {any} data - parsed response
 */
function maybeSyncBalance(params, body, data) {
    if (!data || typeof data !== 'object' || data.balance === undefined) return;
    try {
        const myAddr = localStorage.getItem('publicKey') || '';
        if (!myAddr) return;
        // Check address from query params (GET) or body (POST)
        const reqAddr = String(
            (params && (params.address || params.owner)) ||
            (body && (body.address || body.owner)) ||
            ''
        );
        if (!reqAddr || reqAddr.toLowerCase() !== myAddr.toLowerCase()) return;
        const bal = Number(data.balance);
        if (!Number.isFinite(bal)) return;
        localStorage.setItem('user_balance', String(Math.max(0, Math.trunc(bal))));
        window.dispatchEvent(new CustomEvent('balanceUpdated', { detail: bal }));
    } catch (_) { }
}

/**
 * Auto-sync inbox count: if the API response contains `new_inbox_items`,
 * persist to localStorage and dispatch an event so TopBar/MobileBottomNav
 * can update the badge (survives component remounts across navigation).
 *
 * Skips the update if the count was explicitly set client-side within the
 * last 5 seconds (e.g. mark-as-read), so a stale server response from a
 * request that was in-flight before the mark can't flash the old count.
 * @param {any} data - parsed response
 */
function maybeSyncInbox(data) {
    if (!data || typeof data !== 'object' || typeof data.new_inbox_items !== 'number') return;
    try {
        const setAt = parseInt(localStorage.getItem('inbox_count_set_at'), 10);
        if (setAt && (Date.now() - setAt) < 5000) return;
        const count = Math.max(0, data.new_inbox_items);
        localStorage.setItem('inbox_count', String(count));
        window.dispatchEvent(new CustomEvent('inboxCount', { detail: count }));
    } catch (_) { }
}

/**
 * @typedef {Object} RequestOptions
 * @property {number=} timeoutMs
 * @property {Record<string,string>=} headers
 */

/**
 * @param {string} path
 * @param {Record<string, any>=} params
 * @param {RequestOptions=} options
 */
async function get(path, params, options) {
    const url = buildUrl(path, params);
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), Math.max(1, Number((options && options.timeoutMs) || 10000)));
    try {
        const resp = await fetch(url, { signal: controller.signal, headers: (options && options.headers) || {} });
        if (resp.ok) {
            const ct = resp.headers.get('content-type') || '';
            // If HTML came back, likely misroute: attempt remote fallback
            if (!ct.includes('text/html')) {
                if (ct.includes('application/json')) {
                    const json = await resp.json();
                    maybeSyncBalance(params, undefined, json);
                    maybeSyncInbox(json);
                    return json;
                }
                return await resp.text();
            }
        }
        let detail = '';
        try { detail = resp && typeof resp.text === 'function' ? await resp.text() : ''; } catch (_) { detail = ''; }
        throw new Error(`HTTP ${resp && typeof resp.status === 'number' ? resp.status : 'ERR'}: ${detail}`);
    } finally {
        clearTimeout(id);
    }
}

/**
 * @param {string} path
 * @param {any} body
 * @param {RequestOptions=} options
 */
async function post(path, body, options) {
    const url = buildUrl(path);
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), Math.max(1, Number((options && options.timeoutMs) || 10000)));
    try {
        const resp = await fetch(url, {
            method: 'POST',
            signal: controller.signal,
            headers: { 'Content-Type': 'application/json', ...(options && options.headers) },
            body: JSON.stringify(body == null ? {} : body),
        });
        if (resp.ok) {
            const ct = resp.headers.get('content-type') || '';
            if (!ct.includes('text/html')) {
                if (ct.includes('application/json')) {
                    const json = await resp.json();
                    maybeSyncBalance(undefined, body, json);
                    maybeSyncInbox(json);
                    return json;
                }
                return await resp.text();
            }
        }
        let detail = '';
        try { detail = resp && typeof resp.text === 'function' ? await resp.text() : ''; } catch (_) { detail = ''; }
        throw new Error(`HTTP ${resp && typeof resp.status === 'number' ? resp.status : 'ERR'}: ${detail}`);
    } finally {
        clearTimeout(id);
    }
}

export const Api = { get, post, buildUrl, API_BASE };

export default Api;


