import React, { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import { Link, useLocation } from 'react-router-dom';
import Storage from '../../utils/Storage';
import MobileBottomNav from './components/MobileBottomNav';
import { ProfileMenuContent } from './components/TopBar';

/** Same horizontal inset for nav row and all page content below */
const SHELL_INSET_X = '0.75rem';

const Container = styled.div`
    width: 100%;
    padding: 0 ${SHELL_INSET_X};
    padding-bottom: 3rem;
    @media (max-width: 600px) {
        padding-bottom: 80px;
    }
`;

const TopBar = styled.div`
    display: flex;
    align-items: baseline;
    padding: 0.5rem ${SHELL_INSET_X} 0.35rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panel};
    font-size: 0.7rem;
    gap: 0.75rem;
    flex-wrap: wrap;
`;

const Brand = styled(Link)`
    font-weight: 700;
    font-size: 1.4rem;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    letter-spacing: 0.05em;
    line-height: 1;
    flex-shrink: 0;
`;

const PageTitle = styled.span`
    font-size: 0.8rem;
    font-weight: 400;
    color: ${({ theme }) => theme.colors.subtleText};
    white-space: nowrap;
`;

const Nav = styled.div`
    display: flex;
    gap: 0.5rem;
    margin-left: auto;
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

const NavSep = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    user-select: none;
    font-weight: 600;
`;

const UserMenuWrapper = styled.div`
    position: relative;
    display: inline-flex;
    align-items: baseline;
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
    color: ${({ theme, $active }) => ($active ? theme.colors.text : theme.colors.subtleText)};
    text-decoration: ${({ $active }) => ($active ? 'underline' : 'none')};
    &:hover {
        color: ${({ theme }) => theme.colors.text};
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
    '/create_post': 'submit',
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

    return (
        <UserMenuWrapper ref={wrapRef}>
            <NavSep aria-hidden="true">|</NavSep>
            <UserMenuTrigger
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                aria-haspopup="menu"
                $active={open || isAccountSection}
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
    const isFollowing = path === '/following';
    const isTopics = path === '/topics';
    const isSettings = path === '/settings';
    const isSubmit = path === '/create_post';
    const isInbox = path === '/inbox';
    const isLoggedIn = !!(state && state.publicKey);

    const pageTitle = getPageTitle(path);

    return (
        <>
            <TopBar>
                <Brand to="/home">MIRAGE</Brand>
                {pageTitle && <PageTitle>{pageTitle}</PageTitle>}
                <Nav>
                    <NavLink to="/home" $active={isHome}>home</NavLink>
                    <NavLink to="/following" $active={isFollowing}>following</NavLink>
                    <NavLink to="/topics" $active={isTopics}>topics</NavLink>
                    {isLoggedIn && (
                        <>
                            <NavLink to="/create_post" $active={isSubmit}>submit</NavLink>
                            <NavLink to="/inbox" $active={isInbox}>inbox</NavLink>
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
