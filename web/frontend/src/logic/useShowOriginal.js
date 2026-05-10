import { useEffect, useState } from "react";

/**
 * Per-post toggle for "Show original" / "Show modified" content when an
 * agent (e.g. SafeSpaceBot) has overlaid a post. The toggle is in-memory
 * only — it intentionally does not persist across reloads, since the
 * default state ("show modified") matches the user's own moderation
 * choice.
 *
 * The store is a small Map<post_id, true> with a listener set so any
 * component that calls `useShowOriginal(postId)` re-renders when the
 * toggle for that post flips.
 */

const store = new Map();
const listeners = new Set();

const notify = () => {
    for (const fn of listeners) {
        try { fn(); } catch (_) { /* noop */ }
    }
};

export function isShowingOriginal(postId) {
    if (postId === undefined || postId === null) return false;
    return store.get(String(postId)) === true;
}

export function setShowingOriginal(postId, value) {
    if (postId === undefined || postId === null) return;
    const key = String(postId);
    if (value) store.set(key, true);
    else store.delete(key);
    notify();
}

export function toggleShowOriginal(postId) {
    setShowingOriginal(postId, !isShowingOriginal(postId));
}

export function useShowOriginal(postId) {
    const [, setTick] = useState(0);
    useEffect(() => {
        const fn = () => setTick(t => (t + 1) | 0);
        listeners.add(fn);
        return () => { listeners.delete(fn); };
    }, []);
    return isShowingOriginal(postId);
}

export default useShowOriginal;
