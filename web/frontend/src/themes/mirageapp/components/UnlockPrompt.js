import React, { useState, useCallback } from 'react';
import styled from 'styled-components';
import seedVault from '../../../utils/SeedVault';

// ── Styled components ─────────────────────────────────────────────────────────

const Overlay = styled.div`
    position: fixed;
    inset: 0;
    z-index: 99999;
    display: flex;
    align-items: center;
    justify-content: center;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(255, 255, 255, 0.92)'
        : 'rgba(20, 20, 20, 0.95)'};
    backdrop-filter: blur(8px);
`;

const Card = styled.div`
    width: 100%;
    max-width: 380px;
    padding: 2rem 1.5rem;
    background-color: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    text-align: center;
    margin: 0 1rem;
`;

const Title = styled.h2`
    font-size: 1.25rem;
    font-weight: 600;
    margin: 0 0 0.5rem 0;
    color: ${({ theme }) => theme.colors.text};
`;

const Subtitle = styled.p`
    font-size: 0.8rem;
    color: ${({ theme }) => theme.colors.subtleText};
    margin: 0 0 1.25rem 0;
    line-height: 1.4;
`;

const Input = styled.input`
    display: block;
    width: 100%;
    padding: 0.65rem 0.85rem;
    font-size: 0.85rem;
    background-color: ${({ theme }) => theme.colors.panelAlt};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    color: ${({ theme }) => theme.colors.text};
    box-sizing: border-box;
    margin-bottom: 0.75rem;

    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.borderStrong};
        box-shadow: none;
    }
`;

const UnlockButton = styled.button`
    display: block;
    width: 100%;
    padding: 0.65rem;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    border: none;
    border-radius: 8px;
    background: #3b82f6;
    color: #fff;
    transition: background 0.15s ease;

    &:hover:not(:disabled) {
        background: #2563eb;
    }

    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
`;

const ErrorText = styled.div`
    color: #f66;
    font-size: 0.75rem;
    margin-top: 0.5rem;
`;

const LinkText = styled.span`
    display: inline-block;
    margin-top: 1rem;
    font-size: 0.7rem;
    color: ${({ theme }) => theme.colors.subtleText};
    cursor: pointer;
    text-decoration: underline;

    &:hover {
        color: ${({ theme }) => theme.colors.text};
    }
`;

const LockIcon = styled.div`
    font-size: 2rem;
    margin-bottom: 0.75rem;
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
                    <LockIcon>&#128274;</LockIcon>
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
                        {loading ? 'Unlocking...' : 'Unlock'}
                    </UnlockButton>
                    {error && <ErrorText>{error}</ErrorText>}
                    <LinkText onClick={onFallbackLogin}>
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
                    <LockIcon>&#128274;</LockIcon>
                    <Title>Unlock Mirage</Title>
                    <Subtitle>Authenticate with your passkey to unlock.</Subtitle>
                    <UnlockButton onClick={handlePasskeyUnlock} disabled={loading}>
                        {loading ? 'Waiting for passkey...' : 'Tap to Unlock'}
                    </UnlockButton>
                    {error && <ErrorText>{error}</ErrorText>}
                    <LinkText onClick={onFallbackLogin}>
                        Sign in with recovery phrase instead
                    </LinkText>
                </Card>
            </Overlay>
        );
    }

    // Shouldn't reach here, but safety fallback
    return null;
}
