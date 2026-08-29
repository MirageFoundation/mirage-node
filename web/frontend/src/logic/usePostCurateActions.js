import { useCallback, useEffect, useMemo, useState } from 'react';
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

// Distinct from the '' tag: '' is the curator saying "untagged", this is the
// curator having no opinion so the community tag and author tag apply again.
const INHERIT_TAG = '__inherit__';
const POST_TAG_OPTIONS = [
    { value: INHERIT_TAG, label: 'No override' },
    ...TAG_OPTIONS.map(({ value, label }) => ({ value, label: value ? label : 'Untagged' })),
];

function postCommunity(post) {
    const topic = typeof post?.topic === 'string' ? post.topic.trim() : '';
    if (topic) return topic.toLowerCase();
    const community = typeof post?.community === 'string' ? post.community.trim() : '';
    return community.toLowerCase();
}

/**
 * Curate actions for a single post, visible only when the viewer is a
 * curator of a team in that post's community.
 *
 * Pass `active` (menu open) so moderation state is fetched only then.
 * Each pair is a toggle: Hide XOR Show, never both.
 */
export function usePostCurateActions(post, { active = false } = {}) {
    const community = postCommunity(post);
    const postId = post?.post_id ? String(post.post_id).toLowerCase() : '';
    const author = String(post?.user_id || post?.author || '').trim().toLowerCase();
    const rootHash = String(post?.root_post_id || postId || '').trim().toLowerCase();
    const viewer = String(Storage.load('publicKey', '') || '').toLowerCase();
    const { teamId, teamName, isCurator, loading: membershipLoading } = useViewerCuratorMembership(community);
    const { getInfo, getStatus } = usePendingCuration();
    const [modState, setModState] = useState(null);
    const [modError, setModError] = useState('');
    const [modLoading, setModLoading] = useState(false);

    useEffect(() => {
        if (!active || !isCurator || !teamId || !community || !postId || !author || !viewer || viewer === 'guest') {
            return undefined;
        }
        let cancelled = false;
        setModLoading(true);
        setModError('');
        console.debug('[curation] load moderation state', {
            community,
            teamId,
            postId: postId.slice(0, 12),
        });
        Api.get(
            `communities/${encodeURIComponent(community)}/teams/${teamId}/moderation`,
            {
                viewer,
                post_id: postId,
                author,
                root: rootHash,
                _cb: Date.now(),
            },
        )
            .then((data) => {
                if (cancelled) return;
                if (typeof data?.post_hidden !== 'boolean'
                    || typeof data?.user_hidden !== 'boolean'
                    || typeof data?.thread_locked !== 'boolean') {
                    throw new Error('Invalid moderation state response');
                }
                setModState({
                    postHidden: data.post_hidden,
                    userHidden: data.user_hidden,
                    threadLocked: data.thread_locked,
                    // null means this team has no tag opinion on the post; ''
                    // means a curator marked it untagged.
                    postTag: typeof data.post_tag === 'string' ? data.post_tag : null,
                });
                setModError('');
            })
            .catch((err) => {
                if (cancelled) return;
                const message = String(err?.message || err);
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
    }, [active, author, community, isCurator, postId, rootHash, teamId, viewer]);

    const run = useCallback(async (label, operation, optimistic) => {
        try {
            console.debug('[curation] post curate action', { label, community, teamId, postId: postId.slice(0, 12) });
            const result = await operation();
            if (!result?.success) {
                updateNotification(formatError(result), 4);
                return;
            }
            if (optimistic && typeof optimistic === 'object') {
                setModState((prev) => ({
                    postHidden: false,
                    userHidden: false,
                    threadLocked: false,
                    postTag: null,
                    ...(prev || {}),
                    ...optimistic,
                }));
            }
        } catch (err) {
            const message = err instanceof Error ? err.message : formatError(err);
            console.error('[curation] post curate failed', { label, error: message });
            updateNotification(message, 4);
        }
    }, [community, postId, teamId]);

    const items = useMemo(() => {
        if (!isCurator || !teamId || !community || !postId || !modState) return [];
        const pending = (action, target) => !!getInfo(action, community, teamId, target);
        const status = (action, target, fallback) => getStatus(action, community, teamId, target, fallback);

        const out = [];
        if (modState.postHidden) {
            out.push({
                key: 'restore_post',
                label: status('set_curation_post_hidden', postId, 'Restoring…') || 'Restore post',
                danger: false,
                disabled: pending('set_curation_post_hidden', postId),
                icon: <HiOutlineEye />,
                run: () => run(
                    'Restore post',
                    () => tx.moderateCurationPost(community, teamId, postId, false),
                    { postHidden: false },
                ),
            });
        } else {
            out.push({
                key: 'hide_post',
                label: status('set_curation_post_hidden', postId, 'Hiding…') || 'Hide post',
                danger: true,
                disabled: pending('set_curation_post_hidden', postId),
                icon: <HiOutlineEyeSlash />,
                run: () => run(
                    'Hide post',
                    () => tx.moderateCurationPost(community, teamId, postId, true),
                    { postHidden: true },
                ),
            });
        }

        if (modState.userHidden) {
            out.push({
                key: 'restore_user',
                label: status('set_curation_user_hidden', author, 'Restoring…') || 'Restore user',
                danger: false,
                disabled: !author || pending('set_curation_user_hidden', author),
                icon: <HiOutlineUser />,
                run: () => run(
                    'Restore user',
                    () => tx.moderateCurationUser(community, teamId, author, false),
                    { userHidden: false },
                ),
            });
        } else {
            out.push({
                key: 'hide_user',
                label: status('set_curation_user_hidden', author, 'Hiding…') || 'Hide user',
                danger: true,
                disabled: !author || pending('set_curation_user_hidden', author),
                icon: <HiOutlineNoSymbol />,
                run: () => run(
                    'Hide user',
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
        visible: isCurator && !!teamId && !!community && !!postId,
        loading: membershipLoading || (active && modLoading),
        modError,
        teamId,
        teamName,
        community,
        items,
    };
}

export default usePostCurateActions;
