import React, { useState, useRef, useEffect, useCallback } from 'react';
import styled from 'styled-components';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import Storage from '../../../utils/Storage';
import { getTierColor } from '../../../utils/tierColors';

/**
 * Reddit-style TopBar for the mirageapp theme.
 * Sticky top, full width. Hidden on mobile (MobileHeader takes over at ≤600px).
 *
 * Structure (left → right):
 *   [brand]  [primary nav]            [search]  [create]  [inbox]  [user menu]
 */

const Bar = styled.header`
    position: sticky;
    top: 0;
    z-index: 100;
    display: flex;
    align-items: center;
    gap: 1rem;
    padding: 0.5rem 1rem;
    background: ${({ theme }) => theme.colors.panel};
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    backdrop-filter: saturate(1.1);

    @media (max-width: 600px) {
        display: none;
    }
`;

const BrandLink = styled(Link)`
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    font-weight: 800;
    font-size: 1.1rem;
    letter-spacing: 0.02em;
    flex-shrink: 0;

    &:hover { text-decoration: none; }
`;

const BrandMark = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border-radius: 6px;
    background: ${({ theme }) => theme.colors.link};
    color: #fff;
    font-size: 0.75rem;
    font-weight: 900;
    letter-spacing: 0;
`;

const PrimaryNav = styled.nav`
    display: flex;
    align-items: center;
    gap: 0.25rem;

    @media (max-width: 900px) {
        display: none;
    }
`;

const NavItem = styled(Link)`
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.4rem 0.75rem;
    border-radius: 999px;
    color: ${({ theme, $active }) => ($active ? theme.colors.text : theme.colors.subtleText)};
    background: ${({ theme, $active }) => ($active ? theme.colors.panelAlt : 'transparent')};
    text-decoration: none;
    font-weight: 600;
    font-size: 0.78rem;

    &:hover {
        color: ${({ theme }) => theme.colors.text};
        background: ${({ theme }) => theme.colors.panelAlt};
    }
`;

const Spacer = styled.div`
    flex: 1 1 auto;
`;

const SearchForm = styled.form`
    position: relative;
    flex: 0 1 460px;
    min-width: 180px;
    max-width: 460px;

    @media (max-width: 1100px) {
        flex: 0 1 320px;
    }
    @media (max-width: 800px) {
        display: none;
    }
`;

const SearchInput = styled.input`
    width: 100%;
    box-sizing: border-box;
    padding: 0.5rem 0.85rem 0.5rem 2.1rem;
    border-radius: 999px;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panelAlt};
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.82rem;
    outline: none;

    &::placeholder { color: ${({ theme }) => theme.colors.subtleText}; }
    &:focus {
        border-color: ${({ theme }) => theme.colors.link};
        background: ${({ theme }) => theme.colors.panel};
    }
`;

const SearchIcon = styled.svg`
    position: absolute;
    left: 0.7rem;
    top: 50%;
    transform: translateY(-50%);
    width: 16px;
    height: 16px;
    color: ${({ theme }) => theme.colors.subtleText};
    pointer-events: none;
`;

const IconButton = styled(Link)`
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border-radius: 999px;
    color: ${({ theme, $active }) => ($active ? theme.colors.text : theme.colors.subtleText)};
    background: ${({ theme, $active }) => ($active ? theme.colors.panelAlt : 'transparent')};
    text-decoration: none;

    &:hover {
        color: ${({ theme }) => theme.colors.text};
        background: ${({ theme }) => theme.colors.panelAlt};
    }
`;

const CreateButton = styled(Link)`
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.45rem 0.85rem;
    border-radius: 999px;
    background: ${({ theme }) => theme.colors.panelAlt};
    color: ${({ theme }) => theme.colors.text};
    border: 1px solid ${({ theme }) => theme.colors.border};
    font-weight: 600;
    font-size: 0.8rem;
    text-decoration: none;

    &:hover {
        background: ${({ theme }) => theme.colors.accentHover};
    }

    @media (max-width: 1000px) {
        padding: 0.45rem 0.65rem;
        .create-label { display: none; }
    }
`;

const InboxBadge = styled.span`
    position: absolute;
    top: 2px;
    right: 2px;
    min-width: 16px;
    height: 16px;
    padding: 0 4px;
    background: #FF3B30;
    border-radius: 999px;
    border: 2px solid ${({ theme }) => theme.colors.panel};
    color: #fff;
    font-size: 0.55rem;
    font-weight: 700;
    line-height: 12px;
    text-align: center;
    box-sizing: border-box;
`;

const UserMenuWrapper = styled.div`
    position: relative;
    display: inline-flex;
    align-items: center;
`;

const UserMenuTrigger = styled.button`
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.35rem 0.6rem 0.35rem 0.45rem;
    border-radius: 999px;
    border: 1px solid ${({ theme, $open }) => ($open ? theme.colors.border : 'transparent')};
    background: ${({ theme, $open }) => ($open ? theme.colors.panelAlt : 'transparent')};
    color: ${({ theme }) => theme.colors.text};
    font-weight: 600;
    font-size: 0.78rem;
    cursor: pointer;

    &:hover {
        background: ${({ theme }) => theme.colors.panelAlt};
    }
`;

const Avatar = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: 999px;
    background: ${({ theme, $tierColor }) => $tierColor || theme.colors.link};
    color: #fff;
    font-size: 0.75rem;
    font-weight: 800;
    text-transform: uppercase;
    flex-shrink: 0;
`;

const UserName = styled.span`
    max-width: 10ch;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;

    @media (max-width: 1100px) { display: none; }
`;

const Dropdown = styled.div`
    position: absolute;
    right: 0;
    top: calc(100% + 0.5rem);
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    padding: 0.4rem 0;
    min-width: 14rem;
    z-index: 10000;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.28);
`;

const DropdownHeader = styled.div`
    padding: 0.4rem 0.9rem 0.5rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    margin-bottom: 0.35rem;
`;

const DropdownUsername = styled.div`
    font-size: 0.78rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
`;

const MenuItem = styled(Link)`
    display: block;
    padding: 0.5rem 0.9rem;
    font-size: 0.78rem;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    &:hover {
        background: ${({ theme }) => theme.colors.panelAlt};
    }
`;

const MenuDivider = styled.div`
    height: 1px;
    background: ${({ theme }) => theme.colors.border};
    margin: 0.35rem 0;
`;

const SignInLink = styled(Link)`
    display: inline-flex;
    align-items: center;
    padding: 0.45rem 0.95rem;
    border-radius: 999px;
    background: ${({ theme }) => theme.colors.link};
    color: #fff;
    font-weight: 700;
    font-size: 0.8rem;
    text-decoration: none;
    &:hover { filter: brightness(1.08); }
`;

// Shared profile menu content — also used by MobileBottomNav and the user-menu dropdown.
export function ProfileMenuContent({ displayName, onItemClick }) {
    const userLevel = Number(Storage.load('user_level', '0')) || 0;
    const isAdmin = userLevel >= 100;
    const [referralsEnabled, setReferralsEnabled] = useState(false);

    useEffect(() => {
        const readConfig = () => {
            try {
                const nc = JSON.parse(localStorage.getItem('nodeConfig') || '{}');
                setReferralsEnabled(!!nc.registration_invite_code_required);
            } catch (_) {
                setReferralsEnabled(false);
            }
        };
        readConfig();
        window.addEventListener('nodeConfigUpdated', readConfig);
        return () => window.removeEventListener('nodeConfigUpdated', readConfig);
    }, []);

    const handleItemClick = (targetPath) => {
        if (typeof onItemClick === 'function') onItemClick(targetPath);
    };

    return (
        <>
            <DropdownHeader>
                {displayName && <DropdownUsername>@{displayName}</DropdownUsername>}
            </DropdownHeader>
            <MenuItem to="/profile" onClick={() => handleItemClick('/profile')}>Profile</MenuItem>
            <MenuItem to="/subscription" onClick={() => handleItemClick('/subscription')}>Subscription</MenuItem>
            <MenuItem to="/settings" onClick={() => handleItemClick('/settings')}>Settings</MenuItem>
            <MenuItem to="/follows" onClick={() => handleItemClick('/follows')}>Follows</MenuItem>
            <MenuItem to="/blocks" onClick={() => handleItemClick('/blocks')}>Blocks</MenuItem>
            <MenuItem to="/agents" onClick={() => handleItemClick('/agents')}>Agents</MenuItem>
            <MenuItem to="/network" onClick={() => handleItemClick('/network')}>Network</MenuItem>
            {referralsEnabled && (
                <MenuItem to="/referrals" onClick={() => handleItemClick('/referrals')}>Referrals</MenuItem>
            )}
            {isAdmin && (
                <>
                    <MenuDivider />
                    <MenuItem to="/stats" onClick={() => handleItemClick('/stats')}>Stats</MenuItem>
                    <MenuItem to="/reports" onClick={() => handleItemClick('/reports')}>Reports</MenuItem>
                </>
            )}
            <MenuDivider />
            <MenuItem to="/sign_out" onClick={() => handleItemClick('/sign_out')}>Sign out</MenuItem>
        </>
    );
}

const formatBadgeCount = (n) => n > 99 ? '99+' : String(n);

function TopBar({ state }) {
    const location = useLocation();
    const navigate = useNavigate();
    const path = location.pathname;

    const isHome = path === '/' || path === '/home' || path.startsWith('/t/');
    const isFeeds = isHome || path === '/following';
    const isTopics = path === '/topics';
    const isInbox = path === '/inbox';
    const isLoggedIn = !!(state && state.publicKey);

    const username = (state && state.username) ? state.username : Storage.load('username', '');
    const publicKey = (state && state.publicKey) ? state.publicKey : Storage.load('publicKey', '');
    const shortAddr = publicKey && publicKey.length > 14
        ? `${publicKey.slice(0, 6)}…${publicKey.slice(-4)}`
        : publicKey || '';
    const triggerLabel = username || shortAddr || 'account';
    const avatarInitial = (username || shortAddr || 'm').slice(0, 1);

    const [userLevel, setUserLevel] = useState(() => Number(Storage.load('user_level', '0')) || 0);
    const tierColor = getTierColor(userLevel);

    const [inboxCount, setInboxCount] = useState(() => {
        try {
            const stored = localStorage.getItem('inbox_count');
            return stored ? Math.max(0, parseInt(stored, 10) || 0) : 0;
        } catch (_) { return 0; }
    });

    useEffect(() => {
        if (!isLoggedIn) { setInboxCount(0); return; }
        const onInbox = (e) => {
            const count = typeof e.detail === 'number' ? Math.max(0, e.detail) : 0;
            setInboxCount(count);
        };
        window.addEventListener('inboxCount', onInbox);
        return () => window.removeEventListener('inboxCount', onInbox);
    }, [isLoggedIn]);

    useEffect(() => {
        const sync = () => setUserLevel(Number(Storage.load('user_level', '0')) || 0);
        sync();
        window.addEventListener('userStatusUpdated', sync);
        return () => window.removeEventListener('userStatusUpdated', sync);
    }, [state?.publicKey]);

    const [menuOpen, setMenuOpen] = useState(false);
    const menuRef = useRef(null);
    useEffect(() => {
        const onDoc = (e) => {
            if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
        };
        document.addEventListener('mousedown', onDoc, true);
        return () => document.removeEventListener('mousedown', onDoc, true);
    }, []);
    useEffect(() => { setMenuOpen(false); }, [location.pathname]);

    const [query, setQuery] = useState('');
    const handleSearchSubmit = useCallback((e) => {
        e.preventDefault();
        const q = query.trim();
        if (!q) return;
        navigate(`/search?q=${encodeURIComponent(q)}`);
    }, [query, navigate]);

    return (
        <Bar>
            <BrandLink to="/home" aria-label="Mirage home">
                <BrandMark>M</BrandMark>
                <span>Mirage</span>
            </BrandLink>

            <PrimaryNav aria-label="Primary">
                <NavItem to="/home" $active={isFeeds}>Home</NavItem>
                {isLoggedIn && <NavItem to="/following" $active={path === '/following'}>Following</NavItem>}
                <NavItem to="/topics" $active={isTopics}>Topics</NavItem>
            </PrimaryNav>

            <Spacer />

            <SearchForm role="search" onSubmit={handleSearchSubmit}>
                <SearchIcon viewBox="0 0 24 24" aria-hidden="true">
                    <path
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M21 21l-4.35-4.35M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z"
                    />
                </SearchIcon>
                <SearchInput
                    type="search"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search Mirage"
                    aria-label="Search"
                />
            </SearchForm>

            {isLoggedIn && (
                <CreateButton to="/create_post" aria-label="Create post">
                    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
                        <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" d="M12 5v14M5 12h14" />
                    </svg>
                    <span className="create-label">Create</span>
                </CreateButton>
            )}

            {isLoggedIn && (
                <IconButton
                    to="/inbox"
                    $active={isInbox}
                    aria-label={inboxCount > 0 ? `Inbox, ${inboxCount} unread` : 'Inbox'}
                >
                    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                        {isInbox
                            ? <path fill="currentColor" d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z" />
                            : <path fill="currentColor" d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V8l8 5 8-5v10zm-8-7L4 6h16l-8 5z" />
                        }
                    </svg>
                    {inboxCount > 0 && <InboxBadge aria-hidden="true">{formatBadgeCount(inboxCount)}</InboxBadge>}
                </IconButton>
            )}

            {isLoggedIn ? (
                <UserMenuWrapper ref={menuRef}>
                    <UserMenuTrigger
                        type="button"
                        $open={menuOpen}
                        onClick={() => setMenuOpen((v) => !v)}
                        aria-haspopup="menu"
                        aria-expanded={menuOpen}
                    >
                        <Avatar $tierColor={tierColor || undefined}>{avatarInitial}</Avatar>
                        <UserName>@{triggerLabel}</UserName>
                    </UserMenuTrigger>
                    {menuOpen && (
                        <Dropdown role="menu">
                            <ProfileMenuContent
                                displayName={username}
                                onItemClick={() => setMenuOpen(false)}
                            />
                        </Dropdown>
                    )}
                </UserMenuWrapper>
            ) : (
                <SignInLink to="/login">Sign in</SignInLink>
            )}
        </Bar>
    );
}

export default TopBar;
