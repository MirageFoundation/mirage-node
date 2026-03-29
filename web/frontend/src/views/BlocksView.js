import React, { useEffect, useState } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import { useNavigate, useLocation } from 'react-router-dom';
import Storage from "../utils/Storage";
import Api from '../lib/api';
import * as tx from '../utils/tx';
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import Button from "../components/Button";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, TabsRow, ClickableTab } from "../styled/Layout";
import { usePendingBlocks } from "../utils/usePendingBlocks";
import { resolveUsernames as resolveUsernamesCached } from "../utils/UsernameCache";

const SectionTitle = styled.div`
    margin-top: ${({ $first, theme }) => $first ? '0' : (theme.layout.sectionMarginTop)};
    margin-bottom: ${({ theme }) => theme.layout.sectionMarginBottom};
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
    font-size: ${({ theme }) => theme.layout.sectionSize};
    display: flex;
    align-items: center;
    gap: 0.5rem;

    &::after {
        content: '';
        flex: 1;
        height: 1px;
        background: ${({ theme }) => theme.colors.border};
    }
`;

const ValueBox = styled.div`
    background-color: ${({ theme }) => theme.layout.containerBg };
    border: ${({ theme }) => theme.layout.containerBorder};
    border-bottom: ${({ theme }) => theme.layout.containerBorderBottom};
    border-radius: ${({ theme }) => theme.layout.containerRadius};
    padding: ${({ theme }) => theme.layout.containerPaddingCompact};
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;

const PostsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: ${({ theme }) => theme.layout.cardGap};
`;

const PostItem = styled.a`
    display: block;
    text-decoration: none;
    color: inherit;
    border: ${({ theme }) => theme.layout.cardBorder};
    border-bottom: ${({ theme }) => theme.layout.cardBorderBottom};
    background-color: ${({ theme }) => theme.layout.cardBg };
    border-radius: ${({ theme }) => theme.layout.cardRadius};
    padding: ${({ theme }) => theme.layout.cardPadding};
    cursor: pointer;
    transition: background-color 0.2s ease, border-color 0.2s ease;

    &:hover {
        background-color: ${({ theme }) => theme.colors.panelAlt};
        border-color: ${({ theme }) => theme.colors.subtleText};
    }
`;

const BlockItemRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
`;

const BlockItemContent = styled.div`
    min-width: 0;
    flex: 1;
`;

const BlockItemActions = styled.div`
    flex-shrink: 0;
    display: flex;
    align-items: center;
`;

const PostMeta = styled.div`
    font-size: 0.55rem;
    color: ${({ theme }) => theme.colors.subtleText};
    margin-bottom: 0.25rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
`;

const PostPreview = styled.div`
    font-size: 0.65rem;
    color: ${({ theme }) => theme.colors.text};
    line-height: 1.3;
    word-break: break-word;
    white-space: pre-line;
`;

const Mono = styled.span`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.8rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
`;

const shortenAddress = (addr) => {
    if (!addr) return '';
    if (addr.length <= 24) return addr;
    return `${addr.slice(0, 14)}...${addr.slice(-8)}`;
};

export default function BlocksView({ state }) {
    const navigate = useNavigate();
    const location = useLocation();
    const address = (state && state.publicKey) ? state.publicKey : Storage.load('publicKey', '');

    const [blockedUsers, setBlockedUsers] = useState([]);
    const [blockedPosts, setBlockedPosts] = useState([]);
    const [blockedTopics, setBlockedTopics] = useState([]);
    const [blockedUsernames, setBlockedUsernames] = useState({});
    const [listsLoading, setListsLoading] = useState(false);
    const [listsError, setListsError] = useState('');

    const {
        isTopicPending,
        isUserPending,
        isPostPending,
        formatTopicStatus,
        formatUserStatus,
        formatPostStatus,
    } = usePendingBlocks();

    useEffect(() => {
        if (!address) return;
        let cancelled = false;
        const fetchBlocks = async () => {
            setListsLoading(true);
            setListsError('');
            try {
                const data = await Api.get('get_user_blocked', { address });
                if (cancelled) return;
                setBlockedUsers(data?.blocked_users || []);
                setBlockedPosts(data?.blocked_posts || []);
                setBlockedTopics(data?.blocked_topics || []);
            } catch (err) {
                if (!cancelled) {
                    setListsError(err?.message || 'Failed to load blocked items');
                }
            } finally {
                if (!cancelled) {
                    setListsLoading(false);
                }
            }
        };
        fetchBlocks();
        return () => { cancelled = true; };
    }, [address]);

    useEffect(() => {
        const addrs = blockedUsers.map(a => String(a || '').trim()).filter(Boolean);
        if (addrs.length === 0) {
            setBlockedUsernames({});
            return;
        }

        let cancelled = false;
        const resolveAll = async () => {
            try {
                const mapping = await resolveUsernamesCached(addrs, { timeoutMs: 5000 });
                if (cancelled) return;
                const result = {};
                for (const addr of addrs) {
                    const lower = String(addr || '').toLowerCase();
                    const uname = mapping[lower];
                    result[addr] = uname || addr;
                }
                setBlockedUsernames(result);
            } catch {
                if (cancelled) return;
                const result = {};
                addrs.forEach(a => { result[a] = a; });
                setBlockedUsernames(result);
            }
        };
        resolveAll();
        return () => { cancelled = true; };
    }, [blockedUsers]);

    const handleUnblockTopic = async (e, topic) => {
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        const topicTrimmed = String(topic || '').trim().toLowerCase();
        if (!topicTrimmed) return;
        try {
            const result = await tx.unblockTopic(topicTrimmed);
            if (result && result.success) {
                setBlockedTopics((prev) => prev.filter(t => String(t || '').trim().toLowerCase() !== topicTrimmed));
            } else {
                alert(`Failed to unblock topic: ${result?.error || 'Unknown error'}`);
            }
        } catch (error) {
            alert(`Error unblocking topic: ${error?.message || error}`);
        }
    };

    const handleUnblockUser = async (e, userAddr) => {
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        const userTrimmed = String(userAddr || '').trim().toLowerCase();
        if (!userTrimmed) return;
        try {
            const result = await tx.unblockUser(userTrimmed);
            if (result && result.success) {
                setBlockedUsers((prev) => prev.filter(u => String(u || '').trim().toLowerCase() !== userTrimmed));
            } else {
                alert(`Failed to unblock user: ${result?.error || 'Unknown error'}`);
            }
        } catch (error) {
            alert(`Error unblocking user: ${error?.message || error}`);
        }
    };

    const handleUnblockPost = async (e, postId) => {
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        const postTrimmed = String(postId || '').trim().toLowerCase();
        if (!postTrimmed) return;
        try {
            const result = await tx.unblockPost(postTrimmed);
            if (result && result.success) {
                setBlockedPosts((prev) => prev.filter(p => String(p || '').trim().toLowerCase() !== postTrimmed));
            } else {
                alert(`Failed to unblock post: ${result?.error || 'Unknown error'}`);
            }
        } catch (error) {
            alert(`Error unblocking post: ${error?.message || error}`);
        }
    };

    return (
        <ContentGrid>
            <Helmet>
                <title>Blocks | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow>
                            <ClickableTab $active>Blocks</ClickableTab>
                        </TabsRow>
                        <ContainerBody>
                            <SectionTitle $first>Blocked Topics</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                {!listsLoading && !listsError && blockedTopics.length === 0 && (
                                    <Mono style={{ color: '#888' }}>No blocked topics.</Mono>
                                )}
                                {!listsLoading && !listsError && blockedTopics.length > 0 && (
                                    <PostsList>
                                        {blockedTopics.map((topic) => {
                                            const isPending = isTopicPending(topic);
                                            const status = formatTopicStatus(topic);
                                            return (
                                                <PostItem key={topic} href={`/t/${encodeURIComponent(topic)}`} onClick={(e) => { if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) { e.preventDefault(); navigate(`/t/${encodeURIComponent(topic)}`); } }}>
                                                    <BlockItemRow>
                                                        <BlockItemContent>
                                                            <PostPreview>#{topic}</PostPreview>
                                                        </BlockItemContent>
                                                        <BlockItemActions>
                                                            <Button
                                                                variant="ghost"
                                                                size="sm"
                                                                disabled={isPending}
                                                                loading={isPending}
                                                                onClick={(e) => handleUnblockTopic(e, topic)}
                                                            >
                                                                {status || 'Unblock'}
                                                            </Button>
                                                        </BlockItemActions>
                                                    </BlockItemRow>
                                                </PostItem>
                                            );
                                        })}
                                    </PostsList>
                                )}
                            </ValueBox>

                            <SectionTitle>Blocked Users</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                {!listsLoading && !listsError && blockedUsers.length === 0 && (
                                    <Mono style={{ color: '#888' }}>No blocked users.</Mono>
                                )}
                                {!listsLoading && !listsError && blockedUsers.length > 0 && (
                                    <PostsList>
                                        {blockedUsers.map((userAddr) => {
                                            const isPending = isUserPending(userAddr);
                                            const status = formatUserStatus(userAddr);
                                            return (
                                                <PostItem key={userAddr} href={`/u/${encodeURIComponent(blockedUsernames[userAddr] || userAddr)}`} onClick={(e) => { if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) { e.preventDefault(); navigate(`/u/${encodeURIComponent(blockedUsernames[userAddr] || userAddr)}`); } }}>
                                                    <BlockItemRow>
                                                        <BlockItemContent>
                                                            <PostPreview>
                                                                {blockedUsernames[userAddr] && blockedUsernames[userAddr] !== userAddr
                                                                    ? blockedUsernames[userAddr]
                                                                    : shortenAddress(userAddr)}
                                                            </PostPreview>
                                                            <PostMeta>{userAddr}</PostMeta>
                                                        </BlockItemContent>
                                                        <BlockItemActions>
                                                            <Button
                                                                variant="ghost"
                                                                size="sm"
                                                                disabled={isPending}
                                                                loading={isPending}
                                                                onClick={(e) => handleUnblockUser(e, userAddr)}
                                                            >
                                                                {status || 'Unblock'}
                                                            </Button>
                                                        </BlockItemActions>
                                                    </BlockItemRow>
                                                </PostItem>
                                            );
                                        })}
                                    </PostsList>
                                )}
                            </ValueBox>

                            <SectionTitle>Blocked Posts</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                {!listsLoading && !listsError && blockedPosts.length === 0 && (
                                    <Mono style={{ color: '#888' }}>No blocked posts.</Mono>
                                )}
                                {!listsLoading && !listsError && blockedPosts.length > 0 && (
                                    <PostsList>
                                        {blockedPosts.map((postId) => {
                                            const isPending = isPostPending(postId);
                                            const status = formatPostStatus(postId);
                                            return (
                                                <PostItem key={postId} href={`/p/${encodeURIComponent(postId)}`} onClick={(e) => { if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) { e.preventDefault(); navigate(`/p/${encodeURIComponent(postId)}`); } }}>
                                                    <BlockItemRow>
                                                        <BlockItemContent>
                                                            <PostPreview>{shortenAddress(postId)}</PostPreview>
                                                            <PostMeta>{postId}</PostMeta>
                                                        </BlockItemContent>
                                                        <BlockItemActions>
                                                            <Button
                                                                variant="ghost"
                                                                size="sm"
                                                                disabled={isPending}
                                                                loading={isPending}
                                                                onClick={(e) => handleUnblockPost(e, postId)}
                                                            >
                                                                {status || 'Unblock'}
                                                            </Button>
                                                        </BlockItemActions>
                                                    </BlockItemRow>
                                                </PostItem>
                                            );
                                        })}
                                    </PostsList>
                                )}
                            </ValueBox>
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
