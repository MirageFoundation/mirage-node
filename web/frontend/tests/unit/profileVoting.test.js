import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const frontendSrc = join(dirname(fileURLToPath(import.meta.url)), '../../src');

describe('profile voting', () => {
    it('passes updatePost through both profile routes to the submissions feed', () => {
        const app = readFileSync(join(frontendSrc, 'App.js'), 'utf8');
        const profile = readFileSync(
            join(frontendSrc, 'themes/default/routes/ProfileView.js'),
            'utf8',
        );

        expect(app.match(/<ProfileView state=\{this\.state\} updatePost=\{this\.updatePost\}/g))
            .toHaveLength(2);
        expect(profile).toMatch(/ProfileView\(\{ state, updatePost \}\)/);
        expect(profile).toMatch(/<ProfileViewAuthenticated state=\{state\} updatePost=\{updatePost\}/);
        expect(profile).toMatch(/<FeedComponent[\s\S]*?updatePost=\{updatePost\}/);
    });

    it('shows public creator earnings while restricting claims to the owner', () => {
        const profile = readFileSync(
            join(frontendSrc, 'themes/default/routes/ProfileView.js'),
            'utf8',
        );
        const earnings = readFileSync(
            join(frontendSrc, 'themes/default/components/CreatorEarningsPanel.js'),
            'utf8',
        );

        expect(profile).toMatch(
            /activeTab === 'earnings' && profileAddress[\s\S]*CreatorEarningsPanel creator=\{profileAddress\} canClaim=\{isOwnProfile\}/,
        );
        expect(profile).not.toMatch(/activeTab === 'earnings' && isOwnProfile/);
        expect(earnings).toMatch(/\{canClaim && <input/);
        expect(earnings).toMatch(/\{canClaim && earnings\.items\.length > 0 && <Actions>/);
        expect(earnings).toMatch(/Claim before \$\{deadline\}/);
        expect(earnings).toMatch(/formatCreatorRewardTime\(item\.epoch_start_unix/);
        expect(earnings).not.toMatch(/Daily MIRAGE rewards/);
        expect(earnings).not.toMatch(/Claim by epoch/);
    });
});
