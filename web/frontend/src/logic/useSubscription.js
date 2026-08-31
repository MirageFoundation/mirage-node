import { useState, useEffect, useRef } from "react";
import { useTheme } from "styled-components";
import { useLocation, useNavigate } from "react-router-dom";
import Storage from "../utils/Storage";
import { formatMirageCompact } from "../utils/formatters";
import Api from "../utils/api";
import { subscribe as txSubscribe, setAutoRenewal as txSetAutoRenewal } from "../utils/tx";
import { usePendingSubscribes } from "./usePendingSubscribes.js";
import transactionHandler from "../utils/TransactionHandler";
import { formatError } from "../utils/errorMessages";
import { readReturnTo } from "../utils/returnTo";
export const TIER_NAMES = {
    0: 'Free',
    1: 'Subscriber',
};
export const TIER_COLORS = {
    0: '#6B7280',
    1: '#F59E0B',
};
export const ADMIN_COLOR = '#EF4444';
export const getTierName = level => {
    if (level >= 100) return 'Admin';
    if (level >= 1) return 'Subscriber';
    return 'Free';
};
export const getTierColor = level => {
    if (level >= 100) return ADMIN_COLOR;
    if (level >= 1) return TIER_COLORS[1];
    return TIER_COLORS[0];
};
export const isAdmin = level => level >= 100;
// Paid subscribers and admins may lead/join curator teams (matches types.CanCurate).
export const canCurate = (effectivePaid, level) => Boolean(effectivePaid) || Number(level) >= 100;
export const TIERS = [{
    level: 0,
    name: 'Free'
}, {
    level: 1,
    name: 'Subscriber'
}];

// Map user level to the chain `tiers` array index.
// Free=0, Subscriber=1, Admin(>=100)=2 — see LevelToTierIndex in params.go.
export const levelToTierIndex = level => {
    const n = Number(level);
    if (n === 0) return 0;
    if (n === 1) return 1;
    if (n >= 100) return 2;
    return -1;
};
export const buildTierConfig = chainTiers => {
    return TIERS.map(meta => {
        const tierIdx = levelToTierIndex(meta.level);
        const chainTier = tierIdx >= 0 && tierIdx < chainTiers.length ? chainTiers[tierIdx] : {};
        const periodFeeUmirage = Number(chainTier.period_fee || 0);
        const num = key => {
            const v = Number(chainTier[key] ?? 0);
            return Number.isFinite(v) && v > 0 ? v : 0;
        };
        const maxContent = num('max_content_length');
        const maxCommunities = num('max_joined_communities');
        const maxUsers = num('max_followed_users');
        const maxDailyRelays = num('max_daily_relays');
        const followParts = [];
        if (maxCommunities > 0) followParts.push(`${maxCommunities} communities`);
        if (maxUsers > 0) followParts.push(`${maxUsers} users`);
        let features;
        if (meta.level === 0) {
            features = [
                'PoW for every transaction',
                maxContent > 0 && `Post up to ${maxContent.toLocaleString()} characters`,
                followParts.length > 0 && `Join or follow up to ${followParts.join(' and ')}`,
                'Basic posting',
            ];
        } else {
            if (maxDailyRelays < 1) {
                throw new Error(`subscriber tier missing max_daily_relays`);
            }
            features = [
                `${maxDailyRelays.toLocaleString()} transactions per day without PoW`,
                'Lead curator teams',
                maxContent > 0 && `Post up to ${maxContent.toLocaleString()} characters`,
                followParts.length > 0 && `Join or follow up to ${followParts.join(' and ')}`,
                'Profile biography, avatar & banner',
            ];
        }
        return {
            level: meta.level,
            name: meta.name,
            periodFeeUmirage,
            features: features.filter(Boolean),
            chainTier
        };
    });
};
export function useSubscription({
    state
}) {
    const location = useLocation();
    const navigate = useNavigate();
    const address = Storage.load('publicKey', '') || '';
    const [userLevel, setUserLevel] = useState(0);
    const [subscriptionExpiry, setSubscriptionExpiry] = useState(0);
    const [autoRenew, setAutoRenew] = useState(false);
    const [balance, setBalance] = useState(0);
    const [reserveFunds, setReserveFunds] = useState(0);
    const [isLoading, setIsLoading] = useState(true);
    const [isUpgrading, setIsUpgrading] = useState(false);
    const [error, setError] = useState('');
    const [subscriptionPeriodMinutes, setSubscriptionPeriodMinutes] = useState(0);
    const [tierConfig, setTierConfig] = useState([]);
    const [expandedTierLevel, setExpandedTierLevel] = useState(null);
    const [pendingTier, setPendingTier] = useState(null);
    const {
        isPending: isSubscribePending,
        formatStatus: formatSubscribeStatus
    } = usePendingSubscribes();
    const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 599px)').matches);
    const txInFlightRef = useRef(false);
    const autoRenewDisplayRef = useRef(false);
    const detailsPanelRef = useRef(null);
    const detailsScrollTimeoutRef = useRef(null);
    const theme = useTheme();
    const loadTierConfigFromStorage = () => {
        try {
            const raw = localStorage.getItem('chainConfig');
            if (!raw) return;
            const cached = JSON.parse(raw);
            if (Array.isArray(cached.tiers) && cached.tiers.length > 0) {
                setTierConfig(buildTierConfig(cached.tiers));
            }
            if (typeof cached.subscription_period === 'number') {
                setSubscriptionPeriodMinutes(Number(cached.subscription_period) || 0);
            }
        } catch (_) { }
    };

    // Load tiers from cached chain config (and keep in sync with chainConfigUpdated events)
    useEffect(() => {
        loadTierConfigFromStorage();
        const onConfigUpdated = () => {
            loadTierConfigFromStorage();
        };
        window.addEventListener('chainConfigUpdated', onConfigUpdated);
        return () => window.removeEventListener('chainConfigUpdated', onConfigUpdated);
    }, []);

    // Refresh chain config when visiting SubscriptionView
    useEffect(() => {
        (async () => {
            try {
                const cfg = await Api.get('get_chain_config', undefined);
                if (!cfg || typeof cfg !== 'object') return;
                try {
                    transactionHandler.cacheChainConfig(cfg);
                } catch (_) { }
            } catch (_) { }
        })();
    }, []);

    // Load user-specific subscription data
    useEffect(() => {
        let cancelled = false;
        if (!address) {
            setIsLoading(false);
            return;
        }
        (async () => {
            try {
                const data = await Api.get('get_user_status', {
                    address,
                    _cb: Date.now()
                });
                if (cancelled) return;
                // Persist to Storage so TransactionHandler picks up the latest user_level
                try {
                    transactionHandler.cacheUserStatus(data);
                } catch (_) { }
                if (typeof data.user_level === 'number') {
                    setUserLevel(data.user_level);
                }
                if (typeof data.subscription_expiry === 'number') {
                    setSubscriptionExpiry(data.subscription_expiry);
                }
                if (typeof data.auto_renew === 'boolean') {
                    setAutoRenew(data.auto_renew);
                    autoRenewDisplayRef.current = data.auto_renew;
                }
                // Balance from API response (cacheUserStatus above also syncs to TopBar via useBalance hook)
                const balanceVal = data.balance !== undefined ? data.balance : data.user_balance;
                if (typeof balanceVal !== 'undefined') {
                    setBalance(Number(balanceVal) || 0);
                }
                if (typeof data.reserve_funds !== 'undefined') {
                    setReserveFunds(Number(data.reserve_funds) || 0);
                }
            } catch (err) {
                if (!cancelled) {
                    console.error('Failed to load subscription info:', err);
                }
            } finally {
                if (!cancelled) {
                    setIsLoading(false);
                }
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [address]);
    useEffect(() => {
        if (!isUpgrading) {
            autoRenewDisplayRef.current = autoRenew;
        }
    }, [autoRenew, isUpgrading]);
    useEffect(() => {
        if (expandedTierLevel !== null) {
            if (detailsScrollTimeoutRef.current) {
                clearTimeout(detailsScrollTimeoutRef.current);
            }
            detailsScrollTimeoutRef.current = setTimeout(() => {
                detailsPanelRef.current?.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start',
                    inline: 'nearest'
                });
                detailsScrollTimeoutRef.current = null;
            }, 50);
        }
        return () => {
            if (detailsScrollTimeoutRef.current) {
                clearTimeout(detailsScrollTimeoutRef.current);
                detailsScrollTimeoutRef.current = null;
            }
        };
    }, [expandedTierLevel]);
    useEffect(() => {
        const mediaQuery = window.matchMedia('(max-width: 599px)');
        const handleChange = e => setIsMobile(e.matches);
        mediaQuery.addEventListener('change', handleChange);
        return () => mediaQuery.removeEventListener('change', handleChange);
    }, []);
    const formatTimeRemaining = (timestamp, isAutoRenew) => {
        if (!timestamp || timestamp <= 0) return null;
        const date = new Date(timestamp * 1000);
        const now = new Date();
        if (date <= now) {
            return {
                prefix: isAutoRenew ? null : 'Expired',
                highlight: null
            };
        }
        const diffMs = date - now;
        const hours = Math.floor(diffMs / (1000 * 60 * 60));
        const minutes = Math.floor(diffMs % (1000 * 60 * 60) / (1000 * 60));
        const prefix = isAutoRenew ? 'Renews in ' : 'Expiring in ';
        if (hours > 0) {
            return {
                prefix,
                highlight: `${hours} hour${hours === 1 ? '' : 's'}`
            };
        }
        if (minutes > 0) {
            return {
                prefix,
                highlight: `${minutes} minute${minutes === 1 ? '' : 's'}`
            };
        }
        return {
            prefix: isAutoRenew ? 'Renews soon' : 'Expiring soon',
            highlight: null
        };
    };
    const formatExactTime = timestamp => {
        if (!timestamp || timestamp <= 0) return null;
        const date = new Date(timestamp * 1000);
        return date.toLocaleString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        });
    };
    const formatPeriodLabel = minutes => {
        const m = Number(minutes || 0);
        if (!isFinite(m) || m <= 0) return 'period';
        const MIN_PER_HOUR = 60;
        const MIN_PER_DAY = 1440;
        const MIN_PER_WEEK = 10080;
        const MIN_PER_MONTH = 43200;
        const MIN_PER_YEAR = 525600;
        if (m % MIN_PER_YEAR === 0) {
            const y = m / MIN_PER_YEAR;
            return y === 1 ? 'year' : `${y} years`;
        }
        if (m % MIN_PER_MONTH === 0) {
            const mo = m / MIN_PER_MONTH;
            return mo === 1 ? 'month' : `${mo} months`;
        }
        if (m % MIN_PER_WEEK === 0) {
            const w = m / MIN_PER_WEEK;
            return w === 1 ? 'week' : `${w} weeks`;
        }
        if (m % MIN_PER_DAY === 0) {
            const d = m / MIN_PER_DAY;
            return d === 1 ? 'day' : `${d} days`;
        }
        if (m % MIN_PER_HOUR === 0) {
            const h = m / MIN_PER_HOUR;
            return h === 1 ? 'hour' : `${h} hours`;
        }
        return m === 1 ? 'minute' : `${m} minutes`;
    };
    const refreshSubscriptionFromBackend = async (options = {}) => {
        const {
            expectedAutoRenew,
            expectedLevel
        } = options || {};
        const maxDurationMs = 6000; // ~2 * block time (3s)
        const pollIntervalMs = 1000;
        const deadline = Date.now() + maxDurationMs;
        let first = true;
        while (Date.now() < deadline) {
            const delayMs = first ? 1000 : pollIntervalMs;
            first = false;
            await new Promise(r => setTimeout(r, delayMs));
            try {
                const data = await Api.get('get_user_status', {
                    address: address || undefined,
                    _cb: Date.now()
                });
                // Persist to Storage so TransactionHandler picks up the new user_level
                // (also syncs balance to TopBar via _persistUserBalance → balanceUpdated event)
                try {
                    transactionHandler.cacheUserStatus(data);
                } catch (_) { }
                const balanceVal = data?.balance !== undefined ? data.balance : data?.user_balance;
                if (balanceVal !== undefined) {
                    setBalance(Number(balanceVal) || 0);
                }
                // Only overwrite optimistic state when backend matches the expected outcome
                const fetchedLevel = data?.user_level !== undefined ? Number(data.user_level) || 0 : undefined;
                const fetchedAuto = data?.auto_renew !== undefined ? Boolean(data.auto_renew) : undefined;
                if (data?.subscription_expiry !== undefined) {
                    setSubscriptionExpiry(Number(data.subscription_expiry) || 0);
                }
                if ((typeof expectedLevel === 'undefined' && typeof fetchedLevel !== 'undefined') || fetchedLevel === expectedLevel) {
                    setUserLevel(fetchedLevel || 0);
                }
                if ((typeof expectedAutoRenew === 'undefined' && typeof fetchedAuto !== 'undefined') || fetchedAuto === expectedAutoRenew) {
                    setAutoRenew(Boolean(fetchedAuto));
                }
                if (data?.reserve_funds !== undefined) {
                    setReserveFunds(Number(data.reserve_funds) || 0);
                }
                const matchesAuto = typeof expectedAutoRenew === 'undefined' || Boolean(data?.auto_renew) === Boolean(expectedAutoRenew);
                const matchesLevel = typeof expectedLevel === 'undefined' || Number(data?.user_level ?? 0) === Number(expectedLevel);
                if (matchesAuto && matchesLevel) {
                    break;
                }
            } catch (_) {
                // Ignore and retry until deadline
            }
        }
    };
    const handleToggleAutoRenew = async () => {
        if (txInFlightRef.current) return;
        if (isSubscribePending(address)) return;
        txInFlightRef.current = true;
        setError('');
        autoRenewDisplayRef.current = autoRenew;
        setIsUpgrading(true);
        try {
            const nextValue = !autoRenew;
            const result = await txSetAutoRenewal(nextValue);
            if (result.success || result.tx_hash) {
                setAutoRenew(nextValue);
                setError('');
                await refreshSubscriptionFromBackend({
                    expectedAutoRenew: nextValue
                });
            } else {
                setError(formatError(result));
            }
        } catch (e) {
            setError(String(e?.message || e || 'Unknown error'));
        } finally {
            txInFlightRef.current = false;
            setIsUpgrading(false);
            autoRenewDisplayRef.current = autoRenew;
        }
    };
    const handleCancelAutoRenew = handleToggleAutoRenew;
    const canAfford = tier => {
        return balance >= tier.periodFeeUmirage;
    };
    const buildTierDetails = (tier, periodLabel) => {
        const details = [];
        if (tier.periodFeeUmirage === 0) {
            details.push('Free tier. No MIRAGE needed to keep this plan active.');
        } else {
            const price = `${formatMirageCompact(tier.periodFeeUmirage)} MIRAGE`;
            details.push(`Subscription price: ${price} every ${periodLabel}.`);
        }
        const raw = tier.chainTier || {};
        const num = key => {
            const v = Number(raw[key] ?? 0);
            return Number.isFinite(v) && v > 0 ? v : 0;
        };
        const maxUsers = num('max_followed_users');
        if (maxUsers) {
            details.push(`Follow up to ${maxUsers} users.`);
        } else {
            details.push('Cannot follow users.');
        }
        const maxCommunities = num('max_joined_communities');
        if (maxCommunities) {
            details.push(`Join up to ${maxCommunities} communities.`);
        } else {
            details.push('Cannot join communities.');
        }
        const maxBlockedUsers = num('max_blocked_users');
        if (maxBlockedUsers) {
            details.push(`Block up to ${maxBlockedUsers} users.`);
        } else {
            details.push('Cannot block users.');
        }
        const maxBlockedPosts = num('max_blocked_posts');
        if (maxBlockedPosts) {
            details.push(`Block up to ${maxBlockedPosts} posts.`);
        } else {
            details.push('Cannot block posts.');
        }
        const maxBlockedCommunities = num('max_blocked_communities');
        if (maxBlockedCommunities) {
            details.push(`Block up to ${maxBlockedCommunities} communities.`);
        } else {
            details.push('Cannot block communities.');
        }
        const maxTitle = num('max_title_length');
        if (maxTitle) {
            details.push(`Post titles up to ${maxTitle.toLocaleString()} characters.`);
        } else {
            details.push('Post titles not available.');
        }
        const maxContent = num('max_content_length');
        if (maxContent) {
            details.push(`Post content up to ${maxContent.toLocaleString()} characters.`);
        } else {
            details.push('Post content not available.');
        }
        const editingMinutes = num('editing_time_mins');
        if (editingMinutes) {
            details.push(`Edit posts for up to ${editingMinutes} minutes after publishing.`);
        } else {
            details.push('Cannot edit posts after publishing.');
        }
        if (tier.level >= 1) {
            details.push('Can lead curator teams.');
        }
        if (raw.can_have_biography) {
            details.push('Profile biography available.');
        } else {
            details.push('Profile biography not available.');
        }
        if (raw.can_have_avatar) {
            details.push('Profile avatar available.');
        } else {
            details.push('Profile avatar not available.');
        }
        if (raw.can_have_banner) {
            details.push('Profile banner available.');
        } else {
            details.push('Profile banner not available.');
        }
        const maxDailyRelays = num('max_daily_relays');
        if (tier.level === 0) {
            details.push('Uses proof-of-work (PoW) for every transaction.');
        } else if (maxDailyRelays > 0) {
            details.push(`${maxDailyRelays.toLocaleString()} transactions per day without PoW.`);
        } else {
            throw new Error(`paid tier ${tier.level} missing max_daily_relays`);
        }
        const seen = new Set();
        const deduped = [];
        for (const item of details) {
            const key = String(item || '').trim().toLowerCase();
            if (!key || seen.has(key)) continue;
            seen.add(key);
            deduped.push(item);
        }
        return deduped;
    };
    // Open the confirmation dialog for a tier change. The actual tx is
    // not submitted until the user confirms via `confirmUpgrade`. This
    // gives the user immediate visual feedback (dialog appears instantly)
    // and a chance to back out before any chain interaction.
    const requestUpgrade = tier => {
        if (txInFlightRef.current) return;
        if (!tier || tier.level === userLevel) return;
        if (tier.level > 0 && !canAfford(tier)) {
            setError(`Insufficient balance. You need ${formatMirageCompact(tier.periodFeeUmirage)} MIRAGE.`);
            return;
        }
        setError('');
        setPendingTier(tier);
    };
    const cancelUpgrade = () => {
        if (isUpgrading) return;
        setPendingTier(null);
    };
    const confirmUpgrade = async () => {
        const tier = pendingTier;
        if (!tier) return;
        await handleUpgrade(tier);
        setPendingTier(null);
    };
    const handleUpgrade = async tier => {
        if (txInFlightRef.current) return;
        if (tier.level === userLevel) return;
        if (tier.level > 0 && !canAfford(tier)) {
            setError(`Insufficient balance. You need ${formatMirageCompact(tier.periodFeeUmirage)} MIRAGE.`);
            return;
        }
        txInFlightRef.current = true;
        setError('');
        autoRenewDisplayRef.current = autoRenew;
        setIsUpgrading(true);
        try {
            if (tier.level === 0) {
                // Downgrade to free at expiry by disabling auto-renewal
                const result = await txSetAutoRenewal(false);
                if (result.success || result.tx_hash) {
                    setError('');
                } else {
                    setError(formatError(result));
                }
            } else {
                const result = await txSubscribe(tier.level, tier.periodFeeUmirage);
                if (result.success || result.tx_hash) {
                    setError('');
                } else {
                    setError(formatError(result));
                }
            }
            const expectedAutoRenew = tier.level === 0 ? false : true;
            const expectedLevel = tier.level > 0 ? tier.level : undefined;
            await refreshSubscriptionFromBackend({
                expectedAutoRenew,
                expectedLevel
            });
            // Paid upgrade from a deep link (?next=) — send the user back once
            // status has refreshed so the destination page sees effective_paid.
            if (tier.level > 0) {
                const next = readReturnTo(location.search);
                if (next) {
                    console.debug('[subscription] returning after subscribe', { next });
                    navigate(next, { replace: true });
                }
            }
        } catch (e) {
            setError(String(e?.message || e || 'Unknown error'));
        } finally {
            txInFlightRef.current = false;
            setIsUpgrading(false);
            autoRenewDisplayRef.current = autoRenew;
        }
    };
    return {
        location,
        address,
        userLevel,
        subscriptionExpiry,
        autoRenew,
        balance,
        reserveFunds,
        isLoading,
        isUpgrading,
        error,
        subscriptionPeriodMinutes,
        tierConfig,
        expandedTierLevel,
        setExpandedTierLevel,
        isSubscribePending,
        formatSubscribeStatus,
        isMobile,
        autoRenewDisplayRef,
        detailsPanelRef,
        theme,
        formatTimeRemaining,
        formatExactTime,
        formatPeriodLabel,
        handleCancelAutoRenew,
        canAfford,
        buildTierDetails,
        handleUpgrade,
        pendingTier,
        requestUpgrade,
        confirmUpgrade,
        cancelUpgrade
    };
}