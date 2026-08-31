import { useEffect, useMemo, useRef, useState } from 'react';
import styled from 'styled-components';
import { Helmet } from 'react-helmet-async';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import Storage from '../../../utils/Storage';
import * as tx from '../../../utils/tx';
import { communityLabel } from '../../../utils/community';
import { formatError } from '../../../utils/errorMessages';
import {
    CURATION_TEAM_DESCRIPTION_EXAMPLE,
    MAX_CURATION_TEAM_DESCRIPTION_LENGTH,
    MAX_CURATION_TEAM_NAME_LENGTH,
    formatSubscriberCount,
    invalidateCurationReads,
    runeLength,
    sliceRunes,
    waitForCurationTeamGone,
    waitForCurationTeamProfile,
} from '../../../utils/curation';
import { formatUserLabel, resolveUserIdentity } from '../../../utils/UsernameCache';
import {
    useCurationTeam,
    useHiddenCurationPosts,
    useHiddenCurationUsers,
} from '../../../logic/useCurationTeams';
import { usePendingCuration } from '../../../logic/usePendingCuration';
import { TAG_OPTIONS } from '../../../logic/useCreatePost';
import Button from '../components/Button';
import ConfirmDialog from '../components/ConfirmDialog';
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
const DangerCard = styled(Card)`
    border-color: ${({ theme }) => requireThemeColor(theme, 'buttonDangerBorder')};
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
const Field = styled.label`
    display: grid;
    gap: 0.25rem;
`;
const FieldHeader = styled.span`
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
`;
const FieldLabel = styled.span`
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    font-size: 0.68rem;
    font-weight: 600;
`;
const SettingRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding-top: 0.15rem;
`;
const SettingCopy = styled.div`
    display: grid;
    gap: 0.15rem;
    min-width: 0;
`;
const SettingTitle = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    font-size: 0.75rem;
    font-weight: 600;
`;
/** Primary actions: content-width, right-aligned on desktop; full-width on mobile. */
const FormActions = styled.div`
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.4rem;
    flex-wrap: wrap;

    @media (max-width: 600px) {
        flex-direction: column;
        align-items: stretch;
        & > * {
            width: 100%;
        }
    }
`;
const Input = styled.input.attrs({
    autoComplete: 'off',
    'data-bwignore': 'true',
    'data-1p-ignore': 'true',
    'data-lpignore': 'true',
})`
    box-sizing: border-box; width: 100%;
    padding: 0.45rem 0.55rem; border-radius: 7px; border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')}; color: inherit;
    font: inherit; font-size: 0.75rem;
`;
const Textarea = styled.textarea.attrs({
    autoComplete: 'off',
    'data-bwignore': 'true',
    'data-1p-ignore': 'true',
    'data-lpignore': 'true',
})`
    box-sizing: border-box; width: 100%;
    /* Tall enough to show the full 800-char team description without scrolling */
    min-height: 16rem; padding: 0.45rem 0.55rem; border-radius: 7px; resize: vertical;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')}; color: inherit;
    font: inherit; font-size: 0.75rem; line-height: 1.4;
`;
const Select = styled.select`
    padding: 0.3rem 0.4rem; border-radius: 7px;
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    background: ${({ theme }) => requireThemeColor(theme, 'inputBackground')}; color: inherit;
    font: inherit; font-size: 0.7rem; cursor: pointer;
`;
const Meta = styled.div`font-size: 0.65rem; line-height: 1.45; color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};`;
const ErrorText = styled.div`color: ${({ theme }) => requireThemeColor(theme, 'voteDown')}; font-size: 0.65rem;`;
const Body = styled.p`
    margin: 0;
    font-size: 0.75rem;
    line-height: 1.45;
    white-space: pre-line;
    overflow-wrap: anywhere;
    word-break: break-word;
    min-width: 0;
`;
const ItemLink = styled(Link)`
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: ${({ theme }) => requireThemeColor(theme, 'link')};
    text-decoration: none;
    &:hover { text-decoration: underline; }
`;
const ItemLabel = styled.span`
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

export default function CurationTeamView() {
    const { topic: community, teamId } = useParams();
    const location = useLocation();
    const navigate = useNavigate();
    const viewer = String(Storage.load('publicKey', '') || '').toLowerCase();
    const { team, loading, error: loadError, refresh: refreshTeam } = useCurationTeam(community, teamId, viewer);
    const { getInfo, getStatus } = usePendingCuration();
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [profileStatus, setProfileStatus] = useState('idle');
    const [deleteStatus, setDeleteStatus] = useState('idle');
    const [confirmDelete, setConfirmDelete] = useState(false);
    const savedProfileRef = useRef(null);
    const [invitee, setInvitee] = useState('');
    const [inviteBusy, setInviteBusy] = useState(false);
    const [error, setError] = useState('');
    const [optimisticTag, setOptimisticTag] = useState(null);
    const members = useMemo(() => team?.members || [], [team]);
    const invitations = useMemo(
        () => (team?.invitations || []).filter((invitation) => invitation.status === 0),
        [team],
    );
    const isLeader = !team?.deleted && team?.owner === viewer;
    const isCurator = useMemo(
        () => !team?.deleted && members.some((member) => String(member.address || '').toLowerCase() === viewer),
        [members, team?.deleted, viewer],
    );
    const hiddenUsers = useHiddenCurationUsers(community, teamId, {
        viewer,
        enabled: isCurator,
    });
    const hiddenPosts = useHiddenCurationPosts(community, teamId, {
        viewer,
        enabled: isCurator,
    });
    const myInvitation = invitations.find((invite) => invite.address === viewer);

    useEffect(() => {
        if (!team) return;
        // A refetch triggered by our own save can beat the indexer, and that read
        // still carries the previous profile. Reseeding from it would put the old
        // text back under the user right after they saved.
        const saved = savedProfileRef.current;
        if (saved) {
            if (team.name !== saved.name || team.description !== saved.description) return;
            savedProfileRef.current = null;
            console.debug('[curation] team profile caught up', { community, teamId });
        }
        setName(team.name);
        setDescription(team.description);
    }, [community, team, teamId]);

    useEffect(() => {
        if (optimisticTag === null || !team) return undefined;
        if ((team.tag || '') === optimisticTag) {
            setOptimisticTag(null);
            console.debug('[curation] community tag caught up', { community, teamId, tag: optimisticTag });
        }
        return undefined;
    }, [community, optimisticTag, team, teamId]);

    useEffect(() => {
        if (!isCurator || location.hash !== '#hidden-users') return undefined;
        const el = document.getElementById('hidden-users');
        if (!el) return undefined;
        el.scrollIntoView({ block: 'start', behavior: 'smooth' });
        console.debug('[curation] scrolled to hidden users', { community, teamId });
        return undefined;
    }, [community, isCurator, location.hash, teamId]);

    const run = async (operation) => {
        setError('');
        const result = await operation();
        if (!result?.success) setError(formatError(result));
        return result;
    };
    const pendingFor = (action, target = '') => getInfo(action, community, Number(teamId), target);
    const statusFor = (action, target, fallback) => getStatus(action, community, Number(teamId), target, fallback);
    const maxTeamNameLength = MAX_CURATION_TEAM_NAME_LENGTH;
    const maxTeamDescriptionLength = MAX_CURATION_TEAM_DESCRIPTION_LENGTH;
    const saveProfile = async (event) => {
        event.preventDefault();
        const trimmedName = name.trim();
        if (!trimmedName) {
            setError('Team name is required.');
            return undefined;
        }
        if (runeLength(trimmedName) > maxTeamNameLength) {
            setError(`Team name too long. Maximum ${maxTeamNameLength} characters.`);
            console.error('[curation] update team name too long', {
                length: runeLength(trimmedName),
                max: maxTeamNameLength,
            });
            return undefined;
        }
        if (runeLength(description) > maxTeamDescriptionLength) {
            setError(`Description too long. Maximum ${maxTeamDescriptionLength} characters.`);
            console.error('[curation] update team description too long', {
                length: runeLength(description),
                max: maxTeamDescriptionLength,
            });
            return undefined;
        }
        // Same staged wait as team creation: confirm the tx, then confirm the API
        // serves the new profile before letting the form reseed from a read.
        savedProfileRef.current = { name: trimmedName, description };
        setProfileStatus('saving');
        const abandon = (message) => {
            savedProfileRef.current = null;
            setProfileStatus('idle');
            if (message) setError(message);
            return undefined;
        };
        try {
            const result = await run(() => tx.updateCurationTeam(community, Number(teamId), trimmedName, description));
            if (!result?.success) return abandon('');
            const txHash = result.tx_hash ? String(result.tx_hash).toLowerCase() : '';
            if (!txHash) {
                console.error('[curation] update team missing tx_hash', { community, teamId });
                return abandon('Team profile saved without a transaction hash.');
            }
            setProfileStatus('verifying');
            console.debug('[curation] update team verifying', { community, teamId, txHash: txHash.slice(0, 12) });
            const pollResult = await tx.pollTxStatus(txHash);
            if (!pollResult) return abandon('Team profile timed out waiting for confirmation.');
            if (!pollResult.success) {
                return abandon(pollResult.error_details?.message || 'Transaction rejected');
            }
            const visible = await waitForCurationTeamProfile(
                community,
                Number(teamId),
                trimmedName,
                description,
                { viewer },
            );
            setProfileStatus('idle');
            if (!visible) {
                // The tx is on chain, so keep showing what was saved rather than
                // reverting to a stale read the indexer is about to replace.
                console.error('[curation] update team not visible after index', { community, teamId });
                setError('Profile saved but is not visible yet. Refresh in a moment.');
                return undefined;
            }
            await refreshTeam().catch(() => { });
            console.debug('[curation] update team ready', { community, teamId });
            return result;
        } catch (err) {
            const message = formatError(err);
            console.error('[curation] update team failed', { community, teamId, error: message });
            return abandon(message);
        }
    };
    const deleteTeam = async () => {
        setDeleteStatus('deleting');
        const abandon = (message) => {
            setDeleteStatus('idle');
            if (message) setError(message);
        };
        try {
            const result = await run(() => tx.deleteCurationTeam(community, Number(teamId)));
            if (!result?.success) return abandon('');
            const txHash = result.tx_hash ? String(result.tx_hash).toLowerCase() : '';
            if (!txHash) {
                console.error('[curation] delete team missing tx_hash', { community, teamId });
                return abandon('Team deletion submitted without a transaction hash.');
            }
            setDeleteStatus('verifying');
            console.debug('[curation] delete team verifying', { community, teamId, txHash: txHash.slice(0, 12) });
            const pollResult = await tx.pollTxStatus(txHash);
            if (!pollResult) return abandon('Team deletion timed out waiting for confirmation.');
            if (!pollResult.success) {
                return abandon(pollResult.error_details?.message || 'Transaction rejected');
            }
            setConfirmDelete(false);
            // The indexer drops the team a moment after the tx lands. Refresh
            // curation reads only once it has, so the sidebar's curator highlight
            // clears on its own instead of surviving until a full reload.
            waitForCurationTeamGone(community, Number(teamId), { viewer })
                .then(() => invalidateCurationReads(community))
                .catch(() => { });
            console.debug('[curation] delete team done, leaving team page', { community, teamId });
            navigate(`/c/${encodeURIComponent(community)}`);
            return undefined;
        } catch (err) {
            const message = formatError(err);
            console.error('[curation] delete team failed', { community, teamId, error: message });
            return abandon(message);
        }
    };
    const submitInvite = async (event) => {
        event.preventDefault();
        const raw = invitee.trim();
        if (!raw) {
            setError('Enter a username or mirage1 address.');
            return;
        }
        setError('');
        setInviteBusy(true);
        try {
            const identity = await resolveUserIdentity(raw);
            console.debug('[curation] invite curator', {
                community,
                teamId: Number(teamId),
                kind: identity.kind,
                address: identity.address.slice(0, 12),
                username: identity.username,
            });
            const result = await run(() => tx.inviteCurationTeamMember(
                community,
                Number(teamId),
                identity.address,
            ));
            if (result?.success) setInvitee('');
        } catch (err) {
            const message = err instanceof Error ? err.message : formatError(err);
            setError(message);
            console.error('[curation] invite resolve failed', { error: message });
        } finally {
            setInviteBusy(false);
        }
    };

    if (loading) return <Page>Loading curator team…</Page>;
    if (loadError || !team) return <Page><ErrorText>{loadError || 'Curator team not found.'}</ErrorText></Page>;

    const communityName = communityLabel(community);
    const displayTag = optimisticTag !== null ? optimisticTag : (team.tag || '');

    return <Page>
        <Helmet><title>{team.name} · {communityName} | Mirage</title></Helmet>
        <BackLink to={`/c/${encodeURIComponent(community)}`} title={communityName}>
            ← Back to community
        </BackLink>
        <Title>{team.name}</Title>
        {team.deleted && <ErrorText>This curator team has been deleted.</ErrorText>}
        <Meta>{formatSubscriberCount(Number(team.subscriber_count))}</Meta>
        {error && <ErrorText role="alert">{error}</ErrorText>}

        {isLeader ? (
            <>
                <Card>
                    <CardTitle>Team profile</CardTitle>
                    <Meta>Set the name and explain how your team curates this community.</Meta>
                    <Form onSubmit={saveProfile}>
                        <Field>
                            <FieldHeader>
                                <FieldLabel>Team name</FieldLabel>
                                <Meta>{runeLength(name)} / {maxTeamNameLength}</Meta>
                            </FieldHeader>
                            <Input
                                value={name}
                                onChange={(event) => setName(sliceRunes(event.target.value, maxTeamNameLength))}
                                placeholder={team.name || 'e.g. Signal Desk'}
                                maxLength={maxTeamNameLength}
                            />
                        </Field>
                        <Field>
                            <FieldHeader>
                                <FieldLabel>Community header description</FieldLabel>
                                <Meta>{runeLength(description)} / {maxTeamDescriptionLength}</Meta>
                            </FieldHeader>
                            <Meta>Shown beneath your team name when users choose your curation team.</Meta>
                            <Textarea
                                value={description}
                                onChange={(event) => setDescription(sliceRunes(event.target.value, maxTeamDescriptionLength))}
                                placeholder={CURATION_TEAM_DESCRIPTION_EXAMPLE}
                                maxLength={maxTeamDescriptionLength}
                            />
                        </Field>
                        <FormActions>
                            <Button
                                type="submit"
                                size="xs"
                                disabled={profileStatus !== 'idle' || !!pendingFor('set_curation_team_profile')}
                            >
                                {profileStatus === 'verifying'
                                    ? 'Verifying…'
                                    : (statusFor('set_curation_team_profile', '', 'Saving…')
                                        || (profileStatus === 'saving' ? 'Saving…' : 'Save team profile'))}
                            </Button>
                        </FormActions>
                    </Form>
                </Card>

                <Card>
                    <CardTitle>Community defaults</CardTitle>
                    <SettingRow>
                        <SettingCopy>
                            <SettingTitle>Subscriber-only posting</SettingTitle>
                            <Meta>Require users to be active subscribers when they create a post.</Meta>
                        </SettingCopy>
                        <Button size="xs" variant="subtle" disabled={!!pendingFor('set_curation_subscriber_only')} onClick={() => run(() => tx.setCurationSubscriberOnly(community, Number(teamId), !team.subscriber_only))}>
                            {statusFor('set_curation_subscriber_only', '', 'Updating…') || (team.subscriber_only ? 'Disable' : 'Enable')}
                        </Button>
                    </SettingRow>
                    <SettingRow>
                        <SettingCopy>
                            <SettingTitle>Community tag</SettingTitle>
                            <Meta>
                                Tags every post in this community, overriding what authors set.
                                Curators can still override it on individual posts.
                            </Meta>
                        </SettingCopy>
                        <Select
                            value={displayTag}
                            disabled={!!pendingFor('set_curation_tag')}
                            onChange={async (e) => {
                                const next = e.target.value;
                                setOptimisticTag(next);
                                console.debug('[curation] optimistic community tag', {
                                    community,
                                    teamId,
                                    tag: next,
                                });
                                const result = await run(() => tx.setCurationTag(community, Number(teamId), next));
                                if (!result?.success) {
                                    setOptimisticTag(null);
                                    console.debug('[curation] community tag reverted', {
                                        community,
                                        teamId,
                                        tag: team.tag || '',
                                    });
                                }
                            }}
                        >
                            {TAG_OPTIONS.map(({ value, label }) => (
                                <option key={value} value={value}>{value ? label : 'No community tag'}</option>
                            ))}
                        </Select>
                    </SettingRow>
                    {statusFor('set_curation_tag', '', 'Updating…') ? (
                        <Meta>{statusFor('set_curation_tag', '', 'Updating…')}</Meta>
                    ) : null}
                </Card>
            </>
        ) : (
            <>
                <Card>
                    <CardTitle>Team profile</CardTitle>
                    <Body>{team.description || 'No description provided.'}</Body>
                </Card>
                <Card>
                    <CardTitle>Community defaults</CardTitle>
                    <SettingRow>
                        <SettingCopy>
                            <SettingTitle>Subscriber-only posting</SettingTitle>
                            <Meta>{team.subscriber_only ? 'Enabled' : 'Disabled'}</Meta>
                        </SettingCopy>
                    </SettingRow>
                    <SettingRow>
                        <SettingCopy>
                            <SettingTitle>Community tag</SettingTitle>
                            <Meta>
                                {team.tag
                                    ? (TAG_OPTIONS.find((opt) => opt.value === team.tag)?.label || team.tag)
                                    : 'No community tag'}
                            </Meta>
                        </SettingCopy>
                    </SettingRow>
                </Card>
            </>
        )}

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
                <span title={member.address}>
                    {formatUserLabel(member.username, member.address)}
                    {member.address === team.owner ? ' · leader' : ''}
                </span>
                {isLeader && member.address !== team.owner && <Actions>
                    <Button size="xs" variant="subtle" disabled={!!pendingFor('transfer_curation_team', member.address)} onClick={() => run(() => tx.transferCurationTeamLeadership(community, Number(teamId), member.address))}>
                        {statusFor('transfer_curation_team', member.address, 'Transferring…') || 'Transfer leadership'}
                    </Button>
                    <Button size="xs" variant="danger" disabled={!!pendingFor('remove_curator', member.address)} onClick={() => run(() => tx.removeCurationTeamMember(community, Number(teamId), member.address))}>
                        {statusFor('remove_curator', member.address, 'Removing…') || 'Remove'}
                    </Button>
                </Actions>}
            </Row>)}
            {isLeader && <Form onSubmit={submitInvite}>
                <Input
                    aria-label="Username or address to invite"
                    value={invitee}
                    onChange={(event) => setInvitee(event.target.value)}
                    placeholder="Username or mirage1…"
                    required
                    disabled={inviteBusy}
                />
                <FormActions>
                    <Button type="submit" size="xs" disabled={inviteBusy} aria-busy={inviteBusy}>
                        {inviteBusy ? 'Inviting…' : 'Invite curator'}
                    </Button>
                </FormActions>
            </Form>}
            {invitations.filter((invite) => invite.address !== viewer).map((invite) => <Row key={invite.address}>
                <Meta title={invite.address}>Pending: {formatUserLabel(invite.username, invite.address)}</Meta>
                {isLeader && <Button size="xs" variant="subtle" disabled={!!pendingFor('revoke_curator_invite', invite.address)} onClick={() => run(() => tx.revokeCurationTeamInvitation(community, Number(teamId), invite.address))}>
                    {statusFor('revoke_curator_invite', invite.address, 'Revoking…') || 'Revoke'}
                </Button>}
            </Row>)}
            {isCurator && !isLeader && (
                <FormActions>
                    <Button
                        size="xs"
                        variant="danger"
                        disabled={!!pendingFor('leave_curation_team', viewer)}
                        onClick={() => run(() => tx.leaveCurationTeam(community, Number(teamId)))}
                    >
                        {statusFor('leave_curation_team', viewer, 'Leaving…') || 'Leave team'}
                    </Button>
                </FormActions>
            )}
        </Card>

        {isCurator && (
            <Card id="hidden-users">
                <CardTitle>Hidden users</CardTitle>
                <Meta>Hidden from this team&apos;s feed. Newest first.</Meta>
                {hiddenUsers.loading && hiddenUsers.users.length === 0 && <Meta>Loading hidden users…</Meta>}
                {hiddenUsers.error && <ErrorText>{hiddenUsers.error}</ErrorText>}
                {!hiddenUsers.loading && !hiddenUsers.error && hiddenUsers.users.length === 0 && (
                    <Meta>No hidden users.</Meta>
                )}
                {hiddenUsers.users.map((user) => (
                    <Row key={user.address}>
                        <ItemLabel title={user.address}>
                            {formatUserLabel(user.username, user.address)}
                        </ItemLabel>
                        <Button
                            size="xs"
                            variant="subtle"
                            disabled={!!pendingFor('set_curation_user_hidden', user.address)}
                            onClick={() => run(() => tx.moderateCurationUser(
                                community,
                                Number(teamId),
                                user.address,
                                false,
                            ))}
                        >
                            {statusFor('set_curation_user_hidden', user.address, 'Restoring…') || 'Restore'}
                        </Button>
                    </Row>
                ))}
                {hiddenUsers.hasMore && (
                    <FormActions>
                        <Button
                            size="xs"
                            variant="subtle"
                            disabled={hiddenUsers.loadingMore}
                            onClick={() => {
                                console.debug('[curation] load more hidden users', {
                                    community,
                                    teamId,
                                    loaded: hiddenUsers.users.length,
                                });
                                hiddenUsers.loadMore().catch(() => { });
                            }}
                        >
                            {hiddenUsers.loadingMore ? 'Loading…' : 'Load 50 more'}
                        </Button>
                    </FormActions>
                )}
            </Card>
        )}

        {isCurator && (
            <Card id="hidden-posts">
                <CardTitle>Hidden posts</CardTitle>
                <Meta>Hidden from this team&apos;s feed. Newest first.</Meta>
                {hiddenPosts.loading && hiddenPosts.posts.length === 0 && <Meta>Loading hidden posts…</Meta>}
                {hiddenPosts.error && <ErrorText>{hiddenPosts.error}</ErrorText>}
                {!hiddenPosts.loading && !hiddenPosts.error && hiddenPosts.posts.length === 0 && (
                    <Meta>No hidden posts.</Meta>
                )}
                {hiddenPosts.posts.map((post) => (
                    <Row key={post.postId}>
                        <ItemLink to={`/p/${encodeURIComponent(post.postId)}`} title={post.postId}>
                            {post.title
                                || (post.postId.length <= 24
                                    ? post.postId
                                    : `${post.postId.slice(0, 14)}…${post.postId.slice(-8)}`)}
                        </ItemLink>
                        <Button
                            size="xs"
                            variant="subtle"
                            disabled={!!pendingFor('set_curation_post_hidden', post.postId)}
                            onClick={() => run(() => tx.moderateCurationPost(
                                community,
                                Number(teamId),
                                post.postId,
                                false,
                            ))}
                        >
                            {statusFor('set_curation_post_hidden', post.postId, 'Restoring…') || 'Restore'}
                        </Button>
                    </Row>
                ))}
                {hiddenPosts.hasMore && (
                    <FormActions>
                        <Button
                            size="xs"
                            variant="subtle"
                            disabled={hiddenPosts.loadingMore}
                            onClick={() => {
                                console.debug('[curation] load more hidden posts', {
                                    community,
                                    teamId,
                                    loaded: hiddenPosts.posts.length,
                                });
                                hiddenPosts.loadMore().catch(() => { });
                            }}
                        >
                            {hiddenPosts.loadingMore ? 'Loading…' : 'Load 50 more'}
                        </Button>
                    </FormActions>
                )}
            </Card>
        )}

        {isLeader && !team.deleted && (
            <DangerCard>
                <CardTitle>Danger zone</CardTitle>
                <SettingRow>
                    <SettingCopy>
                        <SettingTitle>Delete team</SettingTitle>
                        <Meta>Permanently removes this curator team. Community posts remain available.</Meta>
                    </SettingCopy>
                    <Button
                        size="xs"
                        variant="danger"
                        disabled={deleteStatus !== 'idle' || !!pendingFor('delete_curation_team')}
                        onClick={() => setConfirmDelete(true)}
                    >
                        {deleteStatus === 'verifying'
                            ? 'Verifying…'
                            : (statusFor('delete_curation_team', '', 'Deleting…')
                                || (deleteStatus === 'deleting' ? 'Deleting…' : 'Delete team'))}
                    </Button>
                </SettingRow>
            </DangerCard>
        )}

        <ConfirmDialog
            open={confirmDelete}
            title="Delete this curator team?"
            message="The team and its lens disappear for everyone who reads this community. Posts stay available."
            confirmLabel="Delete team"
            confirmVariant="danger"
            pending={deleteStatus !== 'idle'}
            onConfirm={deleteTeam}
            onCancel={() => setConfirmDelete(false)}
        />

    </Page>;
}
