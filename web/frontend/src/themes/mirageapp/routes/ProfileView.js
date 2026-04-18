import { Helmet } from "react-helmet-async";
import styled, { useTheme } from "styled-components";
import { HiChevronRight, HiShare, HiGift, HiPencilSquare, HiClipboardDocument, HiCheck } from "react-icons/hi2";
import Button from "../components/Button.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, CappedPageColumn } from "../Layout";
import { tooltipStyles } from "../components/Tooltip.js";
import { useProfile } from "../../../logic/useProfile";
import { formatMirageCompact } from "../../../utils/formatters";
import { dicebearAvatarUrl } from "../../../utils/avatar";

/** Compact MIRAGE balance for the right-aside stats grid (e.g. `1.2K MIRAGE`). */
const compactMirageLabel = (raw) => {
    if (raw === null || raw === undefined) return '—';
    const compact = formatMirageCompact(raw);
    return compact ? `${compact} MIRAGE` : '—';
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
const LoadingSpinner = styled.div`
    width: 16px;
    height: 16px;
    border: 2px solid ${({
    theme
}) => theme.colors.border};
    border-top: 2px solid ${({
    theme
}) => theme.colors.subtleText};
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;
const SubtleMono = styled(Mono)`
    color: ${({
    theme
}) => theme.colors.subtleText};
`;
const LoadingRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.5rem 0 0.75rem;
    padding: 0.5rem 1rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
`;

/** Horizontal inset for content on posts/algo tabs — matches `SettingsWrap` row padding. */
const ProfilePostsTabGutter = styled.div`
    padding: 0 1rem;
`;

/** No per-row divider. Padding matches `SettingsView::SettingRow` (0.55rem 1rem). */
const ProfileFieldRow = styled.div`
    display: grid;
    grid-template-columns: ${({ theme }) => theme.layout.formRowColumns};
    gap: ${({ theme }) => theme.layout.formRowGap};
    align-items: center;
    padding: 0.55rem 1rem;
    box-sizing: border-box;
    width: 100%;
    min-width: 0;

    @media (max-width: 1000px) {
        grid-template-columns: 1fr;
        gap: 0.35rem;
        align-items: stretch;
        padding: 0.5rem 0.85rem;
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

    @media (max-width: 1000px) {
        flex-wrap: wrap;
    }
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
`;

/** Main-column header: avatar + large display name + `u/handle`. Replaces the old "Profile" text. */
const ProfileIdentity = styled.div`
    display: flex;
    align-items: center;
    gap: 0.85rem;
    padding: 0.75rem 1rem 0.6rem;
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

// DiceBear identicon avatar (seeded). DiceBear's identicon variant returns a
// transparent background, so the styled bg shows through the pattern's
// negative space. We hard-pin the bg to the dark-mode surface3 value
// (#232830) in BOTH modes so the avatar circle looks identical in light
// and dark — matches the dark-mode chip you approved.
const Avatar = styled.img`
    width: ${({ $size }) => $size || 64}px;
    height: ${({ $size }) => $size || 64}px;
    border-radius: 50%;
    background: #232830;
    object-fit: cover;
    flex-shrink: 0;
    display: block;
`;

const IdentityBlock = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
`;

const DisplayName = styled.div`
    color: ${({ theme }) => theme.colors.text};
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
    color: ${({ theme }) => theme.colors.text};
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
    background: ${({ theme }) => theme.colors.actionIconBg};
    color: ${({ theme }) => theme.colors.text};
    font-family: inherit;
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1;
    cursor: pointer;
    text-decoration: none;
    transition: background 0.12s ease;

    &:hover { background: ${({ theme }) => theme.colors.actionIconHoverBg}; }
    &:focus { outline: none; }
    &:focus-visible { box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.borderStrong}; }

    svg { width: 14px; height: 14px; fill: currentColor; }
`;

/** Gift Sub button in the aside actions row — same 32px height + visual
 *  language as `AsideShareBtn` so it sits flush next to Share. */
const AsideGiftSubBtn = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    height: 32px;
    padding: 0 12px;
    border-radius: 9999px;
    border: none;
    background: ${({ theme }) => theme.colors.actionIconBg};
    color: ${({ theme }) => theme.colors.text};
    font-family: inherit;
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1;
    cursor: pointer;
    transition: background 0.12s ease;

    &:hover:not(:disabled) { background: ${({ theme }) => theme.colors.actionIconHoverBg}; }
    &:disabled { cursor: not-allowed; opacity: 0.55; }
    &:focus { outline: none; }
    &:focus-visible { box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.borderStrong}; }

    svg { width: 14px; height: 14px; fill: currentColor; }
`;

/** Compact Follow button used in the aside identity card and the main profile
 *  header. Solid `followBtnBg` pill in idle / Following states; flips to a
 *  danger outline on hover when already following (so the click target reads
 *  as "Unfollow"). 32px tall — matches `AsideShareBtn` / `AsideGiftSubBtn`
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
        ? theme.colors.voteDown
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
            ? theme.colors.voteDown
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
    padding-top: 0.4rem;
`;

/** Section header — primary `text` color (was `subtleText`). No inline rule. */
const SectionHeader = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.85rem 1rem 0.35rem;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

/** Algo tab list primitives — borrow Settings row density. */
const AlgoList = styled.div`
    display: flex;
    flex-direction: column;
`;

const AlgoRow = styled.a`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.45rem 1rem;
    text-decoration: none;
    color: ${({ theme }) => theme.colors.cardBodyText};
    font-family: inherit;
    font-size: 0.72rem;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.15s ease;

    &:hover { background-color: ${({ theme }) => theme.colors.hoverBg}; }

    @media (max-width: 1000px) {
        padding: 0.45rem 0.85rem;
    }
`;

const AlgoValue = styled.span`
    font-size: 0.72rem;
    font-weight: 500;
    color: ${({ theme, $color }) => $color || theme.colors.cardBodyText};
    white-space: nowrap;
`;

const AlgoEmpty = styled.div`
    padding: 0.45rem 1rem;
    color: ${({ theme, $danger }) => $danger ? theme.colors.voteDown : theme.colors.cardBodyText};
    font-size: 0.72rem;
    font-weight: 500;

    @media (max-width: 1000px) {
        padding: 0.45rem 0.85rem;
    }
`;

/** "show more / show less" pill inside an algo list. Centered, outlined, full-radius. */
const AlgoExpandRow = styled.div`
    display: flex;
    justify-content: center;
    padding: 0.45rem 1rem;
`;

const AlgoExpandPill = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    height: 26px;
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

//

export default function ProfileView({
    state
}) {
    const { caps } = useTheme();
    const profileHideFilterSelect = caps.profileHideFilterSelect;
    const profilePostsFullWidth = caps.profilePostsFullWidth;
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
        handleGiftSub,
        confirmGiftSubAction,
        cancelGiftSub,
        formatPrefWeight,
        colorForWeight,
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
        canHaveBiography,
        BIO_MAX,
        handleBioSave,
        formatDonateAmount,
        handleDonate,
        confirmDonateAction,
        cancelDonate
    } = useProfile({
        state
    });
    // Show loading/error states for username resolution
    if (isResolvingUsername || usernameResolutionError) {
        return <ContentGrid>
            <Helmet>
                <title>{routeIdentity ? `@${routeIdentity}` : 'Profile'} | Mirage</title>
            </Helmet>
            <ModernPostFeed>
                <CappedPageColumn>
                    <TabbedContainer>
                        <ContainerBody style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            textAlign: 'center',
                            padding: '2rem',
                            gap: '0.5rem',
                            minHeight: '200px'
                        }}>
                            {isResolvingUsername ? <span style={{
                                color: theme.colors.subtleText
                            }}>Looking up @{routeIdentity}...</span> : <span style={{
                                color: theme.colors.voteDown
                            }}>{usernameResolutionError}</span>}
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
                                        <Avatar $size={64} src={dicebearAvatarUrl(profileAddress || profileUsername || routeIdentity, 64)} alt={profileUsername ? `${profileUsername} avatar` : 'Profile avatar'} />
                                        <IdentityBlock>
                                            <DisplayName title={profileUsername}>{usernameDisplay}</DisplayName>
                                            <Handle>u/{profileUsername || (profileAddress ? shortenAddress(profileAddress) : 'anon')}</Handle>
                                        </IdentityBlock>
                                    </ProfileIdentityMain>
                                    {!isOwnProfile && address && (
                                        <ProfileIdentityActions>
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
                            </TabsRow>
                            <TabContent>
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
                                </ProfileFieldValue>
                            </ProfileFieldRow>
                            {confirmGiftSub && <ProfileFieldRow>
                                <div aria-hidden="true" />
                                <ProfileFieldValuePlain>
                                    <div style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.6rem',
                                        width: '100%',
                                        flexWrap: 'wrap',
                                        background: theme.colors.inboxHighlightBg,
                                        border: `1px solid ${theme.colors.inboxHighlightRail}`,
                                        padding: '0.5rem 0.6rem',
                                        boxSizing: 'border-box'
                                    }}>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                                            <span style={{ whiteSpace: 'nowrap', fontSize: '0.8rem' }}>
                                                🎁 {confirmGiftSub.level === 10 ? 'Gift agent subscription' : 'Gift subscription'} to {profileUsername || profileAddress?.substring(0, 12) + '...'}?{(confirmGiftSub.level === 10 ? agentFeeLabel : subFeeLabel) ? ` (${confirmGiftSub.level === 10 ? agentFeeLabel : subFeeLabel})` : ''}
                                            </span>
                                            {confirmGiftSub.loading && (
                                                <span style={{ fontSize: '0.75rem', opacity: 0.7 }}>Loading expiry...</span>
                                            )}
                                            {confirmGiftSub.expiryLabel && (
                                                <span style={{ fontSize: '0.75rem', opacity: 0.7 }}>{confirmGiftSub.expiryLabel}</span>
                                            )}
                                            {confirmGiftSub.error && (
                                                <span style={{ fontSize: '0.75rem', color: theme.colors.voteDown }}>{confirmGiftSub.error}</span>
                                            )}
                                        </div>
                                        <div style={{
                                            display: 'flex',
                                            gap: '0.5rem',
                                            marginLeft: 'auto',
                                            flexShrink: 0
                                        }}>
                                            <Button variant="warning" size="sm" onClick={confirmGiftSubAction} disabled={subFeePending || confirmGiftSub.loading || !!confirmGiftSub.error}>
                                                {subFeeStatus || 'Confirm'}
                                            </Button>
                                            <Button variant="ghost" size="sm" onClick={cancelGiftSub}>Cancel</Button>
                                        </div>
                                    </div>
                                </ProfileFieldValuePlain>
                            </ProfileFieldRow>}
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
                                    <Mono>{balanceDisplay}</Mono>
                                    {!isOwnProfile && profileAddress && hasValidAccount && (
                                        <GiftMirageBtn type="button" onClick={handleDonate} disabled={donatePending} title="Gift Mirage">
                                            <HiGift aria-hidden="true" /> {donatePending ? donateStatus || 'Sending...' : 'Gift Mirage'}
                                        </GiftMirageBtn>
                                    )}
                                </ProfileFieldValue>
                            </ProfileFieldRow>
                            {confirmDonate && <ProfileFieldRow>
                                <div aria-hidden="true" />
                                <ProfileFieldValuePlain>
                                    <div style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.6rem',
                                        width: '100%',
                                        flexWrap: 'wrap',
                                        background: theme.colors.inboxHighlightBg,
                                        border: `1px solid ${theme.colors.inboxHighlightRail}`,
                                        padding: '0.5rem 0.6rem',
                                        boxSizing: 'border-box'
                                    }}>
                                        <span style={{
                                            whiteSpace: 'nowrap',
                                            fontSize: '0.8rem'
                                        }}>
                                            💰 Gift Mirage to {profileUsername || profileAddress?.substring(0, 12) + '...'}:
                                        </span>
                                        <div style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.35rem',
                                            background: theme.colors.surface2,
                                            border: `1px solid ${theme.colors.borderSubtle}`,
                                            borderRadius: '8px',
                                            padding: '0.2rem 0.5rem'
                                        }}>
                                            <input type="text" inputMode="numeric" value={formatDonateAmount(donateAmountRaw)} onChange={e => setDonateAmountRaw(e.target.value.replace(/[^\d]/g, ""))} placeholder="10,000" maxLength={11} disabled={donatePending} style={{
                                                width: '5.5rem',
                                                background: 'transparent',
                                                border: 'none',
                                                outline: 'none',
                                                color: theme.colors.text,
                                                fontSize: '0.75rem',
                                                fontWeight: 500,
                                                textAlign: 'right'
                                            }} />
                                            <span style={{
                                                fontSize: '0.68rem',
                                                opacity: 0.7
                                            }}>MIRAGE</span>
                                        </div>
                                        <div style={{
                                            display: 'flex',
                                            gap: '0.5rem',
                                            marginLeft: 'auto',
                                            flexShrink: 0
                                        }}>
                                            <Button variant="warning" size="sm" onClick={confirmDonateAction} disabled={donatePending}>
                                                {donateStatus || 'Send'}
                                            </Button>
                                            <Button variant="ghost" size="sm" onClick={cancelDonate}>Cancel</Button>
                                        </div>
                                    </div>
                                </ProfileFieldValuePlain>
                            </ProfileFieldRow>}
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
                                    <Mono>{reserveDisplay}</Mono>
                                </ProfileFieldValuePlain>
                            </ProfileFieldRow>
                            <ProfileFieldRow>
                                <Label>Registered:</Label>
                                <ProfileFieldValuePlain>
                                    <Mono>{registeredDisplay}</Mono>
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
                                        {isOwnProfile && canHaveBiography && <IconActionButton type="button" onClick={() => {
                                            setBioDraft(biography);
                                            setBioEditing(true);
                                            setBioError('');
                                        }} title={biography ? 'Edit biography' : 'Add biography'} aria-label={biography ? 'Edit biography' : 'Add biography'}>
                                            <HiPencilSquare aria-hidden="true" />
                                        </IconActionButton>}
                                        {isOwnProfile && !canHaveBiography && <Button size="sm" variant="subtle" mobileFullWidth onClick={() => navigate('/subscription')}>
                                            Upgrade
                                        </Button>}
                                    </ProfileFieldValue>}
                                </ProfileFieldValuePlain>
                            </ProfileFieldRow>
                        </>}

                        {isPostsTab && profileUsesListFeed && <>
                            {isLoadingRecentPosts && recentPosts.length === 0 && <LoadingRow>
                                <LoadingSpinner />
                                <SubtleMono>Loading posts...</SubtleMono>
                            </LoadingRow>}
                            {!isLoadingRecentPosts && recentPostsError && <ProfilePostsTabGutter><Mono style={{
                                color: theme.colors.voteDown
                            }}>{recentPostsError}</Mono></ProfilePostsTabGutter>}
                            {!isLoadingRecentPosts && !recentPostsError && recentPosts.length === 0 && <ProfilePostsTabGutter><SubtleMono>No {effectivePostsFilter === 'all' ? 'posts' : effectivePostsFilter === 'submissions' ? 'submissions' : 'comments'} yet.</SubtleMono></ProfilePostsTabGutter>}
                            {recentPosts.length > 0 && <FeedComponent posts={recentPosts} state={state} showSortTabs={false} bleedShell={false} />}
                            {(recentAutoLoading || (isLoadingRecentPosts && recentPage > 1)) && <ProfilePostsTabGutter><SubtleMono style={{
                                display: 'block',
                                marginTop: '0.5rem',
                                fontStyle: 'italic'
                            }}>
                                Loading more...
                            </SubtleMono></ProfilePostsTabGutter>}
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
                            {isLoadingRecentPosts && <LoadingRow>
                                <LoadingSpinner />
                                <SubtleMono>Loading posts...</SubtleMono>
                            </LoadingRow>}
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
                            {(recentAutoLoading || (isLoadingRecentPosts && recentPage > 1)) && <ProfilePostsTabGutter><SubtleMono style={{
                                display: 'block',
                                marginTop: '0.5rem',
                                fontStyle: 'italic'
                            }}>
                                Loading more...
                            </SubtleMono></ProfilePostsTabGutter>}
                            <div ref={recentBottomSentinelRef} style={{
                                width: '100%',
                                height: '20px',
                                minHeight: '20px'
                            }} />
                        </>}

                        {activeTab === 'algo' && <>
                            <SectionHeader>Topic preferences</SectionHeader>
                            <AlgoList>
                                {prefsLoading && <AlgoEmpty>Loading...</AlgoEmpty>}
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
                                            return <AlgoRow key={t.topic} href={`/t/${encodeURIComponent(t.topic)}`} onClick={e => {
                                                if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                                    e.preventDefault();
                                                    navigate(`/t/${encodeURIComponent(t.topic)}`);
                                                }
                                            }}>
                                                <span>#{t.topic}</span>
                                                <AlgoValue $color={colorForWeight(t.weight)}>{formatPrefWeight(t.weight)}</AlgoValue>
                                            </AlgoRow>;
                                        })}
                                        {showAllTopicPrefs && prefsTopics.length > 10 && <AlgoExpandRow><AlgoExpandPill type="button" onClick={() => setShowAllTopicPrefs(false)}>Show less</AlgoExpandPill></AlgoExpandRow>}
                                    </>;
                                })()}
                            </AlgoList>

                            <SectionHeader>User preferences</SectionHeader>
                            <AlgoList>
                                {prefsLoading && <AlgoEmpty>Loading...</AlgoEmpty>}
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
                                            return <AlgoRow key={u.user} href={`/u/${encodeURIComponent(prefAuthorUsernames[u.user] || u.user)}?tab=posts`} onClick={e => {
                                                if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                                    e.preventDefault();
                                                    navigate(`/u/${encodeURIComponent(prefAuthorUsernames[u.user] || u.user)}?tab=posts`);
                                                }
                                            }}>
                                                <span>{uname && uname !== u.user ? uname : shortenAddress(u.user)}</span>
                                                <AlgoValue $color={colorForWeight(u.weight)}>{formatPrefWeight(u.weight)}</AlgoValue>
                                            </AlgoRow>;
                                        })}
                                        {showAllAuthorPrefs && prefsAuthors.length > 10 && <AlgoExpandRow><AlgoExpandPill type="button" onClick={() => setShowAllAuthorPrefs(false)}>Show less</AlgoExpandPill></AlgoExpandRow>}
                                    </>;
                                })()}
                            </AlgoList>

                            <SectionHeader>Similar users</SectionHeader>
                            <AlgoList>
                                {similarUsersLoading && <AlgoEmpty>Computing similarity...</AlgoEmpty>}
                                {!similarUsersLoading && similarUsersError && <AlgoEmpty $danger>{similarUsersError}</AlgoEmpty>}
                                {!similarUsersLoading && !similarUsersError && similarUsers.length === 0 && <AlgoEmpty>No similar users found yet.</AlgoEmpty>}
                                {!similarUsersError && similarUsers.length > 0 && <>
                                    {(showAllSimilarUsers ? similarUsers : similarUsers.slice(0, 5)).map(u => <AlgoRow key={u.address} href={`/u/${encodeURIComponent(u.username || u.address)}?tab=posts`} onClick={e => {
                                        if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                            e.preventDefault();
                                            navigate(`/u/${encodeURIComponent(u.username || u.address)}?tab=posts`);
                                        }
                                    }}>
                                        <span>{u.username || shortenAddress(u.address)}</span>
                                        <AlgoValue $color={u.similarity >= 0 ? theme.colors.voteUp : theme.colors.voteDown}>
                                            {u.similarity >= 0 ? '+' : ''}{Math.round(u.similarity * 100)}% ({u.shared_dimensions} shared)
                                        </AlgoValue>
                                    </AlgoRow>)}
                                    {!showAllSimilarUsers && similarUsers.length > 5 && <AlgoExpandRow><AlgoExpandPill type="button" onClick={() => setShowAllSimilarUsers(true)}>Show {similarUsers.length - 5} more</AlgoExpandPill></AlgoExpandRow>}
                                    {showAllSimilarUsers && similarUsers.length > 5 && <AlgoExpandRow><AlgoExpandPill type="button" onClick={() => setShowAllSimilarUsers(false)}>Show less</AlgoExpandPill></AlgoExpandRow>}
                                </>}
                            </AlgoList>
                        </>}

                            </TabContent>
                            </ProfileMainColumn>
                            <ProfileAside>
                                <AsideCard>
                                    <Banner />
                                    <AsideInner>
                                        <AsideIdentityRow>
                                            <AsideAvatarWrap>
                                                <Avatar $size={60} src={dicebearAvatarUrl(profileAddress || profileUsername || routeIdentity, 60)} alt={profileUsername ? `${profileUsername} avatar` : 'Profile avatar'} />
                                            </AsideAvatarWrap>
                                            <AsideNameBlock>
                                                <AsideName title={profileUsername}>{usernameDisplay}</AsideName>
                                                <AsideHandle>u/{profileUsername || (profileAddress ? shortenAddress(profileAddress) : 'anon')}</AsideHandle>
                                            </AsideNameBlock>
                                        </AsideIdentityRow>
                                        {biography && <AsideBio>{biography}</AsideBio>}
                                        <AsideActions>
                                            <AsideShareBtn type="button" onClick={() => {
                                                try { navigator.clipboard.writeText(window.location.href); } catch (_) { /* noop */ }
                                            }} title="Copy profile link">
                                                <HiShare aria-hidden="true" /> Share
                                            </AsideShareBtn>
                                            {!isOwnProfile && profileAddress && hasValidAccount && (
                                                <AsideGiftSubBtn type="button" onClick={handleGiftSub} disabled={subFeePending} title="Gift Sub">
                                                    <HiGift aria-hidden="true" /> {subFeePending ? subFeeStatus || 'Gifting...' : 'Gift Sub'}
                                                </AsideGiftSubBtn>
                                            )}
                                            {!isOwnProfile && address && (
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
    </ContentGrid>;
}