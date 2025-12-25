import { useState, useEffect, useCallback } from 'react';
import * as tx from './tx';
import { useTxStatus } from './useTxStatus';

/**
 * Hook to track pending follow/unfollow operations globally.
 * Works similarly to usePendingVotes in VoteSection.js.
 * 
 * All blockchain operations should follow the same pattern:
 * - Use global state tracking that persists across page navigation
 * - Display queue position using formatStatusForPosition()
 * - Show action-specific text (e.g., "Following..." vs "Unfollowing...")
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

    const isTopicPending = useCallback((topic) => {
        return isPending('topic', topic);
    }, [isPending]);

    const isUserPending = useCallback((user) => {
        return isPending('user', user);
    }, [isPending]);

    const getTopicInfo = useCallback((topic) => {
        return getInfo('topic', topic);
    }, [getInfo]);

    const getUserInfo = useCallback((user) => {
        return getInfo('user', user);
    }, [getInfo]);

    const formatTopicStatus = useCallback((topic) => {
        const info = getInfo('topic', topic);
        if (!info) return null;
        const formatted = formatStatusForPosition(info.queuePosition);
        if (formatted) return formatted;
        return info.action === 'unfollow' ? 'Unfollowing...' : 'Following...';
    }, [getInfo, formatStatusForPosition]);

    const formatUserStatus = useCallback((user) => {
        const info = getInfo('user', user);
        if (!info) return null;
        const formatted = formatStatusForPosition(info.queuePosition);
        if (formatted) return formatted;
        return info.action === 'unfollow' ? 'Unfollowing...' : 'Following...';
    }, [getInfo, formatStatusForPosition]);

    return {
        pendingFollows,
        isPending,
        getInfo,
        isTopicPending,
        isUserPending,
        getTopicInfo,
        getUserInfo,
        formatTopicStatus,
        formatUserStatus,
    };
}

export default usePendingFollows;

