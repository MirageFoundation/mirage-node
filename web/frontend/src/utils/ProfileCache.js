import Api from './api';
import { onSessionReset } from './sessionLifecycle';

const CACHE_KEY = 'profile_followed_cache';
const NO_CACHE_UNTIL_KEY = 'profile_no_cache_until';
const CACHE_TTL_MS = 86400000; // 24 hours
const NO_CACHE_WINDOW_MS = 30000; // 30 seconds after follow/unfollow

const pendingRequests = new Map();

// Keyed by viewer address, so a request still pending at sign-out would resolve
// into the next account's session.
onSessionReset(({ reason }) => {
    pendingRequests.clear();
    try { console.debug('[ProfileCache] pending cleared on session reset', { reason }); } catch (_) { /* noop */ }
});

function isInNoCacheWindow() {
    try {
        const until = localStorage.getItem(NO_CACHE_UNTIL_KEY);
        if (!until) return false;
        return Date.now() < Number(until);
    } catch (_) {
        return false;
    }
}

function startNoCacheWindow() {
    try {
        localStorage.removeItem(CACHE_KEY); // Clear cache immediately
        localStorage.setItem(NO_CACHE_UNTIL_KEY, String(Date.now() + NO_CACHE_WINDOW_MS));
    } catch (_) { }
}

function loadFromStorage() {
    try {
        const raw = localStorage.getItem(CACHE_KEY);
        if (!raw) return null;
        const data = JSON.parse(raw);
        if (!data || !data.address || !data.timestamp) return null;
        // Check if expired
        if (Date.now() - data.timestamp > CACHE_TTL_MS) {
            localStorage.removeItem(CACHE_KEY);
            return null;
        }
        return data;
    } catch (_) {
        return null;
    }
}

function saveToStorage(address, profile) {
    try {
        localStorage.setItem(CACHE_KEY, JSON.stringify({
            address: address.toLowerCase(),
            timestamp: Date.now(),
            profile: profile
        }));
    } catch (_) { }
}

function getCachedData(address) {
    const cached = loadFromStorage();
    if (cached && cached.address === address.toLowerCase()) {
        return cached.profile;
    }
    return null;
}

export async function fetchProfile(viewerAddress, force = false) {
    const addr = String(viewerAddress || '').trim().toLowerCase();
    if (!addr || addr === 'guest') {
        return null;
    }

    const inNoCacheWindow = isInNoCacheWindow();

    // Return cached data if valid and not in no-cache window
    if (!force && !inNoCacheWindow) {
        const cached = getCachedData(addr);
        if (cached) {
            return cached;
        }
    }

    // If there's already a pending request for this address, reuse it.
    const pending = pendingRequests.get(addr);
    if (pending) {
        return pending;
    }

    // Make the request
    const request = Api.get('get_user_followed', { address: addr })
        .then(data => {
            // Only save to cache if we're outside the no-cache window
            if (!isInNoCacheWindow()) {
                saveToStorage(addr, data);
            }
            return data;
        })
        .catch(e => {
            console.error('[ProfileCache] Failed to fetch followed data:', e);
            throw e;
        })
        .finally(() => {
            pendingRequests.delete(addr);
        });

    pendingRequests.set(addr, request);
    return request;
}

export function getJoinedCommunities() {
    const cached = loadFromStorage();
    if (!cached || !cached.profile) return [];
    const topics = cached.profile.joined_communities || [];
    return topics.map(t => String(t || '').trim()).filter(t => {
        const v = t.toLowerCase();
        return v !== 'all' && v !== 'home' && v !== '';
    });
}

export function getFollowedUsers() {
    const cached = loadFromStorage();
    if (!cached || !cached.profile) return [];
    const users = cached.profile.followed_users || [];
    return users.map(u => String(u || '').trim().toLowerCase()).filter(Boolean);
}

export function invalidateCache() {
    // Clear cached profile data, but intentionally keep the no-cache window flag.
    // This way, callers that just performed follow/unfollow and then manually
    // invalidate the cache will STILL be in the 60s "always refetch" window.
    localStorage.removeItem(CACHE_KEY);
    pendingRequests.clear();
}

export function isCacheValid(addr) {
    const a = String(addr || '').trim().toLowerCase();
    if (!a || a === 'guest') return false;
    const cached = loadFromStorage();
    return cached && cached.address === a;
}

export function updateCacheTopics(topics, address = null) {
    // Don't write to cache during no-cache window
    if (isInNoCacheWindow()) return;

    let cached = loadFromStorage();
    if (!cached || !cached.profile) {
        // Initialize cache if missing
        const addr = address || localStorage.getItem('publicKey') || '';
        if (!addr) return;
        cached = {
            address: addr.toLowerCase(),
            timestamp: Date.now(),
            profile: { joined_communities: [], followed_users: [] }
        };
    }
    cached.profile.joined_communities = topics;
    cached.timestamp = Date.now();
    try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(cached));
    } catch (_) { }
}

export function updateCacheUsers(users, address = null) {
    // Don't write to cache during no-cache window
    if (isInNoCacheWindow()) return;

    let cached = loadFromStorage();
    if (!cached || !cached.profile) {
        // Initialize cache if missing
        const addr = address || localStorage.getItem('publicKey') || '';
        if (!addr) return;
        cached = {
            address: addr.toLowerCase(),
            timestamp: Date.now(),
            profile: { joined_communities: [], followed_users: [] }
        };
    }
    cached.profile.followed_users = users;
    cached.timestamp = Date.now();
    try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(cached));
    } catch (_) { }
}

// Clear cache and don't allow caching for 30s (ensures blockchain propagation)
export function scheduleRefresh(address) {
    startNoCacheWindow();
}

// Seed the profile_followed_cache from the /api/bootstrap response so the
// sidebar's joined communities / followed users render instantly on cold load
// without firing a separate /api/get_user_followed request. Honors the
// no-cache window — if the user just performed a join/leave we keep the
// stale-bypass active and do nothing.
export function seedFromBootstrap(address, data) {
    if (!address || !data || typeof data !== 'object') return;
    if (isInNoCacheWindow()) return;
    const addr = String(address).trim().toLowerCase();
    if (!addr || addr === 'guest') return;
    saveToStorage(addr, {
        joined_communities: Array.isArray(data.joined_communities) ? data.joined_communities : [],
        followed_users: Array.isArray(data.followed_users) ? data.followed_users : [],
    });
}
