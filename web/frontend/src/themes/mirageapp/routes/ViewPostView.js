import React, { useEffect, useRef, useState } from "react";
import ReactDOM from "react-dom";
import styled from "styled-components";
import { Helmet } from "react-helmet-async";
import Button from "../components/Button.js";
import { Link } from "react-router-dom";
import LoggedOutPromptCard from "../components/LoggedOutPromptCard.js";
import VoteSection from "../components/VoteSection.js";
import * as tx from "../../../utils/tx.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import MarkdownRenderer from "../components/MarkdownRenderer.js";
import MarkdownEditor from "../components/MarkdownEditor.js";
import { MediaRow, MediaPreviewWrapper, MediaPreviewImage, MediaSpinner, MediaRemoveButton, MediaIconButton } from "../components/MediaAttachmentLayout.js";
import Api from "../../../utils/api";
import Storage from "../../../utils/Storage";
import StickerPicker from "../components/StickerPicker.js";
import GifPicker from "../components/GifPicker.js";
import { getAuthorColor, getAuthorTooltip } from "../../../utils/tierColors";
import { Tooltip, tooltipStyles } from "../components/Tooltip.js";
import { useViewPost, tagColors, formatTimeStamp, formatElapsed } from "../../../logic/useViewPost";
import { normalizeTag } from "../../../utils/ContentTags";
import ConfirmDialog from "../components/ConfirmDialog.js";
import { useBlocks } from "../../../logic/useBlocks";
import { HiNoSymbol } from "react-icons/hi2";
/**
 * Post Details — root post container.
 *
 * Matches `CardView::Card` rhythm exactly so the root post reads as the
 * same feed card the user clicked to arrive here. Single-canvas per R1:
 * transparent background that lifts to `hoverBg` on hover, vertical gap
 * between header / title / body / action row driven by flex `gap`, not
 * per-child margins. Ends with a `border-bottom` divider to separate
 * from the comment thread below (R3).
 *
 * `$isNew` ("freshly seen" inbox highlight) paints a subtle inset left
 * rail so R1 still holds.
 */
const PostCard = styled.div`
    background: transparent;
    border: none;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 0;
    box-shadow: none;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    text-align: left;
    gap: 0.5rem;
    padding: 0.75rem 1rem 0.8rem;
    margin: 0;
    position: relative;
    transition: background 0.12s ease;

    ${({ $isNew, theme }) => $isNew ? `
        /* Subtle left-rail accent for newly-seen content (R1: no bg fill). */
        box-shadow: inset 3px 0 0 0 ${theme.colors.focusBlue};
    ` : ''}

    @keyframes flashGlow {
        0%   { background: rgba(102, 126, 234, 0.12); }
        100% { background: transparent; }
    }

    @media (max-width: 1000px) {
        padding: 0.7rem 0.85rem 0.75rem;
        gap: 0.45rem;
    }

    @media (max-width: 600px) {
        padding: 0.65rem 0.85rem 0.7rem;
        gap: 0.4rem;
    }
`;

/**
 * Comment row — reddit + mobile-app hybrid.
 *
 * Full-bleed flat row with a **left thread rail** at every depth level
 * (`1px solid theme.colors.border`, R3). No card background of its own;
 * hover lifts to `hoverBg` matching the feed card rhythm. Indentation is
 * carried by `margin-left` + the rail, matching mobile `comment-item.tsx`.
 *
 * Level-0 (direct replies to the root) get no rail since they already sit
 * against the root post divider.
 *
 * Each comment also gets a subtle bottom divider between siblings so deep
 * threads read cleanly, even when text lengths differ dramatically.
 */
const CommentCard = styled(PostCard)`
    border-bottom: 1px solid ${({ theme }) => theme.colors.borderSubtle};
    box-shadow: none;
    background: transparent;
    gap: 0.35rem;

    /* Each level indents a clean 1.15rem; deeper levels render a rail. */
    margin-left: ${({ $level }) => `${Math.max(Number($level) || 0, 0) * 1.15}rem`};
    padding: ${({ $isCollapsed, $level }) => {
        const leftInset = Number($level) > 0 ? '0.9rem' : '1rem';
        if ($isCollapsed) return `0.45rem ${leftInset} 0.45rem`;
        return `0.65rem ${leftInset} 0.75rem`;
    }};
    border-left: ${({ $level, theme }) =>
        Number($level) > 0 ? `1px solid ${theme.colors.border}` : 'none'};

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    /* Persistent highlight for inbox-linked comments: left-rail accent +
     * subtle tinted background so the single-canvas rule still holds. */
    &.inbox-highlight {
        box-shadow: inset 3px 0 0 0 ${({ theme }) => theme.colors.inboxHighlightRail} !important;
        background: ${({ theme }) => theme.colors.inboxHighlightBg} !important;
    }

    @media (max-width: 1000px) {
        margin-left: ${({ $level }) => `${Math.max(Number($level) || 0, 0) * 0.9}rem`};
        padding: ${({ $isCollapsed, $level }) => {
            const leftInset = Number($level) > 0 ? '0.8rem' : '0.85rem';
            if ($isCollapsed) return `0.4rem ${leftInset}`;
            return `0.55rem ${leftInset} 0.65rem`;
        }};
    }
`;
/**
 * Thread reminder banner shown above the root post when a user is viewing
 * a single comment's sub-thread via `/p/:commentId`. Flat row on `bg`,
 * separated by a bottom divider (R3).
 */
const StyledThreadReminder = styled.div`
    background: transparent;
    border: none;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 0;
    padding: 0.65rem 1rem;
    margin: 0;
    color: ${({ theme }) => theme.colors.subtleText};
    font-weight: 500;
    font-size: 0.7rem;

    a {
        font-size: inherit;
        color: ${({ theme }) => theme.colors.link};
        text-decoration: underline;
        font-weight: 600;

        &:hover {
            color: ${({ theme }) => theme.colors.linkHover};
        }
    }
`;
/**
 * "Continue this thread →" deep-link shown under a comment whose children
 * haven't been loaded. Flat row, bottom divider, left-indented to match
 * the parent comment rail depth.
 */
const ContinueThreadLink = styled(Link)`
    display: block;
    background: transparent;
    border: none;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    border-left: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 0;
    padding: 0.55rem 0.85rem;
    margin-left: ${({ $level }) => `${0.9 * Math.max(Number($level) || 0, 0) + 0.9}rem`};
    margin-top: 0;
    margin-bottom: 0;
    color: ${({ theme }) => theme.colors.link};
    font-size: 0.72rem;
    font-weight: 500;
    text-decoration: none;
    transition: color 0.15s ease, background 0.15s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
        color: ${({
    theme
}) => theme.colors.linkHover};
    }

    @media (max-width: 1000px) {
        margin-left: ${({
    $level
}) => `${0.6 * (Number($level) || 0)}rem`};
        padding: 0.4rem 0.6rem;
    }
`;

// Topic hero container aligned with ModernPostFeed width
const TopicHeroWrapper = styled.div`
    width: 100%;
    margin: 0;
`;
/**
 * Flat header row above the root post — holds the back button (left) and
 * follow-topic button (right). No card background; separated from the
 * post below via the `PostCard` bottom divider (R3). Matches the Inbox /
 * Search header rhythm.
 */
const TopicHeroCard = styled.div`
    width: 100%;
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0.4rem 1rem 0.5rem;
    box-shadow: none;
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;

    @media (max-width: 600px) {
        flex-direction: column;
        gap: 0.35rem;
        padding: 0.35rem 0.75rem 0.5rem;
    }
`;
const TopicHeroTopRow = styled.div`
    display: none;
    
    @media (max-width: 600px) {
        display: flex;
        width: 100%;
        align-items: center;
        justify-content: space-between;
    }
`;
const TopicHeroBackSection = styled.div`
    display: flex;
    align-items: center;
    flex-shrink: 0;
    
    @media (max-width: 600px) {
        display: none;
    }
`;
const TopicAction = styled.div`
    display: flex;
    align-items: center;
    flex-shrink: 0;
    
    @media (max-width: 600px) {
        display: none;
    }
`;

/**
 * Follow topic button in the post-details header. Matches
 * `CardView::FollowButton` 1:1 so the same visual language is used
 * across feed cards and the post-details top bar. Solid blue when not
 * following; transparent with `followBtnBorder` outline when already
 * following; hovers to `followBtnBgHover`. No brand-kit `Button` here —
 * we want the same pill rhythm as the feed.
 */
const TopicFollowButton = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 6px 12px;
    border-radius: 9999px;
    font-size: 0.58rem;
    font-weight: 700;
    font-family: inherit;
    line-height: 1;
    cursor: pointer;
    border: 1.5px solid
        ${({ $active, theme }) =>
            $active ? theme.colors.followBtnBorder : theme.colors.followBtnBg};
    background: ${({ $active, theme }) =>
        $active ? 'transparent' : theme.colors.followBtnBg};
    color: ${({ $active, theme }) =>
        $active ? theme.colors.text : '#FFFFFF'};
    transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;

    &:hover:not(:disabled) {
        background: ${({ $active, theme }) =>
            $active ? 'transparent' : theme.colors.followBtnBgHover};
        border-color: ${({ $active, theme }) =>
            $active ? theme.colors.followBtnBorderHover : theme.colors.followBtnBgHover};
    }
    &:disabled { opacity: 0.6; cursor: default; }
`;

/**
 * Root post title line. Matches `CardView::TitleLink` exactly for visual
 * parity with feed post cards (R4). No extra top margin — parent flex
 * `gap` handles spacing.
 */
const RootTitleRow = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.88rem;
    font-weight: 700;
    line-height: 1.3;
    word-break: break-word;
    overflow-wrap: anywhere;
    margin: 0;

    @media (max-width: 1000px) {
    }
`;
/**
 * No-op placeholder — the old rendered a horizontal rule between title
 * and body, but `CardView` has no such divider and the new flex `gap`
 * handles spacing. Kept as a stub so the JSX `<TitleDivider />` sites
 * below still compile without changes.
 */
const TitleDivider = styled.div`
    display: none;
`;

// Reuse the same visual style as topic links in the feed
// BreadcrumbLink removed (unused)

const StyledProfileLink = styled(Link)`
    color: ${({
    $tierColor,
    theme
}) => $tierColor} !important;
    text-decoration: none;
    font-weight: bold;
    ${() => tooltipStyles()}

    &:hover {
        color: ${({
    $tierColor,
    theme
}) => $tierColor} !important;
    }
`;
const StyledTopicLink = styled(Link)`
    color: ${({
    theme
}) => theme.colors.link};
    text-decoration: none;
    font-weight: bold;
    text-transform: lowercase;

    &:hover {
        color: ${({
    theme
}) => theme.colors.linkHover};
    }
`;
const BackButton = styled.button`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: transparent;
    border: none;
    color: ${({
    theme
}) => theme.colors.subtleText};
    cursor: pointer;
    font-size: 0.9rem;
    font-weight: 600;
    padding: 0.5rem 0.5rem 0.5rem 0;
    margin-bottom: 0.25rem;
    transition: color 0.2s ease;

    &:hover {
        color: ${({
    theme
}) => theme.colors.text};
    }

    svg {
        width: 18px;
        height: 18px;
    }
`;

/**
 * Header row — matches `CardView::HeaderRow` so the post-details screen
 * reads the same as the feed card. Left side holds the metadata cluster
 * (topic · user · time · tag). Right side holds the actions (follow,
 * menu). Flat row, no border, no margin — parent gap handles spacing.
 */
const MetaInfoRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    min-width: 0;
    margin: 0;
    padding: 0;
    border: none;

    @media (max-width: 768px) {
        flex-wrap: wrap;
    }
`;
/**
 * Metadata cluster (topic · user · time · tag) on the left side of the
 * header row. Ported 1:1 from `CardView::HeaderMeta`: 0.62rem font,
 * `feedCtrlText` color, flex-wrap, tight gap.
 */
const MetaInfoRowLeft = styled.div`
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.2rem 0.3rem;
    min-width: 0;
    font-size: 0.62rem;
    font-weight: 400;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    line-height: 1.2;

    & a {
        color: ${({ theme }) => theme.colors.feedCtrlText};
        text-decoration: none;
        font-weight: 500;
    }
    & a:hover {
        color: ${({ theme }) => theme.colors.text};
        text-decoration: none;
    }
    & span {
        font-size: 0.62rem;
        font-weight: 400;
    }
`;
/**
 * Bullet separator between metadata items. Matches `CardView::HeaderDot`.
 */
const MetaSeparator = styled.span`
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-size: 0.75rem;
    font-weight: 700;
    line-height: 1;
`;
/**
 * Inline collapse/expand toggle shown next to the comment timestamp.
 * Rendered as a plain text chunk (no box, no button chrome) so it reads
 * as quiet metadata in the same rhythm as author / time / tag. Lifts
 * to `text` on hover.
 */
const CollapseToggle = styled.button`
    appearance: none;
    background: none;
    border: none;
    padding: 0 0.15rem;
    margin: 0;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-family: inherit;
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1;
    cursor: pointer;
    transition: color 0.12s ease;
    display: inline-flex;
    align-items: center;
    justify-content: center;

    svg {
        width: 12px;
        height: 12px;
        fill: none;
        stroke: currentColor;
        stroke-width: 2.5;
        stroke-linecap: round;
        stroke-linejoin: round;
        transition: transform 0.15s ease;
    }

    &:hover {
        color: ${({ theme }) => theme.colors.text};
    }
`;

// Mobile root post meta - two rows: author+menu, then topic+time
const MobileRootMeta = styled.div`
    display: none;
    @media (max-width: 600px) {
        display: flex;
        flex-direction: column;
        gap: 0.15rem;
        margin: 0;
        padding: 0;
        border: none;
        color: ${({ theme }) => theme.colors.feedCtrlText};
        font-weight: 400;
        line-height: 1.2;
    }
`;
const MobileRootMetaTop = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.2;
    & a {
        font-size: inherit;
        line-height: inherit;
    }
`;
const MobileRootMetaBottom = styled.div`
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.2rem 0.3rem;
    font-size: 0.62rem;
    font-weight: 400;
    line-height: 1.2;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    & a {
        color: ${({ theme }) => theme.colors.feedCtrlText};
        text-decoration: none;
        font-weight: 500;
        font-size: inherit;
        line-height: inherit;
    }
    & a:hover {
        color: ${({ theme }) => theme.colors.text};
    }
`;

// Desktop version - hide on mobile for root posts
const DesktopMetaInfoRow = styled(MetaInfoRow)`
    @media (max-width: 600px) {
        display: ${({
    $hideOnMobile
}) => $hideOnMobile ? 'none' : 'flex'};
    }
`;
const TagBadge = styled.span`
    display: inline-flex;
    align-items: center;
    padding: 0.1rem 0.45rem;
    border-radius: 999px;
    background: ${({
    $tag
}) => tagColors[$tag]?.bg || tagColors.default.bg};
    color: ${({
    $tag
}) => tagColors[$tag]?.text || tagColors.default.text};
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: lowercase;
    border: 1px solid ${({
    $tag
}) => tagColors[$tag]?.border || tagColors.default.border};
`;

/**
 * Ellipsis more-menu button. Matches `CardView::MoreButton` (28x28
 * circle, transparent fill, `feedCtrlHoverBg` on hover, no transform).
 */
const MenuButton = styled.button`
    appearance: none;
    width: 28px;
    height: 28px;
    border-radius: 9999px;
    border: none;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    margin-right: -4px;
    transition: background 0.12s ease;

    &:hover { background: ${({ theme }) => theme.colors.feedCtrlHoverBg}; }

    svg {
        width: 16px;
        height: 16px;
        fill: currentColor;
    }
`;
const MenuContainer = styled.div`
    position: relative;
    display: inline-block;
`;
/**
 * Post / comment options dropdown.
 *
 * Matches `CardView::Menu` 1:1 so every dropdown in the theme reads the
 * same — same `menuBg` surface, same 10px radius, same border, same
 * shadow. `position: fixed` is preserved from the old implementation
 * because the dropdown gets portaled into `document.body` via
 * `ReactDOM.createPortal` (so it escapes the post card and can anchor
 * next to the ellipsis button on every screen size).
 */
const MenuDropdown = styled.div`
    position: fixed;
    min-width: max-content;
    width: max-content;
    padding: 0;
    background: ${({ theme }) => theme.colors.menuBg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    z-index: 99999;
    display: flex;
    flex-direction: column;
    gap: 0;
    overflow: hidden;
`;
/**
 * Dropdown row — matches `CardView::MenuItemBtn` 1:1: 3 slots (leading
 * icon → label → trailing gap), `sidebarItemText` at rest lifting to
 * `menuItemHoverText` on hover, `menuSelectedBg` on hover for background
 * tile. Danger rows saturate to `voteDown` on hover.
 *
 * The old implementation used a `data-danger="true"` attribute to flip
 * the text red; we keep that working via an attribute selector AND the
 * modern `$danger` transient prop so existing JSX doesn't need to
 * change.
 */
const MenuItem = styled.button`
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.6rem;
    width: 100%;
    padding: 10px 14px;
    white-space: nowrap;
    background: transparent;
    border: none;
    border-radius: 0;
    color: ${({ theme }) => theme.colors.sidebarItemText};
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: 400;
    text-align: left;
    cursor: pointer;
    line-height: 1;
    transition: background 0.12s ease, color 0.12s ease;

    &[data-danger="true"] {
        color: ${({ theme }) => theme.colors.menuDangerText};
    }

    &:hover {
        background: ${({ theme }) => theme.colors.menuItemHoverBg};
        color: ${({ theme }) => theme.colors.menuItemHoverText};
    }

    &[data-danger="true"]:hover {
        background: ${({ theme }) => theme.colors.menuItemHoverBg};
        color: ${({ theme }) => theme.colors.voteDown};
    }

    & > svg,
    & > span > svg {
        width: 17px;
        height: 17px;
        flex-shrink: 0;
        color: inherit;
    }
`;
/**
 * Markdown + media content slot inside the root post and each comment.
 * Font size matches `CardView::Body` so the post-details view reads the
 * same as feed cards (R4 visual parity with CardView).
 */
const StyledContentArea = styled.div`
    margin: 0;
    padding: 0;
    color: ${({ theme }) => theme.colors.cardBodyText};
    font-weight: normal;
    font-size: 0.74rem;
    line-height: 1.5;
    overflow-wrap: anywhere;
    word-break: break-word;
    white-space: normal;
    max-width: 100%;

    p { margin: 0 0 0.5rem; }
    p:last-child { margin-bottom: 0; }
    a { color: ${({ theme }) => theme.colors.link}; }

    img, video {
        max-width: 100%;
        max-height: 600px;
    }

    @media (max-width: 1000px) {
    }
`;
/**
 * Column wrapper inside `PostCard` / `CommentCard`. Uses `display: contents`
 * so its children inherit the parent card's flex `gap` rhythm — the card
 * itself is already `flex-direction: column`, so no extra nesting is
 * needed. This makes post/comment body + title + meta + action row all
 * live in a single flex track, matching `CardView::Card` spacing exactly.
 */
const ColumnFlex = styled.div`
    display: contents;
`;
const MainContentWrapper = styled.div`
    width: 100%;
    min-width: 0;
    min-height: 120vh;
    overflow-x: hidden;
    box-sizing: border-box;
`;
/**
 * Inline reply composer block. Flat wrapper that sits under the active
 * post/comment. Uses the feed card rhythm: no card chrome of its own,
 * content separated from the surrounding post/comment by a top divider
 * (R3), tight 0.45rem vertical gap so media row → editor → action row
 * read as a single unit.
 *
 * Also overrides the nested `MarkdownEditor` shared component so the
 * textarea + toolbar read against the mirageapp theme instead of the
 * bluemoon-era `panelAlt` card look. The overrides are scoped to this
 * wrapper via descendant selectors so `MarkdownEditor` stays untouched
 * for any other route that uses it (CreatePost, edit flows, etc.).
 */
const StyledReply = styled.div`
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 0.35rem;
    width: 100%;
    padding: 0.5rem 0 0.4rem;
    margin-top: 0.15rem;
    background: transparent;
    border: none;
    border-top: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 0;

    /* --- MarkdownEditor textarea override -----------------------------
     * Sits flat on the main bg canvas (R1). Hover/focus stay subtle and
     * neutral — no blue ring; uses borderStrong instead so the input
     * doesn't compete with link/highlight blues elsewhere on the page.
     */
    textarea {
        background: ${({ theme }) => theme.colors.bg} !important;
        border: 1px solid ${({ theme }) => theme.colors.border} !important;
        border-radius: 10px !important;
        padding: 0.45rem 0.7rem !important;
        font-size: 0.68rem !important;
        font-weight: 400 !important;
        line-height: 1.45 !important;
        color: ${({ theme }) => theme.colors.text} !important;
        transition: border-color 0.12s ease, background 0.12s ease !important;
        box-shadow: none !important;
        min-height: 60px !important;
    }
    textarea:hover {
        border-color: ${({ theme }) => theme.colors.borderStrong} !important;
    }
    textarea:focus {
        outline: none !important;
        border-color: ${({ theme }) => theme.colors.borderStrong} !important;
        box-shadow: none !important;
    }
    textarea:disabled {
        opacity: 0.55 !important;
    }

    /* --- MarkdownEditor toolbar override -------------------------------
     * Scoped to [data-mirageapp-editor]. Toolbar buttons render as quiet
     * 24x24 pills that lift to feedCtrlHoverBg on hover.
     */
    [data-mirageapp-editor] button[type='button'] {
        background: transparent !important;
        border: 1px solid transparent !important;
        border-radius: 6px !important;
        min-width: 24px !important;
        height: 24px !important;
        padding: 2px 4px !important;
        color: ${({ theme }) => theme.colors.feedCtrlText} !important;
        transition: background 0.12s ease, color 0.12s ease !important;
        box-shadow: none !important;
    }
    [data-mirageapp-editor] button[type='button'] svg,
    [data-mirageapp-editor] button[type='button'] .md-icon {
        max-width: 14px !important;
        max-height: 14px !important;
        font-size: 0.78rem !important;
    }
    /* Bold (B) and Italic (I) glyphs render as text via styled spans, so
     * the SVG/font-size rules above don't reach them. Shrink them here.
     */
    [data-mirageapp-editor] button[type='button'] > span {
        font-size: 0.6rem !important;
        line-height: 1 !important;
    }
    [data-mirageapp-editor] button[type='button']:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.feedCtrlHoverBg} !important;
        color: ${({ theme }) => theme.colors.text} !important;
        border-color: transparent !important;
    }
    [data-mirageapp-editor] button[type='button'][data-active='true'] {
        background: ${({ theme }) => theme.colors.feedCtrlHoverBg} !important;
        color: ${({ theme }) => theme.colors.text} !important;
        border-color: transparent !important;
    }

    /* --- Preview toggle (custom checkmark) ----------------------------
     * Matches the CreatePostView preview pill exactly: rounded ghost pill
     * with a small square checkbox. Checked state fills rgb(68,109,228)
     * and centers a white checkmark via translate(-50%, -55%) so the
     * rotated glyph lands visually in the middle of the box.
     */
    [data-mirageapp-editor] label {
        background: transparent !important;
        background-color: transparent !important;
        border: 1px solid ${({ theme }) => theme.colors.border} !important;
        border-radius: 9999px !important;
        padding: 0 0.55rem !important;
        font-size: 0.62rem !important;
        font-weight: 500 !important;
        color: ${({ theme }) => theme.colors.subtleText} !important;
        gap: 0.35rem !important;
        height: 1.5rem !important;
        transition: color 0.12s ease, border-color 0.12s ease !important;
    }
    [data-mirageapp-editor] label:hover {
        background: transparent !important;
        background-color: transparent !important;
        color: ${({ theme }) => theme.colors.text} !important;
        border-color: ${({ theme }) => theme.colors.borderStrong} !important;
    }
    [data-mirageapp-editor] label input[type='checkbox'] {
        appearance: none !important;
        -webkit-appearance: none !important;
        width: 0.9rem !important;
        height: 0.9rem !important;
        border-radius: 4px !important;
        border: 1px solid ${({ theme }) => theme.colors.borderStrong} !important;
        background: transparent !important;
        background-color: transparent !important;
        cursor: pointer !important;
        position: relative !important;
        margin: 0 !important;
        flex-shrink: 0 !important;
        transition: border-color 0.12s ease !important;
    }
    [data-mirageapp-editor] label input[type='checkbox']:checked {
        background: rgb(68, 109, 228) !important;
        background-color: rgb(68, 109, 228) !important;
        border-color: rgb(68, 109, 228) !important;
    }
    [data-mirageapp-editor] label input[type='checkbox']:checked::after {
        content: '' !important;
        position: absolute !important;
        left: 50% !important;
        top: 46% !important;
        width: 4px !important;
        height: 8px !important;
        border: solid #ffffff !important;
        border-width: 0 2px 2px 0 !important;
        transform: translate(-50%, -55%) rotate(45deg) !important;
        background: transparent !important;
    }

    /* --- Preview pane --------------------------------------------------
     * LivePreviewContainer is the LAST child of EditorContainer (which is
     * itself the only direct child of [data-mirageapp-editor]). Override
     * it to a subtle composerPreviewBg tile with lighter body text.
     */
    [data-mirageapp-editor] > div > :last-child {
        background: ${({ theme }) => theme.colors.composerPreviewBg} !important;
        border: 1px solid ${({ theme }) => theme.colors.border} !important;
        border-radius: 8px !important;
        padding: 0.55rem 0.7rem !important;
        font-size: 0.7rem !important;
        font-weight: 400 !important;
        color: ${({ theme }) => theme.colors.text} !important;
    }
    [data-mirageapp-editor] > div > :last-child p,
    [data-mirageapp-editor] > div > :last-child li,
    [data-mirageapp-editor] > div > :last-child span {
        font-weight: 400 !important;
    }
    [data-mirageapp-editor] > div > :last-child > div:first-child {
        font-size: 0.5rem !important;
        font-weight: 600 !important;
        color: ${({ theme }) => theme.colors.subtleText} !important;
        margin-bottom: 0.35rem !important;
    }

    /* --- Submit / Cancel buttons --------------------------------------
     * Submit: flat pill in followBtnBg (matches the topic Follow pill in
     * CardView and the post-details header) so the primary CTA across the
     * theme reads with the same blue. Cancel: ghost pill, lighter weight.
     */
    button[type='submit'] {
        background: ${({ theme }) => theme.colors.followBtnBg} !important;
        color: #ffffff !important;
        border: 1px solid ${({ theme }) => theme.colors.followBtnBg} !important;
        box-shadow: none !important;
        font-weight: 500 !important;
        font-size: 0.7rem !important;
        padding: 0.35rem 0.85rem !important;
        border-radius: 999px !important;
        background-image: none !important;
        text-transform: none !important;
        transform: none !important;
        transition: background 0.12s ease, border-color 0.12s ease !important;
    }
    button[type='submit']:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.followBtnBgHover} !important;
        border-color: ${({ theme }) => theme.colors.followBtnBgHover} !important;
        box-shadow: none !important;
        transform: none !important;
    }
    button[type='submit']:disabled {
        opacity: 0.55 !important;
    }

    /* Cancel button — flagged via data-mirageapp-cancel on the JSX so we
     * never accidentally restyle other buttons in the composer.
     */
    button[data-mirageapp-cancel] {
        background: transparent !important;
        color: ${({ theme }) => theme.colors.subtleText} !important;
        border: 1px solid ${({ theme }) => theme.colors.border} !important;
        box-shadow: none !important;
        font-weight: 500 !important;
        font-size: 0.7rem !important;
        padding: 0.35rem 0.85rem !important;
        border-radius: 999px !important;
        background-image: none !important;
        transform: none !important;
        transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease !important;
    }
    button[data-mirageapp-cancel]:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.feedCtrlHoverBg} !important;
        color: ${({ theme }) => theme.colors.text} !important;
        border-color: ${({ theme }) => theme.colors.borderStrong} !important;
        transform: none !important;
    }
`;

// Mobile reply overlay - fullscreen focused reply experience (leaves room for bottom nav)
const MobileReplyOverlay = styled.div`
    display: none;
    
    @media (max-width: 600px) {
        display: flex;
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 56px; /* Leave room for bottom nav */
        z-index: 10001;
        flex-direction: column;
        background: ${({
    theme
}) => theme.colors.bg};
        overflow-y: auto;
        -webkit-overflow-scrolling: touch;
    }
`;
const MobileReplyHeader = styled.div`
    display: flex;
    align-items: center;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.bg};
    position: sticky;
    top: 0;
    z-index: 1;
`;
const MobileReplyBackButton = styled.button`
    display: flex;
    align-items: center;
    gap: 0.35rem;
    background: transparent;
    border: none;
    color: ${({
    theme
}) => theme.colors.text};
    cursor: pointer;
    font-size: 0.85rem;
    font-weight: 600;
    padding: 0.4rem;
    margin: -0.4rem;
    
    svg {
        width: 18px;
        height: 18px;
    }
`;
const MobileReplyContent = styled.div`
    flex: 1;
    display: flex;
    flex-direction: column;
    padding: 0.75rem;
    gap: 0.5rem;
    padding-bottom: calc(0.75rem + env(safe-area-inset-bottom, 0px));
`;
const MobileReplyPostPreview = styled.div`
    background: transparent;
    border: none;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 0;
    padding: 0.5rem 0 0.65rem;
`;
const MobileReplyPostMeta = styled.div`
    font-size: 0.65rem;
    color: ${({
    theme
}) => theme.colors.mutedText};
    margin-bottom: 0.3rem;
    display: flex;
    align-items: center;
    gap: 0.25rem;
`;
const MobileReplyPostContent = styled.div`
    font-size: 0.8rem;
    color: ${({
    theme
}) => theme.colors.text};
    line-height: 1.4;
`;
/**
 * Submit button cluster on the right side of the composer action row.
 * Keeps the submit + cancel buttons tightly grouped.
 */
const StyledSubmitButtonContainer = styled.div`
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: nowrap;
    flex-shrink: 0;
`;
/**
 * Character counter under the reply editor. Tiny, `subtleText` at rest,
 * `voteDown` when over the limit (same red the CardView action row uses).
 */
const ReplyCounter = styled.span`
    font-size: 0.58rem;
    font-weight: 500;
    line-height: 1.2;
    color: ${({ $warn, theme }) =>
        $warn ? theme.colors.voteDown : theme.colors.subtleText};
`;
/**
 * Reply composer action row — character counter on the left, submit /
 * cancel buttons on the right. Flat row with a top divider matching the
 * feed-card separator rhythm.
 */
const ReplyActionsRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    gap: 0.5rem;
    flex-wrap: nowrap;
    padding-top: 0.4rem;
    border-top: 1px solid ${({ theme }) => theme.colors.borderSubtle};
`;
/**
 * Inline error banner under the reply editor. Uses `voteDown` for tint
 * and `buttonDangerBg` for the fill so the styling flows through the R2
 * token pairs rather than raw hex values.
 */
const ReplyErrorMessage = styled.div`
    background: ${({ theme }) => theme.colors.buttonDangerBg};
    border: 1px solid ${({ theme }) => theme.colors.buttonDangerBorder};
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    margin-top: 0.25rem;
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.65rem;
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

const CommentsHeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.55rem 1rem 0.45rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};

    @media (max-width: 600px) {
        padding: 0.45rem 0.85rem 0.35rem;
    }
`;
const CommentsHeaderTitle = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.72rem;
    font-weight: 700;
    line-height: 1.2;
`;
const CommentsHeaderCount = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-weight: 500;
`;
const VPStateBlock = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
    padding: 3rem 1.25rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.subtleText};
`;
const VPStateIcon = styled.div`
    width: 48px;
    height: 48px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 1px solid ${({ theme }) => theme.colors.border};

    svg {
        width: 22px;
        height: 22px;
        color: ${({ $tone, theme }) => $tone === 'danger' ? theme.colors.voteDown : theme.colors.subtleText};
    }
`;
const VPStateTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.85rem;
    font-weight: 700;
`;
const VPStateMessage = styled.div`
    font-size: 0.72rem;
    line-height: 1.55;
    max-width: 24rem;
    color: ${({ theme }) => theme.colors.subtleText};
`;
const VPLoadingSpinner = styled.div`
    width: 28px;
    height: 28px;
    border: 3px solid ${({ theme }) => theme.colors.border};
    border-top: 3px solid ${({ theme }) => theme.colors.focusBlue};
    border-radius: 50%;
    animation: vpSpin 0.8s linear infinite;

    @keyframes vpSpin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;

/**
 * Blocked-post state — visual twin of `MainView`'s `BlockedTopicState`.
 * Shown when the viewer navigates to `/p/<id>` for a post they have
 * blocked. Sits on the main feed canvas (`theme.colors.bg`) with no
 * divider so it reads as part of the feed column, not a separate panel.
 * Unblock uses the same red `Button variant="danger"` style the rest of
 * the Blocks surface uses (06.3 polish round 5).
 */
const BlockedPostState = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
    padding: 3rem 1.25rem;
    text-align: center;
    background: ${({ theme }) => theme.colors.bg};
    box-sizing: border-box;
`;
const BlockedPostIcon = styled.div`
    width: 56px;
    height: 56px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.voteDown};

    svg { width: 26px; height: 26px; }
`;
const BlockedPostTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.95rem;
    font-weight: 700;
`;
const BlockedPostMessage = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.78rem;
    line-height: 1.5;
    max-width: 26rem;
`;
const BlockedPostActions = styled.div`
    display: flex;
    gap: 0.5rem;
    margin-top: 0.35rem;
`;

const MetaRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0;
    padding: 0;
    border: none;
    line-height: 1;

    @media (max-width: 600px) {
        flex-wrap: wrap;
        gap: 0.35rem;

        /* Hide "share" text on mobile, keep icon */
        .share-text {
            display: none;
        }
    }
`;
/**
 * Thin flex spacer that pushes the trailing actions (block/share) to the
 * right edge. Matches `CardView::Spacer`.
 */
const MetaSeparatorAction = styled.span`
    flex: 1 1 auto;
    min-width: 0;
`;
/**
 * Inline bullet separator used between tightly-clustered action items
 * (e.g. vote container and reply button) on the left side of the
 * action row. Rendered as a small `·` glyph in `feedCtrlText` so it
 * reads as quiet metadata, not a heavy divider.
 */
const DotSep = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-size: 0.75rem;
    font-weight: 700;
    line-height: 1;
    flex-shrink: 0;
`;
/**
 * Leading glyph slot inside an `ActionButton`. The icon lives inside a
 * pill so this just inherits sizing; kept as a span for compat with the
 * existing JSX.
 */
const Icon = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: inherit;

    svg {
        width: 18px;
        height: 18px;
        fill: currentColor;
    }
`;
/**
 * Pill-shaped action button — matches `CardView::ActionPill`. Used for
 * comment count, reply, block/report, share. 32px tall, rounded, filled
 * with `actionIconBg`, no border, no transform on hover. Anchor by
 * default (legacy `<a>` usage across the file); `as="button"` works too.
 */
const ActionButton = styled.a`
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.3rem;
    height: 32px;
    padding: 0 12px;
    border-radius: 9999px;
    border: none;
    background: ${({ theme }) => theme.colors.actionIconBg};
    color: ${({ theme, $danger }) =>
        $danger ? theme.colors.voteDown : theme.colors.feedCtrlText};
    font-family: inherit;
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1;
    text-decoration: none;
    white-space: nowrap;
    cursor: pointer;
    transition: background 0.12s ease, color 0.12s ease;

    &:visited { color: ${({ theme, $danger }) =>
        $danger ? theme.colors.voteDown : theme.colors.feedCtrlText}; }
    &:hover,
    &:visited:hover {
        background: ${({ theme }) => theme.colors.actionIconHoverBg};
        color: ${({ theme, $danger }) =>
            $danger ? theme.colors.voteDown : theme.colors.text};
    }

    svg { width: 16px; height: 16px; fill: currentColor; }

    @media (max-width: 600px) {
        height: 32px;
        padding: 0 10px;
    }
`;
const BlockErrorMessage = styled.div`
    background: ${({ theme }) => theme.colors.buttonDangerBg};
    border: 1px solid ${({ theme }) => theme.colors.buttonDangerBorder};
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    margin: 0.35rem 0;
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.65rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;
const BlockSuccessMessage = styled.div`
    background: ${({ theme }) => theme.colors.buttonSuccessBg};
    border: 1px solid ${({ theme }) => theme.colors.buttonSuccessBorder};
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    margin: 0.35rem 0;
    color: ${({ theme }) => theme.colors.voteUp};
    font-size: 0.65rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;
const BlockConfirmMessage = styled.div`
    background: ${({ theme }) => theme.colors.inboxHighlightBg};
    border: 1px solid ${({ theme }) => theme.colors.inboxHighlightRail};
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    margin: 0.35rem 0;
    color: ${({ theme }) => theme.colors.inboxHighlightRail};
    font-size: 0.65rem;
    display: flex;
    flex-direction: column;          /* message on top, buttons below */
    align-items: flex-start;         /* left align content */
    gap: 0.75rem;
    width: 100%;                     /* fill the column on mobile like Block Post */
    & > span:first-child {
        display: block;              /* ensure full-width message */
        width: 100%;
    }
`;
const ConfirmButtons = styled.div`
    display: flex;
    gap: 0.5rem;
    align-items: center;
    flex-wrap: nowrap;
    width: 100%;
    justify-content: flex-end;
`;
// `ReportInput` removed (06.3) — replaced by the `ConfirmDialog`
// textarea at the route root.

// Returns absolute local timestamp: YYYY-MM-DD HH:MM:SS

function ViewPostView({
    state,
    updatePost
}) {
    const {
        root,
        setRoot,
        setChildren,
        loading,
        setLoading,
        blockError,
        blockSuccess,
        isBlocking,
        confirmBlockPost,
        confirmBlockUser,
        confirmBlockTopic,
        confirmDeletePost,
        isDeleting,
        deleteMessages,
        deletedPosts,
        confirmSuspendQuests,
        isSuspending,
        suspendDuration,
        setSuspendDuration,
        suspendSuccess,
        confirmUnsuspendQuests,
        isUnsuspending,
        userSuspendedMap,
        confirmDonate,
        setConfirmDonate,
        donateAmount,
        donateMessages,
        giftSubMessages,
        confirmGiftSub,
        confirmAward,
        setConfirmAward,
        isAwarding,
        awardMessages,
        confirmReportPost,
        reportReason,
        setReportReason,
        isReporting,
        reportMessages,
        error,
        setError,
        shareMessages,
        setShareMessages,
        showContext,
        actualRootPost,
        cardSize,
        theme,
        location,
        navigate,
        questsEnabled,
        isMobile,
        goBackToFeed,
        viewerAddress,
        topicFollowHover,
        setTopicFollowHover,
        isTopicPending,
        isUserPending,
        formatTopicStatus,
        formatUserStatus,
        isSendPending,
        formatSendStatus,
        isSubscribePending,
        formatSubscribeStatus,
        openMenuId,
        setOpenMenuId,
        menuPosition,
        setMenuPosition,
        menuButtonRefs,
        menuDropdownRef,
        isFollowingAuthor,
        handleFollowToggle,
        isSubscribedTopic,
        handleTopicFollowToggle,
        replyUploadProgress,
        setReplyUploadProgress,
        replyEditorUpload,
        setReplyEditorUpload,
        replyIsUploading,
        setReplyIsUploading,
        replyAttachedType,
        setReplyAttachedType,
        replyAttachedUrl,
        setReplyAttachedUrl,
        replyThumbLoading,
        setReplyThumbLoading,
        replySubmitError,
        setReplySubmitError,
        replySubmitStatus,
        replyErrorClearTimeoutRef,
        mobileReplyOverlayRef,
        limits,
        closeReply,
        toggleReply,
        handleBlockPost,
        confirmBlockPostAction,
        cancelBlockPost,
        handleBlockUser,
        confirmBlockUserAction,
        cancelBlockUser,
        handleBlockTopic,
        confirmBlockTopicAction,
        cancelBlockTopic,
        handleReport,
        confirmReportAction,
        cancelReport,
        handleDeletePost,
        confirmDeletePostAction,
        cancelDeletePost,
        handleSuspendFromQuests,
        confirmSuspendFromQuests,
        cancelSuspendFromQuests,
        fetchUserSuspensionStatus,
        handleUnsuspendFromQuests,
        confirmUnsuspendFromQuests,
        cancelUnsuspendFromQuests,
        handleDonate,
        handleGiftSubscription,
        confirmGiftSubAction,
        cancelGiftSub,
        userBalanceUmirage,
        AWARD_TYPES,
        giftSubscriptionLabel,
        subFeeLabel,
        agentFeeLabel,
        getAwardCost,
        handleGiveAward,
        confirmAwardAction,
        openEdit,
        handleEditSubmit,
        confirmDonateAction,
        cancelDonate,
        handleDonateAmountChange,
        formatDonateAmount,
        handleReplyChange,
        handleReplyDragOver,
        handleReplyDragLeave,
        handleReplyDrop,
        handleSubmit,
        postId,
        focusedCommentId,
        actualRootPostId,
        lastVisitTs,
        setLastVisitTs,
        rootFlash,
        normalizedHighlightId,
        annotated,
        depthError
    } = useViewPost({
        state,
        updatePost
    });

    /**
     * Blocked-post affordance (06.3 polish round 5) — wired to the same
     * `useBlocks` hook BlocksView uses, so unblocking from this page
     * instantly updates `/blocks` and vice versa. Renders a dedicated
     * `BlockedPostState` panel (replacing the post content + comments)
     * when the current post_id is in the viewer's blocked list.
     */
    const {
        blockedPosts,
        isPostPending: isBlockPostPending,
        formatPostStatus: formatBlockPostStatus,
        handleUnblockPost
    } = useBlocks({ state });
    const blockedPostIdLower = postId ? String(postId).trim().toLowerCase() : '';
    const isPostBlocked = !!blockedPostIdLower && blockedPosts.some(
        p => String(p || '').trim().toLowerCase() === blockedPostIdLower
    );
    const isUnblockPostPending = isPostBlocked && isBlockPostPending(blockedPostIdLower);
    const unblockPostStatus = isPostBlocked ? formatBlockPostStatus(blockedPostIdLower) : '';
    /* After the user unblocks the post inline we need to re-fetch the
     * content because the initial load (made while the post was still
     * blocked) either failed server-side or was short-circuited. We use
     * a nonce counter that's included in the fetch effect's deps so
     * bumping it re-triggers the effect; we also reset loading/error so
     * the spinner shows during the refetch instead of the stale error
     * state. (06.3 polish round 6.) */
    const [refetchNonce, setRefetchNonce] = useState(0);
    const handleUnblockBlockedPost = e => {
        if (!blockedPostIdLower) return;
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        handleUnblockPost(e, blockedPostIdLower);
        // Reset loading/error and bump the nonce so the comments effect
        // re-fetches the post now that it's no longer blocked.
        try { setLoading(true); } catch (_) { /* noop */ }
        try { setError(null); } catch (_) { /* noop */ }
        setRefetchNonce(n => n + 1);
    };

    const commentsRequestRef = useRef(0);
    const commentsAutoOpenTimersRef = useRef(new Set());
    useEffect(() => {
        const autoOpenTimeouts = commentsAutoOpenTimersRef.current;
        const post_id = postId;
        const requestId = commentsRequestRef.current + 1;
        commentsRequestRef.current = requestId;
        let cancelled = false;
        if (post_id) {
            const viewerAddress = Storage.load("publicKey", "");
            Api.get('get_comments', {
                post_id,
                address: viewerAddress
            }).then(data => {
                if (cancelled || commentsRequestRef.current !== requestId) return;
                setLoading(false);
                setRoot(data.root);
                setChildren(data.children);
                try {
                    const f = tx && tx['reconcileAfterCommentsFetch'];
                    if (typeof f === 'function') f(post_id, data.root, data.children);
                } catch (_) { }
                // Mark current comment count as visited
                if (data.root && data.root.comments !== undefined) {
                    try {
                        Storage.setLastVisitCommentCount(post_id, data.root.comments);
                    } catch (_) { }
                }
                // Capture previous visit timestamp for highlight, then set new visit time
                try {
                    const prevTs = Storage.getLastVisitTimestamp(post_id);
                    if (prevTs !== null && !isNaN(Number(prevTs))) setLastVisitTs(Number(prevTs));
                } catch (_) {
                    setLastVisitTs(null);
                }
                // Mark visit timestamp after capturing previous, for highlighting
                try {
                    const nowSec = Math.floor(Date.now() / 1000);
                    Storage.setLastVisitTimestamp(post_id, nowSec);
                } catch (_) { }
                // Auto-open edit if edit query parameter is present and user owns the post
                const params = new URLSearchParams(location.search);
                const shouldEdit = params.get('edit') === 'true';
                if (shouldEdit && data.root) {
                    const currentUserAddress = state && state.publicKey ? String(state.publicKey).trim().toLowerCase() : Storage.load('publicKey', '').trim().toLowerCase();
                    const postAuthorAddress = data.root && data.root.user_id ? String(data.root.user_id).trim().toLowerCase() : '';
                    const isAuthor = currentUserAddress && postAuthorAddress && currentUserAddress === postAuthorAddress;
                    if (isAuthor) {
                        // Small delay to ensure state is updated
                        const timeoutId = setTimeout(() => {
                            autoOpenTimeouts.delete(timeoutId);
                            if (cancelled || commentsRequestRef.current !== requestId) return;
                            openEdit(data.root);
                        }, 100);
                        autoOpenTimeouts.add(timeoutId);
                    }
                }
                // Auto-open donate dialog if donate query parameter is present
                const shouldDonate = params.get('donate') === 'true';
                if (shouldDonate && data.root && data.root.user_id) {
                    const timeoutId = setTimeout(() => {
                        autoOpenTimeouts.delete(timeoutId);
                        if (cancelled || commentsRequestRef.current !== requestId) return;
                        setConfirmDonate(data.root.user_id);
                    }, 100);
                    autoOpenTimeouts.add(timeoutId);
                }
                // Do not auto-open reply; user explicitly opens when needed
            }).catch(error => {
                if (cancelled || commentsRequestRef.current !== requestId) return;
                setLoading(false);
                let errorMessage = "An unknown error occurred";
                const msg = error && error.message ? String(error.message) : "";
                if (/HTTP\s*404/i.test(msg)) {
                    errorMessage = <span>
                        <br />&nbsp;
                        <strong>No post with id:</strong><br />
                        <span style={{
                            fontSize: '0.6rem'
                        }}>{post_id}</span>
                        <br />
                        <br />
                        <span style={{
                            fontSize: '0.75rem'
                        }}>
                            Try Again in ~10s; it may be still propagating across the network.
                        </span>
                        <br />&nbsp;
                    </span>;
                } else if (msg) {
                    errorMessage = msg;
                }
                setError(errorMessage);
            });
        }
        return () => {
            cancelled = true;
            autoOpenTimeouts.forEach((timeoutId) => clearTimeout(timeoutId));
            autoOpenTimeouts.clear();
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [postId, refetchNonce]);

    // When in focused view, fetch the focused comment's children separately
    // This ensures we get 6 levels of children from the focused comment, not limited by its depth from root

    // Blocked-post short circuit — when the viewer has blocked this
    // post, render only the `BlockedPostState` panel (no content, no
    // comments). Mirrors the blocked-topic / blocked-user experience.
    // The viewer can unblock inline; once the tx settles the hook flips
    // `isPostBlocked` back to false and the full post loads normally.
    if (isPostBlocked) {
        return <ContentGrid>
            <div>
                <ModernPostFeed>
                    <BackButton onClick={goBackToFeed}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <line x1="19" y1="12" x2="5" y2="12"></line>
                            <polyline points="12 19 5 12 12 5"></polyline>
                        </svg>
                        Back
                    </BackButton>
                    <BlockedPostState role="region" aria-label="Blocked post">
                        <BlockedPostIcon aria-hidden="true">
                            <HiNoSymbol />
                        </BlockedPostIcon>
                        <BlockedPostTitle>This post is blocked</BlockedPostTitle>
                        <BlockedPostMessage>
                            You have blocked this post, so it's hidden from every feed you see. Unblock to view it — you can always re-block it later from the post menu or the Blocks page.
                        </BlockedPostMessage>
                        <BlockedPostActions>
                            {/* Standalone state panel — use `size="md"` (not
                                `sm` like BlocksView rows) so the CTA has the
                                same visual height as the primary buttons
                                used elsewhere in the app. No radius override;
                                Button's default `md` radius applies. */}
                            <Button
                                variant="danger"
                                size="md"
                                minWidth="5.5rem"
                                disabled={isUnblockPostPending}
                                loading={isUnblockPostPending}
                                onClick={handleUnblockBlockedPost}
                            >
                                {isUnblockPostPending ? unblockPostStatus || 'Processing' : 'Unblock post'}
                            </Button>
                        </BlockedPostActions>
                    </BlockedPostState>
                </ModernPostFeed>
            </div>
        </ContentGrid>;
    }

    if (loading || error || depthError) {
        return <ContentGrid>
            <div>
                <ModernPostFeed>
                    <BackButton onClick={goBackToFeed}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <line x1="19" y1="12" x2="5" y2="12"></line>
                            <polyline points="12 19 5 12 12 5"></polyline>
                        </svg>
                        Back
                    </BackButton>
                    {loading ? <VPStateBlock role="status" aria-live="polite">
                        <VPLoadingSpinner />
                        <VPStateTitle>Loading post…</VPStateTitle>
                    </VPStateBlock> : <VPStateBlock role="alert">
                        <VPStateIcon $tone="danger">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                                <line x1="12" y1="9" x2="12" y2="13" />
                                <line x1="12" y1="17" x2="12.01" y2="17" />
                            </svg>
                        </VPStateIcon>
                        <VPStateTitle>Couldn't load post</VPStateTitle>
                        <VPStateMessage>{depthError || error}</VPStateMessage>
                    </VPStateBlock>}
                </ModernPostFeed>
            </div>
        </ContentGrid>;
    }
    const shortenAddress = address => {
        if (!address) return "";
        return `${address.substring(0, 10)}...${address.substring(address.length - 4)}`;
    };
    const renderAuthorLink = currentPost => {
        if (!currentPost) return null;
        const trimmedUsername = currentPost.username && String(currentPost.username).trim() ? String(currentPost.username).trim() : '';
        const fallback = currentPost.user_id === state.publicKey && state.username ? state.username : shortenAddress(currentPost.user_id);
        const display = trimmedUsername || fallback;
        if (!display) return null;
        const displayWithAt = `@${display}`;
        const ownerAddress = currentPost.user_id ? String(currentPost.user_id).trim() : '';
        // New clean URL: prefer username, fallback to address
        const href = trimmedUsername ? `/u/${encodeURIComponent(trimmedUsername)}` : `/u/${encodeURIComponent(ownerAddress)}`;
        const tierColor = getAuthorColor(currentPost.author_level, currentPost.author_is_new);
        const tierName = getAuthorTooltip(currentPost.author_level, currentPost.author_is_new);
        const content = ownerAddress ? <StyledProfileLink to={href} $tierColor={tierColor} data-tooltip={tierName}>{displayWithAt}</StyledProfileLink> : displayWithAt;
        return content;
    };
    const isValidHash64 = s => {
        return typeof s === 'string' && /^[0-9a-f]{64}$/i.test(s);
    };
    const buildPermaLinkPath = post => {
        const rootId = root && root.post_id ? String(root.post_id).toLowerCase() : '';
        if (!rootId) return '';
        const rawCommentId = post && (post.tx_hash || post.post_id) ? String(post.tx_hash || post.post_id).toLowerCase() : '';
        const validCommentId = isValidHash64(rawCommentId) ? rawCommentId : '';
        const isComment = post && post.post_id && String(post.post_id).toLowerCase() !== rootId;
        // New clean URL format: /p/:postId
        if (isComment && validCommentId) {
            // For comments, link directly to the comment (no depth = single comment view)
            return `/p/${encodeURIComponent(validCommentId)}`;
        }
        return `/p/${encodeURIComponent(rootId)}`;
    };
    const handleShare = async post => {
        try {
            const path = buildPermaLinkPath(post);
            const origin = typeof window !== 'undefined' && window.location && window.location.origin ? window.location.origin : '';
            const url = origin + path;
            const title = root && root.title ? String(root.title) : 'Mirage';
            const tagline = 'True Discourse. Decentralized. Unstoppable.';
            const text = `${title}\n\n${tagline}\n\n${url}`;

            // Get thumbnail URL if available
            const thumbnailUrl = (() => {
                if (root && typeof root.thumbnail === 'string' && root.thumbnail.trim()) {
                    return root.thumbnail.trim();
                }
                return null;
            })();

            // Check if mobile device
            const isMobileDevice = (() => {
                try {
                    if (typeof window !== 'undefined' && window.matchMedia) {
                        return window.matchMedia('(max-width: 1000px)').matches;
                    }
                    if (typeof window !== 'undefined') {
                        return window.innerWidth < 1000;
                    }
                } catch (_) { }
                return false;
            })();

            // Only use navigator.share on mobile devices
            if (isMobileDevice && navigator && navigator.share) {
                try {
                    const shareData = {
                        title,
                        text,
                        url
                    };
                    // Try to include image if available (Web Share API Level 2)
                    if (thumbnailUrl && navigator.canShare) {
                        try {
                            const response = await fetch(thumbnailUrl);
                            const blob = await response.blob();
                            const file = new File([blob], 'thumbnail.jpg', {
                                type: blob.type || 'image/jpeg'
                            });
                            const testShareData = {
                                ...shareData,
                                files: [file]
                            };
                            if (navigator.canShare(testShareData)) {
                                await navigator.share(testShareData);
                                return;
                            }
                        } catch (_) {
                            // If image fetch fails, fall through to share without image
                        }
                    }
                    await navigator.share(shareData);
                    return;
                } catch (_) {
                    /* user-cancel or unsupported, fallback below */
                }
            }

            // Desktop: always copy URL to clipboard
            if (navigator && navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(url);
                // show in-view green success for 3s
                setShareMessages(prev => ({
                    ...prev,
                    [post.post_id]: {
                        type: 'success',
                        message: 'link copied to clipboard'
                    }
                }));
                setTimeout(() => {
                    setShareMessages(prev => {
                        const n = {
                            ...prev
                        };
                        delete n[post.post_id];
                        return n;
                    });
                }, 3000);
                return;
            }
            // Last resort: open the link
            if (typeof window !== 'undefined') {
                window.open(url, '_blank', 'noopener,noreferrer');
            }
        } catch (_) {
            /* noop */
        }
    };
    const displayConfirmation = post => {
        // Block / report confirmations moved to a root-level `ConfirmDialog`
        // modal (06.3 polish). The inline banners for the other flows
        // (delete, suspend, donate, gift sub, award) still render below.
        if (confirmBlockPost === post.post_id) return null;
        if (confirmBlockUser?.postId === post.post_id) return null;
        if (confirmBlockTopic?.postId === post.post_id) return null;
        if (confirmDeletePost === post.post_id) {
            const isComment = post.target && post.target !== '';
            return <BlockConfirmMessage>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.6rem',
                    width: '100%'
                }}>
                    <span style={{
                        whiteSpace: 'nowrap'
                    }}>⚠ Mark {isComment ? 'comment' : 'post'} as deleted?</span>
                    <ConfirmButtons style={{
                        marginLeft: 'auto',
                        flexShrink: 0,
                        width: 'auto'
                    }}>
                        <Button variant="warning" size="sm" onClick={confirmDeletePostAction} disabled={isDeleting}>
                            Delete
                        </Button>
                        <Button variant="ghost" size="sm" onClick={cancelDeletePost}>Cancel</Button>
                    </ConfirmButtons>
                </div>
            </BlockConfirmMessage>;
        }
        if (confirmSuspendQuests?.postId === post.post_id) {
            return <BlockConfirmMessage>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.6rem',
                    width: '100%'
                }}>
                    <span style={{
                        whiteSpace: 'nowrap'
                    }}>🛡️ Suspend this user from quests:</span>
                    <select value={suspendDuration} onChange={e => setSuspendDuration(Number(e.target.value))} style={{
                        padding: '0.25rem 0.5rem',
                        borderRadius: '4px',
                        border: '1px solid #d97706',
                        background: '#fef3c7',
                        color: '#92400e',
                        fontWeight: 500
                    }}>
                        <option value={1}>1 day</option>
                        <option value={3}>3 days</option>
                        <option value={7}>7 days</option>
                        <option value={30}>30 days</option>
                        <option value={0}>Permanent</option>
                    </select>
                    <ConfirmButtons style={{
                        marginLeft: 'auto',
                        flexShrink: 0,
                        width: 'auto'
                    }}>
                        <Button variant="warning" size="sm" onClick={confirmSuspendFromQuests} disabled={isSuspending}>
                            {isSuspending ? 'Suspending...' : 'Suspend'}
                        </Button>
                        <Button variant="ghost" size="sm" onClick={cancelSuspendFromQuests}>Cancel</Button>
                    </ConfirmButtons>
                </div>
            </BlockConfirmMessage>;
        }
        if (confirmUnsuspendQuests?.postId === post.post_id) {
            return <BlockConfirmMessage>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.6rem',
                    width: '100%'
                }}>
                    <span style={{
                        whiteSpace: 'nowrap'
                    }}>🛡️ Unsuspend this user from quests?</span>
                    <ConfirmButtons style={{
                        marginLeft: 'auto',
                        flexShrink: 0,
                        width: 'auto'
                    }}>
                        <Button variant="warning" size="sm" onClick={confirmUnsuspendFromQuests} disabled={isUnsuspending}>
                            {isUnsuspending ? 'Unsuspending...' : 'Unsuspend'}
                        </Button>
                        <Button variant="ghost" size="sm" onClick={cancelUnsuspendFromQuests}>Cancel</Button>
                    </ConfirmButtons>
                </div>
            </BlockConfirmMessage>;
        }
        if (suspendSuccess[post.post_id]) {
            return <div style={{
                background: 'rgba(34, 197, 94, 0.1)',
                border: '1px solid #22c55e',
                borderRadius: '3px',
                padding: '0.75rem 1rem',
                margin: '0.5rem 0',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                color: '#16a34a',
                fontSize: '0.8rem'
            }}>
                <span>✓</span>
                {suspendSuccess[post.post_id]}
            </div>;
        }
        // Report popup moved to a root-level `ConfirmDialog` (06.3 polish).
        if (confirmReportPost === post.post_id) return null;
        if (confirmDonate?.postId === post.post_id) {
            return <BlockConfirmMessage>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.6rem',
                    width: '100%'
                }}>
                    <span style={{
                        whiteSpace: 'nowrap'
                    }}>
                        💰 Donate to {post.username || post.user_id.substring(0, 12) + '...'}:
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
                        <input type="text" inputMode="numeric" value={formatDonateAmount(donateAmount)} onChange={e => handleDonateAmountChange(e.target.value)} placeholder="10,000" maxLength={11} disabled={isSendPending(confirmDonate?.userId)} style={{
                            width: '5.5rem',
                            background: 'transparent',
                            border: 'none',
                            outline: 'none',
                            color: theme.colors.text,
                            fontSize: '0.8rem',
                            fontWeight: 700,
                            textAlign: 'right'
                        }} />
                        <span style={{
                            fontSize: '0.68rem',
                            opacity: 0.7
                        }}>MIRAGE</span>
                    </div>
                    <ConfirmButtons style={{
                        marginLeft: 'auto',
                        flexShrink: 0,
                        width: 'auto'
                    }}>
                        <Button variant="warning" size="sm" onClick={confirmDonateAction} disabled={isSendPending(confirmDonate?.userId)}>
                            {formatSendStatus(confirmDonate?.userId) || 'Send'}
                        </Button>
                        <Button variant="ghost" size="sm" onClick={cancelDonate}>Cancel</Button>
                    </ConfirmButtons>
                </div>
            </BlockConfirmMessage>;
        }
        const donateMsg = donateMessages[post.post_id];
        if (donateMsg) {
            return <>
                {donateMsg.type === 'error' ? <BlockErrorMessage>
                    <span>⚠</span>
                    {donateMsg.message}
                </BlockErrorMessage> : <BlockSuccessMessage>
                    <span>✓</span>
                    {donateMsg.message}
                </BlockSuccessMessage>}
            </>;
        }
        if (confirmGiftSub?.postId === post.post_id) {
            const giftFeeLabel = confirmGiftSub.level === 10 ? agentFeeLabel : subFeeLabel;
            return <BlockConfirmMessage>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.6rem',
                    width: '100%'
                }}>
                    <div style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.25rem'
                    }}>
                        <span style={{
                            whiteSpace: 'nowrap'
                        }}>
                            🎁 {confirmGiftSub.level === 10 ? 'Gift agent subscription' : 'Gift subscription'} to {post.username || post.user_id.substring(0, 12) + '...'}?{giftFeeLabel ? ` (${giftFeeLabel})` : ''}
                        </span>
                        {confirmGiftSub.loading && <span style={{
                            fontSize: '0.75rem',
                            opacity: 0.7
                        }}>Loading expiry...</span>}
                        {confirmGiftSub.expiryLabel && <span style={{
                            fontSize: '0.75rem',
                            opacity: 0.7
                        }}>{confirmGiftSub.expiryLabel}</span>}
                        {confirmGiftSub.error && <span style={{
                            fontSize: '0.75rem',
                            color: '#ef4444'
                        }}>{confirmGiftSub.error}</span>}
                    </div>
                    <ConfirmButtons style={{
                        marginLeft: 'auto',
                        flexShrink: 0,
                        width: 'auto'
                    }}>
                        <Button variant="warning" size="sm" onClick={confirmGiftSubAction} disabled={isSubscribePending(confirmGiftSub?.userId) || confirmGiftSub.loading || !!confirmGiftSub.error}>
                            {formatSubscribeStatus(confirmGiftSub?.userId) || 'Confirm'}
                        </Button>
                        <Button variant="ghost" size="sm" onClick={cancelGiftSub}>Cancel</Button>
                    </ConfirmButtons>
                </div>
            </BlockConfirmMessage>;
        }
        const giftMsg = giftSubMessages[post.post_id];
        if (giftMsg) {
            return <>
                {giftMsg.type === 'error' ? <BlockErrorMessage>
                    <span>⚠</span>
                    {giftMsg.message}
                </BlockErrorMessage> : <BlockSuccessMessage>
                    <span>✓</span>
                    {giftMsg.message}
                </BlockSuccessMessage>}
            </>;
        }
        if (confirmAward?.postId === post.post_id) {
            return <BlockConfirmMessage>
                <div style={{
                    width: '100%'
                }}>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        marginBottom: '0.5rem'
                    }}>
                        <span style={{
                            fontWeight: 600,
                            fontSize: '0.85rem',
                            whiteSpace: 'nowrap',
                            flexShrink: 0
                        }}>Give Award</span>
                        <ConfirmButtons>
                            <Button variant="ghost" size="sm" onClick={() => setConfirmAward(null)}>Cancel</Button>
                        </ConfirmButtons>
                    </div>
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr 1fr',
                        gap: '0.4rem'
                    }}>
                        {AWARD_TYPES.map(award => {
                            const costUmirage = getAwardCost(award.name);
                            const costMirage = costUmirage != null && costUmirage > 0 ? (costUmirage / 1_000_000).toLocaleString() + ' MIRAGE' : null;
                            const canAfford = costUmirage != null && userBalanceUmirage !== null && userBalanceUmirage >= costUmirage;
                            const disabled = isAwarding || !canAfford;
                            return <button key={award.name} onClick={() => canAfford && confirmAwardAction(post.post_id, award.name)} disabled={disabled} style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                padding: '0.45rem 0.6rem',
                                background: theme.colors.surface2,
                                border: `1px solid ${theme.colors.borderSubtle}`,
                                borderRadius: '8px',
                                color: theme.colors.text,
                                cursor: disabled ? isAwarding ? 'wait' : 'not-allowed' : 'pointer',
                                opacity: disabled ? 0.4 : 1,
                                fontSize: '0.78rem',
                                transition: 'background 0.15s, opacity 0.15s'
                            }} onMouseEnter={e => {
                                if (!disabled) e.currentTarget.style.background = theme.colors.hover;
                            }} onMouseLeave={e => {
                                e.currentTarget.style.background = theme.colors.surface2;
                            }}>
                                <span style={{
                                    fontSize: '1.1rem'
                                }}>{award.icon}</span>
                                <span style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    alignItems: 'flex-start',
                                    lineHeight: 1.2
                                }}>
                                    <span style={{
                                        fontWeight: 600
                                    }}>{award.label}</span>
                                    <span style={{
                                        fontSize: '0.68rem',
                                        opacity: 0.6,
                                        color: !canAfford ? '#ef4444' : 'inherit'
                                    }}>
                                        {costMirage == null ? 'Loading...' : !canAfford ? 'Insufficient MIRAGE' : costMirage}
                                    </span>
                                </span>
                            </button>;
                        })}
                    </div>
                    {isAwarding && <div style={{
                        textAlign: 'center',
                        marginTop: '0.4rem',
                        fontSize: '0.75rem',
                        opacity: 0.7
                    }}>Submitting...</div>}
                </div>
            </BlockConfirmMessage>;
        }
        const awardMsg = awardMessages[post.post_id];
        if (awardMsg) {
            return awardMsg.type === 'error' ? <BlockErrorMessage><span>⚠</span>{awardMsg.message}</BlockErrorMessage> : <BlockSuccessMessage><span>✓</span>{awardMsg.message}</BlockSuccessMessage>;
        }

        // Show delete-specific messages for this post
        const deleteMsg = deleteMessages[post.post_id];
        if (deleteMsg) {
            return <>
                {deleteMsg.type === 'error' ? <BlockErrorMessage>
                    <span>⚠</span>
                    {deleteMsg.message}
                </BlockErrorMessage> : <BlockSuccessMessage>
                    <span>✓</span>
                    {deleteMsg.message}
                </BlockSuccessMessage>}
            </>;
        }

        // Show report messages for this post
        const repMsg = reportMessages[post.post_id];
        if (repMsg) {
            return <>
                {repMsg.type === 'error' ? <BlockErrorMessage>
                    <span>⚠</span>
                    {repMsg.message}
                </BlockErrorMessage> : <BlockSuccessMessage>
                    <span>✓</span>
                    {repMsg.message}
                </BlockSuccessMessage>}
            </>;
        }

        // Show share success message for this post
        const shMsg = shareMessages[post.post_id];
        if (shMsg) {
            return <>
                <BlockSuccessMessage>
                    <span>✓</span>
                    {shMsg.message}
                </BlockSuccessMessage>
            </>;
        }

        // Show error/success messages (only for root post to avoid duplicates)
        if (post.level === 0 || post.post_id === root.post_id) {
            return <>
                {blockError && <BlockErrorMessage>
                    <span>⚠</span>
                    {blockError}
                </BlockErrorMessage>}
                {blockSuccess && <BlockSuccessMessage>
                    <span>✓</span>
                    {blockSuccess}
                </BlockSuccessMessage>}
            </>;
        }
        return null;
    };
    const renderPostMenu = post => {
        const publicKeyStr = String(state.publicKey || '').trim();
        const hasValidAccount = publicKeyStr && publicKeyStr !== 'guest';
        const isOwnPost = post && state && post.user_id === state.publicKey;
        const userLevel = Number(Storage.load('user_level', '0')) || 0;
        const isAdmin = hasValidAccount && userLevel >= 100;
        const isOpen = openMenuId === post.post_id;
        const authorAddr = String(post.user_id || '').trim().toLowerCase();
        const isFollowingThisAuthor = isFollowingAuthor(authorAddr);
        const userSuspendedStatus = post.user_id ? userSuspendedMap[post.user_id] : undefined;
        const handleMenuClick = e => {
            e.stopPropagation();
            if (!isOpen) {
                const btn = menuButtonRefs.current[post.post_id];
                if (btn) {
                    const rect = btn.getBoundingClientRect();
                    setMenuPosition({
                        top: rect.bottom + 4,
                        left: Math.max(10, rect.right - 180)
                    });
                }
                if (isAdmin && post.user_id && questsEnabled) {
                    fetchUserSuspensionStatus(post.user_id);
                }
            }
            setOpenMenuId(isOpen ? null : post.post_id);
        };
        return <MenuContainer>
            <MenuButton ref={el => menuButtonRefs.current[post.post_id] = el} onClick={handleMenuClick} aria-label="Post menu">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="1.5"></circle>
                    <circle cx="12" cy="5" r="1.5"></circle>
                    <circle cx="12" cy="19" r="1.5"></circle>
                </svg>
            </MenuButton>
            {isOpen && ReactDOM.createPortal(<MenuDropdown ref={menuDropdownRef} style={{
                top: menuPosition.top,
                left: menuPosition.left
            }} onClick={e => e.stopPropagation()}>
                {isOwnPost && <>
                    <MenuItem onClick={() => {
                        setOpenMenuId(null);
                        const isRoot = !!(post.title && String(post.title).trim() !== '');
                        if (isRoot) {
                            navigate(`/create_post?post_id=${post.post_id}&edit=true`);
                        } else {
                            openEdit(post);
                        }
                    }}>Edit</MenuItem>
                    <MenuItem onClick={() => {
                        setOpenMenuId(null);
                        handleDeletePost(post.post_id);
                    }} data-danger="true">Delete</MenuItem>
                </>}
                {!isOwnPost && hasValidAccount && <>
                    <MenuItem onClick={() => {
                        setOpenMenuId(null);
                        handleFollowToggle(authorAddr);
                    }}>
                        {isUserPending(authorAddr) ? formatUserStatus(authorAddr) : isFollowingThisAuthor ? 'Unfollow user' : 'Follow user'}
                    </MenuItem>
                    <MenuItem onClick={() => {
                        setOpenMenuId(null);
                        handleGiveAward(post.post_id);
                    }}>Give Award</MenuItem>
                    {viewerAddress !== 'guest' && <MenuItem onClick={() => {
                        setOpenMenuId(null);
                        handleDonate(post.user_id, post.post_id);
                    }}>Gift Mirage</MenuItem>}
                    {viewerAddress !== 'guest' && <MenuItem onClick={() => {
                        setOpenMenuId(null);
                        handleGiftSubscription(post.user_id, post.post_id, post.author_level);
                    }} disabled={isSubscribePending(post.user_id)}>
                        {formatSubscribeStatus(post.user_id) || giftSubscriptionLabel}
                    </MenuItem>}
                    <MenuItem onClick={() => {
                        setOpenMenuId(null);
                        handleBlockUser(post.user_id, post.post_id);
                    }} data-danger="true">Block user</MenuItem>
                    <MenuItem onClick={() => {
                        setOpenMenuId(null);
                        handleBlockPost(post.post_id);
                    }} data-danger="true">Block post</MenuItem>
                    {post?.topic && <MenuItem onClick={() => {
                        setOpenMenuId(null);
                        handleBlockTopic(post.topic, post.post_id);
                    }} data-danger="true">Block topic</MenuItem>}
                    {!isAdmin && <MenuItem onClick={() => {
                        setOpenMenuId(null);
                        handleReport(post.post_id);
                    }}>Report</MenuItem>}
                    {isAdmin && <>
                        <MenuItem onClick={() => {
                            setOpenMenuId(null);
                            handleDeletePost(post.post_id);
                        }} data-danger="true">🛡️ Mark post deleted</MenuItem>
                        {questsEnabled && userSuspendedStatus !== true && <MenuItem onClick={() => {
                            setOpenMenuId(null);
                            handleSuspendFromQuests(post.user_id, post.post_id);
                        }} data-danger="true">🛡️ Suspend from quests</MenuItem>}
                        {questsEnabled && userSuspendedStatus === true && <MenuItem onClick={() => {
                            setOpenMenuId(null);
                            handleUnsuspendFromQuests(post.user_id, post.post_id);
                        }}>🛡️ Unsuspend from quests</MenuItem>}
                    </>}
                </>}
            </MenuDropdown>, document.body)}
        </MenuContainer>;
    };
    const renderActionBar = post => {
        const publicKeyStr = String(state.publicKey || '').trim();
        const hasValidAccount = publicKeyStr && publicKeyStr !== 'guest';
        if (!hasValidAccount) {
            return <MetaRow>
                <VoteSection inline state={state} post={post} updatePost={updatePost} />
                <DotSep aria-hidden="true">·</DotSep>
                <Link to="/signup" style={{
                    fontSize: '0.7rem',
                    color: 'inherit',
                    textDecoration: 'underline'
                }}>Sign in to participate</Link>
            </MetaRow>;
        }
        return <MetaRow>
            <VoteSection inline state={state} post={post} updatePost={updatePost} />
            <DotSep aria-hidden="true">·</DotSep>
            <ActionButton onClick={() => toggleReply(post.post_id)}>
                <Icon aria-hidden="true">
                    <svg viewBox="0 0 24 24">
                        <path d="M4 4h16v12H5.17L4 17.17V4zm0-2a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H4z"></path>
                    </svg>
                </Icon>
                <span>reply</span>
            </ActionButton>
            <MetaSeparatorAction />
            <ActionButton onClick={() => handleShare(post)}>
                <Icon aria-hidden="true">
                    <svg viewBox="0 0 458.624 458.624">
                        <path d="M339.588,314.529c-14.215,0-27.456,4.133-38.621,11.239l-112.682-78.67c1.809-6.315,2.798-12.976,2.798-19.871 c0-6.896-0.989-13.557-2.798-19.871l109.64-76.547c11.764,8.356,26.133,13.286,41.662,13.286c39.79,0,72.047-32.257,72.047-72.047 C411.634,32.258,379.378,0,339.588,0c-39.79,0-72.047,32.257-72.047,72.047c0,5.255,0.578,10.373,1.646,15.308l-112.424,78.491 c-10.974-6.759-23.892-10.666-37.727-10.666c-39.79,0-72.047,32.257-72.047,72.047s32.256,72.047,72.047,72.047 c13.834,0,26.753-3.907,37.727-10.666l113.292,79.097c-1.629,6.017-2.514,12.34-2.514,18.872c0,39.79,32.257,72.047,72.047,72.047 c39.79,0,72.047-32.257,72.047-72.047C411.635,346.787,379.378,314.529,339.588,314.529z" fill="currentColor" />
                    </svg>
                </Icon>
                <span className="share-text">share</span>
            </ActionButton>
        </MetaRow>;
    };
    const getVideoThumbnailUrl = url => {
        try {
            if (!url) return null;
            const u = new URL(url);
            const host = u.hostname.toLowerCase();
            const isStream = host.endsWith('cloudflarestream.com') || host.endsWith('videodelivery.net');
            if (!isStream) return null;
            const parts = u.pathname.split('/').filter(Boolean);
            const uid = parts[0];
            if (!uid) return null;
            return `${u.origin}/${uid}/thumbnails/thumbnail.jpg`;
        } catch (_) {
            return null;
        }
    };
    const displayReplyBox = (post, forMobileOverlay = false) => {
        if (!state.posts[post.post_id]?.replyOpen) return <div></div>;
        const isEdit = state.posts[post.post_id]?.replyMode === 'edit';

        // On mobile, don't render inline reply (use overlay instead) - except for edits
        if (isMobile && !isEdit && !forMobileOverlay) return <div></div>;
        const isBusy = (isEdit && !!state.posts[post.post_id]?.editBusy) || (!isEdit && !!state.posts[post.post_id]?.replyBusy);
        const replyText = state.posts[post.post_id]?.replyText || "";
        return <form onSubmit={e => {
            if (isEdit) {
                e.preventDefault();
                handleEditSubmit(post);
            } else {
                handleSubmit(post.post_id)(e);
            }
        }} onKeyDown={e => {
            if (e.key !== 'Tab') return;
            const form = e.currentTarget;
            const focusable = form.querySelectorAll('input:not([type="hidden"]):not([tabindex="-1"]):not(:disabled), textarea:not(:disabled), button:not([tabindex="-1"]):not(:disabled)');
            if (focusable.length === 0) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }}>
            <div style={{
                display: 'flex',
                flexDirection: 'column'
            }} onDragOver={e => handleReplyDragOver(post.post_id, e)} onDragLeave={e => handleReplyDragLeave(post.post_id, e)} onDrop={e => handleReplyDrop(post.post_id, e)}>
                <StyledReply offsetLeft={'0rem'} style={{
                    marginTop: isEdit ? '0.2rem' : '0.4rem',
                    position: 'relative'
                }}>
                    <MediaRow>
                        <StickerPicker onSelect={stickerUrl => {
                            setReplyAttachedType(prev => ({
                                ...prev,
                                [post.post_id]: 'image'
                            }));
                            setReplyAttachedUrl(prev => ({
                                ...prev,
                                [post.post_id]: stickerUrl
                            }));
                            setReplyThumbLoading(prev => ({
                                ...prev,
                                [post.post_id]: true
                            }));
                        }} disabled={isBusy || !!replyIsUploading[post.post_id] || !!replyAttachedUrl[post.post_id]} />
                        <GifPicker onSelect={gifUrl => {
                            setReplyAttachedType(prev => ({
                                ...prev,
                                [post.post_id]: 'image'
                            }));
                            setReplyAttachedUrl(prev => ({
                                ...prev,
                                [post.post_id]: gifUrl
                            }));
                            setReplyThumbLoading(prev => ({
                                ...prev,
                                [post.post_id]: true
                            }));
                        }} disabled={isBusy || !!replyIsUploading[post.post_id] || !!replyAttachedUrl[post.post_id]} />
                        <MediaIconButton type="button" tabIndex={-1} onClick={() => {
                            try {
                                const api = replyEditorUpload[post.post_id];
                                if (!api || typeof api.selectFile !== 'function') return;
                                if (replyIsUploading[post.post_id]) return;
                                api.selectFile();
                            } catch (_) { }
                        }} disabled={isBusy || !!replyIsUploading[post.post_id] || !replyEditorUpload[post.post_id] || !!replyAttachedUrl[post.post_id]} aria-label="Upload" title="Upload">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                <polyline points="17 8 12 3 7 8" />
                                <line x1="12" y1="3" x2="12" y2="15" />
                            </svg>
                        </MediaIconButton>
                        {(replyIsUploading[post.post_id] || (replyAttachedType[post.post_id] && replyAttachedUrl[post.post_id])) && <MediaPreviewWrapper>
                            {replyAttachedType[post.post_id] && replyAttachedUrl[post.post_id] && !replyIsUploading[post.post_id] && <>
                                <MediaPreviewImage src={replyAttachedType[post.post_id] === 'image' ? replyAttachedUrl[post.post_id] : getVideoThumbnailUrl(replyAttachedUrl[post.post_id]) || replyAttachedUrl[post.post_id]} alt="" onLoad={() => {
                                    setReplyThumbLoading(prev => {
                                        const next = {
                                            ...prev
                                        };
                                        delete next[post.post_id];
                                        return next;
                                    });
                                }} onError={() => {
                                    setReplyThumbLoading(prev => {
                                        const next = {
                                            ...prev
                                        };
                                        delete next[post.post_id];
                                        return next;
                                    });
                                }} />
                                {replyThumbLoading[post.post_id] && <MediaSpinner />}
                                <MediaRemoveButton type="button" tabIndex={-1} disabled={isBusy} onClick={() => {
                                    if (isBusy) return;
                                    setReplyAttachedType(prev => {
                                        const n = {
                                            ...prev
                                        };
                                        delete n[post.post_id];
                                        return n;
                                    });
                                    setReplyAttachedUrl(prev => {
                                        const n = {
                                            ...prev
                                        };
                                        delete n[post.post_id];
                                        return n;
                                    });
                                    setReplyThumbLoading(prev => {
                                        const n = {
                                            ...prev
                                        };
                                        delete n[post.post_id];
                                        return n;
                                    });
                                }} aria-label="Remove attached media" title="Remove attached media">
                                    ×
                                </MediaRemoveButton>
                            </>}
                            {replyIsUploading[post.post_id] && <div style={{
                                width: '100%',
                                height: '100%',
                                display: 'flex',
                                flexDirection: 'column',
                                alignItems: 'center',
                                justifyContent: 'center',
                                padding: '0.5rem',
                                boxSizing: 'border-box'
                            }}>
                                <span style={{
                                    fontSize: '0.7rem',
                                    color: '#888',
                                    marginBottom: '0.25rem'
                                }}>
                                    Uploading {replyUploadProgress[post.post_id] !== undefined ? `${Math.round(replyUploadProgress[post.post_id])}%` : '...'}
                                </span>
                                <Button variant="danger" size="xs" tabIndex={-1} onClick={() => {
                                    try {
                                        const api = replyEditorUpload[post.post_id];
                                        if (api && typeof api.cancelUpload === 'function') {
                                            api.cancelUpload();
                                        }
                                    } catch (_) { }
                                }}>
                                    Cancel
                                </Button>
                            </div>}
                        </MediaPreviewWrapper>}
                    </MediaRow>
                    <div data-mirageapp-editor style={{
                        position: 'relative'
                    }}>
                        <MarkdownEditor value={replyText} onChange={v => handleReplyChange(post.post_id, v)} maxLength={limits.maxContent} disabled={isBusy} autoFocus={true} onSubmitShortcut={() => {
                            if (isEdit) {
                                handleEditSubmit(post);
                            } else {
                                try {
                                    handleSubmit(post.post_id)({
                                        preventDefault() { },
                                        stopPropagation() { }
                                    });
                                } catch (_) { }
                            }
                        }} showCounters={false} toolbarButtonSize="1.5rem" toolbarIconSize="0.95rem" toolbarTopGap="0.35rem" registerUploadHandler={api => {
                            setReplyEditorUpload(prev => ({
                                ...prev,
                                [post.post_id]: api
                            }));
                        }} renderHelperRow={false} onMediaUploaded={(type, url, error) => {
                            if (error) {
                                // Clear attachment state on error
                                setReplyAttachedType(prev => {
                                    const n = {
                                        ...prev
                                    };
                                    delete n[post.post_id];
                                    return n;
                                });
                                setReplyAttachedUrl(prev => {
                                    const n = {
                                        ...prev
                                    };
                                    delete n[post.post_id];
                                    return n;
                                });
                                setReplyThumbLoading(prev => {
                                    const n = {
                                        ...prev
                                    };
                                    delete n[post.post_id];
                                    return n;
                                });
                                // Clear existing timeout if any
                                try {
                                    const t = replyErrorClearTimeoutRef.current?.[post.post_id];
                                    if (t) {
                                        clearTimeout(t);
                                        delete replyErrorClearTimeoutRef.current[post.post_id];
                                    }
                                } catch (_) {/* noop */ }
                                // Set error message
                                setReplySubmitError(prev => ({
                                    ...prev,
                                    [post.post_id]: error
                                }));
                                // Auto-clear after 5s
                                const tid = setTimeout(() => {
                                    setReplySubmitError(prev => {
                                        const next = {
                                            ...prev
                                        };
                                        delete next[post.post_id];
                                        return next;
                                    });
                                    try {
                                        delete replyErrorClearTimeoutRef.current[post.post_id];
                                    } catch (_) {/* noop */ }
                                }, 5000);
                                try {
                                    replyErrorClearTimeoutRef.current[post.post_id] = tid;
                                } catch (_) {/* noop */ }
                            } else if (!type || !url) {
                                // Generic failure without explicit error
                                setReplyAttachedType(prev => {
                                    const n = {
                                        ...prev
                                    };
                                    delete n[post.post_id];
                                    return n;
                                });
                                setReplyAttachedUrl(prev => {
                                    const n = {
                                        ...prev
                                    };
                                    delete n[post.post_id];
                                    return n;
                                });
                                setReplyThumbLoading(prev => {
                                    const n = {
                                        ...prev
                                    };
                                    delete n[post.post_id];
                                    return n;
                                });
                                // Show default message
                                const msg = 'Media upload failed. Please try again.';
                                // Clear any prior timer and set new message
                                try {
                                    const t = replyErrorClearTimeoutRef.current?.[post.post_id];
                                    if (t) {
                                        clearTimeout(t);
                                        delete replyErrorClearTimeoutRef.current[post.post_id];
                                    }
                                } catch (_) {/* noop */ }
                                setReplySubmitError(prev => ({
                                    ...prev,
                                    [post.post_id]: msg
                                }));
                                const tid = setTimeout(() => {
                                    setReplySubmitError(prev => {
                                        const next = {
                                            ...prev
                                        };
                                        delete next[post.post_id];
                                        return next;
                                    });
                                    try {
                                        delete replyErrorClearTimeoutRef.current[post.post_id];
                                    } catch (_) {/* noop */ }
                                }, 5000);
                                try {
                                    replyErrorClearTimeoutRef.current[post.post_id] = tid;
                                } catch (_) {/* noop */ }
                            } else {
                                // Success: attach media
                                setReplyAttachedType(prev => ({
                                    ...prev,
                                    [post.post_id]: type
                                }));
                                setReplyAttachedUrl(prev => ({
                                    ...prev,
                                    [post.post_id]: url
                                }));
                                setReplyThumbLoading(prev => ({
                                    ...prev,
                                    [post.post_id]: true
                                }));
                                // Clear any stale error
                                setReplySubmitError(prev => {
                                    const n = {
                                        ...prev
                                    };
                                    delete n[post.post_id];
                                    return n;
                                });
                                try {
                                    const t = replyErrorClearTimeoutRef.current?.[post.post_id];
                                    if (t) {
                                        clearTimeout(t);
                                        delete replyErrorClearTimeoutRef.current[post.post_id];
                                    }
                                } catch (_) {/* noop */ }
                            }
                        }} onUploadStateChange={uploading => {
                            setReplyIsUploading(prev => ({
                                ...prev,
                                [post.post_id]: uploading
                            }));
                            if (!uploading) {
                                setReplyUploadProgress(prev => {
                                    const next = {
                                        ...prev
                                    };
                                    delete next[post.post_id];
                                    return next;
                                });
                            }
                        }} onUploadProgress={progress => {
                            setReplyUploadProgress(prev => ({
                                ...prev,
                                [post.post_id]: progress ?? undefined
                            }));
                        }} suffixLabel={limits.willPayFee ? '(paid tier)' : '(free tier)'} showUploadButton={false} belowElement={replySubmitError[post.post_id] ? <ReplyErrorMessage role="alert">{replySubmitError[post.post_id]}</ReplyErrorMessage> : null} />
                    </div>
                    <ReplyActionsRow>
                        <div style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '2px',
                            minWidth: 0,
                            flex: '1 1 auto',
                            alignSelf: 'flex-start'
                        }}>
                            <ReplyCounter $warn={replyText.length >= limits.maxContent}>
                                {replyText.length} / {limits.maxContent} {limits.willPayFee ? '(paid tier)' : '(free tier)'}
                            </ReplyCounter>
                        </div>
                        <StyledSubmitButtonContainer>
                            <Button type="submit" size="sm" disabled={isBusy || !!replyIsUploading[post.post_id]} loading={isBusy}>
                                {isBusy ? replySubmitStatus[post.post_id] === 'submitting' ? 'Submitting...' : replySubmitStatus[post.post_id] === 'verifying' ? 'Verifying...' : 'Processing' : isEdit ? 'Save Edit' : replyIsUploading[post.post_id] ? 'Uploading…' : 'Submit'}
                            </Button>
                            <Button data-mirageapp-cancel type="button" variant="ghost" size="sm" onClick={() => closeReply(post.post_id)} disabled={isBusy}>Cancel</Button>
                        </StyledSubmitButtonContainer>
                    </ReplyActionsRow>
                </StyledReply>
            </div>
        </form>;
    };
    const toggleCollapsed = (postId, currentVisible) => {
        const hasVisible = typeof currentVisible === 'boolean';
        const current = hasVisible ? currentVisible : !!state.posts[postId]?.collapsed;
        updatePost(postId, {
            collapsed: !current
        });
    };

    // Merge root with any optimistic/local updates from state.posts for immediate UI reflection (title/topic/content edits)
    const mergedRoot = (() => {
        try {
            if (!root || !root.post_id) return root;
            const sp = state && state.posts ? state.posts[root.post_id] : undefined;
            if (!sp) return root;
            const out = {
                ...root
            };
            if (sp.title !== undefined) out.title = sp.title;
            if (sp.topic !== undefined) out.topic = sp.topic;
            if (sp.root_topic !== undefined) out.root_topic = sp.root_topic;
            if (sp.tag !== undefined) out.tag = sp.tag;
            if (sp.content !== undefined) out.content = sp.content;
            if (sp.media !== undefined) out.media = sp.media;
            if (sp.edited !== undefined) out.edited = sp.edited;
            if (sp.edited_ts !== undefined) out.edited_ts = sp.edited_ts;
            return out;
        } catch (_) {
            return root;
        }
    })();

    // Find post with open reply (for mobile overlay) - exclude edit mode
    const mobileReplyPost = (() => {
        if (!isMobile) return null;
        const allPosts = [...annotated];
        for (const p of allPosts) {
            if (state.posts[p.post_id]?.replyOpen && state.posts[p.post_id]?.replyMode !== 'edit') {
                return p;
            }
        }
        return null;
    })();

    // Render mobile reply overlay
    const renderMobileReplyOverlay = () => {
        if (!isMobile || !mobileReplyPost) return null;
        const post = mobileReplyPost;
        const authorDisplay = post.username || (post.author ? `${post.author.substring(0, 8)}...` : 'Unknown');
        return ReactDOM.createPortal(<MobileReplyOverlay ref={mobileReplyOverlayRef}>
            <MobileReplyHeader>
                <MobileReplyBackButton onClick={() => closeReply(post.post_id)}>
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="19" y1="12" x2="5" y2="12"></line>
                        <polyline points="12 19 5 12 12 5"></polyline>
                    </svg>
                    Cancel
                </MobileReplyBackButton>
            </MobileReplyHeader>
            <MobileReplyContent>
                <MobileReplyPostPreview>
                    <MobileReplyPostMeta>
                        Replying to <strong>@{authorDisplay}</strong>
                    </MobileReplyPostMeta>
                    <MobileReplyPostContent>
                        {post.content || ''}
                    </MobileReplyPostContent>
                </MobileReplyPostPreview>
                {displayReplyBox(post, true)}
            </MobileReplyContent>
        </MobileReplyOverlay>, document.body);
    };

    // Check if user is logged in
    const isLoggedIn = viewerAddress && viewerAddress !== 'guest';

    if (!isLoggedIn) {
        return <ContentGrid>
            <div>
                <ModernPostFeed>
                    <LoggedOutPromptCard
                        role="region"
                        aria-label="View post on Mirage"
                        eyebrow="Post Details"
                        title="Sign in to view this post"
                        description="Create an account or sign in to read posts, vote, and join the conversation."
                        links={[
                            { label: "Watch Introduction (YouTube)", href: "https://www.youtube.com/watch?v=TOvP32ihQ0M", external: true },
                            { label: "Learn More", href: "https://mirage.foundation", external: true },
                        ]}
                        inviteText="Have an invite code? Join the community today."
                        primaryLabel="Create account"
                        secondaryLabel="Sign in"
                    />
                </ModernPostFeed>
            </div>
        </ContentGrid>;
    }
    if (root) {
        const origin = typeof window !== 'undefined' && window.location && window.location.origin ? window.location.origin : 'https://mirage.vote';
        const postUrl = `${origin}/p/${root.post_id}`;
        const postTitle = mergedRoot && mergedRoot.title ? String(mergedRoot.title).trim() : root && root.title ? String(root.title).trim() : 'Mirage';
        const postDescription = mergedRoot && mergedRoot.content ? String(mergedRoot.content).trim().substring(0, 200) : root && root.content ? String(root.content).trim().substring(0, 200) : 'Decentralized social network';
        const imageUrl = `${origin}/images/logo.webp`;
        return <ContentGrid>
            <MainContentWrapper>
                <Helmet>
                    <title>{postTitle} | Mirage</title>
                    <meta name="description" content={postDescription} />
                    <meta property="og:type" content="article" />
                    <meta property="og:url" content={postUrl} />
                    <meta property="og:title" content={postTitle} />
                    <meta property="og:description" content={postDescription} />
                    <meta property="og:image" content={imageUrl} />
                    <meta name="twitter:card" content="summary" />
                    <meta name="twitter:url" content={postUrl} />
                    <meta name="twitter:title" content={postTitle} />
                    <meta name="twitter:description" content={postDescription} />
                    <meta name="twitter:image" content={imageUrl} />
                </Helmet>
                <ModernPostFeed>
                    {/* Topic Hero Card */}
                    {(() => {
                        const displayTopic = mergedRoot?.topic || mergedRoot?.root_topic || root?.topic || root?.root_topic || actualRootPost?.topic || '';
                        const topicLower = displayTopic.toLowerCase();
                        const isTopicFollowing = isSubscribedTopic(topicLower);
                        const isTopicInProgress = isTopicPending(topicLower);
                        const hasValidAccount = state.publicKey && state.publicKey !== 'guest';
                        return <TopicHeroWrapper>
                            <TopicHeroCard role="region" aria-label="Topic context">
                                {/* Mobile: Top row with Back button and Follow button */}
                                <TopicHeroTopRow>
                                    <BackButton onClick={goBackToFeed} style={{
                                        padding: 0,
                                        margin: 0,
                                        fontSize: '0.8rem'
                                    }}>
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{
                                            width: '14px',
                                            height: '14px'
                                        }}>
                                            <line x1="19" y1="12" x2="5" y2="12"></line>
                                            <polyline points="12 19 5 12 12 5"></polyline>
                                        </svg>
                                        Back
                                    </BackButton>
                                    {hasValidAccount && <TopicFollowButton
                                        type="button"
                                        $active={isTopicFollowing}
                                        onMouseEnter={() => setTopicFollowHover(true)}
                                        onMouseLeave={() => setTopicFollowHover(false)}
                                        onClick={() => {
                                            if (!isTopicInProgress && displayTopic) {
                                                handleTopicFollowToggle(displayTopic);
                                            }
                                        }}
                                        disabled={isTopicInProgress}
                                    >
                                        {isTopicInProgress ? formatTopicStatus(topicLower) : isTopicFollowing ? (topicFollowHover ? 'Unfollow' : 'Following') : 'Follow'}
                                    </TopicFollowButton>}
                                </TopicHeroTopRow>

                                {/* Desktop: Back section */}
                                <TopicHeroBackSection>
                                    <BackButton onClick={goBackToFeed} style={{
                                        padding: 0,
                                        margin: 0,
                                        fontSize: '0.8rem'
                                    }}>
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{
                                            width: '14px',
                                            height: '14px'
                                        }}>
                                            <line x1="19" y1="12" x2="5" y2="12"></line>
                                            <polyline points="12 19 5 12 12 5"></polyline>
                                        </svg>
                                        Back
                                    </BackButton>
                                </TopicHeroBackSection>

                                {/* Desktop: Follow button */}
                                <TopicAction>
                                    {hasValidAccount && <TopicFollowButton
                                        type="button"
                                        $active={isTopicFollowing}
                                        onMouseEnter={() => setTopicFollowHover(true)}
                                        onMouseLeave={() => setTopicFollowHover(false)}
                                        onClick={() => {
                                            if (!isTopicInProgress && displayTopic) {
                                                handleTopicFollowToggle(displayTopic);
                                            }
                                        }}
                                        disabled={isTopicInProgress}
                                    >
                                        {isTopicInProgress ? formatTopicStatus(topicLower) : isTopicFollowing ? (topicFollowHover ? `Unfollow #${displayTopic}` : `Following #${displayTopic}`) : `Follow #${displayTopic}`}
                                    </TopicFollowButton>}
                                </TopicAction>
                            </TopicHeroCard>
                        </TopicHeroWrapper>;
                    })()}
                    {annotated.filter(p => !p.hidden && !deletedPosts.has(p.post_id)).map(post => {
                        const normalizedPostId = String(post.post_id).toLowerCase();
                        const isRoot = post.level === 0;
                        const isCollapsed = !!(post.level > 0 && post.collapsed);
                        const CardComponent = isRoot ? PostCard : CommentCard;
                        // Flash: root uses rootFlash state, comments use post.flash
                        const shouldFlash = isRoot ? rootFlash : !!post.flash;
                        const displayLevel = post.level;
                        // Persistent highlight for inbox-linked comments
                        const isHighlighted = !isRoot && normalizedHighlightId && normalizedPostId === normalizedHighlightId;
                        return <div id={`comment-${normalizedPostId}`} key={post.post_id}>
                            <CardComponent className={isHighlighted ? 'inbox-highlight' : undefined} $isFlash={shouldFlash} $isNew={!!(lastVisitTs && post.level > 0 && typeof post.timestamp === 'number' && post.timestamp > lastVisitTs)} $isCollapsed={isCollapsed} $level={displayLevel} $size={cardSize}>
                                <ColumnFlex>
                                    {/* Mobile root post meta - two rows */}
                                    {isRoot && <MobileRootMeta>
                                        <MobileRootMetaTop>
                                            {renderAuthorLink(post)}
                                            {renderPostMenu(post)}
                                        </MobileRootMetaTop>
                                        <MobileRootMetaBottom>
                                            {(() => {
                                                const topicLabel = post.topic || post.root_topic || mergedRoot?.topic || mergedRoot?.root_topic || root?.topic || root?.root_topic || '';
                                                return topicLabel ? <StyledTopicLink to={`/t/${encodeURIComponent(topicLabel.toLowerCase())}`}>#{topicLabel}</StyledTopicLink> : null;
                                            })()}
                                            <MetaSeparator>·</MetaSeparator>
                                            <span>{formatElapsed(post.timestamp)} ago</span>
                                            {(() => {
                                                const tagLabel = normalizeTag(post.tag || mergedRoot?.tag || root?.tag || '');
                                                return tagLabel ? <>
                                                    <MetaSeparator>·</MetaSeparator>
                                                    <TagBadge $tag={tagLabel}>{tagLabel}</TagBadge>
                                                </> : null;
                                            })()}
                                            {post.edited && <>
                                                <MetaSeparator>·</MetaSeparator>
                                                <span style={{
                                                    fontStyle: 'italic'
                                                }}>edited</span>
                                            </>}
                                            {post?.awards?.length > 0 && <>
                                                <MetaSeparator>·</MetaSeparator>
                                                <span style={{
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                    gap: '0.1rem',
                                                    fontSize: '0.6rem'
                                                }}>
                                                    {post.awards.map(a => {
                                                        const def = AWARD_TYPES.find(t => t.name === a.type);
                                                        if (!def) return null;
                                                        const cnt = Number(a.count || 0);
                                                        return <Tooltip key={a.type} data-tooltip={def.label}>{cnt > 1 ? `${cnt}x` : ''}{def.icon}</Tooltip>;
                                                    })}
                                                </span>
                                            </>}
                                        </MobileRootMetaBottom>
                                    </MobileRootMeta>}
                                    {/* Desktop meta info row (hidden on mobile for root posts) */}
                                    <DesktopMetaInfoRow $hideOnMobile={isRoot}>
                                        <MetaInfoRowLeft>
                                            {renderAuthorLink(post)}
                                            <MetaSeparator>·</MetaSeparator>
                                            <Tooltip $dotted data-tooltip={formatTimeStamp(post.timestamp)}>
                                                {formatElapsed(post.timestamp)} ago
                                            </Tooltip>
                                            {!isRoot && <>
                                                <MetaSeparator>·</MetaSeparator>
                                                <CollapseToggle
                                                    type="button"
                                                    onClick={() => toggleCollapsed(post.post_id, !!post.collapsed)}
                                                    aria-label={post.collapsed ? 'Expand' : 'Collapse'}
                                                >
                                                    <svg viewBox="0 0 24 24" style={{ transform: post.collapsed ? 'rotate(-90deg)' : 'rotate(0deg)' }}>
                                                        <polyline points="6 9 12 15 18 9" />
                                                    </svg>
                                                </CollapseToggle>
                                            </>}
                                            {/* Only show topic for root posts - comments inherit from root */}
                                            {isRoot && (() => {
                                                const topicLabel = post.topic || post.root_topic || mergedRoot?.topic || mergedRoot?.root_topic || root?.topic || root?.root_topic || '';
                                                return topicLabel ? <>
                                                    <MetaSeparator>·</MetaSeparator>
                                                    <StyledTopicLink to={`/t/${encodeURIComponent(topicLabel.toLowerCase())}`}>#{topicLabel}</StyledTopicLink>
                                                </> : null;
                                            })()}
                                            {(() => {
                                                const tagLabel = normalizeTag(post.tag || mergedRoot?.tag || root?.tag || '');
                                                return tagLabel ? <>
                                                    <MetaSeparator>·</MetaSeparator>
                                                    <TagBadge $tag={tagLabel}>{tagLabel}</TagBadge>
                                                </> : null;
                                            })()}
                                            {post.edited && <>
                                                <MetaSeparator>·</MetaSeparator>
                                                <Tooltip $dotted data-tooltip={formatTimeStamp(post.edited_ts)} style={{
                                                    fontStyle: 'italic'
                                                }}>
                                                    edited {formatElapsed(post.edited_ts)} ago
                                                </Tooltip>
                                            </>}
                                            {post?.awards?.length > 0 && <>
                                                <MetaSeparator>·</MetaSeparator>
                                                <span style={{
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                    gap: '0.1rem',
                                                    fontSize: '0.6rem'
                                                }}>
                                                    {post.awards.map(a => {
                                                        const def = AWARD_TYPES.find(t => t.name === a.type);
                                                        if (!def) return null;
                                                        const cnt = Number(a.count || 0);
                                                        return <Tooltip key={a.type} data-tooltip={def.label}>{cnt > 1 ? `${cnt}x` : ''}{def.icon}</Tooltip>;
                                                    })}
                                                </span>
                                            </>}
                                            {post.agent_edited && <>
                                                <MetaSeparator>·</MetaSeparator>
                                                <span style={{
                                                    opacity: 0.5,
                                                    fontStyle: 'italic'
                                                }}>
                                                    agent modified
                                                </span>
                                            </>}
                                        </MetaInfoRowLeft>
                                        {renderPostMenu(post)}
                                    </DesktopMetaInfoRow>

                                    {/* Title for root post */}
                                    {isRoot && <>
                                        <RootTitleRow>
                                            {post && post.title ? post.title : mergedRoot && mergedRoot.title ? mergedRoot.title : root && root.title ? root.title : ''}
                                        </RootTitleRow>
                                        <TitleDivider />
                                    </>}

                                    {/* Content — for the focused post, use mergedRoot so optimistic edits (media etc.) appear immediately */}
                                    {(() => {
                                        const isFocusedPost = post.post_id === root?.post_id;
                                        const displayPost = isFocusedPost && mergedRoot ? mergedRoot : post;
                                        const displayContent = displayPost.content || '';
                                        const displayMedia = Array.isArray(displayPost.media) ? displayPost.media : [];
                                        const displayMediaMeta = Array.isArray(displayPost.media_meta) ? displayPost.media_meta : [];
                                        const hasContent = !!(displayContent || displayMedia.length > 0);
                                        if (isCollapsed || !hasContent) return null;
                                        if (state.posts[post.post_id]?.replyOpen && state.posts[post.post_id]?.replyMode === 'edit') return null;
                                        return <StyledContentArea>
                                            {(() => {
                                                const raw = String(displayContent || '');
                                                const mediaArr = displayMedia;

                                                // v1.12.0: Render from dedicated media array if available
                                                if (mediaArr.length > 0) {
                                                    const Inline = require("../components/InlineMedia").default;
                                                    const Gallery = require("../components/MediaGallery").default;
                                                    const mediaNode = mediaArr.length > 1 && Gallery ? React.createElement(Gallery, {
                                                        items: mediaArr,
                                                        variant: isRoot ? 'root_post' : undefined,
                                                        mediaMeta: displayMediaMeta
                                                    }) : Inline ? React.createElement(Inline, {
                                                        url: mediaArr[0],
                                                        variant: isRoot ? 'root_post' : undefined,
                                                        mediaMeta: displayMediaMeta[0] || null
                                                    }) : null;
                                                    return <>
                                                        {mediaNode}
                                                        {raw ? <div style={{
                                                            height: '0.5rem'
                                                        }} /> : null}
                                                        {raw ? <MarkdownRenderer text={raw} /> : null}
                                                    </>;
                                                }

                                                // LEGACY (v1.11): First-line media URL extraction for posts created before v1.12.0.
                                                // Remove after March 2026 when all old posts have been migrated or expired.
                                                const idx = raw.indexOf('\n');
                                                const first = (idx >= 0 ? raw.slice(0, idx) : raw).trim();
                                                const restRaw = (idx >= 0 ? raw.slice(idx + 1) : '').replace(/^\n+/, '');
                                                const isUrl = /^https?:\/\//i.test(first);
                                                if (isUrl) {
                                                    return <>
                                                        {require("../components/InlineMedia").default ? React.createElement(require("../components/InlineMedia").default, {
                                                            url: first,
                                                            variant: isRoot ? 'root_post' : undefined,
                                                            mediaMeta: displayMediaMeta[0] || null
                                                        }) : null}
                                                        {restRaw ? <div style={{
                                                            height: '0.5rem'
                                                        }} /> : null}
                                                        {restRaw ? <MarkdownRenderer text={restRaw} /> : null}
                                                    </>;
                                                }
                                                return <MarkdownRenderer text={raw} />;
                                            })()}
                                        </StyledContentArea>;
                                    })()}

                                    {/* Agent annotation appendices */}
                                    {!isCollapsed && post.appendices && post.appendices.length > 0 && post.appendices.map((a, idx) => {
                                        const label = a.agent_username || a.agent || 'Agent';
                                        return <div key={`appx-${idx}`} style={{
                                            margin: '0.5rem 0'
                                        }}>
                                            <div style={{
                                                marginBottom: '0.2rem'
                                            }}>
                                                <Link to={`/u/${label}`} style={{
                                                    textDecoration: 'underline',
                                                    fontSize: '0.6rem',
                                                    color: theme.colors?.textMuted || theme.colors?.textSecondary || '#888'
                                                }}>@{label}</Link>
                                                <span style={{
                                                    color: theme.colors?.textMuted || '#888',
                                                    fontSize: '0.6rem'
                                                }}>:</span>
                                            </div>
                                            <div style={{
                                                padding: '0.4rem 0.65rem',
                                                borderLeft: `3px solid ${theme.colors?.border || '#444'}`,
                                                background: theme.colors?.cardBg || 'rgba(99,102,241,0.05)',
                                                borderRadius: '0 6px 6px 0',
                                                fontSize: '0.85em'
                                            }}>
                                                <MarkdownRenderer text={a.text} />
                                            </div>
                                        </div>;
                                    })}
                                    {/* Action bar with horizontal votes */}
                                    {!isCollapsed && <>
                                        {state.posts[post.post_id]?.replyOpen && state.posts[post.post_id]?.replyMode === 'edit' ? <>
                                            {displayReplyBox(post)}
                                            {renderActionBar(post)}
                                            {displayConfirmation(post)}
                                        </> : <>
                                            {renderActionBar(post)}
                                            {displayConfirmation(post)}
                                            {displayReplyBox(post)}
                                        </>}
                                    </>}
                                </ColumnFlex>
                            </CardComponent>
                            {isRoot && !!focusedCommentId && <StyledThreadReminder>
                                You are viewing a single comment's thread.{' '}
                                {!showContext ? <>
                                    Click{' '}
                                    <Link to={`/p/${focusedCommentId}?depth=5`}>
                                        here
                                    </Link>
                                    {' '}to view the recent context, or{' '}
                                    <Link to={`/p/${actualRootPostId}`}>here</Link>
                                    {' '}to view the full thread.
                                </> : <>
                                    Click{' '}
                                    <Link to={`/p/${actualRootPostId}`}>here</Link>
                                    {' '}to view the full thread.
                                </>}
                            </StyledThreadReminder>}
                            {isRoot && <CommentsHeaderRow>
                                <CommentsHeaderTitle>
                                    Comments
                                    {typeof (mergedRoot?.comments ?? root?.comments) === 'number' && <CommentsHeaderCount>({mergedRoot?.comments ?? root?.comments})</CommentsHeaderCount>}
                                </CommentsHeaderTitle>
                            </CommentsHeaderRow>}
                            {isRoot && annotated.filter(p => !p.hidden && !deletedPosts.has(p.post_id) && p.level > 0).length === 0 && <VPStateBlock>
                                <VPStateIcon>
                                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                                    </svg>
                                </VPStateIcon>
                                <VPStateTitle>No comments yet</VPStateTitle>
                                <VPStateMessage>Be the first to share your thoughts.</VPStateMessage>
                            </VPStateBlock>}
                            {/* Continue thread link for deeply nested comments with unloaded children */}
                            {(() => {
                                // Don't show for root post
                                if (isRoot) return null;
                                // Don't show if collapsed
                                if (isCollapsed) return null;
                                // Don't show for context comments (parent chain in focused view)
                                if (post.isContextComment) return null;
                                // Don't show if this IS the focused comment (we're already viewing its thread)
                                if (focusedCommentId && String(post.post_id).toLowerCase() === String(focusedCommentId).toLowerCase()) return null;
                                // Don't show if no replies
                                if ((post.comments || 0) <= 0) return null;
                                // Check if children are loaded (either in post.children or state.posts)
                                const stateChildren = state.posts?.[post.post_id]?.children;
                                const hasLoadedChildren = (post.children && post.children.length > 0) || (stateChildren && stateChildren.length > 0);
                                if (hasLoadedChildren) return null;
                                return <ContinueThreadLink to={`/p/${post.post_id}`} $level={displayLevel}>
                                    Continue this thread →
                                </ContinueThreadLink>;
                            })()}
                        </div>;
                    })}
                </ModernPostFeed>
            </MainContentWrapper>
            {renderMobileReplyOverlay()}
            {/**
              * Destructive-action dialogs (block post/user/topic + report).
              * Rendered at the route root so a single `ConfirmDialog` owns
              * the modal UI for the whole page. The existing state machine
              * in `useViewPost` (`confirmBlockPost`, `confirmBlockUser`,
              * `confirmBlockTopic`, `confirmReportPost`) drives visibility;
              * the on-click handlers still live inside the hook.
              *
              * Username lookup uses `state.posts[postId]?.username` so the
              * dialog title shows the friendly handle when available.
              */}
            {(() => {
                const blockUserPostId = confirmBlockUser?.postId;
                const blockUserPost = blockUserPostId ? state.posts?.[blockUserPostId] : null;
                const blockUserLabel = blockUserPost?.username
                    ? `@${blockUserPost.username}`
                    : (confirmBlockUser?.userId ? `${String(confirmBlockUser.userId).slice(0, 10)}…` : 'this user');
                return <>
                    <ConfirmDialog
                        open={!!confirmBlockPost}
                        title="Block this post?"
                        message="This post will be hidden from every feed you see. The author won't be notified."
                        confirmLabel="Block post"
                        confirmVariant="danger"
                        pending={isBlocking}
                        onConfirm={confirmBlockPostAction}
                        onCancel={cancelBlockPost}
                    />
                    <ConfirmDialog
                        open={!!confirmBlockUser}
                        title={`Block ${blockUserLabel}?`}
                        message="Posts and replies from this user will be hidden from your feeds, comments, and inbox. You can unblock them later from Settings → Blocks or their profile."
                        confirmLabel="Block user"
                        confirmVariant="danger"
                        pending={isBlocking}
                        onConfirm={confirmBlockUserAction}
                        onCancel={cancelBlockUser}
                    />
                    <ConfirmDialog
                        open={!!confirmBlockTopic}
                        title={`Block #${confirmBlockTopic?.topic || 'topic'}?`}
                        message="Posts tagged with this topic will stop appearing in your Home and discovery feeds."
                        confirmLabel="Block topic"
                        confirmVariant="danger"
                        pending={isBlocking}
                        onConfirm={confirmBlockTopicAction}
                        onCancel={cancelBlockTopic}
                    />
                    <ConfirmDialog
                        open={!!confirmReportPost}
                        title="🚨 Report this post? Provide a short reason."
                        message="Reports are reviewed by moderators. Be clear and specific — reports without context are usually dismissed."
                        confirmLabel="Report"
                        confirmVariant="warning"
                        pending={isReporting}
                        requireReason
                        reasonPlaceholder="short reason"
                        reasonMaxLength={200}
                        wide
                        reasonInitial={reportReason}
                        onConfirm={(trimmed) => {
                            setReportReason(trimmed);
                            // Defer so the hook sees the updated reason.
                            setTimeout(() => { try { confirmReportAction(); } catch (_) { /* noop */ } }, 0);
                        }}
                        onCancel={cancelReport}
                    />
                </>;
            })()}
        </ContentGrid>;
    } else {
        return <ContentGrid>
            <MainContentWrapper>
                <ModernPostFeed>
                    <BackButton onClick={goBackToFeed}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <line x1="19" y1="12" x2="5" y2="12"></line>
                            <polyline points="12 19 5 12 12 5"></polyline>
                        </svg>
                        Back
                    </BackButton>
                    <VPStateBlock role="alert">
                        <VPStateIcon $tone="danger">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                                <line x1="12" y1="9" x2="12" y2="13" />
                                <line x1="12" y1="17" x2="12.01" y2="17" />
                            </svg>
                        </VPStateIcon>
                        <VPStateTitle>Unable to load post</VPStateTitle>
                        <VPStateMessage>Something went wrong. Try going back and opening the post again.</VPStateMessage>
                    </VPStateBlock>
                </ModernPostFeed>
            </MainContentWrapper>
        </ContentGrid>;
    }
}
export default ViewPostView;