import { useState, useMemo, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { HiTrash, HiChevronLeft, HiChevronRight, HiChevronDown, HiArrowUpTray } from "react-icons/hi2";
import { TopicSelector } from "../components/TopicSelector.js";
import MarkdownEditor from "../components/MarkdownEditor.js";
import Button from "../components/Button.js";
import ConfirmDialog from "../components/ConfirmDialog.js";
import LoggedOutPromptCard from "../components/LoggedOutPromptCard.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import FeedRightRail from "../components/FeedRightRail.js";
import { getCachedWelcomeStats } from "../../../utils/welcomeStatsCache";
import { MediaRow, MediaPreviewWrapper, MediaPreviewImage, MediaSpinner, MediaRemoveButton } from "../components/MediaAttachmentLayout.js";
import DefaultEditorChrome, { EditorMediaTools } from "../components/DefaultEditorChrome.js";
import { useCreatePost, TAG_OPTIONS_ENABLED } from "../../../logic/useCreatePost";

/**
 * default `CreatePostView` — Twitter-style single composer.
 *
 * Follows R1 (bg canvas), R2 (tokens only), R3 (border dividers),
 * R5 (neutral input focus), R6 (HiChevronDown), R7 (compact font scale).
 *
 * Layout
 *  - Header row mirrors `InboxView::HeaderRow`/`HeaderTitle` (1.1rem/700,
 *    `0.25rem 1rem 0.5rem` padding) plus a trailing "Drafts" hint.
 *  - 820px capped `ComposerColumn` (matches Inbox width).
 *  - Stacked: topic → title → action chip row → unfurled artifacts
 *    (link input, media carousel) → body editor → submit row.
 *  - Action chips ("+ Link", "+ Media", "+ Tag") sit between Title and
 *    Body. "+ Link" and "+ Media" each unfurl their artifact directly
 *    below the row so attached content sits above the body — matching
 *    how the post will render in the feed. "+ Media" toggles an inline
 *    drop panel that stays open across uploads (drop multiple files one
 *    by one) and also exposes a "Choose file" button. Whole-page
 *    drag/drop still uploads via the outer `ContentGrid` handlers.
 *  - "+ Tag" is a self-contained inline dropdown — clicking it pops a
 *    small radio menu beneath the chip and the chip text rewrites
 *    itself to "Tag: <Name>" once a tag is picked, so the selection
 *    reads inline without burning vertical space on a card.
 *  - GIF / Sticker pickers live inline in the body editor's toolbar
 *    (via `toolbarExtra`) since they decorate the body rather than
 *    standing alongside the structural Link / Media / Tag chips.
 *
 * Typography (R7)
 *  - All inputs, pills, help text: 0.75rem / 500 (inputs),
 *    0.62rem floating labels, 0.7rem helper copy.
 *  - Page heading: 1.1rem / 700 (matches Inbox).
 *  - Draft & Post buttons share a 2rem pill height.
 */

/* -------------------------------------------------------------------------- */
/* Header row (matches Inbox)                                                 */
/* -------------------------------------------------------------------------- */

const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.25rem 1rem 0.5rem;

    @media (max-width: 600px) {
        padding: 0.25rem 0 0.5rem;
    }
`;

/* ─── Typography scale ────────────────────────────────────────────────────
 *
 * The composer uses a tight 5-step scale. Reach for one of these instead
 * of inventing a new size — every drift adds visual noise.
 *
 *   1.05rem   — page header only (HeaderTitle)
 *   0.78rem   — primary inputs, textarea body, preview body, drop heading
 *   0.7rem    — buttons, chips, menu items, advisory + error notes
 *   0.62rem   — floating labels, counters, badges, hint subtitles
 *   0.55rem   — uppercase section microcopy (Preview header, Edit Hash)
 *
 * Decorative SVG/glyph sizes (0.8 / 0.85 / 0.9rem) sit outside the text
 * scale on purpose — they're icon dimensions, not type. */

const HeaderTitle = styled.div`
    display: flex;
    align-items: center;
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

/* -------------------------------------------------------------------------- */
/* Stack / fields                                                             */
/* -------------------------------------------------------------------------- */

const Stack = styled.form`
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    padding: 0 1rem 2rem;

    @media (max-width: 1000px) {
        padding: 0 0.85rem 1.5rem;
    }

    @media (max-width: 600px) {
        padding: 0 0 1.5rem;
    }
`;

const Field = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    min-width: 0;
`;

/* -------------------------------------------------------------------------- */
/* Title / Link inputs — floating-label shell                                 */
/* -------------------------------------------------------------------------- */

/* InputShell — bordered, transparent background (canvas shows through).
 * Title and Link share the exact same shell styling per request. */
const InputShell = styled.div`
    position: relative;
    width: 100%;
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 14px;
    background: transparent;
    transition: border-color 0.15s ease;

    &:hover { border-color: ${({ theme }) => theme.colors.borderStrong}; }
    &:focus-within { border-color: ${({ theme }) => theme.colors.borderStrong}; }
`;

const FloatLabel = styled.label`
    position: absolute;
    top: 0.5rem;
    left: 1rem;
    font-size: 0.62rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
    pointer-events: none;

    &::after {
        content: '*';
        color: ${({ theme }) => theme.colors.voteDown};
        margin-left: 2px;
    }
`;

const ShellInput = styled.input`
    width: 100%;
    box-sizing: border-box;
    border: none;
    border-radius: 14px;
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    font-family: inherit;
    font-size: 0.78rem;
    /* Light weight — matches Link input exactly (R7). */
    font-weight: 400;
    line-height: 1.4;
    /* Identical label→text spacing for Title and Link URL. */
    padding: 1.55rem 2.75rem 0.55rem 1rem;
    margin: 0;
    outline: none;
    pointer-events: auto !important;

    &:focus { outline: none; box-shadow: none; }
    &:disabled { opacity: 0.55; cursor: not-allowed; }
    &::placeholder { color: transparent; }
`;

const ValidCheck = styled.span`
    position: absolute;
    right: 0.9rem;
    top: 50%;
    transform: translateY(-50%);
    color: ${({ theme }) => theme.colors.voteUp};
    display: inline-flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;

    svg { width: 20px; height: 20px; }
`;

const Counter = styled.span`
    position: absolute;
    right: 0.1rem;
    top: calc(100% + 0.2rem);
    font-size: 0.62rem;
    font-weight: 500;
    color: ${({ $warn, theme }) => ($warn ? theme.colors.voteDown : theme.colors.subtleText)};
    pointer-events: none;
`;

/* Field-level error panel — used for hard validation failures (invalid URL,
 * etc.). Uses the theme's `voteDown` (red) palette to signal "error", which
 * is distinct from the amber `NewTopicNote` that signals "advisory".
 *
 * The fill is intentionally very soft (red with ~6% alpha) so the red text
 * remains the primary signal rather than the background. */
const FieldError = styled.div`
    display: flex;
    align-items: flex-start;
    gap: 0.45rem;
    margin-top: 0.3rem;
    padding: 0.45rem 0.65rem;
    border-radius: 10px;
    border: 1px solid rgba(255, 69, 58, 0.35);
    background: rgba(255, 69, 58, 0.06);
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.7rem;
    font-weight: 500;
    line-height: 1.45;

    &::before {
        content: '⚠';
        line-height: 1.2;
        font-size: 0.78rem;
        flex: 0 0 auto;
    }
`;

/* -------------------------------------------------------------------------- */
/* Add tags pill + radio card                                                 */
/* -------------------------------------------------------------------------- */

/* -------------------------------------------------------------------------- */
/* Tag chip dropdown                                                          */
/*                                                                            */
/* The "+ Tag" chip is a self-contained SELECT control: clicking it opens a   */
/* small popover-style menu anchored beneath the chip with the tag options.   */
/* Picking one closes the menu and rewrites the chip text to "Tag: <Name>"   */
/* (parentheticals stripped from the option label) so the selection is       */
/* readable inline and the radio-card real estate disappears.                */
/* -------------------------------------------------------------------------- */

/* Anchor for the absolutely-positioned `TagMenu`. Inline-flex so it sits
 * naturally inside the action chip row and inherits `flex-wrap` behavior. */
const TagChipWrap = styled.div`
    position: relative;
    display: inline-flex;
`;

const TagMenu = styled.div`
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    min-width: 12rem;
    background: ${({ theme }) => theme.colors.menuBg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.28);
    z-index: 1000;
    padding: 0.25rem 0;
    display: flex;
    flex-direction: column;
`;

const TagMenuItem = styled.button`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    width: 100%;
    padding: 0.45rem 0.85rem;
    background: transparent;
    border: none;
    color: ${({ $selected, theme }) => ($selected ? theme.colors.followBtnBg : theme.colors.sidebarItemText)};
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: ${({ $selected }) => ($selected ? 600 : 500)};
    text-align: left;
    cursor: pointer;
    transition: background 0.12s ease, color 0.12s ease;

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.menuSelectedBg};
        color: ${({ $selected, theme }) => ($selected ? theme.colors.followBtnBg : theme.colors.menuItemHoverText)};
    }
    &:disabled { opacity: 0.5; cursor: not-allowed; }
    &:focus { outline: none; }
`;

const TagMenuCheck = styled.span`
    font-size: 0.85rem;
    line-height: 1;
    color: ${({ theme }) => theme.colors.followBtnBg};
`;

const TagMenuDivider = styled.hr`
    border: none;
    border-top: 1px solid ${({ theme }) => theme.colors.borderSubtle};
    margin: 0.25rem 0;
`;

const TagMenuFooter = styled.div`
    padding: 0.4rem 0.85rem 0.5rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.45;
`;

/* -------------------------------------------------------------------------- */
/* Body editor shell                                                          */
/* - Outer container has a border (matches Link/Title shells).                */
/* - Toolbar row divider lives below the icon buttons (borderSubtle).         */
/* - Inside: icon buttons are transparent, textarea bg is transparent,        */
/*   preview pill bg is transparent (R7 neutral focus / no blue fills).       */
/*                                                                            */
/* NOTE: styled-components nested selectors like `button { ... }` scope to    */
/* descendants of this component's class automatically, so we do NOT need     */
/* `[data-default-editor]` prefixes (those would have to match a descendant */
/* element, but the attribute sits on the root — it never matched, which is   */
/* why toolbar tiles looked unstyled before).                                 */
/* -------------------------------------------------------------------------- */

const EditorShell = styled.div`
    position: relative;
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 14px;
    background: transparent;
    overflow: hidden;
    transition: border-color 0.15s ease;

    &:hover { border-color: ${({ theme }) => theme.colors.borderStrong}; }
    &:focus-within { border-color: ${({ theme }) => theme.colors.borderStrong}; }

    /* Toolbar styling — entirely owned by DefaultEditorChrome so the
     * toolbar in this composer is byte-identical to the one in the
     * comments reply editor (StickerPicker / GifPicker / divider all
     * look and lay out the same in both contexts). The only thing this
     * shell adds is a tiny inset so toolbar buttons aren't pressed
     * against the rounded outer border. */
    > div > div > div:first-child {
        padding-left: 0.35rem;
        padding-right: 0.35rem;
        padding-top: 0.3rem;
    }

    /* Textarea — transparent inside the bordered shell. */
    textarea {
        border: none !important;
        border-radius: 0 !important;
        background: transparent !important;
        background-color: transparent !important;
        color: ${({ theme }) => theme.colors.text} !important;
        padding: 0.7rem 0.85rem !important;
        font-size: 0.78rem !important;
        font-weight: 500 !important;
        line-height: 1.55 !important;
        transition: none !important;
    }
    textarea:hover,
    textarea:focus {
        border: none !important;
        box-shadow: none !important;
        background: transparent !important;
        background-color: transparent !important;
    }
    textarea::placeholder {
        color: ${({ theme }) => theme.colors.subtleText} !important;
        font-weight: 500 !important;
    }
    textarea:disabled {
        background: transparent !important;
        background-color: transparent !important;
        color: ${({ theme }) => theme.colors.subtleText} !important;
    }

    /* Live preview tile (extra hop through DefaultEditorChrome). */
    > div > div > :last-child {
        background: ${({ theme }) => theme.colors.composerPreviewBg} !important;
        border: 1px solid ${({ theme }) => theme.colors.borderSubtle} !important;
        border-radius: 10px !important;
        padding: 0.65rem 0.85rem !important;
        margin: 0.5rem 0.55rem 0.55rem !important;
        font-size: 0.78rem !important;
        color: ${({ theme }) => theme.colors.text} !important;
    }
    > div > div > :last-child > div:first-child {
        font-size: 0.55rem !important;
        font-weight: 600 !important;
        color: ${({ theme }) => theme.colors.subtleText} !important;
        margin-bottom: 0.35rem !important;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
`;

/* Hide-but-keep-mounted wrapper so the MarkdownEditor upload API stays
 * registered even when the Media or Link tab is active — otherwise
 * `editorUpload` is null and the Upload/Add buttons on the Media tile
 * become no-ops. */
const EditorMount = styled.div`
    display: ${({ $hidden }) => ($hidden ? 'none' : 'block')};
`;

/* Action chip row (sits between Title and Body — Twitter-style composer).
 *
 * Houses the structural "add something to the post" affordances: link,
 * media upload, content tag. Each chip is a text pill button so the
 * affordance reads at a glance ("+ Link", "+ Media") rather than
 * relying on icon recognition. GIF / Sticker pickers live inside the
 * body editor toolbar instead — they decorate the body and matter less
 * than the structural chips.
 *
 * Active-state semantics, per chip:
 *   - "+ Link"  — active while the URL input is open or non-empty.
 *   - "+ Media" — active while the drop panel is open or items attached.
 *   - "+ Tag"   — active while the dropdown is open or a tag is set.
 *     Once a tag is picked the chip rewrites to "Tag: <Name>". */
const ActionRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex-wrap: wrap;
`;

/* Inline drop panel — toggled by the "+ Media" chip. Stays open across
 * uploads so users can drop multiple files one by one. Dashed border +
 * drag-active highlight mirror the old empty-state CarouselTile so the
 * affordance reads as "drop target". A "Choose file" button covers the
 * fallback path for users who prefer the OS picker. */
const MediaDropZone = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.55rem;
    padding: 1.1rem 1rem;
    border: 1.5px dashed ${({ $dragging, theme }) => ($dragging ? theme.colors.borderStrong : theme.colors.border)};
    border-radius: 14px;
    background: ${({ $dragging, theme }) => ($dragging ? theme.colors.hoverBg : 'transparent')};
    color: ${({ theme }) => theme.colors.subtleText};
    text-align: center;
    transition: border-color 0.15s ease, background 0.15s ease;
`;

const MediaDropIcon = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2.4rem;
    height: 2.4rem;
    border-radius: 50%;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panelAlt};
    color: ${({ theme }) => theme.colors.text};

    svg { width: 1.1rem; height: 1.1rem; }
`;

const MediaDropText = styled.div`
    font-size: 0.78rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.text};
    line-height: 1.4;
`;

const MediaDropHint = styled.div`
    font-size: 0.62rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
    margin-top: -0.15rem;
`;

/* Tri-state action chip:
 *   default — neutral ghost (chip available, nothing committed yet)
 *   $active — borderStrong + panelAlt fill (e.g. an attached panel is open
 *             but no value is locked in)
 *   $set    — amber palette signaling "value committed" (used by the tag
 *             chip so a chosen content-warning tag is impossible to miss
 *             at a glance, matching the amber palette of NewTopicNote
 *             which sits in the same content-warning vocabulary)
 *
 * `$set` wins over `$active` visually so a user re-opening the menu on
 * an already-set tag still sees the committed state. */
const ActionChip = styled.button`
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0 0.7rem;
    height: 1.65rem;
    border-radius: 9999px;
    border: 1px solid ${({ $set, $active, theme }) =>
        $set ? 'rgba(245, 158, 11, 0.5)'
            : $active ? theme.colors.borderStrong
                : theme.colors.border};
    background: ${({ $set, $active, theme }) =>
        $set ? 'rgba(245, 158, 11, 0.12)'
            : $active ? theme.colors.panelAlt
                : 'transparent'};
    color: ${({ $set, $active, theme }) =>
        $set ? '#f59e0b'
            : $active ? theme.colors.text
                : theme.colors.subtleText};
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: ${({ $set }) => ($set ? 600 : 500)};
    cursor: pointer;
    transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;

    &:hover:not(:disabled) {
        border-color: ${({ $set, theme }) =>
        $set ? 'rgba(245, 158, 11, 0.7)' : theme.colors.borderStrong};
        background: ${({ $set, theme }) =>
        $set ? 'rgba(245, 158, 11, 0.18)' : theme.colors.hoverBg};
        color: ${({ $set, theme }) => ($set ? '#f59e0b' : theme.colors.text)};
    }
    &:disabled { opacity: 0.5; cursor: not-allowed; }
    &:focus { outline: none; }
    &:focus-visible { border-color: ${({ theme }) => theme.colors.borderStrong}; }

    svg {
        width: 0.85rem;
        height: 0.85rem;
        display: block;
    }
`;

/* -------------------------------------------------------------------------- */
/* Images & Video — carousel tile (matches screenshot reference)              */
/* -------------------------------------------------------------------------- */

/* CarouselTile
 * - Empty state: 11rem tall dashed drop zone.
 * - With media: flex column with a header row (Add/Delete) above the slide.
 * - While a media item is uploading/loading a thumb: keep a stable
 *   `min-height` so the tile doesn't collapse to zero. */
const CarouselTile = styled.div`
    position: relative;
    border: 1.5px dashed ${({ $dragging, theme }) => ($dragging ? theme.colors.borderStrong : theme.colors.border)};
    border-radius: 18px;
    background: transparent;
    min-height: ${({ $hasMedia, $loading }) => {
        if ($loading) return '14rem';
        return $hasMedia ? '12rem' : '9rem';
    }};
    display: flex;
    flex-direction: ${({ $hasMedia }) => ($hasMedia ? 'column' : 'row')};
    align-items: ${({ $hasMedia }) => ($hasMedia ? 'stretch' : 'center')};
    justify-content: center;
    padding: ${({ $hasMedia }) => ($hasMedia ? '0.5rem' : '1.25rem')};
    gap: 0.5rem;
    overflow: hidden;
    transition: border-color 0.15s ease, background 0.15s ease, min-height 0.2s ease;

    ${({ $dragging, theme }) => $dragging && `background: ${theme.colors.hoverBg};`}
`;

/* Header row above the media slide. Holds a position counter on the
 * left ("3 / 5") and Delete on the right. The "Add" affordance lives
 * in the inline drop panel above the carousel — when the panel is
 * closed the user reopens it via the "+ Media" chip. */
const CarouselHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 0.2rem;
`;

/* Capacity pill — "attached / max", e.g. "3 / 10". Small, pill-shaped,
 * neutral fill so it reads as a status indicator rather than a button.
 * Static during navigation between items (capacity doesn't change as
 * you click prev/next) — increments only when media is added or
 * removed, signalling the user's progress against the MAX_MEDIA cap. */
const SlideCounter = styled.span`
    display: inline-flex;
    align-items: center;
    height: 1.6rem;
    padding: 0 0.65rem;
    border-radius: 9999px;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panelAlt};
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    user-select: none;
`;

/* Fixed-height stage: every slide renders inside the same 22rem-tall
 * frame regardless of the image's intrinsic aspect ratio, so navigating
 * between media items doesn't reflow the composer. The image is sized
 * via `max-*: 100%` and centered by the parent flex container — small
 * images render at natural pixels, large images shrink to fit. */
const MediaSlide = styled.div`
    position: relative;
    width: 100%;
    height: 22rem;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 14px;
    overflow: hidden;
`;

const MediaSlideImage = styled.img`
    max-width: 100%;
    max-height: 100%;
    width: auto;
    height: auto;
    display: ${({ $loaded }) => ($loaded ? 'block' : 'none')};
`;

/* Loading skeleton shown while a newly added media item is still uploading
 * or its thumbnail hasn't resolved. Keeps the tile at a stable height so
 * the composer doesn't jump around. */
const MediaSlidePlaceholder = styled.div`
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    font-weight: 500;
`;

const MediaSpinnerRing = styled.span`
    width: 1.1rem;
    height: 1.1rem;
    border-radius: 50%;
    border: 2px solid ${({ theme }) => theme.colors.border};
    border-top-color: ${({ theme }) => theme.colors.followBtnBg};
    animation: default-cp-spin 0.8s linear infinite;

    @keyframes default-cp-spin {
        to { transform: rotate(360deg); }
    }
`;

/* Floating corner button (Add / Delete / prev / next). */
const CornerButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.35rem;
    padding: ${({ $iconOnly }) => ($iconOnly ? '0' : '0 0.8rem')};
    width: ${({ $iconOnly }) => ($iconOnly ? '2rem' : 'auto')};
    height: 2rem;
    border-radius: 9999px;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panelAlt};
    color: ${({ theme }) => theme.colors.text};
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
    box-shadow: none;

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.surface2};
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }
    &:disabled { opacity: 0.5; cursor: not-allowed; }

    svg { font-size: 0.9rem; }
`;

/* Delete button lives in the CarouselHeader, right aligned. */
const HeaderDelete = styled(CornerButton)`
    padding: 0;
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 50%;

    &:hover:not(:disabled) {
        color: ${({ theme }) => theme.colors.voteDown};
        border-color: ${({ theme }) => theme.colors.voteDown};
    }

    svg { font-size: 0.8rem; }
`;

/* Prev/Next remain overlaid on the slide. */
const NavButton = styled(CornerButton)`
    position: absolute;
    top: 50%;
    transform: translateY(-50%);
    width: 1.9rem;
    height: 1.9rem;
    padding: 0;
    border-radius: 50%;
`;

const NavPrev = styled(NavButton)`
    left: 0.6rem;
`;

const NavNext = styled(NavButton)`
    right: 0.6rem;
`;

const UploadingBadge = styled.div`
    position: absolute;
    bottom: 0.75rem;
    left: 50%;
    transform: translateX(-50%);
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.3rem 0.7rem;
    border-radius: 9999px;
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.62rem;
    font-weight: 500;
`;

/* -------------------------------------------------------------------------- */
/* Bottom bar — Draft + Post buttons, matched heights                         */
/* -------------------------------------------------------------------------- */

const BottomBar = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    margin-top: 0.5rem;

    @media (max-width: 600px) {
        flex-direction: column;
        align-items: stretch;
        gap: 0.6rem;
    }
`;

const ContentCounter = styled.span`
    font-size: 0.62rem;
    font-weight: 500;
    color: ${({ $warn, theme }) => ($warn ? theme.colors.voteDown : theme.colors.subtleText)};
`;

const SubmitGroup = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    justify-content: flex-end;
    flex-shrink: 0;
`;

const BTN_HEIGHT = '1.7rem';

const PostBtn = styled.button`
    height: ${BTN_HEIGHT};
    padding: 0 1rem;
    background: ${({ theme }) => theme.colors.followBtnBg};
    color: #ffffff;
    border: 1px solid ${({ theme }) => theme.colors.followBtnBg};
    font-family: inherit;
    font-weight: 600;
    font-size: 0.7rem;
    border-radius: 9999px;
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease;

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.followBtnBgHover};
        border-color: ${({ theme }) => theme.colors.followBtnBgHover};
    }

    &:disabled { opacity: 0.55; cursor: not-allowed; }
`;

/* Guidance note shown when user selects/creates a new (unknown) topic.
 * Amber advisory palette, intentionally softer than `FieldError` so it reads
 * as guidance rather than an error. Fill is ~6% alpha to match `FieldError`
 * treatment and keep the amber text as the primary signal. */
const NewTopicNote = styled.div`
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    padding: 0.55rem 0.75rem;
    border: 1px solid rgba(245, 158, 11, 0.35);
    border-radius: 10px;
    background: rgba(245, 158, 11, 0.06);
    color: #f59e0b;
    font-size: 0.7rem;
    font-weight: 500;
    line-height: 1.45;

    &::before {
        content: '⚠';
        line-height: 1.2;
        font-size: 0.78rem;
        flex: 0 0 auto;
    }

    b { color: #fbbf24; font-weight: 600; }
`;

/* Content counter row — right-aligned beneath the body editor.
 * `margin-top` matches the 0.2rem gap that the title Counter uses
 * (`top: calc(100% + 0.2rem)` on the absolute-positioned title counter),
 * so vertical rhythm is consistent between the two counters. */
const ContentCounterRow = styled.div`
    display: flex;
    justify-content: flex-end;
    margin-top: 0.2rem;
    padding: 0 0.1rem;
`;

/* -------------------------------------------------------------------------- */
/* Misc                                                                       */
/* -------------------------------------------------------------------------- */

const ErrorMessage = styled.div`
    background-color: ${({ theme }) => theme.colors.buttonDangerBg};
    border: 1px solid ${({ theme }) => theme.colors.buttonDangerBorder};
    border-radius: 10px;
    padding: 0.45rem 0.7rem;
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.7rem;
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

const EditHashRow = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    padding: 0.4rem 0.75rem;
    border: 1px solid ${({ theme }) => theme.colors.borderSubtle};
    border-radius: 10px;
    background: ${({ theme }) => theme.colors.surface};
`;

const EditHashLabel = styled.span`
    font-size: 0.55rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-weight: 500;
    letter-spacing: 0.04em;
    text-transform: uppercase;
`;

const Mono = styled.span`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.7rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    word-break: break-all;
    overflow-wrap: anywhere;
`;

/** 820px cap (960 px on large desktops) — matches InboxView width. */
const ComposerColumn = styled.div`
    width: 100%;
    max-width: 820px;

    @media (min-width: 1500px) {
        max-width: 960px;
    }

    @media (min-width: 1900px) {
        max-width: 1200px;
    }
`;

/* -------------------------------------------------------------------------- */
/* Component                                                                  */
/* -------------------------------------------------------------------------- */

function CreatePostView({ state, setPosts, updatePost }) {
    const isLoggedIn = !!(state && state.publicKey && state.publicKey !== 'guest');
    if (!isLoggedIn) {
        return (
            <ContentGrid>
                <Helmet>
                    <title>Create Post | Mirage</title>
                </Helmet>
                <FeedRailRow $feedViewMode="card">
                    <FeedCol>
                        <ModernPostFeed>
                            <LoggedOutPromptCard
                                role="region"
                                aria-label="Create a post on Mirage"
                                title="Sign in to post on Mirage"
                                description="Create an account or sign in to publish posts, join topics, and participate on-chain."
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
    return <CreatePostAuthenticated state={state} setPosts={setPosts} updatePost={updatePost} />;
}

function CreatePostAuthenticated({ state, setPosts, updatePost }) {
    const {
        isEditMode,
        overrideId,
        topicValue,
        titleValue,
        contentValue,
        setContentValue,
        submitError,
        setSubmitError,
        errorSetTimeRef,
        errorClearTimeoutRef,
        isSubmitting,
        submitStatus,
        editorUpload,
        setEditorUpload,
        attachedMedia,
        setAttachedMedia,
        MAX_MEDIA,
        isUploading,
        setIsUploading,
        uploadProgress,
        setUploadProgress,
        thumbsLoading,
        setThumbsLoading,
        tagValue,
        setTagValue,
        tagEnabled,
        setTagEnabled,
        setTagManuallySet,
        titleInputRef,
        contentEditorRef,
        limits,
        handleTopicChange,
        getByteLength,
        handleTitleChange,
        getVideoThumbnailUrl,
        addMediaItem,
        handleTitlePaste,
        handleSubmit,
    } = useCreatePost({ state, setPosts, updatePost });

    const [linkUrl, setLinkUrl] = useState('');
    const [linkOpen, setLinkOpen] = useState(false);
    const [slideIndex, setSlideIndex] = useState(0);
    const [topicIsNew, setTopicIsNew] = useState(false);
    /* Picker-attached image (GIF / sticker). Single-slot, mirrors the
     * comments reply editor's `replyAttachedUrl` pattern. The body
     * textarea stays clean; the URL is prepended to `contentValue` at
     * submit time so the renderer turns it into an inline image — same
     * trick `useViewPost.handleSubmit` uses for replies. */
    const [pickerMediaUrl, setPickerMediaUrl] = useState(null);
    const [pickerThumbLoading, setPickerThumbLoading] = useState(false);
    /* "+ Media" chip toggles a persistent inline drop panel — stays open
     * across uploads so users can drop multiple files one at a time. */
    const [mediaPanelOpen, setMediaPanelOpen] = useState(false);
    const [mediaPanelDragging, setMediaPanelDragging] = useState(false);
    /* `panelOpenedByDragRef` remembers whether the currently-open panel
     * was auto-opened by a file drag (so dragleave should auto-close
     * it) vs. opened by an explicit "+ Media" click (which dragleave
     * must not stomp). */
    const panelOpenedByDragRef = useRef(false);
    /* "+ Tag" chip is a self-contained dropdown — clicking it pops a small
     * radio-style menu of tag options anchored beneath the chip. The chip
     * label rewrites itself to "Tag: <Name>" once a tag is selected so
     * the choice reads inline without burning vertical space on a card. */
    const [tagMenuOpen, setTagMenuOpen] = useState(false);
    const tagMenuWrapRef = useRef(null);

    /* Display name for the chip — strips parentheticals out of option
     * labels (e.g. "Sensitive (blur content)" → "Sensitive") so the chip
     * stays compact. Returns null when no tag is set; the chip then
     * falls back to the default "+ Tag" label. */
    const tagDisplayLabel = useMemo(() => {
        if (!tagEnabled || !tagValue) return null;
        const opt = TAG_OPTIONS_ENABLED.find(o => o.value === tagValue);
        if (!opt) return null;
        return String(opt.label || '').replace(/\s*\(.*?\)\s*/g, '').trim();
    }, [tagEnabled, tagValue]);

    const handleTagSelect = value => {
        if (!value) {
            setTagEnabled(false);
            setTagValue('');
        } else {
            setTagEnabled(true);
            setTagValue(value);
        }
        setTagManuallySet(true);
        setTagMenuOpen(false);
        if (submitError) setSubmitError('');
    };

    /* Close the tag menu on click-outside or Escape. Both listeners are
     * attached only while the menu is open so they don't leak. */
    useEffect(() => {
        if (!tagMenuOpen) return;
        const onMouseDown = e => {
            if (tagMenuWrapRef.current && !tagMenuWrapRef.current.contains(e.target)) {
                setTagMenuOpen(false);
            }
        };
        const onKey = e => {
            if (e.key === 'Escape') {
                e.preventDefault();
                setTagMenuOpen(false);
            }
        };
        document.addEventListener('mousedown', onMouseDown);
        window.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onMouseDown);
            window.removeEventListener('keydown', onKey);
        };
    }, [tagMenuOpen]);

    /* -------------------------------------------------------------------- */
    /* Unsaved-changes guard                                                */
    /*                                                                      */
    /* Replaces the old draft system. There is no autosave and no restore.  */
    /* If the user has typed/attached anything and tries to leave the page  */
    /* before submitting, we prompt them to discard.                        */
    /*                                                                      */
    /* Two surfaces, two coverage levels:                                   */
    /*   - `beforeunload`: tab close / refresh / hard URL change. Browser   */
    /*     shows its own native "Leave site?" prompt (the message text is   */
    /*     ignored by all modern browsers — that's a 2018+ change, not a    */
    /*     bug here).                                                       */
    /*   - Document-level click capture for SPA `<a>` clicks: we intercept  */
    /*     the click before it triggers in-app navigation and show our own  */
    /*     `ConfirmDialog`. On confirm we forward to the captured href via  */
    /*     `useNavigate`.                                                   */
    /*                                                                      */
    /* Known holes (acknowledged, not in scope):                            */
    /*   - Programmatic `useNavigate()` calls fired from OTHER components   */
    /*     while CreatePostView is mounted. Nothing in the app navigates    */
    /*     while sitting on /create-post in practice.                       */
    /*   - Browser back/forward. `<BrowserRouter>` (this codebase) doesn't  */
    /*     expose a stable blocker API for popstate without a data router.  */
    /*                                                                      */
    /* Bypassed entirely while `isSubmitting` is true so the post-and-      */
    /* redirect flow doesn't trip its own guard.                            */
    /* -------------------------------------------------------------------- */
    const navigate = useNavigate();
    const [pendingNavHref, setPendingNavHref] = useState(null);

    const hasUnsavedContent = useMemo(() => {
        if (isEditMode) return false;
        return !!(
            (topicValue && topicValue.trim())
            || (titleValue && titleValue.trim())
            || (contentValue && contentValue.trim())
            || (linkUrl && linkUrl.trim())
            || tagEnabled
            || (attachedMedia && attachedMedia.length > 0)
            || pickerMediaUrl
        );
    }, [isEditMode, topicValue, titleValue, contentValue, linkUrl, tagEnabled, attachedMedia, pickerMediaUrl]);

    /* Browser-level guard — covers tab close, refresh, hard URL changes.
     * `returnValue = ''` is the legacy contract that triggers the prompt;
     * `preventDefault()` is the spec-correct one. Set both for safety. */
    useEffect(() => {
        if (!hasUnsavedContent || isSubmitting) return;
        const handler = e => {
            e.preventDefault();
            e.returnValue = '';
        };
        window.addEventListener('beforeunload', handler);
        return () => window.removeEventListener('beforeunload', handler);
    }, [hasUnsavedContent, isSubmitting]);

    /* In-app guard — capture-phase click listener at the document root so
     * we run BEFORE React's synthetic handlers (React listens on the app
     * root in capture phase too, but document captures fire first).
     *
     * We only swallow clicks that look like a real same-origin SPA
     * navigation: primary mouse button, no modifier keys, an `<a>` with
     * a same-origin path that isn't `target=_blank` / download. Anything
     * else (external link, ctrl-click for new tab, etc.) is left alone. */
    useEffect(() => {
        if (!hasUnsavedContent || isSubmitting) return;
        const handler = e => {
            if (e.defaultPrevented) return;
            if (e.button !== 0) return;
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            const link = e.target?.closest?.('a[href]');
            if (!link) return;
            if (link.target && link.target !== '' && link.target !== '_self') return;
            if (link.hasAttribute('download')) return;
            const href = link.getAttribute('href');
            if (!href) return;
            // External / cross-origin → let it go (beforeunload will catch it).
            if (/^([a-z][a-z0-9+.-]*:|\/\/)/i.test(href)) return;
            e.preventDefault();
            e.stopPropagation();
            setPendingNavHref(href);
        };
        document.addEventListener('click', handler, true);
        return () => document.removeEventListener('click', handler, true);
    }, [hasUnsavedContent, isSubmitting]);

    const handleConfirmDiscard = () => {
        const href = pendingNavHref;
        setPendingNavHref(null);
        if (href) navigate(href);
    };

    const handleCancelDiscard = () => setPendingNavHref(null);

    /* See `pickerMediaUrl` declaration above. `handlePickerSelect` is
     * the GIF/sticker `onSelect` callback; the URL becomes a thumbnail
     * tile rendered right above the body editor and is prepended to
     * `contentValue` at submit time. */
    const handlePickerSelect = url => {
        if (!url) return;
        setPickerMediaUrl(url);
        setPickerThumbLoading(true);
    };
    const handleRemovePickerMedia = () => {
        if (isSubmitting) return;
        setPickerMediaUrl(null);
        setPickerThumbLoading(false);
    };

    /* Toggle the link input chip. Active state = chip is "on", which
     * happens whenever the input is open OR a URL has been typed. Clicking
     * an active chip collapses + clears the URL — "disable wipes value"
     * so users always know what's queued for submission. */
    const showLinkInput = linkOpen || !!linkUrl;
    const handleLinkToggle = () => {
        if (showLinkInput) {
            setLinkOpen(false);
            setLinkUrl('');
        } else {
            setLinkOpen(true);
        }
        if (submitError) setSubmitError('');
    };

    /* Wrap the hook's topic change handler so we can surface a guidance
     * note when the user picks the "Create #xyz" option in TopicSelector. */
    const wrappedTopicChange = e => {
        const meta = e?.meta || {};
        setTopicIsNew(!!meta.isNew);
        handleTopicChange(e);
    };

    const tierLabel = limits.unlimited ? 'admin' : (limits.willPayFee ? 'paid tier' : 'free tier');

    const submitLabel = isSubmitting
        ? submitStatus === 'verifying'
            ? 'Verifying...'
            : submitStatus === 'submitting'
                ? 'Submitting...'
                : 'Processing'
        : isEditMode ? 'Save Edit' : 'Post';

    const titleValid = useMemo(() => {
        const len = getByteLength(titleValue || '');
        return len >= (limits.minTitle || 1) && len <= limits.maxTitle;
    }, [titleValue, getByteLength, limits.minTitle, limits.maxTitle]);

    /* Link validation — returns `{ ok, error }` so we can render inline help.
     *
     * Rules:
     *  1. Non-empty input.
     *  2. Must literally contain `://` — otherwise `new URL("https:google.com")`
     *     is accepted by WHATWG (it treats `google.com` as the path),
     *     which is almost always a typo the user wants flagged.
     *  3. Scheme must be http(s).
     *  4. Host must be present and contain at least one dot. */
    const linkValidation = useMemo(() => {
        if (!linkUrl || !linkUrl.trim()) return { ok: false, error: '' };
        const raw = linkUrl.trim();
        if (!raw.includes('://')) {
            return { ok: false, error: 'Links must start with http:// or https://.' };
        }
        let parsed;
        try {
            parsed = new URL(raw);
        } catch (_) {
            return { ok: false, error: 'Enter a valid URL (e.g. https://example.com).' };
        }
        const scheme = (parsed.protocol || '').toLowerCase();
        if (scheme !== 'http:' && scheme !== 'https:') {
            return { ok: false, error: 'Links must start with http:// or https://.' };
        }
        if (!parsed.hostname || !parsed.hostname.includes('.')) {
            return { ok: false, error: 'Enter a valid hostname.' };
        }
        return { ok: true, error: '' };
    }, [linkUrl]);
    const linkValid = linkValidation.ok;

    /* Submit gate — disables the Post button until required fields are filled. */
    const canSubmit = useMemo(() => {
        if (isSubmitting || isUploading) return false;
        if (!topicValue || topicValue.length < (limits.minTopic || 1)) return false;
        if (!titleValid) return false;
        if (linkUrl.trim() && !linkValid) return false;
        return true;
    }, [isSubmitting, isUploading, topicValue, limits.minTopic, titleValid, linkUrl, linkValid]);

    const activeMedia = attachedMedia[Math.min(slideIndex, Math.max(0, attachedMedia.length - 1))];
    const canPrev = attachedMedia.length > 1 && slideIndex > 0;
    const canNext = attachedMedia.length > 1 && slideIndex < attachedMedia.length - 1;

    /* Auto-advance to the most recently added media slide AND collapse
     * the drop panel after a successful upload. The panel is treated
     * as a one-shot affordance: open it via "+ Media" (or auto-open on
     * drag), drop a file, panel closes. To attach another, click
     * "+ Media" again or drag a new file — the auto-open-on-drag
     * effect will reopen it. */
    const lastMediaCountRef = useRef(attachedMedia.length);
    useEffect(() => {
        const prev = lastMediaCountRef.current;
        const next = attachedMedia.length;
        if (next > prev) {
            setSlideIndex(next - 1);
            setMediaPanelOpen(false);
            setMediaPanelDragging(false);
        } else if (next === 0) {
            setSlideIndex(0);
        } else if (slideIndex > next - 1) {
            setSlideIndex(Math.max(0, next - 1));
        }
        lastMediaCountRef.current = next;
    }, [attachedMedia.length, slideIndex]);

    /* -------------------------------------------------------------------- */
    /* Auto-open / auto-close the media panel on file drag                  */
    /*                                                                      */
    /* The panel is the *single* drop target — drops outside it do nothing */
    /* (we only suppress the browser-default of navigating to the file).   */
    /* Window-level handlers do two things:                                 */
    /*                                                                      */
    /* 1. Surface the panel automatically when a file is dragged anywhere   */
    /*    over the page so the user always sees where to drop, without     */
    /*    needing to click "+ Media" first.                                 */
    /* 2. Hide it again if the user drags back out without dropping.        */
    /*                                                                      */
    /* Implementation notes:                                                */
    /*                                                                      */
    /* - We detect "drag truly left the viewport" via dragleave's          */
    /*    `e.relatedTarget`: when moving across child elements within the  */
    /*    page, relatedTarget is the element being entered (non-null);     */
    /*    when the drag exits the window entirely, relatedTarget is null.  */
    /*    This is more reliable than counter or timer schemes — those     */
    /*    fight against the noisy enter/leave events that fire on every    */
    /*    child transition and produce flicker. With relatedTarget, in-    */
    /*    page moves are a clean no-op.                                    */
    /* - `panelOpenedByDragRef` ensures we only auto-close panels we       */
    /*    auto-opened — a manually-clicked "+ Media" panel is immune.     */
    /* - `drop` outside the panel is a no-op upload-wise (we honor the     */
    /*    user's "single area" rule) but we still preventDefault to stop   */
    /*    the browser from navigating to the file URL, and we close the    */
    /*    panel if it was drag-owned so the user can re-open with a clean  */
    /*    slate.                                                            */
    /* - The panel's own `onDrop` calls e.stopPropagation(), so this       */
    /*    listener never sees drops that landed inside the panel.          */
    /* -------------------------------------------------------------------- */
    useEffect(() => {
        const hasFiles = e => {
            const types = Array.from(e?.dataTransfer?.types ?? []);
            return types.includes('Files');
        };
        const closeIfDragOwned = () => {
            if (!panelOpenedByDragRef.current) return;
            panelOpenedByDragRef.current = false;
            setMediaPanelOpen(false);
            setMediaPanelDragging(false);
        };
        const onWindowDragEnter = e => {
            if (!hasFiles(e)) return;
            if (isSubmitting || isUploading) return;
            if (attachedMedia.length >= MAX_MEDIA) return;
            setMediaPanelOpen(prev => {
                if (!prev) {
                    panelOpenedByDragRef.current = true;
                    return true;
                }
                return prev;
            });
        };
        const onWindowDragOver = e => {
            const types = Array.from(e?.dataTransfer?.types ?? []);
            if (!types.includes('Files')) return;
            e.preventDefault();
        };
        const onWindowDragLeave = e => {
            // In-page moves: relatedTarget is the new element under the
            // cursor (non-null) — ignore. Truly leaving the window:
            // relatedTarget is null — close the panel if drag-owned.
            if (e.relatedTarget) return;
            closeIfDragOwned();
        };
        const onWindowDrop = e => {
            if (!hasFiles(e)) return;
            e.preventDefault();
            // Drops outside the panel are intentionally not uploaded —
            // the panel is the single designated drop target. We just
            // suppress the browser-default and close the panel if it
            // was opened by this drag.
            closeIfDragOwned();
        };
        window.addEventListener('dragenter', onWindowDragEnter);
        window.addEventListener('dragover', onWindowDragOver);
        window.addEventListener('dragleave', onWindowDragLeave);
        window.addEventListener('drop', onWindowDrop);
        return () => {
            window.removeEventListener('dragenter', onWindowDragEnter);
            window.removeEventListener('dragover', onWindowDragOver);
            window.removeEventListener('dragleave', onWindowDragLeave);
            window.removeEventListener('drop', onWindowDrop);
        };
    }, [isSubmitting, isUploading, attachedMedia.length, MAX_MEDIA]);

    const handleWrappedSubmit = e => {
        /* Resolve the body string for this submit synchronously — React
         * state updates are async, so we can't `setContentValue(...)` and
         * then call `handleSubmit` and expect the new value to land. We
         * pass the resolved body through `opts.content` instead, same
         * shape comments use (see useViewPost.handleSubmit's
         * `${mediaUrl}\n\n${replyString}` trick). */
        let bodyForSubmit = (linkUrl.trim() && linkValid && !contentValue)
            ? linkUrl
            : contentValue;
        if (pickerMediaUrl) {
            const trimmed = String(bodyForSubmit || '').trim();
            bodyForSubmit = trimmed
                ? `${pickerMediaUrl}\n\n${trimmed}`
                : pickerMediaUrl;
        }
        return handleSubmit(e, { content: bodyForSubmit });
    };

    const handleRemoveActiveMedia = () => {
        if (isSubmitting) return;
        setAttachedMedia(prev => {
            const next = prev.filter((_, i) => i !== slideIndex);
            setSlideIndex(idx => Math.max(0, Math.min(idx, next.length - 1)));
            return next;
        });
    };

    /* Toggle the inline media panel. One-shot: clicking opens the panel,
     * a successful upload closes it (handled by the auto-advance effect),
     * and the user reopens it via another "+ Media" click for the next
     * file. Dragging a file anywhere on the page also auto-opens it.
     * We clear the drag-ownership flag here so a stray dragleave can't
     * close a panel the user explicitly opened with the chip. */
    const handleMediaChipClick = () => {
        panelOpenedByDragRef.current = false;
        setMediaPanelOpen(prev => {
            const next = !prev;
            if (!next) setMediaPanelDragging(false);
            return next;
        });
    };

    /* Choose-file button inside the panel. Routes to the editor's hidden
     * file input. The panel will auto-close on successful upload; if the
     * user wants another file they re-click "+ Media". */
    const handleMediaPanelChoose = () => {
        try { editorUpload && editorUpload.selectFile(); } catch (_) { /* noop */ }
    };

    const handleMediaPanelDrop = e => {
        try {
            e.preventDefault();
            e.stopPropagation();
            setMediaPanelDragging(false);
            if (isUploading || attachedMedia.length >= MAX_MEDIA) return;
            const files = Array.from(e?.dataTransfer?.files ?? []);
            if (!files || files.length === 0) return;
            if (editorUpload && typeof editorUpload.uploadFile === 'function') {
                editorUpload.uploadFile(files[0]);
            }
        } catch (_) { /* noop */ }
    };

    const handleMediaPanelDragOver = e => {
        try {
            const types = Array.from(e?.dataTransfer?.types ?? []);
            if (!types.includes('Files')) return;
            e.preventDefault();
            e.stopPropagation();
            if (!mediaPanelDragging) setMediaPanelDragging(true);
        } catch (_) { /* noop */ }
    };

    const handleMediaPanelDragLeave = e => {
        try {
            const types = Array.from(e?.dataTransfer?.types ?? []);
            if (!types.includes('Files')) return;
            e.preventDefault();
            e.stopPropagation();
            if (!e.currentTarget.contains(e.relatedTarget)) setMediaPanelDragging(false);
        } catch (_) { /* noop */ }
    };

    return (
        <ContentGrid>
            <Helmet>
                <title>{isEditMode ? 'Edit Post' : 'Create Post'} | Mirage</title>
            </Helmet>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
                    <ModernPostFeed>
                        <ComposerColumn>
                            <HeaderRow>
                                <HeaderTitle>{isEditMode ? 'Edit post' : 'Create post'}</HeaderTitle>
                            </HeaderRow>
                            <Stack
                                id="create-post-form"
                                onSubmit={handleWrappedSubmit}
                                autoComplete="off"
                                onKeyDown={e => {
                                    if (e.key !== 'Tab') return;
                                    const form = e.currentTarget;
                                    const focusable = form.querySelectorAll('input:not([type="hidden"]):not([tabindex="-1"]):not(:disabled), textarea:not(:disabled), button[type="submit"]:not(:disabled)');
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
                                }}
                            >
                                {isEditMode && (
                                    <EditHashRow>
                                        <EditHashLabel>Tx hash</EditHashLabel>
                                        <Mono>{overrideId}</Mono>
                                    </EditHashRow>
                                )}

                                <TopicSelector
                                    value={topicValue}
                                    maxLength={limits.maxTopic}
                                    minLength={limits.minTopic}
                                    onChange={wrappedTopicChange}
                                    disabled={isSubmitting}
                                    aria-label="Topic"
                                />

                                {topicIsNew && (
                                    <NewTopicNote role="note">
                                        <span>
                                            Topics are communities centered around specific interests. Posting in the wrong topic may affect your overall trust status on Mirage. Make sure to post into the right category!
                                        </span>
                                    </NewTopicNote>
                                )}

                                <Field>
                                    <InputShell>
                                        <FloatLabel htmlFor="title">Title</FloatLabel>
                                        <ShellInput
                                            ref={titleInputRef}
                                            name="title"
                                            id="title"
                                            value={titleValue}
                                            placeholder="Title"
                                            onPaste={handleTitlePaste}
                                            autoComplete="off"
                                            autoCorrect="on"
                                            autoCapitalize="sentences"
                                            spellCheck
                                            maxLength={limits.maxTitle}
                                            onChange={handleTitleChange}
                                            disabled={isSubmitting}
                                            aria-label="Title"
                                            onKeyDown={e => {
                                                if (e.key === 'Enter') {
                                                    e.preventDefault();
                                                    if (contentEditorRef.current) contentEditorRef.current.focus();
                                                }
                                            }}
                                        />
                                        {titleValid && (
                                            <ValidCheck aria-hidden="true">
                                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                                    <polyline points="20 6 9 17 4 12" />
                                                </svg>
                                            </ValidCheck>
                                        )}
                                        <Counter $warn={!limits.unlimited && getByteLength(titleValue) >= limits.maxTitle}>
                                            ({tierLabel}) {limits.unlimited ? `${getByteLength(titleValue)} / unlimited` : `${getByteLength(titleValue)} / ${limits.maxTitle}`}
                                        </Counter>
                                    </InputShell>
                                </Field>

                                {/* Action chips — text-label pill buttons that
                                  * sit between Title and Body. Each chip
                                  * unfurls its artifact (tag card, link
                                  * input, media carousel) right below the
                                  * row, so attached content sits above the
                                  * body just like it will in the rendered
                                  * post. Sticker / GIF use the picker's
                                  * `renderTrigger` to swap in a chip while
                                  * keeping the picker's popover behavior. */}
                                <ActionRow>
                                    <ActionChip
                                        type="button"
                                        onClick={handleLinkToggle}
                                        disabled={isSubmitting}
                                        $active={showLinkInput}
                                        aria-pressed={showLinkInput}
                                        aria-label="Add link"
                                    >
                                        + Link
                                    </ActionChip>
                                    <ActionChip
                                        type="button"
                                        onClick={handleMediaChipClick}
                                        disabled={isSubmitting}
                                        $active={mediaPanelOpen || attachedMedia.length > 0}
                                        aria-pressed={mediaPanelOpen}
                                        aria-expanded={mediaPanelOpen}
                                        aria-controls="media-drop-panel"
                                        aria-label="Add image or video"
                                    >
                                        + Media
                                    </ActionChip>
                                    <TagChipWrap ref={tagMenuWrapRef}>
                                        <ActionChip
                                            type="button"
                                            onClick={() => setTagMenuOpen(prev => !prev)}
                                            disabled={isSubmitting}
                                            $set={!!tagDisplayLabel}
                                            $active={tagMenuOpen}
                                            aria-haspopup="menu"
                                            aria-expanded={tagMenuOpen}
                                            aria-label={tagDisplayLabel ? `Content tag: ${tagDisplayLabel}` : 'Add content tag'}
                                        >
                                            {tagDisplayLabel ? `Tag: ${tagDisplayLabel}` : '+ Tag'}
                                            <HiChevronDown aria-hidden="true" />
                                        </ActionChip>
                                        {tagMenuOpen && (
                                            <TagMenu role="menu">
                                                {TAG_OPTIONS_ENABLED.map(opt => {
                                                    const shortLabel = String(opt.label || '').replace(/\s*\(.*?\)\s*/g, '').trim();
                                                    const checked = tagEnabled && tagValue === opt.value;
                                                    return (
                                                        <TagMenuItem
                                                            key={opt.value}
                                                            type="button"
                                                            role="menuitemradio"
                                                            aria-checked={checked}
                                                            $selected={checked}
                                                            disabled={isSubmitting}
                                                            onClick={() => handleTagSelect(opt.value)}
                                                        >
                                                            <span>{shortLabel}</span>
                                                            {checked && <TagMenuCheck aria-hidden="true">✓</TagMenuCheck>}
                                                        </TagMenuItem>
                                                    );
                                                })}
                                                {tagEnabled && tagValue && (
                                                    <>
                                                        <TagMenuDivider />
                                                        <TagMenuItem
                                                            type="button"
                                                            role="menuitem"
                                                            disabled={isSubmitting}
                                                            onClick={() => handleTagSelect('')}
                                                        >
                                                            <span>Remove tag</span>
                                                        </TagMenuItem>
                                                    </>
                                                )}
                                                <TagMenuDivider />
                                                <TagMenuFooter>
                                                    Flag posts with sensitive material so users can opt in or filter them out.
                                                </TagMenuFooter>
                                            </TagMenu>
                                        )}
                                    </TagChipWrap>
                                </ActionRow>

                                {/* Link URL — unfurls when the link chip is
                                  * active. autoFocus so users can type
                                  * immediately after clicking the chip. */}
                                {showLinkInput && (
                                    <Field>
                                        <InputShell>
                                            <FloatLabel htmlFor="link-url">Link URL</FloatLabel>
                                            <ShellInput
                                                id="link-url"
                                                name="link-url"
                                                type="url"
                                                value={linkUrl}
                                                placeholder="Link URL (optional)"
                                                autoComplete="off"
                                                spellCheck={false}
                                                autoFocus
                                                onChange={e => setLinkUrl(e.target.value)}
                                                disabled={isSubmitting}
                                                aria-label="Link URL"
                                            />
                                            {linkValid && (
                                                <ValidCheck aria-hidden="true">
                                                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                                        <polyline points="20 6 9 17 4 12" />
                                                    </svg>
                                                </ValidCheck>
                                            )}
                                        </InputShell>
                                        {linkUrl.trim() && linkValidation.error && (
                                            <FieldError role="alert">{linkValidation.error}</FieldError>
                                        )}
                                    </Field>
                                )}

                                {/* Inline media drop panel — one-shot: opens
                                  * via the "+ Media" chip (or auto-opens
                                  * when a file is dragged anywhere over
                                  * the page) and closes itself once the
                                  * upload completes. To attach another
                                  * file the user clicks "+ Media" again
                                  * or drags. "Choose file" covers the
                                  * OS-picker fallback. */}
                                {mediaPanelOpen && (
                                    <Field>
                                        <MediaDropZone
                                            id="media-drop-panel"
                                            $dragging={mediaPanelDragging}
                                            onDragOver={handleMediaPanelDragOver}
                                            onDragLeave={handleMediaPanelDragLeave}
                                            onDrop={handleMediaPanelDrop}
                                        >
                                            <MediaDropIcon aria-hidden="true">
                                                <HiArrowUpTray />
                                            </MediaDropIcon>
                                            {/* Upload status lives solely in the carousel below to
                                              * avoid double "Uploading…" labels — when isUploading
                                              * we hide this row entirely. */}
                                            {!isUploading && (
                                                <MediaDropText>
                                                    {attachedMedia.length >= MAX_MEDIA
                                                        ? `Max ${MAX_MEDIA} attachments reached`
                                                        : 'Drag and drop an image or video here'}
                                                </MediaDropText>
                                            )}
                                            {attachedMedia.length < MAX_MEDIA && !isUploading && (
                                                <>
                                                    <MediaDropHint>or</MediaDropHint>
                                                    <Button
                                                        variant="primary"
                                                        size="sm"
                                                        type="button"
                                                        onClick={handleMediaPanelChoose}
                                                        disabled={isSubmitting}
                                                    >
                                                        Choose file
                                                    </Button>
                                                </>
                                            )}
                                        </MediaDropZone>
                                    </Field>
                                )}

                                {/* Media carousel — only renders once at least
                                  * one media item is attached or an upload
                                  * is in flight. The empty drop-zone tile
                                  * is gone; the + Media chip above is now
                                  * the entry point. Whole-page drag/drop
                                  * still works via the outer ContentGrid
                                  * handlers. */}
                                {(attachedMedia.length > 0 || isUploading) && (
                                    <Field>
                                        {(() => {
                                            const activeUrl = activeMedia?.url;
                                            const activeLoading = !!(activeUrl && thumbsLoading && thumbsLoading.has(activeUrl));
                                            const showLoadingState = isUploading || activeLoading;
                                            return (
                                                <CarouselTile
                                                    $hasMedia={attachedMedia.length > 0}
                                                    $loading={showLoadingState}
                                                >
                                                    {attachedMedia.length === 0 && isUploading && (
                                                        <MediaSlidePlaceholder>
                                                            <MediaSpinnerRing aria-hidden="true" />
                                                            <span>
                                                                Uploading{uploadProgress !== null ? ` ${Math.round(uploadProgress)}%` : '...'}
                                                            </span>
                                                        </MediaSlidePlaceholder>
                                                    )}
                                                    {attachedMedia.length > 0 && (
                                                        <>
                                                            <CarouselHeader>
                                                                <SlideCounter
                                                                    aria-live="polite"
                                                                    aria-atomic="true"
                                                                    title={`${attachedMedia.length} of ${MAX_MEDIA} attachments`}
                                                                >
                                                                    {attachedMedia.length} / {MAX_MEDIA}
                                                                </SlideCounter>
                                                                <HeaderDelete
                                                                    type="button"
                                                                    tabIndex={-1}
                                                                    onClick={handleRemoveActiveMedia}
                                                                    disabled={isSubmitting}
                                                                    aria-label="Remove media"
                                                                    title="Remove"
                                                                >
                                                                    <HiTrash aria-hidden="true" />
                                                                </HeaderDelete>
                                                            </CarouselHeader>
                                                            <MediaSlide>
                                                                {activeLoading && (
                                                                    <MediaSlidePlaceholder>
                                                                        <MediaSpinnerRing aria-hidden="true" />
                                                                        <span>Processing media…</span>
                                                                    </MediaSlidePlaceholder>
                                                                )}
                                                                <MediaSlideImage
                                                                    $loaded={!activeLoading}
                                                                    src={activeMedia?.type === 'image' ? activeMedia.url : getVideoThumbnailUrl(activeMedia?.url) || activeMedia?.url}
                                                                    alt=""
                                                                    onLoad={() => {
                                                                        if (!activeMedia) return;
                                                                        setThumbsLoading(prev => {
                                                                            const n = new Set(prev);
                                                                            n.delete(activeMedia.url);
                                                                            return n;
                                                                        });
                                                                    }}
                                                                    onError={() => {
                                                                        if (!activeMedia) return;
                                                                        setThumbsLoading(prev => {
                                                                            const n = new Set(prev);
                                                                            n.delete(activeMedia.url);
                                                                            return n;
                                                                        });
                                                                    }}
                                                                />
                                                                {canPrev && (
                                                                    <NavPrev
                                                                        type="button"
                                                                        tabIndex={-1}
                                                                        onClick={() => setSlideIndex(i => Math.max(0, i - 1))}
                                                                        aria-label="Previous media"
                                                                        $iconOnly
                                                                    >
                                                                        <HiChevronLeft aria-hidden="true" />
                                                                    </NavPrev>
                                                                )}
                                                                {canNext && (
                                                                    <NavNext
                                                                        type="button"
                                                                        tabIndex={-1}
                                                                        onClick={() => setSlideIndex(i => Math.min(attachedMedia.length - 1, i + 1))}
                                                                        aria-label="Next media"
                                                                        $iconOnly
                                                                    >
                                                                        <HiChevronRight aria-hidden="true" />
                                                                    </NavNext>
                                                                )}
                                                            </MediaSlide>
                                                        </>
                                                    )}
                                                    {isUploading && attachedMedia.length > 0 && (
                                                        <UploadingBadge>
                                                            Uploading {uploadProgress !== null ? `${Math.round(uploadProgress)}%` : '...'}
                                                            <Button
                                                                variant="danger"
                                                                size="xs"
                                                                tabIndex={-1}
                                                                onClick={() => {
                                                                    try {
                                                                        if (editorUpload && editorUpload.cancelUpload) {
                                                                            editorUpload.cancelUpload();
                                                                        }
                                                                    } catch (_) { /* noop */ }
                                                                }}
                                                            >
                                                                Cancel
                                                            </Button>
                                                        </UploadingBadge>
                                                    )}
                                                </CarouselTile>
                                            );
                                        })()}
                                    </Field>
                                )}

                                {/* Picker-attached image preview tile. Same shape the
                                  * reply editor uses (MediaRow > MediaPreviewWrapper >
                                  * MediaPreviewImage + MediaRemoveButton). Sits right
                                  * above the body editor so the user actually sees the
                                  * picked GIF / sticker without flipping a preview pane. */}
                                {pickerMediaUrl && (
                                    <Field>
                                        <MediaRow>
                                            <MediaPreviewWrapper>
                                                <MediaPreviewImage
                                                    src={pickerMediaUrl}
                                                    alt=""
                                                    onLoad={() => setPickerThumbLoading(false)}
                                                    onError={() => setPickerThumbLoading(false)}
                                                />
                                                {pickerThumbLoading && <MediaSpinner />}
                                                <MediaRemoveButton
                                                    type="button"
                                                    tabIndex={-1}
                                                    disabled={isSubmitting}
                                                    onClick={handleRemovePickerMedia}
                                                    aria-label="Remove attached image"
                                                    title="Remove attached image"
                                                >
                                                    ×
                                                </MediaRemoveButton>
                                            </MediaPreviewWrapper>
                                        </MediaRow>
                                    </Field>
                                )}

                                {/* Body editor — primary input. Optional. */}
                                <EditorMount>
                                    <Field>
                                        <EditorShell>
                                            <DefaultEditorChrome>
                                                <MarkdownEditor
                                                    value={contentValue}
                                                    onChange={v => setContentValue(v)}
                                                    maxLength={limits.maxContent}
                                                    disabled={isSubmitting}
                                                    uploadBlocked={attachedMedia.length >= MAX_MEDIA}
                                                    placeholder="Body (optional)"
                                                    toolbarExtra={
                                                        <EditorMediaTools
                                                            onSelect={handlePickerSelect}
                                                            onUploadImage={() => {
                                                                try { editorUpload && editorUpload.selectFile('image'); } catch (_) { /* noop */ }
                                                            }}
                                                            onLinkImage={() => {
                                                                try { editorUpload && editorUpload.insertImageLink(); } catch (_) { /* noop */ }
                                                            }}
                                                            disabled={isSubmitting || !!pickerMediaUrl}
                                                        />
                                                    }
                                                    onSubmitShortcut={() => {
                                                        try {
                                                            const form = document.getElementById('create-post-form');
                                                            if (form) form.requestSubmit();
                                                        } catch (_) { /* noop */ }
                                                    }}
                                                    showCounters={false}
                                                    renderHelperRow={false}
                                                    toolbarButtonSize="1.6rem"
                                                    toolbarIconSize="0.9rem"
                                                    minHeight="6rem"
                                                    registerUploadHandler={setEditorUpload}
                                                    editorRef={ref => { contentEditorRef.current = ref; }}
                                                    onMediaUploaded={(type, url, error) => {
                                                        if (error) {
                                                            if (errorClearTimeoutRef.current) {
                                                                clearTimeout(errorClearTimeoutRef.current);
                                                                errorClearTimeoutRef.current = null;
                                                            }
                                                            errorSetTimeRef.current = Date.now();
                                                            setSubmitError(error);
                                                            errorClearTimeoutRef.current = setTimeout(() => {
                                                                setSubmitError('');
                                                                errorSetTimeRef.current = null;
                                                                errorClearTimeoutRef.current = null;
                                                            }, 5000);
                                                        } else if (!type || !url) {
                                                            if (errorClearTimeoutRef.current) {
                                                                clearTimeout(errorClearTimeoutRef.current);
                                                                errorClearTimeoutRef.current = null;
                                                            }
                                                            errorSetTimeRef.current = Date.now();
                                                            setSubmitError('Media upload failed. Please try again.');
                                                            errorClearTimeoutRef.current = setTimeout(() => {
                                                                setSubmitError('');
                                                                errorSetTimeRef.current = null;
                                                                errorClearTimeoutRef.current = null;
                                                            }, 5000);
                                                        } else {
                                                            addMediaItem(type, url);
                                                        }
                                                    }}
                                                    onUploadStateChange={uploading => {
                                                        setIsUploading(uploading);
                                                        if (!uploading) setUploadProgress(null);
                                                    }}
                                                    onUploadProgress={progress => setUploadProgress(progress)}
                                                />
                                            </DefaultEditorChrome>
                                        </EditorShell>
                                    </Field>
                                    <ContentCounterRow>
                                        <ContentCounter $warn={!limits.unlimited && contentValue.length >= limits.maxContent}>
                                            ({tierLabel}) {limits.unlimited ? `${contentValue.length} / unlimited` : `${contentValue.length} / ${limits.maxContent}`}
                                        </ContentCounter>
                                    </ContentCounterRow>
                                </EditorMount>

                                {submitError && <ErrorMessage role="alert">{submitError}</ErrorMessage>}

                                <BottomBar>
                                    <span aria-hidden="true" />
                                    <SubmitGroup>
                                        <PostBtn
                                            type="submit"
                                            disabled={!canSubmit}
                                            aria-disabled={!canSubmit}
                                        >
                                            {submitLabel}
                                        </PostBtn>
                                    </SubmitGroup>
                                </BottomBar>
                            </Stack>
                        </ComposerColumn>
                    </ModernPostFeed>
                </FeedCol>
                <FeedRightRail />
            </FeedRailRow>
            <ConfirmDialog
                open={!!pendingNavHref}
                title="Discard post?"
                message="You have unsaved content. If you leave now, what you've typed will be lost."
                confirmLabel="Discard"
                cancelLabel="Keep editing"
                confirmVariant="danger"
                onConfirm={handleConfirmDiscard}
                onCancel={handleCancelDiscard}
            />
        </ContentGrid>
    );
}

export default CreatePostView;
