import React, { useMemo } from "react";
import { Helmet } from "react-helmet-async";
import styled, { useTheme } from "styled-components";
import {
    ResponsiveContainer, AreaChart, Area, BarChart, Bar,
    XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine,
} from "recharts";
import { useStats } from "../logic/useStats";
import Storage from "../utils/Storage";

const CHART_COLORS = {
    newUsers: "#2563eb",
    contributors: "#14b8a6",
    active: "#22c55e",
    posts: "#8b5cf6",
    comments: "#f59e0b",
    retention: "#2563eb",
    retained: "#22c55e",
    churned: "#ef4444",
    pending: "rgba(130,132,148,0.55)",
};

// Backend buckets days at UTC midnight, so label them in UTC too. Using local
// getMonth/getDate would shift every label back a day for viewers west of UTC
// (e.g. a 6/23 00:00 UTC bucket rendered as "6/22" at UTC-4).
const shortDay = (t) => {
    const d = new Date(t * 1000);
    return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
};

/**
 * Admin-only, fleet-wide growth dashboard. Theme-neutral: reads a few common
 * theme tokens with safe fallbacks so it renders correctly under every theme.
 * Data comes from the signed /api/admin/stats/aggregate endpoint via useStats.
 */

const tok = (theme, key, fallback) => (theme && theme.colors && theme.colors[key]) || fallback;

// Neutral, translucent surface/border tokens. Built from grey alpha so the same
// values read correctly on both dark and light themes without knowing which is
// active — they darken light backgrounds and lighten dark ones.
const SURFACE = "rgba(130,132,148,0.06)";
const SURFACE_HOVER = "rgba(130,132,148,0.11)";
const BORDER = "rgba(130,132,148,0.22)";
const BORDER_SOFT = "rgba(130,132,148,0.13)";
const ACCENT = "#2563eb";

const Page = styled.div`
    width: 100%;
    max-width: 1180px;
    margin: 0 auto;
    padding: 1.5rem 1.5rem 4rem;
    color: ${({ theme }) => tok(theme, "text", "#e6e6e6")};
    font-variant-numeric: tabular-nums;
`;

const Header = styled.div`
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1.5rem;
`;

const Title = styled.h1`
    font-size: 1.6rem;
    font-weight: 750;
    letter-spacing: -0.02em;
    margin: 0 0 0.3rem;
`;

const Subtitle = styled.div`
    font-size: 0.82rem;
    opacity: 0.6;
`;

const Controls = styled.div`
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
`;

const Segmented = styled.div`
    display: inline-flex;
    align-items: center;
    padding: 0.2rem;
    gap: 0.15rem;
    background: ${SURFACE};
    border: 1px solid ${BORDER_SOFT};
    border-radius: 10px;
`;

const PresetBtn = styled.button`
    border: none;
    background: ${({ $active }) => ($active ? ACCENT : "transparent")};
    color: ${({ $active, theme }) => ($active ? "#fff" : tok(theme, "text", "#e6e6e6"))};
    border-radius: 7px;
    padding: 0.38rem 0.85rem;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.12s ease, color 0.12s ease;
    box-shadow: ${({ $active }) => ($active ? "0 1px 2px rgba(0,0,0,0.18)" : "none")};
    &:hover {
        background: ${({ $active }) => ($active ? ACCENT : SURFACE_HOVER)};
    }
`;

const GhostBtn = styled.button`
    border: 1px solid ${BORDER};
    background: ${SURFACE};
    color: ${({ theme }) => tok(theme, "text", "#e6e6e6")};
    border-radius: 9px;
    padding: 0.42rem 0.85rem;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.12s ease, border-color 0.12s ease;
    &:hover {
        background: ${SURFACE_HOVER};
        border-color: ${ACCENT};
    }
`;

const DateInput = styled.input`
    border: 1px solid ${BORDER};
    background: ${SURFACE};
    color: ${({ theme }) => tok(theme, "text", "#e6e6e6")};
    border-radius: 9px;
    padding: 0.38rem 0.6rem;
    font-size: 0.78rem;
    color-scheme: ${({ theme }) => (theme && theme.isLight ? "light" : "dark")};
`;

const SectionHeader = styled.div`
    display: flex;
    align-items: center;
    gap: 0.7rem;
    text-transform: uppercase;
    font-size: 0.68rem;
    letter-spacing: 0.08em;
    font-weight: 700;
    opacity: 0.55;
    margin: 2.1rem 0 0.7rem;
    &::after {
        content: "";
        flex: 1;
        height: 1px;
        background: ${BORDER_SOFT};
    }
`;

const TileGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 0.75rem;
`;

const Tile = styled.div`
    position: relative;
    overflow: hidden;
    background: ${SURFACE};
    border: 1px solid ${BORDER};
    border-radius: 14px;
    padding: 1rem 1.1rem 0.95rem 1.2rem;
    transition: background 0.12s ease, transform 0.12s ease;
    &::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 3px;
        background: ${({ $accent }) => $accent || "transparent"};
    }
    &:hover {
        background: ${SURFACE_HOVER};
    }
`;

const TileValue = styled.div`
    font-size: 1.85rem;
    font-weight: 750;
    line-height: 1.1;
    letter-spacing: -0.02em;
`;

const TileLabel = styled.div`
    font-size: 0.72rem;
    opacity: 0.6;
    margin-top: 0.4rem;
    line-height: 1.3;
`;

const Card = styled.div`
    background: ${SURFACE};
    border: 1px solid ${BORDER};
    border-radius: 16px;
    padding: 1.1rem 1.2rem;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
`;

const Table = styled.table`
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8rem;
`;

const Th = styled.th`
    text-align: ${({ $right }) => ($right ? "right" : "left")};
    padding: 0.55rem 0.6rem;
    border-bottom: 1px solid ${BORDER};
    opacity: 0.55;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.66rem;
    letter-spacing: 0.05em;
`;

const Td = styled.td`
    text-align: ${({ $right }) => ($right ? "right" : "left")};
    padding: 0.55rem 0.6rem;
    border-bottom: 1px solid ${BORDER_SOFT};
`;

const Tr = styled.tr`
    transition: background 0.1s ease;
    &:hover td {
        background: ${SURFACE};
    }
`;

const StatusPill = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    background: ${({ $ok }) => ($ok ? "rgba(34,197,94,0.16)" : "rgba(239,68,68,0.16)")};
    color: ${({ $ok }) => ($ok ? "#22c55e" : "#ef4444")};
    &::before {
        content: "";
        width: 0.4rem;
        height: 0.4rem;
        border-radius: 50%;
        background: currentColor;
    }
`;

const Message = styled.div`
    padding: 3rem 1rem;
    text-align: center;
    opacity: 0.7;
    font-size: 0.9rem;
`;

const SourceLegend = styled(Card)`
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
    margin-bottom: 0.5rem;
    font-size: 0.78rem;
    line-height: 1.5;
`;

const LegendItem = styled.div`
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
`;

const Dot = styled.span`
    flex: 0 0 auto;
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    background: ${({ $c }) => $c};
    box-shadow: 0 0 0 3px ${({ $c }) => $c}22;
    transform: translateY(1px);
`;

// Inline caveat under a section, used to spell out exactly what a metric does
// and does not cover (esp. on-chain-retroactive vs tracked-since-a-date).
const Note = styled.div`
    font-size: 0.74rem;
    line-height: 1.5;
    opacity: 0.65;
    margin: 0 0 0.8rem;
    max-width: 760px;
`;

const Warn = styled(Note)`
    opacity: 1;
    color: ${({ theme }) => tok(theme, "text", "#e6e6e6")};
    background: rgba(245, 158, 11, 0.08);
    border: 1px solid rgba(245, 158, 11, 0.3);
    border-left: 3px solid #f59e0b;
    border-radius: 8px;
    padding: 0.6rem 0.75rem;
`;

const ChartGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 0.9rem;
`;

const ChartCard = styled(Card)`
    padding: 1.1rem 1.1rem 0.7rem;
`;

const ChartTitle = styled.div`
    font-size: 0.85rem;
    font-weight: 700;
    margin-bottom: 0.9rem;
`;

const ChartHeight = styled.div`
    width: 100%;
    height: 240px;
`;

const SubNote = styled.div`
    font-size: 0.82rem;
    opacity: 0.6;
    margin: 0 0 0.5rem;
`;

function isAdmin() {
    try {
        return (Number(Storage.load("user_level", "0")) || 0) >= 100;
    } catch (_) {
        return false;
    }
}

export default function AdminStatsDashboard() {
    const theme = useTheme();
    const {
        preset, setPreset, PRESETS,
        customStart, setCustomStart, customEnd, setCustomEnd,
        aggregate, servers, windowRange: win,
        loading, error, refresh,
        formatNumber, formatPercent, formatDate,
    } = useStats();

    const admin = isAdmin();

    // Merge first-touch campaigns across all reachable servers.
    const campaigns = useMemo(() => {
        const map = new Map();
        for (const s of servers) {
            if (s.status !== "ok" || !s.stats) continue;
            for (const c of s.stats.campaigns || []) {
                const key = `${c.source}|${c.campaign}`;
                const cur = map.get(key) || { source: c.source, campaign: c.campaign, visitors: 0, signups: 0, contributors: 0 };
                cur.visitors += c.visitors || 0;
                cur.signups += c.signups || 0;
                cur.contributors += c.contributors || 0;
                map.set(key, cur);
            }
        }
        return Array.from(map.values())
            .map(c => ({
                ...c,
                signupConversion: c.visitors ? c.signups / c.visitors : 0,
                contributorConversion: c.signups ? c.contributors / c.signups : 0,
            }))
            .sort((a, b) => b.visitors - a.visitors)
            .slice(0, 25);
    }, [servers]);

    if (!admin) {
        return (
            <Page>
                <Helmet><title>Stats | Mirage</title></Helmet>
                <Title>Stats</Title>
                <Message>This page is restricted to administrators.</Message>
            </Page>
        );
    }

    const g = aggregate && aggregate.growth;
    const o = aggregate && aggregate.onchain;
    const r = aggregate && aggregate.retention;
    const series = (aggregate && aggregate.series) || [];
    const trackingSince = (aggregate && aggregate.tracking_since) || null;
    const trackingSinceLabel = trackingSince ? formatDate(trackingSince) : null;
    // Whether the selected window predates visitor tracking. If so, the tracked
    // metrics are empty and the tracked-engagement half of retention can't be seen.
    const windowEndsBeforeTracking = !!(trackingSince && win && win.end < trackingSince);
    const windowStartsBeforeTracking = !!(trackingSince && win && win.start < trackingSince);
    // Day bucket tracking began. Tracked lines (Active) are nulled before this so
    // the chart shows a gap, not a misleading flat zero, prior to tracking.
    const trackingSinceDay = trackingSince ? Math.floor(trackingSince / 86400) * 86400 : null;
    // Drop the current (still-building) UTC day so charts end at the last complete day.
    const todayDay = Math.floor(Date.now() / 1000 / 86400) * 86400;
    const chartSeries = series
        .filter(pt => pt.t < todayDay)
        .map(pt => {
            // Split each signup day into D7 outcome: retained (still active 7d
            // later), churned (eligible but gone), and pending (too recent to judge).
            const elig = pt.d7_eligible || 0;
            const retained = pt.d7_retained || 0;
            const churned = Math.max(elig - retained, 0);
            const pending = Math.max((pt.new_users || 0) - elig, 0);
            const active = trackingSinceDay != null && pt.t < trackingSinceDay ? null : pt.active;
            return { ...pt, active, d7_churned: churned, d7_pending: pending };
        });
    const retentionData = r ? ["d7", "d14", "d30"].map(k => ({
        name: k.toUpperCase(),
        rate: r[k].eligible ? Math.round(r[k].rate * 1000) / 10 : null,
        label: `${r[k].retained}/${r[k].eligible}`,
    })) : [];
    const axisColor = tok(theme, "text", "#e6e6e6");
    const gridColor = "rgba(127,127,127,0.18)";
    const tooltipStyle = {
        fontSize: 12,
        background: tok(theme, "background", "#15171c"),
        border: "1px solid rgba(130,132,148,0.3)",
        borderRadius: 10,
        boxShadow: "0 6px 20px rgba(0,0,0,0.25)",
        color: axisColor,
    };
    const tooltipLabelStyle = { color: axisColor, opacity: 0.7, marginBottom: 4 };

    return (
        <Page>
            <Helmet><title>Stats | Mirage</title></Helmet>
            <Header>
                <div>
                    <Title>Growth Stats</Title>
                    <Subtitle>
                        Fleet-wide, admin-only. {aggregate ? `${aggregate.servers_counted} server(s) reporting` : ""}
                        {win ? ` · ${formatDate(win.start)} – ${formatDate(win.end)}` : ""}
                    </Subtitle>
                </div>
                <Controls>
                    <Segmented>
                        {PRESETS.map(p => (
                            <PresetBtn key={p.id} $active={preset === p.id} onClick={() => setPreset(p.id)}>
                                {p.label}
                            </PresetBtn>
                        ))}
                        <PresetBtn $active={preset === "custom"} onClick={() => setPreset("custom")}>Custom</PresetBtn>
                    </Segmented>
                    {preset === "custom" && (
                        <>
                            <DateInput type="date" value={customStart} onChange={e => setCustomStart(e.target.value)} />
                            <span style={{ opacity: 0.5 }}>–</span>
                            <DateInput type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)} />
                        </>
                    )}
                    <GhostBtn onClick={refresh}>↻ Refresh</GhostBtn>
                </Controls>
            </Header>

            {loading && <Message>Loading…</Message>}
            {error && !loading && <Message style={{ color: "#ef4444" }}>{error}</Message>}

            {!loading && !error && aggregate && (
                <>
                    <SourceLegend>
                        <LegendItem>
                            <Dot $c={CHART_COLORS.posts} />
                            <span>
                                <strong>On-chain</strong> — recorded by the blockchain since genesis.
                                Accurate for <strong>any</strong> historical window: new users, contributors,
                                posts, comments.
                            </span>
                        </LegendItem>
                        <LegendItem>
                            <Dot $c={CHART_COLORS.active} />
                            <span>
                                <strong>Visitor tracking</strong> (Mirage-owned) — logged-out visitors,
                                logged-in active users, signups and campaigns.{" "}
                                {trackingSinceLabel
                                    ? <>Began <strong>{trackingSinceLabel}</strong>. Anything before that date is blank here — not zero-because-nothing-happened.</>
                                    : <>No tracked events recorded yet, so these are still empty.</>}
                            </span>
                        </LegendItem>
                    </SourceLegend>

                    <SectionHeader>On-chain — full history (retroactive)</SectionHeader>
                    <Note>Counts every signup / post / comment in the window straight from the chain. Reliable for past windows.</Note>
                    <TileGrid>
                        <Tile $accent={CHART_COLORS.newUsers}><TileValue>{formatNumber(o.new_users)}</TileValue><TileLabel>New users (signups)</TileLabel></Tile>
                        <Tile $accent={CHART_COLORS.contributors}><TileValue>{formatNumber(o.contributors)}</TileValue><TileLabel>Contributors (posted/commented)</TileLabel></Tile>
                        <Tile $accent={CHART_COLORS.posts}><TileValue>{formatNumber(o.posts)}</TileValue><TileLabel>Posts</TileLabel></Tile>
                        <Tile $accent={CHART_COLORS.comments}><TileValue>{formatNumber(o.comments)}</TileValue><TileLabel>Comments</TileLabel></Tile>
                    </TileGrid>

                    <SectionHeader>
                        Visitor tracking{trackingSinceLabel ? ` — only since ${trackingSinceLabel}` : ""}
                    </SectionHeader>
                    <Note>
                        <strong>Contributors</strong> post or comment. <strong>Active users</strong> are logged-in
                        users who read, browse, search, view profiles/topics or vote without posting/commenting.
                        <strong>Visitors</strong> are logged-out users.
                    </Note>
                    {windowEndsBeforeTracking && (
                        <Warn>This window ends before tracking began, so every number below is 0 by definition — not a real reading.</Warn>
                    )}
                    <TileGrid>
                        <Tile $accent={CHART_COLORS.active}><TileValue>{formatNumber(g.active)}</TileValue><TileLabel>Active users</TileLabel></Tile>
                        <Tile $accent={CHART_COLORS.newUsers}><TileValue>{formatNumber(g.visitors)}</TileValue><TileLabel>Visitors (logged out)</TileLabel></Tile>
                        <Tile $accent={CHART_COLORS.contributors}><TileValue>{formatNumber(g.signups)}</TileValue><TileLabel>Tracked signed-in users</TileLabel></Tile>
                        <Tile $accent="#f59e0b"><TileValue>{(g.visitors || g.signups) ? formatPercent(g.signup_conversion) : "—"}</TileValue><TileLabel>Signed-in share</TileLabel></Tile>
                    </TileGrid>

                    <SectionHeader>Trends</SectionHeader>
                    <Note>
                        <strong>D7 outcome</strong> splits each day's signups by what happened 7 days later:
                        green = still active, red = churned, grey = too recent to judge yet. The full bar height
                        is that day's new users — so the red share is your weekly drop-off.
                    </Note>
                    <ChartGrid>
                        <ChartCard>
                            <ChartTitle>Active &amp; contributors per day (stacked)</ChartTitle>
                            <ChartHeight>
                                <ResponsiveContainer width="100%" height="100%">
                                    <AreaChart data={chartSeries} margin={{ top: 5, right: 8, left: -12, bottom: 0 }}>
                                        <defs>
                                            <linearGradient id="gContrib" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="0%" stopColor={CHART_COLORS.contributors} stopOpacity={0.55} />
                                                <stop offset="100%" stopColor={CHART_COLORS.contributors} stopOpacity={0.05} />
                                            </linearGradient>
                                            <linearGradient id="gActive" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="0%" stopColor={CHART_COLORS.active} stopOpacity={0.55} />
                                                <stop offset="100%" stopColor={CHART_COLORS.active} stopOpacity={0.05} />
                                            </linearGradient>
                                        </defs>
                                        <CartesianGrid stroke={gridColor} vertical={false} />
                                        <XAxis dataKey="t" tickFormatter={shortDay} tick={{ fontSize: 11, fill: axisColor }} stroke={gridColor} minTickGap={24} />
                                        <YAxis tick={{ fontSize: 11, fill: axisColor }} stroke={gridColor} allowDecimals={false} width={36} />
                                        <Tooltip labelFormatter={shortDay} contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} />
                                        <Legend wrapperStyle={{ fontSize: 11 }} />
                                        {trackingSinceDay != null && (
                                            <ReferenceLine
                                                x={trackingSinceDay}
                                                stroke={CHART_COLORS.active}
                                                strokeDasharray="4 3"
                                                label={{ value: "tracking start", position: "insideTopRight", fontSize: 10, fill: CHART_COLORS.active }}
                                            />
                                        )}
                                        <Area type="monotone" dataKey="contributors" name="Contributors" stackId="eng" stroke={CHART_COLORS.contributors} fill="url(#gContrib)" strokeWidth={2} />
                                        <Area type="monotone" dataKey="active" name="Active" stackId="eng" stroke={CHART_COLORS.active} fill="url(#gActive)" strokeWidth={2} connectNulls={false} />
                                    </AreaChart>
                                </ResponsiveContainer>
                            </ChartHeight>
                        </ChartCard>
                        <ChartCard>
                            <ChartTitle>New signups by day — D7 outcome</ChartTitle>
                            <ChartHeight>
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={chartSeries} margin={{ top: 5, right: 8, left: -12, bottom: 0 }}>
                                        <CartesianGrid stroke={gridColor} vertical={false} />
                                        <XAxis dataKey="t" tickFormatter={shortDay} tick={{ fontSize: 11, fill: axisColor }} stroke={gridColor} minTickGap={24} />
                                        <YAxis tick={{ fontSize: 11, fill: axisColor }} stroke={gridColor} allowDecimals={false} width={36} />
                                        <Tooltip labelFormatter={shortDay} contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} cursor={{ fill: "rgba(130,132,148,0.1)" }} />
                                        <Legend wrapperStyle={{ fontSize: 11 }} />
                                        <Bar dataKey="d7_retained" name="Retained @ D7" stackId="s" fill={CHART_COLORS.retained} />
                                        <Bar dataKey="d7_churned" name="Churned by D7" stackId="s" fill={CHART_COLORS.churned} />
                                        <Bar dataKey="d7_pending" name="Too recent (<7d)" stackId="s" fill={CHART_COLORS.pending} radius={[3, 3, 0, 0]} />
                                    </BarChart>
                                </ResponsiveContainer>
                            </ChartHeight>
                        </ChartCard>
                        <ChartCard>
                            <ChartTitle>Posts &amp; comments per day</ChartTitle>
                            <ChartHeight>
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={chartSeries} margin={{ top: 5, right: 8, left: -12, bottom: 0 }}>
                                        <CartesianGrid stroke={gridColor} vertical={false} />
                                        <XAxis dataKey="t" tickFormatter={shortDay} tick={{ fontSize: 11, fill: axisColor }} stroke={gridColor} minTickGap={24} />
                                        <YAxis tick={{ fontSize: 11, fill: axisColor }} stroke={gridColor} allowDecimals={false} width={36} />
                                        <Tooltip labelFormatter={shortDay} contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} cursor={{ fill: "rgba(130,132,148,0.1)" }} />
                                        <Legend wrapperStyle={{ fontSize: 11 }} />
                                        <Bar dataKey="posts" name="Posts" stackId="a" fill={CHART_COLORS.posts} radius={[0, 0, 0, 0]} />
                                        <Bar dataKey="comments" name="Comments" stackId="a" fill={CHART_COLORS.comments} radius={[3, 3, 0, 0]} />
                                    </BarChart>
                                </ResponsiveContainer>
                            </ChartHeight>
                        </ChartCard>
                    </ChartGrid>

                    <SectionHeader>Date-range cohort &amp; retention</SectionHeader>
                    <SubNote>
                        Of the {formatNumber(r.cohort_size)} users who signed up in this window, how many were still active later:
                    </SubNote>
                    <Note>
                        <strong>Still active</strong> at horizon N (D7/D14/D30) = at or after their signup + N days they
                        either <strong>posted/commented</strong> (on-chain, retroactive) <strong>or browsed/voted</strong>
                        {" "}(tracked{trackingSinceLabel ? `, only since ${trackingSinceLabel}` : ""}). Each horizon only
                        counts users who signed up early enough that N days have already elapsed (shown as retained/eligible).
                    </Note>
                    {(windowEndsBeforeTracking || windowStartsBeforeTracking) && (
                        <Warn>
                            {windowEndsBeforeTracking
                                ? "This cohort signed up entirely before tracking began, so \"active later\" only counts people who posted or commented — returning lurkers are invisible. Treat these rates as a floor (real retention is higher)."
                                : `Part of this cohort signed up before tracking began${trackingSinceLabel ? ` (${trackingSinceLabel})` : ""}; for those users only posting/commenting counts as active, so the rates are a conservative floor.`}
                        </Warn>
                    )}
                    <ChartGrid>
                        <ChartCard>
                            <ChartTitle>Retention by horizon</ChartTitle>
                            <ChartHeight>
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={retentionData} margin={{ top: 5, right: 8, left: -12, bottom: 0 }}>
                                        <CartesianGrid stroke={gridColor} vertical={false} />
                                        <XAxis dataKey="name" tick={{ fontSize: 12, fill: axisColor }} stroke={gridColor} />
                                        <YAxis tick={{ fontSize: 11, fill: axisColor }} stroke={gridColor} unit="%" domain={[0, 100]} width={40} />
                                        <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} cursor={{ fill: "rgba(130,132,148,0.1)" }} formatter={(v) => (v == null ? "—" : `${v}%`)} />
                                        <Bar dataKey="rate" name="Retention" fill={CHART_COLORS.retention} radius={[4, 4, 0, 0]} maxBarSize={64} />
                                    </BarChart>
                                </ResponsiveContainer>
                            </ChartHeight>
                        </ChartCard>
                        <TileGrid style={{ alignContent: "start" }}>
                            {["d7", "d14", "d30"].map(k => (
                                <Tile key={k} $accent={CHART_COLORS.retention}>
                                    <TileValue>{r[k].eligible ? formatPercent(r[k].rate) : "—"}</TileValue>
                                    <TileLabel>{k.toUpperCase()} retention ({formatNumber(r[k].retained)}/{formatNumber(r[k].eligible)})</TileLabel>
                                </Tile>
                            ))}
                        </TileGrid>
                    </ChartGrid>

                    {campaigns.length > 0 && (
                        <>
                            <SectionHeader>Attribution (first-touch campaigns)</SectionHeader>
                            <Card style={{ padding: "0.4rem 0.6rem" }}>
                                <Table>
                                    <thead>
                                        <tr>
                                            <Th>Source</Th><Th>Campaign</Th>
                                            <Th $right>Visitors</Th><Th $right>Signups</Th>
                                            <Th $right>Signup conv.</Th>
                                            <Th $right>Contributors</Th><Th $right>Contrib. conv.</Th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {campaigns.map((cp, i) => (
                                            <Tr key={i}>
                                                <Td>{cp.source || "—"}</Td>
                                                <Td>{cp.campaign || "—"}</Td>
                                                <Td $right>{formatNumber(cp.visitors)}</Td>
                                                <Td $right>{formatNumber(cp.signups)}</Td>
                                                <Td $right>{formatPercent(cp.signupConversion)}</Td>
                                                <Td $right>{formatNumber(cp.contributors)}</Td>
                                                <Td $right>{formatPercent(cp.contributorConversion)}</Td>
                                            </Tr>
                                        ))}
                                    </tbody>
                                </Table>
                            </Card>
                        </>
                    )}

                    <SectionHeader>Servers ({servers.length})</SectionHeader>
                    <Card style={{ padding: "0.4rem 0.6rem" }}>
                        <Table>
                            <thead>
                                <tr>
                                    <Th>Server</Th><Th>Status</Th>
                                    <Th $right>Logged-out visitors</Th><Th $right>Active users</Th>
                                    <Th $right>New users</Th><Th $right>Contributors</Th><Th $right>D7</Th>
                                </tr>
                            </thead>
                            <tbody>
                                {servers.map((s, i) => {
                                    const ok = s.status === "ok";
                                    const st = s.stats || {};
                                    const sg = st.growth || {};
                                    const so = st.onchain || {};
                                    const sr = (st.retention && st.retention.d7) || {};
                                    return (
                                        <Tr key={i}>
                                            <Td>{s.server}</Td>
                                            <Td><StatusPill $ok={ok}>{s.status}</StatusPill></Td>
                                            <Td $right>{ok ? formatNumber(sg.visitors) : "—"}</Td>
                                            <Td $right>{ok ? formatNumber(sg.active) : "—"}</Td>
                                            <Td $right>{ok ? formatNumber(so.new_users) : "—"}</Td>
                                            <Td $right>{ok ? formatNumber(so.contributors) : "—"}</Td>
                                            <Td $right>{ok && sr.eligible ? formatPercent(sr.rate) : "—"}</Td>
                                        </Tr>
                                    );
                                })}
                            </tbody>
                        </Table>
                    </Card>
                </>
            )
            }
        </Page >
    );
}
