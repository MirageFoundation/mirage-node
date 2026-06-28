import React, { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import { Link, useLocation } from 'react-router-dom';
import useThemeSwitcher from '../logic/useThemeSwitcher';

/**
 * Theme + appearance switcher for logged-out visitors.
 *
 * Lives in shared `components/` (not per-theme) so every theme's TopBar gets
 * an identical, working guest control without duplicating the dropdown. It is
 * theme-agnostic: all colors come from the active theme's `theme.colors.*`
 * tokens via styled-components, so it adapts to whichever theme is active.
 */

const Wrapper = styled.div`
    position: relative;
    display: inline-flex;
    align-items: center;
`;

const TriggerButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2.2rem;
    height: 2.2rem;
    border-radius: 50%;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panel};
    color: ${({ theme }) => theme.colors.text};
    cursor: pointer;
    padding: 0;
    -webkit-appearance: none;
    appearance: none;
    transition: background-color 0.15s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.panelAlt};
    }
    &:focus-visible {
        outline: 2px solid ${({ theme }) => theme.colors.focusBorder || theme.colors.border};
        outline-offset: 2px;
    }

    svg {
        width: 1.15rem;
        height: 1.15rem;
    }
`;

const Dropdown = styled.div`
    position: absolute;
    right: 0;
    top: calc(100% + 0.5rem);
    background-color: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    padding: 0.4rem 0;
    min-width: 13rem;
    z-index: 10000;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
`;

const SectionLabel = styled.div`
    padding: 0.45rem 0.85rem 0.25rem;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const RowLink = styled(Link)`
    display: block;
    padding: 0.5rem 0.85rem;
    font-size: 0.85rem;
    font-weight: 500;
    white-space: nowrap;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    transition: background-color 0.15s;
    &:hover {
        background-color: ${({ theme }) => theme.colors.panelAlt};
    }
`;

const RowButton = styled.button`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    width: 100%;
    padding: 0.5rem 0.85rem;
    font-size: 0.85rem;
    font-weight: 500;
    text-align: left;
    white-space: nowrap;
    border: none;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    cursor: pointer;
    font-family: inherit;
    transition: background-color 0.15s;
    &:hover {
        background-color: ${({ theme }) => theme.colors.panelAlt};
    }
`;

const ActiveDot = styled.span`
    width: 0.45rem;
    height: 0.45rem;
    border-radius: 50%;
    background: ${({ theme }) => theme.colors.accent || theme.colors.text};
    flex-shrink: 0;
`;

const Divider = styled.div`
    height: 1px;
    background: ${({ theme }) => theme.colors.border};
    margin: 0.35rem 0;
`;

export default function GuestThemeMenu() {
    const location = useLocation();
    const [open, setOpen] = useState(false);
    const wrapRef = useRef(null);
    const { themeId, themeMode, themes, modes, pickTheme, pickMode } = useThemeSwitcher();

    useEffect(() => {
        const onDoc = (e) => {
            if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener('mousedown', onDoc, true);
        return () => document.removeEventListener('mousedown', onDoc, true);
    }, []);

    useEffect(() => { setOpen(false); }, [location.pathname]);

    return (
        <Wrapper ref={wrapRef}>
            <TriggerButton
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-haspopup="menu"
                aria-expanded={open}
                aria-label="Theme and appearance"
                title="Theme"
            >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="12" cy="12" r="9" />
                    <path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor" stroke="none" />
                </svg>
            </TriggerButton>
            {open && (
                <Dropdown role="menu">
                    <SectionLabel>Account</SectionLabel>
                    <RowLink to="/signup" onClick={() => setOpen(false)}>Sign up</RowLink>
                    <RowLink to="/login" onClick={() => setOpen(false)}>Log in</RowLink>
                    <Divider />
                    <SectionLabel>Theme</SectionLabel>
                    {themes.map((m) => {
                        const active = m.id === themeId;
                        return (
                            <RowButton
                                key={m.id}
                                type="button"
                                onClick={() => pickTheme(m.id)}
                                aria-pressed={active}
                            >
                                <span>{m.label || m.id}</span>
                                {active && <ActiveDot aria-hidden="true" />}
                            </RowButton>
                        );
                    })}
                    <Divider />
                    <SectionLabel>Appearance</SectionLabel>
                    {modes.map((m) => {
                        const active = m.value === themeMode;
                        return (
                            <RowButton
                                key={m.value}
                                type="button"
                                onClick={() => pickMode(m.value)}
                                aria-pressed={active}
                            >
                                <span>{m.label}</span>
                                {active && <ActiveDot aria-hidden="true" />}
                            </RowButton>
                        );
                    })}
                    <Divider />
                    <RowLink to="/faq" onClick={() => setOpen(false)}>FAQ</RowLink>
                </Dropdown>
            )}
        </Wrapper>
    );
}
