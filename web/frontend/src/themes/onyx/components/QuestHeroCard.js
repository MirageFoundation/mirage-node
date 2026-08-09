/**
 * QuestHeroCard - Displays daily quests, progress, and claimable rewards
 */

import React, { useState, useCallback, useEffect } from 'react';
import styled, { keyframes, css, useTheme } from 'styled-components';
import { useRewards } from '../../../logic/useQuests';
import Api from '../../../utils/api';
import Storage from '../../../utils/Storage';
import { requireThemeColor } from '../../../utils/themeColor';

const QuestCardContainer = styled.div`
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: ${({ $size }) => $size === 'compact' ? '4px' : '6px'};
    padding: ${({ $size }) => $size === 'compact' ? '0.4rem 0.6rem' : '0.6rem 0.9rem'};
    display: flex;
    flex-direction: column;
    gap: ${({ $size }) => $size === 'compact' ? '0.25rem' : '0.35rem'};

    @media (max-width: 1000px) {
        padding: ${({ $size }) => $size === 'compact' ? '0.35rem 0.5rem' : '0.5rem 0.75rem'};
    }

    @media (max-width: 768px) {
        border-radius: 4px;
        padding: 0.4rem 0.6rem;
    }
`;

const QuestHeader = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
`;

const QuestTitle = styled.div`
    font-size: 0.7rem;
    font-weight: 600;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    display: flex;
    align-items: center;
    gap: 0.4rem;
    line-height: 1;

    @media (max-width: 1000px) {
        font-size: 0.6rem;
    }
`;

const ResetTimer = styled.div`
    font-size: 0.6rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    background: ${({ theme }) => theme.colors.surface};
    padding: 0.15rem 0.35rem;
    border-radius: 4px;
    font-variant-numeric: tabular-nums;

    @media (max-width: 768px) {
        font-size: 0.5rem;
    }
`;

const QuestList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
`;

const QuestItem = styled.div`
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    padding: 0.4rem 0.5rem;
    background: ${({ theme, $completed }) => {
        if ($completed) {
            return theme.colors.successBg;
        }
        return theme.colors.surface;
    }};
    border-radius: 6px;
    transition: background 0.2s ease;

    @media (max-width: 768px) {
        padding: 0.35rem 0.4rem;
        gap: 0.4rem;
    }
`;

const QuestDetails = styled.div`
    flex: 1;
    min-width: 0;
`;

const QuestName = styled.div`
    font-size: 0.65rem;
    font-weight: 600;
    color: ${({ theme, $completed }) => $completed
        ? theme.colors.success
        : requireThemeColor(theme, 'text')};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;

    @media (max-width: 768px) {
        font-size: 0.55rem;
        white-space: normal;
        overflow: visible;
    }
`;

const QuestDescription = styled.div`
    font-size: 0.6rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;

    @media (max-width: 768px) {
        font-size: 0.55rem;
        white-space: normal;
        overflow: visible;
    }
`;

const QuestReward = styled.div`
    font-size: 0.5rem;
    color: ${({ theme }) => theme.colors.warning};
    font-weight: 600;

    @media (max-width: 768px) {
        font-size: 0.45rem;
    }
`;

const QuestRequirements = styled.ul`
    font-size: 0.5rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    margin: 0.2rem 0 0 0;
    padding-left: 1rem;
    list-style-type: disc;

    li {
        margin: 0.1rem 0;
    }

    @media (max-width: 768px) {
        font-size: 0.45rem;
    }
`;

const LoyaltyBonusText = styled.div`
    font-size: 0.5rem;
    color: ${({ theme }) => theme.colors.focusBorder};
    text-decoration: underline dotted;
    text-underline-offset: 2px;
    cursor: default;
    transition: opacity 0.15s ease;
    margin-top: 0.15rem;

    &:hover {
        opacity: 0.7;
    }

    @media (max-width: 768px) {
        font-size: 0.45rem;
    }
`;

const ProgressContainer = styled.div`
    width: 45px;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.15rem;
    flex-shrink: 0;

    @media (max-width: 768px) {
        width: 40px;
    }
`;

const ProgressBar = styled.div`
    width: 100%;
    height: 4px;
    background: ${({ theme }) => theme.colors.surface};
    border-radius: 2px;
    overflow: hidden;
`;

const ProgressFill = styled.div`
    height: 100%;
    width: ${props => Math.min(100, (props.$progress / props.$target) * 100)}%;
    background: ${({ theme, $completed }) => $completed ? theme.colors.success : theme.colors.focusBorder};
    border-radius: 2px;
    transition: width 0.3s ease;
`;

const ProgressText = styled.div`
    font-size: 0.5rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-variant-numeric: tabular-nums;
`;

const BalancedProgressText = styled.div`
    font-size: 0.45rem;
    font-variant-numeric: tabular-nums;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 1px;
`;

const BalancedProgressRow = styled.span`
    display: flex;
    align-items: center;
    gap: 2px;
    color: ${({ $met, theme }) => $met
        ? theme.colors.success
        : requireThemeColor(theme, 'subtleText')};
    font-weight: ${({ $met }) => $met ? '600' : '400'};
`;

const CheckMark = styled.div`
    width: 1.1rem;
    height: 1.1rem;
    background: ${({ theme }) => theme.colors.success};
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;

    &::after {
        content: '';
        width: 0.3rem;
        height: 0.18rem;
        border-left: 1.5px solid ${({ theme }) => theme.colors.bg};
        border-bottom: 1.5px solid ${({ theme }) => theme.colors.bg};
        transform: rotate(-45deg) translateY(-1px);
    }
`;

const ClaimSection = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding-top: 0.4rem;
    border-top: 1px solid ${({ theme }) => theme.colors.borderSubtle};
`;

const ClaimButton = styled.button`
    padding: 0.3rem 0.6rem;
    border: none;
    border-radius: 6px;
    font-size: 0.6rem;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.2s ease;

    ${props => props.$hasRewards ? css`
        background: ${({ theme }) => theme.colors.warning};
        color: ${({ theme }) => theme.colors.bg};

        &:hover {
            opacity: 0.85;
        }
    ` : css`
        background: ${({ theme }) => theme.colors.surface};
        color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
        cursor: not-allowed;
    `}

    &:disabled {
        cursor: not-allowed;
        opacity: 0.7;
    }

    @media (max-width: 768px) {
        padding: 0.25rem 0.5rem;
        font-size: 0.5rem;
    }
`;

const ClaimErrorMessage = styled.div`
    margin-top: 0.5rem;
    padding: 0.5rem 0.75rem;
    background: ${({ theme }) => theme.colors.dangerBg};
    border: 1px solid ${({ theme }) => theme.colors.dangerBorder};
    border-radius: 6px;
    font-size: 0.6rem;
    color: ${({ theme }) => theme.colors.danger};
    line-height: 1.4;

    @media (max-width: 768px) {
        font-size: 0.55rem;
        padding: 0.4rem 0.6rem;
    }
`;

const celebrationFadeIn = keyframes`
    0% { opacity: 0; }
    100% { opacity: 1; }
`;

const CelebrationOverlay = styled.div`
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.8);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10000;
    animation: ${celebrationFadeIn} 0.3s ease;
`;

const CelebrationContent = styled.div`
    text-align: center;
    padding: 2rem;
`;

const CelebrationTitle = styled.div`
    font-size: 1.5rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.warning};
    margin-bottom: 0.5rem;
`;

const CelebrationAmount = styled.div`
    font-size: 2.5rem;
    font-weight: 800;
    color: ${({ theme }) => theme.colors.text};
    margin-bottom: 1rem;
`;

const CelebrationClose = styled.button`
    padding: 0.75rem 2rem;
    background: ${({ theme }) => theme.colors.success};
    color: ${({ theme }) => theme.colors.bg};
    border: none;
    border-radius: 6px;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.2s ease;

    &:hover {
        opacity: 0.85;
    }
`;

const SuspendedBanner = styled.div`
    background: ${({ theme }) => theme.colors.dangerBg};
    border: 1px solid ${({ theme }) => theme.colors.dangerBorder};
    border-radius: 6px;
    padding: 0.4rem 0.6rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.danger};
    font-size: 0.6rem;
`;

const EmptyState = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.65rem;
    line-height: 1.5;

    @media (max-width: 1000px) {
        font-size: 0.55rem;
    }
`;

/**
 * Format seconds into HH:MM:SS or MM:SS
 */
function formatTime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;

    if (h > 0) {
        return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }
    return `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * Get reward display text for a quest (handles MIRAGE and invite_code rewards)
 */
function getQuestRewardDisplay(rewards, rewardMultiplier) {
    if (!rewards || !Array.isArray(rewards)) return null;

    const mirageReward = rewards.find(r => r.type === 'mirage');
    const inviteCodeReward = rewards.find(r => r.type === 'invite_code');

    if (inviteCodeReward) {
        const count = inviteCodeReward.amount || 1;
        return `+${count} Invite Code${count > 1 ? 's' : ''}`;
    }

    if (mirageReward) {
        const amount = mirageReward.amount || 0;
        const applyMultiplier = mirageReward.apply_multiplier !== false;
        const displayAmount = applyMultiplier ? Math.round(amount * rewardMultiplier) : amount;
        return `+${displayAmount.toLocaleString()} MIRAGE`;
    }

    return null;
}

/**
 * Get quest requirements as array of strings
 */
function getQuestRequirements(quest) {
    const reqs = [];
    if (quest.min_content_length) {
        reqs.push(`Min ${quest.min_content_length} characters`);
    }
    if (quest.time_spacing_minutes) {
        const mins = quest.time_spacing_minutes;
        reqs.push(mins >= 60 ? `Min ${mins / 60} hour${mins >= 120 ? 's' : ''} between each` : `Min ${mins} minute${mins === 1 ? '' : 's'} between each`);
    }
    if (quest.unique_target) {
        reqs.push('Must be different targets');
    }
    if (quest.unique_topics_min) {
        reqs.push(`At least ${quest.unique_topics_min} different topics`);
    }
    if (quest.quality_threshold) {
        reqs.push(`Needs ${quest.quality_threshold}+ upvotes`);
    }
    if (quest.action_type === 'vote' && quest.count_vote_changes === false) {
        reqs.push('New votes only (changes don\'t count)');
    }
    return reqs;
}

// Debug panel styled components
const DebugPanel = styled.div`
    margin-top: 0.5rem;
    padding: 0.5rem;
    background: ${({ theme }) => theme.colors.dangerBg};
    border: 1px solid ${({ theme }) => theme.colors.dangerBorder};
    border-radius: 6px;
    font-size: 0.55rem;
`;

const DebugTitle = styled.div`
    font-weight: 700;
    color: ${({ theme }) => theme.colors.danger};
    margin-bottom: 0.4rem;
    display: flex;
    align-items: center;
    gap: 0.3rem;
`;

const DebugRow = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.15rem 0;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
`;

const DebugLabel = styled.span`
    opacity: 0.7;
`;

const DebugValue = styled.span`
    font-weight: 600;
    font-variant-numeric: tabular-nums;
`;

const DebugButton = styled.button`
    background: ${({ $variant, theme }) =>
        $variant === 'danger' ? theme.colors.dangerBg :
            $variant === 'success' ? theme.colors.successBg :
                theme.colors.accentSubtle};
    border: 1px solid ${({ $variant, theme }) =>
        $variant === 'danger' ? theme.colors.dangerBorder :
            $variant === 'success' ? theme.colors.successBorder :
                theme.colors.focusBorder};
    color: ${({ $variant, theme }) =>
        $variant === 'danger' ? theme.colors.danger :
            $variant === 'success' ? theme.colors.success :
                theme.colors.focusBorder};
    font-size: 0.5rem;
    font-weight: 600;
    padding: 0.2rem 0.4rem;
    border-radius: 4px;
    cursor: pointer;
    transition: opacity 0.15s ease;

    &:hover:not(:disabled) {
        opacity: 0.8;
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;

const DebugButtonGroup = styled.div`
    display: flex;
    gap: 0.3rem;
    flex-wrap: wrap;
    margin-top: 0.3rem;
`;

const DebugInput = styled.input`
    width: 50px;
    padding: 0.15rem 0.25rem;
    font-size: 0.5rem;
    border: 1px solid ${({ theme }) => theme.colors.focusBorder};
    border-radius: 4px;
    background: ${({ theme }) => theme.colors.inputBackground};
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    text-align: center;

    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.focusBorder};
    }
`;

const DebugQuestRow = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.2rem 0.3rem;
    margin: 0.15rem 0;
    background: ${({ theme }) => theme.colors.surface};
    border-radius: 4px;
`;

// Collapse button
const CollapseButton = styled.button`
    background: transparent;
    border: none;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.65rem;
    font-weight: 600;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 4px;
    transition: color 0.2s ease, background 0.2s ease;
    display: flex;
    align-items: center;
    gap: 4px;

    &:hover {
        color: ${({ theme }) => requireThemeColor(theme, 'text')};
        background: ${({ theme }) => theme.colors.surface};
    }
`;

export default function QuestHeroCard({ collapsed = false, onToggleCollapse, size = 'large' }) {
    const theme = useTheme();
    const {
        dailyQuests,
        flashQuest,
        secondsUntilReset,
        rewardMultiplier,
        loading: questsLoading,
        error: questsError,
        suspended: questsSuspended,
        suspensionInfo: questsSuspensionInfo,
        disabled: questsDisabled,
        debug: debugEnabled,
        totalAfterMultiplier,
        pendingInviteCodes,
        claiming,
        claimRewards,
        claimingAvailable,
        payoutPending,
        refresh: refreshAll,
    } = useRewards();

    const [showCelebration, setShowCelebration] = useState(false);
    const [claimedAmount, setClaimedAmount] = useState(0);
    const [claimedInviteCodes, setClaimedInviteCodes] = useState(0);
    const [claimError, setClaimError] = useState(null);

    const userAddress = Storage.load('publicKey', '');

    // Debug panel state (controlled by BACKEND_DEBUG env var on backend)
    const [showDebug, setShowDebug] = useState(false);
    const [debugInfo, setDebugInfo] = useState(null);
    const [debugLoading, setDebugLoading] = useState(false);
    const [targetCompletedCount, setTargetCompletedCount] = useState('');

    const fetchDebugInfo = useCallback(async () => {
        if (!userAddress || !debugEnabled) return;
        setDebugLoading(true);
        try {
            const data = await Api.get('/rewards/debug', { owner: userAddress });
            setDebugInfo(data);
            setTargetCompletedCount(String(data.completed_count || 0));
        } catch (e) {
            console.error('Failed to fetch debug info:', e);
        } finally {
            setDebugLoading(false);
        }
    }, [userAddress, debugEnabled]);

    const debugCompleteQuest = useCallback(async (questId) => {
        if (!userAddress) return;
        try {
            await Api.post('/rewards/debug/complete', { owner: userAddress, quest_id: questId });
            await fetchDebugInfo();
            refreshAll();
        } catch (e) {
            console.error('Failed to complete quest:', e);
        }
    }, [userAddress, fetchDebugInfo, refreshAll]);

    const debugResetQuests = useCallback(async () => {
        if (!userAddress) return;
        setDebugLoading(true);
        try {
            await Api.post('/rewards/debug/reset', { owner: userAddress });
            refreshAll();
            setTimeout(async () => {
                await fetchDebugInfo();
                setDebugLoading(false);
            }, 500);
        } catch (e) {
            console.error('Failed to reset quests:', e);
            setDebugLoading(false);
        }
    }, [userAddress, fetchDebugInfo, refreshAll]);

    const debugSetCompletedCount = useCallback(async () => {
        if (!userAddress) return;
        const count = parseInt(targetCompletedCount, 10);
        if (isNaN(count) || count < 0) return;
        try {
            await Api.post('/rewards/debug/set_completed', { owner: userAddress, count });
            await fetchDebugInfo();
            refreshAll();
        } catch (e) {
            console.error('Failed to set completed count:', e);
        }
    }, [userAddress, targetCompletedCount, fetchDebugInfo, refreshAll]);

    useEffect(() => {
        if (showDebug && debugEnabled) {
            fetchDebugInfo();
        }
    }, [showDebug, debugEnabled, fetchDebugInfo]);

    const handleClaim = useCallback(async () => {
        setClaimError(null);
        const result = await claimRewards();

        if (result.success) {
            const mirageReward = result.rewards?.find(r => r.type === 'mirage');
            const amount = mirageReward?.amount || 0;

            const inviteCodeReward = result.rewards?.find(r => r.type === 'invite_code');
            const inviteCodesCount = inviteCodeReward?.count || 0;

            setClaimedAmount(amount);
            setClaimedInviteCodes(inviteCodesCount);
            setShowCelebration(true);

            refreshAll();

            if (inviteCodesCount > 0) {
                window.dispatchEvent(new CustomEvent('inviteCodesUpdated'));
            }
        } else {
            const errorMessage = result.message || result.error || 'Failed to claim rewards. Please try again later.';
            setClaimError(errorMessage);
            setTimeout(() => setClaimError(null), 10000);
        }
    }, [claimRewards, refreshAll]);

    const closeCelebration = useCallback(() => {
        setShowCelebration(false);
    }, []);

    if (questsDisabled) {
        return null;
    }

    // Show loading state only on initial load (when we have no quests yet)
    if (questsLoading && dailyQuests.length === 0) {
        return (
            <QuestCardContainer $size={size}>
                <QuestHeader>
                    <QuestTitle>
                        Daily Quests
                        {collapsed && (
                            <span style={{ fontWeight: 'normal' }}>
                                {' '}&mdash; Loading...
                            </span>
                        )}
                    </QuestTitle>
                    {onToggleCollapse && (
                        <CollapseButton onClick={onToggleCollapse}>
                            {collapsed ? 'Show' : 'Hide'}
                        </CollapseButton>
                    )}
                </QuestHeader>
                {!collapsed && (
                    <EmptyState>Loading quests...</EmptyState>
                )}
            </QuestCardContainer>
        );
    }

    // If suspended, show suspension message
    if (questsSuspended) {
        return (
            <QuestCardContainer $size={size}>
                <QuestHeader>
                    <QuestTitle>
                        Quests Suspended
                    </QuestTitle>
                    {onToggleCollapse && (
                        <CollapseButton onClick={onToggleCollapse}>
                            {collapsed ? 'Show' : 'Hide'}
                        </CollapseButton>
                    )}
                </QuestHeader>
                {!collapsed && (
                    <SuspendedBanner>
                        <div style={{ fontWeight: 700, marginBottom: '0.3rem' }}>
                            Your quest rewards have been suspended
                        </div>
                        <div style={{ fontSize: '0.65rem', fontWeight: 600 }}>
                            Reason: Attempting to game the system
                        </div>
                        {questsSuspensionInfo?.suspended_until && (
                            <div style={{ fontSize: '0.6rem', fontWeight: 600, marginTop: '0.2rem' }}>
                                {questsSuspensionInfo.suspended_until > 4000000000
                                    ? 'Permanent suspension'
                                    : `Until: ${new Date(questsSuspensionInfo.suspended_until * 1000).toISOString().replace('T', ' ').replace('Z', 'Z')}`
                                }
                            </div>
                        )}
                    </SuspendedBanner>
                )}
            </QuestCardContainer>
        );
    }

    // If error or no quests, show empty state
    if (questsError || dailyQuests.length === 0) {
        return (
            <QuestCardContainer $size={size}>
                <QuestHeader>
                    <QuestTitle>
                        Daily Quests
                        {collapsed && (
                            <span style={{ fontWeight: 'normal' }}>
                                {' '}&mdash; None available
                            </span>
                        )}
                    </QuestTitle>
                    {onToggleCollapse && (
                        <CollapseButton onClick={onToggleCollapse}>
                            {collapsed ? 'Show' : 'Hide'}
                        </CollapseButton>
                    )}
                </QuestHeader>
                {!collapsed && (
                    <EmptyState>
                        {questsError
                            ? `${typeof questsError === 'string' ? questsError : 'Unable to load quests. Please try again later.'}`
                            : 'No quests available yet. Check back soon!'}
                    </EmptyState>
                )}
            </QuestCardContainer>
        );
    }

    const hasClaimableRewards = totalAfterMultiplier > 0 || pendingInviteCodes > 0;
    const flashTarget = flashQuest?.target || 0;
    const flashProgress = flashQuest ? Math.min(flashQuest.progress || 0, flashTarget) : 0;
    const flashProgressTarget = flashTarget > 0 ? flashTarget : 1;

    return (
        <>
            <QuestCardContainer $size={size} role="region" aria-label="Daily Quests">
                <QuestHeader>
                    <QuestTitle>
                        Daily Quests
                        {collapsed && (
                            <span style={{ fontWeight: 'normal' }}>
                                {' '}&mdash; {dailyQuests.filter(q => !q.completed).length} available
                            </span>
                        )}
                        {!collapsed && (
                            <ResetTimer title="Time until daily quest reset">
                                {formatTime(secondsUntilReset)} left
                            </ResetTimer>
                        )}
                    </QuestTitle>
                    {onToggleCollapse && (
                        <CollapseButton onClick={onToggleCollapse}>
                            {collapsed ? 'Show' : 'Hide'}
                        </CollapseButton>
                    )}
                </QuestHeader>

                {!collapsed && (
                    <QuestList>
                        {dailyQuests.map(quest => {
                            const upvotes = quest.upvotes || 0;
                            const downvotes = quest.downvotes || 0;
                            const targetUpvotes = quest.target_upvotes || 0;
                            const targetDownvotes = quest.target_downvotes || 0;
                            const target = quest.target || 0;
                            const clampedProgress = Math.min(quest.progress || 0, target);
                            const progressTarget = target > 0 ? target : 1;
                            const clampedUpvotes = Math.min(upvotes, targetUpvotes);
                            const clampedDownvotes = Math.min(downvotes, targetDownvotes);
                            if (
                                quest.action_type === 'balanced_vote' &&
                                (upvotes > targetUpvotes || downvotes > targetDownvotes)
                            ) {
                                console.debug('quest.progress.clamped', {
                                    id: quest.id,
                                    upvotes,
                                    downvotes,
                                    targetUpvotes,
                                    targetDownvotes,
                                });
                            }
                            return (
                                <QuestItem key={quest.id} $completed={quest.completed}>
                                    <QuestDetails>
                                        <QuestName $completed={quest.completed}>
                                            {quest.title}
                                            <QuestReward as="span" style={{ marginLeft: '0.4rem' }}>
                                                {getQuestRewardDisplay(quest.rewards, rewardMultiplier)}
                                            </QuestReward>
                                        </QuestName>
                                        <QuestDescription>{quest.description}</QuestDescription>
                                        {getQuestRequirements(quest).length > 0 && (
                                            <QuestRequirements>
                                                {getQuestRequirements(quest).map((req, i) => (
                                                    <li key={i}>{req}</li>
                                                ))}
                                            </QuestRequirements>
                                        )}
                                    </QuestDetails>
                                    {quest.completed ? (
                                        <CheckMark aria-label="Completed" />
                                    ) : (
                                        <>
                                            <ProgressContainer>
                                                <ProgressBar>
                                                    <ProgressFill
                                                        $progress={clampedProgress}
                                                        $target={progressTarget}
                                                        $completed={quest.completed}
                                                    />
                                                </ProgressBar>
                                                {quest.action_type === 'balanced_vote' && quest.target_upvotes !== undefined ? (
                                                    <BalancedProgressText
                                                        title={`Need ${quest.target_upvotes} upvotes and ${quest.target_downvotes} downvotes`}
                                                    >
                                                        <BalancedProgressRow $met={upvotes >= targetUpvotes}>
                                                            ↑{clampedUpvotes}/{quest.target_upvotes}
                                                        </BalancedProgressRow>
                                                        <BalancedProgressRow $met={downvotes >= targetDownvotes}>
                                                            ↓{clampedDownvotes}/{quest.target_downvotes}
                                                        </BalancedProgressRow>
                                                    </BalancedProgressText>
                                                ) : (
                                                    <ProgressText>
                                                        {clampedProgress}/{quest.target}
                                                    </ProgressText>
                                                )}
                                            </ProgressContainer>
                                        </>
                                    )}
                                </QuestItem>
                            );
                        })}

                        {/* Flash quest if active */}
                        {flashQuest && flashQuest.seconds_remaining > 0 && (
                            <QuestItem $completed={flashQuest.completed} style={{ borderLeft: `2px solid ${theme.colors.warning}` }}>
                                <QuestDetails>
                                    <QuestName $completed={flashQuest.completed}>
                                        {flashQuest.title}
                                        <span style={{ color: theme.colors.warning, fontSize: '0.5rem', marginLeft: '0.3rem' }}>
                                            FLASH
                                        </span>
                                        <QuestReward as="span" style={{ marginLeft: '0.4rem' }}>
                                            {getQuestRewardDisplay(flashQuest.rewards, rewardMultiplier)}
                                        </QuestReward>
                                    </QuestName>
                                    <QuestDescription>
                                        {flashQuest.description}{!flashQuest.completed && ` • ${formatTime(flashQuest.seconds_remaining)} left`}
                                    </QuestDescription>
                                    {getQuestRequirements(flashQuest).length > 0 && (
                                        <QuestRequirements>
                                            {getQuestRequirements(flashQuest).map((req, i) => (
                                                <li key={i}>{req}</li>
                                            ))}
                                        </QuestRequirements>
                                    )}
                                </QuestDetails>
                                {flashQuest.completed ? (
                                    <CheckMark aria-label="Completed" />
                                ) : (
                                    <ProgressContainer>
                                        <ProgressBar>
                                            <ProgressFill
                                                $progress={flashProgress}
                                                $target={flashProgressTarget}
                                                $completed={flashQuest.completed}
                                            />
                                        </ProgressBar>
                                        <ProgressText>
                                            {flashProgress}/{flashQuest.target}
                                        </ProgressText>
                                    </ProgressContainer>
                                )}
                            </QuestItem>
                        )}
                    </QuestList>
                )}

                {!collapsed && (
                    <ClaimSection>
                        <div>
                            <LoyaltyBonusText
                                as="div"
                                title="Loyalty multiplier increases from 1.0x to 5.0x over your first 50 completed quests"
                                style={{ marginTop: 0, fontSize: '0.55rem', fontWeight: 600 }}
                            >
                                {rewardMultiplier.toFixed(2)}x loyalty multiplier
                            </LoyaltyBonusText>
                        </div>
                        <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                            <ClaimButton
                                onClick={handleClaim}
                                disabled={!hasClaimableRewards || claiming || !claimingAvailable || payoutPending}
                                $hasRewards={hasClaimableRewards && claimingAvailable && !payoutPending}
                                title={payoutPending ? 'A previous payout is still being confirmed on chain' : !claimingAvailable ? 'Reward distribution is not yet configured' : undefined}
                            >
                                {claiming ? 'Claiming...' : payoutPending ? 'Confirming Payout...' : !claimingAvailable ? 'Coming Soon' : hasClaimableRewards ? 'Claim Rewards' : 'Complete Quests'}
                            </ClaimButton>
                        </div>
                    </ClaimSection>
                )}
                {claimError && !collapsed && (
                    <ClaimErrorMessage>
                        {claimError}
                    </ClaimErrorMessage>
                )}

                {/* Debug panel - only shows when BACKEND_DEBUG=true in backend.env */}
                {!collapsed && debugEnabled && (
                    <div style={{ marginTop: '0.5rem' }}>
                        <DebugButton onClick={() => setShowDebug(!showDebug)}>
                            {showDebug ? 'Hide Debug' : 'Debug'}
                        </DebugButton>
                        {showDebug && (
                            <DebugPanel>
                                <DebugTitle>Quest Debug Panel</DebugTitle>
                                {debugLoading ? (
                                    <div>Loading...</div>
                                ) : debugInfo ? (
                                    <>
                                        <DebugRow>
                                            <DebugLabel>Total Completed Quests:</DebugLabel>
                                            <DebugValue>{debugInfo.completed_count}</DebugValue>
                                        </DebugRow>
                                        <DebugRow>
                                            <DebugLabel>Unused Invite Codes:</DebugLabel>
                                            <DebugValue>{debugInfo.unused_invite_codes}</DebugValue>
                                        </DebugRow>
                                        <div style={{ marginTop: '0.4rem', borderTop: `1px solid ${theme.colors.dangerBorder}`, paddingTop: '0.4rem' }}>
                                            <DebugLabel>invite_recruit:</DebugLabel>
                                            <DebugRow>
                                                <span>
                                                    Has codes: {debugInfo.invite_recruit?.has_codes ? 'Yes' : 'No'} |
                                                    Chance: {debugInfo.invite_recruit?.chance}
                                                </span>
                                                <DebugValue style={{ color: debugInfo.invite_recruit?.assigned ? theme.colors.success : theme.colors.muted }}>
                                                    {debugInfo.invite_recruit?.assigned ? 'ASSIGNED TODAY' : 'not assigned'}
                                                </DebugValue>
                                            </DebugRow>
                                        </div>
                                        <div style={{ marginTop: '0.3rem' }}>
                                            <DebugLabel>invite_earner:</DebugLabel>
                                            <DebugRow>
                                                <span>
                                                    Earned: {debugInfo.invite_earner?.completed || 0} |
                                                    Next milestone: {debugInfo.invite_earner?.next_milestone}
                                                    {debugInfo.invite_earner?.milestone_reached ? ' (reached)' : ''} |
                                                    Chance: {debugInfo.invite_earner?.chance}
                                                </span>
                                                <DebugValue style={{ color: debugInfo.invite_earner?.assigned ? theme.colors.success : theme.colors.muted }}>
                                                    {debugInfo.invite_earner?.assigned ? 'ASSIGNED TODAY' : 'not assigned'}
                                                </DebugValue>
                                            </DebugRow>
                                        </div>
                                        <div style={{ marginTop: '0.4rem', borderTop: `1px solid ${theme.colors.dangerBorder}`, paddingTop: '0.4rem' }}>
                                            <DebugLabel>Today's Quests:</DebugLabel>
                                            {debugInfo.today_quests?.map(q => (
                                                <DebugQuestRow key={q.quest_id}>
                                                    <span>
                                                        {q.quest_id} ({q.progress})
                                                        {q.completed && ' (done)'}
                                                    </span>
                                                    {!q.completed && (
                                                        <DebugButton
                                                            $variant="success"
                                                            onClick={() => debugCompleteQuest(q.quest_id)}
                                                        >
                                                            Complete
                                                        </DebugButton>
                                                    )}
                                                </DebugQuestRow>
                                            ))}
                                        </div>
                                        <div style={{ marginTop: '0.4rem', borderTop: `1px solid ${theme.colors.dangerBorder}`, paddingTop: '0.4rem' }}>
                                            <DebugLabel>Set completed count:</DebugLabel>
                                            <DebugRow>
                                                <DebugInput
                                                    type="number"
                                                    value={targetCompletedCount}
                                                    onChange={e => setTargetCompletedCount(e.target.value)}
                                                    min="0"
                                                />
                                                <DebugButton onClick={debugSetCompletedCount}>
                                                    Set Count
                                                </DebugButton>
                                            </DebugRow>
                                        </div>
                                        <DebugButtonGroup>
                                            <DebugButton $variant="danger" onClick={debugResetQuests}>
                                                Reset Today's Quests
                                            </DebugButton>
                                            <DebugButton onClick={fetchDebugInfo}>
                                                Refresh Debug
                                            </DebugButton>
                                        </DebugButtonGroup>
                                    </>
                                ) : (
                                    <div>No debug info available</div>
                                )}
                            </DebugPanel>
                        )}
                    </div>
                )}
            </QuestCardContainer>

            {/* Celebration overlay */}
            {showCelebration && (
                <CelebrationOverlay onClick={closeCelebration}>
                    <CelebrationContent onClick={e => e.stopPropagation()}>
                        <CelebrationTitle>Rewards Claimed!</CelebrationTitle>
                        {claimedAmount > 0 && (
                            <CelebrationAmount>
                                +{Math.round(claimedAmount / 1_000_000).toLocaleString()} MIRAGE
                            </CelebrationAmount>
                        )}
                        {claimedInviteCodes > 0 && (
                            <CelebrationAmount style={{ fontSize: claimedAmount > 0 ? '1.5rem' : '2.5rem' }}>
                                +{claimedInviteCodes} Invite Code{claimedInviteCodes > 1 ? 's' : ''}
                            </CelebrationAmount>
                        )}
                        <CelebrationClose onClick={closeCelebration}>
                            Done
                        </CelebrationClose>
                    </CelebrationContent>
                </CelebrationOverlay>
            )}
        </>
    );
}
