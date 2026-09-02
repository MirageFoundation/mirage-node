import { useCallback, useEffect, useMemo, useState } from 'react';
import Api from '../utils/api';
import * as tx from '../utils/tx';
import { formatError } from '../utils/errorMessages';
import { usePendingCuration } from './usePendingCuration';

function validateEarnings(data) {
    if (!data || !Array.isArray(data.items)) throw new Error('Invalid creator earnings response');
    const creatorEpochSeconds = Number(data.creator_epoch_seconds);
    if (!Number.isSafeInteger(creatorEpochSeconds) || creatorEpochSeconds < 300) {
        throw new Error('Creator reward interval is required');
    }
    const originEpoch = Number(data.origin_epoch);
    const originUnix = Number(data.origin_unix);
    if (!Number.isSafeInteger(originEpoch) || originEpoch < 0) {
        throw new Error('Creator schedule origin epoch is required');
    }
    if (!Number.isSafeInteger(originUnix) || originUnix < 0) {
        throw new Error('Creator schedule origin unix is required');
    }
    for (const item of data.items) {
        if (!Number.isSafeInteger(Number(item.epoch_id))) throw new Error('Invalid creator earnings epoch');
        if (typeof item.earned !== 'string' || typeof item.claimed !== 'string') {
            throw new Error('Creator earnings amounts must be decimal strings');
        }
        for (const field of ['epoch_start_unix', 'epoch_end_unix', 'claim_deadline_unix']) {
            if (!Number.isSafeInteger(Number(item[field])) || Number(item[field]) <= 0) {
                throw new Error(`Creator earnings ${field} is required`);
            }
        }
        if (!Array.isArray(item.posts)) throw new Error('Creator earnings posts breakdown is required');
        for (const post of item.posts) {
            if (!post.txhash || typeof post.amount !== 'string') {
                throw new Error('Creator earnings post breakdown must carry a txhash and amount');
            }
        }
    }
    return { items: data.items, creatorEpochSeconds, originEpoch, originUnix };
}

export function normalizeClaimEpochs(values) {
    const ids = [...new Set((values || []).map(Number))].sort((a, b) => a - b);
    if (!ids.length) throw new Error('Select at least one claimable epoch');
    if (ids.length > 30) throw new Error('You can claim at most 30 epochs at once');
    if (ids.some((id) => !Number.isSafeInteger(id) || id <= 0)) throw new Error('Invalid epoch selection');
    return ids;
}

export function currentCreatorEpoch(epochSeconds, now = Date.now(), originEpoch = 0, originUnix = 0) {
    const seconds = Number(epochSeconds);
    if (!Number.isSafeInteger(seconds) || seconds <= 0) throw new Error('Invalid creator reward interval');
    const origin = Number(originEpoch);
    const originAt = Number(originUnix);
    if (!Number.isSafeInteger(origin) || origin < 0) throw new Error('Invalid creator schedule origin epoch');
    if (!Number.isSafeInteger(originAt) || originAt < 0) throw new Error('Invalid creator schedule origin unix');
    return origin + Math.floor((Math.floor(now / 1000) - originAt) / seconds);
}

export function isCreatorEarningClaimable(item, now = Date.now()) {
    return (
        BigInt(item.earned) > BigInt(item.claimed)
        && Math.floor(now / 1000) < Number(item.claim_deadline_unix)
        && item.claimed_height == null
    );
}

export function useCreatorEarnings(creator) {
    const address = String(creator || '').trim().toLowerCase();
    const [items, setItems] = useState([]);
    const [creatorEpochSeconds, setCreatorEpochSeconds] = useState(null);
    const [originEpoch, setOriginEpoch] = useState(null);
    const [originUnix, setOriginUnix] = useState(null);
    const [selected, setSelected] = useState([]);
    const [loading, setLoading] = useState(Boolean(address));
    const [error, setError] = useState('');
    const { getInfo, getStatus } = usePendingCuration();
    const pending = getInfo('claim_creator_rewards', '', 0, address);

    const refresh = useCallback(async () => {
        if (!address) {
            setItems([]);
            setCreatorEpochSeconds(null);
            setOriginEpoch(null);
            setOriginUnix(null);
            setLoading(false);
            return [];
        }
        setLoading(true);
        setError('');
        try {
            const next = validateEarnings(await Api.get('creator/earnings', { creator: address, _cb: Date.now() }));
            setItems(next.items);
            setCreatorEpochSeconds(next.creatorEpochSeconds);
            setOriginEpoch(next.originEpoch);
            setOriginUnix(next.originUnix);
            setSelected((current) => current.filter((id) => next.items.some((item) => Number(item.epoch_id) === id)));
            console.debug('[earnings] loaded', {
                creator: address,
                epochs: next.items.length,
                creatorEpochSeconds: next.creatorEpochSeconds,
                originEpoch: next.originEpoch,
                originUnix: next.originUnix,
            });
            return next.items;
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
        return items.filter((item) => isCreatorEarningClaimable(item));
    }, [items]);

    const toggleEpoch = useCallback((epochId) => {
        const id = Number(epochId);
        setSelected((current) => (
            current.includes(id)
                ? current.filter((value) => value !== id)
                : normalizeClaimEpochs([...current, id])
        ));
    }, []);

    // `epochIds` lets the feed banner claim everything outstanding in one go,
    // while the profile panel claims whatever the user ticked.
    const claim = useCallback(async (epochIds = null) => {
        epochIds = normalizeClaimEpochs(epochIds || selected);
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
        creatorEpochSeconds,
        originEpoch,
        originUnix,
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
