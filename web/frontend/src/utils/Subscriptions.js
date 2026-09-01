import transactionHandler from './TransactionHandler';
import { fetchProfile, getJoinedCommunities as getCommunitiesFromCache, invalidateCache as invalidateProfileCache, isCacheValid, updateCacheCommunities, scheduleRefresh } from './ProfileCache';
import { fetchViewerCuratorMembership } from '../logic/useViewerCuratorMembership';
import { invalidateCurationReads } from './curation';
import { requestCommunityLeaveConfirmation } from './communityLeaveConfirmation';

export async function fetchJoinedCommunities(viewerAddress) {
    const addr = String(viewerAddress || '').trim().toLowerCase();
    if (!addr || addr === 'guest') {
        return [];
    }

    try {
        const profile = await fetchProfile(addr);
        if (profile && Array.isArray(profile.joined_communities)) {
            return profile.joined_communities
                .map(t => String(t || '').trim())
                .filter(t => {
                    const v = t.toLowerCase();
                    return v !== 'all' && v !== 'home' && v !== '';
                });
        }
        return getCommunitiesFromCache() || [];
    } catch (e) {
        console.error('[Subscriptions] Failed to fetch joined communities:', e);
        return getCommunitiesFromCache() || [];
    }
}

export function invalidateCache() {
    invalidateProfileCache();
}

export function notifyJoinedCommunitiesUpdated(detail = {}) {
    window.dispatchEvent(new CustomEvent('joinedCommunitiesUpdated', { detail }));
}

export function loadSubscriptions(address) {
    const addr = String(address || '').trim().toLowerCase();
    if (isCacheValid(addr)) {
        return [...getCommunitiesFromCache()];
    }
    return [];
}

export function isJoinedCommunity(address, community) {
    const t = String(community || '').trim();
    if (!t) return false;
    const list = loadSubscriptions(address);
    return list.map(x => x.toLowerCase()).includes(t.toLowerCase());
}

export async function isJoinedCommunityAsync(address, community) {
    const t = String(community || '').trim();
    if (!t) return false;
    const list = await fetchJoinedCommunities(address);
    return list.map(x => x.toLowerCase()).includes(t.toLowerCase());
}

function addToCache(community, address) {
    const t = String(community || '').trim().toLowerCase();
    if (!t || t === 'all' || t === 'home') return;
    const current = getCommunitiesFromCache() || [];
    if (!current.map(x => x.toLowerCase()).includes(t)) {
        updateCacheCommunities([...current, t], address);
    }
}

function removeFromCache(community, address) {
    const t = String(community || '').trim().toLowerCase();
    if (!t) return;
    const current = getCommunitiesFromCache() || [];
    updateCacheCommunities(current.filter(x => x.toLowerCase() !== t), address);
}

export async function joinCommunity(address, community, mode = 0, pinnedTeamId = 0) {
    const t = String(community || '').trim();
    if (!t) return [];
    const lower = t.toLowerCase();
    if (lower === 'all' || lower === 'home') return [];

    const result = await transactionHandler.joinCommunity(t, mode, pinnedTeamId);

    if (result.success) {
        scheduleRefresh(address);
        addToCache(t, address);
        notifyJoinedCommunitiesUpdated({ added: lower });
        return [];
    } else {
        const errLower = String(result.error || '').toLowerCase();
        if (errLower.includes('already followed') || errLower.includes('already joined')) {
            addToCache(t, address);
            notifyJoinedCommunitiesUpdated({ added: lower });
            return [];
        }
        console.error('[Subscriptions] Join community transaction failed:', result.error);
        throw new Error(result.error || 'Join community failed');
    }
}

export async function leaveCommunity(address, community) {
    const t = String(community || '').trim();
    if (!t) return [];
    const lower = t.toLowerCase();
    const membership = await fetchViewerCuratorMembership(lower, address, { fresh: true });
    if (membership) {
        console.debug('[Subscriptions] Curator community leave requires confirmation', {
            community: lower,
            teamId: membership.teamId,
            memberCount: membership.memberCount,
            isLeader: membership.isLeader,
        });
        const confirmed = await requestCommunityLeaveConfirmation({
            community: lower,
            membership,
        });
        if (!confirmed) {
            console.debug('[Subscriptions] Curator community leave cancelled', {
                community: lower,
                teamId: membership.teamId,
            });
            const error = new Error('Community leave cancelled');
            error.code = 'community_leave_cancelled';
            throw error;
        }
    }

    const result = await transactionHandler.leaveCommunity(t);

    if (result.success) {
        scheduleRefresh(address);
        removeFromCache(t, address);
        notifyJoinedCommunitiesUpdated({ removed: lower });
        invalidateCurationReads(lower);
        return [];
    } else {
        const errLower = String(result.error || '').toLowerCase();
        if (errLower.includes('not followed') || errLower.includes('not following') || errLower.includes('not joined')) {
            removeFromCache(t, address);
            notifyJoinedCommunitiesUpdated({ removed: lower });
            invalidateCurationReads(lower);
            return [];
        }
        console.error('[Subscriptions] Leave community transaction failed:', result.error);
        throw new Error(result.error || 'Leave community failed');
    }
}
