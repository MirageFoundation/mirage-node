import React from 'react';
import styled from 'styled-components';
import TopBar from './components/TopBar';
import Sidebar from './components/Sidebar';
import MobileBottomNav from './components/MobileBottomNav';

/**
 * Root shell for the `mirageapp` theme.
 *
 *  Desktop (> 1000px):
 *      ┌──────────────────────────────────────────────────────────┐
 *      │ TopBar (sticky)                                          │
 *      ├──────────────┬───────────────────────────────────────────┤
 *      │              │                                           │
 *      │   Sidebar    │   Main content column (children)          │
 *      │   (sticky)   │                                           │
 *      │              │                                           │
 *      └──────────────┴───────────────────────────────────────────┘
 *
 *  Tablet (601–1000px):
 *      TopBar + Main content column (sidebar hidden)
 *
 *  Mobile (≤ 600px):
 *      MobileHeader (rendered by each route) + Main content +
 *      MobileBottomNav (fixed)
 *
 *  MobileBottomNav remains rendered at the shell level because routes do
 *  not control it. TopBar is hidden below 600px via CSS inside `TopBar.js`,
 *  and Sidebar is hidden below 1000px via CSS inside `Sidebar.js`.
 */

const ShellRoot = styled.div`
    min-height: 100vh;
    background: ${({ theme }) => theme.colors.bg};
    color: ${({ theme }) => theme.colors.text};
`;

const Layout = styled.div`
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr);
    max-width: 1400px;
    margin: 0 auto;
    gap: 0;

    @media (max-width: 1000px) {
        grid-template-columns: minmax(0, 1fr);
        max-width: none;
    }
`;

const Main = styled.main`
    min-width: 0;
    padding: 1.25rem 1.25rem 3rem;
    background: transparent;

    @media (max-width: 1000px) {
        padding: 0.75rem 0.75rem 3rem;
    }

    @media (max-width: 600px) {
        padding: 0 0.75rem 80px;
    }
`;

export default function MirageAppShell({ children, state }) {
    return (
        <ShellRoot>
            <TopBar state={state} />
            <Layout>
                <Sidebar state={state} />
                <Main>{children}</Main>
            </Layout>
            <MobileBottomNav state={state} />
        </ShellRoot>
    );
}
