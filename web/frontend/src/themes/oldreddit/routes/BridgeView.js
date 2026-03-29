import { Helmet } from "react-helmet-async";
import styled, { keyframes, css } from "styled-components";
import Button from "../components/Button.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, TabsRow, ClickableTab, ContainerBody } from "../Layout";
import { tooltipStyles } from "../components/Tooltip.js";
import { useSolanaBridgeInFlow, useBridgeInPanel, useBridge, NETWORKS, truncateAddress, SOURCE_NETWORKS } from "../../../logic/useBridge";
// Responsive address component - shows truncated on mobile, full on desktop
const ResponsiveAddress = ({
    address,
    startChars = 16,
    endChars = 6
}) => {
    if (!address) return null;
    const truncated = truncateAddress(address, startChars, endChars);
    return <>
        <span className="address-full">{address}</span>
        <span className="address-truncated">{truncated}</span>
    </>;
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
const SectionTitle = styled.h3`
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: ${({
    theme
}) => theme.colors.subtleText};
    margin: ${({
    theme
}) => theme.layout.sectionMarginBottom};
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
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    background: ${({
    theme
}) => theme.caps.flatMode ? theme.colors.panelAlt : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'};
    color: #fff;
    font-size: ${({
    theme
}) => theme.layout.tinySize};
    font-weight: 700;
`;
const NetworkGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: ${({
    theme
}) => theme.layout.formRowGap};
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    
    @media (max-width: 600px) {
        grid-template-columns: 1fr;
    }
`;
const NetworkCard = styled.button`
    background: ${({
    theme,
    $selected,
    $color
}) => theme.caps.flatMode ? $selected ? theme.colors.panelAlt : theme.colors.panel : $selected ? `linear-gradient(135deg, ${$color}22 0%, ${$color}11 100%)` : theme.colors.panel};
    border: 2px solid ${({
    $selected,
    $color,
    theme
}) => $selected ? $color : theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    padding: ${({
    theme
}) => theme.layout.cardPadding};
    cursor: pointer;
    transition: all 0.2s ease;
    text-align: left;
    position: relative;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: ${({
    theme
}) => theme.layout.formRowGap};
    
    &:hover:not(:disabled) {
        border-color: ${({
    $color
}) => $color};
        transform: ${({
    theme
}) => theme.caps.flatMode ? 'none' : 'translateY(-2px)'};
        box-shadow: ${({
    theme,
    $color
}) => theme.caps.flatMode ? 'none' : `0 4px 12px ${$color}33`};
    }
    
    &:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    ${({
    $selected,
    $color,
    theme
}) => $selected && css`
        box-shadow: ${theme.caps.flatMode ? 'none' : `0 0 0 1px ${$color}44, 0 4px 12px ${$color}22`};
    `}
`;
const NetworkCardContent = styled.div`
    flex: 1;
    min-width: 0;
`;
const NetworkIcon = styled.img`
    width: ${({
    theme
}) => theme.layout.sectionSize};
    height: ${({
    theme
}) => theme.layout.sectionSize};
    flex-shrink: 0;
    object-fit: contain;
`;
const NetworkName = styled.div`
    font-size: ${({
    theme
}) => theme.layout.sectionSize};
    font-weight: 700;
    color: ${({
    theme
}) => theme.colors.text};
    margin-bottom: 0.2rem;
`;
const NetworkMeta = styled.div`
    font-size: ${({
    theme
}) => theme.layout.smallSize};
    color: ${({
    theme
}) => theme.colors.subtleText};
    display: flex;
    align-items: center;
    gap: 0.35rem;
`;
const NetworkBadge = styled.span`
    display: inline-flex;
    align-items: center;
    padding: ${({
    theme
}) => theme.layout.buttonPadding};
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    font-size: ${({
    theme
}) => theme.layout.tinySize};
    font-weight: 600;
    background: ${({
    $color
}) => `${$color}22`};
    color: ${({
    $color
}) => $color};
`;
const SelectedIndicator = styled.div`
    position: absolute;
    top: ${({
    theme
}) => theme.layout.cardGap};
    right: ${({
    theme
}) => theme.layout.cardGap};
    width: 1rem;
    height: 1rem;
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    background: ${({
    $color
}) => $color};
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: ${({
    theme
}) => theme.layout.tinySize};
    color: #fff;
    animation: ${fadeIn} 0.2s ease-out;
`;
const InputSection = styled.div`
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginTop};
`;
const InputLabel = styled.label`
    display: block;
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    font-weight: 600;
    color: ${({
    theme
}) => theme.colors.subtleText};
    margin-bottom: 0.5rem;
`;
const InputWrapper = styled.div`
    position: relative;
    display: flex;
    align-items: center;
`;
const AmountInput = styled.input`
    width: 100%;
    padding: ${({
    theme
}) => theme.layout.inputPadding};
    border: 1px solid ${({
    theme,
    $error
}) => $error ? '#f56565' : theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    background: ${({
    theme
}) => theme.colors.panelAlt};
    color: ${({
    theme
}) => theme.colors.text};
    font-size: ${({
    theme
}) => theme.layout.sectionSize};
    font-weight: 600;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    outline: none;
    transition: all 0.2s ease;
    
    &::placeholder {
        color: ${({
    theme
}) => theme.colors.subtleText};
        font-weight: 400;
    }
    
    &:focus {
        border-color: ${({
    theme,
    $error
}) => $error ? '#f56565' : theme.colors.link};
        box-shadow: ${({
    theme,
    $error
}) => theme.layout.focusRing};
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
    right: ${({
    theme
}) => theme.layout.cardPadding};
    font-size: ${({
    theme
}) => theme.layout.monoSize};
    font-weight: 600;
    color: ${({
    theme
}) => theme.colors.subtleText};
    pointer-events: none;
`;
const MaxButton = styled.button`
    position: absolute;
    right: ${({
    theme
}) => theme.layout.containerPadding};
    padding: ${({
    theme
}) => theme.layout.buttonPadding};
    border: none;
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    background: ${({
    theme
}) => theme.caps.flatMode ? theme.colors.link : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'};
    color: #fff;
    font-size: ${({
    theme
}) => theme.layout.tinySize};
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    cursor: pointer;
    transition: all 0.2s ease;
    
    &:hover {
        transform: ${({
    theme
}) => theme.caps.flatMode ? 'none' : 'scale(1.05)'};
        box-shadow: ${({
    theme
}) => theme.caps.flatMode ? 'none' : '0 2px 8px rgba(102, 126, 234, 0.4)'};
    }
`;
const AddressInput = styled.input`
    width: 100%;
    padding: ${({
    theme
}) => theme.layout.inputPadding};
    border: 1px solid ${({
    theme,
    $error
}) => $error ? '#f56565' : theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    background: ${({
    theme
}) => theme.colors.panelAlt};
    color: ${({
    theme
}) => theme.colors.text};
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    outline: none;
    transition: all 0.2s ease;
    
    &::placeholder {
        color: ${({
    theme
}) => theme.colors.subtleText};
        font-family: inherit;
    }
    
    &:focus {
        border-color: ${({
    theme,
    $error
}) => $error ? '#f56565' : theme.colors.link};
        box-shadow: ${({
    theme,
    $error
}) => theme.layout.focusRing};
    }
`;
const ErrorText = styled.div`
    color: #f56565;
    font-size: ${({
    theme
}) => theme.layout.smallSize};
    margin-top: 0.35rem;
    display: flex;
    align-items: center;
    gap: 0.25rem;
`;
const PreviewCard = styled.div`
    background: ${({
    theme
}) => theme.caps.flatMode ? theme.colors.panelAlt : `linear-gradient(135deg, 
        ${theme.colors.panelAlt} 0%, 
        ${theme.colors.panel} 100%)`};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    padding: ${({
    theme
}) => theme.layout.containerPadding};
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
`;
const PreviewHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    padding-bottom: ${({
    theme
}) => theme.layout.cardGap};
    border-bottom: 1px solid ${({
    theme
}) => theme.colors.border};
`;
const PreviewTitle = styled.span`
    font-size: ${({
    theme
}) => theme.layout.monoSize};
    font-weight: 600;
    color: ${({
    theme
}) => theme.colors.text};
`;
const PreviewNetwork = styled.span`
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    color: ${({
    $color
}) => $color};
    font-weight: 600;
`;
const PreviewRow = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: ${({
    theme
}) => theme.layout.formRowMargin};
    font-size: ${({
    theme
}) => theme.layout.monoSize};
    gap: 1rem;
`;
const PreviewLabel = styled.span`
    color: ${({
    theme
}) => theme.colors.subtleText};
    white-space: nowrap;
    flex-shrink: 0;
`;
const PreviewValue = styled.span`
    color: ${({
    theme
}) => theme.colors.text};
    font-weight: 500;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    text-align: right;
    white-space: nowrap;
    
    ${({
    $highlight
}) => $highlight && css`
        color: #48bb78;
        font-weight: 700;
    `}
`;
const Divider = styled.div`
    height: 1px;
    background: ${({
    theme
}) => theme.colors.border};
    margin: 0.5rem 0;
`;
const SubmitSection = styled.div`
    margin-top: 0;
`;
const WarningBanner = styled.div`
    display: flex;
    align-items: flex-start;
    gap: ${({
    theme
}) => theme.layout.cardGap};
    padding: ${({
    theme
}) => theme.layout.bannerPadding};
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    background: rgba(245, 158, 11, 0.1);
    border: 1px solid rgba(245, 158, 11, 0.3);
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    color: #f59e0b;
    line-height: 1.5;
`;
const WarningIcon = styled.span`
    font-size: ${({
    theme
}) => theme.layout.labelSize};
    flex-shrink: 0;
`;
const InfoBanner = styled.div`
    display: flex;
    align-items: flex-start;
    gap: ${({
    theme
}) => theme.layout.formRowGap};
    padding: ${({
    theme
}) => theme.layout.cardPadding};
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    background: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    color: ${({
    theme
}) => theme.colors.subtleText};
    line-height: 1.5;
`;
const InfoIcon = styled.span`
    font-size: ${({
    theme
}) => theme.layout.labelSize};
    flex-shrink: 0;
`;
const StatusBanner = styled.div`
    display: flex;
    align-items: center;
    justify-content: center;
    gap: ${({
    theme
}) => theme.layout.formRowGap};
    padding: ${({
    theme
}) => theme.layout.bannerPadding};
    margin-top: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    background: ${({
    $success,
    $error
}) => $success ? 'rgba(72, 187, 120, 0.1)' : $error ? 'rgba(239, 68, 68, 0.1)' : 'rgba(102, 126, 234, 0.1)'};
    border: 1px solid ${({
    $success,
    $error
}) => $success ? 'rgba(72, 187, 120, 0.3)' : $error ? 'rgba(239, 68, 68, 0.3)' : 'rgba(102, 126, 234, 0.3)'};
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    font-size: ${({
    theme
}) => theme.layout.monoSize};
    color: ${({
    $success,
    $error
}) => $success ? '#48bb78' : $error ? '#ef4444' : '#667eea'};
    font-weight: 500;
    animation: ${fadeIn} 0.3s ease-out;
`;
const StepsCard = styled.div`
    background: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    padding: ${({
    theme
}) => theme.layout.cardPadding};
    margin-top: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
`;
const StepsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: ${({
    theme
}) => theme.layout.cardGap};
`;
const StepItem = styled.div`
    display: flex;
    align-items: center;
    gap: ${({
    theme
}) => theme.layout.cardGap};
    font-size: ${({
    theme
}) => theme.layout.monoSize};
`;
const StepDot = styled.span`
    width: 0.65rem;
    height: 0.65rem;
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    flex-shrink: 0;
    background: ${({
    $state,
    theme
}) => {
        if ($state === 'complete') return '#48bb78';
        if ($state === 'active') return '#667eea';
        if ($state === 'error') return '#ef4444';
        return theme.colors.border;
    }};
    box-shadow: ${({
        $state,
        theme
    }) => theme.caps.flatMode || $state !== 'active' ? 'none' : '0 0 0 3px rgba(102, 126, 234, 0.2)'};
`;
const StepText = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
`;
const StepTitle = styled.span`
    color: ${({
    theme
}) => theme.colors.text};
    font-weight: 600;
`;
const StepMeta = styled.span`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: ${({
    theme
}) => theme.layout.smallSize};
    
    a {
        color: ${({
    theme
}) => theme.colors.link};
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
    padding: ${({
    theme
}) => theme.layout.containerPaddingCompact};
`;
const ProgressScreenHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginTop};
    padding-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    border-bottom: 1px solid ${({
    theme
}) => theme.colors.border};
`;
const ProgressScreenTitle = styled.div`
    display: flex;
    align-items: center;
    gap: ${({
    theme
}) => theme.layout.formRowGap};
`;
const ProgressScreenNetworkIcon = styled.img`
    width: ${({
    theme
}) => theme.layout.sectionSize};
    height: ${({
    theme
}) => theme.layout.sectionSize};
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    ${({
    $isMirage,
    theme
}) => $isMirage && `
        filter: brightness(0) ${theme.name === "dark" === false ? 'invert(0)' : 'invert(1)'};
    `}
`;
const ProgressScreenTitleText = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
`;
const ProgressScreenMainTitle = styled.span`
    font-size: ${({
    theme
}) => theme.layout.sectionSize};
    font-weight: 700;
    color: ${({
    theme
}) => theme.colors.text};
`;
const ProgressScreenSubtitle = styled.span`
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    color: ${({
    theme
}) => theme.colors.subtleText};
`;
const ProgressScreenAmount = styled.div`
    text-align: right;
`;
const ProgressScreenAmountValue = styled.div`
    font-size: ${({
    theme
}) => theme.layout.sectionSize};
    font-weight: 700;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    color: ${({
    theme
}) => theme.colors.text};
`;
const ProgressScreenAmountLabel = styled.div`
    font-size: ${({
    theme
}) => theme.layout.smallSize};
    color: ${({
    theme
}) => theme.colors.subtleText};
`;
const BalanceComparisonCard = styled.div`
    background: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    padding: ${({
    theme
}) => theme.layout.containerPadding};
    margin-top: ${({
    theme
}) => theme.layout.sectionMarginTop};
`;
const BalanceComparisonTitle = styled.div`
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: ${({
    theme
}) => theme.colors.subtleText};
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;
const BalanceComparisonGrid = styled.div`
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: ${({
    theme
}) => theme.layout.formRowGap};
    
    @media (max-width: 500px) {
        grid-template-columns: 1fr;
    }
`;
const BalanceComparisonColumn = styled.div`
    display: flex;
    flex-direction: column;
    gap: ${({
    theme
}) => theme.layout.cardGap};
`;
const BalanceComparisonNetwork = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: ${({
    theme
}) => theme.layout.monoSize};
    font-weight: 600;
    color: ${({
    theme
}) => theme.colors.text};
    margin-bottom: 0.25rem;
`;
const BalanceComparisonNetworkIcon = styled.img`
    width: ${({
    theme
}) => theme.layout.sectionSize};
    height: ${({
    theme
}) => theme.layout.sectionSize};
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    ${({
    $isMirage,
    theme
}) => $isMirage && `
        filter: brightness(0) ${theme.name === "dark" === false ? 'invert(0)' : 'invert(1)'};
    `}
`;
const BalanceComparisonRow = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: ${({
    theme
}) => theme.layout.monoSize};
    padding: ${({
    theme
}) => theme.layout.formRowMargin};
    border-bottom: 1px solid ${({
    theme
}) => theme.colors.border};
    
    &:last-child {
        border-bottom: none;
    }
`;
const BalanceComparisonLabel = styled.span`
    color: ${({
    theme
}) => theme.colors.subtleText};
`;
const BalanceComparisonValue = styled.span`
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-weight: 500;
    color: ${({
    theme,
    $highlight,
    $dim
}) => $highlight ? '#48bb78' : $dim ? theme.colors.subtleText : theme.colors.text};
`;

// Derived address display
const DerivedAddressBox = styled.div`
    background: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    padding: ${({
    theme
}) => theme.layout.inputPadding};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: ${({
    theme
}) => theme.layout.monoSize};
    color: ${({
    theme
}) => theme.colors.text};
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
    color: ${({
    theme
}) => theme.colors.link};
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
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    background: ${({
    theme
}) => theme.colors.border};
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 700;
    cursor: help;
    margin-left: 0.35rem;
    ${tooltipStyles()}
`;
const AddressExplanation = styled.div`
    display: flex;
    align-items: flex-start;
    gap: ${({
    theme
}) => theme.layout.cardGap};
    padding: ${({
    theme
}) => theme.layout.cardPadding};
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    background: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    font-size: ${({
    theme
}) => theme.layout.smallSize};
    color: ${({
    theme
}) => theme.colors.subtleText};
    line-height: 1.5;
`;
const ExplanationIcon = styled.span`
    font-size: ${({
    theme
}) => theme.layout.inputSize};
    flex-shrink: 0;
`;

// Source network configurations for Bridge In (where tokens come FROM)

// Solana wallet button
const SolanaWalletButton = styled.button`
    display: flex;
    align-items: center;
    justify-content: center;
    gap: ${({
    theme
}) => theme.layout.cardGap};
    width: 100%;
    padding: ${({
    theme
}) => theme.layout.bannerPadding};
    border: 2px solid #14F195;
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    background: ${({
    theme
}) => theme.caps.flatMode ? theme.colors.panelAlt : 'rgba(20, 241, 149, 0.1)'};
    color: #14F195;
    font-size: ${({
    theme
}) => theme.layout.sectionSize};
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    
    &:hover:not(:disabled) {
        background: ${({
    theme
}) => theme.caps.flatMode ? theme.colors.panelAlt : 'rgba(20, 241, 149, 0.2)'};
        transform: ${({
    theme
}) => theme.caps.flatMode ? 'none' : 'translateY(-1px)'};
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
    background: ${({
    theme
}) => theme.colors.panelAlt};
    border: 1px solid #14F195;
    border-radius: ${({
    theme
}) => theme.layout.containerRadius};
    padding: ${({
    theme
}) => theme.layout.bannerPadding};
`;
const WalletRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: ${({
    theme
}) => theme.layout.cardGap};
`;
const WalletAddress = styled.span`
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: ${({
    theme
}) => theme.layout.monoSize};
    color: ${({
    theme
}) => theme.colors.text};
`;
const DisconnectButton = styled.button`
    background: transparent;
    border: none;
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.7rem;
    cursor: pointer;
    padding: 0.25rem 0.5rem;
    
    &:hover {
        color: #f56565;
    }
`;

// Solana RPC endpoints

// Solana Bridge In Flow Component
function SolanaBridgeInFlow({
    mirageAddress,
    theme,
    chainConfigs,
    attestationThresholdBps,
    onBridgingChange
}) {
    const {
        solanaWallet,
        isConnecting,
        amount,
        setAmount,
        isBridging,
        bridgeStatus,
        bridgeError,
        bridgeTxHash,
        mintStatus,
        attestationProgress,
        buttonRef,
        preBridgeSolanaBalance,
        bridgeAmount,
        solanaCluster,
        solscanClusterParam,
        formatStepTime,
        attestationPowerText,
        getStepState,
        formatAmountDisplay,
        connectPhantom,
        disconnectWallet,
        handleBridge,
        amountError,
        canBridge,
        handleNewBridge,
        showProgressScreen
    } = useSolanaBridgeInFlow({
        mirageAddress,
        theme,
        chainConfigs,
        attestationThresholdBps,
        onBridgingChange
    });
    // If showing progress screen, render the progress view
    if (showProgressScreen) {
        return <ProgressScreenContainer>
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
                            <StepMeta style={{
                                fontFamily: 'Monaco, Menlo, monospace',
                                fontSize: '0.65rem',
                                wordBreak: 'break-all'
                            }}>
                                {bridgeStatus === 'confirming' ? 'Waiting for wallet confirmation' : bridgeStatus === 'error' && !bridgeTxHash ? `Failure: ${bridgeError || 'transaction failed'}` : bridgeTxHash ? <>
                                    {'Success: '}
                                    <a href={`https://solscan.io/tx/${bridgeTxHash}${solscanClusterParam}`} target="_blank" rel="noopener noreferrer">
                                        {bridgeTxHash}
                                    </a>
                                </> : 'Waiting for wallet confirmation'}
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
                                {bridgeStatus === 'confirming' ? 'Waiting for token lock confirmation' : attestationProgress.attestorCount > 0 ? attestationPowerText ? `${attestationProgress.attestorCount} validator${attestationProgress.attestorCount !== 1 ? 's' : ''} attested (${attestationPowerText})${attestationProgress.confirmed ? ' - threshold reached' : ''}` : `${attestationProgress.attestorCount} validator${attestationProgress.attestorCount !== 1 ? 's' : ''} attested${attestationProgress.confirmed ? ' - threshold reached' : ''}` : mintStatus.state === 'minted' || bridgeStatus === 'complete' ? 'Threshold reached' : 'Waiting for validator attestations...'}
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
                            <StepMeta style={{
                                fontFamily: 'Monaco, Menlo, monospace',
                                fontSize: '0.65rem',
                                wordBreak: 'break-all'
                            }}>
                                {bridgeStatus === 'complete' && mintStatus.txHash ? <>
                                    {'Success: '}
                                    <a href={`/chain/rpc/tx?hash=0x${mintStatus.txHash}`} target="_blank" rel="noopener noreferrer">
                                        {mintStatus.txHash}
                                    </a>
                                </> : bridgeStatus === 'complete' ? 'MIRAGE minted to your address' : mintStatus.state === 'timeout' ? 'Taking longer than expected - check your balance' : mintStatus.state === 'error' ? `Error: ${mintStatus.error || 'mint failed'}` : 'Waiting for attestation'}
                            </StepMeta>
                        </StepText>
                    </StepItem>
                </StepsList>

                {bridgeStatus === 'error' && bridgeError && <StatusBanner $error style={{
                    marginTop: '0.75rem'
                }}>
                    ✗ {bridgeError}
                </StatusBanner>}

                {bridgeStatus === 'complete' && <StatusBanner $success style={{
                    marginTop: '0.75rem'
                }}>
                    ✓ Bridge complete! {bridgeAmount ? `${bridgeAmount} ` : ''}MIRAGE minted to your address.
                </StatusBanner>}
            </StepsCard>

            {/* Balance Comparison - only show when mint is fully complete (or error/timeout) */}
            {(mintStatus.state === 'minted' || mintStatus.state === 'error' || mintStatus.state === 'timeout' || bridgeStatus === 'error') && <BalanceComparisonCard>
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
            </BalanceComparisonCard>}

            {/* Action Button */}
            <div ref={buttonRef} style={{
                paddingTop: '0.5rem',
                paddingBottom: '2rem'
            }}>
                <Button variant="primary" fullWidth disabled={mintStatus.state !== 'minted' && mintStatus.state !== 'error' && mintStatus.state !== 'timeout' && bridgeStatus !== 'error'} onClick={handleNewBridge} style={{
                    background: 'linear-gradient(135deg, #14F195 0%, #0ea66e 100%)'
                }}>
                    {mintStatus.state === 'minted' || mintStatus.state === 'error' || mintStatus.state === 'timeout' || bridgeStatus === 'error' ? 'Start New Bridge' : 'Bridging...'}
                </Button>
            </div>
        </ProgressScreenContainer>;
    }
    return <>
        {/* Step 2: Connect Solana Wallet */}
        <SectionTitle>
            <StepNumber>2</StepNumber>
            Connect Solana Wallet
        </SectionTitle>
        <InputSection>
            {/* Network indicator */}
            {solanaCluster !== 'mainnet' && <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.5rem 0.75rem',
                marginBottom: '0.75rem',
                background: 'rgba(20, 241, 149, 0.1)',
                borderRadius: '0.5rem',
                border: '1px solid rgba(20, 241, 149, 0.3)',
                fontSize: '0.8rem'
            }}>
                <span style={{
                    color: '#14F195',
                    fontWeight: 600
                }}>
                    {solanaCluster.toUpperCase()}
                </span>
                <span style={{
                    color: theme.colors.subtleText
                }}>
                    — Set Phantom to {solanaCluster} in Settings → Developer Settings
                </span>
            </div>}
            {!solanaWallet ? <>
                <SolanaWalletButton type="button" onClick={connectPhantom} disabled={isConnecting}>
                    <img src="/images/bridges/solana.svg" alt="Solana" />
                    {isConnecting ? 'Connecting...' : 'Connect Phantom'}
                </SolanaWalletButton>
                {bridgeError && bridgeStatus === 'idle' && <ErrorText style={{
                    marginTop: '0.5rem'
                }}>⚠ {bridgeError}</ErrorText>}
            </> : <ConnectedWalletBox>
                <WalletRow>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                        minWidth: 0,
                        flex: 1
                    }}>
                        <img src="/images/bridges/solana.svg" alt="Solana" style={{
                            width: '1.25rem',
                            height: '1.25rem',
                            flexShrink: 0
                        }} />
                        <WalletAddress style={{
                            overflow: 'hidden',
                            textOverflow: 'ellipsis'
                        }}>{solanaWallet.address}</WalletAddress>
                    </div>
                    <DisconnectButton type="button" onClick={disconnectWallet} style={{
                        flexShrink: 0
                    }}>
                        Disconnect
                    </DisconnectButton>
                </WalletRow>
                <div style={{
                    display: 'flex',
                    gap: '0.75rem',
                    flexWrap: 'wrap',
                    marginTop: '0.5rem'
                }}>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.4rem',
                        padding: '0.35rem 0.6rem',
                        background: 'rgba(20, 241, 149, 0.1)',
                        borderRadius: '6px',
                        border: '1px solid rgba(20, 241, 149, 0.3)'
                    }}>
                        <span style={{
                            fontSize: '0.9rem',
                            fontWeight: 600,
                            color: theme.colors.text
                        }}>
                            {solanaWallet.mirageBalance !== null ? solanaWallet.mirageBalance.toLocaleString() : '...'}
                        </span>
                        <span style={{
                            fontSize: '0.7rem',
                            color: theme.colors.subtleText,
                            fontWeight: 500
                        }}>MIRAGE</span>
                    </div>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.4rem',
                        padding: '0.35rem 0.6rem',
                        background: 'rgba(20, 241, 149, 0.1)',
                        borderRadius: '6px',
                        border: '1px solid rgba(20, 241, 149, 0.3)'
                    }}>
                        <span style={{
                            fontSize: '0.9rem',
                            fontWeight: 600,
                            color: theme.colors.text
                        }}>
                            {solanaWallet.solBalance !== null ? solanaWallet.solBalance.toLocaleString(undefined, {
                                minimumFractionDigits: 4,
                                maximumFractionDigits: 4
                            }) : '...'}
                        </span>
                        <span style={{
                            fontSize: '0.7rem',
                            color: theme.colors.subtleText,
                            fontWeight: 500
                        }}>SOL</span>
                    </div>
                </div>
                {solanaWallet.mirageBalance === 0 && solanaCluster !== 'mainnet' && <div style={{
                    marginTop: '0.5rem',
                    padding: '0.5rem',
                    background: 'rgba(245, 158, 11, 0.1)',
                    borderRadius: '0.25rem',
                    fontSize: '0.75rem',
                    color: '#f59e0b'
                }}>
                    No MIRAGE tokens found. Make sure Phantom is set to {solanaCluster}.
                </div>}
            </ConnectedWalletBox>}
        </InputSection>

        {/* Step 3: Enter Amount (only show when connected) */}
        {solanaWallet && <>
            <SectionTitle>
                <StepNumber>3</StepNumber>
                Send to Mirage
            </SectionTitle>
            <InputSection>
                {/* Inline balance display */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'flex-end',
                    fontSize: '0.75rem',
                    color: theme.colors.subtleText,
                    marginBottom: '0.35rem'
                }}>
                    Balance: {solanaWallet?.mirageBalance !== null ? `${solanaWallet.mirageBalance.toLocaleString()} MIRAGE` : '...'}
                </div>
                <InputWrapper>
                    <AmountInput type="text" inputMode="decimal" placeholder="0.00" value={amount} onChange={e => {
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
                    }} $error={!!amountError} disabled={isBridging} />
                    {solanaWallet.mirageBalance !== null && <MaxButton type="button" onClick={() => setAmount(formatAmountDisplay(String(solanaWallet.mirageBalance)))} disabled={isBridging}>
                        Max
                    </MaxButton>}
                    <AmountSuffix>MIRAGE</AmountSuffix>
                </InputWrapper>
                {amountError && <ErrorText>⚠ {amountError}</ErrorText>}
            </InputSection>

            {/* Step 4: Destination */}
            <SectionTitle>
                <StepNumber>4</StepNumber>
                Destination
            </SectionTitle>
            <InputSection>
                <div style={{
                    fontSize: '0.75rem',
                    color: theme.colors.subtleText,
                    marginBottom: '0.35rem'
                }}>
                    Tokens will arrive at your Mirage address:
                </div>
                <div style={{
                    fontFamily: "'Monaco', 'Menlo', 'Ubuntu Mono', monospace",
                    fontSize: '0.8rem',
                    padding: '0.5rem 0.75rem',
                    background: theme.colors.panelAlt,
                    border: `1px solid ${theme.colors.border}`,
                    borderRadius: '6px',
                    wordBreak: 'break-all',
                    color: theme.colors.text
                }}>
                    {mirageAddress}
                </div>
            </InputSection>

            {/* Preview Card - matches Bridge Out style */}
            {amount && parseFloat(amount.replace(/,/g, '')) > 0 && <PreviewCard>
                <PreviewHeader>
                    <PreviewTitle>Summary</PreviewTitle>
                    <PreviewNetwork $color="#14F195">
                        <img src="/images/bridges/solana.svg" alt="" style={{
                            width: '1.25rem',
                            height: '1.25rem'
                        }} /> Solana
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
            </PreviewCard>}

            {/* Bridge Button */}
            <div ref={buttonRef} style={{
                paddingBottom: '1rem'
            }}>
                <Button variant="primary" fullWidth disabled={!canBridge} onClick={handleBridge} style={{
                    background: 'linear-gradient(135deg, #14F195 0%, #0ea66e 100%)'
                }}>
                    {!amount || parseFloat(amount) <= 0 ? 'Enter Amount' : `Bridge ${amount} MIRAGE`}
                </Button>
            </div>
        </>}
    </>;
}

// Bridge In Panel Component
function BridgeInPanel({
    address,
    chainConfigs,
    attestationThresholdBps,
    balance,
    balanceLoading,
    balanceError,
    refreshBalance,
    formatBalance
}) {
    const {
        theme,
        selectedSource,
        isSolanaBridging,
        handleSourceSelect,
        handleSolanaBridgingChange
    } = useBridgeInPanel({
        address,
        chainConfigs,
        attestationThresholdBps,
        balance,
        balanceLoading,
        balanceError,
        refreshBalance,
        formatBalance
    });
    if (!address) {
        return <BridgeContainer>
            <BridgeLayout>
                <InfoBanner>
                    <InfoIcon>ℹ️</InfoIcon>
                    <span>Sign in to bridge MIRAGE tokens from other networks.</span>
                </InfoBanner>
            </BridgeLayout>
        </BridgeContainer>;
    }
    return <BridgeContainer>
        <BridgeLayout>
            {/* Hide form elements when Solana bridging is in progress */}
            {!isSolanaBridging && <>
                {/* Step 1: Source Network Selection */}
                <SectionTitle>
                    <StepNumber>1</StepNumber>
                    Select Source Chain
                </SectionTitle>
                <NetworkGrid>
                    {Object.values(SOURCE_NETWORKS).map(network => <NetworkCard key={network.id} type="button" $selected={selectedSource?.id === network.id} $color={network.color} onClick={() => handleSourceSelect(network.id)} disabled={!network.enabled}>
                        <NetworkCardContent>
                            <NetworkName>{network.name}</NetworkName>
                            <NetworkMeta>
                                <NetworkBadge $color={network.color}>
                                    {network.estimatedTime}
                                </NetworkBadge>
                            </NetworkMeta>
                        </NetworkCardContent>
                        <NetworkIcon src={network.icon} alt={network.name} />
                        {selectedSource?.id === network.id && <SelectedIndicator $color={network.color}>
                            ✓
                        </SelectedIndicator>}
                    </NetworkCard>)}
                </NetworkGrid>
            </>}

            {/* Solana Bridge In Flow */}
            {selectedSource?.id === 'solana' && <SolanaBridgeInFlow mirageAddress={address} theme={theme} chainConfigs={chainConfigs} attestationThresholdBps={attestationThresholdBps} onBridgingChange={handleSolanaBridgingChange} />}

            {/* Info when no source selected */}
            {!selectedSource && <InfoBanner>
                <InfoIcon>ℹ️</InfoIcon>
                <span>
                    Select a source chain above to see instructions for bridging MIRAGE tokens to your Mirage wallet.
                </span>
            </InfoBanner>}
        </BridgeLayout>
    </BridgeContainer>;
}
export default function BridgeView({
    state
}) {
    const {
        theme,
        address,
        valoperAddress,
        activeTab,
        selectedNetwork,
        amount,
        destinationAddress,
        setDestinationAddress,
        useDifferentAddress,
        setUseDifferentAddress,
        balance,
        balanceLoading,
        balanceError,
        submitStage,
        submitError,
        submitTxHash,
        errorStage,
        errors,
        setErrors,
        stepsRef,
        mintStatus,
        outboundAttestationProgress,
        chainConfigs,
        attestationThresholdBps,
        preBridgeMirageBalance,
        bridgeOutAmount,
        bridgeOutNetwork,
        bridgeFee,
        derivedAddress,
        refreshBalance,
        handleNewBridge,
        handleTabChange,
        handleNetworkSelect,
        rawAmount,
        handleAmountChange,
        handleMaxAmount,
        handleAddressChange,
        handleSubmit,
        parsedAmount,
        receiveAmount,
        hasValidDestination,
        canSubmit,
        inputsDisabled,
        isSolanaBridge,
        solscanClusterParam,
        formatBalance,
        getStepState,
        formatStepTime,
        showMintTimer,
        outboundAttestationPowerText
    } = useBridge({
        state
    });
    return <ContentGrid>
        <Helmet>
            <title>Bridge | Mirage</title>
        </Helmet>
        <div>
            <ModernPostFeed>
                <MobileHeader />
                <TabbedContainer>
                    <TabsRow>
                        <ClickableTab type="button" role="tab" aria-selected={activeTab === 'out'} $active={activeTab === 'out'} onClick={() => handleTabChange('out')}>
                            Bridge Out
                        </ClickableTab>
                        <ClickableTab type="button" role="tab" aria-selected={activeTab === 'in'} $active={activeTab === 'in'} onClick={() => handleTabChange('in')}>
                            Bridge In
                        </ClickableTab>
                    </TabsRow>
                    <ContainerBody>
                        {activeTab === 'out' && (!address ? <InfoBanner>
                            <InfoIcon>ℹ️</InfoIcon>
                            <span>Sign in to bridge MIRAGE tokens to other networks.</span>
                        </InfoBanner> : submitStage !== 'idle' ?
                            // Progress Screen - shown when bridge is in progress
                            <ProgressScreenContainer>
                                <ProgressScreenHeader>
                                    <ProgressScreenTitle>
                                        <ProgressScreenNetworkIcon src={bridgeOutNetwork?.icon || selectedNetwork?.icon || '/images/bridges/solana.svg'} alt="" />
                                        <ProgressScreenTitleText>
                                            <ProgressScreenMainTitle>Bridge Out</ProgressScreenMainTitle>
                                            <ProgressScreenSubtitle>
                                                Mirage → {bridgeOutNetwork?.name || selectedNetwork?.name || 'Destination'}
                                            </ProgressScreenSubtitle>
                                        </ProgressScreenTitleText>
                                    </ProgressScreenTitle>
                                    <ProgressScreenAmount>
                                        <ProgressScreenAmountValue>
                                            {bridgeOutAmount ? parseFloat(bridgeOutAmount).toLocaleString() : rawAmount ? parseFloat(rawAmount).toLocaleString() : '...'} MIRAGE
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
                                                    {getStepState('submitting') === 'complete' ? <>Relayed by <ResponsiveAddress address={valoperAddress} startChars={16} endChars={6} /></> : submitStage === 'error' && errorStage === 'submitting' ? `Failure: ${submitError || 'submission failed'}` : 'Broadcasting to network...'}
                                                </StepMeta>
                                            </StepText>
                                        </StepItem>
                                        <StepItem>
                                            <StepDot $state={getStepState('verifying')} />
                                            <StepText>
                                                <StepTitle>
                                                    {isSolanaBridge ? 'Burning tokens on Mirage' : 'Confirming transaction on Mirage'}
                                                    {formatStepTime('verifying')}
                                                </StepTitle>
                                                <StepMeta style={{
                                                    fontFamily: 'Monaco, Menlo, monospace',
                                                    fontSize: '0.65rem',
                                                    wordBreak: 'break-all'
                                                }}>
                                                    {submitStage === 'confirmed' ? <>
                                                        {'Success: '}
                                                        <a href={`/chain/rpc/tx?hash=0x${submitTxHash}`} target="_blank" rel="noopener noreferrer">
                                                            {submitTxHash}
                                                        </a>
                                                    </> : submitStage === 'error' && errorStage === 'verifying' ? `Failure: ${submitError || 'transaction failed'}` : submitTxHash || 'Waiting for confirmation'}
                                                </StepMeta>
                                            </StepText>
                                        </StepItem>
                                        <StepItem>
                                            <StepDot $state={getStepState('confirmed')} />
                                            <StepText>
                                                <StepTitle>
                                                    {isSolanaBridge ? 'Minting tokens on Solana' : `Finalizing bridge to ${bridgeOutNetwork?.name || selectedNetwork?.name || 'destination'}`}
                                                    {showMintTimer ? formatStepTime('confirmed') : ''}
                                                </StepTitle>
                                                <StepMeta style={{
                                                    fontFamily: 'Monaco, Menlo, monospace',
                                                    fontSize: '0.65rem',
                                                    wordBreak: 'break-all'
                                                }}>
                                                    {isSolanaBridge ? mintStatus.state === 'minted' && mintStatus.destinationTx ? <>
                                                        {'Success: '}
                                                        <a href={`https://solscan.io/tx/${mintStatus.destinationTx}${solscanClusterParam}`} target="_blank" rel="noopener noreferrer">
                                                            {mintStatus.destinationTx}
                                                        </a>
                                                    </> : mintStatus.state === 'error' ? `Error: ${mintStatus.error || 'mint confirmation failed'}` : mintStatus.state === 'timeout' ? 'Pending: confirmation taking longer than expected.' : outboundAttestationProgress.attestorCount > 0 ? outboundAttestationPowerText ? `${outboundAttestationProgress.attestorCount} validator${outboundAttestationProgress.attestorCount !== 1 ? 's' : ''} attested (${outboundAttestationPowerText})${outboundAttestationProgress.confirmed ? ' - minting' : ''}` : `${outboundAttestationProgress.attestorCount} validator${outboundAttestationProgress.attestorCount !== 1 ? 's' : ''} attested${outboundAttestationProgress.confirmed ? ' - minting' : ''}` : 'Waiting for validator attestations...' : submitStage === 'confirmed' ? 'Bridge burn confirmed.' : 'Waiting for transaction confirmation'}
                                                </StepMeta>
                                            </StepText>
                                        </StepItem>
                                    </StepsList>
                                    {submitStage === 'error' && submitError && <StatusBanner $error style={{
                                        marginTop: '0.75rem'
                                    }}>
                                        ✗ {submitError}
                                    </StatusBanner>}
                                    {isSolanaBridge && mintStatus.state === 'minted' && <StatusBanner $success style={{
                                        marginTop: '0.75rem'
                                    }}>
                                        ✓ Bridge complete! {bridgeOutAmount && bridgeFee !== null ? `${(parseFloat(bridgeOutAmount) - bridgeFee).toFixed(6).replace(/\.?0+$/, '')} ` : ''}MIRAGE minted on Solana.
                                    </StatusBanner>}
                                    {!isSolanaBridge && submitStage === 'confirmed' && <StatusBanner $success style={{
                                        marginTop: '0.75rem'
                                    }}>
                                        ✓ Bridge complete! {bridgeOutAmount && bridgeFee !== null ? `${(parseFloat(bridgeOutAmount) - bridgeFee).toFixed(6).replace(/\.?0+$/, '')} ` : ''}MIRAGE bridged to {bridgeOutNetwork?.name || selectedNetwork?.name || 'destination'}.
                                    </StatusBanner>}
                                </StepsCard>

                                {/* Balance Comparison - only show when fully complete or error */}
                                {(submitStage === 'error' || (isSolanaBridge && (mintStatus.state === 'minted' || mintStatus.state === 'error' || mintStatus.state === 'timeout')) || (!isSolanaBridge && submitStage === 'confirmed')) && <BalanceComparisonCard>
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
                                                <BalanceComparisonNetworkIcon src={bridgeOutNetwork?.icon || selectedNetwork?.icon || '/images/bridges/solana.svg'} alt="" />
                                                {bridgeOutNetwork?.name || selectedNetwork?.name || 'Destination'}
                                            </BalanceComparisonNetwork>
                                            <BalanceComparisonRow>
                                                <BalanceComparisonLabel>Received</BalanceComparisonLabel>
                                                <BalanceComparisonValue $highlight={mintStatus.state === 'minted' ? true : (!isSolanaBridge && submitStage === 'confirmed')}>
                                                    +{bridgeOutAmount && bridgeFee !== null ? (parseFloat(bridgeOutAmount) - bridgeFee).toLocaleString() : '...'} MIRAGE
                                                </BalanceComparisonValue>
                                            </BalanceComparisonRow>
                                        </BalanceComparisonColumn>
                                    </BalanceComparisonGrid>
                                </BalanceComparisonCard>}

                                {/* Action Button */}
                                <div style={{
                                    paddingTop: '0.5rem',
                                    paddingBottom: '2rem'
                                }}>
                                    <Button variant="primary" fullWidth disabled={
                                        // For Solana: wait for mint to complete (or error/timeout)
                                        isSolanaBridge ? mintStatus.state !== 'minted' && mintStatus.state !== 'error' && mintStatus.state !== 'timeout' : submitStage !== 'confirmed' && submitStage !== 'error'} onClick={handleNewBridge} style={bridgeOutNetwork || selectedNetwork ? {
                                            background: `linear-gradient(135deg, ${(bridgeOutNetwork || selectedNetwork).color} 0%, ${(bridgeOutNetwork || selectedNetwork).color}CC 100%)`
                                        } : {}}>
                                        {(isSolanaBridge ? mintStatus.state === 'minted' || mintStatus.state === 'error' || mintStatus.state === 'timeout' : submitStage === 'confirmed' || submitStage === 'error') ? 'Start New Bridge' : 'Bridging...'}
                                    </Button>
                                </div>
                            </ProgressScreenContainer> : <BridgeContainer>
                                <BridgeLayout>
                                    {/* Step 1: Network Selection */}
                                    <SectionTitle>
                                        <StepNumber>1</StepNumber>
                                        Select Destination
                                    </SectionTitle>
                                    <NetworkGrid>
                                        {Object.values(NETWORKS).map(network => <NetworkCard key={network.id} type="button" $selected={selectedNetwork?.id === network.id} $color={network.color} onClick={() => handleNetworkSelect(network.id)} disabled={!network.enabled || inputsDisabled}>
                                            <NetworkCardContent>
                                                <NetworkName>{network.name}</NetworkName>
                                                <NetworkMeta>
                                                    <NetworkBadge $color={network.color}>
                                                        {network.estimatedTime}
                                                    </NetworkBadge>
                                                </NetworkMeta>
                                            </NetworkCardContent>
                                            <NetworkIcon src={network.icon} alt={network.name} />
                                            {selectedNetwork?.id === network.id && <SelectedIndicator $color={network.color}>
                                                ✓
                                            </SelectedIndicator>}
                                        </NetworkCard>)}
                                    </NetworkGrid>

                                    {/* Step 2: Amount */}
                                    <SectionTitle>
                                        <StepNumber>2</StepNumber>
                                        {selectedNetwork ? `Send to ${selectedNetwork.name}` : 'Enter Amount'}
                                    </SectionTitle>
                                    <InputSection>
                                        {/* Inline balance display */}
                                        <div style={{
                                            display: 'flex',
                                            justifyContent: 'flex-end',
                                            fontSize: '0.75rem',
                                            color: theme.colors.subtleText,
                                            marginBottom: '0.35rem'
                                        }}>
                                            Balance: {balanceLoading ? '...' : balanceError ? 'Error' : `${formatBalance(balance)} MIRAGE`}
                                        </div>
                                        <InputWrapper>
                                            <AmountInput type="text" inputMode="decimal" placeholder="0.00" value={amount} onChange={handleAmountChange} $error={!!errors.amount} disabled={!selectedNetwork || inputsDisabled} />
                                            <MaxButton type="button" onClick={handleMaxAmount} disabled={!selectedNetwork || inputsDisabled}>
                                                Max
                                            </MaxButton>
                                            <AmountSuffix>MIRAGE</AmountSuffix>
                                        </InputWrapper>
                                        {errors.amount && <ErrorText>⚠ {errors.amount}</ErrorText>}
                                    </InputSection>

                                    {/* Step 3: Destination Address */}
                                    <SectionTitle>
                                        <StepNumber>3</StepNumber>
                                        Destination Address
                                        {selectedNetwork?.canDerive && <HelpIconWrapper data-tooltip="Your Mirage key works on Cosmos chains. We auto-derive your address.">
                                            ?
                                        </HelpIconWrapper>}
                                    </SectionTitle>
                                    <InputSection>
                                        {/* Cosmos chains: show derived address with option to change */}
                                        {selectedNetwork?.canDerive ? <>
                                            {!useDifferentAddress ? <>
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
                                                <DifferentAddressToggle type="button" onClick={() => setUseDifferentAddress(true)} disabled={inputsDisabled}>
                                                    Send to a different address →
                                                </DifferentAddressToggle>
                                            </> : <>
                                                <InputLabel>
                                                    {selectedNetwork.name} Address
                                                </InputLabel>
                                                <AddressInput type="text" placeholder={`${selectedNetwork.addressPrefix}1...`} value={destinationAddress} onChange={handleAddressChange} $error={!!errors.address} disabled={inputsDisabled} />
                                                {errors.address && <ErrorText>⚠ {errors.address}</ErrorText>}
                                                <DifferentAddressToggle type="button" onClick={() => {
                                                    setUseDifferentAddress(false);
                                                    setDestinationAddress('');
                                                    setErrors(prev => ({
                                                        ...prev,
                                                        address: null
                                                    }));
                                                }} disabled={inputsDisabled}>
                                                    ← Use my {selectedNetwork.name} address
                                                </DifferentAddressToggle>
                                            </>}
                                        </> : (/* Non-Cosmos chains: require manual entry */
                                            <>
                                                <InputLabel>
                                                    {selectedNetwork ? `${selectedNetwork.name} Address` : 'Recipient Address'}
                                                </InputLabel>
                                                <AddressInput type="text" placeholder={selectedNetwork?.id === 'solana' ? 'Enter your Solana wallet address' : 'Select a network first'} value={destinationAddress} onChange={handleAddressChange} $error={!!errors.address} disabled={!selectedNetwork || inputsDisabled} />
                                                {errors.address && <ErrorText>⚠ {errors.address}</ErrorText>}
                                            </>)}
                                    </InputSection>

                                    {/* Preview */}
                                    {selectedNetwork && parsedAmount > 0 && <PreviewCard>
                                        <PreviewHeader>
                                            <PreviewTitle>Summary</PreviewTitle>
                                            <PreviewNetwork $color={selectedNetwork.color}>
                                                <img src={selectedNetwork.icon} alt="" style={{
                                                    width: '1.25rem',
                                                    height: '1.25rem'
                                                }} /> {selectedNetwork.name}
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
                                    </PreviewCard>}

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
                                        <Button variant="primary" fullWidth disabled={!canSubmit} onClick={handleSubmit} style={selectedNetwork ? {
                                            background: `linear-gradient(135deg, ${selectedNetwork.color} 0%, ${selectedNetwork.color}CC 100%)`
                                        } : {}}>
                                            {!selectedNetwork ? 'Select Network' : !amount || parseFloat(amount) <= 0 ? 'Enter Amount' : !hasValidDestination ? 'Enter Address' : `Bridge to ${selectedNetwork.name}`}
                                        </Button>
                                    </SubmitSection>
                                </BridgeLayout>
                            </BridgeContainer>)}
                        {activeTab === 'in' && <BridgeInPanel address={address} chainConfigs={chainConfigs} attestationThresholdBps={attestationThresholdBps} balance={balance} balanceLoading={balanceLoading} balanceError={balanceError} refreshBalance={refreshBalance} formatBalance={formatBalance} />}
                    </ContainerBody>
                </TabbedContainer>
            </ModernPostFeed>
        </div>
    </ContentGrid>;
}