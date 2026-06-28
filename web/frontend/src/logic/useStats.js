import { useEffect, useState, useCallback, useMemo } from "react";
import { useLocation } from "react-router-dom";
import Api from "../utils/api";
import { signPlainPayload } from "../utils/signPlain";

// Admin stats are signed with one payload type, matching the backend:
//   stats:{address}:{timestamp}:{nonce}
const STATS_ACTION = "stats";

const DAY = 86400;
export const PRESETS = [
    { id: "24h", label: "24h", seconds: DAY },
    { id: "7d", label: "7d", seconds: 7 * DAY },
    { id: "30d", label: "30d", seconds: 30 * DAY },
];

function lsString(key) {
    try {
        const raw = localStorage.getItem(key);
        if (!raw) return "";
        try { const v = JSON.parse(raw); return typeof v === "string" ? v : raw; } catch (_) { return raw; }
    } catch (_) { return ""; }
}

function todayStr() {
    return new Date().toISOString().slice(0, 10);
}

export function useStats() {
    const location = useLocation();
    const [preset, setPreset] = useState("7d");
    // Custom range (inclusive day strings YYYY-MM-DD); only used when preset === 'custom'.
    const [customStart, setCustomStart] = useState(todayStr());
    const [customEnd, setCustomEnd] = useState(todayStr());

    const [aggregate, setAggregate] = useState(null);
    const [servers, setServers] = useState([]);
    const [windowRange, setWindowRange] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const address = lsString("publicKey");

    const resolveWindow = useCallback(() => {
        const now = Math.floor(Date.now() / 1000);
        if (preset === "custom") {
            const start = Math.floor(new Date(customStart + "T00:00:00Z").getTime() / 1000);
            const end = Math.floor(new Date(customEnd + "T23:59:59Z").getTime() / 1000);
            return { start: Math.min(start, end), end: Math.max(start, end) };
        }
        const p = PRESETS.find(x => x.id === preset) || PRESETS[1];
        return { start: now - p.seconds, end: now };
    }, [preset, customStart, customEnd]);

    const fetchStats = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const { start, end } = resolveWindow();
            const signed = await signPlainPayload(
                (timestamp, nonce) => `${STATS_ACTION}:${(address || "").toLowerCase()}:${timestamp}:${nonce}`
            );
            const data = await Api.post("admin/stats/aggregate", {
                ...signed,
                address,
                start,
                end,
            }, { timeoutMs: 30000 });
            setAggregate(data.aggregate || null);
            setServers(Array.isArray(data.servers) ? data.servers : []);
            setWindowRange(data.window || { start, end });
        } catch (err) {
            setError(err && err.message ? err.message : "Failed to load stats");
            setAggregate(null);
            setServers([]);
        } finally {
            setLoading(false);
        }
    }, [resolveWindow, address]);

    useEffect(() => {
        fetchStats();
    }, [fetchStats]);

    const formatNumber = (num, digits = 0) => {
        if (num === null || num === undefined) return "0";
        const n = typeof num === "number" ? num : parseFloat(num);
        if (!Number.isFinite(n)) return "0";
        return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
    };
    const formatPercent = (rate, digits = 1) => {
        const v = typeof rate === "number" ? rate : parseFloat(rate);
        if (!Number.isFinite(v)) return "0%";
        return (v * 100).toFixed(digits) + "%";
    };
    const formatDate = ts => {
        if (!ts) return "N/A";
        return new Date(ts * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    };

    const okServers = useMemo(() => servers.filter(s => s.status === "ok"), [servers]);

    return {
        location,
        preset, setPreset,
        customStart, setCustomStart,
        customEnd, setCustomEnd,
        PRESETS,
        aggregate, servers, okServers, windowRange,
        loading, error,
        refresh: fetchStats,
        formatNumber, formatPercent, formatDate,
    };
}
