import { useState, useMemo, useEffect, useCallback } from "react";
import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { Link } from "react-router-dom";
import {
    HiOutlineDocumentText,
    HiOutlineHashtag,
    HiOutlineUser,
    HiOutlineMagnifyingGlass,
    HiExclamationTriangle,
} from "react-icons/hi2";
import Button from "../components/Button.js";
import LoggedOutPromptCard from "../components/LoggedOutPromptCard.js";
import CardView from "../components/CardView.js";
import {
    ContentGrid,
    ModernPostFeed,
    TabbedContainer,
    ContainerTab,
    ContainerBody,
} from "../Layout";
import {
    FeedViewToggle,
    MemoCompactRow,
    RowSlot,
    loadViewMode,
    saveViewMode,
} from "../ListFeedView";
import { getAuthorColor, getAuthorTooltip } from "../../../utils/tierColors";
import { dicebearAvatarUrl } from "../../../utils/avatar";
import { useSearchResults } from "../../../logic/useSearchResults";

/**
 * `/search?q=...` — mirageapp full results view.
 *
 * Follows `RULES.md`:
 *  - R1: sits on `theme.colors.bg` via the shared `ContainerBody` wrapper.
 *  - R2: every color routed through tokens.
 *  - R3: only `1px solid theme.colors.border` dividers.
 *  - R4: data parity with `themes/bluemoon/routes/SearchResultsView.js`
 *    (topics, users, posts + load-more per tab), visual tone from
 *    `mirage-mobile-app/src/pages/search-screen.tsx` (plain-text tab row
 *    with active underline + count badge, row-style topic/user results,
 *    post results via the theme-local `CardView`).
 */

const TABS = [
    { id: "posts", label: "Posts" },
    { id: "topics", label: "Topics" },
    { id: "users", label: "Users" },
];

const SearchWrap = styled.div`
    width: 100%;
    max-width: 720px;
    margin: -0.75rem 0 0;

    @media (max-width: 1000px) {
        margin-top: -0.5rem;
    }

    @media (min-width: 1001px) {
        [data-sidebar-hidden='true'] & {
            width: 80%;
            max-width: none;
        }
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
 * Sub-header row sits directly under the title and hosts both the
 * "Results for ..." caption and (when the Posts tab is active) the
 * shared `FeedViewToggle` button. Laid out as a flex row so the toggle
 * anchors to the right edge of the search column.
 *
 * A fixed `min-height` reserves vertical space equal to the toggle button
 * so the row never changes height when the toggle hides on the Topics /
 * Users tabs. The toggle itself is always mounted and toggles via a
 * `$visible` flag (visibility: hidden) — keeping it in the DOM preserves
 * its horizontal slot and prevents the tab bar below from shifting.
 */
const HeaderSubRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    min-height: 28px;
    padding: 0 1rem 0.35rem;
`;

const HeaderSub = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.65rem;
    font-weight: 500;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

/**
 * Wrapper around the feed view toggle that keeps it in the DOM on every
 * tab but hides it visually when the Posts tab isn't active. Prevents
 * layout shift of the tab bar when switching tabs.
 */
const ViewToggleSlot = styled.div`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    visibility: ${({ $visible }) => ($visible ? "visible" : "hidden")};
    pointer-events: ${({ $visible }) => ($visible ? "auto" : "none")};
`;

/**
 * Plain-text tab row with an animated underline under the active tab.
 * Matches the mobile search-screen tab bar (three equal-width columns,
 * `primary` color + semibold on active, `subtleText` + regular on
 * inactive). Count badges live beside each label.
 */
const TabsRow = styled.div`
    position: relative;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
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
    /* Active + inactive share the same weight so the tab label never
     * reflows when you switch tabs. Active/inactive contrast is carried
     * entirely by color + the TabIndicator underline. */
    font-weight: 500;
    color: ${({ theme, $active }) =>
        $active ? theme.colors.text : theme.colors.subtleText};
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
    width: calc(100% / 3);
    height: 2px;
    background: ${({ theme }) => theme.colors.focusBlue};
    transform: translateX(${({ $index }) => `${$index * 100}%`});
    transition: transform 0.2s ease;
`;

/**
 * Per-tab count rendered as plain "(N)" inline text — intentionally no
 * filled pill / blue bg, per UI review. Color follows the tab's own
 * text color so it dims when the tab is inactive.
 */
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

const PostsList = styled.div`
    display: flex;
    flex-direction: column;
`;

/**
 * Reusable row container for topic / user results. Matches the inbox
 * row style (full-bleed, feed divider, hover tile from `hoverBg`).
 */
const RowItem = styled(Link)`
    display: flex;
    align-items: center;
    gap: 0.75rem;
    text-decoration: none;
    color: inherit;
    padding: 0.65rem 1rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    transition: background-color 0.15s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }
`;

const RowIcon = styled.span`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    color: ${({ theme }) => theme.colors.subtleText};

    svg {
        width: 18px;
        height: 18px;
    }
`;

/** Dicebear avatar used for user result rows. Same 28x28 footprint as
 *  `RowIcon` so the user list aligns with the topic list. */
const RowAvatar = styled.img`
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: #232830;
    object-fit: cover;
`;

const RowMain = styled.div`
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.12rem;
`;

/* Primary line in topic / user result rows. Matches the Inbox row text
 * style (0.7rem / weight 500) so all full-bleed list routes share one
 * typography rhythm. */
const RowPrimary = styled.div`
    font-size: 0.7rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.text};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const TierName = styled.span`
    color: ${({ $tierColor, theme }) => $tierColor || theme.colors.text};
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
        font-size: 0.62rem;
        font-weight: 500;
        white-space: nowrap;
        z-index: 20;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.15s ease;
    }

    &[data-tooltip]:hover::after {
        opacity: 1;
    }
`;

const RowMeta = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const LoadMoreWrap = styled.div`
    display: flex;
    justify-content: center;
    padding: 0.85rem 1rem 1.2rem;
`;

const StateBlock = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    padding: 2.2rem 1rem;
    text-align: center;
`;

const StateIcon = styled.div`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 42px;
    height: 42px;
    color: ${({ theme, $tone }) =>
        $tone === "danger" ? theme.colors.voteDown : theme.colors.subtleText};

    svg {
        width: 30px;
        height: 30px;
    }
`;

const StateTitle = styled.div`
    font-size: 0.85rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.text};
`;

const StateMessage = styled.div`
    max-width: 28rem;
    font-size: 0.68rem;
    line-height: 1.55;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const LoadingSpinner = styled.div`
    width: 30px;
    height: 30px;
    border-radius: 50%;
    border: 2px solid ${({ theme }) => theme.colors.border};
    border-top-color: ${({ theme }) => theme.colors.focusBlue};
    animation: spin 0.8s linear infinite;

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }
`;

function formatPostCount(count) {
    const n = Number(count || 0);
    if (!n) return "";
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M posts`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K posts`;
    return `${n} post${n === 1 ? "" : "s"}`;
}

function shortAddress(address) {
    const a = String(address || "");
    if (a.length < 14) return a;
    return `${a.slice(0, 8)}…${a.slice(-6)}`;
}

export default function SearchResultsView({ state }) {
    const {
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
    } = useSearchResults({ state });

    const [activeTab, setActiveTab] = useState("posts");
    const activeTabIndex = useMemo(
        () => TABS.findIndex((t) => t.id === activeTab),
        [activeTab]
    );

    // Tracks whether the current `activeTab` was picked by the user (as
    // opposed to the default / an auto-jump). Once the user clicks a tab
    // we stop auto-jumping even if that tab is empty — their explicit
    // pick always wins and we show the per-tab "no results" state.
    const [userPickedTab, setUserPickedTab] = useState(false);
    const handleTabClick = useCallback((tabId) => {
        setActiveTab(tabId);
        setUserPickedTab(true);
    }, []);

    // Reset the "user picked" flag whenever the query changes so a fresh
    // search can auto-jump to the first tab with results again.
    useEffect(() => {
        setUserPickedTab(false);
    }, [query]);

    // Feed view mode shared with the home feed via `mirageapp_feed_view_mode`.
    // Default is `compact` (handled by `VIEW_MODE_DEFAULT` in ListFeedView).
    const [viewMode, setViewMode] = useState(() => loadViewMode());
    const handleViewModeChange = useCallback((next) => {
        setViewMode(next);
        saveViewMode(next);
    }, []);

    // If the active tab has zero results but another tab has hits, auto-jump
    // to the first tab that has results. Keeps the page useful when a query
    // only matches (for example) users. Skipped once the user manually
    // clicks a tab for the current query — their explicit pick wins and
    // we render the per-tab empty state instead.
    useEffect(() => {
        if (loading || error) return;
        if (userPickedTab) return;
        const counts = {
            posts: posts.length,
            topics: topics.length,
            users: users.length,
        };
        if (counts[activeTab] > 0) return;
        const firstWithResults = TABS.find((t) => counts[t.id] > 0);
        if (firstWithResults && firstWithResults.id !== activeTab) {
            setActiveTab(firstWithResults.id);
        }
    }, [query, loading, error, posts.length, topics.length, users.length, activeTab, userPickedTab]);

    const renderShell = (body) => (
        <ContentGrid>
            <Helmet>
                <title>{query ? `Search: ${query}` : "Search"} | Mirage</title>
            </Helmet>
            <div>
                <ModernPostFeed>
                    <TabbedContainer>
                        <ContainerTab>Search</ContainerTab>
                        <ContainerBody $fullWidth>
                            <SearchWrap>{body}</SearchWrap>
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );

    if (!isLoggedIn) {
        return (
            <ContentGrid>
                <Helmet>
                    <title>{query ? `Search: ${query}` : "Search"} | Mirage</title>
                </Helmet>
                <div>
                    <ModernPostFeed>
                        <LoggedOutPromptCard
                            role="region"
                            aria-label="Search on Mirage"
                            eyebrow="Search Mirage"
                            title={query ? "Sign in to search Mirage" : "Search Mirage"}
                            description={
                                query
                                    ? `You searched for "${displayQuery}". Create an account or sign in to search topics, users, and posts.`
                                    : "Search topics, users, and posts after you sign in."
                            }
                            links={[
                                {
                                    label: "Watch Introduction (YouTube)",
                                    href: "https://www.youtube.com/watch?v=TOvP32ihQ0M",
                                    external: true,
                                },
                                {
                                    label: "Learn More",
                                    href: "https://mirage.foundation",
                                    external: true,
                                },
                            ]}
                            inviteText="Have an invite code? Join the community today."
                            primaryLabel="Create account"
                            secondaryLabel="Sign in"
                        />
                    </ModernPostFeed>
                </div>
            </ContentGrid>
        );
    }

    // No query yet — show the page shell with an idle prompt.
    if (!query) {
        return renderShell(
            <>
                <HeaderRow>
                    <HeaderTitle>Search</HeaderTitle>
                </HeaderRow>
                <StateBlock>
                    <StateIcon>
                        <HiOutlineMagnifyingGlass />
                    </StateIcon>
                    <StateTitle>Search Mirage</StateTitle>
                    <StateMessage>
                        Use the search bar above to find posts, topics, and users.
                    </StateMessage>
                </StateBlock>
            </>
        );
    }

    if (loading) {
        return renderShell(
            <>
                <HeaderRow>
                    <HeaderTitle>Search</HeaderTitle>
                </HeaderRow>
                <HeaderSubRow>
                    <HeaderSub>Searching for “{displayQuery}”…</HeaderSub>
                </HeaderSubRow>
                <StateBlock role="status" aria-live="polite">
                    <LoadingSpinner />
                </StateBlock>
            </>
        );
    }

    if (error) {
        return renderShell(
            <>
                <HeaderRow>
                    <HeaderTitle>Search</HeaderTitle>
                </HeaderRow>
                <HeaderSubRow>
                    <HeaderSub>Results for “{displayQuery}”</HeaderSub>
                </HeaderSubRow>
                <StateBlock role="alert">
                    <StateIcon $tone="danger">
                        <HiExclamationTriangle />
                    </StateIcon>
                    <StateTitle>Something went wrong</StateTitle>
                    <StateMessage>{error}</StateMessage>
                </StateBlock>
            </>
        );
    }

    if (!hasResults) {
        return renderShell(
            <>
                <HeaderRow>
                    <HeaderTitle>Search</HeaderTitle>
                </HeaderRow>
                <HeaderSubRow>
                    <HeaderSub>Results for “{displayQuery}”</HeaderSub>
                </HeaderSubRow>
                <StateBlock>
                    <StateIcon>
                        <HiOutlineMagnifyingGlass />
                    </StateIcon>
                    <StateTitle>No results found</StateTitle>
                    <StateMessage>
                        Try a different keyword, or remove filters. You can also search by
                        username (`@name`) or topic (`#topic`).
                    </StateMessage>
                </StateBlock>
            </>
        );
    }

    const renderPosts = () => {
        if (posts.length === 0) {
            return (
                <StateBlock>
                    <StateIcon>
                        <HiOutlineDocumentText />
                    </StateIcon>
                    <StateTitle>No posts found</StateTitle>
                    <StateMessage>
                        Try the Topics or Users tab, or search with different keywords.
                    </StateMessage>
                </StateBlock>
            );
        }
        return (
            <PostsList>
                {posts.map((post) => {
                    const postObj = {
                        post_id: post.post_id,
                        user_id: post.user_id,
                        username: post.username,
                        author_level: post.author_level,
                        author_is_new: post.author_is_new,
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
                        <RowSlot key={post.post_id}>
                            {viewMode === "compact" ? (
                                <MemoCompactRow post={postObj} state={state} />
                            ) : (
                                <CardView post={postObj} state={state} />
                            )}
                        </RowSlot>
                    );
                })}
                {hasMorePosts && (
                    <LoadMoreWrap>
                        <Button
                            variant="secondary"
                            size="sm"
                            fullWidth
                            onClick={loadMorePosts}
                            loading={loadingMorePosts}
                            disabled={loadingMorePosts}
                        >
                            {loadingMorePosts ? "Loading…" : "Load more posts"}
                        </Button>
                    </LoadMoreWrap>
                )}
            </PostsList>
        );
    };

    const renderTopics = () => {
        if (topics.length === 0) {
            return (
                <StateBlock>
                    <StateIcon>
                        <HiOutlineHashtag />
                    </StateIcon>
                    <StateTitle>No topics found</StateTitle>
                    <StateMessage>Try a different topic name.</StateMessage>
                </StateBlock>
            );
        }
        return (
            <List>
                {topics.map((topic) => (
                    <RowItem
                        key={`topic-${topic.topic}`}
                        to={`/t/${encodeURIComponent(topic.topic)}`}
                    >
                        <RowIcon>
                            <HiOutlineHashtag />
                        </RowIcon>
                        <RowMain>
                            <RowPrimary>{topic.topic}</RowPrimary>
                            <RowMeta>
                                {formatPostCount(topic.post_count) || "No posts yet"}
                            </RowMeta>
                        </RowMain>
                    </RowItem>
                ))}
                {hasMoreTopics && (
                    <LoadMoreWrap>
                        <Button
                            variant="secondary"
                            size="sm"
                            fullWidth
                            onClick={loadMoreTopics}
                            loading={loadingMoreTopics}
                            disabled={loadingMoreTopics}
                        >
                            {loadingMoreTopics ? "Loading…" : "Load more topics"}
                        </Button>
                    </LoadMoreWrap>
                )}
            </List>
        );
    };

    const renderUsers = () => {
        if (users.length === 0) {
            return (
                <StateBlock>
                    <StateIcon>
                        <HiOutlineUser />
                    </StateIcon>
                    <StateTitle>No users found</StateTitle>
                    <StateMessage>Try a different username.</StateMessage>
                </StateBlock>
            );
        }
        return (
            <List>
                {users.map((user) => {
                    const tierColor = getAuthorColor(user.level, user.user_is_new);
                    const tooltip = getAuthorTooltip(user.level, user.user_is_new);
                    const joined = user.created_at
                        ? ` · joined ${formatDate(user.created_at)}`
                        : "";
                    const postCount = user.post_count || 0;
                    return (
                        <RowItem
                            key={`user-${user.address}`}
                            to={`/u/${encodeURIComponent(
                                user.username || user.address
                            )}`}
                        >
                            <RowAvatar
                                src={dicebearAvatarUrl(user.username || user.address, 56)}
                                alt=""
                                loading="lazy"
                            />
                            <RowMain>
                                <RowPrimary>
                                    <TierName
                                        $tierColor={tierColor}
                                        data-tooltip={tooltip}
                                    >
                                        @{user.username || shortAddress(user.address)}
                                    </TierName>
                                </RowPrimary>
                                <RowMeta>
                                    {`${postCount} post${postCount === 1 ? "" : "s"}${joined}`}
                                </RowMeta>
                            </RowMain>
                        </RowItem>
                    );
                })}
                {hasMoreUsers && (
                    <LoadMoreWrap>
                        <Button
                            variant="secondary"
                            size="sm"
                            fullWidth
                            onClick={loadMoreUsers}
                            loading={loadingMoreUsers}
                            disabled={loadingMoreUsers}
                        >
                            {loadingMoreUsers ? "Loading…" : "Load more users"}
                        </Button>
                    </LoadMoreWrap>
                )}
            </List>
        );
    };

    const tabContent = {
        posts: renderPosts,
        topics: renderTopics,
        users: renderUsers,
    };

    const tabCounts = {
        posts: posts.length,
        topics: topics.length,
        users: users.length,
    };

    return renderShell(
        <>
            <HeaderRow>
                <HeaderTitle>Search</HeaderTitle>
            </HeaderRow>
            <HeaderSubRow>
                <HeaderSub>Results for “{displayQuery}”</HeaderSub>
                <ViewToggleSlot
                    $visible={activeTab === "posts" && posts.length > 0}
                    aria-hidden={!(activeTab === "posts" && posts.length > 0)}
                >
                    <FeedViewToggle
                        viewMode={viewMode}
                        onChange={handleViewModeChange}
                    />
                </ViewToggleSlot>
            </HeaderSubRow>
            <TabsRow role="tablist" aria-label="Search result categories">
                {TABS.map((tab) => {
                    const isActive = activeTab === tab.id;
                    const count = tabCounts[tab.id];
                    return (
                        <TabButton
                            key={tab.id}
                            role="tab"
                            type="button"
                            aria-selected={isActive}
                            $active={isActive}
                            onClick={() => handleTabClick(tab.id)}
                        >
                            {tab.label}
                            {count > 0 && (
                                <TabCount>({count > 99 ? "99+" : count})</TabCount>
                            )}
                        </TabButton>
                    );
                })}
                <TabIndicator $index={activeTabIndex} aria-hidden="true" />
            </TabsRow>
            {(tabContent[activeTab] || renderPosts)()}
        </>
    );
}
