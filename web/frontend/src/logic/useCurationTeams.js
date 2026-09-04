import { useCallback, useEffect, useRef, useState } from 'react';
import Api from '../utils/api';
import {
    HIDDEN_LIST_INITIAL,
    HIDDEN_LIST_MORE,
    requireCommunitySlug,
    requireTeamId,
} from '../utils/curation';
import { onSessionReset } from '../utils/sessionLifecycle';
import { CURATOR_READ_ACTION, signReadParams } from '../utils/signPlain';

/**
 * Roster and settings the viewer has already changed on chain, but which the
 * indexer has not projected yet. Module scope is load-bearing: the landed
 * transaction fires `curationUpdated`, every listener refetches within the
 * same tick, and that read still describes the team as it was before the
 * change. Component state would therefore be overwritten a moment after the
 * click, which is exactly the "nothing happened" this is meant to remove.
 * Each field deletes itself as soon as a server read agrees with it, so a
 * later change made by somebody else is never masked.
 */
const teamPatches = new Map();

onSessionReset(({ reason }) => {
    teamPatches.clear();
    console.debug('[curation] optimistic team patches cleared on session reset', { reason });
});

const PATCH_FIELDS = ['removeMember', 'addMember', 'removeInvitation', 'owner', 'subscriberOnly'];

function patchKey(community, teamId) {
    return `${requireCommunitySlug(community)}:${requireTeamId(teamId)}`;
}

function normalizeAddress(value) {
    return String(value || '').trim().toLowerCase();
}

function requirePatchAddress(value) {
    const address = normalizeAddress(value);
    if (!address) throw new Error('Curation team patch is missing an address');
    return address;
}

function addressOf(entry) {
    return normalizeAddress(entry?.address);
}

function emptyPatch() {
    return {
        removedMembers: new Set(),
        addedMembers: new Map(),
        removedInvitations: new Set(),
        owner: undefined,
        subscriberOnly: undefined,
    };
}

function patchIsEmpty(patch) {
    return patch.removedMembers.size === 0
        && patch.addedMembers.size === 0
        && patch.removedInvitations.size === 0
        && patch.owner === undefined
        && patch.subscriberOnly === undefined;
}

function requirePatchFields(change) {
    const fields = Object.keys(change || {});
    if (!fields.length) throw new Error('Empty curation team patch');
    for (const field of fields) {
        if (!PATCH_FIELDS.includes(field)) {
            throw new Error(`Unknown curation team patch field: ${field}`);
        }
    }
    return fields;
}

function announcePatch(key) {
    window.dispatchEvent(new CustomEvent('curationTeamOptimistic', { detail: { team: key } }));
}

/**
 * Show a roster or settings change immediately, before the indexer serves it.
 * Revert the identical `change` if the transaction turns out to have failed.
 */
export function patchCurationTeamOptimistically(community, teamId, change) {
    const fields = requirePatchFields(change);
    const key = patchKey(community, teamId);
    const patch = teamPatches.get(key) || emptyPatch();
    for (const field of fields) {
        const value = change[field];
        if (field === 'removeMember') {
            const address = requirePatchAddress(value);
            patch.addedMembers.delete(address);
            patch.removedMembers.add(address);
        } else if (field === 'addMember') {
            const address = requirePatchAddress(value?.address);
            patch.removedMembers.delete(address);
            patch.addedMembers.set(address, { ...value, address });
        } else if (field === 'removeInvitation') {
            patch.removedInvitations.add(requirePatchAddress(value));
        } else if (field === 'owner') {
            patch.owner = requirePatchAddress(value);
        } else if (typeof value !== 'boolean') {
            throw new Error('subscriberOnly patch must be a boolean');
        } else {
            patch.subscriberOnly = value;
        }
    }
    teamPatches.set(key, patch);
    announcePatch(key);
    console.debug('[curation] team patch applied', { team: key, fields });
}

export function revertCurationTeamPatch(community, teamId, change) {
    const fields = requirePatchFields(change);
    const key = patchKey(community, teamId);
    const patch = teamPatches.get(key);
    if (!patch) return;
    for (const field of fields) {
        const value = change[field];
        if (field === 'removeMember') patch.removedMembers.delete(requirePatchAddress(value));
        else if (field === 'addMember') patch.addedMembers.delete(requirePatchAddress(value?.address));
        else if (field === 'removeInvitation') patch.removedInvitations.delete(requirePatchAddress(value));
        else if (field === 'owner') patch.owner = undefined;
        else patch.subscriberOnly = undefined;
    }
    if (patchIsEmpty(patch)) teamPatches.delete(key);
    announcePatch(key);
    console.debug('[curation] team patch reverted', { team: key, fields });
}

/** Drop the parts of the patch a server read now reflects on its own. */
function reconcileTeamPatch(key, serverTeam) {
    const patch = teamPatches.get(key);
    if (!patch) return;
    const memberAddresses = new Set((serverTeam.members || []).map(addressOf));
    for (const address of [...patch.removedMembers]) {
        if (!memberAddresses.has(address)) patch.removedMembers.delete(address);
    }
    for (const address of [...patch.addedMembers.keys()]) {
        if (memberAddresses.has(address)) patch.addedMembers.delete(address);
    }
    const inviteAddresses = new Set((serverTeam.invitations || []).map(addressOf));
    for (const address of [...patch.removedInvitations]) {
        if (!inviteAddresses.has(address)) patch.removedInvitations.delete(address);
    }
    if (patch.owner !== undefined && normalizeAddress(serverTeam.owner) === patch.owner) {
        patch.owner = undefined;
    }
    if (patch.subscriberOnly !== undefined && serverTeam.subscriber_only === patch.subscriberOnly) {
        patch.subscriberOnly = undefined;
    }
    if (patchIsEmpty(patch)) {
        teamPatches.delete(key);
        console.debug('[curation] team patch caught up', { team: key });
    }
}

function projectCurationTeam(key, serverTeam) {
    const patch = teamPatches.get(key);
    if (!patch || !serverTeam) return serverTeam;
    let members = serverTeam.members || [];
    if (patch.removedMembers.size) {
        members = members.filter((member) => !patch.removedMembers.has(addressOf(member)));
    }
    if (patch.addedMembers.size) {
        const present = new Set(members.map(addressOf));
        const additions = [...patch.addedMembers.values()].filter((member) => !present.has(member.address));
        if (additions.length) members = [...members, ...additions];
    }
    let invitations = serverTeam.invitations || [];
    if (patch.removedInvitations.size) {
        invitations = invitations.filter((invite) => !patch.removedInvitations.has(addressOf(invite)));
    }
    return {
        ...serverTeam,
        members,
        invitations,
        owner: patch.owner === undefined ? serverTeam.owner : patch.owner,
        subscriber_only: patch.subscriberOnly === undefined
            ? serverTeam.subscriber_only
            : patch.subscriberOnly,
    };
}

async function curatorParams(viewer, params = {}) {
    const address = String(viewer || '').trim().toLowerCase();
    if (!address || address === 'guest') return params;
    return { ...params, viewer: address, ...await signReadParams(CURATOR_READ_ACTION, address) };
}

function validateTeam(team) {
    if (!team || typeof team !== 'object') throw new Error('Invalid curator team response');
    requireTeamId(team.team_id);
    if (!team.owner || !team.name || typeof team.description !== 'string') {
        throw new Error('Curator team is missing required fields');
    }
    if (typeof team.subscriber_count !== 'string') {
        throw new Error('Curator team is missing subscriber_count');
    }
    return team;
}

export function useCurationTeams(community, { includeDeleted = false, viewer = '', enabled = true } = {}) {
    const slug = enabled ? requireCommunitySlug(community) : '';
    const [teams, setTeams] = useState([]);
    const [loading, setLoading] = useState(enabled);
    const [error, setError] = useState('');
    const requestSeq = useRef(0);

    const refresh = useCallback(async ({ background = false } = {}) => {
        if (!enabled) {
            setTeams([]);
            setLoading(false);
            return [];
        }
        const seq = ++requestSeq.current;
        if (!background) {
            setLoading(true);
            setError('');
        }
        try {
            const params = await curatorParams(viewer, {
                include_deleted: includeDeleted,
                _cb: Date.now(),
            });
            const data = await Api.get(`communities/${encodeURIComponent(slug)}/teams`, params);
            if (!data || !Array.isArray(data.items)) throw new Error('Invalid curator teams response');
            const next = data.items.map(validateTeam);
            if (seq !== requestSeq.current) {
                console.debug('[curation] teams stale response dropped', {
                    community: slug,
                    seq,
                    current: requestSeq.current,
                });
                return null;
            }
            setTeams(next);
            console.debug('[curation] teams loaded', { community: slug, count: next.length, background });
            return next;
        } catch (err) {
            if (seq !== requestSeq.current) return null;
            const message = String(err?.message || err);
            setError(message);
            console.error('[curation] teams failed', { community: slug, error: message });
            throw err;
        } finally {
            if (seq === requestSeq.current && !background) {
                setLoading(false);
            }
        }
    }, [enabled, includeDeleted, slug, viewer]);

    useEffect(() => {
        if (!enabled) {
            setTeams([]);
            setLoading(false);
            setError('');
            return undefined;
        }
        requestSeq.current += 1;
        refresh().catch(() => { });
        const onUpdate = (event) => {
            const changed = String(event?.detail?.community || '').toLowerCase();
            if (!changed || changed === slug) {
                refresh({ background: true }).catch(() => { });
            }
        };
        window.addEventListener('curationUpdated', onUpdate);
        return () => {
            requestSeq.current += 1;
            window.removeEventListener('curationUpdated', onUpdate);
        };
    }, [enabled, refresh, slug]);

    return { teams, loading, error, refresh };
}

export function useCurationTeam(community, teamId, viewer = '') {
    const slug = requireCommunitySlug(community);
    const id = requireTeamId(teamId);
    const key = `${slug}:${id}`;
    const [team, setTeam] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    // Kept so an optimistic patch can be re-projected without another fetch.
    const serverTeamRef = useRef(null);

    const refresh = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const [data, invitationData] = await Promise.all([
                viewer
                    ? curatorParams(viewer).then((params) => (
                        Api.get(`communities/${encodeURIComponent(slug)}/teams/${id}`, params)
                    ))
                    : Api.get(`communities/${encodeURIComponent(slug)}/teams/${id}`),
                viewer
                    ? curatorParams(viewer).then((params) => (
                        Api.get(`communities/${encodeURIComponent(slug)}/teams/${id}/invitations`, params)
                    ))
                    : Promise.resolve({ items: [] }),
            ]);
            const next = validateTeam(data);
            if (Number(next.team_id) !== id) throw new Error('Curator team ID mismatch');
            if (!Array.isArray(next.members) || !invitationData || !Array.isArray(invitationData.items)) {
                throw new Error('Curator team detail is missing roster data');
            }
            const invitations = invitationData.items.map((invitation) => {
                if (typeof invitation.invitee !== 'string' || !Number.isInteger(invitation.status)) {
                    throw new Error('Invalid curator invitation response');
                }
                if (invitation.username != null && typeof invitation.username !== 'string') {
                    throw new Error('Invalid curator invitation username');
                }
                return {
                    ...invitation,
                    address: invitation.invitee,
                    username: invitation.username || null,
                };
            });
            const combined = { ...next, invitations };
            serverTeamRef.current = combined;
            reconcileTeamPatch(key, combined);
            const projected = projectCurationTeam(key, combined);
            setTeam(projected);
            console.debug('[curation] team detail loaded', { community: slug, teamId: id });
            return projected;
        } catch (err) {
            const message = String(err?.message || err);
            setError(message);
            console.error('[curation] team detail failed', { community: slug, teamId: id, error: message });
            throw err;
        } finally {
            setLoading(false);
        }
    }, [id, key, slug, viewer]);

    useEffect(() => {
        refresh().catch(() => { });
        const onUpdate = (event) => {
            const changed = String(event?.detail?.community || '').toLowerCase();
            if (!changed || changed === slug) refresh().catch(() => { });
        };
        // Re-project from the last read instead of refetching: the point of the
        // patch is that the server does not know about the change yet.
        const onPatch = (event) => {
            if (String(event?.detail?.team || '') !== key) return;
            if (!serverTeamRef.current) return;
            setTeam(projectCurationTeam(key, serverTeamRef.current));
        };
        window.addEventListener('curationUpdated', onUpdate);
        window.addEventListener('curationTeamOptimistic', onPatch);
        return () => {
            window.removeEventListener('curationUpdated', onUpdate);
            window.removeEventListener('curationTeamOptimistic', onPatch);
        };
    }, [key, refresh, slug]);

    return { team, loading, error, refresh };
}

function useHiddenCurationPage(kind, community, teamId, { viewer = '', enabled = false } = {}) {
    const slug = enabled ? requireCommunitySlug(community) : '';
    const id = enabled ? requireTeamId(teamId) : 0;
    const viewerAddr = String(viewer || '').toLowerCase();
    const pathSuffix = kind === 'posts' ? 'hidden-posts' : 'hidden-users';
    const [items, setItems] = useState([]);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(false);
    const [loadingMore, setLoadingMore] = useState(false);
    const [error, setError] = useState('');
    const optimisticallyRemovedRef = useRef(new Set());

    const itemKey = useCallback((item) => (
        kind === 'posts' ? String(item?.postId || '').toLowerCase() : String(item?.address || '').toLowerCase()
    ), [kind]);

    const fetchPage = useCallback(async ({ offset, limit, append }) => {
        if (!enabled || !slug || !id || !viewerAddr || viewerAddr === 'guest') {
            setItems([]);
            setHasMore(false);
            setLoading(false);
            setLoadingMore(false);
            setError('');
            return [];
        }
        if (append) setLoadingMore(true);
        else setLoading(true);
        setError('');
        try {
            const data = await Api.get(
                `communities/${encodeURIComponent(slug)}/teams/${id}/${pathSuffix}`,
                await curatorParams(viewerAddr, {
                    offset,
                    limit,
                    _cb: Date.now(),
                }),
            );
            if (!data || !Array.isArray(data.items) || typeof data.has_more !== 'boolean') {
                throw new Error(`Invalid ${pathSuffix} response`);
            }
            const next = data.items.map((item) => {
                if (kind === 'posts') {
                    if (typeof item?.post_id !== 'string' || !item.post_id.trim()) {
                        throw new Error('Hidden post is missing post_id');
                    }
                    if (item.title != null && typeof item.title !== 'string') {
                        throw new Error('Invalid hidden post title');
                    }
                    return {
                        postId: item.post_id.trim().toLowerCase(),
                        title: item.title?.trim() || null,
                    };
                }
                if (typeof item?.address !== 'string' || !item.address.trim()) {
                    throw new Error('Hidden user is missing address');
                }
                if (item.username != null && typeof item.username !== 'string') {
                    throw new Error('Invalid hidden user username');
                }
                return {
                    address: item.address.trim().toLowerCase(),
                    username: item.username || null,
                };
            });
            const visible = next.filter((item) => !optimisticallyRemovedRef.current.has(itemKey(item)));
            setItems((prev) => (append ? [...prev, ...visible] : visible));
            setHasMore(data.has_more);
            console.debug(`[curation] ${pathSuffix} loaded`, {
                community: slug,
                teamId: id,
                offset,
                limit,
                count: next.length,
                hasMore: data.has_more,
                append,
            });
            return next;
        } catch (err) {
            const message = String(err?.message || err);
            if (!append) setItems([]);
            setError(message);
            console.error(`[curation] ${pathSuffix} failed`, {
                community: slug,
                teamId: id,
                error: message,
            });
            throw err;
        } finally {
            if (append) setLoadingMore(false);
            else setLoading(false);
        }
    }, [enabled, id, itemKey, kind, pathSuffix, slug, viewerAddr]);

    const refresh = useCallback(async () => (
        fetchPage({ offset: 0, limit: HIDDEN_LIST_INITIAL, append: false })
    ), [fetchPage]);

    const loadMore = useCallback(async () => {
        if (!hasMore || loadingMore || loading) return [];
        return fetchPage({
            offset: items.length,
            limit: HIDDEN_LIST_MORE,
            append: true,
        });
    }, [fetchPage, hasMore, items.length, loading, loadingMore]);

    const removeOptimistically = useCallback((item) => {
        const key = itemKey(item);
        if (!key) throw new Error(`Cannot optimistically unban invalid ${kind === 'posts' ? 'post' : 'user'}`);
        optimisticallyRemovedRef.current.add(key);
        setItems((prev) => prev.filter((candidate) => itemKey(candidate) !== key));
        console.debug(`[curation] ${pathSuffix} optimistic remove`, {
            community: slug,
            teamId: id,
            target: key.slice(0, 12),
        });
    }, [id, itemKey, kind, pathSuffix, slug]);

    const restoreOptimistically = useCallback((item) => {
        const key = itemKey(item);
        if (!key) throw new Error(`Cannot restore invalid ${kind === 'posts' ? 'post' : 'user'}`);
        optimisticallyRemovedRef.current.delete(key);
        setItems((prev) => (
            prev.some((candidate) => itemKey(candidate) === key) ? prev : [item, ...prev]
        ));
        console.debug(`[curation] ${pathSuffix} optimistic restore`, {
            community: slug,
            teamId: id,
            target: key.slice(0, 12),
        });
    }, [id, itemKey, kind, pathSuffix, slug]);

    useEffect(() => {
        if (!enabled) {
            setItems([]);
            setHasMore(false);
            setLoading(false);
            setLoadingMore(false);
            setError('');
            return undefined;
        }
        refresh().catch(() => { });
        const onUpdate = (event) => {
            const changed = String(event?.detail?.community || '').toLowerCase();
            if (!changed || changed === slug) refresh().catch(() => { });
        };
        window.addEventListener('curationUpdated', onUpdate);
        return () => window.removeEventListener('curationUpdated', onUpdate);
    }, [enabled, refresh, slug]);

    return {
        items,
        hasMore,
        loading,
        loadingMore,
        error,
        refresh,
        loadMore,
        removeOptimistically,
        restoreOptimistically,
    };
}

export function useHiddenCurationUsers(community, teamId, options) {
    const state = useHiddenCurationPage('users', community, teamId, options);
    return {
        users: state.items,
        hasMore: state.hasMore,
        loading: state.loading,
        loadingMore: state.loadingMore,
        error: state.error,
        refresh: state.refresh,
        loadMore: state.loadMore,
        removeOptimistically: state.removeOptimistically,
        restoreOptimistically: state.restoreOptimistically,
    };
}

export function useHiddenCurationPosts(community, teamId, options) {
    const state = useHiddenCurationPage('posts', community, teamId, options);
    return {
        posts: state.items,
        hasMore: state.hasMore,
        loading: state.loading,
        loadingMore: state.loadingMore,
        error: state.error,
        refresh: state.refresh,
        loadMore: state.loadMore,
        removeOptimistically: state.removeOptimistically,
        restoreOptimistically: state.restoreOptimistically,
    };
}
