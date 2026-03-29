import { useEffect, useState, useCallback } from "react";
import { useLocation } from "react-router-dom";
import Storage from "../utils/Storage";
import Api from "../lib/api";
export const PERIODS = [{
  key: "7d",
  label: "Last 7 Days"
}, {
  key: "30d",
  label: "Last 30 Days"
}, {
  key: "month",
  label: "This Month"
}, {
  key: "prev_month",
  label: "Last Month"
}];
export const PAGE_SIZE = 50;
export function getMonthStr(offset = 0) {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}
export function useReferrals({
  state
}) {
  const location = useLocation();
  const publicKey = state && state.publicKey ? state.publicKey : Storage.load("publicKey", "");
  const username = state && state.username ? state.username : Storage.load("username", "");
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
    Api.get('get_invite_codes', {
      address: publicKey
    }).then(resp => {
      if (cancelled) return;
      if (resp && Array.isArray(resp.codes)) setInviteCodes(resp.codes);
    }).catch(() => {});
    return () => {
      cancelled = true;
    };
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
  const fetchSummary = useCallback(async ({
    append = false,
    offset: offsetParam
  } = {}) => {
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
      const params = {
        address: publicKey,
        limit: PAGE_SIZE,
        offset: baseOffset
      };
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
    fetchSummary({
      append: false,
      offset: 0
    });
  }, [fetchSummary]);
  const handleLoadMore = () => {
    if (loadingMore || !hasMore) return;
    fetchSummary({
      append: true,
      offset
    });
  };
  const handleCopy = () => {
    try {
      navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (_) {}
  };
  return {
    location,
    publicKey,
    username,
    period,
    setPeriod,
    data,
    referrals,
    hasMore,
    loading,
    loadingMore,
    error,
    copied,
    shareUrl,
    handleLoadMore,
    handleCopy
  };
}