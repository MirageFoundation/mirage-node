import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { Link } from "react-router-dom";
import Sidebar from "../components/Sidebar.js";
import TopBar from "../components/TopBar.js";
import Button from "../components/Button.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../Layout";
import { useDiscover, tagColors } from "../../../logic/useDiscover";
const SearchInput = styled.input`
    width: 100%;
    padding: 0.4rem 0.6rem;
    margin-top: 0.5rem;
    margin-bottom: 0.5rem;
    background-color: ${({
  theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
  theme
}) => theme.colors.border};
    border-radius: ${({
  theme
}) => theme.layout.inputRadius};
    color: ${({
  theme
}) => theme.colors.text};
    font-size: ${({
  theme
}) => theme.layout.inputSize};
    font-family: inherit;
    &:focus {
        outline: none;
        border-color: ${({
  theme
}) => theme.colors.link};
    }
`;
const Section = styled.div`
    border: 1px solid ${({
  theme
}) => theme.colors.border};
    border-radius: ${({
  theme
}) => theme.layout.bannerRadius};
    margin: 0.5rem 0;
    padding: ${({
  theme
}) => theme.layout.cardPadding};
    background: ${({
  theme
}) => theme.colors.panelAlt};
`;
const SectionTitle = styled.div`
    font-weight: bold;
    font-size: ${({
  theme
}) => theme.layout.monoSize};
    margin-bottom: 0.4rem;
`;
const ItemRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.5rem 0;
    border-bottom: 1px solid ${({
  theme
}) => theme.colors.border};
    &:last-child { border-bottom: none; }
    font-size: ${({
  theme
}) => theme.layout.smallSize};
    gap: 0.4rem;

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
const EmptyMessage = styled.div`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-size: 0.7rem;
    padding: 0.5rem 0;
`;
const MoreTopicsHint = styled.div`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-size: 0.7rem;
    font-style: italic;
    text-align: center;
    padding: 0.6rem 0 0.3rem;
    border-top: 1px solid ${({
  theme
}) => theme.colors.border};
    margin-top: 0.3rem;
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
    handleSubscribeToggle,
    location
  } = useDiscover({
    state
  });
  return <ContentGrid>
            <Helmet>
                <title>Topics | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerTab>Discover</ContainerTab>
                        <ContainerBody>
                            <SearchInput type="text" placeholder="Search topics..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} />
                            <Section>
                                <SectionTitle>Topics</SectionTitle>
                                {loading ? <EmptyMessage>Loading topics...</EmptyMessage> : filteredTopics.length === 0 && searchResults.length === 0 && !isSearching ? <EmptyMessage>
                                        {searchTerm.trim() ? 'No topics match your search' : 'No topics found'}
                                    </EmptyMessage> : <>
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
                                                <MoreTopicsHint style={{
                    marginTop: filteredTopics.length > 0 ? '0.5rem' : 0,
                    borderTop: filteredTopics.length > 0 ? undefined : 'none',
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
                                        {isSearching && <EmptyMessage>Searching for more topics...</EmptyMessage>}
                                        {!searchTerm.trim() && smallTopicsCount > 0 && <MoreTopicsHint>
                                                and {smallTopicsCount} more topic{smallTopicsCount !== 1 ? 's' : ''} with fewer than 10 posts
                                            </MoreTopicsHint>}
                                    </>}
                            </Section>
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>;
}