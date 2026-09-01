import Storage from './Storage';

/**
 * Bootstrap stash helpers.
 *
 * Background: /api/bootstrap collapses the cold-load fan-out into one
 * request. App.js writes per-section snapshots into localStorage under
 * keys like `bootstrap_user_blocked`, `bootstrap_invite_codes`,
 * `bootstrap_rewards_summary`, and `bootstrap_view` with a
 * `{ data, at, pk }` envelope.
 *
 * Consumer hooks (useMain blocked communities / feed, invite codes; useQuests
 * fetchAll; useViewPost; useInbox) read the stash on mount instead of
 * firing their own request — but only once, and only within a short TTL
 * after bootstrap. If the stash is missing, expired, or for a different
 * user, the hook falls through to its existing fetch path.
 *
 * For `bootstrap_view` (multi-kind: feed / thread / inbox), prefer
 * peek → match → consume so a mismatched consumer does not erase the
 * payload another hook needs.
 */

const TTL_MS = 30000;

function _readEnvelope(key, expectedPk) {
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
        return { data, key };
    } catch (_) {
        return null;
    }
}

export function peekBootstrapStash(key, expectedPk) {
    const env = _readEnvelope(key, expectedPk);
    return env ? env.data : null;
}

export function readBootstrapStash(key, expectedPk) {
    const env = _readEnvelope(key, expectedPk);
    if (!env) return null;
    try { Storage.remove(key); } catch (_) { }
    return env.data;
}

async function waitForBootstrap(expectedPk) {
    try {
        if (typeof window === 'undefined') return;
        const expected = String(expectedPk || '').toLowerCase();

        let bootstrapPromise = window.__MIRAGE_BOOTSTRAP_PROMISE__;
        let bootstrapPk = window.__MIRAGE_BOOTSTRAP_PK__;
        // App installs the promise in componentDidMount; child effects can run
        // a tick earlier. Brief settle wait, then await the real request.
        if (!bootstrapPromise || typeof bootstrapPromise.then !== 'function') {
            await new Promise(resolve => setTimeout(resolve, 100));
            bootstrapPromise = window.__MIRAGE_BOOTSTRAP_PROMISE__;
            bootstrapPk = window.__MIRAGE_BOOTSTRAP_PK__;
        }
        if (!bootstrapPromise || typeof bootstrapPromise.then !== 'function') return;

        const active = String(bootstrapPk || '').toLowerCase();
        if (expected && active && active !== expected) return;

        // Await the in-flight bootstrap fully. Racing a short timeout caused
        // consumers to fall through to their own fetch while bootstrap later
        // wrote a view stash that could paint launch-time data on a later POP.
        await bootstrapPromise.catch(() => null);
    } catch (_) { /* noop */ }
}

export async function peekBootstrapStashAfterBootstrap(key, expectedPk) {
    const immediate = peekBootstrapStash(key, expectedPk);
    if (immediate) return immediate;
    await waitForBootstrap(expectedPk);
    return peekBootstrapStash(key, expectedPk);
}

export async function readBootstrapStashAfterBootstrap(key, expectedPk) {
    const immediate = readBootstrapStash(key, expectedPk);
    if (immediate) return immediate;

    await waitForBootstrap(expectedPk);
    return readBootstrapStash(key, expectedPk);
}
