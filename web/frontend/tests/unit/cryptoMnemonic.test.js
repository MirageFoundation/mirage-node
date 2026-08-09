import { describe, it, expect } from 'vitest';
import { generateMnemonic, validateMnemonic } from 'bip39';
import { requireValidMnemonic, deriveKeysFromSeed } from '../../src/utils/CryptoUtils.js';

describe('requireValidMnemonic', () => {
    it('accepts a valid 12-word phrase and normalizes whitespace/case', () => {
        const mnemonic = generateMnemonic();
        expect(validateMnemonic(mnemonic)).toBe(true);
        const spaced = `  ${mnemonic.toUpperCase().split(' ').join('   ')}  `;
        const normalized = requireValidMnemonic(spaced);
        expect(normalized).toBe(mnemonic);
        expect(normalized.split(' ')).toHaveLength(12);
    });

    it('rejects empty / wrong word count / checksum failures', () => {
        expect(() => requireValidMnemonic('')).toThrow(/required/i);
        expect(() => requireValidMnemonic('one two three')).toThrow(/12, 15, 18, 21, or 24/);
        // Valid words but wrong checksum
        expect(() => requireValidMnemonic('abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon')).toThrow(/Invalid recovery phrase/);
    });

    it('derives stable owner addresses for a fixed mnemonic', () => {
        const mnemonic = requireValidMnemonic(generateMnemonic());
        const a = deriveKeysFromSeed(mnemonic);
        const b = deriveKeysFromSeed(mnemonic);
        expect(a.publicKey).toBe(b.publicKey);
        expect(a.publicKey.startsWith('mirage')).toBe(true);
        expect(a.privateKey).toHaveLength(64);
    });
});
