import React, { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import styled, { useTheme } from 'styled-components';
import { AUTH_REQUIRED_EVENT } from '../utils/openBrowsing';

/**
 * Global signup prompt for open-browsing nodes. A single theme-neutral modal
 * (reads a few theme tokens with safe fallbacks) mounted once in the Shell.
 * Logged-out write/social actions call requireAccount(), which dispatches
 * AUTH_REQUIRED_EVENT; this modal listens and prompts the visitor to sign up.
 */

const tok = (theme, key, fallback) => (theme && theme.colors && theme.colors[key]) || fallback;

const Overlay = styled.div`
    position: fixed;
    inset: 0;
    z-index: 4000;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
    background: rgba(0, 0, 0, 0.55);
`;

const Card = styled.div`
    position: relative;
    width: 100%;
    max-width: 360px;
    border-radius: 12px;
    padding: 1.5rem 1.4rem 1.3rem;
    background: ${({ theme }) => tok(theme, 'cardBg', tok(theme, 'bg', '#16181c'))};
    color: ${({ theme }) => tok(theme, 'text', '#e6e6e6')};
    border: 1px solid ${({ theme }) => tok(theme, 'border', '#2b2f36')};
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
`;

const Title = styled.div`
    font-size: 1.05rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
    padding-right: 1.5rem;
`;

const Desc = styled.div`
    font-size: 0.85rem;
    line-height: 1.4;
    opacity: 0.75;
    margin-bottom: 1.1rem;
`;

const Row = styled.div`
    display: flex;
    gap: 0.6rem;
`;

const Primary = styled.button`
    flex: 1;
    border: none;
    border-radius: 8px;
    padding: 0.6rem 0.8rem;
    font-size: 0.85rem;
    font-weight: 700;
    cursor: pointer;
    color: #fff;
    background: ${({ theme }) => tok(theme, 'accent', tok(theme, 'voteUp', '#3b82f6'))};
`;

const Secondary = styled.button`
    flex: 1;
    border: 1px solid ${({ theme }) => tok(theme, 'border', '#2b2f36')};
    border-radius: 8px;
    padding: 0.6rem 0.8rem;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    background: transparent;
    color: ${({ theme }) => tok(theme, 'text', '#e6e6e6')};
`;

const CloseX = styled.button`
    position: absolute;
    top: 0.6rem;
    right: 0.7rem;
    border: none;
    background: transparent;
    color: ${({ theme }) => tok(theme, 'text', '#e6e6e6')};
    opacity: 0.5;
    font-size: 1.2rem;
    line-height: 1;
    cursor: pointer;
`;

export default function AuthPromptModal() {
    const theme = useTheme();
    const navigate = useNavigate();
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

    const close = useCallback(() => setOpen(false), []);
    const go = useCallback(to => { setOpen(false); navigate(to); }, [navigate]);

    if (!open) return null;

    return (
        <Overlay onClick={close} role="dialog" aria-modal="true">
            <Card onClick={e => e.stopPropagation()} theme={theme}>
                <CloseX onClick={close} aria-label="Close">×</CloseX>
                <Title>Create an account{action ? ` to ${action}` : ''}</Title>
                <Desc>
                    Browsing Mirage is open to everyone. To vote, comment, post, or follow,
                    you'll need a free Mirage account.
                </Desc>
                <Row>
                    <Primary onClick={() => go('/signup')}>Create account</Primary>
                    <Secondary onClick={() => go('/login')}>Sign in</Secondary>
                </Row>
            </Card>
        </Overlay>
    );
}
