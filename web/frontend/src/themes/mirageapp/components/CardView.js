import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import styled, { useTheme, css } from "styled-components";
import { Link, useNavigate } from "react-router-dom";

import { getThemeFamily } from "../../../registry/theme";
import { getAuthorColor, getAuthorTooltip } from "../../../utils/tierColors";
import { normalizeTag } from "../../../utils/ContentTags";
import { isLikelyImageUrl, isLikelyVideoUrl } from "../../../utils/media";
import * as tx from "../../../utils/tx";
import { follow, unfollow, isFollowing } from "../../../utils/FollowUsers";
import Storage from "../../../utils/Storage";

import InlineMedia from "./InlineMedia";
import MarkdownRenderer from "./MarkdownRenderer";

/**
 * CardView — Mirage-app inspired post card.
 *
 * Visual language ported from `mirage-mobile-app/src/components/molecules/post-card.tsx`:
 *   · Subtle bottom border between posts (no card shadow).
 *   · Header:   #topic · time · @username            [ follow button ]
 *   · Title (bold) + markdown body (truncated to 700 chars in feed).
 *   · Media block (InlineMedia handles image / video / redgifs / gallery).
 *   · Action row: [▲ count ▼] pill · comment pill · ⇢ share · ⋯ more menu.
 *
 * Props shape MUST stay compatible with other themes' CardView so shared
 * hooks (useMain / useProfile / useViewPost) can pass it around unchanged.
 */

// ─── Layout primitives ─────────────────────────────────────────────────────

const Card = styled.article`
    background: ${({ theme }) => theme.colors.bg};
    border: none;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    padding: 0.85rem 1rem 0.7rem;
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
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

    @media (max-width: 600px) {
        padding: 0.7rem 0.85rem 0.55rem;
        gap: 0.45rem;
    }
`;

const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    min-width: 0;
`;

const HeaderMeta = styled.div`
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.25rem 0.35rem;
    min-width: 0;
    font-size: 0.68rem;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.2;
`;

const TopicLink = styled(Link)`
    font-weight: 700;
    font-size: 0.75rem;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    &:hover { text-decoration: underline; }
`;

const HeaderDot = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.65rem;
    line-height: 1;
    opacity: 0.8;
`;

const TimeText = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.65rem;
`;

const UserLink = styled(Link)`
    color: ${({ theme }) => theme.colors.subtleText};
    font-weight: 500;
    font-size: 0.68rem;
    text-decoration: none;
    &:hover { text-decoration: underline; }
`;

const FollowButton = styled.button`
    appearance: none;
    height: 22px;
    padding: 0 11px;
    border-radius: 9999px;
    font-size: 0.62rem;
    font-weight: 700;
    font-family: inherit;
    cursor: pointer;
    border: 1px solid ${({ $active, theme }) =>
        $active ? theme.colors.border : theme.colors.focusBlue};
    background: ${({ $active, theme }) =>
        $active ? 'transparent' : theme.colors.focusBlue};
    color: ${({ $active, theme }) =>
        $active ? theme.colors.text : '#FFFFFF'};
    transition: background 0.12s ease, color 0.12s ease, transform 0.12s ease;

    &:hover:not(:disabled) { opacity: 0.9; }
    &:active:not(:disabled) { transform: scale(0.96); }
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

    &:hover { background: ${({ theme }) => theme.colors.hoverBg}; }
    &:active { transform: scale(0.92); }

    svg { width: 16px; height: 16px; fill: currentColor; }
`;

const HeaderActions = styled.div`
    display: flex;
    align-items: center;
    gap: 0.35rem;
    flex-shrink: 0;
`;

// ─── Body ──────────────────────────────────────────────────────────────────

const TitleLink = styled(Link)`
    display: block;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.95rem;
    font-weight: 700;
    line-height: 1.3;
    text-decoration: none;
    word-break: break-word;
    overflow-wrap: anywhere;
    &:hover { text-decoration: none; color: ${({ theme }) => theme.colors.text}; }
    &:visited { color: ${({ theme }) => theme.colors.text}; }

    @media (max-width: 600px) {
        font-size: 0.85rem;
    }
`;

const TagBadge = styled.span`
    display: inline-block;
    font-size: 0.55rem;
    font-weight: 800;
    color: ${({ theme }) => theme.colors.subtleText};
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-right: 0.35rem;
    padding: 0.12rem 0.35rem;
    border-radius: 4px;
    background: ${({ theme }) => theme.colors.hoverBg};
    vertical-align: middle;
`;

const Body = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.78rem;
    line-height: 1.5;
    word-break: break-word;
    overflow-wrap: anywhere;

    p { margin: 0 0 0.5rem; }
    p:last-child { margin-bottom: 0; }

    a { color: ${({ theme }) => theme.colors.link}; }
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
    gap: 0.55rem;
    margin-top: 0.25rem;
`;

const ActionPill = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    height: 28px;
    padding: 0 11px;
    border-radius: 9999px;
    border: 0.5px solid ${({ theme }) => theme.colors.border};
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    font: inherit;
    font-weight: 700;
    font-size: 0.68rem;
    line-height: 1;
    cursor: pointer;
    text-decoration: none;
    transition: background 0.12s ease, transform 0.12s ease;

    &:hover { background: ${({ theme }) => theme.colors.hoverBg}; }
    &:active { transform: scale(0.96); }

    svg {
        width: 14px;
        height: 14px;
        fill: currentColor;
    }
`;

const Spacer = styled.div`
    flex: 1 1 auto;
    min-width: 0;
`;

// ─── More menu dropdown ────────────────────────────────────────────────────

const MenuRoot = styled.div`
    position: absolute;
    right: 1rem;
    top: 2.4rem;
    min-width: 200px;
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.25);
    padding: 0.35rem 0;
    z-index: 20;
`;

const MenuItem = styled.button`
    display: flex;
    width: 100%;
    align-items: center;
    gap: 0.5rem;
    padding: 0.4rem 0.75rem;
    background: transparent;
    border: none;
    color: ${({ $danger, theme }) => ($danger ? theme.colors.voteDown : theme.colors.text)};
    font: inherit;
    font-size: 0.7rem;
    font-weight: 500;
    text-align: left;
    cursor: pointer;

    &:hover { background: ${({ theme }) => theme.colors.hoverBg}; }

    svg { width: 13px; height: 13px; fill: currentColor; }
`;

// ─── Icons ─────────────────────────────────────────────────────────────────

const CommentIcon = (p) => (
    <svg viewBox="0 0 24 24" aria-hidden {...p}>
        <path d="M21 6H3a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3v3l4-3h11a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1z" />
    </svg>
);

const ShareIcon = (p) => (
    <svg viewBox="0 0 24 24" aria-hidden {...p}>
        <path d="M14 4v4H8a4 4 0 0 0-4 4v4h2v-4a2 2 0 0 1 2-2h6v4l6-5-6-5z" />
    </svg>
);

const EllipsisIcon = (p) => (
    <svg viewBox="0 0 24 24" aria-hidden {...p}>
        <circle cx="5" cy="12" r="1.8" />
        <circle cx="12" cy="12" r="1.8" />
        <circle cx="19" cy="12" r="1.8" />
    </svg>
);

const BlockIcon = (p) => (
    <svg viewBox="0 0 24 24" aria-hidden {...p}>
        <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 0 1-6.3-12.9L16.9 18.3A7.96 7.96 0 0 1 12 20zm6.3-3.1L7.1 5.7A8 8 0 0 1 18.3 16.9z" />
    </svg>
);

const LinkIcon = (p) => (
    <svg viewBox="0 0 24 24" aria-hidden {...p}>
        <path d="M10.6 13.4a3 3 0 0 0 4.2 0l3.5-3.5a3 3 0 0 0-4.2-4.2l-1.3 1.3 1.4 1.4 1.3-1.3a1 1 0 0 1 1.4 1.4l-3.5 3.5a1 1 0 0 1-1.4 0l-1.4 1.4zm2.8-2.8a3 3 0 0 0-4.2 0L5.7 14.1a3 3 0 0 0 4.2 4.2l1.3-1.3-1.4-1.4-1.3 1.3a1 1 0 0 1-1.4-1.4l3.5-3.5a1 1 0 0 1 1.4 0l1.4-1.4z" />
    </svg>
);

const FlagIcon = (p) => (
    <svg viewBox="0 0 24 24" aria-hidden {...p}>
        <path d="M6 3h2v18H6zM9 4h11l-2 4 2 4H9z" />
    </svg>
);

const TrashIcon = (p) => (
    <svg viewBox="0 0 24 24" aria-hidden {...p}>
        <path d="M9 3h6l1 2h4v2H4V5h4zm-3 6h12l-1 11H7zM10 11v7h1v-7zm3 0v7h1v-7z" />
    </svg>
);

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

// ─── Component ─────────────────────────────────────────────────────────────

function CardView({ state, post, updatePost, showContent = false, footer = null }) {
    const navigate = useNavigate();
    const theme = useTheme();
    const VoteSection = useMemo(
        () => getThemeFamily(theme.themeId).VoteSection,
        [theme.themeId]
    );

    const [menuOpen, setMenuOpen] = useState(false);
    const [shareCopied, setShareCopied] = useState(false);
    const [blurOverride, setBlurOverride] = useState(false);
    const [followOverride, setFollowOverride] = useState(null);
    const menuRef = useRef(null);

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

    // Close menu on outside click
    useEffect(() => {
        if (!menuOpen) return undefined;
        const handler = (e) => {
            if (menuRef.current && !menuRef.current.contains(e.target)) {
                setMenuOpen(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [menuOpen]);

    // Clear flash flag after animation
    useEffect(() => {
        if (!post || !post.post_id || !post.flash || !updatePost) return undefined;
        const t = setTimeout(() => {
            try { updatePost(post.post_id, { flash: false }); } catch (_) { /* noop */ }
        }, 1250);
        return () => clearTimeout(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [post && post.post_id]);

    // Derive safe values — these must be computed BEFORE any early return
    // so the hooks below are called in a stable order on every render.
    // Use a stable reference when `post` is missing so downstream useMemo
    // dependencies don't re-run on every render.
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

    const userFollowing = (() => {
        if (followOverride !== null) return followOverride;
        if (!isLoggedIn || !authorAddress) return false;
        try { return isFollowing(viewerAddress, authorAddress); }
        catch (_) { return false; }
    })();

    const { mediaUrl, body } = useMemo(() => resolveDisplayContent(safePost), [safePost]);
    const hasMedia = !!mediaUrl;

    const hasTag = !!(safePost.tag && String(safePost.tag).trim());
    const shouldBlurMedia = hasMedia && blurSensitive && hasTag && !blurOverride;

    const displayBody = useMemo(() => {
        if (!body) return '';
        if (showContent) return body;
        if (body.length <= MAX_BODY_LENGTH) return body;
        return body.slice(0, MAX_BODY_LENGTH).trimEnd() + '…';
    }, [body, showContent]);

    const commentCount = Number(safePost.comments) || 0;

    // ─── Handlers ──────────────────────────────────────────────────────────

    const handleCopyLink = useCallback(() => {
        const url = `${window.location.origin}${linkTarget}`;
        try {
            navigator.clipboard.writeText(url);
            setShareCopied(true);
            setTimeout(() => setShareCopied(false), 1500);
        } catch (_) { /* noop */ }
    }, [linkTarget]);

    const handleFollowUser = useCallback(async () => {
        if (!isLoggedIn || !authorAddress) return;
        const next = !userFollowing;
        setFollowOverride(next);
        try {
            if (next) await follow(viewerAddress, authorAddress);
            else await unfollow(viewerAddress, authorAddress);
        } catch (_) {
            setFollowOverride(!next);
        }
    }, [isLoggedIn, authorAddress, userFollowing, viewerAddress]);

    const handleBlockUser = useCallback(async () => {
        setMenuOpen(false);
        if (!isLoggedIn || !authorAddress) return;
        try { await tx.blockUser(authorAddress, true); } catch (_) { /* noop */ }
    }, [isLoggedIn, authorAddress]);

    const handleBlockPost = useCallback(async () => {
        setMenuOpen(false);
        if (!isLoggedIn) return;
        try { await tx.blockPost(postId, true); } catch (_) { /* noop */ }
        if (typeof updatePost === 'function') {
            try { updatePost(postId, { hidden_client: true }); } catch (_) { /* noop */ }
        }
    }, [isLoggedIn, postId, updatePost]);

    const handleBlockTopic = useCallback(async () => {
        setMenuOpen(false);
        if (!isLoggedIn) return;
        try { await tx.blockTopic(topic); } catch (_) { /* noop */ }
    }, [isLoggedIn, topic]);

    const handleReport = useCallback(async () => {
        setMenuOpen(false);
        if (!isLoggedIn) return;
        const reason = typeof window !== 'undefined'
            ? window.prompt('Report reason (optional)') || ''
            : '';
        try { await tx.reportPost(postId, reason); } catch (_) { /* noop */ }
    }, [isLoggedIn, postId]);

    const handleEdit = useCallback(() => {
        setMenuOpen(false);
        navigate(`/edit_post/${postId}`);
    }, [navigate, postId]);

    const handleDelete = useCallback(async () => {
        setMenuOpen(false);
        if (!isLoggedIn) return;
        try { await tx.deletePost(postId); } catch (_) { /* noop */ }
        if (typeof updatePost === 'function') {
            try { updatePost(postId, { deleted: true }); } catch (_) { /* noop */ }
        }
    }, [isLoggedIn, postId, updatePost]);

    const handleRevealMedia = useCallback(() => {
        setBlurOverride(true);
    }, []);

    // ─── Guards (after all hooks) ──────────────────────────────────────────
    if (!post || post.deleted || post.blocked) return null;
    if (typeof post.title !== 'string' || post.title.trim() === '') return null;
    if (typeof post.topic !== 'string' || post.topic.trim() === '') return null;

    // ─── Render ────────────────────────────────────────────────────────────

    return (
        <Card $flash={!!post.flash}>
            <HeaderRow>
                <HeaderMeta>
                    <TopicLink to={`/t/${encodeURIComponent(topic)}`}>#{topic}</TopicLink>
                    <HeaderDot>·</HeaderDot>
                    <TimeText title={new Date(ts * 1000).toLocaleString()}>{formatAge(ts)}</TimeText>
                    <HeaderDot>·</HeaderDot>
                    <UserLink
                        to={`/u/${encodeURIComponent(post.username || authorAddress)}`}
                        style={authorColor ? { color: authorColor } : undefined}
                        title={authorTooltip || undefined}
                    >
                        @{authorDisplay}
                    </UserLink>
                </HeaderMeta>
                <HeaderActions>
                    {!isOwnPost && isLoggedIn && authorAddress && (
                        <FollowButton
                            $active={userFollowing}
                            onClick={handleFollowUser}
                        >
                            {userFollowing ? 'Following' : 'Follow'}
                        </FollowButton>
                    )}
                    <MoreButton
                        type="button"
                        aria-label="More options"
                        onClick={(e) => {
                            e.stopPropagation();
                            setMenuOpen((v) => !v);
                        }}
                    >
                        <EllipsisIcon />
                    </MoreButton>
                </HeaderActions>
                {menuOpen && (
                    <MenuRoot ref={menuRef}>
                        <MenuItem onClick={handleCopyLink}>
                            <LinkIcon />
                            {shareCopied ? 'Copied!' : 'Copy link'}
                        </MenuItem>
                        {!isOwnPost && isLoggedIn && (
                            <>
                                <MenuItem $danger onClick={handleBlockUser}>
                                    <BlockIcon />
                                    Block @{authorDisplay}
                                </MenuItem>
                                <MenuItem $danger onClick={handleBlockPost}>
                                    <BlockIcon />
                                    Hide this post
                                </MenuItem>
                                <MenuItem $danger onClick={handleBlockTopic}>
                                    <BlockIcon />
                                    Block #{topic}
                                </MenuItem>
                                <MenuItem $danger onClick={handleReport}>
                                    <FlagIcon />
                                    Report post
                                </MenuItem>
                            </>
                        )}
                        {isOwnPost && (
                            <>
                                <MenuItem onClick={handleEdit}>
                                    <LinkIcon />
                                    Edit post
                                </MenuItem>
                                <MenuItem $danger onClick={handleDelete}>
                                    <TrashIcon />
                                    Delete post
                                </MenuItem>
                            </>
                        )}
                    </MenuRoot>
                )}
            </HeaderRow>

            <TitleLink to={linkTarget}>
                {hasTag && <TagBadge>{normalizeTag(String(post.tag).trim())}</TagBadge>}
                {post.title}
            </TitleLink>

            {hasMedia && (
                <MediaWrap $blur={shouldBlurMedia} onClick={shouldBlurMedia ? handleRevealMedia : undefined}>
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

            <ActionRow>
                <VoteSection state={state} post={post} updatePost={updatePost} inline />
                <ActionPill as={Link} to={linkTarget}>
                    <CommentIcon />
                    {formatCompact(commentCount)}
                </ActionPill>
                <Spacer />
                <ActionPill type="button" onClick={handleCopyLink} title="Copy link">
                    <ShareIcon />
                </ActionPill>
            </ActionRow>

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
