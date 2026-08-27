// Use Argon2id in the worker (same-origin pinned WASM bundle; see public/pow/MANIFEST.txt)
importScripts('/pow/argon2-bundled.min.js');

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

function bytesToHex(bytes) {
    let hex = '';
    for (let i = 0; i < bytes.length; i++) {
        hex += bytes[i].toString(16).padStart(2, '0');
    }
    return hex;
}

function uvarint(n) {
    const out = [];
    // Support both Number and BigInt
    let v = typeof n === 'bigint' ? n : BigInt(n >>> 0);
    while (v >= 0x80n) { out.push(Number((v & 0x7Fn) | 0x80n)); v >>= 7n; }
    out.push(Number(v));
    return Uint8Array.from(out);
}

function concatBytes(a, b, c) {
    const out = new Uint8Array(a.length + b.length + c.length);
    out.set(a, 0);
    out.set(b, a.length);
    out.set(c, a.length + b.length);
    return out;
}

/**
 * Target-based PoW check using BigInt.
 * base_target = 2^(256 - powBaseBits)
 * eff_target  = base_target * 1000 / (1000 * (1 + step)^difficulty)
 * Pass if hash_int <= eff_target
 */
const BASE_DIFFICULTY_FACTOR = 1000;
const MAX_SAFE_DIFFICULTY_FACTOR = Number.MAX_SAFE_INTEGER;

function difficultyFactor(difficultySteps, powFactor) {
    if (!Number.isFinite(powFactor) || powFactor <= 0 || powFactor > 1) return null;
    if (!Number.isFinite(difficultySteps) || !Number.isInteger(difficultySteps) || difficultySteps < 0) return null;
    if (difficultySteps === 0) return BASE_DIFFICULTY_FACTOR;
    const factorFloat = BASE_DIFFICULTY_FACTOR * Math.pow(1 + powFactor, difficultySteps);
    if (!Number.isFinite(factorFloat) || factorFloat > MAX_SAFE_DIFFICULTY_FACTOR) return MAX_SAFE_DIFFICULTY_FACTOR;
    const rounded = Math.round(factorFloat);
    return Math.max(BASE_DIFFICULTY_FACTOR, rounded);
}

function checkPowTarget(hashBytes, difficultySteps, powBaseBits, powFactor) {
    const hashHex = bytesToHex(hashBytes);
    const hashInt = BigInt('0x' + hashHex);
    const baseTarget = 1n << BigInt(256 - powBaseBits);
    const factor = difficultyFactor(difficultySteps, powFactor);
    if (factor === null) return false;
    const effTarget = baseTarget * 1000n / BigInt(factor);
    return hashInt <= effTarget;
}

function powErrorCode(err) {
    const msg = String(err && err.message ? err.message : err);
    if (/blocked by CSP/i.test(msg) || msg === 'wasm_csp_blocked') return 'wasm_csp_blocked';
    return 'pow_failed';
}

// Empty WASM module (magic + version). instantiate() succeeds if CSP allows
// compilation and throws CompileError "blocked by CSP" if it does not.
// Argon2's own instantiate is async and does not reject when CSP blocks it,
// so without this probe the worker hangs until the 60s main-thread timeout.
async function assertWasmAllowed() {
    const emptyModule = new Uint8Array([0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00]);
    try {
        await WebAssembly.instantiate(emptyModule);
        console.debug('[PoW] wasm instantiate allowed');
    } catch (err) {
        const msg = String(err && err.message ? err.message : err);
        console.error('[PoW] wasm instantiate failed', { name: err && err.name, message: msg });
        if (/blocked by CSP/i.test(msg)) {
            throw new Error('wasm_csp_blocked');
        }
        throw err;
    }
}

async function isValidProofArgon2id(baseBytes, saltBytes, proof, difficultySteps, powBaseBits, powFactor) {
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
    return checkPowTarget(bytes, difficultySteps, powBaseBits, powFactor);
}

async function performPow(baseHex, saltHex, difficultySteps, powBaseBits, powFactor, start) {
    const baseBytes = hexToBytes(baseHex);
    const saltBytes = hexToBytes((saltHex || '').trim());
    let proof = (start >>> 0) || 0;
    while (true) {
        // eslint-disable-next-line no-await-in-loop
        const ok = await isValidProofArgon2id(baseBytes, saltBytes, proof, difficultySteps, powBaseBits, powFactor);
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
    const baseBits = (data && typeof data.powBaseBits === 'number') ? data.powBaseBits : NaN;
    const powFactor = (data && typeof data.powFactor === 'number') ? data.powFactor : NaN;
    const start = (data && typeof data.start === 'number') ? (data.start >>> 0) : 0;

    if (
        !baseHex ||
        !saltHex ||
        !Number.isFinite(diff) ||
        !Number.isInteger(diff) ||
        diff < 0 ||
        !Number.isFinite(baseBits) ||
        !Number.isInteger(baseBits) ||
        baseBits <= 0 ||
        baseBits > 256 ||
        !Number.isFinite(powFactor) ||
        powFactor <= 0 ||
        powFactor > 1
    ) {
        self.postMessage({ error: 'invalid_params' });
        return;
    }
    assertWasmAllowed()
        .then(() => performPow(baseHex, saltHex, diff, baseBits, powFactor, start))
        .then((pow) => self.postMessage(pow))
        .catch((err) => {
            const code = powErrorCode(err);
            console.error('[PoW] worker failed', { error: code, detail: String(err && err.message ? err.message : err) });
            self.postMessage({ error: code });
        });
};
