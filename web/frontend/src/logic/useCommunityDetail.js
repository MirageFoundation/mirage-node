import { useCallback, useEffect, useRef, useState } from 'react';
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
    const [loading, setLoading] = useState(enabled);
    const [error, setError] = useState('');
    // Drops out-of-order HTTP responses so a slow refresh after a rapid lens
    // switch cannot overwrite a newer preference the indexer already returned.
    const requestSeq = useRef(0);

    const refresh = useCallback(async ({ background = false } = {}) => {
        if (!enabled) {
            setDetail(null);
            setLoading(false);
            return null;
        }
        const seq = ++requestSeq.current;
        if (!background) {
            setLoading(true);
            setError('');
        }
        try {
            const params = viewer ? { viewer: String(viewer).toLowerCase() } : undefined;
            const data = validateDetail(await Api.get(`communities/${encodeURIComponent(slug)}`, params), slug);
            if (seq !== requestSeq.current) {
                console.debug('[community] detail stale response dropped', {
                    community: slug,
                    seq,
                    current: requestSeq.current,
                });
                return null;
            }
            setDetail(data);
            console.debug('[community] detail loaded', {
                community: slug,
                curated: data.curated,
                liveTeamCount: Number(data.live_team_count),
                storedMode: Number(data.stored_mode),
                effectiveTeamId: Number(data.effective_team_id || 0),
                background,
            });
            return data;
        } catch (err) {
            if (seq !== requestSeq.current) return null;
            const message = String(err?.message || err);
            setError(message);
            console.error('[community] detail failed', { community: slug, error: message });
            throw err;
        } finally {
            if (seq === requestSeq.current && !background) {
                setLoading(false);
            }
        }
    }, [enabled, slug, viewer]);

    useEffect(() => {
        if (!enabled) {
            setDetail(null);
            setLoading(false);
            setError('');
            return undefined;
        }
        let active = true;
        requestSeq.current += 1;
        refresh().catch(() => {
            if (!active) return;
        });
        const onUpdate = (event) => {
            const changed = String(event?.detail?.community || '').toLowerCase();
            if (!changed || changed === slug) {
                refresh({ background: true }).catch(() => { });
            }
        };
        window.addEventListener('curationUpdated', onUpdate);
        return () => {
            active = false;
            requestSeq.current += 1;
            window.removeEventListener('curationUpdated', onUpdate);
        };
    }, [enabled, refresh, slug]);

    return { detail, loading, error, refresh };
}

export default useCommunityDetail;
