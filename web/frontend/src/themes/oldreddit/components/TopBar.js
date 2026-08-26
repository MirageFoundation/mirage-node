import React, { useState, useRef, useEffect } from "react";
import styled from "styled-components";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { SearchContainer, SearchRow, SearchInput } from "../Layout";
import Storage from "../../../utils/Storage";
import Button from "./Button";
import GuestThemeMenu from "../../../components/GuestThemeMenu";
import { formatMirageBalance } from "../../../utils/formatters";
import useBalance from "../../../logic/useBalance";

const UserControls = styled.div`
    display: flex;
    align-items: center;
    gap: 0.75rem;
`;

const BalanceDisplay = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.55rem 0.85rem;
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 18px;
    flex-shrink: 0;

    @media (max-width: 800px) {
        padding: 0.45rem 0.7rem;
    }
`;

const BalanceAmount = styled.span`
    font-size: 0.85rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.text};
    font-variant-numeric: tabular-nums;
`;

const BalanceLabel = styled.span`
    font-size: 0.75rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const TabletLogo = styled(Link)`
    display: none;
    font-size: 1rem;
    font-weight: 800;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    letter-spacing: 0.05em;
    white-space: nowrap;
    flex-shrink: 0;
    ${({ theme }) => theme.name !== 'light' && `
        animation: glowWander 8s ease-in-out infinite;
    `}

    @keyframes glowWander {
        0% { text-shadow: 0 0 12px rgba(255, 255, 255, 0.4), 6px 2px 15px rgba(255, 255, 255, 0.25); }
        50% { text-shadow: 0 0 10px rgba(255, 255, 255, 0.45), -6px -2px 15px rgba(255, 255, 255, 0.25); }
        100% { text-shadow: 0 0 12px rgba(255, 255, 255, 0.4), 6px 2px 15px rgba(255, 255, 255, 0.25); }
    }

    @media (max-width: 1000px) {
        display: block;
    }
`;

const TabletNav = styled.div`
    display: none;
    gap: 0.25rem;
    margin-top: 0.5rem;

    @media (max-width: 1000px) {
        display: flex;
    }
`;

const TabletNavItem = styled(Link)`
    padding: 0.35rem 0.75rem;
    border-radius: 16px;
    text-decoration: none;
    font-size: 0.8rem;
    font-weight: 500;
    color: ${({ theme, $active }) => $active ? '#fff' : (theme.colors.text)};
    background: ${({ theme, $active }) => $active
        ? 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
        : (theme.colors.panelAlt)};
    border: 1px solid ${({ theme, $active }) => $active ? 'transparent' : (theme.colors.border)};
    transition: all 0.15s ease;

    &:hover {
        background: ${({ $active }) => $active
        ? 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
        : 'rgba(102, 126, 234, 0.15)'};
        border-color: ${({ $active }) => $active ? 'transparent' : 'rgba(102, 126, 234, 0.3)'};
    }
`;

const InboxLink = styled.a`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2.2rem;
    height: 2.2rem;
    border-radius: 50%;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panel};
    color: ${({ $hasUnread, theme }) => $hasUnread ? '#FF3B30' : (theme.colors.text)};
    text-decoration: none;
    transition: all 0.15s ease;
    position: relative;
    cursor: pointer;

    &:hover {
        background: ${({ theme }) => theme.colors.accent};
        transform: scale(1.05);
    }

    @media (max-width: 600px) {
        display: ${({ $hasUnread }) => $hasUnread ? 'inline-flex' : 'none'};
    }
`;

const formatBadgeCount = (n) => n > 99 ? '99+' : String(n);

const InboxIcon = styled.svg`
    width: 1.1rem;
    height: 1.1rem;
    fill: currentColor;
`;

const UnreadBadge = styled.span`
    position: absolute;
    top: -5px;
    right: -9px;
    min-width: 24px;
    height: 24px;
    padding: 0 6px;
    background: #FF3B30;
    border-radius: 12px;
    border: 2px solid ${({ theme }) => theme.colors.panel};
    color: #fff;
    font-size: 11px;
    font-weight: 700;
    line-height: 20px;
    text-align: center;
    box-sizing: border-box;
`;

const MenuWrapper = styled.div`
    position: relative;
    display: inline-flex;
`;

const Avatar = styled.button`
    width: 2.2rem;
    height: 2.2rem;
    border-radius: 50%;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: #FFFFFF;
    font-weight: 600;
    font-size: 0.9rem;
    border: none;
    padding: 0;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    text-transform: uppercase;
    letter-spacing: 0.02em;
    transition: transform 0.15s ease;
    font-family: inherit;
    box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
    overflow: hidden;
    -webkit-appearance: none;
    appearance: none;

    &:hover {
        transform: scale(1.08);
    }
    &:focus-visible {
        outline: 2px solid rgba(255, 255, 255, 0.6);
        outline-offset: 2px;
    }
    &:active {
        transform: scale(0.98);
    }
`;

const Dropdown = styled.div`
    position: absolute;
    right: 0;
    top: calc(100% + 0.5rem);
    background-color: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    padding: 0.5rem 0;
    min-width: 12rem;
    z-index: 10000;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
`;

const DropdownHeader = styled.div`
    padding: 0.6rem 0.85rem 0.7rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    margin-bottom: 0.35rem;
`;

const DropdownUsername = styled.div`
    font-size: 0.9rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.text};
    word-break: break-all;
`;

const MenuItem = styled(Link)`
    display: block;
    padding: 0.5rem 0.85rem;
    font-size: 0.85rem;
    white-space: nowrap;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    transition: background-color 0.15s;
    &:hover {
        background-color: ${({ theme }) => theme.colors.panelAlt};
    }
`;

const MenuDivider = styled.div`
    height: 1px;
    background: ${({ theme }) => theme.colors.border};
    margin: 0.35rem 0;
`;

// Shared profile menu content used by both TopBar dropdown and mobile bottom sheet
export function ProfileMenuContent({ displayName, onItemClick }) {
    const userLevel = Number(Storage.load('user_level', '0')) || 0;
    const isAdmin = userLevel >= 100;

    const handleItemClick = (targetPath) => {
        if (typeof onItemClick === 'function') {
            onItemClick(targetPath);
        }
    };

    return (
        <>
            <DropdownHeader>
                {displayName && <DropdownUsername>@{displayName}</DropdownUsername>}
            </DropdownHeader>
            <MenuItem
                to="/profile"
                onClick={() => handleItemClick('/profile')}
            >
                Profile
            </MenuItem>
            <MenuItem
                to="/subscription"
                onClick={() => handleItemClick('/subscription')}
            >
                Subscription
            </MenuItem>
            <MenuItem
                to="/settings"
                onClick={() => handleItemClick('/settings')}
            >
                Settings
            </MenuItem>
            <MenuItem
                to="/follows"
                onClick={() => handleItemClick('/follows')}
            >
                Follows
            </MenuItem>
            <MenuItem
                to="/blocks"
                onClick={() => handleItemClick('/blocks')}
            >
                Blocks
            </MenuItem>
            <MenuItem
                to="/agents"
                onClick={() => handleItemClick('/agents')}
            >
                Agents
            </MenuItem>
            <MenuItem
                to="/network"
                onClick={() => handleItemClick('/network')}
            >
                Network
            </MenuItem>
            {isAdmin && (
                <>
                    <MenuDivider />
                    <MenuItem
                        to="/reports"
                        onClick={() => handleItemClick('/reports')}
                    >
                        Reports
                    </MenuItem>
                </>
            )}
            <MenuDivider />
            <MenuItem
                to="/sign_out"
                onClick={() => handleItemClick('/sign_out')}
            >
                Sign Out
            </MenuItem>
        </>
    );
}

function TopBar({ state }) {
    // Hide TopBar entirely on mobile viewports
    const [isMobile, setIsMobile] = useState(() => {
        if (typeof window === 'undefined') return false;
        try {
            return window.innerWidth <= 600;
        } catch (_) {
            return false;
        }
    });
    const location = useLocation();
    const navigate = useNavigate();
    const pathname = location?.pathname || "";
    const isAuthRoute = pathname === "/login" || pathname === "/signup";
    const publicKey = (state && state.publicKey) ? state.publicKey : Storage.load("publicKey", "");
    const username = (state && state.username) ? state.username : Storage.load("username", "");
    const hasPublicKey = !!publicKey;
    const showAuthButton = !hasPublicKey && !isAuthRoute;

    const [menuOpen, setMenuOpen] = useState(false);
    const [inboxCount, setInboxCount] = useState(() => {
        try {
            const stored = localStorage.getItem('inbox_count');
            return stored ? Math.max(0, parseInt(stored, 10) || 0) : 0;
        } catch (_) { return 0; }
    });
    const [searchQuery, setSearchQuery] = useState('');
    const { displayBalance } = useBalance();
    const menuRef = useRef(null);
    const mountedRef = useRef(true);

    useEffect(() => {
        mountedRef.current = true;
        return () => { mountedRef.current = false; };
    }, []);

    // Track viewport changes to toggle mobile state
    useEffect(() => {
        const updateIsMobile = () => {
            try {
                setIsMobile(window.innerWidth <= 600);
            } catch (_) { }
        };
        updateIsMobile();
        window.addEventListener('resize', updateIsMobile);
        window.addEventListener('orientationchange', updateIsMobile);
        return () => {
            window.removeEventListener('resize', updateIsMobile);
            window.removeEventListener('orientationchange', updateIsMobile);
        };
    }, []);

    // Listen for server-side inbox count from every API response
    useEffect(() => {
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
    }, [publicKey]);

    useEffect(() => {
        const onDocClick = (e) => {
            try {
                if (menuRef.current && !menuRef.current.contains(e.target)) {
                    setMenuOpen(false);
                }
            } catch (_) { }
        };
        document.addEventListener('mousedown', onDocClick, true);
        return () => document.removeEventListener('mousedown', onDocClick, true);
    }, []);

    useEffect(() => {
        setMenuOpen(false);
    }, [pathname]);

    const getInitials = (name) => {
        if (!name) return '?';
        let str = String(name).trim();
        if (str.startsWith('@')) str = str.slice(1);
        if (str.startsWith('Anon-')) str = str.slice(5);
        if (str.startsWith('mirage1')) return 'M';
        if (!str) return '?';
        return str.charAt(0).toUpperCase();
    };

    const displayName = username || '';
    const initials = getInitials(displayName || publicKey);

    const handleSearchKeyDown = (e) => {
        if (e.key === 'Enter' && searchQuery.trim()) {
            navigate(`/search?q=${encodeURIComponent(searchQuery.trim())}`);
        }
    };

    if (isMobile) return null;

    const handleNavClick = (targetPath, e) => {
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
        const currentPathname = location.pathname;
        const isAlreadyOnRoute = currentPathname === targetPath ||
            (targetPath === '/home' && (currentPathname === '/' || currentPathname === '/home'));

        if (isAlreadyOnRoute) {
            e.preventDefault();
            window.scrollTo({ top: 0, behavior: 'smooth' });
            window.dispatchEvent(new CustomEvent('mirageRefreshFeed'));
        }
    };

    const isNavActive = (path) => {
        if (path === '/home') {
            return pathname === '/home' || pathname === '/';
        }
        return pathname === path;
    };

    return (
        <SearchContainer>
            <SearchRow>
                <TabletLogo to="/home">MIRAGE</TabletLogo>
                <SearchInput
                    type="text"
                    placeholder="Search..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={handleSearchKeyDown}
                />
                {hasPublicKey && (
                    <BalanceDisplay title="Your MIRAGE balance">
                        <BalanceAmount>{displayBalance === null ? '~' : formatMirageBalance(displayBalance)}</BalanceAmount>
                        <BalanceLabel>MIRAGE</BalanceLabel>
                    </BalanceDisplay>
                )}
                {showAuthButton && (
                    <Button to="/signup" variant="secondary" size="pill">Sign in / Sign up</Button>
                )}
                {!hasPublicKey && <GuestThemeMenu />}
                {hasPublicKey && (
                    <UserControls>
                        <InboxLink
                            href="/inbox"
                            $hasUnread={inboxCount > 0}
                            title="Inbox"
                            onClick={(e) => {
                                // Allow right-click, ctrl+click, cmd+click, middle-click to work natively
                                if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                    e.preventDefault();
                                    navigate('/inbox');
                                }
                            }}
                        >
                            <InboxIcon viewBox="0 0 24 24">
                                <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z" />
                            </InboxIcon>
                            {inboxCount > 0 && <UnreadBadge>{formatBadgeCount(inboxCount)}</UnreadBadge>}
                        </InboxLink>
                        <MenuWrapper ref={menuRef}>
                            <Avatar
                                aria-label="user menu"
                                aria-haspopup="true"
                                aria-expanded={menuOpen}
                                onClick={() => setMenuOpen((v) => !v)}
                                title={displayName || publicKey}
                            >
                                {initials}
                            </Avatar>
                            {menuOpen && (
                                <Dropdown>
                                    <ProfileMenuContent
                                        displayName={displayName}
                                        onItemClick={() => {
                                            setMenuOpen(false);
                                        }}
                                    />
                                </Dropdown>
                            )}
                        </MenuWrapper>
                    </UserControls>
                )}
            </SearchRow>
            <TabletNav>
                <TabletNavItem
                    to="/home"
                    $active={isNavActive('/home')}
                    onClick={(e) => handleNavClick('/home', e)}
                >
                    Home
                </TabletNavItem>
                <TabletNavItem
                    to="/following"
                    $active={isNavActive('/following')}
                    onClick={(e) => handleNavClick('/following', e)}
                >
                    Following
                </TabletNavItem>
                <TabletNavItem
                    to="/topics"
                    $active={isNavActive('/topics')}
                >
                    Topics
                </TabletNavItem>
            </TabletNav>
        </SearchContainer>
    );
}

export default TopBar;


