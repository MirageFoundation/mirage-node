import React, { useEffect, useState } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import { useLocation } from "react-router-dom";
import Api from '../lib/api';
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../styled/Layout";
import { InfoIcon as TooltipInfoIcon } from "../components/Tooltip";

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

export default function StatsView() {
    const location = useLocation();
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        const fetchStats = async () => {
            try {
                setLoading(true);
                const data = await Api.get('get_stats', {}, { timeoutMs: 30000 });
                setStats(data);
                setError(null);
            } catch (err) {
                setError(err.message || 'Failed to load stats');
            } finally {
                setLoading(false);
            }
        };
        fetchStats();
    }, []);

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

    const getDAUTrend = () => {
        if (!stats || !stats.dau_today || !stats.dau_yesterday) return null;
        if (stats.dau_today > stats.dau_yesterday) return 'up';
        if (stats.dau_today < stats.dau_yesterday) return 'down';
        return 'same';
    };

    if (loading || error || !stats) {
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
                            <ContainerTab>Stats</ContainerTab>
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
                        <ContainerTab>Stats</ContainerTab>
                        <ContainerBody>
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
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}

