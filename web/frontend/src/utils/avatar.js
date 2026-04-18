/**
 * DiceBear identicon avatar URL helper.
 *
 * Single source of truth so the same user always renders the same identicon
 * regardless of which surface is asking (TopBar, ProfileView, comment author
 * row, etc.). The seed is normalized (trimmed + lowercased) so casing
 * differences between data sources (e.g. URL slug `sonali` vs API field
 * `Sonali`) collapse to the same image.
 *
 * Mirrors the mobile app's DiceBear v9 identicon at
 *   `https://api.dicebear.com/9.x/identicon/png?seed=<seed>&size=<px>`
 */

const DICEBEAR_BASE = 'https://api.dicebear.com/9.x/identicon/png';

/** Normalize a seed for stable identicon output. */
export function normalizeAvatarSeed(seed) {
    if (seed === null || seed === undefined) return 'default';
    const trimmed = String(seed).trim();
    if (!trimmed) return 'default';
    return trimmed.toLowerCase();
}

/**
 * Build a DiceBear identicon URL.
 * @param {string} seed - username, address, or any identifier
 * @param {number} pxSize - on-screen size in CSS pixels (the URL requests 2x)
 */
export function dicebearAvatarUrl(seed, pxSize = 32) {
    const safeSeed = encodeURIComponent(normalizeAvatarSeed(seed));
    const size = Math.max(32, Math.round((pxSize || 32) * 2));
    return `${DICEBEAR_BASE}?seed=${safeSeed}&size=${size}`;
}
