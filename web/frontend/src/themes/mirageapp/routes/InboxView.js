import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { Navigate } from "react-router-dom";
import {
    HiArrowUturnLeft,
    HiAtSymbol,
    HiGift,
    HiUserPlus,
    HiSparkles,
    HiOutlineBellAlert,
    HiExclamationTriangle,
} from "react-icons/hi2";
import { ListRowSkeletonList, PageHeaderSkeleton } from "../components/Skeleton.js";
import ShowMoreButton from "../components/ShowMoreButton.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../Layout";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import FeedRightRail from "../components/FeedRightRail.js";
import { getAuthorColor, getAuthorTooltip } from "../../../utils/tierColors";
import { formatMirage } from "../../../utils/formatters";
import { useInbox, formatAwardLabel } from "../../../logic/useInbox";
import { formatTimeAgo } from "../../../logic/useAgents";
import InlineMedia from "../components/InlineMedia";
import { isLikelyImageUrl, isLikelyVideoUrl } from "../../../utils/media";

/**
 * InboxView — `mirageapp` Plan 05 sub-plan 01.
 *
 * Follows `docs/guides/web-theme-mirageapp/RULES.md`:
 *  - R1 rows sit directly on `theme.colors.bg`; unread rows get a
 *    primary-blue tint via `inboxReplyUnreadBg`.
 *  - R2 every color routed through a token (no raw hex/rgb).
 *  - R3 rows are full-bleed divided by `1px solid theme.colors.border`
 *    — the same divider used by the feed.
 *  - R4 data parity with `themes/bluemoon/routes/InboxView.js`; visual
 *    parity with `mirage-mobile-app/src/components/molecules/inbox-item.tsx`
 *    (no avatar, action icon on the left, time-ago on the right).
 */

/**
 * `InboxWrap` caps the inbox at the card-view feed width (820px) by
 * default and left-aligns it in the content column. When the sidebar is
 * hidden on desktop, it expands like `ListFeedView`'s compact view
 * (width 80%, no max-width cap) but stays pinned to the LEFT — no auto
 * margins — per user preference.
 */
const InboxWrap = styled.div`
    width: 100%;
    max-width: 820px;
    /* Pull the inbox up under the TopBar — cancels the top half of
     * ContainerBody's vertical padding without touching the shared
     * theme layout token (which would affect every route). */
    margin: -0.75rem 0 0;

    @media (max-width: 1000px) {
        margin-top: -0.5rem;
    }

    @media (min-width: 1500px) {
        max-width: 960px;
    }
`;

const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.75rem;
    padding: 0.25rem 1rem 0.5rem;
`;

const HeaderTitle = styled.div`
    display: flex;
    align-items: center;
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

/**
 * Sub-row beneath the header showing the unread count on the left and the
 * "Mark all as read" button on the right. Uses the standard feed divider.
 */
const UnreadInfoRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.4rem 1rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const UnreadCountText = styled.span`
    font-size: 0.65rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
`;

/**
 * Header "Mark all as read" button. Per UI review:
 *  - no background hover (transparent always)
 *  - no leading icon
 *  - rest text uses `sidebarItemText` (rgb 221,228,232 dark / rgb 34,39,42 light)
 *  - hover text uses `sidebarItemActiveText` (white dark / black light)
 */
const MarkAllButton = styled.button`
    display: inline-flex;
    align-items: center;
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
    font-family: inherit;
    font-size: 0.68rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.inboxMarkAllText};
    cursor: pointer;
    transition: color 0.15s ease;

    &:hover:not(:disabled) {
        color: ${({ theme }) => theme.colors.sidebarItemActiveText};
        background: transparent;
    }

    &:disabled {
        opacity: 0.45;
        cursor: default;
    }
`;

const ReplyList = styled.div`
    display: flex;
    flex-direction: column;
`;

/* Rows are full-bleed; the only separator is the feed divider (R3). */
const ReplyItem = styled.a`
    display: block;
    text-decoration: none;
    color: inherit;
    padding: 0.5rem 1rem;
    background: ${({ theme, $isUnread, $isActive }) => {
        if ($isActive) return theme.colors.panelAlt;
        return $isUnread ? theme.colors.inboxReplyUnreadBg : theme.colors.inboxReplyReadBg;
    }};
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    cursor: pointer;
    transition: background-color 0.15s ease;

    &:hover {
        background: ${({ theme, $isUnread, $isActive }) => {
        if ($isActive) return theme.colors.panelAlt;
        return $isUnread ? theme.colors.inboxReplyUnreadBgHover : theme.colors.inboxReplyReadBgHover;
    }};
    }

    &:hover .mark-read {
        opacity: 1;
        pointer-events: auto;
    }

    @media (max-width: 600px) {
        padding: 0.45rem 0.85rem;
    }
`;

const HeaderTextRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.55rem;
    margin-bottom: ${({ $hasContent }) => ($hasContent ? '0.25rem' : '0')};
`;

const ActionIcon = styled.span`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-top: 0.05rem;
    color: ${({ theme }) => theme.colors.subtleText};

    svg {
        width: 18px;
        height: 18px;
    }
`;

const HeaderTextBlock = styled.div`
    flex: 1;
    min-width: 0;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.7rem;
    line-height: 1.45;
    font-weight: ${({ $isUnread }) => ($isUnread ? 600 : 400)};
    word-break: break-word;
    overflow-wrap: break-word;

    @media (max-width: 600px) {
    }
`;

const ReplyUsername = styled.span`
    color: ${({ $tierColor }) => $tierColor || 'inherit'} !important;
    font-weight: 700;
    position: relative;

    &::after {
        content: attr(data-tooltip);
        position: absolute;
        bottom: 100%;
        left: 0;
        margin-bottom: 0.3rem;
        background: ${({ theme }) => theme.colors.panel};
        border: 1px solid ${({ theme }) => theme.colors.border};
        color: ${({ theme }) => theme.colors.text};
        padding: 0.25rem 0.4rem;
        border-radius: 6px;
        font-size: 0.65rem;
        font-weight: 500;
        white-space: nowrap;
        z-index: 1000;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.15s ease;
    }

    &[data-tooltip]:hover::after {
        opacity: 1;
    }
`;

const ActionText = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-weight: 500;
`;

const ParentPreview = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-weight: 500;
    word-break: break-word;
    overflow-wrap: break-word;
`;

const TimeText = styled.span`
    flex-shrink: 0;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.45;
    white-space: nowrap;
`;

/**
 * Body row container that holds the reply text (or donation / quote /
 * placeholder) on the left and the per-row "Mark read" pill on the right.
 * This is the "2nd row" of the unread reply card — timestamp stays in the
 * header row above, and the mark-read action sits beside the body so they
 * share a single line. When no body is present we still render this row
 * for unread items so the pill has a home (e.g. follow / subscription
 * gift events).
 */
const BodyRow = styled.div`
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 0.5rem;
    margin-left: 1.65rem;

    @media (max-width: 600px) {
        margin-left: 1.55rem;
    }

    /* Body blocks inside BodyRow must drop their own indent since the
     * row itself already provides it. */
    & > *:first-child {
        margin-left: 0;
        flex: 1;
        min-width: 0;
    }
`;

/**
 * Per-row "Mark read" pill. Hidden by default (opacity 0) and revealed
 * on hover of the enclosing `ReplyItem`. Transparent at rest with an
 * invisible border so the size stays constant — on hover the border
 * lifts to a visible neutral outline (no blue) and text pops to active.
 */
const MarkReadButton = styled.button.attrs({ className: 'mark-read' })`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.15rem 0.5rem;
    font-family: inherit;
    font-size: 0.55rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.sidebarItemText};
    background: transparent;
    border: 1px solid transparent;
    border-radius: 999px;
    cursor: pointer;
    white-space: nowrap;
    opacity: 0;
    pointer-events: none;
    transition: color 0.15s ease, border-color 0.15s ease, opacity 0.15s ease;

    &:hover {
        color: ${({ theme }) => theme.colors.sidebarItemActiveText};
        border-color: ${({ theme }) => theme.colors.followBtnBorder};
    }

    /* Always visible on mobile (no hover). */
    @media (max-width: 600px) {
        opacity: 1;
        pointer-events: auto;
    }
`;

const ReplyContent = styled.div`
    margin-left: 1.65rem; /* aligns under the header text (icon width + gap) */
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.68rem;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;

    @media (max-width: 600px) {
        margin-left: 1.55rem;
    }

    /* Stack plain-text fragments and inline media vertically so a GIF
     * or image embedded in a reply renders as its own block instead of
     * fighting with the surrounding prose on a single flex line. */
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
`;

/* Wraps an `InlineMedia` block inside an inbox row so images / GIFs /
 * videos stay capped to the reply column width with a soft rounded
 * border — matches the look of media blocks inside feed cards. */
const InboxMediaWrap = styled.div`
    max-width: 320px;
    max-height: 240px;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.surface2};
    display: block;

    img, video {
        max-width: 100%;
        max-height: 240px;
        display: block;
    }
`;

const DonationAmount = styled.div`
    margin-left: 1.65rem;
    /* Match the regular ReplyContent body metrics (size / weight /
     * line-height) so donation rows do not read as visually heavier
     * than every other inbox message. Color stays on the shared
     * voteUp green token (#16A34A) used for positive-amount
     * indicators across the app (vote pills, success banners, quest
     * claim state). */
    color: ${({ theme }) => theme.colors.voteUp};
    font-size: 0.68rem;
    line-height: 1.5;

    @media (max-width: 600px) {
        margin-left: 1.55rem;
    }
`;

const QuoteBlock = styled.blockquote`
    margin: 0.25rem 0 0 1.65rem;
    padding: 0.25rem 0.55rem;
    border-left: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.64rem;
    font-style: italic;
    line-height: 1.5;
    word-break: break-word;
    overflow-wrap: break-word;

    @media (max-width: 600px) {
        margin-left: 1.55rem;
    }
`;

/* ----- State blocks (empty / loading / error) ----- */

const StateBlock = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
    padding: 3rem 1.25rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const StateIcon = styled.div`
    width: 52px;
    height: 52px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 1px solid ${({ theme }) => theme.colors.border};

    svg {
        width: 24px;
        height: 24px;
        color: ${({ $tone, theme }) => ($tone === 'danger' ? theme.colors.voteDown : theme.colors.subtleText)};
    }
`;

const StateTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.95rem;
    font-weight: 700;
`;

const StateMessage = styled.div`
    font-size: 0.8rem;
    line-height: 1.55;
    max-width: 24rem;
    color: ${({ theme }) => theme.colors.subtleText};
`;

/* ----- Action icon mapping (mirrors mobile `inbox-item.tsx`). ----- */

function getActionIcon(type) {
    switch (type) {
        case 'mention':
            return HiAtSymbol;
        case 'award':
            return HiGift;
        case 'donation':
            return HiGift;
        case 'follow':
            return HiUserPlus;
        case 'subscription_gift':
            return HiSparkles;
        default:
            return HiArrowUturnLeft;
    }
}

const PARENT_PREVIEW_MAX = 80;
function truncateParent(content) {
    if (!content) return '';
    const single = String(content).replace(/\s+/g, ' ').trim();
    if (single.length <= PARENT_PREVIEW_MAX) return single;
    return single.slice(0, PARENT_PREVIEW_MAX).trimEnd() + '…';
}

/* Pull every http(s) URL out of a content string. Returns a list of
 * `{ type, url, start, end }` tokens for URLs that look like image or
 * video media, along with the raw indices so we can splice them out of
 * the text when rendering. Non-media URLs are ignored here and left in
 * the text (rendered as plain text / clickable link by the caller). */
function extractInboxMediaTokens(content) {
    if (!content) return [];
    const out = [];
    const re = /https?:\/\/[^\s<>"')]+/g;
    let m;
    while ((m = re.exec(content)) !== null) {
        const url = m[0].replace(/[.,;:!?)]+$/, '');
        const start = m.index;
        const end = start + url.length;
        if (isLikelyImageUrl(url)) out.push({ type: 'image', url, start, end });
        else if (isLikelyVideoUrl(url)) out.push({ type: 'video', url, start, end });
    }
    return out;
}

/* Render inbox reply / parent body text with inline image/GIF/video
 * previews instead of a raw link. Bare media URLs (gif, jpg, mp4,
 * cloudflarestream, imagedelivery, youtube, redgifs, …) become an
 * InlineMedia block; non-media text stays on its own line. Multiple
 * media URLs in a single message render as multiple thumbnails stacked
 * vertically — matching how the feed card view renders them. */
function renderInboxBody(content) {
    if (!content || typeof content !== 'string') return null;
    const tokens = extractInboxMediaTokens(content);
    if (tokens.length === 0) return content;
    const parts = [];
    let cursor = 0;
    tokens.forEach((tok, idx) => {
        if (tok.start > cursor) {
            const text = content.slice(cursor, tok.start).trim();
            if (text) parts.push(<span key={`t-${idx}`}>{text}</span>);
        }
        parts.push(
            <InboxMediaWrap key={`m-${idx}`} onClick={e => e.stopPropagation()}>
                <InlineMedia url={tok.url} />
            </InboxMediaWrap>
        );
        cursor = tok.end;
    });
    if (cursor < content.length) {
        const tail = content.slice(cursor).trim();
        if (tail) parts.push(<span key="t-tail">{tail}</span>);
    }
    return parts;
}

export default function InboxView({ state }) {
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
        truncateWords
    } = useInbox({ state });

    const renderShell = (body, heading) => (
        <ContentGrid>
            <Helmet>
                <title>{heading || 'Inbox'} | Mirage</title>
            </Helmet>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
                    <ModernPostFeed>
                        <TabbedContainer>
                            <ContainerTab>Inbox</ContainerTab>
                            <ContainerBody $fullWidth>
                                <InboxWrap>{body}</InboxWrap>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </FeedCol>
                <FeedRightRail />
            </FeedRailRow>
        </ContentGrid>
    );

    // Redirect non-logged-in users to home (shows welcome banner)
    if (!viewerAddress) {
        return <Navigate to="/home" replace />;
    }

    if (loading) {
        return renderShell(
            <>
                <PageHeaderSkeleton />
                <ListRowSkeletonList count={6} />
            </>
        );
    }

    if (error) {
        return renderShell(
            <StateBlock role="alert">
                <StateIcon $tone="danger">
                    <HiExclamationTriangle />
                </StateIcon>
                <StateTitle>Couldn’t load your inbox</StateTitle>
                <StateMessage>{error}</StateMessage>
            </StateBlock>
        );
    }

    const headerBlock = (
        <>
            <HeaderRow>
                <HeaderTitle>Inbox</HeaderTitle>
            </HeaderRow>
            {replies.length > 0 && (
                <UnreadInfoRow>
                    <UnreadCountText>
                        {unreadCount === 0 ? 'No unread' : `${unreadCount} unread`}
                    </UnreadCountText>
                    <MarkAllButton
                        type="button"
                        onClick={handleMarkAllAsRead}
                        disabled={unreadCount === 0}
                        title="Mark all as read"
                    >
                        Mark all as read
                    </MarkAllButton>
                </UnreadInfoRow>
            )}
        </>
    );

    if (replies.length === 0) {
        return renderShell(
            <>
                {headerBlock}
                <StateBlock>
                    <StateIcon>
                        <HiOutlineBellAlert />
                    </StateIcon>
                    <StateTitle>No replies yet</StateTitle>
                    <StateMessage>
                        When someone replies to your posts or comments, follows you, or sends you an award, it will show up here.
                    </StateMessage>
                </StateBlock>
            </>
        );
    }

    return renderShell(
        <>
            {headerBlock}
            <ReplyList>
                {replies.map(reply => {
                    const isUnread = !viewedReplyIds.includes(reply.reply_id);
                    const displayUsername = `@${reply.reply_username || shortenAddress(reply.reply_owner)}`;
                    const isMention = reply.type === 'mention';
                    const isAward = reply.type === 'award';
                    const isFollow = reply.type === 'follow';
                    const isDonation = reply.type === 'donation';
                    const isSubscriptionGift = reply.type === 'subscription_gift';
                    const isSpecialEvent = isFollow || isDonation || isSubscriptionGift;
                    const awardLabel = isAward ? formatAwardLabel(reply.award_type) : '';
                    const awardTarget = isAward && reply.root_post_id && reply.root_post_id === reply.reply_id ? 'post' : 'comment';
                    const parentPreview = truncateParent(reply.parent_content);
                    const actorIdentity = reply.reply_username || reply.reply_owner;
                    const profileUrl = actorIdentity ? `/u/${encodeURIComponent(actorIdentity)}` : `/u/${encodeURIComponent(reply.reply_owner)}`;
                    const replyUrl = isSpecialEvent ? profileUrl : `/p/${reply.reply_id}?depth=1`;
                    const donationAmount = Number(reply.amount);
                    const formattedDonation = Number.isFinite(donationAmount) ? formatMirage(donationAmount) : null;
                    if (isDonation && !Number.isFinite(donationAmount)) {
                        console.error('[inbox] invalid donation amount', {
                            amount: reply.amount,
                            id: reply.reply_id
                        });
                    }
                    const tierColor = getAuthorColor(reply.reply_author_level, reply.reply_author_is_new);
                    const tierTooltip = getAuthorTooltip(reply.reply_author_level, reply.reply_author_is_new);
                    const timeAgo = reply.reply_timestamp ? formatTimeAgo(reply.reply_timestamp) : null;

                    const Icon = getActionIcon(reply.type);

                    // Build the action label + inline parent preview (bluemoon parity).
                    let actionLabel;
                    if (isAward) {
                        actionLabel = ` gave you a “${awardLabel}” award for your ${awardTarget}`;
                    } else if (isDonation) {
                        actionLabel = ' donated to you';
                    } else if (isFollow) {
                        actionLabel = ' followed you';
                    } else if (isSubscriptionGift) {
                        actionLabel = ' gifted you a subscription';
                    } else if (isMention) {
                        actionLabel = ' mentioned you in ';
                    } else {
                        actionLabel = ' replied to ';
                    }

                    // Determine body content (indented under header, like mobile).
                    let bodyNode = null;
                    if (isAward) {
                        bodyNode = (
                            <>
                                {reply.parent_content && (
                                    <ReplyContent>
                                        <ParentPreview>{renderInboxBody(reply.parent_content)}</ParentPreview>
                                    </ReplyContent>
                                )}
                                {reply.reply_content && (
                                    <QuoteBlock>{renderInboxBody(truncateWords(reply.reply_content, 50))}</QuoteBlock>
                                )}
                            </>
                        );
                    } else if (isDonation) {
                        bodyNode = (
                            <DonationAmount>
                                {formattedDonation ? `${formattedDonation} MIRAGE` : 'Invalid donation amount'}
                            </DonationAmount>
                        );
                    } else if (reply.reply_content && !isSpecialEvent) {
                        bodyNode = <ReplyContent>{renderInboxBody(reply.reply_content)}</ReplyContent>;
                    }
                    const hasBody = Boolean(bodyNode);

                    return (
                        <ReplyItem
                            key={`${reply.reply_id}_${reply.type || 'reply'}`}
                            href={replyUrl}
                            $isUnread={isUnread}
                            $isActive={activeReplyId === reply.reply_id}
                            onClick={e => {
                                // Allow right-click / cmd-click / middle-click to work natively.
                                if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                    e.preventDefault();
                                    handleReplyClick(reply);
                                }
                            }}
                        >
                            <HeaderTextRow $hasContent={hasBody}>
                                <ActionIcon>
                                    <Icon />
                                </ActionIcon>
                                <HeaderTextBlock $isUnread={isUnread}>
                                    <ReplyUsername $tierColor={tierColor} data-tooltip={tierTooltip}>
                                        {displayUsername}
                                    </ReplyUsername>
                                    <ActionText>{actionLabel}</ActionText>
                                    {!isSpecialEvent && !isAward && parentPreview && (
                                        <ParentPreview>“{parentPreview}”</ParentPreview>
                                    )}
                                </HeaderTextBlock>
                                {timeAgo && <TimeText>{timeAgo}</TimeText>}
                            </HeaderTextRow>
                            {(hasBody || isUnread) && (
                                <BodyRow>
                                    {hasBody ? bodyNode : <span />}
                                    {isUnread && (
                                        <MarkReadButton
                                            onClick={e => handleMarkOneAsRead(e, reply)}
                                            title="Mark as read"
                                            aria-label="Mark as read"
                                        >
                                            Mark read
                                        </MarkReadButton>
                                    )}
                                </BodyRow>
                            )}
                        </ReplyItem>
                    );
                })}
            </ReplyList>
            {hasMoreReplies && (
                <ShowMoreButton onClick={handleLoadMore} loading={isLoadingMore} spacing="loose">
                    Show more
                </ShowMoreButton>
            )}
        </>
    );
}
