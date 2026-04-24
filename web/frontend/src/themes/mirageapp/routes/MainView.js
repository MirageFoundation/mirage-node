import { Helmet } from "react-helmet-async";
import { useCallback, useEffect, useState } from "react";
import {
    HiNoSymbol,
    HiChevronDown,
    HiXMark,
    HiClipboardDocument,
    HiCheck,
    HiLink,
    HiShare,
} from "react-icons/hi2";
import { FaGooglePlay, FaApple } from "react-icons/fa6";
import { getThemeFamily } from "../../../registry/theme";
import Button from "../components/Button.js";
import LoggedOutPromptCard from "../components/LoggedOutPromptCard.js";
import QuestHeroCard from "../components/QuestHeroCard.js";
import FeedRightRail from "../components/FeedRightRail.js";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import { FeedSortToggle, FeedViewToggle, loadViewMode, saveViewMode, VIEW_MODE_CHANGE_EVENT } from "../ListFeedView.js";
import { FeedCardSkeletonList, FeedCardSkeleton, PageHeaderSkeleton } from "../components/Skeleton.js";
import ShowMoreButton from "../components/ShowMoreButton.js";
import styled, { keyframes, useTheme } from "styled-components";
import { Link } from "react-router-dom";
import Storage from "../../../utils/Storage";
import * as tx from "../../../utils/tx";
import { isSubscribed, subscribe, unsubscribe, invalidateCache as invalidateTopicsCache } from "../../../utils/Subscriptions";
import { ContentGrid, ModernPostFeed, StyledError, OLDREDDIT_SHELL_INSET_X } from "../Layout";
import { useMain } from "../../../logic/useMain";
import { requireThemeColor } from "../../../utils/themeColor";

// Mobile header branding for home/following feeds

// Invite-only card — adapted from mirage-mobile-app `InviteCodesCard`:
// clean panel surface, icon tile + title/subtitle + count badge + chevron header,
// collapsed body = subtitle paragraph + brand-blue "Share Invite Code" CTA.
const FeedHeroColumn = styled.div.attrs(({ $feedViewMode }) => ({
    'data-feed-view-mode': $feedViewMode,
}))`
    width: 100%;
    max-width: 820px;
    margin: 0;

    @media (min-width: 1001px) {
        [data-sidebar-hidden='true'] &[data-feed-view-mode='card'] {
            width: 100%;
            max-width: 820px;
            margin-left: auto;
            margin-right: auto;
        }

        [data-sidebar-hidden='true'] &[data-feed-view-mode='compact'] {
            width: 80%;
            max-width: none;
            margin: 0;
        }
    }

    /* Very large screens (> average laptop): lock the hero column to a
     * fixed centered width so it tracks the stable feed column regardless
     * of sidebar visibility OR feed view mode. */
    @media (min-width: 1500px) {
        [data-sidebar-hidden] &[data-feed-view-mode] {
            width: 100%;
            max-width: 820px;
            margin-left: auto;
            margin-right: auto;
        }
    }
`;

/**
 * `FeedSkeletonColumn` mirrors the width rules applied by `ListFeedView`'s
 * `FeedList` so loading-state skeletons render at the same width as real
 * posts — 820px card / 80% compact when the sidebar is hidden — on home,
 * following, and topic feeds. Keeping this parallel to `FeedHeroColumn`
 * avoids cross-file coupling and makes the wrapper explicit at the
 * skeleton render sites.
 */
const FeedSkeletonColumn = styled.div.attrs(({ $feedViewMode }) => ({
    'data-feed-view-mode': $feedViewMode,
}))`
    width: 100%;
    max-width: 820px;
    margin: 0;

    @media (min-width: 1001px) {
        [data-sidebar-hidden='true'] &[data-feed-view-mode='card'] {
            width: 100%;
            max-width: 820px;
            margin-left: auto;
            margin-right: auto;
        }

        [data-sidebar-hidden='true'] &[data-feed-view-mode='compact'] {
            width: 80%;
            max-width: none;
            margin: 0;
        }
    }

    /* Very large screens (> average laptop): lock the skeleton column to a
     * fixed centered width so loading state matches the stable feed column
     * regardless of sidebar visibility OR feed view mode. */
    @media (min-width: 1500px) {
        [data-sidebar-hidden] &[data-feed-view-mode] {
            width: 100%;
            max-width: 820px;
            margin-left: auto;
            margin-right: auto;
        }
    }
`;

const InviteOnlyBanner = styled.div`
    /* Match the post CardView exactly (border-radius: 8px; margin: 4px 0)
     * so this banner aligns with the feed column and shares the same bg. */
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
    align-self: flex-start;
    margin: 4px 0;
    /* Match the main page bg so the banner blends with the feed
     * (no "floating card" look). */
    background: ${({ theme }) => requireThemeColor(theme, 'bg')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 8px;
    overflow: hidden;
    box-shadow: none;

    @media (max-width: 600px) {
        border-radius: 6px;
    }
`;
const InviteHeaderButton = styled.button`
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
const InviteTitleRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex: 1;
    min-width: 0;
`;
const InviteIconTile = styled.div`
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    border-radius: 7px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.8rem;
    line-height: 1;
    color: #667eea;
    background: transparent;
`;
const InviteTitleStack = styled.div`
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
    flex: 1;
`;
const InviteTitleText = styled.div`
    font-size: 0.72rem;
    font-weight: 600;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;
const InviteSubtitleText = styled.div`
    font-size: 0.6rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
`;
const InviteHeaderRight = styled.div`
    display: flex;
    align-items: center;
    gap: 0.35rem;
    flex-shrink: 0;
`;
const InviteCountBadge = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    padding: 0.08rem 0.35rem;
    border-radius: 999px;
    font-size: 0.58rem;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    color: #667eea;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(102, 126, 234, 0.14)'
        : 'rgba(102, 126, 234, 0.24)'};
`;
/* Match the post-card chevron (HiChevronDown from react-icons/hi2).
 * Rotates -90deg when the panel is collapsed. */
const InviteChevron = styled(HiChevronDown)`
    display: inline-flex;
    width: 14px;
    height: 14px;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    transition: transform 0.2s ease;
    transform: rotate(${({ $collapsed }) => ($collapsed ? '-90deg' : '0deg')});
`;
const InviteContent = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
    padding: 0 1rem 0.6rem;

    @media (max-width: 600px) {
        padding: 0 0.85rem 0.55rem;
    }
`;
const InviteSubtitleBody = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.64rem;
    line-height: 1.35;
`;
const InviteBannerButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.35rem;
    width: 100%;
    padding: 0.42rem 0.75rem;
    font-size: 0.68rem;
    font-weight: 700;
    font-family: inherit;
    color: #FFFFFF;
    background: ${({ theme }) => requireThemeColor(theme, 'followBtnBg')};
    border: none;
    border-radius: 7px;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.15s ease, transform 0.15s ease, opacity 0.15s ease;

    &:hover:not(:disabled) {
        background: ${({ theme }) => requireThemeColor(theme, 'followBtnBgHover')};
        transform: translateY(-1px);
    }

    &:active:not(:disabled) {
        transform: translateY(0);
    }

    &:disabled {
        background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0, 0, 0, 0.05)'
        : 'rgba(255, 255, 255, 0.06)'};
        color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
        cursor: not-allowed;
    }
`;
const InviteBannerButtonArrow = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.9rem;
    line-height: 1;
    transform: translateY(-1px);
`;
/* Vertical breathing room between the invite banner and the quest card
 * so they don't visually collide. */
const HomeSectionSpacer = styled.div`
    height: 0.6rem;

    @media (max-width: 768px) {
        height: 0.5rem;
    }
`;
// Legacy alias kept so any stray references (e.g. older inline layouts) keep compiling.
// Newer JSX uses the explicit `InviteContent` + `InviteSubtitleBody` components.
const InviteBannerContentWrapper = InviteContent;
const InviteBannerTextContent = InviteSubtitleBody;
const InviteBannerCount = styled.span`
    font-size: 0.62rem;
    color: rgba(255, 255, 255, 0.85);
    font-weight: 500;
`;

// Collapse button for hero cards
const CollapseButton = styled.button`
    background: transparent;
    border: none;
    color: ${({
    theme
}) => requireThemeColor(theme, 'subtleText')};
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
        color: ${({
    theme
}) => requireThemeColor(theme, 'text')};
        background: ${({
    theme
}) => theme.name === 'light' ? 'rgba(0, 0, 0, 0.05)' : 'rgba(255, 255, 255, 0.05)'};
    }
`;

// ──────────────────────────────────────────────────────────────────────────
// Invite Code Modal — mirageapp-aligned share sheet.
//
// Visual language matches the rest of the theme's modals (ConfirmDialog /
// OptionModal / GiftDialogs):
//   • `panel` surface on `overlay` dim, 14px radius, fade-in + slide-up.
//   • Header / Body / Footer with 1px `border` dividers between sections.
//   • Primary CTA uses the shared `gradient` token; secondary rows sit on
//     `surface2` neutrals so they read as chrome, not decoration.
//   • Icons come from `react-icons/hi2` (HiXMark, HiClipboardDocument,
//     HiCheck, HiLink, HiShare) — no raw emoji glyphs in controls.
// ──────────────────────────────────────────────────────────────────────────

const inviteFadeIn = keyframes`
    from { opacity: 0; }
    to   { opacity: 1; }
`;

const inviteSlideUp = keyframes`
    from { transform: translateY(8px); opacity: 0; }
    to   { transform: translateY(0);   opacity: 1; }
`;

const InviteModalOverlay = styled.div`
    position: fixed;
    inset: 0;
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
    background: ${({ theme }) => theme.colors.overlay};
    animation: ${inviteFadeIn} 0.15s ease;
`;

const InviteModalContent = styled.div`
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 14px;
    width: 100%;
    max-width: 440px;
    max-height: calc(100vh - 2rem);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
    animation: ${inviteSlideUp} 0.2s ease;
`;

const InviteModalHeader = styled.div`
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.85rem 1rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const InviteModalHeroIcon = styled.div`
    width: 36px;
    height: 36px;
    border-radius: 10px;
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: #FFFFFF;
    background: ${({ theme }) => theme.colors.gradient};

    svg {
        width: 20px;
        height: 20px;
        fill: #FFFFFF;
    }
`;

// Mirage app brand mark — palm tree glyph (same SVG as LoggedOutPromptCard /
// AuthPageShell so the invite modal feels like a first-party Mirage surface).
const MiragePalmTreeIcon = () => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 527.41 593.64" aria-hidden="true">
        <path d="M85.03,197.11c-.77-.41-1.02,1.23-1.27,1.98-.89,4.66-1.97,9.3-2.97,13.74-4.2,16.58-.74,36.06-12.57,49.79-19.98,21.05-35.86,46.61-49.24,72.25-2.54,4.08-5,14.71-9.37,11.16-10.87-20.06-10.77-56.33-8.13-80.05,8.11-74.35,64.71-133.17,140.39-137.47,25.49-1.82,51.61,1.9,75.05,12.03,4.28,1.83,3.56-.9,1.44-3.38-14.47-18.53-32.09-34.46-50.45-48.97-6.85-5.97,2.67-9.75,4.16-15.29-.57-2.2-4.03-.86-6.05-.95-5.01.31-11.57.58-15.54-.33-9.76-3.12-17.1-10.88-26.25-15.46-2.83-1.81-7.17-3.15-8.24-6.48-.16-4.05,3.86-8.93,5.99-12.27,4.72-5.67.85-5.42-4.33-3.97-6.1,1.49-12.2,4.27-18.51,4.21-8.89-.62-19.71-5.44-28.83-7.13-10.53-2.21-21.48-3.4-32.19-4.48-1.55-.15-3.18-.2-4.71-.48-1.54-.26-2.54-.96-2.43-1.92.18-1.21,1.22-2.15,2.13-2.92,12.76-9.25,31.39-14.68,45.47-17.65,87.21-17.38,152.37,47.81,181.95,123.22.62.03,1.13-1.02,1.55-2.36.56-1.92,1.07-3.92,1.74-5.79C288.75,45.92,362.99-15.54,441.97,3.5c13.15,2.8,26.57,8.26,38.43,14.69,3.05,2.01,5.62,3.08,6.83,5.59.2.77-.49,1.33-1.99,1.58-1.8.29-4.39.29-6.49.37-27.45.93-54.01,10.14-75.58,27.36-5.24,4.36-12.11,1.67-18.25.55-3.09-.75-6.54-.66-10.08-.72-2.63.05-6.46-.29-8.81.48-.61.3-.68.76-.27,1.32,3.71,3.17,10.62,6.8,13.43,10.29,1.92,2.1.07,4.3-1.96,5.72-27.33,20.52-55.82,41.74-78,68.06-3.59,4.29-1.27,4.95,3.04,2.8,101.2-46.59,244.69,12.48,222.91,138.05-1.12,4.66-2.51,9.22-4.48,13.59-1.59,3.35-3.35,5.73-7.15,2.78-8.67-6.91-16.19-15.31-24-23.21-13.03-13.67-27.22-26.21-42.42-37.49-9.29-6.31-15.87-10.04-16.58-22.27-1.12-8.18-3.49-16.18-5.39-24.18-.61-2.73-1.76-3.87-3.15-.85-2.97,5.04-4.39,22.37-9.19,23.78-4.76.73-8.88-4.31-13.09-6-39.7-21.77-83.93-26.94-128.72-25.07-4.85.08-6.56,4.21-7.78,8.3-39.34,131.64-2.05,288.21,88.55,390.43,5.01,4.53,6.1,11.99-3.63,13.79-35.93.13-72.02.82-107.94-.04-9-.37-19.77,1.45-23.34-9.2-21.22-77.97-26.49-159.48-23.41-240.19,1.04-22.78,3.56-45.49,8.02-67.89,6.36-31.78,16.54-63.02,32.21-91.36,2.95-4.91-2.26-4.82-5.58-4.85-8.36-.08-17.58.72-26.01,1.57-38.68,4.18-71.21,22.85-100.3,47.6-2.41,1.7-5.2,5.72-8.19,5.7-2.89-1.86-2.41-6.9-3.35-9.94-1.36-7.2-2.46-14.46-3.74-21.64-.48-1.8-.37-4.37-1.43-5.85l-.05-.05Z"/>
    </svg>
);

const InviteModalTitleStack = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    min-width: 0;
    flex: 1;
`;

const InviteModalTitle = styled.h2`
    font-size: 0.82rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
    margin: 0;
    line-height: 1.3;
`;

const InviteModalSubtitle = styled.div`
    font-size: 0.7rem;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.35;
`;

const InviteModalClose = styled.button`
    background: transparent;
    border: none;
    color: ${({ theme }) => theme.colors.subtleText};
    cursor: pointer;
    padding: 0;
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    flex-shrink: 0;
    transition: background 0.12s ease, color 0.12s ease;

    svg {
        width: 20px;
        height: 20px;
    }

    &:hover {
        color: ${({ theme }) => theme.colors.text};
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    &:focus,
    &:focus-visible {
        outline: none;
        box-shadow: none;
    }
`;

const InviteModalBody = styled.div`
    padding: 0.85rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    overflow-y: auto;
`;

const InviteCodeDisplay = styled.div`
    display: flex;
    align-items: center;
    gap: 0.6rem;
    background: ${({ theme }) => theme.colors.surface2};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
    padding: 0.65rem 0.8rem;
`;

const InviteCodeStack = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
    flex: 1;
`;

const InviteCodeLabel = styled.div`
    font-size: 0.55rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const InviteCodeText = styled.div`
    font-size: 1.1rem;
    font-weight: 700;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    color: ${({ theme }) => theme.colors.text};
    letter-spacing: 0.1em;
    line-height: 1.2;
    word-break: break-all;

    @media (max-width: 400px) {
        font-size: 1rem;
        letter-spacing: 0.08em;
    }
`;

const InviteCodeCopyIcon = styled.button`
    appearance: none;
    width: 34px;
    height: 34px;
    flex-shrink: 0;
    border-radius: 8px;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme, $copied }) =>
        $copied ? theme.colors.buttonSuccessBg : theme.colors.panel};
    color: ${({ theme, $copied }) =>
        $copied ? theme.colors.voteUp : theme.colors.text};
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;

    svg {
        width: 16px;
        height: 16px;
    }

    &:hover {
        background: ${({ theme, $copied }) =>
            $copied ? theme.colors.buttonSuccessBg : theme.colors.hoverBg};
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    &:focus,
    &:focus-visible {
        outline: none;
        box-shadow: none;
    }
`;

// Primary action row: Copy Link (neutral) + Share (gradient CTA).
const InvitePrimaryActions = styled.div`
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;

    @media (max-width: 380px) {
        grid-template-columns: 1fr;
    }
`;

const InviteActionButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.45rem;
    padding: 0.6rem 0.75rem;
    font-family: inherit;
    font-size: 0.72rem;
    font-weight: 600;
    line-height: 1;
    color: ${({ theme }) => theme.colors.text};
    background: ${({ theme }) => theme.colors.surface2};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 9px;
    cursor: pointer;
    transition: background 0.12s ease, border-color 0.12s ease;

    svg {
        width: 15px;
        height: 15px;
    }

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.hoverBg};
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    &:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }

    &:focus,
    &:focus-visible {
        outline: none;
        box-shadow: none;
    }
`;

const InvitePrimaryCta = styled(InviteActionButton)`
    background: ${({ theme }) => theme.colors.gradient};
    border: none;
    color: #FFFFFF;

    &:hover:not(:disabled) {
        filter: brightness(1.08);
        background: ${({ theme }) => theme.colors.gradient};
        border: none;
    }

    &:active {
        filter: brightness(0.98);
    }
`;

const InviteSocialDivider = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.1rem 0 0;
    font-size: 0.55rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.subtleText};

    &::before,
    &::after {
        content: '';
        flex: 1;
        height: 1px;
        background: ${({ theme }) => theme.colors.border};
    }
`;

const InviteSocialGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.5rem;

    @media (max-width: 380px) {
        grid-template-columns: 1fr;
    }
`;

const InviteSocialButton = styled.a`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.45rem;
    padding: 0.55rem 0.7rem;
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: 500;
    line-height: 1;
    text-decoration: none;
    color: ${({ theme }) => theme.colors.text};
    background: ${({ theme }) => theme.colors.surface2};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
        border-color: ${({ theme }) => theme.colors.borderStrong};
        color: ${({ theme }) => theme.colors.text};
        text-decoration: none;
    }
`;

const InviteModalFooter = styled.div`
    padding: 0.6rem 1rem 0.75rem;
    border-top: 1px solid ${({ theme }) => theme.colors.border};
    text-align: center;
    font-size: 0.65rem;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const InviteNoCodesText = styled.div`
    text-align: center;
    padding: 0.85rem 0;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.75rem;
    line-height: 1.5;
`;

// Top feed title row for home/following feeds — matches InboxView HeaderRow spacing
const HomeFeedTitleBar = styled.div`
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
    align-self: flex-start;
    margin: 0;
    padding: 0.5rem 1rem;

    @media (max-width: 600px) {
        padding: 0.5rem 0;
    }
`;

// NSFW welcome hero — mirageapp: compact, app-style card using the
// Mirage gradient accent. Matches the visual language of InviteOnlyBanner
// (blends with page bg, rounded 8px, themed border) and TopicHeroCard.
const NsfwWelcomeHero = styled.div.attrs(({ $feedViewMode }) => ({
    'data-feed-view-mode': $feedViewMode,
}))`
    box-sizing: border-box;
    width: 100%;
    /* Width rules mirror FeedList (ListFeedView.js) + FeedHeroColumn so the
     * consent card tracks the post column across both feed view modes and
     * the sidebar-hidden state:
     *   - default / sidebar visible: capped at 820px, left-aligned.
     *   - sidebar hidden + card view:    centered 820px column.
     *   - sidebar hidden + compact view: 80% wide, left-aligned. */
    max-width: 820px;
    margin: 4px 0;

    @media (min-width: 1001px) {
        [data-sidebar-hidden='true'] &[data-feed-view-mode='card'] {
            width: 100%;
            max-width: 820px;
            margin-left: auto;
            margin-right: auto;
        }

        [data-sidebar-hidden='true'] &[data-feed-view-mode='compact'] {
            width: 80%;
            max-width: none;
            margin: 4px 0;
        }
    }

    /* Very large screens (> average laptop): lock the consent hero to a
     * fixed centered width so it tracks the stable feed column regardless
     * of sidebar visibility OR feed view mode. */
    @media (min-width: 1500px) {
        [data-sidebar-hidden] &[data-feed-view-mode] {
            width: 100%;
            max-width: 820px;
            margin-left: auto;
            margin-right: auto;
        }
    }

    /* Red tint — mirrors the danger palette used elsewhere in mirageapp
     * (ReferralsView danger cards, Settings danger buttons): a soft
     * voteDownBg wash + buttonDangerBorder outline so the consent
     * prompt reads as a cautionary NSFW-flavored card. */
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(255, 59, 48, 0.06)'
        : 'rgba(255, 69, 58, 0.08)'};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'buttonDangerBorder')};
    border-radius: 8px;
    padding: 0.75rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    overflow: hidden;

    @media (max-width: 600px) {
        border-radius: 6px;
        padding: 0.65rem 0.85rem;
    }
`;
const NsfwHeroHeader = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-width: 0;
`;
const NsfwHeroIconTile = styled.div`
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    border-radius: 7px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.85rem;
    line-height: 1;
    /* Icon tile picks up the same red wash so the 🔞 badge reads as
     * warning-toned without introducing a new token. */
    background: ${({ theme }) => requireThemeColor(theme, 'buttonDangerBg')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'buttonDangerBorder')};
`;
const NsfwHeroTitle = styled.div`
    font-size: 0.78rem;
    font-weight: 600;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    line-height: 1.2;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;
const NsfwHeroEmoji = styled.span`
    font-size: 0.95rem;
    line-height: 1;
`;
const NsfwHeroDescription = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.68rem;
    line-height: 1.5;

    strong {
        color: ${({ theme }) => requireThemeColor(theme, 'text')};
        font-weight: 600;
    }
`;
const NsfwHeroButtons = styled.div`
    display: flex;
    gap: 0.5rem;
    margin-top: 0.15rem;
    flex-wrap: wrap;

    @media (max-width: 600px) {
        gap: 0.4rem;
    }
`;
const NsfwHeroButton = styled.button`
    padding: 0.4rem 0.9rem;
    border-radius: 7px;
    font-size: 0.7rem;
    font-weight: 600;
    cursor: pointer;
    transition: transform 0.15s ease, background 0.15s ease,
        border-color 0.15s ease, color 0.15s ease;
    border: 1px solid transparent;
    line-height: 1.2;

    &:focus-visible {
        outline: 2px solid ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        outline-offset: 2px;
    }

    @media (max-width: 600px) {
        padding: 0.4rem 0.75rem;
        flex: 1;
        min-width: 80px;
    }

    ${({ $variant, theme }) => $variant === 'yes' ? `
        background: ${requireThemeColor(theme, 'voteDown')};
        color: #ffffff;
        border-color: ${requireThemeColor(theme, 'voteDown')};
        &:hover {
            transform: translateY(-1px);
            background: ${requireThemeColor(theme, 'voteDownHover')};
            border-color: ${requireThemeColor(theme, 'voteDownHover')};
        }
    ` : `
        background: transparent;
        color: ${requireThemeColor(theme, 'text')};
        border-color: ${requireThemeColor(theme, 'buttonDangerBorder')};
        &:hover {
            background: ${requireThemeColor(theme, 'buttonDangerBg')};
            border-color: ${requireThemeColor(theme, 'voteDown')};
        }
    `}
`;
const NsfwHeroNote = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.6rem;
    line-height: 1.4;
    margin-top: 0.1rem;

    a {
        color: ${({ theme }) => requireThemeColor(theme, 'link')};
        text-decoration: none;
        &:hover {
            text-decoration: underline;
        }
    }
`;

// ============================================================
// App-download hero cards (Android + iPhone) — mirageapp theme
// Visuals match the QuestHeroCard language: flat panel on `bg`,
// 1px `border`, 8px radius, icon tile + title/subtitle header,
// gradient CTA button, neutral dismiss pill.
// Platform color accents (Google green / Apple blue) are kept for
// the icon tile + CTA so the cards still read as store-specific.
// ============================================================
const ANDROID_ACCENT = '#34A853';
const IPHONE_ACCENT = '#007AFF';

const AndroidAppHero = styled.div`
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
    align-self: flex-start;
    margin: 4px 0;
    background: ${({ theme }) => requireThemeColor(theme, 'bg')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 8px;
    padding: 0.7rem 1rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    box-shadow: none;

    @media (max-width: 600px) {
        border-radius: 6px;
        padding: 0.6rem 0.85rem 0.65rem;
    }
`;
const IPhoneAppHero = styled(AndroidAppHero)``;

/* Title row: icon tile + stacked title/subtitle */
const AndroidHeroTitle = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-width: 0;
    font-size: 0.78rem;
    font-weight: 600;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    line-height: 1.25;
`;

/* Store-icon slot — no background tile, just the platform-tinted glyph
 * sitting inline with the title. */
const AndroidHeroEmoji = styled.span`
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
    background: transparent;
    color: ${({ theme }) => (theme.name === 'light' ? '#000' : '#fff')};

    svg {
        width: 18px;
        height: 18px;
    }

    ${IPhoneAppHero} && {
        color: ${({ theme }) => (theme.name === 'light' ? '#000' : '#fff')};
        width: 22px;
        height: 22px;

        svg {
            width: 22px;
            height: 22px;
        }
    }
`;

const AndroidHeroDescription = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.65rem;
    line-height: 1.4;
`;

const AndroidHeroButtons = styled.div`
    display: flex;
    gap: 0.4rem;
    margin-top: 0.1rem;
    flex-wrap: wrap;
`;

/* Primary CTA — platform-tinted gradient, matches QuestHeroCard's
 * `CtaButton` geometry (7px radius, 0.42rem × 0.75rem padding). */
const AndroidHeroButton = styled.a`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    flex: 1;
    min-width: 120px;
    padding: 0.42rem 0.75rem;
    border-radius: 7px;
    font-size: 0.68rem;
    font-weight: 700;
    font-family: inherit;
    text-decoration: none;
    text-align: center;
    color: #fff;
    border: none;
    cursor: pointer;
    background: linear-gradient(90deg, #34A853 0%, #1E7E34 100%);
    box-shadow: 0 1px 5px rgba(52, 168, 83, 0.22);
    transition: opacity 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;

    &:hover {
        opacity: 0.92;
        transform: translateY(-1px);
        box-shadow: 0 2px 8px rgba(52, 168, 83, 0.3);
        color: #fff;
        text-decoration: none;
    }

    &:active {
        transform: translateY(0);
    }

    svg {
        width: 0.9rem;
        height: 0.9rem;
        flex-shrink: 0;
    }
`;

const IPhoneHeroButton = styled(AndroidHeroButton)`
    background: linear-gradient(90deg, #007AFF 0%, #5856D6 100%);
    box-shadow: 0 1px 5px rgba(0, 122, 255, 0.22);

    &:hover {
        box-shadow: 0 2px 8px rgba(0, 122, 255, 0.3);
    }

    svg {
        width: 1.1rem;
        height: 1.1rem;
    }
`;

/* Neutral dismiss pill — same geometry as CTA, subtle surface */
const AndroidHeroDismiss = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 1;
    min-width: 100px;
    padding: 0.42rem 0.75rem;
    border-radius: 7px;
    font-size: 0.68rem;
    font-weight: 600;
    font-family: inherit;
    cursor: pointer;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0, 0, 0, 0.04)'
        : 'rgba(255, 255, 255, 0.06)'};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    transition: background 0.15s ease, color 0.15s ease;

    &:hover {
        background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0, 0, 0, 0.07)'
        : 'rgba(255, 255, 255, 0.1)'};
        color: ${({ theme }) => requireThemeColor(theme, 'text')};
    }
`;
const HomeFeedInfoTitle = styled.div`
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: ${({
    theme
}) => theme.colors.text};
    display: flex;
    align-items: center;
    gap: 0;
    line-height: 1.2;
`;
const HomeFeedHeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
`;
const HomeFeedModeInline = styled.div`
    display: flex;
    align-items: center;
    gap: 0.2rem;
    font-size: 0.7rem;
`;
const HomeFeedModeSelect = styled.select`
    font-size: 0.65rem;
    padding: 0.15rem 0.35rem;
    border-radius: 6px;
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    background: ${({
    theme
}) => theme.colors.inputBackground};
    color: ${({
    theme
}) => theme.colors.text};
    outline: none;
    box-shadow: ${({
    theme
}) => theme.name === 'light' ? '0 1px 2px rgba(0,0,0,0.08)' : 'none'};
`;

// Post header card shown on single post view
const PostHeaderCard = styled.div`
    margin-top: 0.5rem;
    margin-left: 1rem;
    margin-right: 1rem;
    background-color: ${({
    theme
}) => requireThemeColor(theme, 'card')};
    border: 1px solid ${({
    theme
}) => requireThemeColor(theme, 'cardBorder')};
    color: ${({
    theme
}) => theme.colors.text};
    border-radius: 6px;
    padding: 0.2rem 0.6rem 0.4rem 0.6rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    @media (max-width: 1000px) {
        margin-left: 0.25rem;
        margin-right: 0.25rem;
        padding: 0.3rem 0.6rem;
    }
`;
const PostHeaderText = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.6rem;
    line-height: 1.5;
`;
const TopicLinkInHeader = styled(Link)`
    color: ${({
    theme
}) => theme.colors.link};
    text-decoration: none;
    font-weight: 700;
    &:hover {
        color: ${({
    theme
}) => theme.colors.linkHover};
        text-decoration: underline;
        text-decoration-color: ${({
    theme
}) => theme.colors.link};
    }
`;
const PostHeaderTitle = styled.div`
    color: ${({
    theme
}) => theme.colors.text};
    font-size: 0.9rem;
    font-weight: bold;
`;
const HeaderInlineLink = styled.a`
    background: none;
    border: none;
    padding: 0;
    margin: 0;
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-weight: 700;
    font-size: 0.6rem;
    font-family: inherit;
    cursor: pointer;
    text-decoration: none;
    &:hover {
        color: ${({
    theme
}) => theme.colors.text};
        text-decoration: none;
    }
`;
/* inline subscribe/unsubscribe will be rendered via FilterBar rightAction */

// Removed old topics bar styled components (unused)

/** Feed column fills the full width — background is the app-wide bg so
 *  the feed reads as one continuous canvas (no panel/body color split). */
const MainFeedPanel = styled.div`
    width: 100%;
    background: ${({ theme }) => theme.colors.bg};
`;

/**
 * LoadingCard — flat list row, same surface as ListFeedView (no inset card / no body bg gaps)
 */
const LoadingCard = styled.div`
    margin-left: calc(-1 * ${OLDREDDIT_SHELL_INSET_X});
    margin-right: calc(-1 * ${OLDREDDIT_SHELL_INSET_X});
    width: calc(100% + 2 * ${OLDREDDIT_SHELL_INSET_X});
    max-width: none;
    padding: ${({
    $size
}) => ($size === 'compact' ? '0.75rem' : '1rem')} ${OLDREDDIT_SHELL_INSET_X};
    min-height: 5rem;
    background-color: ${({
    theme
}) => theme.colors.panel};
    border: none;
    border-radius: 0;
    border-bottom: 1px solid ${({
    theme
}) => theme.colors.border};
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: ${({
    $size
}) => $size === 'compact' ? '0.5rem' : '0.65rem'};
    box-sizing: border-box;
`;
const LoadingText = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.85rem;
    font-weight: 500;
`;

/**
 * Blocked-topic empty state — shown when the viewer navigates to `/t/<topic>`
 * where the topic is in their blocked list. Mirrors the `StateBlock`
 * pattern used across BlocksView / Follows / Reports so the visual
 * language stays consistent (circle icon + title + message + action).
 */
const BlockedTopicState = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
    padding: 3rem 1.25rem;
    text-align: center;
    /* Sits on the main feed canvas (theme.colors.bg) with no divider so
     * the empty state reads as part of the feed column, not a separate
     * panel (06.3 polish round 4). */
    background: ${({ theme }) => theme.colors.bg};
    margin-left: calc(-1 * ${OLDREDDIT_SHELL_INSET_X});
    margin-right: calc(-1 * ${OLDREDDIT_SHELL_INSET_X});
    width: calc(100% + 2 * ${OLDREDDIT_SHELL_INSET_X});
    box-sizing: border-box;
`;
const BlockedTopicIcon = styled.div`
    width: 56px;
    height: 56px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.voteDown};

    svg { width: 26px; height: 26px; }
`;
const BlockedTopicTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.95rem;
    font-weight: 700;
`;
const BlockedTopicMessage = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.78rem;
    line-height: 1.5;
    max-width: 26rem;
`;
const BlockedTopicActions = styled.div`
    display: flex;
    gap: 0.5rem;
    margin-top: 0.35rem;
`;

// TopicsBar removed (unused)

const InlineLink = styled(Link)`
    color: ${({
    theme
}) => theme.colors.link};
    text-decoration: none;
    font-weight: 700;
    &:hover {
        color: ${({
    theme
}) => theme.colors.linkHover};
        text-decoration: underline;
        text-decoration-color: ${({
    theme
}) => theme.colors.link};
    }
`;

// Topic header card (for topic pages) - unified with HomeFeedInfoCard
const TopicHeroCard = styled.div`
    margin-top: 1rem;
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.06) 0%, rgba(139, 92, 246, 0.06) 100%);
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: 10px;
    padding: 0.6rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;

    @media (max-width: 1000px) {
        border-radius: 8px;
        padding: 0.5rem 0.75rem;
    }

    @media (max-width: 768px) {
        border-radius: 6px;
        padding: 0.4rem 0.6rem;
        margin-top: 0.5rem;
    }
`;
const TopicHeroTitle = styled.div`
    font-size: 0.7rem;
    font-weight: 600;
    color: ${({
    theme
}) => theme.colors.text};
    display: flex;
    align-items: center;
    gap: 0.4rem;
    line-height: 1;

    @media (max-width: 1000px) {
    }
`;
const TopicHeroHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
`;
const TopicHeroDescription = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.65rem;
    line-height: 1.5;

    @media (max-width: 1000px) {
        line-height: 1.4;
    }

    strong {
        color: ${({
    theme
}) => theme.colors.text};
        font-weight: 600;
    }
`;

/**
 * EmptyHomeCard — flat full-width strip, aligned with list feed surface
 */
const EmptyHomeCard = styled.div`
    margin-left: calc(-1 * ${OLDREDDIT_SHELL_INSET_X});
    margin-right: calc(-1 * ${OLDREDDIT_SHELL_INSET_X});
    width: calc(100% + 2 * ${OLDREDDIT_SHELL_INSET_X});
    max-width: none;
    padding: 1.25rem ${OLDREDDIT_SHELL_INSET_X};
    background-color: ${({
    theme
}) => theme.colors.panel};
    border: none;
    border-radius: 0;
    border-bottom: 1px solid ${({
    theme
}) => theme.colors.border};
    text-align: center;
    box-sizing: border-box;
`;
const EmptyHomeTitle = styled.div`
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    color: ${({
    theme
}) => theme.colors.text};
`;
const EmptyHomeBody = styled.div`
    font-size: 0.8rem;
    line-height: 1.5;
    color: ${({
    theme
}) => theme.colors.subtleText};
`;
const EmptyHomeMessage = () => <EmptyHomeCard role="region" aria-label="Empty home feed">
    <EmptyHomeTitle>Your home feed is empty</EmptyHomeTitle>
    <EmptyHomeBody>
        Follow a few topics to personalize your feed. If this node is new, be the first to post. Browse <InlineLink to="/topics">topics</InlineLink> to get started.
    </EmptyHomeBody>
</EmptyHomeCard>;

// Session storage key helpers for feed state preservation (keyed by topic)

const MainView = ({
    state,
    setPosts,
    updatePost,
    setTopic,
    routeTopic
}) => {
    const theme = useTheme();
    const showHero = theme.caps.showHeroCards;
    const {
        urlTopic,
        currentTopicRef,
        error,
        stableOrder,
        setStableOrder,
        isLoading,
        hasMorePosts,
        homeSortMode,
        setHomeSortMode,
        oldRedditSort,
        handleOldRedditSortChange,
        cardSize,
        handleCardSizeChange,
        hideDownvotedPosts,
        hidingPostsSet,
        flashingPostsSet,
        isLoadingMore,
        isMobile,
        isTopicBlockedLocal,
        location,
        viewerAddress,
        followedTopicsSet,
        setFollowedTopicsSet,
        topicFollowHover,
        setTopicFollowHover,
        isTopicPending,
        formatTopicStatus,
        forceHardRefreshRef,
        dismissAndroidBanner,
        dismissIPhoneBanner,
        showNsfwHero,
        isLoggedIn,
        inviteCodesEnabled,
        questsEnabled,
        showAndroidBanner,
        showIPhoneBanner,
        inviteModalOpen,
        setInviteModalOpen,
        inviteCodeCopied,
        welcomeStats,
        welcomeStatsStale,
        inviteBannerCollapsed,
        questCardCollapsed,
        toggleInviteBanner,
        toggleQuestCard,
        nextAvailableCode,
        availableCodeCount,
        handleOpenInviteModal,
        handleCopyInviteCode,
        handleNativeShare,
        canNativeShare,
        getShareUrl,
        getShareText,
        handleNsfwChoice,
        bottomSentinelRef,
        loadMore
    } = useMain({
        state,
        setPosts,
        updatePost,
        setTopic,
        routeTopic
    });
    const [feedViewMode, setFeedViewMode] = useState(() => loadViewMode());
    useEffect(() => {
        const syncFeedViewMode = () => setFeedViewMode(loadViewMode());
        window.addEventListener(VIEW_MODE_CHANGE_EVENT, syncFeedViewMode);
        return () => window.removeEventListener(VIEW_MODE_CHANGE_EVENT, syncFeedViewMode);
    }, []);
    const handleFeedViewModeChange = useCallback((next) => {
        setFeedViewMode(next);
        saveViewMode(next);
    }, []);
    // Local UI state for invite modal "Copy Code" button (distinct from "Copy Link")
    const [rawCodeCopied, setRawCodeCopied] = useState(false);
    const handleCopyRawInviteCode = useCallback(async () => {
        const code = nextAvailableCode?.code;
        if (!code) return;
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(code);
            } else {
                const ta = document.createElement('textarea');
                ta.value = code;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            setRawCodeCopied(true);
            setTimeout(() => setRawCodeCopied(false), 2000);
        } catch (_err) {
            /* clipboard denied — silent */
        }
    }, [nextAvailableCode]);
    // Close the invite modal on Escape — matches ConfirmDialog / OptionModal.
    useEffect(() => {
        if (!inviteModalOpen) return undefined;
        const onKey = (e) => {
            if (e.key === 'Escape' || e.key === 'Esc') {
                e.preventDefault();
                setInviteModalOpen(false);
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [inviteModalOpen, setInviteModalOpen]);
    if (error) {
        return <StyledError>{error}</StyledError>;
    }
    const isPostView = location.pathname.startsWith('/p/');
    let header = null;
    if (isPostView) {
        const pid = (() => {
            if (location.pathname.startsWith('/p/')) {
                const raw = location.pathname.slice(3);
                return raw ? decodeURIComponent(raw) : null;
            }
            return null;
        })();
        const p = pid ? state.posts[pid] : null;
        if (p) {
            const topicKey = String(p.topic || '').trim().toLowerCase();
            const isTopicFollowing = topicKey && (followedTopicsSet.has(topicKey) || isSubscribed(viewerAddress || 'guest', p.topic));
            const isTopicInProgress = isTopicPending(topicKey);
            header = <PostHeaderCard role="region" aria-label="Post context">
                <PostHeaderText>
                    Posted in{' '}
                    <TopicLinkInHeader to={`/t/${p.topic}`} title={`View #${p.topic}`}>
                        #{p.topic}
                    </TopicLinkInHeader>{' '}
                    (
                    <HeaderInlineLink href="#" onClick={async e => {
                        e.preventDefault();
                        const key = topicKey;
                        if (!key) return;
                        if (isTopicPending(key)) return;
                        try {
                            const isCurrentlyFollowing = key && (followedTopicsSet.has(key) || isSubscribed(viewerAddress || 'guest', p.topic));
                            if (isCurrentlyFollowing) {
                                await unsubscribe(viewerAddress || 'guest', p.topic);
                                setFollowedTopicsSet(prev => {
                                    const next = new Set(prev);
                                    next.delete(key);
                                    return next;
                                });
                            } else {
                                await subscribe(viewerAddress || 'guest', p.topic);
                                setFollowedTopicsSet(prev => new Set([...prev, key]));
                            }
                            invalidateTopicsCache();
                            setStableOrder(s => s.slice());
                        } catch (_) {/* noop */ }
                    }}>
                        {isTopicInProgress ? formatTopicStatus(topicKey) : isTopicFollowing ? 'unfollow' : 'follow'}
                    </HeaderInlineLink>
                    )
                </PostHeaderText>
                <PostHeaderTitle>{p.title}</PostHeaderTitle>
            </PostHeaderCard>;
        }
    }
    const showPosts = () => {
        // Compute display state
        const displayTopic = currentTopicRef.current || urlTopic;
        const routeTopicLower = urlTopic ? String(urlTopic).toLowerCase() : '';
        const topicKeyLower = routeTopicLower || (displayTopic ? String(displayTopic).toLowerCase() : '');
        const isCurrentTopic = routeTopicLower && routeTopicLower !== 'home' && routeTopicLower !== 'all' && routeTopicLower !== 'following';
        const isTopicFollowing = isCurrentTopic && (followedTopicsSet.has(routeTopicLower) || isSubscribed(viewerAddress || 'guest', urlTopic));
        const isTopicInProgress = isCurrentTopic && isTopicPending(routeTopicLower);
        /**
         * When the viewer navigates to `/t/<topic>` for a topic they've
         * blocked, hide the feed and show a dedicated `BlockedTopicState`
         * panel with an Unblock CTA. Keeps the visual language of the
         * BlocksView state blocks (circle icon + title + message).
         */
        const isUrlTopicBlocked = !!(isLoggedIn && isCurrentTopic && typeof isTopicBlockedLocal === 'function' && isTopicBlockedLocal(routeTopicLower));

        // Determine what content to show
        let showEmptyHome = false;
        let showNoPostsAvailable = false;
        let showLoadingPosts = false;
        let orderedPosts = [];

        // Show loading when switching to a different topic
        const isTopicSwitching = isLoading && displayTopic !== urlTopic;
        // Force loading overlay even when posts exist (e.g., mode toggle / hard refresh)
        const isHardRefreshLoading = isLoading && forceHardRefreshRef.current;

        // Check loading states
        if (isHardRefreshLoading) {
            showLoadingPosts = true;
        } else if (isTopicSwitching) {
            // Switching topics - show loading immediately
            showLoadingPosts = true;
        } else if (!state.posts || Object.keys(state.posts).length === 0) {
            if (isLoading) {
                showLoadingPosts = true;
            } else if (displayTopic === 'home') {
                showEmptyHome = true;
            } else {
                showNoPostsAvailable = true;
            }
        } else if (isLoading && stableOrder.length === 0) {
            showLoadingPosts = true;
        } else {
            // Convert the posts object to an array once
            const postsArray = Object.values(state.posts || {});

            // Only include top-level posts (exclude comments or partial objects, deleted, and optimistically blocked topics)
            const isTopLevelPost = p => {
                if (!p || p.deleted) return false;
                if (p.hidden_client) return false;
                const hasTitle = typeof p.title === 'string' && p.title.trim().length > 0;
                const hasTopic = typeof p.topic === 'string' && p.topic.trim().length > 0;
                const topicVal = String(p.topic || '').trim().toLowerCase();
                const isReserved = ['all', 'home', 'following'].includes(topicVal);
                if (isTopicBlockedLocal(topicVal)) return false;
                return hasTitle && hasTopic && !isReserved;
            };
            const topLevelPosts = postsArray.filter(isTopLevelPost);
            const filteredPosts = displayTopic === "all" || displayTopic === "home" || displayTopic === "following" ? topLevelPosts : topLevelPosts.filter(post => String(post.topic || '').toLowerCase() === String(displayTopic || '').toLowerCase());
            if (filteredPosts.length === 0 && !isLoading) {
                if (displayTopic === 'home') {
                    showEmptyHome = true;
                } else {
                    showNoPostsAvailable = true;
                }
            } else {
                // Build a stable ordered list of posts
                const postsById = {};
                for (const p of filteredPosts) {
                    if (p && p.post_id && !p.deleted && !p.hidden_client) {
                        postsById[p.post_id] = p;
                    }
                }
                if (stableOrder.length > 0) {
                    orderedPosts = stableOrder.map(id => postsById[id]).filter(Boolean);
                } else {
                    orderedPosts = filteredPosts.filter(p => p && !p.deleted);
                }

                // Hide posts the viewer downvoted (Home only, client-side)
                if (displayTopic === 'home' && hideDownvotedPosts) {
                    orderedPosts = orderedPosts.filter(p => {
                        const postKey = String(p?.post_id || '').toLowerCase();
                        // If post is animating out, keep it in the list for now
                        if (hidingPostsSet.has(postKey)) return true;
                        // Prefer in-memory/state direction; backend provides user_vote on fetch.
                        const dir = Number(p?.direction ?? p?.user_vote ?? p?.my_vote ?? p?.myVote ?? p?.userVote ?? 0);
                        if (Number.isFinite(dir) && dir < 0) return false;
                        return true;
                    });
                }
            }
        }

        // Full-width main column + shell header (no left sidebar; old Reddit style)
        const pageTitle = urlTopic === 'home' ? 'Home' : urlTopic === 'following' ? 'Following' : urlTopic === 'all' ? 'All Posts' : `#${urlTopic}`;
        const noPostsMessage = urlTopic === 'following'
            ? 'No posts available. Follow people or topics to populate this feed.'
            : 'No posts available';
        return <ContentGrid>
            <Helmet>
                <title>{pageTitle} | Mirage</title>
            </Helmet>
            <FeedRailRow $feedViewMode={feedViewMode}>
            <FeedCol>
                {header}
                <MainFeedPanel>
                    <ModernPostFeed>

                        {isLoggedIn && isCurrentTopic && showHero && !isUrlTopicBlocked && <TopicHeroCard>
                            <TopicHeroHeader>
                                <TopicHeroTitle>#{urlTopic}</TopicHeroTitle>
                                <HomeFeedModeInline>
                                    <HomeFeedModeSelect value={homeSortMode} onChange={e => {
                                        const mode = e.target.value;
                                        setHomeSortMode(mode);
                                        Storage.save('home_sort_mode', mode);
                                    }}>
                                        <option value="magic">Magic</option>
                                        <option value="newest">Newest</option>
                                    </HomeFeedModeSelect>
                                    <HomeFeedModeSelect value={cardSize} onChange={e => handleCardSizeChange(e.target.value)}>
                                        <option value="large">Large</option>
                                        {!isMobile && <option value="compact">Compact</option>}
                                        <option value="media">Media</option>
                                    </HomeFeedModeSelect>
                                    <Button variant={isTopicFollowing && topicFollowHover ? 'primaryDanger' : isTopicFollowing ? 'subtle' : 'primary'} size="xs" minWidth="5.5rem" onMouseEnter={() => setTopicFollowHover(true)} onMouseLeave={() => setTopicFollowHover(false)} disabled={isTopicInProgress} onClick={async () => {
                                        const topicName = urlTopic;
                                        if (!topicName) return;
                                        const key = topicKeyLower;
                                        if (!key) return;
                                        if (isTopicPending(key)) return;
                                        try {
                                            if (isTopicFollowing) {
                                                await unsubscribe(viewerAddress || 'guest', topicName);
                                                setFollowedTopicsSet(prev => {
                                                    const next = new Set(prev);
                                                    next.delete(key);
                                                    return next;
                                                });
                                            } else {
                                                await subscribe(viewerAddress || 'guest', topicName);
                                                setFollowedTopicsSet(prev => new Set([...prev, key]));
                                            }
                                            invalidateTopicsCache();
                                        } catch (_) {/* noop */ }
                                    }}>
                                        {isTopicInProgress ? formatTopicStatus(topicKeyLower) : isTopicFollowing ? topicFollowHover ? 'Unfollow' : 'Following' : 'Follow'}
                                    </Button>
                                </HomeFeedModeInline>
                            </TopicHeroHeader>
                            <TopicHeroDescription>
                                Topic feed for #{urlTopic}. Follow this community to stay up to date with the latest posts, discussions, and updates from people actively contributing to this topic.
                            </TopicHeroDescription>
                        </TopicHeroCard>}

                        {(isLoggedIn && (urlTopic === 'home' || urlTopic === 'following')) && <FeedHeroColumn $feedViewMode={feedViewMode}>
                            {/* Keep only the feed title row at the top for home/following. */}
                            <HomeFeedTitleBar role="region" aria-label={`${urlTopic} feed header`}>
                                <HomeFeedHeaderRow>
                                    <HomeFeedInfoTitle>
                                        {urlTopic === 'home' ? 'Home' : 'Following'}
                                    </HomeFeedInfoTitle>
                                    <HomeFeedModeInline>
                                        <FeedSortToggle sortMode={oldRedditSort} onChange={handleOldRedditSortChange} />
                                        <FeedViewToggle viewMode={feedViewMode} onChange={handleFeedViewModeChange} />
                                    </HomeFeedModeInline>
                                </HomeFeedHeaderRow>
                            </HomeFeedTitleBar>
                            {/* Invite-only banner - shown only when invite codes are enabled on this node */}
                            {inviteCodesEnabled && <InviteOnlyBanner role="region" aria-label="Invite-only announcement">
                                <InviteHeaderButton
                                    type="button"
                                    onClick={toggleInviteBanner}
                                    aria-expanded={!inviteBannerCollapsed}
                                >
                                    <InviteTitleRow>
                                        <InviteIconTile aria-hidden="true">🎁</InviteIconTile>
                                        <InviteTitleStack>
                                            <InviteTitleText>Invite Codes</InviteTitleText>
                                            <InviteSubtitleText>
                                                {availableCodeCount > 0
                                                    ? `${availableCodeCount} ${availableCodeCount === 1 ? 'code' : 'codes'} available`
                                                    : 'No codes left'}
                                            </InviteSubtitleText>
                                        </InviteTitleStack>
                                    </InviteTitleRow>
                                    <InviteHeaderRight>
                                        {availableCodeCount > 0 && (
                                            <InviteCountBadge>{availableCodeCount}</InviteCountBadge>
                                        )}
                                        <InviteChevron $collapsed={inviteBannerCollapsed} aria-hidden="true" />
                                    </InviteHeaderRight>
                                </InviteHeaderButton>
                                {!inviteBannerCollapsed && <InviteContent>
                                    <InviteSubtitleBody>
                                        Mirage is now invite-only — because great conversations require great people!
                                        {' '}{availableCodeCount > 0 ? "But don't fret, we've given you some invite codes for your friends. Use them wisely." : "Unfortunately, you're out of invite codes. But don't worry, we might drop some more soon. Stay tuned!"}
                                    </InviteSubtitleBody>
                                    <InviteBannerButton
                                        type="button"
                                        onClick={handleOpenInviteModal}
                                        disabled={availableCodeCount === 0}
                                    >
                                        {availableCodeCount > 0
                                            ? 'Share Invite Code'
                                            : 'No Codes Left'}
                                    </InviteBannerButton>
                                </InviteContent>}
                            </InviteOnlyBanner>}

                            {/* Quest hero card - shown below invite codes on home/following */}
                            {inviteCodesEnabled && questsEnabled && <HomeSectionSpacer />}
                            {questsEnabled && <QuestHeroCard collapsed={questCardCollapsed} onToggleCollapse={toggleQuestCard} />}
                        </FeedHeroColumn>}

                        {/* Android app banner - shown once for Android users until dismissed */}
                        {showAndroidBanner && <AndroidAppHero role="region" aria-label="Android app available">
                            <AndroidHeroTitle>
                                <AndroidHeroEmoji><FaGooglePlay aria-hidden="true" /></AndroidHeroEmoji> Mirage is available on Play Store
                            </AndroidHeroTitle>
                            <AndroidHeroDescription>
                                Get the native Android app for a faster, smoother experience with push notifications and offline support.
                            </AndroidHeroDescription>
                            <AndroidHeroButtons>
                                <AndroidHeroButton href="https://play.google.com/store/apps/details?id=talk.mirage.mobile" target="_blank" rel="noopener noreferrer">
                                    <FaGooglePlay aria-hidden="true" /> Get the app
                                </AndroidHeroButton>
                                <AndroidHeroDismiss onClick={dismissAndroidBanner}>
                                    No thanks
                                </AndroidHeroDismiss>
                            </AndroidHeroButtons>
                        </AndroidAppHero>}

                        {showIPhoneBanner && <IPhoneAppHero role="region" aria-label="iPhone app available">
                            <AndroidHeroTitle>
                                <AndroidHeroEmoji><FaApple aria-hidden="true" /></AndroidHeroEmoji> Mirage is available on App Store
                            </AndroidHeroTitle>
                            <AndroidHeroDescription>
                                Get the native iOS app for a faster, smoother experience with push notifications and offline support.
                            </AndroidHeroDescription>
                            <AndroidHeroButtons>
                                <IPhoneHeroButton href="https://apps.apple.com/us/app/mirage-speak-your-mind/id6757619038" target="_blank" rel="noopener noreferrer">
                                    <FaApple aria-hidden="true" /> Get the app
                                </IPhoneHeroButton>
                                <AndroidHeroDismiss onClick={dismissIPhoneBanner}>
                                    No thanks
                                </AndroidHeroDismiss>
                            </AndroidHeroButtons>
                        </IPhoneAppHero>}

                        {/* NSFW welcome hero - shown once for logged-in users until dismissed */}
                        {/* Consent prompt — always show regardless of theme.caps.showHeroCards so
                            the mirageapp theme (which disables hero cards) still surfaces it. */}
                        {/* Match the Invite↔Quest spacing (HomeSectionSpacer) so the
                            Quest↔NSFW gap reads identical to the Invite↔Quest gap. */}
                        {isLoggedIn && urlTopic === 'home' && showNsfwHero && questsEnabled && <HomeSectionSpacer />}
                        {isLoggedIn && urlTopic === 'home' && showNsfwHero && <NsfwWelcomeHero $feedViewMode={feedViewMode} role="region" aria-label="Content preferences">
                            <NsfwHeroHeader>
                                <NsfwHeroIconTile aria-hidden="true">
                                    <NsfwHeroEmoji>🔞</NsfwHeroEmoji>
                                </NsfwHeroIconTile>
                                <NsfwHeroTitle>Allow adult content?</NsfwHeroTitle>
                            </NsfwHeroHeader>
                            <NsfwHeroDescription>
                                Mirage is uncensored and may include <strong>adult content</strong>, <strong>violence</strong>, and other NSFW material. Would you like to see this content in your feed?
                            </NsfwHeroDescription>
                            <NsfwHeroButtons>
                                <NsfwHeroButton $variant="yes" onClick={() => handleNsfwChoice(true)}>
                                    Show everything
                                </NsfwHeroButton>
                                <NsfwHeroButton $variant="no" onClick={() => handleNsfwChoice(false)}>
                                    Keep it clean
                                </NsfwHeroButton>
                            </NsfwHeroButtons>
                            <NsfwHeroNote>
                                You can change this anytime in <Link to="/settings" style={{
                                    color: 'inherit',
                                    textDecoration: 'underline'
                                }}>Settings</Link>.
                            </NsfwHeroNote>
                        </NsfwWelcomeHero>}

                        {/* Home/Following header cards moved to the very top of the feed
                         * (see block rendered just after <TopicHeroCard>). */}

                        {/* Blocked topic state — takes precedence over loading/empty states */}
                        {isUrlTopicBlocked && <BlockedTopicState role="region" aria-label="Blocked topic">
                            <BlockedTopicIcon aria-hidden="true">
                                <HiNoSymbol />
                            </BlockedTopicIcon>
                            <BlockedTopicTitle>#{urlTopic} is blocked</BlockedTopicTitle>
                            <BlockedTopicMessage>
                                Posts tagged with this topic are hidden from your feeds. Unblock to see them again — you can always re-block it later from any post header or the Blocks page.
                            </BlockedTopicMessage>
                            <BlockedTopicActions>
                                {/* Standalone state panel — use `size="md"`
                                    so the CTA height matches primary buttons
                                    elsewhere (larger than BlocksView rows). */}
                                <Button
                                    variant="danger"
                                    size="md"
                                    minWidth="5.5rem"
                                    onClick={async () => {
                                        try { await tx.unblockTopic(routeTopicLower); } catch (_) { /* noop */ }
                                    }}
                                >
                                    Unblock #{urlTopic}
                                </Button>
                            </BlockedTopicActions>
                        </BlockedTopicState>}

                        {/* Loading state - only show to logged-in users */}
                        {isLoggedIn && !isUrlTopicBlocked && showLoadingPosts && (
                            <FeedSkeletonColumn $feedViewMode={feedViewMode}>
                                <PageHeaderSkeleton showSubtitle={false} titleWidth="20%" />
                                <FeedCardSkeletonList count={5} />
                            </FeedSkeletonColumn>
                        )}

                        {/* Empty home feed - only show to logged-in users */}
                        {isLoggedIn && !isUrlTopicBlocked && showEmptyHome && <EmptyHomeMessage />}

                        {/* No posts available - only show to logged-in users */}
                        {isLoggedIn && !isUrlTopicBlocked && showNoPostsAvailable && <LoadingCard $size={cardSize}>
                            <LoadingText>{noPostsMessage}</LoadingText>
                        </LoadingCard>}

                        {/* Invite-only hero - shown to logged-out users on all feeds */}
                        {!isLoggedIn && <LoggedOutPromptCard
                            role="region"
                            aria-label="Welcome to Mirage"
                            title={urlTopic === 'following' ? 'Sign in to follow people' : 'Welcome to Mirage'}
                            notice="Currently in Private Beta — Invite Only"
                            description={urlTopic === 'following'
                                ? 'Sign in to unlock your following feed and keep up with the people and topics you care about.'
                                : 'Mirage is a fully decentralized social network built on its own blockchain, designed to be 100% censorship resistant. Your posts, votes, and identity live on-chain — no central authority can silence you.'}
                            stats={welcomeStats && welcomeStats.userCount > 0 ? [
                                { label: 'Users', value: `${welcomeStatsStale ? '~' : ''}${welcomeStats.userCount.toLocaleString()}` },
                                { label: 'Active (24h)', value: `${welcomeStatsStale ? '~' : ''}${welcomeStats.active24h.toLocaleString()}` },
                                { label: 'Posts (24h)', value: `${welcomeStatsStale ? '~' : ''}${(welcomeStats.posts24h + welcomeStats.comments24h).toLocaleString()}` },
                            ] : []}
                            links={[
                                { label: 'Watch Introduction (YouTube)', href: 'https://www.youtube.com/watch?v=TOvP32ihQ0M', external: true },
                                { label: 'Learn More', href: 'https://mirage.foundation', external: true },
                            ]}
                            inviteText="Have an invite code? Join the community today."
                            primaryLabel="Create account"
                            secondaryLabel="Sign in"
                        />}

                        {/* Posts grid - only show to logged-in users */}
                        {isLoggedIn && !isUrlTopicBlocked && !showLoadingPosts && !showEmptyHome && !showNoPostsAvailable && orderedPosts.length > 0 && (() => {
                            const family = getThemeFamily(state?.themeId);
                            const FeedComponent = family.Feed;
                            const visiblePosts = orderedPosts.filter(p => {
                                const hasValidTitle = p && typeof p.title === 'string' && p.title.trim().length > 0;
                                const hasValidTopic = p && typeof p.topic === 'string' && p.topic.trim().length > 0;
                                return hasValidTitle && hasValidTopic && !p.deleted;
                            });
                            // Feed header is now owned by ListFeedView (sort + view controls only).
                            // Create-post action and nav tabs live in the left rail / sidebar,
                            // so we no longer inject a sidebar column here.
                            // Feed header is shown on all/topic feeds only.
                            // Home/following keep the toolbar controls without an
                            // extra title header above the posts.
                            const isTopicFeed = !!urlTopic && !['home', 'following', 'all'].includes(urlTopic);
                            const showFeedToolbar = urlTopic === 'all' || isTopicFeed;
                            let feedTitle = null;
                            if (urlTopic === 'all') feedTitle = 'All';
                            else if (isTopicFeed) feedTitle = `#${urlTopic}`;
                            return <FeedComponent posts={visiblePosts} state={state} updatePost={updatePost} hidingPostsSet={hidingPostsSet} flashingPostsSet={flashingPostsSet} viewerAddress={viewerAddress} sortMode={oldRedditSort} onSortChange={handleOldRedditSortChange} showSortTabs={showFeedToolbar} feedTitle={feedTitle} feedNavTopic={urlTopic} />;
                        })()}

                        {isLoggedIn && isLoadingMore && !showEmptyHome && !showNoPostsAvailable && (
                            <FeedSkeletonColumn $feedViewMode={feedViewMode}>
                                <FeedCardSkeleton />
                            </FeedSkeletonColumn>
                        )}
                        {isLoggedIn && <div ref={bottomSentinelRef} style={{
                            width: '100%',
                            minHeight: '1px'
                        }}>
                            {hasMorePosts && !isLoadingMore && !isLoading && !showEmptyHome && !showNoPostsAvailable && (
                                <ShowMoreButton onClick={loadMore}>Show more</ShowMoreButton>
                            )}
                        </div>}
                    </ModernPostFeed>
                </MainFeedPanel>
            </FeedCol>
            <FeedRightRail />
            </FeedRailRow>

            {/* Invite Code Modal */}
            {inviteModalOpen && (
                <InviteModalOverlay
                    role="presentation"
                    onClick={() => setInviteModalOpen(false)}
                >
                    <InviteModalContent
                        role="dialog"
                        aria-modal="true"
                        aria-label="Share invite code"
                        onClick={e => e.stopPropagation()}
                    >
                        <InviteModalHeader>
                            <InviteModalHeroIcon aria-hidden="true">
                                <MiragePalmTreeIcon />
                            </InviteModalHeroIcon>
                            <InviteModalTitleStack>
                                <InviteModalTitle>Share Invite Code</InviteModalTitle>
                                <InviteModalSubtitle>Invite a friend to join Mirage</InviteModalSubtitle>
                            </InviteModalTitleStack>
                            <InviteModalClose
                                type="button"
                                onClick={() => setInviteModalOpen(false)}
                                aria-label="Close invite modal"
                                title="Close"
                            >
                                <HiXMark aria-hidden="true" />
                            </InviteModalClose>
                        </InviteModalHeader>

                        <InviteModalBody>
                            {nextAvailableCode ? (
                                <>
                                    <InviteCodeDisplay>
                                        <InviteCodeStack>
                                            <InviteCodeLabel>Invite code</InviteCodeLabel>
                                            <InviteCodeText>{nextAvailableCode.code}</InviteCodeText>
                                        </InviteCodeStack>
                                        <InviteCodeCopyIcon
                                            type="button"
                                            $copied={rawCodeCopied}
                                            onClick={handleCopyRawInviteCode}
                                            aria-label={rawCodeCopied ? 'Copied' : 'Copy code'}
                                            title={rawCodeCopied ? 'Copied!' : 'Copy code'}
                                        >
                                            {rawCodeCopied ? <HiCheck /> : <HiClipboardDocument />}
                                        </InviteCodeCopyIcon>
                                    </InviteCodeDisplay>

                                    <InvitePrimaryActions>
                                        <InviteActionButton
                                            type="button"
                                            onClick={handleCopyInviteCode}
                                            title="Copy share link"
                                        >
                                            {inviteCodeCopied ? <HiCheck /> : <HiLink />}
                                            {inviteCodeCopied ? 'Copied!' : 'Copy link'}
                                        </InviteActionButton>
                                        <InvitePrimaryCta
                                            type="button"
                                            onClick={canNativeShare ? handleNativeShare : handleCopyInviteCode}
                                            title={canNativeShare ? 'Share via…' : 'Share link'}
                                        >
                                            <HiShare />
                                            Share
                                        </InvitePrimaryCta>
                                    </InvitePrimaryActions>

                                    <InviteSocialDivider>or share on</InviteSocialDivider>
                                    <InviteSocialGrid>
                                        <InviteSocialButton
                                            href={`https://twitter.com/intent/tweet?text=${encodeURIComponent(getShareText())}&url=${encodeURIComponent(getShareUrl())}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                        >
                                            Twitter / X
                                        </InviteSocialButton>
                                        <InviteSocialButton
                                            href={`https://t.me/share/url?url=${encodeURIComponent(getShareUrl())}&text=${encodeURIComponent(getShareText())}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                        >
                                            Telegram
                                        </InviteSocialButton>
                                        <InviteSocialButton
                                            href={`https://wa.me/?text=${encodeURIComponent(getShareText() + ' ' + getShareUrl())}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                        >
                                            WhatsApp
                                        </InviteSocialButton>
                                        <InviteSocialButton
                                            href={`mailto:?subject=${encodeURIComponent('Join me on Mirage!')}&body=${encodeURIComponent(getShareText() + '\n\n' + getShareUrl())}`}
                                        >
                                            Email
                                        </InviteSocialButton>
                                    </InviteSocialGrid>
                                </>
                            ) : (
                                <InviteNoCodesText>
                                    You don't have any invite codes available. Check back later!
                                </InviteNoCodesText>
                            )}
                        </InviteModalBody>

                        {nextAvailableCode && (
                            <InviteModalFooter>
                                {availableCodeCount} invite{availableCodeCount !== 1 ? 's' : ''} remaining
                            </InviteModalFooter>
                        )}
                    </InviteModalContent>
                </InviteModalOverlay>
            )}
        </ContentGrid>;
    };
    return showPosts();
};
export default MainView;
