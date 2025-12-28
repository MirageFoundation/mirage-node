import styled from "styled-components";

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

// Tabbed container: title is an integrated tab rising from the container
// Creates a file-folder aesthetic where title and content are visually unified
export const TabbedContainer = styled.div`
    margin-top: 2.0rem;
    position: relative;
`;

export const ContainerTab = styled.div`
    position: absolute;
    bottom: 100%;
    left: 1rem;
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    padding: 0.25rem 0.65rem 0.1rem 0.65rem;
    font-size: 0.75rem;
    font-weight: 600;
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    z-index: 2;
    /* Pull tab down to overlap container border */
    margin-bottom: -1px;
    
    /* Mask to cover container's top border under the tab */
    &::after {
        content: '';
        position: absolute;
        bottom: -2px;
        left: 0;
        right: 0;
        height: 3px;
        background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    }
    
    @media (max-width: 1000px) {
        left: 0.5rem;
        padding: 0.2rem 0.5rem 0.1rem 0.5rem;
        font-size: 0.7rem;
    }
`;

export const ContainerBody = styled.div`
    background-color: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    border-radius: 12px;
    overflow: visible;
    padding: 1.25rem;
    
    @media (max-width: 1000px) {
        border-radius: 8px;
        padding: 1rem;
    }
`;

// Shared grid layout for main content alongside the sidebar
// Breakpoints: Desktop (>1000px) | Tablet (601-1000px) | Mobile (<=600px)
// Uses CSS custom property --content-max-width for full-width mode support
export const ContentGrid = styled.div`
    display: grid;
    grid-template-columns: 200px minmax(0, 1fr);
    gap: 0.5rem;
    max-width: var(--content-max-width, 1240px);
    margin: 0 auto;
    padding: 0 0.5rem;
    box-sizing: border-box;
    width: 100%;

    @media (max-width: 1000px) {
        grid-template-columns: minmax(0, 1fr);
        padding: 0 0.25rem;
    }
`;

/**
 * ModernPostFeed - Main content container for the feed
 * 
 * IMPORTANT: This container provides horizontal padding (0.75rem desktop, minimal on mobile).
 * Cards and content inside should NOT add their own horizontal margins.
 * Use margin: 0 for cards to match CardView width.
 * 
 * Width: max-width 1000px, centered (or full width via CSS custom property)
 */
export const ModernPostFeed = styled.div`
    max-width: var(--feed-max-width, 1000px);
    width: 100%;
    margin: 0 auto;
    padding: 0 0.75rem;
    box-sizing: border-box;

    @media (max-width: 1000px) {
        padding: 0 0.25rem;
    }

    @media (max-width: 600px) {
        padding: 0 0 0 0;
    }
`;

/**
 * PostGrid - Vertical stack for cards
 * 
 * Cards inside this grid should have margin: 0 (no horizontal margins).
 * The parent ModernPostFeed handles horizontal spacing.
 * 
 * Gap is controlled via CSS custom properties (--card-gap, --card-gap-mobile)
 * which are set by CardView based on the compact mode setting.
 */
export const PostGrid = styled.div`
    display: flex;
    flex-direction: column;
    gap: var(--card-gap, 1.25rem);
    margin-top: var(--card-margin-top, 1.25rem);

    @media (max-width: 600px) {
        gap: var(--card-gap-mobile, 0.5rem);
        margin-top: var(--card-margin-top-mobile, 0.5rem);
    }
`;

// Simple animated wrapper for cards/items that should slide in
export const AnimatedCard = styled.div`
    opacity: 0;
    transform: translateY(10px);
    animation: slideInUp 0.3s ease-out forwards;

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
            outline: 3px solid rgba(251, 191, 36, 0.6);
            outline-offset: -3px;
        }
        100% {
            outline: 3px solid transparent;
        }
    }

    /* Apply flash animation when flash prop is true */
    ${({ $flash, $hiding }) => ($flash && !$hiding) && `
        /* Ensure the card is visible even when flashing */
        opacity: 1;
        transform: translateY(0);
        /* Run slide-in + flash together (flash only affects outline) */
        animation: slideInUp 0.3s ease-out forwards, flashHighlight 1s ease-out forwards;
    `}

    /* Apply hiding animation when hiding prop is true (takes precedence) */
    ${({ $hiding }) => $hiding && `
        animation: slideUpHide 0.25s ease-out forwards !important;
        overflow: hidden;
    `}

    /* Disable animation on mobile to prevent layout shifts interacting with fixed elements */
    @media (max-width: 600px) {
        animation: ${({ $hiding }) => $hiding ? 'slideUpHide 0.25s ease-out forwards' : 'none'};
        opacity: 1;
        transform: none;
    }
`;

// Shared error banner
export const StyledError = styled.div`
    margin-top: 0.5rem;
    margin-left: 1rem;
    margin-right: 1rem;
    padding-top: 0.1rem;
    padding-bottom: 0.25rem;
    background-color: ${({ theme }) => theme?.colors?.panel || "#23272C"};
    display: flex;
    flex-direction: row;
    justify-content: center;
    align-items: center;
    text-align: center;
    font-size: 1rem;
    white-space: pre-line;
`;

// Generic empty-state card used across views
export const EmptyCard = styled.div`
    margin-top: 0.5rem;
    margin-left: 1rem;
    margin-right: 1rem;
    padding: 1.25rem 1rem;
    background-color: ${({ theme }) => theme?.colors?.cardAlt || "#2A2E33"};
    border: 1px solid ${({ theme }) => theme?.colors?.cardBorder || "#444"};
    border-radius: 8px;
    text-align: left;

    @media (max-width: 1000px) {
        margin-left: 0.25rem;
        margin-right: 0.25rem;
    }
`;

export const EmptyTitle = styled.div`
    font-size: 1.1rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
    color: ${({ theme }) => theme?.colors?.text || "#FFFFFF"};
`;

export const EmptyBody = styled.div`
    font-size: 0.75rem;
    line-height: 1.5;
    color: ${({ theme }) => theme?.colors?.subtleText || "#CCCCCC"};
`;

// Shared search shell (input and its container/row)
// Horizontally aligned with the topic hero card in MainView
// Uses CSS custom property --feed-max-width for full-width mode support
export const SearchContainer = styled.div`
    width: 100%;
    max-width: var(--feed-max-width, 1000px);
    margin: 0.75rem auto;
    padding: 0 0.75rem;
    box-sizing: border-box;

    @media (max-width: 1000px) {
        margin: 0.5rem auto;
        padding: 0 0.25rem;
    }
`;

export const SearchRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    width: 100%;
`;

export const SearchInput = styled.input`
    width: 100%;
    padding: 0.55rem 0.85rem;
    border: 1px solid ${({ theme }) => theme?.colors?.border || "#333"};
    border-radius: 18px;
    background: ${({ theme }) => theme?.colors?.panel || "#23272C"};
    color: ${({ theme }) => theme?.colors?.text || "#FFFFFF"};
    font-size: 0.85rem;
    outline: none;
    transition: all 0.2s ease;

    &::placeholder {
        color: ${({ theme }) => theme?.colors?.subtleText || "#CCCCCC"};
    }

    &:focus {
        border-color: ${({ theme }) => theme?.colors?.link || "#FFFFFF"};
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
    }
`;

// Shared row container for multiple clickable tabs
export const TabsRow = styled.div`
    display: flex;
    position: absolute;
    bottom: 100%;
    left: 1rem;
    z-index: 2;
    /* Pull tabs down to overlap container border */
    margin-bottom: -1px;

    @media (max-width: 1000px) {
        left: 0.5rem;
    }
`;

// Clickable tab button - consistent styling with ContainerTab
export const ClickableTab = styled.button`
    position: relative;
    background: ${({ theme, $active }) =>
        $active
            ? (theme?.colors?.panel || '#23272C')
            : (theme?.colors?.panelAlt || '#1f2328')};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    border-bottom: ${({ $active, theme }) =>
        $active ? 'none' : `1px solid ${theme?.colors?.border || '#333'}`};
    border-radius: 6px 6px 0 0;
    padding: 0.25rem 0.65rem 0.1rem 0.65rem;
    font-family: inherit;
    font-size: 0.75rem;
    font-weight: 600;
    color: ${({ theme, $active }) =>
        $active
            ? (theme?.colors?.text || '#FFFFFF')
            : (theme?.colors?.subtleText || '#888')};
    cursor: pointer;
    margin-right: 0.25rem;
    /* Only animate background and text color to avoid border flicker on tab switch */
    transition: background 0.15s ease, color 0.15s ease;
    
    &:hover:not([disabled]) {
        color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
        background: ${({ theme, $active }) =>
        $active
            ? (theme?.colors?.panel || '#23272C')
            : (theme?.colors?.accent || '#2A2E33')};
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => theme?.colors?.link || '#667eea'};
        outline-offset: 2px;
    }

    /* Active tab mask to cover container's top border */
    &::after {
        content: '';
        position: absolute;
        bottom: -2px;
        left: 0;
        right: 0;
        height: 3px;
        background: ${({ theme, $active }) => $active ? (theme?.colors?.panel || '#23272C') : 'transparent'};
    }

    @media (max-width: 1000px) {
        padding: 0.2rem 0.5rem 0.1rem 0.5rem;
        font-size: 0.7rem;
    }
`;


