import React, { useEffect, useMemo, useRef, useState } from "react";
import { Helmet } from 'react-helmet-async';
import styled from "styled-components";
import { useNavigate, useLocation, useParams } from 'react-router-dom';
import { bech32 } from 'bech32';
import Storage from "../utils/Storage";
import seedVault from "../utils/SeedVault";
import { derivePrivateKeyFromSeed, derivePublicKeyFromSeed } from "../utils/CryptoUtils";
import Api from '../lib/api';
import * as tx from '../utils/tx';
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import Button from "../components/Button";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, TabsRow, ClickableTab } from "../styled/Layout";
import { useTabs } from "../utils/useTabs";
import { follow, unfollow, isFollowingAsync, invalidateCache as invalidateFollowCache } from "../utils/FollowUsers";
import { tooltipStyles } from "../components/Tooltip";
import { useTxStatus } from "../utils/useTxStatus";
import { resolveUsernames as resolveUsernamesCached } from "../utils/UsernameCache";
import { formatMirage } from "../utils/formatters";

const Row = styled.div`
    display: grid;
    grid-template-columns: 6rem minmax(0, 1fr);
    gap: 0.5rem;
    align-items: start;
    margin: 0.4rem 0;
    @media (max-width: 1000px) {
        grid-template-columns: 1fr;
        gap: 0.35rem;
        align-items: stretch;
    }
`;

const RowCentered = styled(Row)`
    align-items: center;
`;

const Label = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#ccc'};
    font-weight: 600;
    font-size: 0.85rem;
    white-space: nowrap;
    @media (max-width: 1000px) {
        margin-bottom: 0.1rem;
    }
`;

const HoverableLabel = styled.div`
    color: ${({ theme }) => theme?.colors?.subtleText || '#ccc'};
    font-weight: 600;
    font-size: 0.85rem;
    white-space: nowrap;
    ${tooltipStyles('right')}
    
    @media (max-width: 1000px) {
        margin-bottom: 0.1rem;
    }
`;

const ValueBox = styled.div`
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.6rem 0.85rem;
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;

const ValueBoxWithButton = styled(ValueBox)`
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: nowrap;
    overflow: hidden;
    @media (max-width: 1000px) {
        flex-wrap: wrap;
        gap: 0.5rem;
    }
`;


const ModeratorsList = styled.div`
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
`;

const ModeratorTag = styled.div`
    background-color: ${({ theme }) => theme?.colors?.accent || '#2E3238'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 20px;
    padding: 0.35rem 0.75rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8rem;
    opacity: ${props => props.$isRemoving ? 0.6 : 1};
    transition: all 0.2s ease;
`;

const RemoveModeratorButton = styled.button`
    background: none;
    border: none;
    color: ${({ theme }) => theme?.colors?.subtleText || '#ccc'};
    cursor: pointer;
    padding: 0;
    font-size: 0.9rem;
    line-height: 1;
    
    &:hover {
        color: ${({ theme }) => theme?.colors?.text || '#fff'};
    }
`;

const ModeratorInput = styled.input`
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.5rem 0.85rem;
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-size: 0.85rem;
    flex: 1;
    transition: all 0.2s ease;
    
    &:focus {
        outline: none;
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);
    }
`;

const ModeratorInputRow = styled.div`
    display: flex;
    margin-top: 0.5rem;
    align-items: center;
    gap: 0.5rem;
    @media (max-width: 600px) {
        flex-direction: column;
        align-items: stretch;
    }
`;

const ModeratorErrorMessage = styled.div`
    background-color: rgba(220, 38, 38, 0.1);
    border: 1px solid #dc2626;
    border-radius: 3px;
    padding: 0.5rem;
    margin-top: 0.5rem;
    color: #dc2626;
    font-size: 0.8rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

const ModeratorSuccessMessage = styled.div`
    background-color: rgba(34, 197, 94, 0.1);
    border: 1px solid #22c55e;
    border-radius: 3px;
    padding: 0.5rem;
    margin-top: 0.5rem;
    color: #22c55e;
    font-size: 0.8rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

const SectionTitle = styled.div`
    margin-top: ${({ $first }) => $first ? '0' : '1.5rem'};
    margin-bottom: 0.5rem;
    font-weight: 700;
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-size: 0.95rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;

    &::after {
        content: '';
        flex: 1;
        height: 1px;
        background: ${({ theme }) => theme?.colors?.border || '#333'};
    }
`;

const FilterSelect = styled.select`
    width: 100%;
    margin-bottom: 0.75rem;
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.5rem 0.85rem;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    font-size: 0.85rem;
    cursor: pointer;
    transition: all 0.2s ease;
    
    &:focus {
        outline: none;
        border-color: #667eea;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.15);
    }
`;

const PostsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
`;

const PostItem = styled.div`
    border: 1px solid ${({ theme, isActive }) => isActive ? '#667eea' : (theme?.colors?.border || '#444')};
    background-color: ${({ theme, isActive }) => isActive ? 'rgba(102, 126, 234, 0.1)' : (theme?.colors?.panel || '#23272C')};
    border-radius: 8px;
    padding: 0.6rem 0.85rem;
    cursor: pointer;
    transition: background-color 0.2s ease, border-color 0.2s ease;
    box-shadow: ${({ isActive }) => (isActive ? '0 0 12px rgba(102, 126, 234, 0.25)' : 'none')};

    &:hover {
        background-color: ${({ theme }) => theme?.colors?.panelAlt || '#2E3238'};
        border-color: ${({ theme }) => theme?.colors?.subtleText || '#666'};
    }
`;

const PostMeta = styled.div`
    font-size: 0.55rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    margin-bottom: 0.25rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
`;

const PostPreview = styled.div`
    font-size: 0.65rem;
    color: ${({ theme }) => theme?.colors?.text || '#DDDDDD'};
    line-height: 1.3;
    word-break: break-word;
    white-space: pre-line;
`;

const Mono = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#eee'};
    font-size: 0.8rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
`;

// Single-line with ellipsis for short values (e.g., username)
const InlineMono = styled(Mono)`
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
`;

const LoadingSpinner = styled.div`
    width: 16px;
    height: 16px;
    border: 2px solid ${({ theme }) => theme?.colors?.border || theme?.colors?.borderSubtle || '#393E46'};
    border-top: 2px solid ${({ theme }) => theme?.colors?.subtleText || '#bcb1a2'};
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;

const SubtleMono = styled(Mono)`
    color: ${({ theme }) => theme?.colors?.subtleText || '#bcb1a2'};
`;

const LoadingRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.5rem 0 0.75rem;
    padding: 0.5rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#bcb1a2'};
`;

// (no footer actions here; sign out moved to header menu)

//

const isValidMirageAddress = (value) => {
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

export default function ProfileView({ state }) {
    const navigate = useNavigate();
    const location = useLocation();
    const routeParams = useParams();
    const username = (state && state.username) ? state.username : Storage.load('username', '');
    const address = (state && state.publicKey) ? state.publicKey : Storage.load('publicKey', '');
    const seedPhrase = (state && state.seedPhrase) ? state.seedPhrase : (seedVault.getSeed() || '');

    // State for username resolution (for /u/:identity route)
    const [resolvedAddress, setResolvedAddress] = useState(null);
    const [usernameResolutionError, setUsernameResolutionError] = useState(null);
    const [isResolvingUsername, setIsResolvingUsername] = useState(false);

    // Support new clean URL /u/:identity and legacy /profile?address=...
    const routeIdentity = routeParams.identity || '';

    // DEPRECATED: Legacy query params, remove in future release
    const queryAddress = useMemo(() => {
        try {
            const params = new URLSearchParams(location.search);
            const raw = params.get('address');
            return raw ? raw.trim() : '';
        } catch {
            return '';
        }
    }, [location.search]);

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
        Api.get('get_address_from_username', { username: routeIdentity }, { timeoutMs: 10000 })
            .then((res) => {
                setIsResolvingUsername(false);
                if (res && res.exists && res.address) {
                    setResolvedAddress(res.address);
                } else {
                    setUsernameResolutionError(`User "${routeIdentity}" not found`);
                    setResolvedAddress(null);
                }
            })
            .catch((err) => {
                setIsResolvingUsername(false);
                console.error('[ProfileView] Failed to resolve username:', err);
                setUsernameResolutionError(`Failed to look up user "${routeIdentity}"`);
                setResolvedAddress(null);
            });
    }, [routeIdentity]);

    // Determine effective profile address: route identity (resolved) > legacy query > own address
    const profileAddress = useMemo(() => {
        if (routeIdentity) {
            // For /u/:identity route
            if (isValidMirageAddress(routeIdentity)) return routeIdentity.trim().toLowerCase();
            return resolvedAddress || '';
        }
        // Legacy /profile?address=... or own profile
        return queryAddress || address || '';
    }, [routeIdentity, resolvedAddress, queryAddress, address]);

    const normalizedOwn = (address || '').trim().toLowerCase();
    const normalizedProfile = (profileAddress || '').trim().toLowerCase();
    const isOwnProfile = normalizedOwn && normalizedProfile
        ? normalizedOwn === normalizedProfile
        : Boolean(normalizedOwn) && !queryAddress && !routeIdentity;

    const VALID_TABS = ['profile', 'posts', 'follows', 'blocks', 'algo'];
    const [activeTab, setActiveTab] = useTabs('profile', VALID_TABS);
    const [profileUsername, setProfileUsername] = useState(() => (isOwnProfile ? (username || '') : ''));
    const [balance, setBalance] = useState(null);
    const [reserveFunds, setReserveFunds] = useState(null);
    const [profileRegisteredAt, setProfileRegisteredAt] = useState(null);
    const [userLevel, setUserLevel] = useState(0);
    const [subscriptionExpiry, setSubscriptionExpiry] = useState(0);
    const [moderators, setModerators] = useState([]);
    const [moderatorUsernames, setModeratorUsernames] = useState({});
    const [newModeratorInput, setNewModeratorInput] = useState('');
    const [moderatorError, setModeratorError] = useState('');
    const [moderatorSuccess, setModeratorSuccess] = useState('');
    const [isAddingModerator, setIsAddingModerator] = useState(false);
    const [isRemovingModerator, setIsRemovingModerator] = useState('');
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
    const [followedUsers, setFollowedUsers] = useState([]);
    const [followedTopics, setFollowedTopics] = useState([]);
    const [blockedUsers, setBlockedUsers] = useState([]);
    const [blockedPosts, setBlockedPosts] = useState([]);
    const [listsLoading, setListsLoading] = useState(false);
    const [listsError, setListsError] = useState('');
    const [followedUsernames, setFollowedUsernames] = useState({});
    const [blockedUsernames, setBlockedUsernames] = useState({});
    const [addressCopied, setAddressCopied] = useState(false);
    const [isFollowingProfile, setIsFollowingProfile] = useState(false);
    const [isFollowInProgress, setIsFollowInProgress] = useState(false);
    const [isUnfollowAction, setIsUnfollowAction] = useState(false);
    const [followHover, setFollowHover] = useState(false);
    const [myQueuePosition, setMyQueuePosition] = useState(null);
    const { formatStatusForPosition, getMyQueuePosition } = useTxStatus();
    const [prefsTopics, setPrefsTopics] = useState([]);
    const [prefsAuthors, setPrefsAuthors] = useState([]);
    const [prefsLoading, setPrefsLoading] = useState(false);
    const [prefsError, setPrefsError] = useState('');
    const [prefAuthorUsernames, setPrefAuthorUsernames] = useState({});
    const [similarUsers, setSimilarUsers] = useState([]);
    const [similarUsersLoading, setSimilarUsersLoading] = useState(false);
    const [similarUsersError, setSimilarUsersError] = useState('');
    const formatPrefWeight = (w) => {
        const num = Number(w);
        if (!Number.isFinite(num)) return '0';
        return `${num > 0 ? '+' : ''}${num.toFixed(3)}`;
    };
    const colorForWeight = (w) => (w > 0 ? '#22c55e' : w < 0 ? '#f87171' : '#888');
    // Server metrics are shown on ServerView; no local server balance state here
    // const [cfg, setCfg] = useState(() => {
    //     const loadNumber = (key) => {
    //         const val = Storage.load(key, '');
    //         return val === '' ? undefined : Number(val);
    //     };
    //     return {
    //         validator_account_address: Storage.load('validator_account_address', ''),
    //         validator_operator_address: Storage.load('validator_operator_address', ''),
    //         validator_consensus_address: Storage.load('validator_consensus_address', ''),
    //         user_level: loadNumber('user_level'),
    //         min_fee_post: loadNumber('min_fee_post'),
    //         min_fee_comment: loadNumber('min_fee_comment'),
    //         min_fee_vote: loadNumber('min_fee_vote'),
    //         min_fee_set_profile: loadNumber('min_fee_set_profile'),
    //         min_fee_set_mods: loadNumber('min_fee_set_mods'),
    //         min_fee_block_post: loadNumber('min_fee_block_post'),
    //         min_fee_block_user: loadNumber('min_fee_block_user'),
    //         min_fee_delete: loadNumber('min_fee_delete'),
    //         min_fee_send_tokens: loadNumber('min_fee_send_tokens'),
    //         block_time: loadNumber('block_time_seconds'),
    //         pow_difficulty: loadNumber('pow_difficulty_cached'),
    //         paid_vote_multiplier: loadNumber('paid_vote_multiplier'),
    //     };
    // });

    // Fetch follows data when follows tab is opened (always fresh)
    useEffect(() => {
        if (activeTab !== 'follows' || !profileAddress) return;
        let cancelled = false;
        const fetchFollows = async () => {
            setListsLoading(true);
            setListsError('');
            try {
                const data = await Api.get('get_user_followed', { address: profileAddress }, { timeoutMs: 10000 });
                if (cancelled) return;
                setFollowedUsers(data?.followed_users || []);
                setFollowedTopics(data?.followed_topics || []);
                setModerators(data?.followed_moderators || []);
                if (isOwnProfile) {
                    Storage.save('followed_moderators', data?.followed_moderators || []);
                }
            } catch (err) {
                if (!cancelled) {
                    setListsError(err?.message || 'Failed to load follows');
                }
            } finally {
                if (!cancelled) {
                    setListsLoading(false);
                }
            }
        };
        fetchFollows();
        return () => { cancelled = true; };
    }, [activeTab, profileAddress, isOwnProfile]);

    // Fetch blocks data when blocks tab is opened (always fresh)
    useEffect(() => {
        if (activeTab !== 'blocks' || !profileAddress) return;
        let cancelled = false;
        const fetchBlocks = async () => {
            setListsLoading(true);
            setListsError('');
            try {
                const data = await Api.get('get_user_blocked', { address: profileAddress }, { timeoutMs: 10000 });
                if (cancelled) return;
                setBlockedUsers(data?.blocked_users || []);
                setBlockedPosts(data?.blocked_posts || []);
            } catch (err) {
                if (!cancelled) {
                    setListsError(err?.message || 'Failed to load blocked items');
                }
            } finally {
                if (!cancelled) {
                    setListsLoading(false);
                }
            }
        };
        fetchBlocks();
        return () => { cancelled = true; };
    }, [activeTab, profileAddress]);

    // Fetch preferences for Algo tab
    useEffect(() => {
        if (activeTab !== 'algo' || !profileAddress) return;
        let cancelled = false;
        const fetchPrefs = async () => {
            setPrefsLoading(true);
            setPrefsError('');
            try {
                const data = await Api.get('get_preferences', { address: profileAddress }, { timeoutMs: 10000 });
                if (cancelled) return;
                setPrefsTopics(Array.isArray(data?.topics) ? data.topics : []);
                setPrefsAuthors(Array.isArray(data?.authors) ? data.authors : []);
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
        return () => { cancelled = true; };
    }, [activeTab, profileAddress]);

    // Resolve author usernames for algo tab
    useEffect(() => {
        const authors = prefsAuthors.map((a) => String(a?.user || '')).filter(Boolean);
        if (authors.length === 0) {
            setPrefAuthorUsernames({});
            return;
        }
        let cancelled = false;
        (async () => {
            try {
                const mapping = await resolveUsernamesCached(authors, { timeoutMs: 5000 });
                if (cancelled) return;
                setPrefAuthorUsernames(mapping || {});
            } catch {
                if (cancelled) return;
                setPrefAuthorUsernames({});
            }
        })();
        return () => { cancelled = true; };
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
                const data = await Api.get('get_similar_users', { address: profileAddress }, { timeoutMs: 15000 });
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
        return () => { cancelled = true; };
    }, [activeTab, profileAddress]);

    // Reset data when profile changes
    useEffect(() => {
        setFollowedUsers([]);
        setFollowedTopics([]);
        setBlockedUsers([]);
        setBlockedPosts([]);
        setModerators([]);
        setPrefsTopics([]);
        setPrefsAuthors([]);
        setPrefsError('');
        setPrefAuthorUsernames({});
        setSimilarUsers([]);
        setSimilarUsersError('');
    }, [profileAddress]);

    // Resolve all usernames in one bulk request (moderators + followed users + blocked users)
    useEffect(() => {
        const combined = [...moderators, ...followedUsers, ...blockedUsers]
            .map(a => String(a || '').trim())
            .filter(Boolean);
        if (combined.length === 0) {
            setModeratorUsernames({});
            setFollowedUsernames({});
            setBlockedUsernames({});
            return;
        }

        let cancelled = false;
        const resolveAll = async () => {
            try {
                const mapping = await resolveUsernamesCached(combined, { timeoutMs: 5000 });
                if (cancelled) return;

                // Build maps for each category
                const buildMap = (addresses) => {
                    const result = {};
                    for (const addr of addresses) {
                        const lower = String(addr || '').toLowerCase();
                        const uname = mapping[lower];
                        result[addr] = uname || addr;
                    }
                    return result;
                };

                setModeratorUsernames(buildMap(moderators));
                setFollowedUsernames(buildMap(followedUsers));
                setBlockedUsernames(buildMap(blockedUsers));
            } catch {
                if (cancelled) return;
                // Fallback to addresses
                const buildFallback = (addresses) => {
                    const result = {};
                    addresses.forEach(a => { result[a] = a; });
                    return result;
                };
                setModeratorUsernames(buildFallback(moderators));
                setFollowedUsernames(buildFallback(followedUsers));
                setBlockedUsernames(buildFallback(blockedUsers));
            }
        };
        resolveAll();
        return () => { cancelled = true; };
    }, [moderators, followedUsers, blockedUsers]);

    useEffect(() => {
        if (isOwnProfile) {
            setProfileUsername(username || '');
        } else {
            setProfileUsername('');
        }
    }, [isOwnProfile, username, profileAddress]);

    // Only fetch user status on 'profile' tab (balance, level, etc. not needed for follows/blocks)
    useEffect(() => {
        if (activeTab !== 'profile' || !profileAddress) return;
        let cancelled = false;
        const fetchUserStatus = async () => {
            try {
                const data = await Api.get('get_user_status', { address: profileAddress, _cb: Date.now() }, { timeoutMs: 10000 });
                if (!data || cancelled) return;

                if (isOwnProfile) {
                    try {
                        await tx.cacheConfigData(data);
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
        fetchUserStatus();
        return () => {
            cancelled = true;
        };
    }, [activeTab, profileAddress, isOwnProfile, username]);

    useEffect(() => {
        if (isOwnProfile || !address || !profileAddress) {
            setIsFollowingProfile(false);
            return;
        }
        let cancelled = false;
        isFollowingAsync(address, profileAddress).then((following) => {
            if (!cancelled) setIsFollowingProfile(following);
        }).catch(() => {
            if (!cancelled) setIsFollowingProfile(false);
        });
        return () => { cancelled = true; };
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
    }, [recentPostsFilter]);

    // Lazy-load posts only when posts tab is active
    useEffect(() => {
        let cancelled = false;
        if (!profileAddress || activeTab !== 'posts') {
            return;
        }
        const fetchRecentPosts = async () => {
            setIsLoadingRecentPosts(true);
            setRecentAutoLoading(false);
            setRecentPostsError('');
            try {
                const params = { owner: profileAddress, limit: 50, page: recentPage };
                if (address) params.address = address;
                if (recentPostsFilter === 'submissions' || recentPostsFilter === 'comments') {
                    params.type = recentPostsFilter;
                }
                const res = await Api.get('get_user_posts', params, { timeoutMs: 10000 });
                if (cancelled) return;
                const incoming = Array.isArray(res?.posts) ? res.posts : [];
                const hasMore = !!res?.has_more;
                setRecentHasMore(hasMore);
                setRecentPosts((prev) => {
                    if (recentPage === 1) {
                        return incoming;
                    }
                    const existing = new Set(prev.map((p) => p?.post_id));
                    const filtered = incoming.filter((p) => p && p.post_id && !existing.has(p.post_id));
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
    }, [profileAddress, address, recentPage, recentPostsFilter, activeTab]);

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
        const observer = new IntersectionObserver(
            (entries) => {
                const entry = entries[0];
                if (entry && entry.isIntersecting) {
                    setRecentAutoLoading(true);
                    if (recentLoadTimerRef.current) clearTimeout(recentLoadTimerRef.current);
                    recentLoadTimerRef.current = window.setTimeout(() => {
                        setRecentPage((prev) => prev + 1);
                    }, 1000);
                }
            },
            { root: null, rootMargin: '0px', threshold: 0.01 }
        );
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

    const shortenAddress = (addr) => {
        if (!addr) return '';
        if (addr.length <= 24) return addr;
        return `${addr.slice(0, 14)}...${addr.slice(-8)}`;
    };

    const formatRegistrationDate = (ts) => {
        const num = Number(ts);
        // Default to 2025-11-01 00:00 UTC if no registration date available
        if (!Number.isFinite(num) || num <= 0) {
            return '2025-11-01 00:00 UTC';
        }
        const date = new Date(num * 1000);
        if (Number.isNaN(date.getTime())) {
            return '2025-11-01 00:00 UTC';
        }
        const pad = (value) => String(value).padStart(2, '0');
        const year = date.getFullYear();
        const month = pad(date.getMonth() + 1);
        const day = pad(date.getDate());
        const hours = pad(date.getHours());
        const minutes = pad(date.getMinutes());
        const tz = date.toLocaleTimeString('en-US', { timeZoneName: 'short' }).split(' ').pop();
        return `${year}-${month}-${day} ${hours}:${minutes} ${tz}`;
    };

    const getTierName = (level) => {
        const names = ['Free', 'Trusted', 'Established', 'Distinguished'];
        if (level >= 100) return 'Admin';
        return names[level] || 'Free';
    };

    const getTierColor = (level) => {
        const colors = ['#6B7280', '#3B82F6', '#8B5CF6', '#F59E0B'];
        if (level >= 100) return '#EF4444';
        return colors[level] || colors[0];
    };

    const formatSubscriptionExpiry = (timestamp) => {
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

    const formatElapsed = (ts) => {
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

    const buildMetaLine = (post) => {
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

    const renderPostPreview = (post) => {
        if (!post) return null;
        const isComment = post.target && post.target.trim() !== '';
        if (isComment) {
            const head = post.content ? truncateContent(post.content) : '(comment)';
            return head || '(comment)';
        }
        return post.title || truncateContent(post.content) || '(untitled post)';
    };



    // Helper functions for better UX
    const clearMessages = () => {
        setModeratorError('');
        setModeratorSuccess('');
    };

    const showError = (message) => {
        setModeratorError(message);
        setModeratorSuccess('');
        // Auto-clear error after 5 seconds
        setTimeout(() => setModeratorError(''), 5000);
    };

    const showSuccess = (message) => {
        setModeratorSuccess(message);
        setModeratorError('');
        // Auto-clear success after 3 seconds
        setTimeout(() => setModeratorSuccess(''), 3000);
    };

    const addModerator = async () => {
        if (!isOwnProfile) return;
        const trimmed = newModeratorInput.trim();
        if (!trimmed) return;

        clearMessages();
        setIsAddingModerator(true);

        // Validate username format (alphanumeric and hyphens)
        if (!/^[A-Za-z0-9-]+$/.test(trimmed)) {
            showError('Invalid username format. Only letters, numbers, and hyphens are allowed.');
            setIsAddingModerator(false);
            return;
        }

        // Check if username exists and get the address
        try {
            const response = await Api.get('get_address_from_username', { username: trimmed }, { timeoutMs: 5000 });
            if (!response || !response.exists || !response.address) {
                showError(`Username "${trimmed}" not found. Make sure the username exists on-chain.`);
                setIsAddingModerator(false);
                return;
            }

            const modAddress = response.address;

            // Check if moderator address is already in list
            if (moderators.map(m => m.toLowerCase()).includes(modAddress.toLowerCase())) {
                showError('This moderator is already in your list.');
                setIsAddingModerator(false);
                return;
            }

            // Create transaction to follow moderator on-chain

            // Fetch fresh parameters before submitting
            const paramsData = await Api.get('get_parameters', address ? { address } : undefined, { timeoutMs: 5000 });
            if (!paramsData) {
                showError('Unable to fetch network parameters. Please try again.');
                setIsAddingModerator(false);
                return;
            }

            const lastBlockHash = paramsData.last_block_hash || '';
            const powDifficulty = Number(paramsData.pow_difficulty);

            if (!lastBlockHash) {
                showError('Unable to get last block hash from server. Please try again.');
                setIsAddingModerator(false);
                return;
            }

            if (!seedPhrase) {
                showError('Seed phrase not available. Please sign in again.');
                setIsAddingModerator(false);
                return;
            }

            const transaction = {
                action: 'follow_moderator',
                moderator: modAddress,
                last_block_hash: lastBlockHash,
                pow_difficulty: powDifficulty,
                difficulty: powDifficulty,
            };

            // Submit transaction via facade
            const result = await tx.performTransaction(
                transaction,
                lastBlockHash,
                derivePrivateKeyFromSeed(seedPhrase),
                address,
                false // forcePow
            );

            if (result.success) {
                // Update local state on success
                const updated = [...moderators.filter(m => m !== modAddress), modAddress];
                if (updated.length > 3) updated.shift();
                setModerators(updated);
                if (isOwnProfile) {
                    Storage.save('followed_moderators', updated);
                }
                setNewModeratorInput('');
                showSuccess(`Successfully added moderator "${trimmed}"`);
            } else {
                showError(`Failed to add moderator: ${result.error || 'Unknown error'}`);
            }
        } catch (error) {
            showError(`Error checking username: ${error.message || 'Network error'}`);
        } finally {
            setIsAddingModerator(false);
        }
    };

    const removeModerator = async (modAddress) => {
        if (!isOwnProfile) return;
        setIsRemovingModerator(modAddress);
        clearMessages();

        try {
            // Create updated list without this moderator
            const updated = moderators.filter(m => m !== modAddress);

            // Fetch fresh parameters before submitting
            const paramsData = await Api.get('get_parameters', address ? { address } : undefined, { timeoutMs: 5000 });
            if (!paramsData) {
                showError('Unable to fetch network parameters. Please try again.');
                setIsRemovingModerator('');
                return;
            }

            const lastBlockHash = paramsData.last_block_hash || '';
            const powDifficulty = Number(paramsData.pow_difficulty);

            if (!lastBlockHash) {
                showError('Unable to fetch last block hash. Please try again.');
                setIsRemovingModerator('');
                return;
            }

            const transaction = {
                action: 'unfollow_moderator',
                moderator: modAddress,
                last_block_hash: lastBlockHash,
                pow_difficulty: powDifficulty >>> 0,
            };

            const seedPhrase = seedVault.getSeed() || '';
            if (!seedPhrase) {
                showError('No seed phrase found. Please sign in again.');
                setIsRemovingModerator('');
                return;
            }

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = derivePublicKeyFromSeed(seedPhrase);
            const challenge = `${derivedAddress}:${lastBlockHash}:${powDifficulty}`;

            const result = await tx.performTransaction(transaction, challenge, privateKeyHex, derivedAddress, false);

            if (result && result.success) {
                setModerators(updated);
                Storage.save('followed_moderators', updated);
                const username = moderatorUsernames[modAddress] || modAddress;
                showSuccess(`Removed moderator "${username}"`);
            } else {
                showError(`Failed to remove moderator: ${result?.error || 'Unknown error'}`);
            }
        } catch (error) {
            console.error('Remove moderator error:', error);
            showError(`Failed to remove moderator: ${error.message || error}`);
        } finally {
            setIsRemovingModerator('');
        }
    };

    const handleModeratorKeyDown = (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            addModerator();
        }
    };

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

    const handleRecentPostClick = async (post) => {
        if (!post || !post.post_id) return;
        setActiveRecentPost(post.post_id);
        try {
            Storage.setPendingPostHighlight(post.post_id);
        } catch (_) { }

        // New clean URL format - works for both posts and comments
        // For comments, the view will auto-detect and show context options
        const isComment = post.target && post.target.trim() !== '';
        if (isComment) {
            // Show comment with parent context
            navigate(`/p/${post.post_id}?depth=1`);
        } else {
            navigate(`/p/${post.post_id}`);
        }
    };


    const usernameDisplay = (profileUsername || (isOwnProfile ? username : '')) || '(not set)';
    const balanceDisplay = profileAddress
        ? (balance === null ? '(loading...)' : `${formatMirage(balance)} MIRAGE`)
        : '(address required)';
    const reserveDisplay = profileAddress
        ? (reserveFunds === null ? '(loading...)' : `${formatMirage(reserveFunds)} MIRAGE`)
        : '(address required)';
    const registeredDisplay = formatRegistrationDate(profileRegisteredAt);
    const canEditProfile = isOwnProfile && Boolean(address);
    const moderatorsEmptyMessage = canEditProfile
        ? 'You can follow moderators, and any posts or users they choose to block will automatically be blocked for you as well.'
        : 'Not following any moderators.';

    const profileTitle = profileUsername
        ? `@${profileUsername}`
        : profileAddress
            ? `${profileAddress.slice(0, 10)}...`
            : 'Profile';

    // Show loading/error states for username resolution
    if (isResolvingUsername || usernameResolutionError) {
        return (
            <ContentGrid>
                <Helmet>
                    <title>{routeIdentity ? `@${routeIdentity}` : 'Profile'} | Mirage</title>
                </Helmet>
                <Sidebar currentPath={location.pathname} state={state} />
                <div>
                    <TopBar state={state} />
                    <ModernPostFeed>
                        <MobileHeader />
                        <TabbedContainer>
                            <ContainerBody style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: '2rem', gap: '0.5rem', minHeight: '200px' }}>
                                {isResolvingUsername ? (
                                    <span style={{ color: '#888' }}>Looking up @{routeIdentity}...</span>
                                ) : (
                                    <span style={{ color: '#ff6b6b' }}>{usernameResolutionError}</span>
                                )}
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </div>
            </ContentGrid>
        );
    }

    return (
        <ContentGrid>
            <Helmet>
                <title>{profileTitle} | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow>
                            <ClickableTab $active={activeTab === 'profile'} onClick={() => setActiveTab('profile')}>
                                Profile
                            </ClickableTab>
                            <ClickableTab $active={activeTab === 'posts'} onClick={() => setActiveTab('posts')}>
                                Posts
                            </ClickableTab>
                            <ClickableTab $active={activeTab === 'follows'} onClick={() => setActiveTab('follows')}>
                                Follows
                            </ClickableTab>
                            <ClickableTab $active={activeTab === 'blocks'} onClick={() => setActiveTab('blocks')}>
                                Blocks
                            </ClickableTab>
                            <ClickableTab $active={activeTab === 'algo'} onClick={() => setActiveTab('algo')}>
                                Algo
                            </ClickableTab>
                        </TabsRow>
                        <ContainerBody>
                            {activeTab === 'profile' && (
                                <>
                                    <RowCentered>
                                        <Label>Username:</Label>
                                        <ValueBoxWithButton>
                                            <InlineMono title={profileUsername}>{usernameDisplay}</InlineMono>
                                            {canEditProfile && (
                                                <Button onClick={() => navigate('/change_username')} size="sm" minWidth="copy" mobileFullWidth>Change</Button>
                                            )}
                                            {!isOwnProfile && address && (
                                                <Button
                                                    variant={
                                                        (isFollowingProfile && followHover) || isUnfollowAction
                                                            ? 'primaryDanger'
                                                            : isFollowingProfile
                                                                ? 'subtle'
                                                                : 'primary'
                                                    }
                                                    size="pill"
                                                    minWidth="follow"
                                                    onMouseEnter={() => setFollowHover(true)}
                                                    onMouseLeave={() => setFollowHover(false)}
                                                    disabled={isFollowInProgress}
                                                    loading={isFollowInProgress}
                                                    onClick={handleFollowToggle}
                                                    mobileFullWidth
                                                >
                                                    {isFollowInProgress
                                                        ? (formatStatusForPosition(myQueuePosition) || 'Solving PoW...')
                                                        : (isFollowingProfile
                                                            ? (followHover ? 'Unfollow' : 'Following')
                                                            : 'Follow')}
                                                </Button>
                                            )}
                                        </ValueBoxWithButton>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Address:</Label>
                                        <ValueBoxWithButton>
                                            <InlineMono title={profileAddress}>{profileAddress || '(unavailable)'}</InlineMono>
                                            {profileAddress && (
                                                <Button
                                                    onClick={() => {
                                                        navigator.clipboard.writeText(profileAddress);
                                                        setAddressCopied(true);
                                                        setTimeout(() => setAddressCopied(false), 1500);
                                                    }}
                                                    size="sm"
                                                    minWidth="copy"
                                                    copied={addressCopied}
                                                    mobileFullWidth
                                                >
                                                    {addressCopied ? 'Copied!' : 'Copy'}
                                                </Button>
                                            )}
                                        </ValueBoxWithButton>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Tier:</Label>
                                        <ValueBox>
                                            <Mono style={{ color: getTierColor(userLevel) }}>
                                                {getTierName(userLevel)}
                                            </Mono>
                                            {userLevel > 0 && subscriptionExpiry > 0 && formatSubscriptionExpiry(subscriptionExpiry) && (
                                                <span style={{ marginLeft: '0.5rem', fontSize: '0.7rem', color: '#888' }}>
                                                    ({formatSubscriptionExpiry(subscriptionExpiry)})
                                                </span>
                                            )}
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <HoverableLabel tabIndex={0} data-tooltip={`Spendable wallet balance in MIRAGE.\n\nThis is what a subscription will be paid with.`}>
                                            Balance:
                                        </HoverableLabel>
                                        <ValueBox>
                                            <Mono>{balanceDisplay}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <HoverableLabel tabIndex={0} data-tooltip={`Escrowed reserve in MIRAGE used for relayed gas and subscriptions.\n\nHeld internally by the blockchain and used to process all transactions while subscribed.\n\nNot directly spendable and will get burned if not used.`}>
                                            Reserve:
                                        </HoverableLabel>
                                        <ValueBox>
                                            <Mono>{reserveDisplay}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Registered:</Label>
                                        <ValueBox>
                                            <Mono>{registeredDisplay}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                </>
                            )}

                            {activeTab === 'posts' && (
                                <>
                                    {profileAddress && (
                                        <FilterSelect
                                            value={recentPostsFilter}
                                            onChange={(e) => setRecentPostsFilter(e.target.value)}
                                        >
                                            <option value="all">All</option>
                                            <option value="submissions">Submissions</option>
                                            <option value="comments">Comments</option>
                                        </FilterSelect>
                                    )}
                                    {isLoadingRecentPosts && (
                                        <LoadingRow>
                                            <LoadingSpinner />
                                            <SubtleMono>Loading posts...</SubtleMono>
                                        </LoadingRow>
                                    )}
                                    {!isLoadingRecentPosts && recentPostsError && (
                                        <Mono style={{ color: '#f87171' }}>{recentPostsError}</Mono>
                                    )}
                                    {!isLoadingRecentPosts && !recentPostsError && recentPosts.length === 0 && (
                                        <SubtleMono>No {recentPostsFilter === 'all' ? 'posts' : (recentPostsFilter === 'submissions' ? 'submissions' : 'comments')} yet.</SubtleMono>
                                    )}
                                    {!recentPostsError && recentPosts.length > 0 && (
                                        <PostsList>
                                            {recentPosts.map((post) => (
                                                <PostItem
                                                    key={post.post_id}
                                                    isActive={activeRecentPost === post.post_id}
                                                    onClick={() => handleRecentPostClick(post)}
                                                >
                                                    <PostPreview>{renderPostPreview(post)}</PostPreview>
                                                    <PostMeta>{buildMetaLine(post)}</PostMeta>
                                                </PostItem>
                                            ))}
                                        </PostsList>
                                    )}
                                    {(recentAutoLoading || (isLoadingRecentPosts && recentPage > 1)) && (
                                        <SubtleMono style={{ display: 'block', marginTop: '0.5rem', fontStyle: 'italic' }}>
                                            Loading more...
                                        </SubtleMono>
                                    )}
                                    <div ref={recentBottomSentinelRef} style={{ width: '100%', height: '20px', minHeight: '20px' }} />
                                </>
                            )}

                            {activeTab === 'follows' && (
                                <>
                                    <SectionTitle $first>Moderators</SectionTitle>
                                    <ValueBox>
                                        {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                        {!listsLoading && !listsError && moderators.length === 0 && (
                                            <Mono style={{ color: '#888' }}>{moderatorsEmptyMessage}</Mono>
                                        )}
                                        {!listsLoading && !listsError && moderators.length > 0 && (
                                            isOwnProfile ? (
                                                <ModeratorsList>
                                                    {moderators.map((modAddr) => (
                                                        <ModeratorTag key={modAddr} $isRemoving={isRemovingModerator === modAddr}>
                                                            <Mono
                                                                style={{ cursor: 'pointer' }}
                                                                onClick={() => navigate(`/u/${encodeURIComponent(moderatorUsernames[modAddr] || modAddr)}?tab=posts`)}
                                                            >
                                                                {moderatorUsernames[modAddr] && moderatorUsernames[modAddr] !== modAddr
                                                                    ? moderatorUsernames[modAddr]
                                                                    : shortenAddress(modAddr)}
                                                            </Mono>
                                                            <RemoveModeratorButton
                                                                onClick={() => removeModerator(modAddr)}
                                                                title="Remove"
                                                                disabled={isRemovingModerator === modAddr}
                                                            >
                                                                {isRemovingModerator === modAddr ? <LoadingSpinner /> : '×'}
                                                            </RemoveModeratorButton>
                                                        </ModeratorTag>
                                                    ))}
                                                </ModeratorsList>
                                            ) : (
                                                <PostsList>
                                                    {moderators.map((modAddr) => (
                                                        <PostItem
                                                            key={modAddr}
                                                            onClick={() => navigate(`/u/${encodeURIComponent(moderatorUsernames[modAddr] || modAddr)}?tab=posts`)}
                                                        >
                                                            <PostPreview>
                                                                {moderatorUsernames[modAddr] && moderatorUsernames[modAddr] !== modAddr
                                                                    ? moderatorUsernames[modAddr]
                                                                    : shortenAddress(modAddr)}
                                                            </PostPreview>
                                                            <PostMeta>{modAddr}</PostMeta>
                                                        </PostItem>
                                                    ))}
                                                </PostsList>
                                            )
                                        )}
                                        {isOwnProfile && !listsLoading && (
                                            <>
                                                <ModeratorInputRow>
                                                    <ModeratorInput
                                                        type="text"
                                                        placeholder="Add a moderator by username"
                                                        value={newModeratorInput}
                                                        onChange={(e) => {
                                                            setNewModeratorInput(e.target.value);
                                                            setModeratorError('');
                                                            setModeratorSuccess('');
                                                        }}
                                                        onKeyDown={handleModeratorKeyDown}
                                                        disabled={isAddingModerator}
                                                    />
                                                    <Button
                                                        onClick={addModerator}
                                                        disabled={isAddingModerator || !newModeratorInput.trim()}
                                                        loading={isAddingModerator}
                                                        size="sm"
                                                    >
                                                        Add
                                                    </Button>
                                                </ModeratorInputRow>
                                                {moderatorError && (
                                                    <ModeratorErrorMessage>
                                                        <span>⚠</span>
                                                        {moderatorError}
                                                    </ModeratorErrorMessage>
                                                )}
                                                {moderatorSuccess && (
                                                    <ModeratorSuccessMessage>
                                                        <span>✓</span>
                                                        {moderatorSuccess}
                                                    </ModeratorSuccessMessage>
                                                )}
                                            </>
                                        )}
                                    </ValueBox>

                                    <SectionTitle>Topics</SectionTitle>
                                    <ValueBox>
                                        {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                        {!listsLoading && !listsError && followedTopics.length === 0 && (
                                            <Mono style={{ color: '#888' }}>Not following any topics.</Mono>
                                        )}
                                        {!listsLoading && !listsError && followedTopics.length > 0 && (
                                            <PostsList>
                                                {followedTopics.map((topic) => (
                                                    <PostItem key={topic} onClick={() => navigate(`/t/${encodeURIComponent(topic)}`)}>
                                                        <PostPreview>#{topic}</PostPreview>
                                                    </PostItem>
                                                ))}
                                            </PostsList>
                                        )}
                                    </ValueBox>

                                    <SectionTitle>Users</SectionTitle>
                                    <ValueBox>
                                        {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                        {!listsLoading && listsError && <Mono style={{ color: '#f87171' }}>{listsError}</Mono>}
                                        {!listsLoading && !listsError && followedUsers.length === 0 && (
                                            <Mono style={{ color: '#888' }}>Not following any users.</Mono>
                                        )}
                                        {!listsLoading && !listsError && followedUsers.length > 0 && (
                                            <PostsList>
                                                {followedUsers.map((userAddr) => (
                                                    <PostItem
                                                        key={userAddr}
                                                        onClick={() => navigate(`/u/${encodeURIComponent(followedUsernames[userAddr] || userAddr)}?tab=posts`)}
                                                    >
                                                        <PostPreview>
                                                            {followedUsernames[userAddr] && followedUsernames[userAddr] !== userAddr
                                                                ? followedUsernames[userAddr]
                                                                : shortenAddress(userAddr)}
                                                        </PostPreview>
                                                        <PostMeta>{userAddr}</PostMeta>
                                                    </PostItem>
                                                ))}
                                            </PostsList>
                                        )}
                                    </ValueBox>
                                </>
                            )}

                            {activeTab === 'algo' && (
                                <>
                                    <SectionTitle $first>Topic preferences</SectionTitle>
                                    <ValueBox style={{ padding: '0.25rem 0.5rem' }}>
                                        {prefsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                        {!prefsLoading && prefsError && <Mono style={{ color: '#f87171' }}>{prefsError}</Mono>}
                                        {!prefsLoading && !prefsError && prefsTopics.length === 0 && (
                                            <Mono style={{ color: '#888' }}>No topic preference data yet.</Mono>
                                        )}
                                        {!prefsError && prefsTopics.length > 0 && (
                                            <div>
                                                {prefsTopics.map((t) => (
                                                    <div key={t.topic} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0' }}>
                                                        <Mono>#{t.topic}</Mono>
                                                        <Mono style={{ color: colorForWeight(t.weight) }}>
                                                            {formatPrefWeight(t.weight)}
                                                        </Mono>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </ValueBox>

                                    <SectionTitle>User preferences</SectionTitle>
                                    <ValueBox style={{ padding: '0.25rem 0.5rem' }}>
                                        {prefsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                        {!prefsLoading && prefsError && <Mono style={{ color: '#f87171' }}>{prefsError}</Mono>}
                                        {!prefsLoading && !prefsError && prefsAuthors.length === 0 && (
                                            <Mono style={{ color: '#888' }}>No user preference data yet.</Mono>
                                        )}
                                        {!prefsError && prefsAuthors.length > 0 && (
                                            <div>
                                                {prefsAuthors.map((u) => {
                                                    const uname = prefAuthorUsernames[String(u.user || '').toLowerCase()];
                                                    return (
                                                        <div
                                                            key={u.user}
                                                            style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', cursor: 'pointer' }}
                                                            onClick={() => navigate(`/u/${encodeURIComponent(prefAuthorUsernames[u.user] || u.user)}?tab=posts`)}
                                                        >
                                                            <Mono>{uname && uname !== u.user ? uname : shortenAddress(u.user)}</Mono>
                                                            <Mono style={{ color: colorForWeight(u.weight) }}>
                                                                {formatPrefWeight(u.weight)}
                                                            </Mono>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    </ValueBox>

                                    <SectionTitle>Similar users</SectionTitle>
                                    <ValueBox style={{ padding: '0.25rem 0.5rem' }}>
                                        {similarUsersLoading && <Mono style={{ color: '#888' }}>Computing similarity...</Mono>}
                                        {!similarUsersLoading && similarUsersError && <Mono style={{ color: '#f87171' }}>{similarUsersError}</Mono>}
                                        {!similarUsersLoading && !similarUsersError && similarUsers.length === 0 && (
                                            <Mono style={{ color: '#888' }}>No similar users found yet.</Mono>
                                        )}
                                        {!similarUsersError && similarUsers.length > 0 && (
                                            <div>
                                                {similarUsers.map((u) => (
                                                    <div
                                                        key={u.address}
                                                        style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', cursor: 'pointer' }}
                                                        onClick={() => navigate(`/u/${encodeURIComponent(u.username || u.address)}?tab=posts`)}
                                                    >
                                                        <Mono>{u.username || shortenAddress(u.address)}</Mono>
                                                        <Mono style={{ color: '#22c55e' }}>
                                                            {(u.similarity * 100).toFixed(0)}% ({u.shared_dimensions} shared)
                                                        </Mono>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </ValueBox>
                                </>
                            )}

                            {activeTab === 'blocks' && (
                                <>
                                    <SectionTitle $first>Blocked Users</SectionTitle>
                                    <ValueBox>
                                        {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                        {!listsLoading && !listsError && blockedUsers.length === 0 && (
                                            <Mono style={{ color: '#888' }}>No blocked users.</Mono>
                                        )}
                                        {!listsLoading && !listsError && blockedUsers.length > 0 && (
                                            <PostsList>
                                                {blockedUsers.map((userAddr) => (
                                                    <PostItem key={userAddr} onClick={() => navigate(`/u/${encodeURIComponent(blockedUsernames[userAddr] || userAddr)}`)}>
                                                        <PostPreview>
                                                            {blockedUsernames[userAddr] && blockedUsernames[userAddr] !== userAddr
                                                                ? blockedUsernames[userAddr]
                                                                : shortenAddress(userAddr)}
                                                        </PostPreview>
                                                        <PostMeta>{userAddr}</PostMeta>
                                                    </PostItem>
                                                ))}
                                            </PostsList>
                                        )}
                                    </ValueBox>

                                    <SectionTitle>Blocked Posts</SectionTitle>
                                    <ValueBox>
                                        {listsLoading && <Mono style={{ color: '#888' }}>Loading...</Mono>}
                                        {!listsLoading && !listsError && blockedPosts.length === 0 && (
                                            <Mono style={{ color: '#888' }}>No blocked posts.</Mono>
                                        )}
                                        {!listsLoading && !listsError && blockedPosts.length > 0 && (
                                            <PostsList>
                                                {blockedPosts.map((postId) => (
                                                    <PostItem key={postId} onClick={() => navigate(`/p/${encodeURIComponent(postId)}`)}>
                                                        <PostPreview>{shortenAddress(postId)}</PostPreview>
                                                        <PostMeta>{postId}</PostMeta>
                                                    </PostItem>
                                                ))}
                                            </PostsList>
                                        )}
                                    </ValueBox>
                                </>
                            )}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
