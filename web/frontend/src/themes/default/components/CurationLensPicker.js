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
    gap: 0.45rem;
    min-width: 0;
    flex: 1 1 auto;
`;

const Select = styled.select`
    height: 28px;
    max-width: 14rem;
    min-width: 7.5rem;
    padding: 0 1.6rem 0 0.55rem;
    border-radius: 6px;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background-color: transparent;
    background-image: linear-gradient(45deg, transparent 50%, currentColor 50%),
        linear-gradient(135deg, currentColor 50%, transparent 50%);
    background-position: calc(100% - 12px) calc(50% - 2px), calc(100% - 7px) calc(50% - 2px);
    background-size: 5px 5px, 5px 5px;
    background-repeat: no-repeat;
    color: ${({ theme }) => requireThemeColor(theme, 'feedCtrlText')};
    font: inherit;
    font-size: 0.68rem;
    font-weight: 500;
    line-height: 1;
    cursor: pointer;
    appearance: none;

    &:hover:not(:disabled) {
        background-color: ${({ theme }) => requireThemeColor(theme, 'feedCtrlHoverBg')};
    }

    &:disabled {
        opacity: 0.55;
        cursor: wait;
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        outline-offset: 2px;
    }
`;

const Meta = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    min-width: 0;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.65rem;
    white-space: nowrap;
`;

const Status = styled.span`
    display: inline-flex;
    align-items: center;
    height: 22px;
    padding: 0 0.45rem;
    border-radius: 999px;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(0, 0, 0, 0.03)'
        : 'rgba(255, 255, 255, 0.04)'};
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.62rem;
    font-weight: 500;
`;

const ManageLink = styled(Link)`
    color: ${({ theme }) => requireThemeColor(theme, 'link')};
    font-size: 0.65rem;
    font-weight: 500;
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
    const viewerAddr = viewer && viewer !== 'guest' ? String(viewer).toLowerCase() : '';
    const { detail, loading: detailLoading } = useCommunityDetail(community, viewerAddr);
    const { teams, loading: teamsLoading } = useCurationTeams(community, { viewer: viewerAddr });
    // Side effect only: toast when a stored pinned team is gone. Lens changes are local.
    useCurationPreference(community, detail);
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

    const change = (event) => {
        const selection = event.target.value;
        const [lens, rawTeamId] = selection.split(':');
        const teamId = rawTeamId ? Number(rawTeamId) : null;
        console.debug('[lens] view selection (local only)', { community, lens, teamId });
        setOptimisticSelection(selection);
    };

    const teamsPath = `/c/${encodeURIComponent(community)}/teams`;
    const statusText = detail?.curated ? `${detail.live_team_count} live teams` : 'Uncurated';

    return (
        <Wrap aria-label="Community lens">
            <Select
                value={selected}
                onChange={change}
                disabled={detailLoading || teamsLoading}
                aria-label="Curation lens"
            >
                <option value={LENS.DEFAULT}>Node default</option>
                {liveTeams.map((team) => (
                    <option key={team.team_id} value={`${LENS.TEAM}:${team.team_id}`}>
                        {team.name} · {team.subscriber_count} subscribers
                    </option>
                ))}
                <option value={LENS.RAW}>Uncensored</option>
            </Select>
            <Meta>
                <Status>{statusText}</Status>
                <ManageLink to={teamsPath}>Curator teams</ManageLink>
            </Meta>
        </Wrap>
    );
}
