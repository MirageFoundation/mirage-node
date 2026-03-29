import { Helmet } from "react-helmet-async";
import styled, { useTheme } from "styled-components";
import { Navigate } from "react-router-dom";
import MobileHeader from "../components/MobileHeader.js";
import Button from "../components/Button.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../Layout";
import { getAuthorColor, getAuthorTooltip } from "../../../utils/tierColors";
import { formatMirage } from "../../../utils/formatters";
import { useInbox, formatAwardLabel } from "../../../logic/useInbox";
const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-end;
    margin: ${({
    theme
}) => theme.layout.containerPadding};
`;

// Using <a> tag so right-click "Open in new window" works natively
const ReplyItem = styled.a`
    display: block;
    text-decoration: none;
    color: inherit;
    padding: ${({
    theme
}) => theme.layout.cardPadding};
    margin-bottom: ${({
    theme
}) => theme.layout.formRowGap};
    background: ${({
    theme,
    $isUnread,
    $isActive
}) => {
        if ($isActive) return theme.colors.panelAlt;
        return $isUnread ? theme.colors.inboxReplyUnreadBg : theme.colors.inboxReplyReadBg;
    }};
    border-radius: ${({
        theme
    }) => theme.layout.cardRadius};
    font-size: 0.5rem;
    cursor: pointer;
    transition: background-color 0.2s;
    border: ${({
        theme,
        $isUnread,
        $isActive
    }) => {
        if (theme.caps.flatMode) return 'none';
        if ($isActive) return `1px solid ${theme.colors.accent}`;
        return `1px solid ${$isUnread ? theme.colors.inboxReplyUnreadBorder : theme.colors.inboxReplyReadBorder}`;
    }};
    border-bottom: ${({
        theme
    }) => theme.layout.cardBorderBottom};
    opacity: ${({
        theme,
        $isUnread,
        $isActive
    }) => theme.caps.flatMode ? '1' : $isActive || $isUnread ? '1' : '0.7'};

    &:hover {
        background-color: ${({
        theme,
        $isUnread,
        $isActive
    }) => {
        if ($isActive) return theme.colors.panelAlt;
        return $isUnread ? theme.colors.inboxReplyUnreadBgHover : theme.colors.inboxReplyReadBgHover;
    }};
        opacity: 1;
    }
    @media (max-width: 1000px) {
        padding: ${({
        theme
    }) => theme.layout.cardPadding};
        margin-bottom: ${({
        theme
    }) => theme.layout.formRowGap};
        border-radius: ${({
        theme
    }) => theme.layout.cardRadius};
    }
`;
const ReplyContentText = styled.div`
    color: ${({
    theme
}) => theme.colors.text};
    font-size: 0.6rem;
    white-space: pre-wrap;
    word-break: break-word;
    ${({
    theme
}) => theme.caps.flatMode ? `
        margin-left: 0.5rem;
        max-width: 700px;
    ` : ''}
`;
const MarkReadButton = styled.button`
    display: none;
    flex-shrink: 0;
    padding: 0.15rem 0.35rem;
    font-size: 0.5rem;
    font-weight: 600;
    background: ${({
    theme
}) => theme.layout.containerBg};
    color: ${({
    theme
}) => theme.caps.flatMode ? theme.colors.subtleText : theme.colors.text};
    border: ${({
    theme
}) => theme.layout.cardBorder};
    border-radius: 0;
    cursor: pointer;
    transition: all 0.15s ease;
    white-space: nowrap;

    &:hover {
        background: ${({
    theme
}) => theme.layout.containerBg};
        border-color: ${({
    theme
}) => theme.caps.flatMode ? 'transparent' : 'rgba(102, 126, 234, 0.5)'};
        text-decoration: ${({
    theme
}) => theme.caps.flatMode ? 'underline' : 'none'};
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
    font-weight: ${({
    $isUnread
}) => $isUnread ? 'bold' : 'normal'};
    color: ${({
    theme
}) => theme.colors.text};
    font-size: 0.6rem;
    line-height: 1.4;
    word-break: break-word;
    overflow-wrap: break-word;
    ${({
    theme
}) => theme.caps.flatMode ? `
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    ` : ''}
`;
const ReplyUsername = styled.span`
    color: ${({
    $tierColor,
    theme
}) => $tierColor} !important;
    font-weight: bold;
    position: relative;

    &::after {
        content: attr(data-tooltip);
        position: absolute;
        bottom: 100%;
        left: 0;
        margin-bottom: 0.3rem;
        background: ${({
    theme
}) => theme.colors.panel};
        border: 1px solid ${({
    theme
}) => theme.colors.border};
        color: ${({
    theme
}) => theme.colors.text};
        padding: ${({
    theme
}) => theme.layout.cardPadding};
        border-radius: 0;
        font-size: ${({
    theme
}) => theme.layout.smallSize};
        font-weight: normal;
        white-space: nowrap;
        z-index: 1000;
        box-shadow: none;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.15s ease;
    }

    &[data-tooltip]:hover::after {
        opacity: 1;
    }
`;
const ParentContent = styled.span`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: inherit;
    display: inline;
    word-break: break-word;
    overflow-wrap: break-word;
    white-space: normal;
`;
const Separator = styled.div`
    height: 1px;
    background: ${({
    theme
}) => theme.colors.border};
    margin: 0.25rem 0;
`;
const QuoteBlock = styled.blockquote`
    margin: 0.25rem 0 0 ${({
    theme
}) => theme.caps.flatMode ? '0.5rem' : '0'};
    padding: 0.25rem 0.4rem;
    border-left: 2px solid ${({
    theme
}) => theme.colors.border};
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.55rem;
    font-style: italic;
    line-height: 1.4;
    word-break: break-word;
    overflow-wrap: break-word;
`;
export default function InboxView({
    state
}) {
    const theme = useTheme();
    const inboxFullWidth = theme.caps.inboxFullWidth;
    const {
        replies,
        loading,
        error,
        hasMoreReplies,
        isLoadingMore,
        viewerAddress,
        activeReplyId,
        handleLoadMore,
        handleMarkAllAsRead,
        handleMarkOneAsRead,
        handleReplyClick,
        shortenAddress,
        viewedReplyIds,
        unreadCount,
        titleText,
        truncateWords
    } = useInbox({
        state
    });
    const renderShell = (body, heading) => <ContentGrid>
        <Helmet>
            <title>{heading || 'Inbox'} | Mirage</title>
        </Helmet>
        <div>
            <ModernPostFeed>
                <MobileHeader />
                <TabbedContainer>
                    <ContainerTab>{heading || 'Inbox'}</ContainerTab>
                    <ContainerBody $fullWidth={inboxFullWidth}>
                        {body}
                    </ContainerBody>
                </TabbedContainer>
            </ModernPostFeed>
        </div>
    </ContentGrid>;

    // Redirect non-logged-in users to home (shows welcome banner)
    if (!viewerAddress) {
        return <Navigate to="/home" replace />;
    }
    if (loading) {
        return renderShell(<div>Loading…</div>, 'Inbox');
    }
    if (error) {
        return renderShell(<div style={{
            color: '#f66'
        }}>{error}</div>, 'Inbox');
    }
    return renderShell(<>
        <HeaderRow>
            {replies.length > 0 && <Button variant={unreadCount > 0 ? "subtle" : "ghost"} size="sm" onClick={handleMarkAllAsRead}>Mark all as read</Button>}
        </HeaderRow>
        {replies.length === 0 && <div>No notifications yet.</div>}
        {replies.map(reply => {
            const isUnread = !viewedReplyIds.includes(reply.reply_id);
            const displayUsername = `@${reply.reply_username || shortenAddress(reply.reply_owner)}`;
            const isMention = reply.type === 'mention';
            const isAward = reply.type === 'award';
            const isFollow = reply.type === 'follow';
            const isDonation = reply.type === 'donation';
            const isSubscriptionGift = reply.type === 'subscription_gift';
            const awardLabel = isAward ? formatAwardLabel(reply.award_type) : '';
            const awardTarget = isAward && reply.root_post_id && reply.root_post_id === reply.reply_id ? 'post' : 'comment';
            const hasParent = Boolean(reply.parent_content);
            const actorIdentity = reply.reply_username || reply.reply_owner;
            const profileUrl = actorIdentity ? `/u/${encodeURIComponent(actorIdentity)}` : `/u/${encodeURIComponent(reply.reply_owner)}`;
            // Use new clean URL with depth=1 for reply with parent context
            const replyUrl = isFollow || isDonation || isSubscriptionGift ? profileUrl : `/p/${reply.reply_id}?depth=1`;
            const donationAmount = Number(reply.amount);
            const formattedDonation = Number.isFinite(donationAmount) ? formatMirage(donationAmount) : null;
            if (!Number.isFinite(donationAmount)) {
                console.error('[inbox] invalid donation amount', {
                    amount: reply.amount,
                    id: reply.reply_id
                });
            }
            return <ReplyItem key={`${reply.reply_id}_${reply.type || 'reply'}`} href={replyUrl} $isUnread={isUnread} $isActive={activeReplyId === reply.reply_id} onClick={e => {
                // Allow right-click, ctrl+click, cmd+click, middle-click to work natively
                if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                    e.preventDefault();
                    handleReplyClick(reply);
                }
            }}>
                <ReplyHeaderRow>
                    <ReplyHeader $isUnread={isUnread}>
                        {isAward ? <>Award received</> : isFollow ? <>
                            <ReplyUsername $tierColor={getAuthorColor(reply.reply_author_level, reply.reply_author_is_new)} data-tooltip={getAuthorTooltip(reply.reply_author_level, reply.reply_author_is_new)}>{displayUsername}</ReplyUsername>
                            {' followed you'}
                        </> : isDonation ? <>
                            <ReplyUsername $tierColor={getAuthorColor(reply.reply_author_level, reply.reply_author_is_new)} data-tooltip={getAuthorTooltip(reply.reply_author_level, reply.reply_author_is_new)}>{displayUsername}</ReplyUsername>
                            {' donated to you'}
                        </> : isSubscriptionGift ? <>
                            <ReplyUsername $tierColor={getAuthorColor(reply.reply_author_level, reply.reply_author_is_new)} data-tooltip={getAuthorTooltip(reply.reply_author_level, reply.reply_author_is_new)}>{displayUsername}</ReplyUsername>
                            {' gifted you a subscription'}
                        </> : <>
                            <ReplyUsername $tierColor={getAuthorColor(reply.reply_author_level, reply.reply_author_is_new)} data-tooltip={getAuthorTooltip(reply.reply_author_level, reply.reply_author_is_new)}>{displayUsername}</ReplyUsername>
                            {isMention ? ' mentioned you in ' : ' replied to '}
                            <ParentContent title={reply.parent_content}>{reply.parent_content}</ParentContent>:
                        </>}
                    </ReplyHeader>
                    {isUnread && <MarkReadButton onClick={e => handleMarkOneAsRead(e, reply)} title="Mark as read">
                        Mark read
                    </MarkReadButton>}
                </ReplyHeaderRow>
                <Separator />
                {isAward ? <ReplyContentText>
                    <ReplyUsername $tierColor={getAuthorColor(reply.reply_author_level, reply.reply_author_is_new)} data-tooltip={getAuthorTooltip(reply.reply_author_level, reply.reply_author_is_new)}>{displayUsername}</ReplyUsername>
                    {` gave you a "${awardLabel}" award for your ${awardTarget}`}
                    {hasParent && <>{': '}<ParentContent>{reply.parent_content}</ParentContent></>}
                    {reply.reply_content && <QuoteBlock>{truncateWords(reply.reply_content, 50)}</QuoteBlock>}
                </ReplyContentText> : isDonation ? formattedDonation ? <ReplyContentText>{`Amount: ${formattedDonation} MIRAGE`}</ReplyContentText> : <ReplyContentText>Invalid donation amount</ReplyContentText> : isFollow ? <ReplyContentText>View profile</ReplyContentText> : isSubscriptionGift ? <ReplyContentText>View profile</ReplyContentText> : reply.reply_content && <ReplyContentText>{reply.reply_content}</ReplyContentText>}
            </ReplyItem>;
        })}
        {hasMoreReplies && <Button variant="secondary" size="sm" fullWidth onClick={handleLoadMore} loading={isLoadingMore} style={{
            marginTop: '0.5rem'
        }}>
            Load more content
        </Button>}
    </>, titleText);
}