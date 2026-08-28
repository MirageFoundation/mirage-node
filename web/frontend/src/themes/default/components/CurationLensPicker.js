import { useEffect, useMemo, useState } from 'react';
import styled from 'styled-components';
import { Link } from 'react-router-dom';
import { useCommunityDetail } from '../../../logic/useCommunityDetail';
import { useCurationTeams } from '../../../logic/useCurationTeams';
import { useCurationPreference } from '../../../logic/useCurationPreference';
import { CURATION_MODE, LENS } from '../../../utils/curation';
import { requireThemeColor } from '../../../utils/themeColor';

const Wrap = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex-wrap: wrap;
`;

const Select = styled.select`
    min-width: 10rem;
    padding: 0.35rem 0.5rem;
    border-radius: 7px;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')};
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    font: inherit;
    font-size: 0.68rem;
`;

const State = styled.span`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.62rem;
`;

const ManageLink = styled(Link)`
    color: ${({ theme }) => requireThemeColor(theme, 'link')};
    font-size: 0.62rem;
    text-decoration: none;
    &:hover { text-decoration: underline; }
`;

function initialSelection(detail) {
    if (!detail) return LENS.DEFAULT;
    if (Number(detail.stored_mode) === CURATION_MODE.RAW) return LENS.RAW;
    if (Number(detail.effective_mode) === CURATION_MODE.PINNED && Number(detail.effective_team_id) > 0) {
        return `${LENS.TEAM}:${Number(detail.effective_team_id)}`;
    }
    return LENS.DEFAULT;
}

export default function CurationLensPicker({ community, viewer, onChange }) {
    const [optimisticSelection, setOptimisticSelection] = useState(null);
    const { detail, loading: detailLoading } = useCommunityDetail(community, viewer);
    const { teams, loading: teamsLoading } = useCurationTeams(community, { viewer });
    const { selectLens, pending, pendingStatus, error } = useCurationPreference(community, detail);
    const liveTeams = useMemo(() => teams.filter((team) => !team.deleted), [teams]);
    const authoritativeSelection = initialSelection(detail);
    const selected = optimisticSelection || authoritativeSelection;

    useEffect(() => {
        setOptimisticSelection(null);
    }, [community]);

    useEffect(() => {
        if (optimisticSelection && optimisticSelection === authoritativeSelection) {
            setOptimisticSelection(null);
        }
    }, [authoritativeSelection, optimisticSelection]);

    useEffect(() => {
        if (detailLoading || teamsLoading) return;
        const [lens, rawTeamId] = selected.split(':');
        onChange?.(lens, rawTeamId ? Number(rawTeamId) : null);
    }, [detailLoading, onChange, selected, teamsLoading]);

    const change = async (event) => {
        const selection = event.target.value;
        const [lens, rawTeamId] = selection.split(':');
        const teamId = rawTeamId ? Number(rawTeamId) : null;
        try {
            await selectLens(lens, teamId);
            setOptimisticSelection(selection);
        } catch (err) {
            console.error('[lens] selection failed', { community, lens, teamId, error: String(err?.message || err) });
        }
    };

    return <Wrap aria-label="Community lens">
        <Select value={selected} onChange={change} disabled={pending || detailLoading || teamsLoading}>
            <option value={LENS.DEFAULT}>Node default</option>
            {liveTeams.map((team) => (
                <option key={team.team_id} value={`${LENS.TEAM}:${team.team_id}`}>
                    {team.name} · {team.subscriber_count} subscribers
                </option>
            ))}
            <option value={LENS.RAW}>Uncensored</option>
        </Select>
        <State>{pendingStatus || error || (detail?.curated ? `${detail.live_team_count} live teams` : 'Uncurated')}</State>
        <ManageLink to={`/c/${encodeURIComponent(community)}/teams`}>Curator teams</ManageLink>
    </Wrap>;
}
