import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Storage from "../utils/Storage";
import Api from "../utils/api";
import { signPlainPayload } from "../utils/signPlain";
import { peekBootstrapStashAfterBootstrap, readBootstrapStash } from "../utils/bootstrapStash";
export const AWARD_LABELS = {
    quality_post: 'Quality Post',
    original_content: 'Original Content',
    based: 'Based AF',
    receipts: 'Receipts'
};
export const formatAwardLabel = name => {
    const key = String(name || '').trim();
    return AWARD_LABELS[key] || key || 'Award';
};
export function truncateWords(text, maxWords) {
    if (!text) return '';
    const words = text.split(/\s+/).filter(Boolean);
    if (words.length <= maxWords) return text.trim();
    return words.slice(0, maxWords).join(' ') + '…';
}
export function useInbox({
    state
}) {
    const navigate = useNavigate();
    const location = useLocation();
    const [replies, setReplies] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [currentPage, setCurrentPage] = useState(1);
    const [hasMoreReplies, setHasMoreReplies] = useState(false);
    const [isLoadingMore, setIsLoadingMore] = useState(false);
    const viewerAddress = Storage.load('publicKey', '');
    const [activeReplyId, setActiveReplyId] = useState('');
    const isMountedRef = useRef(true);
    const fetchRequestRef = useRef(0);
    const bootstrapInboxTriedRef = useRef(false);
    const badgeCountRef = useRef((() => {
        try {
            return Math.max(0, parseInt(localStorage.getItem('inbox_count'), 10) || 0);
        } catch (_) {
            return 0;
        }
    })());

    // Persist inbox count to localStorage and dispatch event to update badge.
    // Also sets a cooldown timestamp so maybeSyncInbox in api.js won't
    // overwrite with a stale server value from an in-flight request.
    const setBadgeCount = useCallback(count => {
        const n = Math.max(0, count);
        badgeCountRef.current = n;
        try {
            localStorage.setItem('inbox_count', String(n));
            localStorage.setItem('inbox_count_set_at', String(Date.now()));
        } catch (_) { }
        window.dispatchEvent(new CustomEvent('inboxCount', {
            detail: n
        }));
    }, []);
    const persistInboxLastViewed = useCallback(value => {
        const ts = Math.max(0, Number(value) || 0);
        if (!ts) return;
        try {
            localStorage.setItem('inbox_last_viewed_at', String(ts));
        } catch (_) { }
    }, []);

    // Track server-side badge count so we can decrement it on individual mark-read
    useEffect(() => {
        const handler = e => {
            if (typeof e.detail === 'number') badgeCountRef.current = Math.max(0, e.detail);
        };
        window.addEventListener('inboxCount', handler);
        return () => {
            isMountedRef.current = false;
            window.removeEventListener('inboxCount', handler);
        };
    }, []);

    const applyInboxPage = useCallback((res, {
        requestId,
        requestAddress,
        append
    }) => {
        if (!isMountedRef.current || fetchRequestRef.current !== requestId) return false;
        if (!res || !Array.isArray(res.replies)) {
            setError('Invalid response from server');
            return false;
        }
        if (append) {
            setReplies(prev => [...prev, ...res.replies]);
        } else {
            setReplies(res.replies);
            signPlainPayload((ts, n) => `mark_inbox_viewed:${requestAddress.toLowerCase()}:${ts}:${n}`).then(sig => {
                console.debug("[Inbox] mark_inbox_viewed send", {
                    address: requestAddress
                });
                if (!isMountedRef.current || fetchRequestRef.current !== requestId) return null;
                return Api.post('mark_inbox_viewed', {
                    address: requestAddress,
                    ...sig
                });
            }).then(res => {
                if (!isMountedRef.current || fetchRequestRef.current !== requestId) return;
                if (res && typeof res.inbox_last_viewed_at === 'number') {
                    persistInboxLastViewed(res.inbox_last_viewed_at);
                }
            }).catch(err => {
                console.error("[Inbox] mark_inbox_viewed failed", err);
            });
            // Clear badge immediately — don't wait for next API response
            setBadgeCount(0);
        }
        setHasMoreReplies(res.has_more || false);
        setError('');
        return true;
    }, [persistInboxLastViewed, setBadgeCount]);

    const fetchInbox = useCallback(async (page = 1, append = false) => {
        if (!viewerAddress) {
            setLoading(false);
            setReplies([]);
            return;
        }
        try {
            const requestId = fetchRequestRef.current + 1;
            fetchRequestRef.current = requestId;
            const requestAddress = viewerAddress;
            if (page === 1) {
                setLoading(true);
            } else {
                setIsLoadingMore(true);
            }

            // First page cold-start: prefer bootstrap_view inbox stash.
            if (page === 1 && !append && !bootstrapInboxTriedRef.current) {
                bootstrapInboxTriedRef.current = true;
                try {
                    const stashed = await peekBootstrapStashAfterBootstrap('bootstrap_view', viewerAddress);
                    if (
                        stashed
                        && stashed.kind === 'inbox'
                        && Array.isArray(stashed.replies)
                    ) {
                        readBootstrapStash('bootstrap_view', viewerAddress);
                        console.debug('[Inbox] bootstrap stash hit', {
                            replies: stashed.replies.length,
                            has_more: !!stashed.has_more,
                        });
                        if (applyInboxPage(stashed, { requestId, requestAddress, append: false })) {
                            return;
                        }
                    }
                } catch (_) { /* fall through to get_inbox */ }
            }

            // Independent fetch: drop late launch stash so it cannot override
            // a later inbox mount within the stash TTL.
            if (page === 1 && !append) {
                try { Storage.remove('bootstrap_view'); } catch (_) { }
            }

            const res = await Api.get('get_inbox', {
                address: viewerAddress,
                page,
                limit: 25
            });
            applyInboxPage(res, { requestId, requestAddress, append });
        } catch (e) {
            if (!isMountedRef.current) return;
            setError(String(e && e.message ? e.message : 'Failed to load inbox'));
        } finally {
            // A return here would swallow anything propagating out of the try.
            if (isMountedRef.current) {
                setLoading(false);
                setIsLoadingMore(false);
            }
        }
    }, [viewerAddress, applyInboxPage]);
    useEffect(() => {
        fetchInbox(1, false);
    }, [fetchInbox]);
    const handleLoadMore = () => {
        const nextPage = currentPage + 1;
        setCurrentPage(nextPage);
        fetchInbox(nextPage, true);
    };
    const handleMarkAllAsRead = () => {
        const allReplyIds = replies.map(r => r.reply_id);
        Storage.markAllRepliesAsViewed(allReplyIds);
        setReplies(prev => prev.map(r => ({
            ...r,
            isUnread: false
        })));
        signPlainPayload((ts, n) => `mark_inbox_viewed:${viewerAddress.toLowerCase()}:${ts}:${n}`).then(sig => {
            console.debug("[Inbox] mark_inbox_viewed send", {
                address: viewerAddress
            });
            return Api.post('mark_inbox_viewed', {
                address: viewerAddress,
                ...sig
            });
        }).then(res => {
            if (res && typeof res.inbox_last_viewed_at === 'number') {
                persistInboxLastViewed(res.inbox_last_viewed_at);
            }
        }).catch(err => {
            console.error("[Inbox] mark_inbox_viewed failed", err);
        });
        // Clear badge immediately
        setBadgeCount(0);
    };
    const handleMarkOneAsRead = (e, reply) => {
        e.preventDefault();
        e.stopPropagation();
        Storage.addViewedReplyId(reply.reply_id);
        setReplies(prev => [...prev]);
        // Decrement badge immediately
        setBadgeCount(badgeCountRef.current - 1);
    };
    const handleReplyClick = reply => {
        if (!reply) return;
        const wasUnread = !Storage.getViewedReplyIds().includes(reply.reply_id);
        Storage.addViewedReplyId(reply.reply_id);
        if (wasUnread) {
            setBadgeCount(badgeCountRef.current - 1);
        }
        const isProfileNotice = reply.type === 'follow' || reply.type === 'donation' || reply.type === 'subscription_gift';
        if (isProfileNotice) {
            const actorIdentity = reply.reply_username || reply.reply_owner;
            if (actorIdentity) {
                setActiveReplyId(reply.reply_id);
                navigate(`/u/${encodeURIComponent(actorIdentity)}`);
            }
            return;
        }
        if (reply.root_post_id) {
            try {
                Storage.setPendingPostHighlight(reply.reply_id);
            } catch (_) { }
            setActiveReplyId(reply.reply_id);
        }
        // Use new clean URL with depth=1 to show reply with immediate parent context
        navigate(`/p/${reply.reply_id}?depth=1`);
    };
    const handleReplyPointerDown = useCallback((reply) => {
        if (!reply?.reply_id || !viewerAddress) return;
        if (reply.type === 'follow' || reply.type === 'donation' || reply.type === 'subscription_gift') return;
        console.debug('[Inbox] prefetch get_comments', { post_id: reply.reply_id });
        Api.prefetch('get_comments', { post_id: reply.reply_id, address: viewerAddress });
    }, [viewerAddress]);
    const shortenAddress = addr => {
        if (!addr) return '';
        return `${addr.slice(0, 10)}…${addr.slice(-4)}`;
    };

    // removed unused formatTime

    const viewedReplyIds = Storage.getViewedReplyIds();
    const unreadCount = replies.reduce((acc, r) => acc + (viewedReplyIds.includes(r.reply_id) ? 0 : 1), 0);
    const titleText = unreadCount > 0 ? `Inbox (${unreadCount} unread)` : 'Inbox';
    return {
        location,
        replies,
        loading,
        error,
        hasMoreReplies,
        isLoadingMore,
        viewerAddress,
        activeReplyId,
        handleLoadMore,
        handleMarkAllAsRead,
        handleMarkOneAsRead,
        handleReplyClick,
        handleReplyPointerDown,
        shortenAddress,
        viewedReplyIds,
        unreadCount,
        titleText,
        truncateWords
    };
}
