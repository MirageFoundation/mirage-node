import { describe, expect, it } from 'vitest';
import {
    LENS,
    curationPendingKey,
    lensCacheKey,
    lensQuery,
    normalizeLens,
} from '../../src/utils/curation.js';
import { currentCreatorEpoch, normalizeClaimEpochs } from '../../src/logic/useCreatorEarnings.js';

describe('curation lenses', () => {
    it('keeps viewer, scope, lens, team, and community in feed cache identity', () => {
        const base = { viewer: 'mirage1viewer', community: 'tech', scope: 'current' };
        const raw = lensCacheKey({ ...base, lens: LENS.RAW });
        const team = lensCacheKey({ ...base, lens: LENS.TEAM, teamId: 7 });
        const otherViewer = lensCacheKey({ ...base, viewer: 'mirage1other', lens: LENS.RAW });
        expect(new Set([raw, team, otherViewer]).size).toBe(3);
    });

    it('requires a team ID only for the explicit team lens', () => {
        expect(normalizeLens('team', '3')).toEqual({ lens: 'team', teamId: 3 });
        expect(() => normalizeLens('team')).toThrow('team_id');
        expect(() => normalizeLens('raw', 3)).toThrow('only valid');
        expect(lensQuery('default')).toEqual({ lens: 'default', scope: 'current' });
    });

    it('uses the global pending tuple contract', () => {
        expect(curationPendingKey('invite_curator', 'Tech', 2, 'MIRAGE1USER'))
            .toBe('invite_curator:tech:2:mirage1user');
    });
});

describe('creator reward claims', () => {
    it('deduplicates and sorts epoch IDs', () => {
        expect(normalizeClaimEpochs([9, 3, 9, 5])).toEqual([3, 5, 9]);
    });

    it('rejects empty and oversized batches', () => {
        expect(() => normalizeClaimEpochs([])).toThrow('at least one');
        expect(() => normalizeClaimEpochs(Array.from({ length: 31 }, (_, index) => index + 1)))
            .toThrow('at most 30');
    });

    it('uses UTC day epochs for claim deadlines', () => {
        expect(currentCreatorEpoch(Date.UTC(2026, 7, 27, 23, 59, 59))).toBe(20692);
    });
});
