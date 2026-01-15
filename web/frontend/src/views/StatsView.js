import React, { useEffect, useState, useCallback } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import { useLocation, Link } from "react-router-dom";
import Api from '../lib/api';
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, TabsRow, ClickableTab } from "../styled/Layout";
import { InfoIcon as TooltipInfoIcon } from "../components/Tooltip";
import { useTabs } from "../utils/useTabs";

// Tier names and colors (same as SubscriptionView)
const TIER_NAMES = ['Free', 'Trusted', 'Established', 'Distinguished'];
const TIER_COLORS = ['#6B7280', '#3B82F6', '#8B5CF6', '#F59E0B'];

const Row = styled.div`
    display: grid;
    grid-template-columns: 10rem minmax(0, 1fr);
    gap: 0.5rem;
    align-items: start;
    margin: 0.4rem 0;
    @media (max-width: 1000px) {
        grid-template-columns: 1fr;
        gap: 0.35rem;
    }
`;

const Label = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#ccc'};
    font-weight: 600;
    font-size: 0.85rem;
    padding-top: 0.75rem;
`;

const ValueBox = styled.div`
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.6rem 0.85rem;
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
    text-align: left;
`;

const InfoIcon = TooltipInfoIcon;

const SectionTitle = styled.div`
    color: ${({ theme }) => theme?.colors?.link || '#FFFFFF'};
    font-weight: bold;
    font-size: 0.9rem;
    margin-top: 1rem;
    margin-bottom: 0.5rem;
    padding-bottom: 0.25rem;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

const SectionInfoIcon = styled(TooltipInfoIcon)`
    align-self: flex-start;
    transform: translateX(-0.5rem);
`;

const Mono = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-size: 0.8rem;
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
    color: ${({ trend }) => trend === 'up' ? '#22c55e' : trend === 'down' ? '#dc2626' : '#888'};
`;

const SectionNote = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
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
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-weight: 600;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    white-space: nowrap;
`;

const Td = styled.td`
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#333'}22;
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
    background: ${({ theme }) => theme?.colors?.border || '#333'};
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.6rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

const UserLink = styled(Link)`
    color: ${({ theme }) => theme?.colors?.link || '#60a5fa'};
    text-decoration: none;
    font-weight: 500;
    &:hover {
        text-decoration: underline;
    }
`;

const AddressText = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.7rem;
`;

const Badge = styled.span`
    display: inline-block;
    padding: 0.1rem 0.4rem;
    border-radius: 4px;
    font-size: 0.65rem;
    font-weight: 600;
    background: ${({ $variant, theme }) => {
        if ($variant === 'subscriber') return '#3B82F620';
        if ($variant === 'moderator') return '#F59E0B20';
        return theme?.colors?.panelAlt || '#1f2328';
    }};
    color: ${({ $variant }) => {
        if ($variant === 'subscriber') return '#3B82F6';
        if ($variant === 'moderator') return '#F59E0B';
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
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    border-radius: 8px;
    padding: 0.75rem;
    text-align: center;
`;

const SummaryValue = styled.div`
    font-size: 1.5rem;
    font-weight: bold;
    color: ${({ theme, $color }) => $color || theme?.colors?.text || '#fff'};
`;

const SummaryLabel = styled.div`
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
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
    border-bottom: 2px solid ${({ $color }) => $color || '#333'};
`;

const TierBadge = styled.span`
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    background: ${({ $color }) => $color}20;
    color: ${({ $color }) => $color};
`;

const TierCount = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.8rem;
`;

const VALID_TABS = ['overview', 'signups', 'subscribers', 'accounts'];

export default function StatsView() {
    const location = useLocation();
    const [activeTab, setActiveTab] = useTabs('overview', VALID_TABS);
    const [stats, setStats] = useState(null);
    const [signupsData, setSignupsData] = useState(null);
    const [subscribersData, setSubscribersData] = useState(null);
    const [accountsData, setAccountsData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Fetch data based on active tab
    const fetchData = useCallback(async (tab) => {
        setLoading(true);
        setError(null);
        try {
            const data = await Api.get('get_stats', { tab }, { timeoutMs: 30000 });
            if (tab === 'overview') {
                setStats(data);
            } else if (tab === 'signups') {
                setSignupsData(data);
            } else if (tab === 'subscribers') {
                setSubscribersData(data);
            } else if (tab === 'accounts') {
                setAccountsData(data);
            }
        } catch (err) {
            setError(err.message || 'Failed to load stats');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchData(activeTab);
    }, [activeTab, fetchData]);

    const formatNumber = (num, digits = 0) => {
        if (num === null || num === undefined) return '0';
        if (typeof num === 'string') return num;
        return num.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
    };

    const formatPercentage = (num, digits = 1) => {
        if (num === null || num === undefined) return '0%';
        const val = typeof num === 'number' ? num : parseFloat(num);
        return val.toFixed(digits) + '%';
    };

    const formatDateShort = (ts) => {
        if (!ts) return 'N/A';
        return new Date(ts * 1000).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
        });
    };

    const formatMirage = (umirage) => {
        if (!umirage && umirage !== 0) return '0';
        const mirage = umirage / 1_000_000;
        return mirage.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 0 });
    };

    const getDAUTrend = () => {
        if (!stats || !stats.dau_today || !stats.dau_yesterday) return null;
        if (stats.dau_today > stats.dau_yesterday) return 'up';
        if (stats.dau_today < stats.dau_yesterday) return 'down';
        return 'same';
    };

    const truncateAddress = (addr) => {
        if (!addr) return '';
        return `${addr.slice(0, 8)}...${addr.slice(-6)}`;
    };

    const renderUserCell = (user, showAddress = true) => {
        if (!user) return <Td>-</Td>;
        const address = user.address;
        return (
            <Td>
                <UserCell>
                    {user.avatar ? (
                        <Avatar src={user.avatar} alt="" />
                    ) : (
                        <AvatarPlaceholder>?</AvatarPlaceholder>
                    )}
                    <div>
                        {address ? (
                            <UserLink to={`/profile?address=${address}`}>
                                {user.username || truncateAddress(address)}
                            </UserLink>
                        ) : (
                            <span>{user.username || 'Anonymous'}</span>
                        )}
                        {showAddress && address && user.username && (
                            <div>
                                <AddressText>{truncateAddress(address)}</AddressText>
                            </div>
                        )}
                        {user.is_subscriber && <Badge $variant="subscriber">SUB</Badge>}
                        {user.is_moderator && <Badge $variant="moderator">MOD</Badge>}
                    </div>
                </UserCell>
            </Td>
        );
    };

    const renderSubscriberCell = (user) => {
        if (!user) return <Td>-</Td>;
        return (
            <Td>
                <UserCell>
                    {user.avatar ? (
                        <Avatar src={user.avatar} alt="" />
                    ) : (
                        <AvatarPlaceholder>?</AvatarPlaceholder>
                    )}
                    <div>
                        {user.address ? (
                            <UserLink to={`/profile?address=${user.address}`}>
                                {user.username || 'Anonymous'}
                            </UserLink>
                        ) : (
                            <span style={{ fontWeight: 500 }}>{user.username || 'Anonymous'}</span>
                        )}
                        {user.is_moderator && <Badge $variant="moderator">MOD</Badge>}
                    </div>
                </UserCell>
            </Td>
        );
    };

    // Loading/Error state for any tab
    if (loading || error) {
        return (
            <ContentGrid>
                <Helmet>
                    <title>Stats | Mirage</title>
                </Helmet>
                <Sidebar currentPath={location.pathname} state={{}} />
                <div>
                    <TopBar state={{}} />
                    <ModernPostFeed>
                        <MobileHeader />
                        <TabbedContainer>
                            <TabsRow>
                                <ClickableTab $active={activeTab === 'overview'} onClick={() => setActiveTab('overview')}>
                                    Overview
                                </ClickableTab>
                                <ClickableTab $active={activeTab === 'signups'} onClick={() => setActiveTab('signups')}>
                                    Signups
                                </ClickableTab>
                                <ClickableTab $active={activeTab === 'subscribers'} onClick={() => setActiveTab('subscribers')}>
                                    Subscribers
                                </ClickableTab>
                                <ClickableTab $active={activeTab === 'accounts'} onClick={() => setActiveTab('accounts')}>
                                    Accounts
                                </ClickableTab>
                            </TabsRow>
                            <ContainerBody>
                                {loading && !error && (
                                    <ValueBox style={{ textAlign: 'center', padding: '2rem' }}>
                                        <LoadingSpinner style={{ margin: '0 auto' }} />
                                    </ValueBox>
                                )}
                                {!loading && error && (
                                    <ErrorMessage>{error}</ErrorMessage>
                                )}
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </div>
            </ContentGrid>
        );
    }

    const dauTrend = getDAUTrend();
    const trendSymbol = dauTrend === 'up' ? '↑' : dauTrend === 'down' ? '↓' : '→';

    const renderSubscriberTable = (subscribers, tierColor) => {
        if (!subscribers || subscribers.length === 0) {
            return <SectionNote>No subscribers in this tier.</SectionNote>;
        }
        return (
            <ValueBox style={{ padding: 0, overflow: 'auto' }}>
                <Table style={{ tableLayout: 'fixed', width: '100%' }}>
                    <thead>
                        <tr>
                            <Th style={{ width: '30%' }}>User</Th>
                            <Th style={{ textAlign: 'center', width: '12%' }}>Posts</Th>
                            <Th style={{ textAlign: 'center', width: '14%' }}>Comments</Th>
                            <Th style={{ textAlign: 'center', width: '12%' }}>Votes</Th>
                            <Th style={{ textAlign: 'center', width: '14%' }}>Followers</Th>
                            <Th style={{ textAlign: 'center', width: '18%' }}>Joined</Th>
                        </tr>
                    </thead>
                    <tbody>
                        {subscribers.map((sub, idx) => (
                            <tr key={idx}>
                                {renderSubscriberCell(sub)}
                                <Td style={{ textAlign: 'center' }}>
                                    <Mono>{formatNumber(sub.post_count)}</Mono>
                                </Td>
                                <Td style={{ textAlign: 'center' }}>
                                    <Mono>{formatNumber(sub.comment_count)}</Mono>
                                </Td>
                                <Td style={{ textAlign: 'center' }}>
                                    <Mono>{formatNumber(sub.vote_count)}</Mono>
                                </Td>
                                <Td style={{ textAlign: 'center' }}>
                                    <Mono>{formatNumber(sub.follower_count)}</Mono>
                                </Td>
                                <Td style={{ textAlign: 'center' }}>
                                    <Mono style={{ fontSize: '0.7rem' }}>{formatDateShort(sub.created_at)}</Mono>
                                </Td>
                            </tr>
                        ))}
                    </tbody>
                </Table>
            </ValueBox>
        );
    };

    return (
        <ContentGrid>
            <Helmet>
                <title>Stats | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={{}} />
            <div>
                <TopBar state={{}} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow>
                            <ClickableTab $active={activeTab === 'overview'} onClick={() => setActiveTab('overview')}>
                                Overview
                            </ClickableTab>
                            <ClickableTab $active={activeTab === 'signups'} onClick={() => setActiveTab('signups')}>
                                Signups
                            </ClickableTab>
                            <ClickableTab $active={activeTab === 'subscribers'} onClick={() => setActiveTab('subscribers')}>
                                Subscribers
                            </ClickableTab>
                            <ClickableTab $active={activeTab === 'accounts'} onClick={() => setActiveTab('accounts')}>
                                Accounts
                            </ClickableTab>
                        </TabsRow>
                        <ContainerBody>
                            {/* Overview Tab */}
                            {activeTab === 'overview' && stats && (
                                <>
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
                                                {formatNumber(stats.dau_any_today || stats.dau_today || 0)}
                                                {dauTrend && <TrendIndicator trend={dauTrend}>{trendSymbol}</TrendIndicator>}
                                            </Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            DAUs (Registered)
                                            <InfoIcon data-tooltip="Daily Active Users: unique logged-in users today">
                                                ?
                                            </InfoIcon>
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(stats.dau_registered_today || 0)}</Mono>
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
                                            <Mono>{formatNumber(stats.maus || 0)}</Mono>
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
                                            <Mono>{formatNumber(stats.registered_users || 0)}</Mono>
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
                                            <Mono>{formatNumber(stats.new_registrations_7d || 0)}</Mono>
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
                                            <Mono>{formatNumber(stats.subscribers || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row style={{ paddingLeft: '1rem' }}>
                                        <Label style={{ fontSize: '0.9em', color: TIER_COLORS[1] }}>
                                            {TIER_NAMES[1]}
                                        </Label>
                                        <ValueBox>
                                            <Mono style={{ fontSize: '0.9em' }}>{formatNumber(stats.subscribers_tier_1 || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row style={{ paddingLeft: '1rem' }}>
                                        <Label style={{ fontSize: '0.9em', color: TIER_COLORS[2] }}>
                                            {TIER_NAMES[2]}
                                        </Label>
                                        <ValueBox>
                                            <Mono style={{ fontSize: '0.9em' }}>{formatNumber(stats.subscribers_tier_2 || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row style={{ paddingLeft: '1rem' }}>
                                        <Label style={{ fontSize: '0.9em', color: TIER_COLORS[3] }}>
                                            {TIER_NAMES[3]}
                                        </Label>
                                        <ValueBox>
                                            <Mono style={{ fontSize: '0.9em' }}>{formatNumber(stats.subscribers_tier_3 || 0)}</Mono>
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
                                            <Mono>{formatNumber(stats.total_posts || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Comments
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(stats.total_comments || 0)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Votes
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(stats.total_votes || 0)}</Mono>
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
                                                ↑{formatNumber(stats.upvotes || 0)} / ↓{formatNumber(stats.downvotes || 0)}
                                            </Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Avg Posts/User
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(stats.average_posts_per_user || 0, 1)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Avg Comments/Post
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(stats.average_comments_per_post || 0, 1)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    <Row>
                                        <Label>
                                            Avg Votes/User
                                        </Label>
                                        <ValueBox>
                                            <Mono>{formatNumber(stats.average_votes_per_user || 0, 1)}</Mono>
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
                                            <Mono>{formatPercentage((stats.edit_frequency || 0) * 100, 1)}</Mono>
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
                                            <Mono>{formatPercentage((stats.delete_rate || 0) * 100, 1)}</Mono>
                                        </ValueBox>
                                    </Row>
                                    {stats.most_active_topics && stats.most_active_topics.length > 0 && (
                                        <>
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
                                                        {stats.most_active_topics.map((item, idx) => (
                                                            <StatItem key={idx}>
                                                                <Mono>#{item.topic}</Mono>
                                                                <Mono>{formatNumber(item.count)}</Mono>
                                                            </StatItem>
                                                        ))}
                                                    </StatList>
                                                </ValueBox>
                                            </Row>
                                        </>
                                    )}
                                    {stats.tag_counts && (
                                        <>
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
                                                            <Mono>{formatNumber(stats.tag_counts.safe || 0)}</Mono>
                                                        </StatItem>
                                                        <StatItem>
                                                            <Mono>Sensitive</Mono>
                                                            <Mono>{formatNumber(stats.tag_counts.sensitive || 0)}</Mono>
                                                        </StatItem>
                                                        <StatItem>
                                                            <Mono>Porn</Mono>
                                                            <Mono>{formatNumber(stats.tag_counts.porn || 0)}</Mono>
                                                        </StatItem>
                                                        <StatItem>
                                                            <Mono>Violence</Mono>
                                                            <Mono>{formatNumber(stats.tag_counts.violence || 0)}</Mono>
                                                        </StatItem>
                                                        <StatItem>
                                                            <Mono>Gore</Mono>
                                                            <Mono>{formatNumber(stats.tag_counts.gore || 0)}</Mono>
                                                        </StatItem>
                                                        <StatItem>
                                                            <Mono>Death</Mono>
                                                            <Mono>{formatNumber(stats.tag_counts.death || 0)}</Mono>
                                                        </StatItem>
                                                    </StatList>
                                                </ValueBox>
                                            </Row>
                                        </>
                                    )}
                                    {stats.device_breakdown && (
                                        <>
                                            <SectionTitle>
                                                Device Types
                                                <SectionInfoIcon data-tooltip="Session breakdown by device type (last 30 days).">
                                                    ?
                                                </SectionInfoIcon>
                                            </SectionTitle>
                                            <Row>
                                                <Label>
                                                    By Device
                                                </Label>
                                                <ValueBox>
                                                    <StatList>
                                                        <StatItem>
                                                            <Mono>Desktop</Mono>
                                                            <Mono>{stats.device_breakdown.desktop}</Mono>
                                                        </StatItem>
                                                        <StatItem>
                                                            <Mono>Mobile</Mono>
                                                            <Mono>{stats.device_breakdown.mobile}</Mono>
                                                        </StatItem>
                                                        <StatItem>
                                                            <Mono>Tablet</Mono>
                                                            <Mono>{stats.device_breakdown.tablet}</Mono>
                                                        </StatItem>
                                                        {stats.device_breakdown.other && stats.device_breakdown.other !== "0%" && (
                                                            <StatItem>
                                                                <Mono>Other</Mono>
                                                                <Mono>{stats.device_breakdown.other}</Mono>
                                                            </StatItem>
                                                        )}
                                                    </StatList>
                                                </ValueBox>
                                            </Row>
                                        </>
                                    )}
                                    {stats.browser_breakdown && stats.browser_breakdown.length > 0 && (
                                        <>
                                            <SectionTitle>
                                                Browsers
                                                <SectionInfoIcon data-tooltip="Top browsers (last 30 days).">
                                                    ?
                                                </SectionInfoIcon>
                                            </SectionTitle>
                                            <Row>
                                                <Label>
                                                    Top Browsers
                                                </Label>
                                                <ValueBox>
                                                    <StatList>
                                                        {stats.browser_breakdown.map((item, idx) => (
                                                            <StatItem key={idx}>
                                                                <Mono>{item.name}</Mono>
                                                                <Mono>{item.pct}</Mono>
                                                            </StatItem>
                                                        ))}
                                                    </StatList>
                                                </ValueBox>
                                            </Row>
                                        </>
                                    )}
                                    {stats.os_breakdown && stats.os_breakdown.length > 0 && (
                                        <>
                                            <SectionTitle>
                                                Operating Systems
                                                <SectionInfoIcon data-tooltip="Top operating systems (last 30 days).">
                                                    ?
                                                </SectionInfoIcon>
                                            </SectionTitle>
                                            <Row>
                                                <Label>
                                                    Top OS
                                                </Label>
                                                <ValueBox>
                                                    <StatList>
                                                        {stats.os_breakdown.map((item, idx) => (
                                                            <StatItem key={idx}>
                                                                <Mono>{item.name}</Mono>
                                                                <Mono>{item.pct}</Mono>
                                                            </StatItem>
                                                        ))}
                                                    </StatList>
                                                </ValueBox>
                                            </Row>
                                        </>
                                    )}
                                </>
                            )}

                            {/* Signups Tab */}
                            {activeTab === 'signups' && signupsData && (
                                <>
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

                                    {signupsData.top_referrers && signupsData.top_referrers.length > 0 && (
                                        <>
                                            <SectionTitle>
                                                Top Referrers
                                                <SectionInfoIcon data-tooltip="Users who have invited the most new members.">
                                                    ?
                                                </SectionInfoIcon>
                                            </SectionTitle>
                                            <ValueBox style={{ padding: 0, overflow: 'auto' }}>
                                                <Table>
                                                    <thead>
                                                        <tr>
                                                            <Th>#</Th>
                                                            <Th>Referrer</Th>
                                                            <Th style={{ textAlign: 'right' }}>Invites</Th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        {signupsData.top_referrers.map((ref, idx) => (
                                                            <tr key={idx}>
                                                                <Td style={{ width: '40px', color: '#888' }}>{idx + 1}</Td>
                                                                {renderUserCell(ref)}
                                                                <Td style={{ textAlign: 'right', fontWeight: 'bold' }}>
                                                                    {formatNumber(ref.invite_count)}
                                                                </Td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </Table>
                                            </ValueBox>
                                        </>
                                    )}

                                    <SectionTitle>
                                        Recent Signups
                                        <SectionInfoIcon data-tooltip="Most recent users who signed up via invite codes.">
                                            ?
                                        </SectionInfoIcon>
                                    </SectionTitle>
                                    <SectionNote>Showing up to 100 most recent signups via invite codes.</SectionNote>
                                    <ValueBox style={{ padding: 0, overflow: 'auto' }}>
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
                                                {signupsData.signups && signupsData.signups.length > 0 ? (
                                                    signupsData.signups.map((signup, idx) => (
                                                        <tr key={idx}>
                                                            {renderUserCell(signup.signup)}
                                                            {renderUserCell(signup.referrer)}
                                                            <Td>
                                                                <Mono style={{ fontSize: '0.7rem' }}>{signup.code}</Mono>
                                                            </Td>
                                                            <Td>
                                                                <Mono style={{ fontSize: '0.7rem' }}>{formatDateShort(signup.used_at)}</Mono>
                                                            </Td>
                                                        </tr>
                                                    ))
                                                ) : (
                                                    <tr>
                                                        <Td colSpan={4} style={{ textAlign: 'center', color: '#888' }}>
                                                            No signups via invite codes yet.
                                                        </Td>
                                                    </tr>
                                                )}
                                            </tbody>
                                        </Table>
                                    </ValueBox>
                                </>
                            )}

                            {/* Subscribers Tab */}
                            {activeTab === 'subscribers' && subscribersData && (
                                <>
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
                                            <SummaryValue $color={TIER_COLORS[3]}>{formatNumber(subscribersData.count_tier_3 || 0)}</SummaryValue>
                                            <SummaryLabel>{TIER_NAMES[3]}</SummaryLabel>
                                        </SummaryItem>
                                        <SummaryItem>
                                            <SummaryValue $color={TIER_COLORS[2]}>{formatNumber(subscribersData.count_tier_2 || 0)}</SummaryValue>
                                            <SummaryLabel>{TIER_NAMES[2]}</SummaryLabel>
                                        </SummaryItem>
                                        <SummaryItem>
                                            <SummaryValue $color={TIER_COLORS[1]}>{formatNumber(subscribersData.count_tier_1 || 0)}</SummaryValue>
                                            <SummaryLabel>{TIER_NAMES[1]}</SummaryLabel>
                                        </SummaryItem>
                                    </SummaryBox>

                                    {/* Tier 3 - Distinguished */}
                                    <TierSection>
                                        <TierHeader $color={TIER_COLORS[3]}>
                                            <TierBadge $color={TIER_COLORS[3]}>{TIER_NAMES[3]}</TierBadge>
                                            <TierCount>({formatNumber(subscribersData.count_tier_3 || 0)})</TierCount>
                                        </TierHeader>
                                        {renderSubscriberTable(subscribersData.tier_3, TIER_COLORS[3])}
                                    </TierSection>

                                    {/* Tier 2 - Established */}
                                    <TierSection>
                                        <TierHeader $color={TIER_COLORS[2]}>
                                            <TierBadge $color={TIER_COLORS[2]}>{TIER_NAMES[2]}</TierBadge>
                                            <TierCount>({formatNumber(subscribersData.count_tier_2 || 0)})</TierCount>
                                        </TierHeader>
                                        {renderSubscriberTable(subscribersData.tier_2, TIER_COLORS[2])}
                                    </TierSection>

                                    {/* Tier 1 - Trusted */}
                                    <TierSection>
                                        <TierHeader $color={TIER_COLORS[1]}>
                                            <TierBadge $color={TIER_COLORS[1]}>{TIER_NAMES[1]}</TierBadge>
                                            <TierCount>({formatNumber(subscribersData.count_tier_1 || 0)})</TierCount>
                                        </TierHeader>
                                        {renderSubscriberTable(subscribersData.tier_1, TIER_COLORS[1])}
                                    </TierSection>
                                </>
                            )}

                            {/* Accounts Tab */}
                            {activeTab === 'accounts' && accountsData && (
                                <>
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
                                    <ValueBox style={{ padding: 0, overflow: 'auto' }}>
                                        <Table>
                                            <thead>
                                                <tr>
                                                    <Th>#</Th>
                                                    <Th>Address</Th>
                                                    <Th>Name</Th>
                                                    <Th style={{ textAlign: 'right' }}>Balance (MIRAGE)</Th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {accountsData.accounts && accountsData.accounts.length > 0 ? (
                                                    accountsData.accounts.map((account, idx) => (
                                                        <tr key={idx}>
                                                            <Td style={{ width: '40px', color: '#888' }}>{idx + 1}</Td>
                                                            <Td>
                                                                <UserLink to={`/profile?address=${account.address}`}>
                                                                    <AddressText>{truncateAddress(account.address)}</AddressText>
                                                                </UserLink>
                                                            </Td>
                                                            <Td>
                                                                {account.username ? (
                                                                    <UserLink to={`/profile?address=${account.address}`}>
                                                                        {account.username}
                                                                    </UserLink>
                                                                ) : (
                                                                    <span style={{ color: '#666' }}>-</span>
                                                                )}
                                                            </Td>
                                                            <Td style={{ textAlign: 'right' }}>
                                                                <Mono style={{ fontWeight: 'bold' }}>{formatMirage(account.balance)}</Mono>
                                                            </Td>
                                                        </tr>
                                                    ))
                                                ) : (
                                                    <tr>
                                                        <Td colSpan={4} style={{ textAlign: 'center', color: '#888' }}>
                                                            No accounts found.
                                                        </Td>
                                                    </tr>
                                                )}
                                            </tbody>
                                        </Table>
                                    </ValueBox>
                                </>
                            )}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
