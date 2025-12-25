import React, { useEffect, useState } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import { useLocation } from "react-router-dom";
import Api from "../lib/api";
import Storage from "../utils/Storage";
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import Button from "../components/Button";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../styled/Layout";

const Row = styled.div`
    display: grid;
    grid-template-columns: 8rem minmax(0, 1fr);
    gap: 0.5rem;
    align-items: start;
    margin: 0.4rem 0;
    @media (max-width: 1000px) {
        grid-template-columns: 1fr;
        gap: 0.35rem;
    }
`;

const RowCentered = styled(Row)`
    align-items: center;
`;

const Label = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#ccc'};
    font-weight: 600;
    font-size: 0.85rem;
`;

const ValueBox = styled.div`
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.6rem 0.85rem;
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;

const ValueBoxWithButton = styled(ValueBox)`
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: nowrap;
    overflow: hidden;
    @media (max-width: 1000px) {
        flex-wrap: wrap;
        gap: 0.5rem;
    }
`;

const Mono = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-size: 0.85rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
`;

const InlineMono = styled(Mono)`
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
    min-width: 0;
    font-size: 0.75rem;
`;

const SectionTitle = styled.h3`
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-size: 0.95rem;
    font-weight: 600;
    margin: 1.5rem 0 0.75rem 0;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
`;

const WarningBox = styled.div`
    background-color: rgba(234, 179, 8, 0.1);
    border: 1px solid rgba(234, 179, 8, 0.3);
    border-radius: 8px;
    padding: 0.85rem;
    margin-top: 1.5rem;
    font-size: 0.8rem;
    line-height: 1.5;
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
`;

const WarningTitle = styled.div`
    color: #eab308;
    font-weight: 600;
    margin-bottom: 0.5rem;
    font-size: 0.85rem;
`;

const RewardAmount = styled.span`
    color: ${({ $positive }) => $positive ? '#22c55e' : '#eab308'};
    font-weight: 600;
`;

const EmptyState = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.85rem;
    padding: 0.5rem 0;
`;

const ReferredByBox = styled.div`
    background: linear-gradient(135deg, rgba(34, 197, 94, 0.1) 0%, rgba(34, 197, 94, 0.05) 100%);
    border: 1px solid rgba(34, 197, 94, 0.3);
    border-radius: 8px;
    padding: 0.85rem;
    margin-bottom: 1rem;
    font-size: 0.85rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#aaa'};
`;

const ReferredByLink = styled.a`
    color: #22c55e;
    font-weight: 600;
    text-decoration: none;
    &:hover {
        text-decoration: underline;
    }
`;

const HowItWorks = styled.div`
    background-color: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.85rem;
    margin-top: 1rem;
    font-size: 0.8rem;
    line-height: 1.6;
`;

const HowItWorksTitle = styled.div`
    font-weight: 600;
    margin-bottom: 0.5rem;
    font-size: 0.85rem;
`;

const HowItWorksList = styled.ul`
    margin: 0;
    padding-left: 1.2rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#aaa'};
`;

const ExampleBox = styled.div`
    margin-top: 0.75rem;
    padding-top: 0.6rem;
    border-top: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    font-size: 0.78rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#aaa'};
    line-height: 1.5;
`;

const TreeContainer = styled.div`
    margin-top: 0.5rem;
`;

const TreeNode = styled.div`
    margin-left: ${({ $level }) => ($level - 1) * 1.25}rem;
    padding: 0.4rem 0;
    border-left: ${({ $level }) => $level > 1 ? '2px solid #333' : 'none'};
    padding-left: ${({ $level }) => $level > 1 ? '0.75rem' : '0'};
`;

const TreeNodeContent = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.35rem 0.6rem;
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border-radius: 6px;
    font-size: 0.8rem;
`;

const TreeUsername = styled.a`
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    text-decoration: none;
    font-weight: 500;
    &:hover {
        text-decoration: underline;
    }
`;

const TreeLevelWrapper = styled.span`
    position: relative;
    display: inline-block;
`;

const TreeLevel = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.7rem;
    padding: 0.1rem 0.35rem;
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1a1d21'};
    border-radius: 4px;
    cursor: help;
`;

const TreeLevelTooltip = styled.span`
    visibility: hidden;
    position: absolute;
    bottom: 125%;
    left: 50%;
    transform: translateX(-50%);
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    padding: 0.4rem 0.6rem;
    border-radius: 6px;
    font-size: 0.75rem;
    white-space: nowrap;
    z-index: 100;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);

    ${TreeLevelWrapper}:hover & {
        visibility: visible;
    }

    &::after {
        content: '';
        position: absolute;
        top: 100%;
        left: 50%;
        transform: translateX(-50%);
        border: 5px solid transparent;
        border-top-color: ${({ theme }) => theme?.colors?.border || '#444'};
    }
`;

const TreeEarnings = styled.span`
    font-size: 0.75rem;
    margin-left: auto;
    display: flex;
    gap: 0.5rem;
`;

const TreePending = styled.span`
    color: #eab308;
    font-weight: 600;
`;

const TreePaid = styled.span`
    color: #22c55e;
    font-weight: 600;
`;

const TreeDenied = styled.span`
    color: #ef4444;
    font-weight: 600;
`;

const NextUpdateBox = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.75rem;
    padding: 0.6rem 0.85rem;
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    font-size: 0.6rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

const NextUpdateTime = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-weight: 500;
`;

const ExpandButton = styled.button`
    background: none;
    border: none;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    cursor: pointer;
    padding: 0;
    font-size: 0.75rem;
    margin-right: 0.25rem;
    &:hover {
        color: ${({ theme }) => theme?.colors?.text || '#eee'};
    }
`;

function ReferralTreeNode({ node, level = 1 }) {
    const [expanded, setExpanded] = useState(level <= 2);
    const hasChildren = node.children && node.children.length > 0;

    return (
        <TreeNode $level={level}>
            <TreeNodeContent>
                {hasChildren && (
                    <ExpandButton onClick={() => setExpanded(!expanded)}>
                        {expanded ? '▼' : '▶'}
                    </ExpandButton>
                )}
                {!hasChildren && <span style={{ width: '0.9rem' }} />}
                <TreeUsername href={`/profile?address=${node.address}`}>
                    @{node.username || node.address.slice(0, 10) + '...'}
                </TreeUsername>
                <TreeLevelWrapper>
                    <TreeLevel>L{level}</TreeLevel>
                    <TreeLevelTooltip>You earn {node.rate} MIRAGE per active day</TreeLevelTooltip>
                </TreeLevelWrapper>
                <TreeEarnings>
                    {(node.paid || 0) > 0 && (
                        <TreePaid>paid: {node.paid.toFixed(4)}</TreePaid>
                    )}
                    {(node.denied || 0) > 0 && (
                        <TreeDenied>denied: {node.denied.toFixed(4)}</TreeDenied>
                    )}
                    <TreePending>pending: {node.pending?.toFixed(4) || '0.0000'}</TreePending>
                </TreeEarnings>
            </TreeNodeContent>
            {expanded && hasChildren && (
                <div>
                    {node.children.map((child, idx) => (
                        <ReferralTreeNode key={idx} node={child} level={level + 1} />
                    ))}
                </div>
            )}
        </TreeNode>
    );
}

export default function InviteView({ state }) {
    const location = useLocation();
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [stats, setStats] = useState(null);
    const [countdownText, setCountdownText] = useState('');

    const address = (state && state.publicKey) ? state.publicKey : Storage.load('publicKey', '');
    const origin = window.location.origin;
    const hostname = window.location.hostname;
    const isReferralsEnabled = hostname === 'mirage.talk' || hostname === 'localhost';
    const homeLink = address ? `${origin}/?referrer=${address}` : '';
    const createLink = address ? `${origin}/create_account?referrer=${address}` : '';
    const [homeCopied, setHomeCopied] = useState(false);
    const [createCopied, setCreateCopied] = useState(false);

    const formatNextUpdate = (nextTs) => {
        if (!nextTs) return 'Unknown';
        const now = Math.floor(Date.now() / 1000);
        const diff = nextTs - now;
        if (diff <= 0) return 'Soon';
        if (diff < 60) return `${diff}s`;
        if (diff < 3600) return `${Math.floor(diff / 60)}m`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}m`;
        return `${Math.floor(diff / 86400)}d ${Math.floor((diff % 86400) / 3600)}h`;
    };

    useEffect(() => {
        if (!address) {
            setLoading(false);
            return;
        }

        const fetchStats = async () => {
            try {
                const resp = await Api.get(`/referral/stats?address=${address}`);
                if (resp.error) {
                    setError(resp.error);
                } else {
                    setStats(resp);
                    if (resp.next_update_ts) {
                        setCountdownText(formatNextUpdate(resp.next_update_ts));
                    }
                }
            } catch (err) {
                setError('Failed to load referral stats');
            } finally {
                setLoading(false);
            }
        };

        fetchStats();
    }, [address]);

    // Live countdown update every 30 seconds
    useEffect(() => {
        if (!stats?.next_update_ts) return;

        const updateCountdown = () => {
            setCountdownText(formatNextUpdate(stats.next_update_ts));
        };

        const interval = setInterval(updateCountdown, 30000);
        return () => clearInterval(interval);
    }, [stats?.next_update_ts]);

    const handleCopyHome = () => {
        navigator.clipboard.writeText(homeLink);
        setHomeCopied(true);
        setTimeout(() => setHomeCopied(false), 1500);
    };

    const handleCopyCreate = () => {
        navigator.clipboard.writeText(createLink);
        setCreateCopied(true);
        setTimeout(() => setCreateCopied(false), 1500);
    };

    if (!isReferralsEnabled) {
        return (
            <ContentGrid>
                <Helmet><title>Invite &amp; Earn | Mirage</title></Helmet>
                <Sidebar currentPath={location.pathname} state={state} />
                <div>
                    <TopBar state={state} />
                    <ModernPostFeed>
                        <MobileHeader />
                        <TabbedContainer>
                            <ContainerTab>Invite &amp; Earn</ContainerTab>
                            <ContainerBody>
                                <EmptyState>Referrals are not available on this server.</EmptyState>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </div>
            </ContentGrid>
        );
    }

    if (!address) {
        return (
            <ContentGrid>
                <Helmet><title>Invite &amp; Earn | Mirage</title></Helmet>
                <Sidebar currentPath={location.pathname} state={state} />
                <div>
                    <TopBar state={state} />
                    <ModernPostFeed>
                        <MobileHeader />
                        <TabbedContainer>
                            <ContainerTab>Invite &amp; Earn</ContainerTab>
                            <ContainerBody>
                                <EmptyState>Please log in to access your referral link.</EmptyState>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </div>
            </ContentGrid>
        );
    }

    return (
        <ContentGrid>
            <Helmet><title>Invite &amp; Earn | Mirage</title></Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerTab>Invite &amp; Earn</ContainerTab>
                        <ContainerBody>
                            {stats?.referred_by && (
                                <ReferredByBox>
                                    You were invited by <ReferredByLink href={`/profile?address=${stats.referred_by.address}`}>
                                        @{stats.referred_by.username || stats.referred_by.address.slice(0, 12) + '...'}
                                    </ReferredByLink>
                                </ReferredByBox>
                            )}
                            <SectionTitle style={{ marginTop: '0' }}>Your Referral Links</SectionTitle>
                            <RowCentered>
                                <Label>Link #1:</Label>
                                <ValueBoxWithButton>
                                    <InlineMono>{homeLink}</InlineMono>
                                    <Button
                                        onClick={handleCopyHome}
                                        size="sm"
                                        minWidth="copy"
                                        copied={homeCopied}
                                        mobileFullWidth
                                    >
                                        {homeCopied ? 'Copied!' : 'Copy'}
                                    </Button>
                                </ValueBoxWithButton>
                            </RowCentered>
                            <RowCentered>
                                <Label>Link #2:</Label>
                                <ValueBoxWithButton>
                                    <InlineMono>{createLink}</InlineMono>
                                    <Button
                                        onClick={handleCopyCreate}
                                        size="sm"
                                        minWidth="copy"
                                        copied={createCopied}
                                        mobileFullWidth
                                    >
                                        {createCopied ? 'Copied!' : 'Copy'}
                                    </Button>
                                </ValueBoxWithButton>
                            </RowCentered>

                            <HowItWorks>
                                <HowItWorksTitle>How it works</HowItWorksTitle>
                                <HowItWorksList>
                                    <li>Share your referral link with friends</li>
                                    <li>Earn 1 MIRAGE for each day a direct referral posts or comments (L1 = 1x)</li>
                                    <li>Earn 0.5 MIRAGE for each day their referrals post (L2 = 0.5x)</li>
                                    <li>Earn 0.25, 0.125, 0.0625 for L3, L4, L5 respectively</li>
                                    <li>Max 10 active days count per referral</li>
                                    <li>Rewards are reviewed weekly and paid out after approval</li>
                                </HowItWorksList>
                                <ExampleBox>
                                    <strong>Example:</strong> You invite Alice and Bob. Alice is active for 5 days and invites Carol, who is active for 3 days.
                                    You earn: (5 × 1) + (5 × 1) + (3 × 0.5) = <strong>11.5 MIRAGE</strong>
                                </ExampleBox>
                            </HowItWorks>

                            <SectionTitle>Your Rewards</SectionTitle>

                            {loading ? (
                                <EmptyState>Loading...</EmptyState>
                            ) : error ? (
                                <EmptyState style={{ color: '#f87171' }}>{error}</EmptyState>
                            ) : stats ? (
                                <>
                                    <RowCentered>
                                        <Label>Pending:</Label>
                                        <ValueBox>
                                            <RewardAmount $positive={false}>
                                                {stats.pending_total?.toFixed(4) || '0.0000'} MIRAGE
                                            </RewardAmount>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Paid:</Label>
                                        <ValueBox>
                                            <RewardAmount $positive={true}>
                                                {stats.paid_total?.toFixed(4) || '0.0000'} MIRAGE
                                            </RewardAmount>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Referrals:</Label>
                                        <ValueBox>
                                            <Mono>{stats.total_referrals || 0} users (all levels)</Mono>
                                        </ValueBox>
                                    </RowCentered>

                                    {stats.referral_tree && stats.referral_tree.length > 0 && (
                                        <>
                                            <SectionTitle>Your Referral Tree</SectionTitle>
                                            <TreeContainer>
                                                {stats.referral_tree.map((node, idx) => (
                                                    <ReferralTreeNode key={idx} node={node} level={1} />
                                                ))}
                                            </TreeContainer>
                                        </>
                                    )}

                                    {(!stats.referral_tree || stats.referral_tree.length === 0) && (
                                        <EmptyState>No referrals yet. Share your link to get started!</EmptyState>
                                    )}
                                </>
                            ) : (
                                <EmptyState>No referral data available.</EmptyState>
                            )}

                            <WarningBox>
                                <WarningTitle>Important</WarningTitle>
                                Creating fake accounts (sockpuppets) to game the referral system is strictly prohibited.
                                All referred accounts are reviewed for authenticity. If sockpuppet activity is detected,
                                <strong> your account will be suspended and all pending rewards will be forfeited</strong>.
                                Only invite real people who will genuinely participate in Mirage.
                            </WarningBox>

                            {stats && countdownText && (
                                <NextUpdateBox>
                                    Next rewards update in: <NextUpdateTime>{countdownText}</NextUpdateTime>
                                </NextUpdateBox>
                            )}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
