import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import { Link } from "react-router-dom";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, TabsRow, ClickableTab } from "../Layout";
import { useReferrals, PERIODS } from "../../../logic/useReferrals";
const ShareBox = styled.div`
    background: ${({
  theme
}) => theme.layout.containerBg};
    border: ${({
  theme
}) => theme.layout.containerBorder};
    border-bottom: ${({
  theme
}) => theme.layout.containerBorderBottom};
    border-radius: ${({
  theme
}) => theme.layout.containerRadius};
    padding: ${({
  theme
}) => theme.layout.containerPadding};
    margin-bottom: ${({
  theme
}) => theme.layout.sectionMarginBottom};
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
`;
const ShareUrl = styled.input`
    flex: 1;
    min-width: 200px;
    background: ${({
  theme
}) => theme.layout.containerBg};
    color: ${({
  theme
}) => theme.colors.text};
    border: 1px solid ${({
  theme
}) => theme.colors.border};
    border-radius: ${({
  theme
}) => theme.layout.inputRadius};
    padding: ${({
  theme
}) => theme.layout.inputPadding};
    font-size: ${({
  theme
}) => theme.layout.inputSize};
    font-family: monospace;
`;
const CopyBtn = styled.button`
    background: ${({
  $copied,
  theme
}) => $copied ? '#4caf50' : theme.colors.accent};
    color: white;
    border: none;
    border-radius: ${({
  theme
}) => theme.layout.inputRadius};
    padding: ${({
  theme
}) => theme.layout.buttonPadding};
    font-size: ${({
  theme
}) => theme.layout.buttonSize};
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.2s;
    &:hover { opacity: 0.9; }
`;
const Table = styled.table`
    width: 100%;
    border-collapse: collapse;
    font-size: ${({
  theme
}) => theme.layout.inputSize};
`;
const Th = styled.th`
    text-align: left;
    padding: 0.5rem 0.4rem;
    border-bottom: 1px solid ${({
  theme
}) => theme.colors.border};
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-weight: 600;
    white-space: nowrap;
`;
const Td = styled.td`
    padding: 0.4rem;
    border-bottom: 1px solid ${({
  theme
}) => theme.colors.border};
    color: ${({
  theme
}) => theme.colors.text};
    vertical-align: middle;
`;
const Badge = styled.span`
    display: inline-block;
    padding: ${({
  theme
}) => theme.layout.buttonPadding};
    border-radius: ${({
  theme
}) => theme.layout.buttonRadius};
    font-size: ${({
  theme
}) => theme.layout.tinySize};
    font-weight: 600;
    background: ${({
  $real
}) => $real ? '#2e7d3233' : '#78909c22'};
    color: ${({
  $real
}) => $real ? '#66bb6a' : '#90a4ae'};
`;
const EmptyState = styled.div`
    text-align: center;
    padding: ${({
  theme
}) => theme.layout.containerPadding};
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-size: ${({
  theme
}) => theme.layout.monoSize};
`;
const SummaryRow = styled.div`
    display: flex;
    gap: 1.5rem;
    margin-bottom: 1rem;
    flex-wrap: wrap;
`;
const SummaryCard = styled.div`
    background: ${({
  theme
}) => theme.layout.cardBg};
    border: ${({
  theme
}) => theme.layout.cardBorder};
    border-bottom: ${({
  theme
}) => theme.layout.cardBorderBottom};
    border-radius: ${({
  theme
}) => theme.layout.cardRadius};
    padding: ${({
  theme
}) => theme.layout.cardPadding};
    min-width: 100px;
    text-align: center;
`;
const SummaryValue = styled.div`
    font-size: ${({
  theme
}) => theme.layout.sectionSize};
    font-weight: 700;
    color: ${({
  theme
}) => theme.colors.text};
`;
const SummaryLabel = styled.div`
    font-size: ${({
  theme
}) => theme.layout.tinySize};
    color: ${({
  theme
}) => theme.colors.subtleText};
    margin-top: 0.15rem;
`;
function ReferralsView({
  state
}) {
  const {
    location,
    publicKey,
    username,
    period,
    setPeriod,
    data,
    referrals,
    hasMore,
    loading,
    loadingMore,
    error,
    copied,
    shareUrl,
    handleLoadMore,
    handleCopy
  } = useReferrals({
    state
  });
  return <ContentGrid>
            <Helmet><title>Referrals | Mirage</title></Helmet>
            <div>
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow>
                            {PERIODS.map(p => <ClickableTab key={p.key} $active={period === p.key} onClick={() => setPeriod(p.key)}>
                                    {p.label}
                                </ClickableTab>)}
                        </TabsRow>
                        <ContainerBody>
                            {username && shareUrl && <ShareBox>
                                    <ShareUrl value={shareUrl} readOnly onClick={e => e.target.select()} />
                                    <CopyBtn $copied={copied} onClick={handleCopy}>
                                        {copied ? "Copied!" : "Copy Link"}
                                    </CopyBtn>
                                </ShareBox>}

                            {!publicKey ? <EmptyState>Sign in to view your referrals.</EmptyState> : loading ? <EmptyState>Loading...</EmptyState> : error ? <EmptyState>{error}</EmptyState> : referrals.length === 0 ? <EmptyState>No referrals yet. Share your link above to get started.</EmptyState> : <>
                                    <SummaryRow>
                                        <SummaryCard>
                                            <SummaryValue>{data?.total ?? referrals.length}</SummaryValue>
                                            <SummaryLabel>Total Referred</SummaryLabel>
                                        </SummaryCard>
                                    </SummaryRow>
                                    <Table>
                                        <thead>
                                            <tr>
                                                <Th>User</Th>
                                                <Th>Posts</Th>
                                                <Th>Votes</Th>
                                                <Th>Total</Th>
                                                <Th>Status</Th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {referrals.map(r => {
                    const isActive = (r?.total_actions || 0) >= 10;
                    return <tr key={r.address}>
                                                        <Td>
                                                            {r.username ? <Link to={`/u/${r.username}`} style={{
                          color: 'inherit',
                          textDecoration: 'none'
                        }}>
                                                                    @{r.username}
                                                                </Link> : <span style={{
                          opacity: 0.5,
                          fontSize: '0.65rem'
                        }}>{r.address.slice(0, 12)}...</span>}
                                                        </Td>
                                                        <Td>{r.posts}</Td>
                                                        <Td>{r.votes}</Td>
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
                                    {hasMore && <div style={{
                display: 'flex',
                justifyContent: 'center',
                marginTop: '0.75rem'
              }}>
                                            <CopyBtn onClick={handleLoadMore} $copied={loadingMore}>
                                                {loadingMore ? "Loading..." : "Load more"}
                                            </CopyBtn>
                                        </div>}
                                </>}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>;
}
export default ReferralsView;