import React, { memo, useCallback, useState, useEffect } from 'react';
import styled from 'styled-components';
import { Link } from 'react-router-dom';
import VoteSection from './components/VoteSection';
import { buildPhotonUrl, isLikelyImageUrl } from '../../utils/media';
import { getAuthorColor } from '../../utils/tierColors';
import Storage from '../../utils/Storage';

const ListContainer = styled.div`
    display: flex;
    flex-direction: column;
    background: ${({ theme }) => theme.colors.panel};
`;

const Row = styled.div`
    display: flex;
    align-items: center;
    padding: 0.4rem 0.5rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    gap: 0.4rem;
    min-height: 52px;

    &:last-child {
        border-bottom: none;
    }

    &:hover {
        background: ${({ theme }) => theme.colors.panelAlt};
    }
`;

const Rank = styled.span`
    flex: 0 0 1.8rem;
    text-align: right;
    font-size: 0.75rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
    padding-top: 0.25rem;
`;

const VoteColumn = styled.div`
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 2.5rem;
    align-self: flex-start;
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
    }
`;

const ContentColumn = styled.div`
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
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
`;

const MetaLine = styled.div`
    font-size: 0.65rem;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.35;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
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
    gap: 0.6rem;
    font-size: 0.65rem;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.35;
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

const SortTabs = styled.div`
    display: flex;
    gap: 0.5rem;
    padding: 0.4rem 0.5rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panel};
`;

const SortTab = styled.button`
    background: ${({ $active, theme }) => ($active ? theme.colors.panelAlt : 'transparent')};
    border: 1px solid ${({ $active, theme }) => ($active ? theme.colors.border : 'transparent')};
    color: ${({ $active, theme }) => ($active ? theme.colors.text : theme.colors.subtleText)};
    font-size: 0.65rem;
    font-weight: 700;
    padding: 0.15rem 0.4rem;
    text-transform: lowercase;
    cursor: pointer;
    &:hover {
        color: ${({ theme }) => theme.colors.text};
        border-color: ${({ theme }) => theme.colors.border};
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
    const shouldBlur = blurSensitive && hasTag;
    let displayAuthor = '';
    if (typeof username === 'string' && username.trim().length > 0) {
        displayAuthor = username;
    } else if (typeof author === 'string' && author.trim().length > 0) {
        displayAuthor = `${author.slice(0, 10)}...`;
    }

    return (
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
                    {hasTag && <TagBadge>{String(post.tag).trim()}</TagBadge>}
                    {title}
                </Title>
                <MetaLine>
                    {isComment ? 'commented' : 'submitted'} {formatAge(ts)} by{' '}
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
                </ActionsLine>
            </ContentColumn>
        </Row>
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

const SORT_TABS = ['best', 'new'];

export default function ListFeedView({ posts, state, updatePost, startRank = 1, sortMode, onSortChange, showSortTabs }) {
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
        <ListContainer>
            {showSortTabs && (
                <SortTabs role="tablist" aria-label="Sort posts">
                    {SORT_TABS.map((tab) => (
                        <SortTab
                            key={tab}
                            type="button"
                            $active={tab === sortMode}
                            onClick={() => onSortChange(tab)}
                            role="tab"
                            aria-selected={tab === sortMode}
                        >
                            {tab}
                        </SortTab>
                    ))}
                </SortTabs>
            )}
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
