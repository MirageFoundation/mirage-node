const bluemoonDarkColors = {
    bg: '#1A1A1A',
    text: '#FFFFFF',
    subtleText: '#CCCCCC',
    card: '#23272C',
    panel: '#23272C',
    panelAlt: '#33373C',
    border: '#444',
    accent: '#2E3238',
    accentHover: '#3A3F46',
    accentDisabled: '#4A4F55',
    buttonText: '#FFFFFF',
    link: '#FFFFFF',
    linkHover: '#CCCCCC',
    scrollbar: '#CCCCCC',
    cardAlt: '#2A2E33',
    cardBorder: '#444',
    sidebarBg: '#23272C',
    headerBg: '#23272C',
    voteUp: '#16a34a',
    voteUpHover: '#22c55e',
    voteUpBg: 'rgba(22, 163, 74, 0.16)',
    voteDown: '#dc2626',
    voteDownHover: '#ef4444',
    voteDownBg: 'rgba(220, 38, 38, 0.16)',
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

    inboxReplyUnreadBg: 'rgba(59, 130, 246, 0.15)',
    inboxReplyReadBg: 'rgba(255, 255, 255, 0.05)',
    inboxReplyUnreadBorder: 'rgba(59, 130, 246, 0.3)',
    inboxReplyReadBorder: 'rgba(255, 255, 255, 0.1)',
};

const bluemoonLightColors = {
    bg: '#FFFFFF',
    text: '#111827',
    subtleText: '#4B5563',
    card: '#FFFFFF',
    panel: '#F7F7F8',
    panelAlt: '#EFEFF1',
    border: '#D1D5DB',
    accent: '#E5E7EB',
    accentHover: '#D1D5DB',
    accentDisabled: '#F3F4F6',
    buttonText: '#111827',
    link: '#111827',
    linkHover: '#374151',
    scrollbar: '#9CA3AF',
    cardAlt: '#F3F4F6',
    cardBorder: '#D1D5DB',
    sidebarBg: '#F7F7F8',
    headerBg: '#F7F7F8',
    voteUp: '#16a34a',
    voteUpHover: '#15803d',
    voteUpBg: 'rgba(22, 163, 74, 0.16)',
    voteDown: '#dc2626',
    voteDownHover: '#b91c1c',
    voteDownBg: 'rgba(220, 38, 38, 0.16)',
    overlay: 'rgba(0, 0, 0, 0.7)',
    cardShadow: '0 4px 12px rgba(0, 0, 0, 0.1)',
    cardShadowHover: '0 6px 20px rgba(0, 0, 0, 0.15)',
    inboxReplyUnreadBg: 'rgba(59, 130, 246, 0.08)',
    inboxReplyReadBg: 'rgba(0, 0, 0, 0.03)',
    inboxReplyUnreadBorder: 'rgba(59, 130, 246, 0.2)',
    inboxReplyReadBorder: 'rgba(0, 0, 0, 0.05)',

    inboxReplyUnreadBgHover: 'rgba(59, 130, 246, 0.12)',
    inboxReplyReadBgHover: 'rgba(0, 0, 0, 0.05)',

};

function buildLayout(colors) {
    return {
        // Form rows

        fontFamily: "'Noto Sans', sans-serif",
        formRowColumns: 'minmax(140px, 220px) minmax(0, 1fr)',
        formRowGap: '0.5rem',
        formRowMargin: '0.4rem 0',
        formRowAlign: 'start',

        // Labels
        labelSize: '0.85rem',
        labelWeight: '600',
        labelPaddingTop: '0.7rem',

        // Value containers (settings rows, profile fields)
        containerBg: colors.panelAlt,
        containerBorder: `1px solid ${colors.border}`,
        containerBorderBottom: null,
        containerRadius: '8px',
        containerPadding: '0.75rem 1rem',
        containerPaddingCompact: '0.6rem 0.85rem',

        // Inputs / selects
        inputRadius: '8px',
        inputPadding: '0.5rem 0.85rem',
        inputSize: '0.85rem',
        focusRing: '0 0 0 3px rgba(102, 126, 234, 0.15)',

        // Buttons (small inline buttons, not the Button component)
        buttonRadius: '6px',
        buttonPadding: '0.45rem 0.85rem',
        buttonSize: '0.78rem',

        // Typography scale
        bodySize: '0.85rem',
        smallSize: '0.7rem',
        tinySize: '0.6rem',
        monoSize: '0.8rem',

        // Cards / list items
        cardBg: colors.panel,
        cardBorder: `1px solid ${colors.border}`,
        cardBorderBottom: null,
        cardRadius: '8px',
        cardPadding: '0.6rem 0.85rem',
        cardGap: '0.5rem',

        // Sections
        sectionSize: '0.95rem',
        sectionMarginTop: '1.5rem',
        sectionMarginBottom: '0.5rem',

        // Dividers
        dividerMargin: '0.75rem 0',

        // Banners
        bannerRadius: '6px',
        bannerPadding: '0.75rem',
        bannerSize: '0.78rem',

        // Tabs
        showContainerTab: true,

        containerTabLeft: '1rem',
        containerTabRadius: '6px 6px 0 0',
        containerTabPadding: '0.25rem 0.65rem 0.1rem 0.65rem',
        tabSize: '0.75rem',
        tabWeight: '600',

        contentGridCols: '200px minmax(0, 1fr)',
        contentGridGap: '0.5rem',
        contentMaxWidth: '1600px',
        contentMargin: '0 auto',
        contentPadding: '0 0.5rem',
        contentPaddingTablet: '0 0.25rem',

        feedMaxWidth: 'none',
        feedMargin: '0 auto',
        feedPadding: '0 0.75rem',
        feedGap: 'var(--card-gap, 0.5rem)',
        feedPaddingTablet: '0 0.25rem',
        feedGapTablet: '0.4rem',
        feedGapMobile: 'var(--card-gap-mobile, 0.35rem)',

        // Tabbed container (wrapper around ContainerBody)
        tabbedMarginTop: '2.0rem',

        // Container body (panel that holds view content)
        containerBodyBorder: `1px solid ${colors.border}`,
        containerBodyRadius: '12px',
        containerBodyPadding: '1.25rem',
        containerBodyMaxWidth: 'none',
        containerBodyRadiusMobile: '8px',
        containerBodyPaddingMobile: '1rem',

        searchMaxWidth: 'none',
        searchMargin: '0.75rem auto',
        searchPadding: '0 0.75rem',
        searchMarginTablet: '0.5rem auto',
        searchPaddingTablet: '0 0.25rem',
        searchInputPadding: '0.55rem 0.85rem',
        searchInputRadius: '18px',
        searchInputSize: '0.85rem',
        searchFocusShadow: '0 0 0 2px rgba(59, 130, 246, 0.2)',

        // Empty states
        emptyMarginX: '1rem',
        emptyMarginXTablet: '0.25rem',
        emptyPadding: '1.25rem 1rem',
        emptyRadius: '8px',
        emptyTitleSize: '1.1rem',
        emptyTitleMarginBottom: '0.5rem',
        emptyBodySize: '0.75rem',

        // Error banner
        errorMarginX: '1rem',
        errorPadding: '0.1rem 0 0.25rem 0',
        errorBorder: 'none',
        errorJustify: 'center',
        errorAlign: 'center',
        errorSize: '1rem',

        // Vote area (the pill container around up/down/count)
        voteAreaBg: colors.panel,
        voteAreaBorder: `1px solid ${colors.border}`,
        voteAreaRadius: '14px',
        voteAreaShadow: '0 10px 24px rgba(0,0,0,0.14)',
        voteAreaPadding: '8px 6px',
        voteAreaPaddingCompact: '6px 4px',
        voteAreaMarginRight: '0.25rem',
        voteAreaGap: '2px',
        voteAreaGapCompact: '2px',
        voteAreaWidth: '64px',
        voteAreaWidthCompact: '56px',
        voteAreaHeight: '120px',
        voteAreaHeightCompact: '96px',

        // Vote buttons
        voteButtonSize: '32px',
        voteButtonSizeCompact: '28px',
        voteButtonBgInactive: colors.panelAlt,
        voteButtonBorder: `1px solid ${colors.border}`,
        voteButtonRadius: '10px',
        voteButtonHoverTransform: 'translateY(-1px)',
        voteIconSize: '16px',

        // Vote count display
        voteFontSize: '0.95rem',
        voteLineHeight: 'normal',

        // Tabs row positioning
        tabsRowPosition: 'absolute',
        tabsRowBottom: '100%',
        tabsRowLeft: '1rem',
        tabsRowMarginBottom: '-1px',
        tabsRowGap: '0',
        tabsRowBorderBottom: 'none',
        tabsRowBg: 'transparent',
        tabsRowLeftTablet: '0.5rem',

        // Clickable tab
        clickableTabRadius: '6px 6px 0 0',
        clickableTabPadding: '0.25rem 0.65rem 0.1rem 0.65rem',
        clickableTabPaddingTablet: '0.2rem 0.5rem 0.1rem 0.5rem',
        clickableTabMarginRight: '0.25rem',
        clickableTabTextTransform: 'none',
        clickableTabActiveBorderBottom: 'none',
        clickableTabInactiveBorderBottom: 'none',
        clickableTabShowAfter: true,
        tabSizeTablet: '0.7rem',

        flatMode: false,
        maxVideoWidth: null,
        inboxFullWidth: false,
        profilePostsFullWidth: false,
    };
}

export const dark = {
    name: 'dark',
    themeId: 'bluemoon',
    colors: bluemoonDarkColors,
    layout: buildLayout(bluemoonDarkColors),
};

export const light = {
    name: 'light',
    themeId: 'bluemoon',
    colors: bluemoonLightColors,
    layout: buildLayout(bluemoonLightColors),
};
