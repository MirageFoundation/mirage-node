import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Storage from "../utils/Storage";
import { getAllowedTagsParam } from "../utils/ContentTags";
import Api from "../utils/api";

/**
 * Drives the TopBar search dropdown sheet for the default theme.
 *
 * Mirrors `mirage-mobile-app/src/pages/search-screen.tsx` behavior:
 *  - When the input is empty, surface **recent searches** + **trending topics**.
 *  - When the user types, debounce and surface **live results** (posts,
 *    topics, users) inside the sheet.
 *  - On submit, record the query as a recent search and let the caller
 *    navigate to `/search?q=...` for the full results page.
 *
 * This is **visual infrastructure only** — it never touches
 * `useSearchResults.js` (the full results hook).
 *
 * Recent searches are persisted in `localStorage` under
 * `mirage_recent_searches`, mirroring the shape of mobile's zustand store.
 */

const RECENTS_KEY = "mirage_recent_searches";
const TRENDING_CACHE_KEY = "mirage_trending_topics_cache";
const TRENDING_CACHE_TTL_MS = 5 * 60 * 1000;
const MAX_RECENTS = 8;
const DEBOUNCE_MS = 300;
const LIVE_LIMIT = 5;
const TRENDING_LIMIT = 10;

function loadTrendingCache(viewerKey) {
    try {
        const raw = localStorage.getItem(TRENDING_CACHE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object") return null;
        if (parsed.viewer !== viewerKey) return null;
        if (Date.now() - Number(parsed.at || 0) > TRENDING_CACHE_TTL_MS) return null;
        return Array.isArray(parsed.topics) ? parsed.topics : null;
    } catch (_) {
        return null;
    }
}

function persistTrendingCache(viewerKey, topics) {
    try {
        localStorage.setItem(
            TRENDING_CACHE_KEY,
            JSON.stringify({ viewer: viewerKey, at: Date.now(), topics })
        );
    } catch (_) { }
}

function loadRecents() {
    try {
        const raw = localStorage.getItem(RECENTS_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return [];
        return parsed
            .filter(
                (entry) =>
                    entry &&
                    typeof entry === "object" &&
                    typeof entry.query === "string" &&
                    entry.query.trim().length > 0
            )
            .slice(0, MAX_RECENTS);
    } catch (_) {
        return [];
    }
}

function persistRecents(list) {
    try {
        localStorage.setItem(RECENTS_KEY, JSON.stringify(list));
    } catch (_) { }
}

export function useSearchDropdown(options = {}) {
    // `trendingEnabled`: when true (e.g. on the /search results route), trending
    // topics load eagerly on mount — the user is already on a search-focused
    // surface, no point waiting. When false (e.g. the TopBar search dropdown,
    // which mounts on every page), trending stays dormant and the caller fires
    // `loadTrending()` on first focus / dropdown-open. Defaults to true to
    // preserve existing call-site behavior.
    const { trendingEnabled = true } = options;
    const viewerAddress = Storage.load("publicKey", "") || "";
    const viewerKey = viewerAddress || "guest";
    const mountedRef = useRef(true);

    const [rawQuery, setRawQuery] = useState("");
    const [debouncedQuery, setDebouncedQuery] = useState("");
    const [isSearching, setIsSearching] = useState(false);
    const [liveResults, setLiveResults] = useState({
        posts: [],
        users: [],
        topics: [],
    });
    const [liveError, setLiveError] = useState("");

    const [trendingTopics, setTrendingTopics] = useState(() => loadTrendingCache(viewerKey) || []);
    const [isLoadingTrending, setIsLoadingTrending] = useState(false);
    const trendingFetchedRef = useRef(false);

    const [recentSearches, setRecentSearches] = useState(() => loadRecents());

    useEffect(() => {
        mountedRef.current = true;
        return () => {
            mountedRef.current = false;
        };
    }, []);

    // Debounce the raw query → debouncedQuery. As soon as the user types
    // a new non-empty query, flip `isSearching` immediately so the dropdown
    // shows a "Searching…" state (or keeps the previous results visible)
    // instead of flashing the stale "no results" empty block during the
    // debounce window.
    useEffect(() => {
        const trimmed = rawQuery.trim();
        if (!trimmed) {
            setDebouncedQuery("");
            setLiveResults({ posts: [], users: [], topics: [] });
            setIsSearching(false);
            setLiveError("");
            return undefined;
        }
        setIsSearching(true);
        setLiveError("");
        const handle = setTimeout(() => {
            if (!mountedRef.current) return;
            setDebouncedQuery(trimmed);
        }, DEBOUNCE_MS);
        return () => clearTimeout(handle);
    }, [rawQuery]);

    // Run live search when the debounced query changes.
    useEffect(() => {
        if (!debouncedQuery) return undefined;
        let cancelled = false;
        setIsSearching(true);
        setLiveError("");
        const params = {
            q: debouncedQuery,
            limit: LIVE_LIMIT,
        };
        if (viewerAddress) params.address = viewerAddress;
        params.allowed_tags = getAllowedTagsParam();

        Api.get("search", params, { timeoutMs: 10000 })
            .then((data) => {
                if (cancelled || !mountedRef.current) return;
                setLiveResults({
                    posts: Array.isArray(data?.posts) ? data.posts : [],
                    users: Array.isArray(data?.users) ? data.users : [],
                    topics: Array.isArray(data?.topics) ? data.topics : [],
                });
                setIsSearching(false);
            })
            .catch((err) => {
                if (cancelled || !mountedRef.current) return;
                setLiveError(err?.message || "Search failed");
                setIsSearching(false);
            });

        return () => {
            cancelled = true;
        };
    }, [debouncedQuery, viewerAddress]);

    // Lazy trending-topics fetch. Single-shot per hook instance, with a 5-min
    // localStorage cache to avoid re-fetching across re-mounts inside the
    // session. Callers that care (TopBar) invoke `loadTrending()` when the
    // user opens the dropdown; callers that don't (SearchResultsView, mobile
    // search route) opt into eager via `trendingEnabled: true`.
    const loadTrending = useCallback(() => {
        if (trendingFetchedRef.current) return;
        const cached = loadTrendingCache(viewerKey);
        if (cached && cached.length > 0) {
            trendingFetchedRef.current = true;
            setTrendingTopics(cached);
            return;
        }
        trendingFetchedRef.current = true;
        setIsLoadingTrending(true);
        Api.get(
            "get_topics",
            {
                limit: 40,
                min_posts: 10,
                address: viewerKey,
                allowed_tags: getAllowedTagsParam(),
            },
            { timeoutMs: 10000 }
        )
            .then((data) => {
                if (!mountedRef.current) return;
                const list = Array.isArray(data?.topics) ? data.topics : [];
                const sorted = [...list]
                    .filter((t) => t && t.topic)
                    .sort(
                        (a, b) =>
                            (b.post_count || b.count || 0) -
                            (a.post_count || a.count || 0)
                    )
                    .slice(0, TRENDING_LIMIT);
                setTrendingTopics(sorted);
                setIsLoadingTrending(false);
                persistTrendingCache(viewerKey, sorted);
            })
            .catch(() => {
                if (!mountedRef.current) return;
                setTrendingTopics([]);
                setIsLoadingTrending(false);
                // Allow retry on next caller-initiated open.
                trendingFetchedRef.current = false;
            });
    }, [viewerKey]);

    useEffect(() => {
        trendingFetchedRef.current = false;
        setTrendingTopics(loadTrendingCache(viewerKey) || []);
    }, [viewerKey]);

    useEffect(() => {
        if (!trendingEnabled) return;
        loadTrending();
    }, [trendingEnabled, loadTrending]);

    const addRecentSearch = useCallback((query) => {
        const trimmed = String(query || "").trim();
        if (!trimmed) return;
        setRecentSearches((prev) => {
            const lower = trimmed.toLowerCase();
            const filtered = prev.filter(
                (entry) => String(entry.query || "").toLowerCase() !== lower
            );
            const next = [
                { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, query: trimmed, timestamp: Date.now() },
                ...filtered,
            ].slice(0, MAX_RECENTS);
            persistRecents(next);
            return next;
        });
    }, []);

    const removeRecentSearch = useCallback((id) => {
        setRecentSearches((prev) => {
            const next = prev.filter((entry) => entry.id !== id);
            persistRecents(next);
            return next;
        });
    }, []);

    const clearRecentSearches = useCallback(() => {
        setRecentSearches([]);
        persistRecents([]);
    }, []);

    const setQuery = useCallback((q) => {
        setRawQuery(q);
    }, []);

    const resetQuery = useCallback(() => {
        setRawQuery("");
        setDebouncedQuery("");
        setLiveResults({ posts: [], users: [], topics: [] });
        setIsSearching(false);
        setLiveError("");
    }, []);

    const hasQuery = useMemo(() => rawQuery.trim().length > 0, [rawQuery]);
    const hasLiveResults = useMemo(
        () =>
            liveResults.posts.length > 0 ||
            liveResults.users.length > 0 ||
            liveResults.topics.length > 0,
        [liveResults]
    );

    return {
        rawQuery,
        setQuery,
        resetQuery,
        debouncedQuery,
        isSearching,
        liveResults,
        liveError,
        hasQuery,
        hasLiveResults,
        trendingTopics,
        isLoadingTrending,
        loadTrending,
        recentSearches,
        addRecentSearch,
        removeRecentSearch,
        clearRecentSearches,
    };
}
