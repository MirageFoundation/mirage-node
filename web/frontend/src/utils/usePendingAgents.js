import { useState, useEffect, useCallback } from 'react';
import * as tx from './tx';
import { useTxStatus } from './useTxStatus';

export function usePendingAgents() {
    const [pendingAgents, setPendingAgents] = useState({});
    const { formatStatusForPosition } = useTxStatus();

    useEffect(() => {
        let unsubscribe = null;
        let mounted = true;

        const setup = async () => {
            try {
                const initial = await tx.getPendingAgents();
                if (mounted) setPendingAgents(initial);
            } catch (_) { }

            unsubscribe = await tx.addAgentListener((agents) => {
                if (mounted) setPendingAgents(agents);
            });
        };

        setup();

        return () => {
            mounted = false;
            if (unsubscribe) unsubscribe();
        };
    }, []);

    const isPending = useCallback((agentAddress) => {
        const key = String(agentAddress || '').toLowerCase();
        return !!pendingAgents[key];
    }, [pendingAgents]);

    const getInfo = useCallback((agentAddress) => {
        const key = String(agentAddress || '').toLowerCase();
        return pendingAgents[key] || null;
    }, [pendingAgents]);

    const formatStatus = useCallback((agentAddress) => {
        const info = getInfo(agentAddress);
        if (!info) return null;
        const formatted = formatStatusForPosition(info.queuePosition);
        if (formatted) return formatted;
        return info.action === 'disable' ? 'Disabling...' : 'Enabling...';
    }, [getInfo, formatStatusForPosition]);

    return {
        pendingAgents,
        isPending,
        getInfo,
        formatStatus,
    };
}

export default usePendingAgents;
