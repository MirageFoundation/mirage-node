/**
 * useBalance – single source of truth for the logged-in user's MIRAGE balance.
 *
 * Every component that displays the current user's balance MUST use this hook.
 * Balance is written to localStorage exclusively through TransactionHandler._persistUserBalance,
 * which also fires a 'balanceUpdated' CustomEvent so all consumers update in lockstep.
 *
 * Returns:
 *   balance          – raw umirage (Number) or null while loading
 *   displayBalance   – balance + any optimistic claim delta, or null
 */

import { useState, useEffect, useCallback } from 'react';
import Storage from './Storage';

const OPTIMISTIC_CLAIM_KEY = 'user_balance_optimistic_claim';

/** Parse a stored/event balance value into a safe integer, or null. */
function parseBalance(raw) {
    if (raw === null || raw === undefined) return null;
    const n = Number(raw);
    if (!Number.isFinite(n)) return null;
    return n;
}

/** Resolve any pending optimistic reward delta. */
function resolveOptimisticDelta(currentBalance) {
    const payload = Storage.load(OPTIMISTIC_CLAIM_KEY, null);
    if (!payload || typeof payload !== 'object') return 0;
    const delta = Number(payload.delta_umirage);
    const base = Number(payload.base_umirage);
    const expiresAt = Number(payload.expires_at_ms);
    if (!Number.isFinite(delta) || delta <= 0 || !Number.isFinite(expiresAt) || Date.now() > expiresAt) {
        Storage.remove(OPTIMISTIC_CLAIM_KEY);
        return 0;
    }
    if (Number.isFinite(currentBalance) && Number.isFinite(base) && currentBalance !== base) {
        Storage.remove(OPTIMISTIC_CLAIM_KEY);
        return 0;
    }
    return delta;
}

export default function useBalance() {
    const publicKey = Storage.load('publicKey', '');
    const hasPublicKey = !!publicKey;

    const [balance, setBalance] = useState(() => {
        if (!hasPublicKey) return null;
        return parseBalance(Storage.load('user_balance', null));
    });
    const [optimisticDelta, setOptimisticDelta] = useState(0);

    const applyUpdate = useCallback((raw) => {
        const parsed = parseBalance(raw);
        if (parsed === null) {
            setBalance(null);
            setOptimisticDelta(0);
            return;
        }
        setBalance(parsed);
        setOptimisticDelta(resolveOptimisticDelta(parsed));
    }, []);

    useEffect(() => {
        if (!hasPublicKey) {
            setBalance(null);
            setOptimisticDelta(0);
            Storage.remove(OPTIMISTIC_CLAIM_KEY);
            return;
        }

        // Read current value on mount / login
        const stored = Storage.load('user_balance', null);
        if (stored !== null) applyUpdate(stored);

        // TransactionHandler._persistUserBalance fires this on every write
        const onBalanceUpdated = (e) => {
            if (e.detail !== undefined) applyUpdate(e.detail);
        };

        // Cross-tab sync via native storage event
        const onStorage = (e) => {
            if (e.key === 'user_balance') applyUpdate(e.newValue);
        };

        // Quest / claim optimistic bumps
        const onOptimistic = () => {
            const s = Storage.load('user_balance', null);
            if (s !== null) applyUpdate(s);
        };

        window.addEventListener('balanceUpdated', onBalanceUpdated);
        window.addEventListener('storage', onStorage);
        window.addEventListener('optimisticBalanceUpdate', onOptimistic);

        return () => {
            window.removeEventListener('balanceUpdated', onBalanceUpdated);
            window.removeEventListener('storage', onStorage);
            window.removeEventListener('optimisticBalanceUpdate', onOptimistic);
        };
    }, [hasPublicKey, applyUpdate]);

    const displayBalance = balance === null ? null : balance + optimisticDelta;

    return { balance, displayBalance };
}
