import React, { useState, useCallback, useEffect } from 'react';
import styled from 'styled-components';
import { useLocation } from 'react-router-dom';
import { HiBars3 } from 'react-icons/hi2';
import TopBar from './components/TopBar';
import Sidebar from './components/Sidebar';
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
    overflow: visible;
    transition: grid-template-columns 0.18s ease;
    /* Always fill at least the viewport height below the TopBar so the
       vertical divider (and the sidebar column) never get visually cut
       off on short routes like Create Post, Search, or loading states. */
    min-height: calc(100vh - 2.5rem - 1px);

    @media (max-width: 1000px) {
        grid-template-columns: minmax(0, 1fr);
        max-width: none;
        min-height: 0;
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
    /* Sticky (not absolute) so the button stays pinned next to the */
    /* TopBar even when the main feed scrolls. The top value equals */
    /* TopBar height + 14px inset (matches the first sidebar nav row). */
    position: sticky;
    top: calc(2.5rem + 1px + 14px);
    /* Center the 32px button on the 1px divider line at the column's */
    /* left edge: shift it left by half its width. */
    margin-left: -16px;
    /* 14px top inset from the top of DividerCol, which itself starts */
    /* right below the TopBar. */
    margin-top: 14px;
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

const Main = styled.main.attrs(({ $hidden }) => ({
    'data-sidebar-hidden': $hidden ? 'true' : 'false',
}))`
    min-width: 0;
    /* Top padding kept tight so the first feed row / toolbar control aligns
       vertically with the first sidebar menu item. Right padding widens to
       ~30px when the sidebar is hidden so the feed doesn't run to the
       viewport edge. */
    padding: ${({ $hidden }) => ($hidden ? '0.5rem 30px 3rem 1rem' : '0.5rem 1rem 3rem')};
    background: transparent;

    @media (max-width: 1000px) {
        padding: 0.5rem 0.75rem 3rem;
    }

    @media (max-width: 600px) {
        padding: 0 0.75rem 1.5rem;
    }
`;

const DrawerOverlay = styled.div`
    display: none;

    @media (max-width: 1000px) {
        display: block;
        position: fixed;
        inset: 0;
        z-index: 200;
        background: rgba(0, 0, 0, 0.5);
        opacity: ${({ $open }) => ($open ? 1 : 0)};
        pointer-events: ${({ $open }) => ($open ? 'auto' : 'none')};
        transition: opacity 0.2s ease;
    }
`;

const DrawerPanel = styled.div`
    display: none;

    @media (max-width: 1000px) {
        display: block;
        position: fixed;
        top: 0;
        left: 0;
        bottom: 0;
        width: 260px;
        z-index: 201;
        background: ${({ theme }) => theme.colors.bg};
        border-right: 1px solid ${({ theme }) => theme.colors.headerBorder};
        transform: translateX(${({ $open }) => ($open ? '0' : '-100%')});
        transition: transform 0.2s ease;
        overflow-y: auto;
        -webkit-overflow-scrolling: touch;

        & > aside {
            display: block !important;
            position: static;
            width: 100%;
            max-height: none;
        }
    }
`;

export default function MirageAppShell({ children, state }) {
    const location = useLocation();
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

    const [drawerOpen, setDrawerOpen] = useState(false);

    useEffect(() => {
        setDrawerOpen(false);
    }, [location.pathname]);

    useEffect(() => {
        const onToggle = () => setDrawerOpen(v => !v);
        window.addEventListener('mirageToggleDrawer', onToggle);
        return () => window.removeEventListener('mirageToggleDrawer', onToggle);
    }, []);

    const toggleSidebar = useCallback(() => {
        setHidden(v => !v);
    }, []);

    const toggleDrawer = useCallback(() => {
        setDrawerOpen(v => !v);
    }, []);

    return (
        <ShellRoot>
            <TopBar state={state} onToggleSidebar={toggleSidebar} onToggleDrawer={toggleDrawer} sidebarHidden={hidden} />
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
                        <HiBars3 aria-hidden="true" />
                    </ToggleButton>
                </DividerCol>
                <Main $hidden={hidden}>{children}</Main>
            </Layout>
            <DrawerOverlay $open={drawerOpen} onClick={() => setDrawerOpen(false)} />
            <DrawerPanel $open={drawerOpen}>
                <Sidebar state={state} />
            </DrawerPanel>
        </ShellRoot>
    );
}
