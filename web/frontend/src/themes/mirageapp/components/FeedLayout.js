import styled from "styled-components";

/**
 * Shared feed-column + right-rail layout primitives for the mirageapp
 * theme. Extracted from `MainView` so multiple routes (home feed, post
 * details / comments view, etc.) can render the same 720 px feed column
 * with the `FeedRightRail` footer pinned on the right edge.
 *
 * The two components cooperate via attribute selectors — `FeedRailRow`
 * mirrors the caller's `$feedViewMode` onto `data-feed-view-mode`, and
 * `MirageAppShell::Main` mirrors sidebar visibility onto the
 * `data-sidebar-hidden` attribute. All width/centering rules below are
 * scoped against those two data attributes so the same markup responds
 * to sidebar toggles without any JS bookkeeping in the consuming route.
 *
 * See the original comment block in `MainView.js` for the full
 * breakdown of breakpoints and width rules.
 */
export const FeedRailRow = styled.div.attrs(({ $feedViewMode }) => ({
    'data-feed-view-mode': $feedViewMode,
}))`
    display: flex;
    flex-direction: row;
    align-items: stretch;
    gap: 0;
    width: 100%;
    box-sizing: border-box;

    @media (min-width: 1001px) {
        /* Neutralise width caps that ListFeedView / FeedHeroColumn apply
         * based on data-feed-view-mode. !important is required because
         * the ListFeedView "compact hidden -> 80 percent" rule has higher
         * specificity (data-sidebar-hidden + data-feed-view-mode) than
         * any selector we could practically chain here, and without this
         * override the feed renders at 80 percent of FeedCol, leaving a
         * visible gap between the feed and the rail. */
        & [data-feed-view-mode] {
            width: 100% !important;
            max-width: none !important;
            margin-left: 0 !important;
            margin-right: 0 !important;
        }

        /* Sidebar visible (card or compact): small breathing gap between
         * feed and rail so they do not butt together. */
        [data-sidebar-hidden='false'] &[data-feed-view-mode] {
            gap: 1.5rem;
        }

        /* Sidebar hidden (card OR compact): center the feed + rail pair
         * as a single block inside Main with the same breathing gap as
         * the sidebar-visible states. Compact now matches card exactly
         * so the feed column width + rail placement are identical in
         * both view modes. */
        [data-sidebar-hidden='true'] &[data-feed-view-mode='card'],
        [data-sidebar-hidden='true'] &[data-feed-view-mode='compact'] {
            max-width: calc(720px + 1.5rem + 260px);
            margin-left: auto;
            margin-right: auto;
            gap: 1.5rem;
        }
    }

    /* Very large screens (> average laptop): ALWAYS center the feed+rail
     * pair inside Main with a consistent 1.5rem gap between them,
     * regardless of sidebar visibility or view mode. Higher specificity
     * (two attribute selectors) so these rules beat the 1001px rules
     * above even at equal cascade order. */
    @media (min-width: 1500px) {
        [data-sidebar-hidden] &[data-feed-view-mode] {
            max-width: calc(720px + 1.5rem + 260px);
            margin-left: auto;
            margin-right: auto;
            gap: 1.5rem;
        }
    }
`;

/**
 * Feed column inside `FeedRailRow`.
 *   - Sidebar visible (card or compact): 720 px fixed track.
 *   - Sidebar hidden (card or compact): 720 px fixed (centered with
 *     the rail). Compact mode intentionally matches card so the feed
 *     width + rail placement are identical in both modes.
 *   - <= 1000 px: collapses to viewport-filling width (rail hidden).
 */
export const FeedCol = styled.div`
    min-width: 0;

    @media (min-width: 1001px) {
        flex: 0 0 720px;
        width: 720px;
        max-width: 720px;
    }

    /* Large-screen centered layout — redundant with the 1001px rule
     * above now that compact no longer flex-grows, but kept for clarity
     * so the intent ("feed is always 720 px above 1000 px") is obvious
     * at both breakpoints. */
    @media (min-width: 1500px) {
        [data-feed-view-mode] & {
            flex: 0 0 720px;
            width: 720px;
            max-width: 720px;
        }
    }

    @media (max-width: 1000px) {
        flex: 1 1 auto;
        width: 100%;
    }
`;
