import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useTheme } from "styled-components";
import { useLocation, useParams, useNavigationType } from "react-router-dom";
import Storage from "../utils/Storage";
import { getAllowedTagsParam } from "../utils/ContentTags";
import Api from "../utils/api";
import { fetchFollowedTopics } from "../utils/Subscriptions";
import { fetchFollowedUsers } from "../utils/FollowUsers";
import { readBootstrapStashAfterBootstrap } from "../utils/bootstrapStash";
import { usePendingFollows } from "./useFollowState.js";

const APP_BANNER_COOLDOWN_MS = 14 * 24 * 60 * 60 * 1000;
const MODERATION_REMINDER_SNOOZE_MS = 7 * 24 * 60 * 60 * 1000;
// Show the moderation reminder only after the user has been logged in on the
// home feed for at least this long. Avoids piling onto first-visit onboarding.
const MODERATION_REMINDER_MIN_AGE_MS = 10 * 60 * 1000;

// Session storage key helpers for feed state preservation (keyed by topic)
export const getFeedKey = (topic, suffix) => `feed_${suffix}_${topic}`;

// In-memory (per-tab) feed cache to avoid sessionStorage quota issues on long feeds.
// This cache survives SPA navigation (feed -> post -> back), but not a full page refresh.
export const getFeedMemCache = () => {
    try {
        if (typeof window === 'undefined') return null;
        if (!window.__MIRAGE_FEED_MEM_CACHE__) {
            window.__MIRAGE_FEED_MEM_CACHE__ = {};
        }
        return window.__MIRAGE_FEED_MEM_CACHE__;
    } catch (_) {
        return null;
    }
};
export const getMemKey = topic => {
    try {
        return encodeURIComponent(String(topic || '').trim());
    } catch (_) {
        return String(topic || '');
    }
};
export const readMemFeedState = topic => {
    try {
        const cache = getFeedMemCache();
        if (!cache) return null;
        const key = getMemKey(topic);
        const v = cache[key];
        if (!v || typeof v !== 'object') return null;
        return v;
    } catch (_) {
        return null;
    }
};
export const writeMemFeedState = (topic, patch) => {
    try {
        const cache = getFeedMemCache();
        if (!cache) return;
        const key = getMemKey(topic);
        const prev = cache[key] && typeof cache[key] === 'object' ? cache[key] : {};
        cache[key] = {
            ...prev,
            ...patch,
            at: Date.now()
        };
    } catch (_) { }
};
export const readSavedOrder = topic => {
    try {
        const savedOrder = sessionStorage.getItem(getFeedKey(topic, 'order'));
        if (!savedOrder) return null;
        const parsed = JSON.parse(savedOrder);
        return Array.isArray(parsed) ? parsed : null;
    } catch (_) {
        return null;
    }
};
export const isTopLevelPostForFeed = p => {
    if (!p) return false;
    const hasTitle = typeof p.title === 'string' && p.title.trim().length > 0;
    const hasTopic = typeof p.topic === 'string' && String(p.topic).trim().length > 0;
    if (!hasTitle || !hasTopic) return false;
    const topicVal = String(p.topic || '').trim().toLowerCase();
    const isReserved = ['all', 'home', 'following'].includes(topicVal);
    return !isReserved;
};
export const hasAnyCachedPostsForTopic = (topic, postsObj) => {
    try {
        if (!postsObj || typeof postsObj !== 'object') return false;
        const ids = Object.keys(postsObj);
        if (ids.length === 0) return false;
        const t = String(topic || '').trim();
        const tLower = t.toLowerCase();
        const values = Object.values(postsObj);

        // "all", "home", "following" all render top-level posts across topics.
        if (tLower === 'all' || tLower === 'home' || tLower === 'following') {
            return values.some(isTopLevelPostForFeed);
        }
        return values.some(p => {
            if (!isTopLevelPostForFeed(p)) return false;
            return String(p.topic || '').trim().toLowerCase() === tLower;
        });
    } catch (_) {
        return false;
    }
};
export const checkRestoreFeedIntent = topic => {
    try {
        const raw = sessionStorage.getItem('mirage_restore_feed');
        if (!raw) return false;
        const parsed = JSON.parse(raw);
        const intended = String(parsed?.topic || '').trim();
        const at = Number(parsed?.at || 0);
        if (!intended || !Number.isFinite(at) || at <= 0) return false;
        const ageMs = Date.now() - at;
        if (ageMs < 0 || ageMs > 15000) return false;
        return intended === String(topic || '');
    } catch (_) {
        return false;
    }
};
export const clearRestoreFeedIntent = () => {
    try {
        sessionStorage.removeItem('mirage_restore_feed');
    } catch (_) { }
};

// Check if we navigated here from a post view via browser back button
// This flag is set when clicking a post link from the feed
export const checkCameFromViewPost = () => {
    try {
        const raw = sessionStorage.getItem('mirage_came_from_feed');
        if (!raw) return false;
        const parsed = JSON.parse(raw);
        const at = Number(parsed?.at || 0);
        if (!Number.isFinite(at) || at <= 0) return false;
        // Valid for 30 minutes (enough time for reading a post with comments)
        const ageMs = Date.now() - at;
        if (ageMs < 0 || ageMs > 1800000) return false;
        return true;
    } catch (_) {
        return false;
    }
};
export const clearCameFromFeedFlag = () => {
    try {
        sessionStorage.removeItem('mirage_came_from_feed');
    } catch (_) { }
};

// Track if we've seen the first SPA navigation (to distinguish page refresh from back nav).
// On true page refresh (F5), this starts as false and the first POP is the refresh.
// After ANY navigation within the SPA, we set this to true, so subsequent POPs are back navigations.
export let __hasHadFirstSpaNavigation = false;

// Check if this is the very first page load (before any SPA navigation happened)
export const isInitialPageLoad = () => {
    return !__hasHadFirstSpaNavigation;
};

// Mark that we've had at least one SPA navigation
export const markSpaNavigationOccurred = () => {
    __hasHadFirstSpaNavigation = true;
};

// Helper to detect back/forward navigation
// Returns true for POP navigations (back button, navigate(-1), browser back/forward)
// but NOT for the initial page load (where POP just means "loaded directly")
export const getIsBackNavigation = navigationType => {
    if (navigationType !== 'POP') return false;
    // On the very first load, POP just means we landed here (not a back nav)
    if (isInitialPageLoad()) return false;
    return true;
};

// For scroll restoration, we want to restore on BOTH back navigation AND page refresh
export const shouldRestoreScroll = navigationType => {
    return navigationType === 'POP';
};
export function useMain({
    state,
    setPosts,
    updatePost,
    setTopic,
    routeTopic
}) {
    const params = useParams();
    const urlTopic = routeTopic || params.topic || "home"; // Get the topic from URL or prop
    const navigationType = useNavigationType(); // 'POP' = back/forward, 'PUSH'/'REPLACE' = direct nav
    const isBackNavigation = getIsBackNavigation(navigationType);
    const theme = useTheme();
    const mapHomeSortMode = theme.caps.mapHomeSortMode;
    const currentTopicRef = useRef(urlTopic); // Track current topic to detect changes
    const restoreFeedIntentRef = useRef(checkRestoreFeedIntent(urlTopic));
    // For browser back button: only restore if we came from a post view that was opened from the feed
    const cameFromViewPostRef = useRef(isBackNavigation && checkCameFromViewPost());

    // If we are switching topics (and reusing component), we must invalidate any stale "restore" intents
    // that were calculated for the previous topic.
    if (currentTopicRef.current !== urlTopic) {
        try {
            restoreFeedIntentRef.current = false;
            cameFromViewPostRef.current = false;
        } catch (_) { }
    }
    const shouldAttemptRestore = isBackNavigation || restoreFeedIntentRef.current === true || cameFromViewPostRef.current === true;
    const shouldRestoreFeedState = shouldAttemptRestore;

    // Mark that we've navigated within the SPA (so subsequent POPs are back navigations)
    useEffect(() => {
        markSpaNavigationOccurred();
    }, []);

    // Clear the restore intent after we've consumed it (in effect to avoid StrictMode double-render issues)
    useEffect(() => {
        if (restoreFeedIntentRef.current) {
            clearRestoreFeedIntent();
        }
        if (cameFromViewPostRef.current) {
            clearCameFromFeedFlag();
        }
    }, []);
    const [error, setError] = useState(null);
    const [, setTopics] = useState([]); // Dynamically store unique topics (state is persisted but value unused)

    // Only restore from cache on back navigation (POP), not on direct nav (clicking links)
    const [stableOrder, setStableOrder] = useState(() => {
        if (!shouldRestoreFeedState) return [];
        try {
            const mem = readMemFeedState(urlTopic);
            const memOrder = mem && Array.isArray(mem.order) ? mem.order : null;
            if (memOrder && memOrder.length > 0) return memOrder;
        } catch (_) { }
        try {
            const savedOrder = sessionStorage.getItem(getFeedKey(urlTopic, 'order'));
            if (savedOrder) {
                const parsed = JSON.parse(savedOrder);
                return Array.isArray(parsed) ? parsed : [];
            }
        } catch (_) { }
        return [];
    });

    // Only skip loading on back navigation with cached state
    const [isLoading, setIsLoading] = useState(() => {
        if (!shouldRestoreFeedState) return true;
        try {
            const memOrder = readMemFeedState(urlTopic)?.order;
            const order = readSavedOrder(urlTopic) || (Array.isArray(memOrder) ? memOrder : null);
            if (order && order.length > 0 && state.posts && order.some(id => state.posts[id])) return false;
            if (hasAnyCachedPostsForTopic(urlTopic, state.posts)) return false;
        } catch (_) { }
        return true;
    });

    // Only restore currentPage on back navigation
    const [currentPage, setCurrentPage] = useState(() => {
        if (!shouldRestoreFeedState) return 1;
        try {
            const memPage = Number(readMemFeedState(urlTopic)?.page || 0);
            if (Number.isFinite(memPage) && memPage > 0) return Math.floor(memPage);
        } catch (_) { }
        try {
            const savedPage = sessionStorage.getItem(getFeedKey(urlTopic, 'page'));
            if (savedPage) return parseInt(savedPage, 10) || 1;
        } catch (_) { }
        return 1;
    });

    // Only restore hasMorePosts on back navigation
    const [hasMorePosts, setHasMorePosts] = useState(() => {
        if (!shouldRestoreFeedState) return false;
        try {
            const memHasMore = readMemFeedState(urlTopic)?.hasMore;
            if (typeof memHasMore === 'boolean') return memHasMore;
        } catch (_) { }
        try {
            const savedHasMore = sessionStorage.getItem(getFeedKey(urlTopic, 'hasmore'));
            if (savedHasMore) return savedHasMore === 'true';
        } catch (_) { }
        return false;
    });
    const [homeSortMode, setHomeSortMode] = useState(() => {
        const defaultMode = 'magic';
        let mode = Storage.load('home_sort_mode', defaultMode);

        // Migrate deprecated/unknown modes to the new unified mode.
        // Magic is now the only algo mode.
        if (mode !== 'magic' && mode !== 'newest') {
            mode = defaultMode;
            Storage.save('home_sort_mode', mode);
        }
        return mode;
    });
    const [oldRedditSort, setOldRedditSort] = useState(() => {
        // Derive from the persisted home_sort_mode so the toggle survives refresh.
        // 'newest' -> 'new', anything else -> 'best'. Without this the effect below
        // resets home_sort_mode back to 'magic' on every mount.
        try {
            const saved = Storage.load('home_sort_mode', 'magic');
            return saved === 'newest' ? 'new' : 'best';
        } catch (_) {
            return 'best';
        }
    });
    const handleOldRedditSortChange = useCallback(mode => {
        if (mode !== 'best' && mode !== 'new') return;
        console.debug('[OldReddit] sort.select', {
            mode
        });
        setOldRedditSort(mode);
    }, []);
    useEffect(() => {
        if (!mapHomeSortMode) return;
        const mapped = oldRedditSort === 'new' ? 'newest' : 'magic';
        if (homeSortMode !== mapped) {
            console.debug('[OldReddit] sort.map', {
                oldRedditSort,
                homeSortMode,
                mapped
            });
            setHomeSortMode(mapped);
            Storage.save('home_sort_mode', mapped);
        }
    }, [mapHomeSortMode, oldRedditSort, homeSortMode]);
    const [cardSize, setCardSize] = useState(() => {
        try {
            return Storage.load('card_size', 'compact');
        } catch (_) {
            return 'compact';
        }
    });
    const handleCardSizeChange = newSize => {
        setCardSize(newSize);
        Storage.save('card_size', newSize);
        window.dispatchEvent(new CustomEvent('settingsUpdated', {
            detail: {
                cardSize: newSize
            }
        }));
    };
    const [hideDownvotedPosts, setHideDownvotedPosts] = useState(() => {
        const val = Storage.load('hide_downvoted_posts', false);
        return val === true ? true : false;
    });
    const hideDownvotedPostsRef = useRef(hideDownvotedPosts);
    useEffect(() => {
        hideDownvotedPostsRef.current = hideDownvotedPosts;
    }, [hideDownvotedPosts]);
    const [hidingPostsSet, setHidingPostsSet] = useState(() => new Set()); // Posts animating out
    const [blockedTopicsLocal, setBlockedTopicsLocal] = useState(() => new Set()); // Optimistic blocked topic patterns (may contain *)
    const [flashingPostsSet, setFlashingPostsSet] = useState(() => {
        // Consume any pending highlight on mount
        const pendingId = Storage.consumePendingPostHighlight();
        return pendingId ? new Set([pendingId]) : new Set();
    });
    const [isLoadingMore, setIsLoadingMore] = useState(false);
    const [isMobile, setIsMobile] = useState(() => {
        try {
            if (typeof window !== 'undefined' && window.matchMedia) {
                return window.matchMedia('(max-width: 600px)').matches;
            }
            if (typeof window !== 'undefined') {
                return window.innerWidth <= 600;
            }
        } catch (_) { }
        return false;
    });
    const _topicMatchesPattern = (topic, pattern) => {
        if (!pattern.includes('*')) return topic === pattern;
        const re = new RegExp('^' + pattern.split('*').map(s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*') + '$');
        return re.test(topic);
    };
    const isTopicBlockedLocal = useCallback(topicVal => {
        const t = String(topicVal || '').trim().toLowerCase();
        if (!t) return false;
        if (blockedTopicsLocal.size === 0) return false;
        for (const pat of blockedTopicsLocal) {
            if (_topicMatchesPattern(t, pat)) return true;
        }
        return false;
    }, [blockedTopicsLocal]);
    const location = useLocation(); // Call useLocation at the top level of the component
    const viewerAddress = Storage.load('publicKey', '') || 'guest';
    useEffect(() => {
        setBlockedTopicsLocal(new Set());
    }, [viewerAddress]);
    // Hydrate the local blocked-topics set from the server on login / viewer
    // change. Without this, `isTopicBlockedLocal` only reflects topics the
    // viewer blocked in THIS session — so visiting /t/<already-blocked>
    // would still render the normal "no posts" state on a fresh page load.
    // On cold load the data is usually already in the bootstrap stash; we
    // consume that first and skip the request entirely.
    useEffect(() => {
        if (!viewerAddress || viewerAddress === 'guest') return undefined;
        let cancelled = false;
        const applyBlocked = (data) => {
            if (cancelled) return;
            const serverTopics = Array.isArray(data?.blocked_topics) ? data.blocked_topics : [];
            if (serverTopics.length === 0) return;
            setBlockedTopicsLocal(prev => {
                const next = new Set(prev);
                for (const raw of serverTopics) {
                    const t = String(raw || '').trim().toLowerCase();
                    if (t) next.add(t);
                }
                return next;
            });
        };
        (async () => {
            try {
                const stashed = await readBootstrapStashAfterBootstrap('bootstrap_user_blocked', viewerAddress);
                if (stashed) {
                    applyBlocked(stashed);
                    return;
                }
                const data = await Api.get('get_user_blocked', { address: viewerAddress });
                applyBlocked(data);
            } catch (_) { /* noop — optimistic UI falls back to empty set */ }
        })();
        return () => { cancelled = true; };
    }, [viewerAddress]);
    const [followedTopicsSet, setFollowedTopicsSet] = useState(new Set());
    const [followedAuthorsSet, setFollowedAuthorsSet] = useState(new Set());
    const [topicFollowHover, setTopicFollowHover] = useState(false);
    const {
        isTopicPending,
        formatTopicStatus
    } = usePendingFollows();
    const followDataLoadedRef = useRef(false);
    const afterSetPostsRef = useRef(0);
    const topicsLoadedRef = useRef(false); // Track if we've attempted to load topics from API
    const isMountedRef = useRef(true); // Track if component is mounted
    const forceHardRefreshRef = useRef(isInitialPageLoad()); // Bypass debounce on initial page load
    const downvoteTimeoutsRef = useRef(new Set());
    const latestFeedRequestRef = useRef(0);

    // Android app banner: cooldown after dismissal
    const isAndroid = (() => {
        try {
            return /android/i.test(navigator.userAgent);
        } catch (_) {
            return false;
        }
    })();
    const [androidBannerDismissedAt, setAndroidBannerDismissedAt] = useState(() => {
        try {
            const stored = Storage.load('android_app_banner_dismissed_at_ms', 0);
            const parsed = Number(stored);
            return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
        } catch (_) {
            return 0;
        }
    });
    const dismissAndroidBanner = () => {
        const now = Date.now();
        try {
            Storage.save('android_app_banner_dismissed_at_ms', now);
        } catch (_) { }
        setAndroidBannerDismissedAt(now);
    };

    // iPhone app banner: cooldown after dismissal
    const isIPhone = (() => {
        try {
            return /iPhone/i.test(navigator.userAgent) && !isAndroid;
        } catch (_) {
            return false;
        }
    })();
    const [iphoneBannerDismissedAt, setIphoneBannerDismissedAt] = useState(() => {
        try {
            const stored = Storage.load('iphone_app_banner_dismissed_at_ms', 0);
            const parsed = Number(stored);
            return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
        } catch (_) {
            return 0;
        }
    });
    const dismissIPhoneBanner = () => {
        const now = Date.now();
        try {
            Storage.save('iphone_app_banner_dismissed_at_ms', now);
        } catch (_) { }
        setIphoneBannerDismissedAt(now);
    };

    const isLoggedIn = viewerAddress && viewerAddress !== 'guest';

    // NSFW welcome hero: show once for logged-in users until they choose yes/no
    const [showNsfwHero, setShowNsfwHero] = useState(() => {
        try {
            return !Storage.load('nsfw_hero_dismissed_v1', false);
        } catch (_) {
            return true;
        }
    });

    // handleNsfwChoice is defined after getPosts (see below)

    const [showModerationReminder, setShowModerationReminder] = useState(false);
    useEffect(() => {
        if (!isLoggedIn || urlTopic !== 'home') {
            setShowModerationReminder(false);
            return undefined;
        }

        const suffix = String(viewerAddress).toLowerCase();
        const dismissedKey = `moderation_reminder_understood_v1_${suffix}`;
        const snoozedUntilKey = `moderation_reminder_snoozed_until_v1_${suffix}`;
        const firstSeenKey = `moderation_reminder_first_seen_at_v1_${suffix}`;

        const dismissed = Storage.load(dismissedKey, false) === true;
        const snoozedUntilRaw = Number(Storage.load(snoozedUntilKey, 0));
        const now = Date.now();
        const snoozed = Number.isFinite(snoozedUntilRaw) && snoozedUntilRaw > now;

        let firstSeenAt = Number(Storage.load(firstSeenKey, 0));
        if (!Number.isFinite(firstSeenAt) || firstSeenAt <= 0 || firstSeenAt > now) {
            firstSeenAt = now;
            try {
                Storage.save(firstSeenKey, firstSeenAt);
            } catch (_) { }
        }

        const ageMs = now - firstSeenAt;
        const eligible = !dismissed && !snoozed;
        const shouldShow = eligible && ageMs >= MODERATION_REMINDER_MIN_AGE_MS;
        setShowModerationReminder(shouldShow);

        try {
            console.debug('[MainView] moderation reminder eligibility', {
                firstSeenAt,
                ageMs,
                dismissed,
                snoozed,
                shouldShow
            });
        } catch (_) { }

        if (eligible && !shouldShow) {
            const remainingMs = MODERATION_REMINDER_MIN_AGE_MS - ageMs;
            const handle = setTimeout(() => {
                setShowModerationReminder(true);
                try {
                    console.debug('[MainView] moderation reminder timer fired', {
                        firstSeenAt,
                        remainingMs
                    });
                } catch (_) { }
            }, Math.max(0, remainingMs));
            return () => clearTimeout(handle);
        }
        return undefined;
    }, [isLoggedIn, urlTopic, viewerAddress]);

    const dismissModerationReminder = useCallback(() => {
        if (!viewerAddress || viewerAddress === 'guest') return;
        const suffix = String(viewerAddress).toLowerCase();
        try {
            Storage.save(`moderation_reminder_understood_v1_${suffix}`, true);
            Storage.remove(`moderation_reminder_snoozed_until_v1_${suffix}`);
            console.debug('[MainView] moderation reminder dismissed');
        } catch (_) { }
        setShowModerationReminder(false);
    }, [viewerAddress]);

    const snoozeModerationReminder = useCallback(() => {
        if (!viewerAddress || viewerAddress === 'guest') return;
        const suffix = String(viewerAddress).toLowerCase();
        const snoozedUntil = Date.now() + MODERATION_REMINDER_SNOOZE_MS;
        try {
            Storage.save(`moderation_reminder_snoozed_until_v1_${suffix}`, snoozedUntil);
            console.debug('[MainView] moderation reminder snoozed', {
                snoozedUntil
            });
        } catch (_) { }
        setShowModerationReminder(false);
    }, [viewerAddress]);

    const [nodeConfigTick, setNodeConfigTick] = useState(0);
    useEffect(() => {
        const handler = () => setNodeConfigTick(prev => prev + 1);
        window.addEventListener('nodeConfigUpdated', handler);
        // Cold-load race: on a first visit, /api/bootstrap can resolve and
        // dispatch 'nodeConfigUpdated' before this listener attaches (passive
        // effects are deferred while the main thread parses the ~1MB bundle).
        // If the config already landed in storage, force a re-read here so we
        // don't stay stuck on the null we read at first render — otherwise
        // openBrowsingEnabled never flips true and the gated feed/topics
        // fetches never fire (the feed renders an endless skeleton).
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
    if (nodeConfigTick > 0 && !nodeConfig) {
        try {
            console.error('[MainView] nodeConfig missing after fetch attempt');
        } catch (_) { }
        throw new Error('MainView requires nodeConfig to render app banners');
    }
    if (nodeConfig && (typeof nodeConfig.android_banner_enabled !== 'boolean' || typeof nodeConfig.ios_banner_enabled !== 'boolean')) {
        try {
            console.error('[MainView] nodeConfig missing banner flags', {
                android_banner_enabled: nodeConfig.android_banner_enabled,
                ios_banner_enabled: nodeConfig.ios_banner_enabled
            });
        } catch (_) { }
        throw new Error('MainView requires android_banner_enabled and ios_banner_enabled in nodeConfig');
    }
    useEffect(() => {
        if (!nodeConfig) return;
        try {
            console.debug('[MainView] app banner flags', {
                android_banner_enabled: nodeConfig.android_banner_enabled,
                ios_banner_enabled: nodeConfig.ios_banner_enabled
            });
        } catch (_) { }
    }, [nodeConfig]);
    const inviteCodesEnabled = Boolean(nodeConfig?.registration_enabled) && Boolean(nodeConfig?.registration_invite_code_required);
    const questsEnabled = Boolean(nodeConfig?.quests_enabled);
    // Open browsing: when on, logged-out visitors fetch & read the feed/topics
    // (account prompts only fire on write/social actions). When off, behavior is
    // unchanged: logged-out users get the welcome/invite screen, no content fetch.
    const openBrowsingEnabled = Boolean(nodeConfig?.open_browsing_enabled);
    const nowMs = Date.now();
    const androidBannerCooldownActive = androidBannerDismissedAt > 0 && (nowMs - androidBannerDismissedAt) < APP_BANNER_COOLDOWN_MS;
    const iphoneBannerCooldownActive = iphoneBannerDismissedAt > 0 && (nowMs - iphoneBannerDismissedAt) < APP_BANNER_COOLDOWN_MS;
    const showAndroidBanner = Boolean(nodeConfig) && isAndroid && !androidBannerCooldownActive && nodeConfig.android_banner_enabled;
    const showIPhoneBanner = Boolean(nodeConfig) && isIPhone && !iphoneBannerCooldownActive && nodeConfig.ios_banner_enabled;
    useEffect(() => {
        const androidNextEligibleAt = androidBannerDismissedAt ? androidBannerDismissedAt + APP_BANNER_COOLDOWN_MS : 0;
        const iphoneNextEligibleAt = iphoneBannerDismissedAt ? iphoneBannerDismissedAt + APP_BANNER_COOLDOWN_MS : 0;
        console.debug('[MainView] app banner cooldown', {
            android: {
                dismissedAtMs: androidBannerDismissedAt,
                nextEligibleAtMs: androidNextEligibleAt
            },
            iphone: {
                dismissedAtMs: iphoneBannerDismissedAt,
                nextEligibleAtMs: iphoneNextEligibleAt
            }
        });
    }, [androidBannerDismissedAt, iphoneBannerDismissedAt]);

    // Invite code state
    const [inviteCodes, setInviteCodes] = useState([]);
    const [inviteModalOpen, setInviteModalOpen] = useState(false);
    const [inviteCodeCopied, setInviteCodeCopied] = useState(false);

    // Welcome stats for logged-out users (user count, posts, 7d active)
    // Initialize from cache for instant display (stale-while-revalidate pattern).
    // Discard caches missing the current shape — schema changed from `active24h`
    // to `active7d`, and stale shapes would crash the render with `undefined`.
    const _loadValidWelcomeCache = () => {
        try {
            const cached = Storage.load('welcome_stats_cache', null);
            if (!cached || typeof cached !== 'object') return null;
            if (typeof cached.active7d !== 'number') return null;
            return cached;
        } catch (_) {
            return null;
        }
    };
    const [welcomeStats, setWelcomeStats] = useState(_loadValidWelcomeCache);
    const [welcomeStatsStale, setWelcomeStatsStale] = useState(() => _loadValidWelcomeCache() !== null);

    // Collapse state for hero cards (persisted)
    const [inviteBannerCollapsed, setInviteBannerCollapsed] = useState(() => {
        try {
            return Storage.load('invite_banner_collapsed', true);
        } catch (_) {
            return true;
        }
    });
    const [questCardCollapsed, setQuestCardCollapsed] = useState(() => {
        try {
            return Storage.load('quest_card_collapsed', false);
        } catch (_) {
            return false;
        }
    });
    const toggleInviteBanner = () => {
        const next = !inviteBannerCollapsed;
        setInviteBannerCollapsed(next);
        try {
            Storage.save('invite_banner_collapsed', next);
        } catch (_) { }
    };
    const toggleQuestCard = () => {
        const next = !questCardCollapsed;
        setQuestCardCollapsed(next);
        try {
            Storage.save('quest_card_collapsed', next);
        } catch (_) { }
    };

    // Fetch invite codes for logged-in users. On cold load the data is usually
    // already in the bootstrap stash; we consume that first and skip the request.
    useEffect(() => {
        if (!isLoggedIn || !inviteCodesEnabled) {
            setInviteCodes([]);
            return;
        }
        let cancelled = false;
        const loadInviteCodes = async () => {
            try {
                const resp = await Api.get('get_invite_codes', {
                    address: viewerAddress
                });
                if (cancelled) return;
                if (resp && Array.isArray(resp.codes)) {
                    setInviteCodes(resp.codes);
                }
            } catch (_) { }
        };
        (async () => {
            const stashed = await readBootstrapStashAfterBootstrap('bootstrap_invite_codes', viewerAddress);
            if (cancelled) return;
            if (stashed && Array.isArray(stashed.codes)) {
                setInviteCodes(stashed.codes);
            } else {
                loadInviteCodes();
            }
        })();

        // Listen for invite codes updates (e.g., when claimed from quests)
        const handleInviteCodesUpdated = () => {
            loadInviteCodes();
        };
        window.addEventListener('inviteCodesUpdated', handleInviteCodesUpdated);
        return () => {
            cancelled = true;
            window.removeEventListener('inviteCodesUpdated', handleInviteCodesUpdated);
        };
    }, [isLoggedIn, viewerAddress, inviteCodesEnabled]);

    // Fetch welcome stats for logged-out users (user count, posts in 24h, 7d active)
    // Uses lightweight endpoint that only returns essential counts (fast, cached)
    // Implements stale-while-revalidate: show cached value immediately, update when fresh
    useEffect(() => {
        if (isLoggedIn) return; // Only fetch for logged-out visitors

        let cancelled = false;
        const loadWelcomeStats = async () => {
            try {
                const data = await Api.get('get_welcome_stats', {}, {
                    timeoutMs: 3000
                });
                if (cancelled) return;
                if (data) {
                    const freshStats = {
                        userCount: data.registered_users || 0,
                        posts24h: data.posts_24h || 0,
                        comments24h: 0,
                        active7d: data.active_7d || 0
                    };
                    setWelcomeStats(freshStats);
                    setWelcomeStatsStale(false);
                    try {
                        Storage.save('welcome_stats_cache', freshStats);
                    } catch (_) { }
                }
            } catch (_) {
                // Keep showing stale data if we have it
            }
        };
        loadWelcomeStats();
        return () => {
            cancelled = true;
        };
    }, [isLoggedIn]);

    // Get next available invite code
    const nextAvailableCode = inviteCodes.find(c => !c.is_used);
    const availableCodeCount = inviteCodes.filter(c => !c.is_used).length;

    // Handle opening invite modal
    const handleOpenInviteModal = () => {
        setInviteModalOpen(true);
        setInviteCodeCopied(false);
    };
    const handleCopyInviteCode = () => {
        if (!nextAvailableCode) return;
        navigator.clipboard.writeText(getShareUrl());
        setInviteCodeCopied(true);
        setTimeout(() => setInviteCodeCopied(false), 2000);
    };

    // Handle native share (mobile)
    const handleNativeShare = async () => {
        if (!nextAvailableCode || !navigator.share) return;
        try {
            await navigator.share({
                title: 'Join me on Mirage',
                text: getShareText(),
                url: getShareUrl()
            });
        } catch (err) {
            // User cancelled or share failed - ignore
        }
    };

    // Check if native share is available (typically mobile)
    const canNativeShare = typeof navigator !== 'undefined' && !!navigator.share;
    const getShareUrl = () => {
        if (!nextAvailableCode) return '';
        const viewerName = Storage.load('username', '');
        const precheckEnabled = Storage.load('referral_precheck_enabled', false) === true;
        if (inviteCodesEnabled && precheckEnabled && viewerName) {
            return `${window.location.origin}/signup?ref=${encodeURIComponent(viewerName)}`;
        }
        return `${window.location.origin}/signup?invite=${nextAvailableCode.code}`;
    };
    const SHARE_TEXTS = [
        // Tame / Descriptive
        'Join me on Mirage: a decentralized social network.', 'Join me on Mirage: social media, decentralized.', 'Join me on Mirage: the decentralized social platform.', 'Join me on Mirage: where conversations happen on-chain.', 'Join me on Mirage: social media built on blockchain.', 'Join me on Mirage: a new kind of social network.', 'Join me on Mirage: decentralized and user-controlled.', 'Join me on Mirage: social media you actually own.', 'Join me on Mirage: your posts live on the blockchain.', 'Join me on Mirage: decentralized discourse awaits.', 'Join me on Mirage: where you control your experience.', 'Join me on Mirage: social media with transparency built in.', 'Join me on Mirage: open, decentralized, community-driven.', 'Join me on Mirage: the user-first social network.', 'Join me on Mirage: social media redesigned for users.', 'Join me on Mirage: simple, decentralized, yours.', 'Join me on Mirage: a platform built for real conversations.', 'Join me on Mirage: where your data stays yours.', 'Join me on Mirage: social media without the middleman.', 'Join me on Mirage: decentralized by design.',
        // User Control Focus
        'Join me on Mirage: you control your feed, not an algorithm.', 'Join me on Mirage: no black box algorithms here.', 'Join me on Mirage: you own your algorithm.', 'Join me on Mirage: your feed, your rules.', 'Join me on Mirage: take back control of your feed.', 'Join me on Mirage: transparent algorithms, real control.', 'Join me on Mirage: no hidden manipulation, just content you choose.', 'Join me on Mirage: the algorithm works for you, not against you.', 'Join me on Mirage: see what you want, not what they want.', 'Join me on Mirage: your timeline, your choice.', 'Join me on Mirage: no engagement tricks, just real content.', 'Join me on Mirage: social media that respects your attention.', 'Join me on Mirage: finally, a feed you understand.', 'Join me on Mirage: no mystery algorithms deciding what you see.', 'Join me on Mirage: user-centric from day one.', 'Join me on Mirage: built around you, not advertisers.', 'Join me on Mirage: your experience, your control.', 'Join me on Mirage: social media that puts users first.', 'Join me on Mirage: no data harvesting, just discourse.', 'Join me on Mirage: privacy and control by default.',
        // Anti-Corporate
        'Join me on Mirage: no corporate overlords.', 'Join me on Mirage: social media without corporate control.', 'Join me on Mirage: free from corporate censorship.', 'Join me on Mirage: no faceless corporations deciding what\'s allowed.', 'Join me on Mirage: discourse without corporate interference.', 'Join me on Mirage: not owned by billionaires.', 'Join me on Mirage: social media that can\'t be bought.', 'Join me on Mirage: no shareholders to please, just users.', 'Join me on Mirage: built for users, not profits.', 'Join me on Mirage: no ads, no corporate agenda.', 'Join me on Mirage: social media without the corporate BS.', 'Join me on Mirage: where corporations don\'t control the conversation.', 'Join me on Mirage: no CEO can change the rules on you.', 'Join me on Mirage: your voice isn\'t a product here.', 'Join me on Mirage: social media that doesn\'t sell you out.', 'Join me on Mirage: no corporate content moderation.', 'Join me on Mirage: escape the corporate walled gardens.', 'Join me on Mirage: owned by everyone, controlled by no one.', 'Join me on Mirage: social media without the suits.', 'Join me on Mirage: decentralized means no corporate master.',
        // Censorship / Free Speech
        'Join me on Mirage: censorship-proof by design.', 'Join me on Mirage: where speech is protected, not policed.', 'Join me on Mirage: built to protect speech, not suppress it.', 'Join me on Mirage: your voice can\'t be silenced here.', 'Join me on Mirage: no arbitrary bans, no shadow banning.', 'Join me on Mirage: speak freely, permanently.', 'Join me on Mirage: censorship-resistant social media.', 'Join me on Mirage: your posts can\'t be erased by agents.', 'Join me on Mirage: where deplatforming isn\'t possible.', 'Join me on Mirage: true freedom of expression.', 'Join me on Mirage: your speech doesn\'t need approval.', 'Join me on Mirage: no trust & safety theater here.', 'Join me on Mirage: post without fear of removal.', 'Join me on Mirage: uncensorable discourse.', 'Join me on Mirage: where no one can memory-hole your posts.', 'Join me on Mirage: permanent, immutable, yours.', 'Join me on Mirage: the platform that can\'t censor you.', 'Join me on Mirage: your words, preserved forever on-chain.', 'Join me on Mirage: no one decides what you can say.', 'Join me on Mirage: discourse without gatekeepers.',
        // Provocative / Bold
        'Join me on Mirage: the social network they can\'t shut down.', 'Join me on Mirage: unstoppable.', 'Join me on Mirage: decentralized, unstoppable, yours.', 'Join me on Mirage: true discourse, decentralized, unstoppable.', 'Join me on Mirage: what Reddit could have been.', 'Join me on Mirage: what Twitter should have been.', 'Join me on Mirage: what social media was meant to be.', 'Join me on Mirage: social media, unchained.', 'Join me on Mirage: the revolution is decentralized.', 'Join me on Mirage: they can\'t stop the signal.', 'Join me on Mirage: immune to takedowns.', 'Join me on Mirage: no kill switch.', 'Join me on Mirage: built to survive.', 'Join me on Mirage: the platform that fights back.', 'Join me on Mirage: ungovernable social media.', 'Join me on Mirage: where free speech isn\'t negotiable.', 'Join me on Mirage: the network no government can silence.', 'Join me on Mirage: decentralized means unstoppable.', 'Join me on Mirage: burn the algorithm, own your feed.', 'Join me on Mirage: social media with teeth.'];
    const getShareText = () => {
        return SHARE_TEXTS[Math.floor(Math.random() * SHARE_TEXTS.length)];
    };
    useEffect(() => {
        let cancelled = false;
        const loadFollowData = async () => {
            if (!viewerAddress || viewerAddress === 'guest' || followDataLoadedRef.current) return;
            try {
                const [topics, authors] = await Promise.all([fetchFollowedTopics(viewerAddress), fetchFollowedUsers(viewerAddress)]);
                if (cancelled) return;
                setFollowedTopicsSet(new Set(topics.map(t => t.toLowerCase())));
                setFollowedAuthorsSet(new Set(authors.map(a => a.toLowerCase())));
                followDataLoadedRef.current = true;
            } catch (_) { }
        };
        loadFollowData();
        return () => {
            cancelled = true;
        };
    }, [viewerAddress]);

    // Listen for settings changes (downvote hiding) - tag changes handled after getPosts is defined
    useEffect(() => {
        const handler = e => {
            const detail = e?.detail || {};
            if (Object.prototype.hasOwnProperty.call(detail, 'hideDownvotedPosts')) {
                setHideDownvotedPosts(Boolean(detail.hideDownvotedPosts));
            }
        };
        window.addEventListener('settingsUpdated', handler);
        return () => window.removeEventListener('settingsUpdated', handler);
    }, []);

    // Track mobile screen size to hide compact option in dropdown
    useEffect(() => {
        const checkMobile = () => {
            try {
                if (typeof window !== 'undefined' && window.matchMedia) {
                    const mobile = window.matchMedia('(max-width: 600px)').matches;
                    setIsMobile(mobile);
                } else if (typeof window !== 'undefined') {
                    const mobile = window.innerWidth <= 600;
                    setIsMobile(mobile);
                }
            } catch (_) { }
        };
        checkMobile();
        window.addEventListener('resize', checkMobile);
        if (typeof window !== 'undefined' && window.matchMedia) {
            const mediaQuery = window.matchMedia('(max-width: 600px)');
            if (mediaQuery.addEventListener) {
                mediaQuery.addEventListener('change', checkMobile);
                return () => {
                    window.removeEventListener('resize', checkMobile);
                    mediaQuery.removeEventListener('change', checkMobile);
                };
            }
        }
        return () => window.removeEventListener('resize', checkMobile);
    }, []);

    // Track posts the viewer downvoted to hide with animation on Home
    useEffect(() => {
        const timeoutSet = downvoteTimeoutsRef.current;
        const handler = e => {
            const detail = e?.detail || {};
            const pid = String(detail?.postId || '').toLowerCase();
            const dir = Number(detail?.direction);
            if (!pid || dir >= 0) return;

            // Only hide if the setting is enabled AND we are on the Home feed
            // The setting explicitly says "(Home feed only)", so we shouldn't animate on other feeds
            // where the post will reappear anyway.
            const isHome = currentTopicRef.current === 'home';
            if (!hideDownvotedPostsRef.current || !isHome) return;

            // First, add to hiding set to trigger animation
            setHidingPostsSet(prev => {
                if (prev.has(pid)) return prev;
                const next = new Set(prev);
                next.add(pid);
                return next;
            });

            // After fade animation completes, permanently hide for this session
            const timeoutId = setTimeout(() => {
                try {
                    if (typeof updatePost === 'function') {
                        updatePost(pid, {
                            hidden_client: true
                        });
                    }
                } catch (_) {/* noop */ }
                try {
                    setStableOrder(prev => prev.filter(id => String(id || '').toLowerCase() !== pid));
                } catch (_) {/* noop */ }
                setHidingPostsSet(prev => {
                    if (!prev.has(pid)) return prev;
                    const next = new Set(prev);
                    next.delete(pid);
                    return next;
                });
                timeoutSet.delete(timeoutId);
            }, 250);
            timeoutSet.add(timeoutId);
        };
        window.addEventListener('postDownvoted', handler);
        return () => {
            window.removeEventListener('postDownvoted', handler);
            timeoutSet.forEach((timeoutId) => clearTimeout(timeoutId));
            timeoutSet.clear();
        };
    }, [updatePost]);

    // Clear flash animation after it completes
    useEffect(() => {
        if (flashingPostsSet.size === 0) return;
        const timer = setTimeout(() => {
            setFlashingPostsSet(new Set());
        }, 1000);
        return () => clearTimeout(timer);
    }, [flashingPostsSet]);
    const optimisticPostIdsRef = useRef(new Map()); // post_id -> created_at_ms

    const getPosts = useCallback((topic, overrideChrono = null, pageOverride = null, silent = false) => {
        if (!isMountedRef.current) return;

        // Logged-out users only fetch when open browsing is on. Guests have no
        // personalized home/following feed, so show the public "all" feed instead.
        const viewer = Storage.load("publicKey", "");
        const isGuest = !viewer || viewer === 'guest';
        if (isGuest && !openBrowsingEnabled) return;
        if (topic === "") topic = "all";
        if (isGuest && (topic === 'home' || topic === 'following')) topic = 'all';
        const isHomeFeed = topic === 'home';
        const isFollowingFeed = topic === 'following';
        if (topic !== state.topic) {
            if (!isMountedRef.current) return;
            setTopic(topic);
        }
        if (!isMountedRef.current) return;
        // Only show full loading state for initial load or topic switch, not pagination
        const effectivePage = typeof pageOverride === 'number' && Number.isFinite(pageOverride) && pageOverride > 0 ? Math.floor(pageOverride) : currentPage;
        const isPaginating = effectivePage > 1;
        if (!silent && !isPaginating) {
            setIsLoading(true);
        }
        const viewerAddress = Storage.load("publicKey", "");
        const page = effectivePage;
        const requestId = latestFeedRequestRef.current + 1;
        latestFeedRequestRef.current = requestId;
        const isCurrentRequest = () => latestFeedRequestRef.current === requestId;
        const matchTopic = t => {
            if (topic === 'all') return true;
            if (topic === 'home' || topic === 'following') return true;
            return String(t || '').toLowerCase() === String(topic || '').toLowerCase();
        };
        const handleResponse = data => {
            if (!isMountedRef.current) return;
            if (!isCurrentRequest()) return;
            const forcedHard = !!forceHardRefreshRef.current;
            const arr = data && Array.isArray(data.posts) ? data.posts : [];
            const hasMore = !!(data && data.has_more);
            if (!isMountedRef.current) return;
            setHasMorePosts(hasMore);
            const isTopLevelPost = p => {
                if (!p) return false;
                const hasTitle = typeof p.title === 'string' && p.title.trim().length > 0;
                const hasTopic = typeof p.topic === 'string' && p.topic.trim().length > 0;
                const topicVal = String(p.topic || '').trim().toLowerCase();
                const isReserved = ['all', 'home', 'following'].includes(topicVal);
                return hasTitle && hasTopic && !isReserved;
            };
            const topLevel = arr.filter(isTopLevelPost);
            let filtered = isHomeFeed || isFollowingFeed ? topLevel : topLevel.filter(p => matchTopic(p.topic));

            // Note: Downvote filtering is handled in render phase to avoid stale closure issues

            // Server already returns posts in correct order for all feeds (magic or newest)
            const sortedOnce = filtered;
            const sortedOrder = sortedOnce.map(p => p.post_id);
            const postDict = sortedOnce.reduce((acc, post) => {
                acc[post.post_id] = post;
                return acc;
            }, {});
            if (!isMountedRef.current) return;
            afterSetPostsRef.current = typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now();
            if (page === 1) {
                setPosts(postDict, Date.now());
            } else {
                // Append new posts to existing ones
                const currentPosts = state.posts || {};
                const combined = {
                    ...currentPosts,
                    ...postDict
                };
                setPosts(combined, Date.now());
            }
            if (!isMountedRef.current) return;
            setStableOrder(currentOrder => {
                if (page === 1) {
                    const topicChanged = currentTopicRef.current !== topic;
                    if (topicChanged || forcedHard) {
                        const now = Date.now();
                        const keepOptimistic = [];
                        for (const [id, ts] of optimisticPostIdsRef.current.entries()) {
                            if (now - Number(ts || 0) > 5 * 1000) continue;
                            if (!sortedOrder.includes(id) && currentOrder.includes(id)) keepOptimistic.push(id);
                            if (sortedOrder.includes(id)) optimisticPostIdsRef.current.delete(id);
                        }
                        return [...keepOptimistic, ...sortedOrder.filter(id => !keepOptimistic.includes(id))];
                    } else {
                        // Same topic refresh: preserve existing posts from previous pages
                        const currentPosts = state.posts || {};
                        const existingPostsInOrder = currentOrder.filter(id => {
                            const post = currentPosts[id];
                            if (!post || post.deleted) return false;
                            if (topic === 'all') {
                                const hasTitle = typeof post.title === 'string' && post.title.trim().length > 0;
                                const hasTopic = typeof post.topic === 'string' && post.topic.trim().length > 0;
                                const topicVal = String(post.topic || '').trim().toLowerCase();
                                const isReserved = ['all', 'home', 'following'].includes(topicVal);
                                return hasTitle && hasTopic && !isReserved;
                            } else if (topic === 'home' || topic === 'following') {
                                return isTopLevelPost(post);
                            } else {
                                return String(post.topic || '').trim().toLowerCase() === topic.toLowerCase();
                            }
                        }).filter(id => !sortedOrder.includes(id));
                        return [...sortedOrder, ...existingPostsInOrder];
                    }
                } else {
                    // Append new posts to existing order
                    return [...currentOrder, ...sortedOrder.filter(id => !currentOrder.includes(id))];
                }
            });
            try {
                forceHardRefreshRef.current = false;
            } catch (_) { }

            // Mark topic switch complete - from now on, render new topic
            if (!isMountedRef.current) return;
            try {
                currentTopicRef.current = topic;
            } catch (_) { }
            // Only clear isLoading if we set it (not during pagination)
            if (page === 1) {
                if (!silent) setIsLoading(false);
                setIsLoadingMore(false);
                try {
                    loadMoreLockRef.current = false;
                } catch (_) { }
            } else {
                // For pagination, defer clearing isLoadingMore until after posts render
                requestAnimationFrame(() => {
                    if (isMountedRef.current) {
                        setIsLoadingMore(false);
                        try {
                            loadMoreLockRef.current = false;
                        } catch (_) { }
                    }
                });
            }
        };
        const onError = error => {
            if (!isMountedRef.current) return;
            if (!isCurrentRequest()) return;
            const errorMessage = error && error.message ? error.message : "An unknown error occurred";
            setError(errorMessage);
            try {
                forceHardRefreshRef.current = false;
            } catch (_) { }
            // Only clear isLoading if we set it (not during pagination)
            if (page === 1) {
                if (!silent) setIsLoading(false);
            }
            setIsLoadingMore(false);
            try {
                loadMoreLockRef.current = false;
            } catch (_) { }
        };

        // Determine sort mode
        const mode = overrideChrono !== null ? overrideChrono ? 'newest' : 'magic' : homeSortMode;
        if (isHomeFeed || isFollowingFeed) {
            const params = {
                feed: topic,
                limit: 15,
                page: page,
                address: viewerAddress
            };
            params.by = mode;
            params.allowed_tags = getAllowedTagsParam();
            Api.get('get_posts', params).then(handleResponse).catch(onError);
        } else {
            const params = {
                topic,
                limit: 15,
                page: page,
                address: viewerAddress
            };
            params.by = mode;
            params.allowed_tags = getAllowedTagsParam();
            Api.get('get_posts', params).then(handleResponse).catch(onError);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [state.topic, state.lastFetched, setTopic, setPosts, currentPage, followedTopicsSet, followedAuthorsSet, homeSortMode, isLoadingMore, hideDownvotedPosts, openBrowsingEnabled]);

    // handleNsfwChoice - must be after getPosts is defined
    const handleNsfwChoice = useCallback(allowNsfw => {
        try {
            // Dismiss the hero
            Storage.save('nsfw_hero_dismissed_v1', true);
            setShowNsfwHero(false);
            if (allowNsfw) {
                // Enable all NSFW tags
                Storage.save('show_tag_adult', true);
                Storage.save('show_tag_violence', true);
                Storage.save('show_tag_gore', true);
                Storage.save('show_tag_death', true);
                // Dispatch settings update event so feed refreshes
                window.dispatchEvent(new CustomEvent('settingsUpdated', {
                    detail: {
                        showTagAdult: true,
                        showTagViolence: true,
                        showTagGore: true,
                        showTagDeath: true
                    }
                }));
            }
            // If they click "No", we keep defaults (only sensitive allowed)
            // No action needed as that's already the default

            // Force refresh the feed to apply the new settings
            try {
                forceHardRefreshRef.current = true;
                setIsLoading(true);
                setCurrentPage(1);
                setHasMorePosts(false);
                setStableOrder([]);
                // Always force page 1 on user-initiated feed refresh to avoid stale pagination leaks
                getPosts(urlTopic, null, 1);
            } catch (_) {/* noop */ }
        } catch (_) {/* noop */ }
    }, [getPosts, urlTopic]);

    // Listen for content tag settings changes - must be after getPosts is defined
    useEffect(() => {
        const handler = e => {
            const detail = e?.detail || {};
            const tagKeys = ['showTagSensitive', 'showTagAdult', 'showTagViolence', 'showTagGore', 'showTagDeath'];
            const hasTagChange = tagKeys.some(key => Object.prototype.hasOwnProperty.call(detail, key));
            if (hasTagChange) {
                // Force refresh the home feed to apply new tag filters
                try {
                    forceHardRefreshRef.current = true;
                    setIsLoading(true);
                    setCurrentPage(1);
                    setHasMorePosts(false);
                    setStableOrder([]);
                    getPosts(urlTopic, null, 1);
                } catch (_) {/* noop */ }
            }
        };
        window.addEventListener('settingsUpdated', handler);
        return () => window.removeEventListener('settingsUpdated', handler);
    }, [getPosts, urlTopic]);

    // Listen for new post creation events (must be after getPosts is defined)
    useEffect(() => {
        const handler = e => {
            const detail = e?.detail || {};
            const pid = String(detail?.postId || '').toLowerCase();
            if (!pid) return;
            try {
                const viewer = String(Storage.load("publicKey", "") || '').trim().toLowerCase();
                const topic = String(detail?.topic || '').trim();
                const title = String(detail?.title || '').trim();
                const content = String(detail?.content || '');
                const tag = String(detail?.tag || '').trim().toLowerCase();
                const thumbnail = String(detail?.thumbnail || '').trim();
                if (viewer && viewer !== 'guest' && topic && title) {
                    const nowSec = Math.floor(Date.now() / 1000);
                    const optimistic = {
                        post_id: pid,
                        author: viewer,
                        user_id: viewer,
                        username: "",
                        timestamp: nowSec,
                        topic,
                        title,
                        content,
                        tag,
                        thumbnail: thumbnail || "",
                        direction: 1,
                        user_vote: 1,
                        user_weight: 1,
                        points: 1,
                        comments: 0,
                        deleted: false
                    };
                    optimisticPostIdsRef.current.set(pid, Date.now());
                    setPosts({
                        [pid]: optimistic
                    }, Date.now());
                    setStableOrder(prev => [pid, ...prev.filter(id => id !== pid)]);
                }
            } catch (_) {/* noop */ }
            setFlashingPostsSet(prev => {
                if (prev.has(pid)) return prev;
                const next = new Set(prev);
                next.add(pid);
                return next;
            });
            // If we're on home, immediately refetch page 1 in the current mode and pin the fresh post
            if (currentTopicRef.current === 'home' || urlTopic === 'home') {
                try {
                    forceHardRefreshRef.current = true;
                } catch (_) { }
                setCurrentPage(1);
                setHasMorePosts(false);
                setIsLoadingMore(false);
                try {
                    loadMoreLockRef.current = false;
                } catch (_) { }
                getPosts('home', homeSortMode === 'newest', 1, true);
            }
        };
        window.addEventListener('postCreated', handler);
        return () => window.removeEventListener('postCreated', handler);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [getPosts, urlTopic, homeSortMode]);

    // Reset page and loading state when topic changes
    // Skip reset on back navigation (we want to restore cached state)
    //
    // `isBackNavigation` is intentionally NOT in the dependency array. It is
    // derived from `navigationType` + the module-level `__hasHadFirstSpaNavigation`
    // flag, so after a hard refresh (navigationType === 'POP') it flips
    // false -> true once the first SPA navigation marker is set post-mount, and
    // back to false when you click the already-active "Home" link (same-path
    // navigation, which react-router treats as REPLACE). That stray flip used to
    // re-run this effect and clear the feed (setStableOrder([]) + setIsLoading)
    // WITHOUT the fetch effect below firing — the fetcher is keyed on
    // `location.pathname`, which does not change for a same-path click — leaving
    // the feed wiped and stuck on the loading skeleton with nothing reloaded.
    // We only want to reset on a real trigger change (topic / viewer / sort /
    // downvote toggle); `isBackNavigation` is read inside the body purely as a
    // guard, so a stale closure value is fine here.
    useEffect(() => {
        // On back navigation, don't reset - state was already restored from cache
        if (isBackNavigation || restoreFeedIntentRef.current === true) {
            return;
        }

        // Force fresh fetch on navigation (bypass debounce)
        forceHardRefreshRef.current = true;
        setCurrentPage(1);
        setHasMorePosts(false);
        setStableOrder([]); // Clear stale order to prevent flash of old content
        setIsLoading(true); // Show loading immediately when navigating
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [urlTopic, viewerAddress, homeSortMode, hideDownvotedPosts]);

    // Infinite scroll: observe a sentinel near the bottom (also clickable fallback)
    const bottomSentinelRef = useRef(null);
    const loadMoreLockRef = useRef(false);
    const loadMore = useCallback(() => {
        if (!hasMorePosts || isLoadingMore || isLoading) {
            console.debug('[Feed] loadMore blocked:', {
                hasMorePosts,
                isLoadingMore,
                isLoading
            });
            return;
        }
        if (loadMoreLockRef.current) {
            console.debug('[Feed] loadMore blocked: lock held');
            return;
        }
        loadMoreLockRef.current = true;
        setIsLoadingMore(true);
        setCurrentPage(prev => {
            console.debug('[Feed] loadMore: page', prev, '->', prev + 1);
            return prev + 1;
        });
    }, [hasMorePosts, isLoadingMore, isLoading]);

    // Safety: release stuck loadMore lock after 10s
    useEffect(() => {
        if (!isLoadingMore) return;
        const timer = setTimeout(() => {
            if (loadMoreLockRef.current) {
                console.warn('[Feed] loadMore lock stuck for 10s, releasing');
                loadMoreLockRef.current = false;
                setIsLoadingMore(false);
            }
        }, 10000);
        return () => clearTimeout(timer);
    }, [isLoadingMore]);

    // IntersectionObserver for infinite scroll
    useEffect(() => {
        const el = bottomSentinelRef.current;
        if (!el) return;
        if (!hasMorePosts || isLoadingMore || isLoading) return;

        // Check if sentinel is already in the visible viewport (content shorter than screen)
        const rect = el.getBoundingClientRect();
        const isAlreadyVisible = rect.top < window.innerHeight;
        if (isAlreadyVisible) {
            console.debug('[Feed] sentinel already visible, triggering loadMore');
            loadMore();
            return;
        }

        // Trigger loading ~2-3 cards before bottom (600px margin)
        const observer = new IntersectionObserver(entries => {
            const entry = entries[0];
            if (entry && entry.isIntersecting) {
                console.debug('[Feed] IntersectionObserver triggered');
                loadMore();
            }
        }, {
            root: null,
            rootMargin: '600px 0px',
            threshold: 0
        });
        observer.observe(el);
        return () => observer.disconnect();
    }, [hasMorePosts, isLoadingMore, isLoading, stableOrder.length, loadMore]);

    // Backup scroll listener for browsers where IntersectionObserver may not fire reliably
    useEffect(() => {
        if (!hasMorePosts || isLoadingMore || isLoading) return;
        let ticking = false;
        const handleScroll = () => {
            if (ticking) return;
            ticking = true;
            requestAnimationFrame(() => {
                ticking = false;
                if (!hasMorePosts || isLoadingMore || isLoading || loadMoreLockRef.current) return;
                const el = bottomSentinelRef.current;
                if (!el) return;
                const rect = el.getBoundingClientRect();
                // Trigger when sentinel is within 600px of viewport bottom
                if (rect.top < window.innerHeight + 600) {
                    loadMore();
                }
            });
        };
        window.addEventListener('scroll', handleScroll, {
            passive: true
        });
        return () => window.removeEventListener('scroll', handleScroll);
    }, [hasMorePosts, isLoadingMore, isLoading, loadMore]);

    // Trigger fetch when page increments (pagination)
    useEffect(() => {
        // Only fetch page > 1 when infinite-scroll explicitly requested it.
        // This prevents stale state from a previous feed from accidentally fetching page 2 on navigation.
        if (currentPage > 1 && hasMorePosts && isLoadingMore) {
            try {
                console.log('[Feed] paginate fetch:', {
                    topic: urlTopic,
                    page: currentPage
                });
            } catch (_) { }
            getPosts(urlTopic);
        } else if (currentPage > 1 && !hasMorePosts) {
            setIsLoadingMore(false);
            try {
                loadMoreLockRef.current = false;
            } catch (_) { }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentPage, urlTopic, hasMorePosts, isLoadingMore]);
    useEffect(() => {
        // Skip topics fetch for logged-out users, unless open browsing is on (then
        // they can navigate topics like anyone else).
        if (!isLoggedIn && !openBrowsingEnabled) return;
        const storedTopicsData = Storage.load("topics", {
            topics: [],
            lastFetched: null
        });
        const stored = Array.isArray(storedTopicsData.topics) ? storedTopicsData.topics : [];
        const lastFetched = storedTopicsData.lastFetched ? new Date(storedTopicsData.lastFetched) : null;
        const shouldFetch = stored.length === 0 || !lastFetched || Date.now() - lastFetched.getTime() > 24 * 60 * 60 * 1000;
        if (shouldFetch && !topicsLoadedRef.current) {
            topicsLoadedRef.current = true;
            let cancelled = false;
            Api.get('get_topics', {
                limit: 50,
                min_posts: 1,
                address: viewerAddress
            }).then(data => {
                if (cancelled || !isMountedRef.current) return;
                if (data && Array.isArray(data.topics)) {
                    const topicsWithCounts = data.topics.filter(t => t && t.topic && typeof t.topic === 'string' && t.topic.trim() !== '').map(t => ({
                        topic: t.topic,
                        count: t.post_count || t.count || 0
                    }));
                    const topicNames = topicsWithCounts.map(t => t.topic);
                    const topicsWithAll = ['all', ...topicNames];
                    Storage.save("topics", {
                        topics: topicsWithAll,
                        topicsWithCounts: topicsWithCounts,
                        lastFetched: new Date().toISOString()
                    });
                    setTopics(topicsWithAll);
                }
            }).catch(error => {
                if (cancelled || !isMountedRef.current) return;
                topicsLoadedRef.current = false;
            });
            return () => {
                cancelled = true;
            };
        } else if (stored.length > 0) {
            setTopics(stored);
        }
    }, [isLoggedIn, viewerAddress, openBrowsingEnabled]);
    useEffect(() => {
        window.getPosts = getPosts; // Expose getPosts globally
        let cancelled = false;

        // Skip posts fetch for logged-out users, unless open browsing is on (then
        // they read the feed as a guest; account prompts fire only on write actions).
        if (!isLoggedIn && !openBrowsingEnabled) {
            setIsLoading(false);
            return;
        }

        // On back navigation (POP), restore from cache if available
        if (shouldRestoreFeedState) {
            const memOrder = readMemFeedState(urlTopic)?.order;
            const order = readSavedOrder(urlTopic) || (Array.isArray(memOrder) ? memOrder : null);
            const hasPostsForOrder = !!(order && order.length > 0 && state.posts && order.some(id => state.posts[id]));
            const hasPostsForTopic = hasAnyCachedPostsForTopic(urlTopic, state.posts);
            if (hasPostsForOrder || hasPostsForTopic) {
                // Back navigation with cached data - don't fetch
                if (!cancelled && isMountedRef.current) {
                    setIsLoading(false);
                    setIsLoadingMore(false);
                    loadMoreLockRef.current = false;
                }
                try {
                    console.log('[Feed] POP restore from cache:', urlTopic);
                } catch (_) { }
                return;
            }
        }

        // For forward navigation (clicking links), ALWAYS fetch fresh
        // Force bypass debounce - this is a user-initiated navigation
        forceHardRefreshRef.current = true;
        setCurrentPage(1);
        setStableOrder([]); // Clear stale order
        setIsLoading(true);
        try {
            console.log('[Feed] PUSH fetch fresh:', urlTopic);
        } catch (_) { }
        const timeoutId = setTimeout(() => {
            if (cancelled || !isMountedRef.current) return;
            // Hard force page 1 on navigation so Home/Following never starts at page 2
            getPosts(urlTopic, null, 1);
        }, 50);
        return () => {
            cancelled = true;
            clearTimeout(timeoutId);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [urlTopic, location.pathname, openBrowsingEnabled]);

    // Refetch when homeSortMode changes (magic/newest toggle)
    const prevHomeSortModeRef = useRef(homeSortMode);
    useEffect(() => {
        // Only trigger if homeSortMode actually changed (not on mount)
        if (prevHomeSortModeRef.current === homeSortMode) return;
        prevHomeSortModeRef.current = homeSortMode;

        // Force refetch with new mode (works for all feeds including topics)
        forceHardRefreshRef.current = true;
        setCurrentPage(1);
        setHasMorePosts(false);
        setStableOrder([]);
        setIsLoading(true);
        getPosts(urlTopic, null, 1);
    }, [homeSortMode, urlTopic, getPosts]);
    useEffect(() => {
        const storedTopicsData = Storage.load("topics", {
            topics: [],
            lastFetched: null
        });
        const stored = Array.isArray(storedTopicsData.topics) ? storedTopicsData.topics : [];

        // If not viewing "all", preserve known topics from storage (do not drop).
        if (urlTopic !== "all") {
            if (stored.length > 0) {
                setTopics(stored);
            } else {
                const fallback = ["all", ...(urlTopic ? [urlTopic] : [])];
                setTopics(fallback);
            }
            return;
        }

        // When viewing "all", just use stored topics (no merging)
        if (stored.length > 0) {
            setTopics(stored);
        }
    }, [urlTopic]);

    // Recompute stable order only when needed; skip if already set by latest fetch
    useEffect(() => {
        if (stableOrder.length > 0) return;
        // Don't compute from possibly stale state.posts while loading fresh data
        // This prevents showing old content briefly before the fetch completes
        if (isLoading) return;
        const postsArray = Object.values(state.posts || {});
        const isTopLevelPost = p => {
            if (!p) return false;
            if (p.hidden_client) return false;
            const hasTitle = typeof p.title === 'string' && p.title.trim().length > 0;
            const hasTopic = typeof p.topic === 'string' && p.topic.trim().length > 0;
            const topicVal = String(p.topic || '').trim().toLowerCase();
            const isReserved = ['all', 'home', 'following'].includes(topicVal);
            if (isTopicBlockedLocal(topicVal)) return false;
            return hasTitle && hasTopic && !isReserved;
        };
        const topLevelPosts = postsArray.filter(isTopLevelPost);
        const filtered = urlTopic === "all" || urlTopic === "home" || urlTopic === "following" ? topLevelPosts : topLevelPosts.filter(post => String(post.topic || '').toLowerCase() === String(urlTopic || '').toLowerCase());
        // Server already returns posts in correct order
        setStableOrder(filtered.map(p => p.post_id));
    }, [state.lastFetched, urlTopic, homeSortMode, stableOrder.length, state.posts, viewerAddress, followedTopicsSet, followedAuthorsSet, isLoading, isTopicBlockedLocal]);

    // Measure time from posts set to first render of list
    useEffect(() => {
        if (!state.lastFetched) return;
        if (afterSetPostsRef.current) {
            afterSetPostsRef.current = 0;
        }
    }, [state.lastFetched]);

    // Cleanup on unmount
    useEffect(() => {
        isMountedRef.current = true;
        return () => {
            isMountedRef.current = false;
        };
    }, []);

    // Save feed state to sessionStorage when values change (for back button restoration)
    // Each topic gets its own cache keys so we can restore any feed independently
    useEffect(() => {
        try {
            const orderKey = getFeedKey(urlTopic, 'order');
            if (stableOrder.length > 0) sessionStorage.setItem(orderKey, JSON.stringify(stableOrder)); else sessionStorage.removeItem(orderKey);
            sessionStorage.setItem(getFeedKey(urlTopic, 'page'), String(currentPage));
            sessionStorage.setItem(getFeedKey(urlTopic, 'hasmore'), String(hasMorePosts));
        } catch (_) { }
        try {
            writeMemFeedState(urlTopic, {
                order: stableOrder,
                page: currentPage,
                hasMore: hasMorePosts
            });
        } catch (_) { }
    }, [urlTopic, stableOrder, currentPage, hasMorePosts]);

    // Save scroll position before navigating away (keyed by current topic)
    useEffect(() => {
        const saveScrollPosition = () => {
            try {
                sessionStorage.setItem(getFeedKey(urlTopic, 'scroll'), String(window.scrollY || 0));
            } catch (_) { }
            try {
                writeMemFeedState(urlTopic, {
                    scroll: Number(window.scrollY || 0)
                });
            } catch (_) { }
        };

        // Save on any navigation (clicking links)
        const handleClick = e => {
            // Check if it's a link click that will navigate
            const link = e.target.closest('a');
            // eslint-disable-next-line no-script-url
            if (link && link.href && !link.href.startsWith('javascript:')) {
                saveScrollPosition();
                // Mark that we navigated to a post from the feed
                // This enables browser back button to restore feed position
                try {
                    const url = new URL(link.href, window.location.origin);
                    if (url.pathname.startsWith('/p/')) {
                        sessionStorage.setItem('mirage_post_nav_source', JSON.stringify({
                            source: 'feed',
                            topic: urlTopic,
                            at: Date.now()
                        }));
                        sessionStorage.setItem('mirage_came_from_feed', JSON.stringify({
                            topic: urlTopic,
                            at: Date.now()
                        }));
                    }
                } catch (_) { }
            }
        };

        // Also save before unload
        window.addEventListener('click', handleClick, true);
        window.addEventListener('beforeunload', saveScrollPosition);
        return () => {
            window.removeEventListener('click', handleClick, true);
            window.removeEventListener('beforeunload', saveScrollPosition);
        };
    }, [urlTopic]);

    // Track if scroll has been restored to prevent multiple restorations
    const scrollRestoredRef = useRef(false);
    // Store whether we should restore scroll (computed once on mount)
    const shouldRestoreScrollRef = useRef(shouldRestoreScroll(navigationType) || restoreFeedIntentRef.current === true || cameFromViewPostRef.current === true);

    // Restore scroll position on back navigation or page refresh
    // Runs when stableOrder is populated (posts are ready to render)
    useEffect(() => {
        // Only restore scroll on POP navigation (back button or refresh)
        if (!shouldRestoreScrollRef.current) return;
        // Only restore once
        if (scrollRestoredRef.current) return;
        // Wait for posts to be loaded
        if (stableOrder.length === 0) return;
        try {
            const savedScrollRaw = sessionStorage.getItem(getFeedKey(urlTopic, 'scroll'));
            const fromSession = savedScrollRaw ? parseInt(savedScrollRaw, 10) : 0;
            const fromMem = Number(readMemFeedState(urlTopic)?.scroll || 0);
            const scrollY = Number.isFinite(fromSession) && fromSession > 0 ? fromSession : Number.isFinite(fromMem) && fromMem > 0 ? fromMem : 0;
            if (scrollY > 0) {
                scrollRestoredRef.current = true;
                // Use multiple requestAnimationFrames to ensure DOM is fully rendered
                // This gives React time to commit all the post cards to the DOM
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        requestAnimationFrame(() => {
                            window.scrollTo(0, scrollY);
                        });
                    });
                });
            }
        } catch (_) { }
    }, [urlTopic, stableOrder.length]);

    // Listen for global hard refresh requests (from header)
    useEffect(() => {
        const handler = () => {
            try {
                forceHardRefreshRef.current = true;
                setIsLoading(true);
                setIsLoadingMore(false);
                try {
                    loadMoreLockRef.current = false;
                } catch (_) { }
                setHasMorePosts(false);
                setCurrentPage(1);
                setStableOrder([]);
                // Refresh current visible topic
                getPosts(urlTopic, null, 1);
            } catch (_) {/* noop */ }
        };
        const applyBlockedTopic = raw => {
            const topic = String(raw || '').trim().toLowerCase();
            if (!topic) return;
            setBlockedTopicsLocal(prev => new Set([...prev, topic]));
            console.debug('[blocked_topics] optimistic pattern added', {
                topic
            });
        };
        const removeBlockedTopic = raw => {
            const topic = String(raw || '').trim().toLowerCase();
            if (!topic) return;
            setBlockedTopicsLocal(prev => {
                const next = new Set(prev);
                next.delete(topic);
                return next;
            });
            console.debug('[blocked_topics] optimistic pattern removed', {
                topic
            });
        };
        const onTopicBlocked = e => {
            applyBlockedTopic(e?.detail?.topic || '');
            handler();
        };
        const onTopicUnblocked = e => {
            removeBlockedTopic(e?.detail?.topic || '');
            handler();
        };
        window.addEventListener('mirageRefreshFeed', handler);
        window.addEventListener('topicBlocked', onTopicBlocked);
        window.addEventListener('topicUnblocked', onTopicUnblocked);
        return () => {
            window.removeEventListener('mirageRefreshFeed', handler);
            window.removeEventListener('topicBlocked', onTopicBlocked);
            window.removeEventListener('topicUnblocked', onTopicUnblocked);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [getPosts, urlTopic]);
    return {
        urlTopic,
        currentTopicRef,
        error,
        stableOrder,
        setStableOrder,
        isLoading,
        hasMorePosts,
        homeSortMode,
        setHomeSortMode,
        oldRedditSort,
        handleOldRedditSortChange,
        cardSize,
        handleCardSizeChange,
        hideDownvotedPosts,
        hidingPostsSet,
        flashingPostsSet,
        isLoadingMore,
        isMobile,
        isTopicBlockedLocal,
        location,
        viewerAddress,
        followedTopicsSet,
        setFollowedTopicsSet,
        topicFollowHover,
        setTopicFollowHover,
        isTopicPending,
        formatTopicStatus,
        forceHardRefreshRef,
        dismissAndroidBanner,
        dismissIPhoneBanner,
        showNsfwHero,
        showModerationReminder,
        dismissModerationReminder,
        snoozeModerationReminder,
        isLoggedIn,
        inviteCodesEnabled,
        questsEnabled,
        openBrowsingEnabled,
        nodeConfigLoaded: Boolean(nodeConfig),
        showAndroidBanner,
        showIPhoneBanner,
        inviteModalOpen,
        setInviteModalOpen,
        inviteCodeCopied,
        welcomeStats,
        welcomeStatsStale,
        inviteBannerCollapsed,
        questCardCollapsed,
        toggleInviteBanner,
        toggleQuestCard,
        nextAvailableCode,
        availableCodeCount,
        handleOpenInviteModal,
        handleCopyInviteCode,
        handleNativeShare,
        canNativeShare,
        getShareUrl,
        getShareText,
        handleNsfwChoice,
        bottomSentinelRef,
        loadMore
    };
}
