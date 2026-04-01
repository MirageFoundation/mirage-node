const oldredditDarkColors = {
    bg: '#1a1a1b',
    text: '#d7dadc',
    subtleText: '#818384',
    panel: '#1a1a1b',
    panelAlt: '#272729',
    border: '#343536',
    accent: '#272729',
    accentHover: '#3a3a3c',
    accentDisabled: '#3a3a3c',
    buttonText: '#d7dadc',
    link: '#4fbcff',
    linkHover: '#7fcfff',
    scrollbar: '#4a4a4c',
    card: '#1a1a1b',
    cardAlt: '#222224',
    cardBorder: '#343536',
    sidebarBg: '#1a1a1b',
    headerBg: '#1a1a1b',
    voteUp: '#ff4500',
    voteUpHover: '#ff5722',
    voteUpBg: 'rgba(255, 69, 0, 0.15)',
    voteDown: '#7193ff',
    voteDownHover: '#5a7cff',
    voteDownBg: 'rgba(113, 147, 255, 0.15)',
    overlay: 'rgba(0, 0, 0, 0.7)',
    cardShadow: 'none',
    cardShadowHover: 'none',

    surface: '#23272C',
    surface2: '#33373C',
    surface3: '#3A3F46',
    borderSubtle: '#333',
    borderStrong: '#555',
    textSecondary: '#CCCCCC',
    inputBackground: '#33373C',
    accentSubtle: '#2A2E33',
    cardHoverBorder: '#555',

    inboxReplyUnreadBg: '#33373C',
    inboxReplyReadBg: '#23272C',
    inboxReplyUnreadBorder: '#444',
    inboxReplyReadBorder: '#444',

    inboxReplyUnreadBgHover: '#3A3F46',
    inboxReplyReadBgHover: '#2A2E33',

    buttonDangerBg: 'rgba(220, 38, 38, 0.15)',
    buttonDangerBorder: '#7A3E3E',
    buttonDangerHoverBg: 'rgba(220, 38, 38, 0.25)',
    buttonSuccessBg: 'rgba(34, 197, 94, 0.15)',
    buttonSuccessBorder: '#3E6A3E',
    buttonSuccessHoverBg: 'rgba(34, 197, 94, 0.25)',
    navActiveBg: '#33373C',
};

const oldredditLightColors = {
    bg: '#dae0e6',
    text: '#1c1c1c',
    subtleText: '#7c7c7c',
    panel: '#ffffff',
    panelAlt: '#f6f7f8',
    border: '#ccc',
    accent: '#f6f7f8',
    accentHover: '#e8e8e8',
    accentDisabled: '#eee',
    buttonText: '#1c1c1c',
    link: '#0079d3',
    linkHover: '#0059a3',
    scrollbar: '#c1c1c1',
    card: '#ffffff',
    cardAlt: '#f6f7f8',
    cardBorder: '#ccc',
    sidebarBg: '#ffffff',
    headerBg: '#f6f7f8',
    voteUp: '#ff4500',
    voteUpHover: '#cc3700',
    voteUpBg: 'rgba(255, 69, 0, 0.1)',
    voteDown: '#7193ff',
    voteDownHover: '#4a6cff',
    voteDownBg: 'rgba(113, 147, 255, 0.1)',
    overlay: 'rgba(0, 0, 0, 0.7)',
    cardShadow: 'none',
    cardShadowHover: 'none',

    surface: '#F7F7F8',
    surface2: '#EFEFF1',
    surface3: '#E5E7EB',
    borderSubtle: '#E5E7EB',
    borderStrong: '#9CA3AF',
    textSecondary: '#4B5563',
    inputBackground: '#EFEFF1',
    accentSubtle: '#F3F4F6',
    cardHoverBorder: '#9CA3AF',

    inboxReplyUnreadBg: '#EFEFF1',
    inboxReplyReadBg: '#F7F7F8',
    inboxReplyUnreadBorder: '#D1D5DB',
    inboxReplyReadBorder: '#D1D5DB',

    buttonDangerBg: 'rgba(220, 38, 38, 0.12)',
    buttonDangerBorder: '#dc2626',
    buttonDangerHoverBg: 'rgba(220, 38, 38, 0.2)',
    buttonSuccessBg: 'rgba(22, 163, 74, 0.12)',
    buttonSuccessBorder: '#16a34a',
    buttonSuccessHoverBg: 'rgba(22, 163, 74, 0.2)',
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

        flatMode: true,
        maxVideoWidth: 800,
        inboxFullWidth: true,
        profilePostsFullWidth: true,
    };
}

export const dark = {
    name: 'dark',
    themeId: 'oldreddit',
    fontFamily: "Verdana, Geneva, 'DejaVu Sans', sans-serif",
    colors: oldredditDarkColors,
    layout: buildLayout(oldredditDarkColors),
};

export const light = {
    name: 'light',
    themeId: 'oldreddit',
    fontFamily: "Verdana, Geneva, 'DejaVu Sans', sans-serif",
    colors: oldredditLightColors,
    layout: buildLayout(oldredditLightColors),
};
