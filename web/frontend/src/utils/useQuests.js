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

    const userAddress = Storage.load('address', '');

    const fetchQuests = useCallback(async () => {
        if (!userAddress) {
            setLoading(false);
            return;
        }

        try {
            setLoading(true);
            setError(null);

            // Fetch daily quests
            const dailyResponse = await Api.get('/quests/daily', { owner: userAddress });
            
            if (dailyResponse.suspended) {
                setSuspended(true);
                setDailyQuests([]);
                setFlashQuest(null);
            } else {
                setSuspended(false);
                setDailyQuests(dailyResponse.daily_quests || []);
                setSecondsUntilReset(dailyResponse.seconds_until_reset || 0);
                setRewardMultiplier(dailyResponse.reward_multiplier || 0);
            }

            // Fetch flash quest
            const flashResponse = await Api.get('/quests/flash', { owner: userAddress });
            if (!flashResponse.suspended && flashResponse.flash_quest) {
                setFlashQuest(flashResponse.flash_quest);
            }
        } catch (err) {
            console.error('Failed to fetch quests:', err);
            setError(err.message || 'Failed to load quests');
        } finally {
            setLoading(false);
        }
    }, [userAddress]);

    useEffect(() => {
        fetchQuests();
        
        // Refresh every 5 minutes
        const interval = setInterval(fetchQuests, 5 * 60 * 1000);
        return () => clearInterval(interval);
    }, [fetchQuests]);

    // Update countdown timer
    useEffect(() => {
        if (secondsUntilReset <= 0) return;
        
        const interval = setInterval(() => {
            setSecondsUntilReset(prev => Math.max(0, prev - 1));
        }, 1000);
        
        return () => clearInterval(interval);
    }, [secondsUntilReset]);

    return {
        dailyQuests,
        flashQuest,
        secondsUntilReset,
        rewardMultiplier,
        loading,
        error,
        suspended,
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

    const userAddress = Storage.load('address', '');

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
        return () => clearInterval(interval);
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

    const userAddress = Storage.load('address', '');

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
