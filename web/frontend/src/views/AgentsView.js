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

const Section = styled.div`
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 6px;
    margin: 0.5rem 0;
    padding: 0.5rem 0.6rem;
    background: ${({ theme }) => theme?.colors?.panelAlt || '#33373C'};
`;

const SectionTitle = styled.div`
    font-weight: bold;
    font-size: 0.8rem;
    margin-bottom: 0.15rem;
`;

const SectionSubtitle = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#999'};
    font-size: 0.6rem;
    margin-bottom: 0.4rem;
    line-height: 1.4;
`;

const ItemRow = styled.div`
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: 0.6rem 0;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    &:last-child { border-bottom: none; }
    font-size: 0.7rem;
    gap: 0.6rem;

    @media (max-width: 700px) {
        flex-direction: column;
        align-items: flex-start;
    }
`;

const ItemLeft = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
    flex: 1;
`;

const ItemRight = styled.div`
    display: flex;
    margin-left: auto;
    flex-shrink: 0;

    @media (max-width: 700px) {
        width: 100%;

        button {
            width: 100%;
        }
    }
`;

const AgentName = styled(Link)`
    color: ${({ theme }) => theme?.colors?.link || '#FFFFFF'};
    text-decoration: none;
    font-weight: bold;
    font-size: 0.75rem;
    &:hover { color: ${({ theme }) => theme?.colors?.linkHover || '#CCCCCC'}; }
`;

const AgentBio = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    font-size: 0.65rem;
    line-height: 1.4;
    word-break: break-word;
    max-width: 500px;
`;

const EmptyMessage = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    font-size: 0.7rem;
    padding: 0.5rem 0;
`;

const ErrorMessage = styled.div`
    color: #f87171;
    font-size: 0.7rem;
    padding: 0.4rem 0;
`;

const OrderControls = styled.div`
    display: inline-flex;
    gap: 0.35rem;
    margin-right: 0.5rem;
`;

const OrderButton = styled.button`
    width: 1.5rem;
    height: 1.5rem;
    border-radius: 6px;
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    background: ${({ theme }) => theme?.colors?.panelAlt || '#33373C'};
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-size: 0.7rem;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;

const ActionRow = styled.div`
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    margin-top: 0.6rem;
`;

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
                const agentsList = Array.isArray(agentsRes.value?.agents) ? agentsRes.value.agents : [];
                console.debug('[AgentsView] loaded', agentsList.length, 'agents');
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
        if (!addr || isPending(addr) || isApplyingOrder) return;
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
            const result = await tx.setAgents(newList);
            if (result?.success && mountedRef.current) {
                setEnabledOrder(newList);
                setDraftOrder(newList);
                setDraftDirty(false);
            } else {
                const errText = String(result?.error || 'Failed to update agents.');
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
    }, [isPending, isEnabled, isApplyingOrder, viewerAddress, maxEnabledAgents, enabledOrder, draftOrder, draftDirty, normalizeOrder, setEnabledOrder, setDraftOrder]);

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
                setErrorMessage(result?.error || 'Failed to reorder agents.');
            }
        } catch (err) {
            setErrorMessage(String(err?.message || err || 'Reorder failed.'));
        }
        setIsApplyingOrder(false);
        await refreshEnabledOrder();
    }, [viewerAddress, isApplyingOrder, hasDraftChanges, pendingAgents, draftOrder, refreshEnabledOrder, normalizeOrder, enabledOrder]);

    const displayOrder = draftOrder.length ? draftOrder : enabledOrder;

    const sortedAgents = React.useMemo(() => {
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
            .filter(agent => agent.addressLower && !enabledSetLocal.has(agent.addressLower));

        return [...enabled, ...rest];
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
                            <Section>
                                <SectionTitle>Available Agents</SectionTitle>
                                <SectionSubtitle>
                                    Order matters: When two agents edit the same field, the one higher in your list wins.
                                </SectionSubtitle>
                                {errorMessage && <ErrorMessage>{errorMessage}</ErrorMessage>}
                                {(loadingAgents || loadingEnabled) ? (
                                    <EmptyMessage>Loading agents...</EmptyMessage>
                                ) : sortedAgents.length === 0 ? (
                                    <EmptyMessage>No agents available yet.</EmptyMessage>
                                ) : (
                                    sortedAgents.map((agent) => {
                                        const addrLower = (agent.address || '').toLowerCase();
                                        const enabled = isEnabled(agent.address);
                                        const pending = isPending(addrLower);
                                        const displayName = agent.username || (agent.address ? `${agent.address.slice(0, 12)}...` : 'Unknown');
                                        const orderIdx = displayOrder.indexOf(addrLower);
                                        const canMoveUp = enabled && orderIdx > 0;
                                        const canMoveDown = enabled && orderIdx >= 0 && orderIdx < (displayOrder.length - 1);
                                        return (
                                            <ItemRow key={agent.address}>
                                                <ItemLeft>
                                                    <AgentName to={`/u/${encodeURIComponent(agent.username || agent.address)}?tab=posts`}>
                                                        @{displayName}
                                                    </AgentName>
                                                    {agent.biography && (
                                                        <AgentBio>{agent.biography}</AgentBio>
                                                    )}
                                                </ItemLeft>
                                                <ItemRight>
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
                                                    <Button
                                                        variant={
                                                            enabled && hoverAgent === addrLower
                                                                ? 'primaryDanger'
                                                                : enabled
                                                                    ? 'subtle'
                                                                    : 'primary'
                                                        }
                                                        size="pill"
                                                        disabled={pending || !viewerAddress || isApplyingOrder || loadingEnabled}
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
                                                    </Button>
                                                </ItemRight>
                                            </ItemRow>
                                        );
                                    })
                                )}
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
                            </Section>
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
