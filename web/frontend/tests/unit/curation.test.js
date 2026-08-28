import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
    LENS,
    curationPendingKey,
    lensCacheKey,
    lensQuery,
    normalizeLens,
} from '../../src/utils/curation.js';
import { currentCreatorEpoch, normalizeClaimEpochs } from '../../src/logic/useCreatorEarnings.js';

const here = dirname(fileURLToPath(import.meta.url));
const frontendSrc = join(here, '../../src');

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

describe('v1.39 curation UI contracts', () => {
    it('keeps lens selection local — never imports tx or setCurationPreference', () => {
        const preferenceSrc = readFileSync(
            join(frontendSrc, 'logic/useCurationPreference.js'),
            'utf8',
        );
        const pickerSrc = readFileSync(
            join(frontendSrc, 'themes/default/components/CurationLensPicker.js'),
            'utf8',
        );
        expect(preferenceSrc).not.toMatch(/from ['"].*\/tx['"]/);
        expect(preferenceSrc).not.toMatch(/setCurationPreference/);
        expect(preferenceSrc).toMatch(/selecting locally \(no tx\)/);
        expect(preferenceSrc).toMatch(/lensChanged/);
        expect(pickerSrc).toMatch(/view selection \(local only\)/);
        expect(pickerSrc).not.toMatch(/await selectLens/);
    });

    it('does not show Create curator team on the Communities discover page', () => {
        const discover = readFileSync(
            join(frontendSrc, 'themes/default/routes/DiscoverView.js'),
            'utf8',
        );
        expect(discover).not.toMatch(/Create curator team/);
        expect(discover).not.toMatch(/curator-teams\/new/);
    });

    it('owns community feed title+sort in CommunityLensBar, not a second ListFeed title', () => {
        const main = readFileSync(
            join(frontendSrc, 'themes/default/routes/MainView.js'),
            'utf8',
        );
        expect(main).toMatch(/CommunityLensBar/);
        expect(main).toMatch(/FeedSortToggle/);
        expect(main).toMatch(/const feedTitle = urlTopic === 'all' \? 'All' : null/);
        expect(main).not.toMatch(/else if \(isTopicFeed\) feedTitle = communityLabel/);
    });

    it('drops the separate moderation policy field from team create/edit forms', () => {
        const create = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamsView.js'),
            'utf8',
        );
        const detail = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamView.js'),
            'utf8',
        );
        expect(create).not.toMatch(/Moderation policy/);
        expect(create).not.toMatch(/setPolicy/);
        expect(create).toMatch(/include how you moderate/);
        expect(detail).not.toMatch(/Team policy/);
        expect(detail).not.toMatch(/setPolicy/);
        expect(detail).toMatch(/include how you moderate/);
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
