import React, { useState, useEffect, useRef } from 'react';
import ReactDOM from 'react-dom';
import styled, { css } from 'styled-components';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import Storage from '../../../utils/Storage';
import { ProfileMenuContent } from './TopBar';

// Nav container - flat oldreddit style
const NavContainer = styled.nav`
    display: none;

    @media (max-width: 600px) {
        display: flex !important;
        position: fixed !important;
        left: 0 !important;
        right: 0 !important;
        z-index: 10002 !important;
        height: 40px;
        width: 100%;
        max-width: 100vw;
        box-sizing: border-box;
        border-top: 1px solid ${({ theme }) => theme.colors.border};
        padding: 0 0.5rem;
        padding-bottom: env(safe-area-inset-bottom, 0px);
        overflow: visible;
        background: ${({ theme }) => theme.colors.panel};
    }
`;

const NavItems = styled.div`
    display: flex;
    width: 100%;
    margin: 0;
    justify-content: space-around;
    align-items: stretch;
    height: 40px;
    box-sizing: border-box;
`;

const navItemStyles = css`
    display: flex;
    align-items: center;
    justify-content: center;
    flex: 1;
    cursor: pointer;
    text-decoration: none;
    color: ${({ theme, $active }) => $active ? theme.colors.text : theme.colors.subtleText};
    user-select: none;
    -webkit-tap-highlight-color: transparent;
    position: relative;

    svg {
        width: 20px;
        height: 20px;
        fill: currentColor;
    }
`;

const NavItemBase = styled.div`${navItemStyles}`;
const NavItemLink = styled(Link)`${navItemStyles}`;
const InboxNavItem = styled.a`${navItemStyles}`;

const UnreadDot = styled.span`
    position: absolute;
    top: 6px;
    right: calc(50% - 14px);
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #FF3B30;
`;

const ProfileSheetBackdrop = styled.div`
    position: fixed;
    inset: 0;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    background: rgba(0, 0, 0, 0.5);
    z-index: 10001;

    @media (min-width: 601px) {
        display: none;
    }
`;

const ProfileSheet = styled.div`
    width: 100%;
    background-color: ${({ theme }) => theme.colors.panel};
    border-top: 1px solid ${({ theme }) => theme.colors.border};
    padding: 0.5rem 0.75rem calc(0.75rem + env(safe-area-inset-bottom, 0px));
    margin-bottom: 40px;
    box-sizing: border-box;

    @media (min-width: 601px) {
        display: none;
    }
`;

const ProfileSheetHandle = styled.div`
    width: 32px;
    height: 2px;
    background: ${({ theme }) => theme.colors.border};
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

const NAV_HEIGHT = 40;

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
    const isProfileActive = isPathActive(pathname, ['/profile', '/subscription', '/settings', '/network', '/reports', '/stats', '/agents']);

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
            navigate('/signup');
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

    const handleFeedNavClick = (targetPath, e) => {
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;

        if (isProfileSheetOpen) {
            setIsProfileSheetOpen(false);
        }

        const isAlreadyOnRoute = pathname === targetPath ||
            (targetPath === '/home' && (pathname === '/' || pathname === '/home' || pathname.startsWith('/t/')));

        window.scrollTo({ top: 0, behavior: 'instant' });

        if (isAlreadyOnRoute) {
            e.preventDefault();
            window.dispatchEvent(new CustomEvent('mirageRefreshFeed'));
        }
    };

    // Don't render on desktop, hidden routes, or when keyboard is open
    if (!isMobile || shouldHide || isInputFocused) return null;

    // Create link always points at /create_post; logged-out users see the welcome prompt there.
    const createLink = hasPublicKey && currentTopic
        ? `/create_post?topic=${encodeURIComponent(currentTopic)}`
        : '/create_post';

    return ReactDOM.createPortal(
        <>
            <NavContainer ref={navRef} role="navigation" aria-label="Main navigation">
                <NavItems>
                    <NavItemLink
                        to="/home"
                        $active={isHomeActive}
                        aria-label="Home"
                        aria-current={isHomeActive ? 'page' : undefined}
                        onClick={(e) => handleFeedNavClick('/home', e)}
                    >
                        <svg viewBox="0 0 24 24">
                            {isHomeActive
                                ? <path d="M10 20v-6h4v6h5v-8h3L12 3 2 12h3v8z" />
                                : <path d="M12 5.69l5 4.5V18h-2v-6H9v6H7v-7.81l5-4.5M12 3L2 12h3v8h6v-6h2v6h6v-8h3L12 3z" />
                            }
                        </svg>
                    </NavItemLink>

                    <NavItemLink
                        to="/following"
                        $active={isFollowingActive}
                        aria-label="Following"
                        aria-current={isFollowingActive ? 'page' : undefined}
                        onClick={(e) => handleFeedNavClick('/following', e)}
                    >
                        <svg viewBox="0 0 24 24">
                            <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5s-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z" />
                        </svg>
                    </NavItemLink>

                    <NavItemLink
                        to={createLink}
                        $active={isCreateActive}
                        aria-label="Create post"
                        aria-current={isCreateActive ? 'page' : undefined}
                        onClick={handleNavItemClick}
                    >
                        <svg viewBox="0 0 24 24">
                            {isCreateActive
                                ? <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 000-1.41l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z" />
                                : <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 000-1.41l-2.34-2.34a1 1 0 00-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z" />
                            }
                        </svg>
                    </NavItemLink>

                    <InboxNavItem
                        href="/inbox"
                        $active={isInboxActive}
                        aria-label={inboxCount > 0 ? `Inbox - ${inboxCount} unread` : 'Inbox'}
                        aria-current={isInboxActive ? 'page' : undefined}
                        onClick={(e) => {
                            handleNavItemClick();
                            if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                e.preventDefault();
                                navigate('/inbox');
                            }
                        }}
                    >
                        <svg viewBox="0 0 24 24">
                            {isInboxActive
                                ? <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z" />
                                : <path d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V8l8 5 8-5v10zm-8-7L4 6h16l-8 5z" />
                            }
                        </svg>
                        {inboxCount > 0 && hasPublicKey && <UnreadDot />}
                    </InboxNavItem>

                    <NavItemBase
                        as="button"
                        type="button"
                        onClick={handleProfileClick}
                        $active={isProfileActive}
                        aria-label="Profile"
                        aria-current={isProfileActive ? 'page' : undefined}
                        style={{ background: 'transparent', border: 'none' }}
                    >
                        <svg viewBox="0 0 24 24">
                            {isProfileActive
                                ? <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
                                : <path d="M12 6c1.1 0 2 .9 2 2s-.9 2-2 2-2-.9-2-2 .9-2 2-2m0 10c2.7 0 5.8 1.29 6 2H6c.23-.72 3.31-2 6-2m0-12C9.79 4 8 5.79 8 8s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4zm0 10c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
                            }
                        </svg>
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
