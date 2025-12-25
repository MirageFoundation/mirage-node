import { useState, useEffect, useCallback } from 'react';
import { addStatusListener, getQueueStatus, getNextQueuePosition } from './tx';
import Storage from './Storage';

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

        const setup = async () => {
            try {
                const initial = await getQueueStatus();
                if (mounted) setStatus(initial);
            } catch (_) { }

            unsubscribe = await addStatusListener((newStatus) => {
                if (mounted) setStatus(newStatus);
            });
        };

        setup();

        return () => {
            mounted = false;
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

        const userLevel = Number(Storage.load('user_level', '0')) || 0;
        const isSubscriber = userLevel > 0;

        // status.position = processedTransactions = the transaction currently being processed (1-indexed)
        // If my position is greater than the current one being processed, I'm queued
        const txsAhead = myQueuePosition - status.position;

        if (txsAhead > 0) {
            return `Queued (in ${txsAhead})`;
        }

        if (status.status === 'submitting') {
            // Subscribers have instant tx, no need to show seconds
            return isSubscriber ? 'Submitting...' : `Submitting (${status.elapsed.toFixed(1)}s)`;
        }

        // Subscribers don't do PoW
        return isSubscriber ? 'Processing...' : `Solving PoW (${status.elapsed.toFixed(1)}s)`;
    }, [status]);

    return { status, formatStatusForPosition, getMyQueuePosition, isActive: status.isActive };
}

export default useTxStatus;

