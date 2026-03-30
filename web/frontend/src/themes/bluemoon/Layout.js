import styled from "styled-components";

/** Blue Moon theme only — styled layout primitives; not shared with other themes. */

/**
 * RESPONSIVE BREAKPOINTS
 * 
 * Desktop: > 1000px
 *   - Sidebar visible
 *   - Full cards with thumbnails
 * 
 * Tablet: 601px - 1000px
 *   - Sidebar hidden
 *   - TopBar logo + nav visible
 *   - Desktop-style cards (thumbnails visible)
 * 
 * Mobile: <= 600px
 *   - TopBar hidden
 *   - Bottom nav visible
 *   - Mobile cards (hero images, compact layout)
 * 
 * Intermediate styling (768px) is used for gradual padding/font adjustments
 * but NOT for structural layout changes.
 */

export const TabbedContainer = styled.div`
    margin-top: ${({ theme }) => theme.layout.tabbedMarginTop};
    position: relative;
`;

export const ContainerTab = styled.div`
    ${({ theme }) => theme.layout.showContainerTab ? '' : 'display: none;'}
    position: absolute;
    bottom: 100%;
    left: ${({ theme }) => theme.layout.containerTabLeft};
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-bottom: none;
    border-radius: ${({ theme }) => theme.layout.containerTabRadius};
    padding: ${({ theme }) => theme.layout.containerTabPadding};
    font-size: ${({ theme }) => theme.layout.tabSize};
    font-weight: ${({ theme }) => theme.layout.tabWeight};
    color: ${({ theme }) => theme.colors.text};
    z-index: 2;
    margin-bottom: -1px;
    
    &::after {
        content: '';
        position: absolute;
        bottom: -2px;
        left: 0;
        right: 0;
        height: 3px;
        background: ${({ theme }) => theme.colors.panel};
    }
    
    @media (max-width: 1000px) {
        left: 0.5rem;
        padding: 0.2rem 0.5rem 0.1rem 0.5rem;
        font-size: 0.7rem;
    }
`;

export const ContainerBody = styled.div`
    background-color: ${({ theme }) => theme.colors.panel};
    border: ${({ theme }) => theme.layout.containerBodyBorder};
    border-radius: ${({ theme }) => theme.layout.containerBodyRadius};
    overflow: visible;
    padding: ${({ theme }) => theme.layout.containerBodyPadding};
    max-width: ${({ theme, $fullWidth }) => $fullWidth ? 'none' : theme.layout.containerBodyMaxWidth};
    
    @media (max-width: 1000px) {
        border-radius: ${({ theme }) => theme.layout.containerBodyRadiusMobile};
        padding: ${({ theme }) => theme.layout.containerBodyPaddingMobile};
    }
`;

export const ContentGrid = styled.div`
    display: grid;
    grid-template-columns: ${({ theme }) => theme.layout.contentGridCols};
    gap: ${({ theme }) => theme.layout.contentGridGap};
    max-width: ${({ theme }) => theme.layout.contentMaxWidth};
    margin: ${({ theme }) => theme.layout.contentMargin};
    padding: ${({ theme }) => theme.layout.contentPadding};
    box-sizing: border-box;
    width: 100%;

    @media (max-width: 1000px) {
        grid-template-columns: minmax(0, 1fr);
        padding: ${({ theme }) => theme.layout.contentPaddingTablet};
    }
`;

export const ModernPostFeed = styled.div`
    max-width: ${({ theme }) => theme.layout.feedMaxWidth};
    width: 100%;
    margin: ${({ theme }) => theme.layout.feedMargin};
    padding: ${({ theme }) => theme.layout.feedPadding};
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: ${({ theme }) => theme.layout.feedGap};

    @media (max-width: 1000px) {
        padding: ${({ theme }) => theme.layout.feedPaddingTablet};
        gap: ${({ theme }) => theme.layout.feedGapTablet};
    }

    @media (max-width: 600px) {
        padding: 0;
        gap: ${({ theme }) => theme.layout.feedGapMobile};
    }
`;

export const PostGrid = styled.div`
    display: flex;
    flex-direction: column;
    gap: var(--card-gap, 1.25rem);

    @media (max-width: 600px) {
        gap: var(--card-gap-mobile, 0.5rem);
    }
`;

export const AnimatedCard = styled.div`
    opacity: 0;
    transform: translateY(10px);
    animation: slideInUp 0.3s ease-out forwards;
    border-radius: 12px;
    position: relative;

    &:hover {
        z-index: 10;
    }

    @keyframes slideInUp {
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }

    @keyframes slideUpHide {
        from {
            opacity: 1;
        }
        to {
            opacity: 0;
        }
    }

    @keyframes flashHighlight {
        0% {
            box-shadow: inset 0 0 0 3px rgba(251, 191, 36, 0.6);
        }
        100% {
            box-shadow: inset 0 0 0 3px transparent;
        }
    }

    ${({ $flash, $hiding }) => ($flash && !$hiding) && `
        opacity: 1;
        transform: translateY(0);
        animation: slideInUp 0.3s ease-out forwards, flashHighlight 1s ease-out forwards;
    `}

    ${({ $hiding }) => $hiding && `
        animation: slideUpHide 0.25s ease-out forwards !important;
        overflow: hidden;
    `}

    @media (max-width: 1000px) {
        border-radius: 10px;
    }

    @media (max-width: 600px) {
        border-radius: 4px;
        animation: ${({ $hiding }) => $hiding ? 'slideUpHide 0.25s ease-out forwards' : 'none'};
        opacity: 1;
        transform: none;
    }
`;

export const StyledError = styled.div`
    margin-top: 0.5rem;
    margin-left: ${({ theme }) => theme.layout.errorMarginX};
    margin-right: ${({ theme }) => theme.layout.errorMarginX};
    padding: ${({ theme }) => theme.layout.errorPadding};
    background-color: ${({ theme }) => theme.colors.panel};
    border: ${({ theme }) => theme.layout.errorBorder};
    display: flex;
    flex-direction: row;
    justify-content: ${({ theme }) => theme.layout.errorJustify};
    align-items: center;
    text-align: ${({ theme }) => theme.layout.errorAlign};
    font-size: ${({ theme }) => theme.layout.errorSize};
    white-space: pre-line;
`;

export const EmptyCard = styled.div`
    margin-top: 0.5rem;
    margin-left: ${({ theme }) => theme.layout.emptyMarginX};
    margin-right: ${({ theme }) => theme.layout.emptyMarginX};
    padding: ${({ theme }) => theme.layout.emptyPadding};
    background-color: ${({ theme }) => theme.colors.cardAlt};
    border: 1px solid ${({ theme }) => theme.colors.cardBorder};
    border-radius: ${({ theme }) => theme.layout.emptyRadius};
    text-align: left;

    @media (max-width: 1000px) {
        margin-left: ${({ theme }) => theme.layout.emptyMarginXTablet};
        margin-right: ${({ theme }) => theme.layout.emptyMarginXTablet};
    }
`;

export const EmptyTitle = styled.div`
    font-size: ${({ theme }) => theme.layout.emptyTitleSize};
    font-weight: 700;
    margin-bottom: ${({ theme }) => theme.layout.emptyTitleMarginBottom};
    color: ${({ theme }) => theme.colors.text};
`;

export const EmptyBody = styled.div`
    font-size: ${({ theme }) => theme.layout.emptyBodySize};
    line-height: 1.5;
    color: ${({ theme }) => theme.colors.subtleText};
`;

export const SearchContainer = styled.div`
    width: 100%;
    max-width: ${({ theme }) => theme.layout.searchMaxWidth};
    margin: ${({ theme }) => theme.layout.searchMargin};
    padding: ${({ theme }) => theme.layout.searchPadding};
    box-sizing: border-box;

    @media (max-width: 1000px) {
        margin: ${({ theme }) => theme.layout.searchMarginTablet};
        padding: ${({ theme }) => theme.layout.searchPaddingTablet};
    }
`;

export const SearchRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
`;

export const SearchInput = styled.input`
    flex: 1;
    min-width: 0;
    padding: ${({ theme }) => theme.layout.searchInputPadding};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: ${({ theme }) => theme.layout.searchInputRadius};
    background: ${({ theme }) => theme.colors.panel};
    color: ${({ theme }) => theme.colors.text};
    font-size: ${({ theme }) => theme.layout.searchInputSize};
    outline: none;
    transition: all 0.2s ease;

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
    }

    &:focus {
        border-color: ${({ theme }) => theme.colors.link};
        box-shadow: ${({ theme }) => theme.layout.searchFocusShadow};
    }
`;

export const TabsRow = styled.div`
    display: flex;
    position: ${({ theme }) => theme.layout.tabsRowPosition};
    bottom: ${({ theme }) => theme.layout.tabsRowBottom};
    left: ${({ theme }) => theme.layout.tabsRowLeft};
    z-index: 2;
    margin-bottom: ${({ theme }) => theme.layout.tabsRowMarginBottom};
    gap: ${({ theme }) => theme.layout.tabsRowGap};
    border-bottom: ${({ theme }) => theme.layout.tabsRowBorderBottom};
    background: ${({ theme }) => theme.layout.tabsRowBg};

    @media (max-width: 1000px) {
        left: ${({ theme }) => theme.layout.tabsRowLeftTablet};
    }
`;

export const ClickableTab = styled.button`
    position: relative;
    background: ${({ theme, $active }) =>
        $active ? theme.colors.panel : theme.colors.panelAlt};
    border: ${({ theme }) => theme.layout.clickableTabShowAfter ? `1px solid ${theme.colors.border}` : 'none'};
    border-bottom: ${({ $active, theme }) => {
        if (!theme.layout.clickableTabShowAfter) {
            return $active
                ? theme.layout.clickableTabActiveBorderBottom
                : theme.layout.clickableTabInactiveBorderBottom;
        }
        return $active ? 'none' : `1px solid ${theme.colors.border}`;
    }};
    border-radius: ${({ theme }) => theme.layout.clickableTabRadius};
    padding: ${({ theme }) => theme.layout.clickableTabPadding};
    font-family: inherit;
    font-size: ${({ theme }) => theme.layout.tabSize};
    font-weight: ${({ theme }) => theme.layout.tabWeight};
    text-transform: ${({ theme }) => theme.layout.clickableTabTextTransform};
    color: ${({ theme, $active }) =>
        $active
            ? theme.colors.text
            : theme.colors.subtleText};
    cursor: pointer;
    margin-right: ${({ theme }) => theme.layout.clickableTabMarginRight};
    transition: background 0.15s ease, color 0.15s ease;
    
    &:hover:not([disabled]) {
        color: ${({ theme }) => theme.colors.text};
        background: ${({ theme, $active }) =>
        $active ? theme.colors.panel : theme.colors.accent};
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => theme.colors.link};
        outline-offset: 2px;
    }

    &::after {
        content: '';
        position: absolute;
        bottom: -2px;
        left: 0;
        right: 0;
        height: 3px;
        display: ${({ theme }) => theme.layout.clickableTabShowAfter ? 'block' : 'none'};
        background: ${({ theme, $active }) => $active ? theme.colors.panel : 'transparent'};
    }

    @media (max-width: 1000px) {
        padding: ${({ theme }) => theme.layout.clickableTabPaddingTablet};
        font-size: ${({ theme }) => theme.layout.tabSizeTablet};
    }
`;
