import React from 'react';
import styled from 'styled-components';

import { dicebearAvatarUrl } from '../../../utils/avatar';

/**
 * PostPlaceholderAvatar — mirageapp
 *
 * Replacement for the no-media thumbnail tile shown on compact feed rows
 * when a post has no image/video. Renders a DiceBear `shapes` glyph
 * seeded by the post author's `mirage1…` bech32 address, on a flat
 * neutral grey tile.
 *
 * Why this exists:
 *   - The previous placeholder was the loud indigo→purple brand gradient
 *     with the author's first initial stamped on top. The brand gradient
 *     is reserved for primary CTAs; using it here made every media-less
 *     row compete for attention and felt template-y.
 *   - A DiceBear `shapes` glyph gives each author a stable, visually
 *     distinct mark with more graphic variety than the geometric
 *     `identicon` style — better suited to a thumbnail-replacement
 *     tile than to a circular user chip. The other avatar surfaces in
 *     the app stay on `identicon`.
 *
 * Seed policy:
 *   - Always seed on the `mirage1` bech32 address so the glyph is
 *     stable across username changes. Fall back to the username, then
 *     a literal `'anonymous'` string so rows without either still get
 *     a deterministic glyph.
 *
 * Background:
 *   - Hard-pinned to `#232830` (dark-mode `surface3`) in BOTH light and
 *     dark themes, matching the TopBar avatar chip + ProfileView Avatar
 *     convention. DiceBear's `shapes` variant is transparent like
 *     `identicon`, so the pinned grey fills the negative space
 *     identically across themes.
 */

const AVATAR_BG = '#232830';

const PlaceholderRoot = styled.div`
    grid-row: 1 / span 3;
    display: flex;
    align-items: center;
    justify-content: center;
    width: ${({ $size }) => $size}px;
    height: ${({ $size }) => $size}px;
    border-radius: 8px;
    background: ${AVATAR_BG};
    flex-shrink: 0;
    overflow: hidden;

    @media (max-width: 600px) {
        width: ${({ $mobileSize }) => $mobileSize}px;
        height: ${({ $mobileSize }) => $mobileSize}px;
        border-radius: 6px;
    }
`;

const AvatarImg = styled.img`
    width: 50%;
    height: 50%;
    display: block;
    object-fit: contain;
    background: ${AVATAR_BG};
`;

function pickSeed({ address, username }) {
    if (typeof address === 'string' && address.trim()) return address.trim();
    if (typeof username === 'string' && username.trim()) return username.trim();
    return 'anonymous';
}

/**
 * @param {object} props
 * @param {string} [props.address]   — `mirage1…` bech32 address (preferred seed)
 * @param {string} [props.username]  — fallback seed if address is missing
 * @param {number} [props.size]      — desktop size in px (default 84)
 * @param {number} [props.mobileSize]— mobile size in px (default 68)
 * @param {string} [props.alt]       — img alt text (defaults to empty; tile is decorative)
 */
export default function PostPlaceholderAvatar({
    address,
    username,
    size = 84,
    mobileSize = 68,
    alt = '',
}) {
    const seed = pickSeed({ address, username });
    // Request at the larger (desktop) footprint so the glyph stays sharp
    // on both breakpoints. `dicebearAvatarUrl` already applies a 2×
    // retina multiplier internally. Use the `shapes` DiceBear style for
    // post-card placeholders (vs `identicon` used for user-avatar chips).
    const src = dicebearAvatarUrl(seed, size, 'shapes');

    return (
        <PlaceholderRoot
            $size={size}
            $mobileSize={mobileSize}
            aria-hidden={alt ? undefined : 'true'}
        >
            <AvatarImg src={src} alt={alt} loading="lazy" />
        </PlaceholderRoot>
    );
}
