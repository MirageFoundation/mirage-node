/**
 * QuestHeroCard - Displays daily quests, progress, and claimable rewards
 */

import React, { useState, useCallback } from 'react';
import styled, { keyframes, css } from 'styled-components';
import { useQuests, usePendingRewards } from '../utils/useQuests';
import { darkColors as fallbackDarkColors } from "../styled/colors/dark";
import { lightColors as fallbackLightColors } from "../styled/colors/light";

const pickThemeColor = (theme, key) => {
    if (theme?.colors?.[key]) return theme.colors[key];
    const isLight = theme?.name === 'light';
    return (isLight ? fallbackLightColors : fallbackDarkColors)[key];
};

// Container styling matching HomeFeedInfoCard exactly
const QuestCardContainer = styled.div`
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.06) 0%, rgba(139, 92, 246, 0.06) 100%);
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: ${({ $size }) => $size === 'compact' ? '8px' : '10px'};
    padding: ${({ $size }) => $size === 'compact' ? '0.4rem 0.6rem' : '0.6rem 0.9rem'};
    display: flex;
    flex-direction: column;
    gap: ${({ $size }) => $size === 'compact' ? '0.25rem' : '0.35rem'};

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
    align-items: center;
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
    }
`;

const QuestDescription = styled.div`
    font-size: 0.55rem;
    color: ${({ theme }) => pickThemeColor(theme, 'subtleText')};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;

    @media (max-width: 768px) {
        font-size: 0.5rem;
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
    align-items: center;
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

export default function QuestHeroCard({ collapsed = false, onToggleCollapse, size = 'large' }) {
    const {
        dailyQuests,
        flashQuest,
        secondsUntilReset,
        rewardMultiplier,
        loading: questsLoading,
        error: questsError,
        suspended: questsSuspended,
        refresh: refreshQuests,
    } = useQuests();

    const {
        totalAfterMultiplier,
        claiming,
        claimRewards,
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

    // Don't render if loading or no quests system
    if (questsLoading) {
        return null;
    }

    // If suspended, show a banner
    if (questsSuspended) {
        return (
            <QuestCardContainer $size={size}>
                <QuestHeader>
                    <QuestTitle>
                        <span>🎯</span> Daily Quests
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
                        <span>🎯</span> Daily Quests
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
                        <span>🎯</span> Daily Quests
                        <MultiplierBadge>
                            {rewardMultiplier.toFixed(1)}x rewards
                        </MultiplierBadge>
                    </QuestTitle>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                        {!collapsed && (
                            <ResetTimer title="Time until daily reset">
                                {formatTime(secondsUntilReset)}
                            </ResetTimer>
                        )}
                        {onToggleCollapse && (
                            <CollapseButton onClick={onToggleCollapse}>
                                {collapsed ? 'Show' : 'Hide'}
                            </CollapseButton>
                        )}
                    </div>
                </QuestHeader>

                {!collapsed && (
                <QuestList>
                    {dailyQuests.map(quest => (
                        <QuestItem key={quest.id} $completed={quest.completed}>
                            <QuestIcon>{getQuestIcon(quest.action_type)}</QuestIcon>
                            <QuestDetails>
                                <QuestName $completed={quest.completed}>{quest.title}</QuestName>
                                <QuestDescription>{quest.description}</QuestDescription>
                            </QuestDetails>
                            {quest.completed ? (
                                <CheckMark aria-label="Completed">✓</CheckMark>
                            ) : (
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
                            )}
                        </QuestItem>
                    ))}

                    {/* Flash quest if active */}
                    {flashQuest && (
                        <QuestItem $completed={flashQuest.completed} style={{ borderLeft: '2px solid #f59e0b' }}>
                            <QuestIcon>⚡</QuestIcon>
                            <QuestDetails>
                                <QuestName $completed={flashQuest.completed}>
                                    {flashQuest.title}
                                    <span style={{ color: '#f59e0b', fontSize: '0.5rem', marginLeft: '0.3rem' }}>
                                        FLASH
                                    </span>
                                </QuestName>
                                <QuestDescription>
                                    {flashQuest.description} • {formatTime(flashQuest.seconds_remaining)} left
                                </QuestDescription>
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
                        <div style={{ fontSize: '0.55rem', color: 'inherit', opacity: 0.7 }}>
                            {completedCount}/{dailyQuests.length} completed
                        </div>
                        {hasClaimableRewards && (
                            <RewardAmount>
                                {formatMirage(totalAfterMultiplier)} MIRAGE available
                            </RewardAmount>
                        )}
                    </div>
                    <ClaimButton
                        onClick={handleClaim}
                        disabled={!hasClaimableRewards || claiming}
                        $hasRewards={hasClaimableRewards}
                    >
                        {claiming ? 'Claiming...' : hasClaimableRewards ? 'Claim Rewards' : 'Complete Quests'}
                    </ClaimButton>
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
                            +{formatMirage(claimedAmount)} MIRAGE
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
