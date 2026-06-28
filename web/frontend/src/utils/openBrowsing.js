// @ts-check

/**
 * Open browsing: logged-out visitors may read all content, and are prompted to
 * create an account only when they attempt a write/social action. Controlled
 * per-node by the `open_browsing_enabled` flag from get_node_config.
 *
 * This module is the single source of truth for that gate on the web client.
 */

import Storage from './Storage';

export const AUTH_REQUIRED_EVENT = 'mirage:auth-required';

/** Whether this node has open browsing turned on. Reads the cached nodeConfig. */
export function isOpenBrowsingEnabled() {
    try {
        const raw = localStorage.getItem('nodeConfig');
        if (!raw) return false;
        return Boolean(JSON.parse(raw).open_browsing_enabled);
    } catch (_) {
        return false;
    }
}

/**
 * Whether the node config has loaded yet. Until it has, open-browsing state is
 * unknown, so callers must NOT render the logged-out gate (it would flash on the
 * first visit before the async config fetch resolves).
 */
export function isNodeConfigLoaded() {
    try {
        return localStorage.getItem('nodeConfig') != null;
    } catch (_) {
        return false;
    }
}

/** Whether a real account is present (not the anonymous "guest"). */
export function isLoggedIn() {
    try {
        const pk = Storage.load('publicKey', '');
        return !!(pk && pk !== 'guest');
    } catch (_) {
        return false;
    }
}

/**
 * Gate a write/social action behind having an account.
 *
 * Returns true when the user may proceed (logged in). When logged out AND open
 * browsing is enabled, it opens the global signup modal and returns false. On
 * nodes with open browsing OFF it stays silent and returns false, preserving the
 * existing invite-only behavior (where these actions are unreachable anyway).
 *
 * @param {string} action short verb phrase, e.g. 'vote', 'comment', 'post', 'follow users'
 * @returns {boolean}
 */
export function requireAccount(action) {
    if (isLoggedIn()) return true;
    if (isOpenBrowsingEnabled()) {
        try {
            window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT, { detail: { action: action || '' } }));
        } catch (_) { /* best-effort */ }
    }
    return false;
}
