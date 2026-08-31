import React, { useState, useEffect, useLayoutEffect, useRef, useMemo } from "react";
import { useTheme } from "styled-components";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import * as tx from "../utils/tx.js";
import Api from "../utils/api";
import Storage from "../utils/Storage";
import { subscribe, unsubscribe, fetchFollowedTopics, invalidateCache as invalidateTopicsCache } from "../utils/Subscriptions";
import { fetchFollowedUsers, follow as followAuthor, unfollow as unfollowAuthor, invalidateCache as invalidateFollowCache } from "../utils/FollowUsers";
import { usePendingFollows } from "./useFollowState.js";
import { usePendingSends } from "./usePendingSends.js";
import { markPostOpened, markPostReplied } from "./useSeenPosts.js";
import { usePendingSubscribes } from "./usePendingSubscribes.js";
import { uploadImage } from "../utils/ImageUpload";
import { sortComments } from "../utils/SortComments";
import { getCollapseThreshold, shouldAutoCollapse } from "../utils/Comments";
import { updateNotification } from "../utils/notifications";
import { requireThemeColor } from "../utils/themeColor";
import { requireAccount } from "../utils/openBrowsing";
import useBalance from "./useBalance.js";
import { formatMirageCompact } from "../utils/formatters";
import { peekBootstrapStashAfterBootstrap, readBootstrapStash } from "../utils/bootstrapStash";
import { communityLabel } from "../utils/community";
import { LENS, lensQuery } from "../utils/curation";
import { signPlainPayload } from "../utils/signPlain";
export const pickCard = requireThemeColor;

function commentsLensParams(lens, teamId) {
    if (lens === LENS.TEAM) return lensQuery(lens, teamId);
    return lensQuery(lens || LENS.EFFECTIVE, null);
}

// Card-based container matching front page style (width aligned with ModernPostFeed)
// Supports $size prop ('compact' or 'large') to match feed view mode
// No margins - ModernPostFeed's gap handles spacing (matches CardView behavior)
export const tagColors = {
    adult: {
        bg: 'rgba(236, 72, 153, 0.18)',
        border: 'rgba(236, 72, 153, 0.50)',
        text: '#ec4899'
    },
    // pink
    violence: {
        bg: 'rgba(185, 28, 28, 0.18)',
        border: 'rgba(185, 28, 28, 0.50)',
        text: '#b91c1c'
    },
    // deep red
    sensitive: {
        bg: 'rgba(109, 40, 217, 0.18)',
        border: 'rgba(109, 40, 217, 0.50)',
        text: '#6d28d9'
    },
    // purple
    // Default: light neutral pill that stays legible on both light and dark backgrounds.
    default: {
        bg: '#e5e7eb',
        border: '#cbd5e1',
        text: '#0f172a'
    }
};

// Returns absolute local timestamp: YYYY-MM-DD HH:MM:SS
export const formatTimeStamp = utcTimestamp => {
    if (utcTimestamp === undefined) return "n/a";
    const utcDate = new Date(utcTimestamp * 1000);
    const localDate = new Date(utcDate.getTime() - utcDate.getTimezoneOffset() * 60000);
    const isoDate = localDate.toISOString().slice(0, 10);
    const isoTime = localDate.toISOString().slice(11, 19);
    return `${isoDate} ${isoTime}`;
};

// Returns short relative time like 5s, 12m, 3h, 2d, 1y
export const formatElapsed = utcTimestamp => {
    if (!utcTimestamp && utcTimestamp !== 0) return "0s";
    let seconds = Math.floor(Date.now() / 1000 - utcTimestamp);
    if (!isFinite(seconds) || isNaN(seconds) || seconds < 0) seconds = 0;
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    if (seconds < 31536000) return `${Math.floor(seconds / 86400)}d`;
    return `${Math.floor(seconds / 31536000)}y`;
};

// Module-level cache for highlight ID (survives React Strict Mode double-mount)
export let _cachedHighlightPostId = null;
export let _highlightConsumed = false;
export function useViewPost({
    state,
    updatePost,
    lens = LENS.EFFECTIVE,
    teamId = null,
}) {
    const threadLensRef = useRef({ lens, teamId });
    threadLensRef.current = { lens, teamId };
    const [root, setRoot] = useState({});
    const [children, setChildren] = useState([]);
    const [loading, setLoading] = useState(true);
    const [blockError, setBlockError] = useState('');
    const [blockSuccess, setBlockSuccess] = useState('');
    const [isBlocking, setIsBlocking] = useState(false);
    const [confirmBlockPost, setConfirmBlockPost] = useState(null);
    const [confirmBlockUser, setConfirmBlockUser] = useState(null); // { userId, postId }
    const [confirmBlockTopic, setConfirmBlockTopic] = useState(null); // { topic, postId }
    const [confirmDeletePost, setConfirmDeletePost] = useState(null);
    const [isDeleting, setIsDeleting] = useState(false);
    const [deleteMessages, setDeleteMessages] = useState({}); // { postId: { type: 'success'|'error', message: string } }
    const [deletedPosts, setDeletedPosts] = useState(new Set()); // Track successfully deleted posts to hide them
    const [confirmDonate, setConfirmDonate] = useState(null); // { userId, postId }
    const [donateAmount, setDonateAmount] = useState("10000");
    const [donateMessages, setDonateMessages] = useState({}); // { postId: { type: 'success'|'error', message: string } }
    const [giftSubMessages, setGiftSubMessages] = useState({}); // { postId: { type: 'success'|'error', message: string } }
    const [confirmGiftSub, setConfirmGiftSub] = useState(null); // { userId, postId }
    const [confirmAward, setConfirmAward] = useState(null); // { postId }
    const [isAwarding, setIsAwarding] = useState(false);
    const [awardMessages, setAwardMessages] = useState({}); // { postId: { type, message } }
    const [confirmReportPost, setConfirmReportPost] = useState(null);
    const [reportReason, setReportReason] = useState("");
    const [isReporting, setIsReporting] = useState(false);
    const [reportMessages, setReportMessages] = useState({}); // { postId: { type: 'success'|'error', message: string } }
    const [error, setError] = useState(null);
    const [shareMessages, setShareMessages] = useState({}); // { postId: { type: 'success', message } }
    // Ancestor chain from get_comments (root-first, ending at immediate parent)
    const [ancestors, setAncestors] = useState([]);
    const [ancestorsOmitted, setAncestorsOmitted] = useState(0);
    const [lastVisitTs, setLastVisitTs] = useState(null);
    // Card size state to match feed view mode (compact or large)
    const [cardSize, setCardSize] = useState(() => {
        try {
            return Storage.load('card_size', 'compact');
        } catch (_) {
            return 'compact';
        }
    });
    const theme = useTheme();
    const location = useLocation();
    const navigate = useNavigate();
    const [configUpdateTrigger, setConfigUpdateTrigger] = useState(0);
    const [subToggleTick, setSubToggleTick] = useState(0);
    useEffect(() => { }, [subToggleTick]);
    const [nodeConfigTick, setNodeConfigTick] = useState(0);
    useEffect(() => {
        const handler = () => setNodeConfigTick(prev => prev + 1);
        window.addEventListener('nodeConfigUpdated', handler);
        // Cold-load race: /api/bootstrap can dispatch 'nodeConfigUpdated' before
        // this listener attaches (passive effects are deferred while the bundle
        // parses). If the config already landed in storage, force a re-read so
        // openBrowsingEnabled doesn't stay stuck false on a first visit.
        try {
            if (localStorage.getItem('nodeConfig') != null) setNodeConfigTick(prev => prev + 1);
        } catch (_) { }
        return () => window.removeEventListener('nodeConfigUpdated', handler);
    }, []);
    const nodeConfig = useMemo(() => {
        void nodeConfigTick;
        try {
            const raw = localStorage.getItem('nodeConfig');
            return raw ? JSON.parse(raw) : null;
        } catch (_) {
            return null;
        }
    }, [nodeConfigTick]);
    const openBrowsingEnabled = Boolean(nodeConfig?.open_browsing_enabled);

    // Capture "opened from feed" info synchronously (before effects) so the Back button can
    // reliably return to the originating feed route (including /t/:topic).
    const openedFromFeedInfoRef = useRef(null);
    if (openedFromFeedInfoRef.current === null) {
        openedFromFeedInfoRef.current = (() => {
            try {
                if (typeof window === 'undefined' || !window.sessionStorage) return {
                    opened: false,
                    topic: null
                };
                const raw = window.sessionStorage.getItem('mirage_post_nav_source');
                if (!raw) return {
                    opened: false,
                    topic: null
                };
                const parsed = JSON.parse(raw);
                if (parsed?.source !== 'feed') return {
                    opened: false,
                    topic: null
                };
                const at = Number(parsed?.at || 0);
                if (!Number.isFinite(at) || at <= 0) return {
                    opened: false,
                    topic: null
                };
                const ageMs = Date.now() - at;
                if (ageMs < 0 || ageMs > 10000) return {
                    opened: false,
                    topic: null
                };
                const topic = typeof parsed?.topic === 'string' ? parsed.topic : null;
                return {
                    opened: true,
                    topic: topic || null
                };
            } catch (_) {
                return {
                    opened: false,
                    topic: null
                };
            }
        })();
    }

    // Mobile detection for focused reply mode
    const [isMobile, setIsMobile] = useState(() => {
        if (typeof window === 'undefined') return false;
        try {
            return window.innerWidth <= 600;
        } catch (_) {
            return false;
        }
    });
    useEffect(() => {
        const updateIsMobile = () => {
            try {
                setIsMobile(window.innerWidth <= 600);
            } catch (_) { }
        };
        window.addEventListener('resize', updateIsMobile);
        window.addEventListener('orientationchange', updateIsMobile);
        return () => {
            window.removeEventListener('resize', updateIsMobile);
            window.removeEventListener('orientationchange', updateIsMobile);
        };
    }, []);

    // Listen for card size changes from other views (MainView settings dropdown)
    useEffect(() => {
        const handleSettingsUpdated = e => {
            try {
                if (e && e.detail && typeof e.detail.cardSize !== 'undefined') {
                    setCardSize(e.detail.cardSize);
                    return;
                }
                // Fallback: re-read from storage
                const size = Storage.load('card_size', 'compact');
                setCardSize(size);
            } catch (_) { }
        };
        window.addEventListener('settingsUpdated', handleSettingsUpdated);
        return () => window.removeEventListener('settingsUpdated', handleSettingsUpdated);
    }, []);

    // Set CSS custom properties for card gap based on compact mode (matches CardView)
    useEffect(() => {
        const isCompactMode = cardSize === 'compact';
        const root = document.documentElement;
        const gap = isCompactMode ? '0.5rem' : '1.0rem';
        const gapMobile = isCompactMode ? '0.25rem' : '0.5rem';
        root.style.setProperty('--card-gap', gap);
        root.style.setProperty('--card-gap-mobile', gapMobile);
    }, [cardSize]);

    // Scroll to top instantly when navigating to this view (skip for focused comment views —
    // those scroll to the target comment after all context loads)
    useEffect(() => {
        const params = new URLSearchParams(location.search);
        if (params.has('depth')) return;
        window.scrollTo({
            top: 0,
            behavior: 'instant'
        });
    }, [location.search]);

    // If this post wasn't opened from the feed, clear any stale "came from feed" flag.
    // We only want feed restoration for browser-back when the user navigated feed -> post view.
    useEffect(() => {
        const openedFromFeed = openedFromFeedInfoRef.current?.opened === true;
        try {
            sessionStorage.removeItem('mirage_post_nav_source');
        } catch (_) { }
        if (!openedFromFeed) {
            try {
                sessionStorage.removeItem('mirage_came_from_feed');
            } catch (_) { }
        }
    }, []); // Only run on mount

    const goBackToFeed = () => {
        try {
            // Prefer browser back when we actually navigated here from a feed
            // (/home, /following, /c/:community). Preserves MainView scroll restore.
            if (openedFromFeedInfoRef.current?.opened === true) {
                console.debug('[ViewPost] back via history (opened from feed)', {
                    topic: openedFromFeedInfoRef.current?.topic || null,
                });
                navigate(-1);
                return;
            }
            if (typeof window !== 'undefined' && window.history.length > 1) {
                try {
                    const cameFrom = window.sessionStorage.getItem('mirage_post_referrer');
                    if (cameFrom === 'search' || cameFrom === 'profile') {
                        window.sessionStorage.removeItem('mirage_post_referrer');
                        navigate(-1);
                        return;
                    }
                } catch (_) { }
            }
            const last = Storage.load('last_feed_route', '');
            const postCommunity = String(root?.topic || root?.root_topic || '').trim().toLowerCase();
            // last_feed_route only started tracking /c/ after v1.39; a stale
            // "/home" here would strand community readers on the wrong feed.
            let target = typeof last === 'string' && last.startsWith('/') ? last : '';
            if (!target || target === '/home' || target === '/') {
                if (postCommunity) target = `/c/${encodeURIComponent(postCommunity)}`;
                else target = '/home';
            }
            const inferTopicIntent = route => {
                try {
                    if (openedFromFeedInfoRef.current?.topic) return openedFromFeedInfoRef.current.topic;
                    if (route === '/home') return 'home';
                    if (route === '/following') return 'following';
                    if (route.startsWith('/c/') || route.startsWith('/t/')) {
                        const withoutPrefix = route.slice(3);
                        const segment = withoutPrefix.split('?')[0].split('#')[0].split('/')[0];
                        const trimmed = String(segment || '').trim();
                        if (!trimmed) return null;
                        return decodeURIComponent(trimmed);
                    }
                    return null;
                } catch (_) {
                    return null;
                }
            };
            const intendedTopic = inferTopicIntent(target) || postCommunity || null;
            try {
                if (typeof window !== 'undefined' && window.sessionStorage) {
                    if (intendedTopic) {
                        window.sessionStorage.setItem('mirage_restore_feed', JSON.stringify({
                            topic: intendedTopic,
                            at: Date.now()
                        }));
                    }
                }
            } catch (_) { }
            console.debug('[ViewPost] back via last_feed_route', {
                target,
                last: last || null,
                postCommunity: postCommunity || null,
            });
            navigate(target, {
                replace: true
            });
        } catch (_) {
            navigate('/home', {
                replace: true
            });
        }
    };
    const viewerAddress = Storage.load('publicKey', '') || 'guest';
    const [followedAuthorsSet, setFollowedAuthorsSet] = useState(new Set());
    const [followedTopicsSet, setFollowedTopicsSet] = useState(new Set());
    const [topicFollowHover, setTopicFollowHover] = useState(false);
    const {
        isTopicPending,
        isUserPending,
        formatTopicStatus,
        formatUserStatus
    } = usePendingFollows();
    const {
        isPending: isSendPending,
        formatStatus: formatSendStatus
    } = usePendingSends();
    const {
        isPending: isSubscribePending,
        formatStatus: formatSubscribeStatus
    } = usePendingSubscribes();

    // Menu state for three-dots dropdown
    const [openMenuId, setOpenMenuId] = useState(null);
    const [menuPosition, setMenuPosition] = useState({
        top: 0,
        left: 0
    });
    const menuButtonRefs = useRef({});
    const menuDropdownRef = useRef({});

    // Close menu when clicking outside
    useEffect(() => {
        if (!openMenuId) return;
        const handleClickOutside = event => {
            const dropdown = menuDropdownRef.current;
            const button = menuButtonRefs.current[openMenuId];
            if (dropdown && !dropdown.contains(event.target) && button && !button.contains(event.target)) {
                setOpenMenuId(null);
            }
        };
        const handleScroll = () => setOpenMenuId(null);
        document.addEventListener('mousedown', handleClickOutside);
        window.addEventListener('scroll', handleScroll, true);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            window.removeEventListener('scroll', handleScroll, true);
        };
    }, [openMenuId]);
    useEffect(() => {
        let cancelled = false;
        const loadFollowed = async () => {
            if (!viewerAddress || viewerAddress === 'guest') return;
            try {
                const [authors, topics] = await Promise.all([fetchFollowedUsers(viewerAddress), fetchFollowedTopics(viewerAddress)]);
                if (!cancelled) {
                    setFollowedAuthorsSet(new Set(authors.map(a => a.toLowerCase())));
                    setFollowedTopicsSet(new Set(topics.map(t => t.toLowerCase())));
                }
            } catch (_) { }
        };
        loadFollowed();
        return () => {
            cancelled = true;
        };
    }, [viewerAddress]);
    const isFollowingAuthor = addr => {
        const a = String(addr || '').trim().toLowerCase();
        return followedAuthorsSet.has(a);
    };
    const handleFollowToggle = async authorAddr => {
        const author = String(authorAddr || '').trim().toLowerCase();
        if (!author || isUserPending(author)) return;
        if (!requireAccount('follow users')) return;
        const wasFollowing = isFollowingAuthor(author);
        try {
            if (wasFollowing) {
                await unfollowAuthor(viewerAddress, author);
                setFollowedAuthorsSet(prev => {
                    const next = new Set(prev);
                    next.delete(author);
                    return next;
                });
                updateNotification(`Unfollowed user ${author.slice(0, 12)}…`);
            } else {
                await followAuthor(viewerAddress, author);
                setFollowedAuthorsSet(prev => new Set([...prev, author]));
                updateNotification(`Now following user ${author.slice(0, 12)}…`);
            }
            invalidateFollowCache();
            setSubToggleTick(x => x + 1);
        } catch (e) {
            console.error('[ViewPostView] Follow toggle error:', e);
        }
    };
    const isSubscribedTopic = topic => {
        return followedTopicsSet.has(String(topic || '').toLowerCase());
    };
    const handleTopicFollowToggle = async topic => {
        const t = String(topic || '').trim().toLowerCase();
        if (!t || isTopicPending(t)) return;
        if (!requireAccount('join communities')) return;
        const wasSubscribed = isSubscribedTopic(topic);
        // Optimistic update
        if (wasSubscribed) {
            setFollowedTopicsSet(prev => {
                const next = new Set(prev);
                next.delete(t);
                return next;
            });
        } else {
            setFollowedTopicsSet(prev => new Set([...prev, t]));
        }
        try {
            if (wasSubscribed) {
                await unsubscribe(viewerAddress, topic);
                updateNotification(`Left ${communityLabel(t)}`);
            } else {
                await subscribe(viewerAddress, topic);
                updateNotification(`Joined ${communityLabel(t)}`);
            }
            invalidateTopicsCache();
            setSubToggleTick(x => x + 1);
        } catch (e) {
            console.error('[ViewPostView] Community membership toggle error:', e);
            // Revert on error
            if (wasSubscribed) {
                setFollowedTopicsSet(prev => new Set([...prev, t]));
            } else {
                setFollowedTopicsSet(prev => {
                    const next = new Set(prev);
                    next.delete(t);
                    return next;
                });
            }
        }
    };
    const [replyDragState, setReplyDragState] = useState({}); // { postId: boolean }
    const [replyUploadProgress, setReplyUploadProgress] = useState({}); // { postId: number }
    const [replyEditorUpload, setReplyEditorUpload] = useState({}); // { postId: api }
    const [replyIsUploading, setReplyIsUploading] = useState({}); // { postId: boolean }
    const [replyAttachedType, setReplyAttachedType] = useState({}); // { postId: 'image'|'video' }
    const [replyAttachedUrl, setReplyAttachedUrl] = useState({}); // { postId: string }
    const [replyThumbLoading, setReplyThumbLoading] = useState({}); // { postId: boolean }
    const [replySubmitError, setReplySubmitError] = useState({}); // { postId: string }
    const [replySubmitStartTime, setReplySubmitStartTime] = useState({}); // { postId: number }
    const [, setReplyElapsedTime] = useState({}); // { postId: number }
    const [replySubmitStatus, setReplySubmitStatus] = useState({}); // { postId: 'idle'|'solving'|'submitting'|'verifying' }
    const replyErrorClearTimeoutRef = useRef({}); // { postId: timeoutId }
    const mobileReplyOverlayRef = useRef(null);

    // Listen for chain config updates and fetch lazily if not cached
    useEffect(() => {
        const handleConfigUpdate = () => {
            setConfigUpdateTrigger(prev => prev + 1);
        };
        window.addEventListener('chainConfigUpdated', handleConfigUpdate);
        window.addEventListener('userStatusUpdated', handleConfigUpdate);
        if (tx.needsChainConfigRefresh()) {
            Api.get('get_chain_config', undefined).then(cfg => {
                if (cfg) try {
                    tx.cacheChainConfig(cfg);
                } catch (_) { }
            }).catch(() => { });
        }
        return () => {
            window.removeEventListener('chainConfigUpdated', handleConfigUpdate);
            window.removeEventListener('userStatusUpdated', handleConfigUpdate);
        };
    }, []);

    // Update elapsed time for any active reply submissions
    useEffect(() => {
        const activePostIds = Object.keys(replySubmitStartTime).filter(id => replySubmitStartTime[id] && state.posts[id]?.replyBusy);
        if (activePostIds.length === 0) return;
        const interval = setInterval(() => {
            setReplyElapsedTime(prev => {
                const next = {
                    ...prev
                };
                for (const id of activePostIds) {
                    const start = replySubmitStartTime[id];
                    if (start) {
                        next[id] = (Date.now() - start) / 1000;
                    }
                }
                return next;
            });
        }, 100);
        return () => clearInterval(interval);
    }, [replySubmitStartTime, state.posts]);

    // Scroll mobile reply overlay to bottom (reply box) when opened
    useEffect(() => {
        if (mobileReplyOverlayRef.current) {
            requestAnimationFrame(() => {
                if (mobileReplyOverlayRef.current) {
                    mobileReplyOverlayRef.current.scrollTop = mobileReplyOverlayRef.current.scrollHeight;
                }
            });
        }
    }, [state.posts, isMobile]);

    // Get content size limits from chain config + user level
    const limits = React.useMemo(() => {
        try {
            const chain = JSON.parse(localStorage.getItem('chainConfig') || '{}');
            const userLevel = parseInt(Storage.load('user_level', '0'));
            const tiers = chain.tiers || [];
            // Free=0, Subscriber=1, Admin(>=100)=2 — matches LevelToTierIndex.
            const tierIndex = userLevel === 0 ? 0 : userLevel >= 100 ? 2 : 1;
            const isAdmin = userLevel >= 100;
            const tier = tiers[tierIndex] || tiers[tiers.length - 1] || {};
            let maxContent = parseInt(tier.max_content_length) || 0;
            if (!maxContent) maxContent = 1000;
            return {
                maxContent,
                willPayFee: userLevel >= 1,
                isAdmin
            };
        } catch (e) {
            console.error('[ViewPostView] Error calculating limits:', e);
            return {
                maxContent: 1000,
                willPayFee: false,
                isAdmin: false
            };
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [state.user_balance, configUpdateTrigger]);
    const closeReply = postId => {
        try {
            const api = replyEditorUpload[postId];
            if (api && typeof api.cancelUpload === 'function') {
                api.cancelUpload();
            }
        } catch (_) {/* noop */ }
        try {
            setReplyIsUploading(prev => ({
                ...prev,
                [postId]: false
            }));
            setReplyUploadProgress(prev => {
                const next = {
                    ...prev
                };
                delete next[postId];
                return next;
            });
            setReplyAttachedType(prev => {
                const next = {
                    ...prev
                };
                delete next[postId];
                return next;
            });
            setReplyAttachedUrl(prev => {
                const next = {
                    ...prev
                };
                delete next[postId];
                return next;
            });
            setReplyThumbLoading(prev => {
                const next = {
                    ...prev
                };
                delete next[postId];
                return next;
            });
            // Clear any error and pending timeout
            setReplySubmitError(prev => {
                const next = {
                    ...prev
                };
                delete next[postId];
                return next;
            });
            try {
                const t = replyErrorClearTimeoutRef.current?.[postId];
                if (t) {
                    clearTimeout(t);
                    delete replyErrorClearTimeoutRef.current[postId];
                }
            } catch (_) {/* noop */ }
        } catch (_) {/* noop */ }
        updatePost(postId, {
            replyOpen: false,
            replyMode: undefined,
            replyText: ""
        });
    };
    const closeAllReplies = () => {
        Object.keys(state.posts || {}).forEach(id => {
            if (state.posts[id]?.replyOpen) {
                updatePost(id, {
                    replyOpen: false,
                    replyMode: undefined
                });
            }
        });
    };
    const toggleReply = postId => {
        // Clear any open confirmations when opening reply
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmDeletePost(null);
        setConfirmReportPost(null);
        setConfirmDonate(null);
        clearBlockMessages();
        let replyOpenState = state.posts[postId]?.replyOpen || false;
        if (!replyOpenState) {
            closeAllReplies();
        }
        updatePost(postId, {
            replyOpen: !replyOpenState,
            replyMode: undefined
        });
    };
    const clearBlockMessages = () => {
        setBlockError('');
        setBlockSuccess('');
    };
    const showBlockError = message => {
        setBlockError(message);
        setBlockSuccess('');
        setTimeout(() => setBlockError(''), 5000);
    };
    const showBlockSuccess = message => {
        setBlockSuccess(message);
        setBlockError('');
        setTimeout(() => setBlockSuccess(''), 3000);
    };
    const handleBlockPost = postId => {
        if (!postId) {
            showBlockError("Invalid post ID");
            return;
        }
        clearBlockMessages();
        setConfirmReportPost(null);
        setConfirmDeletePost(null);
        setConfirmDonate(null);
        setConfirmBlockUser(null); // Cancel any user block confirmation
        setConfirmBlockPost(postId);
        // Close reply box for this post
        try {
            updatePost(postId, {
                replyOpen: false
            });
        } catch (_) { }
    };
    const confirmBlockPostAction = async () => {
        const postId = confirmBlockPost;
        setConfirmBlockPost(null);
        setIsBlocking(true);
        try {
            const result = await tx.blockPost(postId, true);
            if (result.success) {
                showBlockSuccess("Post blocked successfully!");
            } else {
                showBlockError(`Failed to block post: ${result.error}`);
            }
        } catch (error) {
            console.error("Block post error:", error);
            showBlockError(`Error: ${error.message || error}`);
        } finally {
            setIsBlocking(false);
        }
    };
    const cancelBlockPost = () => {
        setConfirmBlockPost(null);
        clearBlockMessages();
    };
    const handleBlockUser = (userAddress, postId) => {
        if (!userAddress) {
            showBlockError("Invalid user address");
            return;
        }
        clearBlockMessages();
        setConfirmBlockPost(null); // Cancel any post block confirmation
        setConfirmReportPost(null);
        setConfirmDeletePost(null);
        setConfirmDonate(null);
        setConfirmBlockUser({
            userId: userAddress,
            postId
        });
        // Close reply box for root (if any)
        try {
            if (root && root.post_id) updatePost(root.post_id, {
                replyOpen: false
            });
        } catch (_) { }
    };
    const confirmBlockUserAction = async () => {
        const userAddress = confirmBlockUser?.userId;
        setConfirmBlockUser(null);
        setIsBlocking(true);
        try {
            const result = await tx.blockUser(userAddress, true);
            if (result.success) {
                showBlockSuccess("User blocked successfully!");
            } else {
                showBlockError(`Failed to block user: ${result.error}`);
            }
        } catch (error) {
            console.error("Block user error:", error);
            showBlockError(`Error: ${error.message || error}`);
        } finally {
            setIsBlocking(false);
        }
    };
    const cancelBlockUser = () => {
        setConfirmBlockUser(null);
        clearBlockMessages();
    };
    const handleBlockTopic = (topicName, postId) => {
        const t = (topicName || "").trim().toLowerCase();
        if (!t) {
            showBlockError("Invalid community");
            return;
        }
        clearBlockMessages();
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmReportPost(null);
        setConfirmDeletePost(null);
        setConfirmDonate(null);
        setConfirmBlockTopic({
            topic: t,
            postId
        });
    };
    const confirmBlockTopicAction = async () => {
        const topicName = confirmBlockTopic?.topic;
        setConfirmBlockTopic(null);
        setIsBlocking(true);
        try {
            const result = await tx.blockTopic(topicName);
            if (result.success) {
                showBlockSuccess("Community blocked successfully!");
            } else {
                showBlockError(`Failed to block community: ${result.error}`);
            }
        } catch (error) {
            console.error("Block community error:", error);
            showBlockError(`Error: ${error.message || error}`);
        } finally {
            setIsBlocking(false);
        }
    };
    const cancelBlockTopic = () => {
        setConfirmBlockTopic(null);
        clearBlockMessages();
    };
    const handleReport = postId => {
        if (!postId) {
            showBlockError("Invalid post ID");
            return;
        }
        clearBlockMessages();
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmDeletePost(null);
        setConfirmDonate(null);
        setReportReason("");
        setConfirmReportPost(postId);
        try {
            updatePost(postId, {
                replyOpen: false
            });
        } catch (_) { }
    };
    const confirmReportAction = async () => {
        const postId = confirmReportPost;
        const reason = (reportReason || "").trim().slice(0, 200);
        setConfirmReportPost(null);
        setIsReporting(true);
        if (!reason) {
            setReportMessages(prev => ({
                ...prev,
                [postId]: {
                    type: 'error',
                    message: 'Reason is required'
                }
            }));
            setTimeout(() => setReportMessages(prev => {
                const n = {
                    ...prev
                };
                delete n[postId];
                return n;
            }), 5000);
            setIsReporting(false);
            return;
        }
        try {
            const result = await tx.reportPost(postId, reason);
            if (result && result.success) {
                setReportMessages(prev => ({
                    ...prev,
                    [postId]: {
                        type: 'success',
                        message: 'Report submitted'
                    }
                }));
                setTimeout(() => setReportMessages(prev => {
                    const n = {
                        ...prev
                    };
                    delete n[postId];
                    return n;
                }), 5000);
            } else {
                setReportMessages(prev => ({
                    ...prev,
                    [postId]: {
                        type: 'error',
                        message: `Failed: ${result && result.error ? result.error : 'unknown error'}`
                    }
                }));
                setTimeout(() => setReportMessages(prev => {
                    const n = {
                        ...prev
                    };
                    delete n[postId];
                    return n;
                }), 5000);
            }
        } catch (e) {
            setReportMessages(prev => ({
                ...prev,
                [postId]: {
                    type: 'error',
                    message: `Error: ${e && e.message ? e.message : e}`
                }
            }));
            setTimeout(() => setReportMessages(prev => {
                const n = {
                    ...prev
                };
                delete n[postId];
                return n;
            }), 5000);
        } finally {
            setIsReporting(false);
        }
    };
    const cancelReport = () => {
        setConfirmReportPost(null);
        setReportReason("");
    };
    const handleDeletePost = postId => {
        if (!postId) {
            showBlockError("Invalid post ID");
            return;
        }
        clearBlockMessages();
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmReportPost(null);
        setConfirmDonate(null);
        setConfirmDeletePost(postId);
        try {
            updatePost(postId, {
                replyOpen: false
            });
        } catch (_) { }
    };
    const confirmDeletePostAction = async () => {
        const postId = confirmDeletePost;
        setConfirmDeletePost(null);
        setIsDeleting(true);

        // Check if this is the root post or a comment
        const isRootPost = postId === root.post_id;
        try {
            const result = await tx.deletePost(postId);
            if (result.success) {
                // Set success message for this specific post
                setDeleteMessages(prev => ({
                    ...prev,
                    [postId]: {
                        type: 'success',
                        message: 'Post deleted successfully!'
                    }
                }));

                // Clear the message and hide the post after 3 seconds
                setTimeout(() => {
                    setDeleteMessages(prev => {
                        const updated = {
                            ...prev
                        };
                        delete updated[postId];
                        return updated;
                    });

                    // If it's the root post, redirect to home
                    if (isRootPost) {
                        navigate('/');
                    } else {
                        // Hide the comment and all its descendants from the list
                        const descendants = findAllDescendantPostIds(postId, children);
                        setDeletedPosts(prev => new Set([...prev, postId, ...descendants]));
                    }
                }, 3000);
            } else {
                // Set error message for this specific post
                setDeleteMessages(prev => ({
                    ...prev,
                    [postId]: {
                        type: 'error',
                        message: `Failed to delete post: ${result.error}`
                    }
                }));
                setTimeout(() => {
                    setDeleteMessages(prev => {
                        const updated = {
                            ...prev
                        };
                        delete updated[postId];
                        return updated;
                    });
                }, 3000);
            }
        } catch (error) {
            console.error("Delete post error:", error);
            setDeleteMessages(prev => ({
                ...prev,
                [postId]: {
                    type: 'error',
                    message: `Error: ${error.message || error}`
                }
            }));
            setTimeout(() => {
                setDeleteMessages(prev => {
                    const updated = {
                        ...prev
                    };
                    delete updated[postId];
                    return updated;
                });
            }, 3000);
        } finally {
            setIsDeleting(false);
        }
    };
    const cancelDeletePost = () => {
        setConfirmDeletePost(null);
        clearBlockMessages();
    };
    const handleDonate = (userAddress, postId) => {
        if (!userAddress) {
            return;
        }
        const viewerAddress = Storage.load('publicKey', '');
        if (!viewerAddress || viewerAddress === 'guest') {
            alert('Please log in to donate');
            return;
        }
        // Resolve the target's username from whichever post in our tree
        // matches `postId` so the Gift Mirage dialog can show "@alice"
        // instead of the raw mirage1... wallet address.
        const targetPost = root && root.post_id === postId
            ? root
            : (children || []).find(c => c && c.post_id === postId);
        const targetUsername = targetPost && typeof targetPost.username === 'string'
            ? targetPost.username.trim()
            : '';
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmDeletePost(null);
        setConfirmReportPost(null);
        setConfirmGiftSub(null);
        setConfirmDonate({
            userId: userAddress,
            postId,
            username: targetUsername || null
        });
        try {
            if (postId) updatePost(postId, {
                replyOpen: false
            });
        } catch (_) { }
        setDonateAmount("10000"); // Reset to default
    };
    const handleGiftSubscription = (userAddress, postId, authorLevel) => {
        if (!userAddress) return;
        if (isSubscribePending(userAddress)) return;
        if (!viewerAddress || viewerAddress === 'guest') {
            alert('Please log in to gift a subscription');
            return;
        }
        const level = 1;
        console.debug('[ViewPostView] gift-subscribe.confirm', {
            target: userAddress,
            postId,
            level
        });
        // Resolve the target's username (see handleDonate for the same
        // lookup). Drives the "@alice" title in the Gift Subscription
        // dialog.
        const targetPost = root && root.post_id === postId
            ? root
            : (children || []).find(c => c && c.post_id === postId);
        const targetUsername = targetPost && typeof targetPost.username === 'string'
            ? targetPost.username.trim()
            : '';
        setOpenMenuId(null);
        setConfirmDonate(null);
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmDeletePost(null);
        setConfirmReportPost(null);
        setConfirmAward(null);
        setConfirmGiftSub({
            userId: userAddress,
            postId,
            level,
            username: targetUsername || null,
            loading: true,
            expiryLabel: null,
            error: null
        });
        void (async () => {
            let cfg = null;
            try {
                const raw = localStorage.getItem('chainConfig');
                cfg = raw ? JSON.parse(raw) : null;
            } catch (e) {
                console.debug('[ViewPostView] gift-subscribe.config-error', e);
            }
            if (!cfg || !Number(cfg.subscription_period || 0)) {
                try {
                    const fetched = await Api.get('get_chain_config', undefined);
                    if (fetched && typeof fetched === 'object') {
                        try {
                            tx.cacheChainConfig(fetched);
                        } catch (_) { }
                        cfg = fetched;
                    }
                } catch (e) {
                    console.debug('[ViewPostView] gift-subscribe.config-fetch-error', e);
                }
            }
            const periodMinutes = Number(cfg?.subscription_period || 0);
            if (!periodMinutes || periodMinutes <= 0) {
                console.debug('[ViewPostView] gift-subscribe.config-invalid', {
                    periodMinutes
                });
                setConfirmGiftSub(prev => prev && prev.userId === userAddress && prev.postId === postId ? {
                    ...prev,
                    loading: false,
                    error: 'Invalid subscription period'
                } : prev);
                return;
            }
            try {
                const pre = await Api.get('get_user_status', {
                    address: userAddress,
                    _cb: Date.now()
                });
                const currentExp = Number(pre?.subscription_expiry || 0);
                const nowSec = Math.floor(Date.now() / 1000);
                const isExtension = currentExp > nowSec;
                const base = Math.max(nowSec, currentExp);
                const expectedExp = base + periodMinutes * 60;
                const dateStr = new Date(expectedExp * 1000).toLocaleDateString(undefined, {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric'
                });
                const label = isExtension ? `Extend until ${dateStr}` : `Until ${dateStr}`;
                console.debug('[ViewPostView] gift-subscribe.expected', {
                    target: userAddress,
                    postId,
                    level,
                    currentExp,
                    expectedExp
                });
                setConfirmGiftSub(prev => prev && prev.userId === userAddress && prev.postId === postId ? {
                    ...prev,
                    loading: false,
                    expiryLabel: label,
                    error: null
                } : prev);
            } catch (e) {
                console.debug('[ViewPostView] gift-subscribe.status-error', e);
                setConfirmGiftSub(prev => prev && prev.userId === userAddress && prev.postId === postId ? {
                    ...prev,
                    loading: false,
                    error: 'Failed to load recipient status'
                } : prev);
            }
        })();
        try {
            if (postId) updatePost(postId, {
                replyOpen: false
            });
        } catch (_) { }
    };
    const confirmGiftSubAction = async () => {
        const userAddress = confirmGiftSub?.userId;
        const postId = confirmGiftSub?.postId;
        const giftLevel = confirmGiftSub?.level || 1;
        if (!userAddress) return;
        if (isSubscribePending(userAddress)) return;
        if (confirmGiftSub?.loading || confirmGiftSub?.error) return;
        const expiryLabel = confirmGiftSub?.expiryLabel || null;
        if (!expiryLabel) {
            setConfirmGiftSub(prev => prev ? {
                ...prev,
                error: 'Missing expected expiry'
            } : prev);
            return;
        }
        try {
            console.debug('[ViewPostView] gift-subscribe.submit', {
                target: userAddress,
                postId,
                level: giftLevel
            });
            const result = await tx.subscribe(giftLevel, 0, userAddress);
            setConfirmGiftSub(null);
            if (result.success) {
                let msg = 'Subscription gifted!';
                msg += ` ${expiryLabel}`;
                setGiftSubMessages(prev => ({
                    ...prev,
                    [postId]: {
                        type: 'success',
                        message: msg
                    }
                }));
            } else {
                const raw = String(result.error || 'Transaction failed');
                const friendly = raw.replace(/^HTTP \d+:\s*/i, '').replace(/^Failed:\s*/i, '');
                setGiftSubMessages(prev => ({
                    ...prev,
                    [postId]: {
                        type: 'error',
                        message: friendly
                    }
                }));
            }
        } catch (error) {
            setConfirmGiftSub(null);
            setGiftSubMessages(prev => ({
                ...prev,
                [postId]: {
                    type: 'error',
                    message: `${error.message || error}`
                }
            }));
        }
        setTimeout(() => {
            setGiftSubMessages(prev => {
                const next = {
                    ...prev
                };
                delete next[postId];
                return next;
            });
        }, 8000);
    };
    const cancelGiftSub = () => {
        console.debug('[ViewPostView] gift-subscribe.cancel', {
            target: confirmGiftSub?.userId || null,
            postId: confirmGiftSub?.postId || null
        });
        setConfirmGiftSub(null);
    };
    const {
        displayBalance: userBalanceUmirage
    } = useBalance();
    const AWARD_TYPES = [{
        name: 'quality_post',
        label: 'Quality Post Award',
        icon: '\uD83C\uDFC6'
    }, {
        name: 'original_content',
        label: 'Original Content Award',
        icon: '\uD83D\uDCA1'
    }, {
        name: 'based',
        label: 'Based AF Award',
        icon: '\uD83D\uDCAA'
    }, {
        name: 'receipts',
        label: 'Receipts Award',
        icon: '\uD83C\uDFF7\uFE0F'
    }];
    const awardConfigs = useMemo(() => {
        void configUpdateTrigger;
        try {
            const raw = localStorage.getItem('chainConfig');
            const cfg = raw ? JSON.parse(raw) : null;
            return cfg?.award_configs || [];
        } catch (_) {
            return [];
        }
    }, [configUpdateTrigger]);
    const giftSubscriptionLabel = 'Gift Subscription';
    const {
        subFeeLabel,
        agentFeeLabel,
        subFeeUmirage,
        agentFeeUmirage
    } = useMemo(() => {
        void configUpdateTrigger;
        try {
            const raw = localStorage.getItem('chainConfig');
            const cfg = raw ? JSON.parse(raw) : null;
            const tiers = cfg?.tiers || [];
            const sf = Number(tiers[1]?.period_fee || 0);
            const af = Number(tiers[2]?.period_fee || 0);
            return {
                subFeeLabel: sf > 0 ? formatMirageCompact(sf) + ' MIRAGE' : null,
                agentFeeLabel: af > 0 ? formatMirageCompact(af) + ' MIRAGE' : null,
                subFeeUmirage: sf > 0 ? sf : null,
                agentFeeUmirage: af > 0 ? af : null
            };
        } catch (_) { }
        return {
            subFeeLabel: null,
            agentFeeLabel: null,
            subFeeUmirage: null,
            agentFeeUmirage: null
        };
    }, [configUpdateTrigger]);
    const getAwardCost = name => {
        if (awardConfigs.length === 0) return null;
        const cfg = awardConfigs.find(c => c.name === name);
        return cfg ? Number(cfg.cost || 0) : null;
    };
    const handleGiveAward = postId => {
        setOpenMenuId(null);
        if (!postId) return;
        setConfirmDonate(null);
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmReportPost(null);
        setConfirmGiftSub(null);
        setConfirmAward({
            postId
        });
        // Ensure the award_configs are available so the dialog doesn't
        // get stuck on "Loading…" — happens when the user lands on this
        // view via a deep link (e.g. profile → post) before App.js'
        // bootstrap fetch finished, or when that boot fetch returned an
        // empty payload. Mirrors the inline fetch used by `usePostGifts`.
        try {
            const raw = localStorage.getItem('chainConfig');
            const cfg = raw ? JSON.parse(raw) : null;
            const hasAwards = Array.isArray(cfg?.award_configs) && cfg.award_configs.length > 0;
            if (!hasAwards) {
                Api.get('get_chain_config', undefined)
                    .then(fetched => {
                        if (fetched && typeof fetched === 'object') {
                            try { tx.cacheChainConfig(fetched); } catch (_) { }
                        } else {
                            try { tx.releaseChainConfigClaim && tx.releaseChainConfigClaim(); } catch (_) { }
                        }
                    })
                    .catch(() => {
                        try { tx.releaseChainConfigClaim && tx.releaseChainConfigClaim(); } catch (_) { }
                    });
            }
        } catch (_) { /* noop */ }
        setTimeout(() => {
            const el = document.getElementById(`comment-${postId.toLowerCase()}`);
            if (el) el.scrollIntoView({
                behavior: 'smooth',
                block: 'center'
            });
        }, 50);
    };
    const friendlyAwardError = raw => {
        const s = String(raw || '').toLowerCase();
        if (s.includes('already awarded')) return 'You already gave this post an award.';
        if (s.includes('insufficient') || s.includes('not enough')) return 'Not enough MIRAGE to give this award.';
        if (s.includes('own post') || s.includes('self-award')) return "You can't award your own post.";
        return raw || 'Something went wrong. Please try again.';
    };
    const applyAwardOptimistic = (postId, awardType, revert) => {
        const addAward = awards => {
            const prev = Array.isArray(awards) ? awards : [];
            if (revert) return revert;
            const existing = prev.find(a => a.type === awardType);
            return existing ? prev.map(a => a.type === awardType ? {
                ...a,
                count: (Number(a.count) || 0) + 1
            } : a) : [...prev, {
                type: awardType,
                count: 1
            }];
        };
        if (root && root.post_id === postId) {
            setRoot(prev => ({
                ...prev,
                awards: addAward(prev.awards)
            }));
        } else {
            setChildren(prev => prev.map(c => c.post_id === postId ? {
                ...c,
                awards: addAward(c.awards)
            } : c));
        }
        try {
            updatePost(postId, {
                awards: addAward((state.posts[postId] || {}).awards)
            });
        } catch (_) { }
    };
    const confirmAwardAction = async (postId, awardType) => {
        if (!postId || isAwarding) return;
        const costUmirage = getAwardCost(awardType);
        if (costUmirage == null) return;
        setIsAwarding(true);
        setConfirmAward(null);
        const targetPost = root && root.post_id === postId ? root : children.find(c => c.post_id === postId);
        const prevAwards = targetPost?.awards ? [...targetPost.awards] : [];

        // Optimistic: deduct balance + show award immediately
        if (costUmirage > 0) tx.adjustBalanceOptimistic(-costUmirage);
        applyAwardOptimistic(postId, awardType, null);
        try {
            const result = await tx.giveAward(postId, awardType);
            if (result.success) {
                const label = AWARD_TYPES.find(a => a.name === awardType)?.label || awardType;
                setAwardMessages(prev => ({
                    ...prev,
                    [postId]: {
                        type: 'success',
                        message: `${label} given!`
                    }
                }));
                setTimeout(() => setAwardMessages(prev => {
                    const n = {
                        ...prev
                    };
                    delete n[postId];
                    return n;
                }), 5000);
                tx.refreshBalance();
            } else {
                // Revert optimistic award + balance
                applyAwardOptimistic(postId, awardType, prevAwards);
                if (costUmirage > 0) tx.adjustBalanceOptimistic(costUmirage);
                tx.refreshBalance();
                const errMsg = friendlyAwardError(result.error);
                setAwardMessages(prev => ({
                    ...prev,
                    [postId]: {
                        type: 'error',
                        message: errMsg
                    }
                }));
                setTimeout(() => setAwardMessages(prev => {
                    const n = {
                        ...prev
                    };
                    delete n[postId];
                    return n;
                }), 5000);
            }
        } catch (error) {
            // Revert optimistic award + balance
            applyAwardOptimistic(postId, awardType, prevAwards);
            if (costUmirage > 0) tx.adjustBalanceOptimistic(costUmirage);
            tx.refreshBalance();
            const errMsg = friendlyAwardError(error.message || String(error));
            setAwardMessages(prev => ({
                ...prev,
                [postId]: {
                    type: 'error',
                    message: errMsg
                }
            }));
            setTimeout(() => setAwardMessages(prev => {
                const n = {
                    ...prev
                };
                delete n[postId];
                return n;
            }), 5000);
        }
        setIsAwarding(false);
    };
    const openEdit = post => {
        if (!post || !post.post_id) return;
        const isRoot = !!(post.title && String(post.title).trim() !== '');
        if (isRoot) {
            navigate(`/create_post?post_id=${post.post_id}&edit=true`);
            return;
        }
        // Comment edit: reuse reply box
        updatePost(post.post_id, {
            replyOpen: true,
            replyMode: 'edit',
            replyText: post.content || '',
            editBusy: false
        });
    };
    const closeEdit = postId => {
        if (!postId) return;
        updatePost(postId, {
            editOpen: false
        });
    };
    const handleEditSubmit = async post => {
        if (!post || !post.post_id) return;
        const isRoot = !!(post.title && String(post.title).trim() !== '');
        // For comments edited via reply box, pull from replyText; fallback to editText for safety
        const editedText = (state.posts[post.post_id]?.replyText || state.posts[post.post_id]?.editText || '').trim();
        // The edit box is the reply editor, so it carries the same GIF/sticker
        // picker and upload attachments — prepend them exactly like handleSubmit
        // does. Without this, swapping the GIF on a media-only comment leaves an
        // empty body and the save is silently dropped by the guard below.
        const attachedUrl = replyAttachedUrl[post.post_id];
        const newContent = attachedUrl
            ? (editedText ? `${attachedUrl}\n\n${editedText}` : attachedUrl)
            : editedText;
        const newTitle = (state.posts[post.post_id]?.editTitle || '').trim();
        console.debug('[ViewPostView] handleEditSubmit', {
            postId: post.post_id,
            textLen: editedText.length,
            attachedUrl: attachedUrl || null
        });
        if (newContent.length === 0) return;
        try {
            const changes = {
                target: post.target || '',
                topic: isRoot ? post.topic || '' : '',
                title: isRoot ? newTitle : '',
                content: newContent,
                tag: post && typeof post.tag === 'string' ? post.tag : '',
                media: Array.isArray(post && post.media) ? post.media : []
            };
            // Disable controls while PoW/broadcast happens
            try {
                updatePost(post.post_id, {
                    editBusy: true
                });
            } catch (_) { }
            const res = await tx.editPost(post.post_id, changes);
            if (res && res.success) {
                // Optimistically update UI: show new content and flash it
                try {
                    const nowTs = Math.floor(Date.now() / 1000);
                    updatePost(post.post_id, {
                        content: newContent,
                        flash: true,
                        edited_at: nowTs
                    });
                    // Clear flash after animation delay
                    setTimeout(() => {
                        try {
                            updatePost(post.post_id, {
                                flash: false
                            });
                        } catch (_) { }
                    }, 1250);
                } catch (_) { }
                // Close edit UIs
                closeEdit(post.post_id);
                closeReply(post.post_id);
            } else {
                alert(`Failed to edit: ${res && res.error ? res.error : 'unknown error'}`);
                try {
                    updatePost(post.post_id, {
                        editBusy: false
                    });
                } catch (_) { }
            }
        } catch (e) {
            alert(`Edit failed: ${e && e.message ? e.message : e}`);
            try {
                updatePost(post.post_id, {
                    editBusy: false
                });
            } catch (_) { }
        }
    };
    const confirmDonateAction = async () => {
        const userAddress = confirmDonate?.userId;
        const postId = confirmDonate?.postId;
        if (userAddress && isSendPending(userAddress)) {
            return;
        }
        const amount = parseInt(String(donateAmount || "").replace(/[^\d]/g, ""), 10);
        if (isNaN(amount) || amount < 10000) {
            if (postId) {
                setDonateMessages(prev => ({
                    ...prev,
                    [postId]: {
                        type: 'error',
                        message: 'Minimum donation is 10,000 MIRAGE'
                    }
                }));
                setTimeout(() => {
                    setDonateMessages(prev => {
                        const updated = {
                            ...prev
                        };
                        delete updated[postId];
                        return updated;
                    });
                }, 5000);
            }
            setConfirmDonate(null);
            return;
        }
        try {
            console.debug('[ViewPostView] donate.submit', {
                target: userAddress,
                amount
            });
            const result = await tx.sendTokens(userAddress, amount);
            setConfirmDonate(null);
            if (result.success) {
                if (postId) {
                    setDonateMessages(prev => ({
                        ...prev,
                        [postId]: {
                            type: 'success',
                            message: `Successfully sent ${Number(amount).toLocaleString()} MIRAGE!`
                        }
                    }));
                }
            } else {
                if (postId) {
                    setDonateMessages(prev => ({
                        ...prev,
                        [postId]: {
                            type: 'error',
                            message: `Failed: ${result.error}`
                        }
                    }));
                }
            }
            if (postId) {
                setTimeout(() => {
                    setDonateMessages(prev => {
                        const updated = {
                            ...prev
                        };
                        delete updated[postId];
                        return updated;
                    });
                }, 5000);
            }
        } catch (error) {
            console.error("Donate error:", error);
            setConfirmDonate(null);
            if (postId) {
                setDonateMessages(prev => ({
                    ...prev,
                    [postId]: {
                        type: 'error',
                        message: `Error: ${error.message || error}`
                    }
                }));
                setTimeout(() => {
                    setDonateMessages(prev => {
                        const updated = {
                            ...prev
                        };
                        delete updated[postId];
                        return updated;
                    });
                }, 5000);
            }
        }
    };
    const cancelDonate = () => {
        setConfirmDonate(null);
    };
    const handleDonateAmountChange = value => {
        setDonateAmount(String(value || '').replace(/[^\d]/g, ""));
    };
    const formatDonateAmount = value => {
        const digits = String(value || "").replace(/[^\d]/g, "");
        if (!digits) return "";
        return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    };

    // Recursively find all descendant post IDs of a given post
    const findAllDescendantPostIds = (postId, commentsTree) => {
        const descendantIds = [];
        const findDescendants = items => {
            for (const item of items) {
                if (item.children && item.children.length > 0) {
                    // First recurse into children to search deeper
                    findDescendants(item.children);
                }

                // If this item matches our target, collect all its descendants
                if (item.post_id === postId && item.children) {
                    const collectAll = childItems => {
                        for (const child of childItems) {
                            descendantIds.push(child.post_id);
                            if (child.children && child.children.length > 0) {
                                collectAll(child.children);
                            }
                        }
                    };
                    collectAll(item.children);
                }
            }
        };
        findDescendants(commentsTree);
        return descendantIds;
    };
    const handleReplyChange = (postId, value) => {
        updatePost(postId, {
            replyText: value
        });
    };
    const insertReplyImageUrl = (postId, url) => {
        const currentText = state.posts[postId]?.replyText || '';
        const separator = currentText && !currentText.endsWith('\n') && !currentText.endsWith(' ') ? ' ' : '';
        const newText = currentText + separator + url;
        handleReplyChange(postId, newText);
    };
    const handleReplyFileUpload = async (postId, file) => {
        const isImg = !!(file && typeof file.type === 'string' && file.type.startsWith('image/'));
        const isVid = !!(file && typeof file.type === 'string' && file.type.startsWith('video/'));
        if (!isImg && !isVid) {
            console.warn('[ViewPostView] Invalid file type for reply upload');
            return;
        }
        try {
            let mediaUrl;
            if (isImg) {
                mediaUrl = await uploadImage(file, progress => {
                    setReplyUploadProgress(prev => ({
                        ...prev,
                        [postId]: progress
                    }));
                });
            } else {
                const {
                    uploadVideo
                } = await import('../utils/VideoUpload');
                mediaUrl = await uploadVideo(file, progress => {
                    setReplyUploadProgress(prev => ({
                        ...prev,
                        [postId]: progress
                    }));
                });
            }
            insertReplyImageUrl(postId, mediaUrl);
            setReplyUploadProgress(prev => {
                const next = {
                    ...prev
                };
                delete next[postId];
                return next;
            });
        } catch (error) {
            console.error('[ViewPostView] Reply image upload failed:', error);
            setReplyUploadProgress(prev => {
                const next = {
                    ...prev
                };
                delete next[postId];
                return next;
            });
        }
    };
    const handleReplyDragOver = (postId, e) => {
        if (replyIsUploading[postId]) return; // Disable drag during upload
        e.preventDefault();
        e.stopPropagation();
        if (!replyDragState[postId]) {
            setReplyDragState(prev => ({
                ...prev,
                [postId]: true
            }));
        }
    };
    const handleReplyDragLeave = (postId, e) => {
        if (replyIsUploading[postId]) return; // Disable drag during upload
        e.preventDefault();
        e.stopPropagation();
        if (!e.currentTarget.contains(e.relatedTarget)) {
            setReplyDragState(prev => {
                const next = {
                    ...prev
                };
                delete next[postId];
                return next;
            });
        }
    };
    const handleReplyDrop = (postId, e) => {
        if (replyIsUploading[postId]) {
            e.preventDefault();
            e.stopPropagation();
            return; // Disable drop during upload
        }
        e.preventDefault();
        e.stopPropagation();
        setReplyDragState(prev => {
            const next = {
                ...prev
            };
            delete next[postId];
            return next;
        });
        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) {
            try {
                const api = replyEditorUpload[postId];
                if (api && typeof api.uploadFile === 'function') {
                    api.uploadFile(files[0]);
                    return;
                }
            } catch (_) { }
            handleReplyFileUpload(postId, files[0]);
        }
    };

    // const handleReplyFileInput = (postId, e) => {
    //     const files = Array.from(e.target.files || []);
    //     if (files.length > 0) {
    //         handleReplyFileUpload(postId, files[0]);
    //     }
    //     e.target.value = '';
    // };

    const handleSubmit = commentId => async event => {
        event.preventDefault();
        if (!requireAccount('comment')) return;
        const replyStringRaw = state.posts[commentId]?.replyText || "";
        let replyString = replyStringRaw.trim();
        // Prepend attached media URL if present (same behavior as create_post)
        try {
            const mediaUrl = replyAttachedUrl[commentId];
            if (mediaUrl) {
                replyString = `${mediaUrl}\n\n${replyString}`;
            }
        } catch (_) { }
        if (replyString === "" || replyString === null) return;
        if (replyString.length > limits.maxContent) {
            alert(`Comment too long (${replyString.length} > ${limits.maxContent} chars)`);
            return;
        }

        // Disable controls while PoW/broadcast happens
        try {
            updatePost(commentId, {
                replyBusy: true
            });
        } catch (_) { }
        setReplySubmitStartTime(prev => ({
            ...prev,
            [commentId]: Date.now()
        }));
        setReplySubmitStatus(prev => ({
            ...prev,
            [commentId]: 'solving'
        }));

        // Submit the comment and wait for completion
        try {
            const res = await tx.createCommentAsync(commentId, replyString);
            if (res && res.success) {
                try {
                    markPostReplied(commentId);
                } catch (_) { }
                // Clear reply text and attached state only on success
                try {
                    updatePost(commentId, {
                        replyText: ""
                    });
                } catch (_) { }
                try {
                    setReplyAttachedType(prev => {
                        const n = {
                            ...prev
                        };
                        delete n[commentId];
                        return n;
                    });
                    setReplyAttachedUrl(prev => {
                        const n = {
                            ...prev
                        };
                        delete n[commentId];
                        return n;
                    });
                    setReplyThumbLoading(prev => {
                        const n = {
                            ...prev
                        };
                        delete n[commentId];
                        return n;
                    });
                } catch (_) { }
                try {
                    const txHash = res && res.tx_hash ? String(res.tx_hash).toLowerCase() : "";
                    if (!txHash) throw new Error("missing tx hash");

                    // Immediately insert optimistic comment and close reply box
                    const viewerAddress = Storage.load("publicKey", "");

                    // Is the replied-to post part of the comment subtree currently on
                    // screen? In the focused single-comment view the actual root post
                    // (and any parent-chain context) are rendered ABOVE the focused
                    // comment, but `root`/`children` only hold the focused comment and
                    // its descendants. Replying to one of those out-of-view posts (e.g.
                    // the root post at the top) produces a comment that can never appear
                    // in this focused view, so we navigate to that post's own thread
                    // where the new reply is visible instead of silently dropping it.
                    const findTargetInChildren = nodes => {
                        if (!Array.isArray(nodes)) return false;
                        for (const n of nodes) {
                            if (n && n.post_id === commentId) return true;
                            if (n && n.children && findTargetInChildren(n.children)) return true;
                        }
                        return false;
                    };
                    const targetVisibleInTree = (root && root.post_id === commentId) || findTargetInChildren(children);
                    if (!targetVisibleInTree) {
                        console.log('[ViewPostView] Reply target is outside the focused view; verifying then navigating to its thread', {
                            commentId,
                            txHash
                        });
                        // Keep the reply box closed but show verifying status while we
                        // wait for the comment to be indexed, so the destination thread
                        // actually contains it when we land there.
                        try {
                            updatePost(commentId, {
                                replyOpen: false
                            });
                        } catch (_) { }
                        setReplySubmitStatus(prev => ({
                            ...prev,
                            [commentId]: 'verifying'
                        }));
                        try {
                            await tx.pollTxStatus(txHash);
                        } catch (_) { }
                        try {
                            updatePost(commentId, {
                                replyBusy: false
                            });
                        } catch (_) { }
                        try {
                            Storage.setPendingPostHighlight(txHash);
                        } catch (_) { }
                        navigate(`/p/${commentId}`);
                        return;
                    }

                    const optimisticComment = {
                        post_id: txHash,
                        user_id: viewerAddress,
                        username: Storage.load("username", ""),
                        content: replyString,
                        target: commentId,
                        timestamp: Math.floor(Date.now() / 1000),
                        points: 1,
                        comments: 0,
                        children: [],
                        user_vote: 1,
                        user_weight: 1,
                        _optimistic: true
                    };

                    // Insert into children - find parent and add as FIRST child (most recent first)
                    if (root && root.post_id === commentId) {
                        // Replying to root - insert at beginning of top-level children
                        setChildren(prev => [optimisticComment, ...prev]);
                        setRoot(prev => ({
                            ...prev,
                            comments: (prev.comments || 0) + 1
                        }));
                    } else {
                        // Replying to a comment - find parent and insert at beginning of its children
                        setChildren(prev => {
                            const insertComment = nodes => {
                                return nodes.map(node => {
                                    if (node.post_id === commentId) {
                                        return {
                                            ...node,
                                            children: [optimisticComment, ...(node.children || [])],
                                            comments: (node.comments || 0) + 1
                                        };
                                    }
                                    if (node.children && node.children.length > 0) {
                                        return {
                                            ...node,
                                            children: insertComment(node.children)
                                        };
                                    }
                                    return node;
                                });
                            };
                            return insertComment(prev);
                        });
                    }

                    // Close reply box immediately
                    try {
                        updatePost(commentId, {
                            replyOpen: false,
                            replyBusy: false
                        });
                    } catch (_) { }

                    // Flash and scroll to new comment
                    setTimeout(() => {
                        try {
                            updatePost(txHash, {
                                flash: true
                            });
                        } catch (_) { }
                        try {
                            const el = document.getElementById(`comment-${txHash}`);
                            if (el) el.scrollIntoView({
                                behavior: 'smooth',
                                block: 'center'
                            });
                        } catch (_) { }
                        setTimeout(() => {
                            try {
                                updatePost(txHash, {
                                    flash: false
                                });
                            } catch (_) { }
                        }, 700);
                    }, 50);

                    // Verify in background (don't block UI)
                    (async () => {
                        try {
                            const result = await tx.pollTxStatus(txHash);
                            if (result && result.success && result.indexed) {
                                const data = await Api.get('get_comments', {
                                    post_id: postId,
                                    address: viewerAddress,
                                    ...commentsLensParams(threadLensRef.current.lens, threadLensRef.current.teamId),
                                });
                                if (data && data.root && Array.isArray(data.ancestors) && ('ancestors_omitted' in data)) {
                                    try { Api.invalidate('get_comments'); } catch (_) { }
                                    setRoot(data.root);
                                    setChildren(data.children || []);
                                    setAncestors(data.ancestors);
                                    setAncestorsOmitted(Number(data.ancestors_omitted) || 0);
                                } else if (data) {
                                    console.error('[ViewPostView] post-submit get_comments missing ancestors', {
                                        postId,
                                        keys: Object.keys(data),
                                    });
                                }
                            }
                        } catch (_) { }
                    })();
                } catch (e) {
                    setReplySubmitError(prev => ({
                        ...prev,
                        [commentId]: String(e && e.message ? e.message : 'Failed to confirm')
                    }));
                    try {
                        updatePost(commentId, {
                            replyBusy: false
                        });
                    } catch (_) { }
                }
            } else {
                setReplySubmitError(prev => ({
                    ...prev,
                    [commentId]: res?.error || 'Comment failed'
                }));
                try {
                    updatePost(commentId, {
                        replyBusy: false
                    });
                } catch (_) { }
            }
        } catch (e) {
            setReplySubmitError(prev => ({
                ...prev,
                [commentId]: String(e?.message || e || 'Comment failed')
            }));
            try {
                updatePost(commentId, {
                    replyBusy: false
                });
            } catch (_) { }
        } finally {
            setReplySubmitStartTime(prev => {
                const n = {
                    ...prev
                };
                delete n[commentId];
                return n;
            });
            setReplyElapsedTime(prev => {
                const n = {
                    ...prev
                };
                delete n[commentId];
                return n;
            });
            setReplySubmitStatus(prev => {
                const n = {
                    ...prev
                };
                delete n[commentId];
                return n;
            });
        }
    };
    const routeParams = useParams();

    // Parse depth from query params (0-5, must be valid integer when provided)
    const depthParam = React.useMemo(() => {
        const params = new URLSearchParams(location.search);
        const raw = params.get('depth');
        if (raw === null || raw === '') return null; // Not provided
        if (!/^\d+$/.test(raw)) {
            console.error('[ViewPostView] Invalid depth parameter:', raw, '- must be 0-5');
            return 'invalid';
        }
        const num = Number(raw);
        if (!Number.isFinite(num) || num < 0 || num > 5) {
            console.error('[ViewPostView] Invalid depth parameter:', raw, '- must be 0-5');
            return 'invalid';
        }
        return num;
    }, [location.search]);
    const postId = routeParams.postId || null;

    // depth is render-only: slice the already-fetched ancestor chain
    const visibleAncestors = React.useMemo(() => {
        if (!ancestors.length) return [];
        if (depthParam === null || depthParam === 'invalid') return ancestors;
        if (depthParam === 0) return ancestors.slice(0, 1);
        const [op, ...parents] = ancestors;
        return [op, ...parents.slice(-depthParam)];
    }, [ancestors, depthParam]);

    useEffect(() => {
        if (postId) markPostOpened(postId);
    }, [postId]);

    const commentsRequestRef = useRef(0);
    const commentsAutoOpenTimersRef = useRef(new Set());
    const loadedPostIdRef = useRef(null);
    useEffect(() => {
        const autoOpenTimeouts = commentsAutoOpenTimersRef.current;
        const post_id = postId;
        const requestId = commentsRequestRef.current + 1;
        commentsRequestRef.current = requestId;
        let cancelled = false;
        const keepContent = !!(
            post_id
            && loadedPostIdRef.current
            && String(loadedPostIdRef.current).toLowerCase() === String(post_id).toLowerCase()
        );
        setError(null);
        if (!keepContent) {
            setLoading(true);
            setRoot({});
            setChildren([]);
            setAncestors([]);
            setAncestorsOmitted(0);
            setLastVisitTs(null);
        } else {
            console.debug('[ViewPostView] lens refetch in place', {
                postId: post_id,
                lens,
                teamId,
            });
        }
        if (!post_id) {
            loadedPostIdRef.current = null;
            setLoading(false);
            return () => {
                cancelled = true;
                autoOpenTimeouts.forEach((timeoutId) => clearTimeout(timeoutId));
                autoOpenTimeouts.clear();
            };
        }

        const applyCommentsData = (data) => {
            if (cancelled || commentsRequestRef.current !== requestId) return;
            // Web hard-requires ancestors (ships with backend). Soft `|| []`
            // would hide a missing-field regression as an empty chain.
            if (!data || !data.root || !Array.isArray(data.children)) {
                setLoading(false);
                setError('Thread response is incomplete');
                console.error('[ViewPostView] get_comments incomplete payload', {
                    postId: post_id,
                    hasRoot: !!(data && data.root),
                    childrenType: data && data.children != null ? typeof data.children : 'missing',
                });
                return;
            }
            if (!Array.isArray(data.ancestors) || !('ancestors_omitted' in data)) {
                setLoading(false);
                setError('Thread response missing ancestors');
                console.error('[ViewPostView] get_comments missing ancestors fields', {
                    postId: post_id,
                    keys: data ? Object.keys(data) : [],
                });
                return;
            }
            setLoading(false);
            loadedPostIdRef.current = post_id;
            setRoot(data.root);
            setChildren(data.children);
            const nextAncestors = data.ancestors;
            const nextOmitted = Number(data.ancestors_omitted) || 0;
            setAncestors(nextAncestors);
            setAncestorsOmitted(nextOmitted);
            console.debug('[ViewPostView] Applied ancestors from comments', {
                postId: post_id,
                ancestors: nextAncestors.length,
                ancestors_omitted: nextOmitted,
                source: data.__bootstrap ? 'bootstrap' : 'get_comments',
            });
            Storage.removeOptimisticPost(post_id);
            try {
                const f = tx && tx['reconcileAfterCommentsFetch'];
                if (typeof f === 'function') f(post_id, data.root, data.children);
            } catch (_) { }
            if (keepContent) {
                return;
            }
            // Mark current comment count as visited
            if (data.root && data.root.comments !== undefined) {
                try {
                    Storage.setLastVisitCommentCount(post_id, data.root.comments);
                } catch (_) { }
            }
            // Capture previous visit timestamp for highlight, then set new visit time
            try {
                const prevTs = Storage.getLastVisitTimestamp(post_id);
                if (prevTs !== null && !isNaN(Number(prevTs))) setLastVisitTs(Number(prevTs));
            } catch (_) {
                setLastVisitTs(null);
            }
            // Mark visit timestamp after capturing previous, for highlighting
            try {
                const nowSec = Math.floor(Date.now() / 1000);
                Storage.setLastVisitTimestamp(post_id, nowSec);
            } catch (_) { }
            // Auto-open edit if edit query parameter is present and user owns the post
            const params = new URLSearchParams(location.search);
            const shouldEdit = params.get('edit') === 'true';
            if (shouldEdit && data.root) {
                const currentUserAddress = state && state.publicKey ? String(state.publicKey).trim().toLowerCase() : Storage.load('publicKey', '').trim().toLowerCase();
                const postAuthorAddress = data.root && data.root.user_id ? String(data.root.user_id).trim().toLowerCase() : '';
                const isAuthor = currentUserAddress && postAuthorAddress && currentUserAddress === postAuthorAddress;
                if (isAuthor) {
                    // Small delay to ensure state is updated
                    const timeoutId = setTimeout(() => {
                        autoOpenTimeouts.delete(timeoutId);
                        if (cancelled || commentsRequestRef.current !== requestId) return;
                        openEdit(data.root);
                    }, 100);
                    autoOpenTimeouts.add(timeoutId);
                }
            }
            // Auto-open donate dialog if donate query parameter is present
            const shouldDonate = params.get('donate') === 'true';
            if (shouldDonate && data.root && data.root.user_id) {
                const timeoutId = setTimeout(() => {
                    autoOpenTimeouts.delete(timeoutId);
                    if (cancelled || commentsRequestRef.current !== requestId) return;
                    setConfirmDonate(data.root.user_id);
                }, 100);
                autoOpenTimeouts.add(timeoutId);
            }
            // Do not auto-open reply; user explicitly opens when needed
        };

        const viewerAddress = Storage.load("publicKey", "");
        (async () => {
            if (!keepContent && lens === LENS.EFFECTIVE) {
                try {
                    const stashed = await peekBootstrapStashAfterBootstrap(
                        'bootstrap_view',
                        viewerAddress || null,
                    );
                    if (cancelled || commentsRequestRef.current !== requestId) return;
                    const rootId = stashed && stashed.root && stashed.root.post_id
                        ? String(stashed.root.post_id).toLowerCase()
                        : '';
                    if (
                        stashed
                        && stashed.kind === 'thread'
                        && stashed.found !== false
                        && rootId
                        && rootId === String(post_id).toLowerCase()
                    ) {
                        readBootstrapStash('bootstrap_view', viewerAddress || null);
                        console.debug('[Bootstrap] thread stash hit', { postId: post_id });
                        applyCommentsData({ ...stashed, __bootstrap: true });
                        return;
                    }
                } catch (_) { /* fall through */ }
            }

            if (cancelled || commentsRequestRef.current !== requestId) return;
            // Independent fetch: drop late launch stash so it cannot override
            // a later navigation to the same route within the stash TTL.
            try { Storage.remove('bootstrap_view'); } catch (_) { }
            const lensParams = commentsLensParams(threadLensRef.current.lens, threadLensRef.current.teamId);
            console.debug('[ViewPostView] get_comments', { postId: post_id, ...lensParams });
            Api.get('get_comments', {
                post_id,
                address: viewerAddress,
                ...lensParams,
            }).then(data => {
                applyCommentsData(data);
            }).catch(error => {
                if (cancelled || commentsRequestRef.current !== requestId) return;
                setLoading(false);
                let errorMessage = "An unknown error occurred";
                const msg = error && error.message ? String(error.message) : "";
                if (/HTTP\s*404/i.test(msg)) {
                    const optimistic = Storage.getOptimisticPost(post_id);
                    if (optimistic) {
                        setError(null);
                        setRoot(optimistic);
                        setChildren([]);
                        return;
                    }
                }
                if (/HTTP\s*404/i.test(msg)) {
                    errorMessage = <span>
                        <br />&nbsp;
                        <strong>No post with id:</strong><br />
                        <span style={{
                            fontSize: '0.6rem'
                        }}>{post_id}</span>
                        <br />
                        <br />
                        <span style={{
                            fontSize: '0.75rem'
                        }}>
                            Try Again in ~10s; it may be still propagating across the network.
                        </span>
                        <br />&nbsp;
                    </span>;
                } else if (msg) {
                    errorMessage = msg;
                }
                setError(errorMessage);
            });
        })();

        return () => {
            cancelled = true;
            autoOpenTimeouts.forEach((timeoutId) => clearTimeout(timeoutId));
            autoOpenTimeouts.clear();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [postId, lens, teamId]);

    useEffect(() => {
        if (!postId) return;
        const normalizedPostId = String(postId).toLowerCase();
        let cancelled = false;
        const viewerAddress = Storage.load("publicKey", "");
        const applyIndexedPost = (rootPost, childPosts, nextAncestors, nextOmitted) => {
            if (cancelled || !rootPost || !rootPost.post_id) return;
            const rootId = String(rootPost.post_id).toLowerCase();
            if (rootId !== normalizedPostId) return;
            if (!Array.isArray(nextAncestors) || nextOmitted === undefined || nextOmitted === null) {
                console.error('[ViewPostView] indexed post missing ancestors', {
                    postId: normalizedPostId,
                    ancestorsType: nextAncestors == null ? 'missing' : typeof nextAncestors,
                });
                return;
            }
            Storage.removeOptimisticPost(normalizedPostId);
            setRoot(rootPost);
            setChildren(Array.isArray(childPosts) ? childPosts : []);
            setAncestors(nextAncestors);
            setAncestorsOmitted(Number(nextOmitted) || 0);
            setError(null);
            setLoading(false);
        };
        const handleIndexed = e => {
            const detail = e?.detail || {};
            const eventPostId = String(detail.postId || detail.root?.post_id || '').toLowerCase();
            if (eventPostId !== normalizedPostId) return;
            applyIndexedPost(detail.root, detail.children || [], detail.ancestors, detail.ancestors_omitted);
        };
        const handleRejected = e => {
            const detail = e?.detail || {};
            const eventPostId = String(detail.postId || '').toLowerCase();
            if (eventPostId !== normalizedPostId) return;
            Storage.removeOptimisticPost(normalizedPostId);
            setChildren([]);
            setLoading(false);
            setError(`Post transaction rejected: ${detail.error || 'unknown error'}`);
        };
        window.addEventListener('postCreatedIndexed', handleIndexed);
        window.addEventListener('postCreatedRejected', handleRejected);

        const optimistic = Storage.getOptimisticPost(normalizedPostId);
        if (optimistic) {
            console.debug('[ViewPostView] Rendering optimistic post while indexer catches up', { postId: normalizedPostId });
            setRoot(optimistic);
            setChildren([]);
            setError(null);
            setLoading(false);

            const retryDelays = [800, 1200, 2000, 3000, 5000, 8000];
            const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
            (async () => {
                for (let attempt = 0; attempt < retryDelays.length + 1; attempt += 1) {
                    if (cancelled) return;
                    if (attempt > 0) {
                        await sleep(retryDelays[attempt - 1]);
                        if (cancelled) return;
                    }
                    try {
                        const data = await Api.get('get_comments', {
                            post_id: normalizedPostId,
                            address: viewerAddress,
                            ...commentsLensParams(threadLensRef.current.lens, threadLensRef.current.teamId),
                        });
                        if (data && data.root && data.root.post_id) {
                            applyIndexedPost(
                                data.root,
                                data.children || [],
                                data.ancestors,
                                data.ancestors_omitted,
                            );
                            return;
                        }
                    } catch (err) {
                        console.debug('[ViewPostView] Optimistic post not indexed yet', {
                            postId: normalizedPostId,
                            attempt: attempt + 1,
                            error: err?.message || String(err)
                        });
                    }
                }
            })();
        }

        return () => {
            cancelled = true;
            window.removeEventListener('postCreatedIndexed', handleIndexed);
            window.removeEventListener('postCreatedRejected', handleRejected);
        };
    }, [postId]);

    // Detect if loaded post is a comment (has non-empty target)
    const isViewingComment = React.useMemo(() => {
        if (!root) return false;
        const target = root.target || '';
        const rootPostId = root.root_post_id || '';
        const thisPostId = (root.post_id || '').toLowerCase();
        return target.trim() !== '' && rootPostId.toLowerCase() !== thisPostId;
    }, [root]);

    // If we loaded a comment (not root), treat postId as focused
    const focusedCommentId = React.useMemo(() => {
        if (isViewingComment && routeParams.postId) {
            return String(routeParams.postId).toLowerCase();
        }
        return '';
    }, [isViewingComment, routeParams.postId]);

    // The actual root post ID (for "view full thread" links)
    const actualRootPostId = React.useMemo(() => {
        if (!root) return '';
        // If viewing a comment, use root_post_id; otherwise use the post's own ID
        if (isViewingComment && root.root_post_id) {
            return root.root_post_id.toLowerCase();
        }
        return (root.post_id || '').toLowerCase();
    }, [root, isViewingComment]);

    // Consume highlight ID once - use module cache to survive React Strict Mode
    const [highlightPostId] = useState(() => {
        if (!_highlightConsumed) {
            _cachedHighlightPostId = Storage.consumePendingPostHighlight();
            _highlightConsumed = true;
        }
        return _cachedHighlightPostId;
    });

    // Reset cache on unmount so next navigation gets fresh value
    useEffect(() => {
        return () => {
            _highlightConsumed = false;
            _cachedHighlightPostId = null;
        };
    }, []);

    // Track if the root post should flash (separate from comments which use state.posts)
    const [rootFlash, setRootFlash] = useState(false);
    const rootFlashTriggeredRef = useRef(false);

    // Flash the root post once when it loads and matches the highlight ID
    useEffect(() => {
        if (rootFlashTriggeredRef.current) return;

        // Compute the target ID directly here
        let targetHighlightId = null;
        if (focusedCommentId && /^[0-9a-f]{64}$/i.test(focusedCommentId)) {
            targetHighlightId = focusedCommentId.toLowerCase();
        } else if (highlightPostId) {
            targetHighlightId = String(highlightPostId).toLowerCase();
        }
        if (!targetHighlightId) return;
        if (!root || !root.post_id) return;
        if (String(root.post_id).toLowerCase() !== targetHighlightId) return;
        rootFlashTriggeredRef.current = true;
        setRootFlash(true);
        setTimeout(() => setRootFlash(false), 700);
    }, [focusedCommentId, highlightPostId, root]);

    // Compute normalizedHighlightId for use elsewhere (highlighting border etc)
    const normalizedHighlightId = React.useMemo(() => {
        if (focusedCommentId && /^[0-9a-f]{64}$/i.test(focusedCommentId)) {
            return focusedCommentId.toLowerCase();
        }
        if (highlightPostId) {
            return String(highlightPostId).toLowerCase();
        }
        const hash = typeof window !== 'undefined' && window.location && window.location.hash ? window.location.hash : '';
        if (hash && hash.startsWith('#comment-')) {
            const commentId = hash.slice('#comment-'.length).toLowerCase();
            if (/^[0-9a-f]{64}$/i.test(commentId)) {
                return commentId;
            }
        }
        return null;
    }, [highlightPostId, focusedCommentId]);

    // Flash comments once after they load (for comment-specific highlights)
    const highlightFlashRef = useRef(false);
    useEffect(() => {
        if (highlightFlashRef.current) return;
        const targetId = normalizedHighlightId;
        if (!targetId) return;
        // Skip if this is the root post (handled above)
        if (root && root.post_id && String(root.post_id).toLowerCase() === targetId) return;
        const targetKey = String(targetId).toLowerCase();
        // Find the comment in children (recursively) and get its actual post_id
        const findInChildren = nodes => {
            if (!Array.isArray(nodes)) return null;
            for (const n of nodes) {
                if (!n || !n.post_id) continue;
                if (String(n.post_id).toLowerCase() === targetKey) return n.post_id;
                if (n.children) {
                    const found = findInChildren(n.children);
                    if (found) return found;
                }
            }
            return null;
        };
        const actualPostId = findInChildren(children);
        if (!actualPostId) return;
        highlightFlashRef.current = true;
        try {
            updatePost(actualPostId, {
                flash: true
            });
        } catch (_) { }
        setTimeout(() => {
            try {
                updatePost(actualPostId, {
                    flash: false
                });
            } catch (_) { }
        }, 1500);
    }, [normalizedHighlightId, root, children, updatePost]);

    // Flatten comments: root is level 0; replies increment level
    const flattenedComments = React.useMemo(() => {
        if (!root || !root.post_id) return [];
        const sortVisibleChildren = (baseChildren) => {
            const visible = Array.isArray(baseChildren) ? baseChildren : [];
            return sortComments(visible, viewerAddress);
        };
        const walk = (nodes, level, out) => {
            if (!Array.isArray(nodes)) return;
            nodes.forEach(n => {
                out.push({
                    ...n,
                    level
                });
                const next = sortVisibleChildren(n.children);
                if (next && next.length) walk(next, level + 1, out);
            });
        };

        // When viewing a comment via /p/:commentId, stitch ancestors + focused + children
        if (isViewingComment) {
            const out = [];
            let nextLevel = 0;
            visibleAncestors.forEach(a => {
                out.push({ ...a, children: [], level: nextLevel, isContextComment: nextLevel > 0 });
                nextLevel++;
            });
            out.push({ ...root, level: nextLevel });
            const focusedChildren = sortVisibleChildren(children);
            if (focusedChildren.length) walk(focusedChildren, nextLevel + 1, out);
            return out;
        }

        // Normal view (root post)
        const out = [{
            ...root,
            level: 0
        }];
        const base = sortVisibleChildren(children);
        walk(base, 1, out);
        return out;
    }, [root, children, viewerAddress, isViewingComment, visibleAncestors]);

    // Compute visibility/collapsed per comment using ancestor stack
    const annotated = React.useMemo(() => {
        const items = flattenedComments;
        const out = [];
        const stack = []; // booleans: collapsed flags of ancestors
        const threshold = getCollapseThreshold();
        items.forEach(n => {
            while (stack.length > n.level) stack.pop();
            const anyAncestorCollapsed = stack.some(Boolean);
            const hasExplicitCollapse = !!(state.posts && state.posts[n.post_id] && Object.prototype.hasOwnProperty.call(state.posts[n.post_id], 'collapsed'));
            const explicitCollapsed = hasExplicitCollapse ? !!state.posts[n.post_id].collapsed : null;
            const autoCollapsed = !hasExplicitCollapse ? shouldAutoCollapse(n, threshold) : false;
            const isCollapsed = hasExplicitCollapse ? explicitCollapsed : autoCollapsed;
            const isNew = !!(lastVisitTs && n.level > 0 && typeof n.timestamp === 'number' && n.timestamp > lastVisitTs);
            const flash = !!state.posts[n.post_id]?.flash;
            // Merge updates from state.posts (for edits, etc.)
            const statePost = state.posts[n.post_id];
            const merged = {
                ...n,
                hidden: anyAncestorCollapsed,
                collapsed: isCollapsed,
                isNew,
                flash
            };
            if (statePost) {
                // Merge content, title, topic, edited fields if they exist in state
                if (statePost.content !== undefined) merged.content = statePost.content;
                if (statePost.title !== undefined) merged.title = statePost.title;
                if (statePost.topic !== undefined) merged.topic = statePost.topic;
                if (statePost.root_topic !== undefined) merged.root_topic = statePost.root_topic;
                if (statePost.tag !== undefined) merged.tag = statePost.tag;
                if (statePost.thread_locked !== undefined) merged.thread_locked = statePost.thread_locked;
                if (statePost.edited !== undefined) merged.edited = statePost.edited;
                if (statePost.edited_ts !== undefined) merged.edited_ts = statePost.edited_ts;
            }
            // If we know the post is edited but don't have edited_ts yet, fall back to backend edited_at
            if (merged.edited && merged.edited_ts === undefined && typeof merged.edited_at === 'number' && merged.edited_at > 0) {
                merged.edited_ts = merged.edited_at;
            }
            out.push(merged);
            stack.push(isCollapsed);
        });
        return out;
    }, [flattenedComments, state.posts, lastVisitTs]);

    // Scroll to focused comment once the thread (including ancestors) is painted
    const scrollToFocusedDone = React.useRef(false);
    useEffect(() => {
        scrollToFocusedDone.current = false;
    }, [postId]);
    useLayoutEffect(() => {
        if (!focusedCommentId || loading || scrollToFocusedDone.current) return;
        const el = document.getElementById(`comment-${focusedCommentId.toLowerCase()}`);
        if (!el) return;
        el.scrollIntoView({ block: 'start', behavior: 'instant' });
        scrollToFocusedDone.current = true;
    }, [loading, focusedCommentId, annotated]);

    // Scroll to hash-linked comment (non-focused, e.g. direct #comment-xxx link)
    const hasScrolledToHash = React.useRef(false);
    useEffect(() => {
        try {
            if (hasScrolledToHash.current || focusedCommentId) return;
            const hash = typeof window !== 'undefined' && window.location && window.location.hash ? window.location.hash : '';
            if (!hash || !hash.startsWith('#comment-')) return;
            const commentId = hash.slice('#comment-'.length).toLowerCase();
            const el = document.getElementById(`comment-${commentId}`);
            if (el) {
                setTimeout(() => {
                    el.scrollIntoView({
                        block: 'start',
                        behavior: 'instant'
                    });
                    hasScrolledToHash.current = true;
                }, 100);
            }
        } catch (_) { }
    }, [annotated, focusedCommentId]);

    // Mark reply as viewed when navigating to it via hash or focusedCommentId
    useEffect(() => {
        const hash = window.location.hash;
        let commentId = null;
        if (focusedCommentId && /^[0-9a-f]{64}$/i.test(focusedCommentId)) {
            commentId = focusedCommentId.toLowerCase();
        } else if (hash && hash.startsWith('#comment-')) {
            commentId = hash.slice('#comment-'.length).toLowerCase();
        }
        if (commentId) {
            try {
                Storage.addViewedReplyId(commentId);
            } catch (_) { }
        }
    }, [focusedCommentId, location.hash]);

    // Show loading/error states within the layout (including invalid depth)
    const depthError = depthParam === 'invalid' ? 'Invalid depth parameter. Must be 0-5.' : null;
    return {
        root,
        setRoot,
        setChildren,
        loading,
        setLoading,
        blockError,
        blockSuccess,
        isBlocking,
        confirmBlockPost,
        confirmBlockUser,
        confirmBlockTopic,
        confirmDeletePost,
        isDeleting,
        deleteMessages,
        deletedPosts,
        confirmDonate,
        setConfirmDonate,
        donateAmount,
        donateMessages,
        giftSubMessages,
        confirmGiftSub,
        confirmAward,
        setConfirmAward,
        isAwarding,
        awardMessages,
        confirmReportPost,
        reportReason,
        setReportReason,
        isReporting,
        reportMessages,
        error,
        setError,
        shareMessages,
        setShareMessages,
        ancestorsOmitted,
        setAncestors,
        setAncestorsOmitted,
        cardSize,
        theme,
        location,
        navigate,
        openBrowsingEnabled,
        nodeConfigLoaded: Boolean(nodeConfig),
        isMobile,
        goBackToFeed,
        viewerAddress,
        topicFollowHover,
        setTopicFollowHover,
        isTopicPending,
        isUserPending,
        formatTopicStatus,
        formatUserStatus,
        isSendPending,
        formatSendStatus,
        isSubscribePending,
        formatSubscribeStatus,
        openMenuId,
        setOpenMenuId,
        menuPosition,
        setMenuPosition,
        menuButtonRefs,
        menuDropdownRef,
        isFollowingAuthor,
        handleFollowToggle,
        isSubscribedTopic,
        handleTopicFollowToggle,
        replyUploadProgress,
        setReplyUploadProgress,
        replyEditorUpload,
        setReplyEditorUpload,
        replyIsUploading,
        setReplyIsUploading,
        replyAttachedType,
        setReplyAttachedType,
        replyAttachedUrl,
        setReplyAttachedUrl,
        replyThumbLoading,
        setReplyThumbLoading,
        replySubmitError,
        setReplySubmitError,
        replySubmitStatus,
        replyErrorClearTimeoutRef,
        mobileReplyOverlayRef,
        limits,
        closeReply,
        toggleReply,
        handleBlockPost,
        confirmBlockPostAction,
        cancelBlockPost,
        handleBlockUser,
        confirmBlockUserAction,
        cancelBlockUser,
        handleBlockTopic,
        confirmBlockTopicAction,
        cancelBlockTopic,
        handleReport,
        confirmReportAction,
        cancelReport,
        handleDeletePost,
        confirmDeletePostAction,
        cancelDeletePost,
        handleDonate,
        handleGiftSubscription,
        confirmGiftSubAction,
        cancelGiftSub,
        userBalanceUmirage,
        AWARD_TYPES,
        giftSubscriptionLabel,
        subFeeLabel,
        agentFeeLabel,
        subFeeUmirage,
        agentFeeUmirage,
        getAwardCost,
        handleGiveAward,
        confirmAwardAction,
        openEdit,
        handleEditSubmit,
        confirmDonateAction,
        cancelDonate,
        handleDonateAmountChange,
        formatDonateAmount,
        handleReplyChange,
        handleReplyDragOver,
        handleReplyDragLeave,
        handleReplyDrop,
        handleSubmit,
        postId,
        focusedCommentId,
        actualRootPostId,
        lastVisitTs,
        setLastVisitTs,
        rootFlash,
        normalizedHighlightId,
        annotated,
        depthError
    };
}
