import { communityLabel, communityPath } from '../../../utils/community';
import { Helmet } from "react-helmet-async";
import { useCallback, useEffect, useState } from "react";
import {
    HiNoSymbol,
} from "react-icons/hi2";
import { FaGooglePlay, FaApple } from "react-icons/fa6";
import { getThemeFamily } from "../../../registry/theme";
import Button from "../components/Button.js";
import LoggedOutPromptCard from "../components/LoggedOutPromptCard.js";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import { FeedSortToggle, FeedViewToggle, loadViewMode, saveViewMode, VIEW_MODE_CHANGE_EVENT } from "../ListFeedView.js";
import { FeedCardSkeletonList, FeedCardSkeleton, PageHeaderSkeleton } from "../components/Skeleton.js";
import ShowMoreButton from "../components/ShowMoreButton.js";
import styled, { useTheme } from "styled-components";
import { Link } from "react-router-dom";
import Storage from "../../../utils/Storage";
import * as tx from "../../../utils/tx";
import { isSubscribed, subscribe, unsubscribe, invalidateCache as invalidateTopicsCache } from "../../../utils/Subscriptions";
import { ContentGrid, ModernPostFeed, StyledError, OLDREDDIT_SHELL_INSET_X } from "../Layout";
import { useMain } from "../../../logic/useMain";
import { requireThemeColor } from "../../../utils/themeColor";
import CurationLensPicker from "../components/CurationLensPicker";
import AccountStatusNotices from "../components/AccountStatusNotices";

// Mobile header branding for home/following feeds

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

// NSFW welcome hero — default: compact, app-style card using the
// Mirage gradient accent. Blends with the page bg (rounded 8px, themed
// border) and matches the visual language of TopicHeroCard.
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

    /* Red tint — mirrors the danger palette used elsewhere in default
     * (Settings danger buttons): a soft
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
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;

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
// App-download hero cards (Android + iPhone) — default theme
// Visuals match the hero-card language: flat panel on `bg`,
// 1px `border`, 8px radius, icon tile + title/subtitle header,
// gradient CTA button, neutral dismiss pill.
// ============================================================
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

/* Primary CTA — platform-tinted gradient, using the shared hero
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

const CommunityLensBar = styled.div`
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 0.35rem;
    width: 100%;
    margin: 0;
    padding: 0.55rem 1rem 0.45rem;
    border-bottom: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    color: ${({ theme }) => requireThemeColor(theme, 'text')};

    @media (max-width: 600px) {
        padding: 0.55rem 0 0.45rem;
    }
`;

const CommunityLensTopRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    min-width: 0;
`;

const CommunityLensTitle = styled.h1`
    margin: 0;
    padding: 0;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    line-height: 1.2;
    min-width: 0;
    max-width: 14rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 0 1 auto;
`;

const CommunityLensControls = styled.div`
    display: flex;
    align-items: center;
    gap: 0.2rem;
    flex: 0 0 auto;
    margin-left: auto;
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
        Follow a few communities to personalize your feed. If this node is new, be the first to post. Browse <InlineLink to="/communities">communities</InlineLink> to get started.
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
        openBrowsingEnabled,
        nodeConfigLoaded,
        showAndroidBanner,
        showIPhoneBanner,
        welcomeStats,
        welcomeStatsStale,
        handleNsfwChoice,
        bottomSentinelRef,
        loadMore,
        setFeedLens,
    } = useMain({
        state,
        setPosts,
        updatePost,
        setTopic,
        routeTopic
    });
    const handleLensChange = useCallback((lens, teamId) => {
        setFeedLens({ lens, teamId });
    }, [setFeedLens]);
    // Open browsing: guests may read the feed too. Content-rendering branches use
    // canBrowse; logged-in-only chrome (heroes, banners) keeps using isLoggedIn.
    // Until the node config has loaded we don't yet know if open browsing is on,
    // so treat browsing as allowed (show a loading skeleton, never flash the
    // logged-out splash) and let the gated splash render only once we know.
    const canBrowse = isLoggedIn || openBrowsingEnabled || !nodeConfigLoaded;
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
                    <TopicLinkInHeader to={communityPath(p.topic)} title={`View ${communityLabel(p.topic)}`}>
                        {communityLabel(p.topic)}
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

                // Hide posts the viewer downvoted immediately when the setting is on.
                // Newest/Magic also omit them on the next feed fetch (backend).
                if (hideDownvotedPosts) {
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
        const pageTitle = urlTopic === 'home' ? 'Home' : urlTopic === 'following' ? 'Following' : urlTopic === 'all' ? 'All Posts' : communityLabel(urlTopic);
        const noPostsMessage = urlTopic === 'following'
            ? 'No posts available. Follow users or communities to populate this feed.'
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
                                    <TopicHeroTitle>{communityLabel(urlTopic)}</TopicHeroTitle>
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
                                    Community feed for {communityLabel(urlTopic)}. Follow this community to stay up to date with the latest posts, discussions, and updates from users actively contributing here.
                                </TopicHeroDescription>
                            </TopicHeroCard>}

                            {isCurrentTopic && !isUrlTopicBlocked && (
                                <CommunityLensBar role="region" aria-label={`${communityLabel(urlTopic)} feed header`}>
                                    <CommunityLensTopRow>
                                        <CommunityLensTitle>{communityLabel(urlTopic)}</CommunityLensTitle>
                                        <CommunityLensControls>
                                            <FeedSortToggle sortMode={oldRedditSort} onChange={handleOldRedditSortChange} />
                                            <FeedViewToggle viewMode={feedViewMode} onChange={handleFeedViewModeChange} />
                                        </CommunityLensControls>
                                    </CommunityLensTopRow>
                                    <CurationLensPicker
                                        community={urlTopic}
                                        viewer={viewerAddress}
                                        onChange={handleLensChange}
                                    />
                                </CommunityLensBar>
                            )}

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
                                <AccountStatusNotices showQuota={false} />
                            </FeedHeroColumn>}

                            {/* Android app banner - shown once for Android users until dismissed */}
                            {isLoggedIn && showAndroidBanner && <AndroidAppHero role="region" aria-label="Android app available">
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

                            {isLoggedIn && showIPhoneBanner && <IPhoneAppHero role="region" aria-label="iPhone app available">
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
                            the default theme (which disables hero cards) still surfaces it. */}
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
                            {isUrlTopicBlocked && <BlockedTopicState role="region" aria-label="Blocked community">
                                <BlockedTopicIcon aria-hidden="true">
                                    <HiNoSymbol />
                                </BlockedTopicIcon>
                                <BlockedTopicTitle>{communityLabel(urlTopic)} is blocked</BlockedTopicTitle>
                                <BlockedTopicMessage>
                                    Posts in this community are hidden from your feeds. Unblock to see them again — you can always re-block it later from any post header or the Blocks page.
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
                                        Unblock {communityLabel(urlTopic)}
                                    </Button>
                                </BlockedTopicActions>
                            </BlockedTopicState>}

                            {/* Loading state (also covers the window before node config
                                has loaded, so guests never flash an empty/splash state) */}
                            {canBrowse && !isUrlTopicBlocked && (showLoadingPosts || !nodeConfigLoaded) && (
                                <FeedSkeletonColumn $feedViewMode={feedViewMode}>
                                    {/* Community feeds already show the real title in CommunityLensBar. */}
                                    {!isCurrentTopic && (
                                        <PageHeaderSkeleton showSubtitle={false} titleWidth="20%" />
                                    )}
                                    <FeedCardSkeletonList count={5} />
                                </FeedSkeletonColumn>
                            )}

                            {/* Empty home feed */}
                            {canBrowse && !isUrlTopicBlocked && nodeConfigLoaded && showEmptyHome && <EmptyHomeMessage />}

                            {/* No posts available */}
                            {canBrowse && !isUrlTopicBlocked && nodeConfigLoaded && showNoPostsAvailable && <LoadingCard $size={cardSize}>
                                <LoadingText>{noPostsMessage}</LoadingText>
                            </LoadingCard>}

                            {/* Welcome / signup hero - only when browsing is gated (open browsing off) */}
                            {!canBrowse && <LoggedOutPromptCard
                                role="region"
                                aria-label="Welcome to Mirage"
                                title={urlTopic === 'following' ? 'Sign in to follow users' : 'Welcome to Mirage'}
                                description={urlTopic === 'following'
                                    ? 'Sign in to unlock your following feed and keep up with the users and communities you care about.'
                                    : 'Communities, posts, and voting without power mods, shadow bans, or corporate gatekeepers. Your identity is portable, moderation is voluntary, and no node can erase you from the network.'}
                                stats={welcomeStats && welcomeStats.userCount > 0 ? [
                                    { label: 'Users', value: `${welcomeStatsStale ? '~' : ''}${welcomeStats.userCount.toLocaleString()}` },
                                    { label: 'Active (7d)', value: `${welcomeStatsStale ? '~' : ''}${welcomeStats.active7d.toLocaleString()}` },
                                    { label: 'Posts (24h)', value: `${welcomeStatsStale ? '~' : ''}${(welcomeStats.posts24h + welcomeStats.comments24h).toLocaleString()}` },
                                ] : []}
                                links={[
                                    { label: 'Watch Introduction (YouTube)', href: 'https://www.youtube.com/watch?v=TOvP32ihQ0M', external: true },
                                    { label: 'Learn More', href: 'https://mirage.foundation', external: true },
                                    { label: 'FAQ', href: '/faq' },
                                ]}
                                primaryLabel="Create account"
                                secondaryLabel="Sign in"
                            />}

                            {/* Posts grid */}
                            {canBrowse && !isUrlTopicBlocked && !showLoadingPosts && !showEmptyHome && !showNoPostsAvailable && orderedPosts.length > 0 && (() => {
                                const family = getThemeFamily(state?.themeId);
                                const FeedComponent = family.Feed;
                                const visiblePosts = orderedPosts.filter(p => {
                                    const hasValidTitle = p && typeof p.title === 'string' && p.title.trim().length > 0;
                                    const hasValidTopic = p && typeof p.topic === 'string' && p.topic.trim().length > 0;
                                    return hasValidTitle && hasValidTopic && !p.deleted;
                                });
                                // Community feeds own title + lens + sort/view in CommunityLensBar.
                                // Only the All feed still uses ListFeedView's toolbar title row.
                                const showFeedToolbar = urlTopic === 'all';
                                const feedTitle = urlTopic === 'all' ? 'All' : null;
                                return <FeedComponent posts={visiblePosts} state={state} updatePost={updatePost} hidingPostsSet={hidingPostsSet} flashingPostsSet={flashingPostsSet} viewerAddress={viewerAddress} sortMode={oldRedditSort} onSortChange={handleOldRedditSortChange} showSortTabs={showFeedToolbar} feedTitle={feedTitle} feedNavTopic={urlTopic} />;
                            })()}

                            {canBrowse && isLoadingMore && !showEmptyHome && !showNoPostsAvailable && (
                                <FeedSkeletonColumn $feedViewMode={feedViewMode}>
                                    <FeedCardSkeleton />
                                </FeedSkeletonColumn>
                            )}
                            {canBrowse && <div ref={bottomSentinelRef} style={{
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
            </FeedRailRow>
        </ContentGrid>;
    };
    return showPosts();
};
export default MainView;
