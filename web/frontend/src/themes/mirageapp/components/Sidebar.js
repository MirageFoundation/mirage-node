import React from 'react';
import styled from 'styled-components';
import { Link, useLocation } from 'react-router-dom';

/**
 * Desktop sidebar rail for the mirageapp theme.
 * Rendered by `MirageAppShell` next to the main content column.
 * Hidden below 1000px via CSS (the shell also collapses the column).
 *
 * Structure:
 *   - Primary nav (Home, Following, Topics, Create)
 *   - Account section (Profile, Settings, Subscription)
 *   - Moderation section (Follows, Blocks, Reports)
 *   - Info section (Network, Referrals, Stats)
 *   - About Mirage footer
 */

const Aside = styled.aside`
    position: sticky;
    top: calc(3.5rem + 1px); /* TopBar height + border */
    align-self: start;
    width: 240px;
    max-height: calc(100vh - 3.5rem - 1px);
    overflow-y: auto;
    padding: 1rem 0.5rem 2rem 1rem;
    box-sizing: border-box;
    scrollbar-width: thin;
    scrollbar-color: ${({ theme }) => theme.colors.scrollbar} transparent;

    &::-webkit-scrollbar { width: 6px; }
    &::-webkit-scrollbar-thumb {
        background: ${({ theme }) => theme.colors.scrollbar};
        border-radius: 3px;
    }

    @media (max-width: 1000px) {
        display: none;
    }
`;

const Section = styled.nav`
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 0.35rem 0.25rem 0.75rem;

    & + & {
        border-top: 1px solid ${({ theme }) => theme.colors.border};
        margin-top: 0.5rem;
        padding-top: 0.75rem;
    }
`;

const SectionLabel = styled.div`
    padding: 0 0.75rem 0.25rem;
    font-size: 0.65rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const Item = styled(Link)`
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.5rem 0.75rem;
    border-radius: 10px;
    color: ${({ theme, $active }) => ($active ? theme.colors.text : theme.colors.text)};
    background: ${({ theme, $active }) => ($active ? theme.colors.panelAlt : 'transparent')};
    font-size: 0.82rem;
    font-weight: ${({ $active }) => ($active ? 700 : 500)};
    text-decoration: none;
    line-height: 1.2;

    &:hover {
        background: ${({ theme }) => theme.colors.panelAlt};
        text-decoration: none;
    }
`;

const IconBox = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    flex-shrink: 0;
    color: ${({ theme, $active }) => ($active ? theme.colors.link : theme.colors.subtleText)};

    svg { width: 18px; height: 18px; }
`;

const Footer = styled.div`
    padding: 1rem 0.75rem 0;
    margin-top: 0.75rem;
    border-top: 1px solid ${({ theme }) => theme.colors.border};
    font-size: 0.65rem;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.5;

    a {
        color: ${({ theme }) => theme.colors.link};
        text-decoration: none;
        &:hover { text-decoration: underline; }
    }
`;

// Small inline icons (hairline) — match Reddit-style sidebar rail
const icons = {
    home: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V10.5Z" />
        </svg>
    ),
    following: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 21s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.5-7 10-7 10Z" />
        </svg>
    ),
    topics: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 6h16M4 12h16M4 18h10" />
        </svg>
    ),
    create: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14M5 12h14" />
        </svg>
    ),
    search: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7" />
            <path d="m21 21-4.3-4.3" />
        </svg>
    ),
    profile: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="8" r="4" />
            <path d="M4 21c0-4 4-7 8-7s8 3 8 7" />
        </svg>
    ),
    inbox: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 12h-6l-2 3h-4l-2-3H2" />
            <path d="M5 7h14l3 5v7a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-7l3-5Z" />
        </svg>
    ),
    settings: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c.2.6.8 1 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
        </svg>
    ),
    subscription: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2 15 8l6 .9-4.5 4.3 1.1 6.3L12 16.8l-5.6 2.7L7.5 13.2 3 8.9 9 8Z" />
        </svg>
    ),
    follows: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="9" cy="8" r="3.5" />
            <path d="M2.5 20c0-3.3 2.9-5.5 6.5-5.5S15.5 16.7 15.5 20" />
            <path d="M17 11l2 2 4-4" />
        </svg>
    ),
    blocks: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="9" />
            <path d="m5.5 5.5 13 13" />
        </svg>
    ),
    reports: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 4v17" />
            <path d="M4 5h12l-2 4 2 4H4" />
        </svg>
    ),
    network: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="9" />
            <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
        </svg>
    ),
    referrals: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2v20M2 12h20" />
            <circle cx="12" cy="12" r="5" />
        </svg>
    ),
    stats: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
        </svg>
    ),
    agents: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="4" y="7" width="16" height="12" rx="2" />
            <path d="M9 3v4M15 3v4M9 13h.01M15 13h.01" />
        </svg>
    ),
    bridge: (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 17V9M21 17V9M3 13h18" />
        </svg>
    ),
};

function isActivePath(pathname, target) {
    if (target === '/home') return pathname === '/' || pathname === '/home' || pathname.startsWith('/t/');
    if (target === '/profile') return pathname === '/profile' || pathname.startsWith('/u/');
    return pathname === target;
}

function SidebarItem({ to, icon, label, pathname }) {
    const active = isActivePath(pathname, to);
    return (
        <Item to={to} $active={active}>
            <IconBox $active={active}>{icon}</IconBox>
            {label}
        </Item>
    );
}

function Sidebar({ state }) {
    const location = useLocation();
    const pathname = location.pathname;
    const isLoggedIn = !!(state && state.publicKey);

    return (
        <Aside aria-label="Sidebar">
            <Section>
                <SectionLabel>Feeds</SectionLabel>
                <SidebarItem to="/home" icon={icons.home} label="Home" pathname={pathname} />
                {isLoggedIn && (
                    <SidebarItem to="/following" icon={icons.following} label="Following" pathname={pathname} />
                )}
                <SidebarItem to="/topics" icon={icons.topics} label="Topics" pathname={pathname} />
                {isLoggedIn && (
                    <SidebarItem to="/create_post" icon={icons.create} label="Create post" pathname={pathname} />
                )}
                <SidebarItem to="/search" icon={icons.search} label="Search" pathname={pathname} />
            </Section>

            {isLoggedIn && (
                <Section>
                    <SectionLabel>Account</SectionLabel>
                    <SidebarItem to="/profile" icon={icons.profile} label="Profile" pathname={pathname} />
                    <SidebarItem to="/inbox" icon={icons.inbox} label="Inbox" pathname={pathname} />
                    <SidebarItem to="/subscription" icon={icons.subscription} label="Subscription" pathname={pathname} />
                    <SidebarItem to="/settings" icon={icons.settings} label="Settings" pathname={pathname} />
                </Section>
            )}

            {isLoggedIn && (
                <Section>
                    <SectionLabel>Moderation</SectionLabel>
                    <SidebarItem to="/follows" icon={icons.follows} label="Follows" pathname={pathname} />
                    <SidebarItem to="/blocks" icon={icons.blocks} label="Blocks" pathname={pathname} />
                    <SidebarItem to="/agents" icon={icons.agents} label="Agents" pathname={pathname} />
                    <SidebarItem to="/reports" icon={icons.reports} label="Reports" pathname={pathname} />
                </Section>
            )}

            <Section>
                <SectionLabel>Network</SectionLabel>
                <SidebarItem to="/network" icon={icons.network} label="This node" pathname={pathname} />
                <SidebarItem to="/stats" icon={icons.stats} label="Stats" pathname={pathname} />
                {isLoggedIn && (
                    <SidebarItem to="/referrals" icon={icons.referrals} label="Referrals" pathname={pathname} />
                )}
                <SidebarItem to="/bridge" icon={icons.bridge} label="Bridge" pathname={pathname} />
            </Section>

            <Footer>
                Mirage is a decentralized social network.
                <br />
                <a href="https://mirage.foundation" target="_blank" rel="noopener noreferrer">
                    About Mirage ↗
                </a>
            </Footer>
        </Aside>
    );
}

export default Sidebar;
