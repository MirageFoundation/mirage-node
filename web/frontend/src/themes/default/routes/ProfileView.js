import React, { useCallback, useEffect, useRef, useState } from "react";
import { Helmet } from "react-helmet-async";
import styled, { useTheme } from "styled-components";
import { HiChevronRight, HiShare, HiGift, HiPencilSquare, HiClipboardDocument, HiCheck } from "react-icons/hi2";
import { HiHashtag } from "react-icons/hi2";
import Button from "../components/Button.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, CappedPageColumn } from "../Layout";
import { ProfileHeaderSkeleton, FeedCardSkeletonList, FeedCardSkeleton, ListRowSkeletonList, ListRowSkeleton } from "../components/Skeleton.js";
import { tooltipStyles } from "../components/Tooltip.js";
import { GiftMirageDialog, GiftSubscriptionDialog } from "../components/GiftDialogs.js";
import { useProfile } from "../../../logic/useProfile";
import { useBlocks } from "../../../logic/useBlocks";
import useBalance from "../../../logic/useBalance.js";
import { formatMirageCompact } from "../../../utils/formatters";
import { FeedViewToggle, loadViewMode, saveViewMode } from "../ListFeedView.js";
import UserAvatar from "../components/UserAvatar.js";
import { getAuthorColor } from "../../../utils/tierColors";
import { Link, useParams } from "react-router-dom";
import MarkdownRenderer from "../components/MarkdownRenderer";
import Storage from "../../../utils/Storage";
import LoggedOutPromptCard from "../components/LoggedOutPromptCard.js";
import { getCachedWelcomeStats } from "../../../utils/welcomeStatsCache";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import Api from "../../../utils/api";
import Tooltip from "../components/Tooltip.js";
import { AWARD_TYPES } from "../../../logic/usePostGifts";

/** Compact MIRAGE balance for the right-aside stats grid + main profile rows
 *  (e.g. `1.2K MIRAGE`). `formatMirageCompact` returns a lowercase suffix
 *  (`k`/`m`/`b`) by default; we uppercase the suffix here so it matches the
 *  rest of default's UPPERCASE MIRAGE label. */
const compactMirageLabel = (raw) => {
    if (raw === null || raw === undefined) return '—';
    const compact = formatMirageCompact(raw);
    if (!compact) return '—';
    const uppercased = compact.replace(/([kmb])(\b|$)/gi, (_, s) => s.toUpperCase());
    return `${uppercased} MIRAGE`;
};

/** Mirrors mirage-mobile-app's `formatAccountAge` (min / hr / d / mo / yr). */
const formatAccountAge = (createdAt) => {
    const ts = Number(createdAt);
    if (!Number.isFinite(ts) || ts <= 0) return '—';
    const nowSec = Date.now() / 1000;
    const ageSec = nowSec - ts;
    const days = ageSec / (60 * 60 * 24);
    const hours = ageSec / 3600;
    const minutes = ageSec / 60;
    if (minutes < 1) return '—';
    if (hours < 1) return `${Math.floor(minutes)}min`;
    if (days < 1) return `${Math.floor(hours)}hr`;
    if (days < 30) return `${Math.floor(days)}d`;
    if (days < 365) return `${Math.floor(days / 30)}mo`;
    return `${Math.floor(days / 365)}yr`;
};
/** Long-form age used by the profile details `Registered:` row. */
const formatAccountAgeLong = (createdAt) => {
    const ts = Number(createdAt);
    if (!Number.isFinite(ts) || ts <= 0) return '—';
    const nowSec = Date.now() / 1000;
    const ageSec = nowSec - ts;
    const days = ageSec / (60 * 60 * 24);
    const hours = ageSec / 3600;
    const minutes = ageSec / 60;
    const pluralize = (value, unit) => `${value} ${unit}${value === 1 ? '' : 's'} ago`;
    if (minutes < 1) return '—';
    if (hours < 1) return pluralize(Math.floor(minutes), 'minute');
    if (days < 1) return pluralize(Math.floor(hours), 'hour');
    if (days < 30) return pluralize(Math.floor(days), 'day');
    if (days < 365) return pluralize(Math.floor(days / 30), 'month');
    return pluralize(Math.floor(days / 365), 'year');
};
/** Matches `SettingsView::SettingLabel` — primary text color, 0.72rem / 500. */
const Label = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-weight: 500;
    font-size: 0.72rem;
    line-height: 1.3;
    white-space: nowrap;
    flex-shrink: 0;
    @media (max-width: 1000px) {
        margin-bottom: 0.1rem;
    }
`;
const HoverableLabel = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-weight: 500;
    font-size: 0.72rem;
    line-height: 1.3;
    white-space: nowrap;
    flex-shrink: 0;
    ${tooltipStyles()}

    @media (max-width: 1000px) {
        margin-bottom: 0.1rem;
    }
`;
const BioTextarea = styled.textarea`
    width: 100%;
    box-sizing: border-box;
    background-color: ${({ theme }) => theme.colors.bg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    padding: 0.6rem 0.75rem;
    color: ${({ theme }) => theme.colors.text};
    font-family: inherit;
    font-size: 0.72rem;
    font-weight: 500;
    line-height: 1.4;
    resize: vertical;
    min-height: 80px;
    &::placeholder { color: ${({ theme }) => theme.colors.subtleText}; }
    &:hover:not(:disabled) { border-color: ${({ theme }) => theme.colors.borderStrong}; }
    &:focus { outline: none; border-color: ${({ theme }) => theme.colors.borderStrong}; box-shadow: none; }
`;

/** Compact pill button used inside the bio editor (Cancel / Save). Full-radius
 *  + reduced height. Save variant matches `CreatePostView::PostBtn` exactly —
 *  `followBtnBg` filled pill with `followBtnBgHover` on hover, white text, and
 *  a matching border so the pill keeps its outline in both light and dark
 *  modes. Ghost (Cancel) stays transparent with a neutral border. */
const BioPillButton = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 26px;
    padding: 0 14px;
    border-radius: 9999px;
    border: 1px solid ${({ $variant, theme }) => ($variant === 'ghost' ? theme.colors.border : theme.colors.followBtnBg)};
    background: ${({ $variant, theme }) => ($variant === 'ghost' ? 'transparent' : theme.colors.followBtnBg)};
    color: ${({ $variant, theme }) => ($variant === 'ghost' ? theme.colors.text : '#ffffff')};
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease;

    &:hover:not(:disabled) {
        background: ${({ $variant, theme }) => ($variant === 'ghost' ? theme.colors.hoverBg : theme.colors.followBtnBgHover)};
        border-color: ${({ $variant, theme }) => ($variant === 'ghost' ? theme.colors.borderStrong : theme.colors.followBtnBgHover)};
    }

    &:disabled { cursor: not-allowed; opacity: 0.55; }
    &:focus { outline: none; }
    &:focus-visible { box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.borderStrong}; }
`;
const FilterSelect = styled.select`
    width: 100%;
    margin-bottom: ${({
    theme
}) => theme.layout.inputMarginBottom};
    background-color: ${({
    theme
}) => theme.colors.bg};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    padding: ${({
    theme
}) => theme.layout.inputPadding};
    color: ${({
    theme
}) => theme.colors.text};
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
    transition: border-color 0.2s ease;

    &:hover:not(:disabled) { border-color: ${({ theme }) => theme.colors.borderStrong}; }
    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.borderStrong};
        box-shadow: none;
    }
`;
const PostsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: ${({
    theme
}) => theme.layout.cardGap};
`;
const PostItem = styled.a`
    display: block;
    text-decoration: none;
    color: inherit;
    border: ${({
    theme,
    isActive
}) => theme.layout.cardBorder};
    border-bottom: ${({
    theme
}) => theme.layout.cardBorderBottom};
    background-color: ${({
    theme,
    isActive
}) => isActive ? theme.colors.accentSubtle : theme.layout.cardBg};
    border-radius: ${({
    theme
}) => theme.layout.cardRadius};
    padding: ${({
    theme
}) => theme.layout.cardPadding};
    cursor: pointer;
    transition: background-color 0.2s ease, border-color 0.2s ease;
    box-shadow: ${({
    theme
}) => theme.layout.cardShadow};

    &:hover {
        background-color: ${({
    theme
}) => theme.colors.hoverBg};
        border-color: ${({
    theme
}) => theme.layout.cardHoverBorder};
    }
`;
const PostMeta = styled.div`
    font-size: 0.62rem;
    font-weight: 500;
    color: ${({
    theme
}) => theme.colors.subtleText};
    margin-bottom: 0.25rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
`;
const PostPreview = styled.div`
    font-size: 0.65rem;
    color: ${({
    theme
}) => theme.colors.text};
    line-height: 1.3;
    word-break: break-word;
    white-space: pre-line;
`;
/** Right-side value text. Matches `CardView::Body` — `cardBodyText` color, 0.72rem / 500 (same size as labels). */
const Mono = styled.span`
    color: ${({ theme }) => theme.colors.cardBodyText};
    font-size: 0.72rem;
    font-weight: 500;
    font-family: inherit;
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
`;

// Single-line with ellipsis for short values (e.g., username)
const InlineMono = styled(Mono)`
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
`;
const SubtleMono = styled(Mono)`
    color: ${({
    theme
}) => theme.colors.subtleText};
`;

/** Horizontal inset for content on posts/algo tabs — matches `SettingsWrap` row padding. */
const ProfilePostsTabGutter = styled.div`
    padding: 0 1rem;

    @media (max-width: 600px) {
        padding: 0;
    }
`;

/** No per-row divider. Padding matches `SettingsView::SettingRow` (0.55rem 1rem).
 *  Label column is a FIXED width (110px) so every row's value starts at the
 *  same x coordinate — Username / Address / Tier / Balance / Registered /
 *  Reserve / Biography all line up vertically. The value column takes the
 *  remaining row width via `minmax(0, 1fr)` so long Mono strings (wallet
 *  address, balance, etc.) can shrink/ellipsize without clipping.
 *
 *  Default `gap: 1.5rem` gives a comfortable breathing room on wide desktop.
 *  As the main column narrows (right-aside still visible but shrinking the
 *  main column into intermediate widths where Mono values start to clip), the
 *  `@media (max-width: 1100px)` rule tightens the gap to claw back horizontal
 *  space for the value. A second step at mobile (<1000px) tightens padding.
 *  Row stays a single line in BOTH desktop and mobile (no stack). */
const ProfileFieldRow = styled.div`
    display: grid;
    grid-template-columns: 110px minmax(0, 1fr);
    gap: 1.5rem;
    align-items: start;
    padding: 0.55rem 1rem;
    box-sizing: border-box;
    width: 100%;
    min-width: 0;

    @media (max-width: 1100px) {
        gap: 0.5rem;
    }

    @media (max-width: 1000px) {
        gap: 0.5rem;
        padding: 0.5rem 0.85rem;
    }

    @media (max-width: 600px) {
        padding: 0.5rem 0;
    }
`;

const ProfileFieldValue = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
    min-width: 0;
    flex-wrap: nowrap;
    overflow: hidden;
`;

const ProfileFieldValuePlain = styled.div`
    min-width: 0;
`;

/** Two-column Reddit-style profile layout: main content on the left, identity/settings rail on the right. */
const ProfileGrid = styled.div`
    display: grid;
    grid-template-columns: minmax(0, 1fr) 320px;
    gap: 1.25rem;
    width: 100%;
    max-width: 1200px;
    margin: -0.25rem auto 0;
    padding: 0 1rem;
    box-sizing: border-box;

    @media (max-width: 1000px) {
        grid-template-columns: minmax(0, 1fr);
        gap: 1rem;
        padding: 0;
        margin-top: 0;
    }

    /* Large displays: above ~1500px the shell drops its max-width cap
     * and pins the sidebar to the left viewport edge. margin: auto
     * then centers the grid within Main (which is offset right by the
     * sidebar), not within the viewport. Override with a viewport-
     * relative margin so the grid is centered against the viewport
     * regardless of sidebar state.
     *
     * Offset = sidebar + divider + Main left padding:
     *   sidebar visible: 273px,  sidebar hidden: 33px
     *
     * Sidebar-hidden applied from 1280px (1200 content + 33*2 ≈ 1266).
     * Sidebar-visible needs vw >= 1746, so threshold is 1800px. */
    @media (min-width: 1280px) {
        [data-sidebar-hidden='true'] & {
            margin-left: calc(50vw - 600px - 33px);
            margin-right: auto;
        }
    }

    @media (min-width: 1800px) {
        [data-sidebar-hidden='false'] & {
            margin-left: calc(50vw - 600px - 273px);
            margin-right: auto;
        }
    }
`;

const ProfileMainColumn = styled.div`
    min-width: 0;
`;

const ProfileAside = styled.aside`
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    min-width: 0;

    @media (max-width: 1000px) {
        order: -1;
        padding: 0 0.85rem;
    }

    @media (max-width: 600px) {
        padding: 0;
    }
`;

/** Main-column header: avatar + large display name + `u/handle`. Replaces
 *  the old "Profile" text. Hidden on narrow screens (<1000px) where the
 *  right-aside identity card re-orders above the main column and already
 *  shows the same avatar / name / follow button — no need to repeat. */
const ProfileIdentity = styled.div`
    display: flex;
    align-items: center;
    gap: 0.85rem;
    padding: 0.75rem 1rem 0.6rem;

    @media (max-width: 1000px) {
        display: none;
    }
`;

/** Wraps avatar + name so they hug the left while the action button(s) on the
 *  right of `ProfileIdentity` get pushed to the far edge. */
const ProfileIdentityMain = styled.div`
    display: flex;
    align-items: center;
    gap: 0.85rem;
    min-width: 0;
    flex: 1 1 auto;
`;

/** Right-side actions slot in the profile header (Follow button on other users' profiles). */
const ProfileIdentityActions = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-shrink: 0;
`;

// Profile-header / aside-card dicebear avatar — thin alias around the
// shared `UserAvatar` so the bg color, retina seed, and 20% inner
// padding match every other avatar surface in the app.
const Avatar = ({ $size, src: _src, ...rest }) => (
    <UserAvatar
        size={$size || 64}
        {...rest}
    />
);

const IdentityBlock = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
`;

const DisplayName = styled.div`
    color: ${({ theme, $tierColor }) => $tierColor || theme.colors.text};
    font-size: 1.35rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const Handle = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.82rem;
    font-weight: 500;
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

/** Sidebar identity card. */
const AsideCard = styled.div`
    position: relative;
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
`;

/** Top header banner — uses the app's main Mirage gradient (`gradientStart`
 *  → `gradientEnd`, the indigo→purple ramp shared with quests / new-posts /
 *  feed-type). Same in both light and dark modes so the banner reads as the
 *  brand surface on either canvas. */
const Banner = styled.div`
    position: relative;
    height: 96px;
    background: linear-gradient(135deg,
        ${({ theme }) => theme.colors.gradientStart} 0%,
        ${({ theme }) => theme.colors.gradientEnd} 100%);
`;

const AsideInner = styled.div`
    position: relative;
    z-index: 1;
    padding: 0.7rem 0.85rem 0.85rem;
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
`;

const AsideIdentityRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.55rem;
    margin-top: -28px;
`;

const AsideAvatarWrap = styled.div`
    padding: 3px;
    /* Concentric ring around the circular avatar. */
    border-radius: 50%;
    background: ${({ theme }) => theme.colors.panel};
    flex-shrink: 0;
`;

const AsideNameBlock = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.05rem;
    min-width: 0;
    padding-top: 28px;
`;

const AsideName = styled.div`
    color: ${({ theme, $tierColor }) => $tierColor || theme.colors.text};
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const AsideHandle = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const AsideBio = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.68rem;
    font-weight: 500;
    line-height: 1.35;
    word-break: break-word;
`;

const AsideActions = styled.div`
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
`;

/** Wrapper that only renders its children on screens where the main-column
 *  `ProfileIdentity` header is hidden (≤1000px). Keeps the Unblock pill
 *  from double-appearing on wide layouts — it belongs next to the Follow
 *  button in the aside only when the header isn't there to host it. */
const AsideOnlyWhenHeaderHidden = styled.span`
    display: none;
    @media (max-width: 1000px) {
        display: inline-flex;
    }
`;

/** Wrapper that only renders its children on mobile (≤600px). Used to
 *  surface the Gift Sub pill inside the aside profile card on phones,
 *  where the Tier row's inline Gift Sub button is hidden to save space. */
const MobileOnly = styled.span`
    display: none;
    @media (max-width: 600px) {
        display: inline-flex;
    }
`;

/** Wrapper that hides its children on mobile (≤600px). Used to keep the
 *  inline Gift Sub button on the Tier row on desktop while showing it
 *  inside the aside profile card on phones. */
const HideOnMobile = styled.span`
    display: inline-flex;
    @media (max-width: 600px) {
        display: none;
    }
`;

/** Share button — same visual language as `CardView::ActionPill` (filled `actionIconBg` pill, 32px tall). */
const AsideShareBtn = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    height: 32px;
    padding: 0 12px;
    border-radius: 9999px;
    border: none;
    background: ${({ theme, $success }) => ($success ? theme.colors.buttonSuccessBg : theme.colors.actionIconBg)};
    color: ${({ theme, $success }) => ($success ? theme.colors.voteUp : theme.colors.text)};
    font-family: inherit;
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1;
    cursor: pointer;
    text-decoration: none;
    transition: background 0.12s ease, color 0.12s ease;

    &:hover { background: ${({ theme, $success }) => ($success ? theme.colors.buttonSuccessBg : theme.colors.actionIconHoverBg)}; }
    &:focus { outline: none; }
    &:focus-visible { box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.borderStrong}; }

    svg { width: 14px; height: 14px; fill: currentColor; }
`;

/** Compact Follow button used in the aside identity card and the main profile
 *  header. Solid `followBtnBg` pill in idle / Following states; flips to a
 *  danger outline on hover when already following (so the click target reads
 *  as "Unfollow"). 32px tall — matches `AsideShareBtn`
 *  so the three action pills sit on the same baseline. */
const CompactFollowBtn = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 32px;
    padding: 0 14px;
    border-radius: 9999px;
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: 600;
    line-height: 1;
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;

    border: 1px solid ${({ $danger, $active, theme }) => ($danger
        ? theme.colors.buttonDangerBorder
        : $active
            ? theme.colors.border
            : theme.colors.followBtnBg)};
    background: ${({ $danger, $active, theme }) => ($danger
        ? 'transparent'
        : $active
            ? 'transparent'
            : theme.colors.followBtnBg)};
    color: ${({ $danger, $active, theme }) => ($danger
        ? theme.colors.voteDown
        : $active
            ? theme.colors.text
            : '#ffffff')};

    &:hover:not(:disabled) {
        background: ${({ $danger, $active, theme }) => ($danger
        ? theme.colors.buttonDangerBg
        : $active
            ? theme.colors.hoverBg
            : theme.colors.followBtnBgHover)};
        border-color: ${({ $danger, $active, theme }) => ($danger
        ? theme.colors.buttonDangerBorder
        : $active
            ? theme.colors.borderStrong
            : theme.colors.followBtnBgHover)};
    }

    &:disabled { cursor: not-allowed; opacity: 0.55; }
    &:focus { outline: none; }
    &:focus-visible { box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.borderStrong}; }
`;

/** Compact "Gift Mirage" pill used inline on the Balance row.
 *  Filled brand-blue pill with a small gift icon + label, sized to hug the
 *  label (no forced min-width). Matches the `AsideGiftSubBtn` / `CompactFollowBtn`
 *  32px height so it's visually consistent across Profile surfaces. */
const GiftMirageBtn = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    height: 32px;
    padding: 0 14px;
    border-radius: 9999px;
    border: 1px solid ${({ theme }) => theme.colors.followBtnBg};
    background: ${({ theme }) => theme.colors.followBtnBg};
    color: #ffffff;
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: 600;
    line-height: 1;
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease;

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.followBtnBgHover};
        border-color: ${({ theme }) => theme.colors.followBtnBgHover};
    }
    &:disabled { cursor: not-allowed; opacity: 0.55; }
    &:focus { outline: none; }
    &:focus-visible { box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.borderStrong}; }

    svg { width: 14px; height: 14px; }
`;

/** Label inside `GiftMirageBtn` that collapses to a short form on mobile.
 *  Renders the long label (e.g. "Gift Mirage" / "Gift Sub") on wide
 *  viewports and just "Gift" under the 600px breakpoint, keeping the
 *  pill compact next to inline values like Tier / Balance. */
const GiftBtnLabelFull = styled.span`
    @media (max-width: 600px) { display: none; }
`;
const GiftBtnLabelShort = styled.span`
    display: none;
    @media (max-width: 600px) { display: inline; }
`;

const AsideStatsGrid = styled.div`
    display: grid;
    grid-template-columns: 1fr 1fr;
    row-gap: 0.75rem;
    column-gap: 0.75rem;
    padding-top: 0.25rem;
`;

const AsideStat = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.05rem;
    min-width: 0;
`;

const AsideStatValue = styled.div`
    color: ${({ $color, theme }) => $color || theme.colors.text};
    font-size: 0.72rem;
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -0.01em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const AsideStatLabel = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.58rem;
    font-weight: 500;
    line-height: 1.2;
`;

/** Sidebar section card: header + clickable rows (settings, actions). */
const AsideSectionHeader = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.58rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 0.6rem 0.85rem 0.25rem;
`;

const AsideSettingsList = styled.div`
    display: flex;
    flex-direction: column;
    padding-bottom: 0.3rem;
`;

const AsideSettingRow = styled.button`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    width: 100%;
    padding: 0.45rem 0.85rem;
    background: transparent;
    border: none;
    cursor: pointer;
    text-align: left;
    font-family: inherit;
    color: ${({ theme }) => theme.colors.text};
    transition: background-color 0.15s ease;

    &:hover { background: ${({ theme }) => theme.colors.hoverBg}; }
    &:disabled { cursor: not-allowed; opacity: 0.5; }
`;

const AsideSettingMain = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.08rem;
    min-width: 0;
`;

const AsideSettingLabel = styled.div`
    font-size: 0.68rem;
    font-weight: 600;
    line-height: 1.2;
`;

const AsideSettingHint = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.58rem;
    font-weight: 500;
    line-height: 1.2;
`;

const AsideSettingChev = styled(HiChevronRight)`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.85rem;
    flex-shrink: 0;
`;

/** Sub-tabs — matches `CreatePostView::TabsRow` / `TabButton` exactly (clean underline, no pill).
 *  Uses `margin` (not `padding`) so the border-bottom starts where the active blue indicator starts. */
/** Tabs row styled to match the `ActionPill` cluster on feed post cards (comment / share). */
const TabsRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.25rem 1rem 0.5rem;
    flex-wrap: wrap;

    @media (max-width: 600px) {
        padding: 0.25rem 0 0.5rem;
    }
`;

/** Right-side slot in `TabsRow` — hosts the feed view toggle on the
 *  Submissions tab (mirrors the home-feed toolbar). Pushed to the right
 *  edge with `margin-left: auto` so it stays out of the way even when
 *  the tab buttons wrap on narrow screens. */
const TabsRowRight = styled.div`
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

/** Pill tab — ghost when inactive (transparent), filled on hover + active. Mirrors the `comment`/`share` pills' hover behaviour. */
const TabButton = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    height: 32px;
    padding: 0 12px;
    border-radius: 9999px;
    border: none;
    background: ${({ $active, theme }) => ($active ? theme.colors.actionIconHoverBg : 'transparent')};
    color: ${({ theme }) => theme.colors.text};
    font-family: inherit;
    font-size: 0.62rem;
    font-weight: ${({ $active }) => ($active ? 600 : 500)};
    line-height: 1;
    cursor: pointer;
    transition: background 0.12s ease;

    &:hover:not(:disabled) { background: ${({ $active, theme }) => ($active ? theme.colors.actionIconHoverBg : theme.colors.actionIconBg)}; }

    &:disabled { cursor: not-allowed; opacity: 0.5; }

    &:focus { outline: none; }
    &:focus-visible { box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.borderStrong}; }
`;

const ProfileTabbedContainer = styled(TabbedContainer)`
    margin-top: 0;
`;

const ProfileShellBody = styled(ContainerBody)`
    padding: 0.35rem 0 0.75rem;
    border: none;
    border-radius: 0;
`;

/** Breathing room between the tabs row and the first content block. */
const TabContent = styled.div`
    padding-top: ${({ $flush }) => ($flush ? '0' : '0.4rem')};
`;

/* -------------------------------------------------------------------------- */
/* Algo tab — topic preferences, user preferences, similar users              */
/* -------------------------------------------------------------------------- */

/** Section wrapper — groups a titled header + list of rows. */
const AlgoSection = styled.section`
    display: flex;
    flex-direction: column;
    margin-top: 0.25rem;

    & + & {
        margin-top: 0.9rem;
    }
`;

/** Section head: title + subtitle, count pill on the right. */
const AlgoSectionHead = styled.div`
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.75rem 1rem 0.55rem;

    @media (max-width: 600px) {
        padding: 0.75rem 0 0.55rem;
    }
`;

const AlgoSectionHeadText = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    min-width: 0;
    flex: 1 1 auto;
`;

const AlgoSectionTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    line-height: 1.2;
`;

const AlgoSectionSubtitle = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 500;
    line-height: 1.25;
`;

const AlgoSectionCount = styled.span`
    background: ${({ theme }) => theme.colors.actionIconBg};
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.58rem;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 9999px;
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
`;

/** Algo list — thin divider rules between rows; mobile-app row density. */
const AlgoList = styled.div`
    display: flex;
    flex-direction: column;
    border-top: 1px solid ${({ theme }) => theme.colors.border};
`;

const AlgoRow = styled.a`
    display: flex;
    align-items: center;
    gap: 0.7rem;
    padding: 0.6rem 1rem;
    text-decoration: none;
    color: inherit;
    background: transparent;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    cursor: pointer;
    transition: background-color 0.15s ease;

    &:hover { background: ${({ theme }) => theme.colors.hoverBg}; }

    @media (max-width: 1000px) {
        padding: 0.55rem 0.85rem;
    }

    @media (max-width: 600px) {
        padding: 0.55rem 0;
    }
`;

/** Circular dicebear avatar — thin alias around the shared `UserAvatar`
 *  so the algo-tab list rows pick up the same 20% inner padding /
 *  bg-color as every other dicebear surface in the app. */
const AlgoAvatar = ({ src: _src, ...rest }) => (
    <UserAvatar size={32} {...rest} />
);

/** "#" chip for topic rows — mirrors `FollowsView::TopicIcon` exactly so
 *  topics read consistently with the follows / topics list screens. */
const AlgoTopicChip = styled.span`
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: ${({ theme }) => theme.colors.surface2};
    border: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.subtleText};
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;

    svg {
        width: 16px;
        height: 16px;
    }
`;

const AlgoIdentity = styled.div`
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.12rem;
`;

const AlgoIdentityTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.78rem;
    font-weight: 600;
    line-height: 1.25;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const AlgoIdentityMeta = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 500;
    line-height: 1.25;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const AlgoIdentityMono = styled(AlgoIdentityMeta)`
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
`;

/** Right-hand weight pill — tinted green for positive, red for negative,
 *  neutral for zero. Uses the same up/down vote palette tokens so the
 *  colour language is consistent with post voting. */
const AlgoWeightPill = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 4px 10px;
    border-radius: 9999px;
    background: ${({ $tone, theme }) => (
        $tone === 'up' ? theme.colors.voteUpBg
            : $tone === 'down' ? theme.colors.voteDownBg
                : theme.colors.actionIconBg
    )};
    color: ${({ $tone, theme }) => (
        $tone === 'up' ? theme.colors.voteUp
            : $tone === 'down' ? theme.colors.voteDown
                : theme.colors.subtleText
    )};
    font-size: 0.62rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    flex-shrink: 0;
    letter-spacing: -0.01em;
`;

const AlgoWeightStack = styled.div`
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.15rem;
    flex-shrink: 0;
`;

const AlgoWeightSub = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.55rem;
    font-weight: 500;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    white-space: nowrap;
`;

const AlgoEmpty = styled.div`
    padding: 1rem 1rem;
    color: ${({ theme, $danger }) => ($danger ? theme.colors.voteDown : theme.colors.subtleText)};
    font-size: 0.7rem;
    font-weight: 500;
    text-align: center;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};

    @media (max-width: 1000px) {
        padding: 0.85rem;
    }
`;

/** "show more / show less" pill inside an algo list. Centered, outlined, full-radius. */
const AlgoExpandRow = styled.div`
    display: flex;
    justify-content: center;
    padding: 0.6rem 1rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const AlgoExpandPill = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    height: 28px;
    padding: 0 14px;
    border-radius: 9999px;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: transparent;
    color: ${({ theme }) => theme.colors.subtleText};
    font-family: inherit;
    font-size: 0.65rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
        border-color: ${({ theme }) => theme.colors.borderStrong};
        color: ${({ theme }) => theme.colors.text};
    }

    &:focus { outline: none; }
    &:focus-visible { box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.borderStrong}; }
`;

/** Round icon-only action button for inline row actions (change username, copy address, edit bio).
 *  Same visual language as `CardView::ActionIconChip` (32×32 filled circle).
 *  $success state: green-tinted bg + green tick (used while "Copied!" feedback is showing). */
const IconActionButton = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    padding: 0;
    border-radius: 9999px;
    border: none;
    background: ${({ theme, $success }) => ($success ? theme.colors.buttonSuccessBg : theme.colors.actionIconBg)};
    color: ${({ theme, $danger, $success }) => ($danger ? theme.colors.voteDown : $success ? theme.colors.voteUp : theme.colors.text)};
    cursor: pointer;
    flex-shrink: 0;
    transition: background 0.12s ease, color 0.12s ease;

    &:hover:not(:disabled) { background: ${({ theme, $success }) => ($success ? theme.colors.buttonSuccessBg : theme.colors.actionIconHoverBg)}; }
    &:disabled { cursor: not-allowed; opacity: 0.5; }
    &:focus { outline: none; }
    &:focus-visible { box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.borderStrong}; }

    svg { width: 14px; height: 14px; }
`;

// (no footer actions here; sign out moved to header menu)

/* -------------------------------------------------------------------------- */
/* Comments-tab row                                                            */
/* -------------------------------------------------------------------------- */

/** Simplified list row used for the Comments tab (and only the Comments
 *  tab). Per the user's profile-comments spec the row is:
 *
 *   ┌────┬───────────────────────────────────────────┐
 *   │    │ #topic · @user · time                      │  ← row 1 (header)
 *   │ AV │ title / first-line snippet                 │  ← row 2 (title)
 *   └────┴───────────────────────────────────────────┘
 *
 * The full CardView / CompactRow footer (vote / comment / share pill row)
 * is intentionally dropped here — comments are read-first navigation
 * shortcuts, not action targets. The avatar is half the CompactRow
 * thumbnail size (84 → 42 desktop, 68 → 34 mobile) to match the
 * lighter density of a comment row vs. a post card. */
const CommentRoot = styled.article`
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    padding: 0.5rem 1rem 0.4rem;
    margin: 4px 0;
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid transparent;
    border-radius: 8px;
    position: relative;
    cursor: pointer;
    transition: background-color 0.12s ease;

    &:hover { background: ${({ theme }) => theme.colors.hoverBg}; }

    @media (max-width: 600px) {
        padding: 0.45rem 0 0.35rem;
        border-radius: 6px;
    }
`;

/* Row slot owns the between-row divider so it sits OUTSIDE the card
 * (matches the Submissions tab's `RowSlot` pattern). The card's 4px
 * vertical margin creates breathing room between the hover background
 * and the divider, so hover never visually touches the separator. */
const CommentRowSlot = styled.div`
    position: relative;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};

    &:last-child {
        border-bottom: none;
    }
`;

const CommentHeader = styled.div`
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.2rem 0.3rem;
    min-width: 0;
    font-size: 0.62rem;
    font-weight: 400;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    line-height: 1.2;
`;

const CommentTopicLink = styled(Link)`
    font-weight: 500;
    font-size: 0.62rem;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    text-decoration: none;
    &:hover { color: ${({ theme }) => theme.colors.text}; text-decoration: none; }
`;

const CommentUserLink = styled(Link)`
    color: ${({ theme, $tierColor }) => $tierColor || theme.colors.feedCtrlText};
    font-weight: 500;
    font-size: 0.62rem;
    text-decoration: none;
    &:hover { color: ${({ theme, $tierColor }) => $tierColor || theme.colors.text}; }
`;

const CommentDot = styled.span`
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-size: 0.75rem;
    font-weight: 700;
    line-height: 1;
`;

const CommentTime = styled.span`
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-size: 0.62rem;
    font-weight: 400;
`;

const CommentBody = styled.div`
    display: block;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.72rem;
    font-weight: 500;
    line-height: 1.4;
    word-break: break-word;
    overflow-wrap: anywhere;
    margin-top: 0.05rem;

    /* Tighten default markdown spacing so a reply reads as a compact
     * block, not a full article. Matches the density of the CompactRow
     * expanded body used on home feed. */
    & > *:first-child { margin-top: 0; }
    & > *:last-child { margin-bottom: 0; }
    p { margin: 0.25rem 0; }
    pre { margin: 0.35rem 0; }
    ul, ol { margin: 0.25rem 0; padding-left: 1.2rem; }
`;

function formatCommentAge(ts) {
    if (!Number.isFinite(ts) || ts <= 0) return '';
    const diff = Math.max(0, Math.floor(Date.now() / 1000) - ts);
    if (diff < 60) return `${diff}s`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}d`;
    if (diff < 2592000) return `${Math.floor(diff / 604800)}w`;
    if (diff < 31536000) return `${Math.floor(diff / 2592000)}mo`;
    return `${Math.floor(diff / 31536000)}y`;
}

/** Single comment row. Click anywhere on the row to open the parent
 *  thread (so the user can see the reply in context). Shows the full
 *  reply body with no truncation and no avatar — the header (topic /
 *  user / time) sits above the raw content. */
/* Module-level cache of comment_id -> { title, rootId } so navigating
 * around the Comments tab doesn't refetch the parent chain repeatedly. */
const __profileCommentParentCache = new Map();
const __profileCommentParentInflight = new Map();
/* Tiny concurrency-limited queue so we don't fire one request per
 * visible row (the backend rate-limits and returns 429 under bursts). */
const __PARENT_TITLE_MAX_CONCURRENT = 2;
let __parentTitleActive = 0;
const __parentTitleQueue = [];
function __runNextParentTitle() {
    if (__parentTitleActive >= __PARENT_TITLE_MAX_CONCURRENT) return;
    const job = __parentTitleQueue.shift();
    if (!job) return;
    __parentTitleActive += 1;
    job().finally(() => {
        __parentTitleActive -= 1;
        __runNextParentTitle();
    });
}
function __enqueueParentTitle(task) {
    return new Promise(resolve => {
        __parentTitleQueue.push(() => task().then(resolve));
        __runNextParentTitle();
    });
}

async function __requestParentChainOnce(commentId) {
    // Single attempt with a 429-aware retry (max 3 tries, exponential
    // backoff with jitter). Failures throw so the caller can decide
    // whether to cache an empty placeholder.
    let lastErr = null;
    for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
            const res = await Api.get('get_comment_context', { comment_id: commentId, max_depth: 5 });
            return res;
        } catch (err) {
            lastErr = err;
            const status = err && (err.status || err.code);
            const is429 = status === 429 || /429|rate/i.test(String((err && err.message) || ''));
            if (!is429) throw err;
            const delay = (300 * Math.pow(2, attempt)) + Math.floor(Math.random() * 200);
            await new Promise(r => setTimeout(r, delay));
        }
    }
    throw lastErr || new Error('rate limited');
}

async function fetchParentTitle(commentId) {
    if (!commentId) return null;
    if (__profileCommentParentCache.has(commentId)) {
        return __profileCommentParentCache.get(commentId);
    }
    if (__profileCommentParentInflight.has(commentId)) {
        return __profileCommentParentInflight.get(commentId);
    }
    const p = __enqueueParentTitle(async () => {
        try {
            const res = await __requestParentChainOnce(commentId);
            const chain = Array.isArray(res?.context) ? res.context : [];
            // The raw API returns immediate-parent first → root last.
            // Take the last entry as the root post.
            const root = chain.length > 0 ? chain[chain.length - 1] : null;
            const title = (root && typeof root.title === 'string') ? root.title.trim() : '';
            const rootId = (root && typeof root.post_id === 'string') ? root.post_id : '';
            const entry = { title, rootId };
            __profileCommentParentCache.set(commentId, entry);
            return entry;
        } catch (_) {
            // Don't cache failures permanently — return an empty
            // placeholder so the row falls back to its existing chip,
            // but allow a retry next time the row mounts.
            return { title: '', rootId: '' };
        } finally {
            __profileCommentParentInflight.delete(commentId);
        }
    });
    __profileCommentParentInflight.set(commentId, p);
    return p;
}

function ProfileCommentRow({ post }) {
    const commentId = post && post.post_id ? String(post.post_id) : '';
    const cached = commentId ? __profileCommentParentCache.get(commentId) : null;
    const [parentInfo, setParentInfo] = useState(cached || null);
    const cancelledRef = useRef(false);

    useEffect(() => {
        cancelledRef.current = false;
        if (!commentId) return undefined;
        if (parentInfo) return undefined;
        fetchParentTitle(commentId).then(info => {
            if (!cancelledRef.current) setParentInfo(info);
        });
        return () => {
            cancelledRef.current = true;
        };
    }, [commentId, parentInfo]);

    if (!post || !post.post_id) return null;
    if (post.deleted || post.hidden_client) return null;

    const authorAddress = post.user_id || post.author || '';
    const displayAuthor = (() => {
        if (typeof post.username === 'string' && post.username.trim()) return post.username.trim();
        if (typeof authorAddress === 'string' && authorAddress.length > 0) {
            return `${authorAddress.slice(0, 8)}…`;
        }
        return 'anonymous';
    })();
    const authorColor = getAuthorColor(post.author_level, post.author_is_new);

    let ts = Number(post.timestamp);
    if (!Number.isFinite(ts)) ts = Math.floor(Date.now() / 1000);
    if (ts > 1e12) ts = Math.floor(ts / 1000);

    // Topic resolution: prefer the row's own `topic`, then `root_topic`
    // (parent post's topic). `useProfile.js` synthesizes a `comment-<short>`
    // placeholder when neither is present — we surface that too so every
    // comment row has a topic chip, and the chip links back to the parent
    // thread via the usual `/t/<topic>` route.
    const rawTopic = typeof post.topic === 'string' ? post.topic.trim() : '';
    const rootTopic = typeof post.root_topic === 'string' ? post.root_topic.trim() : '';
    const displayTopic = rawTopic || rootTopic;
    // Suppress the synthesized `comment-<short>` placeholder so it
    // never appears as `#comment-xxxxxxx` when no parent title is
    // available.
    const isSyntheticTopic = /^comment-[0-9a-f]+$/i.test(displayTopic);
    const hasRealTopic = !!displayTopic && !isSyntheticTopic;
    const postId = String(post.post_id);
    const linkTarget = `/p/${postId}`;

    // Parent post title chip — replaces the legacy `#comment-<id>`
    // placeholder. Fetched client-side via `get_comment_context`
    // (cached per comment id). Truncated to 50 chars + ellipsis.
    const rawParentTitle = (parentInfo && typeof parentInfo.title === 'string')
        ? parentInfo.title.trim()
        : '';
    const parentTitle = rawParentTitle.length > 50
        ? `${rawParentTitle.slice(0, 50)}…`
        : rawParentTitle;
    const rootPostId = (parentInfo && typeof parentInfo.rootId === 'string' && parentInfo.rootId.trim())
        ? parentInfo.rootId.trim()
        : '';
    const parentLink = rootPostId ? `/p/${rootPostId}` : linkTarget;

    // Show the full reply body. useProfile.js synthesizes a truncated
    // `title` (first 80 chars + ellipsis) for the FeedRow renderer — we
    // bypass it entirely and read `content` directly so nothing is cut.
    const fullBody = (typeof post.content === 'string' && post.content.trim())
        ? post.content
        : (typeof post.title === 'string' ? post.title : '(reply)');

    return (
        <CommentRowSlot>
            <CommentRoot as={Link} to={linkTarget} role="link" tabIndex={0} style={{ textDecoration: 'none' }}>
                <CommentHeader>
                    {parentTitle ? (
                        <>
                            <CommentTopicLink to={parentLink} onClick={e => e.stopPropagation()}>
                                {parentTitle}
                            </CommentTopicLink>
                            <CommentDot>·</CommentDot>
                        </>
                    ) : hasRealTopic && (
                        <>
                            <CommentTopicLink to={`/t/${encodeURIComponent(displayTopic)}`} onClick={e => e.stopPropagation()}>
                                #{displayTopic}
                            </CommentTopicLink>
                            <CommentDot>·</CommentDot>
                        </>
                    )}
                    <CommentUserLink
                        to={`/u/${encodeURIComponent(post.username || authorAddress)}`}
                        onClick={e => e.stopPropagation()}
                        $tierColor={authorColor}
                    >
                        @{displayAuthor}
                    </CommentUserLink>
                    <CommentDot>·</CommentDot>
                    <CommentTime>{formatCommentAge(ts)}</CommentTime>
                    {Array.isArray(post?.awards) && post.awards.length > 0 && (
                        <>
                            <CommentDot>·</CommentDot>
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.1rem', fontSize: '0.7rem' }} onClick={e => e.stopPropagation()}>
                                {post.awards.map(a => {
                                    const def = AWARD_TYPES.find(t => t.name === a.type);
                                    if (!def) return null;
                                    const cnt = Number(a.count || 0);
                                    return <Tooltip key={a.type} data-tooltip={def.label}>{cnt > 1 ? `${cnt}x` : ''}{def.icon}</Tooltip>;
                                })}
                            </span>
                        </>
                    )}
                </CommentHeader>
                <CommentBody onClick={e => e.stopPropagation()}>
                    <MarkdownRenderer text={fullBody} />
                </CommentBody>
            </CommentRoot>
        </CommentRowSlot>
    );
}

//

/**
 * Logged-out guard — when a visitor without a publicKey lands on
 * `/profile` (e.g. via the mobile bottom-nav Profile tab), there's no
 * own profile to render. Show the same LoggedOutPromptCard used on
 * `/create_post` so the experience matches the large-screen flow
 * instead of rendering an empty shell or redirecting to /signup.
 *
 * `/u/:identity` routes still render normally so anonymous visitors
 * can browse other users' profiles. Hooks that drive the real profile
 * live inside `ProfileViewAuthenticated` so React's rules-of-hooks
 * aren't violated when we short-circuit here.
 */
export default function ProfileView({ state }) {
    const routeParams = useParams();
    const viewerPublicKey = (state && state.publicKey) ? state.publicKey : Storage.load('publicKey', '');
    const viewerIsLoggedIn = !!(viewerPublicKey && viewerPublicKey !== 'guest');
    if (!viewerIsLoggedIn && !routeParams.identity) {
        return (
            <ContentGrid>
                <Helmet>
                    <title>Profile | Mirage</title>
                </Helmet>
                <FeedRailRow $feedViewMode="card">
                    <FeedCol>
                        <ModernPostFeed>
                            <LoggedOutPromptCard
                                role="region"
                                aria-label="Sign in to view your profile"
                                title="Sign in to view your profile"
                                description="Create an account or sign in to see your identity, balance, posts, and settings."
                                stats={getCachedWelcomeStats()}
                                links={[
                                    { label: 'Watch Introduction (YouTube)', href: 'https://www.youtube.com/watch?v=TOvP32ihQ0M', external: true },
                                    { label: 'Learn More', href: 'https://mirage.foundation', external: true },
                                ]}
                                primaryLabel="Create account"
                                secondaryLabel="Sign in"
                            />
                        </ModernPostFeed>
                    </FeedCol>
                </FeedRailRow>
            </ContentGrid>
        );
    }
    return <ProfileViewAuthenticated state={state} />;
}

function ProfileViewAuthenticated({
    state
}) {
    const { caps } = useTheme();
    const profileHideFilterSelect = caps.profileHideFilterSelect;
    const profilePostsFullWidth = caps.profilePostsFullWidth;
    /**
     * Submissions-tab feed view toggle. The home feed owns the same
     * `loadViewMode()` / `saveViewMode()` pair in localStorage, so the
     * two surfaces stay in sync by default. The `key={profileFeedView}`
     * on `FeedComponent` forces `ListFeedView` to remount when the user
     * flips the toggle — `ListFeedView` reads `loadViewMode()` only on
     * mount, so a remount is the cleanest way to pick up the change.
     */
    const [profileFeedView, setProfileFeedView] = useState(() => loadViewMode());
    const handleProfileFeedViewChange = useCallback((next) => {
        setProfileFeedView(next);
        saveViewMode(next);
    }, []);
    /**
     * Share-button copy-to-clipboard feedback. Tries `navigator.clipboard`
     * first (async, requires a secure context) and falls back to a hidden
     * `<textarea> + document.execCommand('copy')` for http contexts /
     * older browsers. Flips the label to "Link copied" for 1.8s so the
     * user gets visible confirmation the click worked.
     */
    const [profileShareCopied, setProfileShareCopied] = useState(false);
    const {
        navigate,
        theme,
        address,
        usernameResolutionError,
        isResolvingUsername,
        routeIdentity,
        profileAddress,
        isOwnProfile,
        VALID_TABS,
        activeTab,
        setActiveTab,
        profileUsesListFeed,
        FeedComponent,
        isPostsTab,
        profileUsername,
        userLevel,
        subscriptionExpiry,
        recentPosts,
        isLoadingRecentPosts,
        recentPostsError,
        activeRecentPost,
        recentPage,
        recentAutoLoading,
        recentPostsFilter,
        setRecentPostsFilter,
        recentBottomSentinelRef,
        addressCopied,
        setAddressCopied,
        isFollowingProfile,
        isFollowInProgress,
        isUnfollowAction,
        followHover,
        setFollowHover,
        myQueuePosition,
        formatStatusForPosition,
        prefsTopics,
        prefsAuthors,
        prefsLoading,
        prefsError,
        prefAuthorUsernames,
        similarUsers,
        similarUsersLoading,
        similarUsersError,
        showAllTopicPrefs,
        setShowAllTopicPrefs,
        showAllAuthorPrefs,
        setShowAllAuthorPrefs,
        showAllSimilarUsers,
        setShowAllSimilarUsers,
        biography,
        followingCount,
        followerCount,
        bioEditing,
        setBioEditing,
        bioDraft,
        setBioDraft,
        bioSaving,
        bioError,
        setBioError,
        bioButtonStatus,
        confirmDonate,
        donateAmountRaw,
        setDonateAmountRaw,
        donateMessage,
        confirmGiftSub,
        giftSubMessage,
        subFeePending,
        subFeeStatus,
        subFeeLabel,
        agentFeeLabel,
        subFeeUmirage,
        agentFeeUmirage,
        handleGiftSub,
        confirmGiftSubAction,
        cancelGiftSub,
        formatPrefWeight,
        hasValidAccount,
        effectivePostsFilter,
        shortenAddress,
        getTierName,
        getTierColor,
        formatSubscriptionExpiry,
        buildMetaLine,
        renderPostPreview,
        handleFollowToggle,
        getPostUrl,
        handleRecentPostClick,
        usernameDisplay,
        balance,
        reserveFunds,
        profileRegisteredAt,
        balanceDisplay,
        reserveDisplay,
        registeredDisplay,
        canEditProfile,
        donatePending,
        donateStatus,
        profileTitle,
        BIO_MAX,
        handleBioSave,
        formatDonateAmount,
        handleDonate,
        confirmDonateAction,
        cancelDonate
    } = useProfile({
        state
    });
    const handleProfileShare = useCallback(async () => {
        const identity = profileUsername || profileAddress;
        if (!identity || typeof window === 'undefined') return;
        const encodedIdentity = encodeURIComponent(identity);
        const url = `${window.location.origin}/u/${encodedIdentity}?ref=${encodedIdentity}`;
        console.debug('[ProfileView] share.copy', { url });
        let ok = false;
        try {
            if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(url);
                ok = true;
            }
        } catch (_) { /* fall through to legacy path */ }
        if (!ok && typeof document !== 'undefined') {
            try {
                const ta = document.createElement('textarea');
                ta.value = url;
                ta.setAttribute('readonly', '');
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                ok = document.execCommand('copy');
                document.body.removeChild(ta);
            } catch (_) { ok = false; }
        }
        if (ok) {
            setProfileShareCopied(true);
            setTimeout(() => setProfileShareCopied(false), 1800);
        }
    }, [profileAddress, profileUsername]);
    /**
     * Unblock affordance — wired to the same `useBlocks` hook BlocksView
     * uses, so any state mutation in this view is reflected in
     * `/blocks` (and vice versa) once the tx settles. Only an Unblock
     * button is exposed here; "Block" remains a header-menu action.
     */
    const {
        blockedUsers,
        isUserPending: isBlockUserPending,
        formatUserStatus: formatBlockUserStatus,
        handleUnblockUser
    } = useBlocks({ state });
    // Viewer's current balance (umirage). Used by the Gift Mirage / Gift
    // Subscription dialogs to show the balance row + guard against
    // insufficient-balance submits. Separate from `balance` returned by
    // `useProfile`, which is the profile being viewed (not the viewer).
    const { displayBalance: viewerBalanceUmirage } = useBalance();
    const profileAddrLower = String(profileAddress || '').trim().toLowerCase();
    const isProfileBlocked = !!profileAddrLower && blockedUsers.some(
        u => String(u || '').trim().toLowerCase() === profileAddrLower
    );
    const isUnblockPending = isProfileBlocked && isBlockUserPending(profileAddrLower);
    const unblockStatus = isProfileBlocked ? formatBlockUserStatus(profileAddrLower) : '';
    const handleUnblockProfile = e => {
        if (!profileAddrLower) return;
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        handleUnblockUser(e, profileAddrLower);
    };
    // Show loading/error states for username resolution
    if (isResolvingUsername || usernameResolutionError) {
        return <ContentGrid>
            <Helmet>
                <title>{routeIdentity ? `@${routeIdentity}` : 'Profile'} | Mirage</title>
            </Helmet>
            <ModernPostFeed>
                <CappedPageColumn>
                    <TabbedContainer>
                        <ContainerBody>
                            {isResolvingUsername ? (
                                <>
                                    <ProfileHeaderSkeleton />
                                    <FeedCardSkeletonList count={3} />
                                </>
                            ) : (
                                <div style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    textAlign: 'center',
                                    padding: '2rem',
                                    gap: '0.5rem',
                                    minHeight: '200px',
                                    color: theme.colors.voteDown,
                                }}>{usernameResolutionError}</div>
                            )}
                        </ContainerBody>
                    </TabbedContainer>
                </CappedPageColumn>
            </ModernPostFeed>
        </ContentGrid>;
    }
    return <ContentGrid>
        <Helmet>
            <title>{profileTitle} | Mirage</title>
        </Helmet>
        <ModernPostFeed>
            <CappedPageColumn>
                <ProfileTabbedContainer>
                    <ProfileShellBody $fullWidth={profilePostsFullWidth && isPostsTab}>
                        <ProfileGrid>
                            <ProfileMainColumn>
                                <ProfileIdentity>
                                    <ProfileIdentityMain>
                                        <Avatar $size={64} seed={profileAddress || profileUsername || routeIdentity} alt={profileUsername ? `${profileUsername} avatar` : 'Profile avatar'} />
                                        <IdentityBlock>
                                            <DisplayName
                                                title={profileUsername}
                                                $tierColor={getAuthorColor(userLevel)}
                                            >{usernameDisplay}</DisplayName>
                                            <Handle>u/{profileUsername || (profileAddress ? shortenAddress(profileAddress) : 'anon')}</Handle>
                                        </IdentityBlock>
                                    </ProfileIdentityMain>
                                    {!isOwnProfile && address && (
                                        <ProfileIdentityActions>
                                            {isProfileBlocked && (
                                                /* Matches the `Button variant="danger"` Unblock
                                                 * used everywhere else (BlocksView rows,
                                                 * BlockedPost/BlockedTopic state). Inline
                                                 * `borderRadius` keeps the pill fully rounded
                                                 * so it lines up with the adjacent Follow pill. */
                                                <Button
                                                    type="button"
                                                    variant="danger"
                                                    size="sm"
                                                    minWidth="5.5rem"
                                                    disabled={isUnblockPending}
                                                    loading={isUnblockPending}
                                                    onClick={handleUnblockProfile}
                                                    style={{ height: '32px', borderRadius: '9999px', paddingTop: 0, paddingBottom: 0 }}
                                                >
                                                    {isUnblockPending ? unblockStatus || 'Processing' : 'Unblock'}
                                                </Button>
                                            )}
                                            <CompactFollowBtn
                                                type="button"
                                                $active={isFollowingProfile && !((isFollowingProfile && followHover) || isUnfollowAction)}
                                                $danger={(isFollowingProfile && followHover) || isUnfollowAction}
                                                onMouseEnter={() => setFollowHover(true)}
                                                onMouseLeave={() => setFollowHover(false)}
                                                disabled={isFollowInProgress}
                                                onClick={handleFollowToggle}
                                            >
                                                {isFollowInProgress ? formatStatusForPosition(myQueuePosition) || 'Processing' : isFollowingProfile ? followHover ? 'Unfollow' : 'Following' : 'Follow'}
                                            </CompactFollowBtn>
                                        </ProfileIdentityActions>
                                    )}
                                </ProfileIdentity>
                                <TabsRow role="tablist" aria-label="Profile sections">
                                    {VALID_TABS.map(tab => <TabButton key={tab} type="button" role="tab" aria-selected={activeTab === tab} $active={activeTab === tab} onClick={() => setActiveTab(tab)}>
                                        {tab.charAt(0).toUpperCase() + tab.slice(1)}
                                    </TabButton>)}
                                    {activeTab === 'submissions' && (
                                        <TabsRowRight>
                                            <FeedViewToggle
                                                viewMode={profileFeedView}
                                                onChange={handleProfileFeedViewChange}
                                            />
                                        </TabsRowRight>
                                    )}
                                </TabsRow>
                                <TabContent $flush={isPostsTab}>
                                    {activeTab === 'profile' && <>
                                        <ProfileFieldRow>
                                            <Label>Username:</Label>
                                            <ProfileFieldValue>
                                                <InlineMono title={profileUsername}>{usernameDisplay}</InlineMono>
                                                {canEditProfile && <IconActionButton type="button" onClick={() => navigate('/change_username')} title="Change username" aria-label="Change username">
                                                    <HiPencilSquare aria-hidden="true" />
                                                </IconActionButton>}
                                            </ProfileFieldValue>
                                        </ProfileFieldRow>
                                        <ProfileFieldRow>
                                            <Label>Address:</Label>
                                            <ProfileFieldValue>
                                                <InlineMono title={profileAddress}>{profileAddress || '(unavailable)'}</InlineMono>
                                                {profileAddress && <IconActionButton type="button" onClick={() => {
                                                    navigator.clipboard.writeText(profileAddress);
                                                    setAddressCopied(true);
                                                    setTimeout(() => setAddressCopied(false), 1500);
                                                }} $success={addressCopied} title={addressCopied ? 'Copied!' : 'Copy address'} aria-label={addressCopied ? 'Copied' : 'Copy address'}>
                                                    {addressCopied ? <HiCheck aria-hidden="true" /> : <HiClipboardDocument aria-hidden="true" />}
                                                </IconActionButton>}
                                            </ProfileFieldValue>
                                        </ProfileFieldRow>
                                        <ProfileFieldRow>
                                            <Label>Tier:</Label>
                                            <ProfileFieldValue>
                                                <span style={{ display: 'flex', alignItems: 'center' }}>
                                                    <Mono style={userLevel > 0 ? { color: getTierColor(userLevel) } : undefined}>
                                                        {getTierName(userLevel)}
                                                    </Mono>
                                                    {userLevel > 0 && subscriptionExpiry > 0 && formatSubscriptionExpiry(subscriptionExpiry) && <span style={{
                                                        marginLeft: '0.5rem',
                                                        fontSize: '0.7rem',
                                                        color: theme.colors.subtleText
                                                    }}>
                                                        ({formatSubscriptionExpiry(subscriptionExpiry)})
                                                    </span>}
                                                </span>
                                                {!isOwnProfile && profileAddress && hasValidAccount && (
                                                    <HideOnMobile>
                                                        <GiftMirageBtn type="button" onClick={handleGiftSub} disabled={subFeePending} title="Gift Subscription">
                                                            <HiGift aria-hidden="true" />{' '}
                                                            {subFeePending ? (subFeeStatus || 'Gifting...') : 'Gift Sub'}
                                                        </GiftMirageBtn>
                                                    </HideOnMobile>
                                                )}
                                                {isOwnProfile && userLevel === 0 && (() => {
                                                    const insufficient = subFeeUmirage != null && Number(balance) < Number(subFeeUmirage);
                                                    return (
                                                        <Button
                                                            size="sm"
                                                            variant="subtle"
                                                            mobileFullWidth
                                                            disabled={insufficient}
                                                            onClick={() => navigate('/subscription')}
                                                            title={insufficient ? 'Insufficient balance to upgrade' : undefined}
                                                        >
                                                            {insufficient ? 'Insufficient Funds' : 'Upgrade'}
                                                        </Button>
                                                    );
                                                })()}
                                            </ProfileFieldValue>
                                        </ProfileFieldRow>
                                        {/* Gift Subscription confirmation moved to a root-level
                              * default `GiftSubscriptionDialog` modal (matches
                              * the Block / Report dialog visual language). The
                              * `confirmGiftSub` state still drives visibility;
                              * we just render it differently. The success /
                              * error banner below remains inline so the user
                              * sees "Subscription gifted!" next to the Tier row. */}
                                        {giftSubMessage && <ProfileFieldRow>
                                            <div aria-hidden="true" />
                                            <ProfileFieldValuePlain>
                                                <div style={{
                                                    background: giftSubMessage.type === 'success' ? theme.colors.buttonSuccessBg : theme.colors.buttonDangerBg,
                                                    border: `1px solid ${giftSubMessage.type === 'success' ? theme.colors.buttonSuccessBorder : theme.colors.buttonDangerBorder}`,
                                                    padding: '0.6rem 0.85rem',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '0.5rem',
                                                    color: giftSubMessage.type === 'success' ? theme.colors.voteUp : theme.colors.voteDown,
                                                    fontSize: '0.8rem',
                                                    boxSizing: 'border-box'
                                                }}>
                                                    <span>{giftSubMessage.type === 'success' ? '✓' : '⚠'}</span>
                                                    {giftSubMessage.message}
                                                </div>
                                            </ProfileFieldValuePlain>
                                        </ProfileFieldRow>}
                                        <ProfileFieldRow>
                                            <HoverableLabel tabIndex={0} data-tooltip={`Spendable wallet balance in MIRAGE.\n\nThis is what a subscription will be paid with.`}>
                                                Balance:
                                            </HoverableLabel>
                                            <ProfileFieldValue>
                                                <Mono title={balanceDisplay}>{compactMirageLabel(balance)}</Mono>
                                                {!isOwnProfile && profileAddress && hasValidAccount && (
                                                    <GiftMirageBtn type="button" onClick={handleDonate} disabled={donatePending} title="Gift Mirage">
                                                        <HiGift aria-hidden="true" />{' '}
                                                        {donatePending ? (donateStatus || 'Sending...') : (<>
                                                            <GiftBtnLabelFull>Gift Mirage</GiftBtnLabelFull>
                                                            <GiftBtnLabelShort>Gift</GiftBtnLabelShort>
                                                        </>)}
                                                    </GiftMirageBtn>
                                                )}
                                            </ProfileFieldValue>
                                        </ProfileFieldRow>
                                        {/* Gift Mirage confirmation moved to a root-level
                              * default `GiftMirageDialog` modal. Success /
                              * error banner still renders inline below so the
                              * user sees the outcome next to the Balance row. */}
                                        {donateMessage && <ProfileFieldRow>
                                            <div aria-hidden="true" />
                                            <ProfileFieldValuePlain>
                                                <div style={{
                                                    background: donateMessage.type === 'success' ? theme.colors.buttonSuccessBg : theme.colors.buttonDangerBg,
                                                    border: `1px solid ${donateMessage.type === 'success' ? theme.colors.buttonSuccessBorder : theme.colors.buttonDangerBorder}`,
                                                    padding: '0.6rem 0.85rem',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '0.5rem',
                                                    color: donateMessage.type === 'success' ? theme.colors.voteUp : theme.colors.voteDown,
                                                    fontSize: '0.8rem',
                                                    boxSizing: 'border-box'
                                                }}>
                                                    <span>{donateMessage.type === 'success' ? '✓' : '⚠'}</span>
                                                    {donateMessage.message}
                                                </div>
                                            </ProfileFieldValuePlain>
                                        </ProfileFieldRow>}
                                        <ProfileFieldRow>
                                            <HoverableLabel tabIndex={0} data-tooltip={`Escrowed reserve in MIRAGE used for relayed gas and subscriptions.\n\nHeld internally by the blockchain and used to process all transactions while subscribed.\n\nNot directly spendable and will get burned if not used.`}>
                                                Reserve:
                                            </HoverableLabel>
                                            <ProfileFieldValuePlain>
                                                <Mono title={reserveDisplay}>{compactMirageLabel(reserveFunds)}</Mono>
                                            </ProfileFieldValuePlain>
                                        </ProfileFieldRow>
                                        <ProfileFieldRow>
                                            <Label>Registered:</Label>
                                            <ProfileFieldValuePlain>
                                                <Mono title={registeredDisplay}>{profileRegisteredAt ? formatAccountAgeLong(profileRegisteredAt) : registeredDisplay}</Mono>
                                            </ProfileFieldValuePlain>
                                        </ProfileFieldRow>
                                        <ProfileFieldRow>
                                            <HoverableLabel tabIndex={0} data-tooltip={`How many users this account follows.`}>
                                                Following:
                                            </HoverableLabel>
                                            <ProfileFieldValuePlain>
                                                <Mono>{followingCount == null ? '—' : followingCount}</Mono>
                                            </ProfileFieldValuePlain>
                                        </ProfileFieldRow>
                                        <ProfileFieldRow>
                                            <HoverableLabel tabIndex={0} data-tooltip={`How many users follow this account.`}>
                                                Followers:
                                            </HoverableLabel>
                                            <ProfileFieldValuePlain>
                                                <Mono>{followerCount == null ? '—' : followerCount}</Mono>
                                            </ProfileFieldValuePlain>
                                        </ProfileFieldRow>
                                        <ProfileFieldRow>
                                            <Label>Biography:</Label>
                                            <ProfileFieldValuePlain style={{
                                                width: '100%'
                                            }}>
                                                {bioEditing ? <div style={{
                                                    display: 'flex',
                                                    flexDirection: 'column',
                                                    gap: '0.5rem'
                                                }}>
                                                    <BioTextarea value={bioDraft} onChange={e => setBioDraft(e.target.value)} maxLength={BIO_MAX} rows={4} disabled={bioSaving} placeholder="Write a short biography..." autoFocus />
                                                    <div style={{
                                                        display: 'flex',
                                                        justifyContent: 'space-between',
                                                        alignItems: 'center',
                                                        gap: '0.5rem',
                                                        flexWrap: 'wrap'
                                                    }}>
                                                        <span style={{
                                                            fontSize: '0.6rem',
                                                            fontWeight: 500,
                                                            color: bioDraft.length > BIO_MAX ? theme.colors.voteDown : theme.colors.subtleText
                                                        }}>
                                                            {bioDraft.length}/{BIO_MAX}
                                                        </span>
                                                        <div style={{
                                                            display: 'flex',
                                                            gap: '0.5rem'
                                                        }}>
                                                            <BioPillButton type="button" $variant="ghost" disabled={bioSaving} onClick={() => {
                                                                setBioEditing(false);
                                                                setBioError('');
                                                                setBioDraft(biography);
                                                            }}>
                                                                Cancel
                                                            </BioPillButton>
                                                            <BioPillButton type="button" disabled={bioSaving || bioDraft.length > BIO_MAX} onClick={handleBioSave}>
                                                                {bioSaving ? (bioButtonStatus || 'Saving...') : (bioButtonStatus || 'Save')}
                                                            </BioPillButton>
                                                        </div>
                                                    </div>
                                                    {bioError && <span style={{
                                                        fontSize: '0.75rem',
                                                        color: theme.colors.voteDown
                                                    }}>{bioError}</span>}
                                                </div> : <ProfileFieldValue>
                                                    <Mono style={{
                                                        whiteSpace: 'pre-wrap',
                                                        wordBreak: 'break-word',
                                                        color: biography ? undefined : theme.colors.subtleText
                                                    }}>
                                                        {biography || (isOwnProfile ? 'No biography set.' : 'No biography.')}
                                                    </Mono>
                                                    {isOwnProfile && <IconActionButton type="button" onClick={() => {
                                                        setBioDraft(biography);
                                                        setBioEditing(true);
                                                        setBioError('');
                                                    }} title={biography ? 'Edit biography' : 'Add biography'} aria-label={biography ? 'Edit biography' : 'Add biography'}>
                                                        <HiPencilSquare aria-hidden="true" />
                                                    </IconActionButton>}
                                                </ProfileFieldValue>}
                                            </ProfileFieldValuePlain>
                                        </ProfileFieldRow>
                                    </>}

                                    {activeTab === 'submissions' && profileUsesListFeed && <>
                                        {isLoadingRecentPosts && recentPosts.length === 0 && (
                                            <FeedCardSkeletonList count={4} />
                                        )}
                                        {!isLoadingRecentPosts && recentPostsError && <ProfilePostsTabGutter><Mono style={{
                                            color: theme.colors.voteDown
                                        }}>{recentPostsError}</Mono></ProfilePostsTabGutter>}
                                        {!isLoadingRecentPosts && !recentPostsError && recentPosts.length === 0 && <ProfilePostsTabGutter><SubtleMono>No {effectivePostsFilter === 'all' ? 'posts' : effectivePostsFilter === 'submissions' ? 'submissions' : 'comments'} yet.</SubtleMono></ProfilePostsTabGutter>}
                                        {recentPosts.length > 0 && (
                                            <FeedComponent
                                                key={profileFeedView}
                                                posts={recentPosts}
                                                state={state}
                                                showSortTabs={false}
                                                bleedShell={false}
                                            />
                                        )}
                                        {(recentAutoLoading || (isLoadingRecentPosts && recentPage > 1)) && (
                                            <FeedCardSkeleton />
                                        )}
                                        <div ref={recentBottomSentinelRef} style={{
                                            width: '100%',
                                            height: '20px',
                                            minHeight: '20px'
                                        }} />
                                    </>}

                                    {activeTab === 'comments' && profileUsesListFeed && <>
                                        {isLoadingRecentPosts && recentPosts.length === 0 && (
                                            <ListRowSkeletonList count={6} hasAvatar={false} showMeta={true} />
                                        )}
                                        {!isLoadingRecentPosts && recentPostsError && <ProfilePostsTabGutter><Mono style={{
                                            color: theme.colors.voteDown
                                        }}>{recentPostsError}</Mono></ProfilePostsTabGutter>}
                                        {!isLoadingRecentPosts && !recentPostsError && recentPosts.length === 0 && <ProfilePostsTabGutter><SubtleMono>No comments yet.</SubtleMono></ProfilePostsTabGutter>}
                                        {recentPosts.length > 0 && recentPosts.map(post => (
                                            <ProfileCommentRow key={post.post_id} post={post} />
                                        ))}
                                        {(recentAutoLoading || (isLoadingRecentPosts && recentPage > 1)) && (
                                            <ListRowSkeleton hasAvatar={false} showMeta={false} />
                                        )}
                                        <div ref={recentBottomSentinelRef} style={{
                                            width: '100%',
                                            height: '20px',
                                            minHeight: '20px'
                                        }} />
                                    </>}

                                    {isPostsTab && !profileUsesListFeed && <>
                                        {!profileHideFilterSelect && profileAddress && <ProfilePostsTabGutter><FilterSelect value={recentPostsFilter} onChange={e => setRecentPostsFilter(e.target.value)}>
                                            <option value="all">All</option>
                                            <option value="submissions">Submissions</option>
                                            <option value="comments">Comments</option>
                                        </FilterSelect></ProfilePostsTabGutter>}
                                        {isLoadingRecentPosts && (
                                            <ListRowSkeletonList count={5} hasAvatar={false} />
                                        )}
                                        {!isLoadingRecentPosts && recentPostsError && <ProfilePostsTabGutter><Mono style={{
                                            color: theme.colors.voteDown
                                        }}>{recentPostsError}</Mono></ProfilePostsTabGutter>}
                                        {!isLoadingRecentPosts && !recentPostsError && recentPosts.length === 0 && <ProfilePostsTabGutter><SubtleMono>No {effectivePostsFilter === 'all' ? 'posts' : effectivePostsFilter === 'submissions' ? 'submissions' : 'comments'} yet.</SubtleMono></ProfilePostsTabGutter>}
                                        {!recentPostsError && recentPosts.length > 0 && <PostsList>
                                            {recentPosts.map(post => <PostItem key={post.post_id} href={getPostUrl(post)} isActive={activeRecentPost === post.post_id} onClick={e => handleRecentPostClick(post, e)}>
                                                <PostPreview>{renderPostPreview(post)}</PostPreview>
                                                <PostMeta>{buildMetaLine(post)}</PostMeta>
                                            </PostItem>)}
                                        </PostsList>}
                                        {(recentAutoLoading || (isLoadingRecentPosts && recentPage > 1)) && (
                                            <ListRowSkeleton hasAvatar={false} />
                                        )}
                                        <div ref={recentBottomSentinelRef} style={{
                                            width: '100%',
                                            height: '20px',
                                            minHeight: '20px'
                                        }} />
                                    </>}

                                    {activeTab === 'algo' && <>
                                        {/* Topic preferences — "#" chip per topic, weight pill */}
                                        <AlgoSection>
                                            <AlgoSectionHead>
                                                <AlgoSectionHeadText>
                                                    <AlgoSectionTitle>Topic preferences</AlgoSectionTitle>
                                                    <AlgoSectionSubtitle>Topics this account engages with the most</AlgoSectionSubtitle>
                                                </AlgoSectionHeadText>
                                                {!prefsLoading && !prefsError && prefsTopics.length > 0 && (
                                                    <AlgoSectionCount>{prefsTopics.length}</AlgoSectionCount>
                                                )}
                                            </AlgoSectionHead>
                                            <AlgoList>
                                                {prefsLoading && <ListRowSkeletonList count={5} hasAvatar={true} showMeta={false} />}
                                                {!prefsLoading && prefsError && <AlgoEmpty $danger>{prefsError}</AlgoEmpty>}
                                                {!prefsLoading && !prefsError && prefsTopics.length === 0 && <AlgoEmpty>No topic preference data yet.</AlgoEmpty>}
                                                {!prefsError && prefsTopics.length > 0 && (() => {
                                                    const CAP = 5;
                                                    const needsCollapse = prefsTopics.length > CAP * 2;
                                                    const visible = needsCollapse && !showAllTopicPrefs ? [...prefsTopics.slice(0, CAP), null, ...prefsTopics.slice(-CAP)] : prefsTopics;
                                                    return <>
                                                        {visible.map(t => {
                                                            if (t === null) {
                                                                const hidden = prefsTopics.length - CAP * 2;
                                                                return <AlgoExpandRow key="__expand"><AlgoExpandPill type="button" onClick={() => setShowAllTopicPrefs(true)}>Show {hidden} more</AlgoExpandPill></AlgoExpandRow>;
                                                            }
                                                            const tone = t.weight > 0 ? 'up' : t.weight < 0 ? 'down' : 'neutral';
                                                            return <AlgoRow key={t.topic} href={`/t/${encodeURIComponent(t.topic)}`} onClick={e => {
                                                                if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                                                    e.preventDefault();
                                                                    navigate(`/t/${encodeURIComponent(t.topic)}`);
                                                                }
                                                            }}>
                                                                <AlgoTopicChip aria-hidden="true"><HiHashtag /></AlgoTopicChip>
                                                                <AlgoIdentity>
                                                                    <AlgoIdentityTitle>{t.topic}</AlgoIdentityTitle>
                                                                </AlgoIdentity>
                                                                <AlgoWeightPill $tone={tone}>{formatPrefWeight(t.weight)}</AlgoWeightPill>
                                                            </AlgoRow>;
                                                        })}
                                                        {showAllTopicPrefs && prefsTopics.length > 10 && <AlgoExpandRow><AlgoExpandPill type="button" onClick={() => setShowAllTopicPrefs(false)}>Show less</AlgoExpandPill></AlgoExpandRow>}
                                                    </>;
                                                })()}
                                            </AlgoList>
                                        </AlgoSection>

                                        {/* User preferences — dicebear avatar per author, weight pill */}
                                        <AlgoSection>
                                            <AlgoSectionHead>
                                                <AlgoSectionHeadText>
                                                    <AlgoSectionTitle>User preferences</AlgoSectionTitle>
                                                    <AlgoSectionSubtitle>Authors this account engages with the most</AlgoSectionSubtitle>
                                                </AlgoSectionHeadText>
                                                {!prefsLoading && !prefsError && prefsAuthors.length > 0 && (
                                                    <AlgoSectionCount>{prefsAuthors.length}</AlgoSectionCount>
                                                )}
                                            </AlgoSectionHead>
                                            <AlgoList>
                                                {prefsLoading && <ListRowSkeletonList count={5} hasAvatar={true} showMeta={true} />}
                                                {!prefsLoading && prefsError && <AlgoEmpty $danger>{prefsError}</AlgoEmpty>}
                                                {!prefsLoading && !prefsError && prefsAuthors.length === 0 && <AlgoEmpty>No user preference data yet.</AlgoEmpty>}
                                                {!prefsError && prefsAuthors.length > 0 && (() => {
                                                    const CAP = 5;
                                                    const needsCollapse = prefsAuthors.length > CAP * 2;
                                                    const visible = needsCollapse && !showAllAuthorPrefs ? [...prefsAuthors.slice(0, CAP), null, ...prefsAuthors.slice(-CAP)] : prefsAuthors;
                                                    return <>
                                                        {visible.map(u => {
                                                            if (u === null) {
                                                                const hidden = prefsAuthors.length - CAP * 2;
                                                                return <AlgoExpandRow key="__expand"><AlgoExpandPill type="button" onClick={() => setShowAllAuthorPrefs(true)}>Show {hidden} more</AlgoExpandPill></AlgoExpandRow>;
                                                            }
                                                            const uname = prefAuthorUsernames[String(u.user || '').toLowerCase()];
                                                            const displayName = uname && uname !== u.user ? uname : shortenAddress(u.user);
                                                            const avatarSeed = u.user || uname || 'user';
                                                            const tone = u.weight > 0 ? 'up' : u.weight < 0 ? 'down' : 'neutral';
                                                            return <AlgoRow key={u.user} href={`/u/${encodeURIComponent(prefAuthorUsernames[u.user] || u.user)}?tab=posts`} onClick={e => {
                                                                if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                                                    e.preventDefault();
                                                                    navigate(`/u/${encodeURIComponent(prefAuthorUsernames[u.user] || u.user)}?tab=posts`);
                                                                }
                                                            }}>
                                                                <AlgoAvatar seed={avatarSeed} alt={`${displayName} avatar`} />
                                                                <AlgoIdentity>
                                                                    <AlgoIdentityTitle>{uname && uname !== u.user ? uname : displayName}</AlgoIdentityTitle>
                                                                    <AlgoIdentityMono title={u.user}>{shortenAddress(u.user)}</AlgoIdentityMono>
                                                                </AlgoIdentity>
                                                                <AlgoWeightPill $tone={tone}>{formatPrefWeight(u.weight)}</AlgoWeightPill>
                                                            </AlgoRow>;
                                                        })}
                                                        {showAllAuthorPrefs && prefsAuthors.length > 10 && <AlgoExpandRow><AlgoExpandPill type="button" onClick={() => setShowAllAuthorPrefs(false)}>Show less</AlgoExpandPill></AlgoExpandRow>}
                                                    </>;
                                                })()}
                                            </AlgoList>
                                        </AlgoSection>

                                        {/* Similar users — dicebear avatar + similarity score */}
                                        <AlgoSection>
                                            <AlgoSectionHead>
                                                <AlgoSectionHeadText>
                                                    <AlgoSectionTitle>Similar users</AlgoSectionTitle>
                                                    <AlgoSectionSubtitle>Accounts whose taste overlaps with this profile</AlgoSectionSubtitle>
                                                </AlgoSectionHeadText>
                                                {!similarUsersLoading && !similarUsersError && similarUsers.length > 0 && (
                                                    <AlgoSectionCount>{similarUsers.length}</AlgoSectionCount>
                                                )}
                                            </AlgoSectionHead>
                                            <AlgoList>
                                                {similarUsersLoading && <ListRowSkeletonList count={5} hasAvatar={true} showMeta={true} />}
                                                {!similarUsersLoading && similarUsersError && <AlgoEmpty $danger>{similarUsersError}</AlgoEmpty>}
                                                {!similarUsersLoading && !similarUsersError && similarUsers.length === 0 && <AlgoEmpty>No similar users found yet.</AlgoEmpty>}
                                                {!similarUsersError && similarUsers.length > 0 && <>
                                                    {(showAllSimilarUsers ? similarUsers : similarUsers.slice(0, 5)).map(u => {
                                                        const displayName = u.username || shortenAddress(u.address);
                                                        const avatarSeed = u.address || u.username || 'user';
                                                        const tone = u.similarity >= 0 ? 'up' : 'down';
                                                        const pct = `${u.similarity >= 0 ? '+' : ''}${Math.round(u.similarity * 100)}%`;
                                                        return <AlgoRow key={u.address} href={`/u/${encodeURIComponent(u.username || u.address)}?tab=posts`} onClick={e => {
                                                            if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                                                e.preventDefault();
                                                                navigate(`/u/${encodeURIComponent(u.username || u.address)}?tab=posts`);
                                                            }
                                                        }}>
                                                            <AlgoAvatar seed={avatarSeed} alt={`${displayName} avatar`} />
                                                            <AlgoIdentity>
                                                                <AlgoIdentityTitle>{displayName}</AlgoIdentityTitle>
                                                                <AlgoIdentityMono title={u.address}>{shortenAddress(u.address)}</AlgoIdentityMono>
                                                            </AlgoIdentity>
                                                            <AlgoWeightStack>
                                                                <AlgoWeightPill $tone={tone}>{pct}</AlgoWeightPill>
                                                                <AlgoWeightSub>{u.shared_dimensions} shared</AlgoWeightSub>
                                                            </AlgoWeightStack>
                                                        </AlgoRow>;
                                                    })}
                                                    {!showAllSimilarUsers && similarUsers.length > 5 && <AlgoExpandRow><AlgoExpandPill type="button" onClick={() => setShowAllSimilarUsers(true)}>Show {similarUsers.length - 5} more</AlgoExpandPill></AlgoExpandRow>}
                                                    {showAllSimilarUsers && similarUsers.length > 5 && <AlgoExpandRow><AlgoExpandPill type="button" onClick={() => setShowAllSimilarUsers(false)}>Show less</AlgoExpandPill></AlgoExpandRow>}
                                                </>}
                                            </AlgoList>
                                        </AlgoSection>
                                    </>}

                                </TabContent>
                            </ProfileMainColumn>
                            <ProfileAside>
                                <AsideCard>
                                    <Banner />
                                    <AsideInner>
                                        <AsideIdentityRow>
                                            <AsideAvatarWrap>
                                                <Avatar $size={60} seed={profileAddress || profileUsername || routeIdentity} alt={profileUsername ? `${profileUsername} avatar` : 'Profile avatar'} />
                                            </AsideAvatarWrap>
                                            <AsideNameBlock>
                                                <AsideName
                                                    title={profileUsername}
                                                    $tierColor={getAuthorColor(userLevel)}
                                                >{usernameDisplay}</AsideName>
                                                <AsideHandle>u/{profileUsername || (profileAddress ? shortenAddress(profileAddress) : 'anon')}</AsideHandle>
                                            </AsideNameBlock>
                                        </AsideIdentityRow>
                                        {biography && <AsideBio>{biography}</AsideBio>}
                                        <AsideActions>
                                            <AsideShareBtn
                                                type="button"
                                                onClick={handleProfileShare}
                                                title={profileShareCopied ? 'Link copied!' : 'Copy profile link'}
                                                aria-live="polite"
                                                $success={profileShareCopied}
                                            >
                                                {profileShareCopied ? <HiCheck aria-hidden="true" /> : <HiShare aria-hidden="true" />}
                                                {profileShareCopied ? 'Link copied' : 'Share'}
                                            </AsideShareBtn>
                                            {!isOwnProfile && profileAddress && hasValidAccount && (
                                                <MobileOnly>
                                                    <AsideShareBtn type="button" onClick={handleGiftSub} disabled={subFeePending} title="Gift Subscription">
                                                        <HiGift aria-hidden="true" />
                                                        {subFeePending ? (subFeeStatus || 'Gifting...') : 'Gift Sub'}
                                                    </AsideShareBtn>
                                                </MobileOnly>
                                            )}
                                            {!isOwnProfile && address && (
                                                <AsideOnlyWhenHeaderHidden>
                                                    <CompactFollowBtn
                                                        type="button"
                                                        $active={isFollowingProfile && !((isFollowingProfile && followHover) || isUnfollowAction)}
                                                        $danger={(isFollowingProfile && followHover) || isUnfollowAction}
                                                        onMouseEnter={() => setFollowHover(true)}
                                                        onMouseLeave={() => setFollowHover(false)}
                                                        disabled={isFollowInProgress}
                                                        onClick={handleFollowToggle}
                                                    >
                                                        {isFollowInProgress ? formatStatusForPosition(myQueuePosition) || 'Processing' : isFollowingProfile ? followHover ? 'Unfollow' : 'Following' : 'Follow'}
                                                    </CompactFollowBtn>
                                                </AsideOnlyWhenHeaderHidden>
                                            )}
                                            {!isOwnProfile && address && isProfileBlocked && (
                                                <AsideOnlyWhenHeaderHidden>
                                                    <Button
                                                        type="button"
                                                        variant="danger"
                                                        size="sm"
                                                        minWidth="5.5rem"
                                                        disabled={isUnblockPending}
                                                        loading={isUnblockPending}
                                                        onClick={handleUnblockProfile}
                                                        style={{ height: '32px', borderRadius: '9999px', paddingTop: 0, paddingBottom: 0 }}
                                                    >
                                                        {isUnblockPending ? unblockStatus || 'Processing' : 'Unblock'}
                                                    </Button>
                                                </AsideOnlyWhenHeaderHidden>
                                            )}
                                        </AsideActions>
                                        <AsideStatsGrid>
                                            <AsideStat>
                                                <AsideStatValue $color={userLevel > 0 ? getTierColor(userLevel) : undefined}>{getTierName(userLevel)}</AsideStatValue>
                                                <AsideStatLabel>Tier</AsideStatLabel>
                                            </AsideStat>
                                            <AsideStat>
                                                <AsideStatValue title={balanceDisplay}>{compactMirageLabel(balance)}</AsideStatValue>
                                                <AsideStatLabel>Balance</AsideStatLabel>
                                            </AsideStat>
                                            <AsideStat>
                                                <AsideStatValue title={registeredDisplay}>{formatAccountAge(profileRegisteredAt)}</AsideStatValue>
                                                <AsideStatLabel>Joined</AsideStatLabel>
                                            </AsideStat>
                                            <AsideStat>
                                                <AsideStatValue title={reserveDisplay}>{compactMirageLabel(reserveFunds)}</AsideStatValue>
                                                <AsideStatLabel>Reserve</AsideStatLabel>
                                            </AsideStat>
                                            <AsideStat>
                                                <AsideStatValue>{followingCount == null ? '—' : followingCount}</AsideStatValue>
                                                <AsideStatLabel>Following</AsideStatLabel>
                                            </AsideStat>
                                            <AsideStat>
                                                <AsideStatValue>{followerCount == null ? '—' : followerCount}</AsideStatValue>
                                                <AsideStatLabel>Followers</AsideStatLabel>
                                            </AsideStat>
                                        </AsideStatsGrid>
                                    </AsideInner>
                                </AsideCard>
                                {isOwnProfile && <AsideCard>
                                    <AsideSectionHeader>Settings</AsideSectionHeader>
                                    <AsideSettingsList>
                                        <AsideSettingRow type="button" onClick={() => navigate('/change_username')}>
                                            <AsideSettingMain>
                                                <AsideSettingLabel>Username</AsideSettingLabel>
                                                <AsideSettingHint>Change your display name</AsideSettingHint>
                                            </AsideSettingMain>
                                            <AsideSettingChev aria-hidden="true" />
                                        </AsideSettingRow>
                                        <AsideSettingRow type="button" onClick={() => navigate('/settings')}>
                                            <AsideSettingMain>
                                                <AsideSettingLabel>Preferences</AsideSettingLabel>
                                                <AsideSettingHint>App-wide settings</AsideSettingHint>
                                            </AsideSettingMain>
                                            <AsideSettingChev aria-hidden="true" />
                                        </AsideSettingRow>
                                        <AsideSettingRow type="button" onClick={() => navigate('/subscription')}>
                                            <AsideSettingMain>
                                                <AsideSettingLabel>Subscription</AsideSettingLabel>
                                                <AsideSettingHint>Manage your plan</AsideSettingHint>
                                            </AsideSettingMain>
                                            <AsideSettingChev aria-hidden="true" />
                                        </AsideSettingRow>
                                    </AsideSettingsList>
                                </AsideCard>}
                            </ProfileAside>
                        </ProfileGrid>
                    </ProfileShellBody>
                </ProfileTabbedContainer>
            </CappedPageColumn>
        </ModernPostFeed>
        {/* Gift Mirage / Gift Subscription dialogs — rendered at the route
          * root so a single modal owns the overlay + panel for the whole
          * page. Visibility is driven by the existing `confirmDonate` /
          * `confirmGiftSub` state in `useProfile`, matching the pattern
          * used by ViewPostView and the Block/Report dialogs. */}
        <GiftMirageDialog
            open={!!confirmDonate}
            recipientLabel={profileUsername
                ? `@${profileUsername}`
                : (profileAddress ? `@${String(profileAddress).slice(0, 10)}…` : '@this user')}
            amountRaw={donateAmountRaw}
            formatAmount={formatDonateAmount}
            onAmountChange={(value) => setDonateAmountRaw(String(value || '').replace(/[^\d]/g, ''))}
            pending={donatePending}
            userBalanceUmirage={viewerBalanceUmirage}
            onConfirm={confirmDonateAction}
            onCancel={cancelDonate}
        />
        <GiftSubscriptionDialog
            open={!!confirmGiftSub}
            recipientLabel={profileUsername
                ? `@${profileUsername}`
                : (profileAddress ? `@${String(profileAddress).slice(0, 10)}…` : '@this user')}
            level={confirmGiftSub?.level}
            feeLabel={confirmGiftSub?.level === 10 ? agentFeeLabel : subFeeLabel}
            feeUmirage={confirmGiftSub?.level === 10 ? agentFeeUmirage : subFeeUmirage}
            loading={!!confirmGiftSub?.loading}
            expiryLabel={confirmGiftSub?.expiryLabel}
            error={confirmGiftSub?.error}
            pending={subFeePending}
            userBalanceUmirage={viewerBalanceUmirage}
            onConfirm={confirmGiftSubAction}
            onCancel={cancelGiftSub}
        />
    </ContentGrid>;
}
