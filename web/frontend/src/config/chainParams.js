/**
 * Chain Parameters
 * 
 * These values are fetched from the blockchain via the backend API.
 * They are cached in localStorage and refreshed on every app load.
 * 
 * NO HARDCODED FALLBACKS - the chain is the source of truth.
 * If values aren't cached yet, functions return null and UI should handle accordingly.
 */

export const ANON_PREFIX = 'Anon-';
export const ANON_PREFIX_LENGTH = ANON_PREFIX.length; // 5

/**
 * Get the maximum username size from localStorage (set by backend from chain params).
 * Returns null if not yet cached - caller must handle this case.
 */
export const getMaxUsernameSize = () => {
    const raw = localStorage.getItem('max_username_size');
    if (!raw) return null;
    // Try to parse - handle both plain "30" and legacy JSON-stringified "\"30\""
    let value = raw;
    if (raw.startsWith('"')) {
        try { value = JSON.parse(raw); } catch (_) { }
    }
    const parsed = parseInt(value, 10);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
    // Corrupted - clear and let App.js re-fetch
    localStorage.removeItem('max_username_size');
    localStorage.removeItem('config_cached_at');
    return null;
};

/**
 * Get the minimum username size from localStorage (set by backend from chain params).
 * Returns null if not yet cached - caller must handle this case.
 */
export const getMinUsernameSize = () => {
    const raw = localStorage.getItem('min_username_size');
    if (!raw) return null;
    // Try to parse - handle both plain "30" and legacy JSON-stringified "\"30\""
    let value = raw;
    if (raw.startsWith('"')) {
        try { value = JSON.parse(raw); } catch (_) { }
    }
    const parsed = parseInt(value, 10);
    if (Number.isFinite(parsed) && parsed > 0) return parsed;
    // Corrupted - clear and let App.js re-fetch
    localStorage.removeItem('min_username_size');
    localStorage.removeItem('config_cached_at');
    return null;
};

/**
 * Get the maximum length for the input field, accounting for the Anon- prefix if needed.
 * @param {boolean} isFreeUser - Whether the user is on free tier (will have Anon- prefix)
 * Returns null if chain params not yet cached.
 */
export const getMaxInputLength = (isFreeUser) => {
    const maxSize = getMaxUsernameSize();
    if (maxSize === null) return null;
    const result = isFreeUser ? maxSize - ANON_PREFIX_LENGTH : maxSize;
    return Math.max(1, result);
};
