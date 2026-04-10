import React, { memo, useCallback, useMemo, useState, useEffect } from 'react';
import styled, { css } from 'styled-components';
import { Link } from 'react-router-dom';
import VoteSection from './components/VoteSection';
import InlineMedia from './components/InlineMedia';
import MarkdownRenderer from './components/MarkdownRenderer';
import { buildPhotonUrl, isLikelyImageUrl, isLikelyVideoUrl } from '../../utils/media';
import { getAuthorColor } from '../../utils/tierColors';
import Storage from '../../utils/Storage';
import { normalizeTag } from '../../utils/ContentTags';
import { OLDREDDIT_SHELL_INSET_X, OldRedditTab } from './Layout';

/** Home/following: negate shell padding. Profile posts tabs: parent has no horizontal padding — do not bleed or borders stay inset.
 *  Uses display:block (not flex) so float:right sidebar works correctly. */
const ListContainer = styled.div`
    display: block;
    overflow: hidden;
    background: ${({ theme }) => theme.colors.panel};
    max-width: none;
    box-sizing: border-box;
    ${({ $bleedShell }) =>
        $bleedShell
            ? css`
                  margin-left: calc(-1 * ${OLDREDDIT_SHELL_INSET_X});
                  margin-right: calc(-1 * ${OLDREDDIT_SHELL_INSET_X});
                  width: calc(100% + 2 * ${OLDREDDIT_SHELL_INSET_X});
              `
            : css`
                  width: 100%;
                  margin-left: 0;
                  margin-right: 0;
              `}
`;

const Row = styled.div`
    display: flex;
    align-items: center;
    padding: 0.4rem ${OLDREDDIT_SHELL_INSET_X};
    position: relative;
    gap: 0.4rem;
    min-height: 52px;

    &::after {
        content: '';
        position: absolute;
        left: 0;
        right: -400px;
        bottom: 0;
        height: 1px;
        background: ${({ theme }) => theme.colors.border};
        pointer-events: none;
    }

    &:last-child::after {
        display: none;
    }

    &:hover {
        background: ${({ theme }) => theme.colors.panelAlt};
    }

    @media (max-width: 600px) {
        display: grid;
        grid-template-columns: auto auto 1fr;
        grid-template-rows: auto auto auto;
        align-items: start;
        gap: 0.25rem;
        column-gap: 0.35rem;
        padding: 0.5rem;
        min-height: 0;
    }
`;

const Rank = styled.span`
    flex: 0 0 auto;
    min-width: 1rem;
    text-align: left;
    font-variant-numeric: tabular-nums;
    font-size: 0.75rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
    padding-top: 0.25rem;

    @media (max-width: 600px) {
        display: none;
    }
`;

const VoteColumn = styled.div`
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 2.5rem;
    align-self: flex-start;

    @media (max-width: 600px) {
        grid-row: 1 / 4;
        grid-column: 1;
        min-width: 1.8rem;
    }
`;

const Thumbnail = styled(Link)`
    flex: 0 0 70px;
    width: 70px;
    height: 70px;
    overflow: hidden;
    background: ${({ theme }) => theme.colors.panelAlt};
    display: flex;
    align-items: center;
    justify-content: center;

    img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    @media (max-width: 600px) {
        flex: 0 0 50px;
        width: 50px;
        height: 50px;
        grid-row: 1;
        grid-column: 2;
    }
`;

const ContentColumn = styled.div`
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;

    @media (max-width: 600px) {
        grid-row: 1;
        grid-column: 3;
    }
`;

const MobileMetaWrap = styled.div`
    display: none;

    @media (max-width: 600px) {
        display: flex;
        flex-direction: column;
        gap: 0.15rem;
        grid-row: 2 / 4;
        grid-column: 2 / 4;
    }
`;

const DesktopMeta = styled.div`
    display: contents;

    @media (max-width: 600px) {
        display: none;
    }
`;

const Title = styled(Link)`
    font-size: 0.8rem;
    font-weight: 400;
    color: ${({ theme }) => theme.colors.link};
    text-decoration: none;
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;

    &:visited {
        color: ${({ theme }) => theme.colors.subtleText};
    }

    &:hover {
        text-decoration: underline;
    }

    @media (max-width: 600px) {
        font-size: 0.85rem;
        -webkit-line-clamp: 3;
    }
`;

const MetaLine = styled.div`
    font-size: 0.65rem;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.35;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;

    @media (max-width: 600px) {
        white-space: normal;
        overflow: visible;
        font-size: 0.6rem;
    }
`;


const SubmittedLabel = styled.span`
    @media (max-width: 600px) {
        display: none;
    }
`;

const MetaLink = styled(Link)`
    color: inherit;
    text-decoration: none;
    &:hover {
        text-decoration: underline;
    }
`;

const AuthorLink = styled(Link)`
    text-decoration: none;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.subtleText};
    &:hover {
        text-decoration: underline;
    }
`;

const TagBadge = styled.span`
    display: inline;
    font-size: 0.6rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.subtleText};
    margin-right: 0.3rem;
    text-transform: uppercase;
    &::before { content: '['; }
    &::after { content: ']'; }
`;

const ActionsLine = styled.div`
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    font-size: 0.65rem;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.35;

    @media (max-width: 600px) {
        gap: 0.5rem;
        font-size: 0.6rem;
    }
`;

const ActionLink = styled(Link)`
    color: inherit;
    text-decoration: none;
    font-weight: 600;
    &:hover {
        text-decoration: underline;
    }
`;

const ActionButton = styled.button`
    color: inherit;
    background: none;
    border: none;
    padding: 0;
    font: inherit;
    cursor: pointer;
    font-weight: 600;
    &:hover {
        text-decoration: underline;
    }
`;

const ExpandedContent = styled.div`
    padding: 0.5rem ${OLDREDDIT_SHELL_INSET_X};
    padding-left: calc(${OLDREDDIT_SHELL_INSET_X} + 3.5rem + 70px + 0.8rem);
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panel};
    font-size: 0.82rem;
    color: ${({ theme }) => theme.colors.text};
    overflow-wrap: anywhere;
    word-break: break-word;
    max-width: 800px;

    img, video {
        max-width: 100%;
        max-height: 600px;
        border-radius: 4px;
    }

    @media (max-width: 600px) {
        padding: 0.4rem 0.5rem;
        font-size: 0.75rem;
        max-width: 100%;
    }
`;

const FeedToolbar = styled.div`
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-start;
    gap: 0.5rem;
    row-gap: 0.35rem;
    padding: 0.4rem ${OLDREDDIT_SHELL_INSET_X};
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panel};

    @media (max-width: 600px) {
        padding: 0.35rem 0.5rem;
    }
`;

const FeedNavGroup = styled.div`
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem;
    min-width: 0;
`;

const FeedNavTab = styled(OldRedditTab)`
    padding: 0.25rem 0.35rem 0.1rem;

    &:first-child {
        padding-left: 2px;
    }
`;

const FeedToolbarSep = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-weight: 600;
    font-size: 0.65rem;
    user-select: none;
`;

const FeedSortSelect = styled.select`
    font-size: 0.65rem;
    padding: 0.2rem 0.4rem 0.1rem;
    border-radius: 0;
    border: none;
    background: transparent;
    color: ${({ theme }) => theme.colors.subtleText};
    outline: none;
    cursor: pointer;
    font-family: inherit;
    font-weight: 600;
    max-width: 100%;

    &:hover {
        color: ${({ theme }) => theme.colors.text};
    }
`;

function formatAge(tsSec) {
    const now = Math.floor(Date.now() / 1000);
    const diff = Math.max(0, now - tsSec);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 2592000) return `${Math.floor(diff / 86400)}d ago`;
    return new Date(tsSec * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function getThumbUrl(post) {
    const thumb = post?.thumbnail;
    if (typeof thumb !== 'string' || thumb.trim().length === 0) return null;
    if (isLikelyImageUrl(thumb)) {
        try { return buildPhotonUrl(thumb, 140, 105); }
        catch (_) { return null; }
    }
    return null;
}

function truncateText(text, max) {
    if (!text) return '';
    if (text.length <= max) return text;
    return text.slice(0, max) + '…';
}

function ListRow({ post, rank, state, updatePost, saved, onToggleSave, onHide, onShare, blurSensitive }) {
    const [expanded, setExpanded] = useState(false);

    const mediaArr = useMemo(() => (post && Array.isArray(post.media) && post.media.length > 0) ? post.media : null, [post]);
    const expandedTextBody = useMemo(() => {
        const raw = String(post?.content || '').trim();
        if (!raw) return null;
        if (mediaArr) return raw || null;
        const idx = raw.indexOf('\n');
        const first = (idx >= 0 ? raw.slice(0, idx) : raw).trim();
        const rest = (idx >= 0 ? raw.slice(idx + 1) : '').replace(/^\n+/, '');
        if (/^https?:\/\//i.test(first)) return rest || null;
        return raw || null;
    }, [post?.content, mediaArr]);

    if (!post || !post.post_id) return null;
    const isComment = !!(post.target && String(post.target).trim());
    if (!isComment && (typeof post.title !== 'string' || typeof post.topic !== 'string')) {
        throw new Error('ListFeedView: post title/topic missing');
    }
    const postId = String(post.post_id);
    const topic = post.topic || '';
    const title = isComment
        ? truncateText(post.content || post.title || '(comment)', 200)
        : (post.title || '');
    const author = post.author || '';
    const username = post.username;
    const linkTarget = isComment ? `/p/${post.target}?depth=1` : `/p/${postId}`;
    let ts = Number(post.timestamp);
    if (!Number.isFinite(ts)) {
        throw new Error('ListFeedView: timestamp missing');
    }
    if (ts > 1e12) ts = Math.floor(ts / 1000);
    const numComments = Number(post.comments) || 0;
    const thumbUrl = isComment ? null : getThumbUrl(post);
    const authorColor = getAuthorColor(post?.author_level, post?.author_is_new);
    const hasTag = !isComment && !!(post.tag && String(post.tag).trim());
    const shouldBlur = blurSensitive && hasTag && !expanded;
    let displayAuthor = '';
    if (typeof username === 'string' && username.trim().length > 0) {
        displayAuthor = username;
    } else if (typeof author === 'string' && author.trim().length > 0) {
        displayAuthor = `${author.slice(0, 10)}...`;
    }

    const firstMediaUrl = mediaArr ? mediaArr[0] : (() => {
        const raw = String(post?.content || '');
        const m = raw.match(/https?:\/\/[^\s<>"']+/);
        return m ? m[0] : null;
    })();
    const hasExpandableMedia = firstMediaUrl && (isLikelyImageUrl(firstMediaUrl) || isLikelyVideoUrl(firstMediaUrl));
    const hasExpandableContent = hasExpandableMedia || !!expandedTextBody;

    const meta = (
        <MetaLine>
            <SubmittedLabel>{isComment ? 'commented' : 'submitted'} </SubmittedLabel>{formatAge(ts)} by{' '}
            <AuthorLink
                to={`/u/${encodeURIComponent(username || author)}`}
                style={authorColor ? { color: authorColor } : undefined}
            >
                {displayAuthor}
            </AuthorLink>
            {!isComment && topic && (
                <>
                    {' '}to{' '}
                    <MetaLink to={`/t/${encodeURIComponent(topic)}`}>t/{topic}</MetaLink>
                </>
            )}
        </MetaLine>
    );

    const actions = (
        <ActionsLine>
            <ActionLink to={linkTarget}>
                {isComment ? 'context' : `${numComments} comment${numComments !== 1 ? 's' : ''}`}
            </ActionLink>
            <ActionButton type="button" onClick={() => onShare(postId)}>
                share
            </ActionButton>
            <ActionButton type="button" onClick={() => onToggleSave(postId)}>
                {saved ? 'unsave' : 'save'}
            </ActionButton>
            <ActionButton type="button" onClick={() => onHide(postId)}>
                hide
            </ActionButton>
            <ActionLink to={linkTarget}>
                report
            </ActionLink>
            {hasExpandableContent && (
                <ActionButton type="button" onClick={() => setExpanded(prev => !prev)}>
                    {expanded ? '[-]' : '[+]'}
                </ActionButton>
            )}
        </ActionsLine>
    );

    return (
        <>
            <Row>
                <Rank>{rank}</Rank>
                <VoteColumn>
                    <VoteSection state={state} post={post} updatePost={updatePost} showToggle={false} />
                </VoteColumn>
                {thumbUrl ? (
                    <Thumbnail to={linkTarget}>
                        <img src={thumbUrl} alt="" loading="lazy" style={shouldBlur ? { filter: 'blur(8px)' } : undefined} />
                    </Thumbnail>
                ) : null}
                <ContentColumn>
                    <Title to={linkTarget}>
                        {hasTag && <TagBadge>{normalizeTag(String(post.tag).trim())}</TagBadge>}
                        {title}
                    </Title>
                    <DesktopMeta>{meta}{actions}</DesktopMeta>
                </ContentColumn>
                <MobileMetaWrap>{meta}{actions}</MobileMetaWrap>
            </Row>
            {expanded && (
                <ExpandedContent>
                    {hasExpandableMedia && (
                        <div style={{ marginBottom: expandedTextBody ? '0.5rem' : 0 }}>
                            <InlineMedia url={firstMediaUrl} variant="root_post" autoPlay mediaMeta={Array.isArray(post.media_meta) ? post.media_meta[0] || null : null} />
                        </div>
                    )}
                    {expandedTextBody && <MarkdownRenderer text={expandedTextBody} />}
                </ExpandedContent>
            )}
        </>
    );
}

const MemoizedRow = memo(ListRow, (prev, next) => {
    const p = prev.post;
    const n = next.post;
    return (
        prev.blurSensitive === next.blurSensitive &&
        (p === n ||
            (p?.post_id === n?.post_id &&
                p?.score === n?.score &&
                p?.direction === n?.direction &&
                p?.comments === n?.comments &&
                prev.rank === next.rank &&
                prev.saved === next.saved))
    );
});

export default function ListFeedView({
    posts,
    state,
    updatePost,
    startRank = 1,
    sortMode,
    onSortChange,
    showSortTabs,
    feedNavTopic,
    bleedShell = true,
    sidebar,
}) {
    const [blurSensitive, setBlurSensitive] = useState(() => {
        const val = Storage.load('blur_sensitive_media', true);
        return val !== false;
    });

    useEffect(() => {
        const handler = (e) => {
            if (e?.detail && typeof e.detail.blurSensitiveMedia !== 'undefined') {
                setBlurSensitive(e.detail.blurSensitiveMedia !== false);
                return;
            }
            const val = Storage.load('blur_sensitive_media', true);
            setBlurSensitive(val !== false);
        };
        window.addEventListener('settingsUpdated', handler);
        return () => window.removeEventListener('settingsUpdated', handler);
    }, []);

    const [savedSet, setSavedSet] = useState(() => {
        const raw = Storage.load('saved_posts', []);
        const list = Array.isArray(raw) ? raw : [];
        return new Set(list.map((x) => {
            if (typeof x !== 'string') return '';
            return x.trim().toLowerCase();
        }).filter(Boolean));
    });

    const onShare = useCallback((postId) => {
        const id = String(postId || '').trim();
        if (!id) return;
        const url = `${window.location.origin}/p/${id}`;
        console.debug('[OldReddit] share.copy', { postId: id, url });
        navigator.clipboard.writeText(url).catch((err) => {
            console.error('[OldReddit] share.copy.failed', err);
        });
    }, []);

    const onToggleSave = useCallback((postId) => {
        if (!postId) return;
        const rawId = String(postId).trim();
        if (!rawId) return;
        const id = rawId.toLowerCase();

        setSavedSet((prev) => {
            const next = new Set(prev);
            if (next.has(id)) {
                next.delete(id);
                console.debug('[OldReddit] save.off', { postId: rawId });
            } else {
                next.add(id);
                console.debug('[OldReddit] save.on', { postId: rawId });
            }
            Storage.save('saved_posts', Array.from(next));
            return next;
        });
    }, []);

    const onHide = useCallback((postId) => {
        const id = String(postId || '').trim();
        if (!id) return;
        if (typeof updatePost === 'function') {
            console.debug('[OldReddit] hide', { postId: id });
            updatePost(id, { hidden_client: true });
        }
    }, [updatePost]);

    if (!posts || posts.length === 0) return null;

    return (
        <ListContainer $bleedShell={bleedShell}>
            {showSortTabs && (
                <FeedToolbar aria-label="Feed navigation and sort">
                    <FeedNavGroup>
                        <FeedNavTab as={Link} to="/home" $active={feedNavTopic === 'home'}>
                            home
                        </FeedNavTab>
                        <FeedNavTab as={Link} to="/following" $active={feedNavTopic === 'following'}>
                            following
                        </FeedNavTab>
                        <FeedToolbarSep aria-hidden="true">|</FeedToolbarSep>
                        <FeedSortSelect
                            value={sortMode}
                            onChange={(e) => onSortChange(e.target.value)}
                            aria-label="Sort posts"
                        >
                            <option value="best">best</option>
                            <option value="new">new</option>
                        </FeedSortSelect>
                    </FeedNavGroup>
                </FeedToolbar>
            )}
            {sidebar}
            {posts.map((post, i) => {
                const saved = post && post.post_id
                    ? savedSet.has(String(post.post_id).trim().toLowerCase())
                    : false;
                return (
                    <MemoizedRow
                        key={post.post_id}
                        post={post}
                        rank={startRank + i}
                        state={state}
                        updatePost={updatePost}
                        saved={saved}
                        onToggleSave={onToggleSave}
                        onHide={onHide}
                        onShare={onShare}
                        blurSensitive={blurSensitive}
                    />
                );
            })}
        </ListContainer>
    );
}
