import React, { useEffect, useState } from "react";
import styled from "styled-components";
import ConfirmDialog from "./ConfirmDialog";
import { formatMirageBalance } from "../../../utils/formatters";
import Api from "../../../utils/api";
import Storage from "../../../utils/Storage";

/**
 * GiftDialogs — default modal wrappers for the three "pay something to
 * another user" flows (Gift Mirage, Gift Subscription, Give Award).
 *
 * Each dialog wraps the shared `ConfirmDialog` primitive so the panel
 * surface, overlay, header typography, and Cancel/Confirm footer all
 * match the existing Block/Report modals. The body of each dialog is
 * the only piece that varies:
 *
 *  • GiftMirageDialog       — amount input pill + "MIRAGE" unit +
 *                             insufficient-balance guard.
 *  • GiftSubscriptionDialog — fee + expiry summary card + balance row
 *                             + insufficient-balance guard.
 *  • GiveAwardDialog        — 2-column grid of award tiles (pick then
 *                             Send) with a single insufficient-balance
 *                             callout when the user can't afford ANY
 *                             award. Modal is wider than the others.
 *
 * All three dialogs display the viewer's current MIRAGE balance at the
 * top of the body so the user can eyeball whether they can afford the
 * action before committing, matching the mirage-mobile-app pattern.
 *
 * Rules followed:
 *  - R1 surfaces: inherits ConfirmDialog's `panel` + `overlay`.
 *  - R2 tokens only — no raw hex, all colors from the theme.
 *  - R7 typography: 0.72–0.82rem scale, matches the rest of default.
 */

// ─── Shared primitives ───────────────────────────────────────────────────────

const BalanceRow = styled.div`
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0.5rem 0.7rem;
    background: ${({ theme }) => theme.colors.surface2};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
`;

const BalanceLabel = styled.span`
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.subtleText};
`;

const BalanceValue = styled.span`
    /* Match the AmountInput on the right of the amount row (see below)
     * so the balance value and the amount you're typing feel like the
     * same "numeric field" typographic family. */
    font-size: 0.82rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.text};
    letter-spacing: -0.01em;
    white-space: nowrap;
`;

const InsufficientBanner = styled.div`
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.4rem 0.65rem;
    background: ${({ theme }) => theme.colors.buttonDangerBg};
    border: 1px solid ${({ theme }) => theme.colors.buttonDangerBorder};
    border-radius: 10px;
    color: ${({ theme }) => theme.colors.voteDown};
    font-size: 0.68rem;
    font-weight: 500;
    line-height: 1.4;
`;

const InfoCard = styled.div`
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0.6rem 0.7rem;
    background: ${({ theme }) => theme.colors.surface2};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
`;

const InfoCardRow = styled.div`
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
    min-width: 0;
`;

const InfoCardLabel = styled.span`
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.subtleText};
    flex-shrink: 0;
`;

const InfoCardValue = styled.span`
    /* Keep in lock-step with BalanceValue / AmountInput so all "numeric
     * values on the right" across the gift-subscription dialog look the
     * same (balance, fee, expiry). */
    font-size: 0.82rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.text};
    text-align: right;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
`;

const InfoCardDivider = styled.div`
    height: 1px;
    background: ${({ theme }) => theme.colors.border};
    margin: 0.1rem 0;
`;

const AmountRow = styled.div`
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: ${({ theme }) => theme.colors.surface2};
    border: 1px solid ${({ theme }) => theme.colors.border};
    border-radius: 10px;
    padding: 0.45rem 0.7rem;
    transition: border-color 0.12s ease;

    &:focus-within {
        border-color: ${({ theme }) => theme.colors.borderStrong};
    }
`;

const AmountInput = styled.input`
    flex: 1 1 auto;
    min-width: 0;
    background: transparent;
    border: none;
    outline: none;
    color: ${({ theme }) => theme.colors.text};
    font-family: inherit;
    font-size: 0.82rem;
    font-weight: 600;
    text-align: right;
    letter-spacing: 0.01em;

    &::placeholder { color: ${({ theme }) => theme.colors.subtleText}; }
    &:disabled { opacity: 0.6; cursor: not-allowed; }
`;

const AmountUnit = styled.span`
    /* Sits on the LEFT of the amount row (label-like). Matches
     * BalanceLabel so the "Your balance" / "MIRAGE" labels on the left
     * of their respective rows share identical typography. */
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: ${({ theme }) => theme.colors.subtleText};
    flex-shrink: 0;
`;

const Hint = styled.div`
    font-size: 0.68rem;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.45;
`;

const StatusLine = styled.div`
    font-size: 0.72rem;
    color: ${({ theme, $tone }) =>
        $tone === 'error' ? theme.colors.voteDown : theme.colors.subtleText};
    line-height: 1.45;
    display: flex;
    align-items: center;
    gap: 0.35rem;
`;

const AwardGrid = styled.div`
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;

    @media (max-width: 480px) {
        grid-template-columns: 1fr;
    }
`;

const AwardTile = styled.button`
    appearance: none;
    display: flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0.6rem 0.7rem;
    background: ${({ theme, $selected }) =>
        $selected ? theme.colors.buttonSuccessBg : theme.colors.surface2};
    border: 1px solid ${({ theme, $selected }) =>
        $selected ? theme.colors.buttonSuccessBorder : theme.colors.border};
    border-radius: 10px;
    color: ${({ theme }) => theme.colors.text};
    font-family: inherit;
    text-align: left;
    cursor: pointer;
    transition: background 0.12s ease, border-color 0.12s ease, transform 0.12s ease;

    &:hover:not(:disabled) {
        background: ${({ theme, $selected }) =>
            $selected ? theme.colors.buttonSuccessBg : theme.colors.hoverBg};
        border-color: ${({ theme, $selected }) =>
            $selected ? theme.colors.buttonSuccessBorder : theme.colors.borderStrong};
    }

    &:active:not(:disabled) { transform: scale(0.98); }

    &:disabled {
        cursor: ${({ $busy }) => ($busy ? 'wait' : 'not-allowed')};
        opacity: 0.5;
    }

    &:focus { outline: none; }
    &:focus-visible { box-shadow: 0 0 0 2px ${({ theme }) => theme.colors.borderStrong}; }
`;

const AwardIcon = styled.span`
    font-size: 1.4rem;
    line-height: 1;
    flex-shrink: 0;
`;

const AwardText = styled.span`
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
    flex: 1 1 auto;
`;

const AwardLabel = styled.span`
    font-size: 0.74rem;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.text};
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
`;

const AwardCost = styled.span`
    font-size: 0.65rem;
    font-weight: 500;
    color: ${({ theme }) => theme.colors.subtleText};
    line-height: 1.2;
`;

// ─── Shared helpers ──────────────────────────────────────────────────────────

/** Format umirage as `N MIRAGE` using the same balance formatter the
 *  TopBar / MobileHeader / ProfileView already use. Keeps the dialog
 *  and the rest of the UI in lock-step. */
function formatMirage(umirage) {
    const n = Number(umirage);
    if (!isFinite(n)) return '— MIRAGE';
    return `${formatMirageBalance(n)} MIRAGE`;
}

/** Fetch the viewer's *current* balance straight from the API. Returns
 *  null if the user is logged out or the request fails. We use this
 *  instead of relying on the `userBalanceUmirage` prop because that
 *  prop is sourced from `useBalance()` which reads `localStorage.user_balance`,
 *  and that key can be stale or zeroed (e.g. fresh signup, or a viewer
 *  who's never visited their own profile in this session). */
async function fetchViewerBalance() {
    try {
        const publicKey = Storage.load('publicKey', '');
        if (!publicKey) return null;
        const data = await Api.get('get_user_status', { address: publicKey, _cb: Date.now() });
        if (!data) return null;
        const raw = data.balance !== undefined ? data.balance : data.user_balance;
        const n = Number(raw);
        return Number.isFinite(n) ? n : null;
    } catch (_) {
        return null;
    }
}

/** Hook that returns the viewer's freshly-fetched balance whenever the
 *  dialog opens. Falls back to the parent-supplied prop while the fetch
 *  is in flight so we never display a stale "0 MIRAGE" the way the
 *  pre-fix code did. */
function useLiveViewerBalance(open, fallbackUmirage) {
    const [fresh, setFresh] = useState(null);
    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        (async () => {
            const bal = await fetchViewerBalance();
            if (!cancelled && bal !== null) setFresh(bal);
        })();
        return () => { cancelled = true; };
    }, [open]);
    if (fresh !== null) return fresh;
    if (fallbackUmirage != null && Number.isFinite(Number(fallbackUmirage))) {
        return Number(fallbackUmirage);
    }
    return null;
}

/** Convert a raw digit string (MIRAGE whole units) to a thousands-separated
 *  label. Used by `GiftMirageDialog` when the caller doesn't supply its own
 *  formatter (ProfileView passes `formatDonateAmount` from the hook). */
function defaultAmountFormatter(raw) {
    return String(raw || '')
        .replace(/[^\d]/g, '')
        .replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// ─── GiftMirageDialog ────────────────────────────────────────────────────────

export function GiftMirageDialog({
    open,
    recipientLabel,
    amountRaw,
    formatAmount,
    onAmountChange,
    onConfirm,
    onCancel,
    pending = false,
    confirmLabel = 'Send',
    minAmount = 10000,
    userBalanceUmirage,
}) {
    const digits = String(amountRaw || '').replace(/[^\d]/g, '');
    const parsedMirage = digits ? parseInt(digits, 10) : 0;
    const empty = !digits;
    const belowMin = !empty && parsedMirage < minAmount;
    const formatter = typeof formatAmount === 'function' ? formatAmount : defaultAmountFormatter;

    // Pull the live on-chain balance for the logged-in viewer. The hook
    // re-fetches every time the dialog opens, so we never rely on a
    // stale `localStorage.user_balance` (which previously caused the
    // popup to render "0 MIRAGE" + Insufficient banner even when the
    // user had plenty on chain).
    const balanceUmirageNum = useLiveViewerBalance(open, userBalanceUmirage);
    const balanceMirage = balanceUmirageNum !== null
        ? balanceUmirageNum / 1_000_000
        : null;
    // Compare in umirage to avoid float precision loss when the entered
    // amount has many digits.
    const amountUmirage = parsedMirage * 1_000_000;
    const insufficient = balanceUmirageNum !== null
        && parsedMirage > 0
        && balanceUmirageNum < amountUmirage;

    const minLabel = minAmount.toLocaleString();
    const balanceDisplay = balanceMirage !== null
        ? formatMirage(balanceUmirageNum)
        : '—';

    const recipient = recipientLabel || 'this user';

    return (
        <ConfirmDialog
            open={open}
            title={`Gift MIRAGE to ${recipient}`}
            message="Funds are transferred on-chain and can't be refunded. Double-check the amount before confirming."
            confirmLabel={confirmLabel}
            confirmVariant="warning"
            pending={pending}
            confirmDisabled={empty || belowMin || insufficient}
            onConfirm={onConfirm}
            onCancel={onCancel}
            extraWide
        >
            <BalanceRow>
                <BalanceLabel>Your balance</BalanceLabel>
                <BalanceValue>{balanceDisplay}</BalanceValue>
            </BalanceRow>
            <AmountRow>
                <AmountUnit>MIRAGE</AmountUnit>
                <AmountInput
                    type="text"
                    inputMode="numeric"
                    value={formatter(amountRaw)}
                    onChange={e => onAmountChange(e.target.value.replace(/[^\d]/g, ''))}
                    placeholder={minLabel}
                    maxLength={15}
                    disabled={pending}
                    aria-label="Gift amount in MIRAGE"
                    autoFocus
                />
            </AmountRow>
            {insufficient ? (
                <InsufficientBanner>
                    <span aria-hidden="true">⚠</span>
                    Insufficient balance
                </InsufficientBanner>
            ) : (empty || belowMin) ? (
                <Hint>Minimum {minLabel} MIRAGE.</Hint>
            ) : (
                <Hint>Sending {parsedMirage.toLocaleString()} MIRAGE to {recipient}.</Hint>
            )}
        </ConfirmDialog>
    );
}

// ─── GiftSubscriptionDialog ──────────────────────────────────────────────────

export function GiftSubscriptionDialog({
    open,
    recipientLabel,
    level,
    feeUmirage,
    feeLabel, // optional pre-formatted string (fallback when feeUmirage not available)
    loading,
    expiryLabel,
    error,
    pending = false,
    confirmLabel = 'Confirm',
    onConfirm,
    onCancel,
    userBalanceUmirage,
}) {
    const isAgent = level === 10;
    const recipient = recipientLabel || 'this user';
    const title = isAgent
        ? `Gift agent subscription to ${recipient}`
        : `Gift subscription to ${recipient}`;
    const message = isAgent
        ? "Pays for one agent-tier subscription period on behalf of the recipient."
        : "Pays for one subscription period on behalf of the recipient.";

    const feeDisplay = feeUmirage != null && isFinite(Number(feeUmirage)) && Number(feeUmirage) > 0
        ? formatMirage(feeUmirage)
        : (feeLabel || null);

    // Live viewer balance — fetched on each open, falls back to the
    // parent prop while the request is in flight.
    const balanceUmirageNum = useLiveViewerBalance(open, userBalanceUmirage);
    const balanceDisplay = balanceUmirageNum !== null
        ? formatMirage(balanceUmirageNum)
        : '—';

    const insufficient = feeUmirage != null
        && isFinite(Number(feeUmirage))
        && balanceUmirageNum !== null
        && balanceUmirageNum < Number(feeUmirage);

    const confirmBlocked = loading || !!error || !expiryLabel || insufficient;

    return (
        <ConfirmDialog
            open={open}
            title={title}
            message={message}
            confirmLabel={confirmLabel}
            confirmVariant="warning"
            pending={pending}
            confirmDisabled={confirmBlocked}
            onConfirm={onConfirm}
            onCancel={onCancel}
            extraWide
        >
            <BalanceRow>
                <BalanceLabel>Your balance</BalanceLabel>
                <BalanceValue>{balanceDisplay}</BalanceValue>
            </BalanceRow>
            <InfoCard>
                {feeDisplay && (
                    <InfoCardRow>
                        <InfoCardLabel>Fee</InfoCardLabel>
                        <InfoCardValue title={feeDisplay}>{feeDisplay}</InfoCardValue>
                    </InfoCardRow>
                )}
                {(feeDisplay && (loading || expiryLabel)) && <InfoCardDivider />}
                {loading && (
                    <InfoCardRow>
                        <InfoCardLabel>Expires</InfoCardLabel>
                        <InfoCardValue>Loading…</InfoCardValue>
                    </InfoCardRow>
                )}
                {!loading && expiryLabel && (
                    <InfoCardRow>
                        <InfoCardLabel>Expires</InfoCardLabel>
                        <InfoCardValue title={expiryLabel}>{expiryLabel}</InfoCardValue>
                    </InfoCardRow>
                )}
            </InfoCard>
            {insufficient && (
                <InsufficientBanner>
                    <span aria-hidden="true">⚠</span>
                    Insufficient balance
                </InsufficientBanner>
            )}
            {error && (
                <StatusLine $tone="error">
                    <span aria-hidden="true">⚠</span>
                    {error}
                </StatusLine>
            )}
        </ConfirmDialog>
    );
}

// ─── GiveAwardDialog ─────────────────────────────────────────────────────────

export function GiveAwardDialog({
    open,
    awardTypes = [],
    getAwardCost,
    userBalanceUmirage,
    isAwarding = false,
    onPick,
    onCancel,
}) {
    const [selected, setSelected] = useState(null);

    // Reset the selection whenever the dialog opens/closes so the next
    // invocation starts on a clean slate.
    useEffect(() => {
        if (!open) setSelected(null);
    }, [open]);

    // Live viewer balance — fetched fresh on every open. Compute
    // affordability per-award + global (can the user afford ANY of them).
    const balance = useLiveViewerBalance(open, userBalanceUmirage);
    const balanceDisplay = balance !== null ? formatMirage(balance) : '—';

    let anyAffordable = false;
    const enriched = awardTypes.map(award => {
        const costUmirage = getAwardCost ? getAwardCost(award.name) : null;
        const costMirage = costUmirage != null && costUmirage > 0
            ? `${(costUmirage / 1_000_000).toLocaleString()} MIRAGE`
            : null;
        const canAfford = costUmirage != null
            && balance !== null
            && balance >= costUmirage;
        if (canAfford) anyAffordable = true;
        return { award, costUmirage, costMirage, canAfford };
    });
    const costsLoaded = enriched.some(e => e.costUmirage != null);
    const noneAffordable = costsLoaded && balance !== null && !anyAffordable;

    const selectedAward = selected
        ? enriched.find(e => e.award.name === selected)
        : null;
    const canSend = !!selectedAward && selectedAward.canAfford && !isAwarding;

    const handleSend = () => {
        if (!canSend || typeof onPick !== 'function') return;
        onPick(selectedAward.award.name);
    };

    return (
        <ConfirmDialog
            open={open}
            title="Give an award"
            message="Pick an award below. Awards cost MIRAGE and notify the author that you enjoyed the post."
            cancelLabel="Cancel"
            confirmLabel={isAwarding ? 'Sending…' : 'Send'}
            confirmVariant="warning"
            pending={isAwarding}
            confirmDisabled={!canSend}
            onConfirm={handleSend}
            onCancel={onCancel}
            extraWide
        >
            <BalanceRow>
                <BalanceLabel>Your balance</BalanceLabel>
                <BalanceValue>{balanceDisplay}</BalanceValue>
            </BalanceRow>
            {noneAffordable && (
                <InsufficientBanner>
                    <span aria-hidden="true">⚠</span>
                    Insufficient balance
                </InsufficientBanner>
            )}
            <AwardGrid>
                {enriched.map(({ award, costUmirage, costMirage, canAfford }) => {
                    const disabled = isAwarding || !canAfford;
                    const isSelected = selected === award.name;
                    return (
                        <AwardTile
                            key={award.name}
                            type="button"
                            disabled={disabled}
                            $busy={isAwarding}
                            $selected={isSelected}
                            aria-pressed={isSelected}
                            onClick={() => {
                                if (disabled) return;
                                setSelected(award.name);
                            }}
                        >
                            <AwardIcon>{award.icon}</AwardIcon>
                            <AwardText>
                                <AwardLabel>{award.label}</AwardLabel>
                                <AwardCost>
                                    {costMirage == null
                                        ? (costUmirage === 0 ? 'Free' : 'Loading…')
                                        : costMirage}
                                </AwardCost>
                            </AwardText>
                        </AwardTile>
                    );
                })}
            </AwardGrid>
        </ConfirmDialog>
    );
}

const GiftDialogs = {
    GiftMirageDialog,
    GiftSubscriptionDialog,
    GiveAwardDialog,
};

export default GiftDialogs;
