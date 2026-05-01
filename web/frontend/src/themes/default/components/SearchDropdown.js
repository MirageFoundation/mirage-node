import React, { useMemo } from "react";
import styled from "styled-components";
import { Link } from "react-router-dom";
import {
    HiOutlineClock,
    HiOutlineXMark,
    HiOutlineHashtag,
    HiOutlineFire,
    HiOutlineMagnifyingGlass,
} from "react-icons/hi2";
import { getAuthorColor } from "../../../utils/tierColors";
import UserAvatar from "./UserAvatar.js";
import PostPlaceholderAvatar from "./PostPlaceholderAvatar.js";

/**
 * Dropdown sheet rendered below the TopBar search input. Mirrors the
 * `mirage-mobile-app/src/pages/search-screen.tsx` behaviour: shows recent
 * searches + trending topics when the query is empty, and live search
 * results (posts / topics / users) while the user is typing.
 *
 * Visual only — all data comes from `useSearchDropdown` which the TopBar
 * owns. Click on any row → delegates to the handler passed in.
 *
 * Tokens used (see `RULES.md`):
 *  - panel canvas: `menuBg` (rgb(25,28,31) dark / rgb(255,255,255) light)
 *  - row hover bg: `menuSelectedBg` (lifts row for visible hover effect)
 *  - row text rest: `sidebarItemText` (matches post-options dropdown)
 *  - row text hover: `menuItemHoverText` (matches post-options dropdown)
 *  - divider:      `border`
 *  - post avatar:  `gradient`
 */

const Sheet = styled.div`
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    right: 0;
    max-height: min(70vh, 540px);
    overflow-y: auto;
    background: ${({ theme }) => theme.colors.menuBg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.28);
    z-index: 200;

    scrollbar-width: thin;
    scrollbar-color: ${({ theme }) => theme.colors.scrollbar} transparent;

    &::-webkit-scrollbar {
        width: 8px;
    }
    &::-webkit-scrollbar-thumb {
        background: ${({ theme }) => theme.colors.scrollbar};
        border-radius: 4px;
    }
`;

const SectionLabelRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.55rem 0.9rem 0.25rem;
    gap: 0.5rem;
`;

const SectionLabel = styled.div`
    font-size: 0.55rem;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.menuHeaderText};
`;

const ClearAllButton = styled.button`
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
    font-family: inherit;
    font-size: 0.55rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.sidebarItemText};
    cursor: pointer;
    transition: color 0.15s ease;

    &:hover {
        color: ${({ theme }) => theme.colors.sidebarItemActiveText};
    }
`;

const SectionDivider = styled.div`
    height: 1px;
    background: ${({ theme }) => theme.colors.border};
    margin: 0 0.9rem;
`;

/**
 * Shared row styles. Text defaults to `sidebarItemText` so it matches the
 * post-options dropdown at rest, and on hover lifts to `menuItemHoverText`
 * with a visible `menuSelectedBg` tile (unlike post-options where the bg
 * stays transparent — the user specifically asked for a hover bg here).
 */
const rowStyles = ({ theme }) => `
    display: flex;
    align-items: center;
    gap: 0.6rem;
    width: 100%;
    padding: 0.5rem 0.9rem;
    background: transparent;
    border: none;
    cursor: pointer;
    color: ${theme.colors.sidebarItemText};
    text-decoration: none;
    font-family: inherit;
    text-align: left;
    transition: background 0.15s ease, color 0.15s ease;

    &:hover {
        background: ${theme.colors.menuSelectedBg};
        color: ${theme.colors.menuItemHoverText};
    }
`;

const RowButton = styled.button`
    ${rowStyles}
`;

const RowLink = styled(Link)`
    ${rowStyles}
`;

const RowIcon = styled.span`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    color: ${({ theme }) => theme.colors.subtleText};

    svg {
        width: 15px;
        height: 15px;
    }

    /* Icon inherits text color lift on row hover. */
    ${RowButton}:hover &, ${RowLink}:hover & {
        color: ${({ theme }) => theme.colors.menuItemHoverText};
    }
`;

/**
 * Dicebear avatar used for search-result user rows. Same 22x22 footprint
 * as `RowIcon` so columns remain aligned with the topic/post rows. Thin
 * alias around the shared `UserAvatar` so the bg color and 20% inner
 * padding stay in sync with the rest of the app's avatar surfaces.
 */
const RowAvatar = ({ src: _src, ...rest }) => (
    <UserAvatar size={22} {...rest} />
);

/**
 * Post-row thumbnail slot: shows the post image if one is available,
 * otherwise renders a gradient tile with the first letter of the author's
 * username. Same 28px size as the topic/user row icon block so columns
 * stay aligned.
 */
const PostThumb = styled.span`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 4px;
    overflow: hidden;
    background: ${({ theme }) => theme.colors.accent};
    color: ${({ theme }) => theme.colors.buttonText};
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0;
    line-height: 1;
`;

const PostThumbImg = styled.img`
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
`;

const RowMain = styled.div`
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.08rem;
    overflow: hidden;
`;

const RowPrimary = styled.span`
    font-size: 0.66rem;
    font-weight: 500;
    color: inherit;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const RowSecondary = styled.span`
    font-size: 0.56rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const RowRemove = styled.button`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    padding: 0;
    margin: 0;
    border: none;
    background: transparent;
    color: ${({ theme }) => theme.colors.subtleText};
    border-radius: 9999px;
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;

    svg {
        width: 13px;
        height: 13px;
    }

    &:hover {
        background: ${({ theme }) => theme.colors.inputIconHoverBg};
        color: ${({ theme }) => theme.colors.text};
    }
`;

const TierUsername = styled.span`
    color: ${({ $tierColor, theme }) => $tierColor || theme.colors.text};
    font-weight: 600;
`;

const EmptyBlock = styled.div`
    padding: 1.1rem 1rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.5;
`;

const ErrorBlock = styled.div`
    padding: 0.85rem 1rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.6rem;
`;

const SeeAllRow = styled.button`
    ${rowStyles}
    justify-content: center;
    /* Tighter gap than standard rows so the magnifier + label read as a
     * single cluster in the footer. */
    gap: 0.3rem;
    font-size: 0.58rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.sidebarItemText};
    border-top: 1px solid ${({ theme }) => theme.colors.border};

    &:hover {
        color: ${({ theme }) => theme.colors.menuItemHoverText};
    }
`;

const SeeAllIcon = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: inherit;

    svg {
        width: 13px;
        height: 13px;
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

/**
 * Pull the best available thumbnail URL from a post search hit. Checks
 * the explicit `thumbnail` field first, then falls back to the first
 * image-like entry in a `media` array if present.
 */
function getPostThumbnail(post) {
    if (!post) return "";
    if (typeof post.thumbnail === "string" && post.thumbnail.trim()) {
        return post.thumbnail.trim();
    }
    if (Array.isArray(post.media) && post.media.length > 0) {
        for (const m of post.media) {
            if (!m) continue;
            if (typeof m === "string" && m.trim()) return m.trim();
            if (typeof m === "object") {
                const url = m.url || m.thumbnail || m.src || "";
                if (typeof url === "string" && url.trim()) return url.trim();
            }
        }
    }
    return "";
}

export default function SearchDropdown({
    rawQuery,
    hasQuery,
    isSearching,
    liveResults,
    liveError,
    hasLiveResults,
    trendingTopics,
    isLoadingTrending,
    recentSearches,
    onRecentClick,
    onRemoveRecent,
    onClearRecents,
    onResultNavigate,
    onSubmitQuery,
}) {
    // --- Idle state: recents + trending -----------------------------------
    const idleView = useMemo(
        () => (
            <>
                {recentSearches.length > 0 && (
                    <>
                        <SectionLabelRow>
                            <SectionLabel>Recent</SectionLabel>
                            <ClearAllButton
                                type="button"
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={onClearRecents}
                            >
                                Clear all
                            </ClearAllButton>
                        </SectionLabelRow>
                        {recentSearches.map((entry) => (
                            <RowButton
                                key={entry.id}
                                type="button"
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => onRecentClick(entry)}
                            >
                                <RowIcon>
                                    <HiOutlineClock />
                                </RowIcon>
                                <RowMain>
                                    <RowPrimary>{entry.query}</RowPrimary>
                                </RowMain>
                                <RowRemove
                                    type="button"
                                    aria-label={`Remove ${entry.query}`}
                                    onMouseDown={(e) => e.preventDefault()}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        onRemoveRecent(entry.id);
                                    }}
                                >
                                    <HiOutlineXMark />
                                </RowRemove>
                            </RowButton>
                        ))}
                        <SectionDivider />
                    </>
                )}

                <SectionLabelRow>
                    <SectionLabel>Trending topics</SectionLabel>
                </SectionLabelRow>

                {isLoadingTrending && (
                    <EmptyBlock>Loading trending topics…</EmptyBlock>
                )}

                {!isLoadingTrending && trendingTopics.length === 0 && (
                    <EmptyBlock>No trending topics available</EmptyBlock>
                )}

                {!isLoadingTrending &&
                    trendingTopics.map((topic) => (
                        <RowLink
                            key={`trending-${topic.topic}`}
                            to={`/t/${encodeURIComponent(topic.topic)}`}
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => onResultNavigate && onResultNavigate()}
                        >
                            <RowIcon>
                                <HiOutlineFire />
                            </RowIcon>
                            <RowMain>
                                <RowPrimary>{topic.topic}</RowPrimary>
                                <RowSecondary>
                                    {formatPostCount(topic.post_count || topic.count)}
                                </RowSecondary>
                            </RowMain>
                        </RowLink>
                    ))}
            </>
        ),
        [
            recentSearches,
            trendingTopics,
            isLoadingTrending,
            onClearRecents,
            onRecentClick,
            onRemoveRecent,
            onResultNavigate,
        ]
    );

    // --- Typing state: live results ---------------------------------------
    const liveView = useMemo(() => {
        const { posts, topics, users } = liveResults;

        if (liveError) return <ErrorBlock>{liveError}</ErrorBlock>;

        // While a new search is in flight we keep any existing results
        // visible so the sheet doesn't flash empty between keystrokes.
        if (isSearching && !hasLiveResults) {
            return <EmptyBlock>Searching…</EmptyBlock>;
        }

        if (!isSearching && !hasLiveResults) {
            return (
                <EmptyBlock>
                    No matches for “{rawQuery.trim()}”. Press Enter to see all
                    results.
                </EmptyBlock>
            );
        }

        return (
            <>
                {topics.length > 0 && (
                    <>
                        <SectionLabelRow>
                            <SectionLabel>Topics</SectionLabel>
                        </SectionLabelRow>
                        {topics.map((topic) => (
                            <RowLink
                                key={`live-topic-${topic.topic}`}
                                to={`/t/${encodeURIComponent(topic.topic)}`}
                                onMouseDown={(e) => e.preventDefault()}
                                onClick={() => onResultNavigate && onResultNavigate()}
                            >
                                <RowIcon>
                                    <HiOutlineHashtag />
                                </RowIcon>
                                <RowMain>
                                    <RowPrimary>{topic.topic}</RowPrimary>
                                    {(topic.post_count || topic.count) && (
                                        <RowSecondary>
                                            {formatPostCount(topic.post_count || topic.count)}
                                        </RowSecondary>
                                    )}
                                </RowMain>
                            </RowLink>
                        ))}
                    </>
                )}

                {users.length > 0 && (
                    <>
                        {topics.length > 0 && <SectionDivider />}
                        <SectionLabelRow>
                            <SectionLabel>Users</SectionLabel>
                        </SectionLabelRow>
                        {users.map((user) => {
                            const tierColor = getAuthorColor(
                                user.level,
                                user.user_is_new
                            );
                            return (
                                <RowLink
                                    key={`live-user-${user.address}`}
                                    to={`/u/${encodeURIComponent(
                                        user.username || user.address
                                    )}`}
                                    onMouseDown={(e) => e.preventDefault()}
                                    onClick={() =>
                                        onResultNavigate && onResultNavigate()
                                    }
                                >
                                    <RowAvatar seed={user.address} alt="" />
                                    <RowMain>
                                        <RowPrimary>
                                            <TierUsername $tierColor={tierColor}>
                                                @{user.username || shortAddress(user.address)}
                                            </TierUsername>
                                        </RowPrimary>
                                        <RowSecondary>
                                            {shortAddress(user.address)}
                                        </RowSecondary>
                                    </RowMain>
                                </RowLink>
                            );
                        })}
                    </>
                )}

                {posts.length > 0 && (
                    <>
                        {(topics.length > 0 || users.length > 0) && <SectionDivider />}
                        <SectionLabelRow>
                            <SectionLabel>Posts</SectionLabel>
                        </SectionLabelRow>
                        {posts.map((post) => {
                            const tierColor = getAuthorColor(
                                post.author_level || post.level,
                                post.author_is_new || post.new_user
                            );
                            const preview =
                                post.title ||
                                (post.content
                                    ? String(post.content).slice(0, 80)
                                    : "");
                            const thumbUrl = getPostThumbnail(post);
                            return (
                                <RowLink
                                    key={`live-post-${post.post_id}`}
                                    to={`/p/${post.post_id}`}
                                    onMouseDown={(e) => e.preventDefault()}
                                    onClick={() =>
                                        onResultNavigate && onResultNavigate()
                                    }
                                >
                                    {thumbUrl ? (
                                        <PostThumb $src={thumbUrl}>
                                            <PostThumbImg
                                                src={thumbUrl}
                                                alt=""
                                                loading="lazy"
                                            />
                                        </PostThumb>
                                    ) : (
                                        <PostPlaceholderAvatar
                                            address={post.address}
                                            username={post.username}
                                            size={28}
                                            mobileSize={28}
                                        />
                                    )}
                                    <RowMain>
                                        <RowPrimary>{preview || "Untitled"}</RowPrimary>
                                        <RowSecondary>
                                            <TierUsername $tierColor={tierColor}>
                                                @{post.username || "anonymous"}
                                            </TierUsername>
                                            {post.topic && ` · #${post.topic}`}
                                        </RowSecondary>
                                    </RowMain>
                                </RowLink>
                            );
                        })}
                    </>
                )}

                <SeeAllRow
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => onSubmitQuery && onSubmitQuery(rawQuery)}
                >
                    <SeeAllIcon>
                        <HiOutlineMagnifyingGlass />
                    </SeeAllIcon>
                    See all results for “{rawQuery.trim()}”
                </SeeAllRow>
            </>
        );
    }, [
        liveError,
        isSearching,
        hasLiveResults,
        liveResults,
        rawQuery,
        onResultNavigate,
        onSubmitQuery,
    ]);

    return <Sheet role="listbox">{hasQuery ? liveView : idleView}</Sheet>;
}
