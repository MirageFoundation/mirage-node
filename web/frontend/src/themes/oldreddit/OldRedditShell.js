import React, { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import { Link, useLocation } from 'react-router-dom';
import Storage from '../../utils/Storage';
import { getTierColor } from '../../utils/tierColors';
import MobileBottomNav from './components/MobileBottomNav';
import { ProfileMenuContent } from './components/TopBar';
import { OLDREDDIT_SHELL_INSET_X } from './Layout';

const Container = styled.div`
    width: 100%;
    padding: 0 ${OLDREDDIT_SHELL_INSET_X};
    padding-bottom: 3rem;
    background-color: ${({ theme }) => theme.colors.panel};
    @media (max-width: 600px) {
        padding-bottom: 52px;
    }
`;

const TopBar = styled.div`
    display: flex;
    align-items: baseline;
    padding: 0.5rem ${OLDREDDIT_SHELL_INSET_X} 0.35rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panel};
    font-size: 0.7rem;
    gap: 0.75rem;
    flex-wrap: wrap;

    @media (max-width: 600px) {
        padding: 0.35rem 0.5rem 0.25rem;
        gap: 0.5rem;
    }
`;

const Brand = styled(Link)`
    font-weight: 700;
    font-size: 1.4rem;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    letter-spacing: 0.05em;
    line-height: 1;
    flex-shrink: 0;

    @media (max-width: 600px) {
        font-size: 1rem;
    }
`;

const PageTitle = styled.span`
    font-size: 0.8rem;
    font-weight: 400;
    color: ${({ theme }) => theme.colors.subtleText};
    white-space: nowrap;
`;

const Nav = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-left: auto;

    @media (max-width: 600px) {
        display: none;
    }
`;

const NavLink = styled(Link)`
    color: ${({ theme, $active }) => ($active ? theme.colors.text : theme.colors.subtleText)};
    text-decoration: none;
    font-weight: 600;
    &:hover {
        color: ${({ theme }) => theme.colors.text};
        text-decoration: underline;
    }
`;

const InboxNavLink = styled(Link)`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    position: relative;
    width: 1.05rem;
    height: 1.05rem;
    color: ${({ theme, $active }) => ($active ? theme.colors.text : theme.colors.subtleText)};
    text-decoration: none;
    font-weight: 600;
    &:hover {
        color: ${({ theme }) => theme.colors.text};
    }
`;

const InboxIcon = styled.svg`
    display: block;
    width: 0.9rem;
    height: 0.9rem;
    fill: currentColor;
    flex-shrink: 0;
`;

const formatBadgeCount = (n) => n > 99 ? '99+' : String(n);

const InboxBadge = styled.span`
    position: absolute;
    top: -6px;
    right: -8px;
    min-width: 16px;
    height: 16px;
    padding: 0 4px;
    background: #FF3B30;
    border-radius: 8px;
    border: 1px solid ${({ theme }) => theme.colors.panel};
    color: #fff;
    font-size: 0.55rem;
    font-weight: 700;
    line-height: 16px;
    text-align: center;
    box-sizing: border-box;
`;

const NavSep = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    user-select: none;
    font-weight: 600;
`;

const UserMenuWrapper = styled.div`
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
`;

const UserMenuTrigger = styled.button`
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    font: inherit;
    font-size: inherit;
    font-weight: 600;
    color: ${({ theme, $active, $tierColor }) => {
        if ($tierColor) return $tierColor;
        return $active ? theme.colors.text : theme.colors.subtleText;
    }};
    text-decoration: ${({ $active }) => ($active ? 'underline' : 'none')};
    &:hover {
        color: ${({ theme, $tierColor }) => ($tierColor ? $tierColor : theme.colors.text)};
        text-decoration: underline;
    }
`;

const UserDropdown = styled.div`
    position: absolute;
    right: 0;
    top: calc(100% + 0.35rem);
    background-color: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    padding: 0.5rem 0;
    min-width: 12rem;
    z-index: 10000;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
`;

const PAGE_TITLES = {
    '/home': 'home',
    '/following': 'following',
    '/create_post': 'create',
    '/inbox': 'inbox',
    '/profile': 'profile',
    '/settings': 'settings',
    '/topics': 'topics',
    '/subscription': 'subscription',
    '/network': 'network',
    '/stats': 'stats',
    '/agents': 'agents',
    '/blocks': 'blocks',
    '/follows': 'follows',
    '/referrals': 'referrals',
    '/reports': 'reports',
    '/search': 'search',
    '/bridge': 'bridge',
};

function getPageTitle(path) {
    for (const [prefix, title] of Object.entries(PAGE_TITLES)) {
        if (path === prefix || path.startsWith(prefix + '/')) return title;
    }
    if (path.startsWith('/t/')) {
        const topic = decodeURIComponent(path.split('/')[2] || '');
        return topic ? `t/${topic}` : null;
    }
    if (path.startsWith('/u/')) {
        const user = decodeURIComponent(path.split('/')[2] || '');
        return user ? `u/${user}` : null;
    }
    if (path.startsWith('/p/')) return 'post';
    if (path === '/') return 'home';
    return null;
}

function ShellUserMenu({ state }) {
    const [open, setOpen] = useState(false);
    const [userLevel, setUserLevel] = useState(() => Number(Storage.load('user_level', '0')) || 0);
    const wrapRef = useRef(null);
    const location = useLocation();
    const username = (state && state.username) ? state.username : Storage.load('username', '');
    const publicKey = (state && state.publicKey) ? state.publicKey : Storage.load('publicKey', '');
    const shortAddr =
        publicKey && publicKey.length > 14
            ? `${publicKey.slice(0, 6)}…${publicKey.slice(-4)}`
            : publicKey || '';
    const triggerLabel = username || shortAddr || 'account';
    const menuDisplayName = username || '';
    const path = location.pathname;
    const isProfile = path.startsWith('/profile');
    const isSettings = path === '/settings';
    const isAccountSection =
        isProfile ||
        isSettings ||
        path.startsWith('/subscription') ||
        path === '/follows' ||
        path === '/blocks' ||
        path === '/agents' ||
        path === '/network' ||
        path === '/referrals' ||
        path === '/reports' ||
        path === '/sign_out';

    useEffect(() => {
        const onDoc = (e) => {
            try {
                if (wrapRef.current && !wrapRef.current.contains(e.target)) {
                    setOpen(false);
                }
            } catch (_) { }
        };
        document.addEventListener('mousedown', onDoc, true);
        return () => document.removeEventListener('mousedown', onDoc, true);
    }, []);

    useEffect(() => {
        setOpen(false);
    }, [location.pathname]);

    useEffect(() => {
        const syncLevel = () => {
            setUserLevel(Number(Storage.load('user_level', '0')) || 0);
        };
        syncLevel();
        window.addEventListener('userStatusUpdated', syncLevel);
        return () => window.removeEventListener('userStatusUpdated', syncLevel);
    }, [state?.publicKey, location.pathname]);

    const tierColor = getTierColor(userLevel);

    return (
        <UserMenuWrapper ref={wrapRef}>
            <NavSep aria-hidden="true">|</NavSep>
            <UserMenuTrigger
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                aria-haspopup="menu"
                $active={open || isAccountSection}
                $tierColor={tierColor || undefined}
            >
                @{triggerLabel}
            </UserMenuTrigger>
            {open && (
                <UserDropdown>
                    <ProfileMenuContent
                        displayName={menuDisplayName}
                        onItemClick={() => setOpen(false)}
                    />
                </UserDropdown>
            )}
        </UserMenuWrapper>
    );
}

export default function OldRedditShell({ children, state }) {
    const location = useLocation();
    const path = location.pathname;
    const isHome = path === '/' || path === '/home' || path.startsWith('/t/');
    const isFeeds = isHome || path === '/following';
    const isTopics = path === '/topics';
    const isSettings = path === '/settings';
    const isInbox = path === '/inbox';
    const isLoggedIn = !!(state && state.publicKey);
    const [inboxCount, setInboxCount] = useState(() => {
        try {
            const stored = localStorage.getItem('inbox_count');
            return stored ? Math.max(0, parseInt(stored, 10) || 0) : 0;
        } catch (_) { return 0; }
    });

    const pageTitle = getPageTitle(path);

    useEffect(() => {
        if (!isLoggedIn) {
            setInboxCount(0);
            return;
        }
        const handleInboxCount = (e) => {
            const count = typeof e.detail === 'number' ? Math.max(0, e.detail) : 0;
            setInboxCount(count);
        };
        window.addEventListener('inboxCount', handleInboxCount);
        return () => window.removeEventListener('inboxCount', handleInboxCount);
    }, [isLoggedIn]);

    return (
        <>
            <TopBar>
                <Brand to="/home">MIRAGE</Brand>
                {pageTitle && <PageTitle>{pageTitle}</PageTitle>}
                <Nav>
                    <NavLink to="/home" $active={isFeeds}>feeds</NavLink>
                    <NavLink to="/topics" $active={isTopics}>topics</NavLink>
                    {isLoggedIn && (
                        <>
                            <InboxNavLink to="/inbox" $active={isInbox} aria-label={inboxCount > 0 ? `Inbox - ${inboxCount} unread` : 'Inbox'}>
                                <InboxIcon viewBox="0 0 24 24" aria-hidden="true">
                                    {isInbox
                                        ? <path d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z" />
                                        : <path d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V8l8 5 8-5v10zm-8-7L4 6h16l-8 5z" />
                                    }
                                </InboxIcon>
                                {inboxCount > 0 && <InboxBadge aria-hidden="true">{formatBadgeCount(inboxCount)}</InboxBadge>}
                            </InboxNavLink>
                            <ShellUserMenu state={state} />
                        </>
                    )}
                    {!isLoggedIn && (
                        <NavLink to="/settings" $active={isSettings}>settings</NavLink>
                    )}
                </Nav>
            </TopBar>
            <Container>{children}</Container>
            <MobileBottomNav state={state} />
        </>
    );
}
