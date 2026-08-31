import { useCallback, useEffect, useState } from 'react';
import Api from '../utils/api';
import Storage from '../utils/Storage';
import { requireCommunitySlug } from '../utils/curation';

/** community → { teamId, teamName } | null */
const membershipCache = new Map();
const inflight = new Map();

function cacheKey(viewer, community) {
    return `${String(viewer || '').toLowerCase()}::${String(community || '').toLowerCase()}`;
}

function clearMembershipCache(community = '') {
    const slug = String(community || '').trim().toLowerCase();
    if (!slug) {
        membershipCache.clear();
        inflight.clear();
        console.debug('[curation] membership cache cleared');
        return;
    }
    for (const key of [...membershipCache.keys()]) {
        if (key.endsWith(`::${slug}`)) membershipCache.delete(key);
    }
    for (const key of [...inflight.keys()]) {
        if (key.endsWith(`::${slug}`)) inflight.delete(key);
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

export async function fetchViewerCuratorMembership(community, viewer, { fresh = false } = {}) {
    const slug = requireCommunitySlug(community);
    const owner = String(viewer || '').trim().toLowerCase();
    if (!owner || owner === 'guest') return null;
    const key = cacheKey(owner, slug);
    if (fresh) {
        membershipCache.delete(key);
        inflight.delete(key);
    }
    if (membershipCache.has(key)) return membershipCache.get(key);
    if (inflight.has(key)) return inflight.get(key);

    const pending = (async () => {
        const params = fresh ? { viewer: owner, _cb: Date.now() } : { viewer: owner };
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
        return await pending;
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
            const data = await Api.get(
                `curators/${encodeURIComponent(viewer)}/communities`,
                { _cb: Date.now() },
            );
            if (!data || !Array.isArray(data.communities)) {
                throw new Error('Invalid curator communities response');
            }
            const next = data.communities
                .map((slug) => String(slug || '').trim().toLowerCase())
                .filter(Boolean);
            setCommunities(next);
            console.debug('[curation] viewer curator communities', {
                viewer: viewer.slice(0, 12),
                count: next.length,
            });
            return next;
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
            refresh().catch(() => {});
        };
        window.addEventListener('curationUpdated', onUpdate);
        return () => {
            cancelled = true;
            window.removeEventListener('curationUpdated', onUpdate);
        };
    }, [enabled, refresh]);

    return { communities, loading, refresh };
}

export function useViewerCuratorMembership(community) {
    const slug = String(community || '').trim().toLowerCase();
    const viewer = String(Storage.load('publicKey', '') || '').toLowerCase();
    const enabled = Boolean(slug && viewer && viewer !== 'guest');
    const [membership, setMembership] = useState(() => {
        if (!enabled) return null;
        return membershipCache.get(cacheKey(viewer, slug)) ?? null;
    });
    const [loading, setLoading] = useState(enabled && !membershipCache.has(cacheKey(viewer, slug)));
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
        setLoading(!membershipCache.has(cacheKey(viewer, slug)));
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
        window.addEventListener('curationUpdated', onUpdate);
        return () => {
            cancelled = true;
            window.removeEventListener('curationUpdated', onUpdate);
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

export default useViewerCuratorMembership;
