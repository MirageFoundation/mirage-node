import React, { useCallback, useEffect, useRef, useState } from "react";
import styled from "styled-components";
import { useNavigate } from "react-router-dom";
import { requireAccount } from "../../../utils/openBrowsing";
import {
    HiOutlineLink,
    HiOutlineUserPlus,
    HiOutlineUserMinus,
    HiOutlineHashtag,
    HiOutlineGift,
    HiOutlineSparkles,
    HiOutlineNoSymbol,
    HiOutlineFlag,
    HiOutlineEyeSlash,
    HiOutlineClipboardDocument,
    HiOutlinePencilSquare,
    HiOutlineTrash,
    HiOutlineShieldExclamation,
} from "react-icons/hi2";

import * as tx from "../../../utils/tx";
import { follow, unfollow, isFollowing } from "../../../utils/FollowUsers";
import { subscribe, unsubscribe, isSubscribed } from "../../../utils/Subscriptions";
import Storage from "../../../utils/Storage";
import { communityLabel } from "../../../utils/community";
import ConfirmDialog from "./ConfirmDialog";
import { GiftMirageDialog, GiftSubscriptionDialog, GiveAwardDialog } from "./GiftDialogs";
import CurateMenuItems from "./CurateMenuItems";
import usePostGifts from "../../../logic/usePostGifts";
import { updateNotification } from "../../../utils/notifications";

/**
 * PostMenu — default Plan 06.3 polish round 3
 *
 * Shared menu chips used by CardView and CompactRow so every feed-row
 * layout gets the SAME dropdown options, styling, and destructive-action
 * dialogs regardless of viewMode.
 *
 * Exports:
 *   • MoreMenuChip — 3-dot ellipsis button with Copy link + Follow
 *     user/topic + Give Award + Gift Mirage + Gift Subscription.
 *     Matches the `MoreButton` menu in CardView.
 *   • BlockChip — filled circle chip with a slashed-circle icon that
 *     opens Block user / Block post / Block topic / Report post.
 *     Matches the `ActionIconChip $danger` block menu in CardView.
 *
 * Each chip owns its popover state + dialog state so callers only pass
 * `{post, state, updatePost}`. Dialogs render inline via `ConfirmDialog`.
 *
 * Visual tokens mirror CardView exactly (same `Menu`, `MenuItemBtn`,
 * `PopoverRoot` definitions ported here so default/ListFeedView doesn't
 * import CardView's internals).
 */

// ─── Shared styled components (mirrored from CardView for parity) ────────────

const PopoverRoot = styled.div`
    position: relative;
    display: inline-flex;
    align-items: center;
`;

const Menu = styled.div`
    position: absolute;
    top: calc(100% + 6px);
    ${({ $align }) => ($align === 'right' ? 'right: 0;' : 'left: 0;')}
    min-width: max-content;
    width: max-content;
    padding: 0;
    background: ${({ theme }) => theme.colors.menuBg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
    z-index: 100;
    display: flex;
    flex-direction: column;
    gap: 0;
    overflow: hidden;
`;

const MenuItemBtn = styled.button`
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.6rem;
    width: 100%;
    padding: 10px 14px;
    white-space: nowrap;
    background: ${({ theme, $active }) =>
        $active ? theme.colors.menuSelectedBg : 'transparent'};
    border: none;
    border-radius: 0;
    color: ${({ theme, $active, $danger }) => {
        if ($danger) return theme.colors.menuDangerText;
        return $active ? theme.colors.sidebarItemActiveText : theme.colors.sidebarItemText;
    }};
    font-family: inherit;
    font-size: 0.7rem;
    font-weight: 400;
    text-align: left;
    cursor: pointer;
    line-height: 1;
    transition: background 0.12s ease, color 0.12s ease;

    &:hover:not(:disabled) {
        background: ${({ theme, $active }) =>
        $active ? theme.colors.menuSelectedBg : theme.colors.menuItemHoverBg};
        color: ${({ theme, $active, $danger }) => {
        if ($danger) return theme.colors.voteDown;
        return $active ? theme.colors.sidebarItemActiveText : theme.colors.menuItemHoverText;
    }};
    }

    &:disabled {
        opacity: 0.55;
        cursor: not-allowed;
    }

    & > svg {
        width: 17px;
        height: 17px;
        flex-shrink: 0;
        color: inherit;
    }

    & > span {
        flex: 1 1 auto;
        min-width: 0;
    }
`;

const MenuHeader = styled.div`
    padding: 10px 14px;
    font-size: 0.7rem;
    font-weight: 500;
    line-height: 1;
    color: ${({ theme }) => theme.colors.menuHeaderText};
    white-space: nowrap;
`;

// 3-dot button — identical rhythm to CardView's `MoreButton`. The svg is
// set to `display: block` to prevent inline-baseline offset (without it
// the glyph sits 1–2px above the optical center of the 28px pill).
const MoreButton = styled.button`
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
    line-height: 0;
    padding: 0;
    transition: background 0.12s ease;

    &:hover { background: ${({ theme }) => theme.colors.feedCtrlHoverBg}; }

    svg {
        display: block;
        width: 16px;
        height: 16px;
        fill: currentColor;
    }
`;

// Block icon chip — identical to CardView's `ActionIconChip $danger`.
// `line-height: 0` + `display: block` on the svg forces optical centering.
const BlockIconChip = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    padding: 0;
    border-radius: 9999px;
    border: none;
    background: ${({ theme }) => theme.colors.actionIconBg};
    color: ${({ theme }) => theme.colors.voteDown};
    cursor: pointer;
    line-height: 0;
    transition: background 0.12s ease;

    &:hover { background: ${({ theme }) => theme.colors.actionIconHoverBg}; }

    svg {
        display: block;
        width: 16px;
        height: 16px;
        fill: currentColor;
    }
`;

// Inline ellipsis glyph (three dots). Same markup as CardView's EllipsisIcon.
const EllipsisIcon = (p) => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...p}>
        <circle cx="12" cy="12" r="1.5" />
        <circle cx="12" cy="5" r="1.5" />
        <circle cx="12" cy="19" r="1.5" />
    </svg>
);

// Slashed-circle block glyph. Same markup as CardView's BlockIcon.
const BlockGlyph = (p) => (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...p}>
        <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 18a8 8 0 0 1-6.3-12.9L16.9 18.3A7.96 7.96 0 0 1 12 20zm6.3-3.1L7.1 5.7A8 8 0 0 1 18.3 16.9z" fill="currentColor" />
    </svg>
);

// Shared helpers ─────────────────────────────────────────────────────────────

function usePostIdentity(post, state) {
    const viewerAddress = state?.publicKey || Storage.load('publicKey', '') || '';
    const isLoggedIn = !!viewerAddress && viewerAddress !== 'guest';
    const postId = post && post.post_id ? String(post.post_id) : '';
    const topic = post && typeof post.topic === 'string' ? post.topic : '';
    const authorAddress = (post && (post.user_id || post.author)) || '';
    const isOwnPost = isLoggedIn && post && post.user_id === viewerAddress;
    const authorLabel = (post && typeof post.username === 'string' && post.username.trim())
        ? `@${post.username.trim()}`
        : (authorAddress ? `${String(authorAddress).slice(0, 10)}…` : 'this user');
    return { viewerAddress, isLoggedIn, postId, topic, authorAddress, isOwnPost, authorLabel };
}

function useOutsidePopover(rootRef, open, onClose) {
    useEffect(() => {
        if (!open) return undefined;
        const onDown = e => {
            if (rootRef.current && !rootRef.current.contains(e.target)) onClose();
        };
        const onKey = e => { if (e.key === 'Escape') onClose(); };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
        };
    }, [open, rootRef, onClose]);
}

const stop = e => { if (e && typeof e.stopPropagation === 'function') e.stopPropagation(); };

// ─── MoreMenuChip ───────────────────────────────────────────────────────────
//
// Mirrors the `MoreButton` popover in CardView: Copy link, Follow user,
// Follow topic, Give Award, Gift Mirage, Gift Subscription. Gift / award
// flows open their modals in-place via `usePostGifts` — identical behavior
// to CardView's MoreButton — so the compact list view no longer hijacks
// the viewer into the author's profile on click.

export function MoreMenuChip({
    post,
    state,
    updatePost, // eslint-disable-line no-unused-vars
    align = 'right',
}) {
    const navigate = useNavigate();
    const rootRef = useRef(null);
    const [open, setOpen] = useState(false);
    const [copied, setCopied] = useState(false);
    const [textCopied, setTextCopied] = useState(false);
    const [followOverride, setFollowOverride] = useState(null);
    const [topicFollowOverride, setTopicFollowOverride] = useState(null);
    const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
    const [deletePending, setDeletePending] = useState(false);

    const { viewerAddress, isLoggedIn, postId, topic, authorAddress, isOwnPost } = usePostIdentity(post, state);
    const linkTarget = postId ? `/p/${postId}` : '#';

    const computedFollowingUser = (() => {
        if (!isLoggedIn || !authorAddress) return false;
        try { return isFollowing(viewerAddress, authorAddress); }
        catch (_) { return false; }
    })();
    const followingUser = followOverride !== null ? followOverride : computedFollowingUser;

    const computedFollowingTopic = (() => {
        if (!isLoggedIn || !topic) return false;
        try { return isSubscribed(viewerAddress, topic); }
        catch (_) { return false; }
    })();
    const followingTopic = topicFollowOverride !== null ? topicFollowOverride : computedFollowingTopic;

    const close = useCallback(() => setOpen(false), []);
    useOutsidePopover(rootRef, open, close);

    const handleToggle = useCallback(e => { stop(e); setOpen(v => !v); }, []);

    /**
     * Sub-plan 06.11 E — feed-row admin parity. Adds the Mark-deleted row
     * for admins viewing other users' posts.
     */
    const isAdminVisible = (() => {
        if (!isLoggedIn || isOwnPost || !postId || !authorAddress) return false;
        try { return Number(Storage.load('user_level', '0')) >= 100; }
        catch (_) { return false; }
    })();

    const handleCopyLink = useCallback(e => {
        stop(e); setOpen(false);
        try {
            const url = `${window.location.origin}${linkTarget}`;
            navigator.clipboard.writeText(url);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch (_) { /* noop */ }
    }, [linkTarget]);

    const handleCopyText = useCallback(e => {
        stop(e); setOpen(false);
        const parts = [];
        const titleStr = post && post.title;
        const contentStr = post && post.content;
        if (typeof titleStr === 'string' && titleStr.trim()) parts.push(titleStr.trim());
        if (typeof contentStr === 'string' && contentStr.trim()) parts.push(contentStr.trim());
        const text = parts.join('\n\n');
        if (!text) return;
        try {
            if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text);
                setTextCopied(true);
                setTimeout(() => setTextCopied(false), 2000);
            }
        } catch (_) { /* noop */ }
    }, [post]);

    const handleEdit = useCallback(e => {
        stop(e); setOpen(false);
        if (!postId) return;
        navigate(`/create_post?post_id=${postId}&edit=true`);
    }, [navigate, postId]);

    const handleDelete = useCallback(e => {
        stop(e); setOpen(false);
        setDeletePending(false);
        setDeleteDialogOpen(true);
    }, []);

    const confirmDeletePost = useCallback(async () => {
        if (!postId) { setDeleteDialogOpen(false); return; }
        setDeletePending(true);
        try { await tx.deletePost(postId); } catch (_) { /* noop */ }
        if (typeof updatePost === 'function') {
            try { updatePost(postId, { deleted: true }); } catch (_) { /* noop */ }
        }
        setDeleteDialogOpen(false);
        setDeletePending(false);
    }, [postId, updatePost]);

    const cancelDeletePost = useCallback(() => {
        setDeleteDialogOpen(false);
        setDeletePending(false);
    }, []);

    const handleFollowUser = useCallback(async e => {
        stop(e); setOpen(false);
        if (!authorAddress) return;
        if (!requireAccount('follow users')) return;
        const next = !followingUser;
        setFollowOverride(next);
        try {
            if (next) await follow(viewerAddress, authorAddress);
            else await unfollow(viewerAddress, authorAddress);
        } catch (_) { setFollowOverride(!next); }
    }, [authorAddress, followingUser, viewerAddress]);

    const handleFollowTopic = useCallback(async e => {
        stop(e); setOpen(false);
        if (!topic) return;
        if (!requireAccount('follow communities')) return;
        const next = !followingTopic;
        setTopicFollowOverride(next);
        try {
            if (next) await subscribe(viewerAddress, topic);
            else await unsubscribe(viewerAddress, topic);
        } catch (_) { setTopicFollowOverride(!next); }
    }, [topic, followingTopic, viewerAddress]);

    /* Gift Mirage / Gift Subscription / Give Award — open in-place via
     * `usePostGifts` so the viewer stays on the current feed (previously
     * we navigated to `/u/<handle>?action=<kind>`, which was jarring
     * mid-scroll). Matches the CardView behavior so both list and card
     * modes feel identical. */
    const gifts = usePostGifts({ post, updatePost });
    const {
        handleGiveAward: giftGiveAwardOpen,
        handleGiftMirage: giftMirageOpen,
        handleGiftSubscription: giftSubOpen,
        confirmDonate,
        donateAmountRaw,
        donatePending,
        donateMessage,
        confirmGiftSub,
        giftSubPending,
        giftSubMessage,
        confirmAward,
        isAwarding,
        awardMessage,
        confirmDonateAction,
        confirmGiftSubAction,
        confirmAwardAction,
        cancelDonate,
        cancelGiftSub,
        cancelAward,
        handleDonateAmountChange,
        formatDonateAmount,
        viewerBalanceUmirage,
        AWARD_TYPES: awardTypes,
        getAwardCost,
        subFeeLabel,
        subFeeUmirage,
    } = gifts;
    const authorLabelShort = (post && typeof post.username === 'string' && post.username.trim())
        ? `@${post.username.trim()}`
        : (authorAddress ? `@${String(authorAddress).slice(0, 10)}…` : '@this user');

    const handleGiveAward = useCallback(e => { stop(e); setOpen(false); giftGiveAwardOpen(); }, [giftGiveAwardOpen]);
    const handleGiftMirage = useCallback(e => { stop(e); setOpen(false); giftMirageOpen(); }, [giftMirageOpen]);
    const handleGiftSubscription = useCallback(e => { stop(e); setOpen(false); giftSubOpen(); }, [giftSubOpen]);

    // Pipe gift-action status messages through the global Toast. Same
    // pattern CardView uses; keeps PostMenu itself free of banner UI.
    useEffect(() => {
        if (!donateMessage) return;
        updateNotification(donateMessage.message, 3, donateMessage.type === 'error');
    }, [donateMessage]);
    useEffect(() => {
        if (!giftSubMessage) return;
        updateNotification(giftSubMessage.message, 4, giftSubMessage.type === 'error');
    }, [giftSubMessage]);
    useEffect(() => {
        if (!awardMessage) return;
        updateNotification(awardMessage.message, 3, awardMessage.type === 'error');
    }, [awardMessage]);

    if (!post || !postId) return null;

    return (
        <>
            <PopoverRoot ref={rootRef} onClick={stop} data-no-card-click>
                <MoreButton
                    type="button"
                    aria-label="Post menu"
                    aria-haspopup="menu"
                    aria-expanded={open}
                    onClick={handleToggle}
                >
                    <EllipsisIcon />
                </MoreButton>
                {open && (
                    <Menu role="menu" aria-label="Post menu" $align={align}>
                        <MenuItemBtn type="button" onClick={handleCopyLink}>
                            <HiOutlineLink />
                            <span>{copied ? 'Copied!' : 'Copy link'}</span>
                        </MenuItemBtn>
                        <MenuItemBtn type="button" onClick={handleCopyText}>
                            <HiOutlineClipboardDocument />
                            <span>{textCopied ? 'Copied!' : 'Copy text'}</span>
                        </MenuItemBtn>
                        {isLoggedIn && isOwnPost && (
                            <>
                                <MenuItemBtn type="button" onClick={handleEdit}>
                                    <HiOutlinePencilSquare />
                                    <span>Edit post</span>
                                </MenuItemBtn>
                                <MenuItemBtn type="button" $danger onClick={handleDelete}>
                                    <HiOutlineTrash />
                                    <span>Delete post</span>
                                </MenuItemBtn>
                            </>
                        )}
                        {isLoggedIn && !isOwnPost && (
                            <>
                                <MenuItemBtn type="button" onClick={handleFollowUser}>
                                    {followingUser ? <HiOutlineUserMinus /> : <HiOutlineUserPlus />}
                                    <span>{followingUser ? 'Unfollow user' : 'Follow user'}</span>
                                </MenuItemBtn>
                                <MenuItemBtn type="button" onClick={handleFollowTopic}>
                                    <HiOutlineHashtag />
                                    <span>{followingTopic ? 'Unfollow community' : 'Follow community'}</span>
                                </MenuItemBtn>
                                <MenuItemBtn type="button" onClick={handleGiveAward}>
                                    <HiOutlineSparkles />
                                    <span>Give Award</span>
                                </MenuItemBtn>
                                <MenuItemBtn type="button" onClick={handleGiftMirage}>
                                    <HiOutlineGift />
                                    <span>Gift Mirage</span>
                                </MenuItemBtn>
                                <MenuItemBtn type="button" onClick={handleGiftSubscription}>
                                    <HiOutlineGift />
                                    <span>Gift Subscription</span>
                                </MenuItemBtn>
                            </>
                        )}
                        {isAdminVisible && (
                            <MenuItemBtn type="button" $danger onClick={handleDelete}>
                                <HiOutlineShieldExclamation />
                                <span>Mark post deleted</span>
                            </MenuItemBtn>
                        )}
                        {isLoggedIn && (
                            <CurateMenuItems
                                post={post}
                                onDone={close}
                                renderHeader={(label) => <MenuHeader>{label}</MenuHeader>}
                                renderItem={(item) => (
                                    <MenuItemBtn
                                        key={item.key}
                                        type="button"
                                        $danger={item.danger}
                                        disabled={item.disabled}
                                        onClick={item.onClick}
                                    >
                                        {item.icon}
                                        <span>{item.label}</span>
                                    </MenuItemBtn>
                                )}
                            />
                        )}
                    </Menu>
                )}
            </PopoverRoot>
            <ConfirmDialog
                open={deleteDialogOpen}
                title={isOwnPost ? 'Delete this post?' : 'Mark post as deleted?'}
                message={isOwnPost
                    ? "This will mark the post as deleted on-chain. You can't undo this action."
                    : 'This will permanently remove this post from every feed. This action cannot be undone.'}
                confirmLabel="Delete post"
                confirmVariant="danger"
                pending={deletePending}
                onConfirm={confirmDeletePost}
                onCancel={cancelDeletePost}
            />
            <GiftMirageDialog
                open={!!confirmDonate}
                recipientLabel={confirmDonate?.username ? `@${confirmDonate.username}` : authorLabelShort}
                amountRaw={donateAmountRaw}
                formatAmount={formatDonateAmount}
                onAmountChange={handleDonateAmountChange}
                pending={donatePending}
                userBalanceUmirage={viewerBalanceUmirage}
                onConfirm={confirmDonateAction}
                onCancel={cancelDonate}
            />
            <GiftSubscriptionDialog
                open={!!confirmGiftSub}
                recipientLabel={confirmGiftSub?.username ? `@${confirmGiftSub.username}` : authorLabelShort}
                level={confirmGiftSub?.level}
                feeLabel={subFeeLabel}
                feeUmirage={subFeeUmirage}
                loading={!!confirmGiftSub?.loading}
                expiryLabel={confirmGiftSub?.expiryLabel}
                error={confirmGiftSub?.error}
                pending={giftSubPending}
                userBalanceUmirage={viewerBalanceUmirage}
                onConfirm={confirmGiftSubAction}
                onCancel={cancelGiftSub}
            />
            <GiveAwardDialog
                open={!!confirmAward}
                awardTypes={awardTypes}
                getAwardCost={getAwardCost}
                userBalanceUmirage={viewerBalanceUmirage}
                isAwarding={isAwarding}
                onPick={(awardName) => {
                    if (confirmAward?.postId) {
                        confirmAwardAction(awardName);
                    }
                }}
                onCancel={cancelAward}
            />
        </>
    );
}

// ─── BlockChip ──────────────────────────────────────────────────────────────
//
// Mirrors CardView's `ActionIconChip $danger` with the slashed-circle icon
// + popover menu: Block user / Block post / Block topic / Report post.
// Each destructive action opens a `ConfirmDialog` (same as CardView).

export function BlockChip({ post, state, updatePost, align = 'right' }) {
    const rootRef = useRef(null);
    const [open, setOpen] = useState(false);
    const [activeDialog, setActiveDialog] = useState(null); // 'block_user' | 'block_post' | 'block_topic' | 'report'
    const [pending, setPending] = useState(false);

    const { isLoggedIn, postId, topic, authorAddress, isOwnPost, authorLabel } = usePostIdentity(post, state);

    const close = useCallback(() => setOpen(false), []);
    useOutsidePopover(rootRef, open, close);

    const handleToggle = useCallback(e => { stop(e); setOpen(v => !v); }, []);

    const openDialog = useCallback((e, mode) => {
        stop(e);
        setOpen(false);
        setPending(false);
        setActiveDialog(mode);
    }, []);

    const closeDialog = useCallback(() => {
        setActiveDialog(null);
        setPending(false);
    }, []);

    const confirmBlockUser = useCallback(async () => {
        if (!authorAddress) { closeDialog(); return; }
        setPending(true);
        try { await tx.blockUser(authorAddress, true); } catch (_) { /* noop */ }
        if (typeof updatePost === 'function' && postId) {
            try { updatePost(postId, { blocked: true }); } catch (_) { /* noop */ }
        }
        closeDialog();
    }, [authorAddress, postId, updatePost, closeDialog]);

    const confirmBlockPost = useCallback(async () => {
        if (!postId) { closeDialog(); return; }
        setPending(true);
        try { await tx.blockPost(postId, true); } catch (_) { /* noop */ }
        if (typeof updatePost === 'function') {
            try { updatePost(postId, { hidden_client: true }); } catch (_) { /* noop */ }
        }
        closeDialog();
    }, [postId, updatePost, closeDialog]);

    const confirmBlockTopic = useCallback(async () => {
        if (!topic) { closeDialog(); return; }
        setPending(true);
        try { await tx.blockTopic(topic); } catch (_) { /* noop */ }
        closeDialog();
    }, [topic, closeDialog]);

    const confirmReport = useCallback(async (reason) => {
        const trimmed = String(reason || '').trim();
        if (!trimmed || !postId) { closeDialog(); return; }
        setPending(true);
        try { await tx.reportPost(postId, trimmed); } catch (_) { /* noop */ }
        closeDialog();
    }, [postId, closeDialog]);

    if (!post || !postId) return null;
    // Matches CardView: the block chip only shows for logged-in viewers on
    // other users' posts.
    if (!isLoggedIn || isOwnPost) return null;

    return (
        <>
            <PopoverRoot ref={rootRef} onClick={stop} data-no-card-click>
                <BlockIconChip
                    type="button"
                    aria-haspopup="menu"
                    aria-expanded={open}
                    aria-label="Block or report"
                    title="Block or report"
                    onClick={handleToggle}
                >
                    <BlockGlyph />
                </BlockIconChip>
                {open && (
                    <Menu role="menu" aria-label="Block and report" $align={align}>
                        <MenuItemBtn type="button" $danger onClick={(e) => openDialog(e, 'block_user')}>
                            <HiOutlineNoSymbol />
                            <span>Block user</span>
                        </MenuItemBtn>
                        <MenuItemBtn type="button" $danger onClick={(e) => openDialog(e, 'block_post')}>
                            <HiOutlineEyeSlash />
                            <span>Block post</span>
                        </MenuItemBtn>
                        <MenuItemBtn type="button" $danger onClick={(e) => openDialog(e, 'block_topic')}>
                            <HiOutlineNoSymbol />
                            <span>Block community</span>
                        </MenuItemBtn>
                        <MenuItemBtn type="button" $danger onClick={(e) => openDialog(e, 'report')}>
                            <HiOutlineFlag />
                            <span>Report post</span>
                        </MenuItemBtn>
                    </Menu>
                )}
            </PopoverRoot>
            <ConfirmDialog
                open={activeDialog === 'block_user'}
                title={`Block ${authorLabel}?`}
                message="Posts and replies from this user will be hidden from your feeds, comments, and inbox. You can unblock them later from Settings → Blocks or their profile."
                confirmLabel="Block user"
                confirmVariant="danger"
                pending={pending}
                onConfirm={confirmBlockUser}
                onCancel={closeDialog}
            />
            <ConfirmDialog
                open={activeDialog === 'block_post'}
                title="Block this post?"
                message="This post will be hidden from every feed you see. The author won't be notified."
                confirmLabel="Block post"
                confirmVariant="danger"
                pending={pending}
                onConfirm={confirmBlockPost}
                onCancel={closeDialog}
            />
            <ConfirmDialog
                open={activeDialog === 'block_topic'}
                title={`Block ${communityLabel(topic || 'community')}?`}
                message="Posts in this community will stop appearing in your Home and discovery feeds."
                confirmLabel="Block community"
                confirmVariant="danger"
                pending={pending}
                onConfirm={confirmBlockTopic}
                onCancel={closeDialog}
            />
            <ConfirmDialog
                open={activeDialog === 'report'}
                title="🚨 Report illegal content only"
                message="Moderators only act on illegal content (CSAM, credible violent threats, doxxing, etc). Reports about the wrong community, untagged adult content, low quality, or anything you just don't like will be dismissed. Hide those from your feed with blocks and community filters."
                confirmLabel="Report"
                confirmVariant="warning"
                pending={pending}
                requireReason
                reasonPlaceholder="Describe the illegality (e.g. CSAM, credible threat, doxxing)"
                reasonMaxLength={200}
                wide
                onConfirm={confirmReport}
                onCancel={closeDialog}
            />
        </>
    );
}
