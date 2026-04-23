import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Storage from "../utils/Storage";
import { getAllowedTagsParam } from "../utils/ContentTags";
import Api from "../utils/api";

/**
 * Drives the TopBar search dropdown sheet for the mirageapp theme.
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
const MAX_RECENTS = 8;
const DEBOUNCE_MS = 300;
const LIVE_LIMIT = 5;
const TRENDING_LIMIT = 10;

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
    } catch (_) {}
}

export function useSearchDropdown() {
    const viewerAddress = Storage.load("publicKey", "") || "";
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

    const [trendingTopics, setTrendingTopics] = useState([]);
    const [isLoadingTrending, setIsLoadingTrending] = useState(false);

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

    // Load trending topics once (matches mobile `useTopics(20)`).
    useEffect(() => {
        let cancelled = false;
        setIsLoadingTrending(true);
        Api.get(
            "get_topics",
            {
                limit: 40,
                min_posts: 10,
                address: viewerAddress || "guest",
                allowed_tags: getAllowedTagsParam(),
            },
            { timeoutMs: 10000 }
        )
            .then((data) => {
                if (cancelled || !mountedRef.current) return;
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
            })
            .catch(() => {
                if (cancelled || !mountedRef.current) return;
                setTrendingTopics([]);
                setIsLoadingTrending(false);
            });
        return () => {
            cancelled = true;
        };
    }, [viewerAddress]);

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
        recentSearches,
        addRecentSearch,
        removeRecentSearch,
        clearRecentSearches,
    };
}
