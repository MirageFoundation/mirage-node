import Storage from './Storage';

/**
 * Bootstrap stash helpers.
 *
 * Background: /api/bootstrap collapses the cold-load fan-out into one
 * request. App.js writes per-section snapshots into localStorage under
 * keys like `bootstrap_user_blocked`, `bootstrap_invite_codes`, and
 * `bootstrap_rewards_summary` with a `{ data, at, pk }` envelope.
 *
 * Consumer hooks (useMain blocked topics, invite codes; useQuests fetchAll)
 * read the stash on mount instead of firing their own request — but only
 * once, and only within a short TTL after bootstrap. If the stash is
 * missing, expired, or for a different user, the hook falls through to
 * its existing fetch path. Reads are single-shot: the entry is removed
 * after consumption so refreshes don't reuse stale data.
 */

const TTL_MS = 30000;
const WAIT_TIMEOUT_MS = 750;

export function readBootstrapStash(key, expectedPk) {
    try {
        const raw = Storage.load(key, null);
        if (!raw || typeof raw !== 'object') return null;
        const { data, at, pk } = raw;
        if (!data || !at) return null;
        if (Date.now() - Number(at) > TTL_MS) {
            Storage.remove(key);
            return null;
        }
        if (expectedPk && pk && String(pk).toLowerCase() !== String(expectedPk).toLowerCase()) {
            Storage.remove(key);
            return null;
        }
        Storage.remove(key);
        return data;
    } catch (_) {
        return null;
    }
}

export async function readBootstrapStashAfterBootstrap(key, expectedPk) {
    const immediate = readBootstrapStash(key, expectedPk);
    if (immediate) return immediate;

    try {
        if (typeof window === 'undefined') return null;
        const bootstrapPromise = window.__MIRAGE_BOOTSTRAP_PROMISE__;
        const bootstrapPk = window.__MIRAGE_BOOTSTRAP_PK__;
        const expected = String(expectedPk || '').toLowerCase();
        const active = String(bootstrapPk || '').toLowerCase();
        if (!bootstrapPromise || typeof bootstrapPromise.then !== 'function') return null;
        if (expected && active && active !== expected) return null;

        await Promise.race([
            bootstrapPromise.catch(() => null),
            new Promise(resolve => setTimeout(resolve, WAIT_TIMEOUT_MS)),
        ]);
    } catch (_) {
        return null;
    }

    return readBootstrapStash(key, expectedPk);
}
