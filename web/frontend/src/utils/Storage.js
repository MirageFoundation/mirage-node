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

    static clear() {
        if (typeof window !== 'undefined' && window.localStorage) {
            window.localStorage.clear();
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
        // avoid restoring stale UI state after a forced logout.
        try {
            if (typeof window !== 'undefined' && window.localStorage) {
                window.localStorage.clear();
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
}

export default Storage;