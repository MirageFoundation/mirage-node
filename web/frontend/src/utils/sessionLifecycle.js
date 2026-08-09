/**
 * Session generation + reset coordination.
 * All account-bound async work must check getSessionGeneration() before writing state.
 */
import seedVault from './SeedVault';
import Storage from './Storage';
import { clearHandoff } from './onboardingSession';

const SESSION_EVENT = 'mirage:session-reset';
const CROSS_TAB_KEY = 'mirage_session_reset_signal';

let generation = 1;
let resetInFlight = null;

/** @type {Set<(info: { generation: number, reason: string }) => void>} */
const listeners = new Set();

export function getSessionGeneration() {
    return generation;
}

export function onSessionReset(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
}

function bumpGeneration(reason) {
    generation += 1;
    try {
        console.debug('[Session] generation-bump', { generation, reason });
    } catch (_) { /* noop */ }
    return generation;
}

function notify(reason, gen) {
    for (const fn of [...listeners]) {
        try { fn({ generation: gen, reason }); } catch (_) { /* noop */ }
    }
    try {
        window.dispatchEvent(new CustomEvent(SESSION_EVENT, { detail: { generation: gen, reason } }));
    } catch (_) { /* noop */ }
}

/**
 * Abort account-bound work, clear vault/identity caches, and bump generation.
 * TransactionHandler drain is awaited when available.
 *
 * @param {{ reason: string, preserveAnalytics?: boolean, clearVault?: boolean, lockVault?: boolean, hardReset?: boolean, nextOwner?: string|null }} opts
 */
export async function resetClientSession(opts) {
    const reason = opts?.reason || 'unspecified';
    if (resetInFlight) {
        try { console.debug('[Session] reset-wait-inflight', { reason }); } catch (_) { /* noop */ }
        await resetInFlight;
    }

    resetInFlight = (async () => {
        const gen = bumpGeneration(reason);
        try {
            console.debug('[Session] reset-start', { reason, generation: gen });
        } catch (_) { /* noop */ }

        // Drain transaction queue if handler is loaded.
        try {
            const tx = await import('./tx');
            if (typeof tx.cancelAll === 'function') {
                await tx.cancelAll(reason);
            } else if (typeof tx.resetSession === 'function') {
                await tx.resetSession(reason);
            }
        } catch (e) {
            try { console.debug('[Session] tx-drain-skip', { message: String(e?.message || e) }); } catch (_) { /* noop */ }
        }

        // Abort API session work.
        try {
            const api = (await import('./api')).default;
            if (typeof api.resetApiSession === 'function') {
                api.resetApiSession(gen, reason);
            }
        } catch (_) { /* noop */ }

        clearHandoff();

        if (opts?.hardReset) {
            Storage.hardResetAllStorage();
        } else if (opts?.preserveAnalytics !== false) {
            Storage.clear();
        }

        if (opts?.clearVault !== false) {
            if (opts?.lockVault) {
                seedVault.lock();
            } else {
                seedVault.clear();
            }
        }

        // Cross-tab signal (not for lock-only — lock is tab-local).
        if (!opts?.lockVault) {
            try {
                localStorage.setItem(CROSS_TAB_KEY, JSON.stringify({ generation: gen, reason, at: Date.now() }));
            } catch (_) { /* noop */ }
        }

        notify(reason, gen);
        try {
            console.debug('[Session] reset-complete', { reason, generation: gen });
        } catch (_) { /* noop */ }
        return gen;
    })();

    try {
        return await resetInFlight;
    } finally {
        resetInFlight = null;
    }
}

/** Install cross-tab listener once. */
export function installCrossTabSessionWatcher(onRemoteReset) {
    const handler = (e) => {
        if (e.key !== CROSS_TAB_KEY || !e.newValue) return;
        try {
            const payload = JSON.parse(e.newValue);
            try { console.debug('[Session] cross-tab-reset', payload); } catch (_) { /* noop */ }
            if (typeof onRemoteReset === 'function') onRemoteReset(payload);
        } catch (_) { /* noop */ }
    };
    window.addEventListener('storage', handler);
    return () => window.removeEventListener('storage', handler);
}

export const SESSION_RESET_EVENT = SESSION_EVENT;
