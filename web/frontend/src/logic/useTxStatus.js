import { useState, useEffect, useCallback } from 'react';
import { addStatusListener, getQueueStatus, getNextQueuePosition } from '../utils/tx';

export function useTxStatus() {
    const [status, setStatus] = useState({
        status: 'idle',
        position: 0,
        total: 0,
        elapsed: 0,
        isActive: false
    });

    useEffect(() => {
        let unsubscribe = null;
        let mounted = true;
        let disposed = false;

        const setup = async () => {
            try {
                const initial = await getQueueStatus();
                if (mounted) setStatus(initial);
            } catch (_) { }

            const listenerCleanup = await addStatusListener((newStatus) => {
                if (mounted) setStatus(newStatus);
            });
            if (disposed) {
                try {
                    if (listenerCleanup) listenerCleanup();
                } catch (_) { }
                return;
            }
            unsubscribe = listenerCleanup;
        };

        setup();

        return () => {
            mounted = false;
            disposed = true;
            if (unsubscribe) unsubscribe();
        };
    }, []);

    const getMyQueuePosition = useCallback(async () => {
        try {
            return await getNextQueuePosition();
        } catch (_) {
            return status.total + 1;
        }
    }, [status.total]);

    const formatStatusForPosition = useCallback((myQueuePosition) => {
        if (!status.isActive || !myQueuePosition) return null;

        // status.position = processedTransactions = the transaction currently being processed (1-indexed)
        // If my position is greater than the current one being processed, I'm queued
        const txsAhead = myQueuePosition - status.position;

        if (txsAhead > 0) {
            return `Queued (in ${txsAhead})`;
        }

        if (status.status === 'submitting') {
            return 'Submitting…';
        }

        return 'Processing';
    }, [status]);

    return { status, formatStatusForPosition, getMyQueuePosition, isActive: status.isActive };
}

export default useTxStatus;

