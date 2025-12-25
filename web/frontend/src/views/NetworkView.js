import React, { useEffect, useState } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import { useLocation, useNavigate } from "react-router-dom";
import Api from "../lib/api";
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import Button from "../components/Button";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, TabsRow, ClickableTab } from "../styled/Layout";

const Row = styled.div`
    display: grid;
    grid-template-columns: 7rem minmax(0, 1fr);
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

const SectionRow = styled(Row)`
    margin-top: 1.5rem;
`;

const Label = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#ccc'};
    font-weight: 600;
    font-size: 0.85rem;
`;

const SectionLabel = styled(Label)`
    padding-top: 0.6rem;
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
`;

const PeerList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
`;

const PeerItem = styled.div`
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border-radius: 8px;
    transition: background 0.2s ease;

    &:hover {
        background: ${({ theme }) => theme?.colors?.panelAlt || '#2E3238'};
    }
`;

const PeerLink = styled.a`
    color: ${({ theme }) => theme?.colors?.link || '#FFFFFF'};
    text-decoration: none;
    font-size: 0.85rem;
    font-weight: 500;
    transition: color 0.2s ease;
    &:hover { color: #667eea; }
`;

const PeerIp = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    font-size: 0.75rem;
`;

const AccountList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
`;

const AccountItem = styled.div`
    display: grid;
    grid-template-columns: 2rem 1fr auto;
    align-items: center;
    gap: 0.5rem;
    padding: 0.4rem 0.6rem;
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border-radius: 6px;
    
    @media (max-width: 1000px) {
        grid-template-columns: 1.5rem 1fr auto;
        gap: 0.35rem;
        padding: 0.35rem 0.5rem;
    }
`;

const AccountRank = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.75rem;
    font-weight: 600;
    text-align: center;
`;

const AccountName = styled.a`
    color: ${({ theme }) => theme?.colors?.link || '#FFFFFF'};
    text-decoration: none;
    font-size: 0.8rem;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    &:hover { color: #667eea; }
`;

const AccountBalance = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-size: 0.8rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    white-space: nowrap;
`;

const ChartContainer = styled.div`
    width: 100%;
    height: 120px;
`;

const ChartSvg = styled.svg`
    width: 100%;
    height: 100%;
`;

const ChartLabel = styled.div`
    display: flex;
    justify-content: space-between;
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

const ChartLegend = styled.div`
    display: flex;
    gap: 1rem;
    font-size: 0.7rem;
`;

const LegendItem = styled.span`
    display: flex;
    align-items: center;
    gap: 0.25rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

const LegendDot = styled.span`
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: ${props => props.color};
`;

function DifficultyChart({ history }) {
    if (!history || history.length < 2) {
        return (
            <ChartContainer>
                <Mono style={{ fontSize: '0.75rem', color: '#888' }}>
                    (chart available after more data is collected)
                </Mono>
            </ChartContainer>
        );
    }

    const width = 400;
    const height = 100;
    const padding = { top: 10, right: 35, bottom: 5, left: 30 };
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;

    // Difficulty data (left axis, blue)
    const difficulties = history.map(h => h.difficulty);
    const minDiff = Math.min(...difficulties);
    const maxDiff = Math.max(...difficulties);
    const diffRange = maxDiff - minDiff || 1;

    // Message count data (right axis, green)
    const msgCounts = history.map(h => h.msg_count || 0);
    const maxMsg = Math.max(...msgCounts, 1);

    const minTs = history[0].timestamp;
    const maxTs = history[history.length - 1].timestamp;
    const tsRange = maxTs - minTs || 1;

    // Difficulty line (blue)
    const diffPoints = history.map((h) => {
        const x = padding.left + ((h.timestamp - minTs) / tsRange) * chartWidth;
        const y = padding.top + chartHeight - ((h.difficulty - minDiff) / diffRange) * chartHeight;
        return `${x},${y}`;
    }).join(' ');

    // Message count line (green)
    const msgPoints = history.map((h) => {
        const x = padding.left + ((h.timestamp - minTs) / tsRange) * chartWidth;
        const y = padding.top + chartHeight - ((h.msg_count || 0) / maxMsg) * chartHeight;
        return `${x},${y}`;
    }).join(' ');

    const hoursAgo = Math.round((Date.now() / 1000 - minTs) / 3600);

    return (
        <>
            <ChartLegend>
                <LegendItem><LegendDot color="#667eea" /> Difficulty</LegendItem>
                <LegendItem><LegendDot color="#48bb78" /> Msgs/Window</LegendItem>
            </ChartLegend>
            <ChartContainer>
                <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                    {/* Grid lines */}
                    <line x1={padding.left} y1={padding.top} x2={padding.left} y2={height - padding.bottom} stroke="#444" strokeWidth="1" />
                    <line x1={padding.left} y1={height - padding.bottom} x2={width - padding.right} y2={height - padding.bottom} stroke="#444" strokeWidth="1" />
                    <line x1={width - padding.right} y1={padding.top} x2={width - padding.right} y2={height - padding.bottom} stroke="#444" strokeWidth="1" />

                    {/* Left Y-axis labels (Difficulty - blue) */}
                    <text x={padding.left - 5} y={padding.top + 4} fill="#667eea" fontSize="9" textAnchor="end">{maxDiff}</text>
                    <text x={padding.left - 5} y={height - padding.bottom} fill="#667eea" fontSize="9" textAnchor="end">{minDiff}</text>

                    {/* Right Y-axis labels (Msgs - green) */}
                    <text x={width - padding.right + 5} y={padding.top + 4} fill="#48bb78" fontSize="9" textAnchor="start">{maxMsg}</text>
                    <text x={width - padding.right + 5} y={height - padding.bottom} fill="#48bb78" fontSize="9" textAnchor="start">0</text>

                    {/* Message count area fill (green, behind) */}
                    <polygon
                        fill="rgba(72, 187, 120, 0.15)"
                        points={`${padding.left},${height - padding.bottom} ${msgPoints} ${width - padding.right},${height - padding.bottom}`}
                    />

                    {/* Message count line (green) */}
                    <polyline
                        fill="none"
                        stroke="#48bb78"
                        strokeWidth="1.5"
                        points={msgPoints}
                    />

                    {/* Difficulty line (blue, on top) */}
                    <polyline
                        fill="none"
                        stroke="#667eea"
                        strokeWidth="2"
                        points={diffPoints}
                    />
                </ChartSvg>
            </ChartContainer>
            <ChartLabel>
                <span>{hoursAgo}h ago</span>
                <span>now</span>
            </ChartLabel>
        </>
    );
}

function formatMirage(umirage) {
    const n = Number(umirage);
    if (!isFinite(n)) return '0.000000';
    const v = n / 1_000_000;
    const [intPart, decPart] = v.toFixed(6).split('.');
    const formattedInt = Number(intPart).toLocaleString('en-US');
    return `${formattedInt}.${decPart}`;
}

export default function NetworkView({ state }) {
    const location = useLocation();
    const navigate = useNavigate();

    // Determine initial tab from URL
    const getInitialTab = () => {
        if (location.pathname === '/server') return 'server';
        return 'network';
    };
    const [activeTab, setActiveTab] = useState(getInitialTab);

    const [cfg, setCfg] = useState({
        block_time: undefined,
        pow_difficulty: undefined,
        pow_message_count: undefined,
        pow_calm_sequence: undefined,
        pow_last_change_height: undefined,
        current_height: undefined,
        difficulty_history: [],
        validator_moniker: undefined,
        validator_account_address: undefined,
        validator_operator_address: undefined,
        validator_consensus_address: undefined,
    });
    const [peers, setPeers] = useState(null);
    const [serverBalance, setServerBalance] = useState(null);
    const [copiedAddress, setCopiedAddress] = useState(null);
    const [circulationStats, setCirculationStats] = useState({ total_supply: null, top_accounts: [] });

    // Update tab when URL changes
    useEffect(() => {
        if (location.pathname === '/server') {
            setActiveTab('server');
        } else if (location.pathname === '/network') {
            setActiveTab('network');
        }
    }, [location.pathname]);

    // Load static validator info from cached config (once)
    useEffect(() => {
        try {
            const configData = localStorage.getItem('configData');
            if (configData) {
                const cached = JSON.parse(configData);
                setCfg(prev => ({
                    ...prev,
                    validator_moniker: cached.validator_moniker || undefined,
                    validator_account_address: cached.validator_account_address,
                    validator_operator_address: cached.validator_operator_address,
                    validator_consensus_address: cached.validator_consensus_address,
                }));
            }
        } catch (_) { }
    }, []);

    // Fetch network stats (dynamic data)
    useEffect(() => {
        let cancelled = false;
        const fetchNetworkStats = async () => {
            try {
                const data = await Api.get('get_network_stats', undefined, { timeoutMs: 10000 });
                if (!cancelled && data) {
                    const sb = Number(data.server_balance);
                    if (isFinite(sb)) setServerBalance(sb);
                    setCfg(prev => ({
                        ...prev,
                        block_time: (typeof data.block_time !== 'undefined') ? Number(data.block_time) : undefined,
                        pow_difficulty: (typeof data.pow_difficulty !== 'undefined') ? Number(data.pow_difficulty) : undefined,
                        pow_message_count: (typeof data.pow_message_count !== 'undefined') ? Number(data.pow_message_count) : undefined,
                        pow_calm_sequence: (typeof data.pow_calm_sequence !== 'undefined') ? Number(data.pow_calm_sequence) : undefined,
                        pow_last_change_height: (typeof data.pow_last_change_height !== 'undefined') ? Number(data.pow_last_change_height) : undefined,
                        current_height: (typeof data.current_height !== 'undefined') ? Number(data.current_height) : undefined,
                        difficulty_history: Array.isArray(data.difficulty_history) ? data.difficulty_history : [],
                    }));
                }
            } catch (_) { }
        };
        fetchNetworkStats();
        // Auto-refresh every 10 seconds
        const interval = setInterval(fetchNetworkStats, 10000);
        return () => { cancelled = true; clearInterval(interval); };
    }, []);

    useEffect(() => {
        let cancelled = false;
        const fetchPeers = async () => {
            try {
                const data = await Api.get('get_peers', undefined, { timeoutMs: 5000 });
                if (!cancelled) {
                    const list = (data && Array.isArray(data.peers)) ? data.peers : [];
                    setPeers(list);
                }
            } catch (_) {
                if (!cancelled) setPeers([]);
            }
        };
        fetchPeers();
        return () => { cancelled = true; };
    }, []);

    // Fetch circulation stats
    useEffect(() => {
        let cancelled = false;
        const fetchCirculationStats = async () => {
            try {
                const data = await Api.get('get_circulation_stats', undefined, { timeoutMs: 15000 });
                if (!cancelled && data) {
                    setCirculationStats({
                        total_supply: data.total_supply ?? null,
                        top_accounts: Array.isArray(data.top_accounts) ? data.top_accounts : [],
                    });
                }
            } catch (_) { }
        };
        fetchCirculationStats();
        const interval = setInterval(fetchCirculationStats, 60000);
        return () => { cancelled = true; clearInterval(interval); };
    }, []);

    const handleTabChange = (tab) => {
        if (tab === activeTab) return;
        setActiveTab(tab);
        navigate(tab === 'server' ? '/server' : '/network', { replace: true });
    };

    const toHttpUrl = (peer) => {
        try {
            if (peer.moniker && (peer.moniker.startsWith('http://') || peer.moniker.startsWith('https://'))) {
                return peer.moniker.endsWith('/') ? peer.moniker : `${peer.moniker}/`;
            }
            if (peer.ip) {
                const formattedHost = (typeof peer.ip === 'string' && peer.ip.includes(':')) ? `[${peer.ip}]` : peer.ip;
                return `http://${formattedHost}/`;
            }
            return '#';
        } catch (_) {
            return '#';
        }
    };

    const getDisplayName = (peer) => {
        if (peer.moniker && (peer.moniker.startsWith('http://') || peer.moniker.startsWith('https://'))) {
            return peer.moniker;
        }
        if (peer.ip) return `http://${peer.ip}`;
        return '(unknown)';
    };

    return (
        <ContentGrid>
            <Helmet>
                <title>Network | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow role="tablist" aria-label="Network sections">
                            <ClickableTab
                                type="button"
                                role="tab"
                                aria-selected={activeTab === 'network'}
                                $active={activeTab === 'network'}
                                onClick={() => handleTabChange('network')}
                            >
                                Network
                            </ClickableTab>
                            <ClickableTab
                                type="button"
                                role="tab"
                                aria-selected={activeTab === 'server'}
                                $active={activeTab === 'server'}
                                onClick={() => handleTabChange('server')}
                            >
                                Server
                            </ClickableTab>
                        </TabsRow>
                        <ContainerBody>
                            {activeTab === 'network' && (
                                <>
                                    <RowCentered>
                                        <Label>Circulation:</Label>
                                        <ValueBox>
                                            <Mono>
                                                {circulationStats.total_supply !== null
                                                    ? `${formatMirage(circulationStats.total_supply)} MIRAGE`
                                                    : '(loading...)'}
                                            </Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Block Time:</Label>
                                        <ValueBox>
                                            <Mono>{typeof cfg.block_time === 'number' ? `${cfg.block_time}s` : '(loading...)'}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Difficulty:</Label>
                                        <ValueBox>
                                            <Mono>{typeof cfg.pow_difficulty === 'number' ? `${cfg.pow_difficulty} bits` : '(loading...)'}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Msgs/Window:</Label>
                                        <ValueBox>
                                            <Mono>{typeof cfg.pow_message_count === 'number' ? cfg.pow_message_count : '(loading...)'}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Calm Streak:</Label>
                                        <ValueBox>
                                            <Mono>{typeof cfg.pow_calm_sequence === 'number' ? cfg.pow_calm_sequence : '(loading...)'}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Height:</Label>
                                        <ValueBox>
                                            <Mono>{typeof cfg.current_height === 'number' ? cfg.current_height.toLocaleString() : '(loading...)'}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <SectionRow>
                                        <SectionLabel>History:</SectionLabel>
                                        <ValueBox>
                                            <DifficultyChart history={cfg.difficulty_history} />
                                        </ValueBox>
                                    </SectionRow>
                                    <SectionRow>
                                        <SectionLabel>Sites:</SectionLabel>
                                        <ValueBox>
                                            {peers === null ? (
                                                <Mono>(loading...)</Mono>
                                            ) : (
                                                <PeerList>
                                                    {(() => {
                                                        if (!peers || !Array.isArray(peers) || peers.length === 0) {
                                                            return <Mono>(none)</Mono>;
                                                        }
                                                        return peers.map((peer, idx) => {
                                                            const peerObj = typeof peer === 'string' ? { ip: peer, moniker: null } : peer;
                                                            if (!peerObj.ip && !peerObj.moniker) {
                                                                return null;
                                                            }
                                                            return (
                                                                <PeerItem key={`peer-${idx}`}>
                                                                    <PeerLink href={toHttpUrl(peerObj)} target="_blank" rel="noopener noreferrer">
                                                                        {getDisplayName(peerObj)}
                                                                    </PeerLink>
                                                                    {peerObj.moniker && (peerObj.moniker.startsWith('http://') || peerObj.moniker.startsWith('https://')) && peerObj.ip && (
                                                                        <PeerIp> ({peerObj.ip})</PeerIp>
                                                                    )}
                                                                </PeerItem>
                                                            );
                                                        });
                                                    })()}
                                                </PeerList>
                                            )}
                                        </ValueBox>
                                    </SectionRow>
                                    <SectionRow>
                                        <SectionLabel>Top Holders:</SectionLabel>
                                        <ValueBox>
                                            {circulationStats.top_accounts.length === 0 ? (
                                                <Mono>(loading...)</Mono>
                                            ) : (
                                                <AccountList>
                                                    {circulationStats.top_accounts.map((account, idx) => (
                                                        <AccountItem key={account.address}>
                                                            <AccountRank>#{idx + 1}</AccountRank>
                                                            <AccountName
                                                                href={`/profile?address=${account.address}`}
                                                                onClick={(e) => {
                                                                    e.preventDefault();
                                                                    navigate(`/profile?address=${account.address}`);
                                                                }}
                                                            >
                                                                {account.username || account.address.slice(0, 12) + '...'}
                                                            </AccountName>
                                                            <AccountBalance>
                                                                {formatMirage(account.balance)}
                                                            </AccountBalance>
                                                        </AccountItem>
                                                    ))}
                                                </AccountList>
                                            )}
                                        </ValueBox>
                                    </SectionRow>
                                </>
                            )}
                            {activeTab === 'server' && (
                                <>
                                    <RowCentered>
                                        <Label>Balance:</Label>
                                        <ValueBox>
                                            <Mono>{serverBalance === null ? '(loading...)' : `${formatMirage(serverBalance)} MIRAGE`}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Address:</Label>
                                        <ValueBoxWithButton>
                                            <InlineMono title={cfg.validator_account_address || ''}>{cfg.validator_account_address || '(loading...)'}</InlineMono>
                                            {cfg.validator_account_address && (
                                                <Button
                                                    onClick={() => {
                                                        navigator.clipboard.writeText(cfg.validator_account_address);
                                                        setCopiedAddress('mirage');
                                                        setTimeout(() => setCopiedAddress(null), 1500);
                                                    }}
                                                    size="sm"
                                                    minWidth="copy"
                                                    copied={copiedAddress === 'mirage'}
                                                >
                                                    {copiedAddress === 'mirage' ? 'Copied!' : 'Copy'}
                                                </Button>
                                            )}
                                        </ValueBoxWithButton>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Valoper:</Label>
                                        <ValueBoxWithButton>
                                            <InlineMono title={cfg.validator_operator_address || ''}>{cfg.validator_operator_address || '(loading...)'}</InlineMono>
                                            {cfg.validator_operator_address && (
                                                <Button
                                                    onClick={() => {
                                                        navigator.clipboard.writeText(cfg.validator_operator_address);
                                                        setCopiedAddress('valoper');
                                                        setTimeout(() => setCopiedAddress(null), 1500);
                                                    }}
                                                    size="sm"
                                                    minWidth="copy"
                                                    copied={copiedAddress === 'valoper'}
                                                >
                                                    {copiedAddress === 'valoper' ? 'Copied!' : 'Copy'}
                                                </Button>
                                            )}
                                        </ValueBoxWithButton>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Valcons:</Label>
                                        <ValueBoxWithButton>
                                            <InlineMono title={cfg.validator_consensus_address || ''}>{cfg.validator_consensus_address || '(loading...)'}</InlineMono>
                                            {cfg.validator_consensus_address && (
                                                <Button
                                                    onClick={() => {
                                                        navigator.clipboard.writeText(cfg.validator_consensus_address);
                                                        setCopiedAddress('valcons');
                                                        setTimeout(() => setCopiedAddress(null), 1500);
                                                    }}
                                                    size="sm"
                                                    minWidth="copy"
                                                    copied={copiedAddress === 'valcons'}
                                                >
                                                    {copiedAddress === 'valcons' ? 'Copied!' : 'Copy'}
                                                </Button>
                                            )}
                                        </ValueBoxWithButton>
                                    </RowCentered>
                                </>
                            )}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
