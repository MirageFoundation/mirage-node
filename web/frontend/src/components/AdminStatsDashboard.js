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

const Page = styled.div`
    width: 100%;
    max-width: 1100px;
    margin: 0 auto;
    padding: 1rem 1.25rem 3rem;
    color: ${({ theme }) => tok(theme, "text", "#e6e6e6")};
`;

const Title = styled.h1`
    font-size: 1.2rem;
    font-weight: 700;
    margin: 0 0 0.25rem;
`;

const Subtitle = styled.div`
    font-size: 0.8rem;
    opacity: 0.65;
    margin-bottom: 1rem;
`;

const Controls = styled.div`
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 1.25rem;
`;

// Fixed brand blue so the active state always has white-on-blue contrast,
// independent of whatever the theme's accent token resolves to.
const ACCENT = "#2563eb";

const PresetBtn = styled.button`
    border: 1px solid ${({ $active, theme }) => ($active ? ACCENT : tok(theme, "border", "#3a3a3a"))};
    background: ${({ $active }) => ($active ? ACCENT : "transparent")};
    color: ${({ $active, theme }) => ($active ? "#fff" : tok(theme, "text", "#e6e6e6"))};
    border-radius: 6px;
    padding: 0.35rem 0.75rem;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.12s ease, border-color 0.12s ease;
    &:hover {
        border-color: ${ACCENT};
        background: ${({ $active }) => ($active ? ACCENT : "rgba(37,99,235,0.12)")};
    }
`;

const DateInput = styled.input`
    border: 1px solid ${({ theme }) => tok(theme, "border", "#333")};
    background: transparent;
    color: ${({ theme }) => tok(theme, "text", "#e6e6e6")};
    border-radius: 6px;
    padding: 0.3rem 0.5rem;
    font-size: 0.78rem;
`;

const SectionHeader = styled.div`
    text-transform: uppercase;
    font-size: 0.62rem;
    letter-spacing: 0.06em;
    font-weight: 700;
    opacity: 0.6;
    margin: 1.5rem 0 0.6rem;
`;

const TileGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 0.6rem;
`;

const Tile = styled.div`
    border: 1px solid ${({ theme }) => tok(theme, "border", "#333")};
    border-radius: 8px;
    padding: 0.7rem 0.8rem;
`;

const TileValue = styled.div`
    font-size: 1.35rem;
    font-weight: 700;
`;

const TileLabel = styled.div`
    font-size: 0.7rem;
    opacity: 0.65;
    margin-top: 0.15rem;
`;

const Table = styled.table`
    width: 100%;
    border-collapse: collapse;
    font-size: 0.78rem;
`;

const Th = styled.th`
    text-align: ${({ $right }) => ($right ? "right" : "left")};
    padding: 0.4rem 0.5rem;
    border-bottom: 1px solid ${({ theme }) => tok(theme, "border", "#333")};
    opacity: 0.7;
    font-weight: 600;
`;

const Td = styled.td`
    text-align: ${({ $right }) => ($right ? "right" : "left")};
    padding: 0.4rem 0.5rem;
    border-bottom: 1px solid ${({ theme }) => tok(theme, "border", "#222")};
`;

const StatusPill = styled.span`
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    padding: 0.1rem 0.4rem;
    border-radius: 4px;
    background: ${({ $ok, theme }) => ($ok ? "rgba(34,197,94,0.18)" : "rgba(239,68,68,0.18)")};
    color: ${({ $ok }) => ($ok ? "#22c55e" : "#ef4444")};
`;

const Message = styled.div`
    padding: 2rem 1rem;
    text-align: center;
    opacity: 0.7;
    font-size: 0.85rem;
`;

const SourceLegend = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    border: 1px solid ${({ theme }) => tok(theme, "border", "#333")};
    border-radius: 8px;
    padding: 0.7rem 0.85rem;
    margin-bottom: 1.25rem;
    font-size: 0.74rem;
    line-height: 1.45;
`;

const LegendItem = styled.div`
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
`;

const Dot = styled.span`
    flex: 0 0 auto;
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    background: ${({ $c }) => $c};
    transform: translateY(1px);
`;

// Inline caveat under a section, used to spell out exactly what a metric does
// and does not cover (esp. on-chain-retroactive vs tracked-since-a-date).
const Note = styled.div`
    font-size: 0.72rem;
    line-height: 1.45;
    opacity: 0.7;
    margin: 0 0 0.7rem;
    max-width: 720px;
`;

const Warn = styled(Note)`
    opacity: 1;
    color: ${({ theme }) => tok(theme, "text", "#e6e6e6")};
    border-left: 3px solid #f59e0b;
    padding-left: 0.6rem;
`;

const ChartGrid = styled.div`
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 0.8rem;
`;

const ChartCard = styled.div`
    border: 1px solid ${({ theme }) => tok(theme, "border", "#333")};
    border-radius: 10px;
    padding: 0.9rem 0.9rem 0.6rem;
`;

const ChartTitle = styled.div`
    font-size: 0.8rem;
    font-weight: 700;
    margin-bottom: 0.6rem;
`;

const ChartHeight = styled.div`
    width: 100%;
    height: 220px;
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
    // metrics are empty and the browsing half of retention can't be seen.
    const windowEndsBeforeTracking = !!(trackingSince && win && win.end < trackingSince);
    const windowStartsBeforeTracking = !!(trackingSince && win && win.start < trackingSince);
    // Day bucket tracking began. Tracked lines (Active) are nulled before this so
    // the chart shows a gap, not a misleading flat zero, prior to tracking.
    const trackingSinceDay = trackingSince ? Math.floor(trackingSince / 86400) * 86400 : null;
    // Drop the current (still-building) UTC day so charts end at the last complete day.
    const todayDay = Math.floor(Date.now() / 1000 / 86400) * 86400;
    const chartSeries = series
        .filter(pt => pt.t < todayDay)
        .map(pt => (trackingSinceDay == null
            ? pt
            : { ...pt, active: pt.t < trackingSinceDay ? null : pt.active }));
    const retentionData = r ? ["d7", "d14", "d30"].map(k => ({
        name: k.toUpperCase(),
        rate: r[k].eligible ? Math.round(r[k].rate * 1000) / 10 : null,
        label: `${r[k].retained}/${r[k].eligible}`,
    })) : [];
    const axisColor = tok(theme, "text", "#e6e6e6");
    const gridColor = "rgba(127,127,127,0.18)";

    return (
        <Page>
            <Helmet><title>Stats | Mirage</title></Helmet>
            <Title>Growth Stats</Title>
            <Subtitle>
                Fleet-wide, admin-only. {aggregate ? `${aggregate.servers_counted} server(s) reporting` : ""}
                {win ? ` · ${formatDate(win.start)} – ${formatDate(win.end)}` : ""}
            </Subtitle>

            <Controls>
                {PRESETS.map(p => (
                    <PresetBtn key={p.id} $active={preset === p.id} onClick={() => setPreset(p.id)}>
                        {p.label}
                    </PresetBtn>
                ))}
                <PresetBtn $active={preset === "custom"} onClick={() => setPreset("custom")}>Custom</PresetBtn>
                {preset === "custom" && (
                    <>
                        <DateInput type="date" value={customStart} onChange={e => setCustomStart(e.target.value)} />
                        <span style={{ opacity: 0.5 }}>–</span>
                        <DateInput type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)} />
                    </>
                )}
                <PresetBtn onClick={refresh}>Refresh</PresetBtn>
            </Controls>

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
                                <strong>Visitor tracking</strong> (Mirage-owned) — visitors, active browsing,
                                signups and campaigns.{" "}
                                {trackingSinceLabel
                                    ? <>Began <strong>{trackingSinceLabel}</strong>. Anything before that date is blank here — not zero-because-nothing-happened.</>
                                    : <>No tracked events recorded yet, so these are still empty.</>}
                            </span>
                        </LegendItem>
                    </SourceLegend>

                    <SectionHeader>On-chain — full history (retroactive)</SectionHeader>
                    <Note>Counts every signup / post / comment in the window straight from the chain. Reliable for past windows.</Note>
                    <TileGrid>
                        <Tile><TileValue>{formatNumber(o.new_users)}</TileValue><TileLabel>New users (signups)</TileLabel></Tile>
                        <Tile><TileValue>{formatNumber(o.contributors)}</TileValue><TileLabel>Contributors (posted/commented)</TileLabel></Tile>
                        <Tile><TileValue>{formatNumber(o.posts)}</TileValue><TileLabel>Posts</TileLabel></Tile>
                        <Tile><TileValue>{formatNumber(o.comments)}</TileValue><TileLabel>Comments</TileLabel></Tile>
                    </TileGrid>

                    <SectionHeader>
                        Visitor tracking{trackingSinceLabel ? ` — only since ${trackingSinceLabel}` : ""}
                    </SectionHeader>
                    <Note>
                        <strong>Active</strong> = made ≥1 content request (posts, comments, profiles, topics or search)
                        in the window — i.e. actually browsing, logged in or a logged-out lurker. Votes, config polls
                        and bare page loads don't count.
                    </Note>
                    {windowEndsBeforeTracking && (
                        <Warn>This window ends before tracking began, so every number below is 0 by definition — not a real reading.</Warn>
                    )}
                    <TileGrid>
                        <Tile><TileValue>{formatNumber(g.active)}</TileValue><TileLabel>Active (browsing, incl. lurkers)</TileLabel></Tile>
                        <Tile><TileValue>{formatNumber(g.visitors)}</TileValue><TileLabel>Visitors</TileLabel></Tile>
                        <Tile><TileValue>{formatNumber(g.signups)}</TileValue><TileLabel>Signups (visitor → account)</TileLabel></Tile>
                        <Tile><TileValue>{g.visitors ? formatPercent(g.signup_conversion) : "—"}</TileValue><TileLabel>Signup conversion</TileLabel></Tile>
                    </TileGrid>

                    <SectionHeader>Trends</SectionHeader>
                    <ChartGrid>
                        <ChartCard>
                            <ChartTitle>New users, contributors & active per day</ChartTitle>
                            <ChartHeight>
                                <ResponsiveContainer width="100%" height="100%">
                                    <AreaChart data={chartSeries} margin={{ top: 5, right: 8, left: -12, bottom: 0 }}>
                                        <defs>
                                            <linearGradient id="gNew" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="0%" stopColor={CHART_COLORS.newUsers} stopOpacity={0.35} />
                                                <stop offset="100%" stopColor={CHART_COLORS.newUsers} stopOpacity={0} />
                                            </linearGradient>
                                            <linearGradient id="gContrib" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="0%" stopColor={CHART_COLORS.contributors} stopOpacity={0.3} />
                                                <stop offset="100%" stopColor={CHART_COLORS.contributors} stopOpacity={0} />
                                            </linearGradient>
                                            <linearGradient id="gActive" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="0%" stopColor={CHART_COLORS.active} stopOpacity={0.35} />
                                                <stop offset="100%" stopColor={CHART_COLORS.active} stopOpacity={0} />
                                            </linearGradient>
                                        </defs>
                                        <CartesianGrid stroke={gridColor} vertical={false} />
                                        <XAxis dataKey="t" tickFormatter={shortDay} tick={{ fontSize: 11, fill: axisColor }} stroke={gridColor} minTickGap={24} />
                                        <YAxis tick={{ fontSize: 11, fill: axisColor }} stroke={gridColor} allowDecimals={false} width={36} />
                                        <Tooltip labelFormatter={shortDay} contentStyle={{ fontSize: 12 }} />
                                        <Legend wrapperStyle={{ fontSize: 11 }} />
                                        {trackingSinceDay != null && (
                                            <ReferenceLine
                                                x={trackingSinceDay}
                                                stroke={CHART_COLORS.active}
                                                strokeDasharray="4 3"
                                                label={{ value: "tracking start", position: "insideTopRight", fontSize: 10, fill: CHART_COLORS.active }}
                                            />
                                        )}
                                        <Area type="monotone" dataKey="new_users" name="New users" stroke={CHART_COLORS.newUsers} fill="url(#gNew)" strokeWidth={2} />
                                        <Area type="monotone" dataKey="contributors" name="Contributors" stroke={CHART_COLORS.contributors} fill="url(#gContrib)" strokeWidth={2} />
                                        <Area type="monotone" dataKey="active" name="Active" stroke={CHART_COLORS.active} fill="url(#gActive)" strokeWidth={2} connectNulls={false} />
                                    </AreaChart>
                                </ResponsiveContainer>
                            </ChartHeight>
                        </ChartCard>
                        <ChartCard>
                            <ChartTitle>Posts & comments per day</ChartTitle>
                            <ChartHeight>
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={chartSeries} margin={{ top: 5, right: 8, left: -12, bottom: 0 }}>
                                        <CartesianGrid stroke={gridColor} vertical={false} />
                                        <XAxis dataKey="t" tickFormatter={shortDay} tick={{ fontSize: 11, fill: axisColor }} stroke={gridColor} minTickGap={24} />
                                        <YAxis tick={{ fontSize: 11, fill: axisColor }} stroke={gridColor} allowDecimals={false} width={36} />
                                        <Tooltip labelFormatter={shortDay} contentStyle={{ fontSize: 12 }} />
                                        <Legend wrapperStyle={{ fontSize: 11 }} />
                                        <Bar dataKey="posts" name="Posts" stackId="a" fill={CHART_COLORS.posts} radius={[0, 0, 0, 0]} />
                                        <Bar dataKey="comments" name="Comments" stackId="a" fill={CHART_COLORS.comments} radius={[2, 2, 0, 0]} />
                                    </BarChart>
                                </ResponsiveContainer>
                            </ChartHeight>
                        </ChartCard>
                    </ChartGrid>

                    <SectionHeader>Date-range cohort &amp; retention</SectionHeader>
                    <Subtitle style={{ margin: "0 0 0.4rem" }}>
                        Of the {formatNumber(r.cohort_size)} users who signed up in this window, how many were still active later:
                    </Subtitle>
                    <Note>
                        <strong>Still active</strong> at horizon N (D7/D14/D30) = at or after their signup + N days they
                        either <strong>posted/commented</strong> (on-chain, retroactive) <strong>or browsed</strong>
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
                                        <Tooltip contentStyle={{ fontSize: 12 }} formatter={(v) => (v == null ? "—" : `${v}%`)} />
                                        <Bar dataKey="rate" name="Retention" fill={CHART_COLORS.retention} radius={[3, 3, 0, 0]} />
                                    </BarChart>
                                </ResponsiveContainer>
                            </ChartHeight>
                        </ChartCard>
                        <TileGrid style={{ alignContent: "start" }}>
                            {["d7", "d14", "d30"].map(k => (
                                <Tile key={k}>
                                    <TileValue>{r[k].eligible ? formatPercent(r[k].rate) : "—"}</TileValue>
                                    <TileLabel>{k.toUpperCase()} retention ({formatNumber(r[k].retained)}/{formatNumber(r[k].eligible)})</TileLabel>
                                </Tile>
                            ))}
                        </TileGrid>
                    </ChartGrid>

                    {campaigns.length > 0 && (
                        <>
                            <SectionHeader>Attribution (first-touch campaigns)</SectionHeader>
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
                                        <tr key={i}>
                                            <Td>{cp.source || "—"}</Td>
                                            <Td>{cp.campaign || "—"}</Td>
                                            <Td $right>{formatNumber(cp.visitors)}</Td>
                                            <Td $right>{formatNumber(cp.signups)}</Td>
                                            <Td $right>{formatPercent(cp.signupConversion)}</Td>
                                            <Td $right>{formatNumber(cp.contributors)}</Td>
                                            <Td $right>{formatPercent(cp.contributorConversion)}</Td>
                                        </tr>
                                    ))}
                                </tbody>
                            </Table>
                        </>
                    )}

                    <SectionHeader>Servers ({servers.length})</SectionHeader>
                    <Table>
                        <thead>
                            <tr>
                                <Th>Server</Th><Th>Status</Th>
                                <Th $right>Visitors</Th><Th $right>Active</Th>
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
                                    <tr key={i}>
                                        <Td>{s.server}</Td>
                                        <Td><StatusPill $ok={ok}>{s.status}</StatusPill></Td>
                                        <Td $right>{ok ? formatNumber(sg.visitors) : "—"}</Td>
                                        <Td $right>{ok ? formatNumber(sg.active) : "—"}</Td>
                                        <Td $right>{ok ? formatNumber(so.new_users) : "—"}</Td>
                                        <Td $right>{ok ? formatNumber(so.contributors) : "—"}</Td>
                                        <Td $right>{ok && sr.eligible ? formatPercent(sr.rate) : "—"}</Td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </Table>
                </>
            )}
        </Page>
    );
}
