import { Helmet } from "react-helmet-async";
import { useCallback, useEffect, useState } from "react";
import { HiNoSymbol, HiChevronDown } from "react-icons/hi2";
import { getThemeFamily } from "../../../registry/theme";
import Button from "../components/Button.js";
import LoggedOutPromptCard from "../components/LoggedOutPromptCard.js";
import QuestHeroCard from "../components/QuestHeroCard.js";
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

// Mobile header branding for home/following feeds

// Invite-only card — adapted from mirage-mobile-app `InviteCodesCard`:
// clean panel surface, icon tile + title/subtitle + count badge + chevron header,
// collapsed body = subtitle paragraph + gradient "Share Invite Code" CTA.
const FeedHeroColumn = styled.div.attrs(({ $feedViewMode }) => ({
    'data-feed-view-mode': $feedViewMode,
}))`
    width: 100%;
    max-width: 720px;
    margin: 0;

    @media (min-width: 1001px) {
        [data-sidebar-hidden='true'] &[data-feed-view-mode='card'] {
            width: 100%;
            max-width: 720px;
            margin-left: auto;
            margin-right: auto;
        }

        [data-sidebar-hidden='true'] &[data-feed-view-mode='compact'] {
            width: 80%;
            max-width: none;
            margin: 0;
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
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(102, 126, 234, 0.12)'
        : 'rgba(102, 126, 234, 0.22)'};
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
    background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    border: none;
    border-radius: 7px;
    cursor: pointer;
    white-space: nowrap;
    transition: transform 0.15s ease, box-shadow 0.15s ease, opacity 0.15s ease;
    box-shadow: 0 1px 5px rgba(102, 126, 234, 0.22);

    &:hover:not(:disabled) {
        transform: translateY(-1px);
        box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3);
        opacity: 0.95;
    }

    &:active:not(:disabled) {
        transform: translateY(0);
    }

    &:disabled {
        background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0, 0, 0, 0.05)'
        : 'rgba(255, 255, 255, 0.06)'};
        color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
        box-shadow: none;
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

// Invite Code Modal
const InviteModalOverlay = styled.div`
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: 1rem;
`;
const InviteModalContent = styled.div`
    background: ${({
    theme
}) => theme.colors.panel};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: 14px;
    padding: 1.1rem 1rem 1rem;
    max-width: 400px;
    width: 100%;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
    max-height: calc(100vh - 2rem);
    overflow-y: auto;

    @media (max-width: 768px) {
        padding: 0.9rem 0.85rem 0.85rem;
        border-radius: 11px;
    }
`;
const InviteModalTopBar = styled.div`
    display: flex;
    justify-content: flex-end;
    align-items: center;
    margin-bottom: 0.2rem;
`;
const InviteModalHero = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 0.35rem;
    margin-bottom: 0.85rem;
`;
const InviteModalHeroIcon = styled.div`
    width: 48px;
    height: 48px;
    border-radius: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 1.35rem;
    line-height: 1;
    color: #667eea;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(102, 126, 234, 0.14)'
        : 'rgba(102, 126, 234, 0.22)'};
    margin-bottom: 0.2rem;
`;
const InviteModalTitle = styled.h2`
    font-size: 0.95rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
    margin: 0;
`;
const InviteModalSubtitle = styled.div`
    font-size: 0.7rem;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.3;
`;
const InviteModalClose = styled.button`
    background: none;
    border: none;
    color: ${({
    theme
}) => theme.colors.subtleText};
    cursor: pointer;
    font-size: 1.25rem;
    line-height: 1;
    padding: 0;
    width: 24px;
    height: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    &:hover {
        color: ${({
    theme
}) => theme.colors.text};
        background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0, 0, 0, 0.05)'
        : 'rgba(255, 255, 255, 0.07)'};
    }
`;
const InviteCodeDisplay = styled.div`
    background: ${({ theme }) => theme.colors.panelAlt};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
    padding: 0.75rem 1rem;
    text-align: center;
    margin-bottom: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    align-items: center;
`;
const InviteCodeLabel = styled.div`
    font-size: 0.55rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.subtleText};
`;
const InviteCodeText = styled.div`
    font-size: 1.55rem;
    font-weight: 700;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    color: ${({
    theme
}) => theme.colors.text};
    letter-spacing: 0.16em;
    line-height: 1.1;

    @media (max-width: 768px) {
        font-size: 1.3rem;
        letter-spacing: 0.12em;
    }
`;
const InviteCodeSubtext = styled.div`
    font-size: 0.65rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
`;
const InviteShareOptions = styled.div`
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.4rem;
    margin-bottom: 0.75rem;
`;
const InviteShareOption = styled.button`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.35rem;
    padding: 0.65rem 0.4rem;
    font-family: inherit;
    font-size: 0.62rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.text};
    background: ${({ theme }) => theme.colors.panelAlt};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 9px;
    cursor: pointer;
    text-align: center;
    text-decoration: none;
    transition: transform 0.15s ease, background 0.15s ease, border-color 0.15s ease;

    &:hover:not(:disabled) {
        transform: translateY(-1px);
        background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0, 0, 0, 0.02)'
        : 'rgba(255, 255, 255, 0.04)'};
    }

    &:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }
`;
const InviteShareOptionIcon = styled.span`
    width: 34px;
    height: 34px;
    border-radius: 17px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.95rem;
    color: #FFFFFF;
    background: ${({ $tint }) => $tint || '#667eea'};
    transition: background 0.15s ease;
`;
const InviteSocialDivider = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin: 0.2rem 0 0.55rem;
    font-size: 0.55rem;
    font-weight: 600;
    letter-spacing: 0.1em;
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
const InviteShareButtons = styled.div`
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.4rem;
    margin-bottom: 0.75rem;

    @media (max-width: 400px) {
        grid-template-columns: 1fr;
    }
`;
const InviteShareButton = styled.button`
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    padding: 0.5rem 0.65rem;
    font-size: 0.65rem;
    font-weight: 500;
    font-family: inherit;
    color: ${({
    theme
}) => theme.colors.text};
    background: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: 7px;
    cursor: pointer;
    transition: all 0.15s ease;

    &:hover {
        background: ${({
    theme
}) => theme.colors.accent};
        border-color: ${({
    theme
}) => theme.colors.text};
    }
`;
const InviteCopyButton = styled(InviteShareButton)`
    grid-column: 1 / -1;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border: none;
    color: #FFFFFF;
    font-weight: 600;

    &:hover {
        background: linear-gradient(135deg, #5a6fd6 0%, #6a4190 100%);
        border: none;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        transform: translateY(-1px);
    }

    &:active {
        transform: translateY(0);
    }
`;
const InviteNativeShareButton = styled(InviteCopyButton)`
    background: linear-gradient(135deg, #10B981 0%, #059669 100%);

    &:hover {
        background: linear-gradient(135deg, #0d9668 0%, #047857 100%);
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
    }
`;
const InviteDesktopShareButtons = styled.div`
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.4rem;
    margin-bottom: 0.75rem;

    @media (max-width: 600px) {
        display: none;
    }
`;
const InviteRemainingText = styled.div`
    text-align: center;
    font-size: 0.62rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
`;
const InviteNoCodesText = styled.div`
    text-align: center;
    padding: 1rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.85rem;
`;

// Top feed title row for home/following feeds — matches InboxView HeaderRow spacing
const HomeFeedTitleBar = styled.div`
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
    align-self: flex-start;
    margin: 0;
    padding: 0.5rem 1rem;
`;

// NSFW welcome hero - shown once to logged-in users on home feed
const NsfwWelcomeHero = styled.div`
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.08) 0%, rgba(220, 38, 127, 0.08) 100%);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;

    @media (max-width: 1000px) {
        border-radius: 10px;
        padding: 1rem 1.25rem;
    }

    @media (max-width: 768px) {
        border-radius: 8px;
        padding: 0.85rem 1rem;
    }
`;
const NsfwHeroTitle = styled.div`
    font-size: 1rem;
    font-weight: 700;
    color: ${({
    theme
}) => theme.colors.text};
    display: flex;
    align-items: center;
    gap: 0.5rem;
    line-height: 1.2;

    @media (max-width: 768px) {
    }
`;
const NsfwHeroEmoji = styled.span`
    font-size: 1.1rem;
    line-height: 1;
`;
const NsfwHeroDescription = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.8rem;
    line-height: 1.6;

    @media (max-width: 768px) {
    }

    strong {
        color: ${({
    theme
}) => theme.colors.text};
        font-weight: 600;
    }
`;
const NsfwHeroButtons = styled.div`
    display: flex;
    gap: 0.75rem;
    margin-top: 0.25rem;
    flex-wrap: wrap;

    @media (max-width: 768px) {
        gap: 0.5rem;
    }
`;
const NsfwHeroButton = styled.button`
    padding: 0.5rem 1.25rem;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    border: none;

    @media (max-width: 768px) {
        padding: 0.45rem 1rem;
        flex: 1;
        min-width: 80px;
    }

    ${({
    $variant
}) => $variant === 'yes' ? `
        background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
        color: #fff;
        &:hover {
            background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
            transform: translateY(-1px);
        }
    ` : `
        background: rgba(100, 116, 139, 0.2);
        color: #94a3b8;
        border: 1px solid rgba(100, 116, 139, 0.3);
        &:hover {
            background: rgba(100, 116, 139, 0.3);
            color: #cbd5e1;
        }
    `}
`;
const NsfwHeroNote = styled.div`
    color: ${({
    theme
}) => theme.colors.mutedText};
    font-size: 0.7rem;
    font-style: italic;
    margin-top: 0.25rem;

    a {
        color: ${({
    theme
}) => theme.colors.link};
        text-decoration: none;
        &:hover {
            text-decoration: underline;
        }
    }
`;

// Android app banner - shown once to Android mobile users until dismissed
const AndroidAppHero = styled.div`
    background: linear-gradient(135deg, rgba(52, 168, 83, 0.08) 0%, rgba(66, 133, 244, 0.08) 100%);
    border: 1px solid rgba(66, 133, 244, 0.3);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;

    @media (max-width: 1000px) {
        border-radius: 10px;
        padding: 1rem 1.25rem;
    }

    @media (max-width: 768px) {
        border-radius: 8px;
        padding: 0.85rem 1rem;
    }
`;
const AndroidHeroTitle = styled.div`
    font-size: 1rem;
    font-weight: 700;
    color: ${({
    theme
}) => theme.colors.text};
    display: flex;
    align-items: center;
    gap: 0.5rem;
    line-height: 1.2;

    @media (max-width: 768px) {
    }
`;
const AndroidHeroEmoji = styled.span`
    font-size: 1.1rem;
    line-height: 1;
`;
const AndroidHeroDescription = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.8rem;
    line-height: 1.6;

    @media (max-width: 768px) {
    }
`;
const AndroidHeroButtons = styled.div`
    display: flex;
    gap: 0.75rem;
    margin-top: 0.25rem;
    flex-wrap: wrap;

    @media (max-width: 768px) {
        gap: 0.5rem;
    }
`;
const AndroidHeroButton = styled.a`
    padding: 0.5rem 1.25rem;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    border: none;
    text-decoration: none;
    text-align: center;
    background: linear-gradient(135deg, #34a853 0%, #2d9249 100%);
    color: #fff;

    &:hover {
        background: linear-gradient(135deg, #2d9249 0%, #267a3d 100%);
        transform: translateY(-1px);
    }

    @media (max-width: 768px) {
        padding: 0.45rem 1rem;
        flex: 1;
        min-width: 80px;
    }
`;
const AndroidHeroDismiss = styled.button`
    padding: 0.5rem 1.25rem;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    background: rgba(100, 116, 139, 0.2);
    color: #94a3b8;
    border: 1px solid rgba(100, 116, 139, 0.3);

    &:hover {
        background: rgba(100, 116, 139, 0.3);
        color: #cbd5e1;
    }

    @media (max-width: 768px) {
        padding: 0.45rem 1rem;
        flex: 1;
        min-width: 80px;
    }
`;
const IPhoneAppHero = styled.div`
    background: linear-gradient(135deg, rgba(0, 122, 255, 0.08) 0%, rgba(88, 86, 214, 0.08) 100%);
    border: 1px solid rgba(0, 122, 255, 0.3);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;

    @media (max-width: 1000px) {
        border-radius: 10px;
        padding: 1rem 1.25rem;
    }

    @media (max-width: 768px) {
        border-radius: 8px;
        padding: 0.85rem 1rem;
    }
`;
const IPhoneHeroButton = styled.a`
    padding: 0.5rem 1.25rem;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    border: none;
    text-decoration: none;
    text-align: center;
    background: linear-gradient(135deg, #007AFF 0%, #5856D6 100%);
    color: #fff;

    &:hover {
        background: linear-gradient(135deg, #0066D6 0%, #4B49B8 100%);
        transform: translateY(-1px);
    }

    @media (max-width: 768px) {
        padding: 0.45rem 1rem;
        flex: 1;
        min-width: 80px;
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
            <div>
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
                        {showHero && showAndroidBanner && <AndroidAppHero role="region" aria-label="Android app available">
                            <AndroidHeroTitle>
                                <AndroidHeroEmoji>📱</AndroidHeroEmoji> Mirage is available on Android
                            </AndroidHeroTitle>
                            <AndroidHeroDescription>
                                Get the native Android app for a faster, smoother experience with push notifications and offline support.
                            </AndroidHeroDescription>
                            <AndroidHeroButtons>
                                <AndroidHeroButton href="https://play.google.com/store/apps/details?id=talk.mirage.mobile" target="_blank" rel="noopener noreferrer">
                                    Get the app
                                </AndroidHeroButton>
                                <AndroidHeroDismiss onClick={dismissAndroidBanner}>
                                    No thanks
                                </AndroidHeroDismiss>
                            </AndroidHeroButtons>
                        </AndroidAppHero>}

                        {showHero && showIPhoneBanner && <IPhoneAppHero role="region" aria-label="iPhone app available">
                            <AndroidHeroTitle>
                                <AndroidHeroEmoji>📱</AndroidHeroEmoji> Mirage is available on iPhone
                            </AndroidHeroTitle>
                            <AndroidHeroDescription>
                                Get the native iOS app for a faster, smoother experience with push notifications and offline support.
                            </AndroidHeroDescription>
                            <AndroidHeroButtons>
                                <IPhoneHeroButton href="https://apps.apple.com/us/app/mirage-speak-your-mind/id6757619038" target="_blank" rel="noopener noreferrer">
                                    Get the app
                                </IPhoneHeroButton>
                                <AndroidHeroDismiss onClick={dismissIPhoneBanner}>
                                    No thanks
                                </AndroidHeroDismiss>
                            </AndroidHeroButtons>
                        </IPhoneAppHero>}

                        {/* NSFW welcome hero - shown once for logged-in users until dismissed */}
                        {isLoggedIn && showHero && urlTopic === 'home' && showNsfwHero && <NsfwWelcomeHero role="region" aria-label="Content preferences">
                            <NsfwHeroTitle>
                                <NsfwHeroEmoji>🔞</NsfwHeroEmoji> Allow Adult Content?
                            </NsfwHeroTitle>
                            <NsfwHeroDescription>
                                Mirage is uncensored and may include <strong>adult content</strong>, <strong>violence</strong>, and other NSFW material. Would you like to see this content in your feed?
                            </NsfwHeroDescription>
                            <NsfwHeroButtons>
                                <NsfwHeroButton $variant="yes" onClick={() => handleNsfwChoice(true)}>
                                    Yes, show everything
                                </NsfwHeroButton>
                                <NsfwHeroButton $variant="no" onClick={() => handleNsfwChoice(false)}>
                                    No, keep it clean
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
                            <>
                                <PageHeaderSkeleton showSubtitle={false} titleWidth="20%" />
                                <FeedCardSkeletonList count={5} />
                            </>
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
                            eyebrow={urlTopic === 'following' ? 'Following feed' : 'Join Mirage'}
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
                            <FeedCardSkeleton />
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
            </div>

            {/* Invite Code Modal */}
            {inviteModalOpen && <InviteModalOverlay onClick={() => setInviteModalOpen(false)}>
                <InviteModalContent onClick={e => e.stopPropagation()}>
                    <InviteModalTopBar>
                        <InviteModalClose
                            type="button"
                            onClick={() => setInviteModalOpen(false)}
                            aria-label="Close invite modal"
                        >&times;</InviteModalClose>
                    </InviteModalTopBar>
                    <InviteModalHero>
                        <InviteModalHeroIcon aria-hidden="true">🎁</InviteModalHeroIcon>
                        <InviteModalTitle>Share Invite Code</InviteModalTitle>
                        <InviteModalSubtitle>Invite a friend to join Mirage</InviteModalSubtitle>
                    </InviteModalHero>

                    {nextAvailableCode ? <>
                        <InviteCodeDisplay>
                            <InviteCodeLabel>Your Invite Code</InviteCodeLabel>
                            <InviteCodeText>{nextAvailableCode.code}</InviteCodeText>
                            <InviteCodeSubtext>Share this code with a friend to invite them</InviteCodeSubtext>
                        </InviteCodeDisplay>

                        <InviteShareOptions>
                            <InviteShareOption
                                type="button"
                                onClick={handleCopyRawInviteCode}
                                title="Copy code to clipboard"
                            >
                                <InviteShareOptionIcon
                                    $tint={rawCodeCopied ? '#10B981' : '#667eea'}
                                    aria-hidden="true"
                                >
                                    {rawCodeCopied ? '✓' : '⧉'}
                                </InviteShareOptionIcon>
                                {rawCodeCopied ? 'Copied!' : 'Copy Code'}
                            </InviteShareOption>
                            <InviteShareOption
                                type="button"
                                onClick={handleCopyInviteCode}
                                title="Copy share link to clipboard"
                            >
                                <InviteShareOptionIcon
                                    $tint={inviteCodeCopied ? '#10B981' : '#6366F1'}
                                    aria-hidden="true"
                                >
                                    {inviteCodeCopied ? '✓' : '🔗'}
                                </InviteShareOptionIcon>
                                {inviteCodeCopied ? 'Copied!' : 'Copy Link'}
                            </InviteShareOption>
                            <InviteShareOption
                                type="button"
                                onClick={canNativeShare ? handleNativeShare : handleCopyInviteCode}
                                disabled={!canNativeShare && !handleCopyInviteCode}
                                title={canNativeShare ? 'Share via…' : 'Share link'}
                            >
                                <InviteShareOptionIcon $tint="#10B981" aria-hidden="true">↗</InviteShareOptionIcon>
                                Share
                            </InviteShareOption>
                        </InviteShareOptions>

                        <InviteSocialDivider>or share on</InviteSocialDivider>
                        <InviteDesktopShareButtons>
                            <InviteShareButton as="a" href={`https://twitter.com/intent/tweet?text=${encodeURIComponent(getShareText())}&url=${encodeURIComponent(getShareUrl())}`} target="_blank" rel="noopener noreferrer">
                                <span role="img" aria-label="X">𝕏</span> Twitter/X
                            </InviteShareButton>
                            <InviteShareButton as="a" href={`https://t.me/share/url?url=${encodeURIComponent(getShareUrl())}&text=${encodeURIComponent(getShareText())}`} target="_blank" rel="noopener noreferrer">
                                <span role="img" aria-label="telegram">📨</span> Telegram
                            </InviteShareButton>
                            <InviteShareButton as="a" href={`https://wa.me/?text=${encodeURIComponent(getShareText() + ' ' + getShareUrl())}`} target="_blank" rel="noopener noreferrer">
                                <span role="img" aria-label="whatsapp">💬</span> WhatsApp
                            </InviteShareButton>
                            <InviteShareButton as="a" href={`mailto:?subject=${encodeURIComponent('Join me on Mirage!')}&body=${encodeURIComponent(getShareText() + '\n\n' + getShareUrl())}`}>
                                <span role="img" aria-label="email">📧</span> Email
                            </InviteShareButton>
                        </InviteDesktopShareButtons>

                        <InviteRemainingText>
                            You have {availableCodeCount} invite{availableCodeCount !== 1 ? 's' : ''} remaining
                        </InviteRemainingText>
                    </> : <InviteNoCodesText>
                        You don't have any invite codes available. Check back later!
                    </InviteNoCodesText>}
                </InviteModalContent>
            </InviteModalOverlay>}
        </ContentGrid>;
    };
    return showPosts();
};
export default MainView;
