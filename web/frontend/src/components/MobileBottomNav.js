import React, { useState, useEffect, useRef } from 'react';
import ReactDOM from 'react-dom';
import styled from 'styled-components';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import Storage from '../utils/Storage';
import { ProfileMenuContent } from './TopBar';

// Nav container - uses JS positioning, not CSS bottom
const NavContainer = styled.nav`
    display: none;

    @media (max-width: 600px) {
        display: flex !important;
        position: fixed !important;
        /* Don't use bottom: 0 - we'll set top via JS */
        left: 0 !important;
        right: 0 !important;
        /* Keep bottom nav above overlays/sheets on mobile */
        z-index: 10002 !important;
        height: 56px;
        width: 100%;
        max-width: 100vw;
        box-sizing: border-box;
        border-top: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
        padding: 0;
        padding-bottom: env(safe-area-inset-bottom, 0px);
        overflow: visible;
        
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        background: ${({ theme }) =>
        theme?.name === 'dark'
            ? 'rgba(26, 26, 26, 0.95)'
            : 'rgba(255, 255, 255, 0.95)'};
        box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.15);
    }
`;

// Nav items container
const NavItems = styled.div`
    display: flex;
    width: 100%;
    max-width: min(430px, 100%);
    margin: 0 auto;
    justify-content: space-around;
    align-items: stretch;
    height: 56px;
    box-sizing: border-box;
`;

// Base nav item styling
const NavItemBase = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex: 1;
    min-width: 48px;
    max-width: 80px;
    cursor: pointer;
    text-decoration: none;
    color: ${({ theme, $active }) =>
        $active
            ? (theme?.colors?.link || theme?.colors?.accent || '#667eea')
            : (theme?.colors?.subtleText || '#888')};
    transition: color 0.15s ease;
    position: relative;
    user-select: none;
    -webkit-tap-highlight-color: transparent;

    &:hover, &:focus {
        color: ${({ theme }) => theme?.colors?.link || theme?.colors?.accent || '#667eea'};
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => theme?.colors?.link || '#667eea'};
        outline-offset: -2px;
        border-radius: 8px;
    }
`;

const NavItemLink = styled(Link)`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex: 1;
    min-width: 48px;
    max-width: 80px;
    cursor: pointer;
    text-decoration: none;
    color: ${({ theme, $active }) =>
        $active
            ? (theme?.colors?.link || theme?.colors?.accent || '#667eea')
            : (theme?.colors?.subtleText || '#888')};
    transition: color 0.15s ease;
    position: relative;
    user-select: none;
    -webkit-tap-highlight-color: transparent;

    &:hover, &:focus {
        color: ${({ theme }) => theme?.colors?.link || theme?.colors?.accent || '#667eea'};
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => theme?.colors?.link || '#667eea'};
        outline-offset: -2px;
        border-radius: 8px;
    }
`;

// Inbox uses a regular anchor tag so right-click "Open in new window" works natively
const InboxNavItem = styled.a`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex: 1;
    min-width: 48px;
    max-width: 80px;
    cursor: pointer;
    text-decoration: none;
    color: ${({ theme, $active }) =>
        $active
            ? (theme?.colors?.link || theme?.colors?.accent || '#667eea')
            : (theme?.colors?.subtleText || '#888')};
    transition: color 0.15s ease;
    position: relative;
    user-select: none;
    -webkit-tap-highlight-color: transparent;

    &:hover, &:focus {
        color: ${({ theme }) => theme?.colors?.link || theme?.colors?.accent || '#667eea'};
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => theme?.colors?.link || '#667eea'};
        outline-offset: -2px;
        border-radius: 8px;
    }
`;

// Create button - elevated center CTA
const CreateButton = styled(Link)`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-end;
    flex: 1;
    min-width: 48px;
    max-width: 80px;
    cursor: pointer;
    text-decoration: none;
    position: relative;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
    padding-bottom: 4px;

    &:focus-visible {
        outline: 2px solid ${({ theme }) => theme?.colors?.link || '#667eea'};
        outline-offset: -2px;
        border-radius: 8px;
    }
`;

const CreateIconWrapper = styled.div`
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    margin-top: -16px;
    margin-bottom: 2px;
`;

// Icon container
const IconWrapper = styled.div`
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
`;

// SVG icon styling
const Icon = styled.svg`
    width: 22px;
    height: 22px;
    fill: currentColor;
`;

const CreateIcon = styled.svg`
    width: 20px;
    height: 20px;
    fill: #FFFFFF;
`;

// Label text
const Label = styled.span`
    font-size: 10px;
    font-weight: 500;
    margin-top: 2px;
    letter-spacing: 0.01em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
`;

const CreateLabel = styled(Label)`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

// Unread badge with count
const UnreadBadge = styled.span`
    position: absolute;
    top: -5px;
    right: -11px;
    min-width: 24px;
    height: 24px;
    padding: 0 6px;
    background: #FF3B30;
    border-radius: 12px;
    border: 2px solid ${({ theme }) =>
        theme?.name === 'dark'
            ? 'rgba(26, 26, 26, 0.92)'
            : 'rgba(255, 255, 255, 0.92)'};
    color: #fff;
    font-size: 11px;
    font-weight: 700;
    line-height: 20px;
    text-align: center;
    box-sizing: border-box;
`;

const formatBadgeCount = (n) => n > 99 ? '99+' : String(n);

// Lock icon for gated profile
const LockIcon = styled.svg`
    width: 10px;
    height: 10px;
    fill: currentColor;
    position: absolute;
    bottom: -2px;
    right: -4px;
    opacity: 0.7;
`;

// Backdrop for the bottom sheet profile menu (mobile only)
const ProfileSheetBackdrop = styled.div`
    position: fixed;
    inset: 0;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    background: ${({ theme }) =>
        theme?.colors?.overlay || 'rgba(0, 0, 0, 0.7)'};
    /* Slightly below the bottom nav so nav remains visually on top */
    z-index: 10001;

    @media (min-width: 601px) {
        display: none;
    }
`;

// Bottom sheet container that mirrors the desktop avatar dropdown styling
const ProfileSheet = styled.div`
    width: 100%;
    max-width: min(430px, 100%);
    background-color: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border-top-left-radius: 16px;
    border-top-right-radius: 16px;
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    border-bottom: none;
    box-shadow: 0 -8px 24px rgba(0, 0, 0, 0.5);
    padding: 0.6rem 0.9rem calc(0.9rem + env(safe-area-inset-bottom, 0px));
    /* Sit visually above the fixed bottom nav bar */
    margin-bottom: 56px;
    box-sizing: border-box;
    transform: translateY(0);
    animation: slideUpProfileSheet 0.22s ease-out;

    @keyframes slideUpProfileSheet {
        from {
            transform: translateY(18px);
            opacity: 0;
        }
        to {
            transform: translateY(0);
            opacity: 1;
        }
    }

    @media (min-width: 601px) {
        display: none;
    }
`;

const ProfileSheetHandle = styled.div`
    width: 32px;
    height: 3px;
    border-radius: 999px;
    background: ${({ theme }) => theme?.colors?.border || '#444'};
    opacity: 0.7;
    margin: 0 auto 0.4rem;
`;

// Routes that should not show the bottom nav
const HIDDEN_ROUTES = [];

// Check if current path matches or starts with given pattern
const isPathActive = (pathname, patterns) => {
    if (!Array.isArray(patterns)) patterns = [patterns];
    return patterns.some(pattern => {
        if (pattern === '/') return pathname === '/';
        return pathname === pattern || pathname.startsWith(pattern + '/');
    });
};

// Navigation height in pixels
const NAV_HEIGHT = 56;

function MobileBottomNav({ state }) {
    const location = useLocation();
    const navigate = useNavigate();
    const pathname = location?.pathname || '';
    const navRef = useRef(null);

    // Don't run any logic on desktop - check initial window width
    const [isMobile, setIsMobile] = useState(() =>
        typeof window !== 'undefined' && window.innerWidth <= 600
    );

    // Update on resize
    useEffect(() => {
        const checkMobile = () => setIsMobile(window.innerWidth <= 600);
        window.addEventListener('resize', checkMobile);
        return () => window.removeEventListener('resize', checkMobile);
    }, []);

    // State for unread inbox count (server-side, initialized from localStorage to survive remounts)
    const [inboxCount, setInboxCount] = useState(() => {
        try {
            const stored = localStorage.getItem('inbox_count');
            return stored ? Math.max(0, parseInt(stored, 10) || 0) : 0;
        } catch (_) { return 0; }
    });
    const mountedRef = useRef(true);

    // Bottom-sheet profile menu visibility
    const [isProfileSheetOpen, setIsProfileSheetOpen] = useState(false);

    // Track if an input/textarea is focused (keyboard is likely open)
    const [isInputFocused, setIsInputFocused] = useState(false);

    const publicKey = (state && state.publicKey) ? state.publicKey : Storage.load('publicKey', '');
    const username = (state && state.username) ? state.username : Storage.load('username', '');
    const hasPublicKey = !!publicKey;

    // Hide nav on certain routes
    const shouldHide = HIDDEN_ROUTES.some(route => pathname === route || pathname.startsWith(route));

    // Determine active tab
    const isHomeActive = isPathActive(pathname, ['/', '/home']) || pathname.startsWith('/t/');
    const isFollowingActive = pathname === '/following';
    const isCreateActive = pathname === '/create_post';
    const isInboxActive = pathname === '/inbox';
    const isProfileActive = isPathActive(pathname, ['/profile', '/subscription', '/settings', '/network', '/reports', '/stats']);

    // Get current topic for create button
    const currentTopic = React.useMemo(() => {
        try {
            const m = pathname.match(/^\/t\/([^/]+)/);
            const t = m && m[1] ? decodeURIComponent(m[1]) : '';
            return t || '';
        } catch (_) {
            return '';
        }
    }, [pathname]);

    // Position the nav using JavaScript instead of CSS bottom: 0
    // This is more reliable across different mobile browser behaviors
    useEffect(() => {
        // Skip on desktop
        if (!isMobile) return;

        const nav = navRef.current;
        if (!nav) return;

        const updatePosition = () => {
            if (!nav) return;

            // Use visualViewport if available, otherwise fall back to window dimensions
            let viewportHeight;
            if (window.visualViewport) {
                viewportHeight = window.visualViewport.height + window.visualViewport.offsetTop;
            } else {
                viewportHeight = window.innerHeight;
            }

            // Position nav at the bottom of the visible viewport
            const topPosition = viewportHeight - NAV_HEIGHT;
            nav.style.top = `${Math.max(0, topPosition)}px`;
            nav.style.bottom = 'auto';
        };

        // Update on various events
        updatePosition();

        // Use requestAnimationFrame for smooth updates
        let rafId = null;
        const scheduleUpdate = () => {
            if (rafId) return;
            rafId = requestAnimationFrame(() => {
                rafId = null;
                updatePosition();
            });
        };

        // Listen to all relevant events
        window.addEventListener('resize', scheduleUpdate);
        window.addEventListener('scroll', scheduleUpdate);
        window.addEventListener('orientationchange', scheduleUpdate);

        if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', scheduleUpdate);
            window.visualViewport.addEventListener('scroll', scheduleUpdate);
        }

        // Initial position update
        updatePosition();

        return () => {
            window.removeEventListener('resize', scheduleUpdate);
            window.removeEventListener('scroll', scheduleUpdate);
            window.removeEventListener('orientationchange', scheduleUpdate);

            if (window.visualViewport) {
                window.visualViewport.removeEventListener('resize', scheduleUpdate);
                window.visualViewport.removeEventListener('scroll', scheduleUpdate);
            }

            if (rafId) cancelAnimationFrame(rafId);
        };
    }, [isMobile]);

    // Track when text inputs are focused to hide bottom nav (keyboard open)
    useEffect(() => {
        if (!isMobile) return;

        const handleFocusIn = (e) => {
            const tag = e.target?.tagName?.toLowerCase();
            const type = e.target?.type?.toLowerCase();
            // Detect text inputs and textareas (not buttons, checkboxes, etc.)
            const isTextInput = tag === 'textarea' ||
                (tag === 'input' && ['text', 'search', 'email', 'password', 'tel', 'url', 'number'].includes(type));
            if (isTextInput) {
                setIsInputFocused(true);
            }
        };

        const handleFocusOut = (e) => {
            const tag = e.target?.tagName?.toLowerCase();
            const type = e.target?.type?.toLowerCase();
            const isTextInput = tag === 'textarea' ||
                (tag === 'input' && ['text', 'search', 'email', 'password', 'tel', 'url', 'number'].includes(type));
            if (isTextInput) {
                setIsInputFocused(false);
            }
        };

        document.addEventListener('focusin', handleFocusIn);
        document.addEventListener('focusout', handleFocusOut);

        return () => {
            document.removeEventListener('focusin', handleFocusIn);
            document.removeEventListener('focusout', handleFocusOut);
        };
    }, [isMobile]);

    // Close profile sheet on Escape key while it is open
    useEffect(() => {
        if (!isMobile || !isProfileSheetOpen) return;
        const onKeyDown = (e) => {
            if (e.key === 'Escape' || e.key === 'Esc') {
                setIsProfileSheetOpen(false);
            }
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [isMobile, isProfileSheetOpen]);

    useEffect(() => {
        mountedRef.current = true;
        return () => { mountedRef.current = false; };
    }, []);

    // Listen for server-side inbox count from every API response
    useEffect(() => {
        if (!isMobile) return;
        if (!publicKey) {
            setInboxCount(0);
            return;
        }

        const handleInboxCount = (e) => {
            if (!mountedRef.current) return;
            const count = typeof e.detail === 'number' ? Math.max(0, e.detail) : 0;

            setInboxCount(count);
        };

        window.addEventListener('inboxCount', handleInboxCount);
        return () => window.removeEventListener('inboxCount', handleInboxCount);
    }, [isMobile, publicKey]);

    // Close the profile sheet on any route change
    useEffect(() => {
        if (!isMobile) return;
        setIsProfileSheetOpen(false);
    }, [pathname, isMobile]);

    const handleProfileClick = (e) => {
        e.preventDefault();

        if (!hasPublicKey) {
            navigate('/create_account');
            return;
        }

        setIsProfileSheetOpen(true);
    };

    const handleCloseProfileSheet = () => {
        setIsProfileSheetOpen(false);
    };

    const handleProfileMenuNavigate = (targetPath) => {
        // Ensure mobile profile menu navigation snaps to top instantly
        try {
            if (typeof window !== 'undefined' && window.innerWidth <= 600) {
                window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
            }
        } catch (_) { }
        setIsProfileSheetOpen(false);
    };

    const handleNavItemClick = () => {
        if (isProfileSheetOpen) {
            setIsProfileSheetOpen(false);
        }
    };

    // Handle clicking on feed nav items - always scroll to top, refresh if already on route
    const handleFeedNavClick = (targetPath, e) => {
        if (isProfileSheetOpen) {
            setIsProfileSheetOpen(false);
        }

        const isAlreadyOnRoute = pathname === targetPath ||
            (targetPath === '/home' && (pathname === '/' || pathname === '/home' || pathname.startsWith('/t/')));

        // Always scroll to top (including header visibility)
        window.scrollTo({ top: 0, behavior: 'instant' });

        if (isAlreadyOnRoute) {
            e.preventDefault();
            // Trigger refresh
            window.dispatchEvent(new CustomEvent('mirageRefreshFeed'));
        }
    };

    // Don't render on desktop, hidden routes, or when keyboard is open
    if (!isMobile || shouldHide || isInputFocused) return null;

    // If not signed in, Create button redirects to sign up
    const createLink = hasPublicKey
        ? (currentTopic
            ? `/create_post?topic=${encodeURIComponent(currentTopic)}`
            : '/create_post')
        : '/create_account';

    return ReactDOM.createPortal(
        <>
            <NavContainer ref={navRef} role="navigation" aria-label="Main navigation">
                <NavItems>
                    {/* Home Tab */}
                    <NavItemLink
                        to="/home"
                        $active={isHomeActive}
                        aria-label="Home"
                        aria-current={isHomeActive ? 'page' : undefined}
                        onClick={(e) => handleFeedNavClick('/home', e)}
                    >
                        <IconWrapper>
                            <Icon viewBox="0 0 24 24">
                                {isHomeActive ? (
                                    <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" />
                                ) : (
                                    <path d="M12 5.69l5 4.5V18h-2v-6H9v6H7v-7.81l5-4.5M12 3L2 12h3v8h6v-6h2v6h6v-8h3L12 3z" />
                                )}
                            </Icon>
                        </IconWrapper>
                        <Label>Home</Label>
                    </NavItemLink>

                    {/* Following Tab */}
                    <NavItemLink
                        to="/following"
                        $active={isFollowingActive}
                        aria-label="Following"
                        aria-current={isFollowingActive ? 'page' : undefined}
                        onClick={(e) => handleFeedNavClick('/following', e)}
                    >
                        <IconWrapper>
                            <Icon viewBox="0 0 24 24">
                                {isFollowingActive ? (
                                    <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z" />
                                ) : (
                                    <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5s-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z" />
                                )}
                            </Icon>
                        </IconWrapper>
                        <Label>Following</Label>
                    </NavItemLink>

                    {/* Create Tab (Center CTA) */}
                    <CreateButton
                        to={createLink}
                        aria-label="Create post"
                        aria-current={isCreateActive ? 'page' : undefined}
                        onClick={handleNavItemClick}
                    >
                        <CreateIconWrapper>
                            <CreateIcon viewBox="0 0 24 24">
                                <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" />
                            </CreateIcon>
                        </CreateIconWrapper>
                        <CreateLabel>Create</CreateLabel>
                    </CreateButton>

                    {/* Inbox Tab */}
                    <InboxNavItem
                        href="/inbox"
                        $active={isInboxActive}
                        aria-label={inboxCount > 0 ? `Inbox - ${inboxCount} unread` : 'Inbox'}
                        aria-current={isInboxActive ? 'page' : undefined}
                        onClick={(e) => {
                            handleNavItemClick();
                            // Allow right-click, ctrl+click, cmd+click, middle-click to work natively
                            if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                e.preventDefault();
                                navigate('/inbox');
                            }
                        }}
                    >
                        <IconWrapper>
                            <Icon viewBox="0 0 24 24">
                                {isInboxActive ? (
                                    <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z" />
                                ) : (
                                    <path d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V8l8 5 8-5v10zm-8-7L4 6h16l-8 5z" />
                                )}
                            </Icon>
                            {inboxCount > 0 && hasPublicKey && <UnreadBadge aria-hidden="true">{formatBadgeCount(inboxCount)}</UnreadBadge>}
                        </IconWrapper>
                        <Label>Inbox</Label>
                    </InboxNavItem>

                    {/* Profile Tab (opens profile sheet on mobile) */}
                    <NavItemBase
                        as="button"
                        type="button"
                        onClick={handleProfileClick}
                        $active={isProfileActive}
                        aria-label="Profile"
                        aria-current={isProfileActive ? 'page' : undefined}
                        style={{ background: 'transparent', border: 'none' }}
                    >
                        <IconWrapper>
                            <Icon viewBox="0 0 24 24">
                                {isProfileActive ? (
                                    <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
                                ) : (
                                    <path d="M12 6c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2 .9-2 2-2m0 10c2.7 0 5.8 1.29 6 2H6c.23-.72 3.31-2 6-2m0-12C9.79 4 8 5.79 8 8s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4zm0 10c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
                                )}
                            </Icon>
                            {!hasPublicKey && (
                                <LockIcon viewBox="0 0 24 24" aria-hidden="true">
                                    <path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z" />
                                </LockIcon>
                            )}
                        </IconWrapper>
                        <Label>Profile</Label>
                    </NavItemBase>
                </NavItems>
            </NavContainer>

            {isProfileSheetOpen && (
                <ProfileSheetBackdrop
                    role="presentation"
                    onClick={handleCloseProfileSheet}
                >
                    <ProfileSheet
                        role="dialog"
                        aria-modal="true"
                        aria-label="Profile menu"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <ProfileSheetHandle aria-hidden="true" />
                        <ProfileMenuContent
                            displayName={username || ''}
                            onItemClick={handleProfileMenuNavigate}
                        />
                    </ProfileSheet>
                </ProfileSheetBackdrop>
            )}
        </>,
        document.body
    );
}

export default MobileBottomNav;
