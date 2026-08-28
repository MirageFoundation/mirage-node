import { useCallback, useEffect, useState } from 'react';
import Api from '../utils/api';
import { requireCommunitySlug } from '../utils/curation';

function validateDetail(data, slug) {
    if (!data || typeof data !== 'object' || data.community !== slug) {
        throw new Error('Invalid community detail response');
    }
    if (typeof data.curated !== 'boolean' || !Number.isInteger(Number(data.live_team_count))) {
        throw new Error('Community detail is missing curation state');
    }
    return data;
}

export function useCommunityDetail(community, viewer = '', enabled = true) {
    const slug = enabled ? requireCommunitySlug(community) : '';
    const [detail, setDetail] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const refresh = useCallback(async () => {
        if (!enabled) {
            setDetail(null);
            setLoading(false);
            return null;
        }
        setLoading(true);
        setError('');
        try {
            const params = viewer ? { viewer: String(viewer).toLowerCase() } : undefined;
            const data = validateDetail(await Api.get(`communities/${encodeURIComponent(slug)}`, params), slug);
            setDetail(data);
            console.debug('[community] detail loaded', {
                community: slug,
                curated: data.curated,
                liveTeamCount: Number(data.live_team_count),
            });
            return data;
        } catch (err) {
            const message = String(err?.message || err);
            setError(message);
            console.error('[community] detail failed', { community: slug, error: message });
            throw err;
        } finally {
            setLoading(false);
        }
    }, [enabled, slug, viewer]);

    useEffect(() => {
        if (!enabled) return undefined;
        let active = true;
        refresh().catch(() => {
            if (!active) return;
        });
        const onUpdate = (event) => {
            const changed = String(event?.detail?.community || '').toLowerCase();
            if (!changed || changed === slug) refresh().catch(() => {});
        };
        window.addEventListener('curationUpdated', onUpdate);
        return () => {
            active = false;
            window.removeEventListener('curationUpdated', onUpdate);
        };
    }, [enabled, refresh, slug]);

    return { detail, loading, error, refresh };
}

export default useCommunityDetail;
