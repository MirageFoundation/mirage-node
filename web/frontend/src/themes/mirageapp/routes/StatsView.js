import React from "react";
import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { Link } from "react-router-dom";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, OldRedditContentBleed, OldRedditTabsStrip, OldRedditTabsRow, OldRedditTab } from "../Layout";
import { InfoIcon as TooltipInfoIcon } from "../components/Tooltip.js";
import { useStats, TIER_NAMES, TIER_COLORS, InfoIcon } from "../../../logic/useStats";
const Row = styled.div`
    display: grid;
    grid-template-columns: 10rem minmax(0, 1fr);
    gap: ${({
  theme
}) => theme.layout.formRowGap};
    margin: ${({
  theme
}) => theme.layout.formRowMargin};
    align-items: ${({
  theme
}) => theme.layout.formRowAlign};
    @media (max-width: 1000px) {
        grid-template-columns: 1fr;
        gap: 0.35rem;
    }
`;
const Label = styled.div`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-weight: ${({
  theme
}) => theme.layout.labelWeight};
    font-size: ${({
  theme
}) => theme.layout.labelSize};
    padding-top: ${({
  theme
}) => theme.layout.labelPaddingTop};
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
    text-align: left;
`;
const StatsTabbedContainer = styled(TabbedContainer)`
    margin-top: 0;
`;
const SectionTitle = styled.div`
    color: ${({
  theme
}) => theme.colors.link};
    font-weight: bold;
    font-size: ${({
  theme
}) => theme.layout.sectionSize};
    margin-top: ${({
  theme
}) => theme.layout.sectionMarginTop};
    margin-bottom: ${({
  theme
}) => theme.layout.sectionMarginBottom};
    padding-bottom: 0.25rem;
    border-bottom: 1px solid ${({
  theme
}) => theme.colors.border};
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;
const SectionInfoIcon = styled(TooltipInfoIcon)`
    align-self: flex-start;
    transform: translateX(-0.5rem);
`;
const Mono = styled.span`
    color: ${({
  theme
}) => theme.colors.text};
    font-size: ${({
  theme
}) => theme.layout.monoSize};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
`;
const LoadingSpinner = styled.div`
    width: 12px;
    height: 12px;
    border: 2px solid transparent;
    border-top: 2px solid currentColor;
    border-radius: 50%;
    animation: spin 1s linear infinite;
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;
const ErrorMessage = styled.div`
    background-color: rgba(220, 38, 38, 0.1);
    border: 1px solid #dc2626;
    border-radius: 8px;
    padding: 0.6rem 0.85rem;
    margin-top: 0.5rem;
    color: #dc2626;
    font-size: 0.8rem;
`;
const StatList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
`;
const StatItem = styled.div`
    display: flex;
    justify-content: space-between;
    padding: 0.2rem 0;
    font-size: 0.8rem;
`;
const TrendIndicator = styled.span`
    margin-left: 0.5rem;
    color: ${({
  trend
}) => trend === 'up' ? '#22c55e' : trend === 'down' ? '#dc2626' : '#888'};
`;
const SectionNote = styled.div`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-size: 0.75rem;
    font-style: italic;
    margin-bottom: 0.5rem;
`;

// Table styles for signups/accounts tabs
const Table = styled.table`
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8rem;
`;
const Th = styled.th`
    text-align: left;
    padding: 0.5rem 0.75rem;
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-weight: 600;
    border-bottom: 1px solid ${({
  theme
}) => theme.colors.border};
    white-space: nowrap;
`;
const Td = styled.td`
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid ${({
  theme
}) => theme.colors.border}22;
    vertical-align: middle;
`;
const UserCell = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;
const Avatar = styled.img`
    width: 24px;
    height: 24px;
    border-radius: 50%;
    object-fit: cover;
`;
const AvatarPlaceholder = styled.div`
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: ${({
  theme
}) => theme.colors.border};
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.6rem;
    color: ${({
  theme
}) => theme.colors.subtleText};
`;
const UserLink = styled(Link)`
    color: ${({
  theme
}) => theme.colors.link};
    text-decoration: none;
    font-weight: 500;
    &:hover {
        text-decoration: underline;
    }
`;
const AddressText = styled.span`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.7rem;
`;
const Badge = styled.span`
    display: inline-block;
    padding: 0.1rem 0.4rem;
    border-radius: 4px;
    font-size: 0.65rem;
    font-weight: 600;
    background: ${({
  $variant,
  theme
}) => {
  if ($variant === 'subscriber') return '#F59E0B20';
  if ($variant === 'agent') return '#EF444420';
  return theme.colors.panelAlt;
}};
    color: ${({
  $variant
}) => {
  if ($variant === 'subscriber') return '#F59E0B';
  if ($variant === 'agent') return '#EF4444';
  return '#888';
}};
    margin-left: 0.25rem;
`;
const SummaryBox = styled.div`
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 0.75rem;
    margin-bottom: 1rem;
`;
const SummaryItem = styled.div`
    background: ${({
  theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
  theme
}) => theme.colors.border};
    border-radius: 8px;
    padding: 0.75rem;
    text-align: center;
`;
const SummaryValue = styled.div`
    font-size: 1.5rem;
    font-weight: bold;
    color: ${({
  theme,
  $color
}) => $color};
`;
const SummaryLabel = styled.div`
    font-size: 0.7rem;
    color: ${({
  theme
}) => theme.colors.subtleText};
    margin-top: 0.25rem;
`;
const TierSection = styled.div`
    margin-bottom: 1.5rem;
`;
const TierHeader = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
    padding-bottom: 0.25rem;
    border-bottom: 2px solid ${({
  $color
}) => $color || '#333'};
`;
const TierBadge = styled.span`
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    background: ${({
  $color
}) => $color}20;
    color: ${({
  $color
}) => $color};
`;
const TierCount = styled.span`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-size: 0.8rem;
`;
export default function StatsView() {
  const {
    activeTab,
    setActiveTab,
    signupsData,
    subscribersData,
    accountsData,
    rewardsData,
    expandedUsers,
    setExpandedUsers,
    payouts,
    payoutsHasMore,
    payoutsLoading,
    loading,
    error,
    mergedStats,
    fetchRewardHistory,
    formatNumber,
    formatPercentage,
    formatDateShort,
    formatMirage,
    getDAUTrend,
    truncateAddress
  } = useStats();
  const renderUserCell = (user, showAddress = true) => {
    if (!user) return <Td>-</Td>;
    const address = user.address;
    return <Td>
                <UserCell>
                    {user.avatar ? <Avatar src={user.avatar} alt="" /> : <AvatarPlaceholder>?</AvatarPlaceholder>}
                    <div>
                        {address ? <UserLink to={`/u/${user.username || address}`}>
                                {user.username || truncateAddress(address)}
                            </UserLink> : <span>{user.username || 'Anonymous'}</span>}
                        {showAddress && address && user.username && <div>
                                <AddressText>{truncateAddress(address)}</AddressText>
                            </div>}
                        {user.is_subscriber && <Badge $variant="subscriber">SUB</Badge>}
                        {user.flair && <Badge $variant="agent">{user.flair}</Badge>}
                    </div>
                </UserCell>
            </Td>;
  };
  const renderSubscriberCell = user => {
    if (!user) return <Td>-</Td>;
    return <Td>
                <UserCell>
                    {user.avatar ? <Avatar src={user.avatar} alt="" /> : <AvatarPlaceholder>?</AvatarPlaceholder>}
                    <div>
                        {user.address ? <UserLink to={`/u/${user.username || user.address}`}>
                                {user.username || 'Anonymous'}
                            </UserLink> : <span style={{
            fontWeight: 500
          }}>{user.username || 'Anonymous'}</span>}
                        {user.flair && <Badge $variant="agent">{user.flair}</Badge>}
                    </div>
                </UserCell>
            </Td>;
  };

  // Loading/Error state for any tab
  if (loading || error) {
    return <ContentGrid>
                <Helmet>
                    <title>Stats | Mirage</title>
                </Helmet>
                <div>
                    <ModernPostFeed>
                        <OldRedditContentBleed>
                            <OldRedditTabsStrip>
                                <OldRedditTabsRow role="tablist" aria-label="Stats sections">
                                    <OldRedditTab type="button" role="tab" aria-selected={activeTab === 'overview'} $active={activeTab === 'overview'} onClick={() => setActiveTab('overview')}>
                                        Overview
                                    </OldRedditTab>
                                    <OldRedditTab type="button" role="tab" aria-selected={activeTab === 'signups'} $active={activeTab === 'signups'} onClick={() => setActiveTab('signups')}>
                                        Signups
                                    </OldRedditTab>
                                    <OldRedditTab type="button" role="tab" aria-selected={activeTab === 'subscribers'} $active={activeTab === 'subscribers'} onClick={() => setActiveTab('subscribers')}>
                                        Subscribers
                                    </OldRedditTab>
                                    <OldRedditTab type="button" role="tab" aria-selected={activeTab === 'accounts'} $active={activeTab === 'accounts'} onClick={() => setActiveTab('accounts')}>
                                        Accounts
                                    </OldRedditTab>
                                    <OldRedditTab type="button" role="tab" aria-selected={activeTab === 'rewards'} $active={activeTab === 'rewards'} onClick={() => setActiveTab('rewards')}>
                                        Rewards
                                    </OldRedditTab>
                                </OldRedditTabsRow>
                            </OldRedditTabsStrip>
                        </OldRedditContentBleed>
                        <StatsTabbedContainer>
                            <ContainerBody>
                                {loading && !error && <ValueBox style={{
                textAlign: 'center',
                padding: '2rem'
              }}>
                                        <LoadingSpinner style={{
                  margin: '0 auto'
                }} />
                                    </ValueBox>}
                                {!loading && error && <ErrorMessage>{error}</ErrorMessage>}
                            </ContainerBody>
                        </StatsTabbedContainer>
                    </ModernPostFeed>
                </div>
            </ContentGrid>;
  }
  const dauTrend = getDAUTrend();
  const trendSymbol = dauTrend === 'up' ? '↑' : dauTrend === 'down' ? '↓' : '→';
  const renderSubscriberTable = (subscribers, tierColor) => {
    if (!subscribers || subscribers.length === 0) {
      return <SectionNote>No subscribers in this tier.</SectionNote>;
    }
    return <ValueBox style={{
      padding: 0,
      overflow: 'auto'
    }}>
                <Table style={{
        tableLayout: 'fixed',
        width: '100%'
      }}>
                    <thead>
                        <tr>
                            <Th style={{
              width: '30%'
            }}>User</Th>
                            <Th style={{
              textAlign: 'center',
              width: '12%'
            }}>Posts</Th>
                            <Th style={{
              textAlign: 'center',
              width: '14%'
            }}>Comments</Th>
                            <Th style={{
              textAlign: 'center',
              width: '12%'
            }}>Votes</Th>
                            <Th style={{
              textAlign: 'center',
              width: '14%'
            }}>Followers</Th>
                            <Th style={{
              textAlign: 'center',
              width: '18%'
            }}>Joined</Th>
                        </tr>
                    </thead>
                    <tbody>
                        {subscribers.map((sub, idx) => <tr key={idx}>
                                {renderSubscriberCell(sub)}
                                <Td style={{
              textAlign: 'center'
            }}>
                                    <Mono>{formatNumber(sub.post_count)}</Mono>
                                </Td>
                                <Td style={{
              textAlign: 'center'
            }}>
                                    <Mono>{formatNumber(sub.comment_count)}</Mono>
                                </Td>
                                <Td style={{
              textAlign: 'center'
            }}>
                                    <Mono>{formatNumber(sub.vote_count)}</Mono>
                                </Td>
                                <Td style={{
              textAlign: 'center'
            }}>
                                    <Mono>{formatNumber(sub.follower_count)}</Mono>
                                </Td>
                                <Td style={{
              textAlign: 'center'
            }}>
                                    <Mono style={{
                fontSize: '0.7rem'
              }}>{formatDateShort(sub.created_at)}</Mono>
                                </Td>
                            </tr>)}
                    </tbody>
                </Table>
            </ValueBox>;
  };
  return <ContentGrid>
            <Helmet>
                <title>Stats | Mirage</title>
            </Helmet>
            <div>
                <ModernPostFeed>
                    <OldRedditContentBleed>
                        <OldRedditTabsStrip>
                            <OldRedditTabsRow role="tablist" aria-label="Stats sections">
                                <OldRedditTab type="button" role="tab" aria-selected={activeTab === 'overview'} $active={activeTab === 'overview'} onClick={() => setActiveTab('overview')}>
                                    Overview
                                </OldRedditTab>
                                <OldRedditTab type="button" role="tab" aria-selected={activeTab === 'signups'} $active={activeTab === 'signups'} onClick={() => setActiveTab('signups')}>
                                    Signups
                                </OldRedditTab>
                                <OldRedditTab type="button" role="tab" aria-selected={activeTab === 'subscribers'} $active={activeTab === 'subscribers'} onClick={() => setActiveTab('subscribers')}>
                                    Subscribers
                                </OldRedditTab>
                                <OldRedditTab type="button" role="tab" aria-selected={activeTab === 'accounts'} $active={activeTab === 'accounts'} onClick={() => setActiveTab('accounts')}>
                                    Accounts
                                </OldRedditTab>
                                <OldRedditTab type="button" role="tab" aria-selected={activeTab === 'rewards'} $active={activeTab === 'rewards'} onClick={() => setActiveTab('rewards')}>
                                    Rewards
                                </OldRedditTab>
                            </OldRedditTabsRow>
                        </OldRedditTabsStrip>
                    </OldRedditContentBleed>
                    <StatsTabbedContainer>
                        <ContainerBody>
                            {/* Overview Tab */}
                            {activeTab === 'overview' && mergedStats && <>
                                    <SectionTitle>
                                        Usage
                                        <SectionInfoIcon data-tooltip="Activity counts pulled from on-chain data and lightweight session tracking.">
                                            ?
                                        </SectionInfoIcon>
                                    </SectionTitle>
                                    <SectionNote>All known bots and crawlers are excluded — these are real users only.</SectionNote>
                                    <Row>
                                        <Label>
                                            DAUs (Any)
                                            <InfoIcon data-tooltip="Daily Active Users: unique users or sessions seen today">
                                                ?
                                            </InfoIcon>
                                        </Label>
                                        <ValueBox>
                                            <Mono>
                                                {formatNumber(mergedStats.dau_any_today || mergedStats.dau_today || 0)}
                                                {dauTrend && <TrendIndicator trend={dauTrend}>{trendSymbol}</TrendIndicator>}
                                            </Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            MAUs (Any)
                                            <InfoIcon data-tooltip="Unique users or sessions in the last 30 days">
                                                ?
                                            </InfoIcon>
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(mergedStats.maus || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Total Registered
                                            <InfoIcon data-tooltip="Profiles created on-chain">
                                                ?
                                            </InfoIcon>
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(mergedStats.registered_users || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            New Registrations
                                            <InfoIcon data-tooltip="New profile registrations in the last 7 days">
                                                ?
                                            </InfoIcon>
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(mergedStats.new_registrations_7d || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Subscribers
                                            <InfoIcon data-tooltip="Profiles with active subscription (all tiers)">
                                                ?
                                            </InfoIcon>
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(mergedStats.subscribers || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row style={{
                paddingLeft: '1rem'
              }}>
                                        <Label style={{
                  fontSize: '0.9em',
                  color: TIER_COLORS[1]
                }}>
                                            {TIER_NAMES[1]}
                                        </Label>
                                        <ValueBox>
                                            <Mono style={{
                    fontSize: '0.9em'
                  }}>{formatNumber(mergedStats.subscribers_tier_1 || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row style={{
                paddingLeft: '1rem'
              }}>
                                        <Label style={{
                  fontSize: '0.9em',
                  color: TIER_COLORS[10]
                }}>
                                            {TIER_NAMES[10]}
                                        </Label>
                                        <ValueBox>
                                            <Mono style={{
                    fontSize: '0.9em'
                  }}>{formatNumber(mergedStats.subscribers_tier_10 || 0)}</Mono>
                                        </ValueBox>
                                    </Row>

                                    <SectionTitle>
                                        Content
                                        <SectionInfoIcon data-tooltip="Blockchain-wide content counts.">
                                            ?
                                        </SectionInfoIcon>
                                    </SectionTitle>
                                    <Row>
                                        <Label>
                                            Posts
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(mergedStats.total_posts || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Comments
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(mergedStats.total_comments || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Votes
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(mergedStats.total_votes || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <SectionTitle>
                                        Engagement
                                        <SectionInfoIcon data-tooltip="Activity metrics for registered users only.">
                                            ?
                                        </SectionInfoIcon>
                                    </SectionTitle>
                                    <Row>
                                        <Label>
                                            Votes
                                        </Label>
                                        <ValueBox>
                                            <Mono>
                                                ↑{formatNumber(mergedStats.upvotes || 0)} / ↓{formatNumber(mergedStats.downvotes || 0)}
                                            </Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Avg Posts/User
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(mergedStats.average_posts_per_user || 0, 1)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Avg Comments/Post
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(mergedStats.average_comments_per_post || 0, 1)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Avg Votes/User
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(mergedStats.average_votes_per_user || 0, 1)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Edit %
                                            <InfoIcon data-tooltip="Percentage of posts that have been edited">
                                                ?
                                            </InfoIcon>
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatPercentage((mergedStats.edit_frequency || 0) * 100, 1)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Delete %
                                            <InfoIcon data-tooltip="Percentage of posts that have been deleted">
                                                ?
                                            </InfoIcon>
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatPercentage((mergedStats.delete_rate || 0) * 100, 1)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    {mergedStats.most_active_topics && mergedStats.most_active_topics.length > 0 && <>
                                            <SectionTitle>
                                                Active Topics
                                                <SectionInfoIcon data-tooltip="Top topics by post volume (chain-wide).">
                                                    ?
                                                </SectionInfoIcon>
                                            </SectionTitle>
                                            <Row>
                                                <Label>
                                                    Top Topics
                                                </Label>
                                                <ValueBox>
                                                    <StatList>
                                                        {mergedStats.most_active_topics.map((item, idx) => <StatItem key={idx}>
                                                                <Link to={`/t/${encodeURIComponent(item.topic)}`} style={{
                          color: 'inherit',
                          textDecoration: 'none'
                        }}><Mono>#{item.topic}</Mono></Link>
                                                                <Mono>{formatNumber(item.count)}</Mono>
                                                            </StatItem>)}
                                                    </StatList>
                                                </ValueBox>
                                            </Row>
                                        </>}
                                    {mergedStats.tag_counts && <>
                                            <SectionTitle>
                                                Content Tags
                                                <SectionInfoIcon data-tooltip="Posts by content tag (chain-wide).">
                                                    ?
                                                </SectionInfoIcon>
                                            </SectionTitle>
                                            <Row>
                                                <Label>
                                                    By Tag
                                                </Label>
                                                <ValueBox>
                                                    <StatList>
                                                        <StatItem>
                                                            <Mono>Safe</Mono>
                                                            <Mono>{formatNumber(mergedStats.tag_counts.safe || 0)}</Mono>
                                                        </StatItem>
                                                        <StatItem>
                                                            <Mono>Sensitive</Mono>
                                                            <Mono>{formatNumber(mergedStats.tag_counts.sensitive || 0)}</Mono>
                                                        </StatItem>
                                                        <StatItem>
                                                            <Mono>Adult</Mono>
                                                            <Mono>{formatNumber(mergedStats.tag_counts.adult || 0)}</Mono>
                                                        </StatItem>
                                                        <StatItem>
                                                            <Mono>Violence</Mono>
                                                            <Mono>{formatNumber(mergedStats.tag_counts.violence || 0)}</Mono>
                                                        </StatItem>
                                                        <StatItem>
                                                            <Mono>Gore</Mono>
                                                            <Mono>{formatNumber(mergedStats.tag_counts.gore || 0)}</Mono>
                                                        </StatItem>
                                                        <StatItem>
                                                            <Mono>Death</Mono>
                                                            <Mono>{formatNumber(mergedStats.tag_counts.death || 0)}</Mono>
                                                        </StatItem>
                                                    </StatList>
                                                </ValueBox>
                                            </Row>
                                        </>}
                                </>}

                            {/* Signups Tab */}
                            {activeTab === 'signups' && signupsData && <>
                                    <SectionTitle>
                                        Invite Code Summary
                                        <SectionInfoIcon data-tooltip="Overview of invite code usage.">
                                            ?
                                        </SectionInfoIcon>
                                    </SectionTitle>
                                    <SummaryBox>
                                        <SummaryItem>
                                            <SummaryValue>{formatNumber(signupsData.total_used || 0)}</SummaryValue>
                                            <SummaryLabel>Codes Used</SummaryLabel>
                                        </SummaryItem>
                                        <SummaryItem>
                                            <SummaryValue>{formatNumber(signupsData.total_available || 0)}</SummaryValue>
                                            <SummaryLabel>Available</SummaryLabel>
                                        </SummaryItem>
                                        <SummaryItem>
                                            <SummaryValue>{formatNumber(signupsData.unique_referrers || 0)}</SummaryValue>
                                            <SummaryLabel>Unique Referrers</SummaryLabel>
                                        </SummaryItem>
                                    </SummaryBox>

                                    {signupsData.top_referrers && signupsData.top_referrers.length > 0 && <>
                                            <SectionTitle>
                                                Top Referrers
                                                <SectionInfoIcon data-tooltip="Users who have invited the most new members.">
                                                    ?
                                                </SectionInfoIcon>
                                            </SectionTitle>
                                            <ValueBox style={{
                  padding: 0,
                  overflow: 'auto'
                }}>
                                                <Table>
                                                    <thead>
                                                        <tr>
                                                            <Th>#</Th>
                                                            <Th>Referrer</Th>
                                                            <Th style={{
                          textAlign: 'right'
                        }}>Invites</Th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        {signupsData.top_referrers.map((ref, idx) => <tr key={idx}>
                                                                <Td style={{
                          width: '40px',
                          color: '#888'
                        }}>{idx + 1}</Td>
                                                                {renderUserCell(ref)}
                                                                <Td style={{
                          textAlign: 'right',
                          fontWeight: 'bold'
                        }}>
                                                                    {formatNumber(ref.invite_count)}
                                                                </Td>
                                                            </tr>)}
                                                    </tbody>
                                                </Table>
                                            </ValueBox>
                                        </>}

                                    <SectionTitle>
                                        Recent Signups
                                        <SectionInfoIcon data-tooltip="Most recent users who signed up via invite codes.">
                                            ?
                                        </SectionInfoIcon>
                                    </SectionTitle>
                                    <SectionNote>Showing up to 100 most recent signups via invite codes.</SectionNote>
                                    <ValueBox style={{
                padding: 0,
                overflow: 'auto'
              }}>
                                        <Table>
                                            <thead>
                                                <tr>
                                                    <Th>New User</Th>
                                                    <Th>Invited By</Th>
                                                    <Th>Code</Th>
                                                    <Th>Date</Th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {signupsData.signups && signupsData.signups.length > 0 ? signupsData.signups.map((signup, idx) => <tr key={idx}>
                                                            {renderUserCell(signup.signup)}
                                                            {renderUserCell(signup.referrer)}
                                                            <Td>
                                                                <Mono style={{
                          fontSize: '0.7rem'
                        }}>{signup.code}</Mono>
                                                            </Td>
                                                            <Td>
                                                                <Mono style={{
                          fontSize: '0.7rem'
                        }}>{formatDateShort(signup.used_at)}</Mono>
                                                            </Td>
                                                        </tr>) : <tr>
                                                        <Td colSpan={4} style={{
                        textAlign: 'center',
                        color: '#888'
                      }}>
                                                            No signups via invite codes yet.
                                                        </Td>
                                                    </tr>}
                                            </tbody>
                                        </Table>
                                    </ValueBox>
                                </>}

                            {/* Subscribers Tab */}
                            {activeTab === 'subscribers' && subscribersData && <>
                                    <SectionTitle>
                                        Subscriber Summary
                                        <SectionInfoIcon data-tooltip="Active subscribers by tier.">
                                            ?
                                        </SectionInfoIcon>
                                    </SectionTitle>
                                    <SummaryBox>
                                        <SummaryItem>
                                            <SummaryValue>{formatNumber(subscribersData.total_subscribers || 0)}</SummaryValue>
                                            <SummaryLabel>Total Subscribers</SummaryLabel>
                                        </SummaryItem>
                                        <SummaryItem>
                                            <SummaryValue $color={TIER_COLORS[10]}>{formatNumber(subscribersData.count_tier_10 || 0)}</SummaryValue>
                                            <SummaryLabel>{TIER_NAMES[10]}</SummaryLabel>
                                        </SummaryItem>
                                        <SummaryItem>
                                            <SummaryValue $color={TIER_COLORS[1]}>{formatNumber(subscribersData.count_tier_1 || 0)}</SummaryValue>
                                            <SummaryLabel>{TIER_NAMES[1]}</SummaryLabel>
                                        </SummaryItem>
                                    </SummaryBox>

                                    {/* Tier 10 - Agent */}
                                    <TierSection>
                                        <TierHeader $color={TIER_COLORS[10]}>
                                            <TierBadge $color={TIER_COLORS[10]}>{TIER_NAMES[10]}</TierBadge>
                                            <TierCount>({formatNumber(subscribersData.count_tier_10 || 0)})</TierCount>
                                        </TierHeader>
                                        {renderSubscriberTable(subscribersData.tier_10, TIER_COLORS[10])}
                                    </TierSection>

                                    {/* Tier 1 - Subscriber */}
                                    <TierSection>
                                        <TierHeader $color={TIER_COLORS[1]}>
                                            <TierBadge $color={TIER_COLORS[1]}>{TIER_NAMES[1]}</TierBadge>
                                            <TierCount>({formatNumber(subscribersData.count_tier_1 || 0)})</TierCount>
                                        </TierHeader>
                                        {renderSubscriberTable(subscribersData.tier_1, TIER_COLORS[1])}
                                    </TierSection>
                                </>}

                            {/* Accounts Tab */}
                            {activeTab === 'accounts' && accountsData && <>
                                    <SectionTitle>
                                        Top Accounts by Balance
                                        <SectionInfoIcon data-tooltip="Accounts ranked by wallet balance.">
                                            ?
                                        </SectionInfoIcon>
                                    </SectionTitle>
                                    <SummaryBox>
                                        <SummaryItem>
                                            <SummaryValue>{formatNumber(accountsData.total_accounts || 0)}</SummaryValue>
                                            <SummaryLabel>Total Accounts</SummaryLabel>
                                        </SummaryItem>
                                    </SummaryBox>

                                    <SectionNote>Top 100 accounts by MIRAGE balance.</SectionNote>
                                    <ValueBox style={{
                padding: 0,
                overflow: 'auto'
              }}>
                                        <Table>
                                            <thead>
                                                <tr>
                                                    <Th>#</Th>
                                                    <Th>Address</Th>
                                                    <Th>Name</Th>
                                                    <Th style={{
                        textAlign: 'right'
                      }}>Balance (MIRAGE)</Th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {accountsData.accounts && accountsData.accounts.length > 0 ? accountsData.accounts.map((account, idx) => <tr key={idx}>
                                                            <Td style={{
                        width: '40px',
                        color: '#888'
                      }}>{idx + 1}</Td>
                                                            <Td>
                                                                <UserLink to={`/u/${account.username || account.address}`}>
                                                                    <AddressText>{truncateAddress(account.address)}</AddressText>
                                                                </UserLink>
                                                            </Td>
                                                            <Td>
                                                                {account.username ? <UserLink to={`/u/${account.username}`}>
                                                                        {account.username}
                                                                    </UserLink> : <span style={{
                          color: '#666'
                        }}>-</span>}
                                                            </Td>
                                                            <Td style={{
                        textAlign: 'right'
                      }}>
                                                                <Mono style={{
                          fontWeight: 'bold'
                        }}>{formatMirage(account.balance)}</Mono>
                                                            </Td>
                                                        </tr>) : <tr>
                                                        <Td colSpan={4} style={{
                        textAlign: 'center',
                        color: '#888'
                      }}>
                                                            No accounts found.
                                                        </Td>
                                                    </tr>}
                                            </tbody>
                                        </Table>
                                    </ValueBox>
                                </>}

                            {/* Rewards Tab */}
                            {activeTab === 'rewards' && rewardsData && <>
                                    <SectionTitle>
                                        Reward Pool Status
                                    </SectionTitle>
                                    <SummaryBox>
                                        <SummaryItem>
                                            <SummaryValue $color={rewardsData.summary?.quest_payouts_enabled ? '#22c55e' : '#ef4444'}>
                                                {rewardsData.summary?.quest_payouts_enabled ? 'Active' : 'Disabled'}
                                            </SummaryValue>
                                            <SummaryLabel>Payouts</SummaryLabel>
                                        </SummaryItem>
                                        <SummaryItem>
                                            <SummaryValue>{formatMirage(rewardsData.summary?.pool_balance || 0)}</SummaryValue>
                                            <SummaryLabel>Pool (MIRAGE)</SummaryLabel>
                                        </SummaryItem>
                                        <SummaryItem>
                                            <SummaryValue>{formatMirage(rewardsData.summary?.daily_rate || 0)}</SummaryValue>
                                            <SummaryLabel>Earned/Day (7d avg)</SummaryLabel>
                                        </SummaryItem>
                                    </SummaryBox>

                                    <SectionTitle>
                                        Overall Statistics
                                    </SectionTitle>
                                    <SummaryBox>
                                        <SummaryItem>
                                            <SummaryValue>{formatMirage(rewardsData.summary?.total_amount || 0)}</SummaryValue>
                                            <SummaryLabel>MIRAGE Earned</SummaryLabel>
                                        </SummaryItem>
                                        <SummaryItem>
                                            <SummaryValue $color="#22c55e">{formatMirage(rewardsData.summary?.claimed_amount || 0)}</SummaryValue>
                                            <SummaryLabel>MIRAGE Claimed</SummaryLabel>
                                        </SummaryItem>
                                        <SummaryItem>
                                            <SummaryValue $color="#f59e0b">{formatMirage(rewardsData.summary?.pending_amount || 0)}</SummaryValue>
                                            <SummaryLabel>MIRAGE Pending</SummaryLabel>
                                        </SummaryItem>
                                        <SummaryItem>
                                            <SummaryValue>{rewardsData.summary?.total_rewards || 0}</SummaryValue>
                                            <SummaryLabel>Reward Count</SummaryLabel>
                                        </SummaryItem>
                                    </SummaryBox>

                                    <SectionTitle>
                                        Per-User Breakdown
                                    </SectionTitle>
                                    <SectionNote>Showing {rewardsData.users?.length || 0} users who have earned rewards. Click to expand.</SectionNote>
                                    <ValueBox style={{
                padding: 0,
                overflow: 'auto'
              }}>
                                        <Table>
                                            <thead>
                                                <tr>
                                                    <Th style={{
                        width: '30px'
                      }}></Th>
                                                    <Th>User</Th>
                                                    <Th style={{
                        textAlign: 'right'
                      }}>Earned</Th>
                                                    <Th style={{
                        textAlign: 'right'
                      }}>Per Day</Th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {rewardsData.users && rewardsData.users.length > 0 ? rewardsData.users.map((user, idx) => <React.Fragment key={idx}>
                                                            <tr onClick={() => setExpandedUsers(prev => ({
                        ...prev,
                        [user.address]: !prev[user.address]
                      }))} style={{
                        cursor: 'pointer',
                        background: expandedUsers[user.address] ? 'rgba(102, 126, 234, 0.1)' : 'transparent'
                      }}>
                                                                <Td style={{
                          width: '30px',
                          textAlign: 'center',
                          color: '#888'
                        }}>
                                                                    {expandedUsers[user.address] ? '▼' : '▶'}
                                                                </Td>
                                                                <Td>
                                                                    <UserCell>
                                                                        <AvatarPlaceholder>?</AvatarPlaceholder>
                                                                        <div>
                                                                            <UserLink to={`/u/${user.username || user.address}`} onClick={e => e.stopPropagation()}>
                                                                                {user.username || truncateAddress(user.address)}
                                                                            </UserLink>
                                                                            {user.username && <div>
                                                                                    <AddressText>{truncateAddress(user.address)}</AddressText>
                                                                                </div>}
                                                                        </div>
                                                                    </UserCell>
                                                                </Td>
                                                                <Td style={{
                          textAlign: 'right'
                        }}>
                                                                    <Mono style={{
                            fontWeight: 'bold'
                          }}>{formatMirage(user.total_earned)}</Mono>
                                                                </Td>
                                                                <Td style={{
                          textAlign: 'right'
                        }}>
                                                                    <Mono style={{
                            color: '#888'
                          }}>{formatMirage(user.earnings_per_day)}</Mono>
                                                                </Td>
                                                            </tr>
                                                            {expandedUsers[user.address] && <tr>
                                                                    <Td colSpan={4} style={{
                          background: 'rgba(102, 126, 234, 0.05)',
                          padding: '1rem'
                        }}>
                                                                        <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                            gap: '1rem'
                          }}>
                                                                            <div>
                                                                                <div style={{
                                fontSize: '0.7rem',
                                color: '#888',
                                marginBottom: '0.25rem'
                              }}>Claimed</div>
                                                                                <Mono style={{
                                color: '#22c55e',
                                fontWeight: 'bold'
                              }}>{formatMirage(user.claimed_amount)} MIRAGE</Mono>
                                                                            </div>
                                                                            <div>
                                                                                <div style={{
                                fontSize: '0.7rem',
                                color: '#888',
                                marginBottom: '0.25rem'
                              }}>Pending</div>
                                                                                <Mono style={{
                                color: '#f59e0b',
                                fontWeight: 'bold'
                              }}>{formatMirage(user.pending_amount)} MIRAGE</Mono>
                                                                            </div>
                                                                            <div>
                                                                                <div style={{
                                fontSize: '0.7rem',
                                color: '#888',
                                marginBottom: '0.25rem'
                              }}>Reward Count</div>
                                                                                <Mono>{user.reward_count} ({user.claimed_count} claimed, {user.pending_count} pending)</Mono>
                                                                            </div>
                                                                            <div>
                                                                                <div style={{
                                fontSize: '0.7rem',
                                color: '#888',
                                marginBottom: '0.25rem'
                              }}>First Reward</div>
                                                                                <Mono>{user.first_reward_at ? formatDateShort(user.first_reward_at) : 'N/A'}</Mono>
                                                                            </div>
                                                                            <div>
                                                                                <div style={{
                                fontSize: '0.7rem',
                                color: '#888',
                                marginBottom: '0.25rem'
                              }}>Last Reward</div>
                                                                                <Mono>{user.last_reward_at ? formatDateShort(user.last_reward_at) : 'N/A'}</Mono>
                                                                            </div>
                                                                            <div>
                                                                                <div style={{
                                fontSize: '0.7rem',
                                color: '#888',
                                marginBottom: '0.25rem'
                              }}>Account Created</div>
                                                                                <Mono>{user.account_created_at ? formatDateShort(user.account_created_at) : 'N/A'}</Mono>
                                                                            </div>
                                                                        </div>
                                                                    </Td>
                                                                </tr>}
                                                        </React.Fragment>) : <tr>
                                                        <Td colSpan={4} style={{
                        textAlign: 'center',
                        color: '#888'
                      }}>
                                                            No reward data found.
                                                        </Td>
                                                    </tr>}
                                            </tbody>
                                        </Table>
                                    </ValueBox>

                                    <SectionTitle style={{
                marginTop: '1.5rem'
              }}>
                                        Reward History
                                    </SectionTitle>

                                    {payouts.length > 0 ? <div style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '0.5rem'
              }}>
                                            {payouts.map((reward, idx) => <div key={idx} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.75rem',
                  padding: '0.5rem 0.75rem',
                  background: reward.claimed ? 'rgba(34, 197, 94, 0.05)' : 'rgba(245, 158, 11, 0.05)',
                  borderRadius: '6px',
                  borderLeft: `3px solid ${reward.claimed ? '#22c55e' : '#f59e0b'}`
                }}>
                                                    <div style={{
                    flex: '0 0 auto',
                    minWidth: '80px'
                  }}>
                                                        <Mono style={{
                      color: reward.claimed ? '#22c55e' : '#f59e0b',
                      fontWeight: 'bold',
                      fontSize: '0.85rem'
                    }}>
                                                            +{formatMirage(reward.amount)}
                                                        </Mono>
                                                    </div>
                                                    <div style={{
                    flex: 1,
                    minWidth: 0
                  }}>
                                                        <UserLink to={`/u/${reward.username || reward.address}`} style={{
                      fontWeight: 500
                    }}>
                                                            {reward.username || truncateAddress(reward.address)}
                                                        </UserLink>
                                                        <div style={{
                      fontSize: '0.7rem',
                      color: '#888',
                      marginTop: '0.15rem'
                    }}>
                                                            {reward.reason}
                                                        </div>
                                                    </div>
                                                    <div style={{
                    flex: '0 0 auto',
                    fontSize: '0.7rem',
                    color: '#666',
                    textAlign: 'right'
                  }}>
                                                        {formatDateShort(reward.created_at)}
                                                        {reward.claimed && <div style={{
                      color: '#22c55e',
                      fontSize: '0.6rem'
                    }}>claimed</div>}
                                                    </div>
                                                </div>)}

                                            {payoutsHasMore && <button onClick={() => fetchRewardHistory(payouts.length, true)} disabled={payoutsLoading} style={{
                  padding: '0.75rem',
                  background: 'transparent',
                  border: '1px dashed #444',
                  borderRadius: '6px',
                  color: '#888',
                  cursor: payoutsLoading ? 'wait' : 'pointer',
                  fontSize: '0.8rem'
                }}>
                                                    {payoutsLoading ? 'Loading...' : 'Load more'}
                                                </button>}
                                        </div> : payoutsLoading ? <ValueBox style={{
                textAlign: 'center',
                padding: '2rem'
              }}>
                                            <LoadingSpinner style={{
                  margin: '0 auto'
                }} />
                                        </ValueBox> : <SectionNote>No rewards recorded yet.</SectionNote>}
                                </>}
                        </ContainerBody>
                    </StatsTabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>;
}