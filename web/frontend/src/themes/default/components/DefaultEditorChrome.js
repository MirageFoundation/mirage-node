import styled from "styled-components";
import { LuImageUp, LuImagePlus } from "react-icons/lu";
import StickerPicker from "./StickerPicker.js";
import GifPicker from "./GifPicker.js";

/* Shared "default theme editor chrome" — wraps MarkdownEditor and applies
 * the toolbar/icon/preview-toggle styling that both the post composer
 * (CreatePostView -> EditorShell) and the comments reply editor
 * (ViewPostView -> StyledReply) want to share.
 *
 * Single source of truth so the formatting icon group (B / I / link /
 * quote / code / lists / spoiler) plus the right-side media group
 * (sticker / GIF) plus the Preview toggle all read identically in
 * both contexts. Per-route container chrome (outer border, textarea
 * size, preview tile bg, etc.) stays in the route's own wrapper since
 * those legitimately differ.
 *
 * Selectors are unscoped because this styled component IS the wrapper —
 * styled-components nests rules inside the element automatically, so
 * styles can't leak to sibling content in the parent (e.g. the reply
 * editor's MediaRow above the textarea is unaffected). */
const DefaultEditorChrome = styled.div.attrs({ 'data-default-editor': '' })`
    position: relative;

    /* Toolbar row centered so the right-side icon group (sticker / GIF,
     * rendered via toolbarExtra) lands on the same baseline as the
     * left-side formatting buttons. */
    > div:first-child > div:first-child {
        align-items: center !important;
    }
    /* Flatten toolbarExtra wrapper spacing to match Toolbar's own gap. */
    > div:first-child > div:first-child > div {
        display: inline-flex !important;
        align-items: center !important;
        gap: 0.25rem !important;
    }
    /* Picker triggers (StickerPicker / GifPicker) wrap their button in
     * a PickerWrapper (inline-block). Promote each toolbarExtra child
     * to a 24px flex cell so divider, sticker trigger, and GIF trigger
     * all sit on the same baseline. */
    > div:first-child > div:first-child > div > * {
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        height: 24px !important;
        line-height: 1 !important;
        vertical-align: middle !important;
    }
    > div:first-child > div {
        gap: 0.25rem !important;
    }

    /* Toolbar icon buttons — 24×24 quiet pills with a subtle hover lift.
     * Covers MarkdownEditor's built-in ToolBtns AND any direct buttons
     * passed in via toolbarExtra (PickerButton). */
    button[type='button'] {
        background: transparent !important;
        border: 1px solid transparent !important;
        border-radius: 6px !important;
        box-sizing: border-box !important;
        width: 24px !important;
        min-width: 24px !important;
        height: 24px !important;
        padding: 2px 4px !important;
        color: ${({ theme }) => theme.colors.feedCtrlText} !important;
        transition: background 0.12s ease, color 0.12s ease !important;
        box-shadow: none !important;
        vertical-align: middle !important;
    }
    button[type='button'] svg,
    button[type='button'] img,
    button[type='button'] .md-icon {
        max-width: 14px !important;
        max-height: 14px !important;
        width: 14px !important;
        height: 14px !important;
        font-size: 0.78rem !important;
    }
    /* GIF glyph is text-in-svg; bump it so "GIF" stays legible at
     * toolbar scale. Sticker (smiley) keeps the 14px clamp above. */
    button[type='button'][aria-label='GIFs'] {
        padding: 0 !important;
    }
    button[type='button'][aria-label='GIFs'] svg,
    button[type='button'][aria-label='GIFs'] svg text {
        max-width: 20px !important;
        max-height: 20px !important;
        width: 20px !important;
        height: 20px !important;
    }
    /* Bold (B) and Italic (I) render as letter glyphs inside a span,
     * so the SVG sizing rules above don't reach them. */
    button[type='button'] > span {
        font-size: 0.6rem !important;
        line-height: 1 !important;
    }
    button[type='button']:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.feedCtrlHoverBg} !important;
        color: ${({ theme }) => theme.colors.text} !important;
        border-color: transparent !important;
    }
    button[type='button'][data-active='true'] {
        background: ${({ theme }) => theme.colors.feedCtrlHoverBg} !important;
        color: ${({ theme }) => theme.colors.text} !important;
        border-color: transparent !important;
    }

    /* Preview toggle — rounded ghost pill with a small square checkbox.
     * Checked state fills rgb(68,109,228) and centers a white checkmark
     * via translate(-50%, -55%) so the rotated glyph lands visually in
     * the middle of the box regardless of size. */
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
`;

/* Thin vertical rule used inside the editor toolbar to separate the
 * formatting icon group (B, I, link, quote, code, lists, spoiler) from
 * the right-side media icon group (sticker, GIF) rendered via
 * `toolbarExtra`. Shared so the same separator appears in both the
 * post composer and the comments reply editor. */
export const ToolbarDivider = styled.span`
    display: inline-block;
    width: 1px;
    height: 18px;
    background: ${({ theme }) => theme.colors.border};
    margin: 0;
    align-self: center;
    flex-shrink: 0;
`;

/* Shared "right side" of the editor toolbar — the divider + image upload
 * + sticker + GIF group that both the post composer and the comments
 * reply editor render via MarkdownEditor's `toolbarExtra` slot. Single
 * component so the two editors are literally identical at this seam — no
 * place left for the JSX to drift apart.
 *
 * Two image actions lead the group:
 *   - `onUploadImage` routes to the editor's hidden file input, giving the
 *     same inline image as ctrl+v paste but discoverable as a click.
 *   - `onLinkImage` inserts an inline image-by-URL markdown so users can
 *     drop in a remote image link without uploading a file.
 * Drag-drop and paste-upload still flow through MarkdownEditor's handlers. */
export function EditorMediaTools({ onSelect, onUploadImage, onLinkImage, disabled = false }) {
    return (
        <>
            <ToolbarDivider />
            {onUploadImage ? (
                <button
                    type="button"
                    tabIndex={-1}
                    onClick={() => { if (!disabled) onUploadImage(); }}
                    disabled={disabled}
                    aria-label="Upload image"
                    title="Upload image"
                >
                    <LuImageUp className="md-icon" aria-hidden="true" />
                </button>
            ) : null}
            {onLinkImage ? (
                <button
                    type="button"
                    tabIndex={-1}
                    onClick={() => { if (!disabled) onLinkImage(); }}
                    disabled={disabled}
                    aria-label="Insert image by URL"
                    title="Insert image by URL"
                >
                    <LuImagePlus className="md-icon" aria-hidden="true" />
                </button>
            ) : null}
            <StickerPicker onSelect={onSelect} disabled={disabled} />
            <GifPicker onSelect={onSelect} disabled={disabled} />
        </>
    );
}

export default DefaultEditorChrome;
