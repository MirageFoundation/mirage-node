import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom";
import styled from "styled-components";
import {
    HiChevronDown,
    HiCheck,
    HiOutlineShieldExclamation,
} from "react-icons/hi2";

import Api from "../../../utils/api";
import Storage from "../../../utils/Storage";
import * as tx from "../../../utils/tx";
import { updateNotification } from "../../../utils/notifications";
import ConfirmDialog from "./ConfirmDialog";

/**
 * AdminQuestActions — sub-plan 06.11 E (feed-row admin parity).
 *
 * Shared admin actions used by feed-row menus (`CardView.js` and the
 * `MoreMenuChip` in `PostMenu.js`) so every feed surface offers the same
 * Mark-deleted / Suspend-from-quests / Unsuspend-from-quests trio that
 * the post-detail view already exposes.
 *
 * Visual + behavior parity with sub-plan 06.11 D1:
 *   - Suspend dialog uses the canonical `ConfirmDialog` shell with the
 *     `SuspendDurationDropdown` (search-dropdown styling, R6 chevron,
 *     check-on-the-right rows, `voteUp` selected text).
 *   - Unsuspend dialog uses the same `ConfirmDialog` shell.
 *   - Mark-deleted reuses the existing `tx.deletePost` flow with a
 *     `ConfirmDialog` (matches the Delete dialog wording in
 *     `ViewPostView`).
 *   - Success toasts go through the global default `Toast`.
 *
 * No raw hex / emoji. R5 inputs, R6 chevron, R7 typography.
 */

// ─── SuspendDurationDropdown — shared with ViewPostView D1 visuals ──────────

const SuspendField = styled.label`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    width: 100%;
`;
const SuspendFieldLabel = styled.span`
    font-size: 0.62rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: ${({ theme }) => theme.colors.subtleText};
`;
const SuspendTrigger = styled.button.attrs({ type: "button" })`
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    background-color: ${({ theme }) => theme.colors.surface2};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    padding: 0.55rem 0.75rem;
    color: ${({ theme }) => theme.colors.text};
    font-family: inherit;
    font-size: 0.8rem;
    font-weight: 500;
    line-height: 1.3;
    cursor: pointer;
    transition: border-color 0.2s ease;

    &:hover:not(:disabled) {
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }
    &:focus {
        outline: none;
        border-color: ${({ theme }) => theme.colors.borderStrong};
        box-shadow: none;
    }
    &:disabled { cursor: not-allowed; opacity: 0.55; }

    & > svg {
        flex-shrink: 0;
        width: 14px;
        height: 14px;
        color: ${({ theme }) => theme.colors.subtleText};
        transition: transform 0.15s ease;
    }
    &[data-open="true"] > svg {
        transform: rotate(180deg);
    }
`;
const SuspendMenuPanel = styled.div`
    position: fixed;
    min-width: max-content;
    max-height: min(60vh, 320px);
    overflow-y: auto;
    background: ${({ theme }) => theme.colors.menuBg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 12px;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.28);
    z-index: 100000;
    display: flex;
    flex-direction: column;
    padding: 0.25rem 0;

    scrollbar-width: thin;
    scrollbar-color: ${({ theme }) => theme.colors.scrollbar} transparent;

    &::-webkit-scrollbar { width: 8px; }
    &::-webkit-scrollbar-thumb {
        background: ${({ theme }) => theme.colors.scrollbar};
        border-radius: 4px;
    }
`;
const SuspendMenuItem = styled.button.attrs({ type: "button" })`
    display: flex;
    align-items: center;
    gap: 0.6rem;
    width: 100%;
    padding: 0.5rem 0.9rem;
    white-space: nowrap;
    background: transparent;
    border: none;
    color: ${({ theme }) => theme.colors.sidebarItemText};
    font-family: inherit;
    font-size: 0.66rem;
    font-weight: 500;
    text-align: left;
    cursor: pointer;
    line-height: 1.2;
    transition: background 0.15s ease, color 0.15s ease;

    & > span:first-child {
        flex: 1;
        min-width: 0;
    }

    &[data-selected="true"] {
        color: ${({ theme }) => theme.colors.voteUp};
        font-weight: 600;
    }

    &:hover {
        background: ${({ theme }) => theme.colors.menuSelectedBg};
        color: ${({ theme }) => theme.colors.menuItemHoverText};
    }

    &[data-selected="true"]:hover {
        color: ${({ theme }) => theme.colors.voteUp};
    }
`;
const SuspendMenuItemIcon = styled.span`
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    color: ${({ theme }) => theme.colors.subtleText};

    svg {
        width: 15px;
        height: 15px;
        stroke-width: 2.4;
        opacity: ${({ $visible }) => ($visible ? 1 : 0)};
    }

    ${SuspendMenuItem}:hover & {
        color: ${({ theme }) => theme.colors.menuItemHoverText};
    }
    ${SuspendMenuItem}[data-selected="true"] & {
        color: ${({ theme }) => theme.colors.voteUp};
    }
`;

const SUSPEND_DURATION_OPTIONS = [
    { value: 1, label: "1 day" },
    { value: 3, label: "3 days" },
    { value: 7, label: "7 days" },
    { value: 30, label: "30 days" },
    { value: 0, label: "Permanent" },
];

function SuspendDurationDropdown({ value, onChange, disabled }) {
    const [open, setOpen] = useState(false);
    const [position, setPosition] = useState({ top: 0, left: 0, width: 0 });
    const triggerRef = useRef(null);
    const panelRef = useRef(null);

    const selected = SUSPEND_DURATION_OPTIONS.find(o => o.value === value)
        || SUSPEND_DURATION_OPTIONS[2];

    useEffect(() => {
        if (!open) return undefined;
        const updatePosition = () => {
            const btn = triggerRef.current;
            if (!btn) return;
            const rect = btn.getBoundingClientRect();
            setPosition({
                top: rect.bottom + 4,
                left: rect.left,
                width: rect.width,
            });
        };
        updatePosition();
        const onClickOutside = (e) => {
            const panel = panelRef.current;
            const btn = triggerRef.current;
            if (panel && panel.contains(e.target)) return;
            if (btn && btn.contains(e.target)) return;
            setOpen(false);
        };
        const onKey = (e) => {
            if (e.key === "Escape") setOpen(false);
        };
        window.addEventListener("resize", updatePosition);
        window.addEventListener("scroll", updatePosition, true);
        document.addEventListener("mousedown", onClickOutside);
        window.addEventListener("keydown", onKey);
        return () => {
            window.removeEventListener("resize", updatePosition);
            window.removeEventListener("scroll", updatePosition, true);
            document.removeEventListener("mousedown", onClickOutside);
            window.removeEventListener("keydown", onKey);
        };
    }, [open]);

    const panel = open && typeof document !== "undefined"
        ? ReactDOM.createPortal(
            <SuspendMenuPanel
                ref={panelRef}
                style={{
                    top: position.top,
                    left: position.left,
                    width: position.width,
                }}
                role="listbox"
            >
                {SUSPEND_DURATION_OPTIONS.map(option => (
                    <SuspendMenuItem
                        key={option.value}
                        data-selected={option.value === value ? "true" : "false"}
                        role="option"
                        aria-selected={option.value === value}
                        onClick={() => {
                            onChange(option.value);
                            setOpen(false);
                        }}
                    >
                        <span>{option.label}</span>
                        <SuspendMenuItemIcon $visible={option.value === value}>
                            <HiCheck aria-hidden="true" />
                        </SuspendMenuItemIcon>
                    </SuspendMenuItem>
                ))}
            </SuspendMenuPanel>,
            document.body,
        )
        : null;

    return (
        <>
            <SuspendTrigger
                ref={triggerRef}
                disabled={disabled}
                data-open={open ? "true" : "false"}
                aria-haspopup="listbox"
                aria-expanded={open}
                onClick={() => setOpen(prev => !prev)}
            >
                <span>{selected.label}</span>
                <HiChevronDown aria-hidden="true" />
            </SuspendTrigger>
            {panel}
        </>
    );
}

// ─── Hook: per-post admin quest actions ─────────────────────────────────────

/**
 * Returns {
 *   isAdminVisible:   boolean,
 *   adminMenuItems:   ({ key, label, danger, icon, onClick })[],
 *   dialogs:          JSX (suspend / unsuspend / mark-deleted dialogs),
 * }
 *
 * Callers spread `adminMenuItems` into their dropdown after the existing
 * non-owner actions (Follow / Gift / Award), and render `dialogs` once
 * inside their fragment so the modals overlay the page.
 */
export function useAdminQuestActions({ post, state, updatePost, onCloseMenu }) {
    const safePost = post || null;
    const postId = safePost && safePost.post_id ? String(safePost.post_id) : "";
    const targetUserId = safePost && safePost.user_id ? String(safePost.user_id) : "";
    const targetUsername = safePost && typeof safePost.username === "string"
        ? safePost.username.trim()
        : "";

    const viewerAddress = state?.publicKey || Storage.load("publicKey", "") || "";
    const hasValidAccount = !!viewerAddress && viewerAddress !== "guest";
    const userLevel = (() => {
        try { return Number(Storage.load("user_level", "0")); }
        catch (_) { return 0; }
    })();
    const isAdmin = hasValidAccount && userLevel >= 100;

    const questsEnabled = useMemo(() => {
        try {
            const raw = localStorage.getItem("nodeConfig");
            const cfg = raw ? JSON.parse(raw) : null;
            return Boolean(cfg && cfg.quests_enabled);
        } catch (_) { return false; }
    }, []);

    const isOwnPost = hasValidAccount && safePost && safePost.user_id === viewerAddress;

    // Suspension status — fetched lazily when the menu opens for an admin
    // viewing someone else's post on a quests-enabled node.
    const [userSuspendedStatus, setUserSuspendedStatus] = useState(null);
    const fetchUserSuspensionStatus = useCallback(async (userId) => {
        if (!userId || !questsEnabled) {
            setUserSuspendedStatus(null);
            return;
        }
        try {
            const response = await Api.get(
                `/rewards/summary?owner=${encodeURIComponent(userId)}`,
            );
            setUserSuspendedStatus(response && response.suspended === true);
        } catch (_) {
            setUserSuspendedStatus(null);
        }
    }, [questsEnabled]);

    // Dialog state.
    const [suspendOpen, setSuspendOpen] = useState(false);
    const [unsuspendOpen, setUnsuspendOpen] = useState(false);
    const [deleteOpen, setDeleteOpen] = useState(false);
    const [suspendDuration, setSuspendDuration] = useState(7);
    const [isSuspending, setIsSuspending] = useState(false);
    const [isUnsuspending, setIsUnsuspending] = useState(false);
    const [isDeleting, setIsDeleting] = useState(false);

    const closeMenuSafely = useCallback(() => {
        if (typeof onCloseMenu === "function") {
            try { onCloseMenu(); } catch (_) { /* noop */ }
        }
    }, [onCloseMenu]);

    const handleMarkDeleted = useCallback(() => {
        closeMenuSafely();
        setDeleteOpen(true);
    }, [closeMenuSafely]);

    const handleSuspend = useCallback(() => {
        closeMenuSafely();
        setSuspendDuration(7);
        setSuspendOpen(true);
    }, [closeMenuSafely]);

    const handleUnsuspend = useCallback(() => {
        closeMenuSafely();
        setUnsuspendOpen(true);
    }, [closeMenuSafely]);

    const cancelSuspend = useCallback(() => {
        if (isSuspending) return;
        setSuspendOpen(false);
    }, [isSuspending]);

    const cancelUnsuspend = useCallback(() => {
        if (isUnsuspending) return;
        setUnsuspendOpen(false);
    }, [isUnsuspending]);

    const cancelDelete = useCallback(() => {
        if (isDeleting) return;
        setDeleteOpen(false);
    }, [isDeleting]);

    const confirmSuspend = useCallback(async () => {
        if (!targetUserId || !viewerAddress) {
            setSuspendOpen(false);
            return;
        }
        setIsSuspending(true);
        try {
            const response = await Api.post("/admin/rewards/suspend", {
                admin: viewerAddress,
                target: targetUserId,
                duration_days: suspendDuration,
                reason: "Attempting to game the quest system",
            });
            if (response && response.success) {
                const durationText = suspendDuration > 0
                    ? `for ${suspendDuration} day${suspendDuration > 1 ? "s" : ""}`
                    : "permanently";
                setUserSuspendedStatus(true);
                setSuspendOpen(false);
                try {
                    updateNotification(
                        `User suspended from quests ${durationText}`,
                        4,
                        false,
                    );
                } catch (_) { /* noop */ }
            } else {
                const reason = (response && (response.error || response.message))
                    || "Unknown error";
                try { updateNotification(`Failed to suspend: ${reason}`, 4, true); }
                catch (_) { /* noop */ }
                setSuspendOpen(false);
            }
        } catch (err) {
            try {
                updateNotification(
                    `Error suspending user: ${err && err.message ? err.message : "Unknown error"}`,
                    4,
                    true,
                );
            } catch (_) { /* noop */ }
            setSuspendOpen(false);
        }
        setIsSuspending(false);
        setSuspendDuration(7);
    }, [targetUserId, viewerAddress, suspendDuration]);

    const confirmUnsuspend = useCallback(async () => {
        if (!targetUserId || !viewerAddress) {
            setUnsuspendOpen(false);
            return;
        }
        setIsUnsuspending(true);
        try {
            const response = await Api.post("/admin/rewards/unsuspend", {
                admin: viewerAddress,
                target: targetUserId,
            });
            if (response && response.success) {
                setUserSuspendedStatus(false);
                setUnsuspendOpen(false);
                try { updateNotification("User unsuspended from quests", 4, false); }
                catch (_) { /* noop */ }
            } else {
                const reason = (response && (response.error || response.message))
                    || "Unknown error";
                try { updateNotification(`Failed to unsuspend: ${reason}`, 4, true); }
                catch (_) { /* noop */ }
                setUnsuspendOpen(false);
            }
        } catch (err) {
            try {
                updateNotification(
                    `Error unsuspending user: ${err && err.message ? err.message : "Unknown error"}`,
                    4,
                    true,
                );
            } catch (_) { /* noop */ }
            setUnsuspendOpen(false);
        }
        setIsUnsuspending(false);
    }, [targetUserId, viewerAddress]);

    const confirmDelete = useCallback(async () => {
        if (!postId) {
            setDeleteOpen(false);
            return;
        }
        setIsDeleting(true);
        try { await tx.deletePost(postId); } catch (_) { /* noop */ }
        if (typeof updatePost === "function") {
            try { updatePost(postId, { deleted: true }); } catch (_) { /* noop */ }
        }
        setDeleteOpen(false);
        setIsDeleting(false);
    }, [postId, updatePost]);

    // The admin section only shows for: logged-in admins viewing other
    // users' posts on a quests-enabled node. Mirrors bluemoon.
    const isAdminVisible = !!(
        isAdmin
        && safePost
        && postId
        && targetUserId
        && !isOwnPost
    );

    const adminMenuItems = useMemo(() => {
        if (!isAdminVisible) return [];
        const items = [];
        items.push({
            key: "admin-mark-deleted",
            label: "Mark post deleted",
            danger: true,
            icon: <HiOutlineShieldExclamation />,
            onClick: handleMarkDeleted,
        });
        if (questsEnabled && userSuspendedStatus !== true) {
            items.push({
                key: "admin-suspend-quests",
                label: "Suspend from quests",
                danger: true,
                icon: <HiOutlineShieldExclamation />,
                onClick: handleSuspend,
            });
        }
        if (questsEnabled && userSuspendedStatus === true) {
            items.push({
                key: "admin-unsuspend-quests",
                label: "Unsuspend from quests",
                danger: false,
                icon: <HiOutlineShieldExclamation />,
                onClick: handleUnsuspend,
            });
        }
        return items;
    }, [
        isAdminVisible,
        questsEnabled,
        userSuspendedStatus,
        handleMarkDeleted,
        handleSuspend,
        handleUnsuspend,
    ]);

    const suspendTitle = (
        <span style={{ display: "inline-flex", alignItems: "center", gap: "0.55rem" }}>
            <HiOutlineShieldExclamation
                aria-hidden="true"
                style={{ flexShrink: 0, fontSize: "1rem" }}
            />
            <span>
                Suspend {targetUsername ? `@${targetUsername}` : "this user"} from quests?
            </span>
        </span>
    );
    const unsuspendTitle = (
        <span style={{ display: "inline-flex", alignItems: "center", gap: "0.55rem" }}>
            <HiOutlineShieldExclamation
                aria-hidden="true"
                style={{ flexShrink: 0, fontSize: "1rem" }}
            />
            <span>
                Unsuspend {targetUsername ? `@${targetUsername}` : "this user"} from quests?
            </span>
        </span>
    );

    const dialogs = (
        <>
            <ConfirmDialog
                open={suspendOpen}
                title={suspendTitle}
                message="The user will be blocked from quest rewards for the selected duration."
                confirmLabel={isSuspending ? "Suspending…" : "Suspend"}
                cancelLabel="Cancel"
                confirmVariant="danger"
                pending={isSuspending}
                onConfirm={confirmSuspend}
                onCancel={cancelSuspend}
            >
                <SuspendField>
                    <SuspendFieldLabel>Duration</SuspendFieldLabel>
                    <SuspendDurationDropdown
                        value={suspendDuration}
                        onChange={(next) => setSuspendDuration(Number(next))}
                        disabled={isSuspending}
                    />
                </SuspendField>
            </ConfirmDialog>
            <ConfirmDialog
                open={unsuspendOpen}
                title={unsuspendTitle}
                message="The user will resume earning quest rewards immediately."
                confirmLabel={isUnsuspending ? "Unsuspending…" : "Unsuspend"}
                cancelLabel="Cancel"
                confirmVariant="danger"
                pending={isUnsuspending}
                onConfirm={confirmUnsuspend}
                onCancel={cancelUnsuspend}
            />
            <ConfirmDialog
                open={deleteOpen}
                title="Mark post as deleted?"
                message="This will permanently remove this post from every feed. This action cannot be undone."
                confirmLabel="Delete post"
                confirmVariant="danger"
                pending={isDeleting}
                onConfirm={confirmDelete}
                onCancel={cancelDelete}
            />
        </>
    );

    return {
        isAdminVisible,
        adminMenuItems,
        dialogs,
        // Callers fire this when their menu opens (matches bluemoon's
        // `fetchUserSuspensionStatus` wiring).
        fetchUserSuspensionStatus,
    };
}

export default useAdminQuestActions;
