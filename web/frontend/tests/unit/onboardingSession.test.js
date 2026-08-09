import { describe, it, expect, beforeEach } from 'vitest';
import { createHandoff, peekHandoff, consumeHandoff, clearHandoff, _debugHandoffCount } from '../../src/utils/onboardingSession.js';

describe('onboardingSession', () => {
    beforeEach(() => {
        clearHandoff();
    });

    it('stores secrets only in memory and consumes once', () => {
        const { id } = createHandoff({ purpose: 'import', seed: 'alpha beta', owner: 'mirage1abc' });
        expect(_debugHandoffCount()).toBe(1);
        const peeked = peekHandoff(id, 'import');
        expect(peeked.seed).toBe('alpha beta');
        const consumed = consumeHandoff(id, 'import');
        expect(consumed.seed).toBe('alpha beta');
        expect(peekHandoff(id, 'import')).toBeNull();
        expect(_debugHandoffCount()).toBe(0);
    });

    it('rejects invalid purpose and enforces purpose match', () => {
        expect(() => createHandoff({ purpose: 'nope', seed: 'x' })).toThrow(/purpose/);
        const { id } = createHandoff({ purpose: 'welcome', seed: 'phrase here' });
        expect(peekHandoff(id, 'import')).toBeNull();
        expect(peekHandoff(id, 'welcome')?.seed).toBe('phrase here');
    });
});
