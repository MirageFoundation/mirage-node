import { useState } from 'react';
import styled from 'styled-components';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Helmet } from 'react-helmet-async';
import Storage from '../../../utils/Storage';
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
    const [policy, setPolicy] = useState('');
    const [error, setError] = useState('');
    const viewer = String(Storage.load('publicKey', '') || '').toLowerCase();
    const community = routeCommunity || sanitizeCommunitySlug(slug);
    const canLoad = Boolean(routeCommunity && isValidCommunitySlug(routeCommunity));
    const teamState = useCurationTeams(routeCommunity, { viewer, enabled: canLoad && !createOnly });
    const communityState = useCommunityDetail(routeCommunity, viewer, canLoad && !createOnly);
    const { getInfo, getStatus } = usePendingCuration();
    const pending = getInfo('create_curation_team', community);

    const submit = async (event) => {
        event.preventDefault();
        const nextSlug = sanitizeCommunitySlug(slug);
        if (!isValidCommunitySlug(nextSlug)) {
            setError('Enter a valid lowercase community slug.');
            return;
        }
        setError('');
        const result = await tx.createCuratorTeam(nextSlug, name, description, policy);
        if (!result?.success) {
            setError(formatError(result));
            return;
        }
        navigate(`/c/${encodeURIComponent(nextSlug)}/teams`);
    };

    return <Page>
        <Helmet><title>Curator teams | Mirage</title></Helmet>
        <Header>
            <div>
                <h1>{createOnly ? 'Create curator team' : `Curator teams for ${communityLabel(routeCommunity)}`}</h1>
                {!createOnly && <Meta>{teamState.teams.length ? 'Curated' : 'Uncurated'} · {teamState.teams.length} live teams</Meta>}
            </div>
            {!createOnly && viewer && <Button to="/curator-teams/new" size="sm">Create team</Button>}
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
            This community is uncurated. Its posts remain available through the uncensored lens.
        </Card>}

        {createOnly && !viewer && <Card>Sign in to create a curator team.</Card>}
        {viewer && (createOnly || !teamState.teams.some((team) => team.owner === viewer)) && <Card>
            <h2>Create curator team</h2>
            <Meta>You become this team&apos;s leader. You must already follow the community and have an active paid subscription.</Meta>
            <Form onSubmit={submit}>
                {createOnly && <Input aria-label="Community slug" value={slug} onChange={(event) => setSlug(sanitizeCommunitySlug(event.target.value))} placeholder="community-slug" required />}
                <Input aria-label="Team name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Team name" required />
                <Textarea aria-label="Team description" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Description" />
                <Textarea aria-label="Team policy" value={policy} onChange={(event) => setPolicy(event.target.value)} placeholder="Moderation policy" />
                {error && <ErrorText>{error}</ErrorText>}
                <Button type="submit" disabled={!!pending}>
                    {getStatus('create_curation_team', community, 0, '', 'Creating team…') || 'Create curator team'}
                </Button>
            </Form>
        </Card>}
    </Page>;
}
