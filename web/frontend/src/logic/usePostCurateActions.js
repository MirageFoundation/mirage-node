import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    HiOutlineEye,
    HiOutlineEyeSlash,
    HiOutlineLockClosed,
    HiOutlineLockOpen,
    HiOutlineNoSymbol,
    HiOutlineTag,
    HiOutlineUser,
} from 'react-icons/hi2';
import Api from '../utils/api';
import Storage from '../utils/Storage';
import * as tx from '../utils/tx';
import { formatError } from '../utils/errorMessages';
import { updateNotification } from '../utils/notifications';
import { usePendingCuration } from './usePendingCuration';
import { useViewerCuratorMembership } from './useViewerCuratorMembership';
import { TAG_OPTIONS } from './useCreatePost';
import { viewingTeamId as viewingTeamIdOf } from '../utils/curation';
import { setOptimisticCurationVisibility } from '../utils/curationVisibility';
import { CURATOR_READ_ACTION, signReadParams } from '../utils/signPlain';

// Distinct from the '' tag: '' is the curator saying "untagged", this is the
// curator having no opinion so the community tag and author tag apply again.
const INHERIT_TAG = '__inherit__';
const POST_TAG_OPTIONS = [
    { value: INHERIT_TAG, label: 'No override' },
    ...TAG_OPTIONS.map(({ value, label }) => ({ value, label: value ? label : 'Untagged' })),
];

// Survives the curate menu unmounting on close, so a reopen that beats the
// indexer still shows the tag we just wrote instead of the previous one.
const optimisticByPost = new Map();

function optimisticCacheKey(community, teamId, postId) {
    return `${community}:${teamId}:${postId}`;
}

function postCommunity(post) {
    const community = typeof post?.community === 'string' ? post.community.trim() : '';
    return community.toLowerCase();
}

/**
 * Curate actions for a single post, visible only when the viewer is a
 * curator of a team in that post's community AND the post is currently
 * being viewed through that team's lens (not uncensored, not another team).
 *
 * Pass `active` (menu open) so moderation state is fetched only then.
 * Each pair is a toggle: Hide XOR Show, never both.
 */
export function usePostCurateActions(post, { active = false, updatePost } = {}) {
    const community = postCommunity(post);
    const postId = post?.post_id ? String(post.post_id).toLowerCase() : '';
    const postKey = post?.post_id ? String(post.post_id) : '';
    const author = String(post?.user_id || post?.author || '').trim().toLowerCase();
    const rootHash = String(post?.root_post_id || postId || '').trim().toLowerCase();
    const viewer = String(Storage.load('publicKey', '') || '').toLowerCase();
    const { teamId, teamName, isCurator, loading: membershipLoading } = useViewerCuratorMembership(community);
    const viewingTeamId = viewingTeamIdOf(post);
    const isOwnContent = !!author && author === viewer;
    const viewingAsCuratorTeam = isCurator && !isOwnContent && !!teamId && viewingTeamId === teamId;
    const { getInfo, getStatus } = usePendingCuration();
    const cacheKey = community && teamId && postId ? optimisticCacheKey(community, teamId, postId) : '';
    const storedOptimistic = cacheKey ? optimisticByPost.get(cacheKey) : null;
    const [modState, setModState] = useState(storedOptimistic?.modState || null);
    const [modError, setModError] = useState('');
    const [modLoading, setModLoading] = useState(false);
    // Pending optimistic patch. A fetch that beats the indexer must not
    // overwrite these fields, or the menu snaps back after "Transaction submitted".
    const optimisticRef = useRef(storedOptimistic?.patch || null);
    // Effective tag while this team had no override — used when the curator
    // later picks "No override" so the badge can revert without a round-trip.
    const inheritedTagRef = useRef(storedOptimistic?.inheritedTag);

    useEffect(() => {
        if (!active || !viewingAsCuratorTeam || !teamId || !community || !postId || !author || !viewer || viewer === 'guest') {
            return undefined;
        }
        let cancelled = false;
        const tagAtOpen = typeof post?.tag === 'string' ? post.tag : '';
        setModLoading(true);
        setModError('');
        console.debug('[curation] load moderation state', {
            community,
            teamId,
            postId: postId.slice(0, 12),
        });
        signReadParams(CURATOR_READ_ACTION, viewer)
            .then((proof) => Api.get(
                `communities/${encodeURIComponent(community)}/teams/${teamId}/moderation`,
                {
                    viewer,
                    post_id: postId,
                    author,
                    root: rootHash,
                    _cb: Date.now(),
                    ...proof,
                },
            ))
            .then((data) => {
                if (cancelled) return;
                if (typeof data?.post_hidden !== 'boolean'
                    || typeof data?.user_hidden !== 'boolean'
                    || typeof data?.thread_locked !== 'boolean') {
                    throw new Error('Invalid moderation state response');
                }
                const fetchedTag = typeof data.post_tag === 'string' ? data.post_tag : null;
                if (fetchedTag === null && inheritedTagRef.current === undefined) {
                    inheritedTagRef.current = tagAtOpen;
                }
                const pending = optimisticRef.current;
                const next = {
                    postHidden: data.post_hidden,
                    userHidden: data.user_hidden,
                    threadLocked: data.thread_locked,
                    // null means this team has no tag opinion on the post; ''
                    // means a curator marked it untagged.
                    postTag: fetchedTag,
                };
                if (pending && typeof pending === 'object') {
                    const confirmed = Object.keys(pending).every((key) => next[key] === pending[key]);
                    if (confirmed) {
                        optimisticRef.current = null;
                        if (cacheKey) optimisticByPost.delete(cacheKey);
                        console.debug('[curation] optimistic confirmed by fetch', {
                            community,
                            teamId,
                            postId: postId.slice(0, 12),
                            pending,
                        });
                    } else {
                        Object.assign(next, pending);
                        console.debug('[curation] keeping optimistic over stale fetch', {
                            community,
                            teamId,
                            postId: postId.slice(0, 12),
                            pending,
                        });
                    }
                }
                setModState(next);
                setModError('');
            })
            .catch((err) => {
                if (cancelled) return;
                const message = String(err?.message || err);
                if (optimisticRef.current) {
                    console.error('[curation] moderation state failed, keeping optimistic', {
                        community,
                        teamId,
                        error: message,
                    });
                    setModError('');
                    return;
                }
                setModState(null);
                setModError(message);
                console.error('[curation] moderation state failed', {
                    community,
                    teamId,
                    error: message,
                });
            })
            .finally(() => {
                if (!cancelled) setModLoading(false);
            });
        return () => { cancelled = true; };
    }, [active, author, cacheKey, community, viewingAsCuratorTeam, postId, rootHash, teamId, viewer]);

    const applyDisplayedTag = useCallback((nextTag, { optimistic } = {}) => {
        if (typeof updatePost !== 'function' || !postKey) return;
        const patch = { tag: nextTag };
        if (optimistic) patch._optimisticTag = nextTag;
        else patch._optimisticTag = undefined;
        updatePost(postKey, patch);
        console.debug('[curation] displayed tag', {
            postId: postKey.slice(0, 12),
            tag: nextTag,
            optimistic: !!optimistic,
        });
    }, [postKey, updatePost]);

    const applyDisplayedLock = useCallback((locked, { optimistic } = {}) => {
        if (typeof updatePost !== 'function') return;
        const keys = [postKey, rootHash, post?.root_post_id, post?.post_id]
            .map((key) => String(key || '').trim())
            .filter(Boolean);
        const patch = { thread_locked: !!locked };
        if (optimistic) patch._optimisticLock = !!locked;
        else patch._optimisticLock = undefined;
        for (const key of new Set(keys)) {
            updatePost(key, patch);
        }
        console.debug('[curation] displayed lock', {
            postId: (postKey || rootHash).slice(0, 12),
            locked: !!locked,
            optimistic: !!optimistic,
        });
    }, [post, postKey, rootHash, updatePost]);

    const applyDisplayedVisibility = useCallback((kind, target, hidden) => {
        if (kind !== 'post' && kind !== 'user') throw new Error(`Invalid curation visibility kind: ${kind}`);
        const normalizedTarget = String(target || '').trim().toLowerCase();
        if (!community || !teamId || !normalizedTarget) return;
        setOptimisticCurationVisibility({
            community,
            teamId,
            kind,
            target: normalizedTarget,
            hidden,
        });
        console.debug('[curation] displayed visibility', {
            community,
            teamId,
            kind,
            target: normalizedTarget.slice(0, 12),
            hidden: !!hidden,
        });
    }, [community, teamId]);

    const run = useCallback(async (label, operation, optimistic) => {
        const snapshot = modState;
        const previousTag = typeof post?.tag === 'string' ? post.tag : '';
        const previousLock = (optimistic && Object.prototype.hasOwnProperty.call(optimistic, 'threadLocked'))
            ? !optimistic.threadLocked
            : !!post?.thread_locked;
        if (optimistic && typeof optimistic === 'object') {
            optimisticRef.current = { ...(optimisticRef.current || {}), ...optimistic };
            const nextMod = {
                postHidden: false,
                userHidden: false,
                threadLocked: false,
                postTag: null,
                ...(modState || {}),
                ...optimistic,
            };
            setModState(nextMod);
            if (cacheKey) {
                optimisticByPost.set(cacheKey, {
                    patch: optimisticRef.current,
                    inheritedTag: inheritedTagRef.current,
                    modState: nextMod,
                });
            }
            if (Object.prototype.hasOwnProperty.call(optimistic, 'postTag')) {
                const nextTag = optimistic.postTag === null
                    ? (inheritedTagRef.current !== undefined ? inheritedTagRef.current : previousTag)
                    : String(optimistic.postTag);
                applyDisplayedTag(nextTag, { optimistic: true });
            }
            if (Object.prototype.hasOwnProperty.call(optimistic, 'threadLocked')) {
                applyDisplayedLock(optimistic.threadLocked, { optimistic: true });
            }
            if (Object.prototype.hasOwnProperty.call(optimistic, 'postHidden')) {
                applyDisplayedVisibility('post', postId, optimistic.postHidden);
            }
            if (Object.prototype.hasOwnProperty.call(optimistic, 'userHidden')) {
                applyDisplayedVisibility('user', author, optimistic.userHidden);
            }
            console.debug('[curation] optimistic apply', {
                label,
                community,
                teamId,
                postId: postId.slice(0, 12),
                optimistic,
            });
        }
        const revert = () => {
            optimisticRef.current = null;
            if (cacheKey) optimisticByPost.delete(cacheKey);
            if (snapshot) setModState(snapshot);
            if (optimistic && Object.prototype.hasOwnProperty.call(optimistic, 'postTag')) {
                applyDisplayedTag(previousTag, { optimistic: false });
            }
            if (optimistic && Object.prototype.hasOwnProperty.call(optimistic, 'threadLocked')) {
                applyDisplayedLock(previousLock, { optimistic: false });
            }
            if (optimistic && Object.prototype.hasOwnProperty.call(optimistic, 'postHidden')) {
                applyDisplayedVisibility('post', postId, !!snapshot?.postHidden);
            }
            if (optimistic && Object.prototype.hasOwnProperty.call(optimistic, 'userHidden')) {
                applyDisplayedVisibility('user', author, !!snapshot?.userHidden);
            }
            console.debug('[curation] optimistic revert', {
                label,
                community,
                teamId,
                postId: postId.slice(0, 12),
            });
        };
        try {
            console.debug('[curation] post curate action', { label, community, teamId, postId: postId.slice(0, 12) });
            const result = await operation();
            if (!result?.success) {
                revert();
                updateNotification(formatError(result), 4);
                return;
            }
        } catch (err) {
            revert();
            const message = err instanceof Error ? err.message : formatError(err);
            console.error('[curation] post curate failed', { label, error: message });
            updateNotification(message, 4);
        }
    }, [applyDisplayedLock, applyDisplayedTag, applyDisplayedVisibility, author, cacheKey, community, modState, post, postId, teamId]);

    const items = useMemo(() => {
        if (!isCurator || !teamId || !community || !postId || !modState) return [];
        const pending = (action, target) => !!getInfo(action, community, teamId, target);
        const status = (action, target, fallback) => getStatus(action, community, teamId, target, fallback);

        const out = [];
        if (modState.postHidden) {
            out.push({
                key: 'restore_post',
                label: status('set_curation_post_hidden', postId, 'Unbanning…') || 'Unban post',
                danger: false,
                disabled: pending('set_curation_post_hidden', postId),
                icon: <HiOutlineEye />,
                run: () => run(
                    'Unban post',
                    () => tx.moderateCurationPost(community, teamId, postId, false),
                    { postHidden: false },
                ),
            });
        } else {
            out.push({
                key: 'hide_post',
                label: status('set_curation_post_hidden', postId, 'Banning…') || 'Ban post',
                danger: true,
                disabled: pending('set_curation_post_hidden', postId),
                icon: <HiOutlineEyeSlash />,
                confirm: {
                    title: 'Ban this post?',
                    message: "This post will be hidden from this curation team's feed. You can unban it later from the team's Banned posts tab.",
                    label: 'Ban post',
                },
                run: () => run(
                    'Ban post',
                    () => tx.moderateCurationPost(community, teamId, postId, true),
                    { postHidden: true },
                ),
            });
        }

        if (modState.userHidden) {
            out.push({
                key: 'restore_user',
                label: status('set_curation_user_hidden', author, 'Unbanning…') || 'Unban user',
                danger: false,
                disabled: !author || pending('set_curation_user_hidden', author),
                icon: <HiOutlineUser />,
                run: () => run(
                    'Unban user',
                    () => tx.moderateCurationUser(community, teamId, author, false),
                    { userHidden: false },
                ),
            });
        } else {
            out.push({
                key: 'hide_user',
                label: status('set_curation_user_hidden', author, 'Banning…') || 'Ban user',
                danger: true,
                disabled: !author || pending('set_curation_user_hidden', author),
                icon: <HiOutlineNoSymbol />,
                confirm: {
                    title: 'Ban this user?',
                    message: "Content from this user will be hidden from this curation team's feed. You can unban them later from the team's Banned users tab.",
                    label: 'Ban user',
                },
                run: () => run(
                    'Ban user',
                    () => tx.moderateCurationUser(community, teamId, author, true),
                    { userHidden: true },
                ),
            });
        }

        if (modState.threadLocked) {
            out.push({
                key: 'unlock_thread',
                label: status('set_curation_thread_locked', rootHash, 'Unlocking…') || 'Unlock thread',
                danger: false,
                disabled: !rootHash || pending('set_curation_thread_locked', rootHash),
                icon: <HiOutlineLockOpen />,
                run: () => run(
                    'Unlock thread',
                    () => tx.setCurationThreadLocked(community, teamId, rootHash, false),
                    { threadLocked: false },
                ),
            });
        } else {
            out.push({
                key: 'lock_thread',
                label: status('set_curation_thread_locked', rootHash, 'Locking…') || 'Lock thread',
                danger: true,
                disabled: !rootHash || pending('set_curation_thread_locked', rootHash),
                icon: <HiOutlineLockClosed />,
                run: () => run(
                    'Lock thread',
                    () => tx.setCurationThreadLocked(community, teamId, rootHash, true),
                    { threadLocked: true },
                ),
            });
        }

        // A select rather than one row per tag: six extra rows would swamp the
        // menu, and the choices are mutually exclusive anyway.
        out.push({
            key: 'post_tag',
            type: 'select',
            label: 'Content tag',
            icon: <HiOutlineTag />,
            value: modState.postTag === null ? INHERIT_TAG : modState.postTag,
            options: POST_TAG_OPTIONS,
            disabled: pending('set_curation_post_tag', postId),
            status: status('set_curation_post_tag', postId, 'Tagging…'),
            onSelect: (value) => {
                const clear = value === INHERIT_TAG;
                run(
                    'Tag post',
                    () => tx.setCurationPostTag(community, teamId, postId, clear ? '' : value, clear),
                    { postTag: clear ? null : value },
                );
            },
        });
        return out;
    }, [author, community, getInfo, getStatus, isCurator, modState, postId, rootHash, run, teamId]);

    return {
        visible: viewingAsCuratorTeam && !!community && !!postId,
        loading: membershipLoading || (active && modLoading),
        modError,
        teamId,
        teamName,
        community,
        items,
    };
}

export default usePostCurateActions;
