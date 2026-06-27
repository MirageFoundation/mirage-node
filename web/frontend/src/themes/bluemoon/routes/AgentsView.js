import React from "react";
import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { Link } from "react-router-dom";
import Sidebar from "../components/Sidebar.js";
import TopBar from "../components/TopBar.js";
import Button from "../components/Button.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerTab, ContainerBody } from "../Layout";
import { useAgents, MOBILE_ACTION_HEIGHT, formatTimeAgo } from "../../../logic/useAgents";
const SectionSubtitle = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.7rem;
    margin-bottom: 0.75rem;
    line-height: 1.4;
`;
const AgentsList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
`;
const AgentCard = styled.div`
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    background-color: ${({
    theme
}) => theme.colors.panelAlt};
    border-radius: 8px;
    padding: 0.75rem 1rem;
    transition: background-color 0.2s ease, border-color 0.2s ease;

    &:hover {
        background-color: ${({
    theme
}) => theme.colors.accent};
        border-color: ${({
    theme
}) => theme.colors.subtleText};
    }
`;
const AgentRow = styled.div`
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;

    @media (max-width: 600px) {
        flex-direction: column;
        align-items: stretch;
    }
`;
const AgentInfo = styled.div`
    min-width: 0;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
`;
const AgentActions = styled.div`
    flex-shrink: 0;
    display: flex;
    align-items: flex-start;

    @media (max-width: 600px) {
        width: 100%;
        button { width: 100%; }
    }
`;
const AgentNameRow = styled.div`
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    min-width: 0;
`;
const AgentName = styled(Link)`
    color: ${({
    theme
}) => theme.colors.text};
    text-decoration: none;
    font-weight: 600;
    font-size: 0.85rem;
    white-space: nowrap;
    &:hover { color: ${({
    theme
}) => theme.colors.link}; }
`;
const AgentLastActive = styled.span`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.65rem;
    white-space: nowrap;
`;
const AgentBio = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.7rem;
    line-height: 1.4;
    word-break: break-word;
`;
const EmptyMessage = styled.div`
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.8rem;
    padding: 1rem 0;
`;
const ErrorMessage = styled.div`
    color: #f87171;
    font-size: 0.75rem;
    padding: 0.5rem 0.75rem;
    margin-bottom: 0.5rem;
    background: rgba(248, 113, 113, 0.1);
    border: 1px solid rgba(248, 113, 113, 0.25);
    border-radius: 6px;
`;
const EnforcedTag = styled.span`
    display: inline-flex;
    align-items: center;
    padding: 0.3rem 0.6rem;
    border-radius: 6px;
    border: 1px solid ${({
  theme
}) => theme.colors.border};
    background: ${({
  theme
}) => theme.colors.panel};
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-size: 0.7rem;
    font-weight: 600;
    white-space: nowrap;
`;
const OrderControls = styled.div`
    display: inline-flex;
    gap: 0.25rem;
    margin-right: 0.5rem;
`;
const OrderButton = styled.button`
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 6px;
    border: 1px solid ${({
    theme
}) => theme.colors.border};
    background: ${({
    theme
}) => theme.colors.panel};
    color: ${({
    theme
}) => theme.colors.subtleText};
    font-size: 0.7rem;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;

    &:hover:not(:disabled) {
        background: ${({
    theme
}) => theme.colors.panelAlt};
        color: ${({
    theme
}) => theme.colors.text};
        border-color: ${({
    theme
}) => theme.colors.subtleText};
    }

    &:disabled {
        opacity: 0.35;
        cursor: not-allowed;
    }

    @media (max-width: 600px) {
        min-width: ${MOBILE_ACTION_HEIGHT};
        height: ${MOBILE_ACTION_HEIGHT};
        font-size: 0.9rem;
    }
`;
const AgentActionButton = styled(Button)`
    @media (max-width: 600px) {
        min-height: ${MOBILE_ACTION_HEIGHT};
        height: ${MOBILE_ACTION_HEIGHT};
    }
`;
const Divider = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin: 0.25rem 0;
    font-size: 0.7rem;
    color: ${({
    theme
}) => theme.colors.subtleText};

    &::before, &::after {
        content: '';
        flex: 1;
        height: 1px;
        background: ${({
    theme
}) => theme.colors.border};
    }
`;
const ActionRow = styled.div`
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    margin-top: 0.75rem;
`;
export default function AgentsView({
    state
}) {
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
        location,
        isEnabled,
        handleToggle,
        hasDraftChanges,
        moveAgent,
        applyOrder,
        displayOrder,
        sortedAgents,
        enabledCount,
        autoEnabledAgents
    } = useAgents({
        state
    });
    return <ContentGrid>
        <Helmet>
            <title>Agents | Mirage</title>
        </Helmet>
        <Sidebar currentPath={location.pathname} state={state} />
        <div>
            <TopBar state={state} />
            <ModernPostFeed>
                <MobileHeader />
                <TabbedContainer>
                    <ContainerTab>Agents</ContainerTab>
                    <ContainerBody>
                        <SectionSubtitle>
                            <strong>Mirage has no built-in moderation</strong> — all content lives on-chain unaltered.
                        </SectionSubtitle>
                        <SectionSubtitle>
                            <strong>Anyone</strong> can create an agent that filters spam, fixes tags, translates posts, or curates however they see fit. You choose which ones to trust, and your feed reflects their work while the originals stay untouched.
                        </SectionSubtitle>
                        <SectionSubtitle>
                            The result is an <em>open marketplace of moderation</em> where quality rises through competition, not central authority.
                        </SectionSubtitle>
                        {errorMessage && <ErrorMessage>{errorMessage}</ErrorMessage>}
                        {autoEnabledAgents.length > 0 && <>
                            <Divider>enforced by this server</Divider>
                            <SectionSubtitle style={{
                                marginBottom: '0.25rem'
                            }}>
                                These agents are enabled for everyone on this server. You can't disable them.
                            </SectionSubtitle>
                            <AgentsList>
                                {autoEnabledAgents.map(agent => <AgentCard key={`enforced-${agent.address}`}>
                                    <AgentRow>
                                        <AgentInfo>
                                            <AgentNameRow>
                                                <AgentName to={`/u/${encodeURIComponent(agent.username || agent.address)}?tab=posts`}>
                                                    {agent.displayName}
                                                </AgentName>
                                                <AgentLastActive>
                                                    {agent.last_active ? `(active ${formatTimeAgo(agent.last_active)})` : '(no activity yet)'}
                                                </AgentLastActive>
                                            </AgentNameRow>
                                            {agent.biography && <AgentBio>{agent.biography}</AgentBio>}
                                        </AgentInfo>
                                        <AgentActions>
                                            <EnforcedTag title="Enabled for everyone on this server">Enforced</EnforcedTag>
                                        </AgentActions>
                                    </AgentRow>
                                </AgentCard>)}
                            </AgentsList>
                        </>}
                        {loadingAgents || loadingEnabled ? <EmptyMessage>Loading agents...</EmptyMessage> : sortedAgents.length === 0 ? (autoEnabledAgents.length === 0 ? <EmptyMessage>No agents available yet.</EmptyMessage> : null) : <AgentsList>
                            {sortedAgents.map((agent, idx) => {
                                const addrLower = (agent.address || '').toLowerCase();
                                const enabled = isEnabled(agent.address);
                                const pending = isPending(addrLower);
                                const displayName = agent.username || (agent.address ? `${agent.address.slice(0, 12)}...` : 'Unknown');
                                const orderIdx = displayOrder.indexOf(addrLower);
                                const canMoveUp = enabled && orderIdx > 0;
                                const canMoveDown = enabled && orderIdx >= 0 && orderIdx < displayOrder.length - 1;
                                const showEnabledLabel = idx === 0 && enabledCount > 0;
                                const showAvailableLabel = idx === enabledCount && enabledCount > 0;
                                return <React.Fragment key={agent.address}>
                                    {showEnabledLabel && <>
                                        <Divider>enabled agents</Divider>
                                        <SectionSubtitle style={{
                                            marginBottom: '0.25rem'
                                        }}>
                                            Order matters. When two agents edit the same field, the one higher in your list wins.
                                        </SectionSubtitle>
                                    </>}
                                    {showAvailableLabel && <>
                                        {hasDraftChanges && <ActionRow>
                                            <Button variant="primary" size="sm" disabled={isApplyingOrder || !viewerAddress} loading={isApplyingOrder} onClick={applyOrder}>
                                                Apply order
                                            </Button>
                                        </ActionRow>}
                                        <Divider>available agents</Divider>
                                    </>}
                                    <AgentCard>
                                        <AgentRow>
                                            <AgentInfo>
                                                <AgentNameRow>
                                                    <AgentName to={`/u/${encodeURIComponent(agent.username || agent.address)}?tab=posts`}>
                                                        @{displayName}
                                                    </AgentName>
                                                    <AgentLastActive>
                                                        {agent.last_active ? `(active ${formatTimeAgo(agent.last_active)})` : '(no activity yet)'}
                                                    </AgentLastActive>
                                                </AgentNameRow>
                                                {agent.biography && <AgentBio>{agent.biography}</AgentBio>}
                                            </AgentInfo>
                                            <AgentActions>
                                                {enabled && <OrderControls>
                                                    <OrderButton type="button" onClick={() => moveAgent(addrLower, -1)} disabled={!canMoveUp || pending || isApplyingOrder} aria-label="Move agent up">
                                                        ↑
                                                    </OrderButton>
                                                    <OrderButton type="button" onClick={() => moveAgent(addrLower, 1)} disabled={!canMoveDown || pending || isApplyingOrder} aria-label="Move agent down">
                                                        ↓
                                                    </OrderButton>
                                                </OrderControls>}
                                                <AgentActionButton variant={enabled && hoverAgent === addrLower ? 'primaryDanger' : enabled ? 'subtle' : 'primary'} size="sm" minWidth="8.0rem" disabled={pending || !viewerAddress || loadingEnabled} loading={pending} onMouseEnter={() => setHoverAgent(addrLower)} onMouseLeave={() => setHoverAgent(null)} onClick={() => handleToggle(agent.address)}>
                                                    {pending ? formatStatus(addrLower) : enabled ? hoverAgent === addrLower ? 'Disable' : 'Enabled' : 'Enable'}
                                                </AgentActionButton>
                                            </AgentActions>
                                        </AgentRow>
                                    </AgentCard>
                                </React.Fragment>;
                            })}
                        </AgentsList>}
                        {hasDraftChanges && enabledCount === sortedAgents.length && <ActionRow>
                            <Button variant="primary" size="sm" disabled={isApplyingOrder || !viewerAddress} loading={isApplyingOrder} onClick={applyOrder}>
                                Apply order
                            </Button>
                        </ActionRow>}
                    </ContainerBody>
                </TabbedContainer>
            </ModernPostFeed>
        </div>
    </ContentGrid>;
}