/**
 * Chain Parameters
 *
 * These values are fetched from the blockchain via the get_chain_config API.
 * They are cached in localStorage as 'chainConfig' and refreshed on every app load.
 *
 * NO HARDCODED FALLBACKS - the chain is the source of truth.
 * If values aren't cached yet, functions return null and UI should handle accordingly.
 */

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
 * Get the maximum length for the username input field.
 * Returns null if chain params not yet cached.
 */
export const getMaxInputLength = () => getMaxUsernameSize();
