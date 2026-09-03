import { Link } from 'react-router-dom';
import styled from 'styled-components';
import { HiSparkles } from 'react-icons/hi2';
import * as tx from '../../../utils/tx';
import { communityLabel } from '../../../utils/community';
import { formatError } from '../../../utils/errorMessages';
import { curatorInviteHeroCopy } from '../../../utils/curation';
import { useViewerPendingCuratorInvites } from '../../../logic/useViewerCuratorMembership';
import { usePendingCuration } from '../../../logic/usePendingCuration';
import { requireThemeColor } from '../../../utils/themeColor';
import Storage from '../../../utils/Storage';

const Card = styled.div`
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
    align-self: flex-start;
    margin: 4px 0;
    background: ${({ theme }) => theme.name === 'light'
        ? 'rgba(102, 126, 234, 0.08)'
        : 'rgba(102, 126, 234, 0.14)'};
    border: 1px solid ${({ theme }) => requireThemeColor(theme, 'gradientStart')};
    border-radius: 8px;
    padding: 0.75rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    overflow: hidden;

    @media (max-width: 600px) {
        border-radius: 6px;
        padding: 0.65rem 0.85rem;
    }
`;

const Header = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-width: 0;
`;

const IconTile = styled.div`
    flex-shrink: 0;
    width: 24px;
    height: 24px;
    border-radius: 7px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    background: ${({ theme }) => requireThemeColor(theme, 'gradient')};

    svg {
        width: 0.8rem;
        height: 0.8rem;
    }
`;

const Title = styled.div`
    font-size: 0.78rem;
    font-weight: 600;
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    line-height: 1.2;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const Description = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.68rem;
    line-height: 1.5;
`;

const Buttons = styled.div`
    display: flex;
    gap: 0.5rem;
    margin-top: 0.15rem;
    flex-wrap: wrap;

    @media (max-width: 600px) {
        gap: 0.4rem;
    }
`;

const HeroButton = styled.button`
    padding: 0.4rem 0.9rem;
    border-radius: 7px;
    font-size: 0.7rem;
    font-weight: 600;
    font-family: inherit;
    cursor: pointer;
    transition: transform 0.15s ease, opacity 0.15s ease, box-shadow 0.15s ease;
    line-height: 1.2;
    display: inline-flex;
    align-items: center;
    justify-content: center;

    &:disabled {
        opacity: 0.6;
        cursor: not-allowed;
        transform: none;
    }

    &:focus-visible {
        outline: 2px solid ${({ theme }) => requireThemeColor(theme, 'focusBlue')};
        outline-offset: 2px;
    }

    @media (max-width: 600px) {
        padding: 0.4rem 0.75rem;
        flex: 1;
        min-width: 80px;
    }

    ${({ $variant, theme }) => $variant === 'accept' ? `
        background: ${requireThemeColor(theme, 'gradient')};
        color: #ffffff;
        border: 1px solid transparent;
        box-shadow: 0 1px 5px rgba(102, 126, 234, 0.28);
        &:hover:not(:disabled) {
            transform: translateY(-1px);
            box-shadow: 0 2px 8px rgba(102, 126, 234, 0.36);
        }
    ` : `
        background: transparent;
        color: ${requireThemeColor(theme, 'text')};
        border: 1px solid ${requireThemeColor(theme, 'borderStrong')};
        &:hover:not(:disabled) {
            transform: translateY(-1px);
            background: ${requireThemeColor(theme, 'hoverBg')};
        }
    `}
`;

const Note = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.6rem;
    line-height: 1.4;
`;

const TeamLink = styled(Link)`
    color: inherit;
    text-decoration: underline;
`;

function InviteCard({ invite, getInfo, getStatus, onRespond }) {
    const viewer = String(Storage.load('publicKey', '') || '').toLowerCase();
    const copy = curatorInviteHeroCopy({
        community: invite.community,
        name: invite.name,
        inviterUsername: invite.inviterUsername,
        inviter: invite.inviter,
    });
    const teamPath = `/c/${encodeURIComponent(invite.community)}/teams/${invite.teamId}`;
    const accepting = !!getInfo('accept_curator_invite', invite.community, invite.teamId, viewer);
    const declining = !!getInfo('decline_curator_invite', invite.community, invite.teamId, viewer);
    const busy = accepting || declining;

    return (
        <Card role="region" aria-label={`Curator invitation for ${communityLabel(invite.community)}`}>
            <Header>
                <IconTile aria-hidden="true">
                    <HiSparkles />
                </IconTile>
                <Title>{copy.title}</Title>
            </Header>
            <Description>{copy.body}</Description>
            <Buttons>
                <HeroButton
                    type="button"
                    $variant="accept"
                    disabled={busy}
                    onClick={() => onRespond(invite, true)}
                >
                    {getStatus('accept_curator_invite', invite.community, invite.teamId, viewer, 'Accepting…') || 'Accept invite'}
                </HeroButton>
                <HeroButton
                    type="button"
                    $variant="decline"
                    disabled={busy}
                    onClick={() => onRespond(invite, false)}
                >
                    {getStatus('decline_curator_invite', invite.community, invite.teamId, viewer, 'Declining…') || 'Decline'}
                </HeroButton>
            </Buttons>
            <Note>
                You can also open the{' '}
                <TeamLink to={teamPath}>{invite.name}</TeamLink>
                {' '}team page.
            </Note>
        </Card>
    );
}

export default function CuratorInviteHero() {
    const { invites, dismiss, restore } = useViewerPendingCuratorInvites();
    const { getInfo, getStatus } = usePendingCuration();

    const respond = async (invite, accept) => {
        dismiss(invite.community, invite.teamId);
        console.debug('[curation] invite hero respond', {
            community: invite.community,
            teamId: invite.teamId,
            accept,
        });
        try {
            const result = await tx.respondCurationTeamInvitation(
                invite.community,
                invite.teamId,
                accept,
            );
            if (!result?.success) {
                restore(invite);
                console.error('[curation] invite hero respond failed', {
                    community: invite.community,
                    teamId: invite.teamId,
                    accept,
                    error: formatError(result),
                });
            }
        } catch (err) {
            restore(invite);
            console.error('[curation] invite hero respond failed', {
                community: invite.community,
                teamId: invite.teamId,
                accept,
                error: formatError(err),
            });
        }
    };

    if (!invites.length) return null;

    return (
        <>
            {invites.map((invite) => (
                <InviteCard
                    key={`${invite.community}:${invite.teamId}`}
                    invite={invite}
                    getInfo={getInfo}
                    getStatus={getStatus}
                    onRespond={respond}
                />
            ))}
        </>
    );
}
