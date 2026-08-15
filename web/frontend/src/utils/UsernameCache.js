import Api from './api';
import { onSessionReset } from './sessionLifecycle';

// Shared username cache (address -> username), persisted for 24h.
const CACHE_KEY = 'usernames_cache_v1';
const TTL_MS = 86400000; // 24 hours

let cacheLoaded = false;
let cacheMap = {}; // keys: lowercase address, value: username string
let cacheTimestamp = 0;

// Sign-out wipes the localStorage copy, so the in-memory map has to be dropped
// too or loadCache() keeps serving it without ever re-reading.
onSessionReset(({ reason }) => {
    cacheLoaded = false;
    cacheMap = {};
    cacheTimestamp = 0;
    try { console.debug('[UsernameCache] cleared on session reset', { reason }); } catch (_) { /* noop */ }
});

function loadCache() {
    if (cacheLoaded) return;
    cacheLoaded = true;
    try {
        if (typeof window === 'undefined' || !window.localStorage) return;
        const raw = window.localStorage.getItem(CACHE_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return;
        const { map, timestamp } = parsed;
        if (!map || typeof map !== 'object' || !timestamp) {
            window.localStorage.removeItem(CACHE_KEY);
            return;
        }
        if (Date.now() - Number(timestamp) > TTL_MS) {
            window.localStorage.removeItem(CACHE_KEY);
            return;
        }
        const lowerMap = Object.entries(map).reduce((acc, [k, v]) => {
            const key = String(k || '').toLowerCase();
            if (!key) return acc;
            acc[key] = v;
            return acc;
        }, {});
        cacheMap = lowerMap;
        cacheTimestamp = Number(timestamp) || Date.now();
    } catch {
        // ignore
    }
}

function saveCache() {
    try {
        if (typeof window === 'undefined' || !window.localStorage) return;
        const payload = {
            map: cacheMap,
            timestamp: cacheTimestamp || Date.now(),
        };
        window.localStorage.setItem(CACHE_KEY, JSON.stringify(payload));
    } catch {
        // ignore
    }
}

/**
 * Resolve usernames for a list of addresses with shared 24h cache.
 *
 * @param {string[]} addresses - list of addresses (any casing)
 * @param {{ timeoutMs?: number }} opts - optional timeout config
 * @returns {Promise<Record<string, string>>} - map from lowercase address -> username
 */
export async function resolveUsernames(addresses, opts = {}) {
    loadCache();

    const timeoutMs = typeof opts.timeoutMs === 'number' ? opts.timeoutMs : 8000;

    const normalized = Array.from(
        new Set(
            (addresses || [])
                .map((a) => String(a || '').trim().toLowerCase())
                .filter(Boolean)
        )
    );

    if (normalized.length === 0) {
        return {};
    }

    const unresolved = normalized.filter((addr) => !cacheMap[addr]);
    if (unresolved.length > 0) {
        try {
            const res = await Api.post(
                'get_username_from_address',
                { addresses: unresolved },
                { timeoutMs }
            );
            if (res && res.map && typeof res.map === 'object') {
                Object.entries(res.map).forEach(([k, v]) => {
                    const key = String(k || '').toLowerCase();
                    if (!key) return;
                    cacheMap[key] = v;
                });
                cacheTimestamp = Date.now();
                saveCache();
            }
        } catch {
            // Network failure: leave cache as-is, return best-effort below.
        }
    }

    const out = {};
    normalized.forEach((addr) => {
        out[addr] = cacheMap[addr] || '';
    });
    return out;
}

