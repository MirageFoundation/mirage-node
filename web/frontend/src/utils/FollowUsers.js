import transactionHandler from './TransactionHandler';
import { fetchProfile, getFollowedUsers as getUsersFromCache, invalidateCache as invalidateProfileCache, isCacheValid, updateCacheUsers, scheduleRefresh } from './ProfileCache';

export async function fetchFollowedUsers(viewerAddress) {
    const addr = String(viewerAddress || '').trim().toLowerCase();
    if (!addr || addr === 'guest') {
        return [];
    }

    try {
        // Always go through ProfileCache so no-cache window / TTL logic applies.
        const profile = await fetchProfile(addr);
        if (profile && Array.isArray(profile.followed_users)) {
            // Normalize the list the same way as getUsersFromCache()
            return profile.followed_users
                .map(u => String(u || '').trim().toLowerCase())
                .filter(Boolean);
        }
        // Fallback to whatever is in cache (may be empty during no-cache window)
        return getUsersFromCache() || [];
    } catch (e) {
        console.error('[FollowUsers] Failed to fetch followed users:', e);
        return getUsersFromCache() || [];
    }
}

export function invalidateCache() {
    invalidateProfileCache();
}

export function notifyUsersUpdated(detail = {}) {
    window.dispatchEvent(new CustomEvent('followedUsersUpdated', { detail }));
}

export function loadFollowedAuthors(viewerAddress) {
    const addr = String(viewerAddress || '').trim().toLowerCase();
    if (isCacheValid(addr)) {
        return [...getUsersFromCache()];
    }
    return [];
}

export function isFollowing(viewerAddress, authorAddress) {
    const a = String(authorAddress || '').trim().toLowerCase();
    if (!a) return false;
    const list = loadFollowedAuthors(viewerAddress);
    return list.includes(a);
}

export async function isFollowingAsync(viewerAddress, authorAddress) {
    const a = String(authorAddress || '').trim().toLowerCase();
    if (!a) return false;
    const list = await fetchFollowedUsers(viewerAddress);
    return list.includes(a);
}

function addToCache(userAddress, viewerAddress) {
    const a = String(userAddress || '').trim().toLowerCase();
    if (!a) return;
    const current = getUsersFromCache() || [];
    if (!current.includes(a)) {
        updateCacheUsers([...current, a], viewerAddress);
    }
}

function removeFromCache(userAddress, viewerAddress) {
    const a = String(userAddress || '').trim().toLowerCase();
    if (!a) return;
    const current = getUsersFromCache() || [];
    updateCacheUsers(current.filter(u => u !== a), viewerAddress);
}

export async function follow(viewerAddress, authorAddress) {
    const a = String(authorAddress || '').trim().toLowerCase();
    if (!a) return [];

    const result = await transactionHandler.followUser(a);

    if (result.success) {
        scheduleRefresh(viewerAddress); // Clear cache, start no-cache window
        addToCache(a, viewerAddress);   // Will be skipped during no-cache window
        notifyUsersUpdated({ added: a });
        return [];
    } else {
        // "already followed/following" means the user's intent is satisfied
        const errLower = String(result.error || '').toLowerCase();
        if (errLower.includes('already follow')) {
            addToCache(a, viewerAddress);
            notifyUsersUpdated({ added: a });
            return [];
        }
        console.error('[FollowUsers] Follow transaction failed:', result.error);
        throw new Error(result.error || 'Follow failed');
    }
}

export async function unfollow(viewerAddress, authorAddress) {
    const a = String(authorAddress || '').trim().toLowerCase();
    if (!a) return [];

    const result = await transactionHandler.unfollowUser(a);

    if (result.success) {
        scheduleRefresh(viewerAddress); // Clear cache, start no-cache window
        removeFromCache(a, viewerAddress); // Will be skipped during no-cache window
        notifyUsersUpdated({ removed: a });
        return [];
    } else {
        // "not followed/following" means the user's intent is satisfied
        const errLower = String(result.error || '').toLowerCase();
        if (errLower.includes('not follow')) {
            removeFromCache(a, viewerAddress);
            notifyUsersUpdated({ removed: a });
            return [];
        }
        console.error('[FollowUsers] Unfollow transaction failed:', result.error);
        throw new Error(result.error || 'Unfollow failed');
    }
}

export const followAuthor = follow;
export const unfollowAuthor = unfollow;
export const isFollowingAuthor = isFollowing;
