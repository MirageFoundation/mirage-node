import React, { useEffect, useState, useRef, memo, useMemo } from "react";
import ReactDOM from "react-dom";
import styled, { useTheme, css } from "styled-components"
import { Link, useNavigate } from 'react-router-dom';
import { getThemeFamily } from "../../../registry/theme";
import InlineMedia from "./InlineMedia";
import Button from "./Button";
import Storage from '../../../utils/Storage';
import * as tx from "../../../utils/tx.js";
import Api from '../../../utils/api';
import { subscribe, unsubscribe, isSubscribed, isSubscribedAsync } from '../../../utils/Subscriptions';
import { follow, unfollow, isFollowing } from '../../../utils/FollowUsers';
import { requireThemeColor } from "../../../utils/themeColor";
import { buildPhotonUrl, buildWsrvUrl, buildBlurredWsrvUrl, isLikelyImageUrl, isLikelyVideoUrl, redgifsCanonicalWatchUrl } from "../../../utils/media";
import MarkdownRenderer from "./MarkdownRenderer";
import { getAuthorColor, getAuthorTooltip } from "../../../utils/tierColors";
import useBalance from "../../../logic/useBalance";
import { usePendingSends } from "../../../logic/usePendingSends";
import { usePendingSubscribes } from "../../../logic/usePendingSubscribes";
import { formatMirageCompact } from "../../../utils/formatters";
import { normalizeTag } from "../../../utils/ContentTags";
import { getTagPalette } from "../utils/tagPalette";
import { resolveCardSize } from "../utils/cardSize";

import { Tooltip, tooltipStyles } from "./Tooltip";

const StyledMainContainer = styled.div`
    background: ${({ theme }) => requireThemeColor(theme, 'card')};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'cardBorder')};
    border-radius: 6px;
    display: flex;    
    min-height: auto;
    flex-direction: row;
    text-align: left;
    align-items: flex-start;
    padding: 1.5rem;
    margin: 0;
    contain: layout style;
    will-change: transform;
    box-shadow: ${({ theme }) => theme.colors.cardShadow};

    &:hover {
        background: ${({ theme }) => requireThemeColor(theme, 'cardAlt')};
        box-shadow: ${({ theme }) => theme.colors.cardShadowHover};
    }

    position: relative;

    @media (max-width: 1000px) {
        padding: 1rem;
        border-radius: 6px;
    }

    @media (max-width: 600px) {
        padding: 0.6rem;
        border-radius: 4px;
        margin: 0;
    }
`;

const StyledContentArea = styled.div`
    display: flex;
    flex-direction: column;
    padding: 0;
    margin: 0;
    flex: 1 1 auto;
    min-width: 0;
    overflow-wrap: anywhere;
    word-break: break-word;
    text-indent: 0;
	white-space: normal;
`

const ThumbVoteContainer = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    margin-right: 1.5rem;
    margin-top: 0.3rem;

    @media (max-width: 600px) {
        display: none;
    }
`

const StyledThumbBox = styled.div`
    width: 120px;
    min-width: 120px;
    height: 120px;
    border-radius: 6px;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    background: ${({ theme }) => theme.colors.panelAlt};
    border: 1px solid ${({ theme }) => theme.colors.borderSubtle};
`

const ThumbImage = styled.img`
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
    transform-origin: center;
    display: block;
`

const MobileCardWrapper = styled.div`
    display: none;
    @media (max-width: 600px) {
        display: block;
        width: 100%;
        margin: 0.5rem 0 0.5rem 0;
        border-radius: 6px;
        overflow: hidden;
        border: 1px solid ${({ theme }) => requireThemeColor(theme, 'cardBorder')};
        background: ${({ theme }) => requireThemeColor(theme, 'cardAlt')};
        position: relative;
    }
`

// Mobile-only compact meta line: "#topic @username 5d ago"
const MobileMetaLine = styled.div`
    display: none;

    @media (max-width: 600px) {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 0.25rem;
        font-size: 0.7rem;
        font-weight: 600;
        color: ${({ theme }) => theme.colors.subtleText};
        margin: 0 0 0.35rem 0;
    }

    a {
        color: inherit;
        text-decoration: none;
        font-weight: 600;
    }

    a:hover {
        color: ${({ theme }) => theme.colors.text};
    }
`

const VoteInline = styled.div`
    display: inline-flex;
    align-items: center;
`

const ShareText = styled.span`
    @media (max-width: 600px) {
        display: none;
    }
`

// Helper component to render centered text that auto-fits (for text-only cards)
function MobileCardFitText({ titleText }) {
    const containerRef = useRef(null);
    const textRef = useRef(null);

    useEffect(() => {
        const el = textRef.current;
        const container = containerRef.current;
        if (!el || !container) return;
        // Reset font-size to a reasonable starting point - larger for impact
        let base = 20;
        try {
            if (typeof window !== 'undefined') {
                base = Math.max(14, Math.min(28, Math.floor(window.innerWidth * 0.055)));
            }
        } catch (_) { /* ignore */ }
        el.style.fontSize = base + 'px';
        // Shrink until it fits with padding
        let size = base;
        const minSize = 12;
        const padding = 32;
        let guard = 0;
        while (guard < 100 && container && el && (el.scrollHeight > container.clientHeight - padding) && size > minSize) {
            size -= 0.5;
            el.style.fontSize = size + 'px';
            guard += 1;
        }
    }, [titleText]);

    return (
        <MobileCardText ref={containerRef}>
            <QuoteMark>"</QuoteMark>
            <MobileTextContent ref={textRef}>{titleText}</MobileTextContent>
        </MobileCardText>
    );
}

const MobileCardSquare = styled.div`
    position: relative;
    width: 100%;
    /* 2:1 aspect ratio (half the height of the width) */
    padding-bottom: 50%;
    background: ${({ $gradient, theme }) => $gradient || theme.colors.panelAlt};
    overflow: hidden;
`

const MobileCardImg = styled.img`
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center;
    transform-origin: center;
    display: block;
`

const MobileCardText = styled.div`
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: ${({ theme }) => theme.colors.text};
    font-weight: 800;
    text-align: center;
    padding: 1rem 1.5rem;
    box-sizing: border-box;
    overflow: hidden;
`

// Decorative quote mark for text-only cards
const QuoteMark = styled.span`
    position: absolute;
    top: 0.3rem;
    left: 0.6rem;
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 3.5rem;
    font-weight: 400;
    line-height: 1;
    color: ${({ theme }) => theme.colors.muted};
    opacity: 0.3;
    pointer-events: none;
    z-index: 3;
    user-select: none;
`

// The actual text content wrapper
const MobileTextContent = styled.span`
    position: relative;
    z-index: 4;
    font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-weight: 700;
    line-height: 1.25;
    letter-spacing: -0.01em;
    max-height: 100%;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
`


// eslint-disable-next-line no-unused-vars
const MobileCardTitleBar = styled.div`
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 0.5rem 0.65rem;
    color: ${({ theme }) => theme.colors.text};
    font-weight: 700;
    font-size: clamp(0.60rem, 3.2vw, 1.0rem);
    line-height: 1.15;
    pointer-events: none;
    z-index: 2;
`

const MobileCardTitleBelow = styled.div`
    display: none;
    @media (max-width: 600px) {
        display: block;
        padding: 0.5rem 0.65rem;
        font-weight: 700;
        font-size: clamp(0.65rem, 3.2vw, 0.95rem);
        line-height: 1.25;
        color: ${({ theme }) => theme.colors.text};
    }
`

const HideOnMobileTitle = styled.div`
    margin: 0.4rem 0;
    @media (max-width: 600px) {
        display: none;
    }
`

const StyledLink = styled(Link)`
    color: ${({ theme }) => theme.colors.link};
    text-decoration: none;

    &:hover {
      color: ${({ theme }) => theme.colors.linkHover};
    }
    font-weight: bold;
    font-size: 1.0rem;
    overflow-wrap: anywhere;
    word-break: break-word;
    white-space: normal;
    text-indent: 0;
    @media (max-width: 1000px) {
        font-size: 0.8rem; /* slightly smaller titles on mobile */
    }
`

const StyledProfileLink = styled(Link)`
    font-size: inherit;
    color: ${({ $tierColor, theme }) => $tierColor} !important;
    text-decoration: none;
    font-weight: bold;
    ${() => tooltipStyles()}

    &:hover {
        color: ${({ $tierColor, theme }) => $tierColor} !important;
    }
`


// Success box styled like the delete confirmation but in green
const ShareSuccessMessage = styled.div`
    background-color: ${({ theme }) => theme.colors.successBg};
    border: 1px solid ${({ theme }) => theme.colors.successBorder};
    border-radius: 4px;
    padding: 0.75rem 1rem;
    margin: 0.5rem 0.5rem 0.5rem 0;
    color: ${({ theme }) => theme.colors.success};
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

// legacy inline comment/topic link and admin/user buttons removed (unused)

const BlockConfirmMessage = styled.div`
    background-color: ${({ theme }) => theme.colors.warningBg};
    border: 1px solid ${({ theme }) => theme.colors.warningBorder};
    border-radius: 4px;
    padding: 0.4rem 0.75rem;
    margin: 0.6rem 0 0.25rem 0;
    color: ${({ theme }) => theme.colors.warning};
    font-size: 0.85rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 0.4rem;
`;

const ConfirmButtons = styled.div`
    display: flex;
    gap: 0.5rem;
`;






// Simple metadata row - ONE consistent style
const MetaRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0rem;
    padding-top: .5rem;
    border-top: 1px solid ${({ theme }) => theme.colors.border};
    font-size: 0.7rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1;

    & a {
        color: ${({ theme }) => theme.colors.subtleText};
        text-decoration: none;
        font-size: 0.7rem;
        font-weight: 600;
        line-height: 1;
    }

    & a:hover {
        color: ${({ theme }) => theme.colors.text};
    }

    & span {
        font-size: 0.7rem;
        font-weight: 600;
        line-height: 1;
    }

    @media (max-width: 600px) {
        flex-wrap: wrap;
    }
`

// Compact info row above title
const MetaInfoRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.35rem;
    margin-top: 0.0rem;
    padding-bottom: 0.2rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.60rem;
    font-weight: 600;
    line-height: 1.1;

    & a {
        color: ${({ theme }) => theme.colors.subtleText};
        text-decoration: none;
        font-weight: 600;
    }

    & a:hover {
        color: ${({ theme }) => theme.colors.text};
    }

    @media (max-width: 600px) {
        display: none;
    }
`

const MetaInfoRowLeft = styled.div`
    display: flex;
    align-items: center;
    gap: 0.35rem;
`

const MetaSeparator = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    margin: 0 0.0rem;
    font-size: 0.9rem;
    font-weight: 900;
    line-height: 1;
    display: inline-block;
    vertical-align: middle;
`

// Optional debug/reason line explaining why a post appears in the Home feed (mobile only)
const FeedReasonLine = styled.div`
    display: none;

    @media (max-width: 600px) {
        display: block;
        margin-top: 0.15rem;
        margin-bottom: 0.15rem;
        color: ${({ theme }) => theme.colors.subtleText};
        font-size: 0.60rem;
        font-weight: 400;
    }
`;

// Score display - hidden on mobile
const ScoreDisplay = styled.span`
    opacity: 0.75;
    margin-left: 0.4rem;

    @media (max-width: 600px) {
        display: none;
    }
`;

const TagBadge = styled.span`
    display: inline-flex;
    align-items: center;
    padding: 0.1rem 0.4rem;
    border-radius: 4px;
    ${({ theme, $tag }) => {
        const palette = getTagPalette(theme, $tag);
        return css`
            background: ${palette.bg};
            color: ${palette.text};
            border: 1px solid ${palette.border};
        `;
    }}
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: lowercase;
`;

// Wrapper for feed reason with tooltip
const FeedReasonWrapper = styled.span`
    display: inline;
    position: relative;

    @media (max-width: 600px) {
        display: none;
    }
`;

// Inline feed reason shown next to time on desktop only
const FeedReasonInline = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.60rem;
    font-weight: 600;
    font-style: italic;
`;

// Debug tooltip for feed explanation (rendered via portal)
const FeedDebugTooltip = styled.div`
    position: fixed;
    z-index: 10000;
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 6px;
    padding: 0.75rem;
    min-width: 420px;
    max-width: 560px;
    font-style: normal;
    font-weight: 400;
    font-size: 0.7rem;
    line-height: 1.4;
    text-align: left;
    box-shadow: 0 2px 8px rgba(0, 0, 0, ${({ theme }) => theme.name === 'light' ? '0.1' : '0.2'});
    white-space: normal;
    word-break: break-word;
`;

const FeedDebugRow = styled.div`
    display: flex;
    justify-content: space-between;
    margin-bottom: 0.25rem;
    
    &:last-child {
        margin-bottom: 0;
    }
`;

const FeedDebugLabel = styled.span`
    color: ${({ theme }) => theme.colors.text};
`;

const FeedDebugValue = styled.span`
    color: ${({ theme }) => theme.colors.text};
    font-weight: 600;
`;

const FeedDebugExplanation = styled.div`
    margin-top: 0.5rem;
    padding-top: 0.5rem;
    border-top: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.subtleText};
    white-space: normal;
`;

// Larger separator for action bar only
const MetaSeparatorAction = styled(MetaSeparator)`
    font-size: 2.5rem;
    margin: 0 0.35rem 0 0.75rem;
`

const Icon = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    color: ${({ theme }) => theme.colors.subtleText};
    svg {
        width: 18px;
        height: 18px;
        fill: currentColor;
    }
`

const MenuButton = styled.button`
    background: none;
    border: none;
    padding: 0.2rem;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: ${({ theme }) => theme.colors.subtleText};
    border-radius: 4px;
    transition: background 0.2s ease, color 0.2s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.panelAlt};
        color: ${({ theme }) => theme.colors.text};
    }

    svg {
        width: 18px;
        height: 18px;
    }
`

const MenuContainer = styled.div`
    position: relative;
    display: inline-block;
`

const MenuDropdown = styled.div`
    position: fixed;
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 6px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    min-width: 180px;
    z-index: 99999;
    overflow: hidden;
`

const MenuItem = styled.button`
    width: 100%;
    padding: 0.5rem 0.75rem;
    text-align: left;
    background: none;
    border: none;
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.75rem;
    cursor: pointer;
    transition: background 0.2s ease;
    display: flex;
    align-items: center;
    gap: 0.5rem;

    &:hover {
        background: ${({ theme }) => theme.colors.panelAlt};
    }

    &:not(:last-child) {
        border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    }

    &[data-danger="true"] {
        color: ${({ theme }) => theme.colors.danger};
    }
`



const MediaWrapper = styled.div`
    margin-top: 0.35rem;
    max-width: 100%;
`

// Container for full-size media in media mode
const MediaModeContainer = styled.div`
    margin: 0.5rem 0;
    width: 100%;
    overflow: hidden;
    border-radius: 6px;
    
    img, video {
        max-width: 100%;
        max-height: 2000px;
        width: auto;
        height: auto;
        border-radius: 6px;
        display: block;
        ${({ $blur }) => $blur ? 'filter: blur(30px);' : ''}
    }
    
    /* For iframes (YouTube, Redgifs embeds) */
    & > div {
        max-height: 2000px;
        overflow: hidden;
        border-radius: 6px;
        ${({ $blur }) => $blur ? 'filter: blur(30px);' : ''}
    }
`

const StyledFooter = styled.div`
    margin-top: 0rem;
    border-top: 1px solid ${({ theme }) => theme.colors.border};
    padding-top: 0.15rem;
    display: flex;
    justify-content: flex-start;
    font-size: 0.5rem;
`


// Returns absolute local timestamp: YYYY-MM-DD HH:MM:SS
const formatTimeStamp = (utcTimestamp) => {
    if (utcTimestamp === undefined) return "n/a";

    const utcDate = new Date(utcTimestamp * 1000);
    const localDate = new Date(utcDate.getTime() - (utcDate.getTimezoneOffset() * 60000));

    const isoDate = localDate.toISOString().slice(0, 10);
    const isoTime = localDate.toISOString().slice(11, 19);
    return `${isoDate} ${isoTime}`;
};

const markViewPostOpenedFromFeed = () => {
    try {
        if (typeof window === 'undefined' || !window.sessionStorage) return;
        const pathname = String(window.location?.pathname || '');

        // Only stamp feed markers when the user is currently on a feed route.
        // This ensures "Back" from ViewPostView returns to the same feed position without refetching.
        let topic = null;
        if (pathname === '/' || pathname === '/home') {
            topic = 'home';
        } else if (pathname === '/following') {
            topic = 'following';
        } else if (pathname.startsWith('/t/')) {
            const withoutPrefix = pathname.slice(3); // after "/t/"
            const segment = withoutPrefix.split('?')[0].split('#')[0].split('/')[0];
            const trimmed = String(segment || '').trim();
            if (trimmed) {
                try {
                    topic = decodeURIComponent(trimmed);
                } catch (_) {
                    topic = trimmed;
                }
            }
        }

        if (!topic) return;

        // Save scroll position under the same key scheme used by MainView:
        // getFeedKey(topic, 'scroll') -> `feed_scroll_${topic}`.
        try {
            window.sessionStorage.setItem(`feed_scroll_${topic}`, String(window.scrollY || 0));
        } catch (_) { }

        const at = Date.now();
        window.sessionStorage.setItem('mirage_post_nav_source', JSON.stringify({ source: 'feed', topic: topic, at }));
        window.sessionStorage.setItem('mirage_came_from_feed', JSON.stringify({ topic: topic, at }));
    } catch (_) { }
};

function CardView({ state, post, updatePost, showContent = false, footer = null }) {
    const navigate = useNavigate();
    const theme = useTheme();
    const VoteSection = useMemo(() => getThemeFamily(theme.themeId).VoteSection, [theme.themeId]);
    const [nodeConfigTick, setNodeConfigTick] = useState(0);
    const [confirmDelete, setConfirmDelete] = useState(false);
    const [isDeleting, setIsDeleting] = useState(false);
    const [confirmSuspendQuests, setConfirmSuspendQuests] = useState(false);
    const [isSuspending, setIsSuspending] = useState(false);
    const [suspendDuration, setSuspendDuration] = useState(7); // days, or 0 for permanent
    const [suspendSuccess, setSuspendSuccess] = useState(null); // success message or null
    const [confirmUnsuspend, setConfirmUnsuspend] = useState(false);
    const [isUnsuspending, setIsUnsuspending] = useState(false);
    const [userSuspendedStatus, setUserSuspendedStatus] = useState(null); // null = unknown, true/false = known
    const [followOverride, setFollowOverride] = useState(null);
    const [topicFollowOverride, setTopicFollowOverride] = useState(null);
    const [confirmDonate, setConfirmDonate] = useState(false);
    const [donateAmountRaw, setDonateAmountRaw] = useState("10000");
    const [donateMessage, setDonateMessage] = useState(null); // { type, message }
    const [giftSubMessage, setGiftSubMessage] = useState(null);
    const [confirmGiftSub, setConfirmGiftSub] = useState(false);
    const [confirmAward, setConfirmAward] = useState(false);
    const [isAwarding, setIsAwarding] = useState(false);
    const [awardMessage, setAwardMessage] = useState(null); // { type, message }
    const { isPending: isSendPending, formatStatus: formatSendStatus } = usePendingSends();
    const { isPending: isSubscribePending, formatStatus: formatSubscribeStatus } = usePendingSubscribes();
    const [shareCopied, setShareCopied] = useState(false);
    const [confirmBlockPost, setConfirmBlockPost] = useState(false);
    const [confirmBlockUser, setConfirmBlockUser] = useState(false);
    const [confirmBlockTopic, setConfirmBlockTopic] = useState(false);
    const [blockTopicInput, setBlockTopicInput] = useState('');
    const [blockTopicError, setBlockTopicError] = useState('');
    const [blockTopicSuccess, setBlockTopicSuccess] = useState('');
    const [blockingTopic, setBlockingTopic] = useState(false);
    const [blockTopicInputWidth, setBlockTopicInputWidth] = useState(20);
    const blockTopicMeasureRef = useRef(null);
    const [menuOpen, setMenuOpen] = useState(false);
    const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
    const [feedTooltipOpen, setFeedTooltipOpen] = useState(false);
    const [feedTooltipPosition, setFeedTooltipPosition] = useState({ top: 0, left: 0, openDown: false });
    const feedReasonRef = useRef(null);
    const [mediaExpanded, setMediaExpanded] = useState(false);

    useEffect(() => {
        const handler = () => setNodeConfigTick(prev => prev + 1);
        window.addEventListener('nodeConfigUpdated', handler);
        window.addEventListener('chainConfigUpdated', handler);
        return () => {
            window.removeEventListener('nodeConfigUpdated', handler);
            window.removeEventListener('chainConfigUpdated', handler);
        };
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

    const questsEnabled = Boolean(nodeConfig?.quests_enabled);
    const [blurSensitiveMedia, setBlurSensitiveMedia] = useState(() => {
        try {
            const val = Storage.load('blur_sensitive_media', true);
            return val === false ? false : true;
        } catch (_) {
            return true;
        }
    });
    const [cardSize, setCardSize] = useState(() => resolveCardSize(Storage.load('card_size', 'compact')));
    const menuRef = useRef(null);
    const menuButtonRef = useRef(null);
    const isMountedRef = useRef(true);
    useEffect(() => {
        return () => { isMountedRef.current = false; };
    }, []);

    // Determine hide flag first, but do not return before hooks
    const hideTeaser = (!post || post.deleted || post.blocked || typeof post.title !== 'string' || post.title.trim() === '' || typeof post.topic !== 'string' || post.topic.trim() === '');

    // Ownership and admin checks for menu visibility
    const publicKeyStr = String(state?.publicKey || '').trim();
    const hasValidAccount = publicKeyStr && publicKeyStr !== 'guest';
    const isOwnPost = post && hasValidAccount && (post.user_id === state.publicKey);
    const userLevel = (() => {
        try {
            return Number(Storage.load('user_level', '0'));
        } catch (_) {
            return 0;
        }
    })();
    const isAdmin = hasValidAccount && userLevel >= 100;

    useEffect(() => {
        const handleSettingsUpdated = (e) => {
            try {
                if (e && e.detail && typeof e.detail.blurSensitiveMedia !== 'undefined') {
                    setBlurSensitiveMedia(e.detail.blurSensitiveMedia === false ? false : true);
                }
                if (e && e.detail && typeof e.detail.cardSize !== 'undefined') {
                    setCardSize(resolveCardSize(e.detail.cardSize));
                    return;
                }
                const val = Storage.load('blur_sensitive_media', true);
                setBlurSensitiveMedia(val === false ? false : true);
                const size = Storage.load('card_size', 'compact');
                setCardSize(resolveCardSize(size));
            } catch (err) {
                console.debug('[Onyx][CardView] Failed to apply settings update', err);
                throw err;
            }
        };
        window.addEventListener('settingsUpdated', handleSettingsUpdated);
        return () => window.removeEventListener('settingsUpdated', handleSettingsUpdated);
    }, []);

    // Set CSS custom properties for card gap based on compact mode
    // margin-top should equal gap for consistent spacing between info bar and cards
    useEffect(() => {
        const isCompactMode = cardSize === 'compact';
        const root = document.documentElement;
        const gap = isCompactMode ? '0.5rem' : '1.0rem';
        const gapMobile = isCompactMode ? '0.25rem' : '0.5rem';
        root.style.setProperty('--card-gap', gap);
        root.style.setProperty('--card-gap-mobile', gapMobile);
        root.style.setProperty('--card-margin-top', gap);
        root.style.setProperty('--card-margin-top-mobile', gapMobile);
    }, [cardSize]);

    // Ensure flash happens only once per post
    useEffect(() => {
        if (!post || !post.post_id || !post.flash || !updatePost) return;
        const timer = setTimeout(() => {
            try { updatePost(post.post_id, { flash: false }); } catch (_) { }
        }, 1250);
        return () => clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [post && post.post_id]);

    const handleDeletePost = () => {
        setMenuOpen(false);
        if (!post || !post.post_id) return;
        setConfirmSuspendQuests(false);
        setSuspendSuccess(null);
        setConfirmDonate(false);
        setDonateMessage(null);
        setConfirmBlockPost(false);
        setConfirmBlockUser(false);
        setConfirmUnsuspend(false);
        setConfirmDelete(true);
    };

    const confirmDeletePostAction = async () => {
        if (!post || !post.post_id) return;
        if (isMountedRef.current) setConfirmDelete(false);
        if (isMountedRef.current) setIsDeleting(true);
        try {
            const result = await tx.deletePost(post.post_id);
            if (result.success) {
                // Remove the post from view by marking it as deleted
                if (updatePost) {
                    updatePost(post.post_id, { deleted: true });
                }
                if (isMountedRef.current) setIsDeleting(false);
            } else {
                alert(`Failed to delete post: ${result.error || 'Unknown error'}`);
                if (isMountedRef.current) setIsDeleting(false);
            }
        } catch (err) {
            alert(`Error deleting post: ${err.message || 'Unknown error'}`);
            if (isMountedRef.current) setIsDeleting(false);
        }
    };

    const cancelDeletePost = () => {
        setConfirmDelete(false);
        setIsDeleting(false);
    };

    const handleSuspendFromQuests = () => {
        setMenuOpen(false);
        if (!post || !post.user_id) return;
        setConfirmDelete(false);
        setConfirmDonate(false);
        setDonateMessage(null);
        setConfirmBlockPost(false);
        setConfirmBlockUser(false);
        setConfirmUnsuspend(false);
        setConfirmSuspendQuests(true);
    };

    const confirmSuspendFromQuests = async () => {
        console.log('confirmSuspendFromQuests called', { post: post?.user_id, suspendDuration });
        if (!post || !post.user_id) {
            console.log('No post or user_id');
            return;
        }
        const adminAddress = Storage.load('publicKey', '');
        if (!adminAddress) {
            console.log('No admin address');
            return;
        }

        setIsSuspending(true);
        try {
            console.log('Making API call to suspend', { adminAddress, target: post.user_id, duration_days: suspendDuration });
            const response = await Api.post('/admin/rewards/suspend', {
                admin: adminAddress,
                target: post.user_id,
                duration_days: suspendDuration,  // 0 = permanent
                reason: 'Attempting to game the quest system',
            });
            console.log('Suspend response:', response);
            if (response.success) {
                const durationText = suspendDuration > 0 ? `for ${suspendDuration} day${suspendDuration > 1 ? 's' : ''}` : 'permanently';
                setConfirmSuspendQuests(false);
                setUserSuspendedStatus(true); // Update status after successful suspend
                setSuspendSuccess(`User suspended from quests ${durationText}`);
                setTimeout(() => setSuspendSuccess(null), 4000);
            } else {
                alert(`Failed to suspend: ${response.error || response.message || 'Unknown error'}`);
                setConfirmSuspendQuests(false);
            }
        } catch (err) {
            console.error('Suspend error:', err);
            alert(`Error suspending user: ${err.message || 'Unknown error'}`);
            setConfirmSuspendQuests(false);
        }
        setIsSuspending(false);
        setSuspendDuration(7); // Reset to default
    };

    const cancelSuspendFromQuests = () => {
        setConfirmSuspendQuests(false);
        setIsSuspending(false);
    };

    const fetchUserSuspensionStatus = async (userId) => {
        if (!userId || !questsEnabled) {
            setUserSuspendedStatus(null);
            return;
        }
        try {
            const response = await Api.get(`/rewards/summary?owner=${encodeURIComponent(userId)}`);
            setUserSuspendedStatus(response.suspended === true);
        } catch (err) {
            console.error('Error fetching suspension status:', err);
            setUserSuspendedStatus(null);
        }
    };

    const handleUnsuspendFromQuests = () => {
        setMenuOpen(false);
        if (!post || !post.user_id) return;
        setConfirmDelete(false);
        setConfirmSuspendQuests(false);
        setConfirmDonate(false);
        setDonateMessage(null);
        setConfirmBlockPost(false);
        setConfirmBlockUser(false);
        setConfirmUnsuspend(true);
    };

    const confirmUnsuspendFromQuests = async () => {
        if (!post || !post.user_id) return;
        const adminAddress = Storage.load('publicKey', '');
        if (!adminAddress) {
            alert('You must be logged in');
            return;
        }

        setIsUnsuspending(true);
        try {
            const response = await Api.post('/admin/rewards/unsuspend', {
                admin: adminAddress,
                target: post.user_id,
            });
            if (response.success) {
                setConfirmUnsuspend(false);
                setUserSuspendedStatus(false); // Update status after successful unsuspend
                setSuspendSuccess('User unsuspended from quests');
                setTimeout(() => setSuspendSuccess(null), 4000);
            } else {
                alert(`Failed to unsuspend: ${response.error || response.message || 'Unknown error'}`);
                setConfirmUnsuspend(false);
            }
        } catch (err) {
            alert(`Error unsuspending user: ${err.message || 'Unknown error'}`);
            setConfirmUnsuspend(false);
        }
        setIsUnsuspending(false);
    };

    const cancelUnsuspendFromQuests = () => {
        setConfirmUnsuspend(false);
        setIsUnsuspending(false);
    };

    // Close menu when clicking outside
    useEffect(() => {
        if (!menuOpen) return;

        const handleClickOutside = (event) => {
            const clickedInDropdown = menuRef.current && menuRef.current.contains(event.target);
            const clickedInButton = menuButtonRef.current && menuButtonRef.current.contains(event.target);
            if (!clickedInDropdown && !clickedInButton) {
                setMenuOpen(false);
            }
        };

        const handleScroll = () => {
            setMenuOpen(false);
        };

        // Use mousedown to catch clicks before they bubble
        document.addEventListener('mousedown', handleClickOutside);
        window.addEventListener('scroll', handleScroll, true);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            window.removeEventListener('scroll', handleScroll, true);
        };
    }, [menuOpen]);

    const handleEditPost = () => {
        setMenuOpen(false);
        if (!post || !post.post_id) return;
        const targetPostId = post.post_id;
        markViewPostOpenedFromFeed();
        navigate(`/p/${encodeURIComponent(targetPostId)}?edit=true`);
    };

    const handleDonate = () => {
        setMenuOpen(false);
        if (!post || !post.user_id) return;
        if (!hasValidAccount) {
            alert('Please log in to gift MIRAGE');
            return;
        }
        setConfirmDelete(false);
        setConfirmSuspendQuests(false);
        setSuspendSuccess(null);
        setDonateMessage(null);
        setConfirmBlockPost(false);
        setConfirmBlockUser(false);
        setConfirmUnsuspend(false);
        setConfirmGiftSub(false);
        setDonateAmountRaw("10000");
        setConfirmDonate(true);
    };

    const formatDonateAmount = (value) => {
        const digits = String(value || "").replace(/[^\d]/g, "");
        if (!digits) return "";
        return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    };


    const confirmDonateAction = async () => {
        if (!post || !post.user_id) return;
        if (isSendPending(post.user_id)) return;
        const amount = parseInt(String(donateAmountRaw || "").replace(/[^\d]/g, ""), 10);
        if (!Number.isFinite(amount) || amount < 10000) {
            setDonateMessage({ type: 'error', message: 'Minimum gift is 10,000 MIRAGE' });
            setTimeout(() => setDonateMessage(null), 5000);
            return;
        }
        try {
            console.debug('[CardView] donate.submit', { target: post.user_id, amount });
            const result = await tx.sendTokens(post.user_id, amount);
            setConfirmDonate(false);
            if (result.success) {
                setDonateMessage({ type: 'success', message: `Successfully sent ${Number(amount).toLocaleString()} MIRAGE!` });
            } else {
                if (!result?.error) {
                    throw new Error('Missing error for send_tokens');
                }
                setDonateMessage({ type: 'error', message: `Failed: ${result.error}` });
            }
            setTimeout(() => setDonateMessage(null), 5000);
        } catch (error) {
            setConfirmDonate(false);
            setDonateMessage({ type: 'error', message: `Error: ${error.message || error}` });
            setTimeout(() => setDonateMessage(null), 5000);
        }
    };

    const cancelDonate = () => {
        setConfirmDonate(false);
    };

    const handleGiftSubscription = () => {
        setMenuOpen(false);
        if (!post || !post.user_id || isSubscribePending(post.user_id)) return;
        if (!hasValidAccount) {
            alert('Please log in to gift a subscription');
            return;
        }
        const level = (Number(post.author_level) || 0) >= 10 ? 10 : 1;
        const target = post.user_id;
        console.debug('[CardView] gift-subscribe.confirm', { target, level });
        setConfirmDelete(false);
        setConfirmSuspendQuests(false);
        setSuspendSuccess(null);
        setConfirmDonate(false);
        setConfirmBlockPost(false);
        setConfirmBlockUser(false);
        setConfirmUnsuspend(false);
        setConfirmAward(false);
        setGiftSubMessage(null);
        setConfirmGiftSub({ level, target, loading: true, expiryLabel: null, error: null });
        void (async () => {
            let cfg = null;
            try {
                const raw = localStorage.getItem('chainConfig');
                cfg = raw ? JSON.parse(raw) : null;
            } catch (e) {
                console.debug('[CardView] gift-subscribe.config-error', e);
            }
            if (!cfg || !Number(cfg.subscription_period || 0)) {
                try {
                    const fetched = await Api.get('get_chain_config', undefined);
                    if (fetched && typeof fetched === 'object') {
                        try { tx.cacheChainConfig(fetched); } catch (_) { }
                        cfg = fetched;
                    }
                } catch (e) {
                    console.debug('[CardView] gift-subscribe.config-fetch-error', e);
                }
            }
            const periodMinutes = Number(cfg?.subscription_period || 0);
            if (!periodMinutes || periodMinutes <= 0) {
                console.debug('[CardView] gift-subscribe.config-invalid', { periodMinutes });
                setConfirmGiftSub((prev) => (prev && prev.target === target ? { ...prev, loading: false, error: 'Invalid subscription period' } : prev));
                return;
            }
            try {
                const pre = await Api.get('get_user_status', { address: target, _cb: Date.now() });
                const currentExp = Number(pre?.subscription_expiry || 0);
                const nowSec = Math.floor(Date.now() / 1000);
                const isExtension = currentExp > nowSec;
                const base = Math.max(nowSec, currentExp);
                const expectedExp = base + periodMinutes * 60;
                const dateStr = new Date(expectedExp * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
                const label = isExtension ? `Extend until ${dateStr}` : `Until ${dateStr}`;
                console.debug('[CardView] gift-subscribe.expected', { target, level, currentExp, expectedExp });
                setConfirmGiftSub((prev) => (prev && prev.target === target ? { ...prev, loading: false, expiryLabel: label, error: null } : prev));
            } catch (e) {
                console.debug('[CardView] gift-subscribe.status-error', e);
                setConfirmGiftSub((prev) => (prev && prev.target === target ? { ...prev, loading: false, error: 'Failed to load recipient status' } : prev));
            }
        })();
    };

    const confirmGiftSubAction = async () => {
        if (!post || !post.user_id) return;
        if (isSubscribePending(post.user_id)) return;
        if (confirmGiftSub?.loading || confirmGiftSub?.error) return;
        const giftLevel = confirmGiftSub?.level || 1;
        const target = confirmGiftSub?.target || post.user_id;
        const expiryLabel = confirmGiftSub?.expiryLabel || null;
        if (!expiryLabel) {
            setConfirmGiftSub((prev) => (prev ? { ...prev, error: 'Missing expected expiry' } : prev));
            return;
        }
        try {
            console.debug('[CardView] gift-subscribe.submit', { target, level: giftLevel });
            const result = await tx.subscribe(giftLevel, 0, target);
            setConfirmGiftSub(null);
            if (result.success) {
                const isAgent = giftLevel === 10;
                let msg = isAgent ? 'Agent subscription gifted!' : 'Subscription gifted!';
                msg += ` ${expiryLabel}`;
                setGiftSubMessage({ type: 'success', message: msg });
            } else {
                const raw = String(result.error || 'Transaction failed');
                const friendly = raw.replace(/^HTTP \d+:\s*/i, '').replace(/^Failed:\s*/i, '');
                setGiftSubMessage({ type: 'error', message: friendly });
            }
            setTimeout(() => setGiftSubMessage(null), 8000);
        } catch (error) {
            setConfirmGiftSub(null);
            setGiftSubMessage({ type: 'error', message: `${error.message || error}` });
            setTimeout(() => setGiftSubMessage(null), 5000);
        }
    };

    const cancelGiftSub = () => {
        console.debug('[CardView] gift-subscribe.cancel', { target: post?.user_id || null });
        setConfirmGiftSub(null);
    };

    const { displayBalance: userBalanceUmirage } = useBalance();

    const AWARD_TYPES = [
        { name: 'quality_post', label: 'Quality Post Award', short: 'QP' },
        { name: 'original_content', label: 'Original Content Award', short: 'OC' },
        { name: 'based', label: 'Based AF Award', short: 'BA' },
        { name: 'receipts', label: 'Receipts Award', short: 'RC' },
    ];

    const awardConfigs = useMemo(() => {
        void nodeConfigTick;
        try {
            const raw = localStorage.getItem('chainConfig');
            const cfg = raw ? JSON.parse(raw) : null;
            return cfg?.award_configs || [];
        } catch (_) {
            return [];
        }
    }, [nodeConfigTick]);

    const giftSubscriptionLabel = 'Gift Subscription';

    const { subFeeLabel, agentFeeLabel } = useMemo(() => {
        void nodeConfigTick;
        try {
            const raw = localStorage.getItem('chainConfig');
            const cfg = raw ? JSON.parse(raw) : null;
            const tiers = cfg?.tiers || [];
            const sf = Number(tiers[1]?.period_fee || 0);
            const af = Number(tiers[2]?.period_fee || 0);
            return {
                subFeeLabel: sf > 0 ? formatMirageCompact(sf) + ' MIRAGE' : null,
                agentFeeLabel: af > 0 ? formatMirageCompact(af) + ' MIRAGE' : null,
            };
        } catch (_) { }
        return { subFeeLabel: null, agentFeeLabel: null };
    }, [nodeConfigTick]);

    const getAwardCost = (name) => {
        if (awardConfigs.length === 0) return null;
        const cfg = awardConfigs.find(c => c.name === name);
        return cfg ? Number(cfg.cost || 0) : null;
    };

    const handleGiveAward = () => {
        setMenuOpen(false);
        if (!post || !post.post_id) return;
        setConfirmDonate(false);
        setConfirmBlockPost(false);
        setConfirmBlockUser(false);
        setConfirmGiftSub(false);
        setAwardMessage(null);
        setConfirmAward(true);
    };

    const friendlyAwardError = (raw) => {
        const s = String(raw || '').toLowerCase();
        if (s.includes('already awarded')) return 'You already gave this post an award.';
        if (s.includes('insufficient') || s.includes('not enough')) return 'Not enough MIRAGE to give this award.';
        if (s.includes('own post') || s.includes('self-award')) return "You can't award your own post.";
        return raw || 'Something went wrong. Please try again.';
    };

    const confirmAwardAction = async (awardType) => {
        if (!post || !post.post_id || isAwarding) return;
        const costUmirage = getAwardCost(awardType);
        if (costUmirage == null) return;
        setIsAwarding(true);
        setConfirmAward(false);
        const prevAwards = post.awards ? [...post.awards] : [];

        // Optimistic: deduct balance + show award immediately
        if (costUmirage > 0) tx.adjustBalanceOptimistic(-costUmirage);
        if (updatePost) {
            const existing = prevAwards.find(a => a.type === awardType);
            const nextAwards = existing
                ? prevAwards.map(a => a.type === awardType ? { ...a, count: (Number(a.count) || 0) + 1 } : a)
                : [...prevAwards, { type: awardType, count: 1 }];
            updatePost(post.post_id, { awards: nextAwards });
        }

        try {
            const result = await tx.giveAward(post.post_id, awardType);
            if (result.success) {
                const label = AWARD_TYPES.find(a => a.name === awardType)?.label || awardType;
                setAwardMessage({ type: 'success', message: `${label} given!` });
                setTimeout(() => setAwardMessage(null), 5000);
                tx.refreshBalance();
            } else {
                // Revert optimistic award + balance
                if (updatePost) updatePost(post.post_id, { awards: prevAwards });
                if (costUmirage > 0) tx.adjustBalanceOptimistic(costUmirage);
                tx.refreshBalance();
                const errMsg = friendlyAwardError(result.error);
                setAwardMessage({ type: 'error', message: errMsg });
                setTimeout(() => setAwardMessage(null), 5000);
            }
        } catch (error) {
            // Revert optimistic award + balance
            if (updatePost) updatePost(post.post_id, { awards: prevAwards });
            if (costUmirage > 0) tx.adjustBalanceOptimistic(costUmirage);
            tx.refreshBalance();
            const errMsg = friendlyAwardError(error.message || String(error));
            setAwardMessage({ type: 'error', message: errMsg });
            setTimeout(() => setAwardMessage(null), 5000);
        }
        setIsAwarding(false);
    };

    const cancelAward = () => {
        setConfirmAward(false);
    };

    const handleBlockPost = () => {
        setMenuOpen(false);
        if (!post || !post.post_id) return;
        // Close any open confirmation dialogs
        setConfirmDelete(false);
        setConfirmSuspendQuests(false);
        setConfirmDonate(false);
        setConfirmBlockUser(false);
        setConfirmUnsuspend(false);
        setConfirmBlockPost(true);
    };

    const confirmBlockPostAction = async () => {
        if (!post || !post.post_id) return;
        setConfirmBlockPost(false);
        try {
            const result = await tx.blockPost(post.post_id);
            if (result.success) {
                if (updatePost) {
                    updatePost(post.post_id, { blocked: true });
                }
            } else {
                alert(`Failed to block post: ${result.error || 'Unknown error'}`);
            }
        } catch (err) {
            alert(`Error blocking post: ${err.message || 'Unknown error'}`);
        }
    };

    const cancelBlockPost = () => {
        setConfirmBlockPost(false);
    };

    const handleBlockUser = () => {
        setMenuOpen(false);
        if (!post || (!post.user_id && !post.author)) return;
        // Close any open confirmation dialogs
        setConfirmDelete(false);
        setConfirmSuspendQuests(false);
        setConfirmDonate(false);
        setConfirmBlockPost(false);
        setConfirmUnsuspend(false);
        setConfirmBlockUser(true);
    };

    const confirmBlockUserAction = async () => {
        if (!post || (!post.user_id && !post.author)) return;
        const authorAddress = post.user_id || post.author;
        setConfirmBlockUser(false);
        try {
            const result = await tx.blockUser(authorAddress);
            if (result.success) {
                // User blocked on blockchain - hide post immediately
                if (updatePost) {
                    updatePost(post.post_id, { blocked: true });
                }
            } else {
                alert(`Failed to block user: ${result.error || 'Unknown error'}`);
            }
        } catch (err) {
            alert(`Error blocking user: ${err.message || 'Unknown error'}`);
        }
    };

    const cancelBlockUser = () => {
        setConfirmBlockUser(false);
    };

    const handleBlockTopic = () => {
        setMenuOpen(false);
        const topicName = (post?.topic || "").trim().toLowerCase();
        if (!topicName) return;
        // Close any open confirmation dialogs
        setConfirmDelete(false);
        setConfirmSuspendQuests(false);
        setConfirmDonate(false);
        setConfirmBlockPost(false);
        setConfirmBlockUser(false);
        setConfirmUnsuspend(false);
        setBlockTopicInput(topicName);
        setConfirmBlockTopic(true);
    };

    const confirmBlockTopicAction = async () => {
        const topicName = blockTopicInput.trim().toLowerCase();
        if (!topicName) return;
        setBlockTopicError('');
        setBlockingTopic(true);
        try {
            const result = await tx.blockTopic(topicName);
            setBlockingTopic(false);
            setConfirmBlockTopic(false);
            if (result.success) {
                setBlockTopicSuccess(`#${topicName} blocked`);
                setTimeout(() => {
                    setBlockTopicSuccess('');
                    if (updatePost) {
                        const hasWildcard = topicName.includes('*');
                        const allPosts = state?.posts || {};
                        if (hasWildcard) {
                            const re = new RegExp('^' + topicName.split('*').map(s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*') + '$');
                            for (const [pid, p] of Object.entries(allPosts)) {
                                const pt = (p?.topic || "").trim().toLowerCase();
                                if (re.test(pt)) updatePost(pid, { blocked: true });
                            }
                        } else {
                            for (const [pid, p] of Object.entries(allPosts)) {
                                const pt = (p?.topic || "").trim().toLowerCase();
                                if (pt === topicName) updatePost(pid, { blocked: true });
                            }
                        }
                    }
                }, 3000);
            } else {
                setBlockTopicError(result.error || 'Unknown error');
                setTimeout(() => setBlockTopicError(''), 5000);
            }
        } catch (err) {
            setBlockingTopic(false);
            setConfirmBlockTopic(false);
            setBlockTopicError(err.message || 'Unknown error');
            setTimeout(() => setBlockTopicError(''), 5000);
        }
    };

    const cancelBlockTopic = () => {
        if (blockingTopic) return;
        setConfirmBlockTopic(false);
        setBlockTopicInput('');
        setBlockTopicError('');
    };

    const handleFollowUser = async () => {
        setMenuOpen(false);
        if (!post || (!post.user_id && !post.author)) return;
        const authorAddress = post.user_id || post.author;
        const viewerAddress = Storage.load('publicKey', '');
        if (!viewerAddress || viewerAddress === 'guest') {
            alert('Please log in to follow users');
            return;
        }
        try {
            await follow(viewerAddress, authorAddress);
            setFollowOverride(true);
        } catch (err) {
            alert(`Error following user: ${err.message || 'Unknown error'}`);
        }
    };

    const handleUnfollowUser = async () => {
        setMenuOpen(false);
        if (!post || (!post.user_id && !post.author)) return;
        const authorAddress = post.user_id || post.author;
        const viewerAddress = Storage.load('publicKey', '');
        if (!viewerAddress || viewerAddress === 'guest') {
            return;
        }
        try {
            await unfollow(viewerAddress, authorAddress);
            setFollowOverride(false);
        } catch (err) {
            alert(`Error unfollowing user: ${err.message || 'Unknown error'}`);
        }
    };

    const handleFollowTopic = async () => {
        setMenuOpen(false);
        if (!post || !post.topic) return;
        const topic = post.topic;
        const viewerAddress = Storage.load('publicKey', '');
        if (!viewerAddress || viewerAddress === 'guest') {
            alert('Please log in to follow topics');
            return;
        }
        try {
            await subscribe(viewerAddress, topic);
            setTopicFollowOverride(true);
        } catch (err) {
            alert(`Error following topic: ${err.message || 'Unknown error'}`);
        }
    };

    const handleUnfollowTopic = async () => {
        setMenuOpen(false);
        if (!post || !post.topic) return;
        const topic = post.topic;
        const viewerAddress = Storage.load('publicKey', '');
        if (!viewerAddress || viewerAddress === 'guest') {
            return;
        }
        try {
            await unsubscribe(viewerAddress, topic);
            setTopicFollowOverride(false);
        } catch (err) {
            alert(`Error unfollowing topic: ${err.message || 'Unknown error'}`);
        }
    };

    // Check if user follow/block state
    const viewerAddress = Storage.load('publicKey', '');
    const authorAddress = post && (post.user_id || post.author) ? String(post.user_id || post.author).toLowerCase() : '';
    const computedIsFollowing = authorAddress && viewerAddress && viewerAddress !== 'guest'
        ? isFollowing(viewerAddress, authorAddress)
        : false;
    const isFollowingAuthor = followOverride !== null ? followOverride : computedIsFollowing;
    const computedIsSubscribed = post && post.topic && viewerAddress && viewerAddress !== 'guest'
        ? isSubscribed(viewerAddress, post.topic)
        : false;
    const isSubscribedToTopic = topicFollowOverride !== null ? topicFollowOverride : computedIsSubscribed;

    const postTopic = post?.topic;
    useEffect(() => {
        setFollowOverride(null);
        setTopicFollowOverride(null);
    }, [authorAddress, viewerAddress, postTopic]);

    // Async fallback: if sync cache missed, resolve subscription state from API
    useEffect(() => {
        if (topicFollowOverride !== null || computedIsSubscribed || !postTopic || !viewerAddress || viewerAddress === 'guest') return;
        let alive = true;
        isSubscribedAsync(viewerAddress, postTopic).then(result => {
            if (alive && result) setTopicFollowOverride(true);
        }).catch(() => { });
        return () => { alive = false; };
    }, [viewerAddress, postTopic, topicFollowOverride, computedIsSubscribed]);

    // Robust elapsed formatter: treat missing/invalid timestamps as "0s"
    const ts = Number(post && post.timestamp);
    let elapsed = "0s";
    if (Number.isFinite(ts) && ts > 0) {
        let elapsedSeconds = (Date.now() / 1000) - ts;
        if (!isFinite(elapsedSeconds) || isNaN(elapsedSeconds) || elapsedSeconds < 0) elapsedSeconds = 0;
        if (elapsedSeconds <= 60) {
            elapsed = Math.floor(elapsedSeconds) + "s";
        } else if (elapsedSeconds <= 60 * 60) {
            elapsed = Math.floor(elapsedSeconds / 60) + "m";
        } else if (elapsedSeconds <= 60 * 60 * 24) {
            elapsed = Math.floor(elapsedSeconds / 60 / 60) + "h";
        } else if (elapsedSeconds <= 60 * 60 * 24 * 365) {
            elapsed = Math.floor(elapsedSeconds / 60 / 60 / 24) + "d";
        } else {
            elapsed = Math.floor(elapsedSeconds / 60 / 60 / 24 / 365) + "y";
        }
    }

    // LEGACY (v1.11): First-line media URL extraction for posts created before v1.12.0.
    // Remove after March 2026 when all old posts have been migrated or expired.
    const extractFirstUrl = (text) => {
        try {
            if (!text || typeof text !== 'string') return '';
            const m = text.match(/https?:\/\/[^\s<>"']+/);
            return m ? m[0] : '';
        } catch (_) { return ''; }
    };
    const sanitizeUrlForLink = (raw) => {
        try {
            const u = new URL(raw);
            return redgifsCanonicalWatchUrl(u.toString());
        } catch (_) {
            const match = String(raw || '').match(
                /^(https?:\/\/[^\s<>"']*?(?:\.(?:m3u8|mp4|webm|ogv|mov|mkv|gifv|png|jpg|jpeg|gif|webp|bmp|avif))(?:[?#][^\s<>"']*)?)/i
            );
            if (match && match[1]) return redgifsCanonicalWatchUrl(match[1]);
            const generic = String(raw || '').match(/^(https?:\/\/[^\s<>"']+)/i);
            const base = generic && generic[1] ? generic[1] : raw;
            return redgifsCanonicalWatchUrl(base);
        }
    };

    // v1.12.0: Prefer media array if available
    const mediaArr = (post && Array.isArray(post.media) && post.media.length > 0) ? post.media : null;
    const mediaMetaArr = (post && Array.isArray(post.media_meta)) ? post.media_meta : [];
    const firstLinkInContent = (() => {
        // v1.12.0: Use media[0] if available
        if (mediaArr) {
            try { return sanitizeUrlForLink(mediaArr[0]) || ''; } catch (_) { return ''; }
        }
        // LEGACY (v1.11): First-line media URL extraction for posts created before v1.12.0.
        // Remove after March 2026 when all old posts have been migrated or expired.
        try {
            if (!post || !post.content) return '';
            const first = sanitizeUrlForLink(extractFirstUrl(post.content));
            return first || '';
        } catch (_) { return ''; }
    })();


    const isDirectImage = isLikelyImageUrl(firstLinkInContent);
    const isPrimaryVideo = isLikelyVideoUrl(firstLinkInContent);
    const YOUTUBE_THUMB_ZOOM = 1.3;
    const isYoutubeThumb = (() => {
        try {
            const u = String((post && post.thumbnail) || '').trim();
            return u.includes('img.youtube.com') || u.includes('i.ytimg.com');
        } catch (_) { return false; }
    })();

    // Compute the initial thumb state synchronously so the first render already has the
    // correct <img src>. Without this, first render would render a placeholder, the effect
    // below would then swap in the real thumb, and the browser would abort the in-flight
    // placeholder fetch with NS_BINDING_ABORTED.
    const computeInitialThumbState = () => {
        const provided = post && typeof post.thumbnail === 'string' && post.thumbnail.trim() ? post.thumbnail.trim() : '';
        const thumbUrl = provided || (isDirectImage ? firstLinkInContent : null);
        if (!thumbUrl) return { src: null, blurSrc: null, original: null, proxy: 'none' };
        const isYoutubeThumbnail = thumbUrl.includes('img.youtube.com') || thumbUrl.includes('i.ytimg.com');
        if (isYoutubeThumbnail) {
            return { src: thumbUrl, blurSrc: thumbUrl, original: thumbUrl, proxy: 'direct' };
        }
        if (thumbUrl.includes('?')) {
            return {
                src: buildWsrvUrl(thumbUrl, { w: 240, h: 240 }),
                blurSrc: buildBlurredWsrvUrl(thumbUrl, { w: 240, h: 240, blur: 18 }),
                original: thumbUrl,
                proxy: 'wsrv',
            };
        }
        return {
            src: buildPhotonUrl(thumbUrl, { w: 240, h: 240 }),
            blurSrc: buildPhotonUrl(thumbUrl, { w: 240, h: 240 }),
            original: thumbUrl,
            proxy: 'photon',
        };
    };
    const [thumbSrc, setThumbSrc] = useState(() => computeInitialThumbState().src);
    const [thumbBlurSrc, setThumbBlurSrc] = useState(() => computeInitialThumbState().blurSrc);
    const [thumbOriginal, setThumbOriginal] = useState(() => computeInitialThumbState().original);
    const [thumbProxy, setThumbProxy] = useState(() => computeInitialThumbState().proxy);

    useEffect(() => {
        // Use thumbnail from database (indexed by backend), or fall back to direct image URL
        const provided = post && typeof post.thumbnail === 'string' && post.thumbnail.trim() ? post.thumbnail.trim() : '';
        const thumbUrl = provided || (isDirectImage ? firstLinkInContent : null);

        setThumbOriginal(thumbUrl);

        if (thumbUrl) {
            const isYoutubeThumbnail = thumbUrl.includes('img.youtube.com') || thumbUrl.includes('i.ytimg.com');
            const hasQuery = thumbUrl.includes('?');
            if (isYoutubeThumbnail) {
                setThumbProxy('direct');
                setThumbSrc(thumbUrl);
                setThumbBlurSrc(thumbUrl);
            } else if (hasQuery) {
                setThumbProxy('wsrv');
                setThumbSrc(buildWsrvUrl(thumbUrl, { w: 240, h: 240 }));
                setThumbBlurSrc(buildBlurredWsrvUrl(thumbUrl, { w: 240, h: 240, blur: 18 }));
                console.debug('[CardView] thumbnail proxy wsrv for query URL', { thumbUrl });
            } else {
                // NOTE: Photon was chosen over wsrv in the past (reason lost), but it behaved better.
                // If thumbnail issues return, this proxy choice is the likely cause.
                setThumbProxy('photon');
                setThumbSrc(buildPhotonUrl(thumbUrl, { w: 240, h: 240 }));
                setThumbBlurSrc(buildPhotonUrl(thumbUrl, { w: 240, h: 240 }));
            }
        } else {
            setThumbProxy('none');
            setThumbSrc(null);
            setThumbBlurSrc(null);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [post && post.thumbnail, post && post.content, isDirectImage, firstLinkInContent]);

    var title = "";
    const targetPostId = (() => {
        const h = post && post.tx_hash;
        if (h) return String(h).toLowerCase();
        const p = post && post.post_id;
        if (p === 'pending') return 'pending';
        return p ? String(p).toLowerCase() : 'still_resolving';
    })();

    // All card title clicks go to the post view page - external links are available there
    if (post) {
        title = (<StyledLink to={`/p/${targetPostId}`}>{post.title}</StyledLink>);
    }

    // All thumbnail clicks go to the post view page - external links are available there
    const thumbTo = `/p/${targetPostId}`;
    const thumbTarget = undefined;
    const thumbRel = undefined;

    const hasMedia = !!(thumbSrc || thumbBlurSrc || isDirectImage || isPrimaryVideo);
    const shouldBlurMedia = !!(blurSensitiveMedia && post && post.tag && String(post.tag).trim() && hasMedia);
    const displayThumbSrc = shouldBlurMedia && !mediaExpanded && thumbBlurSrc ? thumbBlurSrc : thumbSrc;

    const shortenAddress = (address) => {
        if (!address) return "";
        return `${address.substring(0, 10)}...${address.substring(address.length - 4)}`;
    };

    const pickInlineMediaUrl = (url) => {
        return url;
    };

    const renderAuthorMeta = () => {
        if (!post || (!post.username && !post.user_id)) return null;
        const username = (post && typeof post.username === 'string') ? post.username.trim() : '';
        const display = username ? `@${username}` : `@${shortenAddress(post.user_id)}`;
        const ownerAddress = (post && post.user_id) ? String(post.user_id).trim() : '';
        // New clean URL: prefer username, fallback to address
        const href = username ? `/u/${encodeURIComponent(username)}` : `/u/${encodeURIComponent(ownerAddress)}`;
        const tierColor = getAuthorColor(post.author_level, post.author_is_new);
        const tierName = getAuthorTooltip(post.author_level, post.author_is_new);
        const content = ownerAddress ? (
            <StyledProfileLink
                to={href}
                $tierColor={tierColor}
                data-tooltip={tierName || undefined}
            >
                {display}
            </StyledProfileLink>
        ) : display;
        return content;
    };


    const InlineTeaserMedia = ({ url, mediaMeta }) => {
        return (
            <MediaWrapper>
                <InlineMedia url={pickInlineMediaUrl(url)} mediaMeta={mediaMeta || null} />
            </MediaWrapper>
        );
    };

    const expandedTextBody = useMemo(() => {
        const raw = String(post?.content || '').trim();
        if (!raw) return null;
        if (mediaArr) return raw || null;
        const idx = raw.indexOf('\n');
        const first = (idx >= 0 ? raw.slice(0, idx) : raw).trim();
        const rest = (idx >= 0 ? raw.slice(idx + 1) : '').replace(/^\n+/, '');
        if (/^https?:\/\//i.test(first)) return rest || null;
        return raw || null;
    }, [post?.content, mediaArr]);

    if (hideTeaser) return null;

    // Check if mobile (disable compact mode on mobile)
    const isMobile = (() => {
        try {
            if (typeof window !== 'undefined' && window.matchMedia) {
                return window.matchMedia('(max-width: 600px)').matches;
            }
            if (typeof window !== 'undefined') {
                return window.innerWidth <= 600;
            }
        } catch (_) { }
        return false;
    })();

    // Compact mode: smaller thumb + tighter spacing on desktop (>600px)
    // Disabled on mobile
    const isCompact = !isMobile && cardSize === 'compact';
    // Media mode: hide thumbnails, show full media below title
    const isMediaMode = cardSize === 'media';
    // Check if post has actual media content to display in media mode
    const hasMediaModeContent = isMediaMode && firstLinkInContent && (isDirectImage || isPrimaryVideo);



    const renderCommentCount = () => {
        const currentCount = Number.isFinite(Number(post.comments)) ? Math.round(Number(post.comments)) : 0;
        return `${currentCount} comments`;
    };

    const handleShare = async () => {
        try {
            // New clean URL format: /p/:postId
            const path = `/p/${encodeURIComponent(targetPostId)}`;
            const origin = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : '';
            const url = origin + path;
            const title = (post && post.title) ? String(post.title) : 'Mirage';
            const tagline = 'True Discourse. Decentralized. Unstoppable.';
            const text = `${title}\n\n${tagline}\n\n${url}`;

            // Get thumbnail URL if available
            const thumbnailUrl = (() => {
                const provided = post && typeof post.thumbnail === 'string' && post.thumbnail.trim() ? post.thumbnail.trim() : '';
                if (provided) return provided;
                if (isDirectImage && firstLinkInContent) return firstLinkInContent;
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
                } catch (_) { /* fall back */ }
            }

            // Desktop: always copy to clipboard
            if (navigator && navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(url);
                setShareCopied(true);
                setTimeout(() => { if (isMountedRef.current) setShareCopied(false); }, 3000);
                return;
            }
            if (typeof window !== 'undefined') window.open(url, '_blank', 'noopener,noreferrer');
        } catch (_) { /* noop */ }
    };

    // Compact mode inline style overrides (desktop only)
    // Affects container padding, thumbnail size, internal spacing, and gaps
    const compactContainerStyle = isCompact
        ? { padding: '0.5rem 0.6rem 0.5rem 0.6rem' }
        : undefined;
    const compactThumbVoteStyle = isCompact
        ? { marginRight: '0.5rem', gap: '0.15rem' }
        : undefined;
    const compactThumbBoxStyle = isCompact
        ? { width: '90px', minWidth: '90px', height: '90px', borderRadius: '6px' }
        : undefined;
    const compactMetaInfoRowStyle = isCompact
        ? { paddingBottom: '0.05rem', marginBottom: '0.05rem' }
        : undefined;
    const compactTitleStyle = isCompact
        ? { margin: '0.2rem 0' }
        : undefined;
    const compactMetaRowStyle = isCompact
        ? { paddingTop: '0.25rem', gap: '0.25rem', marginTop: '0' }
        : undefined;

    return (
        <div>
            <StyledMainContainer isFlash={!!(post && post.flash)} style={compactContainerStyle}>
                {!hasMediaModeContent && <ThumbVoteContainer style={compactThumbVoteStyle}>
                    <StyledThumbBox style={compactThumbBoxStyle}>
                        {(() => {
                            const pickPlaceholder = () => {
                                try {
                                    const base = String((post && (post.post_id || post.tx_hash)) || '') || String((post && post.title) || '') || String((post && post.timestamp) || '');
                                    let h = 0;
                                    for (let i = 0; i < base.length; i++) {
                                        h = ((h << 5) - h) + base.charCodeAt(i);
                                        h |= 0;
                                    }
                                    const n = (Math.abs(h) % 20) + 1;
                                    return `/images/text-posts/text_post_${String(n).padStart(2, '0')}.png`;
                                } catch (_) {
                                    const n = (Math.floor(Math.random() * 20) % 20) + 1;
                                    return `/images/text-posts/text_post_${String(n).padStart(2, '0')}.png`;
                                }
                            };
                            const placeholderSrc = pickPlaceholder();
                            const imgEl = (
                                <ThumbImage
                                    src={displayThumbSrc ? displayThumbSrc : placeholderSrc}
                                    alt=""
                                    loading="lazy"
                                    style={(() => {
                                        const s = {};
                                        if (shouldBlurMedia && !mediaExpanded && displayThumbSrc) s.filter = 'blur(15px)';
                                        if (isYoutubeThumb) s.transform = `scale(${YOUTUBE_THUMB_ZOOM})`;
                                        return Object.keys(s).length ? s : undefined;
                                    })()}
                                    onError={() => {
                                        // Photon failed? Try wsrv as fallback
                                        if (thumbProxy === 'photon' && thumbOriginal) {
                                            setThumbProxy('wsrv');
                                            setThumbSrc(buildWsrvUrl(thumbOriginal, { w: 240, h: 240 }));
                                            setThumbBlurSrc(buildBlurredWsrvUrl(thumbOriginal, { w: 240, h: 240, blur: 18 }));
                                            return;
                                        }
                                        // Both failed, show placeholder
                                        setThumbProxy('none');
                                        setThumbSrc(placeholderSrc);
                                        setThumbBlurSrc(null);
                                    }}
                                />
                            );
                            return (
                                <Link to={thumbTo} target={thumbTarget} rel={thumbRel} style={{ display: 'block', width: '100%', height: '100%' }}>
                                    {imgEl}
                                </Link>
                            );
                        })()}
                    </StyledThumbBox>
                </ThumbVoteContainer>}
                <StyledContentArea>
                    <MobileMetaLine>
                        <Link to={post?.topic ? `/t/${post.topic}` : '#'}>{post?.topic ? `#${post.topic}` : '/unknown'}</Link>
                        {renderAuthorMeta() || <span>@Anonymous</span>}
                        <Tooltip $dotted data-tooltip={formatTimeStamp(post.timestamp)}>{elapsed} ago</Tooltip>
                        {post && post.tag ? <TagBadge $tag={normalizeTag(post.tag)}>{normalizeTag(post.tag)}</TagBadge> : null}
                        {post?.awards?.length > 0 && (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.1rem', fontSize: '0.6rem' }}>
                                {post.awards.map(a => {
                                    const def = AWARD_TYPES.find(t => t.name === a.type);
                                    if (!def) return null;
                                    const cnt = Number(a.count || 0);
                                    const countLabel = cnt > 1 ? `${cnt}x ` : '';
                                    return <Tooltip key={a.type} data-tooltip={def.label}>{countLabel}{def.short}</Tooltip>;
                                })}
                            </span>
                        )}
                    </MobileMetaLine>
                    {!hasMediaModeContent && <MobileCardWrapper>
                        <MobileCardSquare $gradient={undefined}>
                            {(() => {
                                // Use the already-computed proxied thumbnail (Photon primary, wsrv fallback)
                                const displayMobileSrc = shouldBlurMedia && !mediaExpanded && thumbBlurSrc ? thumbBlurSrc : thumbSrc;
                                if (displayMobileSrc) {
                                    return (
                                        <Link to={thumbTo} target={thumbTarget} rel={thumbRel} style={{ display: 'block', position: 'absolute', inset: 0 }}>
                                            <MobileCardImg
                                                src={displayMobileSrc}
                                                alt=""
                                                loading="lazy"
                                                style={(() => {
                                                    const s = {};
                                                    if (shouldBlurMedia && !mediaExpanded) s.filter = 'blur(15px)';
                                                    if (isYoutubeThumb) s.transform = `scale(${YOUTUBE_THUMB_ZOOM})`;
                                                    return Object.keys(s).length ? s : undefined;
                                                })()}
                                            />
                                        </Link>
                                    );
                                } else {
                                    return (
                                        <Link to={thumbTo} target={thumbTarget} rel={thumbRel} style={{ display: 'block', position: 'absolute', inset: 0 }}>
                                            <MobileCardFitText titleText={post && post.title ? post.title : ''} />
                                        </Link>
                                    );
                                }
                            })()}
                        </MobileCardSquare>
                        {thumbSrc && post && post.title ? (
                            <MobileCardTitleBelow>
                                <Link to={thumbTo} target={thumbTarget} rel={thumbRel} style={{ color: 'inherit', textDecoration: 'none' }}>
                                    {post.title}
                                </Link>
                            </MobileCardTitleBelow>
                        ) : null}
                    </MobileCardWrapper>}
                    <MetaInfoRow style={compactMetaInfoRowStyle}>
                        <MetaInfoRowLeft>
                            <Link to={post?.topic ? `/t/${post.topic}` : '#'}>{post?.topic ? `#${post.topic}` : '/unknown'}</Link>
                            <MetaSeparator>·</MetaSeparator>
                            {renderAuthorMeta() || <span>@Anonymous</span>}
                            <MetaSeparator>·</MetaSeparator>
                            <Tooltip $dotted data-tooltip={formatTimeStamp(post.timestamp)}>
                                {elapsed} ago
                            </Tooltip>
                            {post && post.tag ? (
                                <>
                                    <MetaSeparator>·</MetaSeparator>
                                    <TagBadge $tag={normalizeTag(post.tag)}>{normalizeTag(post.tag)}</TagBadge>
                                </>
                            ) : null}
                            {post?.awards?.length > 0 && (
                                <>
                                    <MetaSeparator>·</MetaSeparator>
                                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.1rem', fontSize: '0.6rem' }}>
                                        {post.awards.map(a => {
                                            const def = AWARD_TYPES.find(t => t.name === a.type);
                                            if (!def) return null;
                                            const cnt = Number(a.count || 0);
                                            const countLabel = cnt > 1 ? `${cnt}x ` : '';
                                            return <Tooltip key={a.type} data-tooltip={def.label}>{countLabel}{def.short}</Tooltip>;
                                        })}
                                    </span>
                                </>
                            )}
                            {post && post.feed_bucket && post.feed_bucket !== 'guest' && (
                                <>
                                    <MetaSeparator>·</MetaSeparator>
                                    <FeedReasonWrapper
                                        ref={feedReasonRef}
                                        onMouseEnter={() => {
                                            if (post.feed_debug && feedReasonRef.current) {
                                                const rect = feedReasonRef.current.getBoundingClientRect();
                                                const tooltipHeight = 320;
                                                const openDown = rect.top - tooltipHeight - 8 < 0;
                                                setFeedTooltipPosition({
                                                    top: openDown ? rect.bottom + 8 : rect.top - 8,
                                                    left: Math.max(10, rect.left),
                                                    openDown,
                                                });
                                                setFeedTooltipOpen(true);
                                            }
                                        }}
                                        onMouseLeave={() => setFeedTooltipOpen(false)}
                                    >
                                        <FeedReasonInline>
                                            {post.feed_bucket === 'following' && 'following'}
                                            {post.feed_bucket === 'similar' && 'similar'}
                                            {post.feed_bucket === 'liked' && 'liked'}
                                            {post.feed_bucket === 'discovery' && 'discovery'}
                                            {post.feed_bucket === 'popular' && 'popular'}
                                            {post.feed_bucket === 'discussion' && 'discussed'}
                                            {post.feed_bucket === 'second_chance' && 'second chance'}
                                            {post.feed_bucket === 'fresh' && 'discover'}
                                            {post.feed_bucket === 'newest' && 'newest'}
                                        </FeedReasonInline>
                                    </FeedReasonWrapper>
                                    {feedTooltipOpen && post.feed_debug && ReactDOM.createPortal(
                                        <FeedDebugTooltip
                                            style={{ top: feedTooltipPosition.top, left: feedTooltipPosition.left, transform: feedTooltipPosition.openDown ? 'none' : 'translateY(-100%)' }}
                                            onMouseEnter={() => setFeedTooltipOpen(true)}
                                            onMouseLeave={() => setFeedTooltipOpen(false)}
                                        >
                                            {/* Show formula and score for Magic */}
                                            {post.feed_debug.score !== undefined && (
                                                <>
                                                    <FeedDebugRow style={{ marginBottom: '0.3rem' }}>
                                                        <FeedDebugValue style={{ fontFamily: 'monospace', fontSize: '0.8em', opacity: 0.7 }}>
                                                            {post.feed_debug.equation ||
                                                                (post.feed_debug.P !== undefined
                                                                    ? '(√S + √V + √U + √P + √A) × R'
                                                                    : post.feed_debug.C !== undefined
                                                                        ? '(V + C) × R'
                                                                        : '(S + V + U) × R')}
                                                        </FeedDebugValue>
                                                    </FeedDebugRow>
                                                    <FeedDebugRow style={{ marginBottom: '0.5rem', paddingBottom: '0.5rem', borderBottom: `1px solid ${theme.colors.border}` }}>
                                                        <FeedDebugLabel style={{ fontWeight: 'bold' }}>Score:</FeedDebugLabel>
                                                        <FeedDebugValue style={{ fontSize: '1.1em' }}>{post.feed_debug.score?.toFixed(4) || '0'}</FeedDebugValue>
                                                    </FeedDebugRow>
                                                </>
                                            )}
                                            {/* Detailed numeric formula (if provided) */}
                                            {post.feed_debug.formula && (
                                                <FeedDebugRow>
                                                    <FeedDebugLabel>Formula:</FeedDebugLabel>
                                                    <FeedDebugValue style={{ fontFamily: 'monospace', fontSize: '0.85em' }}>
                                                        {post.feed_debug.formula}
                                                    </FeedDebugValue>
                                                </FeedDebugRow>
                                            )}
                                            <FeedDebugRow>
                                                <FeedDebugLabel>S (similar users):</FeedDebugLabel>
                                                <FeedDebugValue>{post.feed_debug.S?.toFixed(3) || '0.000'}</FeedDebugValue>
                                            </FeedDebugRow>
                                            <FeedDebugRow>
                                                <FeedDebugLabel>V (votes):</FeedDebugLabel>
                                                <FeedDebugValue>{post.feed_debug.V?.toFixed(3) || '0.000'}</FeedDebugValue>
                                            </FeedDebugRow>
                                            {/* U for unique commenters */}
                                            {post.feed_debug.U !== undefined && (
                                                <FeedDebugRow>
                                                    <FeedDebugLabel>U (unique commenters):</FeedDebugLabel>
                                                    <FeedDebugValue>{post.feed_debug.U ?? 0}</FeedDebugValue>
                                                </FeedDebugRow>
                                            )}
                                            {/* P for preference boost */}
                                            {post.feed_debug.P !== undefined && (
                                                <FeedDebugRow>
                                                    <FeedDebugLabel>P (your prefs):</FeedDebugLabel>
                                                    <FeedDebugValue>{post.feed_debug.P?.toFixed(3) || '0.000'} [t={post.feed_debug.t_pref ?? 0}+a={post.feed_debug.a_pref ?? 0}]</FeedDebugValue>
                                                </FeedDebugRow>
                                            )}
                                            {/* A for awards */}
                                            {post.feed_debug.A !== undefined && (
                                                <FeedDebugRow>
                                                    <FeedDebugLabel>A (awards):</FeedDebugLabel>
                                                    <FeedDebugValue>{post.feed_debug.A ?? 0}</FeedDebugValue>
                                                </FeedDebugRow>
                                            )}
                                            {/* old magic: C for comments */}
                                            {post.feed_debug.C !== undefined && (
                                                <FeedDebugRow>
                                                    <FeedDebugLabel>C (comments):</FeedDebugLabel>
                                                    <FeedDebugValue>{post.feed_debug.C?.toFixed(3) || '0.000'} [{post.feed_debug.comments || 0}]</FeedDebugValue>
                                                </FeedDebugRow>
                                            )}
                                            <FeedDebugRow>
                                                <FeedDebugLabel>R (recency):</FeedDebugLabel>
                                                <FeedDebugValue>
                                                    {post.feed_debug.R?.toFixed(4) || '0.0000'}
                                                    {post.feed_debug.age_hours !== undefined && ` [${post.feed_debug.age_hours}h ago]`}
                                                </FeedDebugValue>
                                            </FeedDebugRow>
                                            {post.feed_debug.N !== undefined && (
                                                <FeedDebugRow>
                                                    <FeedDebugLabel>N (novelty):</FeedDebugLabel>
                                                    <FeedDebugValue>
                                                        {post.feed_debug.N?.toFixed(4) || '1.0000'}
                                                        {post.feed_debug.seen_count > 0 && ` [seen ${post.feed_debug.seen_count}×]`}
                                                    </FeedDebugValue>
                                                </FeedDebugRow>
                                            )}
                                            {/* Only show Prefs row for older debug formats (Magic shows it inline with P) */}
                                            {post.feed_debug.P === undefined && (
                                                <FeedDebugRow>
                                                    <FeedDebugLabel>Prefs:</FeedDebugLabel>
                                                    <FeedDebugValue>
                                                        t={post.feed_debug.t_pref ?? 0} + a={post.feed_debug.a_pref ?? 0}
                                                    </FeedDebugValue>
                                                </FeedDebugRow>
                                            )}
                                            <FeedDebugExplanation>
                                                {post.feed_debug.reason}
                                            </FeedDebugExplanation>
                                        </FeedDebugTooltip>,
                                        document.body
                                    )}
                                </>
                            )}
                            {post.agent_edited && (
                                <>
                                    <MetaSeparator>·</MetaSeparator>
                                    <span style={{ opacity: 0.5, fontStyle: 'italic' }}>
                                        agent modified
                                    </span>
                                </>
                            )}
                        </MetaInfoRowLeft>
                        <MenuContainer ref={menuRef}>
                            <MenuButton
                                ref={menuButtonRef}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    if (!menuOpen && menuButtonRef.current) {
                                        const rect = menuButtonRef.current.getBoundingClientRect();
                                        setMenuPosition({
                                            top: rect.bottom + 4,
                                            left: rect.right - 180 // 180 is min-width of dropdown
                                        });
                                        // Fetch suspension status for admins
                                        if (isAdmin && post?.user_id && questsEnabled) {
                                            setUserSuspendedStatus(null); // Reset while loading
                                            fetchUserSuspensionStatus(post.user_id);
                                        }
                                    }
                                    setMenuOpen(!menuOpen);
                                }}
                                aria-label="Post menu"
                            >
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <circle cx="12" cy="12" r="1.5"></circle>
                                    <circle cx="12" cy="5" r="1.5"></circle>
                                    <circle cx="12" cy="19" r="1.5"></circle>
                                </svg>
                            </MenuButton>
                            {menuOpen && ReactDOM.createPortal(
                                <MenuDropdown
                                    ref={menuRef}
                                    style={{ top: menuPosition.top, left: Math.max(10, menuPosition.left) }}
                                    onClick={(e) => e.stopPropagation()}
                                >
                                    {isOwnPost && (
                                        <>
                                            <MenuItem onClick={(e) => { e.stopPropagation(); handleEditPost(); }}>Edit post</MenuItem>
                                            <MenuItem onClick={(e) => { e.stopPropagation(); handleDeletePost(); }} data-danger="true">Delete post</MenuItem>
                                        </>
                                    )}
                                    {!isOwnPost && (
                                        <>
                                            <MenuItem onClick={(e) => { e.stopPropagation(); isFollowingAuthor ? handleUnfollowUser() : handleFollowUser(); }}>
                                                {isFollowingAuthor ? 'Unfollow user' : 'Follow user'}
                                            </MenuItem>
                                        </>
                                    )}
                                    <MenuItem onClick={(e) => { e.stopPropagation(); isSubscribedToTopic ? handleUnfollowTopic() : handleFollowTopic(); }}>
                                        {isSubscribedToTopic ? 'Unfollow topic' : 'Follow topic'}
                                    </MenuItem>
                                    {!isOwnPost && (
                                        <>
                                            <MenuItem onClick={(e) => { e.stopPropagation(); handleGiveAward(); }}>Give Award</MenuItem>
                                            {hasValidAccount && (
                                                <MenuItem onClick={(e) => { e.stopPropagation(); handleDonate(); }}>Gift Mirage</MenuItem>
                                            )}
                                            {hasValidAccount && (
                                                <MenuItem onClick={(e) => { e.stopPropagation(); handleGiftSubscription(); }} disabled={isSubscribePending(post?.user_id)}>
                                                    {formatSubscribeStatus(post?.user_id) || giftSubscriptionLabel}
                                                </MenuItem>
                                            )}
                                            <MenuItem onClick={(e) => { e.stopPropagation(); handleBlockUser(); }} data-danger="true">Block user</MenuItem>
                                            <MenuItem onClick={(e) => { e.stopPropagation(); handleBlockPost(); }} data-danger="true">Block post</MenuItem>
                                            {post?.topic && <MenuItem onClick={(e) => { e.stopPropagation(); handleBlockTopic(); }} data-danger="true">Block topic</MenuItem>}
                                        </>
                                    )}
                                    {!isOwnPost && isAdmin && (
                                        <>
                                            <MenuItem onClick={(e) => { e.stopPropagation(); handleDeletePost(); }} data-danger="true">Mark post deleted</MenuItem>
                                            {questsEnabled && userSuspendedStatus !== true && (
                                                <MenuItem onClick={(e) => { e.stopPropagation(); handleSuspendFromQuests(); }} data-danger="true">Suspend from quests</MenuItem>
                                            )}
                                            {questsEnabled && userSuspendedStatus === true && (
                                                <MenuItem onClick={(e) => { e.stopPropagation(); handleUnsuspendFromQuests(); }}>Unsuspend from quests</MenuItem>
                                            )}
                                        </>
                                    )}
                                </MenuDropdown>,
                                document.body
                            )}
                        </MenuContainer>
                    </MetaInfoRow>
                    {post && post.feed_bucket && post.feed_bucket !== 'guest' && !hasMediaModeContent && (
                        <FeedReasonLine>
                            {post.feed_bucket === 'following' && (post.feed_debug?.reason || 'Following')}
                            {post.feed_bucket === 'similar' && (post.feed_debug?.reason || 'Similar taste match')}
                            {post.feed_bucket === 'liked' && (post.feed_debug?.reason || 'Liked topic/author')}
                            {post.feed_bucket === 'discovery' && (post.feed_debug?.reason || 'Discovery')}
                            {post.feed_bucket === 'popular' && (post.feed_debug?.reason || 'Popular post')}
                            {post.feed_bucket === 'discussion' && (post.feed_debug?.reason || 'Active discussion')}
                            {post.feed_bucket === 'second_chance' && (post.feed_debug?.reason || 'Second chance')}
                            {post.feed_bucket === 'fresh' && (post.feed_debug?.reason || 'Fresh pick')}
                            {post.feed_bucket === 'newest' && (post.feed_debug?.reason || 'Newest')}
                            {post.feed_debug && typeof post.feed_debug.score === 'number' && (
                                <ScoreDisplay>
                                    score {post.feed_debug.score}
                                </ScoreDisplay>
                            )}
                        </FeedReasonLine>
                    )}
                    {hasMediaModeContent ? (
                        <div style={{ ...(compactTitleStyle || {}), display: 'flex', alignItems: 'baseline' }}>
                            {title}
                            <span
                                onClick={(e) => { e.stopPropagation(); setMediaExpanded(prev => !prev); }}
                                style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginLeft: 'auto', padding: '0.2rem', opacity: 0.4, transition: 'opacity 0.15s, transform 0.2s', userSelect: 'none', transform: mediaExpanded ? 'rotate(180deg)' : 'none' }}
                                onMouseEnter={e => { e.currentTarget.style.opacity = '1'; }}
                                onMouseLeave={e => { e.currentTarget.style.opacity = '0.4'; }}
                            >
                                <svg viewBox="0 0 24 24" style={{ width: '18px', height: '18px', fill: 'none', stroke: 'currentColor', strokeWidth: 2.5, strokeLinecap: 'round', strokeLinejoin: 'round' }}>
                                    <polyline points="6 9 12 15 18 9" />
                                </svg>
                            </span>
                        </div>
                    ) : (
                        <HideOnMobileTitle style={{ ...(compactTitleStyle || {}), display: 'flex', alignItems: 'baseline' }}>
                            {title}
                            <span
                                onClick={(e) => { e.stopPropagation(); setMediaExpanded(prev => !prev); }}
                                style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginLeft: 'auto', padding: '0.2rem', opacity: 0.4, transition: 'opacity 0.15s, transform 0.2s', userSelect: 'none', transform: mediaExpanded ? 'rotate(180deg)' : 'none' }}
                                onMouseEnter={e => { e.currentTarget.style.opacity = '1'; }}
                                onMouseLeave={e => { e.currentTarget.style.opacity = '0.4'; }}
                            >
                                <svg viewBox="0 0 24 24" style={{ width: '18px', height: '18px', fill: 'none', stroke: 'currentColor', strokeWidth: 2.5, strokeLinecap: 'round', strokeLinejoin: 'round' }}>
                                    <polyline points="6 9 12 15 18 9" />
                                </svg>
                            </span>
                        </HideOnMobileTitle>
                    )}
                    {hasMediaModeContent && (
                        <MediaModeContainer $blur={shouldBlurMedia && !mediaExpanded}>
                            <InlineMedia url={pickInlineMediaUrl(firstLinkInContent)} variant="root_post" autoPlay mediaMeta={mediaMetaArr[0] || null} />
                        </MediaModeContainer>
                    )}
                    {mediaExpanded && (() => {
                        const showMedia = !hasMediaModeContent && firstLinkInContent && (isDirectImage || isPrimaryVideo);
                        if (!showMedia && !expandedTextBody) return null;
                        return (
                            <>
                                {showMedia && (
                                    <MediaModeContainer $blur={false}>
                                        <InlineMedia url={pickInlineMediaUrl(firstLinkInContent)} variant="root_post" autoPlay mediaMeta={mediaMetaArr[0] || null} />
                                    </MediaModeContainer>
                                )}
                                {expandedTextBody && (
                                    <div style={{ padding: '0.4rem 0' }}>
                                        <MarkdownRenderer text={expandedTextBody} />
                                    </div>
                                )}
                            </>
                        );
                    })()}
                    {post && post.feed_bucket && post.feed_bucket !== 'guest' && hasMediaModeContent && (
                        <FeedReasonLine>
                            {post.feed_bucket === 'following' && (post.feed_debug?.reason || 'Following')}
                            {post.feed_bucket === 'similar' && (post.feed_debug?.reason || 'Similar taste match')}
                            {post.feed_bucket === 'liked' && (post.feed_debug?.reason || 'Liked topic/author')}
                            {post.feed_bucket === 'discovery' && (post.feed_debug?.reason || 'Discovery')}
                            {post.feed_bucket === 'popular' && (post.feed_debug?.reason || 'Popular post')}
                            {post.feed_bucket === 'discussion' && (post.feed_debug?.reason || 'Active discussion')}
                            {post.feed_bucket === 'second_chance' && (post.feed_debug?.reason || 'Second chance')}
                            {post.feed_bucket === 'fresh' && (post.feed_debug?.reason || 'Fresh pick')}
                            {post.feed_bucket === 'newest' && (post.feed_debug?.reason || 'Newest')}
                            {post.feed_debug && typeof post.feed_debug.score === 'number' && (
                                <ScoreDisplay>
                                    score {post.feed_debug.score}
                                </ScoreDisplay>
                            )}
                        </FeedReasonLine>
                    )}
                    <MetaRow style={compactMetaRowStyle}>
                        <VoteInline>
                            <VoteSection inline state={state} post={post} updatePost={updatePost} />
                            <MetaSeparatorAction>•</MetaSeparatorAction>
                        </VoteInline>
                        <Link to={`/p/${targetPostId}`} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                            <Icon aria-hidden="true">
                                <svg viewBox="0 0 24 24">
                                    <path d="M4 4h16v12H5.17L4 17.17V4zm0-2a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H4z"></path>
                                </svg>
                            </Icon>
                            <span>{renderCommentCount()}</span>
                        </Link>
                        <MetaSeparatorAction>•</MetaSeparatorAction>
                        <span onClick={handleShare} style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
                            <Icon aria-hidden="true">
                                <svg viewBox="0 0 458.624 458.624">
                                    <path d="M339.588,314.529c-14.215,0-27.456,4.133-38.621,11.239l-112.682-78.67c1.809-6.315,2.798-12.976,2.798-19.871 c0-6.896-0.989-13.557-2.798-19.871l109.64-76.547c11.764,8.356,26.133,13.286,41.662,13.286c39.79,0,72.047-32.257,72.047-72.047 C411.634,32.258,379.378,0,339.588,0c-39.79,0-72.047,32.257-72.047,72.047c0,5.255,0.578,10.373,1.646,15.308l-112.424,78.491 c-10.974-6.759-23.892-10.666-37.727-10.666c-39.79,0-72.047,32.257-72.047,72.047s32.256,72.047,72.047,72.047 c13.834,0,26.753-3.907,37.727-10.666l113.292,79.097c-1.629,6.017-2.514,12.34-2.514,18.872c0,39.79,32.257,72.047,72.047,72.047 c39.79,0,72.047-32.257,72.047-72.047C411.635,346.787,379.378,314.529,339.588,314.529z" fill="currentColor" />
                                </svg>
                            </Icon>
                            <ShareText>share</ShareText>
                        </span>
                    </MetaRow>
                    {shareCopied && (
                        <ShareSuccessMessage>
                            link copied to clipboard
                        </ShareSuccessMessage>
                    )}
                    {confirmBlockPost && (
                        <BlockConfirmMessage>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                                <span style={{ whiteSpace: 'nowrap' }}>Block this post?</span>
                                <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0 }}>
                                    <Button variant="warning" size="sm" onClick={confirmBlockPostAction}>
                                        Block
                                    </Button>
                                    <Button variant="ghost" size="sm" onClick={cancelBlockPost}>Cancel</Button>
                                </ConfirmButtons>
                            </div>
                        </BlockConfirmMessage>
                    )}
                    {confirmBlockUser && (
                        <BlockConfirmMessage>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                                <span style={{ whiteSpace: 'nowrap' }}>Block {post?.username || 'this user'}?</span>
                                <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0 }}>
                                    <Button variant="warning" size="sm" onClick={confirmBlockUserAction}>
                                        Block
                                    </Button>
                                    <Button variant="ghost" size="sm" onClick={cancelBlockUser}>Cancel</Button>
                                </ConfirmButtons>
                            </div>
                        </BlockConfirmMessage>
                    )}
                    {confirmBlockTopic && (
                        <BlockConfirmMessage style={blockingTopic ? { opacity: 0.5, pointerEvents: 'none' } : undefined}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                                <span style={{ whiteSpace: 'nowrap', display: 'inline-flex', alignItems: 'baseline' }}>
                                    Block #<span style={{ position: 'relative', display: 'inline-block' }}>
                                        <span
                                            ref={blockTopicMeasureRef}
                                            aria-hidden="true"
                                            style={{
                                                position: 'absolute',
                                                visibility: 'hidden',
                                                whiteSpace: 'pre',
                                                font: 'inherit',
                                                fontSize: 'inherit',
                                                pointerEvents: 'none',
                                            }}
                                        >{blockTopicInput || ' '}</span>
                                        <input
                                            type="text"
                                            value={blockTopicInput}
                                            disabled={blockingTopic}
                                            onChange={(e) => {
                                                const v = e.target.value.toLowerCase().replace(/[^a-z0-9*]/g, '').replace(/\*{2,}/g, '*');
                                                setBlockTopicInput(v);
                                                if (blockTopicError) setBlockTopicError('');
                                                requestAnimationFrame(() => {
                                                    if (blockTopicMeasureRef.current) {
                                                        setBlockTopicInputWidth(blockTopicMeasureRef.current.offsetWidth + 2);
                                                    }
                                                });
                                            }}
                                            onKeyDown={(e) => { if (e.key === 'Enter' && !blockingTopic) confirmBlockTopicAction(); if (e.key === 'Escape' && !blockingTopic) cancelBlockTopic(); }}
                                            autoFocus
                                            ref={(el) => {
                                                if (el && blockTopicMeasureRef.current) {
                                                    setBlockTopicInputWidth(blockTopicMeasureRef.current.offsetWidth + 2);
                                                }
                                            }}
                                            style={{
                                                background: 'transparent',
                                                border: 'none',
                                                borderBottom: `1px solid ${theme.colors.muted}`,
                                                color: 'inherit',
                                                font: 'inherit',
                                                fontSize: 'inherit',
                                                padding: 0,
                                                width: `${blockTopicInputWidth}px`,
                                                maxWidth: '200px',
                                                outline: 'none',
                                            }}
                                            placeholder="topic*"
                                        />
                                    </span>{blockingTopic ? '…' : '?'}
                                </span>
                                <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0 }}>
                                    <Button variant="warning" size="sm" onClick={confirmBlockTopicAction} disabled={!blockTopicInput.trim() || blockingTopic}>
                                        {blockingTopic ? 'Blocking…' : 'Block'}
                                    </Button>
                                    <Button variant="ghost" size="sm" onClick={cancelBlockTopic} disabled={blockingTopic}>Cancel</Button>
                                </ConfirmButtons>
                            </div>
                        </BlockConfirmMessage>
                    )}
                    {blockTopicSuccess && (
                        <ShareSuccessMessage>
                            {blockTopicSuccess}
                        </ShareSuccessMessage>
                    )}
                    {blockTopicError && (
                        <div style={{
                            background: theme.colors.dangerBg,
                            border: `1px solid ${theme.colors.dangerBorder}`,
                            borderRadius: '4px',
                            padding: '0.75rem 1rem',
                            margin: '0.5rem 0.5rem 0.5rem 0',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            color: theme.colors.danger,
                            fontSize: '0.8rem',
                        }}>
                            {blockTopicError}
                        </div>
                    )}
                    {confirmDelete && (
                        <BlockConfirmMessage>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                                <span style={{ whiteSpace: 'nowrap' }}>Mark post as deleted?</span>
                                <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0 }}>
                                    <Button variant="warning" size="sm" onClick={confirmDeletePostAction} disabled={isDeleting}>
                                        Delete
                                    </Button>
                                    <Button variant="ghost" size="sm" onClick={cancelDeletePost}>Cancel</Button>
                                </ConfirmButtons>
                            </div>
                        </BlockConfirmMessage>
                    )}
                    {confirmSuspendQuests && (
                        <BlockConfirmMessage>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                                <span style={{ whiteSpace: 'nowrap' }}>Suspend this user from quests:</span>
                                <select
                                    value={suspendDuration}
                                    onChange={(e) => setSuspendDuration(Number(e.target.value))}
                                    style={{ padding: '0.25rem 0.5rem', borderRadius: '4px', border: `1px solid ${theme.colors.warningBorder}`, background: theme.colors.warningBg, color: theme.colors.warning, fontWeight: 500 }}
                                >
                                    <option value={1}>1 day</option>
                                    <option value={3}>3 days</option>
                                    <option value={7}>7 days</option>
                                    <option value={30}>30 days</option>
                                    <option value={0}>Permanent</option>
                                </select>
                                <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0 }}>
                                    <Button variant="warning" size="sm" onClick={confirmSuspendFromQuests} disabled={isSuspending}>
                                        {isSuspending ? 'Suspending...' : 'Suspend'}
                                    </Button>
                                    <Button variant="ghost" size="sm" onClick={cancelSuspendFromQuests}>Cancel</Button>
                                </ConfirmButtons>
                            </div>
                        </BlockConfirmMessage>
                    )}
                    {confirmUnsuspend && (
                        <BlockConfirmMessage>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                                <span style={{ whiteSpace: 'nowrap' }}>Unsuspend this user from quests?</span>
                                <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0 }}>
                                    <Button variant="warning" size="sm" onClick={confirmUnsuspendFromQuests} disabled={isUnsuspending}>
                                        {isUnsuspending ? 'Unsuspending...' : 'Unsuspend'}
                                    </Button>
                                    <Button variant="ghost" size="sm" onClick={cancelUnsuspendFromQuests}>Cancel</Button>
                                </ConfirmButtons>
                            </div>
                        </BlockConfirmMessage>
                    )}
                    {suspendSuccess && (
                        <div style={{
                            background: theme.colors.successBg,
                            border: `1px solid ${theme.colors.successBorder}`,
                            borderRadius: '4px',
                            padding: '0.75rem 1rem',
                            margin: '0.5rem 0.5rem 0.5rem 0',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            color: theme.colors.success,
                            fontSize: '0.8rem',
                        }}>
                            {suspendSuccess}
                        </div>
                    )}
                    {confirmDonate && (
                        <BlockConfirmMessage>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                                <span style={{ whiteSpace: 'nowrap' }}>
                                    Gift Mirage to {post?.username || post?.user_id?.substring(0, 12) + '...'}:
                                </span>
                                <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.35rem',
                                    background: theme.colors.inputBackground,
                                    border: `1px solid ${theme.colors.borderSubtle}`,
                                    borderRadius: '6px',
                                    padding: '0.2rem 0.5rem',
                                }}>
                                    <input
                                        type="text"
                                        inputMode="numeric"
                                        value={formatDonateAmount(donateAmountRaw)}
                                        onChange={(e) => setDonateAmountRaw(e.target.value.replace(/[^\d]/g, ""))}
                                        placeholder="10,000"
                                        maxLength={11}
                                        disabled={isSendPending(post?.user_id)}
                                        style={{
                                            width: '6.0rem',
                                            background: 'transparent',
                                            border: 'none',
                                            outline: 'none',
                                            color: theme.colors.text,
                                            fontSize: '0.8rem',
                                            fontWeight: 700,
                                            textAlign: 'right',
                                        }}
                                    />
                                    <span style={{ fontSize: '0.68rem', color: theme.colors.textSecondary }}>MIRAGE</span>
                                </div>
                                <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0 }}>
                                    <Button
                                        variant="warning"
                                        size="sm"
                                        onClick={confirmDonateAction}
                                        disabled={isSendPending(post?.user_id)}
                                    >
                                        {formatSendStatus(post?.user_id) || 'Confirm'}
                                    </Button>
                                    <Button variant="ghost" size="sm" onClick={cancelDonate}>Cancel</Button>
                                </ConfirmButtons>
                            </div>
                        </BlockConfirmMessage>
                    )}
                    {donateMessage && (
                        <div style={{
                            background: donateMessage.type === 'success' ? theme.colors.successBg : theme.colors.dangerBg,
                            border: `1px solid ${donateMessage.type === 'success' ? theme.colors.successBorder : theme.colors.dangerBorder}`,
                            borderRadius: '4px',
                            padding: '0.75rem 1rem',
                            margin: '0.5rem 0.5rem 0.5rem 0',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            color: donateMessage.type === 'success' ? theme.colors.success : theme.colors.danger,
                            fontSize: '0.8rem',
                        }}>
                            {donateMessage.message}
                        </div>
                    )}
                    {confirmGiftSub && (
                        <BlockConfirmMessage>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', width: '100%' }}>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                                    <span style={{ whiteSpace: 'nowrap' }}>
                                        {confirmGiftSub.level === 10 ? 'Gift agent subscription' : 'Gift subscription'} to {post?.username || post?.user_id?.substring(0, 12) + '...'}?{(confirmGiftSub.level === 10 ? agentFeeLabel : subFeeLabel) ? ` (${confirmGiftSub.level === 10 ? agentFeeLabel : subFeeLabel})` : ''}
                                    </span>
                                    {confirmGiftSub.loading && (
                                        <span style={{ fontSize: '0.75rem', opacity: 0.7 }}>Loading expiry...</span>
                                    )}
                                    {confirmGiftSub.expiryLabel && (
                                        <span style={{ fontSize: '0.75rem', opacity: 0.7 }}>{confirmGiftSub.expiryLabel}</span>
                                    )}
                                    {confirmGiftSub.error && (
                                        <span style={{ fontSize: '0.75rem', color: theme.colors.danger }}>{confirmGiftSub.error}</span>
                                    )}
                                </div>
                                <ConfirmButtons style={{ marginLeft: 'auto', flexShrink: 0 }}>
                                    <Button
                                        variant="warning"
                                        size="sm"
                                        onClick={confirmGiftSubAction}
                                        disabled={isSubscribePending(post?.user_id) || confirmGiftSub.loading || !!confirmGiftSub.error}
                                    >
                                        {formatSubscribeStatus(post?.user_id) || 'Confirm'}
                                    </Button>
                                    <Button variant="ghost" size="sm" onClick={cancelGiftSub}>Cancel</Button>
                                </ConfirmButtons>
                            </div>
                        </BlockConfirmMessage>
                    )}
                    {giftSubMessage && (
                        <div style={{
                            background: giftSubMessage.type === 'success' ? theme.colors.successBg : theme.colors.dangerBg,
                            border: `1px solid ${giftSubMessage.type === 'success' ? theme.colors.successBorder : theme.colors.dangerBorder}`,
                            borderRadius: '4px',
                            padding: '0.75rem 1rem',
                            margin: '0.5rem 0.5rem 0.5rem 0',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            color: giftSubMessage.type === 'success' ? theme.colors.success : theme.colors.danger,
                            fontSize: '0.8rem',
                        }}>
                            {giftSubMessage.message}
                        </div>
                    )}
                    {confirmAward && (
                        <BlockConfirmMessage>
                            <div style={{ width: '100%' }}>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                                    <span style={{ fontWeight: 600, fontSize: '0.85rem', whiteSpace: 'nowrap', flexShrink: 0 }}>Give Award</span>
                                    <ConfirmButtons>
                                        <Button variant="ghost" size="sm" onClick={cancelAward}>Cancel</Button>
                                    </ConfirmButtons>
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.4rem' }}>
                                    {AWARD_TYPES.map(award => {
                                        const costUmirage = getAwardCost(award.name);
                                        const costMirage = costUmirage != null && costUmirage > 0 ? (costUmirage / 1_000_000).toLocaleString() + ' MIRAGE' : null;
                                        const canAfford = costUmirage != null && (userBalanceUmirage !== null && userBalanceUmirage >= costUmirage);
                                        const disabled = isAwarding || !canAfford;
                                        return (
                                            <button
                                                key={award.name}
                                                onClick={() => canAfford && confirmAwardAction(award.name)}
                                                disabled={disabled}
                                                style={{
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '0.4rem',
                                                    padding: '0.45rem 0.6rem',
                                                    background: theme.colors.surface2,
                                                    border: `1px solid ${theme.colors.borderSubtle}`,
                                                    borderRadius: '6px',
                                                    color: theme.colors.text,
                                                    cursor: disabled ? (isAwarding ? 'wait' : 'not-allowed') : 'pointer',
                                                    opacity: disabled ? 0.4 : 1,
                                                    fontSize: '0.78rem',
                                                    transition: 'background 0.15s, opacity 0.15s',
                                                }}
                                                onMouseEnter={e => { if (!disabled) e.currentTarget.style.background = theme.colors.hover; }}
                                                onMouseLeave={e => { e.currentTarget.style.background = theme.colors.surface2; }}
                                            >
                                                <span style={{ fontSize: '1.1rem' }}>{award.icon}</span>
                                                <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', lineHeight: 1.2 }}>
                                                    <span style={{ fontWeight: 600 }}>{award.label}</span>
                                                    <span style={{ fontSize: '0.68rem', opacity: 0.6, color: !canAfford ? theme.colors.danger : 'inherit' }}>
                                                        {costMirage == null ? 'Loading...' : !canAfford ? 'Insufficient MIRAGE' : costMirage}
                                                    </span>
                                                </span>
                                            </button>
                                        );
                                    })}
                                </div>
                                {isAwarding && <div style={{ textAlign: 'center', marginTop: '0.4rem', fontSize: '0.75rem', opacity: 0.7 }}>Submitting...</div>}
                            </div>
                        </BlockConfirmMessage>
                    )}
                    {awardMessage && (
                        <div style={{
                            background: awardMessage.type === 'success' ? theme.colors.successBg : theme.colors.dangerBg,
                            border: `1px solid ${awardMessage.type === 'success' ? theme.colors.successBorder : theme.colors.dangerBorder}`,
                            borderRadius: '4px',
                            padding: '0.75rem 1rem',
                            margin: '0.5rem 0.5rem 0.5rem 0',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            color: awardMessage.type === 'success' ? theme.colors.success : theme.colors.danger,
                            fontSize: '0.8rem',
                        }}>
                            {awardMessage.message}
                        </div>
                    )}
                    {showContent && post.content && (
                        <InlineTeaserMedia url={sanitizeUrlForLink(extractFirstUrl(post.content) || post.content)} mediaMeta={mediaMetaArr[0] || null} />
                    )}
                    {footer && (
                        <StyledFooter>{footer}</StyledFooter>
                    )}
                </StyledContentArea>
            </StyledMainContainer>
        </div>
    )
}

// Memoize to prevent re-renders when parent state changes but post data hasn't
export default memo(CardView, (prevProps, nextProps) => {
    // Only re-render if the post data or key callbacks changed
    const prevPost = prevProps.post;
    const nextPost = nextProps.post;
    if (!prevPost || !nextPost) return false;

    // Check essential post fields that affect rendering
    return (
        prevPost.post_id === nextPost.post_id &&
        prevPost.upvotes === nextPost.upvotes &&
        prevPost.downvotes === nextPost.downvotes &&
        prevPost.points === nextPost.points &&
        prevPost.direction === nextPost.direction &&
        prevPost.user_vote === nextPost.user_vote &&
        prevPost.comment_count === nextPost.comment_count &&
        prevPost.title === nextPost.title &&
        prevPost.content === nextPost.content &&
        prevPost.deleted === nextPost.deleted &&
        prevPost.collapsed === nextPost.collapsed &&
        prevPost.flash === nextPost.flash &&
        JSON.stringify(prevPost.awards) === JSON.stringify(nextPost.awards) &&
        prevProps.state?.username === nextProps.state?.username &&
        prevProps.state?.publicKey === nextProps.state?.publicKey
    );
});


