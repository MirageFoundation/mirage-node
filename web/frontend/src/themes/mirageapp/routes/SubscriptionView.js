import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { formatMirage, formatMirageCompact } from "../../../utils/formatters";
import Button from "../components/Button.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, CappedPageColumn } from "../Layout";
import { tooltipStyles } from "../components/Tooltip.js";
import { useSubscription, TIER_COLORS, getTierName, getTierColor, isAdmin } from "../../../logic/useSubscription";

const SubscriptionTabbedContainer = styled(TabbedContainer)`
    margin-top: 0;
`;

const SubscriptionShellBody = styled(ContainerBody)`
    padding: 0;
    border: none;
    border-radius: 0;
`;

const SubscriptionInner = styled.div`
    padding: 0.5rem 0 0.75rem;
    box-sizing: border-box;
`;

const CurrentTierBanner = styled.div`
    display: grid;
    grid-template-columns: 1fr;
    gap: 1rem;
    padding: 0.5rem 0 0.85rem;
    margin-bottom: ${({ theme }) => theme.layout.sectionMarginTop};
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    background: transparent;
    box-shadow: none;
    border-radius: 0;

    @media (min-width: 600px) {
        grid-template-columns: auto 1fr;
        align-items: stretch;
    }
`;
const TierSection = styled.div`
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding-right: 1rem;
    border-right: 1px solid ${({ theme }) => theme.colors.border};
    min-width: 180px;

    @media (max-width: 600px) {
        border-right: none;
        border-bottom: 1px solid ${({ theme }) => theme.colors.border};
        padding-right: 0;
        padding-bottom: 0.75rem;
        align-items: center;
        text-align: center;
    }
`;
const CurrentPlanLabel = styled.div`
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: ${({
    theme
}) => theme.colors.subtleText};
    margin-bottom: 0.5rem;
    font-weight: 600;
`;
const TierNameDisplay = styled.div`
    font-size: ${({
    theme
}) => theme.layout.sectionSize};
    font-weight: 800;
    line-height: 1.5;
    background: ${({
    theme,
    $color
}) => theme.caps.flatMode ? 'transparent' : `linear-gradient(135deg, ${$color}, ${$color}88)`};
    -webkit-background-clip: ${({
    theme
}) => theme.caps.flatMode ? 'unset' : 'text'};
    -webkit-text-fill-color: ${({
    theme
}) => theme.caps.flatMode ? 'unset' : 'transparent'};
    background-clip: ${({
    theme
}) => theme.caps.flatMode ? 'unset' : 'text'};
    color: ${({
    $color
}) => $color};
    filter: ${({
    theme,
    $color
}) => theme.caps.flatMode ? 'none' : `drop-shadow(0 2px 10px ${$color}33)`};
    letter-spacing: -0.03em;
`;
const InfoSection = styled.div`
    display: flex;
    flex-direction: column;
    gap: 1rem;
    
    @media (min-width: 600px) {
        flex-direction: row;
        align-items: stretch;
        justify-content: space-between;
    }
`;
const StatusSection = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    flex: 1;
    justify-content: center;
    align-items: center;
    text-align: center;
`;
const StatusBadge = styled.div`
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: ${({ theme }) => theme.layout.buttonPadding};
    border-radius: ${({ theme }) => theme.layout.buttonRadius};
    font-size: 0.75rem;
    font-weight: 600;
    width: fit-content;
    white-space: nowrap;
    background: ${props => props.$active ? 'rgba(34, 197, 94, 0.15)' : 'rgba(239, 68, 68, 0.15)'};
    color: ${props => props.$active ? '#22C55E' : '#EF4444'};
    border: 1px solid ${props => props.$active ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)'};
    cursor: ${props => props.$clickable && !props.$disabled ? 'pointer' : 'default'};
    opacity: ${props => props.$disabled ? 0.5 : 1};
    pointer-events: ${props => props.$disabled ? 'none' : 'auto'};
    transition: background-color 0.15s ease, border-color 0.15s ease;

    &:hover {
        ${props => props.$clickable && !props.$disabled ? `
            background: ${props.$active ? 'rgba(34, 197, 94, 0.22)' : 'rgba(239, 68, 68, 0.22)'};
        ` : ''}
    }
`;
const StatusIndicator = styled.span`
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
    display: inline-block;
`;
const RenewalTime = styled.div`
    font-size: 0.7rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
    margin-top: 0.25rem;
`;
const TimeHighlight = styled.span`
    color: ${({
    theme
}) => theme.colors.text};
    font-weight: 500;
    ${tooltipStyles()}
`;
const HorizontalDivider = styled.div`
    height: 1px;
    background-color: ${({ theme }) => theme.colors.border};
    width: 100%;
`;
const SectionSeparator = styled.div`
    width: 1px;
    background-color: ${({
    theme
}) => theme.colors.border};
    align-self: stretch;
    display: none;
    @media (min-width: 600px) {
        display: block;
    }
`;
const BalanceSection = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0.35rem 0 0.35rem 1rem;
    border-left: 1px solid ${({ theme }) => theme.colors.border};
    min-width: 180px;
    margin-left: auto;
    background: transparent;

    @media (max-width: 599px) {
        border-left: none;
        border-top: 1px solid ${({ theme }) => theme.colors.border};
        padding: 0.75rem 0 0;
        margin-left: 0;
    }
`;
const BalanceItem = styled.div`
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
`;
const BalanceValueDisplay = styled.div`
    font-size: ${({
    theme,
    $small
}) => {
        if ($small) return theme.layout.labelSize;
        return theme.layout.sectionSize;
    }};
    font-weight: 700;
    color: ${props => props.$small ? ({
        theme
    }) => theme.colors.subtleText : ({
        theme
    }) => theme.colors.text};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    letter-spacing: -0.02em;
    text-align: right;

    span {
        font-size: 0.65rem;
        color: ${({
        theme
    }) => theme.colors.subtleText};
        margin-left: 0.2rem;
        font-weight: normal;
    }
`;
const BalanceLabel = styled.div`
    font-size: 0.6rem;
    color: ${({ theme }) => theme.colors.subtleText};
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 0.25rem;
    padding-top: ${({ theme }) => theme.layout.labelPaddingTop};
    ${tooltipStyles()}
`;
const TiersGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 0.75rem;
    margin-top: 1rem;
`;
const TierCard = styled.div`
    background: ${({
    theme,
    $isActive
}) => {
        if (theme.caps.flatMode) {
            return $isActive ? theme.colors.panelAlt : 'transparent';
        }
        return $isActive ? theme.colors.panelAlt : theme.colors.panel;
    }};
    border: ${props => props.$isActive ? '2px' : '1px'} solid ${props => props.$isActive ? props.$color : props.theme.colors.border};
    border-radius: ${({ theme }) => theme.layout.cardRadius};
    padding: ${({ theme }) => theme.layout.cardPadding};
    display: flex;
    flex-direction: column;
    transition: border-color 0.15s ease;

    &:hover {
        border-color: ${props => props.$color};
    }
`;
const TierHeader = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
`;
const TierName = styled.div`
    font-size: ${({
    theme
}) => theme.layout.sectionSize};
    font-weight: bold;
    color: ${props => props.$color || '#FFFFFF'};
`;
const TierPrice = styled.div`
    font-size: ${({
    theme
}) => theme.layout.sectionSize};
    font-weight: bold;
    color: ${({
    theme
}) => theme.colors.text};
    margin: 0.5rem 0;
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 0.25rem;
    
    span {
        font-size: 0.7rem;
        color: ${({
    theme
}) => theme.colors.subtleText};
        font-weight: normal;
        white-space: nowrap;
    }
`;
const TierFeatures = styled.ul`
    list-style: none;
    padding: 0;
    margin: 0.5rem 0;
    font-size: 0.7rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
    flex: 1;
    
    li {
        padding: 0.2rem 0;
        display: flex;
        align-items: flex-start;
        gap: 0.3rem;
        
        &::before {
            content: '✓';
            color: ${props => props.$color || '#22C55E'};
            font-weight: bold;
            line-height: 1.4;
        }
    }
`;
const TierDetailsPanel = styled.div`
    margin-top: ${({ theme }) => theme.layout.sectionMarginTop};
    padding: ${({ theme }) => theme.layout.containerPadding};
    border-radius: ${({ theme }) => theme.layout.containerRadius};
    background: ${({ theme }) => theme.colors.panelAlt};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-left: 3px solid ${props => props.$color};
`;
const TierDetailsHeader = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    padding-bottom: ${({
    theme
}) => theme.layout.bannerPadding};
    border-bottom: 1px solid ${({
    theme
}) => theme.colors.border};
`;
const TierDetailsTitle = styled.h3`
    margin: 0;
    font-size: ${({ theme }) => theme.layout.sectionSize};
    font-weight: 700;
    color: ${props => props.$color};
`;
const TierDetailsContent = styled.div`
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 1rem;
    font-size: 0.7rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
    line-height: 1.5;
`;
const TierDetailItem = styled.div`
    padding: 0.25rem 0;
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    word-wrap: break-word;
    overflow-wrap: break-word;

    &::before {
        content: '•';
        color: ${props => props.$color || 'rgba(255, 255, 255, 0.4)'};
        font-weight: bold;
        flex-shrink: 0;
        margin-top: 0.2rem;
    }
`;
const InfoText = styled.div`
    font-size: 0.7rem;
    color: ${({
    theme
}) => theme.colors.subtleText};
    text-align: center;
    margin-top: 1rem;
    line-height: 1.5;
`;
const Mono = styled.span`
    color: ${({
    theme
}) => theme.colors.text};
    font-size: 0.8rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
`;
const ErrorMessageBox = styled.div`
    background: ${({
    theme
}) => theme.layout.containerBg};
    border: 1px solid #dc2626;
    border-radius: ${({
    theme
}) => theme.layout.inputRadius};
    padding: ${({
    theme
}) => theme.layout.bannerPadding};
    margin-bottom: ${({
    theme
}) => theme.layout.sectionMarginBottom};
    color: #dc2626;
    font-size: ${({
    theme
}) => theme.layout.inputSize};
`;

function SubscriptionPageShell({
    children
}) {
    return <ContentGrid>
        <Helmet>
            <title>Subscription | Mirage</title>
        </Helmet>
        <ModernPostFeed>
            <CappedPageColumn>
                <SubscriptionTabbedContainer>
                    <SubscriptionShellBody>
                        <SubscriptionInner>
                            {children}
                        </SubscriptionInner>
                    </SubscriptionShellBody>
                </SubscriptionTabbedContainer>
            </CappedPageColumn>
        </ModernPostFeed>
    </ContentGrid>;
}

export default function SubscriptionView({
    state
}) {
    const {
        address,
        userLevel,
        subscriptionExpiry,
        autoRenew,
        balance,
        reserveFunds,
        isLoading,
        isUpgrading,
        error,
        subscriptionPeriodMinutes,
        tierConfig,
        expandedTierLevel,
        setExpandedTierLevel,
        isSubscribePending,
        formatSubscribeStatus,
        isMobile,
        autoRenewDisplayRef,
        detailsPanelRef,
        theme,
        formatTimeRemaining,
        formatExactTime,
        formatPeriodLabel,
        handleCancelAutoRenew,
        canAfford,
        buildTierDetails,
        handleUpgrade
    } = useSubscription({
        state
    });
    if (isLoading) {
        return <SubscriptionPageShell>
            <Mono style={{
                color: theme.colors.subtleText
            }}>Loading subscription info...</Mono>
        </SubscriptionPageShell>;
    }
    if (tierConfig.length === 0) {
        return <SubscriptionPageShell>
            <Mono style={{
                color: theme.colors.subtleText
            }}>Failed to load tier configuration from blockchain.</Mono>
        </SubscriptionPageShell>;
    }
    const currentColor = getTierColor(userLevel);
    const displayAutoRenew = isUpgrading ? autoRenewDisplayRef.current : autoRenew;
    const timeRemainingText = formatTimeRemaining(subscriptionExpiry, displayAutoRenew);
    const exactTime = formatExactTime(subscriptionExpiry);
    const userIsAdmin = isAdmin(userLevel);
    const periodLabel = formatPeriodLabel(subscriptionPeriodMinutes);
    return <SubscriptionPageShell>
        {!address ? <>
            <InfoText style={{
                marginTop: '0',
                marginBottom: '1rem'
            }}>
                Sign in to manage your subscription.
            </InfoText>
            <TiersGrid>
                {tierConfig.map((tier, idx) => {
                    const color = TIER_COLORS[tier.level] || TIER_COLORS[0];
                    return <TierCard key={tier.level} $isActive={false} $color={color}>
                        <TierHeader>
                            <TierName $color={color}>{tier.name}</TierName>
                        </TierHeader>
                        <TierPrice>
                            {tier.periodFeeUmirage === 0 ? 'Free' : <>{formatMirageCompact(tier.periodFeeUmirage)} <span>MIRAGE / {periodLabel}</span></>}
                        </TierPrice>
                        <TierFeatures $color={color}>
                            {tier.features.map((feature, i) => <li key={i}>{feature}</li>)}
                        </TierFeatures>
                        <Button variant="link" size="xs" onClick={() => setExpandedTierLevel(expandedTierLevel === tier.level ? null : tier.level)} style={{
                            alignSelf: 'flex-start',
                            margin: '0.5rem 0'
                        }}>
                            {expandedTierLevel === tier.level ? 'Hide details' : 'See all details'}
                        </Button>
                    </TierCard>;
                })}
            </TiersGrid>
            {expandedTierLevel !== null && (() => {
                const selectedTier = tierConfig.find(t => t.level === expandedTierLevel);
                if (!selectedTier) return null;
                const tierIdx = selectedTier.level;
                const tierColor = TIER_COLORS[tierIdx] || TIER_COLORS[0];
                const details = buildTierDetails(selectedTier, periodLabel);
                return <TierDetailsPanel ref={detailsPanelRef} $color={tierColor}>
                    <TierDetailsHeader>
                        <TierDetailsTitle $color={tierColor}>
                            {selectedTier.name} Plan - Full Details
                        </TierDetailsTitle>
                        <Button variant="ghost" size="xs" onClick={() => setExpandedTierLevel(null)}>
                            Close
                        </Button>
                    </TierDetailsHeader>
                    <TierDetailsContent>
                        {details.map((detail, i) => <TierDetailItem key={i} $color={tierColor}>{detail}</TierDetailItem>)}
                    </TierDetailsContent>
                </TierDetailsPanel>;
            })()}
        </> : <>
            <CurrentTierBanner>
                <TierSection>
                    <CurrentPlanLabel>{isMobile ? 'Active Plan' : 'Active'}</CurrentPlanLabel>
                    <TierNameDisplay $color={currentColor}>
                        {getTierName(userLevel)}
                    </TierNameDisplay>
                </TierSection>

                <InfoSection>
                    {userLevel > 0 && userLevel < 100 && <>
                        <StatusSection>
                            <StatusBadge $active={isUpgrading ? autoRenewDisplayRef.current : autoRenew} $clickable={true} $disabled={isUpgrading} onClick={handleCancelAutoRenew} title={isUpgrading ? 'Processing subscription change...' : autoRenew ? 'Click to cancel auto-renewal' : 'Click to re-enable auto-renewal'}>
                                <StatusIndicator />
                                {isUpgrading ? 'Processing' : autoRenew ? 'Auto-renewing' : 'Not renewing'}
                            </StatusBadge>
                            {timeRemainingText && <RenewalTime>
                                {timeRemainingText.prefix}
                                {timeRemainingText.highlight && <TimeHighlight data-tooltip={exactTime || ''}>
                                    {timeRemainingText.highlight}
                                </TimeHighlight>}
                            </RenewalTime>}
                        </StatusSection>
                        <SectionSeparator />
                    </>}

                    <BalanceSection>
                        <BalanceItem>
                            <BalanceLabel data-tooltip={`Spendable wallet balance in MIRAGE.

This is what a subscription will be paid with.`}>
                                Balance
                            </BalanceLabel>
                            <BalanceValueDisplay>{formatMirage(balance)} <span>MIRAGE</span></BalanceValueDisplay>
                        </BalanceItem>
                        <HorizontalDivider />
                        <BalanceItem>
                            <BalanceLabel data-tooltip={`Escrowed reserve in MIRAGE used for relayed gas and subscriptions.

Held internally by the blockchain and used to process all transactions while subscribed.

Not directly spendable and will get burned if not used.`}>
                                Reserve
                            </BalanceLabel>
                            <BalanceValueDisplay $small>{formatMirage(reserveFunds)} <span>MIRAGE</span></BalanceValueDisplay>
                        </BalanceItem>
                    </BalanceSection>
                </InfoSection>
            </CurrentTierBanner>

            {error && <ErrorMessageBox>
                {error}
            </ErrorMessageBox>}

            {userIsAdmin ? <InfoText style={{
                marginTop: '0'
            }}>
                Admin accounts have full access to all features and cannot be downgraded through this interface.
                Admin status is managed via governance proposals.
            </InfoText> : <>
                <TiersGrid>
                    {tierConfig.map((tier, idx) => {
                        const isActive = tier.level === userLevel;
                        const color = TIER_COLORS[tier.level] || TIER_COLORS[0];
                        const affordable = tier.level === 0 || canAfford(tier);
                        return <TierCard key={tier.level} $isActive={isActive} $color={color}>
                            <TierHeader>
                                <TierName $color={color}>{tier.name}</TierName>
                            </TierHeader>

                            <TierPrice>
                                {tier.periodFeeUmirage === 0 ? 'Free' : <>{formatMirageCompact(tier.periodFeeUmirage)} <span>MIRAGE / {periodLabel}</span></>}
                            </TierPrice>

                            <TierFeatures $color={color}>
                                {tier.features.map((feature, i) => <li key={i}>{feature}</li>)}
                            </TierFeatures>
                            <Button variant="link" size="xs" onClick={() => setExpandedTierLevel(expandedTierLevel === tier.level ? null : tier.level)} style={{
                                alignSelf: 'flex-start',
                                margin: '0.5rem 0'
                            }}>
                                See all details
                            </Button>

                            <Button variant={isActive ? 'ghost' : 'primary'} size="sm" onClick={() => handleUpgrade(tier)} disabled={isActive || isUpgrading || isSubscribePending(address) || (!affordable && tier.level > 0)} style={{
                                marginTop: 'auto',
                                ...(isActive ? {} : theme.caps.flatMode ? {
                                    background: theme.colors.panelAlt,
                                    borderColor: color
                                } : {
                                    background: `linear-gradient(135deg, ${color}, ${color}CC)`,
                                    borderColor: color
                                })
                            }}>
                                {isActive ? isMobile ? 'Active Plan' : 'Active' : tier.level < userLevel ? 'Downgrade' : !affordable ? isMobile ? 'Insufficient Funds' : 'No Funds' : formatSubscribeStatus(address) || 'Subscribe'}
                            </Button>
                        </TierCard>;
                    })}
                </TiersGrid>
                {expandedTierLevel !== null && (() => {
                    const selectedTier = tierConfig.find(t => t.level === expandedTierLevel);
                    if (!selectedTier) return null;
                    const tierIdx = selectedTier.level;
                    const tierColor = TIER_COLORS[tierIdx] || TIER_COLORS[0];
                    const details = buildTierDetails(selectedTier, periodLabel);
                    return <TierDetailsPanel ref={detailsPanelRef} $color={tierColor}>
                        <TierDetailsHeader>
                            <TierDetailsTitle $color={tierColor}>
                                {selectedTier.name} Plan - Full Details
                            </TierDetailsTitle>
                            <Button variant="ghost" size="xs" onClick={() => setExpandedTierLevel(null)}>
                                Close
                            </Button>
                        </TierDetailsHeader>
                        <TierDetailsContent>
                            {details.map((detail, i) => <TierDetailItem key={i} $color={tierColor}>{detail}</TierDetailItem>)}
                        </TierDetailsContent>
                    </TierDetailsPanel>;
                })()}

                <InfoText>
                    Subscriptions are billed every {periodLabel} in MIRAGE tokens.
                    Tokens are burned on payment.
                    If renewal fails due to insufficient balance, you will be downgraded to Free.
                </InfoText>
            </>}
        </>}
    </SubscriptionPageShell>;
}