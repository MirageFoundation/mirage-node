/**
 * QuestHeroCard - Displays daily quests, progress, and claimable rewards.
 * Visual design adapted from the mirage-mobile-app `QuestsSummaryCard`:
 *   - Clean panel background (no gradient overlay)
 *   - Icon pill tile (36×36 tinted circle) + title / subtitle on the left
 *   - Reward chip + rotating chevron on the right
 *   - Expanded body: progress bar → flash quest card → quest rows → CTA button
 */

import React, { useState, useCallback, useEffect } from 'react';
import styled, { css, keyframes } from 'styled-components';
import { HiChevronDown, HiSparkles, HiTicket, HiCheckBadge } from 'react-icons/hi2';
import { useRewards } from '../../../logic/useQuests';
import Api from '../../../utils/api';
import Storage from '../../../utils/Storage';
import { requireThemeColor } from '../../../utils/themeColor';

/* ============================================================
 * Layout / shell
 * ============================================================ */

const CardContainer = styled.div`
    box-sizing: border-box;
    /* Match the post CardView exactly (border-radius: 8px; margin: 4px 0)
     * so this card aligns with the feed column and shares the same bg. */
    width: 100%;
    max-width: 100%;
    align-self: flex-start;
    margin: 4px 0;
    /* Use the main page background so the card blends with the feed
     * (user wants it to feel flush with the feed, not a floating panel). */
    background: ${({ theme }) => requireThemeColor(theme, 'bg')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 8px;
    overflow: hidden;
    box-shadow: none;

    @media (max-width: 600px) {
        border-radius: 6px;
    }
`;

const Header = styled.button`
    all: unset;
    box-sizing: border-box;
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 0.4rem 1rem;
    cursor: pointer;
    user-select: none;
    transition: background 0.15s ease;

    &:hover {
        background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0, 0, 0, 0.02)'
        : 'rgba(255, 255, 255, 0.03)'};
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        outline-offset: -2px;
    }

    @media (max-width: 600px) {
        padding: 0.35rem 0.85rem;
    }
`;

const TitleRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex: 1;
    min-width: 0;
`;

/** Rounded square tile — matches mobile `iconContainer` */
const IconTile = styled.div`
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    border-radius: 7px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.8rem;
    line-height: 1;
    background: transparent;
    color: ${({ $tint }) => $tint || '#667eea'};
`;

const TitleStack = styled.div`
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
    flex: 1;
`;

/** Row combining "Daily Quests" title + an inline live-ticking reset
 * timer pill on its right (bluemoon-style). */
const TitleLine = styled.div`
    display: flex;
    align-items: center;
    gap: 0.35rem;
    min-width: 0;
`;

const TitleText = styled.div`
    font-size: 0.72rem;
    font-weight: 600;
    color: ${({ theme, $color }) => $color || requireThemeColor(theme, 'text')};
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const SubtitleText = styled.div`
    font-size: 0.6rem;
    color: ${({ theme, $color }) => $color || requireThemeColor(theme, 'subtleText')};
    line-height: 1.25;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
`;

/** Small pill showing the live-ticking "Xh Ym Zs left" next to the
 * quest title — bluemoon-style. Updates every second because the
 * `useRewards` hook decrements `secondsUntilReset` once per second. */
const HeaderResetTimer = styled.span`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    font-size: 0.55rem;
    font-weight: 600;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0, 0, 0, 0.05)'
        : 'rgba(255, 255, 255, 0.08)'};
    padding: 0.1rem 0.35rem;
    border-radius: 4px;
    font-variant-numeric: tabular-nums;
    line-height: 1.1;
`;

const HeaderRight = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex-shrink: 0;
`;

/** Small pill on the right of the header — reward or count */
const HeaderBadge = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.15rem;
    font-size: 0.55rem;
    font-weight: 700;
    padding: 0.12rem 0.4rem;
    border-radius: 999px;
    font-variant-numeric: tabular-nums;
    color: ${({ $tint }) => $tint || '#22C55E'};
    background: ${({ $tint, theme }) => {
        const hex = $tint || '#22C55E';
        return theme.name === 'light' ? `${hex}1F` : `${hex}33`;
    }};
    white-space: nowrap;
`;

/** Chevron that rotates 180° when collapsed — uses the same
 * `HiChevronDown` icon as the post card for visual consistency. */
const Chevron = styled(HiChevronDown)`
    display: inline-flex;
    width: 14px;
    height: 14px;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    transition: transform 0.2s ease;
    transform: rotate(${({ $collapsed }) => ($collapsed ? '-90deg' : '0deg')});
`;

const Body = styled.div`
    padding: 0 1rem 0.6rem;
    display: flex;
    flex-direction: column;
    gap: 0.45rem;

    @media (max-width: 600px) {
        padding: 0 0.85rem 0.55rem;
    }
`;

/* ============================================================
 * Flash quest card
 * ============================================================ */

const FLASH_ACCENT = '#F59E0B';

const FlashCard = styled.div`
    border: 1px solid ${FLASH_ACCENT}4D;
    border-radius: 7px;
    padding: 0.4rem 0.5rem;
    background: ${FLASH_ACCENT}0F;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
`;

const FlashHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.4rem;
`;

const FlashBadge = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    font-size: 0.5rem;
    font-weight: 800;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: ${FLASH_ACCENT};
`;

const FlashTimer = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.15rem;
    font-size: 0.55rem;
    font-weight: 600;
    color: ${({ $urgent, theme }) => $urgent
        ? requireThemeColor(theme, 'voteDown')
        : FLASH_ACCENT};
    font-variant-numeric: tabular-nums;
`;

const FlashRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
`;

const FlashTitleText = styled.div`
    flex: 1;
    font-size: 0.65rem;
    font-weight: 500;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    opacity: ${({ $completed }) => ($completed ? 1 : 0.85)};
    line-height: 1.2;
    min-width: 0;
`;

const FlashProgressText = styled.span`
    font-size: 0.58rem;
    color: ${FLASH_ACCENT};
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    flex-shrink: 0;
`;

const FlashProgressTrack = styled.div`
    height: 3px;
    border-radius: 2px;
    overflow: hidden;
    background: ${FLASH_ACCENT}26;
`;

const FlashProgressFill = styled.div`
    height: 100%;
    border-radius: 2px;
    width: ${({ $pct }) => `${Math.max(0, Math.min(100, $pct || 0))}%`};
    background: ${({ $completed, theme }) => $completed
        ? requireThemeColor(theme, 'voteUp')
        : FLASH_ACCENT};
    transition: width 0.3s ease;
`;

/* ============================================================
 * Quest list rows
 * ============================================================ */

/* Uppercase section labels ("TODAY'S QUESTS", "FLASH QUEST") — adapted
 * from mobile `styles.sectionTitle`. */
const SectionLabel = styled.div`
    font-size: 0.5rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    margin-top: 0.1rem;
`;

/* Loyalty multiplier chip (amber pill with flame glyph) — `RewardMultiplierBadge` */
const MultiplierBadge = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    font-size: 0.55rem;
    font-weight: 800;
    padding: 0.1rem 0.4rem;
    border-radius: 999px;
    color: #F59E0B;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(245, 158, 11, 0.14)'
        : 'rgba(245, 158, 11, 0.22)'};
    border: 1px solid ${({ theme }) => theme.name === 'light'
        ? 'rgba(245, 158, 11, 0.35)'
        : 'rgba(245, 158, 11, 0.45)'};
    font-variant-numeric: tabular-nums;
    white-space: nowrap;

    &::before {
        content: '🔥';
        font-size: 0.55rem;
    }
`;

const QuestList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
`;

/* Quest card — bigger bordered tile (not a tight row). Mirrors mobile
 * `styles.questCard`: rounded 10px, panel bg (or success-tint when
 * completed), 1-2px border. */
const QuestRow = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0.55rem 0.7rem;
    border-radius: 8px;
    background: ${({ $completed, theme }) => $completed
        ? (theme.name === 'light' ? 'rgba(16, 185, 129, 0.08)' : 'rgba(16, 185, 129, 0.12)')
        : (theme.name === 'light' ? 'rgba(102, 126, 234, 0.06)' : 'rgba(102, 126, 234, 0.08)')};
    border: 1px solid ${({ $completed, theme }) => $completed
        ? (theme.name === 'light' ? 'rgba(16, 185, 129, 0.35)' : 'rgba(16, 185, 129, 0.45)')
        : (theme.name === 'light' ? 'rgba(102, 126, 234, 0.18)' : 'rgba(102, 126, 234, 0.24)')};
    min-width: 0;
`;

const QuestRowHeader = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
`;

/* Per-quest action-color icon tile */
const QuestActionTile = styled.span`
    position: relative;
    flex-shrink: 0;
    width: 22px;
    height: 22px;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.72rem;
    line-height: 1;
    color: ${({ $tint }) => $tint || '#667eea'};
    background: ${({ $tint, theme }) => {
        const hex = $tint || '#667eea';
        return theme.name === 'light' ? `${hex}26` : `${hex}33`;
    }};
`;

/* Small checkmark badge overlaid on the corner of the action tile */
const QuestCompleteBadge = styled.span`
    position: absolute;
    bottom: -2px;
    right: -2px;
    width: 10px;
    height: 10px;
    border-radius: 999px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.45rem;
    font-weight: 800;
    color: #FFFFFF;
    background: ${({ theme }) => requireThemeColor(theme, 'voteUp')};
    border: 2px solid ${({ theme }) => requireThemeColor(theme, 'panel')};

    &::before { content: '✓'; }
`;

/** Checkmark-circle / ellipse-outline — mimics Ionicons used in mobile */
const QuestStatusIcon = styled.span`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 999px;
    margin-top: 1px;

    ${({ $completed, theme }) => $completed
        ? css`
            background: ${requireThemeColor(theme, 'voteUp')};
            color: #FFFFFF;
            font-size: 0.7rem;
            font-weight: 800;
            line-height: 1;

            &::before { content: '✓'; }
        `
        : css`
            background: transparent;
            border: 1.5px solid ${requireThemeColor(theme, 'subtleText')};
            opacity: 0.55;
        `}
`;

const QuestRowBody = styled.div`
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
`;

const QuestTopLine = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
`;

const QuestRowTitle = styled.span`
    flex: 1;
    min-width: 0;
    font-size: 0.68rem;
    font-weight: 600;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    opacity: ${({ $completed }) => ($completed ? 1 : 0.75)};
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

/* Sparkle reward pill (amber tint) — adapted from mobile `rewardBadge`. */
const QuestRowReward = styled.span`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: 0.15rem;
    font-size: 0.54rem;
    font-weight: 800;
    padding: 0.1rem 0.35rem;
    border-radius: 999px;
    color: #F59E0B;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(245, 158, 11, 0.14)'
        : 'rgba(245, 158, 11, 0.22)'};
    border: 1px solid ${({ theme }) => theme.name === 'light'
        ? 'rgba(245, 158, 11, 0.35)'
        : 'rgba(245, 158, 11, 0.45)'};
    font-variant-numeric: tabular-nums;
    white-space: nowrap;

    &::before {
        content: '✨';
        font-size: 0.5rem;
    }
`;

const QuestRowProgress = styled.span`
    flex-shrink: 0;
    font-size: 0.58rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-variant-numeric: tabular-nums;
    font-weight: 500;
`;

const QuestRowDescription = styled.div`
    font-size: 0.6rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    line-height: 1.25;
    margin-top: 0;
`;

/* Bullet-point list for per-quest requirements / details.
 * Mirrors mobile `QuestRequirements` rendering (dots + gray text). */
const QuestDetailsList = styled.ul`
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 1px;
`;
const QuestDetailItem = styled.li`
    display: flex;
    align-items: flex-start;
    gap: 0.3rem;
    font-size: 0.58rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    line-height: 1.25;

    &::before {
        content: '';
        flex-shrink: 0;
        width: 2.5px;
        height: 2.5px;
        border-radius: 999px;
        margin-top: 0.42em;
        background: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
        opacity: 0.7;
    }
`;

/* Per-quest progress bar row (mirrors mobile `questProgressContainer`) */
const QuestRowProgressTrack = styled.div`
    width: 100%;
    height: 3px;
    border-radius: 2px;
    overflow: hidden;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0, 0, 0, 0.06)'
        : 'rgba(255, 255, 255, 0.08)'};
`;
const QuestRowProgressFill = styled.div`
    height: 100%;
    border-radius: 2px;
    width: ${({ $pct }) => `${Math.max(0, Math.min(100, $pct || 0))}%`};
    background: ${({ $completed, $tint, theme }) => $completed
        ? requireThemeColor(theme, 'voteUp')
        : ($tint || '#F59E0B')};
    transition: width 0.3s ease;
`;
const QuestRowFooter = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.4rem;
`;
const QuestRowPercent = styled.span`
    font-size: 0.58rem;
    font-weight: 700;
    color: ${({ $completed, theme }) => $completed
        ? requireThemeColor(theme, 'voteUp')
        : requireThemeColor(theme, 'subtleText')};
    font-variant-numeric: tabular-nums;
`;

/* ---- Balanced-vote dual progress rows (mirrors mobile QuestRequirements) ---- */

const BALANCED_UP_COLOR = '#10B981';
const BALANCED_DOWN_COLOR = '#8B5CF6';

const BalancedBarsGrid = styled.div`
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;
    width: 100%;
`;

const BalancedBarRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.3rem;
    min-width: 0;
`;

const BalancedArrow = styled.span`
    flex-shrink: 0;
    font-size: 0.7rem;
    line-height: 1;
    color: ${({ $tint }) => $tint};
`;

const BalancedTrack = styled.div`
    flex: 1;
    min-width: 0;
    height: 4px;
    border-radius: 2px;
    overflow: hidden;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0, 0, 0, 0.06)'
        : 'rgba(255, 255, 255, 0.08)'};
`;

const BalancedFill = styled.div`
    height: 100%;
    border-radius: 2px;
    width: ${({ $pct }) => `${Math.max(0, Math.min(100, $pct || 0))}%`};
    background: ${({ $tint }) => $tint};
    transition: width 0.3s ease;
`;

const BalancedCount = styled.span`
    flex-shrink: 0;
    font-size: 0.55rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-variant-numeric: tabular-nums;
`;

/* ============================================================
 * Footer CTA + loyalty multiplier
 * ============================================================ */

const ClaimFooter = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
`;

const LoyaltyRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.3rem;
    font-size: 0.65rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-weight: 500;
    font-variant-numeric: tabular-nums;

    &::before {
        content: '⚡';
        font-size: 0.75rem;
    }
`;

const CtaButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.35rem;
    width: 100%;
    padding: 0.42rem 0.75rem;
    border-radius: 7px;
    font-size: 0.68rem;
    font-weight: 700;
    font-family: inherit;
    color: #FFFFFF;
    border: none;
    cursor: pointer;
    background: ${({ theme }) => requireThemeColor(theme, 'followBtnBg')};
    transition: background 0.15s ease, transform 0.15s ease;

    &:hover:not(:disabled) {
        background: ${({ theme }) => requireThemeColor(theme, 'followBtnBgHover')};
        transform: translateY(-1px);
    }

    &:active:not(:disabled) {
        transform: translateY(0);
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;

const ClaimErrorMessage = styled.div`
    padding: 0.45rem 0.65rem;
    font-size: 0.68rem;
    color: ${({ theme }) => requireThemeColor(theme, 'buttonDangerBorder')};
    line-height: 1.35;
    border-radius: 8px;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(239, 68, 68, 0.08)'
        : 'rgba(239, 68, 68, 0.14)'};
    border: 1px solid ${({ theme }) => theme.name === 'light'
        ? 'rgba(239, 68, 68, 0.25)'
        : 'rgba(239, 68, 68, 0.32)'};
`;

/* ============================================================
 * Suspension + empty + loading states
 * ============================================================ */

const SuspendedBox = styled.div`
    padding: 0.55rem 0.7rem;
    border-radius: 8px;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(239, 68, 68, 0.08)'
        : 'rgba(239, 68, 68, 0.14)'};
    border: 1px solid ${({ theme }) => theme.name === 'light'
        ? 'rgba(239, 68, 68, 0.25)'
        : 'rgba(239, 68, 68, 0.32)'};
    color: ${({ theme }) => theme.name === 'light' ? '#EF4444' : '#F87171'};
    font-size: 0.7rem;
    line-height: 1.4;
    display: flex;
    align-items: flex-start;
    gap: 0.4rem;

    &::before {
        content: '⏱';
        font-size: 0.85rem;
        line-height: 1.1;
    }
`;

const EmptyState = styled.div`
    padding: 0.3rem 0;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.72rem;
    line-height: 1.4;
`;

/* ============================================================
 * Celebration overlay + confetti (unchanged behavior)
 * ============================================================ */

const confettiAnimation = keyframes`
    0% { transform: translateY(0) rotate(0deg); opacity: 1; }
    100% { transform: translateY(400px) rotate(720deg); opacity: 0; }
`;

const overlayFadeIn = keyframes`
    0% { opacity: 0; }
    100% { opacity: 1; }
`;

const cardPopIn = keyframes`
    0%   { opacity: 0; transform: translateY(12px) scale(0.94); }
    60%  { opacity: 1; transform: translateY(-2px) scale(1.01); }
    100% { opacity: 1; transform: translateY(0)    scale(1); }
`;

const emojiBob = keyframes`
    0%, 100% { transform: translateY(0) rotate(-4deg); }
    50%      { transform: translateY(-6px) rotate(4deg); }
`;

const sheen = keyframes`
    0%   { transform: translateX(-120%) skewX(-20deg); }
    100% { transform: translateX(220%)  skewX(-20deg); }
`;

const CelebrationOverlay = styled.div`
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.72);
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10000;
    padding: 1.25rem;
    animation: ${overlayFadeIn} 0.25s ease;
`;

const CelebrationContent = styled.div`
    position: relative;
    width: min(94vw, 480px);
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 18px;
    padding: 1.6rem 1.75rem 1.25rem;
    text-align: center;
    overflow: hidden;
    box-shadow:
        0 20px 60px rgba(0, 0, 0, 0.55),
        0 0 0 1px rgba(255, 255, 255, 0.03) inset;
    animation: ${cardPopIn} 0.45s cubic-bezier(0.2, 0.9, 0.3, 1.2);

    /* Top accent rail using mirage blue */
    &::before {
        content: '';
        position: absolute;
        inset: 0 0 auto 0;
        height: 3px;
        background: linear-gradient(
            90deg,
            transparent 0%,
            ${({ theme }) =>
                theme.name === 'dark' ? theme.colors.followBtnBg : theme.colors.link} 30%,
            ${({ theme }) =>
                theme.name === 'dark' ? theme.colors.followBtnBgHover : theme.colors.linkHover} 70%,
            transparent 100%
        );
    }
`;

const CelebrationEmojiWrap = styled.div`
    margin: 0 auto 0.5rem;
    display: flex;
    align-items: center;
    justify-content: center;
`;

const CelebrationEmoji = styled.div`
    font-size: 2.4rem;
    line-height: 1;
    animation: ${emojiBob} 1.6s ease-in-out infinite;
`;

const CelebrationEyebrow = styled.div`
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.followBtnBg};
    margin-bottom: 0.3rem;
`;

const CelebrationTitle = styled.div`
    font-size: 1.15rem;
    font-weight: 800;
    color: ${({ theme }) => theme.colors.text};
    margin-bottom: 0.2rem;
    letter-spacing: -0.01em;
`;

const CelebrationSubtitle = styled.div`
    font-size: 0.75rem;
    color: ${({ theme }) => theme.colors.subtleText};
    margin-bottom: 1rem;
`;

const RewardsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    margin-bottom: 1.1rem;
`;

const RewardRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.55rem 0.8rem;
    background: ${({ theme }) => theme.colors.panelAlt};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
    text-align: left;
`;

const RewardIcon = styled.div`
    width: 28px;
    height: 28px;
    border-radius: 7px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    background: ${({ theme }) =>
        theme.name === 'dark' ? 'rgba(245, 158, 11, 0.08)' : 'rgba(245, 158, 11, 0.06)'};
    border: 0.5px solid #f59e0b;
    color: #f59e0b;

    svg {
        width: 16px;
        height: 16px;
    }
`;

const RewardMeta = styled.div`
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
`;

const RewardLabel = styled.div`
    font-size: 0.62rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.subtleText};
    text-transform: uppercase;
    letter-spacing: 0.06em;
`;

const RewardValue = styled.div`
    font-family: ui-monospace, "SF Mono", "JetBrains Mono", "Menlo", "Monaco", Consolas, monospace;
    font-size: 0.92rem;
    font-weight: 500;
    letter-spacing: -0.01em;
    font-variant-numeric: tabular-nums;
    color: ${({ theme }) => theme.colors.text};
    line-height: 1.2;
`;

const CelebrationClose = styled.button`
    width: 100%;
    padding: 0.6rem 1.25rem;
    background: ${({ theme }) => theme.colors.followBtnBg};
    color: #ffffff;
    border: 1px solid ${({ theme }) => theme.colors.followBtnBg};
    border-radius: 9px;
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.01em;
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.followBtnBgHover};
        border-color: ${({ theme }) => theme.colors.followBtnBgHover};
        transform: translateY(-1px);
    }

    &:active {
        transform: translateY(0);
    }
`;

const ConfettiPiece = styled.div`
    position: absolute;
    width: 10px;
    height: 10px;
    background: ${({ $color }) => $color};
    top: -10px;
    left: ${({ $left }) => $left}%;
    z-index: 2;
    pointer-events: none;
    animation: ${confettiAnimation} ${({ $duration }) => $duration}s linear forwards;
    animation-delay: ${({ $delay }) => $delay}s;
`;

/* ============================================================
 * Debug panel (unchanged behavior, minor restyling)
 * ============================================================ */

const DebugPanel = styled.div`
    margin-top: 0.5rem;
    padding: 0.5rem;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(239, 68, 68, 0.1)'
        : 'rgba(239, 68, 68, 0.15)'};
    border: 1px dashed rgba(239, 68, 68, 0.5);
    border-radius: 8px;
    font-size: 0.6rem;
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
        $variant === 'danger' ? 'rgba(239, 68, 68, 0.2)'
            : $variant === 'success' ? 'rgba(34, 197, 94, 0.2)'
                : 'rgba(59, 130, 246, 0.2)'};
    border: 1px solid ${({ $variant }) =>
        $variant === 'danger' ? 'rgba(239, 68, 68, 0.5)'
            : $variant === 'success' ? 'rgba(34, 197, 94, 0.5)'
                : 'rgba(59, 130, 246, 0.5)'};
    color: ${({ $variant }) =>
        $variant === 'danger' ? '#ef4444'
            : $variant === 'success' ? '#22c55e'
                : '#3b82f6'};
    font-size: 0.55rem;
    font-weight: 600;
    padding: 0.2rem 0.45rem;
    border-radius: 999px;
    cursor: pointer;
    transition: all 0.15s ease;

    &:hover:not(:disabled) { opacity: 0.85; }
    &:disabled { opacity: 0.5; cursor: not-allowed; }
`;

const DebugButtonGroup = styled.div`
    display: flex;
    gap: 0.3rem;
    flex-wrap: wrap;
    margin-top: 0.3rem;
`;

const DebugInput = styled.input`
    width: 50px;
    padding: 0.15rem 0.3rem;
    font-size: 0.55rem;
    border: 1px solid rgba(59, 130, 246, 0.5);
    border-radius: 4px;
    background: ${({ theme }) => theme.name === 'light' ? 'white' : 'rgba(0,0,0,0.3)'};
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    text-align: center;

    &:focus { outline: none; border-color: #3b82f6; }
`;

const DebugQuestRow = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.2rem 0.35rem;
    margin: 0.15rem 0;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0,0,0,0.03)'
        : 'rgba(255,255,255,0.03)'};
    border-radius: 6px;
`;

/* ============================================================
 * Helpers
 * ============================================================ */

/** `3h 12m` / `14m 5s` — matches mobile `formatTimeShort` + seconds */
function formatTimeCompact(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${String(sec).padStart(2, '0')}s`;
    return `${sec}s`;
}

function getQuestRewardDisplay(rewards, rewardMultiplier) {
    if (!rewards || !Array.isArray(rewards)) return null;
    const mirageReward = rewards.find(r => r.type === 'mirage');
    const inviteCodeReward = rewards.find(r => r.type === 'invite_code');
    if (inviteCodeReward) {
        const count = inviteCodeReward.amount || 1;
        /* Mobile renders invite-code rewards as `+{amount} Invite` — keep
         * the singular label regardless of count to mirror the mobile
         * QuestCard reward pill exactly. */
        return `+${count} Invite`;
    }
    if (mirageReward) {
        const amount = mirageReward.amount || 0;
        const applyMultiplier = mirageReward.apply_multiplier !== false;
        const displayAmount = applyMultiplier ? Math.round(amount * rewardMultiplier) : amount;
        return `+${displayAmount.toLocaleString()}`;
    }
    return null;
}

/* Build the per-quest detail bullet list. First item is the quest
 * description (if any), followed by structured requirement lines.
 * Mirrors mobile `QuestRequirements`. */
function buildQuestDetails(quest) {
    const items = [];
    if (quest.description) items.push(quest.description);
    if (quest.min_content_length) items.push(`Minimum ${quest.min_content_length} characters`);
    if (quest.unique_target === true) items.push('Must be different targets');
    if (quest.time_spacing_minutes) {
        const mins = quest.time_spacing_minutes;
        items.push(mins >= 60
            ? `${mins / 60} hour${mins === 60 ? '' : 's'} between actions`
            : `${mins} min between actions`);
    }
    if (quest.unique_topics_min) items.push(`At least ${quest.unique_topics_min} different topics`);
    if (quest.quality_threshold) items.push(`Needs ${quest.quality_threshold}+ upvotes`);
    /* Mobile renders the "New votes only" requirement for ANY quest
     * whose `count_vote_changes === false`, not just `vote`. Cover
     * `balanced_vote` + any future vote-like action by dropping the
     * action-type gate. */
    if (quest.count_vote_changes === false
        && (quest.action_type === 'vote' || quest.action_type === 'balanced_vote')) {
        items.push('New votes only (changes don\u2019t count)');
    }
    return items;
}

const CONFETTI_COLORS = ['#f59e0b', '#22c55e', '#667eea', '#ec4899', '#764ba2'];

/* Per-action colors / emojis — adapted from mobile `ACTION_COLORS`
 * and `ACTION_ICONS`. Keeps visual parity with the mobile quests screen. */
const ACTION_COLORS = {
    comment: '#3B82F6',
    vote: '#10B981',
    balanced_vote: '#06B6D4',
    post: '#8B5CF6',
    follow: '#F59E0B',
    share: '#EC4899',
    upvotes_received: '#F97316',
    comment_upvotes_received: '#6366F1',
    invite_recruit: '#14B8A6',
    claim_only: '#A855F7',
    /* Additional action types the backend can emit that the mobile
     * client inherits via default fallback — add explicit entries so
     * each variant gets a distinct tile on the web card. */
    unique_topic_post: '#0EA5E9',
    comments_received: '#0891B2',
    quality_comments: '#D946EF',
    first_topic_post: '#FB7185',
};
const ACTION_EMOJI = {
    comment: '💬',
    vote: '👍',
    balanced_vote: '⇅',
    post: '✍️',
    follow: '➕',
    share: '↗',
    upvotes_received: '📈',
    comment_upvotes_received: '💭',
    invite_recruit: '👥',
    claim_only: '🎁',
    unique_topic_post: '🗂',
    comments_received: '📬',
    quality_comments: '⭐',
    first_topic_post: '🏴',
};

function getActionColor(actionType) {
    return ACTION_COLORS[actionType] || '#667eea';
}
function getActionEmoji(actionType) {
    return ACTION_EMOJI[actionType] || '⭐';
}

/* Format a unix timestamp (seconds) using the viewer's locale —
 * mirrors mobile's `suspendedUntil.toLocaleDateString` + `toLocaleTimeString`
 * split so the suspension box can show both parts. */
function formatSuspensionDate(suspendedUntilSeconds) {
    if (!suspendedUntilSeconds || suspendedUntilSeconds > 4000000000) return null;
    try {
        const d = new Date(suspendedUntilSeconds * 1000);
        const date = d.toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
        });
        const time = d.toLocaleTimeString(undefined, {
            hour: '2-digit',
            minute: '2-digit',
        });
        return { date, time };
    } catch (_) {
        return null;
    }
}

/* ============================================================
 * Component
 * ============================================================ */

export default function QuestHeroCard({ feedViewMode = 'compact', collapsed = false, onToggleCollapse }) {
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

    // TEMP TEST: force-show the Rewards Claimed popup on mount.
    const [showCelebration, setShowCelebration] = useState(true);
    const [claimedAmount, setClaimedAmount] = useState(1_234_000_000);
    const [claimedInviteCodes, setClaimedInviteCodes] = useState(2);
    const [claimError, setClaimError] = useState(null);

    /* Local live-ticking copies of the two countdowns. The `useRewards`
     * hook has its own ticker but it can be interrupted by data refreshes
     * or unmounted children, so we keep an independent 1s interval here
     * to guarantee the UI updates every second. Both values resync
     * whenever the underlying hook state changes. */
    const [liveResetSeconds, setLiveResetSeconds] = useState(
        Number.isFinite(secondsUntilReset) ? secondsUntilReset : 0,
    );
    const [liveFlashSeconds, setLiveFlashSeconds] = useState(
        flashQuest?.seconds_remaining || 0,
    );

    useEffect(() => {
        if (Number.isFinite(secondsUntilReset)) {
            setLiveResetSeconds(secondsUntilReset);
        }
    }, [secondsUntilReset]);
    useEffect(() => {
        setLiveFlashSeconds(flashQuest?.seconds_remaining || 0);
    }, [flashQuest?.id, flashQuest?.seconds_remaining]);

    useEffect(() => {
        const id = setInterval(() => {
            setLiveResetSeconds(s => (s > 0 ? s - 1 : 0));
            setLiveFlashSeconds(s => (s > 0 ? s - 1 : 0));
        }, 1000);
        return () => clearInterval(id);
    }, []);

    const userAddress = Storage.load('publicKey', '');

    // Debug panel state
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
        if (showDebug && debugEnabled) fetchDebugInfo();
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

    const closeCelebration = useCallback(() => setShowCelebration(false), []);

    if (questsDisabled) return null;

    /* Loading (initial) */
    if (questsLoading && dailyQuests.length === 0) {
        return (
            <CardContainer $feedViewMode={feedViewMode}>
                <Header type="button" onClick={onToggleCollapse} aria-expanded={!collapsed}>
                    <TitleRow>
                        <IconTile $tint="#F59E0B">🏆</IconTile>
                        <TitleStack>
                            <TitleText>Daily Quests</TitleText>
                            <SubtitleText>loading…</SubtitleText>
                        </TitleStack>
                    </TitleRow>
                    <HeaderRight>
                        <Chevron $collapsed={collapsed} aria-hidden="true" />
                    </HeaderRight>
                </Header>
                {!collapsed && (
                    <Body><EmptyState>Loading quests…</EmptyState></Body>
                )}
            </CardContainer>
        );
    }

    /* Suspended */
    if (questsSuspended) {
        const suspendedUntil = questsSuspensionInfo?.suspended_until;
        const suspensionReason = typeof questsSuspensionInfo?.reason === 'string'
            && questsSuspensionInfo.reason.trim().length > 0
            ? questsSuspensionInfo.reason
            : 'Your quest rewards have been suspended';
        const formatted = formatSuspensionDate(suspendedUntil);
        const suspendedUntilText = formatted
            ? `Suspended until ${formatted.date} at ${formatted.time}`
            : 'Your quest rewards have been suspended.';
        return (
            <CardContainer $feedViewMode={feedViewMode}>
                <Header type="button" onClick={onToggleCollapse} aria-expanded={!collapsed}>
                    <TitleRow>
                        <IconTile $tint="#EF4444">⚠️</IconTile>
                        <TitleStack>
                            <TitleText $color="#EF4444">Quests Suspended</TitleText>
                            <SubtitleText $color="#F87171" title={suspensionReason}>{suspensionReason}</SubtitleText>
                        </TitleStack>
                    </TitleRow>
                    <HeaderRight>
                        <Chevron $collapsed={collapsed} aria-hidden="true" />
                    </HeaderRight>
                </Header>
                {!collapsed && (
                    <Body>
                        <SuspendedBox>{suspendedUntilText}</SuspendedBox>
                    </Body>
                )}
            </CardContainer>
        );
    }

    /* Empty / error */
    if (questsError || dailyQuests.length === 0) {
        const subtitle = questsError
            ? (typeof questsError === 'string' ? questsError : 'Unable to load quests')
            : 'No quests available yet';
        return (
            <CardContainer $feedViewMode={feedViewMode}>
                <Header type="button" onClick={onToggleCollapse} aria-expanded={!collapsed}>
                    <TitleRow>
                        <IconTile $tint="#F59E0B">🏆</IconTile>
                        <TitleStack>
                            <TitleText>Daily Quests</TitleText>
                            <SubtitleText>{subtitle}</SubtitleText>
                        </TitleStack>
                    </TitleRow>
                    <HeaderRight>
                        <Chevron $collapsed={collapsed} aria-hidden="true" />
                    </HeaderRight>
                </Header>
                {!collapsed && (
                    <Body>
                        <EmptyState>
                            {questsError
                                ? (typeof questsError === 'string' ? questsError : 'Unable to load quests. Please try again later.')
                                : 'No quests available yet. Check back soon!'}
                        </EmptyState>
                    </Body>
                )}
            </CardContainer>
        );
    }

    /* Normal state */
    const completedCount = dailyQuests.filter(q => q.completed).length;
    const totalCount = dailyQuests.length;
    const progressPct = totalCount > 0 ? (completedCount / totalCount) * 100 : 0;
    const allComplete = totalCount > 0 && completedCount === totalCount;
    const hasClaimableRewards = totalAfterMultiplier > 0 || pendingInviteCodes > 0;

    const flashTarget = flashQuest?.target || 0;
    const flashProgress = flashQuest ? Math.min(flashQuest.progress || 0, flashTarget) : 0;
    const flashPct = flashTarget > 0 ? (flashProgress / flashTarget) * 100 : 0;
    const flashUrgent = flashQuest && liveFlashSeconds > 0 && liveFlashSeconds < 1800;
    const flashVisible = flashQuest && liveFlashSeconds > 0;

    /* Subtitle: just "X/Y completed" — the reset timer is shown on its
     * own live-ticking pill next to the title. */
    const headerSubtitle = `${completedCount}/${totalCount} completed`;

    /* Header reward chip */
    let headerChip = null;
    if (hasClaimableRewards) {
        const amountFmt = totalAfterMultiplier > 0
            ? `+${Math.round(totalAfterMultiplier / 1_000_000).toLocaleString()}`
            : null;
        const invitesFmt = pendingInviteCodes > 0
            ? `+${pendingInviteCodes} invite${pendingInviteCodes > 1 ? 's' : ''}`
            : null;
        headerChip = (
            <HeaderBadge $tint="#22C55E">
                <span aria-hidden="true">✨</span>
                {amountFmt || invitesFmt}
            </HeaderBadge>
        );
    }

    /* CTA label */
    let ctaLabel;
    if (claiming) ctaLabel = 'Claiming…';
    else if (!claimingAvailable) ctaLabel = 'Payouts Coming Soon';
    else if (hasClaimableRewards) ctaLabel = 'Claim Rewards';
    else if (allComplete) ctaLabel = 'All Quests Complete';
    else ctaLabel = 'Complete Quests to Earn';

    const ctaDisabled = !hasClaimableRewards || claiming || !claimingAvailable;

    return (
        <>
            <CardContainer $feedViewMode={feedViewMode} role="region" aria-label="Daily Quests">
                <Header type="button" onClick={onToggleCollapse} aria-expanded={!collapsed}>
                    <TitleRow>
                        <IconTile $tint="#F59E0B">🏆</IconTile>
                        <TitleStack>
                            <TitleLine>
                                <TitleText>Daily Quests</TitleText>
                                {liveResetSeconds > 0 && (
                                    <HeaderResetTimer title="Time until daily quest reset">
                                        {formatTimeCompact(liveResetSeconds)} left
                                    </HeaderResetTimer>
                                )}
                            </TitleLine>
                            <SubtitleText>{headerSubtitle}</SubtitleText>
                        </TitleStack>
                    </TitleRow>
                    <HeaderRight>
                        {headerChip}
                        {rewardMultiplier > 1 && (
                            <MultiplierBadge title="Loyalty multiplier increases from 1.0x to 5.0x over your first 50 completed quests">
                                {rewardMultiplier.toFixed(2)}x
                            </MultiplierBadge>
                        )}
                        <Chevron $collapsed={collapsed} aria-hidden="true" />
                    </HeaderRight>
                </Header>

                {!collapsed && (
                    <Body>
                        {/* Flash quest */}
                        {flashVisible && (
                            <>
                                <SectionLabel>Flash Quest</SectionLabel>
                                <FlashCard>
                                <FlashHeader>
                                    <FlashBadge>
                                        <span aria-hidden="true">⚡</span> Flash
                                    </FlashBadge>
                                    {!flashQuest.completed && (
                                        <FlashTimer $urgent={flashUrgent}>
                                            <span aria-hidden="true">⏱</span>
                                            {formatTimeCompact(liveFlashSeconds)}
                                        </FlashTimer>
                                    )}
                                </FlashHeader>
                                <FlashRow>
                                    <QuestStatusIcon $completed={flashQuest.completed} aria-hidden="true" />
                                    <FlashTitleText $completed={flashQuest.completed}>
                                        {flashQuest.title}
                                    </FlashTitleText>
                                    <FlashProgressText>
                                        {flashProgress}/{flashQuest.target}
                                    </FlashProgressText>
                                </FlashRow>
                                <FlashProgressTrack>
                                    <FlashProgressFill $pct={flashPct} $completed={flashQuest.completed} />
                                </FlashProgressTrack>
                                </FlashCard>
                            </>
                        )}

                        {/* Quest list — mobile-style bigger cards with per-quest progress */}
                        <SectionLabel>Today's Quests</SectionLabel>
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
                                const rewardText = getQuestRewardDisplay(quest.rewards, rewardMultiplier);
                                const detailItems = buildQuestDetails(quest);
                                const isBalanced = quest.action_type === 'balanced_vote' && quest.target_upvotes !== undefined;
                                const actionTint = getActionColor(quest.action_type);
                                const actionEmoji = getActionEmoji(quest.action_type);
                                const questPct = target > 0 ? (clampedProgress / target) * 100 : 0;

                                return (
                                    <QuestRow key={quest.id} $completed={quest.completed}>
                                        <QuestRowHeader>
                                            <QuestActionTile $tint={actionTint} aria-hidden="true">
                                                {actionEmoji}
                                                {quest.completed && <QuestCompleteBadge />}
                                            </QuestActionTile>
                                            <QuestRowBody>
                                                <QuestTopLine>
                                                    <QuestRowTitle $completed={quest.completed}>{quest.title}</QuestRowTitle>
                                                    {rewardText && !quest.completed && (
                                                        <QuestRowReward>{rewardText}</QuestRowReward>
                                                    )}
                                                </QuestTopLine>
                                            </QuestRowBody>
                                        </QuestRowHeader>

                                        {/* Bullet-point details (description + requirements) */}
                                        {detailItems.length > 0 && (
                                            <QuestDetailsList>
                                                {detailItems.map((item, idx) => (
                                                    <QuestDetailItem key={idx}>{item}</QuestDetailItem>
                                                ))}
                                            </QuestDetailsList>
                                        )}

                                        {/* Footer: progress bar + "n/target" + percent (or balanced split) */}
                                        {isBalanced ? (
                                            <>
                                                {/* Mobile `QuestRequirements` renders dual colored
                                                 * ↑/↓ progress bars for balanced_vote so each
                                                 * side is visually trackable. Mirror the exact
                                                 * layout here. */}
                                                <BalancedBarsGrid>
                                                    <BalancedBarRow title="Upvotes">
                                                        <BalancedArrow $tint={BALANCED_UP_COLOR} aria-hidden="true">↑</BalancedArrow>
                                                        <BalancedTrack>
                                                            <BalancedFill
                                                                $tint={BALANCED_UP_COLOR}
                                                                $pct={targetUpvotes > 0 ? (clampedUpvotes / targetUpvotes) * 100 : 0}
                                                            />
                                                        </BalancedTrack>
                                                        <BalancedCount>
                                                            {clampedUpvotes}/{quest.target_upvotes}
                                                        </BalancedCount>
                                                    </BalancedBarRow>
                                                    <BalancedBarRow title="Downvotes">
                                                        <BalancedArrow $tint={BALANCED_DOWN_COLOR} aria-hidden="true">↓</BalancedArrow>
                                                        <BalancedTrack>
                                                            <BalancedFill
                                                                $tint={BALANCED_DOWN_COLOR}
                                                                $pct={targetDownvotes > 0 ? (clampedDownvotes / targetDownvotes) * 100 : 0}
                                                            />
                                                        </BalancedTrack>
                                                        <BalancedCount>
                                                            {clampedDownvotes}/{quest.target_downvotes}
                                                        </BalancedCount>
                                                    </BalancedBarRow>
                                                </BalancedBarsGrid>
                                                <QuestRowFooter>
                                                    <QuestRowProgress>
                                                        {clampedProgress} / {quest.target}
                                                    </QuestRowProgress>
                                                    <QuestRowPercent $completed={quest.completed}>
                                                        {quest.completed ? 'Completed!' : `${Math.round(questPct)}%`}
                                                    </QuestRowPercent>
                                                </QuestRowFooter>
                                            </>
                                        ) : (
                                            <>
                                                <QuestRowProgressTrack>
                                                    <QuestRowProgressFill
                                                        $pct={questPct}
                                                        $tint={actionTint}
                                                        $completed={quest.completed}
                                                    />
                                                </QuestRowProgressTrack>
                                                <QuestRowFooter>
                                                    <QuestRowProgress>
                                                        {clampedProgress} / {quest.target}
                                                    </QuestRowProgress>
                                                    <QuestRowPercent $completed={quest.completed}>
                                                        {quest.completed ? 'Completed!' : `${Math.round(questPct)}%`}
                                                    </QuestRowPercent>
                                                </QuestRowFooter>
                                            </>
                                        )}
                                    </QuestRow>
                                );
                            })}
                        </QuestList>

                        {/* Footer: CTA (loyalty multiplier is shown in the progress header) */}
                        <ClaimFooter>
                            <CtaButton
                                type="button"
                                onClick={handleClaim}
                                disabled={ctaDisabled}
                                title={!claimingAvailable ? 'Reward distribution is not yet configured' : undefined}
                            >
                                {ctaLabel}
                            </CtaButton>
                        </ClaimFooter>

                        {claimError && <ClaimErrorMessage>{claimError}</ClaimErrorMessage>}

                        {/* Debug panel */}
                        {debugEnabled && (
                            <div style={{ marginTop: '0.3rem' }}>
                                <DebugButton onClick={() => setShowDebug(!showDebug)}>
                                    {showDebug ? '🔧 Hide Debug' : '🔧 Debug'}
                                </DebugButton>
                                {showDebug && (
                                    <DebugPanel>
                                        <DebugTitle>🔧 Quest Debug Panel</DebugTitle>
                                        {debugLoading ? (
                                            <div>Loading…</div>
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
                    </Body>
                )}
            </CardContainer>

            {/* Celebration overlay */}
            {showCelebration && (
                <CelebrationOverlay onClick={closeCelebration}>
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
                        <CelebrationEmojiWrap>
                            <CelebrationEmoji>🎉</CelebrationEmoji>
                        </CelebrationEmojiWrap>
                        <CelebrationEyebrow>Rewards Claimed</CelebrationEyebrow>
                        <CelebrationTitle>Nice work!</CelebrationTitle>
                        <CelebrationSubtitle>
                            Your rewards have been added to your account.
                        </CelebrationSubtitle>
                        <RewardsList>
                            {claimedAmount > 0 && (
                                <RewardRow>
                                    <RewardIcon><HiSparkles /></RewardIcon>
                                    <RewardMeta>
                                        <RewardLabel>Mirage</RewardLabel>
                                        <RewardValue>
                                            +{Math.round(claimedAmount / 1_000_000).toLocaleString()} MIRAGE
                                        </RewardValue>
                                    </RewardMeta>
                                </RewardRow>
                            )}
                            {claimedInviteCodes > 0 && (
                                <RewardRow>
                                    <RewardIcon><HiTicket /></RewardIcon>
                                    <RewardMeta>
                                        <RewardLabel>Invite Codes</RewardLabel>
                                        <RewardValue>
                                            +{claimedInviteCodes} Invite Code{claimedInviteCodes > 1 ? 's' : ''}
                                        </RewardValue>
                                    </RewardMeta>
                                </RewardRow>
                            )}
                        </RewardsList>
                        <CelebrationClose onClick={closeCelebration}>
                            Awesome
                        </CelebrationClose>
                    </CelebrationContent>
                </CelebrationOverlay>
            )}
        </>
    );
}
