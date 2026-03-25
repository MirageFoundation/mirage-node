import React, { useEffect, useState, useCallback } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import { useLocation, Link } from 'react-router-dom';
import Storage from "../utils/Storage";
import Api from '../lib/api';
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, TabsRow, ClickableTab } from "../styled/Layout";

const ShareBox = styled.div`
    background: ${({ theme }) => theme?.colors?.panelAlt || '#2A2E33'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 1rem 1.25rem;
    margin-bottom: 1rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
`;

const ShareUrl = styled.input`
    flex: 1;
    min-width: 200px;
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    color: ${({ theme }) => theme?.colors?.text || '#e5e7eb'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 4px;
    padding: 0.4rem 0.6rem;
    font-size: 0.75rem;
    font-family: monospace;
`;

const CopyBtn = styled.button`
    background: ${({ $copied, theme }) => $copied ? '#4caf50' : (theme?.colors?.accent || '#5865f2')};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 0.4rem 0.8rem;
    font-size: 0.75rem;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.2s;
    &:hover { opacity: 0.9; }
`;

const Table = styled.table`
    width: 100%;
    border-collapse: collapse;
    font-size: 0.75rem;
`;

const Th = styled.th`
    text-align: left;
    padding: 0.5rem 0.4rem;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    color: ${({ theme }) => theme?.colors?.subtleText || '#999'};
    font-weight: 600;
    white-space: nowrap;
`;

const Td = styled.td`
    padding: 0.4rem;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    color: ${({ theme }) => theme?.colors?.text || '#e5e7eb'};
    vertical-align: middle;
`;

const Badge = styled.span`
    display: inline-block;
    padding: 0.15rem 0.4rem;
    border-radius: 3px;
    font-size: 0.65rem;
    font-weight: 600;
    background: ${({ $real }) => $real ? '#2e7d3233' : '#78909c22'};
    color: ${({ $real }) => $real ? '#66bb6a' : '#90a4ae'};
`;

const EmptyState = styled.div`
    text-align: center;
    padding: 2rem 1rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#999'};
    font-size: 0.8rem;
`;

const SummaryRow = styled.div`
    display: flex;
    gap: 1.5rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
`;

const SummaryCard = styled.div`
    background: ${({ theme }) => theme?.colors?.panelAlt || '#2A2E33'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.75rem 1rem;
    min-width: 100px;
    text-align: center;
`;

const SummaryValue = styled.div`
    font-size: 1.25rem;
    font-weight: 700;
    color: ${({ theme }) => theme?.colors?.text || '#e5e7eb'};
`;

const SummaryLabel = styled.div`
    font-size: 0.65rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#999'};
    margin-top: 0.15rem;
`;

const PERIODS = [
    { key: "7d", label: "Last 7 Days" },
    { key: "30d", label: "Last 30 Days" },
    { key: "month", label: "This Month" },
    { key: "prev_month", label: "Last Month" },
];
const PAGE_SIZE = 50;

function getMonthStr(offset = 0) {
    const d = new Date();
    d.setDate(1);
    d.setMonth(d.getMonth() + offset);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function ReferralsView({ state }) {
    const location = useLocation();
    const publicKey = (state && state.publicKey) ? state.publicKey : Storage.load("publicKey", "");
    const username = (state && state.username) ? state.username : Storage.load("username", "");
    const precheckEnabled = Storage.load('referral_precheck_enabled', false) === true;
    const [period, setPeriod] = useState("7d");
    const [data, setData] = useState(null);
    const [referrals, setReferrals] = useState([]);
    const [offset, setOffset] = useState(0);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState("");
    const [copied, setCopied] = useState(false);
    const [inviteCodes, setInviteCodes] = useState([]);

    useEffect(() => {
        if (!publicKey) return;
        let cancelled = false;
        Api.get('get_invite_codes', { address: publicKey })
            .then((resp) => {
                if (cancelled) return;
                if (resp && Array.isArray(resp.codes)) setInviteCodes(resp.codes);
            })
            .catch(() => { });
        return () => { cancelled = true; };
    }, [publicKey]);

    const nextAvailableCode = inviteCodes.find(c => !c.is_used);

    const getShareUrl = () => {
        if (!username) return '';
        const origin = typeof window !== 'undefined' ? window.location.origin : '';
        if (precheckEnabled) {
            return `${origin}/signup?ref=${encodeURIComponent(username)}`;
        }
        if (nextAvailableCode) {
            return `${origin}/signup?invite=${nextAvailableCode.code}`;
        }
        return '';
    };

    const shareUrl = getShareUrl();

    const fetchSummary = useCallback(async ({ append = false, offset: offsetParam } = {}) => {
        if (!publicKey) {
            setLoading(false);
            setLoadingMore(false);
            setData(null);
            setReferrals([]);
            setHasMore(false);
            setOffset(0);
            return;
        }
        const baseOffset = Number.isFinite(offsetParam) ? offsetParam : 0;
        if (append) {
            setLoadingMore(true);
        } else {
            setLoading(true);
        }
        setError("");
        try {
            const params = { address: publicKey, limit: PAGE_SIZE, offset: baseOffset };
            if (period === "month") {
                params.period = "month";
                params.month = getMonthStr(0);
            } else if (period === "prev_month") {
                params.period = "month";
                params.month = getMonthStr(-1);
            } else {
                params.period = period;
            }
            const resp = await Api.get('referrals/summary', params);
            const incoming = Array.isArray(resp?.referrals) ? resp.referrals : [];
            setData(resp);
            setReferrals(prev => append ? [...prev, ...incoming] : incoming);
            setHasMore(!!resp?.has_more);
            setOffset(baseOffset + incoming.length);
        } catch (_) {
            if (!append) {
                setReferrals([]);
                setData(null);
            }
            setHasMore(false);
            setError(append ? "Failed to load more." : "Could not load referral data.");
        } finally {
            setLoading(false);
            setLoadingMore(false);
        }
    }, [publicKey, period]);

    useEffect(() => {
        fetchSummary({ append: false, offset: 0 });
    }, [fetchSummary]);

    const handleLoadMore = () => {
        if (loadingMore || !hasMore) return;
        fetchSummary({ append: true, offset });
    };

    const handleCopy = () => {
        try {
            navigator.clipboard.writeText(shareUrl);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch (_) { }
    };


    return (
        <ContentGrid>
            <Helmet><title>Referrals | Mirage</title></Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow>
                            {PERIODS.map(p => (
                                <ClickableTab key={p.key} $active={period === p.key} onClick={() => setPeriod(p.key)}>
                                    {p.label}
                                </ClickableTab>
                            ))}
                        </TabsRow>
                        <ContainerBody>
                            {username && shareUrl && (
                                <ShareBox>
                                    <ShareUrl value={shareUrl} readOnly onClick={e => e.target.select()} />
                                    <CopyBtn $copied={copied} onClick={handleCopy}>
                                        {copied ? "Copied!" : "Copy Link"}
                                    </CopyBtn>
                                </ShareBox>
                            )}

                            {!publicKey ? (
                                <EmptyState>Sign in to view your referrals.</EmptyState>
                            ) : loading ? (
                                <EmptyState>Loading...</EmptyState>
                            ) : error ? (
                                <EmptyState>{error}</EmptyState>
                            ) : referrals.length === 0 ? (
                                <EmptyState>No referrals yet. Share your link above to get started.</EmptyState>
                            ) : (
                                <>
                                    <SummaryRow>
                                        <SummaryCard>
                                            <SummaryValue>{data?.total ?? referrals.length}</SummaryValue>
                                            <SummaryLabel>Total Referred</SummaryLabel>
                                        </SummaryCard>
                                    </SummaryRow>
                                    <Table>
                                        <thead>
                                            <tr>
                                                <Th>User</Th>
                                                <Th>Posts</Th>
                                                <Th>Votes</Th>
                                                <Th>Total</Th>
                                                <Th>Status</Th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {referrals.map((r) => {
                                                const isActive = (r?.total_actions || 0) >= 10;
                                                return (
                                                    <tr key={r.address}>
                                                        <Td>
                                                            {r.username ? (
                                                                <Link to={`/u/${r.username}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                                                                    @{r.username}
                                                                </Link>
                                                            ) : (
                                                                <span style={{ opacity: 0.5, fontSize: '0.65rem' }}>{r.address.slice(0, 12)}...</span>
                                                            )}
                                                        </Td>
                                                        <Td>{r.posts}</Td>
                                                        <Td>{r.votes}</Td>
                                                        <Td>{r.total_actions}</Td>
                                                        <Td>
                                                            <Badge $real={isActive}>
                                                                {isActive ? "Active" : "Inactive"}
                                                            </Badge>
                                                        </Td>
                                                    </tr>
                                                );
                                            })}
                                        </tbody>
                                    </Table>
                                    {hasMore && (
                                        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '0.75rem' }}>
                                            <CopyBtn onClick={handleLoadMore} $copied={loadingMore}>
                                                {loadingMore ? "Loading..." : "Load more"}
                                            </CopyBtn>
                                        </div>
                                    )}
                                </>
                            )}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}

export default ReferralsView;
