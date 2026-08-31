import { useState, useEffect, useCallback } from 'react';
import * as tx from '../utils/tx';
import { useTxStatus } from './useTxStatus';

/**
 * Hook to track pending subscribe operations globally.
 */
export function usePendingSubscribes() {
    const [pendingSubscribes, setPendingSubscribes] = useState({});
    const { formatStatusForPosition } = useTxStatus();

    useEffect(() => {
        let unsubscribe = null;
        let mounted = true;

        const setup = async () => {
            try {
                const initial = await tx.getPendingSubscribes();
                if (mounted) setPendingSubscribes(initial);
            } catch (err) {
                console.error('[subscribe] failed to load pending subscribes', err);
            }

            unsubscribe = await tx.addSubscribeListener((subs) => {
                if (mounted) setPendingSubscribes(subs);
            });
        };

        setup();

        return () => {
            mounted = false;
            if (unsubscribe) unsubscribe();
        };
    }, []);

    const getKey = useCallback((target) => `subscribe:${String(target).toLowerCase()}`, []);

    const isPending = useCallback((target) => {
        const key = getKey(target);
        return !!pendingSubscribes[key];
    }, [pendingSubscribes, getKey]);

    const getInfo = useCallback((target) => {
        const key = getKey(target);
        return pendingSubscribes[key] || null;
    }, [pendingSubscribes, getKey]);

    const formatStatus = useCallback((target) => {
        const info = getInfo(target);
        if (!info) return null;
        const formatted = formatStatusForPosition(info.queuePosition);
        if (formatted) return formatted;
        return info.action === 'gift' ? 'Gifting…' : 'Subscribing…';
    }, [getInfo, formatStatusForPosition]);

    return {
        pendingSubscribes,
        isPending,
        getInfo,
        formatStatus,
    };
}

export default usePendingSubscribes;
