import { Helmet } from "react-helmet-async";
import { useEffect, useRef, useState } from "react";
import styled, { useTheme } from "styled-components";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
    HiChevronLeft,
    HiChevronRight,
    HiChevronDown,
    HiClipboardDocument,
    HiCheck,
    HiUsers,
    HiUserGroup,
    HiBolt,
    HiClock,
    HiArrowTrendingUp,
    HiExclamationTriangle,
    HiTrophy,
} from "react-icons/hi2";
import ShowMoreButton from "../components/ShowMoreButton.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, CappedPageColumn } from "../Layout";
import { useReferrals, compareISOWeeks, shiftISOWeek, formatWeekRange } from "../../../logic/useReferrals";
import UserAvatar from "../components/UserAvatar.js";

/**
 * ReferralsView — `default` Plan 06 sub-plan 05 (Referrals half).
 *
 * Polished section-list rewrite of the /referrals route. Visual only —
 * `useReferrals` hook wiring (week nav, copy, pagination, error/loading
 * branches) is unchanged. Follows `docs/guides/web-theme-default/RULES.md`.
 *
 * Visual highlights:
 *  - Gradient hero share card (R2 brand `gradient` + `link` accent) with
 *    integrated copy button.
 *  - Stat tiles with icon + accent border + active-rate progress bar.
 *  - Smooth gradient-area activity chart with grid lines and value labels.
 *  - Segmented week pill (Prev | week | Next) instead of three loose buttons.
 *  - Beefier list rows: 40px avatar, optional rank chip for top 3, status
 *    ring on the avatar, tabular meta numbers.
 */

/* -------------------------------------------------------------------------- */
/* Shell                                                                      */
/* -------------------------------------------------------------------------- */

const ReferralsWrap = styled.div`
    width: 90%;
    max-width: 960px;
    margin: -0.75rem auto 0;

    @media (max-width: 1000px) {
        width: 100%;
        max-width: none;
        margin-top: -0.5rem;
    }

    /* Large displays: viewport-center override. See SettingsView for
     * the full rationale — above ~1500px the shell drops its max-width
     * cap and pins the sidebar to the left viewport edge, so
     * margin: auto inside Main no longer aligns with viewport center.
     *
     * Offset = sidebar + divider + Main left padding:
     *   sidebar visible: 273px,  sidebar hidden: 33px */
    @media (min-width: 1050px) {
        [data-sidebar-hidden='true'] & {
            margin-left: calc(50vw - 480px - 33px);
            margin-right: auto;
        }
    }

    @media (min-width: 1600px) {
        [data-sidebar-hidden='false'] & {
            margin-left: calc(50vw - 480px - 273px);
            margin-right: auto;
        }
    }

    @media (min-width: 1900px) {
        max-width: 1100px;

        [data-sidebar-hidden='false'] & {
            margin-left: calc(50vw - 550px - 273px);
        }
        [data-sidebar-hidden='true'] & {
            margin-left: calc(50vw - 550px - 33px);
        }
    }
`;

const ReferralsTabbedContainer = styled(TabbedContainer)`
    margin-top: 0;
`;

const ReferralsShellBody = styled(ContainerBody)`
    padding: 0.35rem 0 1rem;
    border: none;
    border-radius: 0;
`;

const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.5rem 1rem;

    @media (max-width: 600px) {
        padding: 0.5rem 0;
    }
`;

const HeaderTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

const HeaderAside = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 40%;
`;

const SectionDivider = styled.div`
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    width: 100%;
`;

/* -------------------------------------------------------------------------- */
/* Sections                                                                   */
/* -------------------------------------------------------------------------- */

const Section = styled.section`
    display: flex;
    flex-direction: column;
`;

const SectionHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 1rem 1rem 0.5rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;

    @media (max-width: 600px) {
        padding: 1rem 0 0.5rem;
    }
`;

const SectionHeaderLabel = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
`;

const SectionBody = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.65rem;
    padding: 0 1rem 0.85rem;

    @media (max-width: 1000px) {
        padding: 0 0.85rem 0.85rem;
    }

    @media (max-width: 600px) {
        padding: 0 0 0.85rem;
    }
`;

const ListSectionBody = styled.div`
    display: flex;
    flex-direction: column;
    padding: 0 0 0.5rem;
`;

const ErrorBanner = styled.div`
    background: ${({ theme }) => theme.colors.buttonDangerBg};
    border: 1px solid ${({ theme }) => theme.colors.buttonDangerBorder};
    border-radius: 8px;
    padding: 0.55rem 0.75rem;
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.72rem;
    font-weight: 500;
    margin: 0.5rem 1rem 0;

    @media (max-width: 1000px) {
        margin: 0.5rem 0.85rem 0;
    }
`;

/* -------------------------------------------------------------------------- */
/* Hero share card                                                            */
/* -------------------------------------------------------------------------- */

const HeroCard = styled.div`
    position: relative;
    border-radius: 12px;
    padding: 1rem 1.1rem;
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-left: 3px solid ${({ theme }) => theme.colors.gradientStart};
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
`;

const HeroTopRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.6rem;
    flex-wrap: wrap;
`;

const HeroEyebrow = styled.div`
    color: ${({ theme }) => theme.colors.gradientStart};
    font-size: 0.55rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.12em;
`;

const HeroBadge = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.22rem 0.55rem;
    border-radius: 999px;
    background: ${({ $tone, theme }) => $tone === 'danger' ? `${theme.colors.voteDown}14` : theme.colors.bg};
    border: 1px solid ${({ $tone, theme }) => $tone === 'danger' ? `${theme.colors.voteDown}40` : theme.colors.border};
    color: ${({ $tone, theme }) => $tone === 'danger' ? theme.colors.voteDown : theme.colors.subtleText};
    font-size: 0.58rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
`;

const HeroTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.95rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    line-height: 1.3;
`;

const HeroSubtitle = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    font-weight: 500;
    line-height: 1.5;
`;

const HeroTextStack = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
`;

const ShareLinkPill = styled.div`
    position: relative;
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.45rem 0.45rem 0.45rem 0.75rem;
    border-radius: 10px;
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    opacity: ${({ $disabled }) => $disabled ? 0.8 : 1};
    transition: border-color 0.15s ease, opacity 0.15s ease;
    overflow: hidden;

    &:hover {
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    @media (max-width: 560px) {
        flex-direction: column;
        align-items: stretch;
        padding: 0.55rem;
    }
`;

const ShareUrl = styled.input`
    flex: 1;
    min-width: 0;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    border: none;
    outline: none;
    padding: 0.25rem 0;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: -0.01em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;

    &::selection { background: ${({ theme }) => theme.colors.menuSelectedBg}; }
`;

const CopyIconButton = styled.button`
    flex-shrink: 0;
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 8px;
    border: 1px solid ${({ $copied, theme }) =>
        $copied ? theme.colors.buttonSuccessBorder : theme.colors.border};
    background: ${({ $copied, theme }) =>
        $copied ? theme.colors.buttonSuccessBg : 'transparent'};
    color: ${({ $copied, theme }) =>
        $copied ? theme.colors.voteUp : theme.colors.subtleText};
    cursor: pointer;
    line-height: 1;
    transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;

    &:hover:not(:disabled) {
        background: ${({ $copied, theme }) =>
        $copied ? theme.colors.buttonSuccessHoverBg : theme.colors.hoverBg};
        border-color: ${({ $copied, theme }) =>
        $copied ? theme.colors.buttonSuccessBorder : theme.colors.borderStrong};
        color: ${({ $copied, theme }) =>
        $copied ? theme.colors.voteUp : theme.colors.text};
    }

    &:focus { outline: none; }

    svg { width: 0.95rem; height: 0.95rem; flex-shrink: 0; }
`;

const HeroEmpty = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.72rem;
    font-weight: 500;
    line-height: 1.5;
    padding: 0.5rem 0.1rem;
`;

/* -------------------------------------------------------------------------- */
/* Toggle — mirrors SettingsView's Toggle (42×24 track, 20px knob)            */
/* -------------------------------------------------------------------------- */

const ToggleTrack = styled.div`
    width: 42px;
    height: 24px;
    flex: 0 0 42px;
    border-radius: 12px;
    background: ${({ $checked, theme }) => $checked ? theme.colors.focusBlue : theme.colors.surface3};
    position: relative;
    cursor: pointer;
    transition: background 0.2s ease;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.15);
`;

const ToggleKnob = styled.div`
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: #fff;
    position: absolute;
    top: 2px;
    left: ${({ $checked }) => $checked ? '20px' : '2px'};
    transition: left 0.2s ease;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
`;

function Toggle({ checked, onChange, disabled }) {
    return (
        <ToggleTrack
            $checked={checked}
            role="switch"
            aria-checked={checked}
            tabIndex={0}
            style={disabled ? { opacity: 0.5, cursor: 'not-allowed' } : undefined}
            onClick={() => {
                if (disabled) return;
                onChange({ target: { checked: !checked } });
            }}
            onKeyDown={(e) => {
                if (disabled) return;
                if (e.key === ' ' || e.key === 'Enter') {
                    e.preventDefault();
                    onChange({ target: { checked: !checked } });
                }
            }}
        >
            <ToggleKnob $checked={checked} />
        </ToggleTrack>
    );
}

/* Referral-link toggle row embedded in the hero card. Border-top separates
 * it from the share-link pill above. Layout mirrors Settings' ToggleRow —
 * label / description stack on the left, Toggle pinned to the right. */
const ToggleRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding-top: 0.6rem;
    border-top: 1px solid ${({ theme }) => theme.colors.border};
`;

const ToggleText = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
`;

const ToggleLabel = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.72rem;
    font-weight: 600;
    line-height: 1.3;
`;

const ToggleDesc = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 500;
    line-height: 1.4;
`;

const ToggleFeedback = styled.div`
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.35;
    padding: 0.15rem 0.1rem 0;
    color: ${({ theme, $tone }) => $tone === 'error' ? theme.colors.voteDown : theme.colors.voteUp};
`;

/* -------------------------------------------------------------------------- */
/* Week controls — segmented pill                                             */
/* -------------------------------------------------------------------------- */

const WeekSegment = styled.div`
    display: inline-flex;
    align-items: stretch;
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 999px;
    align-self: stretch;
    width: 100%;
    max-width: 36rem;

    /* Clip the hover-bg of the first/last buttons to the pill shape */
    & > *:first-child {
        border-top-left-radius: 999px;
        border-bottom-left-radius: 999px;
    }
    & > *:last-child {
        border-top-right-radius: 999px;
        border-bottom-right-radius: 999px;
    }

    @media (max-width: 560px) {
        max-width: 100%;
    }
`;

const WeekNavButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.25rem;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    border: none;
    padding: 0.45rem 0.85rem;
    font-family: inherit;
    font-size: 0.72rem;
    font-weight: 600;
    line-height: 1;
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;
    flex-shrink: 0;

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.hoverBg};
        color: ${({ theme }) => theme.colors.text};
    }

    &:disabled {
        cursor: not-allowed;
        opacity: 0.4;
        color: ${({ theme }) => theme.colors.subtleText};
    }

    &:focus { outline: none; }

    svg { width: 0.85rem; height: 0.85rem; flex-shrink: 0; }
`;

const WeekDivider = styled.div`
    width: 1px;
    background: ${({ theme }) => theme.colors.border};
    flex-shrink: 0;
`;

const WeekSelectWrap = styled.div`
    position: relative;
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: stretch;
`;

const WeekMenuButton = styled.button`
    width: 100%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    border: none;
    padding: 0.45rem 0.85rem;
    font-family: inherit;
    font-size: 0.75rem;
    font-weight: 600;
    line-height: 1.2;
    cursor: pointer;
    transition: background 0.15s ease;

    &:hover { background: ${({ theme }) => theme.colors.hoverBg}; }
    &:focus { outline: none; }

    svg {
        width: 0.8rem;
        height: 0.8rem;
        color: ${({ theme }) => theme.colors.subtleText};
        transition: transform 0.2s ease;
        flex-shrink: 0;
    }

    &[aria-expanded="true"] svg { transform: rotate(180deg); }
`;

const WeekMenuPopover = styled.div`
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    right: 0;
    max-height: min(70vh, 320px);
    overflow-y: auto;
    background: ${({ theme }) => theme.colors.menuBg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.28);
    z-index: 200;

    scrollbar-width: thin;
    scrollbar-color: ${({ theme }) => theme.colors.scrollbar} transparent;
    &::-webkit-scrollbar { width: 8px; }
    &::-webkit-scrollbar-thumb {
        background: ${({ theme }) => theme.colors.scrollbar};
        border-radius: 4px;
    }
`;

const WeekMenuItem = styled.button`
    display: flex;
    align-items: center;
    gap: 0.6rem;
    width: 100%;
    padding: 0.5rem 0.9rem;
    background: ${({ $active, theme }) =>
        $active ? theme.colors.menuSelectedBg : 'transparent'};
    color: ${({ $active, theme }) =>
        $active ? theme.colors.sidebarItemActiveText : theme.colors.sidebarItemText};
    border: none;
    border-radius: 0;
    font-family: inherit;
    font-size: 0.72rem;
    font-weight: ${({ $active }) => ($active ? 600 : 500)};
    text-align: left;
    cursor: pointer;
    line-height: 1.2;
    transition: background 0.15s ease, color 0.15s ease;

    &:hover {
        background: ${({ $active, theme }) =>
        $active ? theme.colors.menuSelectedBg : theme.colors.menuSelectedBg};
        color: ${({ $active, theme }) =>
        $active ? theme.colors.sidebarItemActiveText : theme.colors.menuItemHoverText};
    }

    &:focus { outline: none; }
`;

const ControlsMeta = styled.div`
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
    flex-wrap: wrap;
    padding: 0 0.25rem;
`;

const MutedNote = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 500;
`;

/* -------------------------------------------------------------------------- */
/* Stat tiles                                                                 */
/* -------------------------------------------------------------------------- */

const StatsRow = styled.div`
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.6rem;

    @media (max-width: 700px) {
        grid-template-columns: 1fr;
    }
`;

const StatTile = styled.div`
    position: relative;
    background: ${({ theme, $tone }) => {
        if ($tone === 'success') return `${theme.colors.voteUp}10`;
        if ($tone === 'brand') return `${theme.colors.gradientStart}14`;
        return theme.colors.bg;
    }};
    border: 1px solid ${({ theme, $tone }) => {
        if ($tone === 'success') return `${theme.colors.voteUp}40`;
        if ($tone === 'brand') return `${theme.colors.gradientStart}40`;
        return theme.colors.border;
    }};
    border-radius: 12px;
    padding: 0.85rem 0.95rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    overflow: hidden;
    transition: border-color 0.15s ease, transform 0.15s ease;

    &:hover {
        transform: translateY(-1px);
    }
`;

const StatHead = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
`;

const StatLabel = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.55rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
`;

const StatIcon = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border-radius: 8px;
    background: ${({ theme, $tone }) => {
        if ($tone === 'success') return theme.colors.buttonSuccessBg;
        if ($tone === 'brand') return `${theme.colors.gradientStart}26`;
        return theme.colors.accent;
    }};
    color: ${({ theme, $tone }) => {
        if ($tone === 'success') return theme.colors.voteUp;
        if ($tone === 'brand') return theme.colors.gradientStart;
        return theme.colors.subtleText;
    }};

    svg { width: 14px; height: 14px; }
`;

const StatValue = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.5rem;
    font-weight: 700;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    letter-spacing: -0.03em;
    line-height: 1;
`;

const StatSubLabel = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 500;
    line-height: 1.3;
`;

/* Active-rate progress bar that lives inside the "Active this week" tile. */

const ProgressTrack = styled.div`
    position: relative;
    width: 100%;
    height: 4px;
    border-radius: 999px;
    background: ${({ theme }) => theme.colors.border};
    overflow: hidden;
`;

const ProgressFill = styled.div`
    position: absolute;
    inset: 0 auto 0 0;
    width: ${({ $pct }) => `${$pct}%`};
    background: linear-gradient(
        90deg,
        ${({ theme }) => theme.colors.voteUp} 0%,
        ${({ theme }) => theme.colors.gradientStart} 100%
    );
    border-radius: 999px;
    transition: width 0.4s ease;
`;

const ActiveInfo = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.5;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;

    svg {
        width: 0.85rem;
        height: 0.85rem;
        color: ${({ theme }) => theme.colors.subtleText};
        flex-shrink: 0;
    }
`;

/* -------------------------------------------------------------------------- */
/* Chart                                                                      */
/* -------------------------------------------------------------------------- */

const ChartCard = styled.div`
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    padding: 0.95rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
`;

const ChartTopRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    flex-wrap: wrap;
`;

const ChartLegend = styled.div`
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;

    &::before {
        content: '';
        width: 8px;
        height: 8px;
        border-radius: 2px;
        background: ${({ theme }) => theme.colors.link};
    }
`;

const ChartHint = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 500;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
`;

const ChartContainer = styled.div`
    width: 100%;
    max-width: 480px;
    aspect-ratio: 440 / 160;
`;

const ChartSvg = styled.svg`
    width: 100%;
    height: 100%;
    display: block;
    overflow: visible;
`;

const ChartLabel = styled.div`
    display: flex;
    justify-content: space-between;
    font-size: 0.6rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
`;

/**
 * Build a smooth catmull-rom-ish path string from a list of points using
 * cubic bezier control points derived from neighbors. Output is an SVG `d`
 * attribute string. Returns plain `M ... L ...` if there are fewer than 3
 * points (no smoothing possible).
 */
function smoothPath(points) {
    if (points.length < 2) return '';
    if (points.length < 3) {
        return `M ${points[0][0]} ${points[0][1]} L ${points[1][0]} ${points[1][1]}`;
    }
    const tension = 0.18;
    let d = `M ${points[0][0]} ${points[0][1]}`;
    for (let i = 0; i < points.length - 1; i++) {
        const p0 = points[i - 1] || points[i];
        const p1 = points[i];
        const p2 = points[i + 1];
        const p3 = points[i + 2] || p2;
        const cp1x = p1[0] + (p2[0] - p0[0]) * tension;
        const cp1y = p1[1] + (p2[1] - p0[1]) * tension;
        const cp2x = p2[0] - (p3[0] - p1[0]) * tension;
        const cp2y = p2[1] - (p3[1] - p1[1]) * tension;
        d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2[0]} ${p2[1]}`;
    }
    return d;
}

function ActiveChart({ history, colors }) {
    if (!history || history.length < 2) {
        return <ChartHint>(chart available after more data is collected)</ChartHint>;
    }
    const width = 440, height = 160;
    const padding = { top: 18, right: 14, bottom: 22, left: 34 };
    const innerW = width - padding.left - padding.right;
    const innerH = height - padding.top - padding.bottom;
    const counts = history.map(h => h.active_count);
    const maxVal = Math.max(...counts, 1);

    const points = history.map((h, i) => {
        const x = padding.left + (i / (history.length - 1)) * innerW;
        const y = padding.top + innerH - (h.active_count / maxVal) * innerH;
        return [x, y];
    });

    const linePath = smoothPath(points);
    const areaPath = `${linePath} L ${padding.left + innerW} ${padding.top + innerH} L ${padding.left} ${padding.top + innerH} Z`;

    const gridLines = 3;

    return (
        <>
            <ChartContainer>
                <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                    <defs>
                        <linearGradient id="chart-area" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={colors.stroke} stopOpacity="0.45" />
                            <stop offset="100%" stopColor={colors.stroke} stopOpacity="0" />
                        </linearGradient>
                    </defs>

                    {/* Horizontal grid lines */}
                    {Array.from({ length: gridLines }).map((_, i) => {
                        const y = padding.top + (innerH / (gridLines - 1)) * i;
                        return (
                            <line
                                key={i}
                                x1={padding.left}
                                y1={y}
                                x2={width - padding.right}
                                y2={y}
                                stroke={colors.grid}
                                strokeWidth="1"
                                strokeDasharray={i === gridLines - 1 ? "0" : "3 4"}
                            />
                        );
                    })}

                    {/* Y-axis labels */}
                    <text x={padding.left - 6} y={padding.top + 3} textAnchor="end" fill={colors.axisLabel} fontSize="9" fontFamily="Monaco, Menlo, monospace">{maxVal}</text>
                    <text x={padding.left - 6} y={padding.top + innerH + 3} textAnchor="end" fill={colors.axisLabel} fontSize="9" fontFamily="Monaco, Menlo, monospace">0</text>

                    {/* Area fill */}
                    <path d={areaPath} fill="url(#chart-area)" />

                    {/* Line */}
                    <path
                        d={linePath}
                        fill="none"
                        stroke={colors.stroke}
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                    />

                    {/* Data points */}
                    {points.map(([x, y], i) => (
                        <g key={i}>
                            <circle cx={x} cy={y} r="3.5" fill={colors.bg} stroke={colors.stroke} strokeWidth="1.6" />
                        </g>
                    ))}
                </ChartSvg>
            </ChartContainer>
            <ChartLabel>
                <span>{history[0].week}</span>
                <span>{history[history.length - 1].week}</span>
            </ChartLabel>
        </>
    );
}

/* -------------------------------------------------------------------------- */
/* Referral rows                                                              */
/* -------------------------------------------------------------------------- */

const List = styled.div`
    display: flex;
    flex-direction: column;
`;

const Row = styled.div`
    display: flex;
    align-items: center;
    gap: 0.85rem;
    padding: 0.7rem 1rem;
    background: transparent;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    transition: background-color 0.15s ease;

    ${({ $clickable }) => $clickable && `cursor: pointer;`}

    &:hover {
        background: ${({ $clickable, theme }) => ($clickable ? theme.colors.hoverBg : 'transparent')};
    }

    &:last-child { border-bottom: none; }

    @media (max-width: 600px) {
        padding: 0.6rem 0;
        gap: 0.6rem;
    }
`;

const RankChip = styled.span`
    flex-shrink: 0;
    width: 22px;
    text-align: center;
    color: ${({ theme, $rank }) => {
        if ($rank === 1) return '#FFD24A';
        if ($rank === 2) return '#C7CCD3';
        if ($rank === 3) return '#E0996A';
        return theme.colors.subtleText;
    }};
    font-size: 0.7rem;
    font-weight: 700;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    line-height: 1;

    @media (max-width: 480px) {
        display: none;
    }
`;

const AvatarWrap = styled.div`
    position: relative;
    flex-shrink: 0;
    width: 40px;
    height: 40px;
`;

/**
 * Referral leaderboard avatar — wraps the shared `UserAvatar` so the
 * dicebear bg color + 20% inner padding are consistent with the rest
 * of the app. Active rows get the green `voteUp` ring via the
 * `activeBorderColor` prop on `UserAvatar`.
 */
const AvatarImg = ({ $active, src: _src, ...rest }) => {
    const theme = useTheme();
    return (
        <UserAvatar
            size={40}
            activeBorderColor={$active ? theme.colors.voteUp : undefined}
            {...rest}
        />
    );
};

const AvatarFallback = styled.span`
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: ${({ theme }) => theme.colors.surface2};
    border: 2px solid ${({ $active, theme }) =>
        $active ? theme.colors.voteUp : theme.colors.border};
    color: ${({ theme }) => theme.colors.subtleText};
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.7rem;
    font-weight: 600;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    box-sizing: border-box;
`;

const ActiveDot = styled.span`
    position: absolute;
    right: -1px;
    bottom: -1px;
    width: 11px;
    height: 11px;
    border-radius: 50%;
    background: ${({ theme }) => theme.colors.voteUp};
    border: 2px solid ${({ theme }) => theme.colors.bg};
    box-sizing: border-box;
`;

const Identity = styled.div`
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
`;

const IdentityTitle = styled(Link)`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.82rem;
    font-weight: 400;
    line-height: 1.25;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-decoration: none;

    &:hover { color: ${({ theme }) => theme.colors.link}; }
`;

const IdentityTitlePlain = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.82rem;
    font-weight: 400;
    line-height: 1.25;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    opacity: 0.75;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const IdentityMeta = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.3;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;

    & > span { display: inline-flex; align-items: center; gap: 0.22rem; }

    strong {
        color: ${({ theme }) => theme.colors.text};
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    }

    em {
        font-style: normal;
        color: ${({ theme }) => theme.colors.borderStrong};
    }
`;

const StatusBadge = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.22rem 0.5rem;
    border-radius: 999px;
    font-size: 0.55rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    white-space: nowrap;
    flex-shrink: 0;

    ${({ $active, theme }) => $active
        ? `
            background: ${theme.colors.buttonSuccessBg};
            color: ${theme.colors.voteUp};
            border: 1px solid ${theme.colors.buttonSuccessBorder};
          `
        : `
            background: transparent;
            color: ${theme.colors.subtleText};
            border: 1px solid ${theme.colors.border};
          `}
`;

const StatusDot = styled.span`
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: currentColor;
    display: inline-block;
`;

/* -------------------------------------------------------------------------- */
/* State blocks                                                               */
/* -------------------------------------------------------------------------- */

const StateBlock = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.65rem;
    padding: 2.5rem 1.25rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const StateIcon = styled.div`
    width: 48px;
    height: 48px;
    border-radius: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: ${({ $tone, theme }) =>
        $tone === 'danger' ? theme.colors.buttonDangerBg : `${theme.colors.gradientStart}1a`};
    border: 1px solid ${({ $tone, theme }) =>
        $tone === 'danger' ? theme.colors.buttonDangerBorder : `${theme.colors.gradientStart}33`};

    svg {
        width: 22px;
        height: 22px;
        color: ${({ $tone, theme }) =>
        $tone === 'danger' ? theme.colors.voteDown : theme.colors.gradientStart};
    }
`;

const StateTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.95rem;
    font-weight: 700;
`;

const StateMessage = styled.div`
    font-size: 0.72rem;
    font-weight: 500;
    line-height: 1.5;
    max-width: 24rem;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const LoadingSpinner = styled.div`
    width: 26px;
    height: 26px;
    border: 3px solid ${({ theme }) => theme.colors.border};
    border-top: 3px solid ${({ theme }) => theme.colors.focusBlue};
    border-radius: 50%;
    animation: spin 0.8s linear infinite;

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;

/* -------------------------------------------------------------------------- */
/* Shell component                                                            */
/* -------------------------------------------------------------------------- */

function ReferralsPageShell({ title, aside, children }) {
    return (
        <ContentGrid>
            <Helmet>
                <title>{title}</title>
            </Helmet>
            <ModernPostFeed>
                <CappedPageColumn>
                    <ReferralsTabbedContainer>
                        <ReferralsShellBody>
                            <ReferralsWrap>
                                <HeaderRow>
                                    <HeaderTitle>Referrals</HeaderTitle>
                                    {aside ? <HeaderAside>{aside}</HeaderAside> : null}
                                </HeaderRow>
                                <SectionDivider />
                                {children}
                            </ReferralsWrap>
                        </ReferralsShellBody>
                    </ReferralsTabbedContainer>
                </CappedPageColumn>
            </ModernPostFeed>
        </ContentGrid>
    );
}

function shorten(addr) {
    if (!addr) return '';
    return addr.length > 14 ? `${addr.slice(0, 8)}…${addr.slice(-4)}` : addr;
}

/* -------------------------------------------------------------------------- */
/* Route                                                                      */
/* -------------------------------------------------------------------------- */

function ReferralsView({ state }) {
    const navigate = useNavigate();
    const theme = useTheme();
    const { address: urlAddress } = useParams();
    const [weekMenuOpen, setWeekMenuOpen] = useState(false);
    const weekMenuRef = useRef(null);
    const weekButtonRef = useRef(null);

    useEffect(() => {
        if (!weekMenuOpen) return undefined;
        const onDocClick = (e) => {
            if (weekMenuRef.current?.contains(e.target)) return;
            if (weekButtonRef.current?.contains(e.target)) return;
            setWeekMenuOpen(false);
        };
        const onKey = (e) => { if (e.key === 'Escape') setWeekMenuOpen(false); };
        document.addEventListener('mousedown', onDocClick);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDocClick);
            document.removeEventListener('keydown', onKey);
        };
    }, [weekMenuOpen]);

    const hook = useReferrals({ state, targetAddress: urlAddress });

    const {
        username,
        effectiveAddress,
        isOwnReferrals,
        week,
        setWeek,
        data,
        referrals,
        hasMore,
        loading,
        loadingMore,
        error,
        copied,
        shareUrl,
        handleLoadMore,
        handleCopy,
        referralPrecheckEnabled,
        referralPrecheckBusy,
        referralPrecheckError,
        referralPrecheckSuccess,
        inviteCodesRequired,
        handleReferralPrecheckToggle,
    } = hook;

    const history = Array.isArray(data?.active_history) ? data.active_history : [];
    const selectedWeek = history.find(h => h.week === week);
    const weekRange = selectedWeek ? formatWeekRange(selectedWeek.week_start, selectedWeek.week_end) : '';
    const weekOptions = history.length ? [...history].reverse().map(item => ({
        value: item.week,
        range: formatWeekRange(item.week_start, item.week_end),
    })) : [{ value: week, range: '' }];
    const minWeek = history[0]?.week;
    const maxWeek = history[history.length - 1]?.week;
    const canPrev = minWeek ? compareISOWeeks(week, minWeek) > 0 : true;
    const canNext = maxWeek ? compareISOWeeks(week, maxWeek) < 0 : true;

    const handlePrevWeek = () => {
        const next = shiftISOWeek(week, -1);
        if (next) setWeek(next);
    };
    const handleNextWeek = () => {
        const next = shiftISOWeek(week, 1);
        if (next) setWeek(next);
    };

    const totalReferred = data?.total ?? referrals.length ?? 0;
    const activeCount = data?.active_count ?? 0;
    const inactiveCount = Math.max(0, totalReferred - activeCount);
    const activePct = totalReferred > 0
        ? Math.min(100, Math.round((activeCount / totalReferred) * 100))
        : 0;

    const pageTitle = isOwnReferrals
        ? 'Referrals | Mirage'
        : `Referrals for ${shorten(effectiveAddress)} | Mirage`;
    const asideLabel = !isOwnReferrals && effectiveAddress ? shorten(effectiveAddress) : null;

    /* --- Not signed in ----------------------------------------------------- */

    if (!effectiveAddress) {
        return (
            <ReferralsPageShell title={pageTitle}>
                <StateBlock>
                    <StateIcon><HiUsers /></StateIcon>
                    <StateTitle>Sign in to view your referrals</StateTitle>
                    <StateMessage>Once you're signed in you'll see your share link, weekly activity, and every person you've referred.</StateMessage>
                </StateBlock>
            </ReferralsPageShell>
        );
    }

    /* --- Shell body -------------------------------------------------------- */

    const hasReferralData = referrals.length > 0 || (data?.total ?? 0) > 0;
    const showEmpty = !loading && !error && !hasReferralData;

    return (
        <ReferralsPageShell title={pageTitle} aside={asideLabel}>
            {error && <ErrorBanner>{error}</ErrorBanner>}

            {/* Hero share card — only for own referrals */}
            {isOwnReferrals && (
                <Section>
                    <SectionBody style={{ paddingTop: '0.85rem' }}>
                        <HeroCard>
                            <HeroTopRow>
                                <HeroEyebrow>Invite & earn</HeroEyebrow>
                                {inviteCodesRequired && !referralPrecheckEnabled ? (
                                    <HeroBadge $tone="danger" title="Your referral link is turned off">
                                        Link off
                                    </HeroBadge>
                                ) : (
                                    totalReferred > 0 && (
                                        <HeroBadge>
                                            <HiUserGroup style={{ width: '0.7rem', height: '0.7rem' }} />
                                            {totalReferred} invited
                                        </HeroBadge>
                                    )
                                )}
                            </HeroTopRow>

                            <HeroTextStack>
                                <HeroTitle>Bring your users to Mirage.</HeroTitle>
                                <HeroSubtitle>
                                    {inviteCodesRequired && !referralPrecheckEnabled
                                        ? "Your referral link is currently off — turn it on below to let users sign up through it."
                                        : "Share your link — when they sign up, they appear here and you'll see their weekly activity at a glance."}
                                </HeroSubtitle>
                            </HeroTextStack>

                            {username && shareUrl ? (
                                <ShareLinkPill $disabled={inviteCodesRequired && !referralPrecheckEnabled}>
                                    <ShareUrl
                                        value={shareUrl}
                                        readOnly
                                        onClick={e => e.target.select()}
                                        aria-label="Referral share link"
                                    />
                                    <CopyIconButton
                                        type="button"
                                        $copied={copied}
                                        onClick={handleCopy}
                                        aria-label={copied ? 'Copied' : 'Copy share link'}
                                        title={copied ? 'Copied!' : 'Copy link'}
                                    >
                                        {copied ? <HiCheck /> : <HiClipboardDocument />}
                                    </CopyIconButton>
                                </ShareLinkPill>
                            ) : (
                                <HeroEmpty>
                                    {username
                                        ? 'Your share link will appear here once an invite code is available.'
                                        : 'Set a username to generate your referral share link.'}
                                </HeroEmpty>
                            )}
                            {inviteCodesRequired && (
                                <>
                                    <ToggleRow>
                                        <ToggleText>
                                            <ToggleLabel>Enable referral links</ToggleLabel>
                                            <ToggleDesc>
                                                Lets users sign up via your personal link instead of
                                                sharing invite codes directly.
                                            </ToggleDesc>
                                        </ToggleText>
                                        <Toggle
                                            checked={referralPrecheckEnabled}
                                            disabled={referralPrecheckBusy}
                                            onChange={e => handleReferralPrecheckToggle(!!e.target.checked)}
                                        />
                                    </ToggleRow>
                                    {referralPrecheckError && (
                                        <ToggleFeedback $tone="error">{referralPrecheckError}</ToggleFeedback>
                                    )}
                                    {referralPrecheckSuccess && (
                                        <ToggleFeedback $tone="success">✓ {referralPrecheckSuccess}</ToggleFeedback>
                                    )}
                                </>
                            )}
                        </HeroCard>
                    </SectionBody>
                </Section>
            )}

            {/* Week controls */}
            <Section>
                <SectionHeader>
                    <SectionHeaderLabel>Week</SectionHeaderLabel>
                    {weekRange && <MutedNote>{weekRange}</MutedNote>}
                </SectionHeader>
                <SectionBody>
                    <WeekSegment>
                        <WeekNavButton onClick={handlePrevWeek} disabled={!canPrev} type="button" aria-label="Previous week">
                            <HiChevronLeft />
                            Prev
                        </WeekNavButton>
                        <WeekDivider />
                        <WeekSelectWrap>
                            <WeekMenuButton
                                ref={weekButtonRef}
                                type="button"
                                aria-haspopup="listbox"
                                aria-expanded={weekMenuOpen}
                                aria-label="Select week"
                                onClick={() => setWeekMenuOpen(v => !v)}
                            >
                                {week}
                                <HiChevronDown />
                            </WeekMenuButton>
                            {weekMenuOpen && (
                                <WeekMenuPopover ref={weekMenuRef} role="listbox">
                                    {weekOptions.map(option => (
                                        <WeekMenuItem
                                            key={option.value}
                                            type="button"
                                            role="option"
                                            aria-selected={option.value === week}
                                            $active={option.value === week}
                                            onClick={() => {
                                                setWeek(option.value);
                                                setWeekMenuOpen(false);
                                            }}
                                        >
                                            {option.range ? `${option.value} (${option.range})` : option.value}
                                        </WeekMenuItem>
                                    ))}
                                </WeekMenuPopover>
                            )}
                        </WeekSelectWrap>
                        <WeekDivider />
                        <WeekNavButton onClick={handleNextWeek} disabled={!canNext} type="button" aria-label="Next week">
                            Next
                            <HiChevronRight />
                        </WeekNavButton>
                    </WeekSegment>
                    <ControlsMeta>
                        <MutedNote>UTC weeks (Mon–Sun)</MutedNote>
                    </ControlsMeta>
                </SectionBody>
            </Section>

            {/* Stats tiles */}
            <Section>
                <SectionHeader>
                    <SectionHeaderLabel>Overview</SectionHeaderLabel>
                </SectionHeader>
                <SectionBody>
                    <StatsRow>
                        <StatTile $tone="brand">
                            <StatHead>
                                <StatLabel>Total referred</StatLabel>
                                <StatIcon $tone="brand"><HiUserGroup /></StatIcon>
                            </StatHead>
                            <StatValue>{totalReferred}</StatValue>
                            <StatSubLabel>All-time referrals</StatSubLabel>
                        </StatTile>

                        <StatTile $tone="success">
                            <StatHead>
                                <StatLabel>Active this week</StatLabel>
                                <StatIcon $tone="success"><HiBolt /></StatIcon>
                            </StatHead>
                            <StatValue>{activeCount}</StatValue>
                            <ProgressTrack>
                                <ProgressFill $pct={activePct} />
                            </ProgressTrack>
                            <StatSubLabel>{activePct}% active rate</StatSubLabel>
                        </StatTile>

                        <StatTile>
                            <StatHead>
                                <StatLabel>Inactive</StatLabel>
                                <StatIcon><HiClock /></StatIcon>
                            </StatHead>
                            <StatValue>{inactiveCount}</StatValue>
                            <StatSubLabel>Haven't met activity threshold</StatSubLabel>
                        </StatTile>
                    </StatsRow>
                    <ActiveInfo>
                        <HiArrowTrendingUp />
                        {data?.active_definition || 'Active = 10+ posts or comments in the week.'}
                    </ActiveInfo>
                </SectionBody>
            </Section>

            {/* Activity chart */}
            {history.length > 1 && (
                <Section>
                    <SectionHeader>
                        <SectionHeaderLabel>Weekly activity</SectionHeaderLabel>
                    </SectionHeader>
                    <SectionBody>
                        <ChartCard>
                            <ChartTopRow>
                                <ChartLegend>Active referrals</ChartLegend>
                                <ChartHint>Last {history.length} weeks</ChartHint>
                            </ChartTopRow>
                            <ActiveChart
                                history={history}
                                colors={{
                                    stroke: theme.colors.link,
                                    grid: theme.colors.borderSubtle || theme.colors.border,
                                    bg: theme.colors.bg,
                                    axisLabel: theme.colors.subtleText,
                                }}
                            />
                        </ChartCard>
                    </SectionBody>
                </Section>
            )}

            {/* Referrals list */}
            <Section>
                <SectionHeader>
                    <SectionHeaderLabel>Referrals</SectionHeaderLabel>
                    {referrals.length > 0 && (
                        <MutedNote>
                            {referrals.length}{hasMore ? '+' : ''} shown
                        </MutedNote>
                    )}
                </SectionHeader>
                {loading ? (
                    <StateBlock role="status" aria-live="polite">
                        <LoadingSpinner />
                        <StateTitle>Loading referrals…</StateTitle>
                    </StateBlock>
                ) : error ? (
                    <StateBlock>
                        <StateIcon $tone="danger"><HiExclamationTriangle /></StateIcon>
                        <StateTitle>Couldn't load referrals</StateTitle>
                        <StateMessage>{error}</StateMessage>
                    </StateBlock>
                ) : showEmpty ? (
                    <StateBlock>
                        <StateIcon><HiUsers /></StateIcon>
                        <StateTitle>{isOwnReferrals ? 'No referrals yet' : 'No referrals found'}</StateTitle>
                        <StateMessage>
                            {isOwnReferrals
                                ? 'Share your link above to start earning referral activity.'
                                : 'This address has not referred anyone yet.'}
                        </StateMessage>
                    </StateBlock>
                ) : (
                    <ListSectionBody>
                        <List>
                            {referrals.map((r, idx) => {
                                const isActive = !!r.active;
                                const hasUsername = !!r.username;
                                const userUrl = hasUsername ? `/u/${r.username}` : null;
                                const rowClick = userUrl
                                    ? e => {
                                        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
                                        if (e.target.closest('a')) return;
                                        navigate(userUrl);
                                    }
                                    : undefined;
                                // Seed dicebear on the bech32 address —
                                // stable across username changes and
                                // consistent with every other avatar
                                // surface in the app.
                                const avatarSeed = r.address;
                                const rank = idx + 1;
                                return (
                                    <Row
                                        key={r.address}
                                        $clickable={!!userUrl}
                                        onClick={rowClick}
                                    >
                                        <RankChip $rank={rank}>
                                            {rank <= 3 ? <HiTrophy style={{ width: '0.85rem', height: '0.85rem' }} /> : `#${rank}`}
                                        </RankChip>
                                        <AvatarWrap>
                                            {avatarSeed ? (
                                                <AvatarImg
                                                    seed={avatarSeed}
                                                    alt=""
                                                    $active={isActive}
                                                />
                                            ) : (
                                                <AvatarFallback $active={isActive}>?</AvatarFallback>
                                            )}
                                            {isActive && <ActiveDot title="Active this week" />}
                                        </AvatarWrap>
                                        <Identity>
                                            {hasUsername ? (
                                                <IdentityTitle to={userUrl} onClick={e => e.stopPropagation()}>
                                                    @{r.username}
                                                </IdentityTitle>
                                            ) : (
                                                <IdentityTitlePlain title={r.address}>
                                                    {shorten(r.address)}
                                                </IdentityTitlePlain>
                                            )}
                                            <IdentityMeta>
                                                <span><strong>{r.total_actions}</strong> actions</span>
                                                <em>·</em>
                                                <span><strong>{r.posts}</strong> posts</span>
                                                <em>·</em>
                                                <span><strong>{r.comments}</strong> comments</span>
                                            </IdentityMeta>
                                        </Identity>
                                        <StatusBadge $active={isActive}>
                                            <StatusDot />
                                            {isActive ? 'Active' : 'Inactive'}
                                        </StatusBadge>
                                    </Row>
                                );
                            })}
                        </List>
                        {hasMore && (
                            <ShowMoreButton onClick={handleLoadMore} loading={loadingMore}>
                                Show more
                            </ShowMoreButton>
                        )}
                    </ListSectionBody>
                )}
            </Section>

        </ReferralsPageShell>
    );
}

export default ReferralsView;
