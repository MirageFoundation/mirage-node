import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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

// The claim rows are re-read until the chain has the claim, but never forever.
const CLAIM_SETTLE_TIMEOUT_MS = 120000;
const CLAIM_SETTLE_INTERVAL_MS = 2000;

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
    const mounted = useRef(false);

    // `quiet` re-reads without touching `loading`, so the post-claim polling
    // below does not flash a loading row on the ledger every two seconds.
    const refresh = useCallback(async (quiet = false) => {
        if (!address) {
            setItems([]);
            setCreatorEpochSeconds(null);
            setOriginEpoch(null);
            setOriginUnix(null);
            setLoading(false);
            return [];
        }
        if (!quiet) {
            setLoading(true);
            setError('');
        }
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
            if (!quiet) setLoading(false);
        }
    }, [address]);

    useEffect(() => {
        mounted.current = true;
        refresh().catch(() => {});
        const onUpdate = () => refresh().catch(() => {});
        window.addEventListener('creatorEarningsUpdated', onUpdate);
        return () => {
            mounted.current = false;
            window.removeEventListener('creatorEarningsUpdated', onUpdate);
        };
    }, [refresh]);

    // Runs detached from the claim, so it must stop on its own: bounded by a
    // deadline, and abandoned if the component that started it is gone.
    const settle = useCallback(async (ids) => {
        const deadline = Date.now() + CLAIM_SETTLE_TIMEOUT_MS;
        while (Date.now() < deadline) {
            await new Promise((done) => setTimeout(done, CLAIM_SETTLE_INTERVAL_MS));
            if (!mounted.current) return;
            let next;
            try {
                next = await refresh(true);
            } catch (err) {
                console.error('[earnings] settle refresh failed', String(err?.message || err));
                continue;
            }
            const rows = next.filter((item) => ids.includes(Number(item.epoch_id)));
            if (rows.length === ids.length && rows.every((item) => item.claimed_height != null)) {
                console.debug('[earnings] claim settled', { epochIds: ids });
                await tx.refreshBalance();
                window.dispatchEvent(new Event('creatorEarningsUpdated'));
                return;
            }
        }
        console.warn('[earnings] claim did not settle within the budget', { epochIds: ids });
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
        const ids = normalizeClaimEpochs(epochIds || selected);
        setError('');
        console.debug('[earnings] claiming', { creator: address, epochIds: ids });
        const result = await tx.claimCreatorRewards(ids);
        if (!result?.success) {
            const message = formatError(result);
            setError(message);
            throw new Error(message);
        }
        Api.invalidate('creator/earnings');

        // Submitting already waited for the queue and, on the free tier, for
        // PoW. Do not make the caller wait for the chain on top of that: the
        // claim is expected to land, so the UI confirms now like every other
        // action does. The reward rows still have to be re-read once the chain
        // and indexer catch up, but that happens behind the confirmation
        // instead of in front of it, and it puts the card back if the claim
        // somehow did not land.
        void settle(ids);
        return result;
    }, [address, selected, settle]);

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
