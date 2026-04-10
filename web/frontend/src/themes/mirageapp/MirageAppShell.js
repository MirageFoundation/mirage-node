import React, { useState, useCallback, useEffect } from 'react';
import styled from 'styled-components';
import TopBar from './components/TopBar';
import Sidebar from './components/Sidebar';
import MobileBottomNav from './components/MobileBottomNav';
import Storage from '../../utils/Storage';

/**
 * Root shell for the `mirageapp` theme.
 *
 *  Desktop (> 1000px):
 *      ┌──────────────────────────────────────────────────────────┐
 *      │ TopBar (sticky)                                          │
 *      ├──────────────┬─┬─────────────────────────────────────────┤
 *      │              │⎇│                                         │
 *      │   Sidebar    │ │   Main content column (children)        │
 *      │   (sticky)   │ │                                         │
 *      │              │ │                                         │
 *      └──────────────┴─┴─────────────────────────────────────────┘
 *
 *  A 1px vertical divider (same color as the TopBar divider) sits
 *  between Sidebar and Main, with a round menu toggle button pinned
 *  to the top of the divider. Clicking it collapses/expands the
 *  sidebar column.
 *
 *  Tablet (601–1000px): sidebar + divider hidden.
 *  Mobile (≤ 600px): MobileHeader + MobileBottomNav take over.
 */

const SIDEBAR_HIDDEN_KEY = 'mirageapp_sidebar_hidden';

const ShellRoot = styled.div`
    min-height: 100vh;
    background: ${({ theme }) => theme.colors.bg};
    color: ${({ theme }) => theme.colors.text};
`;

const Layout = styled.div`
    display: grid;
    /* DividerCol is a 17px track = 1px border on its left edge + 16px of
       breathing room to the right of the divider before the Main column. */
    grid-template-columns: ${({ $hidden }) => ($hidden ? '0 17px minmax(0, 1fr)' : '240px 17px minmax(0, 1fr)')};
    max-width: 1400px;
    margin: 0 auto;
    gap: 0;
    transition: grid-template-columns 0.18s ease;

    @media (max-width: 1000px) {
        grid-template-columns: minmax(0, 1fr);
        max-width: none;
    }
`;

const SidebarCol = styled.div`
    min-width: 0;
    overflow: ${({ $hidden }) => ($hidden ? 'hidden' : 'visible')};
    visibility: ${({ $hidden }) => ($hidden ? 'hidden' : 'visible')};

    @media (max-width: 1000px) {
        display: none;
    }
`;

const DividerCol = styled.div`
    position: relative;
    /* 1px divider line sits on the LEFT edge of the column; the rest
       (16px) is empty space between the divider and the Main column. */
    border-left: 1px solid ${({ theme }) => theme.colors.headerBorder};
    overflow: visible;

    @media (max-width: 1000px) {
        display: none;
    }
`;

const ToggleButton = styled.button`
    position: absolute;
    /* Pin to the top of the sidebar column, roughly aligned with the
       first nav row ("Home"). */
    top: 14px;
    /* Center the button on the 1px divider line (at the column's left edge). */
    left: 0;
    transform: translateX(-50%);
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border-radius: 9999px;
    border: 1px solid ${({ theme }) => theme.colors.menuBtnBorder};
    background: ${({ theme }) => theme.colors.bg};
    color: ${({ theme }) => theme.colors.menuBtnIcon};
    cursor: pointer;
    z-index: 50;
    transition: border-color 0.15s ease;
    outline: none;
    -webkit-tap-highlight-color: transparent;

    & svg {
        width: 20px;
        height: 20px;
        display: block;
    }

    &:hover,
    &:active {
        border-color: ${({ theme }) => theme.colors.menuBtnBorderHover};
        background: ${({ theme }) => theme.colors.bg};
        color: ${({ theme }) => theme.colors.menuBtnIcon};
    }

    &:focus,
    &:focus-visible {
        outline: none;
        box-shadow: none;
    }
`;

const Main = styled.main`
    min-width: 0;
    padding: 1rem 1rem 3rem;
    background: transparent;

    @media (max-width: 1000px) {
        padding: 0.75rem 0.75rem 3rem;
    }

    @media (max-width: 600px) {
        padding: 0 0.75rem 80px;
    }
`;

export default function MirageAppShell({ children, state }) {
    const [hidden, setHidden] = useState(() => {
        try {
            return Storage.load(SIDEBAR_HIDDEN_KEY, false) === true;
        } catch (_) {
            return false;
        }
    });

    useEffect(() => {
        try { Storage.save(SIDEBAR_HIDDEN_KEY, hidden); } catch (_) {}
    }, [hidden]);

    const toggleSidebar = useCallback(() => {
        setHidden(v => !v);
    }, []);

    return (
        <ShellRoot>
            <TopBar state={state} />
            <Layout $hidden={hidden}>
                <SidebarCol $hidden={hidden} aria-hidden={hidden}>
                    <Sidebar state={state} />
                </SidebarCol>
                <DividerCol>
                    <ToggleButton
                        type="button"
                        onClick={toggleSidebar}
                        aria-label={hidden ? 'Show sidebar' : 'Hide sidebar'}
                        aria-pressed={!hidden}
                        title={hidden ? 'Show sidebar' : 'Hide sidebar'}
                    >
                        <svg viewBox="0 0 24 24" aria-hidden="true">
                            <path
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2"
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                d="M4 6h16M4 12h16M4 18h16"
                            />
                        </svg>
                    </ToggleButton>
                </DividerCol>
                <Main>{children}</Main>
            </Layout>
            <MobileBottomNav state={state} />
        </ShellRoot>
    );
}
