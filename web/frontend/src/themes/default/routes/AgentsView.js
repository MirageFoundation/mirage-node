import { Helmet } from "react-helmet-async";
import { Link } from "react-router-dom";
import styled from "styled-components";
import {
    HiChevronDown,
    HiExclamationTriangle,
    HiUserGroup,
    HiArrowsUpDown,
} from "react-icons/hi2";
import Button from "../components/Button.js";
import { ListRowSkeletonList, PageHeaderSkeleton } from "../components/Skeleton.js";
import {
    ContentGrid,
    ModernPostFeed,
    TabbedContainer,
    ContainerBody,
} from "../Layout";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import FeedRightRail from "../components/FeedRightRail.js";
import { useAgents, formatTimeAgo } from "../../../logic/useAgents";
import UserAvatar from "../components/UserAvatar.js";
import { getAuthorColor, getAuthorTooltip } from "../../../utils/tierColors";

/**
 * AgentsView — `default` Plan 06 sub-plan 07.
 *
 * Rules (`docs/guides/web-theme-default/RULES.md`):
 *  - R1 rows sit on `theme.colors.bg`; section labels and the reorder
 *    bar share the same canvas — no panel fill on the main column.
 *  - R2 every color routed through a token.
 *  - R3 rows separated by `1px solid theme.colors.border`.
 *  - R4 data parity with `themes/bluemoon/routes/AgentsView.js`; visual
 *    language from `mirage-mobile-app/src/pages/agents-screen.tsx`
 *    (avatar + name + Agent badge + last active + bio + reorder
 *    chevrons + Enable/Disable button).
 *  - R6 chevrons come from `react-icons/hi2` (`HiChevronDown`). The
 *    up-chevron is the same icon rotated 180°.
 *  - R7 page heading 1.1rem/700; section labels 0.55rem/600 uppercase;
 *    row title 0.85rem/600; last-active 0.62rem/500 subtle.
 */

const AgentsWrap = styled.div`
    width: 100%;
    max-width: 820px;
    margin: -0.75rem 0 0;

    @media (max-width: 1000px) {
        margin-top: -0.5rem;
    }

    @media (min-width: 1500px) {
        max-width: 960px;
    }

    @media (min-width: 1900px) {
        max-width: 1200px;
    }
`;

const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.75rem;
    padding: 0.25rem 1rem 0.5rem;

    @media (max-width: 600px) {
        padding: 0.25rem 0 0.5rem;
    }
`;

const HeaderTitle = styled.div`
    display: flex;
    align-items: center;
    color: ${({ theme }) => theme.colors.text};
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

const IntroBlock = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0 1rem 1rem;

    @media (max-width: 600px) {
        padding: 0 0 0.9rem;
    }
`;

const IntroParagraph = styled.p`
    margin: 0;
    color: ${({ theme }) => theme.colors.cardBodyText};
    font-size: 0.75rem;
    font-weight: 500;
    line-height: 1.45;

    strong {
        color: ${({ theme }) => theme.colors.text};
        font-weight: 600;
    }

    em {
        color: ${({ theme }) => theme.colors.text};
        font-style: normal;
        font-weight: 500;
    }
`;

const ErrorBanner = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.5rem 1rem;
    padding: 0.45rem 0.6rem;
    border: 1px solid ${({ theme }) => theme.colors.buttonDangerBorder};
    background: ${({ theme }) => theme.colors.buttonDangerBg};
    border-radius: 6px;
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.7rem;
    font-weight: 500;

    svg {
        width: 14px;
        height: 14px;
        flex-shrink: 0;
    }
`;

const SectionHeader = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.75rem 1rem 0.45rem;

    @media (max-width: 600px) {
        padding: 0.7rem 0 0.4rem;
    }
`;

const SectionLabel = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
`;

const CountBadge = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    background: ${({ theme }) => theme.colors.surface2};
    font-size: 0.6rem;
    font-weight: 600;
    padding: 0.05rem 0.4rem;
    border-radius: 999px;
    line-height: 1.4;
`;

const ReorderBar = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0 1rem 0.5rem;
    padding: 0.45rem 0.55rem;
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    background: ${({ theme }) => theme.colors.surface2};
    color: ${({ theme }) => theme.colors.subtleText};

    svg.reorder-icon {
        width: 14px;
        height: 14px;
        flex-shrink: 0;
        color: ${({ theme }) => theme.colors.subtleText};
    }

    @media (max-width: 600px) {
        margin: 0 0 0.5rem;
    }
`;

const ReorderHint = styled.span`
    flex: 1;
    min-width: 0;
    font-size: 0.65rem;
    font-weight: 500;
    line-height: 1.35;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const List = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0 1rem;

    @media (max-width: 600px) {
        padding: 0;
    }
`;

const Row = styled.div`
    display: flex;
    align-items: flex-start;
    gap: 0.65rem;
    padding: 0.7rem 0.75rem;
    background: ${({ theme }) => theme.colors.bg};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
    transition: background-color 0.15s ease, border-color 0.15s ease;

    &:hover {
        background: ${({ theme }) => theme.colors.hoverBg};
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    @media (max-width: 600px) {
        padding: 0.65rem;
    }
`;

const RowHeader = styled.div`
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
    flex: 1;
    min-width: 0;
`;

/** Agent row avatar — thin alias around the shared `UserAvatar` so
 *  the dicebear bg color and 20% inner padding match the rest of the
 *  app's avatar surfaces. */
const AvatarImg = ({ src: _src, ...rest }) => (
    <UserAvatar size={36} {...rest} />
);

const Identity = styled.div`
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
`;

const NameRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.35rem;
    min-width: 0;
    flex-wrap: wrap;
`;

const NameLink = styled(Link)`
    color: ${({ theme, $tierColor }) => $tierColor || theme.colors.text};
    text-decoration: none;
    font-size: 0.75rem;
    font-weight: 500;
    line-height: 1.25;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;

    &:hover {
        color: ${({ theme, $tierColor }) => $tierColor || theme.colors.link};
    }
`;

const AgentBadge = styled.span`
    display: inline-flex;
    align-items: center;
    padding: 0.05rem 0.35rem;
    border-radius: 4px;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: ${({ theme }) => theme.colors.surface2};
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.55rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
`;

const LastActive = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    line-height: 1.3;
`;

const Bio = styled.p`
    margin: 0;
    color: ${({ theme }) => theme.colors.cardBodyText};
    font-size: 0.7rem;
    font-weight: 500;
    line-height: 1.5;
    word-break: break-word;
    max-width: 58rem;
`;

const Actions = styled.div`
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 0.35rem;

    @media (max-width: 600px) {
        flex-direction: column-reverse;
        align-items: stretch;
        gap: 0.3rem;
    }
`;

const OrderGroup = styled.div`
    display: inline-flex;
    gap: 0.25rem;
`;

const OrderButton = styled.button`
    width: 1.75rem;
    height: 1.75rem;
    border-radius: 6px;
    border: 1px solid ${({ theme }) => theme.colors.border};
    background: transparent;
    color: ${({ theme }) => theme.colors.text};
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;

    svg {
        width: 13px;
        height: 13px;
        transition: transform 0.15s ease;
        transform: rotate(${({ $direction }) => ($direction === 'up' ? '180deg' : '0deg')});
    }

    &:hover:not(:disabled) {
        background: ${({ theme }) => theme.colors.hoverBg};
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    &:focus-visible {
        outline: none;
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }

    &:disabled {
        opacity: 0.35;
        cursor: not-allowed;
    }
`;

/* ----- Empty / loading / error states ----- */

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

const StateIcon = styled.div`
    width: 48px;
    height: 48px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: 1px solid ${({ theme }) => theme.colors.border};

    svg {
        width: 22px;
        height: 22px;
        color: ${({ $tone, theme }) =>
        $tone === 'danger' ? theme.colors.voteDown : theme.colors.subtleText};
    }
`;

const StateTitle = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-size: 0.9rem;
    font-weight: 700;
`;

const StateMessage = styled.div`
    font-size: 0.75rem;
    line-height: 1.5;
    max-width: 24rem;
    color: ${({ theme }) => theme.colors.subtleText};
`;

function formatActive(ts) {
    const ago = formatTimeAgo(ts);
    return ago ? `Active ${ago}` : 'No activity yet';
}

function getToggleLabel({ enabled, hovering, pending, status }) {
    if (pending) return status || (enabled ? 'Disabling…' : 'Enabling…');
    if (enabled) return hovering ? 'Disable' : 'Enabled';
    return 'Enable';
}

export default function AgentsView({ state }) {
    const {
        viewerAddress,
        loadingAgents,
        loadingEnabled,
        errorMessage,
        isApplyingOrder,
        hoverAgent,
        setHoverAgent,
        isPending,
        formatStatus,
        isEnabled,
        handleToggle,
        hasDraftChanges,
        moveAgent,
        applyOrder,
        displayOrder,
        sortedAgents,
        enabledCount,
    } = useAgents({ state });

    const renderShell = (body) => (
        <ContentGrid>
            <Helmet>
                <title>Agents | Mirage</title>
            </Helmet>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
                    <ModernPostFeed>
                        <TabbedContainer>
                            <ContainerBody $fullWidth>
                                <AgentsWrap>{body}</AgentsWrap>
                            </ContainerBody>
                        </TabbedContainer>
                    </ModernPostFeed>
                </FeedCol>
                <FeedRightRail />
            </FeedRailRow>
        </ContentGrid>
    );

    const headerBlock = (
        <>
            <HeaderRow>
                <HeaderTitle>Agents</HeaderTitle>
            </HeaderRow>
            <IntroBlock>
                <IntroParagraph>
                    <strong>Choose the agents you trust</strong> to shape your feed. Originals stay on-chain; agents can hide spam, fix tags, translate, or rewrite content for you.
                </IntroParagraph>
            </IntroBlock>
        </>
    );

    if (loadingAgents || loadingEnabled) {
        return renderShell(
            <>
                <PageHeaderSkeleton />
                <ListRowSkeletonList count={6} />
            </>
        );
    }

    if (errorMessage && sortedAgents.length === 0) {
        return renderShell(
            <>
                {headerBlock}
                <StateBlock role="alert">
                    <StateIcon $tone="danger">
                        <HiExclamationTriangle />
                    </StateIcon>
                    <StateTitle>Couldn’t load agents</StateTitle>
                    <StateMessage>{errorMessage}</StateMessage>
                </StateBlock>
            </>
        );
    }

    if (sortedAgents.length === 0) {
        return renderShell(
            <>
                {headerBlock}
                <StateBlock>
                    <StateIcon>
                        <HiUserGroup />
                    </StateIcon>
                    <StateTitle>No agents available yet</StateTitle>
                    <StateMessage>
                        Agents curate and moderate your feed. When the first ones ship, they’ll show up here.
                    </StateMessage>
                </StateBlock>
            </>
        );
    }

    const enabledAgents = sortedAgents.slice(0, enabledCount);
    const availableAgents = sortedAgents.slice(enabledCount);
    const showReorderBar = enabledCount > 1;

    const renderRow = (agent) => {
        const addrLower = (agent.address || '').toLowerCase();
        const enabled = isEnabled(agent.address);
        /* `isPending(addr)` returns true for EVERY agent while `apply
         *  order` is in-flight (it checks the global `__set_agents__`
         *  key), which caused all Enable/Disable buttons to show a
         *  spinner when only the Apply-order button was pressed. Scope
         *  the loading spinner to per-agent pending state by excluding
         *  the apply-order window. The button is still disabled during
         *  apply-order (see `disabled={...}` below) so users can't
         *  spam-click mid-reorder. */
        const pending = isPending(addrLower);
        const toggleLoading = pending && !isApplyingOrder;
        const displayName = agent.username
            ? `@${agent.username}`
            : agent.address
                ? `${agent.address.slice(0, 12)}…`
                : 'Unknown';
        const orderIdx = displayOrder.indexOf(addrLower);
        const canMoveUp = enabled && orderIdx > 0;
        const canMoveDown =
            enabled && orderIdx >= 0 && orderIdx < displayOrder.length - 1;
        // Seed dicebear on the bech32 address — stable across username
        // changes and consistent with every other avatar surface.
        const avatarSeed = agent.address || addrLower;
        const profileUrl = `/u/${encodeURIComponent(agent.username || agent.address)}?tab=posts`;
        const hovering = hoverAgent === addrLower;
        // Agents listed here are by definition Agent-tier (level 10).
        const agentLevel = Number(agent.level) || 10;
        const agentTierColor = getAuthorColor(agentLevel);
        const agentTierTooltip = getAuthorTooltip(agentLevel);

        return (
            <Row key={agent.address}>
                <AvatarImg seed={avatarSeed} alt="" />
                <RowHeader>
                    <Identity>
                        <NameRow>
                            <NameLink
                                to={profileUrl}
                                $tierColor={agentTierColor}
                                title={agentTierTooltip || undefined}
                            >{displayName}</NameLink>
                            <AgentBadge>Agent</AgentBadge>
                            <LastActive>{formatActive(agent.last_active)}</LastActive>
                        </NameRow>
                        {agent.biography && <Bio>{agent.biography}</Bio>}
                    </Identity>
                    <Actions>
                        {enabled && enabledCount > 1 && (
                            <OrderGroup>
                                <OrderButton
                                    type="button"
                                    $direction="up"
                                    onClick={() => moveAgent(addrLower, -1)}
                                    disabled={!canMoveUp || pending || isApplyingOrder}
                                    aria-label="Move agent up"
                                >
                                    <HiChevronDown />
                                </OrderButton>
                                <OrderButton
                                    type="button"
                                    $direction="down"
                                    onClick={() => moveAgent(addrLower, 1)}
                                    disabled={!canMoveDown || pending || isApplyingOrder}
                                    aria-label="Move agent down"
                                >
                                    <HiChevronDown />
                                </OrderButton>
                            </OrderGroup>
                        )}
                        <Button
                            variant={enabled && hovering ? 'primaryDanger' : enabled ? 'subtle' : 'primary'}
                            size="sm"
                            minWidth="6.5rem"
                            disabled={pending || !viewerAddress || loadingEnabled || isApplyingOrder}
                            loading={toggleLoading}
                            onMouseEnter={() => setHoverAgent(addrLower)}
                            onMouseLeave={() => setHoverAgent(null)}
                            onClick={() => handleToggle(agent.address)}
                        >
                            {getToggleLabel({
                                enabled,
                                hovering,
                                pending: toggleLoading,
                                status: formatStatus(addrLower),
                            })}
                        </Button>
                    </Actions>
                </RowHeader>
            </Row>
        );
    };

    return renderShell(
        <>
            {headerBlock}

            {errorMessage && (
                <ErrorBanner role="alert">
                    <HiExclamationTriangle />
                    <span>{errorMessage}</span>
                </ErrorBanner>
            )}

            {enabledCount > 0 && (
                <>
                    <SectionHeader>
                        <SectionLabel>Enabled agents</SectionLabel>
                        <CountBadge>{enabledCount}</CountBadge>
                    </SectionHeader>
                    {showReorderBar && (
                        <ReorderBar>
                            <HiArrowsUpDown className="reorder-icon" aria-hidden="true" />
                            <ReorderHint>
                                Enabled agents run in order. Higher agents win when two edit the same field.
                            </ReorderHint>
                            <Button
                                variant="primary"
                                size="xs"
                                disabled={!hasDraftChanges || isApplyingOrder || !viewerAddress}
                                loading={isApplyingOrder}
                                onClick={applyOrder}
                            >
                                Apply order
                            </Button>
                        </ReorderBar>
                    )}
                    <List>{enabledAgents.map(renderRow)}</List>
                </>
            )}

            <SectionHeader>
                <SectionLabel>
                    {enabledCount > 0 ? 'Available agents' : 'All agents'}
                </SectionLabel>
                <CountBadge>{availableAgents.length}</CountBadge>
            </SectionHeader>
            {availableAgents.length === 0 ? (
                <StateBlock>
                    <StateIcon>
                        <HiUserGroup />
                    </StateIcon>
                    <StateTitle>All caught up</StateTitle>
                    <StateMessage>
                        Every available agent is already enabled for your feed.
                    </StateMessage>
                </StateBlock>
            ) : (
                <List>{availableAgents.map(renderRow)}</List>
            )}
        </>
    );
}
