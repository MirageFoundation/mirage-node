import React from "react";
import { useLocation } from "react-router-dom";
import Storage from "../utils/Storage";
import Api from "../utils/api";
import * as tx from "../utils/tx";
import { signPlainPayload } from "../utils/signPlain";
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
        } catch (_) {/* noop */ }
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
            const sig = await signPlainPayload(
                (ts, n) => `get_reports:${publicKey.toLowerCase()}:${ts}:${n}`
            );
            const res = await Api.get('get_reports', {
                address: publicKey,
                limit: 200,
                ...sig,
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
            const sig = await signPlainPayload(
                (ts, n) => `resolve_report:${publicKey.toLowerCase()}:${ts}:${n}`
            );
            await Api.post('core/resolve_report', {
                address: publicKey,
                id: id >>> 0,
                ...sig,
            });
            setReports(prev => prev.filter(r => r && Number(r.id) !== Number(id)));
        } catch (e) {
            setError(String(e && e.message ? e.message : 'Failed to resolve report'));
        }
    };
    const [processing, setProcessing] = React.useState(new Set());
    // Per-button action tracking so consumers (e.g. the default-theme
    // ReportsView) can show the spinner only on the button that was
    // actually clicked, instead of both actions for the same row.
    // Maps `report.id` → `'delete' | 'ignore'`.
    const [processingAction, setProcessingAction] = React.useState(new Map());
    const beginAction = (id, action) => {
        setProcessing(prev => new Set(prev).add(id));
        setProcessingAction(prev => {
            const next = new Map(prev);
            next.set(id, action);
            return next;
        });
    };
    const endAction = id => {
        setProcessing(prev => {
            const next = new Set(prev);
            next.delete(id);
            return next;
        });
        setProcessingAction(prev => {
            const next = new Map(prev);
            next.delete(id);
            return next;
        });
    };
    const onDelete = async r => {
        beginAction(r.id, 'delete');
        try {
            await tx.deletePost(r.target);
            setReports(prev => {
                const next = prev.filter(report => report.target !== r.target);
                notifyCount(next.length);
                return next;
            });
        } finally {
            endAction(r.id);
        }
    };
    const onIgnore = async r => {
        beginAction(r.id, 'ignore');
        try {
            await resolveReport(r.id);
        } finally {
            endAction(r.id);
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
        processingAction,
        onDelete,
        onIgnore
    };
}
