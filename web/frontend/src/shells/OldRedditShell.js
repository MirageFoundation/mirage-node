import React from 'react';
import styled from 'styled-components';
import { Link, useLocation } from 'react-router-dom';
import MobileBottomNav from '../components/MobileBottomNav';

const Container = styled.div`
    width: 100%;
    max-width: 100%;
    margin: 0 auto;
    padding: 0 1rem;
    padding-bottom: 3rem;
    @media (max-width: 1000px) {
        padding: 0 0.25rem;
        padding-bottom: 3rem;
    }
    @media (min-width: 1000px) {
        max-width: 90%;
    }
    @media (max-width: 600px) {
        padding-bottom: 80px;
    }
`;

const TopBar = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.35rem 0.5rem;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border};
    background: ${({ theme }) => theme?.colors?.panel};
    font-size: 0.7rem;
`;

const Brand = styled(Link)`
    font-weight: 700;
    color: ${({ theme }) => theme?.colors?.text};
    text-decoration: none;
    letter-spacing: 0.04em;
`;

const Nav = styled.div`
    display: flex;
    gap: 0.5rem;
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

    return (
        <>
            <TopBar>
                <Brand to="/home">MIRAGE</Brand>
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
