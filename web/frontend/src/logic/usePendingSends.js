import { useState, useEffect, useCallback } from 'react';
import * as tx from '../utils/tx';
import { useTxStatus } from './useTxStatus';

/**
 * Hook to track pending send_tokens operations globally.
 */
export function usePendingSends() {
    const [pendingSends, setPendingSends] = useState({});
    const { formatStatusForPosition } = useTxStatus();

    useEffect(() => {
        let unsubscribe = null;
        let mounted = true;

        const setup = async () => {
            try {
                const initial = await tx.getPendingSends();
                if (mounted) setPendingSends(initial);
            } catch (err) {
                console.error('[send_tokens] failed to load pending sends', err);
            }

            unsubscribe = await tx.addSendListener((sends) => {
                if (mounted) setPendingSends(sends);
            });
        };

        setup();

        return () => {
            mounted = false;
            if (unsubscribe) unsubscribe();
        };
    }, []);

    const getKey = useCallback((target) => `send:${String(target).toLowerCase()}`, []);

    const isPending = useCallback((target) => {
        const key = getKey(target);
        return !!pendingSends[key];
    }, [pendingSends, getKey]);

    const getInfo = useCallback((target) => {
        const key = getKey(target);
        return pendingSends[key] || null;
    }, [pendingSends, getKey]);

    const formatStatus = useCallback((target) => {
        const info = getInfo(target);
        if (!info) return null;
        const formatted = formatStatusForPosition(info.queuePosition);
        if (formatted) return formatted;
        return 'Sending...';
    }, [getInfo, formatStatusForPosition]);

    return {
        pendingSends,
        isPending,
        getInfo,
        formatStatus,
    };
}

export default usePendingSends;
