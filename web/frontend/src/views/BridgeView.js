import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Helmet } from 'react-helmet-async';
import styled, { keyframes, css } from 'styled-components';
import { useLocation } from 'react-router-dom';
import { bech32 } from 'bech32';
import Storage from '../utils/Storage';
import Sidebar from '../components/Sidebar';
import TopBar from '../components/TopBar';
import Button from '../components/Button';
import MobileHeader from '../components/MobileHeader';
import { ContentGrid, ModernPostFeed, TabbedContainer, TabsRow, ClickableTab, ContainerBody } from '../styled/Layout';
import { tooltipStyles } from '../components/Tooltip';
import { ibcTransfer, bridgeBurn } from '../utils/tx';

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
        icon: '/bridges/osmosis.svg',
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
        icon: '/bridges/solana.svg',
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

// Bridge fee: flat 1 MIRAGE for all transfers (burned, deflationary)
const BRIDGE_FEE = 1; // 1 MIRAGE

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
    ${tooltipStyles('top')}
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

const BalanceDisplay = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 0.5rem;
    font-size: 0.75rem;
`;

const BalanceLabel = styled.span`
    color: ${({ theme }) => theme?.colors?.subtleText || '#888'};
`;

const BalanceValue = styled.span`
    color: ${({ theme }) => theme?.colors?.text || '#fff'};
    font-weight: 600;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
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
    ${tooltipStyles('top')}
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

export default function BridgeView({ state }) {
    const location = useLocation();
    const address = Storage.load('publicKey', '') || '';
    
    // State
    const [selectedNetwork, setSelectedNetwork] = useState(null);
    const [amount, setAmount] = useState('');
    const [destinationAddress, setDestinationAddress] = useState('');
    const [useDifferentAddress, setUseDifferentAddress] = useState(false);
    const [balance, setBalance] = useState(0);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [submitStatus, setSubmitStatus] = useState(null); // 'success' | 'error' | null
    const [errors, setErrors] = useState({});
    
    // Bridge fee: flat 1 MIRAGE for all transfers (governance parameter, burned)
    const bridgeFee = BRIDGE_FEE;
    
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
    
    // Load user balance from cached config
    useEffect(() => {
        try {
            const cachedBalance = Storage.load('user_balance', 0);
            if (cachedBalance) {
                setBalance(Number(cachedBalance) || 0);
            }
        } catch (_) {}
        
        // Also check configData for balance
        try {
            const configData = localStorage.getItem('configData');
            if (configData) {
                const cached = JSON.parse(configData);
                if (cached.balance !== undefined) {
                    setBalance(Number(cached.balance) || 0);
                }
            }
        } catch (_) {}
    }, []);
    
    // Validation
    const validateAmount = useCallback((value) => {
        if (!value || value === '') return null;
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
        if (num > balance / 1_000_000) {
            return 'Insufficient balance';
        }
        return null;
    }, [selectedNetwork, balance, bridgeFee]);
    
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
    
    // Handlers
    const handleNetworkSelect = (networkId) => {
        setSelectedNetwork(NETWORKS[networkId]);
        setDestinationAddress('');
        setUseDifferentAddress(false);
        setErrors({});
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
            // Store formatted value with commas
            setAmount(formatAmountDisplay(rawValue));
            const error = validateAmount(rawValue);
            setErrors(prev => ({ ...prev, amount: error }));
        }
    };
    
    const handleMaxAmount = () => {
        if (!selectedNetwork) return;
        // Fee is subtracted from amount, so MAX is full balance
        const maxAmount = Math.max(0, balance / 1_000_000);
        setAmount(formatAmountDisplay(maxAmount.toFixed(6)));
        setErrors(prev => ({ ...prev, amount: null }));
    };
    
    const handleAddressChange = (e) => {
        const value = e.target.value;
        setDestinationAddress(value);
        const error = validateAddress(value);
        setErrors(prev => ({ ...prev, address: error }));
    };
    
    const handleSubmit = async () => {
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
        
        setIsSubmitting(true);
        setSubmitStatus(null);
        
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
            
            if (result.success) {
                setSubmitStatus('success');
                // Reset form after success
                setTimeout(() => {
                    setAmount('');
                    setDestinationAddress('');
                    setUseDifferentAddress(false);
                    setSubmitStatus(null);
                }, 5000);
            } else {
                setSubmitStatus('error');
                setErrors({ submit: result.error || 'Bridge transaction failed' });
            }
        } catch (e) {
            console.error('Bridge submission error:', e);
            setSubmitStatus('error');
            setErrors({ submit: e?.message || 'An unexpected error occurred' });
        } finally {
            setIsSubmitting(false);
        }
    };
    
    // Calculate preview values
    // Fee is SUBTRACTED - user pays (amount), receives (amount - fee) on destination
    const parsedAmount = parseFloat(rawAmount) || 0;
    const receiveAmount = Math.max(0, parsedAmount - bridgeFee); // Fee is deducted from receive
    
    // Determine if we can submit
    const needsManualAddress = !selectedNetwork?.canDerive || useDifferentAddress;
    const hasValidDestination = needsManualAddress ? (destinationAddress && !errors.address) : !!derivedAddress;
    const canSubmit = selectedNetwork && 
        rawAmount && 
        parseFloat(rawAmount) > 0 && 
        hasValidDestination && 
        !errors.amount && 
        !isSubmitting;
    
    // Format balance for display
    const formatBalance = (umirage) => {
        const mirage = umirage / 1_000_000;
        if (mirage >= 1000000) return (mirage / 1000000).toFixed(2) + 'M';
        if (mirage >= 1000) return (mirage / 1000).toFixed(2) + 'K';
        return mirage.toFixed(2);
    };
    
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
                            <ClickableTab $active={true}>Bridge</ClickableTab>
                        </TabsRow>
                        <ContainerBody>
                            {!address ? (
                                <InfoBanner>
                                    <InfoIcon>ℹ️</InfoIcon>
                                    <span>Sign in to bridge MIRAGE tokens to other networks.</span>
                                </InfoBanner>
                            ) : (
                                <BridgeContainer>
                                    <BridgeLayout>
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
                                            Enter Amount
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
                                                    disabled={!selectedNetwork}
                                                />
                                                <MaxButton 
                                                    type="button"
                                                    onClick={handleMaxAmount}
                                                    disabled={!selectedNetwork}
                                                >
                                                    Max
                                                </MaxButton>
                                                <AmountSuffix>MIRAGE</AmountSuffix>
                                            </InputWrapper>
                                            <BalanceDisplay>
                                                <BalanceLabel>Available:</BalanceLabel>
                                                <BalanceValue>{formatBalance(balance)} MIRAGE</BalanceValue>
                                            </BalanceDisplay>
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
                                                        disabled={!selectedNetwork}
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
                                                    <PreviewLabel>Send</PreviewLabel>
                                                    <PreviewValue>{formatBalance(parsedAmount * 1_000_000)} MIRAGE</PreviewValue>
                                                </PreviewRow>
                                                <PreviewRow>
                                                    <PreviewLabel data-tooltip="Flat bridge fee (burned, deflationary)">
                                                        − Fee
                                                    </PreviewLabel>
                                                    <PreviewValue>−{bridgeFee} MIRAGE</PreviewValue>
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
                                                loading={isSubmitting}
                                                onClick={handleSubmit}
                                                style={selectedNetwork ? {
                                                    background: `linear-gradient(135deg, ${selectedNetwork.color} 0%, ${selectedNetwork.color}CC 100%)`,
                                                } : {}}
                                            >
                                                {isSubmitting 
                                                    ? 'Processing...'
                                                    : !selectedNetwork 
                                                        ? 'Select Network'
                                                        : !amount || parseFloat(amount) <= 0
                                                            ? 'Enter Amount'
                                                            : !hasValidDestination
                                                                ? 'Enter Address'
                                                                : `Bridge to ${selectedNetwork.name}`
                                                }
                                            </Button>
                                            
                                            {submitStatus === 'success' && (
                                                <StatusBanner $success>
                                                    ✓ Bridge transaction submitted successfully!
                                                </StatusBanner>
                                            )}
                                            {submitStatus === 'error' && errors.submit && (
                                                <StatusBanner $error>
                                                    ✗ {errors.submit}
                                                </StatusBanner>
                                            )}
                                        </SubmitSection>
                                    </BridgeLayout>
                                </BridgeContainer>
                            )}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>
    );
}
