import React, { useState, useRef, useEffect, useCallback } from 'react';
import styled from 'styled-components';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import Storage from '../../../utils/Storage';

/**
 * Reddit-style TopBar for the mirageapp theme.
 * Sticky top, full width. Hidden on mobile (MobileHeader takes over at ≤600px).
 *
 * Structure (left → right):
 *   [brand] ─── flex ───  [search (centered)]  ─── flex ───  [create] [inbox] [avatar]
 *
 * Notes:
 *   - Home / Following / Topics nav lives in the sidebar only.
 *   - Avatar uses the mobile app's DiceBear identicon (seeded by username/address),
 *     matching `mirage-mobile-app/src/components/atoms/avatar.tsx`.
 *   - Search input uses the main Mirage gradient border via tokens.gradient.
 *   - Create button is ghost-styled (no background, no border).
 */

const Bar = styled.header`
    position: sticky;
    top: 0;
    z-index: 100;
    /* Match the mobile app's main background color (mirage-mobile-app surfaces.background) */
    background: ${({ theme }) => theme.colors.bg};
    border-bottom: 1px solid ${({ theme }) => theme.colors.headerBorder};
    backdrop-filter: saturate(1.1);

    @media (max-width: 600px) {
        display: none;
    }
`;

/**
 * Inner flex row constrained to the same max-width as the shell's Layout
 * (`MirageAppShell`) so the brand "Mirage" text lines up horizontally with
 * the sidebar column's left edge on wide viewports.
 */
const BarInner = styled.div`
    display: flex;
    align-items: center;
    gap: 1rem;
    max-width: 1400px;
    margin: 0 auto;
    padding: 0.3rem 0.5rem;
    box-sizing: border-box;
`;

const BrandLink = styled(Link)`
    display: inline-flex;
    align-items: center;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    font-weight: 800;
    font-size: 1.15rem;
    letter-spacing: 0.02em;
    flex-shrink: 0;

    &:hover { text-decoration: none; }
`;

const LeftSpacer = styled.div`
    flex: 1 1 0;
    min-width: 0;
`;

const RightSpacer = styled.div`
    flex: 1 1 0;
    min-width: 0;
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.5rem;
`;

/**
 * Centered search input.
 *
 * The wrapper paints the border color, the inner element has a solid panel
 * background clipped inside it — together they create a constant-width 1px
 * ring. Default: main Mirage gradient. Focused: solid mobile-app blue
 * (#4285f4 via `focusBlue` token). Border width stays the same on focus —
 * only the color changes.
 */
const SearchInner = styled.div`
    position: relative;
    border-radius: 9999px;
    /* Match TopBar background so the input reads as a cut-out of the header */
    background: ${({ theme }) => theme.colors.bg};
    overflow: hidden;
    transition: background 0.15s ease;
`;

const SearchWrapper = styled.form`
    position: relative;
    flex: 0 1 520px;
    min-width: 240px;
    max-width: 560px;
    padding: 1px; /* constant border ring thickness */
    border-radius: 9999px;
    background: ${({ theme }) => theme.colors.gradient};
    transition: background 0.15s ease;

    /* Hover: only the inner fill tints; border stays gradient. */
    &:hover ${SearchInner} {
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    &:focus-within {
        background: ${({ theme }) => theme.colors.focusBlue};
    }

    /* When focused, the inner returns to the header background so the
       blue ring reads cleanly and the hover tint doesn't linger. */
    &:focus-within ${SearchInner} {
        background: ${({ theme }) => theme.colors.bg};
    }

    @media (max-width: 1100px) {
        flex: 0 1 420px;
    }
    @media (max-width: 800px) {
        display: none;
    }
`;

const SearchInput = styled.input`
    width: 100%;
    box-sizing: border-box;
    /* Vertical padding: 0.4rem + 1px on each side = +2px total input height.
       Right padding reserves room for the custom clear button (30px + offset). */
    padding: calc(0.4rem + 1px) 2.4rem calc(0.4rem + 1px) 2.25rem;
    border-radius: 9999px;
    border: none;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.76rem;
    line-height: 1.2;
    outline: none;

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
        font-size: 0.76rem;
    }

    /* Hide the browser's native type="search" clear button — we render our own. */
    &::-webkit-search-cancel-button,
    &::-webkit-search-decoration,
    &::-webkit-search-results-button,
    &::-webkit-search-results-decoration {
        -webkit-appearance: none;
        appearance: none;
        display: none;
    }
`;

const SearchIcon = styled.svg`
    position: absolute;
    left: 0.85rem;
    top: 50%;
    transform: translateY(-50%);
    width: 16px;
    height: 16px;
    color: ${({ theme }) => theme.colors.subtleText};
    pointer-events: none;
`;

const ClearButton = styled.button`
    position: absolute;
    right: 0.35rem;
    top: 50%;
    transform: translate(0, -50%);
    width: 30px;
    height: 30px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    /* Padding gives the hover background room to breathe around the icon.
       Inner icon ends up ~20px (30px box - 5px padding on each side). */
    padding: 5px;
    border: none;
    border-radius: 9999px;
    background: transparent;
    color: ${({ theme }) => theme.colors.inputIconColor};
    cursor: pointer;
    outline: none;
    transition: background 0.15s ease, color 0.15s ease;

    & > svg {
        width: 100%;
        height: 100%;
        display: block;
    }

    &:hover {
        background: ${({ theme }) => theme.colors.inputIconHoverBg};
        color: ${({ theme }) => theme.colors.text};
    }

    &:focus,
    &:focus-visible,
    &:active {
        outline: none;
        box-shadow: none;
    }
`;

const IconButton = styled(Link)`
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border-radius: 999px;
    color: ${({ theme }) => theme.colors.text};
    background: ${({ theme, $active }) => ($active ? theme.colors.panelAlt : 'transparent')};
    text-decoration: none;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }
`;

const CreateButton = styled(Link)`
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.45rem 0.7rem;
    border-radius: 999px;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    border: none;
    font-weight: 400;
    font-size: 0.78rem;
    text-decoration: none;

    &:hover {
        color: ${({ theme }) => theme.colors.text};
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    @media (max-width: 1000px) {
        padding: 0.45rem 0.55rem;
        .create-label { display: none; }
    }
`;

const InboxBadge = styled.span`
    position: absolute;
    top: 2px;
    right: 2px;
    min-width: 16px;
    height: 16px;
    padding: 0 4px;
    background: #FF3B30;
    border-radius: 999px;
    border: 2px solid ${({ theme }) => theme.colors.panel};
    color: #fff;
    font-size: 0.55rem;
    font-weight: 700;
    line-height: 12px;
    text-align: center;
    box-sizing: border-box;
`;

const UserMenuWrapper = styled.div`
    position: relative;
    display: inline-flex;
    align-items: center;
`;

/**
 * Avatar trigger: a relatively-positioned wrapper that holds two stacked copies
 * of the same DiceBear identicon.
 *
 *  - `AvatarGlow`  : larger (48px), absolutely positioned, heavily blurred,
 *                    opacity 0 by default, fades in on hover. This acts as a
 *                    soft colored halo/border around the visible avatar.
 *  - `AvatarImg`   : the normal 32px avatar, sits on top via `position: relative`.
 *
 * The button itself has no border, no background, and no focus outline in any
 * state — the blurred halo is the only hover affordance, and the `$open`
 * dropdown below handles the "menu active" affordance.
 */
const UserMenuTrigger = styled.button`
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border-radius: 9999px;
    border: none;
    background: transparent;
    cursor: pointer;
    overflow: visible;
    outline: none;
    -webkit-tap-highlight-color: transparent;

    &:focus,
    &:focus-visible,
    &:active {
        outline: none;
        box-shadow: none;
    }
`;

const AvatarGlow = styled.img`
    position: absolute;
    top: 50%;
    left: 50%;
    width: 48px;
    height: 48px;
    border-radius: 9999px;
    transform: translate(-50%, -50%) scale(0.95);
    filter: blur(10px);
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.18s ease, transform 0.18s ease;
    object-fit: cover;
    z-index: 0;

    ${UserMenuTrigger}:hover & {
        opacity: 0.85;
        transform: translate(-50%, -50%) scale(1);
    }
`;

const AvatarImg = styled.img`
    position: relative;
    z-index: 1;
    width: 32px;
    height: 32px;
    border-radius: 9999px;
    background: ${({ theme }) => theme.colors.panelAlt};
    display: block;
    flex-shrink: 0;
    object-fit: cover;
    overflow: hidden;
`;

const Dropdown = styled.div`
    position: absolute;
    right: 0;
    top: calc(100% + 0.5rem);
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    padding: 0.4rem 0;
    min-width: 14rem;
    z-index: 10000;
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.28);
`;

const DropdownHeader = styled.div`
    padding: 0.4rem 0.9rem 0.5rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    margin-bottom: 0.35rem;
`;

const DropdownUsername = styled.div`
    font-size: 0.78rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
`;

const MenuItem = styled(Link)`
    display: block;
    padding: 0.5rem 0.9rem;
    font-size: 0.78rem;
    color: ${({ theme }) => theme.colors.text};
    text-decoration: none;
    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }
`;

const MenuDivider = styled.div`
    height: 1px;
    background: ${({ theme }) => theme.colors.border};
    margin: 0.35rem 0;
`;

const SignInLink = styled(Link)`
    display: inline-flex;
    align-items: center;
    padding: 0.45rem 0.95rem;
    border-radius: 999px;
    background: ${({ theme }) => theme.colors.gradient};
    color: #fff;
    font-weight: 700;
    font-size: 0.8rem;
    text-decoration: none;
    &:hover { filter: brightness(1.08); }
`;

// Shared profile menu content — also used by MobileBottomNav and the user-menu dropdown.
export function ProfileMenuContent({ displayName, onItemClick }) {
    const userLevel = Number(Storage.load('user_level', '0')) || 0;
    const isAdmin = userLevel >= 100;
    const [referralsEnabled, setReferralsEnabled] = useState(false);

    useEffect(() => {
        const readConfig = () => {
            try {
                const nc = JSON.parse(localStorage.getItem('nodeConfig') || '{}');
                setReferralsEnabled(!!nc.registration_invite_code_required);
            } catch (_) {
                setReferralsEnabled(false);
            }
        };
        readConfig();
        window.addEventListener('nodeConfigUpdated', readConfig);
        return () => window.removeEventListener('nodeConfigUpdated', readConfig);
    }, []);

    const handleItemClick = (targetPath) => {
        if (typeof onItemClick === 'function') onItemClick(targetPath);
    };

    return (
        <>
            <DropdownHeader>
                {displayName && <DropdownUsername>@{displayName}</DropdownUsername>}
            </DropdownHeader>
            <MenuItem to="/profile" onClick={() => handleItemClick('/profile')}>Profile</MenuItem>
            <MenuItem to="/subscription" onClick={() => handleItemClick('/subscription')}>Subscription</MenuItem>
            <MenuItem to="/settings" onClick={() => handleItemClick('/settings')}>Settings</MenuItem>
            <MenuItem to="/follows" onClick={() => handleItemClick('/follows')}>Follows</MenuItem>
            <MenuItem to="/blocks" onClick={() => handleItemClick('/blocks')}>Blocks</MenuItem>
            <MenuItem to="/agents" onClick={() => handleItemClick('/agents')}>Agents</MenuItem>
            <MenuItem to="/network" onClick={() => handleItemClick('/network')}>Network</MenuItem>
            {referralsEnabled && (
                <MenuItem to="/referrals" onClick={() => handleItemClick('/referrals')}>Referrals</MenuItem>
            )}
            {isAdmin && (
                <>
                    <MenuDivider />
                    <MenuItem to="/stats" onClick={() => handleItemClick('/stats')}>Stats</MenuItem>
                    <MenuItem to="/reports" onClick={() => handleItemClick('/reports')}>Reports</MenuItem>
                </>
            )}
            <MenuDivider />
            <MenuItem to="/sign_out" onClick={() => handleItemClick('/sign_out')}>Sign out</MenuItem>
        </>
    );
}

const formatBadgeCount = (n) => n > 99 ? '99+' : String(n);

/**
 * DiceBear identicon URL matching the mobile app's `Avatar` atom defaults.
 * Seeded by username when available, otherwise by public key.
 */
function dicebearUrl(seed, pxSize) {
    const safeSeed = encodeURIComponent(seed || 'default');
    const size = Math.max(32, Math.round(pxSize * 2));
    return `https://api.dicebear.com/9.x/identicon/png?seed=${safeSeed}&size=${size}`;
}

function TopBar({ state }) {
    const location = useLocation();
    const navigate = useNavigate();
    const path = location.pathname;

    const isInbox = path === '/inbox';
    const isLoggedIn = !!(state && state.publicKey);

    const username = (state && state.username) ? state.username : Storage.load('username', '');
    const publicKey = (state && state.publicKey) ? state.publicKey : Storage.load('publicKey', '');
    const avatarSeed = username || publicKey || 'default';
    const avatarSrc = dicebearUrl(avatarSeed, 32);

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

    const [menuOpen, setMenuOpen] = useState(false);
    const menuRef = useRef(null);
    useEffect(() => {
        const onDoc = (e) => {
            if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
        };
        document.addEventListener('mousedown', onDoc, true);
        return () => document.removeEventListener('mousedown', onDoc, true);
    }, []);
    useEffect(() => { setMenuOpen(false); }, [location.pathname]);

    const [query, setQuery] = useState('');
    const handleSearchSubmit = useCallback((e) => {
        e.preventDefault();
        const q = query.trim();
        if (!q) return;
        navigate(`/search?q=${encodeURIComponent(q)}`);
    }, [query, navigate]);

    return (
        <Bar>
            <BarInner>
            <BrandLink to="/home" aria-label="Mirage home">Mirage</BrandLink>

            <LeftSpacer />

            <SearchWrapper role="search" onSubmit={handleSearchSubmit}>
                <SearchInner>
                    <SearchIcon viewBox="0 0 24 24" aria-hidden="true">
                        <path
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M21 21l-4.35-4.35M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z"
                        />
                    </SearchIcon>
                    <SearchInput
                        type="search"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search Mirage"
                        aria-label="Search"
                    />
                    {query.length > 0 && (
                        <ClearButton
                            type="button"
                            onClick={() => setQuery('')}
                            aria-label="Clear search"
                        >
                            <svg viewBox="0 0 24 24" aria-hidden="true">
                                <path
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="2.2"
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    d="M6 6l12 12M18 6L6 18"
                                />
                            </svg>
                        </ClearButton>
                    )}
                </SearchInner>
            </SearchWrapper>

            <RightSpacer>
                {isLoggedIn && (
                    <CreateButton to="/create_post" aria-label="Create post">
                        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                            <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" d="M12 5v14M5 12h14" />
                        </svg>
                        <span className="create-label">Create</span>
                    </CreateButton>
                )}

                {isLoggedIn && (
                    <IconButton
                        to="/inbox"
                        $active={isInbox}
                        aria-label={inboxCount > 0 ? `Inbox, ${inboxCount} unread` : 'Inbox'}
                    >
                        <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
                            {isInbox
                                ? <path fill="currentColor" d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z" />
                                : <path fill="currentColor" d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 14H4V8l8 5 8-5v10zm-8-7L4 6h16l-8 5z" />
                            }
                        </svg>
                        {inboxCount > 0 && <InboxBadge aria-hidden="true">{formatBadgeCount(inboxCount)}</InboxBadge>}
                    </IconButton>
                )}

                {isLoggedIn ? (
                    <UserMenuWrapper ref={menuRef}>
                        <UserMenuTrigger
                            type="button"
                            $open={menuOpen}
                            onClick={() => setMenuOpen((v) => !v)}
                            aria-haspopup="menu"
                            aria-expanded={menuOpen}
                            aria-label="Account menu"
                        >
                            <AvatarGlow src={avatarSrc} alt="" aria-hidden="true" loading="lazy" />
                            <AvatarImg src={avatarSrc} alt="" loading="lazy" />
                        </UserMenuTrigger>
                        {menuOpen && (
                            <Dropdown role="menu">
                                <ProfileMenuContent
                                    displayName={username}
                                    onItemClick={() => setMenuOpen(false)}
                                />
                            </Dropdown>
                        )}
                    </UserMenuWrapper>
                ) : (
                    <SignInLink to="/login">Sign in</SignInLink>
                )}
            </RightSpacer>
            </BarInner>
        </Bar>
    );
}

export default TopBar;
