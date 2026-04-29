import React, { forwardRef } from 'react';
import styled, { css } from 'styled-components';

import { dicebearAvatarUrl } from '../../../utils/avatar';

/**
 * UserAvatar — single source of truth for circular DiceBear identicon
 * avatars across the mirageapp theme.
 *
 * Why one component:
 *   - Before this, every surface (TopBar, ProfileView, FollowsView,
 *     BlocksView, AgentsView, ReferralsView, SearchResultsView,
 *     SearchDropdown, comment rows in ViewPostView) declared its own
 *     `styled.img` for the dicebear chip. The bg, padding, and image
 *     framing drifted from surface to surface.
 *   - Funneling all of them through `UserAvatar` guarantees a single
 *     visual language: same circle bg, same retina seed URL, and the
 *     same 20% inner padding around the identicon glyph.
 *
 * Visual contract:
 *   - The wrapper is a `size × size` circle filled with `#232830`
 *     (dark-mode `surface3`). The hard-pinned color matches the
 *     existing TopBar / ProfileView convention so light + dark modes
 *     don't diverge for the dicebear surface.
 *   - The identicon `<img>` is centered inside that circle and inset
 *     by 20% on every side, leaving a balanced \"halo\" of negative
 *     space between the identicon and the wrapper edge.
 *
 * Customisation:
 *   - `size` (px) drives both the wrapper footprint and the dicebear
 *     URL retina request. Defaults to 32.
 *   - `activeBorderColor` paints a 2px ring around the wrapper (used
 *     by ReferralsView leaderboard rows for the \"active this week\"
 *     state). Defaults off.
 *   - `paddingRatio` controls the inner inset around the identicon
 *     glyph as a fraction of `size`. Defaults to `0.2` (20%) — the
 *     profile header / aside avatars override this to `0.1` (10%)
 *     so the identicon reads larger in those hero positions.
 *   - `shape` selects the wrapper outline:
 *       - `'circle'` (default) — fully round, `border-radius: 50%`.
 *       - `'rounded'` — square tile with a slight `12px` radius,
 *         used by the profile-header / aside-card avatars.
 *     `radius` lets callers override the rounded-tile radius if they
 *     need a different curve.
 *   - The component is a `forwardRef` and forwards `className` /
 *     `style`, so it composes cleanly with `styled(UserAvatar)` when
 *     a caller needs to add absolute positioning, layout-specific
 *     margins, etc. (e.g. the `CommentAvatar` in `ViewPostView`).
 */

const AVATAR_BG = '#232830';
const DEFAULT_ROUNDED_RADIUS_PX = 12;
const DEFAULT_PADDING_RATIO = 0.2;

const Wrapper = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: ${({ $size }) => $size}px;
    height: ${({ $size }) => $size}px;
    border-radius: ${({ $shape, $radius }) =>
        $shape === 'rounded' ? `${$radius}px` : '50%'};
    background: ${AVATAR_BG};
    flex-shrink: 0;
    box-sizing: border-box;
    padding: ${({ $size, $paddingRatio }) =>
        Math.round(($size || 0) * ($paddingRatio ?? DEFAULT_PADDING_RATIO))}px;
    overflow: hidden;
    ${({ $activeBorderColor }) =>
        $activeBorderColor
            ? css`
                  border: 2px solid ${$activeBorderColor};
              `
            : ''}
`;

const Img = styled.img`
    display: block;
    width: 100%;
    height: 100%;
    object-fit: contain;
    /* The identicon is transparent, so its own bg is irrelevant — but
     * we set it for safety in case a non-identicon dicebear style gets
     * swapped in later. */
    background: transparent;
`;

const UserAvatar = forwardRef(function UserAvatar(
    {
        seed,
        size = 32,
        alt = '',
        loading = 'lazy',
        activeBorderColor,
        shape = 'circle',
        radius = DEFAULT_ROUNDED_RADIUS_PX,
        paddingRatio = DEFAULT_PADDING_RATIO,
        className,
        style,
        title,
        ...rest
    },
    ref,
) {
    const src = dicebearAvatarUrl(seed, size);
    return (
        <Wrapper
            ref={ref}
            $size={size}
            $shape={shape}
            $radius={radius}
            $paddingRatio={paddingRatio}
            $activeBorderColor={activeBorderColor}
            className={className}
            style={style}
            title={title}
            aria-hidden={alt ? undefined : 'true'}
            {...rest}
        >
            <Img src={src} alt={alt} loading={loading} draggable={false} />
        </Wrapper>
    );
});

export default UserAvatar;
