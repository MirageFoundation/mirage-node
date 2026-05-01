import React, { useState, useEffect, useRef, useCallback } from "react";
import Storage from "../utils/Storage";
import Api from "../utils/api";
import { useLocation } from "react-router-dom";
import * as tx from "../utils/tx";
import { usePendingAgents } from "./usePendingAgents.js";
import { formatError } from "../utils/errorMessages";
export const MOBILE_ACTION_HEIGHT = '2.4rem';
export function formatTimeAgo(unixSeconds) {
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
export function useAgents({
    state
}) {
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
    const {
        isPending,
        formatStatus,
        pendingAgents
    } = usePendingAgents();
    const mountedRef = useRef(true);
    const enabledOrderRef = useRef([]);
    useEffect(() => { enabledOrderRef.current = enabledOrder; }, [enabledOrder]);
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
            if (levelRaw === 0) tierIdx = 0; else if (levelRaw === 1) tierIdx = 1; else if (levelRaw === 10 || levelRaw >= 100) tierIdx = 2;
            if (tierIdx < 0 || tierIdx >= cfg.tiers.length) return null;
            const max = Number(cfg.tiers[tierIdx]?.max_enabled_agents ?? 0);
            return Number.isFinite(max) ? max : null;
        } catch (_) {
            return null;
        }
    }, []);
    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
        };
    }, []);
    const normalizeOrder = useCallback(order => {
        const seen = new Set();
        return (order || []).map(a => String(a || '').toLowerCase()).filter(a => {
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
            const tasks = [Api.get('get_agents', {}, {
                timeoutMs: 10000
            }), viewerAddress ? Api.get('get_user_followed', {
                address: viewerAddress
            }, {
                timeoutMs: 10000
            }) : Promise.resolve(null)];
            const [agentsRes, followedRes] = await Promise.allSettled(tasks);
            if (!alive || !mountedRef.current) return;
            if (agentsRes.status === 'fulfilled') {
                const raw = Array.isArray(agentsRes.value?.agents) ? agentsRes.value.agents : [];
                const viewerLower = String(viewerAddress || '').toLowerCase();
                const agentsList = viewerLower ? raw.filter(a => (a.address || '').toLowerCase() !== viewerLower) : raw;
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
        load().catch(err => {
            console.error('[AgentsView] load error:', err);
            if (!alive || !mountedRef.current) return;
            setLoadingAgents(false);
            setLoadingEnabled(false);
            setErrorMessage('Failed to load agents.');
        });
        return () => {
            alive = false;
        };
    }, [viewerAddress, normalizeOrder]);
    useEffect(() => {
        if (draftDirty) return;
        setDraftOrder(enabledOrder);
    }, [enabledOrder, draftDirty]);
    const ensureChainConfig = useCallback(async () => {
        let max = readMaxEnabledAgents();
        if (max !== null) return max;
        try {
            tx.releaseChainConfigClaim();
            const cfg = await Api.get('get_chain_config', undefined, { timeoutMs: 5000 });
            if (cfg && typeof cfg === 'object') {
                await tx.cacheChainConfig(cfg);
            }
        } catch (err) {
            console.error('[AgentsView] chain config fetch failed:', err);
        }
        return readMaxEnabledAgents();
    }, [readMaxEnabledAgents]);
    useEffect(() => {
        let mounted = true;
        const handleConfigUpdate = () => {
            if (!mounted) return;
            setMaxEnabledAgents(readMaxEnabledAgents());
        };
        handleConfigUpdate();
        ensureChainConfig().then(max => {
            if (mounted) setMaxEnabledAgents(max);
        });
        window.addEventListener('chainConfigUpdated', handleConfigUpdate);
        return () => {
            mounted = false;
            window.removeEventListener('chainConfigUpdated', handleConfigUpdate);
        };
    }, [readMaxEnabledAgents, ensureChainConfig]);
    const isEnabled = useCallback(address => {
        return enabledSet.has(String(address || '').toLowerCase());
    }, [enabledSet]);
    const handleToggle = useCallback(async agentAddress => {
        const addr = String(agentAddress || '').toLowerCase();
        if (!addr || isPending(addr)) return;
        setErrorMessage('');
        if (!viewerAddress) return;
        let limit = maxEnabledAgents;
        if (limit === null) {
            limit = await ensureChainConfig();
            if (limit !== null && mountedRef.current) setMaxEnabledAgents(limit);
        }
        const baseOrder = draftDirty ? draftOrder : enabledOrderRef.current;
        const normalizedBase = normalizeOrder(baseOrder);
        const wasEnabled = normalizedBase.includes(addr);
        let newList;
        if (wasEnabled) {
            newList = normalizedBase.filter(a => a !== addr);
        } else {
            if (limit !== null && normalizedBase.length >= limit) {
                setErrorMessage(`Enabled agents limit reached (${limit}). Disable one first.`);
                return;
            }
            newList = [...normalizedBase, addr];
        }
        // Apply optimistic update synchronously so subsequent toggles see the
        // latest list when computing their own newList. Without this, two
        // rapid clicks would each compute against the original enabledOrder
        // and the second setState would clobber the first.
        enabledOrderRef.current = newList;
        setEnabledOrder(newList);
        setDraftOrder(newList);
        setDraftDirty(false);
        try {
            const result = wasEnabled ? await tx.disableAgent(addr) : await tx.enableAgent(addr);
            if (!result?.success && mountedRef.current) {
                const errText = formatError(result);
                const lower = errText.toLowerCase();
                if (lower.includes('limit') || lower.includes('too many agents')) {
                    setErrorMessage(limit !== null
                        ? `Enabled agents limit reached (${limit}). Disable one first.`
                        : 'Enabled agents limit reached. Disable one first.');
                } else {
                    setErrorMessage(errText);
                }
                if (refreshEnabledOrderRef.current) await refreshEnabledOrderRef.current();
            }
        } catch (err) {
            setErrorMessage(String(err?.message || err || 'Agent update failed.'));
            if (mountedRef.current && refreshEnabledOrderRef.current) await refreshEnabledOrderRef.current();
        }
    }, [isPending, viewerAddress, maxEnabledAgents, ensureChainConfig, draftOrder, draftDirty, normalizeOrder]);
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
        const list = draftOrder.length ? [...draftOrder] : [...enabledOrder];
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
            const data = await Api.get('get_user_followed', {
                address: viewerAddress
            }, {
                timeoutMs: 10000
            });
            const enabled = normalizeOrder(data?.enabled_agents || []);
            enabledOrderRef.current = enabled;
            setEnabledOrder(enabled);
            if (!draftDirty) setDraftOrder(enabled);
            console.debug('[AgentsView] refreshed enabled order', enabled);
        } catch (err) {
            console.error('[AgentsView] refresh enabled order failed:', err);
        }
    }, [viewerAddress, draftDirty, normalizeOrder]);
    const refreshEnabledOrderRef = useRef(refreshEnabledOrder);
    useEffect(() => { refreshEnabledOrderRef.current = refreshEnabledOrder; }, [refreshEnabledOrder]);
    const applyOrder = useCallback(async () => {
        if (!viewerAddress || isApplyingOrder || !hasDraftChanges) return;
        if (Object.keys(pendingAgents || {}).length > 0) {
            setErrorMessage('Wait for pending agent transactions to finish.');
            return;
        }
        setErrorMessage('');
        setIsApplyingOrder(true);
        console.debug('[AgentsView] apply order', {
            from: enabledOrder,
            to: draftOrder
        });
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
    const {
        sortedAgents,
        enabledCount
    } = React.useMemo(() => {
        const byAddr = new Map();
        for (const agent of agents) {
            const key = String(agent.address || '').toLowerCase();
            if (!key) continue;
            byAddr.set(key, {
                ...agent,
                addressLower: key
            });
        }
        const enabled = [];
        const enabledSetLocal = new Set(displayOrder);
        for (const addr of displayOrder) {
            const entry = byAddr.get(addr);
            if (entry) enabled.push(entry);
        }
        const rest = agents.map(agent => ({
            ...agent,
            addressLower: String(agent.address || '').toLowerCase()
        })).filter(agent => agent.addressLower && !enabledSetLocal.has(agent.addressLower)).sort((a, b) => (b.last_active || 0) - (a.last_active || 0));
        return {
            sortedAgents: [...enabled, ...rest],
            enabledCount: enabled.length
        };
    }, [agents, displayOrder]);
    return {
        viewerAddress,
        loadingAgents,
        loadingEnabled,
        errorMessage,
        isApplyingOrder,
        hoverAgent,
        setHoverAgent,
        isPending,
        formatStatus,
        location,
        isEnabled,
        handleToggle,
        hasDraftChanges,
        moveAgent,
        applyOrder,
        displayOrder,
        sortedAgents,
        enabledCount
    };
}