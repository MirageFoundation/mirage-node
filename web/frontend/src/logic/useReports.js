import React from "react";
import { useLocation } from "react-router-dom";
import Storage from "../utils/Storage";
import Api from "../lib/api";
import * as tx from "../utils/tx";
export function useReports({
  state
}) {
  const location = useLocation();
  const [reports, setReports] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  const publicKey = Storage.load('publicKey', '');
  const userLevel = Number(Storage.load('user_level', '0'));
  const notifyCount = React.useCallback(count => {
    try {
      const evt = new CustomEvent('reportsUpdated', {
        detail: {
          count
        }
      });
      window.dispatchEvent(evt);
    } catch (_) {/* noop */}
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
      const res = await Api.get('get_reports', {
        address: publicKey,
        limit: 200
      });
      const list = res && Array.isArray(res.reports) ? res.reports : [];
      setReports(list);
      setError('');
      notifyCount(list.length);
    } catch (e) {
      setError(String(e && e.message ? e.message : 'Failed to load reports'));
    } finally {
      setLoading(false);
    }
  }, [publicKey, userLevel, notifyCount]);
  React.useEffect(() => {
    fetchReports();
  }, [fetchReports]);
  const resolveReport = async id => {
    try {
      await Api.post('core/resolve_report', {
        address: publicKey,
        id: id >>> 0
      });
      setReports(prev => prev.filter(r => r && Number(r.id) !== Number(id)));
    } catch (e) {
      setError(String(e && e.message ? e.message : 'Failed to resolve report'));
    }
  };
  const [processing, setProcessing] = React.useState(new Set());
  const onDelete = async r => {
    setProcessing(prev => new Set(prev).add(r.id));
    try {
      await tx.deletePost(r.target);
      setReports(prev => {
        const next = prev.filter(report => report.target !== r.target);
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
  const onDeleteAndBlock = async r => {
    setProcessing(prev => new Set(prev).add(r.id));
    try {
      await tx.deletePost(r.target);
      if (r.post_owner) {
        await tx.blockUser(r.post_owner, true);
      }
      setReports(prev => {
        const next = prev.filter(report => report.target !== r.target);
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
  const onIgnore = async r => {
    setProcessing(prev => new Set(prev).add(r.id));
    try {
      await resolveReport(r.id);
    } finally {
      setProcessing(prev => {
        const next = new Set(prev);
        next.delete(r.id);
        return next;
      });
      setReports(prev => {
        const next = prev.filter(x => x.id !== r.id);
        notifyCount(next.length);
        return next;
      });
    }
  };
  return {
    location,
    reports,
    loading,
    error,
    userLevel,
    processing,
    onDelete,
    onDeleteAndBlock,
    onIgnore
  };
}