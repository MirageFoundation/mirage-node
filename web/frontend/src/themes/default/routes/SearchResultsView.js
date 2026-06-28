import { useState, useMemo, useEffect, useCallback } from "react";
import { Helmet } from "react-helmet-async";
import styled, { css } from "styled-components";
import { Link, useNavigate } from "react-router-dom";
import { requireAccount } from "../../../utils/openBrowsing";
import {
    HiOutlineDocumentText,
    HiOutlineHashtag,
    HiOutlineUser,
    HiOutlineMagnifyingGlass,
    HiExclamationTriangle,
    HiOutlineFire,
} from "react-icons/hi2";
import LoggedOutPromptCard from "../components/LoggedOutPromptCard.js";
import CardView from "../components/CardView.js";
import { FeedCardSkeletonList, PageHeaderSkeleton } from "../components/Skeleton.js";
import ShowMoreButton from "../components/ShowMoreButton.js";
import Button from "../components/Button.js";
import {
    ContentGrid,
    ModernPostFeed,
    TabbedContainer,
    ContainerTab,
    ContainerBody,
} from "../Layout";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import {
    FeedViewToggle,
    MemoCompactRow,
    RowSlot,
    loadViewMode,
    saveViewMode,
} from "../ListFeedView";
import { getAuthorColor, getAuthorTooltip } from "../../../utils/tierColors";
import UserAvatar from "../components/UserAvatar.js";
import { useSearchResults } from "../../../logic/useSearchResults";
import { useSearchDropdown } from "../../../logic/useSearchDropdown";
import { getCachedWelcomeStats } from "../../../utils/welcomeStatsCache";
import Storage from "../../../utils/Storage";
import {
    follow as followUser,
    unfollow as unfollowUser,
    fetchFollowedUsers,
} from "../../../utils/FollowUsers";
import {
    subscribe as subscribeTopic,
    unsubscribe as unsubscribeTopic,
    fetchFollowedTopics,
} from "../../../utils/Subscriptions";
import { usePendingFollows } from "../../../logic/useFollowState.js";

/**
 * `/search?q=...` — default full results view.
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

/**
 * Inline search form rendered at the top of the results view, visible
 * only on screens where the TopBar's desktop search input is hidden
 * (≤800px). Lets users run a new search when the MobileHeader /
 * compact header only offers a search icon (no input).
 */
const MobileSearchForm = styled.form`
    display: none;

    @media (max-width: 800px) {
        display: flex;
        align-items: center;
        margin: 0.15rem 1rem 0.6rem;
        padding: 1px;
        border-radius: 9999px;
        background: ${({ theme }) => theme.colors.gradient};
        transition: background 0.15s ease;

        &:focus-within {
            background: ${({ theme }) => theme.colors.focusBlue};
        }
    }

    @media (max-width: 600px) {
        margin: 0.15rem 0 0.6rem;
    }
`;

const MobileSearchInner = styled.div`
    position: relative;
    width: 100%;
    display: flex;
    align-items: center;
    border-radius: 9999px;
    background: ${({ theme }) => theme.colors.bg};
`;

const MobileSearchIcon = styled.svg`
    position: absolute;
    left: 0.75rem;
    top: 50%;
    transform: translateY(-50%);
    width: 16px;
    height: 16px;
    color: ${({ theme }) => theme.colors.subtleText};
    pointer-events: none;
`;

const MobileSearchInput = styled.input`
    width: 100%;
    box-sizing: border-box;
    padding: calc(0.4rem + 1px) 2.4rem calc(0.4rem + 1px) 2.1rem;
    border-radius: 9999px;
    border: none;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.8rem;
    line-height: 1.2;
    outline: none;

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
        font-size: 0.8rem;
    }

    &::-webkit-search-cancel-button,
    &::-webkit-search-decoration,
    &::-webkit-search-results-button,
    &::-webkit-search-results-decoration {
        -webkit-appearance: none;
        appearance: none;
        display: none;
    }
`;

const MobileSearchClear = styled.button`
    position: absolute;
    right: 0.35rem;
    top: 50%;
    transform: translateY(-50%);
    width: 28px;
    height: 28px;
    border: none;
    border-radius: 999px;
    background: transparent;
    color: ${({ theme }) => theme.colors.subtleText};
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    padding: 0;

    &:hover {
        color: ${({ theme }) => theme.colors.text};
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    svg {
        width: 14px;
        height: 14px;
    }
`;

/**
 * Wrappers used to show / hide entire blocks based on viewport. The
 * search page replaces the idle "Use the search bar" desktop copy with
 * a trending-topics list on mobile, so we hide the desktop-only block
 * below 800px and hide the mobile-only block above 800px.
 */
const DesktopOnly = styled.div`
    @media (max-width: 800px) {
        display: none;
    }
`;

const MobileOnly = styled.div`
    display: none;

    @media (max-width: 800px) {
        display: block;
    }
`;

const TrendingSectionLabel = styled.div`
    font-size: 0.6rem;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.subtleText};
    padding: 0.75rem 1rem 0.35rem;

    @media (max-width: 600px) {
        padding: 0.75rem 0 0.35rem;
    }
`;

const TrendingList = styled.div`
    display: flex;
    flex-direction: column;
`;

const TrendingEmpty = styled.div`
    padding: 1rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.68rem;
    font-weight: 500;
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

    @media (max-width: 600px) {
        padding: 0 0 0.35rem;
    }
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

    @media (max-width: 600px) {
        padding: 0.65rem 0;
    }
`;

/** "#" pill for topic result rows — mirrors `FollowsView::TopicIcon` /
 *  `ProfileView::AlgoTopicChip` so topic chips read consistently across
 *  the follows, algo, and search-results screens. */
const RowIcon = styled.span`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: ${({ theme }) => theme.colors.surface2};
    border: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.subtleText};

    svg {
        width: 14px;
        height: 14px;
    }
`;

/** Dicebear avatar used for user result rows. Same 28x28 footprint as
 *  `RowIcon` so the user list aligns with the topic list. Wraps the
 *  shared `UserAvatar` so the bg color + 20% inner padding stay in
 *  sync with the rest of the app. */
const RowAvatar = ({ src: _src, ...rest }) => (
    <UserAvatar size={28} {...rest} />
);

const RowMain = styled.div`
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.12rem;
`;

/* Primary line in topic / user result rows. Matches
 * `ProfileView::AlgoIdentityTitle` (0.78rem / 600) so topic + user
 * names read the same across the algo tab and search results. */
const RowPrimary = styled.div`
    font-size: 0.78rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.text};
    line-height: 1.25;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const TierName = styled.span`
    color: ${({ $tierColor, theme }) => $tierColor || theme.colors.text};
    position: relative;
    /* Keep the username text in lockstep with topic names — inherit the
     * RowPrimary typography (0.78rem / 600) so the users tab reads at
     * the same size as the topics tab in search results. */
    font-size: inherit;
    font-weight: inherit;
    line-height: inherit;

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

/* Right-side action cluster on each result row. Clicks here must not
 * bubble up to the surrounding `RowItem` (which is a react-router Link),
 * so every event handler on the button stops propagation + prevents
 * the default navigation. */
const RowActions = styled.div`
    flex-shrink: 0;
    display: flex;
    align-items: center;
    margin-left: auto;
`;

/**
 * Follow / Following button used on topic + user result rows. Mirrors
 * the FollowsView affordance:
 *  - Not followed → `primary` filled "Follow" pill.
 *  - Followed     → `subtle` tinted "Following" pill that flips to a
 *                   danger "Unfollow" state on hover / focus.
 * `!important` on the hover swap survives flatMode's !important overrides
 * in the shared Button component (same trick as FollowsView).
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
    const navigate = useNavigate();
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
        openBrowsingEnabled,
        nodeConfigLoaded,
    } = useSearchResults({ state });

    const [activeTab, setActiveTab] = useState("posts");
    const activeTabIndex = useMemo(
        () => TABS.findIndex((t) => t.id === activeTab),
        [activeTab]
    );

    /* --- Follow state (topics + users) ------------------------------------
     * Mirrors `useDiscover` / `useFollows`: load the viewer's followed
     * topics + users once, keep them as lowercased `Set`s for O(1) checks,
     * and optimistically update them on toggle. `usePendingFollows` drives
     * the in-flight spinner / queue-position label so the UI matches the
     * Follows tab.
     */
    const viewerAddress = useMemo(
        () => (state && state.publicKey) || Storage.load("publicKey", "") || "",
        [state]
    );
    const viewerAddressLower = useMemo(
        () => String(viewerAddress || "").trim().toLowerCase(),
        [viewerAddress]
    );
    const [followedTopicsSet, setFollowedTopicsSet] = useState(() => new Set());
    const [followedUsersSet, setFollowedUsersSet] = useState(() => new Set());
    const {
        isTopicPending: isFollowTopicPending,
        isUserPending: isFollowUserPending,
        formatTopicStatus: formatFollowTopicStatus,
        formatUserStatus: formatFollowUserStatus,
    } = usePendingFollows();

    useEffect(() => {
        if (!isLoggedIn || !viewerAddressLower) {
            setFollowedTopicsSet(new Set());
            setFollowedUsersSet(new Set());
            return undefined;
        }
        let cancelled = false;
        (async () => {
            try {
                const [topicsList, usersList] = await Promise.all([
                    fetchFollowedTopics(viewerAddressLower),
                    fetchFollowedUsers(viewerAddressLower),
                ]);
                if (cancelled) return;
                setFollowedTopicsSet(
                    new Set(
                        (topicsList || [])
                            .map((t) => String(t || "").trim().toLowerCase())
                            .filter(Boolean)
                    )
                );
                setFollowedUsersSet(
                    new Set(
                        (usersList || [])
                            .map((u) => String(u || "").trim().toLowerCase())
                            .filter(Boolean)
                    )
                );
            } catch (_) { /* silent — button just shows "Follow" */ }
        })();
        return () => {
            cancelled = true;
        };
    }, [isLoggedIn, viewerAddressLower]);

    const isTopicFollowed = useCallback(
        (topic) => followedTopicsSet.has(String(topic || "").trim().toLowerCase()),
        [followedTopicsSet]
    );
    const isUserFollowed = useCallback(
        (addr) => followedUsersSet.has(String(addr || "").trim().toLowerCase()),
        [followedUsersSet]
    );

    const handleTopicFollowToggle = useCallback(
        async (e, topic) => {
            if (e) {
                if (typeof e.preventDefault === "function") e.preventDefault();
                if (typeof e.stopPropagation === "function") e.stopPropagation();
            }
            const t = String(topic || "").trim();
            if (!t) return;
            if (!requireAccount('follow topics')) return;
            if (!viewerAddressLower) return;
            const lower = t.toLowerCase();
            if (isFollowTopicPending(lower)) return;
            const wasFollowing = isTopicFollowed(t);
            try {
                if (wasFollowing) {
                    await unsubscribeTopic(viewerAddressLower, t);
                    setFollowedTopicsSet((prev) => {
                        const next = new Set(prev);
                        next.delete(lower);
                        return next;
                    });
                } else {
                    await subscribeTopic(viewerAddressLower, t);
                    setFollowedTopicsSet((prev) => new Set([...prev, lower]));
                }
            } catch (err) {
                alert(
                    `Error ${wasFollowing ? "unfollowing" : "following"} topic: ${err?.message || err
                    }`
                );
            }
        },
        [isLoggedIn, viewerAddressLower, isFollowTopicPending, isTopicFollowed]
    );

    const handleUserFollowToggle = useCallback(
        async (e, userAddr) => {
            if (e) {
                if (typeof e.preventDefault === "function") e.preventDefault();
                if (typeof e.stopPropagation === "function") e.stopPropagation();
            }
            const addr = String(userAddr || "").trim().toLowerCase();
            if (!addr) return;
            if (!requireAccount('follow users')) return;
            if (!viewerAddressLower || addr === viewerAddressLower) return;
            if (isFollowUserPending(addr)) return;
            const wasFollowing = isUserFollowed(addr);
            try {
                if (wasFollowing) {
                    await unfollowUser(viewerAddressLower, addr);
                    setFollowedUsersSet((prev) => {
                        const next = new Set(prev);
                        next.delete(addr);
                        return next;
                    });
                } else {
                    await followUser(viewerAddressLower, addr);
                    setFollowedUsersSet((prev) => new Set([...prev, addr]));
                }
            } catch (err) {
                alert(
                    `Error ${wasFollowing ? "unfollowing" : "following"} user: ${err?.message || err
                    }`
                );
            }
        },
        [isLoggedIn, viewerAddressLower, isFollowUserPending, isUserFollowed]
    );

    // Local input state for the small-screen inline search form (visible
    // only on ≤800px, where the TopBar's desktop search input is hidden).
    // Kept in sync with the URL `q` so reopening `/search?q=...` on mobile
    // pre-populates the input, and editing / submitting updates the URL.
    const [mobileQuery, setMobileQuery] = useState(query || "");
    useEffect(() => {
        setMobileQuery(query || "");
    }, [query]);

    const handleMobileSubmit = useCallback(
        (e) => {
            e.preventDefault();
            const q = String(mobileQuery || "").trim();
            if (!q) return;
            navigate(`/search?q=${encodeURIComponent(q)}`);
        },
        [mobileQuery, navigate]
    );

    const handleMobileClear = useCallback(() => {
        setMobileQuery("");
    }, []);

    // Debounced URL sync: while the user types in the mobile input, push
    // the query into the URL (`?q=...`) via `replace` so `useSearchResults`
    // re-fetches and the 3-tab view updates in place — mirroring the
    // desktop experience where pressing Enter lands on the tabbed page.
    // Skip when the trimmed value already matches the URL query to avoid
    // redundant history entries / refetches while the user only added /
    // removed whitespace.
    useEffect(() => {
        const trimmed = String(mobileQuery || "").trim();
        const urlQuery = String(query || "").trim();
        if (trimmed === urlQuery) return undefined;
        const handle = setTimeout(() => {
            if (!trimmed) {
                navigate("/search", { replace: true });
            } else {
                navigate(`/search?q=${encodeURIComponent(trimmed)}`, {
                    replace: true,
                });
            }
        }, 350);
        return () => clearTimeout(handle);
    }, [mobileQuery, query, navigate]);

    // Pull trending topics from the shared dropdown hook so the mobile
    // idle state mirrors the desktop `SearchDropdown`. We intentionally
    // don't push the typed query into the hook — live search runs via
    // the URL-driven `useSearchResults` flow instead, which already
    // renders the full 3-tab view under the input on mobile.
    const { trendingTopics, isLoadingTrending } = useSearchDropdown();

    const mobileSearchBar = (
        <MobileSearchForm role="search" onSubmit={handleMobileSubmit}>
            <MobileSearchInner>
                <MobileSearchIcon viewBox="0 0 24 24" aria-hidden="true">
                    <path
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M21 21l-4.35-4.35M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z"
                    />
                </MobileSearchIcon>
                <MobileSearchInput
                    type="search"
                    value={mobileQuery}
                    onChange={(e) => setMobileQuery(e.target.value)}
                    placeholder="Search Mirage"
                    aria-label="Search"
                    autoComplete="off"
                    enterKeyHint="search"
                />
                {mobileQuery.length > 0 && (
                    <MobileSearchClear
                        type="button"
                        onClick={handleMobileClear}
                        aria-label="Clear search"
                    >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                            <path
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2.2"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                d="M6 6l12 12M18 6L6 18"
                            />
                        </svg>
                    </MobileSearchClear>
                )}
            </MobileSearchInner>
        </MobileSearchForm>
    );

    // Mobile-only trending-topics block. Shown directly under the mobile
    // search input when the input is empty (matches the desktop
    // `SearchDropdown` idle state). Hidden on desktop via the
    // `MobileOnly` wrapper.
    const mobileTrending = (
        <MobileOnly>
            <TrendingSectionLabel>Trending topics</TrendingSectionLabel>
            {isLoadingTrending ? (
                <TrendingEmpty>Loading trending topics…</TrendingEmpty>
            ) : trendingTopics.length === 0 ? (
                <TrendingEmpty>No trending topics available</TrendingEmpty>
            ) : (
                <TrendingList>
                    {trendingTopics.map((topic) => (
                        <RowItem
                            key={`trending-${topic.topic}`}
                            to={`/t/${encodeURIComponent(topic.topic)}`}
                        >
                            <RowIcon>
                                <HiOutlineFire />
                            </RowIcon>
                            <RowMain>
                                <RowPrimary>{topic.topic}</RowPrimary>
                                <RowMeta>
                                    {formatPostCount(
                                        topic.post_count || topic.count
                                    ) || "No posts yet"}
                                </RowMeta>
                            </RowMain>
                        </RowItem>
                    ))}
                </TrendingList>
            )}
        </MobileOnly>
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

    // Feed view mode shared with the home feed via `default_feed_view_mode`.
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
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
                    <ModernPostFeed>
                        <TabbedContainer>
                            <ContainerTab>Search</ContainerTab>
                            <ContainerBody $fullWidth>
                                <SearchWrap>{body}</SearchWrap>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </FeedCol>
            </FeedRailRow>
        </ContentGrid>
    );

    if (!isLoggedIn && !openBrowsingEnabled && nodeConfigLoaded) {
        return (
            <ContentGrid>
                <Helmet>
                    <title>{query ? `Search: ${query}` : "Search"} | Mirage</title>
                </Helmet>
                <FeedRailRow $feedViewMode="card">
                    <FeedCol>
                        <ModernPostFeed>
                            <LoggedOutPromptCard
                                role="region"
                                aria-label="Search on Mirage"
                                title={query ? "Sign in to search Mirage" : "Search Mirage"}
                                description="Create an account or sign in to search topics, users, and posts."
                                stats={getCachedWelcomeStats()}
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
                                primaryLabel="Create account"
                                secondaryLabel="Sign in"
                            />
                        </ModernPostFeed>
                    </FeedCol>
                </FeedRailRow>
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
                {mobileSearchBar}
                <DesktopOnly>
                    <StateBlock>
                        <StateIcon>
                            <HiOutlineMagnifyingGlass />
                        </StateIcon>
                        <StateTitle>Search Mirage</StateTitle>
                        <StateMessage>
                            Use the search bar to find posts, topics, and users.
                        </StateMessage>
                    </StateBlock>
                </DesktopOnly>
                {mobileTrending}
            </>
        );
    }

    if (loading) {
        return renderShell(
            <>
                <HeaderRow>
                    <HeaderTitle>Search</HeaderTitle>
                </HeaderRow>
                {mobileSearchBar}
                <PageHeaderSkeleton />
                <FeedCardSkeletonList count={4} />
            </>
        );
    }

    if (error) {
        return renderShell(
            <>
                <HeaderRow>
                    <HeaderTitle>Search</HeaderTitle>
                </HeaderRow>
                {mobileSearchBar}
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
                {mobileSearchBar}
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
                    <ShowMoreButton onClick={loadMorePosts} loading={loadingMorePosts} spacing="loose">
                        Show more
                    </ShowMoreButton>
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
                {topics.map((topic) => {
                    const topicName = topic.topic;
                    const followed = isTopicFollowed(topicName);
                    const pending = isFollowTopicPending(topicName);
                    const status = formatFollowTopicStatus(topicName);
                    return (
                        <RowItem
                            key={`topic-${topicName}`}
                            to={`/t/${encodeURIComponent(topicName)}`}
                        >
                            <RowIcon>
                                <HiOutlineHashtag />
                            </RowIcon>
                            <RowMain>
                                <RowPrimary>{topicName}</RowPrimary>
                                <RowMeta>
                                    {formatPostCount(topic.post_count) || "No posts yet"}
                                </RowMeta>
                            </RowMain>
                            {isLoggedIn && (
                                <RowActions
                                    onClick={(e) => {
                                        e.preventDefault();
                                        e.stopPropagation();
                                    }}
                                >
                                    {followed ? (
                                        <FollowingButton
                                            variant="subtle"
                                            size="sm"
                                            minWidth="5.5rem"
                                            disabled={pending}
                                            loading={pending}
                                            onClick={(e) =>
                                                handleTopicFollowToggle(e, topicName)
                                            }
                                        >
                                            <FollowingLabel status={status} />
                                        </FollowingButton>
                                    ) : (
                                        <Button
                                            variant="primary"
                                            size="sm"
                                            minWidth="5.5rem"
                                            disabled={pending}
                                            loading={pending}
                                            onClick={(e) =>
                                                handleTopicFollowToggle(e, topicName)
                                            }
                                        >
                                            {status || "Follow"}
                                        </Button>
                                    )}
                                </RowActions>
                            )}
                        </RowItem>
                    );
                })}
                {hasMoreTopics && (
                    <ShowMoreButton onClick={loadMoreTopics} loading={loadingMoreTopics} spacing="loose">
                        Show more
                    </ShowMoreButton>
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
                    const userAddr = user.address;
                    const userAddrLower = String(userAddr || "").trim().toLowerCase();
                    const isSelf = !!userAddrLower && userAddrLower === viewerAddressLower;
                    const followed = isUserFollowed(userAddr);
                    const pending = isFollowUserPending(userAddrLower);
                    const status = formatFollowUserStatus(userAddrLower);
                    return (
                        <RowItem
                            key={`user-${userAddr}`}
                            to={`/u/${encodeURIComponent(
                                user.username || userAddr
                            )}`}
                        >
                            <RowAvatar seed={userAddr} alt="" />
                            <RowMain>
                                <RowPrimary>
                                    <TierName
                                        $tierColor={tierColor}
                                        data-tooltip={tooltip}
                                    >
                                        @{user.username || shortAddress(userAddr)}
                                    </TierName>
                                </RowPrimary>
                                <RowMeta>
                                    {`${postCount} post${postCount === 1 ? "" : "s"}${joined}`}
                                </RowMeta>
                            </RowMain>
                            {isLoggedIn && !isSelf && (
                                <RowActions
                                    onClick={(e) => {
                                        e.preventDefault();
                                        e.stopPropagation();
                                    }}
                                >
                                    {followed ? (
                                        <FollowingButton
                                            variant="subtle"
                                            size="sm"
                                            minWidth="5.5rem"
                                            disabled={pending}
                                            loading={pending}
                                            onClick={(e) =>
                                                handleUserFollowToggle(e, userAddr)
                                            }
                                        >
                                            <FollowingLabel status={status} />
                                        </FollowingButton>
                                    ) : (
                                        <Button
                                            variant="primary"
                                            size="sm"
                                            minWidth="5.5rem"
                                            disabled={pending}
                                            loading={pending}
                                            onClick={(e) =>
                                                handleUserFollowToggle(e, userAddr)
                                            }
                                        >
                                            {status || "Follow"}
                                        </Button>
                                    )}
                                </RowActions>
                            )}
                        </RowItem>
                    );
                })}
                {hasMoreUsers && (
                    <ShowMoreButton onClick={loadMoreUsers} loading={loadingMoreUsers} spacing="loose">
                        Show more
                    </ShowMoreButton>
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
            {mobileSearchBar}
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
