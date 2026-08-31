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

/** Match chain DefaultParams MaxCurationTeamNameLength / DescriptionLength. */
export const MAX_CURATION_TEAM_NAME_LENGTH = 30;
export const MAX_CURATION_TEAM_DESCRIPTION_LENGTH = 800;
export const CURATION_TEAM_DESCRIPTION_EXAMPLE = `This community is dedicated to all things sailboats and sailing. Whether you're a seasoned sailor, a boat enthusiast, or a curious newbie, this place welcomes you.

If you post anything unrelated to sailboats, you might get hidden from our curation team.`;

/** Team-page hidden lists: first page 10, then batches of 50. */
export const HIDDEN_LIST_INITIAL = 10;
export const HIDDEN_LIST_MORE = 50;

/** Unicode code-point length — matches Go utf8.RuneCountInString. */
export function runeLength(value) {
    return [...String(value ?? '')].length;
}

export function sliceRunes(value, max) {
    const limit = Number(max);
    if (!Number.isSafeInteger(limit) || limit < 0) {
        throw new Error(`invalid rune slice max: ${max}`);
    }
    return [...String(value ?? '')].slice(0, limit).join('');
}

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

/** Format a subscriber count as `1 sub` or `N subs`. */
export function formatSubscriberCount(count) {
    const n = Number(count);
    if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
        throw new Error(`invalid subscriber count: ${count}`);
    }
    return n === 1 ? '1 sub' : `${n} subs`;
}

/** Live team with the most subscribers (ties → lowest team_id). */
export function teamIdWithMostSubscribers(teams) {
    if (!Array.isArray(teams) || teams.length === 0) return null;
    let bestId = null;
    let bestCount = -1;
    for (const team of teams) {
        if (team?.deleted) continue;
        const id = Number(team.team_id);
        const count = Number(team.subscriber_count);
        if (!Number.isSafeInteger(id) || id <= 0) {
            throw new Error(`invalid team_id: ${team.team_id}`);
        }
        if (!Number.isFinite(count) || count < 0) {
            throw new Error(`invalid subscriber_count: ${team.subscriber_count}`);
        }
        if (count > bestCount || (count === bestCount && (bestId == null || id < bestId))) {
            bestCount = count;
            bestId = id;
        }
    }
    return bestId;
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

/** Team id the current view is actually applying, or null when uncensored/raw. */
export function viewingTeamId(post) {
    const id = Number(post?.lens?.effective_team_id);
    if (!Number.isSafeInteger(id) || id <= 0) return null;
    return id;
}

/** Closed-label hint from a stamped post.lens before the picker has fetched teams. */
export function lensHintLabel(hintLens) {
    if (!hintLens || typeof hintLens !== 'object') return 'Curation';
    const mode = Number(hintLens.effective_mode);
    if (mode === CURATION_MODE.RAW || !hintLens.effective_team_id) return 'Uncensored';
    if (mode === CURATION_MODE.LIVE_DEFAULT) return 'Default';
    if (mode === CURATION_MODE.PINNED) return 'Curation';
    return 'Curation';
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

/**
 * Poll the community teams list until a deleted team is gone from it.
 * The sidebar's curator highlight and the lens picker refresh on
 * invalidateCurationReads, which is only worth firing once the indexer has
 * actually dropped the team — fire it earlier and the refresh re-reads the
 * team that was just deleted, leaving the row highlighted until a reload.
 */
export async function waitForCurationTeamGone(community, teamId, options = {}) {
    const slug = requireCommunitySlug(community);
    const id = requireTeamId(teamId);

    const {
        viewer = '',
        interval = 1500,
        maxAttempts = 10,
        timeoutMs = 5000,
        sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    } = options;

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        try {
            const params = { include_deleted: false, _cb: Date.now() };
            if (viewer) params.viewer = String(viewer).trim().toLowerCase();
            const data = await Api.get(
                `communities/${encodeURIComponent(slug)}/teams`,
                params,
                { timeoutMs },
            );
            const items = Array.isArray(data?.items) ? data.items : [];
            if (!items.some((team) => Number(team?.team_id) === id && !team?.deleted)) {
                console.debug('[curation] team deletion indexed', { community: slug, teamId: id, attempt });
                return true;
            }
            console.debug('[curation] team deletion not indexed yet', { community: slug, teamId: id, attempt });
        } catch (err) {
            console.warn('[curation] team deletion poll failed', {
                community: slug,
                teamId: id,
                attempt,
                error: String(err?.message || err),
            });
        }
        if (attempt < maxAttempts) await sleep(interval);
    }
    return false;
}

/**
 * Poll one team until the API serves the profile that was just saved.
 * Used after set_curation_team_profile: a read that beats the indexer still
 * carries the old name and description, and reseeding the form from it puts the
 * previous text back under the user seconds after they saved.
 */
export async function waitForCurationTeamProfile(community, teamId, name, description, options = {}) {
    const slug = requireCommunitySlug(community);
    const id = requireTeamId(teamId);
    const wantName = String(name ?? '');
    const wantDescription = String(description ?? '');

    const {
        viewer = '',
        interval = 1500,
        maxAttempts = 10,
        timeoutMs = 5000,
        sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    } = options;

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        try {
            const params = { _cb: Date.now() };
            if (viewer) params.viewer = String(viewer).trim().toLowerCase();
            const data = await Api.get(
                `communities/${encodeURIComponent(slug)}/teams/${id}`,
                params,
                { timeoutMs },
            );
            if (String(data?.name ?? '') === wantName && String(data?.description ?? '') === wantDescription) {
                console.debug('[curation] team profile visible', { community: slug, teamId: id, attempt });
                return data;
            }
            console.debug('[curation] team profile not indexed yet', { community: slug, teamId: id, attempt });
        } catch (err) {
            console.warn('[curation] team profile poll failed', {
                community: slug,
                teamId: id,
                attempt,
                error: String(err?.message || err),
            });
        }
        if (attempt < maxAttempts) await sleep(interval);
    }
    return null;
}

/**
 * Poll the community teams list until the viewer's team is visible.
 * Used after create_curation_team so the UI does not navigate to an empty list
 * while the indexer is still catching up.
 */
export async function waitForOwnCurationTeam(community, owner, name, options = {}) {
    const slug = requireCommunitySlug(community);
    const ownerLower = String(owner || '').trim().toLowerCase();
    const nameLower = String(name || '').trim().toLowerCase();
    if (!ownerLower) throw new Error('owner is required');
    if (!nameLower) throw new Error('team name is required');

    const {
        initialDelay = 0,
        interval = 1500,
        maxAttempts = 10,
        timeoutMs = 5000,
        sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    } = options;

    if (initialDelay > 0) await sleep(initialDelay);

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        try {
            const data = await Api.get(
                `communities/${encodeURIComponent(slug)}/teams`,
                { viewer: ownerLower, _cb: Date.now() },
                { timeoutMs },
            );
            const items = Array.isArray(data?.items) ? data.items : [];
            const found = items.find((team) => (
                String(team?.owner || '').toLowerCase() === ownerLower
                && String(team?.name || '').toLowerCase() === nameLower
            ));
            if (found) {
                console.debug('[curation] create team visible', {
                    community: slug,
                    teamId: found.team_id,
                    attempt,
                });
                return found;
            }
            console.debug('[curation] create team not indexed yet', {
                community: slug,
                attempt,
                count: items.length,
            });
        } catch (err) {
            console.warn('[curation] create team visibility poll failed', {
                community: slug,
                attempt,
                error: String(err?.message || err),
            });
        }
        if (attempt < maxAttempts) await sleep(interval);
    }
    return null;
}
