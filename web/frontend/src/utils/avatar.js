/**
 * DiceBear identicon avatar URL helper.
 *
 * Single source of truth so the same user renders the same identicon across
 * every surface (TopBar, ProfileView, comment author row, …).
 *
 * Matches the mobile app's `Avatar` atom
 * (`mirage-mobile-app/src/components/atoms/avatar.tsx`):
 *   - Raw seed, **no lowercasing / trimming** — the mobile app passes the
 *     value verbatim to the DiceBear URL, so if we lowercase here we'd produce
 *     a different identicon for the same user. We only `encodeURIComponent`
 *     the seed so URL-unsafe characters don't break the request.
 *   - `size` uses the same `resolvedSize * 2` retina multiplier as mobile.
 *
 * Seed policy (also aligned with the mobile app):
 *   - Own profile / TopBar → prefer **wallet address**, fall back to username.
 *     (mobile: `user?.walletAddress || username`)
 *   - Other profile → prefer **userAddress**, fall back to username.
 *     (mobile: `userAddress || username`)
 *   - Post / comment author row → just `username` (the only field the API
 *     carries for those surfaces).
 *
 * The consumer is responsible for picking the right seed in that order.
 */

const DICEBEAR_BASE = 'https://api.dicebear.com/9.x/identicon/png';

/**
 * Build a DiceBear identicon URL.
 * @param {string} seed - username, address, or any stable identifier
 * @param {number} pxSize - on-screen size in CSS pixels (the URL requests 2×)
 */
export function dicebearAvatarUrl(seed, pxSize = 32) {
    const rawSeed = seed === null || seed === undefined ? '' : String(seed);
    const safeSeed = encodeURIComponent(rawSeed || 'default');
    const size = Math.max(32, Math.round((pxSize || 32) * 2));
    return `${DICEBEAR_BASE}?seed=${safeSeed}&size=${size}`;
}
