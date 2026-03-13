/* global BigInt */
import {
    generateEnvelopeNonce,
    buildCanonical,
    uvarint,
    uvarint64,
    encStr,
    encBytes,
    hexToBytes,
} from '../canonicalEncoding';
import fs from 'fs';
import path from 'path';

// ── Helpers ────────────────────────────────────────────────

const FAKE_PUB = new Uint8Array(33).fill(0x02);
const FAKE_BLOCK_HASH = 'aa'.repeat(32);
const NONCE = 1234567890123;
const BASE = {
    pub_bytes: FAKE_PUB,
    last_block_hash: FAKE_BLOCK_HASH,
    difficulty: 10,
    proof: 42,
    timestamp: 1700000000000,
    nonce: NONCE,
};

function decodeNonceFromTag7(bytes) {
    for (let i = 0; i < bytes.length - 1; i++) {
        if (bytes[i] === 7) {
            let val = BigInt(0);
            let shift = 0n;
            let j = i + 1;
            while (j < bytes.length) {
                const b = bytes[j];
                val |= BigInt(b & 0x7f) << shift;
                j++;
                if ((b & 0x80) === 0) break;
                shift += 7n;
            }
            return Number(val);
        }
    }
    return null;
}

// ── generateEnvelopeNonce ──────────────────────────────────

describe('generateEnvelopeNonce', () => {
    test('always returns a positive integer', () => {
        for (let i = 0; i < 200; i++) {
            const n = generateEnvelopeNonce();
            expect(n).toBeGreaterThan(0);
            expect(Number.isInteger(n)).toBe(true);
        }
    });

    test('always returns a JS-safe integer (<=2^53-1)', () => {
        for (let i = 0; i < 200; i++) {
            expect(Number.isSafeInteger(generateEnvelopeNonce())).toBe(true);
        }
    });

    test('generates unique values across calls', () => {
        const seen = new Set();
        for (let i = 0; i < 100; i++) seen.add(generateEnvelopeNonce());
        expect(seen.size).toBeGreaterThanOrEqual(90);
    });
});

// ── Encoding primitives ────────────────────────────────────

describe('uvarint encoding', () => {
    test('encodes 0 as single byte', () => {
        expect(Array.from(uvarint(0))).toEqual([0]);
    });
    test('encodes 127 as single byte', () => {
        expect(Array.from(uvarint(127))).toEqual([127]);
    });
    test('encodes 128 as two bytes', () => {
        expect(Array.from(uvarint(128))).toEqual([0x80, 1]);
    });
    test('encodes 300 correctly', () => {
        expect(Array.from(uvarint(300))).toEqual([0xAC, 0x02]);
    });
});

describe('uvarint64 encoding', () => {
    test('encodes large nonce correctly', () => {
        const bytes = uvarint64(NONCE);
        // Decode it back
        let val = BigInt(0), shift = 0n;
        for (const b of bytes) {
            val |= BigInt(b & 0x7f) << shift;
            shift += 7n;
            if ((b & 0x80) === 0) break;
        }
        expect(Number(val)).toBe(NONCE);
    });
    test('encodes 0', () => {
        expect(Array.from(uvarint64(0))).toEqual([0]);
    });
});

// ── buildCanonical ─────────────────────────────────────────

describe('buildCanonical', () => {
    test('produces bytes containing the message prefix', () => {
        const bytes = buildCanonical({
            msgType: 'MsgPost',
            ...BASE,
            fields: [[100, encStr('target')]],
        });
        const str = new TextDecoder().decode(bytes.slice(0, 30));
        expect(str).toContain('mirage.core.v1:MsgPost');
    });

    test('always includes nonce tag 7 with correct value', () => {
        const bytes = buildCanonical({
            msgType: 'MsgPost',
            ...BASE,
            fields: [[100, encStr('target')]],
        });
        expect(decodeNonceFromTag7(bytes)).toBe(NONCE);
    });

    test('different nonces produce different bytes', () => {
        const a = buildCanonical({ msgType: 'MsgPost', ...BASE, nonce: 111, fields: [] });
        const b = buildCanonical({ msgType: 'MsgPost', ...BASE, nonce: 222, fields: [] });
        expect(Buffer.from(a).equals(Buffer.from(b))).toBe(false);
    });

    test('nonce=0 still encodes tag 7', () => {
        const bytes = buildCanonical({ msgType: 'MsgPost', ...BASE, nonce: 0, fields: [] });
        // Tag 7 should be present even for nonce 0
        let found = false;
        for (let i = 0; i < bytes.length - 1; i++) {
            if (bytes[i] === 7) { found = true; break; }
        }
        expect(found).toBe(true);
    });
});

// ── All message types in buildCanonical ────────────────────

const MSG_CONFIGS = {
    MsgPost: [[100, encStr('t')], [101, encStr('topic')], [102, encStr('title')], [103, encStr('body')]],
    MsgEdit: [[100, encStr('t')], [101, encStr('topic')], [102, encStr('title')], [103, encStr('body')]],
    MsgAnnotate: [[100, encStr('topic')], [101, encStr('title')], [102, encStr('note')]],
    MsgSetUsername: [[100, encStr('t')], [101, encStr('alice')]],
    MsgSetBiography: [[100, encStr('t')], [101, encStr('bio')]],
    MsgEnableAgent: [[100, encStr('t')], [101, encStr('a')]],
    MsgDisableAgent: [[100, encStr('t')], [101, encStr('a')]],
    MsgSetAgents: [[100, encStr('t')]],
    MsgFollowUser: [[100, encStr('t')], [101, encStr('u')]],
    MsgUnfollowUser: [[100, encStr('t')], [101, encStr('u')]],
    MsgFollowTopic: [[100, encStr('t')], [101, encStr('topic')]],
    MsgUnfollowTopic: [[100, encStr('t')], [101, encStr('topic')]],
    MsgBlockPost: [[100, encStr('h')]],
    MsgUnblockPost: [[100, encStr('h')]],
    MsgBlockUser: [[100, encStr('u')]],
    MsgUnblockUser: [[100, encStr('u')]],
    MsgBlockTopic: [[100, encStr('t')], [101, encStr('topic')]],
    MsgUnblockTopic: [[100, encStr('t')], [101, encStr('topic')]],
    MsgDelete: [[100, encStr('h')]],
    MsgDeleteUser: [[100, encStr('t')]],
    MsgSendTokens: [[100, encStr('s')], [101, encStr('t')], [102, uvarint64(1000)]],
    MsgVote: [[100, encStr('target')], [101, uvarint(1)]],
    MsgUpgradeLevel: [[100, uvarint(1)]],
    MsgSetAutoRenewal: [[100, uvarint(1)]],
    MsgBridgeBurn: [[100, encStr('solana')], [101, encStr('addr')], [102, uvarint64(500)]],
    MsgAward: [[100, encStr('target')], [101, encStr('quality_post')]],
    MsgReport: [[100, encStr('target')], [101, encStr('spam')]],
};

describe('buildCanonical: all message types include nonce', () => {
    for (const [msgType, fields] of Object.entries(MSG_CONFIGS)) {
        test(`${msgType} canonical bytes contain nonce tag 7 = ${NONCE}`, () => {
            const bytes = buildCanonical({ msgType, ...BASE, fields });
            expect(decodeNonceFromTag7(bytes)).toBe(NONCE);
        });
    }
});

// ── Source-level structural safety net ──────────────────────
// Scan TransactionHandler.js to ensure every message type includes
// nonce tag 7 in its canonical construction AND envelope_nonce in toRelay.

describe('TransactionHandler.js source-level nonce enforcement', () => {
    const src = fs.readFileSync(
        path.resolve(__dirname, '..', 'TransactionHandler.js'),
        'utf-8'
    );

    const ALL_MSG_TYPES = Object.keys(MSG_CONFIGS);

    test('every message type prefix exists in source', () => {
        for (const msg of ALL_MSG_TYPES) {
            expect(src).toContain(`mirage.core.v1:${msg}\\x00`);
        }
    });

    test('every signing canonical construction includes tag 7 (nonce)', () => {
        // Find all prefix constructions. Exclude PoW worker base-bytes paths
        // (identified by "baseBytes =" nearby) since PoW doesn't need the nonce.
        const prefixPattern = /new TextEncoder\(\)\.encode\("mirage\.core\.v1:(\w+)\\x00"\)/g;
        let match;
        const signing = [];
        while ((match = prefixPattern.exec(src)) !== null) {
            const block = src.slice(match.index, match.index + 2000);
            const isPowPath = block.includes('baseBytes =') || block.includes('baseBytes=');
            if (!isPowPath) {
                signing.push({ msg: match[1], index: match.index });
            }
        }
        expect(signing.length).toBeGreaterThanOrEqual(ALL_MSG_TYPES.length);
        const missingTag7 = [];
        for (const { msg, index } of signing) {
            const block = src.slice(index, index + 2000);
            if (!block.includes('Uint8Array.from([7])')) {
                missingTag7.push(msg);
            }
        }
        if (missingTag7.length > 0) {
            throw new Error(`CRITICAL: signing canonical bytes missing nonce tag 7 for: ${missingTag7.join(', ')}`);
        }
    });

    test('every toRelay payload includes envelope_nonce (explicit or via spread)', () => {
        const relayBlocks = src.match(/toRelay\s*=\s*\{[^}]+\}/g) || [];
        expect(relayBlocks.length).toBeGreaterThan(0);
        const missing = [];
        for (const block of relayBlocks) {
            // Acceptable: explicit envelope_nonce, or ...toRelay spread (inherits from initial)
            const hasNonce = block.includes('envelope_nonce');
            const spreadsToRelay = block.includes('...toRelay');
            const spreadsFromPubkey = block.includes('toRelay.pubkey');
            if (!hasNonce && !spreadsToRelay && !spreadsFromPubkey) {
                missing.push(block.slice(0, 120));
            }
        }
        if (missing.length > 0) {
            throw new Error(`CRITICAL: toRelay blocks missing envelope_nonce:\n${missing.join('\n---\n')}`);
        }
    });

    test('initial toRelay construction includes envelope_nonce', () => {
        // The first toRelay assignment must set envelope_nonce so spread-based blocks inherit it
        expect(src).toMatch(/let toRelay\s*=\s*\{[^}]*envelope_nonce/);
    });

    test('generateEnvelopeNonce is imported (not redefined locally)', () => {
        expect(src).toContain("import { generateEnvelopeNonce }");
        // Must NOT have a local function definition (it should come from canonicalEncoding)
        expect(src).not.toMatch(/^function generateEnvelopeNonce/m);
    });
});
