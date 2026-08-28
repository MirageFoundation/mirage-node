import { useCallback, useMemo } from 'react';
import {
    HiOutlineEye,
    HiOutlineEyeSlash,
    HiOutlineLockClosed,
    HiOutlineLockOpen,
    HiOutlineNoSymbol,
    HiOutlineUser,
} from 'react-icons/hi2';
import * as tx from '../utils/tx';
import { formatError } from '../utils/errorMessages';
import { updateNotification } from '../utils/notifications';
import { usePendingCuration } from './usePendingCuration';
import { useViewerCuratorMembership } from './useViewerCuratorMembership';

function postCommunity(post) {
    const topic = typeof post?.topic === 'string' ? post.topic.trim() : '';
    if (topic) return topic.toLowerCase();
    const community = typeof post?.community === 'string' ? post.community.trim() : '';
    return community.toLowerCase();
}

/**
 * Curate actions for a single post, visible only when the viewer is a
 * curator of a team in that post's community.
 */
export function usePostCurateActions(post) {
    const community = postCommunity(post);
    const postId = post?.post_id ? String(post.post_id).toLowerCase() : '';
    const author = String(post?.user_id || post?.author || '').trim().toLowerCase();
    const rootHash = String(post?.root_post_id || postId || '').trim().toLowerCase();
    const { teamId, teamName, isCurator, loading } = useViewerCuratorMembership(community);
    const { getInfo, getStatus } = usePendingCuration();

    const run = useCallback(async (label, operation) => {
        try {
            console.debug('[curation] post curate action', { label, community, teamId, postId: postId.slice(0, 12) });
            const result = await operation();
            if (!result?.success) {
                updateNotification(formatError(result), 4);
                return;
            }
            updateNotification(`${label} queued`, 2);
        } catch (err) {
            const message = err instanceof Error ? err.message : formatError(err);
            console.error('[curation] post curate failed', { label, error: message });
            updateNotification(message, 4);
        }
    }, [community, postId, teamId]);

    const items = useMemo(() => {
        if (!isCurator || !teamId || !community || !postId) return [];
        const pending = (action, target) => !!getInfo(action, community, teamId, target);
        const status = (action, target, fallback) => getStatus(action, community, teamId, target, fallback);

        return [
            {
                key: 'hide_post',
                label: status('set_curation_post_hidden', postId, 'Hiding…') || 'Hide post',
                danger: true,
                disabled: pending('set_curation_post_hidden', postId),
                icon: <HiOutlineEyeSlash />,
                run: () => run('Hide post', () => tx.moderateCurationPost(community, teamId, postId, true)),
            },
            {
                key: 'show_post',
                label: status('set_curation_post_hidden', postId, 'Showing…') || 'Show post',
                danger: false,
                disabled: pending('set_curation_post_hidden', postId),
                icon: <HiOutlineEye />,
                run: () => run('Show post', () => tx.moderateCurationPost(community, teamId, postId, false)),
            },
            {
                key: 'hide_user',
                label: status('set_curation_user_hidden', author, 'Hiding…') || 'Hide user',
                danger: true,
                disabled: !author || pending('set_curation_user_hidden', author),
                icon: <HiOutlineNoSymbol />,
                run: () => run('Hide user', () => tx.moderateCurationUser(community, teamId, author, true)),
            },
            {
                key: 'show_user',
                label: status('set_curation_user_hidden', author, 'Showing…') || 'Show user',
                danger: false,
                disabled: !author || pending('set_curation_user_hidden', author),
                icon: <HiOutlineUser />,
                run: () => run('Show user', () => tx.moderateCurationUser(community, teamId, author, false)),
            },
            {
                key: 'lock_thread',
                label: status('set_curation_thread_locked', rootHash, 'Locking…') || 'Lock thread',
                danger: true,
                disabled: !rootHash || pending('set_curation_thread_locked', rootHash),
                icon: <HiOutlineLockClosed />,
                run: () => run('Lock thread', () => tx.setCurationThreadLocked(community, teamId, rootHash, true)),
            },
            {
                key: 'unlock_thread',
                label: status('set_curation_thread_locked', rootHash, 'Unlocking…') || 'Unlock thread',
                danger: false,
                disabled: !rootHash || pending('set_curation_thread_locked', rootHash),
                icon: <HiOutlineLockOpen />,
                run: () => run('Unlock thread', () => tx.setCurationThreadLocked(community, teamId, rootHash, false)),
            },
        ];
    }, [author, community, getInfo, getStatus, isCurator, postId, rootHash, run, teamId]);

    return {
        visible: isCurator && !!teamId && !!community && !!postId,
        loading,
        teamId,
        teamName,
        community,
        items,
    };
}

export default usePostCurateActions;
