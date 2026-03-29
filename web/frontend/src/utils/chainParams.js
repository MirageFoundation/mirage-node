/**
 * Chain Parameters
 *
 * These values are fetched from the blockchain via the get_chain_config API.
 * They are cached in localStorage as 'chainConfig' and refreshed on every app load.
 *
 * NO HARDCODED FALLBACKS - the chain is the source of truth.
 * If values aren't cached yet, functions return null and UI should handle accordingly.
 */

export const ANON_PREFIX = 'Anon-';
export const ANON_PREFIX_LENGTH = ANON_PREFIX.length; // 5

/**
 * Read a numeric field from the chainConfig localStorage blob.
 * Returns null if not cached or not a valid positive integer.
 */
function _readChainParam(field) {
    try {
        const raw = localStorage.getItem('chainConfig');
        if (!raw) return null;
        const config = JSON.parse(raw);
        const val = parseInt(config[field], 10);
        if (Number.isFinite(val) && val > 0) return val;
    } catch (_) { }
    return null;
}

/**
 * Get the maximum username size from cached chain config.
 * Returns null if not yet cached - caller must handle this case.
 */
export const getMaxUsernameSize = () => _readChainParam('max_username_size');

/**
 * Get the minimum username size from cached chain config.
 * Returns null if not yet cached - caller must handle this case.
 */
export const getMinUsernameSize = () => _readChainParam('min_username_size');

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
