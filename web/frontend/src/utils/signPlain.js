import { getPublicKey as secp256k1GetPublicKey } from '@noble/secp256k1';
import seedVault from './SeedVault';
import { derivePrivateKeyFromSeed } from './CryptoUtils.js';
import { generateEnvelopeNonce } from './canonicalEncoding';
import { ensureCosmCrypto } from './cosmCrypto';

export const FEED_READ_ACTION = 'get_posts';
export const THREAD_READ_ACTION = 'get_comments';
export const CURATOR_READ_ACTION = 'curator_read';

export function signedReadPayload(action, address, timestamp, nonce) {
    const verb = String(action || '').trim();
    const owner = String(address || '').trim().toLowerCase();
    if (!verb) throw new Error('signed read action is required');
    if (!owner) throw new Error('signed read address is required');
    return `${verb}:${owner}:${timestamp}:${nonce}`;
}

/**
 * Sign a plain UTF-8 payload string with the user's key.
 * Returns { pubkey, signature, envelope_nonce, timestamp } (all base64/number)
 * or null if the user has no seed available.
 */
export async function signPlainPayload(payloadFn) {
    const seed = seedVault.getSeed();
    if (!seed) {
        throw new Error("seed is locked or unavailable");
    }

    const { Secp256k1, sha256 } = await ensureCosmCrypto();

    const privHex = derivePrivateKeyFromSeed(seed);
    const privBytes = new Uint8Array(privHex.match(/.{1,2}/g).map(b => parseInt(b, 16)));
    const pubBytes = secp256k1GetPublicKey(privBytes, true);
    const pubB64 = btoa(Array.from(pubBytes).map(b => String.fromCharCode(b)).join(''));

    const timestamp = Date.now();
    const nonce = generateEnvelopeNonce();

    const payload = payloadFn(timestamp, nonce);
    const payloadBytes = new TextEncoder().encode(payload);
    const digest = sha256(payloadBytes);
    const sigCompact = await Secp256k1.createSignature(digest, privBytes);
    const sigFixed = sigCompact.toFixedLength();
    const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));

    return { pubkey: pubB64, signature: sigB64, envelope_nonce: nonce, timestamp };
}

export async function signReadParams(action, address) {
    return signPlainPayload(
        (timestamp, nonce) => signedReadPayload(action, address, timestamp, nonce),
    );
}
