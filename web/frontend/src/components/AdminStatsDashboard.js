import React, { useMemo } from "react";
import { Helmet } from "react-helmet-async";
import styled, { useTheme } from "styled-components";
import { useStats } from "../logic/useStats";
import Storage from "../utils/Storage";

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

const PresetBtn = styled.button`
    border: 1px solid ${({ theme }) => tok(theme, "border", "#333")};
    background: ${({ $active, theme }) => ($active ? tok(theme, "accent", tok(theme, "voteUp", "#3b82f6")) : "transparent")};
    color: ${({ $active, theme }) => ($active ? "#fff" : tok(theme, "text", "#e6e6e6"))};
    border-radius: 6px;
    padding: 0.35rem 0.7rem;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
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
    const c = aggregate && aggregate.contributors;
    const r = aggregate && aggregate.retention;

    return (
        <Page>
            <Helmet><title>Stats | Mirage</title></Helmet>
            <Title>Growth & Fundraising Stats</Title>
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
                    <SectionHeader>Growth</SectionHeader>
                    <TileGrid>
                        <Tile><TileValue>{formatNumber(g.active)}</TileValue><TileLabel>Active in window (engaged, incl. lurkers)</TileLabel></Tile>
                        <Tile><TileValue>{formatNumber(g.visitors)}</TileValue><TileLabel>Visitors</TileLabel></Tile>
                        <Tile><TileValue>{formatNumber(g.new_users)}</TileValue><TileLabel>New users</TileLabel></Tile>
                        <Tile><TileValue>{formatPercent(g.signup_conversion)}</TileValue><TileLabel>Signup conversion</TileLabel></Tile>
                    </TileGrid>

                    <SectionHeader>Contributors</SectionHeader>
                    <TileGrid>
                        <Tile><TileValue>{formatNumber(c.contributors)}</TileValue><TileLabel>Contributors (post/comment)</TileLabel></Tile>
                        <Tile><TileValue>{formatNumber(c.posts)}</TileValue><TileLabel>Posts</TileLabel></Tile>
                        <Tile><TileValue>{formatNumber(c.comments)}</TileValue><TileLabel>Comments</TileLabel></Tile>
                        <Tile><TileValue>{formatNumber(c.posts_per_contributor, 2)}</TileValue><TileLabel>Posts / contributor</TileLabel></Tile>
                    </TileGrid>

                    <SectionHeader>Date-range cohort &amp; retention</SectionHeader>
                    <Subtitle style={{ margin: "0 0 0.6rem" }}>
                        Of the {formatNumber(r.cohort_size)} users who signed up in this window, how many were still active later:
                    </Subtitle>
                    <TileGrid>
                        {["d7", "d14", "d30"].map(k => (
                            <Tile key={k}>
                                <TileValue>{formatPercent(r[k].rate)}</TileValue>
                                <TileLabel>{k.toUpperCase()} retention ({formatNumber(r[k].retained)}/{formatNumber(r[k].eligible)})</TileLabel>
                            </Tile>
                        ))}
                    </TileGrid>

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

                    <SectionHeader>Servers</SectionHeader>
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
                                const sc = st.contributors || {};
                                const sr = (st.retention && st.retention.d7) || {};
                                return (
                                    <tr key={i}>
                                        <Td>{s.server}</Td>
                                        <Td><StatusPill $ok={ok}>{s.status}</StatusPill></Td>
                                        <Td $right>{ok ? formatNumber(sg.visitors) : "—"}</Td>
                                        <Td $right>{ok ? formatNumber(sg.active) : "—"}</Td>
                                        <Td $right>{ok ? formatNumber(sg.new_users) : "—"}</Td>
                                        <Td $right>{ok ? formatNumber(sc.contributors) : "—"}</Td>
                                        <Td $right>{ok ? formatPercent(sr.rate) : "—"}</Td>
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
