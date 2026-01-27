/**
 * Quest hooks for tracking daily quests, flash quests, and rewards.
 */

import { useState, useEffect, useCallback } from 'react';
import Api from '../lib/api';
import Storage from './Storage';

/**
 * Hook to fetch and manage daily quest data.
 * 
 * @returns {Object} Quest state and actions
 */
export function useQuests() {
    const [dailyQuests, setDailyQuests] = useState([]);
    const [flashQuest, setFlashQuest] = useState(null);
    const [secondsUntilReset, setSecondsUntilReset] = useState(0);
    const [rewardMultiplier, setRewardMultiplier] = useState(1);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [suspended, setSuspended] = useState(false);
    const [disabled, setDisabled] = useState(false);
    const [initialLoadDone, setInitialLoadDone] = useState(false);

    const userAddress = Storage.load('publicKey', '');

    const fetchQuests = useCallback(async (isRefresh = false) => {
        if (!userAddress) {
            setLoading(false);
            return;
        }

        try {
            // Only show loading spinner on initial load, not refreshes
            if (!isRefresh) {
                setLoading(true);
            }
            setError(null);

            // Fetch daily quests
            const dailyResponse = await Api.get('/quests/daily', { owner: userAddress });
            
            // Check if quests system is disabled
            if (dailyResponse.disabled) {
                setDisabled(true);
                setDailyQuests([]);
                setFlashQuest(null);
                setLoading(false);
                return;
            }
            
            setDisabled(false);
            
            if (dailyResponse.suspended) {
                setSuspended(true);
                setDailyQuests([]);
                setFlashQuest(null);
            } else {
                setSuspended(false);
                const newQuests = dailyResponse.daily_quests || [];
                
                // Merge updates to preserve stable references - only update progress/completed
                setDailyQuests(prev => {
                    if (prev.length === 0 || prev.length !== newQuests.length) {
                        return newQuests;
                    }
                    // Check if quest IDs match (same quests, just updated progress)
                    const sameQuests = prev.every((q, i) => q.id === newQuests[i]?.id);
                    if (!sameQuests) {
                        return newQuests;
                    }
                    // Update only progress and completed fields
                    return prev.map((q, i) => ({
                        ...q,
                        progress: newQuests[i].progress,
                        completed: newQuests[i].completed,
                    }));
                });
                setSecondsUntilReset(dailyResponse.seconds_until_reset || 0);
                setRewardMultiplier(dailyResponse.reward_multiplier || 0);
            }

            // Fetch flash quest
            const flashResponse = await Api.get('/quests/flash', { owner: userAddress });
            if (!flashResponse.suspended && flashResponse.flash_quest) {
                const newFlash = flashResponse.flash_quest;
                // Merge flash quest updates
                setFlashQuest(prev => {
                    if (!prev || prev.id !== newFlash.id) {
                        return newFlash;
                    }
                    // Same flash quest, update progress/completed/seconds_remaining
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
            
            setInitialLoadDone(true);
        } catch (err) {
            console.error('Failed to fetch quests:', err);
            setError(err.message || 'Failed to load quests');
        } finally {
            setLoading(false);
        }
    }, [userAddress]);

    useEffect(() => {
        fetchQuests(false); // Initial load
        
        // Refresh every 5 minutes (silent refresh)
        const interval = setInterval(() => fetchQuests(true), 5 * 60 * 1000);

        // Listen for quest-relevant actions (votes, posts, comments) to refresh progress
        const handleQuestAction = () => {
            // Delay refresh to give the indexer time to process the action
            setTimeout(() => fetchQuests(true), 3000);
        };
        window.addEventListener('questActionCompleted', handleQuestAction);

        return () => {
            clearInterval(interval);
            window.removeEventListener('questActionCompleted', handleQuestAction);
        };
    }, [fetchQuests]);

    // Update countdown timer for daily reset
    useEffect(() => {
        if (secondsUntilReset <= 0) return;
        
        const interval = setInterval(() => {
            setSecondsUntilReset(prev => Math.max(0, prev - 1));
        }, 1000);
        
        return () => clearInterval(interval);
    }, [secondsUntilReset]);

    // Update countdown timer for flash quest
    useEffect(() => {
        if (!flashQuest || flashQuest.seconds_remaining <= 0) return;
        
        const interval = setInterval(() => {
            setFlashQuest(prev => {
                if (!prev) return prev;
                const newRemaining = Math.max(0, prev.seconds_remaining - 1);
                // Clear flash quest when expired
                if (newRemaining <= 0) {
                    return null;
                }
                return { ...prev, seconds_remaining: newRemaining };
            });
        }, 1000);
        
        return () => clearInterval(interval);
    }, [flashQuest?.id]); // Only re-run when flash quest changes

    return {
        dailyQuests,
        flashQuest,
        secondsUntilReset,
        rewardMultiplier,
        loading,
        error,
        suspended,
        disabled,
        refresh: fetchQuests,
    };
}

/**
 * Hook to fetch and manage pending rewards.
 * 
 * @returns {Object} Rewards state and actions
 */
export function usePendingRewards() {
    const [pendingRewards, setPendingRewards] = useState([]);
    const [totalMirage, setTotalMirage] = useState(0);
    const [totalAfterMultiplier, setTotalAfterMultiplier] = useState(0);
    const [rewardMultiplier, setRewardMultiplier] = useState(1);
    const [loading, setLoading] = useState(true);
    const [claiming, setClaiming] = useState(false);
    const [error, setError] = useState(null);
    const [suspended, setSuspended] = useState(false);
    const [claimingAvailable, setClaimingAvailable] = useState(true);

    const userAddress = Storage.load('publicKey', '');

    const fetchRewards = useCallback(async () => {
        if (!userAddress) {
            setLoading(false);
            return;
        }

        try {
            setLoading(true);
            setError(null);

            const response = await Api.get('/rewards/pending', { owner: userAddress });
            
            if (response.suspended) {
                setSuspended(true);
                setPendingRewards([]);
                setTotalMirage(0);
                setTotalAfterMultiplier(0);
            } else {
                setSuspended(false);
                setPendingRewards(response.pending_rewards || []);
                setTotalMirage(response.total_mirage || 0);
                setTotalAfterMultiplier(response.total_mirage_after_multiplier || 0);
                setRewardMultiplier(response.reward_multiplier || 0);
                setClaimingAvailable(response.claiming_available !== false);
            }
        } catch (err) {
            console.error('Failed to fetch pending rewards:', err);
            setError(err.message || 'Failed to load rewards');
        } finally {
            setLoading(false);
        }
    }, [userAddress]);

    const claimRewards = useCallback(async () => {
        if (!userAddress || claiming || totalAfterMultiplier <= 0) {
            return { success: false, error: 'nothing_to_claim' };
        }

        try {
            setClaiming(true);
            setError(null);

            const response = await Api.post('/rewards/claim', { owner: userAddress });
            
            if (response.success) {
                // Refresh rewards after successful claim
                await fetchRewards();
                return {
                    success: true,
                    rewards: response.rewards,
                    txHash: response.tx_hash,
                };
            } else {
                setError(response.error || 'Claim failed');
                return { success: false, error: response.error };
            }
        } catch (err) {
            console.error('Failed to claim rewards:', err);
            setError(err.message || 'Failed to claim rewards');
            return { success: false, error: err.message };
        } finally {
            setClaiming(false);
        }
    }, [userAddress, claiming, totalAfterMultiplier, fetchRewards]);

    useEffect(() => {
        fetchRewards();
        
        // Refresh every 2 minutes
        const interval = setInterval(fetchRewards, 2 * 60 * 1000);

        // Listen for quest-relevant actions (votes, posts, comments) to refresh rewards
        const handleQuestAction = () => {
            // Delay refresh to give the indexer time to process the action
            setTimeout(fetchRewards, 3000);
        };
        window.addEventListener('questActionCompleted', handleQuestAction);

        return () => {
            clearInterval(interval);
            window.removeEventListener('questActionCompleted', handleQuestAction);
        };
    }, [fetchRewards]);

    return {
        pendingRewards,
        totalMirage,
        totalAfterMultiplier,
        rewardMultiplier,
        loading,
        claiming,
        error,
        suspended,
        claimingAvailable,
        refresh: fetchRewards,
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

            const response = await Api.get('/achievements', { owner: userAddress });
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

export default useQuests;
