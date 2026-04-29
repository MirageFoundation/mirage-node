/**
 * DiceBear avatar URL helper.
 *
 * Single source of truth so the same user renders the same avatar across
 * every surface (TopBar, ProfileView, comment author row, …).
 *
 * Two DiceBear styles are supported:
 *   - `identicon` (default) — used for the circular user-avatar chip
 *     surfaces (TopBar, profile header, comment rows, list rows, …).
 *   - `shapes` — used for the no-media post-card placeholder so the
 *     compact feed rows get a more graphic, less \"face-y\" thumbnail
 *     instead of the geometric identicon glyph.
 *
 * Matches the mobile app's `Avatar` atom
 * (`mirage-mobile-app/src/components/atoms/avatar.tsx`):
 *   - Raw seed, **no lowercasing / trimming** — the mobile app passes the
 *     value verbatim to the DiceBear URL, so if we lowercase here we'd produce
 *     a different identicon for the same user. We only `encodeURIComponent`
 *     the seed so URL-unsafe characters don't break the request.
 *   - `size` uses the same `resolvedSize * 2` retina multiplier as mobile.
 *
 * Seed policy: every surface in the app passes the user's `mirage1…`
 * bech32 address as the seed, so the avatar stays stable across
 * username changes.
 */

const DICEBEAR_BASE = 'https://api.dicebear.com/9.x';

const SUPPORTED_STYLES = new Set(['identicon', 'shapes']);

/**
 * Build a DiceBear avatar URL.
 * @param {string} seed - username, address, or any stable identifier
 * @param {number} pxSize - on-screen size in CSS pixels (the URL requests 2×)
 * @param {('identicon'|'shapes')} [style='identicon'] — DiceBear style
 */
export function dicebearAvatarUrl(seed, pxSize = 32, style = 'identicon') {
    const rawSeed = seed === null || seed === undefined ? '' : String(seed);
    const safeSeed = encodeURIComponent(rawSeed || 'default');
    const size = Math.max(32, Math.round((pxSize || 32) * 2));
    const safeStyle = SUPPORTED_STYLES.has(style) ? style : 'identicon';
    return `${DICEBEAR_BASE}/${safeStyle}/png?seed=${safeSeed}&size=${size}`;
}
