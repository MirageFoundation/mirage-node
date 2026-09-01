import styled from 'styled-components';
import { useCreatorEarnings } from '../../../logic/useCreatorEarnings';
import Button from './Button';
import { requireThemeColor } from '../../../utils/themeColor';

const Panel = styled.section`
    display: flex;
    flex-direction: column;
    margin-top: 0.25rem;
`;
const Header = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    padding: 0.75rem 1rem 0.55rem;

    @media (max-width: 600px) {
        padding: 0.75rem 0 0.55rem;
    }
`;
const Title = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    line-height: 1.2;
`;
const Subtitle = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.6rem;
    font-weight: 500;
    line-height: 1.25;
`;
const List = styled.div`
    display: flex;
    flex-direction: column;
    border-top: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
`;
const Row = styled.div`
    display: grid;
    grid-template-columns: ${({ $canClaim }) => ($canClaim ? 'auto 1fr auto' : '1fr auto')};
    gap: 0.6rem;
    align-items: center;
    padding: 0.6rem 1rem;
    border-bottom: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    font-size: 0.72rem;

    @media (max-width: 600px) {
        padding: 0.55rem 0;
    }
`;
const Epoch = styled.div`
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    font-size: 0.78rem;
    font-weight: 600;
`;
const Amount = styled.strong`
    color: ${({ theme }) => requireThemeColor(theme, 'text')};
    font-size: 0.72rem;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
`;
const State = styled.div`
    padding: 1rem;
    color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};
    font-size: 0.7rem;
    font-weight: 500;

    @media (max-width: 600px) {
        padding: 1rem 0;
    }
`;
const Actions = styled.div`
    display: flex;
    justify-content: flex-end;
    padding: 0.65rem 1rem 0;

    @media (max-width: 600px) {
        padding: 0.65rem 0 0;
    }
`;
const Meta = styled.div`font-size: 0.68rem; color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};`;
const ErrorText = styled.div`
    padding: 1rem;
    color: ${({ theme }) => requireThemeColor(theme, 'voteDown')};
    font-size: 0.7rem;

    @media (max-width: 600px) {
        padding: 1rem 0;
    }
`;

function formatMirage(umirage) {
    const amount = BigInt(umirage);
    const whole = amount / 1000000n;
    const fraction = String(amount % 1000000n).padStart(6, '0').replace(/0+$/, '');
    return `${whole}${fraction ? `.${fraction}` : ''} MIRAGE`;
}

export function formatCreatorRewardTime(unixSeconds, epochSeconds) {
    const timestamp = Number(unixSeconds);
    const interval = Number(epochSeconds);
    if (!Number.isSafeInteger(timestamp) || timestamp <= 0) throw new Error(`Invalid reward time: ${unixSeconds}`);
    if (!Number.isSafeInteger(interval) || interval <= 0) throw new Error(`Invalid reward interval: ${epochSeconds}`);
    const options = {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        timeZone: 'UTC',
    };
    if (interval < 86400) {
        options.hour = 'numeric';
        options.minute = '2-digit';
        options.timeZoneName = 'short';
    }
    return new Intl.DateTimeFormat(undefined, options).format(new Date(timestamp * 1000));
}

export default function CreatorEarningsPanel({ creator, canClaim = false }) {
    const earnings = useCreatorEarnings(creator);
    return <Panel>
        <Header>
            <Title>Creator earnings</Title>
            <Subtitle>MIRAGE rewards allocated to this creator. Each row shows when they were earned and when they expire.</Subtitle>
        </Header>
        <List>
            {earnings.loading && <State>Loading earnings…</State>}
            {!earnings.loading && !earnings.error && earnings.items.length === 0 && (
                <State>No creator earnings yet.</State>
            )}
            {earnings.items.map((item) => {
                const claimable = earnings.claimable.some((entry) => Number(entry.epoch_id) === Number(item.epoch_id));
                const remaining = BigInt(item.earned) - BigInt(item.claimed);
                const claimed = item.claimed_height != null || remaining <= 0n;
                const expired = Math.floor(Date.now() / 1000) >= Number(item.claim_deadline_unix);
                const deadline = formatCreatorRewardTime(item.claim_deadline_unix, earnings.creatorEpochSeconds);
                const status = claimed
                    ? (item.claimed_height == null ? 'Claimed' : `Claimed at height ${item.claimed_height}`)
                    : expired ? `Expired ${deadline}` : `Claim before ${deadline}`;
                return <Row key={item.epoch_id} $canClaim={canClaim}>
                    {canClaim && <input
                        type="checkbox"
                        checked={earnings.selected.includes(Number(item.epoch_id))}
                        disabled={!claimable || earnings.pending}
                        onChange={() => earnings.toggleEpoch(item.epoch_id)}
                    />}
                    <Epoch>
                        {formatCreatorRewardTime(item.epoch_start_unix, earnings.creatorEpochSeconds)}
                        <Meta>{status}</Meta>
                    </Epoch>
                    <Amount>{formatMirage(remaining)}</Amount>
                </Row>;
            })}
            {earnings.error && <ErrorText>{earnings.error}</ErrorText>}
        </List>
        {canClaim && earnings.items.length > 0 && <Actions>
            <Button
                size="sm"
                disabled={!earnings.selected.length || earnings.pending}
                onClick={() => earnings.claim().catch(() => { })}
            >
                {earnings.pendingStatus || `Claim ${earnings.selected.length || ''} reward${earnings.selected.length === 1 ? '' : 's'}`}
            </Button>
        </Actions>}
    </Panel>;
}
