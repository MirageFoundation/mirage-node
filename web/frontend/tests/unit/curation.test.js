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
        expect(pickerSrc).toMatch(/change\(LENS\.DEFAULT\)/);
        expect(pickerSrc).toMatch(/if \(selection === LENS\.DEFAULT\) return 'Default Curation Team'/);
        expect(pickerSrc).toMatch(/OptionMeta>Currently \{defaultTeamName\}/);
        // Rapid switches: only roll back the failed pick, never a newer one.
        expect(pickerSrc).toMatch(
            /setOptimisticSelection\(\(current\) => \(current === selection \? null : current\)\)/,
        );
        expect(pickerSrc).toMatch(/optimistic confirmed by detail/);
    });

    it('drops stale community/team refreshes so rapid lens switches keep the label', () => {
        const detailSrc = readFileSync(
            join(frontendSrc, 'logic/useCommunityDetail.js'),
            'utf8',
        );
        const teamsSrc = readFileSync(
            join(frontendSrc, 'logic/useCurationTeams.js'),
            'utf8',
        );
        expect(detailSrc).toMatch(/requestSeq/);
        expect(detailSrc).toMatch(/detail stale response dropped/);
        expect(detailSrc).toMatch(/background = false/);
        expect(teamsSrc).toMatch(/requestSeq/);
        expect(teamsSrc).toMatch(/teams stale response dropped/);
        expect(teamsSrc).toMatch(/refresh\(\{ background: true \}\)/);
    });

    it('keeps lens selection and team actions in one dropdown', () => {
        const pickerSrc = readFileSync(
            join(frontendSrc, 'themes/default/components/CurationLensPicker.js'),
            'utf8',
        );
        expect(pickerSrc).toMatch(/if \(!detail\.curated\) return LENS\.RAW/);
        expect(pickerSrc).toMatch(/LENS\.DEFAULT/);
        expect(pickerSrc).not.toMatch(/Node default/);
        expect(pickerSrc).toMatch(/formatSubscriberCount/);
        expect(pickerSrc).toMatch(/__team_action__/);
        expect(pickerSrc).toMatch(/Create new…/);
        expect(pickerSrc).toMatch(/Manage my team…/);
        expect(pickerSrc).toMatch(/teams\/new/);
        expect(pickerSrc).toMatch(/PickerButton/);
        expect(pickerSrc).toMatch(/height: var\(--community-header-control-height, 28px\)/);
        expect(pickerSrc).toMatch(/font-size: var\(--community-header-control-font-size, 0\.68rem\)/);
        expect(pickerSrc).toMatch(/role="listbox"/);
        expect(pickerSrc).toMatch(/onChange\?\.\(lens, rawTeamId \? Number\(rawTeamId\) : null, activeTeam\)/);
        expect(pickerSrc).not.toMatch(/styled\.select/);
        expect(pickerSrc).toMatch(/>Uncensored</);
        // LIVE_DEFAULT stays Default — do not present the most-subscribed team as selected.
        expect(pickerSrc).not.toMatch(/teamIdWithMostSubscribers/);
        expect(pickerSrc).not.toMatch(/No explicit pin/);
        expect(pickerSrc).toMatch(/useViewerCuratorMembership/);
        expect(pickerSrc).not.toMatch(/ManageLink/);
        expect(pickerSrc).not.toMatch(/Curator teams/);
    });

    it('redirects the obsolete team listing route to the community', () => {
        const appSrc = readFileSync(join(frontendSrc, 'App.js'), 'utf8');
        expect(appSrc).toMatch(/path="\/c\/:topic\/teams"/);
        expect(appSrc).toMatch(/element=\{<CommunityTeamsRedirect \/>}/);
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
        expect(MAX_CURATION_TEAM_DESCRIPTION_LENGTH).toBe(800);
        expect(runeLength('café')).toBe(4);
        expect(sliceRunes('abcdefghij', 5)).toBe('abcde');
        expect(sliceRunes('a'.repeat(50), MAX_CURATION_TEAM_NAME_LENGTH).length).toBe(30);
        expect(runeLength(sliceRunes('x'.repeat(5000), MAX_CURATION_TEAM_DESCRIPTION_LENGTH))).toBe(800);
    });

    it('passes return paths through Sign in and Subscribe on the team creation page', () => {
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
        expect(main).toMatch(/CommunityMembershipPicker/);
        expect(main).toMatch(/--community-header-control-height: 28px/);
        expect(main).toMatch(/--community-header-control-font-size: 0\.68rem/);
        expect(main).toMatch(/border: 1px solid transparent/);
        expect(main).toMatch(/CurationTeamHeader/);
        expect(main).toMatch(/activeCurationTeam\.description/);
        // Long unbroken descriptions must wrap inside the header, not overflow sideways.
        expect(main).toMatch(/const CurationTeamDescription = styled\.p`[^`]*overflow-wrap: anywhere;/);
        // The picker already shows the selected team; repeating its name below is noise.
        expect(main).not.toMatch(/CurationTeamTitle/);
        expect(main).not.toMatch(/activeCurationTeam\.name/);
        expect(main).toMatch(/font-size: 0\.62rem/);
        expect(main).toMatch(/\[lens\] community header updated/);
        expect(main).toMatch(/\[community\] membership toggle/);
        // Title is 0.9rem and the controls 0.68rem, so centering their boxes
        // leaves the text off by ~1.2px. Only baseline alignment lines them up.
        expect(main).toMatch(/const CommunityLensTopRow = styled\.div`[^`]*align-items: baseline;/);
        expect(main).toMatch(/const CommunityLensHeading = styled\.div`[^`]*align-items: baseline;/);
        // The view toggle is icon-only and has no baseline, so its group stays centered.
        expect(main).toMatch(/const CommunityLensControls = styled\.div`[^`]*align-items: center;/);
        expect(main).toMatch(/const feedTitle = urlTopic === 'all' \? 'All' : null/);
        expect(main).not.toMatch(/else if \(isTopicFeed\) feedTitle = communityLabel/);
    });

    it('uses the team description as the selected community header description', () => {
        const create = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamsView.js'),
            'utf8',
        );
        const detail = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamView.js'),
            'utf8',
        );
        const curation = readFileSync(join(frontendSrc, 'utils/curation.js'), 'utf8');
        expect(create).not.toMatch(/Moderation policy/);
        expect(create).not.toMatch(/setPolicy/);
        expect(create).toMatch(/Community header description/);
        expect(create).toMatch(/Shown beneath your team name in the community header/);
        expect(create).toMatch(/placeholder="Sailboats & Sailors only"/);
        expect(create).toMatch(/CURATION_TEAM_DESCRIPTION_EXAMPLE/);
        expect(create).toMatch(/'data-bwignore': 'true'/);
        expect(curation).toMatch(/dedicated to all things sailboats and sailing/);
        expect(curation).toMatch(/you might get hidden from our curation team/);
        expect(create).not.toMatch(/About this lens/);
        expect(create).toMatch(/MAX_CURATION_TEAM_NAME_LENGTH/);
        expect(create).toMatch(/MAX_CURATION_TEAM_DESCRIPTION_LENGTH/);
        expect(create).toMatch(/maxLength=\{maxTeamNameLength\}/);
        expect(create).toMatch(/maxLength=\{maxTeamDescriptionLength\}/);
        expect(create).toMatch(/sliceRunes/);
        expect(create).toMatch(/waitForOwnCurationTeam/);
        expect(create).toMatch(/opening created team/);
        expect(create).toMatch(/\/teams\/\$\{visibleId\}/);
        expect(create).toMatch(/← Back to community/);
        expect(create).not.toMatch(/destination team list ready/);
        expect(create).toMatch(/pollTxStatus/);
        expect(create).toMatch(/Verifying…/);
        expect(create).not.toMatch(/curated lens/);
        expect(create).not.toMatch(/No curator team for this community/);
        expect(create).not.toMatch(/teamState\.teams\.map/);
        expect(detail).not.toMatch(/Team policy/);
        expect(detail).not.toMatch(/setPolicy/);
        expect(detail).toMatch(/Community header description/);
        expect(detail).toMatch(/CURATION_TEAM_DESCRIPTION_EXAMPLE/);
        expect(detail).toMatch(/'data-bwignore': 'true'/);
        expect(detail).not.toMatch(/this lens/);
        expect(detail).not.toMatch(/CardTitle>About</);
        expect(detail).toMatch(/CardTitle>Team profile</);
        expect(detail).toMatch(/CardTitle>Community defaults</);
        expect(detail).toMatch(/Subscriber-only posting/);
        expect(detail).toMatch(/Community tag/);
        expect(detail).toMatch(/CardTitle>Danger zone</);
        expect(detail).toMatch(/FieldLabel>Team name</);
        expect(detail).toMatch(/FieldLabel>Community header description</);
        expect(detail).toMatch(/← Back to community/);
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
        expect(detail.indexOf('CardTitle>Danger zone')).toBeGreaterThan(detail.indexOf('Card id="hidden-posts"'));
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

    it('builds the community header from one shared flat control', () => {
        const main = readFileSync(
            join(frontendSrc, 'themes/default/routes/MainView.js'),
            'utf8',
        );
        const picker = readFileSync(
            join(frontendSrc, 'themes/default/components/CurationLensPicker.js'),
            'utf8',
        );
        const listFeed = readFileSync(
            join(frontendSrc, 'themes/default/ListFeedView.js'),
            'utf8',
        );
        const control = readFileSync(
            join(frontendSrc, 'themes/default/components/FeedControlButton.js'),
            'utf8',
        );

        // The header controls (membership, lens, "Best", view mode) must be the
        // same component, or the row drifts back into different sizes/weights.
        const membership = readFileSync(
            join(frontendSrc, 'themes/default/components/CommunityMembershipPicker.js'),
            'utf8',
        );
        expect(control).toMatch(/height: 28px/);
        expect(control).toMatch(/font-size: 0\.68rem/);
        expect(control).toMatch(/font-weight: 400/);
        expect(listFeed).toMatch(/import CtrlButton from "\.\/components\/FeedControlButton"/);
        expect(listFeed).not.toMatch(/const CtrlButton = styled\.button/);
        expect(picker).toMatch(/styled\(FeedControlButton\)/);
        expect(picker).not.toMatch(/variant="secondary"/);
        expect(membership).toMatch(/styled\(FeedControlButton\)/);
        expect(membership).toMatch(/HiChevronDown/);
        expect(membership).toMatch(/actionLabel = joined \? 'Leave' : 'Join'/);
        // Membership sits on the right, immediately left of the sort control.
        expect(main).toMatch(
            /CommunityMembershipPicker[\s\S]*FeedSortToggle[\s\S]*FeedViewToggle/,
        );

        // Default stays a fixed label; pinned teams keep their full name.
        expect(picker).not.toMatch(/max-width: 14rem/);
        expect(picker).toMatch(/return 'Default Curation Team'/);
        expect(picker).toMatch(/return team\.name;/);
    });

    it('deletes a team through an in-app dialog and leaves the page', () => {
        const detail = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamView.js'),
            'utf8',
        );
        const curationUtils = readFileSync(
            join(frontendSrc, 'utils/curation.js'),
            'utf8',
        );
        expect(detail).not.toMatch(/window\.confirm/);
        expect(detail).toMatch(/<ConfirmDialog/);
        expect(detail).toMatch(/confirmLabel="Delete team"/);
        // Once the tx lands the team is gone, so the page must not stay open.
        expect(detail).toMatch(/navigate\(`\/c\/\$\{encodeURIComponent\(community\)\}`\)/);
        // The sidebar's curator highlight only clears on a refresh issued after
        // the indexer has dropped the team.
        expect(curationUtils).toMatch(/export async function waitForCurationTeamGone/);
        expect(detail).toMatch(/waitForCurationTeamGone\(community, Number\(teamId\), \{ viewer \}\)/);
        expect(detail).toMatch(/\.then\(\(\) => invalidateCurationReads\(community\)\)/);
    });

    it('keeps a saved team profile on screen until the API serves it', () => {
        const detail = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamView.js'),
            'utf8',
        );
        const curationUtils = readFileSync(
            join(frontendSrc, 'utils/curation.js'),
            'utf8',
        );
        expect(curationUtils).toMatch(/export async function waitForCurationTeamProfile/);
        // The form must not reseed from a read that predates the save.
        expect(detail).toMatch(/savedProfileRef/);
        expect(detail).toMatch(/if \(team\.name !== saved\.name \|\| team\.description !== saved\.description\) return;/);
        expect(detail).toMatch(/waitForCurationTeamProfile/);
        expect(detail).toMatch(/pollTxStatus/);
        expect(detail).toMatch(/'Verifying…'/);
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
        expect(postMenu).toMatch(/Delete network wide/);
        expect(postMenu).toMatch(/isAdminVisible && curateVisible && <MenuDivider/);
        expect(postMenu).toMatch(/CurateMenuItems/);
        expect(postMenu).not.toMatch(/MenuHeader>Admin</);
        expect(postMenu).not.toMatch(/renderHeader/);
        // ⋯ menu must not own curate / admin-delete anymore.
        expect(postMenu).not.toMatch(/isAdminVisible && \(\s*\n\s*<MenuItemBtn[^>]*Delete network wide/s);
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
        expect(actions).toMatch(/Restore post/);
        expect(actions).toMatch(/Hide user/);
        expect(actions).toMatch(/Restore user/);
        expect(actions).toMatch(/Lock thread/);
        expect(actions).toMatch(/Unlock thread/);
        // Toggle: only one of each pair is pushed per state branch.
        expect(actions).toMatch(/if \(modState\.postHidden\)/);
        expect(actions).toMatch(/if \(modState\.userHidden\)/);
        expect(actions).toMatch(/if \(modState\.threadLocked\)/);
        expect(membership).toMatch(/viewer_team_ids/);
        expect(membership).toMatch(/isCurator/);
        expect(membership).toMatch(/export function useViewerCuratorCommunities/);
        expect(membership).toMatch(/curators\/\$\{encodeURIComponent\(viewer\)\}\/communities/);
        expect(curateItems).toMatch(/active/);
        const sidebar = readFileSync(
            join(frontendSrc, 'themes/default/components/Sidebar.js'),
            'utf8',
        );
        expect(sidebar).toMatch(/useViewerCuratorCommunities/);
        expect(sidebar).toMatch(/\$curated/);
        expect(sidebar).toMatch(/voteUp/);
        expect(sidebar).toMatch(/orderedTopics/);
        expect(sidebar).toMatch(/HiUserGroup/);
        expect(sidebar).not.toMatch(/HiHashtag/);
        const createTeams = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamsView.js'),
            'utf8',
        );
        const teamDetail = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamView.js'),
            'utf8',
        );
        expect(createTeams).toMatch(/min-height: 16rem/);
        expect(teamDetail).toMatch(/min-height: 16rem/);
        expect(teamDetail).toMatch(/Restore/);
        expect(teamDetail).not.toMatch(/Showing…/);
    });

    it('signs both tag messages with the field numbers the chain reads', () => {
        const handler = readFileSync(join(frontendSrc, 'utils/TransactionHandler.js'), 'utf8');

        // These tuples are the browser half of the canon contract: shared
        // canon.py and the Go ante decorators encode the same tags, and a
        // single mismatched number makes every signature unverifiable.
        expect(handler).toMatch(
            /set_curation_tag: \['MsgSetCurationTag', 'core\/set_curation_tag', \[\['community', 100, 'string'\], \['team_id', 101, 'uint'\], \['tag', 102, 'string'\]\]\]/,
        );
        expect(handler).toMatch(
            /set_curation_post_tag: \['MsgSetCurationPostTag', 'core\/set_curation_post_tag', \[\['community', 100, 'string'\], \['team_id', 101, 'uint'\], \['target', 102, 'string'\], \['tag', 103, 'string'\], \['clear', 104, 'bool'\]\]\]/,
        );
        // Both wrappers reject anything outside the shared whitelist before a
        // transaction is ever built.
        expect(handler).toMatch(/async setCurationTag\(community, teamId, tag\)/);
        expect(handler).toMatch(/async setCurationPostTag\(community, teamId, postId, tag, clear = false\)/);
        expect(handler).toMatch(/if \(!ALLOWED_TAGS\.has\(value\)\) throw new Error\(`invalid tag/);

        const txApi = readFileSync(join(frontendSrc, 'utils/tx.js'), 'utf8');
        expect(txApi).toMatch(/export async function setCurationTag\(/);
        expect(txApi).toMatch(/export async function setCurationPostTag\(/);
    });

    it('stops offering a reply on a thread the current lens has locked', () => {
        const viewPost = readFileSync(
            join(frontendSrc, 'themes/default/routes/ViewPostView.js'),
            'utf8',
        );

        // The lock is a read filter, so the chain still accepts a reply. The UI
        // is what has to stop the user from spending PoW and daily quota on a
        // comment their own lens would hide the moment it lands.
        expect(viewPost).toMatch(/const threadLocked = !!root\?\.thread_locked;/);
        expect(viewPost).toMatch(/threadLocked \? <LockedNote/);
        expect(viewPost).toMatch(/thread locked</);
        // A composer already open when the lock lands must close, but editing
        // your own existing post is not a new reply and stays allowed.
        expect(viewPost).toMatch(/if \(threadLocked && !isEdit\) return <div><\/div>;/);
        expect(viewPost).toMatch(/if \(!isMobile \|\| threadLocked\) return null;/);
    });

    it('gives the owner a community tag control and every curator a per-post override', () => {
        const teamDetail = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamView.js'),
            'utf8',
        );
        const actions = readFileSync(join(frontendSrc, 'logic/usePostCurateActions.js'), 'utf8');
        const postMenu = readFileSync(join(frontendSrc, 'themes/default/components/PostMenu.js'), 'utf8');

        // Community tag lives on the owner-only settings page, next to the
        // other team-wide switch, and reuses the composer's tag vocabulary.
        expect(teamDetail).toMatch(/Community tag/);
        expect(teamDetail).toMatch(/tx\.setCurationTag\(community, Number\(teamId\), e\.target\.value\)/);
        expect(teamDetail).toMatch(/TAG_OPTIONS/);

        // Per-post override is one select, not one row per tag, and keeps
        // "no override" distinct from "untagged".
        expect(actions).toMatch(/setCurationPostTag/);
        expect(actions).toMatch(/const INHERIT_TAG = '__inherit__'/);
        expect(actions).toMatch(/No override/);
        expect(actions).toMatch(/Untagged/);
        expect(actions).toMatch(/postTag: typeof data\.post_tag === 'string' \? data\.post_tag : null/);
        expect(actions).toMatch(/modState\.postTag === null \? INHERIT_TAG : modState\.postTag/);
        expect(postMenu).toMatch(/item\.type === 'select'/);
        expect(postMenu).toMatch(/MenuSelect/);
    });

    it('clears the curator membership cache from module scope, not only while mounted', async () => {
        // Creating a team happens on the teams route, which never mounts
        // useViewerCuratorMembership. When the invalidation only reached the
        // hook's own listeners there was nothing to hear it, so the cached
        // "not a curator" survived into the community feed and the curate
        // buttons stayed hidden until a reload.
        const listeners = [];
        const addSpy = vi
            .spyOn(window, 'addEventListener')
            .mockImplementation((type, handler) => {
                listeners.push(type);
                return undefined;
            });
        try {
            vi.resetModules();
            await import('../../src/logic/useViewerCuratorMembership.js');
        } finally {
            addSpy.mockRestore();
        }
        expect(listeners).toContain('curationUpdated');
    });

    it('invalidates curation reads once the created team is indexed', () => {
        const teamsView = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamsView.js'),
            'utf8',
        );
        expect(teamsView).toMatch(/invalidateCurationReads/);
        // Must come after the indexer has been confirmed to serve the team,
        // otherwise the refetch re-caches the pre-team state it is replacing.
        const waitAt = teamsView.indexOf('waitForOwnCurationTeam(nextSlug');
        const invalidateAt = teamsView.indexOf('invalidateCurationReads(nextSlug)');
        expect(waitAt).toBeGreaterThan(-1);
        expect(invalidateAt).toBeGreaterThan(waitAt);
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
