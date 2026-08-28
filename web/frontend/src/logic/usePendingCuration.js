import { useCallback, useEffect, useState } from 'react';
import { addCurationListener, getPendingCuration } from '../utils/tx';
import { curationPendingKey } from '../utils/curation';
import { useTxStatus } from './useTxStatus';

export function usePendingCuration() {
    const [pending, setPending] = useState({});
    const { formatStatusForPosition } = useTxStatus();

    useEffect(() => {
        let mounted = true;
        let remove = null;
        (async () => {
            const initial = await getPendingCuration();
            if (mounted) setPending(initial);
            const cleanup = await addCurationListener((next) => {
                if (mounted) setPending(next);
            });
            if (!mounted) cleanup?.();
            else remove = cleanup;
        })().catch((error) => {
            console.error('[curation] pending listener failed', error);
        });
        return () => {
            mounted = false;
            remove?.();
        };
    }, []);

    const getInfo = useCallback((action, community, teamId = 0, target = '') => (
        pending[curationPendingKey(action, community, teamId, target)] || null
    ), [pending]);

    const getStatus = useCallback((action, community, teamId = 0, target = '', fallback = 'Working…') => {
        const info = getInfo(action, community, teamId, target);
        if (!info) return null;
        return formatStatusForPosition(info.queuePosition) || fallback;
    }, [formatStatusForPosition, getInfo]);

    return { pending, getInfo, getStatus };
}

export default usePendingCuration;
