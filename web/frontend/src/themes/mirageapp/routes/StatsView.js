import React from "react";
import { Helmet } from "react-helmet-async";
import styled, { useTheme } from "styled-components";
import { Link } from "react-router-dom";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, CappedPageColumn } from "../Layout";
import { InfoIcon as TooltipInfoIcon } from "../components/Tooltip.js";
import { formatMirageCompact } from "../../../utils/formatters";
import { useStats, TIER_NAMES, TIER_COLORS } from "../../../logic/useStats";

/**
 * StatsView — `mirageapp` Plan 06 sub-plan 04 (refined).
 *
 * Section-list rewrite of the /stats route. Visual only — `useStats`
 * wiring, `Api.get('get_stats', …)` calls, and pagination handlers are
 * unchanged. Follows `docs/guides/web-theme-mirageapp/RULES.md`:
 *  - R1: single `bg` surface — no lifted panels. Only `SectionHeader`s
 *    (uppercase, subtleText) separate groups, like `SettingsView`.
 *  - R2: every color routed through a token. Tier colors (`TIER_COLORS`)
 *    stay as shared visual language per sub-plan 06.1.
 *  - R3: divider under page header uses `border`.
 *  - R4: data parity with `themes/bluemoon/routes/StatsView.js`.
 *  - R7: page heading 1.1rem/700 (matches `SettingsView`), section
 *    header 0.6rem/700 uppercase, field label 0.72rem/500 text, field
 *    value 0.72rem/500 cardBodyText (matches `ProfileView`).
 */

/* -------------------------------------------------------------------------- */
/* Shell                                                                      */
/* -------------------------------------------------------------------------- */

const StatsWrap = styled.div`
    width: 90%;
    margin: -0.75rem auto 0;

    @media (max-width: 1000px) {
        width: 100%;
        margin-top: -0.5rem;
    }
`;

const StatsTabbedContainer = styled(TabbedContainer)`
    margin-top: 0;
`;

const StatsShellBody = styled(ContainerBody)`
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
/* Tabs                                                                       */
/* -------------------------------------------------------------------------- */

const TabsRow = styled.div`
    position: relative;
    display: grid;
    grid-template-columns: repeat(${({ $count }) => $count || 5}, 1fr);
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    margin: 0 1rem;
`;

const TabButton = styled.button`
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.3rem;
    padding: 0.55rem 0.5rem;
    background: transparent;
    border: none;
    font-family: inherit;
    font-size: 0.75rem;
    font-weight: ${({ $active }) => ($active ? 600 : 500)};
    color: ${({ $active, theme }) => ($active ? theme.colors.text : theme.colors.subtleText)};
    cursor: pointer;
    transition: color 0.15s ease;
    white-space: nowrap;

    &:hover { color: ${({ theme }) => theme.colors.text}; }
    &:focus { outline: none; }
`;

const TabIndicator = styled.div`
    position: absolute;
    bottom: -1px;
    left: 0;
    width: calc(100% / ${({ $count }) => $count || 5});
    height: 2px;
    background: ${({ theme }) => theme.colors.focusBlue};
    transform: translateX(${({ $index }) => `${$index * 100}%`});
    transition: transform 0.2s ease;
`;

/* -------------------------------------------------------------------------- */
/* Sections (flat, no lifted surface — matches SettingsView)                  */
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
    padding: 0.75rem 1rem 0.35rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
`;

const SectionHeaderTitle = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
`;

const SectionBody = styled.div`
    display: flex;
    flex-direction: column;
    padding-bottom: 0.35rem;
`;

const TilesSectionBody = styled.div`
    padding: 0.35rem 1rem 0.75rem;

    @media (max-width: 1000px) {
        padding: 0.35rem 0.85rem 0.75rem;
    }
`;

const RewardSectionBody = styled.div`
    padding: 0.35rem 1rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;

    @media (max-width: 1000px) {
        padding: 0.35rem 0.85rem 0.75rem;
    }
`;

const SectionNote = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    font-style: italic;
    padding: 0 1rem 0.35rem;

    @media (max-width: 1000px) {
        padding: 0 0.85rem 0.35rem;
    }
`;

/* -------------------------------------------------------------------------- */
/* Field rows (match ProfileView's ProfileFieldRow + Label + Mono pattern)    */
/* -------------------------------------------------------------------------- */

const FieldRow = styled.div`
    display: grid;
    grid-template-columns: 160px minmax(0, 1fr);
    gap: 1.5rem;
    align-items: center;
    padding: 0.55rem 1rem;
    box-sizing: border-box;
    width: 100%;
    min-width: 0;

    @media (max-width: 1100px) {
        gap: 0.5rem;
    }

    @media (max-width: 1000px) {
        gap: 0.5rem;
        padding: 0.5rem 0.85rem;
    }
`;

const FieldLabel = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-weight: 500;
    font-size: 0.72rem;
    line-height: 1.3;
    white-space: nowrap;
    flex-shrink: 0;
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
`;

const FieldValue = styled.div`
    display: flex;
    justify-content: flex-start;
    align-items: center;
    gap: 0.5rem;
    min-width: 0;
    flex-wrap: nowrap;
    overflow: hidden;
    color: ${({ theme }) => theme.colors.cardBodyText};
    font-size: 0.72rem;
    font-weight: 500;
    line-height: 1.3;
`;

const SubRow = styled(FieldRow)`
    padding-left: 2rem;

    @media (max-width: 1000px) {
        padding-left: 1.75rem;
    }
`;

const SubLabel = styled(FieldLabel)`
    color: ${({ theme, $color }) => $color || theme.colors.subtleText};
    font-size: 0.7rem;
`;

/* -------------------------------------------------------------------------- */
/* Summary tiles (transparent, only border separates them from bg)            */
/* -------------------------------------------------------------------------- */

const SummaryGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 0.6rem;
`;

const SummaryTile = styled.div`
    background: transparent;
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 8px;
    padding: 0.75rem 0.6rem;
    text-align: center;
`;

const SummaryValue = styled.div`
    color: ${({ theme, $color }) => $color || theme.colors.text};
    font-size: 1.1rem;
    font-weight: 700;
    line-height: 1.2;
`;

const SummaryLabel = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    margin-top: 0.25rem;
`;

/* -------------------------------------------------------------------------- */
/* Tables                                                                     */
/* -------------------------------------------------------------------------- */

const TableWrap = styled.div`
    width: 100%;
    overflow-x: auto;
    padding: 0 1rem;

    @media (max-width: 1000px) {
        padding: 0 0.85rem;
    }
`;

const Table = styled.table`
    width: 100%;
    border-collapse: collapse;
    font-size: 0.72rem;
`;

const Th = styled.th`
    text-align: left;
    padding: 0.5rem 0.5rem;
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    white-space: nowrap;
`;

const Td = styled.td`
    padding: 0.5rem 0.5rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.borderSubtle};
    vertical-align: middle;
    font-size: 0.72rem;
    color: ${({ theme }) => theme.colors.cardBodyText};
    font-weight: 500;
`;

const CellText = styled.span`
    color: ${({ theme }) => theme.colors.cardBodyText};
    font-size: 0.72rem;
    font-weight: 500;
`;

const UserCell = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
`;

const Avatar = styled.img`
    width: 24px;
    height: 24px;
    border-radius: 50%;
    object-fit: cover;
    background: ${({ theme }) => theme.colors.surface3};
    flex-shrink: 0;
`;

const AvatarPlaceholder = styled.div`
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: ${({ theme }) => theme.colors.surface3};
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.6rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.subtleText};
    flex-shrink: 0;
`;

const UserLink = styled(Link)`
    color: ${({ theme }) => theme.colors.link};
    text-decoration: none;
    font-size: 0.72rem;
    font-weight: 500;

    &:hover { color: ${({ theme }) => theme.colors.linkHover}; }
`;

const AddressText = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
`;

const Badge = styled.span`
    display: inline-block;
    padding: 0.1rem 0.4rem;
    border-radius: 4px;
    font-size: 0.56rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-left: 0.25rem;
    background: ${({ $variant, theme }) => {
        if ($variant === 'subscriber') return theme.colors.voteUpBg;
        if ($variant === 'agent') return theme.colors.voteDownBg;
        return theme.colors.accent;
    }};
    color: ${({ $variant, theme }) => {
        if ($variant === 'subscriber') return theme.colors.voteUp;
        if ($variant === 'agent') return theme.colors.voteDown;
        return theme.colors.text;
    }};
`;

/* -------------------------------------------------------------------------- */
/* Tier header (subscriber tier sub-sections)                                 */
/* -------------------------------------------------------------------------- */

const TierBadge = styled.span`
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    background: ${({ $color }) => ($color ? `${$color}20` : 'transparent')};
    color: ${({ $color, theme }) => $color || theme.colors.text};
`;

const TierCount = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.66rem;
    font-weight: 500;
`;

/* -------------------------------------------------------------------------- */
/* Reward list                                                                */
/* -------------------------------------------------------------------------- */

const RewardRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.5rem 0.75rem;
    border-radius: 6px;
    background: transparent;
    border: 1px solid ${({ theme }) => theme.colors.borderSubtle};
    border-left: 3px solid ${({ $claimed, theme }) => ($claimed ? theme.colors.voteUp : theme.colors.inboxHighlightRail)};
`;

const RewardAmount = styled.span`
    color: ${({ $claimed, theme }) => ($claimed ? theme.colors.voteUp : theme.colors.inboxHighlightRail)};
    font-size: 0.76rem;
    font-weight: 700;
    flex: 0 0 auto;
    min-width: 80px;
`;

const RewardBody = styled.div`
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
`;

const RewardReason = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
`;

const RewardMeta = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 500;
    text-align: right;
`;

const ClaimedTag = styled.div`
    color: ${({ theme }) => theme.colors.voteUp};
    font-size: 0.55rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-top: 0.15rem;
`;

const LoadMoreBtn = styled.button`
    padding: 0.55rem;
    background: transparent;
    border: 1px dashed ${({ theme }) => theme.colors.border};
    border-radius: 6px;
    color: ${({ theme }) => theme.colors.subtleText};
    font-family: inherit;
    font-size: 0.72rem;
    font-weight: 500;
    cursor: ${({ disabled }) => (disabled ? 'wait' : 'pointer')};
    transition: border-color 0.15s ease, color 0.15s ease;

    &:hover:not(:disabled) {
        border-color: ${({ theme }) => theme.colors.borderStrong};
        color: ${({ theme }) => theme.colors.text};
    }
`;

/* -------------------------------------------------------------------------- */
/* Expanded reward row cells                                                  */
/* -------------------------------------------------------------------------- */

const ExpandedRow = styled.div`
    background: transparent;
    padding: 0.75rem 0.5rem;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 0.85rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.borderSubtle};
`;

const ExpandedCell = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
`;

const ExpandedCellLabel = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.6rem;
    font-weight: 500;
`;

const ExpandedCellValue = styled.div`
    color: ${({ theme, $color }) => $color || theme.colors.cardBodyText};
    font-size: 0.72rem;
    font-weight: 500;
`;

/* -------------------------------------------------------------------------- */
/* Trend indicator                                                            */
/* -------------------------------------------------------------------------- */

const TrendIndicator = styled.span`
    margin-left: 0.5rem;
    color: ${({ $trend, theme }) => {
        if ($trend === 'up') return theme.colors.voteUp;
        if ($trend === 'down') return theme.colors.voteDown;
        return theme.colors.subtleText;
    }};
`;

/* -------------------------------------------------------------------------- */
/* State blocks (loading / error / empty)                                     */
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

const ErrorMessage = styled.div`
    background-color: ${({ theme }) => theme.colors.buttonDangerBg};
    border: 1px solid ${({ theme }) => theme.colors.buttonDangerBorder};
    border-radius: 8px;
    padding: 0.6rem 0.85rem;
    margin: 0.75rem 1rem 0;
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.72rem;
    font-weight: 500;
`;

const SectionEmpty = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    font-weight: 500;
    font-style: italic;
    padding: 0.5rem 1rem;

    @media (max-width: 1000px) {
        padding: 0.5rem 0.85rem;
    }
`;

/* -------------------------------------------------------------------------- */
/* Tooltip label helper                                                       */
/* -------------------------------------------------------------------------- */

const InfoPill = styled(TooltipInfoIcon)`
    vertical-align: middle;
`;

/* -------------------------------------------------------------------------- */
/* Tabs config                                                                */
/* -------------------------------------------------------------------------- */

const TABS = [
    { id: 'overview', label: 'Overview' },
    { id: 'signups', label: 'Signups' },
    { id: 'subscribers', label: 'Subscribers' },
    { id: 'accounts', label: 'Accounts' },
    { id: 'rewards', label: 'Rewards' },
];

/* -------------------------------------------------------------------------- */
/* Route                                                                      */
/* -------------------------------------------------------------------------- */

export default function StatsView() {
    const theme = useTheme();
    const {
        activeTab,
        setActiveTab,
        signupsData,
        subscribersData,
        accountsData,
        rewardsData,
        expandedUsers,
        setExpandedUsers,
        payouts,
        payoutsHasMore,
        payoutsLoading,
        loading,
        error,
        mergedStats,
        fetchRewardHistory,
        formatNumber,
        formatPercentage,
        formatDateShort,
        getDAUTrend,
        truncateAddress,
    } = useStats();

    const activeTabIndex = Math.max(0, TABS.findIndex(t => t.id === activeTab));

    const renderUserCell = (user, showAddress = true) => {
        if (!user) return <Td>-</Td>;
        const address = user.address;
        return (
            <Td>
                <UserCell>
                    {user.avatar
                        ? <Avatar src={user.avatar} alt="" />
                        : <AvatarPlaceholder>?</AvatarPlaceholder>}
                    <div>
                        {address
                            ? <UserLink to={`/u/${user.username || address}`}>
                                {user.username || truncateAddress(address)}
                            </UserLink>
                            : <span>{user.username || 'Anonymous'}</span>}
                        {showAddress && address && user.username && (
                            <div><AddressText>{truncateAddress(address)}</AddressText></div>
                        )}
                        {user.is_subscriber && <Badge $variant="subscriber">SUB</Badge>}
                        {user.flair && <Badge $variant="agent">{user.flair}</Badge>}
                    </div>
                </UserCell>
            </Td>
        );
    };

    const renderSubscriberCell = user => {
        if (!user) return <Td>-</Td>;
        return (
            <Td>
                <UserCell>
                    {user.avatar
                        ? <Avatar src={user.avatar} alt="" />
                        : <AvatarPlaceholder>?</AvatarPlaceholder>}
                    <div>
                        {user.address
                            ? <UserLink to={`/u/${user.username || user.address}`}>
                                {user.username || 'Anonymous'}
                            </UserLink>
                            : <span style={{ fontWeight: 500 }}>{user.username || 'Anonymous'}</span>}
                        {user.flair && <Badge $variant="agent">{user.flair}</Badge>}
                    </div>
                </UserCell>
            </Td>
        );
    };

    const renderSubscriberTable = subscribers => {
        if (!subscribers || subscribers.length === 0) {
            return <SectionEmpty>No subscribers in this tier.</SectionEmpty>;
        }
        return (
            <TableWrap>
                <Table>
                    <thead>
                        <tr>
                            <Th style={{ width: '30%' }}>User</Th>
                            <Th style={{ textAlign: 'center', width: '12%' }}>Posts</Th>
                            <Th style={{ textAlign: 'center', width: '14%' }}>Comments</Th>
                            <Th style={{ textAlign: 'center', width: '12%' }}>Votes</Th>
                            <Th style={{ textAlign: 'center', width: '14%' }}>Followers</Th>
                            <Th style={{ textAlign: 'center', width: '18%' }}>Joined</Th>
                        </tr>
                    </thead>
                    <tbody>
                        {subscribers.map((sub, idx) => (
                            <tr key={idx}>
                                {renderSubscriberCell(sub)}
                                <Td style={{ textAlign: 'center' }}><CellText>{formatNumber(sub.post_count)}</CellText></Td>
                                <Td style={{ textAlign: 'center' }}><CellText>{formatNumber(sub.comment_count)}</CellText></Td>
                                <Td style={{ textAlign: 'center' }}><CellText>{formatNumber(sub.vote_count)}</CellText></Td>
                                <Td style={{ textAlign: 'center' }}><CellText>{formatNumber(sub.follower_count)}</CellText></Td>
                                <Td style={{ textAlign: 'center' }}><CellText style={{ fontSize: '0.65rem' }}>{formatDateShort(sub.created_at)}</CellText></Td>
                            </tr>
                        ))}
                    </tbody>
                </Table>
            </TableWrap>
        );
    };

    const renderShell = body => (
        <ContentGrid>
            <Helmet>
                <title>Stats | Mirage</title>
            </Helmet>
            <ModernPostFeed>
                <CappedPageColumn>
                    <StatsTabbedContainer>
                        <StatsShellBody>
                            <StatsWrap>
                            <HeaderRow>
                                <HeaderTitle>Stats</HeaderTitle>
                            </HeaderRow>
                            <SectionDivider />
                            <TabsRow role="tablist" aria-label="Stats sections" $count={TABS.length}>
                                {TABS.map(tab => (
                                    <TabButton
                                        key={tab.id}
                                        type="button"
                                        role="tab"
                                        aria-selected={activeTab === tab.id}
                                        $active={activeTab === tab.id}
                                        onClick={() => setActiveTab(tab.id)}
                                    >
                                        {tab.label}
                                    </TabButton>
                                ))}
                                <TabIndicator $count={TABS.length} $index={activeTabIndex} aria-hidden="true" />
                            </TabsRow>
                            {body}
                            </StatsWrap>
                        </StatsShellBody>
                    </StatsTabbedContainer>
                </CappedPageColumn>
            </ModernPostFeed>
        </ContentGrid>
    );

    if (loading || error) {
        return renderShell(
            <>
                {error && !loading && <ErrorMessage>{error}</ErrorMessage>}
                {loading && !error && (
                    <StateBlock role="status" aria-live="polite">
                        <LoadingSpinner />
                        <StateTitle>Loading stats…</StateTitle>
                    </StateBlock>
                )}
            </>
        );
    }

    const dauTrend = getDAUTrend();
    const trendSymbol = dauTrend === 'up' ? '↑' : dauTrend === 'down' ? '↓' : '→';

    /* ---------- Overview ---------- */

    const overviewBody = mergedStats && (
        <>
            <Section>
                <SectionHeader>
                    <SectionHeaderTitle>
                        Usage
                        <InfoPill data-tooltip="Activity counts pulled from on-chain data and lightweight session tracking.">?</InfoPill>
                    </SectionHeaderTitle>
                </SectionHeader>
                <SectionNote>All known bots and crawlers are excluded — these are real users only.</SectionNote>
                <SectionBody>
                    <FieldRow>
                        <FieldLabel>DAUs (Any): <InfoPill data-tooltip="Daily Active Users: unique users or sessions seen today">?</InfoPill></FieldLabel>
                        <FieldValue>
                            {formatNumber(mergedStats.dau_any_today || mergedStats.dau_today || 0)}
                            {dauTrend && <TrendIndicator $trend={dauTrend}>{trendSymbol}</TrendIndicator>}
                        </FieldValue>
                    </FieldRow>
                    <FieldRow>
                        <FieldLabel>MAUs (Any): <InfoPill data-tooltip="Unique users or sessions in the last 30 days">?</InfoPill></FieldLabel>
                        <FieldValue>{formatNumber(mergedStats.maus || 0)}</FieldValue>
                    </FieldRow>
                    <FieldRow>
                        <FieldLabel>Total Registered: <InfoPill data-tooltip="Profiles created on-chain">?</InfoPill></FieldLabel>
                        <FieldValue>{formatNumber(mergedStats.registered_users || 0)}</FieldValue>
                    </FieldRow>
                    <FieldRow>
                        <FieldLabel>New Registrations: <InfoPill data-tooltip="New profile registrations in the last 7 days">?</InfoPill></FieldLabel>
                        <FieldValue>{formatNumber(mergedStats.new_registrations_7d || 0)}</FieldValue>
                    </FieldRow>
                    <FieldRow>
                        <FieldLabel>Subscribers: <InfoPill data-tooltip="Profiles with active subscription (all tiers)">?</InfoPill></FieldLabel>
                        <FieldValue>{formatNumber(mergedStats.subscribers || 0)}</FieldValue>
                    </FieldRow>
                    <SubRow>
                        <SubLabel $color={TIER_COLORS[1]}>{TIER_NAMES[1]}:</SubLabel>
                        <FieldValue>{formatNumber(mergedStats.subscribers_tier_1 || 0)}</FieldValue>
                    </SubRow>
                    <SubRow>
                        <SubLabel $color={TIER_COLORS[10]}>{TIER_NAMES[10]}:</SubLabel>
                        <FieldValue>{formatNumber(mergedStats.subscribers_tier_10 || 0)}</FieldValue>
                    </SubRow>
                </SectionBody>
            </Section>

            <Section>
                <SectionHeader>
                    <SectionHeaderTitle>
                        Content
                        <InfoPill data-tooltip="Blockchain-wide content counts.">?</InfoPill>
                    </SectionHeaderTitle>
                </SectionHeader>
                <SectionBody>
                    <FieldRow><FieldLabel>Posts:</FieldLabel><FieldValue>{formatNumber(mergedStats.total_posts || 0)}</FieldValue></FieldRow>
                    <FieldRow><FieldLabel>Comments:</FieldLabel><FieldValue>{formatNumber(mergedStats.total_comments || 0)}</FieldValue></FieldRow>
                    <FieldRow><FieldLabel>Votes:</FieldLabel><FieldValue>{formatNumber(mergedStats.total_votes || 0)}</FieldValue></FieldRow>
                </SectionBody>
            </Section>

            <Section>
                <SectionHeader>
                    <SectionHeaderTitle>
                        Engagement
                        <InfoPill data-tooltip="Activity metrics for registered users only.">?</InfoPill>
                    </SectionHeaderTitle>
                </SectionHeader>
                <SectionBody>
                    <FieldRow>
                        <FieldLabel>Votes:</FieldLabel>
                        <FieldValue>
                            ↑{formatNumber(mergedStats.upvotes || 0)} / ↓{formatNumber(mergedStats.downvotes || 0)}
                        </FieldValue>
                    </FieldRow>
                    <FieldRow>
                        <FieldLabel>Avg Posts/User:</FieldLabel>
                        <FieldValue>{formatNumber(mergedStats.average_posts_per_user || 0, 1)}</FieldValue>
                    </FieldRow>
                    <FieldRow>
                        <FieldLabel>Avg Comments/Post:</FieldLabel>
                        <FieldValue>{formatNumber(mergedStats.average_comments_per_post || 0, 1)}</FieldValue>
                    </FieldRow>
                    <FieldRow>
                        <FieldLabel>Avg Votes/User:</FieldLabel>
                        <FieldValue>{formatNumber(mergedStats.average_votes_per_user || 0, 1)}</FieldValue>
                    </FieldRow>
                    <FieldRow>
                        <FieldLabel>Edit %: <InfoPill data-tooltip="Percentage of posts that have been edited">?</InfoPill></FieldLabel>
                        <FieldValue>{formatPercentage((mergedStats.edit_frequency || 0) * 100, 1)}</FieldValue>
                    </FieldRow>
                    <FieldRow>
                        <FieldLabel>Delete %: <InfoPill data-tooltip="Percentage of posts that have been deleted">?</InfoPill></FieldLabel>
                        <FieldValue>{formatPercentage((mergedStats.delete_rate || 0) * 100, 1)}</FieldValue>
                    </FieldRow>
                </SectionBody>
            </Section>

            {mergedStats.most_active_topics && mergedStats.most_active_topics.length > 0 && (
                <Section>
                    <SectionHeader>
                        <SectionHeaderTitle>
                            Active Topics
                            <InfoPill data-tooltip="Top topics by post volume (chain-wide).">?</InfoPill>
                        </SectionHeaderTitle>
                    </SectionHeader>
                    <SectionBody>
                        {mergedStats.most_active_topics.map((item, idx) => (
                            <FieldRow key={idx}>
                                <FieldLabel>
                                    <Link to={`/t/${encodeURIComponent(item.topic)}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                                        #{item.topic}
                                    </Link>
                                </FieldLabel>
                                <FieldValue>{formatNumber(item.count)}</FieldValue>
                            </FieldRow>
                        ))}
                    </SectionBody>
                </Section>
            )}

            {mergedStats.tag_counts && (
                <Section>
                    <SectionHeader>
                        <SectionHeaderTitle>
                            Content Tags
                            <InfoPill data-tooltip="Posts by content tag (chain-wide).">?</InfoPill>
                        </SectionHeaderTitle>
                    </SectionHeader>
                    <SectionBody>
                        <FieldRow><FieldLabel>Safe:</FieldLabel><FieldValue>{formatNumber(mergedStats.tag_counts.safe || 0)}</FieldValue></FieldRow>
                        <FieldRow><FieldLabel>Sensitive:</FieldLabel><FieldValue>{formatNumber(mergedStats.tag_counts.sensitive || 0)}</FieldValue></FieldRow>
                        <FieldRow><FieldLabel>Adult:</FieldLabel><FieldValue>{formatNumber(mergedStats.tag_counts.adult || 0)}</FieldValue></FieldRow>
                        <FieldRow><FieldLabel>Violence:</FieldLabel><FieldValue>{formatNumber(mergedStats.tag_counts.violence || 0)}</FieldValue></FieldRow>
                        <FieldRow><FieldLabel>Gore:</FieldLabel><FieldValue>{formatNumber(mergedStats.tag_counts.gore || 0)}</FieldValue></FieldRow>
                        <FieldRow><FieldLabel>Death:</FieldLabel><FieldValue>{formatNumber(mergedStats.tag_counts.death || 0)}</FieldValue></FieldRow>
                    </SectionBody>
                </Section>
            )}
        </>
    );

    /* ---------- Signups ---------- */

    const signupsBody = signupsData && (
        <>
            <Section>
                <SectionHeader>
                    <SectionHeaderTitle>
                        Invite Code Summary
                        <InfoPill data-tooltip="Overview of invite code usage.">?</InfoPill>
                    </SectionHeaderTitle>
                </SectionHeader>
                <TilesSectionBody>
                    <SummaryGrid>
                        <SummaryTile>
                            <SummaryValue>{formatNumber(signupsData.total_used || 0)}</SummaryValue>
                            <SummaryLabel>Codes Used</SummaryLabel>
                        </SummaryTile>
                        <SummaryTile>
                            <SummaryValue>{formatNumber(signupsData.total_available || 0)}</SummaryValue>
                            <SummaryLabel>Available</SummaryLabel>
                        </SummaryTile>
                        <SummaryTile>
                            <SummaryValue>{formatNumber(signupsData.unique_referrers || 0)}</SummaryValue>
                            <SummaryLabel>Unique Referrers</SummaryLabel>
                        </SummaryTile>
                    </SummaryGrid>
                </TilesSectionBody>
            </Section>

            {signupsData.top_referrers && signupsData.top_referrers.length > 0 && (
                <Section>
                    <SectionHeader>
                        <SectionHeaderTitle>
                            Top Referrers
                            <InfoPill data-tooltip="Users who have invited the most new members.">?</InfoPill>
                        </SectionHeaderTitle>
                    </SectionHeader>
                    <TableWrap>
                        <Table>
                            <thead>
                                <tr>
                                    <Th>#</Th>
                                    <Th>Referrer</Th>
                                    <Th style={{ textAlign: 'right' }}>Invites</Th>
                                </tr>
                            </thead>
                            <tbody>
                                {signupsData.top_referrers.map((ref, idx) => (
                                    <tr key={idx}>
                                        <Td style={{ width: '40px' }}><CellText>{idx + 1}</CellText></Td>
                                        {renderUserCell(ref)}
                                        <Td style={{ textAlign: 'right' }}>
                                            <CellText style={{ fontWeight: 600 }}>{formatNumber(ref.invite_count)}</CellText>
                                        </Td>
                                    </tr>
                                ))}
                            </tbody>
                        </Table>
                    </TableWrap>
                </Section>
            )}

            <Section>
                <SectionHeader>
                    <SectionHeaderTitle>
                        Recent Signups
                        <InfoPill data-tooltip="Most recent users who signed up via invite codes.">?</InfoPill>
                    </SectionHeaderTitle>
                </SectionHeader>
                <SectionNote>Showing up to 100 most recent signups via invite codes.</SectionNote>
                <TableWrap>
                    <Table>
                        <thead>
                            <tr>
                                <Th>New User</Th>
                                <Th>Invited By</Th>
                                <Th>Code</Th>
                                <Th>Date</Th>
                            </tr>
                        </thead>
                        <tbody>
                            {signupsData.signups && signupsData.signups.length > 0
                                ? signupsData.signups.map((signup, idx) => (
                                    <tr key={idx}>
                                        {renderUserCell(signup.signup)}
                                        {renderUserCell(signup.referrer)}
                                        <Td><CellText style={{ fontSize: '0.65rem' }}>{signup.code}</CellText></Td>
                                        <Td><CellText style={{ fontSize: '0.65rem' }}>{formatDateShort(signup.used_at)}</CellText></Td>
                                    </tr>
                                ))
                                : (
                                    <tr>
                                        <Td colSpan={4} style={{ textAlign: 'center' }}>
                                            <SectionEmpty style={{ padding: 0 }}>
                                                No signups via invite codes yet.
                                            </SectionEmpty>
                                        </Td>
                                    </tr>
                                )}
                        </tbody>
                    </Table>
                </TableWrap>
            </Section>
        </>
    );

    /* ---------- Subscribers ---------- */

    const subscribersBody = subscribersData && (
        <>
            <Section>
                <SectionHeader>
                    <SectionHeaderTitle>
                        Subscriber Summary
                        <InfoPill data-tooltip="Active subscribers by tier.">?</InfoPill>
                    </SectionHeaderTitle>
                </SectionHeader>
                <TilesSectionBody>
                    <SummaryGrid>
                        <SummaryTile>
                            <SummaryValue>{formatNumber(subscribersData.total_subscribers || 0)}</SummaryValue>
                            <SummaryLabel>Total Subscribers</SummaryLabel>
                        </SummaryTile>
                        <SummaryTile>
                            <SummaryValue $color={TIER_COLORS[10]}>{formatNumber(subscribersData.count_tier_10 || 0)}</SummaryValue>
                            <SummaryLabel>{TIER_NAMES[10]}</SummaryLabel>
                        </SummaryTile>
                        <SummaryTile>
                            <SummaryValue $color={TIER_COLORS[1]}>{formatNumber(subscribersData.count_tier_1 || 0)}</SummaryValue>
                            <SummaryLabel>{TIER_NAMES[1]}</SummaryLabel>
                        </SummaryTile>
                    </SummaryGrid>
                </TilesSectionBody>
            </Section>

            <Section>
                <SectionHeader>
                    <SectionHeaderTitle>
                        <TierBadge $color={TIER_COLORS[10]}>{TIER_NAMES[10]}</TierBadge>
                        <TierCount>({formatNumber(subscribersData.count_tier_10 || 0)})</TierCount>
                    </SectionHeaderTitle>
                </SectionHeader>
                {renderSubscriberTable(subscribersData.tier_10)}
            </Section>

            <Section>
                <SectionHeader>
                    <SectionHeaderTitle>
                        <TierBadge $color={TIER_COLORS[1]}>{TIER_NAMES[1]}</TierBadge>
                        <TierCount>({formatNumber(subscribersData.count_tier_1 || 0)})</TierCount>
                    </SectionHeaderTitle>
                </SectionHeader>
                {renderSubscriberTable(subscribersData.tier_1)}
            </Section>
        </>
    );

    /* ---------- Accounts ---------- */

    const accountsBody = accountsData && (
        <>
            <Section>
                <SectionHeader>
                    <SectionHeaderTitle>
                        Top Accounts by Balance
                        <InfoPill data-tooltip="Accounts ranked by wallet balance.">?</InfoPill>
                    </SectionHeaderTitle>
                </SectionHeader>
                <TilesSectionBody>
                    <SummaryGrid>
                        <SummaryTile>
                            <SummaryValue>{formatNumber(accountsData.total_accounts || 0)}</SummaryValue>
                            <SummaryLabel>Total Accounts</SummaryLabel>
                        </SummaryTile>
                    </SummaryGrid>
                </TilesSectionBody>
            </Section>

            <Section>
                <SectionHeader>Top 100 Accounts</SectionHeader>
                <SectionNote>Top 100 accounts by MIRAGE balance.</SectionNote>
                <TableWrap>
                    <Table>
                        <thead>
                            <tr>
                                <Th>#</Th>
                                <Th>Address</Th>
                                <Th>Name</Th>
                                <Th style={{ textAlign: 'right' }}>Balance (MIRAGE)</Th>
                            </tr>
                        </thead>
                        <tbody>
                            {accountsData.accounts && accountsData.accounts.length > 0
                                ? accountsData.accounts.map((account, idx) => (
                                    <tr key={idx}>
                                        <Td style={{ width: '40px' }}><CellText>{idx + 1}</CellText></Td>
                                        <Td>
                                            <UserLink to={`/u/${account.username || account.address}`}>
                                                <AddressText>{truncateAddress(account.address)}</AddressText>
                                            </UserLink>
                                        </Td>
                                        <Td>
                                            {account.username
                                                ? <UserLink to={`/u/${account.username}`}>{account.username}</UserLink>
                                                : <span style={{ color: 'inherit', opacity: 0.6 }}>-</span>}
                                        </Td>
                                        <Td style={{ textAlign: 'right' }}>
                                            <CellText style={{ fontWeight: 600 }}>{formatMirageCompact(account.balance)}</CellText>
                                        </Td>
                                    </tr>
                                ))
                                : (
                                    <tr>
                                        <Td colSpan={4} style={{ textAlign: 'center' }}>
                                            <SectionEmpty style={{ padding: 0 }}>No accounts found.</SectionEmpty>
                                        </Td>
                                    </tr>
                                )}
                        </tbody>
                    </Table>
                </TableWrap>
            </Section>
        </>
    );

    /* ---------- Rewards ---------- */

    const rewardsBody = rewardsData && (
        <>
            <Section>
                <SectionHeader>Reward Pool Status</SectionHeader>
                <TilesSectionBody>
                    <SummaryGrid>
                        <SummaryTile>
                            <SummaryValue>
                                {rewardsData.summary?.quest_payouts_enabled ? 'Active' : 'Disabled'}
                            </SummaryValue>
                            <SummaryLabel>Payouts</SummaryLabel>
                        </SummaryTile>
                        <SummaryTile>
                            <SummaryValue>{formatMirageCompact(rewardsData.summary?.pool_balance || 0)}</SummaryValue>
                            <SummaryLabel>Pool (MIRAGE)</SummaryLabel>
                        </SummaryTile>
                        <SummaryTile>
                            <SummaryValue>{formatMirageCompact(rewardsData.summary?.daily_rate || 0)}</SummaryValue>
                            <SummaryLabel>Earned/Day (7d avg)</SummaryLabel>
                        </SummaryTile>
                    </SummaryGrid>
                </TilesSectionBody>
            </Section>

            <Section>
                <SectionHeader>Overall Statistics</SectionHeader>
                <TilesSectionBody>
                    <SummaryGrid>
                        <SummaryTile>
                            <SummaryValue>{formatMirageCompact(rewardsData.summary?.total_amount || 0)}</SummaryValue>
                            <SummaryLabel>MIRAGE Earned</SummaryLabel>
                        </SummaryTile>
                        <SummaryTile>
                            <SummaryValue>{formatMirageCompact(rewardsData.summary?.claimed_amount || 0)}</SummaryValue>
                            <SummaryLabel>MIRAGE Claimed</SummaryLabel>
                        </SummaryTile>
                        <SummaryTile>
                            <SummaryValue>{formatMirageCompact(rewardsData.summary?.pending_amount || 0)}</SummaryValue>
                            <SummaryLabel>MIRAGE Pending</SummaryLabel>
                        </SummaryTile>
                        <SummaryTile>
                            <SummaryValue>{rewardsData.summary?.total_rewards || 0}</SummaryValue>
                            <SummaryLabel>Reward Count</SummaryLabel>
                        </SummaryTile>
                    </SummaryGrid>
                </TilesSectionBody>
            </Section>

            <Section>
                <SectionHeader>Per-User Breakdown</SectionHeader>
                <SectionNote>
                    Showing {rewardsData.users?.length || 0} users who have earned rewards. Click to expand.
                </SectionNote>
                <TableWrap>
                    <Table>
                        <thead>
                            <tr>
                                <Th style={{ width: '30px' }}></Th>
                                <Th>User</Th>
                                <Th style={{ textAlign: 'right' }}>Earned</Th>
                                <Th style={{ textAlign: 'right' }}>Per Day</Th>
                            </tr>
                        </thead>
                        <tbody>
                            {rewardsData.users && rewardsData.users.length > 0
                                ? rewardsData.users.map((user, idx) => (
                                    <React.Fragment key={idx}>
                                        <tr
                                            onClick={() => setExpandedUsers(prev => ({ ...prev, [user.address]: !prev[user.address] }))}
                                            style={{ cursor: 'pointer' }}
                                        >
                                            <Td style={{ width: '30px', textAlign: 'center' }}>
                                                <CellText>{expandedUsers[user.address] ? '▼' : '▶'}</CellText>
                                            </Td>
                                            <Td>
                                                <UserCell>
                                                    <AvatarPlaceholder>?</AvatarPlaceholder>
                                                    <div>
                                                        <UserLink
                                                            to={`/u/${user.username || user.address}`}
                                                            onClick={e => e.stopPropagation()}
                                                        >
                                                            {user.username || truncateAddress(user.address)}
                                                        </UserLink>
                                                        {user.username && (
                                                            <div><AddressText>{truncateAddress(user.address)}</AddressText></div>
                                                        )}
                                                    </div>
                                                </UserCell>
                                            </Td>
                                            <Td style={{ textAlign: 'right' }}>
                                                <CellText style={{ fontWeight: 600 }}>{formatMirageCompact(user.total_earned)}</CellText>
                                            </Td>
                                            <Td style={{ textAlign: 'right' }}>
                                                <CellText style={{ opacity: 0.7 }}>{formatMirageCompact(user.earnings_per_day)}</CellText>
                                            </Td>
                                        </tr>
                                        {expandedUsers[user.address] && (
                                            <tr>
                                                <td colSpan={4} style={{ padding: 0 }}>
                                                    <ExpandedRow>
                                                        <ExpandedCell>
                                                            <ExpandedCellLabel>Claimed</ExpandedCellLabel>
                                                            <ExpandedCellValue $color={theme.colors.voteUp}>
                                                                {formatMirageCompact(user.claimed_amount)} MIRAGE
                                                            </ExpandedCellValue>
                                                        </ExpandedCell>
                                                        <ExpandedCell>
                                                            <ExpandedCellLabel>Pending</ExpandedCellLabel>
                                                            <ExpandedCellValue $color={theme.colors.inboxHighlightRail}>
                                                                {formatMirageCompact(user.pending_amount)} MIRAGE
                                                            </ExpandedCellValue>
                                                        </ExpandedCell>
                                                        <ExpandedCell>
                                                            <ExpandedCellLabel>Reward Count</ExpandedCellLabel>
                                                            <ExpandedCellValue>
                                                                {user.reward_count} ({user.claimed_count} claimed, {user.pending_count} pending)
                                                            </ExpandedCellValue>
                                                        </ExpandedCell>
                                                        <ExpandedCell>
                                                            <ExpandedCellLabel>First Reward</ExpandedCellLabel>
                                                            <ExpandedCellValue>{user.first_reward_at ? formatDateShort(user.first_reward_at) : 'N/A'}</ExpandedCellValue>
                                                        </ExpandedCell>
                                                        <ExpandedCell>
                                                            <ExpandedCellLabel>Last Reward</ExpandedCellLabel>
                                                            <ExpandedCellValue>{user.last_reward_at ? formatDateShort(user.last_reward_at) : 'N/A'}</ExpandedCellValue>
                                                        </ExpandedCell>
                                                        <ExpandedCell>
                                                            <ExpandedCellLabel>Account Created</ExpandedCellLabel>
                                                            <ExpandedCellValue>{user.account_created_at ? formatDateShort(user.account_created_at) : 'N/A'}</ExpandedCellValue>
                                                        </ExpandedCell>
                                                    </ExpandedRow>
                                                </td>
                                            </tr>
                                        )}
                                    </React.Fragment>
                                ))
                                : (
                                    <tr>
                                        <Td colSpan={4} style={{ textAlign: 'center' }}>
                                            <SectionEmpty style={{ padding: 0 }}>No reward data found.</SectionEmpty>
                                        </Td>
                                    </tr>
                                )}
                        </tbody>
                    </Table>
                </TableWrap>
            </Section>

            <Section>
                <SectionHeader>Reward History</SectionHeader>
                <RewardSectionBody>
                    {payouts.length > 0 ? (
                        <>
                            {payouts.map((reward, idx) => (
                                <RewardRow key={idx} $claimed={reward.claimed}>
                                    <RewardAmount $claimed={reward.claimed}>
                                        +{formatMirageCompact(reward.amount)}
                                    </RewardAmount>
                                    <RewardBody>
                                        <UserLink to={`/u/${reward.username || reward.address}`}>
                                            {reward.username || truncateAddress(reward.address)}
                                        </UserLink>
                                        <RewardReason>{reward.reason}</RewardReason>
                                    </RewardBody>
                                    <RewardMeta>
                                        {formatDateShort(reward.created_at)}
                                        {reward.claimed && <ClaimedTag>claimed</ClaimedTag>}
                                    </RewardMeta>
                                </RewardRow>
                            ))}
                            {payoutsHasMore && (
                                <LoadMoreBtn
                                    onClick={() => fetchRewardHistory(payouts.length, true)}
                                    disabled={payoutsLoading}
                                >
                                    {payoutsLoading ? 'Loading…' : 'Load more'}
                                </LoadMoreBtn>
                            )}
                        </>
                    ) : payoutsLoading ? (
                        <StateBlock>
                            <LoadingSpinner />
                        </StateBlock>
                    ) : (
                        <SectionEmpty>No rewards recorded yet.</SectionEmpty>
                    )}
                </RewardSectionBody>
            </Section>
        </>
    );

    const activeBody = activeTab === 'overview' ? overviewBody
        : activeTab === 'signups' ? signupsBody
        : activeTab === 'subscribers' ? subscribersBody
        : activeTab === 'accounts' ? accountsBody
        : activeTab === 'rewards' ? rewardsBody
        : null;

    return renderShell(activeBody);
}
