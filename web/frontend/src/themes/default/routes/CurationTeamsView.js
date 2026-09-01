import { useCallback, useEffect, useState } from 'react';
import styled from 'styled-components';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { Helmet } from 'react-helmet-async';
import Storage from '../../../utils/Storage';
import Api from '../../../utils/api';
import * as tx from '../../../utils/tx';
import { invalidateCache as invalidateCommunitiesCache, notifyJoinedCommunitiesUpdated } from '../../../utils/Subscriptions';
import { communityLabel, sanitizeCommunitySlug, isValidCommunitySlug } from '../../../utils/community';
import {
    CURATION_TEAM_DESCRIPTION_EXAMPLE,
    MAX_CURATION_TEAM_DESCRIPTION_LENGTH,
    MAX_CURATION_TEAM_NAME_LENGTH,
    invalidateCurationReads,
    requireCurationTeamDescription,
    requireCurationTeamName,
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

const FormSection = styled.section`
    display: grid;
    gap: 0.65rem;
    margin-top: 0.85rem;
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

const Input = styled.input.attrs({
    autoComplete: 'off',
    'data-bwignore': 'true',
    'data-1p-ignore': 'true',
    'data-lpignore': 'true',
})`
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

const Textarea = styled.textarea.attrs({
    autoComplete: 'off',
    'data-bwignore': 'true',
    'data-1p-ignore': 'true',
    'data-lpignore': 'true',
})`
    /* ~14 lines at 0.8rem/1.4 ≈ full 800-char description without scrolling */
    min-height: 16rem;
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

export default function CurationTeamsView() {
    const params = useParams();
    const navigate = useNavigate();
    const location = useLocation();
    const returnTo = returnToFromLocation(location);
    const routeCommunity = String(params.community || params.community || '').toLowerCase();
    const [slug, setSlug] = useState(routeCommunity);
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [error, setError] = useState('');
    // idle | creating | verifying — keep the form mounted until the new team is visible
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
    // null = checking; true/false = confirmed from get_user_status.
    // Eligibility fetch failures must NOT look like "not subscribed".
    const [eligible, setEligible] = useState(null);
    const [eligibilityError, setEligibilityError] = useState('');
    const [eligibilityNonce, setEligibilityNonce] = useState(0);
    const label = communityLabel(routeCommunity || previewSlug || '');

    const retryEligibility = useCallback(() => {
        setEligible(null);
        setEligibilityError('');
        setEligibilityNonce((n) => n + 1);
        console.debug('[curation] retry eligibility check');
    }, []);

    useEffect(() => {
        if (!viewer) {
            setEligible(false);
            setEligibilityError('');
            return undefined;
        }
        let cancelled = false;
        setEligible(null);
        setEligibilityError('');
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
                setEligibilityError('');
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
                // Leave eligible null — a failed check is not "ineligible".
                setEligible(null);
                setEligibilityError(message);
                console.error('[curation] eligibility check failed', { error: message });
            });
        return () => { cancelled = true; };
    }, [viewer, eligibilityNonce]);

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
        try {
            requireCurationTeamName(trimmedName, maxTeamNameLength);
            requireCurationTeamDescription(description, maxTeamDescriptionLength);
        } catch (validationError) {
            setError(validationError.message);
            console.error('[curation] create team profile validation failed', {
                error: validationError.message,
                nameLength: runeLength(trimmedName),
                descriptionLength: runeLength(description),
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
                setError('Team created but is not visible yet. Refresh in a moment.');
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
            // The viewer just became a curator here, but the membership lookup
            // behind the curate buttons caches per community for the life of the
            // page, and every feed read still holds a pre-team response. Without
            // this the community feed shows no curator controls until a reload.
            // Safe to fire now and not earlier: waitForOwnCurationTeam has already
            // proven the indexer serves the team, so the refetch cannot re-cache
            // the state we are replacing.
            invalidateCurationReads(nextSlug);
            invalidateCommunitiesCache();
            notifyJoinedCommunitiesUpdated({ added: nextSlug });
            const visibleId = Number(visible.team_id);
            console.debug('[curation] opening created team', {
                community: nextSlug,
                teamId: visibleId,
            });
            navigate(`/c/${encodeURIComponent(nextSlug)}/teams/${visibleId}`);
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

    const communityPath = routeCommunity
        ? `/c/${encodeURIComponent(routeCommunity)}`
        : '/communities';
    // Single phase for the create route — drives one title, one body, no stacked headings.
    // While creating/verifying, keep the form mounted as membership data updates.
    let createPhase = 'form';
    if (!viewer) createPhase = 'signin';
    else if (eligibilityError) createPhase = 'eligibility_error';
    else if (eligible === null) createPhase = 'checking';
    else if (eligible === false) createPhase = 'subscribe';
    else if (teamState.error) createPhase = 'error';
    else if (alreadyCurator && createStatus === 'idle') createPhase = 'already';
    else if (previewSlug && (communityState.loading || teamState.loading) && createStatus === 'idle') createPhase = 'loading';

    // Page is always "create a team" — never retitle to Subscribe on a gate/error.
    const createTitle = {
        signin: 'New team',
        checking: 'New team',
        eligibility_error: 'New team',
        subscribe: 'New team',
        error: 'New team',
        already: 'Your team',
        loading: 'New team',
        form: 'New team',
    }[createPhase];

    const createForm = (
        <FormSection id="create">
            <Meta>
                You&apos;ll lead this team and define how this community is curated for users who choose it.
            </Meta>
            <Form onSubmit={submit}>
                {!routeCommunity && (
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
                        placeholder="Sailboats & Sailors only"
                        maxLength={maxTeamNameLength}
                        required
                        disabled={createBusy}
                    />
                    <FieldHint>{runeLength(name)} / {maxTeamNameLength} characters</FieldHint>
                </Field>
                <Field>
                    <FieldLabel>Community header description</FieldLabel>
                    <FieldHint>
                        Shown beneath your team name in the community header when users choose your curation team.
                    </FieldHint>
                    <Textarea
                        aria-label="Community header description"
                        value={description}
                        onChange={(event) => setDescription(sliceRunes(event.target.value, maxTeamDescriptionLength))}
                        placeholder={CURATION_TEAM_DESCRIPTION_EXAMPLE}
                        maxLength={maxTeamDescriptionLength * 2}
                        disabled={createBusy}
                    />
                    <FieldHint>
                        {runeLength(description)} / {maxTeamDescriptionLength} characters
                    </FieldHint>
                </Field>
                {error && <ErrorText>{error}</ErrorText>}
                <CardActions>
                    <Button type="submit" size="xs" disabled={createBusy} aria-busy={createBusy}>
                        {createButtonLabel}
                    </Button>
                    {routeCommunity && !createBusy && (
                        <Button to={communityPath} size="xs" variant="secondary">Cancel</Button>
                    )}
                </CardActions>
            </Form>
        </FormSection>
    );

    return (
        <Page>
            <Helmet><title>{createTitle}{label ? ` · ${label}` : ''} | Mirage</title></Helmet>
            {routeCommunity ? (
                <BackLink to={communityPath}>← Back to community</BackLink>
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
                <FormSection>
                    <Meta>Sign in with a paid subscription or admin account to create a curator team here.</Meta>
                    <CardActions>
                        <Button to={withReturnTo('/login', returnTo)} size="xs">Sign in</Button>
                    </CardActions>
                </FormSection>
            )}
            {createPhase === 'checking' && <FormSection><Meta>Checking eligibility…</Meta></FormSection>}
            {createPhase === 'eligibility_error' && (
                <FormSection>
                    <ErrorText role="alert">{eligibilityError}</ErrorText>
                    <CardActions>
                        <Button type="button" size="xs" onClick={retryEligibility}>Retry</Button>
                    </CardActions>
                </FormSection>
            )}
            {createPhase === 'subscribe' && (
                <FormSection>
                    <Meta>Curator teams require an active paid subscription or an admin account.</Meta>
                    <CardActions>
                        <Button to={withReturnTo('/subscription', returnTo)} size="xs">Subscribe</Button>
                    </CardActions>
                </FormSection>
            )}
            {createPhase === 'error' && (
                <FormSection><ErrorText role="alert">{teamState.error}</ErrorText></FormSection>
            )}
            {createPhase === 'already' && (
                <FormSection>
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
                </FormSection>
            )}
            {createPhase === 'loading' && <FormSection><Meta>Loading community…</Meta></FormSection>}
            {createPhase === 'form' && createForm}
        </Page>
    );
}
