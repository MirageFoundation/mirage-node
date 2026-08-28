import { useCallback, useEffect, useMemo, useState } from 'react';
import Api from '../utils/api';
import * as tx from '../utils/tx';
import { formatError } from '../utils/errorMessages';
import { usePendingCuration } from './usePendingCuration';

function validateEarnings(data) {
    if (!data || !Array.isArray(data.items)) throw new Error('Invalid creator earnings response');
    for (const item of data.items) {
        if (!Number.isSafeInteger(Number(item.epoch_id))) throw new Error('Invalid creator earnings epoch');
        if (typeof item.earned !== 'string' || typeof item.claimed !== 'string') {
            throw new Error('Creator earnings amounts must be decimal strings');
        }
        if (!Number.isSafeInteger(Number(item.claim_deadline_epoch))) {
            throw new Error('Creator earnings deadline is required');
        }
    }
    return data.items;
}

export function normalizeClaimEpochs(values) {
    const ids = [...new Set((values || []).map(Number))].sort((a, b) => a - b);
    if (!ids.length) throw new Error('Select at least one claimable epoch');
    if (ids.length > 30) throw new Error('You can claim at most 30 epochs at once');
    if (ids.some((id) => !Number.isSafeInteger(id) || id <= 0)) throw new Error('Invalid epoch selection');
    return ids;
}

export function currentCreatorEpoch(now = Date.now()) {
    return Math.floor(now / 86400000);
}

export function useCreatorEarnings(creator) {
    const address = String(creator || '').trim().toLowerCase();
    const [items, setItems] = useState([]);
    const [selected, setSelected] = useState([]);
    const [loading, setLoading] = useState(Boolean(address));
    const [error, setError] = useState('');
    const { getInfo, getStatus } = usePendingCuration();
    const pending = getInfo('claim_creator_rewards', '', 0, address);

    const refresh = useCallback(async () => {
        if (!address) {
            setItems([]);
            setLoading(false);
            return [];
        }
        setLoading(true);
        setError('');
        try {
            const next = validateEarnings(await Api.get('creator/earnings', { creator: address, _cb: Date.now() }));
            setItems(next);
            setSelected((current) => current.filter((id) => next.some((item) => Number(item.epoch_id) === id)));
            console.debug('[earnings] loaded', { creator: address, epochs: next.length });
            return next;
        } catch (err) {
            const message = String(err?.message || err);
            setError(message);
            console.error('[earnings] load failed', { creator: address, error: message });
            throw err;
        } finally {
            setLoading(false);
        }
    }, [address]);

    useEffect(() => {
        refresh().catch(() => {});
        const onUpdate = () => refresh().catch(() => {});
        window.addEventListener('creatorEarningsUpdated', onUpdate);
        return () => window.removeEventListener('creatorEarningsUpdated', onUpdate);
    }, [refresh]);

    const claimable = useMemo(() => {
        const currentEpoch = currentCreatorEpoch();
        return items.filter((item) => (
            BigInt(item.earned) > BigInt(item.claimed)
            && currentEpoch < Number(item.claim_deadline_epoch)
            && item.claimed_height == null
        ));
    }, [items]);

    const toggleEpoch = useCallback((epochId) => {
        const id = Number(epochId);
        setSelected((current) => (
            current.includes(id)
                ? current.filter((value) => value !== id)
                : normalizeClaimEpochs([...current, id])
        ));
    }, []);

    const claim = useCallback(async () => {
        const epochIds = normalizeClaimEpochs(selected);
        setError('');
        console.debug('[earnings] claiming', { creator: address, epochIds });
        const result = await tx.claimCreatorRewards(epochIds);
        if (!result?.success) {
            const message = formatError(result);
            setError(message);
            throw new Error(message);
        }
        Api.invalidate('creator/earnings');
        await Promise.all([refresh(), tx.refreshBalance()]);
        window.dispatchEvent(new Event('creatorEarningsUpdated'));
        return result;
    }, [address, refresh, selected]);

    return {
        items,
        claimable,
        selected,
        toggleEpoch,
        claim,
        loading,
        error,
        pending: !!pending,
        pendingStatus: getStatus('claim_creator_rewards', '', 0, address, 'Claiming…'),
        refresh,
    };
}

export default useCreatorEarnings;
