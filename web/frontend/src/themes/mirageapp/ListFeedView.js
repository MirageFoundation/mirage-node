import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import styled, { css, keyframes, useTheme } from "styled-components";
import { Link, useNavigate } from "react-router-dom";
import { HiChevronDown } from "react-icons/hi2";

import CardView from "./components/CardView";
import InlineMedia from "./components/InlineMedia";
import MarkdownRenderer from "./components/MarkdownRenderer";
import { getThemeFamily } from "../../registry/theme";
import { getAuthorColor } from "../../utils/tierColors";
import { buildPhotonUrl, isLikelyImageUrl, isLikelyVideoUrl } from "../../utils/media";
import Storage from "../../utils/Storage";

/**
 * ListFeedView (mirageapp) — mobile-app inspired feed list.
 *
 * Feed header contains only two controls:
 *   1. Sort button       — plain text + chevron (no bg) opens a sort menu.
 *   2. View mode button  — small grid icon + chevron opens a view menu
 *                          with two choices: Card / Compact.
 *
 * View mode is persisted per viewer in localStorage.
 */

// ─── Storage keys ──────────────────────────────────────────────────────────

export const VIEW_MODE_KEY = 'mirageapp_feed_view_mode';
export const VIEW_MODE_DEFAULT = 'compact';
export const VIEW_MODES = ['card', 'compact'];

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

const SORT_LABELS = {
    best: 'Best',
    new: 'New',
};

// ─── Animations ────────────────────────────────────────────────────────────

const slideIn = keyframes`
    from { opacity: 0; transform: translateY(6px); }
    to   { opacity: 1; transform: translateY(0); }
`;

const slideOut = keyframes`
    from { opacity: 1; max-height: 400px; }
    to   { opacity: 0; max-height: 0; }
`;

const flashGlow = keyframes`
    0%   { background: rgba(102, 126, 234, 0.12); }
    100% { background: transparent; }
`;

// ─── Container primitives ─────────────────────────────────────────────────

const FeedList = styled.div.attrs(({ $viewMode }) => ({
    'data-feed-view-mode': $viewMode,
}))`
    display: flex;
    flex-direction: column;
    width: 100%;
    max-width: 720px;
    margin: 0;
    background: ${({ theme }) => theme.colors.bg};

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

/* Row slot owns the between-card divider so it sits OUTSIDE the card
 * (the card's hover bg no longer bleeds into the divider line, and the
 * divider clearly reads as "below the card" rather than as its border).
 * The last slot omits the divider so the feed doesn't end with a hairline. */
export const RowSlot = styled.div`
    position: relative;
    opacity: 1;
    animation: ${slideIn} 0.25s ease-out;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};

    &:last-child {
        border-bottom: none;
    }

    ${({ $hiding }) =>
        $hiding &&
        css`
            animation: ${slideOut} 0.25s ease-out forwards;
            overflow: hidden;
            pointer-events: none;
        `}

    ${({ $flash }) =>
        $flash &&
        css`
            animation: ${slideIn} 0.25s ease-out, ${flashGlow} 1.1s ease-out;
        `}
`;

// ─── Feed toolbar ──────────────────────────────────────────────────────────

const Toolbar = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.2rem;
    padding: 0 0.5rem 0.4rem 0.25rem;
    background: ${({ theme }) => theme.colors.bg};
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const CtrlButton = styled.button`
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    height: 28px;
    padding: 0 0.5rem;
    background: transparent;
    border: none;
    border-radius: 6px;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-family: inherit;
    font-size: 0.68rem;
    font-weight: 400;
    cursor: pointer;
    outline: none;
    line-height: 1;

    & > svg {
        color: ${({ theme }) => theme.colors.feedCtrlText};
        fill: currentColor;
    }

    &:hover,
    &[aria-expanded='true'] {
        background: ${({ theme }) => theme.colors.feedCtrlHoverBg};
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => theme.colors.focusBlue};
        outline-offset: 2px;
    }
`;

const ChevronWrap = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: inherit;
    transition: transform 0.15s ease;
    transform: ${({ $expanded }) => ($expanded ? 'rotate(180deg)' : 'rotate(0deg)')};

    svg {
        width: 12px;
        height: 12px;
        display: block;
    }
`;

const ViewIconSlot = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 15px;
    height: 15px;
    color: inherit;

    svg {
        width: 15px;
        height: 15px;
        display: block;
    }
`;

// ─── Popover menu ──────────────────────────────────────────────────────────

const PopoverRoot = styled.div`
    position: relative;
    display: inline-flex;
    align-items: center;
`;

const Menu = styled.div`
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    /* Shrinks to the widest item. MenuItem uses white-space: nowrap
       so every option stays on one line. */
    min-width: max-content;
    width: max-content;
    padding: 0;
    background: ${({ theme }) => theme.colors.menuBg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    z-index: 40;
    display: flex;
    flex-direction: column;
    gap: 0;
    overflow: hidden;
`;

/* Header uses the SAME vertical padding as MenuItem so header + options
 * share a single rhythm, but slightly heavier weight (500) than the options (400). */
const MenuHeader = styled.div`
    padding: 10px 14px;
    font-size: 0.7rem;
    font-weight: 500;
    line-height: 1;
    color: ${({ theme }) => theme.colors.menuHeaderText};
    white-space: nowrap;
`;

const MenuItem = styled.button`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    width: 100%;
    padding: 10px 14px;
    white-space: nowrap;
    background: ${({ theme, $active }) =>
        $active ? theme.colors.menuSelectedBg : 'transparent'};
    border: none;
    border-radius: 0;
    color: ${({ theme, $active }) =>
        $active ? theme.colors.sidebarItemActiveText : theme.colors.sidebarItemText};
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: 400;
    text-align: left;
    cursor: pointer;
    line-height: 1;
    transition: background 0.12s ease, color 0.12s ease;

    /* Hover:
     *  - Dark: bg stays transparent, text + icons lift to pure white.
     *  - Light: bg lifts to rgb(246,248,249), text stays normal.
     * Handled via the menuItemHoverBg / menuItemHoverText tokens. */
    &:hover {
        background: ${({ theme, $active }) =>
        $active ? theme.colors.menuSelectedBg : theme.colors.menuItemHoverBg};
        color: ${({ theme, $active }) =>
        $active ? theme.colors.sidebarItemActiveText : theme.colors.menuItemHoverText};
    }

    & > svg {
        width: 15px;
        height: 15px;
        color: inherit;
        flex-shrink: 0;
    }
`;

// ─── SVG icons (2-box = card, 3-box = compact) ─────────────────────────────

const IconCard = (props) => (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
        <rect x="3" y="4" width="18" height="7" rx="1.4" stroke="currentColor" strokeWidth="1.6" />
        <rect x="3" y="13" width="18" height="7" rx="1.4" stroke="currentColor" strokeWidth="1.6" />
    </svg>
);

const IconCompact = (props) => (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props}>
        <rect x="3" y="4" width="18" height="4.2" rx="1.1" stroke="currentColor" strokeWidth="1.6" />
        <rect x="3" y="9.9" width="18" height="4.2" rx="1.1" stroke="currentColor" strokeWidth="1.6" />
        <rect x="3" y="15.8" width="18" height="4.2" rx="1.1" stroke="currentColor" strokeWidth="1.6" />
    </svg>
);

// ─── Compact row ───────────────────────────────────────────────────────────
//
// Compact layout (thumbnail + stacked text):
//
//   ┌──────┐  #topic · @user · time
//   │ thumb│  Title (smaller than card-mode title)
//   │ 72px │  [▲ cnt ▼]  N comments  Share  [⇱ expand]
//   └──────┘
//
// When "expand" is clicked, the row reveals full-size InlineMedia + the
// post body below the footer (without navigating away). Click again to
// collapse. Typography matches CardView.

const CompactRoot = styled.article`
    display: grid;
    grid-template-columns: 84px minmax(0, 1fr);
    grid-template-rows: auto auto auto;
    gap: 0.2rem 0.75rem;
    padding: 0.5rem 1rem 0.4rem;
    margin: 4px 0;
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid transparent;
    border-radius: 8px;
    position: relative;
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
        grid-template-columns: 68px minmax(0, 1fr);
        gap: 0.15rem 0.6rem;
        padding: 0.45rem 0.85rem 0.35rem;
        border-radius: 6px;
    }
`;

/* Thumbnail / placeholder column — spans the 3 text rows on the left. */
const CompactThumbLink = styled(Link)`
    grid-row: 1 / span 3;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    width: 84px;
    height: 84px;
    border-radius: 8px;
    overflow: hidden;
    background: ${({ theme }) => theme.colors.actionIconBg};
    text-decoration: none;
    flex-shrink: 0;

    img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    @media (max-width: 600px) {
        width: 68px;
        height: 68px;
        border-radius: 6px;
    }
`;

const CompactThumbPlaceholder = styled.div`
    grid-row: 1 / span 3;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 84px;
    height: 84px;
    border-radius: 8px;
    background: ${({ theme }) => theme.colors.gradient};
    color: ${({ theme }) => theme.colors.sidebarItemActiveText};
    font-size: 1.1rem;
    font-weight: 700;
    flex-shrink: 0;

    @media (max-width: 600px) {
        width: 68px;
        height: 68px;
        border-radius: 6px;
        font-size: 0.95rem;
    }
`;

/* Header row mirrors CardView's HeaderMeta exactly so the two view modes
 * share a single metadata style. Font sizes + weights are copied 1:1. */
const CompactHeader = styled.div`
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

const CompactTopicLink = styled(Link)`
    font-weight: 500;
    font-size: 0.62rem;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    text-decoration: none;
    &:hover { color: ${({ theme }) => theme.colors.text}; text-decoration: none; }
`;

const CompactUserLink = styled(Link)`
    color: ${({ theme, $tierColor }) => $tierColor || theme.colors.feedCtrlText};
    font-weight: 500;
    font-size: 0.62rem;
    text-decoration: none;
    &:hover { color: ${({ theme, $tierColor }) => $tierColor || theme.colors.text}; }
`;

const CompactHeaderDot = styled.span`
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-size: 0.75rem;
    font-weight: 700;
    line-height: 1;
`;

const CompactTime = styled.span`
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-size: 0.62rem;
    font-weight: 400;
`;

const CompactFeedReasonInline = styled.span`
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-size: 0.62rem;
    font-weight: 400;
    font-style: italic;
`;

/* Title is smaller than CardView's title so the compact row stays short
 * and the thumbnail/title/footer fit the 84px thumbnail height. */
const CompactTitle = styled(Link)`
    display: block;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.72rem;
    font-weight: 700;
    line-height: 1.3;
    text-decoration: none;
    word-break: break-word;
    overflow-wrap: anywhere;

    &:hover { color: ${({ theme }) => theme.colors.text}; text-decoration: none; }
    &:visited { color: ${({ theme }) => theme.colors.text}; }

    @media (max-width: 1000px) {
        font-size: 0.66rem;
    }
`;

/* Footer row: vote pill + plain-text comment / share buttons + expand chip. */
const CompactFooter = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.1rem;
`;

/* Plain-text action button used for the "N comments" and "Share" labels.
 * Matches the 32px height of the vote pill + expand chip so the hover
 * tile lines up visually with the sibling filled chips. */
const CompactTextAction = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 32px;
    padding: 0 12px;
    margin: 0;
    background: transparent;
    border: none;
    border-radius: 9999px;
    font: inherit;
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    cursor: pointer;
    text-decoration: none;
    transition: color 0.12s ease, background 0.12s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.actionIconHoverBg};
        color: ${({ theme }) => theme.colors.sidebarItemActiveText};
    }
`;

/* Expand / collapse chip — same filled surface as the vote pill so the
 * two controls visually balance the footer row. */
const CompactExpandChip = styled.button`
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
    color: ${({ theme }) => theme.colors.text};
    cursor: pointer;
    transition: background 0.12s ease;

    &:hover { background: ${({ theme }) => theme.colors.actionIconHoverBg}; }

    svg {
        width: 16px;
        height: 16px;
    }
`;

const CompactSpacer = styled.div`
    flex: 1 1 auto;
    min-width: 0;
`;

const CompactShareNote = styled.span`
    font-size: 0.62rem;
    font-weight: 500;
    color: #22c55e;
    margin-left: 0.25rem;
`;

/* Expanded content block rendered below the footer when the user clicks
 * the expand chip. Spans the full grid width so media can use all of it. */
const CompactExpandedBlock = styled.div`
    grid-column: 1 / -1;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin-top: 0.3rem;
`;

const CompactExpandedMedia = styled.div`
    max-width: 100%;
    overflow: hidden;
    border-radius: 10px;
`;

const CompactExpandedBody = styled.div`
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

// ─── Helpers ───────────────────────────────────────────────────────────────

function formatAge(tsSec) {
    const now = Math.floor(Date.now() / 1000);
    const diff = Math.max(0, now - tsSec);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    if (diff < 2592000) return `${Math.floor(diff / 86400)}d`;
    return new Date(tsSec * 1000).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
    });
}

export function loadViewMode() {
    try {
        const raw = Storage.load(VIEW_MODE_KEY, VIEW_MODE_DEFAULT);
        return VIEW_MODES.includes(raw) ? raw : VIEW_MODE_DEFAULT;
    } catch (_) {
        return VIEW_MODE_DEFAULT;
    }
}

export function saveViewMode(next) {
    if (!VIEW_MODES.includes(next)) return;
    try { Storage.save(VIEW_MODE_KEY, next); } catch (_) { /* noop */ }
}

/* Resolve the post's primary media URL + post body. Mirrors the helper in
 * CardView so compact expansion shows the same asset the card would. */
function extractFirstUrl(content) {
    if (!content) return null;
    const m = String(content).match(/https?:\/\/[^\s<>"']+/);
    return m ? m[0] : null;
}

function resolveCompactContent(post) {
    const mediaList = Array.isArray(post?.media) && post.media.length > 0 ? post.media : null;
    const rawBody = String(post?.content || '');

    if (mediaList) {
        return { mediaUrl: mediaList[0], body: rawBody.trim() };
    }

    const firstUrl = extractFirstUrl(rawBody);
    if (firstUrl && (isLikelyImageUrl(firstUrl) || isLikelyVideoUrl(firstUrl))) {
        const body = rawBody.replace(firstUrl, '').trim();
        return { mediaUrl: firstUrl, body };
    }

    return { mediaUrl: null, body: rawBody.trim() };
}

/* Small photon-scaled thumbnail for the compact left column. Returns null
 * if we couldn't derive an image URL (the component falls back to the
 * first-letter placeholder). */
function getCompactThumb(post) {
    const thumb = post?.thumbnail;
    if (typeof thumb === 'string' && thumb.trim() && isLikelyImageUrl(thumb)) {
        try { return buildPhotonUrl(thumb, { w: 144, h: 144 }); }
        catch (_) { /* noop */ }
    }
    if (Array.isArray(post?.media) && post.media.length > 0) {
        const first = post.media[0];
        if (typeof first === 'string' && isLikelyImageUrl(first)) {
            try { return buildPhotonUrl(first, { w: 144, h: 144 }); }
            catch (_) { /* noop */ }
        }
    }
    const rawBody = String(post?.content || '');
    const firstUrl = extractFirstUrl(rawBody);
    if (firstUrl && isLikelyImageUrl(firstUrl)) {
        try { return buildPhotonUrl(firstUrl, { w: 144, h: 144 }); }
        catch (_) { /* noop */ }
    }
    return null;
}

// ─── Compact row component ─────────────────────────────────────────────────

// A click on a link/button/popover inside the compact row must NOT bubble
// up to the card-level navigate handler. Mirrors CardView.isInteractiveTarget.
function isCompactInteractive(target) {
    if (!(target instanceof Element)) return false;
    return !!target.closest('a, button, [data-no-card-click]');
}

function CompactRow({ post, state, updatePost }) {
    const theme = useTheme();
    const navigate = useNavigate();
    const VoteSection = useMemo(
        () => getThemeFamily(theme.themeId).VoteSection,
        [theme.themeId]
    );

    const [shareCopied, setShareCopied] = useState(false);
    const [expanded, setExpanded] = useState(false);

    const postId = post && post.post_id ? String(post.post_id) : '';
    const linkTarget = postId ? `/p/${postId}` : '#';

    const handleRowClick = useCallback((e) => {
        if (isCompactInteractive(e.target)) return;
        if (linkTarget && linkTarget !== '#') navigate(linkTarget);
    }, [navigate, linkTarget]);

    const stop = useCallback((e) => { e.stopPropagation(); }, []);

    const handleToggleExpand = useCallback((e) => {
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        setExpanded((v) => !v);
    }, []);

    const handleShare = useCallback(async (e) => {
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        if (!postId) return;
        try {
            const origin = (typeof window !== 'undefined' && window.location && window.location.origin)
                ? window.location.origin
                : '';
            const url = `${origin}/p/${encodeURIComponent(postId)}`;
            if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(url);
                setShareCopied(true);
                setTimeout(() => setShareCopied(false), 2000);
                return;
            }
            if (typeof window !== 'undefined') {
                window.open(url, '_blank', 'noopener,noreferrer');
            }
        } catch (_) { /* noop */ }
    }, [postId]);

    const { mediaUrl, body } = useMemo(() => resolveCompactContent(post || {}), [post]);
    const thumbUrl = useMemo(() => getCompactThumb(post || {}), [post]);
    const canExpand = Boolean(mediaUrl || (typeof body === 'string' && body.trim()));

    if (!post || !post.post_id) return null;
    if (typeof post.title !== 'string' || post.title.trim() === '') return null;
    if (typeof post.topic !== 'string' || post.topic.trim() === '') return null;
    if (post.deleted || post.hidden_client) return null;

    const topic = String(post.topic);
    const authorAddress = post.user_id || post.author || '';
    const displayAuthor = (() => {
        if (typeof post.username === 'string' && post.username.trim()) return post.username.trim();
        if (typeof authorAddress === 'string' && authorAddress.length > 0) {
            return `${authorAddress.slice(0, 8)}…`;
        }
        return 'anonymous';
    })();
    const authorColor = getAuthorColor(post.author_level, post.author_is_new);

    let ts = Number(post.timestamp);
    if (!Number.isFinite(ts)) ts = Math.floor(Date.now() / 1000);
    if (ts > 1e12) ts = Math.floor(ts / 1000);

    const commentCount = Number(post.comments) || 0;
    const placeholderChar = (topic.trim()[0] || '#').toUpperCase();
    const feedBucket = typeof post.feed_bucket === 'string' ? post.feed_bucket : '';
    const feedBucketLabel = feedBucket && feedBucket !== 'guest'
        ? (FEED_BUCKET_LABELS[feedBucket] || '')
        : '';

    return (
        <CompactRoot
            $flash={!!post.flash}
            onClick={handleRowClick}
            role="link"
            tabIndex={0}
        >
            {thumbUrl ? (
                <CompactThumbLink to={linkTarget} aria-label={post.title} onClick={stop}>
                    <img src={thumbUrl} alt="" loading="lazy" />
                </CompactThumbLink>
            ) : (
                <CompactThumbPlaceholder aria-hidden="true">{placeholderChar}</CompactThumbPlaceholder>
            )}

            <CompactHeader>
                <CompactTopicLink to={`/t/${encodeURIComponent(topic)}`} onClick={stop}>
                    #{topic}
                </CompactTopicLink>
                <CompactHeaderDot>·</CompactHeaderDot>
                <CompactUserLink
                    to={`/u/${encodeURIComponent(post.username || authorAddress)}`}
                    onClick={stop}
                    $tierColor={authorColor}
                >
                    @{displayAuthor}
                </CompactUserLink>
                <CompactHeaderDot>·</CompactHeaderDot>
                <CompactTime>{formatAge(ts)}</CompactTime>
                {feedBucketLabel && (
                    <>
                        <CompactHeaderDot>·</CompactHeaderDot>
                        <CompactFeedReasonInline>{feedBucketLabel}</CompactFeedReasonInline>
                    </>
                )}
            </CompactHeader>

            <CompactTitle to={linkTarget} onClick={stop}>
                {post.title}
            </CompactTitle>

            <CompactFooter onClick={stop}>
                <VoteSection state={state} post={post} updatePost={updatePost} inline />
                <CompactTextAction as={Link} to={linkTarget}>
                    {commentCount} comment{commentCount !== 1 ? 's' : ''}
                </CompactTextAction>
                <CompactTextAction type="button" onClick={handleShare}>
                    Share
                </CompactTextAction>
                {shareCopied && <CompactShareNote>link copied</CompactShareNote>}
                <CompactSpacer />
                {canExpand && (
                    <CompactExpandChip
                        type="button"
                        onClick={handleToggleExpand}
                        aria-expanded={expanded}
                        aria-label={expanded ? 'Collapse post' : 'Expand post'}
                        title={expanded ? 'Collapse' : 'Expand'}
                    >
                        <HiChevronDown style={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.15s ease' }} />
                    </CompactExpandChip>
                )}
            </CompactFooter>

            {expanded && canExpand && (
                <CompactExpandedBlock onClick={stop} data-no-card-click>
                    {mediaUrl && (
                        <CompactExpandedMedia>
                            <InlineMedia
                                url={mediaUrl}
                                variant="root_post"
                                autoPlay={false}
                                mediaMeta={Array.isArray(post.media_meta) ? post.media_meta[0] || null : null}
                            />
                        </CompactExpandedMedia>
                    )}
                    {body && (
                        <CompactExpandedBody>
                            <MarkdownRenderer text={body} />
                        </CompactExpandedBody>
                    )}
                </CompactExpandedBlock>
            )}
        </CompactRoot>
    );
}

export const MemoCompactRow = memo(CompactRow, (prev, next) => {
    const p = prev.post;
    const n = next.post;
    if (p === n) return prev.state === next.state;
    return (
        prev.state === next.state &&
        p?.post_id === n?.post_id &&
        p?.title === n?.title &&
        p?.thumbnail === n?.thumbnail &&
        p?.points === n?.points &&
        p?.direction === n?.direction &&
        p?.comments === n?.comments &&
        p?.flash === n?.flash &&
        p?.deleted === n?.deleted &&
        p?.hidden_client === n?.hidden_client
    );
});

// ─── Row wrapper (picks card/compact) ──────────────────────────────────────

function FeedRow({ post, state, updatePost, hiding, flashing, viewMode }) {
    if (!post || !post.post_id) return null;
    if (typeof post.title !== 'string' || post.title.trim() === '') return null;
    if (typeof post.topic !== 'string' || post.topic.trim() === '') return null;
    if (post.deleted || post.hidden_client) return null;

    return (
        <RowSlot $hiding={hiding} $flash={flashing}>
            {viewMode === 'compact' ? (
                <MemoCompactRow post={post} state={state} updatePost={updatePost} />
            ) : (
                <CardView state={state} post={post} updatePost={updatePost} />
            )}
        </RowSlot>
    );
}

const MemoRow = memo(FeedRow, (prev, next) => {
    const p = prev.post;
    const n = next.post;
    if (prev.hiding !== next.hiding) return false;
    if (prev.flashing !== next.flashing) return false;
    if (prev.viewMode !== next.viewMode) return false;
    if (p === n) return prev.state === next.state;
    return (
        prev.state === next.state &&
        p?.post_id === n?.post_id &&
        p?.title === n?.title &&
        p?.content === n?.content &&
        p?.thumbnail === n?.thumbnail &&
        p?.points === n?.points &&
        p?.direction === n?.direction &&
        p?.comments === n?.comments &&
        p?.flash === n?.flash &&
        p?.deleted === n?.deleted &&
        p?.hidden_client === n?.hidden_client
    );
});

// ─── Toolbar popover hooks ─────────────────────────────────────────────────

function useOutsideClick(ref, onClose, active) {
    useEffect(() => {
        if (!active) return undefined;
        const handler = (e) => {
            if (ref.current && !ref.current.contains(e.target)) onClose();
        };
        const key = (e) => { if (e.key === 'Escape') onClose(); };
        document.addEventListener('mousedown', handler);
        document.addEventListener('keydown', key);
        return () => {
            document.removeEventListener('mousedown', handler);
            document.removeEventListener('keydown', key);
        };
    }, [ref, onClose, active]);
}

// ─── Standalone feed view toggle ──────────────────────────────────────────

/**
 * Small, standalone view-toggle button usable outside the feed toolbar
 * (e.g. the Search results header). Renders the same grid-icon +
 * chevron `CtrlButton` + Card/Compact popover menu as the main feed.
 *
 * Controlled: caller owns `viewMode` and receives changes via
 * `onChange(next)`. Persisting to localStorage is the caller's
 * responsibility (use `saveViewMode(next)`) so the host page can decide
 * whether the choice should sync with the home feed.
 */
export function FeedViewToggle({ viewMode, onChange, className }) {
    const [open, setOpen] = useState(false);
    const anchorRef = useRef(null);
    useOutsideClick(anchorRef, () => setOpen(false), open);

    const ViewIcon = viewMode === 'compact' ? IconCompact : IconCard;
    const handleChange = useCallback((next) => {
        if (!VIEW_MODES.includes(next)) return;
        if (typeof onChange === 'function') onChange(next);
        setOpen(false);
    }, [onChange]);

    return (
        <PopoverRoot ref={anchorRef} className={className}>
            <CtrlButton
                type="button"
                aria-haspopup="menu"
                aria-expanded={open}
                aria-label="Change feed view"
                onClick={() => setOpen((v) => !v)}
            >
                <ViewIconSlot>
                    <ViewIcon />
                </ViewIconSlot>
                <ChevronWrap $expanded={open}>
                    <HiChevronDown />
                </ChevronWrap>
            </CtrlButton>
            {open && (
                <Menu role="menu" aria-label="View">
                    <MenuHeader>View</MenuHeader>
                    <MenuItem
                        type="button"
                        role="menuitemradio"
                        aria-checked={viewMode === 'card'}
                        $active={viewMode === 'card'}
                        onClick={() => handleChange('card')}
                    >
                        <span>Card</span>
                        <IconCard />
                    </MenuItem>
                    <MenuItem
                        type="button"
                        role="menuitemradio"
                        aria-checked={viewMode === 'compact'}
                        $active={viewMode === 'compact'}
                        onClick={() => handleChange('compact')}
                    >
                        <span>Compact</span>
                        <IconCompact />
                    </MenuItem>
                </Menu>
            )}
        </PopoverRoot>
    );
}

// ─── Default export ────────────────────────────────────────────────────────

export default function ListFeedView({
    posts,
    state,
    updatePost,
    hidingPostsSet,
    flashingPostsSet,
    viewerAddress,
    sortMode,
    onSortChange,
    showSortTabs = false,
    // feedNavTopic and sidebar props are intentionally ignored — the new
    // header no longer renders nav tabs or a sidebar action column.
}) {
    const hidingSet = hidingPostsSet instanceof Set ? hidingPostsSet : new Set();
    const flashingSet = flashingPostsSet instanceof Set ? flashingPostsSet : new Set();
    const viewerKey = String(viewerAddress || '').toLowerCase();

    const [viewMode, setViewMode] = useState(() => loadViewMode());
    const [sortOpen, setSortOpen] = useState(false);
    const [viewOpen, setViewOpen] = useState(false);
    const sortAnchorRef = useRef(null);
    const viewAnchorRef = useRef(null);

    useOutsideClick(sortAnchorRef, () => setSortOpen(false), sortOpen);
    useOutsideClick(viewAnchorRef, () => setViewOpen(false), viewOpen);

    const changeView = useCallback((next) => {
        if (!VIEW_MODES.includes(next)) return;
        setViewMode(next);
        try { Storage.save(VIEW_MODE_KEY, next); } catch (_) { /* noop */ }
        setViewOpen(false);
    }, []);

    const changeSort = useCallback((next) => {
        if (typeof onSortChange === 'function') onSortChange(next);
        setSortOpen(false);
    }, [onSortChange]);

    const rows = useMemo(() => {
        if (!Array.isArray(posts)) return [];
        return posts.filter(Boolean);
    }, [posts]);

    if (rows.length === 0 && !showSortTabs) return null;

    const currentSortLabel = SORT_LABELS[sortMode] || SORT_LABELS.best;
    const ViewIcon = viewMode === 'compact' ? IconCompact : IconCard;

    return (
        <FeedList $viewMode={viewMode}>
            {showSortTabs && (
                <Toolbar aria-label="Feed sort and view">
                    <PopoverRoot ref={sortAnchorRef}>
                        <CtrlButton
                            type="button"
                            aria-haspopup="menu"
                            aria-expanded={sortOpen}
                            onClick={() => setSortOpen((v) => !v)}
                        >
                            <span>{currentSortLabel}</span>
                            <ChevronWrap $expanded={sortOpen}>
                                <HiChevronDown />
                            </ChevronWrap>
                        </CtrlButton>
                        {sortOpen && (
                            <Menu role="menu" aria-label="Sort posts">
                                <MenuHeader>Sort by</MenuHeader>
                                {['best', 'new'].map((key) => (
                                    <MenuItem
                                        key={key}
                                        type="button"
                                        role="menuitemradio"
                                        aria-checked={sortMode === key}
                                        $active={sortMode === key}
                                        onClick={() => changeSort(key)}
                                    >
                                        <span>{SORT_LABELS[key]}</span>
                                    </MenuItem>
                                ))}
                            </Menu>
                        )}
                    </PopoverRoot>

                    <PopoverRoot ref={viewAnchorRef}>
                        <CtrlButton
                            type="button"
                            aria-haspopup="menu"
                            aria-expanded={viewOpen}
                            aria-label="Change feed view"
                            onClick={() => setViewOpen((v) => !v)}
                        >
                            <ViewIconSlot>
                                <ViewIcon />
                            </ViewIconSlot>
                            <ChevronWrap $expanded={viewOpen}>
                                <HiChevronDown />
                            </ChevronWrap>
                        </CtrlButton>
                        {viewOpen && (
                            <Menu role="menu" aria-label="View">
                                <MenuHeader>View</MenuHeader>
                                <MenuItem
                                    type="button"
                                    role="menuitemradio"
                                    aria-checked={viewMode === 'card'}
                                    $active={viewMode === 'card'}
                                    onClick={() => changeView('card')}
                                >
                                    <span>Card</span>
                                    <IconCard />
                                </MenuItem>
                                <MenuItem
                                    type="button"
                                    role="menuitemradio"
                                    aria-checked={viewMode === 'compact'}
                                    $active={viewMode === 'compact'}
                                    onClick={() => changeView('compact')}
                                >
                                    <span>Compact</span>
                                    <IconCompact />
                                </MenuItem>
                            </Menu>
                        )}
                    </PopoverRoot>
                </Toolbar>
            )}

            {rows.map((post) => {
                const postKey = String(post.post_id || '').toLowerCase();
                const hiding = hidingSet.has(postKey);
                const isViewerPost = viewerKey && String(post.author || post.user_id || '').toLowerCase() === viewerKey;
                let ts = Number(post.timestamp);
                if (Number.isFinite(ts) && ts > 1e12) ts = Math.floor(ts / 1000);
                const isRecent = Number.isFinite(ts)
                    ? (Math.floor(Date.now() / 1000) - ts) <= 30
                    : false;
                const flashing = !hiding && (flashingSet.has(postKey) || !!post.flash || (isViewerPost && isRecent));

                return (
                    <MemoRow
                        key={post.post_id}
                        post={post}
                        state={state}
                        updatePost={updatePost}
                        hiding={hiding}
                        flashing={flashing}
                        viewMode={viewMode}
                    />
                );
            })}
        </FeedList>
    );
}
