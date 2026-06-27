import { useState, useEffect, useCallback, useRef } from 'react';
import * as tx from '../utils/tx';
import Storage from '../utils/Storage';
import { updateNotification } from '../utils/notifications';
import { markPostVoted } from './useSeenPosts';

export function usePendingVotes() {
    const [pendingVotes, setPendingVotes] = useState({});

    useEffect(() => {
        let unsubscribe = null;
        let mounted = true;
        let disposed = false;

        const setup = async () => {
            try {
                const initial = await tx.getPendingVotes();
                if (mounted) setPendingVotes(initial);
            } catch (_) { }

            const listenerCleanup = await tx.addVoteListener((votes) => {
                if (mounted) setPendingVotes(votes);
            });
            if (disposed) {
                try {
                    if (listenerCleanup) listenerCleanup();
                } catch (_) { }
                return;
            }
            unsubscribe = listenerCleanup;
        };

        setup();

        return () => {
            mounted = false;
            disposed = true;
            if (unsubscribe) unsubscribe();
        };
    }, []);

    const isPending = useCallback((postId) => {
        const key = String(postId || '').toLowerCase();
        return !!pendingVotes[key];
    }, [pendingVotes]);

    const getDirection = useCallback((postId) => {
        const key = String(postId || '').toLowerCase();
        return pendingVotes[key]?.direction || null;
    }, [pendingVotes]);

    return { pendingVotes, isPending, getDirection };
}

export function useVoteHandler({ state, updatePost }) {
    const { isPending } = usePendingVotes();
    const localPendingRef = useRef(new Set());

    const handleVote = useCallback(async (postObj, direction) => {
        const postIdValue = postObj?.post_id;
        const isLoggedIn = !!state.publicKey;

        if (!isLoggedIn || !postIdValue) return;

        const key = String(postIdValue).toLowerCase();
        if (isPending(postIdValue) || localPendingRef.current.has(key)) return;
        markPostVoted(postIdValue);
        localPendingRef.current.add(key);

        let current;
        if (state.posts && state.posts[postIdValue] && typeof state.posts[postIdValue].direction === 'number') {
            current = state.posts[postIdValue].direction;
        } else {
            const apiUserVote = postObj?.user_vote ?? postObj?.my_vote ?? postObj?.userVote ?? postObj?.myVote;
            if (apiUserVote !== undefined && apiUserVote !== null && Number.isFinite(Number(apiUserVote))) {
                current = Number(apiUserVote);
            } else {
                current = (postObj && typeof postObj.direction === 'number') ? postObj.direction : 0;
            }
        }

        const newDir = (current === direction) ? 0 : direction;

        if (typeof updatePost === 'function') {
            updatePost(postIdValue, { direction: newDir });
        }

        try {
            Storage.setVote(key, newDir, 100);
        } catch (_) { /* noop */ }

        if (newDir === -1) {
            window.dispatchEvent(new CustomEvent('postDownvoted', {
                detail: { postId: postIdValue, direction: newDir }
            }));
        }

        const userLevel = Number(Storage.load('user_level', '0') || 0);
        if (userLevel === 0) {
            // Keep this toast alive long enough to bridge the gap until the
            // TransactionHandler (lazy-loaded) starts emitting its own progress
            // ticks every 100ms. Using a short default would cause the toast
            // to fade out and back in (flicker) on slower devices.
            updateNotification("Processing", 10);
        }

        try {
            const result = await tx.createVote(postIdValue, newDir);
            if (result && result.success === false) {
                throw new Error(result.error || 'Vote failed');
            }
        } catch (e) {
            try {
                if (typeof updatePost === 'function') {
                    updatePost(postIdValue, { direction: current });
                }
                Storage.setVote(key, current, 100);
            } catch (_) { /* noop */ }
        } finally {
            localPendingRef.current.delete(key);
        }
    }, [state.publicKey, state.posts, isPending, updatePost]);

    const isLocallyPending = useCallback((postId) => {
        const key = String(postId || '').toLowerCase();
        return localPendingRef.current.has(key);
    }, []);

    return { handleVote, isPending, isLocallyPending };
}

export function resolveDirection(post, state) {
    if (state.posts && typeof state.posts[post.post_id]?.direction === 'number') {
        return state.posts[post.post_id].direction;
    }
    const apiUserVote = post?.user_vote ?? post?.my_vote ?? post?.userVote ?? post?.myVote;
    if (apiUserVote !== undefined && apiUserVote !== null && Number.isFinite(Number(apiUserVote))) {
        return Number(apiUserVote);
    }
    return (post && typeof post.direction === 'number') ? post.direction : 0;
}

export function computeDisplayVotes(post, direction) {
    const rawPoints = typeof post.points === 'number' ? post.points : Number(post.points) || 0;
    const userWeight = typeof post.user_weight === 'number' ? post.user_weight : Number(post.user_weight) || 0;
    return Math.round(rawPoints - userWeight + direction);
}
