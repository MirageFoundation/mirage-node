import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import { Link, useLocation } from 'react-router-dom';
import Sidebar from '../components/Sidebar';
import TopBar from '../components/TopBar';
import Button from '../components/Button';
import MobileHeader from '../components/MobileHeader';
import CardView from '../components/CardView';
import Storage from '../utils/Storage';
import Api from '../lib/api';
import { ContentGrid, ModernPostFeed, AnimatedCard } from '../styled/Layout';

const SectionHeader = styled.div`
    font-size: 0.85rem;
    font-weight: 600;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    margin: 1rem 0 0.5rem 0;
    
    &:first-child {
        margin-top: 0;
    }
`;

const ItemRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.6rem 0.75rem;
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    margin-bottom: 0.5rem;
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    font-size: 0.75rem;
    gap: 0.5rem;

    @media (max-width: 700px) {
        flex-direction: column;
        align-items: flex-start;
    }
`;

const ItemLeft = styled.div`
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0.4rem;
    flex-wrap: wrap;
`;

const Subtle = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    font-weight: bold;
    font-size: 0.7rem;
`;

const ItemLink = styled(Link)`
    color: ${({ theme }) => theme?.colors?.link || '#FFFFFF'};
    text-decoration: none;
    font-weight: bold;
    &:hover { color: ${({ theme }) => theme?.colors?.linkHover || '#CCCCCC'}; }
`;

const CountText = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    font-weight: normal;
    font-size: 0.65rem;
`;

const EmptyMessage = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    font-size: 0.8rem;
    padding: 1rem 0;
    text-align: center;
`;

const LoadingMessage = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.8rem;
    text-align: center;
    padding: 2rem 1rem;
`;

const ErrorMessage = styled.div`
    color: #f87171;
    font-size: 0.8rem;
    text-align: center;
    padding: 1rem;
`;

const tagColors = {
    porn: { bg: 'rgba(236, 72, 153, 0.18)', border: 'rgba(236, 72, 153, 0.50)', text: '#ec4899' },
    violence: { bg: 'rgba(185, 28, 28, 0.18)', border: 'rgba(185, 28, 28, 0.50)', text: '#b91c1c' },
    gore: { bg: 'rgba(185, 28, 28, 0.18)', border: 'rgba(185, 28, 28, 0.50)', text: '#b91c1c' },
    death: { bg: 'rgba(185, 28, 28, 0.18)', border: 'rgba(185, 28, 28, 0.50)', text: '#b91c1c' },
    sensitive: { bg: 'rgba(109, 40, 217, 0.18)', border: 'rgba(109, 40, 217, 0.50)', text: '#6d28d9' },
    default: { bg: '#e5e7eb', border: '#cbd5e1', text: '#0f172a' },
};

const TagBadge = styled.span`
    display: inline-flex;
    align-items: center;
    padding: 0.05rem 0.35rem;
    border-radius: 999px;
    background: ${({ $tag }) => (tagColors[$tag]?.bg || tagColors.default.bg)};
    color: ${({ $tag }) => (tagColors[$tag]?.text || tagColors.default.text)};
    font-size: 0.55rem;
    font-weight: 700;
    text-transform: lowercase;
    border: 1px solid ${({ $tag }) => (tagColors[$tag]?.border || tagColors.default.border)};
`;

const LoadMoreButton = styled.div`
    display: flex;
    justify-content: center;
    padding: 0.5rem 0;
    margin-top: 0.25rem;

    @media (max-width: 700px) {
        button { width: 100%; }
    }
`;

const UserMeta = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.65rem;
    font-weight: normal;
`;


export default function SearchResultsView({ state }) {
    const location = useLocation();
    const viewerAddress = Storage.load('publicKey', '') || '';
    const mountedRef = useRef(true);

    const query = useMemo(() => {
        try {
            const params = new URLSearchParams(location.search);
            return (params.get('q') || '').trim();
        } catch {
            return '';
        }
    }, [location.search]);

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [, setSearchType] = useState('general');
    const [topics, setTopics] = useState([]);
    const [users, setUsers] = useState([]);
    const [posts, setPosts] = useState([]);
    const [hasMoreTopics, setHasMoreTopics] = useState(false);
    const [hasMoreUsers, setHasMoreUsers] = useState(false);
    const [hasMorePosts, setHasMorePosts] = useState(false);
    const [loadingMoreTopics, setLoadingMoreTopics] = useState(false);
    const [loadingMoreUsers, setLoadingMoreUsers] = useState(false);
    const [loadingMorePosts, setLoadingMorePosts] = useState(false);
    const [topicsOffset, setTopicsOffset] = useState(0);
    const [usersOffset, setUsersOffset] = useState(0);
    const [postsOffset, setPostsOffset] = useState(0);

    // Extract display query (without @ or # prefix)
    const displayQuery = useMemo(() => {
        if (query.startsWith('@') || query.startsWith('#')) {
            return query.slice(1);
        }
        return query;
    }, [query]);

    useEffect(() => {
        mountedRef.current = true;
        return () => { mountedRef.current = false; };
    }, []);

    useEffect(() => {
        if (!query) {
            setLoading(false);
            setTopics([]);
            setUsers([]);
            setPosts([]);
            return;
        }

        let cancelled = false;
        setLoading(true);
        setError('');
        setTopics([]);
        setUsers([]);
        setPosts([]);
        setTopicsOffset(0);
        setUsersOffset(0);
        setPostsOffset(0);

        const doSearch = async () => {
            try {
                const params = { q: query, limit: 10 };
                if (viewerAddress) params.address = viewerAddress;

                const data = await Api.get('search', params, { timeoutMs: 15000 });
                if (cancelled || !mountedRef.current) return;

                setSearchType(data.search_type || 'general');
                setTopics(data.topics || []);
                setUsers(data.users || []);
                setPosts(data.posts || []);
                setHasMoreTopics(data.has_more_topics || false);
                setHasMoreUsers(data.has_more_users || false);
                setHasMorePosts(data.has_more_posts || false);
                setTopicsOffset((data.topics || []).length);
                setUsersOffset((data.users || []).length);
                setPostsOffset((data.posts || []).length);
                setLoading(false);
            } catch (err) {
                if (!cancelled && mountedRef.current) {
                    setError(err?.message || 'Search failed');
                    setLoading(false);
                }
            }
        };

        doSearch();
        return () => { cancelled = true; };
    }, [query, viewerAddress]);

    const loadMoreTopics = useCallback(async () => {
        if (loadingMoreTopics || !hasMoreTopics) return;
        setLoadingMoreTopics(true);

        try {
            const params = { q: query, type: 'topics', limit: 10, offset: topicsOffset };
            if (viewerAddress) params.address = viewerAddress;

            const data = await Api.get('search', params, { timeoutMs: 15000 });
            if (!mountedRef.current) return;

            const newTopics = data.topics || [];
            setTopics(prev => [...prev, ...newTopics]);
            setHasMoreTopics(data.has_more_topics || false);
            setTopicsOffset(prev => prev + newTopics.length);
        } catch (err) {
            console.error('[SearchResultsView] Load more topics failed:', err);
        } finally {
            if (mountedRef.current) setLoadingMoreTopics(false);
        }
    }, [query, topicsOffset, hasMoreTopics, loadingMoreTopics, viewerAddress]);

    const loadMoreUsers = useCallback(async () => {
        if (loadingMoreUsers || !hasMoreUsers) return;
        setLoadingMoreUsers(true);

        try {
            const params = { q: query, type: 'users', limit: 10, offset: usersOffset };
            if (viewerAddress) params.address = viewerAddress;

            const data = await Api.get('search', params, { timeoutMs: 15000 });
            if (!mountedRef.current) return;

            const newUsers = data.users || [];
            setUsers(prev => [...prev, ...newUsers]);
            setHasMoreUsers(data.has_more_users || false);
            setUsersOffset(prev => prev + newUsers.length);
        } catch (err) {
            console.error('[SearchResultsView] Load more users failed:', err);
        } finally {
            if (mountedRef.current) setLoadingMoreUsers(false);
        }
    }, [query, usersOffset, hasMoreUsers, loadingMoreUsers, viewerAddress]);

    const loadMorePosts = useCallback(async () => {
        if (loadingMorePosts || !hasMorePosts) return;
        setLoadingMorePosts(true);

        try {
            const params = { q: query, type: 'posts', limit: 10, offset: postsOffset };
            if (viewerAddress) params.address = viewerAddress;

            const data = await Api.get('search', params, { timeoutMs: 15000 });
            if (!mountedRef.current) return;

            const newPosts = data.posts || [];
            setPosts(prev => [...prev, ...newPosts]);
            setHasMorePosts(data.has_more_posts || false);
            setPostsOffset(prev => prev + newPosts.length);
        } catch (err) {
            console.error('[SearchResultsView] Load more posts failed:', err);
        } finally {
            if (mountedRef.current) setLoadingMorePosts(false);
        }
    }, [query, postsOffset, hasMorePosts, loadingMorePosts, viewerAddress]);

    const formatDate = (ts) => {
        if (!ts) return '';
        const d = new Date(ts * 1000);
        return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
    };

    const hasResults = topics.length > 0 || users.length > 0 || posts.length > 0;

    return (
        <ContentGrid>
            <Helmet>
                <title>{query ? `Search: ${query}` : 'Search'} | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />

                    {!query && (
                        <EmptyMessage>Enter a search term to find topics, users, and posts.</EmptyMessage>
                    )}

                    {query && loading && (
                        <LoadingMessage>Searching...</LoadingMessage>
                    )}

                    {query && error && (
                        <ErrorMessage>{error}</ErrorMessage>
                    )}

                    {query && !loading && !error && (
                        <>
                            {!hasResults && (
                                <EmptyMessage>No results found for "{displayQuery}"</EmptyMessage>
                            )}

                            {/* Users Section */}
                            {users.length > 0 && (
                                <>
                                    <SectionHeader>Users matching "{displayQuery}"</SectionHeader>
                                    {users.map((user) => (
                                        <ItemRow key={user.address}>
                                            <ItemLeft>
                                                <ItemLink to={`/profile?address=${encodeURIComponent(user.address)}`}>
                                                    @{user.username}
                                                </ItemLink>
                                                <UserMeta>
                                                    {user.post_count || 0} posts
                                                    {user.created_at && ` · joined ${formatDate(user.created_at)}`}
                                                </UserMeta>
                                            </ItemLeft>
                                        </ItemRow>
                                    ))}
                                    {hasMoreUsers && (
                                        <LoadMoreButton>
                                            <Button
                                                variant="subtle"
                                                size="sm"
                                                onClick={loadMoreUsers}
                                                loading={loadingMoreUsers}
                                                disabled={loadingMoreUsers}
                                            >
                                                {loadingMoreUsers ? 'Loading...' : 'Load More Users'}
                                            </Button>
                                        </LoadMoreButton>
                                    )}
                                </>
                            )}

                            {/* Topics Section */}
                            {topics.length > 0 && (
                                <>
                                    <SectionHeader>Topics matching "{displayQuery}"</SectionHeader>
                                    {topics.map((t) => (
                                        <ItemRow key={`topic-${t.topic}`}>
                                            <ItemLeft>
                                                <Subtle>#</Subtle>
                                                <ItemLink to={`/t/${encodeURIComponent(t.topic)}`}>{t.topic}</ItemLink>
                                                {t.dominant_tag && (
                                                    <TagBadge $tag={t.dominant_tag}>{t.dominant_tag}</TagBadge>
                                                )}
                                                <CountText>({t.post_count || 0} posts)</CountText>
                                            </ItemLeft>
                                        </ItemRow>
                                    ))}
                                    {hasMoreTopics && (
                                        <LoadMoreButton>
                                            <Button
                                                variant="subtle"
                                                size="sm"
                                                onClick={loadMoreTopics}
                                                loading={loadingMoreTopics}
                                                disabled={loadingMoreTopics}
                                            >
                                                {loadingMoreTopics ? 'Loading...' : 'Load More Topics'}
                                            </Button>
                                        </LoadMoreButton>
                                    )}
                                </>
                            )}

                            {/* Posts Section */}
                            {posts.length > 0 && (
                                <>
                                    <SectionHeader>Posts matching "{displayQuery}"</SectionHeader>
                                    {posts.map((post, index) => {
                                        const postObj = {
                                            post_id: post.post_id,
                                            user_id: post.user_id,
                                            username: post.username,
                                            timestamp: post.timestamp,
                                            title: post.title,
                                            content: post.content,
                                            topic: post.topic,
                                            tag: post.tag,
                                            thumbnail: post.thumbnail,
                                            points: post.points,
                                            comments: post.comments,
                                            direction: post.user_vote,
                                        };
                                        return (
                                            <AnimatedCard 
                                                key={post.post_id} 
                                                style={{ animationDelay: `${index * 30}ms` }}
                                                onClick={() => {
                                                    try {
                                                        window.sessionStorage.setItem('mirage_post_referrer', 'search');
                                                    } catch (_) { }
                                                }}
                                            >
                                                <CardView
                                                    post={postObj}
                                                    state={state}
                                                />
                                            </AnimatedCard>
                                        );
                                    })}
                                    {hasMorePosts && (
                                        <LoadMoreButton>
                                            <Button
                                                variant="subtle"
                                                size="sm"
                                                onClick={loadMorePosts}
                                                loading={loadingMorePosts}
                                                disabled={loadingMorePosts}
                                            >
                                                {loadingMorePosts ? 'Loading...' : 'Load More Posts'}
                                            </Button>
                                        </LoadMoreButton>
                                    )}
                                </>
                            )}
                        </>
                    )}
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
