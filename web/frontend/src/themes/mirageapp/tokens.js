/**
 * Colors ported from `mirage-mobile-app/src/config/theme.ts`.
 * Mobile palette translated into the same key set the existing oldreddit
 * theme uses, so cloned components keep working without prop drift.
 */
const mirageappDarkColors = {
    // Base surfaces
    bg: '#0d0f12',                  // mobile dark background
    text: '#fafafa',                // mobile dark text default
    subtleText: '#98989D',          // mobile dark neutral
    panel: '#15181d',
    panelAlt: '#1c2026',
    // App-wide divider / border color (dark mode).
    border: 'rgb(39, 40, 42)',
    // TopBar / MobileHeader bottom divider (dark mode) — slightly stronger than `border`.
    headerBorder: 'rgb(63, 65, 66)',
    accent: '#1c2026',
    accentHover: '#232830',
    accentDisabled: '#2A2F36',
    buttonText: '#fafafa',
    link: '#4285f4',                // mobile brand
    linkHover: '#6ba0fa',
    scrollbar: '#4a4f57',
    card: '#15181d',
    cardAlt: '#1c2026',
    cardBorder: '#2A2F36',
    sidebarBg: '#15181d',
    headerBg: '#15181d',

    // Vote palette uses mobile success/error so it matches the app feel
    voteUp: '#16A34A',
    voteUpHover: '#22C55E',
    voteUpBg: 'rgba(22, 163, 74, 0.18)',
    voteDown: '#FF453A',
    voteDownHover: '#ef4444',
    voteDownBg: 'rgba(255, 69, 58, 0.18)',

    overlay: 'rgba(0, 0, 0, 0.7)',
    cardShadow: 'none',
    cardShadowHover: 'none',

    // Surface tiers + form input backgrounds
    surface: '#15181d',
    surface2: '#1c2026',
    surface3: '#232830',
    borderSubtle: '#1f242b',
    borderStrong: '#3a4049',
    textSecondary: '#98989D',
    inputBackground: '#1c2026',
    accentSubtle: '#15181d',
    cardHoverBorder: '#3a4049',

    // Inbox reply rows — mobile-app style: transparent read rows on the bg
    // canvas, a lifted neutral tile on unread rows. Colors from UI review.
    inboxReplyUnreadBg: 'rgb(34, 39, 42)',
    inboxReplyReadBg: 'transparent',
    inboxReplyUnreadBorder: 'transparent',
    inboxReplyReadBorder: 'transparent',
    inboxReplyUnreadBgHover: 'rgb(44, 50, 54)',
    inboxReplyReadBgHover: 'rgb(25, 28, 31)',
    // Inbox header "Mark all as read" button text (rest color). Dark mode
    // reuses the sidebar item text color; light mode diverges to a darker
    // near-black per UI review. Hover still lifts to `sidebarItemActiveText`.
    inboxMarkAllText: 'rgb(221, 228, 232)',

    // Button color variants tied to mobile success/error
    buttonDangerBg: 'rgba(255, 69, 58, 0.18)',
    buttonDangerBorder: '#993332',
    buttonDangerHoverBg: 'rgba(255, 69, 58, 0.28)',
    buttonSuccessBg: 'rgba(22, 163, 74, 0.18)',
    buttonSuccessBorder: '#2f5e3a',
    buttonSuccessHoverBg: 'rgba(22, 163, 74, 0.28)',
    navActiveBg: '#1c2026',

    // Main Mirage app gradient (ported from mirage-mobile-app quests/new-posts/feed-type)
    // Used for primary CTAs and accent borders.
    gradientStart: '#667eea',
    gradientEnd: '#764ba2',
    gradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',

    // Mobile app's primary button blue (`brand: #4285f4` in mirage-mobile-app/src/config/theme.ts).
    // Used for input focus rings and active states that should read as "interactive blue".
    focusBlue: '#4285f4',

    // Hover background for interactive surfaces in TopBar / Sidebar / menus.
    // Dark mode: requested value from UI review.
    hoverBg: 'rgb(25, 28, 31)',

    // Search input inline action icons (clear "X" button, etc.) — dark mode.
    inputIconColor: 'rgb(143, 161, 172)',
    inputIconHoverBg: 'rgb(53, 61, 65)',

    // Sidebar option colors (dark mode).
    sidebarItemText: 'rgb(221, 228, 232)',
    sidebarItemActiveText: '#FFFFFF',
    sidebarItemActiveBg: 'rgb(44, 50, 54)',

    // Sidebar collapse/menu toggle button (dark mode).
    menuBtnBorder: 'rgb(134, 136, 137)',
    menuBtnBorderHover: '#FFFFFF',
    menuBtnIcon: '#FFFFFF',

    // Feed toolbar controls (sort button + view button) — dark mode.
    // Text + icon share the same color; hover bg is a subtle neutral tile.
    feedCtrlText: 'rgb(143, 161, 172)',
    feedCtrlHoverBg: 'rgb(53, 61, 65)',

    // Popover/menu surfaces (sort + view dropdowns) — dark mode.
    menuBg: 'rgb(25, 28, 31)',
    menuSelectedBg: 'rgb(44, 50, 54)',
    menuHeaderText: 'rgb(187, 202, 211)',

    // Follow button (post card header) — dark mode.
    followBtnBg: 'rgb(42, 90, 195)',
    followBtnBgHover: 'rgb(54, 110, 236)',
    /* Border for the "Following" (active) state of the follow pill, plus
     * the hover lift. Spec colors from UI review. */
    followBtnBorder: 'rgb(140, 141, 143)',
    followBtnBorderHover: '#FFFFFF',

    // Bottom action-row icon button chip (block / share pills) — dark mode.
    actionIconBg: 'rgb(44, 50, 54)',
    // Hover tile for vote pill / comment pill / share / block / 3-dots
    // at the bottom of a post card (dark mode).
    actionIconHoverBg: 'rgb(53, 61, 65)',

    // Dropdown menu option hover (dark mode): bg stays unchanged, but text
    // + icons lift to pure white. We express this as a transparent hover
    // bg + a dedicated hover text token so styled-components can branch
    // cleanly on theme values (no runtime mode check).
    menuItemHoverBg: 'transparent',
    menuItemHoverText: '#FFFFFF',
    /* Lighter red used for danger-labelled dropdown rows at rest (block,
     * report, delete). Hover still uses the punchier `voteDown`, so the
     * row picks up saturation when the pointer enters. */
    menuDangerText: '#FF7B70',
};

const mirageappLightColors = {
    // Base surfaces
    bg: '#FFFFFC',                  // mobile light background
    text: '#202329',                // mobile light text default
    subtleText: '#6B7280',          // mobile light neutral
    panel: '#FFFFFF',
    panelAlt: '#F7F8FA',
    // App-wide divider / border color (light mode).
    border: 'rgb(230, 230, 230)',
    // TopBar / MobileHeader bottom divider (light mode) — slightly stronger than `border`.
    headerBorder: 'rgb(204, 204, 204)',
    accent: '#F3F4F6',
    accentHover: '#E5E7EB',
    accentDisabled: '#F3F4F6',
    buttonText: '#202329',
    link: '#4285f4',                // mobile brand
    linkHover: '#2563eb',
    scrollbar: '#C1C1C1',
    card: '#FFFFFF',
    cardAlt: '#F7F8FA',
    cardBorder: '#E5E7EB',
    sidebarBg: '#FFFFFF',
    headerBg: '#FFFFFF',

    voteUp: '#16A34A',
    voteUpHover: '#15803d',
    voteUpBg: 'rgba(22, 163, 74, 0.12)',
    voteDown: '#FF3B30',
    voteDownHover: '#DC2626',
    voteDownBg: 'rgba(255, 59, 48, 0.12)',

    overlay: 'rgba(0, 0, 0, 0.5)',
    cardShadow: '0 1px 3px rgba(0, 0, 0, 0.06)',
    cardShadowHover: '0 2px 6px rgba(0, 0, 0, 0.1)',

    surface: '#F7F8FA',
    surface2: '#EFF1F5',
    surface3: '#E5E7EB',
    borderSubtle: '#EDEFF2',
    borderStrong: '#9CA3AF',
    textSecondary: '#4B5563',
    inputBackground: '#FFFFFF',
    accentSubtle: '#F7F8FA',
    cardHoverBorder: '#9CA3AF',

    // Inbox reply rows — mobile-app style: transparent read rows on the bg
    // canvas, a lifted neutral tile on unread rows. Light-mode pairs for
    // the dark values in `mirageappDarkColors`.
    inboxReplyUnreadBg: 'rgb(239, 241, 243)',
    inboxReplyReadBg: 'transparent',
    inboxReplyUnreadBorder: 'transparent',
    inboxReplyReadBorder: 'transparent',
    inboxReplyUnreadBgHover: 'rgb(230, 235, 238)',
    inboxReplyReadBgHover: 'rgb(246, 248, 249)',
    // Inbox header "Mark all as read" button text (rest color). Light-mode
    // diverges from `sidebarItemText` to a darker near-black per UI review.
    inboxMarkAllText: 'rgb(25, 28, 31)',

    buttonDangerBg: 'rgba(255, 59, 48, 0.12)',
    buttonDangerBorder: '#FF3B30',
    buttonDangerHoverBg: 'rgba(255, 59, 48, 0.2)',
    buttonSuccessBg: 'rgba(22, 163, 74, 0.12)',
    buttonSuccessBorder: '#16A34A',
    buttonSuccessHoverBg: 'rgba(22, 163, 74, 0.2)',
    navActiveBg: '#EFF1F5',

    // Main Mirage app gradient (ported from mirage-mobile-app quests/new-posts/feed-type)
    gradientStart: '#667eea',
    gradientEnd: '#764ba2',
    gradient: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',

    // Mobile app's primary button blue (`brand: #4285f4`).
    focusBlue: '#4285f4',

    // Hover background for interactive surfaces in TopBar / Sidebar / menus.
    // Light mode: requested value from UI review.
    hoverBg: 'rgb(246, 248, 249)',

    // Search input inline action icons (clear "X" button, etc.) — light mode.
    inputIconColor: 'rgb(95, 108, 115)',
    inputIconHoverBg: 'rgb(221, 238, 232)',

    // Sidebar option colors (light mode).
    sidebarItemText: 'rgb(34, 39, 42)',
    sidebarItemActiveText: '#000000',
    sidebarItemActiveBg: 'rgb(230, 235, 238)',

    // Sidebar collapse/menu toggle button (light mode).
    menuBtnBorder: 'rgb(128, 128, 128)',
    menuBtnBorderHover: '#000000',
    menuBtnIcon: '#000000',

    // Feed toolbar controls (sort button + view button) — light mode.
    feedCtrlText: 'rgb(95, 108, 115)',
    feedCtrlHoverBg: 'rgb(221, 228, 232)',

    // Popover/menu surfaces (sort + view dropdowns) — light mode.
    menuBg: 'rgb(255, 255, 255)',
    menuSelectedBg: 'rgb(230, 235, 238)',
    menuHeaderText: 'rgb(95, 108, 115)',

    // Follow button (post card header) — light mode.
    followBtnBg: 'rgb(30, 67, 150)',
    followBtnBgHover: 'rgb(21, 46, 104)',
    /* Border for the "Following" (active) state of the follow pill, plus
     * the hover lift. Spec colors from UI review. */
    followBtnBorder: 'rgb(124, 125, 125)',
    followBtnBorderHover: '#000000',

    // Bottom action-row icon button chip (block / share pills) — light mode.
    actionIconBg: 'rgb(230, 235, 238)',
    // Hover tile for vote pill / comment pill / share / block / 3-dots
    // at the bottom of a post card (light mode).
    actionIconHoverBg: 'rgb(221, 228, 232)',

    // Dropdown menu option hover (light mode): bg lifts to a neutral tile,
    // text stays the normal sidebar item color (unchanged).
    menuItemHoverBg: 'rgb(246, 248, 249)',
    menuItemHoverText: 'rgb(34, 39, 42)',
    /* Lighter red used for danger-labelled dropdown rows at rest. Hover
     * still uses the saturated `voteDown` so the row picks up emphasis
     * when the pointer enters. */
    menuDangerText: '#FF6A5E',
};

function buildLayout(colors) {
    return {
        // Form rows

        fontFamily: "Verdana, Geneva, 'DejaVu Sans', sans-serif",
        formRowColumns: 'minmax(140px, 260px) minmax(0, 1fr)',
        formRowGap: '0.25rem',
        formRowMargin: '0.15rem 0',
        formRowAlign: 'start',

        // Labels
        labelSize: '0.7rem',
        labelWeight: '700',
        labelPaddingTop: '0.35rem',

        // Value containers (settings rows, profile fields)
        containerBg: 'transparent',
        containerBorder: 'none',
        containerBorderBottom: `1px solid ${colors.border}`,
        containerRadius: '0',
        containerPadding: '0.3rem 0',
        containerPaddingCompact: '0.3rem 0',

        // Inputs / selects
        inputRadius: '0',
        inputPadding: '0.25rem 0.4rem',
        inputSize: '0.7rem',
        focusRing: 'none',

        // Buttons (small inline buttons)
        buttonRadius: '0',
        buttonPadding: '0.25rem 0.5rem',
        buttonSize: '0.65rem',

        // Typography scale
        bodySize: '0.7rem',
        smallSize: '0.6rem',
        tinySize: '0.55rem',
        monoSize: '0.7rem',

        // Cards / list items
        cardBg: 'transparent',
        cardBorder: 'none',
        cardBorderBottom: `1px solid ${colors.border}`,
        cardRadius: '0',
        cardPadding: '0.35rem 0.4rem',
        cardGap: '0',

        // Sections
        sectionSize: '0.75rem',
        sectionMarginTop: '0.75rem',
        sectionMarginBottom: '0.25rem',

        // Dividers
        dividerMargin: '0.35rem 0',

        // Banners
        bannerRadius: '0',
        bannerPadding: '0.4rem 0.5rem',
        bannerSize: '0.65rem',

        // Tabs
        showContainerTab: false,

        containerTabLeft: '0',
        containerTabRadius: '0',
        containerTabPadding: '0',
        tabSize: '0.65rem',
        tabWeight: '700',

        // Content grid — full width, no left sidebar (classic old.reddit list layout)
        contentGridCols: 'minmax(0, 1fr)',
        contentGridGap: '0',
        contentMaxWidth: 'none',
        contentMargin: '0',
        contentPadding: '0',
        contentPaddingTablet: '0',

        // Feed container
        feedMaxWidth: 'none',
        feedMargin: '0',
        feedPadding: '0',
        feedGap: '0',
        feedPaddingTablet: '0',
        feedGapTablet: '0',
        feedGapMobile: '0',

        // Tabbed container
        tabbedMarginTop: '0.25rem',

        // Container body
        containerBodyBorder: 'none',
        containerBodyRadius: '0',
        containerBodyPadding: '0.75rem 0',
        containerBodyMaxWidth: 'none',
        containerBodyRadiusMobile: '0',
        containerBodyPaddingMobile: '0.5rem 0',

        // Search
        searchMaxWidth: 'none',
        searchMargin: '0.5rem 0',
        searchPadding: '0',
        searchMarginTablet: '0.35rem 0',
        searchPaddingTablet: '0',
        searchInputPadding: '0.35rem 0.5rem',
        searchInputRadius: '0',
        searchInputSize: '0.75rem',
        searchFocusShadow: 'none',

        // Empty states
        emptyMarginX: '0',
        emptyMarginXTablet: '0',
        emptyPadding: '0.75rem 0.5rem',
        emptyRadius: '0',
        emptyTitleSize: '0.85rem',
        emptyTitleMarginBottom: '0.25rem',
        emptyBodySize: '0.7rem',

        // Error banner
        errorMarginX: '0',
        errorPadding: '0.25rem 0.5rem',
        errorBorder: `1px solid ${colors.border}`,
        errorJustify: 'flex-start',
        errorAlign: 'left',
        errorSize: '0.75rem',

        // Vote area
        voteAreaBg: 'transparent',
        voteAreaBorder: 'none',
        voteAreaRadius: '0',
        voteAreaShadow: 'none',
        voteAreaPadding: '0',
        voteAreaPaddingCompact: '0',
        voteAreaMarginRight: '0',
        voteAreaGap: '0',
        voteAreaGapCompact: '0',
        voteAreaWidth: 'auto',
        voteAreaWidthCompact: 'auto',
        voteAreaHeight: 'auto',
        voteAreaHeightCompact: 'auto',

        // Vote buttons
        voteButtonSize: '34px',
        voteButtonSizeCompact: '34px',
        voteButtonBgInactive: 'transparent',
        voteButtonBorder: 'none',
        voteButtonRadius: '0',
        voteButtonHoverTransform: 'none',
        voteIconSize: '25px',

        // Vote count display
        voteFontSize: '0.7rem',
        voteLineHeight: '1',

        // Tabs row positioning
        tabsRowPosition: 'static',
        tabsRowBottom: 'auto',
        tabsRowLeft: 'auto',
        tabsRowMarginBottom: '0',
        tabsRowGap: '0',
        tabsRowBorderBottom: `1px solid ${colors.border}`,
        tabsRowBg: colors.panel,
        tabsRowLeftTablet: 'auto',

        // Clickable tab
        clickableTabRadius: '0',
        clickableTabPadding: '0.3rem 0.5rem',
        clickableTabPaddingTablet: '0.25rem 0.4rem',
        clickableTabMarginRight: '0',
        clickableTabTextTransform: 'lowercase',
        clickableTabActiveBorderBottom: `2px solid ${colors.text}`,
        clickableTabInactiveBorderBottom: '2px solid transparent',
        clickableTabShowAfter: false,
        tabSizeTablet: '0.6rem',

        // mirageapp is a mobile-app-inspired theme — pills + rounded panels are on-brand,
        // so we opt out of the oldreddit-era `border-radius: 0 !important` reset in Style.js.
        flatMode: false,
        maxVideoWidth: 600,
        inboxFullWidth: true,
        profilePostsFullWidth: true,
    };
}

export const dark = {
    name: 'dark',
    themeId: 'mirageapp',
    fontFamily: "Verdana, Geneva, 'DejaVu Sans', sans-serif",
    colors: mirageappDarkColors,
    layout: buildLayout(mirageappDarkColors),
};

export const light = {
    name: 'light',
    themeId: 'mirageapp',
    fontFamily: "Verdana, Geneva, 'DejaVu Sans', sans-serif",
    colors: mirageappLightColors,
    layout: buildLayout(mirageappLightColors),
};
