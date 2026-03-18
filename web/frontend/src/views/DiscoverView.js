import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Helmet } from 'react-helmet-async';
import styled from 'styled-components';
import Storage from '../utils/Storage';
import { getAllowedTagsParam } from '../utils/ContentTags';
import Api from '../lib/api';
import { subscribe, unsubscribe, fetchFollowedTopics, invalidateCache as invalidateTopicsCache } from '../utils/Subscriptions';
import { usePendingFollows } from '../utils/useFollowState';
import { Link, useLocation } from 'react-router-dom';
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import Button from "../components/Button";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../styled/Layout";

const SearchInput = styled.input`
    width: 100%;
    padding: 0.4rem 0.6rem;
    margin-top: 0.5rem;
    margin-bottom: 0.5rem;
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#33373C'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 4px;
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-size: 0.75rem;
    font-family: inherit;
    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme?.colors?.link || '#FFFFFF'};
    }
`;

const Section = styled.div`
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 6px;
    margin: 0.5rem 0;
    padding: 0.5rem 0.6rem;
    background: ${({ theme }) => theme?.colors?.panelAlt || '#33373C'};
`;

const SectionTitle = styled.div`
    font-weight: bold;
    font-size: 0.8rem;
    margin-bottom: 0.4rem;
`;

const ItemRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 0;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    &:last-child { border-bottom: none; }
    font-size: 0.7rem;
    gap: 0.4rem;

    @media (max-width: 700px) {
        flex-direction: column;
        align-items: flex-start;
    }
`;

const ItemLeft = styled.div`
    display: flex;
    flex-direction: row;
    align-items: baseline;
    gap: 0.3rem;
    flex-wrap: wrap;
`;

const ItemRight = styled.div`
    display: flex;
    margin-left: auto;

    @media (max-width: 700px) {
        width: 100%;

        button {
            width: 100%;
        }
    }
`;

const Subtle = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    font-weight: bold;
    font-size: 0.6rem;
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
    font-size: 0.7rem;
    padding: 0.5rem 0;
`;

const MoreTopicsHint = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.7rem;
    font-style: italic;
    text-align: center;
    padding: 0.6rem 0 0.3rem;
    border-top: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    margin-top: 0.3rem;
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
    margin-left: 0.3rem;
`;

export default function DiscoverView({ state }) {
    const viewerAddress = Storage.load('publicKey', '') || 'guest';
    const [topics, setTopics] = useState([]);
    const [filteredTopics, setFilteredTopics] = useState([]);
    const [smallTopicsCount, setSmallTopicsCount] = useState(0);
    const [searchTerm, setSearchTerm] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [isSearching, setIsSearching] = useState(false);
    const [loading, setLoading] = useState(true);
    const [followedTopicsSet, setFollowedTopicsSet] = useState(new Set());
    const [hoverTopic, setHoverTopic] = useState(null);
    const { isTopicPending, formatTopicStatus } = usePendingFollows();
    const mountedRef = useRef(true);
    const searchRequestId = useRef(0);

    useEffect(() => {
        mountedRef.current = true;
        return () => { mountedRef.current = false; };
    }, []);

    useEffect(() => {
        let alive = true;
        setLoading(true);
        Api.get('get_topics', { limit: 200, min_posts: 10, address: viewerAddress, allowed_tags: getAllowedTagsParam() })
            .then((data) => {
                if (!alive || !mountedRef.current) return;
                if (data && Array.isArray(data.topics)) {
                    const topicsList = data.topics
                        .filter(t => t && t.topic && typeof t.topic === 'string' && t.topic.trim() !== '')
                        .map(t => ({
                            topic: t.topic,
                            post_count: t.post_count || t.count || 0,
                            comment_count: t.comment_count || 0,
                            dominant_tag: t.dominant_tag || null
                        }));
                    setTopics(topicsList);
                    setFilteredTopics(topicsList);
                    setSmallTopicsCount(data.small_topics_count || 0);
                } else {
                    setTopics([]);
                    setFilteredTopics([]);
                    setSmallTopicsCount(0);
                }
                setLoading(false);
            })
            .catch((error) => {
                if (!alive || !mountedRef.current) return;
                console.error('[DiscoverView] Failed to load topics:', error);
                setTopics([]);
                setFilteredTopics([]);
                setLoading(false);
            });
        return () => { alive = false; };
    }, [viewerAddress]);

    // Filter local topics and search API for more results
    useEffect(() => {
        const term = searchTerm.toLowerCase().trim().replace(/^#+/, '');

        if (!term) {
            setFilteredTopics(topics);
            setSearchResults([]);
            setIsSearching(false);
            return;
        }

        // Filter local topics immediately
        const filtered = topics.filter(t => {
            const topicName = String(t.topic || '').toLowerCase();
            return topicName.includes(term);
        });
        setFilteredTopics(filtered);

        // Also search API for topics with < 10 posts (debounced)
        if (term.length < 2) {
            setSearchResults([]);
            setIsSearching(false);
            return;
        }

        const requestId = searchRequestId.current + 1;
        searchRequestId.current = requestId;
        setIsSearching(true);

        const handle = setTimeout(async () => {
            try {
                const data = await Api.get('search_topics', { q: term, limit: 50, allowed_tags: getAllowedTagsParam() }, { timeoutMs: 8000 });
                if (searchRequestId.current !== requestId || !mountedRef.current) return;
                const results = Array.isArray(data?.topics) ? data.topics : [];
                // Filter out topics already in the main list
                const existingLower = new Set(topics.map(t => t.topic.toLowerCase()));
                const newTopics = results
                    .filter(t => t && t.topic && !existingLower.has(t.topic.toLowerCase()))
                    .map(t => ({
                        topic: t.topic,
                        post_count: t.post_count || t.count || 0,
                        comment_count: t.comment_count || 0,
                        dominant_tag: t.dominant_tag || null,
                        fromSearch: true
                    }));
                setSearchResults(newTopics);
            } catch (_) {
                if (searchRequestId.current === requestId) setSearchResults([]);
            } finally {
                if (searchRequestId.current === requestId) setIsSearching(false);
            }
        }, 250);

        return () => {
            searchRequestId.current += 1;
            clearTimeout(handle);
        };
    }, [searchTerm, topics]);

    useEffect(() => {
        let cancelled = false;
        const loadFollowedTopics = async () => {
            if (!viewerAddress || viewerAddress === 'guest') return;
            try {
                const list = await fetchFollowedTopics(viewerAddress);
                if (!cancelled && mountedRef.current) {
                    setFollowedTopicsSet(new Set(list.map(t => t.toLowerCase())));
                }
            } catch (_) { }
        };
        loadFollowedTopics();
        return () => { cancelled = true; };
    }, [viewerAddress]);

    const isSubscribedTopic = useCallback((topic) => {
        return followedTopicsSet.has(String(topic || '').toLowerCase());
    }, [followedTopicsSet]);

    const handleSubscribeToggle = useCallback(async (topic) => {
        const t = String(topic || '').toLowerCase();
        if (!t || isTopicPending(t)) return;

        const wasSubscribed = isSubscribedTopic(topic);
        try {
            if (wasSubscribed) {
                await unsubscribe(viewerAddress, topic);
                if (mountedRef.current) {
                    setFollowedTopicsSet(prev => {
                        const next = new Set(prev);
                        next.delete(t);
                        return next;
                    });
                }
            } else {
                await subscribe(viewerAddress, topic);
                if (mountedRef.current) {
                    setFollowedTopicsSet(prev => new Set([...prev, t]));
                }
            }
            invalidateTopicsCache();
        } catch (_) { }
    }, [viewerAddress, isTopicPending, isSubscribedTopic]);

    const location = useLocation();

    return (
        <ContentGrid>
            <Helmet>
                <title>Topics | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerTab>Discover</ContainerTab>
                        <ContainerBody>
                            <SearchInput
                                type="text"
                                placeholder="Search topics..."
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                            />
                            <Section>
                                <SectionTitle>Topics</SectionTitle>
                                {loading ? (
                                    <EmptyMessage>Loading topics...</EmptyMessage>
                                ) : filteredTopics.length === 0 && searchResults.length === 0 && !isSearching ? (
                                    <EmptyMessage>
                                        {searchTerm.trim() ? 'No topics match your search' : 'No topics found'}
                                    </EmptyMessage>
                                ) : (
                                    <>
                                        {filteredTopics.map((t) => {
                                            const topicLower = t.topic.toLowerCase();
                                            const isFollowing = isSubscribedTopic(t.topic);
                                            const isInProgress = isTopicPending(topicLower);
                                            return (
                                                <ItemRow key={`topic-${t.topic}`}>
                                                    <ItemLeft>
                                                        <Subtle>#</Subtle>
                                                        <ItemLink to={`/t/${t.topic}`}>{t.topic}</ItemLink>
                                                        {t.dominant_tag && (
                                                            <TagBadge $tag={t.dominant_tag}>{t.dominant_tag}</TagBadge>
                                                        )}
                                                        <CountText>
                                                            ({t.post_count || 0} posts, {t.comment_count || 0} comments)
                                                        </CountText>
                                                    </ItemLeft>
                                                    <ItemRight>
                                                        <Button
                                                            variant={
                                                                isFollowing && hoverTopic === topicLower
                                                                    ? 'primaryDanger'
                                                                    : isFollowing
                                                                        ? 'subtle'
                                                                        : 'primary'
                                                            }
                                                            size="sm"
                                                            minWidth="follow"
                                                            disabled={isInProgress}
                                                            loading={isInProgress}
                                                            onMouseEnter={() => setHoverTopic(topicLower)}
                                                            onMouseLeave={() => setHoverTopic(null)}
                                                            onClick={() => handleSubscribeToggle(t.topic)}
                                                        >
                                                            {isInProgress
                                                                ? formatTopicStatus(topicLower)
                                                                : isFollowing
                                                                    ? (hoverTopic === topicLower ? 'Unfollow' : 'Following')
                                                                    : 'Follow'}
                                                        </Button>
                                                    </ItemRight>
                                                </ItemRow>
                                            );
                                        })}
                                        {searchResults.length > 0 && (
                                            <>
                                                <MoreTopicsHint style={{ marginTop: filteredTopics.length > 0 ? '0.5rem' : 0, borderTop: filteredTopics.length > 0 ? undefined : 'none', fontStyle: 'normal', fontWeight: 600 }}>
                                                    Topics with fewer than 10 posts
                                                </MoreTopicsHint>
                                                {searchResults.map((t) => {
                                                    const topicLower = t.topic.toLowerCase();
                                                    const isFollowing = isSubscribedTopic(t.topic);
                                                    const isInProgress = isTopicPending(topicLower);
                                                    return (
                                                        <ItemRow key={`search-${t.topic}`}>
                                                            <ItemLeft>
                                                                <Subtle>#</Subtle>
                                                                <ItemLink to={`/t/${t.topic}`}>{t.topic}</ItemLink>
                                                                {t.dominant_tag && (
                                                                    <TagBadge $tag={t.dominant_tag}>{t.dominant_tag}</TagBadge>
                                                                )}
                                                                <CountText>
                                                                    ({t.post_count || 0} posts, {t.comment_count || 0} comments)
                                                                </CountText>
                                                            </ItemLeft>
                                                            <ItemRight>
                                                                <Button
                                                                    variant={
                                                                        isFollowing && hoverTopic === topicLower
                                                                            ? 'primaryDanger'
                                                                            : isFollowing
                                                                                ? 'subtle'
                                                                                : 'primary'
                                                                    }
                                                                    size="sm"
                                                                    minWidth="follow"
                                                                    disabled={isInProgress}
                                                                    loading={isInProgress}
                                                                    onMouseEnter={() => setHoverTopic(topicLower)}
                                                                    onMouseLeave={() => setHoverTopic(null)}
                                                                    onClick={() => handleSubscribeToggle(t.topic)}
                                                                >
                                                                    {isInProgress
                                                                        ? formatTopicStatus(topicLower)
                                                                        : isFollowing
                                                                            ? (hoverTopic === topicLower ? 'Unfollow' : 'Following')
                                                                            : 'Follow'}
                                                                </Button>
                                                            </ItemRight>
                                                        </ItemRow>
                                                    );
                                                })}
                                            </>
                                        )}
                                        {isSearching && (
                                            <EmptyMessage>Searching for more topics...</EmptyMessage>
                                        )}
                                        {!searchTerm.trim() && smallTopicsCount > 0 && (
                                            <MoreTopicsHint>
                                                and {smallTopicsCount} more topic{smallTopicsCount !== 1 ? 's' : ''} with fewer than 10 posts
                                            </MoreTopicsHint>
                                        )}
                                    </>
                                )}
                            </Section>
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}

