import React, { useEffect, useState, useRef, memo } from "react";
import ReactDOM from "react-dom";
import styled from "styled-components"
import { Link } from 'react-router-dom';
import VoteSection from "./VoteSection";
import InlineMedia from "./InlineMedia";
import Button from "./Button";
import Storage from '../utils/Storage';
import * as tx from "../utils/tx.js";
import Api from '../lib/api';
import { subscribe, unsubscribe, isSubscribed } from '../utils/Subscriptions';
import { follow, unfollow, isFollowing } from '../utils/FollowUsers';
import { darkColors as fallbackDarkColors } from "../styled/colors/dark";
import { lightColors as fallbackLightColors } from "../styled/colors/light";
import { buildPhotonUrl, buildWsrvUrl, buildBlurredWsrvUrl, isLikelyImageUrl, isLikelyVideoUrl, redgifsCanonicalWatchUrl } from "../utils/media";

const pickCard = (theme, key) => {
    if (theme?.colors?.[key]) return theme.colors[key];
    const isLight = theme?.name === 'light';
    return (isLight ? fallbackLightColors : fallbackDarkColors)[key];
};


const StyledMainContainer = styled.div`
    background: ${({ theme }) => pickCard(theme, 'card')};
    border: 1px solid ${({ theme }) => pickCard(theme, 'cardBorder')};
    border-radius: 12px;
    display: flex;    
    min-height: auto;
    flex-direction: row;
    text-align: left;
    align-items: flex-start;
    padding: 1.5rem;
    margin: 0;
    contain: layout style;
    will-change: transform;
    box-shadow: ${({ theme }) => theme?.name === 'light' ? '0 4px 12px rgba(0, 0, 0, 0.1)' : 'none'};

    &:hover {
        background: ${({ theme }) => pickCard(theme, 'cardAlt')};
        box-shadow: ${({ theme }) => theme?.name === 'light' ? '0 6px 20px rgba(0, 0, 0, 0.15)' : 'none'};
    }

    position: relative;
    overflow: hidden;
    
    ${(props) => props.isFlash ? `
        animation: flashGlow 0.5s ease-out forwards;
    ` : ``}

    @keyframes flashGlow {
        0% { background: rgba(255, 255, 200, 0.3); }
        100% { background: ${(props) => props.theme?.colors?.card || '#1a1a1a'}; }
    }

    @media (max-width: 1000px) {
        padding: 1rem;
        border-radius: 10px;
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
    border-radius: 12px;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    background: linear-gradient(135deg, #f3f4f6, #e5e7eb);
    border: 1px solid rgba(255, 255, 255, 0.2);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    transition: transform 0.3s ease;

    &:hover {
        transform: scale(1.05);
    }
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
        border-radius: 12px;
        overflow: hidden;
        border: 1px solid ${({ theme }) => pickCard(theme, 'cardBorder')};
        background: ${({ theme }) => pickCard(theme, 'cardAlt')};
        position: relative;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
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
        color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
        margin: 0 0 0.35rem 0;
    }

    a {
        color: inherit;
        text-decoration: none;
        font-weight: 600;
    }

    a:hover {
        color: ${({ theme }) => theme?.colors?.text || '#FFF'};
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

// Helper component to render the title scaled down to fit within the card area (for image cards)
function MobileCardFitTitle({ titleText, children }) {
    const overlayRef = useRef(null);
    const textRef = useRef(null);

    useEffect(() => {
        const el = textRef.current;
        const parent = overlayRef.current;
        if (!el || !parent) return;
        // Reset font-size to a reasonable starting point based on viewport width
        let base = 16;
        try {
            if (typeof window !== 'undefined') {
                base = Math.max(10, Math.min(18, Math.floor(window.innerWidth * 0.04)));
            }
        } catch (_) { /* ignore */ }
        el.style.fontSize = base + 'px';
        el.style.wordBreak = 'break-word';
        el.style.overflow = 'hidden';
        el.style.display = 'block';
        // Shrink until it fits or until minimum size
        let size = base;
        const minSize = 8;
        let guard = 0;
        while (guard < 80 && parent && el && (el.scrollHeight > parent.clientHeight - 8) && size > minSize) {
            size -= 1;
            el.style.fontSize = size + 'px';
            guard += 1;
        }
    }, [titleText]);

    return (
        <>
            {children}
            <MobileCardTitleBar ref={overlayRef}>
                <span ref={textRef}>{titleText}</span>
            </MobileCardTitleBar>
        </>
    );
}

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
    background: ${({ $gradient }) => $gradient || '#fff'};
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
    color: rgba(0, 0, 0, 0.85);
    font-weight: 800;
    text-align: center;
    padding: 1rem 1.5rem;
    box-sizing: border-box;
    overflow: hidden;
    
    /* Noise texture overlay for depth */
    &::before {
        content: '';
        position: absolute;
        inset: 0;
        background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
        opacity: 0.04;
        pointer-events: none;
        z-index: 1;
    }
    
    /* Subtle inner glow */
    &::after {
        content: '';
        position: absolute;
        inset: 0;
        box-shadow: inset 0 0 60px rgba(255, 255, 255, 0.15);
        pointer-events: none;
        z-index: 2;
    }
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
    color: rgba(0, 0, 0, 0.12);
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
    text-shadow: 0 1px 2px rgba(255, 255, 255, 0.3);
    max-height: 100%;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
`

// Generate a unique gradient based on post hash
const generatePostGradient = (post) => {
    // Get a hash-like value from post data
    const base = String((post && (post.post_id || post.tx_hash)) || '')
        || String((post && post.title) || '')
        || String((post && post.timestamp) || '');

    let hash = 0;
    for (let i = 0; i < base.length; i++) {
        hash = ((hash << 5) - hash) + base.charCodeAt(i);
        hash |= 0;
    }

    // Curated gradient palettes - vibrant but readable with dark text
    const gradients = [
        // Warm sunset
        'linear-gradient(135deg, #ffecd2 0%, #fcb69f 50%, #ff9a9e 100%)',
        // Ocean breeze
        'linear-gradient(135deg, #a8edea 0%, #fed6e3 50%, #ffecd2 100%)',
        // Lavender dream
        'linear-gradient(135deg, #e0c3fc 0%, #8ec5fc 50%, #f5f7fa 100%)',
        // Citrus burst
        'linear-gradient(135deg, #fff1eb 0%, #ace0f9 50%, #f5f7fa 100%)',
        // Mint fresh
        'linear-gradient(135deg, #d4fc79 0%, #96e6a1 50%, #84fab0 100%)',
        // Peach glow
        'linear-gradient(135deg, #ffeaa7 0%, #ffecd2 50%, #fcb69f 100%)',
        // Arctic aurora
        'linear-gradient(135deg, #c1dfc4 0%, #deecdd 50%, #f5f7fa 100%)',
        // Coral reef
        'linear-gradient(135deg, #ff9a9e 0%, #fecfef 50%, #ffecd2 100%)',
        // Morning sky
        'linear-gradient(135deg, #89f7fe 0%, #66a6ff 50%, #a8edea 100%)',
        // Rose gold
        'linear-gradient(135deg, #f5f7fa 0%, #ffecd2 50%, #fcb69f 100%)',
        // Electric lime
        'linear-gradient(135deg, #d4fc79 0%, #96e6a1 50%, #c1dfc4 100%)',
        // Soft violet
        'linear-gradient(135deg, #f5f7fa 0%, #e0c3fc 50%, #8ec5fc 100%)',
        // Honey dew
        'linear-gradient(135deg, #ffeaa7 0%, #dfe6e9 50%, #b2bec3 100%)',
        // Pastel sky
        'linear-gradient(135deg, #a8edea 0%, #fed6e3 50%, #e0c3fc 100%)',
        // Warm sand
        'linear-gradient(135deg, #ffecd2 0%, #fcb69f 50%, #ffeaa7 100%)',
        // Cool mint
        'linear-gradient(135deg, #84fab0 0%, #8fd3f4 50%, #a8edea 100%)',
    ];

    const index = Math.abs(hash) % gradients.length;
    return gradients[index];
};

const MobileCardTitleBar = styled.div`
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 0.5rem 0.65rem;
    color: #fff;
    font-weight: 700;
    font-size: clamp(0.60rem, 3.2vw, 1.0rem);
    line-height: 1.15;
    text-shadow: 0 1px 2px rgba(0,0,0,0.65);
    pointer-events: none;
    z-index: 2;
    /* Extend the gradient well above the bar for readability on bright images */
    &::before {
        content: '';
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        height: 200%;
        background: linear-gradient(to top, rgba(0,0,0,0.75) 0%, rgba(0,0,0,0.5) 50%, rgba(0,0,0,0) 100%);
        z-index: -1;
    }
`

const HideOnMobileTitle = styled.div`
    margin: 0.4rem 0;
    @media (max-width: 600px) {
        display: none;
    }
`

const StyledLink = styled(Link)`
    color: ${({ theme }) => theme?.colors?.link || '#FFFFFF'};
    text-decoration: none;

    &:hover {
      color: ${({ theme }) => theme?.colors?.linkHover || '#CCCCCC'};
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
    color: ${({ theme }) => theme?.colors?.subtleText || '#CCCCCC'};
    text-decoration: none;
    font-weight: bold;

    &:hover {
        color: ${({ theme }) => theme?.colors?.text || '#EEEEEE'};
    }
`


// Success box styled like the delete confirmation but in green
const ShareSuccessMessage = styled.div`
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

// legacy inline comment/topic link and admin/user buttons removed (unused)

const BlockConfirmMessage = styled.div`
    background-color: rgba(251, 191, 36, 0.1);
    border: 1px solid #f59e0b;
    border-radius: 3px;
    padding: 0.75rem 1rem;
    margin: 0.5rem 0.5rem 0.5rem 0;
    color: #f59e0b;
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 0.5rem;
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
    border-top: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
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
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.60rem;
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
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
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
        color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
        font-size: 0.60rem;
        font-weight: 400;
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
    padding: 0.1rem 0.4rem;
    border-radius: 999px;
    background: ${({ $tag }) => (tagColors[$tag]?.bg || tagColors.default.bg)};
    color: ${({ $tag }) => (tagColors[$tag]?.text || tagColors.default.text)};
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: lowercase;
    border: 1px solid ${({ $tag }) => (tagColors[$tag]?.border || tagColors.default.border)};
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
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.60rem;
    font-weight: 600;
    font-style: italic;
    cursor: help;
`;

// Debug tooltip for feed explanation (rendered via portal)
const FeedDebugTooltip = styled.div`
    position: fixed;
    z-index: 10000;
    background: ${({ theme }) => theme?.name === 'light' ? '#ffffff' : (theme?.colors?.cardBackground || '#1a1a1a')};
    border: 1px solid ${({ theme }) => theme?.name === 'light' ? '#e0e0e0' : (theme?.colors?.border || '#333')};
    border-radius: 6px;
    padding: 0.75rem;
    min-width: 420px;
    max-width: 560px;
    font-style: normal;
    font-weight: 400;
    font-size: 0.7rem;
    line-height: 1.4;
    text-align: left;
    box-shadow: ${({ theme }) => theme?.name === 'light' ? '0 4px 12px rgba(0, 0, 0, 0.15)' : '0 4px 12px rgba(0, 0, 0, 0.3)'};
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
    /* Use main text color for maximum contrast in both themes */
    color: ${({ theme }) => theme?.colors?.text || (theme?.name === 'light' ? '#111111' : '#f5f5f5')};
`;

const FeedDebugValue = styled.span`
    color: ${({ theme }) => theme?.colors?.text || (theme?.name === 'light' ? '#000000' : '#ffffff')};
    font-weight: 600;
`;

const FeedDebugExplanation = styled.div`
    margin-top: 0.5rem;
    padding-top: 0.5rem;
    border-top: 1px solid ${({ theme }) => theme?.name === 'light' ? '#e0e0e0' : (theme?.colors?.border || '#333')};
    color: ${({ theme }) => theme?.colors?.subtleText || (theme?.name === 'light' ? '#555555' : '#aaaaaa')};
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
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
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
`

const MenuContainer = styled.div`
    position: relative;
    display: inline-block;
`

const MenuDropdown = styled.div`
    position: fixed;
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    border-radius: 8px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
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
        border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    }

    &[data-danger="true"] {
        color: #ff6b6b;
    }
`



const MediaWrapper = styled.div`
    margin-top: 0.35rem;
    max-width: 100%;
`

const StyledFooter = styled.div`
    margin-top: 0rem;
    border-top: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    padding-top: 0.15rem;
    display: flex;
    justify-content: flex-start;
    font-size: 0.5rem;
`

// Simple tooltip rendered via portal (like FeedDebugTooltip)
const TimeTooltip = styled.div`
    position: fixed;
    z-index: 10000;
    background: ${({ theme }) => theme?.name === 'light' ? '#ffffff' : '#1a1a1a'};
    border: 1px solid ${({ theme }) => theme?.name === 'light' ? '#e0e0e0' : '#333'};
    border-radius: 6px;
    padding: 0.35rem 0.5rem;
    font-size: 0.7rem;
    font-weight: 600;
    white-space: nowrap;
    box-shadow: ${({ theme }) => theme?.name === 'light' ? '0 4px 12px rgba(0, 0, 0, 0.15)' : '0 4px 12px rgba(0, 0, 0, 0.3)'};
    color: ${({ theme }) => theme?.colors?.text || '#ccc'};
`;

const TimeWrapper = styled.span`
    cursor: help;
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

function CardView({ state, post, updatePost, showContent = false, footer = null }) {
    const [confirmDelete, setConfirmDelete] = useState(false);
    const [isDeleting, setIsDeleting] = useState(false);
    const [shareCopied, setShareCopied] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 });
    const [feedTooltipOpen, setFeedTooltipOpen] = useState(false);
    const [feedTooltipPosition, setFeedTooltipPosition] = useState({ top: 0, left: 0 });
    const feedReasonRef = useRef(null);
    const [timeTooltipOpen, setTimeTooltipOpen] = useState(false);
    const [timeTooltipPosition, setTimeTooltipPosition] = useState({ top: 0, left: 0 });
    const timeRef = useRef(null);
    const [blurSensitiveMedia, setBlurSensitiveMedia] = useState(() => {
        try {
            const val = Storage.load('blur_sensitive_media', true);
            return val === false ? false : true;
        } catch (_) {
            return true;
        }
    });
    const [cardSize, setCardSize] = useState(() => {
        try {
            return Storage.load('card_size', 'large');
        } catch (_) {
            return 'large';
        }
    });
    const menuRef = useRef(null);
    const menuButtonRef = useRef(null);
    const isMountedRef = useRef(true);
    useEffect(() => {
        return () => { isMountedRef.current = false; };
    }, []);

    // Determine hide flag first, but do not return before hooks
    const hideTeaser = (!post || post.deleted || typeof post.title !== 'string' || post.title.trim() === '' || typeof post.topic !== 'string' || post.topic.trim() === '');

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
                    setCardSize(e.detail.cardSize);
                    return;
                }
                const val = Storage.load('blur_sensitive_media', true);
                setBlurSensitiveMedia(val === false ? false : true);
                const size = Storage.load('card_size', 'large');
                setCardSize(size);
            } catch (_) { }
        };
        window.addEventListener('settingsUpdated', handleSettingsUpdated);
        return () => window.removeEventListener('settingsUpdated', handleSettingsUpdated);
    }, []);

    // Set CSS custom properties for card gap based on compact mode
    useEffect(() => {
        const isCompactMode = cardSize === 'compact';
        const root = document.documentElement;
        root.style.setProperty('--card-gap', isCompactMode ? '0.5rem' : '1.5rem');
        root.style.setProperty('--card-gap-mobile', isCompactMode ? '0.25rem' : '0.5rem');
        root.style.setProperty('--card-margin-top', isCompactMode ? '0.35rem' : '1rem');
        root.style.setProperty('--card-margin-top-mobile', isCompactMode ? '0.2rem' : '0.5rem');
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
        if (!post || !post.post_id) return;
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
        window.location.href = `/view_post?post_id=${targetPostId}&edit=true`;
    };

    const handleDonate = () => {
        setMenuOpen(false);
        if (!post || !post.post_id) return;
        const targetPostId = post.post_id;
        window.location.href = `/view_post?post_id=${targetPostId}`;
    };

    const handleBlockPost = () => {
        setMenuOpen(false);
        if (!post || !post.post_id) return;
        const blockedPosts = Storage.load('blocked_posts', []);
        if (!blockedPosts.includes(post.post_id)) {
            blockedPosts.push(post.post_id);
            Storage.save('blocked_posts', blockedPosts);
            if (updatePost) {
                updatePost(post.post_id, { blocked: true });
            }
        }
    };

    const handleBlockUser = () => {
        setMenuOpen(false);
        if (!post || !post.author) return;
        const blockedUsers = Storage.load('blocked_users', []);
        const authorAddress = String(post.author).toLowerCase();
        if (!blockedUsers.includes(authorAddress)) {
            blockedUsers.push(authorAddress);
            Storage.save('blocked_users', blockedUsers);
        }
    };

    const handleFollowUser = async () => {
        setMenuOpen(false);
        if (!post || !post.author) return;
        const authorAddress = post.author;
        const viewerAddress = Storage.load('publicKey', '');
        if (!viewerAddress || viewerAddress === 'guest') {
            alert('Please log in to follow users');
            return;
        }
        try {
            await follow(viewerAddress, authorAddress);
            if (updatePost) {
                updatePost(post.post_id, {});
            }
        } catch (err) {
            alert(`Error following user: ${err.message || 'Unknown error'}`);
        }
    };

    const handleUnfollowUser = async () => {
        setMenuOpen(false);
        if (!post || !post.author) return;
        const authorAddress = post.author;
        const viewerAddress = Storage.load('publicKey', '');
        if (!viewerAddress || viewerAddress === 'guest') {
            return;
        }
        try {
            await unfollow(viewerAddress, authorAddress);
            if (updatePost) {
                updatePost(post.post_id, {});
            }
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
        } catch (err) {
            alert(`Error unfollowing topic: ${err.message || 'Unknown error'}`);
        }
    };

    // Check if user follow/block state
    const viewerAddress = Storage.load('publicKey', '');
    const authorAddress = post && post.author ? String(post.author).toLowerCase() : '';
    const isFollowingAuthor = authorAddress && viewerAddress && viewerAddress !== 'guest' ? isFollowing(viewerAddress, authorAddress) : false;
    const isSubscribedToTopic = post && post.topic && viewerAddress && viewerAddress !== 'guest' ? isSubscribed(viewerAddress, post.topic) : false;

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

    const [thumbSrc, setThumbSrc] = useState(null);
    const [thumbBlurSrc, setThumbBlurSrc] = useState(null);
    const [thumbOriginal, setThumbOriginal] = useState(null); // Original URL for fallback
    const [thumbProxy, setThumbProxy] = useState('photon'); // 'photon' | 'wsrv' | 'none'

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

    const firstLinkInContent = (() => {
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

    useEffect(() => {
        // Use thumbnail from database (indexed by backend), or fall back to direct image URL
        const provided = post && typeof post.thumbnail === 'string' && post.thumbnail.trim() ? post.thumbnail.trim() : '';
        const thumbUrl = provided || (isDirectImage ? firstLinkInContent : null);

        setThumbOriginal(thumbUrl);

        if (thumbUrl) {
            // Check if it's a YouTube thumbnail - use direct URL (no proxy needed, CSS handles cropping)
            const isYoutubeThumbnail = thumbUrl.includes('img.youtube.com') || thumbUrl.includes('i.ytimg.com');
            if (isYoutubeThumbnail) {
                setThumbProxy('direct');
                setThumbSrc(thumbUrl);
                setThumbBlurSrc(thumbUrl);
            } else {
                // Try Photon first (works with redgifs), wsrv as fallback on error
                setThumbProxy('photon');
                setThumbSrc(buildPhotonUrl(thumbUrl, { w: 240, h: 240 }));
                setThumbBlurSrc(buildPhotonUrl(thumbUrl, { w: 240, h: 240 })); // Photon doesn't support blur
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

    if (post && post.content && (post.content.startsWith("http://") || post.content.startsWith("https://"))) {
        const firstUrl = sanitizeUrlForLink(extractFirstUrl(post.content));
        if (isLikelyImageUrl(firstUrl) || isLikelyVideoUrl(firstUrl)) {
            // For safe images/videos: open the comment view with this post as root
            title = (<StyledLink to={`/view_post?post_id=${targetPostId}`}>{post.title}</StyledLink>);
        } else {
            // Non-media: keep external link behavior
            const href = firstUrl || `/view_post?post_id=${targetPostId}`;
            title = <StyledLink to={href.startsWith('http') ? href : `/view_post?post_id=${targetPostId}`} target={href.startsWith('http') ? "_blank" : undefined} rel={href.startsWith('http') ? "noopener noreferrer" : undefined}>{post.title}</StyledLink>
        }
    } else if (post) {
        title = (<StyledLink to={`/view_post?post_id=${targetPostId}`}>{post.title}</StyledLink>);
    }

    // Compute click-through behavior for thumbnails to match the title behavior
    let thumbTo = `/view_post?post_id=${targetPostId}`;
    let thumbTarget = undefined;
    let thumbRel = undefined;
    if (post && post.content && (post.content.startsWith("http://") || post.content.startsWith("https://"))) {
        const hrefCandidate = firstLinkInContent || `/view_post?post_id=${targetPostId}`;
        if (isDirectImage || isPrimaryVideo) {
            thumbTo = `/view_post?post_id=${targetPostId}`;
        } else {
            if (hrefCandidate && hrefCandidate.startsWith('http')) {
                thumbTo = hrefCandidate;
                thumbTarget = "_blank";
                thumbRel = "noopener noreferrer";
            } else {
                thumbTo = `/view_post?post_id=${targetPostId}`;
            }
        }
    }

    const hasMedia = !!(thumbSrc || thumbBlurSrc || isDirectImage || isPrimaryVideo);
    const shouldBlurMedia = !!(blurSensitiveMedia && post && post.tag && String(post.tag).trim() && hasMedia);
    const displayThumbSrc = shouldBlurMedia && thumbBlurSrc ? thumbBlurSrc : thumbSrc;

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
        const href = ownerAddress ? `/profile?address=${encodeURIComponent(ownerAddress)}` : '/profile';
        const content = ownerAddress ? (
            <StyledProfileLink to={href}>{display}</StyledProfileLink>
        ) : display;
        return content;
    };


    const InlineTeaserMedia = ({ url }) => {
        return (
            <MediaWrapper>
                <InlineMedia url={pickInlineMediaUrl(url)} />
            </MediaWrapper>
        );
    };

    if (hideTeaser) return null;

    // Compact mode: smaller thumb + tighter spacing on desktop (>600px)
    const isCompact = cardSize === 'compact';

    const renderCommentCount = () => {
        const currentCount = Number.isFinite(Number(post.comments)) ? Math.round(Number(post.comments)) : 0;
        return `${currentCount} comments`;
    };

    const handleShare = async () => {
        try {
            const hasTitle = post && post.title && String(post.title).trim() !== '';
            const isComment = !hasTitle;
            let path = `/view_post?post_id=${encodeURIComponent(targetPostId)}`;
            if (isComment) {
                try {
                    const res = await Api.get('get_root_post_id', { comment_id: targetPostId }, { timeoutMs: 5000 });
                    if (res && res.root_post_id) {
                        const rootId = String(res.root_post_id).toLowerCase();
                        path = `/view_post?post_id=${encodeURIComponent(targetPostId)}&root=${encodeURIComponent(rootId)}#comment-${encodeURIComponent(targetPostId)}`;
                    }
                } catch (_) {
                    /* fallback to sharing the comment itself if root lookup fails */
                }
            }
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
        ? { padding: '0.25rem 0.6rem' }
        : undefined;
    const compactThumbVoteStyle = isCompact
        ? { marginRight: '0.5rem', gap: '0.15rem' }
        : undefined;
    const compactThumbBoxStyle = isCompact
        ? { width: '90px', minWidth: '90px', height: '90px', borderRadius: '8px' }
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
                <ThumbVoteContainer style={compactThumbVoteStyle}>
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
                                    return `/text_post_${String(n).padStart(2, '0')}.png`;
                                } catch (_) {
                                    const n = (Math.floor(Math.random() * 20) % 20) + 1;
                                    return `/text_post_${String(n).padStart(2, '0')}.png`;
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
                                        if (shouldBlurMedia && displayThumbSrc) s.filter = 'blur(10px)';
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
                </ThumbVoteContainer>
                <StyledContentArea>
                    <MobileMetaLine>
                        <Link to={post?.topic ? `/t/${post.topic}` : '#'}>{post?.topic ? `#${post.topic}` : '/unknown'}</Link>
                        {renderAuthorMeta() || <span>@Anonymous</span>}
                        <span>{elapsed} ago</span>
                        {post && post.tag ? <TagBadge $tag={post.tag}>{post.tag}</TagBadge> : null}
                    </MobileMetaLine>
                    <MobileCardWrapper>
                        <MobileCardSquare $gradient={!thumbSrc ? generatePostGradient(post) : undefined}>
                            {(() => {
                                // Use the already-computed proxied thumbnail (Photon primary, wsrv fallback)
                                const displayMobileSrc = shouldBlurMedia && thumbBlurSrc ? thumbBlurSrc : thumbSrc;
                                if (displayMobileSrc) {
                                    return (
                                        <Link to={thumbTo} target={thumbTarget} rel={thumbRel} style={{ display: 'block', position: 'absolute', inset: 0 }}>
                                            <MobileCardFitTitle titleText={post && post.title ? post.title : ''}>
                                                <MobileCardImg
                                                    src={displayMobileSrc}
                                                    alt=""
                                                    loading="lazy"
                                                    style={(() => {
                                                        const s = {};
                                                        if (shouldBlurMedia) s.filter = 'blur(10px)';
                                                        if (isYoutubeThumb) s.transform = `scale(${YOUTUBE_THUMB_ZOOM})`;
                                                        return Object.keys(s).length ? s : undefined;
                                                    })()}
                                                />
                                            </MobileCardFitTitle>
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
                    </MobileCardWrapper>
                    <MetaInfoRow style={compactMetaInfoRowStyle}>
                        <MetaInfoRowLeft>
                            <Link to={post?.topic ? `/t/${post.topic}` : '#'}>{post?.topic ? `#${post.topic}` : '/unknown'}</Link>
                            <MetaSeparator>·</MetaSeparator>
                            {renderAuthorMeta() || <span>@Anonymous</span>}
                            <MetaSeparator>·</MetaSeparator>
                            <TimeWrapper
                                ref={timeRef}
                                onMouseEnter={() => {
                                    if (timeRef.current) {
                                        const rect = timeRef.current.getBoundingClientRect();
                                        setTimeTooltipPosition({
                                            top: rect.top - 8,
                                            left: rect.left + rect.width / 2
                                        });
                                        setTimeTooltipOpen(true);
                                    }
                                }}
                                onMouseLeave={() => setTimeTooltipOpen(false)}
                            >
                                {elapsed} ago
                            </TimeWrapper>
                            {timeTooltipOpen && ReactDOM.createPortal(
                                <TimeTooltip
                                    style={{
                                        top: timeTooltipPosition.top,
                                        left: timeTooltipPosition.left,
                                        transform: 'translate(-50%, -100%)'
                                    }}
                                >
                                    {formatTimeStamp(post.timestamp)}
                                </TimeTooltip>,
                                document.body
                            )}
                            {post && post.tag ? (
                                <>
                                    <MetaSeparator>·</MetaSeparator>
                                    <TagBadge $tag={post.tag}>{post.tag}</TagBadge>
                                </>
                            ) : null}
                            {post && post.feed_type === 'home' && post.feed_bucket && post.feed_bucket !== 'guest' && (
                                <>
                                    <MetaSeparator>·</MetaSeparator>
                                    <FeedReasonWrapper
                                        ref={feedReasonRef}
                                        onMouseEnter={() => {
                                            if (post.feed_debug && feedReasonRef.current) {
                                                const rect = feedReasonRef.current.getBoundingClientRect();
                                                setFeedTooltipPosition({
                                                    top: rect.bottom + 8,
                                                    left: Math.max(10, rect.left)
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
                                            {post.feed_bucket === 'discovery' && 'discover'}
                                            {post.feed_bucket === 'popular' && 'popular'}
                                            {post.feed_bucket === 'discussion' && 'discussion'}
                                            {post.feed_bucket === 'second_chance' && '2nd chance'}
                                        </FeedReasonInline>
                                    </FeedReasonWrapper>
                                    {feedTooltipOpen && post.feed_debug && ReactDOM.createPortal(
                                        <FeedDebugTooltip
                                            style={{ top: feedTooltipPosition.top, left: feedTooltipPosition.left }}
                                            onMouseEnter={() => setFeedTooltipOpen(true)}
                                            onMouseLeave={() => setFeedTooltipOpen(false)}
                                        >
                                            {/* Show formula and score for magic2/3 */}
                                            {post.feed_debug.score !== undefined && (
                                                <>
                                                    <FeedDebugRow style={{ marginBottom: '0.3rem' }}>
                                                        <FeedDebugValue style={{ fontFamily: 'monospace', fontSize: '0.8em', opacity: 0.7 }}>
                                                            {post.feed_debug.P !== undefined
                                                                ? '(S + V + U + P) × R'
                                                                : '(S + V + U) × R'}
                                                        </FeedDebugValue>
                                                    </FeedDebugRow>
                                                    <FeedDebugRow style={{ marginBottom: '0.5rem', paddingBottom: '0.5rem', borderBottom: '1px solid #444' }}>
                                                        <FeedDebugLabel style={{ fontWeight: 'bold' }}>Score:</FeedDebugLabel>
                                                        <FeedDebugValue style={{ fontSize: '1.1em' }}>{post.feed_debug.score?.toFixed(4) || '0'}</FeedDebugValue>
                                                    </FeedDebugRow>
                                                </>
                                            )}
                                            {/* Old magic formula */}
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
                                                <FeedDebugValue>{post.feed_debug.V?.toFixed(3) || '0.000'} [{post.feed_debug.points ?? 0} pts]</FeedDebugValue>
                                            </FeedDebugRow>
                                            {/* magic2/3: U for unique commenters */}
                                            {post.feed_debug.U !== undefined && (
                                                <FeedDebugRow>
                                                    <FeedDebugLabel>U (unique commenters):</FeedDebugLabel>
                                                    <FeedDebugValue>{post.feed_debug.U?.toFixed(3) || '0.000'} [{post.feed_debug.unique_commenters ?? 0}]</FeedDebugValue>
                                                </FeedDebugRow>
                                            )}
                                            {/* magic3: P for preference boost */}
                                            {post.feed_debug.P !== undefined && (
                                                <FeedDebugRow>
                                                    <FeedDebugLabel>P (your prefs):</FeedDebugLabel>
                                                    <FeedDebugValue>{post.feed_debug.P?.toFixed(3) || '0.000'} [t={post.feed_debug.t_pref ?? 0}+a={post.feed_debug.a_pref ?? 0}]</FeedDebugValue>
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
                                            {/* Only show Prefs row for old magic (magic2/3 show it inline with P) */}
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
                                    {!isOwnPost && isAdmin && (
                                        <MenuItem onClick={(e) => { e.stopPropagation(); handleDeletePost(); }} data-danger="true">🛡️ Admin delete</MenuItem>
                                    )}
                                    {!isOwnPost && (
                                        <>
                                            <MenuItem onClick={(e) => { e.stopPropagation(); isFollowingAuthor ? handleUnfollowUser() : handleFollowUser(); }}>
                                                {isFollowingAuthor ? 'Unfollow user' : 'Follow user'}
                                            </MenuItem>
                                            <MenuItem onClick={(e) => { e.stopPropagation(); handleDonate(); }}>Donate to user</MenuItem>
                                            <MenuItem onClick={(e) => { e.stopPropagation(); handleBlockUser(); }} data-danger="true">Block user</MenuItem>
                                            <MenuItem onClick={(e) => { e.stopPropagation(); handleBlockPost(); }} data-danger="true">Block post</MenuItem>
                                        </>
                                    )}
                                    <MenuItem onClick={(e) => { e.stopPropagation(); isSubscribedToTopic ? handleUnfollowTopic() : handleFollowTopic(); }}>
                                        {isSubscribedToTopic ? 'Unfollow topic' : 'Follow topic'}
                                    </MenuItem>
                                </MenuDropdown>,
                                document.body
                            )}
                        </MenuContainer>
                    </MetaInfoRow>
                    {post && post.feed_type === 'home' && post.feed_bucket && (
                        <FeedReasonLine>
                            {post.feed_bucket === 'following' && (post.feed_debug?.reason || 'Following')}
                            {post.feed_bucket === 'similar' && (post.feed_debug?.reason || 'Similar taste match')}
                            {post.feed_bucket === 'liked' && (post.feed_debug?.reason || 'Liked topic/author')}
                            {post.feed_bucket === 'discovery' && (post.feed_debug?.reason || 'Discovery')}
                            {post.feed_bucket === 'popular' && (post.feed_debug?.reason || 'Popular post')}
                            {post.feed_bucket === 'discussion' && (post.feed_debug?.reason || 'Active discussion')}
                            {post.feed_bucket === 'second_chance' && (post.feed_debug?.reason || 'Second chance')}
                        </FeedReasonLine>
                    )}
                    <HideOnMobileTitle style={compactTitleStyle}>
                        {title}
                    </HideOnMobileTitle>
                    <MetaRow style={compactMetaRowStyle}>
                        <VoteInline>
                            <VoteSection inline state={state} post={post} updatePost={updatePost} />
                            <MetaSeparatorAction>•</MetaSeparatorAction>
                        </VoteInline>
                        <Link to={`/view_post?post_id=${targetPostId}`} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
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
                            <span>✓</span>
                            link copied to clipboard
                        </ShareSuccessMessage>
                    )}
                    {confirmDelete && (
                        <BlockConfirmMessage>
                            <span>⚠ Confirm delete post? This action cannot be undone.</span>
                            <ConfirmButtons>
                                <Button variant="warning" size="sm" onClick={confirmDeletePostAction} disabled={isDeleting}>
                                    Delete
                                </Button>
                                <Button variant="ghost" size="sm" onClick={cancelDeletePost}>Cancel</Button>
                            </ConfirmButtons>
                        </BlockConfirmMessage>
                    )}
                    {showContent && post.content && (
                        <InlineTeaserMedia url={sanitizeUrlForLink(extractFirstUrl(post.content) || post.content)} />
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
        prevPost.comment_count === nextPost.comment_count &&
        prevPost.title === nextPost.title &&
        prevPost.content === nextPost.content &&
        prevPost.deleted === nextPost.deleted &&
        prevProps.state?.username === nextProps.state?.username &&
        prevProps.state?.publicKey === nextProps.state?.publicKey
    );
});


