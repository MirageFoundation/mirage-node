import { Helmet } from "react-helmet-async";
import styled, { useTheme } from "styled-components";
import { HiClipboardDocument, HiCheck } from "react-icons/hi2";
import { ContentGrid, ModernPostFeed, TabbedContainer, ContainerBody } from "../Layout";
import { FeedRailRow, FeedCol } from "../components/FeedLayout.js";
import FeedRightRail from "../components/FeedRightRail.js";
import { Skeleton, ListRowSkeletonList } from "../components/Skeleton.js";
import { formatMirageCompact } from "../../../utils/formatters";
import { useNetwork, CHART, fmtMirage } from "../../../logic/useNetwork";

/**
 * NetworkView — `mirageapp` Plan 06 sub-plan 04 (refined).
 *
 * Section-list rewrite of the /network + /server routes. Visual only —
 * `useNetwork` data wiring, polling intervals, and copy handlers are
 * unchanged. Follows `docs/guides/web-theme-mirageapp/RULES.md`:
 *  - R1: single `bg` surface — no lifted panels. Only `SectionHeader`s
 *    (uppercase, subtleText) separate groups, like `SettingsView`.
 *  - R2: every color routed through a token (no raw hex / rgba).
 *  - R3: divider under page header uses `border`.
 *  - R4: data parity with `themes/bluemoon/routes/NetworkView.js`.
 *  - R7: page heading 1.1rem/700 (matches `SettingsView`), section
 *    header 0.6rem/700 uppercase, field label 0.72rem/500 text, field
 *    value 0.72rem/500 cardBodyText (matches `ProfileView`).
 */

/* -------------------------------------------------------------------------- */
/* Shell                                                                      */
/* -------------------------------------------------------------------------- */

const NetworkWrap = styled.div`
    width: 100%;
    max-width: 820px;
    margin: -0.75rem 0 0;

    @media (max-width: 1000px) {
        margin-top: -0.5rem;
    }

    @media (min-width: 1500px) {
        max-width: 960px;
    }
`;

const NetworkTabbedContainer = styled(TabbedContainer)`
    margin-top: 0;
`;

const NetworkShellBody = styled(ContainerBody)`
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
    grid-template-columns: repeat(${({ $count }) => $count || 2}, 1fr);
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

    &:hover { color: ${({ theme }) => theme.colors.text}; }
    &:focus { outline: none; }
`;

const TabIndicator = styled.div`
    position: absolute;
    bottom: -1px;
    left: 0;
    width: calc(100% / ${({ $count }) => $count || 2});
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

const SectionBody = styled.div`
    display: flex;
    flex-direction: column;
    padding-bottom: 0.35rem;
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
`;

const FieldValue = styled.div`
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
    min-width: 0;
    flex-wrap: nowrap;
    overflow: hidden;
`;

const ValueText = styled.span`
    color: ${({ theme }) => theme.colors.cardBodyText};
    font-size: 0.72rem;
    font-weight: 500;
    font-family: inherit;
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
`;

const InlineMono = styled(ValueText)`
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
    flex: 1;
    min-width: 0;
`;

/* -------------------------------------------------------------------------- */
/* Status pill (server tab "earned 24h" / "burned 24h" etc.)                  */
/* -------------------------------------------------------------------------- */

const StatusPill = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.1rem 0.45rem;
    border-radius: 999px;
    font-size: 0.68rem;
    font-weight: 600;
    background: ${({ theme, $tone }) => {
        if ($tone === 'up') return theme.colors.voteUpBg;
        if ($tone === 'down') return theme.colors.voteDownBg;
        return theme.colors.accent;
    }};
    color: ${({ theme, $tone }) => {
        if ($tone === 'up') return theme.colors.voteUp;
        if ($tone === 'down') return theme.colors.voteDown;
        return theme.colors.text;
    }};
`;

/* -------------------------------------------------------------------------- */
/* Icon action button (matches ProfileView's copy / edit pattern)             */
/* -------------------------------------------------------------------------- */

const IconActionButton = styled.button`
    appearance: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    padding: 0;
    border-radius: 9999px;
    border: none;
    background: ${({ theme, $success }) => ($success ? theme.colors.buttonSuccessBg : theme.colors.actionIconBg)};
    color: ${({ theme, $success }) => ($success ? theme.colors.voteUp : theme.colors.text)};
    cursor: pointer;
    flex-shrink: 0;
    transition: background 0.12s ease, color 0.12s ease;

    &:hover:not(:disabled) { background: ${({ theme, $success }) => ($success ? theme.colors.buttonSuccessBg : theme.colors.actionIconHoverBg)}; }
    &:disabled { cursor: not-allowed; opacity: 0.5; }
    &:focus { outline: none; }
    &:focus-visible { box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.borderStrong}; }

    svg { width: 14px; height: 14px; }
`;

/* -------------------------------------------------------------------------- */
/* Peers / Top Holders lists                                                  */
/* -------------------------------------------------------------------------- */

const ListBody = styled.div`
    display: flex;
    flex-direction: column;
    padding: 0 1rem 0.35rem;

    @media (max-width: 1000px) {
        padding: 0 0.85rem 0.35rem;
    }
`;

const PeerRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.3rem 0;
`;

const PeerLink = styled.a`
    color: ${({ theme }) => theme.colors.link};
    text-decoration: none;
    font-size: 0.72rem;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;

    &:hover { color: ${({ theme }) => theme.colors.linkHover}; }
`;

const PeerMeta = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.62rem;
    font-weight: 500;
    white-space: nowrap;
`;

const AccountRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.3rem 0;
`;

const AccountRank = styled.span`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.68rem;
    font-weight: 600;
    flex-shrink: 0;
    min-width: 1.25rem;
`;

const AccountName = styled.a`
    color: ${({ theme }) => theme.colors.link};
    text-decoration: none;
    font-size: 0.72rem;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
    flex: 1;

    &:hover { color: ${({ theme }) => theme.colors.linkHover}; }
`;

const AccountBalance = styled.span`
    color: ${({ theme }) => theme.colors.cardBodyText};
    font-size: 0.72rem;
    font-weight: 500;
    white-space: nowrap;
    flex-shrink: 0;
`;

const EmptyNote = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    font-weight: 500;
    font-style: italic;
    padding: 0.4rem 1rem 0.35rem;

    @media (max-width: 1000px) {
        padding: 0.4rem 0.85rem 0.35rem;
    }
`;

/* -------------------------------------------------------------------------- */
/* Chart primitives                                                           */
/* -------------------------------------------------------------------------- */

const ChartRow = styled.div`
    display: grid;
    grid-template-columns: 160px minmax(0, 1fr);
    gap: 1.5rem;
    align-items: start;
    padding: 0.55rem 1rem;
    box-sizing: border-box;
    width: 100%;

    @media (max-width: 1100px) {
        gap: 0.5rem;
    }

    @media (max-width: 1000px) {
        gap: 0.5rem;
        padding: 0.5rem 0.85rem;
    }

    @media (max-width: 700px) {
        grid-template-columns: 1fr;
        gap: 0.35rem;
    }
`;

const ChartRowLabel = styled.div`
    color: ${({ theme }) => theme.colors.text};
    font-weight: 500;
    font-size: 0.72rem;
    line-height: 1.3;
    white-space: nowrap;
`;

const ChartWrapper = styled.div`
    width: 100%;
    max-width: 600px;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
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
    font-size: 0.6rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.cardBodyText};
`;

const ChartLegend = styled.div`
    display: flex;
    gap: 1rem;
    font-size: 0.6rem;
    font-weight: 500;
    flex-wrap: wrap;
`;

const LegendItem = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    color: ${({ theme }) => theme.colors.cardBodyText};
`;

const LegendDot = styled.span`
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: ${({ $color }) => $color};
    flex-shrink: 0;
`;

const ChartEmpty = styled.div`
    color: ${({ theme }) => theme.colors.subtleText};
    font-size: 0.7rem;
    font-weight: 500;
    font-style: italic;
    padding: 0.25rem 0;
`;

/* -------------------------------------------------------------------------- */
/* Shared grid element (uses `border` token for axes)                         */
/* -------------------------------------------------------------------------- */

function ChartGrid({ stroke }) {
    const { width, height, padding } = CHART;
    return (
        <>
            <line x1={padding.left} y1={padding.top} x2={padding.left} y2={height - padding.bottom} stroke={stroke} strokeWidth="1" />
            <line x1={padding.left} y1={height - padding.bottom} x2={width - padding.right} y2={height - padding.bottom} stroke={stroke} strokeWidth="1" />
            <line x1={width - padding.right} y1={padding.top} x2={width - padding.right} y2={height - padding.bottom} stroke={stroke} strokeWidth="1" />
        </>
    );
}

function chartColors(theme) {
    return {
        grid: theme.colors.border,
        text: theme.colors.cardBodyText,
        diff: theme.colors.focusBlue,
        diffArea: theme.colors.accent,
        up: theme.colors.voteUp,
        upArea: theme.colors.voteUpBg,
        down: theme.colors.voteDown,
        downArea: theme.colors.voteDownBg,
        neutral: theme.colors.cardBodyText,
    };
}

/* -------------------------------------------------------------------------- */
/* Charts                                                                     */
/* -------------------------------------------------------------------------- */

function DifficultyChart({ history }) {
    const theme = useTheme();
    const c = chartColors(theme);

    if (!history || history.length < 2) {
        return (
            <ChartWrapper>
                <ChartEmpty>(chart available after more data is collected)</ChartEmpty>
            </ChartWrapper>
        );
    }
    const { width, height, padding, innerW, innerH } = CHART;

    const difficulties = history.map(h => h.difficulty);
    const minDiff = Math.min(...difficulties);
    const maxDiff = Math.max(...difficulties);
    const diffRange = maxDiff - minDiff || 1;

    const msgCounts = history.map(h => h.msg_count || 0);
    const maxMsg = Math.max(...msgCounts, 1);
    const minTs = history[0].timestamp;
    const maxTs = history[history.length - 1].timestamp;
    const tsRange = maxTs - minTs || 1;

    const diffPoints = history.map(h => {
        const x = padding.left + (h.timestamp - minTs) / tsRange * innerW;
        const y = padding.top + innerH - (h.difficulty - minDiff) / diffRange * innerH;
        return `${x},${y}`;
    }).join(' ');
    const msgPoints = history.map(h => {
        const x = padding.left + (h.timestamp - minTs) / tsRange * innerW;
        const y = padding.top + innerH - (h.msg_count || 0) / maxMsg * innerH;
        return `${x},${y}`;
    }).join(' ');
    const hoursAgo = Math.round((Date.now() / 1000 - minTs) / 3600);

    return (
        <ChartWrapper>
            <ChartLegend>
                <LegendItem><LegendDot $color={c.diff} /> Difficulty</LegendItem>
                <LegendItem><LegendDot $color={c.up} /> Msgs/Window</LegendItem>
            </ChartLegend>
            <ChartContainer>
                <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                    <ChartGrid stroke={c.grid} />

                    <text x={padding.left - 4} y={padding.top - 4} fill={c.diff} fontSize="8" textAnchor="end">{maxDiff}</text>
                    <text x={padding.left - 4} y={height - padding.bottom + 8} fill={c.diff} fontSize="8" textAnchor="end">{minDiff}</text>

                    <text x={width - padding.right - 2} y={padding.top - 4} fill={c.up} fontSize="8" textAnchor="end">{maxMsg}</text>
                    <text x={width - padding.right - 2} y={height - padding.bottom + 8} fill={c.up} fontSize="8" textAnchor="end">0</text>

                    <polygon fill={c.upArea} points={`${padding.left},${height - padding.bottom} ${msgPoints} ${width - padding.right},${height - padding.bottom}`} />
                    <polyline fill="none" stroke={c.up} strokeWidth="1.5" points={msgPoints} />
                    <polyline fill="none" stroke={c.diff} strokeWidth="2" points={diffPoints} />
                </ChartSvg>
            </ChartContainer>
            <ChartLabel>
                <span>{hoursAgo}h ago</span>
                <span>now</span>
            </ChartLabel>
        </ChartWrapper>
    );
}

function BurnMintChart({ history }) {
    const theme = useTheme();
    const c = chartColors(theme);

    if (!history || history.length < 2) {
        return (
            <ChartWrapper>
                <ChartEmpty>(chart available after more data is collected)</ChartEmpty>
            </ChartWrapper>
        );
    }
    const { width, height, padding, innerW, innerH } = CHART;

    const data = [];
    let cumMinted = 0;
    let cumBurned = 0;
    for (let i = 1; i < history.length; i++) {
        const delta = history[i].total_supply - history[i - 1].total_supply;
        if (delta > 0) cumMinted += delta; else cumBurned += -delta;
        data.push({ timestamp: history[i].timestamp, minted: cumMinted, burned: cumBurned });
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

    return (
        <ChartWrapper>
            <ChartLegend>
                <LegendItem><LegendDot $color={c.up} /> Minted ({fmtMirage(totalMinted)})</LegendItem>
                <LegendItem><LegendDot $color={c.down} /> Burned ({fmtMirage(totalBurned)})</LegendItem>
            </ChartLegend>
            <ChartContainer>
                <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                    <ChartGrid stroke={c.grid} />
                    <text x={padding.left - 4} y={padding.top - 4} fill={c.text} fontSize="8" textAnchor="end">{fmtMirage(maxY / 1e6)}</text>
                    <text x={padding.left - 4} y={height - padding.bottom + 8} fill={c.text} fontSize="8" textAnchor="end">0</text>
                    <polygon fill={c.upArea} points={`${base} ${mintedPts} ${end}`} />
                    <polygon fill={c.downArea} points={`${base} ${burnedPts} ${end}`} />
                    <polyline fill="none" stroke={c.up} strokeWidth="1.5" points={mintedPts} />
                    <polyline fill="none" stroke={c.down} strokeWidth="1.5" points={burnedPts} />
                </ChartSvg>
            </ChartContainer>
            <ChartLabel>
                <span>{daysAgo}d ago</span>
                <span>now</span>
            </ChartLabel>
        </ChartWrapper>
    );
}

function SupplyChart({ history }) {
    const theme = useTheme();
    const c = chartColors(theme);

    if (!history || history.length < 2) {
        return (
            <ChartWrapper>
                <ChartEmpty>(chart available after more data is collected)</ChartEmpty>
            </ChartWrapper>
        );
    }
    const { width, height, padding, innerW, innerH } = CHART;
    const data = history.map(h => ({ timestamp: h.timestamp, supply: h.total_supply / 1e6 }));
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
    const positive = delta >= 0;
    const color = positive ? c.up : c.down;
    const fill = positive ? c.upArea : c.downArea;

    const fmtAxis = v => {
        if (maxS >= 1e9) {
            const topB = (maxS / 1e9).toFixed(2);
            const botB = (minS / 1e9).toFixed(2);
            if (topB !== botB) return (v / 1e9).toFixed(2) + 'B';
        }
        if (maxS >= 1e6) {
            const topM = Math.round(maxS / 1e6);
            const botM = Math.round(minS / 1e6);
            if (topM !== botM) return Math.round(v / 1e6).toLocaleString() + 'M';
            return (v / 1e6).toFixed(1) + 'M';
        }
        return fmtMirage(v);
    };
    const fmtDelta = v => (v >= 0 ? '+' : '') + fmtMirage(v);
    const base = `${padding.left},${height - padding.bottom}`;
    const end = `${width - padding.right},${height - padding.bottom}`;

    return (
        <ChartWrapper>
            <ChartLegend>
                <LegendItem><LegendDot $color={color} /> Supply ({fmtDelta(delta)})</LegendItem>
            </ChartLegend>
            <ChartContainer>
                <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                    <ChartGrid stroke={c.grid} />
                    <text x={padding.left - 4} y={padding.top - 4} fill={c.text} fontSize="8" textAnchor="end">{fmtAxis(maxS)}</text>
                    <text x={padding.left - 4} y={height - padding.bottom + 8} fill={c.text} fontSize="8" textAnchor="end">{fmtAxis(minS)}</text>
                    <polygon fill={fill} points={`${base} ${pts} ${end}`} />
                    <polyline fill="none" stroke={color} strokeWidth="1.5" points={pts} />
                </ChartSvg>
            </ChartContainer>
            <ChartLabel>
                <span>{daysAgo}d ago</span>
                <span>now</span>
            </ChartLabel>
        </ChartWrapper>
    );
}

function NodeBalanceChart({ history }) {
    const theme = useTheme();
    const c = chartColors(theme);

    const data = (history || []).filter(h => h.node_balance != null);
    if (data.length < 2) {
        return (
            <ChartWrapper>
                <ChartEmpty>(collecting node balance data…)</ChartEmpty>
            </ChartWrapper>
        );
    }
    const { width, height, padding, innerW, innerH } = CHART;
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
    const positive = delta >= 0;
    const color = positive ? c.up : c.down;
    const fill = positive ? c.upArea : c.downArea;
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

    return (
        <ChartWrapper>
            <ChartLegend>
                <LegendItem><LegendDot $color={color} /> Balance ({fmtDelta(delta)})</LegendItem>
            </ChartLegend>
            <ChartContainer>
                <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                    <ChartGrid stroke={c.grid} />
                    <text x={padding.left - 4} y={padding.top - 4} fill={c.text} fontSize="8" textAnchor="end">{fmtAxis(maxB)}</text>
                    <text x={padding.left - 4} y={height - padding.bottom + 8} fill={c.text} fontSize="8" textAnchor="end">{fmtAxis(minB)}</text>
                    <polygon fill={fill} points={`${base} ${pts} ${end}`} />
                    <polyline fill="none" stroke={color} strokeWidth="1.5" points={pts} />
                </ChartSvg>
            </ChartContainer>
            <ChartLabel>
                <span>{daysAgo}d ago</span>
                <span>now</span>
            </ChartLabel>
        </ChartWrapper>
    );
}

function NodeMintBurnChart({ history }) {
    const theme = useTheme();
    const c = chartColors(theme);

    const raw = (history || []).filter(h => h.node_balance != null);
    if (raw.length < 2) {
        return (
            <ChartWrapper>
                <ChartEmpty>(collecting node balance data…)</ChartEmpty>
            </ChartWrapper>
        );
    }
    const { width, height, padding, innerW, innerH } = CHART;

    const data = [];
    let cumEarned = 0;
    let cumSpent = 0;
    for (let i = 1; i < raw.length; i++) {
        const diff = raw[i].node_balance - raw[i - 1].node_balance;
        if (diff > 0) cumEarned += diff; else if (diff < 0) cumSpent += -diff;
        data.push({ timestamp: raw[i].timestamp, earned: cumEarned, spent: cumSpent });
    }
    if (data.length < 1) return null;
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

    return (
        <ChartWrapper>
            <ChartLegend>
                <LegendItem><LegendDot $color={c.up} /> Earned ({fmtMirage(totalEarned)})</LegendItem>
                <LegendItem><LegendDot $color={c.down} /> Spent ({fmtMirage(totalSpent)})</LegendItem>
            </ChartLegend>
            <ChartContainer>
                <ChartSvg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
                    <ChartGrid stroke={c.grid} />
                    <text x={padding.left - 4} y={padding.top - 4} fill={c.text} fontSize="8" textAnchor="end">{fmtMirage(maxY / 1e6)}</text>
                    <text x={padding.left - 4} y={height - padding.bottom + 8} fill={c.text} fontSize="8" textAnchor="end">0</text>
                    <polygon fill={c.upArea} points={`${base} ${earnedPts} ${end}`} />
                    <polygon fill={c.downArea} points={`${base} ${spentPts} ${end}`} />
                    <polyline fill="none" stroke={c.up} strokeWidth="1.5" points={earnedPts} />
                    <polyline fill="none" stroke={c.down} strokeWidth="1.5" points={spentPts} />
                </ChartSvg>
            </ChartContainer>
            <ChartLabel>
                <span>{daysAgo}d ago</span>
                <span>now</span>
            </ChartLabel>
        </ChartWrapper>
    );
}

/* -------------------------------------------------------------------------- */
/* Route                                                                      */
/* -------------------------------------------------------------------------- */

const TABS = [
    { id: 'network', label: 'Network' },
    { id: 'server', label: 'Server' },
];

export default function NetworkView({ state }) {
    const {
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
        getDisplayName,
    } = useNetwork({ state });

    const activeTabIndex = Math.max(0, TABS.findIndex(t => t.id === activeTab));

    const renderValue = (v, suffix = '') => v === null || v === undefined
        ? <Skeleton width="6rem" height="0.75rem" inline />
        : <ValueText>{v}{suffix}</ValueText>;

    const renderCopyRow = (label, addr, key) => (
        <FieldRow>
            <FieldLabel>{label}:</FieldLabel>
            <FieldValue>
                <InlineMono title={addr || ''}>
                    {addr || <Skeleton width="14rem" height="0.75rem" inline />}
                </InlineMono>
                {addr && (
                    <IconActionButton
                        type="button"
                        onClick={() => {
                            navigator.clipboard.writeText(addr);
                            setCopiedAddress(key);
                            setTimeout(() => setCopiedAddress(null), 1500);
                        }}
                        $success={copiedAddress === key}
                        title={copiedAddress === key ? 'Copied!' : `Copy ${label.toLowerCase()}`}
                        aria-label={copiedAddress === key ? 'Copied' : `Copy ${label.toLowerCase()}`}
                    >
                        {copiedAddress === key ? <HiCheck aria-hidden="true" /> : <HiClipboardDocument aria-hidden="true" />}
                    </IconActionButton>
                )}
            </FieldValue>
        </FieldRow>
    );

    const renderPeers = () => {
        if (peers === null) return <ListRowSkeletonList count={3} hasAvatar={false} showMeta={false} />;
        if (!Array.isArray(peers) || peers.length === 0) return <EmptyNote>(none)</EmptyNote>;
        return (
            <ListBody>
                {peers.map((peer, idx) => {
                    const p = typeof peer === 'string' ? { ip: peer, moniker: null } : peer;
                    if (!p.ip && !p.moniker) return null;
                    const hasMonikerUrl = p.moniker && (p.moniker.startsWith('http://') || p.moniker.startsWith('https://'));
                    return (
                        <PeerRow key={`peer-${idx}`}>
                            <PeerLink href={toHttpUrl(p)} target="_blank" rel="noopener noreferrer">
                                {getDisplayName(p)}
                            </PeerLink>
                            {hasMonikerUrl && p.ip && <PeerMeta>({p.ip})</PeerMeta>}
                        </PeerRow>
                    );
                })}
            </ListBody>
        );
    };

    const renderTopHolders = () => {
        if (circulationStats.top_accounts.length === 0) return <ListRowSkeletonList count={5} hasAvatar={false} />;
        return (
            <ListBody>
                {circulationStats.top_accounts.map((account, idx) => {
                    const label = account.username || `${account.address.slice(0, 12)}…`;
                    const href = `/u/${account.username || account.address}`;
                    return (
                        <AccountRow key={account.address}>
                            <AccountRank>#{idx + 1}</AccountRank>
                            <AccountName
                                href={href}
                                onClick={e => {
                                    if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
                                        e.preventDefault();
                                        navigate(href);
                                    }
                                }}
                            >
                                {label}
                            </AccountName>
                            <AccountBalance>{formatMirageCompact(account.balance)}</AccountBalance>
                        </AccountRow>
                    );
                })}
            </ListBody>
        );
    };

    return (
        <ContentGrid>
            <Helmet>
                <title>Network | Mirage</title>
            </Helmet>
            <FeedRailRow $feedViewMode="card">
                <FeedCol>
                    <ModernPostFeed>
                        <NetworkTabbedContainer>
                            <NetworkShellBody>
                                <NetworkWrap>
                            <HeaderRow>
                                <HeaderTitle>Network</HeaderTitle>
                            </HeaderRow>
                            <SectionDivider />
                            <TabsRow role="tablist" aria-label="Network sections" $count={TABS.length}>
                                {TABS.map(tab => (
                                    <TabButton
                                        key={tab.id}
                                        type="button"
                                        role="tab"
                                        aria-selected={activeTab === tab.id}
                                        $active={activeTab === tab.id}
                                        onClick={() => handleTabChange(tab.id)}
                                    >
                                        {tab.label}
                                    </TabButton>
                                ))}
                                <TabIndicator $count={TABS.length} $index={activeTabIndex} aria-hidden="true" />
                            </TabsRow>

                            {activeTab === 'network' && (
                                <>
                                    <Section>
                                        <SectionHeader>Chain Info</SectionHeader>
                                        <SectionBody>
                                            <FieldRow>
                                                <FieldLabel>Circulation:</FieldLabel>
                                                <FieldValue>
                                                    {circulationStats.total_supply !== null
                                                        ? <ValueText>{formatMirageCompact(circulationStats.total_supply)} MIRAGE</ValueText>
                                                        : <Skeleton width="8rem" height="0.75rem" inline />}
                                                </FieldValue>
                                            </FieldRow>
                                            <FieldRow>
                                                <FieldLabel>Block Time:</FieldLabel>
                                                <FieldValue>
                                                    {typeof cfg.block_time === 'number'
                                                        ? <ValueText>{cfg.block_time}s</ValueText>
                                                        : <Skeleton width="3rem" height="0.75rem" inline />}
                                                </FieldValue>
                                            </FieldRow>
                                            <FieldRow>
                                                <FieldLabel>Difficulty:</FieldLabel>
                                                <FieldValue>{renderValue(typeof cfg.pow_difficulty === 'number' ? cfg.pow_difficulty : null)}</FieldValue>
                                            </FieldRow>
                                            <FieldRow>
                                                <FieldLabel>Msgs/Window:</FieldLabel>
                                                <FieldValue>{renderValue(typeof cfg.pow_message_count === 'number' ? cfg.pow_message_count : null)}</FieldValue>
                                            </FieldRow>
                                            <FieldRow>
                                                <FieldLabel>Calm Streak:</FieldLabel>
                                                <FieldValue>{renderValue(typeof cfg.pow_calm_sequence === 'number' ? cfg.pow_calm_sequence : null)}</FieldValue>
                                            </FieldRow>
                                            <FieldRow>
                                                <FieldLabel>Height:</FieldLabel>
                                                <FieldValue>{renderValue(typeof cfg.current_height === 'number' ? cfg.current_height.toLocaleString() : null)}</FieldValue>
                                            </FieldRow>
                                        </SectionBody>
                                    </Section>

                                    <ChartRow>
                                        <ChartRowLabel>Difficulty History:</ChartRowLabel>
                                        <DifficultyChart history={cfg.difficulty_history && typeof cfg.pow_difficulty === 'number' ? [...cfg.difficulty_history, {
                                            height: cfg.current_height || 0,
                                            difficulty: cfg.pow_difficulty,
                                            msg_count: cfg.pow_message_count || 0,
                                            timestamp: Math.floor(Date.now() / 1000),
                                        }] : cfg.difficulty_history} />
                                    </ChartRow>

                                    <ChartRow>
                                        <ChartRowLabel>Minted vs Burned:</ChartRowLabel>
                                        <BurnMintChart history={supplyHistory.history} />
                                    </ChartRow>

                                    <ChartRow>
                                        <ChartRowLabel>Total Supply:</ChartRowLabel>
                                        <SupplyChart history={supplyHistory.history} />
                                    </ChartRow>

                                    <Section>
                                        <SectionHeader>Sites</SectionHeader>
                                        {renderPeers()}
                                    </Section>

                                    <Section>
                                        <SectionHeader>Top Holders</SectionHeader>
                                        {renderTopHolders()}
                                    </Section>
                                </>
                            )}

                            {activeTab === 'server' && (
                                <>
                                    <Section>
                                        <SectionHeader>Validator Balance</SectionHeader>
                                        <SectionBody>
                                            <FieldRow>
                                                <FieldLabel>Staked:</FieldLabel>
                                                <FieldValue>
                                                    {stakedBalance === null
                                                        ? <Skeleton width="8rem" height="0.75rem" inline />
                                                        : <ValueText>{formatMirageCompact(stakedBalance)} MIRAGE</ValueText>}
                                                </FieldValue>
                                            </FieldRow>
                                            <FieldRow>
                                                <FieldLabel>Balance:</FieldLabel>
                                                <FieldValue>
                                                    {serverBalance === null
                                                        ? <Skeleton width="8rem" height="0.75rem" inline />
                                                        : <ValueText>{formatMirageCompact(serverBalance)} MIRAGE</ValueText>}
                                                </FieldValue>
                                            </FieldRow>
                                            <FieldRow>
                                                <FieldLabel>Earned (24h):</FieldLabel>
                                                <FieldValue>
                                                    {cfg.earned_24h == null
                                                        ? <Skeleton width="8rem" height="0.75rem" inline />
                                                        : <StatusPill $tone={cfg.earned_24h > 0 ? 'up' : 'neutral'}>
                                                            +{formatMirageCompact(cfg.earned_24h)} MIRAGE
                                                        </StatusPill>}
                                                </FieldValue>
                                            </FieldRow>
                                            <FieldRow>
                                                <FieldLabel>Burned (24h):</FieldLabel>
                                                <FieldValue>
                                                    {cfg.burned_24h == null
                                                        ? <Skeleton width="8rem" height="0.75rem" inline />
                                                        : <StatusPill $tone={cfg.burned_24h > 0 ? 'down' : 'neutral'}>
                                                            −{formatMirageCompact(cfg.burned_24h)} MIRAGE
                                                        </StatusPill>}
                                                </FieldValue>
                                            </FieldRow>
                                        </SectionBody>
                                    </Section>

                                    <Section>
                                        <SectionHeader>Validator Addresses</SectionHeader>
                                        <SectionBody>
                                            {renderCopyRow('Address', cfg.validator_account_address, 'mirage')}
                                            {renderCopyRow('Valoper', cfg.validator_operator_address, 'valoper')}
                                            {renderCopyRow('Valcons', cfg.validator_consensus_address, 'valcons')}
                                        </SectionBody>
                                    </Section>

                                    <ChartRow>
                                        <ChartRowLabel>Node Balance:</ChartRowLabel>
                                        <NodeBalanceChart history={supplyHistory.history} />
                                    </ChartRow>

                                    <ChartRow>
                                        <ChartRowLabel>Earned vs Spent:</ChartRowLabel>
                                        <NodeMintBurnChart history={supplyHistory.history} />
                                    </ChartRow>
                                </>
                            )}
                                </NetworkWrap>
                            </NetworkShellBody>
                        </NetworkTabbedContainer>
                    </ModernPostFeed>
                </FeedCol>
                <FeedRightRail />
            </FeedRailRow>
        </ContentGrid>
    );
}
