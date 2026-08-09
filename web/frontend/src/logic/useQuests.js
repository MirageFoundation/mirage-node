/**
 * Quest hooks for tracking daily quests, flash quests, and rewards.
 *
 * All data is fetched via a single GET /api/rewards/summary call.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import Api from '../utils/api';
import Storage from '../utils/Storage';
import { readBootstrapStashAfterBootstrap } from '../utils/bootstrapStash';
import { signPlainPayload } from '../utils/signPlain';
import { formatError } from '../utils/errorMessages';

const OPTIMISTIC_CLAIM_KEY = 'user_balance_optimistic_claim';
const OPTIMISTIC_CLAIM_TTL_MS = 45000;

/**
 * Combined hook – fetches daily quests, flash quest, and pending rewards
 * in a single /api/rewards/summary call.
 */
export function useRewards() {
    // --- quest state ---
    const [dailyQuests, setDailyQuests] = useState([]);
    const [flashQuest, setFlashQuest] = useState(null);
    const [secondsUntilReset, setSecondsUntilReset] = useState(0);
    const [rewardMultiplier, setRewardMultiplier] = useState(1);
    const [suspended, setSuspended] = useState(false);
    const [suspensionInfo, setSuspensionInfo] = useState(null);
    const [disabled, setDisabled] = useState(false);
    const [debug, setDebug] = useState(false);

    // --- rewards state ---
    const [pendingRewards, setPendingRewards] = useState([]);
    const [totalMirage, setTotalMirage] = useState(0);
    const [totalAfterMultiplier, setTotalAfterMultiplier] = useState(0);
    const [pendingInviteCodes, setPendingInviteCodes] = useState(0);
    const [claimingAvailable, setClaimingAvailable] = useState(true);
    // A payout the node has reserved but not yet settled. Claiming again while
    // it is open would ask for a second payment for the same rewards.
    const [payoutPending, setPayoutPending] = useState(false);

    // --- shared state ---
    const [loading, setLoading] = useState(true);
    const [claiming, setClaiming] = useState(false);
    const [error, setError] = useState(null);
    const questActionTimeoutsRef = useRef(new Set());
    const flashQuestId = flashQuest ? flashQuest.id : null;
    const flashQuestHasRemaining = !!(flashQuest && flashQuest.seconds_remaining > 0);

    const userAddress = Storage.load('publicKey', '');

    // ---- optimistic claim helpers ----
    const setOptimisticClaimBalance = useCallback((umirageAmount) => {
        const amount = Number(umirageAmount);
        if (!Number.isFinite(amount) || amount <= 0) return;
        const deltaUmirage = Math.round(amount);
        const baseRaw = Storage.load('user_balance', null);
        const baseNum = Number(baseRaw);
        const payload = {
            delta_umirage: deltaUmirage,
            base_umirage: Number.isFinite(baseNum) ? baseNum : null,
            expires_at_ms: Date.now() + OPTIMISTIC_CLAIM_TTL_MS,
        };
        Storage.save(OPTIMISTIC_CLAIM_KEY, payload);
        console.log('[useRewards] Optimistic claim balance set', payload);
    }, []);

    const clearOptimisticClaimBalance = useCallback((reason) => {
        Storage.remove(OPTIMISTIC_CLAIM_KEY);
        console.log(`[useRewards] Optimistic claim balance cleared: ${reason}`);
    }, []);

    // First-mount stash consumed flag — only the very first fetchAll() reads
    // from /api/bootstrap's snapshot. Refreshes (claim, manual reload) always
    // hit /api/rewards/summary.
    const bootstrapStashConsumedRef = useRef(false);

    // ---- single fetch ----
    const fetchAll = useCallback(async (isRefresh = false) => {
        if (!userAddress) {
            setLoading(false);
            return;
        }

        try {
            if (!isRefresh) setLoading(true);
            setError(null);

            let res = null;
            if (!isRefresh && !bootstrapStashConsumedRef.current) {
                bootstrapStashConsumedRef.current = true;
                res = await readBootstrapStashAfterBootstrap('bootstrap_rewards_summary', userAddress);
            }
            if (!res) {
                res = await Api.get('/rewards/summary', { owner: userAddress });
            }
            setPayoutPending(res.payout_pending === true);

            // --- disabled ---
            if (res.disabled) {
                setDisabled(true);
                setDebug(res.debug === true);
                setDailyQuests([]);
                setFlashQuest(null);
                setPendingRewards([]);
                setTotalMirage(0);
                setTotalAfterMultiplier(0);
                setPendingInviteCodes(0);
                setLoading(false);
                return;
            }
            setDisabled(false);
            setDebug(res.debug === true);

            // --- suspended ---
            if (res.suspended) {
                setSuspended(true);
                setSuspensionInfo(res.suspension || null);
                setDailyQuests([]);
                setFlashQuest(null);
                setPendingRewards([]);
                setTotalMirage(0);
                setTotalAfterMultiplier(0);
                setPendingInviteCodes(0);
                setLoading(false);
                return;
            }
            setSuspended(false);

            // --- daily quests (merge for stable references) ---
            const newQuests = res.daily_quests || [];
            setDailyQuests(prev => {
                if (prev.length === 0 || prev.length !== newQuests.length) return newQuests;
                const sameQuests = prev.every((q, i) => q.id === newQuests[i]?.id);
                if (!sameQuests) return newQuests;
                return prev.map((q, i) => ({
                    ...q,
                    progress: newQuests[i].progress,
                    completed: newQuests[i].completed,
                    upvotes: newQuests[i].upvotes,
                    downvotes: newQuests[i].downvotes,
                }));
            });

            setSecondsUntilReset(res.seconds_until_reset || 0);
            setRewardMultiplier(res.reward_multiplier || 1);

            // --- flash quest (merge) ---
            const newFlash = res.flash_quest;
            if (newFlash) {
                setFlashQuest(prev => {
                    if (!prev || prev.id !== newFlash.id) return newFlash;
                    return {
                        ...prev,
                        progress: newFlash.progress,
                        completed: newFlash.completed,
                        seconds_remaining: newFlash.seconds_remaining,
                    };
                });
            } else {
                setFlashQuest(null);
            }

            // --- pending rewards ---
            setPendingRewards(res.pending_rewards || []);
            setTotalMirage(res.total_mirage || 0);
            setTotalAfterMultiplier(res.total_mirage_after_multiplier || 0);
            setPendingInviteCodes(res.pending_invite_codes || 0);
            setClaimingAvailable(res.claiming_available !== false);
        } catch (err) {
            console.error('Failed to fetch rewards summary:', err);
            setError(err.message || 'Failed to load quests');
        } finally {
            setLoading(false);
        }
    }, [userAddress]);

    // ---- claim ----
    const claimRewards = useCallback(async () => {
        const hasClaimable = totalAfterMultiplier > 0 || pendingInviteCodes > 0;
        if (payoutPending) {
            return { success: false, error: 'payout_pending', message: formatError('payout_pending') };
        }
        if (!userAddress || claiming || !hasClaimable) {
            return { success: false, error: 'nothing_to_claim' };
        }

        try {
            setClaiming(true);
            setError(null);
            setOptimisticClaimBalance(totalAfterMultiplier);
            try { window.dispatchEvent(new CustomEvent('optimisticBalanceUpdate')); } catch (_) { }

            const sig = await signPlainPayload(
                (ts, n) => `rewards_claim:${userAddress.toLowerCase()}:${ts}:${n}`
            );
            const response = await Api.post('/rewards/claim', { owner: userAddress, ...sig });

            if (response.success) {
                await fetchAll(true);
                return {
                    success: true,
                    rewards: response.rewards,
                    txHash: response.tx_hash,
                };
            } else if (response.error_code === 'payout_pending') {
                // The node has committed to this payment and may already have
                // broadcast it. Lock claiming until it settles rather than
                // inviting the user to ask for the same rewards again.
                setPayoutPending(true);
                clearOptimisticClaimBalance('payout_pending');
                await fetchAll(true);
                return { success: false, error: 'payout_pending', message: formatError('payout_pending') };
            } else {
                clearOptimisticClaimBalance('claim_failed');
                // Don't setError() here — claim failures are returned to the caller
                // and displayed via claimError in the component. Setting the shared
                // error state would hide the quests UI with a generic "load" error.
                return { success: false, error: response.error, message: response.message };
            }
        } catch (err) {
            console.error('Failed to claim rewards:', err);
            clearOptimisticClaimBalance('claim_error');
            let errorCode = err.message;
            let errorMessage = null;
            try {
                const jsonMatch = err.message?.match(/\{[\s\S]*\}/);
                if (jsonMatch) {
                    const parsed = JSON.parse(jsonMatch[0]);
                    errorCode = parsed.error || err.message;
                    errorMessage = parsed.message;
                }
            } catch (_) { /* ignore parse errors */ }
            // Don't setError() — return to caller for display via claimError
            return { success: false, error: errorCode, message: errorMessage };
        } finally {
            setClaiming(false);
        }
    }, [userAddress, claiming, payoutPending, totalAfterMultiplier, pendingInviteCodes, fetchAll, setOptimisticClaimBalance, clearOptimisticClaimBalance]);

    // ---- polling & event listeners ----
    useEffect(() => {
        const timeoutSet = questActionTimeoutsRef.current;
        fetchAll(false);

        // Refresh every 2 minutes
        const interval = setInterval(() => fetchAll(true), 2 * 60 * 1000);

        const handleQuestAction = (e) => {
            console.log('[useRewards] questActionCompleted event received:', e?.detail);
            const timeoutId = setTimeout(async () => {
                timeoutSet.delete(timeoutId);
                console.log('[useRewards] Refreshing after action...');
                await fetchAll(true);
                console.log('[useRewards] Refresh complete');
            }, 5000);
            timeoutSet.add(timeoutId);
        };
        window.addEventListener('questActionCompleted', handleQuestAction);

        return () => {
            clearInterval(interval);
            window.removeEventListener('questActionCompleted', handleQuestAction);
            timeoutSet.forEach((timeoutId) => clearTimeout(timeoutId));
            timeoutSet.clear();
        };
    }, [fetchAll]);

    useEffect(() => {
        if (!payoutPending) return undefined;
        const interval = setInterval(() => fetchAll(true), 3000);
        return () => clearInterval(interval);
    }, [payoutPending, fetchAll]);

    // ---- countdown: daily reset ----
    useEffect(() => {
        if (secondsUntilReset <= 0) return;
        const interval = setInterval(() => {
            setSecondsUntilReset(prev => Math.max(0, prev - 1));
        }, 1000);
        return () => clearInterval(interval);
    }, [secondsUntilReset]);

    // ---- countdown: flash quest ----
    useEffect(() => {
        if (!flashQuestHasRemaining) return;
        const interval = setInterval(() => {
            setFlashQuest(prev => {
                if (!prev) return prev;
                const newRemaining = Math.max(0, prev.seconds_remaining - 1);
                if (newRemaining <= 0) return null;
                return { ...prev, seconds_remaining: newRemaining };
            });
        }, 1000);
        return () => clearInterval(interval);
    }, [flashQuestId, flashQuestHasRemaining]);

    return {
        // quest data
        dailyQuests,
        flashQuest,
        secondsUntilReset,
        rewardMultiplier,
        suspended,
        suspensionInfo,
        disabled,
        debug,
        // rewards data
        pendingRewards,
        totalMirage,
        totalAfterMultiplier,
        pendingInviteCodes,
        claimingAvailable,
        claiming,
        payoutPending,
        // shared
        loading,
        error,
        refresh: fetchAll,
        claimRewards,
    };
}

/**
 * Hook to fetch achievements.
 *
 * @returns {Object} Achievements state
 */
export function useAchievements() {
    const [achievements, setAchievements] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const userAddress = Storage.load('publicKey', '');

    const fetchAchievements = useCallback(async () => {
        if (!userAddress) {
            setLoading(false);
            return;
        }

        try {
            setLoading(true);
            setError(null);

            const response = await Api.get('/rewards/achievements', { owner: userAddress });
            setAchievements(response.achievements || []);
        } catch (err) {
            console.error('Failed to fetch achievements:', err);
            setError(err.message || 'Failed to load achievements');
        } finally {
            setLoading(false);
        }
    }, [userAddress]);

    useEffect(() => {
        fetchAchievements();
    }, [fetchAchievements]);

    return {
        achievements,
        loading,
        error,
        refresh: fetchAchievements,
    };
}

export default useRewards;
