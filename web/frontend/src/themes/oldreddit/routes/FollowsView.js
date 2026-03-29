import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, TabsRow, ClickableTab } from "../Layout";
import { useFollows, shortenAddress } from "../../../logic/useFollows";
const SectionTitle = styled.div`
    margin-top: ${({
  $first,
  theme
}) => $first ? '0' : theme.layout.sectionMarginTop};
    margin-bottom: ${({
  theme
}) => theme.layout.sectionMarginBottom};
    font-weight: 700;
    color: ${({
  theme
}) => theme.colors.text};
    font-size: ${({
  theme
}) => theme.layout.sectionSize};
    display: flex;
    align-items: center;
    gap: 0.5rem;

    &::after {
        content: '';
        flex: 1;
        height: 1px;
        background: ${({
  theme
}) => theme.colors.border};
    }
`;
const ValueBox = styled.div`
    background-color: ${({
  theme
}) => theme.layout.containerBg};
    border: ${({
  theme
}) => theme.layout.containerBorder};
    border-bottom: ${({
  theme
}) => theme.layout.containerBorderBottom};
    border-radius: ${({
  theme
}) => theme.layout.containerRadius};
    padding: ${({
  theme
}) => theme.layout.containerPaddingCompact};
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;
const PostsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: ${({
  theme
}) => theme.layout.cardGap};
`;
const PostItem = styled.a`
    display: block;
    text-decoration: none;
    color: inherit;
    border: ${({
  theme
}) => theme.layout.cardBorder};
    border-bottom: ${({
  theme
}) => theme.layout.cardBorderBottom};
    background-color: ${({
  theme
}) => theme.layout.cardBg};
    border-radius: ${({
  theme
}) => theme.layout.cardRadius};
    padding: ${({
  theme
}) => theme.layout.cardPadding};
    cursor: pointer;
    transition: background-color 0.2s ease, border-color 0.2s ease;

    &:hover {
        background-color: ${({
  theme
}) => theme.colors.panelAlt};
        border-color: ${({
  theme
}) => theme.colors.subtleText};
    }
`;
const BlockItemRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
`;
const BlockItemContent = styled.div`
    min-width: 0;
    flex: 1;
`;
const BlockItemActions = styled.div`
    flex-shrink: 0;
    display: flex;
    align-items: center;
`;
const PostMeta = styled.div`
    font-size: 0.55rem;
    color: ${({
  theme
}) => theme.colors.subtleText};
    margin-bottom: 0.25rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
`;
const PostPreview = styled.div`
    font-size: 0.65rem;
    color: ${({
  theme
}) => theme.colors.text};
    line-height: 1.3;
    word-break: break-word;
    white-space: pre-line;
`;
const Mono = styled.span`
    color: ${({
  theme
}) => theme.colors.text};
    font-size: 0.8rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
`;
export default function FollowsView({
  state
}) {
  const {
    navigate,
    followedUsers,
    followedTopics,
    followedUsernames,
    listsLoading,
    listsError,
    isFollowTopicPending,
    isFollowUserPending,
    formatFollowTopicStatus,
    formatFollowUserStatus,
    handleUnfollowTopic,
    handleUnfollowUser
  } = useFollows({
    state
  });
  return <ContentGrid>
            <Helmet>
                <title>Follows | Mirage</title>
            </Helmet>
            <div>
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow>
                            <ClickableTab $active>Follows</ClickableTab>
                        </TabsRow>
                        <ContainerBody>
                            <SectionTitle $first>Topics</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{
                color: '#888'
              }}>Loading...</Mono>}
                                {!listsLoading && !listsError && followedTopics.length === 0 && <Mono style={{
                color: '#888'
              }}>Not following any topics.</Mono>}
                                {!listsLoading && !listsError && followedTopics.length > 0 && <PostsList>
                                        {followedTopics.map(topic => {
                  const isPending = isFollowTopicPending(topic);
                  const status = formatFollowTopicStatus(topic);
                  return <PostItem key={topic} href={`/t/${encodeURIComponent(topic)}`} onClick={e => {
                    if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                      e.preventDefault();
                      navigate(`/t/${encodeURIComponent(topic)}`);
                    }
                  }}>
                                                    <BlockItemRow>
                                                        <BlockItemContent>
                                                            <PostPreview>#{topic}</PostPreview>
                                                        </BlockItemContent>
                                                        <BlockItemActions>
                                                            <Button variant="ghost" size="sm" minWidth="5.5rem" disabled={isPending} loading={isPending} onClick={e => handleUnfollowTopic(e, topic)}>
                                                                {status || 'Unfollow'}
                                                            </Button>
                                                        </BlockItemActions>
                                                    </BlockItemRow>
                                                </PostItem>;
                })}
                                    </PostsList>}
                            </ValueBox>

                            <SectionTitle>Users</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{
                color: '#888'
              }}>Loading...</Mono>}
                                {!listsLoading && listsError && <Mono style={{
                color: '#f87171'
              }}>{listsError}</Mono>}
                                {!listsLoading && !listsError && followedUsers.length === 0 && <Mono style={{
                color: '#888'
              }}>Not following any users.</Mono>}
                                {!listsLoading && !listsError && followedUsers.length > 0 && <PostsList>
                                        {followedUsers.map(userAddr => {
                  const isPending = isFollowUserPending(userAddr);
                  const status = formatFollowUserStatus(userAddr);
                  return <PostItem key={userAddr} href={`/u/${encodeURIComponent(followedUsernames[userAddr] || userAddr)}?tab=posts`} onClick={e => {
                    if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                      e.preventDefault();
                      navigate(`/u/${encodeURIComponent(followedUsernames[userAddr] || userAddr)}?tab=posts`);
                    }
                  }}>
                                                    <BlockItemRow>
                                                        <BlockItemContent>
                                                            <PostPreview>
                                                                {followedUsernames[userAddr] && followedUsernames[userAddr] !== userAddr ? followedUsernames[userAddr] : shortenAddress(userAddr)}
                                                            </PostPreview>
                                                            <PostMeta>{userAddr}</PostMeta>
                                                        </BlockItemContent>
                                                        <BlockItemActions>
                                                            <Button variant="ghost" size="sm" minWidth="5.5rem" disabled={isPending} loading={isPending} onClick={e => handleUnfollowUser(e, userAddr)}>
                                                                {status || 'Unfollow'}
                                                            </Button>
                                                        </BlockItemActions>
                                                    </BlockItemRow>
                                                </PostItem>;
                })}
                                    </PostsList>}
                            </ValueBox>
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>;
}