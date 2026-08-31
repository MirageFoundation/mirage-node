import { onSessionReset } from './sessionLifecycle';

const hiddenPosts = new Set();
const hiddenUsers = new Set();

onSessionReset(({ reason }) => {
    hiddenPosts.clear();
    hiddenUsers.clear();
    console.debug('[curation] optimistic visibility cleared on session reset', { reason });
});

function visibilityKey(community, teamId, target) {
    const slug = String(community || '').trim().toLowerCase();
    const id = Number(teamId);
    const normalizedTarget = String(target || '').trim().toLowerCase();
    if (!slug || !Number.isSafeInteger(id) || id <= 0 || !normalizedTarget) {
        throw new Error('Invalid optimistic curation visibility identity');
    }
    return `${slug}:${id}:${normalizedTarget}`;
}

export function setOptimisticCurationVisibility({ community, teamId, kind, target, hidden }) {
    if (kind !== 'post' && kind !== 'user') {
        throw new Error(`Invalid curation visibility kind: ${kind}`);
    }
    const key = visibilityKey(community, teamId, target);
    const entries = kind === 'post' ? hiddenPosts : hiddenUsers;
    if (hidden) entries.add(key);
    else entries.delete(key);
    window.dispatchEvent(new CustomEvent('curationModerationOptimistic', {
        detail: {
            community: String(community).trim().toLowerCase(),
            teamId: Number(teamId),
            kind,
            target: String(target).trim().toLowerCase(),
            hidden: !!hidden,
        },
    }));
}

export function isOptimisticallyCurationHidden(post) {
    const community = String(post?.topic || post?.community || '').trim().toLowerCase();
    const teamId = Number(post?.lens?.effective_team_id);
    const postId = String(post?.post_id || '').trim().toLowerCase();
    const author = String(post?.user_id || post?.author || '').trim().toLowerCase();
    if (!community || !Number.isSafeInteger(teamId) || teamId <= 0) return false;
    return (
        (postId && hiddenPosts.has(visibilityKey(community, teamId, postId)))
        || (author && hiddenUsers.has(visibilityKey(community, teamId, author)))
    );
}
