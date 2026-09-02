import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Api from '../utils/api';
import * as tx from '../utils/tx';
import { formatError } from '../utils/errorMessages';
import { usePendingCuration } from './usePendingCuration';

const EARNINGS_PAGE_LIMIT = 50;
const EARNINGS_MAX_PAGES = 200;

export function validateEarnings(data) {
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
    const maxClaimEpochs = Number(data.max_creator_claim_epochs);
    if (!Number.isSafeInteger(maxClaimEpochs) || maxClaimEpochs <= 0) {
        throw new Error('Creator claim batch limit is required');
    }
    if (typeof data.has_more !== 'boolean') throw new Error('Creator earnings pagination state is required');
    const nextCursor = data.next_cursor == null ? null : String(data.next_cursor);
    if (data.has_more && !nextCursor) throw new Error('Creator earnings next cursor is required');
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
    return {
        items: data.items,
        creatorEpochSeconds,
        originEpoch,
        originUnix,
        maxClaimEpochs,
        nextCursor,
        hasMore: data.has_more,
    };
}

const CLAIM_SETTLE_TIMEOUT_MS = 120000;
const CLAIM_SETTLE_INTERVAL_MS = 2000;

export function normalizeClaimEpochs(values, maxClaimEpochs) {
    const cap = Number(maxClaimEpochs);
    if (!Number.isSafeInteger(cap) || cap <= 0) throw new Error('Creator claim batch limit is required');
    const ids = [...new Set((values || []).map(Number))].sort((a, b) => a - b);
    if (!ids.length) throw new Error('Select at least one claimable epoch');
    if (ids.length > cap) throw new Error(`You can claim at most ${cap} epochs at once`);
    if (ids.some((id) => !Number.isSafeInteger(id) || id <= 0)) throw new Error('Invalid epoch selection');
    return ids;
}

export function nextClaimSelection(current, epochId, maxClaimEpochs) {
    const id = Number(epochId);
    const cap = Number(maxClaimEpochs);
    if (!Number.isSafeInteger(id) || id <= 0) throw new Error('Invalid epoch selection');
    if (!Number.isSafeInteger(cap) || cap <= 0) throw new Error('Creator claim batch limit is required');
    const selected = [...new Set((current || []).map(Number))];
    if (selected.includes(id)) return { selected: selected.filter((value) => value !== id), atCap: false };
    if (selected.length >= cap) return { selected, atCap: true };
    return { selected: [...selected, id], atCap: false };
}

export function requireCreatorClaimCheckTx(result) {
    if (!result?.success) throw new Error(formatError(result));
    const txHash = String(result.tx_hash || '').trim().toLowerCase();
    if (!txHash) throw new Error('Creator claim response did not include a transaction hash');
    return txHash;
}

function assertSameEarningsConfig(expected, actual) {
    for (const key of ['creatorEpochSeconds', 'originEpoch', 'originUnix', 'maxClaimEpochs']) {
        if (expected[key] !== actual[key]) throw new Error(`Creator earnings ${key} changed during pagination`);
    }
}

export async function fetchCreatorEarningsPages(creator, {
    claimableOnly = false,
    stopEpochIds = [],
} = {}) {
    const address = String(creator || '').trim().toLowerCase();
    if (!address) throw new Error('Creator address is required');
    const wanted = new Set((stopEpochIds || []).map(Number));
    const found = new Set();
    const seenCursors = new Set();
    const items = [];
    let cursor = null;
    let config = null;

    for (let page = 0; page < EARNINGS_MAX_PAGES; page += 1) {
        const params = {
            creator: address,
            limit: EARNINGS_PAGE_LIMIT,
            claimable_only: claimableOnly,
            sort: claimableOnly ? 'claim_deadline_asc' : 'epoch_desc',
            _cb: Date.now(),
        };
        if (cursor) params.cursor = cursor;
        const next = validateEarnings(await Api.get('creator/earnings', params));
        if (config) assertSameEarningsConfig(config, next);
        else config = next;
        items.push(...next.items);
        for (const item of next.items) {
            if (wanted.has(Number(item.epoch_id))) found.add(Number(item.epoch_id));
        }
        if (wanted.size > 0 && found.size === wanted.size) break;
        if (!next.hasMore) break;
        if (seenCursors.has(next.nextCursor)) throw new Error('Creator earnings cursor repeated');
        seenCursors.add(next.nextCursor);
        cursor = next.nextCursor;
        if (page === EARNINGS_MAX_PAGES - 1) {
            throw new Error('Creator earnings exceeded the pagination budget');
        }
    }
    return { ...config, items };
}

export async function waitForCreatorClaim({
    epochIds,
    txHash,
    creator,
    pollTxStatus = tx.pollTxStatus,
    fetchEarnings = fetchCreatorEarningsPages,
    sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now = () => Date.now(),
    settleTimeoutMs = CLAIM_SETTLE_TIMEOUT_MS,
    settleIntervalMs = CLAIM_SETTLE_INTERVAL_MS,
}) {
    const delivered = await pollTxStatus(txHash, {
        initialDelay: 0,
        interval: 2000,
        maxAttempts: 30,
        requireIndexed: false,
    });
    if (!delivered) throw new Error('Timed out waiting for the creator claim transaction');
    if (!delivered.success) {
        throw new Error(delivered.error_details?.message || 'Creator claim was rejected by the chain');
    }

    const deadline = now() + settleTimeoutMs;
    while (now() < deadline) {
        const data = await fetchEarnings(creator, { stopEpochIds: epochIds });
        const rows = data.items.filter((item) => epochIds.includes(Number(item.epoch_id)));
        if (rows.length === epochIds.length && rows.every((item) => item.claimed_height != null)) {
            return rows;
        }
        await sleep(settleIntervalMs);
    }
    throw new Error('The claim was accepted, but earnings indexing timed out. Please try again.');
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
    const [maxClaimEpochs, setMaxClaimEpochs] = useState(null);
    const [claimableItems, setClaimableItems] = useState([]);
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
            setMaxClaimEpochs(null);
            setClaimableItems([]);
            setLoading(false);
            return [];
        }
        if (!quiet) {
            setLoading(true);
            setError('');
        }
        try {
            const [history, claimableData] = await Promise.all([
                fetchCreatorEarningsPages(address),
                fetchCreatorEarningsPages(address, { claimableOnly: true }),
            ]);
            assertSameEarningsConfig(history, claimableData);
            setItems(history.items);
            setClaimableItems(claimableData.items);
            setCreatorEpochSeconds(history.creatorEpochSeconds);
            setOriginEpoch(history.originEpoch);
            setOriginUnix(history.originUnix);
            setMaxClaimEpochs(history.maxClaimEpochs);
            setSelected((current) => current.filter(
                (id) => claimableData.items.some((item) => Number(item.epoch_id) === id),
            ));
            console.debug('[earnings] loaded', {
                creator: address,
                epochs: history.items.length,
                claimableEpochs: claimableData.items.length,
                creatorEpochSeconds: history.creatorEpochSeconds,
                originEpoch: history.originEpoch,
                originUnix: history.originUnix,
                maxClaimEpochs: history.maxClaimEpochs,
            });
            return history.items;
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

    const claimable = useMemo(() => {
        return claimableItems.filter((item) => isCreatorEarningClaimable(item));
    }, [claimableItems]);

    const toggleEpoch = useCallback((epochId) => {
        const next = nextClaimSelection(selected, epochId, maxClaimEpochs);
        if (next.atCap) {
            setError(`You can claim at most ${maxClaimEpochs} epochs at once`);
            return;
        }
        setError('');
        setSelected(next.selected);
    }, [maxClaimEpochs, selected]);

    // `epochIds` lets the feed banner claim everything outstanding in one go,
    // while the profile panel claims whatever the user ticked.
    const claim = useCallback(async (epochIds = null) => {
        const ids = normalizeClaimEpochs(epochIds || selected, maxClaimEpochs);
        setError('');
        console.debug('[earnings] claiming', { creator: address, epochIds: ids });
        try {
            const result = await tx.claimCreatorRewards(ids);
            const txHash = requireCreatorClaimCheckTx(result);
            Api.invalidate('creator/earnings');
            await waitForCreatorClaim({
                epochIds: ids,
                txHash,
                creator: address,
                fetchEarnings: (_ignored, options) => fetchCreatorEarningsPages(address, options),
            });
            if (!mounted.current) throw new Error('Creator claim view closed before confirmation');
            await refresh(true);
            await tx.refreshBalance();
            window.dispatchEvent(new Event('creatorEarningsUpdated'));
            console.debug('[earnings] claim confirmed', { creator: address, epochIds: ids, txHash });
            return result;
        } catch (err) {
            const message = String(err?.message || err);
            setError(message);
            console.error('[earnings] claim failed', { creator: address, epochIds: ids, error: message });
            throw new Error(message);
        }
    }, [address, maxClaimEpochs, refresh, selected]);

    return {
        items,
        creatorEpochSeconds,
        originEpoch,
        originUnix,
        maxClaimEpochs,
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
