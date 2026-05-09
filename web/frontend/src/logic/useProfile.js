import { useEffect, useMemo, useRef, useState } from "react";
import { useTheme } from "styled-components";
import { useNavigate, useLocation, useParams } from "react-router-dom";
import { bech32 } from "bech32";
import Storage from "../utils/Storage";
import { getAllowedTagsParam } from "../utils/ContentTags";
import Api from "../utils/api";
import * as tx from "../utils/tx";
import { getThemeFamily } from "../registry/theme";
import { useTabs } from "./useTabs.js";
import { follow, unfollow, isFollowingAsync, invalidateCache as invalidateFollowCache } from "../utils/FollowUsers";
import { useTxStatus } from "./useTxStatus.js";
import { resolveUsernames as resolveUsernamesCached } from "../utils/UsernameCache";
import { formatMirage, formatMirageCompact } from "../utils/formatters";
import { usePendingSends } from "./usePendingSends.js";
import { usePendingSubscribes } from "./usePendingSubscribes.js";

// (no footer actions here; sign out moved to header menu)

//

const isValidMirageAddress = value => {
    if (!value) return false;
    const trimmed = String(value).trim();
    if (!trimmed) return false;
    const candidate = trimmed.toLowerCase();
    if (!candidate.startsWith('mirage1')) return false;
    try {
        const decoded = bech32.decode(candidate);
        return decoded && decoded.prefix === 'mirage';
    } catch (_) {
        return false;
    }
};
export function useProfile({
    state
}) {
    const navigate = useNavigate();
    const location = useLocation();
    const routeParams = useParams();
    const theme = useTheme();
    const username = state && state.username ? state.username : Storage.load('username', '');
    const address = state && state.publicKey ? state.publicKey : Storage.load('publicKey', '');
    // State for username resolution (for /u/:identity route)
    const [resolvedAddress, setResolvedAddress] = useState(null);
    const [usernameResolutionError, setUsernameResolutionError] = useState(null);
    const [isResolvingUsername, setIsResolvingUsername] = useState(false);
    const routeIdentity = routeParams.identity || '';

    // Resolve username to address for /u/:identity route
    useEffect(() => {
        if (!routeIdentity) {
            setResolvedAddress(null);
            setUsernameResolutionError(null);
            return;
        }
        // If identity is a valid mirage bech32 address, treat as address directly
        if (isValidMirageAddress(routeIdentity)) {
            setResolvedAddress(routeIdentity.trim().toLowerCase());
            setUsernameResolutionError(null);
            return;
        }
        // Otherwise, resolve username to address
        setIsResolvingUsername(true);
        setUsernameResolutionError(null);
        Api.get('get_address_from_username', {
            username: routeIdentity
        }).then(res => {
            setIsResolvingUsername(false);
            if (res && res.exists && res.address) {
                setResolvedAddress(res.address);
            } else {
                setUsernameResolutionError(`User "${routeIdentity}" not found`);
                setResolvedAddress(null);
            }
        }).catch(err => {
            setIsResolvingUsername(false);
            console.error('[ProfileView] Failed to resolve username:', err);
            setUsernameResolutionError(`Failed to look up user "${routeIdentity}"`);
            setResolvedAddress(null);
        });
    }, [routeIdentity]);
    const profileAddress = useMemo(() => {
        if (routeIdentity) {
            if (isValidMirageAddress(routeIdentity)) return routeIdentity.trim().toLowerCase();
            return resolvedAddress || '';
        }
        return address || '';
    }, [routeIdentity, resolvedAddress, address]);
    const normalizedOwn = (address || '').trim().toLowerCase();
    const normalizedProfile = (profileAddress || '').trim().toLowerCase();
    const isOwnProfile = normalizedOwn && normalizedProfile ? normalizedOwn === normalizedProfile : Boolean(normalizedOwn) && !routeIdentity;
    const VALID_TABS = theme.caps.profileTabs;
    const [activeTab, setActiveTab] = useTabs(theme.caps.profileDefaultTab, VALID_TABS);
    const profileUsesListFeed = theme.caps.profileUsesListFeed;
    const FeedComponent = useMemo(() => getThemeFamily(theme.themeId).Feed, [theme.themeId]);
    const isPostsTab = activeTab === 'submissions' || activeTab === 'comments';
    const [profileUsername, setProfileUsername] = useState(() => isOwnProfile ? username || '' : '');
    const [balance, setBalance] = useState(null);
    const [reserveFunds, setReserveFunds] = useState(null);
    const [profileRegisteredAt, setProfileRegisteredAt] = useState(null);
    const [userLevel, setUserLevel] = useState(0);
    const [subscriptionExpiry, setSubscriptionExpiry] = useState(0);
    const [recentPosts, setRecentPosts] = useState([]);
    const [isLoadingRecentPosts, setIsLoadingRecentPosts] = useState(false);
    const [recentPostsError, setRecentPostsError] = useState('');
    const [activeRecentPost, setActiveRecentPost] = useState('');
    const [recentPage, setRecentPage] = useState(1);
    const [recentHasMore, setRecentHasMore] = useState(false);
    const [recentAutoLoading, setRecentAutoLoading] = useState(false);
    const [recentPostsFilter, setRecentPostsFilter] = useState('all');
    const recentBottomSentinelRef = useRef(null);
    const recentLoadTimerRef = useRef(null);
    const [addressCopied, setAddressCopied] = useState(false);
    const [isFollowingProfile, setIsFollowingProfile] = useState(false);
    const [isFollowInProgress, setIsFollowInProgress] = useState(false);
    const [isUnfollowAction, setIsUnfollowAction] = useState(false);
    const [followHover, setFollowHover] = useState(false);
    const [myQueuePosition, setMyQueuePosition] = useState(null);
    const {
        formatStatusForPosition,
        getMyQueuePosition
    } = useTxStatus();
    const [prefsTopics, setPrefsTopics] = useState([]);
    const [prefsAuthors, setPrefsAuthors] = useState([]);
    const [prefsLoading, setPrefsLoading] = useState(false);
    const [prefsError, setPrefsError] = useState('');
    const [prefAuthorUsernames, setPrefAuthorUsernames] = useState({});
    const [similarUsers, setSimilarUsers] = useState([]);
    const [similarUsersLoading, setSimilarUsersLoading] = useState(false);
    const [similarUsersError, setSimilarUsersError] = useState('');
    const [showAllTopicPrefs, setShowAllTopicPrefs] = useState(false);
    const [showAllAuthorPrefs, setShowAllAuthorPrefs] = useState(false);
    const [showAllSimilarUsers, setShowAllSimilarUsers] = useState(false);

    // Biography state
    const [biography, setBiography] = useState('');
    const [bioEditing, setBioEditing] = useState(false);
    const [bioDraft, setBioDraft] = useState('');
    const [bioSaving, setBioSaving] = useState(false);
    const [bioError, setBioError] = useState('');
    const [bioButtonStatus, setBioButtonStatus] = useState('');
    const [confirmDonate, setConfirmDonate] = useState(false);
    const [donateAmountRaw, setDonateAmountRaw] = useState("10000");
    const [donateMessage, setDonateMessage] = useState(null);
    const [confirmGiftSub, setConfirmGiftSub] = useState(null);
    const [giftSubMessage, setGiftSubMessage] = useState(null);
    const formatPrefWeight = w => {
        const num = Number(w);
        if (!Number.isFinite(num)) return '0';
        return `${num > 0 ? '+' : ''}${num.toFixed(3)}`;
    };
    const colorForWeight = w => w > 0 ? '#22c55e' : w < 0 ? '#f87171' : '#888';
    // Server metrics are shown on ServerView; no local server balance state here
    const hasValidAccount = Boolean(address) && address !== 'guest';
    const {
        isPending: isSendPending,
        formatStatus: formatSendStatus
    } = usePendingSends();
    const {
        isPending: isSubscribePending,
        formatStatus: formatSubscribeStatus
    } = usePendingSubscribes();

    // Fetch preferences for Algo tab
    useEffect(() => {
        if (activeTab !== 'algo' || !profileAddress) return;
        let cancelled = false;
        const fetchPrefs = async () => {
            setPrefsLoading(true);
            setPrefsError('');
            try {
                const data = await Api.get('get_preferences', {
                    address: profileAddress
                });
                if (cancelled) return;
                setPrefsTopics(Array.isArray(data?.topics) ? data.topics : []);
                setPrefsAuthors(Array.isArray(data?.authors) ? data.authors : []);
                setShowAllTopicPrefs(false);
                setShowAllAuthorPrefs(false);
            } catch (err) {
                if (!cancelled) {
                    setPrefsError(err?.message || 'Failed to load preferences');
                }
            } finally {
                if (!cancelled) {
                    setPrefsLoading(false);
                }
            }
        };
        fetchPrefs();
        return () => {
            cancelled = true;
        };
    }, [activeTab, profileAddress]);

    // Resolve author usernames for algo tab
    useEffect(() => {
        const authors = prefsAuthors.map(a => String(a?.user || '')).filter(Boolean);
        if (authors.length === 0) {
            setPrefAuthorUsernames({});
            return;
        }
        let cancelled = false;
        (async () => {
            try {
                const mapping = await resolveUsernamesCached(authors, {
                    timeoutMs: 5000
                });
                if (cancelled) return;
                setPrefAuthorUsernames(mapping || {});
            } catch {
                if (cancelled) return;
                setPrefAuthorUsernames({});
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [prefsAuthors]);

    // Fetch similar users for Algo tab
    useEffect(() => {
        if (activeTab !== 'algo' || !profileAddress) {
            setSimilarUsers([]);
            return;
        }
        let cancelled = false;
        const fetchSimilarUsers = async () => {
            setSimilarUsersLoading(true);
            setSimilarUsersError('');
            try {
                const data = await Api.get('get_similar_users', {
                    address: profileAddress
                }, {
                    timeoutMs: 15000
                });
                if (cancelled) return;
                setSimilarUsers(Array.isArray(data?.similar_users) ? data.similar_users : []);
            } catch (err) {
                if (!cancelled) {
                    setSimilarUsersError(err?.message || 'Failed to load similar users');
                }
            } finally {
                if (!cancelled) {
                    setSimilarUsersLoading(false);
                }
            }
        };
        fetchSimilarUsers();
        return () => {
            cancelled = true;
        };
    }, [activeTab, profileAddress]);

    // Reset data when profile changes
    useEffect(() => {
        setPrefsTopics([]);
        setPrefsAuthors([]);
        setPrefsError('');
        setPrefAuthorUsernames({});
        setSimilarUsers([]);
        setSimilarUsersError('');
    }, [profileAddress]);
    useEffect(() => {
        setConfirmDonate(false);
        setDonateMessage(null);
        setDonateAmountRaw("10000");
    }, [profileAddress]);
    useEffect(() => {
        if (isOwnProfile) {
            setProfileUsername(username || '');
        } else {
            setProfileUsername('');
        }
    }, [isOwnProfile, username, profileAddress]);

    // Fetch user status whenever the profile address changes. The header /
    // aside card (username, balance, reserve, joined, tier, biography) are
    // visible on every tab, so the fetch must not be gated on `activeTab`.
    // Previously this was scoped to the Profile tab only, which meant
    // landing on the page with `?tab=comments|submissions|algo` (e.g. after
    // hitting "back" from a post / comment / algo link) left the header and
    // aside blank until the user manually switched to the Profile tab.
    useEffect(() => {
        if (!profileAddress) return;
        let cancelled = false;
        const fetchUserStatus = async () => {
            try {
                const data = await Api.get('get_user_status', {
                    address: profileAddress,
                    _cb: Date.now()
                });
                if (!data || cancelled) return;
                if (isOwnProfile) {
                    try {
                        await tx.cacheUserStatus(data);
                    } catch (_) { }
                }
                if (typeof data.username === 'string' && data.username) {
                    setProfileUsername(data.username);
                } else if (isOwnProfile) {
                    setProfileUsername(username || '');
                }

                // Set balance from API response (works for both own and other profiles)
                const balanceVal = data.balance !== undefined ? data.balance : data.user_balance;
                if (typeof balanceVal !== 'undefined') {
                    const asInt = Number(balanceVal);
                    if (Number.isFinite(asInt)) {
                        setBalance(asInt);
                    }
                } else {
                    setBalance(null);
                }
                if (typeof data.reserve_funds !== 'undefined') {
                    const rf = Number(data.reserve_funds);
                    if (Number.isFinite(rf)) {
                        setReserveFunds(rf);
                    }
                } else {
                    setReserveFunds(null);
                }
                if (typeof data.profile_registered_at !== 'undefined' && data.profile_registered_at !== null) {
                    const ts = Number(data.profile_registered_at);
                    setProfileRegisteredAt(Number.isFinite(ts) ? ts : null);
                } else {
                    setProfileRegisteredAt(null);
                }
                if (typeof data.user_level === 'number') {
                    setUserLevel(data.user_level);
                } else {
                    setUserLevel(0);
                }
                if (typeof data.subscription_expiry === 'number') {
                    setSubscriptionExpiry(data.subscription_expiry);
                } else {
                    setSubscriptionExpiry(0);
                }
            } catch (_) {
                if (!cancelled) {
                    setBalance(null);
                    setReserveFunds(null);
                    setProfileRegisteredAt(null);
                }
            }
        };
        const fetchBiography = async () => {
            try {
                const data = await Api.get('get_profile', {
                    address: profileAddress,
                    _cb: Date.now()
                });
                if (!data || cancelled) return;
                setBiography(data.biography || '');
            } catch (_) {
                if (!cancelled) setBiography('');
            }
        };
        fetchUserStatus();
        fetchBiography();
        return () => {
            cancelled = true;
        };
    }, [profileAddress, isOwnProfile, username]);
    useEffect(() => {
        if (isOwnProfile || !address || !profileAddress) {
            setIsFollowingProfile(false);
            return;
        }
        let cancelled = false;
        isFollowingAsync(address, profileAddress).then(following => {
            if (!cancelled) setIsFollowingProfile(following);
        }).catch(() => {
            if (!cancelled) setIsFollowingProfile(false);
        });
        return () => {
            cancelled = true;
        };
    }, [isOwnProfile, address, profileAddress]);
    useEffect(() => {
        setRecentPosts([]);
        setRecentPage(1);
        setRecentHasMore(false);
        setRecentPostsError('');
        setRecentAutoLoading(false);
        setRecentPostsFilter('all');
        if (recentLoadTimerRef.current) {
            clearTimeout(recentLoadTimerRef.current);
            recentLoadTimerRef.current = null;
        }
    }, [profileAddress]);
    const effectivePostsFilter = activeTab === 'submissions' ? 'submissions' : activeTab === 'comments' ? 'comments' : profileUsesListFeed ? 'all' : recentPostsFilter;
    useEffect(() => {
        setRecentPosts([]);
        setRecentPage(1);
        setRecentHasMore(false);
        setRecentPostsError('');
        setRecentAutoLoading(false);
        if (recentLoadTimerRef.current) {
            clearTimeout(recentLoadTimerRef.current);
            recentLoadTimerRef.current = null;
        }
    }, [effectivePostsFilter]);

    // Lazy-load posts only when a posts-related tab is active
    useEffect(() => {
        let cancelled = false;
        if (!profileAddress || !isPostsTab) {
            return;
        }
        const fetchRecentPosts = async () => {
            setIsLoadingRecentPosts(true);
            setRecentAutoLoading(false);
            setRecentPostsError('');
            try {
                const params = {
                    owner: profileAddress,
                    limit: 50,
                    page: recentPage
                };
                if (address) params.address = address;
                if (effectivePostsFilter === 'submissions' || effectivePostsFilter === 'comments') {
                    params.type = effectivePostsFilter;
                }
                params.allowed_tags = getAllowedTagsParam();
                const res = await Api.get('get_user_posts', params);
                if (cancelled) return;
                const raw = Array.isArray(res?.posts) ? res.posts : [];
                // Comments don't carry a `title` (parent post owns it) and the
                // backend explicitly forbids a `topic` on comments. The shared
                // FeedRow renderer drops any row missing either field, so we
                // synthesize both here when rendering the Comments tab — title
                // from the body's first line, topic from the parent post id —
                // so users actually see their replies. Submissions untouched.
                const incoming = (effectivePostsFilter === 'comments')
                    ? raw.map(p => {
                        if (!p) return p;
                        const next = { ...p };
                        const hasTitle = typeof next.title === 'string' && next.title.trim() !== '';
                        if (!hasTitle) {
                            const body = typeof next.content === 'string' ? next.content : '';
                            const firstLine = body.split(/\r?\n/).find(l => l.trim() !== '') || '';
                            const snippet = firstLine.trim().slice(0, 80);
                            next.title = snippet ? (snippet + (firstLine.trim().length > 80 ? '…' : '')) : '(reply)';
                        }
                        const hasTopic = typeof next.topic === 'string' && next.topic.trim() !== '';
                        if (!hasTopic) {
                            // Prefer the parent post's topic (`root_topic`) when
                            // the backend includes it — that's the real topic
                            // users care about. Fall back to a `comment-<short>`
                            // placeholder (keyed off root post id) so the shared
                            // FeedRow renderer still accepts the row.
                            const rootTopic = typeof next.root_topic === 'string' ? next.root_topic.trim() : '';
                            if (rootTopic) {
                                next.topic = rootTopic;
                            } else {
                                const root = (typeof next.root_post_id === 'string' && next.root_post_id) ? next.root_post_id : (next.target || '');
                                const shortRoot = root ? String(root).slice(0, 8) : 'reply';
                                next.topic = `comment-${shortRoot}`;
                            }
                        }
                        return next;
                    })
                    : raw;
                const hasMore = !!res?.has_more;
                setRecentHasMore(hasMore);
                setRecentPosts(prev => {
                    if (recentPage === 1) {
                        return incoming;
                    }
                    const existing = new Set(prev.map(p => p?.post_id));
                    const filtered = incoming.filter(p => p && p.post_id && !existing.has(p.post_id));
                    return [...prev, ...filtered];
                });
            } catch (err) {
                if (!cancelled) {
                    setRecentPostsError(err?.message || 'Failed to load posts');
                }
            } finally {
                if (!cancelled) {
                    setIsLoadingRecentPosts(false);
                }
            }
        };
        fetchRecentPosts();
        return () => {
            cancelled = true;
        };
    }, [profileAddress, address, recentPage, effectivePostsFilter, activeTab, isPostsTab]);

    // Reset posts when profile changes
    useEffect(() => {
        setRecentPosts([]);
        setRecentPostsError('');
        setRecentHasMore(false);
        setIsLoadingRecentPosts(false);
    }, [profileAddress]);
    useEffect(() => {
        const el = recentBottomSentinelRef.current;
        if (!el) return;
        if (!recentHasMore || isLoadingRecentPosts) {
            return;
        }

        // Safari-compatible IntersectionObserver configuration
        const observer = new IntersectionObserver(entries => {
            const entry = entries[0];
            if (entry && entry.isIntersecting) {
                setRecentAutoLoading(true);
                if (recentLoadTimerRef.current) clearTimeout(recentLoadTimerRef.current);
                recentLoadTimerRef.current = window.setTimeout(() => {
                    setRecentPage(prev => prev + 1);
                }, 1000);
            }
        }, {
            root: null,
            rootMargin: '0px',
            threshold: 0.01
        });
        observer.observe(el);
        return () => {
            observer.disconnect();
            if (recentLoadTimerRef.current) {
                clearTimeout(recentLoadTimerRef.current);
                recentLoadTimerRef.current = null;
            }
        };
    }, [recentHasMore, isLoadingRecentPosts]);

    // no copy buttons requested; show full values with wrapping

    const shortenAddress = addr => {
        if (!addr) return '';
        if (addr.length <= 24) return addr;
        return `${addr.slice(0, 14)}...${addr.slice(-8)}`;
    };
    const formatRegistrationDate = ts => {
        const num = Number(ts);
        // Default to 2025-11-01 00:00 UTC if no registration date available
        if (!Number.isFinite(num) || num <= 0) {
            return '2025-11-01 00:00 UTC';
        }
        const date = new Date(num * 1000);
        if (Number.isNaN(date.getTime())) {
            return '2025-11-01 00:00 UTC';
        }
        const pad = value => String(value).padStart(2, '0');
        const year = date.getFullYear();
        const month = pad(date.getMonth() + 1);
        const day = pad(date.getDate());
        const hours = pad(date.getHours());
        const minutes = pad(date.getMinutes());
        const tz = date.toLocaleTimeString('en-US', {
            timeZoneName: 'short'
        }).split(' ').pop();
        return `${year}-${month}-${day} ${hours}:${minutes} ${tz}`;
    };
    const getTierName = level => {
        const names = {
            0: 'Free',
            1: 'Subscriber',
            10: 'Agent'
        };
        if (level >= 100) return 'Admin';
        return names[level] || 'Free';
    };
    const getTierColor = level => {
        const colors = {
            0: '#6B7280',
            1: '#F59E0B',
            10: '#EF4444'
        };
        if (level >= 100) return '#EF4444';
        return colors[level] || colors[0];
    };
    const formatSubscriptionExpiry = timestamp => {
        if (!timestamp || timestamp <= 0) return null;
        const date = new Date(timestamp * 1000);
        const now = new Date();
        if (date <= now) return null; // Don't show "Expired" in profile - tier handles this via EndBlock

        const diffMs = date - now;
        const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        if (days > 0) return `${days} day${days === 1 ? '' : 's'} remaining`;
        const hours = Math.floor(diffMs / (1000 * 60 * 60));
        if (hours > 0) return `${hours} hour${hours === 1 ? '' : 's'} remaining`;
        const mins = Math.floor(diffMs / (1000 * 60));
        return `${mins} minute${mins === 1 ? '' : 's'} remaining`;
    };
    const formatElapsed = ts => {
        const num = Number(ts);
        if (!Number.isFinite(num) || num <= 0) return 'unknown';
        const now = Math.floor(Date.now() / 1000);
        let delta = Math.max(0, now - num);
        if (delta < 60) return `${delta}s`;
        if (delta < 3600) return `${Math.floor(delta / 60)}m`;
        if (delta < 86400) return `${Math.floor(delta / 3600)}h`;
        if (delta < 86400 * 365) return `${Math.floor(delta / 86400)}d`;
        return `${Math.floor(delta / (86400 * 365))}y`;
    };
    const truncateContent = (text, maxLen = 180) => {
        if (!text) return '';
        const trimmed = String(text).trim();
        if (trimmed.length <= maxLen) return trimmed;
        return `${trimmed.slice(0, maxLen - 3)}...`;
    };
    const buildMetaLine = post => {
        const parts = [];
        parts.push(`posted ${formatElapsed(post.timestamp)} ago`);
        const isComment = post.target && post.target.trim() !== '';
        if (!isComment) {
            const topicPart = post.topic ? `#${post.topic}` : 'no topic';
            parts.push(`in ${topicPart}`);
        }
        const rawPoints = typeof post.points === 'number' ? post.points : Number(post.points) || 0;
        const userWeight = typeof post.user_weight === 'number' ? post.user_weight : Number(post.user_weight) || 0;
        const userVote = typeof post.user_vote === 'number' ? post.user_vote : Number(post.user_vote) || 0;
        const adjustedPoints = rawPoints - userWeight + userVote;
        const points = Math.round(adjustedPoints);
        const formattedPoints = points >= 0 ? `+${points}` : `${points}`;
        parts.push(`(${formattedPoints} points)`);
        return parts.join(' ');
    };
    const renderPostPreview = post => {
        if (!post) return null;
        const isComment = post.target && post.target.trim() !== '';
        if (isComment) {
            const head = post.content ? truncateContent(post.content) : '(comment)';
            return head || '(comment)';
        }
        return post.title || truncateContent(post.content) || '(untitled post)';
    };

    // Helper functions for better UX
    const handleFollowToggle = async () => {
        if (isOwnProfile || !address || !profileAddress || isFollowInProgress) return;
        const queuePos = await getMyQueuePosition();
        setMyQueuePosition(queuePos);
        setIsFollowInProgress(true);
        const wasFollowing = isFollowingProfile;
        setIsUnfollowAction(wasFollowing);
        setIsFollowingProfile(!wasFollowing); // Optimistic update
        try {
            if (wasFollowing) {
                await unfollow(address, profileAddress);
            } else {
                await follow(address, profileAddress);
            }
            invalidateFollowCache();
        } catch (e) {
            console.error('[ProfileView] Follow toggle error:', e);
            setIsFollowingProfile(wasFollowing); // Revert on error
        } finally {
            setIsFollowInProgress(false);
            setIsUnfollowAction(false);
            setMyQueuePosition(null);
        }
    };
    const getPostUrl = post => {
        if (!post || !post.post_id) return '#';
        const isComment = post.target && post.target.trim() !== '';
        return isComment ? `/p/${post.post_id}?depth=1` : `/p/${post.post_id}`;
    };
    const handleRecentPostClick = async (post, e) => {
        if (!post || !post.post_id) return;
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        setActiveRecentPost(post.post_id);
        try {
            Storage.setPendingPostHighlight(post.post_id);
        } catch (_) { }
        navigate(getPostUrl(post));
    };
    const usernameDisplay = profileUsername || (isOwnProfile ? username : '') || '(loading...)';
    const balanceDisplay = profileAddress ? balance === null ? '(loading...)' : `${formatMirage(balance)} MIRAGE` : '(address required)';
    const reserveDisplay = profileAddress ? reserveFunds === null ? '(loading...)' : `${formatMirage(reserveFunds)} MIRAGE` : '(address required)';
    const registeredDisplay = formatRegistrationDate(profileRegisteredAt);
    const canEditProfile = isOwnProfile && Boolean(address);
    const donatePending = isSendPending(profileAddress);
    const donateStatus = formatSendStatus(profileAddress);
    const profileTitle = profileUsername ? `@${profileUsername}` : profileAddress ? `${profileAddress.slice(0, 10)}...` : 'Profile';
    const canHaveBiography = userLevel > 0;
    const BIO_MAX = 512;
    const handleBioSave = async () => {
        const trimmed = bioDraft.trim();
        if (trimmed.length > BIO_MAX) {
            setBioError(`Biography too long (${trimmed.length}/${BIO_MAX})`);
            return;
        }
        setBioSaving(true);
        setBioError('');
        setBioButtonStatus('Processing');
        try {
            const result = await tx.setBiography(trimmed);
            if (!result || !result.success) {
                setBioError(String(result?.error || 'Failed to update biography'));
                setBioSaving(false);
                setBioButtonStatus('');
                return;
            }
            const txHash = result.tx_hash ? String(result.tx_hash).toLowerCase() : '';
            if (txHash) {
                const pollResult = await tx.pollTxStatus(txHash, {
                    initialDelay: 3000,
                    interval: 2000,
                    maxAttempts: 5
                });
                if (pollResult && !pollResult.success) {
                    setBioError(pollResult.error_details?.message || 'Transaction rejected');
                    setBioSaving(false);
                    setBioButtonStatus('');
                    return;
                }
            }
            setBiography(trimmed);
            setBioEditing(false);
            setBioSaving(false);
            setBioButtonStatus('');
        } catch (e) {
            setBioError(String(e?.message || e));
            setBioSaving(false);
            setBioButtonStatus('');
        }
    };
    const formatDonateAmount = value => {
        const digits = String(value || "").replace(/[^\d]/g, "");
        if (!digits) return "";
        return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    };
    const handleDonate = () => {
        if (!profileAddress || !hasValidAccount) {
            setDonateMessage({
                type: 'error',
                message: 'Please log in to gift MIRAGE'
            });
            setTimeout(() => setDonateMessage(null), 5000);
            return;
        }
        console.debug('[ProfileView] gift-mirage.open', {
            target: profileAddress
        });
        setDonateAmountRaw("10000");
        setDonateMessage(null);
        setConfirmGiftSub(null);
        setGiftSubMessage(null);
        setConfirmDonate(true);
    };
    const confirmDonateAction = async () => {
        if (!profileAddress || !hasValidAccount) return;
        if (donatePending) return;
        const amount = parseInt(String(donateAmountRaw || "").replace(/[^\d]/g, ""), 10);
        if (!Number.isFinite(amount) || amount < 10000) {
            setDonateMessage({
                type: 'error',
                message: 'Minimum gift is 10,000 MIRAGE'
            });
            setTimeout(() => setDonateMessage(null), 5000);
            setConfirmDonate(false);
            return;
        }
        console.debug('[ProfileView] donate.submit', {
            target: profileAddress,
            amount
        });
        try {
            const result = await tx.sendTokens(profileAddress, amount);
            setConfirmDonate(false);
            if (result.success) {
                setDonateMessage({
                    type: 'success',
                    message: `Successfully sent ${Number(amount).toLocaleString()} MIRAGE!`
                });
            } else {
                const raw = String(result?.error || 'Transaction failed');
                setDonateMessage({
                    type: 'error',
                    message: `Failed: ${raw}`
                });
            }
            setTimeout(() => setDonateMessage(null), 5000);
        } catch (error) {
            console.error("Donate error:", error);
            setConfirmDonate(false);
            setDonateMessage({
                type: 'error',
                message: `Error: ${error.message || error}`
            });
            setTimeout(() => setDonateMessage(null), 5000);
        }
    };
    const cancelDonate = () => {
        setConfirmDonate(false);
    };

    const subFeePending = isSubscribePending(profileAddress);
    const subFeeStatus = formatSubscribeStatus(profileAddress);

    /* Re-evaluate when chainConfig lands after mount (e.g. fresh profile
     * navigate). Mirrors `usePostGifts`' `configUpdateTrigger` listener so
     * the GiftSubscriptionDialog shows the Fee row + insufficient-balance
     * guard identically to the post-options flow. */
    const [chainConfigTick, setChainConfigTick] = useState(0);
    useEffect(() => {
        const bump = () => setChainConfigTick(prev => prev + 1);
        window.addEventListener('chainConfigUpdated', bump);
        window.addEventListener('userStatusUpdated', bump);
        try {
            if (tx.needsChainConfigRefresh && tx.needsChainConfigRefresh()) {
                Api.get('get_chain_config', undefined)
                    .then(cfg => {
                        if (cfg) {
                            try { tx.cacheChainConfig(cfg); } catch (_) { }
                        }
                    })
                    .catch(() => { });
            }
        } catch (_) { /* noop */ }
        return () => {
            window.removeEventListener('chainConfigUpdated', bump);
            window.removeEventListener('userStatusUpdated', bump);
        };
    }, []);

    const { subFeeLabel, agentFeeLabel, subFeeUmirage, agentFeeUmirage } = useMemo(() => {
        void chainConfigTick;
        try {
            const raw = localStorage.getItem('chainConfig');
            const cfg = raw ? JSON.parse(raw) : null;
            const tiers = cfg?.subscription_tiers || cfg?.tiers || [];
            const sf = Number(tiers?.[1]?.period_fee || 0);
            const af = Number(tiers?.[2]?.period_fee || 0);
            return {
                subFeeLabel: sf > 0 ? formatMirageCompact(sf) + ' MIRAGE' : null,
                agentFeeLabel: af > 0 ? formatMirageCompact(af) + ' MIRAGE' : null,
                subFeeUmirage: sf > 0 ? sf : null,
                agentFeeUmirage: af > 0 ? af : null,
            };
        } catch (_) { }
        return { subFeeLabel: null, agentFeeLabel: null, subFeeUmirage: null, agentFeeUmirage: null };
    }, [chainConfigTick]);

    const handleGiftSub = () => {
        if (!profileAddress || !hasValidAccount) {
            setGiftSubMessage({
                type: 'error',
                message: 'Please log in to gift a subscription'
            });
            setTimeout(() => setGiftSubMessage(null), 5000);
            return;
        }
        if (isSubscribePending(profileAddress)) return;
        const level = (userLevel >= 10) ? 10 : 1;
        console.debug('[ProfileView] gift-subscribe.confirm', { target: profileAddress, level });
        setConfirmDonate(false);
        setDonateMessage(null);
        setGiftSubMessage(null);
        setConfirmGiftSub({ level, target: profileAddress, loading: true, expiryLabel: null, error: null });
        void (async () => {
            let cfg = null;
            try {
                const raw = localStorage.getItem('chainConfig');
                cfg = raw ? JSON.parse(raw) : null;
            } catch (e) {
                console.debug('[ProfileView] gift-subscribe.config-error', e);
            }
            if (!cfg || !Number(cfg.subscription_period || 0)) {
                try {
                    const fetched = await Api.get('get_chain_config', undefined);
                    if (fetched && typeof fetched === 'object') {
                        try { tx.cacheChainConfig(fetched); } catch (_) { }
                        cfg = fetched;
                    }
                } catch (e) {
                    console.debug('[ProfileView] gift-subscribe.config-fetch-error', e);
                }
            }
            const periodMinutes = Number(cfg?.subscription_period || 0);
            if (!periodMinutes || periodMinutes <= 0) {
                console.debug('[ProfileView] gift-subscribe.config-invalid', { periodMinutes });
                setConfirmGiftSub((prev) => (prev && prev.target === profileAddress ? { ...prev, loading: false, error: 'Invalid subscription period' } : prev));
                return;
            }
            try {
                const pre = await Api.get('get_user_status', { address: profileAddress, _cb: Date.now() });
                const currentExp = Number(pre?.subscription_expiry || 0);
                const nowSec = Math.floor(Date.now() / 1000);
                const isExtension = currentExp > nowSec;
                const base = Math.max(nowSec, currentExp);
                const expectedExp = base + periodMinutes * 60;
                const dateStr = new Date(expectedExp * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
                const label = isExtension ? `Extend until ${dateStr}` : `Until ${dateStr}`;
                console.debug('[ProfileView] gift-subscribe.expected', { target: profileAddress, level, currentExp, expectedExp });
                setConfirmGiftSub((prev) => (prev && prev.target === profileAddress ? { ...prev, loading: false, expiryLabel: label, error: null } : prev));
            } catch (e) {
                console.debug('[ProfileView] gift-subscribe.status-error', e);
                setConfirmGiftSub((prev) => (prev && prev.target === profileAddress ? { ...prev, loading: false, error: 'Failed to load recipient status' } : prev));
            }
        })();
    };

    const confirmGiftSubAction = async () => {
        if (!profileAddress) return;
        if (isSubscribePending(profileAddress)) return;
        if (confirmGiftSub?.loading || confirmGiftSub?.error) return;
        const giftLevel = confirmGiftSub?.level || 1;
        const target = confirmGiftSub?.target || profileAddress;
        const expiryLabel = confirmGiftSub?.expiryLabel || null;
        if (!expiryLabel) {
            setConfirmGiftSub((prev) => (prev ? { ...prev, error: 'Missing expected expiry' } : prev));
            return;
        }
        try {
            console.debug('[ProfileView] gift-subscribe.submit', { target, level: giftLevel });
            const result = await tx.subscribe(giftLevel, 0, target);
            setConfirmGiftSub(null);
            if (result.success) {
                const isAgent = giftLevel === 10;
                let msg = isAgent ? 'Agent subscription gifted!' : 'Subscription gifted!';
                msg += ` ${expiryLabel}`;
                setGiftSubMessage({ type: 'success', message: msg });
            } else {
                const raw = String(result.error || 'Transaction failed');
                const friendly = raw.replace(/^HTTP \d+:\s*/i, '').replace(/^Failed:\s*/i, '');
                setGiftSubMessage({ type: 'error', message: friendly });
            }
            setTimeout(() => setGiftSubMessage(null), 8000);
        } catch (error) {
            setConfirmGiftSub(null);
            setGiftSubMessage({ type: 'error', message: `${error.message || error}` });
            setTimeout(() => setGiftSubMessage(null), 5000);
        }
    };

    const cancelGiftSub = () => {
        console.debug('[ProfileView] gift-subscribe.cancel', { target: profileAddress || null });
        setConfirmGiftSub(null);
    };

    // Show loading/error states for username resolution
    return {
        navigate,
        location,
        theme,
        address,
        usernameResolutionError,
        isResolvingUsername,
        routeIdentity,
        profileAddress,
        isOwnProfile,
        VALID_TABS,
        activeTab,
        setActiveTab,
        profileUsesListFeed,
        FeedComponent,
        isPostsTab,
        profileUsername,
        userLevel,
        subscriptionExpiry,
        recentPosts,
        isLoadingRecentPosts,
        recentPostsError,
        activeRecentPost,
        recentPage,
        recentAutoLoading,
        recentPostsFilter,
        setRecentPostsFilter,
        recentBottomSentinelRef,
        addressCopied,
        setAddressCopied,
        isFollowingProfile,
        isFollowInProgress,
        isUnfollowAction,
        followHover,
        setFollowHover,
        myQueuePosition,
        formatStatusForPosition,
        prefsTopics,
        prefsAuthors,
        prefsLoading,
        prefsError,
        prefAuthorUsernames,
        similarUsers,
        similarUsersLoading,
        similarUsersError,
        showAllTopicPrefs,
        setShowAllTopicPrefs,
        showAllAuthorPrefs,
        setShowAllAuthorPrefs,
        showAllSimilarUsers,
        setShowAllSimilarUsers,
        biography,
        bioEditing,
        setBioEditing,
        bioDraft,
        setBioDraft,
        bioSaving,
        bioError,
        setBioError,
        bioButtonStatus,
        confirmDonate,
        donateAmountRaw,
        setDonateAmountRaw,
        donateMessage,
        formatPrefWeight,
        colorForWeight,
        hasValidAccount,
        effectivePostsFilter,
        shortenAddress,
        getTierName,
        getTierColor,
        formatSubscriptionExpiry,
        buildMetaLine,
        renderPostPreview,
        handleFollowToggle,
        getPostUrl,
        handleRecentPostClick,
        usernameDisplay,
        balance,
        reserveFunds,
        profileRegisteredAt,
        balanceDisplay,
        reserveDisplay,
        registeredDisplay,
        canEditProfile,
        donatePending,
        donateStatus,
        profileTitle,
        canHaveBiography,
        BIO_MAX,
        handleBioSave,
        formatDonateAmount,
        handleDonate,
        confirmDonateAction,
        cancelDonate,
        confirmGiftSub,
        giftSubMessage,
        subFeePending,
        subFeeStatus,
        subFeeLabel,
        agentFeeLabel,
        subFeeUmirage,
        agentFeeUmirage,
        handleGiftSub,
        confirmGiftSubAction,
        cancelGiftSub
    };
}
