import { useState, useMemo, useEffect, useRef } from "react";
import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { HiArrowUpTray, HiPlus, HiTrash, HiChevronLeft, HiChevronRight } from "react-icons/hi2";
import { TopicSelector } from "../components/TopicSelector.js";
import MarkdownEditor from "../components/MarkdownEditor.js";
import Button from "../components/Button.js";
import LoggedOutPromptCard from "../components/LoggedOutPromptCard.js";
import { ContentGrid, ModernPostFeed, CappedPageColumn } from "../Layout";
import { MediaRow } from "../components/MediaAttachmentLayout.js";
import StickerPicker from "../components/StickerPicker.js";
import GifPicker from "../components/GifPicker.js";
import { RadioInput } from "../../../logic/useSettings.js";
import { useCreatePost, TAG_OPTIONS_ENABLED } from "../../../logic/useCreatePost";

/**
 * mirageapp `CreatePostView` — Reddit-inspired, mirageapp-tokenized.
 *
 * Follows R1 (bg canvas), R2 (tokens only), R3 (border dividers),
 * R5 (neutral input focus), R6 (HiChevronDown), R7 (compact font scale).
 *
 * Layout
 *  - Header row mirrors `InboxView::HeaderRow`/`HeaderTitle` (1.1rem/700,
 *    `0.25rem 1rem 0.5rem` padding) plus a trailing "Drafts" hint.
 *  - 720px capped `ComposerColumn` (matches Inbox width).
 *  - Stacked blocks: topic pill → tabs → title input (shared across tabs)
 *    → tag pill → tab body (editor / carousel / link input) → bottom bar.
 *
 * Typography (R7)
 *  - All inputs, pills, tab labels, help text: 0.75rem / 500 (inputs),
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
`;

const HeaderTitle = styled.div`
    display: flex;
    align-items: center;
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

const DraftsHint = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
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
`;

const Field = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    min-width: 0;
`;

/* -------------------------------------------------------------------------- */
/* Tabs (Text / Images & Video / Link)                                        */
/* -------------------------------------------------------------------------- */

const TabsRow = styled.div`
    display: flex;
    align-items: center;
    gap: 1.25rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const TabButton = styled.button`
    position: relative;
    background: transparent;
    border: none;
    padding: 0.4rem 0;
    margin: 0;
    font-family: inherit;
    font-size: 0.75rem;
    font-weight: ${({ $active }) => ($active ? 600 : 500)};
    line-height: 1.2;
    cursor: pointer;
    color: ${({ $active, theme }) => ($active ? theme.colors.text : theme.colors.subtleText)};
    transition: color 0.15s ease;

    &:hover:not(:disabled) { color: ${({ theme }) => theme.colors.text}; }

    &:disabled { cursor: not-allowed; opacity: 0.5; }

    &::after {
        content: '';
        position: absolute;
        left: 0;
        right: 0;
        bottom: -1px;
        height: 2px;
        border-radius: 2px;
        background: ${({ $active, theme }) => ($active ? theme.colors.focusBlue : 'transparent')};
        transition: background 0.15s ease;
    }

    &:focus { outline: none; }
    &:focus-visible::after { background: ${({ theme }) => theme.colors.borderStrong}; }
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
    font-size: 0.75rem;
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
    font-size: 0.65rem;
    font-weight: 500;
    line-height: 1.45;

    &::before {
        content: '⚠';
        line-height: 1.2;
        font-size: 0.75rem;
        flex: 0 0 auto;
    }
`;

/* -------------------------------------------------------------------------- */
/* Add tags pill + radio card                                                 */
/* -------------------------------------------------------------------------- */

const TagPill = styled.button`
    align-self: flex-start;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0 0.7rem;
    height: 1.65rem;
    border-radius: 9999px;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ $active, theme }) => ($active ? theme.colors.panelAlt : 'transparent')};
    color: ${({ theme }) => theme.colors.subtleText};
    font-family: inherit;
    font-size: 0.68rem;
    font-weight: 500;
    cursor: pointer;
    transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;

    &:hover:not(:disabled) {
        border-color: ${({ theme }) => theme.colors.borderStrong};
        color: ${({ theme }) => theme.colors.text};
        background: ${({ theme }) => theme.colors.hoverBg};
    }

    &:disabled { opacity: 0.5; cursor: not-allowed; }

    &:focus { outline: none; }
    &:focus-visible { border-color: ${({ theme }) => theme.colors.borderStrong}; }
`;

const TagIcon = styled.span`
    font-size: 0.8rem;
    line-height: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const TagRadioCard = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    padding: 0.6rem 0.8rem;
    border: 1px solid ${({ theme }) => theme.colors.borderSubtle};
    border-radius: 12px;
    background: ${({ theme }) => theme.colors.bg};
`;

const RadioGroup = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
`;

const RadioLabel = styled.label`
    display: inline-grid;
    grid-template-columns: auto minmax(0, 1fr);
    column-gap: 0.5rem;
    align-items: center;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.7rem;
    font-weight: 500;
    line-height: 1.25;
    cursor: pointer;
    user-select: none;

    &:has(input:disabled) { cursor: not-allowed; opacity: 0.5; }
`;

const HelpText = styled.div`
    font-size: 0.62rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.5;

    b { color: ${({ theme }) => theme.colors.text}; font-weight: 600; }
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
/* `[data-mirageapp-editor]` prefixes (those would have to match a descendant */
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

    /* Toolbar row (MarkdownEditor's first inner row) — divider below. */
    > div > div:first-child {
        padding: 0.4rem 0.55rem;
        border-bottom: 1px solid ${({ theme }) => theme.colors.borderSubtle};
        background: transparent;
        margin: 0;
    }

    /* Toolbar icon buttons — transparent tile, no hover fill. */
    button[type='button'] {
        background: transparent !important;
        background-color: transparent !important;
        border: 1px solid transparent !important;
        border-radius: 6px !important;
        min-width: 1.6rem !important;
        height: 1.6rem !important;
        padding: 0.15rem 0.3rem !important;
        color: ${({ theme }) => theme.colors.feedCtrlText} !important;
        transition: color 0.12s ease !important;
        box-shadow: none !important;
    }
    button[type='button'] svg,
    button[type='button'] .md-icon {
        max-width: 0.9rem !important;
        max-height: 0.9rem !important;
    }
    /* Bold (B) and Italic (I) render as letter glyphs inside a <span>.
     * Bump the size so they read as prominent as the Lucide icons next to them. */
    button[type='button'] > span {
        font-size: 0.95rem !important;
        line-height: 1 !important;
    }
    button[type='button']:hover:not(:disabled) {
        background: transparent !important;
        background-color: transparent !important;
        color: ${({ theme }) => theme.colors.text} !important;
    }
    button[type='button'][data-active='true'] {
        background: transparent !important;
        background-color: transparent !important;
        color: ${({ theme }) => theme.colors.followBtnBg} !important;
        border-color: transparent !important;
    }

    /* Preview toggle — ghost pill; checkbox = transparent square with a
     * blue (followBtnBg) checkmark glyph when checked. */
    label {
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
    label:hover {
        background: transparent !important;
        background-color: transparent !important;
        color: ${({ theme }) => theme.colors.text} !important;
        border-color: ${({ theme }) => theme.colors.borderStrong} !important;
    }
    label input[type='checkbox'] {
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
    /* Checked state — filled blue (rgb(68,109,228)) square with a centered
     * white checkmark. Centering uses left/top 50% + translate so the
     * rotated glyph lands visually in the middle regardless of box size. */
    label input[type='checkbox']:checked {
        background: rgb(68, 109, 228) !important;
        background-color: rgb(68, 109, 228) !important;
        border-color: rgb(68, 109, 228) !important;
    }
    label input[type='checkbox']:checked::after {
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

    /* Textarea — transparent inside the bordered shell. */
    textarea {
        border: none !important;
        border-radius: 0 !important;
        background: transparent !important;
        background-color: transparent !important;
        color: ${({ theme }) => theme.colors.text} !important;
        padding: 0.7rem 0.85rem !important;
        font-size: 0.75rem !important;
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

    /* Live preview tile. */
    > div > :last-child {
        background: ${({ theme }) => theme.colors.composerPreviewBg} !important;
        border: 1px solid ${({ theme }) => theme.colors.borderSubtle} !important;
        border-radius: 10px !important;
        padding: 0.65rem 0.85rem !important;
        margin: 0.5rem 0.55rem 0.55rem !important;
        font-size: 0.75rem !important;
        color: ${({ theme }) => theme.colors.text} !important;
    }
    > div > :last-child > div:first-child {
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

/* Unified inline media toolbar (sticker / gif / attach) — lives below the
 * editor in the Text tab. Keeps media pickers out of the primary body
 * UI while remaining reachable. */
/* MediaToolbar
 * - Normalizes the StickerPicker/GifPicker buttons so their icons share one
 *   baseline. The GifPicker renders a 28x28 SVG inside a 28px tall button,
 *   which visually nudges above the StickerPicker's 16x16 icon. We scope a
 *   descendant rule to bring the GIF svg to 16px and keep its button at
 *   28x28 for pixel-perfect alignment with the sticker button. */
const MediaToolbar = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding-top: 0.25rem;
    flex-wrap: wrap;

    button {
        width: 28px !important;
        height: 28px !important;
        padding: 0 !important;
    }
    button svg {
        width: 16px !important;
        height: 16px !important;
        display: block !important;
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
        if ($loading) return '16rem';
        return $hasMedia ? '14rem' : '11rem';
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

/* Header row above the media slide holding Add (left) and Delete (right). */
const CarouselHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 0.2rem;
`;

const EmptyDropLabel = styled.div`
    display: inline-flex;
    align-items: center;
    gap: 0.6rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    font-weight: 500;
`;

const EmptyUploadBtn = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.9rem;
    height: 1.9rem;
    border-radius: 50%;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.panelAlt};
    color: ${({ theme }) => theme.colors.text};
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease;

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.surface2};
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }
    &:disabled { opacity: 0.5; cursor: not-allowed; }
    svg { font-size: 0.95rem; }
`;

const MediaSlide = styled.div`
    position: relative;
    width: 100%;
    flex: 1;
    min-height: 12rem;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 14px;
    overflow: hidden;
`;

const MediaSlideImage = styled.img`
    max-width: 100%;
    max-height: 26rem;
    height: auto;
    width: auto;
    display: ${({ $loaded }) => ($loaded ? 'block' : 'none')};
    object-fit: contain;
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
    animation: mirageapp-cp-spin 0.8s linear infinite;

    @keyframes mirageapp-cp-spin {
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

/* Add pill lives in the CarouselHeader (not on top of the image). */
const HeaderAdd = styled(CornerButton)`
    padding: 0 0.55rem;
    height: 1.6rem;
    font-size: 0.65rem;
    gap: 0.25rem;

    svg { font-size: 0.78rem; }
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

const DraftButton = styled.button`
    height: ${BTN_HEIGHT};
    padding: 0 0.9rem;
    border-radius: 9999px;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: transparent;
    color: ${({ theme }) => theme.colors.subtleText};
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.hoverBg};
        color: ${({ theme }) => theme.colors.text};
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    &:disabled { opacity: 0.5; cursor: not-allowed; }
`;

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
    font-size: 0.68rem;
    font-weight: 500;
    line-height: 1.45;

    &::before {
        content: '⚠';
        line-height: 1.2;
        font-size: 0.8rem;
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

const GlobalDropOverlay = styled.div`
    position: fixed;
    inset: 0;
    border: 2px dashed ${({ theme }) => theme.colors.borderStrong};
    background-color: ${({ theme }) => theme.colors.overlay};
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
    z-index: 250;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.85rem;
    font-weight: 600;
`;

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
    font-size: 0.65rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    word-break: break-all;
    overflow-wrap: anywhere;
`;

/** 720px cap — matches InboxView width. */
const ComposerColumn = styled.div`
    width: 100%;
    max-width: 720px;

    @media (min-width: 1001px) {
        [data-sidebar-hidden='true'] & {
            width: 80%;
            max-width: none;
        }
    }
`;

const TABS = [
    { id: 'text', label: 'Text' },
    { id: 'media', label: 'Images & Video' },
    { id: 'link', label: 'Link' },
];

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
                <CappedPageColumn>
                    <ModernPostFeed>
                        <LoggedOutPromptCard
                            role="region"
                            aria-label="Create a post on Mirage"
                            eyebrow="Create post"
                            title="Sign in to post on Mirage"
                            description="Create an account or sign in to publish posts, join topics, and participate on-chain."
                            links={[
                                { label: 'Watch Introduction (YouTube)', href: 'https://www.youtube.com/watch?v=TOvP32ihQ0M', external: true },
                                { label: 'Learn More', href: 'https://mirage.foundation', external: true },
                            ]}
                            inviteText="Have an invite code? Join the community today."
                            primaryLabel="Create account"
                            secondaryLabel="Sign in"
                        />
                    </ModernPostFeed>
                </CappedPageColumn>
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
        globalDragging,
        setGlobalDragging,
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

    const [activeTab, setActiveTab] = useState('text');
    const [linkUrl, setLinkUrl] = useState('');
    const [slideIndex, setSlideIndex] = useState(0);
    const [topicIsNew, setTopicIsNew] = useState(false);

    /* Wrap the hook's topic change handler so we can surface a guidance
     * note when the user picks the "Create #xyz" option in TopicSelector. */
    const wrappedTopicChange = e => {
        const meta = e?.meta || {};
        setTopicIsNew(!!meta.isNew);
        handleTopicChange(e);
    };

    const tierLabel = limits.willPayFee ? 'paid tier' : 'basic tier';

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
        if (activeTab === 'link' && !linkValid) return false;
        return true;
    }, [isSubmitting, isUploading, topicValue, limits.minTopic, titleValid, activeTab, linkValid]);

    const activeMedia = attachedMedia[Math.min(slideIndex, Math.max(0, attachedMedia.length - 1))];
    const canPrev = attachedMedia.length > 1 && slideIndex > 0;
    const canNext = attachedMedia.length > 1 && slideIndex < attachedMedia.length - 1;

    /* Auto-advance to the most recently added media slide. */
    const lastMediaCountRef = useRef(attachedMedia.length);
    useEffect(() => {
        const prev = lastMediaCountRef.current;
        const next = attachedMedia.length;
        if (next > prev) setSlideIndex(next - 1);
        else if (next === 0) setSlideIndex(0);
        else if (slideIndex > next - 1) setSlideIndex(Math.max(0, next - 1));
        lastMediaCountRef.current = next;
    }, [attachedMedia.length, slideIndex]);

    const onDragOver = e => {
        try {
            if (isUploading) return;
            const types = Array.from(e?.dataTransfer?.types ?? []);
            if (!types.includes('Files')) return;
            e.preventDefault();
            e.stopPropagation();
            if (!globalDragging) setGlobalDragging(true);
        } catch (_) { /* noop */ }
    };
    const onDragLeave = e => {
        try {
            if (isUploading) return;
            const types = Array.from(e?.dataTransfer?.types ?? []);
            if (!types.includes('Files')) return;
            e.preventDefault();
            e.stopPropagation();
            if (!e.currentTarget.contains(e.relatedTarget)) setGlobalDragging(false);
        } catch (_) { /* noop */ }
    };
    const onDrop = e => {
        try {
            if (isUploading || attachedMedia.length >= MAX_MEDIA) {
                e.preventDefault();
                e.stopPropagation();
                return;
            }
            const files = Array.from(e?.dataTransfer?.files ?? []);
            if (!files || files.length === 0) return;
            e.preventDefault();
            e.stopPropagation();
            setGlobalDragging(false);
            if (editorUpload && typeof editorUpload.uploadFile === 'function') {
                editorUpload.uploadFile(files[0]);
                setActiveTab('media');
            }
        } catch (_) { /* noop */ }
    };

    const handleTagToggle = () => {
        const enabled = !tagEnabled;
        setTagEnabled(enabled);
        if (enabled) {
            setTagValue(prev => prev || (TAG_OPTIONS_ENABLED.find(o => o.value)?.value) || 'sensitive');
            setTagManuallySet(true);
        } else {
            setTagValue('');
            setTagManuallySet(true);
        }
        if (submitError) setSubmitError('');
    };

    const handleWrappedSubmit = e => {
        if (activeTab === 'link' && linkValid && !contentValue) {
            setContentValue(linkUrl);
        }
        return handleSubmit(e);
    };

    const handleRemoveActiveMedia = () => {
        if (isSubmitting) return;
        setAttachedMedia(prev => {
            const next = prev.filter((_, i) => i !== slideIndex);
            setSlideIndex(idx => Math.max(0, Math.min(idx, next.length - 1)));
            return next;
        });
    };

    const handleUploadClick = () => {
        try { editorUpload && editorUpload.selectFile(); } catch (_) { /* noop */ }
    };

    return (
        <ContentGrid onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}>
            <Helmet>
                <title>{isEditMode ? 'Edit Post' : 'Create Post'} | Mirage</title>
            </Helmet>
            <CappedPageColumn>
                <ModernPostFeed>
                    <ComposerColumn>
                        <HeaderRow>
                            <HeaderTitle>{isEditMode ? 'Edit post' : 'Create post'}</HeaderTitle>
                            <DraftsHint aria-hidden="true">Drafts(0)</DraftsHint>
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

                            <TabsRow role="tablist">
                                {TABS.map(t => (
                                    <TabButton
                                        key={t.id}
                                        type="button"
                                        role="tab"
                                        aria-selected={activeTab === t.id}
                                        $active={activeTab === t.id}
                                        onClick={() => setActiveTab(t.id)}
                                        disabled={isSubmitting}
                                    >
                                        {t.label}
                                    </TabButton>
                                ))}
                            </TabsRow>

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
                                    <Counter $warn={getByteLength(titleValue) >= limits.maxTitle}>
                                        ({tierLabel}) {getByteLength(titleValue)}/{limits.maxTitle}
                                    </Counter>
                                </InputShell>
                            </Field>

                            <Field style={{ gap: '0.5rem', marginTop: '0.6rem' }}>
                                <TagPill
                                    type="button"
                                    onClick={handleTagToggle}
                                    $active={tagEnabled}
                                    disabled={isSubmitting}
                                    aria-pressed={tagEnabled}
                                    aria-label="Add tags"
                                >
                                    <TagIcon aria-hidden="true">{tagEnabled ? '✓' : '+'}</TagIcon>
                                    {tagEnabled ? 'Tagged' : 'Add tags'}
                                </TagPill>
                                {tagEnabled && (
                                    <TagRadioCard>
                                        <RadioGroup>
                                            {TAG_OPTIONS_ENABLED.filter(opt => opt.value).map(opt => (
                                                <RadioLabel key={opt.value}>
                                                    <RadioInput
                                                        name="content_warning"
                                                        value={opt.value}
                                                        checked={tagValue === opt.value}
                                                        onChange={() => {
                                                            setTagValue(opt.value);
                                                            setTagManuallySet(true);
                                                            if (submitError) setSubmitError('');
                                                        }}
                                                        disabled={isSubmitting}
                                                    />
                                                    <span>{opt.label}</span>
                                                </RadioLabel>
                                            ))}
                                        </RadioGroup>
                                        <HelpText>
                                            Flag posts with sensitive material so users can opt in or filter them out.
                                        </HelpText>
                                    </TagRadioCard>
                                )}
                            </Field>

                            {/* Always-mounted editor: keeps editorUpload API
                              * registered so Upload/Add buttons on the Media
                              * tile work even when Text tab is hidden. */}
                            <EditorMount $hidden={activeTab !== 'text'}>
                                <Field>
                                    <EditorShell data-mirageapp-editor>
                                        <MarkdownEditor
                                            value={contentValue}
                                            onChange={v => setContentValue(v)}
                                            maxLength={limits.maxContent}
                                            disabled={isSubmitting}
                                            uploadBlocked={attachedMedia.length >= MAX_MEDIA}
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
                                            minHeight="11rem"
                                            registerUploadHandler={setEditorUpload}
                                            editorRef={ref => { contentEditorRef.current = ref; }}
                                            belowElement={submitError && activeTab === 'text' ? <ErrorMessage role="alert">{submitError}</ErrorMessage> : null}
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
                                                    if (activeTab !== 'text') setActiveTab('media');
                                                }
                                            }}
                                            onUploadStateChange={uploading => {
                                                setIsUploading(uploading);
                                                if (!uploading) setUploadProgress(null);
                                            }}
                                            onUploadProgress={progress => setUploadProgress(progress)}
                                        />
                                    </EditorShell>
                                </Field>
                                {activeTab === 'text' && (
                                    <ContentCounterRow>
                                        <ContentCounter $warn={contentValue.length >= limits.maxContent}>
                                            ({tierLabel}) {contentValue.length}/{limits.maxContent}
                                        </ContentCounter>
                                    </ContentCounterRow>
                                )}
                            </EditorMount>

                            {activeTab === 'media' && (
                                <Field>
                                    {(() => {
                                        const activeUrl = activeMedia?.url;
                                        const activeLoading = !!(activeUrl && thumbsLoading && thumbsLoading.has(activeUrl));
                                        const showLoadingState = isUploading || activeLoading;
                                        return (
                                    <CarouselTile
                                        $dragging={globalDragging}
                                        $hasMedia={attachedMedia.length > 0}
                                        $loading={showLoadingState}
                                    >
                                        {attachedMedia.length === 0 && !isUploading && (
                                            <EmptyDropLabel>
                                                Drag and drop or upload media
                                                <EmptyUploadBtn
                                                    type="button"
                                                    tabIndex={-1}
                                                    onClick={handleUploadClick}
                                                    disabled={isSubmitting || attachedMedia.length >= MAX_MEDIA}
                                                    aria-label="Upload image or video"
                                                    title="Upload"
                                                >
                                                    <HiArrowUpTray aria-hidden="true" />
                                                </EmptyUploadBtn>
                                            </EmptyDropLabel>
                                        )}
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
                                                    <HeaderAdd
                                                        type="button"
                                                        tabIndex={-1}
                                                        onClick={handleUploadClick}
                                                        disabled={isSubmitting || isUploading || attachedMedia.length >= MAX_MEDIA}
                                                        aria-label="Add media"
                                                    >
                                                        <HiPlus aria-hidden="true" />
                                                        Add
                                                    </HeaderAdd>
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
                                    {submitError && <ErrorMessage role="alert">{submitError}</ErrorMessage>}
                                    <MediaToolbar>
                                        <MediaRow>
                                            <StickerPicker
                                                onSelect={stickerUrl => {
                                                    if (attachedMedia.length >= MAX_MEDIA) return;
                                                    addMediaItem('image', stickerUrl);
                                                }}
                                                disabled={isSubmitting || isUploading || attachedMedia.length >= MAX_MEDIA}
                                            />
                                            <GifPicker
                                                onSelect={gifUrl => {
                                                    if (attachedMedia.length >= MAX_MEDIA) return;
                                                    addMediaItem('image', gifUrl);
                                                }}
                                                disabled={isSubmitting || isUploading || attachedMedia.length >= MAX_MEDIA}
                                            />
                                        </MediaRow>
                                    </MediaToolbar>
                                </Field>
                            )}

                            {activeTab === 'link' && (
                                <Field>
                                    <InputShell>
                                        <FloatLabel htmlFor="link-url">Link URL</FloatLabel>
                                        <ShellInput
                                            id="link-url"
                                            name="link-url"
                                            type="url"
                                            value={linkUrl}
                                            placeholder="Link URL"
                                            autoComplete="off"
                                            spellCheck={false}
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
                                    {linkValidation.error && (
                                        <FieldError role="alert">{linkValidation.error}</FieldError>
                                    )}
                                    {submitError && <ErrorMessage role="alert">{submitError}</ErrorMessage>}
                                </Field>
                            )}

                            <BottomBar>
                                <span aria-hidden="true" />
                                <SubmitGroup>
                                    <DraftButton type="button" disabled={isSubmitting}>Save Draft</DraftButton>
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
            </CappedPageColumn>
            {globalDragging && <GlobalDropOverlay>Drop image or video to upload</GlobalDropOverlay>}
        </ContentGrid>
    );
}

export default CreatePostView;
