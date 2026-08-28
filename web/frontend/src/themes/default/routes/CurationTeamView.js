import { useEffect, useMemo, useState } from 'react';
import styled from 'styled-components';
import { Helmet } from 'react-helmet-async';
import { Link, useParams } from 'react-router-dom';
import Storage from '../../../utils/Storage';
import * as tx from '../../../utils/tx';
import { communityLabel } from '../../../utils/community';
import { formatError } from '../../../utils/errorMessages';
import { useCurationTeam } from '../../../logic/useCurationTeams';
import { useCommunityDetail } from '../../../logic/useCommunityDetail';
import { usePendingCuration } from '../../../logic/usePendingCuration';
import Button from '../components/Button';
import { requireThemeColor } from '../../../utils/themeColor';

const Page = styled.main`max-width: 820px; margin: 0 auto; padding: 1rem; color: ${({ theme }) => requireThemeColor(theme, 'text')};`;
const Card = styled.section`
    padding: 0.85rem; margin-top: 0.75rem; border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 10px; background: ${({ theme }) => requireThemeColor(theme, 'panel')};
`;
const Row = styled.div`display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; padding: 0.45rem 0; flex-wrap: wrap;`;
const Actions = styled.div`display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;`;
const Form = styled.form`display: grid; gap: 0.55rem; margin-top: 0.6rem;`;
const Input = styled.input`
    padding: 0.5rem; border-radius: 7px; border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')}; color: inherit;
`;
const Textarea = styled.textarea`
    min-height: 4.5rem; padding: 0.5rem; border-radius: 7px; resize: vertical;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')}; color: inherit;
`;
const Meta = styled.div`font-size: 0.7rem; line-height: 1.5; color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};`;
const ErrorText = styled.div`color: ${({ theme }) => requireThemeColor(theme, 'voteDown')}; font-size: 0.7rem;`;

export default function CurationTeamView() {
    const { topic: community, teamId } = useParams();
    const viewer = String(Storage.load('publicKey', '') || '').toLowerCase();
    const { team, loading, error: loadError } = useCurationTeam(community, teamId, viewer);
    const { detail: communityDetail } = useCommunityDetail(community, viewer);
    const { getInfo, getStatus } = usePendingCuration();
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [policy, setPolicy] = useState('');
    const [invitee, setInvitee] = useState('');
    const [moderationTarget, setModerationTarget] = useState('');
    const [error, setError] = useState('');
    const members = useMemo(() => team?.members || [], [team]);
    const invitations = useMemo(
        () => (team?.invitations || []).filter((invitation) => invitation.status === 0),
        [team],
    );
    const isLeader = !team?.deleted && team?.owner === viewer;
    const isCurator = useMemo(
        () => !team?.deleted && members.some((member) => member.address === viewer),
        [members, team?.deleted, viewer],
    );
    const myInvitation = invitations.find((invite) => invite.address === viewer);

    useEffect(() => {
        if (!team) return;
        setName(team.name);
        setDescription(team.description);
        setPolicy(team.policy);
    }, [team]);

    const run = async (operation) => {
        setError('');
        const result = await operation();
        if (!result?.success) setError(formatError(result));
        return result;
    };
    const pendingFor = (action, target = '') => getInfo(action, community, Number(teamId), target);
    const statusFor = (action, target, fallback) => getStatus(action, community, Number(teamId), target, fallback);
    const saveProfile = (event) => {
        event.preventDefault();
        return run(() => tx.updateCurationTeam(community, Number(teamId), name, description, policy));
    };

    if (loading) return <Page>Loading curator team…</Page>;
    if (loadError || !team) return <Page><ErrorText>{loadError || 'Curator team not found.'}</ErrorText></Page>;

    return <Page>
        <Helmet><title>{team.name} · {communityLabel(community)} | Mirage</title></Helmet>
        <Link to={`/c/${encodeURIComponent(community)}/teams`}>← {communityLabel(community)} teams</Link>
        <h1>{team.name}</h1>
        {team.deleted && <ErrorText>This curator team has been deleted.</ErrorText>}
        <Meta>{String(team.team_id) === String(communityDetail?.default_team?.team_id) ? 'Node default · ' : ''}{team.subscriber_count} paid subscribers</Meta>
        <Card>
            <h2>About</h2>
            <p>{team.description || 'No description provided.'}</p>
            <Meta>{team.policy || 'No moderation policy provided.'}</Meta>
            <Meta>Leader: {team.owner}</Meta>
        </Card>

        {!team.deleted && myInvitation && <Card>
            <h2>Team invitation</h2>
            <p>The leader invited you to join this curator team.</p>
            <Actions>
                <Button disabled={!!getInfo('accept_curator_invite', community, Number(teamId), viewer)} onClick={() => run(() => tx.respondCurationTeamInvitation(community, Number(teamId), true))}>
                    {getStatus('accept_curator_invite', community, Number(teamId), viewer, 'Accepting…') || 'Accept'}
                </Button>
                <Button variant="subtle" disabled={!!getInfo('decline_curator_invite', community, Number(teamId), viewer)} onClick={() => run(() => tx.respondCurationTeamInvitation(community, Number(teamId), false))}>
                    {getStatus('decline_curator_invite', community, Number(teamId), viewer, 'Declining…') || 'Decline'}
                </Button>
            </Actions>
        </Card>}

        <Card>
            <h2>Curators ({members.length})</h2>
            {members.map((member) => <Row key={member.address}>
                <span>{member.username || member.address}{member.address === team.owner ? ' · leader' : ''}</span>
                {isLeader && member.address !== team.owner && <Actions>
                    <Button size="xs" variant="subtle" disabled={!!pendingFor('transfer_curation_team', member.address)} onClick={() => run(() => tx.transferCurationTeamLeadership(community, Number(teamId), member.address))}>
                        {statusFor('transfer_curation_team', member.address, 'Transferring…') || 'Transfer leadership'}
                    </Button>
                    <Button size="xs" variant="danger" disabled={!!pendingFor('remove_curator', member.address)} onClick={() => run(() => tx.removeCurationTeamMember(community, Number(teamId), member.address))}>
                        {statusFor('remove_curator', member.address, 'Removing…') || 'Remove'}
                    </Button>
                </Actions>}
            </Row>)}
            {isLeader && <Form onSubmit={(event) => {
                event.preventDefault();
                run(() => tx.inviteCurationTeamMember(community, Number(teamId), invitee)).then((result) => {
                    if (result?.success) setInvitee('');
                });
            }}>
                <Input aria-label="User address to invite" value={invitee} onChange={(event) => setInvitee(event.target.value)} placeholder="mirage1…" required />
                <Button type="submit" disabled={!!pendingFor('invite_curator', invitee.trim().toLowerCase())}>
                    {statusFor('invite_curator', invitee.trim().toLowerCase(), 'Inviting…') || 'Invite curator'}
                </Button>
            </Form>}
            {invitations.filter((invite) => invite.address !== viewer).map((invite) => <Row key={invite.address}>
                <Meta>Pending: {invite.address}</Meta>
                {isLeader && <Button size="xs" variant="subtle" disabled={!!pendingFor('revoke_curator_invite', invite.address)} onClick={() => run(() => tx.revokeCurationTeamInvitation(community, Number(teamId), invite.address))}>
                    {statusFor('revoke_curator_invite', invite.address, 'Revoking…') || 'Revoke'}
                </Button>}
            </Row>)}
            {isCurator && !isLeader && <Button
                size="xs"
                variant="danger"
                disabled={!!pendingFor('leave_curation_team', viewer)}
                onClick={() => run(() => tx.leaveCurationTeam(community, Number(teamId)))}
            >
                {statusFor('leave_curation_team', viewer, 'Leaving…') || 'Leave team'}
            </Button>}
        </Card>

        {isLeader && <Card>
            <h2>Team settings</h2>
            <Form onSubmit={saveProfile}>
                <Input value={name} onChange={(event) => setName(event.target.value)} placeholder={team.name} aria-label="Team name" />
                <Textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder={team.description || 'Description'} aria-label="Team description" />
                <Textarea value={policy} onChange={(event) => setPolicy(event.target.value)} placeholder={team.policy || 'Policy'} aria-label="Team policy" />
                <Button type="submit" disabled={!!pendingFor('set_curation_team_profile')}>
                    {statusFor('set_curation_team_profile', '', 'Saving…') || 'Save team profile'}
                </Button>
            </Form>
            <Row>
                <span>Subscriber-only posting</span>
                <Button size="xs" variant="subtle" disabled={!!pendingFor('set_curation_subscriber_only')} onClick={() => run(() => tx.setCurationSubscriberOnly(community, Number(teamId), !team.subscriber_only))}>
                    {statusFor('set_curation_subscriber_only', '', 'Updating…') || (team.subscriber_only ? 'Disable' : 'Enable')}
                </Button>
            </Row>
            <Button variant="danger" disabled={!!pendingFor('delete_curation_team')} onClick={() => {
                if (window.confirm('Delete this curator team? Posts in the community will remain available.')) {
                    run(() => tx.deleteCurationTeam(community, Number(teamId)));
                }
            }}>{statusFor('delete_curation_team', '', 'Deleting…') || 'Delete team'}</Button>
        </Card>}

        {isCurator && <Card>
            <h2>Moderation tools</h2>
            <Meta>Enter a post hash, thread root hash, or user address, then choose the team-scoped action.</Meta>
            <Form onSubmit={(event) => event.preventDefault()}>
                <Input value={moderationTarget} onChange={(event) => setModerationTarget(event.target.value)} placeholder="Post hash, thread root, or mirage1…" aria-label="Moderation target" />
                <Actions>
                    <Button size="xs" disabled={!!pendingFor('set_curation_post_hidden', moderationTarget.toLowerCase())} onClick={() => run(() => tx.moderateCurationPost(community, Number(teamId), moderationTarget, true))}>
                        {statusFor('set_curation_post_hidden', moderationTarget.toLowerCase(), 'Moderating…') || 'Hide post'}
                    </Button>
                    <Button size="xs" variant="subtle" disabled={!!pendingFor('set_curation_post_hidden', moderationTarget.toLowerCase())} onClick={() => run(() => tx.moderateCurationPost(community, Number(teamId), moderationTarget, false))}>Show post</Button>
                    <Button size="xs" disabled={!!pendingFor('set_curation_user_hidden', moderationTarget.toLowerCase())} onClick={() => run(() => tx.moderateCurationUser(community, Number(teamId), moderationTarget, true))}>
                        {statusFor('set_curation_user_hidden', moderationTarget.toLowerCase(), 'Moderating…') || 'Hide user'}
                    </Button>
                    <Button size="xs" variant="subtle" disabled={!!pendingFor('set_curation_user_hidden', moderationTarget.toLowerCase())} onClick={() => run(() => tx.moderateCurationUser(community, Number(teamId), moderationTarget, false))}>Show user</Button>
                    <Button size="xs" disabled={!!pendingFor('set_curation_thread_locked', moderationTarget.toLowerCase())} onClick={() => run(() => tx.setCurationThreadLocked(community, Number(teamId), moderationTarget, true))}>
                        {statusFor('set_curation_thread_locked', moderationTarget.toLowerCase(), 'Moderating…') || 'Lock thread'}
                    </Button>
                    <Button size="xs" variant="subtle" disabled={!!pendingFor('set_curation_thread_locked', moderationTarget.toLowerCase())} onClick={() => run(() => tx.setCurationThreadLocked(community, Number(teamId), moderationTarget, false))}>Unlock thread</Button>
                </Actions>
            </Form>
        </Card>}
        {error && <ErrorText>{error}</ErrorText>}
    </Page>;
}
