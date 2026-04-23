import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { Link } from "react-router-dom";
import {
    HiHashtag,
    HiMagnifyingGlass,
    HiXMark,
} from "react-icons/hi2";
import Button from "../components/Button.js";
import { ListRowSkeletonList, ListRowSkeleton, PageHeaderSkeleton } from "../components/Skeleton.js";
import {
    ContentGrid,
    ModernPostFeed,
    TabbedContainer,
    ContainerBody,
} from "../Layout";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import FeedRightRail from "../components/FeedRightRail.js";
import { useDiscover, tagColors } from "../../../logic/useDiscover";
import { normalizeTag } from "../../../utils/ContentTags";

/**
 * DiscoverView — `mirageapp` Plan 06 sub-plan 07.
 *
 * Rules (`docs/guides/web-theme-mirageapp/RULES.md`):
 *  - R1 search + list sit on `theme.colors.bg`.
 *  - R2 every color routed through a token (topic tag badge still uses
 *    `tagColors` from the shared `useDiscover` util which already pairs
 *    bg/border/text — left unchanged per R4 "do not hard-code tag
 *    icon / color").
 *  - R3 no row dividers (matches AgentsView decision).
 *  - R4 data parity with `themes/bluemoon/routes/DiscoverView.js`;
 *    visual language from `mirage-mobile-app/src/pages/topics-list-screen.tsx`
 *    (search pill on top, topic rows with `#topic`, post/comment meta,
 *    Follow action on the right).
 *  - R5 search input focuses on `borderStrong` with no blue ring.
 *  - R7 page heading 1.1rem/700, section label 0.6rem/700 uppercase,
 *    row title 0.75rem/500, meta 0.62rem/500 subtle.
 */

const DiscoverWrap = styled.div`
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
`;

const HeaderTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

const SearchRow = styled.div`
    padding: 0 1rem 0.6rem;
`;

const SearchField = styled.label`
    position: relative;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    height: 2.1rem;
    padding: 0 0.6rem;
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 9999px;
    transition: border-color 0.15s ease;

    &:hover {
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    &:focus-within {
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    svg.search-icon {
        width: 14px;
        height: 14px;
        flex-shrink: 0;
        color: ${({ theme }) => theme.colors.subtleText};
    }
`;

const SearchInput = styled.input`
    flex: 1;
    min-width: 0;
    background: transparent;
    border: none;
    outline: none;
    color: ${({ theme }) => theme.colors.text};
    font-family: inherit;
    font-size: 0.75rem;
    font-weight: 500;

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
    }

    /* Hide the browser's native type="search" clear button — we render our own. */
    &::-webkit-search-cancel-button,
    &::-webkit-search-decoration,
    &::-webkit-search-results-button,
    &::-webkit-search-results-decoration {
        -webkit-appearance: none;
        appearance: none;
        display: none;
    }
`;

const ClearButton = styled.button`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.4rem;
    height: 1.4rem;
    border: none;
    background: transparent;
    color: ${({ theme }) => theme.colors.subtleText};
    border-radius: 50%;
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;

    svg {
        width: 18px;
        height: 18px;
    }

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
        color: ${({ theme }) => theme.colors.text};
    }
`;

const SectionHeader = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.65rem 1rem 0.35rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
`;

const CountBadge = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    background: ${({ theme }) => theme.colors.surface2};
    font-size: 0.6rem;
    font-weight: 600;
    padding: 0.05rem 0.4rem;
    border-radius: 999px;
    letter-spacing: 0;
    text-transform: none;
    line-height: 1.4;
`;

const List = styled.div`
    display: flex;
    flex-direction: column;
`;

const Row = styled.div`
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.65rem 1rem;
    background: transparent;
    transition: background-color 0.15s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    @media (max-width: 600px) {
        padding: 0.6rem 0.85rem;
    }
`;

const RowIconWrap = styled.span`
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
        width: 15px;
        height: 15px;
    }
`;

const RowMain = styled.div`
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
`;

const TopicLine = styled.div`
    display: flex;
    align-items: center;
    gap: 0.35rem;
    min-width: 0;
    flex-wrap: wrap;
`;

const TopicLink = styled(Link)`
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    font-size: 0.75rem;
    font-weight: 500;
    line-height: 1.25;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;

    &:hover {
        color: ${({ theme }) => theme.colors.link};
    }
`;

const TagBadge = styled.span`
    display: inline-flex;
    align-items: center;
    padding: 0.05rem 0.35rem;
    border-radius: 999px;
    background: ${({ $tag }) => tagColors[$tag]?.bg || tagColors.default.bg};
    color: ${({ $tag }) => tagColors[$tag]?.text || tagColors.default.text};
    font-size: 0.55rem;
    font-weight: 700;
    text-transform: lowercase;
    border: 1px solid ${({ $tag }) => tagColors[$tag]?.border || tagColors.default.border};
`;

const RowMeta = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.3;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const RowActions = styled.div`
    flex-shrink: 0;
    display: flex;
    align-items: center;
`;

/* ----- Empty / loading / error states ----- */

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
        color: ${({ $tone, theme }) =>
            $tone === 'danger' ? theme.colors.voteDown : theme.colors.subtleText};
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

const FootHint = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    font-weight: 500;
    text-align: center;
    padding: 0.85rem 1rem 0.25rem;
`;

function formatCountMeta(t) {
    const posts = Number(t.post_count || 0);
    const comments = Number(t.comment_count || 0);
    return `${posts.toLocaleString()} post${posts === 1 ? '' : 's'} · ${comments.toLocaleString()} comment${comments === 1 ? '' : 's'}`;
}

function getToggleLabel({ isFollowing, hovering, pending, status }) {
    if (pending) return status || (isFollowing ? 'Unfollowing…' : 'Following…');
    if (isFollowing) return hovering ? 'Unfollow' : 'Following';
    return 'Follow';
}

export default function DiscoverView({ state }) {
    const {
        filteredTopics,
        smallTopicsCount,
        searchTerm,
        setSearchTerm,
        searchResults,
        isSearching,
        loading,
        hoverTopic,
        setHoverTopic,
        isTopicPending,
        formatTopicStatus,
        isSubscribedTopic,
        handleSubscribeToggle,
    } = useDiscover({ state });

    const renderShell = (body) => (
        <ContentGrid>
            <Helmet>
                <title>Topics | Mirage</title>
            </Helmet>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
                    <ModernPostFeed>
                        <TabbedContainer>
                            <ContainerBody $fullWidth>
                                <DiscoverWrap>{body}</DiscoverWrap>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </FeedCol>
                <FeedRightRail />
            </FeedRailRow>
        </ContentGrid>
    );

    const hasQuery = Boolean(searchTerm.trim());
    const showSmallHint = !hasQuery && smallTopicsCount > 0;

    const headerBlock = (
        <>
            <HeaderRow>
                <HeaderTitle>Topics</HeaderTitle>
            </HeaderRow>
            <SearchRow>
                <SearchField>
                    <HiMagnifyingGlass className="search-icon" aria-hidden="true" />
                    <SearchInput
                        type="search"
                        placeholder="Search topics"
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        aria-label="Search topics"
                    />
                    {hasQuery && (
                        <ClearButton
                            type="button"
                            onClick={() => setSearchTerm('')}
                            aria-label="Clear search"
                        >
                            <HiXMark />
                        </ClearButton>
                    )}
                </SearchField>
            </SearchRow>
        </>
    );

    if (loading) {
        return renderShell(
            <>
                <PageHeaderSkeleton />
                <ListRowSkeletonList count={8} />
            </>
        );
    }

    const topicsEmpty = filteredTopics.length === 0 && searchResults.length === 0 && !isSearching;

    if (topicsEmpty) {
        return renderShell(
            <>
                {headerBlock}
                <StateBlock>
                    <StateIcon>
                        <HiHashtag />
                    </StateIcon>
                    <StateTitle>
                        {hasQuery ? 'No topics match your search' : 'No topics yet'}
                    </StateTitle>
                    <StateMessage>
                        {hasQuery
                            ? 'Try a different keyword or check your spelling.'
                            : 'Topics will appear here as the community creates them.'}
                    </StateMessage>
                </StateBlock>
            </>
        );
    }

    const renderRow = (t, keyPrefix) => {
        const topicLower = t.topic.toLowerCase();
        const isFollowing = isSubscribedTopic(t.topic);
        const pending = isTopicPending(topicLower);
        const hovering = hoverTopic === topicLower;
        const tag = t.dominant_tag ? normalizeTag(t.dominant_tag) : null;

        return (
            <Row key={`${keyPrefix}-${t.topic}`}>
                <RowIconWrap aria-hidden="true">
                    <HiHashtag />
                </RowIconWrap>
                <RowMain>
                    <TopicLine>
                        <TopicLink to={`/t/${t.topic}`}>{t.topic}</TopicLink>
                        {tag && <TagBadge $tag={tag}>{tag}</TagBadge>}
                    </TopicLine>
                    <RowMeta>{formatCountMeta(t)}</RowMeta>
                </RowMain>
                <RowActions>
                    <Button
                        variant={isFollowing && hovering ? 'primaryDanger' : isFollowing ? 'subtle' : 'primary'}
                        size="sm"
                        minWidth="5.5rem"
                        disabled={pending}
                        loading={pending}
                        onMouseEnter={() => setHoverTopic(topicLower)}
                        onMouseLeave={() => setHoverTopic(null)}
                        onClick={() => handleSubscribeToggle(t.topic)}
                    >
                        {getToggleLabel({
                            isFollowing,
                            hovering,
                            pending,
                            status: formatTopicStatus(topicLower),
                        })}
                    </Button>
                </RowActions>
            </Row>
        );
    };

    return renderShell(
        <>
            {headerBlock}

            {filteredTopics.length > 0 && (
                <>
                    <SectionHeader>
                        <span>{hasQuery ? 'Matching topics' : 'All topics'}</span>
                        <CountBadge>{filteredTopics.length}</CountBadge>
                    </SectionHeader>
                    <List>{filteredTopics.map((t) => renderRow(t, 'topic'))}</List>
                </>
            )}

            {searchResults.length > 0 && (
                <>
                    <SectionHeader>
                        <span>Topics with fewer than 10 posts</span>
                        <CountBadge>{searchResults.length}</CountBadge>
                    </SectionHeader>
                    <List>{searchResults.map((t) => renderRow(t, 'search'))}</List>
                </>
            )}

            {isSearching && (
                <ListRowSkeleton />
            )}

            {showSmallHint && (
                <FootHint>
                    and {smallTopicsCount} more topic{smallTopicsCount !== 1 ? 's' : ''} with fewer than 10 posts
                </FootHint>
            )}
        </>
    );
}
