import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Helmet } from 'react-helmet-async';
import styled from 'styled-components';
import Storage from '../utils/Storage';
import Api from '../lib/api';
import { Link, useLocation } from 'react-router-dom';
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import Button from "../components/Button";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../styled/Layout";
import * as tx from '../utils/tx';
import { usePendingAgents } from '../utils/usePendingAgents';
import { formatError } from '../utils/errorMessages';

const SectionSubtitle = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.7rem;
    margin-bottom: 0.75rem;
    line-height: 1.4;
`;

const AgentsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
`;

const AgentCard = styled.div`
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border-radius: 8px;
    padding: 0.75rem 1rem;
    transition: background-color 0.2s ease, border-color 0.2s ease;

    &:hover {
        background-color: ${({ theme }) => theme?.colors?.accent || '#2E3238'};
        border-color: ${({ theme }) => theme?.colors?.subtleText || '#666'};
    }
`;

const AgentRow = styled.div`
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;

    @media (max-width: 600px) {
        flex-direction: column;
        align-items: stretch;
    }
`;

const AgentInfo = styled.div`
    min-width: 0;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
`;

const AgentActions = styled.div`
    flex-shrink: 0;
    display: flex;
    align-items: flex-start;

    @media (max-width: 600px) {
        width: 100%;
        button { width: 100%; }
    }
`;

const AgentNameRow = styled.div`
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    min-width: 0;
`;

const AgentName = styled(Link)`
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    text-decoration: none;
    font-weight: 600;
    font-size: 0.85rem;
    white-space: nowrap;
    &:hover { color: ${({ theme }) => theme?.colors?.link || '#667eea'}; }
`;

const AgentLastActive = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.65rem;
    white-space: nowrap;
`;

const AgentBio = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    font-size: 0.7rem;
    line-height: 1.4;
    word-break: break-word;
`;

const EmptyMessage = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.8rem;
    padding: 1rem 0;
`;

const ErrorMessage = styled.div`
    color: #f87171;
    font-size: 0.75rem;
    padding: 0.5rem 0.75rem;
    margin-bottom: 0.5rem;
    background: rgba(248, 113, 113, 0.1);
    border: 1px solid rgba(248, 113, 113, 0.25);
    border-radius: 6px;
`;

const OrderControls = styled.div`
    display: inline-flex;
    gap: 0.25rem;
    margin-right: 0.5rem;
`;

const MOBILE_ACTION_HEIGHT = '2.4rem';

const OrderButton = styled.button`
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 6px;
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    font-size: 0.7rem;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme?.colors?.panelAlt || '#33373C'};
        color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
        border-color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    }

    &:disabled {
        opacity: 0.35;
        cursor: not-allowed;
    }

    @media (max-width: 600px) {
        min-width: ${MOBILE_ACTION_HEIGHT};
        height: ${MOBILE_ACTION_HEIGHT};
        font-size: 0.9rem;
    }
`;

const AgentActionButton = styled(Button)`
    @media (max-width: 600px) {
        min-height: ${MOBILE_ACTION_HEIGHT};
        height: ${MOBILE_ACTION_HEIGHT};
    }
`;

const Divider = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.25rem 0;
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};

    &::before, &::after {
        content: '';
        flex: 1;
        height: 1px;
        background: ${({ theme }) => theme?.colors?.border || '#333'};
    }
`;

const ActionRow = styled.div`
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    margin-top: 0.75rem;
`;

function formatTimeAgo(unixSeconds) {
    if (!unixSeconds) return null;
    const diff = Math.floor(Date.now() / 1000) - unixSeconds;
    if (diff < 0) return 'just now';
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 2592000) return `${Math.floor(diff / 86400)}d ago`;
    if (diff < 31536000) return `${Math.floor(diff / 2592000)}mo ago`;
    return `${Math.floor(diff / 31536000)}y ago`;
}

export default function AgentsView({ state }) {
    const viewerAddress = Storage.load('publicKey', '') || '';
    const [agents, setAgents] = useState([]);
    const [enabledOrder, setEnabledOrder] = useState([]);
    const [draftOrder, setDraftOrder] = useState([]);
    const [draftDirty, setDraftDirty] = useState(false);
    const [loadingAgents, setLoadingAgents] = useState(true);
    const [loadingEnabled, setLoadingEnabled] = useState(true);
    const [errorMessage, setErrorMessage] = useState('');
    const [maxEnabledAgents, setMaxEnabledAgents] = useState(null);
    const [isApplyingOrder, setIsApplyingOrder] = useState(false);
    const [hoverAgent, setHoverAgent] = useState(null);
    const { isPending, formatStatus, pendingAgents } = usePendingAgents();
    const mountedRef = useRef(true);
    const location = useLocation();

    const enabledSet = React.useMemo(() => new Set(enabledOrder), [enabledOrder]);

    const readMaxEnabledAgents = useCallback(() => {
        try {
            const raw = localStorage.getItem('chainConfig');
            if (!raw) return null;
            const cfg = JSON.parse(raw);
            if (!Array.isArray(cfg?.tiers)) return null;
            const levelRaw = Number(Storage.load('user_level', '0')) || 0;
            let tierIdx = -1;
            if (levelRaw === 0) tierIdx = 0;
            else if (levelRaw === 1) tierIdx = 1;
            else if (levelRaw === 10 || levelRaw >= 100) tierIdx = 2;
            if (tierIdx < 0 || tierIdx >= cfg.tiers.length) return null;
            const max = Number(cfg.tiers[tierIdx]?.max_enabled_agents ?? 0);
            return Number.isFinite(max) ? max : null;
        } catch (_) {
            return null;
        }
    }, []);

    useEffect(() => {
        mountedRef.current = true;
        return () => { mountedRef.current = false; };
    }, []);

    const normalizeOrder = useCallback((order) => {
        const seen = new Set();
        return (order || [])
            .map(a => String(a || '').toLowerCase())
            .filter(a => {
                if (!a || seen.has(a)) return false;
                seen.add(a);
                return true;
            });
    }, []);

    useEffect(() => {
        let alive = true;
        setLoadingAgents(true);
        setLoadingEnabled(true);
        setErrorMessage('');

        const load = async () => {
            const tasks = [
                Api.get('get_agents', {}, { timeoutMs: 10000 }),
                viewerAddress
                    ? Api.get('get_user_followed', { address: viewerAddress }, { timeoutMs: 10000 })
                    : Promise.resolve(null),
            ];
            const [agentsRes, followedRes] = await Promise.allSettled(tasks);

            if (!alive || !mountedRef.current) return;

            if (agentsRes.status === 'fulfilled') {
                const raw = Array.isArray(agentsRes.value?.agents) ? agentsRes.value.agents : [];
                const viewerLower = String(viewerAddress || '').toLowerCase();
                const agentsList = viewerLower
                    ? raw.filter(a => (a.address || '').toLowerCase() !== viewerLower)
                    : raw;
                if (viewerLower) {
                    console.debug('[AgentsView] loaded', agentsList.length, 'agents (excluded self)');
                } else {
                    console.debug('[AgentsView] loaded', agentsList.length, 'agents');
                }
                setAgents(agentsList);
            } else {
                console.error('[AgentsView] failed to load agents:', agentsRes.reason);
                setAgents([]);
                setErrorMessage('Failed to load agents.');
            }
            setLoadingAgents(false);

            if (followedRes.status === 'fulfilled') {
                const enabled = normalizeOrder(followedRes.value?.enabled_agents || []);
                setEnabledOrder(enabled);
                setDraftOrder(enabled);
                console.debug('[AgentsView] user has', enabled.length, 'enabled agents');
            } else if (viewerAddress) {
                console.error('[AgentsView] failed to load enabled agents:', followedRes.reason);
                setEnabledOrder([]);
                setDraftOrder([]);
                setErrorMessage('Failed to load enabled agents.');
            }
            setLoadingEnabled(false);
        };

        load().catch((err) => {
            console.error('[AgentsView] load error:', err);
            if (!alive || !mountedRef.current) return;
            setLoadingAgents(false);
            setLoadingEnabled(false);
            setErrorMessage('Failed to load agents.');
        });
        return () => { alive = false; };
    }, [viewerAddress, normalizeOrder]);

    useEffect(() => {
        if (draftDirty) return;
        setDraftOrder(enabledOrder);
    }, [enabledOrder, draftDirty]);

    useEffect(() => {
        let mounted = true;

        const refreshChainConfig = async () => {
            try {
                if (tx.needsChainConfigRefresh()) {
                    const cfg = await Api.get('get_chain_config', undefined);
                    if (cfg && typeof cfg === 'object') {
                        await tx.cacheChainConfig(cfg);
                    }
                }
            } catch (err) {
                console.error('[AgentsView] chain config fetch failed:', err);
            } finally {
                if (mounted) setMaxEnabledAgents(readMaxEnabledAgents());
            }
        };

        const handleConfigUpdate = () => {
            if (!mounted) return;
            setMaxEnabledAgents(readMaxEnabledAgents());
        };

        refreshChainConfig();
        handleConfigUpdate();
        window.addEventListener('chainConfigUpdated', handleConfigUpdate);
        return () => {
            mounted = false;
            window.removeEventListener('chainConfigUpdated', handleConfigUpdate);
        };
    }, [readMaxEnabledAgents]);

    const isEnabled = useCallback((address) => {
        return enabledSet.has(String(address || '').toLowerCase());
    }, [enabledSet]);

    const handleToggle = useCallback(async (agentAddress) => {
        const addr = String(agentAddress || '').toLowerCase();
        if (!addr || isPending(addr)) return;
        setErrorMessage('');

        if (!viewerAddress) return;
        if (maxEnabledAgents === null) {
            setErrorMessage('Unable to determine agent limit. Please refresh.');
            return;
        }

        const baseOrder = draftDirty ? draftOrder : enabledOrder;
        const normalizedBase = normalizeOrder(baseOrder);
        const wasEnabled = normalizedBase.includes(addr);
        let newList;
        if (wasEnabled) {
            newList = normalizedBase.filter(a => a !== addr);
        } else {
            if (normalizedBase.length >= maxEnabledAgents) {
                setErrorMessage(`Enabled agents limit reached (${maxEnabledAgents}). Disable one first.`);
                return;
            }
            newList = [...normalizedBase, addr];
        }

        try {
            const result = await tx.setAgents(newList, { triggerAgent: addr });
            if (result?.success && mountedRef.current) {
                setEnabledOrder(newList);
                setDraftOrder(newList);
                setDraftDirty(false);
            } else {
                const errText = formatError(result);
                const lower = errText.toLowerCase();
                if (lower.includes('limit') || lower.includes('too many agents')) {
                    setErrorMessage(`Enabled agents limit reached (${maxEnabledAgents}). Disable one first.`);
                } else {
                    setErrorMessage(errText);
                }
            }
        } catch (err) {
            setErrorMessage(String(err?.message || err || 'Agent update failed.'));
        }
    }, [isPending, viewerAddress, maxEnabledAgents, enabledOrder, draftOrder, draftDirty, normalizeOrder, setEnabledOrder, setDraftOrder]);

    const ordersEqual = useCallback((a, b) => {
        if (a.length !== b.length) return false;
        for (let i = 0; i < a.length; i += 1) {
            if (a[i] !== b[i]) return false;
        }
        return true;
    }, []);

    const hasDraftChanges = draftDirty && !ordersEqual(draftOrder, enabledOrder);

    const moveAgent = useCallback((agentAddress, direction) => {
        const addr = String(agentAddress || '').toLowerCase();
        if (!addr || isApplyingOrder) return;
        const list = (draftOrder.length ? [...draftOrder] : [...enabledOrder]);
        const idx = list.indexOf(addr);
        if (idx < 0) return;
        const nextIdx = idx + direction;
        if (nextIdx < 0 || nextIdx >= list.length) return;
        const temp = list[idx];
        list[idx] = list[nextIdx];
        list[nextIdx] = temp;
        setDraftOrder(list);
        setDraftDirty(true);
    }, [draftOrder, enabledOrder, isApplyingOrder]);

    const refreshEnabledOrder = useCallback(async () => {
        if (!viewerAddress) return;
        try {
            const data = await Api.get('get_user_followed', { address: viewerAddress }, { timeoutMs: 10000 });
            const enabled = normalizeOrder(data?.enabled_agents || []);
            setEnabledOrder(enabled);
            if (!draftDirty) setDraftOrder(enabled);
            console.debug('[AgentsView] refreshed enabled order', enabled);
        } catch (err) {
            console.error('[AgentsView] refresh enabled order failed:', err);
        }
    }, [viewerAddress, draftDirty, normalizeOrder]);

    const applyOrder = useCallback(async () => {
        if (!viewerAddress || isApplyingOrder || !hasDraftChanges) return;
        if (Object.keys(pendingAgents || {}).length > 0) {
            setErrorMessage('Wait for pending agent transactions to finish.');
            return;
        }
        setErrorMessage('');
        setIsApplyingOrder(true);
        console.debug('[AgentsView] apply order', { from: enabledOrder, to: draftOrder });

        const desired = normalizeOrder(draftOrder);
        try {
            const result = await tx.setAgents(desired);
            if (result?.success && mountedRef.current) {
                setDraftDirty(false);
                setEnabledOrder(desired);
                setDraftOrder(desired);
            } else {
                setErrorMessage(formatError(result));
            }
        } catch (err) {
            setErrorMessage(String(err?.message || err || 'Reorder failed.'));
        }
        setIsApplyingOrder(false);
        await refreshEnabledOrder();
    }, [viewerAddress, isApplyingOrder, hasDraftChanges, pendingAgents, draftOrder, refreshEnabledOrder, normalizeOrder, enabledOrder]);

    const displayOrder = draftOrder.length ? draftOrder : enabledOrder;

    const { sortedAgents, enabledCount } = React.useMemo(() => {
        const byAddr = new Map();
        for (const agent of agents) {
            const key = String(agent.address || '').toLowerCase();
            if (!key) continue;
            byAddr.set(key, { ...agent, addressLower: key });
        }

        const enabled = [];
        const enabledSetLocal = new Set(displayOrder);
        for (const addr of displayOrder) {
            const entry = byAddr.get(addr);
            if (entry) enabled.push(entry);
        }

        const rest = agents
            .map(agent => ({ ...agent, addressLower: String(agent.address || '').toLowerCase() }))
            .filter(agent => agent.addressLower && !enabledSetLocal.has(agent.addressLower))
            .sort((a, b) => (b.last_active || 0) - (a.last_active || 0));

        return { sortedAgents: [...enabled, ...rest], enabledCount: enabled.length };
    }, [agents, displayOrder]);

    return (
        <ContentGrid>
            <Helmet>
                <title>Agents | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <ContainerTab>Agents</ContainerTab>
                        <ContainerBody>
                            <SectionSubtitle>
                                <strong>Mirage has no built-in moderation</strong> — all content lives on-chain unaltered.
                            </SectionSubtitle>
                            <SectionSubtitle>
                                <strong>Anyone</strong> can create an agent that filters spam, fixes tags, translates posts, or curates however they see fit. You choose which ones to trust, and your feed reflects their work while the originals stay untouched.
                            </SectionSubtitle>
                            <SectionSubtitle>
                                The result is an <em>open marketplace of moderation</em> where quality rises through competition, not central authority.
                            </SectionSubtitle>
                            {errorMessage && <ErrorMessage>{errorMessage}</ErrorMessage>}
                            {(loadingAgents || loadingEnabled) ? (
                                <EmptyMessage>Loading agents...</EmptyMessage>
                            ) : sortedAgents.length === 0 ? (
                                <EmptyMessage>No agents available yet.</EmptyMessage>
                            ) : (
                                <AgentsList>
                                    {sortedAgents.map((agent, idx) => {
                                        const addrLower = (agent.address || '').toLowerCase();
                                        const enabled = isEnabled(agent.address);
                                        const pending = isPending(addrLower);
                                        const displayName = agent.username || (agent.address ? `${agent.address.slice(0, 12)}...` : 'Unknown');
                                        const orderIdx = displayOrder.indexOf(addrLower);
                                        const canMoveUp = enabled && orderIdx > 0;
                                        const canMoveDown = enabled && orderIdx >= 0 && orderIdx < (displayOrder.length - 1);
                                        const showEnabledLabel = idx === 0 && enabledCount > 0;
                                        const showAvailableLabel = idx === enabledCount && enabledCount > 0;
                                        return (
                                            <React.Fragment key={agent.address}>
                                                {showEnabledLabel && <>
                                                    <Divider>enabled agents</Divider>
                                                    <SectionSubtitle style={{ marginBottom: '0.25rem' }}>
                                                        Order matters. When two agents edit the same field, the one higher in your list wins.
                                                    </SectionSubtitle>
                                                </>}
                                                {showAvailableLabel && <>
                                                    {hasDraftChanges && (
                                                        <ActionRow>
                                                            <Button
                                                                variant="primary"
                                                                size="sm"
                                                                disabled={isApplyingOrder || !viewerAddress}
                                                                loading={isApplyingOrder}
                                                                onClick={applyOrder}
                                                            >
                                                                Apply order
                                                            </Button>
                                                        </ActionRow>
                                                    )}
                                                    <Divider>available agents</Divider>
                                                </>}
                                                <AgentCard>
                                                    <AgentRow>
                                                        <AgentInfo>
                                                            <AgentNameRow>
                                                                <AgentName to={`/u/${encodeURIComponent(agent.username || agent.address)}?tab=posts`}>
                                                                    @{displayName}
                                                                </AgentName>
                                                                <AgentLastActive>
                                                                    {agent.last_active
                                                                        ? `(active ${formatTimeAgo(agent.last_active)})`
                                                                        : '(no activity yet)'}
                                                                </AgentLastActive>
                                                            </AgentNameRow>
                                                            {agent.biography && (
                                                                <AgentBio>{agent.biography}</AgentBio>
                                                            )}
                                                        </AgentInfo>
                                                        <AgentActions>
                                                            {enabled && (
                                                                <OrderControls>
                                                                    <OrderButton
                                                                        type="button"
                                                                        onClick={() => moveAgent(addrLower, -1)}
                                                                        disabled={!canMoveUp || pending || isApplyingOrder}
                                                                        aria-label="Move agent up"
                                                                    >
                                                                        ↑
                                                                    </OrderButton>
                                                                    <OrderButton
                                                                        type="button"
                                                                        onClick={() => moveAgent(addrLower, 1)}
                                                                        disabled={!canMoveDown || pending || isApplyingOrder}
                                                                        aria-label="Move agent down"
                                                                    >
                                                                        ↓
                                                                    </OrderButton>
                                                                </OrderControls>
                                                            )}
                                                            <AgentActionButton
                                                                variant={
                                                                    enabled && hoverAgent === addrLower
                                                                        ? 'primaryDanger'
                                                                        : enabled
                                                                            ? 'subtle'
                                                                            : 'primary'
                                                                }
                                                                size="sm"
                                                                minWidth="8.0rem"
                                                                disabled={pending || !viewerAddress || loadingEnabled}
                                                                loading={pending}
                                                                onMouseEnter={() => setHoverAgent(addrLower)}
                                                                onMouseLeave={() => setHoverAgent(null)}
                                                                onClick={() => handleToggle(agent.address)}
                                                            >
                                                                {pending
                                                                    ? formatStatus(addrLower)
                                                                    : enabled
                                                                        ? (hoverAgent === addrLower ? 'Disable' : 'Enabled')
                                                                        : 'Enable'}
                                                            </AgentActionButton>
                                                        </AgentActions>
                                                    </AgentRow>
                                                </AgentCard>
                                            </React.Fragment>
                                        );
                                    })}
                                </AgentsList>
                            )}
                            {hasDraftChanges && enabledCount === sortedAgents.length && (
                                <ActionRow>
                                    <Button
                                        variant="primary"
                                        size="sm"
                                        disabled={isApplyingOrder || !viewerAddress}
                                        loading={isApplyingOrder}
                                        onClick={applyOrder}
                                    >
                                        Apply order
                                    </Button>
                                </ActionRow>
                            )}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
