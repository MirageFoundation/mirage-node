import { useEffect, useMemo, useState } from 'react';
import styled from 'styled-components';
import { Link } from 'react-router-dom';
import { useCommunityDetail } from '../../../logic/useCommunityDetail';
import { useCurationTeams } from '../../../logic/useCurationTeams';
import { useCurationPreference } from '../../../logic/useCurationPreference';
import { useViewerCuratorMembership } from '../../../logic/useViewerCuratorMembership';
import {
    CURATION_MODE,
    LENS,
    formatSubscriberCount,
} from '../../../utils/curation';
import { requireThemeColor } from '../../../utils/themeColor';

const Wrap = styled.div`
    display: flex;
    align-items: center;
    gap: 0.55rem;
    min-width: 0;
    width: 100%;
    flex-wrap: wrap;
`;

const Label = styled.span`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    line-height: 1;
    text-transform: uppercase;
    white-space: nowrap;
`;

const Select = styled.select`
    height: 30px;
    max-width: 18rem;
    min-width: 7.5rem;
    padding: 0 1.75rem 0 0.65rem;
    border-radius: 999px;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background-color: ${({ theme }) => requireThemeColor(theme, 'panel')};
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

const FixedLens = styled.span`
    display: inline-flex;
    align-items: center;
    height: 30px;
    padding: 0 0.7rem;
    border-radius: 999px;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'panel')};
    color: ${({ theme }) => requireThemeColor(theme, 'feedCtrlText')};
    font-size: 0.7rem;
    font-weight: 600;
    line-height: 1;
    white-space: nowrap;
`;

const Meta = styled.span`
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    min-width: 0;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.65rem;
    white-space: nowrap;
`;

const Status = styled.span`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.62rem;
    font-weight: 500;
`;

const ManageLink = styled(Link)`
    display: inline-flex;
    align-items: center;
    height: 30px;
    padding: 0 0.65rem;
    border-radius: 999px;
    color: ${({ theme }) => requireThemeColor(theme, 'link')};
    font-size: 0.68rem;
    font-weight: 600;
    text-decoration: none;
    white-space: nowrap;

    &:hover {
        background: ${({ theme }) => requireThemeColor(theme, 'feedCtrlHoverBg')};
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        outline-offset: 2px;
    }
`;

function pickAuthoritativeSelection(detail) {
    if (!detail) return LENS.DEFAULT;
    if (!detail.curated) return LENS.RAW;
    if (Number(detail.stored_mode) === CURATION_MODE.RAW) return LENS.RAW;
    if (Number(detail.stored_mode) === CURATION_MODE.PINNED
        && Number(detail.effective_mode) === CURATION_MODE.PINNED
        && Number(detail.effective_team_id) > 0) {
        return `${LENS.TEAM}:${Number(detail.effective_team_id)}`;
    }
    return LENS.DEFAULT;
}

function sortTeamsBySubscribers(teams) {
    return [...teams].sort((a, b) => {
        const countDiff = Number(b.subscriber_count) - Number(a.subscriber_count);
        if (countDiff !== 0) return countDiff;
        return Number(a.team_id) - Number(b.team_id);
    });
}

export default function CurationLensPicker({ community, viewer, onChange }) {
    const [optimisticSelection, setOptimisticSelection] = useState(null);
    const viewerAddr = viewer && viewer !== 'guest' ? String(viewer).toLowerCase() : '';
    const { detail, loading: detailLoading } = useCommunityDetail(community, viewerAddr);
    const { teams, loading: teamsLoading } = useCurationTeams(community, { viewer: viewerAddr });
    const { isCurator, teamId: curatorTeamId } = useViewerCuratorMembership(community);
    const { selectLens, pending, pendingStatus, error } = useCurationPreference(community, detail);
    const liveTeams = useMemo(() => teams.filter((team) => !team.deleted), [teams]);
    const rankedTeams = useMemo(() => sortTeamsBySubscribers(liveTeams), [liveTeams]);
    const curated = Boolean(detail?.curated);
    const authoritativeSelection = pickAuthoritativeSelection(detail);
    const joined = Boolean(viewerAddr && detail?.viewer_joined);
    // Uncurated communities have only one meaningful lens.
    const selected = (!detailLoading && detail && !curated)
        ? LENS.RAW
        : (optimisticSelection || authoritativeSelection);

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
        console.debug('[lens] applying feed lens', { community, lens, teamId: rawTeamId || null, curated });
        onChange?.(lens, rawTeamId ? Number(rawTeamId) : null);
    }, [community, curated, detailLoading, onChange, selected, teamsLoading]);

    const change = (event) => {
        const selection = event.target.value;
        const [lens, rawTeamId] = selection.split(':');
        const teamId = rawTeamId ? Number(rawTeamId) : null;
        setOptimisticSelection(selection);
        if (!joined) {
            console.debug('[lens] view selection (local preview)', { community, lens, teamId });
            return;
        }
        console.debug('[lens] persist selection', { community, lens, teamId });
        selectLens(lens, teamId).catch((err) => {
            console.error('[lens] selection failed', { community, lens, teamId, error: String(err?.message || err) });
            setOptimisticSelection(null);
        });
    };

    const teamsPath = `/c/${encodeURIComponent(community)}/teams`;
    const managePath = isCurator && curatorTeamId
        ? `${teamsPath}/${curatorTeamId}`
        : teamsPath;
    const manageLabel = isCurator ? 'Open Curation' : 'Curator teams →';
    const loading = detailLoading || teamsLoading;
    // Wait for detail before collapsing to Uncensored — curated communities
    // would otherwise flash the fixed label while the request is in flight.
    const uncensoredOnly = Boolean(detail) && !detailLoading && !curated;
    const defaultTeamName = String(detail?.default_team?.name || '').trim();
    const defaultLabel = defaultTeamName ? `Default (${defaultTeamName})` : 'Default';

    return (
        <Wrap aria-label="Community lens">
            <Label>Feed lens</Label>
            {uncensoredOnly ? (
                <FixedLens aria-label="Curation lens">Uncensored</FixedLens>
            ) : (
                <Select
                    value={selected}
                    onChange={change}
                    disabled={pending || loading}
                    aria-label="Curation lens"
                >
                    <option value={LENS.DEFAULT}>{defaultLabel}</option>
                    <option value={LENS.RAW}>Uncensored</option>
                    {rankedTeams.length > 0 && (
                        <option disabled value="__sep__">────────</option>
                    )}
                    {rankedTeams.map((team) => (
                        <option key={team.team_id} value={`${LENS.TEAM}:${team.team_id}`}>
                            {team.name} ({formatSubscriberCount(Number(team.subscriber_count))})
                        </option>
                    ))}
                </Select>
            )}
            <Meta>
                {(pendingStatus || error) && <Status>{pendingStatus || error}</Status>}
                <ManageLink to={managePath}>{manageLabel}</ManageLink>
            </Meta>
        </Wrap>
    );
}
