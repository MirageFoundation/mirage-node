import React, { useRef, useState, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import styled from "styled-components";
import {
    LuLink,
    LuQuote,
    LuCode,
    LuList,
    LuListOrdered,
    LuEyeOff,
} from "react-icons/lu";
import { HiOutlineMagnifyingGlass } from "react-icons/hi2";
import { getUploadUrl, downscaleImage } from "../../../utils/ImageUpload";
import Api from "../../../utils/api";
import UserAvatar from "./UserAvatar.js";

// Lazy import to keep initial bundle small
async function uploadVideoLazy(file, onProgress, xhrRef) {
    const mod = await import("../../../utils/VideoUpload");
    // Prefer cancellable path if available
    if (mod.uploadVideoWithCancel) {
        return mod.uploadVideoWithCancel(file, onProgress, xhrRef);
    }
    return mod.uploadVideo(file, onProgress);
}

// Wrapper for image upload with cancellation support
async function uploadImageWithCancel(file, onProgress, xhrRef) {
    try {
        const originalFileName = file.name || '';
        let originalExtension = '';
        if (originalFileName.includes('.')) {
            const lastDot = originalFileName.lastIndexOf('.');
            if (lastDot > 0 && lastDot < originalFileName.length - 1) {
                originalExtension = originalFileName.substring(lastDot).toLowerCase();
            }
        }
        if (!originalExtension) {
            if (file.type && file.type.includes('png')) {
                originalExtension = '.png';
            } else if (file.type && file.type.includes('gif')) {
                originalExtension = '.gif';
            } else if (file.type && file.type.includes('webp')) {
                originalExtension = '.webp';
            } else {
                originalExtension = '.jpg';
            }
        }

        const downscaledFile = await downscaleImage(file);
        const { uploadURL, accountHash } = await getUploadUrl('image');

        // Create XHR manually for cancellation support
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhrRef.current = xhr;

            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable && onProgress) {
                    const progress = (e.loaded / e.total) * 100;
                    onProgress(progress);
                }
            });

            xhr.addEventListener('load', () => {
                xhrRef.current = null;
                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        const response = JSON.parse(xhr.responseText);
                        let imageUrl = null;

                        if (response.result && response.result.variants && response.result.variants.length > 0) {
                            imageUrl = response.result.variants[0];
                        } else if (response.result && response.result.id) {
                            const id = response.result.id;
                            imageUrl = `https://imagedelivery.net/${accountHash}/${id}/public`;
                        } else if (response.variants && response.variants.length > 0) {
                            imageUrl = response.variants[0];
                        } else if (response.url) {
                            imageUrl = response.url;
                        } else if (typeof response === 'string') {
                            imageUrl = response;
                        }

                        if (!imageUrl) {
                            const text = xhr.responseText;
                            const urlMatch = text.match(/https?:\/\/[^\s"']+/);
                            if (urlMatch) {
                                imageUrl = urlMatch[0];
                            }
                        }

                        if (!imageUrl) {
                            reject(new Error('Could not determine image URL from Cloudflare response'));
                            return;
                        }

                        resolve(imageUrl);
                    } catch (error) {
                        reject(new Error(`Failed to parse Cloudflare response: ${error.message}`));
                    }
                } else {
                    xhrRef.current = null;
                    let errorMsg = `Upload failed with status ${xhr.status}`;
                    try {
                        const errorResponse = JSON.parse(xhr.responseText);
                        if (errorResponse.errors && errorResponse.errors.length > 0) {
                            errorMsg = errorResponse.errors[0].message || errorMsg;
                        }
                    } catch (_) { }
                    reject(new Error(errorMsg));
                }
            });

            xhr.addEventListener('error', () => {
                xhrRef.current = null;
                reject(new Error('Network error during upload'));
            });

            xhr.addEventListener('abort', () => {
                xhrRef.current = null;
                reject(new Error('Upload aborted'));
            });

            xhr.open('POST', uploadURL);
            const formData = new FormData();
            formData.append('file', downscaledFile);
            xhr.send(formData);
        });
    } catch (error) {
        xhrRef.current = null;
        throw new Error(`Image upload failed: ${error.message}`);
    }
}

/* Toolbar icons — use Lucide (react-icons/lu) for a cleaner, modern look.
 * They're 1em by default so sizing still flows from the Toolbar's
 * `$iconFontSize` (see Toolbar styled-component). */
const LinkIcon = () => <LuLink className="md-icon" aria-hidden="true" />;
const QuoteIcon = () => <LuQuote className="md-icon" aria-hidden="true" />;
const CodeIcon = () => <LuCode className="md-icon" aria-hidden="true" />;
const UlIcon = () => <LuList className="md-icon" aria-hidden="true" />;
const OlIcon = () => <LuListOrdered className="md-icon" aria-hidden="true" />;
const SpoilerIcon = () => <LuEyeOff className="md-icon" aria-hidden="true" />;

/**
 * Measure where the caret sits inside a `<textarea>` by mirroring its
 * computed text styles into a hidden <div>, inserting the substring
 * before the caret + a marker span, and reading the marker's offset.
 *
 * Returns `{ top, left, lineHeight }` in textarea content coordinates
 * (i.e. before scroll subtraction). Used to anchor the @-mention
 * dropdown to the line being typed instead of the textarea bbox.
 */
function measureCaretInTextarea(textarea, caretIndex) {
    const style = window.getComputedStyle(textarea);
    const div = document.createElement("div");
    const props = [
        "boxSizing", "width", "height",
        "overflowX", "overflowY",
        "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
        "borderStyle",
        "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
        "fontStyle", "fontVariant", "fontWeight", "fontStretch", "fontSize",
        "fontSizeAdjust", "lineHeight", "fontFamily",
        "textAlign", "textTransform", "textIndent", "textDecoration",
        "letterSpacing", "wordSpacing", "tabSize", "MozTabSize",
        "whiteSpace", "wordBreak", "overflowWrap",
    ];
    props.forEach((p) => { div.style[p] = style[p]; });
    div.style.position = "absolute";
    div.style.visibility = "hidden";
    div.style.top = "0";
    div.style.left = "-9999px";
    div.style.whiteSpace = "pre-wrap";
    div.style.wordWrap = "break-word";

    const value = textarea.value || "";
    const before = value.substring(0, caretIndex);
    div.textContent = before;
    const span = document.createElement("span");
    // Non-empty marker so it has measurable layout.
    span.textContent = value.substring(caretIndex) || ".";
    div.appendChild(span);

    document.body.appendChild(div);
    const top = span.offsetTop;
    const left = span.offsetLeft;
    let lineHeight = parseFloat(style.lineHeight);
    if (!Number.isFinite(lineHeight)) {
        lineHeight = parseFloat(style.fontSize) * 1.2;
    }
    document.body.removeChild(div);
    return { top, left, lineHeight };
}

const EditorContainer = styled.div`
	display: flex;
	flex-direction: column;
	gap: 0.35rem;
	position: relative;
	pointer-events: auto;
`;

const Toolbar = styled.div`
	/* Optional sizing vars, set by props from parent when needed */
	${({ $btnSize }) => ($btnSize ? `--btn-size: ${$btnSize};` : "")}
	${({ $iconFontSize }) => ($iconFontSize ? `--icon-font-size: ${$iconFontSize};` : "")}
	${({ $topGap }) => ($topGap ? `margin-top: ${$topGap};` : "")}
	display: flex;
	flex-wrap: wrap;
	gap: 0.25rem;
`;

const ToolButton = styled.button`
	background-color: ${({ theme }) => theme.colors.panelAlt};
	color: ${({ theme }) => theme.colors.text};
	border: 1px solid ${({ theme }) => theme.colors.border};
	border-radius: 3px;
	/* Scale padding with button size to keep proportions reasonable */
	padding: calc((var(--btn-size, 1.75rem)) * 0.12) calc((var(--btn-size, 1.75rem)) * 0.23);
	font-size: 0.65rem; /* text labels like Image/Video remain modest */
	cursor: pointer;
	display: flex;
	align-items: center;
	justify-content: center;
	min-width: var(--btn-size, 1.75rem);
	height: var(--btn-size, 1.75rem);
	/* Make inline SVG and icon spans scale with icon font var */
	svg, .md-icon {
		font-size: var(--icon-font-size, 0.7rem);
		max-width: calc(var(--btn-size, 1.75rem) - 0.2rem);
		max-height: calc(var(--btn-size, 1.75rem) - 0.2rem);
	}
	&[data-active="true"] {
		background-color: ${({ theme }) => theme.colors.panel};
		border-color: ${({ theme }) => theme.colors.link};
		color: ${({ theme }) => theme.colors.text};
	}
	&:hover {
		background-color: ${({ theme }) => theme.colors.panel};
	}
	&:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
`;

const IconBold = styled.span`
	font-weight: 700;
	font-size: var(--icon-font-size, 0.7rem);
	line-height: 1;
`;

const IconItalic = styled.span`
	font-style: italic;
	font-size: var(--icon-font-size, 0.7rem);
	line-height: 1;
`;

// eslint-disable-next-line no-unused-vars
const IconLink = styled.span`
	font-size: var(--icon-font-size, 0.65rem);
	line-height: 1;
	display: inline-block;
	&::before {
		content: "🔗";
		font-size: var(--icon-font-size, 0.65rem);
		display: block;
	}
`;

// eslint-disable-next-line no-unused-vars
const IconBlockquote = styled.span`
	font-size: var(--icon-font-size, 0.65rem);
	line-height: 1;
	display: inline-block;
	&::before {
		content: """;
		font-size: var(--icon-font-size, 0.75rem);
		display: block;
	}
`;

// eslint-disable-next-line no-unused-vars
const IconCode = styled.span`
	font-size: var(--icon-font-size, 0.65rem);
	line-height: 1;
	font-family: monospace;
	display: inline-block;
	&::before {
		content: "<";
		display: inline;
	}
	&::after {
		content: ">";
		display: inline;
	}
`;

const ListIconWrapper = styled.span`
	font-size: var(--icon-font-size, 0.55rem);
	line-height: 1.1;
	display: inline-flex;
	flex-direction: column;
	gap: 0.1rem;
	align-items: flex-start;
`;

// eslint-disable-next-line no-unused-vars
const IconUnorderedList = styled(ListIconWrapper)`
	&::before {
		content: "•";
		display: block;
	}
	&::after {
		content: "•";
		display: block;
	}
	span {
		display: block;
	}
`;

// eslint-disable-next-line no-unused-vars
const IconOrderedList = styled(ListIconWrapper)`
	font-size: var(--icon-font-size, 0.5rem);
	&::before {
		content: "1";
		display: block;
	}
	&::after {
		content: "2";
		display: block;
	}
	span {
		display: block;
	}
`;

// eslint-disable-next-line no-unused-vars
const IconTable = styled.span`
	font-size: var(--icon-font-size, 0.65rem);
	line-height: 1;
	&::before {
		content: "⊞";
		font-size: var(--icon-font-size, 0.7rem);
	}
`;

const Area = styled.textarea`
	border: 1px solid ${({ theme }) => theme.colors.border};
	border-radius: 8px;
	margin: 0;
	background-color: ${({ theme }) => theme.colors.panelAlt};
	color: ${({ theme }) => theme.colors.text};
	padding: 0.5rem 0.75rem;
	resize: none;
	min-height: ${({ $minHeight }) => $minHeight || '4rem'};
	overflow-y: hidden;
	line-height: 1.4;
	font-size: 0.85rem;
	font-weight: 400;
	box-sizing: border-box;
	width: 100%;
	max-width: 100%;
	transition: all 0.2s ease;
	&:hover {
		border-color: ${({ theme }) => theme.colors.subtleText};
	}
	&:focus {
		outline: none;
		border-color: ${({ theme }) => theme.colors.borderStrong};
		box-shadow: none;
	}
	&:disabled {
		opacity: 0.5;
		cursor: not-allowed;
		background-color: ${({ theme }) => theme.colors.panel};
		color: ${({ theme }) => theme.colors.subtleText};
	}
`;

const HelperRow = styled.div`
	display: flex;
	align-items: center;
	gap: 0.5rem;
	margin-left: 0.1rem;
`;

const SmallText = styled.span`
	font-size: 0.4rem;
	color: #888;
	margin-top: -0.25rem;
`;

const MentionDropdown = styled.div`
	position: fixed;
	${({ $top }) => ($top != null ? `top: ${$top}px;` : "")}
	${({ $bottom }) => ($bottom != null ? `bottom: ${$bottom}px;` : "")}
	left: ${({ $left }) => $left}px;
	width: ${({ $width }) => $width}px;
	background: ${({ theme }) => theme.colors.menuBg};
	border: 1px solid ${({ theme }) => theme.colors.border};
	border-radius: 12px;
	box-shadow: 0 12px 32px rgba(0, 0, 0, 0.28);
	z-index: 1000;
	max-height: min(60vh, 320px);
	overflow-y: auto;
	scrollbar-width: thin;
	scrollbar-color: ${({ theme }) => theme.colors.scrollbar} transparent;

	&::-webkit-scrollbar {
		width: 8px;
	}
	&::-webkit-scrollbar-thumb {
		background: ${({ theme }) => theme.colors.scrollbar};
		border-radius: 4px;
	}
`;

const MentionHeader = styled.div`
	display: flex;
	align-items: center;
	gap: 0.4rem;
	padding: 0.5rem 0.75rem;
	border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const MentionHeaderLabel = styled.span`
	font-size: 0.55rem;
	font-weight: 500;
	letter-spacing: 0.05em;
	text-transform: uppercase;
	color: ${({ theme }) => theme.colors.menuHeaderText};
`;

const MentionQueryBadge = styled.span`
	display: inline-flex;
	align-items: center;
	padding: 0.1rem 0.4rem;
	border-radius: 9999px;
	background: ${({ theme }) => theme.colors.accent};
	color: ${({ theme }) => theme.colors.focusBlue};
	font-size: 0.6rem;
	font-weight: 600;
	max-width: 12rem;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
`;

const MentionItem = styled.div`
	display: flex;
	align-items: center;
	gap: 0.6rem;
	padding: 0.5rem 0.75rem;
	cursor: pointer;
	color: ${({ theme }) => theme.colors.sidebarItemText};
	background: ${({ $active, theme }) =>
        $active ? theme.colors.menuSelectedBg : "transparent"};
	transition: background 0.15s ease, color 0.15s ease;

	&:hover {
		background: ${({ theme }) => theme.colors.menuSelectedBg};
		color: ${({ theme }) => theme.colors.menuItemHoverText};
	}
`;


const MentionTextCol = styled.div`
	flex: 1;
	min-width: 0;
	display: flex;
	flex-direction: column;
	gap: 0.08rem;
	overflow: hidden;
`;

const MentionUsername = styled.span`
	font-size: 0.7rem;
	font-weight: 600;
	color: inherit;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
`;

const MentionAddress = styled.span`
	font-size: 0.6rem;
	font-weight: 500;
	color: ${({ theme }) => theme.colors.subtleText};
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
`;

const MentionHint = styled.div`
	display: flex;
	align-items: center;
	gap: 0.5rem;
	padding: 0.7rem 0.9rem;
	color: ${({ theme }) => theme.colors.subtleText};
	font-size: 0.65rem;
	font-weight: 500;

	svg {
		width: 13px;
		height: 13px;
		flex-shrink: 0;
	}
`;

const HiddenInput = styled.input`
	display: none;
`;

const LivePreviewContainer = styled.div`
	margin-top: 0.5rem;
	padding: 0.6rem 0.75rem;
	background: ${({ theme }) => theme.colors.panelAlt};
	border: 1px solid ${({ theme }) => theme.colors.border};
	border-radius: 6px;
	font-size: 0.85rem;
	color: ${({ theme }) => theme.colors.text};
	overflow-y: auto;
	opacity: ${({ $visible }) => ($visible ? 1 : 0)};
	transform: translateY(${({ $visible }) => ($visible ? "0" : "-4px")});
	transition: opacity 0.2s ease, transform 0.2s ease;
	pointer-events: ${({ $visible }) => ($visible ? "auto" : "none")};
	position: ${({ $visible }) => ($visible ? "relative" : "absolute")};
	${({ $visible }) => !$visible && "height: 0; padding: 0; margin: 0; border: none; overflow: hidden;"}
`;

const PreviewLabel = styled.div`
	font-size: 0.55rem;
	font-weight: 600;
	text-transform: uppercase;
	letter-spacing: 0.05em;
	color: ${({ theme }) => theme.colors.subtleText};
	margin-bottom: 0.35rem;
	display: flex;
	align-items: center;
	gap: 0.35rem;

	&::after {
		content: "";
		flex: 1;
		height: 1px;
		background: ${({ theme }) => theme.colors.border};
	}
`;

const PreviewToggle = styled.label`
	display: flex;
	align-items: center;
	gap: 0.4rem;
	cursor: pointer;
	font-size: 0.75rem;
	color: ${({ theme }) => theme.colors.subtleText};
	margin-left: auto;
	user-select: none;
	padding: 0.25rem 0.55rem;
	border-radius: 6px;
	border: 1px solid ${({ theme }) => theme.colors.border};
	background: ${({ theme }) => theme.colors.panelAlt};
	transition: background 0.15s ease, border-color 0.15s ease;

	&:hover {
		background: ${({ theme }) => theme.colors.panel};
		border-color: ${({ theme }) => theme.colors.subtleText};
	}

	input {
		width: 0.9rem;
		height: 0.9rem;
		margin: 0;
		cursor: pointer;
		accent-color: ${({ theme }) => theme.colors.accent};
	}

	@media (max-width: 640px) {
		width: 100%;
		justify-content: flex-start;
		margin-left: 0;
		margin-top: 0.35rem;
	}
`;

export default function MarkdownEditor({
    value,
    onChange,
    maxLength,
    disabled,
    onSubmitShortcut,
    showCounters,
    uploadInProgressText, // optional text for upload progress like "Uploading: 50%"
    registerUploadHandler, // optional: (api | null) => void; exposes selectFile(type) and uploadFile(file)
    toolbarButtonSize, // optional: CSS size for buttons, e.g., "1.5rem"
    toolbarIconSize,   // optional: CSS size for icons, e.g., "0.9rem"
    onMediaUploaded,   // optional: (type: 'image' | 'video', url: string) => void; called when media is successfully uploaded
    onUploadStateChange, // optional: (isUploading: boolean) => void; called when upload starts/stops
    onUploadProgress, // optional: (progress: number) => void; called with upload progress 0-100
    suffixLabel, // optional: string to show inline with counters (e.g., "(free tier)")
    toolbarTopGap, // optional: CSS size to add margin above toolbar (e.g., "0.35rem")
    belowElement, // optional: React node rendered directly below the textarea and above counters
    showUploadButton = false, // optional: show "Upload media" control in the toolbar
    uploadButtonLabel = "Upload media", // optional: label for the upload button
    uploadButtonDisabled = false, // optional: externally disable upload when busy
    uploadBlocked = false, // optional: when true, ALL upload paths are blocked (paste, drop, file picker)
    toolbarExtra = null, // optional: React node rendered at end of toolbar (next to upload)
    renderHelperRow = true, // optional: when false, don't render empty helper row (removes bottom gap)
    autoFocus = false, // optional: focus textarea on mount
    minHeight, // optional: CSS size for minimum height, e.g., "8rem"
    editorRef, // optional: (ref) => void; exposes { focus: () => void } to parent
}) {
    const areaRef = useRef(null);

    useEffect(() => {
        if (editorRef) {
            editorRef({
                focus: () => {
                    if (areaRef.current) areaRef.current.focus();
                }
            });
        }
        return () => {
            if (editorRef) editorRef(null);
        };
    }, [editorRef]);

    // Auto-resize textarea to fit content
    const autoResize = React.useCallback(() => {
        const ta = areaRef.current;
        if (!ta) return;
        // Save scroll position before resize to prevent page jump
        const scrollY = window.scrollY;
        // Reset height to auto to get accurate scrollHeight
        ta.style.height = 'auto';
        // Set height to scrollHeight to fit content
        ta.style.height = `${ta.scrollHeight}px`;
        // Restore scroll position
        window.scrollTo(window.scrollX, scrollY);
    }, []);

    // Auto-resize on value change
    useEffect(() => {
        autoResize();
    }, [value, autoResize]);

    useEffect(() => {
        if (autoFocus && areaRef.current) {
            requestAnimationFrame(() => {
                try { areaRef.current.focus(); } catch (_) { }
            });
        }
    }, [autoFocus]);
    const fileInputRef = useRef(null);
    const uploadXhrRef = useRef(null); // Store XHR for cancellation
    const [uploadPct, setUploadPct] = useState(null);

    // ---- @mention autocomplete state ----
    const [mentionQuery, setMentionQuery] = useState(""); // current search prefix
    const [mentionResults, setMentionResults] = useState([]); // [{username, address}]
    const [mentionIndex, setMentionIndex] = useState(0); // highlighted index
    const [mentionOpen, setMentionOpen] = useState(false); // dropdown visible
    const [mentionLoading, setMentionLoading] = useState(false);
    // Computed position for the mention dropdown (rendered via portal
    // so it escapes any `overflow: hidden` ancestor like CreatePostView's
    // EditorShell). Either `top` or `bottom` is set depending on whether
    // the dropdown opens below or above the cursor caret.
    const [mentionPos, setMentionPos] = useState({
        top: null,
        bottom: null,
        left: 0,
        width: 0,
    });
    const mentionTimerRef = useRef(null); // debounce timer
    const mentionAbortRef = useRef(null); // abort controller for in-flight request
    // Position in the text where the @ trigger started
    const mentionStartRef = useRef(-1);

    // Detect @mention trigger from cursor position and text value
    const detectMention = useCallback((text, cursorPos) => {
        if (!text || cursorPos <= 0) {
            setMentionOpen(false);
            return;
        }
        // Walk backwards from cursor to find @ trigger
        let i = cursorPos - 1;
        while (i >= 0 && /[A-Za-z0-9-]/.test(text[i])) {
            i--;
        }
        if (i < 0 || text[i] !== '@') {
            setMentionOpen(false);
            return;
        }
        // The char before @ must be a non-word char or start of string (to avoid email@user)
        if (i > 0 && /\w/.test(text[i - 1])) {
            setMentionOpen(false);
            return;
        }
        const query = text.slice(i + 1, cursorPos).toLowerCase();
        if (query.length === 0) {
            // Just typed '@' with nothing after — show dropdown but no results yet
            mentionStartRef.current = i;
            setMentionQuery("");
            setMentionResults([]);
            setMentionOpen(true);
            return;
        }
        mentionStartRef.current = i;
        setMentionQuery(query);
        setMentionOpen(true);
        setMentionIndex(0);
    }, []);

    // Debounced API call when mentionQuery changes
    useEffect(() => {
        if (!mentionOpen || !mentionQuery || mentionQuery.length < 1) {
            setMentionResults([]);
            setMentionLoading(false);
            return;
        }
        setMentionLoading(true);
        // Cancel previous timer
        if (mentionTimerRef.current) clearTimeout(mentionTimerRef.current);
        // Cancel previous in-flight request
        if (mentionAbortRef.current) {
            try { mentionAbortRef.current.abort(); } catch (_) { /* noop */ }
        }

        mentionTimerRef.current = setTimeout(async () => {
            const controller = new AbortController();
            mentionAbortRef.current = controller;
            try {
                const mentionSearchQuery = mentionQuery.startsWith("anon-") ? mentionQuery.slice(5) : mentionQuery;
                const res = await Api.get('search_username', { q: mentionSearchQuery || mentionQuery, limit: 8 }, { timeoutMs: 4000 });
                if (!controller.signal.aborted && res && Array.isArray(res.results)) {
                    setMentionResults(res.results);
                    setMentionIndex(0);
                }
            } catch (_) {
                if (!controller.signal.aborted) {
                    setMentionResults([]);
                }
            } finally {
                if (!controller.signal.aborted) {
                    setMentionLoading(false);
                }
            }
        }, 200);

        return () => {
            if (mentionTimerRef.current) clearTimeout(mentionTimerRef.current);
        };
    }, [mentionQuery, mentionOpen]);

    // Insert a selected mention into the textarea
    const insertMention = useCallback((username) => {
        const ta = areaRef.current;
        const text = value || "";
        const atPos = mentionStartRef.current;
        if (atPos < 0 || !ta) {
            setMentionOpen(false);
            return;
        }
        // Replace @partial with @username + space
        const cursorPos = ta.selectionStart ?? 0;
        const before = text.slice(0, atPos);
        const after = text.slice(cursorPos);
        const insert = `@${username} `;
        const next = before + insert + after;
        onChange(next);
        setMentionOpen(false);
        setMentionQuery("");
        setMentionResults([]);
        // Restore cursor after the inserted mention
        const newPos = atPos + insert.length;
        requestAnimationFrame(() => {
            try {
                ta.focus();
                ta.setSelectionRange(newPos, newPos);
            } catch (_) { /* noop */ }
        });
    }, [value, onChange]);

    // Close mention dropdown
    const closeMention = useCallback(() => {
        setMentionOpen(false);
        setMentionQuery("");
        setMentionResults([]);
        setMentionIndex(0);
    }, []);

    // Compute fixed-position coordinates for the mention dropdown anchored
    // to the caret line of the textarea (NOT the textarea bounding box).
    // Uses the standard "mirror div" technique: copy the textarea's
    // computed text styles to an offscreen div, insert the text up to the
    // @-trigger, and measure where a marker span lands. Anchors the
    // dropdown right above or right below that line so it visually hugs
    // what the user is typing.
    useEffect(() => {
        if (!mentionOpen) return;
        const compute = () => {
            const ta = areaRef.current;
            if (!ta) return;
            const rect = ta.getBoundingClientRect();
            const viewportH = window.innerHeight || document.documentElement.clientHeight;

            // Caret y relative to the textarea's content area.
            const atPos = mentionStartRef.current >= 0
                ? mentionStartRef.current
                : (ta.selectionStart ?? 0);
            const caret = measureCaretInTextarea(ta, atPos);

            // The caret's top in viewport coords = textarea top + caret y
            // in content - scroll. lineH gives the caret line height so
            // we can place the dropdown directly above/below the line.
            const caretTop = rect.top + caret.top - ta.scrollTop;
            const caretBottom = caretTop + caret.lineHeight;

            const GAP = 6;
            const NEEDED = 340;
            const spaceAbove = caretTop;
            const spaceBelow = viewportH - caretBottom;
            const openUpward = spaceAbove >= NEEDED || spaceAbove > spaceBelow;

            if (openUpward) {
                // Anchor the dropdown's bottom edge right above the caret line.
                setMentionPos({
                    top: null,
                    bottom: viewportH - caretTop + GAP,
                    left: rect.left,
                    width: rect.width,
                });
            } else {
                // Anchor the dropdown's top edge right below the caret line.
                setMentionPos({
                    top: caretBottom + GAP,
                    bottom: null,
                    left: rect.left,
                    width: rect.width,
                });
            }
        };
        compute();
        window.addEventListener("scroll", compute, true);
        window.addEventListener("resize", compute);
        return () => {
            window.removeEventListener("scroll", compute, true);
            window.removeEventListener("resize", compute);
        };
    }, [mentionOpen, mentionResults.length, mentionLoading, mentionQuery]);

    // Preview toggle with localStorage persistence
    const [previewEnabled, setPreviewEnabled] = useState(() => {
        try {
            const stored = localStorage.getItem('mdEditorPreview');
            if (stored === 'true') return true;
            if (stored === 'false') return false;
        } catch (_) { /* noop */ }
        return false; // default to disabled
    });

    const handlePreviewToggle = (e) => {
        const enabled = e.target.checked;
        setPreviewEnabled(enabled);
        try {
            localStorage.setItem('mdEditorPreview', enabled ? 'true' : 'false');
        } catch (_) { /* noop */ }
    };

    const applyWrap = (prefix, suffix = prefix) => {
        const ta = areaRef.current;
        if (!ta) return;
        const start = ta.selectionStart ?? 0;
        const end = ta.selectionEnd ?? 0;
        const text = value || "";
        const selected = text.slice(start, end);
        const insert = `${prefix}${selected || ""}${suffix}`;
        const next = text.slice(0, start) + insert + text.slice(end);
        onChange(next);
        const pos = start + prefix.length + (selected ? selected.length : 0);
        requestAnimationFrame(() => {
            try {
                ta.focus();
                ta.setSelectionRange(pos, pos);
            } catch (_) { }
        });
    };

    const toggleList = (ordered = false) => {
        const ta = areaRef.current;
        if (!ta) return;
        const start = ta.selectionStart ?? 0;
        const end = ta.selectionEnd ?? 0;
        const text = value || "";
        const before = text.slice(0, start);
        const selected = text.slice(start, end);
        const after = text.slice(end);
        const lines = (selected || "").split("\n");
        const isAllPrefixed = lines.every((l, i) => {
            const trimmed = l.trimStart();
            if (ordered) return /^\d+\.\s/.test(trimmed);
            return /^-\s/.test(trimmed) || /^\*\s/.test(trimmed);
        });
        const transformed = lines
            .map((l, i) => {
                if (isAllPrefixed) {
                    return l.replace(/^(\s*)(?:\d+\.\s|-\s|\*\s)/, "$1");
                }
                const indent = l.match(/^\s*/)?.[0] || "";
                if (ordered) return `${indent}${i + 1}. ${l.trimStart()}`;
                return `${indent}- ${l.trimStart()}`;
            })
            .join("\n");
        const next = before + transformed + after;
        onChange(next);
        requestAnimationFrame(() => {
            try {
                ta.focus();
                ta.setSelectionRange(before.length, before.length + transformed.length);
            } catch (_) { }
        });
    };

    const toggleQuote = () => {
        const ta = areaRef.current;
        if (!ta) return;
        const start = ta.selectionStart ?? 0;
        const end = ta.selectionEnd ?? 0;
        const text = value || "";
        const before = text.slice(0, start);
        const selected = text.slice(start, end);
        const after = text.slice(end);
        const lines = (selected || "").split("\n");
        const isAllQuoted = lines.every((l) => /^>\s?/.test(l.trimStart()));
        const transformed = lines
            .map((l) => {
                if (isAllQuoted) return l.replace(/^(\s*)>\s?/, "$1");
                const indent = l.match(/^\s*/)?.[0] || "";
                return `${indent}> ${l.trimStart()}`;
            })
            .join("\n");
        const next = before + transformed + after;
        onChange(next);
        requestAnimationFrame(() => {
            try {
                ta.focus();
                ta.setSelectionRange(before.length, before.length + transformed.length);
            } catch (_) { }
        });
    };

    const toggleCode = () => {
        const ta = areaRef.current;
        if (!ta) return;
        const start = ta.selectionStart ?? 0;
        const end = ta.selectionEnd ?? 0;
        const text = value || "";
        const selected = text.slice(start, end);
        if (!selected.includes("\n")) {
            applyWrap("`", "`");
        } else {
            const insert = "```\n" + selected + "\n```";
            const next = text.slice(0, start) + insert + text.slice(end);
            onChange(next);
            const pos = start + insert.length;
            requestAnimationFrame(() => {
                try {
                    ta.focus();
                    ta.setSelectionRange(pos, pos);
                } catch (_) { }
            });
        }
    };

    const insertLink = () => {
        const ta = areaRef.current;
        if (!ta) return;
        const start = ta.selectionStart ?? 0;
        const end = ta.selectionEnd ?? 0;
        const text = value || "";
        const selected = text.slice(start, end) || "link text";
        const insert = `[${selected}](https://)`;
        const next = text.slice(0, start) + insert + text.slice(end);
        onChange(next);
        const urlStart = start + insert.indexOf("https://");
        const urlEnd = urlStart + "https://".length;
        requestAnimationFrame(() => {
            try {
                ta.focus();
                ta.setSelectionRange(urlStart, urlEnd);
            } catch (_) { }
        });
    };

    // eslint-disable-next-line no-unused-vars
    const handleUploadClick = (type) => {
        if (uploadPct !== null) return; // Disable upload click during upload
        const input = fileInputRef.current;
        if (!input) return;
        input.value = "";
        input.accept = type === "image" ? "image/*" : "video/*";
        input.dataset.type = type;
        input.click();
    };

    const performUploadFile = async (file) => {
        if (!file) return;
        if (uploadBlocked) return;
        const isImg = file.type.startsWith("image/");
        const isVid = file.type.startsWith("video/");
        if (!isImg && !isVid) return;
        setUploadPct(0);
        // Notify parent that upload started
        if (typeof onUploadStateChange === 'function') {
            onUploadStateChange(true);
        }
        if (typeof onUploadProgress === 'function') {
            onUploadProgress(0);
        }
        try {
            let mediaUrl;
            if (isImg) {
                mediaUrl = await uploadImageWithCancel(file, (p) => {
                    setUploadPct(p);
                    if (typeof onUploadProgress === 'function') {
                        onUploadProgress(p);
                    }
                }, uploadXhrRef);
            } else {
                mediaUrl = await uploadVideoLazy(file, (p) => {
                    setUploadPct(p);
                    if (typeof onUploadProgress === 'function') {
                        onUploadProgress(p);
                    }
                }, uploadXhrRef);
            }
            // Notify parent that media was uploaded (don't modify content here)
            if (typeof onMediaUploaded === 'function') {
                onMediaUploaded(isImg ? 'image' : 'video', mediaUrl);
            }
        } catch (e) {
            // If aborted, don't notify parent of error
            if (e.message === 'Upload aborted') {
                // User cancelled, that's fine
            } else {
                // Log error for debugging
                console.error('[MarkdownEditor] Upload failed:', e);
                // Notify parent of error if callback exists
                if (typeof onMediaUploaded === 'function') {
                    // Pass error message as 3rd arg
                    try { onMediaUploaded(null, null, e.message || 'Upload failed'); } catch (_) { }
                }
            }
        } finally {
            setUploadPct(null);
            uploadXhrRef.current = null;
            // Notify parent that upload finished
            if (typeof onUploadStateChange === 'function') {
                onUploadStateChange(false);
            }
            if (typeof onUploadProgress === 'function') {
                onUploadProgress(null);
            }
        }
    };

    const cancelUpload = () => {
        if (uploadXhrRef.current) {
            uploadXhrRef.current.abort();
            uploadXhrRef.current = null;
        }
    };

    const handleFileChange = async (e) => {
        if (uploadPct !== null) return; // Disable file change during upload
        const file = e.target?.files?.[0];
        await performUploadFile(file);
    };

    const handlePaste = async (e) => {
        try {
            if (disabled) return;
            if (uploadBlocked) return;
            if (uploadPct !== null) return; // Disable paste upload during upload
            const cd = e.clipboardData || window.clipboardData;
            if (!cd) return;
            let file = null;
            // Prefer items (Chrome/Edge/Firefox)
            if (cd.items && cd.items.length) {
                for (let i = 0; i < cd.items.length; i += 1) {
                    const it = cd.items[i];
                    if (!it) continue;
                    if (it.kind === "file") {
                        const f = it.getAsFile && it.getAsFile();
                        if (f && (f.type?.startsWith("image/") || f.type?.startsWith("video/"))) {
                            file = f;
                            break;
                        }
                    }
                }
            }
            // Fallback to files collection
            if (!file && cd.files && cd.files.length) {
                for (let i = 0; i < cd.files.length; i += 1) {
                    const f = cd.files[i];
                    if (f && (f.type?.startsWith("image/") || f.type?.startsWith("video/"))) {
                        file = f;
                        break;
                    }
                }
            }
            if (file) {
                // Prevent raw blob or data URL from being pasted into the textarea
                e.preventDefault();
                await performUploadFile(file);
            }
        } catch (_) { /* ignore paste errors */ }
    };

    const onKeyDown = (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
            e.preventDefault();
            applyWrap("**");
        } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "i") {
            e.preventDefault();
            applyWrap("*");
        } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
            e.preventDefault();
            insertLink();
        } else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
            if (onSubmitShortcut) {
                e.preventDefault();
                onSubmitShortcut();
            }
        } else if (e.key === "PageUp" || e.key === "PageDown") {
            // Custom paging since auto-resize textarea doesn't page properly
            e.preventDefault();
            const ta = areaRef.current;
            if (!ta) return;

            const style = getComputedStyle(ta);
            const lineHeight = parseFloat(style.lineHeight) || 20;
            const linesPerPage = Math.floor(window.innerHeight / lineHeight) - 2;

            const text = ta.value || '';
            const lines = text.split('\n');
            const textBeforeCursor = text.substring(0, ta.selectionStart);
            const currentLine = (textBeforeCursor.match(/\n/g) || []).length;
            const columnInLine = ta.selectionStart - textBeforeCursor.lastIndexOf('\n') - 1;

            let newLine;
            if (e.key === "PageDown") {
                newLine = Math.min(currentLine + linesPerPage, lines.length - 1);
            } else {
                newLine = Math.max(currentLine - linesPerPage, 0);
            }

            // Calculate new cursor position
            let newPos = 0;
            for (let i = 0; i < newLine; i++) {
                newPos += lines[i].length + 1;
            }
            newPos += Math.min(columnInLine, lines[newLine].length);

            ta.setSelectionRange(newPos, newPos);

            // Now scroll to cursor
            setTimeout(() => {
                const rect = ta.getBoundingClientRect();
                const paddingTop = parseFloat(style.paddingTop) || 8;
                const margin = lineHeight * 2;
                const targetY = rect.top + paddingTop + (newLine * lineHeight);

                // If near bottom, show Save button
                let scrollTarget = targetY;
                if (newLine >= lines.length - 3) {
                    scrollTarget = rect.bottom + lineHeight * 4;
                }

                if (scrollTarget < margin) {
                    window.scrollBy({ top: scrollTarget - margin, behavior: 'instant' });
                } else if (scrollTarget > window.innerHeight - margin) {
                    window.scrollBy({ top: scrollTarget - window.innerHeight + margin, behavior: 'instant' });
                }
            }, 0);
        } else if ((e.ctrlKey || e.metaKey) && (e.key === "End" || e.key === "Home" || e.key === "ArrowUp" || e.key === "ArrowDown")) {
            const key = e.key;
            // Use setTimeout to ensure browser has processed the key event
            setTimeout(() => {
                const ta = areaRef.current;
                if (!ta) return;

                const rect = ta.getBoundingClientRect();
                const style = getComputedStyle(ta);
                const lineHeight = parseFloat(style.lineHeight) || 20;
                const paddingTop = parseFloat(style.paddingTop) || 8;
                const margin = lineHeight * 2;

                let targetY;
                if (key === "End") {
                    // Scroll to bottom of textarea, plus extra space to show Save button below
                    targetY = rect.bottom + lineHeight * 4;
                } else if (key === "Home") {
                    // Scroll to top of textarea
                    targetY = rect.top + paddingTop;
                } else {
                    // For arrow keys, calculate cursor position
                    const textBeforeCursor = (ta.value || '').substring(0, ta.selectionStart);
                    const lineNumber = (textBeforeCursor.match(/\n/g) || []).length;
                    targetY = rect.top + paddingTop + (lineNumber * lineHeight);

                    // If cursor is near bottom of textarea, add extra space for Save button
                    const totalLines = ((ta.value || '').match(/\n/g) || []).length;
                    if (lineNumber >= totalLines - 2) {
                        targetY = rect.bottom + lineHeight * 4;
                    }
                }

                // Scroll if target is outside visible area
                if (targetY < margin) {
                    window.scrollBy({ top: targetY - margin, behavior: 'instant' });
                } else if (targetY > window.innerHeight - margin) {
                    window.scrollBy({ top: targetY - window.innerHeight + margin, behavior: 'instant' });
                }
            }, 0);
        }
    };


    // Expose upload actions to parent exactly once on mount to avoid render loops
    // Intentionally ignore function identity changes of registerUploadHandler and performUploadFile
    // to avoid re-registering on every render, which would cause render loops.
    React.useEffect(() => {
        if (typeof registerUploadHandler !== 'function') return;
        const api = {
            selectFile: (type) => {
                try {
                    const input = fileInputRef.current;
                    if (!input) return;
                    input.value = "";
                    if (!type) input.accept = "image/*,video/*";
                    else input.accept = type === "image" ? "image/*" : "video/*";
                    input.click();
                } catch (_) { /* noop */ }
            },
            uploadFile: (file) => performUploadFile(file),
            cancelUpload: () => cancelUpload(),
        };
        registerUploadHandler(api);
        return () => {
            try { registerUploadHandler(null); } catch (_) { /* noop */ }
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return (
        <EditorContainer>
            <Toolbar $btnSize={toolbarButtonSize} $iconFontSize={toolbarIconSize} $topGap={toolbarTopGap}>
                <ToolButton type="button" tabIndex={-1} onClick={() => applyWrap("**")} disabled={disabled} aria-label="Bold">
                    <IconBold>B</IconBold>
                </ToolButton>
                <ToolButton type="button" tabIndex={-1} onClick={() => applyWrap("*")} disabled={disabled} aria-label="Italic">
                    <IconItalic>I</IconItalic>
                </ToolButton>
                <ToolButton type="button" tabIndex={-1} onClick={insertLink} disabled={disabled} aria-label="Insert link">
                    <LinkIcon />
                </ToolButton>
                <ToolButton type="button" tabIndex={-1} onClick={toggleQuote} disabled={disabled} aria-label="Quote">
                    <QuoteIcon />
                </ToolButton>
                <ToolButton type="button" tabIndex={-1} onClick={toggleCode} disabled={disabled} aria-label="Code">
                    <CodeIcon />
                </ToolButton>
                <ToolButton type="button" tabIndex={-1} onClick={() => toggleList(false)} disabled={disabled} aria-label="Bulleted list">
                    <UlIcon />
                </ToolButton>
                <ToolButton type="button" tabIndex={-1} onClick={() => toggleList(true)} disabled={disabled} aria-label="Numbered list">
                    <OlIcon />
                </ToolButton>
                <ToolButton type="button" tabIndex={-1} onClick={() => applyWrap("||")} disabled={disabled} aria-label="Spoiler">
                    <SpoilerIcon />
                </ToolButton>
                {showUploadButton ? (
                    <ToolButton
                        type="button"
                        tabIndex={-1}
                        onClick={() => {
                            if (disabled) return;
                            if (uploadPct !== null) return;
                            if (uploadButtonDisabled) return;
                            try {
                                const input = fileInputRef.current;
                                if (!input) return;
                                input.value = "";
                                input.accept = "image/*,video/*";
                                input.click();
                            } catch (_) { /* noop */ }
                        }}
                        disabled={disabled || uploadButtonDisabled || uploadPct !== null}
                        aria-label="Upload media"
                    >
                        {uploadButtonLabel || "Upload media"}
                    </ToolButton>
                ) : null}
                {toolbarExtra ? (
                    <div style={{ display: "flex", alignItems: "center", gap: "0.25rem" }}>
                        {toolbarExtra}
                    </div>
                ) : null}
                <PreviewToggle>
                    <input
                        type="checkbox"
                        tabIndex={-1}
                        checked={previewEnabled}
                        onChange={handlePreviewToggle}
                        disabled={disabled}
                    />
                    Preview
                </PreviewToggle>
            </Toolbar>
            <div style={{ position: "relative", pointerEvents: "auto" }}>
                {mentionOpen && mentionPos.width > 0 && createPortal(
                    <MentionDropdown
                        $top={mentionPos.top}
                        $bottom={mentionPos.bottom}
                        $left={mentionPos.left}
                        $width={mentionPos.width}
                    >
                        <MentionHeader>
                            <MentionHeaderLabel>Results for</MentionHeaderLabel>
                            <MentionQueryBadge>@{mentionQuery || ""}</MentionQueryBadge>
                        </MentionHeader>
                        {!mentionQuery && (
                            <MentionHint>
                                <HiOutlineMagnifyingGlass />
                                Type a username after @
                            </MentionHint>
                        )}
                        {mentionLoading && mentionResults.length === 0 && mentionQuery.length > 0 && (
                            <MentionHint>Searching…</MentionHint>
                        )}
                        {!mentionLoading && mentionResults.length === 0 && mentionQuery.length > 0 && (
                            <MentionHint>No users found</MentionHint>
                        )}
                        {mentionResults.map((item, i) => (
                            <MentionItem
                                key={item.username}
                                $active={i === mentionIndex}
                                onMouseDown={(e) => {
                                    e.preventDefault(); // prevent textarea blur
                                    insertMention(item.username);
                                }}
                                onMouseEnter={() => setMentionIndex(i)}
                            >
                                <UserAvatar seed={item.username} size={28} />
                                <MentionTextCol>
                                    <MentionUsername>@{item.username}</MentionUsername>
                                    {item.address ? (
                                        <MentionAddress>
                                            {`${item.address.slice(0, 8)}…${item.address.slice(-4)}`}
                                        </MentionAddress>
                                    ) : null}
                                </MentionTextCol>
                            </MentionItem>
                        ))}
                    </MentionDropdown>,
                    document.body
                )}
                <Area
                    ref={areaRef}
                    value={value}
                    onChange={(e) => {
                        const next = e.target.value;
                        let applied;
                        if (typeof maxLength === "number" && next.length > maxLength) {
                            applied = next.slice(0, maxLength);
                            onChange(applied);
                        } else {
                            applied = next;
                            onChange(next);
                        }
                        // Detect @mention trigger after onChange
                        requestAnimationFrame(() => {
                            const ta = areaRef.current;
                            if (ta) detectMention(applied, ta.selectionStart);
                        });
                    }}
                    disabled={disabled}
                    maxLength={maxLength}
                    onKeyDown={(e) => {
                        // Intercept keys when mention dropdown is open
                        if (mentionOpen && mentionResults.length > 0) {
                            if (e.key === "ArrowDown") {
                                e.preventDefault();
                                setMentionIndex(prev => (prev + 1) % mentionResults.length);
                                return;
                            }
                            if (e.key === "ArrowUp") {
                                e.preventDefault();
                                setMentionIndex(prev => (prev - 1 + mentionResults.length) % mentionResults.length);
                                return;
                            }
                            if (e.key === "Enter" || e.key === "Tab") {
                                e.preventDefault();
                                insertMention(mentionResults[mentionIndex].username);
                                return;
                            }
                        }
                        if (mentionOpen && e.key === "Escape") {
                            e.preventDefault();
                            closeMention();
                            return;
                        }
                        onKeyDown(e);
                    }}
                    onPaste={handlePaste}
                    placeholder="Link or content"
                    readOnly={false}
                    $minHeight={minHeight}
                />
            </div>
            {belowElement ? belowElement : null}
            {renderHelperRow && showCounters && typeof maxLength === "number" ? (
                <HelperRow>
                    <SmallText>
                        {value?.length || 0} / {maxLength}{suffixLabel ? ` ${suffixLabel}` : ""}
                    </SmallText>
                </HelperRow>
            ) : null}
            <HiddenInput ref={fileInputRef} type="file" onChange={handleFileChange} />
            <LivePreviewContainer $visible={!!(previewEnabled && value && value.trim())}>
                <PreviewLabel>Preview</PreviewLabel>
                {/* eslint-disable-next-line global-require */}
                {previewEnabled && value && value.trim() && require("./MarkdownRenderer").default
                    ? React.createElement(require("./MarkdownRenderer").default, { text: value })
                    : null}
            </LivePreviewContainer>
        </EditorContainer>
    );
}
