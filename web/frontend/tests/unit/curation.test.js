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

    it('shows Uncensored only when a community has no curator teams', () => {
        const pickerSrc = readFileSync(
            join(frontendSrc, 'themes/default/components/CurationLensPicker.js'),
            'utf8',
        );
        expect(pickerSrc).toMatch(/uncensoredOnly/);
        expect(pickerSrc).toMatch(/FixedLens/);
        expect(pickerSrc).toMatch(/if \(!detail\.curated\) return LENS\.RAW/);
        expect(pickerSrc).toMatch(/Node default/);
        expect(pickerSrc).toMatch(/>Uncensored</);
        // Fixed "Uncensored" already means no teams — no redundant Uncurated chip.
        expect(pickerSrc).not.toMatch(/'Uncurated'/);
        expect(pickerSrc).not.toMatch(/"Uncurated"/);
    });

    it('passes return paths through Sign in and Subscribe on the teams page', () => {
        const teams = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamsView.js'),
            'utf8',
        );
        expect(teams).toMatch(/withReturnTo\('\/login'/);
        expect(teams).toMatch(/withReturnTo\('\/subscription'/);
    });

    it('treats admins as eligible to create curator teams without effective_paid', () => {
        const teams = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamsView.js'),
            'utf8',
        );
        const subscription = readFileSync(
            join(frontendSrc, 'logic/useSubscription.js'),
            'utf8',
        );
        expect(subscription).toMatch(/export const canCurate = \(effectivePaid, level\) => Boolean\(effectivePaid\) \|\| Number\(level\) >= 100/);
        expect(subscription).toMatch(/if \(n >= 100\) return 2/);
        expect(teams).toMatch(/canCurate\(data\.effective_paid, data\.user_level\)/);
        expect(teams).toMatch(/or an admin account/);
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
