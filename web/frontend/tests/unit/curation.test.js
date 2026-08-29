import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import {
    LENS,
    MAX_CURATION_TEAM_DESCRIPTION_LENGTH,
    MAX_CURATION_TEAM_NAME_LENGTH,
    curationPendingKey,
    formatSubscriberCount,
    lensCacheKey,
    lensQuery,
    normalizeLens,
    runeLength,
    sliceRunes,
    teamIdWithMostSubscribers,
    waitForOwnCurationTeam,
} from '../../src/utils/curation.js';
import { currentCreatorEpoch, normalizeClaimEpochs } from '../../src/logic/useCreatorEarnings.js';
import Api from '../../src/utils/api.js';

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
    it('persists Default / team / Uncensored for joined viewers', () => {
        const preferenceSrc = readFileSync(
            join(frontendSrc, 'logic/useCurationPreference.js'),
            'utf8',
        );
        const pickerSrc = readFileSync(
            join(frontendSrc, 'themes/default/components/CurationLensPicker.js'),
            'utf8',
        );
        expect(preferenceSrc).toMatch(/tx\.setCurationPreference/);
        expect(preferenceSrc).toMatch(/LIVE_DEFAULT/);
        expect(preferenceSrc).toMatch(/lensChanged/);
        expect(pickerSrc).toMatch(/selectLens\(lens, teamId\)/);
        expect(pickerSrc).toMatch(/view selection \(local preview\)/);
        expect(pickerSrc).toMatch(/persist selection/);
        expect(pickerSrc).toMatch(/value=\{LENS\.DEFAULT\}/);
        expect(pickerSrc).toMatch(/`Default \(\$\{defaultTeamName\}\)`/);
        expect(pickerSrc).toMatch(/: 'Default'/);
    });

    it('shows Uncensored only when a community has no curator teams', () => {
        const pickerSrc = readFileSync(
            join(frontendSrc, 'themes/default/components/CurationLensPicker.js'),
            'utf8',
        );
        expect(pickerSrc).toMatch(/uncensoredOnly/);
        expect(pickerSrc).toMatch(/FixedLens/);
        expect(pickerSrc).toMatch(/if \(!detail\.curated\) return LENS\.RAW/);
        expect(pickerSrc).toMatch(/LENS\.DEFAULT/);
        expect(pickerSrc).not.toMatch(/Node default/);
        expect(pickerSrc).toMatch(/formatSubscriberCount/);
        expect(pickerSrc).toMatch(/__sep__/);
        expect(pickerSrc).toMatch(/>Uncensored</);
        // LIVE_DEFAULT stays Default — do not present the most-subscribed team as selected.
        expect(pickerSrc).not.toMatch(/teamIdWithMostSubscribers/);
        expect(pickerSrc).not.toMatch(/No explicit pin/);
        // Fixed "Uncensored" already means no teams — no redundant Uncurated chip.
        expect(pickerSrc).not.toMatch(/'Uncurated'/);
        expect(pickerSrc).not.toMatch(/"Uncurated"/);
        expect(pickerSrc).toMatch(/useViewerCuratorMembership/);
        expect(pickerSrc).toMatch(/Open Curation/);
        expect(pickerSrc).toMatch(/Curator teams →/);
        expect(pickerSrc).toMatch(/manageLabel = isCurator \? 'Open Curation'/);
    });

    it('formats subscriber counts as 1 sub / N subs', () => {
        expect(formatSubscriberCount(0)).toBe('0 subs');
        expect(formatSubscriberCount(1)).toBe('1 sub');
        expect(formatSubscriberCount(2)).toBe('2 subs');
        expect(teamIdWithMostSubscribers([
            { team_id: '2', subscriber_count: '1' },
            { team_id: '1', subscriber_count: '3' },
            { team_id: '3', subscriber_count: '3' },
        ])).toBe(1);
    });

    it('clamps team fields to chain rune limits', () => {
        expect(MAX_CURATION_TEAM_NAME_LENGTH).toBe(30);
        expect(MAX_CURATION_TEAM_DESCRIPTION_LENGTH).toBe(4000);
        expect(runeLength('café')).toBe(4);
        expect(sliceRunes('abcdefghij', 5)).toBe('abcde');
        expect(sliceRunes('a'.repeat(50), MAX_CURATION_TEAM_NAME_LENGTH).length).toBe(30);
        expect(runeLength(sliceRunes('x'.repeat(5000), MAX_CURATION_TEAM_DESCRIPTION_LENGTH))).toBe(4000);
    });

    it('passes return paths through Sign in and Subscribe on the teams page', () => {
        const teams = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamsView.js'),
            'utf8',
        );
        expect(teams).toMatch(/withReturnTo\('\/login'/);
        expect(teams).toMatch(/withReturnTo\('\/subscription'/);
        // Hidden users are team-scoped — only on the team detail page.
        expect(teams).not.toMatch(/#hidden-users/);
        expect(teams).not.toMatch(/Hidden users/);
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
        expect(main).toMatch(/CommunityLensHeading/);
        expect(main).toMatch(/topicFollowHover \? 'Unfollow' : 'Following'/);
        expect(main).toMatch(/\[community\] follow toggle/);
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
        expect(create).toMatch(/Describe your curation approach:/);
        expect(create).not.toMatch(/About this lens/);
        expect(create).toMatch(/MAX_CURATION_TEAM_NAME_LENGTH/);
        expect(create).toMatch(/MAX_CURATION_TEAM_DESCRIPTION_LENGTH/);
        expect(create).toMatch(/maxLength=\{maxTeamNameLength\}/);
        expect(create).toMatch(/maxLength=\{maxTeamDescriptionLength\}/);
        expect(create).toMatch(/sliceRunes/);
        expect(create).toMatch(/waitForOwnCurationTeam/);
        expect(create).toMatch(/pollTxStatus/);
        expect(create).toMatch(/Verifying…/);
        expect(create).toMatch(/curated feed/);
        expect(create).not.toMatch(/curated lens/);
        expect(create).toMatch(/No curator team for this community/);
        expect(create).toMatch(/no curator team yet/);
        expect(create).not.toMatch(/No curator teams yet/);
        expect(detail).not.toMatch(/Team policy/);
        expect(detail).not.toMatch(/setPolicy/);
        expect(detail).toMatch(/include how you moderate/);
        expect(detail).not.toMatch(/this lens/);
        expect(detail).not.toMatch(/CardTitle>About</);
        expect(detail).toMatch(/CardTitle>Team settings</);
        expect(detail).toMatch(/isLeader \? \(/);
        expect(detail).toMatch(/MAX_CURATION_TEAM_DESCRIPTION_LENGTH/);
        expect(detail).toMatch(/maxLength=\{maxTeamDescriptionLength\}/);
        expect(detail).toMatch(/resolveUserIdentity/);
        expect(detail).toMatch(/Username or mirage1/);
        expect(detail).toMatch(/formatUserLabel/);
        expect(detail).toMatch(/formatSubscriberCount/);
        expect(detail).not.toMatch(/Node default/);
        expect(detail).not.toMatch(/placeholder="mirage1…"/);
        // Hide/lock still live on the post shield, not a team-page target form.
        expect(detail).not.toMatch(/Moderation tools/);
        expect(detail).not.toMatch(/moderationTarget/);
        expect(detail).not.toMatch(/Hide post/);
        expect(detail).not.toMatch(/Lock thread/);
        expect(detail).toMatch(/Hidden users/);
        expect(detail).toMatch(/Hidden posts/);
        expect(detail).toMatch(/hidden-users/);
        expect(detail).toMatch(/hidden-posts/);
        expect(detail).toMatch(/useHiddenCurationUsers/);
        expect(detail).toMatch(/useHiddenCurationPosts/);
        expect(detail).toMatch(/moderateCurationUser/);
        expect(detail).toMatch(/moderateCurationPost/);
        expect(detail).toMatch(/Load 50 more/);
        expect(detail).toMatch(/FormActions/);
        expect(detail).toMatch(/justify-content: flex-end/);
        const teamsHook = readFileSync(
            join(frontendSrc, 'logic/useCurationTeams.js'),
            'utf8',
        );
        expect(teamsHook).toMatch(/export function useHiddenCurationUsers/);
        expect(teamsHook).toMatch(/export function useHiddenCurationPosts/);
        expect(teamsHook).toMatch(/HIDDEN_LIST_INITIAL/);
        expect(teamsHook).toMatch(/HIDDEN_LIST_MORE/);
        expect(teamsHook).toMatch(/'hidden-users'/);
        expect(teamsHook).toMatch(/'hidden-posts'/);
        const curationUtils = readFileSync(
            join(frontendSrc, 'utils/curation.js'),
            'utf8',
        );
        expect(curationUtils).toMatch(/HIDDEN_LIST_INITIAL = 10/);
        expect(curationUtils).toMatch(/HIDDEN_LIST_MORE = 50/);
    });

    it('puts Curate + admin delete on a separate ModMenuChip shield menu', () => {
        const postMenu = readFileSync(
            join(frontendSrc, 'themes/default/components/PostMenu.js'),
            'utf8',
        );
        const cardView = readFileSync(
            join(frontendSrc, 'themes/default/components/CardView.js'),
            'utf8',
        );
        const viewPost = readFileSync(
            join(frontendSrc, 'themes/default/routes/ViewPostView.js'),
            'utf8',
        );
        const listFeed = readFileSync(
            join(frontendSrc, 'themes/default/ListFeedView.js'),
            'utf8',
        );
        const curateItems = readFileSync(
            join(frontendSrc, 'themes/default/components/CurateMenuItems.js'),
            'utf8',
        );
        const actions = readFileSync(
            join(frontendSrc, 'logic/usePostCurateActions.js'),
            'utf8',
        );
        const membership = readFileSync(
            join(frontendSrc, 'logic/useViewerCuratorMembership.js'),
            'utf8',
        );

        expect(postMenu).toMatch(/export function ModMenuChip/);
        expect(postMenu).toMatch(/Moderation menu/);
        expect(postMenu).toMatch(/Mark post deleted/);
        expect(postMenu).toMatch(/CurateMenuItems/);
        expect(postMenu).not.toMatch(/MenuHeader>Admin</);
        expect(postMenu).not.toMatch(/renderHeader/);
        // ⋯ menu must not own curate / admin-delete anymore.
        expect(postMenu).not.toMatch(/isAdminVisible && \(\s*\n\s*<MenuItemBtn[^>]*Mark post deleted/s);
        for (const src of [cardView, viewPost, listFeed]) {
            expect(src).toMatch(/ModMenuChip/);
            expect(src).not.toMatch(/CurateMenuItems/);
        }
        expect(curateItems).not.toMatch(/Curate · /);
        expect(curateItems).toMatch(/usePostCurateActions/);
        expect(actions).toMatch(/moderateCurationPost/);
        expect(actions).toMatch(/moderateCurationUser/);
        expect(actions).toMatch(/setCurationThreadLocked/);
        expect(actions).toMatch(/\/moderation/);
        expect(actions).toMatch(/modState\.postHidden/);
        expect(actions).toMatch(/modState\.userHidden/);
        expect(actions).toMatch(/modState\.threadLocked/);
        expect(actions).toMatch(/Hide post/);
        expect(actions).toMatch(/Show post/);
        expect(actions).toMatch(/Hide user/);
        expect(actions).toMatch(/Show user/);
        expect(actions).toMatch(/Lock thread/);
        expect(actions).toMatch(/Unlock thread/);
        // Toggle: only one of each pair is pushed per state branch.
        expect(actions).toMatch(/if \(modState\.postHidden\)/);
        expect(actions).toMatch(/if \(modState\.userHidden\)/);
        expect(actions).toMatch(/if \(modState\.threadLocked\)/);
        expect(membership).toMatch(/viewer_team_ids/);
        expect(membership).toMatch(/isCurator/);
        expect(curateItems).toMatch(/active/);
    });
});

describe('waitForOwnCurationTeam', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    it('returns the team once the owner+name appear in the list', async () => {
        const sleep = vi.fn(async () => { });
        const get = vi.spyOn(Api, 'get')
            .mockResolvedValueOnce({ items: [] })
            .mockResolvedValueOnce({
                items: [{
                    team_id: 3,
                    owner: 'mirage1viewer',
                    name: 'Signal Desk',
                    description: '',
                    subscriber_count: '0',
                }],
            });

        const found = await waitForOwnCurationTeam('Tech', 'MIRAGE1VIEWER', 'Signal Desk', {
            interval: 10,
            maxAttempts: 5,
            sleep,
        });

        expect(found.team_id).toBe(3);
        expect(get).toHaveBeenCalledTimes(2);
        expect(sleep).toHaveBeenCalledTimes(1);
    });

    it('returns null when the team never appears within the budget', async () => {
        const sleep = vi.fn(async () => { });
        vi.spyOn(Api, 'get').mockResolvedValue({ items: [] });

        const found = await waitForOwnCurationTeam('tech', 'mirage1viewer', 'Signal Desk', {
            interval: 1,
            maxAttempts: 3,
            sleep,
        });

        expect(found).toBe(null);
        expect(sleep).toHaveBeenCalledTimes(2);
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
