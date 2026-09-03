import React, { useState, useEffect, useRef } from 'react';
import ReactDOM from 'react-dom';
import styled, { keyframes } from 'styled-components';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
    HiHome,
    HiOutlineHome,
    HiMagnifyingGlass,
    HiOutlineMagnifyingGlass,
    HiPlusCircle,
    HiOutlinePlusCircle,
    HiInbox,
    HiOutlineInbox,
    HiUser,
    HiOutlineUser,
} from 'react-icons/hi2';
import Storage from '../../../utils/Storage';
import { communityFromPathname, createPostPathForContext } from '../../../utils/community';
import { ProfileMenuContent } from './TopBar';
import ConfirmDialog from './ConfirmDialog.js';

/**
 * default MobileBottomNav — mobile tab bar aligned with `mirage-mobile-app`'s
 * tab layout. Rendered only ≤600px and portaled to `document.body` so it stays
 * pinned to the visible viewport even when the main column scrolls.
 *
 * Per sub-plan 06.8 + RULES.md:
 *   R1 — Bar sits on `bg` (single canvas), NOT `panel`.
 *   R3 — Top divider uses `headerBorder` (stronger than `border`).
 *   R5 — Active icon uses `focusBlue` + small dot indicator; no blue-ring focus.
 *   R6 — Icons from `react-icons/hi2` (outline → filled on active).
 *   R7 — Labels at `0.6rem/500`, `600` on active.
 *
 * Five tabs: Home, Search, Create, Inbox, Profile.
 * Profile tab opens `ProfileMenuContent` inside a centered modal panel that
 * matches the rest of the default theme (ConfirmDialog / OptionModal /
 * GiftDialogs) — `panel` surface on `overlay` dim, 14px radius, fade-in +
 * small slide-up — instead of a bottom-drawer sheet.
 */

// Height reserved for the bar (used for JS positioning + content padding).
export const DEFAULT_BOTTOM_NAV_HEIGHT = 56;

const NavContainer = styled.nav`
    display: none;

    @media (max-width: 600px) {
        display: flex !important;
        position: fixed !important;
        left: 0 !important;
        right: 0 !important;
        z-index: 10002 !important;
        height: ${DEFAULT_BOTTOM_NAV_HEIGHT}px;
        width: 100%;
        max-width: 100vw;
        box-sizing: border-box;
        background: ${({ theme }) => theme.colors.bg};
        border-top: 1px solid ${({ theme }) => theme.colors.headerBorder};
        padding: 0;
        padding-bottom: env(safe-area-inset-bottom, 0px);
        overflow: visible;
    }
`;

const NavItems = styled.div`
    display: flex;
    width: 100%;
    margin: 0;
    justify-content: space-around;
    align-items: stretch;
    height: ${DEFAULT_BOTTOM_NAV_HEIGHT}px;
    box-sizing: border-box;
`;

// Per R7: label typography 0.6rem / 500, active 600. Active color uses
// `sidebarItemActiveText` — pure white in dark mode, pure black in light mode.
const navItemCss = ({ theme, $active }) => `
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    flex: 1;
    min-width: 48px;
    max-width: 96px;
    cursor: pointer;
    text-decoration: none;
    color: ${$active ? theme.colors.sidebarItemActiveText : theme.colors.subtleText};
    user-select: none;
    -webkit-tap-highlight-color: transparent;
    position: relative;
    background: transparent;
    border: none;
    padding: 0;
    font: inherit;
    transition: color 0.15s ease, background 0.15s ease;

    /* Tap highlight — mirage hover tile, not a blue focus ring. */
    &:hover,
    &:active {
        background: ${theme.colors.hoverBg};
        color: ${$active ? theme.colors.sidebarItemActiveText : theme.colors.text};
    }

    /* Explicitly suppress blue outline / focus ring per R5. */
    &:focus,
    &:focus-visible {
        outline: none;
        box-shadow: none;
    }

    svg {
        width: 24px;
        height: 24px;
        display: block;
    }
`;

const NavItemLink = styled(Link)`${navItemCss}`;
const NavItemAnchor = styled.a`${navItemCss}`;
const NavItemButton = styled.button`${navItemCss}`;

const NavLabel = styled.span`
    font-size: 0.6rem;
    font-weight: ${({ $active }) => ($active ? 600 : 500)};
    line-height: 1;
    letter-spacing: 0.01em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
`;

// Inbox unread pill — small red badge (reuses MobileHeader pattern).
const InboxBadge = styled.span`
    position: absolute;
    top: 4px;
    left: calc(50% + 6px);
    min-width: 14px;
    height: 14px;
    padding: 0 3px;
    background: #FF3B30;
    border-radius: 999px;
    border: 2px solid ${({ theme }) => theme.colors.bg};
    color: #fff;
    font-size: 0.5rem;
    font-weight: 700;
    line-height: 10px;
    text-align: center;
    box-sizing: border-box;
`;

const formatBadgeCount = (n) => (n > 99 ? '99+' : String(n));

const fadeInBackdrop = keyframes`
    from { opacity: 0; }
    to   { opacity: 1; }
`;

const slideUpPanel = keyframes`
    from { transform: translateY(8px); opacity: 0; }
    to   { transform: translateY(0);    opacity: 1; }
`;

const ProfileSheetBackdrop = styled.div`
    position: fixed;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
    background: ${({ theme }) => theme.colors.overlay};
    z-index: 10001;
    animation: ${fadeInBackdrop} 0.15s ease;

    @media (min-width: 601px) {
        display: none;
    }
`;

const ProfileSheet = styled.div`
    width: 100%;
    max-width: 420px;
    max-height: 80vh;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    background-color: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 14px;
    padding: 0.4rem 0;
    box-sizing: border-box;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
    animation: ${slideUpPanel} 0.2s ease;

    @media (min-width: 601px) {
        display: none;
    }
`;

const HIDDEN_ROUTES = [];

const isPathActive = (pathname, patterns) => {
    if (!Array.isArray(patterns)) patterns = [patterns];
    return patterns.some(pattern => {
        if (pattern === '/') return pathname === '/';
        return pathname === pattern || pathname.startsWith(pattern + '/');
    });
};

function MobileBottomNav({ state }) {
    const location = useLocation();
    const navigate = useNavigate();
    const pathname = location?.pathname || '';
    const navRef = useRef(null);

    const [isMobile, setIsMobile] = useState(() =>
        typeof window !== 'undefined' && window.innerWidth <= 600
    );

    useEffect(() => {
        const checkMobile = () => setIsMobile(window.innerWidth <= 600);
        window.addEventListener('resize', checkMobile);
        return () => window.removeEventListener('resize', checkMobile);
    }, []);

    // Unread inbox count — seeded from localStorage so remounts don't flicker.
    const [inboxCount, setInboxCount] = useState(() => {
        try {
            const stored = localStorage.getItem('inbox_count');
            return stored ? Math.max(0, parseInt(stored, 10) || 0) : 0;
        } catch (_) { return 0; }
    });
    const mountedRef = useRef(true);

    const [isProfileSheetOpen, setIsProfileSheetOpen] = useState(false);
    const [signOutDialogOpen, setSignOutDialogOpen] = useState(false);

    const publicKey = (state && state.publicKey) ? state.publicKey : Storage.load('publicKey', '');
    const username = (state && state.username) ? state.username : Storage.load('username', '');
    const hasPublicKey = !!publicKey;

    const shouldHide = HIDDEN_ROUTES.some(route => pathname === route || pathname.startsWith(route));

    const isHomeActive = isPathActive(pathname, ['/', '/home', '/following']) || pathname.startsWith('/c/');
    const isSearchActive = pathname === '/search' || pathname.startsWith('/search');
    const isCreateActive = pathname === '/create_post';
    const isInboxActive = pathname === '/inbox';
    const isProfileActive = isPathActive(pathname, ['/profile', '/subscription', '/settings', '/network', '/reports', '/stats', '/blocks']);

    const currentCommunity = React.useMemo(() => {
        return communityFromPathname(pathname);
    }, [pathname]);

    // Position the nav with JS against the visual viewport so the iOS keyboard
    // or URL bar does not leave a gap.
    useEffect(() => {
        if (!isMobile) return;
        const nav = navRef.current;
        if (!nav) return;

        const updatePosition = () => {
            if (!nav) return;
            let viewportHeight;
            if (window.visualViewport) {
                viewportHeight = window.visualViewport.height + window.visualViewport.offsetTop;
            } else {
                viewportHeight = window.innerHeight;
            }
            const topPosition = viewportHeight - DEFAULT_BOTTOM_NAV_HEIGHT;
            nav.style.top = `${Math.max(0, topPosition)}px`;
            nav.style.bottom = 'auto';
        };

        updatePosition();

        let rafId = null;
        const scheduleUpdate = () => {
            if (rafId) return;
            rafId = requestAnimationFrame(() => {
                rafId = null;
                updatePosition();
            });
        };

        window.addEventListener('resize', scheduleUpdate);
        window.addEventListener('scroll', scheduleUpdate);
        window.addEventListener('orientationchange', scheduleUpdate);
        if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', scheduleUpdate);
            window.visualViewport.addEventListener('scroll', scheduleUpdate);
        }

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

    // Close the profile sheet on Escape.
    useEffect(() => {
        if (!isMobile || !isProfileSheetOpen) return;
        const onKeyDown = (e) => {
            if (e.key === 'Escape' || e.key === 'Esc') setIsProfileSheetOpen(false);
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [isMobile, isProfileSheetOpen]);

    useEffect(() => {
        mountedRef.current = true;
        return () => { mountedRef.current = false; };
    }, []);

    useEffect(() => {
        if (!isMobile) return;
        if (!publicKey) { setInboxCount(0); return; }
        const handleInboxCount = (e) => {
            if (!mountedRef.current) return;
            const count = typeof e.detail === 'number' ? Math.max(0, e.detail) : 0;
            setInboxCount(count);
        };
        window.addEventListener('inboxCount', handleInboxCount);
        return () => window.removeEventListener('inboxCount', handleInboxCount);
    }, [isMobile, publicKey]);

    useEffect(() => {
        if (!isMobile) return;
        setIsProfileSheetOpen(false);
    }, [pathname, isMobile]);

    const handleProfileClick = (e) => {
        e.preventDefault();
        if (!hasPublicKey) {
            // Match the large-screen behavior: send logged-out users to
            // /profile so ProfileView can render its logged-out prompt,
            // rather than redirecting straight to the signup form.
            navigate('/profile');
            return;
        }
        setIsProfileSheetOpen(true);
    };

    const handleCloseProfileSheet = () => setIsProfileSheetOpen(false);

    const handleProfileMenuNavigate = () => {
        try {
            if (typeof window !== 'undefined' && window.innerWidth <= 600) {
                window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
            }
        } catch (_) { /* noop */ }
        setIsProfileSheetOpen(false);
    };

    const handleNavItemClick = () => {
        if (isProfileSheetOpen) setIsProfileSheetOpen(false);
    };

    const handleFeedNavClick = (targetPath, e) => {
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
        if (isProfileSheetOpen) setIsProfileSheetOpen(false);

        const isAlreadyOnRoute = pathname === targetPath ||
            (targetPath === '/home' && (pathname === '/' || pathname === '/home' || pathname.startsWith('/c/')));

        window.scrollTo({ top: 0, behavior: 'instant' });

        if (isAlreadyOnRoute) {
            e.preventDefault();
            window.dispatchEvent(new CustomEvent('mirageRefreshFeed'));
        }
    };

    // Keep the bar mounted even while a text input is focused. The
    // `updatePosition` effect above already re-anchors the nav to the
    // visual viewport (which shrinks when the virtual keyboard opens),
    // so the bar floats above the keyboard rather than disappearing.
    // Unmounting on focus previously caused the bar to vanish on the
    // login / create-account screens — and on iOS the `focusout` event
    // doesn't always fire when the keyboard dismisses, leaving the bar
    // stuck hidden until the next route change.
    if (!isMobile || shouldHide) return null;

    // Always route to /create_post so CreatePostView can render the same
    // LoggedOutPromptCard logged-out users see on large screens — avoids
    // dumping them straight onto the signup form.
    const createLink = createPostPathForContext(hasPublicKey, currentCommunity);

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
                        {isHomeActive ? <HiHome aria-hidden="true" /> : <HiOutlineHome aria-hidden="true" />}
                        <NavLabel $active={isHomeActive}>Home</NavLabel>
                    </NavItemLink>

                    <NavItemLink
                        to="/search"
                        $active={isSearchActive}
                        aria-label="Search"
                        aria-current={isSearchActive ? 'page' : undefined}
                        onClick={handleNavItemClick}
                    >
                        {isSearchActive
                            ? <HiMagnifyingGlass aria-hidden="true" />
                            : <HiOutlineMagnifyingGlass aria-hidden="true" />
                        }
                        <NavLabel $active={isSearchActive}>Search</NavLabel>
                    </NavItemLink>

                    <NavItemLink
                        to={createLink}
                        $active={isCreateActive}
                        aria-label="Create post"
                        aria-current={isCreateActive ? 'page' : undefined}
                        onClick={handleNavItemClick}
                    >
                        {isCreateActive
                            ? <HiPlusCircle aria-hidden="true" />
                            : <HiOutlinePlusCircle aria-hidden="true" />
                        }
                        <NavLabel $active={isCreateActive}>Create</NavLabel>
                    </NavItemLink>

                    <NavItemAnchor
                        href="/inbox"
                        $active={isInboxActive}
                        aria-label={inboxCount > 0 ? `Inbox, ${inboxCount} unread` : 'Inbox'}
                        aria-current={isInboxActive ? 'page' : undefined}
                        onClick={(e) => {
                            handleNavItemClick();
                            if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                e.preventDefault();
                                navigate('/inbox');
                            }
                        }}
                    >
                        {isInboxActive ? <HiInbox aria-hidden="true" /> : <HiOutlineInbox aria-hidden="true" />}
                        {inboxCount > 0 && hasPublicKey && (
                            <InboxBadge aria-hidden="true">{formatBadgeCount(inboxCount)}</InboxBadge>
                        )}
                        <NavLabel $active={isInboxActive}>Inbox</NavLabel>
                    </NavItemAnchor>

                    <NavItemButton
                        type="button"
                        onClick={handleProfileClick}
                        $active={isProfileActive}
                        aria-label="Profile"
                        aria-current={isProfileActive ? 'page' : undefined}
                    >
                        {isProfileActive ? <HiUser aria-hidden="true" /> : <HiOutlineUser aria-hidden="true" />}
                        <NavLabel $active={isProfileActive}>Profile</NavLabel>
                    </NavItemButton>
                </NavItems>
            </NavContainer>

            {isProfileSheetOpen && (
                <ProfileSheetBackdrop role="presentation" onClick={handleCloseProfileSheet}>
                    <ProfileSheet
                        role="dialog"
                        aria-modal="true"
                        aria-label="Profile menu"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <ProfileMenuContent
                            displayName={username || ''}
                            onItemClick={handleProfileMenuNavigate}
                            onSignOut={() => {
                                setIsProfileSheetOpen(false);
                                setSignOutDialogOpen(true);
                            }}
                        />
                    </ProfileSheet>
                </ProfileSheetBackdrop>
            )}
            {signOutDialogOpen && (
                <ConfirmDialog
                    open
                    title="Sign out?"
                    message="You’ll need your recovery phrase to log back in."
                    confirmLabel="Sign out"
                    confirmVariant="danger"
                    onConfirm={() => {
                        setSignOutDialogOpen(false);
                        navigate('/sign_out');
                    }}
                    onCancel={() => setSignOutDialogOpen(false)}
                />
            )}
        </>,
        document.body
    );
}

export { communityFromPathname, createPostPathForContext };

export default MobileBottomNav;
