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
import { unfollow, notifyUsersUpdated } from "../utils/FollowUsers";
import { notifyTopicsUpdated } from "../utils/Subscriptions";
import { usePendingFollows } from "../utils/useFollowState";
import { resolveUsernames as resolveUsernamesCached } from "../utils/UsernameCache";

const isOr = (t) => t?.themeId === 'oldreddit';

const SectionTitle = styled.div`
    margin-top: ${({ $first, theme }) => $first ? '0' : (isOr(theme) ? '0.75rem' : '1.5rem')};
    margin-bottom: ${({ theme }) => isOr(theme) ? '0.25rem' : '0.5rem'};
    font-weight: 700;
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-size: ${({ theme }) => isOr(theme) ? '0.75rem' : '0.95rem'};
    display: flex;
    align-items: center;
    gap: 0.5rem;

    &::after {
        content: '';
        flex: 1;
        height: 1px;
        background: ${({ theme }) => theme?.colors?.border || '#333'};
    }
`;

const ValueBox = styled.div`
    background-color: ${({ theme }) => isOr(theme) ? 'transparent' : (theme?.colors?.panelAlt || '#1f2328')};
    border: ${({ theme }) => isOr(theme) ? 'none' : `1px solid ${theme?.colors?.border || '#444'}`};
    border-bottom: ${({ theme }) => isOr(theme) ? `1px solid ${theme?.colors?.border || '#444'}` : 'none'};
    border-radius: ${({ theme }) => isOr(theme) ? '0' : '8px'};
    padding: ${({ theme }) => isOr(theme) ? '0.3rem 0' : '0.6rem 0.85rem'};
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;

const PostsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: ${({ theme }) => isOr(theme) ? '0' : '0.5rem'};
`;

const PostItem = styled.a`
    display: block;
    text-decoration: none;
    color: inherit;
    border: ${({ theme }) => isOr(theme) ? 'none' : `1px solid ${theme?.colors?.border || '#444'}`};
    border-bottom: ${({ theme }) => isOr(theme) ? `1px solid ${theme?.colors?.border || '#444'}` : 'none'};
    background-color: ${({ theme }) => isOr(theme) ? 'transparent' : (theme?.colors?.panel || '#23272C')};
    border-radius: ${({ theme }) => isOr(theme) ? '0' : '8px'};
    padding: ${({ theme }) => isOr(theme) ? '0.35rem 0.4rem' : '0.6rem 0.85rem'};
    cursor: pointer;
    transition: background-color 0.2s ease, border-color 0.2s ease;

    &:hover {
        background-color: ${({ theme }) => theme?.colors?.panelAlt || '#2E3238'};
        border-color: ${({ theme }) => theme?.colors?.subtleText || '#666'};
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
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    margin-bottom: 0.25rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
`;

const PostPreview = styled.div`
    font-size: 0.65rem;
    color: ${({ theme }) => theme?.colors?.text || '#DDDDDD'};
    line-height: 1.3;
    word-break: break-word;
    white-space: pre-line;
`;

const Mono = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
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

export default function FollowsView({ state }) {
    const navigate = useNavigate();
    const location = useLocation();
    const address = (state && state.publicKey) ? state.publicKey : Storage.load('publicKey', '');

    const [followedUsers, setFollowedUsers] = useState([]);
    const [followedTopics, setFollowedTopics] = useState([]);
    const [followedUsernames, setFollowedUsernames] = useState({});
    const [listsLoading, setListsLoading] = useState(false);
    const [listsError, setListsError] = useState('');

    const {
        isTopicPending: isFollowTopicPending,
        isUserPending: isFollowUserPending,
        formatTopicStatus: formatFollowTopicStatus,
        formatUserStatus: formatFollowUserStatus,
    } = usePendingFollows();

    useEffect(() => {
        if (!address) return;
        let cancelled = false;
        const fetchFollows = async () => {
            setListsLoading(true);
            setListsError('');
            try {
                const data = await Api.get('get_user_followed', { address });
                if (cancelled) return;
                setFollowedUsers(data?.followed_users || []);
                setFollowedTopics(data?.followed_topics || []);
            } catch (err) {
                if (!cancelled) {
                    setListsError(err?.message || 'Failed to load follows');
                }
            } finally {
                if (!cancelled) {
                    setListsLoading(false);
                }
            }
        };
        fetchFollows();
        return () => { cancelled = true; };
    }, [address]);

    useEffect(() => {
        const addresses = followedUsers
            .map(a => String(a || '').trim())
            .filter(Boolean);
        if (addresses.length === 0) {
            setFollowedUsernames({});
            return;
        }

        let cancelled = false;
        const resolveAll = async () => {
            try {
                const mapping = await resolveUsernamesCached(addresses, { timeoutMs: 5000 });
                if (cancelled) return;
                const result = {};
                for (const addr of addresses) {
                    const lower = String(addr || '').toLowerCase();
                    const uname = mapping[lower];
                    result[addr] = uname || addr;
                }
                setFollowedUsernames(result);
            } catch {
                if (cancelled) return;
                const result = {};
                addresses.forEach(a => { result[a] = a; });
                setFollowedUsernames(result);
            }
        };
        resolveAll();
        return () => { cancelled = true; };
    }, [followedUsers]);

    const handleUnfollowTopic = async (e, topic) => {
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        const topicTrimmed = String(topic || '').trim().toLowerCase();
        if (!topicTrimmed) return;
        try {
            const result = await tx.unfollowTopic(topicTrimmed);
            if (result && result.success) {
                setFollowedTopics((prev) => prev.filter(t => String(t || '').trim().toLowerCase() !== topicTrimmed));
                notifyTopicsUpdated({ removed: topicTrimmed });
            } else {
                alert(`Failed to unfollow topic: ${result?.error || 'Unknown error'}`);
            }
        } catch (error) {
            alert(`Error unfollowing topic: ${error?.message || error}`);
        }
    };

    const handleUnfollowUser = async (e, userAddr) => {
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        const userTrimmed = String(userAddr || '').trim().toLowerCase();
        if (!userTrimmed) return;
        try {
            await unfollow(address, userTrimmed);
            setFollowedUsers((prev) => prev.filter(u => String(u || '').trim().toLowerCase() !== userTrimmed));
            notifyUsersUpdated({ removed: userTrimmed });
        } catch (error) {
            alert(`Error unfollowing user: ${error?.message || error}`);
        }
    };

    return (
        <ContentGrid>
            <Helmet>
                <title>Follows | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow>
                            <ClickableTab $active>Follows</ClickableTab>
                        </TabsRow>
                        <ContainerBody>
                            <SectionTitle $first>Topics</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                {!listsLoading && !listsError && followedTopics.length === 0 && (
                                    <Mono style={{ color: '#888' }}>Not following any topics.</Mono>
                                )}
                                {!listsLoading && !listsError && followedTopics.length > 0 && (
                                    <PostsList>
                                        {followedTopics.map((topic) => {
                                            const isPending = isFollowTopicPending(topic);
                                            const status = formatFollowTopicStatus(topic);
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
                                                                minWidth="5.5rem"
                                                                disabled={isPending}
                                                                loading={isPending}
                                                                onClick={(e) => handleUnfollowTopic(e, topic)}
                                                            >
                                                                {status || 'Unfollow'}
                                                            </Button>
                                                        </BlockItemActions>
                                                    </BlockItemRow>
                                                </PostItem>
                                            );
                                        })}
                                    </PostsList>
                                )}
                            </ValueBox>

                            <SectionTitle>Users</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                {!listsLoading && listsError && <Mono style={{ color: '#f87171' }}>{listsError}</Mono>}
                                {!listsLoading && !listsError && followedUsers.length === 0 && (
                                    <Mono style={{ color: '#888' }}>Not following any users.</Mono>
                                )}
                                {!listsLoading && !listsError && followedUsers.length > 0 && (
                                    <PostsList>
                                        {followedUsers.map((userAddr) => {
                                            const isPending = isFollowUserPending(userAddr);
                                            const status = formatFollowUserStatus(userAddr);
                                            return (
                                                <PostItem
                                                    key={userAddr}
                                                    href={`/u/${encodeURIComponent(followedUsernames[userAddr] || userAddr)}?tab=posts`}
                                                    onClick={(e) => { if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) { e.preventDefault(); navigate(`/u/${encodeURIComponent(followedUsernames[userAddr] || userAddr)}?tab=posts`); } }}
                                                >
                                                    <BlockItemRow>
                                                        <BlockItemContent>
                                                            <PostPreview>
                                                                {followedUsernames[userAddr] && followedUsernames[userAddr] !== userAddr
                                                                    ? followedUsernames[userAddr]
                                                                    : shortenAddress(userAddr)}
                                                            </PostPreview>
                                                            <PostMeta>{userAddr}</PostMeta>
                                                        </BlockItemContent>
                                                        <BlockItemActions>
                                                            <Button
                                                                variant="ghost"
                                                                size="sm"
                                                                minWidth="5.5rem"
                                                                disabled={isPending}
                                                                loading={isPending}
                                                                onClick={(e) => handleUnfollowUser(e, userAddr)}
                                                            >
                                                                {status || 'Unfollow'}
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
