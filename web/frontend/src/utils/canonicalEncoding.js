// Nonce: (Date.now() * 1_000_000) + rand32. Must be >0, <=2^53-1 (JS safe int).
export function generateEnvelopeNonce() {
    const cryptoApi = (typeof window !== 'undefined' && window.crypto) ? window.crypto : null;
    if (!cryptoApi || typeof cryptoApi.getRandomValues !== 'function') {
        throw new Error('Secure random source unavailable');
    }
    const rand = new Uint32Array(1);
    cryptoApi.getRandomValues(rand);
    const randomPart = rand[0] >>> 0;
    const base = Math.floor(Date.now() * 1_000_000);
    let nonce = base + randomPart;
    if (nonce <= 0 || !Number.isSafeInteger(nonce)) {
        nonce = (Date.now() * 1000) + (randomPart % 1000) + 1;
    }
    if (nonce <= 0 || !Number.isSafeInteger(nonce)) {
        throw new Error('Failed to generate valid envelope nonce');
    }
    return nonce;
}

export function uvarint(n) {
    const out = [];
    let v = (n >>> 0);
    while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
    out.push(v);
    return Uint8Array.from(out);
}

export function uvarint64(n) {
    const out = [];
    let v = BigInt(n || 0);
    while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
    out.push(Number(v));
    return Uint8Array.from(out);
}

export function encStr(s) {
    const b = new TextEncoder().encode(s || "");
    return new Uint8Array([...uvarint(b.length), ...b]);
}

export function encBytes(arr) {
    return new Uint8Array([...uvarint(arr.length), ...arr]);
}

export function hexToBytes(hex) {
    const h = (hex || "").replace(/^0x/i, "");
    if (!h) return new Uint8Array(0);
    if (h.length % 2) throw new Error('Invalid hex length');
    if (!/^[0-9a-fA-F]+$/.test(h)) throw new Error('Invalid hex characters');
    const arr = new Uint8Array(h.length / 2);
    for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
    return arr;
}

export function concat(...arrs) {
    let total = 0; arrs.forEach(a => total += a.length);
    const out = new Uint8Array(total);
    let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
    return out;
}

// Build canonical bytes for any message type.
// Handles the common envelope (prefix, pubkey, block_hash, difficulty, pow, timestamp, nonce)
// then appends message-specific payload fields.
export function buildCanonical({ msgType, pub_bytes, last_block_hash, difficulty, proof, timestamp, nonce, fields }) {
    const prefix = new TextEncoder().encode(`mirage.core.v1:${msgType}\x00`);
    const tag2 = Uint8Array.from([2]);
    const tag3 = Uint8Array.from([3]);
    const tag4 = Uint8Array.from([4]);
    const tag5 = Uint8Array.from([5]);
    const tag6 = Uint8Array.from([6]);
    const tag7 = Uint8Array.from([7]);

    const parts = [
        prefix,
        tag2, encBytes(pub_bytes || new Uint8Array()),
        tag3, encBytes(hexToBytes(last_block_hash)),
        tag4, uvarint(difficulty >>> 0),
        tag5, uvarint(proof >>> 0),
        tag6, uvarint64(timestamp || 0),
        tag7, uvarint64(nonce),
    ];

    for (const [tagNum, value] of fields) {
        parts.push(Uint8Array.from([tagNum]));
        parts.push(value);
    }

    return concat(...parts);
}
