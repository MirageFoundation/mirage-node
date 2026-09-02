import { useCallback, useEffect, useRef, useState } from 'react';
import Api from '../utils/api';
import {
    HIDDEN_LIST_INITIAL,
    HIDDEN_LIST_MORE,
    requireCommunitySlug,
    requireTeamId,
} from '../utils/curation';
import { CURATOR_READ_ACTION, signReadParams } from '../utils/signPlain';

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
    const [team, setTeam] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

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
        refresh().catch(() => { });
        const onUpdate = (event) => {
            const changed = String(event?.detail?.community || '').toLowerCase();
            if (!changed || changed === slug) refresh().catch(() => { });
        };
        window.addEventListener('curationUpdated', onUpdate);
        return () => window.removeEventListener('curationUpdated', onUpdate);
    }, [refresh, slug]);

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
