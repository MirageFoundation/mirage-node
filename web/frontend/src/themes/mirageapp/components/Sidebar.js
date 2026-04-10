import React, { useEffect, useState } from 'react';
import styled from 'styled-components';
import { Link, useLocation } from 'react-router-dom';
import Storage from '../../../utils/Storage';
import { fetchFollowedTopics, loadSubscriptions } from '../../../utils/Subscriptions';
import { fetchFollowedUsers, loadFollowedAuthors } from '../../../utils/FollowUsers';
import { resolveUsernames } from '../../../utils/UsernameCache';

/**
 * Desktop sidebar rail for the mirageapp theme.
 * Rendered by `MirageAppShell` next to the main content column.
 * Hidden below 1000px via CSS (the shell also collapses the column).
 *
 * Structure:
 *   - Primary nav (Home, Following, Topics, Create post, Search)
 *   - Topics you follow (collapsible)
 *   - Users you follow (collapsible)
 */

const Aside = styled.aside`
    position: sticky;
    top: calc(3.5rem + 1px);
    align-self: start;
    width: 240px;
    max-height: calc(100vh - 3.5rem - 1px);
    overflow-y: auto;
    padding: 0.25rem 0.75rem 2rem 0.5rem;
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
    /* padding-bottom intentionally 0: the only vertical space below a */
    /* section comes from the next section's margin-top, which keeps the */
    /* space above and below a collapsed SectionHeader equal. */
    padding: 0.25rem 0 0;

    & + & {
        margin-top: 0.5rem;
        padding-top: 0.5rem;
        border-top: 1px solid ${({ theme }) => theme.colors.border};
    }
`;

const SectionHeader = styled.button`
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: 0.4rem 0.6rem;
    margin: 0;
    background: transparent;
    border: none;
    font-family: inherit;
    font-size: 0.6rem;
    font-weight: 400;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.subtleText};
    cursor: pointer;
    border-radius: 8px;

    /* Hover: only background changes — text & chevron color stay the same. */
    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
        color: ${({ theme }) => theme.colors.subtleText};
    }
`;

const Chevron = styled.svg`
    width: 16px;
    height: 16px;
    flex-shrink: 0;
    color: inherit;
    transition: transform 0.18s ease;
    transform: ${({ $expanded }) => ($expanded ? 'rotate(0deg)' : 'rotate(-90deg)')};
`;

const ChevronIcon = ({ expanded }) => (
    <Chevron $expanded={expanded} viewBox="0 0 24 24" aria-hidden="true">
        <path
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M6 9l6 6 6-6"
        />
    </Chevron>
);

const Item = styled(Link)`
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.4rem 0.6rem;
    border-radius: 8px;
    color: ${({ theme, $active }) => ($active ? theme.colors.sidebarItemActiveText : theme.colors.sidebarItemText)};
    background: ${({ theme, $active }) => ($active ? theme.colors.sidebarItemActiveBg : 'transparent')};
    font-size: 0.72rem;
    font-weight: 500;
    text-decoration: none;
    line-height: 1.2;

    &:hover {
        background: ${({ theme, $active }) => ($active ? theme.colors.sidebarItemActiveBg : theme.colors.hoverBg)};
        color: ${({ theme, $active }) => ($active ? theme.colors.sidebarItemActiveText : theme.colors.sidebarItemText)};
        text-decoration: none;
    }
`;

const IconBox = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    flex-shrink: 0;
    color: inherit;

    svg { width: 18px; height: 18px; }
`;

const TopicLink = styled(Link)`
    display: block;
    padding: 0.25rem 0.6rem;
    border-radius: 6px;
    font-size: 0.68rem;
    color: ${({ theme }) => theme.colors.sidebarItemText};
    text-decoration: none;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
        text-decoration: none;
    }
`;

const UserLink = styled(Link)`
    display: block;
    padding: 0.25rem 0.6rem;
    border-radius: 6px;
    font-size: 0.68rem;
    color: ${({ theme }) => theme.colors.sidebarItemText};
    text-decoration: none;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
        text-decoration: none;
    }
`;

const EmptyRow = styled.div`
    padding: 0.25rem 0.6rem;
    font-size: 0.65rem;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const ToggleMore = styled.button`
    margin: 0.25rem 0 0 0.3rem;
    padding: 0.2rem 0.5rem;
    border: none;
    border-radius: 10px;
    background: transparent;
    color: ${({ theme }) => theme.colors.subtleText};
    font-family: inherit;
    font-size: 0.6rem;
    font-weight: 500;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
        color: ${({ theme }) => theme.colors.text};
    }
`;

// Outline + filled icon pairs. `filled` is used when the item is active.
const icons = {
    home: {
        outline: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V10.5Z" />
            </svg>
        ),
        filled: (
            <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V10.5Z" />
            </svg>
        ),
    },
    following: {
        outline: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 21s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.5-7 10-7 10Z" />
            </svg>
        ),
        filled: (
            <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 21s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.5-7 10-7 10Z" />
            </svg>
        ),
    },
    topics: {
        outline: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 6h16M4 12h16M4 18h10" />
            </svg>
        ),
        filled: (
            <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M3 5.5A1.5 1.5 0 0 1 4.5 4h15a1.5 1.5 0 0 1 0 3h-15A1.5 1.5 0 0 1 3 5.5Zm0 6A1.5 1.5 0 0 1 4.5 10h15a1.5 1.5 0 0 1 0 3h-15A1.5 1.5 0 0 1 3 11.5Zm0 6A1.5 1.5 0 0 1 4.5 16h9a1.5 1.5 0 0 1 0 3h-9A1.5 1.5 0 0 1 3 17.5Z" />
            </svg>
        ),
    },
    create: {
        outline: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 5v14M5 12h14" />
            </svg>
        ),
        filled: (
            <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2a1.5 1.5 0 0 1 1.5 1.5V10.5h7a1.5 1.5 0 0 1 0 3h-7v7a1.5 1.5 0 0 1-3 0v-7h-7a1.5 1.5 0 0 1 0-3h7V3.5A1.5 1.5 0 0 1 12 2Z" />
            </svg>
        ),
    },
    search: {
        outline: (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="7" />
                <path d="m21 21-4.3-4.3" />
            </svg>
        ),
        filled: (
            <svg viewBox="0 0 24 24" fill="currentColor">
                <path d="M10.5 3a7.5 7.5 0 1 1-4.74 13.32l-3.24 3.24a1.5 1.5 0 1 1-2.12-2.12l3.24-3.24A7.5 7.5 0 0 1 10.5 3Zm0 3a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9Z" />
            </svg>
        ),
    },
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
            <IconBox>{active ? icon.filled : icon.outline}</IconBox>
            {label}
        </Item>
    );
}

function Sidebar({ state }) {
    const location = useLocation();
    const pathname = location.pathname;
    const isLoggedIn = !!(state && state.publicKey);
    const viewerAddress = Storage.load('publicKey', '') || 'guest';

    const [topicsOpen, setTopicsOpen] = useState(true);
    const [usersOpen, setUsersOpen] = useState(true);
    const [showAllTopics, setShowAllTopics] = useState(false);
    const [showAllUsers, setShowAllUsers] = useState(false);

    const [topics, setTopics] = useState(() => loadSubscriptions(viewerAddress));
    const [people, setPeople] = useState(() => loadFollowedAuthors(viewerAddress));
    const [usernamesMap, setUsernamesMap] = useState({});

    const [topicsLimit, setTopicsLimit] = useState(() => {
        const v = Storage.load('sidebar_topics_limit', 10);
        return Number.isFinite(Number(v)) ? Number(v) : 10;
    });
    const [peopleLimit, setPeopleLimit] = useState(() => {
        const v = Storage.load('sidebar_people_limit', 10);
        return Number.isFinite(Number(v)) ? Number(v) : 10;
    });

    useEffect(() => {
        const handleSettingsUpdated = () => {
            const t = Storage.load('sidebar_topics_limit', 10);
            const p = Storage.load('sidebar_people_limit', 10);
            setTopicsLimit(Number.isFinite(Number(t)) ? Number(t) : 10);
            setPeopleLimit(Number.isFinite(Number(p)) ? Number(p) : 10);
        };
        window.addEventListener('sidebarSettingsUpdated', handleSettingsUpdated);
        return () => window.removeEventListener('sidebarSettingsUpdated', handleSettingsUpdated);
    }, []);

    useEffect(() => {
        let mounted = true;

        const loadFollows = async () => {
            if (!viewerAddress || viewerAddress === 'guest') {
                if (mounted) {
                    setTopics([]);
                    setPeople([]);
                }
                return;
            }
            try {
                const [followedTopics, followedUsers] = await Promise.all([
                    fetchFollowedTopics(viewerAddress),
                    fetchFollowedUsers(viewerAddress),
                ]);
                if (mounted) {
                    setTopics(followedTopics || []);
                    setPeople(followedUsers || []);
                }
            } catch (_) {
                // keep cached data on error
            }
        };

        const handleTopicsUpdated = (e) => {
            const detail = e?.detail || {};
            if (detail.added) {
                const t = String(detail.added).trim().toLowerCase();
                if (t && t !== 'all' && t !== 'home') {
                    setTopics(prev => prev.includes(t) ? prev : [...prev, t]);
                }
            } else if (detail.removed) {
                const t = String(detail.removed).trim().toLowerCase();
                setTopics(prev => prev.filter(x => x.toLowerCase() !== t));
            } else {
                loadFollows();
            }
        };
        const handleUsersUpdated = (e) => {
            const detail = e?.detail || {};
            if (detail.added) {
                const a = String(detail.added).trim().toLowerCase();
                if (a) {
                    setPeople(prev => prev.includes(a) ? prev : [...prev, a]);
                }
            } else if (detail.removed) {
                const a = String(detail.removed).trim().toLowerCase();
                setPeople(prev => prev.filter(x => x.toLowerCase() !== a));
            } else {
                loadFollows();
            }
        };

        loadFollows();
        window.addEventListener('followedTopicsUpdated', handleTopicsUpdated);
        window.addEventListener('followedUsersUpdated', handleUsersUpdated);

        return () => {
            mounted = false;
            window.removeEventListener('followedTopicsUpdated', handleTopicsUpdated);
            window.removeEventListener('followedUsersUpdated', handleUsersUpdated);
        };
    }, [viewerAddress]);

    useEffect(() => {
        if (!people || people.length === 0) return;
        let alive = true;
        (async () => {
            try {
                const mapping = await resolveUsernames(people, { timeoutMs: 8000 });
                if (alive) setUsernamesMap(mapping);
            } catch (_) {}
        })();
        return () => { alive = false; };
    }, [people]);

    const topicsToShow = showAllTopics ? topics : topics.slice(0, topicsLimit);
    const usersToShow = showAllUsers ? people : people.slice(0, peopleLimit);

    const renderUserLabel = (addr) => {
        if (!addr) return '';
        const lower = String(addr || '').toLowerCase();
        const uname = usernamesMap?.[lower];
        if (uname && typeof uname === 'string' && uname.trim().length > 0) {
            return `@${uname.trim()}`;
        }
        const trimmed = lower.replace(/^mirage1/, 'm1');
        return `@${trimmed.slice(0, 10)}…${trimmed.slice(-4)}`;
    };

    return (
        <Aside aria-label="Sidebar">
            <Section>
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
                    <SectionHeader
                        type="button"
                        onClick={() => setTopicsOpen(v => !v)}
                        aria-expanded={topicsOpen}
                    >
                        <span>Topics</span>
                        <ChevronIcon expanded={topicsOpen} />
                    </SectionHeader>
                    {topicsOpen && (
                        <div>
                            {topicsToShow.length === 0 ? (
                                <EmptyRow>None followed</EmptyRow>
                            ) : (
                                topicsToShow.map((topic) => (
                                    <TopicLink key={topic} to={`/t/${topic}`}>
                                        #{topic}
                                    </TopicLink>
                                ))
                            )}
                            {topics.length > topicsLimit && (
                                <ToggleMore type="button" onClick={() => setShowAllTopics(v => !v)}>
                                    {showAllTopics ? 'Show less' : `+${topics.length - topicsLimit} more`}
                                    <ChevronIcon expanded={showAllTopics} />
                                </ToggleMore>
                            )}
                        </div>
                    )}
                </Section>
            )}

            {isLoggedIn && (
                <Section>
                    <SectionHeader
                        type="button"
                        onClick={() => setUsersOpen(v => !v)}
                        aria-expanded={usersOpen}
                    >
                        <span>Users</span>
                        <ChevronIcon expanded={usersOpen} />
                    </SectionHeader>
                    {usersOpen && (
                        <div>
                            {usersToShow.length === 0 ? (
                                <EmptyRow>None followed</EmptyRow>
                            ) : (
                                usersToShow.map((addr) => {
                                    const lower = String(addr || '').toLowerCase();
                                    const uname = usernamesMap?.[lower];
                                    const identity = (uname && typeof uname === 'string' && uname.trim().length > 0) ? uname.trim() : addr;
                                    return (
                                        <UserLink
                                            key={addr}
                                            to={`/u/${encodeURIComponent(identity)}?tab=posts`}
                                        >
                                            {renderUserLabel(addr)}
                                        </UserLink>
                                    );
                                })
                            )}
                            {people.length > peopleLimit && (
                                <ToggleMore type="button" onClick={() => setShowAllUsers(v => !v)}>
                                    {showAllUsers ? 'Show less' : `+${people.length - peopleLimit} more`}
                                    <ChevronIcon expanded={showAllUsers} />
                                </ToggleMore>
                            )}
                        </div>
                    )}
                </Section>
            )}
        </Aside>
    );
}

export default Sidebar;
