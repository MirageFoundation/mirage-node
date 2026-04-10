import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import styled, { css, keyframes, useTheme } from "styled-components";
import { Link } from "react-router-dom";
import { HiChevronDown } from "react-icons/hi2";

import CardView from "./components/CardView";
import { getThemeFamily } from "../../registry/theme";
import { buildPhotonUrl, isLikelyImageUrl } from "../../utils/media";
import { getAuthorColor } from "../../utils/tierColors";
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

const VIEW_MODE_KEY = 'mirageapp_feed_view_mode';
const VIEW_MODE_DEFAULT = 'card';
const VIEW_MODES = ['card', 'compact'];

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

const FeedList = styled.div`
    display: flex;
    flex-direction: column;
    width: 100%;
    max-width: 720px;
    margin: 0;
    background: ${({ theme }) => theme.colors.bg};
`;

const RowSlot = styled.div`
    position: relative;
    opacity: 1;
    animation: ${slideIn} 0.25s ease-out;

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
    min-width: 200px;
    /* No horizontal padding so MenuItem's active/hover background extends
       edge-to-edge inside the popover. Header still gets inline padding. */
    padding: 6px 0;
    background: ${({ theme }) => theme.colors.menuBg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    z-index: 40;
    display: flex;
    flex-direction: column;
    gap: 2px;
    overflow: hidden;
`;

const MenuHeader = styled.div`
    padding: 4px 12px 6px;
    font-size: 0.66rem;
    font-weight: 400;
    color: ${({ theme }) => theme.colors.menuHeaderText};
`;

const MenuItem = styled.button`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    width: 100%;
    padding: 8px 12px;
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

    &:hover {
        background: ${({ theme, $active }) =>
        $active ? theme.colors.menuSelectedBg : theme.colors.feedCtrlHoverBg};
        color: ${({ theme, $active }) =>
        $active ? theme.colors.sidebarItemActiveText : theme.colors.sidebarItemText};
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

const CompactRoot = styled.article`
    display: grid;
    grid-template-columns: auto 56px minmax(0, 1fr);
    align-items: center;
    gap: 0.6rem;
    padding: 0.5rem 0.75rem 0.5rem 0.5rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.bg};
    position: relative;
    contain: layout style;

    ${({ $flash }) =>
        $flash &&
        css`
            animation: miragePostFlash 1.1s ease-out forwards;
        `}

    @keyframes miragePostFlash {
        0%   { background: rgba(102, 126, 234, 0.12); }
        100% { background: transparent; }
    }

    &:hover {
        background: ${({ theme }) => theme.colors.panelAlt};
    }

    @media (max-width: 600px) {
        grid-template-columns: auto 46px minmax(0, 1fr);
        padding: 0.45rem 0.5rem;
        gap: 0.45rem;
    }
`;

const CompactVote = styled.div`
    display: flex;
    align-items: center;
    justify-content: center;
    align-self: center;
`;

const CompactThumb = styled(Link)`
    display: flex;
    align-items: center;
    justify-content: center;
    width: 56px;
    height: 56px;
    background: ${({ theme }) => theme.colors.panelAlt};
    border-radius: 8px;
    overflow: hidden;
    text-decoration: none;
    flex-shrink: 0;

    img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    @media (max-width: 600px) {
        width: 46px;
        height: 46px;
        border-radius: 6px;
    }
`;

const CompactThumbPlaceholder = styled.div`
    display: flex;
    align-items: center;
    justify-content: center;
    width: 56px;
    height: 56px;
    background: ${({ theme }) => theme.colors.panelAlt};
    border-radius: 8px;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.75rem;
    font-weight: 700;
    flex-shrink: 0;

    @media (max-width: 600px) {
        width: 46px;
        height: 46px;
        border-radius: 6px;
    }
`;

const CompactContent = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    min-width: 0;
`;

const CompactTitle = styled(Link)`
    font-size: 0.82rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;

    &:hover { color: ${({ theme }) => theme.colors.link}; }

    @media (max-width: 600px) {
        font-size: 0.78rem;
        -webkit-line-clamp: 2;
    }
`;

const CompactMeta = styled.div`
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.62rem;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.3;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const CompactMetaLink = styled(Link)`
    color: ${({ theme }) => theme.colors.subtleText};
    text-decoration: none;
    font-weight: 600;

    &:hover { color: ${({ theme }) => theme.colors.text}; }
`;

const CompactMetaSep = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    opacity: 0.6;
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

function getThumbUrl(post) {
    const thumb = post?.thumbnail;
    if (typeof thumb === 'string' && thumb.trim() && isLikelyImageUrl(thumb)) {
        try { return buildPhotonUrl(thumb, { w: 112, h: 112 }); }
        catch (_) { /* noop */ }
    }
    if (Array.isArray(post?.media) && post.media.length > 0) {
        const first = post.media[0];
        if (typeof first === 'string' && isLikelyImageUrl(first)) {
            try { return buildPhotonUrl(first, { w: 112, h: 112 }); }
            catch (_) { /* noop */ }
        }
    }
    return null;
}

function loadViewMode() {
    try {
        const raw = Storage.load(VIEW_MODE_KEY, VIEW_MODE_DEFAULT);
        return VIEW_MODES.includes(raw) ? raw : VIEW_MODE_DEFAULT;
    } catch (_) {
        return VIEW_MODE_DEFAULT;
    }
}

// ─── Compact row component ─────────────────────────────────────────────────

function CompactRow({ post, state, updatePost }) {
    const theme = useTheme();
    const VoteSection = useMemo(
        () => getThemeFamily(theme.themeId).VoteSection,
        [theme.themeId]
    );

    if (!post || !post.post_id) return null;
    if (typeof post.title !== 'string' || post.title.trim() === '') return null;
    if (typeof post.topic !== 'string' || post.topic.trim() === '') return null;
    if (post.deleted || post.hidden_client) return null;

    const postId = String(post.post_id);
    const linkTarget = `/p/${postId}`;
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
    const thumbUrl = getThumbUrl(post);
    const placeholderChar = (topic.trim()[0] || '#').toUpperCase();

    return (
        <CompactRoot $flash={!!post.flash}>
            <CompactVote>
                <VoteSection state={state} post={post} updatePost={updatePost} />
            </CompactVote>

            {thumbUrl ? (
                <CompactThumb to={linkTarget} aria-label={post.title}>
                    <img src={thumbUrl} alt="" loading="lazy" />
                </CompactThumb>
            ) : (
                <CompactThumbPlaceholder aria-hidden="true">{placeholderChar}</CompactThumbPlaceholder>
            )}

            <CompactContent>
                <CompactTitle to={linkTarget}>{post.title}</CompactTitle>
                <CompactMeta>
                    <CompactMetaLink to={`/t/${encodeURIComponent(topic)}`}>#{topic}</CompactMetaLink>
                    <CompactMetaSep>·</CompactMetaSep>
                    <CompactMetaLink
                        to={`/u/${encodeURIComponent(post.username || authorAddress)}`}
                        style={authorColor ? { color: authorColor } : undefined}
                    >
                        @{displayAuthor}
                    </CompactMetaLink>
                    <CompactMetaSep>·</CompactMetaSep>
                    <span>{formatAge(ts)}</span>
                    <CompactMetaSep>·</CompactMetaSep>
                    <CompactMetaLink to={linkTarget}>
                        {commentCount} comment{commentCount !== 1 ? 's' : ''}
                    </CompactMetaLink>
                </CompactMeta>
            </CompactContent>
        </CompactRoot>
    );
}

const MemoCompactRow = memo(CompactRow, (prev, next) => {
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
        <FeedList>
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
