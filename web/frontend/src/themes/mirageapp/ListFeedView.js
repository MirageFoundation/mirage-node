import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import styled, { css, keyframes, useTheme } from "styled-components";
import { Link, useNavigate } from "react-router-dom";
import { HiChevronDown } from "react-icons/hi2";

import CardView from "./components/CardView";
import InlineMedia from "./components/InlineMedia";
import MarkdownRenderer from "./components/MarkdownRenderer";
import { MoreMenuChip, BlockChip } from "./components/PostMenu";
import PostPlaceholderAvatar from "./components/PostPlaceholderAvatar";
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
export const VIEW_MODE_CHANGE_EVENT = 'mirageapp-feed-view-mode-change';

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
    max-width: 820px;
    margin: 0;
    background: ${({ theme }) => theme.colors.bg};

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

    /* Very large screens (> average laptop): lock the feed to a fixed
     * centered column so its position stays stable regardless of sidebar
     * visibility OR feed view mode. Uses the same two-attribute specificity
     * as the rules above (plus later source order) so it wins on overlap.
     * Grows to 960 px on large desktops / external monitors. */
    @media (min-width: 1500px) {
        [data-sidebar-hidden] &[data-feed-view-mode] {
            width: 100%;
            max-width: 960px;
            margin-left: auto;
            margin-right: auto;
        }
    }

    /* Ultrawide / 4K displays (> 1900 px): grow the feed column further
     * so it fills more of the available viewport on large external
     * monitors while remaining centered and readable. */
    @media (min-width: 1900px) {
        [data-sidebar-hidden] &[data-feed-view-mode] {
            width: 100%;
            max-width: 1200px;
            margin-left: auto;
            margin-right: auto;
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

    /* Mobile (below the 600px breakpoint) gets extra breathing room above
     * the title — on narrow screens the toolbar sits directly under the
     * sticky MobileHeader, which made the topic title (e.g. "#memes")
     * look cramped against the top edge. */
    @media (max-width: 600px) {
        padding: 0.75rem 0.5rem 0.5rem 0.5rem;
    }
`;

/* Optional title that can sit at the left of the toolbar (e.g. the
 * topic name on `/t/:topic` feeds). Anchors to the leading edge and
 * pushes any sort/view controls to the right via `margin-left: auto`
 * on the first adjacent `PopoverRoot`. */
const ToolbarTitle = styled.h1`
    margin: 0;
    padding: 0 0.5rem 0 0.5rem;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.95rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    line-height: 1.2;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 0 1 auto;

    /* When a title is present, the first control to its right gets an
     * auto left margin so the control cluster hugs the right edge. */
    & + * {
        margin-left: auto;
    }
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
//   │ 72px │  [▲ cnt ▼]  [💬 N]       [⊘] [↗]  [⇱ expand]
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

/* No-media placeholder lives in `./components/PostPlaceholderAvatar` — a
 * DiceBear identicon seeded by the author's `mirage1…` bech32 address on a
 * neutral grey tile. Kept as its own component so other surfaces can reuse
 * the same "empty post" visual without duplicating the bg/size logic. */

/* Header row mirrors CardView's HeaderMeta exactly so the two view modes
 * share a single metadata style. Font sizes + weights are copied 1:1.
 *
 * We wrap the header meta in a flex row that also hosts the 3-dot
 * overflow menu on the right, so the menu sits in the top-right corner
 * of every compact card (matches the user's request to move it out of
 * the footer). `min-width: 0` keeps the meta column shrinkable. */
const CompactTopRow = styled.div`
    grid-column: 2 / 3;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.5rem;
    min-width: 0;
`;

const CompactHeader = styled.div`
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.2rem 0.3rem;
    min-width: 0;
    flex: 1 1 auto;
    font-size: 0.62rem;
    font-weight: 400;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    line-height: 1.2;
`;

/* Right side of the top row: hosts the 3-dot overflow menu. Flex-shrink 0
 * keeps the button intact even when the header meta line wraps. */
const CompactTopActions = styled.div`
    display: flex;
    align-items: center;
    gap: 0.25rem;
    flex-shrink: 0;
    margin-top: -2px; /* align ellipsis with the first line of header text */
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
    }
`;

/* Footer row: vote pill + plain-text comment / share buttons + expand chip. */
const CompactFooter = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.1rem;
`;

/* Plain-text action button used for the "N comments" and "Share" labels
 * on larger screens. Matches the 32px height of the vote pill + expand
 * chip so the hover tile lines up visually with the sibling filled
 * chips. Hidden on mobile (where the bottom nav appears) — the icon
 * pill takes over there. */
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

    @media (max-width: 600px) {
        display: none;
    }
`;

const CompactShareNote = styled.span`
    font-size: 0.62rem;
    font-weight: 500;
    color: #22c55e;
    margin-left: 0.25rem;

    @media (max-width: 600px) {
        display: none;
    }
`;

/* Comment-count pill. Mirrors CardView's `ActionPill` exactly so the two
 * view modes share a single visual language for the "N comments" chip:
 * filled `actionIconBg` surface, 32px tall, icon + label, 0.62rem label.
 * Only shown on mobile (where the bottom nav appears) — larger screens
 * use the original `CompactTextAction` text label instead. */
const CompactActionPill = styled.button`
    appearance: none;
    display: none;
    align-items: center;
    gap: 0.3rem;
    height: 32px;
    padding: 0 12px;
    border-radius: 9999px;
    border: none;
    background: ${({ theme }) => theme.colors.actionIconBg};
    color: ${({ theme }) => theme.colors.text};
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

    @media (max-width: 600px) {
        display: inline-flex;
    }
`;

/* Expand / collapse chip — same filled surface as the vote pill so the
 * two controls visually balance the footer row. `line-height: 0` +
 * `display: block` on the svg forces optical centering inside the 32px
 * pill (without it the chevron sat a couple pixels above center). */
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
    line-height: 0;
    transition: background 0.12s ease;

    &:hover { background: ${({ theme }) => theme.colors.actionIconHoverBg}; }

    svg {
        display: block;
        width: 16px;
        height: 16px;
    }
`;

const CompactSpacer = styled.div`
    flex: 1 1 auto;
    min-width: 0;
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
    color: ${({ theme }) => theme.colors.cardBodyText};
    font-family: ${({ theme }) => theme.layout.contentFontFamily || 'inherit'};
    font-size: 0.7rem;
    line-height: 1.45;
    word-break: break-word;
    overflow-wrap: anywhere;

    p { margin: 0 0 0.4rem; }
    p:last-child { margin-bottom: 0; }

    a { color: ${({ theme }) => theme.colors.link}; }

    @media (max-width: 1000px) {
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

/* Short numeric label for action-pill counts (e.g. "1.2K"). Mirrors the
 * helper of the same name in CardView so compact + card rows render
 * comment counts identically. */
function formatCompact(num) {
    const n = Number(num) || 0;
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return String(n);
}

/* Icons mirrored from CardView so the compact footer reads with the same
 * visual language as the card footer. Kept inline (rather than exported
 * from CardView) to keep this view self-contained. */
const CommentIcon = (p) => (
    <svg viewBox="0 0 24 24" aria-hidden="true" width="18" height="18" {...p}>
        <path d="M4 4h16v12H5.17L4 17.17V4zm0-2a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H4z" fill="currentColor" />
    </svg>
);

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
    if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent(VIEW_MODE_CHANGE_EVENT, {
            detail: { viewMode: next }
        }));
    }
}

export function FeedSortToggle({ sortMode, onChange, className }) {
    const [open, setOpen] = useState(false);
    const anchorRef = useRef(null);
    useOutsideClick(anchorRef, () => setOpen(false), open);

    const currentSortLabel = SORT_LABELS[sortMode] || SORT_LABELS.best;
    const handleChange = useCallback((next) => {
        if (typeof onChange === 'function') onChange(next);
        setOpen(false);
    }, [onChange]);

    return (
        <PopoverRoot ref={anchorRef} className={className}>
            <CtrlButton
                type="button"
                aria-haspopup="menu"
                aria-expanded={open}
                onClick={() => setOpen((v) => !v)}
            >
                <span>{currentSortLabel}</span>
                <ChevronWrap $expanded={open}>
                    <HiChevronDown />
                </ChevronWrap>
            </CtrlButton>
            {open && (
                <Menu role="menu" aria-label="Sort posts">
                    <MenuHeader>Sort by</MenuHeader>
                    {['best', 'new'].map((key) => (
                        <MenuItem
                            key={key}
                            type="button"
                            role="menuitemradio"
                            aria-checked={sortMode === key}
                            $active={sortMode === key}
                            onClick={() => handleChange(key)}
                        >
                            <span>{SORT_LABELS[key]}</span>
                        </MenuItem>
                    ))}
                </Menu>
            )}
        </PopoverRoot>
    );
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
                <PostPlaceholderAvatar
                    address={authorAddress}
                    username={post.username}
                />
            )}

            <CompactTopRow>
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
                {/* 3-dot overflow — same dropdown as CardView's MoreButton. */}
                <CompactTopActions>
                    <MoreMenuChip post={post} state={state} updatePost={updatePost} align="right" />
                </CompactTopActions>
            </CompactTopRow>

            <CompactTitle to={linkTarget} onClick={stop}>
                {post.title}
            </CompactTitle>

            <CompactFooter onClick={stop}>
                <VoteSection state={state} post={post} updatePost={updatePost} inline />
                {/* Larger-screen (no bottom nav) buttons — original text
                 * labels for "N comments" and "Share". Hidden when the
                 * mobile bottom nav appears (≤ 600px). */}
                <CompactTextAction as={Link} to={linkTarget}>
                    {commentCount} comment{commentCount !== 1 ? 's' : ''}
                </CompactTextAction>
                <CompactTextAction type="button" onClick={handleShare}>
                    Share
                </CompactTextAction>
                {shareCopied && <CompactShareNote>link copied</CompactShareNote>}
                {/* Mobile (bottom nav visible) — icon-based comment pill
                 * that mirrors CardView's ActionPill. Share is intentionally
                 * omitted on mobile to keep the compact footer uncluttered. */}
                <CompactActionPill as={Link} to={linkTarget}>
                    <CommentIcon />
                    {formatCompact(commentCount)}
                </CompactActionPill>
                <CompactSpacer />
                {/* Block/report chip — identical to CardView's action-row block chip. */}
                <BlockChip post={post} state={state} updatePost={updatePost} align="right" />
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
    feedTitle = null,
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

    /* Keep this feed's internal viewMode in sync when another component
     * (e.g. the top Home/Following toolbar) changes the view mode. */
    useEffect(() => {
        if (typeof window === 'undefined') return undefined;
        const sync = (e) => {
            const next = e?.detail?.viewMode;
            if (VIEW_MODES.includes(next)) {
                setViewMode(next);
            } else {
                setViewMode(loadViewMode());
            }
        };
        window.addEventListener(VIEW_MODE_CHANGE_EVENT, sync);
        return () => window.removeEventListener(VIEW_MODE_CHANGE_EVENT, sync);
    }, []);

    const changeView = useCallback((next) => {
        if (!VIEW_MODES.includes(next)) return;
        setViewMode(next);
        saveViewMode(next);
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

    const hasToolbar = showSortTabs || !!feedTitle;
    if (rows.length === 0 && !hasToolbar) return null;

    const currentSortLabel = SORT_LABELS[sortMode] || SORT_LABELS.best;
    const ViewIcon = viewMode === 'compact' ? IconCompact : IconCard;

    return (
        <FeedList $viewMode={viewMode}>
            {hasToolbar && (
                <Toolbar aria-label="Feed header">
                    {feedTitle && <ToolbarTitle>{feedTitle}</ToolbarTitle>}
                    {showSortTabs && (
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
                    )}

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
