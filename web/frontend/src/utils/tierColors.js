/**
 * Tier color utilities for displaying user subscription status.
 * These colors match the subscription tiers: Free, Trusted, Established, Distinguished.
 */

// Tier colors matching SubscriptionView.js
const TIER_COLORS = ['#6B7280', '#3B82F6', '#8B5CF6', '#F59E0B'];
const TIER_NAMES = ['Free', 'Trusted Subscriber', 'Established Subscriber', 'Distinguished Subscriber'];

/**
 * Get the color for a user's tier level.
 * @param {number} level - The user's tier level (0-3 for regular tiers, >= 100 for admin)
 * @returns {string|null} - The color hex code, or null if Free tier (level 0) or admin (level >= 100)
 */
export const getTierColor = (level) => {
    if (level === undefined || level === null || level === 0) return null;
    if (level >= 100) return null; // Admins use default colors
    if (level > 0 && level < TIER_COLORS.length) {
        return TIER_COLORS[level];
    }
    return null;
};

/**
 * Get the display name for a user's tier level (for tooltips).
 * @param {number} level - The user's tier level (0-3 for regular tiers)
 * @returns {string|null} - The tier name, or null if Free tier or admin
 */
export const getTierName = (level) => {
    if (level === undefined || level === null || level === 0) return null;
    if (level >= 100) return null; // Admins don't show tier tooltip
    if (level > 0 && level < TIER_NAMES.length) {
        return TIER_NAMES[level];
    }
    return null;
};

/**
 * Check if an author level should have colored name display.
 * Returns true for tier levels > 0 (subscribers and admins).
 * @param {number} level - The user's tier level
 * @returns {boolean}
 */
export const shouldColorName = (level) => {
    return level !== undefined && level !== null && level > 0;
};
