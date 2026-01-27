/**
 * QuestHeroCard - Displays daily quests, progress, and claimable rewards
 */

import React, { useState, useCallback } from 'react';
import styled, { keyframes, css } from 'styled-components';
import { useQuests, usePendingRewards } from '../utils/useQuests';
import { darkColors as fallbackDarkColors } from "../styled/colors/dark";
import { lightColors as fallbackLightColors } from "../styled/colors/light";
// DEBUG IMPORTS - TEMPORARY - REMOVE BEFORE PRODUCTION
import Api from '../lib/api';
import Storage from '../utils/Storage';
// END DEBUG IMPORTS

const pickThemeColor = (theme, key) => {
    if (theme?.colors?.[key]) return theme.colors[key];
    const isLight = theme?.name === 'light';
    return (isLight ? fallbackLightColors : fallbackDarkColors)[key];
};

// Container styling matching invite codes card (blue/indigo theme)
const QuestCardContainer = styled.div`
    background: ${({ theme }) => theme?.name === 'light'
        ? 'linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(99, 102, 241, 0.1) 100%)'
        : 'linear-gradient(135deg, rgba(59, 130, 246, 0.2) 0%, rgba(99, 102, 241, 0.2) 100%)'};
    border: 2px solid ${({ theme }) => theme?.name === 'light'
        ? 'rgba(59, 130, 246, 0.5)'
        : 'rgba(59, 130, 246, 0.5)'};
    border-radius: ${({ $size }) => $size === 'compact' ? '8px' : '10px'};
    padding: ${({ $size }) => $size === 'compact' ? '0.4rem 0.6rem' : '0.6rem 0.9rem'};
    display: flex;
    flex-direction: column;
    gap: ${({ $size }) => $size === 'compact' ? '0.25rem' : '0.35rem'};
    box-shadow: ${({ theme }) => theme?.name === 'light'
        ? '0 4px 12px rgba(59, 130, 246, 0.15)'
        : '0 4px 12px rgba(59, 130, 246, 0.25)'};

    @media (max-width: 1000px) {
        border-radius: ${({ $size }) => $size === 'compact' ? '6px' : '8px'};
        padding: ${({ $size }) => $size === 'compact' ? '0.35rem 0.5rem' : '0.5rem 0.75rem'};
    }

    @media (max-width: 768px) {
        border-radius: 6px;
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
    color: ${({ theme }) => pickThemeColor(theme, 'text')};
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
    color: ${({ theme }) => pickThemeColor(theme, 'subtleText')};
    background: ${({ theme }) => theme?.name === 'light'
        ? 'rgba(0, 0, 0, 0.05)'
        : 'rgba(255, 255, 255, 0.08)'};
    padding: 0.15rem 0.35rem;
    border-radius: 4px;
    font-variant-numeric: tabular-nums;

    @media (max-width: 768px) {
        font-size: 0.5rem;
    }
`;

const MultiplierBadge = styled.div`
    font-size: 0.6rem;
    color: #60a5fa;
    background: ${({ theme }) => theme?.name === 'light'
        ? 'rgba(59, 130, 246, 0.15)'
        : 'rgba(96, 165, 250, 0.2)'};
    padding: 0.15rem 0.35rem;
    border-radius: 4px;
    font-weight: 600;
    text-decoration: underline dotted;
    text-underline-offset: 2px;
    cursor: default;
    transition: all 0.15s ease;

    &:hover {
        color: #93c5fd;
        background: ${({ theme }) => theme?.name === 'light'
        ? 'rgba(59, 130, 246, 0.25)'
        : 'rgba(96, 165, 250, 0.35)'};
    }

    @media (max-width: 768px) {
        font-size: 0.5rem;
    }
`;

const QuestCountBadge = styled.span`
    font-size: 0.6rem;
    color: rgba(255, 255, 255, 0.8);
    font-weight: 500;

    @media (max-width: 1000px) {
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
            return theme?.name === 'light'
                ? 'rgba(34, 197, 94, 0.1)'
                : 'rgba(34, 197, 94, 0.12)';
        }
        return theme?.name === 'light'
            ? 'rgba(0, 0, 0, 0.03)'
            : 'rgba(255, 255, 255, 0.04)';
    }};
    border-radius: 6px;
    transition: background 0.2s ease;

    @media (max-width: 768px) {
        padding: 0.35rem 0.4rem;
        gap: 0.4rem;
    }
`;

const QuestIcon = styled.div`
    font-size: 0.9rem;
    width: 1.4rem;
    height: 1.4rem;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;

    @media (max-width: 768px) {
        font-size: 0.75rem;
        width: 1.2rem;
        height: 1.2rem;
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
        ? '#22c55e'
        : pickThemeColor(theme, 'text')};
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
    color: ${({ theme }) => pickThemeColor(theme, 'subtleText')};
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
    color: #f59e0b;
    font-weight: 600;

    @media (max-width: 768px) {
        font-size: 0.45rem;
    }
`;

const QuestRequirements = styled.ul`
    font-size: 0.5rem;
    color: ${({ theme }) => pickThemeColor(theme, 'subtleText')};
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
    color: #60a5fa;
    text-decoration: underline dotted;
    text-underline-offset: 2px;
    cursor: default;
    transition: color 0.15s ease;
    margin-top: 0.15rem;

    &:hover {
        color: #93c5fd;
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
    background: ${({ theme }) => theme?.name === 'light'
        ? 'rgba(0, 0, 0, 0.1)'
        : 'rgba(255, 255, 255, 0.1)'};
    border-radius: 2px;
    overflow: hidden;
`;

const ProgressFill = styled.div`
    height: 100%;
    width: ${props => Math.min(100, (props.$progress / props.$target) * 100)}%;
    background: ${props => props.$completed ? '#22c55e' : '#60a5fa'};
    border-radius: 2px;
    transition: width 0.3s ease;
`;

const ProgressText = styled.div`
    font-size: 0.5rem;
    color: ${({ theme }) => pickThemeColor(theme, 'subtleText')};
    font-variant-numeric: tabular-nums;
`;

const CheckMark = styled.div`
    width: 1.1rem;
    height: 1.1rem;
    background: #22c55e;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-size: 0.55rem;
    font-weight: bold;
    flex-shrink: 0;
`;

const ClaimSection = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding-top: 0.4rem;
    border-top: 1px solid ${({ theme }) => theme?.name === 'light'
        ? 'rgba(0, 0, 0, 0.08)'
        : 'rgba(255, 255, 255, 0.08)'};
`;

const RewardAmount = styled.div`
    font-size: 0.65rem;
    font-weight: 600;
    color: #f59e0b;

    @media (max-width: 768px) {
        font-size: 0.55rem;
    }
`;

const pulseAnimation = keyframes`
    0% { transform: scale(1); }
    50% { transform: scale(1.02); }
    100% { transform: scale(1); }
`;

const ClaimButton = styled.button`
    padding: 0.3rem 0.6rem;
    border: none;
    border-radius: 6px;
    font-size: 0.6rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;

    ${props => props.$hasRewards ? css`
        background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
        color: white;
        animation: ${pulseAnimation} 2s infinite;

        &:hover {
            background: linear-gradient(135deg, #d97706 0%, #b45309 100%);
            transform: translateY(-1px);
        }

        &:active {
            transform: translateY(0);
        }
    ` : css`
        background: ${({ theme }) => theme?.name === 'light'
            ? 'rgba(0, 0, 0, 0.08)'
            : 'rgba(255, 255, 255, 0.1)'};
        color: ${({ theme }) => pickThemeColor(theme, 'subtleText')};
        cursor: not-allowed;
    `}

    &:disabled {
        cursor: not-allowed;
        animation: none;
        opacity: 0.7;
    }

    @media (max-width: 768px) {
        padding: 0.25rem 0.5rem;
        font-size: 0.5rem;
    }
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
    background: rgba(239, 68, 68, 0.15);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 6px;
    padding: 0.4rem 0.6rem;
    text-align: center;
    color: #ef4444;
    font-size: 0.6rem;
`;

const EmptyState = styled.div`
    color: ${({ theme }) => pickThemeColor(theme, 'subtleText')};
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
 * Format MIRAGE amount (umirage to MIRAGE)
 */
function formatMirage(amount) {
    const mirage = amount / 1_000_000;
    if (mirage >= 1) {
        return mirage.toLocaleString(undefined, { maximumFractionDigits: 2 });
    }
    return mirage.toFixed(6);
}

/**
 * Get icon for quest action type
 */
function getQuestIcon(actionType) {
    const icons = {
        'post': '📝',
        'comment': '💬',
        'vote': '👍',
        'balanced_vote': '⚖️',
        'upvotes_received': '⭐',
        'comment_upvotes_received': '🌟',
        'unique_topic_post': '🗺️',
    };
    return icons[actionType] || '🎯';
}

/**
 * Get MIRAGE reward amount from quest rewards array
 */
function getQuestMirageReward(rewards) {
    if (!rewards || !Array.isArray(rewards)) return 0;
    const mirageReward = rewards.find(r => r.type === 'mirage');
    return mirageReward?.amount || 0;
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
        reqs.push(mins >= 60 ? `Min ${mins / 60} hour${mins >= 120 ? 's' : ''} between each` : `Min ${mins} min between each`);
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

// Collapse button
const CollapseButton = styled.button`
    background: transparent;
    border: none;
    color: ${({ theme }) => pickThemeColor(theme, 'subtleText')};
    font-size: 0.65rem;
    font-weight: 600;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 12px;
    transition: all 0.2s ease;
    display: flex;
    align-items: center;
    gap: 4px;

    &:hover {
        color: ${({ theme }) => pickThemeColor(theme, 'text')};
        background: ${({ theme }) => theme?.name === 'light'
        ? 'rgba(0, 0, 0, 0.05)'
        : 'rgba(255, 255, 255, 0.05)'};
    }
`;

// ==========================================================================
// DEBUG STYLED COMPONENT - TEMPORARY - REMOVE BEFORE PRODUCTION
// ==========================================================================
const DebugCompleteButton = styled.button`
    background: #ef4444;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 0.5rem;
    font-weight: 600;
    cursor: pointer;
    margin-left: 8px;
    flex-shrink: 0;
    
    &:hover {
        background: #dc2626;
    }
    
    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;
// ==========================================================================
// END DEBUG STYLED COMPONENT
// ==========================================================================

export default function QuestHeroCard({ collapsed = false, onToggleCollapse, size = 'large' }) {
    const {
        dailyQuests,
        flashQuest,
        secondsUntilReset,
        rewardMultiplier,
        loading: questsLoading,
        error: questsError,
        suspended: questsSuspended,
        disabled: questsDisabled,
        refresh: refreshQuests,
    } = useQuests();

    const {
        totalAfterMultiplier,
        claiming,
        claimRewards,
        claimingAvailable,
        refresh: refreshRewards,
    } = usePendingRewards();

    const [showCelebration, setShowCelebration] = useState(false);
    const [claimedAmount, setClaimedAmount] = useState(0);

    const handleClaim = useCallback(async () => {
        const result = await claimRewards();

        if (result.success) {
            // Find the MIRAGE reward amount
            const mirageReward = result.rewards?.find(r => r.type === 'mirage');
            const amount = mirageReward?.amount || 0;

            setClaimedAmount(amount);
            setShowCelebration(true);

            // Refresh data
            refreshQuests();
            refreshRewards();
        }
    }, [claimRewards, refreshQuests, refreshRewards]);

    const closeCelebration = useCallback(() => {
        setShowCelebration(false);
    }, []);

    // ==========================================================================
    // DEBUG HANDLER - TEMPORARY - REMOVE BEFORE PRODUCTION
    // ==========================================================================
    const [debugCompleting, setDebugCompleting] = useState(null);

    const handleDebugComplete = useCallback(async (questId) => {
        const owner = Storage.load('publicKey', '');
        if (!owner) {
            console.error('[DEBUG] No user address found');
            return;
        }

        setDebugCompleting(questId);
        try {
            const result = await Api.post('/debug/quest/complete', { owner, quest_id: questId });
            console.log('[DEBUG] Quest complete result:', result);
            if (result.success) {
                // Refresh quests and rewards
                refreshQuests();
                refreshRewards();
            }
        } catch (err) {
            console.error('[DEBUG] Failed to complete quest:', err);
        } finally {
            setDebugCompleting(null);
        }
    }, [refreshQuests, refreshRewards]);

    const [debugResetting, setDebugResetting] = useState(false);

    const handleDebugReset = useCallback(async () => {
        const owner = Storage.load('publicKey', '');
        if (!owner) {
            console.error('[DEBUG] No user address found');
            return;
        }

        setDebugResetting(true);
        try {
            const result = await Api.post('/debug/quest/reset', { owner });
            console.log('[DEBUG] Quest reset result:', result);
            if (result.success) {
                // Refresh quests and rewards
                refreshQuests();
                refreshRewards();
            }
        } catch (err) {
            console.error('[DEBUG] Failed to reset quests:', err);
        } finally {
            setDebugResetting(false);
        }
    }, [refreshQuests, refreshRewards]);
    // ==========================================================================
    // END DEBUG HANDLER
    // ==========================================================================

    // If quests system is disabled, don't render anything
    if (questsDisabled) {
        return null;
    }

    // Show loading state only on initial load (when we have no quests yet)
    if (questsLoading && dailyQuests.length === 0) {
        return (
            <QuestCardContainer $size={size}>
                <QuestHeader>
                    <QuestTitle>
                        <span>🚀</span> Daily Quests
                        {collapsed && (
                            <span style={{ fontWeight: 'normal' }}>
                                {' '}— Loading...
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

    // If suspended, show a banner
    if (questsSuspended) {
        return (
            <QuestCardContainer $size={size}>
                <QuestHeader>
                    <QuestTitle>
                        <span>🚀</span> Daily Quests
                        {collapsed && (
                            <span style={{ fontWeight: 'normal' }}>
                                {' '}— None available
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
                    <EmptyState>Rewards suspended</EmptyState>
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
                        <span>🚀</span> Daily Quests
                        {collapsed && (
                            <span style={{ fontWeight: 'normal' }}>
                                {' '}— None available
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
                        {questsError ? 'Unable to load quests' : 'No quests available yet. Check back soon!'}
                    </EmptyState>
                )}
            </QuestCardContainer>
        );
    }

    const hasClaimableRewards = totalAfterMultiplier > 0;
    const completedCount = dailyQuests.filter(q => q.completed).length;

    return (
        <>
            <QuestCardContainer $size={size} role="region" aria-label="Daily Quests">
                <QuestHeader>
                    <QuestTitle>
                        <span>🚀</span> Daily Quests
                        {collapsed && (
                            <span style={{ fontWeight: 'normal' }}>
                                {' '}— {dailyQuests.filter(q => !q.completed).length} available
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
                        {dailyQuests.filter(q => !q.completed).map(quest => (
                            <QuestItem key={quest.id} $completed={quest.completed}>
                                <QuestIcon>{getQuestIcon(quest.action_type)}</QuestIcon>
                                <QuestDetails>
                                    <QuestName $completed={quest.completed}>
                                        {quest.title}
                                        <QuestReward as="span" style={{ marginLeft: '0.4rem' }}>
                                            +{Math.round(getQuestMirageReward(quest.rewards) * rewardMultiplier).toLocaleString()} MIRAGE
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
                                    <CheckMark aria-label="Completed">✓</CheckMark>
                                ) : (
                                    <>
                                        <ProgressContainer>
                                            <ProgressBar>
                                                <ProgressFill
                                                    $progress={quest.progress}
                                                    $target={quest.target}
                                                    $completed={quest.completed}
                                                />
                                            </ProgressBar>
                                            <ProgressText>
                                                {quest.progress}/{quest.target}
                                            </ProgressText>
                                        </ProgressContainer>
                                        {/* DEBUG BUTTON - TEMPORARY - REMOVE BEFORE PRODUCTION */}
                                        <DebugCompleteButton
                                            onClick={() => handleDebugComplete(quest.id)}
                                            disabled={debugCompleting === quest.id}
                                            title="DEBUG: Instantly complete this quest"
                                        >
                                            {debugCompleting === quest.id ? '...' : 'DEBUG'}
                                        </DebugCompleteButton>
                                        {/* END DEBUG BUTTON */}
                                    </>
                                )}
                            </QuestItem>
                        ))}

                        {/* Flash quest if active and not completed */}
                        {flashQuest && flashQuest.seconds_remaining > 0 && !flashQuest.completed && (
                            <QuestItem $completed={flashQuest.completed} style={{ borderLeft: '2px solid #f59e0b' }}>
                                <QuestIcon>⚡</QuestIcon>
                                <QuestDetails>
                                    <QuestName $completed={flashQuest.completed}>
                                        {flashQuest.title}
                                        <span style={{ color: '#f59e0b', fontSize: '0.5rem', marginLeft: '0.3rem' }}>
                                            FLASH
                                        </span>
                                        <QuestReward as="span" style={{ marginLeft: '0.4rem' }}>
                                            +{Math.round(getQuestMirageReward(flashQuest.rewards) * rewardMultiplier).toLocaleString()} MIRAGE
                                        </QuestReward>
                                    </QuestName>
                                    <QuestDescription>
                                        {flashQuest.description} • {formatTime(flashQuest.seconds_remaining)} left
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
                                        <ProgressBar>
                                            <ProgressFill
                                                $progress={flashQuest.progress}
                                                $target={flashQuest.target}
                                                $completed={flashQuest.completed}
                                            />
                                        </ProgressBar>
                                        <ProgressText>
                                            {flashQuest.progress}/{flashQuest.target}
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
                                title="Loyalty multiplier increases from 1x to 5x over your first 30 days"
                                style={{ marginTop: 0, fontSize: '0.55rem', fontWeight: 600 }}
                            >
                                {rewardMultiplier.toFixed(2)}x loyalty multiplier
                            </LoyaltyBonusText>
                        </div>
                        <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                            {/* DEBUG BUTTON - TEMPORARY - REMOVE BEFORE PRODUCTION */}
                            <DebugCompleteButton
                                onClick={handleDebugReset}
                                disabled={debugResetting}
                                title="DEBUG: Reset quests and get new random ones"
                            >
                                {debugResetting ? '...' : 'RESET'}
                            </DebugCompleteButton>
                            {/* END DEBUG BUTTON */}
                            <ClaimButton
                                onClick={handleClaim}
                                disabled={!hasClaimableRewards || claiming || !claimingAvailable}
                                $hasRewards={hasClaimableRewards && claimingAvailable}
                                title={!claimingAvailable ? 'Reward distribution is not yet configured' : undefined}
                            >
                                {claiming ? 'Claiming...' : !claimingAvailable ? 'Coming Soon' : hasClaimableRewards ? `Claim ${Math.round(totalAfterMultiplier / 1_000_000).toLocaleString()} MIRAGE` : 'Complete Quests'}
                            </ClaimButton>
                        </div>
                    </ClaimSection>
                )}
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
                        <CelebrationAmount>
                            +{Math.round(claimedAmount / 1_000_000).toLocaleString()} MIRAGE
                        </CelebrationAmount>
                        <CelebrationClose onClick={closeCelebration}>
                            Awesome!
                        </CelebrationClose>
                    </CelebrationContent>
                </CelebrationOverlay>
            )}
        </>
    );
}
