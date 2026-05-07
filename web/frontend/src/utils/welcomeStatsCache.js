import Storage from "./Storage";

/**
 * Read the welcome stats cache populated by `useMain` and format it as the
 * `stats` array the logged-out prompt card expects. Returns an empty array
 * if the cache is empty or malformed so callers can unconditionally spread it.
 */
export function getCachedWelcomeStats() {
    let cached = null;
    try {
        cached = Storage.load("welcome_stats_cache", null);
    } catch (_) {
        cached = null;
    }
    if (!cached || typeof cached !== "object") return [];
    if (!cached.userCount || cached.userCount <= 0) return [];
    // Discard stale shape (pre-7d migration). Without this, the card would
    // render "Active (7d): 0" until fresh data arrives.
    if (typeof cached.active7d !== "number") return [];

    const prefix = cached.stale ? "~" : "";
    const users = Number(cached.userCount);
    const active = Number(cached.active7d);
    const posts = Number(cached.posts24h || 0) + Number(cached.comments24h || 0);

    return [
        { label: "Users", value: `${prefix}${users.toLocaleString()}` },
        { label: "Active (7d)", value: `${prefix}${active.toLocaleString()}` },
        { label: "Posts (24h)", value: `${prefix}${posts.toLocaleString()}` },
    ];
}
