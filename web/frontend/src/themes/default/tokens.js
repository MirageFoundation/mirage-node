/**
 * Colors ported from `mirage-mobile-app/src/config/theme.ts`.
 * Mobile palette translated into the shared web token contract.
 */
const defaultDarkColors = {
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
    borderStrong: '#525b66',
    textSecondary: '#98989D',
    inputBackground: '#1c2026',
    accentSubtle: '#15181d',
    cardHoverBorder: '#525b66',

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

    inboxHighlightRail: '#FACC15',
    inboxHighlightBg: 'rgba(250, 204, 21, 0.06)',

    // Reply composer live-preview surface. A subtly-lifted tile so the
    // preview block reads distinct from the textarea (which sits on `bg`).
    composerPreviewBg: 'rgb(26, 28, 31)',

    // Sticker / GIF picker popover surface. Sits one tone above `bg` so
    // the popover reads as a dedicated sheet without competing with menus.
    pickerBg: 'rgb(25, 28, 31)',

    // Button color variants tied to mobile success/error
    buttonDangerBg: 'rgba(255, 69, 58, 0.18)',
    buttonDangerBorder: '#993332',
    buttonDangerHoverBg: 'rgba(255, 69, 58, 0.28)',
    buttonSuccessBg: 'rgba(22, 163, 74, 0.18)',
    buttonSuccessBorder: '#2f5e3a',
    buttonSuccessHoverBg: 'rgba(22, 163, 74, 0.28)',
    navActiveBg: '#1c2026',

    // Canonical warning palette. Identical in both modes, matching the amber
    // already inlined by SettingsView, WelcomeView, CreatePostView and
    // SubscriptionView; those raw rgba literals should migrate onto these.
    warningBg: 'rgba(245, 158, 11, 0.08)',
    warningBorder: 'rgba(245, 158, 11, 0.25)',
    warningHoverBg: 'rgba(245, 158, 11, 0.15)',
    warningText: '#f59e0b',

    // Main Mirage gradient for primary CTAs and accent borders.
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

    cardBodyText: 'rgb(187, 201, 211)',

    // Comment thread rails (J-curve elbow + avatar spine) on post-details
    // screen. Dedicated token so rails can diverge from `borderSubtle`.
    commentThread: 'rgb(47, 48, 47)',

    // DiceBear avatar chip background (UserAvatar + PostPlaceholderAvatar).
    // Identicon/shapes PNGs are transparent, so this fills the negative
    // space behind the glyph. Dark mode uses `surface3` so the chip reads
    // as a lifted neutral tile against `bg`/`panel`.
    avatarBg: '#232830',

    // Admin tier accent (R2). Used wherever `getTierColor(userLevel)` would
    // resolve to the shared `ADMIN_COLOR` from `logic/useSubscription.js`
    // (admin tier label, admin chip, admin section accents). Kept in tokens
    // so light mode can diverge per R2 without touching the cross-theme
    // helper. Sub-plan 06.11.A.
    tierAdmin: '#EF4444',
};

const defaultLightColors = {
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
    // the dark values in `defaultDarkColors`.
    inboxReplyUnreadBg: 'rgb(239, 241, 243)',
    inboxReplyReadBg: 'transparent',
    inboxReplyUnreadBorder: 'transparent',
    inboxReplyReadBorder: 'transparent',
    inboxReplyUnreadBgHover: 'rgb(230, 235, 238)',
    inboxReplyReadBgHover: 'rgb(246, 248, 249)',
    // Inbox header "Mark all as read" button text (rest color). Light-mode
    // diverges from `sidebarItemText` to a darker near-black per UI review.
    inboxMarkAllText: 'rgb(25, 28, 31)',

    inboxHighlightRail: '#D97706',
    inboxHighlightBg: 'rgba(217, 119, 6, 0.08)',

    // Reply composer live-preview surface (light-mode pair).
    composerPreviewBg: 'rgb(246, 248, 249)',

    // Sticker / GIF picker popover surface (light-mode pair).
    pickerBg: 'rgb(246, 248, 249)',

    buttonDangerBg: 'rgba(255, 59, 48, 0.12)',
    buttonDangerBorder: '#FF3B30',
    buttonDangerHoverBg: 'rgba(255, 59, 48, 0.2)',
    buttonSuccessBg: 'rgba(22, 163, 74, 0.12)',
    buttonSuccessBorder: '#16A34A',
    buttonSuccessHoverBg: 'rgba(22, 163, 74, 0.2)',
    navActiveBg: '#EFF1F5',

    // Canonical warning palette (light-mode pair — the amber is deliberately
    // shared across both modes, like `link` and `focusBlue`).
    warningBg: 'rgba(245, 158, 11, 0.08)',
    warningBorder: 'rgba(245, 158, 11, 0.25)',
    warningHoverBg: 'rgba(245, 158, 11, 0.15)',
    warningText: '#f59e0b',

    // Main Mirage gradient.
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

    cardBodyText: 'rgb(53, 61, 65)',

    // Comment thread rails (light-mode pair for `commentThread`).
    commentThread: 'rgb(222, 224, 222)',

    // DiceBear avatar chip background (light-mode pair for `avatarBg`).
    // A soft mid-slate so the chip reads as a distinct surface against
    // the near-white page bg without the dark-mode `#232830` punching
    // a heavy hole into the light layout. Sits darker than `surface3`
    // (which dissolves into the page) and lighter than `borderStrong`,
    // giving the colored identicon glyph enough contrast to pop.
    avatarBg: '#C4CAD3',

    // Admin tier accent (R2 light-mode pair for `tierAdmin`). Slightly
    // deeper than the dark-mode hex so it stays legible on the near-white
    // page bg. Sub-plan 06.11.A.
    tierAdmin: '#DC2626',
};

function buildLayout(colors) {
    return {
        // Form rows

        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
        contentFontFamily: "Verdana, Geneva, 'DejaVu Sans', sans-serif",
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

        // default is a mobile-app-inspired theme — pills + rounded panels are on-brand,
        // so we opt out of the global square-corner reset in Style.js.
        flatMode: false,
        maxVideoWidth: 600,
        inboxFullWidth: true,
        profilePostsFullWidth: true,
    };
}

export const dark = {
    name: 'dark',
    themeId: 'default',
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    contentFontFamily: "Verdana, Geneva, 'DejaVu Sans', sans-serif",
    colors: defaultDarkColors,
    layout: buildLayout(defaultDarkColors),
};

export const light = {
    name: 'light',
    themeId: 'default',
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
    contentFontFamily: "Verdana, Geneva, 'DejaVu Sans', sans-serif",
    colors: defaultLightColors,
    layout: buildLayout(defaultLightColors),
};
