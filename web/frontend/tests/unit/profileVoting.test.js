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
});
