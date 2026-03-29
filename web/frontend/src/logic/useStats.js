import { useEffect, useState, useCallback } from "react";
import { useLocation } from "react-router-dom";
import Api from "../lib/api";
import { InfoIcon as TooltipInfoIcon } from "../components/Tooltip";
import { useTabs } from "./useTabs.js";

// Tier names and colors (same as SubscriptionView)
export const TIER_NAMES = {
    0: 'Free',
    1: 'Subscriber',
    10: 'Agent'
};
export const TIER_COLORS = {
    0: '#6B7280',
    1: '#F59E0B',
    10: '#EF4444'
};
export const InfoIcon = TooltipInfoIcon;
export const VALID_TABS = ['overview', 'signups', 'subscribers', 'accounts', 'rewards'];
export function useStats() {
    const location = useLocation();
    const [activeTab, setActiveTab] = useTabs('overview', VALID_TABS);
    const [stats, setStats] = useState(null);
    const [signupsData, setSignupsData] = useState(null);
    const [subscribersData, setSubscribersData] = useState(null);
    const [accountsData, setAccountsData] = useState(null);
    const [rewardsData, setRewardsData] = useState(null);
    const [expandedUsers, setExpandedUsers] = useState({});
    const [payouts, setPayouts] = useState([]);
    const [payoutsHasMore, setPayoutsHasMore] = useState(false);
    const [payoutsLoading, setPayoutsLoading] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Merge stats with analytics when both are loaded
    const mergedStats = stats;

    // Fetch reward history with pagination
    const fetchRewardHistory = useCallback(async (offset = 0, append = false) => {
        setPayoutsLoading(true);
        try {
            const data = await Api.get('get_stats', {
                tab: 'rewards_history',
                offset,
                limit: 50
            }, {
                timeoutMs: 30000
            });
            if (append) {
                setPayouts(prev => [...prev, ...(data.rewards || [])]);
            } else {
                setPayouts(data.rewards || []);
            }
            setPayoutsHasMore(data.has_more || false);
        } catch (err) {
            console.error('Failed to load reward history:', err);
        } finally {
            setPayoutsLoading(false);
        }
    }, []);

    // Fetch data based on active tab
    const fetchData = useCallback(async tab => {
        setLoading(true);
        setError(null);
        try {
            const data = await Api.get('get_stats', {
                tab
            }, {
                timeoutMs: 30000
            });
            if (tab === 'overview') {
                setStats(data);
            } else if (tab === 'signups') {
                setSignupsData(data);
            } else if (tab === 'subscribers') {
                setSubscribersData(data);
            } else if (tab === 'accounts') {
                setAccountsData(data);
            } else if (tab === 'rewards') {
                setRewardsData(data);
                // Also fetch initial reward history
                setPayouts([]);
                fetchRewardHistory(0, false);
            }
        } catch (err) {
            setError(err.message || 'Failed to load stats');
        } finally {
            setLoading(false);
        }
    }, [fetchRewardHistory]);
    useEffect(() => {
        fetchData(activeTab);
    }, [activeTab, fetchData]);
    const formatNumber = (num, digits = 0) => {
        if (num === null || num === undefined) return '0';
        if (typeof num === 'string') return num;
        return num.toLocaleString(undefined, {
            maximumFractionDigits: digits,
            minimumFractionDigits: digits
        });
    };
    const formatPercentage = (num, digits = 1) => {
        if (num === null || num === undefined) return '0%';
        const val = typeof num === 'number' ? num : parseFloat(num);
        return val.toFixed(digits) + '%';
    };
    const formatDateShort = ts => {
        if (!ts) return 'N/A';
        return new Date(ts * 1000).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric'
        });
    };
    const formatMirage = umirage => {
        if (!umirage && umirage !== 0) return '0';
        const mirage = Math.round(umirage / 1_000_000);
        return mirage.toLocaleString();
    };
    const getDAUTrend = () => {
        if (!mergedStats || !mergedStats.dau_today || !mergedStats.dau_yesterday) return null;
        if (mergedStats.dau_today > mergedStats.dau_yesterday) return 'up';
        if (mergedStats.dau_today < mergedStats.dau_yesterday) return 'down';
        return 'same';
    };
    const truncateAddress = addr => {
        if (!addr) return '';
        return `${addr.slice(0, 8)}...${addr.slice(-6)}`;
    };
    return {
        location,
        activeTab,
        setActiveTab,
        signupsData,
        subscribersData,
        accountsData,
        rewardsData,
        expandedUsers,
        setExpandedUsers,
        payouts,
        payoutsHasMore,
        payoutsLoading,
        loading,
        error,
        mergedStats,
        fetchRewardHistory,
        formatNumber,
        formatPercentage,
        formatDateShort,
        formatMirage,
        getDAUTrend,
        truncateAddress
    };
}