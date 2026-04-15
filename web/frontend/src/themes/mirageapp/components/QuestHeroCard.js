/**
 * QuestHeroCard - Displays daily quests, progress, and claimable rewards
 */

import React, { useState, useCallback, useEffect } from 'react';
import styled, { css, keyframes } from 'styled-components';
import { useRewards } from '../../../logic/useQuests';
import Api from '../../../utils/api';
import Storage from '../../../utils/Storage';
import { requireThemeColor } from '../../../utils/themeColor';

/** Quest section — no outer border; parent SidebarBox provides the box frame */
const QuestCardContainer = styled.div`
    box-sizing: border-box;
    background: ${({ theme }) => requireThemeColor(theme, 'panel')};
    display: flex;
    flex-direction: column;
`;

/** Tinted header strip at top of widget — entire bar is clickable to toggle */
const QuestHeader = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
    padding: 0.3rem 0.5rem;
    background: ${({ theme }) => requireThemeColor(theme, 'panelAlt')};
    border-bottom: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    cursor: pointer;
    user-select: none;

    &:hover > * {
        color: ${({ theme }) => requireThemeColor(theme, 'link')};
    }
`;

const QuestTitle = styled.div`
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.35rem;
    line-height: 1.2;
`;

const ResetTimer = styled.span`
    font-size: 0.6rem;
    font-weight: 400;
    text-transform: none;
    letter-spacing: 0;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-variant-numeric: tabular-nums;
`;

/** Body area inside the widget (below the header strip) */
const QuestBody = styled.div`
    padding: 0.35rem 0.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
`;

const QuestList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0;
`;

const QuestItem = styled.div`
    display: flex;
    align-items: flex-start;
    gap: 0.4rem;
    padding: 0.25rem 0;
`;

const QuestDetails = styled.div`
    flex: 1;
    min-width: 0;
`;

const QuestName = styled.div`
    font-size: 0.7rem;
    font-weight: 400;
    color: ${({ theme, $completed }) => $completed
        ? requireThemeColor(theme, 'subtleText')
        : requireThemeColor(theme, 'link')};
    text-decoration: ${({ $completed }) => $completed ? 'line-through' : 'none'};
    line-height: 1.35;
`;

const QuestDescription = styled.div`
    font-size: 0.6rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    line-height: 1.3;
`;

const QuestReward = styled.span`
    font-size: 0.6rem;
    color: ${({ theme }) => requireThemeColor(theme, 'voteUp')};
    font-weight: 700;
`;

const FlashBadge = styled.span`
    margin-left: 0.3rem;
    font-size: 0.5rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: ${({ theme }) => requireThemeColor(theme, 'voteUp')};
`;

const QuestRequirements = styled.ul`
    font-size: 0.5rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    margin: 0.15rem 0 0 0;
    padding-left: 0.9rem;
    list-style-type: disc;

    li {
        margin: 0.05rem 0;
    }

    @media (max-width: 768px) {
    }
`;

const LoyaltyBonusText = styled.div`
    font-size: 0.6rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    cursor: default;
`;

const ProgressContainer = styled.div`
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    justify-content: flex-start;
    flex-shrink: 0;
    min-width: 2.5rem;
`;

const ProgressText = styled.div`
    font-size: 0.6rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-variant-numeric: tabular-nums;
`;

const BalancedProgressText = styled.div`
    font-size: 0.55rem;
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
        ? requireThemeColor(theme, 'buttonSuccessBorder')
        : requireThemeColor(theme, 'subtleText')};
    font-weight: ${({ $met }) => $met ? '600' : '400'};
`;

const CheckMark = styled.span`
    flex-shrink: 0;
    color: ${({ theme }) => requireThemeColor(theme, 'buttonSuccessBorder')};
    font-size: 0.65rem;
    font-weight: 700;
    line-height: 1.35;
`;

const ClaimSection = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
    padding-top: 0.2rem;
    border-top: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
`;

const ClaimButton = styled.button`
    padding: 0.15rem 0.4rem;
    border-radius: 2px;
    font-size: 0.6rem;
    font-weight: 700;
    font-family: inherit;
    cursor: pointer;
    transition: background 0.15s ease;

    ${props => props.$hasRewards ? css`
        background: ${({ theme }) => requireThemeColor(theme, 'panelAlt')};
        color: ${({ theme }) => requireThemeColor(theme, 'link')};
        border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};

        &:hover:not(:disabled) {
            color: ${({ theme }) => requireThemeColor(theme, 'linkHover')};
            text-decoration: underline;
        }
    ` : css`
        background: ${({ theme }) => requireThemeColor(theme, 'panelAlt')};
        color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
        border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
        cursor: not-allowed;
    `}

    &:disabled {
        cursor: not-allowed;
        opacity: 0.7;
    }
`;

const ClaimErrorMessage = styled.div`
    padding: 0.3rem 0.5rem;
    font-size: 0.6rem;
    color: ${({ theme }) => requireThemeColor(theme, 'buttonDangerBorder')};
    line-height: 1.3;
`;

// Celebration animation
const confettiAnimation = keyframes`
    0% { transform: translateY(0) rotate(0deg); opacity: 1; }
    100% { transform: translateY(400px) rotate(720deg); opacity: 0; }
`;

const celebrationFadeIn = keyframes`
    0% { opacity: 0; transform: scale(0.8); }
    100% { opacity: 1; transform: scale(1); }
`;

const countUpAnimation = keyframes`
    0% { transform: scale(1); }
    50% { transform: scale(1.1); }
    100% { transform: scale(1); }
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

const CelebrationEmoji = styled.div`
    font-size: 4rem;
    margin-bottom: 1rem;
    animation: ${countUpAnimation} 0.5s ease infinite;
`;

const CelebrationTitle = styled.div`
    font-size: 1.5rem;
    font-weight: 700;
    color: #f59e0b;
    margin-bottom: 0.5rem;
`;

const CelebrationAmount = styled.div`
    font-size: 2.5rem;
    font-weight: 800;
    color: white;
    margin-bottom: 1rem;
`;

const CelebrationClose = styled.button`
    padding: 0.75rem 2rem;
    background: #22c55e;
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 1rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.2s ease;

    &:hover {
        background: #16a34a;
    }
`;

const ConfettiPiece = styled.div`
    position: absolute;
    width: 10px;
    height: 10px;
    background: ${props => props.$color};
    top: -10px;
    left: ${props => props.$left}%;
    animation: ${confettiAnimation} ${props => props.$duration}s linear forwards;
    animation-delay: ${props => props.$delay}s;
`;

const SuspendedBanner = styled.div`
    text-align: left;
    color: ${({ theme }) => requireThemeColor(theme, 'buttonDangerBorder')};
    font-size: 0.6rem;
    line-height: 1.35;
`;

const EmptyState = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.6rem;
    line-height: 1.4;
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
    // For vote quests, show if vote changes don't count
    if (quest.action_type === 'vote' && quest.count_vote_changes === false) {
        reqs.push('New votes only (changes don\'t count)');
    }
    return reqs;
}

const CONFETTI_COLORS = ['#f59e0b', '#22c55e', '#3b82f6', '#ec4899', '#8b5cf6'];

// Debug panel styled components
const DebugPanel = styled.div`
    margin-top: 0.5rem;
    padding: 0.5rem;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(239, 68, 68, 0.1)'
        : 'rgba(239, 68, 68, 0.15)'};
    border: 1px dashed rgba(239, 68, 68, 0.5);
    border-radius: 6px;
    font-size: 0.55rem;
`;

const DebugTitle = styled.div`
    font-weight: 700;
    color: #ef4444;
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
    background: ${({ $variant }) =>
        $variant === 'danger' ? 'rgba(239, 68, 68, 0.2)' :
            $variant === 'success' ? 'rgba(34, 197, 94, 0.2)' :
                'rgba(59, 130, 246, 0.2)'};
    border: 1px solid ${({ $variant }) =>
        $variant === 'danger' ? 'rgba(239, 68, 68, 0.5)' :
            $variant === 'success' ? 'rgba(34, 197, 94, 0.5)' :
                'rgba(59, 130, 246, 0.5)'};
    color: ${({ $variant }) =>
        $variant === 'danger' ? '#ef4444' :
            $variant === 'success' ? '#22c55e' :
                '#3b82f6'};
    font-size: 0.5rem;
    font-weight: 600;
    padding: 0.2rem 0.4rem;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.15s ease;

    &:hover:not(:disabled) {
        opacity: 0.8;
        transform: scale(1.02);
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
    border: 1px solid rgba(59, 130, 246, 0.5);
    border-radius: 4px;
    background: ${({ theme }) => theme.name === 'light' ? 'white' : 'rgba(0,0,0,0.3)'};
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    text-align: center;

    &:focus {
        outline: none;
        border-color: #3b82f6;
    }
`;

const DebugQuestRow = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.2rem 0.3rem;
    margin: 0.15rem 0;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0,0,0,0.03)'
        : 'rgba(255,255,255,0.03)'};
    border-radius: 4px;
`;


export default function QuestHeroCard({ collapsed = false, onToggleCollapse }) {
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
            // Find the MIRAGE reward amount
            const mirageReward = result.rewards?.find(r => r.type === 'mirage');
            const amount = mirageReward?.amount || 0;

            // Find invite code rewards
            const inviteCodeReward = result.rewards?.find(r => r.type === 'invite_code');
            const inviteCodesCount = inviteCodeReward?.count || 0;

            setClaimedAmount(amount);
            setClaimedInviteCodes(inviteCodesCount);
            setShowCelebration(true);

            // Refresh data
            refreshAll();

            // If invite codes were claimed, notify other components to refresh
            if (inviteCodesCount > 0) {
                window.dispatchEvent(new CustomEvent('inviteCodesUpdated'));
            }
        } else {
            // Show user-friendly message from backend if available, otherwise show error code
            const errorMessage = result.message || result.error || 'Failed to claim rewards. Please try again later.';
            setClaimError(errorMessage);
            // Clear error after 10 seconds
            setTimeout(() => setClaimError(null), 10000);
        }
    }, [claimRewards, refreshAll]);

    const closeCelebration = useCallback(() => {
        setShowCelebration(false);
    }, []);

    // If quests system is disabled, don't render anything
    if (questsDisabled) {
        return null;
    }

    // Show loading state only on initial load (when we have no quests yet)
    if (questsLoading && dailyQuests.length === 0) {
        return (
            <QuestCardContainer>
                <QuestHeader onClick={onToggleCollapse}>
                    <QuestTitle>
                        Daily Quests
                        {collapsed && <ResetTimer>{' '}— loading...</ResetTimer>}
                    </QuestTitle>
                </QuestHeader>
                {!collapsed && (
                    <QuestBody><EmptyState>Loading quests...</EmptyState></QuestBody>
                )}
            </QuestCardContainer>
        );
    }

    // If suspended, show suspension message
    if (questsSuspended) {
        return (
            <QuestCardContainer>
                <QuestHeader onClick={onToggleCollapse}>
                    <QuestTitle>Quests Suspended</QuestTitle>
                </QuestHeader>
                {!collapsed && (
                    <QuestBody>
                        <SuspendedBanner>
                            Your quest rewards have been suspended. Reason: Attempting to game the system.
                            {questsSuspensionInfo?.suspended_until && (
                                <span>
                                    {' '}{questsSuspensionInfo.suspended_until > 4000000000
                                        ? '(Permanent)'
                                        : `Until: ${new Date(questsSuspensionInfo.suspended_until * 1000).toISOString().replace('T', ' ').replace('Z', 'Z')}`
                                    }
                                </span>
                            )}
                        </SuspendedBanner>
                    </QuestBody>
                )}
            </QuestCardContainer>
        );
    }

    // If error or no quests, show empty state
    if (questsError || dailyQuests.length === 0) {
        return (
            <QuestCardContainer>
                <QuestHeader onClick={onToggleCollapse}>
                    <QuestTitle>
                        Daily Quests
                        {collapsed && <ResetTimer>{' '}— none available</ResetTimer>}
                    </QuestTitle>
                </QuestHeader>
                {!collapsed && (
                    <QuestBody>
                        <EmptyState>
                            {questsError
                                ? (typeof questsError === 'string' ? questsError : 'Unable to load quests. Please try again later.')
                                : 'No quests available yet. Check back soon!'}
                        </EmptyState>
                    </QuestBody>
                )}
            </QuestCardContainer>
        );
    }

    const hasClaimableRewards = totalAfterMultiplier > 0 || pendingInviteCodes > 0;
    const flashTarget = flashQuest?.target || 0;
    const flashProgress = flashQuest ? Math.min(flashQuest.progress || 0, flashTarget) : 0;

    return (
        <>
            <QuestCardContainer role="region" aria-label="Daily Quests">
                <QuestHeader onClick={onToggleCollapse}>
                    <QuestTitle>
                        Daily Quests
                        {collapsed && (
                            <ResetTimer>
                                {' '}— {dailyQuests.filter(q => !q.completed).length} available
                            </ResetTimer>
                        )}
                        {!collapsed && (
                            <ResetTimer title="Time until daily quest reset">
                                {formatTime(secondsUntilReset)} left
                            </ResetTimer>
                        )}
                    </QuestTitle>
                </QuestHeader>

                {!collapsed && <QuestBody>
                    <QuestList>
                        {dailyQuests.map(quest => {
                            const upvotes = quest.upvotes || 0;
                            const downvotes = quest.downvotes || 0;
                            const targetUpvotes = quest.target_upvotes || 0;
                            const targetDownvotes = quest.target_downvotes || 0;
                            const target = quest.target || 0;
                            const clampedProgress = Math.min(quest.progress || 0, target);
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
                                <QuestItem key={quest.id}>
                                    <QuestDetails>
                                        <QuestName $completed={quest.completed}>
                                            {quest.title}{' '}
                                            <QuestReward>{getQuestRewardDisplay(quest.rewards, rewardMultiplier)}</QuestReward>
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
                                        <CheckMark aria-label="Completed">✓</CheckMark>
                                    ) : (
                                        <ProgressContainer>
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
                                    )}
                                </QuestItem>
                            );
                        })}

                        {/* Flash quest if active */}
                        {flashQuest && flashQuest.seconds_remaining > 0 && (
                            <QuestItem>
                                <QuestDetails>
                                    <QuestName $completed={flashQuest.completed}>
                                        {flashQuest.title}
                                        <FlashBadge>flash</FlashBadge>{' '}
                                        <QuestReward>{getQuestRewardDisplay(flashQuest.rewards, rewardMultiplier)}</QuestReward>
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
                                    <CheckMark aria-label="Completed">✓</CheckMark>
                                ) : (
                                    <ProgressContainer>
                                        <ProgressText>
                                            {flashProgress}/{flashQuest.target}
                                        </ProgressText>
                                    </ProgressContainer>
                                )}
                            </QuestItem>
                        )}
                    </QuestList>

                    <ClaimSection>
                        <LoyaltyBonusText
                            title="Loyalty multiplier increases from 1.0x to 5.0x over your first 50 completed quests"
                        >
                            {rewardMultiplier.toFixed(2)}x loyalty multiplier
                        </LoyaltyBonusText>
                        <ClaimButton
                            onClick={handleClaim}
                            disabled={!hasClaimableRewards || claiming || !claimingAvailable}
                            $hasRewards={hasClaimableRewards && claimingAvailable}
                            title={!claimingAvailable ? 'Reward distribution is not yet configured' : undefined}
                        >
                            {claiming ? 'claiming...' : !claimingAvailable ? 'coming soon' : hasClaimableRewards ? 'claim rewards' : 'complete quests'}
                        </ClaimButton>
                    </ClaimSection>

                    {claimError && (
                        <ClaimErrorMessage>{claimError}</ClaimErrorMessage>
                    )}

                    {/* Debug panel - only shows when BACKEND_DEBUG=true in backend.env */}
                    {debugEnabled && (
                        <div style={{ marginTop: '0.3rem' }}>
                            <DebugButton onClick={() => setShowDebug(!showDebug)}>
                                {showDebug ? '🔧 Hide Debug' : '🔧 Debug'}
                            </DebugButton>
                            {showDebug && (
                                <DebugPanel>
                                    <DebugTitle>🔧 Quest Debug Panel</DebugTitle>
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
                                            <div style={{ marginTop: '0.4rem', borderTop: '1px dashed rgba(239,68,68,0.3)', paddingTop: '0.4rem' }}>
                                                <DebugLabel>invite_recruit:</DebugLabel>
                                                <DebugRow>
                                                    <span>
                                                        Has codes: {debugInfo.invite_recruit?.has_codes ? 'Yes' : 'No'} |
                                                        Chance: {debugInfo.invite_recruit?.chance}
                                                    </span>
                                                    <DebugValue style={{ color: debugInfo.invite_recruit?.assigned ? '#22c55e' : '#6b7280' }}>
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
                                                        {debugInfo.invite_earner?.milestone_reached ? ' ✓' : ''} |
                                                        Chance: {debugInfo.invite_earner?.chance}
                                                    </span>
                                                    <DebugValue style={{ color: debugInfo.invite_earner?.assigned ? '#22c55e' : '#6b7280' }}>
                                                        {debugInfo.invite_earner?.assigned ? 'ASSIGNED TODAY' : 'not assigned'}
                                                    </DebugValue>
                                                </DebugRow>
                                            </div>
                                            <div style={{ marginTop: '0.4rem', borderTop: '1px dashed rgba(239,68,68,0.3)', paddingTop: '0.4rem' }}>
                                                <DebugLabel>Today's Quests:</DebugLabel>
                                                {debugInfo.today_quests?.map(q => (
                                                    <DebugQuestRow key={q.quest_id}>
                                                        <span>
                                                            {q.quest_id} ({q.progress})
                                                            {q.completed && ' ✓'}
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
                                            <div style={{ marginTop: '0.4rem', borderTop: '1px dashed rgba(239,68,68,0.3)', paddingTop: '0.4rem' }}>
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
                </QuestBody>}
            </QuestCardContainer>

            {/* Celebration overlay */}
            {showCelebration && (
                <CelebrationOverlay onClick={closeCelebration}>
                    {/* Confetti pieces */}
                    {Array.from({ length: 30 }).map((_, i) => (
                        <ConfettiPiece
                            key={i}
                            $color={CONFETTI_COLORS[i % CONFETTI_COLORS.length]}
                            $left={Math.random() * 100}
                            $duration={2 + Math.random() * 2}
                            $delay={Math.random() * 0.5}
                        />
                    ))}
                    <CelebrationContent onClick={e => e.stopPropagation()}>
                        <CelebrationEmoji>🎉</CelebrationEmoji>
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
                            Awesome!
                        </CelebrationClose>
                    </CelebrationContent>
                </CelebrationOverlay>
            )}
        </>
    );
}
