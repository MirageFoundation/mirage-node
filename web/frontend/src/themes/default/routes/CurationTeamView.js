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

const Page = styled.main`
    max-width: 820px;
    margin: 0 auto;
    padding: 0.75rem 1rem 1.5rem;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    font-size: 0.75rem;
    line-height: 1.45;
`;
const BackLink = styled(Link)`
    display: block;
    min-width: 0;
    margin-bottom: 0.45rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: ${({ theme }) => requireThemeColor(theme, 'link')};
    font-size: 0.65rem;
    font-weight: 500;
    text-decoration: none;
    &:hover { text-decoration: underline; }
`;
const Title = styled.h1`
    margin: 0;
    font-size: 1.05rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    line-height: 1.25;
    overflow-wrap: anywhere;
`;
const Card = styled.section`
    display: grid;
    gap: 0.4rem;
    padding: 0.7rem 0.75rem;
    margin-top: 0.65rem;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 10px;
    background: ${({ theme }) => requireThemeColor(theme, 'panel')};
`;
const CardTitle = styled.h2`
    margin: 0;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    line-height: 1.3;
`;
const Row = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.6rem;
    padding: 0.35rem 0;
    flex-wrap: wrap;
    font-size: 0.75rem;
`;
const Actions = styled.div`display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;`;
const Form = styled.form`display: grid; gap: 0.5rem; margin-top: 0.15rem;`;
const Input = styled.input`
    padding: 0.45rem 0.55rem; border-radius: 7px; border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')}; color: inherit;
    font: inherit; font-size: 0.75rem;
`;
const Textarea = styled.textarea`
    min-height: 4.5rem; padding: 0.45rem 0.55rem; border-radius: 7px; resize: vertical;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')}; color: inherit;
    font: inherit; font-size: 0.75rem; line-height: 1.4;
`;
const Meta = styled.div`font-size: 0.65rem; line-height: 1.45; color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};`;
const ErrorText = styled.div`color: ${({ theme }) => requireThemeColor(theme, 'voteDown')}; font-size: 0.65rem;`;
const Body = styled.p`margin: 0; font-size: 0.75rem; line-height: 1.45;`;

export default function CurationTeamView() {
    const { topic: community, teamId } = useParams();
    const viewer = String(Storage.load('publicKey', '') || '').toLowerCase();
    const { team, loading, error: loadError } = useCurationTeam(community, teamId, viewer);
    const { detail: communityDetail } = useCommunityDetail(community, viewer);
    const { getInfo, getStatus } = usePendingCuration();
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
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
        return run(() => tx.updateCurationTeam(community, Number(teamId), name, description));
    };

    if (loading) return <Page>Loading curator team…</Page>;
    if (loadError || !team) return <Page><ErrorText>{loadError || 'Curator team not found.'}</ErrorText></Page>;

    const communityName = communityLabel(community);

    return <Page>
        <Helmet><title>{team.name} · {communityName} | Mirage</title></Helmet>
        <BackLink to={`/c/${encodeURIComponent(community)}/teams`} title={`${communityName} teams`}>
            ← Back to teams
        </BackLink>
        <Title>{team.name}</Title>
        {team.deleted && <ErrorText>This curator team has been deleted.</ErrorText>}
        <Meta>{String(team.team_id) === String(communityDetail?.default_team?.team_id) ? 'Node default · ' : ''}{team.subscriber_count} paid subscribers</Meta>
        <Card>
            <CardTitle>About</CardTitle>
            <Body>{team.description || 'No description provided.'}</Body>
            <Meta>Leader: {team.owner}</Meta>
        </Card>

        {!team.deleted && myInvitation && <Card>
            <CardTitle>Team invitation</CardTitle>
            <Body>The leader invited you to join this curator team.</Body>
            <Actions>
                <Button size="xs" disabled={!!getInfo('accept_curator_invite', community, Number(teamId), viewer)} onClick={() => run(() => tx.respondCurationTeamInvitation(community, Number(teamId), true))}>
                    {getStatus('accept_curator_invite', community, Number(teamId), viewer, 'Accepting…') || 'Accept'}
                </Button>
                <Button size="xs" variant="subtle" disabled={!!getInfo('decline_curator_invite', community, Number(teamId), viewer)} onClick={() => run(() => tx.respondCurationTeamInvitation(community, Number(teamId), false))}>
                    {getStatus('decline_curator_invite', community, Number(teamId), viewer, 'Declining…') || 'Decline'}
                </Button>
            </Actions>
        </Card>}

        <Card>
            <CardTitle>Curators ({members.length})</CardTitle>
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
                <Button type="submit" size="xs" disabled={!!pendingFor('invite_curator', invitee.trim().toLowerCase())}>
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
            <CardTitle>Team settings</CardTitle>
            <Form onSubmit={saveProfile}>
                <Input value={name} onChange={(event) => setName(event.target.value)} placeholder={team.name || 'e.g. Signal Desk'} aria-label="Team name" />
                <Textarea
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder={team.description || 'What this lens stands for — include how you moderate'}
                    aria-label="Team description"
                />
                <Button type="submit" size="xs" disabled={!!pendingFor('set_curation_team_profile')}>
                    {statusFor('set_curation_team_profile', '', 'Saving…') || 'Save team profile'}
                </Button>
            </Form>
            <Row>
                <span>Subscriber-only posting</span>
                <Button size="xs" variant="subtle" disabled={!!pendingFor('set_curation_subscriber_only')} onClick={() => run(() => tx.setCurationSubscriberOnly(community, Number(teamId), !team.subscriber_only))}>
                    {statusFor('set_curation_subscriber_only', '', 'Updating…') || (team.subscriber_only ? 'Disable' : 'Enable')}
                </Button>
            </Row>
            <Button size="xs" variant="danger" disabled={!!pendingFor('delete_curation_team')} onClick={() => {
                if (window.confirm('Delete this curator team? Posts in the community will remain available.')) {
                    run(() => tx.deleteCurationTeam(community, Number(teamId)));
                }
            }}>{statusFor('delete_curation_team', '', 'Deleting…') || 'Delete team'}</Button>
        </Card>}

        {isCurator && <Card>
            <CardTitle>Moderation tools</CardTitle>
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
