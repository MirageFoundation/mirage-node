import { useEffect, useState } from 'react';
import styled from 'styled-components';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Helmet } from 'react-helmet-async';
import Storage from '../../../utils/Storage';
import Api from '../../../utils/api';
import * as tx from '../../../utils/tx';
import { communityLabel, sanitizeCommunitySlug, isValidCommunitySlug } from '../../../utils/community';
import { formatError } from '../../../utils/errorMessages';
import { useCurationTeams } from '../../../logic/useCurationTeams';
import { useCommunityDetail } from '../../../logic/useCommunityDetail';
import { usePendingCuration } from '../../../logic/usePendingCuration';
import Button from '../components/Button';
import { requireThemeColor } from '../../../utils/themeColor';

const Page = styled.main`
    max-width: 820px;
    margin: 0 auto;
    padding: 1rem;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
`;
const Header = styled.div`
    display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
`;
const Card = styled.section`
    padding: 0.85rem;
    margin-top: 0.75rem;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 10px;
    background: ${({ theme }) => requireThemeColor(theme, 'panel')};
`;
const TeamLink = styled(Link)`
    color: ${({ theme }) => requireThemeColor(theme, 'link')};
    font-size: 0.9rem; font-weight: 700; text-decoration: none;
`;
const Meta = styled.div`
    margin-top: 0.3rem; color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.7rem; line-height: 1.45;
`;
const Form = styled.form`
    display: grid; gap: 0.6rem; margin-top: 0.7rem;
`;
const Input = styled.input`
    padding: 0.55rem; border-radius: 7px; border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')}; color: inherit;
`;
const Textarea = styled.textarea`
    min-height: 5rem; padding: 0.55rem; resize: vertical; border-radius: 7px;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')}; color: inherit;
`;
const ErrorText = styled.div`color: ${({ theme }) => requireThemeColor(theme, 'voteDown')}; font-size: 0.7rem;`;

export default function CurationTeamsView({ createOnly = false }) {
    const params = useParams();
    const navigate = useNavigate();
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
    const [paid, setPaid] = useState(null);
    const [joining, setJoining] = useState(false);

    useEffect(() => {
        if (!viewer) {
            setPaid(false);
            return undefined;
        }
        let cancelled = false;
        Api.get('get_user_status', { address: viewer, _cb: Date.now() })
            .then((data) => {
                if (cancelled) return;
                if (typeof data?.effective_paid !== 'boolean') {
                    throw new Error('user status missing effective_paid');
                }
                setPaid(data.effective_paid);
                setError('');
                tx.cacheUserStatus(data);
                console.debug('[curation] create eligibility', { effectivePaid: data.effective_paid });
            })
            .catch((err) => {
                if (cancelled) return;
                const message = formatError(err);
                setPaid(false);
                setError(message);
                console.error('[curation] paid status failed', { error: message });
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
        if (!paid) {
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

    const createForm = <Card id="create">
        <h2>Create curator team</h2>
        <Meta>You become this team&apos;s leader. You must already follow the community and have an active paid subscription. Other teams in this community stay; they compete as lenses.</Meta>
        <Form onSubmit={submit}>
            {createOnly && !routeCommunity && <Input aria-label="Community slug" value={slug} onChange={(event) => setSlug(sanitizeCommunitySlug(event.target.value))} placeholder="community-slug" required />}
            <Input aria-label="Team name" value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Signal Desk" required />
            <Textarea
                aria-label="Team description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="What this lens stands for — include how you moderate (e.g. hide spam, keep adult content, no brigading)"
            />
            {error && <ErrorText>{error}</ErrorText>}
            <Button type="submit" disabled={!!pending}>
                {getStatus('create_curation_team', community, 0, '', 'Creating team…') || 'Create curator team'}
            </Button>
        </Form>
    </Card>;

    return <Page>
        <Helmet><title>Curator teams | Mirage</title></Helmet>
        <Header>
            <div>
                <h1>{createOnly ? 'Create curator team' : `Curator teams for ${communityLabel(routeCommunity)}`}</h1>
                {!createOnly && <Meta>{teamState.teams.length ? 'Curated' : 'Uncurated'} · {teamState.teams.length} live teams</Meta>}
            </div>
            {!createOnly && <Button to={createPath} size="sm">Create team</Button>}
        </Header>

        {!createOnly && teamState.loading && <Card>Loading curator teams…</Card>}
        {!createOnly && teamState.error && <ErrorText>{teamState.error}</ErrorText>}
        {!createOnly && !teamState.loading && teamState.teams.map((team) => <Card key={team.team_id}>
            <TeamLink to={`/c/${encodeURIComponent(routeCommunity)}/teams/${team.team_id}`}>{team.name}</TeamLink>
            {String(team.team_id) === String(communityState.detail?.default_team?.team_id) && <Meta>Node default</Meta>}
            <Meta>{team.description || 'No description provided.'}</Meta>
            <Meta>{team.subscriber_count} paid subscribers</Meta>
        </Card>)}
        {!createOnly && !teamState.loading && teamState.teams.length === 0 && <Card>
            This community is uncurated. Create a team to publish a description and moderate through your own lens. Posts stay available through the uncensored lens either way.
        </Card>}

        {!viewer && <Card>
            <h2>Create curator team</h2>
            <Meta>Sign in with a paid subscription, then follow this community, to create a competing curator team.</Meta>
            <Button to="/login" size="sm">Sign in</Button>
        </Card>}
        {viewer && paid === null && <Card>Checking subscription…</Card>}
        {viewer && paid === false && <Card>
            <h2>Create curator team</h2>
            <Meta>Only paid subscribers can create a curator team. The chain rejects this for free accounts.</Meta>
            <Button to="/subscription" size="sm">Subscribe</Button>
            {error && <ErrorText>{error}</ErrorText>}
        </Card>}
        {viewer && paid === true && !alreadyCurator && previewSlug && communityState.loading && <Card>Loading community…</Card>}
        {viewer && paid === true && alreadyCurator && <Card>
            <h2>Create curator team</h2>
            <Meta>You already curate {ownTeam?.name || 'a team'} here. The chain allows one membership per community.</Meta>
            {ownTeam && <Button to={`/c/${encodeURIComponent(routeCommunity || previewSlug)}/teams/${ownTeam.team_id}`} size="sm">Open your team</Button>}
        </Card>}
        {viewer && paid === true && !alreadyCurator && previewSlug && communityState.detail && communityState.detail.viewer_joined !== true && <Card>
            <h2>Create curator team</h2>
            <Meta>Follow {communityLabel(previewSlug)} first. The chain will not let you create a team in a community you have not joined.</Meta>
            <Button
                type="button"
                size="sm"
                disabled={joining}
                onClick={async () => {
                    setJoining(true);
                    setError('');
                    const result = await tx.followTopic(previewSlug);
                    setJoining(false);
                    if (!result?.success) {
                        setError(formatError(result));
                        return;
                    }
                    communityState.refresh().catch(() => {});
                }}
            >
                {joining ? 'Following…' : `Follow ${communityLabel(previewSlug)}`}
            </Button>
            {error && <ErrorText>{error}</ErrorText>}
        </Card>}
        {viewer && paid === true && !alreadyCurator && (!previewSlug || communityState.detail?.viewer_joined === true) && createForm}
    </Page>;
}
