import React from 'react';
import styled from 'styled-components';
import { Link, useLocation } from 'react-router-dom';
import MobileBottomNav from '../components/MobileBottomNav';

const Container = styled.div`
    width: 100%;
    padding: 0 0.5rem;
    padding-bottom: 3rem;
    @media (max-width: 600px) {
        padding: 0 0.25rem;
        padding-bottom: 80px;
    }
`;

const TopBar = styled.div`
    display: flex;
    align-items: baseline;
    padding: 0.5rem 0.5rem 0.35rem;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border};
    background: ${({ theme }) => theme?.colors?.panel};
    font-size: 0.7rem;
    gap: 0.75rem;
    flex-wrap: wrap;
`;

const Brand = styled(Link)`
    font-weight: 700;
    font-size: 1.4rem;
    color: ${({ theme }) => theme?.colors?.text};
    text-decoration: none;
    letter-spacing: 0.05em;
    line-height: 1;
    flex-shrink: 0;
`;

const PageTitle = styled.span`
    font-size: 0.8rem;
    font-weight: 400;
    color: ${({ theme }) => theme?.colors?.subtleText};
    white-space: nowrap;
`;

const Nav = styled.div`
    display: flex;
    gap: 0.5rem;
    margin-left: auto;
`;

const NavLink = styled(Link)`
    color: ${({ theme, $active }) => ($active ? theme?.colors?.text : theme?.colors?.subtleText)};
    text-decoration: none;
    font-weight: 600;
    &:hover {
        color: ${({ theme }) => theme?.colors?.text};
        text-decoration: underline;
    }
`;

const PAGE_TITLES = {
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
    return null;
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
    const isProfile = path.startsWith('/profile');
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
                            <NavLink to="/profile" $active={isProfile}>profile</NavLink>
                        </>
                    )}
                    <NavLink to="/settings" $active={isSettings}>settings</NavLink>
                </Nav>
            </TopBar>
            <Container>{children}</Container>
            <MobileBottomNav state={state} />
        </>
    );
}
