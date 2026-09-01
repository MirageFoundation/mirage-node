import { useState, useEffect, useRef, useCallback } from "react";
import Storage from "../utils/Storage";
import Api from "../utils/api";
import { joinCommunity, leaveCommunity, fetchJoinedCommunities, invalidateCache as invalidateCommunitiesCache } from "../utils/Subscriptions";
import { usePendingFollows } from "./useFollowState.js";
import { useLocation } from "react-router-dom";
import { requireAccount } from "../utils/openBrowsing";
import { stripCommunityPrefix } from "../utils/community";

function mapCommunity(item) {
    if (!item || typeof item.community !== 'string' || typeof item.curated !== 'boolean') {
        throw new Error('Invalid community directory item');
    }
    if (!Number.isInteger(item.live_team_count) || !Number.isInteger(item.post_count)) {
        throw new Error('Community directory counts are required');
    }
    if (item.curated && (
        !item.default_team
        || typeof item.default_team.team_id !== 'string'
        || typeof item.default_team.name !== 'string'
        || typeof item.default_team.subscriber_count !== 'string'
    )) {
        throw new Error('Curated community is missing its default team');
    }
    return {
        community: item.community,
        curated: item.curated,
        live_team_count: item.live_team_count,
        post_count: item.post_count,
        default_team: item.default_team,
    };
}

function sortByPostCount(list) {
    return [...list].sort((a, b) => {
        const diff = b.post_count - a.post_count;
        if (diff !== 0) return diff;
        return String(a.community).localeCompare(String(b.community));
    });
}
export const tagColors = {
    adult: {
        bg: 'rgba(236, 72, 153, 0.18)',
        border: 'rgba(236, 72, 153, 0.50)',
        text: '#ec4899'
    },
    violence: {
        bg: 'rgba(185, 28, 28, 0.18)',
        border: 'rgba(185, 28, 28, 0.50)',
        text: '#b91c1c'
    },
    gore: {
        bg: 'rgba(185, 28, 28, 0.18)',
        border: 'rgba(185, 28, 28, 0.50)',
        text: '#b91c1c'
    },
    death: {
        bg: 'rgba(185, 28, 28, 0.18)',
        border: 'rgba(185, 28, 28, 0.50)',
        text: '#b91c1c'
    },
    sensitive: {
        bg: 'rgba(109, 40, 217, 0.18)',
        border: 'rgba(109, 40, 217, 0.50)',
        text: '#6d28d9'
    },
    default: {
        bg: '#e5e7eb',
        border: '#cbd5e1',
        text: '#0f172a'
    }
};
export function useDiscover({
    state
}) {
    const viewerAddress = Storage.load('publicKey', '') || 'guest';
    const [communities, setCommunities] = useState([]);
    const [filteredCommunities, setFilteredCommunities] = useState([]);
    const [smallCommunitiesCount, setSmallCommunitiesCount] = useState(0);
    const [searchTerm, setSearchTerm] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [isSearching, setIsSearching] = useState(false);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [joinedCommunitiesSet, setJoinedCommunitiesSet] = useState(new Set());
    const [hoverCommunity, setHoverCommunity] = useState(null);
    const {
        isCommunityPending,
        formatCommunityStatus
    } = usePendingFollows();
    const mountedRef = useRef(true);
    const searchRequestId = useRef(0);
    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
        };
    }, []);
    useEffect(() => {
        let alive = true;
        setLoading(true);
        setError('');
        Api.get('communities', {
            limit: 100,
        }).then(data => {
            if (!alive || !mountedRef.current) return;
            if (data && Array.isArray(data.items)) {
                const communitiesList = sortByPostCount(data.items.map(mapCommunity));
                setCommunities(communitiesList);
                setFilteredCommunities(communitiesList);
                setSmallCommunitiesCount(0);
                console.debug('[DiscoverView] loaded communities', {
                    count: communitiesList.length,
                    first: communitiesList[0]?.community,
                    firstPosts: communitiesList[0]?.post_count,
                });
            } else {
                setCommunities([]);
                setFilteredCommunities([]);
                setSmallCommunitiesCount(0);
            }
            setLoading(false);
        }).catch(error => {
            if (!alive || !mountedRef.current) return;
            console.error('[DiscoverView] Failed to load communities:', error);
            setError(String(error?.message || error));
            setLoading(false);
        });
        return () => {
            alive = false;
        };
    }, [viewerAddress]);

    // Filter local communities and search API for more results
    useEffect(() => {
        const term = stripCommunityPrefix(searchTerm).toLowerCase();
        if (!term) {
            setFilteredCommunities(communities);
            setSearchResults([]);
            setIsSearching(false);
            return;
        }

        // Filter local communities immediately
        const filtered = communities.filter(t => {
            const communityName = String(t.community || '').toLowerCase();
            return communityName.includes(term);
        });
        setFilteredCommunities(filtered);

        // Also search API for communities with < 10 posts (debounced)
        if (term.length < 2) {
            setSearchResults([]);
            setIsSearching(false);
            return;
        }
        const requestId = searchRequestId.current + 1;
        searchRequestId.current = requestId;
        setIsSearching(true);
        const handle = setTimeout(async () => {
            try {
                const data = await Api.get('communities', {
                    query: term,
                    limit: 50,
                }, {
                    timeoutMs: 8000
                });
                if (searchRequestId.current !== requestId || !mountedRef.current) return;
                const results = Array.isArray(data?.items) ? data.items : [];
                const existingLower = new Set(communities.map(t => t.community.toLowerCase()));
                const newCommunities = sortByPostCount(
                    results
                        .filter(t => t && t.community && !existingLower.has(String(t.community).toLowerCase()))
                        .map(mapCommunity)
                );
                setSearchResults(newCommunities);
            } catch (_) {
                if (searchRequestId.current === requestId) setSearchResults([]);
            } finally {
                if (searchRequestId.current === requestId) setIsSearching(false);
            }
        }, 250);
        return () => {
            searchRequestId.current += 1;
            clearTimeout(handle);
        };
    }, [searchTerm, communities]);
    useEffect(() => {
        let cancelled = false;
        const loadJoinedCommunities = async () => {
            if (!viewerAddress || viewerAddress === 'guest') return;
            try {
                const list = await fetchJoinedCommunities(viewerAddress);
                if (!cancelled && mountedRef.current) {
                    setJoinedCommunitiesSet(new Set(list.map(t => t.toLowerCase())));
                }
            } catch (_) { }
        };
        loadJoinedCommunities();
        return () => {
            cancelled = true;
        };
    }, [viewerAddress]);
    const isJoinedCommunity = useCallback(community => {
        return joinedCommunitiesSet.has(String(community || '').toLowerCase());
    }, [joinedCommunitiesSet]);
    const handleSubscribeToggle = useCallback(async community => {
        const t = String(community || '').toLowerCase();
        if (!t || isCommunityPending(t)) return;
        if (!requireAccount('join a community')) return;
        const wasSubscribed = isJoinedCommunity(community);
        try {
            if (wasSubscribed) {
                await leaveCommunity(viewerAddress, community);
                if (mountedRef.current) {
                    setJoinedCommunitiesSet(prev => {
                        const next = new Set(prev);
                        next.delete(t);
                        return next;
                    });
                }
            } else {
                await joinCommunity(viewerAddress, community);
                if (mountedRef.current) {
                    setJoinedCommunitiesSet(prev => new Set([...prev, t]));
                }
            }
            invalidateCommunitiesCache();
        } catch (_) { }
    }, [viewerAddress, isCommunityPending, isJoinedCommunity]);
    const location = useLocation();
    return {
        filteredCommunities,
        smallCommunitiesCount,
        searchTerm,
        setSearchTerm,
        searchResults,
        isSearching,
        loading,
        error,
        hoverCommunity,
        setHoverCommunity,
        isCommunityPending,
        formatCommunityStatus,
        isJoinedCommunity,
        handleSubscribeToggle,
        location
    };
}