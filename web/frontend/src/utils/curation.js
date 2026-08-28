import Api from './api';

export const CURATION_MODE = Object.freeze({
    LIVE_DEFAULT: 0,
    PINNED: 1,
    RAW: 2,
});

export const LENS = Object.freeze({
    EFFECTIVE: 'effective',
    DEFAULT: 'default',
    TEAM: 'team',
    RAW: 'raw',
});

const VALID_LENSES = new Set(Object.values(LENS));

export function requireCommunitySlug(value) {
    const slug = String(value || '').trim().toLowerCase();
    if (!slug) throw new Error('community is required');
    return slug;
}

export function requireTeamId(value) {
    const teamId = Number(value);
    if (!Number.isSafeInteger(teamId) || teamId <= 0) {
        throw new Error('team_id must be a positive integer');
    }
    return teamId;
}

export function normalizeLens(lens, teamId = null) {
    const requested = String(lens || LENS.EFFECTIVE).trim().toLowerCase();
    if (!VALID_LENSES.has(requested)) throw new Error(`invalid lens: ${requested}`);
    if (requested === LENS.TEAM) {
        return { lens: requested, teamId: requireTeamId(teamId) };
    }
    if (teamId !== null && teamId !== undefined && String(teamId) !== '') {
        throw new Error('team_id is only valid with the team lens');
    }
    return { lens: requested, teamId: null };
}

export function lensQuery(lens, teamId = null, scope = 'current') {
    if (scope !== 'current' && scope !== 'legacy') throw new Error(`invalid scope: ${scope}`);
    const normalized = normalizeLens(lens, teamId);
    const params = { lens: normalized.lens, scope };
    if (normalized.lens === LENS.TEAM) params.team_id = normalized.teamId;
    return params;
}

export function lensCacheKey({ viewer, community, scope = 'current', lens = LENS.EFFECTIVE, teamId = null }) {
    const normalized = normalizeLens(lens, teamId);
    return [
        String(viewer || 'guest').trim().toLowerCase(),
        String(community || 'all').trim().toLowerCase(),
        scope,
        normalized.lens,
        normalized.teamId || 0,
    ].map(encodeURIComponent).join(':');
}

export function curationPendingKey(messageType, community, teamId = 0, target = '') {
    const action = String(messageType || '').trim();
    if (!action) throw new Error('message type is required');
    const slug = String(community || '').trim().toLowerCase();
    const id = Number(teamId || 0);
    if (!Number.isSafeInteger(id) || id < 0) throw new Error('invalid team id');
    return `${action}:${slug}:${id}:${String(target || '').trim().toLowerCase()}`;
}

export function invalidateCurationReads(community = '') {
    const slug = String(community || '').trim().toLowerCase();
    Api.invalidate('communities');
    Api.invalidate('get_posts');
    Api.invalidate('get_comments');
    Api.invalidate('get_post');
    Api.invalidate('search');
    Api.invalidate('creator/earnings');
    try {
        window.__MIRAGE_FEED_MEM_CACHE__ = {};
        window.dispatchEvent(new CustomEvent('curationUpdated', { detail: { community: slug } }));
        window.dispatchEvent(new Event('mirageRefreshFeed'));
        console.debug('[lens] invalidated curation reads', { community: slug || null });
    } catch (_) { /* noop */ }
}
