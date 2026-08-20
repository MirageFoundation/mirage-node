import { Helmet } from "react-helmet-async";
import styled from "styled-components";
import Sidebar from "../components/Sidebar.js";
import TopBar from "../components/TopBar.js";
import Button from "../components/Button.js";
import MobileHeader from "../components/MobileHeader.js";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody, TabsRow, ClickableTab } from "../Layout";
import { formatMirage } from "../../../utils/formatters";
import { useNetwork, CHART, fmtMirage } from "../../../logic/useNetwork";
const Row = styled.div`
    display: grid;
    grid-template-columns: 7rem minmax(0, 1fr);
    gap: ${({
  theme
}) => theme.layout.formRowGap};
    align-items: ${({
  theme
}) => theme.layout.formRowAlign};
    margin: ${({
  theme
}) => theme.layout.formRowMargin};
    @media (max-width: 1000px) {
        grid-template-columns: 1fr;
        gap: 0.35rem;
    }
`;
const RowCentered = styled(Row)`
    align-items: center;
`;
const SectionRow = styled(Row)`
    margin-top: 1.5rem;
`;
const Label = styled.div`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-weight: ${({
  theme
}) => theme.layout.labelWeight};
    font-size: ${({
  theme
}) => theme.layout.labelSize};
`;
const SectionLabel = styled(Label)`
    padding-top: 0.6rem;
`;
const ValueBox = styled.div`
    background-color: ${({
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
}) => theme.layout.containerPaddingCompact};
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
`;
const ValueBoxWithButton = styled(ValueBox)`
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: ${({
  theme
}) => theme.layout.formRowGap};
    flex-wrap: nowrap;
    overflow: hidden;
    @media (max-width: 1000px) {
        flex-wrap: wrap;
        gap: 0.5rem;
    }
`;
const Mono = styled.span`
    color: ${({
  theme
}) => theme.colors.text};
    font-size: ${({
  theme
}) => theme.layout.monoSize};
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
`;
const InlineMono = styled(Mono)`
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
    min-width: 0;
`;
const PeerList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
`;
const PeerItem = styled.div`
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0.5rem;
    padding: ${({
  theme
}) => theme.layout.cardPadding};
    background: ${({
  theme
}) => theme.layout.cardBg};
    border-radius: ${({
  theme
}) => theme.layout.cardRadius};
    border-bottom: ${({
  theme
}) => theme.layout.cardBorderBottom};
    transition: background 0.2s ease;

    &:hover {
        background: ${({
  theme
}) => theme.colors.panelAlt};
    }
`;
const PeerLink = styled.a`
    color: ${({
  theme
}) => theme.colors.link};
    text-decoration: none;
    font-size: 0.85rem;
    font-weight: 500;
    transition: color 0.2s ease;
    &:hover { color: #667eea; }
`;
const PeerIp = styled.span`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-size: 0.75rem;
`;
const AccountList = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
`;
const AccountItem = styled.div`
    display: grid;
    grid-template-columns: 2rem 1fr auto;
    align-items: center;
    gap: 0.5rem;
    padding: 0.4rem 0.6rem;
    background: ${({
  theme
}) => theme.colors.panel};
    border-radius: 6px;
    
    @media (max-width: 1000px) {
        grid-template-columns: 1.5rem 1fr auto;
        gap: 0.35rem;
        padding: 0.35rem 0.5rem;
    }
`;
const AccountRank = styled.span`
    color: ${({
  theme
}) => theme.colors.subtleText};
    font-size: 0.75rem;
    font-weight: 600;
    text-align: center;
`;
const AccountName = styled.a`
    color: ${({
  theme
}) => theme.colors.link};
    text-decoration: none;
    font-size: 0.8rem;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    &:hover { color: #667eea; }
`;
const AccountBalance = styled.span`
    color: ${({
  theme
}) => theme.colors.text};
    font-size: 0.8rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    white-space: nowrap;
`;
const ChartWrapper = styled.div`
    width: 100%;
    max-width: 600px;
`;
const ChartContainer = styled.div`
    width: 100%;
    aspect-ratio: 400 / 120;
`;
const ChartSvg = styled.svg`
    width: 100%;
    height: 100%;
`;
const ChartLabel = styled.div`
    display: flex;
    justify-content: space-between;
    font-size: 0.7rem;
    color: ${({
  theme
}) => theme.colors.subtleText};
`;
const ChartLegend = styled.div`
    display: flex;
    gap: 1rem;
    font-size: 0.7rem;
`;
const LegendItem = styled.span`
    display: flex;
    align-items: center;
    gap: 0.25rem;
    color: ${({
  theme
}) => theme.colors.subtleText};
`;
const LegendDot = styled.span`
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: ${props => props.color};
`;

// Shared chart layout constants — ALL charts MUST use the same values so axes align.
// labelH reserves space above/below the plot area for Y-axis text labels.

// Shared SVG grid (left axis, bottom axis, right axis)
function ChartGrid() {
  const {
    width,
    height,
    padding
  } = CHART;
  return <>
            <line x1={padding.left} y1={padding.top} x2={padding.left} y2={height - padding.bottom} stroke="#444" strokeWidth="1" />
            <line x1={padding.left} y1={height - padding.bottom} x2={width - padding.right} y2={height - padding.bottom} stroke="#444" strokeWidth="1" />
            <line x1={width - padding.right} y1={padding.top} x2={width - padding.right} y2={height - padding.bottom} stroke="#444" strokeWidth="1" />
        </>;
}
function DifficultyChart({
  history
}) {
  if (!history || history.length < 2) {
    return <ChartWrapper>
                <ChartContainer>
                    <Mono style={{
          fontSize: '0.75rem',
          color: '#888'
        }}>
                        (chart available after more data is collected)
                    </Mono>
                </ChartContainer>
            </ChartWrapper>;
  }
  const {
    width,
    height,
    padding,
    innerW,
    innerH
  } = CHART;

  // Difficulty data (left axis, blue)
  const difficulties = history.map(h => h.difficulty);
  const minDiff = Math.min(...difficulties);
  const maxDiff = Math.max(...difficulties);
  const diffRange = maxDiff - minDiff || 1;

  // Message count data (right axis, green)
  const msgCounts = history.map(h => h.msg_count || 0);
  const maxMsg = Math.max(...msgCounts, 1);
  const minTs = history[0].timestamp;
  const maxTs = history[history.length - 1].timestamp;
  const tsRange = maxTs - minTs || 1;

  // Difficulty line (blue)
  const diffPoints = history.map(h => {
    const x = padding.left + (h.timestamp - minTs) / tsRange * innerW;
    const y = padding.top + innerH - (h.difficulty - minDiff) / diffRange * innerH;
    return `${x},${y}`;
  }).join(' ');

  // Message count line (green)
  const msgPoints = history.map(h => {
    const x = padding.left + (h.timestamp - minTs) / tsRange * innerW;
    const y = padding.top + innerH - (h.msg_count || 0) / maxMsg * innerH;
    return `${x},${y}`;
  }).join(' ');
  const hoursAgo = Math.round((Date.now() / 1000 - minTs) / 3600);
  return <ChartWrapper>
            <ChartLegend>
                <LegendItem><LegendDot color="#667eea" /> Difficulty</LegendItem>
                <LegendItem><LegendDot color="#48bb78" /> Msgs/Window</LegendItem>
            </ChartLegend>
            <ChartContainer>
                <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                    <ChartGrid />

                    {/* Left Y-axis labels (Difficulty - blue) */}
                    <text x={padding.left - 4} y={padding.top - 4} fill="#667eea" fontSize="8" textAnchor="end">{maxDiff}</text>
                    <text x={padding.left - 4} y={height - padding.bottom + 8} fill="#667eea" fontSize="8" textAnchor="end">{minDiff}</text>

                    {/* Right Y-axis labels (Msgs - green, just inside right axis) */}
                    <text x={width - padding.right - 2} y={padding.top - 4} fill="#48bb78" fontSize="8" textAnchor="end">{maxMsg}</text>
                    <text x={width - padding.right - 2} y={height - padding.bottom + 8} fill="#48bb78" fontSize="8" textAnchor="end">0</text>

                    {/* Message count area fill (green, behind) */}
                    <polygon fill="rgba(72, 187, 120, 0.15)" points={`${padding.left},${height - padding.bottom} ${msgPoints} ${width - padding.right},${height - padding.bottom}`} />

                    {/* Message count line (green) */}
                    <polyline fill="none" stroke="#48bb78" strokeWidth="1.5" points={msgPoints} />

                    {/* Difficulty line (blue, on top) */}
                    <polyline fill="none" stroke="#667eea" strokeWidth="2" points={diffPoints} />
                </ChartSvg>
            </ChartContainer>
            <ChartLabel>
                <span>{hoursAgo}h ago</span>
                <span>now</span>
            </ChartLabel>
        </ChartWrapper>;
}
function BurnMintChart({
  history
}) {
  if (!history || history.length < 2) {
    return <ChartWrapper>
                <ChartContainer>
                    <Mono style={{
          fontSize: '0.75rem',
          color: '#888'
        }}>
                        (chart available after more data is collected)
                    </Mono>
                </ChartContainer>
            </ChartWrapper>;
  }
  const {
    width,
    height,
    padding,
    innerW,
    innerH
  } = CHART;

  // Cumulative minted/burned from real supply deltas
  const data = [];
  let cumMinted = 0;
  let cumBurned = 0;
  for (let i = 1; i < history.length; i++) {
    const delta = history[i].total_supply - history[i - 1].total_supply;
    if (delta > 0) cumMinted += delta;else cumBurned += -delta;
    data.push({
      timestamp: history[i].timestamp,
      minted: cumMinted,
      burned: cumBurned
    });
  }
  if (data.length < 1) return null;
  const lastPt = data[data.length - 1];
  const totalMinted = cumMinted / 1e6;
  const totalBurned = lastPt.burned / 1e6;
  const maxY = Math.max(cumMinted, lastPt.burned, 1);
  const minTs = data[0].timestamp;
  const tsRange = data[data.length - 1].timestamp - minTs || 1;
  const toXY = (d, val) => {
    const x = padding.left + (d.timestamp - minTs) / tsRange * innerW;
    const y = padding.top + innerH - val / maxY * innerH;
    return `${x},${y}`;
  };
  const mintedPts = data.map(d => toXY(d, d.minted)).join(' ');
  const burnedPts = data.map(d => toXY(d, d.burned)).join(' ');
  const daysAgo = Math.round((Date.now() / 1000 - minTs) / 86400);
  const base = `${padding.left},${height - padding.bottom}`;
  const end = `${width - padding.right},${height - padding.bottom}`;
  return <ChartWrapper>
            <ChartLegend>
                <LegendItem><LegendDot color="#48bb78" /> Minted ({fmtMirage(totalMinted)})</LegendItem>
                <LegendItem><LegendDot color="#f56565" /> Burned ({fmtMirage(totalBurned)})</LegendItem>
            </ChartLegend>
            <ChartContainer>
                <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                    <ChartGrid />
                    <text x={padding.left - 4} y={padding.top - 4} fill="#888" fontSize="8" textAnchor="end">{fmtMirage(maxY / 1e6)}</text>
                    <text x={padding.left - 4} y={height - padding.bottom + 8} fill="#888" fontSize="8" textAnchor="end">0</text>
                    <polygon fill="rgba(72, 187, 120, 0.15)" points={`${base} ${mintedPts} ${end}`} />
                    <polygon fill="rgba(245, 101, 101, 0.15)" points={`${base} ${burnedPts} ${end}`} />
                    <polyline fill="none" stroke="#48bb78" strokeWidth="1.5" points={mintedPts} />
                    <polyline fill="none" stroke="#f56565" strokeWidth="1.5" points={burnedPts} />
                </ChartSvg>
            </ChartContainer>
            <ChartLabel>
                <span>{daysAgo}d ago</span>
                <span>now</span>
            </ChartLabel>
        </ChartWrapper>;
}
function SupplyChart({
  history
}) {
  if (!history || history.length < 2) {
    return <ChartWrapper>
                <ChartContainer>
                    <Mono style={{
          fontSize: '0.75rem',
          color: '#888'
        }}>
                        (chart available after more data is collected)
                    </Mono>
                </ChartContainer>
            </ChartWrapper>;
  }
  const {
    width,
    height,
    padding,
    innerW,
    innerH
  } = CHART;
  const data = history.map(h => ({
    timestamp: h.timestamp,
    supply: h.total_supply / 1e6
  }));
  const minS = Math.min(...data.map(d => d.supply));
  const maxS = Math.max(...data.map(d => d.supply));
  const range = maxS - minS || 1;
  const delta = data[data.length - 1].supply - data[0].supply;
  const minTs = data[0].timestamp;
  const tsRange = data[data.length - 1].timestamp - minTs || 1;
  const pts = data.map(d => {
    const x = padding.left + (d.timestamp - minTs) / tsRange * innerW;
    const y = padding.top + innerH - (d.supply - minS) / range * innerH;
    return `${x},${y}`;
  }).join(' ');
  const daysAgo = Math.round((Date.now() / 1000 - minTs) / 86400);
  const color = delta >= 0 ? '#48bb78' : '#f56565';
  const fill = delta >= 0 ? 'rgba(72, 187, 120, 0.15)' : 'rgba(245, 101, 101, 0.15)';

  // Y-axis labels: pick a unit where top != bottom label
  const fmtAxis = v => {
    // Use the smallest unit that makes the labels distinct
    if (maxS >= 1e9) {
      // Check if B-level labels would be identical
      const topB = (maxS / 1e9).toFixed(2);
      const botB = (minS / 1e9).toFixed(2);
      if (topB !== botB) return (v / 1e9).toFixed(2) + 'B';
      // Fall through to M
    }
    if (maxS >= 1e6) {
      const topM = Math.round(maxS / 1e6);
      const botM = Math.round(minS / 1e6);
      if (topM !== botM) return Math.round(v / 1e6).toLocaleString() + 'M';
      return (v / 1e6).toFixed(1) + 'M';
    }
    return fmtMirage(v);
  };
  const fmtDelta = v => {
    const sign = v >= 0 ? '+' : '';
    return sign + fmtMirage(v);
  };
  const base = `${padding.left},${height - padding.bottom}`;
  const end = `${width - padding.right},${height - padding.bottom}`;
  return <ChartWrapper>
            <ChartLegend>
                <LegendItem><LegendDot color={color} /> Supply ({fmtDelta(delta)})</LegendItem>
            </ChartLegend>
            <ChartContainer>
                <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                    <ChartGrid />
                    <text x={padding.left - 4} y={padding.top - 4} fill="#888" fontSize="8" textAnchor="end">{fmtAxis(maxS)}</text>
                    <text x={padding.left - 4} y={height - padding.bottom + 8} fill="#888" fontSize="8" textAnchor="end">{fmtAxis(minS)}</text>
                    <polygon fill={fill} points={`${base} ${pts} ${end}`} />
                    <polyline fill="none" stroke={color} strokeWidth="1.5" points={pts} />
                </ChartSvg>
            </ChartContainer>
            <ChartLabel>
                <span>{daysAgo}d ago</span>
                <span>now</span>
            </ChartLabel>
        </ChartWrapper>;
}
function NodeBalanceChart({
  history
}) {
  // Filter to entries that have node_balance recorded
  const data = (history || []).filter(h => h.node_balance != null);
  if (data.length < 2) {
    return <ChartWrapper>
                <ChartContainer>
                    <Mono style={{
          fontSize: '0.75rem',
          color: '#888'
        }}>
                        (collecting node balance data...)
                    </Mono>
                </ChartContainer>
            </ChartWrapper>;
  }
  const {
    width,
    height,
    padding,
    innerW,
    innerH
  } = CHART;
  const balances = data.map(d => d.node_balance / 1e6);
  const minB = Math.min(...balances);
  const maxB = Math.max(...balances);
  const range = maxB - minB || 1;
  const delta = balances[balances.length - 1] - balances[0];
  const minTs = data[0].timestamp;
  const tsRange = data[data.length - 1].timestamp - minTs || 1;
  const pts = data.map((d, i) => {
    const x = padding.left + (d.timestamp - minTs) / tsRange * innerW;
    const y = padding.top + innerH - (balances[i] - minB) / range * innerH;
    return `${x},${y}`;
  }).join(' ');
  const daysAgo = Math.round((Date.now() / 1000 - minTs) / 86400);
  const color = delta >= 0 ? '#48bb78' : '#f56565';
  const fill = delta >= 0 ? 'rgba(72, 187, 120, 0.15)' : 'rgba(245, 101, 101, 0.15)';
  const fmtAxis = v => {
    if (Math.abs(v) >= 1e9) return (v / 1e9).toFixed(2) + 'B';
    if (Math.abs(v) >= 1e6) {
      const topM = Math.round(maxB / 1e6);
      const botM = Math.round(minB / 1e6);
      if (topM !== botM) return Math.round(v / 1e6).toLocaleString() + 'M';
      return (v / 1e6).toFixed(1) + 'M';
    }
    return fmtMirage(v);
  };
  const fmtDelta = v => (v >= 0 ? '+' : '') + fmtMirage(v);
  const base = `${padding.left},${height - padding.bottom}`;
  const end = `${width - padding.right},${height - padding.bottom}`;
  return <ChartWrapper>
            <ChartLegend>
                <LegendItem><LegendDot color={color} /> Balance ({fmtDelta(delta)})</LegendItem>
            </ChartLegend>
            <ChartContainer>
                <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                    <ChartGrid />
                    <text x={padding.left - 4} y={padding.top - 4} fill="#888" fontSize="8" textAnchor="end">{fmtAxis(maxB)}</text>
                    <text x={padding.left - 4} y={height - padding.bottom + 8} fill="#888" fontSize="8" textAnchor="end">{fmtAxis(minB)}</text>
                    <polygon fill={fill} points={`${base} ${pts} ${end}`} />
                    <polyline fill="none" stroke={color} strokeWidth="1.5" points={pts} />
                </ChartSvg>
            </ChartContainer>
            <ChartLabel>
                <span>{daysAgo}d ago</span>
                <span>now</span>
            </ChartLabel>
        </ChartWrapper>;
}
function NodeMintBurnChart({
  history
}) {
  // Filter to entries that have the earnings counters recorded
  const raw = (history || []).filter(h => h.node_minted_total != null && h.node_fees_total != null);
  if (raw.length < 2) {
    return <ChartWrapper>
                <ChartContainer>
                    <Mono style={{
          fontSize: '0.75rem',
          color: '#888'
        }}>
                        (collecting earnings data...)
                    </Mono>
                </ChartContainer>
            </ChartWrapper>;
  }
  const {
    width,
    height,
    padding,
    innerW,
    innerH
  } = CHART;

  // The counters are lifetime totals, so the window is each sample measured
  // against its first. Summing balance movements instead treated coins arriving
  // as earnings and coins leaving as spending.
  const origin = raw[0];
  const data = raw.slice(1).map(h => ({
    timestamp: h.timestamp,
    earned: Math.max(0, h.node_minted_total - origin.node_minted_total),
    spent: Math.max(0, h.node_fees_total - origin.node_fees_total)
  }));
  if (data.length < 1) return null;
  const cumEarned = data[data.length - 1].earned;
  const cumSpent = data[data.length - 1].spent;
  const totalEarned = cumEarned / 1e6;
  const totalSpent = cumSpent / 1e6;
  const maxY = Math.max(cumEarned, cumSpent, 1);
  const minTs = data[0].timestamp;
  const tsRange = data[data.length - 1].timestamp - minTs || 1;
  const toXY = (d, val) => {
    const x = padding.left + (d.timestamp - minTs) / tsRange * innerW;
    const y = padding.top + innerH - val / maxY * innerH;
    return `${x},${y}`;
  };
  const earnedPts = data.map(d => toXY(d, d.earned)).join(' ');
  const spentPts = data.map(d => toXY(d, d.spent)).join(' ');
  const daysAgo = Math.round((Date.now() / 1000 - minTs) / 86400);
  const base = `${padding.left},${height - padding.bottom}`;
  const end = `${width - padding.right},${height - padding.bottom}`;
  return <ChartWrapper>
            <ChartLegend>
                <LegendItem><LegendDot color="#48bb78" /> Earned ({fmtMirage(totalEarned)})</LegendItem>
                <LegendItem><LegendDot color="#f56565" /> Spent ({fmtMirage(totalSpent)})</LegendItem>
            </ChartLegend>
            <ChartContainer>
                <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                    <ChartGrid />
                    <text x={padding.left - 4} y={padding.top - 4} fill="#888" fontSize="8" textAnchor="end">{fmtMirage(maxY / 1e6)}</text>
                    <text x={padding.left - 4} y={height - padding.bottom + 8} fill="#888" fontSize="8" textAnchor="end">0</text>
                    <polygon fill="rgba(72, 187, 120, 0.15)" points={`${base} ${earnedPts} ${end}`} />
                    <polygon fill="rgba(245, 101, 101, 0.15)" points={`${base} ${spentPts} ${end}`} />
                    <polyline fill="none" stroke="#48bb78" strokeWidth="1.5" points={earnedPts} />
                    <polyline fill="none" stroke="#f56565" strokeWidth="1.5" points={spentPts} />
                </ChartSvg>
            </ChartContainer>
            <ChartLabel>
                <span>{daysAgo}d ago</span>
                <span>now</span>
            </ChartLabel>
        </ChartWrapper>;
}
export default function NetworkView({
  state
}) {
  const {
    location,
    navigate,
    activeTab,
    cfg,
    peers,
    serverBalance,
    stakedBalance,
    copiedAddress,
    setCopiedAddress,
    circulationStats,
    supplyHistory,
    handleTabChange,
    toHttpUrl,
    getDisplayName
  } = useNetwork({
    state
  });
  return <ContentGrid>
            <Helmet>
                <title>Network | Mirage</title>
            </Helmet>
            <Sidebar currentPath={location.pathname} state={state} />
            <div>
                <TopBar state={state} />
                <ModernPostFeed>
                    <MobileHeader />
                    <TabbedContainer>
                        <TabsRow role="tablist" aria-label="Network sections">
                            <ClickableTab type="button" role="tab" aria-selected={activeTab === 'network'} $active={activeTab === 'network'} onClick={() => handleTabChange('network')}>
                                Network
                            </ClickableTab>
                            <ClickableTab type="button" role="tab" aria-selected={activeTab === 'server'} $active={activeTab === 'server'} onClick={() => handleTabChange('server')}>
                                Server
                            </ClickableTab>
                        </TabsRow>
                        <ContainerBody>
                            {activeTab === 'network' && <>
                                    <RowCentered>
                                        <Label>Circulation:</Label>
                                        <ValueBox>
                                            <Mono>
                                                {circulationStats.total_supply !== null ? `${formatMirage(circulationStats.total_supply)} MIRAGE` : '(loading...)'}
                                            </Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Block Time:</Label>
                                        <ValueBox>
                                            <Mono>{typeof cfg.block_time === 'number' ? `${cfg.block_time}s` : '(loading...)'}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Difficulty:</Label>
                                        <ValueBox>
                                            <Mono>{typeof cfg.pow_difficulty === 'number' ? `${cfg.pow_difficulty}` : '(loading...)'}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Msgs/Window:</Label>
                                        <ValueBox>
                                            <Mono>{typeof cfg.pow_message_count === 'number' ? cfg.pow_message_count : '(loading...)'}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Calm Streak:</Label>
                                        <ValueBox>
                                            <Mono>{typeof cfg.pow_calm_sequence === 'number' ? cfg.pow_calm_sequence : '(loading...)'}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Height:</Label>
                                        <ValueBox>
                                            <Mono>{typeof cfg.current_height === 'number' ? cfg.current_height.toLocaleString() : '(loading...)'}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <SectionRow>
                                        <SectionLabel>History:</SectionLabel>
                                        <ValueBox>
                                            <DifficultyChart history={cfg.difficulty_history && typeof cfg.pow_difficulty === 'number' ? [...cfg.difficulty_history, {
                    height: cfg.current_height || 0,
                    difficulty: cfg.pow_difficulty,
                    msg_count: cfg.pow_message_count || 0,
                    timestamp: Math.floor(Date.now() / 1000)
                  }] : cfg.difficulty_history} />
                                        </ValueBox>
                                    </SectionRow>
                                    <SectionRow>
                                        <SectionLabel>Minted vs Burned:</SectionLabel>
                                        <ValueBox>
                                            <BurnMintChart history={supplyHistory.history} />
                                        </ValueBox>
                                    </SectionRow>
                                    <SectionRow>
                                        <SectionLabel>Total Supply:</SectionLabel>
                                        <ValueBox>
                                            <SupplyChart history={supplyHistory.history} />
                                        </ValueBox>
                                    </SectionRow>
                                    <SectionRow>
                                        <SectionLabel>Sites:</SectionLabel>
                                        <ValueBox>
                                            {peers === null ? <Mono>(loading...)</Mono> : <PeerList>
                                                    {(() => {
                      if (!peers || !Array.isArray(peers) || peers.length === 0) {
                        return <Mono>(none)</Mono>;
                      }
                      return peers.map((peer, idx) => {
                        const peerObj = typeof peer === 'string' ? {
                          ip: peer,
                          moniker: null
                        } : peer;
                        if (!peerObj.ip && !peerObj.moniker) {
                          return null;
                        }
                        return <PeerItem key={`peer-${idx}`}>
                                                                    <PeerLink href={toHttpUrl(peerObj)} target="_blank" rel="noopener noreferrer">
                                                                        {getDisplayName(peerObj)}
                                                                    </PeerLink>
                                                                    {peerObj.moniker && (peerObj.moniker.startsWith('http://') || peerObj.moniker.startsWith('https://')) && peerObj.ip && <PeerIp> ({peerObj.ip})</PeerIp>}
                                                                </PeerItem>;
                      });
                    })()}
                                                </PeerList>}
                                        </ValueBox>
                                    </SectionRow>
                                    <SectionRow>
                                        <SectionLabel>Top Holders:</SectionLabel>
                                        <ValueBox>
                                            {circulationStats.top_accounts.length === 0 ? <Mono>(loading...)</Mono> : <AccountList>
                                                    {circulationStats.top_accounts.map((account, idx) => <AccountItem key={account.address}>
                                                            <AccountRank>#{idx + 1}</AccountRank>
                                                            <AccountName href={`/u/${account.username || account.address}`} onClick={e => {
                        if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                          e.preventDefault();
                          navigate(`/u/${account.username || account.address}`);
                        }
                      }}>
                                                                {account.username || account.address.slice(0, 12) + '...'}
                                                            </AccountName>
                                                            <AccountBalance>
                                                                {formatMirage(account.balance)}
                                                            </AccountBalance>
                                                        </AccountItem>)}
                                                </AccountList>}
                                        </ValueBox>
                                    </SectionRow>
                                </>}
                            {activeTab === 'server' && <>
                                    <RowCentered>
                                        <Label>Staked:</Label>
                                        <ValueBox>
                                            <Mono>{stakedBalance === null ? '(loading...)' : `${formatMirage(stakedBalance)} MIRAGE`}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Balance:</Label>
                                        <ValueBox>
                                            <Mono>{serverBalance === null ? '(loading...)' : `${formatMirage(serverBalance)} MIRAGE`}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Earned (24h):</Label>
                                        <ValueBox>
                                            <Mono>{cfg.earned_24h == null ? '(loading...)' : `${formatMirage(cfg.earned_24h)} MIRAGE`}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Spent (24h):</Label>
                                        <ValueBox>
                                            <Mono>{cfg.spent_24h == null ? '(loading...)' : `${formatMirage(cfg.spent_24h)} MIRAGE`}</Mono>
                                        </ValueBox>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Address:</Label>
                                        <ValueBoxWithButton>
                                            <InlineMono title={cfg.validator_account_address || ''}>{cfg.validator_account_address || '(loading...)'}</InlineMono>
                                            {cfg.validator_account_address && <Button onClick={() => {
                    navigator.clipboard.writeText(cfg.validator_account_address);
                    setCopiedAddress('mirage');
                    setTimeout(() => setCopiedAddress(null), 1500);
                  }} size="sm" minWidth="copy" copied={copiedAddress === 'mirage'}>
                                                    {copiedAddress === 'mirage' ? 'Copied!' : 'Copy'}
                                                </Button>}
                                        </ValueBoxWithButton>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Valoper:</Label>
                                        <ValueBoxWithButton>
                                            <InlineMono title={cfg.validator_operator_address || ''}>{cfg.validator_operator_address || '(loading...)'}</InlineMono>
                                            {cfg.validator_operator_address && <Button onClick={() => {
                    navigator.clipboard.writeText(cfg.validator_operator_address);
                    setCopiedAddress('valoper');
                    setTimeout(() => setCopiedAddress(null), 1500);
                  }} size="sm" minWidth="copy" copied={copiedAddress === 'valoper'}>
                                                    {copiedAddress === 'valoper' ? 'Copied!' : 'Copy'}
                                                </Button>}
                                        </ValueBoxWithButton>
                                    </RowCentered>
                                    <RowCentered>
                                        <Label>Valcons:</Label>
                                        <ValueBoxWithButton>
                                            <InlineMono title={cfg.validator_consensus_address || ''}>{cfg.validator_consensus_address || '(loading...)'}</InlineMono>
                                            {cfg.validator_consensus_address && <Button onClick={() => {
                    navigator.clipboard.writeText(cfg.validator_consensus_address);
                    setCopiedAddress('valcons');
                    setTimeout(() => setCopiedAddress(null), 1500);
                  }} size="sm" minWidth="copy" copied={copiedAddress === 'valcons'}>
                                                    {copiedAddress === 'valcons' ? 'Copied!' : 'Copy'}
                                                </Button>}
                                        </ValueBoxWithButton>
                                    </RowCentered>
                                    <SectionRow>
                                        <SectionLabel>Node Balance:</SectionLabel>
                                        <ValueBox>
                                            <NodeBalanceChart history={supplyHistory.history} />
                                        </ValueBox>
                                    </SectionRow>
                                    <SectionRow>
                                        <SectionLabel>Earned vs Spent:</SectionLabel>
                                        <ValueBox>
                                            <NodeMintBurnChart history={supplyHistory.history} />
                                        </ValueBox>
                                    </SectionRow>
                                </>}
                        </ContainerBody>
                    </TabbedContainer>
                </ModernPostFeed>
            </div>
        </ContentGrid>;
}