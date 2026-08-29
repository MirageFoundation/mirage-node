import { useEffect, useState } from 'react';
import styled from 'styled-components';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { Helmet } from 'react-helmet-async';
import { HiOutlineUserGroup } from 'react-icons/hi2';
import Storage from '../../../utils/Storage';
import Api from '../../../utils/api';
import * as tx from '../../../utils/tx';
import { communityLabel, sanitizeCommunitySlug, isValidCommunitySlug } from '../../../utils/community';
import {
    MAX_CURATION_TEAM_DESCRIPTION_LENGTH,
    MAX_CURATION_TEAM_NAME_LENGTH,
    formatSubscriberCount,
    runeLength,
    sliceRunes,
    waitForOwnCurationTeam,
} from '../../../utils/curation';
import { formatError } from '../../../utils/errorMessages';
import { returnToFromLocation, withReturnTo } from '../../../utils/returnTo';
import { useCurationTeams } from '../../../logic/useCurationTeams';
import { useCommunityDetail } from '../../../logic/useCommunityDetail';
import { usePendingCuration } from '../../../logic/usePendingCuration';
import { canCurate } from '../../../logic/useSubscription';
import Button from '../components/Button';
import { requireThemeColor } from '../../../utils/themeColor';

const Page = styled.main`
    max-width: 820px;
    margin: 0 auto;
    padding: 1.1rem 1rem 2rem;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};

    @media (max-width: 600px) {
        padding: 0.85rem 0 1.5rem;
    }
`;

const HeaderRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding-bottom: 0.9rem;
    border-bottom: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
`;

const TitleBlock = styled.div`
    min-width: 0;
    flex: 1 1 auto;
`;

const Title = styled.h1`
    margin: 0;
    font-size: 1.35rem;
    font-weight: 700;
    letter-spacing: -0.025em;
    line-height: 1.2;
`;

const Subline = styled.div`
    display: flex;
    align-items: baseline;
    gap: 0.35rem;
    min-width: 0;
    margin-top: 0.3rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.72rem;
    line-height: 1.4;
`;

const Slug = styled.span`
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 500;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
`;

const HeaderActions = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex: 0 0 auto;
    padding-top: 0.1rem;
`;

const Card = styled.section`
    display: grid;
    gap: 0.65rem;
    padding: 1rem;
    margin-top: 0.85rem;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 12px;
    background: ${({ theme }) => requireThemeColor(theme, 'panel')};
    font-size: 0.8rem;
    line-height: 1.45;
`;

const CardActions = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.4rem;
    flex-wrap: wrap;
    margin-top: 0.15rem;

    @media (max-width: 600px) {
        flex-direction: column;
        align-items: stretch;
        & > * {
            width: 100%;
        }
    }
`;

const TeamLink = styled(Link)`
    color: ${({ theme }) => requireThemeColor(theme, 'link')};
    font-size: 0.92rem;
    font-weight: 700;
    text-decoration: none;
    &:hover { text-decoration: underline; }
`;

const Meta = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.72rem;
    line-height: 1.45;
`;

const Form = styled.form`
    display: grid;
    gap: 0.9rem;
`;

const Field = styled.label`
    display: grid;
    gap: 0.35rem;
`;

const FieldLabel = styled.span`
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    font-size: 0.72rem;
    font-weight: 650;
`;

const FieldHint = styled.span`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.65rem;
    line-height: 1.4;
`;

const Input = styled.input`
    min-height: 2.5rem;
    padding: 0.55rem 0.7rem;
    border-radius: 8px;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')};
    color: inherit;
    font: inherit;
    font-size: 0.8rem;

    &:focus {
        border-color: ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        outline: 2px solid color-mix(in srgb, ${({ theme }) => requireThemeColor(theme, 'focusBlue')} 20%, transparent);
        outline-offset: 1px;
    }
`;

const Textarea = styled.textarea`
    min-height: 7rem;
    padding: 0.65rem 0.7rem;
    resize: vertical;
    border-radius: 8px;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')};
    color: inherit;
    font: inherit;
    font-size: 0.8rem;
    line-height: 1.4;

    &:focus {
        border-color: ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        outline: 2px solid color-mix(in srgb, ${({ theme }) => requireThemeColor(theme, 'focusBlue')} 20%, transparent);
        outline-offset: 1px;
    }
`;

const ErrorText = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'voteDown')};
    font-size: 0.65rem;
    line-height: 1.4;
`;

const BackLink = styled(Link)`
    display: inline-block;
    margin-bottom: 0.45rem;
    color: ${({ theme }) => requireThemeColor(theme, 'link')};
    font-size: 0.65rem;
    font-weight: 500;
    text-decoration: none;
    &:hover { text-decoration: underline; }
`;

const EmptyState = styled.section`
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.65rem;
    margin-top: 1rem;
    padding: 2.5rem 1.25rem;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 14px;
    background: ${({ theme }) => requireThemeColor(theme, 'panel')};
    text-align: center;
`;

const EmptyIcon = styled.div`
    display: grid;
    place-items: center;
    width: 2.75rem;
    height: 2.75rem;
    border-radius: 50%;
    background: ${({ theme }) => requireThemeColor(theme, 'feedCtrlHoverBg')};
    color: ${({ theme }) => requireThemeColor(theme, 'link')};
    font-size: 1.35rem;
`;

const EmptyTitle = styled.h2`
    margin: 0.15rem 0 0;
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
`;

const EmptyBody = styled.p`
    max-width: 28rem;
    margin: 0;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.75rem;
    line-height: 1.55;
`;

const TeamCard = styled.section`
    display: grid;
    gap: 0.55rem;
    margin-top: 0.75rem;
    padding: 0.95rem 1rem;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 12px;
    background: ${({ theme }) => requireThemeColor(theme, 'panel')};
    transition: border-color 120ms ease, transform 120ms ease;

    &:hover {
        border-color: ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        transform: translateY(-1px);
    }
`;

const TeamHeader = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
`;

export default function CurationTeamsView({ createOnly = false }) {
    const params = useParams();
    const navigate = useNavigate();
    const location = useLocation();
    const returnTo = returnToFromLocation(location);
    const routeCommunity = String(params.topic || params.community || '').toLowerCase();
    const [slug, setSlug] = useState(routeCommunity);
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [error, setError] = useState('');
    // idle | creating | verifying — keep the form mounted until the team is listed
    const [createStatus, setCreateStatus] = useState('idle');
    const viewer = String(Storage.load('publicKey', '') || '').toLowerCase();
    const community = routeCommunity || sanitizeCommunitySlug(slug);
    const canLoad = Boolean(routeCommunity && isValidCommunitySlug(routeCommunity));
    const typedSlug = sanitizeCommunitySlug(slug);
    const previewSlug = canLoad ? routeCommunity : (isValidCommunitySlug(typedSlug) ? typedSlug : '');
    const teamState = useCurationTeams(previewSlug, { viewer, enabled: Boolean(previewSlug) });
    const communityState = useCommunityDetail(previewSlug, viewer, Boolean(previewSlug));
    const { getInfo, getStatus } = usePendingCuration();
    const pending = getInfo('create_curation_team', community);
    const alreadyCurator = Boolean(viewer) && teamState.teams.some((team) => String(team.owner || '').toLowerCase() === viewer);
    const ownTeam = teamState.teams.find((team) => String(team.owner || '').toLowerCase() === viewer);
    const createPath = routeCommunity
        ? `/c/${encodeURIComponent(routeCommunity)}/teams/new`
        : '/curator-teams/new';
    const [eligible, setEligible] = useState(null);
    const label = communityLabel(routeCommunity || previewSlug || '');
    const liveCount = teamState.teams.length;

    useEffect(() => {
        if (!createOnly) {
            setEligible(null);
            return undefined;
        }
        if (!viewer) {
            setEligible(false);
            return undefined;
        }
        let cancelled = false;
        Api.get('get_user_status', { address: viewer, _cb: Date.now() })
            .then((data) => {
                if (cancelled) return;
                if (typeof data?.effective_paid !== 'boolean') {
                    throw new Error('user status missing effective_paid');
                }
                if (typeof data?.user_level !== 'number') {
                    throw new Error('user status missing user_level');
                }
                const next = canCurate(data.effective_paid, data.user_level);
                setEligible(next);
                setError('');
                tx.cacheUserStatus(data);
                console.debug('[curation] create eligibility', {
                    effectivePaid: data.effective_paid,
                    userLevel: data.user_level,
                    canCurate: next,
                });
            })
            .catch((err) => {
                if (cancelled) return;
                const message = formatError(err);
                setEligible(false);
                setError(message);
                console.error('[curation] eligibility check failed', { error: message });
            });
        return () => { cancelled = true; };
    }, [createOnly, viewer]);

    const maxTeamNameLength = MAX_CURATION_TEAM_NAME_LENGTH;
    const maxTeamDescriptionLength = MAX_CURATION_TEAM_DESCRIPTION_LENGTH;

    const submit = async (event) => {
        event.preventDefault();
        const nextSlug = sanitizeCommunitySlug(routeCommunity || slug);
        if (!isValidCommunitySlug(nextSlug)) {
            setError('Enter a valid lowercase community slug.');
            return;
        }
        if (!eligible) {
            setError(formatError({ error_code: 'not_subscriber' }));
            return;
        }
        const trimmedName = name.trim();
        if (!trimmedName) {
            setError('Team name is required.');
            return;
        }
        if (runeLength(trimmedName) > maxTeamNameLength) {
            setError(`Team name too long. Maximum ${maxTeamNameLength} characters.`);
            console.error('[curation] create team name too long', {
                length: runeLength(trimmedName),
                max: maxTeamNameLength,
            });
            return;
        }
        if (runeLength(description) > maxTeamDescriptionLength) {
            setError(`Description too long. Maximum ${maxTeamDescriptionLength} characters.`);
            console.error('[curation] create team description too long', {
                length: runeLength(description),
                max: maxTeamDescriptionLength,
            });
            return;
        }
        setError('');
        setCreateStatus('creating');
        console.debug('[curation] create team form', {
            community: nextSlug,
            nameLength: runeLength(trimmedName),
            descriptionLength: runeLength(description),
            maxNameLength: maxTeamNameLength,
            maxDescriptionLength: maxTeamDescriptionLength,
            joined: communityState.detail?.viewer_joined === true,
        });
        try {
            const result = await tx.createCuratorTeam(nextSlug, trimmedName, description);
            if (!result?.success) {
                setError(formatError(result));
                setCreateStatus('idle');
                return;
            }
            const txHash = result.tx_hash ? String(result.tx_hash).toLowerCase() : '';
            if (!txHash) {
                setError('Team creation succeeded without a transaction hash.');
                console.error('[curation] create team missing tx_hash', { community: nextSlug });
                setCreateStatus('idle');
                return;
            }

            // Same staged wait as username changes: confirm the tx is indexed,
            // then confirm the teams API actually lists our new team.
            setCreateStatus('verifying');
            console.debug('[curation] create team verifying', { community: nextSlug, txHash: txHash.slice(0, 12) });
            const pollResult = await tx.pollTxStatus(txHash);
            if (!pollResult) {
                setError('Team creation timed out waiting for confirmation.');
                setCreateStatus('idle');
                return;
            }
            if (!pollResult.success) {
                setError(pollResult.error_details?.message || 'Transaction rejected');
                setCreateStatus('idle');
                return;
            }

            const visible = await waitForOwnCurationTeam(nextSlug, viewer, trimmedName);
            if (!visible) {
                setError('Team created but is not visible yet. Open Teams and refresh in a moment.');
                console.error('[curation] create team not visible after index', {
                    community: nextSlug,
                    name: trimmedName,
                });
                setCreateStatus('idle');
                return;
            }

            console.debug('[curation] create team ready', {
                community: nextSlug,
                teamId: visible.team_id,
            });
            navigate(`/c/${encodeURIComponent(nextSlug)}/teams`);
        } catch (err) {
            const message = formatError(err);
            setError(message);
            console.error('[curation] create team failed', { community: nextSlug, error: message });
            setCreateStatus('idle');
        }
    };

    const createBusy = createStatus !== 'idle' || !!pending;
    const createButtonLabel = createStatus === 'verifying'
        ? 'Verifying…'
        : (getStatus('create_curation_team', community, 0, '', 'Creating…') || (createStatus === 'creating' ? 'Creating…' : 'Create team'));

    const teamsListPath = routeCommunity
        ? `/c/${encodeURIComponent(routeCommunity)}/teams`
        : '/communities';
    // Single phase for the create route — drives one title, one body, no stacked headings.
    // While creating/verifying, keep the form mounted even if the team list starts to update.
    let createPhase = 'form';
    if (!viewer) createPhase = 'signin';
    else if (eligible === null) createPhase = 'checking';
    else if (eligible === false) createPhase = 'subscribe';
    else if (alreadyCurator && createStatus === 'idle') createPhase = 'already';
    else if (previewSlug && communityState.loading && createStatus === 'idle') createPhase = 'loading';

    const createTitle = {
        signin: 'Sign in',
        checking: 'New team',
        subscribe: 'Subscribe',
        already: 'Your team',
        loading: 'New team',
        form: 'New team',
    }[createPhase];

    const createForm = (
        <Card id="create">
            <Meta>
                You&apos;ll lead this team and define how this community is curated for users who choose it.
            </Meta>
            <Form onSubmit={submit}>
                {createOnly && !routeCommunity && (
                    <Field>
                        <FieldLabel>Community</FieldLabel>
                        <Input
                            aria-label="Community slug"
                            value={slug}
                            onChange={(event) => setSlug(sanitizeCommunitySlug(event.target.value))}
                            placeholder="community-slug"
                            required
                            disabled={createBusy}
                        />
                    </Field>
                )}
                <Field>
                    <FieldLabel>Team name</FieldLabel>
                    <Input
                        aria-label="Team name"
                        value={name}
                        onChange={(event) => setName(sliceRunes(event.target.value, maxTeamNameLength))}
                        placeholder="e.g. Signal Desk"
                        maxLength={maxTeamNameLength}
                        required
                        disabled={createBusy}
                    />
                    <FieldHint>{runeLength(name)} / {maxTeamNameLength} characters</FieldHint>
                </Field>
                <Field>
                    <FieldLabel>Describe your curation approach:</FieldLabel>
                    <Textarea
                        aria-label="Describe your curation approach"
                        value={description}
                        onChange={(event) => setDescription(sliceRunes(event.target.value, maxTeamDescriptionLength))}
                        placeholder="What users will see when they pick this team."
                        maxLength={maxTeamDescriptionLength}
                        disabled={createBusy}
                    />
                    <FieldHint>
                        {runeLength(description)} / {maxTeamDescriptionLength} characters. Help users understand what
                        they&apos;ll see and include how you moderate spam, adult content, and brigading.
                    </FieldHint>
                </Field>
                {error && <ErrorText>{error}</ErrorText>}
                <CardActions>
                    <Button type="submit" size="xs" disabled={createBusy} aria-busy={createBusy}>
                        {createButtonLabel}
                    </Button>
                    {routeCommunity && !createBusy && (
                        <Button to={teamsListPath} size="xs" variant="secondary">Cancel</Button>
                    )}
                </CardActions>
            </Form>
        </Card>
    );

    // Create route: one quiet title + one body. No "Create…" header stacked on a "Create…" card.
    if (createOnly) {
        return (
            <Page>
                <Helmet><title>{createTitle}{label ? ` · ${label}` : ''} | Mirage</title></Helmet>
                {routeCommunity ? (
                    <BackLink to={teamsListPath}>← Teams</BackLink>
                ) : null}
                <HeaderRow>
                    <TitleBlock>
                        <Title>{createTitle}</Title>
                        {previewSlug ? (
                            <Subline>
                                <Slug title={communityLabel(previewSlug)}>{communityLabel(previewSlug)}</Slug>
                            </Subline>
                        ) : null}
                    </TitleBlock>
                </HeaderRow>

                {createPhase === 'signin' && (
                    <Card>
                        <Meta>Sign in with a paid subscription or admin account to create a curator team here.</Meta>
                        <CardActions>
                            <Button to={withReturnTo('/login', returnTo)} size="xs">Sign in</Button>
                        </CardActions>
                    </Card>
                )}
                {createPhase === 'checking' && <Card><Meta>Checking eligibility…</Meta></Card>}
                {createPhase === 'subscribe' && (
                    <Card>
                        <Meta>Curator teams require an active paid subscription or an admin account.</Meta>
                        <CardActions>
                            <Button to={withReturnTo('/subscription', returnTo)} size="xs">Subscribe</Button>
                        </CardActions>
                        {error && <ErrorText>{error}</ErrorText>}
                    </Card>
                )}
                {createPhase === 'already' && (
                    <Card>
                        <Meta>
                            You already curate {ownTeam?.name || 'a team'} here.
                            One membership per community.
                        </Meta>
                        {ownTeam && (
                            <CardActions>
                                <Button
                                    to={`/c/${encodeURIComponent(routeCommunity || previewSlug)}/teams/${ownTeam.team_id}`}
                                    size="xs"
                                >
                                    Open your team
                                </Button>
                            </CardActions>
                        )}
                    </Card>
                )}
                {createPhase === 'loading' && <Card><Meta>Loading community…</Meta></Card>}
                {createPhase === 'form' && createForm}
            </Page>
        );
    }

    return (
        <Page>
            <Helmet>
                <title>{`Curator teams${label ? ` · ${label}` : ''}`} | Mirage</title>
            </Helmet>

            <HeaderRow>
                <TitleBlock>
                    <Title>Curator teams</Title>
                    {label ? (
                        <Subline>
                            <Slug title={label}>{label}</Slug>
                        </Subline>
                    ) : null}
                </TitleBlock>
                <HeaderActions>
                    {liveCount > 0 && (
                        alreadyCurator && ownTeam ? (
                            <Button
                                to={`/c/${encodeURIComponent(routeCommunity)}/teams/${ownTeam.team_id}`}
                                size="xs"
                            >
                                Open your team
                            </Button>
                        ) : (
                            <Button to={createPath} size="xs">Create team</Button>
                        )
                    )}
                </HeaderActions>
            </HeaderRow>

            {teamState.loading && <Card><Meta>Loading curator teams…</Meta></Card>}
            {teamState.error && <ErrorText>{teamState.error}</ErrorText>}
            {!teamState.loading && teamState.teams.map((team) => (
                <TeamCard key={team.team_id}>
                    <TeamHeader>
                        <TeamLink to={`/c/${encodeURIComponent(routeCommunity)}/teams/${team.team_id}`}>
                            {team.name}
                        </TeamLink>
                    </TeamHeader>
                    <Meta>{team.description || 'No description provided.'}</Meta>
                    <Meta>{formatSubscriberCount(Number(team.subscriber_count))}</Meta>
                </TeamCard>
            ))}
            {!teamState.loading && teamState.teams.length === 0 && (
                <EmptyState>
                    <EmptyIcon><HiOutlineUserGroup aria-hidden="true" /></EmptyIcon>
                    <EmptyTitle>No curator team for this community</EmptyTitle>
                    <EmptyBody>
                        This community has no curator team yet, so everyone sees the uncensored feed. Create one to offer a curated feed.
                    </EmptyBody>
                    <Button to={createPath} size="xs">Create the first team</Button>
                </EmptyState>
            )}
        </Page>
    );
}
