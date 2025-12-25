// Use Argon2id in the worker (WASM bundled)
importScripts('https://cdn.jsdelivr.net/npm/argon2-browser/dist/argon2-bundled.min.js');

function hexCharToByte(c) {
    return c >= '0' && c <= '9'
        ? c.charCodeAt(0) - '0'.charCodeAt(0)
        : c.toLowerCase().charCodeAt(0) - 'a'.charCodeAt(0) + 10;
}

function hexToBytes(hex) {
    if (typeof hex !== 'string') throw new Error('hex must be string');
    const clean = hex.startsWith('0x') ? hex.slice(2) : hex;
    if ((clean.length & 1) !== 0) throw new Error('hex length must be even');
    const length = clean.length / 2;
    const bytes = new Uint8Array(length);
    for (let i = 0; i < length; i++) {
        bytes[i] = (hexCharToByte(clean[i * 2]) << 4) | hexCharToByte(clean[i * 2 + 1]);
    }
    return bytes;
}

function uvarint(n) {
    const out = [];
    let v = (n >>> 0);
    while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
    out.push(v);
    return Uint8Array.from(out);
}

function concatBytes(a, b, c) {
    const out = new Uint8Array(a.length + b.length + c.length);
    out.set(a, 0);
    out.set(b, a.length);
    out.set(c, a.length + b.length);
    return out;
}

function leadingZeroBits(bytes) {
    let count = 0;
    for (let i = 0; i < bytes.length; i++) {
        const byte = bytes[i];
        if (byte === 0) { count += 8; continue; }
        let n = 0;
        for (let mask = 0x80; mask !== 0; mask >>= 1) {
            if ((byte & mask) === 0) n++; else break;
        }
        return count + n;
    }
    return count;
}

async function isValidProofArgon2id(baseBytes, saltBytes, proof, requiredBits) {
    const proofBytes = uvarint(proof >>> 0);
    const colon = new Uint8Array([":".charCodeAt(0)]);
    const password = concatBytes(baseBytes, colon, proofBytes);
    const res = await argon2.hash({
        pass: password,
        salt: saltBytes,
        time: 1,
        mem: 4096,
        parallelism: 1,
        hashLen: 32,
        type: argon2.ArgonType.Argon2id,
    });
    const digest = res && (res.hash || res.hashBytes || null);
    const bytes = digest instanceof Uint8Array ? digest : (res.hashHex ? hexToBytes(res.hashHex) : null);
    if (!bytes) return false;
    return leadingZeroBits(bytes) >= requiredBits;
}

async function performPow(baseHex, saltHex, difficulty, start) {
    const baseBytes = hexToBytes(baseHex);
    const saltBytes = hexToBytes((saltHex || '').trim());
    let proof = (start >>> 0) || 0;
    while (true) {
        // eslint-disable-next-line no-await-in-loop
        const ok = await isValidProofArgon2id(baseBytes, saltBytes, proof, difficulty);
        if (ok) break;
        proof++;
    }
    return proof;
}

self.onmessage = function (e) {
    const { data } = e;
    const baseHex = data && typeof data.baseHex === 'string' ? data.baseHex : undefined;
    const saltHex = data && typeof data.saltHex === 'string' ? data.saltHex : undefined;
    const diff = (data && typeof data.difficulty === 'number') ? data.difficulty : NaN;
    const start = (data && typeof data.start === 'number') ? (data.start >>> 0) : 0;
    // const diff = 1;

    if (!baseHex || !saltHex || !Number.isFinite(diff) || diff <= 0 || diff > 256) {
        self.postMessage(0);
        return;
    }
    performPow(baseHex, saltHex, diff, start).then((pow) => self.postMessage(pow)).catch(() => self.postMessage(0));
};
