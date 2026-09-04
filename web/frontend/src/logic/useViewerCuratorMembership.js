import { useCallback, useEffect, useState } from 'react';
import Api from '../utils/api';
import Storage from '../utils/Storage';
import { requireCommunitySlug } from '../utils/curation';
import { onSessionReset } from '../utils/sessionLifecycle';
import { CURATOR_READ_ACTION, signReadParams } from '../utils/signPlain';

/** community → { teamId, teamName } | null */
const membershipCache = new Map();
const inflight = new Map();
const curatorListInflight = new Map();
/** viewer → { loaded, byCommunity: Map(slug → { teamId, teamName }) } */
const curatorListByViewer = new Map();

function cacheKey(viewer, community) {
    return `${String(viewer || '').toLowerCase()}::${String(community || '').toLowerCase()}`;
}

function rememberCuratorList(viewer, memberships) {
    const owner = String(viewer || '').toLowerCase();
    const byCommunity = new Map();
    for (const item of memberships || []) {
        const slug = String(item?.community || '').trim().toLowerCase();
        const teamId = Number(item?.team_id);
        if (!slug || !Number.isSafeInteger(teamId) || teamId <= 0) continue;
        const teamName = typeof item?.name === 'string' ? item.name.trim() : '';
        byCommunity.set(slug, { teamId, teamName });
        membershipCache.set(cacheKey(owner, slug), {
            teamId,
            teamName,
            memberCount: 1,
            isLeader: false,
        });
    }
    curatorListByViewer.set(owner, { loaded: true, byCommunity });
    console.debug('[curation] curator list cached', {
        viewer: owner.slice(0, 12),
        count: byCommunity.size,
    });
}

function membershipFromCuratorList(viewer, community) {
    const owner = String(viewer || '').toLowerCase();
    const slug = String(community || '').trim().toLowerCase();
    const list = curatorListByViewer.get(owner);
    if (!list?.loaded) return undefined;
    const hit = list.byCommunity.get(slug);
    if (!hit) return null;
    return {
        teamId: hit.teamId,
        teamName: hit.teamName,
        memberCount: 1,
        isLeader: false,
    };
}

function clearMembershipCache(community = '') {
    const slug = String(community || '').trim().toLowerCase();
    if (!slug) {
        membershipCache.clear();
        inflight.clear();
        curatorListByViewer.clear();
        curatorListInflight.clear();
        console.debug('[curation] membership cache cleared');
        return;
    }
    for (const key of [...membershipCache.keys()]) {
        if (key.endsWith(`::${slug}`)) membershipCache.delete(key);
    }
    for (const key of [...inflight.keys()]) {
        if (key.endsWith(`::${slug}`)) inflight.delete(key);
    }
    for (const [viewer, list] of curatorListByViewer) {
        list.byCommunity.delete(slug);
        membershipCache.delete(cacheKey(viewer, slug));
    }
    console.debug('[curation] membership cache cleared for community', { community: slug });
}

// The per-component listeners below only run while something is rendering that
// community, and the page that makes you a curator is not one of them: creating
// a team happens on the teams route, which never mounts this hook. Clearing from
// module scope means the cache cannot outlive the change that invalidated it and
// hand a stale "not a curator" to the feed you navigate to next.
if (typeof window !== 'undefined') {
    window.addEventListener('curationUpdated', (event) => {
        clearMembershipCache(String(event?.detail?.community || ''));
    });
}

/**
 * Memberships the viewer just gained by accepting an invite or gave up by
 * leaving, before the indexer projects either. Same reason these live at module
 * scope as the roster patches in `useCurationTeams`: the landed transaction
 * fires `curationUpdated`, every listener refetches immediately, and those
 * reads still describe the old membership — so the sidebar highlight and the
 * curate menu would come straight back. An entry deletes itself once a server
 * read agrees with it.
 *
 * `viewer::community` → { teamId, teamName } | null (null = no longer a curator)
 */
const membershipOverrides = new Map();

onSessionReset(({ reason }) => {
    membershipOverrides.clear();
    console.debug('[curation] optimistic membership cleared on session reset', { reason });
});

function announceMembershipOverride(viewer, community) {
    window.dispatchEvent(new CustomEvent('curatorMembershipOptimistic', {
        detail: { viewer, community },
    }));
}

/** Pass `null` for "left the team", or `{ teamId, teamName }` for "joined it". */
export function setOptimisticCuratorMembership(viewer, community, membership) {
    const owner = String(viewer || '').trim().toLowerCase();
    const slug = requireCommunitySlug(community);
    if (!owner || owner === 'guest') throw new Error('Optimistic membership needs a viewer');
    if (membership !== null) {
        const teamId = Number(membership?.teamId);
        if (!Number.isSafeInteger(teamId) || teamId <= 0) {
            throw new Error('Invalid optimistic curator membership team id');
        }
    }
    const key = cacheKey(owner, slug);
    membershipOverrides.set(key, membership === null ? null : {
        teamId: Number(membership.teamId),
        teamName: typeof membership.teamName === 'string' ? membership.teamName : '',
        memberCount: 1,
        isLeader: false,
    });
    membershipCache.delete(key);
    inflight.delete(key);
    announceMembershipOverride(owner, slug);
    console.debug('[curation] optimistic membership', {
        community: slug,
        teamId: membership === null ? null : Number(membership.teamId),
    });
}

export function clearOptimisticCuratorMembership(viewer, community) {
    const owner = String(viewer || '').trim().toLowerCase();
    const slug = requireCommunitySlug(community);
    const key = cacheKey(owner, slug);
    if (!membershipOverrides.delete(key)) return;
    membershipCache.delete(key);
    inflight.delete(key);
    announceMembershipOverride(owner, slug);
    console.debug('[curation] optimistic membership reverted', { community: slug });
}

/** Server truth wins once it agrees; until then the override does. */
function reconcileMembership(viewer, community, serverValue) {
    const key = cacheKey(viewer, community);
    if (!membershipOverrides.has(key)) return serverValue;
    const override = membershipOverrides.get(key);
    const satisfied = override === null
        ? serverValue == null
        : serverValue != null && serverValue.teamId === override.teamId;
    if (satisfied) {
        membershipOverrides.delete(key);
        console.debug('[curation] optimistic membership caught up', { community });
        return serverValue;
    }
    return override;
}

/** Synchronous best answer for a first render, override included. */
function peekMembership(viewer, community) {
    const key = cacheKey(viewer, community);
    if (membershipOverrides.has(key)) return membershipOverrides.get(key);
    return membershipCache.get(key) ?? null;
}

function projectCuratorCommunities(viewer, list) {
    const owner = String(viewer || '').toLowerCase();
    const prefix = `${owner}::`;
    const next = new Set(list);
    for (const [key, override] of membershipOverrides) {
        if (!key.startsWith(prefix)) continue;
        const slug = key.slice(prefix.length);
        if (override === null) next.delete(slug);
        else next.add(slug);
    }
    return [...next];
}

export async function fetchViewerCuratorMembership(community, viewer, { fresh = false } = {}) {
    const slug = requireCommunitySlug(community);
    const owner = String(viewer || '').trim().toLowerCase();
    if (!owner || owner === 'guest') return null;
    const key = cacheKey(owner, slug);
    if (fresh) {
        membershipCache.delete(key);
        inflight.delete(key);
        const list = curatorListByViewer.get(owner);
        if (list?.loaded) list.byCommunity.delete(slug);
    }
    // Every exit reconciles: the cache and the curator list both hold server
    // truth, which is precisely what an unsettled optimistic change contradicts.
    if (membershipCache.has(key)) return reconcileMembership(owner, slug, membershipCache.get(key));
    if (!fresh) {
        const fromList = membershipFromCuratorList(owner, slug);
        if (fromList !== undefined) {
            membershipCache.set(key, fromList);
            return reconcileMembership(owner, slug, fromList);
        }
    }
    if (inflight.has(key)) return reconcileMembership(owner, slug, await inflight.get(key));

    const pending = (async () => {
        const proof = await signReadParams(CURATOR_READ_ACTION, owner);
        const params = fresh
            ? { viewer: owner, _cb: Date.now(), ...proof }
            : { viewer: owner, ...proof };
        const data = await Api.get(`communities/${encodeURIComponent(slug)}/teams`, params);
        if (!data || !Array.isArray(data.items)) {
            throw new Error('Invalid curator teams response');
        }
        if (!Array.isArray(data.viewer_team_ids)) {
            throw new Error('Curator teams response missing viewer_team_ids');
        }
        const teamIdRaw = data.viewer_team_ids[0];
        if (teamIdRaw == null) {
            membershipCache.set(key, null);
            return null;
        }
        const teamId = Number(teamIdRaw);
        if (!Number.isSafeInteger(teamId) || teamId <= 0) {
            throw new Error('Invalid viewer_team_ids entry');
        }
        const team = data.items.find((item) => Number(item.team_id) === teamId);
        if (!team) throw new Error(`Viewer curator team ${teamId} is missing`);
        const memberCount = Number(team.member_count);
        if (!Number.isSafeInteger(memberCount) || memberCount <= 0) {
            throw new Error(`Invalid curator team member_count: ${team.member_count}`);
        }
        if (typeof team.name !== 'string' || !team.name.trim()) {
            throw new Error(`Invalid curator team name for team ${teamId}`);
        }
        if (typeof team.owner !== 'string' || !team.owner.trim()) {
            throw new Error(`Invalid curator team owner for team ${teamId}`);
        }
        const isLeader = team.owner.toLowerCase() === owner;
        if (memberCount === 1 && !isLeader) {
            throw new Error(`Curator team ${teamId} has one member but a different owner`);
        }
        const result = {
            teamId,
            teamName: team.name,
            memberCount,
            isLeader,
        };
        membershipCache.set(key, result);
        console.debug('[curation] viewer membership', {
            community: slug,
            teamId,
            teamName: result.teamName,
            memberCount,
            isLeader: result.isLeader,
        });
        return result;
    })();

    inflight.set(key, pending);
    try {
        return reconcileMembership(owner, slug, await pending);
    } finally {
        inflight.delete(key);
    }
}

/**
 * Resolve whether the logged-in viewer is a curator for `community`.
 * One membership per community — returns that team's id/name, or null.
 */
/**
 * Communities where the logged-in viewer is an accepted curator on a live team.
 * Used by the sidebar to pin/highlight those rows.
 */
export function useViewerCuratorCommunities() {
    const viewer = String(Storage.load('publicKey', '') || '').toLowerCase();
    const enabled = Boolean(viewer && viewer !== 'guest');
    const [communities, setCommunities] = useState([]);
    const [loading, setLoading] = useState(enabled);

    const refresh = useCallback(async () => {
        if (!enabled) {
            setCommunities([]);
            setLoading(false);
            return [];
        }
        setLoading(true);
        try {
            if (curatorListInflight.has(viewer)) {
                const reused = await curatorListInflight.get(viewer);
                setCommunities(reused);
                return reused;
            }
            const pending = (async () => {
                const proof = await signReadParams(CURATOR_READ_ACTION, viewer);
                const data = await Api.get(
                    `curators/${encodeURIComponent(viewer)}/communities`,
                    { viewer, ...proof },
                );
                if (!data || !Array.isArray(data.communities)) {
                    throw new Error('Invalid curator communities response');
                }
                if (Array.isArray(data.memberships)) {
                    rememberCuratorList(viewer, data.memberships);
                }
                const next = projectCuratorCommunities(viewer, data.communities
                    .map((slug) => String(slug || '').trim().toLowerCase())
                    .filter(Boolean));
                console.debug('[curation] viewer curator communities', {
                    viewer: viewer.slice(0, 12),
                    count: next.length,
                });
                return next;
            })();
            curatorListInflight.set(viewer, pending);
            try {
                const next = await pending;
                setCommunities(next);
                return next;
            } finally {
                curatorListInflight.delete(viewer);
            }
        } catch (err) {
            console.error('[curation] curator communities failed', {
                viewer: viewer.slice(0, 12),
                error: String(err?.message || err),
            });
            setCommunities([]);
            return [];
        } finally {
            setLoading(false);
        }
    }, [enabled, viewer]);

    useEffect(() => {
        if (!enabled) {
            setCommunities([]);
            setLoading(false);
            return undefined;
        }
        let cancelled = false;
        refresh().catch(() => {
            if (!cancelled) setCommunities([]);
        });
        const onUpdate = () => {
            refresh().catch(() => { });
        };
        // Re-project what is already on screen so the sidebar highlight moves on
        // click, then reconcile in the background. Refreshing covers the revert
        // case too, where the override is gone and only the server knows the truth.
        const onOptimistic = () => {
            if (!cancelled) setCommunities((prev) => projectCuratorCommunities(viewer, prev));
            refresh().catch(() => { });
        };
        window.addEventListener('curationUpdated', onUpdate);
        window.addEventListener('curatorMembershipOptimistic', onOptimistic);
        return () => {
            cancelled = true;
            window.removeEventListener('curationUpdated', onUpdate);
            window.removeEventListener('curatorMembershipOptimistic', onOptimistic);
        };
    }, [enabled, refresh, viewer]);

    return { communities, loading, refresh };
}

export function useViewerCuratorMembership(community, { enabled: enabledOption = true } = {}) {
    const slug = String(community || '').trim().toLowerCase();
    const viewer = String(Storage.load('publicKey', '') || '').toLowerCase();
    const enabled = Boolean(enabledOption && slug && viewer && viewer !== 'guest');
    const [membership, setMembership] = useState(() => (enabled ? peekMembership(viewer, slug) : null));
    const [loading, setLoading] = useState(
        enabled
        && !membershipCache.has(cacheKey(viewer, slug))
        && !membershipOverrides.has(cacheKey(viewer, slug)),
    );
    const [error, setError] = useState('');

    const refresh = useCallback(async () => {
        if (!enabled) {
            setMembership(null);
            setLoading(false);
            setError('');
            return null;
        }
        setLoading(true);
        setError('');
        try {
            clearMembershipCache(slug);
            const next = await fetchViewerCuratorMembership(slug, viewer);
            setMembership(next);
            return next;
        } catch (err) {
            const message = String(err?.message || err);
            setError(message);
            setMembership(null);
            console.error('[curation] membership failed', { community: slug, error: message });
            throw err;
        } finally {
            setLoading(false);
        }
    }, [enabled, slug, viewer]);

    useEffect(() => {
        if (!enabled) {
            setMembership(null);
            setLoading(false);
            setError('');
            return undefined;
        }
        let cancelled = false;
        setLoading(
            !membershipCache.has(cacheKey(viewer, slug))
            && !membershipOverrides.has(cacheKey(viewer, slug)),
        );
        fetchViewerCuratorMembership(slug, viewer)
            .then((next) => {
                if (!cancelled) {
                    setMembership(next);
                    setError('');
                }
            })
            .catch((err) => {
                if (!cancelled) {
                    setMembership(null);
                    setError(String(err?.message || err));
                }
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });

        const onUpdate = (event) => {
            const changed = String(event?.detail?.community || '').toLowerCase();
            if (changed && changed !== slug) return;
            clearMembershipCache(slug);
            fetchViewerCuratorMembership(slug, viewer)
                .then((next) => {
                    if (!cancelled) setMembership(next);
                })
                .catch(() => {
                    if (!cancelled) setMembership(null);
                });
        };
        // Take the override straight to state; a fetch would only tell us what
        // the indexer still believes. When it was reverted instead, there is no
        // override left and the fresh read is the answer.
        const onOptimistic = (event) => {
            const changed = String(event?.detail?.community || '').toLowerCase();
            if (changed && changed !== slug) return;
            const override = membershipOverrides.get(cacheKey(viewer, slug));
            if (override !== undefined) {
                if (!cancelled) setMembership(override);
                return;
            }
            fetchViewerCuratorMembership(slug, viewer, { fresh: true })
                .then((next) => {
                    if (!cancelled) setMembership(next);
                })
                .catch(() => {
                    if (!cancelled) setMembership(null);
                });
        };
        window.addEventListener('curationUpdated', onUpdate);
        window.addEventListener('curatorMembershipOptimistic', onOptimistic);
        return () => {
            cancelled = true;
            window.removeEventListener('curationUpdated', onUpdate);
            window.removeEventListener('curatorMembershipOptimistic', onOptimistic);
        };
    }, [enabled, slug, viewer]);

    return {
        teamId: membership?.teamId ?? null,
        teamName: membership?.teamName ?? '',
        loading,
        error,
        refresh,
        isCurator: membership != null,
    };
}

const inviteListInflight = new Map();

/**
 * Invitations the viewer has answered, kept at module scope because component
 * state cannot outlive a remount. Hiding the card is otherwise undone twice
 * over: the landed response fires `curationUpdated`, which refetches while the
 * indexer still lists the row, and any remount refetches from scratch. Both
 * would pop an answered invite back into the feed. Cleared only if the
 * response failed, which is when the invite really is pending again.
 */
const answeredInvites = new Set();

onSessionReset(({ reason }) => {
    answeredInvites.clear();
    console.debug('[curation] answered invites cleared on session reset', { reason });
});

function answeredKey(viewer, community, teamId) {
    return `${String(viewer || '').toLowerCase()}::${String(community || '').toLowerCase()}:${Number(teamId)}`;
}

/**
 * Answering an invite from the team page has to silence the home-feed hero too,
 * and that hero is rendered by a hook this page never mounts.
 */
export function markCuratorInviteAnswered(viewer, community, teamId) {
    answeredInvites.add(answeredKey(viewer, community, teamId));
    console.debug('[curation] invite answered', { community, teamId: Number(teamId) });
}

export function unmarkCuratorInviteAnswered(viewer, community, teamId) {
    answeredInvites.delete(answeredKey(viewer, community, teamId));
}

function withoutAnswered(viewer, list) {
    return list.filter((invite) => !answeredInvites.has(answeredKey(viewer, invite.community, invite.teamId)));
}

function normalizePendingInvite(item) {
    const community = String(item?.community || '').trim().toLowerCase();
    const teamId = Number(item?.team_id);
    const name = typeof item?.name === 'string' ? item.name.trim() : '';
    const inviter = String(item?.inviter || '').trim().toLowerCase();
    const createdHeight = Number(item?.created_height);
    if (!community || !Number.isSafeInteger(teamId) || teamId <= 0) {
        throw new Error('Invalid pending curator invitation');
    }
    if (!name) throw new Error('Pending curator invitation is missing team name');
    if (!inviter) throw new Error('Pending curator invitation is missing inviter');
    if (!Number.isSafeInteger(createdHeight) || createdHeight < 0) {
        throw new Error('Pending curator invitation is missing created_height');
    }
    const inviterUsername = item?.inviter_username;
    if (inviterUsername != null && typeof inviterUsername !== 'string') {
        throw new Error('Invalid inviter username');
    }
    return {
        community,
        teamId,
        name,
        inviter,
        inviterUsername: inviterUsername?.trim() || null,
        createdHeight,
    };
}

/**
 * Pending curator-team invitations for the logged-in viewer.
 * Powers the home-feed invite hero.
 */
export function useViewerPendingCuratorInvites() {
    const viewer = String(Storage.load('publicKey', '') || '').toLowerCase();
    const enabled = Boolean(viewer && viewer !== 'guest');
    const [invites, setInvites] = useState([]);
    const [loading, setLoading] = useState(enabled);

    const refresh = useCallback(async () => {
        if (!enabled) {
            setInvites([]);
            setLoading(false);
            return [];
        }
        setLoading(true);
        try {
            if (inviteListInflight.has(viewer)) {
                const reused = withoutAnswered(viewer, await inviteListInflight.get(viewer));
                setInvites(reused);
                return reused;
            }
            const pending = (async () => {
                const proof = await signReadParams(CURATOR_READ_ACTION, viewer);
                const data = await Api.get(
                    `curators/${encodeURIComponent(viewer)}/invitations`,
                    { viewer, ...proof },
                );
                if (!data || !Array.isArray(data.items)) {
                    throw new Error('Invalid curator invitations response');
                }
                const next = data.items.map(normalizePendingInvite);
                console.debug('[curation] viewer pending invites', {
                    viewer: viewer.slice(0, 12),
                    count: next.length,
                });
                return next;
            })();
            inviteListInflight.set(viewer, pending);
            try {
                const next = withoutAnswered(viewer, await pending);
                setInvites(next);
                return next;
            } finally {
                inviteListInflight.delete(viewer);
            }
        } catch (err) {
            console.error('[curation] pending invites failed', {
                viewer: viewer.slice(0, 12),
                error: String(err?.message || err),
            });
            setInvites([]);
            return [];
        } finally {
            setLoading(false);
        }
    }, [enabled, viewer]);

    useEffect(() => {
        if (!enabled) {
            setInvites([]);
            setLoading(false);
            return undefined;
        }
        let cancelled = false;
        refresh().catch(() => {
            if (!cancelled) setInvites([]);
        });
        const onUpdate = () => {
            refresh().catch(() => { });
        };
        window.addEventListener('curationUpdated', onUpdate);
        return () => {
            cancelled = true;
            window.removeEventListener('curationUpdated', onUpdate);
        };
    }, [enabled, refresh]);

    const dismiss = useCallback((community, teamId) => {
        const slug = String(community || '').toLowerCase();
        const id = Number(teamId);
        markCuratorInviteAnswered(viewer, slug, id);
        setInvites((prev) => prev.filter((invite) => !(
            invite.community === slug && invite.teamId === id
        )));
    }, [viewer]);

    const restore = useCallback((invite) => {
        unmarkCuratorInviteAnswered(viewer, invite.community, invite.teamId);
        setInvites((prev) => {
            if (prev.some((item) => item.community === invite.community && item.teamId === invite.teamId)) {
                return prev;
            }
            return [invite, ...prev];
        });
    }, [viewer]);

    return { invites, loading, refresh, dismiss, restore };
}

export default useViewerCuratorMembership;
