import React, { useState, useEffect, useCallback } from 'react';
import styled from 'styled-components';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import Storage from '../../../utils/Storage';

/**
 * Mobile-only header for the mirageapp theme.
 *
 * Rendered by each theme route inside its main container (existing pattern
 * inherited from `oldreddit`). Hidden above 600px via CSS so desktop users
 * see only the `TopBar` from the shell.
 *
 * Inspired by `mirage-mobile-app/src/components/molecules/feed-header.tsx`:
 *   [menu] [brand]         [search] [inbox]
 */

const Bar = styled.header`
    display: none;

    @media (max-width: 600px) {
        position: sticky;
        top: 0;
        z-index: 90;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.45rem 0.75rem;
        background: ${({ theme }) => theme.colors.panel};
        border-bottom: 1px solid ${({ theme }) => theme.colors.headerBorder};
        margin: 0 calc(-1 * 0.75rem) 0.5rem;
    }
`;

const IconButton = styled.button`
    width: 36px;
    height: 36px;
    border: none;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    cursor: pointer;
    padding: 0;
    flex-shrink: 0;

    &:hover { background: ${({ theme }) => theme.colors.panelAlt}; }
`;

const IconLink = styled(Link)`
    width: 36px;
    height: 36px;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    text-decoration: none;
    flex-shrink: 0;
    position: relative;

    &:hover { background: ${({ theme }) => theme.colors.panelAlt}; }
`;

const BrandLink = styled(Link)`
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    font-weight: 800;
    font-size: 1.02rem;
    letter-spacing: 0.02em;
    min-width: 0;
`;

const BrandText = styled.span`
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const Spacer = styled.div`
    flex: 1 1 auto;
`;

const InboxBadge = styled.span`
    position: absolute;
    top: 4px;
    right: 4px;
    min-width: 14px;
    height: 14px;
    padding: 0 3px;
    background: #FF3B30;
    border-radius: 999px;
    border: 2px solid ${({ theme }) => theme.colors.panel};
    color: #fff;
    font-size: 0.5rem;
    font-weight: 700;
    line-height: 10px;
    text-align: center;
    box-sizing: border-box;
`;

const formatBadgeCount = (n) => (n > 99 ? '99+' : String(n));

function MobileHeader() {
    const location = useLocation();
    const navigate = useNavigate();
    const path = location.pathname;
    const isInbox = path === '/inbox';

    const publicKey = Storage.load('publicKey', '');
    const isLoggedIn = !!publicKey;

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

    const handleMenuClick = useCallback(() => {
        try {
            window.dispatchEvent(new CustomEvent('mirageToggleDrawer'));
        } catch (_) { /* noop */ }
    }, []);

    const handleSearchClick = useCallback(() => {
        navigate('/search');
    }, [navigate]);

    return (
        <Bar>
            <IconButton type="button" aria-label="Scroll to top" onClick={handleMenuClick}>
                <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                    <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
                </svg>
            </IconButton>

            <BrandLink to="/home" aria-label="Mirage home">
                <BrandText>Mirage</BrandText>
            </BrandLink>

            <Spacer />

            <IconButton type="button" aria-label="Search" onClick={handleSearchClick}>
                <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                    <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z" />
                </svg>
            </IconButton>

            {isLoggedIn && (
                <IconLink to="/inbox" aria-label={inboxCount > 0 ? `Inbox, ${inboxCount} unread` : 'Inbox'}>
                    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                        {isInbox
                            ? <path fill="currentColor" d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z" />
                            : <path fill="currentColor" d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V8l8 5 8-5v10zm-8-7L4 6h16l-8 5z" />
                        }
                    </svg>
                    {inboxCount > 0 && <InboxBadge aria-hidden="true">{formatBadgeCount(inboxCount)}</InboxBadge>}
                </IconLink>
            )}
        </Bar>
    );
}

export default MobileHeader;
