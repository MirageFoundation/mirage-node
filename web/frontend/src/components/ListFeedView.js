import React, { memo, useCallback, useState } from 'react';
import styled from 'styled-components';
import { Link } from 'react-router-dom';
import VoteSection from './VoteSection';
import { buildPhotonUrl, isLikelyImageUrl } from '../utils/media';
import { getAuthorColor } from '../utils/tierColors';
import Storage from '../utils/Storage';

const ListContainer = styled.div`
    display: flex;
    flex-direction: column;
    border: 1px solid ${({ theme }) => theme?.colors?.border};
    border-radius: 4px;
    background: ${({ theme }) => theme?.colors?.panel};
`;

const Row = styled.div`
    display: flex;
    align-items: flex-start;
    padding: 0.4rem 0.5rem;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border};
    gap: 0.4rem;
    min-height: 52px;

    &:last-child {
        border-bottom: none;
    }

    &:hover {
        background: ${({ theme }) => theme?.colors?.panelAlt};
    }
`;

const Rank = styled.span`
    flex: 0 0 1.8rem;
    text-align: right;
    font-size: 0.75rem;
    font-weight: 500;
    color: ${({ theme }) => theme?.colors?.subtleText};
    padding-top: 0.25rem;
`;

const VoteColumn = styled.div`
    flex: 0 0 auto;
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 2.5rem;
    padding-top: 0.1rem;
`;

const Thumbnail = styled(Link)`
    flex: 0 0 70px;
    width: 70px;
    height: 52px;
    border-radius: 3px;
    overflow: hidden;
    background: ${({ theme }) => theme?.colors?.panelAlt};
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
        height: 38px;
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
    color: ${({ theme }) => theme?.colors?.link};
    text-decoration: none;
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;

    &:visited {
        color: ${({ theme }) => theme?.colors?.subtleText};
    }

    &:hover {
        text-decoration: underline;
    }
`;

const MetaLine = styled.div`
    font-size: 0.65rem;
    color: ${({ theme }) => theme?.colors?.subtleText};
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
    &:hover {
        text-decoration: underline;
    }
`;

const ActionsLine = styled.div`
    display: flex;
    gap: 0.6rem;
    font-size: 0.65rem;
    color: ${({ theme }) => theme?.colors?.subtleText};
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
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border};
    background: ${({ theme }) => theme?.colors?.panel};
`;

const SortTab = styled.button`
    background: ${({ $active, theme }) => ($active ? theme?.colors?.panelAlt : 'transparent')};
    border: 1px solid ${({ $active, theme }) => ($active ? theme?.colors?.border : 'transparent')};
    color: ${({ $active, theme }) => ($active ? theme?.colors?.text : theme?.colors?.subtleText)};
    font-size: 0.65rem;
    font-weight: 700;
    padding: 0.15rem 0.4rem;
    border-radius: 2px;
    text-transform: lowercase;
    cursor: pointer;
    &:hover {
        color: ${({ theme }) => theme?.colors?.text};
        border-color: ${({ theme }) => theme?.colors?.border};
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

function ListRow({ post, rank, state, updatePost, saved, onToggleSave, onHide, onShare }) {
    if (!post || !post.post_id) return null;
    if (typeof post.title !== 'string' || typeof post.topic !== 'string') {
        throw new Error('ListFeedView: post title/topic missing');
    }
    if (typeof post.author !== 'string') {
        throw new Error('ListFeedView: post author missing');
    }
    const postId = String(post.post_id);
    const topic = post.topic;
    const title = post.title;
    const author = post.author;
    const username = post.username;
    let ts = Number(post.timestamp);
    if (!Number.isFinite(ts)) {
        throw new Error('ListFeedView: timestamp missing');
    }
    if (ts > 1e12) ts = Math.floor(ts / 1000);
    const numComments = Number(post.num_comments) || 0;
    const thumbUrl = getThumbUrl(post);
    const authorColor = getAuthorColor(post?.author_level, post?.author_is_new);
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
                <VoteSection state={state} post={post} updatePost={updatePost} showToggle={false} inline />
            </VoteColumn>
            {thumbUrl ? (
                <Thumbnail to={`/p/${postId}`}>
                    <img src={thumbUrl} alt="" loading="lazy" />
                </Thumbnail>
            ) : null}
            <ContentColumn>
                <Title to={`/p/${postId}`}>{title}</Title>
                <MetaLine>
                    submitted {formatAge(ts)} by{' '}
                    <AuthorLink
                        to={`/u/${encodeURIComponent(username || author)}`}
                        style={authorColor ? { color: authorColor } : undefined}
                    >
                        {displayAuthor}
                    </AuthorLink>
                    {' '}to{' '}
                    <MetaLink to={`/t/${encodeURIComponent(topic)}`}>t/{topic}</MetaLink>
                </MetaLine>
                <ActionsLine>
                    <ActionLink to={`/p/${postId}`}>
                        {numComments} comment{numComments !== 1 ? 's' : ''}
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
                    <ActionLink to={`/p/${postId}`}>
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
        p === n ||
        (p?.post_id === n?.post_id &&
            p?.score === n?.score &&
            p?.direction === n?.direction &&
            p?.num_comments === n?.num_comments &&
            prev.rank === next.rank &&
            prev.saved === next.saved)
    );
});

const SORT_TABS = ['best', 'hot', 'new', 'rising', 'controversial', 'top'];

export default function ListFeedView({ posts, state, updatePost, startRank = 1, sortMode, onSortChange, showSortTabs }) {
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
                    />
                );
            })}
        </ListContainer>
    );
}
