import React, { useState, useEffect, useRef, useMemo } from "react";
import ReactDOM from "react-dom";
import styled, { useTheme } from "styled-components";
import { Helmet } from 'react-helmet-async';
import Button from "../components/Button";
import { useLocation, Link, useNavigate, Navigate, useParams } from 'react-router-dom';
import VoteSection from "../components/VoteSection.js";
import * as tx from "../utils/tx.js";
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import MobileHeader from "../components/MobileHeader";
import { ContentGrid, ModernPostFeed } from "../styled/Layout";
import MarkdownRenderer from "../components/MarkdownRenderer";
import MarkdownEditor from "../components/MarkdownEditor";
import { MediaRow, MediaPreviewWrapper, MediaPreviewImage, MediaSpinner, MediaRemoveButton, MediaIconButton } from "../components/MediaAttachmentLayout";
import Api from '../lib/api';
import Storage from '../utils/Storage';
import { subscribe, unsubscribe, fetchFollowedTopics, invalidateCache as invalidateTopicsCache } from '../utils/Subscriptions';
import { fetchFollowedUsers, follow as followAuthor, unfollow as unfollowAuthor, invalidateCache as invalidateFollowCache } from '../utils/FollowUsers';
import { usePendingFollows } from '../utils/useFollowState';
import { uploadImage } from '../utils/ImageUpload';
import { sortComments } from '../utils/SortComments';
import StickerPicker from '../components/StickerPicker';
import GifPicker from '../components/GifPicker';
import { getCollapseThreshold, shouldAutoCollapse } from '../utils/Comments';
import { updateNotification } from '../utils/notifications';
import { darkColors as fallbackDarkColors } from "../styled/colors/dark";
import { lightColors as fallbackLightColors } from "../styled/colors/light";
import { getTierColor, getTierName } from "../utils/tierColors";

const pickCard = (theme, key) => {
    if (theme?.colors?.[key]) return theme.colors[key];
    const isLight = theme?.name === 'light';
    return (isLight ? fallbackLightColors : fallbackDarkColors)[key];
};

// Card-based container matching front page style (width aligned with ModernPostFeed)
// Supports $size prop ('compact' or 'large') to match feed view mode
// No margins - ModernPostFeed's gap handles spacing (matches CardView behavior)
const PostCard = styled.div`
    background: ${({ theme }) => pickCard(theme, 'card')};
    border: 1px solid ${({ theme }) => pickCard(theme, 'cardBorder')};
    border-radius: ${({ $size }) => $size === 'compact' ? '12px' : '16px'};
    display: flex;    
    min-height: auto;
    flex-direction: row;
    text-align: left;
    align-items: flex-start;
    padding: ${({ $size }) => $size === 'compact' ? '0.85rem' : '1.25rem'};
    /* No margins - gap is handled by ModernPostFeed via --card-gap CSS variable */
    margin: 0;
    transition: background 0.3s ease;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
    ${({ $isNew, theme }) => $isNew ? `background: ${theme?.colors?.panelAlt || '#2A2E33'};` : ''}

    &:hover {
        background: ${({ theme }) => pickCard(theme, 'cardAlt')};
    }

    position: relative;
    overflow: hidden;
    

    @keyframes flashOverlay {
        0% { opacity: 1; }
        100% { opacity: 0; }
    }
    
    @keyframes flashGlow {
        0% { box-shadow: 0 0 50px rgba(255, 255, 255, 0.9), 0 4px 20px rgba(0, 0, 0, 0.1); }
        100% { box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1); }
    }

    @media (max-width: 1000px) {
        padding: ${({ $size }) => $size === 'compact' ? '0.7rem' : '1rem'};
        border-radius: ${({ $size }) => $size === 'compact' ? '10px' : '12px'};
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
    margin-left: ${({ $level, $size }) => `${($size === 'compact' ? 0.75 : 1) * (Number($level) || 0)}rem`};
    padding: ${({ $isCollapsed, $size }) => $isCollapsed
        ? ($size === 'compact' ? '0.35rem 0.75rem' : '0.5rem 1rem')
        : ($size === 'compact' ? '0.7rem' : '1rem')};
    
    /* Persistent highlight for inbox-linked comments */
    &.inbox-highlight {
        border: 2px solid #FACC15 !important;
        background: rgba(250, 204, 21, 0.15) !important;
        box-shadow: 0 0 0 3px rgba(250, 204, 21, 0.3), 0 4px 20px rgba(0, 0, 0, 0.15) !important;
    }
    
    @media (max-width: 1000px) {
        margin-left: ${({ $level, $size }) => `${($size === 'compact' ? 0.45 : 0.6) * (Number($level) || 0)}rem`};
    }
`;

const StyledThreadReminder = styled.div`
    background: ${({ theme }) => pickCard(theme, 'card')};
    border: 1px solid ${({ theme }) => pickCard(theme, 'cardBorder')};
    border-radius: 12px;
    padding: 0.75rem 1rem;
    margin: 0.35rem 0;
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    font-weight: 500;    
    font-size: 0.7rem;
    
    a {
        font-size: inherit;
        color: ${({ theme }) => theme?.colors?.link || '#FFFFFF'};
        text-decoration: underline;
        font-weight: 600;

        &:hover {
            color: ${({ theme }) => theme?.colors?.linkHover || '#CCCCCC'};
        }
    }

    @media (max-width: 1000px) {
        margin: 0.25rem 0;
    }
`;

const ContinueThreadLink = styled(Link)`
    display: block;
    background: ${({ theme }) => pickCard(theme, 'cardAlt')};
    border: 1px solid ${({ theme }) => pickCard(theme, 'cardBorder')};
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    margin-left: ${({ $level }) => `${1 * (Number($level) || 0)}rem`};
    margin-top: 0.25rem;
    margin-bottom: 0.25rem;
    color: ${({ theme }) => theme?.colors?.link || '#64B5F6'};
    font-size: 0.75rem;
    font-weight: 500;
    text-decoration: none;
    transition: all 0.2s ease;

    &:hover {
        background: ${({ theme }) => pickCard(theme, 'card')};
        color: ${({ theme }) => theme?.colors?.linkHover || '#90CAF9'};
    }

    @media (max-width: 1000px) {
        margin-left: ${({ $level }) => `${0.6 * (Number($level) || 0)}rem`};
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
    background: ${({ theme }) => pickCard(theme, 'cardAlt')};
    border: 1px solid ${({ theme }) => pickCard(theme, 'cardBorder')};
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
    color: ${({ theme }) => theme?.colors?.text || '#FFFFFF'};
    font-size: 0.9rem;
    font-weight: bold;
    margin-top: 0.25rem;
`;

const TitleDivider = styled.div`
    height: 1px;
    background: ${({ theme }) => theme?.colors?.border || '#9ca3af'};
    margin: 0.5rem 0;
`;

// Reuse the same visual style as topic links in the feed
// BreadcrumbLink removed (unused)

const StyledProfileLink = styled(Link)`
    color: ${({ $tierColor, theme }) => $tierColor || theme?.colors?.link || '#FFFFFF'} !important;
    text-decoration: none;
    font-weight: bold;
    position: relative;

    &:hover {
        color: ${({ $tierColor, theme }) => $tierColor || theme?.colors?.linkHover || '#CCCCCC'} !important;
    }

    &::after {
        content: attr(data-tooltip);
        position: absolute;
        bottom: 100%;
        left: 0;
        margin-bottom: 0.3rem;
        background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
        border: 1px solid ${({ theme }) => theme?.colors?.border || '#555'};
        color: ${({ theme }) => theme?.colors?.text || '#eee'};
        padding: 0.5rem 0.75rem;
        border-radius: 4px;
        font-size: 0.7rem;
        font-weight: normal;
        white-space: nowrap;
        z-index: 1000;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.15s ease;
    }

    &[data-tooltip]:hover::after {
        opacity: 1;
    }
`;

const StyledTopicLink = styled(Link)`
    color: ${({ theme }) => theme?.colors?.link || '#FFFFFF'};
    text-decoration: none;
    font-weight: bold;
    text-transform: lowercase;

    &:hover {
        color: ${({ theme }) => theme?.colors?.linkHover || '#CCCCCC'};
    }
`;

const BackButton = styled.button`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: transparent;
    border: none;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    cursor: pointer;
    font-size: 0.9rem;
    font-weight: 600;
    padding: 0.5rem 0.5rem 0.5rem 0;
    margin-bottom: 0.25rem;
    transition: color 0.2s ease;

    &:hover {
        color: ${({ theme }) => theme?.colors?.text || '#FFF'};
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
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#9ca3af'};
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.65rem;
    font-weight: 600;
    line-height: 1.1;

    & a {
        color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
        text-decoration: none;
        font-weight: 600;
    }

    & a:hover {
        color: ${({ theme }) => theme?.colors?.text || '#FFF'};
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
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
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
        border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#9ca3af'};
        color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
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
        color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
        text-decoration: none;
        font-weight: 600;
        font-size: inherit;
        line-height: inherit;
    }
    & a:hover {
        color: ${({ theme }) => theme?.colors?.text || '#FFF'};
    }
`;

// Desktop version - hide on mobile for root posts
const DesktopMetaInfoRow = styled(MetaInfoRow)`
    @media (max-width: 600px) {
        display: ${({ $hideOnMobile }) => $hideOnMobile ? 'none' : 'flex'};
    }
`;

const tagColors = {
    porn: { bg: 'rgba(236, 72, 153, 0.18)', border: 'rgba(236, 72, 153, 0.50)', text: '#ec4899' }, // pink
    violence: { bg: 'rgba(185, 28, 28, 0.18)', border: 'rgba(185, 28, 28, 0.50)', text: '#b91c1c' }, // deep red
    sensitive: { bg: 'rgba(109, 40, 217, 0.18)', border: 'rgba(109, 40, 217, 0.50)', text: '#6d28d9' }, // purple
    // Default: light neutral pill that stays legible on both light and dark backgrounds.
    default: { bg: '#e5e7eb', border: '#cbd5e1', text: '#0f172a' },
};

const TagBadge = styled.span`
    display: inline-flex;
    align-items: center;
    padding: 0.1rem 0.45rem;
    border-radius: 999px;
    background: ${({ $tag }) => (tagColors[$tag]?.bg || tagColors.default.bg)};
    color: ${({ $tag }) => (tagColors[$tag]?.text || tagColors.default.text)};
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: lowercase;
    border: 1px solid ${({ $tag }) => (tagColors[$tag]?.border || tagColors.default.border)};
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
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    border-radius: 4px;
    transition: all 0.2s ease;

    &:hover {
        background: ${({ theme }) => theme?.colors?.panelAlt || '#333'};
        color: ${({ theme }) => theme?.colors?.text || '#FFF'};
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
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#9ca3af'};
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
    color: ${({ theme }) => theme?.colors?.text || '#FFF'};
    font-size: 0.75rem;
    cursor: pointer;
    transition: background 0.2s ease;
    display: flex;
    align-items: center;
    gap: 0.5rem;

    &:hover {
        background: ${({ theme }) => theme?.colors?.panelAlt || '#333'};
    }

    &:not(:last-child) {
        border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#9ca3af'};
    }

    &[data-danger="true"] {
        color: #ff6b6b;
    }
`;

const StyledContentArea = styled.div`
    margin-top: 0.25rem;
    margin-left: 0rem;
    color: ${({ theme }) => theme?.colors?.text || '#CCCCCC'};
    font-weight: normal;    
    font-size: 0.9rem;
    padding-left: 0rem;
    padding-right: 0rem;
    overflow-wrap: anywhere;
    word-break: break-word;
    white-space: normal;
    @media (max-width: 1000px) {
        font-size: 0.75rem;  /* slightly smaller comment text on mobile */
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
    background: ${({ theme }) => theme?.colors?.panelAlt || '#2A2E33'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#9ca3af'};
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
        background: ${({ theme }) => theme?.colors?.bg || '#1a1a1a'};
        overflow-y: auto;
        -webkit-overflow-scrolling: touch;
    }
`;

const MobileReplyHeader = styled.div`
    display: flex;
    align-items: center;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#9ca3af'};
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
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
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
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
    background: ${({ theme }) => theme?.colors?.panelAlt || '#f1f5f9'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#d1d5db'};
    border-radius: 8px;
    padding: 0.6rem 0.75rem;
`;

const MobileReplyPostMeta = styled.div`
    font-size: 0.65rem;
    color: ${({ theme }) => theme?.colors?.mutedText || '#718096'};
    margin-bottom: 0.3rem;
    display: flex;
    align-items: center;
    gap: 0.25rem;
`;

const MobileReplyPostContent = styled.div`
    font-size: 0.8rem;
    color: ${({ theme }) => theme?.colors?.text || '#1a202c'};
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
    color: ${({ $warn, theme }) => $warn ? '#ff6b6b' : (theme?.colors?.subtleText || '#888')};
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
    border-top: 1px solid ${({ theme }) => theme?.colors?.border || '#9ca3af'};
    font-size: 0.7rem;
    font-weight: 600;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    line-height: 1;

    & a {
        color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
        text-decoration: none;
        font-size: 0.7rem;
        font-weight: 600;
        line-height: 1;
    }

    & a:hover {
        color: ${({ theme }) => theme?.colors?.text || '#FFF'};
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
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
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
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
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
        color: ${({ theme }) => theme?.colors?.text || '#FFF'};
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



const TooltipText = styled.div`
  visibility: hidden;
  background-color: black;
  color: white;
  text-align: center;
  border-radius: 6px;
  padding: 0.1rem 0.25rem;
  position: absolute;
  z-index: 9999;
  bottom: 100%;
  left: 50%;
  opacity: 0.5;
  transition: opacity 0.3s;
  font-size: inherit;
  white-space: nowrap;
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
    color: ${({ theme }) => theme?.colors?.text || '#CCCCCC'};
    background-color: ${({ theme }) => theme?.colors?.panelAlt || '#333'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#555'};
    border-radius: 4px;
`;

const TooltipContainer = styled.div`
  position: relative;
  display: inline-block;
  font-size: inherit;
  text-decoration: underline;
  text-decoration-style: dotted;
  white-space: nowrap;          /* keep username intact, never split */

  &:hover ${TooltipText} {
    visibility: visible;
    opacity: 1;
    font-weight: bold;      
    font-size: 0.6rem;
  }
`;

// Returns absolute local timestamp: YYYY-MM-DD HH:MM:SS
const formatTimeStamp = (utcTimestamp) => {
    if (utcTimestamp === undefined) return "n/a";

    const utcDate = new Date(utcTimestamp * 1000);
    const localDate = new Date(utcDate.getTime() - (utcDate.getTimezoneOffset() * 60000));

    const isoDate = localDate.toISOString().slice(0, 10);
    const isoTime = localDate.toISOString().slice(11, 19);
    return `${isoDate} ${isoTime}`;
};

// Returns short relative time like 5s, 12m, 3h, 2d, 1y
const formatElapsed = (utcTimestamp) => {
    if (!utcTimestamp && utcTimestamp !== 0) return "0s";
    let seconds = Math.floor((Date.now() / 1000) - utcTimestamp);
    if (!isFinite(seconds) || isNaN(seconds) || seconds < 0) seconds = 0;
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    if (seconds < 31536000) return `${Math.floor(seconds / 86400)}d`;
    return `${Math.floor(seconds / 31536000)}y`;
};


// Module-level cache for highlight ID (survives React Strict Mode double-mount)
let _cachedHighlightPostId = null;
let _highlightConsumed = false;

function ViewPostView({ state, updatePost }) {
    const [root, setRoot] = useState({});
    const [children, setChildren] = useState([]);
    const [loading, setLoading] = useState(true);
    const [blockError, setBlockError] = useState('');
    const [blockSuccess, setBlockSuccess] = useState('');
    const [isBlocking, setIsBlocking] = useState(false);
    const [confirmBlockPost, setConfirmBlockPost] = useState(null);
    const [confirmBlockUser, setConfirmBlockUser] = useState(null); // { userId, postId }
    const [confirmDeletePost, setConfirmDeletePost] = useState(null);
    const [isDeleting, setIsDeleting] = useState(false);
    const [deleteMessages, setDeleteMessages] = useState({}); // { postId: { type: 'success'|'error', message: string } }
    const [deletedPosts, setDeletedPosts] = useState(new Set()); // Track successfully deleted posts to hide them
    const [confirmSuspendQuests, setConfirmSuspendQuests] = useState(null); // { userId, postId }
    const [isSuspending, setIsSuspending] = useState(false);
    const [suspendDuration, setSuspendDuration] = useState(7); // days, or 0 for permanent
    const [suspendSuccess, setSuspendSuccess] = useState({}); // { postId: message }
    const [confirmUnsuspendQuests, setConfirmUnsuspendQuests] = useState(null); // { userId, postId }
    const [isUnsuspending, setIsUnsuspending] = useState(false);
    const [userSuspendedMap, setUserSuspendedMap] = useState({}); // { userId: true/false/null }
    const [confirmDonate, setConfirmDonate] = useState(null); // { userId, postId }
    const [donateAmount, setDonateAmount] = useState("1");
    const [isDonating, setIsDonating] = useState(false);
    const [donateMessages, setDonateMessages] = useState({}); // { postId: { type: 'success'|'error', message: string } }
    const [confirmReportPost, setConfirmReportPost] = useState(null);
    const [reportReason, setReportReason] = useState("");
    const [isReporting, setIsReporting] = useState(false);
    const [reportMessages, setReportMessages] = useState({}); // { postId: { type: 'success'|'error', message: string } }
    const [error, setError] = useState(null);
    const [shareMessages, setShareMessages] = useState({}); // { postId: { type: 'success', message } }
    const [showContext, setShowContext] = useState(false);
    const [contextComments, setContextComments] = useState([]);
    // When viewing a comment, store the actual root post (for display at top)
    const [actualRootPost, setActualRootPost] = useState(null);
    // Card size state to match feed view mode (compact or large)
    const [cardSize, setCardSize] = useState(() => {
        try {
            return Storage.load('card_size', 'compact');
        } catch (_) {
            return 'compact';
        }
    });
    const theme = useTheme();
    const location = useLocation();
    const navigate = useNavigate();
    const [configUpdateTrigger, setConfigUpdateTrigger] = useState(0);
    const [subToggleTick, setSubToggleTick] = useState(0);
    useEffect(() => { }, [subToggleTick]);
    const [nodeConfigTick, setNodeConfigTick] = useState(0);
    useEffect(() => {
        const handler = () => setNodeConfigTick(prev => prev + 1);
        window.addEventListener('nodeConfigUpdated', handler);
        return () => window.removeEventListener('nodeConfigUpdated', handler);
    }, []);
    const nodeConfig = useMemo(() => {
        void nodeConfigTick;
        try {
            const raw = localStorage.getItem('nodeConfig');
            return raw ? JSON.parse(raw) : null;
        } catch (_) {
            return null;
        }
    }, [nodeConfigTick]);
    const questsEnabled = Boolean(nodeConfig?.quests_enabled) && Boolean(nodeConfig?.quest_payouts_enabled);

    // Capture "opened from feed" info synchronously (before effects) so the Back button can
    // reliably return to the originating feed route (including /t/:topic).
    const openedFromFeedInfoRef = useRef(null);
    if (openedFromFeedInfoRef.current === null) {
        openedFromFeedInfoRef.current = (() => {
            try {
                if (typeof window === 'undefined' || !window.sessionStorage) return { opened: false, topic: null };
                const raw = window.sessionStorage.getItem('mirage_post_nav_source');
                if (!raw) return { opened: false, topic: null };
                const parsed = JSON.parse(raw);
                if (parsed?.source !== 'feed') return { opened: false, topic: null };
                const at = Number(parsed?.at || 0);
                if (!Number.isFinite(at) || at <= 0) return { opened: false, topic: null };
                const ageMs = Date.now() - at;
                if (ageMs < 0 || ageMs > 10000) return { opened: false, topic: null };
                const topic = typeof parsed?.topic === 'string' ? parsed.topic : null;
                return { opened: true, topic: topic || null };
            } catch (_) {
                return { opened: false, topic: null };
            }
        })();
    }

    // Mobile detection for focused reply mode
    const [isMobile, setIsMobile] = useState(() => {
        if (typeof window === 'undefined') return false;
        try { return window.innerWidth <= 600; } catch (_) { return false; }
    });

    useEffect(() => {
        const updateIsMobile = () => {
            try { setIsMobile(window.innerWidth <= 600); } catch (_) { }
        };
        window.addEventListener('resize', updateIsMobile);
        window.addEventListener('orientationchange', updateIsMobile);
        return () => {
            window.removeEventListener('resize', updateIsMobile);
            window.removeEventListener('orientationchange', updateIsMobile);
        };
    }, []);

    // Listen for card size changes from other views (MainView settings dropdown)
    useEffect(() => {
        const handleSettingsUpdated = (e) => {
            try {
                if (e && e.detail && typeof e.detail.cardSize !== 'undefined') {
                    setCardSize(e.detail.cardSize);
                    return;
                }
                // Fallback: re-read from storage
                const size = Storage.load('card_size', 'compact');
                setCardSize(size);
            } catch (_) { }
        };
        window.addEventListener('settingsUpdated', handleSettingsUpdated);
        return () => window.removeEventListener('settingsUpdated', handleSettingsUpdated);
    }, []);

    // Set CSS custom properties for card gap based on compact mode (matches CardView)
    useEffect(() => {
        const isCompactMode = cardSize === 'compact';
        const root = document.documentElement;
        const gap = isCompactMode ? '0.5rem' : '1.0rem';
        const gapMobile = isCompactMode ? '0.25rem' : '0.5rem';
        root.style.setProperty('--card-gap', gap);
        root.style.setProperty('--card-gap-mobile', gapMobile);
    }, [cardSize]);

    // Scroll to top instantly when navigating to this view
    useEffect(() => {
        window.scrollTo({ top: 0, behavior: 'instant' });
    }, [location.search]);

    // If this post wasn't opened from the feed, clear any stale "came from feed" flag.
    // We only want feed restoration for browser-back when the user navigated feed -> view_post.
    useEffect(() => {
        const openedFromFeed = openedFromFeedInfoRef.current?.opened === true;

        try {
            sessionStorage.removeItem('mirage_post_nav_source');
        } catch (_) { }

        if (!openedFromFeed) {
            try {
                sessionStorage.removeItem('mirage_came_from_feed');
            } catch (_) { }
        }
    }, []); // Only run on mount

    const goBackToFeed = () => {
        try {
            // Prefer browser back when we actually navigated here from a feed (/home, /following, /t/:topic).
            // This preserves scroll restoration logic in MainView.
            if (openedFromFeedInfoRef.current?.opened === true) {
                navigate(-1);
                return;
            }

            if (typeof window !== 'undefined' && window.history.length > 1) {
                try {
                    const cameFrom = window.sessionStorage.getItem('mirage_post_referrer');
                    if (cameFrom === 'search' || cameFrom === 'profile') {
                        window.sessionStorage.removeItem('mirage_post_referrer');
                        navigate(-1);
                        return;
                    }
                } catch (_) { }
            }

            const last = Storage.load('last_feed_route', '/home');
            const fallback = (typeof last === 'string' && last.startsWith('/')) ? last : '/home';
            const target = fallback;

            const inferTopicIntent = (route) => {
                try {
                    if (openedFromFeedInfoRef.current?.topic) return openedFromFeedInfoRef.current.topic;
                    if (route === '/home') return 'home';
                    if (route === '/following') return 'following';
                    if (!route.startsWith('/t/')) return null;

                    const withoutPrefix = route.slice(3); // after "/t/"
                    const segment = withoutPrefix.split('?')[0].split('#')[0].split('/')[0];
                    const trimmed = String(segment || '').trim();
                    if (!trimmed) return null;
                    return decodeURIComponent(trimmed);
                } catch (_) {
                    return null;
                }
            };

            const intendedTopic = inferTopicIntent(target);
            try {
                if (typeof window !== 'undefined' && window.sessionStorage) {
                    if (intendedTopic) {
                        window.sessionStorage.setItem('mirage_restore_feed', JSON.stringify({
                            topic: intendedTopic,
                            at: Date.now(),
                        }));
                    }
                }
            } catch (_) { }
            navigate(target, { replace: true });
        } catch (_) {
            navigate('/home', { replace: true });
        }
    };
    const viewerAddress = Storage.load('publicKey', '') || 'guest';
    const [followedAuthorsSet, setFollowedAuthorsSet] = useState(new Set());
    const [followedTopicsSet, setFollowedTopicsSet] = useState(new Set());
    const [topicFollowHover, setTopicFollowHover] = useState(false);
    const { isTopicPending, isUserPending, formatTopicStatus, formatUserStatus } = usePendingFollows();

    // Menu state for three-dots dropdown
    const [openMenuId, setOpenMenuId] = useState(null);
    const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
    const menuButtonRefs = useRef({});
    const menuDropdownRef = useRef({});

    // Close menu when clicking outside
    useEffect(() => {
        if (!openMenuId) return;
        const handleClickOutside = (event) => {
            const dropdown = menuDropdownRef.current;
            const button = menuButtonRefs.current[openMenuId];
            if (dropdown && !dropdown.contains(event.target) && button && !button.contains(event.target)) {
                setOpenMenuId(null);
            }
        };
        const handleScroll = () => setOpenMenuId(null);
        document.addEventListener('mousedown', handleClickOutside);
        window.addEventListener('scroll', handleScroll, true);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            window.removeEventListener('scroll', handleScroll, true);
        };
    }, [openMenuId]);

    useEffect(() => {
        let cancelled = false;
        const loadFollowed = async () => {
            if (!viewerAddress || viewerAddress === 'guest') return;
            try {
                const [authors, topics] = await Promise.all([
                    fetchFollowedUsers(viewerAddress),
                    fetchFollowedTopics(viewerAddress)
                ]);
                if (!cancelled) {
                    setFollowedAuthorsSet(new Set(authors.map(a => a.toLowerCase())));
                    setFollowedTopicsSet(new Set(topics.map(t => t.toLowerCase())));
                }
            } catch (_) { }
        };
        loadFollowed();
        return () => { cancelled = true; };
    }, [viewerAddress]);

    const isFollowingAuthor = (addr) => {
        const a = String(addr || '').trim().toLowerCase();
        return followedAuthorsSet.has(a);
    };

    const handleFollowToggle = async (authorAddr) => {
        const author = String(authorAddr || '').trim().toLowerCase();
        if (!author || isUserPending(author)) return;

        const wasFollowing = isFollowingAuthor(author);
        try {
            if (wasFollowing) {
                await unfollowAuthor(viewerAddress, author);
                setFollowedAuthorsSet(prev => {
                    const next = new Set(prev);
                    next.delete(author);
                    return next;
                });
                updateNotification(`Unfollowed user ${author.slice(0, 12)}...`, 3);
            } else {
                await followAuthor(viewerAddress, author);
                setFollowedAuthorsSet(prev => new Set([...prev, author]));
                updateNotification(`Now following user ${author.slice(0, 12)}...`, 3);
            }
            invalidateFollowCache();
            setSubToggleTick(x => x + 1);
        } catch (e) {
            console.error('[ViewPostView] Follow toggle error:', e);
        }
    };

    const isSubscribedTopic = (topic) => {
        return followedTopicsSet.has(String(topic || '').toLowerCase());
    };

    const handleTopicFollowToggle = async (topic) => {
        const t = String(topic || '').trim().toLowerCase();
        if (!t || isTopicPending(t)) return;

        const wasSubscribed = isSubscribedTopic(topic);
        // Optimistic update
        if (wasSubscribed) {
            setFollowedTopicsSet(prev => {
                const next = new Set(prev);
                next.delete(t);
                return next;
            });
        } else {
            setFollowedTopicsSet(prev => new Set([...prev, t]));
        }
        try {
            if (wasSubscribed) {
                await unsubscribe(viewerAddress, topic);
                updateNotification(`Unfollowed topic #${t}`, 3);
            } else {
                await subscribe(viewerAddress, topic);
                updateNotification(`Now following topic #${t}`, 3);
            }
            invalidateTopicsCache();
            setSubToggleTick(x => x + 1);
        } catch (e) {
            console.error('[ViewPostView] Topic follow toggle error:', e);
            // Revert on error
            if (wasSubscribed) {
                setFollowedTopicsSet(prev => new Set([...prev, t]));
            } else {
                setFollowedTopicsSet(prev => {
                    const next = new Set(prev);
                    next.delete(t);
                    return next;
                });
            }
        }
    };
    const [replyDragState, setReplyDragState] = useState({}); // { postId: boolean }
    const [replyUploadProgress, setReplyUploadProgress] = useState({}); // { postId: number }
    const [replyEditorUpload, setReplyEditorUpload] = useState({}); // { postId: api }
    const [replyIsUploading, setReplyIsUploading] = useState({}); // { postId: boolean }
    const [replyAttachedType, setReplyAttachedType] = useState({}); // { postId: 'image'|'video' }
    const [replyAttachedUrl, setReplyAttachedUrl] = useState({}); // { postId: string }
    const [replyThumbLoading, setReplyThumbLoading] = useState({}); // { postId: boolean }
    const [replySubmitError, setReplySubmitError] = useState({}); // { postId: string }
    const [replySubmitStartTime, setReplySubmitStartTime] = useState({}); // { postId: number }
    const [replyElapsedTime, setReplyElapsedTime] = useState({}); // { postId: number }
    const [replySubmitStatus, setReplySubmitStatus] = useState({}); // { postId: 'idle'|'solving'|'submitting'|'verifying' }
    const replyErrorClearTimeoutRef = useRef({}); // { postId: timeoutId }
    const mobileReplyOverlayRef = useRef(null);

    // Listen for chain config updates and fetch lazily if not cached
    useEffect(() => {
        const handleConfigUpdate = () => {
            setConfigUpdateTrigger(prev => prev + 1);
        };

        window.addEventListener('chainConfigUpdated', handleConfigUpdate);
        window.addEventListener('userStatusUpdated', handleConfigUpdate);

        // Fetch chain config if not cached (e.g. first visit after login)
        if (!localStorage.getItem('chainConfig')) {
            Api.get('get_chain_config', undefined, { timeoutMs: 10000 })
                .then((cfg) => { if (cfg) try { tx.cacheChainConfig(cfg); } catch (_) { } })
                .catch(() => { });
        }

        return () => {
            window.removeEventListener('chainConfigUpdated', handleConfigUpdate);
            window.removeEventListener('userStatusUpdated', handleConfigUpdate);
        };
    }, []);

    // Update elapsed time for any active reply submissions
    useEffect(() => {
        const activePostIds = Object.keys(replySubmitStartTime).filter(
            id => replySubmitStartTime[id] && state.posts[id]?.replyBusy
        );
        if (activePostIds.length === 0) return;

        const interval = setInterval(() => {
            setReplyElapsedTime(prev => {
                const next = { ...prev };
                for (const id of activePostIds) {
                    const start = replySubmitStartTime[id];
                    if (start) {
                        next[id] = (Date.now() - start) / 1000;
                    }
                }
                return next;
            });
        }, 100);
        return () => clearInterval(interval);
    }, [replySubmitStartTime, state.posts]);

    // Scroll mobile reply overlay to bottom (reply box) when opened
    useEffect(() => {
        if (mobileReplyOverlayRef.current) {
            requestAnimationFrame(() => {
                if (mobileReplyOverlayRef.current) {
                    mobileReplyOverlayRef.current.scrollTop = mobileReplyOverlayRef.current.scrollHeight;
                }
            });
        }
    }, [state.posts, isMobile]);

    // Get content size limits from chain config + user level
    const limits = React.useMemo(() => {
        try {
            const chain = JSON.parse(localStorage.getItem('chainConfig') || '{}');
            const userLevel = parseInt(Storage.load('user_level', '0'));
            const tiers = chain.tiers || [];
            const tierIndex = Math.min(userLevel, tiers.length - 1);
            const tier = tiers[tierIndex] || {};

            return {
                maxContent: parseInt(tier.max_content_length) || 1000,
                willPayFee: userLevel >= 1
            };
        } catch (e) {
            console.error('[ViewPostView] Error calculating limits:', e);
            return { maxContent: 1000, willPayFee: false };
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [state.user_balance, configUpdateTrigger]);

    const closeReply = (postId) => {
        try {
            const api = replyEditorUpload[postId];
            if (api && typeof api.cancelUpload === 'function') {
                api.cancelUpload();
            }
        } catch (_) { /* noop */ }
        try {
            setReplyIsUploading((prev) => ({ ...prev, [postId]: false }));
            setReplyUploadProgress((prev) => {
                const next = { ...prev };
                delete next[postId];
                return next;
            });
            setReplyAttachedType((prev) => {
                const next = { ...prev };
                delete next[postId];
                return next;
            });
            setReplyAttachedUrl((prev) => {
                const next = { ...prev };
                delete next[postId];
                return next;
            });
            setReplyThumbLoading((prev) => {
                const next = { ...prev };
                delete next[postId];
                return next;
            });
            // Clear any error and pending timeout
            setReplySubmitError((prev) => {
                const next = { ...prev };
                delete next[postId];
                return next;
            });
            try {
                const t = replyErrorClearTimeoutRef.current?.[postId];
                if (t) {
                    clearTimeout(t);
                    delete replyErrorClearTimeoutRef.current[postId];
                }
            } catch (_) { /* noop */ }
        } catch (_) { /* noop */ }
        updatePost(postId, { replyOpen: false, replyMode: undefined, replyText: "" });
    };

    const closeAllReplies = () => {
        Object.keys(state.posts || {}).forEach((id) => {
            if (state.posts[id]?.replyOpen) {
                updatePost(id, { replyOpen: false, replyMode: undefined });
            }
        });
    };

    const toggleReply = (postId) => {
        // Clear any open confirmations when opening reply
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmDeletePost(null);
        setConfirmReportPost(null);
        setConfirmDonate(null);
        clearBlockMessages();

        let replyOpenState = state.posts[postId]?.replyOpen || false;
        if (!replyOpenState) {
            closeAllReplies();
        }
        updatePost(postId, { replyOpen: !replyOpenState, replyMode: undefined });
    };

    const clearBlockMessages = () => {
        setBlockError('');
        setBlockSuccess('');
    };

    const showBlockError = (message) => {
        setBlockError(message);
        setBlockSuccess('');
        setTimeout(() => setBlockError(''), 5000);
    };

    const showBlockSuccess = (message) => {
        setBlockSuccess(message);
        setBlockError('');
        setTimeout(() => setBlockSuccess(''), 3000);
    };

    const handleBlockPost = (postId) => {
        if (!postId) {
            showBlockError("Invalid post ID");
            return;
        }
        clearBlockMessages();
        setConfirmReportPost(null);
        setConfirmDeletePost(null);
        setConfirmDonate(null);
        setConfirmBlockUser(null); // Cancel any user block confirmation
        setConfirmBlockPost(postId);
        // Close reply box for this post
        try { updatePost(postId, { replyOpen: false }); } catch (_) { }
    };

    const confirmBlockPostAction = async () => {
        const postId = confirmBlockPost;
        setConfirmBlockPost(null);
        setIsBlocking(true);

        try {
            const result = await tx.blockPost(postId, true);
            if (result.success) {
                showBlockSuccess("Post blocked successfully!");
            } else {
                showBlockError(`Failed to block post: ${result.error}`);
            }
        } catch (error) {
            console.error("Block post error:", error);
            showBlockError(`Error: ${error.message || error}`);
        } finally {
            setIsBlocking(false);
        }
    };

    const cancelBlockPost = () => {
        setConfirmBlockPost(null);
        clearBlockMessages();
    };

    const handleBlockUser = (userAddress, postId) => {
        if (!userAddress) {
            showBlockError("Invalid user address");
            return;
        }
        clearBlockMessages();
        setConfirmBlockPost(null); // Cancel any post block confirmation
        setConfirmReportPost(null);
        setConfirmDeletePost(null);
        setConfirmDonate(null);
        setConfirmBlockUser({ userId: userAddress, postId });
        // Close reply box for root (if any)
        try { if (root && root.post_id) updatePost(root.post_id, { replyOpen: false }); } catch (_) { }
    };

    const confirmBlockUserAction = async () => {
        const userAddress = confirmBlockUser?.userId;
        setConfirmBlockUser(null);
        setIsBlocking(true);

        try {
            const result = await tx.blockUser(userAddress, true);
            if (result.success) {
                showBlockSuccess("User blocked successfully!");
            } else {
                showBlockError(`Failed to block user: ${result.error}`);
            }
        } catch (error) {
            console.error("Block user error:", error);
            showBlockError(`Error: ${error.message || error}`);
        } finally {
            setIsBlocking(false);
        }
    };

    const cancelBlockUser = () => {
        setConfirmBlockUser(null);
        clearBlockMessages();
    };

    const handleReport = (postId) => {
        if (!postId) {
            showBlockError("Invalid post ID");
            return;
        }
        clearBlockMessages();
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmDeletePost(null);
        setConfirmDonate(null);
        setReportReason("");
        setConfirmReportPost(postId);
        try { updatePost(postId, { replyOpen: false }); } catch (_) { }
    };

    const confirmReportAction = async () => {
        const postId = confirmReportPost;
        const reason = (reportReason || "").trim().slice(0, 140);
        setConfirmReportPost(null);
        setIsReporting(true);

        if (!reason) {
            setReportMessages(prev => ({ ...prev, [postId]: { type: 'error', message: 'Reason is required' } }));
            setTimeout(() => setReportMessages(prev => { const n = { ...prev }; delete n[postId]; return n; }), 5000);
            setIsReporting(false);
            return;
        }

        try {
            const result = await tx.reportPost(postId, reason);
            if (result && result.success) {
                setReportMessages(prev => ({ ...prev, [postId]: { type: 'success', message: 'Report submitted' } }));
                setTimeout(() => setReportMessages(prev => { const n = { ...prev }; delete n[postId]; return n; }), 5000);
            } else {
                setReportMessages(prev => ({ ...prev, [postId]: { type: 'error', message: `Failed: ${result && result.error ? result.error : 'unknown error'}` } }));
                setTimeout(() => setReportMessages(prev => { const n = { ...prev }; delete n[postId]; return n; }), 5000);
            }
        } catch (e) {
            setReportMessages(prev => ({ ...prev, [postId]: { type: 'error', message: `Error: ${e && e.message ? e.message : e}` } }));
            setTimeout(() => setReportMessages(prev => { const n = { ...prev }; delete n[postId]; return n; }), 5000);
        } finally {
            setIsReporting(false);
        }
    };

    const cancelReport = () => {
        setConfirmReportPost(null);
        setReportReason("");
    };

    const handleDeletePost = (postId) => {
        if (!postId) {
            showBlockError("Invalid post ID");
            return;
        }
        clearBlockMessages();
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmReportPost(null);
        setConfirmDonate(null);
        setConfirmDeletePost(postId);
        try { updatePost(postId, { replyOpen: false }); } catch (_) { }
    };

    const confirmDeletePostAction = async () => {
        const postId = confirmDeletePost;
        setConfirmDeletePost(null);
        setIsDeleting(true);

        // Check if this is the root post or a comment
        const isRootPost = postId === root.post_id;

        try {
            const result = await tx.deletePost(postId);
            if (result.success) {
                // Set success message for this specific post
                setDeleteMessages(prev => ({
                    ...prev,
                    [postId]: { type: 'success', message: 'Post deleted successfully!' }
                }));

                // Clear the message and hide the post after 3 seconds
                setTimeout(() => {
                    setDeleteMessages(prev => {
                        const updated = { ...prev };
                        delete updated[postId];
                        return updated;
                    });

                    // If it's the root post, redirect to home
                    if (isRootPost) {
                        navigate('/');
                    } else {
                        // Hide the comment and all its descendants from the list
                        const descendants = findAllDescendantPostIds(postId, children);
                        setDeletedPosts(prev => new Set([...prev, postId, ...descendants]));
                    }
                }, 3000);
            } else {
                // Set error message for this specific post
                setDeleteMessages(prev => ({
                    ...prev,
                    [postId]: { type: 'error', message: `Failed to delete post: ${result.error}` }
                }));
                setTimeout(() => {
                    setDeleteMessages(prev => {
                        const updated = { ...prev };
                        delete updated[postId];
                        return updated;
                    });
                }, 3000);
            }
        } catch (error) {
            console.error("Delete post error:", error);
            setDeleteMessages(prev => ({
                ...prev,
                [postId]: { type: 'error', message: `Error: ${error.message || error}` }
            }));
            setTimeout(() => {
                setDeleteMessages(prev => {
                    const updated = { ...prev };
                    delete updated[postId];
                    return updated;
                });
            }, 3000);
        } finally {
            setIsDeleting(false);
        }
    };

    const cancelDeletePost = () => {
        setConfirmDeletePost(null);
        clearBlockMessages();
    };

    const handleSuspendFromQuests = (userId, postId) => {
        if (!userId) return;
        clearBlockMessages();
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmDeletePost(null);
        setConfirmReportPost(null);
        setConfirmDonate(null);
        setConfirmUnsuspendQuests(null);
        setConfirmSuspendQuests({ userId, postId });
    };

    const confirmSuspendFromQuests = async () => {
        const userId = confirmSuspendQuests?.userId;
        const postId = confirmSuspendQuests?.postId;
        if (!userId) return;
        const adminAddress = state.publicKey;
        if (!adminAddress) return;

        setIsSuspending(true);
        try {
            const response = await Api.post('/admin/rewards/suspend', {
                admin: adminAddress,
                target: userId,
                duration_days: suspendDuration,  // 0 = permanent
                reason: 'Attempting to game the quest system',
            });
            if (response.success) {
                const durationText = suspendDuration > 0 ? `for ${suspendDuration} day${suspendDuration > 1 ? 's' : ''}` : 'permanently';
                setConfirmSuspendQuests(null);
                setUserSuspendedMap(prev => ({ ...prev, [userId]: true }));
                if (postId) {
                    setSuspendSuccess(prev => ({ ...prev, [postId]: `User suspended from quests ${durationText}` }));
                }
                setTimeout(() => {
                    setSuspendSuccess(prev => {
                        const updated = { ...prev };
                        if (postId) delete updated[postId];
                        return updated;
                    });
                }, 4000);
            } else {
                alert(`Failed to suspend: ${response.error || response.message || 'Unknown error'}`);
                setConfirmSuspendQuests(null);
            }
        } catch (err) {
            alert(`Error suspending user: ${err.message || 'Unknown error'}`);
            setConfirmSuspendQuests(null);
        }
        setIsSuspending(false);
        setSuspendDuration(7); // Reset to default
    };

    const cancelSuspendFromQuests = () => {
        setConfirmSuspendQuests(null);
    };

    const fetchUserSuspensionStatus = async (userId) => {
        if (!userId || !questsEnabled) return;
        try {
            const response = await Api.get(`/rewards/summary?owner=${encodeURIComponent(userId)}`);
            setUserSuspendedMap(prev => ({ ...prev, [userId]: response.suspended === true }));
        } catch (err) {
            console.error('Error fetching suspension status:', err);
        }
    };

    const handleUnsuspendFromQuests = (userId, postId) => {
        if (!userId) return;
        clearBlockMessages();
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmDeletePost(null);
        setConfirmReportPost(null);
        setConfirmSuspendQuests(null);
        setConfirmUnsuspendQuests({ userId, postId });
    };

    const confirmUnsuspendFromQuests = async () => {
        const userId = confirmUnsuspendQuests?.userId;
        const postId = confirmUnsuspendQuests?.postId;
        if (!userId) return;
        const adminAddress = state.publicKey;
        if (!adminAddress) return;

        setIsUnsuspending(true);
        try {
            const response = await Api.post('/admin/rewards/unsuspend', {
                admin: adminAddress,
                target: userId,
            });
            if (response.success) {
                setConfirmUnsuspendQuests(null);
                setUserSuspendedMap(prev => ({ ...prev, [userId]: false }));
                if (postId) {
                    setSuspendSuccess(prev => ({ ...prev, [postId]: 'User unsuspended from quests' }));
                }
                setTimeout(() => {
                    setSuspendSuccess(prev => {
                        const updated = { ...prev };
                        if (postId) delete updated[postId];
                        return updated;
                    });
                }, 4000);
            } else {
                alert(`Failed to unsuspend: ${response.error || response.message || 'Unknown error'}`);
                setConfirmUnsuspendQuests(null);
            }
        } catch (err) {
            alert(`Error unsuspending user: ${err.message || 'Unknown error'}`);
            setConfirmUnsuspendQuests(null);
        }
        setIsUnsuspending(false);
    };

    const cancelUnsuspendFromQuests = () => {
        setConfirmUnsuspendQuests(null);
    };

    const handleDonate = (userAddress, postId) => {
        if (!userAddress) {
            return;
        }
        setConfirmBlockPost(null);
        setConfirmBlockUser(null);
        setConfirmDeletePost(null);
        setConfirmReportPost(null);
        setConfirmSuspendQuests(null);
        setConfirmUnsuspendQuests(null);
        setConfirmDonate({ userId: userAddress, postId });
        try { if (postId) updatePost(postId, { replyOpen: false }); } catch (_) { }
        setDonateAmount("1"); // Reset to default
    };

    const openEdit = (post) => {
        if (!post || !post.post_id) return;
        const isRoot = !!(post.title && String(post.title).trim() !== '');
        if (isRoot) {
            navigate(`/create_post?post_id=${post.post_id}&edit=true`);
            return;
        }
        // Comment edit: reuse reply box
        updatePost(post.post_id, {
            replyOpen: true,
            replyMode: 'edit',
            replyText: post.content || '',
            editBusy: false,
        });
    };
    const closeEdit = (postId) => {
        if (!postId) return;
        updatePost(postId, { editOpen: false });
    };
    const handleEditSubmit = async (post) => {
        if (!post || !post.post_id) return;
        const isRoot = !!(post.title && String(post.title).trim() !== '');
        // For comments edited via reply box, pull from replyText; fallback to editText for safety
        const newContent = (state.posts[post.post_id]?.replyText || state.posts[post.post_id]?.editText || '').trim();
        const newTitle = (state.posts[post.post_id]?.editTitle || '').trim();
        if (newContent.length === 0) return;
        try {
            const changes = {
                target: post.target || '',
                topic: isRoot ? (post.topic || '') : '',
                title: isRoot ? newTitle : '',
                content: newContent,
                tag: (post && typeof post.tag === 'string') ? post.tag : '',
                media: Array.isArray(post && post.media) ? post.media : [],
            };
            // Disable controls while PoW/broadcast happens
            try { updatePost(post.post_id, { editBusy: true }); } catch (_) { }
            const res = await tx.editPost(post.post_id, changes);
            if (res && res.success) {
                // Optimistically update UI: show new content and flash it
                try {
                    const nowTs = Math.floor(Date.now() / 1000);
                    updatePost(post.post_id, {
                        content: newContent,
                        flash: true,
                        edited_at: nowTs,
                    });
                    // Clear flash after animation delay
                    setTimeout(() => {
                        try { updatePost(post.post_id, { flash: false }); } catch (_) { }
                    }, 1250);
                } catch (_) { }
                // Close edit UIs
                closeEdit(post.post_id);
                closeReply(post.post_id);
            } else {
                alert(`Failed to edit: ${res && res.error ? res.error : 'unknown error'}`);
                try { updatePost(post.post_id, { editBusy: false }); } catch (_) { }
            }
        } catch (e) {
            alert(`Edit failed: ${e && e.message ? e.message : e}`);
            try { updatePost(post.post_id, { editBusy: false }); } catch (_) { }
        }
    };

    const confirmDonateAction = async () => {
        const userAddress = confirmDonate?.userId;
        const postId = confirmDonate?.postId;
        setConfirmDonate(null);
        setIsDonating(true);

        const amount = parseInt(String(donateAmount || "").replace(/[^\d]/g, ""), 10);
        if (isNaN(amount) || amount <= 0) {
            if (postId) {
                setDonateMessages(prev => ({
                    ...prev,
                    [postId]: { type: 'error', message: 'Invalid amount' }
                }));
                setTimeout(() => {
                    setDonateMessages(prev => {
                        const updated = { ...prev };
                        delete updated[postId];
                        return updated;
                    });
                }, 5000);
            }
            setIsDonating(false);
            return;
        }

        try {
            const result = await tx.sendTokens(userAddress, amount);
            if (result.success) {
                if (postId) {
                    setDonateMessages(prev => ({
                        ...prev,
                        [postId]: { type: 'success', message: `Successfully sent ${Number(amount).toLocaleString()} MIRAGE!` }
                    }));
                    setTimeout(() => {
                        setDonateMessages(prev => {
                            const updated = { ...prev };
                            delete updated[postId];
                            return updated;
                        });
                    }, 5000);
                }
            } else {
                if (postId) {
                    setDonateMessages(prev => ({
                        ...prev,
                        [postId]: { type: 'error', message: `Failed: ${result.error}` }
                    }));
                    setTimeout(() => {
                        setDonateMessages(prev => {
                            const updated = { ...prev };
                            delete updated[postId];
                            return updated;
                        });
                    }, 5000);
                }
            }
        } catch (error) {
            console.error("Donate error:", error);
            if (postId) {
                setDonateMessages(prev => ({
                    ...prev,
                    [postId]: { type: 'error', message: `Error: ${error.message || error}` }
                }));
                setTimeout(() => {
                    setDonateMessages(prev => {
                        const updated = { ...prev };
                        delete updated[postId];
                        return updated;
                    });
                }, 5000);
            }
        } finally {
            setIsDonating(false);
        }
    };

    const cancelDonate = () => {
        setConfirmDonate(null);
    };

    const handleDonateAmountChange = (value) => {
        setDonateAmount(String(value || '').replace(/[^\d]/g, ""));
    };

    const formatDonateAmount = (value) => {
        const digits = String(value || "").replace(/[^\d]/g, "");
        if (!digits) return "";
        return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    };


    // Recursively find all descendant post IDs of a given post
    const findAllDescendantPostIds = (postId, commentsTree) => {
        const descendantIds = [];

        const findDescendants = (items) => {
            for (const item of items) {
                if (item.children && item.children.length > 0) {
                    // First recurse into children to search deeper
                    findDescendants(item.children);
                }

                // If this item matches our target, collect all its descendants
                if (item.post_id === postId && item.children) {
                    const collectAll = (childItems) => {
                        for (const child of childItems) {
                            descendantIds.push(child.post_id);
                            if (child.children && child.children.length > 0) {
                                collectAll(child.children);
                            }
                        }
                    };
                    collectAll(item.children);
                }
            }
        };

        findDescendants(commentsTree);
        return descendantIds;
    };

    const handleReplyChange = (postId, value) => {
        updatePost(postId, { replyText: value });
    };

    const insertReplyImageUrl = (postId, url) => {
        const currentText = state.posts[postId]?.replyText || '';
        const separator = currentText && !currentText.endsWith('\n') && !currentText.endsWith(' ') ? ' ' : '';
        const newText = currentText + separator + url;
        handleReplyChange(postId, newText);
    };

    const handleReplyFileUpload = async (postId, file) => {
        const isImg = !!(file && typeof file.type === 'string' && file.type.startsWith('image/'));
        const isVid = !!(file && typeof file.type === 'string' && file.type.startsWith('video/'));
        if (!isImg && !isVid) {
            console.warn('[ViewPostView] Invalid file type for reply upload');
            return;
        }

        try {
            let mediaUrl;
            if (isImg) {
                mediaUrl = await uploadImage(file, (progress) => {
                    setReplyUploadProgress(prev => ({ ...prev, [postId]: progress }));
                });
            } else {
                const { uploadVideo } = await import('../utils/VideoUpload');
                mediaUrl = await uploadVideo(file, (progress) => {
                    setReplyUploadProgress(prev => ({ ...prev, [postId]: progress }));
                });
            }
            insertReplyImageUrl(postId, mediaUrl);
            setReplyUploadProgress(prev => {
                const next = { ...prev };
                delete next[postId];
                return next;
            });
        } catch (error) {
            console.error('[ViewPostView] Reply image upload failed:', error);
            setReplyUploadProgress(prev => {
                const next = { ...prev };
                delete next[postId];
                return next;
            });
        }
    };

    const handleReplyDragOver = (postId, e) => {
        if (replyIsUploading[postId]) return; // Disable drag during upload
        e.preventDefault();
        e.stopPropagation();
        if (!replyDragState[postId]) {
            setReplyDragState(prev => ({ ...prev, [postId]: true }));
        }
    };

    const handleReplyDragLeave = (postId, e) => {
        if (replyIsUploading[postId]) return; // Disable drag during upload
        e.preventDefault();
        e.stopPropagation();
        if (!e.currentTarget.contains(e.relatedTarget)) {
            setReplyDragState(prev => {
                const next = { ...prev };
                delete next[postId];
                return next;
            });
        }
    };

    const handleReplyDrop = (postId, e) => {
        if (replyIsUploading[postId]) {
            e.preventDefault();
            e.stopPropagation();
            return; // Disable drop during upload
        }
        e.preventDefault();
        e.stopPropagation();
        setReplyDragState(prev => {
            const next = { ...prev };
            delete next[postId];
            return next;
        });

        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) {
            try {
                const api = replyEditorUpload[postId];
                if (api && typeof api.uploadFile === 'function') {
                    api.uploadFile(files[0]);
                    return;
                }
            } catch (_) { }
            handleReplyFileUpload(postId, files[0]);
        }
    };

    // const handleReplyFileInput = (postId, e) => {
    //     const files = Array.from(e.target.files || []);
    //     if (files.length > 0) {
    //         handleReplyFileUpload(postId, files[0]);
    //     }
    //     e.target.value = '';
    // };

    const handleSubmit = (commentId) => async (event) => {
        event.preventDefault();
        const replyStringRaw = state.posts[commentId]?.replyText || "";
        let replyString = replyStringRaw.trim();
        // Prepend attached media URL if present (same behavior as create_post)
        try {
            const mediaUrl = replyAttachedUrl[commentId];
            if (mediaUrl) {
                replyString = `${mediaUrl}\n\n${replyString}`;
            }
        } catch (_) { }
        if (replyString === "" || replyString === null) return;

        if (replyString.length > limits.maxContent) {
            alert(`Comment too long (${replyString.length} > ${limits.maxContent} chars)`);
            return;
        }

        // Disable controls while PoW/broadcast happens
        try { updatePost(commentId, { replyBusy: true }); } catch (_) { }
        setReplySubmitStartTime(prev => ({ ...prev, [commentId]: Date.now() }));
        setReplySubmitStatus(prev => ({ ...prev, [commentId]: 'solving' }));

        // Clear reply text but keep box open (disabled) during PoW
        try {
            updatePost(commentId, {
                replyText: "",
            });
        } catch (_) { }

        // Submit the comment and wait for completion
        try {
            const res = await tx.createCommentAsync(commentId, replyString);
            // Clear attached state for this reply
            try {
                setReplyAttachedType(prev => { const n = { ...prev }; delete n[commentId]; return n; });
                setReplyAttachedUrl(prev => { const n = { ...prev }; delete n[commentId]; return n; });
                setReplyThumbLoading(prev => { const n = { ...prev }; delete n[commentId]; return n; });
            } catch (_) { }

            if (res && res.success) {
                try {
                    const txHash = (res && res.tx_hash) ? String(res.tx_hash).toLowerCase() : "";
                    if (!txHash) throw new Error("missing tx hash");

                    // Immediately insert optimistic comment and close reply box
                    const viewerAddress = Storage.load("publicKey", "");
                    const optimisticComment = {
                        post_id: txHash,
                        user_id: viewerAddress,
                        username: Storage.load("username", ""),
                        content: replyString,
                        target: commentId,
                        timestamp: Math.floor(Date.now() / 1000),
                        points: 1,
                        comments: 0,
                        children: [],
                        user_vote: 1,
                        user_weight: 1,
                        _optimistic: true,
                    };

                    // Insert into children - find parent and add as FIRST child (most recent first)
                    if (root && root.post_id === commentId) {
                        // Replying to root - insert at beginning of top-level children
                        setChildren(prev => [optimisticComment, ...prev]);
                        setRoot(prev => ({ ...prev, comments: (prev.comments || 0) + 1 }));
                    } else {
                        // Replying to a comment - find parent and insert at beginning of its children
                        setChildren(prev => {
                            const insertComment = (nodes) => {
                                return nodes.map(node => {
                                    if (node.post_id === commentId) {
                                        return {
                                            ...node,
                                            children: [optimisticComment, ...(node.children || [])],
                                            comments: (node.comments || 0) + 1,
                                        };
                                    }
                                    if (node.children && node.children.length > 0) {
                                        return { ...node, children: insertComment(node.children) };
                                    }
                                    return node;
                                });
                            };
                            return insertComment(prev);
                        });
                    }

                    // Close reply box immediately
                    try { updatePost(commentId, { replyOpen: false, replyBusy: false }); } catch (_) { }

                    // Flash and scroll to new comment
                    setTimeout(() => {
                        try { updatePost(txHash, { flash: true }); } catch (_) { }
                        try {
                            const el = document.getElementById(`comment-${txHash}`);
                            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        } catch (_) { }
                        setTimeout(() => {
                            try { updatePost(txHash, { flash: false }); } catch (_) { }
                        }, 700);
                    }, 50);

                    // Verify in background (don't block UI)
                    (async () => {
                        try {
                            const result = await tx.pollTxStatus(txHash);
                            if (result && result.success && result.indexed) {
                                const data = await Api.get('get_comments', { post_id: postId, address: viewerAddress }, { timeoutMs: 10000 });
                                if (data) {
                                    setRoot(data.root);
                                    setChildren(data.children);
                                }
                            }
                        } catch (_) { }
                    })();
                } catch (e) {
                    setReplySubmitError(prev => ({ ...prev, [commentId]: String(e && e.message ? e.message : 'Failed to confirm') }));
                    try { updatePost(commentId, { replyBusy: false }); } catch (_) { }
                }
            } else {
                setReplySubmitError(prev => ({ ...prev, [commentId]: res?.error || 'Comment failed' }));
                try { updatePost(commentId, { replyBusy: false }); } catch (_) { }
            }
        } catch (e) {
            setReplySubmitError(prev => ({ ...prev, [commentId]: String(e?.message || e || 'Comment failed') }));
            try { updatePost(commentId, { replyBusy: false }); } catch (_) { }
        } finally {
            setReplySubmitStartTime(prev => { const n = { ...prev }; delete n[commentId]; return n; });
            setReplyElapsedTime(prev => { const n = { ...prev }; delete n[commentId]; return n; });
            setReplySubmitStatus(prev => { const n = { ...prev }; delete n[commentId]; return n; });
        }
    };

    // Support new clean URL /p/:postId and legacy /view_post?post_id=...
    const routeParams = useParams();

    // Parse depth from query params (0-5, must be valid integer when provided)
    const depthParam = React.useMemo(() => {
        const params = new URLSearchParams(location.search);
        const raw = params.get('depth');
        if (raw === null || raw === '') return null; // Not provided
        if (!/^\d+$/.test(raw)) {
            console.error('[ViewPostView] Invalid depth parameter:', raw, '- must be 0-5');
            return 'invalid';
        }
        const num = Number(raw);
        if (!Number.isFinite(num) || num < 0 || num > 5) {
            console.error('[ViewPostView] Invalid depth parameter:', raw, '- must be 0-5');
            return 'invalid';
        }
        return num;
    }, [location.search]);

    const postId = React.useMemo(() => {
        // New clean URL: /p/:postId
        if (routeParams.postId) {
            return routeParams.postId;
        }
        // DEPRECATED: Legacy query params, remove in future release
        const params = new URLSearchParams(location.search);
        return params.get('root') || params.get('post_id');
    }, [routeParams.postId, location.search]);

    // focusedCommentId: set when viewing a specific comment (not the root post)
    // For legacy URLs: when both root and post_id are provided
    // DEPRECATED: Legacy query params, remove in future release
    const legacyFocusedCommentId = React.useMemo(() => {
        const params = new URLSearchParams(location.search);
        const r = params.get('root');
        const pid = params.get('post_id');
        if (r && pid) return String(pid).toLowerCase();
        return '';
    }, [location.search]);

    // For new URLs (/p/:postId): detect if loaded post is a comment (has non-empty target)
    // This is computed after root loads
    const isViewingComment = React.useMemo(() => {
        if (!root) return false;
        // Check if this post has a target (is a reply) and has a different root_post_id
        const target = root.target || '';
        const rootPostId = root.root_post_id || '';
        const thisPostId = (root.post_id || '').toLowerCase();
        return target.trim() !== '' && rootPostId.toLowerCase() !== thisPostId;
    }, [root]);

    // Effective focusedCommentId: use legacy param if set, otherwise detect from loaded data
    const focusedCommentId = React.useMemo(() => {
        if (legacyFocusedCommentId) return legacyFocusedCommentId;
        // For new URL scheme: if we loaded a comment (not root), treat postId as focused
        if (isViewingComment && routeParams.postId) {
            return String(routeParams.postId).toLowerCase();
        }
        return '';
    }, [legacyFocusedCommentId, isViewingComment, routeParams.postId]);

    // The actual root post ID (for "view full thread" links)
    const actualRootPostId = React.useMemo(() => {
        if (!root) return '';
        // If viewing a comment, use root_post_id; otherwise use the post's own ID
        if (isViewingComment && root.root_post_id) {
            return root.root_post_id.toLowerCase();
        }
        return (root.post_id || '').toLowerCase();
    }, [root, isViewingComment]);

    const [lastVisitTs, setLastVisitTs] = useState(null);

    // Consume highlight ID once - use module cache to survive React Strict Mode
    const [highlightPostId] = useState(() => {
        if (!_highlightConsumed) {
            _cachedHighlightPostId = Storage.consumePendingPostHighlight();
            _highlightConsumed = true;
        }
        return _cachedHighlightPostId;
    });

    // Reset cache on unmount so next navigation gets fresh value
    useEffect(() => {
        return () => {
            _highlightConsumed = false;
            _cachedHighlightPostId = null;
        };
    }, []);

    // Track if the root post should flash (separate from comments which use state.posts)
    const [rootFlash, setRootFlash] = useState(false);
    const rootFlashTriggeredRef = useRef(false);

    // Flash the root post once when it loads and matches the highlight ID
    useEffect(() => {
        if (rootFlashTriggeredRef.current) return;

        // Compute the target ID directly here
        let targetHighlightId = null;
        if (focusedCommentId && /^[0-9a-f]{64}$/i.test(focusedCommentId)) {
            targetHighlightId = focusedCommentId.toLowerCase();
        } else if (highlightPostId) {
            targetHighlightId = String(highlightPostId).toLowerCase();
        }

        if (!targetHighlightId) return;
        if (!root || !root.post_id) return;
        if (String(root.post_id).toLowerCase() !== targetHighlightId) return;

        rootFlashTriggeredRef.current = true;
        setRootFlash(true);
        setTimeout(() => setRootFlash(false), 700);
    }, [focusedCommentId, highlightPostId, root]);

    // Compute normalizedHighlightId for use elsewhere (highlighting border etc)
    const normalizedHighlightId = React.useMemo(() => {
        if (focusedCommentId && /^[0-9a-f]{64}$/i.test(focusedCommentId)) {
            return focusedCommentId.toLowerCase();
        }
        if (highlightPostId) {
            return String(highlightPostId).toLowerCase();
        }
        const hash = (typeof window !== 'undefined' && window.location && window.location.hash) ? window.location.hash : '';
        if (hash && hash.startsWith('#comment-')) {
            const commentId = hash.slice('#comment-'.length).toLowerCase();
            if (/^[0-9a-f]{64}$/i.test(commentId)) {
                return commentId;
            }
        }
        return null;
    }, [highlightPostId, focusedCommentId]);

    // Flash comments once after they load (for comment-specific highlights)
    const highlightFlashRef = useRef(false);
    useEffect(() => {
        if (highlightFlashRef.current) return;
        const targetId = normalizedHighlightId;
        if (!targetId) return;
        // Skip if this is the root post (handled above)
        if (root && root.post_id && String(root.post_id).toLowerCase() === targetId) return;
        const targetKey = String(targetId).toLowerCase();
        // Find the comment in children (recursively) and get its actual post_id
        const findInChildren = (nodes) => {
            if (!Array.isArray(nodes)) return null;
            for (const n of nodes) {
                if (!n || !n.post_id) continue;
                if (String(n.post_id).toLowerCase() === targetKey) return n.post_id;
                if (n.children) {
                    const found = findInChildren(n.children);
                    if (found) return found;
                }
            }
            return null;
        };
        const actualPostId = findInChildren(children);
        if (!actualPostId) return;
        highlightFlashRef.current = true;
        try { updatePost(actualPostId, { flash: true }); } catch (_) { }
        setTimeout(() => {
            try { updatePost(actualPostId, { flash: false }); } catch (_) { }
        }, 1500);
    }, [normalizedHighlightId, root, children, updatePost]);

    useEffect(() => {
        const post_id = postId;

        if (post_id) {
            const viewerAddress = Storage.load("publicKey", "");
            Api.get('get_comments', { post_id, address: viewerAddress }, { timeoutMs: 10000 })
                .then((data) => {
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
                    } catch (_) { setLastVisitTs(null); }
                    // Mark visit timestamp after capturing previous, for highlighting
                    try {
                        const nowSec = Math.floor(Date.now() / 1000);
                        Storage.setLastVisitTimestamp(post_id, nowSec);
                    } catch (_) { }
                    // Auto-open edit if edit query parameter is present and user owns the post
                    const params = new URLSearchParams(location.search);
                    const shouldEdit = params.get('edit') === 'true';
                    if (shouldEdit && data.root) {
                        const currentUserAddress = (state && state.publicKey) ? String(state.publicKey).trim().toLowerCase() : Storage.load('publicKey', '').trim().toLowerCase();
                        const postAuthorAddress = (data.root && data.root.user_id) ? String(data.root.user_id).trim().toLowerCase() : '';
                        const isAuthor = currentUserAddress && postAuthorAddress && currentUserAddress === postAuthorAddress;
                        if (isAuthor) {
                            // Small delay to ensure state is updated
                            setTimeout(() => {
                                openEdit(data.root);
                            }, 100);
                        }
                    }
                    // Auto-open donate dialog if donate query parameter is present
                    const shouldDonate = params.get('donate') === 'true';
                    if (shouldDonate && data.root && data.root.user_id) {
                        setTimeout(() => {
                            setConfirmDonate(data.root.user_id);
                        }, 100);
                    }
                    // Do not auto-open reply; user explicitly opens when needed
                })
                .catch((error) => {
                    setLoading(false);
                    let errorMessage = "An unknown error occurred";
                    const msg = (error && error.message) ? String(error.message) : "";
                    if (/HTTP\s*404/i.test(msg)) {
                        errorMessage = (
                            <span>
                                <br />&nbsp;
                                <strong>No post with id:</strong><br />
                                <span style={{ fontSize: '0.6rem' }}>{post_id}</span>
                                <br />
                                <br />
                                <span style={{ fontSize: '0.75rem' }}>
                                    Try Again in ~10s; it may be still propagating across the network.
                                </span>
                                <br />&nbsp;
                            </span>
                        );
                    } else if (msg) {
                        errorMessage = msg;
                    }
                    setError(errorMessage);
                });
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [postId]);

    // When in focused view, fetch the focused comment's children separately
    // This ensures we get 6 levels of children from the focused comment, not limited by its depth from root
    useEffect(() => {
        if (!focusedCommentId || !root) return;

        const viewerAddress = Storage.load("publicKey", "");
        Api.get('get_comments', { post_id: focusedCommentId, address: viewerAddress }, { timeoutMs: 10000 })
            .then((data) => {
                if (data && data.root && data.children) {
                    // Store the focused comment's children in state so they can be merged
                    try {
                        updatePost(focusedCommentId, { children: data.children });
                    } catch (_) { }
                }
            })
            .catch((err) => {
                console.error('[ViewPostView] Failed to load focused comment children:', err);
            });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [focusedCommentId, root]);

    // When viewing a comment via /p/:commentId, also load the actual root post for display
    useEffect(() => {
        if (!isViewingComment || !actualRootPostId) {
            setActualRootPost(null);
            return;
        }
        // Don't reload if we already have it
        if (actualRootPost && actualRootPost.post_id && actualRootPost.post_id.toLowerCase() === actualRootPostId) {
            return;
        }
        const viewerAddress = Storage.load("publicKey", "");
        Api.get('get_comments', { post_id: actualRootPostId, address: viewerAddress }, { timeoutMs: 10000 })
            .then((data) => {
                if (data && data.root) {
                    setActualRootPost(data.root);
                }
            })
            .catch((err) => {
                console.error('[ViewPostView] Failed to load actual root post:', err);
            });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isViewingComment, actualRootPostId]);

    // Flatten comments: root is level 0; replies increment level
    const flattenedComments = React.useMemo(() => {
        if (!root || !root.post_id) return [];

        const mergeChildren = (node, baseChildren) => {
            const fromState = (state.posts && state.posts[node.post_id] && state.posts[node.post_id].children) || [];
            const map = new Map();
            if (Array.isArray(baseChildren)) {
                for (const c of baseChildren) { if (c && c.post_id) map.set(c.post_id, c); }
            }
            if (Array.isArray(fromState)) {
                for (const c of fromState) { if (c && c.post_id) map.set(c.post_id, c); }
            }
            const arr = Array.from(map.values());
            return sortComments(arr, viewerAddress);
        };

        const walk = (nodes, level, out) => {
            if (!Array.isArray(nodes)) return;
            nodes.forEach((n) => {
                out.push({ ...n, level });
                const next = mergeChildren(n, n.children);
                if (next && next.length) walk(next, level + 1, out);
            });
        };

        // When viewing a comment via /p/:commentId, always show actual root post at top
        if (isViewingComment) {
            const out = [];
            let nextLevel = 0;
            // Add actual root post if loaded; if not yet loaded, skip it (it will appear once loaded)
            if (actualRootPost && actualRootPost.post_id) {
                out.push({ ...actualRootPost, level: 0 });
                nextLevel = 1;
            }
            // Add context comments (parent chain) if loaded
            if (showContext && contextComments.length > 0) {
                const rootPostId = actualRootPost?.post_id?.toLowerCase() || '';
                const filteredContext = contextComments.filter(c => {
                    const contextPostId = c && c.post_id ? String(c.post_id).toLowerCase() : '';
                    return contextPostId !== rootPostId;
                });
                filteredContext.forEach((c) => {
                    // Mark as context comment so "Continue this thread" doesn't show
                    out.push({ ...c, children: [], level: nextLevel, isContextComment: true });
                    nextLevel++;
                });
            }
            // Add the focused comment (which is `root` in this case - the loaded comment)
            out.push({ ...root, level: nextLevel });
            // Add focused comment's children
            const focusedChildren = mergeChildren(root, children);
            if (focusedChildren && focusedChildren.length) {
                walk(focusedChildren, nextLevel + 1, out);
            }
            return out;
        }

        // Normal view (viewing a root post, or legacy focused comment flow)
        const out = [{ ...root, level: 0 }];
        const base = mergeChildren(root, children);

        if (focusedCommentId && !isViewingComment) {
            // Legacy focused comment view (from ?root=X&post_id=Y)
            const lcTarget = String(focusedCommentId).toLowerCase();
            const findInMerged = (nodes) => {
                if (!Array.isArray(nodes)) return null;
                for (const n of nodes) {
                    if (!n || !n.post_id) continue;
                    if (String(n.post_id).toLowerCase() === lcTarget) return n;
                    const next = mergeChildren(n, n.children);
                    const found = findInMerged(next);
                    if (found) return found;
                }
                return null;
            };
            const targetNode = findInMerged(base);
            if (targetNode) {
                if (showContext && contextComments.length > 0) {
                    const rootPostId = root && root.post_id ? String(root.post_id).toLowerCase() : '';
                    const filteredContext = contextComments.filter(c => {
                        const contextPostId = c && c.post_id ? String(c.post_id).toLowerCase() : '';
                        return contextPostId !== rootPostId;
                    });
                    const contextDepth = filteredContext.length;
                    filteredContext.forEach((c, idx) => {
                        // Mark as context comment so "Continue this thread" doesn't show
                        const contextNode = { ...c, children: [], isContextComment: true };
                        out.push({ ...contextNode, level: idx + 1 });
                    });
                    const focusedWithLevel = { ...targetNode };
                    out.push({ ...focusedWithLevel, level: contextDepth + 1 });
                    const focusedChildren = mergeChildren(targetNode, targetNode.children);
                    if (focusedChildren && focusedChildren.length) {
                        walk(focusedChildren, contextDepth + 2, out);
                    }
                } else {
                    walk([targetNode], 1, out);
                }
                return out;
            }
            // If target not found, fall back to showing nothing under root
            return out;
        }

        walk(base, 1, out);
        return out;
    }, [root, children, state.posts, focusedCommentId, showContext, contextComments, viewerAddress, isViewingComment, actualRootPost]);

    // Compute visibility/collapsed per comment using ancestor stack
    const annotated = React.useMemo(() => {
        const items = flattenedComments;
        const out = [];
        const stack = []; // booleans: collapsed flags of ancestors
        const threshold = getCollapseThreshold();
        items.forEach((n) => {
            while (stack.length > n.level) stack.pop();
            const anyAncestorCollapsed = stack.some(Boolean);
            const hasExplicitCollapse = !!(state.posts && state.posts[n.post_id] && Object.prototype.hasOwnProperty.call(state.posts[n.post_id], 'collapsed'));
            const explicitCollapsed = hasExplicitCollapse ? !!state.posts[n.post_id].collapsed : null;
            const autoCollapsed = !hasExplicitCollapse ? shouldAutoCollapse(n, threshold) : false;
            const isCollapsed = hasExplicitCollapse ? explicitCollapsed : autoCollapsed;
            const isNew = !!(lastVisitTs && n.level > 0 && typeof n.timestamp === 'number' && n.timestamp > lastVisitTs);
            const flash = !!(state.posts[n.post_id]?.flash);
            // Merge updates from state.posts (for edits, etc.)
            const statePost = state.posts[n.post_id];
            const merged = { ...n, hidden: anyAncestorCollapsed, collapsed: isCollapsed, isNew, flash };
            if (statePost) {
                // Merge content, title, topic, edited fields if they exist in state
                if (statePost.content !== undefined) merged.content = statePost.content;
                if (statePost.title !== undefined) merged.title = statePost.title;
                if (statePost.topic !== undefined) merged.topic = statePost.topic;
                if (statePost.root_topic !== undefined) merged.root_topic = statePost.root_topic;
                if (statePost.tag !== undefined) merged.tag = statePost.tag;
                if (statePost.edited !== undefined) merged.edited = statePost.edited;
                if (statePost.edited_ts !== undefined) merged.edited_ts = statePost.edited_ts;
            }
            // If we know the post is edited but don't have edited_ts yet, fall back to backend edited_at
            if (merged.edited && merged.edited_ts === undefined && typeof merged.edited_at === 'number' && merged.edited_at > 0) {
                merged.edited_ts = merged.edited_at;
            }
            out.push(merged);
            stack.push(isCollapsed);
        });
        return out;
    }, [flattenedComments, state.posts, lastVisitTs]);

    // Scroll to a specific comment if hash is present after comments load
    const hasScrolledToHash = React.useRef(false);
    useEffect(() => {
        try {
            if (hasScrolledToHash.current) return;
            const hash = (typeof window !== 'undefined' && window.location && window.location.hash) ? window.location.hash : '';
            let targetId = '';
            if (focusedCommentId && /^[0-9a-f]{64}$/i.test(focusedCommentId)) {
                targetId = `comment-${focusedCommentId.toLowerCase()}`;
            } else if (hash && hash.startsWith('#comment-')) {
                const commentId = hash.slice('#comment-'.length).toLowerCase();
                targetId = `comment-${commentId}`;
            }
            if (!targetId) return;
            const el = document.getElementById(targetId);
            if (el) {
                setTimeout(() => {
                    el.scrollIntoView({ block: 'start', behavior: 'smooth' });
                    hasScrolledToHash.current = true;
                }, 100);
            }
        } catch (_) { }
    }, [annotated, focusedCommentId]);

    const handleShowContext = async (maxDepth = 5, commentIdOverride = null) => {
        const targetCommentId = commentIdOverride || focusedCommentId;
        if (!targetCommentId) return;
        try {
            const params = { comment_id: targetCommentId, max_depth: Math.min(maxDepth, 5) };
            if (state.publicKey) params.address = state.publicKey;
            const res = await Api.get('get_comment_context', params, { timeoutMs: 10000 });
            if (res && Array.isArray(res.context)) {
                setContextComments(res.context.reverse());
                setShowContext(true);
            }
        } catch (err) {
            console.error('[ViewPostView] Failed to load context:', err);
        }
    };

    // Auto-load context when depth param is provided via URL
    const hasAutoLoadedContextRef = useRef(false);
    useEffect(() => {
        if (hasAutoLoadedContextRef.current) return;
        if (!focusedCommentId) return;
        if (depthParam === null || depthParam === 'invalid') return;
        if (depthParam > 0) {
            hasAutoLoadedContextRef.current = true;
            // Pass focusedCommentId directly to avoid closure issues
            handleShowContext(depthParam, focusedCommentId);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [focusedCommentId, depthParam]);

    // Mark reply as viewed when navigating to it via hash or focusedCommentId
    useEffect(() => {
        const hash = window.location.hash;
        let commentId = null;

        if (focusedCommentId && /^[0-9a-f]{64}$/i.test(focusedCommentId)) {
            commentId = focusedCommentId.toLowerCase();
        } else if (hash && hash.startsWith('#comment-')) {
            commentId = hash.slice('#comment-'.length).toLowerCase();
        }

        if (commentId) {
            try {
                Storage.addViewedReplyId(commentId);
            } catch (_) { }
        }
    }, [focusedCommentId, location.hash]);

    // Show loading/error states within the layout (including invalid depth)
    const depthError = depthParam === 'invalid' ? 'Invalid depth parameter. Must be 0-5.' : null;
    if (loading || error || depthError) {
        return (
            <ContentGrid>
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
                        {loading ? (
                            <PostCard $size={cardSize} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: '2rem', gap: '0.35rem' }}>
                                <span style={{ color: '#888' }}>Loading post...</span>
                            </PostCard>
                        ) : (
                            <PostCard $size={cardSize} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', padding: '2rem', gap: '0.5rem' }}>
                                <span style={{ color: '#ff6b6b' }}>{depthError || error}</span>
                            </PostCard>
                        )}
                    </ModernPostFeed>
                </div>
            </ContentGrid>
        );
    }

    const shortenAddress = (address) => {
        if (!address) return "";
        return `${address.substring(0, 10)}...${address.substring(address.length - 4)}`;
    };

    const renderAuthorLink = (currentPost) => {
        if (!currentPost) return null;
        const trimmedUsername = (currentPost.username && String(currentPost.username).trim()) ? String(currentPost.username).trim() : '';
        const fallback = currentPost.user_id === state.publicKey && state.username ? state.username : shortenAddress(currentPost.user_id);
        const display = trimmedUsername || fallback;
        if (!display) return null;
        const displayWithAt = `@${display}`;
        const ownerAddress = currentPost.user_id ? String(currentPost.user_id).trim() : '';
        // New clean URL: prefer username, fallback to address
        const href = trimmedUsername ? `/u/${encodeURIComponent(trimmedUsername)}` : (ownerAddress ? `/u/${encodeURIComponent(ownerAddress)}` : '/profile');
        const tierColor = getTierColor(currentPost.author_level);
        const tierName = getTierName(currentPost.author_level);
        const content = ownerAddress ? (
            <StyledProfileLink to={href} $tierColor={tierColor} data-tooltip={tierName}>{displayWithAt}</StyledProfileLink>
        ) : displayWithAt;
        return content;
    };

    const isValidHash64 = (s) => {
        return (typeof s === 'string') && /^[0-9a-f]{64}$/i.test(s);
    };

    const buildPermaLinkPath = (post) => {
        const rootId = (root && root.post_id) ? String(root.post_id).toLowerCase() : '';
        if (!rootId) return '';
        const rawCommentId = (post && (post.tx_hash || post.post_id)) ? String(post.tx_hash || post.post_id).toLowerCase() : '';
        const validCommentId = isValidHash64(rawCommentId) ? rawCommentId : '';
        const isComment = post && post.post_id && String(post.post_id).toLowerCase() !== rootId;
        // New clean URL format: /p/:postId
        if (isComment && validCommentId) {
            // For comments, link directly to the comment (no depth = single comment view)
            return `/p/${encodeURIComponent(validCommentId)}`;
        }
        return `/p/${encodeURIComponent(rootId)}`;
    };

    const handleShare = async (post) => {
        try {
            const path = buildPermaLinkPath(post);
            const origin = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
            const url = origin + path;
            const title = (root && root.title) ? String(root.title) : 'Mirage';
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
                    const shareData = { title, text, url };
                    // Try to include image if available (Web Share API Level 2)
                    if (thumbnailUrl && navigator.canShare) {
                        try {
                            const response = await fetch(thumbnailUrl);
                            const blob = await response.blob();
                            const file = new File([blob], 'thumbnail.jpg', { type: blob.type || 'image/jpeg' });
                            const testShareData = { ...shareData, files: [file] };
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
                setShareMessages(prev => ({ ...prev, [post.post_id]: { type: 'success', message: 'link copied to clipboard' } }));
                setTimeout(() => {
                    setShareMessages(prev => { const n = { ...prev }; delete n[post.post_id]; return n; });
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

    const displayConfirmation = (post) => {
        // Show confirmation for this specific post
        if (confirmBlockPost === post.post_id) {
            return (
                <BlockConfirmMessage>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                        <span style={{ whiteSpace: 'nowrap' }}>🚫 Block this post?</span>
                        <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0, width: 'auto' }}>
                            <Button variant="warning" size="sm" onClick={confirmBlockPostAction} disabled={isBlocking}>
                                Block
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelBlockPost}>Cancel</Button>
                        </ConfirmButtons>
                    </div>
                </BlockConfirmMessage>
            );
        }
        if (confirmBlockUser?.postId === post.post_id) {
            return (
                <BlockConfirmMessage>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                        <span style={{ whiteSpace: 'nowrap' }}>🚫 Block {post.username || 'this user'}?</span>
                        <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0, width: 'auto' }}>
                            <Button variant="warning" size="sm" onClick={confirmBlockUserAction} disabled={isBlocking}>
                                Block
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelBlockUser}>Cancel</Button>
                        </ConfirmButtons>
                    </div>
                </BlockConfirmMessage>
            );
        }
        if (confirmDeletePost === post.post_id) {
            const isComment = post.target && post.target !== '';
            return (
                <BlockConfirmMessage>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                        <span style={{ whiteSpace: 'nowrap' }}>⚠ Mark {isComment ? 'comment' : 'post'} as deleted?</span>
                        <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0, width: 'auto' }}>
                            <Button variant="warning" size="sm" onClick={confirmDeletePostAction} disabled={isDeleting}>
                                Delete
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelDeletePost}>Cancel</Button>
                        </ConfirmButtons>
                    </div>
                </BlockConfirmMessage>
            );
        }

        if (confirmSuspendQuests?.postId === post.post_id) {
            return (
                <BlockConfirmMessage>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                        <span style={{ whiteSpace: 'nowrap' }}>🛡️ Suspend this user from quests:</span>
                        <select
                            value={suspendDuration}
                            onChange={(e) => setSuspendDuration(Number(e.target.value))}
                            style={{ padding: '0.25rem 0.5rem', borderRadius: '4px', border: '1px solid #d97706', background: '#fef3c7', color: '#92400e', fontWeight: 500 }}
                        >
                            <option value={1}>1 day</option>
                            <option value={3}>3 days</option>
                            <option value={7}>7 days</option>
                            <option value={30}>30 days</option>
                            <option value={0}>Permanent</option>
                        </select>
                        <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0, width: 'auto' }}>
                            <Button variant="warning" size="sm" onClick={confirmSuspendFromQuests} disabled={isSuspending}>
                                {isSuspending ? 'Suspending...' : 'Suspend'}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelSuspendFromQuests}>Cancel</Button>
                        </ConfirmButtons>
                    </div>
                </BlockConfirmMessage>
            );
        }

        if (confirmUnsuspendQuests?.postId === post.post_id) {
            return (
                <BlockConfirmMessage>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                        <span style={{ whiteSpace: 'nowrap' }}>🛡️ Unsuspend this user from quests?</span>
                        <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0, width: 'auto' }}>
                            <Button variant="warning" size="sm" onClick={confirmUnsuspendFromQuests} disabled={isUnsuspending}>
                                {isUnsuspending ? 'Unsuspending...' : 'Unsuspend'}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelUnsuspendFromQuests}>Cancel</Button>
                        </ConfirmButtons>
                    </div>
                </BlockConfirmMessage>
            );
        }

        if (suspendSuccess[post.post_id]) {
            return (
                <div style={{
                    background: 'rgba(34, 197, 94, 0.1)',
                    border: '1px solid #22c55e',
                    borderRadius: '3px',
                    padding: '0.75rem 1rem',
                    margin: '0.5rem 0',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    color: '#16a34a',
                    fontSize: '0.8rem',
                }}>
                    <span>✓</span>
                    {suspendSuccess[post.post_id]}
                </div>
            );
        }

        if (confirmReportPost === post.post_id) {
            return (
                <BlockConfirmMessage>
                    <span>🚨 Report this post? Provide a short reason.</span>
                    <ReportInput
                        type="text"
                        value={reportReason}
                        onChange={(e) => setReportReason(e.target.value)}
                        placeholder="Short reason (max 140 chars)"
                        maxLength={140}
                    />
                    <ConfirmButtons style={{ width: 'auto' }}>
                        <Button variant="warning" size="sm" onClick={confirmReportAction} disabled={isReporting}>
                            Report
                        </Button>
                        <Button variant="ghost" size="sm" onClick={cancelReport}>Cancel</Button>
                    </ConfirmButtons>
                </BlockConfirmMessage>
            );
        }

        if (confirmDonate?.postId === post.post_id) {
            return (
                <BlockConfirmMessage>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                        <span style={{ whiteSpace: 'nowrap' }}>
                            💰 Donate to {post.username || post.user_id.substring(0, 12) + '...'}:
                        </span>
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.35rem',
                            background: theme?.colors?.surface2 || theme?.colors?.panelAlt || 'rgba(0, 0, 0, 0.3)',
                            border: `1px solid ${theme?.colors?.borderSubtle || 'rgba(148, 163, 184, 0.3)'}`,
                            borderRadius: '8px',
                            padding: '0.2rem 0.5rem',
                        }}>
                            <input
                                type="text"
                                inputMode="numeric"
                                value={formatDonateAmount(donateAmount)}
                                onChange={(e) => handleDonateAmountChange(e.target.value)}
                                placeholder="10,000"
                                maxLength={11}
                                style={{
                                    width: '5.5rem',
                                    background: 'transparent',
                                    border: 'none',
                                    outline: 'none',
                                    color: theme?.colors?.text || 'inherit',
                                    fontSize: '0.8rem',
                                    fontWeight: 700,
                                    textAlign: 'right',
                                }}
                            />
                            <span style={{ fontSize: '0.68rem', opacity: 0.7 }}>MIRAGE</span>
                        </div>
                        <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0, width: 'auto' }}>
                            <Button variant="warning" size="sm" onClick={confirmDonateAction} disabled={isDonating}>
                                {isDonating ? 'Sending...' : 'Send'}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelDonate}>Cancel</Button>
                        </ConfirmButtons>
                    </div>
                </BlockConfirmMessage>
            );
        }

        const donateMsg = donateMessages[post.post_id];
        if (donateMsg) {
            return (
                <>
                    {donateMsg.type === 'error' ? (
                        <BlockErrorMessage>
                            <span>⚠</span>
                            {donateMsg.message}
                        </BlockErrorMessage>
                    ) : (
                        <BlockSuccessMessage>
                            <span>✓</span>
                            {donateMsg.message}
                        </BlockSuccessMessage>
                    )}
                </>
            );
        }

        // Show delete-specific messages for this post
        const deleteMsg = deleteMessages[post.post_id];
        if (deleteMsg) {
            return (
                <>
                    {deleteMsg.type === 'error' ? (
                        <BlockErrorMessage>
                            <span>⚠</span>
                            {deleteMsg.message}
                        </BlockErrorMessage>
                    ) : (
                        <BlockSuccessMessage>
                            <span>✓</span>
                            {deleteMsg.message}
                        </BlockSuccessMessage>
                    )}
                </>
            );
        }

        // Show report messages for this post
        const repMsg = reportMessages[post.post_id];
        if (repMsg) {
            return (
                <>
                    {repMsg.type === 'error' ? (
                        <BlockErrorMessage>
                            <span>⚠</span>
                            {repMsg.message}
                        </BlockErrorMessage>
                    ) : (
                        <BlockSuccessMessage>
                            <span>✓</span>
                            {repMsg.message}
                        </BlockSuccessMessage>
                    )}
                </>
            );
        }

        // Show share success message for this post
        const shMsg = shareMessages[post.post_id];
        if (shMsg) {
            return (
                <>
                    <BlockSuccessMessage>
                        <span>✓</span>
                        {shMsg.message}
                    </BlockSuccessMessage>
                </>
            );
        }

        // Show error/success messages (only for root post to avoid duplicates)
        if (post.level === 0 || post.post_id === root.post_id) {
            return (
                <>
                    {blockError && (
                        <BlockErrorMessage>
                            <span>⚠</span>
                            {blockError}
                        </BlockErrorMessage>
                    )}
                    {blockSuccess && (
                        <BlockSuccessMessage>
                            <span>✓</span>
                            {blockSuccess}
                        </BlockSuccessMessage>
                    )}
                </>
            );
        }

        return null;
    };

    const renderPostMenu = (post) => {
        const publicKeyStr = String(state.publicKey || '').trim();
        const hasValidAccount = publicKeyStr && publicKeyStr !== 'guest';
        const isOwnPost = post && state && (post.user_id === state.publicKey);
        const userLevel = Number(Storage.load('user_level', '0')) || 0;
        const isAdmin = hasValidAccount && userLevel >= 100;
        const isOpen = openMenuId === post.post_id;
        const authorAddr = String(post.user_id || '').trim().toLowerCase();
        const isFollowingThisAuthor = isFollowingAuthor(authorAddr);

        const userSuspendedStatus = post.user_id ? userSuspendedMap[post.user_id] : undefined;

        const handleMenuClick = (e) => {
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

        return (
            <MenuContainer>
                <MenuButton
                    ref={el => menuButtonRefs.current[post.post_id] = el}
                    onClick={handleMenuClick}
                    aria-label="Post menu"
                >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="1.5"></circle>
                        <circle cx="12" cy="5" r="1.5"></circle>
                        <circle cx="12" cy="19" r="1.5"></circle>
                    </svg>
                </MenuButton>
                {isOpen && ReactDOM.createPortal(
                    <MenuDropdown
                        ref={menuDropdownRef}
                        style={{ top: menuPosition.top, left: menuPosition.left }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        {isOwnPost && (
                            <>
                                <MenuItem onClick={() => {
                                    setOpenMenuId(null);
                                    const isRoot = !!(post.title && String(post.title).trim() !== '');
                                    if (isRoot) {
                                        navigate(`/create_post?post_id=${post.post_id}&edit=true`);
                                    } else {
                                        openEdit(post);
                                    }
                                }}>Edit</MenuItem>
                                <MenuItem onClick={() => { setOpenMenuId(null); handleDeletePost(post.post_id); }} data-danger="true">Delete</MenuItem>
                            </>
                        )}
                        {!isOwnPost && hasValidAccount && (
                            <>
                                <MenuItem onClick={() => {
                                    setOpenMenuId(null);
                                    handleFollowToggle(authorAddr);
                                }}>
                                    {isUserPending(authorAddr)
                                        ? formatUserStatus(authorAddr)
                                        : (isFollowingThisAuthor ? 'Unfollow user' : 'Follow user')}
                                </MenuItem>
                                <MenuItem onClick={() => { setOpenMenuId(null); handleDonate(post.user_id, post.post_id); }}>Donate</MenuItem>
                                <MenuItem onClick={() => { setOpenMenuId(null); handleBlockUser(post.user_id, post.post_id); }} data-danger="true">Block user</MenuItem>
                                <MenuItem onClick={() => { setOpenMenuId(null); handleBlockPost(post.post_id); }} data-danger="true">Block post</MenuItem>
                                {!isAdmin && (
                                    <MenuItem onClick={() => { setOpenMenuId(null); handleReport(post.post_id); }}>Report</MenuItem>
                                )}
                                {isAdmin && (
                                    <>
                                        <MenuItem onClick={() => { setOpenMenuId(null); handleDeletePost(post.post_id); }} data-danger="true">🛡️ Mark post deleted</MenuItem>
                                        {questsEnabled && userSuspendedStatus !== true && (
                                            <MenuItem onClick={() => { setOpenMenuId(null); handleSuspendFromQuests(post.user_id, post.post_id); }} data-danger="true">🛡️ Suspend from quests</MenuItem>
                                        )}
                                        {questsEnabled && userSuspendedStatus === true && (
                                            <MenuItem onClick={() => { setOpenMenuId(null); handleUnsuspendFromQuests(post.user_id, post.post_id); }}>🛡️ Unsuspend from quests</MenuItem>
                                        )}
                                    </>
                                )}
                            </>
                        )}
                    </MenuDropdown>,
                    document.body
                )}
            </MenuContainer>
        );
    };

    const renderActionBar = (post) => {
        const publicKeyStr = String(state.publicKey || '').trim();
        const hasValidAccount = publicKeyStr && publicKeyStr !== 'guest';

        if (!hasValidAccount) {
            return (
                <MetaRow>
                    <VoteSection inline state={state} post={post} updatePost={updatePost} />
                    <MetaSeparatorAction>•</MetaSeparatorAction>
                    <Link to="/create_account" style={{ fontSize: '0.7rem', color: 'inherit', textDecoration: 'underline' }}>Sign in to participate</Link>
                </MetaRow>
            );
        }

        return (
            <MetaRow>
                <VoteSection inline state={state} post={post} updatePost={updatePost} />
                <MetaSeparatorAction>•</MetaSeparatorAction>
                <ActionButton onClick={() => toggleReply(post.post_id)} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                    <Icon aria-hidden="true">
                        <svg viewBox="0 0 24 24">
                            <path d="M4 4h16v12H5.17L4 17.17V4zm0-2a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H4z"></path>
                        </svg>
                    </Icon>
                    <span>reply</span>
                </ActionButton>
                <MetaSeparatorAction>•</MetaSeparatorAction>
                <ActionButton onClick={() => handleShare(post)} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                    <Icon aria-hidden="true">
                        <svg viewBox="0 0 458.624 458.624">
                            <path d="M339.588,314.529c-14.215,0-27.456,4.133-38.621,11.239l-112.682-78.67c1.809-6.315,2.798-12.976,2.798-19.871 c0-6.896-0.989-13.557-2.798-19.871l109.64-76.547c11.764,8.356,26.133,13.286,41.662,13.286c39.79,0,72.047-32.257,72.047-72.047 C411.634,32.258,379.378,0,339.588,0c-39.79,0-72.047,32.257-72.047,72.047c0,5.255,0.578,10.373,1.646,15.308l-112.424,78.491 c-10.974-6.759-23.892-10.666-37.727-10.666c-39.79,0-72.047,32.257-72.047,72.047s32.256,72.047,72.047,72.047 c13.834,0,26.753-3.907,37.727-10.666l113.292,79.097c-1.629,6.017-2.514,12.34-2.514,18.872c0,39.79,32.257,72.047,72.047,72.047 c39.79,0,72.047-32.257,72.047-72.047C411.635,346.787,379.378,314.529,339.588,314.529z" fill="currentColor" />
                        </svg>
                    </Icon>
                    <span className="share-text">share</span>
                </ActionButton>
            </MetaRow>
        );
    };

    const getVideoThumbnailUrl = (url) => {
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
        if (!state.posts[post.post_id]?.replyOpen)
            return <div></div>

        const isEdit = state.posts[post.post_id]?.replyMode === 'edit';

        // On mobile, don't render inline reply (use overlay instead) - except for edits
        if (isMobile && !isEdit && !forMobileOverlay)
            return <div></div>;
        const isBusy = (isEdit && !!state.posts[post.post_id]?.editBusy) || (!isEdit && !!state.posts[post.post_id]?.replyBusy);
        const replyText = state.posts[post.post_id]?.replyText || "";
        return (
            <form
                onSubmit={(e) => {
                    if (isEdit) {
                        e.preventDefault();
                        handleEditSubmit(post);
                    } else {
                        handleSubmit(post.post_id)(e);
                    }
                }}
                onKeyDown={(e) => {
                    if (e.key !== 'Tab') return;
                    const form = e.currentTarget;
                    const focusable = form.querySelectorAll(
                        'input:not([type="hidden"]):not([tabindex="-1"]):not(:disabled), textarea:not(:disabled), button:not([tabindex="-1"]):not(:disabled)'
                    );
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
                <div
                    style={{ display: 'flex', flexDirection: 'column' }}
                    onDragOver={(e) => handleReplyDragOver(post.post_id, e)}
                    onDragLeave={(e) => handleReplyDragLeave(post.post_id, e)}
                    onDrop={(e) => handleReplyDrop(post.post_id, e)}
                >
                    <StyledReply offsetLeft={'0rem'} style={{ marginTop: isEdit ? '0.2rem' : '0.4rem', position: 'relative' }}>
                        <MediaRow>
                            <StickerPicker
                                onSelect={(stickerUrl) => {
                                    setReplyAttachedType(prev => ({ ...prev, [post.post_id]: 'image' }));
                                    setReplyAttachedUrl(prev => ({ ...prev, [post.post_id]: stickerUrl }));
                                    setReplyThumbLoading(prev => ({ ...prev, [post.post_id]: true }));
                                }}
                                disabled={isBusy || !!replyIsUploading[post.post_id] || !!replyAttachedUrl[post.post_id]}
                            />
                            <GifPicker
                                onSelect={(gifUrl) => {
                                    setReplyAttachedType(prev => ({ ...prev, [post.post_id]: 'image' }));
                                    setReplyAttachedUrl(prev => ({ ...prev, [post.post_id]: gifUrl }));
                                    setReplyThumbLoading(prev => ({ ...prev, [post.post_id]: true }));
                                }}
                                disabled={isBusy || !!replyIsUploading[post.post_id] || !!replyAttachedUrl[post.post_id]}
                            />
                            <MediaIconButton
                                type="button"
                                tabIndex={-1}
                                onClick={() => {
                                    try {
                                        const api = replyEditorUpload[post.post_id];
                                        if (!api || typeof api.selectFile !== 'function') return;
                                        if (replyIsUploading[post.post_id]) return;
                                        api.selectFile();
                                    } catch (_) { }
                                }}
                                disabled={isBusy || !!replyIsUploading[post.post_id] || !replyEditorUpload[post.post_id] || !!replyAttachedUrl[post.post_id]}
                                aria-label="Upload"
                                title="Upload"
                            >
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                                    <polyline points="17 8 12 3 7 8" />
                                    <line x1="12" y1="3" x2="12" y2="15" />
                                </svg>
                            </MediaIconButton>
                            {(replyIsUploading[post.post_id] || (replyAttachedType[post.post_id] && replyAttachedUrl[post.post_id])) && (
                                <MediaPreviewWrapper>
                                    {replyAttachedType[post.post_id] && replyAttachedUrl[post.post_id] && !replyIsUploading[post.post_id] && (
                                        <>
                                            <MediaPreviewImage
                                                src={
                                                    replyAttachedType[post.post_id] === 'image'
                                                        ? replyAttachedUrl[post.post_id]
                                                        : (getVideoThumbnailUrl(replyAttachedUrl[post.post_id]) || replyAttachedUrl[post.post_id])
                                                }
                                                alt=""
                                                onLoad={() => {
                                                    setReplyThumbLoading(prev => {
                                                        const next = { ...prev };
                                                        delete next[post.post_id];
                                                        return next;
                                                    });
                                                }}
                                                onError={() => {
                                                    setReplyThumbLoading(prev => {
                                                        const next = { ...prev };
                                                        delete next[post.post_id];
                                                        return next;
                                                    });
                                                }}
                                            />
                                            {replyThumbLoading[post.post_id] && (
                                                <MediaSpinner />
                                            )}
                                            <MediaRemoveButton
                                                type="button"
                                                tabIndex={-1}
                                                disabled={isBusy}
                                                onClick={() => {
                                                    if (isBusy) return;
                                                    setReplyAttachedType(prev => { const n = { ...prev }; delete n[post.post_id]; return n; });
                                                    setReplyAttachedUrl(prev => { const n = { ...prev }; delete n[post.post_id]; return n; });
                                                    setReplyThumbLoading(prev => { const n = { ...prev }; delete n[post.post_id]; return n; });
                                                }}
                                                aria-label="Remove attached media"
                                                title="Remove attached media"
                                            >
                                                ×
                                            </MediaRemoveButton>
                                        </>
                                    )}
                                    {replyIsUploading[post.post_id] && (
                                        <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '0.5rem', boxSizing: 'border-box' }}>
                                            <span style={{ fontSize: '0.7rem', color: '#888', marginBottom: '0.25rem' }}>
                                                Uploading {replyUploadProgress[post.post_id] !== undefined ? `${Math.round(replyUploadProgress[post.post_id])}%` : '...'}
                                            </span>
                                            <Button
                                                variant="danger"
                                                size="xs"
                                                tabIndex={-1}
                                                onClick={() => {
                                                    try {
                                                        const api = replyEditorUpload[post.post_id];
                                                        if (api && typeof api.cancelUpload === 'function') {
                                                            api.cancelUpload();
                                                        }
                                                    } catch (_) { }
                                                }}
                                            >
                                                Cancel
                                            </Button>
                                        </div>
                                    )}
                                </MediaPreviewWrapper>
                            )}
                        </MediaRow>
                        <div style={{ position: 'relative' }}>
                            <MarkdownEditor
                                value={replyText}
                                onChange={(v) => handleReplyChange(post.post_id, v)}
                                maxLength={limits.maxContent}
                                disabled={isBusy}
                                autoFocus={true}
                                onSubmitShortcut={() => {
                                    if (isEdit) {
                                        handleEditSubmit(post);
                                    } else {
                                        try { handleSubmit(post.post_id)({ preventDefault() { }, stopPropagation() { } }); } catch (_) { }
                                    }
                                }}
                                showCounters={false}
                                toolbarButtonSize="1.5rem"
                                toolbarIconSize="0.95rem"
                                toolbarTopGap="0.35rem"
                                registerUploadHandler={(api) => {
                                    setReplyEditorUpload(prev => ({ ...prev, [post.post_id]: api }));
                                }}
                                renderHelperRow={false}
                                onMediaUploaded={(type, url, error) => {
                                    if (error) {
                                        // Clear attachment state on error
                                        setReplyAttachedType(prev => { const n = { ...prev }; delete n[post.post_id]; return n; });
                                        setReplyAttachedUrl(prev => { const n = { ...prev }; delete n[post.post_id]; return n; });
                                        setReplyThumbLoading(prev => { const n = { ...prev }; delete n[post.post_id]; return n; });
                                        // Clear existing timeout if any
                                        try {
                                            const t = replyErrorClearTimeoutRef.current?.[post.post_id];
                                            if (t) {
                                                clearTimeout(t);
                                                delete replyErrorClearTimeoutRef.current[post.post_id];
                                            }
                                        } catch (_) { /* noop */ }
                                        // Set error message
                                        setReplySubmitError(prev => ({ ...prev, [post.post_id]: error }));
                                        // Auto-clear after 5s
                                        const tid = setTimeout(() => {
                                            setReplySubmitError(prev => {
                                                const next = { ...prev };
                                                delete next[post.post_id];
                                                return next;
                                            });
                                            try { delete replyErrorClearTimeoutRef.current[post.post_id]; } catch (_) { /* noop */ }
                                        }, 5000);
                                        try { replyErrorClearTimeoutRef.current[post.post_id] = tid; } catch (_) { /* noop */ }
                                    } else if (!type || !url) {
                                        // Generic failure without explicit error
                                        setReplyAttachedType(prev => { const n = { ...prev }; delete n[post.post_id]; return n; });
                                        setReplyAttachedUrl(prev => { const n = { ...prev }; delete n[post.post_id]; return n; });
                                        setReplyThumbLoading(prev => { const n = { ...prev }; delete n[post.post_id]; return n; });
                                        // Show default message
                                        const msg = 'Media upload failed. Please try again.';
                                        // Clear any prior timer and set new message
                                        try {
                                            const t = replyErrorClearTimeoutRef.current?.[post.post_id];
                                            if (t) {
                                                clearTimeout(t);
                                                delete replyErrorClearTimeoutRef.current[post.post_id];
                                            }
                                        } catch (_) { /* noop */ }
                                        setReplySubmitError(prev => ({ ...prev, [post.post_id]: msg }));
                                        const tid = setTimeout(() => {
                                            setReplySubmitError(prev => {
                                                const next = { ...prev };
                                                delete next[post.post_id];
                                                return next;
                                            });
                                            try { delete replyErrorClearTimeoutRef.current[post.post_id]; } catch (_) { /* noop */ }
                                        }, 5000);
                                        try { replyErrorClearTimeoutRef.current[post.post_id] = tid; } catch (_) { /* noop */ }
                                    } else {
                                        // Success: attach media
                                        setReplyAttachedType(prev => ({ ...prev, [post.post_id]: type }));
                                        setReplyAttachedUrl(prev => ({ ...prev, [post.post_id]: url }));
                                        setReplyThumbLoading(prev => ({ ...prev, [post.post_id]: true }));
                                        // Clear any stale error
                                        setReplySubmitError(prev => { const n = { ...prev }; delete n[post.post_id]; return n; });
                                        try {
                                            const t = replyErrorClearTimeoutRef.current?.[post.post_id];
                                            if (t) {
                                                clearTimeout(t);
                                                delete replyErrorClearTimeoutRef.current[post.post_id];
                                            }
                                        } catch (_) { /* noop */ }
                                    }
                                }}
                                onUploadStateChange={(uploading) => {
                                    setReplyIsUploading(prev => ({ ...prev, [post.post_id]: uploading }));
                                    if (!uploading) {
                                        setReplyUploadProgress(prev => {
                                            const next = { ...prev };
                                            delete next[post.post_id];
                                            return next;
                                        });
                                    }
                                }}
                                onUploadProgress={(progress) => {
                                    setReplyUploadProgress(prev => ({ ...prev, [post.post_id]: progress ?? undefined }));
                                }}
                                suffixLabel={limits.willPayFee ? '(paid tier)' : '(free tier)'}
                                showUploadButton={false}
                                belowElement={replySubmitError[post.post_id] ? (<ReplyErrorMessage role="alert">{replySubmitError[post.post_id]}</ReplyErrorMessage>) : null}
                            />
                        </div>
                        <ReplyActionsRow>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', minWidth: 0, flex: '1 1 auto', alignSelf: 'flex-start' }}>
                                <ReplyCounter $warn={replyText.length > limits.maxContent * 0.9}>
                                    {replyText.length} / {limits.maxContent} {limits.willPayFee ? '(paid tier)' : '(free tier)'}
                                </ReplyCounter>
                            </div>
                            <StyledSubmitButtonContainer>
                                <Button
                                    type="submit"
                                    size="sm"
                                    disabled={isBusy || !!replyIsUploading[post.post_id]}
                                    loading={isBusy}
                                >
                                    {isBusy
                                        ? (replySubmitStatus[post.post_id] === 'solving' ? `Solving PoW... (${(replyElapsedTime[post.post_id] || 0).toFixed(1)}s)` :
                                            replySubmitStatus[post.post_id] === 'submitting' ? `Submitting... (${(replyElapsedTime[post.post_id] || 0).toFixed(1)}s)` :
                                                replySubmitStatus[post.post_id] === 'verifying' ? `Verifying... (${(replyElapsedTime[post.post_id] || 0).toFixed(1)}s)` :
                                                    `Solving PoW... (${(replyElapsedTime[post.post_id] || 0).toFixed(1)}s)`)
                                        : (isEdit
                                            ? 'Save Edit'
                                            : (replyIsUploading[post.post_id] ? 'Uploading…' : 'Submit'))}
                                </Button>
                                <Button type="button" variant="ghost" size="sm" onClick={() => closeReply(post.post_id)} disabled={isBusy}>Cancel</Button>
                            </StyledSubmitButtonContainer>
                        </ReplyActionsRow>
                    </StyledReply>
                </div>
            </form>
        );
    }


    const toggleCollapsed = (postId, currentVisible) => {
        const hasVisible = (typeof currentVisible === 'boolean');
        const current = hasVisible ? currentVisible : !!(state.posts[postId]?.collapsed);
        updatePost(postId, { collapsed: !current });
    };

    // Merge root with any optimistic/local updates from state.posts for immediate UI reflection (title/topic/content edits)
    const mergedRoot = (() => {
        try {
            if (!root || !root.post_id) return root;
            const sp = (state && state.posts) ? state.posts[root.post_id] : undefined;
            if (!sp) return root;
            const out = { ...root };
            if (sp.title !== undefined) out.title = sp.title;
            if (sp.topic !== undefined) out.topic = sp.topic;
            if (sp.root_topic !== undefined) out.root_topic = sp.root_topic;
            if (sp.tag !== undefined) out.tag = sp.tag;
            if (sp.content !== undefined) out.content = sp.content;
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

        return ReactDOM.createPortal(
            <MobileReplyOverlay ref={mobileReplyOverlayRef}>
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
            </MobileReplyOverlay>,
            document.body
        );
    };

    // Check if user is logged in
    const isLoggedIn = viewerAddress && viewerAddress !== 'guest';

    // Redirect non-logged-in users to home (shows welcome banner)
    if (!isLoggedIn) {
        return <Navigate to="/home" replace />;
    }

    if (root) {
        const origin = typeof window !== 'undefined' && window.location && window.location.origin ? window.location.origin : 'https://mirage.vote';
        const postUrl = `${origin}/view_post?post_id=${root.post_id}`;
        const postTitle = mergedRoot && mergedRoot.title ? String(mergedRoot.title).trim() : (root && root.title ? String(root.title).trim() : 'Mirage');
        const postDescription = mergedRoot && mergedRoot.content ? String(mergedRoot.content).trim().substring(0, 200) : (root && root.content ? String(root.content).trim().substring(0, 200) : 'Decentralized social network');
        const imageUrl = `${origin}/images/logo.webp`;

        return (
            <ContentGrid>
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
                            const displayTopic = mergedRoot?.topic || root?.topic || '';
                            const topicLower = displayTopic.toLowerCase();
                            const isTopicFollowing = isSubscribedTopic(topicLower);
                            const isTopicInProgress = isTopicPending(topicLower);
                            const hasValidAccount = state.publicKey && state.publicKey !== 'guest';

                            return (
                                <TopicHeroWrapper>
                                    <TopicHeroCard role="region" aria-label="Topic context">
                                        {/* Mobile: Top row with Back button and Follow button */}
                                        <TopicHeroTopRow>
                                            <BackButton onClick={goBackToFeed} style={{ padding: 0, margin: 0, fontSize: '0.8rem' }}>
                                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: '14px', height: '14px' }}>
                                                    <line x1="19" y1="12" x2="5" y2="12"></line>
                                                    <polyline points="12 19 5 12 12 5"></polyline>
                                                </svg>
                                                Back
                                            </BackButton>
                                            {hasValidAccount && (
                                                <Button
                                                    variant={
                                                        (isTopicFollowing && topicFollowHover)
                                                            ? 'primaryDanger'
                                                            : isTopicFollowing
                                                                ? 'subtle'
                                                                : 'primary'
                                                    }
                                                    size="pill"
                                                    onMouseEnter={() => setTopicFollowHover(true)}
                                                    onMouseLeave={() => setTopicFollowHover(false)}
                                                    onClick={() => {
                                                        if (!isTopicInProgress && displayTopic) {
                                                            handleTopicFollowToggle(displayTopic);
                                                        }
                                                    }}
                                                    disabled={isTopicInProgress}
                                                    loading={isTopicInProgress}
                                                >
                                                    {isTopicInProgress
                                                        ? formatTopicStatus(topicLower)
                                                        : isTopicFollowing
                                                            ? (topicFollowHover ? 'Unfollow' : 'Following')
                                                            : 'Follow'}
                                                </Button>
                                            )}
                                        </TopicHeroTopRow>

                                        {/* Desktop: Back section */}
                                        <TopicHeroBackSection>
                                            <BackButton onClick={goBackToFeed} style={{ padding: 0, margin: 0, fontSize: '0.8rem' }}>
                                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: '14px', height: '14px' }}>
                                                    <line x1="19" y1="12" x2="5" y2="12"></line>
                                                    <polyline points="12 19 5 12 12 5"></polyline>
                                                </svg>
                                                Back
                                            </BackButton>
                                        </TopicHeroBackSection>

                                        {/* Desktop: Follow button */}
                                        <TopicAction>
                                            {hasValidAccount && (
                                                <Button
                                                    variant={
                                                        (isTopicFollowing && topicFollowHover)
                                                            ? 'primaryDanger'
                                                            : isTopicFollowing
                                                                ? 'subtle'
                                                                : 'primary'
                                                    }
                                                    size="pill"
                                                    minWidth="follow"
                                                    onMouseEnter={() => setTopicFollowHover(true)}
                                                    onMouseLeave={() => setTopicFollowHover(false)}
                                                    onClick={() => {
                                                        if (!isTopicInProgress && displayTopic) {
                                                            handleTopicFollowToggle(displayTopic);
                                                        }
                                                    }}
                                                    disabled={isTopicInProgress}
                                                    loading={isTopicInProgress}
                                                >
                                                    {isTopicInProgress
                                                        ? formatTopicStatus(topicLower)
                                                        : isTopicFollowing
                                                            ? (topicFollowHover ? `Unfollow #${displayTopic}` : `Following #${displayTopic}`)
                                                            : `Follow #${displayTopic}`}
                                                </Button>
                                            )}
                                        </TopicAction>
                                    </TopicHeroCard>
                                </TopicHeroWrapper>
                            );
                        })()}
                        {annotated.filter((p) => !p.hidden && !deletedPosts.has(p.post_id)).map((post) => {
                            const normalizedPostId = String(post.post_id).toLowerCase();
                            const isRoot = post.level === 0;
                            const isCollapsed = !!(post.level > 0 && post.collapsed);
                            const CardComponent = isRoot ? PostCard : CommentCard;
                            // Flash: root uses rootFlash state, comments use post.flash
                            const shouldFlash = isRoot ? rootFlash : !!post.flash;
                            const displayLevel = post.level;
                            // Persistent highlight for inbox-linked comments
                            const isHighlighted = !isRoot && normalizedHighlightId && normalizedPostId === normalizedHighlightId;

                            return (
                                <div id={`comment-${normalizedPostId}`} key={post.post_id}>
                                    <CardComponent
                                        className={isHighlighted ? 'inbox-highlight' : undefined}
                                        $isFlash={shouldFlash}
                                        $isNew={!!(lastVisitTs && post.level > 0 && typeof post.timestamp === 'number' && post.timestamp > lastVisitTs)}
                                        $isCollapsed={isCollapsed}
                                        $level={displayLevel}
                                        $size={cardSize}
                                    >
                                        <ColumnFlex>
                                            {/* Mobile root post meta - two rows */}
                                            {isRoot && (
                                                <MobileRootMeta>
                                                    <MobileRootMetaTop>
                                                        {renderAuthorLink(post)}
                                                        {renderPostMenu(post)}
                                                    </MobileRootMetaTop>
                                                    <MobileRootMetaBottom>
                                                        {(() => {
                                                            const topicLabel =
                                                                post.topic ||
                                                                post.root_topic ||
                                                                mergedRoot?.topic ||
                                                                mergedRoot?.root_topic ||
                                                                root?.topic ||
                                                                root?.root_topic ||
                                                                '';
                                                            return topicLabel ? (
                                                                <StyledTopicLink to={`/t/${encodeURIComponent(topicLabel.toLowerCase())}`}>#{topicLabel}</StyledTopicLink>
                                                            ) : null;
                                                        })()}
                                                        <MetaSeparator>·</MetaSeparator>
                                                        <span>{formatElapsed(post.timestamp)} ago</span>
                                                        {(() => {
                                                            const tagLabel =
                                                                post.tag ||
                                                                mergedRoot?.tag ||
                                                                root?.tag ||
                                                                '';
                                                            return tagLabel ? (
                                                                <>
                                                                    <MetaSeparator>·</MetaSeparator>
                                                                    <TagBadge $tag={tagLabel}>{tagLabel}</TagBadge>
                                                                </>
                                                            ) : null;
                                                        })()}
                                                        {post.edited && (
                                                            <>
                                                                <MetaSeparator>·</MetaSeparator>
                                                                <span style={{ fontStyle: 'italic' }}>edited</span>
                                                            </>
                                                        )}
                                                    </MobileRootMetaBottom>
                                                </MobileRootMeta>
                                            )}
                                            {/* Desktop meta info row (hidden on mobile for root posts) */}
                                            <DesktopMetaInfoRow $hideOnMobile={isRoot}>
                                                <MetaInfoRowLeft>
                                                    {!isRoot && (
                                                        <>
                                                            <span
                                                                onClick={() => toggleCollapsed(post.post_id, !!post.collapsed)}
                                                                style={{ cursor: 'pointer', fontWeight: 'bold' }}
                                                                aria-label={post.collapsed ? 'Expand' : 'Collapse'}
                                                            >
                                                                [{post.collapsed ? '+' : '−'}]
                                                            </span>
                                                            <MetaSeparator>·</MetaSeparator>
                                                        </>
                                                    )}
                                                    {renderAuthorLink(post)}
                                                    <MetaSeparator>·</MetaSeparator>
                                                    <TooltipContainer>
                                                        <span>{formatElapsed(post.timestamp)} ago</span>
                                                        <TooltipText>{formatTimeStamp(post.timestamp)}</TooltipText>
                                                    </TooltipContainer>
                                                    {/* Only show topic for root posts - comments inherit from root */}
                                                    {isRoot && (() => {
                                                        const topicLabel =
                                                            post.topic ||
                                                            post.root_topic ||
                                                            mergedRoot?.topic ||
                                                            mergedRoot?.root_topic ||
                                                            root?.topic ||
                                                            root?.root_topic ||
                                                            '';
                                                        return topicLabel ? (
                                                            <>
                                                                <MetaSeparator>·</MetaSeparator>
                                                                <StyledTopicLink to={`/t/${encodeURIComponent(topicLabel.toLowerCase())}`}>#{topicLabel}</StyledTopicLink>
                                                            </>
                                                        ) : null;
                                                    })()}
                                                    {(() => {
                                                        const tagLabel =
                                                            post.tag ||
                                                            mergedRoot?.tag ||
                                                            root?.tag ||
                                                            '';
                                                        return tagLabel ? (
                                                            <>
                                                                <MetaSeparator>·</MetaSeparator>
                                                                <TagBadge $tag={tagLabel}>{tagLabel}</TagBadge>
                                                            </>
                                                        ) : null;
                                                    })()}
                                                    {post.edited && (
                                                        <>
                                                            <MetaSeparator>·</MetaSeparator>
                                                            <TooltipContainer>
                                                                <span style={{ fontStyle: 'italic' }}>edited {formatElapsed(post.edited_ts)} ago</span>
                                                                <TooltipText>{formatTimeStamp(post.edited_ts)}</TooltipText>
                                                            </TooltipContainer>
                                                        </>
                                                    )}
                                                </MetaInfoRowLeft>
                                                {renderPostMenu(post)}
                                            </DesktopMetaInfoRow>

                                            {/* Title for root post */}
                                            {isRoot && (
                                                <>
                                                    <RootTitleRow>
                                                        {post && post.title ? post.title : (mergedRoot && mergedRoot.title ? mergedRoot.title : (root && root.title ? root.title : ''))}
                                                    </RootTitleRow>
                                                    <TitleDivider />
                                                </>
                                            )}

                                            {/* Content */}
                                            {!isCollapsed && post.content && !(state.posts[post.post_id]?.replyOpen && state.posts[post.post_id]?.replyMode === 'edit') && (
                                                <StyledContentArea>
                                                    {(() => {
                                                        const raw = String(post.content || '');
                                                        const mediaArr = Array.isArray(post.media) ? post.media : [];

                                                        // v1.12.0: Render from dedicated media array if available
                                                        if (mediaArr.length > 0) {
                                                            const Inline = require("../components/InlineMedia").default;
                                                            const Gallery = require("../components/MediaGallery").default;
                                                            const mediaNode = (mediaArr.length > 1 && Gallery)
                                                                ? React.createElement(Gallery, { items: mediaArr, variant: isRoot ? 'root_post' : undefined })
                                                                : (Inline
                                                                    ? React.createElement(Inline, { url: mediaArr[0], variant: isRoot ? 'root_post' : undefined })
                                                                    : null);
                                                            return (
                                                                <>
                                                                    {mediaNode}
                                                                    {raw ? <div style={{ height: '0.5rem' }} /> : null}
                                                                    {raw ? <MarkdownRenderer text={raw} /> : null}
                                                                </>
                                                            );
                                                        }

                                                        // LEGACY (v1.11): First-line media URL extraction for posts created before v1.12.0.
                                                        // Remove after March 2026 when all old posts have been migrated or expired.
                                                        const idx = raw.indexOf('\n');
                                                        const first = (idx >= 0 ? raw.slice(0, idx) : raw).trim();
                                                        const restRaw = (idx >= 0 ? raw.slice(idx + 1) : '').replace(/^\n+/, '');
                                                        const isUrl = /^https?:\/\//i.test(first);
                                                        if (isUrl) {
                                                            return (
                                                                <>
                                                                    {require("../components/InlineMedia").default
                                                                        ? React.createElement(require("../components/InlineMedia").default, { url: first, variant: isRoot ? 'root_post' : undefined })
                                                                        : null}
                                                                    {restRaw ? <div style={{ height: '0.5rem' }} /> : null}
                                                                    {restRaw ? <MarkdownRenderer text={restRaw} /> : null}
                                                                </>
                                                            );
                                                        }
                                                        return <MarkdownRenderer text={raw} />;
                                                    })()}
                                                </StyledContentArea>
                                            )}

                                            {/* Action bar with horizontal votes */}
                                            {!isCollapsed && (
                                                <>
                                                    {state.posts[post.post_id]?.replyOpen && state.posts[post.post_id]?.replyMode === 'edit' ? (
                                                        <>
                                                            {displayReplyBox(post)}
                                                            {renderActionBar(post)}
                                                            {displayConfirmation(post)}
                                                        </>
                                                    ) : (
                                                        <>
                                                            {renderActionBar(post)}
                                                            {displayConfirmation(post)}
                                                            {displayReplyBox(post)}
                                                        </>
                                                    )}
                                                </>
                                            )}
                                        </ColumnFlex>
                                    </CardComponent>
                                    {isRoot && !!focusedCommentId && (
                                        <StyledThreadReminder>
                                            You are viewing a single comment's thread.{' '}
                                            {!showContext ? (
                                                <>
                                                    Click{' '}
                                                    <Link to={`/p/${focusedCommentId}?depth=5`}>
                                                        here
                                                    </Link>
                                                    {' '}to view the recent context, or{' '}
                                                    <Link to={`/p/${actualRootPostId}`}>here</Link>
                                                    {' '}to view the full thread.
                                                </>
                                            ) : (
                                                <>
                                                    Click{' '}
                                                    <Link to={`/p/${actualRootPostId}`}>here</Link>
                                                    {' '}to view the full thread.
                                                </>
                                            )}
                                        </StyledThreadReminder>
                                    )}
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

                                        return (
                                            <ContinueThreadLink
                                                to={`/p/${post.post_id}`}
                                                $level={displayLevel}
                                            >
                                                Continue this thread →
                                            </ContinueThreadLink>
                                        );
                                    })()}
                                </div>
                            );
                        })}
                    </ModernPostFeed>
                </MainContentWrapper>
                {renderMobileReplyOverlay()}
            </ContentGrid>
        );
    }
    else {
        return (
            <ContentGrid>
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
                        <PostCard $size={cardSize} style={{ textAlign: 'center', padding: '2rem' }}>
                            <span style={{ color: '#ff6b6b' }}>Unable to load post.</span>
                        </PostCard>
                    </ModernPostFeed>
                </MainContentWrapper>
            </ContentGrid>
        );
    }
}

export default ViewPostView;
