/**
 * In-memory single-tab onboarding handoff for recovery phrases.
 * Secrets never enter router history, localStorage, or sessionStorage.
 */
const HANDOFF_TTL_MS = 15 * 60 * 1000;
const PURPOSES = new Set(['import', 'create', 'welcome', 'create-user-signing']);

/** @type {Map<string, { id: string, purpose: string, seed: string, owner: string|null, createdAt: number, expiresAt: number }>} */
const handoffs = new Map();

function newId() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

function purgeExpired() {
    const now = Date.now();
    for (const [id, entry] of handoffs) {
        if (entry.expiresAt <= now) {
            handoffs.delete(id);
            try { console.debug('[OnboardingSession] expired', { id, purpose: entry.purpose }); } catch (_) { /* noop */ }
        }
    }
}

/**
 * @param {{ purpose: string, seed: string, owner?: string|null }} opts
 * @returns {{ id: string }}
 */
export function createHandoff({ purpose, seed, owner = null }) {
    purgeExpired();
    if (!PURPOSES.has(purpose)) {
        throw new Error(`invalid onboarding handoff purpose: ${purpose}`);
    }
    if (typeof seed !== 'string' || !seed.trim()) {
        throw new Error('onboarding handoff requires a seed');
    }
    const id = newId();
    const now = Date.now();
    handoffs.set(id, {
        id,
        purpose,
        seed: seed.trim(),
        owner: owner || null,
        createdAt: now,
        expiresAt: now + HANDOFF_TTL_MS,
    });
    try {
        console.debug('[OnboardingSession] created', {
            id,
            purpose,
            ownerPrefix: owner ? String(owner).slice(0, 12) : null,
        });
    } catch (_) { /* noop */ }
    return { id };
}

/**
 * Peek without consuming. Returns null if missing/expired/purpose mismatch.
 * @param {string} id
 * @param {string=} expectedPurpose
 */
export function peekHandoff(id, expectedPurpose) {
    purgeExpired();
    if (!id) return null;
    const entry = handoffs.get(id);
    if (!entry) return null;
    if (expectedPurpose && entry.purpose !== expectedPurpose) return null;
    return { id: entry.id, purpose: entry.purpose, owner: entry.owner, seed: entry.seed };
}

/**
 * Consume (remove) a handoff. Returns null if missing/expired/purpose mismatch.
 * @param {string} id
 * @param {string=} expectedPurpose
 */
export function consumeHandoff(id, expectedPurpose) {
    const entry = peekHandoff(id, expectedPurpose);
    if (!entry) return null;
    handoffs.delete(id);
    try {
        console.debug('[OnboardingSession] consumed', { id, purpose: entry.purpose });
    } catch (_) { /* noop */ }
    return entry;
}

/**
 * Clear one handoff or all handoffs.
 * @param {string=} id
 */
export function clearHandoff(id) {
    if (id) {
        const existed = handoffs.delete(id);
        try { console.debug('[OnboardingSession] cleared', { id, existed }); } catch (_) { /* noop */ }
        return;
    }
    const n = handoffs.size;
    handoffs.clear();
    try { console.debug('[OnboardingSession] cleared-all', { count: n }); } catch (_) { /* noop */ }
}

/**
 * Peek the most recent handoff for a purpose (does not consume).
 * @param {string} purpose
 */
export function peekHandoffByPurpose(purpose) {
    purgeExpired();
    let best = null;
    for (const entry of handoffs.values()) {
        if (entry.purpose !== purpose) continue;
        if (!best || entry.createdAt > best.createdAt) best = entry;
    }
    if (!best) return null;
    return { id: best.id, purpose: best.purpose, owner: best.owner, seed: best.seed };
}

/** Test-only helper */
export function _debugHandoffCount() {
    purgeExpired();
    return handoffs.size;
}
