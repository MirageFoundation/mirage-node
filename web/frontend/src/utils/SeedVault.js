import Storage from './Storage';
import { requireValidMnemonic } from './CryptoUtils';

// ── Storage keys ──────────────────────────────────────────────────────────────
const KEY_MODE = 'seed_storage_mode';       // "insecure" | "memory" | "password" | "passkey"
const KEY_PLAINTEXT = 'seedPhrase';              // legacy / insecure mode
const KEY_PWD_ENCRYPTED = 'seed_encrypted';          // {iv, salt, ciphertext} base64 JSON
const KEY_PRF_ENCRYPTED = 'seed_prf_encrypted';      // {iv, credentialId, ciphertext} base64 JSON
const KEY_PRF_CRED_ID = 'seed_prf_credential_id';  // raw credential ID for allowCredentials

// ── Helpers: base64 <-> ArrayBuffer ───────────────────────────────────────────
const toBase64 = (buf) => {
    const bytes = new Uint8Array(buf);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
};

const fromBase64 = (b64) => {
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
};

// ── AES-GCM encrypt / decrypt ─────────────────────────────────────────────────
async function encryptAESGCM(plaintext, rawKeyBytes) {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const key = await crypto.subtle.importKey('raw', rawKeyBytes, 'AES-GCM', false, ['encrypt']);
    const encoded = new TextEncoder().encode(plaintext);
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded);
    return { iv: toBase64(iv), ciphertext: toBase64(ciphertext) };
}

async function decryptAESGCM(ivB64, ciphertextB64, rawKeyBytes) {
    const iv = new Uint8Array(fromBase64(ivB64));
    const ciphertext = fromBase64(ciphertextB64);
    const key = await crypto.subtle.importKey('raw', rawKeyBytes, 'AES-GCM', false, ['decrypt']);
    const decrypted = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, ciphertext);
    return new TextDecoder().decode(decrypted);
}

// ── PBKDF2 password → 256-bit key ────────────────────────────────────────────
async function deriveKeyFromPassword(password, saltBytes) {
    const enc = new TextEncoder().encode(password);
    const baseKey = await crypto.subtle.importKey('raw', enc, 'PBKDF2', false, ['deriveBits']);
    const bits = await crypto.subtle.deriveBits(
        { name: 'PBKDF2', salt: saltBytes, iterations: 600_000, hash: 'SHA-256' },
        baseKey,
        256,
    );
    return new Uint8Array(bits);
}

// ── WebAuthn PRF helpers ──────────────────────────────────────────────────────
const PRF_SALT = new TextEncoder().encode('mirage-seed-vault');

function isPRFSupported() {
    try {
        if (typeof window === 'undefined') return false;
        if (!window.PublicKeyCredential) return false;
        // Firefox does not support the WebAuthn PRF extension (as of early 2026).
        // Detect Firefox and return false so the option is greyed out in settings.
        const ua = navigator.userAgent || '';
        if (/Firefox\//i.test(ua) && !/Seamonkey\//i.test(ua)) return false;
        return true;
    } catch (_) {
        return false;
    }
}

async function createPRFCredential() {
    const challenge = crypto.getRandomValues(new Uint8Array(32));
    const userId = crypto.getRandomValues(new Uint8Array(16));

    const credential = await navigator.credentials.create({
        publicKey: {
            challenge,
            rp: { name: 'Mirage', id: window.location.hostname },
            user: { id: userId, name: 'mirage-user', displayName: 'Mirage User' },
            pubKeyCredParams: [
                { alg: -7, type: 'public-key' },  // ES256
                { alg: -257, type: 'public-key' },  // RS256
            ],
            authenticatorSelection: {
                authenticatorAttachment: 'platform',
                userVerification: 'required',
                residentKey: 'preferred',
            },
            extensions: {
                prf: { eval: { first: PRF_SALT } },
            },
        },
    });

    if (!credential) throw new Error('Passkey creation cancelled');

    const ext = credential.getClientExtensionResults();
    if (!ext.prf || !ext.prf.enabled) {
        throw new Error('Your browser does not support the PRF extension needed for passkey encryption. This feature requires Chrome, Edge, or Safari. Firefox does not support it yet.');
    }

    return credential;
}

async function getPRFKey(credentialIdBytes) {
    const challenge = crypto.getRandomValues(new Uint8Array(32));

    const assertion = await navigator.credentials.get({
        publicKey: {
            challenge,
            allowCredentials: [{ type: 'public-key', id: credentialIdBytes }],
            userVerification: 'required',
            extensions: {
                prf: { eval: { first: PRF_SALT } },
            },
        },
    });

    if (!assertion) throw new Error('Passkey authentication cancelled');

    const ext = assertion.getClientExtensionResults();
    if (!ext.prf || !ext.prf.results || !ext.prf.results.first) {
        throw new Error('PRF result missing from passkey response');
    }

    // PRF output → 256-bit AES key
    const prfOutput = new Uint8Array(ext.prf.results.first);
    const hash = await crypto.subtle.digest('SHA-256', prfOutput);
    return new Uint8Array(hash);
}

// ── SeedVault singleton ───────────────────────────────────────────────────────

class SeedVault {
    constructor() {
        this._seed = null;          // in-memory plaintext seed (set after unlock)
        this._pwdKeyBytes = null;   // cached password-derived key (for re-encrypt on storeSeed)
        this._prfKeyBytes = null;   // cached PRF-derived key
        this._lastUnlockedAt = 0;   // ms timestamp; memory-only
        this._lastActivityAt = 0;
    }

    // ── Mode ──────────────────────────────────────────────────────────────────

    getMode() {
        const mode = Storage.load(KEY_MODE, null);
        if (mode && ['insecure', 'memory', 'password', 'passkey'].includes(mode)) {
            return mode;
        }
        // Backwards compat: if no mode saved but plaintext seed exists → insecure
        const raw = Storage.load(KEY_PLAINTEXT, '');
        if (raw) return 'insecure';
        return 'insecure';
    }

    // ── Read ──────────────────────────────────────────────────────────────────

    getSeed() {
        // If already unlocked, return from memory
        if (this._seed) return this._seed;

        // For insecure mode, auto-load from localStorage
        const mode = this.getMode();
        if (mode === 'insecure') {
            const raw = Storage.load(KEY_PLAINTEXT, '');
            if (raw) {
                this._seed = raw;
                return raw;
            }
        }

        // All other modes require explicit unlock
        return null;
    }

    isLocked() {
        if (this._seed) return false;
        const mode = this.getMode();
        if (mode === 'insecure') {
            // insecure auto-loads; if no seed exists user is simply logged out
            return false;
        }
        if (mode === 'memory') {
            // memory mode never persists; "locked" means needs re-login
            return false;
        }
        // password / passkey: locked until unlocked
        if (mode === 'password') {
            const blob = Storage.load(KEY_PWD_ENCRYPTED, null);
            return !!blob;
        }
        if (mode === 'passkey') {
            const blob = Storage.load(KEY_PRF_ENCRYPTED, null);
            return !!blob;
        }
        return false;
    }

    // ── Unlock ────────────────────────────────────────────────────────────────

    async unlock(secret) {
        const mode = this.getMode();

        if (mode === 'insecure') {
            this._seed = Storage.load(KEY_PLAINTEXT, '') || null;
            if (this._seed) this._touchUnlock();
            return !!this._seed;
        }

        if (mode === 'memory') {
            // Nothing to unlock — user must re-enter seed via login
            return false;
        }

        if (mode === 'password') {
            if (!secret) throw new Error('Password required');
            const blob = Storage.load(KEY_PWD_ENCRYPTED, null);
            if (!blob) throw new Error('No encrypted seed found');

            const { iv, salt, ciphertext } = blob;
            const saltBytes = new Uint8Array(fromBase64(salt));
            const keyBytes = await deriveKeyFromPassword(secret, saltBytes);

            try {
                this._seed = await decryptAESGCM(iv, ciphertext, keyBytes);
                this._pwdKeyBytes = keyBytes;
                this._touchUnlock();
                return true;
            } catch (_e) {
                throw new Error('Incorrect password');
            }
        }

        if (mode === 'passkey') {
            const blob = Storage.load(KEY_PRF_ENCRYPTED, null);
            if (!blob) throw new Error('No encrypted seed found');

            const credIdB64 = Storage.load(KEY_PRF_CRED_ID, null);
            if (!credIdB64) throw new Error('No passkey credential found');

            const credIdBytes = new Uint8Array(fromBase64(credIdB64));
            const keyBytes = await getPRFKey(credIdBytes);

            try {
                this._seed = await decryptAESGCM(blob.iv, blob.ciphertext, keyBytes);
                this._prfKeyBytes = keyBytes;
                this._touchUnlock();
                return true;
            } catch (_e) {
                throw new Error('Passkey decryption failed');
            }
        }

        return false;
    }

    // ── Store / switch modes ──────────────────────────────────────────────────

    async storeSeed(seed, mode, secret) {
        if (!seed) return;
        const normalized = requireValidMnemonic(seed);

        // CRITICAL: Build the new storage blob FIRST, then clear old formats.
        // This prevents seed loss if encryption throws — the old format stays untouched.

        if (mode === 'insecure') {
            this._clearAllStoredSeeds();
            Storage.save(KEY_PLAINTEXT, normalized);
            Storage.save(KEY_MODE, 'insecure');
            this._seed = normalized;
            this._touchUnlock();
            try { console.debug('[SeedVault] stored insecure'); } catch (_) { /* noop */ }
            return;
        }

        if (mode === 'memory') {
            this._clearAllStoredSeeds();
            // Don't persist the seed anywhere — only keep in memory
            Storage.save(KEY_MODE, 'memory');
            this._seed = normalized;
            this._touchUnlock();
            try { console.debug('[SeedVault] stored memory-only'); } catch (_) { /* noop */ }
            return;
        }

        if (mode === 'password') {
            let keyBytes;
            let newBlob;

            if (secret) {
                // New password — derive fresh key
                const salt = crypto.getRandomValues(new Uint8Array(16));
                keyBytes = await deriveKeyFromPassword(secret, salt);
                const encrypted = await encryptAESGCM(normalized, keyBytes);
                newBlob = {
                    iv: encrypted.iv,
                    salt: toBase64(salt),
                    ciphertext: encrypted.ciphertext,
                };
            } else if (this._pwdKeyBytes) {
                // Re-encrypt with the cached key (e.g. setCredentials called during session)
                keyBytes = this._pwdKeyBytes;
                const existingBlob = Storage.load(KEY_PWD_ENCRYPTED, null);
                const salt = existingBlob ? new Uint8Array(fromBase64(existingBlob.salt)) : crypto.getRandomValues(new Uint8Array(16));
                const encrypted = await encryptAESGCM(normalized, keyBytes);
                newBlob = {
                    iv: encrypted.iv,
                    salt: toBase64(salt),
                    ciphertext: encrypted.ciphertext,
                };
            } else {
                throw new Error('Password required for password mode');
            }

            // Encryption succeeded — now safe to clear old formats and write new
            this._clearAllStoredSeeds();
            Storage.save(KEY_PWD_ENCRYPTED, newBlob);
            Storage.save(KEY_MODE, 'password');
            this._seed = normalized;
            this._pwdKeyBytes = keyBytes;
            this._touchUnlock();
            try { console.debug('[SeedVault] stored password'); } catch (_) { /* noop */ }
            return;
        }

        if (mode === 'passkey') {
            // secret is the PRF key bytes (from registerPasskey), or use cached
            const keyBytes = secret || this._prfKeyBytes;
            if (!keyBytes) throw new Error('PRF key required for passkey mode');

            // Encrypt first, then clear old formats
            const encrypted = await encryptAESGCM(normalized, keyBytes);
            const newBlob = {
                iv: encrypted.iv,
                ciphertext: encrypted.ciphertext,
            };

            // Encryption succeeded — now safe to clear old formats and write new
            this._clearAllStoredSeeds();
            Storage.save(KEY_PRF_ENCRYPTED, newBlob);
            Storage.save(KEY_MODE, 'passkey');
            this._seed = normalized;
            this._prfKeyBytes = keyBytes;
            this._touchUnlock();
            try { console.debug('[SeedVault] stored passkey'); } catch (_) { /* noop */ }
            return;
        }

        throw new Error('Unknown seed storage mode: ' + mode);
    }

    _touchUnlock() {
        const now = Date.now();
        this._lastUnlockedAt = now;
        this._lastActivityAt = now;
    }

    touchActivity() {
        if (this._seed) this._lastActivityAt = Date.now();
    }

    getAutoLockMinutes() {
        const raw = Storage.load('vault_auto_lock_minutes', null);
        if (raw === 'off' || raw === 0 || raw === '0') return 0;
        const n = Number(raw);
        if ([5, 15, 30, 60].includes(n)) return n;
        // Default 15 for protected/memory; insecure never locks.
        return 15;
    }

    setAutoLockMinutes(minutes) {
        if (minutes === 'off' || minutes === 0) {
            Storage.save('vault_auto_lock_minutes', 'off');
            return;
        }
        const n = Number(minutes);
        if (![5, 15, 30, 60].includes(n)) throw new Error('invalid auto-lock minutes');
        Storage.save('vault_auto_lock_minutes', n);
    }

    /**
     * Lock protected/memory vaults after idle timeout. Plaintext mode never auto-locks.
     * @returns {boolean} true if locked
     */
    checkAutoLock() {
        const mode = this.getMode();
        if (mode === 'insecure') return false;
        if (!this._seed) return false;
        const mins = this.getAutoLockMinutes();
        if (!mins) return false;
        const idleMs = Date.now() - (this._lastActivityAt || this._lastUnlockedAt || 0);
        if (idleMs < mins * 60 * 1000) return false;
        try { console.debug('[SeedVault] auto-lock', { mode, idleMs, mins }); } catch (_) { /* noop */ }
        this.lock();
        return true;
    }

    /**
     * Whether storeSeed(seed, getMode(), null) can succeed. The protected modes
     * re-encrypt with a cached key, and lock() nulls it, so after a lock there is
     * no secret and the write would throw. Callers must pick a storable target
     * mode instead of leaving the session with no seed at all.
     */
    canStoreWithoutSecret() {
        const mode = this.getMode();
        if (mode === 'password') return !!this._pwdKeyBytes;
        if (mode === 'passkey') return !!this._prfKeyBytes;
        return true;
    }

    /**
     * Store a seed for a session that has just been established by login, using a
     * mode that can actually be written.
     *
     * The "sign in with recovery phrase instead" link locks the vault before
     * routing to /login, so a protected mode arrives here with no secret and no
     * cached key. Writing it anyway threw, which left the app rendering as signed
     * in with no seed: every signature failed and the unlock screen offered the
     * same broken link on reload. Falling back to memory keeps the session usable
     * and persists nothing, so it is not a downgrade to plaintext — but it does
     * not survive a refresh, which is why the caller warns the user to set the
     * vault up again.
     *
     * @returns {Promise<{ mode: string, requested: string }>}
     */
    async storeSeedForSession(seed) {
        const requested = this.getMode() || 'insecure';
        const mode = this.canStoreWithoutSecret() ? requested : 'memory';
        await this.storeSeed(seed, mode, null);
        return { mode, requested };
    }

    requireFreshUnlock(maxAgeMs = 60_000) {
        if (!this._seed) return false;
        if (!this._lastUnlockedAt) return false;
        return (Date.now() - this._lastUnlockedAt) <= maxAgeMs;
    }

    // ── Passkey registration ───────────────────────────────────────────────────

    async registerPasskey(seed) {
        const credential = await createPRFCredential();
        const credIdBytes = new Uint8Array(credential.rawId);

        // Save credential ID so we can use it for future unlocks
        Storage.save(KEY_PRF_CRED_ID, toBase64(credIdBytes));

        // Now get the PRF key by doing an assertion with the new credential
        const keyBytes = await getPRFKey(credIdBytes);

        // Encrypt and store
        await this.storeSeed(seed, 'passkey', keyBytes);
    }

    async unlockWithPasskey() {
        return this.unlock(null);   // passkey mode unlock doesn't need a secret param
    }

    // ── Lock / clear ──────────────────────────────────────────────────────────

    lock() {
        this._seed = null;
        this._pwdKeyBytes = null;
        this._prfKeyBytes = null;
    }

    clear() {
        this.lock();
        this._clearAllStoredSeeds();
        Storage.remove(KEY_MODE);
        Storage.remove(KEY_PRF_CRED_ID);
    }

    // ── Helpers ───────────────────────────────────────────────────────────────

    isPRFSupported() {
        return isPRFSupported();
    }

    _clearAllStoredSeeds() {
        Storage.remove(KEY_PLAINTEXT);
        Storage.remove(KEY_PWD_ENCRYPTED);
        Storage.remove(KEY_PRF_ENCRYPTED);
        // Don't remove KEY_PRF_CRED_ID here — it's needed if user switches back to passkey.
        // It gets removed in clear() (full sign-out).
    }
}

// Export singleton
const seedVault = new SeedVault();
export default seedVault;
