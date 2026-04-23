import React, { useState, useCallback } from 'react';
import styled from 'styled-components';
import { HiLockClosed } from 'react-icons/hi2';
import seedVault from '../../../utils/SeedVault';

// ── Styled components ─────────────────────────────────────────────────────────

const Overlay = styled.div`
    position: fixed;
    inset: 0;
    z-index: 99999;
    display: flex;
    align-items: center;
    justify-content: center;
    background: ${({ theme }) => theme.colors.overlay};
    backdrop-filter: blur(8px);
`;

const Card = styled.div`
    width: 100%;
    max-width: 360px;
    padding: 1.5rem 1.25rem;
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    text-align: center;
    margin: 0 1rem;
    box-shadow: ${({ theme }) =>
        theme.name === 'light'
            ? '0 12px 28px rgba(15, 23, 42, 0.06)'
            : '0 16px 36px rgba(0, 0, 0, 0.32)'};
`;

const Title = styled.h2`
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    margin: 0 0 0.4rem 0;
    color: ${({ theme }) => theme.colors.text};
`;

const Subtitle = styled.p`
    font-size: 0.78rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
    margin: 0 0 1rem 0;
    line-height: 1.45;
`;

const Input = styled.input`
    display: block;
    width: 100%;
    padding: 0.55rem 0.75rem;
    font-size: 0.75rem;
    font-weight: 500;
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    color: ${({ theme }) => theme.colors.text};
    box-sizing: border-box;
    margin-bottom: 0.6rem;
    font-family: inherit;
    transition: border-color 0.15s ease;

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
    }

    &:hover:not(:disabled) {
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.borderStrong};
        box-shadow: none;
    }

    &:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }
`;

const UnlockButton = styled.button`
    display: block;
    width: 100%;
    padding: 0.55rem 0.75rem;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid ${({ theme }) => theme.colors.followBtnBg};
    border-radius: 8px;
    background: ${({ theme }) => theme.colors.followBtnBg};
    color: #ffffff;
    font-family: inherit;
    transition: background 0.15s ease, border-color 0.15s ease;

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.followBtnBgHover};
        border-color: ${({ theme }) => theme.colors.followBtnBgHover};
    }

    &:focus {
        outline: none;
    }

    &:focus-visible {
        outline: none;
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    &:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }
`;

const ErrorText = styled.div`
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.72rem;
    font-weight: 500;
    margin-top: 0.5rem;
`;

const LinkText = styled.button`
    display: inline-block;
    margin-top: 0.85rem;
    font-size: 0.7rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
    cursor: pointer;
    background: none;
    border: none;
    padding: 0;
    font-family: inherit;
    text-decoration: underline;

    &:hover {
        color: ${({ theme }) => theme.colors.text};
    }
`;

const LockIcon = styled.div`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2.4rem;
    height: 2.4rem;
    border-radius: 0.85rem;
    margin: 0 auto 0.6rem;
    background: ${({ theme }) => theme.colors.accent};
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.05rem;

    & > svg {
        width: 1.1rem;
        height: 1.1rem;
    }
`;

// ── Component ─────────────────────────────────────────────────────────────────

export default function UnlockPrompt({ mode, onUnlocked, onFallbackLogin }) {
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const handlePasswordUnlock = useCallback(async () => {
        if (!password.trim()) {
            setError('Please enter your password');
            return;
        }
        setLoading(true);
        setError('');
        try {
            await seedVault.unlock(password);
            onUnlocked();
        } catch (e) {
            setError(String(e?.message || 'Incorrect password'));
        } finally {
            setLoading(false);
        }
    }, [password, onUnlocked]);

    const handlePasskeyUnlock = useCallback(async () => {
        setLoading(true);
        setError('');
        try {
            await seedVault.unlock(null);
            onUnlocked();
        } catch (e) {
            setError(String(e?.message || 'Passkey authentication failed'));
        } finally {
            setLoading(false);
        }
    }, [onUnlocked]);

    const handleKeyDown = useCallback((e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            handlePasswordUnlock();
        }
    }, [handlePasswordUnlock]);

    // ── Password mode ─────────────────────────────────────────────────────────
    if (mode === 'password') {
        return (
            <Overlay>
                <Card>
                    <LockIcon aria-hidden="true"><HiLockClosed /></LockIcon>
                    <Title>Unlock Mirage</Title>
                    <Subtitle>Enter your password to decrypt your recovery phrase.</Subtitle>
                    <Input
                        type="password"
                        placeholder="Password"
                        value={password}
                        onChange={(e) => { setPassword(e.target.value); setError(''); }}
                        onKeyDown={handleKeyDown}
                        disabled={loading}
                        autoFocus
                    />
                    <UnlockButton onClick={handlePasswordUnlock} disabled={loading || !password.trim()}>
                        {loading ? 'Unlocking…' : 'Unlock'}
                    </UnlockButton>
                    {error && <ErrorText>{error}</ErrorText>}
                    <LinkText type="button" onClick={onFallbackLogin}>
                        Sign in with recovery phrase instead
                    </LinkText>
                </Card>
            </Overlay>
        );
    }

    // ── Passkey mode ─────────────────────────────────────────────────────────
    if (mode === 'passkey') {
        return (
            <Overlay>
                <Card>
                    <LockIcon aria-hidden="true"><HiLockClosed /></LockIcon>
                    <Title>Unlock Mirage</Title>
                    <Subtitle>Authenticate with your passkey to unlock.</Subtitle>
                    <UnlockButton onClick={handlePasskeyUnlock} disabled={loading}>
                        {loading ? 'Waiting for passkey…' : 'Tap to Unlock'}
                    </UnlockButton>
                    {error && <ErrorText>{error}</ErrorText>}
                    <LinkText type="button" onClick={onFallbackLogin}>
                        Sign in with recovery phrase instead
                    </LinkText>
                </Card>
            </Overlay>
        );
    }

    // Shouldn't reach here, but safety fallback
    return null;
}
