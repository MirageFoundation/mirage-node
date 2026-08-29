import { useEffect, useMemo, useRef, useState } from 'react';
import styled from 'styled-components';
import { useNavigate } from 'react-router-dom';
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
import FeedControlButton from './FeedControlButton';

const Wrap = styled.div`
    display: flex;
    align-items: center;
    gap: 0.35rem;
    min-width: 0;
    flex: 0 1 auto;
`;

const PickerRoot = styled.div`
    position: relative;
    min-width: 0;
`;

const PickerButton = styled(FeedControlButton)`
    box-sizing: border-box;
    height: var(--community-header-control-height, 28px);
    justify-content: space-between;
    gap: 0.35rem;
    /* No cap: team names are capped at 30 chars on chain, so the selected team
       shows in full instead of being cut to an ellipsis. */
    max-width: 100%;
    font-size: var(--community-header-control-font-size, 0.68rem);
`;

const PickerLabel = styled.span`
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const Chevron = styled.span`
    width: 6px;
    height: 6px;
    flex: 0 0 auto;
    border-right: 1.5px solid currentColor;
    border-bottom: 1.5px solid currentColor;
    transform: ${({ $open }) => ($open ? 'rotate(225deg)' : 'rotate(45deg)')};
    transition: transform 0.15s ease;
`;

const Menu = styled.div`
    position: absolute;
    z-index: 100;
    top: calc(100% + 0.35rem);
    left: 0;
    box-sizing: border-box;
    width: max-content;
    min-width: 13rem;
    max-width: min(20rem, calc(100vw - 2rem));
    padding: 0.3rem;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 10px;
    background: ${({ theme }) => requireThemeColor(theme, 'panel')};
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.18);
`;

const Option = styled.button`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    width: 100%;
    padding: 0.5rem 0.6rem;
    border: 0;
    border-radius: 7px;
    background: ${({ $selected, theme }) => ($selected
        ? requireThemeColor(theme, 'accent')
        : 'transparent')};
    color: ${({ $action, theme }) => requireThemeColor(theme, $action ? 'link' : 'text')};
    font: inherit;
    font-size: 0.72rem;
    font-weight: ${({ $selected }) => ($selected ? 600 : 500)};
    line-height: 1.2;
    text-align: left;
    cursor: pointer;

    &:hover,
    &:focus-visible {
        outline: none;
        background: ${({ theme }) => requireThemeColor(theme, 'accentHover')};
    }
`;

const OptionCopy = styled.span`
    display: grid;
    gap: 0.15rem;
    min-width: 0;
`;

const OptionMeta = styled.span`
    overflow: hidden;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.62rem;
    font-weight: 500;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const Check = styled.span`
    color: ${({ theme }) => requireThemeColor(theme, 'link')};
    font-size: 0.72rem;
`;

const Divider = styled.div`
    height: 1px;
    margin: 0.3rem 0.25rem;
    background: ${({ theme }) => requireThemeColor(theme, 'border')};
`;

const Status = styled.span`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.62rem;
    font-weight: 500;
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

// Default stays a fixed label — the concrete default team name belongs in the
// menu meta ("Currently …"), not on the trigger. Pinned teams keep their name.
function selectionLabel(selection, teams) {
    if (selection === LENS.DEFAULT) return 'Default Curation Team';
    if (selection === LENS.RAW) return 'Uncensored';
    const [lens, rawTeamId] = selection.split(':');
    if (lens !== LENS.TEAM) throw new Error(`Invalid curation selection: ${selection}`);
    const teamId = Number(rawTeamId);
    const team = teams.find((item) => Number(item.team_id) === teamId);
    if (!team) throw new Error(`Selected curation team is missing: ${teamId}`);
    return team.name;
}

export default function CurationLensPicker({ community, viewer, onChange }) {
    const navigate = useNavigate();
    const rootRef = useRef(null);
    const [open, setOpen] = useState(false);
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
    const activeTeam = useMemo(() => {
        if (detailLoading || teamsLoading || !detail || !curated || selected === LENS.RAW) return null;
        const [lens, rawTeamId] = selected.split(':');
        const teamId = lens === LENS.TEAM
            ? Number(rawTeamId)
            : Number(detail.default_team?.team_id);
        const team = liveTeams.find((item) => Number(item.team_id) === teamId);
        if (!team) throw new Error(`Active curation team is missing: ${teamId}`);
        return team;
    }, [curated, detail, detailLoading, liveTeams, selected, teamsLoading]);

    useEffect(() => {
        setOpen(false);
        setOptimisticSelection(null);
    }, [community]);

    useEffect(() => {
        if (!open) return undefined;
        const closeOutside = (event) => {
            if (!rootRef.current?.contains(event.target)) setOpen(false);
        };
        document.addEventListener('pointerdown', closeOutside);
        return () => document.removeEventListener('pointerdown', closeOutside);
    }, [open]);

    useEffect(() => {
        // Hold the optimistic label until the indexer confirms the same lens.
        // Clearing earlier lets a slow/stale detail refresh snap the trigger
        // back to the previous team while a newer pick is already on chain.
        if (optimisticSelection && optimisticSelection === authoritativeSelection) {
            console.debug('[lens] optimistic confirmed by detail', {
                community,
                selection: optimisticSelection,
            });
            setOptimisticSelection(null);
        }
    }, [authoritativeSelection, community, optimisticSelection]);

    useEffect(() => {
        if (detailLoading || teamsLoading) return;
        const [lens, rawTeamId] = selected.split(':');
        console.debug('[lens] applying feed lens', { community, lens, teamId: rawTeamId || null, curated });
        onChange?.(lens, rawTeamId ? Number(rawTeamId) : null, activeTeam);
    }, [activeTeam, community, curated, detailLoading, onChange, selected, teamsLoading]);

    const change = (selection) => {
        setOpen(false);
        if (selection === '__team_action__') {
            const destination = isCurator && curatorTeamId
                ? `/c/${encodeURIComponent(community)}/teams/${curatorTeamId}`
                : `/c/${encodeURIComponent(community)}/teams/new`;
            console.debug('[lens] open team action', { community, destination });
            navigate(destination);
            return;
        }
        if (selection === selected) return;
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
            // Only roll back this pick — a newer optimistic choice must stick.
            setOptimisticSelection((current) => (current === selection ? null : current));
        });
    };

    // Background detail/team reloads must not flash "Loading…" over a known pick.
    const loading = (detailLoading && !detail) || (teamsLoading && rankedTeams.length === 0);
    const defaultTeamName = String(detail?.default_team?.name || '').trim();
    const teamActionLabel = isCurator ? 'Manage my team…' : 'Create new…';
    const currentLabel = pendingStatus
        || (loading ? 'Loading…' : selectionLabel(selected, rankedTeams));

    return (
        <Wrap aria-label="Community lens">
            <PickerRoot
                ref={rootRef}
                onKeyDown={(event) => {
                    if (event.key === 'Escape') setOpen(false);
                    if (event.key === 'ArrowDown') setOpen(true);
                }}
            >
                <PickerButton
                    type="button"
                    disabled={pending || loading}
                    aria-label="Curation lens"
                    aria-haspopup="listbox"
                    aria-expanded={open}
                    onClick={() => setOpen((value) => !value)}
                >
                    <PickerLabel>{currentLabel}</PickerLabel>
                    <Chevron $open={open} aria-hidden="true" />
                </PickerButton>
                {open && (
                    <Menu role="listbox" aria-label="Curation lens">
                        {(!detail || curated) && (
                            <Option
                                type="button"
                                role="option"
                                aria-selected={selected === LENS.DEFAULT}
                                $selected={selected === LENS.DEFAULT}
                                onClick={() => change(LENS.DEFAULT)}
                            >
                                <OptionCopy>
                                    <span>Default</span>
                                    {defaultTeamName && <OptionMeta>Currently {defaultTeamName}</OptionMeta>}
                                </OptionCopy>
                                {selected === LENS.DEFAULT && <Check aria-hidden="true">✓</Check>}
                            </Option>
                        )}
                        <Option
                            type="button"
                            role="option"
                            aria-selected={selected === LENS.RAW}
                            $selected={selected === LENS.RAW}
                            onClick={() => change(LENS.RAW)}
                        >
                            <span>Uncensored</span>
                            {selected === LENS.RAW && <Check aria-hidden="true">✓</Check>}
                        </Option>
                        {rankedTeams.length > 0 && <Divider />}
                        {rankedTeams.map((team) => {
                            const value = `${LENS.TEAM}:${team.team_id}`;
                            return (
                                <Option
                                    key={team.team_id}
                                    type="button"
                                    role="option"
                                    aria-selected={selected === value}
                                    $selected={selected === value}
                                    onClick={() => change(value)}
                                >
                                    <span>{team.name} ({formatSubscriberCount(Number(team.subscriber_count))})</span>
                                    {selected === value && <Check aria-hidden="true">✓</Check>}
                                </Option>
                            );
                        })}
                        <Divider />
                        <Option
                            type="button"
                            $action
                            onClick={() => change('__team_action__')}
                        >
                            <span>{teamActionLabel}</span>
                        </Option>
                    </Menu>
                )}
            </PickerRoot>
            {error && <Status>{error}</Status>}
        </Wrap>
    );
}
