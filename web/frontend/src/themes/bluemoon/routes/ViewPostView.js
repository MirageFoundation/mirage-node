import React from "react";
import ReactDOM from "react-dom";
import styled from "styled-components";
import { Helmet } from "react-helmet-async";
import Button from "../components/Button.js";
import { Link, Navigate } from "react-router-dom";
import VoteSection from "../components/VoteSection.js";
import Sidebar from "../components/Sidebar.js";
import TopBar from "../components/TopBar.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed } from "../Layout";
import MarkdownRenderer from "../components/MarkdownRenderer.js";
import MarkdownEditor from "../components/MarkdownEditor.js";
import InlineMedia from "../components/InlineMedia.js";
import MediaGallery from "../components/MediaGallery.js";
import { MediaRow, MediaPreviewWrapper, MediaPreviewImage, MediaSpinner, MediaRemoveButton, MediaIconButton } from "../components/MediaAttachmentLayout.js";
import VideoPlayBadge from "../../../components/VideoPlayBadge";
import Storage from "../../../utils/Storage";
import { getVideoThumbnailUrl, getDownloadableMedia, mediaDownloadLabel, triggerMediaDownload } from "../../../utils/media";
import StickerPicker from "../components/StickerPicker.js";
import GifPicker from "../components/GifPicker.js";
import { getAuthorColor, getAuthorTooltip } from "../../../utils/tierColors";
import { Tooltip, tooltipStyles } from "../components/Tooltip.js";
import { useViewPost, pickCard, tagColors, formatTimeStamp, formatElapsed } from "../../../logic/useViewPost";
import { normalizeTag } from "../../../utils/ContentTags";
// Card-based container matching front page style (width aligned with ModernPostFeed)
// Supports $size prop ('compact' or 'large') to match feed view mode
// No margins - ModernPostFeed's gap handles spacing (matches CardView behavior)
const PostCard = styled.div`
    background: ${({
    theme
}) => pickCard(theme, 'card')};
    border: 1px solid ${({
    theme
}) => pickCard(theme, 'cardBorder')};
    border-radius: ${({
    $size
}) => $size === 'compact' ? '12px' : '16px'};
    display: flex;    
    min-height: auto;
    flex-direction: row;
    text-align: left;
    align-items: flex-start;
    padding: ${({
    $size
}) => $size === 'compact' ? '0.85rem' : '1.25rem'};
    /* No margins - gap is handled by ModernPostFeed via --card-gap CSS variable */
    margin: 0;
    transition: background 0.3s ease;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
    ${({
    $isNew,
    theme
}) => $isNew ? `background: ${theme.colors.panelAlt};` : ''}

    &:hover {
        background: ${({
    theme
}) => pickCard(theme, 'cardAlt')};
    }

    position: relative;

    @keyframes flashGlow {
        0% { box-shadow: 0 0 50px rgba(255, 255, 255, 0.9), 0 4px 20px rgba(0, 0, 0, 0.1); }
        100% { box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1); }
    }

    @media (max-width: 1000px) {
        padding: ${({
    $size
}) => $size === 'compact' ? '0.7rem' : '1rem'};
        border-radius: ${({
    $size
}) => $size === 'compact' ? '10px' : '12px'};
    }

    @media (max-width: 768px) {
        padding: 0.35rem 0.75rem;
        border-radius: 8px;
    }
`;

// Comment card with consistent, slightly tighter indentation per level
// Inherits $size prop from PostCard for compact/large mode
// Only margin-left for indentation - vertical spacing from ModernPostFeed gap
const CommentCard = styled(PostCard)`
    /* Each level indents by 1rem relative to the root card (tighter in compact mode) */
    margin-left: ${({
    $level,
    $size
}) => `${($size === 'compact' ? 0.75 : 1) * (Number($level) || 0)}rem`};
    padding: ${({
    $isCollapsed,
    $size
}) => $isCollapsed ? $size === 'compact' ? '0.35rem 0.75rem' : '0.5rem 1rem' : $size === 'compact' ? '0.7rem' : '1rem'};
    
    /* Persistent highlight for inbox-linked comments */
    &.inbox-highlight {
        border: 2px solid #FACC15 !important;
        background: rgba(250, 204, 21, 0.15) !important;
        box-shadow: 0 0 0 3px rgba(250, 204, 21, 0.3), 0 4px 20px rgba(0, 0, 0, 0.15) !important;
    }
    
    @media (max-width: 1000px) {
        margin-left: ${({
    $level,
    $size
}) => `${($size === 'compact' ? 0.45 : 0.6) * (Number($level) || 0)}rem`};
    }
`;
const StyledThreadReminder = styled.div`
    background: ${({
    theme
}) => pickCard(theme, 'card')};
    border: 1px solid ${({
    theme
}) => pickCard(theme, 'cardBorder')};
    border-radius: 12px;
    padding: 0.75rem 1rem;
    margin: 0.35rem 0;
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-weight: 500;    
    font-size: 0.7rem;
    
    a {
        font-size: inherit;
        color: ${({
    theme
}) => theme.colors.link};
        text-decoration: underline;
        font-weight: 600;

        &:hover {
            color: ${({
    theme
}) => theme.colors.linkHover};
        }
    }

    @media (max-width: 1000px) {
        margin: 0.25rem 0;
    }
`;
const ContinueThreadLink = styled(Link)`
    display: block;
    background: ${({
    theme
}) => pickCard(theme, 'cardAlt')};
    border: 1px solid ${({
    theme
}) => pickCard(theme, 'cardBorder')};
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    margin-left: ${({
    $level
}) => `${1 * (Number($level) || 0)}rem`};
    margin-top: 0.25rem;
    margin-bottom: 0.25rem;
    color: ${({
    theme
}) => theme.colors.link};
    font-size: 0.75rem;
    font-weight: 500;
    text-decoration: none;
    transition: all 0.2s ease;

    &:hover {
        background: ${({
    theme
}) => pickCard(theme, 'card')};
        color: ${({
    theme
}) => theme.colors.linkHover};
    }

    @media (max-width: 1000px) {
        margin-left: ${({
    $level
}) => `${0.6 * (Number($level) || 0)}rem`};
        font-size: 0.7rem;
        padding: 0.4rem 0.6rem;
    }
`;

// Topic hero container aligned with ModernPostFeed width
const TopicHeroWrapper = styled.div`
    width: 100%;
    margin: 0.5rem 0;
`;
const TopicHeroCard = styled.div`
    width: 100%;
    background: ${({
    theme
}) => pickCard(theme, 'cardAlt')};
    border: 1px solid ${({
    theme
}) => pickCard(theme, 'cardBorder')};
    border-radius: 12px;
    padding: 0.3rem 1rem;
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.14);
    display: flex;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;

    @media (max-width: 600px) {
        flex-direction: column;
        gap: 0.5rem;
        padding: 0.5rem 0.75rem;
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

// Title line inside the root post, above the content
const RootTitleRow = styled.div`
    color: ${({
    theme
}) => theme.colors.text};
    font-size: 0.9rem;
    font-weight: bold;
    margin-top: 0.25rem;
`;
const TitleDivider = styled.div`
    height: 1px;
    background: ${({
    theme
}) => theme.colors.border};
    margin: 0.5rem 0;
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

// Meta info row at top of card (topic, author, time, menu)
const MetaInfoRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.35rem;
    margin-bottom: 0.35rem;
    padding-bottom: 0.35rem;
    border-bottom: 1px solid ${({
    theme
}) => theme.colors.border};
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.65rem;
    font-weight: 600;
    line-height: 1.1;

    & a {
        color: ${({
    theme
}) => theme.colors.subtleText};
        text-decoration: none;
        font-weight: 600;
    }

    & a:hover {
        color: ${({
    theme
}) => theme.colors.text};
    }

    @media (max-width: 768px) {
        flex-wrap: wrap;
    }
`;
const MetaInfoRowLeft = styled.div`
    display: flex;
    align-items: center;
    gap: 0.35rem;
    flex-wrap: wrap;
`;
const MetaSeparator = styled.span`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.9rem;
    font-weight: 900;
`;

// Mobile root post meta - two rows: author+menu, then topic+time
const MobileRootMeta = styled.div`
    display: none;
    @media (max-width: 600px) {
        display: flex;
        flex-direction: column;
        gap: 0;
        margin-bottom: 0.35rem;
        padding-bottom: 0.35rem;
        border-bottom: 1px solid ${({
    theme
}) => theme.colors.border};
        color: ${({
    theme
}) => theme.colors.subtleText};
        font-size: 0.65rem;
        font-weight: 600;
        line-height: 1;
    }
`;
const MobileRootMetaTop = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    font-size: 0.75rem;
    line-height: 1;
    margin-bottom: -0.1rem;
    & a {
        font-size: inherit;
        line-height: inherit;
    }
`;
const MobileRootMetaBottom = styled.div`
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.65rem;
    line-height: 1;
    & a {
        color: ${({
    theme
}) => theme.colors.subtleText};
        text-decoration: none;
        font-weight: 600;
        font-size: inherit;
        line-height: inherit;
    }
    & a:hover {
        color: ${({
    theme
}) => theme.colors.text};
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

// Three-dots menu button
const MenuButton = styled.button`
    background: none;
    border: none;
    padding: 0.2rem;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: ${({
    theme
}) => theme.colors.subtleText};
    border-radius: 4px;
    transition: all 0.2s ease;

    &:hover {
        background: ${({
    theme
}) => theme.colors.panelAlt};
        color: ${({
    theme
}) => theme.colors.text};
    }

    svg {
        width: 18px;
        height: 18px;
    }
`;
const MenuContainer = styled.div`
    position: relative;
    display: inline-block;
`;
const MenuDropdown = styled.div`
    position: fixed;
    background: ${({
    theme
}) => theme.colors.panel};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    min-width: 180px;
    z-index: 99999;
    overflow: hidden;
`;
const MenuItem = styled.button`
    width: 100%;
    padding: 0.5rem 0.75rem;
    text-align: left;
    background: none;
    border: none;
    color: ${({
    theme
}) => theme.colors.text};
    font-size: 0.75rem;
    cursor: pointer;
    transition: background 0.2s ease;
    display: flex;
    align-items: center;
    gap: 0.5rem;

    &:hover {
        background: ${({
    theme
}) => theme.colors.panelAlt};
    }

    &:not(:last-child) {
        border-bottom: 1px solid ${({
    theme
}) => theme.colors.border};
    }

    &[data-danger="true"] {
        color: #ff6b6b;
    }
`;
const StyledContentArea = styled.div`
    margin-top: 0.25rem;
    margin-left: 0rem;
    color: ${({
    theme
}) => theme.colors.text};
    font-weight: normal;    
    font-size: 0.82rem;
    padding-left: 0rem;
    padding-right: 0rem;
    overflow-wrap: anywhere;
    word-break: break-word;
    white-space: normal;
    @media (max-width: 1000px) {
        font-size: 0.72rem;
    }
`;
const ColumnFlex = styled.div`
    width: 100%;
    display: flex;
    flex-direction: column;
    margin-bottom: 0;                 /* prevent trailing space below children */
    padding-bottom: 0;
`;
const MainContentWrapper = styled.div`
    width: 100%;
    min-width: 0;
    min-height: 120vh;
    overflow-x: hidden;
    box-sizing: border-box;
`;
const StyledReply = styled.div`
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 0.5rem;
    width: 100%;
    padding: 0.75rem;
    background: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: 10px;
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
    border-bottom: 1px solid ${({
    theme
}) => theme.colors.border};
    background: ${({
    theme
}) => theme.colors.panel};
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
    background: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: 8px;
    padding: 0.6rem 0.75rem;
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
const StyledSubmitButtonContainer = styled.div`
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: nowrap;
`;
const ReplyCounter = styled.span`
    font-size: 0.45rem;
    color: ${({
    $warn,
    theme
}) => $warn ? '#ff6b6b' : theme.colors.subtleText};
    line-height: 1.2;
    margin-left: 0.2rem;
    margin-top: -0.25em;
`;
const ReplyActionsRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    gap: 0.5rem;
    flex-wrap: nowrap;
`;
const ReplyErrorMessage = styled.div`
    background-color: rgba(220, 38, 38, 0.1);
    border: 1px solid #dc2626;
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    margin-top: 0.25rem;
    color: #dc2626;
    font-size: 0.7rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

// Action bar matching CardView style
const MetaRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.5rem;
    padding-top: 0.5rem;
    border-top: 1px solid ${({
    theme
}) => theme.colors.border};
    font-size: 0.7rem;
    font-weight: 600;
    color: ${({
    theme
}) => theme.colors.subtleText};
    line-height: 1;

    & a {
        color: ${({
    theme
}) => theme.colors.subtleText};
        text-decoration: none;
        font-size: 0.7rem;
        font-weight: 600;
        line-height: 1;
    }

    & a:hover {
        color: ${({
    theme
}) => theme.colors.text};
    }

    & span {
        font-size: 0.7rem;
        font-weight: 600;
        line-height: 1;
    }

    @media (max-width: 768px) {
        flex-wrap: wrap;
        font-size: 0.6rem;
        gap: 0.35rem;

        & a, & span {
            font-size: 0.6rem;
        }

        /* Hide "share" text on mobile, keep icon */
        .share-text {
            display: none;
        }
    }
`;
const MetaSeparatorAction = styled.span`
    font-size: 2.5rem;
    margin: 0 0.35rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-weight: 900;
    line-height: 1;

    @media (max-width: 768px) {
        font-size: 2rem;
        margin: 0 0.2rem;
    }
`;
const Icon = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    color: ${({
    theme
}) => theme.colors.subtleText};
    svg {
        width: 18px;
        height: 18px;
        fill: currentColor;
    }

    @media (max-width: 768px) {
        width: 14px;
        height: 14px;
        svg {
            width: 14px;
            height: 14px;
        }
    }
`;
const ActionButton = styled.a`
    &:visited { color: inherit; }
    &:hover, &:visited:hover {
        color: ${({
    theme
}) => theme.colors.text};
    }
    cursor: pointer;
    font-size: inherit;
    font-weight: 600;
    color: inherit;
    text-decoration: none;
    white-space: nowrap;
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
`;
const BlockErrorMessage = styled.div`
    background-color: rgba(220, 38, 38, 0.1);
    border: 1px solid #dc2626;
    border-radius: 3px;
    padding: 0.75rem 1rem;
    margin: 0.5rem 0.5rem 0.5rem 0;
    color: #dc2626;
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;
const BlockSuccessMessage = styled.div`
    background-color: rgba(34, 197, 94, 0.1);
    border: 1px solid #22c55e;
    border-radius: 3px;
    padding: 0.75rem 1rem;
    margin: 0.5rem 0.5rem 0.5rem 0;
    color: #22c55e;
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;
const BlockConfirmMessage = styled.div`
    background-color: rgba(251, 191, 36, 0.1);
    border: 1px solid #f59e0b;
    border-radius: 3px;
    padding: 0.75rem 1rem;
    margin: 0.5rem 0.5rem 0.5rem 0;
    color: #f59e0b;
    font-size: 0.9rem;
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
const ReportInput = styled.input`
    display: block;
    width: 100%;
    max-width: 100%;
    box-sizing: border-box;
    padding: 0.5rem;
    font-size: 0.8rem;
    color: ${({
    theme
}) => theme.colors.text};
    background-color: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: 4px;
`;

// Returns absolute local timestamp: YYYY-MM-DD HH:MM:SS

function ViewPostView({
    state,
    updatePost
}) {
    const {
        root,
        loading,
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
        shareMessages,
        setShareMessages,
        ancestorsOmitted,
        cardSize,
        theme,
        location,
        navigate,
        openBrowsingEnabled,
        nodeConfigLoaded,
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
        focusedCommentId,
        actualRootPostId,
        lastVisitTs,
        rootFlash,
        normalizedHighlightId,
        annotated,
        depthError
    } = useViewPost({
        state,
        updatePost
    });
    if (loading || error || depthError) {
        return <ContentGrid>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <BackButton onClick={goBackToFeed}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <line x1="19" y1="12" x2="5" y2="12"></line>
                            <polyline points="12 19 5 12 12 5"></polyline>
                        </svg>
                        Back
                    </BackButton>
                    {loading ? <PostCard $size={cardSize} style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        textAlign: 'center',
                        padding: '2rem',
                        gap: '0.35rem'
                    }}>
                        <span style={{
                            color: '#888'
                        }}>Loading post...</span>
                    </PostCard> : <PostCard $size={cardSize} style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        textAlign: 'center',
                        padding: '2rem',
                        gap: '0.5rem'
                    }}>
                        <span style={{
                            color: '#ff6b6b'
                        }}>{depthError || error}</span>
                    </PostCard>}
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
        // Show confirmation for this specific post
        if (confirmBlockPost === post.post_id) {
            return <BlockConfirmMessage>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.6rem',
                    width: '100%'
                }}>
                    <span style={{
                        whiteSpace: 'nowrap'
                    }}>🚫 Block this post?</span>
                    <ConfirmButtons style={{
                        marginLeft: 'auto',
                        flexShrink: 0,
                        width: 'auto'
                    }}>
                        <Button variant="warning" size="sm" onClick={confirmBlockPostAction} disabled={isBlocking}>
                            Block
                        </Button>
                        <Button variant="ghost" size="sm" onClick={cancelBlockPost}>Cancel</Button>
                    </ConfirmButtons>
                </div>
            </BlockConfirmMessage>;
        }
        if (confirmBlockUser?.postId === post.post_id) {
            return <BlockConfirmMessage>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.6rem',
                    width: '100%'
                }}>
                    <span style={{
                        whiteSpace: 'nowrap'
                    }}>🚫 Block {post.username || 'this user'}?</span>
                    <ConfirmButtons style={{
                        marginLeft: 'auto',
                        flexShrink: 0,
                        width: 'auto'
                    }}>
                        <Button variant="warning" size="sm" onClick={confirmBlockUserAction} disabled={isBlocking}>
                            Block
                        </Button>
                        <Button variant="ghost" size="sm" onClick={cancelBlockUser}>Cancel</Button>
                    </ConfirmButtons>
                </div>
            </BlockConfirmMessage>;
        }
        if (confirmBlockTopic?.postId === post.post_id) {
            return <BlockConfirmMessage>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.6rem',
                    width: '100%'
                }}>
                    <span style={{
                        whiteSpace: 'nowrap'
                    }}>🚫 Block #{confirmBlockTopic.topic}?</span>
                    <ConfirmButtons style={{
                        marginLeft: 'auto',
                        flexShrink: 0,
                        width: 'auto'
                    }}>
                        <Button variant="warning" size="sm" onClick={confirmBlockTopicAction} disabled={isBlocking}>
                            Block
                        </Button>
                        <Button variant="ghost" size="sm" onClick={cancelBlockTopic}>Cancel</Button>
                    </ConfirmButtons>
                </div>
            </BlockConfirmMessage>;
        }
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
        if (confirmReportPost === post.post_id) {
            return <BlockConfirmMessage>
                <span>🚨 Report illegal content only (CSAM, credible threats, doxxing, etc). Wrong topic, untagged adult content, low quality, or anything you just don't like will be ignored. To filter those out, follow a moderation agent. Agents are how moderation works on Mirage for everyone.</span>
                <ReportInput type="text" value={reportReason} onChange={e => setReportReason(e.target.value)} placeholder="Describe the illegality (e.g. CSAM, credible threat, doxxing)" maxLength={200} />
                <ConfirmButtons style={{
                    width: 'auto'
                }}>
                    <Button variant="warning" size="sm" onClick={confirmReportAction} disabled={isReporting}>
                        Report
                    </Button>
                    <Button variant="ghost" size="sm" onClick={cancelReport}>Cancel</Button>
                </ConfirmButtons>
            </BlockConfirmMessage>;
        }
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
                            {formatSendStatus(confirmDonate?.userId) || 'Confirm'}
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
        const mediaDownloads = getDownloadableMedia((() => {
            if (Array.isArray(post.media) && post.media.length > 0) return post.media;
            const raw = String(post.content || '');
            const idx = raw.indexOf('\n');
            const first = (idx >= 0 ? raw.slice(0, idx) : raw).trim();
            return /^https?:\/\//i.test(first) ? [first] : [];
        })());
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
                {mediaDownloads.map((d, i) => (
                    <MenuItem key={`dl-${i}`} onClick={() => { setOpenMenuId(null); triggerMediaDownload(d); }}>
                        {mediaDownloadLabel(d.kind, i, mediaDownloads.length, d.format)}
                    </MenuItem>
                ))}
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
                <MetaSeparatorAction>•</MetaSeparatorAction>
                <Link to="/signup" style={{
                    fontSize: '0.7rem',
                    color: 'inherit',
                    textDecoration: 'underline'
                }}>Sign in to participate</Link>
            </MetaRow>;
        }
        return <MetaRow>
            <VoteSection inline state={state} post={post} updatePost={updatePost} />
            <MetaSeparatorAction>•</MetaSeparatorAction>
            <ActionButton onClick={() => toggleReply(post.post_id)} style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.25rem'
            }}>
                <Icon aria-hidden="true">
                    <svg viewBox="0 0 24 24">
                        <path d="M4 4h16v12H5.17L4 17.17V4zm0-2a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H4z"></path>
                    </svg>
                </Icon>
                <span>reply</span>
            </ActionButton>
            <MetaSeparatorAction>•</MetaSeparatorAction>
            <ActionButton onClick={() => handleShare(post)} style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.25rem'
            }}>
                <Icon aria-hidden="true">
                    <svg viewBox="0 0 458.624 458.624">
                        <path d="M339.588,314.529c-14.215,0-27.456,4.133-38.621,11.239l-112.682-78.67c1.809-6.315,2.798-12.976,2.798-19.871 c0-6.896-0.989-13.557-2.798-19.871l109.64-76.547c11.764,8.356,26.133,13.286,41.662,13.286c39.79,0,72.047-32.257,72.047-72.047 C411.634,32.258,379.378,0,339.588,0c-39.79,0-72.047,32.257-72.047,72.047c0,5.255,0.578,10.373,1.646,15.308l-112.424,78.491 c-10.974-6.759-23.892-10.666-37.727-10.666c-39.79,0-72.047,32.257-72.047,72.047s32.256,72.047,72.047,72.047 c13.834,0,26.753-3.907,37.727-10.666l113.292,79.097c-1.629,6.017-2.514,12.34-2.514,18.872c0,39.79,32.257,72.047,72.047,72.047 c39.79,0,72.047-32.257,72.047-72.047C411.635,346.787,379.378,314.529,339.588,314.529z" fill="currentColor" />
                    </svg>
                </Icon>
                <span className="share-text">share</span>
            </ActionButton>
        </MetaRow>;
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
                    <div style={{
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
                            <Button type="button" variant="ghost" size="sm" onClick={() => closeReply(post.post_id)} disabled={isBusy}>Cancel</Button>
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

    // Redirect non-logged-in users to home (shows welcome banner)
    if (!isLoggedIn && !openBrowsingEnabled && nodeConfigLoaded) {
        return <Navigate to="/home" replace />;
    }
    if (root) {
        const origin = typeof window !== 'undefined' && window.location && window.location.origin ? window.location.origin : 'https://mirage.vote';
        const postUrl = `${origin}/p/${root.post_id}`;
        const postTitle = mergedRoot && mergedRoot.title ? String(mergedRoot.title).trim() : root && root.title ? String(root.title).trim() : 'Mirage';
        const postDescription = mergedRoot && mergedRoot.content ? String(mergedRoot.content).trim().substring(0, 200) : root && root.content ? String(root.content).trim().substring(0, 200) : 'Decentralized social network';
        const imageUrl = `${origin}/images/logo.webp`;
        return <ContentGrid>
            <Sidebar currentPath={location.pathname} state={state} />
            <MainContentWrapper>
                <TopBar state={state} />
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
                    <MobileHeader />
                    {/* Topic Hero Card */}
                    {(() => {
                        const displayTopic = mergedRoot?.topic || mergedRoot?.root_topic || root?.topic || root?.root_topic || '';
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
                                    {hasValidAccount && <Button variant={isTopicFollowing && topicFollowHover ? 'primaryDanger' : isTopicFollowing ? 'subtle' : 'primary'} size="sm" minWidth="follow" onMouseEnter={() => setTopicFollowHover(true)} onMouseLeave={() => setTopicFollowHover(false)} onClick={() => {
                                        if (!isTopicInProgress && displayTopic) {
                                            handleTopicFollowToggle(displayTopic);
                                        }
                                    }} disabled={isTopicInProgress} loading={isTopicInProgress}>
                                        {isTopicInProgress ? formatTopicStatus(topicLower) : isTopicFollowing ? topicFollowHover ? 'Unfollow' : 'Following' : 'Follow'}
                                    </Button>}
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
                                    {hasValidAccount && <Button variant={isTopicFollowing && topicFollowHover ? 'primaryDanger' : isTopicFollowing ? 'subtle' : 'primary'} size="sm" minWidth="follow" onMouseEnter={() => setTopicFollowHover(true)} onMouseLeave={() => setTopicFollowHover(false)} onClick={() => {
                                        if (!isTopicInProgress && displayTopic) {
                                            handleTopicFollowToggle(displayTopic);
                                        }
                                    }} disabled={isTopicInProgress} loading={isTopicInProgress}>
                                        {isTopicInProgress ? formatTopicStatus(topicLower) : isTopicFollowing ? topicFollowHover ? `Unfollow #${displayTopic}` : `Following #${displayTopic}` : `Follow #${displayTopic}`}
                                    </Button>}
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
                                            {!isRoot && <>
                                                <span onClick={() => toggleCollapsed(post.post_id, !!post.collapsed)} style={{
                                                    cursor: 'pointer',
                                                    fontWeight: 'bold'
                                                }} aria-label={post.collapsed ? 'Expand' : 'Collapse'}>
                                                    [{post.collapsed ? '+' : '−'}]
                                                </span>
                                                <MetaSeparator>·</MetaSeparator>
                                            </>}
                                            {renderAuthorLink(post)}
                                            <MetaSeparator>·</MetaSeparator>
                                            <Tooltip $dotted data-tooltip={formatTimeStamp(post.timestamp)}>
                                                {formatElapsed(post.timestamp)} ago
                                            </Tooltip>
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
                                {ancestorsOmitted > 0 ? <>
                                    {ancestorsOmitted} older {ancestorsOmitted === 1 ? 'reply' : 'replies'} above.{' '}
                                </> : null}
                                Click{' '}
                                <Link to={`/p/${actualRootPostId}`}>here</Link>
                                {' '}to view the full thread.
                            </StyledThreadReminder>}
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
        </ContentGrid>;
    } else {
        return <ContentGrid>
            <Sidebar currentPath={location.pathname} state={state} />
            <MainContentWrapper>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <BackButton onClick={goBackToFeed}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <line x1="19" y1="12" x2="5" y2="12"></line>
                            <polyline points="12 19 5 12 12 5"></polyline>
                        </svg>
                        Back
                    </BackButton>
                    <PostCard $size={cardSize} style={{
                        textAlign: 'center',
                        padding: '2rem'
                    }}>
                        <span style={{
                            color: '#ff6b6b'
                        }}>Unable to load post.</span>
                    </PostCard>
                </ModernPostFeed>
            </MainContentWrapper>
        </ContentGrid>;
    }
}
export default ViewPostView;