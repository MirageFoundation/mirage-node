import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Api from "../utils/api";

// Shared chart layout constants — ALL charts MUST use the same values so axes align.
// labelH reserves space above/below the plot area for Y-axis text labels.
const CHART_LABEL_H = 10;
export const CHART = {
    width: 400,
    height: 120,
    padding: {
        top: CHART_LABEL_H + 4,
        right: 10,
        bottom: CHART_LABEL_H + 4,
        left: 50
    }
};
CHART.innerW = CHART.width - CHART.padding.left - CHART.padding.right;
CHART.innerH = CHART.height - CHART.padding.top - CHART.padding.bottom;

// Shared compact MIRAGE formatter
export function fmtMirage(v) {
    const a = Math.abs(v);
    if (a >= 1e9) return (v / 1e9).toFixed(a >= 1e11 ? 1 : 2) + 'B';
    if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e8 ? 1 : 2) + 'M';
    if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e5 ? 0 : 1) + 'K';
    if (a >= 1) return v.toFixed(1);
    if (a >= 0.01) return v.toFixed(2);
    return v.toFixed(4);
}

// Shared SVG grid (left axis, bottom axis, right axis)
export function useNetwork({
    state
}) {
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
        pow_factor: undefined,
        pow_message_count: undefined,
        pow_calm_sequence: undefined,
        pow_last_change_height: undefined,
        current_height: undefined,
        difficulty_history: [],
        validator_moniker: undefined,
        validator_account_address: undefined,
        validator_operator_address: undefined,
        validator_consensus_address: undefined
    });
    const [peers, setPeers] = useState(null);
    const [serverBalance, setServerBalance] = useState(null);
    const [stakedBalance, setStakedBalance] = useState(null);
    const [copiedAddress, setCopiedAddress] = useState(null);
    const [circulationStats, setCirculationStats] = useState({
        total_supply: null,
        top_accounts: []
    });
    const [supplyHistory, setSupplyHistory] = useState({
        history: []
    });

    // Update tab when URL changes
    useEffect(() => {
        if (location.pathname === '/server') {
            setActiveTab('server');
        } else if (location.pathname === '/network') {
            setActiveTab('network');
        }
    }, [location.pathname]);

    // Load static validator info from cached node config (once)
    useEffect(() => {
        try {
            const raw = localStorage.getItem('nodeConfig');
            if (raw) {
                const cached = JSON.parse(raw);
                setCfg(prev => ({
                    ...prev,
                    validator_moniker: cached.validator_moniker || undefined,
                    validator_account_address: cached.validator_account_address,
                    validator_operator_address: cached.validator_operator_address,
                    validator_consensus_address: cached.validator_consensus_address
                }));
            }
        } catch (_) { }
    }, []);

    // Fetch network stats (dynamic data)
    useEffect(() => {
        let cancelled = false;
        const fetchNetworkStats = async () => {
            try {
                const data = await Api.get('get_network_stats', undefined);
                if (!cancelled && data) {
                    const sb = Number(data.server_balance);
                    if (isFinite(sb)) setServerBalance(sb);
                    const stk = Number(data.staked_balance);
                    if (isFinite(stk)) setStakedBalance(stk);
                    setCfg(prev => ({
                        ...prev,
                        block_time: typeof data.block_time !== 'undefined' ? Number(data.block_time) : undefined,
                        pow_difficulty: typeof data.pow_difficulty !== 'undefined' ? Number(data.pow_difficulty) : undefined,
                        pow_factor: typeof data.pow_factor !== 'undefined' ? Number(data.pow_factor) : undefined,
                        pow_message_count: typeof data.pow_message_count !== 'undefined' ? Number(data.pow_message_count) : undefined,
                        pow_calm_sequence: typeof data.pow_calm_sequence !== 'undefined' ? Number(data.pow_calm_sequence) : undefined,
                        pow_last_change_height: typeof data.pow_last_change_height !== 'undefined' ? Number(data.pow_last_change_height) : undefined,
                        current_height: typeof data.current_height !== 'undefined' ? Number(data.current_height) : undefined,
                        difficulty_history: Array.isArray(data.difficulty_history) ? data.difficulty_history : [],
                        earned_24h: typeof data.earned_24h !== 'undefined' ? Number(data.earned_24h) : undefined,
                        burned_24h: typeof data.burned_24h !== 'undefined' ? Number(data.burned_24h) : undefined
                    }));
                }
            } catch (_) { }
        };
        fetchNetworkStats();
        // Auto-refresh every 10 seconds
        const interval = setInterval(fetchNetworkStats, 10000);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, []);
    useEffect(() => {
        let cancelled = false;
        const fetchPeers = async () => {
            try {
                const data = await Api.get('get_peers', undefined, {
                    timeoutMs: 5000
                });
                if (!cancelled) {
                    const list = data && Array.isArray(data.peers) ? data.peers : [];
                    setPeers(list);
                }
            } catch (_) {
                if (!cancelled) setPeers([]);
            }
        };
        fetchPeers();
        return () => {
            cancelled = true;
        };
    }, []);

    // Fetch circulation stats
    useEffect(() => {
        let cancelled = false;
        const fetchCirculationStats = async () => {
            try {
                const data = await Api.get('get_circulation_stats', undefined, {
                    timeoutMs: 15000
                });
                if (!cancelled && data) {
                    setCirculationStats({
                        total_supply: data.total_supply ?? null,
                        top_accounts: Array.isArray(data.top_accounts) ? data.top_accounts : []
                    });
                }
            } catch (_) { }
        };
        fetchCirculationStats();
        const interval = setInterval(fetchCirculationStats, 60000);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, []);

    // Fetch supply history for burn/mint chart
    useEffect(() => {
        let cancelled = false;
        const fetchSupplyHistory = async () => {
            try {
                const data = await Api.get('get_supply_history', undefined, {
                    timeoutMs: 15000
                });
                if (!cancelled && data) {
                    setSupplyHistory({
                        history: Array.isArray(data.history) ? data.history : []
                    });
                }
            } catch (_) { }
        };
        fetchSupplyHistory();
        const interval = setInterval(fetchSupplyHistory, 60000);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, []);
    const handleTabChange = tab => {
        if (tab === activeTab) return;
        setActiveTab(tab);
        navigate(tab === 'server' ? '/server' : '/network', {
            replace: true
        });
    };
    const toHttpUrl = peer => {
        try {
            if (peer.moniker && (peer.moniker.startsWith('http://') || peer.moniker.startsWith('https://'))) {
                return peer.moniker.endsWith('/') ? peer.moniker : `${peer.moniker}/`;
            }
            if (peer.ip) {
                const formattedHost = typeof peer.ip === 'string' && peer.ip.includes(':') ? `[${peer.ip}]` : peer.ip;
                return `http://${formattedHost}/`;
            }
            return '#';
        } catch (_) {
            return '#';
        }
    };
    const getDisplayName = peer => {
        if (peer.moniker && (peer.moniker.startsWith('http://') || peer.moniker.startsWith('https://'))) {
            return peer.moniker;
        }
        if (peer.ip) return `http://${peer.ip}`;
        return '(unknown)';
    };
    return {
        location,
        navigate,
        activeTab,
        cfg,
        peers,
        serverBalance,
        stakedBalance,
        copiedAddress,
        setCopiedAddress,
        circulationStats,
        supplyHistory,
        handleTabChange,
        toHttpUrl,
        getDisplayName
    };
}