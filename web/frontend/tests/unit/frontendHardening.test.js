/**
 * Regression tests for the 2026-08-14 frontend security review.
 *
 * Each test reproduces the defect the finding describes, so reverting the fix
 * makes the test fail rather than making it vacuous. Where a finding lives in a
 * React component the load-bearing decision was moved into a plain function so
 * it can be exercised without a DOM.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { generateMnemonic } from 'bip39';

import seedVault from '../../src/utils/SeedVault.js';
import Storage from '../../src/utils/Storage.js';
import { markdownUrlTransform } from '../../src/utils/markdownUrl.js';
import { getSessionGeneration, onSessionReset, resetClientSession } from '../../src/utils/sessionLifecycle.js';

const PASSWORD = 'correct-horse-battery-staple';

describe('H-1: recovery-phrase fallback leaves a usable session', () => {
    beforeEach(() => {
        localStorage.clear();
        seedVault.lock();
    });

    it('reports that a locked protected vault cannot be written without a secret', async () => {
        const phrase = generateMnemonic();
        await seedVault.storeSeed(phrase, 'password', PASSWORD);
        expect(seedVault.getMode()).toBe('password');
        expect(seedVault.canStoreWithoutSecret()).toBe(true);

        // handleFallbackLogin nulls the cached key before routing to /login.
        seedVault.lock();
        expect(seedVault.canStoreWithoutSecret()).toBe(false);
    });

    it('stores the seed after a fallback login instead of throwing', async () => {
        const phrase = generateMnemonic();
        await seedVault.storeSeed(phrase, 'password', PASSWORD);
        seedVault.lock();
        expect(seedVault.getSeed()).toBe(null);

        const { mode, requested } = await seedVault.storeSeedForSession(phrase);

        expect(requested).toBe('password');
        expect(mode).toBe('memory');
        // The defect: storeSeed(..., 'password', null) threw, so the app rendered
        // as signed in while every signing path read null out of the vault.
        expect(seedVault.getSeed()).toBe(phrase);
    });

    it('leaves an unlocked protected vault on its own mode', async () => {
        const phrase = generateMnemonic();
        await seedVault.storeSeed(phrase, 'password', PASSWORD);

        const { mode, requested } = await seedVault.storeSeedForSession(phrase);

        expect(requested).toBe('password');
        expect(mode).toBe('password');
        expect(seedVault.getMode()).toBe('password');
    });

    it('does not downgrade a protected vault to plaintext', async () => {
        const phrase = generateMnemonic();
        await seedVault.storeSeed(phrase, 'password', PASSWORD);
        seedVault.lock();

        await seedVault.storeSeedForSession(phrase);

        expect(seedVault.getMode()).toBe('memory');
        expect(localStorage.getItem('seedPhrase')).toBe(null);
    });
});

describe('M-7: revealing the phrase needs a recent unlock', () => {
    beforeEach(() => {
        localStorage.clear();
        seedVault.lock();
    });

    it('treats an unlock as stale once the window passes', async () => {
        const phrase = generateMnemonic();
        await seedVault.storeSeed(phrase, 'password', PASSWORD);

        expect(seedVault.requireFreshUnlock(120_000)).toBe(true);

        const realNow = Date.now;
        try {
            Date.now = () => realNow() + 121_000;
            expect(seedVault.requireFreshUnlock(120_000)).toBe(false);
        } finally {
            Date.now = realNow;
        }
    });

    it('fails closed when the step-up password is wrong', async () => {
        const phrase = generateMnemonic();
        await seedVault.storeSeed(phrase, 'password', PASSWORD);
        seedVault.lock();

        await expect(seedVault.unlock('not-the-password')).rejects.toThrow(/Incorrect password/);
        expect(seedVault.getSeed()).toBe(null);
    });

    it('accepts the correct password and refreshes the unlock timestamp', async () => {
        const phrase = generateMnemonic();
        await seedVault.storeSeed(phrase, 'password', PASSWORD);
        seedVault.lock();

        await expect(seedVault.unlock(PASSWORD)).resolves.toBe(true);
        expect(seedVault.requireFreshUnlock(120_000)).toBe(true);
        expect(seedVault.getSeed()).toBe(phrase);
    });
});

describe('M-2: session reset drains account-bound caches', () => {
    beforeEach(() => {
        localStorage.clear();
        seedVault.lock();
    });

    it('notifies subscribers and bumps the generation', async () => {
        const seen = [];
        const unsubscribe = onSessionReset((info) => seen.push(info));
        const before = getSessionGeneration();

        await resetClientSession({ reason: 'test_reset', clearVault: true });

        expect(getSessionGeneration()).toBeGreaterThan(before);
        expect(seen).toHaveLength(1);
        expect(seen[0].reason).toBe('test_reset');
        unsubscribe();
    });

    it('clears the per-tab feed cache, which is keyed by topic and not by account', async () => {
        const { writeMemFeedState, readMemFeedState } = await import('../../src/logic/useMain.js');
        writeMemFeedState('all', { posts: [{ post_id: 'a', user_vote: 1 }] });
        expect(readMemFeedState('all')).toBeTruthy();

        await resetClientSession({ reason: 'test_feed_cache', clearVault: true });

        expect(readMemFeedState('all')).toBe(null);
    });

    it('drops cached GET responses so the next account is not served the last one', async () => {
        const Api = (await import('../../src/utils/api.js')).default;
        let calls = 0;
        const fetchMock = vi.fn(async () => {
            calls += 1;
            return {
                ok: true,
                headers: { get: () => 'application/json' },
                json: async () => ({ call: calls }),
            };
        });
        const realFetch = globalThis.fetch;
        globalThis.fetch = fetchMock;
        try {
            const first = await Api.get('get_feed', { topic: 'all' }, { cacheMs: 60_000 });
            expect(first.call).toBe(1);

            // Served from responseCache, which the cache-hit branch never
            // compared against the session generation.
            const cached = await Api.get('get_feed', { topic: 'all' }, { cacheMs: 60_000 });
            expect(cached.call).toBe(1);

            Api.resetApiSession(getSessionGeneration() + 1, 'test_api_cache');

            const afterReset = await Api.get('get_feed', { topic: 'all' }, { cacheMs: 60_000 });
            expect(afterReset.call).toBe(2);
        } finally {
            globalThis.fetch = realFetch;
        }
    });

    it('sign-out clears sessionStorage, not just localStorage', () => {
        localStorage.setItem('publicKey', '"mirage1abc"');
        sessionStorage.setItem('feed_order_all', '["a"]');
        sessionStorage.setItem('_seenPending', '[{"id":"a","reason":"view"}]');

        Storage.hardResetAllStorage();

        expect(localStorage.getItem('publicKey')).toBe(null);
        expect(sessionStorage.getItem('feed_order_all')).toBe(null);
        expect(sessionStorage.getItem('_seenPending')).toBe(null);
    });
});

describe('L-1: cross-tab sign-out drains the sibling tab', () => {
    beforeEach(() => {
        localStorage.clear();
        seedVault.lock();
    });

    it('locks rather than clears the vault, and does not re-broadcast', async () => {
        const phrase = generateMnemonic();
        await seedVault.storeSeed(phrase, 'password', PASSWORD);
        const before = getSessionGeneration();
        localStorage.removeItem('mirage_session_reset_signal');

        await resetClientSession({ reason: 'cross_tab_sign_out', clearVault: true, lockVault: true });

        // The generation bump is what stops a queued intent that predates the
        // sign-out from matching if the user signs back into the same account.
        expect(getSessionGeneration()).toBeGreaterThan(before);
        expect(seedVault.getSeed()).toBe(null);
        // Re-broadcasting would bounce the signal back to the originating tab.
        expect(localStorage.getItem('mirage_session_reset_signal')).toBe(null);
    });
});

describe('sub-threshold: protocol-relative markdown links', () => {
    it('drops authority-relative URLs that resolve off-site', () => {
        expect(markdownUrlTransform('//evil.example/phish')).toBe('');
        expect(markdownUrlTransform('  //evil.example')).toBe('');
        expect(markdownUrlTransform('\\\\evil.example')).toBe('');
        expect(markdownUrlTransform('/\\evil.example')).toBe('');
    });

    it('still allows ordinary internal and external links', () => {
        expect(markdownUrlTransform('/t/mirage')).toBe('/t/mirage');
        expect(markdownUrlTransform('https://example.com/x')).toBe('https://example.com/x');
        expect(markdownUrlTransform('mailto:a@example.com')).toBe('mailto:a@example.com');
        expect(markdownUrlTransform('#anchor')).toBe('#anchor');
    });

    it('keeps rejecting script-bearing schemes', () => {
        expect(markdownUrlTransform('javascript:alert(1)')).toBe('');
        expect(markdownUrlTransform('data:text/html,<script>alert(1)</script>')).toBe('');
    });
});
