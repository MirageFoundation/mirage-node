import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { Link, Navigate } from "react-router-dom";
import MobileHeader from "../components/MobileHeader.js";
import Button from "../components/Button.js";
import CardView from "../components/CardView.js";
import { ContentGrid, ModernPostFeed, PostGrid, AnimatedCard } from "../Layout";
import { getAuthorColor, getAuthorTooltip } from "../../../utils/tierColors";
import { useSearchResults, tagColors } from "../../../logic/useSearchResults";
const SectionHeader = styled.div`
    font-size: ${({
  theme
}) => theme.layout.labelSize};
    font-weight: 600;
    color: ${({
  theme
}) => theme.colors.subtleText};
    margin: ${({
  theme
}) => theme.layout.sectionMarginTop};
    
    &:first-child {
        margin-top: 0;
    }
`;
const ItemRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: ${({
  theme
}) => theme.layout.cardPadding};
    border: ${({
  theme
}) => theme.layout.cardBorder};
    border-bottom: ${({
  theme
}) => theme.layout.cardBorderBottom};
    border-radius: ${({
  theme
}) => theme.layout.cardRadius};
    margin-bottom: ${({
  theme
}) => theme.layout.sectionMarginBottom};
    background: ${({
  theme
}) => theme.layout.cardBg};
    font-size: ${({
  theme
}) => theme.layout.inputSize};
    gap: 0.5rem;

    @media (max-width: 700px) {
        flex-direction: column;
        align-items: flex-start;
    }
`;
const ItemLeft = styled.div`
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0.4rem;
    flex-wrap: wrap;
`;
const Subtle = styled.span`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-weight: bold;
    font-size: ${({
  theme
}) => theme.layout.smallSize};
`;
const ItemLink = styled(Link)`
    color: ${({
  $tierColor,
  theme
}) => $tierColor} !important;
    text-decoration: none;
    font-weight: bold;
    position: relative;
    &:hover { color: ${({
  $tierColor,
  theme
}) => $tierColor} !important; }

    &::after {
        content: attr(data-tooltip);
        position: absolute;
        bottom: 100%;
        left: 0;
        margin-bottom: 0.3rem;
        background: ${({
  theme
}) => theme.layout.cardBg};
        border: 1px solid ${({
  theme
}) => theme.colors.border};
        color: ${({
  theme
}) => theme.colors.text};
        padding: ${({
  theme
}) => theme.layout.inputPadding};
        border-radius: ${({
  theme
}) => theme.layout.inputRadius};
        font-size: ${({
  theme
}) => theme.layout.smallSize};
        font-weight: normal;
        white-space: nowrap;
        z-index: 1000;
        box-shadow: ${({
  theme
}) => theme.layout.focusRing};
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.15s ease;
    }

    &[data-tooltip]:hover::after {
        opacity: 1;
    }
`;
const CountText = styled.span`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-weight: normal;
    font-size: ${({
  theme
}) => theme.layout.tinySize};
`;
const EmptyMessage = styled.div`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-size: ${({
  theme
}) => theme.layout.monoSize};
    padding: ${({
  theme
}) => theme.layout.containerPadding};
    text-align: center;
`;
const LoadingMessage = styled.div`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-size: ${({
  theme
}) => theme.layout.monoSize};
    text-align: center;
    padding: ${({
  theme
}) => theme.layout.containerPadding};
`;
const ErrorMessage = styled.div`
    color: #f87171;
    font-size: ${({
  theme
}) => theme.layout.monoSize};
    text-align: center;
    padding: ${({
  theme
}) => theme.layout.containerPadding};
`;
const TagBadge = styled.span`
    display: inline-flex;
    align-items: center;
    padding: ${({
  theme
}) => theme.layout.buttonPadding};
    border-radius: ${({
  theme
}) => theme.layout.containerRadius};
    background: ${({
  $tag
}) => tagColors[$tag]?.bg || tagColors.default.bg};
    color: ${({
  $tag
}) => tagColors[$tag]?.text || tagColors.default.text};
    font-size: ${({
  theme
}) => theme.layout.tinySize};
    font-weight: 700;
    text-transform: lowercase;
    border: 1px solid ${({
  $tag
}) => tagColors[$tag]?.border || tagColors.default.border};
`;
const LoadMoreButton = styled.div`
    display: flex;
    justify-content: center;
    padding: ${({
  theme
}) => theme.layout.containerPaddingCompact};
    margin-top: ${({
  theme
}) => theme.layout.sectionMarginBottom};

    @media (max-width: 700px) {
        button { width: 100%; }
    }
`;
const UserMeta = styled.span`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-size: ${({
  theme
}) => theme.layout.tinySize};
    font-weight: normal;
`;
export default function SearchResultsView({
  state
}) {
  const {
    location,
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
    isLoggedIn
  } = useSearchResults({
    state
  });
  // Redirect non-logged-in users to home (shows welcome banner)
  if (!isLoggedIn) {
    return <Navigate to="/home" replace />;
  }
  return <ContentGrid>
            <Helmet>
                <title>{query ? `Search: ${query}` : 'Search'} | Mirage</title>
            </Helmet>
            <div>
                <ModernPostFeed>
                    <MobileHeader />

                    {!query && <EmptyMessage>Enter a search term to find topics, users, and posts.</EmptyMessage>}

                    {query && loading && <LoadingMessage>Searching...</LoadingMessage>}

                    {query && error && <ErrorMessage>{error}</ErrorMessage>}

                    {query && !loading && !error && <>
                            {!hasResults && <EmptyMessage>No results found for "{displayQuery}"</EmptyMessage>}

                            {/* Users Section */}
                            {users.length > 0 && <>
                                    <SectionHeader>Users matching "{displayQuery}"</SectionHeader>
                                    {users.map(user => <ItemRow key={user.address}>
                                            <ItemLeft>
                                                <ItemLink to={`/u/${encodeURIComponent(user.username || user.address)}`} $tierColor={getAuthorColor(user.level, user.user_is_new)} data-tooltip={getAuthorTooltip(user.level, user.user_is_new)}>
                                                    @{user.username}
                                                </ItemLink>
                                                <UserMeta>
                                                    {user.post_count || 0} posts
                                                    {user.created_at && ` · joined ${formatDate(user.created_at)}`}
                                                </UserMeta>
                                            </ItemLeft>
                                        </ItemRow>)}
                                    {hasMoreUsers && <LoadMoreButton>
                                            <Button variant="subtle" size="sm" onClick={loadMoreUsers} loading={loadingMoreUsers} disabled={loadingMoreUsers}>
                                                {loadingMoreUsers ? 'Loading...' : 'Load More Users'}
                                            </Button>
                                        </LoadMoreButton>}
                                </>}

                            {/* Topics Section */}
                            {topics.length > 0 && <>
                                    <SectionHeader>Topics matching "{displayQuery}"</SectionHeader>
                                    {topics.map(t => <ItemRow key={`topic-${t.topic}`}>
                                            <ItemLeft>
                                                <Subtle>#</Subtle>
                                                <ItemLink to={`/t/${encodeURIComponent(t.topic)}`}>{t.topic}</ItemLink>
                                                {t.dominant_tag && <TagBadge $tag={t.dominant_tag}>{t.dominant_tag}</TagBadge>}
                                                <CountText>({t.post_count || 0} posts)</CountText>
                                            </ItemLeft>
                                        </ItemRow>)}
                                    {hasMoreTopics && <LoadMoreButton>
                                            <Button variant="subtle" size="sm" onClick={loadMoreTopics} loading={loadingMoreTopics} disabled={loadingMoreTopics}>
                                                {loadingMoreTopics ? 'Loading...' : 'Load More Topics'}
                                            </Button>
                                        </LoadMoreButton>}
                                </>}

                            {/* Posts Section */}
                            {posts.length > 0 && <>
                                    <SectionHeader>Posts matching "{displayQuery}"</SectionHeader>
                                    <PostGrid>
                                        {posts.map((post, index) => {
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
                  direction: post.user_vote
                };
                return <AnimatedCard key={post.post_id} style={{
                  animationDelay: `${index * 30}ms`
                }} onClick={() => {
                  try {
                    window.sessionStorage.setItem('mirage_post_referrer', 'search');
                  } catch (_) {}
                }}>
                                                    <CardView post={postObj} state={state} />
                                                </AnimatedCard>;
              })}
                                    </PostGrid>
                                    {hasMorePosts && <LoadMoreButton>
                                            <Button variant="subtle" size="sm" onClick={loadMorePosts} loading={loadingMorePosts} disabled={loadingMorePosts}>
                                                {loadingMorePosts ? 'Loading...' : 'Load More Posts'}
                                            </Button>
                                        </LoadMoreButton>}
                                </>}
                        </>}
                </ModernPostFeed>
            </div>
        </ContentGrid>;
}