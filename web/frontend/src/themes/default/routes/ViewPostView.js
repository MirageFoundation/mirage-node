import { communityLabel, communityPath } from '../../../utils/community';
import { LENS, normalizeLens } from '../../../utils/curation';
import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import ReactDOM from "react-dom";
import styled from "styled-components";
import { Helmet } from "react-helmet-async";
import Button from "../components/Button.js";
import { Link, useSearchParams } from "react-router-dom";
import LoggedOutPromptCard from "../components/LoggedOutPromptCard.js";
import VoteSection from "../components/VoteSection.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import MarkdownRenderer from "../components/MarkdownRenderer.js";
import MarkdownEditor from "../components/MarkdownEditor.js";
import InlineMedia from "../components/InlineMedia.js";
import MediaGallery from "../components/MediaGallery.js";
import DefaultEditorChrome, { EditorMediaTools } from "../components/DefaultEditorChrome.js";
import { FeedCardSkeleton, CommentSkeleton } from "../components/Skeleton.js";
import { MediaRow, MediaPreviewWrapper, MediaPreviewImage, MediaSpinner, MediaRemoveButton } from "../components/MediaAttachmentLayout.js";
import VideoPlayBadge from "../../../components/VideoPlayBadge";
import Api from "../../../utils/api";
import Storage from "../../../utils/Storage";
import { getVideoThumbnailUrl, getDownloadableMedia, mediaDownloadLabel, triggerMediaDownload } from "../../../utils/media";
import { getCachedWelcomeStats } from "../../../utils/welcomeStatsCache";
import { getAuthorColor, getAuthorTooltip } from "../../../utils/tierColors";
import { Tooltip, tooltipStyles } from "../components/Tooltip.js";
import { useViewPost, formatTimeStamp, formatElapsed } from "../../../logic/useViewPost";
import { normalizeTag } from "../../../utils/ContentTags";
import { isOptimisticallyCurationHidden } from "../../../utils/curationVisibility";
import ConfirmDialog from "../components/ConfirmDialog.js";
import { GiftMirageDialog, GiftSubscriptionDialog, GiveAwardDialog } from "../components/GiftDialogs.js";
import { useBlocks } from "../../../logic/useBlocks";
import UserAvatar from "../components/UserAvatar.js";
import ContentTagBadge, { ThreadLockMark } from "../components/ContentTagBadge";
import { BlockChip } from "../components/PostMenu";
import { PostLensPicker } from "../components/CurationLensPicker";
import CommunityMembershipButton from "../components/CommunityMembershipButton";
import {
    HiNoSymbol,
    HiOutlineLink,
    HiOutlineClipboardDocument,
    HiOutlineDocumentText,
    HiOutlinePencilSquare,
    HiOutlineTrash,
    HiOutlineUserPlus,
    HiOutlineUserMinus,
    HiOutlineSparkles,
    HiOutlineGift,
    HiOutlineHashtag,
    HiOutlineArrowDownTray,
    HiOutlineShieldExclamation,
} from "react-icons/hi2";
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
        padding: 0.65rem 0 0.7rem;
        gap: 0.4rem;
    }
`;

/**
 * Comment row — reddit + mobile-app hybrid.
 *
 * Full-bleed flat row with **continuous Reddit-style ancestor rails**.
 * Each comment renders one vertical 1px rail per ancestor depth level
 * (drawn as 1px-wide `background-image` linear-gradients, so they tile
 * seamlessly across consecutive sibling/descendant cards and form one
 * unbroken vertical line through the whole sub-thread). Indentation is
 * carried by `padding-left`, matching mobile `comment-item.tsx`.
 *
 * Level-0 (root) uses `PostCard` instead, so this component only ever
 * sees `$level >= 1`. We deliberately drop the per-comment bottom divider
 * here — the rails carry the visual rhythm and a horizontal line at every
 * comment chops the rails into disconnected stubs (which is how the old
 * styling read).
 */
/*
 * Reddit-style avatar-anchored threading.
 *
 * Geometry per non-root comment:
 *   avatarLeft   = BASE_LEFT + (level - 1) * INDENT
 *   railX        = avatarLeft - INDENT + AVATAR_SIZE / 2   // parent avatar center
 *   contentLeft  = avatarLeft + AVATAR_SIZE + CONTENT_GAP
 *
 * Thread guide rules:
 *   - Each parent draws a spine (::after) from its avatar center down to
 *     the card bottom, BUT ONLY if it actually has children.
 *   - Each child draws a J-curve (::before) from the parent's avatar
 *     center down to its own avatar left.
 *   - Non-last children also draw a full-height ancestor rail at the
 *     parent's column so the line continues through them to the next
 *     sibling. LAST children do NOT draw this rail — the line stops
 *     at their avatar (J-curve only).
 *   - The same logic applies recursively for grandparent columns.
 */
const COMMENT_BASE_LEFT_PX = 12;
const COMMENT_BASE_LEFT_PX_MOBILE = 8;
const COMMENT_INDENT_PX = 26;
const COMMENT_INDENT_PX_MOBILE = 22;
/* DiceBear identicons are a 5×5 cell grid. For pixel-crisp rendering
 * (no fractional-cell anti-aliasing) the *inner* render size — i.e.
 * chip size minus the 2× padding halo — has to be a multiple of 5.
 * `CommentAvatar` overrides the inherited ratio-based padding with
 * absolute values via `!important`: 4px on desktop (23-4-4 = 15px
 * inner) and 3px on mobile (21-3-3 = 15px inner). Both land at 15px
 * inner → 3px cells. The 15px identicon square is comfortably
 * inscribed inside the 23-diameter desktop circle (corners at 10.6
 * < radius 11.5), so the round border-radius doesn't clip its
 * corners. Don't drift these without also updating CommentAvatar's
 * hardcoded padding rules so `(size - 2*padding)` stays divisible
 * by 5. */
const COMMENT_AVATAR_SIZE_PX = 23;
const COMMENT_AVATAR_SIZE_PX_MOBILE = 21;
const COMMENT_RAIL_WIDTH_PX = 1;
const COMMENT_CURVE_RADIUS_PX = 10;
const COMMENT_CURVE_RADIUS_PX_MOBILE = 9;
const COMMENT_CONTENT_GAP_PX = 8;
const COMMENT_CONTENT_GAP_PX_MOBILE = 6;
const MIN_CONTINUE_THREAD_LEVEL = 4;
const CONTINUE_THREAD_PAD_Y_REM = 0.2;
/* Padding-top values for collapsed / expanded comment cards (and their
 * mobile counterparts), expressed in `rem` so the avatar-center math
 * below tracks the actual root font-size. The default theme bumps
 * `html { font-size }` from 20px to 22px at viewports >= 1900px (and
 * applies a 1.08 body zoom on top), so any `px`-baked center value goes
 * stale on wide displays. Keeping the padding side as `rem` and adding
 * the (px) avatar half-height lets the browser do the math at render
 * time instead. */
const COMMENT_PAD_TOP_COLLAPSED_REM = 0.45;
const COMMENT_PAD_TOP_EXPANDED_REM = 0.55;
const COMMENT_PAD_TOP_COLLAPSED_REM_MOBILE = 0.4;
const COMMENT_PAD_TOP_EXPANDED_REM_MOBILE = 0.5;

/* Effective height of the comment meta row. The 3-dot `MenuButton`
 * (28×28, rendered to the right of `MetaInfoRowLeft`) is the tallest
 * item on the row — taller than both the desktop (24) and mobile (22)
 * avatars — so with `align-items: center` the row height locks to 28
 * regardless of viewport. The avatar therefore sits centered inside
 * a 28px row rather than centered inside its own 24/22px footprint,
 * and its vertical center lives at `padding-top + 14` (NOT
 * `padding-top + avatar-size/2`). The J-curve elbow needs that exact
 * Y to land on the leftmost point of the now-circular avatar.
 * Kept in sync with `MenuButton`'s `width/height` further down. */
const COMMENT_META_ROW_HALF_PX = 14;

/* Y of the avatar's vertical CENTER inside its `CommentCard`. */
const COMMENT_AVATAR_CENTER_Y_COLLAPSED = `calc(${COMMENT_PAD_TOP_COLLAPSED_REM}rem + ${COMMENT_META_ROW_HALF_PX}px)`;
const COMMENT_AVATAR_CENTER_Y_EXPANDED = `calc(${COMMENT_PAD_TOP_EXPANDED_REM}rem + ${COMMENT_META_ROW_HALF_PX}px)`;
const COMMENT_AVATAR_CENTER_Y_COLLAPSED_MOBILE = `calc(${COMMENT_PAD_TOP_COLLAPSED_REM_MOBILE}rem + ${COMMENT_META_ROW_HALF_PX}px)`;
const COMMENT_AVATAR_CENTER_Y_EXPANDED_MOBILE = `calc(${COMMENT_PAD_TOP_EXPANDED_REM_MOBILE}rem + ${COMMENT_META_ROW_HALF_PX}px)`;

/* Y of the avatar's BOTTOM edge for each (collapsed/expanded, viewport)
 * pair. The own-spine (`&::after` on `CommentCard`) starts here rather
 * than at the avatar's center, so the thread line never bleeds through
 * transparent regions of the identicon glyph (most visible in light
 * theme where `UserAvatar`'s wrapper bg is transparent).
 * Bottom = padding-top + (row_height + avatar_size) / 2:
 * desktop = padding-top + (28 + 24) / 2 = padding-top + 26
 * mobile  = padding-top + (28 + 22) / 2 = padding-top + 25 */
const COMMENT_AVATAR_BOTTOM_Y_COLLAPSED = `calc(${COMMENT_PAD_TOP_COLLAPSED_REM}rem + ${COMMENT_META_ROW_HALF_PX + COMMENT_AVATAR_SIZE_PX / 2}px)`;
const COMMENT_AVATAR_BOTTOM_Y_EXPANDED = `calc(${COMMENT_PAD_TOP_EXPANDED_REM}rem + ${COMMENT_META_ROW_HALF_PX + COMMENT_AVATAR_SIZE_PX / 2}px)`;
const COMMENT_AVATAR_BOTTOM_Y_COLLAPSED_MOBILE = `calc(${COMMENT_PAD_TOP_COLLAPSED_REM_MOBILE}rem + ${COMMENT_META_ROW_HALF_PX + COMMENT_AVATAR_SIZE_PX_MOBILE / 2}px)`;
const COMMENT_AVATAR_BOTTOM_Y_EXPANDED_MOBILE = `calc(${COMMENT_PAD_TOP_EXPANDED_REM_MOBILE}rem + ${COMMENT_META_ROW_HALF_PX + COMMENT_AVATAR_SIZE_PX_MOBILE / 2}px)`;

function commentAvatarLeftPx(level, baseLeft, indent) {
    const lvl = Math.max(Number(level) || 0, 1);
    return baseLeft + (lvl - 1) * indent;
}

function commentContentLeftPx(level, baseLeft, indent, avatarSize, gap) {
    const lvl = Math.max(Number(level) || 0, 0);
    if (lvl === 0) return null;
    return commentAvatarLeftPx(lvl, baseLeft, indent) + avatarSize + gap;
}

function commentRailXPx(level, baseLeft, indent, avatarSize) {
    const lvl = Math.max(Number(level) || 0, 2);
    return commentAvatarLeftPx(lvl - 1, baseLeft, indent) + avatarSize / 2;
}

/* In a pre-order flat array, a comment is the last child of its parent
 * if every comment after it is either a descendant or belongs to an
 * ancestor's next sibling branch. */
function isLastChildInPreorder(array, index) {
    const level = array[index].level;
    for (let j = index + 1; j < array.length; j++) {
        if (array[j].level <= level - 1) return true;
        if (array[j].level === level) return false;
    }
    return true;
}

/* Find the parent of the comment at `index` in a pre-order array. */
function getParentIndex(array, index) {
    const level = array[index].level;
    for (let j = index - 1; j >= 0; j--) {
        if (array[j].level === level - 1) return j;
    }
    return -1;
}

/* Return the ancestor depths (1..level-1) that should draw a full-height
 * rail on this comment's card. A depth D rail continues through this
 * comment only if the ancestor at depth D+1 (in this comment's chain)
 * is NOT the last child of its parent. */
function getAncestorRailDepths(array, index) {
    const level = array[index].level;
    const depths = [];
    let currentIndex = index;
    for (let targetLevel = level; targetLevel >= 2; targetLevel--) {
        if (!isLastChildInPreorder(array, currentIndex)) {
            depths.push(targetLevel - 1);
        }
        const parentIndex = getParentIndex(array, currentIndex);
        if (parentIndex === -1) break;
        currentIndex = parentIndex;
    }
    return depths;
}

function buildAncestorRails(level, baseLeft, indent, avatarSize, color, activeDepths) {
    if (!activeDepths || activeDepths.length === 0) {
        return { image: 'none', position: '0 0', size: '0 0' };
    }
    const images = [];
    const positions = [];
    const sizes = [];
    for (const K of activeDepths) {
        const x = commentAvatarLeftPx(K, baseLeft, indent) + avatarSize / 2;
        images.push(`linear-gradient(${color}, ${color})`);
        positions.push(`${x}px 0`);
        sizes.push(`${COMMENT_RAIL_WIDTH_PX}px 100%`);
    }
    return {
        image: images.join(', '),
        position: positions.join(', '),
        size: sizes.join(', '),
    };
}

const CommentCard = styled(PostCard)`
    position: relative;
    border-bottom: none;
    border-left: none;
    box-shadow: none;
    background: transparent;
    background-color: transparent;
    background-repeat: no-repeat;
    margin-left: 0;
    gap: 0.35rem;

    /* Ancestor thread guides — only drawn at depths where this comment
     * is NOT the last child in its ancestor chain, so the line continues
     * through non-last siblings and stops at the last sibling's avatar. */
    ${({ $level, $activeDepths, theme }) => {
        const r = buildAncestorRails(
            $level,
            COMMENT_BASE_LEFT_PX,
            COMMENT_INDENT_PX,
            COMMENT_AVATAR_SIZE_PX,
            theme.colors.commentThread || theme.colors.borderSubtle || theme.colors.border,
            $activeDepths,
        );
        return `
            background-image: ${r.image};
            background-position: ${r.position};
            background-size: ${r.size};
        `;
    }}

    /* Own spine: drops from this comment's avatar BOTTOM edge to the
     * card bottom so descendants can continue the thread. Starting at
     * the avatar's bottom (instead of its center) keeps the rail from
     * bleeding through transparent regions of the identicon glyph in
     * light theme, where the avatar wrapper bg is transparent. Only
     * drawn when this comment actually has children. */
    &::after {
        content: '';
        position: absolute;
        display: ${({ $level, $hasChildren, $isCollapsed }) => (Number($level) > 0 && $hasChildren && !$isCollapsed ? 'block' : 'none')};
        top: ${({ $isCollapsed }) =>
        ($isCollapsed ? COMMENT_AVATAR_BOTTOM_Y_COLLAPSED : COMMENT_AVATAR_BOTTOM_Y_EXPANDED)};
        left: ${({ $level }) =>
        `${commentAvatarLeftPx($level, COMMENT_BASE_LEFT_PX, COMMENT_INDENT_PX) + COMMENT_AVATAR_SIZE_PX / 2}px`};
        width: ${COMMENT_RAIL_WIDTH_PX}px;
        height: calc(100% - ${({ $isCollapsed }) =>
        ($isCollapsed ? COMMENT_AVATAR_BOTTOM_Y_COLLAPSED : COMMENT_AVATAR_BOTTOM_Y_EXPANDED)});
        background: ${({ theme }) => theme.colors.commentThread || theme.colors.borderSubtle || theme.colors.border};
        pointer-events: none;
    }

    /* J-curve elbow: drops from the PARENT avatar's vertical center
     * (one column left) down to this comment's avatar vertical center,
     * then curves right and lands at this comment's avatar LEFT edge.
     * Always drawn for depth >= 2 — it is the visual hook that connects
     * this reply to its parent, regardless of whether this reply is
     * the last child. */
    &::before {
        content: '';
        position: absolute;
        display: ${({ $level }) => (Number($level) >= 2 ? 'block' : 'none')};
        top: 0;
        left: ${({ $level }) =>
        `${commentRailXPx($level, COMMENT_BASE_LEFT_PX, COMMENT_INDENT_PX, COMMENT_AVATAR_SIZE_PX)}px`};
        width: ${COMMENT_INDENT_PX - COMMENT_AVATAR_SIZE_PX / 2}px;
        height: ${({ $isCollapsed }) =>
        ($isCollapsed ? COMMENT_AVATAR_CENTER_Y_COLLAPSED : COMMENT_AVATAR_CENTER_Y_EXPANDED)};
        border-left: ${COMMENT_RAIL_WIDTH_PX}px solid ${({ theme }) => theme.colors.commentThread || theme.colors.borderSubtle || theme.colors.border};
        border-bottom: ${COMMENT_RAIL_WIDTH_PX}px solid ${({ theme }) => theme.colors.commentThread || theme.colors.borderSubtle || theme.colors.border};
        border-bottom-left-radius: ${COMMENT_CURVE_RADIUS_PX}px;
        pointer-events: none;
    }

    padding: ${({ $isCollapsed, $level }) => {
        const lvl = Math.max(Number($level) || 0, 0);
        const leftPad = lvl > 0
            ? `${commentContentLeftPx(lvl, COMMENT_BASE_LEFT_PX, COMMENT_INDENT_PX, COMMENT_AVATAR_SIZE_PX, COMMENT_CONTENT_GAP_PX)}px`
            : '1rem';
        if ($isCollapsed) return `${COMMENT_PAD_TOP_COLLAPSED_REM}rem 1rem ${COMMENT_PAD_TOP_COLLAPSED_REM}rem ${leftPad}`;
        return `${COMMENT_PAD_TOP_EXPANDED_REM}rem 1rem 0.7rem ${leftPad}`;
    }};

    &:hover {
        background-color: ${({ theme }) => theme.colors.hoverBg};
    }

    &.inbox-highlight {
        box-shadow: inset 3px 0 0 0 ${({ theme }) => theme.colors.inboxHighlightRail} !important;
        background-color: ${({ theme }) => theme.colors.inboxHighlightBg} !important;
    }

    @media (max-width: 1000px) {
        ${({ $level, $activeDepths, theme }) => {
        const r = buildAncestorRails(
            $level,
            COMMENT_BASE_LEFT_PX_MOBILE,
            COMMENT_INDENT_PX_MOBILE,
            COMMENT_AVATAR_SIZE_PX_MOBILE,
            theme.colors.commentThread || theme.colors.borderSubtle || theme.colors.border,
            $activeDepths,
        );
        return `
                background-image: ${r.image};
                background-position: ${r.position};
                background-size: ${r.size};
            `;
    }}
        &::after {
            left: ${({ $level }) =>
        `${commentAvatarLeftPx($level, COMMENT_BASE_LEFT_PX_MOBILE, COMMENT_INDENT_PX_MOBILE) + COMMENT_AVATAR_SIZE_PX_MOBILE / 2}px`};
            top: ${({ $isCollapsed }) =>
        ($isCollapsed ? COMMENT_AVATAR_BOTTOM_Y_COLLAPSED_MOBILE : COMMENT_AVATAR_BOTTOM_Y_EXPANDED_MOBILE)};
            height: calc(100% - ${({ $isCollapsed }) =>
        ($isCollapsed ? COMMENT_AVATAR_BOTTOM_Y_COLLAPSED_MOBILE : COMMENT_AVATAR_BOTTOM_Y_EXPANDED_MOBILE)});
        }
        &::before {
            left: ${({ $level }) =>
        `${commentRailXPx($level, COMMENT_BASE_LEFT_PX_MOBILE, COMMENT_INDENT_PX_MOBILE, COMMENT_AVATAR_SIZE_PX_MOBILE)}px`};
            width: ${COMMENT_INDENT_PX_MOBILE - COMMENT_AVATAR_SIZE_PX_MOBILE / 2}px;
            height: ${({ $isCollapsed }) =>
        ($isCollapsed ? COMMENT_AVATAR_CENTER_Y_COLLAPSED_MOBILE : COMMENT_AVATAR_CENTER_Y_EXPANDED_MOBILE)};
            border-bottom-left-radius: ${COMMENT_CURVE_RADIUS_PX_MOBILE}px;
        }
        padding: ${({ $isCollapsed, $level }) => {
        const lvl = Math.max(Number($level) || 0, 0);
        const leftPad = lvl > 0
            ? `${commentContentLeftPx(lvl, COMMENT_BASE_LEFT_PX_MOBILE, COMMENT_INDENT_PX_MOBILE, COMMENT_AVATAR_SIZE_PX_MOBILE, COMMENT_CONTENT_GAP_PX_MOBILE)}px`
            : '0.85rem';
        if ($isCollapsed) return `${COMMENT_PAD_TOP_COLLAPSED_REM_MOBILE}rem 0.85rem ${COMMENT_PAD_TOP_COLLAPSED_REM_MOBILE}rem ${leftPad}`;
        return `${COMMENT_PAD_TOP_EXPANDED_REM_MOBILE}rem 0.85rem 0.6rem ${leftPad}`;
    }};
    }
`;

/**
 * DiceBear identicon avatar anchored to the username row of a
 * `CommentCard`. Rendered INLINE as the first item inside the meta
 * row's `MetaInfoRowLeft` flex container so it auto-centers vertically
 * with the username text via `align-items: center` — no fragile
 * pixel-tuned `top` offset needed.
 *
 * Horizontal placement: the meta row's left edge sits at the card's
 * `padding-left` (= `commentContentLeftPx`). The avatar pulls itself
 * back into the avatar gutter with a negative `margin-left` equal to
 * its own width plus the content gap, so its left edge lands exactly
 * at `commentAvatarLeftPx` for the row's level. The J-curve elbow
 * (drawn as a `::before` on `CommentCard`) terminates at that same x,
 * visually "delivering" the thread connection into the avatar.
 *
 * Wraps the shared `UserAvatar` component so the dicebear bg color and
 * 20% inner padding around the identicon glyph are consistent with
 * every other avatar surface in the app.
 */
const CommentAvatar = styled(UserAvatar)`
    flex-shrink: 0;
    align-self: center;
    margin-left: ${-(COMMENT_AVATAR_SIZE_PX + COMMENT_CONTENT_GAP_PX)}px;
    /* The meta row's flex column-gap (0.3rem ≈ 6px) gives most of the
     * gap to the next item; this margin-right tops it up to the
     * full content gap so the username text starts at the same x as
     * the body content below. */
    margin-right: ${Math.max(0, COMMENT_CONTENT_GAP_PX - 6)}px;
    pointer-events: none;
    position: relative;
    z-index: 2;
    /* Override the inherited ratio-based padding from \`UserAvatar\`.
     * \`!important\` is necessary because the Wrapper's runtime-
     * computed \`padding: ...px\` interpolation gets emitted into a
     * stylesheet rule whose source-order varies with first-render
     * timing — without \`!important\` we sometimes lose the cascade
     * race and the chip renders with the original 20% halo (the
     * identicon then hugs the chip border). We hardcode absolute
     * halos: 4px on desktop (23-4-4 = 15px inner), 3px on mobile
     * (21-3-3 = 15px inner). Both yield 15px / 5 = 3px cells —
     * pixel-perfect identicon rendering. The 15px identicon square
     * is also comfortably inscribed inside the 23-diameter desktop
     * circle (corners at 10.6 < radius 11.5), so \`border-radius:
     * 50%\` doesn't clip the identicon's corner cells either. */
    padding: 4px !important;

    /* In light theme the shared UserAvatar wrapper is transparent, so
     * the comment thread spine (drawn behind the avatar) shows through
     * the identicon's negative space. Force an opaque page-bg fill on
     * the comment-row avatar specifically so the spine is hidden behind
     * the chip — matching the dark-theme behavior — without changing
     * any other avatar surface. */
    ${({ theme }) =>
        theme.name === 'light'
            ? `background: ${theme.colors.bg} !important;`
            : ''}

    @media (max-width: 1000px) {
        margin-left: ${-(COMMENT_AVATAR_SIZE_PX_MOBILE + COMMENT_CONTENT_GAP_PX_MOBILE)}px;
        margin-right: ${Math.max(0, COMMENT_CONTENT_GAP_PX_MOBILE - 6)}px;
        width: ${COMMENT_AVATAR_SIZE_PX_MOBILE}px;
        height: ${COMMENT_AVATAR_SIZE_PX_MOBILE}px;
        padding: 3px !important;
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
    position: relative;
    display: block;
    background: transparent;
    background-color: transparent;
    background-repeat: no-repeat;
    border: none;
    border-radius: 0;
    margin-left: 0;
    margin-top: 0;
    margin-bottom: 0;
    color: ${({ theme }) => theme.colors.link};
    font-size: 0.72rem;
    font-weight: 500;
    text-decoration: none;
    transition: color 0.15s ease, background-color 0.15s ease;

    /* The link inherits the parent's ancestor rails so the thread line
     * continues seamlessly into this row. Terminal row: J-curve only —
     * no downward spine past the elbow (that stub looked broken). */
    ${({ $activeDepths, theme }) => {
        const r = buildAncestorRails(
            0, /* level is irrelevant when activeDepths is passed directly */
            COMMENT_BASE_LEFT_PX,
            COMMENT_INDENT_PX,
            COMMENT_AVATAR_SIZE_PX,
            theme.colors.commentThread || theme.colors.borderSubtle || theme.colors.border,
            $activeDepths,
        );
        return `
            background-image: ${r.image};
            background-position: ${r.position};
            background-size: ${r.size};
        `;
    }}

    &::before {
        content: '';
        position: absolute;
        top: 0;
        left: ${({ $level }) => {
        const effective = (Number($level) || 0) + 1;
        return `${commentRailXPx(effective, COMMENT_BASE_LEFT_PX, COMMENT_INDENT_PX, COMMENT_AVATAR_SIZE_PX)}px`;
    }};
        width: ${COMMENT_INDENT_PX - COMMENT_AVATAR_SIZE_PX / 2}px;
        height: calc(${CONTINUE_THREAD_PAD_Y_REM}rem + ${COMMENT_META_ROW_HALF_PX}px);
        border-left: ${COMMENT_RAIL_WIDTH_PX}px solid ${({ theme }) => theme.colors.commentThread || theme.colors.borderSubtle || theme.colors.border};
        border-bottom: ${COMMENT_RAIL_WIDTH_PX}px solid ${({ theme }) => theme.colors.commentThread || theme.colors.borderSubtle || theme.colors.border};
        border-bottom-left-radius: ${COMMENT_CURVE_RADIUS_PX}px;
        pointer-events: none;
    }

    /* Elbow lands at child avatar-left; no avatar here, so park the
     * label a few px past the tip instead of avatar+gap (that left a
     * wide empty gutter). */
    padding: ${({ $level }) => {
        const effective = (Number($level) || 0) + 1;
        const leftPad = commentAvatarLeftPx(effective, COMMENT_BASE_LEFT_PX, COMMENT_INDENT_PX) + 6;
        return `${CONTINUE_THREAD_PAD_Y_REM}rem 1rem ${CONTINUE_THREAD_PAD_Y_REM}rem ${leftPad}px`;
    }};

    &:hover {
        background-color: ${({ theme }) => theme.colors.hoverBg};
        color: ${({
        theme
    }) => theme.colors.linkHover};
    }

    @media (max-width: 1000px) {
        ${({ $activeDepths, theme }) => {
        const r = buildAncestorRails(
            0,
            COMMENT_BASE_LEFT_PX_MOBILE,
            COMMENT_INDENT_PX_MOBILE,
            COMMENT_AVATAR_SIZE_PX_MOBILE,
            theme.colors.commentThread || theme.colors.borderSubtle || theme.colors.border,
            $activeDepths,
        );
        return `
                background-image: ${r.image};
                background-position: ${r.position};
                background-size: ${r.size};
            `;
    }}
        &::before {
            left: ${({ $level }) => {
        const effective = (Number($level) || 0) + 1;
        return `${commentRailXPx(effective, COMMENT_BASE_LEFT_PX_MOBILE, COMMENT_INDENT_PX_MOBILE, COMMENT_AVATAR_SIZE_PX_MOBILE)}px`;
    }};
            width: ${COMMENT_INDENT_PX_MOBILE - COMMENT_AVATAR_SIZE_PX_MOBILE / 2}px;
            height: calc(${CONTINUE_THREAD_PAD_Y_REM}rem + ${COMMENT_META_ROW_HALF_PX}px);
            border-bottom-left-radius: ${COMMENT_CURVE_RADIUS_PX_MOBILE}px;
        }
        padding: ${({ $level }) => {
        const effective = (Number($level) || 0) + 1;
        const leftPad = commentAvatarLeftPx(effective, COMMENT_BASE_LEFT_PX_MOBILE, COMMENT_INDENT_PX_MOBILE) + 5;
        return `${CONTINUE_THREAD_PAD_Y_REM}rem 0.85rem ${CONTINUE_THREAD_PAD_Y_REM}rem ${leftPad}px`;
    }};
    }
`;

// Community hero container aligned with ModernPostFeed width
const CommunityHeroWrapper = styled.div`
    width: 100%;
    margin: 0;
`;
/**
 * Flat header row above the root post — holds the back button (left) and
 * follow-community button (right). No card background; separated from the
 * post below via the `PostCard` bottom divider (R3). Matches the Inbox /
 * Search header rhythm.
 */
const CommunityHeroCard = styled.div`
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
        padding: 0.35rem 0 0.5rem;
    }
`;
const CommunityHeroTopRow = styled.div`
    display: none;
    
    @media (max-width: 600px) {
        display: flex;
        width: 100%;
        align-items: center;
        justify-content: space-between;
    }
`;
const CommunityHeroMobileActions = styled.div`
    display: flex;
    align-items: center;
    gap: 0.2rem;
    margin-left: auto;
`;
const CommunityHeroBackSection = styled.div`
    display: flex;
    align-items: center;
    flex-shrink: 0;
    
    @media (max-width: 600px) {
        display: none;
    }
`;
const CommunityAction = styled.div`
    display: flex;
    align-items: center;
    gap: 0.2rem;
    flex-shrink: 0;
    
    @media (max-width: 600px) {
        display: none;
    }
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

// Reuse the same visual style as community links in the feed
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
const StyledCommunityLink = styled(Link)`
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
 * (community · user · time · tag). Right side holds the actions (follow,
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
 * Metadata cluster (community · user · time · tag) on the left side of the
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
const MetaInfoRowRight = styled.div`
    display: flex;
    align-items: center;
    gap: 0.3rem;
    margin-left: auto;
    flex: 0 0 auto;
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
 * as quiet metadata in the same rhythm as community / author / time.
 * Lifts to `text` on hover.
 */
const CollapseToggle = styled.button`
    appearance: none;
    background: transparent;
    border: 1px solid currentColor;
    border-radius: 50%;
    padding: 0;
    box-sizing: border-box;
    margin: 0;
    width: 14px;
    height: 14px;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-family: inherit;
    font-size: 11px;
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
    transition: color 0.12s ease, border-color 0.12s ease;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    vertical-align: middle;
    text-align: center;
    user-select: none;

    & > span {
        display: block;
        line-height: 1;
        transform: translateY(-0.5px);
    }

    &:hover {
        color: ${({ theme }) => theme.colors.text};
    }
`;

// Mobile root post meta - two rows: community+author+menu, then time/tag.
// Same leading order as the feed card: [community] · @author · time.
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
    gap: 0.3rem;
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.2;
    & a {
        font-size: inherit;
        line-height: inherit;
    }
`;
const MobileRootMetaPrimary = styled.div`
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.2rem 0.3rem;
    min-width: 0;
    flex: 1 1 auto;
`;
const MobileRootMetaMenu = styled.div`
    display: flex;
    align-items: center;
    margin-left: auto;
    flex: 0 0 auto;
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
    cursor: ${({ $clickable }) => ($clickable ? 'pointer' : 'default')};
    user-select: ${({ $clickable }) => ($clickable ? 'none' : 'auto')};
    @media (max-width: 600px) {
        display: ${({
    $hideOnMobile
}) => $hideOnMobile ? 'none' : 'flex'};
    }
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
    display: inline-flex;
    align-items: center;
    gap: 0.15rem;
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

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.menuItemHoverBg};
        color: ${({ theme }) => theme.colors.menuItemHoverText};
    }

    &[data-danger="true"]:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.menuItemHoverBg};
        color: ${({ theme }) => theme.colors.voteDown};
    }

    &:disabled {
        opacity: 0.55;
        cursor: not-allowed;
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
    /* Let drag-resized media break out of the narrow FeedCol column. */
    overflow: visible;

    p { margin: 0 0 0.5rem; }
    p:last-child { margin-bottom: 0; }
    a { color: ${({ theme }) => theme.colors.link}; }

    /* Let drag-resized images escape the post column. The initial size
     * is still capped via InlineMedia's internal max (600px height for
     * root posts, 225px for comments). When the user drags the image
     * wider, InlineMedia sets maxWidth: 'none' inline, allowing the
     * image to grow up to the viewport width — matching bluemoon. */
    img, video {
        max-height: 600px;
    }
    img[style*="max-width: none"],
    video[style*="max-width: none"] {
        max-height: none;
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
    /* Allow drag-resized images to visually escape the 820px FeedCol
     * on desktop and extend toward the viewport edge (matching the
     * bluemoon theme's behaviour). The image itself is capped at
     * window.innerWidth - 16 by InlineMedia so it never triggers a
     * page-level horizontal scrollbar. */
    overflow-x: visible;
    box-sizing: border-box;

    /* On tablet/mobile the feed column collapses to full-bleed, so the
     * previous hidden behaviour is fine — re-enable it to keep the old
     * defensive guard against any stray horizontal overflow (long code
     * blocks, iframes, etc.). */
    @media (max-width: 1000px) {
        overflow-x: hidden;
    }
`;
/**
 * Inline reply composer block. Flat wrapper that sits under the active
 * post/comment. Uses the feed card rhythm: no card chrome of its own,
 * content separated from the surrounding post/comment by a top divider
 * (R3), tight 0.45rem vertical gap so media row → editor → action row
 * read as a single unit.
 *
 * Also overrides the nested `MarkdownEditor` shared component so the
 * textarea + toolbar read against the default theme instead of the
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

    /* Toolbar / icon / preview-toggle styling lives in
     * DefaultEditorChrome, the shared wrapper around <MarkdownEditor>
     * used by both this composer and CreatePostView. Only context-
     * specific stuff (textarea size, preview pane size, submit/cancel
     * pills) stays here. */

    /* --- Preview pane --------------------------------------------------
     * LivePreviewContainer is the LAST child of EditorContainer (which is
     * itself the only direct child of [data-default-editor]). Override
     * it to a subtle composerPreviewBg tile with lighter body text.
     */
    [data-default-editor] > div > :last-child {
        background: ${({ theme }) => theme.colors.composerPreviewBg} !important;
        border: 1px solid ${({ theme }) => theme.colors.border} !important;
        border-radius: 8px !important;
        padding: 0.55rem 0.7rem !important;
        font-size: 0.7rem !important;
        font-weight: 400 !important;
        color: ${({ theme }) => theme.colors.text} !important;
    }
    [data-default-editor] > div > :last-child p,
    [data-default-editor] > div > :last-child li,
    [data-default-editor] > div > :last-child span {
        font-weight: 400 !important;
    }
    [data-default-editor] > div > :last-child > div:first-child {
        font-size: 0.5rem !important;
        font-weight: 600 !important;
        color: ${({ theme }) => theme.colors.subtleText} !important;
        margin-bottom: 0.35rem !important;
    }

    /* --- Submit / Cancel buttons --------------------------------------
     * Submit: flat pill in followBtnBg (matches the community Follow pill in
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

    /* Cancel button — flagged via data-default-cancel on the JSX so we
     * never accidentally restyle other buttons in the composer.
     */
    button[data-default-cancel] {
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
    button[data-default-cancel]:hover:not(:disabled) {
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
/**
 * Blocked-post state — visual twin of `MainView`'s `BlockedCommunityState`.
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
 * Sits where the reply button would be when the current lens has the thread
 * locked. It reads as metadata rather than an error because the lock is a
 * curation choice, not a failure, and switching to the raw lens lifts it.
 */
const LockedNote = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    color: ${({ theme }) => theme.colors.feedCtrlText};
    font-size: 0.75rem;
    line-height: 1;
    flex-shrink: 0;
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
    background: ${({ theme, $success }) =>
        $success ? theme.colors.buttonSuccessBg : theme.colors.actionIconBg};
    color: ${({ theme, $danger, $success }) =>
        $success ? theme.colors.voteUp : $danger ? theme.colors.voteDown : theme.colors.feedCtrlText};
    font-family: inherit;
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1;
    text-decoration: none;
    white-space: nowrap;
    cursor: pointer;
    transition: background 0.12s ease, color 0.12s ease;

    &:visited { color: ${({ theme, $danger, $success }) =>
        $success ? theme.colors.voteUp : $danger ? theme.colors.voteDown : theme.colors.feedCtrlText}; }
    &:hover,
    &:visited:hover {
        background: ${({ theme, $success }) =>
        $success ? theme.colors.buttonSuccessBg : theme.colors.actionIconHoverBg};
        color: ${({ theme, $danger, $success }) =>
        $success ? theme.colors.voteUp : $danger ? theme.colors.voteDown : theme.colors.text};
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
// `BlockConfirmMessage` + `ConfirmButtons` removed in 06.11 D1 — every
// confirm flow on this route now renders through the canonical
// `ConfirmDialog` modal at the route root.
// `ReportInput` removed (06.3) — replaced by the `ConfirmDialog`
// textarea at the route root.

// Returns absolute local timestamp: YYYY-MM-DD HH:MM:SS

function ViewPostView({
    state,
    updatePost
}) {
    const [searchParams, setSearchParams] = useSearchParams();
    const threadLens = React.useMemo(
        () => normalizeLens(searchParams.get('lens') || LENS.EFFECTIVE, searchParams.get('team_id')),
        [searchParams],
    );
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
        confirmBlockCommunity,
        confirmDeletePost,
        isDeleting,
        deleteMessages,
        deletedPosts,
        confirmDonate,
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
        ancestorsOmitted,
        setAncestors,
        setAncestorsOmitted,
        cardSize,
        theme,
        navigate,
        openBrowsingEnabled,
        nodeConfigLoaded,
        isMobile,
        goBackToFeed,
        viewerAddress,
        isCommunityPending,
        isUserPending,
        formatCommunityStatus,
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
        isJoinedCommunity,
        handleCommunityJoinToggle,
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
        confirmBlockPostAction,
        cancelBlockPost,
        confirmBlockUserAction,
        cancelBlockUser,
        confirmBlockCommunityAction,
        cancelBlockCommunity,
        confirmReportAction,
        cancelReport,
        handleDeletePost,
        confirmDeletePostAction,
        cancelDeletePost,
        handleDonate,
        handleGiftSubscription,
        confirmGiftSubAction,
        cancelGiftSub,
        userBalanceUmirage,
        AWARD_TYPES,
        giftSubscriptionLabel,
        subFeeLabel,
        subFeeUmirage,
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
        rootFlash,
        normalizedHighlightId,
        annotated,
        depthError
    } = useViewPost({
        state,
        updatePost,
        lens: threadLens.lens,
        teamId: threadLens.teamId,
    });
    const [, setCurationVisibilityRevision] = useState(0);
    useEffect(() => {
        const handleOptimisticModeration = () => {
            setCurationVisibilityRevision((current) => current + 1);
        };
        window.addEventListener('curationModerationOptimistic', handleOptimisticModeration);
        return () => window.removeEventListener('curationModerationOptimistic', handleOptimisticModeration);
    }, []);

    const handleThreadLensChange = useCallback((nextLens, nextTeamId) => {
        const next = normalizeLens(nextLens, nextTeamId);
        const params = new URLSearchParams(searchParams);
        params.set('lens', next.lens);
        if (next.teamId) params.set('team_id', String(next.teamId));
        else params.delete('team_id');
        console.debug('[ViewPostView] thread lens', next);
        setSearchParams(params, { replace: true });
    }, [searchParams, setSearchParams]);

    // Inline block/report popover lives on BlockChip (same slot as the
    // feed). 3-dot overflow clamping below still applies to this page's
    // custom ⋯ portal.
    const clampMenuIntoViewport = (dropdownEl, buttonEl, setPosition) => {
        if (!dropdownEl || !buttonEl) return;
        const margin = 8;
        const ddH = dropdownEl.offsetHeight;
        const ddW = dropdownEl.offsetWidth;
        const vh = (typeof window !== 'undefined' && window.innerHeight) || 0;
        const vw = (typeof window !== 'undefined' && window.innerWidth) || 0;
        const btnRect = buttonEl.getBoundingClientRect();
        let top = btnRect.bottom + 4;
        let left = Math.max(10, btnRect.right - ddW);
        if (top + ddH > vh - margin) {
            const flippedTop = btnRect.top - 4 - ddH;
            if (flippedTop >= margin) {
                top = flippedTop;
            } else {
                top = Math.max(margin, vh - margin - ddH);
            }
        }
        if (left + ddW > vw - margin) {
            left = Math.max(margin, vw - margin - ddW);
        }
        setPosition({ top, left });
    };

    useLayoutEffect(() => {
        if (!openMenuId) return;
        clampMenuIntoViewport(
            menuDropdownRef.current,
            menuButtonRefs.current[openMenuId],
            setMenuPosition
        );
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [openMenuId]);

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
    /* Unblock-then-reveal — poll-and-hydrate approach (06.3 polish
     * round 7 final).
     *
     * Server-side `get_comments` filters the comment tree against the
     * viewer's blocked list and returns 404 when the target post is
     * blocked. That means the initial mount's fetch 404s, leaving
     * `error` set and `root` empty in the hook state.
     *
     * When the user clicks Unblock, `useBlocks` optimistically removes
     * the post id from `blockedPosts` as soon as the tx resolves — but
     * the chain-side commit takes longer, so an immediate refetch still
     * returns 404. A hard `window.location.reload()` races the same
     * way: the fresh mount hydrates `blockedPosts` from the server,
     * which may still show the post as blocked, so we flip right back
     * into the block panel.
     *
     * The robust fix is to keep the block panel showing (gated on a
     * local `unblockInFlight` flag) while we poll `get_comments` with
     * backoff until it returns a root. When it does, we commit
     * `root` + `children` into the hook state, clear `error`/`loading`,
     * then drop `unblockInFlight` so the panel gives way to the real
     * post content — no reload, no error flash. */
    const [unblockInFlight, setUnblockInFlight] = useState(false);
    const unblockAbortRef = useRef(false);
    useEffect(() => () => { unblockAbortRef.current = true; }, []);
    const handleUnblockBlockedPost = async e => {
        if (!blockedPostIdLower) return;
        if (e && typeof e.preventDefault === 'function') e.preventDefault();
        if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
        setUnblockInFlight(true);
        try { setError(null); } catch (_) { /* noop */ }
        try {
            await handleUnblockPost(e, blockedPostIdLower);
        } catch (_) { /* handleUnblockPost already alerts on error */ }
        // Poll `get_comments` until the server returns the post (chain
        // commit can lag the tx resolve by 0.5–2s). Backoff: 400ms,
        // 700ms, 1000ms, 1500ms, 2000ms × 3 — ~10s total.
        const delays = [400, 700, 1000, 1500, 2000, 2000, 2000];
        const viewerAddress = Storage.load('publicKey', '');
        let delivered = false;
        for (let i = 0; i < delays.length; i++) {
            if (unblockAbortRef.current) return;
            await new Promise(r => setTimeout(r, delays[i]));
            if (unblockAbortRef.current) return;
            try {
                const data = await Api.get('get_comments', {
                    post_id: blockedPostIdLower,
                    address: viewerAddress,
                    lens: 'effective',
                    scope: 'current',
                });
                if (
                    data && data.root && data.root.post_id
                    && Array.isArray(data.ancestors)
                    && ('ancestors_omitted' in data)
                ) {
                    if (unblockAbortRef.current) return;
                    try { setRoot(data.root); } catch (_) { /* noop */ }
                    try { setChildren(data.children || []); } catch (_) { /* noop */ }
                    try { setAncestors(data.ancestors); } catch (_) { /* noop */ }
                    try { setAncestorsOmitted(Number(data.ancestors_omitted) || 0); } catch (_) { /* noop */ }
                    try { setError(null); } catch (_) { /* noop */ }
                    try { setLoading(false); } catch (_) { /* noop */ }
                    delivered = true;
                    break;
                }
            } catch (_) { /* 404s while tx commits — retry */ }
        }
        if (!delivered) {
            // Final fallback: reload the page so the fresh mount gets a
            // clean state. By this point ~10s have passed so the unblock
            // has almost certainly committed.
            try { window.location.reload(); } catch (_) { /* noop */ }
            return;
        }
        setUnblockInFlight(false);
    };

    // Blocked-post short circuit — when the viewer has blocked this
    // post, render only the `BlockedPostState` panel (no content, no
    // comments). Also held open while `unblockInFlight` is true so we
    // don't flash the "Couldn't load post" error state during the poll
    // window between tx-resolve and the server returning the post.
    if (isPostBlocked || unblockInFlight) {
        const unblockBusy = unblockInFlight || isUnblockPostPending;
        return <ContentGrid>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
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
                            <BlockedPostTitle>
                                {unblockInFlight ? 'Unblocking post…' : 'This post is blocked'}
                            </BlockedPostTitle>
                            <BlockedPostMessage>
                                {unblockInFlight
                                    ? 'Waiting for the unblock to commit on-chain. The post content will appear here shortly — hang tight.'
                                    : "You have blocked this post, so it's hidden from every feed you see. Unblock to view it — you can always re-block it later from the post menu or the Blocks page."}
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
                                    disabled={unblockBusy}
                                    onClick={handleUnblockBlockedPost}
                                >
                                    {unblockBusy ? (unblockPostStatus || 'Processing') : 'Unblock post'}
                                </Button>
                            </BlockedPostActions>
                        </BlockedPostState>
                    </ModernPostFeed>
                </FeedCol>
            </FeedRailRow>
        </ContentGrid>;
    }

    if (loading || error || depthError) {
        return <ContentGrid>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
                    <ModernPostFeed>
                        <BackButton onClick={goBackToFeed}>
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <line x1="19" y1="12" x2="5" y2="12"></line>
                                <polyline points="12 19 5 12 12 5"></polyline>
                            </svg>
                            Back
                        </BackButton>
                        {loading ? (
                            <div role="status" aria-live="polite" aria-label="Loading post">
                                <FeedCardSkeleton />
                                <CommentSkeleton />
                                <CommentSkeleton indent={1} />
                                <CommentSkeleton />
                            </div>
                        ) : <VPStateBlock role="alert">
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
                </FeedCol>
            </FeedRailRow>
        </ContentGrid>;
    }
    const shortenAddress = address => {
        if (!address) return "";
        return `${address.substring(0, 10)}…${address.substring(address.length - 4)}`;
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
        // Block / report / delete confirmations all moved to root-level
        // `ConfirmDialog` modals (06.3 + 06.11 D1). The inline banners for
        // the remaining flows (donate, gift sub, award) still render below.
        if (confirmBlockPost === post.post_id) return null;
        if (confirmBlockUser?.postId === post.post_id) return null;
        if (confirmBlockCommunity?.postId === post.post_id) return null;
        if (confirmDeletePost === post.post_id) return null;
        // Report popup moved to a root-level `ConfirmDialog` (06.3 polish).
        if (confirmReportPost === post.post_id) return null;
        // Gift Mirage / Gift Subscription / Give Award popups now render
        // as root-level default `ConfirmDialog` modals (see below). We
        // still surface their success/error banners inline so the user
        // sees "Sent 10,000 MIRAGE!" / "Subscription gifted!" under the
        // post card they acted on.
        if (confirmDonate?.postId === post.post_id) return null;
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
        if (confirmGiftSub?.postId === post.post_id) return null;
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
        if (confirmAward?.postId === post.post_id) return null;
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

        // Share success is surfaced inline on the share button itself
        // (label flips to "Link copied"). No bottom banner — matches the
        // profile-card share feedback pattern.

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
        const isOpen = openMenuId === post.post_id;
        const authorAddr = String(post.user_id || '').trim().toLowerCase();
        const isFollowingThisAuthor = isFollowingAuthor(authorAddr);
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
                {(() => {
                    const isRootPost = !!(post.title && String(post.title).trim() !== '');
                    const itemLabel = isRootPost ? 'post' : 'comment';
                    const communityLower = (post && typeof post.community === 'string') ? post.community.trim().toLowerCase() : '';
                    const joinedCommunity = communityLower ? isJoinedCommunity(communityLower) : false;
                    const postLinkPath = isRootPost
                        ? `/p/${post.post_id}`
                        : `/p/${post.post_id}`;
                    const handleCopyLink = () => {
                        setOpenMenuId(null);
                        try {
                            const url = `${window.location.origin}${postLinkPath}`;
                            if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
                                navigator.clipboard.writeText(url);
                            }
                        } catch (_) { /* noop */ }
                    };
                    const handleCopyText = () => {
                        setOpenMenuId(null);
                        try {
                            const parts = [];
                            const titleStr = post.title;
                            const contentStr = post.content;
                            if (titleStr && String(titleStr).trim()) parts.push(String(titleStr).trim());
                            if (contentStr && String(contentStr).trim()) parts.push(String(contentStr).trim());
                            const text = parts.join('\n\n');
                            if (text && typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
                                navigator.clipboard.writeText(text);
                            }
                        } catch (_) { /* noop */ }
                    };
                    const mediaUrlsForDownload = (() => {
                        if (Array.isArray(post.media) && post.media.length > 0) return post.media;
                        const raw = String(post.content || '');
                        const idx = raw.indexOf('\n');
                        const first = (idx >= 0 ? raw.slice(0, idx) : raw).trim();
                        return /^https?:\/\//i.test(first) ? [first] : [];
                    })();
                    const mediaDownloads = getDownloadableMedia(mediaUrlsForDownload);
                    return <>
                        <MenuItem onClick={handleCopyLink}>
                            <HiOutlineLink />
                            <span>Copy link</span>
                        </MenuItem>
                        <MenuItem onClick={handleCopyText}>
                            <HiOutlineClipboardDocument />
                            <span>Copy text</span>
                        </MenuItem>
                        {mediaDownloads.map((d, i) => (
                            <MenuItem key={`dl-${i}`} onClick={() => { setOpenMenuId(null); triggerMediaDownload(d); }}>
                                <HiOutlineArrowDownTray />
                                <span>{mediaDownloadLabel(d.kind, i, mediaDownloads.length, d.format)}</span>
                            </MenuItem>
                        ))}
                        {isOwnPost && <>
                            <MenuItem onClick={() => {
                                setOpenMenuId(null);
                                if (isRootPost) {
                                    navigate(`/create_post?post_id=${post.post_id}&edit=true`);
                                } else {
                                    openEdit(post);
                                }
                            }}>
                                <HiOutlinePencilSquare />
                                <span>Edit {itemLabel}</span>
                            </MenuItem>
                            <MenuItem data-danger="true" onClick={() => {
                                setOpenMenuId(null);
                                handleDeletePost(post.post_id);
                            }}>
                                <HiOutlineTrash />
                                <span>Delete {itemLabel}</span>
                            </MenuItem>
                        </>}
                        {!isOwnPost && hasValidAccount && <>
                            <MenuItem onClick={() => {
                                setOpenMenuId(null);
                                handleFollowToggle(authorAddr);
                            }}>
                                {isFollowingThisAuthor ? <HiOutlineUserMinus /> : <HiOutlineUserPlus />}
                                <span>{isUserPending(authorAddr) ? formatUserStatus(authorAddr) : isFollowingThisAuthor ? 'Unfollow user' : 'Follow user'}</span>
                            </MenuItem>
                            {isRootPost && post?.community && <MenuItem disabled={isCommunityPending(communityLower)} onClick={() => {
                                setOpenMenuId(null);
                                handleCommunityJoinToggle(post.community);
                            }}>
                                <HiOutlineHashtag />
                                <span>{isCommunityPending(communityLower) ? formatCommunityStatus(communityLower) : joinedCommunity ? 'Leave community' : 'Join community'}</span>
                            </MenuItem>}
                            <MenuItem onClick={() => {
                                setOpenMenuId(null);
                                handleGiveAward(post.post_id);
                            }}>
                                <HiOutlineSparkles />
                                <span>Give Award</span>
                            </MenuItem>
                            {viewerAddress !== 'guest' && <MenuItem onClick={() => {
                                setOpenMenuId(null);
                                handleDonate(post.user_id, post.post_id);
                            }}>
                                <HiOutlineGift />
                                <span>Gift Mirage</span>
                            </MenuItem>}
                            {viewerAddress !== 'guest' && <MenuItem disabled={isSubscribePending(post.user_id)} onClick={() => {
                                setOpenMenuId(null);
                                handleGiftSubscription(post.user_id, post.post_id, post.author_level);
                            }}>
                                <HiOutlineGift />
                                <span>{formatSubscribeStatus(post.user_id) || giftSubscriptionLabel}</span>
                            </MenuItem>}
                        </>}
                        {!isOwnPost && hasValidAccount && (() => {
                            try { return Number(Storage.load('user_level', '0')) >= 100; }
                            catch (_) { return false; }
                        })() && (
                                <MenuItem data-danger="true" onClick={() => {
                                    setOpenMenuId(null);
                                    handleDeletePost(post.post_id);
                                }}>
                                    <HiOutlineShieldExclamation />
                                    <span>Delete network wide</span>
                                </MenuItem>
                            )}
                    </>;
                })()}
            </MenuDropdown>, document.body)}
        </MenuContainer>;
    };
    const renderHeaderLensPicker = community => {
        if (!community) return null;
        return <PostLensPicker
            community={community}
            viewer={viewerAddress}
            hintLens={mergedRoot?.lens || root?.lens}
            onChange={handleThreadLensChange}
        />;
    };
    // The lock belongs to the thread under the current lens, so it applies to
    // every post in the view, not just the root the backend reports it on.
    // state.posts wins so a lock/unlock from the curate menu is visible before
    // the indexer serves the new value.
    const stateEntry = root?.post_id
        ? (state?.posts?.[root.post_id] || state?.posts?.[String(root.post_id).toLowerCase()])
        : null;
    const stateLock = stateEntry?.thread_locked;
    const threadLocked = stateLock !== undefined ? !!stateLock : !!root?.thread_locked;
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
            {threadLocked ? <LockedNote title="A curator locked this thread. Switch to the uncensored lens to see and add replies.">
                <Icon aria-hidden="true">
                    <svg viewBox="0 0 24 24">
                        <path d="M12 1a5 5 0 0 0-5 5v3H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V11a2 2 0 0 0-2-2h-1V6a5 5 0 0 0-5-5zm0 2a3 3 0 0 1 3 3v3H9V6a3 3 0 0 1 3-3z"></path>
                    </svg>
                </Icon>
                <span>thread locked</span>
            </LockedNote> : <ActionButton onClick={() => toggleReply(post.post_id)}>
                <Icon aria-hidden="true">
                    <svg viewBox="0 0 24 24">
                        <path d="M4 4h16v12H5.17L4 17.17V4zm0-2a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H4z"></path>
                    </svg>
                </Icon>
                <span>reply</span>
            </ActionButton>}
            <MetaSeparatorAction />
            <BlockChip post={post} state={state} updatePost={updatePost} align="right" />
            {(() => {
                const shareCopied = !!shareMessages[post.post_id];
                return (
                    <ActionButton
                        onClick={() => handleShare(post)}
                        $success={shareCopied}
                        title={shareCopied ? 'Link copied!' : 'Share'}
                        aria-label={shareCopied ? 'Link copied' : 'Share post'}
                        aria-live="polite"
                    >
                        <Icon aria-hidden="true">
                            {shareCopied ? (
                                <svg viewBox="0 0 24 24">
                                    <path d="M9.55 17.54l-4.24-4.24 1.41-1.41 2.83 2.83 7.07-7.07 1.41 1.41z" fill="currentColor" />
                                </svg>
                            ) : (
                                <svg viewBox="0 0 458.624 458.624">
                                    <path d="M339.588,314.529c-14.215,0-27.456,4.133-38.621,11.239l-112.682-78.67c1.809-6.315,2.798-12.976,2.798-19.871 c0-6.896-0.989-13.557-2.798-19.871l109.64-76.547c11.764,8.356,26.133,13.286,41.662,13.286c39.79,0,72.047-32.257,72.047-72.047 C411.634,32.258,379.378,0,339.588,0c-39.79,0-72.047,32.257-72.047,72.047c0,5.255,0.578,10.373,1.646,15.308l-112.424,78.491 c-10.974-6.759-23.892-10.666-37.727-10.666c-39.79,0-72.047,32.257-72.047,72.047s32.256,72.047,72.047,72.047 c13.834,0,26.753-3.907,37.727-10.666l113.292,79.097c-1.629,6.017-2.514,12.34-2.514,18.872c0,39.79,32.257,72.047,72.047,72.047 c39.79,0,72.047-32.257,72.047-72.047C411.635,346.787,379.378,314.529,339.588,314.529z" fill="currentColor" />
                                </svg>
                            )}
                        </Icon>
                        <span className="share-text">{shareCopied ? 'Link copied' : 'Share'}</span>
                    </ActionButton>
                );
            })()}
        </MetaRow>;
    };
    const displayReplyBox = (post, forMobileOverlay = false) => {
        if (!state.posts[post.post_id]?.replyOpen) return <div></div>;
        const isEdit = state.posts[post.post_id]?.replyMode === 'edit';
        // A composer left open from before the lock landed must not stay usable.
        // Editing your own existing post is not a new reply, so it survives.
        if (threadLocked && !isEdit) return <div></div>;

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
                    {(replyIsUploading[post.post_id] || (replyAttachedType[post.post_id] && replyAttachedUrl[post.post_id])) && <MediaRow>
                        <MediaPreviewWrapper>
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
                                {replyAttachedType[post.post_id] === 'video' && !replyThumbLoading[post.post_id] && <VideoPlayBadge size={26} />}
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
                                    Uploading {replyUploadProgress[post.post_id] !== undefined ? `${Math.round(replyUploadProgress[post.post_id])}%` : '…'}
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
                        </MediaPreviewWrapper>
                    </MediaRow>}
                    <DefaultEditorChrome>
                        <MarkdownEditor value={replyText} onChange={v => handleReplyChange(post.post_id, v)} maxLength={limits.maxContent} disabled={isBusy} autoFocus={true} toolbarExtra={
                            /* Same shared component as the post composer in
                             * CreatePostView. No explicit upload button here —
                             * drag-drop and paste-upload still flow through
                             * MarkdownEditor's built-in handlers. */
                            <EditorMediaTools
                                onSelect={pickedUrl => {
                                    setReplyAttachedType(prev => ({ ...prev, [post.post_id]: 'image' }));
                                    setReplyAttachedUrl(prev => ({ ...prev, [post.post_id]: pickedUrl }));
                                    setReplyThumbLoading(prev => ({ ...prev, [post.post_id]: true }));
                                }}
                                onUploadImage={() => {
                                    try {
                                        const api = replyEditorUpload[post.post_id];
                                        if (api && typeof api.selectFile === 'function') api.selectFile('image');
                                    } catch (_) { /* noop */ }
                                }}
                                onLinkImage={() => {
                                    try {
                                        const api = replyEditorUpload[post.post_id];
                                        if (api && typeof api.insertImageLink === 'function') api.insertImageLink();
                                    } catch (_) { /* noop */ }
                                }}
                                disabled={isBusy || !!replyIsUploading[post.post_id] || !!replyAttachedUrl[post.post_id]}
                            />
                        } onSubmitShortcut={() => {
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
                        }} suffixLabel={limits.isAdmin ? '(admin)' : (limits.willPayFee ? '(paid tier)' : '(free tier)')} showUploadButton={false} belowElement={replySubmitError[post.post_id] ? <ReplyErrorMessage role="alert">{replySubmitError[post.post_id]}</ReplyErrorMessage> : null} />
                    </DefaultEditorChrome>
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
                                {`${replyText.length} / ${limits.maxContent} ${limits.isAdmin ? '(admin)' : (limits.willPayFee ? '(paid tier)' : '(free tier)')}`}
                            </ReplyCounter>
                        </div>
                        <StyledSubmitButtonContainer>
                            <Button type="submit" size="sm" disabled={isBusy || !!replyIsUploading[post.post_id]} loading={isBusy}>
                                {isBusy ? replySubmitStatus[post.post_id] === 'submitting' ? 'Submitting…' : replySubmitStatus[post.post_id] === 'verifying' ? 'Verifying…' : 'Processing' : isEdit ? 'Save edit' : replyIsUploading[post.post_id] ? 'Uploading…' : 'Submit'}
                            </Button>
                            <Button data-default-cancel type="button" variant="ghost" size="sm" onClick={() => closeReply(post.post_id)} disabled={isBusy}>Cancel</Button>
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

    // Merge root with any optimistic/local updates from state.posts for immediate UI reflection (title/community/content edits)
    const mergedRoot = (() => {
        try {
            if (!root || !root.post_id) return root;
            const sp = state && state.posts ? state.posts[root.post_id] : undefined;
            if (!sp) return root;
            const out = {
                ...root
            };
            if (sp.title !== undefined) out.title = sp.title;
            if (sp.community !== undefined) out.community = sp.community;
            if (sp.root_community !== undefined) out.root_community = sp.root_community;
            if (sp.tag !== undefined) out.tag = sp.tag;
            if (sp.thread_locked !== undefined) out.thread_locked = sp.thread_locked;
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
        if (!isMobile || threadLocked) return null;
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
        const authorDisplay = post.username || (post.author ? `${post.author.substring(0, 8)}…` : 'Unknown');
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

    // Open browsing: guests may read the post; the signup prompt fires only when
    // they try to vote/comment/follow. Otherwise keep the logged-out gate. Wait for
    // node config before gating so a shared link doesn't flash the sign-in card.
    if (!isLoggedIn && !openBrowsingEnabled && nodeConfigLoaded) {
        return <ContentGrid>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
                    <ModernPostFeed>
                        <LoggedOutPromptCard
                            role="region"
                            aria-label="View post on Mirage"
                            title="Sign in to view this post"
                            description="Create an account or sign in to read posts, vote, and join the conversation."
                            stats={getCachedWelcomeStats()}
                            links={[
                                { label: "Watch Introduction (YouTube)", href: "https://www.youtube.com/watch?v=TOvP32ihQ0M", external: true },
                                { label: "Learn More", href: "https://mirage.foundation", external: true },
                            ]}
                            primaryLabel="Create account"
                            secondaryLabel="Sign in"
                        />
                    </ModernPostFeed>
                </FeedCol>
            </FeedRailRow>
        </ContentGrid>;
    }
    if (root) {
        const origin = typeof window !== 'undefined' && window.location && window.location.origin ? window.location.origin : 'https://mirage.vote';
        const postUrl = `${origin}/p/${root.post_id}`;
        const postTitle = mergedRoot && mergedRoot.title ? String(mergedRoot.title).trim() : root && root.title ? String(root.title).trim() : 'Mirage';
        const postDescription = mergedRoot && mergedRoot.content ? String(mergedRoot.content).trim().substring(0, 200) : root && root.content ? String(root.content).trim().substring(0, 200) : 'Decentralized social network';
        const imageUrl = `${origin}/images/logo.webp`;
        return <ContentGrid>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
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
                            {/* Community Hero Card */}
                            {(() => {
                                const displayCommunity = mergedRoot?.community || mergedRoot?.root_community || root?.community || root?.root_community || '';
                                const communityLower = displayCommunity.toLowerCase();
                                const isJoined = isJoinedCommunity(communityLower);
                                const isCommunityInProgress = isCommunityPending(communityLower);
                                const hasValidAccount = state.publicKey && state.publicKey !== 'guest';
                                return <CommunityHeroWrapper>
                                    <CommunityHeroCard role="region" aria-label="Community context">
                                        {/* Mobile: Top row with Back button and Follow button */}
                                        <CommunityHeroTopRow>
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
                                            <CommunityHeroMobileActions>
                                                {hasValidAccount && <CommunityMembershipButton
                                                    joined={isJoined}
                                                    pending={isCommunityInProgress}
                                                    statusLabel={formatCommunityStatus(communityLower)}
                                                    onToggle={() => handleCommunityJoinToggle(displayCommunity)}
                                                />}
                                                {renderHeaderLensPicker(displayCommunity)}
                                            </CommunityHeroMobileActions>
                                        </CommunityHeroTopRow>

                                        {/* Desktop: Back section */}
                                        <CommunityHeroBackSection>
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
                                        </CommunityHeroBackSection>

                                        {/* Desktop: Follow button */}
                                        <CommunityAction>
                                            {hasValidAccount && <CommunityMembershipButton
                                                joined={isJoined}
                                                pending={isCommunityInProgress}
                                                statusLabel={formatCommunityStatus(communityLower)}
                                                communityLabel={communityLabel(displayCommunity)}
                                                onToggle={() => handleCommunityJoinToggle(displayCommunity)}
                                            />}
                                            {renderHeaderLensPicker(displayCommunity)}
                                        </CommunityAction>
                                    </CommunityHeroCard>
                                </CommunityHeroWrapper>;
                            })()}
                            {(() => {
                                const visibleAnnotated = annotated.filter(p => (
                                    !p.hidden
                                    && !deletedPosts.has(p.post_id)
                                    && !isOptimisticallyCurationHidden(p)
                                ));
                                const ancestorDepthsMap = visibleAnnotated.map((_, idx) => getAncestorRailDepths(visibleAnnotated, idx));
                                return visibleAnnotated.map((post, idx) => {
                                    const normalizedPostId = String(post.post_id).toLowerCase();
                                    const isRoot = post.level === 0;
                                    const isCollapsed = !!(post.level > 0 && post.collapsed);
                                    const CardComponent = isRoot ? PostCard : CommentCard;
                                    const shouldFlash = isRoot ? rootFlash : !!post.flash;
                                    const displayLevel = post.level;
                                    const isHighlighted = !isRoot && normalizedHighlightId && normalizedPostId === normalizedHighlightId;
                                    const hasChildren = (post.comments || 0) > 0;
                                    const activeDepths = ancestorDepthsMap[idx];
                                    const editedAt = post.edited ? (post.edited_ts || post.edited_at) : null;
                                    const displayTs = editedAt || post.timestamp;
                                    const timeLabel = editedAt
                                        ? `edited ${formatElapsed(displayTs)} ago`
                                        : `${formatElapsed(displayTs)} ago`;
                                    return <div id={`comment-${normalizedPostId}`} key={post.post_id}>
                                        <CardComponent className={isHighlighted ? 'inbox-highlight' : undefined} $isFlash={shouldFlash} $isNew={!!(lastVisitTs && post.level > 0 && typeof post.timestamp === 'number' && post.timestamp > lastVisitTs)} $isCollapsed={isCollapsed} $level={displayLevel} $size={cardSize} $hasChildren={hasChildren} $activeDepths={activeDepths}>
                                            <ColumnFlex>
                                                {/* Mobile root post meta - two rows */}
                                                {isRoot && <MobileRootMeta>
                                                    <MobileRootMetaTop>
                                                        <MobileRootMetaPrimary>
                                                            {(() => {
                                                                const postCommunity = post.community || post.root_community || mergedRoot?.community || mergedRoot?.root_community || root?.community || root?.root_community || '';
                                                                return postCommunity ? <>
                                                                    <StyledCommunityLink to={communityPath(encodeURIComponent(postCommunity.toLowerCase()))}>{communityLabel(postCommunity)}</StyledCommunityLink>
                                                                    <MetaSeparator>·</MetaSeparator>
                                                                </> : null;
                                                            })()}
                                                            {renderAuthorLink(post)}
                                                        </MobileRootMetaPrimary>
                                                        <MobileRootMetaMenu>
                                                            {renderPostMenu(post)}
                                                        </MobileRootMetaMenu>
                                                    </MobileRootMetaTop>
                                                    <MobileRootMetaBottom>
                                                        <span>{timeLabel}</span>
                                                        {(() => {
                                                            const tagLabel = normalizeTag(post.tag || mergedRoot?.tag || root?.tag || '');
                                                            return tagLabel ? <>
                                                                <MetaSeparator>·</MetaSeparator>
                                                                <ContentTagBadge tag={tagLabel} size="md" />
                                                            </> : null;
                                                        })()}
                                                        {threadLocked && <>
                                                            <MetaSeparator>·</MetaSeparator>
                                                            <ThreadLockMark size="md" />
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
                                                <DesktopMetaInfoRow
                                                    $hideOnMobile={isRoot}
                                                    $clickable={!isRoot}
                                                    onClick={!isRoot ? (e) => {
                                                        // Ignore clicks that landed on interactive children
                                                        // (author/community links, menu button, tooltips with handlers).
                                                        if (e.target.closest && e.target.closest('a,button')) return;
                                                        toggleCollapsed(post.post_id, !!post.collapsed);
                                                    } : undefined}
                                                >
                                                    <MetaInfoRowLeft>
                                                        {!isRoot && (() => {
                                                            // Seed dicebear on the bech32 address
                                                            // (`user_id`) — stable across username
                                                            // changes and consistent with every
                                                            // other avatar surface in the app.
                                                            const seed = (post.user_id ? String(post.user_id) : '')
                                                                || (post.username && String(post.username).trim())
                                                                || 'anon';
                                                            // The visible halo is hardcoded inside
                                                            // CommentAvatar (2px desktop, 1px
                                                            // mobile) so we get pixel-perfect 4px
                                                            // cells on both breakpoints — see the
                                                            // size-constants comment above.
                                                            return <CommentAvatar
                                                                seed={seed}
                                                                size={COMMENT_AVATAR_SIZE_PX}
                                                                alt=""
                                                            />;
                                                        })()}
                                                        {/* Root posts match the feed card order:
                                                         * [community] · @author · time. Comments
                                                         * have no community chip (inherited). */}
                                                        {isRoot && (() => {
                                                            const postCommunity = post.community || post.root_community || mergedRoot?.community || mergedRoot?.root_community || root?.community || root?.root_community || '';
                                                            return postCommunity ? <>
                                                                <StyledCommunityLink to={communityPath(encodeURIComponent(postCommunity.toLowerCase()))}>{communityLabel(postCommunity)}</StyledCommunityLink>
                                                                <MetaSeparator>·</MetaSeparator>
                                                            </> : null;
                                                        })()}
                                                        {renderAuthorLink(post)}
                                                        <MetaSeparator>·</MetaSeparator>
                                                        <Tooltip $dotted data-tooltip={formatTimeStamp(displayTs)}>
                                                            {timeLabel}
                                                        </Tooltip>
                                                        {(() => {
                                                            const tagLabel = normalizeTag(post.tag || mergedRoot?.tag || root?.tag || '');
                                                            return tagLabel ? <>
                                                                <MetaSeparator>·</MetaSeparator>
                                                                <ContentTagBadge tag={tagLabel} size="md" />
                                                            </> : null;
                                                        })()}
                                                        {isRoot && threadLocked && <>
                                                            <MetaSeparator>·</MetaSeparator>
                                                            <ThreadLockMark size="md" />
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
                                                        {/* Collapse/expand chevron for comments — rendered AFTER the
                                              * content-warning tag so the chevron sits to the right of the
                                              * tag badge rather than between the timestamp and the tag. */}
                                                        {!isRoot && <>
                                                            <MetaSeparator>·</MetaSeparator>
                                                            <CollapseToggle
                                                                type="button"
                                                                onClick={() => toggleCollapsed(post.post_id, !!post.collapsed)}
                                                                aria-label={post.collapsed ? 'Expand' : 'Collapse'}
                                                            >
                                                                <span aria-hidden="true">{post.collapsed ? '+' : '\u2212'}</span>
                                                            </CollapseToggle>
                                                        </>}
                                                    </MetaInfoRowLeft>
                                                    <MetaInfoRowRight>
                                                        {renderPostMenu(post)}
                                                    </MetaInfoRowRight>
                                                </DesktopMetaInfoRow>

                                                {/* Title for root post */}
                                                {isRoot && <>
                                                    <RootTitleRow>
                                                        {(() => {
                                                            if (post && post.title) return post.title;
                                                            if (mergedRoot && mergedRoot.title) return mergedRoot.title;
                                                            if (root && root.title) return root.title;
                                                            return '';
                                                        })()}
                                                    </RootTitleRow>
                                                    <TitleDivider />
                                                </>}

                                                {/* Content — for the focused post, use mergedRoot so optimistic edits (media etc.) appear immediately */}
                                                {(() => {
                                                    const isFocusedPost = post.post_id === root?.post_id;
                                                    const baseDisplayPost = isFocusedPost && mergedRoot ? mergedRoot : post;
                                                    const displayPost = baseDisplayPost;
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
                                                                const mediaNode = mediaArr.length > 1 ? <MediaGallery
                                                                    items={mediaArr}
                                                                    variant={isRoot ? 'root_post' : undefined}
                                                                    mediaMeta={displayMediaMeta}
                                                                /> : <InlineMedia
                                                                    url={mediaArr[0]}
                                                                    variant={isRoot ? 'root_post' : undefined}
                                                                    mediaMeta={displayMediaMeta[0] || null}
                                                                />;
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
                                                                    <InlineMedia
                                                                        url={first}
                                                                        variant={isRoot ? 'root_post' : undefined}
                                                                        mediaMeta={displayMediaMeta[0] || null}
                                                                    />
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
                                            {ancestorsOmitted > 0 ? <>
                                                {ancestorsOmitted} older {ancestorsOmitted === 1 ? 'reply' : 'replies'} above.{' '}
                                            </> : null}
                                            Click{' '}
                                            <Link to={`/p/${actualRootPostId}`}>here</Link>
                                            {' '}to view the full thread.
                                        </StyledThreadReminder>}
                                        {isRoot && <CommentsHeaderRow>
                                            <CommentsHeaderTitle>
                                                Comments
                                                {typeof post.comments === 'number' && <CommentsHeaderCount>({post.comments})</CommentsHeaderCount>}
                                            </CommentsHeaderTitle>
                                        </CommentsHeaderRow>}
                                        {isRoot && annotated.filter(p => (
                                            !p.hidden
                                            && !deletedPosts.has(p.post_id)
                                            && !isOptimisticallyCurationHidden(p)
                                            && p.level > 0
                                        )).length === 0 && <VPStateBlock>
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
                                            // Keep shallow conversations inline; deep-link only once
                                            // indentation has reached the thread-depth cutoff.
                                            if (displayLevel < MIN_CONTINUE_THREAD_LEVEL) return null;
                                            // Don't show if this IS the focused comment (we're already viewing its thread)
                                            if (focusedCommentId && String(post.post_id).toLowerCase() === String(focusedCommentId).toLowerCase()) return null;
                                            // Don't show if no replies
                                            if ((post.comments || 0) <= 0) return null;
                                            // Check if children are loaded (either in post.children or state.posts)
                                            const stateChildren = state.posts?.[post.post_id]?.children;
                                            const hasLoadedChildren = (post.children && post.children.length > 0) || (stateChildren && stateChildren.length > 0);
                                            if (hasLoadedChildren) return null;
                                            return <ContinueThreadLink to={`/p/${post.post_id}`} $level={displayLevel} $activeDepths={activeDepths}>
                                                Continue this thread →
                                            </ContinueThreadLink>;
                                        })()}
                                    </div>;
                                });
                            })()}
                        </ModernPostFeed>
                    </MainContentWrapper>
                </FeedCol>
            </FeedRailRow>
            {renderMobileReplyOverlay()}
            {/**
              * Destructive-action dialogs (block post/user/community + report).
              * Rendered at the route root so a single `ConfirmDialog` owns
              * the modal UI for the whole page. The existing state machine
              * in `useViewPost` (`confirmBlockPost`, `confirmBlockUser`,
              * `confirmBlockCommunity`, `confirmReportPost`) drives visibility;
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
                // Resolve friendly labels for the Gift Mirage / Gift
                // Subscription dialogs. The hook (`useViewPost`) now
                // stashes the target's `username` on the confirm state
                // when it's available (see handleDonate /
                // handleGiftSubscription), so we prefer that first and
                // only fall back to the wallet address when the post is
                // from an anonymous author.
                const donateLabel = confirmDonate?.username
                    ? `@${confirmDonate.username}`
                    : (confirmDonate?.userId ? String(confirmDonate.userId) : 'this user');
                const giftSubLabel = confirmGiftSub?.username
                    ? `@${confirmGiftSub.username}`
                    : (confirmGiftSub?.userId ? String(confirmGiftSub.userId) : 'this user');
                const giftSubFeeLabel = subFeeLabel;
                const giftSubFeeUmirage = subFeeUmirage;
                const donateBusy = isSendPending(confirmDonate?.userId);
                const giftSubBusy = isSubscribePending(confirmGiftSub?.userId);
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
                        open={!!confirmBlockCommunity}
                        title={`Block ${communityLabel(confirmBlockCommunity?.community || 'community')}?`}
                        message="Posts in this community will stop appearing in your Home and discovery feeds."
                        confirmLabel="Block community"
                        confirmVariant="danger"
                        pending={isBlocking}
                        onConfirm={confirmBlockCommunityAction}
                        onCancel={cancelBlockCommunity}
                    />
                    {(() => {
                        const deletePostId = confirmDeletePost;
                        // A delete-confirm targets a comment whenever the
                        // selected id is anything other than the root post
                        // currently being viewed. `state.posts[id]` only
                        // holds UI state (replyOpen, flash, …) so we can
                        // not rely on `target` there. Comparing to the
                        // loaded `root.post_id` matches the same heuristic
                        // used for the comment menu items above.
                        const rootId = root && root.post_id
                            ? String(root.post_id).toLowerCase()
                            : '';
                        const isComment = !!(
                            deletePostId
                            && rootId
                            && String(deletePostId).toLowerCase() !== rootId
                        );
                        return (
                            <ConfirmDialog
                                open={!!confirmDeletePost}
                                title={isComment ? 'Mark comment as deleted?' : 'Mark post as deleted?'}
                                message={isComment
                                    ? 'This will permanently remove this comment from every feed. This action cannot be undone.'
                                    : 'This will permanently remove this post from every feed. This action cannot be undone.'}
                                confirmLabel={isComment ? 'Delete comment' : 'Delete post'}
                                confirmVariant="danger"
                                pending={isDeleting}
                                onConfirm={confirmDeletePostAction}
                                onCancel={cancelDeletePost}
                            />
                        );
                    })()}
                    <ConfirmDialog
                        open={!!confirmReportPost}
                        title="🚨 Report illegal content only"
                        message="Moderators only act on illegal content (CSAM, credible violent threats, doxxing, etc). Reports about the wrong community, untagged adult content, low quality, or anything you just don't like will be dismissed. Hide those from your feed with blocks and community filters."
                        confirmLabel="Report"
                        confirmVariant="warning"
                        pending={isReporting}
                        requireReason
                        reasonPlaceholder="Describe the illegality (e.g. CSAM, credible threat, doxxing)"
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
                    <GiftMirageDialog
                        open={!!confirmDonate}
                        recipientLabel={donateLabel}
                        amountRaw={donateAmount}
                        formatAmount={formatDonateAmount}
                        onAmountChange={handleDonateAmountChange}
                        pending={donateBusy}
                        confirmLabel={formatSendStatus(confirmDonate?.userId) || 'Send'}
                        userBalanceUmirage={userBalanceUmirage}
                        onConfirm={confirmDonateAction}
                        onCancel={cancelDonate}
                    />
                    <GiftSubscriptionDialog
                        open={!!confirmGiftSub}
                        recipientLabel={giftSubLabel}
                        level={confirmGiftSub?.level}
                        feeLabel={giftSubFeeLabel}
                        feeUmirage={giftSubFeeUmirage}
                        loading={!!confirmGiftSub?.loading}
                        expiryLabel={confirmGiftSub?.expiryLabel}
                        error={confirmGiftSub?.error}
                        pending={giftSubBusy}
                        confirmLabel={formatSubscribeStatus(confirmGiftSub?.userId) || 'Confirm'}
                        userBalanceUmirage={userBalanceUmirage}
                        onConfirm={confirmGiftSubAction}
                        onCancel={cancelGiftSub}
                    />
                    <GiveAwardDialog
                        open={!!confirmAward}
                        awardTypes={AWARD_TYPES}
                        getAwardCost={getAwardCost}
                        userBalanceUmirage={userBalanceUmirage}
                        isAwarding={isAwarding}
                        onPick={(awardName) => {
                            if (confirmAward?.postId) {
                                confirmAwardAction(confirmAward.postId, awardName);
                            }
                        }}
                        onCancel={() => setConfirmAward(null)}
                    />
                </>;
            })()}
        </ContentGrid>;
    } else {
        return <ContentGrid>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
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
                </FeedCol>
            </FeedRailRow>
        </ContentGrid>;
    }
}
export default ViewPostView;
