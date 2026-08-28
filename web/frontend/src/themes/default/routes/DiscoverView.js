import { communityLabel, communityPath } from '../../../utils/community';
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
import { useDiscover } from "../../../logic/useDiscover";
import { normalizeTag } from "../../../utils/ContentTags";
import ContentTagBadge from "../components/ContentTagBadge";

/**
 * DiscoverView — `default` Plan 06 sub-plan 07.
 *
 * Rules (`docs/guides/web-theme-default/RULES.md`):
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
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.25rem 1rem 0.5rem;

    @media (max-width: 600px) {
        padding: 0.25rem 0 0.5rem;
    }
`;

const HeaderTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

const SearchRow = styled.div`
    padding: 0 1rem 0.6rem;

    @media (max-width: 600px) {
        padding: 0 0 0.6rem;
    }
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

    @media (max-width: 600px) {
        padding: 0.65rem 0 0.35rem;
    }
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
        padding: 0.6rem 0;
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

    @media (max-width: 600px) {
        padding: 0.85rem 0 0.25rem;
    }
`;

function formatRowMeta(t) {
    if (!t.curated) return `Uncurated · ${t.post_count} posts`;
    return `Curated · ${t.live_team_count} teams · ${t.post_count} posts · Default: ${t.default_team.name} (${t.default_team.subscriber_count} subscribers)`;
}

function getToggleLabel({ isJoined, hovering, pending, status }) {
    if (pending) return status || (isJoined ? 'Leaving…' : 'Joining…');
    if (isJoined) return hovering ? 'Leave' : 'Joined';
    return 'Join';
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
        error,
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
                <title>Communities | Mirage</title>
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
            </FeedRailRow>
        </ContentGrid>
    );

    const hasQuery = Boolean(searchTerm.trim());
    const showSmallHint = !hasQuery && smallTopicsCount > 0;

    const headerBlock = (
        <>
            <HeaderRow>
                <HeaderTitle>Communities</HeaderTitle>
                <Button to="/curator-teams/new" variant="primary" size="sm">
                    Create curator team
                </Button>
            </HeaderRow>
            <SearchRow>
                <SearchField>
                    <HiMagnifyingGlass className="search-icon" aria-hidden="true" />
                    <SearchInput
                        type="search"
                        placeholder="Search communities"
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        aria-label="Search communities"
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

    if (error) {
        return renderShell(<><HeaderRow><HeaderTitle>Communities</HeaderTitle></HeaderRow><StateBlock><StateTitle>Couldn’t load communities</StateTitle><StateMessage>{error}</StateMessage></StateBlock></>);
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
                        {hasQuery ? 'No communities match your search' : 'No communities yet'}
                    </StateTitle>
                    <StateMessage>
                        {hasQuery
                            ? 'Try a different slug. Any valid slug can be used when composing a post.'
                            : 'Compose a post with any valid slug to start a community.'}
                    </StateMessage>
                    <Button to="/create_post" variant="primary" size="sm">
                        Create post
                    </Button>
                </StateBlock>
            </>
        );
    }

    const renderRow = (t, keyPrefix) => {
        const topicLower = t.topic.toLowerCase();
        const isJoined = isSubscribedTopic(t.topic);
        const pending = isTopicPending(topicLower);
        const hovering = hoverTopic === topicLower;
        const tag = t.dominant_tag ? normalizeTag(t.dominant_tag) : null;
        const meta = formatRowMeta(t);

        return (
            <Row key={`${keyPrefix}-${t.topic}`}>
                <RowMain>
                    <TopicLine>
                        <TopicLink to={communityPath(t.topic)}>{communityLabel(t.topic)}</TopicLink>
                        {tag && <ContentTagBadge tag={tag} />}
                    </TopicLine>
                    {meta ? <RowMeta>{meta}</RowMeta> : null}
                </RowMain>
                <RowActions>
                    <Button
                        variant={isJoined && hovering ? 'primaryDanger' : isJoined ? 'subtle' : 'primary'}
                        size="sm"
                        minWidth="5.5rem"
                        disabled={pending}
                        loading={pending}
                        onMouseEnter={() => setHoverTopic(topicLower)}
                        onMouseLeave={() => setHoverTopic(null)}
                        onClick={() => handleSubscribeToggle(t.topic)}
                    >
                        {getToggleLabel({
                            isJoined,
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
                        <span>{hasQuery ? 'Matching communities' : 'All communities'}</span>
                        <CountBadge>{filteredTopics.length}</CountBadge>
                    </SectionHeader>
                    <List>{filteredTopics.map((t) => renderRow(t, 'topic'))}</List>
                </>
            )}

            {searchResults.length > 0 && (
                <>
                    <SectionHeader>
                        <span>More communities</span>
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
                    and {smallTopicsCount} more communit{smallTopicsCount !== 1 ? 'ies' : 'y'} with fewer than 10 posts
                </FootHint>
            )}
        </>
    );
}
