import Api from '../utils/api';
import { CURATOR_READ_ACTION, signReadParams } from '../utils/signPlain';

// Opening a post's curate menu used to cost a signed round trip for that one
// post, even though the viewer's curator membership was already known and the
// menu is reachable for every post on the page. This caches the team's verdict
// per post and coalesces the misses into one request per team, so a feed page
// costs a single call and opening a menu costs none.
//
// Requests are batched rather than prefetched wholesale: a team's hidden-post
// list is unbounded, while the posts on screen are not.
//
// Must match MODERATION_BATCH_CAP in web/backend/routes/communities.py. It is
// one feed page, which is also as many 64-character ids as a query string can
// carry before the proxy rejects the request outright.
const BATCH_CAP = 50;
const FLUSH_DELAY_MS = 30;

/** `viewer::community::teamId` → Map(postId → state) */
const stateByTeam = new Map();
/** `viewer::community::teamId` → { postIds:Set, waiters:Map(postId → [resolve]), timer } */
const batches = new Map();

function teamKey(viewer, community, teamId) {
    return `${String(viewer || '').toLowerCase()}::${String(community || '').toLowerCase()}::${Number(teamId)}`;
}

function normalizeState(item) {
    if (typeof item?.post_hidden !== 'boolean'
        || typeof item?.user_hidden !== 'boolean'
        || typeof item?.thread_locked !== 'boolean') {
        throw new Error('Invalid moderation state entry');
    }
    return {
        postHidden: item.post_hidden,
        userHidden: item.user_hidden,
        threadLocked: item.thread_locked,
        // null means this team has no tag opinion on the post; '' means a
        // curator marked it untagged.
        postTag: typeof item.post_tag === 'string' ? item.post_tag : null,
    };
}

export function getCachedTeamModeration(viewer, community, teamId, postId) {
    const cached = stateByTeam.get(teamKey(viewer, community, teamId));
    return cached ? cached.get(String(postId || '').toLowerCase()) : undefined;
}

export function setCachedTeamModeration(viewer, community, teamId, postId, state) {
    const key = teamKey(viewer, community, teamId);
    if (!stateByTeam.has(key)) stateByTeam.set(key, new Map());
    stateByTeam.get(key).set(String(postId || '').toLowerCase(), state);
}

async function flush(key, viewer, community, teamId) {
    const batch = batches.get(key);
    if (!batch) return;
    batches.delete(key);
    const postIds = [...batch.postIds].slice(0, BATCH_CAP);
    // Anything over the cap is left unresolved on purpose; its waiter falls back
    // to the per-post read rather than being handed a missing entry.
    const overflow = [...batch.postIds].slice(BATCH_CAP);
    try {
        const proof = await signReadParams(CURATOR_READ_ACTION, viewer);
        const data = await Api.get(
            `communities/${encodeURIComponent(community)}/teams/${teamId}/moderation`,
            { viewer, post_ids: postIds.join(','), ...proof },
        );
        if (!data || !Array.isArray(data.items)) {
            throw new Error('Invalid batch moderation response');
        }
        for (const item of data.items) {
            const postId = String(item?.post_id || '').toLowerCase();
            if (!postId) throw new Error('Batch moderation entry is missing post_id');
            setCachedTeamModeration(viewer, community, teamId, postId, normalizeState(item));
        }
        console.debug('[curation] team moderation batch', {
            community,
            teamId,
            requested: postIds.length,
            received: data.items.length,
        });
        for (const [postId, resolvers] of batch.waiters) {
            const state = getCachedTeamModeration(viewer, community, teamId, postId);
            for (const resolve of resolvers) resolve(state);
        }
    } catch (err) {
        console.error('[curation] team moderation batch failed', {
            community,
            teamId,
            requested: postIds.length,
            error: String(err?.message || err),
        });
        for (const [, resolvers] of batch.waiters) {
            for (const resolve of resolvers) resolve(undefined);
        }
    }
    if (overflow.length) {
        console.debug('[curation] team moderation batch overflow', {
            community,
            teamId,
            deferred: overflow.length,
        });
    }
}

/**
 * Resolve one post's moderation state, coalescing concurrent misses for the
 * same team into a single request. Resolves `undefined` when the state could
 * not be established, which leaves the caller on the per-post read.
 */
export function requestTeamModeration(viewer, community, teamId, postId) {
    const owner = String(viewer || '').toLowerCase();
    const slug = String(community || '').toLowerCase();
    const id = String(postId || '').toLowerCase();
    const key = teamKey(owner, slug, teamId);
    const cached = getCachedTeamModeration(owner, slug, teamId, id);
    if (cached) return Promise.resolve(cached);

    if (!batches.has(key)) {
        batches.set(key, { postIds: new Set(), waiters: new Map(), timer: null });
    }
    const batch = batches.get(key);
    batch.postIds.add(id);
    return new Promise((resolve) => {
        if (!batch.waiters.has(id)) batch.waiters.set(id, []);
        batch.waiters.get(id).push(resolve);
        if (batch.timer === null) {
            batch.timer = setTimeout(() => {
                flush(key, owner, slug, teamId).catch(() => {});
            }, FLUSH_DELAY_MS);
        }
    });
}

/**
 * Drop cached verdicts so the next read reflects a curation write. Scoped to a
 * community when given one, since a hide in one team says nothing about another.
 */
export function clearTeamModeration(community = '') {
    const slug = String(community || '').trim().toLowerCase();
    if (!slug) {
        stateByTeam.clear();
        console.debug('[curation] team moderation cache cleared');
        return;
    }
    for (const key of [...stateByTeam.keys()]) {
        if (key.includes(`::${slug}::`)) stateByTeam.delete(key);
    }
    console.debug('[curation] team moderation cache cleared for community', { community: slug });
}

// A curation write anywhere invalidates these verdicts, and the component that
// made the write is not necessarily the one holding the stale entry.
if (typeof window !== 'undefined') {
    window.addEventListener('curationUpdated', (event) => {
        clearTeamModeration(String(event?.detail?.community || ''));
    });
}
