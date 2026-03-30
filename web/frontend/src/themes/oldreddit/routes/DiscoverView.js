import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { Link } from "react-router-dom";
import Button from "../components/Button.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody, CappedPageColumn, OldRedditContentBleed } from "../Layout";
import { useDiscover, tagColors } from "../../../logic/useDiscover";

const TopicsListShell = styled.div`
    display: flex;
    flex-direction: column;
    width: 100%;
    min-width: 0;
    box-sizing: border-box;
    background: ${({ theme }) => theme.colors.panel};

    & > *:last-child {
        border-bottom: none;
    }
`;

/** Search row — padded like topic rows; rule below is a sibling `OldRedditContentBleed` so it spans shell width. */
const TopicsSearchStrip = styled.div`
    background: ${({ theme }) => theme.colors.panel};
    margin-top: ${({ theme }) => theme.layout.tabbedMarginTop};
`;

/** Full-width divider under search (bleed cancels shell horizontal padding; search + list stay in `CappedPageColumn`). */
const TopicsSearchFullBleedRule = styled.div`
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    width: 100%;
    box-sizing: border-box;
`;

/** No extra horizontal inset — shell `Container` already matches the top bar; avoids double padding vs. MIRAGE. */
const TopicsSearchInner = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
    box-sizing: border-box;
    padding: 0.4rem 0;
`;

const SearchInputWedged = styled.input`
    width: 100%;
    padding: 0.25rem 0.5rem;
    margin: 0;
    background-color: ${({ theme }) => theme.colors.panelAlt};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: ${({ theme }) => theme.layout.inputRadius};
    color: ${({ theme }) => theme.colors.text};
    font-size: ${({ theme }) => theme.layout.inputSize};
    font-family: inherit;
    box-sizing: border-box;
    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.link};
    }
`;

const DiscoverContainerBody = styled(ContainerBody)`
    padding: 0;
`;

const DiscoverTabbedContainer = styled(TabbedContainer)`
    margin-top: 0;
`;

const ItemRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.4rem 0;
    font-size: ${({
    theme
}) => theme.layout.smallSize};
    gap: 0.4rem;
    transition: background-color 0.12s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.accentHover};
    }

    @media (max-width: 700px) {
        flex-direction: column;
        align-items: flex-start;
    }
`;
const ItemLeft = styled.div`
    display: flex;
    flex-direction: row;
    align-items: baseline;
    gap: 0.3rem;
    flex-wrap: wrap;
`;
const ItemRight = styled.div`
    display: flex;
    margin-left: auto;

    @media (max-width: 700px) {
        width: 100%;

        button {
            width: 100%;
        }
    }
`;
const Subtle = styled.span`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-weight: bold;
    font-size: 0.6rem;
`;
const ItemLink = styled(Link)`
    color: ${({
    theme
}) => theme.colors.link};
    text-decoration: none;
    font-weight: bold;
    &:hover { color: ${({
    theme
}) => theme.colors.linkHover}; }
`;
const CountText = styled.span`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-weight: normal;
    font-size: 0.65rem;
`;
const TopicsStatusRow = styled.div`
    padding: 0.65rem 0;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
`;

const MoreTopicsHint = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    font-style: italic;
    text-align: center;
    padding: 0.5rem 0;
    border-top: ${({ $showTopDivider, theme }) =>
        $showTopDivider === false ? 'none' : `1px solid ${theme.colors.border}`};
`;
const TagBadge = styled.span`
    display: inline-flex;
    align-items: center;
    padding: 0.05rem 0.35rem;
    border-radius: 999px;
    background: ${({
    $tag
}) => tagColors[$tag]?.bg || tagColors.default.bg};
    color: ${({
    $tag
}) => tagColors[$tag]?.text || tagColors.default.text};
    font-size: 0.55rem;
    font-weight: 700;
    text-transform: lowercase;
    border: 1px solid ${({
    $tag
}) => tagColors[$tag]?.border || tagColors.default.border};
    margin-left: 0.3rem;
`;
export default function DiscoverView({
    state
}) {
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
        handleSubscribeToggle
    } = useDiscover({
        state
    });
    return <ContentGrid>
        <Helmet>
            <title>Topics | Mirage</title>
        </Helmet>
        <ModernPostFeed>
            <MobileHeader />
            <CappedPageColumn>
                <TopicsSearchStrip>
                    <TopicsSearchInner>
                        <SearchInputWedged type="text" placeholder="Search topics..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} aria-label="Search topics" />
                    </TopicsSearchInner>
                </TopicsSearchStrip>
            </CappedPageColumn>
            <OldRedditContentBleed>
                <TopicsSearchFullBleedRule aria-hidden="true" />
            </OldRedditContentBleed>
            <CappedPageColumn>
                <DiscoverTabbedContainer>
                    <ContainerTab>Discover</ContainerTab>
                    <DiscoverContainerBody>
                        <TopicsListShell>
                            {loading ? <TopicsStatusRow>Loading topics...</TopicsStatusRow> : filteredTopics.length === 0 && searchResults.length === 0 && !isSearching ? <TopicsStatusRow>
                                {searchTerm.trim() ? 'No topics match your search' : 'No topics found'}
                            </TopicsStatusRow> : <>
                                {filteredTopics.map(t => {
                                    const topicLower = t.topic.toLowerCase();
                                    const isFollowing = isSubscribedTopic(t.topic);
                                    const isInProgress = isTopicPending(topicLower);
                                    return <ItemRow key={`topic-${t.topic}`}>
                                        <ItemLeft>
                                            <Subtle>#</Subtle>
                                            <ItemLink to={`/t/${t.topic}`}>{t.topic}</ItemLink>
                                            {t.dominant_tag && <TagBadge $tag={t.dominant_tag}>{t.dominant_tag}</TagBadge>}
                                            <CountText>
                                                ({t.post_count || 0} posts, {t.comment_count || 0} comments)
                                            </CountText>
                                        </ItemLeft>
                                        <ItemRight>
                                            <Button variant={isFollowing && hoverTopic === topicLower ? 'primaryDanger' : isFollowing ? 'subtle' : 'primary'} size="sm" minWidth="follow" disabled={isInProgress} loading={isInProgress} onMouseEnter={() => setHoverTopic(topicLower)} onMouseLeave={() => setHoverTopic(null)} onClick={() => handleSubscribeToggle(t.topic)}>
                                                {isInProgress ? formatTopicStatus(topicLower) : isFollowing ? hoverTopic === topicLower ? 'Unfollow' : 'Following' : 'Follow'}
                                            </Button>
                                        </ItemRight>
                                    </ItemRow>;
                                })}
                                {searchResults.length > 0 && <>
                                    <MoreTopicsHint $showTopDivider={filteredTopics.length > 0} style={{
                                        fontStyle: 'normal',
                                        fontWeight: 600
                                    }}>
                                        Topics with fewer than 10 posts
                                    </MoreTopicsHint>
                                    {searchResults.map(t => {
                                        const topicLower = t.topic.toLowerCase();
                                        const isFollowing = isSubscribedTopic(t.topic);
                                        const isInProgress = isTopicPending(topicLower);
                                        return <ItemRow key={`search-${t.topic}`}>
                                            <ItemLeft>
                                                <Subtle>#</Subtle>
                                                <ItemLink to={`/t/${t.topic}`}>{t.topic}</ItemLink>
                                                {t.dominant_tag && <TagBadge $tag={t.dominant_tag}>{t.dominant_tag}</TagBadge>}
                                                <CountText>
                                                    ({t.post_count || 0} posts, {t.comment_count || 0} comments)
                                                </CountText>
                                            </ItemLeft>
                                            <ItemRight>
                                                <Button variant={isFollowing && hoverTopic === topicLower ? 'primaryDanger' : isFollowing ? 'subtle' : 'primary'} size="sm" minWidth="follow" disabled={isInProgress} loading={isInProgress} onMouseEnter={() => setHoverTopic(topicLower)} onMouseLeave={() => setHoverTopic(null)} onClick={() => handleSubscribeToggle(t.topic)}>
                                                    {isInProgress ? formatTopicStatus(topicLower) : isFollowing ? hoverTopic === topicLower ? 'Unfollow' : 'Following' : 'Follow'}
                                                </Button>
                                            </ItemRight>
                                        </ItemRow>;
                                    })}
                                </>}
                                {isSearching && <TopicsStatusRow>Searching for more topics...</TopicsStatusRow>}
                                {!searchTerm.trim() && smallTopicsCount > 0 && <MoreTopicsHint>
                                    and {smallTopicsCount} more topic{smallTopicsCount !== 1 ? 's' : ''} with fewer than 10 posts
                                </MoreTopicsHint>}
                            </>}
                        </TopicsListShell>
                    </DiscoverContainerBody>
                </DiscoverTabbedContainer>
            </CappedPageColumn>
        </ModernPostFeed>
    </ContentGrid>;
}