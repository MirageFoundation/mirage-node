import React, { useState, useEffect, useCallback } from 'react';
import { Helmet } from 'react-helmet-async';
import styled from 'styled-components';
import { useNavigate, useLocation, Navigate } from 'react-router-dom';
import Storage from '../utils/Storage';
import Api from '../lib/api';
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import MobileHeader from "../components/MobileHeader";
import Button from "../components/Button";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../styled/Layout";
import { getTierColor } from '../utils/tierColors';

const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-end;
    margin: 0.25rem 0 0.75rem 0;
`;

// Using <a> tag so right-click "Open in new window" works natively
const ReplyItem = styled.a`
    display: block;
    text-decoration: none;
    color: inherit;
    padding: 0.5rem;
    margin-bottom: 0.5rem;
    background: ${({ theme, $isUnread, $isActive }) => {
        if ($isActive) return theme?.colors?.panelAlt || 'rgba(250, 204, 21, 0.12)';
        return $isUnread
            ? (theme?.name === 'dark' ? 'rgba(59, 130, 246, 0.15)' : 'rgba(59, 130, 246, 0.08)')
            : (theme?.name === 'dark' ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.03)');
    }};
    border-radius: 6px;
    font-size: 0.5rem;
    cursor: pointer;
    transition: background-color 0.2s;
    border: 1px solid ${({ theme, $isUnread, $isActive }) => {
        if ($isActive) return theme?.colors?.accent || 'rgba(250, 204, 21, 0.8)';
        return $isUnread
            ? (theme?.name === 'dark' ? 'rgba(59, 130, 246, 0.4)' : 'rgba(59, 130, 246, 0.3)')
            : (theme?.name === 'dark' ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)');
    }};
    opacity: ${({ $isUnread, $isActive }) => ($isActive || $isUnread ? '1' : '0.7')};

    &:hover {
        background-color: ${({ theme, $isUnread, $isActive }) => {
        if ($isActive) return theme?.colors?.panelAlt || 'rgba(250, 204, 21, 0.15)';
        return $isUnread
            ? (theme?.name === 'dark' ? 'rgba(59, 130, 246, 0.2)' : 'rgba(59, 130, 246, 0.12)')
            : (theme?.name === 'dark' ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.05)');
    }};
        opacity: 1;
    }
    @media (max-width: 1000px) {
        padding: 0.35rem;
        margin-bottom: 0.35rem;
        border-radius: 4px;
    }
`;

const ReplyContentText = styled.div`
    color: ${({ theme }) => theme?.colors?.text || '#CCCCCC'};
    font-size: 0.6rem;
    white-space: pre-wrap;
    word-break: break-word;
`;

const MarkReadButton = styled.button`
    display: none;
    flex-shrink: 0;
    padding: 0.15rem 0.35rem;
    font-size: 0.5rem;
    font-weight: 600;
    background: rgba(102, 126, 234, 0.15);
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    border: 1px solid rgba(102, 126, 234, 0.3);
    border-radius: 3px;
    cursor: pointer;
    transition: all 0.15s ease;
    white-space: nowrap;

    &:hover {
        background: rgba(102, 126, 234, 0.25);
        border-color: rgba(102, 126, 234, 0.5);
    }

    @media (min-width: 1001px) {
        display: block;
    }
`;

const ReplyHeaderRow = styled.div`
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    margin-bottom: 0.25rem;
`;

const ReplyHeader = styled.div`
    flex: 1;
    min-width: 0;
    font-weight: ${({ $isUnread }) => ($isUnread ? 'bold' : 'normal')};
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-size: 0.6rem;
    line-height: 1.4;
    word-break: break-word;
    overflow-wrap: break-word;
`;

const ReplyUsername = styled.span`
    color: ${({ $tierColor, theme }) => $tierColor || theme?.colors?.link || '#FFFFFF'} !important;
    font-weight: bold;
`;

const ParentContent = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    font-size: inherit;
    display: inline;
    word-break: break-word;
    overflow-wrap: break-word;
    white-space: normal;
`;

const Separator = styled.div`
    height: 1px;
    background: ${({ theme }) => theme?.colors?.border || '#444'};
    margin: 0.25rem 0;
`;

// removed unused Actions

export default function InboxView({ state }) {
    const navigate = useNavigate();
    const location = useLocation();
    const [replies, setReplies] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [currentPage, setCurrentPage] = useState(1);
    const [hasMoreReplies, setHasMoreReplies] = useState(false);
    const [isLoadingMore, setIsLoadingMore] = useState(false);
    const viewerAddress = Storage.load('publicKey', '');
    const [activeReplyId, setActiveReplyId] = useState('');

    const fetchInbox = useCallback(async (page = 1, append = false) => {
        if (!viewerAddress) {
            setLoading(false);
            setReplies([]);
            return;
        }

        try {
            if (page === 1) {
                setLoading(true);
            } else {
                setIsLoadingMore(true);
            }

            const res = await Api.get('get_inbox', {
                address: viewerAddress,
                page,
                limit: 25
            }, { timeoutMs: 10000 });

            if (res && Array.isArray(res.replies)) {
                if (append) {
                    setReplies(prev => [...prev, ...res.replies]);
                } else {
                    setReplies(res.replies);
                }
                setHasMoreReplies(res.has_more || false);
                setError('');

                const viewedReplyIds = Storage.getViewedReplyIds();
                const unreadCount = res.replies.reduce((acc, r) => acc + (viewedReplyIds.includes(r.reply_id) ? 0 : 1), 0);
                Storage.save('inbox_unread_count', unreadCount);
                const latestTs = res.replies.length ? Math.max(...res.replies.map(r => r.reply_timestamp || 0)) : 0;
                if (latestTs > 0) {
                    Storage.save('inbox_latest_ts', latestTs);
                }
                window.dispatchEvent(new CustomEvent('inboxUpdated', { detail: { unreadCount, latestTs } }));
            } else {
                setError('Invalid response from server');
            }
        } catch (e) {
            setError(String(e && e.message ? e.message : 'Failed to load inbox'));
        } finally {
            setLoading(false);
            setIsLoadingMore(false);
        }
    }, [viewerAddress]);

    useEffect(() => {
        fetchInbox(1, false);
    }, [fetchInbox]);

    const handleLoadMore = () => {
        const nextPage = currentPage + 1;
        setCurrentPage(nextPage);
        fetchInbox(nextPage, true);
    };

    const handleMarkAllAsRead = () => {
        const allReplyIds = replies.map(r => r.reply_id);
        Storage.markAllRepliesAsViewed(allReplyIds);
        setReplies(prev => prev.map(r => ({ ...r, isUnread: false })));
        const latestTs = replies.length ? Math.max(...replies.map(r => r.reply_timestamp || 0)) : 0;
        Storage.save('inbox_unread_count', 0);
        if (latestTs > 0) {
            Storage.save('inbox_last_viewed_at', String(latestTs));
            Storage.save('inbox_latest_ts', latestTs);
        }
        window.dispatchEvent(new CustomEvent('inboxUpdated', { detail: { unreadCount: 0, latestTs } }));
    };

    const handleMarkOneAsRead = (e, reply) => {
        e.preventDefault();
        e.stopPropagation();
        Storage.addViewedReplyId(reply.reply_id);
        const newViewedIds = Storage.getViewedReplyIds();
        const newUnreadCount = replies.reduce((acc, r) => acc + (newViewedIds.includes(r.reply_id) ? 0 : 1), 0);
        Storage.save('inbox_unread_count', newUnreadCount);
        if (newUnreadCount === 0) {
            const latestTs = replies.length ? Math.max(...replies.map(r => r.reply_timestamp || 0)) : 0;
            if (latestTs > 0) {
                Storage.save('inbox_last_viewed_at', String(latestTs));
                Storage.save('inbox_latest_ts', latestTs);
            }
            window.dispatchEvent(new CustomEvent('inboxUpdated', { detail: { unreadCount: 0, latestTs } }));
        } else {
            window.dispatchEvent(new CustomEvent('inboxUpdated', { detail: { unreadCount: newUnreadCount } }));
        }
        setReplies(prev => [...prev]);
    };

    const handleReplyClick = (reply) => {
        if (!reply) return;
        Storage.addViewedReplyId(reply.reply_id);
        if (reply.root_post_id) {
            try {
                Storage.setPendingPostHighlight(reply.reply_id);
            } catch (_) { }
            setActiveReplyId(reply.reply_id);
        }
        // Update unread count and last viewed when all read
        const viewedReplyIds = Storage.getViewedReplyIds();
        const unreadCount = replies.reduce((acc, r) => acc + (viewedReplyIds.includes(r.reply_id) ? 0 : 1), 0);
        Storage.save('inbox_unread_count', unreadCount);
        if (unreadCount === 0) {
            const latestTs = replies.length ? Math.max(...replies.map(r => r.reply_timestamp || 0)) : (reply.reply_timestamp || 0);
            if (latestTs > 0) {
                Storage.save('inbox_last_viewed_at', String(latestTs));
                Storage.save('inbox_latest_ts', latestTs);
            }
            window.dispatchEvent(new CustomEvent('inboxUpdated', { detail: { unreadCount: 0, latestTs } }));
        } else {
            window.dispatchEvent(new CustomEvent('inboxUpdated', { detail: { unreadCount } }));
        }
        navigate(`/view_post?post_id=${reply.root_post_id}#comment-${reply.reply_id}`);
    };

    const shortenAddress = (addr) => {
        if (!addr) return '';
        return `${addr.slice(0, 10)}…${addr.slice(-4)}`;
    };

    // removed unused formatTime

    const viewedReplyIds = Storage.getViewedReplyIds();
    const unreadCount = replies.reduce((acc, r) => acc + (viewedReplyIds.includes(r.reply_id) ? 0 : 1), 0);

    const titleText = unreadCount > 0 ? `Inbox (${unreadCount} unread)` : 'Inbox';

    const renderShell = (body, heading) => (
        <ContentGrid>
            <Helmet>
                <title>{heading || 'Inbox'} | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerTab>{heading || 'Inbox'}</ContainerTab>
                        <ContainerBody>
                            {body}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );

    // Redirect non-logged-in users to home (shows welcome banner)
    if (!viewerAddress) {
        return <Navigate to="/home" replace />;
    }

    if (loading) {
        return renderShell(
            <div>Loading…</div>,
            'Inbox'
        );
    }

    if (error) {
        return renderShell(
            <div style={{ color: '#f66' }}>{error}</div>,
            'Inbox'
        );
    }

    return renderShell(
        <>
            <HeaderRow>
                {replies.length > 0 && (
                    <Button variant={unreadCount > 0 ? "subtle" : "ghost"} size="sm" onClick={handleMarkAllAsRead}>Mark all as read</Button>
                )}
            </HeaderRow>
            {replies.length === 0 && <div>No replies yet.</div>}
            {replies.map((reply) => {
                const isUnread = !viewedReplyIds.includes(reply.reply_id);
                const displayUsername = `@${reply.reply_username || shortenAddress(reply.reply_owner)}`;
                const replyUrl = `/view_post?post_id=${reply.root_post_id}#comment-${reply.reply_id}`;
                return (
                    <ReplyItem
                        key={reply.reply_id}
                        href={replyUrl}
                        $isUnread={isUnread}
                        $isActive={activeReplyId === reply.reply_id}
                        onClick={(e) => {
                            // Allow right-click, ctrl+click, cmd+click, middle-click to work natively
                            if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                e.preventDefault();
                                handleReplyClick(reply);
                            }
                        }}
                    >
                        <ReplyHeaderRow>
                            <ReplyHeader $isUnread={isUnread}>
                                <ReplyUsername $tierColor={getTierColor(reply.reply_author_level)}>{displayUsername}</ReplyUsername> replied to <ParentContent title={reply.parent_content}>{reply.parent_content}</ParentContent>:
                            </ReplyHeader>
                            {isUnread && (
                                <MarkReadButton
                                    onClick={(e) => handleMarkOneAsRead(e, reply)}
                                    title="Mark as read"
                                >
                                    Mark read
                                </MarkReadButton>
                            )}
                        </ReplyHeaderRow>
                        <Separator />
                        <ReplyContentText>{reply.reply_content}</ReplyContentText>
                    </ReplyItem>
                );
            })}
            {hasMoreReplies && (
                <Button
                    variant="secondary"
                    size="sm"
                    fullWidth
                    onClick={handleLoadMore}
                    loading={isLoadingMore}
                    style={{ marginTop: '0.5rem' }}
                >
                    Load more content
                </Button>
            )}
        </>,
        titleText
    );
}

