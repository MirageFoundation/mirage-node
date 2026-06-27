import styled from "styled-components";

/**
 * Shared feed-column layout primitives for the default
 * theme. Extracted from `MainView` so multiple routes (home feed, post
 * details / comments view, etc.) can render the same 720 px feed column
 * with consistent desktop centering.
 *
 * The two components cooperate via attribute selectors — `FeedRailRow`
 * mirrors the caller's `$feedViewMode` onto `data-feed-view-mode`, and
 * `DefaultShell::Main` mirrors sidebar visibility onto the
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
        /* Always fill at least the Main column's viewport height so short
         * states (empty inbox, single post, loading state, etc.) keep the
         * same page rhythm as full feeds.
         *
         * Math: Layout shell is min-height: calc(100vh - 2.5rem - 1px)
         * (TopBar + divider). Main adds 0.5rem top + 3rem bottom
         * padding, so the inner content box is that minus 3.5rem. */
        min-height: calc(100vh - 2.5rem - 1px - 3.5rem);

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

        /* Sidebar hidden (card OR compact): center the feed column inside
         * Main. Compact now matches card exactly so the feed column width
         * is identical in both view modes. */
        [data-sidebar-hidden='true'] &[data-feed-view-mode='card'],
        [data-sidebar-hidden='true'] &[data-feed-view-mode='compact'] {
            max-width: 820px;
            margin-left: auto;
            margin-right: auto;
            gap: 1.5rem;
        }
    }

    /* Very large screens (> average laptop): ALWAYS center the feed column
     * inside Main regardless of sidebar visibility or view mode. Higher specificity
     * (two attribute selectors) so these rules beat the 1001px rules
     * above even at equal cascade order. Feed column grows to 960 px
     * (up from the 820 px laptop cap) so content reads more comfortably
     * on large desktops / external monitors. */
    @media (min-width: 1500px) {
        [data-sidebar-hidden] &[data-feed-view-mode] {
            max-width: 960px;
            margin-left: auto;
            margin-right: auto;
            gap: 1.5rem;
        }
    }

    /* Ultrawide / 4K displays (> 1900 px): feed column grows to 1200 px
     * so the feed fills more of the viewport on large external monitors. */
    @media (min-width: 1900px) {
        [data-sidebar-hidden] &[data-feed-view-mode] {
            max-width: 1200px;
            margin-left: auto;
            margin-right: auto;
            gap: 1.5rem;
        }
    }
`;

/**
 * Feed column inside `FeedRailRow`.
 *   - Sidebar visible (card or compact): 820 px fixed track.
 *   - Sidebar hidden (card or compact): 820 px fixed and centered.
 *     Compact mode intentionally matches card so the feed width is
 *     identical in both modes.
 *   - >= 1500 px (large desktops): column grows to 960 px.
 *   - <= 1000 px: collapses to viewport-filling width (rail hidden).
 */
export const FeedCol = styled.div`
    min-width: 0;

    @media (min-width: 1001px) {
        flex: 0 0 820px;
        width: 820px;
        max-width: 820px;
    }

    /* Large-screen centered layout — feed column grows to 960 px on
     * viewports >= 1500 px so the content reads more comfortably on
     * larger desktops / external monitors. */
    @media (min-width: 1500px) {
        [data-feed-view-mode] & {
            flex: 0 0 960px;
            width: 960px;
            max-width: 960px;
        }
    }

    /* Ultrawide / 4K displays (> 1900 px): feed column grows to 1200 px
     * so the feed fills more of the available space on large monitors. */
    @media (min-width: 1900px) {
        [data-feed-view-mode] & {
            flex: 0 0 1200px;
            width: 1200px;
            max-width: 1200px;
        }
    }

    @media (max-width: 1000px) {
        flex: 1 1 auto;
        width: 100%;
    }
`;
