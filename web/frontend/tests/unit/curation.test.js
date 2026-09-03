import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import {
    LENS,
    LENS_PICKS_MAX,
    MAX_CURATION_TEAM_DESCRIPTION_LENGTH,
    MAX_CURATION_TEAM_NAME_LENGTH,
    clearLensPick,
    curationPendingKey,
    formatPinCount,
    formatSubscriberCount,
    joinPreferenceForLens,
    lensCacheKey,
    lensHintLabel,
    lensPicksParam,
    lensQuery,
    normalizeLens,
    readLensPick,
    requireCurationTeamDescription,
    requireCurationTeamName,
    runeLength,
    sliceRunes,
    teamIdWithMostSubscribers,
    viewingTeamId,
    waitForOwnCurationTeam,
    waitForCurationInvite,
    curatorInviteHeroCopy,
    writeLensPick,
} from '../../src/utils/curation.js';
import {
    currentCreatorEpoch,
    fetchCreatorEarningsPages,
    isCreatorEarningClaimable,
    nextClaimSelection,
    normalizeClaimEpochs,
    requireCreatorClaimCheckTx,
    waitForCreatorClaim,
} from '../../src/logic/useCreatorEarnings.js';
import { formatCreatorRewardTime } from '../../src/themes/default/components/CreatorEarningsPanel.js';
import {
    communityFromPathname,
    createPostPathForContext,
    isValidCommunitySlug,
    sanitizeCommunitySlug,
    splitCommunityMentions,
    splitJoinedCommunitiesForComposer,
} from '../../src/utils/community.js';
import {
    CURATOR_READ_ACTION,
    FEED_READ_ACTION,
    signedReadPayload,
} from '../../src/utils/signPlain.js';
import Api from '../../src/utils/api.js';
import {
    registerCommunityLeaveConfirmationHandler,
    requestCommunityLeaveConfirmation,
} from '../../src/utils/communityLeaveConfirmation.js';
import {
    isOptimisticallyCurationHidden,
    setOptimisticCurationVisibility,
} from '../../src/utils/curationVisibility.js';
import { TransactionHandler } from '../../src/utils/TransactionHandler.js';

vi.mock('../../src/utils/signPlain.js', async (importOriginal) => ({
    ...await importOriginal(),
    signReadParams: vi.fn().mockResolvedValue({
        pubkey: 'proof-pubkey',
        signature: 'proof-signature',
        envelope_nonce: 1,
        timestamp: 1,
    }),
}));

const here = dirname(fileURLToPath(import.meta.url));
const frontendSrc = join(here, '../../src');

describe('join locks in the lens on screen', () => {
    it('maps every pickable lens to the preference the join stores', () => {
        expect(joinPreferenceForLens(LENS.TEAM, 7)).toEqual({ mode: 1, pinnedTeamId: 7 });
        expect(joinPreferenceForLens(LENS.RAW)).toEqual({ mode: 2, pinnedTeamId: 0 });
        // Default and effective both defer to the chain, which resolves the
        // community default to a concrete pin at join height.
        expect(joinPreferenceForLens(LENS.DEFAULT)).toEqual({ mode: 0, pinnedTeamId: 0 });
        expect(joinPreferenceForLens(LENS.EFFECTIVE)).toEqual({ mode: 0, pinnedTeamId: 0 });
        expect(joinPreferenceForLens(undefined)).toEqual({ mode: 0, pinnedTeamId: 0 });
    });

    it('refuses a team lens without a team, rather than joining on the wrong lens', () => {
        expect(() => joinPreferenceForLens(LENS.TEAM, 0)).toThrow(/team_id/);
        expect(() => joinPreferenceForLens('nonsense')).toThrow(/Cannot join with lens/);
    });

    // The browser, the backend and the chain each build the signed preimage
    // independently; one byte of disagreement makes every join unverifiable.
    // Expected values come from shared/canon.py, which is itself pinned to Go
    // by blockchain/app/ante_canon_v139_parity_test.go.
    it('encodes the lens fields exactly as shared/canon.py does', () => {
        const envelope = {
            pub_bytes: Uint8Array.from({ length: 32 }, (_, i) => i),
            last_block_hash: 'aa'.repeat(32),
            difficulty: 21,
            proof: 3,
            timestamp: 1750000000,
            nonce: 7,
            community: 'technology',
        };
        const toHex = (bytes) => Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
        const canon = (mode, pinned_team_id) => toHex(
            TransactionHandler.prototype.canonicalJoinCommunity({ ...envelope, mode, pinned_team_id }),
        );
        const prefix = '6d69726167652e636f72652e76313a4d73674a6f696e436f6d6d756e69747900'
            + '0220000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f'
            + '0320aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
            + '041505030680c3bbc2060707640a746563686e6f6c6f6779';
        expect(canon(0, 0)).toBe(`${prefix}65006600`);
        expect(canon(1, 4)).toBe(`${prefix}65016604`);
        expect(canon(2, 0)).toBe(`${prefix}65026600`);
    });

    // Every hand-written message is encoded twice in TransactionHandler: a
    // canonicalX method for the metasig, and an inline branch for the PoW
    // preimage. Nothing links the two, so adding a field to one and not the
    // other ships a browser whose PoW covers different bytes than the chain
    // verifies — which is how the join lens fields reached the metasig only.
    // No suite caught it, because the Python helpers sign with shared/canon.py
    // and only a real browser runs the PoW branch.
    //
    // Curation messages are structurally immune: both sides iterate
    // CURATION_TX_SPECS. These pairs are the ones a human has to keep in step,
    // so assert it instead of trusting it. Envelope tags legitimately differ —
    // the metasig covers the proof (field 5) and the PoW preimage cannot — so
    // this compares message fields, which are tag 100 and up.
    it('keeps message fields identical between every metasig and PoW preimage', () => {
        const src = readFileSync(join(frontendSrc, 'utils/TransactionHandler.js'), 'utf8');
        const byMessage = new Map();

        for (const match of src.matchAll(/mirage\.core\.v1:(Msg\w+)\\x00/g)) {
            const concatAt = src.indexOf('concat(', match.index);
            expect(concatAt, `no concat() found for ${match[1]}`).toBeGreaterThan(-1);
            // Balance parens rather than scanning for ');': the tag consts are
            // themselves `Uint8Array.from([2]);` and nested calls end in ')'.
            let depth = 0;
            let end = concatAt;
            for (let i = concatAt + 'concat'.length; i < src.length; i++) {
                if (src[i] === '(') depth++;
                else if (src[i] === ')') { depth--; if (depth === 0) { end = i; break; } }
            }
            const region = src.slice(match.index, end);
            const declared = new Map();
            for (const d of region.matchAll(/const\s+(tag\w+)\s*=\s*Uint8Array\.from\(\[(\d+)\]\)/g)) {
                declared.set(d[1], Number(d[2]));
            }
            // Scan the whole builder, not just the concat() arguments: MsgPost
            // and friends assemble a parts array and push onto it above the
            // final concat. Drop the tag declarations first, so a const that is
            // declared but never encoded still reads as a missing field.
            const body = region.replace(/const\s+tag\w+\s*=\s*Uint8Array\.from\(\[\d+\]\);/g, '');
            const tags = new Set();
            for (const t of body.matchAll(/\btag(\w+)\b/g)) {
                const resolved = declared.has(`tag${t[1]}`) ? declared.get(`tag${t[1]}`) : Number(t[1]);
                if (Number.isFinite(resolved)) tags.add(resolved);
            }
            for (const t of body.matchAll(/Uint8Array\.from\(\[(\d+)\]\)/g)) tags.add(Number(t[1]));

            const fields = [...tags].filter((n) => n >= 100).sort((a, b) => a - b);
            if (!byMessage.has(match[1])) byMessage.set(match[1], []);
            byMessage.get(match[1]).push(fields);
        }

        const paired = [...byMessage.entries()].filter(([, variants]) => variants.length > 1);
        // Guards the parser itself: a regex that silently matched nothing would
        // otherwise make this test vacuously pass forever.
        expect(paired.length).toBeGreaterThanOrEqual(10);

        // Report every drifted message at once. Failing on the first one turns a
        // sweep into one-at-a-time archaeology.
        const drifted = paired
            .filter(([, variants]) => variants.slice(1).some((v) => String(v) !== String(variants[0])))
            .map(([message, variants]) => `${message}: ${variants.map((v) => `[${v}]`).join(' vs ')}`);
        expect(drifted, 'metasig and PoW preimages cover different message fields').toEqual([]);

        // subscribe, set_auto_renewal and award are paid with tokens and the
        // chain rejects any of them carrying PoW, so they must have exactly one
        // builder. MsgSubscribe used to carry a second, unreachable PoW encoder
        // that had quietly lost envelope_timestamp, envelope_nonce and
        // period_count — a drift nobody could hit, sitting one routing change
        // away from being reachable.
        for (const message of ['MsgSubscribe', 'MsgSetAutoRenewal', 'MsgAward']) {
            expect(byMessage.get(message), `${message} is fee-only and must not have a PoW preimage`)
                .toHaveLength(1);
        }
    });
});

describe('curation lenses', () => {
    it('keeps viewer, scope, lens, team, and community in feed cache identity', () => {
        const base = { viewer: 'mirage1viewer', community: 'tech', scope: 'current' };
        const raw = lensCacheKey({ ...base, lens: LENS.RAW });
        const team = lensCacheKey({ ...base, lens: LENS.TEAM, teamId: 7 });
        const otherViewer = lensCacheKey({ ...base, viewer: 'mirage1other', lens: LENS.RAW });
        expect(new Set([raw, team, otherViewer]).size).toBe(3);
    });

    it('refetches instead of restoring another lens from community-wide post state', () => {
        const main = readFileSync(join(frontendSrc, 'logic/useMain.js'), 'utf8');
        expect(main).toMatch(/shouldRestoreFeedState && showsCurrentLens/);
        expect(main).toMatch(/if \(hasPostsForOrder\)/);
        expect(main).not.toMatch(/hasAnyCachedPostsForCommunity/);
    });

    it('ties restore and cache writes to the lens the on-screen posts came from', () => {
        const main = readFileSync(join(frontendSrc, 'logic/useMain.js'), 'utf8');
        // The identity may only advance when a page-1 response is applied,
        // otherwise a lens switch restores (or saves) the previous feed.
        expect(main).toMatch(/const showsCurrentLens = feedDataIdentityRef\.current === feedCacheCommunity/);
        expect(main).toMatch(/if \(feedDataIdentityRef\.current !== feedCacheCommunity\) \{/);
        expect(main).toMatch(/feedDataIdentityRef\.current = feedCacheCommunity;/);
        expect(main).toMatch(/posts belong to another lens/);
    });

    it('ignores a repeated lens pick so the pending fetch is not cancelled', () => {
        const main = readFileSync(join(frontendSrc, 'logic/useMain.js'), 'utf8');
        expect(main).toMatch(/setStoredFeedLens\(\(prev\) => \(/);
        expect(main).toMatch(/prev\.lens === lens && prev\.teamId === teamId/);
    });

    it('keeps a picked lens for the tab, scoped to viewer and community', () => {
        sessionStorage.clear();
        const viewer = 'mirage1viewer';
        expect(readLensPick({ viewer, community: 'tech' })).toBeNull();

        writeLensPick({ viewer, community: 'tech', lens: LENS.RAW });
        expect(readLensPick({ viewer, community: 'tech' })).toEqual({ lens: LENS.RAW, teamId: null });
        expect(readLensPick({ viewer, community: 'other' })).toBeNull();
        expect(readLensPick({ viewer: 'mirage1other', community: 'tech' })).toBeNull();

        writeLensPick({ viewer, community: 'tech', lens: LENS.TEAM, teamId: 4 });
        expect(readLensPick({ viewer, community: 'tech' })).toEqual({ lens: LENS.TEAM, teamId: 4 });

        // Never the device: a pick that outlived the visit would keep overriding
        // the community's live default here, including a later curation team.
        expect(Object.keys(localStorage).filter((key) => key.startsWith('lens_pick_'))).toEqual([]);
        sessionStorage.clear();
        expect(readLensPick({ viewer, community: 'tech' })).toBeNull();

        writeLensPick({ viewer, community: 'tech', lens: LENS.TEAM, teamId: 4 });
        clearLensPick({ viewer, community: 'tech' });
        expect(readLensPick({ viewer, community: 'tech' })).toBeNull();
    });

    it('rejects an unusable pick instead of storing it', () => {
        sessionStorage.clear();
        expect(() => writeLensPick({ viewer: 'v', community: 'c', lens: 'sideways' })).toThrow('invalid lens');
        expect(() => writeLensPick({ viewer: 'v', community: 'c', lens: LENS.TEAM })).toThrow('team_id');
        expect(readLensPick({ viewer: 'v', community: 'c' })).toBeNull();
    });

    it('mounts the feed and the picker into the lens picked in this tab', () => {
        const main = readFileSync(join(frontendSrc, 'logic/useMain.js'), 'utf8');
        const picker = readFileSync(join(frontendSrc, 'themes/default/components/CurationLensPicker.js'), 'utf8');
        expect(main).toMatch(/const pick = readLensPick\(\{ viewer: viewerAddress, community \}\)/);
        expect(main).toMatch(/useState\(\(\) => initialLensFor\(urlCommunity\)\)/);
        expect(picker).toMatch(/useState\(\(\) => readStoredPick\(community\)\)/);
        expect(picker).toMatch(/if \(applyOnLoad\) writeLensPick\(/);
        // A thread picker follows the ?lens= in its URL, not the feed's pick.
        expect(picker).toMatch(/const readStoredPick = \(slug\) => \(applyOnLoad/);
    });

    it('does not refetch the feed when community detail concretizes effective', () => {
        const picker = readFileSync(join(frontendSrc, 'themes/default/components/CurationLensPicker.js'), 'utf8');
        const mainView = readFileSync(join(frontendSrc, 'themes/default/routes/MainView.js'), 'utf8');
        // Detail-load onChange is header-only (4th arg false). A user pick
        // still omits that arg so handleLensChange defaults syncFeed to true.
        expect(picker).toMatch(/onChange\?\.\(lens, rawTeamId \? Number\(rawTeamId\) : null, activeTeam, false\)/);
        expect(picker).toMatch(/onChange\?\.\(lens, teamId, null\);/);
        expect(mainView).toMatch(/\(lens, teamId, team, syncFeed = true\)/);
        expect(mainView).toMatch(/if \(syncFeed\) setFeedLens\(\{ lens, teamId \}\)/);
    });

    it('sends every picked lens per community on an aggregated feed', () => {
        sessionStorage.clear();
        const viewer = 'mirage1viewer';
        expect(lensPicksParam({ viewer })).toBe('');

        writeLensPick({ viewer, community: 'tech', lens: LENS.RAW });
        writeLensPick({ viewer, community: 'news', lens: LENS.TEAM, teamId: 4 });
        writeLensPick({ viewer: 'mirage1other', community: 'sports', lens: LENS.RAW });
        expect(lensPicksParam({ viewer })).toBe('news:team:4,tech:raw');
        expect(lensPicksParam({ viewer: 'mirage1other' })).toBe('sports:raw');

        clearLensPick({ viewer, community: 'news' });
        expect(lensPicksParam({ viewer })).toBe('tech:raw');
    });

    it('retains only the 20 most recent lens picks deterministically', () => {
        sessionStorage.clear();
        const viewer = 'mirage1viewer';
        for (let index = 0; index < 25; index += 1) {
            writeLensPick({ viewer, community: `community-${index}`, lens: LENS.RAW });
        }
        const picks = lensPicksParam({ viewer }).split(',');
        expect(LENS_PICKS_MAX).toBe(20);
        expect(picks).toHaveLength(20);
        for (let index = 0; index < 5; index += 1) {
            expect(readLensPick({ viewer, community: `community-${index}` })).toBeNull();
        }
        for (let index = 5; index < 25; index += 1) {
            expect(readLensPick({ viewer, community: `community-${index}` })).toEqual({
                lens: LENS.RAW,
                teamId: null,
            });
        }
        expect(picks).toEqual([...picks].sort());
    });

    it('keys the aggregated feed and its cold-start stash on the picks it sent', () => {
        const main = readFileSync(join(frontendSrc, 'logic/useMain.js'), 'utf8');
        // A home feed fetched under one set of picks must not be restored, or
        // painted from the launch payload, under another.
        expect(main).toMatch(/feedLensPicks \? `\|\$\{feedLensPicks\}` : ''/);
        expect(main).toMatch(/params\.lens_picks = feedLensPicks/);
        expect(main).toMatch(/feedLens\.lens === LENS\.EFFECTIVE && !feedLensPicks/);
    });

    it('requires a team ID only for the explicit team lens', () => {
        expect(normalizeLens('team', '3')).toEqual({ lens: 'team', teamId: 3 });
        expect(() => normalizeLens('team')).toThrow('team_id');
        expect(() => normalizeLens('raw', 3)).toThrow('only valid');
        expect(lensQuery('default')).toEqual({ lens: 'default', scope: 'current' });
    });

    it('reads the viewing team from a stamped post.lens', () => {
        expect(viewingTeamId({ lens: { effective_team_id: 7 } })).toBe(7);
        expect(viewingTeamId({ lens: { effective_mode: 2, effective_team_id: null } })).toBe(null);
        expect(viewingTeamId({})).toBe(null);
        expect(lensHintLabel({ effective_mode: 2 })).toBe('Uncensored');
        expect(lensHintLabel({ effective_mode: 0, effective_team_id: 3 })).toBe('Default');
        expect(lensHintLabel({ effective_mode: 1, effective_team_id: 3 })).toBe('Curation');
    });

    it('uses the global pending tuple contract', () => {
        expect(curationPendingKey('invite_curator', 'Tech', 2, 'MIRAGE1USER'))
            .toBe('invite_curator:tech:2:mirage1user');
    });
});

describe('community leave confirmation', () => {
    it('routes curator leave consequences through the registered dialog', async () => {
        const details = {
            community: 'tech',
            membership: { teamId: 2, teamName: 'Signal', memberCount: 1, isLeader: true },
        };
        const handler = vi.fn().mockResolvedValue(true);
        const unregister = registerCommunityLeaveConfirmationHandler(handler);
        await expect(requestCommunityLeaveConfirmation(details)).resolves.toBe(true);
        expect(handler).toHaveBeenCalledWith(details);
        unregister();
    });
});

describe('optimistic curation visibility', () => {
    it('retains bans across route consumers until an unban clears them', () => {
        const post = {
            post_id: 'post-1',
            user_id: 'mirage1author',
            community: 'tech',
            lens: { effective_team_id: 7 },
        };
        for (const [kind, target] of [['post', 'post-1'], ['user', 'mirage1author']]) {
            setOptimisticCurationVisibility({
                community: 'tech',
                teamId: 7,
                kind,
                target,
                hidden: true,
            });
            expect(isOptimisticallyCurationHidden(post)).toBe(true);
            setOptimisticCurationVisibility({
                community: 'tech',
                teamId: 7,
                kind,
                target,
                hidden: false,
            });
            expect(isOptimisticallyCurationHidden(post)).toBe(false);
        }
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
        expect(pickerSrc).toMatch(/return compact \? 'Default' : 'Default Curation Team'/);
        expect(pickerSrc).toMatch(/OptionMeta>Currently \{defaultTeamName\}/);
        // Rapid switches: only roll back the failed pick, never a newer one.
        expect(pickerSrc).toMatch(
            /setOptimisticSelection\(\(current\) => \{\s*if \(current !== selection\) return current;\s*clearLensPick\(\{ viewer: viewerAddr, community \}\);\s*return null;/,
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
        expect(pickerSrc).toMatch(/formatPinCount/);
        expect(pickerSrc).toMatch(/__team_action__/);
        expect(pickerSrc).toMatch(/Create new…/);
        expect(pickerSrc).toMatch(/Manage my team…/);
        expect(pickerSrc).toMatch(/teams\/new/);
        expect(pickerSrc).toMatch(/PickerButton/);
        expect(pickerSrc).toMatch(/height: var\(--community-header-control-height, 28px\)/);
        expect(pickerSrc).toMatch(/font-size: var\(--community-header-control-font-size, 0\.68rem\)/);
        expect(pickerSrc).toMatch(/role="listbox"/);
        expect(pickerSrc).toMatch(/onChange\?\.\(lens, rawTeamId \? Number\(rawTeamId\) : null, activeTeam, false\)/);
        expect(pickerSrc).not.toMatch(/styled\.select/);
        expect(pickerSrc).toMatch(/>Uncensored</);
        // LIVE_DEFAULT stays Default — do not present the most-subscribed team as selected.
        expect(pickerSrc).not.toMatch(/teamIdWithMostSubscribers/);
        expect(pickerSrc).not.toMatch(/No explicit pin/);
        expect(pickerSrc).toMatch(/useViewerCuratorMembership\(community, \{ enabled: hooksEnabled \}\)/);
        expect(pickerSrc).not.toMatch(/ManageLink/);
        expect(pickerSrc).not.toMatch(/Curator teams/);
    });

    it('reuses the curator-communities list instead of one /teams fetch per feed row', () => {
        const membership = readFileSync(
            join(frontendSrc, 'logic/useViewerCuratorMembership.js'),
            'utf8',
        );
        expect(membership).toMatch(/function rememberCuratorList/);
        expect(membership).toMatch(/function membershipFromCuratorList/);
        expect(membership).toMatch(/Array\.isArray\(data\.memberships\)/);
        expect(membership).toMatch(/curatorListInflight/);
        expect(membership).toMatch(/`curators\/\$\{encodeURIComponent\(viewer\)\}\/communities`,\s*\{ viewer, \.\.\.proof \}/);
        expect(membership).toMatch(/enabled: enabledOption = true/);
    });

    it('does not keep topic or agent routes as compatibility redirects', () => {
        const appSrc = readFileSync(join(frontendSrc, 'App.js'), 'utf8');
        expect(appSrc).not.toMatch(/path="\/t\//);
        expect(appSrc).not.toMatch(/path="\/topics"/);
        expect(appSrc).not.toMatch(/path="\/agents"/);
        expect(appSrc).not.toMatch(/TopicToCommunityRedirect/);

        const handler = readFileSync(join(frontendSrc, 'utils/TransactionHandler.js'), 'utf8');
        expect(handler).not.toMatch(/followTopic/);
        expect(handler).not.toMatch(/unfollowTopic/);
        expect(handler).not.toMatch(/blockTopic/);
        expect(handler).not.toMatch(/unblockTopic/);
        expect(handler).not.toMatch(/MsgFollowTopic/);
        expect(handler).not.toMatch(/MsgUnfollowTopic/);

        const txApi = readFileSync(join(frontendSrc, 'utils/tx.js'), 'utf8');
        expect(txApi).not.toMatch(/followTopic/);
        expect(txApi).not.toMatch(/unfollowTopic/);
        expect(txApi).not.toMatch(/function blockTopic/);
        expect(txApi).not.toMatch(/function unblockTopic/);

        const subscriptions = readFileSync(join(frontendSrc, 'utils/Subscriptions.js'), 'utf8');
        expect(subscriptions).toMatch(/export async function joinCommunity/);
        expect(subscriptions).toMatch(/export async function leaveCommunity/);
        expect(subscriptions).not.toMatch(/export async function subscribe\(/);
        expect(subscriptions).not.toMatch(/export const followTopic/);
        expect(subscriptions).not.toMatch(/export const unfollowTopic/);

        const aasa = readFileSync(
            join(here, '../../public/.well-known/apple-app-site-association'),
            'utf8',
        );
        expect(aasa).toMatch(/\/c\/\*/);
        expect(aasa).toMatch(/\/communities/);
        expect(aasa).not.toMatch(/\/t\/\*/);
        expect(aasa).not.toMatch(/\/topics/);
        expect(aasa).not.toMatch(/\/agents/);
        expect(aasa).not.toMatch(/\/referrals/);
    });

    it('redirects the obsolete team listing route to the community', () => {
        const appSrc = readFileSync(join(frontendSrc, 'App.js'), 'utf8');
        expect(appSrc).toMatch(/path="\/c\/:community\/teams"/);
        expect(appSrc).toMatch(/element=\{<CommunityTeamsRedirect \/>}/);
    });

    it('explains that curation counts are explicit user pins', () => {
        expect(formatSubscriberCount(0)).toBe('0 users pinned');
        expect(formatSubscriberCount(1)).toBe('1 user pinned');
        expect(formatSubscriberCount(2)).toBe('2 users pinned');
        expect(formatPinCount(0)).toBe('0 pins');
        expect(formatPinCount(1)).toBe('1 pin');
        expect(formatPinCount(2)).toBe('2 pins');
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

    it('validates team names at every boundary', () => {
        expect(requireCurationTeamName('A')).toBe('A');
        expect(requireCurationTeamName('Signal Desk_2')).toBe('Signal Desk_2');
        expect(requireCurationTeamName('a'.repeat(30))).toBe('a'.repeat(30));
        for (const invalid of ['', '   ', ' leading', 'trailing ', 'a'.repeat(31), 'bad!', 'tëam', '-team']) {
            expect(() => requireCurationTeamName(invalid)).toThrow();
        }
    });

    it('allows optional descriptions, trims whitespace, and rejects rune overflow', () => {
        expect(requireCurationTeamDescription('')).toBe('');
        expect(requireCurationTeamDescription('🙂'.repeat(800))).toBe('🙂'.repeat(800));
        expect(requireCurationTeamDescription('   ')).toBe('');
        expect(requireCurationTeamDescription(' leading')).toBe('leading');
        expect(requireCurationTeamDescription('trailing\n')).toBe('trailing');
        // The limit applies after trimming, matching the chain.
        expect(requireCurationTeamDescription(` ${'x'.repeat(800)} `)).toBe('x'.repeat(800));
        for (const invalid of ['x'.repeat(801), '🙂'.repeat(801)]) {
            expect(() => requireCurationTeamDescription(invalid)).toThrow();
        }
    });

    it('passes return paths through Sign in and Subscribe on the team creation page', () => {
        const teams = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamsView.js'),
            'utf8',
        );
        expect(teams).toMatch(/withReturnTo\('\/login'/);
        expect(teams).toMatch(/withReturnTo\('\/subscription'/);
        // Banned users are team-scoped — only on the team detail page.
        expect(teams).not.toMatch(/#hidden-users/);
        expect(teams).not.toMatch(/Banned users/);
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

    it('keeps New team title on eligibility failure and does not treat fetch errors as subscribe', () => {
        const teams = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamsView.js'),
            'utf8',
        );
        expect(teams).toMatch(/eligibility_error/);
        expect(teams).toMatch(/retryEligibility/);
        expect(teams).toMatch(/Leave eligible null/);
        expect(teams).toMatch(/subscribe: 'New team'/);
        expect(teams).not.toMatch(/subscribe: 'Subscribe'/);
        expect(teams).not.toMatch(/setEligible\(false\);\s*setError\(message\)/);
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
        expect(main).toMatch(/CommunityMembershipButton/);
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
        expect(main).toMatch(/const feedTitle = urlCommunity === 'all' \? 'All' : null/);
        expect(main).not.toMatch(/else if \(isCommunityFeed\) feedTitle = communityLabel/);
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
        expect(curation).toMatch(/you might get banned from our curation team/);
        expect(create).not.toMatch(/About this lens/);
        expect(create).toMatch(/MAX_CURATION_TEAM_NAME_LENGTH/);
        expect(create).toMatch(/MAX_CURATION_TEAM_DESCRIPTION_LENGTH/);
        expect(create).toMatch(/maxLength=\{maxTeamNameLength\}/);
        expect(create).toMatch(/maxLength=\{maxTeamDescriptionLength \* 2\}/);
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
        expect(detail).toMatch(/maxLength=\{maxTeamDescriptionLength \* 2\}/);
        expect(detail).toMatch(/resolveUserIdentity/);
        expect(detail).toMatch(/Username or mirage1/);
        expect(detail).toMatch(/formatUserLabel/);
        expect(detail).toMatch(/formatSubscriberCount/);
        expect(detail).not.toMatch(/Node default/);
        expect(detail).not.toMatch(/placeholder="mirage1…"/);
        // Ban/lock still live on the post shield, not a team-page target form.
        expect(detail).not.toMatch(/Moderation tools/);
        expect(detail).not.toMatch(/moderationTarget/);
        expect(detail).not.toMatch(/Ban post/);
        expect(detail).not.toMatch(/Lock thread/);
        expect(detail).toMatch(/Banned users/);
        expect(detail).toMatch(/Banned posts/);
        expect(detail).toMatch(/hidden-users/);
        expect(detail).toMatch(/hidden-posts/);
        expect(detail).toMatch(/Overview[\s\S]*Curators[\s\S]*Banned posts[\s\S]*Banned users/);
        expect(detail).toMatch(/role="tablist" aria-label="Curator team sections"/);
        expect(detail).toMatch(/activeTab === 'overview'/);
        expect(detail).toMatch(/activeTab === 'curators'/);
        expect(detail).toMatch(/activeTab === 'banned-posts'/);
        expect(detail).toMatch(/activeTab === 'banned-users'/);
        expect(detail).toMatch(/enabled: isCurator && activeTab === 'banned-posts'/);
        expect(detail).toMatch(/enabled: isCurator && activeTab === 'banned-users'/);
        expect(detail.indexOf('CardTitle>Danger zone')).toBeGreaterThan(detail.indexOf('Card id="hidden-posts"'));
        expect(detail).toMatch(/useHiddenCurationUsers/);
        expect(detail).toMatch(/useHiddenCurationPosts/);
        expect(detail).toMatch(/moderateCurationUser/);
        expect(detail).toMatch(/moderateCurationPost/);
        expect(detail).toMatch(/list\.removeOptimistically\(item\)/);
        expect(detail).toMatch(/list\.restoreOptimistically\(item\)/);
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
        expect(teamsHook).toMatch(/optimisticallyRemovedRef/);
        expect(teamsHook).toMatch(/removeOptimistically/);
        expect(teamsHook).toMatch(/restoreOptimistically/);
        const curationUtils = readFileSync(
            join(frontendSrc, 'utils/curation.js'),
            'utf8',
        );
        expect(curationUtils).toMatch(/HIDDEN_LIST_INITIAL = 10/);
        expect(curationUtils).toMatch(/HIDDEN_LIST_MORE = 50/);
    });

    it('builds community membership as one shared direct-action button', () => {
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

        const membership = readFileSync(
            join(frontendSrc, 'themes/default/components/CommunityMembershipButton.js'),
            'utf8',
        );
        const viewPost = readFileSync(
            join(frontendSrc, 'themes/default/routes/ViewPostView.js'),
            'utf8',
        );
        expect(control).toMatch(/height: 28px/);
        expect(control).toMatch(/font-size: 0\.68rem/);
        expect(control).toMatch(/font-weight: 400/);
        expect(listFeed).toMatch(/import CtrlButton from "\.\/components\/FeedControlButton"/);
        expect(listFeed).not.toMatch(/const CtrlButton = styled\.button/);
        expect(picker).toMatch(/styled\(FeedControlButton\)/);
        expect(picker).toMatch(/const PickerRoot = styled\.div`[^`]*display: inline-flex;[^`]*align-items: center;/);
        expect(picker).not.toMatch(/variant="secondary"/);
        expect(membership).toMatch(/function CommunityMembershipButton/);
        expect(membership).toMatch(/MembershipLabel/);
        expect(membership).toMatch(/<MembershipLabel>\s*<span>Joined\{suffix\}<\/span>\s*<span>Leave\{suffix\}<\/span>/);
        expect(membership).toMatch(/\) : \(\s*<span>Join\{suffix\}<\/span>/);
        expect(membership).not.toMatch(/<span>Join\{suffix\}<\/span>\s*<span>Joined\{suffix\}<\/span>/);
        expect(membership).toMatch(/buttonDangerBg/);
        expect(membership).not.toMatch(/aria-haspopup/);
        expect(main).toMatch(/import CommunityMembershipButton/);
        expect(viewPost).toMatch(/import CommunityMembershipButton/);
        expect(viewPost).not.toMatch(/const CommunityFollowButton/);
        // Membership, lens, sort and view controls stay together on the right.
        expect(main).toMatch(
            /CommunityMembershipButton[\s\S]*CurationLensPicker[\s\S]*FeedSortToggle[\s\S]*FeedViewToggle/,
        );

        // Default stays a fixed label; pinned teams keep their full name.
        expect(picker).not.toMatch(/max-width: 14rem/);
        expect(picker).toMatch(/return compact \? 'Default' : 'Default Curation Team'/);
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

    it('puts admin delete on the ⋯ menu and curator tools on BlockChip', () => {
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
        const curationVisibility = readFileSync(
            join(frontendSrc, 'utils/curationVisibility.js'),
            'utf8',
        );
        const mainView = readFileSync(
            join(frontendSrc, 'themes/default/routes/MainView.js'),
            'utf8',
        );
        const membership = readFileSync(
            join(frontendSrc, 'logic/useViewerCuratorMembership.js'),
            'utf8',
        );

        expect(postMenu).not.toMatch(/export function ModMenuChip/);
        expect(postMenu).toMatch(/export function MoreMenuChip/);
        expect(postMenu).toMatch(/export function BlockChip/);
        expect(postMenu).toMatch(/Delete network wide/);
        expect(postMenu).toMatch(/isAdminVisible && \(/);
        expect(postMenu).toMatch(/curateVisible/);
        expect(postMenu).toMatch(/Report post/);
        expect(postMenu).toMatch(/HiOutlineShieldExclamation/);
        expect(postMenu).toMatch(/CurateMenuItems/);
        expect(postMenu).not.toMatch(/MenuHeader>Admin</);
        expect(postMenu).not.toMatch(/renderHeader/);
        for (const src of [cardView, viewPost, listFeed]) {
            expect(src).not.toMatch(/ModMenuChip/);
        }
        expect(cardView).toMatch(/Delete network wide/);
        expect(viewPost).toMatch(/Delete network wide/);
        expect(listFeed).toMatch(/MoreMenuChip/);
        expect(cardView).toMatch(/BlockChip/);
        expect(viewPost).toMatch(/BlockChip/);
        expect(listFeed).toMatch(/BlockChip/);
        expect(curateItems).not.toMatch(/Curate · /);
        expect(postMenu).toMatch(/usePostCurateActions\(post, \{ active: open, updatePost \}\)/);
        expect(postMenu).toMatch(/open=\{!!curationConfirmation\}/);
        expect(postMenu).toMatch(/onConfirm=\{openCurationConfirmation\}/);
        expect(curateItems).toMatch(/confirmation requested/);
        expect(actions).toMatch(/title: 'Ban this post\?'/);
        expect(actions).toMatch(/title: 'Ban this user\?'/);
        expect(actions).toMatch(/viewingAsCuratorTeam/);
        expect(actions).toMatch(/viewingTeamId === teamId/);
        expect(actions).toMatch(/const isOwnContent = !!author && author === viewer/);
        expect(actions).toMatch(/isCurator && !isOwnContent/);
        expect(postMenu).toMatch(/String\(authorAddress\)\.toLowerCase\(\) === String\(viewerAddress\)\.toLowerCase\(\)/);
        expect(postMenu).toMatch(/if \(isOwnPost && !curateVisible\) return null/);
        expect(cardView).toMatch(/PostLensPicker/);
        expect(viewPost).toMatch(/PostLensPicker/);
        expect(listFeed).toMatch(/PostLensPicker/);
        expect(cardView).toMatch(/showPostLens && <PostLensPicker/);
        expect(listFeed).toMatch(/showPostLens && <PostLensPicker/);
        expect(cardView).toMatch(/showPostLens = false/);
        expect(listFeed).toMatch(/showPostLens = false/);
        expect(mainView).toMatch(/showPostLens=\{false\}/);
        expect(viewPost).toMatch(/<CommunityHeroMobileActions>[\s\S]*CommunityMembershipButton[\s\S]*renderHeaderLensPicker\(displayCommunity\)/);
        expect(viewPost).toMatch(/<CommunityAction>[\s\S]*CommunityMembershipButton[\s\S]*renderHeaderLensPicker\(displayCommunity\)/);
        expect(viewPost).toMatch(/<MobileRootMetaMenu>\s*\{renderPostMenu\(post\)\}/);
        expect(viewPost).toMatch(/<MetaInfoRowRight>\s*\{renderPostMenu\(post\)\}/);
        expect(viewPost).toMatch(/handleThreadLensChange/);
        const pickerSrc = readFileSync(
            join(frontendSrc, 'themes/default/components/CurationLensPicker.js'),
            'utf8',
        );
        expect(pickerSrc).toMatch(/export function PostLensPicker/);
        expect(pickerSrc).toMatch(/compact/);
        expect(pickerSrc).toMatch(/lazy/);
        expect(pickerSrc).toMatch(/applyOnLoad=\{false\}/);
        expect(pickerSrc).toMatch(/if \(!applyOnLoad\) return;/);
        expect(pickerSrc).toMatch(/if \(!activated \|\| !detail \|\| detailLoading \|\| teamsLoading\) return;/);
        expect(pickerSrc).toMatch(/onChange\?\.\(lens, teamId, null\);/);
        const viewPostLogic = readFileSync(
            join(frontendSrc, 'logic/useViewPost.js'),
            'utf8',
        );
        expect(viewPostLogic).toMatch(/loadedPostIdRef/);
        expect(viewPostLogic).toMatch(/lens refetch in place/);
        expect(actions).toMatch(/moderateCurationUser/);
        expect(actions).toMatch(/setCurationThreadLocked/);
        expect(actions).toMatch(/\/moderation/);
        expect(actions).toMatch(/modState\.postHidden/);
        expect(actions).toMatch(/modState\.userHidden/);
        expect(actions).toMatch(/modState\.threadLocked/);
        expect(actions).toMatch(/Ban post/);
        expect(actions).toMatch(/Unban post/);
        expect(actions).toMatch(/Ban user/);
        expect(actions).toMatch(/Unban user/);
        expect(actions).toMatch(/setOptimisticCurationVisibility/);
        expect(curationVisibility).toMatch(/curationModerationOptimistic/);
        expect(curationVisibility).toMatch(/const hiddenPosts = new Set\(\)/);
        expect(curationVisibility).toMatch(/const hiddenUsers = new Set\(\)/);
        expect(actions).toMatch(/applyDisplayedVisibility\('post', postId, optimistic\.postHidden\)/);
        expect(actions).toMatch(/applyDisplayedVisibility\('user', author, optimistic\.userHidden\)/);
        expect(mainView).toMatch(/window\.addEventListener\('curationModerationOptimistic'/);
        expect(mainView).toMatch(/if \(isOptimisticallyCurationHidden\(p\)\) return false;/);
        expect(viewPost).toMatch(/window\.addEventListener\('curationModerationOptimistic'/);
        expect(viewPost).toMatch(/&& !isOptimisticallyCurationHidden\(p\)/);
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
        expect(sidebar).toMatch(/orderedCommunities/);
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
        expect(teamDetail).toMatch(/Unban/);
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
        expect(viewPost).toMatch(/const threadLocked = stateLock !== undefined \? !!stateLock : !!root\?\.thread_locked;/);
        expect(viewPost).toMatch(/threadLocked \? <LockedNote/);
        expect(viewPost).toMatch(/thread locked</);
        expect(viewPost).toMatch(/ThreadLockMark/);
        // A composer already open when the lock lands must close, but editing
        // your own existing post is not a new reply and stays allowed.
        expect(viewPost).toMatch(/if \(threadLocked && !isEdit\) return <div><\/div>;/);
        expect(viewPost).toMatch(/if \(!isMobile \|\| threadLocked\) return null;/);

        const cardView = readFileSync(
            join(frontendSrc, 'themes/default/components/CardView.js'),
            'utf8',
        );
        const listFeed = readFileSync(
            join(frontendSrc, 'themes/default/ListFeedView.js'),
            'utf8',
        );
        expect(cardView).toMatch(/ThreadLockMark/);
        expect(cardView).toMatch(/safePost\.thread_locked/);
        expect(listFeed).toMatch(/ThreadLockMark/);
        expect(listFeed).toMatch(/post\.thread_locked/);
    });

    it('keeps a post lens across reloads without resurrecting filtered replies', () => {
        const viewPost = readFileSync(
            join(frontendSrc, 'themes/default/routes/ViewPostView.js'),
            'utf8',
        );
        const picker = readFileSync(
            join(frontendSrc, 'themes/default/components/CurationLensPicker.js'),
            'utf8',
        );
        const viewPostLogic = readFileSync(
            join(frontendSrc, 'logic/useViewPost.js'),
            'utf8',
        );

        expect(viewPost).toMatch(/useSearchParams/);
        expect(viewPost).toMatch(/params\.set\('lens', next\.lens\)/);
        expect(viewPost).toMatch(/const MIN_CONTINUE_THREAD_LEVEL = 4/);
        expect(viewPost).toMatch(/displayLevel < MIN_CONTINUE_THREAD_LEVEL/);
        expect(picker).toMatch(/pickRequestedSelection\(hintLens\)/);
        expect(viewPostLogic).toMatch(/!keepContent && lens === LENS\.EFFECTIVE/);
        expect(viewPostLogic).not.toMatch(/state\.posts\[node\.post_id\]\.children/);
    });

    it('gives the owner a community tag control and every curator a per-post override', () => {
        const teamDetail = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamView.js'),
            'utf8',
        );
        const actions = readFileSync(join(frontendSrc, 'logic/usePostCurateActions.js'), 'utf8');
        const postMenu = readFileSync(join(frontendSrc, 'themes/default/components/PostMenu.js'), 'utf8');
        const app = readFileSync(join(frontendSrc, 'App.js'), 'utf8');

        // Community tag lives on the owner-only settings page, next to the
        // other team-wide switch, and reuses the composer's tag vocabulary.
        expect(teamDetail).toMatch(/Community tag/);
        expect(teamDetail).toMatch(/tx\.setCurationTag\(community, Number\(teamId\), next\)/);
        expect(teamDetail).toMatch(/optimistic community tag/);
        expect(teamDetail).toMatch(/community tag reverted/);
        expect(teamDetail).toMatch(/TAG_OPTIONS/);

        // Per-post override is one select, not one row per tag, and keeps
        // "no override" distinct from "untagged".
        expect(actions).toMatch(/setCurationPostTag/);
        expect(actions).toMatch(/const INHERIT_TAG = '__inherit__'/);
        expect(actions).toMatch(/No override/);
        expect(actions).toMatch(/Untagged/);
        expect(actions).toMatch(/fetchedTag = typeof data\.post_tag === 'string' \? data\.post_tag : null/);
        expect(actions).toMatch(/modState\.postTag === null \? INHERIT_TAG : modState\.postTag/);
        expect(actions).toMatch(/optimistic apply/);
        expect(actions).toMatch(/optimistic revert/);
        expect(actions).toMatch(/_optimisticTag/);
        expect(actions).toMatch(/applyDisplayedLock/);
        expect(actions).toMatch(/_optimisticLock/);
        expect(postMenu).toMatch(/item\.type === 'select'/);
        expect(postMenu).toMatch(/MenuSelect/);
        expect(postMenu).toMatch(/usePostCurateActions\(post, \{ active: open, updatePost \}\)/);
        expect(app).toMatch(/existing\._optimisticTag !== undefined/);
        expect(app).toMatch(/existing\._optimisticLock !== undefined/);
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
            .mockImplementation((type, _handler) => {
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

    it('warns before every curator community leave path', () => {
        const subscriptions = readFileSync(join(frontendSrc, 'utils/Subscriptions.js'), 'utf8');
        const app = readFileSync(join(frontendSrc, 'App.js'), 'utf8');
        const follows = readFileSync(join(frontendSrc, 'logic/useFollows.js'), 'utf8');

        expect(subscriptions).toMatch(/fetchViewerCuratorMembership\(lower, address, \{ fresh: true \}\)/);
        expect(subscriptions).toMatch(/requestCommunityLeaveConfirmation/);
        expect(app).toMatch(/<CommunityLeaveConfirmation \/>/);
        expect(follows).toMatch(/await leaveCommunity\(address, communityTrimmed\)/);
        expect(follows).not.toMatch(/tx\.leaveCommunity/);
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
        const communitiesAt = teamsView.indexOf('notifyJoinedCommunitiesUpdated({ added: nextSlug })');
        expect(waitAt).toBeGreaterThan(-1);
        expect(invalidateAt).toBeGreaterThan(waitAt);
        expect(communitiesAt).toBeGreaterThan(invalidateAt);
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

describe('curator invite UX', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    it('writes invite hero copy with the team and inviter', () => {
        expect(curatorInviteHeroCopy({
            community: 'crypto',
            name: 'Crypto Team',
            inviterUsername: 'God',
            inviter: 'mirage1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        })).toEqual({
            title: "You're invited to curate [crypto]",
            body: '@God invited you to join Crypto Team. Accept to start shaping what subscribers see.',
        });
    });

    it('returns the invitation once the invitee appears as pending', async () => {
        const sleep = vi.fn(async () => { });
        const get = vi.spyOn(Api, 'get')
            .mockResolvedValueOnce({ items: [] })
            .mockResolvedValueOnce({
                items: [{ invitee: 'mirage1invitee', status: 0 }],
            });

        const found = await waitForCurationInvite('crypto', 3, 'MIRAGE1INVITEE', {
            viewer: 'mirage1owner',
            interval: 10,
            maxAttempts: 5,
            sleep,
        });

        expect(found.status).toBe(0);
        expect(get).toHaveBeenCalledTimes(2);
        expect(sleep).toHaveBeenCalledTimes(1);
    });

    it('optimistically lists the invite and surfaces it on the home feed', () => {
        const teamView = readFileSync(
            join(frontendSrc, 'themes/default/routes/CurationTeamView.js'),
            'utf8',
        );
        const mainView = readFileSync(
            join(frontendSrc, 'themes/default/routes/MainView.js'),
            'utf8',
        );
        expect(teamView).toMatch(/setOptimisticInvites/);
        expect(teamView).toMatch(/waitForCurationInvite/);
        expect(mainView).toMatch(/<CuratorInviteHero \/>/);
    });
});

describe('community composer context', () => {
    it('preserves canonical internal hyphens', () => {
        expect(sanitizeCommunitySlug(' Foo-Bar ')).toBe('foo-bar');
        expect(isValidCommunitySlug('foo-bar', 2, 50)).toBe(true);
        expect(isValidCommunitySlug('foo--bar', 2, 50)).toBe(false);
    });

    it('carries a /c/ slug into the mobile create link', () => {
        const community = communityFromPathname('/c/foo-bar');
        expect(community).toBe('foo-bar');
        expect(createPostPathForContext(true, community)).toBe('/create_post?community=foo-bar');
        expect(createPostPathForContext(false, community)).toBe('/create_post');
        expect(communityFromPathname('/home')).toBe('');
        expect(communityFromPathname('/c/all')).toBe('');
        expect(createPostPathForContext(true, 'home')).toBe('/create_post');
    });

    it('lists curator communities before other joined ones', () => {
        expect(splitJoinedCommunitiesForComposer(
            ['joined-a', 'curated-one', 'joined-b'],
            ['curated-one', 'curated-two'],
        )).toEqual({
            curated: ['curated-one', 'curated-two'],
            joined: ['joined-a', 'joined-b'],
        });
        expect(splitJoinedCommunitiesForComposer(['alpha', 'beta'], [])).toEqual({
            curated: [],
            joined: ['alpha', 'beta'],
        });
        expect(splitJoinedCommunitiesForComposer(['alpha', 'alpha'], ['alpha', 'home'])).toEqual({
            curated: ['alpha'],
            joined: [],
        });
    });

    it('turns [slug] in running text into community mentions', () => {
        expect(splitCommunityMentions(
            'Unmoderated at the moment. Direct all your Mirage related feedback to the [mirage] community.',
        )).toEqual([
            { type: 'text', value: 'Unmoderated at the moment. Direct all your Mirage related feedback to the ' },
            { type: 'community', slug: 'mirage' },
            { type: 'text', value: ' community.' },
        ]);
        expect(splitCommunityMentions('see [foo-bar] and c/baz plus [keep](https://example.com)')).toEqual([
            { type: 'text', value: 'see ' },
            { type: 'community', slug: 'foo-bar' },
            { type: 'text', value: ' and ' },
            { type: 'community', slug: 'baz' },
            { type: 'text', value: ' plus [keep](https://example.com)' },
        ]);
        expect(splitCommunityMentions('[home] stays plain')).toEqual([
            { type: 'text', value: '[home] stays plain' },
        ]);
    });
});

describe('signed authenticated reads', () => {
    it('uses stable feed and curator payload actions', () => {
        expect(signedReadPayload(FEED_READ_ACTION, 'MIRAGE1VIEWER', 123, 7))
            .toBe('get_posts:mirage1viewer:123:7');
        expect(signedReadPayload(CURATOR_READ_ACTION, 'mirage1viewer', 456, 8))
            .toBe('curator_read:mirage1viewer:456:8');
    });
});

describe('creator reward claims', () => {
    it('deduplicates and sorts epoch IDs', () => {
        expect(normalizeClaimEpochs([9, 3, 9, 5], 10)).toEqual([3, 5, 9]);
    });

    it('rejects empty and oversized batches', () => {
        expect(() => normalizeClaimEpochs([], 4)).toThrow('at least one');
        expect(() => normalizeClaimEpochs([1, 2, 3], 2)).toThrow('at most 2');
    });

    it('does not throw when selecting beyond a lowered governance cap', () => {
        expect(nextClaimSelection([1, 2], 3, 2)).toEqual({ selected: [1, 2], atCap: true });
        expect(nextClaimSelection([1, 2], 2, 2)).toEqual({ selected: [1], atCap: false });
    });

    it('surfaces CheckTx failure before settlement polling', () => {
        expect(() => requireCreatorClaimCheckTx({
            success: false,
            error_code: 'transaction_rejected',
            error_details: { message: 'invalid claim' },
        })).toThrow();
    });

    it('uses the configured creator reward interval', () => {
        const now = Date.UTC(2026, 7, 27, 23, 59, 59);
        expect(currentCreatorEpoch(86400, now)).toBe(20692);
        expect(currentCreatorEpoch(300, now)).toBe(5959583);
        expect(currentCreatorEpoch(300, now, 19676, Math.floor(now / 1000))).toBe(19676);
        expect(currentCreatorEpoch(300, now + 300000, 19676, Math.floor(now / 1000))).toBe(19677);
    });

    it('uses the API deadline timestamp for claimability', () => {
        const item = {
            earned: '100',
            claimed: '0',
            claimed_height: null,
            claim_deadline_unix: 1800,
        };
        expect(isCreatorEarningClaimable(item, 1799999)).toBe(true);
        expect(isCreatorEarningClaimable(item, 1800000)).toBe(false);
    });

    it('shows UTC time for sub-daily creator rewards', () => {
        const unix = Date.UTC(2026, 7, 27, 12, 5, 0) / 1000;
        expect(formatCreatorRewardTime(unix, 300)).toMatch(/12:05.*UTC/);
        expect(formatCreatorRewardTime(unix, 86400)).not.toMatch(/12:05/);
    });

    it('pages through claimable earnings oldest-deadline-first', async () => {
        const base = {
            creator_epoch_seconds: 21600,
            origin_epoch: 10,
            origin_unix: 100,
            max_creator_claim_epochs: 3,
        };
        const row = (epoch) => ({
            epoch_id: epoch,
            earned: '100',
            claimed: '0',
            epoch_start_unix: epoch * 100,
            epoch_end_unix: epoch * 100 + 50,
            claim_deadline_unix: epoch * 100 + 500,
            claimed_height: null,
            posts: [],
        });
        const get = vi.spyOn(Api, 'get')
            .mockResolvedValueOnce({ ...base, items: [row(1)], has_more: true, next_cursor: 'next' })
            .mockResolvedValueOnce({ ...base, items: [row(2)], has_more: false, next_cursor: null });

        const result = await fetchCreatorEarningsPages('mirage1creator', { claimableOnly: true });

        expect(result.items.map((item) => item.epoch_id)).toEqual([1, 2]);
        expect(get.mock.calls[0][1]).toMatchObject({
            claimable_only: true,
            sort: 'claim_deadline_asc',
        });
        expect(get.mock.calls[1][1].cursor).toBe('next');
        get.mockRestore();
    });

    it('waits for DeliverTx and indexed claimed_height', async () => {
        const pollTxStatus = vi.fn().mockResolvedValue({ success: true, indexed: false });
        const fetchEarnings = vi.fn()
            .mockResolvedValueOnce({ items: [{ epoch_id: 4, claimed_height: null }] })
            .mockResolvedValueOnce({ items: [{ epoch_id: 4, claimed_height: 99 }] });
        const sleep = vi.fn().mockResolvedValue(undefined);

        await expect(waitForCreatorClaim({
            epochIds: [4],
            txHash: 'abc',
            creator: 'mirage1creator',
            pollTxStatus,
            fetchEarnings,
            sleep,
        })).resolves.toEqual([{ epoch_id: 4, claimed_height: 99 }]);
        expect(pollTxStatus).toHaveBeenCalledWith('abc', expect.objectContaining({ requireIndexed: false }));
        expect(fetchEarnings).toHaveBeenCalledTimes(2);
    });

    it('surfaces DeliverTx rejection before claiming financial success', async () => {
        const fetchEarnings = vi.fn();
        await expect(waitForCreatorClaim({
            epochIds: [4],
            txHash: 'abc',
            creator: 'mirage1creator',
            pollTxStatus: vi.fn().mockResolvedValue({
                success: false,
                error_details: { message: 'claim window closed' },
            }),
            fetchEarnings,
        })).rejects.toThrow('claim window closed');
        expect(fetchEarnings).not.toHaveBeenCalled();
    });

    it('surfaces indexer query failure so the claim can be retried', async () => {
        await expect(waitForCreatorClaim({
            epochIds: [4],
            txHash: 'abc',
            creator: 'mirage1creator',
            pollTxStatus: vi.fn().mockResolvedValue({ success: true }),
            fetchEarnings: vi.fn().mockRejectedValue(new Error('indexer unavailable')),
        })).rejects.toThrow('indexer unavailable');
    });

    it('times out when claimed_height is not indexed', async () => {
        let time = 0;
        await expect(waitForCreatorClaim({
            epochIds: [4],
            txHash: 'abc',
            creator: 'mirage1creator',
            pollTxStatus: vi.fn().mockResolvedValue({ success: true }),
            fetchEarnings: vi.fn().mockResolvedValue({
                items: [{ epoch_id: 4, claimed_height: null }],
            }),
            now: () => time,
            sleep: async (ms) => { time += ms; },
            settleTimeoutMs: 2,
            settleIntervalMs: 1,
        })).rejects.toThrow('indexing timed out');
    });

    it('allows a successful retry after a projection failure', async () => {
        const options = {
            epochIds: [4],
            txHash: 'abc',
            creator: 'mirage1creator',
            pollTxStatus: vi.fn().mockResolvedValue({ success: true }),
        };
        await expect(waitForCreatorClaim({
            ...options,
            fetchEarnings: vi.fn().mockRejectedValue(new Error('temporary indexer failure')),
        })).rejects.toThrow('temporary indexer failure');
        await expect(waitForCreatorClaim({
            ...options,
            fetchEarnings: vi.fn().mockResolvedValue({
                items: [{ epoch_id: 4, claimed_height: 101 }],
            }),
        })).resolves.toEqual([{ epoch_id: 4, claimed_height: 101 }]);
    });
});

describe('retired runtime source guards', () => {
    it('keeps compatibility code while removing live retired-feature branches', () => {
        const handler = readFileSync(join(frontendSrc, 'utils/TransactionHandler.js'), 'utf8');
        const app = readFileSync(join(frontendSrc, 'App.js'), 'utf8');
        const index = readFileSync(join(frontendSrc, 'index.js'), 'utf8');
        const profile = readFileSync(join(frontendSrc, 'logic/useProfile.js'), 'utf8');
        const subscription = readFileSync(join(frontendSrc, 'logic/useSubscription.js'), 'utf8');
        const postGifts = readFileSync(join(frontendSrc, 'logic/usePostGifts.js'), 'utf8');
        const viewPost = readFileSync(join(frontendSrc, 'logic/useViewPost.js'), 'utf8');
        const main = readFileSync(join(frontendSrc, 'logic/useMain.js'), 'utf8');
        const themesReadme = readFileSync(join(frontendSrc, 'themes/README.md'), 'utf8');

        expect(handler).not.toContain('questActionCompleted');
        expect(handler).not.toMatch(/targetLevel\s*===\s*10/);
        expect(app).not.toContain('bootstrap_rewards_summary');
        expect(profile).not.toMatch(/reserveFunds|reserveDisplay|agentFee/);
        expect(subscription).not.toMatch(/reserveFunds|setReserveFunds/);
        expect(postGifts).not.toMatch(/agentFee/);
        expect(viewPost).not.toMatch(/agentFee/);
        expect(themesReadme).not.toMatch(/bluemoon|oldreddit|onyx/i);

        expect(index).toContain('Storage.migrateRenamedKeys()');
        expect(handler).toContain('(protocol_version == null ? 1 : protocol_version)');
        expect(viewPost).toContain("target.startsWith('/t/') || target === '/topics' || target === '/agents'");
        expect(main).toMatch(/signReadParams\(FEED_READ_ACTION, viewerAddress\)/);
        expect(app).toMatch(/signReadParams\(readAction, pk\)/);
    });
});
