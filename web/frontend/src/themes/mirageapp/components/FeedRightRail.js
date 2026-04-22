import React from 'react';
import styled from 'styled-components';

/**
 * FeedRightRail — renders inline to the right of the feed column on
 * screens where the main Sidebar is visible (> 1000px). Below that
 * breakpoint the shell collapses to a single column and the mobile
 * bottom nav takes over, so the rail hides completely.
 *
 * Visual: borderless footer-style link cluster pinned to the bottom of
 * the feed row via sticky positioning. No heavy chrome — just two rows
 * of links in a lighter weight so the rail reads as quiet navigation.
 *
 * Static link set mirrors the marketing footer on `mirage.foundation`.
 * No network dependency — safe to render in loading / error states.
 */

const RailRoot = styled.aside`
    display: none;

    @media (min-width: 1001px) {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        width: 260px;
        flex: 0 0 260px;
        align-self: flex-end;
        position: sticky;
        bottom: 1rem;
        max-height: calc(100vh - 2.5rem - 1px - 2rem);
        overflow: auto;
        padding: 0.85rem 1rem;
        background: transparent;
        border: none;
        color: ${({ theme }) => theme.colors.subtleText};
        font-size: 0.66rem;
        line-height: 1.45;
        box-sizing: border-box;
        z-index: 5;
    }
`;

const LinksRow = styled.div`
    display: flex;
    flex-wrap: nowrap;
    gap: 0.75rem;
`;

const RailLink = styled.a`
    color: ${({ theme }) => theme.colors.subtleText};
    text-decoration: none;
    font-weight: 400;
    transition: color 0.15s ease;
    white-space: nowrap;

    &:hover,
    &:focus-visible {
        color: ${({ theme }) => theme.colors.text};
        text-decoration: underline;
    }
`;

const FOUNDATION_URL = 'https://mirage.foundation';

// Two balanced rows: row 1 = four short labels, row 2 = three labels
// (one of them longer). Keeps the visual rhythm even without wrap.
const ROW_ONE = [
    { label: 'About Mirage', href: `${FOUNDATION_URL}/#about` },
    { label: 'Docs', href: `${FOUNDATION_URL}/docs` },
    { label: 'FAQ', href: `${FOUNDATION_URL}/faq` },
];
const ROW_TWO = [
    { label: 'Blog', href: `${FOUNDATION_URL}/blog` },
    { label: 'Explorer', href: 'https://www.mirage.watch' },
    { label: 'X', href: 'https://x.com/mirage_found' },
];
const ROW_THREE = [
    { label: 'Download app', href: `${FOUNDATION_URL}/app` },
    { label: 'Exit is always free', href: `${FOUNDATION_URL}/#community` },
];

export default function FeedRightRail() {
    return (
        <RailRoot aria-label="Mirage links">
            <LinksRow>
                {ROW_ONE.map(({ label, href }) => (
                    <RailLink key={label} href={href} target="_blank" rel="noopener noreferrer">{label}</RailLink>
                ))}
            </LinksRow>
            <LinksRow>
                {ROW_TWO.map(({ label, href }) => (
                    <RailLink key={label} href={href} target="_blank" rel="noopener noreferrer">{label}</RailLink>
                ))}
            </LinksRow>
            <LinksRow>
                {ROW_THREE.map(({ label, href }) => (
                    <RailLink key={label} href={href} target="_blank" rel="noopener noreferrer">{label}</RailLink>
                ))}
            </LinksRow>
        </RailRoot>
    );
}
