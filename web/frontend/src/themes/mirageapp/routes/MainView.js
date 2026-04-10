import { Helmet } from "react-helmet-async";
import { getThemeFamily } from "../../../registry/theme";
import Button from "../components/Button.js";
import MobileHeader from "../components/MobileHeader.js";
import QuestHeroCard from "../components/QuestHeroCard.js";
import styled, { useTheme } from "styled-components";
import { Link } from "react-router-dom";
import Storage from "../../../utils/Storage";
import { isSubscribed, subscribe, unsubscribe, invalidateCache as invalidateTopicsCache } from "../../../utils/Subscriptions";
import { ContentGrid, ModernPostFeed, StyledError, OLDREDDIT_SHELL_INSET_X } from "../Layout";
import { useMain } from "../../../logic/useMain";
import { requireThemeColor } from "../../../utils/themeColor";

// Invite-only hero — flat, left-aligned (classic old.reddit density, not a marketing card)
const InviteOnlyHero = styled.div`
    margin-top: 0.35rem;
    background: transparent;
    border: none;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    padding: 0.35rem ${OLDREDDIT_SHELL_INSET_X} 0.45rem;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    text-align: left;
    gap: 0.3rem;
    width: 100%;
    box-sizing: border-box;
`;
const InviteOnlyHeroTitle = styled.h1`
    font-size: 0.8rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
    margin: 0;
    line-height: 1.25;
    text-transform: none;
`;
const InviteOnlyHeroSubtitle = styled.div`
    font-size: 0.6rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.link};
`;
const InviteOnlyHeroDescription = styled.p`
    font-size: 0.65rem;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.45;
    margin: 0;
    max-width: none;
`;
const InviteOnlyHeroStats = styled.div`
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem;
    font-size: 0.6rem;
    color: ${({ theme }) => theme.colors.subtleText};
`;
const InviteOnlyHeroStat = styled.span`
    font-weight: 600;
    color: ${({ theme }) => theme.colors.subtleText};

    strong {
        color: ${({ theme }) => theme.colors.text};
        font-weight: 700;
    }
`;
const InviteOnlyHeroLinks = styled.div`
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.6rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.subtleText};

    a {
        color: ${({ theme }) => theme.colors.link};
        text-decoration: underline;
        font-weight: 600;
    }
`;
const InviteOnlyHeroSep = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
`;
const InviteOnlyHeroButtons = styled.div`
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    margin-top: 0.2rem;
`;

// Mobile header branding for home/following feeds

// Invite-only banner - permanent, non-dismissable (matches HomeFeedInfoCard style)
const InviteOnlyBanner = styled.div`
    background: ${({
    theme
}) => theme.name === 'light' ? 'linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(99, 102, 241, 0.1) 100%)' : 'linear-gradient(135deg, rgba(59, 130, 246, 0.2) 0%, rgba(99, 102, 241, 0.2) 100%)'};
    border: 2px solid ${({
    theme
}) => theme.name === 'light' ? 'rgba(59, 130, 246, 0.5)' : 'rgba(96, 165, 250, 0.6)'};
    border-radius: ${({
    $size
}) => $size === 'compact' ? '8px' : '10px'};
    padding: ${({
    $size
}) => $size === 'compact' ? '0.4rem 0.6rem' : '0.6rem 0.9rem'};
    display: flex;
    flex-direction: column;
    gap: ${({
    $size
}) => $size === 'compact' ? '0.25rem' : '0.35rem'};
    box-shadow: ${({
    theme
}) => theme.name === 'light' ? '0 0 12px rgba(59, 130, 246, 0.2)' : '0 0 15px rgba(96, 165, 250, 0.25)'};

    @media (max-width: 1000px) {
        border-radius: ${({
    $size
}) => $size === 'compact' ? '6px' : '8px'};
        padding: ${({
    $size
}) => $size === 'compact' ? '0.35rem 0.5rem' : '0.5rem 0.75rem'};
    }

    @media (max-width: 768px) {
        border-radius: 6px;
        padding: 0.4rem 0.6rem;
    }
`;
const InviteBannerContentWrapper = styled.div`
    display: flex;
    align-items: center;
    gap: 1rem;
    flex: 1;

    @media (max-width: 768px) {
        flex-direction: column;
        align-items: stretch;
        gap: 0.75rem;
    }
`;
const InviteBannerTextContent = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    flex: 1;
    min-width: 0;
    padding-right: 3rem;

    @media (max-width: 768px) {
        padding-right: 0;
    }
`;
const InviteBannerButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.35rem;
    padding: 0.45rem 0.9rem;
    font-size: 0.7rem;
    font-weight: 600;
    font-family: inherit;
    color: #FFFFFF;
    background: linear-gradient(135deg, #FF8C00 0%, #FF5722 100%);
    border: none;
    border-radius: 6px;
    cursor: pointer;
    white-space: nowrap;
    transition: transform 0.15s ease;
    box-shadow: 0 2px 8px rgba(255, 140, 0, 0.4);
    flex-shrink: 0;

    &:hover {
        transform: translateY(-1px);
    }

    &:active {
        transform: translateY(0);
    }

    &:disabled {
        background: linear-gradient(135deg, #666 0%, #555 100%);
        box-shadow: none;
        cursor: not-allowed;
        opacity: 0.7;
    }

    @media (max-width: 1000px) {
        padding: 0.4rem 0.75rem;
        font-size: 0.6rem;
    }

    @media (max-width: 768px) {
        width: 100%;
        padding: 0.5rem 1rem;
        font-size: 0.65rem;
    }
`;
const InviteBannerCount = styled.span`
    font-size: 0.6rem;
    color: rgba(255, 255, 255, 0.8);
    font-weight: 500;

    @media (max-width: 1000px) {
        font-size: 0.5rem;
    }
`;

// Collapse button for hero cards
const CollapseButton = styled.button`
    background: transparent;
    border: none;
    color: ${({
    theme
}) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.65rem;
    font-weight: 600;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: 12px;
    transition: all 0.2s ease;
    display: flex;
    align-items: center;
    gap: 4px;

    &:hover {
        color: ${({
    theme
}) => requireThemeColor(theme, 'text')};
        background: ${({
    theme
}) => theme.name === 'light' ? 'rgba(0, 0, 0, 0.05)' : 'rgba(255, 255, 255, 0.05)'};
    }
`;

// Invite Code Modal
const InviteModalOverlay = styled.div`
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: 1rem;
`;
const InviteModalContent = styled.div`
    background: ${({
    theme
}) => theme.colors.panel};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: 16px;
    padding: 1.5rem;
    max-width: 420px;
    width: 100%;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);

    @media (max-width: 768px) {
        padding: 1.25rem;
        border-radius: 12px;
    }
`;
const InviteModalHeader = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1rem;
`;
const InviteModalTitle = styled.h2`
    font-size: 1.1rem;
    font-weight: 600;
    color: ${({
    theme
}) => theme.colors.text};
    margin: 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;
const InviteModalClose = styled.button`
    background: none;
    border: none;
    color: ${({
    theme
}) => theme.colors.subtleText};
    cursor: pointer;
    font-size: 1.5rem;
    line-height: 1;
    padding: 0;
    &:hover {
        color: ${({
    theme
}) => theme.colors.text};
    }
`;
const InviteCodeDisplay = styled.div`
    background: linear-gradient(135deg, rgba(102, 126, 234, 0.15) 0%, rgba(118, 75, 162, 0.15) 100%);
    border: 2px dashed rgba(102, 126, 234, 0.4);
    border-radius: 12px;
    padding: 1.25rem;
    text-align: center;
    margin-bottom: 1rem;
`;
const InviteCodeText = styled.div`
    font-size: 1.75rem;
    font-weight: 700;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    color: ${({
    theme
}) => theme.colors.text};
    letter-spacing: 0.1em;
    margin-bottom: 0.5rem;

    @media (max-width: 768px) {
        font-size: 1.5rem;
    }
`;
const InviteCodeSubtext = styled.div`
    font-size: 0.75rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
`;
const InviteShareButtons = styled.div`
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.5rem;
    margin-bottom: 1rem;

    @media (max-width: 400px) {
        grid-template-columns: 1fr;
    }
`;
const InviteShareButton = styled.button`
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    padding: 0.6rem 0.75rem;
    font-size: 0.75rem;
    font-weight: 500;
    font-family: inherit;
    color: ${({
    theme
}) => theme.colors.text};
    background: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.15s ease;

    &:hover {
        background: ${({
    theme
}) => theme.colors.accent};
        border-color: ${({
    theme
}) => theme.colors.text};
    }
`;
const InviteCopyButton = styled(InviteShareButton)`
    grid-column: 1 / -1;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border: none;
    color: #FFFFFF;
    font-weight: 600;

    &:hover {
        background: linear-gradient(135deg, #5a6fd6 0%, #6a4190 100%);
        border: none;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        transform: translateY(-1px);
    }

    &:active {
        transform: translateY(0);
    }
`;
const InviteNativeShareButton = styled(InviteCopyButton)`
    background: linear-gradient(135deg, #10B981 0%, #059669 100%);

    &:hover {
        background: linear-gradient(135deg, #0d9668 0%, #047857 100%);
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
    }
`;
const InviteDesktopShareButtons = styled.div`
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.5rem;
    margin-bottom: 1rem;

    @media (max-width: 600px) {
        display: none;
    }
`;
const InviteRemainingText = styled.div`
    text-align: center;
    font-size: 0.7rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
`;
const InviteNoCodesText = styled.div`
    text-align: center;
    padding: 1rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.85rem;
`;

// Home feed info card for logged-in users
const HomeFeedInfoCard = styled.div`
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.06) 0%, rgba(139, 92, 246, 0.06) 100%);
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: ${({
    $size
}) => $size === 'compact' ? '8px' : '10px'};
    padding: ${({
    $size
}) => $size === 'compact' ? '0.4rem 0.6rem' : '0.6rem 0.9rem'};
    display: flex;
    flex-direction: column;
    gap: ${({
    $size
}) => $size === 'compact' ? '0.25rem' : '0.35rem'};

    @media (max-width: 1000px) {
        border-radius: ${({
    $size
}) => $size === 'compact' ? '6px' : '8px'};
        padding: ${({
    $size
}) => $size === 'compact' ? '0.35rem 0.5rem' : '0.5rem 0.75rem'};
    }

    @media (max-width: 768px) {
        border-radius: 6px;
        padding: 0.4rem 0.6rem;
    }
`;

// NSFW welcome hero - shown once to logged-in users on home feed
const NsfwWelcomeHero = styled.div`
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.08) 0%, rgba(220, 38, 127, 0.08) 100%);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;

    @media (max-width: 1000px) {
        border-radius: 10px;
        padding: 1rem 1.25rem;
    }

    @media (max-width: 768px) {
        border-radius: 8px;
        padding: 0.85rem 1rem;
    }
`;
const NsfwHeroTitle = styled.div`
    font-size: 1rem;
    font-weight: 700;
    color: ${({
    theme
}) => theme.colors.text};
    display: flex;
    align-items: center;
    gap: 0.5rem;
    line-height: 1.2;

    @media (max-width: 768px) {
        font-size: 0.9rem;
    }
`;
const NsfwHeroEmoji = styled.span`
    font-size: 1.1rem;
    line-height: 1;
`;
const NsfwHeroDescription = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.8rem;
    line-height: 1.6;

    @media (max-width: 768px) {
        font-size: 0.75rem;
    }

    strong {
        color: ${({
    theme
}) => theme.colors.text};
        font-weight: 600;
    }
`;
const NsfwHeroButtons = styled.div`
    display: flex;
    gap: 0.75rem;
    margin-top: 0.25rem;
    flex-wrap: wrap;

    @media (max-width: 768px) {
        gap: 0.5rem;
    }
`;
const NsfwHeroButton = styled.button`
    padding: 0.5rem 1.25rem;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    border: none;

    @media (max-width: 768px) {
        padding: 0.45rem 1rem;
        font-size: 0.8rem;
        flex: 1;
        min-width: 80px;
    }

    ${({
    $variant
}) => $variant === 'yes' ? `
        background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
        color: #fff;
        &:hover {
            background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
            transform: translateY(-1px);
        }
    ` : `
        background: rgba(100, 116, 139, 0.2);
        color: #94a3b8;
        border: 1px solid rgba(100, 116, 139, 0.3);
        &:hover {
            background: rgba(100, 116, 139, 0.3);
            color: #cbd5e1;
        }
    `}
`;
const NsfwHeroNote = styled.div`
    color: ${({
    theme
}) => theme.colors.mutedText};
    font-size: 0.7rem;
    font-style: italic;
    margin-top: 0.25rem;

    a {
        color: ${({
    theme
}) => theme.colors.link};
        text-decoration: none;
        &:hover {
            text-decoration: underline;
        }
    }
`;

// Android app banner - shown once to Android mobile users until dismissed
const AndroidAppHero = styled.div`
    background: linear-gradient(135deg, rgba(52, 168, 83, 0.08) 0%, rgba(66, 133, 244, 0.08) 100%);
    border: 1px solid rgba(66, 133, 244, 0.3);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;

    @media (max-width: 1000px) {
        border-radius: 10px;
        padding: 1rem 1.25rem;
    }

    @media (max-width: 768px) {
        border-radius: 8px;
        padding: 0.85rem 1rem;
    }
`;
const AndroidHeroTitle = styled.div`
    font-size: 1rem;
    font-weight: 700;
    color: ${({
    theme
}) => theme.colors.text};
    display: flex;
    align-items: center;
    gap: 0.5rem;
    line-height: 1.2;

    @media (max-width: 768px) {
        font-size: 0.9rem;
    }
`;
const AndroidHeroEmoji = styled.span`
    font-size: 1.1rem;
    line-height: 1;
`;
const AndroidHeroDescription = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.8rem;
    line-height: 1.6;

    @media (max-width: 768px) {
        font-size: 0.75rem;
    }
`;
const AndroidHeroButtons = styled.div`
    display: flex;
    gap: 0.75rem;
    margin-top: 0.25rem;
    flex-wrap: wrap;

    @media (max-width: 768px) {
        gap: 0.5rem;
    }
`;
const AndroidHeroButton = styled.a`
    padding: 0.5rem 1.25rem;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    border: none;
    text-decoration: none;
    text-align: center;
    background: linear-gradient(135deg, #34a853 0%, #2d9249 100%);
    color: #fff;

    &:hover {
        background: linear-gradient(135deg, #2d9249 0%, #267a3d 100%);
        transform: translateY(-1px);
    }

    @media (max-width: 768px) {
        padding: 0.45rem 1rem;
        font-size: 0.8rem;
        flex: 1;
        min-width: 80px;
    }
`;
const AndroidHeroDismiss = styled.button`
    padding: 0.5rem 1.25rem;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    background: rgba(100, 116, 139, 0.2);
    color: #94a3b8;
    border: 1px solid rgba(100, 116, 139, 0.3);

    &:hover {
        background: rgba(100, 116, 139, 0.3);
        color: #cbd5e1;
    }

    @media (max-width: 768px) {
        padding: 0.45rem 1rem;
        font-size: 0.8rem;
        flex: 1;
        min-width: 80px;
    }
`;
const IPhoneAppHero = styled.div`
    background: linear-gradient(135deg, rgba(0, 122, 255, 0.08) 0%, rgba(88, 86, 214, 0.08) 100%);
    border: 1px solid rgba(0, 122, 255, 0.3);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;

    @media (max-width: 1000px) {
        border-radius: 10px;
        padding: 1rem 1.25rem;
    }

    @media (max-width: 768px) {
        border-radius: 8px;
        padding: 0.85rem 1rem;
    }
`;
const IPhoneHeroButton = styled.a`
    padding: 0.5rem 1.25rem;
    border-radius: 8px;
    font-size: 0.85rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    border: none;
    text-decoration: none;
    text-align: center;
    background: linear-gradient(135deg, #007AFF 0%, #5856D6 100%);
    color: #fff;

    &:hover {
        background: linear-gradient(135deg, #0066D6 0%, #4B49B8 100%);
        transform: translateY(-1px);
    }

    @media (max-width: 768px) {
        padding: 0.45rem 1rem;
        font-size: 0.8rem;
        flex: 1;
        min-width: 80px;
    }
`;
const HomeFeedInfoTitle = styled.div`
    font-size: 0.7rem;
    font-weight: 600;
    color: ${({
    theme
}) => theme.colors.text};
    display: flex;
    align-items: center;
    gap: 0.4rem;
    line-height: 1;

    @media (max-width: 1000px) {
        font-size: 0.6rem;
    }
`;
const HomeFeedHeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
`;
const HomeFeedModeInline = styled.div`
    display: flex;
    align-items: center;
    gap: 0.45rem;
    font-size: 0.7rem;
`;
const HomeFeedInfoEmoji = styled.span`
    font-size: 0.85rem;
    line-height: 1;
    display: inline-block;
    transform: translateY(-1px);

    @media (max-width: 1000px) {
        font-size: 0.75rem;
    }
`;
const HomeFeedInfoDescription = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.65rem;
    line-height: 1.5;

    @media (max-width: 1000px) {
        font-size: 0.55rem;
    }

    strong {
        color: ${({
    theme
}) => theme.colors.text};
        font-weight: 600;
    }
`;
const HomeFeedModeSelect = styled.select`
    font-size: 0.65rem;
    padding: 0.15rem 0.35rem;
    border-radius: 6px;
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    background: ${({
    theme
}) => theme.colors.inputBackground};
    color: ${({
    theme
}) => theme.colors.text};
    outline: none;
    box-shadow: ${({
    theme
}) => theme.name === 'light' ? '0 1px 2px rgba(0,0,0,0.08)' : 'none'};
`;

// Post header card shown on single post view
const PostHeaderCard = styled.div`
    margin-top: 0.5rem;
    margin-left: 1rem;
    margin-right: 1rem;
    background-color: ${({
    theme
}) => requireThemeColor(theme, 'card')};
    border: 1px solid ${({
    theme
}) => requireThemeColor(theme, 'cardBorder')};
    color: ${({
    theme
}) => theme.colors.text};
    border-radius: 6px;
    padding: 0.2rem 0.6rem 0.4rem 0.6rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    @media (max-width: 1000px) {
        margin-left: 0.25rem;
        margin-right: 0.25rem;
        padding: 0.3rem 0.6rem;
    }
`;
const PostHeaderText = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.6rem;
    line-height: 1.5;
`;
const TopicLinkInHeader = styled(Link)`
    color: ${({
    theme
}) => theme.colors.link};
    text-decoration: none;
    font-weight: 700;
    &:hover {
        color: ${({
    theme
}) => theme.colors.linkHover};
        text-decoration: underline;
        text-decoration-color: ${({
    theme
}) => theme.colors.link};
    }
`;
const PostHeaderTitle = styled.div`
    color: ${({
    theme
}) => theme.colors.text};
    font-size: 0.9rem;
    font-weight: bold;
`;
const HeaderInlineLink = styled.a`
    background: none;
    border: none;
    padding: 0;
    margin: 0;
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-weight: 700;
    font-size: 0.6rem;
    font-family: inherit;
    cursor: pointer;
    text-decoration: none;
    &:hover {
        color: ${({
    theme
}) => theme.colors.text};
        text-decoration: none;
    }
`;
/* inline subscribe/unsubscribe will be rendered via FilterBar rightAction */

// Removed old topics bar styled components (unused)

/** Fills feed column with panel color so body bg does not show between stacked sections */
const MainFeedPanel = styled.div`
    width: 100%;
    background: ${({ theme }) => theme.colors.panel};
`;

/** Sidebar floats right inside the ListContainer, below the toolbar.
 *  Feed row borders extend full-width underneath it. */
const SidebarFloat = styled.aside`
    float: right;
    width: 18rem;
    margin: 0.35rem ${OLDREDDIT_SHELL_INSET_X} 0.5rem 0.75rem;
    position: relative;
    z-index: 5;

    @media (max-width: 1000px) {
        display: none;
    }
`;

/** Single bordered sidebar widget containing quests + submit */
const SidebarBox = styled.div`
    box-sizing: border-box;
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
    display: flex;
    flex-direction: column;
`;

/** Sidebar action link — same visual weight as the quest header strip */
const SidebarAction = styled(Link)`
    display: block;
    box-sizing: border-box;
    width: 100%;
    padding: 0.3rem 0.5rem;
    font-size: 0.6rem;
    font-weight: 700;
    font-family: inherit;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    text-decoration: none;
    text-align: left;
    color: ${({ theme }) => theme.colors.text};
    background: ${({ theme }) => theme.colors.panelAlt};
    border: none;
    border-top: 1px solid ${({ theme }) => theme.colors.border};
    cursor: pointer;

    &:hover {
        color: ${({ theme }) => theme.colors.link};
    }
`;

const LoadingMoreIndicator = styled.div`
    width: 100%;
    margin-top: 0.5rem;
    padding: 0.5rem 0;
    text-align: center;
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.8rem;
    font-style: italic;
`;
const LoadMoreButton = styled.button`
    display: block;
    width: 100%;
    padding: 0.75rem 0;
    margin-top: 0.25rem;
    border: none;
    background: transparent;
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.85rem;
    cursor: pointer;
    text-align: center;
    &:hover {
        color: ${({
    theme
}) => theme.colors.text};
    }
`;

/**
 * LoadingCard — flat list row, same surface as ListFeedView (no inset card / no body bg gaps)
 */
const LoadingCard = styled.div`
    margin-left: calc(-1 * ${OLDREDDIT_SHELL_INSET_X});
    margin-right: calc(-1 * ${OLDREDDIT_SHELL_INSET_X});
    width: calc(100% + 2 * ${OLDREDDIT_SHELL_INSET_X});
    max-width: none;
    padding: ${({
    $size
}) => ($size === 'compact' ? '0.75rem' : '1rem')} ${OLDREDDIT_SHELL_INSET_X};
    min-height: 5rem;
    background-color: ${({
    theme
}) => theme.colors.panel};
    border: none;
    border-radius: 0;
    border-bottom: 1px solid ${({
    theme
}) => theme.colors.border};
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: ${({
    $size
}) => $size === 'compact' ? '0.5rem' : '0.65rem'};
    box-sizing: border-box;
`;
const LoadingSpinner = styled.div`
    width: 24px;
    height: 24px;
    border: 3px solid ${({
    theme
}) => theme.colors.border};
    border-top: 3px solid ${({
    theme
}) => theme.colors.subtleText};
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;
const LoadingText = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.85rem;
    font-weight: 500;
`;

// TopicsBar removed (unused)

const InlineLink = styled(Link)`
    color: ${({
    theme
}) => theme.colors.link};
    text-decoration: none;
    font-weight: 700;
    &:hover {
        color: ${({
    theme
}) => theme.colors.linkHover};
        text-decoration: underline;
        text-decoration-color: ${({
    theme
}) => theme.colors.link};
    }
`;

// Topic header card (for topic pages) - unified with HomeFeedInfoCard
const TopicHeroCard = styled.div`
    margin-top: 1rem;
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.06) 0%, rgba(139, 92, 246, 0.06) 100%);
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: 10px;
    padding: 0.6rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;

    @media (max-width: 1000px) {
        border-radius: 8px;
        padding: 0.5rem 0.75rem;
    }

    @media (max-width: 768px) {
        border-radius: 6px;
        padding: 0.4rem 0.6rem;
        margin-top: 0.5rem;
    }
`;
const TopicHeroTitle = styled.div`
    font-size: 0.7rem;
    font-weight: 600;
    color: ${({
    theme
}) => theme.colors.text};
    display: flex;
    align-items: center;
    gap: 0.4rem;
    line-height: 1;

    @media (max-width: 1000px) {
        font-size: 0.6rem;
    }
`;
const TopicHeroHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
`;
const TopicHeroDescription = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.65rem;
    line-height: 1.5;

    @media (max-width: 1000px) {
        font-size: 0.55rem;
        line-height: 1.4;
    }

    strong {
        color: ${({
    theme
}) => theme.colors.text};
        font-weight: 600;
    }
`;

/**
 * EmptyHomeCard — flat full-width strip, aligned with list feed surface
 */
const EmptyHomeCard = styled.div`
    margin-left: calc(-1 * ${OLDREDDIT_SHELL_INSET_X});
    margin-right: calc(-1 * ${OLDREDDIT_SHELL_INSET_X});
    width: calc(100% + 2 * ${OLDREDDIT_SHELL_INSET_X});
    max-width: none;
    padding: 1.25rem ${OLDREDDIT_SHELL_INSET_X};
    background-color: ${({
    theme
}) => theme.colors.panel};
    border: none;
    border-radius: 0;
    border-bottom: 1px solid ${({
    theme
}) => theme.colors.border};
    text-align: center;
    box-sizing: border-box;
`;
const EmptyHomeTitle = styled.div`
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    color: ${({
    theme
}) => theme.colors.text};
`;
const EmptyHomeBody = styled.div`
    font-size: 0.8rem;
    line-height: 1.5;
    color: ${({
    theme
}) => theme.colors.subtleText};
`;
const EmptyHomeMessage = () => <EmptyHomeCard role="region" aria-label="Empty home feed">
    <EmptyHomeTitle>Your home feed is empty</EmptyHomeTitle>
    <EmptyHomeBody>
        Follow a few topics to personalize your feed. If this node is new, be the first to post. Browse <InlineLink to="/topics">topics</InlineLink> to get started.
    </EmptyHomeBody>
</EmptyHomeCard>;

// Session storage key helpers for feed state preservation (keyed by topic)

const MainView = ({
    state,
    setPosts,
    updatePost,
    setTopic,
    routeTopic
}) => {
    const theme = useTheme();
    const showHero = theme.caps.showHeroCards;
    const {
        urlTopic,
        currentTopicRef,
        error,
        stableOrder,
        setStableOrder,
        isLoading,
        hasMorePosts,
        homeSortMode,
        setHomeSortMode,
        oldRedditSort,
        handleOldRedditSortChange,
        cardSize,
        handleCardSizeChange,
        hideDownvotedPosts,
        hidingPostsSet,
        flashingPostsSet,
        isLoadingMore,
        isMobile,
        isTopicBlockedLocal,
        location,
        viewerAddress,
        followedTopicsSet,
        setFollowedTopicsSet,
        topicFollowHover,
        setTopicFollowHover,
        isTopicPending,
        formatTopicStatus,
        forceHardRefreshRef,
        dismissAndroidBanner,
        dismissIPhoneBanner,
        showNsfwHero,
        isLoggedIn,
        inviteCodesEnabled,
        questsEnabled,
        showAndroidBanner,
        showIPhoneBanner,
        inviteModalOpen,
        setInviteModalOpen,
        inviteCodeCopied,
        welcomeStats,
        welcomeStatsStale,
        inviteBannerCollapsed,
        questCardCollapsed,
        toggleInviteBanner,
        toggleQuestCard,
        nextAvailableCode,
        availableCodeCount,
        handleOpenInviteModal,
        handleCopyInviteCode,
        handleNativeShare,
        canNativeShare,
        getShareUrl,
        getShareText,
        handleNsfwChoice,
        bottomSentinelRef,
        loadMore
    } = useMain({
        state,
        setPosts,
        updatePost,
        setTopic,
        routeTopic
    });
    if (error) {
        return <StyledError>{error}</StyledError>;
    }
    const isPostView = location.pathname.startsWith('/p/');
    let header = null;
    if (isPostView) {
        const pid = (() => {
            if (location.pathname.startsWith('/p/')) {
                const raw = location.pathname.slice(3);
                return raw ? decodeURIComponent(raw) : null;
            }
            return null;
        })();
        const p = pid ? state.posts[pid] : null;
        if (p) {
            const topicKey = String(p.topic || '').trim().toLowerCase();
            const isTopicFollowing = topicKey && (followedTopicsSet.has(topicKey) || isSubscribed(viewerAddress || 'guest', p.topic));
            const isTopicInProgress = isTopicPending(topicKey);
            header = <PostHeaderCard role="region" aria-label="Post context">
                <PostHeaderText>
                    Posted in{' '}
                    <TopicLinkInHeader to={`/t/${p.topic}`} title={`View #${p.topic}`}>
                        #{p.topic}
                    </TopicLinkInHeader>{' '}
                    (
                    <HeaderInlineLink href="#" onClick={async e => {
                        e.preventDefault();
                        const key = topicKey;
                        if (!key) return;
                        if (isTopicPending(key)) return;
                        try {
                            const isCurrentlyFollowing = key && (followedTopicsSet.has(key) || isSubscribed(viewerAddress || 'guest', p.topic));
                            if (isCurrentlyFollowing) {
                                await unsubscribe(viewerAddress || 'guest', p.topic);
                                setFollowedTopicsSet(prev => {
                                    const next = new Set(prev);
                                    next.delete(key);
                                    return next;
                                });
                            } else {
                                await subscribe(viewerAddress || 'guest', p.topic);
                                setFollowedTopicsSet(prev => new Set([...prev, key]));
                            }
                            invalidateTopicsCache();
                            setStableOrder(s => s.slice());
                        } catch (_) {/* noop */ }
                    }}>
                        {isTopicInProgress ? formatTopicStatus(topicKey) : isTopicFollowing ? 'unfollow' : 'follow'}
                    </HeaderInlineLink>
                    )
                </PostHeaderText>
                <PostHeaderTitle>{p.title}</PostHeaderTitle>
            </PostHeaderCard>;
        }
    }
    const showPosts = () => {
        // Compute display state
        const displayTopic = currentTopicRef.current || urlTopic;
        const routeTopicLower = urlTopic ? String(urlTopic).toLowerCase() : '';
        const topicKeyLower = routeTopicLower || (displayTopic ? String(displayTopic).toLowerCase() : '');
        const isCurrentTopic = routeTopicLower && routeTopicLower !== 'home' && routeTopicLower !== 'all' && routeTopicLower !== 'following';
        const isTopicFollowing = isCurrentTopic && (followedTopicsSet.has(routeTopicLower) || isSubscribed(viewerAddress || 'guest', urlTopic));
        const isTopicInProgress = isCurrentTopic && isTopicPending(routeTopicLower);

        // Determine what content to show
        let showEmptyHome = false;
        let showNoPostsAvailable = false;
        let showLoadingPosts = false;
        let orderedPosts = [];

        // Show loading when switching to a different topic
        const isTopicSwitching = isLoading && displayTopic !== urlTopic;
        // Force loading overlay even when posts exist (e.g., mode toggle / hard refresh)
        const isHardRefreshLoading = isLoading && forceHardRefreshRef.current;

        // Check loading states
        if (isHardRefreshLoading) {
            showLoadingPosts = true;
        } else if (isTopicSwitching) {
            // Switching topics - show loading immediately
            showLoadingPosts = true;
        } else if (!state.posts || Object.keys(state.posts).length === 0) {
            if (isLoading) {
                showLoadingPosts = true;
            } else if (displayTopic === 'home') {
                showEmptyHome = true;
            } else {
                showNoPostsAvailable = true;
            }
        } else if (isLoading && stableOrder.length === 0) {
            showLoadingPosts = true;
        } else {
            // Convert the posts object to an array once
            const postsArray = Object.values(state.posts || {});

            // Only include top-level posts (exclude comments or partial objects, deleted, and optimistically blocked topics)
            const isTopLevelPost = p => {
                if (!p || p.deleted) return false;
                if (p.hidden_client) return false;
                const hasTitle = typeof p.title === 'string' && p.title.trim().length > 0;
                const hasTopic = typeof p.topic === 'string' && p.topic.trim().length > 0;
                const topicVal = String(p.topic || '').trim().toLowerCase();
                const isReserved = ['all', 'home', 'following'].includes(topicVal);
                if (isTopicBlockedLocal(topicVal)) return false;
                return hasTitle && hasTopic && !isReserved;
            };
            const topLevelPosts = postsArray.filter(isTopLevelPost);
            const filteredPosts = displayTopic === "all" || displayTopic === "home" || displayTopic === "following" ? topLevelPosts : topLevelPosts.filter(post => String(post.topic || '').toLowerCase() === String(displayTopic || '').toLowerCase());
            if (filteredPosts.length === 0 && !isLoading) {
                if (displayTopic === 'home') {
                    showEmptyHome = true;
                } else {
                    showNoPostsAvailable = true;
                }
            } else {
                // Build a stable ordered list of posts
                const postsById = {};
                for (const p of filteredPosts) {
                    if (p && p.post_id && !p.deleted && !p.hidden_client) {
                        postsById[p.post_id] = p;
                    }
                }
                if (stableOrder.length > 0) {
                    orderedPosts = stableOrder.map(id => postsById[id]).filter(Boolean);
                } else {
                    orderedPosts = filteredPosts.filter(p => p && !p.deleted);
                }

                // Hide posts the viewer downvoted (Home only, client-side)
                if (displayTopic === 'home' && hideDownvotedPosts) {
                    orderedPosts = orderedPosts.filter(p => {
                        const postKey = String(p?.post_id || '').toLowerCase();
                        // If post is animating out, keep it in the list for now
                        if (hidingPostsSet.has(postKey)) return true;
                        // Prefer in-memory/state direction; backend provides user_vote on fetch.
                        const dir = Number(p?.direction ?? p?.user_vote ?? p?.my_vote ?? p?.myVote ?? p?.userVote ?? 0);
                        if (Number.isFinite(dir) && dir < 0) return false;
                        return true;
                    });
                }
            }
        }

        // Full-width main column + shell header (no left sidebar; old Reddit style)
        const pageTitle = urlTopic === 'home' ? 'Home' : urlTopic === 'following' ? 'Following' : urlTopic === 'all' ? 'All Posts' : `#${urlTopic}`;
        const noPostsMessage = urlTopic === 'following'
            ? 'No posts available. Follow people or topics to populate this feed.'
            : 'No posts available';
        return <ContentGrid>
            <Helmet>
                <title>{pageTitle} | Mirage</title>
            </Helmet>
            <div>
                {header}
                <MainFeedPanel>
                    <ModernPostFeed>
                        <MobileHeader />

                        {isLoggedIn && isCurrentTopic && showHero && <TopicHeroCard>
                            <TopicHeroHeader>
                                <TopicHeroTitle>#{urlTopic}</TopicHeroTitle>
                                <HomeFeedModeInline>
                                    <HomeFeedModeSelect value={homeSortMode} onChange={e => {
                                        const mode = e.target.value;
                                        setHomeSortMode(mode);
                                        Storage.save('home_sort_mode', mode);
                                    }}>
                                        <option value="magic">Magic</option>
                                        <option value="newest">Newest</option>
                                    </HomeFeedModeSelect>
                                    <HomeFeedModeSelect value={cardSize} onChange={e => handleCardSizeChange(e.target.value)}>
                                        <option value="large">Large</option>
                                        {!isMobile && <option value="compact">Compact</option>}
                                        <option value="media">Media</option>
                                    </HomeFeedModeSelect>
                                    <Button variant={isTopicFollowing && topicFollowHover ? 'primaryDanger' : isTopicFollowing ? 'subtle' : 'primary'} size="xs" minWidth="5.5rem" onMouseEnter={() => setTopicFollowHover(true)} onMouseLeave={() => setTopicFollowHover(false)} disabled={isTopicInProgress} onClick={async () => {
                                        const topicName = urlTopic;
                                        if (!topicName) return;
                                        const key = topicKeyLower;
                                        if (!key) return;
                                        if (isTopicPending(key)) return;
                                        try {
                                            if (isTopicFollowing) {
                                                await unsubscribe(viewerAddress || 'guest', topicName);
                                                setFollowedTopicsSet(prev => {
                                                    const next = new Set(prev);
                                                    next.delete(key);
                                                    return next;
                                                });
                                            } else {
                                                await subscribe(viewerAddress || 'guest', topicName);
                                                setFollowedTopicsSet(prev => new Set([...prev, key]));
                                            }
                                            invalidateTopicsCache();
                                        } catch (_) {/* noop */ }
                                    }}>
                                        {isTopicInProgress ? formatTopicStatus(topicKeyLower) : isTopicFollowing ? topicFollowHover ? 'Unfollow' : 'Following' : 'Follow'}
                                    </Button>
                                </HomeFeedModeInline>
                            </TopicHeroHeader>
                            <TopicHeroDescription>
                                Topic feed for #{urlTopic}. Follow this community to stay up to date with the latest posts, discussions, and updates from people actively contributing to this topic.
                            </TopicHeroDescription>
                        </TopicHeroCard>}

                        {/* Invite-only banner - shown only when invite codes are enabled on this node */}
                        {isLoggedIn && showHero && inviteCodesEnabled && (urlTopic === 'home' || urlTopic === 'following') && <InviteOnlyBanner $size={cardSize} role="region" aria-label="Invite-only announcement">
                            <HomeFeedHeaderRow>
                                <HomeFeedInfoTitle>
                                    <HomeFeedInfoEmoji>✨</HomeFeedInfoEmoji> Invite Codes
                                    {inviteBannerCollapsed && <span style={{
                                        fontWeight: 'normal'
                                    }}>
                                        {' '}{availableCodeCount === 0 ? '— None available' : `— ${availableCodeCount} ${availableCodeCount === 1 ? 'code' : 'codes'} left`}
                                    </span>}
                                </HomeFeedInfoTitle>
                                <CollapseButton onClick={toggleInviteBanner}>
                                    {inviteBannerCollapsed ? 'Show' : 'Hide'}
                                </CollapseButton>
                            </HomeFeedHeaderRow>
                            {!inviteBannerCollapsed && <InviteBannerContentWrapper>
                                <InviteBannerTextContent>
                                    <HomeFeedInfoDescription>
                                        Mirage is now invite-only — because great conversations require great people!
                                        {' '}{availableCodeCount > 0 ? "But don't fret, we've given you some invite codes for your friends. Use them wisely." : "Unfortunately, you're out of invite codes. But don't worry, we might drop some more soon. Stay tuned!"}
                                    </HomeFeedInfoDescription>
                                </InviteBannerTextContent>
                                <InviteBannerButton onClick={handleOpenInviteModal} disabled={availableCodeCount === 0}>
                                    {availableCodeCount > 0 ? <>Share Invite Code <InviteBannerCount>({availableCodeCount} left)</InviteBannerCount></> : 'No Codes Left'}
                                </InviteBannerButton>
                            </InviteBannerContentWrapper>}
                        </InviteOnlyBanner>}

                        {/* Android app banner - shown once for Android users until dismissed */}
                        {showHero && showAndroidBanner && <AndroidAppHero role="region" aria-label="Android app available">
                            <AndroidHeroTitle>
                                <AndroidHeroEmoji>📱</AndroidHeroEmoji> Mirage is available on Android
                            </AndroidHeroTitle>
                            <AndroidHeroDescription>
                                Get the native Android app for a faster, smoother experience with push notifications and offline support.
                            </AndroidHeroDescription>
                            <AndroidHeroButtons>
                                <AndroidHeroButton href="https://play.google.com/store/apps/details?id=talk.mirage.mobile" target="_blank" rel="noopener noreferrer">
                                    Get the app
                                </AndroidHeroButton>
                                <AndroidHeroDismiss onClick={dismissAndroidBanner}>
                                    No thanks
                                </AndroidHeroDismiss>
                            </AndroidHeroButtons>
                        </AndroidAppHero>}

                        {showHero && showIPhoneBanner && <IPhoneAppHero role="region" aria-label="iPhone app available">
                            <AndroidHeroTitle>
                                <AndroidHeroEmoji>📱</AndroidHeroEmoji> Mirage is available on iPhone
                            </AndroidHeroTitle>
                            <AndroidHeroDescription>
                                Get the native iOS app for a faster, smoother experience with push notifications and offline support.
                            </AndroidHeroDescription>
                            <AndroidHeroButtons>
                                <IPhoneHeroButton href="https://apps.apple.com/us/app/mirage-speak-your-mind/id6757619038" target="_blank" rel="noopener noreferrer">
                                    Get the app
                                </IPhoneHeroButton>
                                <AndroidHeroDismiss onClick={dismissIPhoneBanner}>
                                    No thanks
                                </AndroidHeroDismiss>
                            </AndroidHeroButtons>
                        </IPhoneAppHero>}

                        {/* NSFW welcome hero - shown once for logged-in users until dismissed */}
                        {isLoggedIn && showHero && urlTopic === 'home' && showNsfwHero && <NsfwWelcomeHero role="region" aria-label="Content preferences">
                            <NsfwHeroTitle>
                                <NsfwHeroEmoji>🔞</NsfwHeroEmoji> Allow Adult Content?
                            </NsfwHeroTitle>
                            <NsfwHeroDescription>
                                Mirage is uncensored and may include <strong>adult content</strong>, <strong>violence</strong>, and other NSFW material. Would you like to see this content in your feed?
                            </NsfwHeroDescription>
                            <NsfwHeroButtons>
                                <NsfwHeroButton $variant="yes" onClick={() => handleNsfwChoice(true)}>
                                    Yes, show everything
                                </NsfwHeroButton>
                                <NsfwHeroButton $variant="no" onClick={() => handleNsfwChoice(false)}>
                                    No, keep it clean
                                </NsfwHeroButton>
                            </NsfwHeroButtons>
                            <NsfwHeroNote>
                                You can change this anytime in <Link to="/settings" style={{
                                    color: 'inherit',
                                    textDecoration: 'underline'
                                }}>Settings</Link>.
                            </NsfwHeroNote>
                        </NsfwWelcomeHero>}

                        {/* Home feed info card - permanent for logged-in users (hidden while NSFW hero is shown) */}
                        {isLoggedIn && urlTopic === 'home' && !showNsfwHero && showHero && <HomeFeedInfoCard $size={cardSize} role="region" aria-label="Home feed information">
                            <HomeFeedHeaderRow>
                                <HomeFeedInfoTitle>
                                    <HomeFeedInfoEmoji>🏠</HomeFeedInfoEmoji> Your Home Feed
                                </HomeFeedInfoTitle>
                                <HomeFeedModeInline>
                                    <HomeFeedModeSelect value={cardSize} onChange={e => handleCardSizeChange(e.target.value)}>
                                        <option value="large">Large</option>
                                        {!isMobile && <option value="compact">Compact</option>}
                                        <option value="media">Media</option>
                                    </HomeFeedModeSelect>
                                </HomeFeedModeInline>
                            </HomeFeedHeaderRow>
                            <HomeFeedInfoDescription>
                                Your followed topics plus fresh content to discover. <strong>The more you vote, the more your feed reflects your preferences.</strong>
                            </HomeFeedInfoDescription>
                        </HomeFeedInfoCard>}

                        {/* Following feed info card - permanent for logged-in users */}
                        {isLoggedIn && urlTopic === 'following' && showHero && <HomeFeedInfoCard $size={cardSize} role="region" aria-label="Following feed information">
                            <HomeFeedHeaderRow>
                                <HomeFeedInfoTitle>
                                    <HomeFeedInfoEmoji>👥</HomeFeedInfoEmoji> Your Following Feed
                                </HomeFeedInfoTitle>
                                <HomeFeedModeInline>
                                    <HomeFeedModeSelect value={cardSize} onChange={e => handleCardSizeChange(e.target.value)}>
                                        <option value="large">Large</option>
                                        {!isMobile && <option value="compact">Compact</option>}
                                        <option value="media">Media</option>
                                    </HomeFeedModeSelect>
                                </HomeFeedModeInline>
                            </HomeFeedHeaderRow>
                            <HomeFeedInfoDescription>
                                <strong>Only posts from topics and people you follow.</strong> A focused view of your communities without discovery content.
                            </HomeFeedInfoDescription>
                        </HomeFeedInfoCard>}

                        {/* Loading state - only show to logged-in users */}
                        {isLoggedIn && showLoadingPosts && <LoadingCard $size={cardSize}>
                            <LoadingSpinner />
                            <LoadingText>Loading posts...</LoadingText>
                        </LoadingCard>}

                        {/* Empty home feed - only show to logged-in users */}
                        {isLoggedIn && showEmptyHome && <EmptyHomeMessage />}

                        {/* No posts available - only show to logged-in users */}
                        {isLoggedIn && showNoPostsAvailable && <LoadingCard $size={cardSize}>
                            <LoadingText>{noPostsMessage}</LoadingText>
                        </LoadingCard>}

                        {/* Invite-only hero - shown to logged-out users on all feeds */}
                        {!isLoggedIn && <InviteOnlyHero role="region" aria-label="Welcome to Mirage">
                            <InviteOnlyHeroTitle>Welcome to Mirage<sup style={{
                                fontSize: '0.55em',
                                marginLeft: '0.25em',
                                verticalAlign: 'super',
                                opacity: 0.75
                            }}>BETA</sup></InviteOnlyHeroTitle>
                            <InviteOnlyHeroSubtitle>Currently in Private Beta — Invite Only</InviteOnlyHeroSubtitle>
                            <InviteOnlyHeroDescription>
                                Mirage is a fully decentralized social network built on its own blockchain, designed to be 100% censorship resistant. Your posts, votes, and identity live on-chain — no central authority can silence you.
                            </InviteOnlyHeroDescription>
                            {welcomeStats && welcomeStats.userCount > 0 && <InviteOnlyHeroStats>
                                <InviteOnlyHeroStat>
                                    <strong>Users:</strong> {welcomeStatsStale ? '~' : ''}{welcomeStats.userCount.toLocaleString()}
                                </InviteOnlyHeroStat>
                                <InviteOnlyHeroStat>
                                    <strong>Active (24h):</strong> {welcomeStatsStale ? '~' : ''}{welcomeStats.active24h.toLocaleString()}
                                </InviteOnlyHeroStat>
                                <InviteOnlyHeroStat>
                                    <strong>Posts (24h):</strong> {welcomeStatsStale ? '~' : ''}{(welcomeStats.posts24h + welcomeStats.comments24h).toLocaleString()}
                                </InviteOnlyHeroStat>
                            </InviteOnlyHeroStats>}
                            <InviteOnlyHeroLinks>
                                <a href="https://www.youtube.com/watch?v=TOvP32ihQ0M" target="_blank" rel="noopener noreferrer"><strong>Watch Introduction (YouTube)</strong></a>
                                <InviteOnlyHeroSep aria-hidden="true">·</InviteOnlyHeroSep>
                                <a href="https://mirage.foundation" target="_blank" rel="noopener noreferrer">Learn More</a>
                            </InviteOnlyHeroLinks>
                            <InviteOnlyHeroButtons>
                                <Button to="/signup" size="xs">
                                    Create account
                                </Button>
                                <Button to="/login" variant="ghost" size="xs">
                                    Sign in
                                </Button>
                            </InviteOnlyHeroButtons>
                        </InviteOnlyHero>}

                        {/* Posts grid - only show to logged-in users */}
                        {isLoggedIn && !showLoadingPosts && !showEmptyHome && !showNoPostsAvailable && orderedPosts.length > 0 && (() => {
                            const family = getThemeFamily(state?.themeId);
                            const FeedComponent = family.Feed;
                            const visiblePosts = orderedPosts.filter(p => {
                                const hasValidTitle = p && typeof p.title === 'string' && p.title.trim().length > 0;
                                const hasValidTopic = p && typeof p.topic === 'string' && p.topic.trim().length > 0;
                                return hasValidTitle && hasValidTopic && !p.deleted;
                            });
                            const isTopicFeed = urlTopic && urlTopic !== 'home' && urlTopic !== 'following';
                            const createPostLink = isTopicFeed
                                ? `/create_post?topic=${encodeURIComponent(urlTopic)}`
                                : '/create_post';
                            const sidebarContent = (
                                <SidebarFloat>
                                    <SidebarBox>
                                        {questsEnabled && <QuestHeroCard collapsed={questCardCollapsed} onToggleCollapse={toggleQuestCard} />}
                                        <SidebarAction to={createPostLink}>Create a new post</SidebarAction>
                                    </SidebarBox>
                                </SidebarFloat>
                            );
                            return <FeedComponent posts={visiblePosts} state={state} updatePost={updatePost} hidingPostsSet={hidingPostsSet} flashingPostsSet={flashingPostsSet} viewerAddress={viewerAddress} sortMode={oldRedditSort} onSortChange={handleOldRedditSortChange} showSortTabs={urlTopic === 'home' || urlTopic === 'following'} feedNavTopic={urlTopic} sidebar={sidebarContent} />;
                        })()}

                        {isLoggedIn && isLoadingMore && !showEmptyHome && !showNoPostsAvailable && <LoadingMoreIndicator>Loading more...</LoadingMoreIndicator>}
                        {isLoggedIn && <div ref={bottomSentinelRef} style={{
                            width: '100%',
                            minHeight: '1px'
                        }}>
                            {hasMorePosts && !isLoadingMore && !isLoading && !showEmptyHome && !showNoPostsAvailable && <LoadMoreButton type="button" onClick={loadMore}>
                                Load more
                            </LoadMoreButton>}
                        </div>}
                    </ModernPostFeed>
                </MainFeedPanel>
            </div>

            {/* Invite Code Modal */}
            {inviteModalOpen && <InviteModalOverlay onClick={() => setInviteModalOpen(false)}>
                <InviteModalContent onClick={e => e.stopPropagation()}>
                    <InviteModalHeader>
                        <InviteModalTitle>
                            <span role="img" aria-label="sparkles">✨</span> Share Your Invite Code
                        </InviteModalTitle>
                        <InviteModalClose onClick={() => setInviteModalOpen(false)}>&times;</InviteModalClose>
                    </InviteModalHeader>

                    {nextAvailableCode ? <>
                        <InviteCodeDisplay>
                            <InviteCodeText>{nextAvailableCode.code}</InviteCodeText>
                            <InviteCodeSubtext>Share this code with a friend to invite them</InviteCodeSubtext>
                        </InviteCodeDisplay>

                        <InviteShareButtons>
                            <InviteCopyButton onClick={handleCopyInviteCode}>
                                {inviteCodeCopied ? '✓ Copied!' : 'Copy Invite Link'}
                            </InviteCopyButton>
                            {canNativeShare && <InviteNativeShareButton onClick={handleNativeShare}>
                                <span role="img" aria-label="share">📤</span> Share via...
                            </InviteNativeShareButton>}
                        </InviteShareButtons>
                        <InviteDesktopShareButtons>
                            <InviteShareButton as="a" href={`https://twitter.com/intent/tweet?text=${encodeURIComponent(getShareText())}&url=${encodeURIComponent(getShareUrl())}`} target="_blank" rel="noopener noreferrer">
                                <span role="img" aria-label="X">𝕏</span> Twitter/X
                            </InviteShareButton>
                            <InviteShareButton as="a" href={`https://t.me/share/url?url=${encodeURIComponent(getShareUrl())}&text=${encodeURIComponent(getShareText())}`} target="_blank" rel="noopener noreferrer">
                                <span role="img" aria-label="telegram">📨</span> Telegram
                            </InviteShareButton>
                            <InviteShareButton as="a" href={`https://wa.me/?text=${encodeURIComponent(getShareText() + ' ' + getShareUrl())}`} target="_blank" rel="noopener noreferrer">
                                <span role="img" aria-label="whatsapp">💬</span> WhatsApp
                            </InviteShareButton>
                            <InviteShareButton as="a" href={`mailto:?subject=${encodeURIComponent('Join me on Mirage!')}&body=${encodeURIComponent(getShareText() + '\n\n' + getShareUrl())}`}>
                                <span role="img" aria-label="email">📧</span> Email
                            </InviteShareButton>
                        </InviteDesktopShareButtons>

                        <InviteRemainingText>
                            You have {availableCodeCount} invite{availableCodeCount !== 1 ? 's' : ''} remaining
                        </InviteRemainingText>
                    </> : <InviteNoCodesText>
                        You don't have any invite codes available. Check back later!
                    </InviteNoCodesText>}
                </InviteModalContent>
            </InviteModalOverlay>}
        </ContentGrid>;
    };
    return showPosts();
};
export default MainView;