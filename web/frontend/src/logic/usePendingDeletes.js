import { useState, useEffect, useCallback } from 'react';
import * as tx from '../utils/tx';
import { useTxStatus } from './useTxStatus';

/**
 * Hook to track pending delete-account operations globally.
 */
export function usePendingDeletes() {
    const [pendingDeletes, setPendingDeletes] = useState({});
    const { formatStatusForPosition } = useTxStatus();

    useEffect(() => {
        let unsubscribe = null;
        let mounted = true;

        const setup = async () => {
            try {
                const initial = await tx.getPendingDeletes();
                if (mounted) setPendingDeletes(initial);
            } catch (err) {
                console.error('[delete_user] failed to load pending deletes', err);
            }

            unsubscribe = await tx.addDeleteListener((deletes) => {
                if (mounted) setPendingDeletes(deletes);
            });
        };

        setup();

        return () => {
            mounted = false;
            if (unsubscribe) unsubscribe();
        };
    }, []);

    const getInfo = useCallback((target) => {
        const key = `account:${String(target || '').toLowerCase()}`;
        return pendingDeletes[key] || null;
    }, [pendingDeletes]);

    const isPending = useCallback((target) => !!getInfo(target), [getInfo]);

    const formatStatus = useCallback((target) => {
        const info = getInfo(target);
        if (!info) return null;
        const formatted = formatStatusForPosition(info.queuePosition);
        if (formatted) return formatted;
        return 'Deleting...';
    }, [getInfo, formatStatusForPosition]);

    return {
        pendingDeletes,
        getInfo,
        isPending,
        formatStatus,
    };
}

export default usePendingDeletes;
