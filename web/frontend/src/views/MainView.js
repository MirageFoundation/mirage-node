import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Helmet } from 'react-helmet-async';
import { getThemeFamily } from "../styled/theme";
import Sidebar from "../components/Sidebar";
import TopBar from "../components/TopBar";
import Button from "../components/Button";
import MobileHeader from "../components/MobileHeader";
import QuestHeroCard from "../components/QuestHeroCard";
import styled, { useTheme } from "styled-components";
import { Link, useLocation, useParams, useNavigationType } from 'react-router-dom';
import Storage from '../utils/Storage';
import { getAllowedTagsParam } from '../utils/ContentTags';
import Api from '../lib/api';
import { isSubscribed, subscribe, unsubscribe, fetchFollowedTopics, invalidateCache as invalidateTopicsCache } from '../utils/Subscriptions';
import { fetchFollowedUsers } from '../utils/FollowUsers';
import { usePendingFollows } from '../utils/useFollowState';
import { darkColors as fallbackDarkColors } from "../styled/colors/dark";
import { lightColors as fallbackLightColors } from "../styled/colors/light";
import {
    ContentGrid,
    ModernPostFeed,
    StyledError,
} from "../styled/Layout";

const pickThemeColor = (theme, key) => {
    if (theme.colors[key]) return theme.colors[key];
    const isLight = theme.name === 'light';
    return (isLight ? fallbackLightColors : fallbackDarkColors)[key];
};

// Welcome card that appears for first-time visitors on the front page
// eslint-disable-next-line no-unused-vars
const WelcomeCard = styled.div`
    margin-top: 1rem;
    background-color: rgba(251, 191, 36, 0.1);
    border: 1px solid #f59e0b;
    color: #f59e0b;
    border-radius: 16px;
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);

    @media (max-width: 1000px) {
        border-radius: 12px;
        padding: 1rem;
    }

    @media (max-width: 768px) {
        border-radius: 8px;
        padding: 0.75rem;
    }
`;

// eslint-disable-next-line no-unused-vars
const WelcomeDescription = styled.div`
    color: #f59e0b;
    font-size: 0.75rem;
    line-height: 1.5;
    @media (max-width: 1000px) {
        font-size: 0.55rem;
    }
`;

// eslint-disable-next-line no-unused-vars
const WelcomeFooter = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
`;

// eslint-disable-next-line no-unused-vars
const WelcomeText = styled.a`
    color: #f59e0b;
    text-decoration: none;
    font-weight: 600;
    font-size: 0.8rem;
    flex: 1 1 auto;
    &:hover {
        color: #d97706;
        text-decoration: underline;
        text-decoration-color: #f59e0b;
    }
`;

// Invite-only hero for logged-out users on the front page
const InviteOnlyHero = styled.div`
    margin-top: 1rem;
    background: ${({ theme }) => theme.name === 'light'
        ? 'linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%)'
        : 'linear-gradient(135deg, rgba(102, 126, 234, 0.15) 0%, rgba(118, 75, 162, 0.15) 100%)'};
    border: 1px solid ${({ theme }) => theme.name === 'light'
        ? 'rgba(102, 126, 234, 0.3)'
        : 'rgba(102, 126, 234, 0.35)'};
    border-radius: 16px;
    padding: 2rem 2.5rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 1rem;

    @media (max-width: 1000px) {
        border-radius: 12px;
        padding: 1.5rem 1.25rem;
    }

    @media (max-width: 768px) {
        border-radius: 10px;
        padding: 1.25rem 1rem;
        gap: 0.75rem;
    }
`;

const InviteOnlyHeroEmoji = styled.span`
    font-size: 2.5rem;
    line-height: 1;
    display: block;
    margin-bottom: 0.25rem;

    @media (max-width: 768px) {
        font-size: 2rem;
    }
`;

const InviteOnlyHeroTitle = styled.h1`
    font-size: 1.5rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
    margin: 0;
    line-height: 1.2;

    @media (max-width: 1000px) {
        font-size: 1.25rem;
    }

    @media (max-width: 768px) {
        font-size: 1.1rem;
    }
`;

const InviteOnlyHeroSubtitle = styled.div`
    font-size: 0.95rem;
    font-weight: 600;
    color: #667eea;
    margin-top: -0.25rem;

    @media (max-width: 1000px) {
        font-size: 0.8rem;
    }

    @media (max-width: 768px) {
        font-size: 0.7rem;
    }
`;

const InviteOnlyHeroDescription = styled.p`
    font-size: 0.85rem;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.6;
    margin: 0;
    max-width: 500px;

    @media (max-width: 1000px) {
        font-size: 0.7rem;
    }

    @media (max-width: 768px) {
        font-size: 0.65rem;
        line-height: 1.5;
    }
`;

const InviteOnlyHeroButtons = styled.div`
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
    margin-top: 0.5rem;

    @media (max-width: 768px) {
        grid-template-columns: 1fr;
        width: 100%;
        max-width: 280px;
        gap: 0.5rem;
    }
`;

// Stats display for welcome hero (logged-out users)
const WelcomeStatsGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.75rem;
    margin: 0.5rem 0;
    padding: 0.75rem 0;
    border-top: 1px solid ${({ theme }) => theme.name === 'light'
        ? 'rgba(102, 126, 234, 0.2)'
        : 'rgba(102, 126, 234, 0.25)'};
    border-bottom: 1px solid ${({ theme }) => theme.name === 'light'
        ? 'rgba(102, 126, 234, 0.2)'
        : 'rgba(102, 126, 234, 0.25)'};
    width: 100%;

    @media (max-width: 768px) {
        gap: 0.5rem;
    }
`;

const WelcomeStatItem = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    gap: 0.15rem;
    flex: 1;
    min-width: 0;
`;

const WelcomeStatValue = styled.div`
    font-size: 1.25rem;
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
    font-variant-numeric: tabular-nums;

    @media (max-width: 1000px) {
        font-size: 1.1rem;
    }

    @media (max-width: 768px) {
        font-size: 1rem;
    }
`;

const WelcomeStatLabel = styled.div`
    font-size: 0.65rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
    text-transform: uppercase;
    letter-spacing: 0.03em;

    @media (max-width: 1000px) {
        font-size: 0.6rem;
    }

    @media (max-width: 768px) {
        font-size: 0.55rem;
    }
`;

// Mobile header branding for home/following feeds

// Invite-only banner - permanent, non-dismissable (matches HomeFeedInfoCard style)
const InviteOnlyBanner = styled.div`
    background: ${({ theme }) => theme.name === 'light'
        ? 'linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(99, 102, 241, 0.1) 100%)'
        : 'linear-gradient(135deg, rgba(59, 130, 246, 0.2) 0%, rgba(99, 102, 241, 0.2) 100%)'};
    border: 2px solid ${({ theme }) => theme.name === 'light'
        ? 'rgba(59, 130, 246, 0.5)'
        : 'rgba(96, 165, 250, 0.6)'};
    border-radius: ${({ $size }) => $size === 'compact' ? '8px' : '10px'};
    padding: ${({ $size }) => $size === 'compact' ? '0.4rem 0.6rem' : '0.6rem 0.9rem'};
    display: flex;
    flex-direction: column;
    gap: ${({ $size }) => $size === 'compact' ? '0.25rem' : '0.35rem'};
    box-shadow: ${({ theme }) => theme.name === 'light'
        ? '0 0 12px rgba(59, 130, 246, 0.2)'
        : '0 0 15px rgba(96, 165, 250, 0.25)'};

    @media (max-width: 1000px) {
        border-radius: ${({ $size }) => $size === 'compact' ? '6px' : '8px'};
        padding: ${({ $size }) => $size === 'compact' ? '0.35rem 0.5rem' : '0.5rem 0.75rem'};
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
    color: ${({ theme }) => pickThemeColor(theme, 'subtleText')};
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
        color: ${({ theme }) => pickThemeColor(theme, 'text')};
        background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0, 0, 0, 0.05)'
        : 'rgba(255, 255, 255, 0.05)'};
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
    background: ${({ theme }) => theme.colors.panel};
    border: 1px solid ${({ theme }) => theme.colors.border};
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
    color: ${({ theme }) => theme.colors.text};
    margin: 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

const InviteModalClose = styled.button`
    background: none;
    border: none;
    color: ${({ theme }) => theme.colors.subtleText};
    cursor: pointer;
    font-size: 1.5rem;
    line-height: 1;
    padding: 0;
    &:hover {
        color: ${({ theme }) => theme.colors.text};
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
    color: ${({ theme }) => theme.colors.text};
    letter-spacing: 0.1em;
    margin-bottom: 0.5rem;

    @media (max-width: 768px) {
        font-size: 1.5rem;
    }
`;

const InviteCodeSubtext = styled.div`
    font-size: 0.75rem;
    color: ${({ theme }) => theme.colors.subtleText};
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
    color: ${({ theme }) => theme.colors.text};
    background: ${({ theme }) => theme.colors.panelAlt};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.15s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.accent};
        border-color: ${({ theme }) => theme.colors.text};
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
    color: ${({ theme }) => theme.colors.subtleText};
`;

const InviteNoCodesText = styled.div`
    text-align: center;
    padding: 1rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.85rem;
`;

// Home feed info card for logged-in users
const HomeFeedInfoCard = styled.div`
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.06) 0%, rgba(139, 92, 246, 0.06) 100%);
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: ${({ $size }) => $size === 'compact' ? '8px' : '10px'};
    padding: ${({ $size }) => $size === 'compact' ? '0.4rem 0.6rem' : '0.6rem 0.9rem'};
    display: flex;
    flex-direction: column;
    gap: ${({ $size }) => $size === 'compact' ? '0.25rem' : '0.35rem'};

    @media (max-width: 1000px) {
        border-radius: ${({ $size }) => $size === 'compact' ? '6px' : '8px'};
        padding: ${({ $size }) => $size === 'compact' ? '0.35rem 0.5rem' : '0.5rem 0.75rem'};
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
    color: ${({ theme }) => theme.colors.text};
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
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.8rem;
    line-height: 1.6;

    @media (max-width: 768px) {
        font-size: 0.75rem;
    }

    strong {
        color: ${({ theme }) => theme.colors.text};
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

    ${({ $variant }) => $variant === 'yes' ? `
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
    color: ${({ theme }) => theme.colors.mutedText};
    font-size: 0.7rem;
    font-style: italic;
    margin-top: 0.25rem;

    a {
        color: ${({ theme }) => theme.colors.link};
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
    color: ${({ theme }) => theme.colors.text};
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
    color: ${({ theme }) => theme.colors.subtleText};
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
    color: ${({ theme }) => theme.colors.text};
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
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.65rem;
    line-height: 1.5;

    @media (max-width: 1000px) {
        font-size: 0.55rem;
    }

    strong {
        color: ${({ theme }) => theme.colors.text};
        font-weight: 600;
    }
`;

const HomeFeedModeSelect = styled.select`
    font-size: 0.65rem;
    padding: 0.15rem 0.35rem;
    border-radius: 6px;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) =>
        theme.colors.inputBackground  };
    color: ${({ theme }) => theme.colors.text };
    outline: none;
    box-shadow: ${({ theme }) => theme.name === 'light' ? '0 1px 2px rgba(0,0,0,0.08)' : 'none'};
`;

// Post header card shown on single post view
const PostHeaderCard = styled.div`
    margin-top: 0.5rem;
    margin-left: 1rem;
    margin-right: 1rem;
    background-color: ${({ theme }) => pickThemeColor(theme, 'card') || '#23272C'};
    border: 1px solid ${({ theme }) => pickThemeColor(theme, 'cardBorder') || '#333'};
    color: ${({ theme }) => theme.colors.text};
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
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    line-height: 1.5;
`;

const TopicLinkInHeader = styled(Link)`
    color: ${({ theme }) => theme.colors.link};
    text-decoration: none;
    font-weight: 700;
    &:hover {
        color: ${({ theme }) => theme.colors.linkHover};
        text-decoration: underline;
        text-decoration-color: ${({ theme }) => theme.colors.link};
    }
`;

const PostHeaderTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.9rem;
    font-weight: bold;
`;

const HeaderInlineLink = styled.a`
    background: none;
    border: none;
    padding: 0;
    margin: 0;
    color: ${({ theme }) => theme.colors.subtleText};
    font-weight: 700;
    font-size: 0.6rem;
    font-family: inherit;
    cursor: pointer;
    text-decoration: none;
    &:hover {
        color: ${({ theme }) => theme.colors.text};
        text-decoration: none;
    }
`;
/* inline subscribe/unsubscribe will be rendered via FilterBar rightAction */

// Removed old topics bar styled components (unused)

const LoadingMoreIndicator = styled.div`
    width: 100%;
    margin-top: 0.5rem;
    padding: 0.5rem 1rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.8rem;
    font-style: italic;
`;

const LoadMoreButton = styled.button`
    display: block;
    width: 100%;
    padding: 0.75rem 1rem;
    margin-top: 0.25rem;
    border: none;
    background: transparent;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.85rem;
    cursor: pointer;
    text-align: center;
    &:hover {
        color: ${({ theme }) => theme.colors.text};
    }
`;

/**
 * LoadingCard - Full-width loading/empty state card
 * 
 * No horizontal margins - parent ModernPostFeed provides padding.
 * This ensures same width as CardView cards.
 */
const LoadingCard = styled.div`
    margin: ${({ $size }) => $size === 'compact' ? '0.5rem 0 0 0' : '1rem 0 0 0'};
    padding: ${({ $size }) => $size === 'compact' ? '1rem 0.6rem' : '2rem 1rem'};
    background-color: ${({ theme }) => theme.colors.cardAlt };
    border: 1px solid ${({ theme }) => theme.colors.cardBorder };
    border-radius: ${({ $size }) => $size === 'compact' ? '8px' : '12px'};
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: ${({ $size }) => $size === 'compact' ? '0.5rem' : '0.75rem'};

    @media (max-width: 1000px) {
        padding: ${({ $size }) => $size === 'compact' ? '0.75rem 0.5rem' : '1.5rem 0.75rem'};
    }
`;

const LoadingSpinner = styled.div`
    width: 24px;
    height: 24px;
    border: 3px solid ${({ theme }) => theme.colors.border };
    border-top: 3px solid ${({ theme }) => theme.colors.subtleText};
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;

const LoadingText = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.85rem;
    font-weight: 500;
`;

// TopicsBar removed (unused)

const InlineLink = styled(Link)`
    color: ${({ theme }) => theme.colors.link};
    text-decoration: none;
    font-weight: 700;
    &:hover {
        color: ${({ theme }) => theme.colors.linkHover};
        text-decoration: underline;
        text-decoration-color: ${({ theme }) => theme.colors.link};
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
    color: ${({ theme }) => theme.colors.text};
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
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.65rem;
    line-height: 1.5;

    @media (max-width: 1000px) {
        font-size: 0.55rem;
        line-height: 1.4;
    }

    strong {
        color: ${({ theme }) => theme.colors.text};
        font-weight: 600;
    }
`;


/**
 * EmptyHomeCard - Empty state for home feed
 * 
 * No horizontal margins - parent ModernPostFeed provides padding.
 * This ensures same width as CardView cards.
 */
const EmptyHomeCard = styled.div`
    margin: 1rem 0 0 0;
    padding: 1.5rem 1.25rem;
    background-color: ${({ theme }) => theme.colors.cardAlt };
    border: 1px solid ${({ theme }) => theme.colors.cardBorder };
    border-radius: 12px;
    text-align: center;

    @media (max-width: 1000px) {
        padding: 1.25rem 1rem;
    }
`;

const EmptyHomeTitle = styled.div`
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 0.5rem;
    color: ${({ theme }) => theme.colors.text};
`;

const EmptyHomeBody = styled.div`
    font-size: 0.8rem;
    line-height: 1.5;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const EmptyHomeMessage = () => (
    <EmptyHomeCard role="region" aria-label="Empty home feed">
        <EmptyHomeTitle>Your home feed is empty</EmptyHomeTitle>
        <EmptyHomeBody>
            Follow a few topics to personalize your feed. If this node is new, be the first to post. Browse <InlineLink to="/topics">topics</InlineLink> to get started.
        </EmptyHomeBody>
    </EmptyHomeCard>
);

// Session storage key helpers for feed state preservation (keyed by topic)
const getFeedKey = (topic, suffix) => `feed_${suffix}_${topic}`;

// In-memory (per-tab) feed cache to avoid sessionStorage quota issues on long feeds.
// This cache survives SPA navigation (feed -> post -> back), but not a full page refresh.
const getFeedMemCache = () => {
    try {
        if (typeof window === 'undefined') return null;
        if (!window.__MIRAGE_FEED_MEM_CACHE__) {
            window.__MIRAGE_FEED_MEM_CACHE__ = {};
        }
        return window.__MIRAGE_FEED_MEM_CACHE__;
    } catch (_) {
        return null;
    }
};

const getMemKey = (topic) => {
    try {
        return encodeURIComponent(String(topic || '').trim());
    } catch (_) {
        return String(topic || '');
    }
};

const readMemFeedState = (topic) => {
    try {
        const cache = getFeedMemCache();
        if (!cache) return null;
        const key = getMemKey(topic);
        const v = cache[key];
        if (!v || typeof v !== 'object') return null;
        return v;
    } catch (_) {
        return null;
    }
};

const writeMemFeedState = (topic, patch) => {
    try {
        const cache = getFeedMemCache();
        if (!cache) return;
        const key = getMemKey(topic);
        const prev = (cache[key] && typeof cache[key] === 'object') ? cache[key] : {};
        cache[key] = {
            ...prev,
            ...patch,
            at: Date.now(),
        };
    } catch (_) { }
};

const readSavedOrder = (topic) => {
    try {
        const savedOrder = sessionStorage.getItem(getFeedKey(topic, 'order'));
        if (!savedOrder) return null;
        const parsed = JSON.parse(savedOrder);
        return Array.isArray(parsed) ? parsed : null;
    } catch (_) {
        return null;
    }
};

const isTopLevelPostForFeed = (p) => {
    if (!p) return false;
    const hasTitle = typeof p.title === 'string' && p.title.trim().length > 0;
    const hasTopic = typeof p.topic === 'string' && String(p.topic).trim().length > 0;
    if (!hasTitle || !hasTopic) return false;
    const topicVal = String(p.topic || '').trim().toLowerCase();
    const isReserved = ['all', 'home', 'following'].includes(topicVal);
    return !isReserved;
};

const hasAnyCachedPostsForTopic = (topic, postsObj) => {
    try {
        if (!postsObj || typeof postsObj !== 'object') return false;
        const ids = Object.keys(postsObj);
        if (ids.length === 0) return false;
        const t = String(topic || '').trim();
        const tLower = t.toLowerCase();

        const values = Object.values(postsObj);

        // "all", "home", "following" all render top-level posts across topics.
        if (tLower === 'all' || tLower === 'home' || tLower === 'following') {
            return values.some(isTopLevelPostForFeed);
        }

        return values.some((p) => {
            if (!isTopLevelPostForFeed(p)) return false;
            return String(p.topic || '').trim().toLowerCase() === tLower;
        });
    } catch (_) {
        return false;
    }
};

const checkRestoreFeedIntent = (topic) => {
    try {
        const raw = sessionStorage.getItem('mirage_restore_feed');
        if (!raw) return false;
        const parsed = JSON.parse(raw);
        const intended = String(parsed?.topic || '').trim();
        const at = Number(parsed?.at || 0);
        if (!intended || !Number.isFinite(at) || at <= 0) return false;
        const ageMs = Date.now() - at;
        if (ageMs < 0 || ageMs > 15000) return false;
        return intended === String(topic || '');
    } catch (_) {
        return false;
    }
};

const clearRestoreFeedIntent = () => {
    try { sessionStorage.removeItem('mirage_restore_feed'); } catch (_) { }
};

// Check if we navigated here from a post view via browser back button
// This flag is set when clicking a post link from the feed
const checkCameFromViewPost = () => {
    try {
        const raw = sessionStorage.getItem('mirage_came_from_feed');
        if (!raw) return false;
        const parsed = JSON.parse(raw);
        const at = Number(parsed?.at || 0);
        if (!Number.isFinite(at) || at <= 0) return false;
        // Valid for 30 minutes (enough time for reading a post with comments)
        const ageMs = Date.now() - at;
        if (ageMs < 0 || ageMs > 1800000) return false;
        return true;
    } catch (_) {
        return false;
    }
};

const clearCameFromFeedFlag = () => {
    try { sessionStorage.removeItem('mirage_came_from_feed'); } catch (_) { }
};

// Track if we've seen the first SPA navigation (to distinguish page refresh from back nav).
// On true page refresh (F5), this starts as false and the first POP is the refresh.
// After ANY navigation within the SPA, we set this to true, so subsequent POPs are back navigations.
let __hasHadFirstSpaNavigation = false;

// Check if this is the very first page load (before any SPA navigation happened)
const isInitialPageLoad = () => {
    return !__hasHadFirstSpaNavigation;
};

// Mark that we've had at least one SPA navigation
const markSpaNavigationOccurred = () => {
    __hasHadFirstSpaNavigation = true;
};

// Helper to detect back/forward navigation
// Returns true for POP navigations (back button, navigate(-1), browser back/forward)
// but NOT for the initial page load (where POP just means "loaded directly")
const getIsBackNavigation = (navigationType) => {
    if (navigationType !== 'POP') return false;
    // On the very first load, POP just means we landed here (not a back nav)
    if (isInitialPageLoad()) return false;
    return true;
};

// For scroll restoration, we want to restore on BOTH back navigation AND page refresh
const shouldRestoreScroll = (navigationType) => {
    return navigationType === 'POP';
};

const MainView = ({ state, setPosts, updatePost, setTopic, routeTopic }) => {
    const params = useParams();
    const urlTopic = routeTopic || params.topic || "home"; // Get the topic from URL or prop
    const navigationType = useNavigationType(); // 'POP' = back/forward, 'PUSH'/'REPLACE' = direct nav
    const isBackNavigation = getIsBackNavigation(navigationType);
    const theme = useTheme();
    const showHero = theme.caps.showHeroCards;
    const mapHomeSortMode = theme.caps.mapHomeSortMode;

    const currentTopicRef = useRef(urlTopic); // Track current topic to detect changes
    const restoreFeedIntentRef = useRef(checkRestoreFeedIntent(urlTopic));
    // For browser back button: only restore if we came from a post view that was opened from the feed
    const cameFromViewPostRef = useRef(isBackNavigation && checkCameFromViewPost());

    // If we are switching topics (and reusing component), we must invalidate any stale "restore" intents
    // that were calculated for the previous topic.
    if (currentTopicRef.current !== urlTopic) {
        try {
            restoreFeedIntentRef.current = false;
            cameFromViewPostRef.current = false;
        } catch (_) { }
    }

    const shouldAttemptRestore =
        isBackNavigation ||
        restoreFeedIntentRef.current === true ||
        cameFromViewPostRef.current === true;
    const shouldRestoreFeedState = shouldAttemptRestore;

    // Mark that we've navigated within the SPA (so subsequent POPs are back navigations)
    useEffect(() => {
        markSpaNavigationOccurred();
    }, []);

    // Clear the restore intent after we've consumed it (in effect to avoid StrictMode double-render issues)
    useEffect(() => {
        if (restoreFeedIntentRef.current) {
            clearRestoreFeedIntent();
        }
        if (cameFromViewPostRef.current) {
            clearCameFromFeedFlag();
        }
    }, []);

    const [error, setError] = useState(null);
    const [, setTopics] = useState([]); // Dynamically store unique topics (state is persisted but value unused)

    // Only restore from cache on back navigation (POP), not on direct nav (clicking links)
    const [stableOrder, setStableOrder] = useState(() => {
        if (!shouldRestoreFeedState) return [];
        try {
            const mem = readMemFeedState(urlTopic);
            const memOrder = mem && Array.isArray(mem.order) ? mem.order : null;
            if (memOrder && memOrder.length > 0) return memOrder;
        } catch (_) { }
        try {
            const savedOrder = sessionStorage.getItem(getFeedKey(urlTopic, 'order'));
            if (savedOrder) {
                return JSON.parse(savedOrder);
            }
        } catch (_) { }
        return [];
    });

    // Only skip loading on back navigation with cached state
    const [isLoading, setIsLoading] = useState(() => {
        if (!shouldRestoreFeedState) return true;
        try {
            const memOrder = readMemFeedState(urlTopic)?.order;
            const order = readSavedOrder(urlTopic) || (Array.isArray(memOrder) ? memOrder : null);
            if (order && order.length > 0 && state.posts && order.some((id) => state.posts[id])) return false;
            if (hasAnyCachedPostsForTopic(urlTopic, state.posts)) return false;
        } catch (_) { }
        return true;
    });

    // Only restore currentPage on back navigation
    const [currentPage, setCurrentPage] = useState(() => {
        if (!shouldRestoreFeedState) return 1;
        try {
            const memPage = Number(readMemFeedState(urlTopic)?.page || 0);
            if (Number.isFinite(memPage) && memPage > 0) return Math.floor(memPage);
        } catch (_) { }
        try {
            const savedPage = sessionStorage.getItem(getFeedKey(urlTopic, 'page'));
            if (savedPage) return parseInt(savedPage, 10) || 1;
        } catch (_) { }
        return 1;
    });

    // Only restore hasMorePosts on back navigation
    const [hasMorePosts, setHasMorePosts] = useState(() => {
        if (!shouldRestoreFeedState) return false;
        try {
            const memHasMore = readMemFeedState(urlTopic)?.hasMore;
            if (typeof memHasMore === 'boolean') return memHasMore;
        } catch (_) { }
        try {
            const savedHasMore = sessionStorage.getItem(getFeedKey(urlTopic, 'hasmore'));
            if (savedHasMore) return savedHasMore === 'true';
        } catch (_) { }
        return false;
    });
    const [homeSortMode, setHomeSortMode] = useState(() => {
        const defaultMode = 'magic';
        let mode = Storage.load('home_sort_mode', defaultMode);

        // Migrate deprecated/unknown modes to the new unified mode.
        // Magic is now the only algo mode.
        if (mode !== 'magic' && mode !== 'newest') {
            mode = defaultMode;
            Storage.save('home_sort_mode', mode);
        }

        return mode;
    });
    const [oldRedditSort, setOldRedditSort] = useState('best');

    const handleOldRedditSortChange = useCallback((mode) => {
        if (mode !== 'best' && mode !== 'new') return;
        console.debug('[OldReddit] sort.select', { mode });
        setOldRedditSort(mode);
    }, []);

    useEffect(() => {
        if (!mapHomeSortMode) return;
        const mapped = oldRedditSort === 'new' ? 'newest' : 'magic';
        if (homeSortMode !== mapped) {
            console.debug('[OldReddit] sort.map', { oldRedditSort, homeSortMode, mapped });
            setHomeSortMode(mapped);
            Storage.save('home_sort_mode', mapped);
        }
    }, [mapHomeSortMode, oldRedditSort, homeSortMode]);
    const [cardSize, setCardSize] = useState(() => {
        try {
            return Storage.load('card_size', 'compact');
        } catch (_) {
            return 'compact';
        }
    });
    const handleCardSizeChange = (newSize) => {
        setCardSize(newSize);
        Storage.save('card_size', newSize);
        window.dispatchEvent(new CustomEvent('settingsUpdated', { detail: { cardSize: newSize } }));
    };
    const [hideDownvotedPosts, setHideDownvotedPosts] = useState(() => {
        const val = Storage.load('hide_downvoted_posts', false);
        return val === true ? true : false;
    });
    const hideDownvotedPostsRef = useRef(hideDownvotedPosts);
    useEffect(() => { hideDownvotedPostsRef.current = hideDownvotedPosts; }, [hideDownvotedPosts]);

    const [hidingPostsSet, setHidingPostsSet] = useState(() => new Set()); // Posts animating out
    const [blockedTopicsLocal, setBlockedTopicsLocal] = useState(() => new Set()); // Optimistic blocked topic patterns (may contain *)
    const [flashingPostsSet, setFlashingPostsSet] = useState(() => {
        // Consume any pending highlight on mount
        const pendingId = Storage.consumePendingPostHighlight();
        return pendingId ? new Set([pendingId]) : new Set();
    });
    const [isLoadingMore, setIsLoadingMore] = useState(false);
    const [isMobile, setIsMobile] = useState(() => {
        try {
            if (typeof window !== 'undefined' && window.matchMedia) {
                return window.matchMedia('(max-width: 600px)').matches;
            }
            if (typeof window !== 'undefined') {
                return window.innerWidth <= 600;
            }
        } catch (_) { }
        return false;
    });
    const _topicMatchesPattern = (topic, pattern) => {
        if (!pattern.includes('*')) return topic === pattern;
        const re = new RegExp('^' + pattern.split('*').map(s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*') + '$');
        return re.test(topic);
    };
    const isTopicBlockedLocal = useCallback((topicVal) => {
        const t = String(topicVal || '').trim().toLowerCase();
        if (!t) return false;
        if (blockedTopicsLocal.size === 0) return false;
        for (const pat of blockedTopicsLocal) {
            if (_topicMatchesPattern(t, pat)) return true;
        }
        return false;
    }, [blockedTopicsLocal]);
    const location = useLocation();  // Call useLocation at the top level of the component
    const viewerAddress = Storage.load('publicKey', '') || 'guest';

    useEffect(() => {
        setBlockedTopicsLocal(new Set());
    }, [viewerAddress]);
    const [followedTopicsSet, setFollowedTopicsSet] = useState(new Set());
    const [followedAuthorsSet, setFollowedAuthorsSet] = useState(new Set());
    const [topicFollowHover, setTopicFollowHover] = useState(false);
    const { isTopicPending, formatTopicStatus } = usePendingFollows();
    const followDataLoadedRef = useRef(false);
    const afterSetPostsRef = useRef(0);
    const topicsLoadedRef = useRef(false); // Track if we've attempted to load topics from API
    const isMountedRef = useRef(true); // Track if component is mounted
    const forceHardRefreshRef = useRef(isInitialPageLoad()); // Bypass debounce on initial page load

    // First-visit welcome card: show on front page until dismissed (only for guests)
    // eslint-disable-next-line no-unused-vars
    const [showWelcomeCard, setShowWelcomeCard] = useState(() => {
        try {
            return !Storage.load('welcome_card_dismissed_v1', false);
        } catch (_) {
            return true;
        }
    });
    // eslint-disable-next-line no-unused-vars
    const dismissWelcomeCard = () => {
        try { Storage.save('welcome_card_dismissed_v1', true); } catch (_) { }
        setShowWelcomeCard(false);
    };

    // Android app banner: show once for Android users until dismissed
    const isAndroid = (() => { try { return /android/i.test(navigator.userAgent); } catch (_) { return false; } })();
    const [androidBannerDismissed, setAndroidBannerDismissed] = useState(() => {
        try { return Storage.load('android_app_banner_dismissed', false); } catch (_) { return false; }
    });
    const dismissAndroidBanner = () => {
        try { Storage.save('android_app_banner_dismissed', true); } catch (_) { }
        setAndroidBannerDismissed(true);
    };

    // iPhone app banner: show once for iPhone users until dismissed
    const isIPhone = (() => { try { return /iPhone/i.test(navigator.userAgent) && !isAndroid; } catch (_) { return false; } })();
    const [iphoneBannerDismissed, setIphoneBannerDismissed] = useState(() => {
        try { return Storage.load('iphone_app_banner_dismissed', false); } catch (_) { return false; }
    });
    const dismissIPhoneBanner = () => {
        try { Storage.save('iphone_app_banner_dismissed', true); } catch (_) { }
        setIphoneBannerDismissed(true);
    };

    // NSFW welcome hero: show once for logged-in users until they choose yes/no
    const [showNsfwHero, setShowNsfwHero] = useState(() => {
        try {
            return !Storage.load('nsfw_hero_dismissed_v1', false);
        } catch (_) {
            return true;
        }
    });

    // handleNsfwChoice is defined after getPosts (see below)

    const isLoggedIn = viewerAddress && viewerAddress !== 'guest';

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

    if (nodeConfigTick > 0 && !nodeConfig) {
        try { console.error('[MainView] nodeConfig missing after fetch attempt'); } catch (_) { }
        throw new Error('MainView requires nodeConfig to render app banners');
    }

    if (nodeConfig && (typeof nodeConfig.android_banner_enabled !== 'boolean' || typeof nodeConfig.ios_banner_enabled !== 'boolean')) {
        try {
            console.error('[MainView] nodeConfig missing banner flags', {
                android_banner_enabled: nodeConfig.android_banner_enabled,
                ios_banner_enabled: nodeConfig.ios_banner_enabled,
            });
        } catch (_) { }
        throw new Error('MainView requires android_banner_enabled and ios_banner_enabled in nodeConfig');
    }

    useEffect(() => {
        if (!nodeConfig) return;
        try {
            console.debug('[MainView] app banner flags', {
                android_banner_enabled: nodeConfig.android_banner_enabled,
                ios_banner_enabled: nodeConfig.ios_banner_enabled,
            });
        } catch (_) { }
    }, [nodeConfig]);

    const inviteCodesEnabled = Boolean(nodeConfig?.registration_enabled) && Boolean(nodeConfig?.registration_invite_code_required);
    const questsEnabled = Boolean(nodeConfig?.quests_enabled) && Boolean(nodeConfig?.quest_payouts_enabled);
    const showAndroidBanner = Boolean(nodeConfig) && isAndroid && !androidBannerDismissed && nodeConfig.android_banner_enabled;
    const showIPhoneBanner = Boolean(nodeConfig) && isIPhone && !iphoneBannerDismissed && nodeConfig.ios_banner_enabled;

    // Invite code state
    const [inviteCodes, setInviteCodes] = useState([]);
    const [inviteModalOpen, setInviteModalOpen] = useState(false);
    const [inviteCodeCopied, setInviteCodeCopied] = useState(false);

    // Welcome stats for logged-out users (user count, posts, DAU)
    // Initialize from cache for instant display (stale-while-revalidate pattern)
    const [welcomeStats, setWelcomeStats] = useState(() => {
        try { return Storage.load('welcome_stats_cache', null); } catch (_) { return null; }
    });
    const [welcomeStatsStale, setWelcomeStatsStale] = useState(() => {
        // If we have cached stats, they're stale until fresh data loads
        try { return Storage.load('welcome_stats_cache', null) !== null; } catch (_) { return false; }
    });

    // Collapse state for hero cards (persisted)
    const [inviteBannerCollapsed, setInviteBannerCollapsed] = useState(() => {
        try { return Storage.load('invite_banner_collapsed', true); } catch (_) { return true; }
    });
    const [questCardCollapsed, setQuestCardCollapsed] = useState(() => {
        try { return Storage.load('quest_card_collapsed', false); } catch (_) { return false; }
    });
    const toggleInviteBanner = () => {
        const next = !inviteBannerCollapsed;
        setInviteBannerCollapsed(next);
        try { Storage.save('invite_banner_collapsed', next); } catch (_) { }
    };
    const toggleQuestCard = () => {
        const next = !questCardCollapsed;
        setQuestCardCollapsed(next);
        try { Storage.save('quest_card_collapsed', next); } catch (_) { }
    };

    // Fetch invite codes for logged-in users
    useEffect(() => {
        if (!isLoggedIn || !inviteCodesEnabled) {
            setInviteCodes([]);
            return;
        }
        let cancelled = false;
        const loadInviteCodes = async () => {
            try {
                const resp = await Api.get('get_invite_codes', { address: viewerAddress });
                if (cancelled) return;
                if (resp && Array.isArray(resp.codes)) {
                    setInviteCodes(resp.codes);
                }
            } catch (_) { }
        };
        loadInviteCodes();

        // Listen for invite codes updates (e.g., when claimed from quests)
        const handleInviteCodesUpdated = () => {
            loadInviteCodes();
        };
        window.addEventListener('inviteCodesUpdated', handleInviteCodesUpdated);

        return () => {
            cancelled = true;
            window.removeEventListener('inviteCodesUpdated', handleInviteCodesUpdated);
        };
    }, [isLoggedIn, viewerAddress, inviteCodesEnabled]);

    // Fetch welcome stats for logged-out users (user count, posts in 24h, DAU)
    // Uses lightweight endpoint that only returns essential counts (fast, cached)
    // Implements stale-while-revalidate: show cached value immediately, update when fresh
    useEffect(() => {
        if (isLoggedIn) return; // Only fetch for logged-out visitors

        let cancelled = false;
        const loadWelcomeStats = async () => {
            try {
                const data = await Api.get('get_welcome_stats', {}, { timeoutMs: 3000 });
                if (cancelled) return;
                if (data) {
                    const freshStats = {
                        userCount: data.registered_users || 0,
                        posts24h: data.posts_24h || 0,
                        comments24h: 0,
                        active24h: data.active_24h || 0,
                    };
                    setWelcomeStats(freshStats);
                    setWelcomeStatsStale(false);
                    try { Storage.save('welcome_stats_cache', freshStats); } catch (_) { }
                }
            } catch (_) {
                // Keep showing stale data if we have it
            }
        };
        loadWelcomeStats();
        return () => { cancelled = true; };
    }, [isLoggedIn]);

    // Get next available invite code
    const nextAvailableCode = inviteCodes.find(c => !c.is_used);
    const availableCodeCount = inviteCodes.filter(c => !c.is_used).length;

    // Handle opening invite modal
    const handleOpenInviteModal = () => {
        setInviteModalOpen(true);
        setInviteCodeCopied(false);
    };

    const handleCopyInviteCode = () => {
        if (!nextAvailableCode) return;
        navigator.clipboard.writeText(getShareUrl());
        setInviteCodeCopied(true);
        setTimeout(() => setInviteCodeCopied(false), 2000);
    };

    // Handle native share (mobile)
    const handleNativeShare = async () => {
        if (!nextAvailableCode || !navigator.share) return;
        try {
            await navigator.share({
                title: 'Join me on Mirage',
                text: getShareText(),
                url: getShareUrl(),
            });
        } catch (err) {
            // User cancelled or share failed - ignore
        }
    };

    // Check if native share is available (typically mobile)
    const canNativeShare = typeof navigator !== 'undefined' && !!navigator.share;

    const getShareUrl = () => {
        if (!nextAvailableCode) return '';
        const viewerName = Storage.load('username', '');
        const precheckEnabled = Storage.load('referral_precheck_enabled', false) === true;
        if (inviteCodesEnabled && precheckEnabled && viewerName) {
            return `${window.location.origin}/signup?ref=${encodeURIComponent(viewerName)}`;
        }
        return `${window.location.origin}/signup?invite=${nextAvailableCode.code}`;
    };

    const SHARE_TEXTS = [
        // Tame / Descriptive
        'Join me on Mirage: a decentralized social network.',
        'Join me on Mirage: social media, decentralized.',
        'Join me on Mirage: the decentralized social platform.',
        'Join me on Mirage: where conversations happen on-chain.',
        'Join me on Mirage: social media built on blockchain.',
        'Join me on Mirage: a new kind of social network.',
        'Join me on Mirage: decentralized and user-controlled.',
        'Join me on Mirage: social media you actually own.',
        'Join me on Mirage: your posts live on the blockchain.',
        'Join me on Mirage: decentralized discourse awaits.',
        'Join me on Mirage: where you control your experience.',
        'Join me on Mirage: social media with transparency built in.',
        'Join me on Mirage: open, decentralized, community-driven.',
        'Join me on Mirage: the user-first social network.',
        'Join me on Mirage: social media redesigned for users.',
        'Join me on Mirage: simple, decentralized, yours.',
        'Join me on Mirage: a platform built for real conversations.',
        'Join me on Mirage: where your data stays yours.',
        'Join me on Mirage: social media without the middleman.',
        'Join me on Mirage: decentralized by design.',
        // User Control Focus
        'Join me on Mirage: you control your feed, not an algorithm.',
        'Join me on Mirage: no black box algorithms here.',
        'Join me on Mirage: you own your algorithm.',
        'Join me on Mirage: your feed, your rules.',
        'Join me on Mirage: take back control of your feed.',
        'Join me on Mirage: transparent algorithms, real control.',
        'Join me on Mirage: no hidden manipulation, just content you choose.',
        'Join me on Mirage: the algorithm works for you, not against you.',
        'Join me on Mirage: see what you want, not what they want.',
        'Join me on Mirage: your timeline, your choice.',
        'Join me on Mirage: no engagement tricks, just real content.',
        'Join me on Mirage: social media that respects your attention.',
        'Join me on Mirage: finally, a feed you understand.',
        'Join me on Mirage: no mystery algorithms deciding what you see.',
        'Join me on Mirage: user-centric from day one.',
        'Join me on Mirage: built around you, not advertisers.',
        'Join me on Mirage: your experience, your control.',
        'Join me on Mirage: social media that puts users first.',
        'Join me on Mirage: no data harvesting, just discourse.',
        'Join me on Mirage: privacy and control by default.',
        // Anti-Corporate
        'Join me on Mirage: no corporate overlords.',
        'Join me on Mirage: social media without corporate control.',
        'Join me on Mirage: free from corporate censorship.',
        'Join me on Mirage: no faceless corporations deciding what\'s allowed.',
        'Join me on Mirage: discourse without corporate interference.',
        'Join me on Mirage: not owned by billionaires.',
        'Join me on Mirage: social media that can\'t be bought.',
        'Join me on Mirage: no shareholders to please, just users.',
        'Join me on Mirage: built for people, not profits.',
        'Join me on Mirage: no ads, no corporate agenda.',
        'Join me on Mirage: social media without the corporate BS.',
        'Join me on Mirage: where corporations don\'t control the conversation.',
        'Join me on Mirage: no CEO can change the rules on you.',
        'Join me on Mirage: your voice isn\'t a product here.',
        'Join me on Mirage: social media that doesn\'t sell you out.',
        'Join me on Mirage: no corporate content moderation.',
        'Join me on Mirage: escape the corporate walled gardens.',
        'Join me on Mirage: owned by everyone, controlled by no one.',
        'Join me on Mirage: social media without the suits.',
        'Join me on Mirage: decentralized means no corporate master.',
        // Censorship / Free Speech
        'Join me on Mirage: censorship-proof by design.',
        'Join me on Mirage: where speech is protected, not policed.',
        'Join me on Mirage: built to protect speech, not suppress it.',
        'Join me on Mirage: your voice can\'t be silenced here.',
        'Join me on Mirage: no arbitrary bans, no shadow banning.',
        'Join me on Mirage: speak freely, permanently.',
        'Join me on Mirage: censorship-resistant social media.',
        'Join me on Mirage: your posts can\'t be erased by agents.',
        'Join me on Mirage: where deplatforming isn\'t possible.',
        'Join me on Mirage: true freedom of expression.',
        'Join me on Mirage: your speech doesn\'t need approval.',
        'Join me on Mirage: no trust & safety theater here.',
        'Join me on Mirage: post without fear of removal.',
        'Join me on Mirage: uncensorable discourse.',
        'Join me on Mirage: where no one can memory-hole your posts.',
        'Join me on Mirage: permanent, immutable, yours.',
        'Join me on Mirage: the platform that can\'t censor you.',
        'Join me on Mirage: your words, preserved forever on-chain.',
        'Join me on Mirage: no one decides what you can say.',
        'Join me on Mirage: discourse without gatekeepers.',
        // Provocative / Bold
        'Join me on Mirage: the social network they can\'t shut down.',
        'Join me on Mirage: unstoppable.',
        'Join me on Mirage: decentralized, unstoppable, yours.',
        'Join me on Mirage: true discourse, decentralized, unstoppable.',
        'Join me on Mirage: what Reddit could have been.',
        'Join me on Mirage: what Twitter should have been.',
        'Join me on Mirage: what social media was meant to be.',
        'Join me on Mirage: social media, unchained.',
        'Join me on Mirage: the revolution is decentralized.',
        'Join me on Mirage: they can\'t stop the signal.',
        'Join me on Mirage: immune to takedowns.',
        'Join me on Mirage: no kill switch.',
        'Join me on Mirage: built to survive.',
        'Join me on Mirage: the platform that fights back.',
        'Join me on Mirage: ungovernable social media.',
        'Join me on Mirage: where free speech isn\'t negotiable.',
        'Join me on Mirage: the network no government can silence.',
        'Join me on Mirage: decentralized means unstoppable.',
        'Join me on Mirage: burn the algorithm, own your feed.',
        'Join me on Mirage: social media with teeth.',
    ];

    const getShareText = () => {
        return SHARE_TEXTS[Math.floor(Math.random() * SHARE_TEXTS.length)];
    };

    useEffect(() => {
        let cancelled = false;
        const loadFollowData = async () => {
            if (!viewerAddress || viewerAddress === 'guest' || followDataLoadedRef.current) return;
            try {
                const [topics, authors] = await Promise.all([
                    fetchFollowedTopics(viewerAddress),
                    fetchFollowedUsers(viewerAddress)
                ]);
                if (cancelled) return;
                setFollowedTopicsSet(new Set(topics.map(t => t.toLowerCase())));
                setFollowedAuthorsSet(new Set(authors.map(a => a.toLowerCase())));
                followDataLoadedRef.current = true;
            } catch (_) { }
        };
        loadFollowData();
        return () => { cancelled = true; };
    }, [viewerAddress]);

    // Listen for settings changes (downvote hiding) - tag changes handled after getPosts is defined
    useEffect(() => {
        const handler = (e) => {
            const detail = e?.detail || {};
            if (Object.prototype.hasOwnProperty.call(detail, 'hideDownvotedPosts')) {
                setHideDownvotedPosts(Boolean(detail.hideDownvotedPosts));
            }
        };
        window.addEventListener('settingsUpdated', handler);
        return () => window.removeEventListener('settingsUpdated', handler);
    }, []);

    // Track mobile screen size to hide compact option in dropdown
    useEffect(() => {
        const checkMobile = () => {
            try {
                if (typeof window !== 'undefined' && window.matchMedia) {
                    const mobile = window.matchMedia('(max-width: 600px)').matches;
                    setIsMobile(mobile);
                } else if (typeof window !== 'undefined') {
                    const mobile = window.innerWidth <= 600;
                    setIsMobile(mobile);
                }
            } catch (_) { }
        };
        checkMobile();
        window.addEventListener('resize', checkMobile);
        if (typeof window !== 'undefined' && window.matchMedia) {
            const mediaQuery = window.matchMedia('(max-width: 600px)');
            if (mediaQuery.addEventListener) {
                mediaQuery.addEventListener('change', checkMobile);
                return () => {
                    window.removeEventListener('resize', checkMobile);
                    mediaQuery.removeEventListener('change', checkMobile);
                };
            }
        }
        return () => window.removeEventListener('resize', checkMobile);
    }, []);

    // Track posts the viewer downvoted to hide with animation on Home
    useEffect(() => {
        const handler = (e) => {
            const detail = e?.detail || {};
            const pid = String(detail?.postId || '').toLowerCase();
            const dir = Number(detail?.direction);
            if (!pid || dir >= 0) return;

            // Only hide if the setting is enabled AND we are on the Home feed
            // The setting explicitly says "(Home feed only)", so we shouldn't animate on other feeds
            // where the post will reappear anyway.
            const isHome = currentTopicRef.current === 'home';
            if (!hideDownvotedPostsRef.current || !isHome) return;

            // First, add to hiding set to trigger animation
            setHidingPostsSet((prev) => {
                if (prev.has(pid)) return prev;
                const next = new Set(prev);
                next.add(pid);
                return next;
            });

            // After fade animation completes, permanently hide for this session
            setTimeout(() => {
                try {
                    if (typeof updatePost === 'function') {
                        updatePost(pid, { hidden_client: true });
                    }
                } catch (_) { /* noop */ }
                try {
                    setStableOrder((prev) => prev.filter((id) => String(id || '').toLowerCase() !== pid));
                } catch (_) { /* noop */ }
                setHidingPostsSet((prev) => {
                    if (!prev.has(pid)) return prev;
                    const next = new Set(prev);
                    next.delete(pid);
                    return next;
                });
            }, 250);
        };
        window.addEventListener('postDownvoted', handler);
        return () => window.removeEventListener('postDownvoted', handler);
    }, [updatePost]);

    // Clear flash animation after it completes
    useEffect(() => {
        if (flashingPostsSet.size === 0) return;
        const timer = setTimeout(() => {
            setFlashingPostsSet(new Set());
        }, 1000);
        return () => clearTimeout(timer);
    }, [flashingPostsSet]);

    const optimisticPostIdsRef = useRef(new Map()); // post_id -> created_at_ms

    const getPosts = useCallback((topic, overrideChrono = null, pageOverride = null, silent = false) => {
        if (!isMountedRef.current) return;

        // Never fetch posts for logged-out users
        const viewer = Storage.load("publicKey", "");
        if (!viewer || viewer === 'guest') return;

        if (topic === "")
            topic = "all";

        const isHomeFeed = topic === 'home';
        const isFollowingFeed = topic === 'following';

        if (topic !== state.topic) {
            if (!isMountedRef.current) return;
            setTopic(topic);
        }

        if (!isMountedRef.current) return;
        // Only show full loading state for initial load or topic switch, not pagination
        const effectivePage = (typeof pageOverride === 'number' && Number.isFinite(pageOverride) && pageOverride > 0) ? Math.floor(pageOverride) : currentPage;
        const isPaginating = effectivePage > 1;
        if (!silent && !isPaginating) {
            setIsLoading(true);
        }

        const viewerAddress = Storage.load("publicKey", "");
        const page = effectivePage;

        const matchTopic = (t) => {
            if (topic === 'all') return true;
            if (topic === 'home' || topic === 'following') return true;
            return String(t || '').toLowerCase() === String(topic || '').toLowerCase();
        };

        const handleResponse = (data) => {
            if (!isMountedRef.current) return;
            const forcedHard = !!forceHardRefreshRef.current;
            const arr = (data && Array.isArray(data.posts)) ? data.posts : [];

            const hasMore = !!(data && data.has_more);
            if (!isMountedRef.current) return;
            setHasMorePosts(hasMore);

            const isTopLevelPost = (p) => {
                if (!p) return false;
                const hasTitle = typeof p.title === 'string' && p.title.trim().length > 0;
                const hasTopic = typeof p.topic === 'string' && p.topic.trim().length > 0;
                const topicVal = String(p.topic || '').trim().toLowerCase();
                const isReserved = ['all', 'home', 'following'].includes(topicVal);
                return hasTitle && hasTopic && !isReserved;
            };
            const topLevel = arr.filter(isTopLevelPost);
            let filtered = (isHomeFeed || isFollowingFeed)
                ? topLevel
                : topLevel.filter(p => matchTopic(p.topic));

            // Note: Downvote filtering is handled in render phase to avoid stale closure issues

            // Server already returns posts in correct order for all feeds (magic or newest)
            const sortedOnce = filtered;
            const sortedOrder = sortedOnce.map(p => p.post_id);

            const postDict = sortedOnce.reduce((acc, post) => {
                acc[post.post_id] = post;
                return acc;
            }, {});

            if (!isMountedRef.current) return;
            afterSetPostsRef.current = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();

            if (page === 1) {
                setPosts(postDict, Date.now());
            } else {
                // Append new posts to existing ones
                const currentPosts = state.posts || {};
                const combined = { ...currentPosts, ...postDict };
                setPosts(combined, Date.now());
            }

            if (!isMountedRef.current) return;
            setStableOrder((currentOrder) => {
                if (page === 1) {
                    const topicChanged = currentTopicRef.current !== topic;
                    if (topicChanged || forcedHard) {
                        const now = Date.now();
                        const keepOptimistic = [];
                        for (const [id, ts] of optimisticPostIdsRef.current.entries()) {
                            if (now - Number(ts || 0) > 5 * 1000) continue;
                            if (!sortedOrder.includes(id) && currentOrder.includes(id)) keepOptimistic.push(id);
                            if (sortedOrder.includes(id)) optimisticPostIdsRef.current.delete(id);
                        }
                        return [...keepOptimistic, ...sortedOrder.filter((id) => !keepOptimistic.includes(id))];
                    } else {
                        // Same topic refresh: preserve existing posts from previous pages
                        const currentPosts = state.posts || {};
                        const existingPostsInOrder = currentOrder.filter(id => {
                            const post = currentPosts[id];
                            if (!post || post.deleted) return false;
                            if (topic === 'all') {
                                const hasTitle = typeof post.title === 'string' && post.title.trim().length > 0;
                                const hasTopic = typeof post.topic === 'string' && post.topic.trim().length > 0;
                                const topicVal = String(post.topic || '').trim().toLowerCase();
                                const isReserved = ['all', 'home', 'following'].includes(topicVal);
                                return hasTitle && hasTopic && !isReserved;
                            } else if (topic === 'home' || topic === 'following') {
                                return isTopLevelPost(post);
                            } else {
                                return String(post.topic || '').trim().toLowerCase() === topic.toLowerCase();
                            }
                        }).filter(id => !sortedOrder.includes(id));
                        return [...sortedOrder, ...existingPostsInOrder];
                    }
                } else {
                    // Append new posts to existing order
                    return [...currentOrder, ...sortedOrder.filter(id => !currentOrder.includes(id))];
                }
            });
            try { forceHardRefreshRef.current = false; } catch (_) { }

            // Mark topic switch complete - from now on, render new topic
            if (!isMountedRef.current) return;
            try { currentTopicRef.current = topic; } catch (_) { }
            // Only clear isLoading if we set it (not during pagination)
            if (page === 1) {
                if (!silent) setIsLoading(false);
                setIsLoadingMore(false);
                try { loadMoreLockRef.current = false; } catch (_) { }
            } else {
                // For pagination, defer clearing isLoadingMore until after posts render
                requestAnimationFrame(() => {
                    if (isMountedRef.current) {
                        setIsLoadingMore(false);
                        try { loadMoreLockRef.current = false; } catch (_) { }
                    }
                });
            }
        };

        const onError = (error) => {
            if (!isMountedRef.current) return;
            const errorMessage = (error && error.message) ? error.message : "An unknown error occurred";
            setError(errorMessage);
            try { forceHardRefreshRef.current = false; } catch (_) { }
            // Only clear isLoading if we set it (not during pagination)
            if (page === 1) {
                if (!silent) setIsLoading(false);
            }
            setIsLoadingMore(false);
            try { loadMoreLockRef.current = false; } catch (_) { }
        };

        // Determine sort mode
        const mode = overrideChrono !== null
            ? (overrideChrono ? 'newest' : 'magic')
            : homeSortMode;

        if (isHomeFeed || isFollowingFeed) {
            const params = { feed: topic, limit: 15, page: page, address: viewerAddress };
            params.by = mode;
            params.allowed_tags = getAllowedTagsParam();
            Api.get('get_posts', params)
                .then(handleResponse)
                .catch(onError);
        } else {
            const params = { topic, limit: 15, page: page, address: viewerAddress };
            params.by = mode;
            params.allowed_tags = getAllowedTagsParam();
            Api.get('get_posts', params)
                .then(handleResponse)
                .catch(onError);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [state.topic, state.lastFetched, setTopic, setPosts, currentPage, followedTopicsSet, followedAuthorsSet, homeSortMode, isLoadingMore, hideDownvotedPosts]);

    // handleNsfwChoice - must be after getPosts is defined
    const handleNsfwChoice = useCallback((allowNsfw) => {
        try {
            // Dismiss the hero
            Storage.save('nsfw_hero_dismissed_v1', true);
            setShowNsfwHero(false);

            if (allowNsfw) {
                // Enable all NSFW tags
                Storage.save('show_tag_porn', true);
                Storage.save('show_tag_violence', true);
                Storage.save('show_tag_gore', true);
                Storage.save('show_tag_death', true);
                // Dispatch settings update event so feed refreshes
                window.dispatchEvent(new CustomEvent('settingsUpdated', {
                    detail: {
                        showTagPorn: true,
                        showTagViolence: true,
                        showTagGore: true,
                        showTagDeath: true
                    }
                }));
            }
            // If they click "No", we keep defaults (only sensitive allowed)
            // No action needed as that's already the default

            // Force refresh the feed to apply the new settings
            try {
                forceHardRefreshRef.current = true;
                setIsLoading(true);
                setCurrentPage(1);
                setHasMorePosts(false);
                setStableOrder([]);
                // Always force page 1 on user-initiated feed refresh to avoid stale pagination leaks
                getPosts(urlTopic, null, 1);
            } catch (_) { /* noop */ }
        } catch (_) { /* noop */ }
    }, [getPosts, urlTopic]);

    // Listen for content tag settings changes - must be after getPosts is defined
    useEffect(() => {
        const handler = (e) => {
            const detail = e?.detail || {};
            const tagKeys = ['showTagSensitive', 'showTagPorn', 'showTagViolence', 'showTagGore', 'showTagDeath'];
            const hasTagChange = tagKeys.some(key => Object.prototype.hasOwnProperty.call(detail, key));
            if (hasTagChange) {
                // Force refresh the home feed to apply new tag filters
                try {
                    forceHardRefreshRef.current = true;
                    setIsLoading(true);
                    setCurrentPage(1);
                    setHasMorePosts(false);
                    setStableOrder([]);
                    getPosts(urlTopic, null, 1);
                } catch (_) { /* noop */ }
            }
        };
        window.addEventListener('settingsUpdated', handler);
        return () => window.removeEventListener('settingsUpdated', handler);
    }, [getPosts, urlTopic]);

    // Listen for new post creation events (must be after getPosts is defined)
    useEffect(() => {
        const handler = (e) => {
            const detail = e?.detail || {};
            const pid = String(detail?.postId || '').toLowerCase();
            if (!pid) return;
            try {
                const viewer = String(Storage.load("publicKey", "") || '').trim().toLowerCase();
                const topic = String(detail?.topic || '').trim();
                const title = String(detail?.title || '').trim();
                const content = String(detail?.content || '');
                const tag = String(detail?.tag || '').trim().toLowerCase();
                const thumbnail = String(detail?.thumbnail || '').trim();
                if (viewer && viewer !== 'guest' && topic && title) {
                    const nowSec = Math.floor(Date.now() / 1000);
                    const optimistic = {
                        post_id: pid,
                        author: viewer,
                        user_id: viewer,
                        username: "",
                        timestamp: nowSec,
                        topic,
                        title,
                        content,
                        tag,
                        thumbnail: thumbnail || "",
                        direction: 1,
                        user_vote: 1,
                        points: 1,
                        comments: 0,
                        deleted: false,
                    };
                    optimisticPostIdsRef.current.set(pid, Date.now());
                    setPosts({ [pid]: optimistic }, Date.now());
                    setStableOrder((prev) => [pid, ...prev.filter((id) => id !== pid)]);
                }
            } catch (_) { /* noop */ }
            setFlashingPostsSet((prev) => {
                if (prev.has(pid)) return prev;
                const next = new Set(prev);
                next.add(pid);
                return next;
            });
            // If we're on home, immediately refetch page 1 in the current mode and pin the fresh post
            if ((currentTopicRef.current === 'home') || (urlTopic === 'home')) {
                try { forceHardRefreshRef.current = true; } catch (_) { }
                setCurrentPage(1);
                setHasMorePosts(false);
                setIsLoadingMore(false);
                try { loadMoreLockRef.current = false; } catch (_) { }
                getPosts('home', homeSortMode === 'newest', 1, true);
            }
        };
        window.addEventListener('postCreated', handler);
        return () => window.removeEventListener('postCreated', handler);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [getPosts, urlTopic, homeSortMode]);

    // Reset page and loading state when topic changes
    // Skip reset on back navigation (we want to restore cached state)
    useEffect(() => {
        // On back navigation, don't reset - state was already restored from cache
        if (isBackNavigation || restoreFeedIntentRef.current === true) {
            return;
        }

        // Force fresh fetch on navigation (bypass debounce)
        forceHardRefreshRef.current = true;
        setCurrentPage(1);
        setHasMorePosts(false);
        setStableOrder([]); // Clear stale order to prevent flash of old content
        setIsLoading(true); // Show loading immediately when navigating
    }, [urlTopic, viewerAddress, homeSortMode, hideDownvotedPosts, isBackNavigation]);

    // Infinite scroll: observe a sentinel near the bottom (also clickable fallback)
    const bottomSentinelRef = useRef(null);
    const loadMoreLockRef = useRef(false);
    const loadMore = useCallback(() => {
        if (!hasMorePosts || isLoadingMore || isLoading) {
            console.debug('[Feed] loadMore blocked:', { hasMorePosts, isLoadingMore, isLoading });
            return;
        }
        if (loadMoreLockRef.current) {
            console.debug('[Feed] loadMore blocked: lock held');
            return;
        }
        loadMoreLockRef.current = true;
        setIsLoadingMore(true);
        setCurrentPage((prev) => {
            console.debug('[Feed] loadMore: page', prev, '->', prev + 1);
            return prev + 1;
        });
    }, [hasMorePosts, isLoadingMore, isLoading]);

    // Safety: release stuck loadMore lock after 10s
    useEffect(() => {
        if (!isLoadingMore) return;
        const timer = setTimeout(() => {
            if (loadMoreLockRef.current) {
                console.warn('[Feed] loadMore lock stuck for 10s, releasing');
                loadMoreLockRef.current = false;
                setIsLoadingMore(false);
            }
        }, 10000);
        return () => clearTimeout(timer);
    }, [isLoadingMore]);

    // IntersectionObserver for infinite scroll
    useEffect(() => {
        const el = bottomSentinelRef.current;
        if (!el) return;
        if (!hasMorePosts || isLoadingMore || isLoading) return;

        // Check if sentinel is already in the visible viewport (content shorter than screen)
        const rect = el.getBoundingClientRect();
        const isAlreadyVisible = rect.top < window.innerHeight;
        if (isAlreadyVisible) {
            console.debug('[Feed] sentinel already visible, triggering loadMore');
            loadMore();
            return;
        }

        // Trigger loading ~2-3 cards before bottom (600px margin)
        const observer = new IntersectionObserver(
            (entries) => {
                const entry = entries[0];
                if (entry && entry.isIntersecting) {
                    console.debug('[Feed] IntersectionObserver triggered');
                    loadMore();
                }
            },
            {
                root: null,
                rootMargin: '600px 0px',
                threshold: 0
            }
        );
        observer.observe(el);
        return () => observer.disconnect();
    }, [hasMorePosts, isLoadingMore, isLoading, stableOrder.length, loadMore]);

    // Backup scroll listener for browsers where IntersectionObserver may not fire reliably
    useEffect(() => {
        if (!hasMorePosts || isLoadingMore || isLoading) return;

        let ticking = false;
        const handleScroll = () => {
            if (ticking) return;
            ticking = true;
            requestAnimationFrame(() => {
                ticking = false;
                if (!hasMorePosts || isLoadingMore || isLoading || loadMoreLockRef.current) return;
                const el = bottomSentinelRef.current;
                if (!el) return;
                const rect = el.getBoundingClientRect();
                // Trigger when sentinel is within 600px of viewport bottom
                if (rect.top < window.innerHeight + 600) {
                    loadMore();
                }
            });
        };

        window.addEventListener('scroll', handleScroll, { passive: true });
        return () => window.removeEventListener('scroll', handleScroll);
    }, [hasMorePosts, isLoadingMore, isLoading, loadMore]);

    // Trigger fetch when page increments (pagination)
    useEffect(() => {
        // Only fetch page > 1 when infinite-scroll explicitly requested it.
        // This prevents stale state from a previous feed from accidentally fetching page 2 on navigation.
        if (currentPage > 1 && hasMorePosts && isLoadingMore) {
            try { console.log('[Feed] paginate fetch:', { topic: urlTopic, page: currentPage }); } catch (_) { }
            getPosts(urlTopic);
        } else if (currentPage > 1 && !hasMorePosts) {
            setIsLoadingMore(false);
            try { loadMoreLockRef.current = false; } catch (_) { }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentPage, urlTopic, hasMorePosts, isLoadingMore]);

    useEffect(() => {
        // Skip topics fetch for logged-out users - they can't navigate topics anyway
        if (!isLoggedIn) return;

        const storedTopicsData = Storage.load("topics", { topics: [], lastFetched: null });
        const stored = Array.isArray(storedTopicsData.topics) ? storedTopicsData.topics : [];
        const lastFetched = storedTopicsData.lastFetched ? new Date(storedTopicsData.lastFetched) : null;

        const shouldFetch = stored.length === 0 || !lastFetched || (Date.now() - lastFetched.getTime()) > 24 * 60 * 60 * 1000;

        if (shouldFetch && !topicsLoadedRef.current) {
            topicsLoadedRef.current = true;
            let cancelled = false;
            Api.get('get_topics', { limit: 50, min_posts: 1, address: viewerAddress })
                .then((data) => {
                    if (cancelled || !isMountedRef.current) return;
                    if (data && Array.isArray(data.topics)) {
                        const topicsWithCounts = data.topics
                            .filter(t => t && t.topic && typeof t.topic === 'string' && t.topic.trim() !== '')
                            .map(t => ({ topic: t.topic, count: t.post_count || t.count || 0 }));
                        const topicNames = topicsWithCounts.map(t => t.topic);
                        const topicsWithAll = ['all', ...topicNames];
                        Storage.save("topics", { topics: topicsWithAll, topicsWithCounts: topicsWithCounts, lastFetched: new Date().toISOString() });
                        setTopics(topicsWithAll);
                    }
                })
                .catch((error) => {
                    if (cancelled || !isMountedRef.current) return;
                    topicsLoadedRef.current = false;
                });
            return () => {
                cancelled = true;
            };
        } else if (stored.length > 0) {
            setTopics(stored);
        }
    }, [isLoggedIn, viewerAddress]);

    useEffect(() => {
        window.getPosts = getPosts;  // Expose getPosts globally
        let cancelled = false;

        // Skip posts fetch for logged-out users - they see the welcome screen instead
        if (!isLoggedIn) {
            setIsLoading(false);
            return;
        }

        // On back navigation (POP), restore from cache if available
        if (shouldRestoreFeedState) {
            const memOrder = readMemFeedState(urlTopic)?.order;
            const order = readSavedOrder(urlTopic) || (Array.isArray(memOrder) ? memOrder : null);
            const hasPostsForOrder = !!(order && order.length > 0 && state.posts && order.some((id) => state.posts[id]));
            const hasPostsForTopic = hasAnyCachedPostsForTopic(urlTopic, state.posts);

            if (hasPostsForOrder || hasPostsForTopic) {
                // Back navigation with cached data - don't fetch
                if (!cancelled && isMountedRef.current) {
                    setIsLoading(false);
                    setIsLoadingMore(false);
                    loadMoreLockRef.current = false;
                }
                try { console.log('[Feed] POP restore from cache:', urlTopic); } catch (_) { }
                return;
            }
        }

        // For forward navigation (clicking links), ALWAYS fetch fresh
        // Force bypass debounce - this is a user-initiated navigation
        forceHardRefreshRef.current = true;
        setCurrentPage(1);
        setStableOrder([]);  // Clear stale order
        setIsLoading(true);
        try { console.log('[Feed] PUSH fetch fresh:', urlTopic); } catch (_) { }

        const timeoutId = setTimeout(() => {
            if (cancelled || !isMountedRef.current) return;
            // Hard force page 1 on navigation so Home/Following never starts at page 2
            getPosts(urlTopic, null, 1);
        }, 50);
        return () => {
            cancelled = true;
            clearTimeout(timeoutId);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [urlTopic, location.pathname]);

    // Refetch when homeSortMode changes (magic/newest toggle)
    const prevHomeSortModeRef = useRef(homeSortMode);
    useEffect(() => {
        // Only trigger if homeSortMode actually changed (not on mount)
        if (prevHomeSortModeRef.current === homeSortMode) return;
        prevHomeSortModeRef.current = homeSortMode;

        // Force refetch with new mode (works for all feeds including topics)
        forceHardRefreshRef.current = true;
        setCurrentPage(1);
        setHasMorePosts(false);
        setStableOrder([]);
        setIsLoading(true);
        getPosts(urlTopic, null, 1);
    }, [homeSortMode, urlTopic, getPosts]);

    useEffect(() => {
        const storedTopicsData = Storage.load("topics", { topics: [], lastFetched: null });
        const stored = Array.isArray(storedTopicsData.topics) ? storedTopicsData.topics : [];

        // If not viewing "all", preserve known topics from storage (do not drop).
        if (urlTopic !== "all") {
            if (stored.length > 0) {
                setTopics(stored);
            } else {
                const fallback = ["all", ...(urlTopic ? [urlTopic] : [])];
                setTopics(fallback);
            }
            return;
        }

        // When viewing "all", just use stored topics (no merging)
        if (stored.length > 0) {
            setTopics(stored);
        }
    }, [urlTopic]);

    // Recompute stable order only when needed; skip if already set by latest fetch
    useEffect(() => {
        if (stableOrder.length > 0) return;
        // Don't compute from possibly stale state.posts while loading fresh data
        // This prevents showing old content briefly before the fetch completes
        if (isLoading) return;
        const postsArray = Object.values(state.posts || {});
        const isTopLevelPost = (p) => {
            if (!p) return false;
            if (p.hidden_client) return false;
            const hasTitle = typeof p.title === 'string' && p.title.trim().length > 0;
            const hasTopic = typeof p.topic === 'string' && p.topic.trim().length > 0;
            const topicVal = String(p.topic || '').trim().toLowerCase();
            const isReserved = ['all', 'home', 'following'].includes(topicVal);
            if (isTopicBlockedLocal(topicVal)) return false;
            return hasTitle && hasTopic && !isReserved;
        };
        const topLevelPosts = postsArray.filter(isTopLevelPost);
        const filtered = (urlTopic === "all" || urlTopic === "home" || urlTopic === "following")
            ? topLevelPosts
            : topLevelPosts.filter(post => String(post.topic || '').toLowerCase() === String(urlTopic || '').toLowerCase());
        // Server already returns posts in correct order
        setStableOrder(filtered.map(p => p.post_id));
    }, [state.lastFetched, urlTopic, homeSortMode, stableOrder.length, state.posts, viewerAddress, followedTopicsSet, followedAuthorsSet, isLoading, isTopicBlockedLocal]);

    // Measure time from posts set to first render of list
    useEffect(() => {
        if (!state.lastFetched) return;
        if (afterSetPostsRef.current) {
            afterSetPostsRef.current = 0;
        }
    }, [state.lastFetched]);

    // Cleanup on unmount
    useEffect(() => {
        isMountedRef.current = true;
        return () => {
            isMountedRef.current = false;
        };
    }, []);

    // Save feed state to sessionStorage when values change (for back button restoration)
    // Each topic gets its own cache keys so we can restore any feed independently
    useEffect(() => {
        try {
            const orderKey = getFeedKey(urlTopic, 'order');
            if (stableOrder.length > 0) sessionStorage.setItem(orderKey, JSON.stringify(stableOrder));
            else sessionStorage.removeItem(orderKey);
            sessionStorage.setItem(getFeedKey(urlTopic, 'page'), String(currentPage));
            sessionStorage.setItem(getFeedKey(urlTopic, 'hasmore'), String(hasMorePosts));
        } catch (_) { }
        try {
            writeMemFeedState(urlTopic, {
                order: stableOrder,
                page: currentPage,
                hasMore: hasMorePosts,
            });
        } catch (_) { }
    }, [urlTopic, stableOrder, currentPage, hasMorePosts]);

    // Save scroll position before navigating away (keyed by current topic)
    useEffect(() => {
        const saveScrollPosition = () => {
            try {
                sessionStorage.setItem(getFeedKey(urlTopic, 'scroll'), String(window.scrollY || 0));
            } catch (_) { }
            try {
                writeMemFeedState(urlTopic, {
                    scroll: Number(window.scrollY || 0),
                });
            } catch (_) { }
        };

        // Save on any navigation (clicking links)
        const handleClick = (e) => {
            // Check if it's a link click that will navigate
            const link = e.target.closest('a');
            // eslint-disable-next-line no-script-url
            if (link && link.href && !link.href.startsWith('javascript:')) {
                saveScrollPosition();
                // Mark that we navigated to a post from the feed
                // This enables browser back button to restore feed position
                try {
                    const url = new URL(link.href, window.location.origin);
                    if (url.pathname.startsWith('/p/')) {
                        sessionStorage.setItem('mirage_post_nav_source', JSON.stringify({
                            source: 'feed',
                            topic: urlTopic,
                            at: Date.now(),
                        }));
                        sessionStorage.setItem('mirage_came_from_feed', JSON.stringify({
                            topic: urlTopic,
                            at: Date.now(),
                        }));
                    }
                } catch (_) { }
            }
        };

        // Also save before unload
        window.addEventListener('click', handleClick, true);
        window.addEventListener('beforeunload', saveScrollPosition);

        return () => {
            window.removeEventListener('click', handleClick, true);
            window.removeEventListener('beforeunload', saveScrollPosition);
        };
    }, [urlTopic]);

    // Track if scroll has been restored to prevent multiple restorations
    const scrollRestoredRef = useRef(false);
    // Store whether we should restore scroll (computed once on mount)
    const shouldRestoreScrollRef = useRef(shouldRestoreScroll(navigationType) || restoreFeedIntentRef.current === true || cameFromViewPostRef.current === true);

    // Restore scroll position on back navigation or page refresh
    // Runs when stableOrder is populated (posts are ready to render)
    useEffect(() => {
        // Only restore scroll on POP navigation (back button or refresh)
        if (!shouldRestoreScrollRef.current) return;
        // Only restore once
        if (scrollRestoredRef.current) return;
        // Wait for posts to be loaded
        if (stableOrder.length === 0) return;

        try {
            const savedScrollRaw = sessionStorage.getItem(getFeedKey(urlTopic, 'scroll'));
            const fromSession = savedScrollRaw ? parseInt(savedScrollRaw, 10) : 0;
            const fromMem = Number(readMemFeedState(urlTopic)?.scroll || 0);
            const scrollY = (Number.isFinite(fromSession) && fromSession > 0)
                ? fromSession
                : ((Number.isFinite(fromMem) && fromMem > 0) ? fromMem : 0);

            if (scrollY > 0) {
                scrollRestoredRef.current = true;
                // Use multiple requestAnimationFrames to ensure DOM is fully rendered
                // This gives React time to commit all the post cards to the DOM
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        requestAnimationFrame(() => {
                            window.scrollTo(0, scrollY);
                        });
                    });
                });
            }
        } catch (_) { }
    }, [urlTopic, stableOrder.length]);

    // Listen for global hard refresh requests (from header)
    useEffect(() => {
        const handler = () => {
            try {
                forceHardRefreshRef.current = true;
                setIsLoading(true);
                setIsLoadingMore(false);
                try { loadMoreLockRef.current = false; } catch (_) { }
                setHasMorePosts(false);
                setCurrentPage(1);
                setStableOrder([]);
                // Refresh current visible topic
                getPosts(urlTopic, null, 1);
            } catch (_) { /* noop */ }
        };
        const applyBlockedTopic = (raw) => {
            const topic = String(raw || '').trim().toLowerCase();
            if (!topic) return;
            setBlockedTopicsLocal(prev => new Set([...prev, topic]));
            console.debug('[blocked_topics] optimistic pattern added', { topic });
        };
        const removeBlockedTopic = (raw) => {
            const topic = String(raw || '').trim().toLowerCase();
            if (!topic) return;
            setBlockedTopicsLocal(prev => {
                const next = new Set(prev);
                next.delete(topic);
                return next;
            });
            console.debug('[blocked_topics] optimistic pattern removed', { topic });
        };
        const onTopicBlocked = (e) => {
            applyBlockedTopic(e?.detail?.topic || '');
            handler();
        };
        const onTopicUnblocked = (e) => {
            removeBlockedTopic(e?.detail?.topic || '');
            handler();
        };
        window.addEventListener('mirageRefreshFeed', handler);
        window.addEventListener('topicBlocked', onTopicBlocked);
        window.addEventListener('topicUnblocked', onTopicUnblocked);
        return () => {
            window.removeEventListener('mirageRefreshFeed', handler);
            window.removeEventListener('topicBlocked', onTopicBlocked);
            window.removeEventListener('topicUnblocked', onTopicUnblocked);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [getPosts, urlTopic]);

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

            header = (
                <PostHeaderCard role="region" aria-label="Post context">
                    <PostHeaderText>
                        Posted in{' '}
                        <TopicLinkInHeader
                            to={`/t/${p.topic}`}
                            title={`View #${p.topic}`}
                        >
                            #{p.topic}
                        </TopicLinkInHeader>{' '}
                        (
                        <HeaderInlineLink
                            href="#"
                            onClick={async (e) => {
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
                                    setStableOrder((s) => s.slice());
                                } catch (_) { /* noop */ }
                            }}
                        >
                            {isTopicInProgress ? formatTopicStatus(topicKey) : (isTopicFollowing ? 'unfollow' : 'follow')}
                        </HeaderInlineLink>
                        )
                    </PostHeaderText>
                    <PostHeaderTitle>{p.title}</PostHeaderTitle>
                </PostHeaderCard>
            );
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
            const isTopLevelPost = (p) => {
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

            const filteredPosts = (displayTopic === "all" || displayTopic === "home" || displayTopic === "following")
                ? topLevelPosts
                : topLevelPosts.filter(post => String(post.topic || '').toLowerCase() === String(displayTopic || '').toLowerCase());

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
                    orderedPosts = stableOrder
                        .map((id) => postsById[id])
                        .filter(Boolean);
                } else {
                    orderedPosts = filteredPosts.filter((p) => p && !p.deleted);
                }

                // Hide posts the viewer downvoted (Home only, client-side)
                if (displayTopic === 'home' && hideDownvotedPosts) {
                    orderedPosts = orderedPosts.filter((p) => {
                        const postKey = String(p?.post_id || '').toLowerCase();
                        // If post is animating out, keep it in the list for now
                        if (hidingPostsSet.has(postKey)) return true;
                        // Prefer in-memory/state direction; backend provides user_vote on fetch.
                        const dir = Number(
                            p?.direction ?? p?.user_vote ?? p?.my_vote ?? p?.myVote ?? p?.userVote ?? 0
                        );
                        if (Number.isFinite(dir) && dir < 0) return false;
                        return true;
                    });
                }
            }
        }

        // Always render the full layout with sidebar and header
        const pageTitle = urlTopic === 'home' ? 'Home'
            : urlTopic === 'following' ? 'Following'
                : urlTopic === 'all' ? 'All Posts'
                    : `#${urlTopic}`;
        return (
            <ContentGrid>
                <Helmet>
                    <title>{pageTitle} | Mirage</title>
                </Helmet>
                <Sidebar currentPath={location.pathname} state={state} />
                <div>
                    {header}
                    <TopBar state={state} />

                    <ModernPostFeed>
                        <MobileHeader />

                        {isLoggedIn && isCurrentTopic && showHero && (
                            <TopicHeroCard>
                                <TopicHeroHeader>
                                    <TopicHeroTitle>#{urlTopic}</TopicHeroTitle>
                                    <HomeFeedModeInline>
                                        <HomeFeedModeSelect
                                            value={homeSortMode}
                                            onChange={(e) => {
                                                const mode = e.target.value;
                                                setHomeSortMode(mode);
                                                Storage.save('home_sort_mode', mode);
                                            }}
                                        >
                                            <option value="magic">Magic</option>
                                            <option value="newest">Newest</option>
                                        </HomeFeedModeSelect>
                                        <HomeFeedModeSelect
                                            value={cardSize}
                                            onChange={(e) => handleCardSizeChange(e.target.value)}
                                        >
                                            <option value="large">Large</option>
                                            {!isMobile && <option value="compact">Compact</option>}
                                            <option value="media">Media</option>
                                        </HomeFeedModeSelect>
                                        <Button
                                            variant={
                                                isTopicFollowing && topicFollowHover
                                                    ? 'primaryDanger'
                                                    : isTopicFollowing
                                                        ? 'subtle'
                                                        : 'primary'
                                            }
                                            size="xs"
                                            minWidth="5.5rem"
                                            onMouseEnter={() => setTopicFollowHover(true)}
                                            onMouseLeave={() => setTopicFollowHover(false)}
                                            disabled={isTopicInProgress}
                                            onClick={async () => {
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
                                                } catch (_) { /* noop */ }
                                            }}
                                        >
                                            {isTopicInProgress
                                                ? formatTopicStatus(topicKeyLower)
                                                : isTopicFollowing
                                                    ? (topicFollowHover ? 'Unfollow' : 'Following')
                                                    : 'Follow'}
                                        </Button>
                                    </HomeFeedModeInline>
                                </TopicHeroHeader>
                                <TopicHeroDescription>
                                    Topic feed for #{urlTopic}. Follow this community to stay up to date with the latest posts, discussions, and updates from people actively contributing to this topic.
                                </TopicHeroDescription>
                            </TopicHeroCard>
                        )}

                        {/* Invite-only banner - shown only when invite codes are enabled on this node */}
                        {isLoggedIn && showHero && inviteCodesEnabled && (urlTopic === 'home' || urlTopic === 'following') && (
                            <InviteOnlyBanner $size={cardSize} role="region" aria-label="Invite-only announcement">
                                <HomeFeedHeaderRow>
                                    <HomeFeedInfoTitle>
                                        <HomeFeedInfoEmoji>✨</HomeFeedInfoEmoji> Invite Codes
                                        {inviteBannerCollapsed && (
                                            <span style={{ fontWeight: 'normal' }}>
                                                {' '}{availableCodeCount === 0 ? '— None available' : `— ${availableCodeCount} ${availableCodeCount === 1 ? 'code' : 'codes'} left`}
                                            </span>
                                        )}
                                    </HomeFeedInfoTitle>
                                    <CollapseButton onClick={toggleInviteBanner}>
                                        {inviteBannerCollapsed ? 'Show' : 'Hide'}
                                    </CollapseButton>
                                </HomeFeedHeaderRow>
                                {!inviteBannerCollapsed && (
                                    <InviteBannerContentWrapper>
                                        <InviteBannerTextContent>
                                            <HomeFeedInfoDescription>
                                                Mirage is now invite-only — because great conversations require great people!
                                                {' '}{availableCodeCount > 0
                                                    ? "But don't fret, we've given you some invite codes for your friends. Use them wisely."
                                                    : "Unfortunately, you're out of invite codes. But don't worry, we might drop some more soon. Stay tuned!"}
                                            </HomeFeedInfoDescription>
                                        </InviteBannerTextContent>
                                        <InviteBannerButton onClick={handleOpenInviteModal} disabled={availableCodeCount === 0}>
                                            {availableCodeCount > 0 ? <>Share Invite Code <InviteBannerCount>({availableCodeCount} left)</InviteBannerCount></> : 'No Codes Left'}
                                        </InviteBannerButton>
                                    </InviteBannerContentWrapper>
                                )}
                            </InviteOnlyBanner>
                        )}

                        {/* Quest hero card - only when quests are enabled on this node */}
                        {isLoggedIn && questsEnabled && (urlTopic === 'home' || urlTopic === 'following') && (
                            <QuestHeroCard
                                collapsed={questCardCollapsed}
                                onToggleCollapse={toggleQuestCard}
                                size={cardSize}
                            />
                        )}

                        {/* Android app banner - shown once for Android users until dismissed */}
                        {showHero && showAndroidBanner && (
                            <AndroidAppHero role="region" aria-label="Android app available">
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
                            </AndroidAppHero>
                        )}

                        {showHero && showIPhoneBanner && (
                            <IPhoneAppHero role="region" aria-label="iPhone app available">
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
                            </IPhoneAppHero>
                        )}

                        {/* NSFW welcome hero - shown once for logged-in users until dismissed */}
                        {isLoggedIn && showHero && urlTopic === 'home' && showNsfwHero && (
                            <NsfwWelcomeHero role="region" aria-label="Content preferences">
                                <NsfwHeroTitle>
                                    <NsfwHeroEmoji>🔞</NsfwHeroEmoji> Allow Adult Content?
                                </NsfwHeroTitle>
                                <NsfwHeroDescription>
                                    Mirage is uncensored and includes adult content like <strong>pornography</strong>, <strong>violence</strong>, and other NSFW material. Would you like to see this content in your feed?
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
                                    You can change this anytime in <Link to="/settings" style={{ color: 'inherit', textDecoration: 'underline' }}>Settings</Link>.
                                </NsfwHeroNote>
                            </NsfwWelcomeHero>
                        )}

                        {/* Home feed info card - permanent for logged-in users (hidden while NSFW hero is shown) */}
                        {isLoggedIn && urlTopic === 'home' && !showNsfwHero && showHero && (
                            <HomeFeedInfoCard $size={cardSize} role="region" aria-label="Home feed information">
                                <HomeFeedHeaderRow>
                                    <HomeFeedInfoTitle>
                                        <HomeFeedInfoEmoji>🏠</HomeFeedInfoEmoji> Your Home Feed
                                    </HomeFeedInfoTitle>
                                    <HomeFeedModeInline>
                                        <HomeFeedModeSelect
                                            value={homeSortMode}
                                            onChange={(e) => {
                                                const mode = e.target.value;
                                                setHomeSortMode(mode);
                                                Storage.save('home_sort_mode', mode);
                                            }}
                                        >
                                            <option value="magic">Magic</option>
                                            <option value="newest">Newest</option>
                                        </HomeFeedModeSelect>
                                        <HomeFeedModeSelect
                                            value={cardSize}
                                            onChange={(e) => handleCardSizeChange(e.target.value)}
                                        >
                                            <option value="large">Large</option>
                                            {!isMobile && <option value="compact">Compact</option>}
                                            <option value="media">Media</option>
                                        </HomeFeedModeSelect>
                                    </HomeFeedModeInline>
                                </HomeFeedHeaderRow>
                                <HomeFeedInfoDescription>
                                    Your followed topics plus fresh content to discover. <strong>The more you vote, the more your feed reflects your preferences.</strong>
                                </HomeFeedInfoDescription>
                            </HomeFeedInfoCard>
                        )}

                        {/* Following feed info card - permanent for logged-in users */}
                        {isLoggedIn && urlTopic === 'following' && showHero && (
                            <HomeFeedInfoCard $size={cardSize} role="region" aria-label="Following feed information">
                                <HomeFeedHeaderRow>
                                    <HomeFeedInfoTitle>
                                        <HomeFeedInfoEmoji>👥</HomeFeedInfoEmoji> Your Following Feed
                                    </HomeFeedInfoTitle>
                                    <HomeFeedModeInline>
                                        <HomeFeedModeSelect
                                            value={homeSortMode}
                                            onChange={(e) => {
                                                const mode = e.target.value;
                                                setHomeSortMode(mode);
                                                Storage.save('home_sort_mode', mode);
                                            }}
                                        >
                                            <option value="magic">Magic</option>
                                            <option value="newest">Newest</option>
                                        </HomeFeedModeSelect>
                                        <HomeFeedModeSelect
                                            value={cardSize}
                                            onChange={(e) => handleCardSizeChange(e.target.value)}
                                        >
                                            <option value="large">Large</option>
                                            {!isMobile && <option value="compact">Compact</option>}
                                            <option value="media">Media</option>
                                        </HomeFeedModeSelect>
                                    </HomeFeedModeInline>
                                </HomeFeedHeaderRow>
                                <HomeFeedInfoDescription>
                                    <strong>Only posts from topics and people you follow.</strong> A focused view of your communities without discovery content.
                                </HomeFeedInfoDescription>
                            </HomeFeedInfoCard>
                        )}

                        {/* Loading state - only show to logged-in users */}
                        {isLoggedIn && showLoadingPosts && (
                            <LoadingCard $size={cardSize}>
                                <LoadingSpinner />
                                <LoadingText>Loading posts...</LoadingText>
                            </LoadingCard>
                        )}

                        {/* Empty home feed - only show to logged-in users */}
                        {isLoggedIn && showEmptyHome && <EmptyHomeMessage />}

                        {/* No posts available - only show to logged-in users */}
                        {isLoggedIn && showNoPostsAvailable && (
                            <LoadingCard $size={cardSize}>
                                <LoadingText>No posts available</LoadingText>
                            </LoadingCard>
                        )}

                        {/* Invite-only hero - shown to logged-out users on all feeds */}
                        {!isLoggedIn && (
                            <InviteOnlyHero role="region" aria-label="Welcome to Mirage">
                                <InviteOnlyHeroEmoji>✨</InviteOnlyHeroEmoji>
                                <InviteOnlyHeroTitle>Welcome to Mirage<sup style={{ fontSize: '0.5em', marginLeft: '0.3em', verticalAlign: 'super', opacity: 0.8 }}>BETA</sup></InviteOnlyHeroTitle>
                                <InviteOnlyHeroSubtitle>Currently in Private Beta — Invite Only</InviteOnlyHeroSubtitle>
                                <InviteOnlyHeroDescription>
                                    Mirage is a fully decentralized social network built on its own blockchain, designed to be 100% censorship resistant. Your posts, votes, and identity live on-chain — no central authority can silence you.
                                </InviteOnlyHeroDescription>
                                <InviteOnlyHeroDescription>
                                    <a href="https://mirage.foundation" target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'underline' }}>Learn more about our mission</a>
                                </InviteOnlyHeroDescription>
                                {welcomeStats && welcomeStats.userCount > 0 && (
                                    <WelcomeStatsGrid>
                                        <WelcomeStatItem>
                                            <WelcomeStatValue>{welcomeStatsStale ? '~' : ''}{welcomeStats.userCount.toLocaleString()}</WelcomeStatValue>
                                            <WelcomeStatLabel>Users</WelcomeStatLabel>
                                        </WelcomeStatItem>
                                        <WelcomeStatItem>
                                            <WelcomeStatValue>{welcomeStatsStale ? '~' : ''}{welcomeStats.active24h.toLocaleString()}</WelcomeStatValue>
                                            <WelcomeStatLabel>Active (24h)</WelcomeStatLabel>
                                        </WelcomeStatItem>
                                        <WelcomeStatItem>
                                            <WelcomeStatValue>{welcomeStatsStale ? '~' : ''}{(welcomeStats.posts24h + welcomeStats.comments24h).toLocaleString()}</WelcomeStatValue>
                                            <WelcomeStatLabel>Posts (24h)</WelcomeStatLabel>
                                        </WelcomeStatItem>
                                    </WelcomeStatsGrid>
                                )}
                                <InviteOnlyHeroDescription>
                                    Have an invite code? Join the community today.
                                </InviteOnlyHeroDescription>
                                <InviteOnlyHeroButtons>
                                    <Button to="/signup" size="md">
                                        Create Account
                                    </Button>
                                    <Button to="/login" variant="ghost" size="md">
                                        Sign In
                                    </Button>
                                </InviteOnlyHeroButtons>
                            </InviteOnlyHero>
                        )}

                        {/* Posts grid - only show to logged-in users */}
                        {isLoggedIn && !showLoadingPosts && !showEmptyHome && !showNoPostsAvailable && orderedPosts.length > 0 && (() => {
                            const family = getThemeFamily(state?.themeId);
                            const FeedComponent = family.Feed;
                            const visiblePosts = orderedPosts.filter((p) => {
                                const hasValidTitle = p && typeof p.title === 'string' && p.title.trim().length > 0;
                                const hasValidTopic = p && typeof p.topic === 'string' && p.topic.trim().length > 0;
                                return hasValidTitle && hasValidTopic && !p.deleted;
                            });
                            return (
                                <FeedComponent
                                    posts={visiblePosts}
                                    state={state}
                                    updatePost={updatePost}
                                    hidingPostsSet={hidingPostsSet}
                                    flashingPostsSet={flashingPostsSet}
                                    viewerAddress={viewerAddress}
                                    sortMode={oldRedditSort}
                                    onSortChange={handleOldRedditSortChange}
                                    showSortTabs={urlTopic === 'home' || urlTopic === 'following'}
                                />
                            );
                        })()}

                        {isLoggedIn && isLoadingMore && !showEmptyHome && !showNoPostsAvailable && (
                            <LoadingMoreIndicator>Loading more...</LoadingMoreIndicator>
                        )}
                        {isLoggedIn && (
                            <div ref={bottomSentinelRef} style={{ width: '100%', minHeight: '1px' }}>
                                {hasMorePosts && !isLoadingMore && !isLoading && !showEmptyHome && !showNoPostsAvailable && (
                                    <LoadMoreButton type="button" onClick={loadMore}>
                                        Load more
                                    </LoadMoreButton>
                                )}
                            </div>
                        )}
                    </ModernPostFeed>
                </div>

                {/* Invite Code Modal */}
                {inviteModalOpen && (
                    <InviteModalOverlay onClick={() => setInviteModalOpen(false)}>
                        <InviteModalContent onClick={(e) => e.stopPropagation()}>
                            <InviteModalHeader>
                                <InviteModalTitle>
                                    <span role="img" aria-label="sparkles">✨</span> Share Your Invite Code
                                </InviteModalTitle>
                                <InviteModalClose onClick={() => setInviteModalOpen(false)}>&times;</InviteModalClose>
                            </InviteModalHeader>

                            {nextAvailableCode ? (
                                <>
                                    <InviteCodeDisplay>
                                        <InviteCodeText>{nextAvailableCode.code}</InviteCodeText>
                                        <InviteCodeSubtext>Share this code with a friend to invite them</InviteCodeSubtext>
                                    </InviteCodeDisplay>

                                    <InviteShareButtons>
                                        <InviteCopyButton onClick={handleCopyInviteCode}>
                                            {inviteCodeCopied ? '✓ Copied!' : 'Copy Invite Link'}
                                        </InviteCopyButton>
                                        {canNativeShare && (
                                            <InviteNativeShareButton onClick={handleNativeShare}>
                                                <span role="img" aria-label="share">📤</span> Share via...
                                            </InviteNativeShareButton>
                                        )}
                                    </InviteShareButtons>
                                    <InviteDesktopShareButtons>
                                        <InviteShareButton
                                            as="a"
                                            href={`https://twitter.com/intent/tweet?text=${encodeURIComponent(getShareText())}&url=${encodeURIComponent(getShareUrl())}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                        >
                                            <span role="img" aria-label="X">𝕏</span> Twitter/X
                                        </InviteShareButton>
                                        <InviteShareButton
                                            as="a"
                                            href={`https://t.me/share/url?url=${encodeURIComponent(getShareUrl())}&text=${encodeURIComponent(getShareText())}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                        >
                                            <span role="img" aria-label="telegram">📨</span> Telegram
                                        </InviteShareButton>
                                        <InviteShareButton
                                            as="a"
                                            href={`https://wa.me/?text=${encodeURIComponent(getShareText() + ' ' + getShareUrl())}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                        >
                                            <span role="img" aria-label="whatsapp">💬</span> WhatsApp
                                        </InviteShareButton>
                                        <InviteShareButton
                                            as="a"
                                            href={`mailto:?subject=${encodeURIComponent('Join me on Mirage!')}&body=${encodeURIComponent(getShareText() + '\n\n' + getShareUrl())}`}
                                        >
                                            <span role="img" aria-label="email">📧</span> Email
                                        </InviteShareButton>
                                    </InviteDesktopShareButtons>

                                    <InviteRemainingText>
                                        You have {availableCodeCount} invite{availableCodeCount !== 1 ? 's' : ''} remaining
                                    </InviteRemainingText>
                                </>
                            ) : (
                                <InviteNoCodesText>
                                    You don't have any invite codes available. Check back later!
                                </InviteNoCodesText>
                            )}
                        </InviteModalContent>
                    </InviteModalOverlay>
                )}
            </ContentGrid>
        );
    };

    return showPosts();
};

export default MainView;
