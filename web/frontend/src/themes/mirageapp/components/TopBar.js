import React, { useState, useRef, useEffect, useCallback } from 'react';
import styled from 'styled-components';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import Storage from '../../../utils/Storage';
import { THEME_MANIFESTS } from '../../manifests';
import { normalizeThemeId } from '../../../registry/theme';
import SearchDropdown from './SearchDropdown.js';
import { useSearchDropdown } from '../../../logic/useSearchDropdown';
import { dicebearAvatarUrl } from '../../../utils/avatar';
import ConfirmDialog from './ConfirmDialog.js';

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
    /* Explicit, locked height so the Sidebar's sticky top offset always */
    /* matches the real TopBar box, regardless of search input, avatar */
    /* size, or font-size clamp. Prevents the Sidebar from jumping up on */
    /* short (non-scrollable) pages like Create Post / Search. */
    height: calc(2.5rem + 1px);
    box-sizing: border-box;
    /* Match the mobile app's main background color (mirage-mobile-app surfaces.background) */
    background: ${({ theme }) => theme.colors.bg};
    border-bottom: 1px solid ${({ theme }) => theme.colors.headerBorder};
    backdrop-filter: saturate(1.1);
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
    padding: 0 0.5rem;
    box-sizing: border-box;
    height: 100%;

    @media (max-width: 600px) {
        gap: 0.5rem;
        padding: 0 0.35rem;
    }

    /* Very large screens (> average laptop): drop the centered 1400px cap
     * so the brand / nav keep their left-edge position and the header
     * content doesn't visually shift inward when the viewport widens.
     * Matches the Layout override in MirageAppShell.js. */
    @media (min-width: 1500px) {
        max-width: none;
        margin: 0;
    }
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

    @media (max-width: 600px) {
    }
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
    background: transparent;
    text-decoration: none;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    @media (max-width: 1000px) {
        width: 34px;
        height: 34px;
        svg { width: 20px; height: 20px; }
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
    width: 42px;
    height: 42px;
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

// Hard-pinned to the dark-mode chip color (#232830) in BOTH modes so the
// top-bar avatar matches the profile-page avatar exactly. DiceBear's
// identicon variant is transparent, so this fills the pattern's negative
// space identically in light and dark themes.
const AvatarImg = styled.img`
    position: relative;
    z-index: 1;
    width: 32px;
    height: 32px;
    border-radius: 9999px;
    background: #232830;
    display: block;
    flex-shrink: 0;
    object-fit: cover;
    overflow: hidden;

    @media (max-width: 1000px) {
        width: 28px;
        height: 28px;
    }
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

const MenuButton = styled.button`
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.5rem 0.9rem;
    font-size: 0.78rem;
    color: ${({ theme }) => theme.colors.text};
    background: transparent;
    border: none;
    cursor: pointer;
    font-family: inherit;
    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }
`;

const MenuDivider = styled.div`
    height: 1px;
    background: ${({ theme }) => theme.colors.border};
    margin: 0.35rem 0;
`;

const LoginPillLink = styled(Link)`
    display: inline-flex;
    align-items: center;
    padding: 0.42rem 0.95rem;
    border-radius: 999px;
    background: ${({ theme }) => theme.colors.gradient};
    color: #fff;
    font-weight: 500;
    font-size: 0.76rem;
    text-decoration: none;
    line-height: 1;
    border: none;
    box-shadow: none;
    transition: filter 0.16s ease;

    &:hover {
        filter: brightness(1.08);
        text-decoration: none;
        box-shadow: none;
    }

    &:focus,
    &:focus-visible,
    &:active {
        outline: none;
        box-shadow: none;
    }

    @media (max-width: 1000px) {
        display: none;
    }
`;

const SidebarToggleButton = styled.button`
    display: none;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border-radius: 999px;
    border: none;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    cursor: pointer;
    padding: 0;
    flex-shrink: 0;
    -webkit-tap-highlight-color: transparent;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    &:focus,
    &:focus-visible {
        outline: none;
        box-shadow: none;
    }

    @media (max-width: 1000px) {
        display: inline-flex;
    }

    @media (max-width: 600px) {
        width: 32px;
        height: 32px;
    }
`;

const CompactSearchButton = styled.button`
    display: none;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border-radius: 999px;
    border: none;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    cursor: pointer;
    padding: 0;
    flex-shrink: 0;
    -webkit-tap-highlight-color: transparent;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    &:focus,
    &:focus-visible {
        outline: none;
        box-shadow: none;
    }

    @media (max-width: 800px) {
        display: inline-flex;
    }

    @media (max-width: 600px) {
        width: 32px;
        height: 32px;
    }
`;

const MoreButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border-radius: 999px;
    background: ${({ theme, $open }) => ($open ? theme.colors.hoverBg : 'transparent')};
    color: ${({ theme }) => theme.colors.text};
    border: none;
    cursor: pointer;
    padding: 0;
    -webkit-tap-highlight-color: transparent;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    &:focus,
    &:focus-visible,
    &:active {
        outline: none;
        box-shadow: none;
    }

    svg {
        width: 20px;
        height: 20px;
        display: block;
    }
`;

const MenuSectionLabel = styled.div`
    padding: 0.4rem 0.9rem 0.3rem;
    font-size: 0.58rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const ThemeRowButton = styled.button`
    display: flex;
    align-items: center;
    gap: 0.55rem;
    width: 100%;
    padding: 0.4rem 0.9rem;
    border: none;
    background: ${({ theme, $active }) =>
        $active ? theme.colors.hoverBg : 'transparent'};
    color: ${({ theme }) => theme.colors.text};
    font-family: inherit;
    font-size: 0.76rem;
    font-weight: 500;
    text-align: left;
    cursor: pointer;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }
`;

const ThemeSwatchDot = styled.span`
    width: 0.85rem;
    height: 0.85rem;
    border-radius: 999px;
    flex-shrink: 0;
    background: ${({ $bg }) => $bg || '#667eea'};
    border: 1px solid rgba(0, 0, 0, 0.12);
`;

const ThemeNameText = styled.span`
    flex: 1;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const ActiveDot = styled.span`
    width: 0.32rem;
    height: 0.32rem;
    border-radius: 999px;
    background: ${({ theme }) => theme.colors.link};
    flex-shrink: 0;
`;

const ModeTrack = styled.div`
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 4px;
    margin: 0.3rem 0.9rem 0.2rem;
    padding: 4px;
    border-radius: 10px;
    background: ${({ theme }) => theme.colors.hoverBg};
    box-sizing: border-box;
`;

const ModeIconButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.4rem 0;
    border: none;
    border-radius: 7px;
    background: ${({ theme, $active }) =>
        $active ? theme.colors.panel : 'transparent'};
    color: ${({ theme, $active }) =>
        $active ? theme.colors.text : theme.colors.subtleText};
    cursor: pointer;
    box-shadow: ${({ $active }) => ($active ? '0 1px 2px rgba(0, 0, 0, 0.18)' : 'none')};
    transition: background 0.16s ease, color 0.16s ease;

    svg {
        width: 16px;
        height: 16px;
    }

    &:hover {
        color: ${({ theme }) => theme.colors.text};
    }
`;

// Swatch colors per theme id used by the guest dropdown theme list.
const THEME_SWATCHES = {
    mirageapp: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    bluemoon: 'linear-gradient(135deg, #4f7fff 0%, #1b3bbf 100%)',
    onyx: 'linear-gradient(135deg, #2a2a2a 0%, #000000 100%)',
    oldreddit: 'linear-gradient(135deg, #ff6a33 0%, #cc3700 100%)',
};

/**
 * 3-dots menu shown on the right side of the TopBar for logged-out users.
 * Contains: Login, Signup, and a Theme picker with light/dark/auto mode toggle.
 */
function GuestMenu() {
    const [open, setOpen] = useState(false);
    const wrapRef = useRef(null);
    const location = useLocation();

    const [activeThemeId, setActiveThemeId] = useState(() => {
        try {
            return normalizeThemeId(Storage.load('theme_id', 'mirageapp'));
        } catch (_) {
            return 'mirageapp';
        }
    });
    const [themeMode, setThemeMode] = useState(() => {
        try {
            const v = Storage.load('theme_mode', 'time');
            return v === 'light' || v === 'dark' || v === 'time' ? v : 'time';
        } catch (_) {
            return 'time';
        }
    });

    useEffect(() => {
        const onDoc = (e) => {
            if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener('mousedown', onDoc, true);
        return () => document.removeEventListener('mousedown', onDoc, true);
    }, []);

    useEffect(() => { setOpen(false); }, [location.pathname]);

    useEffect(() => {
        const onThemeIdChanged = (e) => {
            const next = e?.detail?.themeId;
            if (next) setActiveThemeId(next);
        };
        const onThemeModeChanged = (e) => {
            const next = e?.detail?.mode;
            if (next) setThemeMode(next);
        };
        window.addEventListener('themeIdChanged', onThemeIdChanged);
        window.addEventListener('themeModeChanged', onThemeModeChanged);
        return () => {
            window.removeEventListener('themeIdChanged', onThemeIdChanged);
            window.removeEventListener('themeModeChanged', onThemeModeChanged);
        };
    }, []);

    const handleThemePick = (id) => {
        const normalized = normalizeThemeId(id);
        if (normalized === activeThemeId) return;
        setActiveThemeId(normalized);
        Storage.save('theme_id', normalized);
        try {
            window.dispatchEvent(new CustomEvent('themeIdChanged', { detail: { themeId: normalized } }));
        } catch (_) { }
    };

    const handleModePick = (mode) => {
        if (mode === themeMode) return;
        setThemeMode(mode);
        Storage.save('theme_mode', mode);
        try {
            window.dispatchEvent(new CustomEvent('themeModeChanged', { detail: { mode } }));
        } catch (_) { }
    };

    return (
        <UserMenuWrapper ref={wrapRef}>
            <MoreButton
                type="button"
                $open={open}
                onClick={() => setOpen((v) => !v)}
                aria-haspopup="menu"
                aria-expanded={open}
                aria-label="More options"
            >
                <svg viewBox="0 0 24 24" aria-hidden="true">
                    <circle cx="5" cy="12" r="1.9" fill="currentColor" />
                    <circle cx="12" cy="12" r="1.9" fill="currentColor" />
                    <circle cx="19" cy="12" r="1.9" fill="currentColor" />
                </svg>
            </MoreButton>
            {open && (
                <Dropdown role="menu">
                    <MenuSectionLabel>Account</MenuSectionLabel>
                    <MenuItem to="/signup" onClick={() => setOpen(false)}>Sign up</MenuItem>
                    <MenuItem to="/login" onClick={() => setOpen(false)}>Log in</MenuItem>
                    <MenuDivider />
                    <MenuSectionLabel>Theme</MenuSectionLabel>
                    {THEME_MANIFESTS.map((m) => {
                        const active = m.id === activeThemeId;
                        return (
                            <ThemeRowButton
                                key={m.id}
                                type="button"
                                $active={active}
                                onClick={() => handleThemePick(m.id)}
                                aria-pressed={active}
                                title={m.label || m.id}
                            >
                                <ThemeSwatchDot $bg={THEME_SWATCHES[m.id]} />
                                <ThemeNameText>{m.label || m.id}</ThemeNameText>
                                {active && <ActiveDot aria-hidden="true" />}
                            </ThemeRowButton>
                        );
                    })}
                    <ModeTrack role="group" aria-label="Theme mode">
                        <ModeIconButton
                            type="button"
                            $active={themeMode === 'light'}
                            onClick={() => handleModePick('light')}
                            aria-pressed={themeMode === 'light'}
                            aria-label="Light mode"
                            title="Light"
                        >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <circle cx="12" cy="12" r="4" />
                                <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
                            </svg>
                        </ModeIconButton>
                        <ModeIconButton
                            type="button"
                            $active={themeMode === 'dark'}
                            onClick={() => handleModePick('dark')}
                            aria-pressed={themeMode === 'dark'}
                            aria-label="Dark mode"
                            title="Dark"
                        >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                            </svg>
                        </ModeIconButton>
                        <ModeIconButton
                            type="button"
                            $active={themeMode === 'time'}
                            onClick={() => handleModePick('time')}
                            aria-pressed={themeMode === 'time'}
                            aria-label="Auto mode"
                            title="Auto"
                        >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <rect x="3" y="4" width="18" height="12" rx="2" />
                                <path d="M8 20h8M12 16v4" />
                            </svg>
                        </ModeIconButton>
                    </ModeTrack>
                </Dropdown>
            )}
        </UserMenuWrapper>
    );
}

// Shared profile menu content — also used by MobileBottomNav and the user-menu dropdown.
export function ProfileMenuContent({ displayName, onItemClick, onSignOut }) {
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

    const handleSignOutClick = () => {
        if (typeof onSignOut === 'function') {
            onSignOut();
        } else if (typeof onItemClick === 'function') {
            // Fallback: close menu + legacy route navigation.
            onItemClick('/sign_out');
        }
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
            <MenuButton type="button" onClick={handleSignOutClick}>Sign out</MenuButton>
        </>
    );
}

const formatBadgeCount = (n) => n > 99 ? '99+' : String(n);

// dicebear URL helper lives in `utils/avatar.js` so every surface (TopBar,
// ProfileView, comment author rows, …) renders the same identicon for the
// same user.

function TopBar({ state, onToggleSidebar, onToggleDrawer, sidebarHidden }) {
    const location = useLocation();
    const navigate = useNavigate();
    const path = location.pathname;

    const isInbox = path === '/inbox';
    const isLoggedIn = !!(state && state.publicKey);

    const username = (state && state.username) ? state.username : Storage.load('username', '');
    const publicKey = (state && state.publicKey) ? state.publicKey : Storage.load('publicKey', '');
    // Seed policy mirrors mirage-mobile-app's own-profile surface
    // (`profile-screen.tsx`): wallet address first, username as fallback.
    const avatarSeed = publicKey || username || 'default';
    const avatarSrc = dicebearAvatarUrl(avatarSeed, 32);

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
    const [signOutDialogOpen, setSignOutDialogOpen] = useState(false);
    const menuRef = useRef(null);
    useEffect(() => {
        const onDoc = (e) => {
            if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
        };
        document.addEventListener('mousedown', onDoc, true);
        return () => document.removeEventListener('mousedown', onDoc, true);
    }, []);
    useEffect(() => { setMenuOpen(false); }, [location.pathname]);

    // Search dropdown: drives recent searches, trending topics, and
    // debounced live results while the user is typing.
    const {
        rawQuery: query,
        setQuery,
        resetQuery,
        isSearching,
        liveResults,
        liveError,
        hasQuery,
        hasLiveResults,
        trendingTopics,
        isLoadingTrending,
        recentSearches,
        addRecentSearch,
        removeRecentSearch,
        clearRecentSearches,
    } = useSearchDropdown();

    const [searchFocused, setSearchFocused] = useState(false);
    const searchWrapRef = useRef(null);
    const searchInputRef = useRef(null);

    // Close the dropdown whenever the route changes.
    useEffect(() => {
        setSearchFocused(false);
    }, [location.pathname, location.search]);

    // Click outside → close dropdown.
    useEffect(() => {
        if (!searchFocused) return undefined;
        const onDoc = (e) => {
            if (searchWrapRef.current && !searchWrapRef.current.contains(e.target)) {
                setSearchFocused(false);
            }
        };
        document.addEventListener('mousedown', onDoc, true);
        return () => document.removeEventListener('mousedown', onDoc, true);
    }, [searchFocused]);

    const submitQuery = useCallback((raw) => {
        const q = String(raw || '').trim();
        if (!q) return;
        addRecentSearch(q);
        setSearchFocused(false);
        if (searchInputRef.current) searchInputRef.current.blur();
        navigate(`/search?q=${encodeURIComponent(q)}`);
    }, [addRecentSearch, navigate]);

    const handleSearchSubmit = useCallback((e) => {
        e.preventDefault();
        submitQuery(query);
    }, [query, submitQuery]);

    const handleRecentClick = useCallback((entry) => {
        submitQuery(entry.query);
    }, [submitQuery]);

    const handleSearchKeyDown = useCallback((e) => {
        if (e.key === 'Escape') {
            e.preventDefault();
            setSearchFocused(false);
            if (searchInputRef.current) searchInputRef.current.blur();
        }
    }, []);

    return (
        <>
        <Bar>
            <BarInner>
            <SidebarToggleButton
                type="button"
                onClick={onToggleDrawer}
                aria-label="Toggle sidebar"
            >
                <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                    <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
                </svg>
            </SidebarToggleButton>

            <BrandLink to="/home" aria-label="Mirage home">Mirage</BrandLink>

            <LeftSpacer />

            <SearchWrapper ref={searchWrapRef} role="search" onSubmit={handleSearchSubmit}>
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
                        ref={searchInputRef}
                        type="search"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        onFocus={() => setSearchFocused(true)}
                        onMouseDown={() => setSearchFocused(true)}
                        onClick={() => setSearchFocused(true)}
                        onKeyDown={handleSearchKeyDown}
                        placeholder="Search Mirage"
                        aria-label="Search"
                        aria-expanded={searchFocused}
                        autoComplete="off"
                    />
                    {query.length > 0 && (
                        <ClearButton
                            type="button"
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => {
                                resetQuery();
                                if (searchInputRef.current) searchInputRef.current.focus();
                            }}
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
                {searchFocused && (
                    <SearchDropdown
                        rawQuery={query}
                        hasQuery={hasQuery}
                        isSearching={isSearching}
                        liveResults={liveResults}
                        liveError={liveError}
                        hasLiveResults={hasLiveResults}
                        trendingTopics={trendingTopics}
                        isLoadingTrending={isLoadingTrending}
                        recentSearches={recentSearches}
                        onRecentClick={handleRecentClick}
                        onRemoveRecent={removeRecentSearch}
                        onClearRecents={clearRecentSearches}
                        onResultNavigate={() => setSearchFocused(false)}
                        onSubmitQuery={submitQuery}
                    />
                )}
            </SearchWrapper>

            <RightSpacer>
                <CompactSearchButton
                    type="button"
                    onClick={() => navigate('/search')}
                    aria-label="Search"
                >
                    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                        <path fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M10.5 18a7.5 7.5 0 1 1 0-15 7.5 7.5 0 0 1 0 15Z" />
                    </svg>
                </CompactSearchButton>
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
                                    onSignOut={() => {
                                        setMenuOpen(false);
                                        setSignOutDialogOpen(true);
                                    }}
                                />
                            </Dropdown>
                        )}
                    </UserMenuWrapper>
                ) : (
                    <>
                        <LoginPillLink to="/login">Sign in</LoginPillLink>
                        <GuestMenu />
                    </>
                )}
            </RightSpacer>
            </BarInner>
        </Bar>
            {signOutDialogOpen && (
                <ConfirmDialog
                    open
                    title="Sign out?"
                    message="You’ll need your recovery phrase to log back in."
                    confirmLabel="Sign out"
                    confirmVariant="danger"
                    onConfirm={() => {
                        setSignOutDialogOpen(false);
                        navigate('/sign_out');
                    }}
                    onCancel={() => setSignOutDialogOpen(false)}
                />
            )}
        </>
    );
}

export default TopBar;
