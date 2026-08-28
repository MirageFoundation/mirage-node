import { useEffect, useState } from 'react';
import styled from 'styled-components';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { Helmet } from 'react-helmet-async';
import Storage from '../../../utils/Storage';
import Api from '../../../utils/api';
import * as tx from '../../../utils/tx';
import { communityLabel, sanitizeCommunitySlug, isValidCommunitySlug } from '../../../utils/community';
import { formatError } from '../../../utils/errorMessages';
import { returnToFromLocation, withReturnTo } from '../../../utils/returnTo';
import { useCurationTeams } from '../../../logic/useCurationTeams';
import { useCommunityDetail } from '../../../logic/useCommunityDetail';
import { usePendingCuration } from '../../../logic/usePendingCuration';
import { canCurate } from '../../../logic/useSubscription';
import Button from '../components/Button';
import { requireThemeColor } from '../../../utils/themeColor';

/**
 * Curator teams list / create — typography matches Discover/Inbox (R7):
 * page title ~1.05rem, meta 0.62–0.7rem, body 0.75rem. Never put the
 * community slug in the page title: long slugs blow the header apart.
 */

const Page = styled.main`
    max-width: 820px;
    margin: 0 auto;
    padding: 0.75rem 1rem 1.5rem;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
`;

const HeaderRow = styled.div`
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 0.75rem;
`;

const TitleBlock = styled.div`
    min-width: 0;
    flex: 1 1 auto;
`;

const Title = styled.h1`
    margin: 0;
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    line-height: 1.25;
`;

const Subline = styled.div`
    display: flex;
    align-items: baseline;
    gap: 0.35rem;
    min-width: 0;
    margin-top: 0.2rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.65rem;
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
    gap: 0.45rem;
    padding: 0.7rem 0.75rem;
    margin-top: 0.65rem;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 10px;
    background: ${({ theme }) => requireThemeColor(theme, 'panel')};
    font-size: 0.75rem;
    line-height: 1.45;
`;

const CardTitle = styled.h2`
    margin: 0;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    line-height: 1.3;
`;

const CardActions = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex-wrap: wrap;
    margin-top: 0.15rem;
`;

const TeamLink = styled(Link)`
    color: ${({ theme }) => requireThemeColor(theme, 'link')};
    font-size: 0.8rem;
    font-weight: 600;
    text-decoration: none;
    &:hover { text-decoration: underline; }
`;

const Meta = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.65rem;
    line-height: 1.45;
`;

const Form = styled.form`
    display: grid;
    gap: 0.5rem;
    margin-top: 0.15rem;
`;

const Input = styled.input`
    padding: 0.45rem 0.55rem;
    border-radius: 7px;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')};
    color: inherit;
    font: inherit;
    font-size: 0.75rem;
`;

const Textarea = styled.textarea`
    min-height: 4.5rem;
    padding: 0.45rem 0.55rem;
    resize: vertical;
    border-radius: 7px;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')};
    color: inherit;
    font: inherit;
    font-size: 0.75rem;
    line-height: 1.4;
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
    const [joining, setJoining] = useState(false);
    const label = communityLabel(routeCommunity || previewSlug || '');
    const liveCount = teamState.teams.length;
    const statusLabel = liveCount ? 'Curated' : 'Uncurated';

    useEffect(() => {
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
    }, [viewer]);

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
        if (previewSlug && communityState.detail && communityState.detail.viewer_joined !== true) {
            setError(formatError({ error_code: 'must_join_community' }));
            return;
        }
        setError('');
        console.debug('[curation] create team form', {
            community: nextSlug,
            nameLength: name.length,
        });
        const result = await tx.createCuratorTeam(nextSlug, name, description);
        if (!result?.success) {
            setError(formatError(result));
            return;
        }
        navigate(`/c/${encodeURIComponent(nextSlug)}/teams`);
    };

    const teamsListPath = routeCommunity
        ? `/c/${encodeURIComponent(routeCommunity)}/teams`
        : '/communities';
    const joined = communityState.detail?.viewer_joined === true;
    // Single phase for the create route — drives one title, one body, no stacked headings.
    let createPhase = 'form';
    if (!viewer) createPhase = 'signin';
    else if (eligible === null) createPhase = 'checking';
    else if (eligible === false) createPhase = 'subscribe';
    else if (alreadyCurator) createPhase = 'already';
    else if (previewSlug && communityState.loading) createPhase = 'loading';
    else if (previewSlug && communityState.detail && !joined) createPhase = 'follow';

    const createTitle = {
        signin: 'Sign in',
        checking: 'New team',
        subscribe: 'Subscribe',
        already: 'Your team',
        loading: 'New team',
        follow: 'Follow community',
        form: 'New team',
    }[createPhase];

    const createForm = (
        <Card id="create">
            {!createOnly && <CardTitle>New team</CardTitle>}
            <Meta>
                You become this team&apos;s leader. Other teams in this community stay and compete as lenses.
            </Meta>
            <Form onSubmit={submit}>
                {createOnly && !routeCommunity && (
                    <Input
                        aria-label="Community slug"
                        value={slug}
                        onChange={(event) => setSlug(sanitizeCommunitySlug(event.target.value))}
                        placeholder="community-slug"
                        required
                    />
                )}
                <Input
                    aria-label="Team name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="e.g. Signal Desk"
                    required
                />
                <Textarea
                    aria-label="Team description"
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="What this lens stands for — include how you moderate (e.g. hide spam, keep adult content, no brigading)"
                />
                {error && <ErrorText>{error}</ErrorText>}
                <CardActions>
                    <Button type="submit" size="xs" disabled={!!pending}>
                        {getStatus('create_curation_team', community, 0, '', 'Creating…') || 'Create team'}
                    </Button>
                </CardActions>
            </Form>
        </Card>
    );

    const followCommunity = async () => {
        setJoining(true);
        setError('');
        const result = await tx.followTopic(previewSlug);
        setJoining(false);
        if (!result?.success) {
            setError(formatError(result));
            return;
        }
        communityState.refresh().catch(() => {});
    };

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
                {createPhase === 'follow' && (
                    <Card>
                        <Meta>Follow this community before creating a team.</Meta>
                        <CardActions>
                            <Button type="button" size="xs" disabled={joining} onClick={followCommunity}>
                                {joining ? 'Following…' : 'Follow'}
                            </Button>
                        </CardActions>
                        {error && <ErrorText>{error}</ErrorText>}
                    </Card>
                )}
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
                    <Subline>
                        {label ? <Slug title={label}>{label}</Slug> : null}
                        {label ? <span aria-hidden="true">·</span> : null}
                        <span>{statusLabel} · {liveCount} live</span>
                    </Subline>
                </TitleBlock>
                <HeaderActions>
                    <Button to={createPath} size="xs">Create team</Button>
                </HeaderActions>
            </HeaderRow>

            {teamState.loading && <Card><Meta>Loading curator teams…</Meta></Card>}
            {teamState.error && <ErrorText>{teamState.error}</ErrorText>}
            {!teamState.loading && teamState.teams.map((team) => (
                <Card key={team.team_id}>
                    <TeamLink to={`/c/${encodeURIComponent(routeCommunity)}/teams/${team.team_id}`}>
                        {team.name}
                    </TeamLink>
                    {String(team.team_id) === String(communityState.detail?.default_team?.team_id) && (
                        <Meta>Node default</Meta>
                    )}
                    <Meta>{team.description || 'No description provided.'}</Meta>
                    <Meta>{team.subscriber_count} paid subscribers</Meta>
                </Card>
            ))}
            {!teamState.loading && teamState.teams.length === 0 && (
                <Card>
                    <Meta>
                        No curator teams yet. Posts stay available through the uncensored lens.
                    </Meta>
                </Card>
            )}

            {!viewer && (
                <Card>
                    <Meta>Sign in with a paid subscription or admin account to create a curator team.</Meta>
                    <CardActions>
                        <Button to={withReturnTo('/login', returnTo)} size="xs">Sign in</Button>
                    </CardActions>
                </Card>
            )}
            {viewer && eligible === null && <Card><Meta>Checking eligibility…</Meta></Card>}
            {viewer && eligible === false && (
                <Card>
                    <Meta>Curator teams require an active paid subscription or an admin account.</Meta>
                    <CardActions>
                        <Button to={withReturnTo('/subscription', returnTo)} size="xs">Subscribe</Button>
                    </CardActions>
                    {error && <ErrorText>{error}</ErrorText>}
                </Card>
            )}
            {viewer && eligible === true && !alreadyCurator && previewSlug && communityState.loading && (
                <Card><Meta>Loading community…</Meta></Card>
            )}
            {viewer && eligible === true && alreadyCurator && (
                <Card>
                    <Meta>
                        You already curate {ownTeam?.name || 'a team'} here. One membership per community.
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
            {viewer && eligible === true && !alreadyCurator && previewSlug && communityState.detail && !joined && (
                <Card>
                    <Meta>Follow this community before creating a team.</Meta>
                    <CardActions>
                        <Button type="button" size="xs" disabled={joining} onClick={followCommunity}>
                            {joining ? 'Following…' : 'Follow'}
                        </Button>
                    </CardActions>
                    {error && <ErrorText>{error}</ErrorText>}
                </Card>
            )}
            {viewer && eligible === true && !alreadyCurator && (!previewSlug || joined) && createForm}
        </Page>
    );
}
