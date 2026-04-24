import { useState } from "react";
import { Helmet } from "react-helmet-async";
import { Navigate, useLocation } from "react-router-dom";
import styled from "styled-components";
import {
    HiHashtag,
    HiUsers,
    HiDocumentText,
    HiExclamationTriangle,
    HiNoSymbol,
} from "react-icons/hi2";
import Button from "../components/Button.js";
import {
    ContentGrid,
    ModernPostFeed,
    TabbedContainer,
    ContainerBody,
} from "../Layout";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import FeedRightRail from "../components/FeedRightRail.js";
import { useBlocks, shortenAddress } from "../../../logic/useBlocks";
import { dicebearAvatarUrl } from "../../../utils/avatar";

/** See FollowsView for the dev-only `?_state=loading|error|empty` trigger. */
function useDebugStateOverride() {
    const location = useLocation();
    const params = new URLSearchParams(location.search || "");
    return params.get("_state") || null;
}

/**
 * BlocksView — `mirageapp` Plan 06 sub-plan 03.
 *
 * Rules applied: R1 rows sit on `bg`; R2 all tokens; R3 rows divided by
 * `1px solid theme.colors.border`; R4 data parity with bluemoon; R7 row
 * title 0.78rem/600, meta 0.62rem/500.
 *
 * Action: `Unblock` via the danger variant of `Button` per sub-plan 06.3.
 */

const BlocksWrap = styled.div`
    width: 100%;
    max-width: 820px;
    margin: -0.75rem 0 0;

    @media (max-width: 1000px) {
        margin-top: -0.5rem;
    }

    @media (min-width: 1500px) {
        max-width: 960px;
    }

    @media (min-width: 1900px) {
        max-width: 1200px;
    }
`;

const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.75rem;
    padding: 0.25rem 1rem 0.5rem;

    @media (max-width: 600px) {
        padding: 0.25rem 0 0.5rem;
    }
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
 * Tabs match the SearchResultsView style — equal-width grid columns +
 * animated `TabIndicator` underline (R3 single-divider rule).
 */
const TabsRow = styled.div`
    position: relative;
    display: grid;
    grid-template-columns: repeat(${({ $count }) => $count || 3}, 1fr);
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const TabButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.3rem;
    padding: 0.55rem 0.5rem;
    background: transparent;
    border: none;
    font-family: inherit;
    font-size: 0.72rem;
    font-weight: 500;
    color: ${({ $active, theme }) => ($active ? theme.colors.text : theme.colors.subtleText)};
    cursor: pointer;
    transition: color 0.15s ease;

    &:hover {
        color: ${({ theme }) => theme.colors.text};
    }
`;

const TabIndicator = styled.div`
    position: absolute;
    bottom: -1px;
    left: 0;
    width: calc(100% / ${({ $count }) => $count || 3});
    height: 2px;
    background: ${({ theme }) => theme.colors.focusBlue};
    transform: translateX(${({ $index }) => `${$index * 100}%`});
    transition: transform 0.2s ease;
`;

const TabCount = styled.span`
    color: inherit;
    font-size: 0.68rem;
    font-weight: 500;
    line-height: 1;
    opacity: 0.75;
`;

const List = styled.div`
    display: flex;
    flex-direction: column;
`;

/** Row is a `<div>` (not `<a>`) so the inner Unblock `<Button>` owns its
 *  click without browser anchor activation. See FollowsView for the same
 *  pattern + cmd/ctrl-click open-in-new-tab handling. */
const Row = styled.div`
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.55rem 1rem;
    text-decoration: none;
    color: inherit;
    background: transparent;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    cursor: pointer;
    transition: background-color 0.15s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    @media (max-width: 600px) {
        padding: 0.5rem 0;
    }
`;

const AvatarImg = styled.img`
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: ${({ theme }) => theme.colors.surface3};
    object-fit: cover;
    flex-shrink: 0;
    display: block;
`;

const LeadingIcon = styled.span`
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: ${({ theme }) => theme.colors.surface2};
    border: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.subtleText};
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;

    svg {
        width: 16px;
        height: 16px;
    }
`;

const Identity = styled.div`
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
`;

const IdentityTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.78rem;
    font-weight: 600;
    line-height: 1.25;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const IdentityMeta = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.25;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
`;

const RowActions = styled.div`
    flex-shrink: 0;
    display: flex;
    align-items: center;
`;

/* ----- State blocks (mirror InboxView). ----- */

const StateBlock = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.6rem;
    padding: 2.5rem 1.25rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const StateIcon = styled.div`
    width: 48px;
    height: 48px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 1px solid ${({ theme }) => theme.colors.border};

    svg {
        width: 22px;
        height: 22px;
        color: ${({ $tone, theme }) => ($tone === 'danger' ? theme.colors.voteDown : theme.colors.subtleText)};
    }
`;

const StateTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.9rem;
    font-weight: 700;
`;

const StateMessage = styled.div`
    font-size: 0.75rem;
    line-height: 1.5;
    max-width: 24rem;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const LoadingSpinner = styled.div`
    width: 26px;
    height: 26px;
    border: 3px solid ${({ theme }) => theme.colors.border};
    border-top: 3px solid ${({ theme }) => theme.colors.focusBlue};
    border-radius: 50%;
    animation: spin 0.8s linear infinite;

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;

const TABS = [
    { id: 'topics', label: 'Topics' },
    { id: 'users', label: 'Users' },
    { id: 'posts', label: 'Posts' },
];

function makeRowClickHandler(navigate, url) {
    return e => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) {
            try { window.open(url, '_blank', 'noopener,noreferrer'); } catch (_) { /* noop */ }
            return;
        }
        if (e.button !== 0) return;
        navigate(url);
    };
}

export default function BlocksView({ state }) {
    const [activeTab, setActiveTab] = useState('topics');
    const debugState = useDebugStateOverride();
    const {
        navigate,
        blockedUsers,
        blockedPosts,
        blockedTopics,
        blockedUsernames,
        listsLoading: listsLoadingRaw,
        listsError: listsErrorRaw,
        isTopicPending,
        isUserPending,
        isPostPending,
        formatTopicStatus,
        formatUserStatus,
        formatPostStatus,
        handleUnblockTopic,
        handleUnblockUser,
        handleUnblockPost,
    } = useBlocks({ state });

    const listsLoading = debugState === 'loading' ? true : listsLoadingRaw;
    const listsError = debugState === 'error'
        ? 'Simulated error — appended ?_state=error to preview the error UI.'
        : listsErrorRaw;
    const forceEmpty = debugState === 'empty';
    const visibleTopics = forceEmpty ? [] : blockedTopics;
    const visibleUsers = forceEmpty ? [] : blockedUsers;
    const visiblePosts = forceEmpty ? [] : blockedPosts;

    const viewerAddress = state && state.publicKey ? state.publicKey : '';
    const activeTabIndex = Math.max(0, TABS.findIndex(t => t.id === activeTab));

    const renderShell = body => (
        <ContentGrid>
            <Helmet>
                <title>Blocks | Mirage</title>
            </Helmet>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
                    <ModernPostFeed>
                        <TabbedContainer>
                            <ContainerBody $fullWidth>
                                <BlocksWrap>{body}</BlocksWrap>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </FeedCol>
                <FeedRightRail />
            </FeedRailRow>
        </ContentGrid>
    );

    if (!viewerAddress) {
        return <Navigate to="/home" replace />;
    }

    const tabCounts = {
        topics: visibleTopics.length,
        users: visibleUsers.length,
        posts: visiblePosts.length,
    };

    const headerBlock = (
        <>
            <HeaderRow>
                <HeaderTitle>Blocks</HeaderTitle>
            </HeaderRow>
            <TabsRow role="tablist" aria-label="Blocks sections" $count={TABS.length}>
                {TABS.map(tab => {
                    const isActive = activeTab === tab.id;
                    const count = tabCounts[tab.id];
                    return (
                        <TabButton
                            key={tab.id}
                            type="button"
                            role="tab"
                            aria-selected={isActive}
                            $active={isActive}
                            onClick={() => setActiveTab(tab.id)}
                        >
                            {tab.label}
                            {count > 0 && (
                                <TabCount>({count > 99 ? '99+' : count})</TabCount>
                            )}
                        </TabButton>
                    );
                })}
                <TabIndicator $count={TABS.length} $index={activeTabIndex} aria-hidden="true" />
            </TabsRow>
        </>
    );

    if (listsLoading) {
        return renderShell(
            <>
                {headerBlock}
                <StateBlock role="status" aria-live="polite">
                    <LoadingSpinner />
                    <StateTitle>Loading blocks…</StateTitle>
                </StateBlock>
            </>
        );
    }

    if (listsError) {
        return renderShell(
            <>
                {headerBlock}
                <StateBlock role="alert">
                    <StateIcon $tone="danger">
                        <HiExclamationTriangle />
                    </StateIcon>
                    <StateTitle>Couldn’t load blocks</StateTitle>
                    <StateMessage>{listsError}</StateMessage>
                </StateBlock>
            </>
        );
    }

    const showTopics = activeTab === 'topics';
    const showUsers = activeTab === 'users';
    const showPosts = activeTab === 'posts';

    return renderShell(
        <>
            {headerBlock}

            {showTopics && visibleTopics.length === 0 && (
                <StateBlock>
                    <StateIcon>
                        <HiNoSymbol />
                    </StateIcon>
                    <StateTitle>No blocked topics</StateTitle>
                    <StateMessage>
                        Topics you block stop appearing in your feed. You can block a topic from any post header.
                    </StateMessage>
                </StateBlock>
            )}

            {showTopics && visibleTopics.length > 0 && (
                <List>
                    {visibleTopics.map(topic => {
                        const isPending = isTopicPending(topic);
                        const status = formatTopicStatus(topic);
                        const topicUrl = `/t/${encodeURIComponent(topic)}`;
                        return (
                            <Row
                                key={topic}
                                role="link"
                                tabIndex={0}
                                onClick={makeRowClickHandler(navigate, topicUrl)}
                                onKeyDown={e => {
                                    if (e.key === 'Enter') navigate(topicUrl);
                                }}
                            >
                                <LeadingIcon aria-hidden="true">
                                    <HiHashtag />
                                </LeadingIcon>
                                <Identity>
                                    <IdentityTitle>{topic}</IdentityTitle>
                                </Identity>
                                <RowActions onClick={e => e.stopPropagation()}>
                                    <Button
                                        variant="danger"
                                        size="sm"
                                        minWidth="5.5rem"
                                        disabled={isPending}
                                        loading={isPending}
                                        onClick={e => {
                                            e.preventDefault();
                                            e.stopPropagation();
                                            handleUnblockTopic(e, topic);
                                        }}
                                    >
                                        {status || 'Unblock'}
                                    </Button>
                                </RowActions>
                            </Row>
                        );
                    })}
                </List>
            )}

            {showUsers && visibleUsers.length === 0 && (
                <StateBlock>
                    <StateIcon>
                        <HiUsers />
                    </StateIcon>
                    <StateTitle>No blocked users</StateTitle>
                    <StateMessage>
                        Users you block won’t appear in your feed, comments, or inbox.
                    </StateMessage>
                </StateBlock>
            )}

            {showUsers && visibleUsers.length > 0 && (
                <List>
                    {visibleUsers.map(userAddr => {
                        const isPending = isUserPending(userAddr);
                        const status = formatUserStatus(userAddr);
                        const username = blockedUsernames[userAddr];
                        const hasUsername = username && username !== userAddr;
                        const identitySeed = hasUsername ? username : userAddr;
                        const profileUrl = `/u/${encodeURIComponent(hasUsername ? username : userAddr)}`;
                        return (
                            <Row
                                key={userAddr}
                                role="link"
                                tabIndex={0}
                                onClick={makeRowClickHandler(navigate, profileUrl)}
                                onKeyDown={e => {
                                    if (e.key === 'Enter') navigate(profileUrl);
                                }}
                            >
                                <AvatarImg
                                    src={dicebearAvatarUrl(identitySeed, 32)}
                                    alt=""
                                    loading="lazy"
                                />
                                <Identity>
                                    <IdentityTitle>
                                        {hasUsername ? `@${username}` : shortenAddress(userAddr)}
                                    </IdentityTitle>
                                    <IdentityMeta title={userAddr}>{userAddr}</IdentityMeta>
                                </Identity>
                                <RowActions onClick={e => e.stopPropagation()}>
                                    <Button
                                        variant="danger"
                                        size="sm"
                                        minWidth="5.5rem"
                                        disabled={isPending}
                                        loading={isPending}
                                        onClick={e => {
                                            e.preventDefault();
                                            e.stopPropagation();
                                            handleUnblockUser(e, userAddr);
                                        }}
                                    >
                                        {status || 'Unblock'}
                                    </Button>
                                </RowActions>
                            </Row>
                        );
                    })}
                </List>
            )}

            {showPosts && visiblePosts.length === 0 && (
                <StateBlock>
                    <StateIcon>
                        <HiDocumentText />
                    </StateIcon>
                    <StateTitle>No blocked posts</StateTitle>
                    <StateMessage>
                        Individual posts you block will be hidden from every feed.
                    </StateMessage>
                </StateBlock>
            )}

            {showPosts && visiblePosts.length > 0 && (
                <List>
                    {visiblePosts.map(postId => {
                        const isPending = isPostPending(postId);
                        const status = formatPostStatus(postId);
                        const postUrl = `/p/${encodeURIComponent(postId)}`;
                        return (
                            <Row
                                key={postId}
                                role="link"
                                tabIndex={0}
                                onClick={makeRowClickHandler(navigate, postUrl)}
                                onKeyDown={e => {
                                    if (e.key === 'Enter') navigate(postUrl);
                                }}
                            >
                                <LeadingIcon aria-hidden="true">
                                    <HiDocumentText />
                                </LeadingIcon>
                                <Identity>
                                    <IdentityTitle>{shortenAddress(postId)}</IdentityTitle>
                                    <IdentityMeta title={postId}>{postId}</IdentityMeta>
                                </Identity>
                                <RowActions onClick={e => e.stopPropagation()}>
                                    <Button
                                        variant="danger"
                                        size="sm"
                                        minWidth="5.5rem"
                                        disabled={isPending}
                                        loading={isPending}
                                        onClick={e => {
                                            e.preventDefault();
                                            e.stopPropagation();
                                            handleUnblockPost(e, postId);
                                        }}
                                    >
                                        {status || 'Unblock'}
                                    </Button>
                                </RowActions>
                            </Row>
                        );
                    })}
                </List>
            )}
        </>
    );
}
