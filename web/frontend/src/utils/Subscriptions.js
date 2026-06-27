import transactionHandler from './TransactionHandler';
import { fetchProfile, getFollowedTopics as getTopicsFromCache, invalidateCache as invalidateProfileCache, isCacheValid, updateCacheTopics, scheduleRefresh } from './ProfileCache';
import { trackEvent } from './analytics';

export async function fetchFollowedTopics(viewerAddress) {
    const addr = String(viewerAddress || '').trim().toLowerCase();
    if (!addr || addr === 'guest') {
        return [];
    }

    try {
        // Always go through ProfileCache so no-cache window / TTL logic applies.
        const profile = await fetchProfile(addr);
        if (profile && Array.isArray(profile.followed_topics)) {
            // Normalize the list the same way as getTopicsFromCache()
            return profile.followed_topics
                .map(t => String(t || '').trim())
                .filter(t => {
                    const v = t.toLowerCase();
                    return v !== 'all' && v !== 'home' && v !== '';
                });
        }
        // Fallback to whatever is in cache (may be empty during no-cache window)
        return getTopicsFromCache() || [];
    } catch (e) {
        console.error('[Subscriptions] Failed to fetch followed topics:', e);
        return getTopicsFromCache() || [];
    }
}

export function invalidateCache() {
    invalidateProfileCache();
}

export function notifyTopicsUpdated(detail = {}) {
    window.dispatchEvent(new CustomEvent('followedTopicsUpdated', { detail }));
}

export function loadSubscriptions(address) {
    const addr = String(address || '').trim().toLowerCase();
    if (isCacheValid(addr)) {
        return [...getTopicsFromCache()];
    }
    return [];
}

export function isSubscribed(address, topic) {
    const t = String(topic || '').trim();
    if (!t) return false;
    const list = loadSubscriptions(address);
    return list.map(x => x.toLowerCase()).includes(t.toLowerCase());
}

export async function isSubscribedAsync(address, topic) {
    const t = String(topic || '').trim();
    if (!t) return false;
    const list = await fetchFollowedTopics(address);
    return list.map(x => x.toLowerCase()).includes(t.toLowerCase());
}

function addToCache(topic, address) {
    const t = String(topic || '').trim().toLowerCase();
    if (!t || t === 'all' || t === 'home') return;
    const current = getTopicsFromCache() || [];
    if (!current.map(x => x.toLowerCase()).includes(t)) {
        updateCacheTopics([...current, t], address);
    }
}

function removeFromCache(topic, address) {
    const t = String(topic || '').trim().toLowerCase();
    if (!t) return;
    const current = getTopicsFromCache() || [];
    updateCacheTopics(current.filter(x => x.toLowerCase() !== t), address);
}

export async function subscribe(address, topic) {
    const t = String(topic || '').trim();
    if (!t) return [];
    const lower = t.toLowerCase();
    if (lower === 'all' || lower === 'home') return [];

    const result = await transactionHandler.followTopic(t);

    if (result.success) {
        scheduleRefresh(address); // Clear cache, start no-cache window
        addToCache(t, address);   // Will be skipped during no-cache window
        notifyTopicsUpdated({ added: lower });
        trackEvent('topic_followed');
        return [];
    } else {
        // "already followed" means the user's intent is satisfied
        const errLower = String(result.error || '').toLowerCase();
        if (errLower.includes('already followed')) {
            addToCache(t, address);
            notifyTopicsUpdated({ added: lower });
            return [];
        }
        console.error('[Subscriptions] Subscribe transaction failed:', result.error);
        throw new Error(result.error || 'Subscribe failed');
    }
}

export async function unsubscribe(address, topic) {
    const t = String(topic || '').trim();
    if (!t) return [];
    const lower = t.toLowerCase();

    const result = await transactionHandler.unfollowTopic(t);

    if (result.success) {
        scheduleRefresh(address); // Clear cache, start no-cache window
        removeFromCache(t, address); // Will be skipped during no-cache window
        notifyTopicsUpdated({ removed: lower });
        return [];
    } else {
        // "not followed" / "not following" means the user's intent is satisfied
        const errLower = String(result.error || '').toLowerCase();
        if (errLower.includes('not followed') || errLower.includes('not following')) {
            removeFromCache(t, address);
            notifyTopicsUpdated({ removed: lower });
            return [];
        }
        console.error('[Subscriptions] Unsubscribe transaction failed:', result.error);
        throw new Error(result.error || 'Unsubscribe failed');
    }
}

export const loadFollowedTopics = loadSubscriptions;
export const saveFollowedTopics = () => { };
export const isFollowingTopic = isSubscribed;
export const followTopic = subscribe;
export const unfollowTopic = unsubscribe;
