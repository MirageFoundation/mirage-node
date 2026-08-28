import { Helmet } from "react-helmet-async";
import styled, { css, useTheme } from "styled-components";
import {
    HiChevronDown,
    HiCheckCircle,
    HiArrowUpRight,
    HiArrowDownLeft,
} from "react-icons/hi2";
import { formatMirageCompact } from "../../../utils/formatters";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, CappedPageColumn } from "../Layout";
import { tooltipStyles } from "../components/Tooltip.js";
import ConfirmDialog from "../components/ConfirmDialog.js";
import { useSubscription, TIER_COLORS, getTierName, getTierColor, isAdmin } from "../../../logic/useSubscription";
import AccountStatusNotices from "../components/AccountStatusNotices";

/**
 * SubscriptionView — `default` Plan 06 sub-plan 05.
 *
 * Section-list rewrite of the /subscription route. Visual only — hook
 * wiring / subscribe / auto-renew handlers unchanged. Follows
 * `docs/guides/web-theme-default/RULES.md`:
 *  - R1: lifted surfaces (ActivePlanCard, TierCard, TierDetailsPanel,
 *    BalanceTile) all sit on `bg` — the main canvas. Only borders
 *    separate them.
 *  - R2: every color routed through a token (TIER_COLORS retained as
 *    shared tier visual language per sub-plan 06.1 / StatsView).
 *    Auto-renewing status uses yellow/amber `inboxHighlightRail` +
 *    `inboxHighlightBg` pair (per the recurring-payment convention).
 *  - R3: dividers use `border` / `borderSubtle`.
 *  - R4: data parity with `themes/bluemoon/routes/SubscriptionView.js`.
 *  - R6: all chevrons/directional icons via `react-icons/hi2`.
 *  - R7: page heading 1.1rem/700, section headers 0.6rem/700
 *    uppercase, CTA pills 0.72rem/600.
 *
 * MIRAGE values are rendered via `formatMirageCompact` everywhere
 * (k / M / B suffixes) to keep the numbers consistent with the rest
 * of the theme.
 */

/* -------------------------------------------------------------------------- */
/* Shell                                                                      */
/* -------------------------------------------------------------------------- */

const SubscriptionWrap = styled.div`
    width: 90%;
    max-width: 960px;
    margin: -0.75rem auto 0;

    @media (max-width: 1000px) {
        width: 100%;
        max-width: none;
        margin-top: -0.5rem;
    }

    /* Large displays: viewport-center override. See SettingsView for
     * the full rationale — above ~1500px the shell drops its max-width
     * cap and pins the sidebar to the left viewport edge, so
     * margin: auto inside Main no longer aligns with viewport center.
     *
     * Offset = sidebar + divider + Main left padding:
     *   sidebar visible: 273px,  sidebar hidden: 33px */
    @media (min-width: 1050px) {
        [data-sidebar-hidden='true'] & {
            margin-left: calc(50vw - 480px - 33px);
            margin-right: auto;
        }
    }

    @media (min-width: 1600px) {
        [data-sidebar-hidden='false'] & {
            margin-left: calc(50vw - 480px - 273px);
            margin-right: auto;
        }
    }

    @media (min-width: 1900px) {
        max-width: 1100px;

        [data-sidebar-hidden='false'] & {
            margin-left: calc(50vw - 550px - 273px);
        }
        [data-sidebar-hidden='true'] & {
            margin-left: calc(50vw - 550px - 33px);
        }
    }
`;

const SubscriptionTabbedContainer = styled(TabbedContainer)`
    margin-top: 0;
`;

const SubscriptionShellBody = styled(ContainerBody)`
    padding: 0.35rem 0 0.75rem;
    border: none;
    border-radius: 0;
`;

const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.75rem;
    padding: 0.5rem 1rem;

    @media (max-width: 600px) {
        padding: 0.5rem 0;
    }
`;

const HeaderTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

const SectionDivider = styled.div`
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    width: 100%;
`;

/* -------------------------------------------------------------------------- */
/* Sections                                                                   */
/* -------------------------------------------------------------------------- */

const Section = styled.section`
    display: flex;
    flex-direction: column;
`;

const SectionHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 0.75rem 1rem 0.45rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;

    @media (max-width: 600px) {
        padding: 0.75rem 0 0.45rem;
    }
`;

const SectionBody = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    padding: 0 1rem 0.75rem;

    @media (max-width: 1000px) {
        padding: 0 0.85rem 0.75rem;
    }

    @media (max-width: 600px) {
        padding: 0 0 0.75rem;
    }
`;

const InfoText = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    font-style: italic;
    line-height: 1.5;
    text-align: center;
    padding: 0.85rem 1rem 0.25rem;

    @media (max-width: 1000px) {
        padding: 0.85rem 0.85rem 0.25rem;
    }

    @media (max-width: 600px) {
        padding: 0.85rem 0 0.25rem;
    }
`;

const ErrorMessage = styled.div`
    background-color: ${({ theme }) => theme.colors.buttonDangerBg};
    border: 1px solid ${({ theme }) => theme.colors.buttonDangerBorder};
    border-radius: 8px;
    padding: 0.6rem 0.85rem;
    margin: 0.75rem 1rem 0;
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.72rem;
    font-weight: 500;

    @media (max-width: 1000px) {
        margin: 0.75rem 0.85rem 0;
    }

    @media (max-width: 600px) {
        margin: 0.75rem 0 0;
    }
`;

/* -------------------------------------------------------------------------- */
/* State blocks                                                               */
/* -------------------------------------------------------------------------- */

const StateBlock = styled.div`
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.6rem;
    padding: 2.5rem 1.25rem;
    text-align: center;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const LoadingSpinner = styled.div`
    width: 26px;
    height: 26px;
    border: 3px solid ${({ theme }) => theme.colors.border};
    border-top: 3px solid ${({ theme }) => theme.colors.focusBlue};
    border-radius: 50%;
    animation: spin 0.8s linear infinite;

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
`;

const StateTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.9rem;
    font-weight: 700;
`;

const StateMessage = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.72rem;
    font-weight: 500;
`;

/* -------------------------------------------------------------------------- */
/* Active plan card                                                           */
/* -------------------------------------------------------------------------- */

const ActivePlanCard = styled.div`
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
    padding: 0.85rem 0.95rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
`;

const ActivePlanTopRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
`;

const ActivePlanLabel = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.55rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 0.15rem;
`;

const ActivePlanName = styled.div`
    color: ${({ $color, theme }) => $color || theme.colors.text};
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    line-height: 1.2;
`;

const StatusCluster = styled.div`
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.3rem;

    @media (max-width: 600px) {
        align-items: flex-start;
    }
`;

/**
 * Auto-renewing → amber/yellow tint (`inboxHighlightRail` token pair).
 * Not renewing    → danger tint (`buttonDanger*`).
 * Processing      → neutral.
 */
const StatusBadge = styled.button`
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.3rem 0.6rem;
    border-radius: 999px;
    font-family: inherit;
    font-size: 0.65rem;
    font-weight: 600;
    white-space: nowrap;
    transition: background 0.15s ease, border-color 0.15s ease;

    ${({ $tone, theme }) => {
        if ($tone === 'processing') {
            return css`
                background: ${theme.colors.accent};
                color: ${theme.colors.subtleText};
                border: 1px solid ${theme.colors.border};
            `;
        }
        if ($tone === 'active') {
            return css`
                /* Matches the canonical warning palette used across default
                   (SeedWarningBanner, WelcomeView WarningBox,
                   LoggedOutPromptCard): amber #f59e0b with
                   0.08 bg / 0.25 border. */
                background: rgba(245, 158, 11, 0.08);
                color: #f59e0b;
                border: 1px solid rgba(245, 158, 11, 0.25);
                &:hover:not(:disabled) {
                    background: rgba(245, 158, 11, 0.15);
                    border-color: rgba(245, 158, 11, 0.4);
                }
            `;
        }
        /* inactive / not renewing */
        return css`
            background: ${theme.colors.buttonDangerBg};
            color: ${theme.colors.voteDown};
            border: 1px solid ${theme.colors.buttonDangerBorder};
            &:hover:not(:disabled) {
                background: ${theme.colors.buttonDangerHoverBg};
            }
        `;
    }}

    cursor: ${({ $clickable, $disabled }) => ($clickable && !$disabled ? 'pointer' : 'default')};
    opacity: ${({ $disabled }) => ($disabled ? 0.7 : 1)};
    pointer-events: ${({ $disabled }) => ($disabled ? 'none' : 'auto')};

    &:focus { outline: none; }
`;

const StatusDot = styled.span`
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
    display: inline-block;
`;

const RenewalTime = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
`;

const TimeHighlight = styled.span`
    color: ${({ theme }) => theme.colors.text};
    font-weight: 600;
    ${tooltipStyles()}
`;

const ActivePlanDivider = styled.div`
    border-bottom: 1px solid ${({ theme }) => theme.colors.borderSubtle};
    width: 100%;
`;

/* Admin variant of ActivePlanCard:
 *  - Left column: tier label + admin name (shrinks to content).
 *  - Vertical 1px divider that hugs the left column's text.
 *  - Right column: Balance + Reserve rows, right-aligned so label and
 *    value sit next to each other.
 * Stacks vertically (divider flips to a top border) on very narrow
 * viewports so nothing gets squeezed. Sub-plan 06.11.C. */
const AdminPlanGrid = styled.div`
    display: flex;
    align-items: stretch;
    gap: 0;

    @media (max-width: 480px) {
        flex-direction: column;
        gap: 0.75rem;
    }
`;

const AdminPlanLeft = styled.div`
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding-right: 1rem;
    border-right: 1px solid ${({ theme }) => theme.colors.border};

    @media (max-width: 480px) {
        padding-right: 0;
        border-right: none;
        border-bottom: 1px solid ${({ theme }) => theme.colors.border};
        padding-bottom: 0.6rem;
    }
`;

const AdminPlanRight = styled.div`
    flex: 1;
    display: grid;
    grid-template-columns: auto auto;
    justify-content: end;
    align-items: baseline;
    column-gap: 0.5rem;
    row-gap: 0.4rem;
    padding-left: 1rem;

    @media (max-width: 480px) {
        padding-left: 0;
        padding-top: 0.6rem;
        /* On narrow viewports the row stacks below the tier column,
         * so we have room to space label and value further apart for
         * a more relaxed read. Sub-plan 06.11.C mobile tweak. */
        justify-content: space-between;
        column-gap: 1.25rem;
    }
`;

/* Admin Balance / Reserve label — same typography as `AdminBalanceValue`
 * so the row reads as "Balance 123 MIRAGE" in one consistent voice
 * (sub-plan 06.11.C tweak). */
const AdminBalanceLabel = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    line-height: 1.2;
    display: inline-flex;
    align-items: center;
    justify-self: end;
    ${tooltipStyles()}
`;

/* Admin Balance / Reserve value. Same font scale + weight as the label
 * so number + unit + label all share the same visual rhythm. Number and
 * "MIRAGE" suffix share the main text color so the value reads as one
 * unit. */
const AdminBalanceValue = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    line-height: 1.2;
    justify-self: end;

    span {
        font-size: inherit;
        font-weight: inherit;
        font-family: inherit;
        letter-spacing: inherit;
        color: inherit;
        margin-left: 0.25rem;
    }
`;

const BalanceRow = styled.div`
    display: grid;
    grid-template-columns: 1fr;
    gap: 0.6rem;
`;

const BalanceTile = styled.div`
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    padding: 0.55rem 0.7rem;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
`;

const BalanceLabel = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.55rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    ${tooltipStyles()}
`;

const BalanceValue = styled.div`
    color: ${({ $muted, theme }) => ($muted ? theme.colors.subtleText : theme.colors.text)};
    font-size: 0.9rem;
    font-weight: 700;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    letter-spacing: -0.02em;
    line-height: 1.2;

    span {
        font-size: 0.6rem;
        color: ${({ theme }) => theme.colors.subtleText};
        margin-left: 0.25rem;
        font-weight: 500;
        font-family: inherit;
        letter-spacing: 0;
    }
`;

/* -------------------------------------------------------------------------- */
/* Tier cards                                                                 */
/* -------------------------------------------------------------------------- */

const TiersList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
`;

const TierCard = styled.div`
    position: relative;
    /* Active tier gets a subtle tier-colored wash (≈6% opacity) + 1px border
       in the tier color. No thicker border, no left rail — the tint alone
       (plus the CurrentBadge) signals the active state. */
    background: ${({ $isActive, $color, theme }) =>
        $isActive ? `${$color}0F` : theme.colors.bg};
    border: 1px solid
        ${({ $isActive, $color, theme }) => ($isActive ? $color : theme.colors.border)};
    border-radius: 10px;
    padding: 0.85rem 0.95rem;
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    transition: background 0.15s ease, border-color 0.15s ease;

    &:hover {
        border-color: ${({ $isActive, $color, theme }) => ($isActive ? $color : theme.colors.cardHoverBorder)};
    }
`;

const TierHeadline = styled.div`
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
`;

const TierNameRow = styled.div`
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    flex-wrap: wrap;
`;

const TierName = styled.div`
    color: ${({ $color, theme }) => $color || theme.colors.text};
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

const CurrentBadge = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    padding: 0.12rem 0.45rem;
    border-radius: 999px;
    background: ${({ theme }) => theme.colors.buttonSuccessBg};
    border: 1px solid ${({ theme }) => theme.colors.buttonSuccessBorder};
    color: ${({ theme }) => theme.colors.voteUp};
    font-size: 0.52rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    line-height: 1;
`;

const TierPrice = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.78rem;
    font-weight: 600;
    display: inline-flex;
    align-items: baseline;
    gap: 0.25rem;
    flex-wrap: wrap;

    span {
        color: ${({ theme }) => theme.colors.subtleText};
        font-size: 0.62rem;
        font-weight: 500;
    }
`;

const TierFeatures = styled.ul`
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.22rem;
`;

const TierFeatureItem = styled.li`
    display: flex;
    align-items: flex-start;
    gap: 0.45rem;
    color: ${({ theme }) => theme.colors.textSecondary};
    font-size: 0.7rem;
    font-weight: 500;
    line-height: 1.45;

    &::before {
        content: '';
        width: 5px;
        height: 5px;
        border-radius: 50%;
        background: ${({ $color, theme }) => $color || theme.colors.subtleText};
        margin-top: 0.5rem;
        flex-shrink: 0;
    }
`;

const TierActions = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    margin-top: 0.2rem;
    flex-wrap: wrap;
`;

const DetailsToggle = styled.button`
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    background: transparent;
    border: none;
    padding: 0.2rem 0;
    color: ${({ theme }) => theme.colors.link};
    font-family: inherit;
    font-size: 0.68rem;
    font-weight: 500;
    cursor: pointer;
    transition: color 0.15s ease;

    &:hover { color: ${({ theme }) => theme.colors.linkHover}; }
    &:focus { outline: none; }
`;

const ChevronWrap = styled.span`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    transition: transform 0.15s ease;
    transform: rotate(${({ $expanded }) => ($expanded ? '180deg' : '0deg')});
`;

/* -------------------------------------------------------------------------- */
/* Plan CTA button — distinct visual per intent                               */
/* -------------------------------------------------------------------------- */

const PlanCTA = styled.button`
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.5rem 1rem;
    border-radius: 999px;
    font-family: inherit;
    font-size: 0.72rem;
    font-weight: 600;
    line-height: 1;
    white-space: nowrap;
    border: 1px solid transparent;
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease, transform 0.1s ease;

    &:focus { outline: none; }
    &:disabled { cursor: not-allowed; }

    svg {
        width: 0.85em;
        height: 0.85em;
        flex-shrink: 0;
    }

    ${({ $intent, theme }) => {
        if ($intent === 'active') {
            return css`
                background: ${theme.colors.buttonSuccessBg};
                border-color: ${theme.colors.buttonSuccessBorder};
                color: ${theme.colors.voteUp};
                cursor: default;
                box-shadow: inset 0 0 0 1px ${theme.colors.buttonSuccessBorder};
            `;
        }
        if ($intent === 'upgrade') {
            return css`
                background: ${theme.colors.followBtnBg};
                border-color: ${theme.colors.followBtnBg};
                color: #ffffff;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.12);

                &:hover:not(:disabled) {
                    background: ${theme.colors.followBtnBgHover};
                    border-color: ${theme.colors.followBtnBgHover};
                    transform: translateY(-1px);
                }
                &:active:not(:disabled) { transform: translateY(0); }
            `;
        }
        if ($intent === 'downgrade') {
            return css`
                background: transparent;
                border-color: ${theme.colors.border};
                color: ${theme.colors.subtleText};

                &:hover:not(:disabled) {
                    background: ${theme.colors.hoverBg};
                    border-color: ${theme.colors.borderStrong};
                    color: ${theme.colors.text};
                }
            `;
        }
        /* insufficient / disabled */
        return css`
            background: ${theme.colors.accent};
            border-color: ${theme.colors.border};
            color: ${theme.colors.subtleText};
            opacity: 0.75;
        `;
    }}
`;

/* -------------------------------------------------------------------------- */
/* Shell component                                                            */
/* -------------------------------------------------------------------------- */

function SubscriptionPageShell({ children }) {
    return (
        <ContentGrid>
            <Helmet>
                <title>Subscription | Mirage</title>
            </Helmet>
            <ModernPostFeed>
                <CappedPageColumn>
                    <SubscriptionTabbedContainer>
                        <SubscriptionShellBody>
                            <SubscriptionWrap>
                                <HeaderRow>
                                    <HeaderTitle>Subscription</HeaderTitle>
                                </HeaderRow>
                                <SectionDivider />
                                {children}
                            </SubscriptionWrap>
                        </SubscriptionShellBody>
                    </SubscriptionTabbedContainer>
                </CappedPageColumn>
            </ModernPostFeed>
        </ContentGrid>
    );
}

/* -------------------------------------------------------------------------- */
/* Route                                                                      */
/* -------------------------------------------------------------------------- */

export default function SubscriptionView({ state }) {
    const theme = useTheme();
    const {
        address,
        userLevel,
        subscriptionExpiry,
        autoRenew,
        balance,
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
        formatTimeRemaining,
        formatExactTime,
        formatPeriodLabel,
        handleCancelAutoRenew,
        buildTierDetails,
        canAfford,
        pendingTier,
        requestUpgrade,
        confirmUpgrade,
        cancelUpgrade,
    } = useSubscription({ state });

    if (isLoading) {
        return (
            <SubscriptionPageShell>
                <StateBlock role="status" aria-live="polite">
                    <LoadingSpinner />
                    <StateTitle>Loading subscription…</StateTitle>
                </StateBlock>
            </SubscriptionPageShell>
        );
    }

    if (tierConfig.length === 0) {
        return (
            <SubscriptionPageShell>
                <StateBlock>
                    <StateTitle>Couldn’t load tiers</StateTitle>
                    <StateMessage>Failed to load tier configuration from the blockchain.</StateMessage>
                </StateBlock>
            </SubscriptionPageShell>
        );
    }

    const userIsAdmin = isAdmin(userLevel);
    // Admin tier accent reads from the R2 `tierAdmin` token so dark/light
    // pairing is honored (see RULES.md and sub-plan 06.11). Other tiers
    // continue to flow through the cross-theme `getTierColor` helper.
    const currentColor = userIsAdmin ? theme.colors.tierAdmin : getTierColor(userLevel);
    const displayAutoRenew = isUpgrading ? autoRenewDisplayRef.current : autoRenew;
    const timeRemainingText = formatTimeRemaining(subscriptionExpiry, displayAutoRenew);
    const exactTime = formatExactTime(subscriptionExpiry);
    const periodLabel = formatPeriodLabel(subscriptionPeriodMinutes);
    const showAutoRenew = userLevel > 0 && userLevel < 100;

    const statusTone = isUpgrading ? 'processing' : autoRenew ? 'active' : 'inactive';

    const renderPlanCTA = (tier) => {
        if (!userIsAdmin && userLevel !== undefined) {
            const isActive = tier.level === userLevel;
            const ctaDisabled =
                isActive ||
                isUpgrading ||
                isSubscribePending(address);

            if (isActive) {
                return (
                    <PlanCTA type="button" $intent="active" disabled aria-label="Active plan">
                        <HiCheckCircle />
                        {isMobile ? 'Active' : 'Current Plan'}
                    </PlanCTA>
                );
            }

            // Show processing on the tier the user just confirmed. The
            // queue-status string from formatSubscribeStatus only appears
            // once the tx hits the pending queue (after key derivation,
            // etc.), which can take a couple of seconds — so fall back to
            // "Processing..." while isUpgrading is true to give immediate
            // feedback and prevent double-clicks.
            const isTargetTier = pendingTier && pendingTier.level === tier.level;
            const pendingLabel = formatSubscribeStatus(address);
            if (pendingLabel || (isUpgrading && isTargetTier)) {
                return (
                    <PlanCTA type="button" $intent="disabled" disabled>
                        {pendingLabel || 'Processing...'}
                    </PlanCTA>
                );
            }

            // Insufficient balance: disable the CTA and surface the
            // reason inline so users know to top up before retrying.
            if (tier.level > 0 && !canAfford(tier)) {
                return (
                    <PlanCTA type="button" $intent="disabled" disabled>
                        Insufficient Funds
                    </PlanCTA>
                );
            }

            if (tier.level < userLevel) {
                return (
                    <PlanCTA
                        type="button"
                        $intent="downgrade"
                        disabled={ctaDisabled}
                        onClick={() => requestUpgrade(tier)}
                    >
                        <HiArrowDownLeft />
                        Downgrade
                    </PlanCTA>
                );
            }

            return (
                <PlanCTA
                    type="button"
                    $intent="upgrade"
                    disabled={ctaDisabled}
                    onClick={() => requestUpgrade(tier)}
                >
                    <HiArrowUpRight />
                    Upgrade
                </PlanCTA>
            );
        }
        return null;
    };

    const renderTierCard = (tier, { isSignedIn }) => {
        const isActive = isSignedIn && tier.level === userLevel;
        const color = TIER_COLORS[tier.level] || TIER_COLORS[0];
        const isExpanded = expandedTierLevel === tier.level;
        const detailItems = isExpanded ? buildTierDetails(tier, periodLabel) : null;

        return (
            <TierCard
                key={tier.level}
                ref={isExpanded ? detailsPanelRef : undefined}
                $isActive={isActive}
                $color={color}
            >
                    <TierHeadline>
                        <TierNameRow>
                            <TierName $color={color}>{tier.name}</TierName>
                            {isActive && (
                                <CurrentBadge>
                                    <HiCheckCircle size="0.7em" />
                                    Current
                                </CurrentBadge>
                            )}
                        </TierNameRow>
                        <TierPrice>
                            {tier.periodFeeUmirage === 0
                                ? 'Free'
                                : <>
                                    {formatMirageCompact(tier.periodFeeUmirage)}
                                    <span>MIRAGE / {periodLabel}</span>
                                </>}
                        </TierPrice>
                    </TierHeadline>

                    {isExpanded ? (
                        <TierFeatures>
                            {detailItems.map((detail, i) => (
                                <TierFeatureItem key={i} $color={color}>
                                    {detail}
                                </TierFeatureItem>
                            ))}
                        </TierFeatures>
                    ) : (
                        <TierFeatures>
                            {tier.features.map((feature, i) => (
                                <TierFeatureItem key={i} $color={color}>
                                    {feature}
                                </TierFeatureItem>
                            ))}
                        </TierFeatures>
                    )}

                    <TierActions>
                        <DetailsToggle
                            type="button"
                            onClick={() => setExpandedTierLevel(isExpanded ? null : tier.level)}
                            aria-expanded={isExpanded}
                        >
                            {isExpanded ? 'Hide details' : 'See all details'}
                            <ChevronWrap $expanded={isExpanded}>
                                <HiChevronDown size="0.85em" />
                            </ChevronWrap>
                        </DetailsToggle>
                        {isSignedIn && renderPlanCTA(tier)}
                    </TierActions>
            </TierCard>
        );
    };

    /* ---------- Not signed in ---------- */

    if (!address) {
        return (
            <SubscriptionPageShell>
                <InfoText>Sign in to manage your subscription.</InfoText>
                <Section>
                    <SectionHeader>Available plans</SectionHeader>
                    <SectionBody>
                        <TiersList>
                            {tierConfig.map(tier => renderTierCard(tier, { isSignedIn: false }))}
                        </TiersList>
                    </SectionBody>
                </Section>
            </SubscriptionPageShell>
        );
    }

    /* ---------- Admin ---------- */

    if (userIsAdmin) {
        return (
            <SubscriptionPageShell>
                <Section style={{ marginTop: '0.85rem' }}>
                    <SectionBody>
                        <ActivePlanCard>
                            <AdminPlanGrid>
                                <AdminPlanLeft>
                                    <ActivePlanLabel>Active tier</ActivePlanLabel>
                                    <ActivePlanName $color={currentColor}>
                                        {getTierName(userLevel)}
                                    </ActivePlanName>
                                </AdminPlanLeft>
                                <AdminPlanRight>
                                    <AdminBalanceLabel data-tooltip={`Spendable wallet balance in MIRAGE.\n\nThis is what a subscription will be paid with.`}>
                                        Balance
                                    </AdminBalanceLabel>
                                    <AdminBalanceValue>
                                        {formatMirageCompact(balance)}
                                        <span>MIRAGE</span>
                                    </AdminBalanceValue>
                                </AdminPlanRight>
                            </AdminPlanGrid>
                        </ActivePlanCard>
                    </SectionBody>
                </Section>
                <InfoText>
                    Admin accounts have full access to all features and cannot be downgraded through this interface.
                    Admin status is managed via governance proposals.
                </InfoText>
            </SubscriptionPageShell>
        );
    }

    /* ---------- Signed in, non-admin ---------- */

    return (
        <SubscriptionPageShell>
            {error && <ErrorMessage>{error}</ErrorMessage>}
            <AccountStatusNotices />

            <Section>
                <SectionHeader>Active plan</SectionHeader>
                <SectionBody>
                    <ActivePlanCard>
                        <ActivePlanTopRow>
                            <div>
                                <ActivePlanLabel>Current tier</ActivePlanLabel>
                                <ActivePlanName $color={currentColor}>
                                    {getTierName(userLevel)}
                                </ActivePlanName>
                            </div>
                            {showAutoRenew && (
                                <StatusCluster>
                                    <StatusBadge
                                        type="button"
                                        $tone={statusTone}
                                        $clickable
                                        $disabled={isUpgrading}
                                        onClick={handleCancelAutoRenew}
                                        title={isUpgrading
                                            ? 'Processing subscription change...'
                                            : autoRenew
                                                ? 'Click to cancel auto-renewal'
                                                : 'Click to re-enable auto-renewal'}
                                    >
                                        <StatusDot />
                                        {isUpgrading
                                            ? 'Processing'
                                            : autoRenew
                                                ? 'Auto-renewing'
                                                : 'Not renewing'}
                                    </StatusBadge>
                                    {timeRemainingText && (
                                        <RenewalTime>
                                            {timeRemainingText.prefix}
                                            {timeRemainingText.highlight && (
                                                <TimeHighlight data-tooltip={exactTime || ''}>
                                                    {timeRemainingText.highlight}
                                                </TimeHighlight>
                                            )}
                                        </RenewalTime>
                                    )}
                                </StatusCluster>
                            )}
                        </ActivePlanTopRow>

                        <ActivePlanDivider />

                        <BalanceRow>
                            <BalanceTile>
                                <BalanceLabel data-tooltip={`Spendable wallet balance in MIRAGE.\n\nThis is what a subscription will be paid with.`}>
                                    Balance
                                </BalanceLabel>
                                <BalanceValue>
                                    {formatMirageCompact(balance)}
                                    <span>MIRAGE</span>
                                </BalanceValue>
                            </BalanceTile>
                        </BalanceRow>
                    </ActivePlanCard>
                </SectionBody>
            </Section>

            <Section>
                <SectionHeader>Available plans</SectionHeader>
                <SectionBody>
                    <TiersList>
                        {tierConfig.map(tier => renderTierCard(tier, { isSignedIn: true }))}
                    </TiersList>
                </SectionBody>
            </Section>

            <InfoText>
                Subscriptions are billed every {periodLabel} in MIRAGE tokens.
                Tokens are burned on payment. If renewal fails due to insufficient balance, you will be downgraded to Free.
            </InfoText>

            {pendingTier && (() => {
                const isDowngradeToFree = pendingTier.level === 0;
                const isUpgradeAction = pendingTier.level > userLevel;
                const priceLabel = pendingTier.periodFeeUmirage > 0
                    ? `${formatMirageCompact(pendingTier.periodFeeUmirage)} MIRAGE`
                    : null;
                let title;
                let dialogMessage;
                let confirmLabel;
                let confirmVariant;
                if (isDowngradeToFree) {
                    title = 'Cancel subscription';
                    dialogMessage = `Auto-renewal will be turned off. Your ${getTierName(userLevel)} plan stays active until it expires, then you'll be downgraded to Free. You won't be charged again.`;
                    confirmLabel = 'Cancel subscription';
                    confirmVariant = 'danger';
                } else if (isUpgradeAction) {
                    title = `Upgrade to ${pendingTier.name}`;
                    dialogMessage = `You'll be charged ${priceLabel} now, and another ${priceLabel} every ${periodLabel} on auto-renewal. You can cancel anytime.`;
                    confirmLabel = `Upgrade to ${pendingTier.name}`;
                    confirmVariant = 'primary';
                } else {
                    title = `Switch to ${pendingTier.name}`;
                    dialogMessage = `This replaces your current ${getTierName(userLevel)} plan immediately. You'll be charged ${priceLabel} now, and another ${priceLabel} every ${periodLabel} on auto-renewal.`;
                    confirmLabel = `Switch to ${pendingTier.name}`;
                    confirmVariant = 'warning';
                }
                return (
                    <ConfirmDialog
                        open
                        title={title}
                        message={dialogMessage}
                        confirmLabel={confirmLabel}
                        confirmVariant={confirmVariant}
                        cancelLabel="Cancel"
                        pending={isUpgrading}
                        onConfirm={confirmUpgrade}
                        onCancel={cancelUpgrade}
                    />
                );
            })()}
        </SubscriptionPageShell>
    );
}
