import React, { useEffect, useState } from 'react';
import styled from 'styled-components';
import { Link, useLocation } from 'react-router-dom';
import Storage from '../../../utils/Storage';
import { fetchFollowedTopics, loadSubscriptions } from '../../../utils/Subscriptions';
import { fetchFollowedUsers, loadFollowedAuthors } from '../../../utils/FollowUsers';
import { resolveUsernames } from '../../../utils/UsernameCache';

const SidebarContainer = styled.div`
    width: 210px;
    background: ${({ theme }) => theme.colors.sidebarBg };
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    padding: 0.75rem;
    height: fit-content;
    margin: 1.75rem 0rem 0 -0.25rem;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);

    @media (max-width: 1000px) {
        display: none;
    }
`;

const LogoSection = styled.div`
    margin-bottom: 0.75rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const Logo = styled(Link)`
    font-size: 1rem;
    font-weight: 800;
    color: ${({ theme }) => theme.colors.text};
    margin: 0;
    cursor: pointer;
    letter-spacing: 0.05em;
    text-decoration: none;
    display: block;
    ${({ theme }) => theme.name !== 'light' && `
        animation: glowWander 8s ease-in-out infinite;
    `}

    @keyframes glowWander {
        0% {
            text-shadow: 
                0 0 12px rgba(255, 255, 255, 0.4),
                6px 2px 15px rgba(255, 255, 255, 0.25);
        }
        25% {
            text-shadow: 
                0 0 14px rgba(255, 255, 255, 0.35),
                -4px 4px 12px rgba(255, 255, 255, 0.2);
        }
        50% {
            text-shadow: 
                0 0 10px rgba(255, 255, 255, 0.45),
                -6px -2px 15px rgba(255, 255, 255, 0.25);
        }
        75% {
            text-shadow: 
                0 0 13px rgba(255, 255, 255, 0.38),
                4px -4px 12px rgba(255, 255, 255, 0.2);
        }
        100% {
            text-shadow: 
                0 0 12px rgba(255, 255, 255, 0.4),
                6px 2px 15px rgba(255, 255, 255, 0.25);
        }
    }

    &:hover {
        color: ${({ theme }) => theme.colors.text};
    }
`;

const NavSection = styled.div`
    margin-bottom: 1rem;
`;

const NavItem = styled(Link)`
    display: block;
    padding: 0.2rem 0.4rem;
    border-radius: 4px;
    text-decoration: none;
    color: ${({ theme }) => theme.colors.text};
    font-weight: 500;
    font-size: 0.75rem;
    transition: all 0.2s ease;
    margin-bottom: 0.04rem;

    &:hover {
        background: ${({ theme }) => theme.colors.accent};
        color: ${({ theme }) => theme.colors.link};
    }

    &.active {
        background: ${({ theme }) => theme.colors.accent};
        color: ${({ theme }) => theme.colors.link};
        font-weight: 600;
    }
`;

const Separator = styled.div`
    height: 1px;
    background: ${({ theme }) => theme.colors.border};
    margin: 0.5rem 0;
`;

const SectionTitle = styled.h3`
    font-size: 0.65rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.subtleText};
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 0.6rem 0 0.2rem 0;
    padding-left: 0.2rem;
`;

const TopicItem = styled(Link)`
    display: block;
    padding: 0.2rem 0.3rem 0.2rem 0.5rem;
    border-radius: 3px;
    text-decoration: none;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.7rem;
    transition: all 0.2s ease;
    margin-bottom: 0.02rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;

    &:hover {
        background: ${({ theme }) => theme.colors.accentHover};
        color: ${({ theme }) => theme.colors.linkHover};
    }
`;

const UserItem = styled(Link)`
    display: block;
    padding: 0.15rem 0.3rem 0.15rem 0.5rem;
    border-radius: 3px;
    text-decoration: none;
    color: ${({ theme }) => theme.colors.text};
    transition: all 0.2s ease;
    margin-bottom: 0.04rem;
    font-size: 0.7rem;
    overflow: hidden;

    &:hover {
        background: ${({ theme }) => theme.colors.accentHover};
        color: ${({ theme }) => theme.colors.linkHover};
    }
`;

const UserName = styled.div`
    font-size: 0.65rem;
    color: ${({ theme }) => theme.colors.subtleText};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const ToggleButton = styled.button`
    margin-top: 0.35rem;
    margin-left: 0.3rem;
    padding: 0.2rem 0.5rem;
    border: none;
    border-radius: 10px;
    background: ${({ theme }) => theme.colors.panelAlt};
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 500;
    line-height: 1;
    cursor: pointer;
    text-align: left;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    transition: all 0.2s ease;
    
    &:hover {
        background: ${({ theme }) => theme.colors.accent};
        color: ${({ theme }) => theme.colors.text};
    }
`;

const ChevronIcon = styled.span`
    display: inline-block;
    font-size: 0.5rem;
    transition: transform 0.2s ease;
    transform: ${({ $expanded }) => $expanded ? 'rotate(180deg)' : 'rotate(0deg)'};
`;

const EmptyState = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    padding: 0.1rem 0.3rem 0.1rem 0.5rem;
`;

const Sidebar = ({ currentPath, state }) => {
    const location = useLocation();
    const [showAllTopics, setShowAllTopics] = useState(false);
    const [showAllPeople, setShowAllPeople] = useState(false);
    const viewerAddress = Storage.load('publicKey', '') || 'guest';

    const handleFeedClick = (targetPath, e) => {
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
    // Initialize with cached data immediately to avoid flicker
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

    const isActive = (path) => currentPath === path;

    const topicsToShow = showAllTopics ? topics : topics.slice(0, topicsLimit);
    const peopleToShow = showAllPeople ? people : people.slice(0, peopleLimit);

    useEffect(() => {
        const handleSettingsUpdated = () => {
            const newTopicsLimit = Storage.load('sidebar_topics_limit', 10);
            const newPeopleLimit = Storage.load('sidebar_people_limit', 10);
            setTopicsLimit(Number.isFinite(Number(newTopicsLimit)) ? Number(newTopicsLimit) : 10);
            setPeopleLimit(Number.isFinite(Number(newPeopleLimit)) ? Number(newPeopleLimit) : 10);
        };
        window.addEventListener('sidebarSettingsUpdated', handleSettingsUpdated);
        return () => window.removeEventListener('sidebarSettingsUpdated', handleSettingsUpdated);
    }, []);

    useEffect(() => {
        let mounted = true;

        const loadFollows = async (force = false) => {
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
                    fetchFollowedUsers(viewerAddress)
                ]);
                if (mounted) {
                    setTopics(followedTopics || []);
                    setPeople(followedUsers || []);
                }
            } catch (_) {
                // Keep existing data on error
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
                loadFollows(true);
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
                loadFollows(true);
            }
        };

        // Always load on mount; ProfileCache prevents unnecessary network calls
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
        if (!people || people.length === 0) {
            return;
        }

        let alive = true;
        const doResolve = async () => {
            try {
                const mapping = await resolveUsernames(people, { timeoutMs: 8000 });
                if (alive) {
                    setUsernamesMap(mapping);
                }
            } catch (_) {
                // Keep existing cached data on error
            }
        };
        doResolve();
        return () => { alive = false; };
    }, [people]);

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
        <SidebarContainer>
            <LogoSection>
                <Logo to="/home">MIRAGE</Logo>
            </LogoSection>

            <NavSection>
                <NavItem
                    to="/home"
                    className={isActive('/home') || isActive('/') ? 'active' : ''}
                    onClick={(e) => handleFeedClick('/home', e)}
                >
                    Home
                </NavItem>
                <NavItem
                    to="/following"
                    className={isActive('/following') ? 'active' : ''}
                    onClick={(e) => handleFeedClick('/following', e)}
                >
                    Following
                </NavItem>
                <NavItem to="/topics" className={isActive('/topics') ? 'active' : ''}>
                    Topics
                </NavItem>
                <NavItem to="/agents" className={isActive('/agents') ? 'active' : ''}>
                    Agents
                </NavItem>
            </NavSection>

            <Separator />

            <SectionTitle>Topics</SectionTitle>

            <div>
                {topicsToShow.length === 0 ? (
                    <EmptyState>None followed</EmptyState>
                ) : (
                    topicsToShow.map((topic) => (
                        <TopicItem key={topic} to={`/t/${topic}`}>
                            #{topic}
                        </TopicItem>
                    ))
                )}
                {topics.length > topicsLimit && (
                    <ToggleButton onClick={() => setShowAllTopics((v) => !v)}>
                        {showAllTopics ? 'Show less' : `+${topics.length - topicsLimit} more`}
                        <ChevronIcon $expanded={showAllTopics}>▼</ChevronIcon>
                    </ToggleButton>
                )}
            </div>

            <SectionTitle style={{ marginTop: '1.15rem' }}>People</SectionTitle>

            <div>
                {peopleToShow.length === 0 ? (
                    <EmptyState>None followed</EmptyState>
                ) : (
                    peopleToShow.map((addr) => {
                        // Prefer username for clean URL, fallback to address
                        const lower = String(addr || '').toLowerCase();
                        const uname = usernamesMap?.[lower];
                        const identity = (uname && typeof uname === 'string' && uname.trim().length > 0) ? uname.trim() : addr;
                        return (
                            <UserItem
                                key={addr}
                                to={`/u/${encodeURIComponent(identity)}?tab=posts`}
                            >
                                <UserName>{renderUserLabel(addr)}</UserName>
                            </UserItem>
                        );
                    })
                )}
                {people.length > peopleLimit && (
                    <ToggleButton onClick={() => setShowAllPeople((v) => !v)}>
                        {showAllPeople ? 'Show less' : `+${people.length - peopleLimit} more`}
                        <ChevronIcon $expanded={showAllPeople}>▼</ChevronIcon>
                    </ToggleButton>
                )}
            </div>

        </SidebarContainer>
    );
};

export default Sidebar;
