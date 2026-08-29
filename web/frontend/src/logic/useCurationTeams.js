import { useCallback, useEffect, useState } from 'react';
import Api from '../utils/api';
import { requireCommunitySlug, requireTeamId } from '../utils/curation';

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
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const refresh = useCallback(async () => {
        if (!enabled) {
            setTeams([]);
            setLoading(false);
            return [];
        }
        setLoading(true);
        setError('');
        try {
            const params = { include_deleted: includeDeleted };
            if (viewer) params.viewer = String(viewer).toLowerCase();
            const data = await Api.get(`communities/${encodeURIComponent(slug)}/teams`, params);
            if (!data || !Array.isArray(data.items)) throw new Error('Invalid curator teams response');
            const next = data.items.map(validateTeam);
            setTeams(next);
            console.debug('[curation] teams loaded', { community: slug, count: next.length });
            return next;
        } catch (err) {
            const message = String(err?.message || err);
            setError(message);
            console.error('[curation] teams failed', { community: slug, error: message });
            throw err;
        } finally {
            setLoading(false);
        }
    }, [enabled, includeDeleted, slug, viewer]);

    useEffect(() => {
        if (!enabled) return undefined;
        refresh().catch(() => {});
        const onUpdate = (event) => {
            const changed = String(event?.detail?.community || '').toLowerCase();
            if (!changed || changed === slug) refresh().catch(() => {});
        };
        window.addEventListener('curationUpdated', onUpdate);
        return () => window.removeEventListener('curationUpdated', onUpdate);
    }, [enabled, refresh, slug]);

    return { teams, loading, error, refresh };
}

export function useCurationTeam(community, teamId, viewer = '') {
    const slug = requireCommunitySlug(community);
    const id = requireTeamId(teamId);
    const [team, setTeam] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const refresh = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            const params = viewer ? { viewer: String(viewer).toLowerCase() } : undefined;
            const [data, invitationData] = await Promise.all([
                Api.get(`communities/${encodeURIComponent(slug)}/teams/${id}`, params),
                viewer
                    ? Api.get(`communities/${encodeURIComponent(slug)}/teams/${id}/invitations`, params)
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
            setTeam(combined);
            console.debug('[curation] team detail loaded', { community: slug, teamId: id });
            return combined;
        } catch (err) {
            const message = String(err?.message || err);
            setError(message);
            console.error('[curation] team detail failed', { community: slug, teamId: id, error: message });
            throw err;
        } finally {
            setLoading(false);
        }
    }, [id, slug, viewer]);

    useEffect(() => {
        refresh().catch(() => {});
        const onUpdate = (event) => {
            const changed = String(event?.detail?.community || '').toLowerCase();
            if (!changed || changed === slug) refresh().catch(() => {});
        };
        window.addEventListener('curationUpdated', onUpdate);
        return () => window.removeEventListener('curationUpdated', onUpdate);
    }, [refresh, slug]);

    return { team, loading, error, refresh };
}

export function useHiddenCurationUsers(community, teamId, { viewer = '', enabled = false } = {}) {
    const slug = enabled ? requireCommunitySlug(community) : '';
    const id = enabled ? requireTeamId(teamId) : 0;
    const viewerAddr = String(viewer || '').toLowerCase();
    const [users, setUsers] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const refresh = useCallback(async () => {
        if (!enabled || !slug || !id || !viewerAddr || viewerAddr === 'guest') {
            setUsers([]);
            setLoading(false);
            setError('');
            return [];
        }
        setLoading(true);
        setError('');
        try {
            const data = await Api.get(
                `communities/${encodeURIComponent(slug)}/teams/${id}/hidden-users`,
                { viewer: viewerAddr, _cb: Date.now() },
            );
            if (!data || !Array.isArray(data.items)) {
                throw new Error('Invalid hidden users response');
            }
            const next = data.items.map((item) => {
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
            setUsers(next);
            console.debug('[curation] hidden users loaded', { community: slug, teamId: id, count: next.length });
            return next;
        } catch (err) {
            const message = String(err?.message || err);
            setUsers([]);
            setError(message);
            console.error('[curation] hidden users failed', { community: slug, teamId: id, error: message });
            throw err;
        } finally {
            setLoading(false);
        }
    }, [enabled, id, slug, viewerAddr]);

    useEffect(() => {
        if (!enabled) {
            setUsers([]);
            setLoading(false);
            setError('');
            return undefined;
        }
        refresh().catch(() => {});
        const onUpdate = (event) => {
            const changed = String(event?.detail?.community || '').toLowerCase();
            if (!changed || changed === slug) refresh().catch(() => {});
        };
        window.addEventListener('curationUpdated', onUpdate);
        return () => window.removeEventListener('curationUpdated', onUpdate);
    }, [enabled, refresh, slug]);

    return { users, loading, error, refresh };
}
