import { useState, useEffect, useCallback } from 'react';
import * as tx from '../utils/tx';
import { useTxStatus } from './useTxStatus';

/**
 * Hook to track pending block/unblock operations globally.
 */
export function usePendingBlocks() {
    const [pendingBlocks, setPendingBlocks] = useState({});
    const { formatStatusForPosition } = useTxStatus();

    useEffect(() => {
        let unsubscribe = null;
        let mounted = true;

        const setup = async () => {
            try {
                const initial = await tx.getPendingBlocks();
                if (mounted) setPendingBlocks(initial);
            } catch (err) {
                console.error('[blocks] failed to load pending blocks', err);
            }

            unsubscribe = await tx.addBlockListener((blocks) => {
                if (mounted) setPendingBlocks(blocks);
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
        return !!pendingBlocks[key];
    }, [pendingBlocks]);

    const getInfo = useCallback((type, target) => {
        const key = `${type}:${String(target || '').toLowerCase()}`;
        return pendingBlocks[key] || null;
    }, [pendingBlocks]);

    const isTopicPending = useCallback((topic) => isPending('topic', topic), [isPending]);
    const isUserPending = useCallback((user) => isPending('user', user), [isPending]);
    const isPostPending = useCallback((postId) => isPending('post', postId), [isPending]);

    const getTopicInfo = useCallback((topic) => getInfo('topic', topic), [getInfo]);
    const getUserInfo = useCallback((user) => getInfo('user', user), [getInfo]);
    const getPostInfo = useCallback((postId) => getInfo('post', postId), [getInfo]);

    const formatStatus = useCallback((type, target) => {
        const info = getInfo(type, target);
        if (!info) return null;
        const formatted = formatStatusForPosition(info.queuePosition);
        if (formatted) return formatted;
        return info.action === 'unblock' ? 'Unblocking…' : 'Blocking…';
    }, [getInfo, formatStatusForPosition]);

    const formatTopicStatus = useCallback((topic) => formatStatus('topic', topic), [formatStatus]);
    const formatUserStatus = useCallback((user) => formatStatus('user', user), [formatStatus]);
    const formatPostStatus = useCallback((postId) => formatStatus('post', postId), [formatStatus]);

    return {
        pendingBlocks,
        isPending,
        getInfo,
        isTopicPending,
        isUserPending,
        isPostPending,
        getTopicInfo,
        getUserInfo,
        getPostInfo,
        formatTopicStatus,
        formatUserStatus,
        formatPostStatus,
    };
}

export default usePendingBlocks;
