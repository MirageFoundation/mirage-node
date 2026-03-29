import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Button from "../components/Button.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, TabsRow, ClickableTab } from "../Layout";
import { useBlocks, shortenAddress } from "../../../logic/useBlocks";
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
export default function BlocksView({
  state
}) {
  const {
    navigate,
    location,
    blockedUsers,
    blockedPosts,
    blockedTopics,
    blockedUsernames,
    listsLoading,
    listsError,
    isTopicPending,
    isUserPending,
    isPostPending,
    formatTopicStatus,
    formatUserStatus,
    formatPostStatus,
    handleUnblockTopic,
    handleUnblockUser,
    handleUnblockPost
  } = useBlocks({
    state
  });
  return <ContentGrid>
            <Helmet>
                <title>Blocks | Mirage</title>
            </Helmet>
            <div>
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow>
                            <ClickableTab $active>Blocks</ClickableTab>
                        </TabsRow>
                        <ContainerBody>
                            <SectionTitle $first>Blocked Topics</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{
                color: '#888'
              }}>Loading...</Mono>}
                                {!listsLoading && !listsError && blockedTopics.length === 0 && <Mono style={{
                color: '#888'
              }}>No blocked topics.</Mono>}
                                {!listsLoading && !listsError && blockedTopics.length > 0 && <PostsList>
                                        {blockedTopics.map(topic => {
                  const isPending = isTopicPending(topic);
                  const status = formatTopicStatus(topic);
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
                                                            <Button variant="ghost" size="sm" disabled={isPending} loading={isPending} onClick={e => handleUnblockTopic(e, topic)}>
                                                                {status || 'Unblock'}
                                                            </Button>
                                                        </BlockItemActions>
                                                    </BlockItemRow>
                                                </PostItem>;
                })}
                                    </PostsList>}
                            </ValueBox>

                            <SectionTitle>Blocked Users</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{
                color: '#888'
              }}>Loading...</Mono>}
                                {!listsLoading && !listsError && blockedUsers.length === 0 && <Mono style={{
                color: '#888'
              }}>No blocked users.</Mono>}
                                {!listsLoading && !listsError && blockedUsers.length > 0 && <PostsList>
                                        {blockedUsers.map(userAddr => {
                  const isPending = isUserPending(userAddr);
                  const status = formatUserStatus(userAddr);
                  return <PostItem key={userAddr} href={`/u/${encodeURIComponent(blockedUsernames[userAddr] || userAddr)}`} onClick={e => {
                    if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                      e.preventDefault();
                      navigate(`/u/${encodeURIComponent(blockedUsernames[userAddr] || userAddr)}`);
                    }
                  }}>
                                                    <BlockItemRow>
                                                        <BlockItemContent>
                                                            <PostPreview>
                                                                {blockedUsernames[userAddr] && blockedUsernames[userAddr] !== userAddr ? blockedUsernames[userAddr] : shortenAddress(userAddr)}
                                                            </PostPreview>
                                                            <PostMeta>{userAddr}</PostMeta>
                                                        </BlockItemContent>
                                                        <BlockItemActions>
                                                            <Button variant="ghost" size="sm" disabled={isPending} loading={isPending} onClick={e => handleUnblockUser(e, userAddr)}>
                                                                {status || 'Unblock'}
                                                            </Button>
                                                        </BlockItemActions>
                                                    </BlockItemRow>
                                                </PostItem>;
                })}
                                    </PostsList>}
                            </ValueBox>

                            <SectionTitle>Blocked Posts</SectionTitle>
                            <ValueBox>
                                {listsLoading && <Mono style={{
                color: '#888'
              }}>Loading...</Mono>}
                                {!listsLoading && !listsError && blockedPosts.length === 0 && <Mono style={{
                color: '#888'
              }}>No blocked posts.</Mono>}
                                {!listsLoading && !listsError && blockedPosts.length > 0 && <PostsList>
                                        {blockedPosts.map(postId => {
                  const isPending = isPostPending(postId);
                  const status = formatPostStatus(postId);
                  return <PostItem key={postId} href={`/p/${encodeURIComponent(postId)}`} onClick={e => {
                    if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                      e.preventDefault();
                      navigate(`/p/${encodeURIComponent(postId)}`);
                    }
                  }}>
                                                    <BlockItemRow>
                                                        <BlockItemContent>
                                                            <PostPreview>{shortenAddress(postId)}</PostPreview>
                                                            <PostMeta>{postId}</PostMeta>
                                                        </BlockItemContent>
                                                        <BlockItemActions>
                                                            <Button variant="ghost" size="sm" disabled={isPending} loading={isPending} onClick={e => handleUnblockPost(e, postId)}>
                                                                {status || 'Unblock'}
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