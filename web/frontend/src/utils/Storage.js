class Storage {
    // Used for security: if user hasn't visited in a long time, force logout + clear storage.
    // Avoid class field syntax for broad compatibility with older build tooling.
    static lastSeenKey() { return '__mirage_last_seen_ms'; }

    static save(key, value) {
        if (typeof window !== 'undefined' && window.localStorage) {
            window.localStorage.setItem(key, JSON.stringify(value));
        }
    }

    /**
     * Persist a small, recency-ordered map of the viewer's own votes.
     *
     * Why: reading/parsing a huge JSON blob on every render is expensive.
     * We only need a small recent cache for "reload before indexing catches up"
     * cases; the API already returns user_vote for fetched posts/comments.
     */
    static setVote(targetId, direction, maxEntries = 100) {
        try {
            const key = String(targetId || '').trim().toLowerCase();
            if (!key) return;
            const dir = Number(direction) || 0;

            const votes = this.load('votes', {}) || {};

            // Update recency ordering (delete + reinsert)
            if (Object.prototype.hasOwnProperty.call(votes, key)) {
                delete votes[key];
            }
            if (dir !== 0) {
                votes[key] = dir;
            }

            const keys = Object.keys(votes);
            if (keys.length > maxEntries) {
                const pruned = {};
                const keep = keys.slice(-maxEntries);
                for (const k of keep) pruned[k] = votes[k];
                this.save('votes', pruned);
            } else {
                this.save('votes', votes);
            }
        } catch (_) { /* noop */ }
    }

    static getVote(targetId, defaultDir = null) {
        try {
            const key = String(targetId || '').trim().toLowerCase();
            if (!key) return defaultDir;
            const votes = this.load('votes', {}) || {};
            const v = votes[key];
            return typeof v === 'number' ? v : defaultDir;
        } catch (_) {
            return defaultDir;
        }
    }


    static load(key, defaultValue) {
        if (typeof window !== 'undefined' && window.localStorage) {
            const storedValue = window.localStorage.getItem(key);
            try {
                let out = storedValue ? JSON.parse(storedValue) : defaultValue;
                return out;
            } catch (e) {
                // console.error("Error parsing JSON from localStorage for key:", key, e);
                return defaultValue;
            }
        }
        return defaultValue;
    }


    static remove(key) {
        if (typeof window !== 'undefined' && window.localStorage) {
            window.localStorage.removeItem(key);
        }
    }

    // v1.39.0 renamed the last topic-named storage keys. Caches are not listed:
    // they refetch. These two are user settings, so move the value once and drop
    // the old key, rather than silently resetting someone's sidebar to default.
    static _RENAMED_KEYS = [
        ['sidebar_topics_limit', 'sidebar_communities_limit'],
        ['sidebar_people_limit', 'sidebar_users_limit'],
    ];

    static migrateRenamedKeys() {
        if (typeof window === 'undefined' || !window.localStorage) return;
        for (const [from, to] of Storage._RENAMED_KEYS) {
            const raw = window.localStorage.getItem(from);
            if (raw === null) continue;
            if (window.localStorage.getItem(to) === null) {
                window.localStorage.setItem(to, raw);
            }
            window.localStorage.removeItem(from);
        }
    }

    static clear() {
        // Preserve the Mirage analytics visitor id across auth cleanup: it is a
        // device identity, not auth state, and must survive logout/account reset
        // so a returning lurker-turned-user stays one analytics identity.
        Storage._clearPreservingAnalytics(window.localStorage);
    }

    // Keys in the analytics namespace that must outlive any storage reset.
    // Mirrors VISITOR_ID_KEY in utils/visitorId.js (identity wire contract).
    static _ANALYTICS_KEYS = ['mirage_analytics_visitor_id'];

    static _clearPreservingAnalytics(store) {
        if (typeof window === 'undefined' || !store) return;
        try {
            const preserved = {};
            for (const k of Storage._ANALYTICS_KEYS) {
                const v = store.getItem(k);
                if (v !== null) preserved[k] = v;
            }
            store.clear();
            for (const [k, v] of Object.entries(preserved)) {
                store.setItem(k, v);
            }
        } catch (_) {
            try { store.clear(); } catch (__) { /* noop */ }
        }
    }

    static getLastSeenMs() {
        try {
            const v = this.load(this.lastSeenKey(), 0);
            const n = Number(v);
            return Number.isFinite(n) ? n : 0;
        } catch (_) {
            return 0;
        }
    }

    static touchLastSeen() {
        try {
            this.save(this.lastSeenKey(), Date.now());
        } catch (_) { /* noop */ }
    }

    static hardResetAllStorage() {
        // Requirement: clear the entire local storage. We also clear sessionStorage to
        // avoid restoring stale UI state after a forced logout. The analytics visitor
        // id is preserved (device identity, not auth state) per the identity contract.
        try {
            if (typeof window !== 'undefined' && window.localStorage) {
                Storage._clearPreservingAnalytics(window.localStorage);
            }
        } catch (_) { /* noop */ }
        try {
            if (typeof window !== 'undefined' && window.sessionStorage) {
                window.sessionStorage.clear();
            }
        } catch (_) { /* noop */ }
    }

    static getLastVisitCommentCount(postId) {
        const key = `last_visit_comments_${postId}`;
        const stored = this.load(key, null);
        return stored !== null ? Number(stored) : null;
    }

    static setLastVisitCommentCount(postId, count) {
        const key = `last_visit_comments_${postId}`;
        this.save(key, Number(count));
    }

    static getLastVisitTimestamp(postId) {
        const key = `last_visit_ts_${postId}`;
        const stored = this.load(key, null);
        return stored !== null ? Number(stored) : null;
    }

    static setLastVisitTimestamp(postId, tsSec) {
        const key = `last_visit_ts_${postId}`;
        this.save(key, Number(tsSec));
    }

    static getViewedReplyIds() {
        return this.load('viewed_reply_ids', []);
    }

    static addViewedReplyId(replyId) {
        const viewed = this.getViewedReplyIds();
        if (!viewed.includes(replyId)) {
            viewed.push(replyId);
            this.save('viewed_reply_ids', viewed);
        }
    }

    static markAllRepliesAsViewed(replyIds = []) {
        const viewed = this.getViewedReplyIds();
        const combined = Array.from(new Set([...viewed, ...replyIds]));
        this.save('viewed_reply_ids', combined);
    }

    static setPendingPostHighlight(postId) {
        if (!postId) return;
        const normalized = String(postId).toLowerCase();
        this.save('pending_post_highlight', normalized);
    }

    static consumePendingPostHighlight() {
        const value = this.load('pending_post_highlight', null);
        if (value !== null && value !== undefined) {
            this.remove('pending_post_highlight');
            return String(value).toLowerCase();
        }
        return null;
    }

    static setOptimisticPost(post, maxEntries = 20) {
        try {
            const postId = String(post?.post_id || '').trim().toLowerCase();
            if (!postId) return;
            const posts = this.load('optimistic_posts', {}) || {};
            posts[postId] = {
                ...post,
                post_id: postId,
                _optimistic: true,
                optimistic_cached_at_ms: Date.now(),
            };
            const entries = Object.entries(posts).sort((a, b) => {
                const av = Number(a[1]?.optimistic_cached_at_ms || 0);
                const bv = Number(b[1]?.optimistic_cached_at_ms || 0);
                return av - bv;
            });
            while (entries.length > maxEntries) {
                const [oldestId] = entries.shift();
                delete posts[oldestId];
            }
            this.save('optimistic_posts', posts);
        } catch (_) { /* noop */ }
    }

    static getOptimisticPost(postId, maxAgeMs = 10 * 60 * 1000) {
        try {
            const normalized = String(postId || '').trim().toLowerCase();
            if (!normalized) return null;
            const posts = this.load('optimistic_posts', {}) || {};
            const post = posts[normalized];
            if (!post) return null;
            const cachedAt = Number(post.optimistic_cached_at_ms || 0);
            if (!Number.isFinite(cachedAt) || cachedAt <= 0 || Date.now() - cachedAt > maxAgeMs) {
                delete posts[normalized];
                this.save('optimistic_posts', posts);
                return null;
            }
            return post;
        } catch (_) {
            return null;
        }
    }

    static removeOptimisticPost(postId) {
        try {
            const normalized = String(postId || '').trim().toLowerCase();
            if (!normalized) return;
            const posts = this.load('optimistic_posts', {}) || {};
            if (!Object.prototype.hasOwnProperty.call(posts, normalized)) return;
            delete posts[normalized];
            this.save('optimistic_posts', posts);
        } catch (_) { /* noop */ }
    }
}

export default Storage;