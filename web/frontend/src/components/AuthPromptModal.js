import React, { useEffect, useState, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import styled from 'styled-components';
import { AUTH_REQUIRED_EVENT } from '../utils/openBrowsing';
import { getCachedWelcomeStats } from '../utils/welcomeStatsCache';
import { returnToFromLocation, withReturnTo } from '../utils/returnTo';
import LoggedOutPromptCard from '../themes/default/components/LoggedOutPromptCard.js';

/**
 * Global signup prompt for open-browsing nodes. Logged-out write/social actions
 * call requireAccount(), which dispatches AUTH_REQUIRED_EVENT; this modal listens
 * and shows the exact same content as the full-page logged-out card (tagline,
 * live network stats, signup/sign-in, and links) so the messaging stays in sync
 * and themes correctly in both light and dark.
 */

const WELCOME_TAGLINE =
    'Communities, posts, and voting without power mods, shadow bans, or corporate gatekeepers. ' +
    'Your identity is portable, moderation is voluntary, and no node can erase you from the network.';

const WELCOME_LINKS = [
    { label: 'Watch Introduction (YouTube)', href: 'https://www.youtube.com/watch?v=TOvP32ihQ0M', external: true },
    { label: 'Learn More', href: 'https://mirage.foundation', external: true },
    { label: 'FAQ', href: '/faq' },
];

const Overlay = styled.div`
    position: fixed;
    inset: 0;
    z-index: 4000;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
    background: rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(2px);
`;

const Dialog = styled.div`
    position: relative;
    width: 100%;
    max-width: 25rem;
    box-sizing: border-box;
    border-radius: 14px;
    padding: 1.75rem 1.4rem 1.4rem;
    background: ${({ theme }) => theme.colors.cardBg || theme.colors.bg};
    color: ${({ theme }) => theme.colors.text};
    border: 1px solid ${({ theme }) => theme.colors.border};
    box-shadow: 0 16px 48px rgba(0, 0, 0, 0.4);
`;

const CloseX = styled.button`
    position: absolute;
    top: 0.55rem;
    right: 0.65rem;
    width: 1.9rem;
    height: 1.9rem;
    display: flex;
    align-items: center;
    justify-content: center;
    border: none;
    border-radius: 50%;
    background: transparent;
    color: ${({ theme }) => theme.colors.subtleText || theme.colors.text};
    opacity: 0.7;
    font-size: 1.25rem;
    line-height: 1;
    cursor: pointer;
    transition: background 0.12s ease, opacity 0.12s ease;

    &:hover {
        opacity: 1;
        background: ${({ theme }) => theme.colors.panelAlt || 'rgba(127,127,127,0.15)'};
    }
`;

// LoggedOutPromptCard is built for the feed column (absolute, viewport-spanning
// Shell + a margin-left nudge to line up with the search bar). Neutralize that
// layout so the very same card content drops cleanly into the centered modal.
const ModalPrompt = styled(LoggedOutPromptCard)`
    && {
        position: static;
        top: auto;
        left: auto;
        width: 100%;
        max-width: 100%;
        padding: 0;
        pointer-events: auto;
    }
    /* inner Card */
    && > div {
        margin-left: 0;
        max-width: 100%;
        background: transparent;
    }
`;

export default function AuthPromptModal() {
    const location = useLocation();
    const [open, setOpen] = useState(false);
    const [action, setAction] = useState('');

    useEffect(() => {
        const handler = e => {
            setAction((e && e.detail && e.detail.action) || '');
            setOpen(true);
        };
        window.addEventListener(AUTH_REQUIRED_EVENT, handler);
        return () => window.removeEventListener(AUTH_REQUIRED_EVENT, handler);
    }, []);

    // Close on Escape for accessibility.
    useEffect(() => {
        if (!open) return undefined;
        const onKey = e => { if (e.key === 'Escape') setOpen(false); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [open]);

    // The card's Create-account / Sign-in buttons navigate via router links, so
    // close the modal whenever the route changes.
    useEffect(() => { setOpen(false); }, [location.pathname]);

    const close = useCallback(() => setOpen(false), []);

    if (!open) return null;

    return (
        <Overlay onClick={close} role="dialog" aria-modal="true">
            <Dialog onClick={e => e.stopPropagation()}>
                <CloseX onClick={close} aria-label="Close">×</CloseX>
                <ModalPrompt
                    title={action ? `Create an account to ${action}` : 'Join Mirage'}
                    description={WELCOME_TAGLINE}
                    stats={getCachedWelcomeStats()}
                    links={WELCOME_LINKS}
                    primaryLabel="Create account"
                    primaryTo={withReturnTo('/signup', returnToFromLocation(location))}
                    secondaryLabel="Sign in"
                    secondaryTo={withReturnTo('/login', returnToFromLocation(location))}
                />
            </Dialog>
        </Overlay>
    );
}
