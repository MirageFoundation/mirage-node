/**
 * usePostGifts — self-contained Give-Award / Gift-Mirage / Gift-Subscription
 * state + handlers that can be mounted on ANY post card (feed / profile tab /
 * view-post), letting those flows open their modals in-place instead of
 * navigating to the author's profile.
 *
 * Mirrors the logic spread across `useViewPost` (give-award) and
 * `useProfile` (gift-mirage, gift-subscription) without pulling in their
 * broader page dependencies. The per-post state lives in the hook, so a
 * card can instantiate it lazily (guarded by `post.post_id`).
 *
 * Consumers should render the three `ConfirmDialog`-based modals from
 * `components/GiftDialogs.js` and pass the returned state/actions through.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import Api from '../utils/api';
import Storage from '../utils/Storage';
import * as tx from '../utils/tx';
import { formatMirageCompact } from '../utils/formatters';
import useBalance from './useBalance.js';

/** Award catalog — mirrors `useViewPost.AWARD_TYPES` so the dialog content
 *  stays in lock-step between the feed and post-detail views. */
export const AWARD_TYPES = [
    { name: 'quality_post', label: 'Quality Post Award', icon: '\uD83C\uDFC6' },
    { name: 'original_content', label: 'Original Content Award', icon: '\uD83D\uDCA1' },
    { name: 'based', label: 'Based AF Award', icon: '\uD83D\uDCAA' },
    { name: 'receipts', label: 'Receipts Award', icon: '\uD83C\uDFF7\uFE0F' },
];

function readChainConfig() {
    try {
        const raw = localStorage.getItem('chainConfig');
        return raw ? JSON.parse(raw) : null;
    } catch (_) {
        return null;
    }
}

function friendlyAwardError(raw) {
    const s = String(raw || '').toLowerCase();
    if (s.includes('already awarded')) return 'You already gave this post an award.';
    if (s.includes('insufficient') || s.includes('not enough')) return 'Not enough MIRAGE to give this award.';
    if (s.includes('own post') || s.includes('self-award')) return "You can't award your own post.";
    return raw || 'Something went wrong. Please try again.';
}

export default function usePostGifts({ post } = {}) {
    const postId = post?.post_id || null;
    const targetUserId = post?.user_id || null;
    const targetUsername = typeof post?.username === 'string' ? post.username.trim() : '';
    const authorLevel = Number(post?.author_level) || 0;

    // ─── Gift Mirage state ───
    const [confirmDonate, setConfirmDonate] = useState(null);
    const [donateAmountRaw, setDonateAmountRaw] = useState('10000');
    const [donatePending, setDonatePending] = useState(false);
    const [donateMessage, setDonateMessage] = useState(null);

    // ─── Gift Subscription state ───
    const [confirmGiftSub, setConfirmGiftSub] = useState(null);
    const [giftSubPending, setGiftSubPending] = useState(false);
    const [giftSubMessage, setGiftSubMessage] = useState(null);

    // ─── Give Award state ───
    const [confirmAward, setConfirmAward] = useState(null);
    const [isAwarding, setIsAwarding] = useState(false);
    const [awardMessage, setAwardMessage] = useState(null);

    // Viewer balance (drives Insufficient banners in the dialogs).
    const { displayBalance: viewerBalanceUmirage } = useBalance();

    /* Chain config may not yet be cached in localStorage when a post card
     * mounts (e.g. fresh page load on the feed). Without this reactivity
     * the `awardConfigs`/`subscription_tiers` useMemos latch empty and the
     * Give-Award dialog shows "loading…" forever. Mirrors useViewPost's
     * listener pattern: bump a trigger on `chainConfigUpdated`, kick off
     * a lazy fetch when stale. */
    const [configUpdateTrigger, setConfigUpdateTrigger] = useState(0);
    useEffect(() => {
        const handleConfigUpdate = () => setConfigUpdateTrigger(prev => prev + 1);
        window.addEventListener('chainConfigUpdated', handleConfigUpdate);
        window.addEventListener('userStatusUpdated', handleConfigUpdate);
        try {
            if (tx.needsChainConfigRefresh && tx.needsChainConfigRefresh()) {
                Api.get('get_chain_config', undefined)
                    .then(cfg => {
                        if (cfg) {
                            try { tx.cacheChainConfig(cfg); } catch (_) { }
                        }
                    })
                    .catch(() => { });
            }
        } catch (_) { /* noop */ }
        return () => {
            window.removeEventListener('chainConfigUpdated', handleConfigUpdate);
            window.removeEventListener('userStatusUpdated', handleConfigUpdate);
        };
    }, []);

    const awardConfigs = useMemo(() => {
        void configUpdateTrigger;
        const cfg = readChainConfig();
        return cfg?.award_configs || [];
    }, [configUpdateTrigger]);

    const { subFeeLabel, agentFeeLabel, subFeeUmirage, agentFeeUmirage } = useMemo(() => {
        void configUpdateTrigger;
        const cfg = readChainConfig();
        const tiers = cfg?.subscription_tiers || cfg?.tiers || [];
        const sf = Number(tiers?.[1]?.period_fee || 0);
        const af = Number(tiers?.[2]?.period_fee || 0);
        return {
            subFeeLabel: sf > 0 ? formatMirageCompact(sf) + ' MIRAGE' : null,
            agentFeeLabel: af > 0 ? formatMirageCompact(af) + ' MIRAGE' : null,
            subFeeUmirage: sf > 0 ? sf : null,
            agentFeeUmirage: af > 0 ? af : null,
        };
    }, [configUpdateTrigger]);

    const getAwardCost = useCallback((name) => {
        if (!awardConfigs || awardConfigs.length === 0) return null;
        const cfg = awardConfigs.find(c => c.name === name);
        return cfg ? Number(cfg.cost || 0) : null;
    }, [awardConfigs]);

    const viewerIsLoggedIn = () => {
        const pk = Storage.load('publicKey', '');
        return !!pk && pk !== 'guest';
    };

    // ─── Openers ─────────────────────────────────────────────────────────
    const handleGiveAward = useCallback(() => {
        if (!postId) return;
        if (!viewerIsLoggedIn()) {
            alert('Please log in to give an award');
            return;
        }
        setConfirmDonate(null);
        setConfirmGiftSub(null);
        setConfirmAward({ postId });

        // If the award configs aren't loaded yet (e.g. the boot fetch in
        // App.js failed, or the card mounted before localStorage was
        // populated), kick off a fresh `get_chain_config` right now so the
        // dialog doesn't get stuck on "Loading…". Mirrors the inline fetch
        // used by `handleGiftSubscription` below.
        try {
            const cfg = readChainConfig();
            const hasAwards = Array.isArray(cfg?.award_configs) && cfg.award_configs.length > 0;
            if (!hasAwards) {
                Api.get('get_chain_config', undefined)
                    .then(fetched => {
                        if (fetched && typeof fetched === 'object') {
                            try { tx.cacheChainConfig(fetched); } catch (_) { }
                        }
                    })
                    .catch(() => { });
            }
        } catch (_) { /* noop */ }
    }, [postId]);

    const handleGiftMirage = useCallback(() => {
        if (!targetUserId) return;
        if (!viewerIsLoggedIn()) {
            alert('Please log in to gift MIRAGE');
            return;
        }
        setConfirmGiftSub(null);
        setConfirmAward(null);
        setDonateAmountRaw('10000');
        setConfirmDonate({
            userId: targetUserId,
            postId,
            username: targetUsername || null,
        });
    }, [targetUserId, postId, targetUsername]);

    const handleGiftSubscription = useCallback(() => {
        if (!targetUserId) return;
        if (!viewerIsLoggedIn()) {
            alert('Please log in to gift a subscription');
            return;
        }
        const level = authorLevel >= 10 ? 10 : 1;
        setConfirmDonate(null);
        setConfirmAward(null);
        setConfirmGiftSub({
            userId: targetUserId,
            postId,
            level,
            username: targetUsername || null,
            loading: true,
            expiryLabel: null,
            error: null,
        });

        void (async () => {
            let cfg = readChainConfig();
            if (!cfg || !Number(cfg.subscription_period || 0)) {
                try {
                    const fetched = await Api.get('get_chain_config', undefined);
                    if (fetched && typeof fetched === 'object') {
                        try { tx.cacheChainConfig(fetched); } catch (_) { }
                        cfg = fetched;
                    }
                } catch (_) { /* noop */ }
            }
            const periodMinutes = Number(cfg?.subscription_period || 0);
            if (!periodMinutes || periodMinutes <= 0) {
                setConfirmGiftSub(prev =>
                    prev && prev.userId === targetUserId
                        ? { ...prev, loading: false, error: 'Invalid subscription period' }
                        : prev
                );
                return;
            }
            try {
                const pre = await Api.get('get_user_status', {
                    address: targetUserId,
                    _cb: Date.now(),
                });
                const currentExp = Number(pre?.subscription_expiry || 0);
                const nowSec = Math.floor(Date.now() / 1000);
                const isExtension = currentExp > nowSec;
                const base = Math.max(nowSec, currentExp);
                const expectedExp = base + periodMinutes * 60;
                const dateStr = new Date(expectedExp * 1000).toLocaleDateString(undefined, {
                    year: 'numeric', month: 'short', day: 'numeric',
                });
                const label = isExtension ? `Extend until ${dateStr}` : `Until ${dateStr}`;
                setConfirmGiftSub(prev =>
                    prev && prev.userId === targetUserId
                        ? { ...prev, loading: false, expiryLabel: label, error: null }
                        : prev
                );
            } catch (_) {
                setConfirmGiftSub(prev =>
                    prev && prev.userId === targetUserId
                        ? { ...prev, loading: false, error: 'Failed to load recipient status' }
                        : prev
                );
            }
        })();
    }, [targetUserId, postId, targetUsername, authorLevel]);

    // ─── Confirm/Cancel actions ──────────────────────────────────────────
    const cancelDonate = useCallback(() => setConfirmDonate(null), []);
    const cancelGiftSub = useCallback(() => setConfirmGiftSub(null), []);
    const cancelAward = useCallback(() => setConfirmAward(null), []);

    const confirmDonateAction = useCallback(async () => {
        const userAddress = confirmDonate?.userId;
        const targetPostId = confirmDonate?.postId;
        if (!userAddress || donatePending) return;
        const amount = parseInt(String(donateAmountRaw || '').replace(/[^\d]/g, ''), 10);
        if (!Number.isFinite(amount) || amount < 10000) {
            setDonateMessage({ type: 'error', message: 'Minimum gift is 10,000 MIRAGE' });
            setTimeout(() => setDonateMessage(null), 5000);
            setConfirmDonate(null);
            return;
        }
        try {
            setDonatePending(true);
            const result = await tx.sendTokens(userAddress, amount);
            setConfirmDonate(null);
            if (result && result.success) {
                setDonateMessage({
                    type: 'success',
                    message: `Successfully sent ${Number(amount).toLocaleString()} MIRAGE!`,
                });
            } else {
                setDonateMessage({
                    type: 'error',
                    message: `Failed: ${result?.error || 'Transaction failed'}`,
                });
            }
        } catch (error) {
            setConfirmDonate(null);
            setDonateMessage({ type: 'error', message: `Error: ${error.message || error}` });
        } finally {
            setDonatePending(false);
            setTimeout(() => setDonateMessage(null), 5000);
        }
        // Mark postId used so lint doesn't complain when we later extend
        void targetPostId;
    }, [confirmDonate, donateAmountRaw, donatePending]);

    const confirmGiftSubAction = useCallback(async () => {
        const userAddress = confirmGiftSub?.userId;
        if (!userAddress || giftSubPending) return;
        if (confirmGiftSub?.loading || confirmGiftSub?.error) return;
        const giftLevel = confirmGiftSub?.level || 1;
        const expiryLabel = confirmGiftSub?.expiryLabel || null;
        if (!expiryLabel) {
            setConfirmGiftSub(prev => prev ? { ...prev, error: 'Missing expected expiry' } : prev);
            return;
        }
        try {
            setGiftSubPending(true);
            const result = await tx.subscribe(giftLevel, 0, userAddress);
            setConfirmGiftSub(null);
            if (result && result.success) {
                const isAgent = giftLevel === 10;
                let msg = isAgent ? 'Agent subscription gifted!' : 'Subscription gifted!';
                msg += ` ${expiryLabel}`;
                setGiftSubMessage({ type: 'success', message: msg });
            } else {
                const raw = String(result?.error || 'Transaction failed');
                const friendly = raw.replace(/^HTTP \d+:\s*/i, '').replace(/^Failed:\s*/i, '');
                setGiftSubMessage({ type: 'error', message: friendly });
            }
        } catch (error) {
            setConfirmGiftSub(null);
            setGiftSubMessage({ type: 'error', message: `${error.message || error}` });
        } finally {
            setGiftSubPending(false);
            setTimeout(() => setGiftSubMessage(null), 8000);
        }
    }, [confirmGiftSub, giftSubPending]);

    const confirmAwardAction = useCallback(async (awardType) => {
        const targetPostId = confirmAward?.postId;
        if (!targetPostId || isAwarding) return;
        const costUmirage = getAwardCost(awardType);
        if (costUmirage == null) return;
        try {
            setIsAwarding(true);
            setConfirmAward(null);
            if (costUmirage > 0) {
                try { tx.adjustBalanceOptimistic(-costUmirage); } catch (_) { }
            }
            const result = await tx.giveAward(targetPostId, awardType);
            if (result && result.success) {
                const label = AWARD_TYPES.find(a => a.name === awardType)?.label || awardType;
                setAwardMessage({ type: 'success', message: `${label} given!` });
                try { tx.refreshBalance(); } catch (_) { }
            } else {
                if (costUmirage > 0) {
                    try { tx.adjustBalanceOptimistic(costUmirage); } catch (_) { }
                }
                try { tx.refreshBalance(); } catch (_) { }
                setAwardMessage({ type: 'error', message: friendlyAwardError(result?.error) });
            }
        } catch (error) {
            if (costUmirage > 0) {
                try { tx.adjustBalanceOptimistic(costUmirage); } catch (_) { }
            }
            try { tx.refreshBalance(); } catch (_) { }
            setAwardMessage({ type: 'error', message: friendlyAwardError(error?.message || String(error)) });
        } finally {
            setIsAwarding(false);
            setTimeout(() => setAwardMessage(null), 5000);
        }
    }, [confirmAward, isAwarding, getAwardCost]);

    const handleDonateAmountChange = useCallback((value) => {
        setDonateAmountRaw(String(value || '').replace(/[^\d]/g, ''));
    }, []);

    const formatDonateAmount = useCallback((value) => {
        const digits = String(value || '').replace(/[^\d]/g, '');
        if (!digits) return '';
        return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }, []);

    return {
        // Openers (wire to menu items)
        handleGiveAward,
        handleGiftMirage,
        handleGiftSubscription,

        // Dialog-driving state
        confirmDonate,
        donateAmountRaw,
        donatePending,
        donateMessage,

        confirmGiftSub,
        giftSubPending,
        giftSubMessage,

        confirmAward,
        isAwarding,
        awardMessage,

        // Confirm / cancel actions
        confirmDonateAction,
        confirmGiftSubAction,
        confirmAwardAction,
        cancelDonate,
        cancelGiftSub,
        cancelAward,

        // Amount utilities
        handleDonateAmountChange,
        formatDonateAmount,

        // Helpers for dialog contents
        viewerBalanceUmirage,
        AWARD_TYPES,
        getAwardCost,
        subFeeLabel,
        agentFeeLabel,
        subFeeUmirage,
        agentFeeUmirage,
    };
}
