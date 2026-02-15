import Api from '../lib/api';

const CACHE_KEY = 'profile_followed_cache';
const NO_CACHE_UNTIL_KEY = 'profile_no_cache_until';
const CACHE_TTL_MS = 86400000; // 24 hours
const NO_CACHE_WINDOW_MS = 30000; // 30 seconds after follow/unfollow

let pendingRequest = null;

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

    // If there's already a pending request for the same address, wait for it
    if (pendingRequest) {
        return pendingRequest;
    }

    // Make the request
    pendingRequest = Api.get('get_user_followed', { address: addr })
        .then(data => {
            // Only save to cache if we're outside the no-cache window
            if (!isInNoCacheWindow()) {
                saveToStorage(addr, data);
            }
            pendingRequest = null;
            return data;
        })
        .catch(e => {
            console.error('[ProfileCache] Failed to fetch followed data:', e);
            pendingRequest = null;
            throw e;
        });

    return pendingRequest;
}

export function getFollowedTopics() {
    const cached = loadFromStorage();
    if (!cached || !cached.profile) return [];
    const topics = cached.profile.followed_topics || [];
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
    pendingRequest = null;
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
            profile: { followed_topics: [], followed_users: [], followed_moderators: [] }
        };
    }
    cached.profile.followed_topics = topics;
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
            profile: { followed_topics: [], followed_users: [], followed_moderators: [] }
        };
    }
    cached.profile.followed_users = users;
    cached.timestamp = Date.now();
    try {
        localStorage.setItem(CACHE_KEY, JSON.stringify(cached));
    } catch (_) { }
}

// Clear cache and don't allow caching for 60s (ensures blockchain propagation)
export function scheduleRefresh(address) {
    startNoCacheWindow();
}
