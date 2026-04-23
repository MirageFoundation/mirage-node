import React, { useEffect, useRef, useState } from "react";
import ReactDOM from "react-dom";
import styled, { keyframes } from "styled-components";
import Button from "./Button.js";

/**
 * ConfirmDialog — mirageapp Plan 06.3
 *
 * Reusable confirmation / input modal used by the post menu's
 * Block / Report actions and future destructive flows. Visual language
 * mirrors mirageapp's `OptionModal` (SettingsView): a centered `panel`
 * surface with a `border` hairline, rounded 14px corners, fade-in
 * overlay + slide-up panel animation, and compact R7 typography.
 *
 * Rules:
 *  - R1 surfaces: `panel` card on `overlay` dim.
 *  - R2 tokens only — no raw hex.
 *  - R3 dividers: single 1px `border` between header / body / footer.
 *  - R5 neutrality: neutral close hover, focus visible via `borderStrong`.
 *  - R7 typography: title 0.82rem/700, body 0.72rem, input 0.8rem.
 *
 * Behavior:
 *  - `Esc` cancels, `Enter` submits (when the input is valid).
 *  - Clicking the overlay cancels.
 *  - Autofocus the textarea (when `reason` variant is used) so the user
 *    can start typing immediately.
 *  - Portaled to `document.body` so it escapes overflow-hidden parents
 *    like the post card `PopoverRoot`.
 *
 * Props:
 *   open              - show/hide
 *   title             - modal heading text
 *   message           - optional explanatory paragraph under the title
 *   confirmLabel      - submit button label (default "Confirm")
 *   cancelLabel       - cancel button label (default "Cancel")
 *   confirmVariant    - Button variant for confirm ("danger" | "warning" | ...)
 *   onConfirm         - (reason) => Promise<void> | void
 *   onCancel          - () => void
 *   pending           - disables buttons + shows Processing label
 *   requireReason     - if true, shows an input, confirm is disabled until non-empty
 *   reasonPlaceholder - input placeholder (default "Short reason")
 *   reasonMaxLength   - input max length (default 140)
 *   reasonInitial     - initial input value (when controlling externally)
 *   confirmDisabled   - additional condition that disables the confirm button
 *                       (on top of `pending` / missing reason). Useful for
 *                       dialogs with async data loading (gift subscription
 *                       expiry lookup) or input validation.
 *   hideConfirm       - when true, the footer only renders the Cancel
 *                       button. Used by the award picker where each award
 *                       tile is its own confirm action.
 *   children          - optional custom body content rendered inside the
 *                       panel's `Body` slot. Paired with (or replacing)
 *                       the built-in reason textarea.
 */

const fadeIn = keyframes`
    from { opacity: 0; }
    to { opacity: 1; }
`;

const slideUp = keyframes`
    from { transform: translateY(8px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
`;

const Overlay = styled.div`
    position: fixed;
    inset: 0;
    z-index: 9999;
    background: ${({ theme }) => theme.colors.overlay};
    display: flex;
    align-items: center;
    justify-content: center;
    animation: ${fadeIn} 0.15s ease;
    padding: 1rem;
`;

const Panel = styled.div`
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 14px;
    width: 100%;
    /* Variants:
     *   default  — 420px (Block / simple confirm dialogs).
     *   wide     — 540px (Report + Gift dialogs; textarea + info cards
     *              read better with more room).
     * Mobile (<600px) always snaps to full-width via the media query below. */
    max-width: ${({ $wide, $extraWide }) =>
        $extraWide ? '620px' : $wide ? '540px' : '420px'};
    max-height: 80vh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    animation: ${slideUp} 0.2s ease;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);

    @media (max-width: 600px) {
        max-width: 100%;
    }
`;

const Header = styled.div`
    padding: 0.85rem 1rem 0.65rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
`;

const Title = styled.div`
    font-size: 0.82rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
    line-height: 1.3;
`;

const Message = styled.div`
    font-size: 0.72rem;
    color: ${({ theme }) => theme.colors.subtleText};
    margin-top: 0.3rem;
    line-height: 1.45;
    word-break: break-word;
`;

const Body = styled.div`
    padding: 0.85rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
`;

const ReasonField = styled.textarea`
    width: 100%;
    min-height: 70px;
    resize: vertical;
    box-sizing: border-box;
    background: ${({ theme }) => theme.colors.surface2};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    padding: 0.55rem 0.7rem;
    color: ${({ theme }) => theme.colors.text};
    font-family: inherit;
    font-size: 0.8rem;
    line-height: 1.4;
    transition: border-color 0.12s ease;

    &::placeholder {
        color: ${({ theme }) => theme.colors.subtleText};
    }

    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }
`;

const ReasonMeta = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 0.6rem;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const ReasonError = styled.span`
    color: ${({ theme }) => theme.colors.voteDown};
`;

const Footer = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.5rem;
    padding: 0.65rem 1rem 0.85rem;
    border-top: 1px solid ${({ theme }) => theme.colors.border};
`;

export default function ConfirmDialog({
    open,
    title,
    message,
    confirmLabel = "Confirm",
    cancelLabel = "Cancel",
    confirmVariant = "danger",
    onConfirm,
    onCancel,
    pending = false,
    requireReason = false,
    reasonPlaceholder = "Short reason",
    reasonMaxLength = 140,
    reasonInitial = "",
    wide = false,
    extraWide = false,
    confirmDisabled = false,
    hideConfirm = false,
    children,
}) {
    const [reason, setReason] = useState(reasonInitial || "");
    const [touched, setTouched] = useState(false);
    const inputRef = useRef(null);
    // Track whether the current pointer press started on the overlay (vs.
    // inside the panel). Fixes the bug where dragging text selection in the
    // textarea could release the pointer over the overlay and close the
    // dialog. We only close if BOTH mousedown and mouseup target the overlay.
    const overlayPressRef = useRef(false);

    useEffect(() => {
        if (open) {
            setReason(reasonInitial || "");
            setTouched(false);
        }
    }, [open, reasonInitial]);

    useEffect(() => {
        if (!open) return undefined;
        const onKey = e => {
            if (e.key === "Escape") {
                e.preventDefault();
                if (!pending && typeof onCancel === "function") onCancel();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [open, pending, onCancel]);

    useEffect(() => {
        if (open && requireReason && inputRef.current) {
            // Defer focus so the slide-up animation doesn't fight the focus ring.
            const t = setTimeout(() => {
                try { inputRef.current.focus(); } catch (_) { /* noop */ }
            }, 50);
            return () => clearTimeout(t);
        }
        return undefined;
    }, [open, requireReason]);

    if (!open) return null;

    const trimmed = String(reason || "").trim();
    const reasonMissing = requireReason && trimmed.length === 0;
    const effectiveConfirmDisabled = pending || reasonMissing || confirmDisabled;

    const handleConfirm = () => {
        if (requireReason && reasonMissing) {
            setTouched(true);
            return;
        }
        if (typeof onConfirm === "function") onConfirm(trimmed);
    };

    const overlayProps = {
        onMouseDown: e => {
            // Mark the press origin. Only a press that BOTH started and
            // ended on the overlay should dismiss the dialog.
            overlayPressRef.current = e.target === e.currentTarget;
        },
        onMouseUp: e => {
            const startedOnOverlay = overlayPressRef.current;
            overlayPressRef.current = false;
            if (!startedOnOverlay) return;
            if (e.target !== e.currentTarget) return;
            if (pending) return;
            if (typeof onCancel === "function") onCancel();
        },
    };

    const dialog = (
        <Overlay role="dialog" aria-modal="true" {...overlayProps}>
            <Panel
                $wide={wide}
                $extraWide={extraWide}
                onMouseDown={e => {
                    // Any press inside the panel must not be treated as an
                    // overlay press (even if it bubbles up here for some
                    // reason — stopPropagation is belt-and-suspenders).
                    overlayPressRef.current = false;
                    e.stopPropagation();
                }}
                onMouseUp={e => e.stopPropagation()}
                onClick={e => e.stopPropagation()}
            >
                <Header>
                    <Title>{title}</Title>
                    {message && <Message>{message}</Message>}
                </Header>
                {(requireReason || children) && (
                    <Body>
                        {children}
                        {requireReason && (
                            <>
                                <ReasonField
                                    ref={inputRef}
                                    value={reason}
                                    onChange={e => setReason(e.target.value.slice(0, reasonMaxLength))}
                                    onBlur={() => setTouched(true)}
                                    placeholder={reasonPlaceholder}
                                    maxLength={reasonMaxLength}
                                    disabled={pending}
                                />
                                <ReasonMeta>
                                    <span>
                                        {touched && reasonMissing
                                            ? <ReasonError>Reason is required.</ReasonError>
                                            : "Keep it short and specific."}
                                    </span>
                                    <span>{trimmed.length}/{reasonMaxLength}</span>
                                </ReasonMeta>
                            </>
                        )}
                    </Body>
                )}
                <Footer>
                    <Button variant="ghost" size="sm" onClick={onCancel} disabled={pending}>
                        {cancelLabel}
                    </Button>
                    {!hideConfirm && (
                        <Button
                            variant={confirmVariant}
                            size="sm"
                            onClick={handleConfirm}
                            disabled={effectiveConfirmDisabled}
                            loading={pending}
                        >
                            {pending ? "Processing" : confirmLabel}
                        </Button>
                    )}
                </Footer>
            </Panel>
        </Overlay>
    );

    if (typeof document === "undefined" || !document.body) return dialog;
    return ReactDOM.createPortal(dialog, document.body);
}
