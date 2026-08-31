import { describe, it, expect } from 'vitest';
import { formatError } from '../../src/utils/errorMessages.js';

describe('formatError', () => {
    it('maps known error_code', () => {
        expect(formatError({ error_code: 'transaction_failed' })).toBe('Transaction failed.');
    });

    it('maps pow wasm CSP block', () => {
        expect(formatError({ error_code: 'pow_wasm_csp_blocked' }))
            .toBe('This browser blocked the proof-of-work engine. Please try again, or use a different browser.');
    });

    it('surfaces cancelled queue reasons instead of Missing error code', () => {
        expect(formatError({ success: false, cancelled: true, reason: 'owner_mismatch' }))
            .toBe('Session changed while submitting. Please try again.');
        expect(formatError({ success: false, cancelled: true, reason: 'missing recovery phrase' }))
            .toBe('Recovery phrase is missing.');
        expect(formatError({ success: false, cancelled: true, error_code: 'missing_onboarding_handoff' }))
            .toBe('Recovery phrase is missing.');
    });

    it('surfaces client/network Error.message when error_code is absent', () => {
        expect(formatError(new Error('Failed to fetch'))).toBe('Failed to fetch');
    });
});