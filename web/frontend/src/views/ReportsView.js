import React from 'react';
import { Helmet } from 'react-helmet-async';
import styled from 'styled-components';
import { Link, useLocation } from 'react-router-dom';
import Storage from '../utils/Storage';
import Api from '../lib/api';
import * as tx from '../utils/tx';
import Button from '../components/Button';
import Sidebar from '../components/Sidebar';
import TopBar from '../components/TopBar';
import MobileHeader from '../components/MobileHeader';
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from '../styled/Layout';

const Table = styled.table`
    width: 100%;
    border-collapse: collapse;
    border-spacing: 0;
    font-size: 0.5rem;
`;

const TableBody = styled.tbody``;

const TableRow = styled.tr``;

const TableCell = styled.td`
    padding: 0.15rem 0.5rem 0.15rem 0;
    vertical-align: top;
    border: none;
    
    &:first-child {
        padding-left: 0;
        padding-right: 0.5rem;
        font-weight: 600;
        white-space: nowrap;
        width: 1%;
    }
    
    &:last-child {
        padding-right: 0;
        word-break: break-word;
        overflow-wrap: anywhere;
    }
`;

const RowContainer = styled.div`
    padding: 0.5rem;
    margin-bottom: 0.5rem;
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border-radius: 6px;
    font-size: 0.5rem;
    @media (max-width: 1000px) {
        padding: 0.35rem;
        margin-bottom: 0.35rem;
        border-radius: 4px;
    }
`;

const Actions = styled.div`
    margin-top: 0.35rem;
    display: flex;
    gap: 0.35rem;
    flex-wrap: wrap;
    @media (max-width: 1000px) {
        flex-direction: column;
        gap: 0.25rem;
        margin-top: 0.25rem;
    }
`;


const ContentPreview = styled.div`
    margin-top: 0.25rem;
    padding: 0.25rem;
    background: ${({ theme }) => theme?.colors?.panelAlt || '#2A2E33'};
    border-radius: 4px;
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 0.75rem;
    line-height: 1.3;
    border-left: 2px solid ${({ theme }) => theme?.colors?.border || '#444'};
    @media (max-width: 1000px) {
        font-size: 0.7rem;
        line-height: 1.25;
        padding: 0.2rem;
        margin-top: 0.2rem;
    }
`;

const TitlePreview = styled(ContentPreview)`
    margin-top: 0.2rem;
    @media (max-width: 1000px) {
        margin-top: 0.15rem;
    }
`;

const StyledLink = styled(Link)`
    color: ${({ theme }) => theme?.colors?.link || '#FFFFFF'};
    text-decoration: none;
    font-weight: 500;
    font-size: 0.5rem;
    display: inline-block;
    max-width: 100%;
    overflow-wrap: anywhere;
    word-break: break-all; /* wrap long hashes/urls */

    &:hover {
        color: ${({ theme }) => theme?.colors?.linkHover || '#CCCCCC'};
        text-decoration: underline;
    }
`;

const Username = styled.span`
    font-size: 0.5rem;
`;

export default function ReportsView({ state }) {
    const location = useLocation();
    const [reports, setReports] = React.useState([]);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState('');
    const publicKey = Storage.load('publicKey', '');
    const userLevel = Number(Storage.load('user_level', '0'));

    const notifyCount = React.useCallback((count) => {
        try {
            const evt = new CustomEvent('reportsUpdated', { detail: { count } });
            window.dispatchEvent(evt);
        } catch (_) { /* noop */ }
    }, []);

    const fetchReports = React.useCallback(async () => {
        if (!publicKey || userLevel < 100) {
            setLoading(false);
            setReports([]);
            notifyCount(0);
            return;
        }
        try {
            setLoading(true);
            const res = await Api.get('get_reports', { address: publicKey, limit: 200 });
            const list = (res && Array.isArray(res.reports)) ? res.reports : [];
            setReports(list);
            setError('');
            notifyCount(list.length);
        } catch (e) {
            setError(String(e && e.message ? e.message : 'Failed to load reports'));
        } finally {
            setLoading(false);
        }
    }, [publicKey, userLevel, notifyCount]);

    React.useEffect(() => { fetchReports(); }, [fetchReports]);

    const resolveReport = async (id) => {
        try {
            await Api.post('core/resolve_report', { address: publicKey, id: id >>> 0 });
            setReports((prev) => prev.filter((r) => (r && Number(r.id) !== Number(id))));
        } catch (e) {
            setError(String(e && e.message ? e.message : 'Failed to resolve report'));
        }
    };

    const [processing, setProcessing] = React.useState(new Set());

    const onDelete = async (r) => {
        setProcessing(prev => new Set(prev).add(r.id));
        try {
            await tx.deletePost(r.target);
            setReports((prev) => {
                const next = prev.filter((report) => report.target !== r.target);
                notifyCount(next.length);
                return next;
            });
        } finally {
            setProcessing(prev => {
                const next = new Set(prev);
                next.delete(r.id);
                return next;
            });
        }
    };

    const onDeleteAndBlock = async (r) => {
        setProcessing(prev => new Set(prev).add(r.id));
        try {
            await tx.deletePost(r.target);
            if (r.post_owner) {
                await tx.blockUser(r.post_owner, true);
            }
            setReports((prev) => {
                const next = prev.filter((report) => report.target !== r.target);
                notifyCount(next.length);
                return next;
            });
        } finally {
            setProcessing(prev => {
                const next = new Set(prev);
                next.delete(r.id);
                return next;
            });
        }
    };

    const onIgnore = async (r) => {
        setProcessing(prev => new Set(prev).add(r.id));
        try {
            await resolveReport(r.id);
        } finally {
            setProcessing(prev => {
                const next = new Set(prev);
                next.delete(r.id);
                return next;
            });
            setReports((prev) => {
                const next = prev.filter((x) => x.id !== r.id);
                notifyCount(next.length);
                return next;
            });
        }
    };

    if (userLevel < 100) return (
        <ContentGrid>
            <Helmet><title>Reports | Mirage</title></Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerTab>Reports</ContainerTab>
                        <ContainerBody><div>Forbidden</div></ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
    if (loading) return (
        <ContentGrid>
            <Helmet><title>Reports | Mirage</title></Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerTab>Reports</ContainerTab>
                        <ContainerBody><div>Loading...</div></ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
    if (error) return (
        <ContentGrid>
            <Helmet><title>Reports | Mirage</title></Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerTab>Reports</ContainerTab>
                        <ContainerBody><div style={{ color: '#f66' }}>{error}</div></ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );

    const shorten = (addr) => {
        if (!addr) return '';
        return `${addr.slice(0, 10)}…${addr.slice(-4)}`;
    };

    const fmtTime = (ts) => {
        try { return new Date((Number(ts) || 0) * 1000).toLocaleString(); } catch (_) { return String(ts); }
    };

    const stripImages = (content) => {
        if (!content || typeof content !== 'string') return '';
        return content.replace(/!\[.*?\]\((.*?)\)/g, '$1');
    };

    return (
        <ContentGrid>
            <Helmet><title>Reports | Mirage</title></Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerTab>Reports ({reports.length})</ContainerTab>
                        <ContainerBody>
                            {reports.length === 0 && <div>No active reports.</div>}
                            {reports.map((r) => {
                                const isProcessing = processing.has(r.id);
                                return (
                                    <RowContainer key={r.id}>
                                        <Table>
                                            <TableBody>
                                                <TableRow>
                                                    <TableCell>Report time:</TableCell>
                                                    <TableCell>{fmtTime(r.timestamp)}</TableCell>
                                                </TableRow>
                                                <TableRow>
                                                    <TableCell>Reporter:</TableCell>
                                                    <TableCell>
                                                        <Username title={r.reporter_owner}>
                                                            {r.reporter_username || shorten(r.reporter_owner)}
                                                        </Username>
                                                    </TableCell>
                                                </TableRow>
                                                <TableRow>
                                                    <TableCell>Reason:</TableCell>
                                                    <TableCell>{r.reason}</TableCell>
                                                </TableRow>
                                                <TableRow>
                                                    <TableCell>Target post:</TableCell>
                                                    <TableCell>
                                                        <StyledLink to={`/p/${encodeURIComponent(String(r.target || ''))}`}>
                                                            {String(r.target || '')}
                                                        </StyledLink>
                                                    </TableCell>
                                                </TableRow>
                                                {r.post_owner && (
                                                    <TableRow>
                                                        <TableCell>Post owner:</TableCell>
                                                        <TableCell>
                                                            <Username title={r.post_owner}>
                                                                {r.post_username || shorten(r.post_owner)}
                                                            </Username>
                                                        </TableCell>
                                                    </TableRow>
                                                )}
                                            </TableBody>
                                        </Table>
                                        {r.title && (
                                            <TitlePreview>
                                                {r.title}
                                            </TitlePreview>
                                        )}
                                        {typeof r.content === 'string' && r.content.length > 0 && (
                                            <ContentPreview>
                                                {stripImages(r.content)}
                                            </ContentPreview>
                                        )}
                                        <Actions>
                                            <Button variant="danger" size="sm" onClick={() => onDelete(r)} disabled={isProcessing} mobileFullWidth>
                                                {isProcessing ? 'Processing…' : 'Delete Post'}
                                            </Button>
                                            <Button variant="danger" size="sm" onClick={() => onDeleteAndBlock(r)} disabled={isProcessing} mobileFullWidth>
                                                {isProcessing ? 'Processing…' : 'Delete + Block User'}
                                            </Button>
                                            <Button variant="success" size="sm" onClick={() => onIgnore(r)} disabled={isProcessing} mobileFullWidth>
                                                {isProcessing ? 'Processing…' : 'Ignore'}
                                            </Button>
                                        </Actions>
                                    </RowContainer>
                                );
                            })}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}


