import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { Link, useParams } from "react-router-dom";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, OldRedditContentBleed } from "../Layout";
import { useReferrals, compareISOWeeks, shiftISOWeek, formatWeekRange } from "../../../logic/useReferrals";

const ShareBox = styled.div`
    background: ${({ theme }) => theme.layout.containerBg};
    border: ${({ theme }) => theme.layout.containerBorder};
    border-bottom: ${({ theme }) => theme.layout.containerBorderBottom};
    border-radius: ${({ theme }) => theme.layout.containerRadius};
    padding: ${({ theme }) => theme.layout.containerPadding};
    margin-bottom: ${({ theme }) => theme.layout.sectionMarginBottom};
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
`;
const ShareUrl = styled.input`
    flex: 1;
    min-width: 200px;
    background: ${({ theme }) => theme.layout.containerBg};
    color: ${({ theme }) => theme.colors.text};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: ${({ theme }) => theme.layout.inputRadius};
    padding: ${({ theme }) => theme.layout.inputPadding};
    font-size: ${({ theme }) => theme.layout.inputSize};
    font-family: monospace;
`;
const CopyBtn = styled.button`
    background: ${({ $copied, theme }) => $copied ? '#4caf50' : theme.colors.accent};
    color: white;
    border: none;
    border-radius: ${({ theme }) => theme.layout.inputRadius};
    padding: ${({ theme }) => theme.layout.buttonPadding};
    font-size: ${({ theme }) => theme.layout.buttonSize};
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.2s;
    &:hover { opacity: 0.9; }
`;
const Table = styled.table`
    width: 100%;
    border-collapse: collapse;
    font-size: ${({ theme }) => theme.layout.inputSize};
`;
const Th = styled.th`
    text-align: left;
    padding: 0.5rem 0.4rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.subtleText};
    font-weight: 600;
    white-space: nowrap;
`;
const Td = styled.td`
    padding: 0.4rem;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
    color: ${({ theme }) => theme.colors.text};
    vertical-align: middle;
`;
const Badge = styled.span`
    display: inline-block;
    padding: ${({ theme }) => theme.layout.buttonPadding};
    border-radius: ${({ theme }) => theme.layout.buttonRadius};
    font-size: ${({ theme }) => theme.layout.tinySize};
    font-weight: 600;
    background: ${({ $real }) => $real ? '#2e7d3233' : '#78909c22'};
    color: ${({ $real }) => $real ? '#66bb6a' : '#90a4ae'};
`;
const ReferralsTabbedContainer = styled(TabbedContainer)`
    margin-top: 0;
`;
const EmptyState = styled.div`
    text-align: center;
    padding: ${({ theme }) => theme.layout.containerPadding};
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: ${({ theme }) => theme.layout.monoSize};
`;
const SummaryRow = styled.div`
    display: flex;
    gap: 1.5rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
`;
const SummaryCard = styled.div`
    background: ${({ theme }) => theme.layout.cardBg};
    border: ${({ theme }) => theme.layout.cardBorder};
    border-bottom: ${({ theme }) => theme.layout.cardBorderBottom};
    border-radius: ${({ theme }) => theme.layout.cardRadius};
    padding: ${({ theme }) => theme.layout.cardPadding};
    min-width: 100px;
    text-align: center;
`;
const SummaryValue = styled.div`
    font-size: ${({ theme }) => theme.layout.sectionSize};
    font-weight: 700;
    color: ${({ theme }) => theme.colors.text};
`;
const SummaryLabel = styled.div`
    font-size: ${({ theme }) => theme.layout.tinySize};
    color: ${({ theme }) => theme.colors.subtleText};
    margin-top: 0.15rem;
`;
const ControlsBox = styled.div`
    background-color: ${({ theme }) => theme.layout.containerBg};
    border: ${({ theme }) => theme.layout.containerBorder};
    border-bottom: ${({ theme }) => theme.layout.containerBorderBottom};
    border-radius: ${({ theme }) => theme.layout.containerRadius};
    padding: ${({ theme }) => theme.layout.containerPaddingCompact};
    margin-bottom: ${({ theme }) => theme.layout.sectionMarginBottom};
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
`;
const ControlsRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
`;
const WeekSelect = styled.select`
    background: ${({ theme }) => theme.layout.containerBg};
    color: ${({ theme }) => theme.colors.text};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: ${({ theme }) => theme.layout.inputRadius};
    padding: ${({ theme }) => theme.layout.inputPadding};
    font-size: ${({ theme }) => theme.layout.inputSize};
    font-family: inherit;
    min-width: 12rem;
`;
const ControlsMeta = styled.div`
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
    flex-wrap: wrap;
`;
const MutedNote = styled.span`
    font-size: ${({ theme }) => theme.layout.tinySize};
    color: ${({ theme }) => theme.colors.subtleText};
`;
const ActiveInfo = styled.div`
    font-size: ${({ theme }) => theme.layout.tinySize};
    color: ${({ theme }) => theme.colors.subtleText};
    padding: 0.4rem 0 0.6rem;
`;
const ChartWrapper = styled.div`
    width: 100%;
    margin-bottom: 1rem;
`;
const ChartContainer = styled.div`
    width: 100%;
    aspect-ratio: 500 / 140;
`;
const ChartSvg = styled.svg`
    width: 100%;
    height: 100%;
`;
const ChartLabel = styled.div`
    display: flex;
    justify-content: space-between;
    font-size: 0.7rem;
    color: ${({ theme }) => theme.colors.subtleText};
`;

function ActiveChart({ history }) {
    if (!history || history.length < 2) {
        return <MutedNote>(chart available after more data is collected)</MutedNote>;
    }
    const width = 500, height = 140;
    const padding = { top: 20, right: 12, bottom: 20, left: 32 };
    const innerW = width - padding.left - padding.right;
    const innerH = height - padding.top - padding.bottom;
    const counts = history.map(h => h.active_count);
    const maxVal = Math.max(...counts, 1);
    const points = history.map((h, i) => {
        const x = padding.left + (i / (history.length - 1)) * innerW;
        const y = padding.top + innerH - (h.active_count / maxVal) * innerH;
        return `${x},${y}`;
    }).join(' ');
    const areaPoints = `${padding.left},${padding.top + innerH} ${points} ${padding.left + innerW},${padding.top + innerH}`;
    return <ChartWrapper>
        <ChartContainer>
            <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                <line x1={padding.left} y1={padding.top} x2={padding.left} y2={height - padding.bottom} stroke="#444" strokeWidth="1" />
                <line x1={padding.left} y1={height - padding.bottom} x2={width - padding.right} y2={height - padding.bottom} stroke="#444" strokeWidth="1" />
                <text x={padding.left - 4} y={padding.top + 4} textAnchor="end" fill="#888" fontSize="9">{maxVal}</text>
                <text x={padding.left - 4} y={height - padding.bottom + 4} textAnchor="end" fill="#888" fontSize="9">0</text>
                <polygon points={areaPoints} fill="#667eea22" />
                <polyline points={points} fill="none" stroke="#667eea" strokeWidth="2" />
            </ChartSvg>
        </ChartContainer>
        <ChartLabel>
            <span>{history[0].week}</span>
            <span>{history[history.length - 1].week}</span>
        </ChartLabel>
    </ChartWrapper>;
}

function ReferralsView({ state }) {
    const { address: urlAddress } = useParams();
    const {
        username,
        effectiveAddress,
        isOwnReferrals,
        week,
        setWeek,
        data,
        referrals,
        hasMore,
        loading,
        loadingMore,
        error,
        copied,
        shareUrl,
        handleLoadMore,
        handleCopy,
    } = useReferrals({ state, targetAddress: urlAddress });
    const history = Array.isArray(data?.active_history) ? data.active_history : [];
    const selectedWeek = history.find(h => h.week === week);
    const weekRange = selectedWeek ? formatWeekRange(selectedWeek.week_start, selectedWeek.week_end) : '';
    const weekOptions = history.length ? [...history].reverse().map(item => ({
        value: item.week,
        range: formatWeekRange(item.week_start, item.week_end),
    })) : [{ value: week, range: '' }];
    const minWeek = history[0]?.week;
    const maxWeek = history[history.length - 1]?.week;
    const canPrev = minWeek ? compareISOWeeks(week, minWeek) > 0 : true;
    const canNext = maxWeek ? compareISOWeeks(week, maxWeek) < 0 : true;
    const handlePrevWeek = () => {
        const nextWeek = shiftISOWeek(week, -1);
        if (nextWeek) setWeek(nextWeek);
    };
    const handleNextWeek = () => {
        const nextWeek = shiftISOWeek(week, 1);
        if (nextWeek) setWeek(nextWeek);
    };

    const pageTitle = isOwnReferrals ? 'Referrals | Mirage' : `Referrals for ${effectiveAddress.slice(0, 12)}… | Mirage`;

    return <ContentGrid>
        <Helmet><title>{pageTitle}</title></Helmet>
        <div>
            <ModernPostFeed>
                <OldRedditContentBleed>
                    <ControlsBox>
                        <ControlsRow>
                            <CopyBtn onClick={handlePrevWeek} disabled={!canPrev}>
                                Prev
                            </CopyBtn>
                            <WeekSelect value={week} onChange={e => setWeek(e.target.value)}>
                                {weekOptions.map(option => (
                                    <option key={option.value} value={option.value}>
                                        {option.range ? `${option.value} (${option.range})` : option.value}
                                    </option>
                                ))}
                            </WeekSelect>
                            <CopyBtn onClick={handleNextWeek} disabled={!canNext}>
                                Next
                            </CopyBtn>
                        </ControlsRow>
                        <ControlsMeta>
                            {weekRange && <MutedNote>{weekRange}</MutedNote>}
                            <MutedNote>UTC weeks (Mon–Sun)</MutedNote>
                        </ControlsMeta>
                    </ControlsBox>
                </OldRedditContentBleed>
                <ReferralsTabbedContainer>
                    <ContainerBody>
                        {isOwnReferrals && username && shareUrl && <ShareBox>
                            <ShareUrl value={shareUrl} readOnly onClick={e => e.target.select()} />
                            <CopyBtn $copied={copied} onClick={handleCopy}>
                                {copied ? "Copied!" : "Copy Link"}
                            </CopyBtn>
                        </ShareBox>}

                        {!effectiveAddress ? <EmptyState>Sign in to view your referrals.</EmptyState> : loading ? <EmptyState>Loading...</EmptyState> : error ? <EmptyState>{error}</EmptyState> : referrals.length === 0 && !data?.total ? <EmptyState>{isOwnReferrals ? 'No referrals yet. Share your link above to get started.' : 'No referrals found for this address.'}</EmptyState> : <>
                            {data?.active_history && <ActiveChart history={data.active_history} />}
                            <SummaryRow>
                                <SummaryCard>
                                    <SummaryValue>{data?.total ?? referrals.length}</SummaryValue>
                                    <SummaryLabel>Total Referred</SummaryLabel>
                                </SummaryCard>
                                <SummaryCard>
                                    <SummaryValue>{data?.active_count ?? 0}</SummaryValue>
                                    <SummaryLabel>Active This Week</SummaryLabel>
                                </SummaryCard>
                            </SummaryRow>
                            <ActiveInfo>{data?.active_definition || "Active = 10+ posts or comments in the week"}</ActiveInfo>
                            <Table>
                                <thead>
                                    <tr>
                                        <Th>User</Th>
                                        <Th>Posts</Th>
                                        <Th>Comments</Th>
                                        <Th>Total</Th>
                                        <Th>Status</Th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {referrals.map(r => {
                                        const isActive = !!r.active;
                                        return <tr key={r.address}>
                                            <Td>
                                                {r.username ? <Link to={`/u/${r.username}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                                                    @{r.username}
                                                </Link> : <span style={{ opacity: 0.5, fontSize: '0.65rem' }}>{r.address.slice(0, 12)}...</span>}
                                            </Td>
                                            <Td>{r.posts}</Td>
                                            <Td>{r.comments}</Td>
                                            <Td>{r.total_actions}</Td>
                                            <Td>
                                                <Badge $real={isActive}>
                                                    {isActive ? "Active" : "Inactive"}
                                                </Badge>
                                            </Td>
                                        </tr>;
                                    })}
                                </tbody>
                            </Table>
                            {hasMore && <div style={{ display: 'flex', justifyContent: 'center', marginTop: '0.75rem' }}>
                                <CopyBtn onClick={handleLoadMore} $copied={loadingMore}>
                                    {loadingMore ? "Loading..." : "Load more"}
                                </CopyBtn>
                            </div>}
                        </>}
                    </ContainerBody>
                </ReferralsTabbedContainer>
            </ModernPostFeed>
        </div>
    </ContentGrid>;
}
export default ReferralsView;
