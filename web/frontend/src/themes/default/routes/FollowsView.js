import { communityLabel, communityPath } from '../../../utils/community';
import { useState } from "react";
import { Helmet } from "react-helmet-async";
import { Navigate, useLocation } from "react-router-dom";
import styled, { css } from "styled-components";
import { HiHashtag, HiExclamationTriangle, HiUsers } from "react-icons/hi2";
import Button from "../components/Button.js";
import { ListRowSkeletonList, PageHeaderSkeleton } from "../components/Skeleton.js";
import {
    ContentGrid,
    ModernPostFeed,
    TabbedContainer,
    ContainerBody,
} from "../Layout";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import { useFollows, shortenAddress } from "../../../logic/useFollows";
import UserAvatar from "../components/UserAvatar.js";

/**
 * Dev-only state override for QA. Append `?_state=loading|error|empty` to
 * preview those branches without touching real data. Strip-safe: the
 * `_state` prefix is `_` so it never collides with a real query param.
 */
function useDebugStateOverride() {
    const location = useLocation();
    const params = new URLSearchParams(location.search || "");
    return params.get("_state") || null;
}

/**
 * FollowsView — `default` Plan 06 sub-plan 03.
 *
 * Follows `docs/guides/web-theme-default/RULES.md`:
 *  - R1 rows sit on `theme.colors.bg`.
 *  - R2 every color routed through a token.
 *  - R3 rows are full-bleed divided by `1px solid theme.colors.border`.
 *  - R4 data parity with `themes/bluemoon/routes/FollowsView.js`; visual
 *    language matches the inbox row density from sub-plan 05.1.
 *  - R7 row title 0.78rem/600, meta 0.62rem/500 subtleText.
 */

const FollowsWrap = styled.div`
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
 * Tab strip — search-results style: equal-width grid columns with an
 * animated `TabIndicator` underline. The underline shares the same
 * `border` baseline so the divider visually starts where the active
 * tab indicator starts.
 */
const TabsRow = styled.div`
    position: relative;
    display: grid;
    grid-template-columns: repeat(${({ $count }) => $count || 2}, 1fr);
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
    width: calc(100% / ${({ $count }) => $count || 2});
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

/**
 * Row: avatar + identity block + right-aligned action button.
 * Rows are full-bleed divided by a single `border` line (R3), and hover
 * uses `hoverBg` as a background tile (no border-color change).
 *
 * Implemented as a `<div>` (not `<a>`) so the inner action `<Button>` can
 * own its click without the browser triggering anchor navigation. The
 * row click manually calls `navigate()`; cmd/ctrl-click open a new tab
 * via `window.open`.
 */
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

/** Followed-user avatar — thin alias around the shared `UserAvatar`
 *  so every dicebear chip in the app shares the same bg color and
 *  20% inner padding around the identicon glyph. */
const AvatarImg = ({ src: _src, ...rest }) => (
    <UserAvatar size={32} {...rest} />
);

const TopicIcon = styled.span`
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

/**
 * Following button that flips to a danger (red) "Unfollow" state on hover.
 * Uses `!important` so the swap survives flatMode's !important overrides in
 * `components/Button.js` (the `subtle` variant).
 */
const dangerHover = css`
    background: ${({ theme }) => theme.colors.buttonDangerBg} !important;
    color: ${({ theme }) => theme.colors.voteDown} !important;
    border-color: ${({ theme }) => theme.colors.buttonDangerBorder} !important;
`;

const FollowingButton = styled(Button)`
    [data-follow-label='hover'] { display: none; }
    [data-follow-label='default'] { display: inline; }

    &:hover:not(:disabled) {
        ${dangerHover}
        [data-follow-label='default'] { display: none; }
        [data-follow-label='hover'] { display: inline; }
    }
    &:focus-visible:not(:disabled) {
        ${dangerHover}
        [data-follow-label='default'] { display: none; }
        [data-follow-label='hover'] { display: inline; }
    }
`;

function FollowingLabel({ status }) {
    if (status) return status;
    return (
        <>
            <span data-follow-label="default">Following</span>
            <span data-follow-label="hover">Unfollow</span>
        </>
    );
}

/* ----- Empty / loading / error states (mirrors InboxView `StateBlock`). ----- */

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

const TABS = [
    { id: 'topics', label: 'Communities' },
    { id: 'users', label: 'Users' },
];

function makeRowClickHandler(navigate, url) {
    return e => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) {
            // Let the user open in a new tab manually.
            try { window.open(url, '_blank', 'noopener,noreferrer'); } catch (_) { /* noop */ }
            return;
        }
        if (e.button !== 0) return;
        navigate(url);
    };
}

export default function FollowsView({ state }) {
    const [activeTab, setActiveTab] = useState('topics');
    const debugState = useDebugStateOverride();
    const {
        navigate,
        followedUsers,
        followedTopics,
        followedUsernames,
        listsLoading: listsLoadingRaw,
        listsError: listsErrorRaw,
        isFollowTopicPending,
        isFollowUserPending,
        formatFollowTopicStatus,
        formatFollowUserStatus,
        handleUnfollowTopic,
        handleUnfollowUser,
    } = useFollows({ state });

    // Apply debug overrides (dev/QA only — driven by `?_state=...`).
    const listsLoading = debugState === 'loading' ? true : listsLoadingRaw;
    const listsError = debugState === 'error'
        ? 'Simulated error — appended ?_state=error to preview the error UI.'
        : listsErrorRaw;
    const forceEmpty = debugState === 'empty';
    const visibleTopics = forceEmpty ? [] : followedTopics;
    const visibleUsers = forceEmpty ? [] : followedUsers;

    const viewerAddress = state && state.publicKey ? state.publicKey : '';
    const activeTabIndex = Math.max(0, TABS.findIndex(t => t.id === activeTab));

    const renderShell = body => (
        <ContentGrid>
            <Helmet>
                <title>Follows | Mirage</title>
            </Helmet>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
                    <ModernPostFeed>
                        <TabbedContainer>
                            <ContainerBody $fullWidth>
                                <FollowsWrap>{body}</FollowsWrap>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </FeedCol>
            </FeedRailRow>
        </ContentGrid>
    );

    if (!viewerAddress) {
        return <Navigate to="/home" replace />;
    }

    const tabCounts = {
        topics: visibleTopics.length,
        users: visibleUsers.length,
    };

    const headerBlock = (
        <>
            <HeaderRow>
                <HeaderTitle>Follows</HeaderTitle>
            </HeaderRow>
            <TabsRow role="tablist" aria-label="Follows sections" $count={TABS.length}>
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
                <PageHeaderSkeleton />
                <ListRowSkeletonList count={6} />
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
                    <StateTitle>Couldn’t load follows</StateTitle>
                    <StateMessage>{listsError}</StateMessage>
                </StateBlock>
            </>
        );
    }

    const showTopics = activeTab === 'topics';
    const showUsers = activeTab === 'users';

    const topicsEmpty = visibleTopics.length === 0;
    const usersEmpty = visibleUsers.length === 0;

    return renderShell(
        <>
            {headerBlock}

            {showTopics && topicsEmpty && (
                <StateBlock>
                    <StateIcon>
                        <HiHashtag />
                    </StateIcon>
                    <StateTitle>Not following any communities</StateTitle>
                    <StateMessage>
                        Communities you follow will appear here. Pin communities you want to see more of in your feed.
                    </StateMessage>
                </StateBlock>
            )}

            {showTopics && !topicsEmpty && (
                <List>
                    {visibleTopics.map(topic => {
                        const isPending = isFollowTopicPending(topic);
                        const status = formatFollowTopicStatus(topic);
                        const topicUrl = communityPath(topic);
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
                                <TopicIcon aria-hidden="true">
                                    <HiHashtag />
                                </TopicIcon>
                                <Identity>
                                    <IdentityTitle>{communityLabel(topic)}</IdentityTitle>
                                </Identity>
                                <RowActions onClick={e => e.stopPropagation()}>
                                    <FollowingButton
                                        variant="subtle"
                                        size="sm"
                                        minWidth="5.5rem"
                                        disabled={isPending}
                                        loading={isPending}
                                        onClick={e => {
                                            e.preventDefault();
                                            e.stopPropagation();
                                            handleUnfollowTopic(e, topic);
                                        }}
                                    >
                                        <FollowingLabel status={status} />
                                    </FollowingButton>
                                </RowActions>
                            </Row>
                        );
                    })}
                </List>
            )}

            {showUsers && usersEmpty && (
                <StateBlock>
                    <StateIcon>
                        <HiUsers />
                    </StateIcon>
                    <StateTitle>Not following any users</StateTitle>
                    <StateMessage>
                        Follow users to see their posts and comments in your feed.
                    </StateMessage>
                </StateBlock>
            )}

            {showUsers && !usersEmpty && (
                <List>
                    {visibleUsers.map(userAddr => {
                        const isPending = isFollowUserPending(userAddr);
                        const status = formatFollowUserStatus(userAddr);
                        const username = followedUsernames[userAddr];
                        const hasUsername = username && username !== userAddr;
                        // Seed dicebear on the bech32 address (stable across
                        // username changes) — matches the policy used on
                        // every other avatar surface in the app.
                        const identitySeed = userAddr;
                        const profileUrl = `/u/${encodeURIComponent(hasUsername ? username : userAddr)}?tab=posts`;
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
                                <AvatarImg seed={identitySeed} alt="" />
                                <Identity>
                                    <IdentityTitle>
                                        {hasUsername ? `@${username}` : shortenAddress(userAddr)}
                                    </IdentityTitle>
                                    <IdentityMeta title={userAddr}>{userAddr}</IdentityMeta>
                                </Identity>
                                <RowActions onClick={e => e.stopPropagation()}>
                                    <FollowingButton
                                        variant="subtle"
                                        size="sm"
                                        minWidth="5.5rem"
                                        disabled={isPending}
                                        loading={isPending}
                                        onClick={e => {
                                            e.preventDefault();
                                            e.stopPropagation();
                                            handleUnfollowUser(e, userAddr);
                                        }}
                                    >
                                        <FollowingLabel status={status} />
                                    </FollowingButton>
                                </RowActions>
                            </Row>
                        );
                    })}
                </List>
            )}
        </>
    );
}
