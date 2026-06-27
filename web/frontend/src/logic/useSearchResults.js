import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useLocation } from "react-router-dom";
import Storage from "../utils/Storage";
import { getAllowedTagsParam } from "../utils/ContentTags";
import Api from "../utils/api";
import { isOpenBrowsingEnabled } from "../utils/openBrowsing";
export const tagColors = {
    adult: {
        bg: 'rgba(236, 72, 153, 0.18)',
        border: 'rgba(236, 72, 153, 0.50)',
        text: '#ec4899'
    },
    violence: {
        bg: 'rgba(185, 28, 28, 0.18)',
        border: 'rgba(185, 28, 28, 0.50)',
        text: '#b91c1c'
    },
    gore: {
        bg: 'rgba(185, 28, 28, 0.18)',
        border: 'rgba(185, 28, 28, 0.50)',
        text: '#b91c1c'
    },
    death: {
        bg: 'rgba(185, 28, 28, 0.18)',
        border: 'rgba(185, 28, 28, 0.50)',
        text: '#b91c1c'
    },
    sensitive: {
        bg: 'rgba(109, 40, 217, 0.18)',
        border: 'rgba(109, 40, 217, 0.50)',
        text: '#6d28d9'
    },
    default: {
        bg: '#e5e7eb',
        border: '#cbd5e1',
        text: '#0f172a'
    }
};
export function useSearchResults({
    state
}) {
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
        return () => {
            mountedRef.current = false;
        };
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
                const params = {
                    q: query,
                    limit: 10
                };
                if (viewerAddress) params.address = viewerAddress;
                params.allowed_tags = getAllowedTagsParam();
                const data = await Api.get('search', params, {
                    timeoutMs: 15000
                });
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
        return () => {
            cancelled = true;
        };
    }, [query, viewerAddress]);
    const loadMoreTopics = useCallback(async () => {
        if (loadingMoreTopics || !hasMoreTopics) return;
        setLoadingMoreTopics(true);
        try {
            const params = {
                q: query,
                type: 'topics',
                limit: 10,
                offset: topicsOffset
            };
            if (viewerAddress) params.address = viewerAddress;
            params.allowed_tags = getAllowedTagsParam();
            const data = await Api.get('search', params, {
                timeoutMs: 15000
            });
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
            const params = {
                q: query,
                type: 'users',
                limit: 10,
                offset: usersOffset
            };
            if (viewerAddress) params.address = viewerAddress;
            params.allowed_tags = getAllowedTagsParam();
            const data = await Api.get('search', params, {
                timeoutMs: 15000
            });
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
            const params = {
                q: query,
                type: 'posts',
                limit: 10,
                offset: postsOffset
            };
            if (viewerAddress) params.address = viewerAddress;
            params.allowed_tags = getAllowedTagsParam();
            const data = await Api.get('search', params, {
                timeoutMs: 15000
            });
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
    const formatDate = ts => {
        if (!ts) return '';
        const d = new Date(ts * 1000);
        return d.toLocaleDateString('en-US', {
            month: 'short',
            year: 'numeric'
        });
    };
    const hasResults = topics.length > 0 || users.length > 0 || posts.length > 0;
    const isLoggedIn = !!viewerAddress;
    const openBrowsingEnabled = isOpenBrowsingEnabled();

    return {
        location,
        query,
        loading,
        error,
        topics,
        users,
        posts,
        hasMoreTopics,
        hasMoreUsers,
        hasMorePosts,
        loadingMoreTopics,
        loadingMoreUsers,
        loadingMorePosts,
        displayQuery,
        loadMoreTopics,
        loadMoreUsers,
        loadMorePosts,
        formatDate,
        hasResults,
        isLoggedIn,
        openBrowsingEnabled
    };
}