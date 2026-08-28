import styled from 'styled-components';
import { currentCreatorEpoch, useCreatorEarnings } from '../../../logic/useCreatorEarnings';
import Button from './Button';
import { requireThemeColor } from '../../../utils/themeColor';

const Panel = styled.section`
    padding: 0.85rem; border: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    border-radius: 10px; background: ${({ theme }) => requireThemeColor(theme, 'panel')};
`;
const Row = styled.label`
    display: grid; grid-template-columns: auto 1fr auto; gap: 0.6rem; align-items: center;
    padding: 0.55rem 0; border-bottom: 1px solid ${({ theme }) => requireThemeColor(theme, 'border')};
    font-size: 0.72rem;
`;
const Meta = styled.div`font-size: 0.68rem; color: ${({ theme }) => requireThemeColor(theme, 'subtleText')};`;
const ErrorText = styled.div`font-size: 0.7rem; color: ${({ theme }) => requireThemeColor(theme, 'voteDown')}; margin-top: 0.5rem;`;

function formatMirage(umirage) {
    const amount = BigInt(umirage);
    const whole = amount / 1000000n;
    const fraction = String(amount % 1000000n).padStart(6, '0').replace(/0+$/, '');
    return `${whole}${fraction ? `.${fraction}` : ''} MIRAGE`;
}

export default function CreatorEarningsPanel({ creator }) {
    const earnings = useCreatorEarnings(creator);
    return <Panel>
        <h2>Creator earnings</h2>
        <Meta>Rewards expire if they are not claimed before the deadline shown for each epoch.</Meta>
        {earnings.loading && <Meta>Loading earnings…</Meta>}
        {!earnings.loading && earnings.items.length === 0 && <Meta>No creator earnings yet.</Meta>}
        {earnings.items.map((item) => {
            const claimable = earnings.claimable.some((entry) => Number(entry.epoch_id) === Number(item.epoch_id));
            const remaining = BigInt(item.earned) - BigInt(item.claimed);
            const claimed = item.claimed_height != null || remaining <= 0n;
            const expired = currentCreatorEpoch() >= Number(item.claim_deadline_epoch);
            const status = claimed
                ? (item.claimed_height == null ? 'Claimed' : `Claimed at height ${item.claimed_height}`)
                : expired ? 'Expired' : `Claim by epoch ${item.claim_deadline_epoch}`;
            return <Row key={item.epoch_id}>
                <input
                    type="checkbox"
                    checked={earnings.selected.includes(Number(item.epoch_id))}
                    disabled={!claimable || earnings.pending}
                    onChange={() => earnings.toggleEpoch(item.epoch_id)}
                />
                <span>
                    Epoch {item.epoch_id}
                    <Meta>{status}</Meta>
                </span>
                <strong>{formatMirage(remaining)}</strong>
            </Row>;
        })}
        <Button
            size="sm"
            disabled={!earnings.selected.length || earnings.pending}
            onClick={() => earnings.claim().catch(() => {})}
            style={{ marginTop: '0.65rem' }}
        >
            {earnings.pendingStatus || `Claim ${earnings.selected.length || ''} epoch${earnings.selected.length === 1 ? '' : 's'}`}
        </Button>
        {earnings.error && <ErrorText>{earnings.error}</ErrorText>}
    </Panel>;
}
