/**
 * Tier color utilities for displaying user subscription status.
 * These colors match the subscription tiers: Free, Subscriber, Agent.
 */

// Tier colors matching SubscriptionView.js
const TIER_COLORS = {
    0: '#6B7280', // Free
    1: '#F59E0B', // Subscriber (gold)
    10: '#EF4444' // Agent (red)
};

const TIER_NAMES = {
    0: 'Free',
    1: 'Subscriber',
    10: 'Agent'
};

/**
 * Get the color for a user's tier level.
 * @param {number} level - The user's tier level (0, 1, 10 for regular tiers, >= 100 for admin)
 * @returns {string|null} - The color hex code, or null if Free tier (level 0) or admin (level >= 100)
 */
export const getTierColor = (level) => {
    if (level === undefined || level === null || level === 0) return null;
    if (level >= 100) return null; // Admins use default colors
    return TIER_COLORS[level] || null;
};

/**
 * Get the display name for a user's tier level (for tooltips).
 * @param {number} level - The user's tier level (0, 1, 10 for regular tiers)
 * @returns {string|null} - The tier name, or null if Free tier or admin
 */
export const getTierName = (level) => {
    if (level === undefined || level === null || level === 0) return null;
    if (level >= 100) return null; // Admins don't show tier tooltip
    return TIER_NAMES[level] || null;
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

const NEW_USER_COLOR = '#22C55E';
const NEW_USER_LABEL = 'New User';

/**
 * Get the display color for an author. Subscriber tiers take priority over new-user green.
 * @param {number} level - The user's tier level
 * @param {boolean} isNewUser - Whether the backend flagged this user as new
 * @returns {string|null}
 */
export const getAuthorColor = (level, isNewUser) => {
    const tierColor = getTierColor(level);
    if (tierColor) return tierColor;
    if (isNewUser) return NEW_USER_COLOR;
    return null;
};

/**
 * Get the tooltip text for an author. Subscriber tier names take priority.
 * @param {number} level - The user's tier level
 * @param {boolean} isNewUser - Whether the backend flagged this user as new
 * @returns {string|null}
 */
export const getAuthorTooltip = (level, isNewUser) => {
    const tierName = getTierName(level);
    if (tierName) return tierName;
    if (isNewUser) return NEW_USER_LABEL;
    return null;
};
