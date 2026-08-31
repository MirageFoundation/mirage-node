import { useState, useEffect, useCallback } from 'react';
import * as tx from '../utils/tx';
import { useTxStatus } from './useTxStatus';

/**
 * Hook to track pending follow/unfollow operations globally.
 * Works similarly to usePendingVotes in VoteSection.js.
 * 
 * All blockchain operations should follow the same pattern:
 * - Use global state tracking that persists across page navigation
 * - Display queue position using formatStatusForPosition()
 * - Show action-specific text
 */
export function usePendingFollows() {
    const [pendingFollows, setPendingFollows] = useState({});
    const { formatStatusForPosition } = useTxStatus();

    useEffect(() => {
        let unsubscribe = null;
        let mounted = true;

        const setup = async () => {
            try {
                const initial = await tx.getPendingFollows();
                if (mounted) setPendingFollows(initial);
            } catch (_) { }

            unsubscribe = await tx.addFollowListener((follows) => {
                if (mounted) setPendingFollows(follows);
            });
        };

        setup();

        return () => {
            mounted = false;
            if (unsubscribe) unsubscribe();
        };
    }, []);

    const isPending = useCallback((type, target) => {
        const key = `${type}:${String(target || '').toLowerCase()}`;
        return !!pendingFollows[key];
    }, [pendingFollows]);

    const getInfo = useCallback((type, target) => {
        const key = `${type}:${String(target || '').toLowerCase()}`;
        return pendingFollows[key] || null;
    }, [pendingFollows]);

    const isCommunityPending = useCallback((community) => {
        return isPending('community', community);
    }, [isPending]);

    const isUserPending = useCallback((user) => {
        return isPending('user', user);
    }, [isPending]);

    const getCommunityInfo = useCallback((community) => {
        return getInfo('community', community);
    }, [getInfo]);

    const getUserInfo = useCallback((user) => {
        return getInfo('user', user);
    }, [getInfo]);

    const formatCommunityStatus = useCallback((community) => {
        const info = getInfo('community', community);
        if (!info) return null;
        const formatted = formatStatusForPosition(info.queuePosition);
        if (formatted) return formatted;
        return info.action === 'leave' ? 'Leaving…' : 'Joining…';
    }, [getInfo, formatStatusForPosition]);

    const formatUserStatus = useCallback((user) => {
        const info = getInfo('user', user);
        if (!info) return null;
        const formatted = formatStatusForPosition(info.queuePosition);
        if (formatted) return formatted;
        return info.action === 'unfollow' ? 'Unfollowing…' : 'Following…';
    }, [getInfo, formatStatusForPosition]);

    return {
        pendingFollows,
        isPending,
        getInfo,
        isCommunityPending,
        isUserPending,
        getCommunityInfo,
        getUserInfo,
        formatCommunityStatus,
        formatUserStatus,
    };
}

export default usePendingFollows;

