import { useEffect, useState, useCallback } from "react";
import { useLocation } from "react-router-dom";
import Storage from "../utils/Storage";
import Api from "../utils/api";
import { signPlainPayload } from "../utils/signPlain";

export const PAGE_SIZE = 50;

export function getISOWeekFromDate(date) {
    const utc = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
    const dayNum = utc.getUTCDay() || 7;
    utc.setUTCDate(utc.getUTCDate() + 4 - dayNum);
    const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
    const weekNo = Math.ceil(((utc - yearStart) / 86400000 + 1) / 7);
    return `${utc.getUTCFullYear()}-W${String(weekNo).padStart(2, '0')}`;
}

export function getCurrentISOWeek() {
    return getISOWeekFromDate(new Date());
}

export function parseISOWeek(weekStr) {
    const match = /^(\d{4})-W(\d{2})$/.exec(String(weekStr || '').trim());
    if (!match) return null;
    const year = Number(match[1]);
    const week = Number(match[2]);
    if (!year || !week) return null;
    const jan4 = new Date(Date.UTC(year, 0, 4));
    const jan4Day = jan4.getUTCDay() || 7;
    const week1Monday = new Date(jan4);
    week1Monday.setUTCDate(jan4.getUTCDate() - (jan4Day - 1));
    const monday = new Date(week1Monday);
    monday.setUTCDate(week1Monday.getUTCDate() + (week - 1) * 7);
    monday.setUTCHours(0, 0, 0, 0);
    return monday;
}

export function shiftISOWeek(weekStr, deltaWeeks) {
    const start = parseISOWeek(weekStr);
    if (!start || !Number.isFinite(deltaWeeks)) return null;
    const next = new Date(start);
    next.setUTCDate(next.getUTCDate() + deltaWeeks * 7);
    return getISOWeekFromDate(next);
}

export function compareISOWeeks(a, b) {
    const dateA = parseISOWeek(a);
    const dateB = parseISOWeek(b);
    if (!dateA || !dateB) return 0;
    if (dateA.getTime() === dateB.getTime()) return 0;
    return dateA.getTime() > dateB.getTime() ? 1 : -1;
}

export function formatWeekRange(weekStartTs, weekEndTs) {
    const start = new Date(Number(weekStartTs) * 1000);
    const end = new Date(Number(weekEndTs) * 1000);
    if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) return '';
    const opts = { month: 'short', day: '2-digit', timeZone: 'UTC' };
    const startLabel = start.toLocaleDateString('en-US', opts);
    const endLabel = end.toLocaleDateString('en-US', opts);
    return `${startLabel} - ${endLabel}`;
}

export function useReferrals({ state, targetAddress }) {
    const location = useLocation();
    const publicKey = state && state.publicKey ? state.publicKey : Storage.load("publicKey", "");
    const username = state && state.username ? state.username : Storage.load("username", "");
    const [precheckEnabled, setPrecheckEnabled] = useState(() => {
        try {
            return Storage.load('referral_precheck_enabled', false) === true;
        } catch (_) {
            return false;
        }
    });
    const [referralPrecheckBusy, setReferralPrecheckBusy] = useState(false);
    const [referralPrecheckError, setReferralPrecheckError] = useState('');
    const [referralPrecheckSuccess, setReferralPrecheckSuccess] = useState('');
    const [inviteCodesRequired] = useState(() => {
        try {
            const nc = JSON.parse(localStorage.getItem('nodeConfig') || '{}');
            return !!nc.registration_invite_code_required;
        } catch (_) {
            return false;
        }
    });

    const effectiveAddress = targetAddress || publicKey;
    const isOwnReferrals = !targetAddress || targetAddress.toLowerCase() === publicKey.toLowerCase();

    const [week, setWeek] = useState(() => getCurrentISOWeek());
    const [data, setData] = useState(null);
    const [referrals, setReferrals] = useState([]);
    const [offset, setOffset] = useState(0);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState("");
    const [copied, setCopied] = useState(false);

    const getShareUrl = () => {
        if (!username) return '';
        const origin = typeof window !== 'undefined' ? window.location.origin : '';
        const identity = encodeURIComponent(username);
        return `${origin}/u/${identity}?ref=${identity}`;
    };
    const shareUrl = getShareUrl();

    const fetchSummary = useCallback(async ({ append = false, offset: offsetParam } = {}) => {
        if (!effectiveAddress) {
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
            const params = {
                address: effectiveAddress,
                week,
                limit: PAGE_SIZE,
                offset: baseOffset,
            };
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
    }, [effectiveAddress, week]);

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

    /* Mirrors `useSettings::handleReferralPrecheckToggle`. Persists to the
     * same `referral_precheck_enabled` key + `/referrals/precheck_opt_in`
     * endpoint so the Referrals-page toggle stays in sync with the one on
     * the Settings page. Only surfaced in the default ReferralsView. */
    const handleReferralPrecheckToggle = async (nextVal) => {
        if (!publicKey || referralPrecheckBusy) return;
        setReferralPrecheckBusy(true);
        setReferralPrecheckError('');
        setReferralPrecheckSuccess('');
        try {
            const addr = String(publicKey).toLowerCase();
            const sig = await signPlainPayload((ts, n) => `referrals_precheck_opt_in:${addr}:${nextVal ? 1 : 0}:${ts}:${n}`);
            const res = await Api.post('referrals/precheck_opt_in', {
                address: publicKey,
                enabled: !!nextVal,
                ...sig,
            });
            if (!res || res.precheck_enabled !== !!nextVal) {
                throw new Error('Unexpected response');
            }
            setPrecheckEnabled(!!nextVal);
            Storage.save('referral_precheck_enabled', !!nextVal);
            setReferralPrecheckSuccess('Saved.');
            setTimeout(() => setReferralPrecheckSuccess(''), 3000);
        } catch (e) {
            setReferralPrecheckError(String(e?.message || e || 'Failed to update'));
        } finally {
            setReferralPrecheckBusy(false);
        }
    };

    return {
        location,
        publicKey,
        username,
        effectiveAddress,
        isOwnReferrals,
        week,
        setWeek,
        data,
        referrals,
        hasMore,
        loading,
        loadingMore,
        error,
        copied,
        shareUrl,
        handleLoadMore,
        handleCopy,
        referralPrecheckEnabled: precheckEnabled,
        referralPrecheckBusy,
        referralPrecheckError,
        referralPrecheckSuccess,
        inviteCodesRequired,
        handleReferralPrecheckToggle,
    };
}
