import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import styled, { useTheme, css } from "styled-components";
import { Link, useNavigate } from "react-router-dom";
import {
    HiOutlineLink,
    HiOutlinePencilSquare,
    HiOutlineTrash,
    HiOutlineUserPlus,
    HiOutlineUserMinus,
    HiOutlineHashtag,
    HiOutlineGift,
    HiOutlineSparkles,
    HiOutlineNoSymbol,
    HiOutlineFlag,
    HiOutlineEyeSlash,
} from "react-icons/hi2";

import { getThemeFamily } from "../../../registry/theme";
import { getAuthorColor, getAuthorTooltip } from "../../../utils/tierColors";
import { normalizeTag } from "../../../utils/ContentTags";
import { isLikelyImageUrl, isLikelyVideoUrl } from "../../../utils/media";
import * as tx from "../../../utils/tx";
import { follow, unfollow, isFollowing } from "../../../utils/FollowUsers";
import { subscribe, unsubscribe, isSubscribed } from "../../../utils/Subscriptions";
import Storage from "../../../utils/Storage";

import InlineMedia from "./InlineMedia";
import MarkdownRenderer from "./MarkdownRenderer";

/**
 * CardView — Mirage-app inspired post card.
 *
 * Visual language ported from `mirage-mobile-app/src/components/molecules/post-card.tsx`:
 *   · Subtle bottom border between posts, whole card is pressable and gets a
 *     hover background.
 *   · Header:   #topic · time · @username [tag]            [ Follow ▾ ] [⋯]
 *   · Title (bold) + markdown body (truncated to 700 chars in feed).
 *   · Media block (InlineMedia handles image / video / redgifs / gallery).
 *   · Action row:
 *       [▲ count ▼]  [💬 count]                [ 🚫 block ]  [↪ share]
 *
 * Three popovers live on a card:
 *   1. Follow popover — Follow topic / Follow user
 *   2. Block popover  — Block user / Block post / Block topic / Report post
 *   3. More popover   — full set of actions mirroring bluemoon
 *
 * All popovers reuse the same visual style and behavior as the feed header
 * dropdowns in `ListFeedView.js`.
 */

// ─── Layout primitives ─────────────────────────────────────────────────────

const Card = styled.article`
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0.75rem 1rem 0.65rem;
    margin: 4px 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    position: relative;
    /* Raise this card's stacking context above siblings whenever any popover
     * (follow / more / block) is open so the absolute-positioned Menu renders
     * above the next card in the feed. */
    z-index: ${({ $menuOpen }) => ($menuOpen ? 50 : 'auto')};
    cursor: pointer;
    transition: background-color 0.12s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    ${({ $flash }) =>
        $flash &&
        css`
            animation: miragePostFlash 1.1s ease-out forwards;
        `}

    @keyframes miragePostFlash {
        0%   { background: rgba(102, 126, 234, 0.12); }
        100% { background: transparent; }
    }

    @media (max-width: 600px) {
        padding: 0.65rem 0.85rem 0.55rem;
        gap: 0.4rem;
        border-radius: 6px;
    }
`;

const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    min-width: 0;
`;

/* Header row typography bumped up a notch (0.56 → 0.62rem) with lighter
 * weights across the board so the metadata reads as a single calm line
 * rather than three bold labels. Topic + user stay heavier than time /
 * feed-reason so they still anchor the row. */
const HeaderMeta = styled.div`
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.2rem 0.3rem;
    min-width: 0;
    font-size: 0.62rem;
    font-weight: 400;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    line-height: 1.2;
`;

const TopicLink = styled(Link)`
    font-weight: 500;
    font-size: 0.62rem;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    text-decoration: none;
    &:hover { color: ${({ theme }) => theme.colors.text}; text-decoration: none; }
`;

const HeaderDot = styled.span`
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-size: 0.75rem;
    font-weight: 700;
    line-height: 1;
`;

const TimeText = styled.span`
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-size: 0.62rem;
    font-weight: 400;
`;

const UserLink = styled(Link)`
    color: ${({ theme, $tierColor }) => $tierColor || theme.colors.feedCtrlText};
    font-weight: 500;
    font-size: 0.62rem;
    text-decoration: none;
    &:hover { color: ${({ theme, $tierColor }) => $tierColor || theme.colors.text}; }
`;

/* Inline italic feed-bucket label ("following", "popular", "similar"…). */
const FeedReasonInline = styled.span`
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-size: 0.62rem;
    font-weight: 400;
    font-style: italic;
`;

// Post content-tag badge (adult / violence / sensitive) — sits next to the
// username in the header meta row, matching the bluemoon layout.
const tagColors = {
    adult: { bg: 'rgba(236, 72, 153, 0.18)', border: 'rgba(236, 72, 153, 0.50)', text: '#ec4899' },
    violence: { bg: 'rgba(185, 28, 28, 0.18)', border: 'rgba(185, 28, 28, 0.50)', text: '#b91c1c' },
    sensitive: { bg: 'rgba(109, 40, 217, 0.18)', border: 'rgba(109, 40, 217, 0.50)', text: '#6d28d9' },
    default: { bg: '#e5e7eb', border: '#cbd5e1', text: '#0f172a' },
};

const TagBadge = styled.span`
    display: inline-flex;
    align-items: center;
    padding: 0.08rem 0.35rem;
    border-radius: 999px;
    background: ${({ $tag }) => (tagColors[$tag]?.bg || tagColors.default.bg)};
    color: ${({ $tag }) => (tagColors[$tag]?.text || tagColors.default.text)};
    font-size: 0.58rem;
    font-weight: 700;
    text-transform: lowercase;
    border: 1px solid ${({ $tag }) => (tagColors[$tag]?.border || tagColors.default.border)};
    vertical-align: middle;
`;

const HeaderActions = styled.div`
    display: flex;
    align-items: center;
    gap: 0.25rem;
    flex-shrink: 0;
`;

// ─── Follow / More header buttons ──────────────────────────────────────────

/* Follow button: solid blue when not following, outlined neutral when
 * following. The neutral border uses dedicated `followBtnBorder` tokens
 * (rgb(140,141,143) dark / rgb(124,125,125) light) and lifts to white /
 * black on hover, so the "Following" pill reads as a clear toggle. */
const FollowButton = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 6px 12px;
    border-radius: 9999px;
    font-size: 0.58rem;
    font-weight: 700;
    font-family: inherit;
    line-height: 1;
    cursor: pointer;
    border: 1.5px solid
        ${({ $active, theme }) =>
            $active ? theme.colors.followBtnBorder : theme.colors.followBtnBg};
    background: ${({ $active, theme }) =>
        $active ? 'transparent' : theme.colors.followBtnBg};
    color: ${({ $active, theme }) =>
        $active ? theme.colors.text : '#FFFFFF'};
    transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;

    &:hover:not(:disabled) {
        background: ${({ $active, theme }) =>
            $active ? 'transparent' : theme.colors.followBtnBgHover};
        border-color: ${({ $active, theme }) =>
            $active ? theme.colors.followBtnBorderHover : theme.colors.followBtnBgHover};
    }
    &:disabled { opacity: 0.6; cursor: default; }
`;

const MoreButton = styled.button`
    appearance: none;
    width: 28px;
    height: 28px;
    border-radius: 9999px;
    border: none;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    margin-right: -4px;
    /* Only background transitions on hover — no transform, so the icon
     * stays rock-steady while the user aims for it. */
    transition: background 0.12s ease;

    &:hover { background: ${({ theme }) => theme.colors.feedCtrlHoverBg}; }

    svg { width: 16px; height: 16px; fill: currentColor; }
`;

// ─── Body ──────────────────────────────────────────────────────────────────

const TitleLink = styled(Link)`
    display: block;
    color: ${({ theme }) => theme.colors.text};
    font-size: 1rem;
    font-weight: 700;
    line-height: 1.3;
    text-decoration: none;
    word-break: break-word;
    overflow-wrap: anywhere;
    &:hover { text-decoration: none; color: ${({ theme }) => theme.colors.text}; }
    &:visited { color: ${({ theme }) => theme.colors.text}; }

    @media (max-width: 1000px) {
        font-size: 0.8rem;
    }
`;

const Body = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.85rem;
    line-height: 1.5;
    word-break: break-word;
    overflow-wrap: anywhere;

    p { margin: 0 0 0.5rem; }
    p:last-child { margin-bottom: 0; }

    a { color: ${({ theme }) => theme.colors.link}; }

    @media (max-width: 1000px) {
        font-size: 0.75rem;
    }
`;

const MediaWrap = styled.div`
    margin-top: 0.1rem;
    max-width: 100%;
    overflow: hidden;
    border-radius: 10px;
    ${({ $blur }) => $blur && css`filter: blur(18px);`}
`;

// ─── Action row ────────────────────────────────────────────────────────────

const ActionRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.25rem;
`;

/* Comment count pill
 * Same visual language as the vote pill and action chips: filled with
 * `actionIconBg`, no border, 32px tall. Lighter, smaller label than the
 * previous version so it reads as metadata.
 * Only background transitions — no scale on :active, so the icon stays
 * in place while clicking. */
const ActionPill = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    height: 32px;
    padding: 0 12px;
    border-radius: 9999px;
    border: none;
    background: ${({ theme }) => theme.colors.actionIconBg};
    color: ${({ theme, $danger }) => ($danger ? theme.colors.voteDown : theme.colors.text)};
    font: inherit;
    font-weight: 500;
    font-size: 0.62rem;
    line-height: 1;
    cursor: pointer;
    text-decoration: none;
    transition: background 0.12s ease;

    &:hover { background: ${({ theme }) => theme.colors.actionIconHoverBg}; }

    svg {
        width: 18px;
        height: 18px;
        fill: currentColor;
    }
`;

/* Square icon-only chip used for the block + share buttons at the right
 * edge of the action row. Identical 32×32 footprint so every action-row
 * button shares the same visual height. */
const ActionIconChip = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border-radius: 9999px;
    border: none;
    background: ${({ theme }) => theme.colors.actionIconBg};
    color: ${({ theme, $danger }) => ($danger ? theme.colors.voteDown : theme.colors.text)};
    cursor: pointer;
    text-decoration: none;
    /* No transform — icon must not shift on hover / press. */
    transition: background 0.12s ease;

    &:hover { background: ${({ theme }) => theme.colors.actionIconHoverBg}; }

    svg {
        width: 15px;
        height: 15px;
        fill: currentColor;
    }
`;

const Spacer = styled.div`
    flex: 1 1 auto;
    min-width: 0;
`;

// ─── Shared dropdown menu (same look & feel as ListFeedView) ──────────────

const PopoverRoot = styled.div`
    position: relative;
    display: inline-flex;
    align-items: center;
`;

const Menu = styled.div`
    position: absolute;
    top: calc(100% + 6px);
    ${({ $align }) => ($align === 'right' ? 'right: 0;' : 'left: 0;')}
    /* Shrinks to the widest item (items use white-space: nowrap). */
    min-width: max-content;
    width: max-content;
    padding: 0;
    background: ${({ theme }) => theme.colors.menuBg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    z-index: 100;
    display: flex;
    flex-direction: column;
    gap: 0;
    overflow: hidden;
`;

const MenuHeader = styled.div`
    padding: 10px 14px;
    font-size: 0.7rem;
    font-weight: 500;
    line-height: 1;
    color: ${({ theme }) => theme.colors.menuHeaderText};
    white-space: nowrap;
`;

/* MenuItemBtn now has 3 visual slots: leading icon → label → trailing
 * gap, with `display: flex` + `gap: 0.6rem` so each row reads like the
 * sidebar nav rows. Icons inherit `currentColor` so the hover text-color
 * lift also lights up the glyph. */
const MenuItemBtn = styled.button`
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.6rem;
    width: 100%;
    padding: 10px 14px;
    white-space: nowrap;
    background: ${({ theme, $active }) =>
        $active ? theme.colors.menuSelectedBg : 'transparent'};
    border: none;
    border-radius: 0;
    color: ${({ theme, $active, $danger }) => {
        if ($danger) return theme.colors.menuDangerText;
        return $active ? theme.colors.sidebarItemActiveText : theme.colors.sidebarItemText;
    }};
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: 400;
    text-align: left;
    cursor: pointer;
    line-height: 1;
    transition: background 0.12s ease, color 0.12s ease;

    /* Hover mirrors ListFeedView MenuItem so every dropdown in this
     * theme has a single, consistent interaction model:
     *   - Dark: bg stays, text + icons lift to white.
     *   - Light: bg lifts to a neutral tile, text stays normal.
     * Danger rows saturate from menuDangerText to voteDown on hover so
     * the red picks up emphasis under the pointer. */
    &:hover {
        background: ${({ theme, $active }) =>
            $active ? theme.colors.menuSelectedBg : theme.colors.menuItemHoverBg};
        color: ${({ theme, $active, $danger }) => {
            if ($danger) return theme.colors.voteDown;
            return $active ? theme.colors.sidebarItemActiveText : theme.colors.menuItemHoverText;
        }};
    }

    & > svg {
        width: 17px;
        height: 17px;
        flex-shrink: 0;
        color: inherit;
    }

    & > span {
        flex: 1 1 auto;
        min-width: 0;
    }
`;

// ─── Icons (ported from bluemoon for visual parity) ────────────────────────

const CommentIcon = (p) => (
    <svg viewBox="0 0 24 24" aria-hidden="true" width="18" height="18" {...p}>
        <path d="M4 4h16v12H5.17L4 17.17V4zm0-2a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H4z" fill="currentColor" />
    </svg>
);

const ShareIcon = (p) => (
    <svg viewBox="0 0 458.624 458.624" aria-hidden="true" {...p}>
        <path d="M339.588,314.529c-14.215,0-27.456,4.133-38.621,11.239l-112.682-78.67c1.809-6.315,2.798-12.976,2.798-19.871 c0-6.896-0.989-13.557-2.798-19.871l109.64-76.547c11.764,8.356,26.133,13.286,41.662,13.286c39.79,0,72.047-32.257,72.047-72.047 C411.634,32.258,379.378,0,339.588,0c-39.79,0-72.047,32.257-72.047,72.047c0,5.255,0.578,10.373,1.646,15.308l-112.424,78.491 c-10.974-6.759-23.892-10.666-37.727-10.666c-39.79,0-72.047,32.257-72.047,72.047s32.256,72.047,72.047,72.047 c13.834,0,26.753-3.907,37.727-10.666l113.292,79.097c-1.629,6.017-2.514,12.34-2.514,18.872c0,39.79,32.257,72.047,72.047,72.047 c39.79,0,72.047-32.257,72.047-72.047C411.635,346.787,379.378,314.529,339.588,314.529z" fill="currentColor" />
    </svg>
);

const EllipsisIcon = (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...p}>
        <circle cx="12" cy="12" r="1.5" />
        <circle cx="12" cy="5" r="1.5" />
        <circle cx="12" cy="19" r="1.5" />
    </svg>
);

// Block / flag icon for the action-row block button.
const BlockIcon = (p) => (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...p}>
        <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 0 1-6.3-12.9L16.9 18.3A7.96 7.96 0 0 1 12 20zm6.3-3.1L7.1 5.7A8 8 0 0 1 18.3 16.9z" fill="currentColor" />
    </svg>
);

/* Share success toast rendered below the action row when the share link is
 * copied, mirroring bluemoon's `ShareSuccessMessage`. */
const ShareSuccessMessage = styled.div`
    background-color: rgba(34, 197, 94, 0.1);
    border: 1px solid #22c55e;
    border-radius: 6px;
    padding: 0.55rem 0.85rem;
    margin-top: 0.4rem;
    color: #22c55e;
    font-size: 0.75rem;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

/* Feed-bucket → inline label map, mirroring bluemoon/CardView. */
const FEED_BUCKET_LABELS = {
    following: 'following',
    similar: 'similar',
    liked: 'liked',
    discovery: 'discovery',
    popular: 'popular',
    discussion: 'discussed',
    second_chance: 'second chance',
    fresh: 'discover',
    newest: 'newest',
};

// ─── Helpers ───────────────────────────────────────────────────────────────

const MAX_BODY_LENGTH = 700;
const EMPTY_POST = Object.freeze({});

function formatAge(tsSec) {
    const now = Math.floor(Date.now() / 1000);
    const diff = Math.max(0, now - tsSec);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    if (diff < 2592000) return `${Math.floor(diff / 86400)}d`;
    if (diff < 31536000) return `${Math.floor(diff / 2592000)}mo`;
    return `${Math.floor(diff / 31536000)}y`;
}

function formatCompact(num) {
    const n = Number(num) || 0;
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return String(n);
}

function extractFirstUrl(content) {
    if (!content) return null;
    const m = String(content).match(/https?:\/\/[^\s<>"']+/);
    return m ? m[0] : null;
}

function resolveDisplayContent(post) {
    const mediaList = Array.isArray(post?.media) && post.media.length > 0 ? post.media : null;
    const rawBody = String(post?.content || '');

    if (mediaList) {
        return { mediaUrl: mediaList[0], mediaList, body: rawBody.trim() };
    }

    const firstUrl = extractFirstUrl(rawBody);
    if (firstUrl && (isLikelyImageUrl(firstUrl) || isLikelyVideoUrl(firstUrl))) {
        const body = rawBody.replace(firstUrl, '').trim();
        return { mediaUrl: firstUrl, mediaList: [firstUrl], body };
    }

    return { mediaUrl: null, mediaList: null, body: rawBody.trim() };
}

// Click originating from an interactive child (link/button/popover) should
// NOT trigger the card's navigate-to-post behavior.
function isInteractiveTarget(target) {
    if (!(target instanceof Element)) return false;
    return !!target.closest('a, button, [role="menu"], [data-no-card-click]');
}

// ─── Component ─────────────────────────────────────────────────────────────

function CardView({ state, post, updatePost, showContent = false, footer = null }) {
    const navigate = useNavigate();
    const theme = useTheme();
    const VoteSection = useMemo(
        () => getThemeFamily(theme.themeId).VoteSection,
        [theme.themeId]
    );

    const [menuOpen, setMenuOpen] = useState(false);
    const [followOpen, setFollowOpen] = useState(false);
    const [blockOpen, setBlockOpen] = useState(false);
    const [shareCopied, setShareCopied] = useState(false);
    const [blurOverride, setBlurOverride] = useState(false);
    const [followOverride, setFollowOverride] = useState(null);
    const [topicFollowOverride, setTopicFollowOverride] = useState(null);

    const menuRef = useRef(null);
    const followRef = useRef(null);
    const blockRef = useRef(null);

    const [blurSensitive, setBlurSensitive] = useState(() => {
        try { return Storage.load('blur_sensitive_media', true) !== false; }
        catch (_) { return true; }
    });

    useEffect(() => {
        const onSettings = (e) => {
            try {
                if (e?.detail && typeof e.detail.blurSensitiveMedia !== 'undefined') {
                    setBlurSensitive(e.detail.blurSensitiveMedia !== false);
                    return;
                }
                const val = Storage.load('blur_sensitive_media', true);
                setBlurSensitive(val !== false);
            } catch (_) { /* noop */ }
        };
        window.addEventListener('settingsUpdated', onSettings);
        return () => window.removeEventListener('settingsUpdated', onSettings);
    }, []);

    // Close popovers on outside click / Escape.
    useEffect(() => {
        const anyOpen = menuOpen || followOpen || blockOpen;
        if (!anyOpen) return undefined;
        const closeAll = () => {
            setMenuOpen(false);
            setFollowOpen(false);
            setBlockOpen(false);
        };
        const handler = (e) => {
            const t = e.target;
            if (menuOpen && menuRef.current && menuRef.current.contains(t)) return;
            if (followOpen && followRef.current && followRef.current.contains(t)) return;
            if (blockOpen && blockRef.current && blockRef.current.contains(t)) return;
            closeAll();
        };
        const key = (e) => { if (e.key === 'Escape') closeAll(); };
        document.addEventListener('mousedown', handler);
        document.addEventListener('keydown', key);
        return () => {
            document.removeEventListener('mousedown', handler);
            document.removeEventListener('keydown', key);
        };
    }, [menuOpen, followOpen, blockOpen]);

    // Clear flash flag after animation.
    useEffect(() => {
        if (!post || !post.post_id || !post.flash || !updatePost) return undefined;
        const t = setTimeout(() => {
            try { updatePost(post.post_id, { flash: false }); } catch (_) { /* noop */ }
        }, 1250);
        return () => clearTimeout(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [post && post.post_id]);

    // Derive safe values BEFORE any early return so hooks run in stable order.
    const safePost = useMemo(() => post || EMPTY_POST, [post]);
    const viewerAddress = state?.publicKey || '';
    const isLoggedIn = !!viewerAddress && viewerAddress !== 'guest';
    const isOwnPost = isLoggedIn && safePost.user_id === state?.publicKey;

    const postId = safePost.post_id ? String(safePost.post_id) : '';
    const topic = typeof safePost.topic === 'string' ? safePost.topic : '';
    const linkTarget = postId ? `/p/${postId}` : '#';
    const authorAddress = safePost.user_id || safePost.author || '';
    const authorDisplay = (() => {
        if (typeof safePost.username === 'string' && safePost.username.trim()) return safePost.username.trim();
        if (typeof authorAddress === 'string' && authorAddress.length > 0) {
            return `${authorAddress.slice(0, 10)}…`;
        }
        return 'Anonymous';
    })();
    const authorColor = getAuthorColor(safePost.author_level, safePost.author_is_new);
    const authorTooltip = getAuthorTooltip(safePost.author_level, safePost.author_is_new);

    let ts = Number(safePost.timestamp);
    if (!Number.isFinite(ts)) ts = Math.floor(Date.now() / 1000);
    if (ts > 1e12) ts = Math.floor(ts / 1000);

    const computedFollowingUser = (() => {
        if (!isLoggedIn || !authorAddress) return false;
        try { return isFollowing(viewerAddress, authorAddress); }
        catch (_) { return false; }
    })();
    const followingUser = followOverride !== null ? followOverride : computedFollowingUser;

    const computedFollowingTopic = (() => {
        if (!isLoggedIn || !topic) return false;
        try { return isSubscribed(viewerAddress, topic); }
        catch (_) { return false; }
    })();
    const followingTopic = topicFollowOverride !== null ? topicFollowOverride : computedFollowingTopic;

    const { mediaUrl, body } = useMemo(() => resolveDisplayContent(safePost), [safePost]);
    const hasMedia = !!mediaUrl;

    const hasTag = !!(safePost.tag && String(safePost.tag).trim());
    const normalizedTag = hasTag ? normalizeTag(String(safePost.tag).trim()) : '';
    const shouldBlurMedia = hasMedia && blurSensitive && hasTag && !blurOverride;

    const displayBody = useMemo(() => {
        if (!body) return '';
        if (showContent) return body;
        if (body.length <= MAX_BODY_LENGTH) return body;
        return body.slice(0, MAX_BODY_LENGTH).trimEnd() + '…';
    }, [body, showContent]);

    const commentCount = Number(safePost.comments) || 0;
    const feedBucket = typeof safePost.feed_bucket === 'string' ? safePost.feed_bucket : '';
    const feedBucketLabel = feedBucket && feedBucket !== 'guest'
        ? (FEED_BUCKET_LABELS[feedBucket] || '')
        : '';

    // Track whether any popover is open so we can raise this card's
    // `z-index` above sibling cards (fix for dropdown rendering behind the
    // next card in the feed).
    const anyMenuOpen = menuOpen || followOpen || blockOpen;

    // ─── Handlers ──────────────────────────────────────────────────────────

    const closeAllMenus = useCallback(() => {
        setMenuOpen(false);
        setFollowOpen(false);
        setBlockOpen(false);
    }, []);

    const handleCardClick = useCallback((e) => {
        if (isInteractiveTarget(e.target)) return;
        if (linkTarget && linkTarget !== '#') navigate(linkTarget);
    }, [navigate, linkTarget]);

    /**
     * Share handler ported from bluemoon: on mobile devices attempt the
     * native Web Share API (including image blob if the thumbnail is
     * shareable); on desktop fall back to copying the link to the
     * clipboard and flashing the inline `ShareSuccessMessage` toast for
     * 3 seconds. Keeps props compatible with bluemoon's UX so both themes
     * behave identically.
     */
    const handleShare = useCallback(async (e) => {
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        closeAllMenus();
        if (!postId) return;
        try {
            const path = `/p/${encodeURIComponent(postId)}`;
            const origin = (typeof window !== 'undefined' && window.location && window.location.origin)
                ? window.location.origin
                : '';
            const url = origin + path;
            const title = (safePost && safePost.title) ? String(safePost.title) : 'Mirage';
            const tagline = 'True Discourse. Decentralized. Unstoppable.';
            const text = `${title}\n\n${tagline}\n\n${url}`;

            const thumbnailUrl = (() => {
                const provided = safePost && typeof safePost.thumbnail === 'string' && safePost.thumbnail.trim()
                    ? safePost.thumbnail.trim()
                    : '';
                if (provided) return provided;
                if (mediaUrl && isLikelyImageUrl(mediaUrl)) return mediaUrl;
                return null;
            })();

            const isMobileDevice = (() => {
                try {
                    if (typeof window !== 'undefined' && window.matchMedia) {
                        return window.matchMedia('(max-width: 1000px)').matches;
                    }
                    if (typeof window !== 'undefined') {
                        return window.innerWidth < 1000;
                    }
                } catch (_) { /* noop */ }
                return false;
            })();

            if (isMobileDevice && typeof navigator !== 'undefined' && navigator.share) {
                try {
                    const shareData = { title, text, url };
                    if (thumbnailUrl && navigator.canShare) {
                        try {
                            const response = await fetch(thumbnailUrl);
                            const blob = await response.blob();
                            const file = new File([blob], 'thumbnail.jpg', { type: blob.type || 'image/jpeg' });
                            const testShareData = { ...shareData, files: [file] };
                            if (navigator.canShare(testShareData)) {
                                await navigator.share(testShareData);
                                return;
                            }
                        } catch (_) { /* fall through */ }
                    }
                    await navigator.share(shareData);
                    return;
                } catch (_) { /* fall through to clipboard */ }
            }

            if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(url);
                setShareCopied(true);
                setTimeout(() => setShareCopied(false), 3000);
                return;
            }
            if (typeof window !== 'undefined') {
                window.open(url, '_blank', 'noopener,noreferrer');
            }
        } catch (_) { /* noop */ }
    }, [closeAllMenus, postId, safePost, mediaUrl]);

    const handleCopyLink = useCallback(() => {
        closeAllMenus();
        const url = `${window.location.origin}${linkTarget}`;
        try {
            navigator.clipboard.writeText(url);
            setShareCopied(true);
            setTimeout(() => setShareCopied(false), 3000);
        } catch (_) { /* noop */ }
    }, [closeAllMenus, linkTarget]);

    const handleFollowUser = useCallback(async () => {
        closeAllMenus();
        if (!isLoggedIn || !authorAddress) return;
        const next = !followingUser;
        setFollowOverride(next);
        try {
            if (next) await follow(viewerAddress, authorAddress);
            else await unfollow(viewerAddress, authorAddress);
        } catch (_) {
            setFollowOverride(!next);
        }
    }, [closeAllMenus, isLoggedIn, authorAddress, followingUser, viewerAddress]);

    const handleFollowTopic = useCallback(async () => {
        closeAllMenus();
        if (!isLoggedIn || !topic) return;
        const next = !followingTopic;
        setTopicFollowOverride(next);
        try {
            if (next) await subscribe(viewerAddress, topic);
            else await unsubscribe(viewerAddress, topic);
        } catch (_) {
            setTopicFollowOverride(!next);
        }
    }, [closeAllMenus, isLoggedIn, topic, followingTopic, viewerAddress]);

    const handleBlockUser = useCallback(async () => {
        closeAllMenus();
        if (!isLoggedIn || !authorAddress) return;
        try { await tx.blockUser(authorAddress, true); } catch (_) { /* noop */ }
        if (typeof updatePost === 'function' && postId) {
            try { updatePost(postId, { blocked: true }); } catch (_) { /* noop */ }
        }
    }, [closeAllMenus, isLoggedIn, authorAddress, updatePost, postId]);

    const handleBlockPost = useCallback(async () => {
        closeAllMenus();
        if (!isLoggedIn) return;
        try { await tx.blockPost(postId, true); } catch (_) { /* noop */ }
        if (typeof updatePost === 'function') {
            try { updatePost(postId, { hidden_client: true }); } catch (_) { /* noop */ }
        }
    }, [closeAllMenus, isLoggedIn, postId, updatePost]);

    const handleBlockTopic = useCallback(async () => {
        closeAllMenus();
        if (!isLoggedIn || !topic) return;
        try { await tx.blockTopic(topic); } catch (_) { /* noop */ }
    }, [closeAllMenus, isLoggedIn, topic]);

    const handleReport = useCallback(async () => {
        closeAllMenus();
        if (!isLoggedIn) return;
        const reason = typeof window !== 'undefined'
            ? window.prompt('Report reason (optional)') || ''
            : '';
        try { await tx.reportPost(postId, reason); } catch (_) { /* noop */ }
    }, [closeAllMenus, isLoggedIn, postId]);

    const handleEdit = useCallback(() => {
        closeAllMenus();
        navigate(`/edit_post/${postId}`);
    }, [closeAllMenus, navigate, postId]);

    const handleDelete = useCallback(async () => {
        closeAllMenus();
        if (!isLoggedIn) return;
        try { await tx.deletePost(postId); } catch (_) { /* noop */ }
        if (typeof updatePost === 'function') {
            try { updatePost(postId, { deleted: true }); } catch (_) { /* noop */ }
        }
    }, [closeAllMenus, isLoggedIn, postId, updatePost]);

    /* Give Award / Gift Mirage / Gift Subscription
     *
     * The bluemoon theme implements these as full in-card confirmation
     * modals (donate amount entry, gift sub level picker, award catalog
     * iframe, etc.) — porting them here would roughly double the file's
     * size. For now we navigate to the author's profile, where the same
     * flows already exist in bluemoon's user view, and append a query
     * parameter so a future profile-side handler can auto-open the
     * matching modal. */
    const handleProfileAction = useCallback((action) => {
        closeAllMenus();
        const handle = post && (post.username || authorAddress);
        if (!handle) return;
        navigate(`/u/${encodeURIComponent(handle)}?action=${action}`);
    }, [closeAllMenus, navigate, post, authorAddress]);

    const handleGiveAward = useCallback(() => handleProfileAction('award'), [handleProfileAction]);
    const handleGiftMirage = useCallback(() => handleProfileAction('gift_mirage'), [handleProfileAction]);
    const handleGiftSubscription = useCallback(() => handleProfileAction('gift_subscription'), [handleProfileAction]);

    const handleRevealMedia = useCallback((e) => {
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        setBlurOverride(true);
    }, []);

    const stop = useCallback((e) => { e.stopPropagation(); }, []);

    // ─── Guards (after all hooks) ──────────────────────────────────────────
    if (!post || post.deleted || post.blocked) return null;
    if (typeof post.title !== 'string' || post.title.trim() === '') return null;
    if (typeof post.topic !== 'string' || post.topic.trim() === '') return null;

    // ─── Render ────────────────────────────────────────────────────────────

    return (
        <Card
            $flash={!!post.flash}
            $menuOpen={anyMenuOpen}
            onClick={handleCardClick}
            role="link"
            tabIndex={0}
        >
            <HeaderRow>
                <HeaderMeta>
                    <TopicLink to={`/t/${encodeURIComponent(topic)}`} onClick={stop}>
                        #{topic}
                    </TopicLink>
                    <HeaderDot>·</HeaderDot>
                    <UserLink
                        to={`/u/${encodeURIComponent(post.username || authorAddress)}`}
                        onClick={stop}
                        $tierColor={authorColor}
                        title={authorTooltip || undefined}
                    >
                        @{authorDisplay}
                    </UserLink>
                    <HeaderDot>·</HeaderDot>
                    <TimeText title={new Date(ts * 1000).toLocaleString()}>{formatAge(ts)}</TimeText>
                    {feedBucketLabel && (
                        <>
                            <HeaderDot>·</HeaderDot>
                            <FeedReasonInline>{feedBucketLabel}</FeedReasonInline>
                        </>
                    )}
                    {hasTag && (
                        <TagBadge $tag={normalizedTag}>{normalizedTag}</TagBadge>
                    )}
                </HeaderMeta>
                <HeaderActions>
                    {!isOwnPost && isLoggedIn && (
                        <PopoverRoot ref={followRef} onClick={stop}>
                            <FollowButton
                                type="button"
                                $active={followingUser || followingTopic}
                                aria-haspopup="menu"
                                aria-expanded={followOpen}
                                onClick={() => {
                                    setMenuOpen(false);
                                    setBlockOpen(false);
                                    setFollowOpen((v) => !v);
                                }}
                            >
                                {followingUser || followingTopic ? 'Following' : 'Follow'}
                            </FollowButton>
                            {followOpen && (
                                <Menu role="menu" aria-label="Follow options" $align="right">
                                    <MenuHeader>Follow</MenuHeader>
                                    <MenuItemBtn
                                        type="button"
                                        role="menuitemradio"
                                        aria-checked={followingTopic}
                                        $active={followingTopic}
                                        onClick={handleFollowTopic}
                                    >
                                        <HiOutlineHashtag />
                                        <span>{followingTopic ? `Unfollow #${topic}` : `Follow #${topic}`}</span>
                                    </MenuItemBtn>
                                    <MenuItemBtn
                                        type="button"
                                        role="menuitemradio"
                                        aria-checked={followingUser}
                                        $active={followingUser}
                                        onClick={handleFollowUser}
                                    >
                                        {followingUser ? <HiOutlineUserMinus /> : <HiOutlineUserPlus />}
                                        <span>{followingUser ? `Unfollow @${authorDisplay}` : `Follow @${authorDisplay}`}</span>
                                    </MenuItemBtn>
                                </Menu>
                            )}
                        </PopoverRoot>
                    )}
                    <PopoverRoot ref={menuRef} onClick={stop}>
                        <MoreButton
                            type="button"
                            aria-label="Post menu"
                            aria-haspopup="menu"
                            aria-expanded={menuOpen}
                            onClick={() => {
                                setFollowOpen(false);
                                setBlockOpen(false);
                                setMenuOpen((v) => !v);
                            }}
                        >
                            <EllipsisIcon />
                        </MoreButton>
                        {menuOpen && (
                            <Menu role="menu" aria-label="Post menu" $align="right">
                                <MenuItemBtn type="button" onClick={handleCopyLink}>
                                    <HiOutlineLink />
                                    <span>{shareCopied ? 'Copied!' : 'Copy link'}</span>
                                </MenuItemBtn>
                                {isOwnPost && (
                                    <>
                                        <MenuItemBtn type="button" onClick={handleEdit}>
                                            <HiOutlinePencilSquare />
                                            <span>Edit post</span>
                                        </MenuItemBtn>
                                        <MenuItemBtn type="button" $danger onClick={handleDelete}>
                                            <HiOutlineTrash />
                                            <span>Delete post</span>
                                        </MenuItemBtn>
                                    </>
                                )}
                                {!isOwnPost && isLoggedIn && (
                                    <>
                                        <MenuItemBtn type="button" onClick={handleFollowUser}>
                                            {followingUser ? <HiOutlineUserMinus /> : <HiOutlineUserPlus />}
                                            <span>{followingUser ? 'Unfollow user' : 'Follow user'}</span>
                                        </MenuItemBtn>
                                        <MenuItemBtn type="button" onClick={handleFollowTopic}>
                                            <HiOutlineHashtag />
                                            <span>{followingTopic ? 'Unfollow topic' : 'Follow topic'}</span>
                                        </MenuItemBtn>
                                        <MenuItemBtn type="button" onClick={handleGiveAward}>
                                            <HiOutlineSparkles />
                                            <span>Give Award</span>
                                        </MenuItemBtn>
                                        <MenuItemBtn type="button" onClick={handleGiftMirage}>
                                            <HiOutlineGift />
                                            <span>Gift Mirage</span>
                                        </MenuItemBtn>
                                        <MenuItemBtn type="button" onClick={handleGiftSubscription}>
                                            <HiOutlineGift />
                                            <span>Gift Subscription</span>
                                        </MenuItemBtn>
                                    </>
                                )}
                            </Menu>
                        )}
                    </PopoverRoot>
                </HeaderActions>
            </HeaderRow>

            <TitleLink to={linkTarget} onClick={stop}>{post.title}</TitleLink>

            {hasMedia && (
                <MediaWrap
                    $blur={shouldBlurMedia}
                    onClick={shouldBlurMedia ? handleRevealMedia : undefined}
                    {...(shouldBlurMedia ? { 'data-no-card-click': true } : {})}
                >
                    <InlineMedia
                        url={mediaUrl}
                        variant="root_post"
                        autoPlay={false}
                        mediaMeta={Array.isArray(post.media_meta) ? post.media_meta[0] || null : null}
                    />
                </MediaWrap>
            )}

            {displayBody && !shouldBlurMedia && (
                <Body>
                    <MarkdownRenderer text={displayBody} />
                </Body>
            )}

            <ActionRow onClick={stop}>
                <VoteSection state={state} post={post} updatePost={updatePost} inline />
                <ActionPill as={Link} to={linkTarget}>
                    <CommentIcon />
                    {formatCompact(commentCount)}
                </ActionPill>
                <Spacer />
                {isLoggedIn && !isOwnPost && (
                    <PopoverRoot ref={blockRef} onClick={stop}>
                        <ActionIconChip
                            type="button"
                            $danger
                            aria-haspopup="menu"
                            aria-expanded={blockOpen}
                            aria-label="Block or report"
                            title="Block or report"
                            onClick={() => {
                                setMenuOpen(false);
                                setFollowOpen(false);
                                setBlockOpen((v) => !v);
                            }}
                        >
                            <BlockIcon style={{ width: 18, height: 18 }} />
                        </ActionIconChip>
                        {blockOpen && (
                            <Menu role="menu" aria-label="Block and report" $align="right">
                                <MenuItemBtn type="button" $danger onClick={handleBlockUser}>
                                    <HiOutlineNoSymbol />
                                    <span>Block user</span>
                                </MenuItemBtn>
                                <MenuItemBtn type="button" $danger onClick={handleBlockPost}>
                                    <HiOutlineEyeSlash />
                                    <span>Block post</span>
                                </MenuItemBtn>
                                <MenuItemBtn type="button" $danger onClick={handleBlockTopic}>
                                    <HiOutlineNoSymbol />
                                    <span>Block topic</span>
                                </MenuItemBtn>
                                <MenuItemBtn type="button" $danger onClick={handleReport}>
                                    <HiOutlineFlag />
                                    <span>Report post</span>
                                </MenuItemBtn>
                            </Menu>
                        )}
                    </PopoverRoot>
                )}
                <ActionIconChip
                    type="button"
                    onClick={handleShare}
                    title={shareCopied ? 'Copied!' : 'Share'}
                    aria-label="Share post"
                >
                    <ShareIcon />
                </ActionIconChip>
            </ActionRow>

            {shareCopied && (
                <ShareSuccessMessage onClick={stop} data-no-card-click>
                    <span>✓</span>
                    link copied to clipboard
                </ShareSuccessMessage>
            )}

            {footer}
        </Card>
    );
}

export default memo(CardView, (prev, next) => {
    const p = prev.post;
    const n = next.post;
    if (p === n) return prev.showContent === next.showContent && prev.state === next.state;
    return (
        prev.showContent === next.showContent &&
        prev.state === next.state &&
        p?.post_id === n?.post_id &&
        p?.title === n?.title &&
        p?.content === n?.content &&
        p?.comments === n?.comments &&
        p?.points === n?.points &&
        p?.direction === n?.direction &&
        p?.flash === n?.flash &&
        p?.deleted === n?.deleted &&
        p?.hidden_client === n?.hidden_client
    );
});
