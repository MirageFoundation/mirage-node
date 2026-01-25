import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Helmet } from 'react-helmet-async';
import styled, { keyframes, css, useTheme } from 'styled-components';
import { useLocation, useSearchParams } from 'react-router-dom';
import { bech32 } from 'bech32';
import Storage from '../utils/Storage';
import Api from '../lib/api';
import Sidebar from '../components/Sidebar';
import TopBar from '../components/TopBar';
import Button from '../components/Button';
import MobileHeader from '../components/MobileHeader';
import { ContentGrid, ModernPostFeed, TabbedContainer, TabsRow, ClickableTab, ContainerBody } from '../styled/Layout';
import { tooltipStyles } from '../components/Tooltip';
import { ibcTransfer, bridgeBurn, pollTxStatus } from '../utils/tx';

// Lazy import for Solana bridge - only loads when needed
const loadSolanaBridge = () => import('../utils/solanaBridge');

// Convert a bech32 address from one prefix to another (e.g., mirage1... -> osmo1...)
const convertBech32Prefix = (address, newPrefix) => {
    try {
        const decoded = bech32.decode(address);
        return bech32.encode(newPrefix, decoded.words);
    } catch (e) {
        return null;
    }
};

// Network configurations - static metadata for supported bridge destinations
const NETWORKS = {
    osmosis: {
        id: 'osmosis',
        name: 'Osmosis',
        symbol: 'OSMO',
        icon: '/images/bridges/osmosis.svg',
        color: '#5E12A0',
        colorLight: 'rgba(94, 18, 160, 0.15)',
        addressPrefix: 'osmo',
        addressLength: 43,
        estimatedTime: '~30 seconds',
        minAmount: 1,
        enabled: true,
        canDerive: true, // Same key derives address on this chain
        isIbc: true,
        ibcChannel: 'channel-0', // IBC channel to Osmosis
    },
    solana: {
        id: 'solana',
        name: 'Solana',
        symbol: 'SOL',
        icon: '/images/bridges/solana.svg',
        color: '#14F195',
        colorLight: 'rgba(20, 241, 149, 0.15)',
        addressPrefix: null, // Solana uses base58, not bech32
        addressLength: 44,
        estimatedTime: '~2-5 minutes',
        minAmount: 10,
        enabled: true,
        canDerive: false, // Different cryptography, no derived address
        isIbc: false,
    },
};

// Polling schedule: 1s for first 30s, then 2s for 30-60s, then 3s after
const BRIDGE_POLL_SCHEDULE = {
    initialDelayMs: 1000,
    intervalsMs: [
        ...Array.from({ length: 30 }, () => 1000),  // 0-30s: every 1s
        ...Array.from({ length: 15 }, () => 2000),  // 30-60s: every 2s
        ...Array.from({ length: 20 }, () => 3000),  // 60-120s: every 3s
    ],
};

// Bridge status polling schedule for Bridge Out (Mirage -> external)
// First poll at 10s, then every 2.5s until 60s, then every 5s. Timeout at 120s.
const BRIDGE_OUT_STATUS_POLL_SCHEDULE = {
    initialDelayMs: 10000, // Wait 10s before first poll (validators need time to detect burn and attest)
    intervalsMs: [
        ...Array.from({ length: 20 }, () => 2500),  // 10-60s: every 2.5s (20 * 2.5s = 50s)
        ...Array.from({ length: 12 }, () => 5000),  // 60-120s: every 5s (12 * 5s = 60s)
    ],
};

const formatAttestationPower = (attestedPower, requiredPower, thresholdBps) => {
    const required = Number(requiredPower) || 0;
    const threshold = Number(thresholdBps) || 0;
    if (required <= 0 || threshold <= 0) return '';
    const thresholdPercent = threshold / 100;
    const percentOfTotal = Math.min(100, (Number(attestedPower) || 0) / required * thresholdPercent);
    return `${percentOfTotal.toFixed(1)}% power, need ${thresholdPercent.toFixed(1)}%`;
};

// Truncate long addresses for mobile display
const truncateAddress = (addr, startChars = 10, endChars = 6) => {
    if (!addr) return '';
    if (addr.length <= startChars + endChars + 3) return addr;
    return `${addr.slice(0, startChars)}...${addr.slice(-endChars)}`;
};

// Responsive address component - shows truncated on mobile, full on desktop
const ResponsiveAddress = ({ address, startChars = 16, endChars = 6 }) => {
    if (!address) return null;
    const truncated = truncateAddress(address, startChars, endChars);
    return (
        <>
            <span className="address-full">{address}</span>
            <span className="address-truncated">{truncated}</span>
        </>
    );
};


// Animations
const fadeIn = keyframes`
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
`;

// Styled Components
const BridgeContainer = styled.div`
    animation: ${fadeIn} 0.3s ease-out;
`;

// Full width layout
const BridgeLayout = styled.div`
    width: 100%;
`;

// Balance banner at the top of Bridge Out
const BalanceBanner = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: ${({ theme }) => theme?.colors?.panel || '#23272C'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 10px;
    padding: 0.75rem 1rem;
    margin-bottom: 1.25rem;
`;

const BalanceBannerLabel = styled.span`
    font-size: 0.75rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-weight: 500;
`;

const BalanceBannerRight = styled.div`
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.1rem;
`;

const BalanceBannerValue = styled.span`
    font-size: 1.1rem;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    font-weight: 700;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    display: flex;
    align-items: baseline;
    gap: 0.35rem;
`;

const BalanceBannerSuffix = styled.span`
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-weight: 500;
`;

const BalanceBannerNetwork = styled.span`
    font-size: 0.65rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    text-transform: uppercase;
    letter-spacing: 0.5px;
`;

const BalanceBannerError = styled.span`
    font-size: 0.75rem;
    color: #f56565;
    cursor: pointer;
    &:hover {
        text-decoration: underline;
    }
`;

const SectionTitle = styled.h3`
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    margin: 0 0 0.75rem 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

const StepNumber = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.1rem;
    height: 1.1rem;
    border-radius: 50%;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: #fff;
    font-size: 0.6rem;
    font-weight: 700;
`;

const NetworkGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.75rem;
    margin-bottom: 1rem;
    
    @media (max-width: 600px) {
        grid-template-columns: 1fr;
    }
`;

const NetworkCard = styled.button`
    background: ${({ theme, $selected, $color }) =>
        $selected
            ? `linear-gradient(135deg, ${$color}22 0%, ${$color}11 100%)`
            : (theme?.colors?.panel || '#23272C')};
    border: 2px solid ${({ $selected, $color, theme }) =>
        $selected ? $color : (theme?.colors?.border || '#444')};
    border-radius: 10px;
    padding: 0.85rem;
    cursor: pointer;
    transition: all 0.2s ease;
    text-align: left;
    position: relative;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    
    &:hover:not(:disabled) {
        border-color: ${({ $color }) => $color};
        transform: translateY(-2px);
        box-shadow: 0 4px 12px ${({ $color }) => `${$color}33`};
    }
    
    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    ${({ $selected, $color }) => $selected && css`
        box-shadow: 0 0 0 1px ${$color}44, 0 4px 12px ${$color}22;
    `}
`;

const NetworkCardContent = styled.div`
    flex: 1;
    min-width: 0;
`;

const NetworkIcon = styled.img`
    width: 2.5rem;
    height: 2.5rem;
    flex-shrink: 0;
    object-fit: contain;
`;

const NetworkName = styled.div`
    font-size: 0.9rem;
    font-weight: 700;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    margin-bottom: 0.2rem;
`;

const NetworkMeta = styled.div`
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    display: flex;
    align-items: center;
    gap: 0.35rem;
`;

const NetworkBadge = styled.span`
    display: inline-flex;
    align-items: center;
    padding: 0.15rem 0.4rem;
    border-radius: 4px;
    font-size: 0.6rem;
    font-weight: 600;
    background: ${({ $color }) => `${$color}22`};
    color: ${({ $color }) => $color};
`;

const SelectedIndicator = styled.div`
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
    width: 1rem;
    height: 1rem;
    border-radius: 50%;
    background: ${({ $color }) => $color};
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.6rem;
    color: #fff;
    animation: ${fadeIn} 0.2s ease-out;
`;

const InputSection = styled.div`
    margin-bottom: 1.5rem;
`;

const InputLabel = styled.label`
    display: block;
    font-size: 0.75rem;
    font-weight: 600;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    margin-bottom: 0.5rem;
`;

const InputWrapper = styled.div`
    position: relative;
    display: flex;
    align-items: center;
`;

const AmountInput = styled.input`
    width: 100%;
    padding: 0.65rem 5rem 0.65rem 0.85rem;
    border: 1px solid ${({ theme, $error }) =>
        $error ? '#f56565' : (theme?.colors?.border || '#444')};
    border-radius: 8px;
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    font-size: 1rem;
    font-weight: 600;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    outline: none;
    transition: all 0.2s ease;
    
    &::placeholder {
        color: ${({ theme }) => theme?.colors?.subtleText || '#666'};
        font-weight: 400;
    }
    
    &:focus {
        border-color: ${({ theme, $error }) =>
        $error ? '#f56565' : (theme?.colors?.link || '#667eea')};
        box-shadow: 0 0 0 3px ${({ $error }) =>
        $error ? 'rgba(245, 101, 101, 0.2)' : 'rgba(102, 126, 234, 0.2)'};
    }
    
    /* Hide number spinners */
    &::-webkit-outer-spin-button,
    &::-webkit-inner-spin-button {
        -webkit-appearance: none;
        margin: 0;
    }
    -moz-appearance: textfield;
`;

const AmountSuffix = styled.span`
    position: absolute;
    right: 0.85rem;
    font-size: 0.8rem;
    font-weight: 600;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    pointer-events: none;
`;

const MaxButton = styled.button`
    position: absolute;
    right: 4.5rem;
    padding: 0.25rem 0.5rem;
    border: none;
    border-radius: 4px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: #fff;
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    cursor: pointer;
    transition: all 0.2s ease;
    
    &:hover {
        transform: scale(1.05);
        box-shadow: 0 2px 8px rgba(102, 126, 234, 0.4);
    }
`;

const AddressInput = styled.input`
    width: 100%;
    padding: 0.65rem 0.85rem;
    border: 1px solid ${({ theme, $error }) =>
        $error ? '#f56565' : (theme?.colors?.border || '#444')};
    border-radius: 8px;
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    font-size: 0.85rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    outline: none;
    transition: all 0.2s ease;
    
    &::placeholder {
        color: ${({ theme }) => theme?.colors?.subtleText || '#666'};
        font-family: inherit;
    }
    
    &:focus {
        border-color: ${({ theme, $error }) =>
        $error ? '#f56565' : (theme?.colors?.link || '#667eea')};
        box-shadow: 0 0 0 3px ${({ $error }) =>
        $error ? 'rgba(245, 101, 101, 0.2)' : 'rgba(102, 126, 234, 0.2)'};
    }
`;

const ErrorText = styled.div`
    color: #f56565;
    font-size: 0.7rem;
    margin-top: 0.35rem;
    display: flex;
    align-items: center;
    gap: 0.25rem;
`;

const PreviewCard = styled.div`
    background: linear-gradient(135deg, 
        ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'} 0%, 
        ${({ theme }) => theme?.colors?.panel || '#23272C'} 100%);
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 10px;
    padding: 1rem;
    margin-bottom: 1rem;
`;

const PreviewHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.75rem;
    padding-bottom: 0.6rem;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
`;

const PreviewTitle = styled.span`
    font-size: 0.8rem;
    font-weight: 600;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
`;

const PreviewNetwork = styled.span`
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.75rem;
    color: ${({ $color }) => $color};
    font-weight: 600;
`;

const PreviewRow = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.35rem 0;
    font-size: 0.8rem;
    gap: 1rem;
`;

const PreviewLabel = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    white-space: nowrap;
    flex-shrink: 0;
`;

const PreviewValue = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    font-weight: 500;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    text-align: right;
    white-space: nowrap;
    
    ${({ $highlight }) => $highlight && css`
        color: #48bb78;
        font-weight: 700;
    `}
`;

const Divider = styled.div`
    height: 1px;
    background: ${({ theme }) => theme?.colors?.border || '#444'};
    margin: 0.5rem 0;
`;

const SubmitSection = styled.div`
    margin-top: 0;
`;

const WarningBanner = styled.div`
    display: flex;
    align-items: flex-start;
    gap: 0.6rem;
    padding: 0.75rem;
    margin-bottom: 1rem;
    background: rgba(245, 158, 11, 0.1);
    border: 1px solid rgba(245, 158, 11, 0.3);
    border-radius: 8px;
    font-size: 0.75rem;
    color: #f59e0b;
    line-height: 1.5;
`;

const WarningIcon = styled.span`
    font-size: 0.85rem;
    flex-shrink: 0;
`;

const InfoBanner = styled.div`
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    padding: 0.85rem;
    margin-bottom: 1rem;
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    font-size: 0.75rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    line-height: 1.5;
`;

const InfoIcon = styled.span`
    font-size: 0.85rem;
    flex-shrink: 0;
`;

const StatusBanner = styled.div`
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    padding: 0.75rem;
    margin-top: 0.75rem;
    background: ${({ $success, $error }) =>
        $success ? 'rgba(72, 187, 120, 0.1)' :
            $error ? 'rgba(239, 68, 68, 0.1)' : 'rgba(102, 126, 234, 0.1)'};
    border: 1px solid ${({ $success, $error }) =>
        $success ? 'rgba(72, 187, 120, 0.3)' :
            $error ? 'rgba(239, 68, 68, 0.3)' : 'rgba(102, 126, 234, 0.3)'};
    border-radius: 8px;
    font-size: 0.8rem;
    color: ${({ $success, $error }) =>
        $success ? '#48bb78' :
            $error ? '#ef4444' : '#667eea'};
    font-weight: 500;
    animation: ${fadeIn} 0.3s ease-out;
`;

const StepsCard = styled.div`
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 10px;
    padding: 0.85rem;
    margin-top: 0.75rem;
    margin-bottom: 0.75rem;
`;

const StepsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
`;

const StepItem = styled.div`
    display: flex;
    align-items: center;
    gap: 0.6rem;
    font-size: 0.8rem;
`;

const StepDot = styled.span`
    width: 0.65rem;
    height: 0.65rem;
    border-radius: 50%;
    flex-shrink: 0;
    background: ${({ $state, theme }) => {
        if ($state === 'complete') return '#48bb78';
        if ($state === 'active') return '#667eea';
        if ($state === 'error') return '#ef4444';
        return theme?.colors?.border || '#555';
    }};
    box-shadow: ${({ $state }) => $state === 'active' ? '0 0 0 3px rgba(102, 126, 234, 0.2)' : 'none'};
`;

const StepText = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
`;

const StepTitle = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    font-weight: 600;
`;

const StepMeta = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.7rem;
    
    a {
        color: ${({ theme }) => theme?.colors?.link || '#667eea'};
    }
    
    /* Responsive address display */
    .address-full {
        display: inline;
    }
    .address-truncated {
        display: none;
    }
    
    @media (max-width: 768px) {
        .address-full {
            display: none;
        }
        .address-truncated {
            display: inline;
        }
    }
`;

// Progress Screen Components (full-screen progress view after submit)
const ProgressScreenContainer = styled.div`
    animation: ${fadeIn} 0.3s ease-out;
    padding: 0.5rem 0;
`;

const ProgressScreenHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.25rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
`;

const ProgressScreenTitle = styled.div`
    display: flex;
    align-items: center;
    gap: 0.75rem;
`;

const ProgressScreenNetworkIcon = styled.img`
    width: 2rem;
    height: 2rem;
    border-radius: 50%;
    ${({ $isMirage, theme }) => $isMirage && `
        filter: brightness(0) ${theme?.isDark === false ? 'invert(0)' : 'invert(1)'};
    `}
`;

const ProgressScreenTitleText = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
`;

const ProgressScreenMainTitle = styled.span`
    font-size: 1rem;
    font-weight: 700;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
`;

const ProgressScreenSubtitle = styled.span`
    font-size: 0.75rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

const ProgressScreenAmount = styled.div`
    text-align: right;
`;

const ProgressScreenAmountValue = styled.div`
    font-size: 1.1rem;
    font-weight: 700;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
`;

const ProgressScreenAmountLabel = styled.div`
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

const BalanceComparisonCard = styled.div`
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 10px;
    padding: 1rem;
    margin-top: 1rem;
`;

const BalanceComparisonTitle = styled.div`
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    margin-bottom: 0.75rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

const BalanceComparisonGrid = styled.div`
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
    
    @media (max-width: 500px) {
        grid-template-columns: 1fr;
    }
`;

const BalanceComparisonColumn = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
`;

const BalanceComparisonNetwork = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.8rem;
    font-weight: 600;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    margin-bottom: 0.25rem;
`;

const BalanceComparisonNetworkIcon = styled.img`
    width: 1rem;
    height: 1rem;
    border-radius: 50%;
    ${({ $isMirage, theme }) => $isMirage && `
        filter: brightness(0) ${theme?.isDark === false ? 'invert(0)' : 'invert(1)'};
    `}
`;

const BalanceComparisonRow = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.8rem;
    padding: 0.35rem 0;
    border-bottom: 1px solid ${({ theme }) => theme?.colors?.border || '#333'};
    
    &:last-child {
        border-bottom: none;
    }
`;

const BalanceComparisonLabel = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

const BalanceComparisonValue = styled.span`
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-weight: 500;
    color: ${({ theme, $highlight, $dim }) =>
        $highlight ? '#48bb78' :
            $dim ? (theme?.colors?.subtleText || '#888') :
                (theme?.colors?.text || '#fff')};
`;

// Derived address display
const DerivedAddressBox = styled.div`
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    padding: 0.65rem 0.85rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.8rem;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    word-break: break-all;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
`;

const AddressText = styled.span`
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const DifferentAddressToggle = styled.button`
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    background: none;
    border: none;
    color: ${({ theme }) => theme?.colors?.link || '#667eea'};
    font-size: 0.7rem;
    font-weight: 500;
    cursor: pointer;
    padding: 0;
    margin-top: 0.5rem;
    
    &:hover {
        text-decoration: underline;
    }
`;

const HelpIconWrapper = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1rem;
    height: 1rem;
    border-radius: 50%;
    background: ${({ theme }) => theme?.colors?.border || '#444'};
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.6rem;
    font-weight: 700;
    cursor: help;
    margin-left: 0.35rem;
    ${tooltipStyles('top')}
`;

const AddressExplanation = styled.div`
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    padding: 0.6rem 0.75rem;
    margin-bottom: 0.75rem;
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 8px;
    font-size: 0.7rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    line-height: 1.5;
`;

const ExplanationIcon = styled.span`
    font-size: 0.75rem;
    flex-shrink: 0;
`;

// Source network configurations for Bridge In (where tokens come FROM)
const SOURCE_NETWORKS = {
    osmosis: {
        id: 'osmosis',
        name: 'Osmosis',
        symbol: 'OSMO',
        icon: '/images/bridges/osmosis.svg',
        color: '#5E12A0',
        colorLight: 'rgba(94, 18, 160, 0.15)',
        addressPrefix: 'osmo',
        estimatedTime: '~30 seconds',
        enabled: true,
        isIbc: true,
        ibcChannel: 'channel-???', // Channel from Osmosis to Mirage (user needs to look this up)
    },
    solana: {
        id: 'solana',
        name: 'Solana',
        symbol: 'SOL',
        icon: '/images/bridges/solana.svg',
        color: '#14F195',
        colorLight: 'rgba(20, 241, 149, 0.15)',
        estimatedTime: '~2-5 minutes',
        enabled: true,
        isIbc: false,
    },
};

// Copy button component for addresses
const CopyButton = styled.button`
    background: ${({ theme }) => theme?.colors?.panelAlt || '#2a2e33'};
    border: 1px solid ${({ theme }) => theme?.colors?.border || '#444'};
    border-radius: 4px;
    padding: 0.35rem 0.5rem;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.65rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    display: flex;
    align-items: center;
    gap: 0.25rem;
    flex-shrink: 0;
    
    &:hover {
        background: ${({ theme }) => theme?.colors?.border || '#444'};
        color: ${({ theme }) => theme?.colors?.text || '#fff'};
    }
`;

const ConfirmButtonRow = styled.div`
    display: flex;
    gap: 0.75rem;
    margin-top: 0.75rem;
`;

const ConfirmButton = styled.button`
    flex: 1;
    padding: 0.6rem 1rem;
    border: 2px solid ${({ $variant }) => $variant === 'yes' ? '#48bb78' : '#f59e0b'};
    border-radius: 8px;
    background: ${({ $variant, $selected }) =>
        $selected
            ? ($variant === 'yes' ? 'rgba(72, 187, 120, 0.2)' : 'rgba(245, 158, 11, 0.2)')
            : 'transparent'};
    color: ${({ $variant }) => $variant === 'yes' ? '#48bb78' : '#f59e0b'};
    font-size: 0.8rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    
    &:hover {
        background: ${({ $variant }) => $variant === 'yes' ? 'rgba(72, 187, 120, 0.15)' : 'rgba(245, 158, 11, 0.15)'};
    }
`;

// Solana wallet button
const SolanaWalletButton = styled.button`
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    width: 100%;
    padding: 0.75rem 1rem;
    border: 2px solid #14F195;
    border-radius: 8px;
    background: rgba(20, 241, 149, 0.1);
    color: #14F195;
    font-size: 0.9rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    
    &:hover:not(:disabled) {
        background: rgba(20, 241, 149, 0.2);
        transform: translateY(-1px);
    }
    
    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    img {
        width: 1.25rem;
        height: 1.25rem;
    }
`;

const ConnectedWalletBox = styled.div`
    background: ${({ theme }) => theme?.colors?.panelAlt || '#1f2328'};
    border: 1px solid #14F195;
    border-radius: 8px;
    padding: 0.75rem;
`;

const WalletRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
`;

const WalletAddress = styled.span`
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: 0.8rem;
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
`;

const DisconnectButton = styled.button`
    background: transparent;
    border: none;
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
    font-size: 0.7rem;
    cursor: pointer;
    padding: 0.25rem 0.5rem;
    
    &:hover {
        color: #f56565;
    }
`;

// Solana RPC endpoints
const SOLANA_RPC_DEVNET = 'https://api.devnet.solana.com';
const SOLANA_RPC_MAINNET = 'https://api.mainnet-beta.solana.com';

// Bridge status polling schedule for Bridge In (Solana -> Mirage)
// First poll at 10s, then every 2.5s until 60s, then every 5s. Timeout at 120s.
const BRIDGE_IN_STATUS_POLL_SCHEDULE = {
    initialDelayMs: 10000, // Wait 10s before first poll (orchestrators need time to detect burn and attest)
    intervalsMs: [
        ...Array.from({ length: 20 }, () => 2500),  // 10-60s: every 2.5s (20 * 2.5s = 50s)
        ...Array.from({ length: 12 }, () => 5000),  // 60-120s: every 5s (12 * 5s = 60s)
    ],
};

// Solana Bridge In Flow Component
function SolanaBridgeInFlow({ mirageAddress, theme, chainConfigs, attestationThresholdBps, onBridgingChange }) {
    const [solanaWallet, setSolanaWallet] = useState(null); // { address, mirageBalance, solBalance }
    const [isConnecting, setIsConnecting] = useState(false);
    const [amount, setAmount] = useState('');
    const [isBridging, setIsBridging] = useState(false);
    const [bridgeStatus, setBridgeStatus] = useState('idle'); // idle | confirming | pending | complete | error
    const [bridgeError, setBridgeError] = useState('');
    const [bridgeTxHash, setBridgeTxHash] = useState('');
    const [burnNonce, setBurnNonce] = useState(null);
    const [mirageBalance, setMirageBalance] = useState(null); // Mirage network balance

    // Step tracking for progress UI
    const [stepTimestamps, setStepTimestamps] = useState({});
    const [stepElapsed, setStepElapsed] = useState({});
    const [mintStatus, setMintStatus] = useState({ state: 'idle', txHash: '', error: '' });
    const [attestationProgress, setAttestationProgress] = useState({
        attestorCount: 0,
        attestedPower: 0,
        requiredPower: 0,
        confirmed: false,
    });
    const buttonRef = useRef(null);

    // Pre-bridge balance tracking for progress screen
    const [preBridgeSolanaBalance, setPreBridgeSolanaBalance] = useState(null);
    const [bridgeAmount, setBridgeAmount] = useState(''); // Store amount at bridge time

    const refreshMirageBalance = useCallback(async (reason = 'init') => {
        if (!mirageAddress) {
            setMirageBalance(null);
            console.debug('[Solana Bridge] Mirage balance fetch skipped (no address)');
            return;
        }
        console.debug('[Solana Bridge] Fetching Mirage balance', { address: mirageAddress, reason });
        try {
            const data = await Api.get(
                'get_user_status',
                { address: mirageAddress, _cb: Date.now() },
                {
                    timeoutMs: 10000,
                    headers: {
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache',
                    },
                }
            );
            const balanceVal = Number(data?.balance);
            if (!Number.isFinite(balanceVal)) {
                throw new Error('Invalid balance from get_user_status');
            }
            setMirageBalance(balanceVal);
            console.debug('[Solana Bridge] Mirage balance updated', { balance: balanceVal });
        } catch (e) {
            console.error('[Solana Bridge] Mirage balance fetch failed:', e);
        }
    }, [mirageAddress]);

    useEffect(() => {
        refreshMirageBalance('init');
    }, [refreshMirageBalance]);

    useEffect(() => {
        if (bridgeStatus !== 'complete') return;
        refreshMirageBalance('minted');
    }, [bridgeStatus, refreshMirageBalance]);

    // Scroll to button when bridge status changes from idle
    useEffect(() => {
        if (bridgeStatus === 'idle') return;
        if (!buttonRef.current) return;
        try {
            buttonRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' });
        } catch (_) { }
    }, [bridgeStatus]);

    // Notify parent when bridging status changes
    useEffect(() => {
        if (onBridgingChange) {
            onBridgingChange(bridgeStatus !== 'idle');
        }
    }, [bridgeStatus, onBridgingChange]);

    // Get Solana config from chainConfigs
    const solanaConfig = chainConfigs?.solana || {};
    const solanaCluster = solanaConfig.solana_cluster || 'devnet';
    const solanaTokenAddress = solanaConfig.solana_token_address || '';
    const solanaRpcUrl = solanaCluster === 'mainnet' ? SOLANA_RPC_MAINNET : SOLANA_RPC_DEVNET;
    const solscanClusterParam = solanaCluster === 'devnet' ? '?cluster=devnet' : '';

    // Update elapsed times every 100ms while actively processing
    useEffect(() => {
        if (bridgeStatus === 'idle' || bridgeStatus === 'error' || bridgeStatus === 'complete') return;

        const stepOrder = ['confirming', 'pending', 'complete'];
        const currentStepIdx = stepOrder.indexOf(bridgeStatus);

        const interval = setInterval(() => {
            const now = Date.now();
            setStepElapsed(prev => {
                const newElapsed = { ...prev };
                for (const [step, startTime] of Object.entries(stepTimestamps)) {
                    const stepIdx = stepOrder.indexOf(step);
                    // Only update elapsed time for current or future steps
                    // For completed steps, freeze at when next step started
                    if (stepIdx < currentStepIdx) {
                        const nextStep = stepOrder[stepIdx + 1];
                        const nextStepStart = stepTimestamps[nextStep];
                        if (nextStepStart) {
                            newElapsed[step] = (nextStepStart - startTime) / 1000;
                        }
                    } else {
                        newElapsed[step] = (now - startTime) / 1000;
                    }
                }
                return newElapsed;
            });
        }, 100);

        return () => clearInterval(interval);
    }, [bridgeStatus, stepTimestamps]);

    // Poll for mint confirmation on Mirage after Solana burn is confirmed
    useEffect(() => {
        if (bridgeStatus !== 'pending' || burnNonce === null) return;

        let cancelled = false;
        const maxAttempts = BRIDGE_IN_STATUS_POLL_SCHEDULE.intervalsMs.length + 1;
        const initialDelayMs = BRIDGE_IN_STATUS_POLL_SCHEDULE.initialDelayMs;
        let attestationFoundTime = null; // Track when we first see found=true

        setMintStatus({ state: 'pending', txHash: '', error: '' });
        setAttestationProgress({
            attestorCount: 0,
            attestedPower: 0,
            requiredPower: 0,
            confirmed: false,
        });

        const poll = async (attempt) => {
            if (cancelled) return;
            try {
                console.debug('[Solana Bridge In] Status poll attempt', attempt, 'of', maxAttempts, 'burn_sequence:', burnNonce);

                // Query bridge status (includes attestor count)
                const res = await fetch(`/api/bridge/status?burn_sequence=${burnNonce}&chain=solana`);
                if (!res.ok) {
                    throw new Error(`status query failed (${res.status})`);
                }
                const data = await res.json();
                console.debug('[Solana Bridge In] Bridge status response:', data);

                // Track when attestation is first found (orchestrator detected the burn)
                if (data.found && !attestationFoundTime) {
                    attestationFoundTime = Date.now();
                    // Freeze the "Validator attestations" step timer
                    setStepElapsed(prev => {
                        const pendingStart = stepTimestamps.pending;
                        if (pendingStart) {
                            return { ...prev, pending: (attestationFoundTime - pendingStart) / 1000 };
                        }
                        return prev;
                    });
                    console.debug('[Solana Bridge In] Attestation found, starting mint timer');
                }

                // Update attestation progress from status response
                if (data.found) {
                    setAttestationProgress(prev => ({
                        ...prev,
                        attestorCount: data.attestor_count || prev.attestorCount,
                        attestedPower: data.attested_power ?? prev.attestedPower,
                        requiredPower: data.required_power ?? prev.requiredPower,
                        confirmed: data.confirmed || prev.confirmed,
                    }));
                }

                if (data.confirmed) {
                    setMintStatus({ state: 'minted', txHash: data.mint_tx || '', error: '' });
                    // Calculate final elapsed time for the 'complete' (mint) step
                    const now = Date.now();
                    const mintStartTime = attestationFoundTime || stepTimestamps.pending || now;
                    setStepTimestamps(prev => ({ ...prev, complete: now }));
                    setStepElapsed(prev => ({
                        ...prev,
                        complete: (now - mintStartTime) / 1000,
                    }));
                    setBridgeStatus('complete');
                    return;
                }
            } catch (e) {
                console.debug('[Solana Bridge In] Status poll error:', e.message);
            }

            if (attempt >= maxAttempts) {
                setMintStatus({ state: 'timeout', txHash: '', error: 'Confirmation taking longer than expected' });
                return;
            }

            const nextDelay = BRIDGE_IN_STATUS_POLL_SCHEDULE.intervalsMs[attempt - 1] || 60000;
            console.debug('[Solana Bridge In] Status poll next delay (ms):', nextDelay);
            setTimeout(() => poll(attempt + 1), nextDelay);
        };

        if (initialDelayMs > 0) {
            setTimeout(() => poll(1), initialDelayMs);
        } else {
            poll(1);
        }

        return () => { cancelled = true; };
    }, [bridgeStatus, burnNonce, stepTimestamps.pending]);

    // Format step time for display
    const formatStepTime = (step) => {
        const elapsed = stepElapsed[step];
        if (elapsed === undefined) return '';
        return ` (${elapsed.toFixed(1)}s)`;
    };

    const attestationPowerText = formatAttestationPower(
        attestationProgress.attestedPower,
        attestationProgress.requiredPower,
        attestationThresholdBps
    );

    // Get step state for styling
    const getStepState = (step) => {
        if (bridgeStatus === 'idle') return 'pending';

        const stepOrder = ['confirming', 'pending', 'complete'];
        const currentIdx = stepOrder.indexOf(bridgeStatus);
        const stepIdx = stepOrder.indexOf(step);

        if (bridgeStatus === 'error') {
            // Find which step had the error
            if (stepIdx < currentIdx) return 'complete';
            if (stepIdx === currentIdx) return 'error';
            return 'pending';
        }

        // When bridgeStatus is 'complete', all steps are complete
        if (bridgeStatus === 'complete') return 'complete';

        if (stepIdx < currentIdx) return 'complete';
        if (stepIdx === currentIdx) return 'active';
        return 'pending';
    };

    // Format number with thousands separators for display
    const formatAmountDisplay = (value) => {
        if (!value || value === '') return '';
        const raw = String(value).replace(/,/g, '');
        const parts = raw.split('.');
        parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        return parts.join('.');
    };

    // Fetch MIRAGE token balance from Solana
    const fetchSolanaBalance = useCallback(async (walletAddress) => {
        try {
            // Fetch SOL balance and MIRAGE token balance in parallel
            const [solResponse, tokenResponse] = await Promise.all([
                // SOL balance
                fetch(solanaRpcUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        id: 1,
                        method: 'getBalance',
                        params: [walletAddress]
                    })
                }),
                // MIRAGE token balance
                solanaTokenAddress ? fetch(solanaRpcUrl, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        id: 2,
                        method: 'getTokenAccountsByOwner',
                        params: [
                            walletAddress,
                            { mint: solanaTokenAddress },
                            { encoding: 'jsonParsed' }
                        ]
                    })
                }) : Promise.resolve(null)
            ]);

            // Parse SOL balance
            const solData = await solResponse.json();
            const solBalance = (solData.result?.value || 0) / 1_000_000_000; // lamports to SOL
            console.debug('[Solana Bridge] SOL balance:', solBalance);

            // Parse MIRAGE balance
            let mirageBalance = 0;
            if (tokenResponse) {
                const tokenData = await tokenResponse.json();
                console.debug('[Solana Bridge] MIRAGE token accounts:', tokenData);

                if (tokenData.result?.value?.length > 0) {
                    for (const account of tokenData.result.value) {
                        const info = account.account?.data?.parsed?.info;
                        if (info) {
                            const amount = info.tokenAmount?.uiAmount || 0;
                            console.debug('[Solana Bridge] Found MIRAGE:', info.mint, 'amount:', amount);
                            mirageBalance += amount;
                        }
                    }
                }
            } else {
                console.warn('[Solana Bridge] No token address configured');
            }

            setSolanaWallet(prev => prev ? { ...prev, mirageBalance, solBalance } : null);
        } catch (e) {
            console.error('[Solana Bridge] Balance fetch error:', e);
            setSolanaWallet(prev => prev ? { ...prev, mirageBalance: 0, solBalance: 0 } : null);
        }
    }, [solanaRpcUrl, solanaTokenAddress]);

    // Connect to Phantom wallet
    const connectPhantom = async () => {
        setIsConnecting(true);
        setBridgeError('');
        try {
            // Check if Phantom is installed
            const { solana } = window;
            if (!solana?.isPhantom) {
                window.open('https://phantom.app/', '_blank');
                throw new Error('Phantom wallet not found. Please install it.');
            }

            // Connect
            const response = await solana.connect();
            const publicKey = response.publicKey.toString();

            setSolanaWallet({
                address: publicKey,
                mirageBalance: null, // Will be fetched
                solBalance: null, // Will be fetched
            });

            console.debug('[Solana Bridge] Connected:', publicKey);

            // Fetch balance
            await fetchSolanaBalance(publicKey);
        } catch (e) {
            console.error('[Solana Bridge] Connection error:', e);
            setBridgeError(e.message || 'Failed to connect wallet');
        } finally {
            setIsConnecting(false);
        }
    };

    // Disconnect wallet
    const disconnectWallet = async () => {
        try {
            const { solana } = window;
            if (solana) {
                await solana.disconnect();
            }
        } catch (e) {
            console.error('[Solana Bridge] Disconnect error:', e);
        }
        setSolanaWallet(null);
        setAmount('');
        setBridgeStatus('idle');
        setBridgeError('');
        setBridgeTxHash('');
        setBurnNonce(null);
        setStepTimestamps({});
        setStepElapsed({});
        setMintStatus({ state: 'idle', txHash: '', error: '' });
    };

    // Handle bridge (burn on Solana)
    const handleBridge = async () => {
        if (!solanaWallet || !amount || parseFloat(amount) <= 0) return;

        const programId = solanaConfig.solana_program_id;
        if (!programId) {
            setBridgeError('Bridge program not configured');
            return;
        }

        // Capture pre-bridge balances for the progress screen
        setPreBridgeSolanaBalance(solanaWallet.mirageBalance);
        setBridgeAmount(amount.replace(/,/g, ''));

        // Reset state
        setIsBridging(true);
        setBridgeStatus('confirming');
        setBridgeError('');
        setBridgeTxHash('');
        setBurnNonce(null);
        setMintStatus({ state: 'idle', txHash: '', error: '' });
        setStepTimestamps({ confirming: Date.now() });
        setStepElapsed({});

        try {
            // Convert amount to base units (6 decimals)
            const rawAmount = amount.replace(/,/g, '');
            const amountBaseUnits = Math.floor(parseFloat(rawAmount) * 1_000_000);

            if (amountBaseUnits <= 0) {
                throw new Error('Invalid amount');
            }

            console.debug('[Solana Bridge] Starting burn', {
                amount: rawAmount,
                amountBaseUnits,
                recipient: mirageAddress,
                programId,
            });

            // Lazy-load Solana bridge module (only loaded when user actually bridges)
            const { executeBurn } = await loadSolanaBridge();

            // Execute the burn transaction
            const result = await executeBurn({
                rpcUrl: solanaRpcUrl,
                programIdStr: programId,
                mirageRecipient: mirageAddress,
                amount: amountBaseUnits,
                onStatus: (status) => {
                    console.debug('[Solana Bridge] Status:', status);
                },
            });

            console.debug('[Solana Bridge] Burn successful', result);
            console.debug('[Solana Bridge] Burn nonce for polling:', result.burnNonce);

            setBridgeTxHash(result.signature);
            setBurnNonce(result.burnNonce !== undefined ? Number(result.burnNonce) : null);
            setBridgeStatus('pending');
            setStepTimestamps(prev => ({ ...prev, pending: Date.now() }));

            // Refresh balance after successful burn
            if (solanaWallet?.address) {
                fetchSolanaBalance(solanaWallet.address);
            }

        } catch (e) {
            console.error('[Solana Bridge] Bridge error:', e);
            setBridgeStatus('error');
            // Clean up error message
            let errorMsg = e.message || 'Bridge transaction failed';
            if (errorMsg.includes('User rejected')) {
                errorMsg = 'Transaction cancelled by user';
            } else if (errorMsg.includes('Insufficient')) {
                errorMsg = 'Insufficient MIRAGE balance';
            } else if (errorMsg.includes('paused')) {
                errorMsg = 'Bridge is currently paused';
            }
            setBridgeError(errorMsg);
        } finally {
            setIsBridging(false);
        }
    };

    // Amount validation
    const amountError = useMemo(() => {
        if (!amount) return null;
        const num = parseFloat(amount);
        if (isNaN(num) || num <= 0) return 'Enter a valid amount';
        if (solanaWallet?.mirageBalance !== null && num > solanaWallet.mirageBalance) {
            return 'Insufficient balance';
        }
        return null;
    }, [amount, solanaWallet?.mirageBalance]);

    const canBridge = solanaWallet && amount && parseFloat(amount) > 0 && !amountError && !isBridging && (bridgeStatus === 'idle' || bridgeStatus === 'error');

    // Reset for new bridge
    const handleNewBridge = () => {
        setAmount('');
        setBridgeStatus('idle');
        setBridgeError('');
        setBridgeTxHash('');
        setBurnNonce(null);
        setStepTimestamps({});
        setStepElapsed({});
        setMintStatus({ state: 'idle', txHash: '', error: '' });
        setPreBridgeSolanaBalance(null);
        setBridgeAmount('');
        // Refresh balances
        refreshMirageBalance('new_bridge');
        if (solanaWallet?.address) {
            fetchSolanaBalance(solanaWallet.address);
        }
    };

    // Show progress screen when bridging is in progress
    const showProgressScreen = bridgeStatus !== 'idle';

    // If showing progress screen, render the progress view
    if (showProgressScreen) {
        return (
            <ProgressScreenContainer>
                <ProgressScreenHeader>
                    <ProgressScreenTitle>
                        <ProgressScreenNetworkIcon src="/images/bridges/solana.svg" alt="" />
                        <ProgressScreenTitleText>
                            <ProgressScreenMainTitle>Bridge In</ProgressScreenMainTitle>
                            <ProgressScreenSubtitle>Solana → Mirage</ProgressScreenSubtitle>
                        </ProgressScreenTitleText>
                    </ProgressScreenTitle>
                </ProgressScreenHeader>

                {/* Progress Steps */}
                <StepsCard>
                    <StepsList>
                        {/* Step 1: Lock tokens on Solana */}
                        <StepItem>
                            <StepDot $state={getStepState('confirming')} />
                            <StepText>
                                <StepTitle>
                                    Locking tokens on Solana{formatStepTime('confirming')}
                                </StepTitle>
                                <StepMeta style={{ fontFamily: 'Monaco, Menlo, monospace', fontSize: '0.65rem', wordBreak: 'break-all' }}>
                                    {bridgeStatus === 'confirming' ? (
                                        'Waiting for wallet confirmation'
                                    ) : bridgeStatus === 'error' && !bridgeTxHash ? (
                                        `Failure: ${bridgeError || 'transaction failed'}`
                                    ) : bridgeTxHash ? (
                                        <>
                                            {'Success: '}
                                            <a
                                                href={`https://solscan.io/tx/${bridgeTxHash}${solscanClusterParam}`}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                            >
                                                {bridgeTxHash}
                                            </a>
                                        </>
                                    ) : (
                                        'Waiting for wallet confirmation'
                                    )}
                                </StepMeta>
                            </StepText>
                        </StepItem>

                        {/* Step 2: Validator attestations */}
                        <StepItem>
                            <StepDot $state={getStepState('pending')} />
                            <StepText>
                                <StepTitle>
                                    Validator attestations{formatStepTime('pending')}
                                </StepTitle>
                                <StepMeta>
                                    {bridgeStatus === 'confirming' ? (
                                        'Waiting for token lock confirmation'
                                    ) : attestationProgress.attestorCount > 0 ? (
                                        attestationPowerText
                                            ? `${attestationProgress.attestorCount} validator${attestationProgress.attestorCount !== 1 ? 's' : ''} attested (${attestationPowerText})${attestationProgress.confirmed ? ' - threshold reached' : ''}`
                                            : `${attestationProgress.attestorCount} validator${attestationProgress.attestorCount !== 1 ? 's' : ''} attested${attestationProgress.confirmed ? ' - threshold reached' : ''}`
                                    ) : mintStatus.state === 'minted' || bridgeStatus === 'complete' ? (
                                        'Threshold reached'
                                    ) : (
                                        'Waiting for validator attestations...'
                                    )}
                                </StepMeta>
                            </StepText>
                        </StepItem>

                        {/* Step 3: Mint tokens on Mirage */}
                        <StepItem>
                            <StepDot $state={getStepState('complete')} />
                            <StepText>
                                <StepTitle>
                                    Minting tokens on Mirage{bridgeStatus === 'complete' ? formatStepTime('complete') : ''}
                                </StepTitle>
                                <StepMeta style={{ fontFamily: 'Monaco, Menlo, monospace', fontSize: '0.65rem', wordBreak: 'break-all' }}>
                                    {bridgeStatus === 'complete' && mintStatus.txHash ? (
                                        <>
                                            {'Success: '}
                                            <a
                                                href={`/chain/rpc/tx?hash=0x${mintStatus.txHash}`}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                            >
                                                {mintStatus.txHash}
                                            </a>
                                        </>
                                    ) : bridgeStatus === 'complete' ? (
                                        'MIRAGE minted to your address'
                                    ) : mintStatus.state === 'timeout' ? (
                                        'Taking longer than expected - check your balance'
                                    ) : mintStatus.state === 'error' ? (
                                        `Error: ${mintStatus.error || 'mint failed'}`
                                    ) : (
                                        'Waiting for attestation'
                                    )}
                                </StepMeta>
                            </StepText>
                        </StepItem>
                    </StepsList>

                    {bridgeStatus === 'error' && bridgeError && (
                        <StatusBanner $error style={{ marginTop: '0.75rem' }}>
                            ✗ {bridgeError}
                        </StatusBanner>
                    )}

                    {bridgeStatus === 'complete' && (
                        <StatusBanner $success style={{ marginTop: '0.75rem' }}>
                            ✓ Bridge complete! {bridgeAmount ? `${bridgeAmount} ` : ''}MIRAGE minted to your address.
                        </StatusBanner>
                    )}
                </StepsCard>

                {/* Balance Comparison - only show when mint is fully complete (or error/timeout) */}
                {(mintStatus.state === 'minted' || mintStatus.state === 'error' || mintStatus.state === 'timeout' || bridgeStatus === 'error') && (
                    <BalanceComparisonCard>
                        <BalanceComparisonTitle>
                            Balance Summary
                        </BalanceComparisonTitle>
                        <BalanceComparisonGrid>
                            <BalanceComparisonColumn>
                                <BalanceComparisonNetwork>
                                    <BalanceComparisonNetworkIcon src="/images/bridges/solana.svg" alt="" />
                                    Solana
                                </BalanceComparisonNetwork>
                                <BalanceComparisonRow>
                                    <BalanceComparisonLabel>Before</BalanceComparisonLabel>
                                    <BalanceComparisonValue $dim>
                                        {preBridgeSolanaBalance !== null ? preBridgeSolanaBalance.toLocaleString() : '...'} MIRAGE
                                    </BalanceComparisonValue>
                                </BalanceComparisonRow>
                                <BalanceComparisonRow>
                                    <BalanceComparisonLabel>After</BalanceComparisonLabel>
                                    <BalanceComparisonValue>
                                        {solanaWallet?.mirageBalance !== null ? solanaWallet.mirageBalance.toLocaleString() : '...'} MIRAGE
                                    </BalanceComparisonValue>
                                </BalanceComparisonRow>
                            </BalanceComparisonColumn>
                            <BalanceComparisonColumn>
                                <BalanceComparisonNetwork>
                                    <BalanceComparisonNetworkIcon src="/favicon.svg" alt="" $isMirage />
                                    Mirage
                                </BalanceComparisonNetwork>
                                <BalanceComparisonRow>
                                    <BalanceComparisonLabel>Received</BalanceComparisonLabel>
                                    <BalanceComparisonValue $highlight={mintStatus.state === 'minted'}>
                                        +{bridgeAmount ? parseFloat(bridgeAmount).toLocaleString() : '...'} MIRAGE
                                    </BalanceComparisonValue>
                                </BalanceComparisonRow>
                            </BalanceComparisonColumn>
                        </BalanceComparisonGrid>
                    </BalanceComparisonCard>
                )}

                {/* Action Button */}
                <div ref={buttonRef} style={{ paddingTop: '0.5rem', paddingBottom: '2rem' }}>
                    <Button
                        variant="primary"
                        fullWidth
                        disabled={mintStatus.state !== 'minted' && mintStatus.state !== 'error' && mintStatus.state !== 'timeout' && bridgeStatus !== 'error'}
                        onClick={handleNewBridge}
                        style={{
                            background: 'linear-gradient(135deg, #14F195 0%, #0ea66e 100%)',
                        }}
                    >
                        {mintStatus.state === 'minted' || mintStatus.state === 'error' || mintStatus.state === 'timeout' || bridgeStatus === 'error'
                            ? 'Start New Bridge'
                            : 'Bridging...'}
                    </Button>
                </div>
            </ProgressScreenContainer>
        );
    }

    return (
        <>
            {/* Step 2: Connect Solana Wallet */}
            <SectionTitle>
                <StepNumber>2</StepNumber>
                Connect Solana Wallet
            </SectionTitle>
            <InputSection>
                {/* Network indicator */}
                {solanaCluster !== 'mainnet' && (
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                        padding: '0.5rem 0.75rem',
                        marginBottom: '0.75rem',
                        background: 'rgba(20, 241, 149, 0.1)',
                        borderRadius: '0.5rem',
                        border: '1px solid rgba(20, 241, 149, 0.3)',
                        fontSize: '0.8rem',
                    }}>
                        <span style={{ color: '#14F195', fontWeight: 600 }}>
                            {solanaCluster.toUpperCase()}
                        </span>
                        <span style={{ color: theme?.colors?.subtleText || '#888' }}>
                            — Set Phantom to {solanaCluster} in Settings → Developer Settings
                        </span>
                    </div>
                )}
                {!solanaWallet ? (
                    <>
                        <SolanaWalletButton
                            type="button"
                            onClick={connectPhantom}
                            disabled={isConnecting}
                        >
                            <img src="/images/bridges/solana.svg" alt="Solana" />
                            {isConnecting ? 'Connecting...' : 'Connect Phantom'}
                        </SolanaWalletButton>
                        {bridgeError && bridgeStatus === 'idle' && (
                            <ErrorText style={{ marginTop: '0.5rem' }}>⚠ {bridgeError}</ErrorText>
                        )}
                    </>
                ) : (
                    <ConnectedWalletBox>
                        <WalletRow>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0, flex: 1 }}>
                                <img src="/images/bridges/solana.svg" alt="Solana" style={{ width: '1.25rem', height: '1.25rem', flexShrink: 0 }} />
                                <WalletAddress style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{solanaWallet.address}</WalletAddress>
                            </div>
                            <DisconnectButton type="button" onClick={disconnectWallet} style={{ flexShrink: 0 }}>
                                Disconnect
                            </DisconnectButton>
                        </WalletRow>
                        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginTop: '0.5rem' }}>
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                padding: '0.35rem 0.6rem',
                                background: 'rgba(20, 241, 149, 0.1)',
                                borderRadius: '6px',
                                border: '1px solid rgba(20, 241, 149, 0.3)',
                            }}>
                                <span style={{ fontSize: '0.9rem', fontWeight: 600, color: theme?.colors?.text || '#fff' }}>
                                    {solanaWallet.mirageBalance !== null
                                        ? solanaWallet.mirageBalance.toLocaleString()
                                        : '...'}
                                </span>
                                <span style={{ fontSize: '0.7rem', color: theme?.colors?.subtleText || '#888', fontWeight: 500 }}>MIRAGE</span>
                            </div>
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                padding: '0.35rem 0.6rem',
                                background: 'rgba(20, 241, 149, 0.1)',
                                borderRadius: '6px',
                                border: '1px solid rgba(20, 241, 149, 0.3)',
                            }}>
                                <span style={{ fontSize: '0.9rem', fontWeight: 600, color: theme?.colors?.text || '#fff' }}>
                                    {solanaWallet.solBalance !== null
                                        ? solanaWallet.solBalance.toLocaleString(undefined, { minimumFractionDigits: 4, maximumFractionDigits: 4 })
                                        : '...'}
                                </span>
                                <span style={{ fontSize: '0.7rem', color: theme?.colors?.subtleText || '#888', fontWeight: 500 }}>SOL</span>
                            </div>
                        </div>
                        {solanaWallet.mirageBalance === 0 && solanaCluster !== 'mainnet' && (
                            <div style={{
                                marginTop: '0.5rem',
                                padding: '0.5rem',
                                background: 'rgba(245, 158, 11, 0.1)',
                                borderRadius: '0.25rem',
                                fontSize: '0.75rem',
                                color: '#f59e0b',
                            }}>
                                No MIRAGE tokens found. Make sure Phantom is set to {solanaCluster}.
                            </div>
                        )}
                    </ConnectedWalletBox>
                )}
            </InputSection>

            {/* Step 3: Enter Amount (only show when connected) */}
            {solanaWallet && (
                <>
                    <SectionTitle>
                        <StepNumber>3</StepNumber>
                        Send to Mirage
                    </SectionTitle>
                    <InputSection>
                        <InputWrapper>
                            <AmountInput
                                type="text"
                                inputMode="decimal"
                                placeholder="0.00"
                                value={amount}
                                onChange={(e) => {
                                    const val = e.target.value.replace(/,/g, '');
                                    if (/^\d*\.?\d*$/.test(val)) {
                                        // Cap at max balance
                                        const numVal = parseFloat(val) || 0;
                                        const maxBalance = solanaWallet?.mirageBalance ?? Infinity;
                                        if (numVal > maxBalance && maxBalance !== Infinity) {
                                            setAmount(formatAmountDisplay(String(maxBalance)));
                                        } else {
                                            setAmount(formatAmountDisplay(val));
                                        }
                                    }
                                }}
                                $error={!!amountError}
                                disabled={isBridging}
                            />
                            {solanaWallet.mirageBalance !== null && (
                                <MaxButton
                                    type="button"
                                    onClick={() => setAmount(formatAmountDisplay(String(solanaWallet.mirageBalance)))}
                                    disabled={isBridging}
                                >
                                    Max
                                </MaxButton>
                            )}
                            <AmountSuffix>MIRAGE</AmountSuffix>
                        </InputWrapper>
                        {amountError && (
                            <ErrorText>⚠ {amountError}</ErrorText>
                        )}
                    </InputSection>

                    {/* Step 4: Destination */}
                    <SectionTitle>
                        <StepNumber>4</StepNumber>
                        Destination
                    </SectionTitle>
                    <InputSection>
                        <div style={{ fontSize: '0.75rem', color: theme?.colors?.subtleText || '#888', marginBottom: '0.35rem' }}>
                            Tokens will arrive at your Mirage address:
                        </div>
                        <div style={{
                            fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
                            fontSize: '0.8rem',
                            padding: '0.5rem 0.75rem',
                            background: theme?.colors?.panelAlt || '#1f2328',
                            border: `1px solid ${theme?.colors?.border || '#444'}`,
                            borderRadius: '6px',
                            wordBreak: 'break-all',
                            color: theme?.colors?.text || '#fff',
                        }}>
                            {mirageAddress}
                        </div>
                    </InputSection>

                    {/* Preview Card - matches Bridge Out style */}
                    {amount && parseFloat(amount.replace(/,/g, '')) > 0 && (
                        <PreviewCard>
                            <PreviewHeader>
                                <PreviewTitle>Summary</PreviewTitle>
                                <PreviewNetwork $color="#14F195">
                                    <img src="/images/bridges/solana.svg" alt="" style={{ width: '1.25rem', height: '1.25rem' }} /> Solana
                                </PreviewNetwork>
                            </PreviewHeader>
                            <PreviewRow>
                                <PreviewLabel>Send Amount</PreviewLabel>
                                <PreviewValue>{parseFloat(amount.replace(/,/g, '')).toLocaleString()} MIRAGE</PreviewValue>
                            </PreviewRow>
                            <PreviewRow>
                                <PreviewLabel>Network Fee</PreviewLabel>
                                <PreviewValue>~0.0001 SOL</PreviewValue>
                            </PreviewRow>
                            <Divider />
                            <PreviewRow>
                                <PreviewLabel>Receive on Mirage</PreviewLabel>
                                <PreviewValue $highlight>
                                    {parseFloat(amount.replace(/,/g, '')).toLocaleString()} MIRAGE
                                </PreviewValue>
                            </PreviewRow>
                        </PreviewCard>
                    )}

                    {/* Bridge Button */}
                    <div ref={buttonRef} style={{ paddingBottom: '1rem' }}>
                        <Button
                            variant="primary"
                            fullWidth
                            disabled={!canBridge}
                            onClick={handleBridge}
                            style={{
                                background: 'linear-gradient(135deg, #14F195 0%, #0ea66e 100%)',
                            }}
                        >
                            {!amount || parseFloat(amount) <= 0
                                ? 'Enter Amount'
                                : `Bridge ${amount} MIRAGE`}
                        </Button>
                    </div>
                </>
            )}
        </>
    );
}

// Bridge In Panel Component
function BridgeInPanel({ address, chainConfigs, attestationThresholdBps, balance, balanceLoading, balanceError, refreshBalance, formatBalance }) {
    const theme = useTheme();
    const [selectedSource, setSelectedSource] = useState(null);
    const [addressConfirmed, setAddressConfirmed] = useState(null); // null = not answered, true = yes, false = no
    const [copiedAddress, setCopiedAddress] = useState(null); // Track which address was copied
    const [isSolanaBridging, setIsSolanaBridging] = useState(false); // Track when Solana bridge is in progress

    // Derive Osmosis address from Mirage address (same key)
    const derivedOsmoAddress = useMemo(() => {
        if (!address) return null;
        return convertBech32Prefix(address, 'osmo');
    }, [address]);

    const handleSourceSelect = (networkId) => {
        setSelectedSource(SOURCE_NETWORKS[networkId]);
        setAddressConfirmed(null); // Reset when changing source
        console.debug('[Bridge In] Selected source:', networkId);
    };

    const handleSolanaBridgingChange = useCallback((isBridging) => {
        setIsSolanaBridging(isBridging);
    }, []);

    const handleCopy = async (addr) => {
        if (!addr) return;
        try {
            await navigator.clipboard.writeText(addr);
            setCopiedAddress(addr);
            setTimeout(() => {
                setCopiedAddress(null);
            }, 2000);
        } catch (e) {
            console.error('Failed to copy:', e);
        }
    };

    if (!address) {
        return (
            <BridgeContainer>
                <BridgeLayout>
                    <InfoBanner>
                        <InfoIcon>ℹ️</InfoIcon>
                        <span>Sign in to bridge MIRAGE tokens from other networks.</span>
                    </InfoBanner>
                </BridgeLayout>
            </BridgeContainer>
        );
    }

    return (
        <BridgeContainer>
            <BridgeLayout>
                {/* Hide form elements when Solana bridging is in progress */}
                {!isSolanaBridging && (
                    <>
                        {/* Step 1: Source Network Selection */}
                        <SectionTitle>
                            <StepNumber>1</StepNumber>
                            Select Source Chain
                        </SectionTitle>
                        <NetworkGrid>
                            {Object.values(SOURCE_NETWORKS).map((network) => (
                                <NetworkCard
                                    key={network.id}
                                    type="button"
                                    $selected={selectedSource?.id === network.id}
                                    $color={network.color}
                                    onClick={() => handleSourceSelect(network.id)}
                                    disabled={!network.enabled}
                                >
                                    <NetworkCardContent>
                                        <NetworkName>{network.name}</NetworkName>
                                        <NetworkMeta>
                                            <NetworkBadge $color={network.color}>
                                                {network.estimatedTime}
                                            </NetworkBadge>
                                        </NetworkMeta>
                                    </NetworkCardContent>
                                    <NetworkIcon src={network.icon} alt={network.name} />
                                    {selectedSource?.id === network.id && (
                                        <SelectedIndicator $color={network.color}>
                                            ✓
                                        </SelectedIndicator>
                                    )}
                                </NetworkCard>
                            ))}
                        </NetworkGrid>
                    </>
                )}

                {/* Osmosis Bridge In Flow */}
                {selectedSource?.id === 'osmosis' && (
                    <>
                        {/* Step 2: Connect Wallet */}
                        <SectionTitle>
                            <StepNumber>2</StepNumber>
                            Connect Wallet
                        </SectionTitle>
                        <InputSection>
                            <div style={{ fontSize: '0.8rem', color: theme?.colors?.subtleText || '#888' }}>
                                Open <a href="https://app.osmosis.zone/assets/ibc/E132A35DC380C8D68E99F46BC7A5083602F171D00E3BE9471541FB1AA62D8BE2" target="_blank" rel="noopener noreferrer" style={{ color: theme?.colors?.link || '#667eea' }}>MIRAGE on Osmosis</a> and
                                connect your wallet (we recommend <a href="https://www.keplr.app/" target="_blank" rel="noopener noreferrer" style={{ color: theme?.colors?.link || '#667eea' }}>Keplr</a>)
                            </div>
                        </InputSection>

                        {/* Step 3: Verify Address */}
                        <SectionTitle>
                            <StepNumber>3</StepNumber>
                            Verify Your Address
                        </SectionTitle>
                        <InputSection>
                            <div style={{ fontSize: '0.8rem', color: theme?.colors?.subtleText || '#888', marginBottom: '0.5rem' }}>
                                Does the Osmosis website show this address after connecting?
                            </div>
                            <div style={{
                                fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
                                fontSize: '0.85rem',
                                padding: '0.6rem 0.85rem',
                                background: theme?.colors?.panelAlt || '#1f2328',
                                border: `1px solid ${theme?.colors?.border || '#444'}`,
                                borderRadius: '8px',
                                wordBreak: 'break-all',
                                color: theme?.colors?.text || '#fff',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                gap: '0.5rem'
                            }}>
                                <span style={{ flex: 1, minWidth: 0 }}>{derivedOsmoAddress || '...'}</span>
                                <CopyButton type="button" onClick={() => handleCopy(derivedOsmoAddress)}>
                                    {copiedAddress === derivedOsmoAddress ? 'Copied' : 'Copy'}
                                </CopyButton>
                            </div>
                            <ConfirmButtonRow>
                                <ConfirmButton
                                    type="button"
                                    $variant="yes"
                                    $selected={addressConfirmed === true}
                                    onClick={() => setAddressConfirmed(true)}
                                >
                                    ✓ Yes, it matches
                                </ConfirmButton>
                                <ConfirmButton
                                    type="button"
                                    $variant="no"
                                    $selected={addressConfirmed === false}
                                    onClick={() => setAddressConfirmed(false)}
                                >
                                    ✗ No, different address
                                </ConfirmButton>
                            </ConfirmButtonRow>

                            {addressConfirmed === false && (
                                <WarningBanner style={{ marginTop: '1rem', marginBottom: 0, flexDirection: 'column', alignItems: 'stretch', gap: '0.5rem' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <WarningIcon>⚠️</WarningIcon>
                                        <span><strong>Your MIRAGE is in a different wallet</strong></span>
                                    </div>
                                    <div style={{ fontSize: '0.75rem', lineHeight: 1.8, marginTop: '0.5rem' }}>
                                        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.4rem' }}>
                                            <span style={{ fontWeight: 700 }}>1.</span>
                                            <span>From your current Osmosis wallet, send your MIRAGE to:</span>
                                        </div>
                                        <div style={{
                                            fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
                                            fontSize: '0.75rem',
                                            padding: '0.4rem 0.6rem',
                                            background: 'rgba(245, 158, 11, 0.15)',
                                            borderRadius: '4px',
                                            wordBreak: 'break-all',
                                            marginBottom: '0.5rem',
                                            marginLeft: '1rem',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'space-between',
                                            gap: '0.5rem'
                                        }}>
                                            <span style={{ flex: 1, minWidth: 0 }}>{derivedOsmoAddress}</span>
                                            <CopyButton type="button" onClick={() => handleCopy(derivedOsmoAddress)} style={{ fontSize: '0.6rem', padding: '0.25rem 0.4rem' }}>
                                                {copiedAddress === derivedOsmoAddress ? 'Copied' : 'Copy'}
                                            </CopyButton>
                                        </div>
                                        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.4rem' }}>
                                            <span style={{ fontWeight: 700 }}>2.</span>
                                            <span>Import your Mirage seed phrase (12 words) into <a href="https://www.keplr.app/" target="_blank" rel="noopener noreferrer" style={{ color: '#f59e0b' }}>Keplr</a></span>
                                        </div>
                                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                                            <span style={{ fontWeight: 700 }}>3.</span>
                                            <span>Withdraw from Osmosis (now your wallet will show the correct address)</span>
                                        </div>
                                    </div>
                                </WarningBanner>
                            )}
                        </InputSection>

                        {/* Step 4: Withdraw (only shown when address is confirmed) */}
                        {addressConfirmed === true && (
                            <>
                                <SectionTitle>
                                    <StepNumber>4</StepNumber>
                                    Withdraw
                                </SectionTitle>
                                <InputSection>
                                    <div style={{ fontSize: '0.8rem', color: theme?.colors?.subtleText || '#888', lineHeight: 1.6 }}>
                                        Click <strong>Withdraw</strong>, enter the amount, and confirm the transaction.
                                        Tokens typically arrive within 30 seconds.
                                    </div>
                                    <StatusBanner $success style={{ marginTop: '0.75rem' }}>
                                        ✓ Your tokens will arrive at your Mirage address
                                    </StatusBanner>
                                </InputSection>
                            </>
                        )}
                    </>
                )}

                {/* Solana Bridge In Flow */}
                {selectedSource?.id === 'solana' && (
                    <SolanaBridgeInFlow
                        mirageAddress={address}
                        theme={theme}
                        chainConfigs={chainConfigs}
                        attestationThresholdBps={attestationThresholdBps}
                        onBridgingChange={handleSolanaBridgingChange}
                    />
                )}

                {/* Info when no source selected */}
                {!selectedSource && (
                    <InfoBanner>
                        <InfoIcon>ℹ️</InfoIcon>
                        <span>
                            Select a source chain above to see instructions for bridging MIRAGE tokens to your Mirage wallet.
                        </span>
                    </InfoBanner>
                )}
            </BridgeLayout>
        </BridgeContainer>
    );
}

export default function BridgeView({ state }) {
    const location = useLocation();
    const [searchParams, setSearchParams] = useSearchParams();
    const address = Storage.load('publicKey', '') || '';
    const valoperAddress = Storage.load('validator_operator_address', '') || '';

    // Get initial tab from URL, default to 'out'
    const tabFromUrl = searchParams.get('tab');
    const initialTab = (tabFromUrl === 'in' || tabFromUrl === 'out') ? tabFromUrl : 'out';

    // State
    const [activeTab, setActiveTab] = useState(initialTab);
    const [selectedNetwork, setSelectedNetwork] = useState(null);
    const [amount, setAmount] = useState('');
    const [destinationAddress, setDestinationAddress] = useState('');
    const [useDifferentAddress, setUseDifferentAddress] = useState(false);
    const [balance, setBalance] = useState(null);
    const [balanceLoading, setBalanceLoading] = useState(false);
    const [balanceError, setBalanceError] = useState(null);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [submitStage, setSubmitStage] = useState('idle'); // idle | submitting | verifying | confirmed | error
    const [submitError, setSubmitError] = useState('');
    const [submitTxHash, setSubmitTxHash] = useState('');
    const [, setVerificationProgress] = useState({ attempt: 0, maxAttempts: 0 });
    const [errorStage, setErrorStage] = useState(null);
    const [errors, setErrors] = useState({});
    const stepsRef = useRef(null);

    // Step timing: track when each step started and current elapsed times
    const [stepTimestamps, setStepTimestamps] = useState({});
    const [stepElapsed, setStepElapsed] = useState({});
    const [mintStatus, setMintStatus] = useState({
        state: 'idle', // idle | pending | minted | timeout | error
        destinationTx: '',
        destinationChain: '',
        error: '',
        completedAt: null, // timestamp when mint completed (for final timer display)
    });
    const [outboundAttestationProgress, setOutboundAttestationProgress] = useState({
        attestorCount: 0,
        attestedPower: 0,
        requiredPower: 0,
        confirmed: false,
    });
    const [chainConfigs, setChainConfigs] = useState({}); // chain_id -> { fee_mirage, enabled, ... }
    const [attestationThresholdBps, setAttestationThresholdBps] = useState(null);

    // Pre-bridge balance tracking for progress screen (Bridge Out)
    const [preBridgeMirageBalance, setPreBridgeMirageBalance] = useState(null);
    const [bridgeOutAmount, setBridgeOutAmount] = useState('');
    const [bridgeOutNetwork, setBridgeOutNetwork] = useState(null);

    // Sync tab state with URL changes (browser back/forward)
    useEffect(() => {
        const tab = searchParams.get('tab');
        if (tab === 'in' || tab === 'out') {
            if (tab !== activeTab) {
                setActiveTab(tab);
            }
        }
    }, [searchParams, activeTab]);

    // Fetch bridge config (per-chain fees) from backend
    useEffect(() => {
        fetch('/api/bridge/config')
            .then(res => res.json())
            .then(data => {
                if (data.chains) {
                    const configs = {};
                    for (const chain of data.chains) {
                        configs[chain.chain_id] = chain;
                    }
                    setChainConfigs(configs);
                    console.debug('[Bridge] Loaded chain configs:', configs);
                }
                if (typeof data.attestation_threshold_bps !== 'undefined') {
                    setAttestationThresholdBps(Number(data.attestation_threshold_bps));
                }
            })
            .catch(err => console.error('[Bridge] Failed to load config:', err));
    }, []);

    // Bridge fee per chain (from backend config)
    const bridgeFee = useMemo(() => {
        if (!selectedNetwork) return null;
        const config = chainConfigs[selectedNetwork.id];
        if (!config) return null; // Chain not configured
        return config.fee_mirage;
    }, [selectedNetwork, chainConfigs]);

    // Derive the user's address on the destination chain (for Cosmos chains)
    const derivedAddress = useMemo(() => {
        if (!address || !selectedNetwork?.canDerive || !selectedNetwork?.addressPrefix) {
            return null;
        }
        return convertBech32Prefix(address, selectedNetwork.addressPrefix);
    }, [address, selectedNetwork]);

    // The effective destination address (derived or manual)
    const effectiveDestination = useMemo(() => {
        if (selectedNetwork?.canDerive && !useDifferentAddress) {
            return derivedAddress;
        }
        return destinationAddress;
    }, [selectedNetwork, useDifferentAddress, derivedAddress, destinationAddress]);

    const refreshBalance = useCallback(async (reason = 'init') => {
        if (!address) {
            setBalance(null);
            setBalanceError(null);
            console.debug('[Bridge] Balance fetch skipped (no address)');
            return;
        }
        console.debug('[Bridge] Fetching on-chain balance', { address, reason });
        setBalanceLoading(true);
        setBalanceError(null);
        try {
            const data = await Api.get(
                'get_user_status',
                { address, _cb: Date.now() },
                {
                    timeoutMs: 10000,
                    headers: {
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache',
                    },
                }
            );
            const balanceVal = Number(data?.balance);
            if (!Number.isFinite(balanceVal)) {
                throw new Error('Invalid balance from get_user_status');
            }
            setBalance(balanceVal);
            setBalanceError(null);
            console.debug('[Bridge] Balance updated', { balance: balanceVal });
        } catch (e) {
            console.error('[Bridge] Balance fetch failed:', e);
            setBalanceError(e.message || 'Failed to load balance');
        } finally {
            setBalanceLoading(false);
        }
    }, [address]);

    useEffect(() => {
        refreshBalance('init');
    }, [refreshBalance]);

    useEffect(() => {
        if (submitStage !== 'confirmed') return;
        refreshBalance('confirmed');
    }, [submitStage, refreshBalance]);

    // Validation
    const validateAmount = useCallback((value) => {
        if (!value || value === '') return null;
        // Only show "Chain not configured" if config has loaded but chain isn't there
        const configLoaded = Object.keys(chainConfigs).length > 0;
        if (bridgeFee === null && configLoaded) return 'Chain not configured';
        if (bridgeFee === null) return null; // Still loading config
        const num = parseFloat(value);
        if (isNaN(num) || num <= 0) return 'Please enter a valid amount';
        // Fee is subtracted from amount, so amount must be greater than fee
        if (num <= bridgeFee) {
            return `Amount must be greater than ${bridgeFee} MIRAGE fee`;
        }
        const receiveAmt = num - bridgeFee;
        if (selectedNetwork && receiveAmt < selectedNetwork.minAmount) {
            return `Receive amount must be at least ${selectedNetwork.minAmount} MIRAGE (after ${bridgeFee} fee)`;
        }
        if (Number.isFinite(balance) && num > balance / 1_000_000) {
            return 'Insufficient balance';
        }
        return null;
    }, [selectedNetwork, balance, bridgeFee, chainConfigs]);

    const validateAddress = useCallback((value, isManualEntry = true) => {
        // If using derived address for Cosmos chains, no validation needed
        if (selectedNetwork?.canDerive && !isManualEntry) {
            return null;
        }

        if (!value || value === '') return null;
        if (!selectedNetwork) return null;

        const trimmed = value.trim();

        if (selectedNetwork.id === 'osmosis') {
            if (!trimmed.startsWith('osmo1')) {
                return 'Osmosis address must start with osmo1';
            }
            try {
                const decoded = bech32.decode(trimmed);
                if (decoded.prefix !== 'osmo') {
                    return 'Invalid Osmosis bech32 prefix';
                }
                const bytes = bech32.fromWords(decoded.words);
                if (!bytes || bytes.length !== 20) {
                    return 'Invalid Osmosis address payload';
                }
            } catch (_) {
                return 'Invalid Osmosis address (bech32 checksum failed)';
            }
        }

        if (selectedNetwork.id === 'solana') {
            // Basic Solana address validation (base58, 32-44 chars)
            if (trimmed.length < 32 || trimmed.length > 44) {
                return 'Invalid Solana address length';
            }
            // Check for valid base58 characters
            if (!/^[1-9A-HJ-NP-Za-km-z]+$/.test(trimmed)) {
                return 'Invalid Solana address format';
            }
        }

        return null;
    }, [selectedNetwork]);

    useEffect(() => {
        if (submitStage === 'idle') return;
        if (!stepsRef.current) return;
        try {
            stepsRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } catch (_) { }
    }, [submitStage]);

    // Handlers
    const resetSubmitState = useCallback(() => {
        setSubmitStage('idle');
        setSubmitError('');
        setSubmitTxHash('');
        setVerificationProgress({ attempt: 0, maxAttempts: 0 });
        setErrorStage(null);
        setStepTimestamps({});
        setStepElapsed({});
        setMintStatus({ state: 'idle', destinationTx: '', destinationChain: '', error: '', completedAt: null });
        setOutboundAttestationProgress({
            attestorCount: 0,
            attestedPower: 0,
            requiredPower: 0,
            confirmed: false,
        });
        setPreBridgeMirageBalance(null);
        setBridgeOutAmount('');
        setBridgeOutNetwork(null);
    }, []);

    // Track step timing: record timestamp when stage changes
    useEffect(() => {
        if (submitStage === 'idle') return;

        // Record timestamp for this step if not already set
        setStepTimestamps(prev => {
            if (prev[submitStage]) return prev;
            return { ...prev, [submitStage]: Date.now() };
        });
    }, [submitStage]);

    // Update elapsed times every 100ms while actively processing (not idle or error)
    useEffect(() => {
        if (submitStage === 'idle' || submitStage === 'error') return;

        const interval = setInterval(() => {
            const now = Date.now();
            setStepElapsed(prev => {
                const newElapsed = { ...prev };
                for (const [step, startTime] of Object.entries(stepTimestamps)) {
                    newElapsed[step] = (now - startTime) / 1000;
                }
                return newElapsed;
            });
        }, 100);

        return () => clearInterval(interval);
    }, [submitStage, stepTimestamps]);

    useEffect(() => {
        if (submitStage !== 'confirmed') return;
        if (selectedNetwork?.id !== 'solana') return;
        if (!submitTxHash) return;

        let cancelled = false;
        const maxAttempts = BRIDGE_OUT_STATUS_POLL_SCHEDULE.intervalsMs.length + 1;
        const initialDelayMs = BRIDGE_OUT_STATUS_POLL_SCHEDULE.initialDelayMs;

        setMintStatus({
            state: 'pending',
            destinationTx: '',
            destinationChain: '',
            error: '',
        });
        setOutboundAttestationProgress({
            attestorCount: 0,
            attestedPower: 0,
            requiredPower: 0,
            confirmed: false,
        });

        console.debug('[Bridge] Status poll schedule (ms):', {
            initialDelayMs,
            intervalsMs: BRIDGE_OUT_STATUS_POLL_SCHEDULE.intervalsMs,
        });

        const poll = async (attempt = 1) => {
            if (cancelled) return;
            try {
                console.debug('[Bridge] Status poll attempt', attempt, 'of', maxAttempts);

                // Query bridge status (includes attestor count)
                const res = await fetch(`/api/bridge/status?burn_tx_hash=${submitTxHash}`);
                if (res.ok) {
                    const data = await res.json();
                    console.debug('[Bridge] Bridge status response:', data);

                    // Update attestation progress from status response
                    if (data.found) {
                        setOutboundAttestationProgress(prev => ({
                            ...prev,
                            attestorCount: data.attestor_count || prev.attestorCount,
                            attestedPower: data.attested_power ?? prev.attestedPower,
                            requiredPower: data.required_power ?? prev.requiredPower,
                            confirmed: data.confirmed || prev.confirmed,
                        }));
                    }

                    if (data?.confirmed) {
                        setMintStatus({
                            state: 'minted',
                            destinationTx: data.destination_tx || '',
                            destinationChain: data.destination_chain || 'solana',
                            error: '',
                            completedAt: Date.now(),
                        });
                        return;
                    }
                } else {
                    console.debug(`[Bridge] Status query error (${res.status}), retrying...`);
                }
            } catch (e) {
                console.debug('[Bridge] Status poll error:', e.message);
            }

            if (attempt >= maxAttempts) {
                setMintStatus({
                    state: 'timeout',
                    destinationTx: '',
                    destinationChain: '',
                    error: 'mint confirmation timed out',
                    completedAt: Date.now(),
                });
                return;
            }

            const nextDelay = BRIDGE_OUT_STATUS_POLL_SCHEDULE.intervalsMs[attempt - 1];
            if (!nextDelay) {
                setMintStatus({
                    state: 'timeout',
                    destinationTx: '',
                    destinationChain: '',
                    error: 'mint confirmation timed out',
                    completedAt: Date.now(),
                });
                return;
            }
            console.debug('[Bridge] Status poll next delay (ms):', nextDelay);
            setTimeout(() => poll(attempt + 1), nextDelay);
        };

        if (initialDelayMs > 0) {
            setTimeout(() => poll(1), initialDelayMs);
        } else {
            poll(1);
        }
        return () => {
            cancelled = true;
        };
    }, [submitStage, selectedNetwork?.id, submitTxHash]);

    const handleNewBridge = () => {
        setAmount('');
        // Keep destination address - it's saved in localStorage
        setUseDifferentAddress(false);
        resetSubmitState();
        setErrors(prev => ({ ...prev, submit: null }));
        // Refresh balance
        refreshBalance('new_bridge');
        console.debug('[Bridge] Reset for new transaction');
    };

    const handleTabChange = (tab) => {
        setActiveTab(tab);
        setSearchParams({ tab }); // Update URL
        resetSubmitState();
        setErrors(prev => ({ ...prev, submit: null }));
        // Always refresh balance when switching tabs
        refreshBalance('tab_switch');
        console.debug('[Bridge] Tab changed:', tab);
    };

    const handleNetworkSelect = (networkId) => {
        setSelectedNetwork(NETWORKS[networkId]);
        // Load saved address for this network from localStorage
        const savedAddress = localStorage.getItem(`bridge_dest_${networkId}`) || '';
        setDestinationAddress(savedAddress);
        setUseDifferentAddress(false);
        setErrors({});
        resetSubmitState();
        console.debug('[Bridge] Selected network:', networkId, 'saved address:', savedAddress);
    };

    // Format number with thousands separators for display
    const formatAmountDisplay = useCallback((value) => {
        if (!value || value === '') return '';
        // Strip existing commas
        const raw = value.replace(/,/g, '');
        // Split by decimal
        const parts = raw.split('.');
        // Add thousands separators to integer part
        parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        return parts.join('.');
    }, []);

    // Get raw amount (without commas) for calculations
    const rawAmount = amount.replace(/,/g, '');

    const handleAmountChange = (e) => {
        // Strip commas from input to get raw value
        const rawValue = e.target.value.replace(/,/g, '');
        // Allow only numbers and single decimal point
        if (/^\d*\.?\d*$/.test(rawValue)) {
            // Cap at max balance
            const numVal = parseFloat(rawValue) || 0;
            const maxBalance = Number.isFinite(balance) ? balance / 1_000_000 : null;
            let finalValue = rawValue;
            if (maxBalance !== null && numVal > maxBalance && maxBalance > 0) {
                finalValue = maxBalance.toFixed(6);
            }
            // Store formatted value with commas
            setAmount(formatAmountDisplay(finalValue));
            const error = validateAmount(finalValue);
            setErrors(prev => ({ ...prev, amount: error }));
            if (submitStage !== 'idle') resetSubmitState();
        }
    };

    const handleMaxAmount = () => {
        if (!selectedNetwork || !Number.isFinite(balance)) return;
        // Fee is subtracted from amount, so MAX is full balance
        const maxAmount = Math.max(0, balance / 1_000_000);
        setAmount(formatAmountDisplay(maxAmount.toFixed(6)));
        setErrors(prev => ({ ...prev, amount: null }));
    };

    const handleAddressChange = (e) => {
        const value = e.target.value;
        setDestinationAddress(value);
        // Save to localStorage for this network
        if (selectedNetwork?.id) {
            localStorage.setItem(`bridge_dest_${selectedNetwork.id}`, value);
        }
        const error = validateAddress(value);
        setErrors(prev => ({ ...prev, address: error }));
        if (submitStage !== 'idle') resetSubmitState();
    };

    const handleSubmit = async () => {
        let stageAtError = 'submitting';
        console.debug('[Bridge] Submit attempt', {
            network: selectedNetwork?.id,
            amount: rawAmount,
            destination: effectiveDestination,
        });

        // Validate all fields (use raw amount without commas)
        const amountError = validateAmount(rawAmount);
        // Only validate manual address entry
        const needsManualAddress = !selectedNetwork?.canDerive || useDifferentAddress;
        const addressError = needsManualAddress ? validateAddress(destinationAddress, true) : null;

        if (!selectedNetwork) {
            setErrors({ network: 'Please select a destination network' });
            return;
        }

        if (amountError || addressError) {
            setErrors({ amount: amountError, address: addressError });
            return;
        }

        if (!rawAmount) {
            setErrors({ amount: 'Amount is required' });
            return;
        }

        // Check we have an effective destination
        if (!effectiveDestination) {
            setErrors({ address: 'Destination address is required' });
            return;
        }

        // Capture pre-bridge balances and info for progress screen
        setPreBridgeMirageBalance(balance);
        setBridgeOutAmount(rawAmount);
        setBridgeOutNetwork(selectedNetwork);
        // Note: For Solana bridge out, we'll fetch the destination balance after mint completes

        setIsSubmitting(true);
        setErrors(prev => ({ ...prev, submit: null }));
        setSubmitError('');
        setSubmitTxHash('');
        setVerificationProgress({ attempt: 0, maxAttempts: 0 });
        setErrorStage(null);
        setSubmitStage('submitting');
        stageAtError = 'submitting';

        try {
            // Convert MIRAGE to umirage (1 MIRAGE = 1,000,000 umirage)
            const amountUmirage = Math.floor(parseFloat(rawAmount) * 1_000_000);

            let result;
            if (selectedNetwork.isIbc) {
                // IBC transfer to Cosmos chains
                const sourceChannel = selectedNetwork.ibcChannel || 'channel-0';
                result = await ibcTransfer(effectiveDestination, amountUmirage, sourceChannel, 600);
            } else {
                // Attested burn for non-IBC chains (e.g., Solana)
                result = await bridgeBurn(selectedNetwork.id, effectiveDestination, amountUmirage);
            }

            if (!result || !result.success) {
                throw new Error(result?.error || 'Bridge transaction failed');
            }

            const txHash = String(result.tx_hash || '').toLowerCase();
            if (!txHash) {
                throw new Error('Missing transaction hash');
            }

            setSubmitTxHash(txHash);
            console.debug('[Bridge] Transaction submitted:', txHash);

            setSubmitStage('verifying');
            stageAtError = 'verifying';
            console.debug('[Bridge] Verification poll schedule (ms):', {
                initialDelayMs: BRIDGE_POLL_SCHEDULE.initialDelayMs,
                intervalsMs: BRIDGE_POLL_SCHEDULE.intervalsMs,
            });
            const pollResult = await pollTxStatus(txHash, {
                initialDelay: BRIDGE_POLL_SCHEDULE.initialDelayMs,
                intervals: BRIDGE_POLL_SCHEDULE.intervalsMs,
                requireIndexed: false,
                onProgress: ({ attempt, maxAttempts }) => {
                    setVerificationProgress({ attempt, maxAttempts });
                    console.debug('[Bridge] Verification attempt', attempt, 'of', maxAttempts);
                },
            });
            if (!pollResult) throw new Error('Confirmation timeout');
            if (!pollResult.success) {
                throw new Error(pollResult.error_details?.message || 'Transaction rejected');
            }

            setSubmitStage('confirmed');
            setErrors(prev => ({ ...prev, submit: null }));
            console.debug('[Bridge] Transaction confirmed:', txHash);

            // Keep final state visible until user starts a new bridge
        } catch (e) {
            const msg = e?.message || 'An unexpected error occurred';
            console.error('Bridge submission error:', e);
            setSubmitStage('error');
            setSubmitError(msg);
            setErrors({ submit: msg });
            setErrorStage(stageAtError);
        } finally {
            setIsSubmitting(false);
        }
    };

    // Calculate preview values
    // Fee is SUBTRACTED - user pays (amount), receives (amount - fee) on destination
    const parsedAmount = parseFloat(rawAmount) || 0;
    const receiveAmount = bridgeFee !== null ? Math.max(0, parsedAmount - bridgeFee) : 0;

    // Determine if we can submit
    const needsManualAddress = !selectedNetwork?.canDerive || useDifferentAddress;
    const hasValidDestination = needsManualAddress ? (destinationAddress && !errors.address) : !!derivedAddress;
    const canSubmit = selectedNetwork &&
        bridgeFee !== null && // Chain must be configured with fee
        rawAmount &&
        parseFloat(rawAmount) > 0 &&
        hasValidDestination &&
        !errors.amount &&
        !isSubmitting &&
        submitStage !== 'confirmed';

    const inputsDisabled = isSubmitting || submitStage === 'confirmed';
    const isSolanaBridge = selectedNetwork?.id === 'solana';
    const solanaCluster = useMemo(() => {
        const cluster = (chainConfigs?.solana?.solana_cluster || '').toLowerCase().trim();
        if (!cluster || cluster === 'mainnet') return '';
        return cluster;
    }, [chainConfigs]);
    const solscanClusterParam = solanaCluster ? `?cluster=${solanaCluster}` : '';

    // Format balance for display (full number with thousands separators, no decimals)
    const formatBalance = (umirage) => {
        if (!Number.isFinite(umirage)) return '...';
        const mirage = Math.floor(umirage / 1_000_000);
        return mirage.toLocaleString();
    };

    const stepOrder = ['submitting', 'verifying', 'confirmed'];
    const currentStepIndex = submitStage === 'error'
        ? stepOrder.indexOf(errorStage || 'submitting')
        : stepOrder.indexOf(submitStage);

    const getStepState = (step) => {
        if (submitStage === 'idle') return 'pending';
        const idx = stepOrder.indexOf(step);
        if (submitStage === 'error') {
            if (idx < currentStepIndex) return 'complete';
            if (idx === currentStepIndex) return 'error';
            return 'pending';
        }
        // When burn is confirmed, the Solana mint step is still pending
        if (submitStage === 'confirmed') {
            if (step === 'confirmed') {
                if (!isSolanaBridge) {
                    return 'complete';
                }
                if (mintStatus.state === 'minted') return 'complete';
                if (mintStatus.state === 'error' || mintStatus.state === 'timeout') return 'error';
                return 'active';
            }
            return 'complete';
        }
        if (idx < currentStepIndex) return 'complete';
        if (idx === currentStepIndex) return 'active';
        return 'pending';
    };

    // Format elapsed time for a step (e.g., "1.2s")
    // For completed steps, show how long they took (until next step started)
    // For active/current step, show time since it started
    const formatStepTime = (step) => {
        const stepStart = stepTimestamps[step];
        if (!stepStart) return '';

        const stepIdx = stepOrder.indexOf(step);
        const state = getStepState(step);

        // For completed steps, show duration (time until next step)
        if (state === 'complete' && stepIdx < stepOrder.length - 1) {
            const nextStep = stepOrder[stepIdx + 1];
            const nextStart = stepTimestamps[nextStep];
            if (nextStart) {
                const duration = (nextStart - stepStart) / 1000;
                return ` (${duration.toFixed(1)}s)`;
            }
        }

        // For the last step (confirmed/mint), use completedAt if available (works for complete, error, timeout)
        if (step === 'confirmed' && mintStatus.completedAt) {
            const duration = (mintStatus.completedAt - stepStart) / 1000;
            return ` (${duration.toFixed(1)}s)`;
        }

        // For active step or last completed step, show elapsed from start
        const elapsed = stepElapsed[step];
        if (elapsed === undefined || elapsed === null) return '';
        return ` (${elapsed.toFixed(1)}s)`;
    };

    const confirmedStepState = getStepState('confirmed');
    const showMintTimer = isSolanaBridge && (confirmedStepState === 'active' || confirmedStepState === 'complete' || confirmedStepState === 'error');
    const outboundAttestationPowerText = formatAttestationPower(
        outboundAttestationProgress.attestedPower,
        outboundAttestationProgress.requiredPower,
        attestationThresholdBps
    );

    return (
        <ContentGrid>
            <Helmet>
                <title>Bridge | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow>
                            <ClickableTab
                                type="button"
                                role="tab"
                                aria-selected={activeTab === 'out'}
                                $active={activeTab === 'out'}
                                onClick={() => handleTabChange('out')}
                            >
                                Bridge Out
                            </ClickableTab>
                            <ClickableTab
                                type="button"
                                role="tab"
                                aria-selected={activeTab === 'in'}
                                $active={activeTab === 'in'}
                                onClick={() => handleTabChange('in')}
                            >
                                Bridge In
                            </ClickableTab>
                        </TabsRow>
                        <ContainerBody>
                            {activeTab === 'out' && (
                                !address ? (
                                    <InfoBanner>
                                        <InfoIcon>ℹ️</InfoIcon>
                                        <span>Sign in to bridge MIRAGE tokens to other networks.</span>
                                    </InfoBanner>
                                ) : submitStage !== 'idle' ? (
                                    // Progress Screen - shown when bridge is in progress
                                    <ProgressScreenContainer>
                                        <ProgressScreenHeader>
                                            <ProgressScreenTitle>
                                                <ProgressScreenNetworkIcon
                                                    src={bridgeOutNetwork?.icon || selectedNetwork?.icon || '/images/bridges/solana.svg'}
                                                    alt=""
                                                />
                                                <ProgressScreenTitleText>
                                                    <ProgressScreenMainTitle>Bridge Out</ProgressScreenMainTitle>
                                                    <ProgressScreenSubtitle>
                                                        Mirage → {bridgeOutNetwork?.name || selectedNetwork?.name || 'Destination'}
                                                    </ProgressScreenSubtitle>
                                                </ProgressScreenTitleText>
                                            </ProgressScreenTitle>
                                            <ProgressScreenAmount>
                                                <ProgressScreenAmountValue>
                                                    {bridgeOutAmount ? parseFloat(bridgeOutAmount).toLocaleString() : (rawAmount ? parseFloat(rawAmount).toLocaleString() : '...')} MIRAGE
                                                </ProgressScreenAmountValue>
                                                <ProgressScreenAmountLabel>Amount</ProgressScreenAmountLabel>
                                            </ProgressScreenAmount>
                                        </ProgressScreenHeader>

                                        {/* Progress Steps */}
                                        <StepsCard ref={stepsRef}>
                                            <StepsList>
                                                <StepItem>
                                                    <StepDot $state={getStepState('submitting')} />
                                                    <StepText>
                                                        <StepTitle>Submitting bridge request{formatStepTime('submitting')}</StepTitle>
                                                        <StepMeta>
                                                            {getStepState('submitting') === 'complete'
                                                                ? <>Relayed by <ResponsiveAddress address={valoperAddress} startChars={16} endChars={6} /></>
                                                                : (submitStage === 'error' && errorStage === 'submitting')
                                                                    ? `Failure: ${submitError || 'submission failed'}`
                                                                    : 'Broadcasting to network...'}
                                                        </StepMeta>
                                                    </StepText>
                                                </StepItem>
                                                <StepItem>
                                                    <StepDot $state={getStepState('verifying')} />
                                                    <StepText>
                                                        <StepTitle>
                                                            {isSolanaBridge
                                                                ? 'Burning tokens on Mirage'
                                                                : 'Confirming transaction on Mirage'}
                                                            {formatStepTime('verifying')}
                                                        </StepTitle>
                                                        <StepMeta style={{ fontFamily: 'Monaco, Menlo, monospace', fontSize: '0.65rem', wordBreak: 'break-all' }}>
                                                            {submitStage === 'confirmed' ? (
                                                                <>
                                                                    {'Success: '}
                                                                    <a
                                                                        href={`/chain/rpc/tx?hash=0x${submitTxHash}`}
                                                                        target="_blank"
                                                                        rel="noopener noreferrer"
                                                                    >
                                                                        {submitTxHash}
                                                                    </a>
                                                                </>
                                                            ) : (submitStage === 'error' && errorStage === 'verifying')
                                                                ? `Failure: ${submitError || 'transaction failed'}`
                                                                : (submitTxHash || 'Waiting for confirmation')}
                                                        </StepMeta>
                                                    </StepText>
                                                </StepItem>
                                                <StepItem>
                                                    <StepDot $state={getStepState('confirmed')} />
                                                    <StepText>
                                                        <StepTitle>
                                                            {isSolanaBridge
                                                                ? 'Minting tokens on Solana'
                                                                : `IBC transfer to ${bridgeOutNetwork?.name || selectedNetwork?.name || 'destination'}`}
                                                            {showMintTimer ? formatStepTime('confirmed') : ''}
                                                        </StepTitle>
                                                        <StepMeta style={{ fontFamily: 'Monaco, Menlo, monospace', fontSize: '0.65rem', wordBreak: 'break-all' }}>
                                                            {isSolanaBridge ? (
                                                                mintStatus.state === 'minted' && mintStatus.destinationTx ? (
                                                                    <>
                                                                        {'Success: '}
                                                                        <a
                                                                            href={`https://solscan.io/tx/${mintStatus.destinationTx}${solscanClusterParam}`}
                                                                            target="_blank"
                                                                            rel="noopener noreferrer"
                                                                        >
                                                                            {mintStatus.destinationTx}
                                                                        </a>
                                                                    </>
                                                                ) : mintStatus.state === 'error' ? (
                                                                    `Error: ${mintStatus.error || 'mint confirmation failed'}`
                                                                ) : mintStatus.state === 'timeout' ? (
                                                                    'Pending: confirmation taking longer than expected.'
                                                                ) : outboundAttestationProgress.attestorCount > 0 ? (
                                                                    outboundAttestationPowerText
                                                                        ? `${outboundAttestationProgress.attestorCount} validator${outboundAttestationProgress.attestorCount !== 1 ? 's' : ''} attested (${outboundAttestationPowerText})${outboundAttestationProgress.confirmed ? ' - minting' : ''}`
                                                                        : `${outboundAttestationProgress.attestorCount} validator${outboundAttestationProgress.attestorCount !== 1 ? 's' : ''} attested${outboundAttestationProgress.confirmed ? ' - minting' : ''}`
                                                                ) : (
                                                                    'Waiting for validator attestations...'
                                                                )
                                                            ) : (
                                                                submitStage === 'confirmed'
                                                                    ? 'IBC packet sent. Tokens will arrive in ~30 seconds.'
                                                                    : 'Waiting for transaction confirmation'
                                                            )}
                                                        </StepMeta>
                                                    </StepText>
                                                </StepItem>
                                            </StepsList>
                                            {submitStage === 'error' && submitError && (
                                                <StatusBanner $error style={{ marginTop: '0.75rem' }}>
                                                    ✗ {submitError}
                                                </StatusBanner>
                                            )}
                                            {isSolanaBridge && mintStatus.state === 'minted' && (
                                                <StatusBanner $success style={{ marginTop: '0.75rem' }}>
                                                    ✓ Bridge complete! {bridgeOutAmount && bridgeFee !== null ? `${(parseFloat(bridgeOutAmount) - bridgeFee).toFixed(6).replace(/\.?0+$/, '')} ` : ''}MIRAGE minted on Solana.
                                                </StatusBanner>
                                            )}
                                            {!isSolanaBridge && submitStage === 'confirmed' && (
                                                <StatusBanner $success style={{ marginTop: '0.75rem' }}>
                                                    ✓ Bridge complete! {bridgeOutAmount && bridgeFee !== null ? `${(parseFloat(bridgeOutAmount) - bridgeFee).toFixed(6).replace(/\.?0+$/, '')} ` : ''}MIRAGE bridged to {bridgeOutNetwork?.name || selectedNetwork?.name || 'destination'}.
                                                </StatusBanner>
                                            )}
                                        </StepsCard>

                                        {/* Balance Comparison - only show when fully complete or error */}
                                        {/* For Solana: wait for mintStatus.state === 'minted', for IBC: wait for submitStage === 'confirmed' */}
                                        {(submitStage === 'error' ||
                                            (isSolanaBridge && (mintStatus.state === 'minted' || mintStatus.state === 'error' || mintStatus.state === 'timeout')) ||
                                            (!isSolanaBridge && submitStage === 'confirmed')
                                        ) && (
                                                <BalanceComparisonCard>
                                                    <BalanceComparisonTitle>
                                                        Balance Summary
                                                    </BalanceComparisonTitle>
                                                    <BalanceComparisonGrid>
                                                        <BalanceComparisonColumn>
                                                            <BalanceComparisonNetwork>
                                                                <BalanceComparisonNetworkIcon src="/favicon.svg" alt="" $isMirage />
                                                                Mirage
                                                            </BalanceComparisonNetwork>
                                                            <BalanceComparisonRow>
                                                                <BalanceComparisonLabel>Before</BalanceComparisonLabel>
                                                                <BalanceComparisonValue $dim>
                                                                    {preBridgeMirageBalance !== null ? formatBalance(preBridgeMirageBalance) : '...'} MIRAGE
                                                                </BalanceComparisonValue>
                                                            </BalanceComparisonRow>
                                                            <BalanceComparisonRow>
                                                                <BalanceComparisonLabel>After</BalanceComparisonLabel>
                                                                <BalanceComparisonValue>
                                                                    {balance !== null ? formatBalance(balance) : '...'} MIRAGE
                                                                </BalanceComparisonValue>
                                                            </BalanceComparisonRow>
                                                        </BalanceComparisonColumn>
                                                        <BalanceComparisonColumn>
                                                            <BalanceComparisonNetwork>
                                                                <BalanceComparisonNetworkIcon
                                                                    src={bridgeOutNetwork?.icon || selectedNetwork?.icon || '/images/bridges/solana.svg'}
                                                                    alt=""
                                                                />
                                                                {bridgeOutNetwork?.name || selectedNetwork?.name || 'Destination'}
                                                            </BalanceComparisonNetwork>
                                                            <BalanceComparisonRow>
                                                                <BalanceComparisonLabel>Received</BalanceComparisonLabel>
                                                                <BalanceComparisonValue $highlight={mintStatus.state === 'minted' || (!isSolanaBridge && submitStage === 'confirmed')}>
                                                                    +{bridgeOutAmount && bridgeFee !== null
                                                                        ? (parseFloat(bridgeOutAmount) - bridgeFee).toLocaleString()
                                                                        : '...'} MIRAGE
                                                                </BalanceComparisonValue>
                                                            </BalanceComparisonRow>
                                                        </BalanceComparisonColumn>
                                                    </BalanceComparisonGrid>
                                                </BalanceComparisonCard>
                                            )}

                                        {/* Action Button */}
                                        <div style={{ paddingTop: '0.5rem', paddingBottom: '2rem' }}>
                                            <Button
                                                variant="primary"
                                                fullWidth
                                                disabled={
                                                    // For Solana: wait for mint to complete (or error/timeout)
                                                    // For IBC: wait for submitStage confirmed (or error)
                                                    isSolanaBridge
                                                        ? (mintStatus.state !== 'minted' && mintStatus.state !== 'error' && mintStatus.state !== 'timeout')
                                                        : (submitStage !== 'confirmed' && submitStage !== 'error')
                                                }
                                                onClick={handleNewBridge}
                                                style={bridgeOutNetwork || selectedNetwork ? {
                                                    background: `linear-gradient(135deg, ${(bridgeOutNetwork || selectedNetwork).color} 0%, ${(bridgeOutNetwork || selectedNetwork).color}CC 100%)`,
                                                } : {}}
                                            >
                                                {(isSolanaBridge
                                                    ? (mintStatus.state === 'minted' || mintStatus.state === 'error' || mintStatus.state === 'timeout')
                                                    : (submitStage === 'confirmed' || submitStage === 'error'))
                                                    ? 'Start New Bridge'
                                                    : 'Bridging...'}
                                            </Button>
                                        </div>
                                    </ProgressScreenContainer>
                                ) : (
                                    <BridgeContainer>
                                        <BridgeLayout>
                                            {/* Balance Banner */}
                                            <BalanceBanner>
                                                <BalanceBannerLabel>Your Balance</BalanceBannerLabel>
                                                {balanceError ? (
                                                    <BalanceBannerError onClick={() => refreshBalance('retry')}>
                                                        Failed to load - click to retry
                                                    </BalanceBannerError>
                                                ) : (
                                                    <BalanceBannerRight>
                                                        <BalanceBannerValue>
                                                            {balanceLoading ? 'Loading...' : formatBalance(balance)}
                                                            {!balanceLoading && <BalanceBannerSuffix>MIRAGE</BalanceBannerSuffix>}
                                                        </BalanceBannerValue>
                                                        {!balanceLoading && <BalanceBannerNetwork>on Mirage Network</BalanceBannerNetwork>}
                                                    </BalanceBannerRight>
                                                )}
                                            </BalanceBanner>

                                            {/* Step 1: Network Selection */}
                                            <SectionTitle>
                                                <StepNumber>1</StepNumber>
                                                Select Destination
                                            </SectionTitle>
                                            <NetworkGrid>
                                                {Object.values(NETWORKS).map((network) => (
                                                    <NetworkCard
                                                        key={network.id}
                                                        type="button"
                                                        $selected={selectedNetwork?.id === network.id}
                                                        $color={network.color}
                                                        onClick={() => handleNetworkSelect(network.id)}
                                                        disabled={!network.enabled || inputsDisabled}
                                                    >
                                                        <NetworkCardContent>
                                                            <NetworkName>{network.name}</NetworkName>
                                                            <NetworkMeta>
                                                                <NetworkBadge $color={network.color}>
                                                                    {network.estimatedTime}
                                                                </NetworkBadge>
                                                            </NetworkMeta>
                                                        </NetworkCardContent>
                                                        <NetworkIcon src={network.icon} alt={network.name} />
                                                        {selectedNetwork?.id === network.id && (
                                                            <SelectedIndicator $color={network.color}>
                                                                ✓
                                                            </SelectedIndicator>
                                                        )}
                                                    </NetworkCard>
                                                ))}
                                            </NetworkGrid>

                                            {/* Step 2: Amount */}
                                            <SectionTitle>
                                                <StepNumber>2</StepNumber>
                                                {selectedNetwork ? `Send to ${selectedNetwork.name}` : 'Enter Amount'}
                                            </SectionTitle>
                                            <InputSection>
                                                <InputWrapper>
                                                    <AmountInput
                                                        type="text"
                                                        inputMode="decimal"
                                                        placeholder="0.00"
                                                        value={amount}
                                                        onChange={handleAmountChange}
                                                        $error={!!errors.amount}
                                                        disabled={!selectedNetwork || inputsDisabled}
                                                    />
                                                    <MaxButton
                                                        type="button"
                                                        onClick={handleMaxAmount}
                                                        disabled={!selectedNetwork || inputsDisabled}
                                                    >
                                                        Max
                                                    </MaxButton>
                                                    <AmountSuffix>MIRAGE</AmountSuffix>
                                                </InputWrapper>
                                                {errors.amount && (
                                                    <ErrorText>⚠ {errors.amount}</ErrorText>
                                                )}
                                            </InputSection>

                                            {/* Step 3: Destination Address */}
                                            <SectionTitle>
                                                <StepNumber>3</StepNumber>
                                                Destination Address
                                                {selectedNetwork?.canDerive && (
                                                    <HelpIconWrapper
                                                        data-tooltip="Your Mirage key works on Cosmos chains. We auto-derive your address."
                                                    >
                                                        ?
                                                    </HelpIconWrapper>
                                                )}
                                            </SectionTitle>
                                            <InputSection>
                                                {/* Cosmos chains: show derived address with option to change */}
                                                {selectedNetwork?.canDerive ? (
                                                    <>
                                                        {!useDifferentAddress ? (
                                                            <>
                                                                <AddressExplanation>
                                                                    <ExplanationIcon>💡</ExplanationIcon>
                                                                    <span>
                                                                        Your Mirage wallet key works on {selectedNetwork.name}.
                                                                        Tokens will arrive at your {selectedNetwork.name} address below.
                                                                    </span>
                                                                </AddressExplanation>
                                                                <InputLabel>Your {selectedNetwork.name} Address</InputLabel>
                                                                <DerivedAddressBox>
                                                                    <AddressText>{derivedAddress || '...'}</AddressText>
                                                                </DerivedAddressBox>
                                                                <DifferentAddressToggle
                                                                    type="button"
                                                                    onClick={() => setUseDifferentAddress(true)}
                                                                    disabled={inputsDisabled}
                                                                >
                                                                    Send to a different address →
                                                                </DifferentAddressToggle>
                                                            </>
                                                        ) : (
                                                            <>
                                                                <InputLabel>
                                                                    {selectedNetwork.name} Address
                                                                </InputLabel>
                                                                <AddressInput
                                                                    type="text"
                                                                    placeholder={`${selectedNetwork.addressPrefix}1...`}
                                                                    value={destinationAddress}
                                                                    onChange={handleAddressChange}
                                                                    $error={!!errors.address}
                                                                    disabled={inputsDisabled}
                                                                />
                                                                {errors.address && (
                                                                    <ErrorText>⚠ {errors.address}</ErrorText>
                                                                )}
                                                                <DifferentAddressToggle
                                                                    type="button"
                                                                    onClick={() => {
                                                                        setUseDifferentAddress(false);
                                                                        setDestinationAddress('');
                                                                        setErrors(prev => ({ ...prev, address: null }));
                                                                    }}
                                                                    disabled={inputsDisabled}
                                                                >
                                                                    ← Use my {selectedNetwork.name} address
                                                                </DifferentAddressToggle>
                                                            </>
                                                        )}
                                                    </>
                                                ) : (
                                                    /* Non-Cosmos chains: require manual entry */
                                                    <>
                                                        <InputLabel>
                                                            {selectedNetwork
                                                                ? `${selectedNetwork.name} Address`
                                                                : 'Recipient Address'}
                                                        </InputLabel>
                                                        <AddressInput
                                                            type="text"
                                                            placeholder={selectedNetwork?.id === 'solana'
                                                                ? 'Enter your Solana wallet address'
                                                                : 'Select a network first'}
                                                            value={destinationAddress}
                                                            onChange={handleAddressChange}
                                                            $error={!!errors.address}
                                                            disabled={!selectedNetwork || inputsDisabled}
                                                        />
                                                        {errors.address && (
                                                            <ErrorText>⚠ {errors.address}</ErrorText>
                                                        )}
                                                    </>
                                                )}
                                            </InputSection>

                                            {/* Preview */}
                                            {selectedNetwork && parsedAmount > 0 && (
                                                <PreviewCard>
                                                    <PreviewHeader>
                                                        <PreviewTitle>Summary</PreviewTitle>
                                                        <PreviewNetwork $color={selectedNetwork.color}>
                                                            <img src={selectedNetwork.icon} alt="" style={{ width: '1.25rem', height: '1.25rem' }} /> {selectedNetwork.name}
                                                        </PreviewNetwork>
                                                    </PreviewHeader>
                                                    <PreviewRow>
                                                        <PreviewLabel>Send Amount</PreviewLabel>
                                                        <PreviewValue>{formatBalance(parsedAmount * 1_000_000)} MIRAGE</PreviewValue>
                                                    </PreviewRow>
                                                    <PreviewRow>
                                                        <PreviewLabel>
                                                            Fee
                                                            <HelpIconWrapper data-tooltip="Bridge fee (burned)">?</HelpIconWrapper>
                                                        </PreviewLabel>
                                                        <PreviewValue>−{bridgeFee !== null ? bridgeFee : '?'} MIRAGE</PreviewValue>
                                                    </PreviewRow>
                                                    <Divider />
                                                    <PreviewRow>
                                                        <PreviewLabel>Receive on {selectedNetwork.name}</PreviewLabel>
                                                        <PreviewValue $highlight>
                                                            {formatBalance(receiveAmount * 1_000_000)} MIRAGE
                                                        </PreviewValue>
                                                    </PreviewRow>
                                                </PreviewCard>
                                            )}

                                            {/* Warning */}
                                            <WarningBanner>
                                                <WarningIcon>⚠️</WarningIcon>
                                                <span>
                                                    Cross-chain transfers are irreversible. Double-check the destination
                                                    address before proceeding.
                                                </span>
                                            </WarningBanner>

                                            {/* Submit */}
                                            <SubmitSection>
                                                <Button
                                                    variant="primary"
                                                    fullWidth
                                                    disabled={!canSubmit}
                                                    onClick={handleSubmit}
                                                    style={selectedNetwork ? {
                                                        background: `linear-gradient(135deg, ${selectedNetwork.color} 0%, ${selectedNetwork.color}CC 100%)`,
                                                    } : {}}
                                                >
                                                    {!selectedNetwork
                                                        ? 'Select Network'
                                                        : !amount || parseFloat(amount) <= 0
                                                            ? 'Enter Amount'
                                                            : !hasValidDestination
                                                                ? 'Enter Address'
                                                                : `Bridge to ${selectedNetwork.name}`}
                                                </Button>
                                            </SubmitSection>
                                        </BridgeLayout>
                                    </BridgeContainer>
                                )
                            )}
                            {activeTab === 'in' && (
                                <BridgeInPanel
                                    address={address}
                                    chainConfigs={chainConfigs}
                                    attestationThresholdBps={attestationThresholdBps}
                                    balance={balance}
                                    balanceLoading={balanceLoading}
                                    balanceError={balanceError}
                                    refreshBalance={refreshBalance}
                                    formatBalance={formatBalance}
                                />
                            )}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
