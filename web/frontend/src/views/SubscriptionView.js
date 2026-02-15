import React, { useState, useEffect, useRef } from 'react';
import { Helmet } from 'react-helmet-async';
import styled from 'styled-components';
import { useLocation } from 'react-router-dom';
import Storage from '../utils/Storage';
import { formatMirage, formatMirageCompact } from '../utils/formatters';
import Api from '../lib/api';
import { upgradeLevel as txUpgradeLevel, setAutoRenewal as txSetAutoRenewal } from '../utils/tx';
import transactionHandler from '../utils/TransactionHandler';
import Sidebar from '../components/Sidebar';
import TopBar from '../components/TopBar';
import Button from '../components/Button';
import MobileHeader from '../components/MobileHeader';
import { ContentGrid, ModernPostFeed, TabbedContainer, TabsRow, ClickableTab, ContainerBody } from '../styled/Layout';
import { tooltipStyles } from '../components/Tooltip';

const TIER_NAMES = ['Free', 'Trusted', 'Established', 'Distinguished'];
const TIER_COLORS = ['#6B7280', '#3B82F6', '#8B5CF6', '#F59E0B'];
const ADMIN_COLOR = '#EF4444';

const getTierName = (level) => {
    if (level >= 100) return 'Admin';
    return TIER_NAMES[level] || 'Free';
};

const getTierColor = (level) => {
    if (level >= 100) return ADMIN_COLOR;
    return TIER_COLORS[level] || TIER_COLORS[0];
};

const isAdmin = (level) => level >= 100;

const CurrentTierBanner = styled.div`
    background: linear-gradient(135deg, ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'} 0%, ${({ theme }) => theme?.colors?.panel || '#23272C'} 100%);
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 1.5rem;
    display: grid;
    grid-template-columns: 1fr;
    gap: 1.25rem;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    
    @media (min-width: 600px) {
        grid-template-columns: auto 1fr;
        align-items: stretch;
    }
`;

const TierSection = styled.div`
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding-right: 2rem;
    border-right: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    min-width: 180px;

    @media (max-width: 600px) {
        border-right: none;
        border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
        padding-right: 0;
        padding-bottom: 1.5rem;
        align-items: center;
        text-align: center;
    }
`;

const CurrentPlanLabel = styled.div`
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    margin-bottom: 0.5rem;
    font-weight: 600;
`;

const TierNameDisplay = styled.div`
    font-size: 1.5rem;
    font-weight: 800;
    line-height: 1.5;
    background: linear-gradient(135deg, ${props => props.$color}, ${props => props.$color}88);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    color: ${props => props.$color}; /* Fallback */
    filter: drop-shadow(0 2px 10px ${props => `${props.$color}33`});
    letter-spacing: -0.03em;
`;


const InfoSection = styled.div`
    display: flex;
    flex-direction: column;
    gap: 1rem;
    
    @media (min-width: 600px) {
        flex-direction: row;
        align-items: stretch;
        justify-content: space-between;
    }
`;

const StatusSection = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    flex: 1;
    justify-content: center;
    align-items: center;
    text-align: center;
`;

const StatusBadge = styled.div`
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.4rem 0.75rem;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 600;
    width: fit-content;
    white-space: nowrap;
    background: ${props => props.$active ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)'};
    color: ${props => props.$active ? '#22C55E' : '#EF4444'};
    border: 1px solid ${props => props.$active ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)'};
    cursor: ${props => (props.$clickable && !props.$disabled) ? 'pointer' : 'default'};
    opacity: ${props => props.$disabled ? 0.5 : 1};
    pointer-events: ${props => props.$disabled ? 'none' : 'auto'};
    transition: all 0.2s ease;
    
    &:hover {
        ${props => (props.$clickable && !props.$disabled) ? `
            background: ${props.$active ? 'rgba(34, 197, 94, 0.25)' : 'rgba(239, 68, 68, 0.25)'};
            transform: translateY(-1px);
        ` : ''}
    }
    
    &:active {
        ${props => (props.$clickable && !props.$disabled) ? 'transform: translateY(0);' : ''}
    }
`;

const StatusIndicator = styled.span`
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
    display: inline-block;
`;

const RenewalTime = styled.div`
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#AAA'};
    margin-top: 0.25rem;
`;

const TimeHighlight = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#EEE'};
    font-weight: 500;
    ${tooltipStyles('bottom-center')}
`;

const HorizontalDivider = styled.div`
    height: 1px;
    background-color: rgba(255, 255, 255, 0.1);
    width: 100%;
`;

const SectionSeparator = styled.div`
    width: 1px;
    background-color: ${({ theme }) => theme?.colors?.border || '#444'};
    align-self: stretch;
    display: none;
    @media (min-width: 600px) {
        display: block;
    }
`;

const BalanceSection = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    background: ${({ theme }) => theme?.colors?.panelAlt || '#33373C'};
    border-radius: 6px;
    padding: 0.5rem 0.75rem;
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    min-width: 180px;
    margin-left: auto;
`;

const BalanceItem = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
`;

const BalanceValueDisplay = styled.div`
    font-size: ${props => props.$small ? '0.85rem' : '1rem'};
    font-weight: 700;
    color: ${props => props.$small ? ({ theme }) => theme?.colors?.subtleText || '#AAA' : ({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    letter-spacing: -0.02em;
    text-align: right;

    span {
        font-size: 0.65rem;
        color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
        margin-left: 0.2rem;
        font-weight: normal;
    }
`;

const BalanceLabel = styled.div`
    font-size: 0.6rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 0.25rem;
    ${tooltipStyles('bottom')}
`;


const TiersGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 0.75rem;
    margin-top: 1rem;
`;

const TierCard = styled.div`
    background: ${({ theme, $isActive }) => $isActive
        ? (theme?.colors?.panelAlt || '#33373C')
        : (theme?.colors?.panel || '#23272C')};
    border: 2px solid ${props => props.$isActive
        ? props.$color
        : (props.theme?.colors?.border || '#444')};
    border-radius: 8px;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    transition: border-color 0.2s, transform 0.1s;
    
    &:hover {
        border-color: ${props => props.$color};
        transform: translateY(-2px);
    }
`;

const TierHeader = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
`;

const TierName = styled.div`
    font-size: 1rem;
    font-weight: bold;
    color: ${props => props.$color || '#FFFFFF'};
`;

const TierPrice = styled.div`
    font-size: 1.5rem;
    font-weight: bold;
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    margin: 0.5rem 0;
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 0.25rem;
    
    span {
        font-size: 0.7rem;
        color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
        font-weight: normal;
        white-space: nowrap;
    }
`;

const TierFeatures = styled.ul`
    list-style: none;
    padding: 0;
    margin: 0.5rem 0;
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    flex: 1;
    
    li {
        padding: 0.2rem 0;
        display: flex;
        align-items: center;
        gap: 0.3rem;
        
        &::before {
            content: '✓';
            color: ${props => props.$color || '#22C55E'};
            font-weight: bold;
        }
    }
`;

const TierDetailsPanel = styled.div`
    margin-top: 1.5rem;
    padding: 1.5rem;
    border-radius: 8px;
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 2px solid ${props => props.$color || 'rgba(255, 255, 255, 0.1)'};
    animation: slideDown 0.3s ease-out;

    @keyframes slideDown {
        from { 
            opacity: 0; 
            transform: translateY(-10px);
        }
        to { 
            opacity: 1; 
            transform: translateY(0);
        }
    }
`;

const TierDetailsHeader = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
`;

const TierDetailsTitle = styled.h3`
    margin: 0;
    font-size: 1.2rem;
    font-weight: 700;
    color: ${props => props.$color || '#fff'};
`;

const TierDetailsContent = styled.div`
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 1rem;
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#aaa'};
    line-height: 1.5;
`;

const TierDetailItem = styled.div`
    padding: 0.25rem 0;
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    word-wrap: break-word;
    overflow-wrap: break-word;

    &::before {
        content: '•';
        color: ${props => props.$color || 'rgba(255, 255, 255, 0.4)'};
        font-weight: bold;
        flex-shrink: 0;
        margin-top: 0.2rem;
    }
`;

const InfoText = styled.div`
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    text-align: center;
    margin-top: 1rem;
    line-height: 1.5;
`;

const Mono = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-size: 0.8rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
`;

// Static tier metadata (names and features). Fees come from blockchain.
const TIER_METADATA = [
    {
        level: 0,
        name: 'Free',
        features: [
            'Basic posting'
        ]
    },
    {
        level: 1,
        name: 'Trusted',
        features: [
            'Change username',
            'Profile biography & avatar',
            'Give basic awards'
        ]
    },
    {
        level: 2,
        name: 'Established',
        features: [
            'Eligible for moderator',
            'Profile banner',
            'Give more awards'
        ]
    },
    {
        level: 3,
        name: 'Distinguished',
        features: [
            'Maximum vote weight',
            'All profile features',
            'Give all award types'
        ]
    }
];

// Build tier display info from chain tiers and static metadata
const buildTierConfig = (chainTiers) => {
    return TIER_METADATA.map((meta, idx) => {
        const chainTier = chainTiers[idx] || {};
        const periodFeeUmirage = Number(chainTier.period_fee || 0);
        const maxContent = Number(chainTier.max_content_length || 0);
        const maxTopics = Number(chainTier.max_followed_topics || 0);
        const maxUsers = Number(chainTier.max_followed_users || 0);

        const prefixFeatures = [];
        if (meta.level === 0) {
            prefixFeatures.push('PoW for transactions');
        } else {
            prefixFeatures.push('Instant posting');
        }
        if (maxContent > 0) prefixFeatures.push(`Up to ${maxContent.toLocaleString()} characters`);
        if (maxTopics > 0 || maxUsers > 0) {
            const parts = [];
            if (maxTopics > 0) parts.push(`${maxTopics} topics`);
            if (maxUsers > 0) parts.push(`${maxUsers} users`);
            prefixFeatures.push(`Follow up to ${parts.join(' and ')}`);
        }
        const features = [...prefixFeatures, ...meta.features];

        return {
            level: meta.level,
            name: meta.name,
            periodFeeUmirage,
            features,
            chainTier
        };
    });
};

export default function SubscriptionView({ state }) {
    const location = useLocation();
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
    const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 599px)').matches);
    const txInFlightRef = useRef(false);
    const autoRenewDisplayRef = useRef(false);
    const detailsPanelRef = useRef(null);

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

    // Force-refresh chain config when visiting SubscriptionView to avoid stale tier pricing
    useEffect(() => {
        (async () => {
            try {
                const cfg = await Api.get('get_chain_config', undefined);
                if (!cfg || typeof cfg !== 'object') return;
                try { transactionHandler.cacheChainConfig(cfg); } catch (_) { }
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
                const data = await Api.get('get_user_status', { address, _cb: Date.now() });
                if (cancelled) return;
                // Persist to Storage so TransactionHandler picks up the latest user_level
                try { transactionHandler.cacheUserStatus(data); } catch (_) { }

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

        return () => { cancelled = true; };
    }, [address]);

    useEffect(() => {
        if (!isUpgrading) {
            autoRenewDisplayRef.current = autoRenew;
        }
    }, [autoRenew, isUpgrading]);

    useEffect(() => {
        if (expandedTierLevel !== null) {
            setTimeout(() => {
                detailsPanelRef.current?.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start',
                    inline: 'nearest'
                });
            }, 50);
        }
    }, [expandedTierLevel]);

    useEffect(() => {
        const mediaQuery = window.matchMedia('(max-width: 599px)');
        const handleChange = (e) => setIsMobile(e.matches);
        mediaQuery.addEventListener('change', handleChange);
        return () => mediaQuery.removeEventListener('change', handleChange);
    }, []);

    const formatTimeRemaining = (timestamp, isAutoRenew) => {
        if (!timestamp || timestamp <= 0) return null;
        const date = new Date(timestamp * 1000);
        const now = new Date();
        if (date <= now) {
            return { prefix: isAutoRenew ? null : 'Expired', highlight: null };
        }

        const diffMs = date - now;
        const hours = Math.floor(diffMs / (1000 * 60 * 60));
        const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));

        const prefix = isAutoRenew ? 'Renews in ' : 'Expiring in ';

        if (hours > 0) {
            return { prefix, highlight: `${hours} hour${hours === 1 ? '' : 's'}` };
        }

        if (minutes > 0) {
            return { prefix, highlight: `${minutes} minute${minutes === 1 ? '' : 's'}` };
        }

        return { prefix: isAutoRenew ? 'Renews soon' : 'Expiring soon', highlight: null };
    };

    const formatExactTime = (timestamp) => {
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

    const formatPeriodLabel = (minutes) => {
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
        const { expectedAutoRenew, expectedLevel } = options || {};
        const maxDurationMs = 6000; // ~2 * block time (3s)
        const pollIntervalMs = 1000;
        const deadline = Date.now() + maxDurationMs;
        let first = true;

        while (Date.now() < deadline) {
            const delayMs = first ? 1000 : pollIntervalMs;
            first = false;
            await new Promise((r) => setTimeout(r, delayMs));

            try {
                const data = await Api.get('get_user_status', { address: address || undefined, _cb: Date.now() });
                // Persist to Storage so TransactionHandler picks up the new user_level
                // (also syncs balance to TopBar via _persistUserBalance → balanceUpdated event)
                try { transactionHandler.cacheUserStatus(data); } catch (_) { }
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

                const matchesAuto =
                    typeof expectedAutoRenew === 'undefined' ||
                    Boolean(data?.auto_renew) === Boolean(expectedAutoRenew);
                const matchesLevel =
                    typeof expectedLevel === 'undefined' ||
                    Number(data?.user_level ?? 0) === Number(expectedLevel);

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
                await refreshSubscriptionFromBackend({ expectedAutoRenew: nextValue });
            } else {
                setError(result.error || (nextValue ? 'Failed to re-enable auto-renewal' : 'Failed to cancel auto-renewal'));
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

    const canAfford = (tier) => {
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
        const num = (key) => {
            const v = Number(raw[key] ?? 0);
            return Number.isFinite(v) && v > 0 ? v : 0;
        };

        const maxMods = num('max_followed_mods');
        if (maxMods) {
            details.push(`Follow up to ${maxMods} moderators.`);
        } else {
            details.push('Cannot follow moderators.');
        }

        const maxUsers = num('max_followed_users');
        if (maxUsers) {
            details.push(`Follow up to ${maxUsers} users.`);
        } else {
            details.push('Cannot follow users.');
        }

        const maxTopics = num('max_followed_topics');
        if (maxTopics) {
            details.push(`Follow up to ${maxTopics} topics.`);
        } else {
            details.push('Cannot follow topics.');
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

        const maxBlockedTopics = num('max_blocked_topics');
        if (maxBlockedTopics) {
            details.push(`Block up to ${maxBlockedTopics} topics.`);
        } else {
            details.push('Cannot block topics.');
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

        const archiveDays = num('archive_duration_days');
        if (archiveDays) {
            details.push(`Posts are archived after approximately ${archiveDays} days.`);
        } else {
            details.push('Posts are not archived.');
        }

        if (typeof raw.vote_weight === 'number' && raw.vote_weight > 0) {
            details.push(`Vote weight: ${raw.vote_weight.toFixed(2)}x.`);
        } else {
            details.push('Standard vote weight.');
        }

        if (raw.eligible_for_mod) {
            details.push('Eligible to be moderator.');
        } else {
            details.push('Ineligible to be moderator.');
        }
        if (raw.can_change_name) {
            details.push('Can change username.');
        } else {
            details.push('Cannot change username.');
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

        const awardPerms = Number(raw.award_permissions ?? 0);
        if (awardPerms > 0) {
            if (awardPerms === 1) {
                details.push('Can give basic awards.');
            } else if (awardPerms === 2) {
                details.push('Can give more awards.');
            } else if (awardPerms >= 3) {
                details.push('Can give all award types.');
            } else {
                details.push(`Can give awards (permission level ${awardPerms}).`);
            }
        } else {
            details.push('Cannot give awards.');
        }

        if (tier.level === 0) {
            details.push('Uses proof-of-work (PoW) for posts and votes.');
        } else {
            details.push('No PoW required for posts or votes while subscribed.');
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

    const handleUpgrade = async (tier) => {
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
                    setError(result.error || 'Failed to cancel auto-renewal');
                }
            } else {
                const result = await txUpgradeLevel(tier.level, tier.periodFeeUmirage);

                if (result.success || result.tx_hash) {
                    setError('');
                } else {
                    setError(result.error || 'Failed to upgrade subscription');
                }
            }

            const expectedAutoRenew = tier.level === 0 ? false : true;
            const expectedLevel = tier.level > 0 ? tier.level : undefined;
            await refreshSubscriptionFromBackend({ expectedAutoRenew, expectedLevel });
        } catch (e) {
            setError(String(e?.message || e || 'Unknown error'));
        } finally {
            txInFlightRef.current = false;
            setIsUpgrading(false);
            autoRenewDisplayRef.current = autoRenew;
        }
    };

    if (isLoading) {
        return (
            <ContentGrid>
                <Helmet>
                    <title>Subscription | Mirage</title>
                </Helmet>
                <Sidebar currentPath={location.pathname} state={state} />
                <div>
                    <TopBar state={state} />
                    <ModernPostFeed>
                        <MobileHeader />
                        <TabbedContainer>
                            <TabsRow>
                                <ClickableTab $active={true}>Subscription</ClickableTab>
                            </TabsRow>
                            <ContainerBody>
                                <Mono style={{ color: '#888' }}>Loading subscription info...</Mono>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </div>
            </ContentGrid>
        );
    }

    if (tierConfig.length === 0) {
        return (
            <ContentGrid>
                <Helmet>
                    <title>Subscription | Mirage</title>
                </Helmet>
                <Sidebar currentPath={location.pathname} state={state} />
                <div>
                    <TopBar state={state} />
                    <ModernPostFeed>
                        <MobileHeader />
                        <TabbedContainer>
                            <TabsRow>
                                <ClickableTab $active={true}>Subscription</ClickableTab>
                            </TabsRow>
                            <ContainerBody>
                                <Mono style={{ color: '#888' }}>Failed to load tier configuration from blockchain.</Mono>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </div>
            </ContentGrid>
        );
    }

    const currentColor = getTierColor(userLevel);
    const displayAutoRenew = isUpgrading ? autoRenewDisplayRef.current : autoRenew;
    const timeRemainingText = formatTimeRemaining(subscriptionExpiry, displayAutoRenew);
    const exactTime = formatExactTime(subscriptionExpiry);
    const userIsAdmin = isAdmin(userLevel);
    const periodLabel = formatPeriodLabel(subscriptionPeriodMinutes);

    return (
        <ContentGrid>
            <Helmet>
                <title>Subscription | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow>
                            <ClickableTab $active={true}>
                                Subscription
                            </ClickableTab>
                        </TabsRow>
                        <ContainerBody>
                            {!address ? (
                                <>
                                    <InfoText style={{ marginTop: '0', marginBottom: '1rem' }}>
                                        Sign in to manage your subscription.
                                    </InfoText>
                                    <TiersGrid>
                                        {tierConfig.map((tier, idx) => {
                                            const color = TIER_COLORS[idx];
                                            return (
                                                <TierCard key={tier.level} $isActive={false} $color={color}>
                                                    <TierHeader>
                                                        <TierName $color={color}>{tier.name}</TierName>
                                                    </TierHeader>
                                                    <TierPrice>
                                                        {tier.periodFeeUmirage === 0 ? (
                                                            'Free'
                                                        ) : (
                                                            <>{formatMirageCompact(tier.periodFeeUmirage)} <span>MIRAGE / {periodLabel}</span></>
                                                        )}
                                                    </TierPrice>
                                                    <TierFeatures $color={color}>
                                                        {tier.features.map((feature, i) => (
                                                            <li key={i}>{feature}</li>
                                                        ))}
                                                    </TierFeatures>
                                                    <Button
                                                        variant="link"
                                                        size="xs"
                                                        onClick={() => setExpandedTierLevel(expandedTierLevel === tier.level ? null : tier.level)}
                                                        style={{ alignSelf: 'flex-start', margin: '0.5rem 0' }}
                                                    >
                                                        {expandedTierLevel === tier.level ? 'Hide details' : 'See all details'}
                                                    </Button>
                                                </TierCard>
                                            );
                                        })}
                                    </TiersGrid>
                                    {expandedTierLevel !== null && (() => {
                                        const selectedTier = tierConfig.find(t => t.level === expandedTierLevel);
                                        if (!selectedTier) return null;
                                        const tierIdx = selectedTier.level;
                                        const tierColor = TIER_COLORS[tierIdx] || TIER_COLORS[0];
                                        const details = buildTierDetails(selectedTier, periodLabel);
                                        return (
                                            <TierDetailsPanel ref={detailsPanelRef} $color={tierColor}>
                                                <TierDetailsHeader>
                                                    <TierDetailsTitle $color={tierColor}>
                                                        {selectedTier.name} Plan - Full Details
                                                    </TierDetailsTitle>
                                                    <Button variant="ghost" size="xs" onClick={() => setExpandedTierLevel(null)}>
                                                        Close
                                                    </Button>
                                                </TierDetailsHeader>
                                                <TierDetailsContent>
                                                    {details.map((detail, i) => (
                                                        <TierDetailItem key={i} $color={tierColor}>{detail}</TierDetailItem>
                                                    ))}
                                                </TierDetailsContent>
                                            </TierDetailsPanel>
                                        );
                                    })()}
                                </>
                            ) : (
                                <>
                                    <CurrentTierBanner>
                                        <TierSection>
                                            <CurrentPlanLabel>{isMobile ? 'Active Plan' : 'Active'}</CurrentPlanLabel>
                                            <TierNameDisplay $color={currentColor}>
                                                {getTierName(userLevel)}
                                            </TierNameDisplay>
                                        </TierSection>

                                        <InfoSection>
                                            {userLevel > 0 && userLevel < 100 && (
                                                <>
                                                    <StatusSection>
                                                        <StatusBadge
                                                            $active={isUpgrading ? autoRenewDisplayRef.current : autoRenew}
                                                            $clickable={true}
                                                            $disabled={isUpgrading}
                                                            onClick={handleCancelAutoRenew}
                                                            title={
                                                                isUpgrading
                                                                    ? 'Processing subscription change...'
                                                                    : autoRenew
                                                                        ? 'Click to cancel auto-renewal'
                                                                        : 'Click to re-enable auto-renewal'
                                                            }
                                                        >
                                                            <StatusIndicator />
                                                            {isUpgrading ? 'Processing...' : (autoRenew ? 'Auto-renewing' : 'Not renewing')}
                                                        </StatusBadge>
                                                        {timeRemainingText && (
                                                            <RenewalTime>
                                                                {timeRemainingText.prefix}
                                                                {timeRemainingText.highlight && (
                                                                    <TimeHighlight data-tooltip={exactTime || ''}>
                                                                        {timeRemainingText.highlight}
                                                                    </TimeHighlight>
                                                                )}
                                                            </RenewalTime>
                                                        )}
                                                    </StatusSection>
                                                    <SectionSeparator />
                                                </>
                                            )}

                                            <BalanceSection>
                                                <BalanceItem>
                                                    <BalanceLabel data-tooltip={`Spendable wallet balance in MIRAGE.

This is what a subscription will be paid with.`}>
                                                        Balance
                                                    </BalanceLabel>
                                                    <BalanceValueDisplay>{formatMirage(balance)} <span>MIRAGE</span></BalanceValueDisplay>
                                                </BalanceItem>
                                                <HorizontalDivider />
                                                <BalanceItem>
                                                    <BalanceLabel data-tooltip={`Escrowed reserve in MIRAGE used for relayed gas and subscriptions.

Held internally by the blockchain and used to process all transactions while subscribed.

Not directly spendable and will get burned if not used.`}>
                                                        Reserve
                                                    </BalanceLabel>
                                                    <BalanceValueDisplay $small>{formatMirage(reserveFunds)} <span>MIRAGE</span></BalanceValueDisplay>
                                                </BalanceItem>
                                            </BalanceSection>
                                        </InfoSection>
                                    </CurrentTierBanner>

                                    {error && (
                                        <div style={{
                                            background: 'rgba(220, 38, 38, 0.1)',
                                            border: '1px solid #dc2626',
                                            borderRadius: '4px',
                                            padding: '0.5rem',
                                            marginBottom: '1rem',
                                            color: '#dc2626',
                                            fontSize: '0.75rem'
                                        }}>
                                            {error}
                                        </div>
                                    )}

                                    {userIsAdmin ? (
                                        <InfoText style={{ marginTop: '0' }}>
                                            Admin accounts have full access to all features and cannot be downgraded through this interface.
                                            Admin status is managed via governance proposals.
                                        </InfoText>
                                    ) : (
                                        <>
                                            <TiersGrid>
                                                {tierConfig.map((tier, idx) => {
                                                    const isActive = tier.level === userLevel;
                                                    const color = TIER_COLORS[idx];
                                                    const affordable = tier.level === 0 || canAfford(tier);

                                                    return (
                                                        <TierCard key={tier.level} $isActive={isActive} $color={color}>
                                                            <TierHeader>
                                                                <TierName $color={color}>{tier.name}</TierName>
                                                            </TierHeader>

                                                            <TierPrice>
                                                                {tier.periodFeeUmirage === 0 ? (
                                                                    'Free'
                                                                ) : (
                                                                    <>{formatMirageCompact(tier.periodFeeUmirage)} <span>MIRAGE / {periodLabel}</span></>
                                                                )}
                                                            </TierPrice>

                                                            <TierFeatures $color={color}>
                                                                {tier.features.map((feature, i) => (
                                                                    <li key={i}>{feature}</li>
                                                                ))}
                                                            </TierFeatures>
                                                            <Button
                                                                variant="link"
                                                                size="xs"
                                                                onClick={() => setExpandedTierLevel(expandedTierLevel === tier.level ? null : tier.level)}
                                                                style={{ alignSelf: 'flex-start', margin: '0.5rem 0' }}
                                                            >
                                                                See all details
                                                            </Button>

                                                            <Button
                                                                variant={isActive ? 'ghost' : 'primary'}
                                                                size="sm"
                                                                onClick={() => handleUpgrade(tier)}
                                                                disabled={isActive || isUpgrading || (!affordable && tier.level > 0)}
                                                                style={{
                                                                    marginTop: 'auto',
                                                                    ...(isActive ? {} : {
                                                                        background: `linear-gradient(135deg, ${color}, ${color}CC)`,
                                                                        borderColor: color
                                                                    })
                                                                }}
                                                            >
                                                                {isActive
                                                                    ? (isMobile ? 'Active Plan' : 'Active')
                                                                    : tier.level < userLevel
                                                                        ? 'Downgrade'
                                                                        : !affordable
                                                                            ? (isMobile ? 'Insufficient Funds' : 'No Funds')
                                                                            : 'Upgrade'}
                                                            </Button>
                                                        </TierCard>
                                                    );
                                                })}
                                            </TiersGrid>
                                            {expandedTierLevel !== null && (() => {
                                                const selectedTier = tierConfig.find(t => t.level === expandedTierLevel);
                                                if (!selectedTier) return null;
                                                const tierIdx = selectedTier.level;
                                                const tierColor = TIER_COLORS[tierIdx] || TIER_COLORS[0];
                                                const details = buildTierDetails(selectedTier, periodLabel);
                                                return (
                                                    <TierDetailsPanel ref={detailsPanelRef} $color={tierColor}>
                                                        <TierDetailsHeader>
                                                            <TierDetailsTitle $color={tierColor}>
                                                                {selectedTier.name} Plan - Full Details
                                                            </TierDetailsTitle>
                                                            <Button variant="ghost" size="xs" onClick={() => setExpandedTierLevel(null)}>
                                                                Close
                                                            </Button>
                                                        </TierDetailsHeader>
                                                        <TierDetailsContent>
                                                            {details.map((detail, i) => (
                                                                <TierDetailItem key={i} $color={tierColor}>{detail}</TierDetailItem>
                                                            ))}
                                                        </TierDetailsContent>
                                                    </TierDetailsPanel>
                                                );
                                            })()}

                                            <InfoText>
                                                Subscriptions are billed every {periodLabel} in MIRAGE tokens.
                                                Tokens are burned on payment.
                                                If renewal fails due to insufficient balance, you will be downgraded to Free.
                                            </InfoText>
                                        </>
                                    )}
                                </>
                            )}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}

