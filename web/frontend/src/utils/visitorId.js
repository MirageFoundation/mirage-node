// @ts-check

/**
 * Mirage-owned analytics visitor identity (web side of the identity wire
 * contract). A stable, anonymous, per-browser id that:
 *   - is generated once and persisted in its own localStorage namespace,
 *   - is sent on every backend request via the `X-Mirage-Visitor` header,
 *   - survives login/logout/account-switch (auth cleanup must not touch it),
 *   - is bound to a Mirage address server-side once the user authenticates.
 *
 * The raw id is opaque; the backend salts/hashes it before storage. The same
 * key name and header are used by web and mobile (see the plan's "identity wire
 * contract"); do not invent variants.
 */

export const VISITOR_ID_KEY = 'mirage_analytics_visitor_id';
export const VISITOR_HEADER = 'X-Mirage-Visitor';

const UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'];

function randomId() {
    try {
        if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
            return crypto.randomUUID().replace(/-/g, '');
        }
        if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
            const bytes = new Uint8Array(16);
            crypto.getRandomValues(bytes);
            return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
        }
    } catch (_) { /* fall through */ }
    return (Date.now().toString(16) + Math.random().toString(16).slice(2)).padStart(32, '0').slice(0, 32);
}

/**
 * Get the stable visitor id, generating and persisting one on first use.
 * @returns {string}
 */
export function getVisitorId() {
    try {
        let id = localStorage.getItem(VISITOR_ID_KEY);
        if (id && id.length >= 8) return id;
        id = randomId();
        localStorage.setItem(VISITOR_ID_KEY, id);
        return id;
    } catch (_) {
        // localStorage unavailable (private mode / SSR): a per-session id keeps
        // the header present without persistence.
        return randomId();
    }
}

/**
 * Capture first-touch UTM params from the current URL and report them to the
 * backend (idempotent server-side; first-touch is never overwritten). Sends at
 * most once per page-load and only when UTM params are present.
 */
export function captureFirstTouchAttribution() {
    try {
        const params = new URLSearchParams(window.location.search);
        const utm = {};
        let any = false;
        for (const k of UTM_KEYS) {
            const v = (params.get(k) || '').trim();
            if (v) { utm[k] = v; any = true; }
        }
        const ref = (params.get('ref') || '').trim();
        if (!any && !ref) return;

        const body = {
            visitor_id: getVisitorId(),
            platform: 'web',
            ref,
            ...utm,
        };
        // Fire-and-forget; analytics must never block or break the page.
        const base = (typeof process !== 'undefined' && process.env && process.env.REACT_APP_API_BASE)
            ? String(process.env.REACT_APP_API_BASE).replace(/\/$/, '').replace(/\/api$/, '') + '/api'
            : '/api';
        fetch(base.replace(/\/$/, '') + '/stats/visitor_attribution', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            keepalive: true,
        }).catch(() => { });
    } catch (_) { /* best-effort */ }
}
